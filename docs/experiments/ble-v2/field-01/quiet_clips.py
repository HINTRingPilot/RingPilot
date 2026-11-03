"""실험 field-01(2026-11-03). 사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/field-01/quiet_clips.py
quiet 지우기를 S-P5 저장 fold 모델(seq-20261031)로 단일 클립 정검출·배경 발행에서 확인한다."""
import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT / "ml"))
import v2, v2_return as vr, v2_stream as vs, v2_erase as ve
CL = vr.CLASSES

def make_replay(quiet, big=300):
    def replay(predict, raw, ts, prep, bias, static, mode, with_scores=False):
        raw = raw.copy(); W, S = prep["window"], prep["stride"]
        x, times = vs.stream_inputs(raw, ts, prep, bias, static); p = predict(x)
        ends = np.arange(W - 1, len(raw), S); ev = []; pending = None
        L, cand, cnt, nc = False, None, 0, 0; armed = False
        for d in range(len(times)):
            s = p[d]; top = int(np.argmax(s)); erase = False; end = ends[d]
            if L:
                nc = nc + 1 if top == 0 and s[0] >= .8 else 0
                if nc >= 2: L, cand, cnt, nc = False, None, 0, 0
            else:
                mg = np.sort(s)[-1] - np.sort(s)[-2]
                if top and s[top] >= .8 and mg >= .2:
                    cnt = cnt + 1 if top == cand else 1; cand = top
                    if cnt >= 2:
                        ev.append({"timestamp_ms": int(times[d]), "class_index": top, "score": float(s[top])})
                        L, cand, cnt, nc = True, None, 0, 0; pending = d + 3; armed = False
                else: cand, cnt = None, 0
            if quiet and not L and pending is None:
                if np.abs(raw[end - S + 1:end + 1, 3:6] - bias[end]).max() > big: armed = True
                q = quiet // 10
                if armed and np.abs(raw[end - q + 1:end + 1, 3:6] - bias[end]).max() < 30:
                    erase, armed = True, False
            if pending is not None and d >= pending: erase, pending = True, None
            if erase:
                raw[:end + 1, 3:6] = bias[end]
                last = int(np.searchsorted(ends, end + W - 1, side="right"))
                if d + 1 < last:
                    lo = ends[d + 1] - (W - 1); hi = ends[last - 1] + 1
                    redo, _ = vs.stream_inputs(raw[lo:hi], ts[lo:hi], prep, bias[lo:hi], static[lo:hi]); p[d + 1:last] = predict(redo)
        return ev
    return replay

tf = v2.configure_tf(); _, by_path, nb = vr.load()
sp, tag = "S-P5", "seq-20261031"; split = v2.load_split(sp); epoch = ve.selected_epoch(tag, sp, by_path, nb)
print(sp, "E", epoch, flush=True)
tot = {q: {"clean": 0, "total": 0, "other_dir": 0, "bg_events": 0, "bg_clips": 0} for q in (0, 150)}
per_seed = {q: [] for q in tot}
for seed in v2.SEEDS:
    st = {q: {"clean": 0, "total": 0, "other_dir": 0, "bg_events": 0, "bg_clips": 0} for q in tot}
    for k, fold in enumerate(split["cv"]["folds"]):
        path = vr.model_dir(ve.LABEL, sp, seed, k, tag)
        model = tf.keras.models.load_model(path / f"e{epoch}.keras"); prep = json.loads((path / "prep.json").read_text(encoding="utf-8"))
        pr = lambda x: model.predict_on_batch(x)
        for q in tot:
            ve.replay = make_replay(q)
            c = ve.eval_clips(pr, prep, fold["validation_sources"], by_path, nb, 3)
            for key in c: st[q][key] += c[key]
    for q in tot:
        per_seed[q].append(st[q]["clean"] / st[q]["total"] * 100)
        for key in st[q]: tot[q][key] += st[q][key]
    print("seed", seed, {q: (st[q]["clean"], st[q]["total"], st[q]["other_dir"], st[q]["bg_events"]) for q in tot}, flush=True)
for q in tot:
    t = tot[q]; print(f"quiet{q}: 정검출 {np.mean(per_seed[q]):.2f}% (seed별 {np.round(per_seed[q],1).tolist()}) 다른방향 {t['other_dir']} 배경발행 {t['bg_events']}/{t['bg_clips']}")
