# Edge Impulse 제스처 데이터 수집

## 2026-10-06 — 5배 증강 시험 데이터

`data/windows-augmented-5x/`에 학습 145개를 원본 포함 725개(UP 195/DOWN 125/LEFT 120/RIGHT 135/NONE 150)로 늘린 로컬 데이터를 생성했다. 테스트 36개는 원본 그대로 유지한다. 증강 방식(회전·잡음 강도)과 업로드 후 재학습 결과(validation-testing 괴리 포함)는 [ModelExperiments.md의 실험 7](ModelExperiments.md)에 기록했다.

- 생성 도구: `node tools/augment-gesture-windows.js`. 출력 폴더가 있으면 덮어쓰지 않고 종료한다. 다른 출력 경로를 첫 인자로 지정할 수 있다.
- `manifest.csv`에 원본 ID·부모 파일·변형 번호, `augmentation.json`에 설정과 수량을 기록한다.

이 문서는 XIAO nRF52840 Sense의 가속도계와 자이로스코프 6축 데이터를 100 Hz로 Edge Impulse에 전달하기 위한 안내다. 현재 채택한 모델 구조는 5절 끝의 링크를 참고한다. 데이터 수집 중에는 별도 펌웨어를 사용하므로 기존 BLE 포인터·스와이프 기능이 일시적으로 중단된다. 수집이 끝나면 `firmware/ble_poc/ble_poc.ino`를 다시 업로드하면 된다.

## 준비된 환경

2026-09-28 현재 PC에서 다음 항목을 설치하고 실행을 확인했다.

- Node.js `24.18.0`
- npm `11.16.0`
- Edge Impulse CLI `1.40.0`
- Seeed Arduino LSM6DS3 `2.0.7`
- Arduino IDE 동봉 CLI `1.5.1`
- Seeed nRF52 Boards(non-mbed) `1.1.13`

같은 날짜에 COM6의 실물 보드에 수집 펌웨어를 업로드했다. 3.034초 동안 유효한 6축 샘플 304개를 받아 `100.2 Hz`를 관측했고, 정지 상태의 평균 가속도 벡터 크기는 `9.8049 m/s²`였다. Edge Impulse Data Forwarder도 100 Hz와 6축을 감지하여 Studio 프로젝트 연결에 성공했다. 이는 센서와 전송 경로의 짧은 정상 동작 확인이며 센서 보정이나 제스처 분류 성능 검증은 아니다.

Edge Impulse 계정과 프로젝트 생성은 사용자 계정으로 진행해야 한다. 공식 Studio: https://studio.edgeimpulse.com/

현재 전용 프로젝트는 `RingPilot`이며 Data acquisition 주소는 다음과 같다.

https://studio.edgeimpulse.com/studio/1122630/acquisition/training

## 1. 수집 펌웨어 업로드

1. 휴대폰 대신 XIAO 보드를 PC USB에 연결한다.
2. Arduino IDE에서 `firmware/imu_capture/imu_capture.ino`를 연다.
3. 보드를 `Seeed XIAO nRF52840 Sense`로 선택한다.
4. XIAO가 연결된 COM 포트를 선택하고 업로드한다.
5. 잠깐 시리얼 모니터를 115200 baud로 열어 쉼표로 구분된 숫자 6개가 계속 나오는지 확인한다.
6. Edge Impulse 실행 전에는 시리얼 모니터를 반드시 닫는다. 하나의 COM 포트를 두 프로그램이 동시에 열 수 없다.

출력 순서와 단위:

```text
accX,accY,accZ,gyrX,gyrY,gyrZ
m/s^2,m/s^2,m/s^2,deg/s,deg/s,deg/s
```

정지 상태에서는 가속도 벡터 크기가 약 `9.81 m/s²`, 자이로 값이 대체로 `0 deg/s` 부근이어야 한다. 센서 편차와 노이즈 때문에 각 축이 정확히 이 값일 필요는 없다.

## 2. Edge Impulse 연결

저장소 루트의 터미널에서 실행한다.

```powershell
.\tools\start-edge-impulse.cmd
```

최초 실행 시 다음 항목을 묻는다.

