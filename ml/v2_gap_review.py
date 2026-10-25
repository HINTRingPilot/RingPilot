"""BLE v2: 완료 시각 e와 센서 기반 주동작 종료의 간격이 조기·정검출 발행과 어떤 관계인지 본다.

저장된 발행 로그(seed-*.json)와 후보 주석만 읽는다. 학습·평가를 하지 않고 기존 파일을 쓰지 않는다.
출력은 새 폴더에만 쓰고, 이미 있으면 거부한다.

  ml/.venv/Scripts/python.exe ml/v2_gap_review.py [--out docs/experiments/ble-v2/diagnostics/completion-review-01/gap-vs-early]

간격(gap) = completion_ms − main_motion_end_ms. 둘 다 같은 자동 도구가 센서에서 계산한 값이며 독립된 정답이 아니다.
관계는 관찰일 뿐이고 원인을 보이지 않는다(간격이 큰 클립은 다른 점에서도 다를 수 있다).
"""

import argparse
from pathlib import Path

import numpy as np

import v2
import v2_diag
from v2 import DOC, ROOT, digest, dump, now

GAP_BINS = ((0, 100), (100, 200), (200, 300), (300, 100000))
SPLITS = v2_diag.SPLITS


def gap_ms(annotation):
    return annotation["completion_ms"] - annotation["main_motion_end_ms"]


def bin_of(gap, bins=GAP_BINS):
    for lo, hi in bins:
        if lo <= gap < hi:
            return (lo, hi)
    return None


def bin_name(b):
    return f"{b[0]}~{'' if b[1] >= 100000 else b[1]}"


def spearman(x, y):
    """순위 상관(동순위는 평균 순위). 값이 상수이면 None."""
    def ranks(v):
        v = np.asarray(v, dtype=float)
        order = np.argsort(v, kind="mergesort")
        r = np.empty(len(v))
        r[order] = np.arange(len(v), dtype=float)
        for value in np.unique(v):
            idx = v == value
            r[idx] = r[idx].mean()
        return r
    if len(x) < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    return float(np.corrcoef(ranks(x), ranks(y))[0, 1])


def clip_table(seed_results, epoch, ann):
    """클립마다 5 seed 중 조기 발행·정검출·발행이 있었던 seed의 비율."""
    per_clip = {}
    for r in seed_results:
        for f in r["folds"]:
            for p in f["per_epoch"][str(epoch)]["per_source"]:
                if p["completion_ms"] is None:
                    continue
                c = per_clip.setdefault(p["source_path"], {"n": 0, "early": 0, "correct": 0, "emitted": 0})
                c["n"] += 1
                c["early"] += any(e["kind"] == "early" for e in p["events"])
                c["correct"] += p["counts"].get("correct", 0) > 0
                c["emitted"] += bool(p["events"])
    rows = []
    for path, c in per_clip.items():
        a = ann[path]
        rows.append({"source_path": path, "gap_ms": gap_ms(a), "n_seeds": c["n"], "early_frac": c["early"] / c["n"],
                     "correct_frac": c["correct"] / c["n"], "emitted_frac": c["emitted"] / c["n"]})
    return rows


def by_gap_bin(rows, bins=GAP_BINS):
    out = {}
    for b in bins:
        sel = [r for r in rows if bin_of(r["gap_ms"], bins) == b]
        pairs = sum(r["n_seeds"] for r in sel)
        agg = lambda key: sum(r[key] * r["n_seeds"] for r in sel) / pairs if pairs else None
        out[bin_name(b)] = {"clips": len(sel), "clip_seed_pairs": pairs, "early": agg("early_frac"),
                            "correct": agg("correct_frac"), "emitted": agg("emitted_frac")}
    return out


def analyse(split, epoch, ann):
    _, seed_results, saved, _ = v2_diag.load_run(split)
    rows = clip_table(seed_results, epoch, ann)
    g = [r["gap_ms"] for r in rows]
    return {"split": split, "epoch": int(epoch), "chosen": str(saved["chosen_E"]) == str(epoch), "n_clips": len(rows),
            "by_gap_bin": by_gap_bin(rows),
            "spearman_gap_vs_early": spearman(g, [r["early_frac"] for r in rows]),
            "spearman_gap_vs_correct": spearman(g, [r["correct_frac"] for r in rows]),
            "spearman_gap_vs_emitted": spearman(g, [r["emitted_frac"] for r in rows])}


def render(report):
    L = ["# 완료 시각 e와 주동작 종료의 간격 대 조기·정검출 발행", "",
         f"생성: {report['created_kst']}. `ml/v2_gap_review.py`가 저장된 발행 로그와 후보 주석만 읽어 만들었다. 학습·평가를 하지 않았고 기존 파일을 쓰지 않았다.", "",
         "간격 = e − `main_motion_end_ms`(ms). 둘 다 같은 자동 센서 도구의 값이라 독립된 정답이 아니다. "
         "각 칸은 클립×seed 쌍의 비율이며 5 seed가 같은 클립을 반복해 보므로 독립 표본이 아니다. "
         "**관찰된 관계일 뿐 원인을 보이지 않는다**(간격이 큰 클립은 다른 점에서도 다를 수 있다). "
         f"분할 {len(report['runs'])}개 × 선택 E와 E=1·60. 순위 상관은 클립 단위(5 seed 평균 비율)다.", ""]
    for row in report["runs"]:
        tag = "선택 E" if row["chosen"] else ""
        L += [f"## {row['split']} E={row['epoch']} {tag}".rstrip(), "",
              "| 간격(ms) | 클립 수 | 조기 발행 있음 | 정검출 있음 | 발행 있음 |", "|---|---:|---:|---:|---:|"]
        for name, b in row["by_gap_bin"].items():
            f = lambda x: "—" if x is None else f"{100 * x:.1f}%"
            L.append(f"| {name} | {b['clips']} | {f(b['early'])} | {f(b['correct'])} | {f(b['emitted'])} |")
        fmt = lambda x: "—" if x is None else f"{x:+.2f}"
        L += ["", f"간격과의 순위 상관(클립 {row['n_clips']}개): 조기 {fmt(row['spearman_gap_vs_early'])}, "
                  f"정검출 {fmt(row['spearman_gap_vs_correct'])}, 발행 {fmt(row['spearman_gap_vs_emitted'])}", ""]
    return "\n".join(L) + "\n"


def main(out_dir):
    out_dir = Path(out_dir)
    targets = [out_dir / "gap-vs-early.json", out_dir / "gap-vs-early.md"]
    for t in targets:
        if t.exists():
            raise FileExistsError(f"{t}가 이미 있다. 덮어쓰지 않는다")
    ann = v2_diag.load_annotations()
    report = {"created_kst": now(), "tool": "ml/v2_gap_review.py", "tool_sha256": digest(ROOT / "ml/v2_gap_review.py"),
              "gap_bins_ms": [list(b) for b in GAP_BINS], "runs": []}
    for s in SPLITS:
        _, _, saved, _ = v2_diag.load_run(s)
        for e in sorted({str(saved["chosen_E"]), "1", "60"}, key=int):
            report["runs"].append(analyse(s, e, ann))
    dump(targets[0], report)
    targets[1].write_bytes(render(report).encode("utf-8"))
    print("wrote", targets[0].name, targets[1].name)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(DOC / "diagnostics/completion-review-01/gap-vs-early"))
    main(p.parse_args().out)
