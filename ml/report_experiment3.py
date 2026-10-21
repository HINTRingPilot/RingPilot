"""Draw BLE-03 clip pilot comparison (Pillow)."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "docs/experiments/ble-v1/results/BLE-03"


def main():
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    canvas = Image.new("RGB", (1250, 510), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 12), "BLE-03 CLIP PILOT | blue=150ms, red=300ms training labels | all evaluation rules unchanged", fill="black")
    for panel, (key, title) in enumerate((("correct_events", "Correct events / 8"),
                                        ("unmatched_emissions", "Unmatched emissions"),
                                        ("early_emissions", "Emissions before return complete"))):
        left, top, width, height = 45+panel*415, 70, 345, 325
        draw.text((left, top-28), title, fill="black")
        for value in range(9):
            y = top+height-value/8*height
            draw.line((left, y, left+width, y), fill="#dddddd")
            draw.text((left-18, y-5), str(value), fill="black")
        draw.rectangle((left, top, left+width, top+height), outline="black")
        for color, condition in (("#2466bf", "150ms"), ("#cc493b", "300ms")):
            points = []
            for i, pair in enumerate(summary["paired"]):
                x, y = left+30+i*145, top+height-pair[condition][key]/8*height
                points.append((x, y)); draw.ellipse((x-4, y-4, x+4, y+4), fill=color)
            draw.line(points, fill=color, width=3)
        for i, pair in enumerate(summary["paired"]):
            draw.text((left+i*145, top+height+14), str(pair["seed"]), fill="black")
        a = summary["condition_summary"]["150"][key]["mean"]
        b = summary["condition_summary"]["300"][key]["mean"]
        draw.text((left, top+height+45), f"Mean: 150ms {a:.2f} | 300ms {b:.2f}", fill="black")
    draw.text((20, 480), "Same 8 validation gestures; shared 221-window training pool. Continuous validation and final policy selection remain pending.", fill="#555555")
    canvas.save(OUT / "comparison.png")
    print("comparison.png created")


if __name__ == "__main__":
    main()
