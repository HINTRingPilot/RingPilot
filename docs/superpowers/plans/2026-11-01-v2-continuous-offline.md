# 실기기 없이 연속 동작 개선 후보 평가 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 noacc와 앞 동작 합성(seq)을 같은 조건에서 비교하고, 실제 33초 기록 개선과 기존 성능 보존 여부로 다음 실험을 결정한다.

**Architecture:** 입력 처리·모델 구조·발행 규칙은 고정하고 학습 데이터 조건만 비교한다. 기존 교차검증, 합성 쌍 평가, 원본 연속 기록 전체 재생을 각각 실시한다. 현재 PC에서 재학습하는 경로를 기본으로 하되 원래 PC의 완전한 저장 모델을 확보하면 기존 실험을 이어간다.

**Tech Stack:** Windows PowerShell, `ml/.venv/Scripts/python.exe`, TensorFlow/Keras, NumPy, 기존 `v2_return`·`v2_seq_eval`·`v2_stream`.

상태: 2026-11-01 계획 작성. 아래 실행 단계는 아직 수행하지 않았다. 실기기·새 사용자 녹화 없이 완료할 범위다. 원본 기획서와 배포 가중치는 보존한다.

## 1. 출발점과 해석의 범위

- 대상 기록은 3초가 아니라 `docs/experiments/ble-v2/consecutive-01/continuous.1.csv`의 약 33초다.
- `consec_ablation.py`는 앞 동작 제거 시 점수 회복을 보여 준다. 다만 rest 조작은 앞 자이로 파형과 회전각 이력을 함께 바꾸므로 각 채널의 단독 원인까지 확정하지 않는다.
- 해당 도구의 `fire`는 잠금 없는 조건 통과다. 전체 상태기계의 실제 발행과 구분한다.
- 세기·속도 변경의 실패는 시험한 변경만으로 해결되지 않았다는 뜻이다. 모든 세기·속도 영향이 없음을 증명하지 않는다. `slow`는 시간축을 늘리면서 자이로 진폭을 유지하므로 누적 각도까지 달라진다.
- 이번 우선 후보는 앞 동작 합성이다. 누설 적분은 이번 비교에서 제외하고 느린 자세 이동 문제의 별도 후보로 보류한다.
- 동작 경계·번갈아 방향은 센서에서 추정했다. 이 기록은 개발 진단 자료이며 독립적인 최종 시험 자료가 아니다.

## 2. 파일과 산출물

| 경로 | 역할 / 작업 |
|---|---|
| `ml/v2_return.py` | 기존 학습·요약 도구 사용. 이번 단계에서 학습 로직 변경 없음 |
| `ml/v2_seq_eval.py` | 동일한 합성 쌍 평가에 사용 |
| `ml/v2_stream.py` | 온라인 영점 및 전체 발행 상태 유지 재생에 사용 |
| `ml/runs/return-label-01/seq-local-20261101/` | 현재 PC 학습 모델·전처리·점수·원본 결과 |
| `docs/experiments/ble-v2/return-label-01/summary-seq-local-20261101.json` | 단일 동작·배경 성능 요약 |
| `docs/experiments/ble-v2/consecutive-01/comparison-seq-local-20261101/` | 모델별 원본 재생 점수·시각·발행 JSON 및 NPZ |
| `docs/experiments/ble-v2/consecutive-01/seq-comparison-20261101.md` | 조건별 비교 표, 채택/보류와 이유를 새로 작성 |
| `docs/experiments/ble-v2/consecutive-01/README.md` | 위 결과 문서 링크와 결론 추가 |
| `docs/TODO.md`, `docs/진행기록.md` | 다음 작업과 실행 사실을 구분해 갱신 |

경로는 저장소 루트 기준. 실행 위치는 `C:/Users/zoonc/Desktop/RingPilot`이다. 기존 결과 파일은 덮어쓰지 않는다. 동일 이름이 있으면 내용과 완료 여부를 확인한 뒤 새 실행 태그를 부여한다.

## 검토 반영(2026-11-01, 실행 전)

