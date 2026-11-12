package com.hintringpilot.ringpilot.dev;

import java.io.File;
import java.io.IOException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Atomic allocation; an existing session (including its DONE marker) is never reused. */
final class SessionDirectory {
    static File create(File root, long wallMillis) throws IOException {
        Files.createDirectories(root.toPath());
        String base = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date(wallMillis));
        for (int suffix = 0; suffix <= 1000; suffix++) {
            File candidate = new File(root, base + (suffix == 0 ? "" : String.format(Locale.US, "-%03d", suffix)));
            try {
                Files.createDirectory(candidate.toPath());
                return candidate;
            } catch (FileAlreadyExistsException collision) {
                // Only a collision is retryable. Permission and storage failures must be reported.
            }
        }
        throw new IOException("Session name collision limit reached: " + base);
    }
}
