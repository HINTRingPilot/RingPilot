"""연속 스트림 재생 점검. 마지막 테스트는 fold 하나의 학습 집합을 만든다(학습은 하지 않는다)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

import v2
import v2_return as vr
import v2_stream as st


def write_csv(path, raw, step=10):
    rows = ["timestamp," + ",".join(v2.AXES)]
    rows += [f"{i * step}," + ",".join(f"{v:.4f}" for v in r) for i, r in enumerate(raw)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")


class ReadTests(unittest.TestCase):
    def test_reads_any_length_and_rejects_gaps(self):
        raw = np.random.default_rng(0).normal(size=(1234, 6))
        with tempfile.TemporaryDirectory() as d:
            write_csv(Path(d) / "long.csv", raw)
            ts, got = st.read_stream(Path(d) / "long.csv")
            self.assertEqual(got.shape, (1234, 6))
            np.testing.assert_allclose(got, raw, atol=1e-4)
            write_csv(Path(d) / "gap.csv", raw, step=20)
            with self.assertRaises(ValueError):
                st.read_stream(Path(d) / "gap.csv")


class StillTests(unittest.TestCase):
    def test_estimate_follows_still_periods_only(self):
        rng = np.random.default_rng(0)
        raw = rng.normal(scale=0.3, size=(600, 6))
        raw[:, 0:3] += (1.0, -2.0, 9.5)
        raw[:, 3:6] += (10.0, -5.0, 3.0)                                  # 정지 중 자이로 치우침
        raw[200:300, 3:6] += rng.normal(scale=150, size=(100, 3))          # 움직임
        raw[300:, 3:6] += (2.0, 0.0, 0.0)                                  # 움직인 뒤 치우침이 조금 바뀜
        gyro_bias, acc_static = st.still_estimates(raw)
        np.testing.assert_allclose(gyro_bias[199], (10, -5, 3), atol=0.2)
        np.testing.assert_allclose(gyro_bias[280], gyro_bias[199])          # 움직이는 동안은 직전 값을 유지
        np.testing.assert_allclose(gyro_bias[599], (12, -5, 3), atol=0.2)
        np.testing.assert_allclose(acc_static[599], (1.0, -2.0, 9.5), atol=0.2)


class WindowTests(unittest.TestCase):
    def test_fixed_precue_reproduces_training_inputs(self):
        # 클립 방식 영점(0~890 ms)을 고정해 넣으면 학습 때 만든 검증 입력과 같아야 한다(prep.json만으로 재현)
        _, by_path, nb = vr.load()
        split = v2.load_split("S-P5")
        for label in (vr.LABEL,):
            d, _ = vr.prepare_fold(label, by_path, nb, split, 0)
            prep = vr.prep_values(label, d)
            for record, x_val, _, meta in d["val"][:3]:
                ts, raw = v2.read_sensor(vr.ROOT / record["source_path"])
                x, times = st.stream_inputs(raw, ts, prep, *st.precue_estimates(raw))
                self.assertEqual(times, [m["timestamp_ms"] for m in meta])
                np.testing.assert_allclose(x, x_val, atol=1e-5, err_msg=f"{label} {record['source_path']}")
