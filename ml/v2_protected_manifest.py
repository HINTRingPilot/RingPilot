"""보호 대상 파일의 목록과 SHA-256을 읽기 전용으로 기록하고, 나중에 다시 해시해 차이를 보고한다.

사용: ml/.venv/Scripts/python.exe ml/v2_protected_manifest.py <명령>
  create --out <manifest.json>   보호 대상을 해시해 manifest를 새로 만든다(이미 있으면 거부).
  check  --manifest <manifest>   다시 해시해 추가·삭제·변경 파일을 보고한다(차이가 있으면 종료 코드 1).

보호 대상 파일은 'rb'로 읽기만 한다. 쓰는 파일은 --out 하나뿐이며 배타적 생성('x')이라 덮어쓰지 않는다.

해시 정의:
  텍스트 파일(.csv .json .txt .md .py .ino .java .gradle .ps1 .js .log 등, 확장자 없는 파일은 내용으로 판단):
      CRLF를 LF로 바꾼 뒤 SHA-256. ml/v2.py의 digest()와 같은 정의다(저장소는 core.autocrlf=true).
  바이너리 파일(.npz .mp4 .mov .png 등): 원시 바이트 SHA-256.
  각 파일에 어느 규칙을 썼는지 manifest의 rule 필드에 남긴다("text-crlf-to-lf" 또는 "binary-raw").
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import v2

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_VERSION = 1

# 보호 대상(루트 기준 glob). 새 진단 출력 폴더와 계획 파일은 넣지 않는다.
PROTECTED_PATTERNS = (
    "data/sessions/phone-20261025-*/**/*",     # excluded/ 와 session_info*.txt 포함
    "data/annotations/ble-v2/**/*",
    "data/splits/v2-*.json",
    "docs/experiments/ble-v2/results/**/*",     # protocol.json 과 V2-*-cal 폴더 전체
    "ml/runs/V2-*-cal/**/*",                    # Git 제외 폴더지만 포함한다
    "기획서 원안.txt",
    "ml/model.py",
    "ml/v2.py",
    "ml/v2_cal.py",
    "ml/v2_diag.py",
)

TEXT_EXTENSIONS = {".csv", ".json", ".txt", ".md", ".py", ".ino", ".java", ".gradle", ".ps1", ".js",
                   ".log", ".kt", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".html", ".css",
                   ".sh", ".bat", ".properties"}
BINARY_EXTENSIONS = {".npz", ".npy", ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip",
                     ".pdf", ".keras", ".h5", ".bin", ".apk", ".jar"}
RULE_TEXT = "text-crlf-to-lf"
RULE_BINARY = "binary-raw"


def choose_rule(path):
    """확장자로 규칙을 정한다. 목록에 없는 확장자(또는 확장자 없음)는 NUL 바이트가 있으면 바이너리로 본다."""
    ext = Path(path).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return RULE_TEXT
    if ext in BINARY_EXTENSIONS:
        return RULE_BINARY
    with open(path, "rb") as f:
        return RULE_BINARY if b"\0" in f.read() else RULE_TEXT


def hash_file(path, rule):
    if rule == RULE_TEXT:
        return v2.digest(path)
    if rule == RULE_BINARY:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    raise ValueError(f"알 수 없는 해시 규칙: {rule}")


def expand(root, patterns):
    """패턴에 걸리는 파일의 루트 기준 상대 경로(/ 구분, 정렬)."""
    root = Path(root)
    found = set()
    for pattern in patterns:
        for p in root.glob(pattern):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def snapshot(root, rel_paths, rules=None):
    """{상대 경로: {sha256, bytes, rule}}. rules가 주어지면 그 경로의 규칙을 그대로 쓴다."""
    root = Path(root)
    out = {}
    for rel in rel_paths:
        full = root / rel
        rule = (rules or {}).get(rel) or choose_rule(full)
        out[rel] = {"sha256": hash_file(full, rule), "bytes": full.stat().st_size, "rule": rule}
    return out


def git_info(root):
    def run(*args):
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
        return r.stdout if r.returncode == 0 else None
    head = run("rev-parse", "HEAD")
    # 경로를 따옴표로 감싸지 않도록 core.quotepath=false
    status = run("-c", "core.quotepath=false", "status", "--short")
    return {
        "git_head": head.strip() if head else None,
        "git_status_short": status.splitlines() if status is not None else None,
    }


def build_manifest(root, patterns=PROTECTED_PATTERNS, with_git=True):
    root = Path(root)
    files = snapshot(root, expand(root, patterns))
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "created_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "purpose": "V2 완료 주석 타당성 확인(작업 A) 전에 기존 보호 대상의 상태를 읽기 전용으로 고정한다.",
        "hash_note": ("텍스트 파일은 CRLF를 LF로 바꾼 뒤 SHA-256(ml/v2.py digest와 같은 정의), "
                      "바이너리 파일은 원시 바이트 SHA-256. 이 manifest는 CRLF→LF 텍스트 해시로 만들었다. "
                      "파일별 규칙은 rule 필드."),
        "protected_patterns": list(patterns),
        "excluded_by_design": ["docs/experiments/ble-v2/diagnostics/completion-review-01/ (새 진단 출력)",
                               "docs/superpowers/ (계획 파일)"],
        "file_count": len(files),
        "files": [{"path": rel, **info} for rel, info in files.items()],
    }
    if with_git:
        manifest.update(git_info(root))
    return manifest


def compare(root, manifest):
    """manifest와 현재 디스크를 비교한다. {'added','removed','changed'} 경로 목록."""
    root = Path(root)
    recorded = {f["path"]: f for f in manifest["files"]}
    rules = {p: f["rule"] for p, f in recorded.items()}
    current_paths = set(expand(root, manifest["protected_patterns"]))
    added = sorted(current_paths - recorded.keys())
    removed = sorted(p for p in recorded if not (root / p).is_file())
    changed = []
    for rel in sorted(set(recorded) - set(removed)):
        if hash_file(root / rel, rules[rel]) != recorded[rel]["sha256"]:
            changed.append(rel)
    return {"added": added, "removed": removed, "changed": changed}


def write_new(path, value):
    """배타적 생성: 이미 있으면 FileExistsError. 항상 LF."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with open(path, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)


