"""BLE-04: 160 vs 120 samples, identical train times and common validation.

Separate native-start replay exposes startup differences without mixing them
into the shared-time window-length comparison. No final test or board timing.
"""

import argparse
from datetime import datetime
import csv
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

import baseline as base
import numpy as np

ROOT = base.ROOT
SOURCE = ROOT / "ml/runs/BLE-01-r03"
DATA = ROOT / "ml/runs/BLE-04-inputs"
DOC = ROOT / "docs/experiments/ble-v1/results/BLE-04"
SEEDS = (20261021, 20261022, 20261023)
LENGTHS = (160, 120)


def now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def short_context(x, length):
    if length < 4 or length > x.shape[1]:
        raise ValueError("Invalid context length")
    return x[:, -length:, :].copy()


def native_windows(record, mean, std, length):
    ts, raw = base.read_sensor(ROOT / record["source_path"])
    ends = np.arange(length-1, len(raw), 5)
    x = np.stack([raw[i-length+1:i+1] for i in ends])
    x = ((x-mean)/std).astype(np.float32)
    y = np.zeros(len(ends), dtype=np.int64)
    e = record["completion_ms"]
    if e is not None:
        y[(ts[ends] >= e) & (ts[ends] < e+150)] = base.CLASSES.index(record["direction"])
    meta = [{"source_path":record["source_path"], "timestamp_ms":int(ts[i]), "target":int(label)} for i,label in zip(ends,y)]
    return x, y, meta


def check_sources():
    manifest = json.loads((SOURCE / "split.json").read_text(encoding="utf-8"))
    assert base.digest(base.MANIFEST) == base.digest(SOURCE / "split.json")
    for r in manifest["records"]:
        assert base.digest(ROOT/r["source_path"]) == r["sha256"]
    return manifest


