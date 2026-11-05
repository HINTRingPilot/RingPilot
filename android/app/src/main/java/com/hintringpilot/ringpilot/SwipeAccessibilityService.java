package com.hintringpilot.ringpilot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
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

import com.hintringpilot.ringpilot.ui.Ui;

import java.lang.ref.WeakReference;

/**
 * 화면에 위·아래·좌·우 스와이프를 주입한다. 제스처 인식 결과를 화면 조작으로 바꾸는 출력 경로다.
 * "스와이프 제어 켜기" 상태에서만 호출된다. 쓰려면 접근성 설정에서 'RingPilot 스와이프'를 켜야 한다.
 */
public final class SwipeAccessibilityService extends AccessibilityService {
    /** 주입이 끝나면 불린다. completed는 시스템이 주입을 마쳤다는 뜻이고, 앱 화면이 원하는 대로 움직였다는 뜻은 아니다. */
    interface SwipeListener {
        void onResult(boolean completed);
    }

    private static final long BANNER_MS = 1200;
    private static final long SWIPE_MS = 400;
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
        view.setTextColor(Ui.TEXT);
        view.setTextSize(13);
        view.setTypeface(getResources().getFont(R.font.do_hyeon));  // 서비스는 앱 화면 없이도 돌아 Ui.init에 기대지 않는다
        view.setPadding((int) (14 * density), (int) (6 * density), (int) (14 * density), (int) (6 * density));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Ui.PANEL & 0xF0FFFFFF);  // 살짝 비치게
        background.setStroke((int) density, Ui.ACCENT);
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

    /** 화면 가운데를 지나는 400 ms 스와이프. 위·아래는 높이의 50%, 좌·우는 폭의 60%를 움직인다. 모르는 방향이면 false. */
    boolean swipe(String direction, SwipeListener listener) {
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
                .addStroke(new GestureDescription.StrokeDescription(path, 0, SWIPE_MS))
                .build();
        return dispatchGesture(gesture, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gestureDescription) {
                listener.onResult(true);
            }

            @Override
            public void onCancelled(GestureDescription gestureDescription) {
                listener.onResult(false);
            }
        }, null);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // 스와이프를 넣기만 하고 화면 내용은 읽지 않는다.
    }

    @Override
    public void onInterrupt() {
        // 끊을 지속 피드백이 없다.
    }
}
