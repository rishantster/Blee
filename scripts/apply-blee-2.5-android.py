#!/usr/bin/env python3
from __future__ import annotations

import math
import re
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/app/src/main"
TEMPLATE = ROOT / "mesh-v2/android/BleeBiometricPlugin.java.in"


def locate_activity() -> Path:
    matches = list((ANDROID / "java").rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee 2.5: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def package_name(activity: Path) -> str:
    m = re.search(r"^package\s+([A-Za-z0-9_.]+);", activity.read_text(), re.M)
    if not m:
        raise SystemExit("Blee 2.5: could not determine Android package")
    return m.group(1)


def install_biometric(activity: Path, package: str) -> None:
    if not TEMPLATE.is_file():
        raise SystemExit("Blee 2.5: biometric Android template missing")
    target = activity.parent / "BleeBiometricPlugin.java"
    target.write_text(TEMPLATE.read_text().replace("__BLEE_APP_PACKAGE__", package))
    print(f"Blee 2.5 biometric: {target.relative_to(ROOT)}")


def harden_capacitor_reject_types(activity: Path) -> None:
    """Capacitor PluginCall.reject accepts Exception, not arbitrary Throwable."""
    target = activity.parent / "BleeBiometricPlugin.java"
    text = target.read_text()
    hits = text.count("catch (Throwable error)")
    if hits:
        text = text.replace("catch (Throwable error)", "catch (Exception error)")
        target.write_text(text)
    if re.search(r"call\.reject\([^;\n]+,\s*error\s*\);", text) and "catch (Throwable error)" in text:
        raise SystemExit("Blee 2.5: a Throwable is still being passed to PluginCall.reject")
    if text.count("catch (Exception error)") < 5:
        raise SystemExit("Blee 2.5: biometric reject paths are not Exception-safe")
    print(f"Blee 2.5: Capacitor reject overload hardened ({hits} legacy Throwable catch blocks normalized)")


def generate_chime() -> None:
    raw = ANDROID / "res/raw"
    raw.mkdir(parents=True, exist_ok=True)
    target = raw / "blee_open_chime.wav"
    rate = 44100
    duration = 0.42
    frames = int(rate * duration)
    notes = ((0.000, 659.25, 0.18), (0.115, 880.00, 0.16), (0.245, 1046.50, 0.12))
    data = bytearray()
    for i in range(frames):
        t = i / rate
        sample = 0.0
        for start, freq, gain in notes:
            local = t - start
            if local < 0 or local > 0.23:
                continue
            attack = min(1.0, local / 0.012)
            decay = math.exp(-local * 12.0)
            sample += gain * attack * decay * math.sin(2 * math.pi * freq * local)
        sample = max(-0.32, min(0.32, sample))
        data += struct.pack('<h', int(sample * 32767))
    with wave.open(str(target), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(data))
    print("Blee 2.5: subtle launch chime generated")


def patch_activity(activity: Path) -> None:
    text = activity.read_text()
    package_end = text.find(';', text.find('package '))
    imports = (
        'import android.Manifest;',
        'import android.content.pm.PackageManager;',
        'import android.media.MediaPlayer;',
        'import android.os.Build;',
        'import android.os.SystemClock;',
        'import java.util.ArrayList;',
        'import java.util.List;',
    )
    for line in imports:
        if line not in text:
            text = text[:package_end+1] + '\n' + line + text[package_end+1:]

    if 'registerPlugin(BleeBiometricPlugin.class);' not in text:
        marker = 'registerPlugin(BleeMeshPlugin.class);'
        if marker not in text:
            raise SystemExit("Blee 2.5: BleeMeshPlugin registration marker missing")
        text = text.replace(marker, marker + '\n        registerPlugin(BleeBiometricPlugin.class);', 1)

    start_marker = 'BleeMeshService.start(this);'
    addition = '''ensureBleeNearbyPermissions();
        BleeMeshService.start(this);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 24002);
        }
        playBleeLaunchChime();'''
    if 'playBleeLaunchChime();' not in text:
        if start_marker not in text:
            raise SystemExit("Blee 2.5: mesh service start marker missing")
        text = text.replace(start_marker, addition, 1)

    if 'BLEE_NEARBY_PERMISSION_REQUEST' not in text:
        close = text.rfind('}')
        method = '''

    private static final int BLEE_NEARBY_PERMISSION_REQUEST = 24003;
    private static long bleeLaunchChimeLastPlayedAt = 0L;

    private void ensureBleeNearbyPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            List<String> missing = new ArrayList<>();
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.BLUETOOTH_SCAN);
            }
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.BLUETOOTH_CONNECT);
            }
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.BLUETOOTH_ADVERTISE);
            }
            if (!missing.isEmpty()) {
                requestPermissions(missing.toArray(new String[0]), BLEE_NEARBY_PERMISSION_REQUEST);
            }
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
            && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.ACCESS_FINE_LOCATION }, BLEE_NEARBY_PERMISSION_REQUEST);
        }
    }

    @Override
    public void onStart() {
        super.onStart();
        // Replay the Blee sonic identity when the user genuinely brings the app
        // to the foreground. A short cooldown prevents duplicate playback from
        // onCreate -> onStart or fast Android lifecycle churn.
        playBleeLaunchChime();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != BLEE_NEARBY_PERMISSION_REQUEST) return;
        boolean granted = grantResults.length > 0;
        for (int result : grantResults) {
            if (result != PackageManager.PERMISSION_GRANTED) {
                granted = false;
                break;
            }
        }
        if (granted) {
            BleeMeshService.start(this);
            recreate();
        }
    }

    private void playBleeLaunchChime() {
        final long now = SystemClock.elapsedRealtime();
        if (now - bleeLaunchChimeLastPlayedAt < 1400L) return;
        bleeLaunchChimeLastPlayedAt = now;
        try {
            final MediaPlayer player = MediaPlayer.create(this, R.raw.blee_open_chime);
            if (player == null) return;
            // Low-volume media playback intentionally respects the user's media
            // volume while remaining audible even when the ringer is silenced.
            player.setVolume(0.24f, 0.24f);
            player.setOnCompletionListener(done -> {
                try { done.release(); } catch (Throwable ignored) {}
            });
            player.setOnErrorListener((failed, what, extra) -> {
                try { failed.release(); } catch (Throwable ignored) {}
                return true;
            });
            player.start();
        } catch (Throwable ignored) {}
    }
'''
        text = text[:close] + method + '\n' + text[close:]
    elif 'ensureBleeNearbyPermissions();' not in text:
        raise SystemExit("Blee 2.5: nearby permission helper exists but is not called")

    activity.write_text(text)


def patch_manifest() -> None:
    path = ANDROID / "AndroidManifest.xml"
    xml = path.read_text()
    marker = '<application'
    pos = xml.find(marker)
    if pos < 0:
        raise SystemExit("Blee 2.5: manifest has no application")
    for permission in ('android.permission.USE_BIOMETRIC', 'android.permission.USE_FINGERPRINT'):
        if f'android:name="{permission}"' not in xml:
            xml = xml[:pos] + f'    <uses-permission android:name="{permission}" />\n' + xml[pos:]
            pos = xml.find(marker)
    path.write_text(xml)


def patch_notifications(activity: Path) -> None:
    service = activity.parent / "BleeMeshService.java"
    text = service.read_text()
    success_marker = 'notifyLedgerChanged(paymentId, "SETTLEMENT_RECEIPT");'
    if 'Payment confirmed' not in text:
        if success_marker not in text:
            raise SystemExit("Blee 2.5: settlement notification marker missing")
        text = text.replace(success_marker, success_marker + '\n                paymentNotification("Payment confirmed", "Your Blee payment is confirmed on Arc Testnet.", paymentId);', 1)
    service.write_text(text)

    db = activity.parent / "BleeMeshDb.java"
    dbtext = db.read_text()
    ack_delete = 'db().delete("mesh_outbox", "message_id=?", new String[] { "pay:" + paymentId });'
    if 'Your payment reached the intended Blee recipient.' not in dbtext:
        if ack_delete not in dbtext:
            raise SystemExit("Blee 2.5: delivery ACK notification marker missing")
        dbtext = dbtext.replace(ack_delete, ack_delete + '\n                notifyTitle = "Payment delivered";\n                notifyBody = "Your payment reached the intended Blee recipient.";', 1)
    db.write_text(dbtext)


def verify(activity: Path) -> None:
    text = activity.read_text()
    for marker in (
        'BleeBiometricPlugin.class', 'POST_NOTIFICATIONS', 'playBleeLaunchChime()', 'R.raw.blee_open_chime',
        'BLEE_NEARBY_PERMISSION_REQUEST', 'BLUETOOTH_SCAN', 'BLUETOOTH_CONNECT', 'BLUETOOTH_ADVERTISE',
        'ensureBleeNearbyPermissions();', 'recreate();', 'public void onStart()', 'SystemClock.elapsedRealtime()',
        'bleeLaunchChimeLastPlayedAt', 'player.setVolume(0.24f, 0.24f)'
    ):
        if marker not in text:
            raise SystemExit(f"Blee 2.5 Android activity feature missing: {marker}")
    if 'protected void onStart()' in text:
        raise SystemExit("Blee 2.5 Android compile guard: onStart must remain public for Capacitor BridgeActivity")
    plugin = activity.parent / "BleeBiometricPlugin.java"
    ptext = plugin.read_text()
    for marker in ('AndroidKeyStore', 'BiometricPrompt', 'FingerprintManager', 'AES/GCM/NoPadding', 'Use a passphrase of at least 8 characters', '@CapacitorPlugin(name = "BleeBiometric")'):
        if marker not in ptext:
            raise SystemExit(f"Blee 2.5 biometric implementation incomplete: {marker}")
    if 'catch (Throwable error)' in ptext:
        raise SystemExit("Blee 2.5 biometric compile guard: Throwable catch survives in reject-capable paths")
    if ptext.count('catch (Exception error)') < 5:
        raise SystemExit("Blee 2.5 biometric compile guard: Exception narrowing was not applied")
    manifest = (ANDROID / 'AndroidManifest.xml').read_text()
    for marker in ('USE_BIOMETRIC', 'POST_NOTIFICATIONS', 'BLUETOOTH_SCAN', 'BLUETOOTH_CONNECT', 'BLUETOOTH_ADVERTISE'):
        if marker not in manifest:
            raise SystemExit(f"Blee 2.5 manifest missing {marker}")
    if not (ANDROID / 'res/raw/blee_open_chime.wav').is_file():
        raise SystemExit("Blee 2.5 launch chime missing")
    service = (activity.parent / 'BleeMeshService.java').read_text()
    if 'Payment confirmed' not in service:
        raise SystemExit("Blee 2.5 confirmed-payment notification missing")
    db = (activity.parent / 'BleeMeshDb.java').read_text()
    if 'Payment delivered' not in db:
        raise SystemExit("Blee 2.5 delivery notification missing")
    print("Blee 2.5 Android verified: fingerprint-only biometric + notifications + reliable foreground launch chime + runtime nearby permissions/rearm")


def main() -> None:
    activity = locate_activity()
    package = package_name(activity)
    install_biometric(activity, package)
    harden_capacitor_reject_types(activity)
    generate_chime()
    patch_activity(activity)
    patch_manifest()
    patch_notifications(activity)
    verify(activity)


if __name__ == '__main__':
    main()
