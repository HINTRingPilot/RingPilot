package com.hintringpilot.ringpilot.dev;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The production capture owner, independent of Android. Every state transition and queue registration
 * uses one lock. WriteQueue must be serial, non-inline and accept execute calls until shutdown.
 * File work never waits for the UI queue; accepted writes survive an Activity's destruction.
 */
final class CaptureCoordinator {
    static final int GESTURE_SAMPLES = 400, FIXED_LONG_SAMPLES = 1000;
    static final long PROMPT_MS = 1200, PRE_ROLL_MS = 1000, REST_MS = 1000, TIMEOUT_EXTRA_MS = 2500;
    static final String HEADER = "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ\n";
    private static final double ACC_SCALE = 0.061 * 2 / 1000.0 * 9.80665;
    private static final double GYRO_SCALE = 4.375 * 16 / 1000.0;

    enum State { IDLE, ARMING, RECORDING, FINALIZING }
    enum Cue { ARMED, STILL, GO, SAVED, FAILED, WAITING, PAUSED, GUIDE_DONE, SESSION_CLOSED, REDONE }
    interface Clock { long elapsedMillis(); long wallMillis(); }
    interface UiScheduler { void post(Runnable action, long delayMillis); }
    interface WriteQueue { void execute(Runnable action); void shutdown(); }
    interface Listener {
        void onChanged(Snapshot snapshot);
        void onCue(Cue cue, String label);
        void onError(String message);
    }

    static final class Snapshot {
        final State state;
        final File directory, lastSavedFile;
        final Map<String, Integer> savedCounts;
        final boolean closing, guideRunning, guidePaused;
        final boolean hasSession, canEndSession, canStartManual, canStartGuide, canResumeGuide,
                canPauseGuide, canStopContinuous, canToggleContinuous, canRedo;
        final int guideIndex, guideSize;
        final String label;
        final int target;
        final String error;
        Snapshot(CaptureCoordinator owner) {
            Session s = owner.session != null ? owner.session : owner.pendingSession;
            Reservation r = owner.active;
            state = owner.state; directory = s == null ? null : s.directory;
            closing = s != null && s.closing;
            hasSession = s != null;
            canEndSession = !owner.destroyed && hasSession && !closing;
            canStartManual = owner.canStartManualLocked();
            canStartGuide = owner.canStartGuideLocked();
            canResumeGuide = owner.guideRunning && owner.guidePaused && owner.available();
            canPauseGuide = !owner.destroyed && !closing && owner.guideRunning && !owner.guidePaused;
            canStopContinuous = !owner.destroyed && !closing && r != null && r.target <= 0
                    && (state == State.ARMING || state == State.RECORDING);
            canToggleContinuous = canStartManual || canStopContinuous;
            canRedo = owner.canRedoLocked();
            lastSavedFile = s == null ? null : s.lastSavedFile;
            savedCounts = Collections.unmodifiableMap(new LinkedHashMap<>(s == null ? Collections.emptyMap() : s.counts));
            guideRunning = owner.guideRunning; guidePaused = owner.guidePaused;
            guideIndex = owner.guideIndex; guideSize = owner.guideQueue.size();
            label = r == null ? null : r.label; target = r == null ? -1 : r.target;
            error = owner.lastError;
        }
    }

