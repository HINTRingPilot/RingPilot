"""Render common/native startup comparisons for BLE-04 (Pillow)."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

OUT=Path(__file__).resolve().parents[1]/"docs/experiments/ble-v1/results/BLE-04"


def main():
    summary=json.loads((OUT/"summary.json").read_text(encoding="utf-8"))
    canvas=Image.new("RGB",(1250,950),"white");draw=ImageDraw.Draw(canvas)
    draw.text((20,10),"BLE-04 | blue=160 samples, red=120 samples | same 8 validation gestures",fill="black")
    for row,mode in enumerate(("common","native")):
        title="COMMON replay: both start at1590ms" if mode=="common" else "NATIVE replay: 160 starts1590ms, 120 starts1190ms"
        draw.text((20,40+row*430),title,fill="black")
        pairs=[p for p in summary["paired"] if p["mode"]==mode]
        for panel,(key,label) in enumerate((("correct_events","Correct events / 8"),("unmatched_emissions","Unmatched emissions"),("early_emissions","Before completion"))):
            left,top,width,height=45+415*panel,90+row*430,345,285
            draw.text((left,top-20),label,fill="black")
            for value in range(9):
                y=top+height-value/8*height
                draw.line((left,y,left+width,y),fill="#dddddd");draw.text((left-18,y-5),str(value),fill="black")
            draw.rectangle((left,top,left+width,top+height),outline="black")
            for color,condition in (("#2466bf","160"),("#cc493b","120")):
                pts=[]
                for i,p in enumerate(pairs):
                    x,y=left+30+i*145,top+height-p[condition][key]/8*height
                    pts.append((x,y));draw.ellipse((x-4,y-4,x+4,y+4),fill=color)
                draw.line(pts,fill=color,width=3)
            for i,p in enumerate(pairs):draw.text((left+i*145,top+height+12),str(p["seed"]),fill="black")
            a=summary["condition_summary"][mode]["160"][key]["mean"];b=summary["condition_summary"][mode]["120"][key]["mean"]
            draw.text((left,top+height+40),f"Mean: 160 {a:.2f} | 120 {b:.2f}",fill="black")
    draw.text((20,915),"Analytical MACs: 288000 vs216000 (-25%); no board timing/RAM or continuous validation.",fill="#555555")
    canvas.save(OUT/"comparison.png");print("comparison.png created")


if __name__=="__main__":main()
