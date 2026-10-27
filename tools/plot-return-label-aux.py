"""return-label-01 증강 비교 그림(SVG). 학습하지 않고 저장된 요약·결과만 읽는다.

  ml/.venv/Scripts/python.exe tools/plot-return-label-aux.py --summary summary-aug-rotwarp.json --tag zoon-pc-20261027

그림 3개를 docs/experiments/ble-v2/return-label-01/figures/에 쓴다(이미 있으면 거부).
  aug-clean-by-seed.svg   분할별 seed 정검출(선택 E), 같은 seed 연결선, 평균, 채택 문턱
  aug-aux-metrics.svg     보조 지표 6개(선택 E): 무발행·조기 발행 클립·배경 오발행·지연·다른 방향·반대 방향 조기 발행
  aug-clean-by-epoch.svg  E별 정검출(seed 평균)과 선택 E
채점은 new_window, 정검출은 clean_success_rate. 색은 dataviz 기본 범주 팔레트 앞 3색(전 쌍 검증 통과).
"""
import argparse
import gzip
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))
import v2  # noqa: E402
import v2_return as vr  # noqa: E402

LABELS = (("newtcnrt", "기준선", "newtcnrt"), ("newtcnrot", "회전", "newtcnrot"), ("newtcnrotwarp", "회전+속도", "newtcnrotwarp"))
COLORS = {"newtcnrt": "#2a78d6", "newtcnrot": "#eb6834", "newtcnrotwarp": "#1baf7a"}
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
FONT = "'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif"
OPP = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
SPLIT_NAMES = {"C": "C (세션 섞은 교차검증)", "S-P5": "S-P5 (P1~P4 세션 교차검증)"}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=12, anchor="start", fill=INK2, weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" '
            f'font-weight="{weight}">{esc(s)}</text>')


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{FONT}" role="img" aria-label="{esc(title)}">\n<title>{esc(title)}</title>\n'
            f'<rect width="{w}" height="{h}" fill="{SURFACE}"/>\n' + "\n".join(body) + "\n</svg>\n")


