# 완료 시각 검토 01 — 표본 파형·점수·발행 요약

작성: 2026-10-25T18:38:09+09:00 · 표본 26개 · E=60, seed 5개 고정 진단 조건

> 완료 시각 e와 main_motion_end_ms는 같은 자동 센서 도구에서 나왔고 실제 자연 복귀 완료의 독립 정답이 아니다. 발행 시점과 e의 관계(조기/구간/늦음)는 어떤 발행도 실제 복귀 완료를 증명하지 않는다.
>
> 이 표본의 비율은 전체 성능이나 대표성의 추정치가 아니다. 이상 사례 점검과 파형 확인을 위한 고정 목록이다(기본 20개는 세션×방향 추첨, 나머지는 이상 사례 점검용).

## 조건

- P1~P4 원본: `V2-S-P5-cal`에서 그 세션이 검증인 fold의 저장 예측. P5 원본: `V2-S-P1-cal`에서 P5가 검증인 fold.
- seed 20261021, 20261022, 20261023, 20261024, 20261025; 발행은 저장된 점수에서 `v2.issue_events`로 다시 만들었고 저장 로그와 비교했다. seed 평균 점수로 새 발행을 만들지 않았다.
- 점수는 1590 ms(첫 완전한 창의 마지막 샘플)부터 있다. 0~1580 ms는 그리지 않고 채우지 않았다.
- 그림: no plotting library; hand-written SVG; Python 3.12.10, NumPy 2.5.4.

## 표본별 요약

