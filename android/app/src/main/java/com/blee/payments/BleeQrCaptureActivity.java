package com.blee.payments;

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

public final class BleeQrCaptureActivity extends CaptureActivity {
    @Override protected void onCreate(Bundle savedInstanceState) {
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
        decor.post(() -> {
            DisplayMetrics metrics = getResources().getDisplayMetrics();
            int width = Math.min((int) (metrics.widthPixels * 0.92f), dp(560));
            int height = Math.min((int) (metrics.heightPixels * 0.72f), dp(720));
            window.setLayout(width, height);
        });
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
