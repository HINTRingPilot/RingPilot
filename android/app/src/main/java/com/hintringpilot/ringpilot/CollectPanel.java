package com.hintringpilot.ringpilot;

import android.content.Context;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Handler;
import android.os.SystemClock;
import android.speech.tts.TextToSpeech;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.hintringpilot.ringpilot.ui.DirectionDial;
import com.hintringpilot.ringpilot.ui.Ui;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/**
 * 데이터 수집 탭(개발용 빌드에서만 보인다).
 * 안내 수집: 방향별 N회를 섞은 순서로 음성·소리 안내에 맞춰 4초씩 자동 기록한다(방향 안내 → 삑: 가만히 → 1초 뒤 삐빅: 움직임).
 * 수동 기록: idle/other 10초, 길이 제한 없는 연속 기록(실사용 시험용).
 * 화면 위쪽 다이얼(DirectionDial)에 단계와 방향별 저장 개수를 보인다. 파일은 SessionRecorder가 쓴다.
 */
final class CollectPanel {
    static final String[] DIRECTION_LABELS = {"raw_up", "raw_down", "raw_left", "raw_right"};

    private static final int GESTURE_SAMPLES = 400;     // 4초. 1초 대기 뒤 동작·자연 복귀·안정 구간까지 담는다
    private static final int FIXED_LONG_SAMPLES = 1000; // idle/other 10초
    private static final long PROMPT_MS = 1200;         // 방향 안내 후 기록 시작까지
    private static final long PRE_ROLL_MS = 1000;       // 기록 시작 후 "지금" 신호까지(가만히 있는 구간)
    private static final long REST_MS = 1000;           // 저장 후 다음 안내까지
    private static final String BUSY = "안내 수집을 일시정지하거나 진행 중인 기록을 끝내세요.";

    private final Context context;
    private final Handler mainHandler;
    private final DirectionDial dial;
    private final TextView promptView;
    private final BooleanSupplier ringReady;
    private final Consumer<String> event;
    final SessionRecorder recorder;

    private TextToSpeech tts;  // 초기화 콜백이 이 필드를 읽으므로 final로 두지 않는다
    private boolean ttsReady = false;
    private final ToneGenerator tones = new ToneGenerator(AudioManager.STREAM_MUSIC, 90);

    private View page;
    private EditText memoInput;
    private EditText repeatInput;
    private TextView progressView;
    private LinearLayout controlsRow;
    private LinearLayout setupGroup;
    private Button pauseButton;
    private Button redoButton;
    private Button sessionButton;
    private Button continuousButton;
    private boolean shown = false;

    private final ArrayList<String> guideQueue = new ArrayList<>();
    private int guideIndex = 0;
    private boolean guideRunning = false;
    private boolean guidePaused = false;
    private int guideGeneration = 0;  // 늘리면 예약된 안내 단계가 모두 무효가 된다

    CollectPanel(Context context, Handler mainHandler, DirectionDial dial, TextView promptView,
                 BooleanSupplier ringReady, Consumer<String> event, Runnable reconnect) {
        this.context = context;
        this.mainHandler = mainHandler;
        this.dial = dial;
        this.promptView = promptView;
        this.ringReady = ringReady;
        this.event = event;
        tts = new TextToSpeech(context, status -> {
            if (status == TextToSpeech.SUCCESS) ttsReady = tts.setLanguage(Locale.KOREAN) >= TextToSpeech.LANG_AVAILABLE;
        });
        recorder = new SessionRecorder(context.getExternalFilesDir(null), mainHandler, new SessionRecorder.Listener() {
            @Override
            public void onEvent(String text) {
                event.accept(text);
            }

            @Override
            public void onWarning(String text) {
                Toast.makeText(context, text, Toast.LENGTH_LONG).show();
            }

            @Override
            public void onChanged() {
                updateProgress();
            }
        }, () -> memoInput.getText().toString(), "gesture_samples=" + GESTURE_SAMPLES + " pre_roll_cue_ms=" + PRE_ROLL_MS);
        page = createPage(reconnect);
        updateProgress();
    }

    View page() {
        return page;
    }

    /** 탭이 바뀔 때. 이 탭에서만 다이얼을 보인다. */
    void setShown(boolean value) {
        shown = value;
        dial.setVisibility(value ? View.VISIBLE : View.GONE);
        updateDial();
    }

    // ---------------------------------------------------------------- 화면

