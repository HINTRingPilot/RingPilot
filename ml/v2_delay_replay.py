"""Fixed-delay replay of unchanged v2 candidates, without truth inputs.

Common mode uses the same original candidate-time cutoff for every delay.
Full mode preserves reservations that have not matured by observation end.
This module writes no files and does not change the original gate or lock.
"""
import math
from numbers import Real

import numpy as np
import v2

SUPPORTED_DELAYS_MS = (0, 50, 100, 150, 200)


def _time(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite nonnegative time')
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be a finite nonnegative time')
    return value.item() if isinstance(value, np.generic) else value


def _policy(delay_ms, max_delay_ms):
    delay_ms = _time(delay_ms, 'delay_ms')
    max_delay_ms = _time(max_delay_ms, 'max_delay_ms')
    if delay_ms not in SUPPORTED_DELAYS_MS:
        raise ValueError('delay_ms must be one of 0, 50, 100, 150, 200')
    if max_delay_ms != 200:
        raise ValueError('the fixed comparison maximum is 200 ms')
    return delay_ms, max_delay_ms


def schedule_events(base_events, delay_ms, last_time_ms, common=True, max_delay_ms=200):
    """Shift original candidates; pending retains original and due timestamps.

    Emitted/excluded events keep the original event schema (only emitted time
    shifts). Pending timestamp_ms remains the original candidate time, with
    explicit original_timestamp_ms and due_timestamp_ms fields added.
    """
    delay_ms, max_delay_ms = _policy(delay_ms, max_delay_ms)
    last_time_ms = _time(last_time_ms, 'last_time_ms')
    cutoff = last_time_ms - max_delay_ms if common else last_time_ms
    emitted, pending, excluded = [], [], []
    previous = None
    for original in base_events:
        candidate = dict(original)
        t = _time(candidate['timestamp_ms'], 'event timestamp_ms')
        if previous is not None and t <= previous:
            raise ValueError('event timestamps must be strictly increasing')
        if t > last_time_ms:
            raise ValueError('candidate occurs beyond observation end')
        previous = t
        if common and t > cutoff:
            excluded.append(candidate)
            continue
        due = t + delay_ms
        if due > last_time_ms:
            pending.append(dict(candidate, original_timestamp_ms=t, due_timestamp_ms=due))
        else:
            candidate['timestamp_ms'] = due
            emitted.append(candidate)
    return {'events': emitted, 'pending': pending, 'excluded': excluded, 'cutoff_ms': cutoff}


def issue_delayed(times, scores, delay_ms, common=True, max_delay_ms=200):
    """Generate candidates with protected v2.issue_events, then schedule them."""
    _policy(delay_ms, max_delay_ms)
    times = np.asarray(times)
    # Preserve the original array dtype: NumPy scalar threshold arithmetic can
    # change at .8/.2 when float16/float32 values are widened before v2 runs.
    scores = np.asarray(scores)
    if times.ndim != 1 or not len(times):
        raise ValueError('times must be a nonempty vector')
    validated = [_time(t, 'decision time') for t in times]
    if any(b <= a for a, b in zip(validated, validated[1:])):
        raise ValueError('decision times must be strictly increasing')
    if any(int(t) != t for t in validated):
        raise ValueError('decision times must be integer milliseconds, as in v2')
    if scores.shape != (len(times), len(v2.CLASSES)) or not np.isfinite(scores).all():
        raise ValueError('scores must be a finite (number of times, 5) matrix')
    return schedule_events(v2.issue_events(times, scores), delay_ms, validated[-1],
                           common=common, max_delay_ms=max_delay_ms)


def full_exposure_ms(first_time_ms, last_time_ms):
    """Original 100 Hz endpoint convention: last - first + 10 ms."""
    first = _time(first_time_ms, 'first_time_ms')
    last = _time(last_time_ms, 'last_time_ms')
    if last < first:
        raise ValueError('observation end precedes first decision')
    return last - first + 10


def common_exposure_ms(first_time_ms, last_time_ms, max_delay_ms=200):
    """Exposure on the common candidate domain, with the same 10 ms endpoint."""
    _policy(0, max_delay_ms)
    full_exposure_ms(first_time_ms, last_time_ms)
    cutoff = last_time_ms - max_delay_ms
    return max(0, cutoff - first_time_ms + 10) if cutoff >= first_time_ms else 0
