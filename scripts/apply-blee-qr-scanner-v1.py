#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"Blee QR scanner: {message}")


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        fail(f"missing {label} anchor")
    return text.replace(old, new, 1)


def patch_register_plugin_import(text: str) -> str:
    if re.search(r"\bregisterPlugin\b", text):
        return text
    match = re.search(r"import\s*\{(?P<body>[^}]*)\}\s*from\s*['\"]@capacitor/core['\"]\s*;?", text, re.S)
    if match:
        body = match.group("body").strip()
        replacement = match.group(0).replace("{" + match.group("body") + "}", "{ " + body.rstrip() + (", " if body else "") + "registerPlugin }")
        return text[:match.start()] + replacement + text[match.end():]
    imports = list(re.finditer(r"(?m)^import\s.+?;\s*$", text))
    if not imports:
        fail("BleeApp has no import block")
    pos = imports[-1].end()
    return text[:pos] + "\nimport { registerPlugin } from '@capacitor/core';" + text[pos:]


def scanner_module_block() -> str:
    return r'''

// BLEE_SEND_QR_SCANNER_V1
interface BleeQrScannerPlugin {
  scan(): Promise<{ value?: string; cancelled?: boolean }>;
}

const BleeQrScanner = registerPlugin<BleeQrScannerPlugin>('BleeQrScanner');

function parseBleeRecipientQr(rawValue: string): string {
  const raw = String(rawValue || '').trim();
  const address = (value: unknown) => {
    const candidate = String(value || '').trim();
    const direct = candidate.match(/^0x[0-9a-fA-F]{40}$/);
    if (direct) return direct[0];
    const embedded = candidate.match(/0x[0-9a-fA-F]{40}/);
    return embedded ? embedded[0] : '';
  };

  const direct = address(raw);
  if (direct && /^0x[0-9a-fA-F]{40}$/.test(raw)) return direct;

  try {
    const parsed = JSON.parse(raw);
    for (const key of ['wallet', 'address', 'recipient', 'to', 'walletAddress']) {
      const candidate = address(parsed?.[key]);
      if (candidate) return candidate;
    }
  } catch {}

  try {
    const normalized = raw.replace(/^ethereum:/i, 'blee://pay/');
    const url = new URL(normalized);
    for (const key of ['to', 'address', 'wallet', 'recipient']) {
      const candidate = address(url.searchParams.get(key));
      if (candidate) return candidate;
    }
    const candidate = address(url.pathname) || address(url.hostname);
    if (candidate) return candidate;
  } catch {}

  const embedded = address(raw);
  if (embedded && /^(?:blee:|ethereum:|https?:)/i.test(raw)) return embedded;
  throw new Error('This QR code does not contain a valid Blee recipient address.');
}
'''


def recipient_input_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    input_start = text.find("<input", start, end)
    if input_start < 0:
        fail("Recipient input not found")
    # React input elements are self-closing in the production Blee UI. Prefer />
    # because arrow handlers contain the '>' character in '=>'.
    close = text.find("/>", input_start, end)
    if close >= 0:
        return input_start, close + 2
    # Defensive fallback: scan until a tag-closing > that is outside quotes and
    # JSX brace expressions rather than stopping on an arrow function.
    quote = None
    brace_depth = 0
    for i in range(input_start + 6, end):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch == "{":
            brace_depth += 1
            continue
        if ch == "}" and brace_depth:
            brace_depth -= 1
            continue
        if ch == ">" and brace_depth == 0:
            return input_start, i + 1
    fail("Recipient input tag is unterminated")


