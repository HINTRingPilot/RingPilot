"""BLE-05: Flatten vs GAP on exactly the frozen BLE-01 input windows.

One readout change; common 160-row input, canonical labels, output state machine
and seed pairs. Source hashes and selection rule frozen before training.
"""

import argparse
import csv
from datetime import datetime
import importlib.metadata
import json
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

import baseline as base
from experiment2 import frozen_data, evaluate
import numpy as np

ROOT=base.ROOT
SOURCE=ROOT/"ml/runs/BLE-01-r03"
DOC=ROOT/"docs/experiments/ble-v1/results/BLE-05"
SEEDS=(20261021,20261022,20261023)
READOUTS=("flatten","gap")


def now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def prepare():
    if (DOC/"protocol.json").exists():raise FileExistsError("Protocol already frozen")
    manifest,a,meta=frozen_data()
    assert len([r for r in manifest["records"] if r["split"]=="validation"])==10
    assert len(meta)==570
    protocol={"experiment":"BLE-05","stage":"clip_comparison_only","created_before_training_kst":now(),
              "source_run":"BLE-01-r03","readouts":READOUTS,"seeds":SEEDS,
              "changed_factor":"Flatten vs GlobalAveragePooling1D, keeping following Dropout(.3) and Dense5; no added hidden Dense",
              "input_sha256":base.digest(SOURCE/"inputs.npz"),"manifest_sha256":base.digest(SOURCE/"split.json"),
              "normalization_sha256":base.digest(SOURCE/"normalization.json"),"meta_sha256":base.digest(SOURCE/"validation-windows.json"),
              "train_window_count":144,"validation_window_count":570,
              "train_class_counts":np.bincount(a["y_train"],minlength=5).tolist(),
              "validation_class_counts":np.bincount(a["y_validation"],minlength=5).tolist(),
              "fixed_architecture":"160x6 -> Conv16,k5 -> Pool2 -> Dropout.2 -> Conv32,k5 -> Pool2 -> READOUT -> Dropout.3 -> Dense5 softmax",
              "parameters":{"flatten":9493,"gap":3253},"readout_features":{"flatten":1280,"gap":32},
              "conv_dense_macs":{"flatten":288000,"gap":281760},
              "gap_reduction_ops_note":"GAP averages 40 times per channel: 1248 additions and32 scale/divide operations, not counted as Conv/Dense MACs",
              "optimizer":"Adam .001","batch_size":16,"max_epochs":100,
              "checkpoint":"unweighted validation loss; patience12; restore best weights",
              "training_positive_width_ms":150,"augmentation":False,"class_weight":None,
              "postprocessing":"same direction2 predictions at score>=.8 margin>=.2; rearm on NONE>=.8 twice",
              "event_rule":"same direction in [e,e+500ms], one-to-one; e is natural return completion; early is not success",
              "decision_rule":"Retain GAP as development candidate only if each paired seed has noninferior correct events and no increase in unmatched or early emissions, with fewer parameters. No deployment/final architecture adoption.",
              "limitations":["aggregation and parameter capacity change together","Dropout.3 has32 instead of1280 features after GAP","same8 gestures repeated for3 seeds","no continuous/new session or board testing","validation targets are sensor-derived"],
              "final_test_inference":False}
    base.dump(DOC/"protocol.json",protocol)
    print(json.dumps(protocol,ensure_ascii=False,indent=2))


def predictions(path,meta,scores):
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f);writer.writerow(["source_path","timestamp_ms","target","predicted",*base.CLASSES])
        for m,p in zip(meta,scores):writer.writerow([m["source_path"],m["timestamp_ms"],base.CLASSES[m["target"]],base.CLASSES[int(p.argmax())],*p.tolist()])


