"""모델 저장 점검. 앞의 두 테스트는 아주 작은 학습(2 epoch)을 한다."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

import v2
import v2_return as vr


def tiny_data():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(32, v2.WINDOW, 6)).astype(np.float32)
    return x, rng.integers(0, 5, size=32)


class SaveTests(unittest.TestCase):
    def test_saved_models_reproduce_snapshot_scores(self):
        import tensorflow as tf
        x, y = tiny_data()
        with tempfile.TemporaryDirectory() as d:
            scores, _ = v2.fit_snapshots(x, y, x[:4], 20261021, (1, 2), model_fn=vr.tcn, save_dir=d)
            for e in (1, 2):
                loaded = tf.keras.models.load_model(Path(d) / f"e{e}.keras")
                np.testing.assert_allclose(loaded(x[:4], training=False).numpy(), scores[e], atol=1e-6)

    def test_saving_does_not_change_training(self):
        # E100 실행의 E≤60 스냅숏이 저장 없이 돌린 결과와 같아야 한다(계획 Task 2)
        x, y = tiny_data()
        plain, _ = v2.fit_snapshots(x, y, x[:4], 20261021, (1, 2), model_fn=vr.tcn)
        with tempfile.TemporaryDirectory() as d:
            saved, _ = v2.fit_snapshots(x, y, x[:4], 20261021, (1, 2), model_fn=vr.tcn, save_dir=d)
        for e in (1, 2):
            np.testing.assert_array_equal(plain[e], saved[e])


class FullSetTests(unittest.TestCase):
    def test_full_training_set_has_no_validation(self):
        _, by_path, nb = vr.load()
        split = v2.load_split("S-P5")
        d, _ = vr.prepare_fold("newtcnrotwarpnoacc", by_path, nb, split, None)
        self.assertEqual(d["val"], [])
        self.assertEqual(d["train_sources"], len(split["train_sources"]))
        prep = vr.prep_values("newtcnrotwarpnoacc", d)
        self.assertEqual(prep["input_channels"], ["gyrX", "gyrY", "gyrZ", "angX", "angY", "angZ"])
        self.assertEqual(d["x_train"].shape[2], len(prep["input_channels"]))
        self.assertEqual(len(prep["angle_mean"]), 3)
