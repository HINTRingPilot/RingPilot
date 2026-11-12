package com.hintringpilot.ringpilot;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Exercises the production coordinator with deliberately stalled UI and disk queues. */
public final class CaptureCoordinatorTest {
    static int checks;
    static void check(boolean value, String why) { checks++; if (!value) throw new AssertionError(why); }
    static final class Harness implements CaptureCoordinator.Clock, CaptureCoordinator.UiScheduler,
            CaptureCoordinator.WriteQueue, CaptureCoordinator.Listener {
        long now, wall = 1794441600000L;
        final List<Task> ui = new ArrayList<>();
        final List<Runnable> disk = new ArrayList<>();
        final List<CaptureCoordinator.Cue> cues = new ArrayList<>();
        final List<String> errors = new ArrayList<>();
        final Path root;
        final CaptureCoordinator coordinator;
        boolean shutdown;
        Harness() throws IOException { this(new CaptureCoordinator.Storage()); }
        Harness(CaptureCoordinator.Storage storage) throws IOException {
            root = Files.createTempDirectory("capture-coordinator-");
            coordinator = new CaptureCoordinator(root.toFile(), "test-activity", this, this, this, this, storage);
            coordinator.onStreamReady(1);
        }
        public long elapsedMillis() { return now; }
        public long wallMillis() { return wall; }
        public void post(Runnable r, long delay) { ui.add(new Task(now + delay, r)); }
        public void execute(Runnable r) { check(!shutdown, "enqueue after shutdown"); disk.add(r); }
        public void shutdown() { shutdown = true; }
        public void onChanged(CaptureCoordinator.Snapshot s) { }
        public void onCue(CaptureCoordinator.Cue cue, String label) { cues.add(cue); }
        public void onError(String message) { errors.add(message); }
        void drainDisk() { while (!disk.isEmpty()) disk.remove(0).run(); }
        void advance(long ms) { now += ms; drainUi(); }
        void drainUi() {
            while (true) {
                Task next = null;
                for (Task t : ui) if (t.at <= now && (next == null || t.at < next.at)) next = t;
                if (next == null) return;
                ui.remove(next); next.run.run();
            }
        }
        void record(String label, int target) {
            check(coordinator.requestManual(label, target, "memo"), "request accepted");
            drainDisk(); advance(target == 0 ? 0 : CaptureCoordinator.PROMPT_MS);
            check(coordinator.snapshot().state == CaptureCoordinator.State.RECORDING, "recording after prerequisites");
        }
        void packet(long generation, long slot, int count) {
            short[] raw = new short[count * 6]; Arrays.fill(raw, (short) 100);
            coordinator.onSamples(generation, slot, raw, count, now);
        }
        File directory() { return coordinator.snapshot().directory; }
        Path csv(String label) { return directory().toPath().resolve(label + ".1.csv"); }
    }
    record Task(long at, Runnable run) { }

