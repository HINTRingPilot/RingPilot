import unittest
import numpy as np
import v2
import v2_event_trace as trace


def scores(classes):
    return np.array([[.9 if j == c else .025 for j in range(5)] for c in classes])


class EventTraceTests(unittest.TestCase):
    def test_lock_rearm_and_raw_blocked_pair(self):
        times = np.arange(8) * 50
        result = trace.trace_events(times, scores([1, 1, 1, 1, 0, 0, 2, 2]))
        self.assertEqual([e['timestamp_ms'] for e in result['events']], [50, 350])
        self.assertTrue(result['decisions'][3]['locked_before'])
        self.assertTrue(result['decisions'][5]['rearmed'])
        d = trace.diagnose_source({'direction': 'UP', 'completion_ms': 100}, times,
                                  scores([1, 1, 1, 1, 0, 0, 2, 2]))
        self.assertEqual(d['category'], 'emitted_without_correct')
        self.assertTrue(d['flags']['truth_pair_blocked_locked'])
        self.assertEqual(d['early_direction_match_count'], 1)

    def test_direction_change_reset_and_no_emit(self):
        p = scores([1, 2, 0, 1])
        r = trace.trace_events([0, 50, 100, 150], p)
        self.assertEqual(r['events'], [])
        self.assertEqual([d['direction_count_after'] for d in r['decisions']], [1, 1, 0, 1])
        self.assertEqual(trace.trace_events([0], scores([1]))['decisions'][0]['locked_before'], False)
        self.assertEqual(trace.diagnose_source({'direction': 'UP', 'completion_ms': 0}, [0], scores([1]))['category'], 'no_emit')

    def test_random_equality_and_prefix_causality(self):
        rng = np.random.default_rng(101)
        p = np.vstack([scores(rng.integers(0, 5, 300)), rng.dirichlet(np.ones(5), 100)])
        t = np.arange(len(p)) * 50
        r = trace.trace_events(t, p)
        self.assertEqual(r['events'], v2.issue_events(t, p))
        for n in (0, 1, 15, 199, 399):
            prefix = trace.trace_events(t[:n], p[:n])
            self.assertEqual(prefix['decisions'], r['decisions'][:n])
            self.assertEqual(prefix['events'], [e for e in r['events'] if e['timestamp_ms'] < n * 50])

    def test_float16_threshold_evidence_matches_original_gate(self):
        p = np.array([[.05, .8, .05, .05, .05]] * 2, dtype=np.float16)
        d = trace.diagnose_source({"direction": "UP", "completion_ms": 0}, [0, 50], p)
        self.assertEqual(len(d["events"]), 1)
        self.assertFalse(d["flags"]["direction_score_below_threshold"])
        self.assertFalse(d["flags"]["direction_margin_below_threshold"])

    def test_invalid_inputs(self):
        for t, p in [([0], np.ones((2, 5))), ([0], np.ones((1, 4))),
                     ([50, 0], scores([1, 1])), ([0, 0], scores([1, 1])),
                     ([float('nan')], scores([1])), ([0], np.full((1, 5), np.inf))]:
            with self.subTest(times=t):
                with self.assertRaises(ValueError): trace.trace_events(t, p)

    def test_pair_can_straddle_completion_boundary(self):
        d = trace.diagnose_source({"direction": "UP", "completion_ms": 125},
                                  [0, 50, 100, 150], scores([1, 1, 1, 1]))
        self.assertTrue(d["flags"]["truth_pair_blocked_locked"])
        self.assertEqual(d["raw_truth_pairs"][0]["first_timestamp_ms"], 100)

    def test_original_scoring_and_boundaries(self):
        record = {'direction': 'UP', 'completion_ms': 50}
        t, p = np.arange(8) * 50, scores([1, 1, 0, 0, 2, 2, 1, 1])
        d = trace.diagnose_source(record, t, p)
        counts, delays, events = v2.classify_events(record, v2.issue_events(t, p))
        self.assertEqual((d['counts'], d['delays_ms'], d['events']), (counts, delays, events))
        self.assertEqual(d['category'], 'correct')
        self.assertEqual(d['rearm_times_ms'], [150])

if __name__ == '__main__': unittest.main()