- 계획의 명령·함수가 지금 코드에 있고 맞물림을 확인했다: `run-all`의 `--save-models`·`--splits`, `summarize`의 `panels["<label>-<split>"].extreme_window.selected_E`(모든 seed 결과가 있는 조건만 들어감), `vr.model_dir`, `prep.json`이 `vs.stream_inputs`에 필요한 키를 담음, `v2.issue_events`(R0), `v2.configure_tf()`가 tensorflow를 돌려줌, `v2.EPOCH_CANDIDATES`에 60 포함.
- 시작 전 커밋: 지난 분석(`consec_ablation.*`, README·진행기록·`consec_trace.py`)과 이 계획·TODO를 먼저 커밋해 실행 코드 식별값을 깨끗한 HEAD로 남긴다.
- 병렬 수: 이 PC는 논리 코어 20개·메모리 약 32 GB다. `run-all`은 미완료 작업의 로그가 있으면 재시작을 거부하므로(로그 보호) 중간에 병렬 수를 바꾸기 어렵다. 그래서 처음부터 병렬 4로 실행하고 메모리를 관찰한다(학습은 스레드 1·결정성 연산이라 병렬 수가 결과를 바꾸지 않음). 메모리가 부족하면 중단하고 미완료 로그를 확인한 뒤 새 태그로 다시 한다.
- 소요 시간(추정): 과거 회전 증강 S-P5 seed 1회 290~485 s(병렬 3). seq는 방향 사본이 더 붙어 더 길다. 20개 작업 대략 1~3시간으로 보고 첫 작업 시간으로 고친다.
- idle/other 분리: `summarize`는 배경 오발행을 합친 값만 낸다. Task 2에서 결과 JSON의 클립별 분류(`background_false`)와 원본 경로의 종류로 나눠 세는 작은 스크립트를 만든다.
- 합성 쌍 평가 시간: `v2_seq_eval` 1회가 간격 7 × seed 5 × fold 5 = 175번 모델을 불러온다. 4회 실행이라 오래 걸릴 수 있다.
- 집계 도구(학습 중 준비): `docs/experiments/ble-v2/consecutive-01/seq_compare.py`의 `background`(Task 2 idle/other 분리), `replay`(Task 4 배치와 같은 재생 + 전체 세션 모델 참고선), `score`(시간순 일대일 대응, 구간별 집계). 기존 seq-20261031 결과로 `background`를, 전체 세션 모델 재생으로 `replay`·`score`를 시험했고 README 값(빠른 위 1/5, 편한 간격 5/5)을 재현했다. 시험 출력은 저장소 밖에 썼다.
- 실측 소요(첫 작업): noacc S-P3 fold 1개 86.6 s(병렬 4). 전체 예상을 약 1시간 안팎으로 고친다.
- 표본 크기: 33초 기록의 빠른 구간 실패 동작은 4개뿐이다. Task 5 기준은 그대로 두고 결과 문서에 작은 표본을 한계로 적는다.

## Task 0. 실행 환경과 비교 조건 고정

- [ ] 현재 변경 파일 목록을 보존한다. 다른 작업의 ablation·README 수정은 되돌리지 않는다.
- [ ] 아래 명령으로 환경과 기존 시험을 확인하고 결과 문서에 Python·TensorFlow·NumPy·PC·코드 커밋 및 미커밋 변경 여부를 기록한다.

```powershell
git status --short
git rev-parse HEAD
hostname
& ml/.venv/Scripts/python.exe -c "import sys,tensorflow as tf,numpy as np; print(sys.version); print(tf.__version__); print(np.__version__)"
& ml/.venv/Scripts/python.exe -m unittest discover -s ml -p 'test_v2*.py'
```

예상: 환경 버전 출력 및 기존 시험 통과. 건너뛴 시험은 사유를 기록한다. 실패하면 학습 전에 원인을 확인한다.

- [ ] 비교 조건을 고정한다: labels=`newtcnrotwarpnoacc`, `newtcnrotwarpnoaccseq`; splits=`S-P3`, `S-P5`; seeds=`20261021`~`20261025`; 발행 R0; 원시 기록·학습 원본·분할 동일.
- [ ] E 선택은 기존 `extreme_window`의 seed 평균 selection_score, 동률이면 작은 E를 그대로 사용한다. 33초 재생 결과로 E·seed·fold를 고르지 않는다. E60 고정 비교도 보조로 남겨 학습량 차이를 확인한다.

