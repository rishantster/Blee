#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee soft refresh v2: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def patch_native_refresh() -> None:
    path = locate("BleeMeshPlugin.java")
    text = path.read_text()
    if "BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2" in text:
        return

    anchor = "    @PluginMethod\n    public void status(PluginCall call) {"
    if anchor not in text:
        fail("BleeMeshPlugin status() anchor missing")

    method = r'''    // BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2
    // Refresh is deliberately a state re-query, never a logout, vault reset or
    // WebView restart. Existing listeners already know how to rebuild UI state
    // when ACTION_LEDGER_CHANGED is emitted.
    @PluginMethod
    public void manualRefresh(PluginCall call) {
        try {
            BleeMeshService.start(getContext());

            Intent refresh = new Intent(BleeMeshService.ACTION_LEDGER_CHANGED);
            refresh.setPackage(getContext().getPackageName());
            refresh.putExtra(BleeMeshService.EXTRA_PAYMENT_ID, "");
            refresh.putExtra(BleeMeshService.EXTRA_EVENT_TYPE, "MANUAL_REFRESH");
            getContext().sendBroadcast(refresh);

            JSObject result = new JSObject();
            result.put("refreshed", true);
            result.put("running", BleeMeshService.running);
            result.put("peerCount", BleeMeshService.nearbyPeersSnapshot().size());
            result.put("at", System.currentTimeMillis());
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to refresh Blee state: " + error.getMessage());
        }
    }

'''
    text = text.replace(anchor, method + anchor, 1)
    path.write_text(text)


def patch_runtime_native_bridge() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        fail("materialized BleeRuntime.tsx missing")
    text = path.read_text()
    if "BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2" in text:
        return

    anchor = "const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');"
    if anchor not in text:
        fail("BleeMesh runtime registration anchor missing")

    bridge = r'''

// BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2
// Pull-to-refresh must never reload the WebView because the unlocked vault
// session is intentionally memory-resident. Re-query native/durable state in
// place and wake the same projection paths used for real ledger/peer events.
if (typeof window !== 'undefined' && !(window as any).__bleeSoftRefreshNativeInstalled) {
  (window as any).__bleeSoftRefreshNativeInstalled = true;
  window.addEventListener('blee:refresh-all', () => {
    void (async () => {
      try { await (BleeMesh as any).manualRefresh?.(); } catch {}
      try {
        const snapshot = await (BleeMesh as any).nearbyPeers?.();
        const peers = Array.isArray(snapshot?.peers) ? snapshot.peers : [];
        (window as any).__bleeMeshPeers = peers;
        window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers } }));
      } catch {}
      try { await (BleeMesh as any).pendingEnvelopes?.(); } catch {}

      // Existing app hooks use these lifecycle signals for network balance,
      // settlement receipt and persisted-state reconciliation. They are safe
      // because the document itself is not replaced.
      try { window.dispatchEvent(new Event('focus')); } catch {}
      try { window.dispatchEvent(new Event('online')); } catch {}
      try { window.dispatchEvent(new Event('pageshow')); } catch {}
      try { document.dispatchEvent(new Event('visibilitychange')); } catch {}
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent('blee:refresh-complete'));
      }, 520);
    })();
  });
}
'''
    text = text.replace(anchor, anchor + bridge, 1)
    path.write_text(text)


