package com.blee.payments;
import java.util.List;
import java.util.ArrayList;
import android.os.SystemClock;
import android.os.Build;
import android.media.MediaPlayer;
import android.content.pm.PackageManager;
import android.Manifest;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(BleeMeshPlugin.class);
        registerPlugin(BleeBiometricPlugin.class);
        registerPlugin(BleeQrScannerPlugin.class);
        super.onCreate(savedInstanceState);
        // BLEE_NOTIFICATION_PERMISSION_REQUEST_V1
        BleePaymentNotifier.ensureChannel(this);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 4817);
        }
        ensureBleeNearbyPermissions();
        BleeMeshService.start(this);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 24002);
        }
        playBleeLaunchChime();
    }


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
            // BLEE_ADAPTIVE_NEARBY_PERMISSION_V3
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.NEARBY_WIFI_DEVICES);
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
        // BLEE_SESSION_BACKGROUND_SAFE_V1
        BleeMeshService.start(this);
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

}
