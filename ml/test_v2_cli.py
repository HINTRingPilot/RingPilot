"""CLI failure paths use temporary results and never start training."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import v2_return as vr


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.out = self.root / "out"
        self.stack.enter_context(patch.object(vr, "OUT", self.out))
        self.stack.enter_context(patch.object(vr, "RUNS", self.root / "runs"))
        self.stack.enter_context(patch.object(vr, "ROOT", self.root))
        self.stack.enter_context(patch.object(vr.v2, "SEEDS", (11, 12)))
        self.stack.enter_context(patch.object(vr.v2, "EPOCH_CANDIDATES", (1, 2)))
        self.weak_file = self.root / "weak.json"
        self.weak_file.write_text("{}", encoding="utf-8")
        self.stack.enter_context(patch.object(vr, "WEAK_GESTURES", self.weak_file))
        self.stack.enter_context(patch.object(vr, "load_weak", return_value=frozenset({"fixture/raw_up.1.csv"})))
        self.stack.enter_context(patch.object(vr, "load", return_value=({}, {}, {})))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def write_results(self):
        sources = [
            {"source_path": "fixture/raw_up.1.csv", "counts": {"correct": 1},
             "delays_ms": [20], "events": [[1600, 1, "correct"]]},
            {"source_path": "fixture/raw_down.1.csv", "counts": {"correct": 1},
             "delays_ms": [30], "events": [[1600, 2, "correct"]]},
            {"source_path": "fixture/idle.1.csv", "counts": {"background_false": 0},
             "delays_ms": [], "events": []},
        ]
        for split in ("C", "S-P5"):
            for seed in vr.v2.SEEDS:
                result = {"label": vr.LABEL, "split": split, "seed": seed,
                          "folds": [{"fold": 0, "per_epoch": {
                              str(epoch): {sc: {"totals": {}, "per_source": copy.deepcopy(sources)}
                                           for sc in vr.SCORINGS}
                              for epoch in vr.v2.EPOCH_CANDIDATES}}]}
                path = vr.result_path(vr.LABEL, split, seed, "fixture")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(result), encoding="utf-8")

    def summarize(self):
        vr.cmd_summarize("summary.json", "fixture", splits=("C", "S-P5"))

    def test_missing_all_does_not_create_summary(self):
        with self.assertRaises(FileNotFoundError) as raised:
            self.summarize()
        self.assertIn("seed-11.json", str(raised.exception))
        self.assertIn("seed-12.json", str(raised.exception))
        self.assertFalse((self.out / "summary.json").exists())

    def test_missing_one_seed_then_complete_same_output(self):
        self.write_results()
        path = vr.result_path(vr.LABEL, "S-P5", 12, "fixture")
        contents = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.summarize()
        self.assertFalse((self.out / "summary.json").exists())
        path.write_bytes(contents)
        self.summarize()
        result = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(result["labels"], [vr.LABEL])
        self.assertEqual(set(result["panels"]), {f"{vr.LABEL}-C", f"{vr.LABEL}-S-P5"})
        panel = result["panels"][f"{vr.LABEL}-C"]["extreme_window"]
        self.assertEqual(panel["selected_E"], 1)
        self.assertEqual(panel["by_epoch"]["1"]["clean_success_rate"], 1.0)

    def test_missing_split_does_not_create_summary(self):
        self.write_results()
        for seed in vr.v2.SEEDS:
            vr.result_path(vr.LABEL, "C", seed, "fixture").unlink()
        with self.assertRaises(FileNotFoundError):
            self.summarize()
        self.assertFalse((self.out / "summary.json").exists())

    def test_empty_splits_rejected(self):
        with self.assertRaises(ValueError):
            vr.cmd_summarize("summary.json", "fixture", splits=())
        self.assertFalse((self.out / "summary.json").exists())

    def test_invalid_json_identifies_file_and_creates_nothing(self):
        self.write_results()
        vr.result_path(vr.LABEL, "C", 11, "fixture").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "seed-11.json"):
            self.summarize()
        self.assertFalse((self.out / "summary.json").exists())

    def test_wrong_seed_and_incomplete_structure_rejected(self):
        self.write_results()
        path = vr.result_path(vr.LABEL, "C", 11, "fixture")
        result = json.loads(path.read_text(encoding="utf-8"))
        result["seed"] = 999
        path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "seed-11.json"):
            self.summarize()
        result["seed"] = 11
        result["folds"] = []
        path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "seed-11.json"):
            self.summarize()
        self.assertFalse((self.out / "summary.json").exists())

    def test_existing_output_unchanged(self):
        self.out.mkdir()
        path = self.out / "summary.json"
        path.write_bytes(b"keep existing result\n")
        with self.assertRaises(FileExistsError):
            self.summarize()
        self.assertEqual(path.read_bytes(), b"keep existing result\n")

    def test_nested_invalid_scores_identify_result_file(self):
        for mutation in ("epoch", "count", "event", "delay"):
            with self.subTest(mutation=mutation):
                self.write_results()
                path = vr.result_path(vr.LABEL, "C", 11, "fixture")
                result = json.loads(path.read_text(encoding="utf-8"))
                epoch = result["folds"][0]["per_epoch"]["1"]
                source = epoch["new_window"]["per_source"][0]
                if mutation == "epoch":
                    result["folds"][0]["per_epoch"]["1"] = []
                elif mutation == "count":
                    source["counts"]["correct"] = "bad"
                elif mutation == "event":
                    source["events"] = [[]]
                else:
                    source["delays_ms"] = [float("nan")]
                path.write_text(json.dumps(result), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "seed-11.json"):
                    self.summarize()
                self.assertFalse((self.out / "summary.json").exists())


class ParallelTests(unittest.TestCase):
    def test_nonpositive_direct_call_has_no_side_effects(self):
        for count in (0, -1):
            with self.subTest(count=count), patch.object(vr, "keep_awake") as awake, \
                    patch.object(vr, "log_dir") as logs, patch.object(vr.subprocess, "Popen") as popen:
                popen.side_effect = AssertionError("must not start training")
                with self.assertRaises(ValueError):
                    vr.cmd_run_all(count)
                awake.assert_not_called()
                logs.assert_not_called()
                popen.assert_not_called()

    def test_cli_invalid_values_exit_two_without_running(self):
        for value in ("0", "-1", "no"):
            with self.subTest(value=value), patch.object(sys, "argv", ["v2_return.py", "run-all", "--parallel", value]), \
                    patch.object(vr, "cmd_run_all") as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    vr.main()
                self.assertEqual(raised.exception.code, 2)
                run.assert_not_called()

    def test_completed_and_failed_jobs_finish_and_logs_close(self):
        for count in (1, 2):
            for failed in (False, True):
                with self.subTest(count=count, failed=failed), tempfile.TemporaryDirectory() as folder, \
                        patch.object(vr, "keep_awake"), patch.object(vr, "log_dir", return_value=Path(folder)), \
                        patch.object(vr.v2, "SEEDS", (11, 12)), \
                        patch.object(vr, "result_path", return_value=Path(folder) / "missing.json"), \
                        patch.object(vr.time, "sleep", side_effect=AssertionError("all fake jobs already completed")), \
                        contextlib.redirect_stdout(io.StringIO()):
                    handles = []

                    def start(*args, **kwargs):
                        handles.append(kwargs["stdout"])
                        return Mock(poll=lambda: int(failed), wait=lambda: int(failed))

                    with patch.object(vr.subprocess, "Popen", side_effect=start) as popen:
                        if failed:
                            with self.assertRaises(SystemExit) as raised:
                                vr.cmd_run_all(count, splits=("C",))
                            self.assertEqual(raised.exception.code, 1)
                        else:
                            vr.cmd_run_all(count, splits=("C",))
                    self.assertEqual(popen.call_count, 2)
                    self.assertTrue(all(handle.closed for handle in handles))


if __name__ == "__main__":
    unittest.main()