def patch_web_refresh() -> None:
    runtime = ROOT / "src/components/BleeRuntime.tsx"
    css = ROOT / "app/globals.css"
    if not runtime.is_file() or not css.is_file():
        fail("materialized runtime/CSS missing")

    text = runtime.read_text()

    # Remove the previous V1 global block completely when present. It contained
    # window.location.reload(), which destroys the in-memory unlocked session.
    start_marker = "// BLEE_PULL_TO_REFRESH_V1"
    start = text.find(start_marker)
    if start >= 0:
        # The old block ends immediately before the next top-level declaration or
        # comment. Find the known diagnostics/runtime function boundary safely.
        candidates = [
            text.find("\nfunction ", start + len(start_marker)),
            text.find("\nexport ", start + len(start_marker)),
            text.find("\nconst ", start + len(start_marker)),
            text.find("\ninterface ", start + len(start_marker)),
        ]
        candidates = [x for x in candidates if x > start]
        if candidates:
            end = min(candidates)
            block = text[start:end]
            if "window.location.reload" in block or "blee-pull-refresh-indicator" in block:
                text = text[:start] + text[end:]

    if "BLEE_SOFT_REFRESH_V2" not in text:
        anchor = "const SHOW_INTERNAL_DIAGNOSTICS = false;"
        if anchor not in text:
            fail("production runtime marker missing")

        block = r'''

// BLEE_SOFT_REFRESH_V2
// Native-style pull-to-refresh. The WebView and unlocked wallet session stay
// alive; only application data/projections are re-queried.
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !(window as any).__bleeSoftRefreshInstalled) {
  (window as any).__bleeSoftRefreshInstalled = true;
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

  const ensureRefreshSplash = () => {
    let node = document.getElementById('blee-refresh-splash');
    if (!node) {
      node = document.createElement('div');
      node.id = 'blee-refresh-splash';
      node.innerHTML = '<div class="blee-refresh-mark"><img src="/brand/blee-logo.svg" alt="" /></div>';
      document.body.appendChild(node);
    }
    return node;
  };

  const playSoftSwish = () => {
    try {
      const AudioContextCtor = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!AudioContextCtor) return;
      const ctx = new AudioContextCtor();
      const duration = 0.38;
      const frames = Math.max(1, Math.floor(ctx.sampleRate * duration));
      const buffer = ctx.createBuffer(1, frames, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < frames; i += 1) {
        const t = i / frames;
        const envelope = Math.sin(Math.PI * t) * (1 - t * 0.34);
        data[i] = (Math.random() * 2 - 1) * envelope * 0.18;
      }
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      const filter = ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.Q.value = 0.72;
      filter.frequency.setValueAtTime(420, ctx.currentTime);
      filter.frequency.exponentialRampToValueAtTime(1900, ctx.currentTime + duration * 0.55);
      filter.frequency.exponentialRampToValueAtTime(760, ctx.currentTime + duration);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.07);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
      source.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);
      source.start();
      source.stop(ctx.currentTime + duration);
      window.setTimeout(() => { try { void ctx.close(); } catch {} }, 650);
    } catch {}
  };

  const setPull = (value: number) => {
    pull = Math.max(0, Math.min(104, value));
    document.documentElement.style.setProperty('--blee-pull-offset', `${Math.round(pull * 0.46)}px`);
    document.documentElement.classList.toggle('blee-pulling', pull > 0);
    const node = ensureIndicator();
    node.style.setProperty('--blee-pull-progress', String(Math.min(1, pull / threshold)));
    node.classList.toggle('ready', pull >= threshold);
  };

  const resetPull = () => {
    tracking = false;
    if (!refreshing) {
      setPull(0);
      document.documentElement.classList.remove('blee-pulling');
    }
  };

  const finishRefresh = () => {
    if (!refreshing) return;
    refreshing = false;
    ensureIndicator().classList.remove('refreshing');
    ensureRefreshSplash().classList.remove('visible');
    document.documentElement.classList.remove('blee-refreshing');
    document.documentElement.style.setProperty('--blee-pull-offset', '0px');
    setPull(0);
  };

  const refreshAll = () => {
    if (refreshing) return;
    refreshing = true;
    const indicator = ensureIndicator();
    const splash = ensureRefreshSplash();
    indicator.classList.add('refreshing');
    splash.classList.remove('visible');
    // restart CSS animation even for rapid consecutive refreshes
    void splash.offsetWidth;
    splash.classList.add('visible');
    document.documentElement.classList.add('blee-refreshing');
    document.documentElement.style.setProperty('--blee-pull-offset', '24px');
    playSoftSwish();
    window.dispatchEvent(new CustomEvent('blee:refresh-all', { detail: { source: 'gesture' } }));
    window.setTimeout(finishRefresh, 920);
  };

  window.addEventListener('blee:refresh-complete', () => {
    // Keep the branded animation visible long enough to feel deliberate rather
    // than flash, but finish promptly once all projections have been woken.
    window.setTimeout(finishRefresh, 260);
  });

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
    if (delta <= 0) { resetPull(); return; }
    if (window.scrollY > 1) { resetPull(); return; }
    event.preventDefault();
    setPull(Math.pow(delta, 0.86));
  }, { passive: false });

  document.addEventListener('touchend', () => {
    if (!tracking) return;
    const shouldRefresh = pull >= threshold;
    tracking = false;
    if (shouldRefresh) refreshAll();
    else resetPull();
  }, { passive: true });
  document.addEventListener('touchcancel', resetPull, { passive: true });

  // The legacy funds-card refresh control now drives the exact same complete,
  // non-destructive refresh instead of owning a separate/stale balance path.
  document.addEventListener('click', (event) => {
    const button = (event.target as HTMLElement | null)?.closest('button');
    if (!button) return;
    if (button.closest('#blee-refresh-splash')) return;
    const label = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('title') || ''} ${button.textContent || ''}`.trim().toLowerCase();
    if (label === 'refresh' || label.includes('refresh balance') || label.includes('refresh funds') || label.includes('refresh wallet')) {
      event.preventDefault();
      event.stopPropagation();
      refreshAll();
    }
  }, true);
}
'''
        text = text.replace(anchor, anchor + block, 1)

    # Absolute guard: no refresh patch may ever reload the document again.
    if "window.location.reload" in text:
        text = text.replace("window.location.reload()", "window.dispatchEvent(new CustomEvent('blee:refresh-all'))")
        text = text.replace("window.location.reload();", "window.dispatchEvent(new CustomEvent('blee:refresh-all'));")

    runtime.write_text(text)

    css_text = css.read_text()
    # Remove/neutralize old V1 CSS marker only by appending stronger V2 rules.
    if "BLEE_SOFT_REFRESH_CSS_V2" not in css_text:
        css_text += r'''

/* BLEE_SOFT_REFRESH_CSS_V2 */
:root { --blee-pull-offset: 0px; }
html.blee-pulling .blee-phone,
html.blee-refreshing .blee-phone {
  transform: translateY(var(--blee-pull-offset));
  transition: transform 110ms cubic-bezier(.22,.8,.25,1);
}
#blee-pull-refresh-indicator {
  position: fixed;
  top: calc(env(safe-area-inset-top, 0px) + 11px);
  left: 50%;
  width: 32px;
  height: 32px;
  margin-left: -16px;
  border-radius: 50%;
  background: rgba(255,255,255,.95);
  box-shadow: 0 7px 24px rgba(0,0,0,.12);
  display: grid;
  place-items: center;
  opacity: calc(var(--blee-pull-progress, 0) * 1);
  transform: translateY(calc((1 - var(--blee-pull-progress, 0)) * -24px)) scale(calc(.74 + var(--blee-pull-progress, 0) * .26));
  pointer-events: none;
  z-index: 10001;
}
#blee-pull-refresh-indicator span {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(0,0,0,.16);
  border-top-color: #111;
  border-radius: 50%;
}
#blee-pull-refresh-indicator.refreshing { opacity: 1; transform: translateY(0) scale(1); }
#blee-pull-refresh-indicator.refreshing span { animation: blee-pull-spin .68s linear infinite; }
@keyframes blee-pull-spin { to { transform: rotate(360deg); } }

#blee-refresh-splash {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  pointer-events: none;
  opacity: 0;
  background: rgba(248,248,246,.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  transition: opacity 180ms ease;
}
#blee-refresh-splash.visible { opacity: 1; }
#blee-refresh-splash .blee-refresh-mark {
  width: 58px;
  height: 78px;
  display: grid;
  place-items: center;
  opacity: 0;
  filter: blur(7px);
  transform: translateY(10px) scale(.82);
}
#blee-refresh-splash.visible .blee-refresh-mark {
  animation: blee-refresh-logo 760ms cubic-bezier(.16,.88,.24,1) both;
}
#blee-refresh-splash img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
@keyframes blee-refresh-logo {
  0% { opacity: 0; filter: blur(7px); transform: translateY(11px) scale(.82); }
  35% { opacity: 1; filter: blur(0); transform: translateY(0) scale(1.035); }
  72% { opacity: 1; filter: blur(0); transform: translateY(0) scale(1); }
  100% { opacity: 0; filter: blur(2px); transform: translateY(-5px) scale(.97); }
}
'''
        css.write_text(css_text)


