"""파이썬(Keras)과 C의 판정 1회 시간을 같은 PC·같은 창에서 비교한다(실험 latency-01). 정확도는 v2_export_c.py check가 본다.

사용: RINGPILOT_CC=<컴파일러> ml/.venv/Scripts/python.exe ml/v2_latency.py --tag T --out <결과 이름>
경로: 입력 처리(원시 자이로 → 모델 입력), 추론(모델 입력 → 점수). 창은 한 번에 하나씩 넣는다(실시간과 같다).
다른 프로그램을 돌리지 않은 상태에서 잰다. 보드 측정은 firmware/gesture_infer의 시리얼 명령 l로 하고 같은 문서에 적는다.
"""
import argparse
import json
import platform
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

import v2
import v2_export_c as ex
import v2_return as vr
import v2_stream as vs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/experiments/ble-v2/latency-01/results"
BUDGET_MS = 50.0
WARMUP = 50


def stats_ms(values_ns):
    a = np.asarray(values_ns, dtype=np.float64) / 1e6
    return {"n": int(a.size), "median_ms": float(np.median(a)), "p95_ms": float(np.percentile(a, 95)), "p99_ms": float(np.percentile(a, 99)),
            "max_ms": float(a.max()), "median_share_of_50ms": float(np.median(a) / BUDGET_MS)}


def load_windows(split, seed, fold, tag, label, limit):
    """검증 클립의 창(원시 6축, 영점, 모델 입력)을 고정 간격으로 limit개 고른다."""
    _, by_path, nb = vr.load()
    d, _ = vr.prepare_fold(label, by_path, nb, v2.load_split(split), fold)
    raws, biases, xs = [], [], []
    for record, x, _, _ in d["val"]:
        _, raw = v2.read_sensor(ROOT / record["source_path"])
        ends = np.arange(v2.WINDOW - 1, len(raw), v2.STRIDE)
        raws.append(np.stack([raw[e - (v2.WINDOW - 1):e + 1] for e in ends]))
        biases.append(np.tile(np.median(raw[:vr.PRECUE_SAMPLES, 3:6], axis=0), (len(ends), 1)))
        xs.append(x)
    raw, bias, x = np.concatenate(raws), np.concatenate(biases), np.concatenate(xs)
    pick = np.linspace(0, len(x) - 1, min(limit, len(x))).astype(int)
    return raw[pick], bias[pick], x[pick]


def time_python(model, prep, raw, bias, x):
    import tensorflow as tf
    ts = np.arange(v2.WINDOW) * prep["sample_ms"]
    prepare = []
    static = np.zeros((v2.WINDOW, 3))
    for r, b in zip(raw, bias):
        est = np.tile(b, (v2.WINDOW, 1))
        t0 = time.perf_counter_ns()
        vs.stream_inputs(r, ts, prep, est, static)
        prepare.append(time.perf_counter_ns() - t0)
    graph = tf.function(lambda one: model(one, training=False), input_signature=[tf.TensorSpec((1, v2.WINDOW, 6), tf.float32)])
    out = {"python_prepare": prepare[WARMUP:]}
    for name, fn in (("keras_eager", lambda one: model(one, training=False)), ("keras_tf_function", graph)):
        fn(tf.constant(x[:1]))
        times = []
        for one in x:
            tensor = tf.constant(one[None])
            t0 = time.perf_counter_ns()
            fn(tensor).numpy()
            times.append(time.perf_counter_ns() - t0)
        out[name] = times[WARMUP:]
    return out


def time_c(exe, raw, bias, work, passes):
    a, b = Path(work) / "time.in", Path(work) / "time.out"
    n = len(raw)
    np.concatenate([raw[:, :, 3:6].astype(np.float32).reshape(n, -1), bias.astype(np.float32)], axis=1).tofile(a)
    subprocess.run([str(exe), "time", str(a), str(b), str(passes)], check=True)
    t = np.fromfile(b, dtype="<u4").reshape(-1, 2)[WARMUP:]
    return {"c_prepare": t[:, 0], "c_predict": t[:, 1]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--split", default="S-P5")
    p.add_argument("--seed", type=int, default=20261021)
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--epoch", type=int, default=60)
    p.add_argument("--tag", required=True)
    p.add_argument("--label", default="newtcnrotwarpnoacc")
    p.add_argument("--windows", type=int, default=1000)
    p.add_argument("--c-passes", type=int, default=5)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    tf = v2.configure_tf()      # 학습과 같이 스레드 1개(보드도 코어 1개)
    path = vr.model_dir(args.label, args.split, args.seed, args.fold, args.tag)
    model = tf.keras.models.load_model(path / f"e{args.epoch}.keras")
    prep = json.loads((path / "prep.json").read_text(encoding="utf-8"))
    raw, bias, x = load_windows(args.split, args.seed, args.fold, args.tag, args.label, args.windows)
    with tempfile.TemporaryDirectory() as work:
        ex.write_header(model, prep, Path(work) / "gesture_weights.h")
        exe = Path(work) / "host_check.exe"
        ex.build_host(work, exe)
        c = time_c(exe, raw, bias, work, args.c_passes)
    py = time_python(model, prep, raw, bias, x)
    positions = ex.needed_positions(ex.dilations_of(model), prep["window"])
    result = {"experiment": "latency-01", "created_kst": v2.now(), "model": f"{args.label} {args.split} seed {args.seed} fold {args.fold} E{args.epoch}",
              "windows": len(x), "warmup_discarded": WARMUP, "c_passes": args.c_passes,
              "macs_c": ex.mac_count(positions, ex.dilations_of(model), 6, 16, 5), "macs_keras_full": 675920,
              "env": {**vr.runtime_env(), "machine": platform.machine(), "processor": platform.processor(), "tf_threads": 1,
                      "c_compiler": " ".join(ex.find_cc()), "c_flags": ex.HOST_FLAGS},
              "paths": {k: stats_ms(v) for k, v in {**py, **c}.items()}}
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{args.out}.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, s in result["paths"].items():
        print(f"{name:20} median {s['median_ms']:9.4f} ms  p95 {s['p95_ms']:9.4f}  p99 {s['p99_ms']:9.4f}  max {s['max_ms']:9.4f}  (n={s['n']})")
    print(target)


if __name__ == "__main__":
    main()