    public static void main(String[] args) throws Exception {
        overlapAndStaleCallbacks(); persistenceBeforeClose(); guideWaitsForPersistence();
        streamBoundariesAndSlots(); collisionAndFailures();
        prerequisitesAndFailureOrdering(); staleTimersAndFiniteBoundaries(); epochAndSlotContracts();
        staleCueAndRedo();
        canceledHeaderOwnership();
        partialMetadataRequiresFreshSession();
        failedMarkerCreationOwnership();
        System.out.println("CaptureCoordinator: " + checks + " checks passed");
    }
    static void overlapAndStaleCallbacks() throws Exception {
        Harness h = new Harness();
        check(h.coordinator.requestManual("idle", 1000, ""), "first reservation");
        check(h.coordinator.snapshot().hasSession && h.coordinator.snapshot().canEndSession, "pending session can be canceled before metadata");
        check(!h.coordinator.snapshot().canStartManual && !h.coordinator.snapshot().canStartGuide, "ARMING disables competing start buttons");
        check(!h.coordinator.requestManual("other", 1000, ""), "double tap rejected while ARMING");
        check(!h.coordinator.startGuide(List.of("raw_up"), ""), "guide cannot replace manual reservation");
        h.coordinator.endSession(); h.advance(2000); h.drainDisk();
        check(h.coordinator.snapshot().state == CaptureCoordinator.State.IDLE, "stale start after end ignored");
        check(h.coordinator.startGuide(List.of("raw_up"), ""), "guide accepted"); h.drainDisk();
        check(h.coordinator.toggleGuidePause(), "pause guide ARMING"); h.drainDisk();
        h.record("idle", 1000);
        check(!h.coordinator.snapshot().canResumeGuide, "resume button disabled while manual recording");
        check(!h.coordinator.toggleGuidePause(), "resume refused while manual recording");
        h.packet(1, 0, 1000);
        check(!h.coordinator.snapshot().canStartManual && !h.coordinator.snapshot().canResumeGuide, "finalizing disables start and resume buttons");
        check(!h.coordinator.toggleGuidePause(), "resume refused while manual finalizing");
        h.drainDisk(); check(h.coordinator.toggleGuidePause(), "resume after persistence");
        h.advance(1000); h.drainDisk(); h.advance(1200);
        h.packet(1, 1000, 400); h.drainDisk();
        check(h.coordinator.snapshot().savedCounts.get("raw_up") == 1, "direction saved");
        h.record("other", 1000);
        h.advance(2000); // Previous guide timeout is now due; it must not clear the new capture.
        check(h.coordinator.snapshot().state == CaptureCoordinator.State.RECORDING, "old timeout cannot clear new capture");
    }
    static void persistenceBeforeClose() throws Exception {
        for (boolean destroy : new boolean[]{false, true}) {
            Harness h = new Harness(); h.record("raw_up", 400); File dir = h.directory();
            h.packet(1, 90, 400); // Do not let a single UI completion run.
            check(h.coordinator.snapshot().state == CaptureCoordinator.State.FINALIZING, "terminal job reserves finalizing");
            if (destroy) h.coordinator.close(); else h.coordinator.endSession();
            h.coordinator.stopCapture(); h.drainDisk();
            check(Files.readAllLines(dir.toPath().resolve("raw_up.1.csv")).size() == 401, "all 400 rows survive close");
            check(Files.exists(dir.toPath().resolve("raw_up.1.csv.capture.json")), "sidecar before marker");
            check(Files.readString(dir.toPath().resolve("session_info.txt")).contains("raw_up:1"), "summary includes durable count");
            check(Files.exists(dir.toPath().resolve("SESSION_DONE")), "done written");
            if (destroy) check(h.shutdown, "writer shutdown registered after close job");
        }
    }
    static void guideWaitsForPersistence() throws Exception {
        Harness h = new Harness();
        check(h.coordinator.startGuide(List.of("raw_up", "raw_down"), ""), "guide start");
        h.drainDisk(); h.advance(1200); h.packet(1, 0, 400);
        h.advance(10000);
        check(h.coordinator.snapshot().guideIndex == 0, "write delay does not advance index");
        check(h.coordinator.snapshot().state == CaptureCoordinator.State.FINALIZING, "busy during delayed write");
        h.drainDisk(); check(h.coordinator.snapshot().guideIndex == 1, "durable result advances once");
        h.advance(999); check(h.coordinator.snapshot().state == CaptureCoordinator.State.IDLE, "rest starts after persistence");
        h.advance(1); check(h.coordinator.snapshot().state == CaptureCoordinator.State.ARMING, "one next reservation after rest");
        h.coordinator.onStreamReady(1); h.drainDisk(); h.advance(1200);
        check(h.coordinator.snapshot().label.equals("raw_down"), "exactly next direction");
    }
    static void streamBoundariesAndSlots() throws Exception {
        Harness h = new Harness(); h.record("continuous", 0); Path old = h.csv("continuous");
        h.packet(1, 100000, 2); h.packet(1, 100000, 2); h.packet(1, 100004, 2);
        h.packet(1, 0, 2); h.drainDisk();
        String oldMeta = Files.readString(old.resolveSibling(old.getFileName() + ".capture.json"));
        check(oldMeta.contains("\"end_status\": \"stopped\"") && oldMeta.contains("\"end_reason\": \"slot_discontinuity\""), "reset ends old continuous capture with exact status/reason");
        check(Files.readAllLines(old).size() == 5, "duplicate ignored, forward gap retained");
        check(Files.readAllLines(old).get(3).startsWith("40,"), "slot gap preserved in timestamps");
        h.record("continuous", 0); h.packet(1, 0, 2); h.coordinator.onStreamBoundary(1, "stopped");
        h.coordinator.onStreamBoundary(1, "connection_lost"); h.drainDisk();
        check(h.coordinator.snapshot().savedCounts.get("continuous") == 2, "terminal plus stop idempotent");
        h.coordinator.onStreamReady(2); h.record("idle", 1000);
        h.packet(1, 100, 1000); check(h.coordinator.snapshot().state == CaptureCoordinator.State.RECORDING, "old generation callback ignored");
        h.packet(2, 0, 1000); h.drainDisk(); check(h.coordinator.snapshot().savedCounts.get("idle") == 1, "new generation slot zero accepted");
        Harness guide = new Harness(); guide.coordinator.startGuide(List.of("raw_left"), ""); guide.drainDisk();
        guide.coordinator.onStreamBoundary(1, "stopped"); guide.coordinator.onStreamReady(2); guide.coordinator.onStreamReady(2);
        guide.advance(1200); guide.drainDisk(); guide.advance(1200);
        check(guide.coordinator.snapshot().state == CaptureCoordinator.State.RECORDING, "ARMING disconnect retries same direction");
        check(guide.coordinator.snapshot().label.equals("raw_left"), "retry direction unchanged");
        check(guide.cues.stream().filter(c -> c == CaptureCoordinator.Cue.STILL).count() == 1, "stale begin cue canceled and retry deduplicated");
    }
    static void collisionAndFailures() throws Exception {
        Harness h = new Harness(); h.record("idle", 1000); h.packet(1, 0, 1000); h.drainDisk();
        File first = h.directory(); byte[] bytes = Files.readAllBytes(h.csv("idle")); h.coordinator.endSession(); h.drainDisk();
        h.record("idle", 1000); check(!h.directory().equals(first), "same clock unique session");
        check(h.directory().getName().endsWith("-001"), "collision uses compatible suffix");
        h.packet(1, 0, 1000); h.drainDisk(); check(Arrays.equals(bytes, Files.readAllBytes(first.toPath().resolve("idle.1.csv"))), "previous CSV unchanged");
        for (String fail : List.of("mkdir", "session_info.txt", "continuous.1.csv", ".capture.json", "idle.1.csv")) {
            CaptureCoordinator.Storage storage = new CaptureCoordinator.Storage() {
                @Override File createSession(File root, long wall) throws IOException {
                    if (fail.equals("mkdir")) throw new IOException("injected mkdir"); return super.createSession(root, wall);
                }
                @Override void writeNew(File file, String data) throws IOException {
                    if (file.getName().endsWith(fail)) throw new IOException("injected " + fail); super.writeNew(file, data);
                }
                @Override void createHeader(File file, Runnable created) throws IOException {
                    if (file.getName().endsWith(fail)) throw new IOException("injected " + fail); super.createHeader(file, created);
                }
            };
            Harness bad = new Harness(storage);
            boolean continuous = fail.equals("continuous.1.csv");
            bad.coordinator.requestManual(continuous ? "continuous" : "idle", continuous ? 0 : 1000, "");
            bad.drainDisk(); bad.advance(1200);
            if (bad.coordinator.snapshot().state == CaptureCoordinator.State.RECORDING) bad.packet(1, 0, 1000);
            bad.drainDisk();
            check(bad.coordinator.snapshot().state == CaptureCoordinator.State.IDLE, "failure releases busy: " + fail);
            check(bad.coordinator.snapshot().savedCounts.isEmpty(), "failure no success: " + fail);
            if (fail.equals("session_info.txt")) {
                File allocated = bad.directory();
                check(allocated != null && allocated.isDirectory(), "mkdir success is retained after metadata failure");
                check(bad.coordinator.snapshot().error.contains(allocated.getAbsolutePath()), "metadata failure exposes allocated path even for pathless IOException");
                bad.coordinator.endSession(); bad.drainDisk();
                check(!Files.exists(allocated.toPath().resolve("SESSION_DONE")), "failed metadata directory stays unmarked");
                check(bad.coordinator.snapshot().error.contains(allocated.getAbsolutePath()), "failed close retains allocated path");
            }
        }
    }
    static void prerequisitesAndFailureOrdering() throws Exception {
        Harness delayed = new Harness();
        delayed.coordinator.requestManual("continuous", 0, ""); delayed.advance(10000);
        check(delayed.coordinator.snapshot().state == CaptureCoordinator.State.ARMING, "header and metadata must persist before RECORDING");
        delayed.drainDisk(); check(delayed.coordinator.snapshot().state == CaptureCoordinator.State.ARMING, "disk completion cannot start sampling before UI start cue");
        delayed.packet(1, 99, 5); delayed.drainUi();
        check(delayed.coordinator.snapshot().state == CaptureCoordinator.State.RECORDING, "UI cue activates recording");
        delayed.packet(1, 0, 2); delayed.coordinator.stopCapture(); delayed.drainDisk();
        check(Files.readAllLines(delayed.csv("continuous")).size() == 3, "samples before actual cue were ignored");
        Harness cue = new Harness(); cue.coordinator.startGuide(List.of("raw_up"), ""); cue.advance(1200);
        cue.now += 5000; cue.drainDisk(); cue.packet(1, 99, 400);
        check(cue.coordinator.snapshot().state == CaptureCoordinator.State.ARMING, "late disk after prompt with stalled UI stays ARMING");
        cue.drainUi(); check(cue.cues.contains(CaptureCoordinator.Cue.STILL), "actual activation delivers STILL");
        cue.advance(999); check(!cue.cues.contains(CaptureCoordinator.Cue.GO), "GO never precedes full preroll after actual cue");
        cue.advance(1); check(cue.cues.contains(CaptureCoordinator.Cue.GO), "GO exactly one second after actual start");
        for (String fail : List.of("csv", "sidecar", "summary", "marker")) {
            CaptureCoordinator.Storage storage = new CaptureCoordinator.Storage() {
                @Override void writeNew(File file, String data) throws IOException {
                    if ((fail.equals("csv") && file.getName().endsWith(".csv"))
                            || (fail.equals("sidecar") && file.getName().endsWith(".json"))) throw new IOException("injected " + fail);
                    super.writeNew(file, data);
                }
                @Override void createMarker(File file, Runnable created) throws IOException {
                    if (fail.equals("marker")) throw new IOException("injected marker"); super.createMarker(file, created);
                }
                @Override void append(File file, String data) throws IOException {
                    if (fail.equals("summary") && file.getName().equals("session_info.txt")) throw new IOException("injected summary");
                    super.append(file, data);
                }
            };
            Harness bad = new Harness(storage);
            bad.coordinator.startGuide(List.of("raw_up", "raw_down"), ""); bad.drainDisk(); bad.advance(1200);
            File dir = bad.directory(); bad.packet(1, 0, 400); bad.drainDisk();
            if (fail.equals("csv") || fail.equals("sidecar")) {
                check(bad.coordinator.snapshot().guidePaused, "write error pauses guide: " + fail);
                check(bad.coordinator.snapshot().guideIndex == 0, "write error keeps same trial: " + fail);
                check(bad.coordinator.snapshot().savedCounts.isEmpty(), "write error has no count: " + fail);
                check(bad.coordinator.snapshot().error.contains(new File(dir, "raw_up.1.csv").getAbsolutePath()),
                        "pathless terminal writer failure preserves absolute capture path: " + fail);
            }
            bad.coordinator.close(); bad.drainDisk();
            if (fail.equals("summary") || fail.equals("marker")) {
                check(!Files.exists(dir.toPath().resolve("SESSION_DONE")), "close failure has no marker: " + fail);
                check(bad.coordinator.snapshot().error.contains("세션 종료 저장 실패"), "close failure retained after UI invalidation");
                check(bad.coordinator.snapshot().error.contains(dir.getAbsolutePath()), "close failure keeps explicit session path");
            }
        }
        final int[] appends = {0};
        Harness header = new Harness(new CaptureCoordinator.Storage() {
            @Override void createHeader(File file, Runnable created) throws IOException { throw new IOException("header failed"); }
            @Override void append(File file, String data) throws IOException { appends[0]++; super.append(file, data); }
        });
        header.coordinator.requestManual("continuous", 0, ""); header.drainDisk(); header.advance(5000);
        header.packet(1, 0, 2000); header.coordinator.stopCapture(); header.drainDisk();
        check(appends[0] == 0, "header failure never permits append");
    }
    static void staleTimersAndFiniteBoundaries() throws Exception {
        Harness h = new Harness(); h.record("raw_up", 400); h.packet(1, 0, 400); h.drainDisk();
        h.record("idle", 1000); h.advance(5300); // First capture timeout at 7700; current timeout is 14900.
        check(h.coordinator.snapshot().state == CaptureCoordinator.State.RECORDING, "actual old timeout leaves new capture intact");
        h.coordinator.onStreamBoundary(1, "connection_lost"); h.drainDisk();
        check(!Files.exists(h.csv("idle")), "incomplete finite capture produces no success CSV");
        String finiteMeta = Files.readString(h.csv("idle").resolveSibling("idle.1.csv.capture.json"));
        check(finiteMeta.contains("\"end_status\": \"aborted\"") && finiteMeta.contains("\"end_reason\": \"connection_lost\""), "finite disconnect exact status/reason");
        Harness overlap = new Harness(); overlap.record("idle", 1000); overlap.packet(1, 100, 5); overlap.packet(1, 103, 5); overlap.drainDisk();
        check(!Files.exists(overlap.csv("idle")), "partial overlap fails finite capture");
        String overlapMeta = Files.readString(overlap.csv("idle").resolveSibling("idle.1.csv.capture.json"));
        check(overlapMeta.contains("\"end_status\": \"aborted\"") && overlapMeta.contains("\"end_reason\": \"slot_discontinuity\""), "finite partial overlap exact status/reason");
        Harness closing = new Harness(); closing.record("continuous", 0); closing.packet(1, 10, 5); File dir = closing.directory();
        closing.coordinator.endSession();
        check(!closing.coordinator.requestManual("idle", 1000, ""), "CLOSING rejects captures");
        closing.drainDisk(); int count = closing.disk.size(); closing.advance(100000); closing.coordinator.onStreamReady(2);
        check(closing.disk.size() == count, "DONE has no future writes from stale callbacks");
        check(Files.readAllLines(dir.toPath().resolve("continuous.1.csv")).get(1).startsWith("0,"), "capture timestamp starts zero");
        Harness lost = new Harness(); lost.record("continuous", 0); lost.packet(1, 20, 3);
        lost.coordinator.onStreamBoundary(1, "connection_lost"); lost.drainDisk();
        String lostMeta = Files.readString(lost.csv("continuous").resolveSibling("continuous.1.csv.capture.json"));
        check(lostMeta.contains("\"end_status\": \"stopped\"") && lostMeta.contains("\"end_reason\": \"connection_lost\""), "continuous disconnect exact status/reason");
    }
    static void epochAndSlotContracts() throws Exception {
        BleConnectionEpoch epoch = new BleConnectionEpoch(); Object oldGatt = new Object(), newGatt = new Object();
        long first = epoch.begin(); epoch.attach(first, oldGatt);
        check(epoch.current(first, oldGatt), "current GATT accepted");
        check(epoch.end(first), "stop delivers boundary without disconnect callback");
        check(!epoch.end(first), "disconnect after stop cannot deliver duplicate boundary");
        long second = epoch.begin(); epoch.attach(second, newGatt);
        check(!epoch.current(first, oldGatt), "stale GATT callback rejected");
        check(!epoch.end(first) && epoch.current(second, newGatt), "stale disconnect cannot close new GATT");
        SlotContinuity slots = new SlotContinuity();
        check(slots.accept(100000, 5) == SlotContinuity.Kind.CONTIGUOUS, "initial high slot valid");
        check(slots.accept(100000, 5) == SlotContinuity.Kind.DUPLICATE, "exact previous duplicate");
        check(slots.accept(100006, 5) == SlotContinuity.Kind.FORWARD_GAP, "forward gap distinct");
        check(slots.accept(0, 5) == SlotContinuity.Kind.DISCONTINUITY, "reset is discontinuity");
        check(new SlotContinuity().accept(0, 5) == SlotContinuity.Kind.CONTIGUOUS, "new stream accepts zero immediately");
        Path root = Files.createTempDirectory("session-errors-"); Path file = root.resolve("file"); Files.writeString(file, "unchanged");
        try { SessionDirectory.create(file.toFile(), 0); throw new AssertionError("mkdir must fail"); }
        catch (IOException expected) { check(Files.readString(file).equals("unchanged"), "noncollision mkdir error aborts without touching old file"); }
    }
    static void staleCueAndRedo() throws Exception {
        Harness h = new Harness();
        h.coordinator.startGuide(List.of("raw_up", "raw_down"), ""); h.drainDisk(); h.advance(1200);
        int previousGo = (int) h.cues.stream().filter(c -> c == CaptureCoordinator.Cue.GO).count();
        h.now += 1000;
        // Let the GO scheduling callback run, but hold the cue it posts to the UI queue.
        Task timer = h.ui.stream().filter(t -> t.at == h.now).findFirst().orElseThrow();
        h.ui.remove(timer); timer.run.run();
        h.coordinator.onStreamBoundary(1, "connection_lost"); h.drainUi(); h.drainDisk();
        check(h.cues.stream().filter(c -> c == CaptureCoordinator.Cue.GO).count() == previousGo, "queued GO invalidated at boundary");
        h.coordinator.onStreamReady(2); h.drainUi(); h.drainDisk(); h.advance(1200);
        h.packet(2, 0, 400); h.drainDisk(); File saved = h.coordinator.snapshot().lastSavedFile;
        check(h.coordinator.redoLast(), "redo accepted during rest");
        h.advance(10000); check(h.coordinator.snapshot().state == CaptureCoordinator.State.FINALIZING, "redo disk job remains busy");
        h.drainDisk(); check(!saved.exists(), "redo removes CSV");
        check(Files.exists(saved.toPath().resolveSibling(saved.getName() + ".capture.json")), "redo retains original timing sidecar");
        check(h.coordinator.snapshot().savedCounts.isEmpty(), "redo decrements durable count");
        h.advance(1000); h.drainDisk(); h.advance(1200);
        check(h.coordinator.snapshot().label.equals("raw_up"), "redo repeats same direction instead of stale next trial");
    }
    static void canceledHeaderOwnership() throws Exception {
        Harness h = new Harness(); h.coordinator.requestManual("continuous", 0, ""); h.drainDisk();
        File dir = h.directory(); Path first = dir.toPath().resolve("continuous.1.csv");
        check(Files.exists(first), "exclusive header prepared while UI activation held");
        h.coordinator.stopCapture();
        check(h.coordinator.requestManual("continuous", 0, ""), "immediate restart reserves a different file");
        h.drainDisk(); h.drainUi(); Path second = dir.toPath().resolve("continuous.2.csv");
        check(!Files.exists(first) && Files.exists(second), "cancel cleanup removes only its owned header");
        h.packet(1, 0, 2); h.coordinator.endSession(); h.drainDisk();
        check(Files.readAllLines(second).size() == 3 && Files.exists(dir.toPath().resolve("SESSION_DONE")), "cleanup precedes close and does not remove newer data");
        Harness preexisting = new Harness(new CaptureCoordinator.Storage() {
            @Override void createHeader(File file, Runnable created) throws IOException {
                Files.writeString(file.toPath(), "sentinel", StandardOpenOption.CREATE_NEW);
                super.createHeader(file, created);
            }
        });
        preexisting.coordinator.requestManual("continuous", 0, ""); preexisting.drainDisk(); preexisting.coordinator.stopCapture(); preexisting.drainDisk();
        check(Files.readString(preexisting.csv("continuous")).equals("sentinel"), "failed CREATE_NEW never grants cleanup ownership over existing file");
    }
    static void partialMetadataRequiresFreshSession() throws Exception {
        final boolean[] failOnce = {true};
        Harness h = new Harness(new CaptureCoordinator.Storage() {
            @Override void writeNew(File file, String data) throws IOException {
                if (file.getName().equals("session_info.txt") && failOnce[0]) {
                    failOnce[0] = false; super.writeNew(file, "partial metadata");
                    throw new IOException("injected failure after creating file");
                }
                super.writeNew(file, data);
            }
        });
        h.coordinator.requestManual("idle", 1000, ""); h.drainDisk(); h.advance(1200); File failed = h.directory();
        check(h.coordinator.snapshot().canEndSession && !h.coordinator.snapshot().canStartManual
                && !h.coordinator.snapshot().canStartGuide, "partial metadata requires end-session action");
        check(!h.coordinator.requestManual("idle", 1000, ""), "partial metadata folder never retried");
        check(h.coordinator.snapshot().error.contains("세션 종료 후 새로 시작"), "partial metadata failure tells user recovery action");
        h.coordinator.endSession(); h.drainDisk(); h.record("idle", 1000);
        check(!h.directory().equals(failed), "recovery uses a freshly allocated session");
        check(Files.readString(failed.toPath().resolve("session_info.txt")).equals("partial metadata"), "partial metadata preserved without overwrite");
        check(!Files.exists(failed.toPath().resolve("SESSION_DONE")), "partial session never marked done");
    }
    static void failedMarkerCreationOwnership() throws Exception {
        for (String phase : List.of("write", "force", "close", "delete")) {
            Harness h = new Harness(new CaptureCoordinator.Storage() {
                @Override void createMarker(File file, Runnable created) throws IOException {
                    // Use the real CREATE_NEW ownership path, then inject the later I/O failure.
                    super.createMarker(file, created);
                    throw new IOException("injected marker " + phase + " failure");
                }
                @Override void delete(File file) throws IOException {
                    if (phase.equals("delete") && file.getName().equals("SESSION_DONE")) throw new IOException("injected delete failure");
                    super.delete(file);
                }
            });
            h.record("idle", 1000); h.packet(1, 0, 1000); h.drainDisk(); File dir = h.directory();
            h.coordinator.endSession(); h.drainDisk(); Path marker = dir.toPath().resolve("SESSION_DONE");
            check(h.coordinator.snapshot().error.contains("세션 종료 저장 실패"), "post-create marker failure reported: " + phase);
            if (phase.equals("delete")) {
                check(Files.exists(marker), "injected marker cleanup failure leaves known artifact");
                check(h.coordinator.snapshot().error.contains("잔존 SESSION_DONE 마커 경고")
                        && h.coordinator.snapshot().error.contains(marker.toFile().getAbsolutePath()), "cleanup failure warns with exact residual marker path");
            } else check(!Files.exists(marker), "failed marker revoked after " + phase);
            check(Files.readAllLines(dir.toPath().resolve("idle.1.csv")).size() == 1001, "marker cleanup preserves captured CSV: " + phase);
        }
        final int[] deletes = {0};
        Harness existing = new Harness(new CaptureCoordinator.Storage() {
            @Override void createMarker(File file, Runnable created) throws IOException {
                Files.writeString(file.toPath(), "preexisting marker", StandardOpenOption.CREATE_NEW);
                super.createMarker(file, created);
            }
            @Override void delete(File file) throws IOException { deletes[0]++; super.delete(file); }
        });
        existing.record("idle", 1000); File dir = existing.directory(); existing.coordinator.endSession(); existing.drainDisk();
        check(Files.readString(dir.toPath().resolve("SESSION_DONE")).equals("preexisting marker"), "CREATE_NEW rejection preserves existing marker bytes");
        check(deletes[0] == 0, "CREATE_NEW rejection never acquires marker deletion ownership");
        check(existing.coordinator.snapshot().error.contains("세션 종료 저장 실패"), "existing marker rejection reports failed close");
    }
}
