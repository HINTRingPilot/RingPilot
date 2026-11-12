package com.hintringpilot.ringpilot.dev;

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

import com.hintringpilot.ringpilot.ui.Ui;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.UUID;
import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/**
 * 데이터 수집 탭(개발용 빌드에서만 보인다).
 * 안내 수집: 방향별 N회를 섞은 순서로 음성·소리 안내에 맞춰 4초씩 자동 기록한다(방향 안내 → 삑: 가만히 → 1초 뒤 삐빅: 움직임).
 * 수동 기록: idle/other 10초, 길이 제한 없는 연속 기록(실사용 시험용).
 * 화면 위쪽 다이얼(DirectionDial)에 단계와 방향별 저장 개수를 보인다. 수집·안내·세션 상태와 파일 저장은 CaptureCoordinator 하나가 맡는다.
 */
public final class CollectPanel {
    public static final String[] DIRECTION_LABELS = {"raw_up", "raw_down", "raw_left", "raw_right"};

    private final Context context;
    private final DirectionDial dial;
    private final TextView promptView;
    private final Consumer<String> event;
    private final CaptureCoordinator coordinator;
    private final Map<String, Integer> previewCounts = new LinkedHashMap<>();
    private boolean previewGuide;

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
    private Button guideButton, idleButton, otherButton;
    private boolean shown = false;

    public CollectPanel(Context context, Handler mainHandler, DirectionDial dial, TextView promptView,
                        Consumer<String> event, Runnable reconnect) {
        this.context = context;
        this.dial = dial;
        this.promptView = promptView;
        this.event = event;
        tts = new TextToSpeech(context, status -> {
            if (status == TextToSpeech.SUCCESS) ttsReady = tts.setLanguage(Locale.KOREAN) >= TextToSpeech.LANG_AVAILABLE;
        });
        ExecutorService fileWriter = Executors.newSingleThreadExecutor();
        coordinator = new CaptureCoordinator(new File(context.getExternalFilesDir(null), "sessions"),
                UUID.randomUUID().toString(), new CaptureCoordinator.Clock() {
                    public long elapsedMillis() { return SystemClock.elapsedRealtime(); }
                    public long wallMillis() { return System.currentTimeMillis(); }
                }, (action, delay) -> mainHandler.postDelayed(action, delay), new CaptureCoordinator.WriteQueue() {
                    public void execute(Runnable action) { fileWriter.execute(action); }
                    public void shutdown() { fileWriter.shutdown(); }
                }, new CaptureCoordinator.Listener() {
                    public void onChanged(CaptureCoordinator.Snapshot snapshot) { updateProgress(); }
                    public void onCue(CaptureCoordinator.Cue cue, String label) { showCue(cue, label); }
                    public void onError(String message) {
                        event.accept(message);
                        Toast.makeText(context, message, Toast.LENGTH_LONG).show();
                        prompt("저장 실패 · 기록 확인", DirectionDial.Phase.IDLE, null);
                    }
                });
        page = createPage(reconnect);
        updateProgress();
    }

    /** Called directly from the BLE callback, preserving the connection generation. */
    public void acceptSamples(long generation, long firstSlot, short[] raw, int count, long arrival) {
        coordinator.onSamples(generation, firstSlot, raw, count, arrival);
    }

    public void onStreamReady(long generation) { coordinator.onStreamReady(generation); }
    public void onStreamBoundary(long generation, String reason) { coordinator.onStreamBoundary(generation, reason); }

    public View page() {
        return page;
    }

