"""Copy portable evidence and draw learning curves from an existing run (Pillow)."""
import csv
import json
from pathlib import Path
import shutil
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "ml/runs/BLE-01-r03"
OUT = ROOT / "docs/experiments/ble-v1/results/BLE-01-r03"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "results.json", "normalization.json", "history.csv",
                 "model-summary.txt", "environment.txt", "validation-predictions.csv"):
        shutil.copy2(RUN / name, OUT / name)
    with (RUN / "history.csv").open(encoding="utf-8") as f:
        history = [{k: float(v) for k,v in row.items()} for row in csv.DictReader(f)]
    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 10), "BLE-01-r03 | blue=train, red=validation | selected checkpoint: epoch 1", fill="black")
    for panel, (name, series, ymax) in enumerate((
        ("Crossentropy loss", ("loss", "val_loss"), max(max(h['loss'], h['val_loss']) for h in history)*1.1),
        ("Window accuracy (NONE-dominated validation)", ("accuracy", "val_accuracy"), 1.0),
    )):
        left, top, width, height = 55+panel*600, 65, 520, 355
        draw.text((left, top-25), name, fill="black")
        for step in range(6):
            y=top+height-step/5*height
            draw.line((left,y,left+width,y),fill="#dddddd")
            draw.text((left-43,y-5),f'{step/5*ymax:.2f}',fill="black")
        draw.rectangle((left,top,left+width,top+height),outline="black")
        for color,key in zip(("#2466bf","#cc493b"),series):
            pts=[(left+i/(len(history)-1)*width,top+height-h[key]/ymax*height) for i,h in enumerate(history)]
            draw.line(pts,fill=color,width=3)
        for epoch in (1,3,5,7,9,11,13):
            draw.text((left+(epoch-1)/12*width-4,top+height+8),str(epoch),fill="black")
        draw.text((left+width/2-20,top+height+30),"Epoch",fill="black")
    image.save(OUT / "learning-curves.png")
    r=json.loads((RUN/'results.json').read_text(encoding='utf-8'))
    assert r['final_test_inference'] is False
    print('Portable evidence copied; learning curves created.')


if __name__ == '__main__':
    main()