| 번호 | 세션 | 방향 | 원본 | 태그 | e | 동작 종료 | e−종료 | 상태/플래그 | 발행한 seed 수 | seed별 발행(시각 구간/방향) |
|---|---|---|---|---|---:|---:|---:|---|---:|---|
| S01 | P1 | UP | `raw_up.12.csv` | base | 2460 | 2150 | 310 | AUTO | 3/5 | 21: —<br>22: —<br>23: 2490 window/불일치(DOWN)<br>24: 2490 window/일치(UP)<br>25: 2040 early/일치(UP) |
| S02 | P1 | DOWN | `raw_down.11.csv` | base | 2030 | 1890 | 140 | AUTO | 4/5 | 21: 2090 window/일치(DOWN)<br>22: —<br>23: 2090 window/일치(DOWN)<br>24: 2090 window/일치(DOWN)<br>25: 2140 window/일치(DOWN) |
| S03 | P1 | LEFT | `raw_left.4.csv` | base | 2020 | 1940 | 80 | AUTO | 5/5 | 21: 2140 window/일치(LEFT)<br>22: 2140 window/일치(LEFT)<br>23: 2140 window/일치(LEFT)<br>24: 2090 window/일치(LEFT)<br>25: 2090 window/일치(LEFT) |
| S04 | P1 | RIGHT | `raw_right.11.csv` | base | 2750 | 2320 | 430 | AUTO | 5/5 | 21: 2440 early/일치(RIGHT)<br>22: 2390 early/일치(RIGHT)<br>23: 2440 early/일치(RIGHT)<br>24: 2440 early/일치(RIGHT)<br>25: 2490 early/일치(RIGHT) |
| S05 | P2 | UP | `raw_up.4.csv` | base | 1960 | 1890 | 70 | AUTO | 3/5 | 21: 2390 window/일치(UP)<br>22: —<br>23: —<br>24: 2390 window/일치(UP)<br>25: 2090 window/불일치(DOWN) |
| S06 | P2 | DOWN | `raw_down.13.csv` | base | 2470 | 2320 | 150 | AUTO | 2/5 | 21: —<br>22: —<br>23: —<br>24: 2540 window/일치(DOWN)<br>25: 2540 window/일치(DOWN) |
| S07 | P2 | LEFT | `raw_left.4.csv` | base | 2220 | 2180 | 40 | AUTO | 4/5 | 21: —<br>22: 2290 window/일치(LEFT)<br>23: 2340 window/일치(LEFT)<br>24: 2340 window/일치(LEFT); 3140 late/불일치(RIGHT)<br>25: 2340 window/일치(LEFT) |
| S08 | P2 | RIGHT | `raw_right.5.csv` | base | 2520 | 2400 | 120 | AUTO | 5/5 | 21: 2140 early/일치(RIGHT)<br>22: 2140 early/일치(RIGHT)<br>23: 2290 early/일치(RIGHT); 2840 window/일치(RIGHT); 3290 late/일치(RIGHT)<br>24: 2290 early/일치(RIGHT)<br>25: 2140 early/일치(RIGHT); 2640 window/일치(RIGHT); 2840 window/일치(RIGHT) |
| S09 | P3 | UP | `raw_up.13.csv` | base | 2870 | 2840 | 30 | AUTO | 2/5 | 21: 2990 window/일치(UP)<br>22: —<br>23: —<br>24: —<br>25: 3140 window/일치(UP) |
| S10 | P3 | DOWN | `raw_down.10.csv` | base | 2220 | 1990 | 230 | AUTO | 0/5 | 21: —<br>22: —<br>23: —<br>24: —<br>25: — |
| S11 | P3 | LEFT | `raw_left.9.csv` | base | 2690 | 2250 | 440 | REVIEW / early_motion | 2/5 | 21: 2440 early/일치(LEFT)<br>22: —<br>23: —<br>24: 3290 late/불일치(RIGHT)<br>25: — |
| S12 | P3 | RIGHT | `raw_right.3.csv` | base | 3210 | 3110 | 100 | AUTO | 3/5 | 21: 2190 early/불일치(UP)<br>22: —<br>23: 2340 early/일치(RIGHT)<br>24: —<br>25: 2240 early/일치(RIGHT) |
| S13 | P4 | UP | `raw_up.1.csv` | base | 2320 | 2170 | 150 | AUTO | 1/5 | 21: —<br>22: —<br>23: —<br>24: 2440 window/일치(UP)<br>25: — |
| S14 | P4 | DOWN | `raw_down.14.csv` | base | 2860 | 2550 | 310 | AUTO | 4/5 | 21: —<br>22: 2990 window/일치(DOWN); 3740 late/불일치(UP)<br>23: 2990 window/일치(DOWN); 3390 late/일치(DOWN)<br>24: 2990 window/일치(DOWN); 3390 late/일치(DOWN)<br>25: 2990 window/일치(DOWN) |
| S15 | P4 | LEFT | `raw_left.14.csv` | base | 2640 | 2290 | 350 | AUTO | 3/5 | 21: —<br>22: 2490 early/일치(LEFT)<br>23: 2640 window/일치(LEFT)<br>24: 2640 window/일치(LEFT)<br>25: — |
| S16 | P4 | RIGHT | `raw_right.3.csv` | base | 2450 | 2310 | 140 | AUTO | 2/5 | 21: —<br>22: —<br>23: 2590 window/일치(RIGHT)<br>24: 2490 window/일치(RIGHT)<br>25: — |
| S17 | P5 | UP | `raw_up.4.csv` | base | 2270 | 2020 | 250 | AUTO | 1/5 | 21: —<br>22: —<br>23: —<br>24: —<br>25: 1840 early/불일치(DOWN); 2440 window/일치(UP) |
| S18 | P5 | DOWN | `raw_down.6.csv` | base | 2220 | 2160 | 60 | AUTO | 4/5 | 21: 2290 window/일치(DOWN)<br>22: —<br>23: 2290 window/일치(DOWN)<br>24: 2290 window/일치(DOWN)<br>25: 2290 window/일치(DOWN) |
| S19 | P5 | LEFT | `raw_left.9.csv` | base | 2680 | 2160 | 520 | AUTO | 4/5 | 21: 2290 early/일치(LEFT)<br>22: —<br>23: 2290 early/일치(LEFT)<br>24: 1890 early/불일치(RIGHT); 2290 early/일치(LEFT)<br>25: 2290 early/일치(LEFT) |
| S20 | P5 | RIGHT | `raw_right.4.csv` | base | 2790 | 2730 | 60 | REVIEW / early_motion | 2/5 | 21: —<br>22: —<br>23: —<br>24: 2440 early/일치(RIGHT); 2740 early/일치(RIGHT)<br>25: 1990 early/불일치(LEFT); 2490 early/일치(RIGHT) |
| S21 | P1 | RIGHT | `raw_right.3.csv` | large_gap | 2790 | 1980 | 810 | AUTO | 5/5 | 21: 2140 early/일치(RIGHT)<br>22: 2140 early/일치(RIGHT); 2440 early/일치(RIGHT)<br>23: 2140 early/일치(RIGHT); 2440 early/일치(RIGHT)<br>24: 2140 early/일치(RIGHT)<br>25: 2140 early/일치(RIGHT) |
| S22 | P3 | LEFT | `raw_left.4.csv` | large_gap | 3210 | 2440 | 770 | REVIEW / early_motion | 3/5 | 21: 2690 early/일치(LEFT)<br>22: —<br>23: —<br>24: 3390 window/불일치(RIGHT)<br>25: 3390 window/불일치(RIGHT) |
| S23 | P5 | DOWN | `raw_down.10.csv` | large_gap | 2740 | 2020 | 720 | AUTO | 4/5 | 21: 2140 early/일치(DOWN)<br>22: —<br>23: 2140 early/일치(DOWN)<br>24: 2140 early/일치(DOWN)<br>25: 2140 early/일치(DOWN) |
| S24 | P5 | UP | `raw_up.13.csv` | large_gap | 2890 | 2170 | 720 | AUTO | 4/5 | 21: 1940 early/불일치(DOWN)<br>22: —<br>23: 1940 early/불일치(DOWN)<br>24: 1940 early/불일치(DOWN)<br>25: 1890 early/불일치(DOWN) |
| S25 | P4 | DOWN | `raw_down.16.csv` | large_gap | 2880 | 2200 | 680 | AUTO | 5/5 | 21: 1990 early/불일치(UP); 2740 early/일치(DOWN)<br>22: 1990 early/불일치(UP); 2690 early/일치(DOWN)<br>23: 1990 early/불일치(UP); 2390 early/일치(DOWN); 2640 early/일치(DOWN); 3090 window/일치(DOWN)<br>24: 1990 early/불일치(UP); 2390 early/일치(DOWN); 2690 early/일치(DOWN); 3090 window/일치(DOWN)<br>25: 2390 early/일치(DOWN); 2690 early/일치(DOWN) |
| S26 | P4 | LEFT | `raw_left.16.csv` | clipped_horizon | 3530 | 3370 | 160 | REVIEW / late_completion | 5/5 | 21: 3990 window/일치(LEFT)<br>22: 3540 window/일치(LEFT); 3940 window/일치(LEFT)<br>23: 3490 early/일치(LEFT); 3790 window/일치(LEFT)<br>24: 3440 early/일치(LEFT); 3790 window/일치(LEFT)<br>25: 3940 window/일치(LEFT) |

