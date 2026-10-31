"""C 추론(firmware/gesture_tcn) 점검. 학습하지 않고 무작위 가중치 모델로 Keras와 비교한다. C 컴파일러가 없으면 빌드 테스트는 건너뛴다."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

import model as ringpilot_model
import v2_export_c as ex

DILATIONS = list(ringpilot_model.TCN_DILATIONS)


def fake_prep():
    rng = np.random.default_rng(1)
    return {"input_channels": ex.INPUT_CHANNELS, "window": 160, "stride": 5, "sample_ms": 10.0,
            "classes": ["NONE", "UP", "DOWN", "LEFT", "RIGHT"], "norm_mean_6axis": rng.normal(size=6).tolist(),
            "norm_std_6axis": rng.uniform(50, 150, 6).tolist(), "angle_mean": rng.normal(0, .02, 3).tolist(),
            "angle_std": rng.uniform(.2, .5, 3).tolist(), "angle_scale_deg": 45.0}


class PositionTests(unittest.TestCase):
    def test_needed_positions_per_block(self):
        positions = ex.needed_positions(DILATIONS, 160)
        self.assertEqual([len(p) for p in positions], [93, 45, 21, 9, 3, 1])
        self.assertEqual(positions[-1], [159])
        self.assertEqual(positions[-2], [61, 110, 159])

    def test_macs_match_design_minus_padding(self):
        positions = ex.needed_positions(DILATIONS, 160)
        # 설계값 96,464에서 창 앞으로 넘어가 건너뛰는 입력 한 칸(6채널 × 16필터)을 뺀다
        self.assertEqual(ex.mac_count(positions, DILATIONS, 6, 16, 5), 96464 - 96)

    def test_source_table_points_to_previous_block(self):
        positions, rows = ex.source_table(DILATIONS, 160)
        self.assertEqual(len(rows), 3 * sum(len(p) for p in positions))
        self.assertEqual(rows[-3:], [positions[-2].index(61), positions[-2].index(110), positions[-2].index(159)])
        self.assertEqual(rows.count(-1), 1)


class TableReferenceTests(unittest.TestCase):
    def test_table_calculation_matches_keras(self):
        import tensorflow as tf
        tf.keras.utils.set_random_seed(11)
        model = ringpilot_model.build_tcn(160, channels=6)
        x = np.random.default_rng(4).normal(size=(5, 160, 6)).astype(np.float32)
        np.testing.assert_allclose(ex.table_predict(model, x), model(x, training=False).numpy(), atol=1e-5)


@unittest.skipIf(ex.find_cc() is None, "C 컴파일러 없음(RINGPILOT_CC 또는 gcc·clang)")
class HostBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tensorflow as tf
        tf.keras.utils.set_random_seed(7)
        cls.model = ringpilot_model.build_tcn(160, channels=6)
        cls.prep = fake_prep()
        cls.work = tempfile.TemporaryDirectory()
        ex.write_header(cls.model, cls.prep, Path(cls.work.name) / "gesture_weights.h")
        cls.exe = Path(cls.work.name) / "host_check.exe"
        ex.build_host(cls.work.name, cls.exe)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_scores_match_keras(self):
        x = np.random.default_rng(2).normal(size=(40, 160, 6)).astype(np.float32)
        c = ex.run_predict(self.exe, x, self.work.name)
        np.testing.assert_allclose(c, self.model(x, training=False).numpy(), atol=1e-5)

    def test_prepare_matches_recipe(self):
        rng = np.random.default_rng(3)
        gyro = rng.normal(0, 80, size=(10, 160, 3))
        bias = rng.normal(0, 5, size=(10, 3))
        x, _ = ex.run_prepare(self.exe, gyro, bias, self.work.name)
        mean, std = np.array(self.prep["norm_mean_6axis"])[3:], np.array(self.prep["norm_std_6axis"])[3:]
        np.testing.assert_allclose(x[:, :, :3], (gyro - mean) / std, atol=1e-4)
        angle = np.cumsum((gyro - bias[:, None]) * .01, axis=1)
        angle -= angle[:, :1]
        expected = (angle / 45.0 - self.prep["angle_mean"]) / self.prep["angle_std"]
        np.testing.assert_allclose(x[:, :, 3:], expected, atol=1e-4)
        self.assertEqual(np.abs(angle[:, 0]).max(), 0.0)


if __name__ == "__main__":
    unittest.main()
