# 제스처 완료 시점 주석

세션별 방향 샘플(`raw_*.N.csv`, 3초 또는 4초)에 대한 자연 복귀 완료 시점 후보표다. 원시 센서 값이나 인증 정보는 저장하지 않는다.

| 파일 | 대상 |
|---|---|
| `gesture-completions-session-2026-10-21-phone.csv` | `data/sessions/phone-20261021-091621/` (휴대폰 앱 수집, 20개) |
| `ble-v1/phone-20261021-091621-candidates.json` | BLE 실험 1용 첫 세션 자동 후보 20개 재계산, 기존 CSV 보존 |
| `ble-v1/phone-20261021-094346-candidates.json` | BLE 실험 1용 추가 세션 자동 후보 40개 |
| `ble-v1/review-decisions.json` | 66개 원본의 센서 파형 기반 채택/보류/제외 판단 및 분할 |

BLE 실험 1의 실제 주석 검토와 시간 제약은 [데이터 검토 기록](../../docs/experiments/ble-v1/01-data-review.md)을 따른다. 자동 후보와 검토 결정을 구분하며, 영상·사용자 확인으로 완료 정답을 확정한 것은 아니다. 새 로컬 학습은 [고정 분할표](../splits/ble-v1.json)와 `ml/baseline.py`를 사용한다.

2026-10-21에 이전 데이터(Edge Impulse 1차 세션 46개, USB 2차 세션 40개, 학습 윈도우)와 그 주석을 사용자 요청으로 모두 삭제했다. 경과는 `docs/진행기록.md`에 있다.

## 현재 계약

- 이벤트 완료 `completion_ms`: 방향 이동과 자연 복귀의 자이로 에너지 99%가 지난 뒤, 최종 자세 부근에서 IMU가 180 ms 안정되기 시작한 시점
  - 에너지 1%/99% 지점은 동작 기준(평활 자이로가 최고값의 8%, 12~40 dps 이상)을 넘는 샘플로만 계산한다. 정지 구간의 착용 잡음(10~30 dps)이 클립 길이만큼 쌓여 시작은 앞당기고 완료는 늦추는 것을 막기 위해서다(2026-10-21 변경).
  - 안정 판정에도 자이로가 동작 기준 미만일 것을 요구한다. 잡음이 큰 꼬리에서 안정 기준이 50 dps 가까이 느슨해지는 것을 막는다.
- 방향 양성 목표: `completion_ms <= t < positive_target_end_ms`
- 현재 양성 폭: 150 ms
- 그 밖의 시점: `NONE`
- `raw_*` 파일 라벨을 그대로 전체 window에 상속하지 않는다.
- 클립 길이, 동작 신호 시각, 자이로 범위는 세션의 `session_info.txt`(`gesture_samples`, `pre_roll_cue_ms`, `gyro_range_dps`)에서 읽는다. 없으면 300행, 500 ms, ±1000 dps로 본다.

끝점에서 잠깐 멈췄다가 복귀하는 동작을 조기 완료로 오인하지 않도록 안정 구간 검색은 전체 자이로 에너지 99% 이후에만 시작한다. 이 정의는 초기 보수안이다. 연속 replay에서 지연이 과도하면 별도의 조기 이벤트 모델과 비교한다.

## 상태와 플래그

- `AUTO`: 현재 자동 기준을 통과한 완료 시점 후보
- `REVIEW`: 완료 시점 후보는 기록했지만 파형을 다시 확인해야 하는 샘플. 첫 모델의 기본 학습 목록에서는 제외한다.
- `early_motion`: 동작 신호(`pre_roll_cue_ms`, 기본 0.5초) 전에 유의미한 동작 에너지가 존재
- `late_completion`: 완료 시점이 클립 끝 0.5초 이내
- `no_180ms_settle`, `second_motion_cluster`, `near_gyro_limit`: 안정 구간 없음, 두 번째 동작 덩어리, 자이로 한계(범위의 90%) 근접
- `return_pose_offset`은 2026-10-19부터 판정에 쓰지 않는다(최종 자세가 시작 자세와 같을 필요가 없음). 각도 값은 `return_angle_deg`로 참고용 기록만 한다.

`REVIEW`를 삭제한다는 뜻은 아니며, 어려운 사례 및 연속 replay 평가 자료로 보존한다.

## 다시 계산

```powershell
node tools/suggest-gesture-completions.js --local-dir data/sessions/<세션> --format csv > data/annotations/gesture-completions-session-<세션>.csv
```

출력 결과를 검토하지 않고 기존 CSV 위에 자동 반영하지 않는다. 학습 창은 `ml/`의 학습 코드가 `data/splits/`의 분할과 `data/annotations/ble-v1/` 주석으로 만든다.

- `sample_id`는 세션마다 9000000000부터 다시 시작한다. export는 파일 이름을 내부 순번으로 만들고 manifest에 `source_path`를 함께 남기므로 겹쳐도 덮어쓰지 않는다. 구분이 필요하면 `--id-start`로 세션별 범위를 준다.
- export는 주석에 나온 세션 폴더(및 `--sessions`로 준 폴더)의 `idle.N.csv`, `other.N.csv`를 NONE 출처로 읽는다. NONE 상한은 동작 클립 배경, idle, other에서 번갈아 고르게 채운다.
