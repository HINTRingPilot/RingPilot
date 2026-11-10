"""TCN 구조 검사: 인과성(미래 샘플이 과거 출력에 영향 없음)과 수용 영역(161샘플). 학습하지 않는다."""
import unittest

import numpy as np

import v2
from model import TCN_DILATIONS, build_tcn, receptive_field


class TcnStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tf = v2.configure_tf()
        tf.keras.utils.set_random_seed(1)
        cls.tf = tf
        cls.model = build_tcn(channels=9)
        cls.sequence = tf.keras.Model(cls.model.input, cls.model.get_layer(f"block{len(TCN_DILATIONS)}").output)
        cls.x = np.random.default_rng(0).normal(size=(2, 160, 9)).astype(np.float32)

    def test_receptive_field_covers_the_window(self):
        self.assertEqual(receptive_field(), 161)
        self.assertEqual(receptive_field(dilations=(1, 2, 4, 8, 16, 32)), 127)

    def test_future_samples_do_not_change_past_outputs(self):
        x2 = self.x.copy()
        x2[:, 100:, :] += 5.0
        a, b = self.sequence(self.x, training=False).numpy(), self.sequence(x2, training=False).numpy()
        np.testing.assert_array_equal(a[:, :100], b[:, :100])
        self.assertFalse(np.array_equal(a[:, 100:], b[:, 100:]))

    def test_first_sample_reaches_the_decision(self):
        x2 = self.x.copy()
        x2[:, 0, :] += 5.0
        self.assertFalse(np.array_equal(self.model(self.x, training=False).numpy(), self.model(x2, training=False).numpy()))

    def test_sample_outside_a_shorter_field_does_not_reach_the_decision(self):
        short = build_tcn(channels=9, dilations=(1, 2, 4, 8, 16, 32))     # 127샘플: 0~32번은 닿지 않는다
        x2 = self.x.copy()
        x2[:, :33, :] += 5.0
        np.testing.assert_array_equal(short(self.x, training=False).numpy(), short(x2, training=False).numpy())
        x2[:, 33, :] += 5.0
        self.assertFalse(np.array_equal(short(self.x, training=False).numpy(), short(x2, training=False).numpy()))

    def test_size(self):
        self.assertEqual(self.model.count_params(), 4613)
        self.assertEqual(self.model.output_shape, (None, 5))


if __name__ == "__main__":
    unittest.main()