    /** Injectable failure boundary; default operations use exclusive creation and force file data. */
    static class Storage {
        File createSession(File root, long wall) throws IOException { return SessionDirectory.create(root, wall); }
        void writeNew(File file, String data) throws IOException {
            write(file, data, () -> { }, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        }
        void append(File file, String data) throws IOException {
            write(file, data, () -> { }, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
        }
        void createHeader(File file, Runnable created) throws IOException {
            write(file, HEADER, created, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        }
        void createMarker(File file, Runnable created) throws IOException {
            write(file, "", created, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        }
        void delete(File file) throws IOException { Files.delete(file.toPath()); }
        private void write(File file, String data, Runnable created, StandardOpenOption... options) throws IOException {
            try (FileChannel channel = FileChannel.open(file.toPath(), options)) {
                created.run();
                ByteBuffer bytes = ByteBuffer.wrap(data.getBytes(StandardCharsets.UTF_8));
                while (bytes.hasRemaining()) channel.write(bytes);
                channel.force(true);
            }
        }
    }
    private static final class Session {
        File directory;
        boolean initialized, initializationFailed, closing;
        final long wall;
        final String memo;
        final Map<String, Integer> counts = new LinkedHashMap<>(), nextIndex = new LinkedHashMap<>();
        File lastSavedFile;
        String lastSavedLabel;
        Session(long wall, String memo) { this.wall = wall; this.memo = memo; }
    }
    private static final class Reservation {
        final long id, stream;
        final Session session;
        final String label;
        final int target;
        final boolean guided;
        final int guideIndex;
        boolean prepared, delayElapsed;
        boolean startScheduled;
        File file;
        Capture capture;
        boolean headerCreated; // ownership fact; only the serial writer accesses this field
        Reservation(long id, long stream, Session session, String label, int target, boolean guided, int index) {
            this.id = id; this.stream = stream; this.session = session; this.label = label;
            this.target = target; this.guided = guided; this.guideIndex = index;
        }
    }
    private static final class Capture {
        final CaptureSidecar sidecar;
        final SlotContinuity continuity = new SlotContinuity();
        final StringBuilder rows = new StringBuilder();
        long firstSlot = -1;
        int count;
        IOException csvError; // only the serial writer accesses this field
        Capture(Reservation r, long start, String activity) {
            sidecar = new CaptureSidecar(r.file.getName(), r.target, start, r.session.directory.getName(), activity);
        }
    }

    private final Object lock = new Object();
    private final File root;
    private final String activity;
    private final Clock clock;
    private final UiScheduler ui;
    private final WriteQueue writer;
    private final Listener listener;
    private final Storage storage;
    private State state = State.IDLE;
    private Session session, pendingSession, guideSession;
    private Reservation active;
    private long serial, visibleId, streamGeneration = -1, guideEpoch, uiEpoch;
    private boolean streaming, destroyed, guideRunning, guidePaused, guideScheduled;
    private final List<String> guideQueue = new ArrayList<>();
    private int guideIndex;
    private String lastError;

    CaptureCoordinator(File root, String activity, Clock clock, UiScheduler ui, WriteQueue writer, Listener listener) {
        this(root, activity, clock, ui, writer, listener, new Storage());
    }
    CaptureCoordinator(File root, String activity, Clock clock, UiScheduler ui, WriteQueue writer, Listener listener, Storage storage) {
        this.root = root; this.activity = activity; this.clock = clock; this.ui = ui;
        this.writer = writer; this.listener = listener; this.storage = storage;
    }
    Snapshot snapshot() { synchronized (lock) { return snapshotLocked(); } }
    private Snapshot snapshotLocked() {
        return new Snapshot(this);
    }
    boolean requestManual(String label, int target, String memo) {
        synchronized (lock) {
            if (!canStartManualLocked()) return false;
            reserve(label, target, false, ensureSession(memo)); return true;
        }
    }
    boolean startGuide(List<String> labels, String memo) {
        synchronized (lock) {
            if (!canStartGuideLocked() || labels.isEmpty()) return false;
            guideEpoch++; guideScheduled = false;
            guideQueue.clear(); guideQueue.addAll(labels); guideIndex = 0;
            guideRunning = true; guidePaused = false; guideSession = ensureSession(memo);
            if (streaming) reserve(guideQueue.get(0), GESTURE_SAMPLES, true, guideSession);
            else { prepareSession(guideSession); cue(Cue.WAITING, null, visibleId); }
            changed(); return true;
        }
    }
    private boolean available() {
        return !destroyed && state == State.IDLE && (session == null || (!session.closing && !session.initializationFailed))
                && (pendingSession == null || (!pendingSession.closing && !pendingSession.initializationFailed));
    }
    private boolean canStartManualLocked() { return available() && streaming && (!guideRunning || guidePaused); }
    private boolean canStartGuideLocked() { return available() && (!guideRunning || guidePaused); }
    private boolean canRedoLocked() { return available() && session != null && session.lastSavedFile != null; }
    private Session ensureSession(String memo) {
        if (session != null) return session;
        if (pendingSession == null) pendingSession = new Session(clock.wallMillis(), memo == null ? "" : memo);
        return pendingSession;
    }
    private void prepareSession(Session s) {
        // Queued before any terminal or close job, including an ARMING cancellation.
        writer.execute(() -> {
            try { initialize(s); }
            catch (IOException error) { synchronized (lock) { preparationFailed(s, null, error); } }
        });
    }
    private void initialize(Session s) throws IOException {
        if (s.initialized) return;
        if (s.initializationFailed) throw new IOException("failed session must be ended before starting a new session");
        File dir = s.directory;
        if (dir == null) {
            dir = storage.createSession(root, s.wall);
            synchronized (lock) { s.directory = dir; changed(); }
        }
        String info = "session=" + dir.getName() + "\nstarted=" + timestamp(s.wall)
                + "\nmemo=" + s.memo.replace('\n', ' ') + "\ndevice=RingPilot-IMU\n"
                + "csv=timestamp ms, accX/Y/Z m/s^2 (raw x 0.122 mg), gyrX/Y/Z deg/s (raw x " + GYRO_SCALE + ")\n"
                + "gyro_range_dps=2000\ngesture_samples=400 pre_roll_cue_ms=1000\n";
        storage.writeNew(new File(dir, "session_info.txt"), info);
        synchronized (lock) {
            s.directory = dir; s.initialized = true;
            if (pendingSession == s) { session = s; pendingSession = null; }
            changed();
        }
    }
    private void reserve(String label, int target, boolean guided, Session s) {
        Reservation r = new Reservation(++serial, streamGeneration, s, label, target, guided, guideIndex);
        active = r; visibleId = r.id; state = State.ARMING;
        cue(Cue.ARMED, label, r.id); changed();
        ui.post(() -> {
            synchronized (lock) {
                if (!valid(r)) return;
                r.delayElapsed = true; beginIfPrepared(r);
            }
        }, target <= 0 ? 0 : PROMPT_MS);
        writer.execute(() -> {
            try {
                initialize(s);
                synchronized (lock) {
                    if (!valid(r)) return;
                    int index = s.nextIndex.getOrDefault(label, 1); s.nextIndex.put(label, index + 1);
                    r.file = new File(s.directory, label + "." + index + ".csv");
                }
                // Continuous samples cannot be accepted until exclusive header creation succeeds.
                if (target <= 0) storage.createHeader(r.file, () -> r.headerCreated = true);
                synchronized (lock) { if (valid(r)) { r.prepared = true; beginIfPrepared(r); } }
            } catch (IOException error) {
                synchronized (lock) { preparationFailed(s, r, error); }
            }
        });
    }
    private boolean valid(Reservation r) {
        return active == r && state == State.ARMING && !destroyed && !r.session.closing
                && streaming && streamGeneration == r.stream;
    }
    private void preparationFailed(Session s, Reservation r, IOException error) {
        // Never retry CREATE_NEW over a possibly partial session_info. Keep its folder for diagnosis,
        // require explicit session close, then allocate a fresh folder for the next request.
        if (!s.initialized) s.initializationFailed = true;
        String message = "세션/CSV 준비 실패 [" + (s.directory == null ? root : s.directory).getAbsolutePath()
                + "]: " + error.getMessage() + (s.initializationFailed ? " · 세션 종료 후 새로 시작하세요." : "");
        if ((r != null && active == r) || (r == null && active == null && guideSession == s)) {
            if (r != null) cleanupHeader(r);
            active = null; state = State.IDLE; visibleId = ++serial;
            guidePaused = guideRunning; invalidateGuide();
            error(message); changed();
        } else {
            error(message); changed();
        }
    }
    private void beginIfPrepared(Reservation r) {
        if (!valid(r) || !r.prepared || !r.delayElapsed || r.startScheduled) return;
        r.startScheduled = true;
        ui.post(() -> {
            synchronized (lock) {
                if (!valid(r)) return;
                // The actual start is a UI task: play the start cue before accepting any samples.
                // A stalled UI cannot consume the preroll before the user hears the cue.
                listener.onCue(Cue.STILL, r.label);
                r.capture = new Capture(r, clock.elapsedMillis(), activity); state = State.RECORDING;
                changed();
                if (r.guided) ui.post(() -> {
                    synchronized (lock) {
                        if (active == r && state == State.RECORDING) cue(Cue.GO, r.label, r.id);
                    }
                }, PRE_ROLL_MS);
                if (r.target > 0) ui.post(() -> {
                    synchronized (lock) {
                        if (active == r && state == State.RECORDING) terminal(r, false, "timeout", "capture timeout");
                    }
                }, r.target * 10L + TIMEOUT_EXTRA_MS);
            }
        }, 0);
    }
    void onSamples(long generation, long firstSlot, short[] raw, int count, long arrival) {
        synchronized (lock) {
            Reservation r = active;
            if (!streaming || generation != streamGeneration || r == null || r.stream != generation
                    || state != State.RECORDING || count <= 0 || raw.length < count * 6) return;
            Capture c = r.capture;
            long expected = c.continuity.expectedSlot();
            SlotContinuity.Kind kind = c.continuity.accept(firstSlot, count);
            if (kind == SlotContinuity.Kind.DUPLICATE) return;
            if (kind == SlotContinuity.Kind.DISCONTINUITY) {
                terminal(r, r.target <= 0, r.target <= 0 ? "stopped" : "aborted", "slot_discontinuity"); return;
            }
            if (kind == SlotContinuity.Kind.FORWARD_GAP && r.target > 0) {
                terminal(r, false, "sample_gap", "missing " + (firstSlot - expected) + " samples"); return;
            }
            for (int i = 0; i < count; i++) {
                long slot = firstSlot + i;
                if (c.firstSlot < 0) c.firstSlot = slot;
                appendRow(c.rows, (slot - c.firstSlot) * 10, raw, i * 6);
                c.sidecar.accept(slot, arrival); c.count++;
                if (r.target > 0 && c.count >= r.target) { terminal(r, true, "completed", null); return; }
            }
            if (r.target <= 0 && c.rows.length() > 64 * 1024) {
                String rows = c.rows.toString(); c.rows.setLength(0);
                writer.execute(() -> {
                    if (c.csvError != null) return;
                    try { storage.append(r.file, rows); }
                    catch (IOException error) {
                        c.csvError = error;
                        synchronized (lock) {
                            if (active == r && state == State.RECORDING) terminal(r, false, "csv_write_failed", error.getMessage());
                        }
                    }
                });
            }
        }
    }
    private static void appendRow(StringBuilder out, long time, short[] raw, int offset) {
        out.append(time);
        for (int axis = 0; axis < 6; axis++) out.append(',').append(String.format(Locale.US, "%.5f",
                raw[offset + axis] * (axis < 3 ? ACC_SCALE : GYRO_SCALE)));
        out.append('\n');
    }
    /** Register immutable terminal work BEFORE detaching recording state, under the same lock. */
    private void terminal(Reservation r, boolean acceptedSuccess, String status, String reason) {
        if (active != r || state != State.RECORDING) return;
        Capture c = r.capture;
        String rows = c.rows.toString(); c.rows.setLength(0);
        long ended = clock.elapsedMillis();
        long resultId = ++serial;
        visibleId = resultId; // Queued STILL/GO cues belong to the previous recording phase.
        // Freeze both variants now: later callbacks cannot mutate timing facts used by this job.
        String normalJson = c.sidecar.json(ended, status, reason, acceptedSuccess || r.target <= 0, false);
        String failedExistingJson = c.sidecar.json(ended, "csv_write_failed", reason, true, true);
        String failedMissingJson = c.sidecar.json(ended, "csv_write_failed", reason, false, true);
        writer.execute(() -> {
            IOException failure = c.csvError;
            boolean csvExists = r.target <= 0;
            if (failure == null && (acceptedSuccess || r.target <= 0)) {
                try {
                    if (r.target > 0) storage.writeNew(r.file, HEADER + rows);
                    else storage.append(r.file, rows);
                    csvExists = true;
                } catch (IOException error) { failure = error; }
            }
            try {
                // All timing/row facts were frozen when the terminal job was registered.
                String json = failure == null ? normalJson : r.file.isFile() ? failedExistingJson : failedMissingJson;
                storage.writeNew(new File(r.session.directory, r.file.getName() + ".capture.json"), json);
            } catch (IOException error) { if (failure == null) failure = error; }
            synchronized (lock) { persisted(r, resultId, acceptedSuccess && csvExists && failure == null, failure); }
        });
        state = State.FINALIZING;
        changed();
    }
    private void persisted(Reservation r, long resultId, boolean success, IOException failure) {
        Session s = r.session;
        if (success) {
            s.counts.put(r.label, s.counts.getOrDefault(r.label, 0) + 1);
            s.lastSavedFile = r.file; s.lastSavedLabel = r.label;
            if (r.guided && guideRunning && guideSession == s && guideIndex == r.guideIndex) guideIndex++;
        }
        if (active == r) { active = null; state = State.IDLE; }
        if (failure != null) {
            guidePaused = guideRunning; invalidateGuide();
            error("캡처 저장 실패 [" + r.file.getAbsolutePath() + "]: " + failure.getMessage());
        }
        if (!s.closing && !destroyed) {
            cue(success ? Cue.SAVED : Cue.FAILED, r.label, resultId);
            if (guideRunning && !guidePaused) scheduleGuide(REST_MS);
        }
        changed();
    }
    void onStreamReady(long generation) {
        synchronized (lock) {
            if (destroyed || generation < streamGeneration) return;
            if (generation > streamGeneration && active != null) boundaryLocked(streamGeneration, "connection_lost");
            streamGeneration = generation; streaming = true;
            scheduleGuide(0); changed();
        }
    }
    void onStreamBoundary(long generation, String reason) {
        synchronized (lock) { boundaryLocked(generation, reason); }
    }
    private void boundaryLocked(long generation, String reason) {
        if (generation != streamGeneration) return;
        streaming = false; invalidateGuide();
        if (active != null && active.stream == generation) {
            if (state == State.ARMING) cancelArming();
            else if (state == State.RECORDING) terminal(active, active.target <= 0,
                    active.target <= 0 ? "stopped" : "aborted", reason);
        }
        if (guideRunning && !guidePaused) cue(Cue.WAITING, null, visibleId);
        changed();
    }
    boolean toggleGuidePause() {
        synchronized (lock) {
            if (!guideRunning || destroyed) return false;
            if (guidePaused) {
                if (!available()) return false;
                guidePaused = false; scheduleGuide(0);
            } else {
                guidePaused = true; invalidateGuide();
                if (active != null && active.guided) cancelCapture("aborted");
                cue(Cue.PAUSED, null, visibleId);
            }
            changed(); return true;
        }
    }
    private void invalidateGuide() { guideEpoch++; guideScheduled = false; }
    private void scheduleGuide(long delay) {
        if (destroyed || !guideRunning || guidePaused || guideScheduled || !streaming || !available()
                || guideSession == null || guideSession.closing || (session != guideSession && pendingSession != guideSession)) return;
        if (guideIndex >= guideQueue.size()) {
            guideRunning = false; cue(Cue.GUIDE_DONE, null, visibleId); changed(); return;
        }
        guideScheduled = true;
        long epoch = guideEpoch; Session s = guideSession;
        ui.post(() -> {
            synchronized (lock) {
                if (epoch != guideEpoch) return;
                guideScheduled = false;
                if (!destroyed && guideRunning && !guidePaused && streaming && available()
                        && guideSession == s && !s.closing && (session == s || pendingSession == s)) {
                    reserve(guideQueue.get(guideIndex), GESTURE_SAMPLES, true, s);
                }
            }
        }, delay);
    }
    void stopCapture() { synchronized (lock) { cancelCapture("stopped"); } }
    private void cancelCapture(String status) {
        if (state == State.ARMING) cancelArming();
        else if (state == State.RECORDING) terminal(active, active.target <= 0, active.target <= 0 ? status : "aborted", "capture cancelled");
    }
    private void cancelArming() {
        cleanupHeader(active);
        active = null; state = State.IDLE; visibleId = ++serial; changed();
    }
    private void cleanupHeader(Reservation r) {
        if (r == null || r.target > 0 || r.file == null) return;
        // Register before detaching ARMING and before a session close. The ownership flag is set
        // only after this reservation's CREATE_NEW succeeds, never for a pre-existing file.
        writer.execute(() -> {
            if (!r.headerCreated) return;
            try { storage.delete(r.file); r.headerCreated = false; }
            catch (IOException failure) {
                synchronized (lock) { error("취소한 CSV 헤더 정리 실패 [" + r.file.getAbsolutePath() + "]: " + failure.getMessage()); }
            }
        });
    }

    boolean redoLast() {
        synchronized (lock) {
            if (!canRedoLocked()) return false;
            Session s = session; File file = s.lastSavedFile; String label = s.lastSavedLabel;
            invalidateGuide(); visibleId = ++serial; state = State.FINALIZING;
            writer.execute(() -> {
                IOException failure = null;
                try { storage.delete(file); } catch (IOException error) { failure = error; }
                synchronized (lock) {
                    if (failure == null) {
                        int count = s.counts.getOrDefault(label, 0) - 1;
                        if (count <= 0) s.counts.remove(label); else s.counts.put(label, count);
                        s.lastSavedFile = null;
                        if (label.startsWith("raw_") && !s.closing) {
                            guideQueue.add(Math.min(guideIndex, guideQueue.size()), label);
                            guideSession = s; guideRunning = true;
                        }
                        cue(Cue.REDONE, label, visibleId);
                    } else { guidePaused = guideRunning; error("삭제 실패 [" + file.getAbsolutePath() + "]: " + failure.getMessage()); }
                    state = State.IDLE; scheduleGuide(REST_MS); changed();
                }
            });
            changed(); return true;
        }
    }
    void endSession() {
        synchronized (lock) { endSessionLocked(); }
    }
    private void endSessionLocked() {
        Session s = session != null ? session : pendingSession;
        if (s == null || s.closing) return;
        s.closing = true; guideRunning = false; guidePaused = false; invalidateGuide();
        cancelCapture("stopped"); visibleId = ++serial;
        writer.execute(() -> {
            IOException failure = null;
            File marker = s.directory == null ? null : new File(s.directory, "SESSION_DONE");
            boolean[] markerCreated = {false};
            try {
                if (!s.initialized) throw new IOException("session initialization did not succeed");
                StringBuilder summary = new StringBuilder("ended=" + timestamp(clock.wallMillis()) + "\ncounts=");
                synchronized (lock) { s.counts.forEach((label, count) -> summary.append(label).append(':').append(count).append(' ')); }
                storage.append(new File(s.directory, "session_info.txt"), summary.append('\n').toString());
                storage.createMarker(marker, () -> markerCreated[0] = true);
            } catch (IOException error) {
                failure = error;
                // CREATE_NEW may succeed before write/force/close fails. Revoke only the marker
                // allocated by this call, in this same serial writer job, before reporting failure.
                if (markerCreated[0]) {
                    try { storage.delete(marker); }
                    catch (IOException cleanup) {
                        failure = new IOException(error.getMessage() + " · 잔존 SESSION_DONE 마커 경고 ["
                                + marker.getAbsolutePath() + "]: 정리 실패: " + cleanup.getMessage(), error);
                        failure.addSuppressed(cleanup);
                    }
                }
            }
            synchronized (lock) {
                if (session == s) session = null;
                if (pendingSession == s) pendingSession = null;
                if (failure != null) error("세션 종료 저장 실패(SESSION_DONE 미완료) ["
                        + (s.directory == null ? root : s.directory).getAbsolutePath() + "]: " + failure.getMessage());
                else cue(Cue.SESSION_CLOSED, null, visibleId);
                changed();
            }
        });
        changed();
    }
    void close() {
        synchronized (lock) {
            if (destroyed) return;
            // Invalidate UI first; register terminal and close writes before shutting down the queue.
            destroyed = true; uiEpoch++; endSessionLocked(); writer.shutdown();
        }
    }
    private static String timestamp(long wall) {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(new Date(wall));
    }
    private void changed() {
        long epoch = uiEpoch;
        if (!destroyed) ui.post(() -> {
            Snapshot value;
            synchronized (lock) { if (destroyed || epoch != uiEpoch) return; value = snapshotLocked(); }
            listener.onChanged(value);
        }, 0);
    }
    private void cue(Cue cue, String label, long id) {
        long epoch = uiEpoch;
        if (!destroyed) ui.post(() -> {
            synchronized (lock) { if (destroyed || epoch != uiEpoch || visibleId != id) return; }
            listener.onCue(cue, label);
        }, 0);
    }
    private void error(String message) {
        // Keep a diagnostic even when close() has already invalidated Activity callbacks.
        lastError = message;
        long epoch = uiEpoch;
        if (!destroyed) ui.post(() -> {
            synchronized (lock) { if (destroyed || epoch != uiEpoch) return; }
            listener.onError(message);
        }, 0);
    }
}
