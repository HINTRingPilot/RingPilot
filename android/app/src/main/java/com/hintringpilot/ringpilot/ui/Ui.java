package com.hintringpilot.ringpilot.ui;

import android.animation.AnimatorSet;
import android.animation.ObjectAnimator;
import android.animation.StateListAnimator;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.fonts.Font;
import android.graphics.fonts.FontFamily;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.DecelerateInterpolator;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.hintringpilot.ringpilot.R;

import java.io.IOException;

/**
 * 화면 디자인 값과 부품. 웹의 CSS 변수·공통 클래스에 해당한다. 색과 모양은 여기서만 바꾼다.
 * 방향: 침대맡 계기판. 어두운 곳에서 보는 화면이라 어두운 테마 하나만 두고, 주황은 "지금 할 일"에만 쓴다.
 */
public final class Ui {
    public static final int BG = 0xFF12100D;
    public static final int DOT = 0xFF2B261F;
    public static final int PANEL = 0xFF1C1915;
    public static final int RAISED = 0xFF27231D;
    public static final int LINE = 0xFF3B352D;
    public static final int ARROW = 0xFF4F473D;
    public static final int TEXT = 0xFFF2EADC;
    public static final int MUTED = 0xFFA89E8F;
    public static final int ACCENT = 0xFFFF5B1F;
    public static final int ON_ACCENT = 0xFF190B04;
    public static final int OK = 0xFF7FE0B0;
    public static final int WARN = 0xFFF2B84B;
    public static final int BAD = 0xFFFF7A6B;

    // 글꼴(res/font, 모두 SIL OFL, 라이선스는 assets/licenses). init을 부른 뒤에 쓴다.
    public static Typeface DISPLAY;    // Do Hyeon: 제목·버튼·큰 값
    public static Typeface BODY;       // Orbit + IBM Plex Mono: 설명 글
    public static Typeface MONO;       // IBM Plex Mono: 숫자·영문 표시
    public static Typeface MONO_BOLD;

    public enum Style { PRIMARY, QUIET, GHOST, ACCENT_LINE }

    private Ui() {
    }

    public static void init(Context context) {
        DISPLAY = context.getResources().getFont(R.font.do_hyeon);
        BODY = bodyTypeface(context);
        MONO = context.getResources().getFont(R.font.ibm_plex_mono);
        MONO_BOLD = context.getResources().getFont(R.font.ibm_plex_mono_bold);
    }

    /** 설명 글은 한글을 Orbit으로, 영문·숫자·기호를 IBM Plex Mono로 쓴다. Orbit의 영문은 "RingPilot-IMU" 같은 기기 이름을 읽기 어렵다. */
    private static Typeface bodyTypeface(Context context) {
        try {
            FontFamily latin = new FontFamily.Builder(
                    new Font.Builder(context.getResources(), R.font.ibm_plex_mono).build()).build();
            FontFamily korean = new FontFamily.Builder(
                    new Font.Builder(context.getResources(), R.font.orbit).build()).build();
            return new Typeface.CustomFallbackBuilder(latin).addCustomFallback(korean).build();
        } catch (IOException e) {
            return context.getResources().getFont(R.font.orbit);
        }
    }

    /**
     * 한글을 단어 단위로 줄바꿈한다. Android는 한글을 글자 어디서나 끊어 "됩니/다."처럼 보이므로,
     * 한글 앞에 폭이 없는 연결 문자(WORD JOINER)를 넣어 띄어쓰기에서만 줄이 바뀌게 한다.
     */
    public static String keepWords(String text) {
        StringBuilder out = new StringBuilder(text.length() + text.length() / 2);
        for (int i = 0; i < text.length(); i++) {
            char current = text.charAt(i);
            out.append(current);
            if (i + 1 < text.length() && isHangul(text.charAt(i + 1)) && !Character.isWhitespace(current)) {
                out.append('\u2060');
            }
        }
        return out.toString();
    }

    private static boolean isHangul(char c) {
        return c >= 0xAC00 && c <= 0xD7A3;
    }

