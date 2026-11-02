package com.hintringpilot.ringpilot;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.speech.tts.TextToSpeech;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

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
    private boolean swipeControl = false;  // 수집 중 스와이프가 나가지 않도록 기본은 끈다
    private boolean horizontalMode = false;  // 좌우 제스처로 전환한다. 켜지면 위 = 왼쪽, 아래 = 오른쪽 스와이프
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
    }

    // ---------------------------------------------------------------- 화면

    private ScrollView createContentView() {
        int pad = dp(14);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(pad, pad, pad, pad);

        connectionView = text(14);
        layout.addView(connectionView, matchWidth());

        promptView = text(38);
        promptView.setTypeface(Typeface.DEFAULT_BOLD);
        promptView.setGravity(Gravity.CENTER);
        promptView.setMinHeight(dp(150));
        promptView.setText("대기");
        layout.addView(promptView, matchWidth());

        progressView = text(15);
        layout.addView(progressView, matchWidth());

        memoInput = new EditText(this);
        memoInput.setHint("세션 메모: 착용 손가락, 자세, 장소 등");
        layout.addView(memoInput, matchWidth());

        LinearLayout repeatRow = row();
        TextView repeatLabel = text(15);
        repeatLabel.setText("방향별 횟수 ");
        repeatRow.addView(repeatLabel);
        repeatInput = new EditText(this);
        repeatInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        repeatInput.setText("10");
        repeatRow.addView(repeatInput, new LinearLayout.LayoutParams(dp(80), ViewGroup.LayoutParams.WRAP_CONTENT));
        layout.addView(repeatRow, matchWidth());

        LinearLayout row1 = row();
        row1.addView(button("방향 안내 수집 시작", v -> startGuide()), weight());
        pauseButton = button("일시정지", v -> togglePause());
        row1.addView(pauseButton, weight());
        row1.addView(button("방금 것 다시", v -> redoLast()), weight());
        layout.addView(row1, matchWidth());

        LinearLayout row2 = row();
        row2.addView(button("idle 10초", v -> startFixedLong("idle", "가만히 10초", "가만히")), weight());
        row2.addView(button("other 10초", v -> startFixedLong("other", "명령 아닌 움직임 10초", "명령 아닌 움직임")), weight());
        continuousButton = button("연속 기록 시작", v -> toggleContinuous());
        row2.addView(continuousButton, weight());
        layout.addView(row2, matchWidth());

        LinearLayout row3 = row();
        sessionButton = button("세션 종료", v -> endSession());
        row3.addView(sessionButton, weight());
        row3.addView(button("링 다시 연결", v -> connectRing()), weight());
        layout.addView(row3, matchWidth());

        swipeButton = button("스와이프 제어 켜기", v -> toggleSwipeControl());
        layout.addView(swipeButton, matchWidth());

        TextView help = text(13);
        help.setText("방향 안내: 방향 음성 → '삑'(기록 시작, 가만히) → '삐빅'(1초 뒤, 지금 동작) → 4초 후 자동 저장.\n"
                + "잘못했으면 '방금 것 다시'. 링 일시정지·연결 끊김 중에는 안내가 기다립니다.\n"
                + "세션을 끝내야 PC로 옮길 수 있습니다(tools/pull-phone-sessions.js, 옮긴 뒤 휴대폰에서 삭제).");
        layout.addView(help, matchWidth());

        eventView = text(13);
        layout.addView(eventView, matchWidth());

        ScrollView scroll = new ScrollView(this);
        scroll.addView(layout);
        updateProgress();
        return scroll;
    }

    private TextView text(int sp) {
        TextView view = new TextView(this);
        view.setTextSize(sp);
        return view;
    }

    private Button button(String label, android.view.View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(listener);
        return button;
    }

    private LinearLayout row() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        return row;
    }

    private LinearLayout.LayoutParams weight() {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
    }

    private LinearLayout.LayoutParams matchWidth() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, dp(6), 0, 0);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void prompt(String text) {
        promptView.setText(text);
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
        sessionButton.setEnabled(sessionDir != null);
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
        if (swipeControl && SwipeAccessibilityService.getCurrent() == null) {
            event("접근성 설정에서 'RingPilot 스와이프'를 켜세요.");
            startActivity(new android.content.Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS));
        } else {
            event(swipeControl ? "스와이프 제어 켬. 이제 다른 앱으로 가도 됩니다." : "스와이프 제어 끔");
        }
    }

    /** 좌우 제스처는 방향을 구분하지 않고 상하·좌우 모드를 바꾼다. 위·아래 제스처는 모드에 맞는 스와이프가 된다. */
    private void applyGesture(String direction, double score) {
        String result = "수신만";
        if (swipeControl) {
            SwipeAccessibilityService service = SwipeAccessibilityService.getCurrent();
            if (service == null) {
                result = "접근성 서비스 꺼짐";
            } else if ("LEFT".equals(direction) || "RIGHT".equals(direction)) {
                horizontalMode = !horizontalMode;
                result = horizontalMode ? "좌우 모드" : "상하 모드";
                service.showBanner(result);
            } else {
                String swipe = direction;
                if (horizontalMode) swipe = "UP".equals(direction) ? "LEFT" : "RIGHT";
                result = service.swipe(swipe) ? "스와이프 " + swipe : "스와이프 실패";
            }
        }
        event(String.format(Locale.US, "제스처 %s (%.2f) → %s", direction, score, result));
    }

    private final Runnable statsTicker = new Runnable() {
        @Override
        public void run() {
            connectionView.setText(String.format(Locale.US, "%s · %.0f Hz · 누락 샘플 %d",
                    connectionText, client.recentRate(), client.missingSamples()));
            mainHandler.postDelayed(this, 500);
        }
    };

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
            mainHandler.post(() -> applyGesture(direction, score));
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
            speak("끝");
            event("안내 수집 완료");
            updateProgress();
            return;
        }
        if (!ringReady()) {
            prompt("링 연결·재개 대기");
            postGuide(this::runNextTrial, 500);
            return;
        }
        String label = guideQueue.get(guideIndex);
        prompt("다음: " + displayName(label) + "\n(" + (guideIndex + 1) + "/" + guideQueue.size() + ")");
        speak(spokenName(label));
        postGuide(() -> beginTrial(label), PROMPT_MS);
    }

    private void beginTrial(String label) {
        tone(ToneGenerator.TONE_PROP_BEEP);
        prompt("가만히…");
        startCapture(label, GESTURE_SAMPLES, this::onTrialDone);
        postGuide(() -> {
            tone(ToneGenerator.TONE_PROP_BEEP2);
            prompt("지금! " + displayName(label));
        }, PRE_ROLL_MS);
    }

    private void onTrialDone(Capture c, boolean ok, String reason) {
        cancelGuideSteps();  // 아직 안 울린 "지금" 신호 등 남은 단계를 취소
        if (!ok) {
            prompt("다시: " + reason);
            event(displayName(c.label) + " 실패(" + reason + "), 다시 합니다");
            postGuide(this::runNextTrial, REST_MS);
            return;
        }
        tone(ToneGenerator.TONE_PROP_ACK);
        saveFixed(c);
        guideIndex++;
        prompt("저장");
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
            updateProgress();
            if (!guidePaused) postGuide(this::runNextTrial, REST_MS);
        } else {
            prompt("방금 것 삭제. 버튼을 다시 누르세요");
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
        speak(spoken);
        mainHandler.postDelayed(() -> {
            tone(ToneGenerator.TONE_PROP_BEEP);
            prompt(promptText + "\n기록 중…");
            startCapture(label, FIXED_LONG_SAMPLES, (c, ok, reason) -> {
                if (ok) {
                    tone(ToneGenerator.TONE_PROP_ACK);
                    saveFixed(c);
                    prompt(label + " 저장");
                    event(c.file.getName() + " 저장");
                } else {
                    prompt(label + " 실패: " + reason);
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
        continuousButton.setText("연속 기록 중지");
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
        long seconds = (SystemClock.elapsedRealtime() - c.startedAt) / 1000;
        prompt("연속 기록 저장");
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
