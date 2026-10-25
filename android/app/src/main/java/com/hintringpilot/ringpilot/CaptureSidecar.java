package com.hintringpilot.ringpilot;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;

/** Capture timing facts only. Callback arrival is not physical sensor acquisition time. */
final class CaptureSidecar {
    private final String csv, session, activity;
    private final int target;
    private final long start;
    private Long first, arrival, last;
    private int count;

    CaptureSidecar(String csv, int target, long start, String session, String activity) {
        this.csv = csv; this.target = target; this.start = start;
        this.session = session; this.activity = activity;
    }

    void accept(long slot, long callbackArrival) {
        if (first == null) { first = slot; arrival = callbackArrival; }
        last = slot;
        count++;
    }

    String json(long end, String status, String reason, boolean csvExists, boolean writeFailed) {
        return "{\n"
            + "  \"schema_version\": 1,\n"
            + "  \"intended_csv\": " + quote(csv) + ",\n"
            + "  \"source_csv\": " + (csvExists ? quote(csv) : "null") + ",\n"
            + "  \"csv_exists_at_finalization\": " + csvExists + ",\n"
            + "  \"csv_write_failed\": " + writeFailed + ",\n"
            + "  \"mode\": " + quote(target > 0 ? "finite" : "continuous") + ",\n"
            + "  \"target_sample_count\": " + (target > 0 ? target : "null") + ",\n"
            + "  \"sample_count\": " + count + ",\n"
            + "  \"sample_interval_ms\": 10,\n"
            + "  \"first_board_slot\": " + first + ",\n"
            + "  \"last_board_slot\": " + last + ",\n"
            + "  \"start_call_elapsed_realtime_ms\": " + start + ",\n"
            + "  \"first_callback_arrival_elapsed_realtime_ms\": " + arrival + ",\n"
            + "  \"end_elapsed_realtime_ms\": " + end + ",\n"
            + "  \"end_status\": " + quote(status) + ",\n"
            + "  \"end_reason\": " + quote(reason) + ",\n"
            + "  \"session_directory\": " + quote(session) + ",\n"
            + "  \"activity_instance_id\": " + quote(activity) + ",\n"
            + "  \"board_boot_id\": null,\n"
            + "  \"board_restart_observed\": null,\n"
            + "  \"firmware_commit\": null,\n"
            + "  \"app_commit\": null,\n"
            + "  \"negotiated_mtu\": null,\n"
            + "  \"timing_semantics\": \"elapsedRealtime is phone boot-relative milliseconds; arrival is listener entry for first accepted sample packet, not physical sample time; slots are board-relative and do not establish video synchronization or board boot identity\"\n"
            + "}\n";
    }

    static void writeExclusive(File file, String json) throws IOException {
        Files.write(file.toPath(), json.getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
    }

    private static String quote(String value) {
        if (value == null) return "null";
        StringBuilder out = new StringBuilder("\"");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c < 32) {
                if (c == '\n') out.append("\\n");
                else out.append(String.format(java.util.Locale.US, "\\u%04x", (int)c));
            } else out.append(c);
        }
        return out.append('"').toString();
    }
}
