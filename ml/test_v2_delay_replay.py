"""Pure reservation scheduling: no truth labels or persisted outputs."""
import inspect
import unittest

import numpy as np
import v2
import v2_delay_replay as replay


def event(t, cls=1):
    return {"timestamp_ms": t, "class_index": cls, "score": .9}


class DelayReplayTests(unittest.TestCase):
    def test_full_zero_identity_and_no_mutation(self):
        base = [event(100), event(500, 2)]
        self.assertEqual(replay.schedule_events(base, 0, 500, common=False)["events"], base)
        replay.schedule_events(base, 200, 500, common=False)
        self.assertEqual(base, [event(100), event(500, 2)])

    def test_zero_delay_preserves_native_threshold_arithmetic(self):
        times = np.array([0, 50])
        scores = np.array([[0, .8, 0, 0, 0]] * 2, dtype=np.float16)
        base = v2.issue_events(times, scores)
        self.assertEqual(len(base), 1)
        self.assertEqual(replay.issue_delayed(times, scores, 0, common=False)['events'], base)

    def test_common_boundary_and_same_candidates_all_delays(self):
        base = [event(100), event(300, 2), event(350, 3)]
        for delay in (0, 50, 100, 150, 200):
            with self.subTest(delay=delay):
                out = replay.schedule_events(base, delay, 500)
                self.assertEqual(out["cutoff_ms"], 300)
                self.assertEqual(out["events"], [event(100+delay), event(300+delay, 2)])
                self.assertEqual(out["excluded"], [event(350, 3)])
                self.assertEqual(out["pending"], [])

    def test_full_boundary_keeps_late_reservations(self):
        out = replay.schedule_events([event(300), event(350, 2)], 200, 500, common=False)
        self.assertEqual(out["events"], [event(500)])
        self.assertEqual(out["excluded"], [])
        self.assertEqual(out["pending"], [dict(event(350, 2), original_timestamp_ms=350, due_timestamp_ms=550)])

    def test_delayed_uses_original_gate_lock_and_rearm(self):
        times = np.arange(0, 500, 50)
        scores = np.eye(5)[[1, 1, 2, 2, 0, 0, 2, 2, 3, 3]]
        base = v2.issue_events(times, scores)
        self.assertEqual([e["timestamp_ms"] for e in base], [50, 350])
        for delay in (0, 50, 100, 150, 200):
            self.assertEqual(replay.issue_delayed(times, scores, delay, common=False),
                             replay.schedule_events(base, delay, 450, common=False))

    def test_delay_cannot_revive_no_emission(self):
        for delay in (0, 50, 100, 150, 200):
            out = replay.issue_delayed([0, 50], [[.6, .4, 0, 0, 0]]*2, delay)
            self.assertEqual(out["events"] + out["pending"], [])

    def test_full_prefix_causal(self):
        times = np.arange(0, 500, 50)
        scores = np.eye(5)[[1, 1, 0, 0, 2, 2, 0, 0, 3, 3]]
        full = replay.issue_delayed(times, scores, 150, common=False)
        for n in range(1, len(times)+1):
            prefix = replay.issue_delayed(times[:n], scores[:n], 150, common=False)
            self.assertEqual(prefix["events"], [e for e in full["events"] if e["timestamp_ms"] <= times[n-1]])

    def test_exposure_endpoint_convention(self):
        self.assertEqual(replay.common_exposure_ms(1590, 3990), 2210)
        self.assertEqual(replay.full_exposure_ms(1590, 3990), 2410)
        self.assertEqual(replay.common_exposure_ms(0, 100), 0)

    def test_invalid_scheduling_inputs_rejected(self):
        for delay in (-50, 1, 250, float('nan'), True):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                replay.schedule_events([], delay, 500)
        for base in ([event(200), event(100)], [event(100), event(100)],
                     [event(float('nan'))], [event(501)], [event(-1)]):
            with self.subTest(base=base), self.assertRaises(ValueError):
                replay.schedule_events(base, 50, 500)

    def test_invalid_predictions_rejected(self):
        for times, scores in (([50, 0], np.eye(5)[:2]), ([0, 0], np.eye(5)[:2]),
                              ([0, float('inf')], np.eye(5)[:2]), ([0], [[float('nan')]*5]),
                              ([0, 50], np.eye(5)[:1]), ([], [])):
            with self.subTest(times=times), self.assertRaises(ValueError):
                replay.issue_delayed(times, scores, 50)

    def test_api_cannot_accept_truth_or_source(self):
        self.assertEqual(list(inspect.signature(replay.issue_delayed).parameters),
                         ['times', 'scores', 'delay_ms', 'common', 'max_delay_ms'])


if __name__ == '__main__':
    unittest.main()