def train():
    import tensorflow as tf
    from model import build_model
    protocol=json.loads((DOC/"protocol.json").read_text(encoding="utf-8"))
    manifest,a,meta=frozen_data()
    for key,filename in (("input_sha256","inputs.npz"),("manifest_sha256","split.json"),
                         ("normalization_sha256","normalization.json"),("meta_sha256","validation-windows.json")):
        assert protocol[key]==base.digest(SOURCE/filename)
    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.experimental.enable_op_determinism()
    for si,seed in enumerate(SEEDS):
        for ri,readout in enumerate(READOUTS):
            run_id=f"BLE-05-r{si*2+ri+1:02}";run=ROOT/"ml/runs"/run_id
            if run.exists():raise FileExistsError(f"Refusing to overwrite {run}")
            run.mkdir(parents=True);(run/"tmp").mkdir();tempfile.tempdir=str(run/"tmp")
            for script in ("baseline.py","experiment2.py","experiment5.py","model.py"):
                shutil.copy2(ROOT/"ml"/script,run/script)
            for filename in ("split.json","normalization.json","train-windows.json","validation-windows.json"):
                shutil.copy2(SOURCE/filename,run/filename)
            shutil.copy2(DOC/"protocol.json",run/"protocol.json")
            (run/"environment.txt").write_text("\n".join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions()))+"\n",encoding="utf-8")
            tf.keras.backend.clear_session();tf.keras.utils.set_random_seed(seed)
            model=build_model(160,readout=readout)
            assert model.count_params()==protocol["parameters"][readout]
            conv_initial=[w.copy() for name in ("conv1","conv2") for w in model.get_layer(name).get_weights()]
            if ri==0:control_conv=conv_initial
            else:
                for x,y in zip(conv_initial,control_conv):np.testing.assert_array_equal(x,y)
            model.compile(optimizer=tf.keras.optimizers.Adam(.001),loss="sparse_categorical_crossentropy",metrics=["accuracy"])
            config={"run_id":run_id,"readout":readout,"seed":seed,"start_kst":now(),
                    "parameters":model.count_params(),"readout_features":protocol["readout_features"][readout],
                    "conv_dense_macs":protocol["conv_dense_macs"][readout],
                    "protocol_sha256":base.digest(DOC/"protocol.json"),"input_sha256":protocol["input_sha256"],
                    "normalization_sha256":protocol["normalization_sha256"],"manifest_sha256":protocol["manifest_sha256"],
                    "model_code_sha256":base.digest(ROOT/"ml/model.py"),"runner_sha256":base.digest(ROOT/"ml/experiment5.py"),
                    "evaluator_sha256":base.digest(ROOT/"ml/experiment2.py"),
                    "convolution_initial_weights_equal_within_seed":True,"dense_initial_weights_equal":False,
                    "python":sys.version,"tensorflow":tf.__version__,"keras":tf.keras.__version__,"numpy":np.__version__,
                    "final_test_inference":False}
            base.dump(run/"config.json",config)
            with (run/"model-summary.txt").open("w",encoding="utf-8") as f:model.summary(print_fn=lambda line:f.write(line+"\n"))
            options=tf.data.Options();options.threading.private_threadpool_size=1
            ds_train=tf.data.Dataset.from_tensor_slices((a["x_train"],a["y_train"])).shuffle(144,seed=seed).batch(16).with_options(options)
            ds_val=tf.data.Dataset.from_tensor_slices((a["x_validation"],a["y_validation"])).batch(16).with_options(options)
            print(f"BEGIN {run_id} readout={readout} seed={seed}",flush=True)
            history=model.fit(ds_train,validation_data=ds_val,epochs=100,verbose=2,shuffle=False,callbacks=[
                tf.keras.callbacks.EarlyStopping(monitor="val_loss",patience=12,restore_best_weights=True),
                tf.keras.callbacks.CSVLogger(str(run/"history.csv")),
                tf.keras.callbacks.ModelCheckpoint(str(run/"best.keras"),monitor="val_loss",save_best_only=True)])
            model.save(run/"model.keras")
            scores=model(a["x_validation"],training=False).numpy()
            np.save(run/"validation-scores.npy",scores)
            reloaded=tf.keras.models.load_model(run/"model.keras")
            np.testing.assert_allclose(scores,reloaded(a["x_validation"],training=False).numpy(),rtol=1e-6,atol=1e-6)
            result=evaluate(manifest,meta,scores)
            result.update(run_id=run_id,readout=readout,seed=seed,end_kst=now(),parameters=model.count_params(),
                          epochs=len(history.history["loss"]),best_epoch=int(np.argmin(history.history["val_loss"]))+1,
                          best_val_loss=float(min(history.history["val_loss"])),saved_model_predictions_verified=True)
            if ri==0:
                prior=np.load(ROOT/"ml/runs"/f"BLE-02-r{si*2+1:02}"/"validation-scores.npy")
                np.testing.assert_allclose(prior,scores,rtol=1e-6,atol=1e-6)
                result["control_reproduction_max_abs_score_difference"]=float(np.max(np.abs(prior-scores)))
            base.dump(run/"results.json",result)
            dest=DOC/run_id;dest.mkdir(parents=True)
            for filename in ("config.json","results.json","history.csv","environment.txt","model-summary.txt"):
                shutil.copy2(run/filename,dest/filename)
            predictions(dest/"validation-predictions.csv",meta,scores)
            print(f"END {run_id}: {result['event_totals']}",flush=True)


def summarize():
    runs=[json.loads((DOC/f"BLE-05-r{i:02}/results.json").read_text(encoding="utf-8")) for i in range(1,7)]
    def metrics(r):
        e=r["event_totals"]
        return {"correct_events":e["correct"],"missed_events":e["missed"],
                "unmatched_emissions":sum(e[k] for k in ("early","wrong_direction","duplicate","late_unmatched","background_false")),
                "early_emissions":e["early"],"macro_f1":r["class_report"]["macro avg"]["f1-score"],
                "window_accuracy":r["validation_window_accuracy"]}
    paired=[];summary={}
    for seed in SEEDS:
        a,b=[metrics(next(r for r in runs if r["seed"]==seed and r["readout"]==head)) for head in READOUTS]
        paired.append({"seed":seed,"flatten":a,"gap":b,"delta_gap_minus_flatten":{k:b[k]-a[k] for k in a}})
    for head in READOUTS:
        selected=[metrics(r) for r in runs if r["readout"]==head]
        summary[head]={k:{"mean":float(np.mean([s[k] for s in selected])),"min":float(min(s[k] for s in selected)),"max":float(max(s[k] for s in selected))} for k in selected[0]}
    candidate=all(p["delta_gap_minus_flatten"]["correct_events"]>=0 and p["delta_gap_minus_flatten"]["unmatched_emissions"]<=0 and p["delta_gap_minus_flatten"]["early_emissions"]<=0 for p in paired)
    result={"experiment":"BLE-05","stage":"clip_comparison_only","created_kst":now(),
            "protocol_sha256":base.digest(DOC/"protocol.json"),"paired":paired,"condition_summary":summary,
            "retain_gap_as_development_candidate":candidate,"final_architecture_adopted":False,
            "parameters":{"flatten":9493,"gap":3253},"parameter_reduction_fraction":1-3253/9493,
            "conv_dense_mac_reduction_fraction":1-281760/288000,"final_test_inference":False,
            "limits":"Same8 sensor-annotated gestures repeated on3 seeds; aggregation and capacity change together; no independent continuous/new-session or board validation."}
    base.dump(DOC/"summary.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare",action="store_true");group.add_argument("--train",action="store_true");group.add_argument("--summarize",action="store_true")
    args=parser.parse_args()
    prepare() if args.prepare else train() if args.train else summarize()
