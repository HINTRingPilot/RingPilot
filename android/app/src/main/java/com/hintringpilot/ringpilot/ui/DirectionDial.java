package com.hintringpilot.ringpilot.ui;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.CornerPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.widget.TextView;

import java.util.Locale;

/**
 * 수집 안내용 네 방향 다이얼. 바깥 눈금은 진행률, 네 화살표는 방향, 가운데 원은 안내 글자다.
 * 화면 표시만 맡는다. 안내 시각과 기록은 이 뷰와 무관하게 CollectPanel에서 정해진다.
 */
public final class DirectionDial extends ViewGroup {
    public enum Phase { IDLE, ARMED, STILL, GO, SAVED }

    private static final int TICKS = 80;
    private static final int NONE = -1;

    private final TextView center;
    private final String[] labels = {"", "", "", ""};
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path arrow = new Path();
    private final int maxSize;
    private final int compactSize;

    private boolean compact = false;
    private Phase phase = Phase.IDLE;
    private int activeDirection = NONE;
    private float progress = 0f;
    private int flashDirection = NONE;
    private float flash = 0f;
    private float pulse = 0f;
    private float pop = 1f;
    private ValueAnimator pulseAnimator;
    private ValueAnimator flashAnimator;
    private ValueAnimator popAnimator;

    public DirectionDial(Context context, TextView center) {
        super(context);
        this.center = center;
        maxSize = Ui.dp(context, 344);
        compactSize = Ui.dp(context, 248);
        setWillNotDraw(false);
        center.setGravity(Gravity.CENTER);
        center.setTextColor(Ui.TEXT);
        center.setTypeface(Ui.DISPLAY);
        center.setAutoSizeTextTypeUniformWithConfiguration(12, 34, 1, android.util.TypedValue.COMPLEX_UNIT_SP);
        addView(center);
        paint.setPathEffect(null);
        textPaint.setTypeface(Ui.DISPLAY);
        textPaint.setTextAlign(Paint.Align.CENTER);
        textPaint.setTextSize(Ui.dp(context, 13));
    }

    /** "UP", "raw_up"처럼 방향이 들어간 이름을 0(위) 1(아래) 2(왼쪽) 3(오른쪽)으로 바꾼다. 방향이 아니면 없음. */
    public static int directionOf(String name) {
        if (name == null) return NONE;
        String lower = name.toLowerCase(Locale.US);
        if (lower.endsWith("up")) return 0;
        if (lower.endsWith("down")) return 1;
        if (lower.endsWith("left")) return 2;
        if (lower.endsWith("right")) return 3;
        return NONE;
    }

    public void setLabels(String up, String down, String left, String right) {
        labels[0] = up;
        labels[1] = down;
        labels[2] = left;
        labels[3] = right;
        invalidate();
    }

    public void setCompact(boolean value) {
        if (compact == value) return;
        compact = value;
        // 작은 다이얼에서 "일시정지" 같은 짧은 낱말이 글자 중간에서 줄바꿈되지 않게 최대 크기를 낮춘다.
        center.setAutoSizeTextTypeUniformWithConfiguration(12, compact ? 26 : 34, 1,
                android.util.TypedValue.COMPLEX_UNIT_SP);
        requestLayout();
    }

    public void setProgress(float value) {
        progress = Math.max(0f, Math.min(1f, value));
        invalidate();
    }

    public void setPhase(Phase next, String directionName) {
        boolean changed = phase != next;
        phase = next;
        activeDirection = directionOf(directionName);
        center.setTextColor(next == Phase.GO ? Ui.ON_ACCENT : next == Phase.SAVED ? Ui.OK : Ui.TEXT);
        if (next == Phase.STILL) startPulse();
        else stopPulse();
        if (changed && next == Phase.GO) startPop();
        invalidate();
    }

