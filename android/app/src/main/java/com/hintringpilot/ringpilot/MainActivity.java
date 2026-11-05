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
import java.io.FileWriter;
import java.io.IOException;
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

    // 원시값 환산(펌웨어 ±4 g, ±2000 dps 설정, LSM6DS3 라이브러리 calcAccel/calcGyro와 동일)
    private static final double ACC_MS2_PER_LSB = 0.061 * 2 / 1000.0 * 9.80665;
    private static final double GYRO_DPS_PER_LSB = 4.375 * 16 / 1000.0;
    private static final int GYRO_RANGE_DPS = 2000;

    private static final int GESTURE_SAMPLES = 400;     // 4초. 1초 대기 뒤 동작·자연 복귀·안정 구간까지 담는다
    private static final int FIXED_LONG_SAMPLES = 1000; // idle/other 10초
    private static final long PROMPT_MS = 1200;         // 방향 안내 후 기록 시작까지
    private static final long PRE_ROLL_MS = 1000;       // 기록 시작 후 "지금" 신호까지(가만히 있는 구간)
    private static final long REST_MS = 1000;           // 저장 후 다음 안내까지
    private static final long TIMEOUT_EXTRA_MS = 2500;  // 정해진 길이 기록이 이만큼 더 늦으면 실패 처리
    private static final String SESSION_DONE_MARKER = "SESSION_DONE";

    private static final String[] DIRECTION_LABELS = {"raw_up", "raw_down", "raw_left", "raw_right"};

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService fileWriter = Executors.newSingleThreadExecutor();
    private final Object captureLock = new Object();

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
    private DirectionDial dial;
    private TextView hzView;
    private TextView missingView;
    private TextView modeView;
    private TextView lastGestureView;
    private TextView controlView;                       // 리모컨 화면의 제어 상태(제어 중·꺼짐·접근성 필요)
    private final LinearLayout[] mapRows = new LinearLayout[3];   // 위, 아래, 좌우
    private final TextView[] mapActions = new TextView[3];
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

    // 세션
    private File sessionDir;
    private final String activityInstanceId = java.util.UUID.randomUUID().toString();
    private final Map<String, Integer> savedCounts = new LinkedHashMap<>();
    private final Map<String, Integer> nextIndex = new LinkedHashMap<>();

    // 기록. capture는 Bluetooth 스레드와 공유하므로 captureLock으로 보호한다.
    private Capture capture;
    private File lastSavedFile;
    private String lastSavedLabel;

    // 안내 수집
    private final ArrayList<String> guideQueue = new ArrayList<>();
    private int guideIndex = 0;
    private boolean guideRunning = false;
    private boolean guidePaused = false;
    private int guideGeneration = 0;  // 늘리면 예약된 안내 단계가 모두 무효가 된다

    private interface CaptureDone {
        void finished(Capture c, boolean ok, String reason);
    }

    private static final class Capture {
        final String label;
        final int target;  // 0 이하면 길이 제한 없음(연속 기록)
        final File file;
        final CaptureDone done;
        final StringBuilder rows = new StringBuilder();
        final long startedAt;
        final CaptureSidecar sidecar;
        long endedAt;
        boolean csvWriteFailed; // accessed only by fileWriter
        long firstSlot = -1;
        long nextSlot = -1;
        int count = 0;
        long gapSamples = 0;
        boolean finished = false;

        Capture(String label, int target, File file, CaptureDone done, long startedAt, String activityId) {
            this.label = label;
            this.target = target;
            this.file = file;
            this.done = done;
            this.startedAt = startedAt;
            this.sidecar = new CaptureSidecar(file.getName(), target, startedAt,
                    file.getParentFile().getName(), activityId);
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
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
        if (swipeControl && !guideRunning && !captureActive()) prompt(controlPrompt());
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
        LinearLayout.LayoutParams fill = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        fill.topMargin = dp(12);
        content.addView(pages[0], fill);  // 리모컨 화면은 남은 높이를 채워 스크롤 없이 한 화면에 든다
        content.addView(pages[1], matchWidth(16));
        content.addView(pages[2], matchWidth(16));

        scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.addView(content);
        root.addView(scrollView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        View tabBar = createTabBar();
        if (!BuildConfig.DEV_TOOLS) tabBar.setVisibility(View.GONE);  // 사용자 빌드는 리모컨 화면만 둔다
        root.addView(tabBar, matchWidth(0));

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
        if (!BuildConfig.DEV_TOOLS) hzView.setVisibility(View.GONE);
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

    /** 평소 쓰는 화면. 지금 모드에서 각 제스처가 하는 일을 크게 보이고, 제스처가 오면 그 줄이 빛난다. */
    private View createRemotePage() {
        LinearLayout page = Ui.column(this);

        LinearLayout hero = Ui.card(this);
        hero.setPadding(dp(20), dp(18), dp(20), dp(18));
        LinearLayout head = Ui.row(this);
        head.addView(Ui.label(this, "지금 모드"), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        controlView = new TextView(this);
        controlView.setTextSize(12);
        controlView.setTypeface(Ui.BODY);
        controlView.setPadding(dp(10), dp(4), dp(10), dp(4));
        head.addView(controlView);
        hero.addView(head, matchWidth(0));

        modeView = Ui.readout(this, 64);
        modeView.setText("상하");
        modeView.setIncludeFontPadding(false);
        hero.addView(modeView, matchWidth(10));
        TextView hint = Ui.body(this, 13, Ui.MUTED);
        hint.setText(Ui.keepWords("좌우 제스처로 상하·좌우 모드를 바꿉니다"));
        hero.addView(hint, matchWidth(4));

        hero.addView(new View(this), new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        String[] glyphs = {"▲", "▼", "◀ ▶"};
        String[] names = {"위", "아래", "좌우"};
        for (int i = 0; i < 3; i++) {
            LinearLayout row = Ui.row(this);
            row.setPadding(dp(12), dp(10), dp(12), dp(10));
            row.setBackground(Ui.surface(this, Ui.RAISED, 0, 14));
            TextView glyph = new TextView(this);
            glyph.setText(glyphs[i]);
            glyph.setTextColor(Ui.ACCENT);
            glyph.setTextSize(15);
            glyph.setGravity(Gravity.CENTER);
            row.addView(glyph, new LinearLayout.LayoutParams(dp(48), ViewGroup.LayoutParams.WRAP_CONTENT));
            TextView name = Ui.body(this, 14, Ui.MUTED);
            name.setText(names[i]);
            row.addView(name, new LinearLayout.LayoutParams(dp(48), ViewGroup.LayoutParams.WRAP_CONTENT));
            mapActions[i] = Ui.readout(this, 20);
            mapActions[i].setGravity(Gravity.END);
            row.addView(mapActions[i], new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            mapRows[i] = row;
            hero.addView(row, matchWidth(i == 0 ? 0 : 8));
        }

        View divider = new View(this);
        divider.setBackgroundColor(Ui.LINE);
        LinearLayout.LayoutParams line = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1));
        line.topMargin = dp(16);
        hero.addView(divider, line);
        LinearLayout recent = Ui.row(this);
        recent.addView(Ui.label(this, "최근"), new LinearLayout.LayoutParams(dp(48), ViewGroup.LayoutParams.WRAP_CONTENT));
        lastGestureView = Ui.body(this, 14, Ui.TEXT);
        lastGestureView.setTypeface(Ui.MONO);
        lastGestureView.setText(Ui.keepWords("아직 받은 제스처가 없습니다"));
        recent.addView(lastGestureView, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        hero.addView(recent, matchWidth(12));
        page.addView(hero, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        updateRemoteMap();

        missingView = Ui.readout(this, 22);
        missingView.setText("0");
        LinearLayout missingTile = Ui.tile(this, "누락 샘플", missingView);
        if (!BuildConfig.DEV_TOOLS) missingTile.setVisibility(View.GONE);
        page.addView(missingTile, matchWidth(10));

        swipeButton = Ui.button(this, "스와이프 제어 켜기", Ui.Style.ACCENT_LINE, v -> toggleSwipeControl());
        page.addView(swipeButton, matchWidth(12));
        page.addView(Ui.button(this, "링 다시 연결", Ui.Style.GHOST, v -> connectRing()), matchWidth(8));
        return page;
    }

    /** 모드에 따라 위·아래가 하는 일을 바꿔 적는다. */
    private void updateRemoteMap() {
        mapActions[0].setText(horizontalMode ? "왼쪽으로 넘기기" : "위로 넘기기");
        mapActions[1].setText(horizontalMode ? "오른쪽으로 넘기기" : "아래로 넘기기");
        mapActions[2].setText("모드 전환");
    }

    /** 받은 제스처의 줄을 잠깐 강조한다. */
    private void flashRemoteRow(String direction) {
        int index = "UP".equals(direction) ? 0 : "DOWN".equals(direction) ? 1 : 2;
        LinearLayout row = mapRows[index];
        if (row.getTag() instanceof Runnable) row.removeCallbacks((Runnable) row.getTag());
        row.setBackground(Ui.surface(this, Ui.RAISED, Ui.ACCENT, 14));
        mapActions[index].setTextColor(Ui.ACCENT);
        Runnable restore = () -> {
            row.setBackground(Ui.surface(this, Ui.RAISED, 0, 14));
            mapActions[index].setTextColor(Ui.TEXT);
        };
        row.setTag(restore);
        row.postDelayed(restore, 700);
    }

    /** 제어 상태 표시. 접근성이 꺼져 있으면 눈에 띄게 알린다. */
    private void updateControlView() {
        String text;
        int color;
        if (!swipeControl) {
            text = "제어 꺼짐";
            color = Ui.MUTED;
        } else if (SwipeAccessibilityService.getCurrent() != null) {
            text = "제어 중";
            color = Ui.OK;
        } else {
            text = "접근성 켜기 필요";
            color = Ui.WARN;
        }
        if (text.contentEquals(controlView.getText())) return;
        controlView.setText(text);
        controlView.setTextColor(color);
        controlView.setBackground(Ui.surface(this, Ui.BG, color, 99));
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

        guideCard.addView(Ui.button(this, "방향 안내 수집 시작", Ui.Style.PRIMARY, v -> startGuide()), matchWidth(12));
        setupGroup.addView(guideCard, matchWidth(0));

        LinearLayout sessionCard = Ui.card(this);
        sessionCard.addView(Ui.label(this, "세션"));
        progressView = Ui.body(this, 14, Ui.TEXT);
        sessionCard.addView(progressView, matchWidth(8));
        setupGroup.addView(sessionCard, matchWidth(10));

        LinearLayout fixedRow = Ui.row(this);
        fixedRow.addView(Ui.button(this, "IDLE\n가만히 10초", Ui.Style.QUIET,
                v -> startFixedLong("idle", "가만히 10초", "가만히")), weight(0));
        fixedRow.addView(Ui.button(this, "OTHER\n다른 움직임 10초", Ui.Style.QUIET,
                v -> startFixedLong("other", "명령 아닌 움직임 10초", "명령 아닌 움직임")), weight(10));
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
        dial.setVisibility(index == 1 ? View.VISIBLE : View.GONE);  // 다이얼은 수집 안내에만 쓴다
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
        dial.setCompact(selectedTab == 1 && !(guideRunning && !guidePaused));
    }

    private String countText(String label) {
        return String.valueOf(savedCounts.getOrDefault(label, 0));
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
        savedCounts.put("raw_up", 3);
        savedCounts.put("raw_down", 4);
        savedCounts.put("raw_left", 2);
        savedCounts.put("raw_right", 3);
        switch (preview) {
            case "pairing":
                savedCounts.clear();
                toggleGuide(0);
                break;
            case "connect":
                savedCounts.clear();
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
                for (int i = 0; i < 40; i++) guideQueue.add(DIRECTION_LABELS[i % 4]);
                guideIndex = 12;
                guideRunning = true;
                selectTab(1);
                prompt("지금! 위↑");
                dial.setPhase(DirectionDial.Phase.GO, "raw_up");
                break;
            case "still":
                for (int i = 0; i < 40; i++) guideQueue.add(DIRECTION_LABELS[i % 4]);
                guideIndex = 12;
                guideRunning = true;
                selectTab(1);
                prompt("가만히…");
                dial.setPhase(DirectionDial.Phase.STILL, "raw_up");
                break;
            default:
                savedCounts.clear();
                swipeControl = true;
                Ui.applyStyle(swipeButton, Ui.Style.PRIMARY);
                swipeButton.setText("스와이프 제어 끄기");
                prompt("제어 중");
                lastGestureView.setText("UP · 0.92 → 스와이프 UP");
                flashRemoteRow("UP");
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
        sb.append(sessionDir == null ? "세션 없음" : "세션 " + sessionDir.getName());
        if (guideRunning) sb.append(" · 안내 ").append(Math.min(guideIndex, guideQueue.size())).append('/').append(guideQueue.size());
        sb.append('\n');
        if (savedCounts.isEmpty()) {
            sb.append("저장한 기록 없음");
        } else {
            for (Map.Entry<String, Integer> entry : savedCounts.entrySet()) {
                sb.append(displayName(entry.getKey())).append(' ').append(entry.getValue()).append("  ");
            }
        }
        progressView.setText(sb.toString().trim());
        pauseButton.setText(guidePaused ? "계속" : "일시정지");
        Ui.setEnabled(sessionButton, sessionDir != null);
        Ui.setEnabled(pauseButton, guideRunning);
        Ui.setEnabled(redoButton, lastSavedFile != null);
        boolean focused = guideRunning && !guidePaused;
        setupGroup.setVisibility(focused ? View.GONE : View.VISIBLE);
        controlsRow.setVisibility(guideRunning || lastSavedFile != null ? View.VISIBLE : View.GONE);
        updateDialSize();
        dial.setProgress(guideRunning && !guideQueue.isEmpty()
                ? Math.min(guideIndex, guideQueue.size()) / (float) guideQueue.size() : 0f);
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
        if (!guideRunning && !captureActive()) prompt(controlPrompt());
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
        updateRemoteMap();
        flashRemoteRow(direction);
        updateDialLabels();
        dial.flash(direction);
    }

    private final Runnable statsTicker = new Runnable() {
        @Override
        public void run() {
            String status = connectionText;
            setTextIfChanged(connectionView, Ui.keepWords(status));
            updateControlView();
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
        public void onSamples(long firstSlot, short[] raw, int count) {
            long arrival = SystemClock.elapsedRealtime();
            acceptSamples(firstSlot, raw, count, arrival);
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

    private boolean ringReady() {
        return client.isStreaming() && !client.isDevicePaused();
    }

    // ---------------------------------------------------------------- 세션

    private void ensureSession() {
        if (sessionDir != null) return;
        String name = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
        sessionDir = new File(new File(getExternalFilesDir(null), "sessions"), name);
        if (!sessionDir.mkdirs()) {
            Toast.makeText(this, "세션 폴더를 만들지 못했습니다.", Toast.LENGTH_LONG).show();
        }
        savedCounts.clear();
        nextIndex.clear();
        lastSavedFile = null;
        String info = "session=" + name + "\n"
                + "started=" + timestamp() + "\n"
                + "memo=" + memoInput.getText().toString().replace('\n', ' ') + "\n"
                + "device=" + ImuBleClient.DEVICE_NAME + "\n"
                + "csv=timestamp ms, accX/Y/Z m/s^2 (raw x 0.122 mg), gyrX/Y/Z deg/s (raw x " + GYRO_DPS_PER_LSB + ")\n"
                + "gyro_range_dps=" + GYRO_RANGE_DPS + "\n"
                + "gesture_samples=" + GESTURE_SAMPLES + " pre_roll_cue_ms=" + PRE_ROLL_MS + "\n";
        File infoFile = new File(sessionDir, "session_info.txt");
        fileWriter.execute(() -> writeText(infoFile, info, false));
        event("세션 시작 " + name);
        updateProgress();
    }

    private void endSession() {
        if (sessionDir == null) return;
        stopGuide();
        if (isContinuousRunning()) stopContinuous();
        abortCapture();
        StringBuilder summary = new StringBuilder("ended=" + timestamp() + "\ncounts=");
        for (Map.Entry<String, Integer> entry : savedCounts.entrySet()) {
            summary.append(entry.getKey()).append(':').append(entry.getValue()).append(' ');
        }
        summary.append('\n');
        File dir = sessionDir;
        String text = summary.toString();
        fileWriter.execute(() -> {
            writeText(new File(dir, "session_info.txt"), text, true);
            writeText(new File(dir, SESSION_DONE_MARKER), "", false);  // PC 옮기기 도구는 이 표시가 있는 세션만 가져간다
        });
        event("세션 종료 " + dir.getName());
        sessionDir = null;
        prompt("세션 종료");
        dial.setPhase(DirectionDial.Phase.IDLE, null);
        updateProgress();
    }

    private File nextFile(String label) {
        int index = nextIndex.getOrDefault(label, 1);
        nextIndex.put(label, index + 1);  // 다시 하기로 지운 번호도 재사용하지 않아 덮어쓰지 않는다
        return new File(sessionDir, label + "." + index + ".csv");
    }

    private void countSaved(String label, int delta) {
        int value = savedCounts.getOrDefault(label, 0) + delta;
        if (value <= 0) savedCounts.remove(label);
        else savedCounts.put(label, value);
    }

    private static String timestamp() {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date());
    }

    private static boolean writeText(File file, String text, boolean append) {
        try (FileWriter writer = new FileWriter(file, append)) {
            writer.write(text);
            return true;
        } catch (IOException ignored) {
            // Capture writers additionally record the failure in their sidecar.
            return false;
        }
    }

    // ---------------------------------------------------------------- 기록

    private boolean captureActive() {
        synchronized (captureLock) {
            return capture != null;
        }
    }

    private boolean isContinuousRunning() {
        synchronized (captureLock) {
            return capture != null && capture.target <= 0;
        }
    }

    private Capture startCapture(String label, int target, CaptureDone done) {
        long startCall = SystemClock.elapsedRealtime();
        ensureSession();
        Capture c = new Capture(label, target, nextFile(label), done, startCall, activityInstanceId);
        if (target <= 0) {
            fileWriter.execute(() -> c.csvWriteFailed |= !writeText(c.file, "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ\n", false));
        }
        synchronized (captureLock) {
            capture = c;
        }
        if (target > 0) {
            long timeout = target * 10L + TIMEOUT_EXTRA_MS;
            mainHandler.postDelayed(() -> {
                synchronized (captureLock) {
                    if (capture != c || c.finished) return;
                    c.finished = true;
                    c.endedAt = SystemClock.elapsedRealtime();
                    capture = null;
                    queueSidecar(c, "timeout", "capture timeout");
                }
                c.done.finished(c, false, "시간 초과(연결 확인)");
            }, timeout);
        }
        return c;
    }

    private void abortCapture() {
        synchronized (captureLock) {
            if (capture == null) return;
            Capture c = capture;
            c.finished = true;
            c.endedAt = SystemClock.elapsedRealtime();
            capture = null;
            queueSidecar(c, "aborted", "capture cancelled");
        }
    }

    /** Bluetooth 스레드에서 호출된다. 정해진 길이 기록은 슬롯이 하나라도 비면 실패로 처리해 깨끗한 파일만 남긴다. */
    private void acceptSamples(long firstSlot, short[] raw, int count, long arrival) {
        Capture done = null;
        boolean ok = false;
        String reason = null;
        synchronized (captureLock) {
            Capture c = capture;
            if (c == null || c.finished) return;
            for (int i = 0; i < count; i++) {
                long slot = firstSlot + i;
                if (c.firstSlot < 0) {
                    c.firstSlot = slot;
                    c.nextSlot = slot;
                }
                if (slot < c.nextSlot) continue;
                if (slot > c.nextSlot) {
                    if (c.target > 0) {
                        reason = "샘플 " + (slot - c.nextSlot) + "개 누락";
                        done = c;
                        break;
                    }
                    c.gapSamples += slot - c.nextSlot;  // 연속 기록은 공백을 timestamp 간격으로 남긴다
                }
                appendRow(c.rows, (slot - c.firstSlot) * 10, raw, i * 6);
                c.nextSlot = slot + 1;
                c.count++;
                c.sidecar.accept(slot, arrival);
                if (c.target > 0 && c.count >= c.target) {
                    ok = true;
                    done = c;
                    break;
                }
            }
            if (done != null) {
                done.finished = true;
                done.endedAt = SystemClock.elapsedRealtime();
                capture = null;
                if (!ok) queueSidecar(done, "sample_gap", reason);
            } else if (c.target <= 0 && c.rows.length() > 64 * 1024) {
                // 연속 기록은 메모리에 계속 쌓지 않고 일정량마다 파일에 덧붙인다
                String data = c.rows.toString();
                c.rows.setLength(0);
                File file = c.file;
                fileWriter.execute(() -> c.csvWriteFailed |= !writeText(file, data, true));
            }
        }
        if (done != null) {
            Capture finished = done;
            boolean success = ok;
            String why = reason;
            mainHandler.post(() -> finished.done.finished(finished, success, why));
        }
    }

    private static void appendRow(StringBuilder sb, long timestampMs, short[] raw, int offset) {
        sb.append(timestampMs);
        for (int axis = 0; axis < 6; axis++) {
            double scale = axis < 3 ? ACC_MS2_PER_LSB : GYRO_DPS_PER_LSB;
            sb.append(',').append(String.format(Locale.US, "%.5f", raw[offset + axis] * scale));
        }
        sb.append('\n');
    }

    /** 정해진 길이 기록이 끝나면 파일로 쓴다. 실패한 기록은 파일을 만들지 않는다. */
    private void saveFixed(Capture c) {
        String data = "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ\n" + c.rows;
        fileWriter.execute(() -> {
            c.csvWriteFailed |= !writeText(c.file, data, false);
            writeSidecar(c, "completed", null);
        });
        lastSavedFile = c.file;
        lastSavedLabel = c.label;
        countSaved(c.label, 1);
        updateProgress();
    }

    // All sidecar writes share CSV ordering and never replace an existing sidecar.
    private void queueSidecar(Capture c, String status, String reason) {
        fileWriter.execute(() -> writeSidecar(c, status, reason));
    }

    private void writeSidecar(Capture c, String status, String reason) {
        File sidecar = new File(c.file.getParentFile(), c.file.getName() + ".capture.json");
        String finalStatus = c.csvWriteFailed ? "csv_write_failed" : status;
        if (c.csvWriteFailed) mainHandler.post(() -> event(c.file.getName() + " CSV 저장 실패(분석 사용 금지)"));
        try {
            CaptureSidecar.writeExclusive(sidecar, c.sidecar.json(c.endedAt, finalStatus,
                    reason, c.file.isFile(), c.csvWriteFailed));
        } catch (IOException e) {
            mainHandler.post(() -> event(sidecar.getName() + " 메타데이터 저장 실패: " + e.getClass().getSimpleName()));
        }
    }

    // ---------------------------------------------------------------- 안내 수집

    private void startGuide() {
        if (captureActive()) {
            Toast.makeText(this, "진행 중인 기록을 먼저 끝내세요.", Toast.LENGTH_SHORT).show();
            return;
        }
        int repeat;
        try {
            repeat = Integer.parseInt(repeatInput.getText().toString().trim());
        } catch (NumberFormatException e) {
            repeat = 0;
        }
        if (repeat <= 0 || repeat > 100) {
            Toast.makeText(this, "방향별 횟수는 1~100으로 입력하세요.", Toast.LENGTH_SHORT).show();
            return;
        }
        ensureSession();
        guideQueue.clear();
        for (int i = 0; i < repeat; i++) Collections.addAll(guideQueue, DIRECTION_LABELS);
        Collections.shuffle(guideQueue);  // 같은 방향이 몰리지 않게 섞어 순서·피로 영향을 줄인다
        guideIndex = 0;
        guideRunning = true;
        guidePaused = false;
        event("안내 수집 시작: 방향별 " + repeat + "회, 총 " + guideQueue.size() + "회");
        updateProgress();
        runNextTrial();
    }

    private void stopGuide() {
        guideRunning = false;
        guidePaused = false;
        cancelGuideSteps();
    }

    private void cancelGuideSteps() {
        guideGeneration++;
    }

    private void postGuide(Runnable step, long delayMs) {
        int generation = guideGeneration;
        mainHandler.postDelayed(() -> {
            if (generation == guideGeneration) step.run();
        }, delayMs);
    }

    private void runNextTrial() {
        if (!guideRunning || guidePaused) return;
        if (guideIndex >= guideQueue.size()) {
            guideRunning = false;
            prompt("안내 수집 완료");
            dial.setPhase(DirectionDial.Phase.SAVED, null);
            speak("끝");
            event("안내 수집 완료");
            updateProgress();
            return;
        }
        if (!ringReady()) {
            prompt("링 연결·재개 대기");
            dial.setPhase(DirectionDial.Phase.IDLE, null);
            postGuide(this::runNextTrial, 500);
            return;
        }
        String label = guideQueue.get(guideIndex);
        prompt("다음: " + displayName(label) + "\n(" + (guideIndex + 1) + "/" + guideQueue.size() + ")");
        dial.setPhase(DirectionDial.Phase.ARMED, label);
        speak(spokenName(label));
        postGuide(() -> beginTrial(label), PROMPT_MS);
    }

    private void beginTrial(String label) {
        tone(ToneGenerator.TONE_PROP_BEEP);
        prompt("가만히…");
        dial.setPhase(DirectionDial.Phase.STILL, label);
        startCapture(label, GESTURE_SAMPLES, this::onTrialDone);
        postGuide(() -> {
            tone(ToneGenerator.TONE_PROP_BEEP2);
            prompt("지금! " + displayName(label));
            dial.setPhase(DirectionDial.Phase.GO, label);
        }, PRE_ROLL_MS);
    }

    private void onTrialDone(Capture c, boolean ok, String reason) {
        cancelGuideSteps();  // 아직 안 울린 "지금" 신호 등 남은 단계를 취소
        if (!ok) {
            prompt("다시: " + reason);
            dial.setPhase(DirectionDial.Phase.IDLE, null);
            event(displayName(c.label) + " 실패(" + reason + "), 다시 합니다");
            postGuide(this::runNextTrial, REST_MS);
            return;
        }
        tone(ToneGenerator.TONE_PROP_ACK);
        saveFixed(c);
        guideIndex++;
        prompt("저장");
        dial.setPhase(DirectionDial.Phase.SAVED, null);
        updateProgress();
        postGuide(this::runNextTrial, REST_MS);
    }

    private void togglePause() {
        if (!guideRunning) return;
        if (guidePaused) {
            guidePaused = false;
            event("안내 계속");
            updateProgress();
            runNextTrial();
        } else {
            guidePaused = true;
            cancelGuideSteps();
            abortCapture();  // 진행 중이던 회차는 버리고, 계속하면 같은 회차부터 다시 한다
            prompt("일시정지");
            dial.setPhase(DirectionDial.Phase.IDLE, null);
            event("안내 일시정지");
            updateProgress();
        }
    }

    private void redoLast() {
        if (lastSavedFile == null) {
            Toast.makeText(this, "다시 할 기록이 없습니다.", Toast.LENGTH_SHORT).show();
            return;
        }
        File file = lastSavedFile;
        String label = lastSavedLabel;
        lastSavedFile = null;
        cancelGuideSteps();
        if (!isContinuousRunning()) abortCapture();
        fileWriter.execute(file::delete);
        countSaved(label, -1);
        event(file.getName() + " 삭제");

        boolean isDirection = label.startsWith("raw_");
        if (isDirection && sessionDir != null) {
            guideQueue.add(Math.min(guideIndex, guideQueue.size()), label);
            guideRunning = true;
            prompt("방금 것 삭제, 다시 합니다");
            dial.setPhase(DirectionDial.Phase.IDLE, null);
            updateProgress();
            if (!guidePaused) postGuide(this::runNextTrial, REST_MS);
        } else {
            prompt("방금 것 삭제. 버튼을 다시 누르세요");
            dial.setPhase(DirectionDial.Phase.IDLE, null);
            updateProgress();
        }
    }

    // ---------------------------------------------------------------- idle/other, 연속 기록

    private void startFixedLong(String label, String promptText, String spoken) {
        if (captureActive() || (guideRunning && !guidePaused)) {
            Toast.makeText(this, "안내 수집을 일시정지하거나 진행 중인 기록을 끝내세요.", Toast.LENGTH_SHORT).show();
            return;
        }
        if (!ringReady()) {
            Toast.makeText(this, "링이 수신 중이 아닙니다.", Toast.LENGTH_SHORT).show();
            return;
        }
        prompt(promptText);
        dial.setPhase(DirectionDial.Phase.ARMED, null);
        speak(spoken);
        mainHandler.postDelayed(() -> {
            tone(ToneGenerator.TONE_PROP_BEEP);
            prompt(promptText + "\n기록 중…");
            dial.setPhase(DirectionDial.Phase.STILL, null);
            startCapture(label, FIXED_LONG_SAMPLES, (c, ok, reason) -> {
                if (ok) {
                    tone(ToneGenerator.TONE_PROP_ACK);
                    saveFixed(c);
                    prompt(label + " 저장");
                    dial.setPhase(DirectionDial.Phase.SAVED, null);
                    event(c.file.getName() + " 저장");
                } else {
                    prompt(label + " 실패: " + reason);
                    dial.setPhase(DirectionDial.Phase.IDLE, null);
                    event(label + " 실패(" + reason + ")");
                }
            });
        }, PROMPT_MS);
    }

    private void toggleContinuous() {
        if (isContinuousRunning()) {
            stopContinuous();
            return;
        }
        if (captureActive() || (guideRunning && !guidePaused)) {
            Toast.makeText(this, "안내 수집을 일시정지하거나 진행 중인 기록을 끝내세요.", Toast.LENGTH_SHORT).show();
            return;
        }
        if (!ringReady()) {
            Toast.makeText(this, "링이 수신 중이 아닙니다.", Toast.LENGTH_SHORT).show();
            return;
        }
        tone(ToneGenerator.TONE_PROP_BEEP);
        Capture c = startCapture("continuous", 0, (cap, ok, reason) -> { });
        prompt("연속 기록 중");
        dial.setPhase(DirectionDial.Phase.STILL, null);
        continuousButton.setText("연속 기록 중지");
        Ui.applyStyle(continuousButton, Ui.Style.PRIMARY);
        event(c.file.getName() + " 시작");
    }

    private void stopContinuous() {
        Capture c;
        String rest;
        synchronized (captureLock) {
            c = capture;
            if (c == null || c.target > 0) return;
            c.finished = true;
            c.endedAt = SystemClock.elapsedRealtime();
            capture = null;
            rest = c.rows.toString();
            c.rows.setLength(0);
        }
        File file = c.file;
        fileWriter.execute(() -> {
            c.csvWriteFailed |= !writeText(file, rest, true);
            writeSidecar(c, "stopped", "continuous capture finalized");
        });
        tone(ToneGenerator.TONE_PROP_ACK);
        countSaved("continuous", 1);
        lastSavedFile = file;
        lastSavedLabel = "continuous";
        continuousButton.setText("연속 기록 시작");
        Ui.applyStyle(continuousButton, Ui.Style.QUIET);
        long seconds = (SystemClock.elapsedRealtime() - c.startedAt) / 1000;
        prompt("연속 기록 저장");
        dial.setPhase(DirectionDial.Phase.SAVED, null);
        event(file.getName() + " 저장: " + seconds + "초, 샘플 " + c.count + ", 공백 " + c.gapSamples);
        updateProgress();
    }

    @Override
    protected void onDestroy() {
        endSession();  // 앱을 닫아도 세션을 끝내 PC로 옮길 수 있게 한다
        mainHandler.removeCallbacksAndMessages(null);
        client.stop();
        fileWriter.shutdown();
        if (tts != null) tts.shutdown();
        if (tones != null) tones.release();
        super.onDestroy();
    }
}
