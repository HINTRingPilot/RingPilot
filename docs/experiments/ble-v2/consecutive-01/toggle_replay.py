"""현재 앱 동작(좌우 = 토글)으로 저장 fold 모델을 재생해 채점한다. 결과는 인자로 준 경로에만 쓴다.
모드: none(안 지움), final(현재 v2_erase·보드와 같은 지우기), old(b3b06ca의 샘플별 영점 지우기)."""
import collections
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))

import numpy as np

import v2
import v2_erase as ve
import v2_return as vr

OUT = Path(sys.argv[1])
TAG = "seq-local-20261101"
EPOCH = 60

src = (ROOT / "ml/v2_erase.py").read_text(encoding="utf-8")
assert "raw[:end + 1, 3:6] = bias[end]" in src
old = types.ModuleType("v2_erase_old")
old.__file__ = str(ROOT / "ml/v2_erase.py")
exec(compile(src.replace("raw[:end + 1, 3:6] = bias[end]", "raw[:end + 1, 3:6] = bias[:end + 1]"), "v2_erase_old", "exec"), old.__dict__)

VARIANTS = {"none": (ve, None), "final": (ve, 3), "old": (old, 3)}
NAMES = list(vr.CLASSES)
print("classes", NAMES, flush=True)
TOGGLE = {NAMES.index("LEFT"), NAMES.index("RIGHT")}


def blank():
    return collections.Counter()


def score_clip(t, ev, spec, direction):
    toggles = sum(e["class_index"] in TOGGLE for e in ev)
    moves = [e["class_index"] for e in ev if e["class_index"] not in TOGGLE]
    if spec is None:
        t["bg_clips"] += 1
        t["bg_events"] += len(ev)
        t["bg_toggles"] += toggles
        t["bg_moves"] += len(moves)
        t["bg_mode_left_flipped"] += toggles % 2
        return
    true = NAMES.index(direction)
    if true in TOGGLE:
        t["lr_clips"] += 1
        t[f"lr_toggles_{min(toggles, 3)}"] += 1
        t["lr_exactly_one_clean"] += int(toggles == 1 and not moves)
        t["lr_spurious_move"] += int(bool(moves))
        # 네 방향 채점 기준 "다른 방향 없음"인데 토글이 짝수인 경우
        t["lr_same_dir_multi"] += int(toggles >= 2 and len({e["class_index"] for e in ev}) == 1)
        t["lr_both_dirs"] += int(len({e["class_index"] for e in ev if e["class_index"] in TOGGLE}) == 2)
    else:
        t["ud_clips"] += 1
        t["ud_right_single"] += int(moves == [true] and toggles == 0)
        t["ud_any_toggle"] += int(toggles > 0)
        t["ud_mode_left_flipped"] += toggles % 2
        t["ud_opposite"] += int(any(m != true for m in moves))
        t["ud_miss"] += int(true not in moves)
        t["ud_multi_same"] += int(moves.count(true) >= 2)


def main():
    tf = v2.configure_tf()
    _, by_path, nb = vr.load()
    rec = np.loadtxt(ve.OUT / "continuous.1.csv", delimiter=",", skiprows=1)
    rec_ts, rec_raw = rec[:, 0], rec[:, 1:]
    gestures = json.loads((ve.OUT / "consec_ablation.json").read_text(encoding="utf-8"))
    result = {"tag": TAG, "epoch": EPOCH, "splits": {}}
    for sp in ("S-P3", "S-P5"):
        split = v2.load_split(sp)
        tot = {m: blank() for m in VARIANTS}
        rec_tot = {m: blank() for m in VARIANTS}
        for seed in v2.SEEDS:
            for k, fold in enumerate(split["cv"]["folds"]):
                path = vr.model_dir(ve.LABEL, sp, seed, k, TAG)
                model = tf.keras.models.load_model(path / f"e{EPOCH}.keras")
                prep = json.loads((path / "prep.json").read_text(encoding="utf-8"))
                predict = lambda x: model.predict_on_batch(x)
                for name, (mod, mode) in VARIANTS.items():
                    t = tot[name]
                    for q in fold["validation_sources"]:
                        ts, raw = v2.read_sensor(ROOT / q)
                        bias, static = mod.vs.precue_estimates(raw)
                        ev = mod.replay(predict, raw, ts, prep, bias, static, mode)
                        spec = by_path[q]["completion_ms"]
                        direction = nb[q]["direction"] if spec is not None else None
                        score_clip(t, ev, spec, direction)
                        if spec is not None:
                            c, _, _ = vr.classify(by_path[q], ev, vr.success_window(q, by_path, nb, "extreme_window"))
                            t["fourway_total"] += 1
                            t["fourway_clean"] += int(c.get("correct", 0) > 0 and len({e["class_index"] for e in ev}) == 1)
                    r = mod.eval_record(predict, prep, rec_raw, rec_ts, gestures, mode)
                    b, st = mod.vs.still_estimates(rec_raw)
                    ev = mod.replay(predict, rec_raw, rec_ts, prep, b, st, mode)
                    rt = rec_tot[name]
                    for part in ("fast", "middle", "easy"):
                        for key in ("right", "wrong", "n"):
                            rt[f"{part}_{key}"] += r[part][key]
                    rt["record_toggles"] += sum(e["class_index"] in TOGGLE for e in ev)
                    rt["record_moves"] += sum(e["class_index"] not in TOGGLE for e in ev)
                    rt["record_models_with_toggle"] += int(any(e["class_index"] in TOGGLE for e in ev))
                    rt["record_models"] += 1
                print(sp, seed, k, "done", flush=True)
                tf.keras.backend.clear_session()
        result["splits"][sp] = {m: {"clips": dict(tot[m]), "record": dict(rec_tot[m])} for m in VARIANTS}
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("finished", flush=True)


main()
