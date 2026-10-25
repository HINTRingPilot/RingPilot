"""Read-only original v2 event tracing; truth is used only after replay.

Raw truth pairs require the second adjacent decision inside [e, e+500]. A blocked
pair means the second decision was actually locked before processing it.
Diagnostic flags overlap and must never be summed as exclusive categories.
"""
import numpy as np
import v2


def trace_events(times, scores):
    """Return original events and causal per-decision state, reset per call.

Scores must have shape (N, 5), times must be finite strictly increasing
integer milliseconds. Scores preserve their original dtype and arithmetic.
"""
    times, scores = np.asarray(times), np.asarray(scores)
    if times.ndim != 1 or scores.ndim != 2 or scores.shape != (len(times), 5):
        raise ValueError('expected times (N,) and scores (N, 5)')
    if not np.isfinite(times).all() or not np.isfinite(scores).all():
        raise ValueError('times and scores must be finite')
    if np.any(times != np.floor(times)) or np.any(np.diff(times) <= 0):
        raise ValueError('times must be strictly increasing integer milliseconds')
    events, decisions = [], []
    locked, candidate, count, none_count = False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        margin = np.sort(p)[-1] - np.sort(p)[-2]
        score_pass = bool(p[top] >= .8)
        margin_pass = bool(margin >= .2)
        eligible = bool(top != 0 and score_pass and margin_pass)
        d = dict(timestamp_ms=int(t), top_class=top, top_score=float(p[top]),
                 margin=float(margin), score_pass=score_pass, margin_pass=margin_pass,
                 eligible=eligible, locked_before=locked,
                 candidate_before=candidate, direction_count_before=count,
                 none_count_before=none_count, emitted=False, rearmed=False)
        if locked:
            none_count = none_count + 1 if top == 0 and p[0] >= .8 else 0
            if none_count >= 2:
                locked, candidate, count, none_count = False, None, 0, 0
                d['rearmed'] = True
        elif eligible:
            count = count + 1 if top == candidate else 1
            candidate = top
            if count >= 2:
                events.append(dict(timestamp_ms=int(t), class_index=top, score=float(p[top])))
                locked, candidate, count, none_count = True, None, 0, 0
                d['emitted'] = True
        else:
            candidate, count = None, 0
        d.update(locked_after=locked, candidate_after=candidate,
                 direction_count_after=count, none_count_after=none_count)
        decisions.append(d)
    return dict(events=events, decisions=decisions)


def diagnose_source(record, times, scores):
    """Post-hoc original scoring plus overlapping failure-path evidence.

Background records have category None (excluded from direction-source totals).
Prior events/rearms are listed for every raw truth pair, including successful
ones; a blocked pair is evidence of suppression, not a counterfactual gain.
"""
    replay = trace_events(times, scores)
    counts, delays, events = v2.classify_events(record, replay['events'])
    ds = replay['decisions']
    e = record['completion_ms']
    truth = v2.CLASSES.index(record['direction']) if e is not None else None
    pairs = []
    rearms = [d['timestamp_ms'] for d in ds if d['rearmed']]
    for previous, current in zip(ds, ds[1:]):
        if (e is not None and e <= current['timestamp_ms'] <= e + v2.MATCH_MS
                and previous['eligible'] and current['eligible']
                and previous['top_class'] == current['top_class'] == truth):
            t = current['timestamp_ms']
            prior = [event for event in replay['events'] if event['timestamp_ms'] < t]
            pairs.append(dict(first_timestamp_ms=previous['timestamp_ms'], timestamp_ms=t,
                              blocked_locked=current['locked_before'],
                              prior_event=dict(prior[-1]) if prior else None,
                              prior_rearm_times_ms=[r for r in rearms if r < t]))
    early_match = sum(ev['kind'] == 'early' and ev['class_index'] == truth for ev in events)
    early_mismatch = sum(ev['kind'] == 'early' and ev['class_index'] != truth for ev in events)
    category = ('correct' if counts['correct'] else 'no_emit' if not events
                else 'emitted_without_correct') if e is not None else None
    # Threshold/margin evidence is independent, not a forced single cause.
    direction = [d for d in ds if d['top_class'] != 0]
    return dict(counts=counts, delays_ms=delays, events=events, category=category,
                flags=dict(raw_truth_direction_pair=bool(pairs),
                           truth_pair_blocked_locked=any(p['blocked_locked'] for p in pairs),
                           early_direction_match=bool(early_match), early_direction_mismatch=bool(early_mismatch),
                           direction_score_below_threshold=any(not d['score_pass'] for d in direction),
                           direction_margin_below_threshold=any(not d['margin_pass'] for d in direction),
                           eligible_direction_without_emit=any(d['eligible'] and not d['locked_before'] and not d['emitted'] for d in ds)),
                raw_truth_pairs=pairs, rearm_times_ms=rearms,
                early_direction_match_count=early_match, early_direction_mismatch_count=early_mismatch)
