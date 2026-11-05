package com.hintringpilot.ringpilot;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Insets;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.hintringpilot.ringpilot.ui.DirectionDial;
import com.hintringpilot.ringpilot.ui.Ui;

import java.io.File;
import java.util.Locale;

/**
 * 앱 화면 하나. 위에서부터 이름·연결 상태·안내 버튼, 탭 내용, 탭 막대(개발용 빌드만)를 둔다.
 * 탭: 리모컨(RemotePanel), 수집(CollectPanel), 기록(LogPanel). 사용자 빌드(DEV_TOOLS=false)는 리모컨만 보인다.
 * 여기서는 화면 조립, 링 연결(ImuBleClient), 받은 제스처의 실행(판단은 GestureRouter)을 맡는다.
 */
public final class MainActivity extends Activity {
    private static final int REQUEST_BLUETOOTH_CONNECT = 100;
    private static final long STATUS_REFRESH_MS = 500;
    private static final String[] TAB_NAMES = {"리모컨", "수집", "기록"};

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final GestureRouter gestureRouter = new GestureRouter();
    private ImuBleClient client;
    private boolean swipeControl = false;  // 수집 중 스와이프가 나가지 않도록 기본은 끈다
    private volatile String connectionText = "연결 준비 중";

    private RemotePanel remote;
    private CollectPanel collect;
    private LogPanel log;
    private GuideDialogs guides;
    private final View[] pages = new View[3];
    private final TextView[] tabs = new TextView[3];
    private TextView connectionView;
    private TextView hzView;
    private View statusDot;
    private int statusDotColor = 0;
    private ScrollView scrollView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);  // 쓰는 동안·수집 중 화면 꺼짐 방지
        Ui.init(this);
        client = new ImuBleClient(this, new File(getExternalFilesDir(null), "connection_log.csv"), bleListener);
        setContentView(createContentView());
        connectRing();
        mainHandler.post(statusTicker);
        applyUiPreview();
    }

    @Override
    protected void onDestroy() {
        collect.shutdown();  // 앱을 닫아도 세션을 끝내 PC로 옮길 수 있게 한다
        mainHandler.removeCallbacksAndMessages(null);
        client.stop();
        super.onDestroy();
    }

    // ---------------------------------------------------------------- 화면

    private View createContentView() {
        LinearLayout root = Ui.column(this);
        root.setBackground(Ui.dotGrid(this));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsets.CONSUMED;
        });

        guides = new GuideDialogs(this, this::connectRing);
        root.addView(createTopBar(), Ui.matchWidth(this, 0));

        LinearLayout content = Ui.column(this);
        content.setPadding(Ui.dp(this, 16), Ui.dp(this, 4), Ui.dp(this, 16), Ui.dp(this, 20));

        TextView promptView = new TextView(this);
        DirectionDial dial = new DirectionDial(this, promptView);
        content.addView(dial, Ui.matchWidth(this, 0));

        log = new LogPanel(this);
        remote = new RemotePanel(this, this::toggleSwipeControl, this::connectRing);
        collect = new CollectPanel(this, mainHandler, dial, promptView,
                () -> client.isStreaming() && !client.isDevicePaused(), log::add, this::connectRing);
        pages[0] = remote.page();
        pages[1] = collect.page();
        pages[2] = log.page();
        LinearLayout.LayoutParams fill = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        fill.topMargin = Ui.dp(this, 12);
        content.addView(pages[0], fill);  // 리모컨 화면은 남은 높이를 채워 스크롤 없이 한 화면에 든다
        content.addView(pages[1], Ui.matchWidth(this, 16));
        content.addView(pages[2], Ui.matchWidth(this, 16));

        scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.addView(content);
        root.addView(scrollView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        View tabBar = createTabBar();
        if (!BuildConfig.DEV_TOOLS) tabBar.setVisibility(View.GONE);
        root.addView(tabBar, Ui.matchWidth(this, 0));

        selectTab(0);
        return root;
    }

    private View createTopBar() {
        LinearLayout bar = Ui.column(this);
        bar.setPadding(Ui.dp(this, 20), Ui.dp(this, 14), Ui.dp(this, 20), Ui.dp(this, 10));

        LinearLayout titleRow = Ui.row(this);
        TextView wordmark = new TextView(this);
        wordmark.setText("RINGPILOT");
        wordmark.setTextColor(Ui.TEXT);
        wordmark.setTextSize(15);
        wordmark.setTypeface(Ui.MONO_BOLD);
        wordmark.setLetterSpacing(0.24f);
        titleRow.addView(wordmark, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        hzView = Ui.label(this, "0 Hz");
        hzView.setTextColor(Ui.TEXT);
        hzView.setTextSize(13);
        hzView.setTypeface(Ui.MONO);
        if (!BuildConfig.DEV_TOOLS) hzView.setVisibility(View.GONE);
        titleRow.addView(hzView);
        bar.addView(titleRow, Ui.matchWidth(this, 0));

        LinearLayout statusRow = Ui.row(this);
        statusRow.setGravity(Gravity.TOP);  // 상태 문구가 두 줄이어도 점은 첫 줄에 맞춘다
        statusDot = new View(this);
        LinearLayout.LayoutParams dotParams = new LinearLayout.LayoutParams(Ui.dp(this, 8), Ui.dp(this, 8));
        dotParams.topMargin = Ui.dp(this, 6);
        statusRow.addView(statusDot, dotParams);
        connectionView = Ui.body(this, 13, Ui.MUTED);
        LinearLayout.LayoutParams statusText = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        statusText.leftMargin = Ui.dp(this, 8);
        statusRow.addView(connectionView, statusText);
        bar.addView(statusRow, Ui.matchWidth(this, 6));

        LinearLayout chips = Ui.row(this);
        chips.addView(guideChip("페어링 방법", GuideDialogs.PAIRING), Ui.weight(this, 0));
        chips.addView(guideChip("연결 방법", GuideDialogs.CONNECTING), Ui.weight(this, 8));
        bar.addView(chips, Ui.matchWidth(this, 10));
        return bar;
    }

    private TextView guideChip(String name, int which) {
        TextView chip = Ui.readout(this, 14);
        chip.setText(name);
        chip.setBackground(Ui.surface(this, Ui.PANEL, Ui.LINE, 14));
        chip.setGravity(Gravity.CENTER);
        chip.setMinHeight(Ui.dp(this, 40));
        chip.setOnClickListener(v -> guides.show(which));
        return chip;
    }

    private View createTabBar() {
        LinearLayout bar = Ui.row(this);
        bar.setBackgroundColor(Ui.PANEL);
        bar.setPadding(Ui.dp(this, 10), Ui.dp(this, 8), Ui.dp(this, 10), Ui.dp(this, 8));
        for (int i = 0; i < TAB_NAMES.length; i++) {
            int index = i;
            TextView tab = new TextView(this);
            tab.setText(TAB_NAMES[i]);
            tab.setGravity(Gravity.CENTER);
            tab.setTextSize(14);
            tab.setTypeface(Ui.DISPLAY);
            tab.setMinHeight(Ui.dp(this, 48));
            tab.setOnClickListener(v -> selectTab(index));
            tabs[i] = tab;
            bar.addView(tab, Ui.weight(this, i == 0 ? 0 : 6));
        }
        return bar;
    }

    private void selectTab(int index) {
        for (int i = 0; i < pages.length; i++) {
            boolean selected = i == index;
            pages[i].setVisibility(selected ? View.VISIBLE : View.GONE);
            tabs[i].setTextColor(selected ? Ui.ACCENT : Ui.MUTED);
            tabs[i].setBackground(selected ? Ui.surface(this, Ui.RAISED, Ui.LINE, 16) : null);
        }
        collect.setShown(index == 1);
        scrollView.scrollTo(0, 0);
        Ui.stagger((ViewGroup) pages[index]);
    }

    /** 0.5초마다 연결 상태와 수신 통계를 화면에 반영한다. */
    private final Runnable statusTicker = new Runnable() {
        @Override
        public void run() {
            String status = connectionText;
            setTextIfChanged(connectionView, Ui.keepWords(status));
            setTextIfChanged(hzView, String.format(Locale.US, "%.0f Hz", client.recentRate()));
            remote.updateStatus(swipeControl, SwipeAccessibilityService.getCurrent() != null, client.missingSamples());
            int color = statusColor(status);
            if (color != statusDotColor) {
                statusDotColor = color;
                GradientDrawable dot = new GradientDrawable();
                dot.setShape(GradientDrawable.OVAL);
                dot.setColor(color);
                statusDot.setBackground(dot);
            }
            mainHandler.postDelayed(this, STATUS_REFRESH_MS);
        }
    };

    private static void setTextIfChanged(TextView view, String text) {
        if (!text.contentEquals(view.getText())) view.setText(text);
    }

    private static int statusColor(String status) {
        if (status.startsWith("수신 중")) return Ui.OK;
        if (status.contains("일시정지") || status.contains("시도") || status.contains("설정 중") || status.contains("준비")) return Ui.WARN;
        return Ui.BAD;
    }

    // ---------------------------------------------------------------- 연결·제스처

    private void connectRing() {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_CONNECT}, REQUEST_BLUETOOTH_CONNECT);
            return;
        }
        client.stop();
        String error = client.start();
        if (error != null) connectionText = error;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_BLUETOOTH_CONNECT) return;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) connectRing();
        else connectionText = "주변 기기 권한이 필요합니다.";
    }

    private final ImuBleClient.Listener bleListener = new ImuBleClient.Listener() {
        @Override
        public void onSamples(long firstSlot, short[] raw, int count) {
            collect.recorder.acceptSamples(firstSlot, raw, count, SystemClock.elapsedRealtime());
        }

        @Override
        public void onConnectionText(String text) {
            connectionText = text;
        }

        @Override
        public void onGesture(String direction, int sequence, double score) {
            mainHandler.post(() -> applyGesture(direction, sequence, score));
        }
    };

    private void toggleSwipeControl() {
        swipeControl = !swipeControl;
        remote.setSwipeControl(swipeControl);
        client.record("swipe_control", swipeControl ? "on" : "off");
        if (swipeControl && SwipeAccessibilityService.getCurrent() == null) {
            log.add("접근성 설정에서 'RingPilot 스와이프'를 켭니다.");
            startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
        } else {
            log.add(swipeControl ? "스와이프 제어 켬. 이제 다른 앱으로 가도 됩니다." : "스와이프 제어 끔");
        }
    }

    /** 판단은 GestureRouter가 하고, 여기서는 실행하고 연결 기록에 남긴다. 실사용 시험 뒤 PC에서 맞춰 보기 위한 기록이다. */
    private void applyGesture(String direction, int sequence, double score) {
        SwipeAccessibilityService service = SwipeAccessibilityService.getCurrent();
        GestureRouter.Action action = gestureRouter.route(direction, swipeControl, service != null);
        client.record("app_gesture", action.logDetail(sequence, score));
        String result = "수신만";
        if (action.kind == GestureRouter.Kind.NO_SERVICE) {
            result = "접근성 서비스 꺼짐";
        } else if (action.kind == GestureRouter.Kind.MODE_CHANGED) {
            result = action.horizontalAfter ? "좌우 모드" : "상하 모드";
            service.showBanner(result);
        } else if (action.kind == GestureRouter.Kind.SWIPE) {
            String swipe = action.swipe;
            boolean sent = service.swipe(swipe, completed -> client.record("swipe_result",
                    GestureRouter.swipeDetail(sequence, swipe, completed ? "completed" : "cancelled")));
            if (!sent) client.record("swipe_result", GestureRouter.swipeDetail(sequence, swipe, "not_dispatched"));
            result = sent ? "스와이프 " + swipe : "스와이프 실패";
        }
        log.add(String.format(Locale.US, "제스처 %s (%.2f) → %s", direction, score, result));
        remote.setMode(action.horizontalAfter);
        remote.flash(direction);
    }

    // ---------------------------------------------------------------- 화면 미리보기

    /**
     * 디버그 빌드에서만 링 없이 화면 상태를 확인한다. 화면 값만 바꾸고 세션·파일은 만들지 않는다.
     * adb shell am start -n com.hintringpilot.ringpilot/.MainActivity --es ui_preview remote
     * 값: remote(기본), pairing, connect, collect, log, go, still
     */
    private void applyUiPreview() {
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) return;
        String preview = getIntent().getStringExtra("ui_preview");
        if (preview == null) return;
        connectionText = "수신 중";
        switch (preview) {
            case "pairing":
                guides.show(GuideDialogs.PAIRING);
                break;
            case "connect":
                guides.show(GuideDialogs.CONNECTING);
                break;
            case "collect":
            case "go":
            case "still":
                for (int i = 0; i < 4; i++) collect.recorder.savedCounts().put(CollectPanel.DIRECTION_LABELS[i], 3 + i % 2);
                selectTab(1);
                if (preview.equals("go")) collect.previewGuide(DirectionDial.Phase.GO);
                else if (preview.equals("still")) collect.previewGuide(DirectionDial.Phase.STILL);
                else collect.updateProgress();
                break;
            case "log":
                log.add("세션 시작 20261105-120000");
                log.add("제스처 UP (0.92) → 스와이프 UP");
                selectTab(2);
                break;
            default:
                swipeControl = true;
                remote.setSwipeControl(true);
                remote.flash("UP");
                break;
        }
    }
}
