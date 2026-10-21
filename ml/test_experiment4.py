"""Check history truncation and startup timing without touching final data."""
import unittest
from unittest.mock import patch
import numpy as np
from experiment4 import short_context, native_windows


class WindowTests(unittest.TestCase):
    def test_short_input_retains_latest_samples(self):
        x=np.arange(160*6).reshape(1,160,6)
        out=short_context(x,120)
        np.testing.assert_array_equal(out[0,0],x[0,40])
        np.testing.assert_array_equal(out[0,-1],x[0,-1])
        out[0,0]=0
        self.assertNotEqual(int(x[0,40,0]),0)

    def test_invalid_length(self):
        with self.assertRaises(ValueError):short_context(np.zeros((1,160,6)),161)

    def test_native_start_and_same_grid(self):
        ts=np.arange(300)*10;raw=np.zeros((300,6));r={"source_path":"unused","completion_ms":1480,"direction":"UP"}
        with patch("experiment4.base.read_sensor",return_value=(ts,raw)):
            x,y,meta=native_windows(r,np.zeros(6),np.ones(6),120)
            self.assertEqual((len(x),meta[0]["timestamp_ms"]),(37,1190))
            self.assertEqual(int(sum(y!=0)),3)
            self.assertEqual(sum(m["timestamp_ms"]>=1590 for m in meta),29)

    def test_no_crossing_file_or_using_future(self):
        ts=np.arange(300)*10;raw=np.repeat(np.arange(300)[:,None],6,axis=1);r={"source_path":"unused","completion_ms":None,"direction":"NONE"}
        with patch("experiment4.base.read_sensor",return_value=(ts,raw)):
            x,y,meta=native_windows(r,np.zeros(6),np.ones(6),120)
            self.assertEqual((x[0,0,0],x[0,-1,0]),(0,119))
            for w,m in zip(x,meta):self.assertEqual(w[-1,0]*10,m["timestamp_ms"])
            self.assertFalse(y.any())


if __name__=="__main__":unittest.main()