    /** 안내 수집이 도는 동안에는 준비용 칸을 접어 다이얼에 집중한다. */
    private View createPage(Runnable reconnect) {
        LinearLayout page = Ui.column(context);

        controlsRow = Ui.row(context);
        pauseButton = Ui.button(context, "일시정지", Ui.Style.QUIET, v -> togglePause());
        controlsRow.addView(pauseButton, Ui.weight(context, 0));
        redoButton = Ui.button(context, "방금 것 다시", Ui.Style.QUIET, v -> redoLast());
        controlsRow.addView(redoButton, Ui.weight(context, 10));
        page.addView(controlsRow, Ui.matchWidth(context, 0));

        setupGroup = Ui.column(context);

        // 메모는 세션을 시작할 때 저장되므로 시작 버튼과 같은 칸에 둔다.
        LinearLayout guideCard = Ui.card(context);
        guideCard.addView(Ui.label(context, "방향 안내 수집"));
        TextView guideHelp = Ui.body(context, 13, Ui.MUTED);
        guideHelp.setText(Ui.keepWords("방향을 불러주면 삑에 가만히, 삐빅에 움직입니다."));
        guideCard.addView(guideHelp, Ui.matchWidth(context, 8));

        memoInput = new EditText(context);
        memoInput.setHint("세션 메모: 착용 손가락, 자세, 장소 등");
        Ui.styleInput(memoInput);
        guideCard.addView(memoInput, Ui.matchWidth(context, 12));
        guideCard.addView(createRepeatStepper(), Ui.matchWidth(context, 12));
        guideCard.addView(Ui.button(context, "방향 안내 수집 시작", Ui.Style.PRIMARY, v -> startGuide()), Ui.matchWidth(context, 12));
        setupGroup.addView(guideCard, Ui.matchWidth(context, 0));

        LinearLayout sessionCard = Ui.card(context);
        sessionCard.addView(Ui.label(context, "세션"));
        progressView = Ui.body(context, 14, Ui.TEXT);
        sessionCard.addView(progressView, Ui.matchWidth(context, 8));
        setupGroup.addView(sessionCard, Ui.matchWidth(context, 10));

        LinearLayout fixedRow = Ui.row(context);
        fixedRow.addView(Ui.button(context, "IDLE\n가만히 10초", Ui.Style.QUIET,
                v -> startFixedLong("idle", "가만히 10초", "가만히")), Ui.weight(context, 0));
        fixedRow.addView(Ui.button(context, "OTHER\n다른 움직임 10초", Ui.Style.QUIET,
                v -> startFixedLong("other", "명령 아닌 움직임 10초", "명령 아닌 움직임")), Ui.weight(context, 10));
        setupGroup.addView(fixedRow, Ui.matchWidth(context, 10));

        continuousButton = Ui.button(context, "연속 기록 시작", Ui.Style.QUIET, v -> toggleContinuous());
        setupGroup.addView(continuousButton, Ui.matchWidth(context, 10));
        page.addView(setupGroup, Ui.matchWidth(context, 10));

        LinearLayout footer = Ui.row(context);
        sessionButton = Ui.button(context, "세션 종료", Ui.Style.GHOST, v -> endSession());
        footer.addView(sessionButton, Ui.weight(context, 0));
        footer.addView(Ui.button(context, "링 다시 연결", Ui.Style.GHOST, v -> reconnect.run()), Ui.weight(context, 10));
        page.addView(footer, Ui.matchWidth(context, 10));
        return page;
    }

