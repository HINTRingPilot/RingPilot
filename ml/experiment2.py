"""BLE-02: diagnose frozen validation predictions and compare class weighting.

Uses exactly BLE-01-r03 inputs, normalization, targets, and split. No test replay.
Commands: --diagnose, --train, --summarize. Run diagnose before any new training.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

import baseline as base  # Also configures deterministic TF environment before import.
import numpy as np

ROOT = base.ROOT
SOURCE = ROOT / "ml/runs/BLE-01-r03"
DOC = ROOT / "docs/experiments/ble-v1/results/BLE-02"
SEEDS = (20261021, 20261022, 20261023)
PROTOCOL = DOC / "protocol.json"
CLASSES = base.CLASSES


def now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def frozen_data():
    manifest = json.loads((SOURCE / "split.json").read_text(encoding="utf-8"))
    for r in manifest["records"]:
        assert base.digest(ROOT / r["source_path"]) == r["sha256"]
    assert base.digest(base.MANIFEST) == base.digest(SOURCE / "split.json")
    arrays = np.load(SOURCE / "inputs.npz")
    meta = json.loads((SOURCE / "validation-windows.json").read_text(encoding="utf-8"))
    assert [m["target"] for m in meta] == arrays["y_validation"].tolist()
    assert arrays["x_train"].shape == (144, 160, 6)
    assert arrays["x_validation"].shape == (570, 160, 6)
    assert np.isfinite(arrays["x_train"]).all() and np.isfinite(arrays["x_validation"]).all()
    return manifest, arrays, meta


def diagnose():
    if PROTOCOL.exists():
        raise FileExistsError("Protocol already frozen")
    manifest, arrays, meta = frozen_data()
    records = {r["source_path"]: r for r in manifest["records"]}
    scores = np.load(SOURCE / "validation-scores.npy")
    assert scores.shape == (570, 5)
    rows = []
    aggregate, bins, by_source = defaultdict(Counter), defaultdict(Counter), defaultdict(list)
    for m, p in zip(meta, scores):
        r = records[m["source_path"]]
        t, e = m["timestamp_ms"], r["completion_ms"]
        pred, truth = int(np.argmax(p)), m["target"]
        region = Path(m["source_path"]).name.split(".")[0] if e is None else "pre_completion" if t < e else "positive" if t < e+150 else "post_positive"
        summary = aggregate[region]
        summary["n"] += 1
        summary["argmax_errors"] += pred != truth
        summary["predicted_NONE"] += pred == 0
        if truth != 0:
            bin_name = f'{int((t-e)//50)*50}-{int((t-e)//50)*50+49}ms'
            bins[bin_name]["n"] += 1
            bins[bin_name]["correct_direction"] += pred == truth
            bins[bin_name]["to_NONE"] += pred == 0
        candidate = pred != 0 and p[pred] >= .8 and np.sort(p)[-1]-np.sort(p)[-2] >= .2
        row = {"source_path": m["source_path"], "timestamp_ms": t,
               "completion_ms": e, "signed_from_completion_ms": None if e is None else t-e,
               "signed_from_positive_end_ms": None if e is None else t-e-150,
               "region": region, "target": CLASSES[truth], "predicted": CLASSES[pred],
               "direction_candidate_pass": bool(candidate), **{c: float(v) for c,v in zip(CLASSES,p)}}
        rows.append(row)
        by_source[m["source_path"]].append(row)
    source_summary = []
    for src, rr in by_source.items():
        r = records[src]
        if r["direction"] == "NONE":
            source_summary.append({"source_path":src,"positive_windows":0,"argmax_errors":sum(v["target"]!=v["predicted"] for v in rr)})
            continue
        positive = [v for v in rr if v["target"] != "NONE"]
        source_summary.append({"source_path":src,"completion_ms":r["completion_ms"],
                               "positive_windows":len(positive),"correct_positive_argmax":sum(v["predicted"]==v["target"] for v in positive),
                               "max_expected_score_in_positive":max(v[r["direction"]] for v in positive),
                               "candidate_pass_count_all_times":sum(v["direction_candidate_pass"] for v in rr)})
    result = {"source_run":"BLE-01-r03","created_kst":now(),"regions":dict(aggregate),
              "positive_bins":dict(bins),"per_file":source_summary,"final_test_inference":False,
              "conclusion":"Positive-to-NONE errors span all three 50ms positive bins; background idle/other argmax errors are zero. No boundary-ignore or NONE resampling justified in this experiment."}
    base.dump(DOC / "diagnosis.json", result)
    with (DOC / "boundary-predictions.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    counts = np.bincount(arrays["y_train"], minlength=5)
    weights = len(arrays["y_train"])/(5*counts.astype(float))
    assert np.isclose(np.dot(counts, weights), len(arrays["y_train"]))
    protocol = {"experiment":"BLE-02","created_before_training_kst":now(),"source_run":"BLE-01-r03",
                "question":"Does training loss class balancing reduce the broad direction-to-NONE confusion?",
                "changed_factor":"training loss class_weight only",
                "conditions":{"control":[1.0]*5,"balanced":weights.tolist()},"class_order":CLASSES,
                "train_counts":counts.tolist(),"seeds":SEEDS,"same_inputs_across_conditions_and_seeds":True,
                "input_sha256":base.digest(SOURCE/"inputs.npz"),"normalization_sha256":base.digest(SOURCE/"normalization.json"),
                "manifest_sha256":base.digest(SOURCE/"split.json"),"meta_sha256":base.digest(SOURCE/"validation-windows.json"),
                "optimizer":"Adam .001","batch_size":16,"max_epochs":100,
                "monitor":"unweighted val_loss, patience12, restore_best_weights",
                "threshold":.8,"margin":.2,"consecutive_direction":2,"consecutive_none":2,"event_tolerance_ms":500,
                "unchanged":["raw files","annotations","split","normalization","selected windows","160x6 input","9493-parameter CNN","augmentation off","postprocessing","validation targets"],
                "decision_rule":"Paired three-seed comparison; require mean correct event count increase without mean unmatched emissions increase and without a regression in any seed to retain as a development candidate. No deployment claim; no threshold search or final test.",
                "no_boundary_ignore":True,"no_none_resampling":True,"final_test_inference":False}
    base.dump(PROTOCOL, protocol)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('Frozen comparison protocol:',PROTOCOL)


def evaluate(manifest, meta, scores):
    from sklearn.metrics import classification_report, confusion_matrix
    y = np.array([m["target"] for m in meta])
    predicted = scores.argmax(axis=1)
    result = {"validation_window_accuracy":float(np.mean(y==predicted)),
              "confusion_matrix":confusion_matrix(y,predicted,labels=range(5)).tolist(),
              "class_report":classification_report(y,predicted,labels=range(5),target_names=CLASSES,zero_division=0,output_dict=True),
              "per_file":[],"final_test_inference":False}
    totals, delays = Counter(),[]
    for r in manifest["records"]:
        if r["split"] != "validation": continue
        indices = [i for i,m in enumerate(meta) if m["source_path"]==r["source_path"]]
        ts = [meta[i]["timestamp_ms"] for i in indices]
        events=base.issue_events(ts,scores[indices])
        counts,latency,annotated=base.classify_events(r,events)
        totals.update(counts); delays.extend(latency)
        result["per_file"].append({"source_path":r["source_path"],"completion_ms":r["completion_ms"],
                                   "positive_windows":sum(y[i]!=0 for i in indices).item(),
                                   "counts":counts,"events":annotated})
    result["event_totals"]=dict(totals)
    result["latency_ms"]={"n":len(delays),"median":float(np.median(delays)) if delays else None,
                          "p95":float(np.percentile(delays,95)) if delays else None}
    result["gesture_count"]=8
    result["background_recording_seconds"]=20.0
    result["background_inference_exposure_seconds"]=16.82
    return result


def train():
    import tensorflow as tf
    from model import build_model
    protocol=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest, arrays, meta=frozen_data()
    assert tuple(protocol["seeds"])==SEEDS
    for key,file in (("input_sha256","inputs.npz"),("normalization_sha256","normalization.json"),
                     ("manifest_sha256","split.json"),("meta_sha256","validation-windows.json")):
        assert protocol[key]==base.digest(SOURCE/file)
    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.experimental.enable_op_determinism()
    for seed_ix,seed in enumerate(SEEDS):
        for condition_ix,(condition,weights) in enumerate(protocol["conditions"].items()):
            run_id=f'BLE-02-r{seed_ix*2+condition_ix+1:02}'
            run=ROOT/"ml/runs"/run_id
            if run.exists(): raise FileExistsError(f"Refusing to overwrite {run}")
            run.mkdir(parents=True); (run/"tmp").mkdir(); tempfile.tempdir=str(run/"tmp")
            for script in ("baseline.py","experiment2.py","model.py"):
                shutil.copy2(ROOT/"ml"/script,run/script)
            for file in ("split.json","normalization.json","train-windows.json","validation-windows.json"):
                shutil.copy2(SOURCE/file,run/file)
            shutil.copy2(PROTOCOL,run/"protocol.json")
            tf.keras.backend.clear_session()
            tf.keras.utils.set_random_seed(seed)
            model=build_model(); assert model.count_params()==9493
            initial=[w.copy() for w in model.get_weights()]
            if condition_ix==0: control_initial=initial
            else:
                for a,b in zip(initial,control_initial): np.testing.assert_array_equal(a,b)
            model.compile(optimizer=tf.keras.optimizers.Adam(.001),loss="sparse_categorical_crossentropy",metrics=["accuracy"])
            config={"run_id":run_id,"condition":condition,"seed":seed,"start_kst":now(),
                    "class_weight":dict(zip(CLASSES,weights)),"protocol_sha256":base.digest(PROTOCOL),
                    "input_sha256":protocol["input_sha256"],"normalization_sha256":protocol["normalization_sha256"],
                    "model_code_sha256":base.digest(ROOT/"ml/model.py"),"runner_sha256":base.digest(ROOT/"ml/experiment2.py"),
                    "python":sys.version,"tensorflow":tf.__version__,"keras":tf.keras.__version__,"numpy":np.__version__,
                    "devices":[str(d) for d in tf.config.list_physical_devices()],
                    "initial_weights_identical_within_seed":True,"final_test_inference":False}
            base.dump(run/"config.json",config)
            (run/"environment.txt").write_text("\n".join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions()))+"\n",encoding="utf-8")
            options=tf.data.Options(); options.threading.private_threadpool_size=1
            ds_train=tf.data.Dataset.from_tensor_slices((arrays["x_train"],arrays["y_train"])).shuffle(144,seed=seed).batch(16).with_options(options)
            ds_val=tf.data.Dataset.from_tensor_slices((arrays["x_validation"],arrays["y_validation"])).batch(16).with_options(options)
            print(f'BEGIN {run_id} {condition} seed={seed}',flush=True)
            history=model.fit(ds_train,validation_data=ds_val,epochs=100,verbose=2,shuffle=False,
                              class_weight=dict(enumerate(weights)),callbacks=[
                                  tf.keras.callbacks.EarlyStopping(monitor="val_loss",patience=12,restore_best_weights=True),
                                  tf.keras.callbacks.CSVLogger(str(run/"history.csv")),
                                  tf.keras.callbacks.ModelCheckpoint(str(run/"best.keras"),monitor="val_loss",save_best_only=True)])
            model.save(run/"model.keras")
            scores=model(arrays["x_validation"],training=False).numpy()
            np.save(run/"validation-scores.npy",scores)
            result=evaluate(manifest,meta,scores)
            result.update(run_id=run_id,condition=condition,seed=seed,end_kst=now(),
                          epochs=len(history.history["loss"]),best_epoch=int(np.argmin(history.history["val_loss"]))+1,
                          best_val_loss=float(min(history.history["val_loss"])))
            if run_id=="BLE-02-r01":
                prior=np.load(SOURCE/"validation-scores.npy")
                delta=float(np.max(np.abs(prior-scores)))
                result["baseline_reproduction_max_abs_score_difference"]=delta
                np.testing.assert_allclose(prior,scores,rtol=1e-6,atol=1e-6)
            reload=tf.keras.models.load_model(run/"model.keras")
            np.testing.assert_allclose(scores,reload(arrays["x_validation"],training=False).numpy(),rtol=1e-6,atol=1e-6)
            result["saved_model_predictions_verified"]=True
            base.dump(run/"results.json",result)
            dest=DOC/run_id; dest.mkdir(parents=True)
            for name in ("config.json","results.json","history.csv","environment.txt"):
                shutil.copy2(run/name,dest/name)
            with (dest/"validation-predictions.csv").open("w",newline="",encoding="utf-8") as f:
                writer=csv.writer(f); writer.writerow(["source_path","timestamp_ms","target","predicted",*CLASSES])
                for m,p in zip(meta,scores): writer.writerow([m["source_path"],m["timestamp_ms"],CLASSES[m["target"]],CLASSES[int(p.argmax())],*p.tolist()])
            print(f'END {run_id}: events={result["event_totals"]}, macroF1={result["class_report"]["macro avg"]["f1-score"]:.4f}',flush=True)


def summarize():
    protocol=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    runs=[json.loads((DOC/f'BLE-02-r{i:02}'/"results.json").read_text(encoding="utf-8")) for i in range(1,7)]
    metrics={}
    def values(r):
        e=r['event_totals']
        return {"correct_events":e['correct'],"missed_events":e['missed'],
                "unmatched_emissions":sum(e[k] for k in ('wrong_direction','duplicate','early','late_unmatched','background_false')),
                "macro_f1":r['class_report']['macro avg']['f1-score'],"window_accuracy":r['validation_window_accuracy']}
    paired=[]
    for seed in SEEDS:
        control=next(r for r in runs if r['seed']==seed and r['condition']=='control')
        balanced=next(r for r in runs if r['seed']==seed and r['condition']=='balanced')
        a,b=values(control),values(balanced)
        paired.append({"seed":seed,"control":a,"balanced":b,"delta_balanced_minus_control":{k:b[k]-a[k] for k in a}})
    for condition in protocol['conditions']:
        selected=[values(r) for r in runs if r['condition']==condition]
        metrics[condition]={k:{"mean":float(np.mean([s[k] for s in selected])),"min":float(min(s[k] for s in selected)),"max":float(max(s[k] for s in selected))} for k in selected[0]}
    candidate=(metrics['balanced']['correct_events']['mean']>metrics['control']['correct_events']['mean']
               and metrics['balanced']['unmatched_emissions']['mean']<=metrics['control']['unmatched_emissions']['mean']
               and all(p['delta_balanced_minus_control']['correct_events']>=0 and p['delta_balanced_minus_control']['unmatched_emissions']<=0 for p in paired))
    summary={"experiment":"BLE-02","created_kst":now(),"protocol_sha256":base.digest(PROTOCOL),
             "paired":paired,"condition_summary":metrics,"retain_as_development_candidate":candidate,
             "run_ids":[r['run_id'] for r in runs],"final_test_inference":False,
             "limits":"Three initialization/shuffle seeds on one fixed small validation split, not independent users/sessions; no continuous or board testing."}
    base.dump(DOC/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(); group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--diagnose",action="store_true"); group.add_argument("--train",action="store_true"); group.add_argument("--summarize",action="store_true")
    args=parser.parse_args()
    diagnose() if args.diagnose else train() if args.train else summarize()
