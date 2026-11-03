"""기존 지표와 같은 시간 구간으로 방향별 성능을 채점하고, 배경 클립의 토글 간격을 잰다. 인자로 준 경로에만 쓴다."""
import collections, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import numpy as np
import v2, v2_erase as ve, v2_return as vr
TAG, EPOCH = "seq-local-20261101", 60
N = list(vr.CLASSES); TOG = {N.index("LEFT"), N.index("RIGHT")}
tf = v2.configure_tf()
_, by_path, nb = vr.load()
res = {}
for sp in ("S-P3", "S-P5"):
    split = v2.load_split(sp)
    out = {}
    for name, mode in (("none", None), ("final", 3)):
        t = collections.Counter(); gaps = []; dur = []
        for seed in v2.SEEDS:
            for k, fold in enumerate(split["cv"]["folds"]):
                path = vr.model_dir(ve.LABEL, sp, seed, k, TAG)
                model = tf.keras.models.load_model(path / f"e{EPOCH}.keras")
                prep = json.loads((path / "prep.json").read_text(encoding="utf-8"))
                pred = lambda x: model.predict_on_batch(x)
                for q in fold["validation_sources"]:
                    ts, raw = v2.read_sensor(ROOT / q)
                    b, st = ve.vs.precue_estimates(raw)
                    ev = ve.replay(pred, raw, ts, prep, b, st, mode)
                    if by_path[q]["completion_ms"] is None:
                        tt = [e["timestamp_ms"] for e in ev if e["class_index"] in TOG]
                        dur.append(float(ts[-1] - ts[0]))
                        gaps += [b_ - a for a, b_ in zip(tt, tt[1:])]
                        t["bg_clips_ge2_toggles"] += int(len(tt) >= 2)
                        continue
                    d = nb[q]["direction"]
                    c, _, _ = vr.classify(by_path[q], ev, vr.success_window(q, by_path, nb, "extreme_window"))
                    clean = int(c.get("correct", 0) > 0 and len({e["class_index"] for e in ev}) == 1)
                    t[d + "_n"] += 1; t[d + "_clean"] += clean
                    win = vr.success_window(q, by_path, nb, "extreme_window")
                    # 좌우는 앱 기준: 구간 안에 토글이 있고 클립 전체 토글이 1번, 스와이프 없음
                    in_win = [e for e in ev if win[0] <= e["timestamp_ms"] <= win[1]]
                    if N.index(d) in TOG:
                        ok = sum(e["class_index"] in TOG for e in ev) == 1 and len(ev) == 1 and any(e["class_index"] in TOG for e in in_win)
                    else:
                        ok = len(ev) == 1 and ev[0]["class_index"] == N.index(d) and bool(in_win)
                    t[d + "_app_ok"] += int(ok)
                tf.keras.backend.clear_session()
        out[name] = {"counts": dict(t), "toggle_gaps_ms": sorted(gaps), "bg_clip_ms_median": float(np.median(dur))}
        print(sp, name, dict(t), "gaps", sorted(gaps), "dur", np.median(dur), flush=True)
    res[sp] = out
    Path(sys.argv[1]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
