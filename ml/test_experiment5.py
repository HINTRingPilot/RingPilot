"""Protect default model compatibility and verify the GAP output contract."""
import unittest
import numpy as np
import tensorflow as tf
from model import build_model


class ReadoutTests(unittest.TestCase):
    def test_default_remains_flatten(self):
        tf.keras.backend.clear_session()
        model=build_model()
        self.assertIsInstance(model.get_layer("time_features"),tf.keras.layers.Flatten)
        self.assertEqual(model.input_shape,(None,160,6))
        self.assertEqual(model.count_params(),9493)

    def test_gap_keeps_five_class_output(self):
        tf.keras.backend.clear_session()
        model=build_model(readout="gap")
        self.assertEqual(model.get_layer("time_features").output.shape,(None,32))
        self.assertEqual(model.count_params(),3253)
        result=model(np.zeros((1,160,6),dtype=np.float32),training=False).numpy()
        self.assertEqual(result.shape,(1,5))
        self.assertTrue(np.isfinite(result).all())
        np.testing.assert_allclose(result.sum(axis=1),[1.0],atol=1e-6)


if __name__=="__main__":unittest.main()
