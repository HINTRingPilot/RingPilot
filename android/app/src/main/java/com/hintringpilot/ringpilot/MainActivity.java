package com.hintringpilot.ringpilot;

import android.Manifest;
import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Insets;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.speech.tts.TextToSpeech;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.hintringpilot.ringpilot.ui.DirectionDial;
import com.hintringpilot.ringpilot.ui.Ui;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 링 IMU 데이터 수집 화면.
 * 안내 수집: 방향별 N회를 섞은 순서로 음성·소리 안내에 맞춰 4초씩 자동 기록한다.
 * 수동 기록: idle/other 10초, 길이 제한 없는 연속 기록.
 * 세션마다 폴더(files/sessions/날짜-시각)에 저장하며, PC로 옮기고 지우는 일은 tools/pull-phone-sessions.js가 맡는다.
 */
public final class MainActivity extends Activity {
    private static final int REQUEST_BLUETOOTH_CONNECT = 100;

    private static final String[] DIRECTION_LABELS = {"raw_up", "raw_down", "raw_left", "raw_right"};

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService fileWriter = Executors.newSingleThreadExecutor();
    private CaptureCoordinator coordinator;
    private CaptureCoordinator.Snapshot captureView;

    private ImuBleClient client;
    private TextToSpeech tts;
    private boolean ttsReady = false;
    private ToneGenerator tones;

    private TextView connectionView;
    private TextView promptView;
    private TextView progressView;
    private TextView eventView;
    private EditText memoInput;
    private EditText repeatInput;
    private Button sessionButton;
    private Button pauseButton;
    private Button continuousButton;
    private Button swipeButton;
    private Button redoButton;
    private Button guideStartButton, idleButton, otherButton;
    private DirectionDial dial;
    private TextView hzView;
    private TextView missingView;
    private TextView modeView;
    private TextView lastGestureView;
    private View statusDot;
    private int statusDotColor = 0;
    private ScrollView scrollView;
    private LinearLayout setupGroup;
    private LinearLayout controlsRow;
    private LinearLayout guidePanel;
    private final LinearLayout[] guideBodies = new LinearLayout[2];
    private final TextView[] guideChips = new TextView[2];
    private final String[] guideChipNames = new String[2];
    private int openGuide = -1;
    private final View[] pages = new View[3];
    private final TextView[] tabs = new TextView[3];
    private int selectedTab = 0;
    private boolean horizontalMode = false;  // 화면 표시용. 판단은 GestureRouter가 한다
    private boolean swipeControl = false;  // 수집 중 스와이프가 나가지 않도록 기본은 끈다
    private final GestureRouter gestureRouter = new GestureRouter();
    private volatile String connectionText = "연결 준비 중";
    private final ArrayDeque<String> recentEvents = new ArrayDeque<>();

