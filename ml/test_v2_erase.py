"""발행 뒤 입력 지우기 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2
import v2_erase as ve
import v2_stream as vs

PREP = {"input_channels": ["gyrX", "gyrY", "gyrZ", "angX", "angY", "angZ"], "window": 160, "stride": 5, "sample_ms": 10.0,
        "norm_mean_6axis": [0.0] * 6, "norm_std_6axis": [1.0] * 6, "angle_mean": [0.0] * 3, "angle_std": [1.0] * 3,
        "angle_scale_deg": 45.0, "acc_mode": None}


def fake_stream(rows=500):
    rng = np.random.default_rng(0)
    raw = np.zeros((rows, 6))
    raw[:, 2] = 9.8
    raw[:, 3:] = rng.normal(0, 1, size=(rows, 3))
    raw[200:230, 4] += 300
    return np.arange(rows) * 10.0, raw


def predictor(calls=None):
    """창 끝 200샘플 안의 주축 자이로가 크면 UP으로 답한다."""
    def predict(x):
        if calls is not None:
            calls.append(len(x))
        out = np.zeros((len(x), 5), dtype=np.float32)
        high = np.abs(x[:, -40:, 1]).max(axis=1) > 100
        out[:, 0] = np.where(high, 0.0, 1.0)
        out[:, 1] = np.where(high, 1.0, 0.0)
        return out
    return predict


class ReplayTests(unittest.TestCase):
    def test_none_mode_matches_issue_events(self):
        ts, raw = fake_stream()
        bias, static = vs.precue_estimates(raw)
        x, times = vs.stream_inputs(raw, ts, PREP, bias, static)
        expected = v2.issue_events(times, predictor()(x))
        events = ve.replay(predictor(), raw, ts, PREP, bias, static, None)
        self.assertTrue(expected)
        self.assertEqual(events, expected)

    def test_erasing_does_not_change_the_input_array(self):
        ts, raw = fake_stream()
        before = raw.copy()
        bias, static = vs.precue_estimates(raw)
        ve.replay(predictor(), raw, ts, PREP, bias, static, 0)
        np.testing.assert_array_equal(raw, before)

    def test_erase_recomputes_later_windows_only(self):
        ts, raw = fake_stream()
        bias, static = vs.precue_estimates(raw)
        calls = []
        ve.replay(predictor(calls), raw, ts, PREP, bias, static, 0)
        self.assertEqual(len(calls), 2)            # 처음 전체 + 발행 뒤 한 번
        self.assertLessEqual(calls[1], 160 // 5)   # 지운 행이 든 창은 판정 32개 이내다

    def test_quiet_erases_unissued_motion(self):
        ts, raw = fake_stream()
        bias, static = vs.precue_estimates(raw)
        never = lambda x: np.tile(np.array([1, 0, 0, 0, 0], np.float32), (len(x), 1))
        calls = []
        counted = lambda x: (calls.append(len(x)), never(x))[1]
        self.assertEqual(ve.replay(counted, raw, ts, PREP, bias, static, None, quiet_ms=150), [])
        self.assertEqual(len(calls), 2)            # 처음 전체 + 움직임(200~230행)이 끝나고 150 ms 정지 뒤 한 번
        calls.clear()
        ve.replay(counted, raw, ts, PREP, bias, static, None)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
