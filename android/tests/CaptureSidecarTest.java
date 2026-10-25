package com.hintringpilot.ringpilot;
import java.nio.file.*;
public final class CaptureSidecarTest {
  static void check(boolean yes) { if (!yes) throw new AssertionError(); }
  public static void main(String[] args) throws Exception {
    CaptureSidecar c = new CaptureSidecar("raw_up.1.csv", 400, 123, "session", "activity");
    String empty = c.json(130, "aborted", "cancel\n\"x", false, false);
    check(empty.contains("\"first_board_slot\": null"));
    check(empty.contains("\"source_csv\": null"));
    check(empty.contains("\"end_status\": \"aborted\""));
    check(empty.contains("\"sample_count\": 0"));
    check(empty.contains("\"start_call_elapsed_realtime_ms\": 123"));
    check(empty.contains("\"board_boot_id\": null"));
    check(empty.contains("\"app_commit\": null"));
    check(empty.contains("\"negotiated_mtu\": null"));
    check(empty.contains("cancel\\n\\\"x"));
    c.accept(4294967290L, 150); c.accept(4294967291L, 180);
    String saved = c.json(200, "completed", null, true, false);
    check(saved.contains("\"first_board_slot\": 4294967290"));
    check(saved.contains("\"first_callback_arrival_elapsed_realtime_ms\": 150"));
    check(saved.contains("\"sample_count\": 2"));
    check(saved.contains("\"last_board_slot\": 4294967291"));
    check(saved.contains("\"sample_interval_ms\": 10"));
    check(saved.contains("\"mode\": \"finite\""));
    check(saved.contains("\"csv_write_failed\": false"));
    check(saved.contains("\"source_csv\": \"raw_up.1.csv\""));
    check(saved.contains("\"end_elapsed_realtime_ms\": 200"));
    String failed = c.json(210, "csv_write_failed", "write failure", false, true);
    check(failed.contains("\"csv_write_failed\": true"));
    check(failed.contains("\"source_csv\": null"));
    if (args.length > 0) Files.writeString(Path.of(args[0]), empty);
    CaptureSidecar continuous = new CaptureSidecar("continuous.1.csv", 0, 5, "s", "a");
    check(continuous.json(10, "stopped", null, true, true).contains("\"mode\": \"continuous\""));
    Path dir = Files.createTempDirectory("capture-sidecar-test");
    Path file = dir.resolve("test.json");
    CaptureSidecar.writeExclusive(file.toFile(), saved);
    try { CaptureSidecar.writeExclusive(file.toFile(), "overwrite"); throw new AssertionError(); }
    catch (FileAlreadyExistsException expected) { }
    check(Files.readString(file).equals(saved));
    Files.delete(file); Files.delete(dir);
    System.out.println("CaptureSidecar tests passed");
  }
}
