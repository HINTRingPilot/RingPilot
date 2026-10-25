"""spec/출력 경로를 받는 배타적 v2 실험 protocol 생성. 기존 protocol은 보존한다."""
import argparse
import json
from pathlib import Path

import v2
import v2_cal
import v2_protected_manifest as protected

BASELINE_PROTOCOL = v2.DOC / "results/protocol.json"
PROTECTED_MANIFEST = v2.DOC / "diagnostics/completion-review-01/protected-manifest.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def relative(path):
    return Path(path).resolve().relative_to(v2.ROOT.resolve()).as_posix()


def code_hashes(spec):
    names = spec["code_files"]
    if not names or len(names) != len(set(names)):
        raise ValueError("code_files는 비어 있지 않은 중복 없는 목록이어야 한다")
    result = {}
    for name in names:
        path = v2.ROOT / name
        if relative(path) != name or path.suffix != ".py":
            raise ValueError(f"프로젝트 안의 명시적 Python 코드 경로가 아니다: {name}")
        result[name] = v2.digest(path)
    return result


def create_protocol(spec_path, output_path):
    spec_path, output_path = Path(spec_path), Path(output_path)
    if output_path.exists():
        raise FileExistsError(output_path)
    spec = read(spec_path)
    if spec.get("data_role") != "development_diagnostic":
        raise ValueError("현재 336개 자료의 용도는 development_diagnostic이어야 한다")
    if set(spec["execution_order"]) != set(v2.SPLIT_NAMES) or len(spec["execution_order"]) != 6:
        raise ValueError("분할은 중복 없이 6개여야 한다")
    v2.verify()
    frozen = read(PROTECTED_MANIFEST)
    changes = protected.compare(v2.ROOT, frozen)
    if any(changes.values()):
        raise ValueError(f"기존 보호 대상이 변경됐다: {changes}")
    baseline = read(BASELINE_PROTOCOL)
    baseline_files = [BASELINE_PROTOCOL, PROTECTED_MANIFEST]
    for name in spec["execution_order"]:
        run = v2.DOC / "results" / f"V2-{name}-cal"
        baseline_files += [run / "config.json", run / "summary.json"]
        baseline_files += [run / f"seed-{s}.json" for s in v2.SEEDS]
        v2_cal.cmd_verify(name)
    fixed = json.loads(json.dumps(baseline["fixed_conditions"]))
    fixed["none_selection"] = "양성·총 NONE·종류별 개수는 원래 선택기 그대로. 각 종류 안에서 고정 seed로 세션→클립→창 배분만 변경"
    out = {
        "experiment": spec["experiment"], "created_before_training_kst": v2.now(),
        "spec_path": relative(spec_path), "spec_sha256": v2.digest(spec_path), "spec": spec,
        "records_sha256": v2.digest(v2.RECORDS),
        "split_sha256": {n: v2.digest(v2.SPLITS / f"v2-{n}.json") for n in v2.SPLIT_NAMES},
        "code_sha256": code_hashes(spec),
        "baseline_input_sha256": {relative(p): v2.digest(p) for p in baseline_files},
        "fixed_conditions": fixed, "data_processing_order": baseline["data_processing_order"],
        "events": baseline["events"], "epoch_selection": baseline["epoch_selection"],
        "code_check_note": "protocol 이전 단위 검사·짧은 코드 점검 학습은 가능. 새 보정 결과를 보고 규칙을 바꾸지 않는다",
        "hash_note": "JSON/CSV/Python은 CRLF→LF 후 SHA-256. 이전 NPZ 등 바이너리는 보호 manifest의 raw SHA-256",
        "git_head": v2_cal.git("rev-parse", "HEAD"),
        "git_status_short": v2_cal.git("status", "--short").splitlines(),
    }
    protected.write_new(output_path, out)
    return out


def input_issues(protocol):
    issues = []
    spec = protocol["spec"]
    if v2.digest(v2.ROOT / protocol["spec_path"]) != protocol["spec_sha256"]:
        issues.append("spec 파일이 protocol과 다르다")
    if read(v2.ROOT / protocol["spec_path"]) != spec:
        issues.append("protocol의 spec 내용이 파일과 다르다")
    if protocol.get("code_sha256") != code_hashes(spec):
        issues.append("code 해시/목록이 protocol과 다르다")
    if protocol.get("records_sha256") != v2.digest(v2.RECORDS):
        issues.append("records 해시가 protocol과 다르다")
    expected = {n: v2.digest(v2.SPLITS / f"v2-{n}.json") for n in v2.SPLIT_NAMES}
    if protocol.get("split_sha256") != expected:
        issues.append("split 해시/목록이 protocol과 다르다")
    for name, sha in protocol["baseline_input_sha256"].items():
        if v2.digest(v2.ROOT / name) != sha:
            issues.append(f"baseline 입력이 바뀌었다: {name}")
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    create_protocol(args.spec, args.out)
    print("protocol saved:", args.out)
