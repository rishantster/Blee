const DIA_SOL_USD_URL = 'https://api.diadata.org/v1/assetQuotation/Solana/0x0000000000000000000000000000000000000000';
const PRICE_CACHE_MS = 120_000;
const REQUEST_TIMEOUT_MS = 6_000;

let cachedSolUsdPrice: { value: number; at: number } | null = null;
let inFlight: Promise<number> | null = null;

type DiaAssetQuotation = {
  Symbol?: string;
  Name?: string;
  Address?: string;
  Blockchain?: string;
  Price?: string | number;
  Time?: string;
  Source?: string;
};

/**
 * BLEE_MARKET_DATA_V3
 *
 * Presentation-only SOL/USD valuation fetched directly from DIA's public,
 * keyless Asset Quotation endpoint. This path does not require the Blee gateway
 * because no credential or privileged Solana RPC capability is involved.
 *
 * Operational SOL balance, signing, settlement, nonce management and payment
 * eligibility remain independently isolated behind the existing Blee Solana
 * gateway. Market price data can never authorize or alter a transaction.
 */
export async function getSolUsdPrice(): Promise<number> {
  const now = Date.now();
  if (cachedSolUsdPrice && now - cachedSolUsdPrice.at < PRICE_CACHE_MS) {
    return cachedSolUsdPrice.value;
  }
  if (inFlight) return inFlight;

  inFlight = (async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(DIA_SOL_USD_URL, {
        method: 'GET',
        headers: { accept: 'application/json' },
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`SOL price request failed (${response.status})`);

      const body = await response.json() as DiaAssetQuotation;
      if (body.Symbol && body.Symbol.toUpperCase() !== 'SOL') {
        throw new Error('SOL USD price response has wrong symbol');
      }
      if (body.Blockchain && body.Blockchain.toLowerCase() !== 'solana') {
        throw new Error('SOL USD price response has wrong blockchain');
      }

      const value = Number(body.Price);
      if (!Number.isFinite(value) || value <= 0) {
        throw new Error('SOL USD price is unavailable');
      }

      cachedSolUsdPrice = { value, at: Date.now() };
      return value;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error('SOL USD price request timed out');
      }
      throw error instanceof Error ? error : new Error('SOL USD price is unavailable');
    } finally {
      clearTimeout(timeout);
      inFlight = null;
    }
  })();

  return inFlight;
}
