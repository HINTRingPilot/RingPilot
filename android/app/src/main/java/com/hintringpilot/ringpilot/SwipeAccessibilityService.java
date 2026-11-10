package com.hintringpilot.ringpilot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.widget.TextView;

import com.hintringpilot.ringpilot.ui.Ui;

import java.lang.ref.WeakReference;

/**
 * 화면 조작 출력 경로. 위·아래·좌·우 스와이프와 탭을 주입하고, 모드 배너와 5방향 스위치 커서를 다른 앱 위에 그린다.
 * "스와이프 제어 켜기" 상태에서만 호출된다. 쓰려면 접근성 설정에서 'RingPilot 스와이프'를 켜야 한다.
 * 배너와 커서는 터치를 가로채지 않으므로, 커서 아래로 넣은 탭이 그대로 앱에 닿는다.
 */
public final class SwipeAccessibilityService extends AccessibilityService {
    /** 주입이 끝나면 불린다. completed는 시스템이 주입을 마쳤다는 뜻이고, 앱 화면이 원하는 대로 움직였다는 뜻은 아니다. */
    interface SwipeListener {
        void onResult(boolean completed);
    }

    private static final long BANNER_MS = 1200;
    private static final long SWIPE_MS = 400;
    private static final long TAP_MS = 50;
    private static final int CURSOR_DP = 22;
    private static WeakReference<SwipeAccessibilityService> current = new WeakReference<>(null);
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView banner;
    private View cursor;
    private WindowManager.LayoutParams cursorParams;

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
        hideCursor();
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
    /** 화면 전체의 좌표 범위(상태 표시줄·내비게이션 바 포함). 커서와 탭은 이 좌표를 쓴다. */
    Rect screenBounds() {
        return getSystemService(WindowManager.class).getCurrentWindowMetrics().getBounds();
    }

    /** 커서 점을 화면 좌표 (x, y)에 중심을 맞춰 보인다. 터치를 가로채지 않는다. 메인 스레드에서 부른다. */
    void showCursor(float x, float y) {
        float density = getResources().getDisplayMetrics().density;
        int size = (int) (CURSOR_DP * density);
        if (cursor == null) {
            View view = new View(this);
            GradientDrawable dot = new GradientDrawable();
            dot.setShape(GradientDrawable.OVAL);
            dot.setColor(Ui.ACCENT & 0xCCFFFFFF);  // 아래가 조금 보이게
            dot.setStroke((int) (2 * density), Ui.TEXT);
            view.setBackground(dot);
            cursorParams = new WindowManager.LayoutParams(size, size,
                    WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                            | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    PixelFormat.TRANSLUCENT);
            cursorParams.gravity = Gravity.TOP | Gravity.LEFT;
            cursorParams.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            cursorParams.x = Math.round(x) - size / 2;
            cursorParams.y = Math.round(y) - size / 2;
            getSystemService(WindowManager.class).addView(view, cursorParams);
            cursor = view;
            return;
        }
        cursorParams.x = Math.round(x) - size / 2;
        cursorParams.y = Math.round(y) - size / 2;
        getSystemService(WindowManager.class).updateViewLayout(cursor, cursorParams);
    }

    void hideCursor() {
        if (cursor != null) {
            getSystemService(WindowManager.class).removeView(cursor);
            cursor = null;
        }
    }

    /** 화면 좌표 (x, y)를 한 번 탭한다. */
    boolean tap(float x, float y, SwipeListener listener) {
        Path path = new Path();
        path.moveTo(x, y);
        return dispatch(new GestureDescription.StrokeDescription(path, 0, TAP_MS), listener);
    }

    private boolean dispatch(GestureDescription.StrokeDescription stroke, SwipeListener listener) {
        GestureDescription gesture = new GestureDescription.Builder().addStroke(stroke).build();
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

        return dispatch(new GestureDescription.StrokeDescription(path, 0, SWIPE_MS), listener);
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
