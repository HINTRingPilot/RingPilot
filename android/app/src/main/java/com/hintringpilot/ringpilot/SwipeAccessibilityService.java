package com.hintringpilot.ringpilot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Color;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.widget.TextView;

import java.lang.ref.WeakReference;

/**
 * 화면에 위·아래·좌·우 스와이프를 주입한다. 제스처 인식 결과를 화면 조작으로 바꾸는 출력 경로로 보존하며,
 * 현재 수집 화면에서는 호출하지 않는다. 다시 쓰려면 접근성 설정에서 'RingPilot 스와이프'를 켜야 한다.
 */
public final class SwipeAccessibilityService extends AccessibilityService {
    private static final long BANNER_MS = 1200;
    private static WeakReference<SwipeAccessibilityService> current = new WeakReference<>(null);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView banner;

    static SwipeAccessibilityService getCurrent() {
        return current.get();
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        current = new WeakReference<>(this);
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        hideBanner();
        if (current.get() == this) {
            current.clear();
        }
        super.onDestroy();
    }

    /** 화면 위쪽에 글자를 잠깐 띄운다. 터치를 가로채지 않는다. 메인 스레드에서 부른다. */
    void showBanner(String text) {
        handler.removeCallbacksAndMessages(null);
        hideBanner();
        float density = getResources().getDisplayMetrics().density;
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(Color.WHITE);
        view.setTextSize(13);
        view.setPadding((int) (14 * density), (int) (6 * density), (int) (14 * density), (int) (6 * density));
        GradientDrawable background = new GradientDrawable();
        background.setColor(0xCC202124);
        background.setCornerRadius(16 * density);
        view.setBackground(background);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.CENTER_HORIZONTAL;
        params.y = (int) (40 * density);
        getSystemService(WindowManager.class).addView(view, params);
        banner = view;
        handler.postDelayed(this::hideBanner, BANNER_MS);
    }

    private void hideBanner() {
        if (banner != null) {
            getSystemService(WindowManager.class).removeView(banner);
            banner = null;
        }
    }

    boolean swipe(String direction) {
        DisplayMetrics metrics = getResources().getDisplayMetrics();
        float startX = metrics.widthPixels * 0.5f;
        float startY = metrics.heightPixels * 0.5f;
        float endX = startX;
        float endY = startY;

        switch (direction) {
            case "UP":
                startY = metrics.heightPixels * 0.75f;
                endY = metrics.heightPixels * 0.25f;
                break;
            case "DOWN":
                startY = metrics.heightPixels * 0.25f;
                endY = metrics.heightPixels * 0.75f;
                break;
            case "LEFT":
                startX = metrics.widthPixels * 0.80f;
                endX = metrics.widthPixels * 0.20f;
                break;
            case "RIGHT":
                startX = metrics.widthPixels * 0.20f;
                endX = metrics.widthPixels * 0.80f;
                break;
            default:
                return false;
        }

        Path path = new Path();
        path.moveTo(startX, startY);
        path.lineTo(endX, endY);

        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 400))
                .build();
        return dispatchGesture(gesture, null, null);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // This prototype only injects gestures; it does not inspect screen content.
    }

    @Override
    public void onInterrupt() {
        // No continuous accessibility feedback to interrupt.
    }
}