## Task 1. 모델 확보: 가능한 경로 하나만 실행

**기본 경로 B — 현재 PC:** 현재 체크아웃에는 전체 세션 모델 하나만 있고 seq 저장 모델 폴더가 없다. 다른 PC를 기다리지 않고 아래 20개 작업을 새 태그로 실행한다. 20개는 조건 2 × 분할 2 × seed 5이고, 각 작업 안에 여러 fold 학습이 있으므로 모델 20개라는 뜻은 아니다.

```powershell
& ml/.venv/Scripts/python.exe ml/v2_return.py run-all --parallel 2 --labels newtcnrotwarpnoacc newtcnrotwarpnoaccseq --splits S-P3 S-P5 --tag seq-local-20261101 --save-models
```

- [ ] 먼저 메모리·첫 작업 소요 시간을 관찰한다. 메모리가 부족하면 병렬 1로 낮춘다. 학습 중 코드 수정·다른 무거운 학습을 실행하지 않는다.
- [ ] 완료 JSON 20개뿐 아니라 각 fold의 `prep.json`·후보 E `.keras`·점수 파일 존재를 확인한다. 결과가 있다고 모델 저장까지 완전하다고 가정하지 않는다.
- [ ] 중단되면 같은 태그의 완료 작업을 보존한다. 기존 도구가 완료 JSON을 건너뛰므로 미완료 fold는 자동 이어학습이 아니라 해당 작업 재실행임을 기록한다.

**대체 경로 A — 원래 PC를 사용할 수 있는 경우:** 기존 15개 결과의 원본 모델·전처리·점수 파일이 모두 있고 코드·데이터 조건이 일치하는지 먼저 확인한다. 모두 일치하면 아래 5개만 수행한다.

```powershell
& ml/.venv/Scripts/python.exe ml/v2_return.py run-all --parallel 2 --labels newtcnrotwarpnoaccseq --splits S-P5 --tag seq-20261031 --save-models
```

- [ ] 경로 A를 선택하면 이후 명령의 태그 및 산출물 이름 `seq-local-20261101`을 `seq-20261031`로 일괄 치환한다. 원래 PC 결과와 현재 PC 신규 학습 결과를 한 조건씩 섞어 비교하지 않는다.
- [ ] 경로 B의 최초 작업 시간을 측정해 전체 예상 시간을 갱신한다. 현 단계에서 소요 시간을 확정하지 않는다.

## Task 2. 단일 동작과 배경 오발행을 먼저 비교

```powershell
& ml/.venv/Scripts/python.exe ml/v2_return.py summarize --tag seq-local-20261101 --splits S-P3 S-P5 --out summary-seq-local-20261101.json
```

- [ ] 출력에 두 조건·두 분할이 모두 포함됐는지 확인한다. 누락된 조건이 있으면 완료로 처리하지 않는다.
- [ ] 분할별·seed별 정검출, clean_success_rate, 누락, 오방향, 중복, 지연을 비교한다. 선택 E와 E60 고정 결과를 둘 다 기록한다.
- [ ] 저장 원본 결과의 배경 클립을 idle과 other로 나눠 발행 건수/클립 수를 따로 집계한다. 합쳐진 평균만으로 idle 악화를 숨기지 않는다.
- [ ] 배경은 같은 원본·seed·fold끼리 비교한다. 반복 평가 횟수를 독립적인 사용자 표본 수로 표현하지 않는다. other 클립의 시간당 환산을 실제 일상 오발행률로 부르지 않는다.

## Task 3. 동일 합성 쌍 평가

- [ ] 아래 명령을 PowerShell에서 실행한다. 분할·조건별 E는 Task 2 요약에서 읽으며 변경하지 않는다.

