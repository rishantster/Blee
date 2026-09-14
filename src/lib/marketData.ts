import { BLEE_SOLANA_GATEWAY } from './solanaGateway';

const PRICE_CACHE_MS = 60_000;
const REQUEST_TIMEOUT_MS = 5_000;

let cachedSolUsdPrice: { value: number; at: number } | null = null;
let inFlight: Promise<number> | null = null;

type SolUsdMarketResponse = {
  symbol?: string;
  quote?: string;
  price?: string | number;
  asOf?: string | number;
};

/**
 * BLEE_MARKET_DATA_V2
 *
 * Presentation-only SOL/USD valuation. This never participates in signing,
 * settlement, nonce management, balance accounting or payment eligibility.
 * The APK talks only to the public Blee gateway boundary; provider selection,
 * credentials, caching and rate limits belong server-side. Operational SOL
 * balance remains independently sourced by the Solana wallet view.
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
      const response = await fetch(`${BLEE_SOLANA_GATEWAY}/v1/market/sol-usd`, {
        method: 'GET',
        headers: { accept: 'application/json' },
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`SOL price request failed (${response.status})`);
      const body = await response.json() as SolUsdMarketResponse;
      if (body.symbol && body.symbol !== 'SOL') throw new Error('SOL USD price response has wrong symbol');
      if (body.quote && body.quote !== 'USD') throw new Error('SOL USD price response has wrong quote');
      const value = Number(body.price);
      if (!Number.isFinite(value) || value <= 0) throw new Error('SOL USD price is unavailable');
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
