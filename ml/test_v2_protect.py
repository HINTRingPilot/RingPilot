"""BLE v2 실행기 보호 검사 점검. 해시가 다르면 거부하는지, 과거 결과를 기록된 코드로 확인하는지 본다.

짧은 학습은 RuntimeRecordTests 하나뿐이며 코드 점검용이다(S-P5 학습용 안의 fold 하나, 1 epoch).
"""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import v2
import v2_cal
from test_v2_cal import epoch_entry, source


def synthetic_run(seeds=(1, 2), epochs=(1, 5), runner_version=2):
    """분할 하나(fold 2개)에 맞는 가짜 설정·분할·결과. 모든 검사를 통과하는 기준 상태."""
    folds = [["data/sessions/x/raw_up.1.csv", "data/sessions/x/idle.1.csv"],
             ["data/sessions/x/raw_up.2.csv", "data/sessions/x/idle.2.csv"]]
    split_obj = {"eval_sources": ["data/sessions/x/raw_up.9.csv"],
                 "cv": {"folds": [{"fold": k, "validation_sources": f, "held_out_session": f"P{k}"} for k, f in enumerate(folds)]}}
    config = {"split": "X", "seeds": list(seeds), "epoch_candidates": list(epochs), "n_folds": 2, "runner_version": runner_version}
    runtime = {"tf_threads_fixed": True, "op_determinism": True, "intra_op_threads": 1, "inter_op_threads": 1}

    def entry(paths):
        per = []
        for p in paths:
            if "raw_" in p:
                per.append(source(Path(p).name, 2000, {"correct": 1},
                                  [{"timestamp_ms": 2100, "class_index": 1, "kind": "correct"}], [100]))
            else:
                per.append(source(Path(p).name, None, {}))
            per[-1]["source_path"] = p
        e = epoch_entry(per)
        e["event_totals"] = {"correct": 1}
        return e

    results = []
    for s in seeds:
        r = {"seed": s, "split": "X", "runner_version": runner_version, "runtime": dict(runtime), "folds": []}
        for k, f in enumerate(folds):
            r["folds"].append({"fold": k, "held_out_session": f"P{k}", "train_loss_by_epoch": [1.0] * max(epochs),
                               "per_epoch": {str(e): entry(f) for e in epochs}})
        results.append(r)
    return config, split_obj, results


class ConfigAndProtocolGuards(unittest.TestCase):
    def state(self, tmp):
        protocol_path = Path(tmp) / "protocol.json"
        v2.dump(protocol_path, {"note": "synthetic"})
        config = {"runner_version": v2_cal.RUNNER_VERSION, "split": "S-P5",
                  "split_sha256": v2.digest(v2.SPLITS / "v2-S-P5.json"), "records_sha256": v2.digest(v2.RECORDS),
                  "code_sha256": dict(v2_cal.code_hashes()), "protocol_sha256": v2.digest(protocol_path),
                  "protocol_path": str(protocol_path)}
        return config, protocol_path

    def setUp(self):
        if not v2.RECORDS.exists():
            self.skipTest("주석이 아직 없다")

    def test_config_issues_flag_each_changed_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, pp = self.state(tmp)
            self.assertEqual(v2_cal.config_issues(config, "S-P5", protocol_path=pp), [])
            for key, text in (("split_sha256", "분할"), ("records_sha256", "records"), ("protocol_sha256", "protocol")):
                issues = v2_cal.config_issues(dict(config, **{key: "0" * 64}), "S-P5", protocol_path=pp)
                self.assertTrue(any(text in i for i in issues), (key, issues))
            for name in v2_cal.CODE_FILES:      # init 이후 코드가 바뀐 경우
                bad = dict(config, code_sha256=dict(config["code_sha256"], **{name: "0" * 64}))
                self.assertTrue(any(name in i for i in v2_cal.config_issues(bad, "S-P5", protocol_path=pp)), name)
            self.assertTrue(any("실행기 버전" in i for i in v2_cal.config_issues(dict(config, runner_version=1), "S-P5", protocol_path=pp)))
            self.assertTrue(any("분할" in i for i in v2_cal.config_issues(config, "C", protocol_path=pp)))

    def test_run_is_refused_when_a_hash_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, pp = self.state(tmp)
            bad = dict(config, records_sha256="f" * 64)
            with self.assertRaises(v2_cal.Mismatch):
                v2_cal.raise_issues("거부", v2_cal.config_issues(bad, "S-P5", protocol_path=pp))

    def test_protocol_issues_flag_split_records_and_code(self):
        protocol = {"split_sha256": {"S-P5": v2.digest(v2.SPLITS / "v2-S-P5.json")}, "records_sha256": v2.digest(v2.RECORDS),
                    "code_sha256": v2_cal.code_hashes()}
        self.assertEqual(v2_cal.protocol_issues(protocol, "S-P5"), [])
        self.assertTrue(v2_cal.protocol_issues(dict(protocol, split_sha256={"S-P5": "0" * 64}), "S-P5"))
        self.assertTrue(v2_cal.protocol_issues(dict(protocol, records_sha256="0" * 64), "S-P5"))
        bad_code = dict(protocol["code_sha256"], **{"v2.py": "0" * 64})
        self.assertTrue(any("v2.py" in i for i in v2_cal.protocol_issues(dict(protocol, code_sha256=bad_code), "S-P5")))

    def test_old_protocol_is_rejected_for_the_changed_runner(self):
        """과거 protocol은 고치지 않는다. 코드가 바뀐 현재는 그 protocol로 새 init을 거부해야 한다."""
        old = json.loads((v2.DOC / "results/protocol.json").read_text(encoding="utf-8"))
        issues = v2_cal.protocol_issues(old, "S-P5")
        self.assertTrue(any("v2_cal.py" in i for i in issues), issues)


