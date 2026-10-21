"""Verify completion remains a lower bound for both training label policies."""
import unittest
import numpy as np
from experiment3 import targets


class LabelPolicyTests(unittest.TestCase):
    def test_never_label_outbound_or_return_before_completion(self):
        np.testing.assert_array_equal(targets([0, 1000, 1999, 2000], 2000, 4, 300), [0, 0, 0, 4])

    def test_half_open_positive_intervals(self):
        t = [1990, 2000, 2140, 2150, 2290, 2300]
        np.testing.assert_array_equal(targets(t, 2000, 2, 150), [0, 2, 2, 0, 0, 0])
        np.testing.assert_array_equal(targets(t, 2000, 2, 300), [0, 2, 2, 2, 2, 0])

    def test_warmup_does_not_move_completion(self):
        t = [1590, 1640, 1690, 1740, 1790]
        np.testing.assert_array_equal(targets(t, 1480, 1, 150), [1, 0, 0, 0, 0])
        np.testing.assert_array_equal(targets(t, 1480, 1, 300), [1, 1, 1, 1, 0])

    def test_background_stays_none(self):
        np.testing.assert_array_equal(targets([0, 1590, 9990], None, 0, 300), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
