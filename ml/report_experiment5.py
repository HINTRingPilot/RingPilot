"""Render BLE-05 readout comparison using saved metrics (Pillow)."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

OUT=Path(__file__).resolve().parents[1]/"docs/experiments/ble-v1/results/BLE-05"


def main():
    summary=json.loads((OUT/"summary.json").read_text(encoding="utf-8"))
    canvas=Image.new("RGB",(1250,520),"white");draw=ImageDraw.Draw(canvas)
    draw.text((20,12),"BLE-05 | blue=Flatten, red=GAP | same 8 validation gestures per replay",fill="black")
    for panel,(key,title) in enumerate((("correct_events","Correct events / 8"),("unmatched_emissions","Unmatched emissions"),("early_emissions","Emissions before return complete"))):
        left,top,width,height=45+415*panel,70,345,325
        draw.text((left,top-22),title,fill="black")
        ymax=max(8,max(p[head][key] for p in summary["paired"] for head in ("flatten","gap")))
        for step in range(9):
            y=top+height-step/8*height
            draw.line((left,y,left+width,y),fill="#dddddd");draw.text((left-20,y-5),f"{step/8*ymax:g}",fill="black")
        draw.rectangle((left,top,left+width,top+height),outline="black")
        for color,condition in (("#2466bf","flatten"),("#cc493b","gap")):
            pts=[]
            for i,p in enumerate(summary["paired"]):
                x,y=left+30+i*145,top+height-p[condition][key]/ymax*height
                pts.append((x,y));draw.ellipse((x-4,y-4,x+4,y+4),fill=color)
            draw.line(pts,fill=color,width=3)
        for i,p in enumerate(summary["paired"]):draw.text((left+i*145,top+height+14),str(p["seed"]),fill="black")
        a=summary["condition_summary"]["flatten"][key]["mean"];b=summary["condition_summary"]["gap"][key]["mean"]
        draw.text((left,top+height+45),f"Mean: Flatten {a:.2f} | GAP {b:.2f}",fill="black")
    draw.text((20,480),"Parameters: 9493 vs3253 (-65.7%); Conv/Dense MACs:288000 vs281760 (-2.17%), GAP reductions extra.",fill="#555555")
    draw.text((20,498),"Fixed clip split; initialization/shuffle variation only. No continuous or board measurements.",fill="#555555")
    canvas.save(OUT/"comparison.png");print("comparison.png created")


if __name__=="__main__":main()
