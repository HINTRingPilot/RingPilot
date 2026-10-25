"""새 경로가 NONE 배분 이외의 학습·채점 조건을 유지하는지 확인."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import v2
import v2_none_cal as cal
import v2_protocol


class FoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.by_path = v2.load_records()
        cls.split = v2.load_split("C")

    def test_legacy_sampler_reproduces_the_legacy_arrays(self):
        old = v2.fold_sets(self.by_path, self.split, 0)
        new = cal.build_fold(self.by_path, self.split, 0, sampler=v2.choose_training)
        for key in ("x_train", "y_train", "mean", "std"):
            np.testing.assert_array_equal(new[key], old[key], err_msg=key)
        for a, b in zip(old["val"], new["val"]):
            self.assertEqual(a[0], b[0])
            np.testing.assert_array_equal(a[1], b[1])
            np.testing.assert_array_equal(a[2], b[2])
            self.assertEqual(a[3], b[3])

    def test_new_sampler_preserves_counts_and_reaches_every_session(self):
        d = cal.build_fold(self.by_path, self.split, 0)
        expected = json.loads((v2.DOC / "results/V2-C-cal/config.json").read_text(encoding="utf-8"))["folds"][0]
        self.assertEqual(d["train_counts"], expected["train_windows_selected"])
        self.assertEqual(d["train_none_groups"], expected["train_none_groups"])
        sessions = {self.by_path[m["source_path"]]["session"] for m in d["selected_meta"] if m["target"] == 0 and m["none_group"] == "in_progress"}
        self.assertEqual(sessions, set(v2.SESSION_KEYS))
        forbidden = set(self.split["eval_sources"]) | set(self.split["cv"]["folds"][0]["validation_sources"])
        self.assertFalse(forbidden & {m["source_path"] for m in d["selected_meta"]})

    def test_new_inputs_complete_a_short_code_check_fit_and_replay(self):
        d = cal.build_fold(self.by_path, self.split, 0)
        validation = np.concatenate([c[1] for c in d["val"]])
        snapshots, loss = v2.fit_snapshots(d["x_train"], d["y_train"], validation, v2.SEED, (1,))
        self.assertEqual(len(loss), 1)
        self.assertTrue(np.isfinite(snapshots[1]).all())
        self.assertTrue(np.allclose(snapshots[1].sum(axis=1), 1, atol=1e-5))
        _, per_source = v2.score_events(d["val"], snapshots[1])
        self.assertEqual({p["source_path"] for p in per_source}, set(self.split["cv"]["folds"][0]["validation_sources"]))


class ProtocolTests(unittest.TestCase):
    def test_generic_output_is_exclusive_and_legacy_protocol_is_not_modified(self):
        spec = v2.DOC / "none-balance-01/spec.json"
        before = v2.digest(v2.DOC / "results/protocol.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "protocol.json"
            p = v2_protocol.create_protocol(spec, out)
            self.assertEqual(p["spec"]["data_role"], "development_diagnostic")
            self.assertEqual(cal.protocol_issues(p), [])
            with self.assertRaises(FileExistsError):
                v2_protocol.create_protocol(spec, out)
            p["records_sha256"] = "0" * 64
            self.assertTrue(any("records" in x for x in cal.protocol_issues(p)))
        self.assertEqual(before, v2.digest(v2.DOC / "results/protocol.json"))

    def test_missing_code_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = v2_protocol.create_protocol(v2.DOC / "none-balance-01/spec.json", Path(tmp) / "p.json")
            del p["code_sha256"]["ml/v2_none_stratified.py"]
            self.assertTrue(any("code" in x for x in cal.protocol_issues(p)))


if __name__ == "__main__":
    unittest.main()