def legend(x, y):
    out = []
    for lab, name, code in LABELS:
        out += [f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{COLORS[lab]}"/>', text(x + 15, y, f"{name} ({code})", 12, fill=INK)]
        x += 30 + 7.2 * len(f"{name} ({code})")
    return out


def column(x, y0, y1, w, color):
    """baseline y0에서 위로 y1까지, 위쪽 모서리 4px 둥글게."""
    h = y0 - y1
    if h <= 0.5:
        return f'<rect x="{x:.1f}" y="{y0 - 1:.1f}" width="{w}" height="1" fill="{color}"/>'
    r = min(4, h, w / 2)
    return (f'<path d="M{x:.1f},{y0:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} H{x + w - r:.1f} '
            f'Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 + r:.1f} V{y0:.1f} Z" fill="{color}"/>')


def nice_ticks(vmax, n=4):
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    top = step * math.ceil(vmax / step - 1e-9)
    return [i * step for i in range(int(round(top / step)) + 1)]


def fmt(v, digits):
    return f"{v:.{digits}f}"


# ---------------------------------------------------------------- 데이터

def load(summary_name, tag):
    s = json.loads((vr.OUT / summary_name).read_text(encoding="utf-8"))
    if s.get("tag") != tag:
        raise ValueError(f"요약의 tag {s.get('tag')} ≠ {tag}")
    panels = {k: v["new_window"] for k, v in s["panels"].items()}
    _, by_path, nb = vr.load()
    opposite = {}
    for lab, _, _ in LABELS:
        for sp in vr.SPLITS:
            e = panels[f"{lab}-{sp}"]["selected_E"]
            n = 0
            for seed in v2.SEEDS:
                path = vr.OUT / "results" / tag / f"{lab}-{sp}" / f"seed-{seed}.json.gz"
                res = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
                for f in res["folds"]:
                    for p in f["per_epoch"][str(e)]["new_window"]["per_source"]:
                        r = nb.get(p["source_path"])
                        if r is None or r["extreme_ms"] is None:
                            continue
                        opp = v2.CLASSES.index(OPP[by_path[p["source_path"]]["direction"]])
                        n += sum(1 for t, c, kind in p["events"]
                                 if kind == "early" and c == opp and r["outbound_peak_ms"] <= t <= r["extreme_ms"])
            opposite[(lab, sp)] = n
    return panels, opposite


def sel(panels, lab, sp):
    p = panels[f"{lab}-{sp}"]
    return p["by_epoch"][str(p["selected_E"])], p["selected_E"]


# ---------------------------------------------------------------- 그림 1: seed별 정검출

def fig_clean_by_seed(panels):
    W, H, pw, top, bottom = 980, 400, 360, 92, 330
    body = [text(24, 30, "정검출(다른 방향 발행 없이 정답 방향만 발행한 클립 비율) — seed 5개", 16, fill=INK, weight=600),
            text(24, 52, "선택 E 기준. 회색 선은 같은 seed 연결, 검은 가로선은 평균, 가는 회색 가로선은 회전+속도 채택 문턱(회전 대비 S-P5 +1%p, C −1%p)", 12)]
    body += legend(24, 76)
    base = {sp: sel(panels, "newtcnrot", sp)[0]["clean_success_rate"] for sp in vr.SPLITS}
    vals = [s["clean_success_rate"] for lab, _, _ in LABELS for sp in vr.SPLITS for s in sel(panels, lab, sp)[0]["per_seed"]]
    lo = min(min(vals), base["C"] - 0.01, base["S-P5"] + 0.01)
    ymin = max(0.0, (int(lo * 100) // 2) * 2 / 100 - 0.02)
    ymax = 1.0
    y = lambda v: bottom - (v - ymin) / (ymax - ymin) * (bottom - top)
    for i, sp in enumerate(vr.SPLITS):
        x0 = 60 + i * (pw + 110)
        body.append(text(x0, bottom + 52, SPLIT_NAMES[sp], 13, fill=INK, weight=600))
        tick = ymin
        while tick <= ymax + 1e-9:
            body += [f'<line x1="{x0}" x2="{x0 + pw}" y1="{y(tick):.1f}" y2="{y(tick):.1f}" stroke="{GRID}" stroke-width="1"/>',
                     text(x0 - 8, y(tick) + 4, f"{tick * 100:.0f}%", 11, "end")]
            tick = round(tick + 0.02, 4)
        xs = {lab: x0 + 60 + j * 120 for j, (lab, _, _) in enumerate(LABELS)}
        seeds = {lab: [s["clean_success_rate"] for s in sel(panels, lab, sp)[0]["per_seed"]] for lab, _, _ in LABELS}
        offs = (-12, -6, 0, 6, 12)
        for k in range(5):
            pts = " ".join(f"{xs[lab] + offs[k]:.1f},{y(seeds[lab][k]):.1f}" for lab, _, _ in LABELS)
            body.append(f'<polyline points="{pts}" fill="none" stroke="#d3d2ce" stroke-width="1"/>')
        thr = base[sp] + (0.01 if sp == "S-P5" else -0.01)
        body += [f'<line x1="{x0}" x2="{x0 + pw}" y1="{y(thr):.1f}" y2="{y(thr):.1f}" stroke="{MUTED}" stroke-width="1"/>',
                 text(x0 + pw + 6, y(thr) - 2, "채택 문턱", 10, fill=MUTED),
                 text(x0 + pw + 6, y(thr) + 11, f"{thr * 100:.1f}%", 10, fill=MUTED)]
        for lab, name, _ in LABELS:
            stat, e = sel(panels, lab, sp)
            for k, v in enumerate(seeds[lab]):
                body.append(f'<circle cx="{xs[lab] + offs[k]:.1f}" cy="{y(v):.1f}" r="4.5" fill="{COLORS[lab]}" stroke="{SURFACE}" stroke-width="2"/>')
            m = stat["clean_success_rate"]
            body += [f'<line x1="{xs[lab] - 22:.1f}" x2="{xs[lab] + 22:.1f}" y1="{y(m):.1f}" y2="{y(m):.1f}" stroke="{INK}" stroke-width="2"/>',
                     text(xs[lab] + 26, y(m) + 4, f"{m * 100:.1f}%", 12, fill=INK, weight=600),
                     text(xs[lab], bottom + 20, name, 12, "middle", INK),
                     text(xs[lab], bottom + 35, f"E{e}", 11, "middle")]
    return svg(W, H + 10, body, "증강 조건별 seed 정검출")


# ---------------------------------------------------------------- 그림 2: 보조 지표

def fig_aux(panels, opposite):
    metrics = [
        ("무발행 클립", "%", lambda st, lab, sp: st["no_issue_rate"] * 100, 1),
        ("조기 발행이 있는 클립", "%", lambda st, lab, sp: st["early_clip_rate"] * 100, 1),
        ("배경 오발행", "10초 배경 클립당 건수", lambda st, lab, sp: st["background_false_per_clip"], 3),
        ("발행 지연 중앙값", "ms, 복귀 기준 r부터", lambda st, lab, sp: st["delay_median_ms"], 0),
        ("다른 방향 발행", "건, seed 5개 합", lambda st, lab, sp: sum(s["wrong_direction"] for s in st["per_seed"]), 0),
        ("반대 방향 조기 발행", "건, 가는 피크~끝점, seed 5개 합", lambda st, lab, sp: opposite[(lab, sp)], 0),
    ]
    cols, pw, ph, gx, gy, left, top0 = 3, 270, 200, 30, 70, 50, 100
    W = left + cols * pw + (cols - 1) * gx + 20
    H = top0 + 2 * (ph + gy) + 10
    body = [text(24, 30, "보조 지표(선택 E, seed 5개 평균 또는 합) — 모두 낮을수록 좋다(지연 포함)", 16, fill=INK, weight=600),
            text(24, 52, "조건마다 고른 E가 다르다(아래 정검출 그림의 E). 다른 방향·반대 방향 건수는 C 5 fold·S-P5 4 fold 검증 클립 전체에서 센 값", 12)]
    body += legend(24, 76)
    for idx, (name, unit, get, digits) in enumerate(metrics):
        cx, cy = left + (idx % cols) * (pw + gx), top0 + (idx // cols) * (ph + gy)
        vals = {(lab, sp): get(sel(panels, lab, sp)[0], lab, sp) for lab, _, _ in LABELS for sp in vr.SPLITS}
        ticks = nice_ticks(max(vals.values()) * 1.15 or 1)
        y0, y1 = cy + ph, cy + 40
        y = lambda v: y0 - v / ticks[-1] * (y0 - y1)
        body += [text(cx, cy + 14, name, 13, fill=INK, weight=600), text(cx, cy + 30, unit, 11)]
        for t in ticks:
            body += [f'<line x1="{cx}" x2="{cx + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{GRID}" stroke-width="1"/>',
                     text(cx - 6, y(t) + 4, fmt(t, 2 if ticks[-1] < 1 else 0), 10, "end")]
        bw = 22
        for g, sp in enumerate(vr.SPLITS):
            gx0 = cx + 30 + g * (pw / 2)
            for j, (lab, _, _) in enumerate(LABELS):
                bx = gx0 + j * (bw + 10)            # 3자리 값 라벨이 겹치지 않을 간격
                v = vals[(lab, sp)]
                body += [column(bx, y0, y(v), bw, COLORS[lab]),
                         text(bx + bw / 2, y(v) - 5, fmt(v, digits), 10, "middle", INK)]
            body.append(text(gx0 + 1.5 * bw + 10, y0 + 16, sp, 11, "middle", INK))
        body.append(f'<line x1="{cx}" x2="{cx + pw}" y1="{y0}" y2="{y0}" stroke="{MUTED}" stroke-width="1"/>')
    return svg(W, H, body, "증강 조건별 보조 지표")


# ---------------------------------------------------------------- 그림 3: E별 정검출

def fig_by_epoch(panels):
    W, H, pw, top, bottom = 980, 380, 380, 100, 320
    epochs = [e for e in v2.EPOCH_CANDIDATES if e >= 5]
    body = [text(24, 30, "학습 길이(E)별 정검출 — seed 5개 평균", 16, fill=INK, weight=600),
            text(24, 52, "큰 점이 선택 E(seed 평균 선택 점수 최대). E1은 학습이 거의 안 된 값이라 뺐다", 12)]
    body += legend(24, 76)
    vals = [panels[f"{lab}-{sp}"]["by_epoch"][str(e)]["clean_success_rate"] for lab, _, _ in LABELS for sp in vr.SPLITS for e in epochs]
    ymin = max(0.0, (int(min(vals) * 100) // 10) * 10 / 100)
    y = lambda v: bottom - (v - ymin) / (1 - ymin) * (bottom - top)
    for i, sp in enumerate(vr.SPLITS):
        x0 = 60 + i * (pw + 110)
        x = lambda e: x0 + 10 + e / max(epochs) * (pw - 20)
        body.append(text(x0, bottom + 48, SPLIT_NAMES[sp], 13, fill=INK, weight=600))
        tick = ymin
        while tick <= 1 + 1e-9:
            body += [f'<line x1="{x0}" x2="{x0 + pw}" y1="{y(tick):.1f}" y2="{y(tick):.1f}" stroke="{GRID}" stroke-width="1"/>',
                     text(x0 - 8, y(tick) + 4, f"{tick * 100:.0f}%", 11, "end")]
            tick = round(tick + (0.05 if 1 - ymin <= 0.4 else 0.1), 4)
        for e in epochs:
            body.append(text(x(e), bottom + 18, f"E{e}", 11, "middle"))
        lines, dots, chosen = [], [], []       # 선 → 작은 점 → 선택 E 점 순서로 그려 선택 E가 가려지지 않게 한다
        for lab, _, _ in LABELS:
            p = panels[f"{lab}-{sp}"]
            pts = [(x(e), y(p["by_epoch"][str(e)]["clean_success_rate"])) for e in epochs]
            lines.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" '
                         f'stroke="{COLORS[lab]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            for e, (a, b) in zip(epochs, pts):
                big = e == p["selected_E"]
                (chosen if big else dots).append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="{6.5 if big else 3.5}" '
                                                 f'fill="{COLORS[lab]}" stroke="{SURFACE}" stroke-width="2"/>')
        body += lines + dots + chosen
    return svg(W, H + 20, body, "E별 정검출")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    out = vr.OUT / "figures"
    out.mkdir(exist_ok=True)
    targets = {"aug-clean-by-seed.svg": None, "aug-aux-metrics.svg": None, "aug-clean-by-epoch.svg": None}
    if any((out / n).exists() for n in targets):
        raise FileExistsError(f"{out}에 그림이 이미 있다")
    panels, opposite = load(args.summary, args.tag)
    targets["aug-clean-by-seed.svg"] = fig_clean_by_seed(panels)
    targets["aug-aux-metrics.svg"] = fig_aux(panels, opposite)
    targets["aug-clean-by-epoch.svg"] = fig_by_epoch(panels)
    for n, content in targets.items():
        (out / n).write_text(content, encoding="utf-8", newline="\n")
        print("wrote", out / n)
    print("opposite-direction early (outbound peak ~ extreme):", {f"{k[0]}-{k[1]}": v for k, v in opposite.items()})


if __name__ == "__main__":
    main()