구간: early = e 전, window = [e, e+500], late = e+500 초과. 방향: 발행 클래스가 정답 방향과 같으면 일치.

## 클립 단위 집계

한 클립에서 여러 번 발행해도 한 번만 센다. 표본은 고정 목록이며 아래 수는 성능 추정치가 아니다.

- 표본 26개 중 5 seed 가운데 하나라도 발행한 표본: 25개
- 발행한 seed 수별 표본 수: 0개 seed → 1개 표본, 1개 seed → 2개 표본, 2개 seed → 5개 표본, 3개 seed → 5개 표본, 4개 seed → 7개 표본, 5개 seed → 6개 표본
- (표본, seed) 쌍 130개 중: 발행 ≥1 85, 발행 ≥2 20, 조기 발행 포함 44 (방향 일치 38, 불일치 12), 구간 안 일치 43, 구간 안 불일치 4, 늦음 일치 3, 늦음 불일치 3
- kind별 쌍 수: correct 43, duplicate 2, wrong_direction 4, early 44, late_unmatched 6
- 발행 이벤트 총수(클립 단위 아님): 111

seed별 (표본 수 기준):

| seed | 발행 ≥1 | 조기 | 정답(correct) | 방향 불일치 구간 안 | 중복 | 늦음 |
|---|---:|---:|---:|---:|---:|---:|
| 20261021 | 16 | 10 | 6 | 0 | 0 | 0 |
| 20261022 | 9 | 5 | 4 | 0 | 1 | 1 |
| 20261023 | 17 | 9 | 10 | 1 | 0 | 2 |
| 20261024 | 22 | 9 | 13 | 1 | 0 | 3 |
| 20261025 | 21 | 11 | 10 | 2 | 1 | 0 |

그룹별(표본 수 기준):

| 그룹 | 표본 수 | 발행 ≥1 인 표본 | 5 seed 모두 발행한 표본 |
|---|---:|---:|---:|
| 전체 | 26 | 25 | 6 |
| 태그 base | 20 | 19 | 3 |
| 태그 large_gap | 5 | 5 | 2 |
| 태그 clipped_horizon | 1 | 1 | 1 |
| 추가 표본만(base 아님) | 6 | 6 | 3 |

## 발행 목록

