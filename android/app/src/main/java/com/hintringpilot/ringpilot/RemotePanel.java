package com.hintringpilot.ringpilot;

import android.content.Context;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.hintringpilot.ringpilot.ui.Ui;

/**
 * 평소 쓰는 리모컨 화면. 제스처마다 하는 일을 세 줄로 크게 보이고, 제스처가 오면 그 줄이 잠깐 빛난다.
 * 그 아래 모드 띠(상하/좌우, 제어 상태), 스와이프 제어 버튼, 링 다시 연결 버튼을 둔다. 세 줄이 남은 높이를 나눠 가져 스크롤 없이 한 화면에 든다.
 */
final class RemotePanel {
    private static final long FLASH_MS = 700;
    private static final String[] GLYPHS = {"▲", "▼", "◀ ▶"};
    private static final String[] NAMES = {"위", "아래", "좌우"};

    private final Context context;
    private final View page;
    private final LinearLayout[] rows = new LinearLayout[3];  // 위, 아래, 좌우
    private final TextView[] actions = new TextView[3];
    private final TextView modeView;
    private final TextView controlView;
    private final TextView missingView;
    private final Button swipeButton;

    RemotePanel(Context context, Runnable toggleSwipe, Runnable reconnect) {
        this.context = context;
        LinearLayout page = Ui.column(context);

        for (int i = 0; i < 3; i++) {
            rows[i] = gestureRow(i);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
            params.topMargin = Ui.dp(context, i == 0 ? 0 : 10);
            page.addView(rows[i], params);
        }

        LinearLayout modeBar = Ui.row(context);
        modeBar.setPadding(Ui.dp(context, 20), Ui.dp(context, 12), Ui.dp(context, 16), Ui.dp(context, 12));
        modeBar.setBackground(Ui.surface(context, Ui.PANEL, Ui.LINE, 22));
        modeBar.addView(Ui.label(context, "모드"));
        modeView = Ui.readout(context, 22);
        LinearLayout.LayoutParams modeParams = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        modeParams.leftMargin = Ui.dp(context, 12);
        modeBar.addView(modeView, modeParams);
        controlView = new TextView(context);
        controlView.setTextSize(12);
        controlView.setTypeface(Ui.BODY);
        controlView.setPadding(Ui.dp(context, 10), Ui.dp(context, 4), Ui.dp(context, 10), Ui.dp(context, 4));
        modeBar.addView(controlView);
        page.addView(modeBar, Ui.matchWidth(context, 10));

        missingView = Ui.readout(context, 22);
        missingView.setText("0");
        LinearLayout missingTile = Ui.tile(context, "누락 샘플", missingView);
        if (!BuildConfig.DEV_TOOLS) missingTile.setVisibility(View.GONE);
        page.addView(missingTile, Ui.matchWidth(context, 10));

        swipeButton = Ui.button(context, "", Ui.Style.ACCENT_LINE, v -> toggleSwipe.run());
        page.addView(swipeButton, Ui.matchWidth(context, 12));
        page.addView(Ui.button(context, "링 다시 연결", Ui.Style.GHOST, v -> reconnect.run()), Ui.matchWidth(context, 8));
        this.page = page;

        setMode(false);
        setSwipeControl(false);
    }

    private LinearLayout gestureRow(int i) {
        LinearLayout row = Ui.row(context);
        row.setPadding(Ui.dp(context, 20), Ui.dp(context, 12), Ui.dp(context, 20), Ui.dp(context, 12));
        row.setBackground(Ui.surface(context, Ui.PANEL, Ui.LINE, 22));
        TextView glyph = new TextView(context);
        glyph.setText(GLYPHS[i]);
        glyph.setTextColor(Ui.ACCENT);
        glyph.setTextSize(20);
        glyph.setGravity(Gravity.CENTER);
        row.addView(glyph, new LinearLayout.LayoutParams(Ui.dp(context, 56), ViewGroup.LayoutParams.WRAP_CONTENT));
        TextView name = Ui.body(context, 15, Ui.MUTED);
        name.setText(NAMES[i]);
        row.addView(name, new LinearLayout.LayoutParams(Ui.dp(context, 56), ViewGroup.LayoutParams.WRAP_CONTENT));
        actions[i] = Ui.readout(context, 26);
        actions[i].setGravity(Gravity.END);
        row.addView(actions[i], new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return row;
    }

    View page() {
        return page;
    }

    /** 모드에 따라 위·아래가 하는 일을 바꿔 적는다. */
    void setMode(boolean horizontal) {
        modeView.setText(horizontal ? "좌우" : "상하");
        actions[0].setText(horizontal ? "왼쪽으로 넘기기" : "위로 넘기기");
        actions[1].setText(horizontal ? "오른쪽으로 넘기기" : "아래로 넘기기");
        actions[2].setText("모드 전환");
    }

    void setSwipeControl(boolean on) {
        swipeButton.setText(on ? "스와이프 제어 끄기" : "스와이프 제어 켜기");
        Ui.applyStyle(swipeButton, on ? Ui.Style.PRIMARY : Ui.Style.ACCENT_LINE);
    }

    /** 받은 제스처의 줄을 잠깐 강조한다. */
    void flash(String direction) {
        int index = "UP".equals(direction) ? 0 : "DOWN".equals(direction) ? 1 : 2;
        LinearLayout row = rows[index];
        if (row.getTag() instanceof Runnable) row.removeCallbacks((Runnable) row.getTag());
        row.setBackground(Ui.surface(context, Ui.RAISED, Ui.ACCENT, 22));
        actions[index].setTextColor(Ui.ACCENT);
        Runnable restore = () -> {
            row.setBackground(Ui.surface(context, Ui.PANEL, Ui.LINE, 22));
            actions[index].setTextColor(Ui.TEXT);
        };
        row.setTag(restore);
        row.postDelayed(restore, FLASH_MS);
    }

    /** 0.5초마다 불린다. 접근성이 꺼져 있으면 눈에 띄게 알린다. */
    void updateStatus(boolean swipeControl, boolean serviceOn, long missingSamples) {
        String text;
        int color;
        if (!swipeControl) {
            text = "제어 꺼짐";
            color = Ui.MUTED;
        } else if (serviceOn) {
            text = "제어 중";
            color = Ui.OK;
        } else {
            text = "접근성 켜기 필요";
            color = Ui.WARN;
        }
        if (!text.contentEquals(controlView.getText())) {
            controlView.setText(text);
            controlView.setTextColor(color);
            controlView.setBackground(Ui.surface(context, Ui.BG, color, 99));
        }
        String missing = String.valueOf(missingSamples);
        if (!missing.contentEquals(missingView.getText())) missingView.setText(missing);
    }
}