1. Edge Impulse 계정 이메일과 비밀번호
2. 연결할 프로젝트
3. 감지된 6개 축 이름: `accX,accY,accZ,gyrX,gyrY,gyrZ`
4. 장치 이름: 예를 들어 `RingPilot-XIAO`

다른 프로젝트로 다시 연결하려면 설정을 초기화한다.

```powershell
.\tools\start-edge-impulse.cmd --clean
```

도우미는 Data Forwarder의 샘플링 주파수를 100 Hz로 고정한다. PowerShell 실행 정책을 변경하지 않기 위해 npm의 `.cmd` 실행 파일을 직접 호출한다.

## 3. 첫 데이터 수집

> 2026-09-28 설계 갱신: 현행 후보는 장기 causal window로 “방금 완료된 제스처”를 검출하는 구조다. 아래 3절의 `raw_*` 수집은 구조 검증용 원시 자료이며, 파일 라벨을 그대로 최종 학습 클래스에 사용하지 않는다. 5절은 이전 수집/게이트 제안의 기록이다. 현재 구조는 [제스처 인식 구조안](제스처인식구조안.md), 위험 분석은 [Windowing 검토](Windowing검토.md)를 따른다.

Edge Impulse Studio의 **Data acquisition**에서 다음 라벨을 사용한다.

- `idle`: 손을 편하게 둔 상태
- `raw_up`
- `raw_down`
- `raw_left`
- `raw_right`
- `other`: 자세 변경, 손가락 굽힘 등 명령이 아니어야 하는 동작

Edge Impulse의 **수집 샘플**과 모델의 **입력 윈도우**는 다르다. 10초를 수집하면 원시 파일은 1개지만, Impulse를 만들 때 예를 들어 1000 ms 윈도우로 잘려 여러 학습 입력이 된다. 잘린 윈도우는 원본 파일의 라벨을 물려받으므로, 한 파일 안에 해당 라벨과 무관한 긴 구간을 넣으면 학습 데이터가 오염된다.

현재 소량 검증 수집 방식:

- `idle`: 10초 × 3개. 파일 전체에서 실제 착용 자세로 정지한다.
- `other`: 10초 × 3개. 목표 스와이프는 제외하고 손가락 굽힘, 손목 회전, 자세 조정 같은 비명령 움직임을 이어서 수행한다. 대부분의 시간을 완전히 정지해 `idle`과 겹치게 만들지 않는다.
- 방향 제스처: 3초짜리 파일 하나에 해당 방향의 자연스러운 이동과 원위치 복귀를 정확히 한 번 넣는다. 처음 약 0.7초는 편한 시작 자세, 중간은 이동과 자연 복귀, 마지막은 다시 편한 자세로 둔다.
- 방향마다 우선 10개씩 수집한다. 기준은 보통 속도 6개, 무리하지 않은 빠른 실사용 속도 2개, 느린 속도 2개다. 속도 구간이 한두 번 겹쳐도 다시 받을 필요는 없다. 일부러 센서 한계까지 세게 움직이지 않는다.
- 이 파일들은 파형과 지속시간을 확인하는 원시 기록이다. Studio에서 임의로 1초 crop하거나 3초 파일의 `raw_*` 라벨을 그대로 방향 분류 학습에 사용하지 않는다. 이후 별도의 완료 시점 주석으로 causal window와 목표 라벨을 생성한다.

따라서 10초짜리 방향 파일 전체를 하나의 제스처로 간주하지 않는다. 긴 파일에 여러 동작을 기록하는 방식도 가능하지만, 이 경우 각 동작 구간을 별도 샘플로 분할해야 한다.

2026-09-28 현재 `raw_up`, `raw_down`, `raw_left`, `raw_right`를 각각 10개씩 수집·점검했다. 이 40개는 구조 검증용 소량 자료이며 최종 데이터셋 규모가 아니다. 이상치 후보를 바로 삭제하지 않고 깨끗한 보충 샘플을 추가한 뒤, 원본과 보충본을 함께 연속 replay에서 평가한다.

완료 시점 정의와 자동 주석 기준은 [제스처 인식 구조안의 '현재 완료 시점 주석 기준'](제스처인식구조안.md)을 따른다. 계산 도구는 `tools/suggest-gesture-completions.js`, 결과는 `data/annotations/gesture-completions.csv`다.