| 표본 | seed | 시각(ms) | t−e(ms) | 구간 | 발행 방향 | 방향 | kind | 점수 |
|---|---|---:|---:|---|---|---|---|---:|
| S01 | 20261023 | 2490 | 30 | window | DOWN | 불일치 | wrong_direction | 0.998 |
| S01 | 20261024 | 2490 | 30 | window | UP | 일치 | correct | 0.943 |
| S01 | 20261025 | 2040 | -420 | early | UP | 일치 | early | 0.903 |
| S02 | 20261021 | 2090 | 60 | window | DOWN | 일치 | correct | 0.995 |
| S02 | 20261023 | 2090 | 60 | window | DOWN | 일치 | correct | 0.999 |
| S02 | 20261024 | 2090 | 60 | window | DOWN | 일치 | correct | 0.997 |
| S02 | 20261025 | 2140 | 110 | window | DOWN | 일치 | correct | 0.999 |
| S03 | 20261021 | 2140 | 120 | window | LEFT | 일치 | correct | 0.990 |
| S03 | 20261022 | 2140 | 120 | window | LEFT | 일치 | correct | 0.993 |
| S03 | 20261023 | 2140 | 120 | window | LEFT | 일치 | correct | 0.998 |
| S03 | 20261024 | 2090 | 70 | window | LEFT | 일치 | correct | 1.000 |
| S03 | 20261025 | 2090 | 70 | window | LEFT | 일치 | correct | 1.000 |
| S04 | 20261021 | 2440 | -310 | early | RIGHT | 일치 | early | 0.999 |
| S04 | 20261022 | 2390 | -360 | early | RIGHT | 일치 | early | 0.986 |
| S04 | 20261023 | 2440 | -310 | early | RIGHT | 일치 | early | 0.997 |
| S04 | 20261024 | 2440 | -310 | early | RIGHT | 일치 | early | 1.000 |
| S04 | 20261025 | 2490 | -260 | early | RIGHT | 일치 | early | 1.000 |
| S05 | 20261021 | 2390 | 430 | window | UP | 일치 | correct | 0.829 |
| S05 | 20261024 | 2390 | 430 | window | UP | 일치 | correct | 0.962 |
| S05 | 20261025 | 2090 | 130 | window | DOWN | 불일치 | wrong_direction | 0.886 |
| S06 | 20261024 | 2540 | 70 | window | DOWN | 일치 | correct | 0.814 |
| S06 | 20261025 | 2540 | 70 | window | DOWN | 일치 | correct | 0.988 |
| S07 | 20261022 | 2290 | 70 | window | LEFT | 일치 | correct | 0.998 |
| S07 | 20261023 | 2340 | 120 | window | LEFT | 일치 | correct | 0.868 |
| S07 | 20261024 | 2340 | 120 | window | LEFT | 일치 | correct | 0.949 |
| S07 | 20261024 | 3140 | 920 | late | RIGHT | 불일치 | late_unmatched | 0.967 |
| S07 | 20261025 | 2340 | 120 | window | LEFT | 일치 | correct | 0.992 |
| S08 | 20261021 | 2140 | -380 | early | RIGHT | 일치 | early | 0.946 |
| S08 | 20261022 | 2140 | -380 | early | RIGHT | 일치 | early | 0.924 |
| S08 | 20261023 | 2290 | -230 | early | RIGHT | 일치 | early | 0.992 |
| S08 | 20261023 | 2840 | 320 | window | RIGHT | 일치 | correct | 0.995 |
| S08 | 20261023 | 3290 | 770 | late | RIGHT | 일치 | late_unmatched | 0.862 |
| S08 | 20261024 | 2290 | -230 | early | RIGHT | 일치 | early | 0.989 |
| S08 | 20261025 | 2140 | -380 | early | RIGHT | 일치 | early | 0.912 |
| S08 | 20261025 | 2640 | 120 | window | RIGHT | 일치 | correct | 0.990 |
| S08 | 20261025 | 2840 | 320 | window | RIGHT | 일치 | duplicate | 0.993 |
| S09 | 20261021 | 2990 | 120 | window | UP | 일치 | correct | 0.969 |
| S09 | 20261025 | 3140 | 270 | window | UP | 일치 | correct | 0.987 |
| S11 | 20261021 | 2440 | -250 | early | LEFT | 일치 | early | 0.943 |
| S11 | 20261024 | 3290 | 600 | late | RIGHT | 불일치 | late_unmatched | 0.999 |
| S12 | 20261021 | 2190 | -1020 | early | UP | 불일치 | early | 0.980 |
| S12 | 20261023 | 2340 | -870 | early | RIGHT | 일치 | early | 0.963 |
| S12 | 20261025 | 2240 | -970 | early | RIGHT | 일치 | early | 0.997 |
| S13 | 20261024 | 2440 | 120 | window | UP | 일치 | correct | 0.995 |
| S14 | 20261022 | 2990 | 130 | window | DOWN | 일치 | correct | 0.997 |
| S14 | 20261022 | 3740 | 880 | late | UP | 불일치 | late_unmatched | 0.966 |
| S14 | 20261023 | 2990 | 130 | window | DOWN | 일치 | correct | 1.000 |
| S14 | 20261023 | 3390 | 530 | late | DOWN | 일치 | late_unmatched | 0.979 |
| S14 | 20261024 | 2990 | 130 | window | DOWN | 일치 | correct | 0.975 |
| S14 | 20261024 | 3390 | 530 | late | DOWN | 일치 | late_unmatched | 0.995 |
| S14 | 20261025 | 2990 | 130 | window | DOWN | 일치 | correct | 0.904 |
| S15 | 20261022 | 2490 | -150 | early | LEFT | 일치 | early | 0.960 |
| S15 | 20261023 | 2640 | 0 | window | LEFT | 일치 | correct | 0.999 |
| S15 | 20261024 | 2640 | 0 | window | LEFT | 일치 | correct | 0.997 |
| S16 | 20261023 | 2590 | 140 | window | RIGHT | 일치 | correct | 0.998 |
| S16 | 20261024 | 2490 | 40 | window | RIGHT | 일치 | correct | 0.895 |
| S17 | 20261025 | 1840 | -430 | early | DOWN | 불일치 | early | 0.983 |
| S17 | 20261025 | 2440 | 170 | window | UP | 일치 | correct | 0.987 |
| S18 | 20261021 | 2290 | 70 | window | DOWN | 일치 | correct | 1.000 |
| S18 | 20261023 | 2290 | 70 | window | DOWN | 일치 | correct | 0.998 |
| S18 | 20261024 | 2290 | 70 | window | DOWN | 일치 | correct | 0.999 |
| S18 | 20261025 | 2290 | 70 | window | DOWN | 일치 | correct | 1.000 |
| S19 | 20261021 | 2290 | -390 | early | LEFT | 일치 | early | 0.950 |
| S19 | 20261023 | 2290 | -390 | early | LEFT | 일치 | early | 0.977 |
| S19 | 20261024 | 1890 | -790 | early | RIGHT | 불일치 | early | 0.978 |
| S19 | 20261024 | 2290 | -390 | early | LEFT | 일치 | early | 1.000 |
| S19 | 20261025 | 2290 | -390 | early | LEFT | 일치 | early | 1.000 |
| S20 | 20261024 | 2440 | -350 | early | RIGHT | 일치 | early | 0.849 |
| S20 | 20261024 | 2740 | -50 | early | RIGHT | 일치 | early | 0.993 |
| S20 | 20261025 | 1990 | -800 | early | LEFT | 불일치 | early | 0.946 |
| S20 | 20261025 | 2490 | -300 | early | RIGHT | 일치 | early | 0.830 |
| S21 | 20261021 | 2140 | -650 | early | RIGHT | 일치 | early | 1.000 |
| S21 | 20261022 | 2140 | -650 | early | RIGHT | 일치 | early | 1.000 |
| S21 | 20261022 | 2440 | -350 | early | RIGHT | 일치 | early | 0.966 |
| S21 | 20261023 | 2140 | -650 | early | RIGHT | 일치 | early | 1.000 |
| S21 | 20261023 | 2440 | -350 | early | RIGHT | 일치 | early | 0.986 |
| S21 | 20261024 | 2140 | -650 | early | RIGHT | 일치 | early | 0.990 |
| S21 | 20261025 | 2140 | -650 | early | RIGHT | 일치 | early | 1.000 |
| S22 | 20261021 | 2690 | -520 | early | LEFT | 일치 | early | 0.987 |
| S22 | 20261024 | 3390 | 180 | window | RIGHT | 불일치 | wrong_direction | 0.998 |
| S22 | 20261025 | 3390 | 180 | window | RIGHT | 불일치 | wrong_direction | 0.826 |
| S23 | 20261021 | 2140 | -600 | early | DOWN | 일치 | early | 1.000 |
| S23 | 20261023 | 2140 | -600 | early | DOWN | 일치 | early | 1.000 |
| S23 | 20261024 | 2140 | -600 | early | DOWN | 일치 | early | 0.998 |
| S23 | 20261025 | 2140 | -600 | early | DOWN | 일치 | early | 1.000 |
| S24 | 20261021 | 1940 | -950 | early | DOWN | 불일치 | early | 0.993 |
| S24 | 20261023 | 1940 | -950 | early | DOWN | 불일치 | early | 0.985 |
| S24 | 20261024 | 1940 | -950 | early | DOWN | 불일치 | early | 0.993 |
| S24 | 20261025 | 1890 | -1000 | early | DOWN | 불일치 | early | 0.996 |
| S25 | 20261021 | 1990 | -890 | early | UP | 불일치 | early | 1.000 |
| S25 | 20261021 | 2740 | -140 | early | DOWN | 일치 | early | 0.999 |
| S25 | 20261022 | 1990 | -890 | early | UP | 불일치 | early | 0.997 |
| S25 | 20261022 | 2690 | -190 | early | DOWN | 일치 | early | 1.000 |
| S25 | 20261023 | 1990 | -890 | early | UP | 불일치 | early | 0.966 |
| S25 | 20261023 | 2390 | -490 | early | DOWN | 일치 | early | 0.995 |
| S25 | 20261023 | 2640 | -240 | early | DOWN | 일치 | early | 1.000 |
| S25 | 20261023 | 3090 | 210 | window | DOWN | 일치 | correct | 0.975 |
| S25 | 20261024 | 1990 | -890 | early | UP | 불일치 | early | 0.998 |
| S25 | 20261024 | 2390 | -490 | early | DOWN | 일치 | early | 1.000 |
| S25 | 20261024 | 2690 | -190 | early | DOWN | 일치 | early | 0.989 |
| S25 | 20261024 | 3090 | 210 | window | DOWN | 일치 | correct | 0.902 |
| S25 | 20261025 | 2390 | -490 | early | DOWN | 일치 | early | 1.000 |
| S25 | 20261025 | 2690 | -190 | early | DOWN | 일치 | early | 1.000 |
| S26 | 20261021 | 3990 | 460 | window | LEFT | 일치 | correct | 1.000 |
| S26 | 20261022 | 3540 | 10 | window | LEFT | 일치 | correct | 1.000 |
| S26 | 20261022 | 3940 | 410 | window | LEFT | 일치 | duplicate | 1.000 |
| S26 | 20261023 | 3490 | -40 | early | LEFT | 일치 | early | 0.834 |
| S26 | 20261023 | 3790 | 260 | window | LEFT | 일치 | correct | 1.000 |
| S26 | 20261024 | 3440 | -90 | early | LEFT | 일치 | early | 0.979 |
| S26 | 20261024 | 3790 | 260 | window | LEFT | 일치 | correct | 0.974 |
| S26 | 20261025 | 3940 | 410 | window | LEFT | 일치 | correct | 1.000 |