def patch_web() -> None:
    app = ROOT / "src/components/BleeApp.tsx"
    css = ROOT / "app/globals.css"
    if not app.is_file() or not css.is_file():
        fail("materialized Blee UI is missing")

    text = app.read_text()
    if "BLEE_SEND_QR_SCANNER_V1" not in text:
        text = patch_register_plugin_import(text)
        imports = list(re.finditer(r"(?m)^import\s.+?;\s*$", text))
        if not imports:
            fail("unable to locate BleeApp import boundary")
        insert_at = imports[-1].end()
        text = text[:insert_at] + scanner_module_block() + text[insert_at:]

        recipient = text.find("Recipient")
        if recipient < 0:
            fail("Send Recipient label not found")
        amount = text.find("Amount", recipient)
        if amount < 0:
            amount = min(len(text), recipient + 8000)
        input_start, input_end = recipient_input_bounds(text, recipient, amount)
        input_tag = text[input_start:input_end]

        value_match = re.search(r"\bvalue\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}", input_tag)
        state_name = value_match.group(1) if value_match else None
        setter = None
        if state_name:
            state_pattern = re.compile(r"const\s*\[\s*" + re.escape(state_name) + r"\s*,\s*([A-Za-z_$][\w$]*)\s*\]\s*=\s*useState")
            state_match = state_pattern.search(text)
            if state_match:
                setter = state_match.group(1)
        if not setter:
            change_match = re.search(r"onChange\s*=\s*\{\s*\(?\s*([A-Za-z_$][\w$]*)\s*\)?\s*=>\s*([A-Za-z_$][\w$]*)\s*\(\s*\1\.target\.value\s*\)\s*\}", input_tag)
            if change_match:
                setter = change_match.group(2)
        if not setter:
            candidates = re.findall(r"const\s*\[\s*(?:recipient|to|sendTo|recipientAddress)\s*,\s*([A-Za-z_$][\w$]*)\s*\]\s*=\s*useState", text, re.I)
            if len(candidates) == 1:
                setter = candidates[0]
        if not setter:
            fail("unable to identify Recipient state setter")

        scanner_button = f'''
        <button
          type="button"
          className="blee-recipient-qr-scan"
          aria-label="Scan recipient QR code"
          onClick={{async () => {{
            try {{
              const result = await BleeQrScanner.scan();
              if (result?.cancelled || !result?.value) return;
              const scannedRecipient = parseBleeRecipientQr(result.value);
              {setter}(scannedRecipient);
            }} catch (error) {{
              const message = error instanceof Error ? error.message : 'Unable to scan this QR code.';
              window.alert(message);
            }}
          }}}}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4M8 8h3v3H8zM13 8h3v3h-3zM8 13h3v3H8zM13 13h3v3h-3z" />
          </svg>
          <span>Scan QR</span>
        </button>'''
        text = text[:input_end] + scanner_button + text[input_end:]
        app.write_text(text)

    css_text = css.read_text()
    if "BLEE_SEND_QR_SCANNER_CSS_V1" not in css_text:
        css_text += r'''

/* BLEE_SEND_QR_SCANNER_CSS_V1 */
.blee-recipient-qr-scan {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  margin-top: 8px;
  padding: 0 13px;
  border: 1px solid rgba(17, 17, 17, .12);
  border-radius: 999px;
  background: rgba(255, 255, 255, .72);
  color: #111;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  -webkit-tap-highlight-color: transparent;
}
.blee-recipient-qr-scan:active { transform: scale(.985); }
.blee-recipient-qr-scan svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}
'''
        css.write_text(css_text)

    verify_web()


def locate_activity() -> Path:
    hits = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(hits) != 1:
        fail(f"expected one MainActivity.java, found {len(hits)}")
    return hits[0]