```powershell
$seqTag = 'seq-local-20261101'
$seqSummary = Get-Content "docs/experiments/ble-v2/return-label-01/summary-$seqTag.json" -Raw | ConvertFrom-Json
foreach ($seqSplit in @('S-P3', 'S-P5')) {
    foreach ($seqLabel in @('newtcnrotwarpnoacc', 'newtcnrotwarpnoaccseq')) {
        $seqPanel = $seqSummary.panels.PSObject.Properties["$seqLabel-$seqSplit"].Value
        $seqEpoch = $seqPanel.extreme_window.selected_E
        if ($null -eq $seqEpoch) { throw '선택 E를 찾을 수 없음' }
        & ml/.venv/Scripts/python.exe ml/v2_seq_eval.py --tag $seqTag --label $seqLabel --split $seqSplit --epoch $seqEpoch --out "$seqTag-$seqLabel-$seqSplit-selected.json"
        if ($LASTEXITCODE -ne 0) { throw '합성 평가 실패' }
    }
}
```

- [ ] gap별 성공·오방향·유효 쌍 수를 비교한다. 후보 간 쌍 수가 다르면 같은 쌍으로 맞추기 전까지 평균을 직접 비교하지 않는다.
- [ ] gap은 r+100 ms 뒤에 삽입한 휴지 시간이다. 실제 피크 간 0.53초와 같은 단위가 아님을 표에 명시한다.
- [ ] 합성 평가가 클립 영점을 사용한다는 한계를 적는다. 온라인 영점 실사용 여부는 다음 단계에서 확인한다.

## Task 4. 원본 33초 전체를 상태를 유지하며 재생

ablation의 앞 동작 제거·회전각 이동은 적용하지 않는다. 기존 `vs.replay`를 호출하면 33초 전체에 온라인 영점과 실제 R0 잠금·재무장이 적용된다. 별도 재생 도구 구현 없이 아래 배치로 비교 자료를 만든다.

- [ ] 저장소 루트에서 다음을 실행해 선택 E와 E60 모델별 점수·발행을 저장한다.

```powershell
@'
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path.cwd() / 'ml'))
import v2
import v2_return as vr
import v2_stream as vs
tf = v2.configure_tf()
tag = 'seq-local-20261101'
root = Path('docs/experiments/ble-v2')
here = root / 'consecutive-01'
summary = json.loads((root / 'return-label-01' / f'summary-{tag}.json').read_text(encoding='utf-8'))
out = here / f'comparison-{tag}'
out.mkdir(exist_ok=False)
ts, raw = vs.read_stream(here / 'continuous.1.csv')
for split in ('S-P3', 'S-P5'):
    for label in ('newtcnrotwarpnoacc', 'newtcnrotwarpnoaccseq'):
        selected = summary['panels'][f'{label}-{split}']['extreme_window']['selected_E']
        for seed in v2.SEEDS:
            for fold in range(v2.load_split(split)['cv']['n_folds']):
                folder = vr.model_dir(label, split, seed, fold, tag)
                prep = json.loads((folder / 'prep.json').read_text(encoding='utf-8'))
                for epoch in sorted({selected, 60}):
                    model = tf.keras.models.load_model(folder / f'e{epoch}.keras')
                    times, scores, events = vs.replay(model, raw, ts, prep, estimates='still')
                    stem = f'{label}-{split}-{seed}-fold{fold}-e{epoch}'
                    np.savez_compressed(out / f'{stem}.npz', times=times, scores=scores)
                    report = dict(label=label, split=split, seed=seed, fold=fold,
                                  epoch=epoch, selected_E=selected, estimates='still', events=events)
                    (out / f'{stem}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                    tf.keras.backend.clear_session()
print(out)
'@ | & ml/.venv/Scripts/python.exe -
```