def cmd_create(args):
    out = Path(args.out)
    if out.exists():
        print(f"거부: 이미 있는 manifest는 덮어쓰지 않는다: {out}", file=sys.stderr)
        return 2
    patterns = tuple(args.pattern) if args.pattern else PROTECTED_PATTERNS
    manifest = build_manifest(args.root, patterns)
    try:
        write_new(out, manifest)
    except FileExistsError:
        print(f"거부: 이미 있는 manifest는 덮어쓰지 않는다: {out}", file=sys.stderr)
        return 2
    print(f"manifest 저장: {out} ({manifest['file_count']}개 파일)")
    return 0


def cmd_check(args):
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    diff = compare(args.root, manifest)
    total = sum(len(v) for v in diff.values())
    print(f"기록된 파일 {manifest['file_count']}개 / 추가 {len(diff['added'])} / 삭제 {len(diff['removed'])} / 변경 {len(diff['changed'])}")
    for key in ("added", "removed", "changed"):
        for p in diff[key]:
            print(f"  {key}: {p}")
    print("차이 없음" if total == 0 else f"차이 {total}건")
    return 0 if total == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT), help="기준 폴더(기본: 프로젝트 루트)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--out", required=True)
    c.add_argument("--pattern", action="append", help="보호 대상 glob(여러 번 가능, 기본은 고정 목록)")
    c.set_defaults(func=cmd_create)
    k = sub.add_parser("check")
    k.add_argument("--manifest", required=True)
    k.set_defaults(func=cmd_check)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