## 무결성 검사

- 발행 재도출: 130/130 (표본×seed) 일치. 시각·클래스·kind 정확히 같음, 점수 최대 차이 0.00e+00, 점수까지 비트 단위로 같은 검사 130건.
- 학습 제외: 130/130 (표본×seed). 각 표본은 해당 fold의 검증 원본이며 학습 부분(train_sources − 검증 원본)과 평가용(eval_sources)에 없다. 목록은 summary.json의 `integrity.training_exclusion.checks`.
- 창 정렬: 판정 시각이 `decision_times`(1590~3990 ms, 50 ms 간격)와 같고 `v2.windows`의 마지막 행이 해당 시각의 원시 행과 같음 (26/26 표본).
- 저장 target이 [e, e+150) 양성 규칙과 같음: 130/130 (표본×seed).

## 한계

- 표본은 고정 목록(세션×방향 추첨 20개 + 이상 사례 점검용 추가)이며 비율은 전체 성능이나 대표성의 추정치가 아니다.
- e와 main_motion_end_ms는 같은 자동 센서 도구의 결과다. 발행이 e 앞/뒤에 놓인 것은 실제 복귀 완료 여부를 증명하지 않는다.
- E=60과 5 seed는 진단용 고정 조건이며 기존 선택 E를 대체하지 않는다. 원본은 fold마다 한 번씩만 검증으로 쓰이므로 seed 5개는 같은 원본의 반복 관측이다.
- 저장된 예측과 발행 로그를 읽기만 했다. 학습·추론·후처리 변경은 하지 않았다.
- 그림 도구: 그래프 라이브러리 없이 손으로 쓴 SVG. 파형 축 범위는 표본마다 자동이며 표본 간 크기 비교용이 아니다.