def patch_android() -> None:
    android = ROOT / "android"
    if not android.is_dir():
        fail("android/ is missing")
    activity = locate_activity()
    package_match = re.search(r"(?m)^package\s+([A-Za-z0-9_.]+);", activity.read_text())
    if not package_match:
        fail("MainActivity package missing")
    package = package_match.group(1)
    native_dir = activity.parent

    gradle = ROOT / "android/app/build.gradle"
    g = gradle.read_text()
    dep = "implementation 'com.journeyapps:zxing-android-embedded:4.3.0'"
    if dep not in g:
        m = re.search(r"(?m)^dependencies\s*\{", g)
        if not m:
            fail("Android dependencies block missing")
        g = g[:m.end()] + "\n    // BLEE_SEND_QR_SCANNER_ANDROID_V1\n    " + dep + g[m.end():]
        gradle.write_text(g)

    plugin = native_dir / "BleeQrScannerPlugin.java"
    plugin.write_text(f'''package {package};

// BLEE_SEND_QR_SCANNER_ANDROID_V1
import android.content.Intent;
import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.journeyapps.barcodescanner.IntentIntegrator;
import com.journeyapps.barcodescanner.IntentResult;

@CapacitorPlugin(name = "BleeQrScanner")
public class BleeQrScannerPlugin extends Plugin {{
    @PluginMethod
    public void scan(PluginCall call) {{
        try {{
            IntentIntegrator integrator = new IntentIntegrator(getActivity());
            integrator.setDesiredBarcodeFormats(IntentIntegrator.QR_CODE);
            integrator.setPrompt("Scan Blee payment QR");
            integrator.setBeepEnabled(false);
            integrator.setBarcodeImageEnabled(false);
            integrator.setOrientationLocked(true);
            Intent intent = integrator.createScanIntent();
            startActivityForResult(call, intent, "scanResult");
        }} catch (Throwable error) {{
            call.reject("Unable to open the QR scanner", error);
        }}
    }}

    @ActivityCallback
    private void scanResult(PluginCall call, ActivityResult activityResult) {{
        if (call == null) return;
        IntentResult result = IntentIntegrator.parseActivityResult(
            activityResult.getResultCode(),
            activityResult.getData()
        );
        JSObject out = new JSObject();
        if (result == null || result.getContents() == null) {{
            out.put("cancelled", true);
            call.resolve(out);
            return;
        }}
        out.put("cancelled", false);
        out.put("value", result.getContents());
        call.resolve(out);
    }}
}}
''')

    a = activity.read_text()
    if "BleeQrScannerPlugin.class" not in a:
        super_match = re.search(r"(?m)^(\s*)super\.onCreate\(savedInstanceState\);", a)
        if not super_match:
            fail("MainActivity super.onCreate anchor missing")
        indent = super_match.group(1)
        registration = indent + "registerPlugin(BleeQrScannerPlugin.class);\n"
        a = a[:super_match.start()] + registration + a[super_match.start():]
        activity.write_text(a)

    verify_android()


def verify_web() -> None:
    app = (ROOT / "src/components/BleeApp.tsx").read_text()
    css = (ROOT / "app/globals.css").read_text()
    required = (
        "BLEE_SEND_QR_SCANNER_V1",
        "registerPlugin<BleeQrScannerPlugin>('BleeQrScanner')",
        "parseBleeRecipientQr",
        'aria-label="Scan recipient QR code"',
        "BleeQrScanner.scan()",
        "blee-recipient-qr-scan",
    )
    missing = [marker for marker in required if marker not in app]
    if missing:
        fail(f"web scanner verification missing {missing}")
    if "BLEE_SEND_QR_SCANNER_CSS_V1" not in css:
        fail("scanner CSS marker missing")
    print("VERIFIED: Send flow exposes a native QR scanner and only accepts a valid EVM recipient")


def verify_android() -> None:
    activity = locate_activity().read_text()
    gradle = (ROOT / "android/app/build.gradle").read_text()
    package_match = re.search(r"(?m)^package\s+([A-Za-z0-9_.]+);", locate_activity().read_text())
    plugin = locate_activity().parent / "BleeQrScannerPlugin.java"
    if not package_match or not plugin.is_file():
        fail("native QR scanner plugin missing")
    native = plugin.read_text()
    for marker in (
        "BLEE_SEND_QR_SCANNER_ANDROID_V1",
        '@CapacitorPlugin(name = "BleeQrScanner")',
        "IntentIntegrator.QR_CODE",
        "startActivityForResult(call, intent, \"scanResult\")",
        "IntentIntegrator.parseActivityResult",
    ):
        if marker not in native:
            fail(f"native scanner verification missing {marker}")
    if "BleeQrScannerPlugin.class" not in activity:
        fail("MainActivity does not register QR scanner")
    if "com.journeyapps:zxing-android-embedded:4.3.0" not in gradle:
        fail("offline ZXing dependency missing")
    print("VERIFIED: Android QR scanner is bundled offline and registered with Capacitor")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--android", action="store_true")
    args = parser.parse_args()
    if not args.web and not args.android:
        args.web = args.android = True
    if args.web:
        patch_web()
    if args.android:
        patch_android()


if __name__ == "__main__":
    main()
