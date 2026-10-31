"""간격별 연속 동작 인식률(실험 consecutive-01). 저장된 fold 모델의 검증 세션 클립을 이어 붙여, 앞 동작 뒤 뒤 동작이 발행되는지 잰다.

사용: ml/.venv/Scripts/python.exe ml/v2_seq_eval.py --tag T --label L --split S-P5 --epoch 60 [--out 결과.json]
뒤 동작이 [뒤 동작 끝점, r+300 ms]에 정답 방향으로 발행되고, 앞 동작 정답 구간 뒤로 다른 방향 발행이 없으면 성공이다.
앞 동작은 같은 검증 세션의 다른 클립에서 고정 난수로 고르므로 조건끼리 같은 쌍을 쓴다. 영점은 클립 방식(첫 정지 구간)이다.
"""
import argparse
import json
from pathlib import Path

import numpy as np

import v2
import v2_return as vr
import v2_stream as vs

GAPS_MS = (0, 100, 200, 300, 500, 800, 1200)
OUT = Path(__file__).resolve().parents[1] / "docs/experiments/ble-v2/consecutive-01"
CL = list(vr.CLASSES)


def pairs_for(paths, starts):
    usable = [p for p in paths if starts[p] >= vr.PRECUE_SAMPLES * vr.SAMPLE_MS]
    rng = np.random.default_rng(20261031)
    return [(p, usable[int(rng.integers(len(usable)))]) for p in usable]


def evaluate_fold(model, prep, val_paths, nb, starts, gap):
    hits = total = 0
    wrong = 0
    xs, spans = [], []
    for path, prior in pairs_for(val_paths, starts):
        if prior == path:
            continue
        ts, raw = v2.read_sensor(v2.ROOT / path)
        _, prior_raw = v2.read_sensor(v2.ROOT / prior)
        n = nb[path]
        joined, valid, r2, prior_r2 = vr.compose_sequence(raw, starts[path], n["event_ms"], prior_raw, starts[prior], nb[prior]["event_ms"], gap, 100)
        if vr.positive_windows(r2, len(raw), valid) != vr.positive_windows(n["event_ms"], len(raw), len(raw)):
            continue
        shift = r2 - n["event_ms"]
        bias, static = vs.precue_estimates(joined)
        x, times = vs.stream_inputs(joined[:valid], ts[:valid], prep, bias[:valid], static[:valid])
        xs.append(x)
        spans.append((times, n["extreme_ms"] + shift, r2 + 300, prior_r2 + v2.POSITIVE_MS, CL.index(n["direction"])))
    scores = model.predict(np.concatenate(xs), batch_size=512, verbose=0)
    offset = 0
    for times, start, end, after, true in spans:
        events = v2.issue_events(times, scores[offset:offset + len(times)])
        offset += len(times)
        later = [e for e in events if e["timestamp_ms"] >= after]
        ok = any(e["class_index"] == true and start <= e["timestamp_ms"] <= end for e in later)
        bad = any(e["class_index"] != true for e in later)
        total += 1
        hits += int(ok and not bad)
        wrong += int(bad)
    return hits, wrong, total


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--split", required=True)
    p.add_argument("--epoch", type=int, default=60)
    p.add_argument("--seeds", type=int, nargs="+", default=list(v2.SEEDS))
    p.add_argument("--out")
    args = p.parse_args()
    tf = v2.configure_tf()
    _, by_path, nb = vr.load()
    split = v2.load_split(args.split)
    starts = vr.motion_starts()
    table = {}
    for gap in GAPS_MS:
        per_seed = []
        for seed in args.seeds:
            h = w = t = 0
            for k, fold in enumerate(split["cv"]["folds"]):
                path = vr.model_dir(args.label, args.split, seed, k, args.tag)
                model = tf.keras.models.load_model(path / f"e{args.epoch}.keras")
                prep = json.loads((path / "prep.json").read_text(encoding="utf-8"))
                val = [q for q in fold["validation_sources"] if by_path[q]["completion_ms"] is not None]
                a, b, c = evaluate_fold(model, prep, val, nb, starts, gap)
                h, w, t = h + a, w + b, t + c
            per_seed.append({"seed": seed, "hit": h, "wrong": w, "total": t})
        table[str(gap)] = per_seed
        rate = [s["hit"] / s["total"] for s in per_seed]
        print(f"{args.label} {args.split} E{args.epoch} gap {gap:5d} ms: 성공 {np.mean(rate)*100:5.1f}% {[round(x*100,1) for x in rate]} 다른 방향 {sum(s['wrong'] for s in per_seed)} (쌍 {per_seed[0]['total']})", flush=True)
    if args.out:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / args.out).write_text(json.dumps({"label": args.label, "split": args.split, "epoch": args.epoch, "tag": args.tag, "gaps": table, "created_kst": v2.now()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
