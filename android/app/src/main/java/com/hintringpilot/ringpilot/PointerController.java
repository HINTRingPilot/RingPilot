package com.hintringpilot.ringpilot;

import android.graphics.Rect;
import android.os.Handler;
import android.os.SystemClock;

import java.util.Locale;
import java.util.function.BiConsumer;
import java.util.function.BooleanSupplier;

/**
 * 반지의 5방향 스위치 상태로 화면 커서를 움직이고, 클릭이면 커서 위치를 탭한다(형식은 firmware/gesture_infer/src/pointer.h).
 * 커서는 평소에 숨겨 두고, 방향 입력이나 클릭이 있으면 보였다가 마지막 입력 HIDE_AFTER_MS 뒤 숨긴다.
 * 방향을 누르는 동안 일정 속도로 움직인다. 반지는 누르는 동안 200 ms마다 상태를 다시 보내므로, STALE_MS 동안 소식이 없으면
 * 뗌을 놓친 것으로 보고 멈춘다. 스와이프 제어가 꺼져 있거나 접근성 서비스가 없으면 아무것도 하지 않는다. 메인 스레드에서만 쓴다.
 */
final class PointerController {
    private static final int UP = 1, DOWN = 2, LEFT = 4, RIGHT = 8;
    private static final long FRAME_MS = 16;
    private static final long HIDE_AFTER_MS = 1500;
    private static final long STALE_MS = 600;
    private static final float SPEED_SCREEN_PER_S = 0.5f;  // 1초에 화면 짧은 변의 절반
    private static final int MAX_TAPS_PER_PACKET = 3;      // 패킷을 여럿 놓쳤을 때 탭이 몰리지 않게

    private final Handler handler;
    private final BooleanSupplier enabled;
    private final BiConsumer<String, String> record;

    private int state = 0;
    private int lastClicks = -1;  // 기준 클릭 수. 구독 직후 첫 패킷으로 잡는다
    private float x = Float.NaN;
    private float y = Float.NaN;
    private long lastPacketMs = 0;
    private long lastActivityMs = 0;
    private long lastFrameMs = 0;
    private boolean framing = false;

    /** enabled: 스와이프 제어가 켜져 있는지. record: 연결 기록(connection_log.csv)에 쓰기. */
    PointerController(Handler handler, BooleanSupplier enabled, BiConsumer<String, String> record) {
        this.handler = handler;
        this.enabled = enabled;
        this.record = record;
    }

    void onPacket(int newState, int clicks, boolean baseline) {
        long now = SystemClock.elapsedRealtime();
        int taps = 0;
        if (!baseline && lastClicks >= 0) taps = Math.min((clicks - lastClicks) & 0xFF, MAX_TAPS_PER_PACKET);
        lastClicks = clicks;

        SwipeAccessibilityService service = SwipeAccessibilityService.getCurrent();
        if (!enabled.getAsBoolean() || service == null) {
            stop();
            return;
        }
        state = newState;
        lastPacketMs = now;
        if (state != 0 || taps > 0) {
            lastActivityMs = now;
            startFrames(service);
        }
        for (int i = 0; i < taps; i++) tap(service);
    }

    private void tap(SwipeAccessibilityService service) {
        float tx = x;
        float ty = y;
        boolean sent = service.tap(tx, ty, completed -> record.accept("pointer_tap_result", completed ? "completed" : "cancelled"));
        record.accept("pointer_tap", String.format(Locale.US, "x=%.0f y=%.0f sent=%b", tx, ty, sent));
    }

    private void startFrames(SwipeAccessibilityService service) {
        if (Float.isNaN(x)) {  // 처음에는 화면 가운데
            Rect b = service.screenBounds();
            x = b.exactCenterX();
            y = b.exactCenterY();
        }
        service.showCursor(x, y);
        if (framing) return;
        framing = true;
        lastFrameMs = SystemClock.elapsedRealtime();
        handler.postDelayed(frame, FRAME_MS);
    }

    private final Runnable frame = new Runnable() {
        @Override
        public void run() {
            SwipeAccessibilityService service = SwipeAccessibilityService.getCurrent();
            if (service == null || !enabled.getAsBoolean()) {
                stop();
                return;
            }
            long now = SystemClock.elapsedRealtime();
            if (state != 0 && now - lastPacketMs > STALE_MS) state = 0;  // 뗌을 놓쳤다
            if (state != 0) {
                Rect b = service.screenBounds();
                float step = SPEED_SCREEN_PER_S * Math.min(b.width(), b.height()) * (now - lastFrameMs) / 1000f;
                int dx = ((state & RIGHT) != 0 ? 1 : 0) - ((state & LEFT) != 0 ? 1 : 0);
                int dy = ((state & DOWN) != 0 ? 1 : 0) - ((state & UP) != 0 ? 1 : 0);
                x = Math.max(b.left, Math.min(b.right - 1, x + dx * step));
                y = Math.max(b.top, Math.min(b.bottom - 1, y + dy * step));
                service.showCursor(x, y);
                lastActivityMs = now;
            } else if (now - lastActivityMs >= HIDE_AFTER_MS) {
                service.hideCursor();
                framing = false;
                return;
            }
            lastFrameMs = now;
            handler.postDelayed(this, FRAME_MS);
        }
    };

    /** 커서를 숨기고 움직임을 멈춘다. 위치와 기준 클릭 수는 남긴다. */
    void stop() {
        state = 0;
        framing = false;
        handler.removeCallbacks(frame);
        SwipeAccessibilityService service = SwipeAccessibilityService.getCurrent();
        if (service != null) service.hideCursor();
    }
}