    public static int dp(Context context, float value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    /** 세로 배치에서 폭을 채우고 위에 간격을 둔다. */
    public static LinearLayout.LayoutParams matchWidth(Context context, int topMarginDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(context, topMarginDp);
        return params;
    }

    /** 가로 배치에서 남은 폭을 나눠 갖고 왼쪽에 간격을 둔다. */
    public static LinearLayout.LayoutParams weight(Context context, int leftMarginDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        params.leftMargin = dp(context, leftMarginDp);
        return params;
    }

    /** 바탕의 옅은 점 격자. 기기 패널 느낌을 주되 글자를 방해하지 않을 만큼만 보인다. */
    public static Drawable dotGrid(Context context) {
        int tile = dp(context, 18);
        Bitmap bitmap = Bitmap.createBitmap(tile, tile, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(BG);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(DOT);
        canvas.drawCircle(tile / 2f, tile / 2f, dp(context, 1), paint);
        BitmapDrawable drawable = new BitmapDrawable(context.getResources(), bitmap);
        drawable.setTileModeXY(Shader.TileMode.REPEAT, Shader.TileMode.REPEAT);
        return drawable;
    }

    public static GradientDrawable surface(Context context, int fill, int stroke, float radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(context, radiusDp));
        if (stroke != 0) drawable.setStroke(dp(context, 1), stroke);
        return drawable;
    }

    /** 작은 대문자 이름표. 계기판의 각인처럼 쓴다. */
    public static TextView label(Context context, String text) {
        TextView view = new TextView(context);
        view.setText(text);
        view.setTextColor(MUTED);
        view.setTextSize(13);
        view.setTypeface(BODY);
        return view;
    }

    public static TextView body(Context context, float sp, int color) {
        TextView view = new TextView(context);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setTypeface(BODY);
        view.setLineSpacing(0, 1.25f);
        return view;
    }

    /** 숫자·상태를 크게 읽는 값. */
    public static TextView readout(Context context, float sp) {
        TextView view = new TextView(context);
        view.setTextSize(sp);
        view.setTextColor(TEXT);
        view.setTypeface(DISPLAY);
        return view;
    }

    public static LinearLayout column(Context context) {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    public static LinearLayout row(Context context) {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setGravity(Gravity.CENTER_VERTICAL);
        return layout;
    }

    public static LinearLayout card(Context context) {
        LinearLayout card = column(context);
        card.setBackground(surface(context, PANEL, LINE, 22));
        int pad = dp(context, 16);
        card.setPadding(pad, pad, pad, pad);
        return card;
    }

    /** 이름표와 값을 담는 벤토 칸. */
    public static LinearLayout tile(Context context, String name, TextView value) {
        LinearLayout tile = card(context);
        tile.addView(label(context, name));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(context, 8);
        tile.addView(value, params);
        return tile;
    }

    public static Button button(Context context, String text, Style style, View.OnClickListener listener) {
        Button button = new Button(context);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(17);
        button.setTypeface(DISPLAY);
        button.setMinHeight(dp(context, 54));
        button.setMinimumHeight(dp(context, 54));
        button.setMinWidth(0);
        button.setMinimumWidth(0);
        button.setPadding(dp(context, 12), dp(context, 10), dp(context, 12), dp(context, 10));
        button.setStateListAnimator(pressAnimator());
        button.setOnClickListener(listener);
        applyStyle(button, style);
        return button;
    }

    public static void applyStyle(Button button, Style style) {
        Context context = button.getContext();
        int fill;
        int stroke;
        int textColor;
        switch (style) {
            case PRIMARY:
                fill = ACCENT;
                stroke = 0;
                textColor = ON_ACCENT;
                break;
            case ACCENT_LINE:
                fill = PANEL;
                stroke = ACCENT;
                textColor = ACCENT;
                break;
            case GHOST:
                fill = 0x00000000;
                stroke = LINE;
                textColor = MUTED;
                break;
            case QUIET:
            default:
                fill = RAISED;
                stroke = LINE;
                textColor = TEXT;
                break;
        }
        button.setTextColor(textColor);
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33FFFFFF),
                surface(context, fill, stroke, 18), surface(context, 0xFFFFFFFF, 0, 18)));
    }

    public static void setEnabled(View view, boolean enabled) {
        view.setEnabled(enabled);
        view.setAlpha(enabled ? 1f : 0.38f);
    }

    public static void styleInput(EditText input) {
        Context context = input.getContext();
        input.setTextColor(TEXT);
        input.setHintTextColor(MUTED);
        input.setTextSize(15);
        input.setTypeface(BODY);
        input.setBackground(surface(context, RAISED, LINE, 14));
        input.setPadding(dp(context, 14), dp(context, 12), dp(context, 14), dp(context, 12));
    }

    /** 누르면 살짝 눌리는 물리 버튼 느낌. */
    private static StateListAnimator pressAnimator() {
        StateListAnimator animator = new StateListAnimator();
        animator.addState(new int[]{android.R.attr.state_pressed}, scaleTo(0.97f, 70));
        animator.addState(new int[0], scaleTo(1f, 120));
        return animator;
    }

    private static AnimatorSet scaleTo(float scale, long durationMs) {
        AnimatorSet set = new AnimatorSet();
        set.playTogether(ObjectAnimator.ofFloat(null, View.SCALE_X, scale),
                ObjectAnimator.ofFloat(null, View.SCALE_Y, scale));
        set.setDuration(durationMs);
        return set;
    }

    /** 탭을 열 때 칸들이 위에서 아래로 차례로 나타난다. */
    public static void stagger(ViewGroup group) {
        float rise = dp(group.getContext(), 10);
        for (int i = 0; i < group.getChildCount(); i++) {
            View child = group.getChildAt(i);
            child.setAlpha(0f);
            child.setTranslationY(rise);
            float target = child.isEnabled() ? 1f : 0.38f;
            child.animate().alpha(target).translationY(0f).setStartDelay(i * 40L).setDuration(240)
                    .setInterpolator(new DecelerateInterpolator()).start();
        }
    }
}
