"""저장한 TCN 모델을 C 헤더로 내보내고, firmware/gesture_infer/src의 C 코드가 파이썬과 같은지 확인한다(계획 Task 7a).

마지막 시점 출력에 필요한 칸만 계산한다. 기본 dilation에서 블록별 93·45·21·9·3·1칸이다.

사용 (ml/.venv/Scripts/python.exe ml/v2_export_c.py <명령>):
  export <모델.keras> <prep.json> [출력.h]                 가중치·전처리 값·계산 칸 표 헤더 작성(기본은 스케치의 src)
  check --split S-P5 --seed N --fold K --epoch E --tag T  실제 검증 클립으로 C(PC 빌드)와 Keras 비교(클립·연속 스트림)
  verify <모델.keras> <prep.json>                          전체 클립을 이어 붙인 연속 스트림으로 C(PC 빌드)와 Keras 비교
C 컴파일러: RINGPILOT_CC(실행 경로 또는 추가 인수가 있는 명령) 또는 PATH의 gcc·clang.
공백 경로는 큰따옴표로 감싼다. Windows는 CommandLineToArgvW, 다른 OS는 POSIX 인용 규칙을 쓴다(shell은 실행하지 않음).
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import v2

ROOT = Path(__file__).resolve().parents[1]
C_DIR = ROOT / "firmware/gesture_infer/src"
HOST_SOURCE = ROOT / "firmware/gesture_host/host_check.c"
GYRO = slice(3, 6)
INPUT_CHANNELS = ["gyrX", "gyrY", "gyrZ", "angX", "angY", "angZ"]
KERNEL = 3


def needed_positions(dilations, window):
    """블록별로 계산할 시점(오름차순). 마지막 블록의 마지막 시점에서 거슬러 올라간다. 창 앞으로 넘어간 칸은 패딩이라 뺀다."""
    needed = [window - 1]
    out = []
    for d in reversed(dilations):
        out.append(needed)
        needed = sorted({t - k * d for t in needed for k in range(KERNEL) if t - k * d >= 0})
    return out[::-1]


def source_table(dilations, window):
    """블록·칸마다 입력 3개(오래된 시점 먼저)가 앞 블록 출력의 몇 번째 칸인지. 첫 블록은 입력의 시점 번호, 패딩은 -1."""
    positions = needed_positions(dilations, window)
    rows = []
    for b, d in enumerate(dilations):
        index = {t: t for t in range(window)} if b == 0 else {t: i for i, t in enumerate(positions[b - 1])}
        for t in positions[b]:
            for k in range(KERNEL - 1, -1, -1):           # Keras 커널 0번이 가장 오래된 시점(t − 2d)이다
                rows.append(index[t - k * d] if t - k * d >= 0 else -1)
    return positions, rows


def mac_count(positions, dilations, channels, filters, classes):
    """C 추론의 곱셈-덧셈 수(패딩으로 건너뛰는 칸은 뺀다)."""
    total = len(positions[0]) * channels * filters      # 첫 블록 1×1 맞춤
    for b, d in enumerate(dilations):
        inputs = channels if b == 0 else filters
        total += sum(1 for t in positions[b] for k in range(KERNEL) if t - k * d >= 0) * inputs * filters
    return total + filters * classes


def c_floats(values):
    a = np.asarray(values, dtype=np.float32).ravel()
    lines = [", ".join(f"{float(v):.9e}f" for v in a[i:i + 6]) for i in range(0, len(a), 6)]
    return "{\n  " + ",\n  ".join(lines) + "\n}"


def dilations_of(model):
    return [layer.dilation_rate[0] for layer in model.layers if layer.name.endswith("_conv")]


def write_header(model, prep, path, source=""):
    if prep["input_channels"] != INPUT_CHANNELS:
        raise ValueError(f"C 입력 처리는 {INPUT_CHANNELS}만 지원한다: {prep['input_channels']}")
    dilations = dilations_of(model)
    window, classes = prep["window"], len(prep["classes"])
    conv = [model.get_layer(f"block{i + 1}_conv").get_weights() for i in range(len(dilations))]
    filters = conv[0][1].size
    match_kernel, match_bias = model.get_layer("block1_match").get_weights()
    dense_kernel, dense_bias = model.get_layer("event").get_weights()
    positions, sources = source_table(dilations, window)
    total = sum(len(p) for p in positions)
    text = f"""/* ml/v2_export_c.py가 만든 파일. 직접 고치지 않는다. 모델: {source or '지정 없음'} */
#ifndef GESTURE_WEIGHTS_H
#define GESTURE_WEIGHTS_H

#include <stdint.h>

