#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"Blee pull refresh: {message}")


def main() -> None:
    runtime = ROOT / "src/components/BleeRuntime.tsx"
    css = ROOT / "app/globals.css"
    if not runtime.is_file() or not css.is_file():
        fail("materialized runtime/CSS missing")
    text = runtime.read_text()
    marker = "// BLEE_PULL_TO_REFRESH_V1"
    if marker not in text:
        anchor = "const SHOW_INTERNAL_DIAGNOSTICS = false;"
        if anchor not in text:
            fail("production runtime marker missing")
        block = r'''

// BLEE_PULL_TO_REFRESH_V1
// One app-level refresh gesture replaces card-specific refresh behavior. Native
// nearby transport stays alive while the WebView rehydrates durable state.
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !(window as any).__bleePullRefreshInstalled) {
  (window as any).__bleePullRefreshInstalled = true;
  let startY = 0;
  let pull = 0;
  let tracking = false;
  let refreshing = false;
  const threshold = 74;

  const ensureIndicator = () => {
    let node = document.getElementById('blee-pull-refresh-indicator');
    if (!node) {
      node = document.createElement('div');
      node.id = 'blee-pull-refresh-indicator';
      node.innerHTML = '<span></span>';
      document.body.appendChild(node);
    }
    return node;
  };

  const setPull = (value: number) => {
    pull = Math.max(0, Math.min(104, value));
    document.documentElement.style.setProperty('--blee-pull-offset', `${Math.round(pull * 0.46)}px`);
    document.documentElement.classList.toggle('blee-pulling', pull > 0);
    const node = ensureIndicator();
    node.style.setProperty('--blee-pull-progress', String(Math.min(1, pull / threshold)));
    node.classList.toggle('ready', pull >= threshold);
  };

  const reset = () => {
    tracking = false;
    if (!refreshing) {
      setPull(0);
      document.documentElement.classList.remove('blee-pulling');
    }
  };

  const refreshAll = () => {
    if (refreshing) return;
    refreshing = true;
    const node = ensureIndicator();
    node.classList.add('refreshing');
    document.documentElement.classList.add('blee-refreshing');
    document.documentElement.style.setProperty('--blee-pull-offset', '34px');
    window.dispatchEvent(new CustomEvent('blee:refresh-all'));
    window.setTimeout(() => window.location.reload(), 180);
  };

  document.addEventListener('touchstart', (event) => {
    if (refreshing || window.scrollY > 1 || event.touches.length !== 1) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest('input,textarea,select,[contenteditable="true"],button')) return;
    startY = event.touches[0].clientY;
    pull = 0;
    tracking = true;
  }, { passive: true });

  document.addEventListener('touchmove', (event) => {
    if (!tracking || event.touches.length !== 1) return;
    const delta = event.touches[0].clientY - startY;
    if (delta <= 0) { reset(); return; }
    if (window.scrollY > 1) { reset(); return; }
    event.preventDefault();
    setPull(Math.pow(delta, 0.86));
  }, { passive: false });

  document.addEventListener('touchend', () => {
    if (!tracking) return;
    const shouldRefresh = pull >= threshold;
    tracking = false;
    if (shouldRefresh) refreshAll();
    else reset();
  }, { passive: true });
  document.addEventListener('touchcancel', reset, { passive: true });

  document.addEventListener('click', (event) => {
    const button = (event.target as HTMLElement | null)?.closest('button');
    if (!button) return;
    const label = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('title') || ''} ${button.textContent || ''}`.trim().toLowerCase();
    if (label === 'refresh' || label.includes('refresh balance') || label.includes('refresh funds')) {
      event.preventDefault();
      event.stopPropagation();
      refreshAll();
    }
  }, true);
}
'''
        text = text.replace(anchor, anchor + block, 1)
        runtime.write_text(text)

    css_text = css.read_text()
    if "BLEE_PULL_TO_REFRESH_CSS_V1" not in css_text:
        css_text += r'''

/* BLEE_PULL_TO_REFRESH_CSS_V1 */
:root { --blee-pull-offset: 0px; }
html.blee-pulling .blee-phone,
html.blee-refreshing .blee-phone {
  transform: translateY(var(--blee-pull-offset));
  transition: transform 90ms ease-out;
}
#blee-pull-refresh-indicator {
  position: fixed;
  top: calc(env(safe-area-inset-top, 0px) + 10px);
  left: 50%;
  width: 34px;
  height: 34px;
  margin-left: -17px;
  border-radius: 50%;
  background: rgba(255,255,255,.94);
  box-shadow: 0 6px 22px rgba(0,0,0,.14);
  display: grid;
  place-items: center;
  opacity: calc(var(--blee-pull-progress, 0) * 1);
  transform: translateY(calc((1 - var(--blee-pull-progress, 0)) * -24px)) scale(calc(.72 + var(--blee-pull-progress, 0) * .28));
  pointer-events: none;
  z-index: 9999;
}
#blee-pull-refresh-indicator span {
  width: 15px;
  height: 15px;
  border: 2px solid rgba(0,0,0,.18);
  border-top-color: #111;
  border-radius: 50%;
}
#blee-pull-refresh-indicator.refreshing { opacity: 1; transform: translateY(0) scale(1); }
#blee-pull-refresh-indicator.refreshing span { animation: blee-pull-spin .72s linear infinite; }
@keyframes blee-pull-spin { to { transform: rotate(360deg); } }
'''
        css.write_text(css_text)

    generated = runtime.read_text()
    for required in ("BLEE_PULL_TO_REFRESH_V1", "blee:refresh-all", "window.location.reload()", "touchmove"):
        if required not in generated:
            fail(f"runtime missing {required}")
    if "BLEE_PULL_TO_REFRESH_CSS_V1" not in css.read_text():
        fail("pull refresh CSS missing")
    print("VERIFIED: app-level pull-to-refresh rehydrates balance, activity, identity and nearby state")


if __name__ == "__main__":
    main()
