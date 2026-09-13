#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee relay v1 compilefix: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def patch_service() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1" not in text:
        fail("relay service stage must run first")
    if "import java.util.Locale;" not in text:
        anchor = "import java.util.List;\n"
        if anchor not in text:
            fail("service java.util import anchor missing")
        text = text.replace(anchor, anchor + "import java.util.Locale;\n", 1)
    path.write_text(text)


def patch_plugin() -> None:
    path = locate("BleeMeshPlugin.java")
    text = path.read_text()
    if "BLEE_RELAY_PLUGIN_V1" not in text:
        fail("relay plugin stage must run first")

    if "import org.json.JSONObject;" not in text:
        anchor = "import java.util.List;\n"
        if anchor not in text:
            fail("plugin import anchor missing")
        text = text.replace(anchor, "import org.json.JSONObject;\n\n" + anchor, 1)

    old = '''    @PluginMethod
    public void relayDiagnostics(PluginCall call) {
        BleeRelayStore relay = new BleeRelayStore(getContext());
        try { call.resolve(JSObject.fromJSONObject(relay.diagnostics())); }
        catch (Throwable error) { call.reject("Unable to read relay diagnostics: " + error.getMessage()); }
        finally { relay.close(); }
    }'''
    new = '''    @PluginMethod
    public void relayDiagnostics(PluginCall call) {
        BleeRelayStore relay = new BleeRelayStore(getContext());
        try {
            JSONObject raw = relay.diagnostics();
            JSObject result = new JSObject();
            for (String key : new String[] {
                "relayQueueSize", "relayPacketsValidated", "relayBroadcastPending",
                "relayConfirmed", "relayExpired", "relayRejected",
                "relayNeedsSenderRefresh", "lastRelayError"
            }) result.put(key, raw.opt(key));
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to read relay diagnostics: " + error.getMessage());
        } finally {
            relay.close();
        }
    }'''
    if "JSObject.fromJSONObject(relay.diagnostics())" in text:
        if old not in text:
            fail("relay diagnostics compatibility anchor changed")
        text = text.replace(old, new, 1)
    path.write_text(text)


def verify() -> None:
    service = locate("BleeMeshService.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    if "import java.util.Locale;" not in service:
        fail("Locale import missing")
    if "JSObject.fromJSONObject" in plugin:
        fail("unsupported JSObject.fromJSONObject call remains")
    for marker in ("import org.json.JSONObject;", "JSONObject raw = relay.diagnostics();", '"relayNeedsSenderRefresh"'):
        if marker not in plugin:
            fail(f"plugin diagnostics bridge missing {marker}")
    print("Blee Relay V1 Android bridge compile compatibility verified")


def main() -> None:
    patch_service()
    patch_plugin()
    verify()


if __name__ == "__main__":
    main()
