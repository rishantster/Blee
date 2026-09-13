package com.blee.payments;

// BLEE_SEND_QR_SCANNER_ANDROID_V1
import android.content.Intent;
import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.zxing.integration.android.IntentIntegrator;

@CapacitorPlugin(name = "BleeQrScanner")
public class BleeQrScannerPlugin extends Plugin {
    @PluginMethod
    public void scan(PluginCall call) {
        try {
            IntentIntegrator integrator = new IntentIntegrator(getActivity());
            integrator.setCaptureActivity(BleeQrCaptureActivity.class);
            integrator.setDesiredBarcodeFormats(IntentIntegrator.QR_CODE);
            integrator.setPrompt("Align the QR code inside the frame");
            integrator.setBeepEnabled(false);
            integrator.setBarcodeImageEnabled(false);
            integrator.setOrientationLocked(true);
            Intent intent = integrator.createScanIntent();
            startActivityForResult(call, intent, "scanResult");
        } catch (Exception error) {
            call.reject("Unable to open the QR scanner", error);
        }
    }

    @ActivityCallback
    private void scanResult(PluginCall call, ActivityResult activityResult) {
        if (call == null) return;
        Intent data = activityResult == null ? null : activityResult.getData();
        String value = data == null ? null : data.getStringExtra("SCAN_RESULT");
        JSObject out = new JSObject();
        if (value == null || value.trim().isEmpty()) {
            out.put("cancelled", true);
            call.resolve(out);
            return;
        }
        out.put("cancelled", false);
        out.put("value", value);
        call.resolve(out);
    }
}
