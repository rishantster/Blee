#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee QR scanner compilefix: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate("BleeQrScannerPlugin.java")
    text = path.read_text()

    # JourneyApps bundles the legacy IntentIntegrator class under the original
    # ZXing integration namespace, not com.journeyapps.barcodescanner.
    text = text.replace(
        "import com.journeyapps.barcodescanner.IntentIntegrator;",
        "import com.google.zxing.integration.android.IntentIntegrator;",
    )

    # Capacitor PluginCall.reject accepts Exception, not a raw Throwable.
    text = text.replace(
        '''        } catch (Throwable error) {\n            call.reject("Unable to open the QR scanner", error);\n        }''',
        '''        } catch (Exception error) {\n            call.reject("Unable to open the QR scanner", error);\n        }''',
    )

    path.write_text(text)

    verify = path.read_text()
    required = (
        "BLEE_SEND_QR_SCANNER_ANDROID_V1",
        "import com.google.zxing.integration.android.IntentIntegrator;",
        "new IntentIntegrator(getActivity())",
        "IntentIntegrator.QR_CODE",
        'startActivityForResult(call, intent, "scanResult")',
        'getStringExtra("SCAN_RESULT")',
        "catch (Exception error)",
        'call.reject("Unable to open the QR scanner", error)',
    )
    missing = [marker for marker in required if marker not in verify]
    if missing:
        fail(f"verification missing {missing}")
    if "import com.journeyapps.barcodescanner.IntentIntegrator;" in verify:
        fail("obsolete JourneyApps IntentIntegrator import remains")
    if "catch (Throwable error)" in verify:
        fail("Capacitor-incompatible Throwable reject path remains")

    print("VERIFIED: QR scanner Java uses the bundled ZXing IntentIntegrator namespace and Capacitor-compatible exception handling")


if __name__ == "__main__":
    main()
