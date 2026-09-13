#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"Blee stability freeze v1: {message}")


def find_block_end(text: str, brace: int) -> int:
    depth = 0
    quote = None
    escape = False
    line_comment = False
    block_comment = False
    i = brace
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ''
        if line_comment:
            if ch == '\n':
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == '*' and nxt == '/':
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch == '/' and nxt == '/':
            line_comment = True
            i += 2
            continue
        if ch == '/' and nxt == '*':
            block_comment = True
            i += 2
            continue
        if ch in ('\'', '"', '`'):
            quote = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    fail("unterminated runtime block")
    return -1


def remove_contacts_runtime_ui(text: str) -> str:
    marker = "// BLEE_CONTACTS_ACTIVITY_UI_V1"
    start = text.find(marker)
    if start < 0:
        return text
    if_start = text.find("if (", start)
    if if_start < 0:
        fail("contacts runtime marker exists without global if block")
    brace = text.find('{', if_start)
    if brace < 0:
        fail("contacts runtime if opening brace missing")
    end = find_block_end(text, brace)
    return text[:start] + "// BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1\n" + text[end:]


def remove_contacts_css(text: str) -> str:
    marker = "/* BLEE_CONTACTS_ACTIVITY_CSS_V1 */"
    start = text.find(marker)
    if start < 0:
        return text
    next_marker = text.find("\n/* BLEE_", start + len(marker))
    if next_marker < 0:
        end = len(text)
    else:
        end = next_marker
    return text[:start].rstrip() + "\n\n/* BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1 */\n" + text[end:].lstrip()


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        fail("materialized BleeRuntime.tsx missing")
    text = path.read_text()
    text = remove_contacts_runtime_ui(text)

    # Canonicalize transport-side wallet identity before it enters the React
    # cache. EVM address comparison is case-insensitive, so rendering one stable
    # lowercase representation prevents mixed-case/lowercase identity churn.
    if "BLEE_CANONICAL_WALLET_CASE_V1" not in text:
        anchor = "const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');"
        if anchor not in text:
            fail("BleeMesh registration anchor missing")
        helper = r'''

// BLEE_CANONICAL_WALLET_CASE_V1
const bleeCanonicalWallet = (value: unknown) => {
  const raw = String(value || '').trim();
  return /^0x[0-9a-fA-F]{40}$/.test(raw) ? raw.toLowerCase() : raw;
};
'''
        text = text.replace(anchor, anchor + helper, 1)

    text = text.replace("wallet: event.wallet,", "wallet: bleeCanonicalWallet(event.wallet),")

    # Presentational guard for own-wallet/profile text that may still be sourced
    # from a checksummed viem account while native persistence is lowercase.
    # This mutates text only; it never changes payment/signing values.
    if "BLEE_CANONICAL_WALLET_TEXT_V1" not in text:
        gate = "const SHOW_INTERNAL_DIAGNOSTICS = false;"
        if gate not in text:
            fail("production diagnostics gate missing")
        normalizer = r'''

// BLEE_CANONICAL_WALLET_TEXT_V1
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !(window as any).__bleeWalletCaseNormalizerInstalled) {
  (window as any).__bleeWalletCaseNormalizerInstalled = true;
  let queued = false;
  const normalizeWalletText = () => {
    queued = false;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const updates: Array<[Text, string]> = [];
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      const value = node.nodeValue || '';
      if (!/0x[0-9a-fA-F]{40}/.test(value)) continue;
      const next = value.replace(/0x[0-9a-fA-F]{40}/g, (address) => address.toLowerCase());
      if (next !== value) updates.push([node, next]);
    }
    for (const [node, next] of updates) node.nodeValue = next;
  };
  const queueWalletTextNormalization = () => {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(normalizeWalletText);
  };
  const observer = new MutationObserver(queueWalletTextNormalization);
  window.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    queueWalletTextNormalization();
  }, { once: true });
  if (document.readyState !== 'loading') {
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    queueWalletTextNormalization();
  }
}
'''
        text = text.replace(gate, gate + normalizer, 1)

    path.write_text(text)


def patch_hook() -> None:
    path = ROOT / "src/hooks/useBlee.ts"
    if not path.is_file():
        fail("materialized useBlee.ts missing")
    text = path.read_text()

    # Native peer projection already treats wallet as identity; force the stored
    # value itself to the same representation instead of only lowercasing map keys.
    text = text.replace(
        "wallet: String(raw.wallet || ''),",
        "wallet: String(raw.wallet || '').toLowerCase(),",
    )
    text = text.replace(
        "wallet: String(raw.wallet || raw.walletAddress || raw.address || ''),",
        "wallet: String(raw.wallet || raw.walletAddress || raw.address || '').toLowerCase(),",
    )
    path.write_text(text)


def patch_css() -> None:
    path = ROOT / "app/globals.css"
    if not path.is_file():
        fail("materialized globals.css missing")
    text = remove_contacts_css(path.read_text())
    if "BLEE_STABLE_SEND_RECIPIENT_ACTION_V1" not in text:
        text = text.rstrip() + r'''

/* BLEE_STABLE_SEND_RECIPIENT_ACTION_V1 */
/* Send Recipient owns one trailing action only: the QR scanner. */
.blee-recipient-input-shell > button:not(.blee-recipient-qr-icon) { display: none !important; }
.blee-recipient-input-shell .blee-recipient-qr-icon { z-index: 4; }
'''
    path.write_text(text)


def verify() -> None:
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    hook = (ROOT / "src/hooks/useBlee.ts").read_text()
    css = (ROOT / "app/globals.css").read_text()

    forbidden = (
        "BLEE_CONTACTS_ACTIVITY_UI_V1",
        "blee-activity-contact-tools",
        "blee-activity-filter-button",
        "blee-activity-contacts-button",
        "#blee-contact-sheet",
    )
    combined = runtime + "\n" + css
    for marker in forbidden:
        if marker in combined:
            fail(f"unstable injected Activity UI survived: {marker}")

    for marker in (
        "BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1",
        "BLEE_CANONICAL_WALLET_CASE_V1",
        "BLEE_CANONICAL_WALLET_TEXT_V1",
        "bleeCanonicalWallet(event.wallet)",
    ):
        if marker not in runtime:
            fail(f"runtime missing {marker}")

    if "BLEE_STABLE_SEND_RECIPIENT_ACTION_V1" not in css:
        fail("stable Send recipient action rule missing")

    # Contacts data/plugin remain intentionally available for a later proper
    # React implementation; only the brittle runtime DOM UI is disabled.
    print("============================================================")
    print("VERIFIED: Blee stability freeze v1")
    print("- injected Contacts/Activity DOM controls are disabled")
    print("- Home no longer receives contact/filter controls")
    print("- broken Activity top-right injected buttons are removed")
    print("- wallet identity uses one canonical lowercase presentation")
    print("- Send Recipient keeps QR as the only trailing action")
    print("============================================================")


def main() -> None:
    patch_runtime()
    patch_hook()
    patch_css()
    verify()


if __name__ == "__main__":
    main()