초기 데이터가 실제로 분리되는지 확인한 다음, 서로 다른 속도·각도·착용 위치·수집 세션을 포함해 라벨별 100회 이상으로 늘린다. 같은 연속 기록을 잘라 학습/시험 양쪽에 넣으면 성능이 부풀려질 수 있으므로 수집 세션 단위로 분리한다.

## 4. 초기 모델 권장값

- Window size 후보: `1600 ms`를 기본, `1200 ms`를 비교군으로 사용한다. 1차 선형 진단에서 800 ms는 AUTO 30개 중 24개의 양성 window가 주동작 시작을 잃어 주 후보에서 제외했다. 1600 ms가 실제 causal CNN/TCN에서도 우월하다는 뜻은 아니며 세부 결과는 [causal window 길이 1차 비교](WindowLengthComparison.md)를 참고한다.
- Window increase 후보: Window size의 `25~50%`
- Processing block: Raw Data 기반 1D 분류와 Spectral Analysis를 비교
- Learning block: Classification
- 배포 형식: Arduino Library, Quantized `int8`

Spectral Analysis는 공식 문서상 반복 운동과 진동 분석에 적합하다. RingPilot의 상하좌우 동작은 일회성 과도 신호이며 반대 방향끼리 파형 부호와 시간 순서가 중요할 수 있으므로, 주파수 특징만 미리 확정하지 않는다. Raw Data/시간 순서 기반 모델과 실제 검증 결과를 비교해서 선택한다.

정확도 하나만 보지 말고 confusion matrix, 클래스별 recall, `idle` 상태의 분당 오인식 횟수, 명령 중복 발생률, 실제 명령 지연을 함께 확인한다. 모델이 준비되면 생성된 Arduino 라이브러리가 현재 non-mbed 코어에서 컴파일되는지 먼저 검증한 뒤 BLE 펌웨어와 합친다.

## 5. 초기 설계안(검토 후 기각)

2026-09-28 설계 갱신 전까지의 가안이었던 "움직임 게이트 + 이벤트 분류기"(시작 임계값으로 고정 길이 버퍼를 열고 `UP/DOWN/LEFT/RIGHT/OTHER`로 분류한 뒤 정지 확인 후 재무장하는 구조)는 검토 끝에 채택하지 않았다. 경계 규칙과 느린 복귀 처리에서 오류가 추가로 생긴다는 것이 기각 이유다. 기각 근거는 [제스처 인식 구조안의 '대안 비교 및 선택 이유'](제스처인식구조안.md)에 정리돼 있다("motion gate 후 이벤트 crop" 행).

현재 채택한 구조(장기 맥락 causal 모델 + 완료 시점 기반 라벨링)는 [제스처 인식 구조안](제스처인식구조안.md)에, 두 구조를 저울질한 위험 분석 과정은 [Windowing 설계 검토](Windowing검토.md)에 있다.

## 문제 해결

- `edge-impulse-data-forwarder` PowerShell 스크립트 실행 오류: 이 문서의 `.cmd` 도우미를 사용한다.
- COM 포트 열기 실패: Arduino 시리얼 모니터 등 포트를 사용하는 프로그램을 닫는다.
- XIAO 포트가 사라짐: RST 버튼을 빠르게 두 번 눌러 부트로더 포트로 진입한 뒤 다시 업로드한다.
- `ERROR: IMU initialization failed`: 보드가 Sense 모델인지 확인하고 전원을 다시 연결한다.
- 축 수가 6개로 감지되지 않음: `--clean`으로 다시 시작하고 시리얼 출력에 숫자 6개만 있는지 확인한다.

## 참고

- Edge Impulse CLI: https://github.com/edgeimpulse/edge-impulse-cli
- Edge Impulse 지원 하드웨어: https://docs.edgeimpulse.com/docs/edge-ai-hardware/mcu-%2B-ai-accelerators
- Seeed XIAO nRF52840 Sense 동작 인식: https://wiki.seeedstudio.com/XIAOEI/
- Edge Impulse의 윈도우 분할 설명: https://docs.edgeimpulse.com/docs/tutorials/end-to-end-tutorials/audio/audio-classification
- Spectral Analysis 블록: https://docs.edgeimpulse.com/docs/edge-impulse-studio/processing-blocks/spectral-features