    private View createRepeatStepper() {
        LinearLayout stepper = Ui.row(context);
        TextView label = Ui.body(context, 14, Ui.TEXT);
        label.setText("방향별 횟수");
        stepper.addView(label, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        int button = Ui.dp(context, 54);
        stepper.addView(Ui.button(context, "−", Ui.Style.QUIET, v -> stepRepeat(-1)), new LinearLayout.LayoutParams(button, button));
        repeatInput = new EditText(context);
        repeatInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        repeatInput.setText("10");
        Ui.styleInput(repeatInput);
        repeatInput.setGravity(Gravity.CENTER);
        repeatInput.setTypeface(Ui.MONO_BOLD);
        repeatInput.setTextSize(18);
        repeatInput.setPadding(0, 0, 0, 0);
        LinearLayout.LayoutParams repeatParams = new LinearLayout.LayoutParams(Ui.dp(context, 68), button);
        repeatParams.setMargins(Ui.dp(context, 8), 0, Ui.dp(context, 8), 0);
        stepper.addView(repeatInput, repeatParams);
        stepper.addView(Ui.button(context, "+", Ui.Style.QUIET, v -> stepRepeat(1)), new LinearLayout.LayoutParams(button, button));
        return stepper;
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

    void updateProgress() {
        StringBuilder sb = new StringBuilder();
        sb.append(recorder.sessionDir() == null ? "세션 없음" : "세션 " + recorder.sessionDir().getName());
        if (guideRunning) sb.append(" · 안내 ").append(Math.min(guideIndex, guideQueue.size())).append('/').append(guideQueue.size());
        sb.append('\n');
        Map<String, Integer> counts = recorder.savedCounts();
        if (counts.isEmpty()) {
            sb.append("저장한 기록 없음");
        } else {
            for (Map.Entry<String, Integer> entry : counts.entrySet()) {
                sb.append(displayName(entry.getKey())).append(' ').append(entry.getValue()).append("  ");
            }
        }
        progressView.setText(sb.toString().trim());
        pauseButton.setText(guidePaused ? "계속" : "일시정지");
        Ui.setEnabled(sessionButton, recorder.sessionDir() != null);
        Ui.setEnabled(pauseButton, guideRunning);
        Ui.setEnabled(redoButton, recorder.lastSavedFile() != null);
        setupGroup.setVisibility(guideRunning && !guidePaused ? View.GONE : View.VISIBLE);
        controlsRow.setVisibility(guideRunning || recorder.lastSavedFile() != null ? View.VISIBLE : View.GONE);
        dial.setProgress(guideRunning && !guideQueue.isEmpty() ? Math.min(guideIndex, guideQueue.size()) / (float) guideQueue.size() : 0f);
        updateDial();
    }

    /** 화살표 옆에 방향별 저장 개수를 보이고, 준비 중에는 다이얼을 줄여 시작 버튼이 한 화면에 들어오게 한다. */
    private void updateDial() {
        dial.setLabels(count("raw_up"), count("raw_down"), count("raw_left"), count("raw_right"));
        dial.setCompact(shown && !(guideRunning && !guidePaused));
    }

    private String count(String label) {
        return String.valueOf(recorder.savedCount(label));
    }

    private void prompt(String text, DirectionDial.Phase phase, String label) {
        promptView.setText(text);
        dial.setPhase(phase, label);
    }

    private void speak(String text) {
        if (ttsReady) tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "prompt");
    }

    private void tone(int toneType) {
        tones.startTone(toneType, 150);
    }

    static String displayName(String label) {
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

    private boolean busy() {
        return recorder.captureActive() || (guideRunning && !guidePaused);
    }

    private void toast(String text) {
        Toast.makeText(context, text, Toast.LENGTH_SHORT).show();
    }

    // ---------------------------------------------------------------- 안내 수집

    private void startGuide() {
        if (recorder.captureActive()) {
            toast("진행 중인 기록을 먼저 끝내세요.");
            return;
        }
        int repeat;
        try {
            repeat = Integer.parseInt(repeatInput.getText().toString().trim());
        } catch (NumberFormatException e) {
            repeat = 0;
        }
        if (repeat <= 0 || repeat > 100) {
            toast("방향별 횟수는 1~100으로 입력하세요.");
            return;
        }
        recorder.ensureSession();
        guideQueue.clear();
        for (int i = 0; i < repeat; i++) Collections.addAll(guideQueue, DIRECTION_LABELS);
        Collections.shuffle(guideQueue);  // 같은 방향이 몰리지 않게 섞어 순서·피로 영향을 줄인다
        guideIndex = 0;
        guideRunning = true;
        guidePaused = false;
        event.accept("안내 수집 시작: 방향별 " + repeat + "회, 총 " + guideQueue.size() + "회");
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
            prompt("안내 수집 완료", DirectionDial.Phase.SAVED, null);
            speak("끝");
            event.accept("안내 수집 완료");
            updateProgress();
            return;
        }
        if (!ringReady.getAsBoolean()) {
            prompt("링 연결·재개 대기", DirectionDial.Phase.IDLE, null);
            postGuide(this::runNextTrial, 500);
            return;
        }
        String label = guideQueue.get(guideIndex);
        prompt("다음: " + displayName(label) + "\n(" + (guideIndex + 1) + "/" + guideQueue.size() + ")", DirectionDial.Phase.ARMED, label);
        speak(spokenName(label));
        postGuide(() -> beginTrial(label), PROMPT_MS);
    }

    private void beginTrial(String label) {
        tone(ToneGenerator.TONE_PROP_BEEP);
        prompt("가만히…", DirectionDial.Phase.STILL, label);
        recorder.start(label, GESTURE_SAMPLES, this::onTrialDone);
        postGuide(() -> {
            tone(ToneGenerator.TONE_PROP_BEEP2);
            prompt("지금! " + displayName(label), DirectionDial.Phase.GO, label);
        }, PRE_ROLL_MS);
    }

    private void onTrialDone(SessionRecorder.Capture c, boolean ok, String reason) {
        cancelGuideSteps();  // 아직 안 울린 "지금" 신호 등 남은 단계를 취소
        if (!ok) {
            prompt("다시: " + reason, DirectionDial.Phase.IDLE, null);
            event.accept(displayName(c.label) + " 실패(" + reason + "), 다시 합니다");
            postGuide(this::runNextTrial, REST_MS);
            return;
        }
        tone(ToneGenerator.TONE_PROP_ACK);
        guideIndex++;
        recorder.saveFixed(c);
        prompt("저장", DirectionDial.Phase.SAVED, null);
        postGuide(this::runNextTrial, REST_MS);
    }

    private void togglePause() {
        if (!guideRunning) return;
        if (guidePaused) {
            guidePaused = false;
            event.accept("안내 계속");
            updateProgress();
            runNextTrial();
        } else {
            guidePaused = true;
            cancelGuideSteps();
            recorder.abort();  // 진행 중이던 회차는 버리고, 계속하면 같은 회차부터 다시 한다
            prompt("일시정지", DirectionDial.Phase.IDLE, null);
            event.accept("안내 일시정지");
            updateProgress();
        }
    }

    private void redoLast() {
        if (recorder.lastSavedFile() == null) {
            toast("다시 할 기록이 없습니다.");
            return;
        }
        cancelGuideSteps();
        String label = recorder.deleteLast();
        if (label.startsWith("raw_") && recorder.sessionDir() != null) {
            guideQueue.add(Math.min(guideIndex, guideQueue.size()), label);
            guideRunning = true;
            prompt("방금 것 삭제, 다시 합니다", DirectionDial.Phase.IDLE, null);
            updateProgress();
            if (!guidePaused) postGuide(this::runNextTrial, REST_MS);
        } else {
            prompt("방금 것 삭제. 버튼을 다시 누르세요", DirectionDial.Phase.IDLE, null);
            updateProgress();
        }
    }

    // ---------------------------------------------------------------- idle/other, 연속 기록

    private void startFixedLong(String label, String promptText, String spoken) {
        if (busy()) {
            toast(BUSY);
            return;
        }
        if (!ringReady.getAsBoolean()) {
            toast("링이 수신 중이 아닙니다.");
            return;
        }
        prompt(promptText, DirectionDial.Phase.ARMED, null);
        speak(spoken);
        mainHandler.postDelayed(() -> {
            tone(ToneGenerator.TONE_PROP_BEEP);
            prompt(promptText + "\n기록 중…", DirectionDial.Phase.STILL, null);
            recorder.start(label, FIXED_LONG_SAMPLES, (c, ok, reason) -> {
                if (ok) {
                    tone(ToneGenerator.TONE_PROP_ACK);
                    recorder.saveFixed(c);
                    prompt(label + " 저장", DirectionDial.Phase.SAVED, null);
                    event.accept(c.file.getName() + " 저장");
                } else {
                    prompt(label + " 실패: " + reason, DirectionDial.Phase.IDLE, null);
                    event.accept(label + " 실패(" + reason + ")");
                }
            });
        }, PROMPT_MS);
    }

    private void toggleContinuous() {
        if (recorder.continuousRunning()) {
            stopContinuous();
            return;
        }
        if (busy()) {
            toast(BUSY);
            return;
        }
        if (!ringReady.getAsBoolean()) {
            toast("링이 수신 중이 아닙니다.");
            return;
        }
        tone(ToneGenerator.TONE_PROP_BEEP);
        SessionRecorder.Capture c = recorder.start("continuous", 0, (cap, ok, reason) -> { });
        prompt("연속 기록 중", DirectionDial.Phase.STILL, null);
        continuousButton.setText("연속 기록 중지");
        Ui.applyStyle(continuousButton, Ui.Style.PRIMARY);
        event.accept(c.file.getName() + " 시작");
    }

    private void stopContinuous() {
        SessionRecorder.Capture c = recorder.stopContinuous();
        if (c == null) return;
        tone(ToneGenerator.TONE_PROP_ACK);
        continuousButton.setText("연속 기록 시작");
        Ui.applyStyle(continuousButton, Ui.Style.QUIET);
        long seconds = (SystemClock.elapsedRealtime() - c.startedAt) / 1000;
        prompt("연속 기록 저장", DirectionDial.Phase.SAVED, null);
        event.accept(c.file.getName() + " 저장: " + seconds + "초, 샘플 " + c.count + ", 공백 " + c.gapSamples);
    }

    /** 세션을 끝낸다. 앱을 닫을 때도 불러 PC로 옮길 수 있게 한다. */
    void endSession() {
        if (recorder.sessionDir() == null) return;
        stopGuide();
        if (recorder.continuousRunning()) stopContinuous();
        recorder.endSession();
        prompt("세션 종료", DirectionDial.Phase.IDLE, null);
    }

    // ---------------------------------------------------------------- 화면 미리보기(디버그 빌드)

    void previewGuide(DirectionDial.Phase phase) {
        for (int i = 0; i < 40; i++) guideQueue.add(DIRECTION_LABELS[i % 4]);
        guideIndex = 12;
        guideRunning = true;
        prompt(phase == DirectionDial.Phase.GO ? "지금! 위↑" : "가만히…", phase, "raw_up");
        updateProgress();
    }

    void shutdown() {
        endSession();
        recorder.shutdown();
        tts.shutdown();
        tones.release();
    }
}
