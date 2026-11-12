package com.hintringpilot.ringpilot.dev;

import android.content.Context;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.hintringpilot.ringpilot.ui.Ui;

import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Date;
import java.util.Locale;

/** 기록 탭(개발용 빌드에서만 보인다). 최근 이벤트 8개와 수집 사용법. 파일 기록은 ImuBleClient의 connection_log.csv가 맡는다. */
public final class LogPanel {
    private static final int MAX_EVENTS = 8;

    private final View page;
    private final TextView eventView;
    private final ArrayDeque<String> recent = new ArrayDeque<>();

    public LogPanel(Context context) {
        LinearLayout page = Ui.column(context);

        LinearLayout eventCard = Ui.card(context);
        eventCard.addView(Ui.label(context, "최근 이벤트"));
        eventView = Ui.body(context, 13, Ui.TEXT);
        eventView.setText("아직 이벤트가 없습니다");
        eventCard.addView(eventView, Ui.matchWidth(context, 10));
        page.addView(eventCard, Ui.matchWidth(context, 0));

        LinearLayout helpCard = Ui.card(context);
        helpCard.addView(Ui.label(context, "사용법"));
        TextView help = Ui.body(context, 13, Ui.MUTED);
        help.setText(Ui.keepWords("방향 안내 수집은 소리만 듣고 따라 하면 됩니다. 방향을 불러준 뒤 '삑' 소리가 나면 가만히 있고, 1초 뒤 '삐빅' 소리가 나면 움직입니다. 4초가 지나면 자동으로 저장됩니다.\n"
                + "잘못 움직였다면 '방금 것 다시'를 누릅니다.\n"
                + "링이 일시정지되거나 연결이 끊기면 안내도 함께 멈춥니다.\n"
                + "PC로 옮기려면 먼저 세션을 끝냅니다. tools/pull-phone-sessions.js로 옮기면 휴대폰에 있던 파일은 지워집니다."));
        helpCard.addView(help, Ui.matchWidth(context, 10));
        page.addView(helpCard, Ui.matchWidth(context, 10));
        this.page = page;
    }

    public View page() {
        return page;
    }

    /** 메인 스레드에서 부른다. */
    public void add(String text) {
        recent.addFirst(new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date()) + "  " + text);
        while (recent.size() > MAX_EVENTS) recent.removeLast();
        eventView.setText(String.join("\n", recent));
    }
}
