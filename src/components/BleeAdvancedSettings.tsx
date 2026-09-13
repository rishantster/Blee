'use client';

import { getActiveNetwork } from '../lib/networkConfig';

// Kept only for compatibility with older generated imports. BleeApp 2.4 owns
// the visible settings experience and intentionally does not expose custom
// networks or multi-asset controls.
export default function BleeAdvancedSettings() {
  const network = getActiveNetwork();
  return (
    <section aria-label="Blee settlement network">
      <strong>{network.name}</strong>
      <small>{network.tokenSymbol} · Chain {network.chainId}</small>
    </section>
  );
}