def prepare():
    if DATA.exists() or (DOC/"protocol.json").exists():
        raise FileExistsError("Refusing to overwrite fixed data/protocol")
    manifest = check_sources()
    a = np.load(SOURCE/"inputs.npz")
    norm = json.loads((SOURCE/"normalization.json").read_text(encoding="utf-8"))
    mean, std = np.array(norm["mean"]), np.array(norm["std"])
    validation = [r for r in manifest["records"] if r["split"] == "validation"]
    common_meta = json.loads((SOURCE/"validation-windows.json").read_text(encoding="utf-8"))
    chunks = [native_windows(r,mean,std,120) for r in validation]
    x_native = np.concatenate([c[0] for c in chunks])
    y_native = np.concatenate([c[1] for c in chunks])
    native_meta = sum([c[2] for c in chunks],[])
    mask = np.array([m["timestamp_ms"] >= 1590 for m in native_meta])
    np.testing.assert_array_equal(x_native[mask],short_context(a["x_validation"],120))
    np.testing.assert_array_equal(y_native[mask],a["y_validation"])
    assert [{k:m[k] for k in ("source_path","timestamp_ms","target")} for m in common_meta] == [m for m, keep in zip(native_meta,mask) if keep]
    assert len(native_meta) == 650 and len(common_meta) == 570
    DATA.mkdir(parents=True)
    np.savez_compressed(DATA/"inputs.npz", x_train160=a["x_train"],x_train120=short_context(a["x_train"],120),
                        y_train=a["y_train"],x_common160=a["x_validation"],x_common120=short_context(a["x_validation"],120),
                        y_common=a["y_validation"],x_native120=x_native,y_native120=y_native)
    for name in ("split.json","normalization.json","train-windows.json","validation-windows.json"):
        shutil.copy2(SOURCE/name,DATA/name)
    base.dump(DATA/"native120-windows.json",native_meta)
    startup=[]
    for r in validation:
        if r["direction"] == "NONE": continue
        counts={str(n):sum(m["target"]!=0 for m in (common_meta if n==160 else native_meta) if m["source_path"]==r["source_path"]) for n in LENGTHS}
        startup.append({"source_path":r["source_path"],"completion_ms":r["completion_ms"],"positive_windows":counts,
                        "less_than_two_160":counts["160"]<2,"less_than_two_120":counts["120"]<2})
    protocol={"experiment":"BLE-04","stage":"clip_comparison_only","created_before_training_kst":now(),
              "source_run":"BLE-01-r03","lengths_samples":LENGTHS,"seeds":SEEDS,
              "changed_factor":"input history length; flatten/dense size changes necessarily",
              "training":"same 144 windows and 150ms targets; short input is last 120 rows of each 160-row input",
              "common_validation":"same 570 times (t>=1590ms), same labels; reset postprocessing per file; also used for val_loss checkpoint selection",
              "native_validation":"160: t>=1590ms, 570 windows; 120: t>=1190ms, 650 windows; replay from native start so earlier emissions affect locking",
              "native_120_extra_windows":80,"train_class_counts":np.bincount(a["y_train"],minlength=5).tolist(),
              "common_class_counts":np.bincount(a["y_validation"],minlength=5).tolist(),
              "native120_class_counts":np.bincount(y_native,minlength=5).tolist(),
              "normalization_sha256":base.digest(DATA/"normalization.json"),"manifest_sha256":base.digest(DATA/"split.json"),
              "source_input_sha256":base.digest(SOURCE/"inputs.npz"),"input_sha256":base.digest(DATA/"inputs.npz"),
              "model":{"conv_filters":[16,32],"kernels":[5,5],"pool":2,"dropout":[.2,.3],
                       "parameters":{"160":9493,"120":7893},"macs":{"160":288000,"120":216000},
                       "input_bytes_float32":{"160":3840,"120":2880}},
              "optimizer":"Adam .001","batch_size":16,"max_epochs":100,"early_stopping":"common val_loss, patience12, restore best",
              "class_weight":None,"augmentation":False,"training_positive_width_ms":150,
              "output":"score .8, margin .2, same direction twice; NONE .8 twice to rearm",
              "user_target":"after natural return","event_rule":"same direction in [e,e+500ms], one-to-one; early remains a failure",
              "decision_rule":"Retain 120 only as development candidate if correct events are noninferior and unmatched/early emissions do not increase in every paired seed in BOTH common and native replay, while analytical MACs decrease. No final deployment claim.",
              "limitations":["fixed small sensor-annotated clips","no independent continuous data","120 native early windows not added to training","same excluded raw files kept excluded","no board timing/RAM measurement"],
              "final_test_inference":False}
    base.dump(DOC/"protocol.json",protocol)
    base.dump(DOC/"startup-coverage.json",startup)
    base.dump(DOC/"native120-windows.json",native_meta)
    print(json.dumps(protocol,ensure_ascii=False,indent=2))
    print(json.dumps(startup,ensure_ascii=False,indent=2))


def evaluate(manifest,meta,scores,length):
    from experiment2 import evaluate as common_evaluator
    result=common_evaluator(manifest,meta,scores)
    background=[r for r in manifest["records"] if r["split"]=="validation" and r["direction"]=="NONE"]
    result["background_inference_exposure_seconds"]=sum((r["rows"]*10-(length-1)*10)/1000 for r in background)
    result["warmup_ms"]=(length-1)*10
    return result


def save_predictions(path,meta,scores):
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f);writer.writerow(["source_path","timestamp_ms","target","predicted",*base.CLASSES])
        for m,p in zip(meta,scores): writer.writerow([m["source_path"],m["timestamp_ms"],base.CLASSES[m["target"]],base.CLASSES[int(p.argmax())],*p.tolist()])