    /** 받은 제스처를 화살표에 잠깐 비춘다. */
    public void flash(String directionName) {
        flashDirection = directionOf(directionName);
        if (flashDirection == NONE) return;
        if (flashAnimator != null) flashAnimator.cancel();
        flashAnimator = ValueAnimator.ofFloat(1f, 0f);
        flashAnimator.setDuration(700);
        flashAnimator.setInterpolator(new DecelerateInterpolator());
        flashAnimator.addUpdateListener(a -> {
            flash = (float) a.getAnimatedValue();
            invalidate();
        });
        flashAnimator.start();
    }

    private void startPulse() {
        if (pulseAnimator != null) return;
        pulseAnimator = ValueAnimator.ofFloat(0f, 1f);
        pulseAnimator.setDuration(900);
        pulseAnimator.setRepeatCount(ValueAnimator.INFINITE);
        pulseAnimator.setRepeatMode(ValueAnimator.REVERSE);
        pulseAnimator.addUpdateListener(a -> {
            pulse = (float) a.getAnimatedValue();
            invalidate();
        });
        pulseAnimator.start();
    }

    private void stopPulse() {
        if (pulseAnimator != null) {
            pulseAnimator.cancel();
            pulseAnimator = null;
        }
        pulse = 0f;
    }

    private void startPop() {
        if (popAnimator != null) popAnimator.cancel();
        popAnimator = ValueAnimator.ofFloat(0.82f, 1f);
        popAnimator.setDuration(220);
        popAnimator.setInterpolator(new android.view.animation.OvershootInterpolator(2.2f));
        popAnimator.addUpdateListener(a -> {
            pop = (float) a.getAnimatedValue();
            invalidate();
        });
        popAnimator.start();
    }

    @Override
    protected void onDetachedFromWindow() {
        stopPulse();
        if (flashAnimator != null) flashAnimator.cancel();
        if (popAnimator != null) popAnimator.cancel();
        super.onDetachedFromWindow();
    }

    @Override
    protected void onMeasure(int widthSpec, int heightSpec) {
        int width = MeasureSpec.getSize(widthSpec);
        int size = Math.min(width, compact ? compactSize : maxSize);
        setMeasuredDimension(width, size);
        int box = Math.round(size * 0.40f);
        center.measure(MeasureSpec.makeMeasureSpec(box, MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(box, MeasureSpec.EXACTLY));
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        int cx = (r - l) / 2;
        int cy = (b - t) / 2;
        int half = center.getMeasuredWidth() / 2;
        center.layout(cx - half, cy - half, cx + half, cy + half);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        float radius = Math.min(getWidth(), getHeight()) / 2f - Ui.dp(getContext(), 2);
        drawPlate(canvas, cx, cy, radius);
        drawTicks(canvas, cx, cy, radius);
        for (int i = 0; i < 4; i++) drawArrow(canvas, cx, cy, radius, i);
        drawHub(canvas, cx, cy, radius);
    }

    private void drawPlate(Canvas canvas, float cx, float cy, float radius) {
        paint.setPathEffect(null);
        paint.setStyle(Paint.Style.FILL);
        paint.setShader(new RadialGradient(cx, cy, radius,
                new int[]{Ui.RAISED, Ui.PANEL}, new float[]{0.45f, 1f}, Shader.TileMode.CLAMP));
        canvas.drawCircle(cx, cy, radius, paint);
        paint.setShader(null);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Ui.dp(getContext(), 1));
        paint.setColor(Ui.LINE);
        canvas.drawCircle(cx, cy, radius, paint);
    }

    /** 위에서 시계 방향으로 진행률만큼 눈금이 주황으로 찬다. 네 방향 눈금은 더 길다. */
    private void drawTicks(Canvas canvas, float cx, float cy, float radius) {
        float outer = radius - Ui.dp(getContext(), 7);
        float minor = Ui.dp(getContext(), 6);
        float major = Ui.dp(getContext(), 9);
        int filled = Math.round(progress * TICKS);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeCap(Paint.Cap.ROUND);
        paint.setStrokeWidth(Ui.dp(getContext(), 2));
        for (int i = 0; i < TICKS; i++) {
            double angle = 2 * Math.PI * i / TICKS - Math.PI / 2;
            float length = i % 20 == 0 ? major : minor;
            float cos = (float) Math.cos(angle);
            float sin = (float) Math.sin(angle);
            paint.setColor(i < filled ? Ui.ACCENT : i % 20 == 0 ? Ui.MUTED : Ui.LINE);
            canvas.drawLine(cx + cos * outer, cy + sin * outer,
                    cx + cos * (outer - length), cy + sin * (outer - length), paint);
        }
        paint.setStrokeCap(Paint.Cap.BUTT);
    }

