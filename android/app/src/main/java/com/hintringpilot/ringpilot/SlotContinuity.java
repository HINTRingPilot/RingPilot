package com.hintringpilot.ringpilot;

/** Packet order within one capture and stream generation. It does not infer board boot identity. */
final class SlotContinuity {
    enum Kind { CONTIGUOUS, FORWARD_GAP, DUPLICATE, DISCONTINUITY }
    private long expected = -1, previousFirst = -1;
    private int previousCount;

    Kind accept(long first, int count) {
        if (count <= 0 || first < 0) return Kind.DISCONTINUITY;
        if (first == previousFirst && count == previousCount) return Kind.DUPLICATE;
        Kind kind = expected < 0 || first == expected ? Kind.CONTIGUOUS
                : first > expected ? Kind.FORWARD_GAP : Kind.DISCONTINUITY;
        if (kind != Kind.DISCONTINUITY) {
            previousFirst = first; previousCount = count; expected = first + count;
        }
        return kind;
    }

    long expectedSlot() { return expected; }
}
