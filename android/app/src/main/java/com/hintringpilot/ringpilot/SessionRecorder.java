package com.hintringpilot.ringpilot;

import android.os.Handler;
import android.os.SystemClock;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

/**
 * 수집 세션과 기록 파일. 세션마다 files/sessions/날짜-시각 폴더에 기록 CSV와 사이드카(.capture.json)를 쓴다.
 * 정해진 길이 기록(방향 4초, idle/other 10초)은 슬롯이 하나라도 비면 실패로 처리해 깨끗한 파일만 남기고,
 * 연속 기록은 공백을 timestamp 간격으로 남긴다. PC로 옮기고 지우는 일은 tools/pull-phone-sessions.js가 맡는다.
 *
 * 스레드: 샘플은 Bluetooth 스레드에서 들어오고(acceptSamples), 나머지는 메인 스레드에서 부른다.
 * 진행 중인 기록은 lock으로 지키고, 파일 쓰기는 단일 스레드(fileWriter)에서 순서대로 한다.
 */
final class SessionRecorder {
    // 원시값 환산(펌웨어 ±4 g, ±2000 dps 설정, LSM6DS3 라이브러리 calcAccel/calcGyro와 동일)
    private static final double ACC_MS2_PER_LSB = 0.061 * 2 / 1000.0 * 9.80665;
    private static final double GYRO_DPS_PER_LSB = 4.375 * 16 / 1000.0;
    private static final int GYRO_RANGE_DPS = 2000;
    private static final long SLOT_MS = 10;
    private static final long TIMEOUT_EXTRA_MS = 2500;  // 정해진 길이 기록이 이만큼 더 늦으면 실패 처리
    private static final int FLUSH_BYTES = 64 * 1024;   // 연속 기록은 이만큼 모이면 파일에 덧붙인다
    private static final String CSV_HEADER = "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ\n";
    private static final String SESSION_DONE_MARKER = "SESSION_DONE";  // PC 옮기기 도구는 이 표시가 있는 세션만 가져간다

    /** 메인 스레드에서 불린다. */
    interface Listener {
        void onEvent(String text);
        void onWarning(String text);
        void onChanged();
    }

    /** 정해진 길이 기록이 끝나거나 실패하면 메인 스레드에서 불린다. */
    interface Done {
        void finished(Capture capture, boolean ok, String reason);
    }

    static final class Capture {
        final String label;
        final int target;  // 0 이하면 길이 제한 없음(연속 기록)
        final File file;
        final Done done;
        final long startedAt;
        final CaptureSidecar sidecar;
        final StringBuilder rows = new StringBuilder();
        long endedAt;
        boolean csvWriteFailed;  // fileWriter에서만 바꾼다
        long firstSlot = -1;
        long nextSlot = -1;
        int count = 0;
        long gapSamples = 0;
        boolean finished = false;

        Capture(String label, int target, File file, Done done, long startedAt, String activityId) {
            this.label = label;
            this.target = target;
            this.file = file;
            this.done = done;
            this.startedAt = startedAt;
            this.sidecar = new CaptureSidecar(file.getName(), target, startedAt, file.getParentFile().getName(), activityId);
        }

        boolean continuous() {
            return target <= 0;
        }
    }

    private final File baseDir;
    private final Handler mainHandler;
    private final Listener listener;
    private final Supplier<String> memo;
    private final String activityInstanceId = UUID.randomUUID().toString();
    private final ExecutorService fileWriter = Executors.newSingleThreadExecutor();
    private final Object lock = new Object();
    private final Map<String, Integer> savedCounts = new LinkedHashMap<>();
    private final Map<String, Integer> nextIndex = new LinkedHashMap<>();
    private final String sessionNote;

    private File sessionDir;
    private Capture capture;  // lock으로 지킨다
    private File lastSavedFile;
    private String lastSavedLabel;

    /** sessionNote는 session_info.txt에 그대로 덧붙는 수집 조건(예: 기록 길이)이다. */
    SessionRecorder(File baseDir, Handler mainHandler, Listener listener, Supplier<String> memo, String sessionNote) {
        this.baseDir = baseDir;
        this.mainHandler = mainHandler;
        this.listener = listener;
        this.memo = memo;
        this.sessionNote = sessionNote;
    }