def train():
    import tensorflow as tf
    from model import build_model
    manifest=check_sources();protocol=json.loads((DOC/"protocol.json").read_text(encoding="utf-8"))
    assert protocol["input_sha256"]==base.digest(DATA/"inputs.npz")
    assert protocol["normalization_sha256"]==base.digest(SOURCE/"normalization.json")
    a=np.load(DATA/"inputs.npz")
    common_meta=json.loads((DATA/"validation-windows.json").read_text(encoding="utf-8"))
    native_meta=json.loads((DATA/"native120-windows.json").read_text(encoding="utf-8"))
    tf.config.threading.set_intra_op_parallelism_threads(1);tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.experimental.enable_op_determinism()
    for si,seed in enumerate(SEEDS):
        for li,length in enumerate(LENGTHS):
            run_id=f"BLE-04-r{si*2+li+1:02}";run=ROOT/"ml/runs"/run_id
            if run.exists():raise FileExistsError(f"Refusing to overwrite {run}")
            run.mkdir(parents=True);(run/"tmp").mkdir();tempfile.tempdir=str(run/"tmp")
            for script in ("baseline.py","model.py","experiment2.py","experiment4.py"):
                shutil.copy2(ROOT/"ml"/script,run/script)
            for name in ("split.json","normalization.json","train-windows.json","validation-windows.json","native120-windows.json"):
                shutil.copy2(DATA/name,run/name)
            shutil.copy2(DOC/"protocol.json",run/"protocol.json")
            (run/"environment.txt").write_text("\n".join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions()))+"\n",encoding="utf-8")
            tf.keras.backend.clear_session();tf.keras.utils.set_random_seed(seed)
            model=build_model(length);assert model.count_params()==protocol["model"]["parameters"][str(length)]
            conv_initial=[w.copy() for layer in ("conv1","conv2") for w in model.get_layer(layer).get_weights()]
            if li==0:control_conv=conv_initial
            else:
                for x,y in zip(conv_initial,control_conv):np.testing.assert_array_equal(x,y)
            model.compile(optimizer=tf.keras.optimizers.Adam(.001),loss="sparse_categorical_crossentropy",metrics=["accuracy"])
            config={"run_id":run_id,"seed":seed,"window_samples":length,"start_kst":now(),
                    "parameters":model.count_params(),"macs_analytical":protocol["model"]["macs"][str(length)],
                    "protocol_sha256":base.digest(DOC/"protocol.json"),"input_sha256":protocol["input_sha256"],
                    "model_code_sha256":base.digest(ROOT/"ml/model.py"),"runner_sha256":base.digest(ROOT/"ml/experiment4.py"),
                    "evaluator_sha256":base.digest(ROOT/"ml/experiment2.py"),
                    "convolution_initial_weights_equal_within_seed":True,"dense_initial_weights_equal":False,
                    "dense_note":"shape differs (1280x5 vs960x5), exact full weight pairing impossible",
                    "python":sys.version,"tensorflow":tf.__version__,"keras":tf.keras.__version__,"numpy":np.__version__,
                    "final_test_inference":False}
            base.dump(run/"config.json",config)
            with (run/"model-summary.txt").open("w",encoding="utf-8") as f:model.summary(print_fn=lambda line:f.write(line+"\n"))
            options=tf.data.Options();options.threading.private_threadpool_size=1
            ds_train=tf.data.Dataset.from_tensor_slices((a[f"x_train{length}"],a["y_train"])).shuffle(144,seed=seed).batch(16).with_options(options)
            ds_val=tf.data.Dataset.from_tensor_slices((a[f"x_common{length}"],a["y_common"])).batch(16).with_options(options)
            print(f"BEGIN {run_id} samples={length} seed={seed}",flush=True)
            history=model.fit(ds_train,validation_data=ds_val,epochs=100,verbose=2,shuffle=False,callbacks=[
                tf.keras.callbacks.EarlyStopping(monitor="val_loss",patience=12,restore_best_weights=True),
                tf.keras.callbacks.CSVLogger(str(run/"history.csv")),
                tf.keras.callbacks.ModelCheckpoint(str(run/"best.keras"),monitor="val_loss",save_best_only=True)])
            model.save(run/"model.keras")
            scores=model(a[f"x_common{length}"],training=False).numpy()
            np.save(run/"common-scores.npy",scores)
            common=evaluate(manifest,common_meta,scores,160) # common replay always starts at1590ms
            if length==120:
                native_scores=model(a["x_native120"],training=False).numpy()
                native=evaluate(manifest,native_meta,native_scores,120)
                mask=np.array([m["timestamp_ms"]>=1590 for m in native_meta])
                np.testing.assert_allclose(native_scores[mask],scores,rtol=1e-6,atol=1e-6)
            else:native_scores,native=scores,common
            np.save(run/"native-scores.npy",native_scores)
            reload=tf.keras.models.load_model(run/"model.keras")
            np.testing.assert_allclose(scores,reload(a[f"x_common{length}"],training=False).numpy(),rtol=1e-6,atol=1e-6)
            result={"run_id":run_id,"seed":seed,"window_samples":length,"end_kst":now(),
                    "epochs":len(history.history["loss"]),"best_epoch":int(np.argmin(history.history["val_loss"]))+1,
                    "best_val_loss":float(min(history.history["val_loss"])),"parameters":model.count_params(),
                    "common":common,"native":native,"saved_model_predictions_verified":True,"final_test_inference":False}
            if run_id=="BLE-04-r01":
                prior=np.load(SOURCE/"validation-scores.npy")
                np.testing.assert_allclose(prior,scores,rtol=1e-6,atol=1e-6)
                result["baseline_reproduction_max_abs_score_difference"]=float(np.max(np.abs(prior-scores)))
            base.dump(run/"results.json",result)
            dest=DOC/run_id;dest.mkdir(parents=True)
            for name in ("config.json","results.json","history.csv","environment.txt","model-summary.txt"):shutil.copy2(run/name,dest/name)
            save_predictions(dest/"common-predictions.csv",common_meta,scores)
            save_predictions(dest/"native-predictions.csv",native_meta if length==120 else common_meta,native_scores)
            print(f"END {run_id}: common={common['event_totals']}, native={native['event_totals']}",flush=True)