#define GT_WINDOW {window}
#define GT_CHANNELS {len(INPUT_CHANNELS)}
#define GT_FILTERS {filters}
#define GT_CLASSES {classes}
#define GT_BLOCKS {len(dilations)}
#define GT_TOTAL_POSITIONS {total}
#define GT_SAMPLE_S {prep['sample_ms'] / 1000:.9e}f
#define GT_ANGLE_SCALE_DEG {prep['angle_scale_deg']:.9e}f
#define GT_MACS {mac_count(positions, dilations, len(INPUT_CHANNELS), filters, classes)}

static const float gt_gyro_mean[3] = {c_floats(np.array(prep['norm_mean_6axis'])[GYRO])};
static const float gt_gyro_std[3] = {c_floats(np.array(prep['norm_std_6axis'])[GYRO])};
static const float gt_angle_mean[3] = {c_floats(prep['angle_mean'])};
static const float gt_angle_std[3] = {c_floats(prep['angle_std'])};
static const int16_t gt_block_positions[GT_BLOCKS] = {{{', '.join(str(len(p)) for p in positions)}}};
static const int16_t gt_sources[{len(sources)}] = {{{', '.join(str(s) for s in sources)}}};
static const float gt_conv_kernels[] = {c_floats(np.concatenate([k.ravel() for k, _ in conv]))};
static const float gt_conv_biases[] = {c_floats(np.concatenate([b for _, b in conv]))};
static const float gt_match_kernel[] = {c_floats(match_kernel)};
static const float gt_match_bias[] = {c_floats(match_bias)};
static const float gt_dense_kernel[] = {c_floats(dense_kernel)};
static const float gt_dense_bias[] = {c_floats(dense_bias)};