    // ---------------------------------------------------------------- 세션

    File sessionDir() {
        return sessionDir;
    }

    /** 라벨별 저장 개수. 화면 미리보기에서 값을 넣을 수 있게 그대로 내준다. */
    Map<String, Integer> savedCounts() {
        return savedCounts;
    }

    int savedCount(String label) {
        return savedCounts.getOrDefault(label, 0);
    }

    File lastSavedFile() {
        return lastSavedFile;
    }

    void ensureSession() {
        if (sessionDir != null) return;
        String name = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
        sessionDir = new File(new File(baseDir, "sessions"), name);
        if (!sessionDir.mkdirs()) listener.onWarning("세션 폴더를 만들지 못했습니다.");
        savedCounts.clear();
        nextIndex.clear();
        lastSavedFile = null;
        String info = "session=" + name + "\n"
                + "started=" + timestamp() + "\n"
                + "memo=" + memo.get().replace('\n', ' ') + "\n"
                + "device=" + ImuBleClient.DEVICE_NAME + "\n"
                + "csv=timestamp ms, accX/Y/Z m/s^2 (raw x 0.122 mg), gyrX/Y/Z deg/s (raw x " + GYRO_DPS_PER_LSB + ")\n"
                + "gyro_range_dps=" + GYRO_RANGE_DPS + "\n"
                + sessionNote + "\n";
        File infoFile = new File(sessionDir, "session_info.txt");
        fileWriter.execute(() -> writeText(infoFile, info, false));
        listener.onEvent("세션 시작 " + name);
        listener.onChanged();
    }

