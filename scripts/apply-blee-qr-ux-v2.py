#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee QR UX v2: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def input_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    input_start = text.find("<input", start, end)
    if input_start < 0:
        fail("Send Recipient input not found")
    close = text.find("/>", input_start, end)
    if close >= 0:
        return input_start, close + 2
    quote = None
    braces = 0
    for i in range(input_start + 6, end):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
            continue
        if ch in ('\"', "'"):
            quote = ch
        elif ch == "{":
            braces += 1
        elif ch == "}" and braces:
            braces -= 1
        elif ch == ">" and braces == 0:
            return input_start, i + 1
    fail("Send Recipient input tag is unterminated")


def patch_web() -> None:
    app = ROOT / "src/components/BleeApp.tsx"
    css = ROOT / "app/globals.css"
    if not app.is_file() or not css.is_file():
        fail("materialized UI missing")
    text = app.read_text()
    if "BLEE_SEND_QR_SCANNER_V1" not in text:
        fail("base QR scanner stage must run first")

    text = re.sub(
        r'\s*<button\b(?=[^>]*\bclassName="(?:blee-recipient-qr-scan|blee-recipient-qr-icon)")[\s\S]*?</button>',
        '',
        text,
    )
    text = text.replace('<div className="blee-recipient-input-shell">', '')
    text = text.replace('</div>{/* BLEE_QR_INPUT_SHELL_V2 */}', '')

    review_matches = list(re.finditer(r"Review payment", text))
    if not review_matches:
        fail("Review payment anchor missing")
    review = review_matches[-1].start()
    window_start = max(0, review - 16000)
    send_labels = list(re.finditer(r">\s*Send\s*<", text[window_start:review], re.I))
    if not send_labels:
        fail("Send heading missing")
    send_start = window_start + send_labels[-1].start()
    recipient_labels = list(re.finditer(r">\s*Recipient\s*<", text[send_start:review], re.I))
    if not recipient_labels:
        fail("Recipient label missing")
    recipient = send_start + recipient_labels[-1].end()
    amount_labels = list(re.finditer(r">\s*Amount\s*<", text[recipient:review], re.I))
    if not amount_labels:
        fail("Amount label missing")
    amount = recipient + amount_labels[0].start()
    input_start, input_end = input_bounds(text, recipient, amount)
    input_tag = text[input_start:input_end]
    if "password" in input_tag.lower() or "passphrase" in input_tag.lower():
        fail("refusing to install scanner on secret input")

    value_match = re.search(r"\bvalue\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}", input_tag)
    setter = None
    if value_match:
        state_name = value_match.group(1)
        state_match = re.search(
            r"const\s*\[\s*" + re.escape(state_name) + r"\s*,\s*([A-Za-z_$][\w$]*)\s*\]\s*=\s*useState",
            text,
        )
        if state_match:
            setter = state_match.group(1)
    if not setter:
        change_match = re.search(
            r"onChange\s*=\s*\{\s*\(?\s*([A-Za-z_$][\w$]*)\s*\)?\s*=>\s*([A-Za-z_$][\w$]*)\s*\(\s*\1\.target\.value\s*\)\s*\}",
            input_tag,
        )
        if change_match:
            setter = change_match.group(2)
    if not setter:
        fail("Recipient setter missing")

    button = f'''\n          <button
            type="button"
            className="blee-recipient-qr-icon"
            aria-label="Scan recipient QR code"
            title="Scan QR"
            onClick={{async () => {{
              try {{
                const result = await BleeQrScanner.scan();
                if (result?.cancelled || !result?.value) return;
                {setter}(parseBleeRecipientQr(result.value));
              }} catch (error) {{
                const message = error instanceof Error ? error.message : 'Unable to scan this QR code.';
                window.alert(message);
              }}
            }}}}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3" />
            </svg>
          </button>'''
    replacement = '<div className="blee-recipient-input-shell">\n' + input_tag + button + '\n        </div>{/* BLEE_QR_INPUT_SHELL_V2 */}'
    text = text[:input_start] + replacement + text[input_end:]
    app.write_text(text)

    css_text = css.read_text()
    css_text += r'''

/* BLEE_QR_UX_V2 */
.blee-recipient-qr-scan { display: none !important; }
.blee-recipient-input-shell {
  position: relative;
  width: 100%;
}
.blee-recipient-input-shell > input {
  width: 100%;
  padding-right: 58px !important;
}
.blee-recipient-qr-icon {
  position: absolute;
  right: 10px;
  top: 50%;
  width: 40px;
  height: 40px;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: inherit;
  padding: 0;
  margin: 0;
  -webkit-tap-highlight-color: transparent;
  z-index: 2;
}
.blee-recipient-qr-icon:active { background: rgba(0,0,0,.05); }
.blee-recipient-qr-icon svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
'''
    css.write_text(css_text)