def verify() -> None:
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    css = (ROOT / "app/globals.css").read_text()

    if "window.location.reload" in runtime:
        fail("destructive WebView reload remains in refresh path")
    for marker in (
        "BLEE_SOFT_REFRESH_V2",
        "BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2",
        "blee:refresh-all",
        "blee:refresh-complete",
        "playSoftSwish",
        "/brand/blee-logo.svg",
        "pendingEnvelopes",
        "nearbyPeers",
        "new Event('focus')",
        "new Event('online')",
    ):
        if marker not in runtime:
            fail(f"runtime missing {marker}")
    for marker in (
        "BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2",
        "MANUAL_REFRESH",
        "BleeMeshService.start(getContext())",
        "ACTION_LEDGER_CHANGED",
    ):
        if marker not in plugin:
            fail(f"native refresh bridge missing {marker}")
    for marker in ("BLEE_SOFT_REFRESH_CSS_V2", "blee-refresh-logo", "#blee-refresh-splash"):
        if marker not in css:
            fail(f"refresh styling missing {marker}")

    print("============================================================")
    print("VERIFIED: Blee non-destructive refresh v2")
    print("- pull gesture and funds-card refresh use the same full refresh path")
    print("- WebView/vault session is never reloaded or logged out")
    print("- native ledger, pending envelopes, nearby peers and lifecycle projections wake")
    print("- Blee logo animation + soft synthesized swish are shown during refresh")
    print("============================================================")


def main() -> None:
    patch_native_refresh()
    patch_runtime_native_bridge()
    patch_web_refresh()
    verify()


if __name__ == "__main__":
    main()