class AnnotationListGuard(unittest.TestCase):
    def test_extra_and_missing_files_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/sessions/s1").mkdir(parents=True)
            for n in ("raw_up.1.csv", "idle.1.csv"):
                (root / "data/sessions/s1" / n).write_text("x", encoding="utf-8")
            data = {"sessions": {"P1": {"folder": "s1"}},
                    "records": [{"source_path": "data/sessions/s1/raw_up.1.csv"}, {"source_path": "data/sessions/s1/idle.1.csv"}]}
            self.assertEqual(v2_cal.annotation_list_issues(data, root), [])
            (root / "data/sessions/s1/raw_up.2.csv").write_text("x", encoding="utf-8")
            self.assertTrue(any("raw_up.2.csv" in i for i in v2_cal.annotation_list_issues(data, root)))
            (root / "data/sessions/s1/raw_up.1.csv").unlink()
            self.assertTrue(any("raw_up.1.csv" in i for i in v2_cal.annotation_list_issues(data, root)))


class RecordedCodeAndRuntime(unittest.TestCase):
    def test_recorded_code_check_uses_the_git_version_not_the_current_code(self):
        body = b"line1\r\nline2\r\n"
        sha = hashlib.sha256(b"line1\nline2\n").hexdigest()
        cfg = {"git_head": "abcdef0123", "code_sha256": {"v2.py": sha}}
        self.assertEqual(v2_cal.recorded_code_issues(cfg, show=lambda head, path: body), [])
        self.assertTrue(v2_cal.recorded_code_issues(cfg, show=lambda head, path: b"other"))
        self.assertTrue(v2_cal.recorded_code_issues(cfg, show=lambda head, path: None))
        self.assertTrue(v2_cal.recorded_code_issues({"code_sha256": {"v2.py": sha}}))

    def test_runtime_ok(self):
        good = {"tf_threads_fixed": True, "op_determinism": True, "intra_op_threads": 1, "inter_op_threads": 1}
        self.assertTrue(v2_cal.runtime_ok(good))
        for key, bad in (("tf_threads_fixed", False), ("tf_threads_fixed", None), ("op_determinism", False),
                         ("intra_op_threads", 0), ("inter_op_threads", 4)):
            self.assertFalse(v2_cal.runtime_ok(dict(good, **{key: bad})), key)
        self.assertFalse(v2_cal.runtime_ok({}))
        self.assertFalse(v2_cal.runtime_ok(None))