def patch_android() -> None:
    plugin = locate("BleeQrScannerPlugin.java")
    activity = locate("MainActivity.java")
    package_match = re.search(r"(?m)^package\s+([A-Za-z0-9_.]+);", activity.read_text())
    if not package_match:
        fail("MainActivity package missing")
    package = package_match.group(1)

    p = plugin.read_text()
    if "BleeQrCaptureActivity.class" not in p:
        anchor = "            IntentIntegrator integrator = new IntentIntegrator(getActivity());"
        if anchor not in p:
            fail("IntentIntegrator construction anchor missing")
        p = p.replace(anchor, anchor + "\n            integrator.setCaptureActivity(BleeQrCaptureActivity.class);", 1)
    p = p.replace('integrator.setPrompt("Scan Blee payment QR");', 'integrator.setPrompt("Align the QR code inside the frame");')
    plugin.write_text(p)

    capture = activity.parent / "BleeQrCaptureActivity.java"
    capture.write_text(f'''package {package};

// BLEE_QR_CAPTURE_UX_V2
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import com.journeyapps.barcodescanner.CaptureActivity;

public final class BleeQrCaptureActivity extends CaptureActivity {{
    @Override protected void onCreate(Bundle savedInstanceState) {{
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        super.onCreate(savedInstanceState);
        Window window = getWindow();
        window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        WindowManager.LayoutParams attrs = window.getAttributes();
        attrs.dimAmount = 0.58f;
        window.setAttributes(attrs);
        window.setGravity(Gravity.CENTER);
        View decor = window.getDecorView();
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.BLACK);
        background.setCornerRadius(dp(28));
        decor.setBackground(background);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) decor.setClipToOutline(true);
        decor.post(() -> {{
            DisplayMetrics metrics = getResources().getDisplayMetrics();
            int width = Math.min((int) (metrics.widthPixels * 0.92f), dp(560));
            int height = Math.min((int) (metrics.heightPixels * 0.72f), dp(720));
            window.setLayout(width, height);
        }});
    }}

    private int dp(int value) {{
        return Math.round(value * getResources().getDisplayMetrics().density);
    }}
}}
''')

    manifest = ROOT / "android/app/src/main/AndroidManifest.xml"
    m = manifest.read_text()
    activity_name = f'{package}.BleeQrCaptureActivity'
    if activity_name not in m:
        pos = m.rfind("</application>")
        if pos < 0:
            fail("manifest application close missing")
        entry = f'''        <!-- BLEE_QR_CAPTURE_UX_V2 -->\n        <activity\n            android:name="{activity_name}"\n            android:exported="false"\n            android:excludeFromRecents="true"\n            android:screenOrientation="portrait"\n            android:theme="@android:style/Theme.Material.Light.Dialog.NoActionBar" />\n'''
        m = m[:pos] + entry + m[pos:]
        manifest.write_text(m)


def verify() -> None:
    app = (ROOT / "src/components/BleeApp.tsx").read_text()
    css = (ROOT / "app/globals.css").read_text()
    plugin = locate("BleeQrScannerPlugin.java").read_text()
    capture = locate("BleeQrCaptureActivity.java").read_text()
    manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text()
    if app.count('className="blee-recipient-qr-icon"') != 1:
        fail("expected exactly one icon scanner")
    if '<span>Scan QR</span>' in app:
        fail("visible Scan QR text remains")
    if "BLEE_QR_INPUT_SHELL_V2" not in app or "BLEE_QR_UX_V2" not in css:
        fail("recipient in-field scanner markers missing")
    if "BleeQrCaptureActivity.class" not in plugin:
        fail("custom portrait capture activity not selected")
    for marker in ("SCREEN_ORIENTATION_PORTRAIT", "BLEE_QR_CAPTURE_UX_V2", "window.setLayout(width, height)"):
        if marker not in capture:
            fail(f"capture activity missing {marker}")
    if "BleeQrCaptureActivity" not in manifest or 'android:screenOrientation="portrait"' not in manifest:
        fail("capture activity manifest entry missing")
    print("VERIFIED: QR scanner is portrait modal UX with an icon-only control inside Send Recipient")


def main() -> None:
    patch_web()
    patch_android()
    verify()


if __name__ == "__main__":
    main()
