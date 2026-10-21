"""Create reproducible sensor quality reports and completion review sheets (Pillow)."""

import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/annotations/ble-v1"
ASSETS = ROOT / "docs/experiments/ble-v1/assets"
AXES = ("accX", "accY", "accZ", "gyrX", "gyrY", "gyrZ")
COLORS = ("#d44b3e", "#299452", "#3268ce")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    annotations = []
    for session in ("phone-20261021-091621", "phone-20261021-094346"):
        result = subprocess.run(
            ["node", "tools/suggest-gesture-completions.js", "--local-dir",
             f"data/sessions/{session}", "--format", "json"],
            cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        )
        report = json.loads(result.stdout)
        # This existing tool restarts numeric sample IDs for every local session.
        # Use source_path as the identity, never the numeric ID alone.
        dest = OUT / f"{session}-candidates.json"
        encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if dest.exists() and dest.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"Refusing to overwrite different candidates: {dest}")
        dest.write_text(encoded, encoding="utf-8")
        annotations.extend(report["annotations"])
        for page in range(math.ceil(len(report["annotations"]) / 20)):
            sheet = Image.new("RGB", (1800, 1660), "white")
            draw = ImageDraw.Draw(sheet)
            draw.text((15, 8), f"{session} / page {page + 1} / X red, Y green, Z blue / completion purple", fill="black")
            for slot, ann in enumerate(report["annotations"][page * 20:(page + 1) * 20]):
                with (ROOT / ann["source_path"]).open(encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
                x0, y0 = (slot % 4) * 450, (slot // 4) * 325 + 30
                draw.text((x0 + 8, y0), f'{ann["filename"]} e={ann["completion_ms"]} {ann["status"]}', fill="black")
                draw.text((x0 + 8, y0 + 17), ann["flags"] or "no flags", fill="black")
                for group, axes in enumerate((AXES[:3], AXES[3:])):
                    left, top, width, height = x0 + 38, y0 + 43 + group * 132, 395, 105
                    series = [[float(r[a]) for r in rows] for a in axes]
                    extent = max(max(abs(v) for v in values) for values in series)
                    extent = max(extent, 1)
                    draw.rectangle((left, top, left + width, top + height), outline="#aaaaaa")
                    draw.line((left, top + height / 2, left + width, top + height / 2), fill="#dddddd")
                    draw.text((x0 + 2, top), "acc" if group == 0 else "gyr", fill="black")
                    draw.text((left, top - 12), f'+/-{extent:.1f}', fill="#666666")
                    for color, values in zip(COLORS, series):
                        pts = [(left + float(rows[i]["timestamp"]) / 3000 * width,
                                top + height / 2 - value / extent * (height / 2 - 3)) for i, value in enumerate(values)]
                        draw.line(pts, fill=color, width=1)
                    marker = left + ann["completion_ms"] / 3000 * width
                    draw.line((marker, top, marker, top + height), fill="#a326aa", width=2)
                    for t in (0, 1000, 2000, 3000):
                        draw.text((left + t / 3000 * width - 6, top + height + 2), str(t), fill="#555555")
            sheet.save(ASSETS / f"{session}-review-{page + 1}.png")
    quality = []
    for session in sorted((ROOT / "data/sessions").glob("phone-*")):
        for src in sorted(session.glob("*.csv")):
            if not src.name.startswith(("raw_", "idle.", "other.")):
                continue
            with src.open(encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                assert reader.fieldnames == ["timestamp", *AXES], src
                rows = list(reader)
            ts = [float(r["timestamp"]) for r in rows]
            values = [[float(r[a]) for a in AXES] for r in rows]
            assert all(math.isfinite(v) for row in values for v in row), src
            assert ts[0] == 0 and all(b-a == 10 for a, b in zip(ts, ts[1:])), src
            assert len(rows) == (300 if src.name.startswith("raw_") else 1000), src
            quality.append({"source_path": src.relative_to(ROOT).as_posix(),
                            "sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "rows": len(rows),
                            "last_timestamp_ms": ts[-1], "max_abs_gyro": max(abs(v) for r in values for v in r[3:])})
    assert len({r["sha256"] for r in quality}) == len(quality), "Duplicate raw file"
    (OUT / "quality.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    background = [q for q in quality if not Path(q["source_path"]).name.startswith("raw_")]
    sheet = Image.new("RGB", (1500, 1050), "white")
    draw = ImageDraw.Draw(sheet)
    for i, q in enumerate(background):
        x0, y0 = i % 2 * 750, i // 2 * 350
        with (ROOT / q["source_path"]).open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        draw.text((x0+10, y0+8), q["source_path"].replace("data/sessions/", ""), fill="black")
        for g, axes in enumerate((AXES[:3], AXES[3:])):
            left, top, width, height = x0+40, y0+40+g*145, 695, 110
            values = [[float(r[a]) for r in rows] for a in axes]
            extent = max(1, max(abs(v) for a in values for v in a))
            draw.rectangle((left, top, left+width, top+height), outline="#aaaaaa")
            draw.text((left, top-13), f'{"acc" if g==0 else "gyr"} +/-{extent:.1f} / 0-10000 ms', fill="black")
            for color, a in zip(COLORS, values):
                draw.line([(left+float(rows[j]["timestamp"])/10000*width, top+height/2-v/extent*(height/2-2)) for j,v in enumerate(a)], fill=color)
    sheet.save(ASSETS / "background-review.png")
    print(json.dumps({"files": len(quality), "annotations": len(annotations),
                      "review": [a for a in annotations if a["status"] == "REVIEW"]}, indent=2))


if __name__ == "__main__":
    main()