#endif
"""
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def table_predict(model, x, window=160):
    """gesture_tcn.c와 같은 표·같은 계산 순서의 float32 파이썬 대조 구현. C 빌드 없이 표와 가중치 배치를 확인한다."""
    dilations = dilations_of(model)
    positions, sources = source_table(dilations, window)
    match_kernel, match_bias = model.get_layer("block1_match").get_weights()
    dense_kernel, dense_bias = model.get_layer("event").get_weights()
    scores = []
    for one in np.asarray(x, dtype=np.float32):
        prev, cursor = one, 0
        for b in range(len(dilations)):
            kernel, bias = model.get_layer(f"block{b + 1}_conv").get_weights()
            cur = np.zeros((len(positions[b]), bias.size), dtype=np.float32)
            for p in range(len(positions[b])):
                src = sources[cursor:cursor + KERNEL]
                cursor += KERNEL
                h = bias.copy()
                for k in range(KERNEL):
                    if src[k] >= 0:
                        h = h + prev[src[k]] @ kernel[k]
                h = np.maximum(h, 0)
                skip = prev[src[2]] @ match_kernel[0] + match_bias if b == 0 else prev[src[2]]
                cur[p] = h + skip
            prev = cur
        logits = prev[0] @ dense_kernel + dense_bias
        e = np.exp(logits - logits.max())
        scores.append(e / e.sum())
    return np.array(scores, dtype=np.float32)


def compiler_command(command):
    """실행 파일의 공백·Windows backslash를 보존해 shell 없는 argv를 만든다."""
    command = command.strip()
    if not command:
        raise ValueError("RINGPILOT_CC가 비어 있다")
    candidate = command
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in "\"'":
        candidate = candidate[1:-1]
    if not candidate.strip():
        raise ValueError("RINGPILOT_CC 실행 파일이 비어 있다")
    try:
        if Path(candidate).is_file():
            return [candidate]
    except OSError:
        # 전체 명령을 경로로 탐색하다 길이 제한에 걸려도 argv 파싱은 가능하다.
        pass
    if os.name != "nt":
        parts = shlex.split(command, posix=True)
        if not parts or not parts[0].strip():
            raise ValueError("RINGPILOT_CC 실행 파일이 비어 있다")
        return parts

    # Windows의 parser는 닫히지 않은 따옴표도 허용하므로 잘못된 설정은 먼저 거절한다.
    quoted, slashes = False, 0
    for char in command:
        if char == "\\":
            slashes += 1
            continue
        if char == '"' and slashes % 2 == 0:
            quoted = not quoted
        slashes = 0
    if quoted:
        raise ValueError("RINGPILOT_CC의 큰따옴표가 닫히지 않았다")
    import ctypes
    from ctypes import wintypes
    parse = ctypes.WinDLL("shell32", use_last_error=True).CommandLineToArgvW
    parse.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
    free.argtypes = (ctypes.c_void_p,)
    free.restype = ctypes.c_void_p
    count = ctypes.c_int()
    argv = parse(command, ctypes.byref(count))
    if not argv:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        parts = [argv[index] for index in range(count.value)]
        if not parts or not parts[0].strip():
            raise ValueError("RINGPILOT_CC 실행 파일이 비어 있다")
        return parts
    finally:
        free(ctypes.cast(argv, ctypes.c_void_p))


def find_cc():
    env = os.environ.get("RINGPILOT_CC")
    if env is not None:
        return compiler_command(env)
    for name in ("gcc", "clang"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


HOST_FLAGS = ["-std=c99", "-D_POSIX_C_SOURCE=199309L", "-O2", "-Wall", "-Wextra", "-Werror"]


def build_host(header_dir, exe):
    """header_dir의 gesture_weights.h로 PC용 프로그램을 빌드한다. 같은 폴더 헤더가 먼저 읽히므로 소스를 header_dir로 복사해 빌드한다."""
    cc = find_cc()
    if cc is None:
        raise RuntimeError("C 컴파일러가 없다(RINGPILOT_CC 또는 gcc·clang)")
    header_dir = Path(header_dir)
    for name in ("gesture_tcn.c", "gesture_tcn.h", "gesture_runtime.c", "gesture_runtime.h"):
        shutil.copy(C_DIR / name, header_dir / name)
    subprocess.run([*cc, *HOST_FLAGS, f"-I{header_dir}", str(header_dir / "gesture_tcn.c"), str(header_dir / "gesture_runtime.c"),
                    str(HOST_SOURCE), "-lm", "-o", str(exe)], check=True)


def run_predict(exe, x, work):
    a, b = Path(work) / "predict.in", Path(work) / "predict.out"
    np.asarray(x, dtype=np.float32).tofile(a)
    subprocess.run([str(exe), "predict", str(a), str(b)], check=True)
    return np.fromfile(b, dtype=np.float32).reshape(len(x), -1)


def run_prepare(exe, gyro, bias, work):
    """창별 원시 자이로·영점 → (C 모델 입력, C 점수)."""
    a, b = Path(work) / "prep.in", Path(work) / "prep.out"
    n, window = gyro.shape[:2]
    np.concatenate([np.asarray(gyro, np.float32).reshape(n, -1), np.asarray(bias, np.float32)], axis=1).tofile(a)
    subprocess.run([str(exe), "prep", str(a), str(b)], check=True)
    out = np.fromfile(b, dtype=np.float32).reshape(n, -1)
    size = window * len(INPUT_CHANNELS)
    return out[:, :size].reshape(n, window, -1), out[:, size:]


def run_stream(exe, gyro, work):
    """샘플별 자이로 → (샘플 번호, 점수, 발행, 영점)."""
    a, b = Path(work) / "stream.in", Path(work) / "stream.out"
    np.asarray(gyro, dtype=np.float32).tofile(a)
    subprocess.run([str(exe), "stream", str(a), str(b)], check=True)
    out = np.fromfile(b, dtype=np.dtype([("index", "<i4"), ("scores", "<f4", 5), ("issued", "<i4"), ("bias", "<f4", 3)]))
    return out["index"], out["scores"], out["issued"], out["bias"]


def check_stream(exe, model, prep, clips, work):
    """클립을 이어 붙인 연속 스트림에서 C 런타임(온라인 영점·입력 처리·추론·발행 규칙)을 파이썬 기준과 비교한다."""
    import v2_erase as ve
    import v2_stream as vs
    raw = np.concatenate(clips)
    ts = np.arange(len(raw)) * prep["sample_ms"]
    bias, static = vs.still_estimates(raw)
    raw_events, times, keras = ve.replay(lambda x: model.predict_on_batch(x), raw, ts, prep, bias, static, ve.MODES["issue150"], with_scores=True,
                                       quiet_ms=ve.QUIET_MS)
    events = [(e["timestamp_ms"], e["class_index"]) for e in raw_events]
    index, scores, issued, c_bias = run_stream(exe, raw[:, GYRO], work)
    c_events = [(int(ts[i]), int(c)) for i, c in zip(index, issued) if c >= 0]
    return {"samples": len(raw), "decisions": len(times), "same_decision_times": [int(ts[i]) for i in index] == times,
            "max_error_bias": float(np.abs(c_bias - bias[index]).max()), "max_error_scores": float(np.abs(scores - keras).max()),
            "issued_events": len(events), "same_events": events == c_events}


def cmd_check(split_name, seed, fold, epoch, tag, label="newtcnrotwarpnoacc"):
    import tensorflow as tf
    import v2_return as vr
    model_path = vr.model_dir(label, split_name, seed, fold, tag)
    model = tf.keras.models.load_model(model_path / f"e{epoch}.keras")
    prep = json.loads((model_path / "prep.json").read_text(encoding="utf-8"))
    _, by_path, nb = vr.load()
    d, _ = vr.prepare_fold(label, by_path, nb, v2.load_split(split_name), fold)
    gyros, biases, keras_x, sizes, times, clips = [], [], [], [], [], []
    for record, x, _, meta in d["val"]:
        _, raw = v2.read_sensor(ROOT / record["source_path"])
        clips.append(raw)
        bias = np.median(raw[:vr.PRECUE_SAMPLES, GYRO], axis=0)
        ends = np.arange(v2.WINDOW - 1, len(raw), v2.STRIDE)
        gyros.append(np.stack([raw[e - (v2.WINDOW - 1):e + 1, GYRO] for e in ends]))
        biases.append(np.tile(bias, (len(ends), 1)))
        keras_x.append(x)
        sizes.append(len(x))
        times.append([m["timestamp_ms"] for m in meta])
    gyro, bias, x = np.concatenate(gyros), np.concatenate(biases), np.concatenate(keras_x)
    keras_scores = model(x, training=False).numpy()
    with tempfile.TemporaryDirectory() as work:
        write_header(model, prep, Path(work) / "gesture_weights.h")
        header = (Path(work) / "gesture_weights.h").read_text(encoding="utf-8")
        exe = Path(work) / "host_check.exe"
        build_host(work, exe)
        same_input = run_predict(exe, x, work)
        c_x, c_scores = run_prepare(exe, gyro, bias, work)
        stream = check_stream(exe, model, prep, clips, work)
    issues = lambda scores: [[(e["timestamp_ms"], e["class_index"]) for e in v2.issue_events(t, scores[o:o + n])]
                             for t, o, n in zip(times, np.cumsum([0, *sizes[:-1]]), sizes)]    # 시각·방향만 비교(점수 값은 소수점 차이가 있다)
    keras_events, c_events = issues(keras_scores), issues(c_scores)
    positions = needed_positions(dilations_of(model), prep["window"])
    result = {"model": f"{label} {split_name} seed {seed} fold {fold} E{epoch}", "clips": len(sizes), "windows": len(x),
              "positions_per_block": [len(p) for p in positions],
              "macs": mac_count(positions, dilations_of(model), len(INPUT_CHANNELS), model.get_layer("event").get_weights()[0].shape[0],
                                len(prep["classes"])),
              "max_error_model_only": float(np.abs(same_input - keras_scores).max()),
              "max_error_input": float(np.abs(c_x - x).max()),
              "max_error_full_pipeline": float(np.abs(c_scores - keras_scores).max()),
              "clips_with_different_events": sum(a != b for a, b in zip(keras_events, c_events)),
              "issued_events": sum(len(e) for e in keras_events), "header_bytes": len(header.encode("utf-8")),
              "stream": stream}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def cmd_verify(model_path, prep_path):
    """학습에 쓴 클립도 포함한다. 성능이 아니라 C와 Keras가 같은지만 본다."""
    import tensorflow as tf
    model = tf.keras.models.load_model(model_path)
    prep = json.loads(Path(prep_path).read_text(encoding="utf-8"))
    _, by_path = v2.load_records()
    clips = [v2.read_sensor(ROOT / p)[1] for p in sorted(by_path)]
    with tempfile.TemporaryDirectory() as work:
        write_header(model, prep, Path(work) / "gesture_weights.h")
        exe = Path(work) / "host_check.exe"
        build_host(work, exe)
        result = check_stream(exe, model, prep, clips, work)
    print(json.dumps({"clips": len(clips), **result}, ensure_ascii=False, indent=2))
    return result


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("model")
    e.add_argument("prep")
    e.add_argument("out", nargs="?", default=str(C_DIR / "gesture_weights.h"))
    e.add_argument("--source", default="")
    y = sub.add_parser("verify")
    y.add_argument("model")
    y.add_argument("prep")
    c = sub.add_parser("check")
    c.add_argument("--split", default="S-P5")
    c.add_argument("--seed", type=int, default=20261021)
    c.add_argument("--fold", type=int, default=0)
    c.add_argument("--epoch", type=int, default=60)
    c.add_argument("--tag")
    args = p.parse_args()
    if args.cmd == "export":
        import tensorflow as tf
        write_header(tf.keras.models.load_model(args.model), json.loads(Path(args.prep).read_text(encoding="utf-8")), args.out, args.source)
    elif args.cmd == "verify":
        cmd_verify(args.model, args.prep)
    else:
        cmd_check(args.split, args.seed, args.fold, args.epoch, args.tag)


if __name__ == "__main__":
    main()
