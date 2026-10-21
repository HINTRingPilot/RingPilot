"""Boundary checks for data labels and event state/matching; no training."""
import unittest
import numpy as np
from baseline import positive_count, issue_events, classify_events, choose_training


class BaselineTests(unittest.TestCase):
    def test_warmup_does_not_invent_positives(self):
        self.assertEqual(positive_count(1420), 0)
        self.assertEqual(positive_count(1480), 1)
        self.assertEqual(positive_count(1590), 3)

    def test_emit_second_and_require_rearm(self):
        direction = [0, .9, .04, .03, .03]
        none = [.9, .03, .03, .02, .02]
        p = np.array([direction]*4 + [none]*2 + [direction]*2)
        self.assertEqual([e['timestamp_ms'] for e in issue_events(range(0, 400, 50), p)], [50, 350])

    def test_direction_switch_restarts_counter(self):
        a, b = [0, .9, .04, .03, .03], [0, .04, .9, .03, .03]
        self.assertEqual([e['timestamp_ms'] for e in issue_events([0, 50, 100], np.array([a, b, b]))], [100])

    def test_early_wrong_duplicate_and_late_are_not_success(self):
        r = {'completion_ms': 2000, 'direction': 'UP'}
        events = [{'timestamp_ms': t, 'class_index': c} for t,c in [(1999,1),(2000,2),(2100,1),(2200,1),(2501,1)]]
        counts, delays, _ = classify_events(r, events)
        self.assertEqual([counts[k] for k in ('early','wrong_direction','correct','duplicate','late_unmatched','missed')], [1,1,1,1,1,0])
        self.assertEqual(delays, [100])

    def test_inclusive_500ms_matching(self):
        c, d, _ = classify_events({'completion_ms': 2000, 'direction': 'UP'}, [{'timestamp_ms': 2500,'class_index':1}])
        self.assertEqual((c['correct'], d), (1, [500]))

    def test_miss_and_background(self):
        c, _, _ = classify_events({'completion_ms':2000,'direction':'UP'}, [])
        self.assertEqual(c['missed'],1)
        c, _, _ = classify_events({'completion_ms':None,'direction':'NONE'}, [{'timestamp_ms':2000,'class_index':1}])
        self.assertEqual(c['background_false'],1)

    def test_none_sampling_only_changes_training_selection(self):
        y=np.array([1,2,3,4]+[0]*20)
        meta=[{'none_group':'idle' if i%2 else 'progress','source_path':str(i%3)} for i in range(len(y))]
        indices=choose_training(y,meta)
        self.assertEqual(np.bincount(y[indices],minlength=5).tolist(),[4,1,1,1,1])
        np.testing.assert_array_equal(indices,choose_training(y,meta))


if __name__ == '__main__':
    unittest.main()