    private void drawArrow(Canvas canvas, float cx, float cy, float radius, int direction) {
        float dx = direction == 2 ? -1 : direction == 3 ? 1 : 0;
        float dy = direction == 0 ? -1 : direction == 1 ? 1 : 0;
        float at = radius * 0.625f;
        float size = radius * 0.085f;
        float ax = cx + dx * at;
        float ay = cy + dy * at;
        boolean active = direction == activeDirection && (phase == Phase.ARMED || phase == Phase.STILL || phase == Phase.GO);
        float lit = direction == flashDirection ? flash : 0f;

        if (phase == Phase.GO && active || lit > 0f) {
            float glow = phase == Phase.GO && active ? 1f : lit;
            int alpha = Math.round(120 * glow);
            paint.setStyle(Paint.Style.FILL);
            paint.setShader(new RadialGradient(ax, ay, size * 2.4f,
                    (alpha << 24) | (Ui.ACCENT & 0xFFFFFF), Ui.ACCENT & 0xFFFFFF, Shader.TileMode.CLAMP));
            canvas.drawCircle(ax, ay, size * 2.4f, paint);
            paint.setShader(null);
        }

        // 끝이 둥근 삼각형. 바깥쪽을 가리킨다.
        arrow.reset();
        arrow.moveTo(ax + dx * size, ay + dy * size);
        arrow.lineTo(ax - dx * size * 0.6f - dy * size, ay - dy * size * 0.6f + dx * size);
        arrow.lineTo(ax - dx * size * 0.6f + dy * size, ay - dy * size * 0.6f - dx * size);
        arrow.close();
        paint.setStyle(Paint.Style.FILL);
        paint.setPathEffect(new CornerPathEffect(Ui.dp(getContext(), 4)));
        int color = Ui.ARROW;
        if (active) color = phase == Phase.GO ? Ui.ACCENT : Ui.TEXT;
        if (lit > 0.05f) color = Ui.ACCENT;
        paint.setColor(color);
        canvas.drawPath(arrow, paint);
        paint.setPathEffect(null);

        String label = labels[direction];
        if (label != null && !label.isEmpty()) {
            float labelAt = radius * 0.80f;
            float lx = cx + dx * labelAt;
            float ly = cy + dy * labelAt - (textPaint.ascent() + textPaint.descent()) / 2f;
            textPaint.setColor(active || lit > 0.05f ? Ui.TEXT : Ui.MUTED);
            canvas.drawText(label, lx, ly, textPaint);
        }
    }

    private void drawHub(Canvas canvas, float cx, float cy, float radius) {
        float hub = radius * 0.50f * pop;
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(phase == Phase.GO ? Ui.ACCENT : Ui.BG);
        canvas.drawCircle(cx, cy, hub, paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Ui.dp(getContext(), phase == Phase.STILL ? 2 : 1));
        int color = phase == Phase.SAVED ? Ui.OK : Ui.LINE;
        if (phase == Phase.STILL) {
            int alpha = 90 + Math.round(165 * pulse);
            color = (alpha << 24) | (Ui.TEXT & 0xFFFFFF);
        }
        paint.setColor(color);
        canvas.drawCircle(cx, cy, hub, paint);
    }

    /** 가로로 넓은 화면에서도 가운데 정렬되도록 자식은 직접 배치한다. */
    @Override
    public boolean shouldDelayChildPressedState() {
        return false;
    }

    @Override
    public void onViewAdded(View child) {
        super.onViewAdded(child);
        child.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
    }
}
