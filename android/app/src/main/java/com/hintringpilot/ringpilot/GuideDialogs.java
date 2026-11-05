package com.hintringpilot.ringpilot;

import android.app.Activity;
import android.app.Dialog;
import android.content.Intent;
import android.graphics.drawable.ColorDrawable;
import android.provider.Settings;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.hintringpilot.ringpilot.ui.Ui;

/** 위쪽 "페어링 방법"·"연결 방법" 버튼으로 여는 안내 팝업. 메인 화면을 밀어내지 않는다. */
final class GuideDialogs {
    static final int PAIRING = 0;
    static final int CONNECTING = 1;

    private final Activity activity;
    private final Runnable reconnect;

    GuideDialogs(Activity activity, Runnable reconnect) {
        this.activity = activity;
        this.reconnect = reconnect;
    }

    void show(int which) {
        Dialog dialog = new Dialog(activity);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout box = which == PAIRING ? pairingCard() : connectingCard();
        box.setBackground(Ui.surface(activity, Ui.PANEL, Ui.LINE, 22));
        LinearLayout.LayoutParams close = Ui.matchWidth(activity, 10);
        box.addView(Ui.button(activity, "닫기", Ui.Style.QUIET, v -> dialog.dismiss()), close);
        ScrollView scroll = new ScrollView(activity);  // 작은 화면에서만 팝업 안이 스크롤된다
        scroll.addView(box);
        dialog.setContentView(scroll);
        Window window = dialog.getWindow();
        if (window != null) {
            window.setBackgroundDrawable(new ColorDrawable(0));
            window.setLayout(activity.getResources().getDisplayMetrics().widthPixels - Ui.dp(activity, 32),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }
        dialog.show();
    }

    private LinearLayout pairingCard() {
        return card("처음 한 번만 하면 됩니다.", new String[]{
                "링의 가운데 스위치를 눌러 전원을 켭니다.",
                "아래 버튼을 눌러 Bluetooth 설정을 엽니다.\n목록에서 RingPilot-IMU를 찾아 등록합니다.",
                "설정 화면에 '연결 안 됨'으로 나와도 괜찮습니다.\n연결은 앱을 열면 앱이 알아서 합니다.",
                "이제 앱으로 돌아가서 '연결 방법'을 보면 됩니다."
        }, Ui.button(activity, "Bluetooth 설정 열기", Ui.Style.QUIET,
                v -> activity.startActivity(new Intent(Settings.ACTION_BLUETOOTH_SETTINGS))));
    }

    private LinearLayout connectingCard() {
        return card("쓸 때마다 이것만 확인하면 됩니다.", new String[]{
                "휴대폰 Bluetooth와 링을 켭니다.",
                "앱을 열면 자동으로 연결됩니다.\n권한을 묻는 창이 뜨면 허용을 누릅니다.",
                "맨 위에 초록 점과 '수신 중'이 보이면\n연결된 겁니다.",
                "안 보이면 아래 버튼을 누릅니다.\n페어링을 막 끝냈다면 꼭 누릅니다.",
                "'링 일시정지됨'이 보일 때는\n가운데 스위치를 짧게 누르면 됩니다.",
                "화면까지 조작하려면 하나만 더 하면 됩니다.\n화면 아래 '스와이프 제어 켜기'를 누릅니다.\n접근성 설정에서 'RingPilot 스와이프'를 켭니다."
        }, Ui.button(activity, "링 다시 연결", Ui.Style.QUIET, v -> reconnect.run()));
    }

    /** 소개 한 줄, 번호 붙은 단계, 행동 버튼. 팝업을 열 때마다 새로 만든다. */
    private LinearLayout card(String intro, String[] steps, Button action) {
        LinearLayout card = Ui.card(activity);
        TextView introView = Ui.readout(activity, 16);
        introView.setText(Ui.keepWords(intro));
        card.addView(introView);
        for (int i = 0; i < steps.length; i++) {
            LinearLayout step = Ui.row(activity);
            step.setGravity(Gravity.TOP);
            TextView number = Ui.readout(activity, 14);
            number.setTypeface(Ui.MONO_BOLD);
            number.setTextColor(Ui.ACCENT);
            number.setText(String.valueOf(i + 1));
            step.addView(number, new LinearLayout.LayoutParams(Ui.dp(activity, 22), ViewGroup.LayoutParams.WRAP_CONTENT));
            TextView text = Ui.body(activity, 14, Ui.TEXT);
            text.setText(Ui.keepWords(steps[i]));
            step.addView(text, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            card.addView(step, Ui.matchWidth(activity, 10));
        }
        card.addView(action, Ui.matchWidth(activity, 14));
        return card;
    }
}
