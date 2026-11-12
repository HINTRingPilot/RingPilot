package com.hintringpilot.ringpilot;

import java.util.concurrent.atomic.AtomicLong;

/** Used under ImuBleClient's lifecycle lock; identities are never reused between attempts. */
final class BleConnectionEpoch {
    private static final AtomicLong SERIAL = new AtomicLong();
    private long generation;
    private Object identity;
    private boolean ended = true;

    long begin() { generation = SERIAL.incrementAndGet(); identity = null; ended = false; return generation; }
    void attach(long attempt, Object identity) { if (attempt == generation && !ended) this.identity = identity; }
    boolean current(long attempt, Object identity) {
        return !ended && attempt == generation && identity != null && this.identity == identity;
    }
    boolean end(long attempt) {
        if (ended || attempt != generation) return false;
        ended = true; identity = null; return true;
    }
}
