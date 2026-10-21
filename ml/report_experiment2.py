"""Render the fixed three-seed BLE-02 comparison as a portable PNG (Pillow)."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/experiments/ble-v1/results/BLE-02"


def main():
    report = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    canvas = Image.new("RGB", (1240, 500), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((22, 10), "BLE-02 | blue=control, red=class-balanced loss | same 8 validation gestures per run", fill="black")
    for panel,(key,title) in enumerate((("correct_events","Correct events / 8"),("unmatched_emissions","Unmatched emissions / replay"))):
        left,top,width,height=60+panel*620,65,530,330
        draw.text((left,top-25),title,fill="black")
        for value in range(9):
            y=top+height-value/8*height
            draw.line((left,y,left+width,y),fill="#dddddd")
            draw.text((left-20,y-5),str(value),fill="black")
        draw.rectangle((left,top,left+width,top+height),outline="black")
        for color,condition in (("#2466bf","control"),("#cc493b","balanced")):
            points=[]
            for i,pair in enumerate(report['paired']):
                x=left+60+i*205; y=top+height-pair[condition][key]/8*height
                points.append((x,y))
                draw.ellipse((x-4,y-4,x+4,y+4),fill=color)
            draw.line(points,fill=color,width=3)
        for i,pair in enumerate(report['paired']):
            draw.text((left+60+i*205-30,top+height+15),str(pair['seed']),fill="black")
        a=report['condition_summary']['control'][key]['mean']
        b=report['condition_summary']['balanced'][key]['mean']
        draw.text((left,top+height+45),f'Mean: control {a:.2f} | balanced {b:.2f}',fill="black")
    draw.text((22,475),"Initialization/shuffle variation on one fixed split; these are not independent sessions or 24 separate gestures.",fill="#555555")
    canvas.save(OUT/'comparison.png')
    print('comparison.png created')


if __name__=='__main__':
    main()
