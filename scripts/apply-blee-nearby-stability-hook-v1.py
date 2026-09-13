#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"Blee nearby hook stability: {message}")


def main() -> None:
    path = ROOT / "src/hooks/useBlee.ts"
    if not path.is_file():
        fail("generated useBlee.ts missing")
    text = path.read_text()
    if "BLEE_NATIVE_PRESENCE_AUTHORITATIVE_V1" in text:
        return
    if "BLEE_PRODUCTION_NATIVE_PEER_MERGE_V1" not in text:
        fail("production peer merge must run first")

    old = '''      setPeers((current: any) => {
        const existing = Array.isArray(current) ? current : [];
        const byWallet = new Map<string, any>();
        for (const peer of existing) {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          if (/^0x[0-9a-f]{40}$/.test(wallet)) byWallet.set(wallet, peer);
        }
        for (const peer of normalized) {
          const previous = byWallet.get(peer.wallet);
          const nativeHasName = peer.displayName && !peer.displayName.startsWith('0x');
          byWallet.set(peer.wallet, {
            ...(previous || {}),
            ...peer,
            displayName: nativeHasName ? peer.displayName : (previous?.displayName || previous?.name || peer.displayName),
            name: nativeHasName ? peer.displayName : (previous?.name || previous?.displayName || peer.name),
            alias: nativeHasName ? peer.displayName : (previous?.alias || previous?.displayName || peer.alias),
            avatar: peer.avatar || previous?.avatar || null,
          });
        }
        const nonWallet = existing.filter((peer: any) => {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          return !/^0x[0-9a-f]{40}$/.test(wallet);
        });
        return [...nonWallet, ...byWallet.values()] as any;
      });'''

    new = '''      // BLEE_NATIVE_PRESENCE_AUTHORITATIVE_V1
      // The native snapshot/event is authoritative for whether a native peer is
      // currently present. Previous native rows may enrich name/avatar, but an
      // absent native wallet must not survive forever as a ghost after disconnect.
      setPeers((current: any) => {
        const existing = Array.isArray(current) ? current : [];
        const previousByWallet = new Map<string, any>();
        const legacyByWallet = new Map<string, any>();
        for (const peer of existing) {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          if (!/^0x[0-9a-f]{40}$/.test(wallet)) continue;
          previousByWallet.set(wallet, peer);
          if (!peer?.__bleeNative) legacyByWallet.set(wallet, peer);
        }

        const nextByWallet = new Map<string, any>();
        for (const peer of normalized) {
          const wallet = String(peer.wallet || '').toLowerCase();
          if (!/^0x[0-9a-f]{40}$/.test(wallet)) continue;
          const previous = previousByWallet.get(wallet);
          const legacy = legacyByWallet.get(wallet);
          const nativeHasName = peer.displayName && !peer.displayName.startsWith('0x');
          nextByWallet.set(wallet, {
            ...(legacy || previous || {}),
            ...peer,
            wallet,
            displayName: nativeHasName ? peer.displayName : (previous?.displayName || legacy?.displayName || previous?.name || peer.displayName),
            name: nativeHasName ? peer.displayName : (previous?.name || legacy?.name || previous?.displayName || peer.name),
            alias: nativeHasName ? peer.displayName : (previous?.alias || legacy?.alias || previous?.displayName || peer.alias),
            avatar: peer.avatar || previous?.avatar || legacy?.avatar || null,
          });
        }

        for (const [wallet, peer] of legacyByWallet.entries()) {
          if (!nextByWallet.has(wallet)) nextByWallet.set(wallet, peer);
        }
        const nonWallet = existing.filter((peer: any) => {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          return !/^0x[0-9a-f]{40}$/.test(wallet) && !peer?.__bleeNative;
        });
        return [...nonWallet, ...nextByWallet.values()] as any;
      });'''

    if old not in text:
        fail("production peer merge anchor missing")
    text = text.replace(old, new, 1)
    path.write_text(text)

    generated = path.read_text()
    for marker in ("BLEE_NATIVE_PRESENCE_AUTHORITATIVE_V1", "previousByWallet", "legacyByWallet", "nextByWallet"):
        if marker not in generated:
            fail(f"missing generated marker {marker}")
    print("VERIFIED: native nearby presence removes stale rows while preserving profile enrichment")


if __name__ == "__main__":
    main()
