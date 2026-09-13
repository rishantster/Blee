package com.blee.payments;

import android.Manifest;
import android.content.pm.PackageManager;
import android.media.MediaPlayer;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;

import com.getcapacitor.BridgeActivity;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends BridgeActivity {
    private static final int BLEE_NEARBY_PERMISSION_REQUEST = 24003;
    private static final int BLEE_NOTIFICATION_PERMISSION_REQUEST = 24004;
    private static long bleeLaunchChimeLastPlayedAt = 0L;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(BleeMeshPlugin.class);
        registerPlugin(BleeBiometricPlugin.class);
        registerPlugin(BleeQrScannerPlugin.class);
        registerPlugin(BleeNotificationsPlugin.class);
        super.onCreate(savedInstanceState);

        BleePaymentNotifier.ensureChannel(this);
        ensureNotificationPermission();
        ensureBleeNearbyPermissions();
        BleeMeshService.start(this);
        playBleeLaunchChime();
    }

    private void ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                new String[] { Manifest.permission.POST_NOTIFICATIONS },
                BLEE_NOTIFICATION_PERMISSION_REQUEST
            );
        }
    }

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
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.NEARBY_WIFI_DEVICES);
            }
            if (!missing.isEmpty()) {
                requestPermissions(missing.toArray(new String[0]), BLEE_NEARBY_PERMISSION_REQUEST);
            }
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
            && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                new String[] { Manifest.permission.ACCESS_FINE_LOCATION },
                BLEE_NEARBY_PERMISSION_REQUEST
            );
        }
    }

    @Override
    public void onStart() {
        super.onStart();
        BleeMeshService.start(this);
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
        long now = SystemClock.elapsedRealtime();
        if (now - bleeLaunchChimeLastPlayedAt < 1400L) return;
        bleeLaunchChimeLastPlayedAt = now;

        try {
            MediaPlayer player = MediaPlayer.create(this, R.raw.blee_open_chime);
            if (player == null) return;
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