    // Rendered snapshots are display data only; the coordinator is the sole state owner.
    private Map<String, Integer> previewCounts;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        coordinator = new CaptureCoordinator(new File(getExternalFilesDir(null), "sessions"),
                java.util.UUID.randomUUID().toString(), new CaptureCoordinator.Clock() {
                    public long elapsedMillis() { return SystemClock.elapsedRealtime(); }
                    public long wallMillis() { return System.currentTimeMillis(); }
                }, (action, delay) -> mainHandler.postDelayed(action, delay), new CaptureCoordinator.WriteQueue() {
                    public void execute(Runnable action) { fileWriter.execute(action); }
                    public void shutdown() { fileWriter.shutdown(); }
                }, captureListener);
        captureView = coordinator.snapshot();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);  // 수집 중 화면 꺼짐 방지
        Ui.init(this);
        setContentView(createContentView());

        tones = new ToneGenerator(AudioManager.STREAM_MUSIC, 90);
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                ttsReady = tts.setLanguage(Locale.KOREAN) >= TextToSpeech.LANG_AVAILABLE;
            }
        });
        client = new ImuBleClient(this, new File(getExternalFilesDir(null), "connection_log.csv"), bleListener);
        connectRing();
        mainHandler.post(statsTicker);
        applyUiPreview();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 접근성 설정에서 돌아왔을 때 다이얼 글자를 실제 상태에 맞춘다.
        if (swipeControl && !captureView.guideRunning && !captureActive()) prompt(controlPrompt());
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

        root.addView(createTopBar(), matchWidth(0));

        LinearLayout content = Ui.column(this);
        content.setPadding(dp(16), dp(4), dp(16), dp(20));

        guidePanel = createGuidePanel();
        content.addView(guidePanel, matchWidth(0));
        renderGuide();

        promptView = new TextView(this);
        promptView.setText("대기");
        dial = new DirectionDial(this, promptView);
        content.addView(dial, matchWidth(0));

        pages[0] = createRemotePage();
        pages[1] = createCollectPage();
        pages[2] = createLogPage();
        for (View page : pages) content.addView(page, matchWidth(16));

        scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.addView(content);
        root.addView(scrollView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        root.addView(createTabBar(), matchWidth(0));

        selectTab(0);
        updateProgress();
        return root;
    }

    private View createTopBar() {
        LinearLayout bar = Ui.column(this);
        bar.setPadding(dp(20), dp(14), dp(20), dp(10));

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
        titleRow.addView(hzView);
        bar.addView(titleRow, matchWidth(0));

        LinearLayout statusRow = Ui.row(this);
        statusDot = new View(this);
        statusRow.setGravity(Gravity.TOP);  // 상태 문구가 두 줄이어도 점은 첫 줄에 맞춘다
        LinearLayout.LayoutParams dotParams = new LinearLayout.LayoutParams(dp(8), dp(8));
        dotParams.topMargin = dp(6);
        statusRow.addView(statusDot, dotParams);
        connectionView = Ui.body(this, 13, Ui.MUTED);
        LinearLayout.LayoutParams statusText = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        statusText.leftMargin = dp(8);
        statusRow.addView(connectionView, statusText);
        bar.addView(statusRow, matchWidth(6));

        LinearLayout chips = Ui.row(this);
        String[] names = {"페어링 방법", "연결 방법"};
        for (int i = 0; i < names.length; i++) {
            int index = i;
            TextView chip = Ui.readout(this, 14);
            chip.setGravity(Gravity.CENTER);
            chip.setMinHeight(dp(40));
            chip.setOnClickListener(v -> toggleGuide(index));
            guideChips[i] = chip;
            guideChipNames[i] = names[i];
            chips.addView(chip, weight(i == 0 ? 0 : 8));
        }
        bar.addView(chips, matchWidth(10));
        return bar;
    }

    /** 위쪽 두 토글로 여닫는 가이드. 어느 탭에서든 열 수 있고, 한 번에 하나만 펼친다. */
    private LinearLayout createGuidePanel() {
        LinearLayout panel = Ui.column(this);
        panel.setVisibility(View.GONE);

        guideBodies[0] = guideCard("처음 한 번만 하면 됩니다.", new String[]{
                "링의 가운데 스위치를 눌러 전원을 켭니다.",
                "아래 버튼을 눌러 Bluetooth 설정을 엽니다.\n목록에서 RingPilot-IMU를 찾아 등록합니다.",
                "설정 화면에 '연결 안 됨'으로 나와도 괜찮습니다.\n연결은 앱을 열면 앱이 알아서 합니다.",
                "이제 앱으로 돌아가서 '연결 방법'을 보면 됩니다."
        }, Ui.button(this, "Bluetooth 설정 열기", Ui.Style.QUIET, v -> startActivity(
                new android.content.Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS))));

        guideBodies[1] = guideCard("쓸 때마다 이것만 확인하면 됩니다.", new String[]{
                "휴대폰 Bluetooth와 링을 켭니다.",
                "앱을 열면 자동으로 연결됩니다.\n권한을 묻는 창이 뜨면 허용을 누릅니다.",
                "맨 위에 초록 점과 '수신 중'이 보이면\n연결된 겁니다.",
                "안 보이면 아래 버튼을 누릅니다.\n페어링을 막 끝냈다면 꼭 누릅니다.",
                "'링 일시정지됨'이 보일 때는\n가운데 스위치를 짧게 누르면 됩니다.",
                "화면까지 조작하려면 하나만 더 하면 됩니다.\n리모컨 탭에서 '스와이프 제어 켜기'를 누릅니다.\n접근성 설정에서 'RingPilot 스와이프'를 켭니다."
        }, Ui.button(this, "링 다시 연결", Ui.Style.QUIET, v -> connectRing()));

        panel.addView(guideBodies[0], matchWidth(0));
        panel.addView(guideBodies[1], matchWidth(0));
        LinearLayout.LayoutParams gap = matchWidth(0);
        gap.height = dp(12);
        panel.addView(new View(this), gap);
        return panel;
    }

    private LinearLayout guideCard(String intro, String[] steps, Button action) {
        LinearLayout card = Ui.card(this);
        TextView introView = Ui.readout(this, 16);
        introView.setText(Ui.keepWords(intro));
        card.addView(introView);
        for (int i = 0; i < steps.length; i++) {
            LinearLayout step = Ui.row(this);
            step.setGravity(Gravity.TOP);
            TextView number = Ui.readout(this, 14);
            number.setTypeface(Ui.MONO_BOLD);
            number.setTextColor(Ui.ACCENT);
            number.setText(String.valueOf(i + 1));
            step.addView(number, new LinearLayout.LayoutParams(dp(22), ViewGroup.LayoutParams.WRAP_CONTENT));
            TextView text = Ui.body(this, 14, Ui.TEXT);
            text.setText(Ui.keepWords(steps[i]));
            step.addView(text, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            card.addView(step, matchWidth(10));
        }
        card.addView(action, matchWidth(14));
        return card;
    }

    private void toggleGuide(int index) {
        openGuide = openGuide == index ? -1 : index;
        renderGuide();
        if (openGuide >= 0) scrollView.scrollTo(0, 0);
    }

    private void renderGuide() {
        guidePanel.setVisibility(openGuide >= 0 ? View.VISIBLE : View.GONE);
        for (int i = 0; i < guideBodies.length; i++) {
            boolean open = i == openGuide;
            guideBodies[i].setVisibility(open ? View.VISIBLE : View.GONE);
            guideChips[i].setText(guideChipNames[i] + (open ? "  ▴" : "  ▾"));
            guideChips[i].setTextColor(open ? Ui.ACCENT : Ui.TEXT);
            guideChips[i].setBackground(Ui.surface(this, open ? Ui.RAISED : Ui.PANEL, open ? Ui.ACCENT : Ui.LINE, 14));
        }
    }

    private View createTabBar() {
        LinearLayout bar = Ui.row(this);
        bar.setBackgroundColor(Ui.PANEL);
        bar.setPadding(dp(10), dp(8), dp(10), dp(8));
        String[] names = {"리모컨", "수집", "기록"};
        for (int i = 0; i < names.length; i++) {
            int index = i;
            TextView tab = new TextView(this);
            tab.setText(names[i]);
            tab.setGravity(Gravity.CENTER);
            tab.setTextSize(14);
            tab.setTypeface(Ui.DISPLAY);
            tab.setMinHeight(dp(48));
            tab.setOnClickListener(v -> selectTab(index));
            tabs[i] = tab;
            bar.addView(tab, weight(i == 0 ? 0 : 6));
        }
        return bar;
    }

    /** 평소 쓰는 화면. 스와이프 제어와 지금 상태만 둔다. */
    private View createRemotePage() {
        LinearLayout page = Ui.column(this);

        swipeButton = Ui.button(this, "스와이프 제어 켜기", Ui.Style.ACCENT_LINE, v -> toggleSwipeControl());
        page.addView(swipeButton, matchWidth(0));

        LinearLayout tiles = Ui.row(this);
        tiles.setBaselineAligned(false);
        modeView = Ui.readout(this, 22);
        modeView.setText("상하");
        tiles.addView(Ui.tile(this, "모드", modeView), weight(0));
        missingView = Ui.readout(this, 22);
        missingView.setText("0");
        tiles.addView(Ui.tile(this, "누락 샘플", missingView), weight(10));
        page.addView(tiles, matchWidth(10));

        lastGestureView = Ui.readout(this, 17);
        lastGestureView.setText(Ui.keepWords("아직 받은 제스처가 없습니다"));
        page.addView(Ui.tile(this, "최근 제스처", lastGestureView), matchWidth(10));

        page.addView(Ui.button(this, "링 다시 연결", Ui.Style.GHOST, v -> connectRing()), matchWidth(10));
        return page;
    }

    /** 데이터 수집 화면. 안내 수집이 도는 동안에는 준비용 칸을 접어 다이얼에 집중한다. */
    private View createCollectPage() {
        LinearLayout page = Ui.column(this);

        controlsRow = Ui.row(this);
        pauseButton = Ui.button(this, "일시정지", Ui.Style.QUIET, v -> togglePause());
        controlsRow.addView(pauseButton, weight(0));
        redoButton = Ui.button(this, "방금 것 다시", Ui.Style.QUIET, v -> redoLast());
        controlsRow.addView(redoButton, weight(10));
        page.addView(controlsRow, matchWidth(0));

        setupGroup = Ui.column(this);

        // 메모는 세션을 시작할 때 저장되므로 시작 버튼과 같은 칸에 둔다.
        LinearLayout guideCard = Ui.card(this);
        guideCard.addView(Ui.label(this, "방향 안내 수집"));
        TextView guideHelp = Ui.body(this, 13, Ui.MUTED);
        guideHelp.setText(Ui.keepWords("방향을 불러주면 삑에 가만히, 삐빅에 움직입니다."));
        guideCard.addView(guideHelp, matchWidth(8));

        memoInput = new EditText(this);
        memoInput.setHint("세션 메모: 착용 손가락, 자세, 장소 등");
        Ui.styleInput(memoInput);
        guideCard.addView(memoInput, matchWidth(12));

        LinearLayout stepper = Ui.row(this);
        TextView stepperLabel = Ui.body(this, 14, Ui.TEXT);
        stepperLabel.setText("방향별 횟수");
        stepper.addView(stepperLabel, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Button minus = Ui.button(this, "−", Ui.Style.QUIET, v -> stepRepeat(-1));
        stepper.addView(minus, new LinearLayout.LayoutParams(dp(54), dp(54)));
        repeatInput = new EditText(this);
        repeatInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        repeatInput.setText("10");
        Ui.styleInput(repeatInput);
        repeatInput.setGravity(Gravity.CENTER);
        repeatInput.setTypeface(Ui.MONO_BOLD);
        repeatInput.setTextSize(18);
        repeatInput.setPadding(0, 0, 0, 0);
        LinearLayout.LayoutParams repeatParams = new LinearLayout.LayoutParams(dp(68), dp(54));
        repeatParams.setMargins(dp(8), 0, dp(8), 0);
        stepper.addView(repeatInput, repeatParams);
        Button plus = Ui.button(this, "+", Ui.Style.QUIET, v -> stepRepeat(1));
        stepper.addView(plus, new LinearLayout.LayoutParams(dp(54), dp(54)));
        guideCard.addView(stepper, matchWidth(12));

        guideStartButton = Ui.button(this, "방향 안내 수집 시작", Ui.Style.PRIMARY, v -> startGuide());
        guideCard.addView(guideStartButton, matchWidth(12));
        setupGroup.addView(guideCard, matchWidth(0));

        LinearLayout sessionCard = Ui.card(this);
        sessionCard.addView(Ui.label(this, "세션"));
        progressView = Ui.body(this, 14, Ui.TEXT);
        sessionCard.addView(progressView, matchWidth(8));
        setupGroup.addView(sessionCard, matchWidth(10));

        LinearLayout fixedRow = Ui.row(this);
        idleButton = Ui.button(this, "IDLE\n가만히 10초", Ui.Style.QUIET,
                v -> startFixedLong("idle", "가만히 10초", "가만히"));
        otherButton = Ui.button(this, "OTHER\n다른 움직임 10초", Ui.Style.QUIET,
                v -> startFixedLong("other", "명령 아닌 움직임 10초", "명령 아닌 움직임"));
        fixedRow.addView(idleButton, weight(0));
        fixedRow.addView(otherButton, weight(10));
        setupGroup.addView(fixedRow, matchWidth(10));

        continuousButton = Ui.button(this, "연속 기록 시작", Ui.Style.QUIET, v -> toggleContinuous());
        setupGroup.addView(continuousButton, matchWidth(10));
        page.addView(setupGroup, matchWidth(10));

        LinearLayout footer = Ui.row(this);
        sessionButton = Ui.button(this, "세션 종료", Ui.Style.GHOST, v -> endSession());
        footer.addView(sessionButton, weight(0));
        footer.addView(Ui.button(this, "링 다시 연결", Ui.Style.GHOST, v -> connectRing()), weight(10));
        page.addView(footer, matchWidth(10));
        return page;
    }

    private View createLogPage() {
        LinearLayout page = Ui.column(this);

        LinearLayout eventCard = Ui.card(this);
        eventCard.addView(Ui.label(this, "최근 이벤트"));
        eventView = Ui.body(this, 13, Ui.TEXT);
        eventView.setTypeface(Ui.BODY);
        eventView.setText("아직 이벤트가 없습니다");
        eventCard.addView(eventView, matchWidth(10));
        page.addView(eventCard, matchWidth(0));

        LinearLayout helpCard = Ui.card(this);
        helpCard.addView(Ui.label(this, "사용법"));
        TextView help = Ui.body(this, 13, Ui.MUTED);
        help.setText(Ui.keepWords("방향 안내 수집은 소리만 듣고 따라 하면 됩니다. 방향을 불러준 뒤 '삑' 소리가 나면 가만히 있고, 1초 뒤 '삐빅' 소리가 나면 움직입니다. 4초가 지나면 자동으로 저장됩니다.\n"
                + "잘못 움직였다면 '방금 것 다시'를 누릅니다.\n"
                + "링이 일시정지되거나 연결이 끊기면 안내도 함께 멈춥니다.\n"
                + "PC로 옮기려면 먼저 세션을 끝냅니다. tools/pull-phone-sessions.js로 옮기면 휴대폰에 있던 파일은 지워집니다."));
        helpCard.addView(help, matchWidth(10));
        page.addView(helpCard, matchWidth(10));
        return page;
    }

    private void selectTab(int index) {
        selectedTab = index;
        for (int i = 0; i < pages.length; i++) {
            pages[i].setVisibility(i == index ? View.VISIBLE : View.GONE);
            boolean selected = i == index;
            tabs[i].setTextColor(selected ? Ui.ACCENT : Ui.MUTED);
            tabs[i].setBackground(selected ? Ui.surface(this, Ui.RAISED, Ui.LINE, 16) : null);
        }
        dial.setVisibility(index == 2 ? View.GONE : View.VISIBLE);
        updateDialLabels();
        updateDialSize();
        scrollView.scrollTo(0, 0);
        Ui.stagger((ViewGroup) pages[index]);
    }

    /** 리모컨 탭은 그 방향이 하는 일을, 수집 탭은 저장한 개수를 화살표 옆에 표시한다. */
    private void updateDialLabels() {
        if (selectedTab == 1) {
            dial.setLabels(countText("raw_up"), countText("raw_down"), countText("raw_left"), countText("raw_right"));
        } else if (horizontalMode) {
            dial.setLabels("왼쪽", "오른쪽", "전환", "전환");
        } else {
            dial.setLabels("위", "아래", "전환", "전환");
        }
    }

    /** 수집 준비 중에는 다이얼을 줄여 시작 버튼이 한 화면에 들어오게 하고, 안내가 돌면 크게 키운다. */
    private void updateDialSize() {
        dial.setCompact(selectedTab == 1 && !(captureView.guideRunning && !captureView.guidePaused));
    }

    private String countText(String label) {
        return String.valueOf((previewCounts == null ? captureView.savedCounts : previewCounts).getOrDefault(label, 0));
    }

    private void stepRepeat(int delta) {
        int value;
        try {
            value = Integer.parseInt(repeatInput.getText().toString().trim());
        } catch (NumberFormatException e) {
            value = 10;
        }
        repeatInput.setText(String.valueOf(Math.max(1, Math.min(100, value + delta))));
    }

    private String controlPrompt() {
        if (!swipeControl) return "대기";
        return SwipeAccessibilityService.getCurrent() != null ? "제어 중" : "접근성\n켜기 필요";
    }

    private LinearLayout.LayoutParams weight(int leftMarginDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        params.leftMargin = dp(leftMarginDp);
        return params;
    }

    private LinearLayout.LayoutParams matchWidth(int topMarginDp) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(topMarginDp);
        return params;
    }

    private int dp(int value) {
        return Ui.dp(this, value);
    }

    private void prompt(String text) {
        promptView.setText(text);
    }

    /**
     * 디버그 빌드에서만 링 없이 화면 상태를 확인한다. 화면 값만 바꾸고 세션·파일은 만들지 않는다.
     * adb shell am start -n com.hintringpilot.ringpilot/.MainActivity --es ui_preview go
     */
    private void applyUiPreview() {
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) return;
        String preview = getIntent().getStringExtra("ui_preview");
        if (preview == null) return;
        connectionText = "수신 중";
        previewCounts = new LinkedHashMap<>();
        previewCounts.put("raw_up", 3);
        previewCounts.put("raw_down", 4);
        previewCounts.put("raw_left", 2);
        previewCounts.put("raw_right", 3);
        switch (preview) {
            case "pairing":
                previewCounts.clear();
                toggleGuide(0);
                break;
            case "connect":
                previewCounts.clear();
                toggleGuide(1);
                break;
            case "collect":
                selectTab(1);
                break;
            case "log":
                event("세션 시작 20261105-120000");
                event("제스처 UP (0.92) → 스와이프 UP");
                selectTab(2);
                break;
            case "go":
                selectTab(1);
                prompt("지금! 위↑");
                dial.setPhase(DirectionDial.Phase.GO, "raw_up");
                break;
            case "still":
                selectTab(1);
                prompt("가만히…");
                dial.setPhase(DirectionDial.Phase.STILL, "raw_up");
                break;
            default:
                previewCounts.clear();
                swipeControl = true;
                Ui.applyStyle(swipeButton, Ui.Style.PRIMARY);
                swipeButton.setText("스와이프 제어 끄기");
                prompt("제어 중");
                lastGestureView.setText("위 · 0.92 → 스와이프 UP");
                dial.flash("UP");
                break;
        }
        updateProgress();
    }

    private void event(String text) {
        String line = new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date()) + "  " + text;
        recentEvents.addFirst(line);
        while (recentEvents.size() > 8) recentEvents.removeLast();
        eventView.setText(String.join("\n", recentEvents));
    }

    private void speak(String text) {
        if (ttsReady) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "prompt");
    }

    private void tone(int toneType) {
        tones.startTone(toneType, 150);
    }

    private void updateProgress() {
        StringBuilder sb = new StringBuilder();
        File dir = captureView.directory;
        sb.append(dir == null ? (captureView.hasSession ? "세션 준비 중" : "세션 없음") : "세션 " + dir.getName());
        if (captureView.closing) sb.append(" · 저장·종료 중");
        if (captureView.guideRunning) sb.append(" · 안내 ").append(Math.min(captureView.guideIndex, captureView.guideSize)).append('/').append(captureView.guideSize);
        sb.append('\n');
        Map<String, Integer> counts = previewCounts == null ? captureView.savedCounts : previewCounts;
        if (counts.isEmpty()) {
            sb.append("저장한 기록 없음");
        } else {
            for (Map.Entry<String, Integer> entry : counts.entrySet()) {
                sb.append(displayName(entry.getKey())).append(' ').append(entry.getValue()).append("  ");
            }
        }
        progressView.setText(sb.toString().trim());
        pauseButton.setText(captureView.guidePaused ? "계속" : "일시정지");
        Ui.setEnabled(sessionButton, captureView.canEndSession);
        Ui.setEnabled(pauseButton, captureView.canPauseGuide || captureView.canResumeGuide);
        Ui.setEnabled(redoButton, captureView.canRedo);
        Ui.setEnabled(guideStartButton, captureView.canStartGuide);
        Ui.setEnabled(idleButton, captureView.canStartManual);
        Ui.setEnabled(otherButton, captureView.canStartManual);
        Ui.setEnabled(continuousButton, captureView.canToggleContinuous);
        boolean focused = captureView.guideRunning && !captureView.guidePaused;
        setupGroup.setVisibility(focused ? View.GONE : View.VISIBLE);
        controlsRow.setVisibility(captureView.guideRunning || captureView.lastSavedFile != null ? View.VISIBLE : View.GONE);
        updateDialSize();
        dial.setProgress(captureView.guideRunning && captureView.guideSize > 0
                ? Math.min(captureView.guideIndex, captureView.guideSize) / (float) captureView.guideSize : 0f);
        boolean continuous = captureView.target == 0 && captureActive();
        continuousButton.setText(continuous ? "연속 기록 중지" : "연속 기록 시작");
        Ui.applyStyle(continuousButton, continuous ? Ui.Style.PRIMARY : Ui.Style.QUIET);
        updateDialLabels();
    }

    private static String displayName(String label) {
        switch (label) {
            case "raw_up": return "위↑";
            case "raw_down": return "아래↓";
            case "raw_left": return "왼쪽←";
            case "raw_right": return "오른쪽→";
            default: return label;
        }
    }

    private static String spokenName(String label) {
        switch (label) {
            case "raw_up": return "위";
            case "raw_down": return "아래";
            case "raw_left": return "왼쪽";
            case "raw_right": return "오른쪽";
            default: return label;
        }
    }

    private void toggleSwipeControl() {
        swipeControl = !swipeControl;
        swipeButton.setText(swipeControl ? "스와이프 제어 끄기" : "스와이프 제어 켜기");
        Ui.applyStyle(swipeButton, swipeControl ? Ui.Style.PRIMARY : Ui.Style.ACCENT_LINE);
        if (!captureView.guideRunning && !captureActive()) prompt(controlPrompt());
        client.record("swipe_control", swipeControl ? "on" : "off");
        if (swipeControl && SwipeAccessibilityService.getCurrent() == null) {
            event("접근성 설정에서 'RingPilot 스와이프'를 켭니다.");
            startActivity(new android.content.Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS));
        } else {
            event(swipeControl ? "스와이프 제어 켬. 이제 다른 앱으로 가도 됩니다." : "스와이프 제어 끔");
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
        event(String.format(Locale.US, "제스처 %s (%.2f) → %s", direction, score, result));
        horizontalMode = action.horizontalAfter;
        modeView.setText(horizontalMode ? "좌우" : "상하");
        lastGestureView.setText(String.format(Locale.US, "%s · %.2f → %s", direction, score, result));
        updateDialLabels();
        dial.flash(direction);
    }

    private final Runnable statsTicker = new Runnable() {
        @Override
        public void run() {
            String status = connectionText;
            setTextIfChanged(connectionView, Ui.keepWords(status));
            setTextIfChanged(hzView, String.format(Locale.US, "%.0f Hz", client.recentRate()));
            setTextIfChanged(missingView, String.valueOf(client.missingSamples()));
            int color = statusColor(status);
            if (color != statusDotColor) {
                statusDotColor = color;
                GradientDrawable dot = new GradientDrawable();
                dot.setShape(GradientDrawable.OVAL);
                dot.setColor(color);
                statusDot.setBackground(dot);
            }
            mainHandler.postDelayed(this, 500);
        }
    };

    /** 값이 그대로면 다시 그리지 않는다(0.5초마다 불린다). */
    private static void setTextIfChanged(TextView view, String text) {
        if (!text.contentEquals(view.getText())) view.setText(text);
    }

    private static int statusColor(String status) {
        if (status.startsWith("수신 중")) return Ui.OK;
        if (status.contains("일시정지") || status.contains("시도") || status.contains("설정 중") || status.contains("준비")) return Ui.WARN;
        return Ui.BAD;
    }

    // ---------------------------------------------------------------- 연결

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
        public void onSamples(long generation, long firstSlot, short[] raw, int count) {
            coordinator.onSamples(generation, firstSlot, raw, count, SystemClock.elapsedRealtime());
        }

        @Override
        public void onStreamReady(long generation) { coordinator.onStreamReady(generation); }

        @Override
        public void onStreamBoundary(long generation, String reason) { coordinator.onStreamBoundary(generation, reason); }

        @Override
        public void onConnectionText(String text) {
            connectionText = text;
        }

        @Override
        public void onGesture(String direction, int sequence, double score) {
            mainHandler.post(() -> applyGesture(direction, sequence, score));
        }
    };

    // ---------------------------------------------------------------- coordinator adapter

    private boolean captureActive() {
        return coordinator.snapshot().state != CaptureCoordinator.State.IDLE;
    }

    private void endSession() { coordinator.endSession(); }

    private void startGuide() {
        int repeat;
        try { repeat = Integer.parseInt(repeatInput.getText().toString().trim()); }
        catch (NumberFormatException error) { repeat = 0; }
        if (repeat <= 0 || repeat > 100) {
            Toast.makeText(this, "방향별 횟수는 1~100으로 입력하세요.", Toast.LENGTH_SHORT).show();
            return;
        }
        ArrayList<String> labels = new ArrayList<>();
        for (int i = 0; i < repeat; i++) Collections.addAll(labels, DIRECTION_LABELS);
        Collections.shuffle(labels);
        if (!coordinator.startGuide(labels, memoInput.getText().toString())) {
            Toast.makeText(this, "진행 중인 기록·저장을 먼저 끝내세요.", Toast.LENGTH_SHORT).show();
        } else event("안내 수집 시작: 방향별 " + repeat + "회");
    }

    private void togglePause() {
        if (!coordinator.toggleGuidePause()) {
            Toast.makeText(this, "진행 중인 수동 기록·저장을 먼저 끝내세요.", Toast.LENGTH_SHORT).show();
        }
    }

    private void redoLast() {
        if (!coordinator.redoLast()) Toast.makeText(this, "진행 중인 기록·저장을 끝낸 뒤 다시 하세요.", Toast.LENGTH_SHORT).show();
    }

    private void startFixedLong(String label, String promptText, String spoken) {
        if (!coordinator.requestManual(label, CaptureCoordinator.FIXED_LONG_SAMPLES, memoInput.getText().toString())) {
            Toast.makeText(this, "수신 상태를 확인하고 안내를 일시정지하거나 기록·저장을 끝내세요.", Toast.LENGTH_SHORT).show();
        }
    }

    private void toggleContinuous() {
        CaptureCoordinator.Snapshot value = coordinator.snapshot();
        if (value.target == 0 && value.state != CaptureCoordinator.State.IDLE) coordinator.stopCapture();
        else if (!coordinator.requestManual("continuous", 0, memoInput.getText().toString())) {
            Toast.makeText(this, "수신 상태를 확인하고 안내를 일시정지하거나 기록·저장을 끝내세요.", Toast.LENGTH_SHORT).show();
        }
    }

    private final CaptureCoordinator.Listener captureListener = new CaptureCoordinator.Listener() {
        public void onChanged(CaptureCoordinator.Snapshot value) {
            captureView = value;
            updateProgress();
        }
        public void onError(String message) { event(message); prompt("저장 실패 · 기록 확인"); }
        public void onCue(CaptureCoordinator.Cue cue, String label) {
            switch (cue) {
                case ARMED:
                    prompt("idle".equals(label) ? "가만히 10초" : "other".equals(label) ? "명령 아닌 움직임 10초" : "다음: " + displayName(label));
                    dial.setPhase(DirectionDial.Phase.ARMED, label);
                    speak("idle".equals(label) ? "가만히" : "other".equals(label) ? "명령 아닌 움직임" : spokenName(label));
                    break;
                case STILL:
                    tone(ToneGenerator.TONE_PROP_BEEP);
                    prompt(label.startsWith("raw_") ? "가만히…" : label + " 기록 중…");
                    dial.setPhase(DirectionDial.Phase.STILL, label);
                    break;
                case GO:
                    tone(ToneGenerator.TONE_PROP_BEEP2);
                    prompt("지금! " + displayName(label));
                    dial.setPhase(DirectionDial.Phase.GO, label);
                    break;
                case SAVED:
                    tone(ToneGenerator.TONE_PROP_ACK);
                    prompt("저장"); dial.setPhase(DirectionDial.Phase.SAVED, null);
                    event(displayName(label) + " 저장");
                    break;
                case FAILED:
                    prompt("기록 중단 · 다시 시도"); dial.setPhase(DirectionDial.Phase.IDLE, null);
                    event(displayName(label) + " 기록 실패·중단");
                    break;
                case WAITING:
                    prompt("링 연결·재개 대기"); dial.setPhase(DirectionDial.Phase.IDLE, null); break;
                case PAUSED:
                    prompt("일시정지"); dial.setPhase(DirectionDial.Phase.IDLE, null); event("안내 일시정지"); break;
                case GUIDE_DONE:
                    prompt("안내 수집 완료"); dial.setPhase(DirectionDial.Phase.SAVED, null); speak("끝"); event("안내 수집 완료"); break;
                case SESSION_CLOSED:
                    prompt("세션 종료"); dial.setPhase(DirectionDial.Phase.IDLE, null); event("세션 저장·종료 완료"); break;
                case REDONE:
                    prompt("방금 것 삭제 · 다시 합니다"); dial.setPhase(DirectionDial.Phase.IDLE, null); event(label + " 삭제"); break;
            }
        }
    };

    @Override
    protected void onDestroy() {
        coordinator.close();
        client.stop();
        mainHandler.removeCallbacksAndMessages(null);
        if (tts != null) tts.shutdown();
        if (tones != null) tones.release();
        super.onDestroy();
    }
}