    /** 탭이 바뀔 때. 이 탭에서만 다이얼을 보인다. */
    public void setShown(boolean value) {
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
        guideButton = Ui.button(context, "방향 안내 수집 시작", Ui.Style.PRIMARY, v -> startGuide());
        guideCard.addView(guideButton, Ui.matchWidth(context, 12));
        setupGroup.addView(guideCard, Ui.matchWidth(context, 0));

        LinearLayout sessionCard = Ui.card(context);
        sessionCard.addView(Ui.label(context, "세션"));
        progressView = Ui.body(context, 14, Ui.TEXT);
        sessionCard.addView(progressView, Ui.matchWidth(context, 8));
        setupGroup.addView(sessionCard, Ui.matchWidth(context, 10));

        LinearLayout fixedRow = Ui.row(context);
        idleButton = Ui.button(context, "IDLE\n가만히 10초", Ui.Style.QUIET, v -> startFixedLong("idle"));
        fixedRow.addView(idleButton, Ui.weight(context, 0));
        otherButton = Ui.button(context, "OTHER\n다른 움직임 10초", Ui.Style.QUIET, v -> startFixedLong("other"));
        fixedRow.addView(otherButton, Ui.weight(context, 10));
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

    public void updateProgress() {
        CaptureCoordinator.Snapshot value = coordinator.snapshot();
        StringBuilder sb = new StringBuilder();
        sb.append(!value.hasSession ? "세션 없음" : value.directory == null ? "세션 준비 중" : "세션 " + value.directory.getName());
        if (value.guideRunning) sb.append(" · 안내 ").append(value.guideIndex).append('/').append(value.guideSize);
        else if (previewGuide) sb.append(" · 안내 12/40");
        if (value.state != CaptureCoordinator.State.IDLE) sb.append(" · ").append(value.state);
        if (value.closing) sb.append(" · 종료 저장 중");
        sb.append('\n');
        Map<String, Integer> counts = previewCounts.isEmpty() ? value.savedCounts : previewCounts;
        if (counts.isEmpty()) sb.append("저장한 기록 없음");
        else for (Map.Entry<String, Integer> entry : counts.entrySet()) {
            sb.append(displayName(entry.getKey())).append(' ').append(entry.getValue()).append("  ");
        }
        progressView.setText(sb.toString().trim());
        pauseButton.setText(value.guidePaused ? "계속" : "일시정지");
        Ui.setEnabled(guideButton, value.canStartGuide);
        Ui.setEnabled(idleButton, value.canStartManual);
        Ui.setEnabled(otherButton, value.canStartManual);
        Ui.setEnabled(sessionButton, value.canEndSession);
        Ui.setEnabled(pauseButton, value.canPauseGuide || value.canResumeGuide);
        Ui.setEnabled(redoButton, value.canRedo);
        Ui.setEnabled(continuousButton, value.canToggleContinuous);
        continuousButton.setText(value.canStopContinuous ? "연속 기록 중지" : "연속 기록 시작");
        Ui.applyStyle(continuousButton, value.canStopContinuous ? Ui.Style.PRIMARY : Ui.Style.QUIET);
        boolean guiding = (value.guideRunning && !value.guidePaused) || previewGuide;
        setupGroup.setVisibility(guiding ? View.GONE : View.VISIBLE);
        controlsRow.setVisibility(value.guideRunning || value.lastSavedFile != null || previewGuide ? View.VISIBLE : View.GONE);
        dial.setProgress(previewGuide ? 0.3f : value.guideRunning && value.guideSize > 0 ? value.guideIndex / (float) value.guideSize : 0f);
        updateDial();
    }

    private void updateDial() {
        CaptureCoordinator.Snapshot value = coordinator.snapshot();
        Map<String, Integer> counts = previewCounts.isEmpty() ? value.savedCounts : previewCounts;
        dial.setLabels(String.valueOf(counts.getOrDefault("raw_up", 0)), String.valueOf(counts.getOrDefault("raw_down", 0)),
                String.valueOf(counts.getOrDefault("raw_left", 0)), String.valueOf(counts.getOrDefault("raw_right", 0)));
        dial.setCompact(shown && !(previewGuide || (value.guideRunning && !value.guidePaused)));
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

    private void toast(String text) { Toast.makeText(context, text, Toast.LENGTH_SHORT).show(); }

    // Every click uses the same coordinator guards that produce enabled button states.
    private void startGuide() {
        int repeat;
        try { repeat = Integer.parseInt(repeatInput.getText().toString().trim()); }
        catch (NumberFormatException error) { repeat = 0; }
        if (repeat < 1 || repeat > 100) { toast("방향별 횟수는 1~100으로 입력하세요."); return; }
        ArrayList<String> queue = new ArrayList<>();
        for (int i = 0; i < repeat; i++) Collections.addAll(queue, DIRECTION_LABELS);
        Collections.shuffle(queue);
        if (coordinator.startGuide(queue, memoInput.getText().toString())) event.accept("안내 수집 시작: 방향별 " + repeat + "회");
        else toast("진행 중인 기록·저장을 끝낸 뒤 시작하세요.");
    }

    private void togglePause() {
        if (!coordinator.toggleGuidePause()) toast("진행 중인 기록·저장을 끝낸 뒤 계속하세요.");
    }

    private void redoLast() {
        if (!coordinator.redoLast()) toast("진행 중인 기록·저장을 끝낸 뒤 다시 하세요.");
    }

    private void startFixedLong(String label) {
        if (!coordinator.requestManual(label, CaptureCoordinator.FIXED_LONG_SAMPLES, memoInput.getText().toString())) {
            toast("수신 상태를 확인하고 안내를 일시정지하거나 기록·저장을 끝내세요.");
        }
    }

    private void toggleContinuous() {
        if (coordinator.snapshot().canStopContinuous) coordinator.stopCapture();
        else if (!coordinator.requestManual("continuous", 0, memoInput.getText().toString())) {
            toast("수신 상태를 확인하고 안내를 일시정지하거나 기록·저장을 끝내세요.");
        }
    }

    private void endSession() { coordinator.endSession(); }

    private void showCue(CaptureCoordinator.Cue cue, String label) {
        switch (cue) {
            case ARMED:
                prompt("idle".equals(label) ? "가만히 10초" : "other".equals(label) ? "명령 아닌 움직임 10초" : "다음: " + displayName(label), DirectionDial.Phase.ARMED, label);
                speak("idle".equals(label) ? "가만히" : "other".equals(label) ? "명령 아닌 움직임" : spokenName(label));
                break;
            case STILL:
                tone(ToneGenerator.TONE_PROP_BEEP);
                prompt("continuous".equals(label) ? "연속 기록 중" : "가만히…", DirectionDial.Phase.STILL, label);
                break;
            case GO:
                tone(ToneGenerator.TONE_PROP_BEEP2);
                prompt("지금! " + displayName(label), DirectionDial.Phase.GO, label);
                break;
            case SAVED:
                tone(ToneGenerator.TONE_PROP_ACK);
                prompt("저장", DirectionDial.Phase.SAVED, null);
                event.accept(displayName(label) + " 저장");
                break;
            case FAILED:
                prompt("기록 실패 · 다시 준비", DirectionDial.Phase.IDLE, null);
                event.accept(displayName(label) + " 실패(샘플 누락·연결·시간 초과 확인)");
                break;
            case WAITING: prompt("링 연결·재개 대기", DirectionDial.Phase.IDLE, null); break;
            case PAUSED: prompt("일시정지", DirectionDial.Phase.IDLE, null); break;
            case GUIDE_DONE:
                prompt("안내 수집 완료", DirectionDial.Phase.SAVED, null);
                speak("끝"); event.accept("안내 수집 완료"); break;
            case SESSION_CLOSED:
                prompt("세션 종료", DirectionDial.Phase.IDLE, null);
                event.accept("세션 종료 저장 완료"); break;
            case REDONE: prompt("방금 것 삭제, 다시 준비", DirectionDial.Phase.IDLE, null); break;
        }
    }

    /** Preview values are presentation only; never modify the coordinator or create files. */
    public void previewCounts() {
        for (int i = 0; i < DIRECTION_LABELS.length; i++) previewCounts.put(DIRECTION_LABELS[i], 3 + i % 2);
        updateProgress();
    }

    public void previewGuide(DirectionDial.Phase phase) {
        previewGuide = true;
        prompt(phase == DirectionDial.Phase.GO ? "지금! 위↑" : "가만히…", phase, "raw_up");
        updateProgress();
    }

    public void shutdown() {
        coordinator.close(); // Drains accepted CSV/sidecar/summary/marker jobs before executor shutdown.
        tts.shutdown();
        tones.release();
    }
}
