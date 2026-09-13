#!/usr/bin/env python3
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee notification permission: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    manifest = ROOT / "android/app/src/main/AndroidManifest.xml"
    m = manifest.read_text()
    permission = '<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />'
    if 'android.permission.POST_NOTIFICATIONS' not in m:
        app_pos = m.find("<application")
        if app_pos < 0:
            fail("manifest application anchor missing")
        m = m[:app_pos] + "    " + permission + "\n" + m[app_pos:]
        manifest.write_text(m)

    notifier = locate("BleePaymentNotifier.java")
    n = notifier.read_text()
    if "BLEE_NOTIFICATION_PERMISSION_V1" not in n:
        anchor = "    private BleePaymentNotifier() {}"
        helper = r'''    private BleePaymentNotifier() {}

    // BLEE_NOTIFICATION_PERMISSION_V1
    public static void ensureChannel(Context rawContext) {
        if (rawContext == null) return;
        Context context = rawContext.getApplicationContext();
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Blee payment activity", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Immediate nearby payment sent and received notifications.");
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }
    }'''
        if anchor not in n:
            fail("notifier constructor anchor missing")
        n = n.replace(anchor, helper, 1)
        notifier.write_text(n)

    activity = locate("MainActivity.java")
    a = activity.read_text()
    if "BLEE_NOTIFICATION_PERMISSION_REQUEST_V1" not in a:
        imports = []
        for imp in (
            "import android.Manifest;",
            "import android.content.pm.PackageManager;",
            "import android.os.Build;",
        ):
            if imp not in a:
                imports.append(imp)
        if imports:
            package_end = a.find(";", a.find("package "))
            if package_end < 0:
                fail("MainActivity package declaration missing")
            a = a[:package_end + 1] + "\n\n" + "\n".join(imports) + a[package_end + 1:]

        super_anchor = "super.onCreate(savedInstanceState);"
        pos = a.find(super_anchor)
        if pos < 0:
            fail("MainActivity onCreate super anchor missing")
        end = pos + len(super_anchor)
        injection = r'''
        // BLEE_NOTIFICATION_PERMISSION_REQUEST_V1
        BleePaymentNotifier.ensureChannel(this);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 4817);
        }'''
        a = a[:end] + injection + a[end:]
        activity.write_text(a)

    for path, markers in (
        (manifest, ("POST_NOTIFICATIONS",)),
        (notifier, ("BLEE_NOTIFICATION_PERMISSION_V1", "ensureChannel")),
        (activity, ("BLEE_NOTIFICATION_PERMISSION_REQUEST_V1", "requestPermissions", "POST_NOTIFICATIONS")),
    ):
        generated = path.read_text()
        for marker in markers:
            if marker not in generated:
                fail(f"{path.name} missing {marker}")
    print("VERIFIED: Android 13+ notification permission is requested and payment channel is created at app launch")


if __name__ == "__main__":
    main()