def summarize():
    runs=[json.loads((DOC/f"BLE-04-r{i:02}/results.json").read_text(encoding="utf-8")) for i in range(1,7)]
    def metrics(r,mode):
        a=r[mode];e=a["event_totals"]
        return {"correct_events":e["correct"],"missed_events":e["missed"],
                "unmatched_emissions":sum(e[k] for k in ("early","wrong_direction","duplicate","late_unmatched","background_false")),
                "early_emissions":e["early"],"macro_f1":a["class_report"]["macro avg"]["f1-score"],"window_accuracy":a["validation_window_accuracy"]}
    paired=[];summary={}
    for mode in ("common","native"):
        summary[mode]={}
        for length in LENGTHS:
            selected=[metrics(r,mode) for r in runs if r["window_samples"]==length]
            summary[mode][str(length)]={k:{"mean":float(np.mean([s[k] for s in selected])),
                                          "min":float(min(s[k] for s in selected)),"max":float(max(s[k] for s in selected))} for k in selected[0]}
        for seed in SEEDS:
            a,b=[metrics(next(r for r in runs if r["seed"]==seed and r["window_samples"]==n),mode) for n in LENGTHS]
            paired.append({"mode":mode,"seed":seed,"160":a,"120":b,"delta120_minus160":{k:b[k]-a[k] for k in a}})
    candidate=all(p["delta120_minus160"]["correct_events"]>=0 and p["delta120_minus160"]["unmatched_emissions"]<=0 and p["delta120_minus160"]["early_emissions"]<=0 for p in paired)
    result={"experiment":"BLE-04","stage":"clip_comparison_only","created_kst":now(),
            "protocol_sha256":base.digest(DOC/"protocol.json"),"paired":paired,"condition_summary":summary,
            "retain_120_as_development_candidate":candidate,"final_window_length_adopted":False,
            "analytical_mac_reduction":.25,"final_test_inference":False,
            "limits":"Same fixed eight gestures and three initialization/shuffle seeds; model size also changes with length; native replay uses extra pre1590ms windows unseen in training; no continuous or board measurement."}
    base.dump(DOC/"summary.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare",action="store_true");group.add_argument("--train",action="store_true");group.add_argument("--summarize",action="store_true")
    args=parser.parse_args()
    prepare() if args.prepare else train() if args.train else summarize()