- [ ] 원본 전체 세션 모델의 기존 재생 결과는 참고선으로만 둔다. 후보 fold 모델과 전체 학습 모델을 직접 대조해 학습 방식 효과로 해석하지 않는다.
- [ ] 동작 구간은 `consec_ablation.json`의 기존 경계로 먼저 고정한다. 모델 점수를 보고 경계·방향을 옮기지 않는다. 번갈아 구간은 추정 방향으로 별도 표를 만든다.
- [ ] 기존 [start_ms, end_ms+400] 진단 구간이 겹치면 발행 하나를 두 동작의 성공으로 세지 않는다. 시간순 일대일 대응을 적용하고 모호한 대응은 따로 표기한다.
- [ ] 빠른 위 반복, 편한 간격, 번갈아 구간, 16.53초 단일 실패를 나눠 정답 발행·누락·중복·오방향·구간 밖 발행을 집계한다. 최대 점수와 실제 발행은 별도 열이다.
- [ ] 지연은 추정 끝점 기준임을 명시한다. 처음 구간 초기화와 잠금 상태를 동작마다 리셋하지 않았음을 확인한다.
- [ ] 방향을 신호에서 추정했으므로 위 표를 사용자 확인 정답 기반 정확도로 발표하지 않는다. 보드 발행과의 시각 일치는 참고이며 새 모델의 보드 검증은 아니다.

## Task 5. 사전 판단 기준과 다음 분기

다음은 이번 실험의 보수적인 **진행 기준**이다. 제품 성능 보장이나 통계적 유의성 기준은 아니다. 결과를 본 뒤 편의에 맞게 바꾸지 않는다.

| 항목 | 다음 후보로 진행하는 기준 |
|---|---|
| 단일 동작 | S-P3·S-P5 각각 seed 평균 clean_success_rate 저하 1%p 이내. seed별 악화도 공개 |
| 배경 | 각 분할의 동일 평가 수 기준 idle·other 총 오발행이 각각 증가하지 않음 |
| 합성 연속 | gap 0~300 ms의 합산 성공률 개선, 오방향 총 건수 증가 없음 |
| 원본 연속 | 빠른 위 구간의 seed별 fold 평균 정답 발행 수가 각 분할에서 5 seed 중 4개 이상 개선 |
| 원본 부작용 | 편한 구간 정답 발행 유지, 중복·오방향·구간 밖 발행 총수가 각 분할에서 증가하지 않음 |

- [ ] 모두 충족하면 **PC 개선 후보**로 기록한다. 자동으로 보드 가중치를 교체하지 않는다. 최종 채택은 새 독립 기록과 보드 시험 뒤에 한다.
- [ ] 합성은 좋아졌지만 실제 기록이 개선되지 않으면 앞 동작 2~3개 합성의 별도 구현 계획을 작성한다. 이때 합성 길이 증가로 대상 동작이 잘리는 문제, 유효 창 수, 동일/반대 방향 조합, 학습 fold 밖 데이터 혼입 방지 시험을 포함한다.
- [ ] 배경이 나빠지면 새 합성 수·양성/NONE 비율과 어떤 배경에서 늘었는지 먼저 분석한다. 임계값을 임의로 낮춰 연속 점수만 살리지 않는다.
- [ ] 번갈아 구간만 개선되지 않으면 추정 정답의 불확실성을 먼저 표시한다. 방향 추정에 맞춰 모델을 추가 튜닝하지 않는다.
- [ ] 16.53초 실패는 별도 현상으로 남긴다. 연속 문제를 해결했다는 이유로 함께 해결됐다고 기록하지 않는다.

## Task 6. 결과 기록과 종료

- [ ] `seq-comparison-20261101.md`에 실행 PC·코드/데이터 식별값·버전·태그·E·seed·fold·소요 시간·분모·원본 결과 경로·판단표를 작성한다.
- [ ] README에 요약과 결과 링크, 진행기록에 날짜·목적·변경·이유·검증·문제/해결·다음 작업을 추가한다. TODO에서 실제 완료 항목만 체크한다.
- [ ] 최종 답변은 “개선 후보 / 보류 / 개선 없음” 중 하나와 근거를 제공한다. 실기기 성공으로 표현하지 않는다.

이번 계획의 완료 조건: 두 학습 조건에 대한 동일 환경 비교와 다음 분기 결정까지. 좌우 자세 변경, 중력 규칙, 앱 개편, 실기기 업로드, 새 데이터 수집은 포함하지 않는다. 사용자가 장치를 확보할 때까지 기다릴 작업은 없다.