class ResultsValidation(unittest.TestCase):
    def contains(self, issues, text):
        self.assertTrue(any(text in i for i in issues), issues)

    def test_baseline_passes(self):
        config, split_obj, results = synthetic_run()
        self.assertEqual(v2_cal.results_issues(config, split_obj, results), [])

    def test_missing_and_duplicate_seed(self):
        config, split_obj, results = synthetic_run()
        self.contains(v2_cal.results_issues(config, split_obj, results[:1]), "seed 목록")
        self.contains(v2_cal.results_issues(config, split_obj, results + [results[0]]), "중복")

    def test_missing_fold_and_epoch(self):
        config, split_obj, results = synthetic_run()
        results[0]["folds"].pop()
        self.contains(v2_cal.results_issues(config, split_obj, results), "fold 목록")
        config, split_obj, results = synthetic_run()
        del results[1]["folds"][0]["per_epoch"]["5"]
        self.contains(v2_cal.results_issues(config, split_obj, results), "epoch 목록")

    def test_duplicate_missing_and_evaluation_sources(self):
        config, split_obj, results = synthetic_run()
        ps = results[0]["folds"][0]["per_epoch"]["1"]["per_source"]
        ps.append(dict(ps[0]))
        self.contains(v2_cal.results_issues(config, split_obj, results), "중복 원본")
        config, split_obj, results = synthetic_run()
        results[0]["folds"][0]["per_epoch"]["1"]["per_source"].pop()
        self.contains(v2_cal.results_issues(config, split_obj, results), "분할과 다르다")
        config, split_obj, results = synthetic_run()
        results[0]["folds"][0]["per_epoch"]["1"]["per_source"][0]["source_path"] = split_obj["eval_sources"][0]
        self.contains(v2_cal.results_issues(config, split_obj, results), "평가용 원본")

    def test_source_in_two_folds_and_inconsistent_totals(self):
        config, split_obj, results = synthetic_run()
        shared = split_obj["cv"]["folds"][0]["validation_sources"][0]
        split_obj["cv"]["folds"][1]["validation_sources"].append(shared)
        extra = dict(results[0]["folds"][0]["per_epoch"]["1"]["per_source"][0])
        results[0]["folds"][1]["per_epoch"]["1"]["per_source"].append(extra)
        self.contains(v2_cal.results_issues(config, split_obj, results), "두 fold")
        config, split_obj, results = synthetic_run()
        results[0]["folds"][0]["per_epoch"]["1"]["event_totals"] = {"correct": 5}
        self.contains(v2_cal.results_issues(config, split_obj, results), "event_totals")
        config, split_obj, results = synthetic_run()
        results[0]["folds"][0]["per_epoch"]["1"]["per_source"][0]["events"] = []
        self.contains(v2_cal.results_issues(config, split_obj, results), "발행 로그")

    def test_runtime_is_required_only_for_new_runs(self):
        config, split_obj, results = synthetic_run()
        results[0]["runtime"]["tf_threads_fixed"] = False
        self.contains(v2_cal.results_issues(config, split_obj, results), "스레드")
        config, split_obj, results = synthetic_run(runner_version=1)       # 과거 결과(런타임 기록 없음)
        for r in results:
            r.pop("runtime")
            r.pop("runner_version")
        self.assertEqual(v2_cal.results_issues(config, split_obj, results), [])


class PastResults(unittest.TestCase):
    """과거 결과(실행기 버전 1)는 현재 코드와 달라도 손상으로 보지 않고 기록된 코드 버전으로 확인한다."""

    @classmethod
    def setUpClass(cls):
        out = v2_cal.results_dir("V2-S-P5-cal")
        if not (out / "summary.json").exists():
            raise unittest.SkipTest("과거 결과가 없다")
        cls.config = v2_cal.load_config("V2-S-P5-cal")
        if json.loads(v2.RECORDS.read_text(encoding="utf-8")).get("revisions"):
            # 2026-10-28 records.json에서 클립 2개를 뺐다. 과거 결과는 이전 records(커밋 b545b95 이전)로 계산됐으므로
            # 해시가 달라 현재 데이터로는 확인할 수 없다. 확인하려면 그 커밋의 data/를 꺼내 실행한다.
            raise unittest.SkipTest("records.json이 수정돼 과거 V2-*-cal 결과는 이전 데이터로만 확인할 수 있다")
        cls.results = v2_cal.load_seed_results(out, cls.config)

    def test_verified_against_recorded_code(self):
        self.assertEqual(self.config.get("runner_version", 1), 1)
        self.assertNotEqual(self.config["code_sha256"]["v2_cal.py"], v2_cal.code_hashes()["v2_cal.py"])   # 현재 코드는 이미 다르다
        kind, issues = v2_cal.check_results(self.config, "S-P5", self.results)
        self.assertEqual(issues, [])
        self.assertIn("과거 결과", kind)
        self.assertTrue(v2_cal.config_issues(self.config, "S-P5"))   # 하지만 새 실행으로는 거부된다

    def test_verify_matches_saved_summary_and_summarize_does_not_overwrite(self):
        out = v2_cal.results_dir("V2-S-P5-cal")
        before = v2.digest(out / "summary.json")
        with contextlib.redirect_stdout(io.StringIO()):     # cmd_verify가 "—"를 출력해 cp949 콘솔 파이프에서 실패하는 것을 피한다
            again = v2_cal.cmd_verify("S-P5")
        saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(again["chosen_E"], saved["chosen_E"])
        with self.assertRaises(FileExistsError):
            v2_cal.cmd_summarize("S-P5")
        self.assertEqual(v2.digest(out / "summary.json"), before)


class RuntimeRecord(unittest.TestCase):
    def test_short_check_run_records_runtime(self):
        if not v2.RECORDS.exists():
            self.skipTest("주석이 아직 없다")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            result = v2_cal.run_seed("S-P5", v2.SEED, tmp, tmp / "scores", folds=[0], epochs=(1,), log=lambda *a: None)   # 코드 점검용 짧은 학습
        rt = result["runtime"]
        self.assertEqual(result["runner_version"], v2_cal.RUNNER_VERSION)
        for key in ("tf_threads_fixed", "intra_op_threads", "inter_op_threads", "op_determinism", "env", "tensorflow", "devices"):
            self.assertIn(key, rt)
        self.assertTrue(rt["op_determinism"])
        self.assertEqual(rt["env"]["TF_ENABLE_ONEDNN_OPTS"], "0")


if __name__ == "__main__":
    unittest.main()