    /** 진행 중인 기록은 버린다. 연속 기록은 먼저 stopContinuous로 저장해야 한다. */
    void endSession() {
        if (sessionDir == null) return;
        abort();
        StringBuilder summary = new StringBuilder("ended=" + timestamp() + "\ncounts=");
        for (Map.Entry<String, Integer> entry : savedCounts.entrySet()) {
            summary.append(entry.getKey()).append(':').append(entry.getValue()).append(' ');
        }
        summary.append('\n');
        File dir = sessionDir;
        String text = summary.toString();
        fileWriter.execute(() -> {
            writeText(new File(dir, "session_info.txt"), text, true);
            writeText(new File(dir, SESSION_DONE_MARKER), "", false);
        });
        listener.onEvent("세션 종료 " + dir.getName());
        sessionDir = null;
        listener.onChanged();
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

    // ---------------------------------------------------------------- 기록

    boolean captureActive() {
        synchronized (lock) {
            return capture != null;
        }
    }

    boolean continuousRunning() {
        synchronized (lock) {
            return capture != null && capture.continuous();
        }
    }

    /** target 샘플을 모으는 기록을 시작한다. target이 0 이하면 멈출 때까지 쓰는 연속 기록이다. */
    Capture start(String label, int target, Done done) {
        long startCall = SystemClock.elapsedRealtime();
        ensureSession();
        Capture c = new Capture(label, target, nextFile(label), done, startCall, activityInstanceId);
        if (c.continuous()) {
            fileWriter.execute(() -> c.csvWriteFailed |= !writeText(c.file, CSV_HEADER, false));
        }
        synchronized (lock) {
            capture = c;
        }
        if (!c.continuous()) {
            mainHandler.postDelayed(() -> {
                synchronized (lock) {
                    if (capture != c || c.finished) return;
                    finish(c);
                    queueSidecar(c, "timeout", "capture timeout");
                }
                c.done.finished(c, false, "시간 초과(연결 확인)");
            }, target * SLOT_MS + TIMEOUT_EXTRA_MS);
        }
        return c;
    }

    /** 진행 중인 기록을 파일 없이 버린다(사이드카에는 남긴다). */
    void abort() {
        synchronized (lock) {
            if (capture == null) return;
            Capture c = capture;
            finish(c);
            queueSidecar(c, "aborted", "capture cancelled");
        }
    }

    /** lock 안에서 부른다. */
    private void finish(Capture c) {
        c.finished = true;
        c.endedAt = SystemClock.elapsedRealtime();
        capture = null;
    }

    /** Bluetooth 스레드에서 호출된다. */
    void acceptSamples(long firstSlot, short[] raw, int count, long arrival) {
        Capture done = null;
        boolean ok = false;
        String reason = null;
        synchronized (lock) {
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
                    if (!c.continuous()) {
                        reason = "샘플 " + (slot - c.nextSlot) + "개 누락";
                        done = c;
                        break;
                    }
                    c.gapSamples += slot - c.nextSlot;
                }
                appendRow(c.rows, (slot - c.firstSlot) * SLOT_MS, raw, i * 6);
                c.nextSlot = slot + 1;
                c.count++;
                c.sidecar.accept(slot, arrival);
                if (!c.continuous() && c.count >= c.target) {
                    ok = true;
                    done = c;
                    break;
                }
            }
            if (done != null) {
                finish(done);
                if (!ok) queueSidecar(done, "sample_gap", reason);
            } else if (c.continuous() && c.rows.length() > FLUSH_BYTES) {
                String data = c.rows.toString();
                c.rows.setLength(0);
                fileWriter.execute(() -> c.csvWriteFailed |= !writeText(c.file, data, true));
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

    /** 성공한 정해진 길이 기록을 파일로 쓴다. 실패한 기록은 파일을 만들지 않는다. */
    void saveFixed(Capture c) {
        String data = CSV_HEADER + c.rows;
        fileWriter.execute(() -> {
            c.csvWriteFailed |= !writeText(c.file, data, false);
            writeSidecar(c, "completed", null);
        });
        markSaved(c.file, c.label);
    }

    /** 연속 기록을 끝내고 남은 행을 덧붙인다. 연속 기록이 아니면 null. */
    Capture stopContinuous() {
        Capture c;
        String rest;
        synchronized (lock) {
            c = capture;
            if (c == null || !c.continuous()) return null;
            finish(c);
            rest = c.rows.toString();
            c.rows.setLength(0);
        }
        fileWriter.execute(() -> {
            c.csvWriteFailed |= !writeText(c.file, rest, true);
            writeSidecar(c, "stopped", "continuous capture finalized");
        });
        markSaved(c.file, c.label);
        return c;
    }

    private void markSaved(File file, String label) {
        lastSavedFile = file;
        lastSavedLabel = label;
        countSaved(label, 1);
        listener.onChanged();
    }

    /** 마지막으로 저장한 기록을 지우고 그 라벨을 돌려준다. 진행 중인 정해진 길이 기록도 버린다. 없으면 null. */
    String deleteLast() {
        if (lastSavedFile == null) return null;
        File file = lastSavedFile;
        String label = lastSavedLabel;
        lastSavedFile = null;
        if (!continuousRunning()) abort();
        fileWriter.execute(file::delete);
        countSaved(label, -1);
        listener.onEvent(file.getName() + " 삭제");
        return label;
    }

    // ---------------------------------------------------------------- 파일

    // 사이드카는 CSV와 같은 순서로 쓰고, 이미 있는 사이드카를 덮어쓰지 않는다.
    private void queueSidecar(Capture c, String status, String reason) {
        fileWriter.execute(() -> writeSidecar(c, status, reason));
    }

    private void writeSidecar(Capture c, String status, String reason) {
        File sidecar = new File(c.file.getParentFile(), c.file.getName() + ".capture.json");
        String finalStatus = c.csvWriteFailed ? "csv_write_failed" : status;
        if (c.csvWriteFailed) mainHandler.post(() -> listener.onEvent(c.file.getName() + " CSV 저장 실패(분석 사용 금지)"));
        try {
            CaptureSidecar.writeExclusive(sidecar, c.sidecar.json(c.endedAt, finalStatus, reason, c.file.isFile(), c.csvWriteFailed));
        } catch (IOException e) {
            mainHandler.post(() -> listener.onEvent(sidecar.getName() + " 메타데이터 저장 실패: " + e.getClass().getSimpleName()));
        }
    }

    private static String timestamp() {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date());
    }

    /** 실패하면 false. 기록 CSV는 실패를 사이드카에도 남긴다. */
    private static boolean writeText(File file, String text, boolean append) {
        try (FileWriter writer = new FileWriter(file, append)) {
            writer.write(text);
            return true;
        } catch (IOException ignored) {
            return false;
        }
    }

    void shutdown() {
        fileWriter.shutdown();
    }
}
