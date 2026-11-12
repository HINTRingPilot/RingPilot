// 제스처 추론 펌웨어(firmware/imu_ble_stream 복사본 + 추론). 기존 IMU 스트림·상태 알림은 그대로라 지금 앱이 그대로 붙는다.
// 추가: 100 Hz 샘플마다 src/gesture_runtime(온라인 영점·입력 처리·TCN·발행 규칙·발행 뒤 입력 지우기)을 돌리고, 발행을 BLE 알림으로 보낸다.
// 발행 패킷: [순번 uint8][클래스 uint8(1=UP 2=DOWN 3=LEFT 4=RIGHT)][점수×1000 uint16 LE][슬롯 uint32 LE].
// 발행하면 LED가 0.7초 켜진다: 위 = 빨강, 아래 = 파랑, 왼쪽 = 흰색, 오른쪽 = 노랑(상태 표시의 짧은 초록·파랑 깜빡임과 헷갈리지 않게 초록은 쓰지 않는다).
// 시리얼 명령: l = 지연 통계, r = 통계 초기화, ? = 상태. 판정 시간은 DWT 사이클로 잰다(이 코어의 micros()는 약 1 ms 단위다). 측정 조건·기록은 docs/experiments/ble-v2/latency-01/README.md.
// 센서 읽기는 우선순위 높은 태스크(samplerTask)가 10 ms마다 해서, loop에서 도는 추론이 읽기를 밀지 않는다. 읽은 값은 잠금 없는
// 대기열 두 개(BLE 전송용 ring, 판정용 gyroQueue)로 loop에 넘긴다. 각 대기열은 태스크만 head를, loop만 tail을 바꾼다. 가득 차면 새 값을 버리고 센다.
// I2C는 imuMutex로 지킨다. 샘플링은 구독 여부와 상관없이 돌아 BLE 없이도 추론 시간을 잴 수 있다. 슬롯이 비면 판정 입력만 직전 값으로 채우고 센다.
//
// IMU 6축을 BLE 알림으로 스트리밍하는 펌웨어. 100 Hz, ±4 g, ±2000 dps로 읽어
// (빠른 동작에서 ±1000 dps 포화를 피하려고 자이로 범위를 이전 USB 수집 펌웨어의 ±1000보다 넓혔다)
// 여러 샘플을 한 알림에 묶어 보낸다. USB 없이 배터리만으로 무선 수집을 시험하기 위한 것이다.
// 센터 스위치(D1): 짧게(0.5초 미만) = 클릭(일시정지 중이면 재개), 0.5~2초 = 일시정지(연결 유지), 2초 이상 = System OFF.
// System OFF에서는 센터를 누르면 재부팅한다. 일시정지는 BLE 연결을 유지한 채 IMU를 끄고 연결 간격을 늘린다.
// 데이터 패킷: [첫 샘플 슬롯 uint32 LE][샘플 수 uint8] + 샘플마다 accX,accY,accZ,gyrX,gyrY,gyrZ 센서 원시값 int16 LE.
// 원시값 환산(±4 g, ±2000 dps 설정): 가속도 1 LSB = 0.122 mg, 자이로 1 LSB = 0.070 dps (LSM6DS3 라이브러리 calcAccel/calcGyro와 동일).
// 범위를 바꾸면 android MainActivity의 환산 계수도 같이 바꿔야 한다.
// 상태 패킷: [상태 uint8][이벤트 uint8][부팅 후 ms uint32 LE][트리거 후 ms uint32 LE] (재개·재연결 지연 측정용).

#include <Adafruit_TinyUSB.h>  // 업로드 시 자동 리셋(1200bps)을 유지하려고 포함
#include <bluefruit.h>
#include <LSM6DS3.h>
#include <Wire.h>
#include <RingPilotTransport.h>
#include <RingPilotBleMailbox.h>

#include "src/gesture_runtime.h"

static const uint32_t kSampleRateHz = 100;
static const uint32_t kCyclesPerUs = F_CPU / 1000000;
static const uint16_t kGyroQueueSize = 64;         // 판정 대기열, 약 0.64초 분량
static const uint8_t kCenterPin = 1;               // D1, 사용자 확인
static const uint32_t kDebounceMs = 30;            // 이보다 짧은 누름은 접점 튐으로 무시
static const uint32_t kPauseHoldMs = 500;          // 이 시간 미만은 클릭, 이상은 일시정지
static const uint32_t kPowerOffHoldMs = 2000;      // 누르고 있는 동안 이 시간에 도달하면 System OFF
static const uint8_t kChargeCurrentPin = 22;       // P0.13(HICHG). 입력(open)이면 50mA로 알려짐
static const uint16_t kHeaderBytes = 5;
static const uint16_t kSampleBytes = 12;
static const uint16_t kMaxSamplesPerPacket = 10;   // 묶음 대기 지연을 최대 약 100 ms로 제한
static const uint16_t kRingSize = 256;             // 약 2.56초 분량
static const uint16_t kIdleLoopDelayMs = 20;       // 스트리밍하지 않을 때 CPU를 쉬게 하는 간격
static const float kGyroDpsPerLsb = 0.07f;         // ±2000 dps 설정의 환산값(학습 데이터와 같음)
static const uint16_t kLatencyHistory = 1024;      // 판정 시간 기록 개수(약 51초)
static const uint32_t kMaxFilledSlots = 20;        // 이보다 긴 공백은 채우지 않고 판정 상태를 초기화한다

// 연결 파라미터 단위: 간격 1.25 ms, 감시 시간 10 ms.
static const uint16_t kStreamInterval = 9;     // 11.25 ms
static const uint16_t kStreamLatency = 0;
static const uint16_t kStreamTimeout = 200;    // 2초
static const uint16_t kPausedInterval = 80;    // 100 ms
static const uint16_t kPausedLatency = 4;      // 최대 4번 연결 이벤트를 건너뛸 수 있음
static const uint16_t kPausedTimeout = 400;    // 4초. (1 + latency) * interval * 2보다 커야 한다

enum DeviceState : uint8_t { STATE_STREAMING = 0, STATE_PAUSED = 1 };
enum StatusEvent : uint8_t { EVENT_SUBSCRIBED = 0, EVENT_PAUSED = 1, EVENT_RESUMED = 2, EVENT_FIRST_DATA = 3 };

struct Sample {
  uint32_t slot;  // 부팅 후 10 ms 슬롯 번호. 빠진 슬롯은 수신 쪽에서 간격으로 드러난다.
  int16_t v[6];
};

LSM6DS3 imu(I2C_MODE, 0x6A);
BLEService imuService("b27a2000-8c5e-4b62-9a21-33dd714e9001");
BLECharacteristic imuStream("b27a2001-8c5e-4b62-9a21-33dd714e9001");
BLECharacteristic imuStatus("b27a2002-8c5e-4b62-9a21-33dd714e9001");
BLECharacteristic gestureEvent("b27a2003-8c5e-4b62-9a21-33dd714e9001");  // 기존 특성 뒤에 더해 기존 핸들을 유지한다

static Sample ring[kRingSize];
static volatile uint32_t ringHead = 0;  // 다음에 쓸 위치(누적 개수). 태스크만 바꾼다
static volatile uint32_t ringTail = 0;  // 다음에 보낼 위치(누적 개수). loop만 바꾼다
static uint32_t droppedSamples = 0;
static uint32_t sentPackets = 0;
static SemaphoreHandle_t imuMutex = nullptr;
static bool haveRead = false;      // 읽기 태스크 쪽: 직전 읽기가 있는지
static uint16_t connHandle = BLE_CONN_HANDLE_INVALID;

static DeviceState state = STATE_STREAMING;
static uint32_t triggerMs = 0;            // 부팅(0) 또는 재개 클릭을 뗀 시각
static bool awaitingFirstData = true;     // 트리거 이후 첫 데이터 패킷을 아직 못 보냈는지
static uint32_t clickCount = 0;           // 짧은 클릭 수. 마우스 클릭 연결 전까지는 세기만 한다

struct GyroItem {
  uint32_t slot;
  uint32_t readCycles;
  float gyro[3];
};

static GyroItem gyroQueue[kGyroQueueSize];
static volatile uint32_t gyroHead = 0;   // 태스크만 바꾼다
static volatile uint32_t gyroTail = 0;   // loop만 바꾼다
static volatile bool gestureRestart = false;  // loop에서 판정 상태를 초기화한다
static uint32_t queueDropped = 0;
static bool haveConsumed = false;  // loop 쪽: 직전 판정 입력이 있는지
static uint32_t lastConsumedSlot = 0;
static float lastGyro[3] = {0.0f, 0.0f, 0.0f};
static uint32_t decisionUs[kLatencyHistory];
static uint32_t decisionLagUs[kLatencyHistory];  // 판정에 쓴 마지막 샘플을 읽은 순간부터 판정 완료까지
static uint32_t decisionCount = 0;
static uint32_t sampleOnlyMaxUs = 0;
static uint32_t filledSlots = 0;
static uint32_t resetGaps = 0;
static uint32_t issuedCount = 0;
static uint8_t gestureSeq = 0;
static int16_t lastRaw[6] = {0, 0, 0, 0, 0, 0};
static uint32_t repeatedReads = 0;     // 6축이 직전 읽기와 모두 같은 횟수(센서가 새 값을 내기 전에 읽음)
static uint32_t totalReads = 0;
static uint32_t lastReadCycles = 0;
static uint32_t maxReadGapUs = 0;
static uint32_t maxReadUs = 0;         // I2C 읽기 한 번(6축)에 걸린 시간
static uint32_t lateReads = 0;         // 직전 읽기에서 12 ms 넘게 지난 읽기(주기 10 ms)
static uint32_t earlyReads = 0;        // 직전 읽기에서 8 ms 안에 온 읽기

static const uint32_t kGestureLedMs = 700;
static uint32_t gestureLedUntil = 0;
static bool gestureLedOn = false;

static uint32_t pressStart = 0;
static bool pauseCueShown = false;
static uint32_t lastBlink = 0;
static bool blinkLit = false;

static void ledsOff() {
  digitalWrite(LED_RED, HIGH);  // 이 보드의 LED는 LOW에서 켜짐
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(LED_BLUE, HIGH);
}

static ringpilot::Transport transport;
static ringpilot::BleMailbox linkMailbox;
static ringpilot::BleMailbox::Snapshot loopLink = {BLE_CONN_HANDLE_INVALID, 0, 0, false, false, false};
static_assert(ringpilot::Transport::NotifyBudgetMs >= BLE_GENERIC_TIMEOUT + 20,
              "Transport wait budget must cover the installed Bluefruit timeout");

static bool connected() {
  return connHandle != BLE_CONN_HANDLE_INVALID && linkMailbox.current(loopLink);
}

static bool dataSubscribed() {
  return connected() && imuStream.notifyEnabled(connHandle);
}

// Only loop calls these queue operations. Callbacks publish bounded snapshots.
static void sendStatus(StatusEvent event) {
  const uint32_t now = millis();
  const uint32_t sinceTrigger = now - triggerMs;
  uint8_t packet[10];
  packet[0] = state;
  packet[1] = event;
  memcpy(packet + 2, &now, 4);
  memcpy(packet + 6, &sinceTrigger, 4);
  imuStatus.write(packet, sizeof(packet));
  transport.enqueueStatus(packet, event == EVENT_RESUMED);
}

static void applyLinkMailbox() {
  loopLink = linkMailbox.snapshot(true);
  connHandle = loopLink.handle;
  transport.synchronize(loopLink.linkEpoch, loopLink.gestureEpoch,
                        connHandle != BLE_CONN_HANDLE_INVALID,
                        loopLink.statusEnabled, loopLink.gestureEnabled);
  if (loopLink.statusSubscribed) sendStatus(EVENT_SUBSCRIBED);
}

static bool sendStatusPacket(void* context, const uint8_t* packet, uint8_t length) {
  (void) context;
  bool boundary;
  const bool accepted = linkMailbox.notifyCurrent(loopLink, ringpilot::BleMailbox::Status,
                                                 imuStatus, packet, length, boundary);
  if (boundary) transport.noteInFlightBoundary();
  return accepted;
}

static bool sendImuPacket(const uint8_t* packet, uint8_t length) {
  if (!transport.imuReady()) return false;
  bool boundary;
  const bool accepted = linkMailbox.notifyCurrent(loopLink, ringpilot::BleMailbox::Data,
                                                 imuStream, packet, length, boundary);
  if (boundary) transport.noteInFlightBoundary();
  return accepted;
}

static void requestConnParams(uint16_t interval, uint16_t latency, uint16_t timeout) {
  if (!connected()) return;
  BLEConnection* conn = Bluefruit.Connection(connHandle);
  if (conn) conn->requestConnectionParameter(interval, latency, timeout);
}

static void onConnect(uint16_t handle) {
  linkMailbox.onConnect(handle);
  BLEConnection* conn = Bluefruit.Connection(handle);
  if (conn) {
    conn->requestPHY();
    conn->requestDataLengthUpdate();
    conn->requestMtuExchange(247);
  }
}

static void onDisconnect(uint16_t handle, uint8_t reason) {
  (void) reason;
  linkMailbox.onDisconnect(handle);
}

static void onStatusCccd(uint16_t handle, BLECharacteristic* chr, uint16_t value) {
  (void) chr;
  linkMailbox.onStatusCccd(handle, value);
}

static void onGestureCccd(uint16_t handle, BLECharacteristic* chr, uint16_t value) {
  (void) chr;
  linkMailbox.onGestureCccd(handle, value);
}

static bool sendGesturePacket(void* context, const uint8_t* packet, uint8_t length) {
  (void) context;
  bool boundary;
  const bool accepted = linkMailbox.notifyCurrent(loopLink, ringpilot::BleMailbox::Gesture,
                                                 gestureEvent, packet, length, boundary);
  if (boundary) transport.noteInFlightBoundary();
  return accepted;
}

static uint16_t samplesPerPacket() {
  if (!connected()) return 1;
  BLEConnection* conn = Bluefruit.Connection(connHandle);
  if (!conn) return 1;
  uint16_t payload = conn->getMtu() - 3;
  uint16_t count = (payload - kHeaderBytes) / kSampleBytes;
  if (count < 1) count = 1;
  if (count > kMaxSamplesPerPacket) count = kMaxSamplesPerPacket;
  return count;
}

static void imuPowerDown() {
  imu.writeRegister(LSM6DS3_ACC_GYRO_CTRL1_XL, 0x00);  // 가속도 power-down
  imu.writeRegister(LSM6DS3_ACC_GYRO_CTRL2_G, 0x00);   // 자이로 power-down
}

static bool imuStart() {
  imu.settings.accelEnabled = 1;
  imu.settings.accelRange = 4;
  imu.settings.accelSampleRate = 104;
  imu.settings.accelBandWidth = 50;
  imu.settings.gyroEnabled = 1;
  imu.settings.gyroRange = 2000;
  imu.settings.gyroSampleRate = 104;
  imu.settings.gyroBandWidth = 50;
  return imu.begin() == 0;
}

// 시리얼 확인용. 발행과, 발행되지 않은 방향 후보(점수 0.5 이상)를 슬롯 시각과 함께 찍는다. 판정 시간 측정에는 들어가지 않는다.
static void printDecision(const GrDecision& d, uint32_t slot) {
  static const char* const kNames[GT_CLASSES] = {"NONE", "UP", "DOWN", "LEFT", "RIGHT"};
  int top = 0;
  for (int n = 1; n < GT_CLASSES; n++) {
    if (d.scores[n] > d.scores[top]) top = n;
  }
  if (d.issued < 0 && (top == 0 || d.scores[top] < 0.5f)) return;
  Serial.print(d.issued >= 0 ? "GESTURE " : "cand ");
  Serial.print(kNames[d.issued >= 0 ? d.issued : top]);
  Serial.print(" ");
  Serial.print(d.scores[d.issued >= 0 ? d.issued : top], 2);
  Serial.print(" t=");
  Serial.println(slot * 0.01f, 2);
}

static void showGestureLed(int8_t cls) {
  ledsOff();
  if (cls == 1 || cls == 3 || cls == 4) digitalWrite(LED_RED, LOW);
  if (cls == 2 || cls == 3) digitalWrite(LED_BLUE, LOW);
  if (cls == 3 || cls == 4) digitalWrite(LED_GREEN, LOW);
  gestureLedUntil = millis() + kGestureLedMs;
  gestureLedOn = true;
  blinkLit = false;
}

static void sendGesture(const GrDecision& d, uint32_t slot) {
  issuedCount++;
  showGestureLed(d.issued);
  applyLinkMailbox();
  if (!transport.gestureReady()) return;
  uint8_t packet[8];
  const uint16_t score = static_cast<uint16_t>(d.scores[d.issued] * 1000.0f);
  packet[0] = gestureSeq++;
  packet[1] = static_cast<uint8_t>(d.issued);
  memcpy(packet + 2, &score, 2);
  memcpy(packet + 4, &slot, 4);
  transport.enqueueGesture(packet, millis());
}

static void startCycleCounter() {
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static void pushGesture(const float gyro[3], uint32_t slot, uint32_t readCycles) {
  GrDecision decision;
  const uint32_t t0 = DWT->CYCCNT;
  const int decided = gr_push(gyro, &decision);
  const uint32_t t1 = DWT->CYCCNT;
  const uint32_t us = (t1 - t0) / kCyclesPerUs;
  if (!decided) {
    if (us > sampleOnlyMaxUs) sampleOnlyMaxUs = us;
    return;
  }
  decisionUs[decisionCount % kLatencyHistory] = us;
  decisionLagUs[decisionCount % kLatencyHistory] = (t1 - readCycles) / kCyclesPerUs;
  decisionCount++;
  if (decision.issued >= 0) sendGesture(decision, slot);
  if (Serial) printDecision(decision, slot);
}

static void printPercentiles(const char* label, const uint32_t* values, uint32_t n) {
  static uint32_t sorted[kLatencyHistory];
  if (n == 0) return;
  memcpy(sorted, values, n * sizeof(uint32_t));
  for (uint32_t i = 1; i < n; i++) {
    const uint32_t v = sorted[i];
    uint32_t j = i;
    while (j > 0 && sorted[j - 1] > v) {
      sorted[j] = sorted[j - 1];
      j--;
    }
    sorted[j] = v;
  }
  Serial.print(label);
  Serial.print(" median/p95/max: ");
  Serial.print(sorted[n / 2]); Serial.print(" / ");
  Serial.print(sorted[n * 95 / 100]); Serial.print(" / ");
  Serial.println(sorted[n - 1]);
}

static void printLatency() {
  const uint32_t n = decisionCount < kLatencyHistory ? decisionCount : kLatencyHistory;
  Serial.print("Decisions: "); Serial.println(decisionCount);
  printPercentiles("Decision us", decisionUs, n);
  printPercentiles("Sample-to-decision us", decisionLagUs, n);
  Serial.print("Sample-only max us: "); Serial.println(sampleOnlyMaxUs);
  Serial.print("Reads/repeated: "); Serial.print(totalReads); Serial.print(" / "); Serial.println(repeatedReads);
  Serial.print("Read gap max us, >12ms, <8ms: ");
  Serial.print(maxReadGapUs); Serial.print(", "); Serial.print(lateReads); Serial.print(", "); Serial.println(earlyReads);
  Serial.print("Read max us: "); Serial.println(maxReadUs);
  Serial.print("Gyro queue dropped: "); Serial.println(queueDropped);
  Serial.print("Filled slots: "); Serial.println(filledSlots);
  Serial.print("Reset gaps: "); Serial.println(resetGaps);
  Serial.print("Issued: "); Serial.println(issuedCount);
  const ringpilot::Transport::Statistics& tx = transport.stats();
  Serial.print("TX accepted/retry/fail/expired/overflow: ");
  Serial.print(tx.accepted); Serial.print(" / "); Serial.print(tx.retries); Serial.print(" / ");
  Serial.print(tx.failures); Serial.print(" / "); Serial.print(tx.expired); Serial.print(" / "); Serial.println(tx.overflow);
  Serial.print("TX discarded link/subscription/pause, in-flight boundary: ");
  Serial.print(tx.linkDiscard); Serial.print(" / "); Serial.print(tx.subscriptionDiscard); Serial.print(" / ");
  Serial.print(tx.pausedDiscard); Serial.print(" / "); Serial.println(tx.inFlightBoundary);
  Serial.print("Dropped samples (ring overflow): "); Serial.println(droppedSamples);
  Serial.print("Connected/data subscribed: "); Serial.print(connected()); Serial.print(" / "); Serial.println(dataSubscribed());
  if (connected()) {
    Serial.print("Interval (x1.25 ms): "); Serial.println(Bluefruit.Connection(connHandle)->getConnectionInterval());
  }
}

static void resetLatency() {
  transport.resetStatistics();
  decisionCount = 0;
  sampleOnlyMaxUs = 0;
  filledSlots = 0;
  resetGaps = 0;
  issuedCount = 0;
  repeatedReads = 0;
  totalReads = 0;
  maxReadGapUs = 0;
  maxReadUs = 0;
  queueDropped = 0;
  lateReads = 0;
  earlyReads = 0;
}

// 읽기 태스크에서 부른다. loop가 무엇을 하든 끼어들어 10 ms마다 읽는다.
static void takeSample(uint32_t slot) {
  const uint32_t t0 = DWT->CYCCNT;
  int16_t v[6];
  // 단위 환산 없이 센서 원시값을 보낸다. 반올림 손실이 없고 크기(샘플당 12바이트)는 같다.
  v[0] = imu.readRawAccelX();
  v[1] = imu.readRawAccelY();
  v[2] = imu.readRawAccelZ();
  v[3] = imu.readRawGyroX();
  v[4] = imu.readRawGyroY();
  v[5] = imu.readRawGyroZ();
  const uint32_t t1 = DWT->CYCCNT;

  const uint32_t readUs = (t1 - t0) / kCyclesPerUs;
  if (readUs > maxReadUs) maxReadUs = readUs;
  if (haveRead) {
    const uint32_t gap = (t1 - lastReadCycles) / kCyclesPerUs;
    if (gap > maxReadGapUs) maxReadGapUs = gap;
    if (gap > 12000) lateReads++;
    if (gap < 8000) earlyReads++;
    if (memcmp(lastRaw, v, sizeof(lastRaw)) == 0) repeatedReads++;
    totalReads++;
  }
  lastReadCycles = t1;
  memcpy(lastRaw, v, sizeof(lastRaw));
  haveRead = true;

  if (ringHead - ringTail >= kRingSize) {
    droppedSamples++;  // loop가 못 따라오면 새 샘플을 버린다
  } else {
    Sample& sample = ring[ringHead % kRingSize];
    sample.slot = slot;
    memcpy(sample.v, v, sizeof(v));
    ringHead = ringHead + 1;
  }

  if (gyroHead - gyroTail >= kGyroQueueSize) {
    queueDropped++;
  } else {
    GyroItem& item = gyroQueue[gyroHead % kGyroQueueSize];
    item.slot = slot;
    item.readCycles = t1;
    for (int a = 0; a < 3; a++) item.gyro[a] = v[a + 3] * kGyroDpsPerLsb;
    gyroHead = gyroHead + 1;
  }
}

static void samplerTask(void* arg) {
  (void) arg;
  const TickType_t base = xTaskGetTickCount();
  uint32_t slot = 0;
  for (;;) {
    // 틱은 1024 Hz라 슬롯 시각을 올림해서 기다린다(간격 약 9.8~10.7 ms, 평균 10 ms)
    const TickType_t target = base + static_cast<TickType_t>(((static_cast<uint64_t>(slot) + 1) * configTICK_RATE_HZ + kSampleRateHz - 1) / kSampleRateHz);
    const int32_t wait = static_cast<int32_t>(target - xTaskGetTickCount());
    if (wait > 0) vTaskDelay(wait);
    slot = static_cast<uint32_t>(static_cast<uint64_t>(xTaskGetTickCount() - base) * kSampleRateHz / configTICK_RATE_HZ);
    xSemaphoreTake(imuMutex, portMAX_DELAY);
    if (state == STATE_STREAMING) takeSample(slot);
    xSemaphoreGive(imuMutex);
  }
}

// loop에서 판정 대기열을 비운다. 판정 입력은 끊기지 않은 100 Hz여야 하므로 빈 슬롯은 직전 값으로 채운다.
static void drainGesture() {
  if (gestureRestart) {
    gestureRestart = false;
    gr_reset();
    haveConsumed = false;
  }
  while (gyroTail != gyroHead) {
    const GyroItem item = gyroQueue[gyroTail % kGyroQueueSize];
    gyroTail = gyroTail + 1;
    if (haveConsumed && item.slot > lastConsumedSlot + 1) {
      const uint32_t missed = item.slot - lastConsumedSlot - 1;
      if (missed > kMaxFilledSlots) {
        gr_reset();
        resetGaps++;
      } else {
        for (uint32_t i = 1; i <= missed; i++) pushGesture(lastGyro, lastConsumedSlot + i, item.readCycles);
        filledSlots += missed;
      }
    }
    memcpy(lastGyro, item.gyro, sizeof(lastGyro));
    lastConsumedSlot = item.slot;
    haveConsumed = true;
    pushGesture(item.gyro, item.slot, item.readCycles);
  }
}

// 알림 1개를 보낼 수 있으면 보낸다. 한 패킷 안의 샘플은 슬롯이 연속이어야 한다.
static void pollSending() {
  uint32_t available = ringHead - ringTail;
  if (available == 0) return;

  uint16_t limit = samplesPerPacket();
  uint16_t run = 1;
  while (run < limit && run < available) {
    const Sample& prev = ring[(ringTail + run - 1) % kRingSize];
    const Sample& next = ring[(ringTail + run) % kRingSize];
    if (next.slot != prev.slot + 1) break;
    run++;
  }
  bool gapFollows = run < available;
  if (run < limit && !gapFollows) return;  // 더 모일 때까지 기다린다

  uint8_t packet[kHeaderBytes + kMaxSamplesPerPacket * kSampleBytes];
  uint32_t firstSlot = ring[ringTail % kRingSize].slot;
  memcpy(packet, &firstSlot, 4);
  packet[4] = static_cast<uint8_t>(run);
  for (uint16_t i = 0; i < run; i++) {
    memcpy(packet + kHeaderBytes + i * kSampleBytes, ring[(ringTail + i) % kRingSize].v, kSampleBytes);
  }

  if (sendImuPacket(packet, kHeaderBytes + run * kSampleBytes)) {
    ringTail += run;
    sentPackets++;
    if (awaitingFirstData) {
      awaitingFirstData = false;
      sendStatus(EVENT_FIRST_DATA);  // 트리거부터 첫 데이터 송신까지 걸린 시간을 기기 시계로 보고
    }
  }
}

static void enterPause() {
  transport.pause();
  xSemaphoreTake(imuMutex, portMAX_DELAY);
  state = STATE_PAUSED;
  imuPowerDown();
  ringTail = ringHead;
  gyroTail = gyroHead;
  haveRead = false;
  xSemaphoreGive(imuMutex);
  gestureRestart = true;
  requestConnParams(kPausedInterval, kPausedLatency, kPausedTimeout);
  sendStatus(EVENT_PAUSED);
}

static void resumeStreaming(uint32_t releaseMs) {
  xSemaphoreTake(imuMutex, portMAX_DELAY);
  imuStart();
  state = STATE_STREAMING;
  xSemaphoreGive(imuMutex);
  triggerMs = releaseMs;
  awaitingFirstData = true;
  requestConnParams(kStreamInterval, kStreamLatency, kStreamTimeout);
  sendStatus(EVENT_RESUMED);
}

static void printStatus() {
  Serial.println("RingPilot-IMU: ? 상태 | 센터 <0.5s 클릭(일시정지 중이면 재개), 0.5~2s 일시정지, 2s+ System OFF");
  Serial.print("State: "); Serial.println(state == STATE_PAUSED ? "PAUSED" : "STREAMING");
  Serial.print("Connected: "); Serial.println(connected());
  if (connected()) {
    BLEConnection* conn = Bluefruit.Connection(connHandle);
    Serial.print("MTU: "); Serial.println(conn->getMtu());
    Serial.print("Interval (x1.25 ms): "); Serial.println(conn->getConnectionInterval());
    Serial.print("Slave latency: "); Serial.println(conn->getSlaveLatency());
    Serial.print("Data subscribed: "); Serial.println(imuStream.notifyEnabled(connHandle));
  }
  Serial.print("Samples per packet: "); Serial.println(samplesPerPacket());
  Serial.print("Sent packets: "); Serial.println(sentPackets);
  Serial.print("Dropped samples (ring overflow): "); Serial.println(droppedSamples);
  Serial.print("Short clicks: "); Serial.println(clickCount);
}

static void waitForRelease() {
  // 깨우는 데 쓴 누름이나 꺼지는 순간의 누름이 남아 있으면 바로 다시 깨어나므로 놓을 때까지 기다린다.
  while (digitalRead(kCenterPin) == LOW) {
    delay(10);
  }
  delay(kDebounceMs);
}

static void powerOff() {
  xSemaphoreTake(imuMutex, portMAX_DELAY);  // 읽기 태스크를 멈춘다. System OFF라 돌려주지 않는다
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW);
    delay(120);
    digitalWrite(LED_RED, HIGH);
    delay(120);
  }
  ledsOff();
  // 끊은 뒤 손을 뗄 때까지 기다리는 동안 광고가 자동 재시작되면 휴대폰이 잠깐 다시 붙었다가
  // System OFF로 응답 없이 끊겨 재연결이 수 초 늦어진다(2026-10-19 측정에서 확인). 광고부터 멈춘다.
  Bluefruit.Advertising.restartOnDisconnect(false);
  Bluefruit.Advertising.stop();
  if (connected()) {
    Bluefruit.disconnect(connHandle);  // 휴대폰이 감시 시간 초과를 기다리지 않도록 먼저 끊는다
    delay(100);
  }
  digitalWrite(PIN_LSM6DS3TR_C_POWER, LOW);  // IMU 전원 차단. System OFF 중 실제 소모 전류는 미측정
  digitalWrite(VBAT_ENABLE, HIGH);  // 분압 회로 끄기(누설 방지). USB를 꽂으면 깨어나 부팅하면서 다시 LOW가 된다
  waitForRelease();
  systemOff(kCenterPin, 0);
}

// 누르는 동안: 0.5초가 지나면 파란 LED를 켜 "지금 떼면 일시정지"를 알리고, 2초가 되면 바로 System OFF.
// 뗄 때: 0.5초 미만이면 클릭, 0.5~2초면 일시정지. 판정을 뗄 때 하므로 2초 누름이 일시정지를 먼저 거치지 않는다.
static void pollCenterSwitch(uint32_t nowMs) {
  bool pressed = digitalRead(kCenterPin) == LOW;
  if (pressed) {
    if (pressStart == 0) pressStart = nowMs;
    uint32_t held = nowMs - pressStart;
    if (held >= kPowerOffHoldMs) {
      powerOff();
    } else if (held >= kPauseHoldMs && !pauseCueShown) {
      ledsOff();
      digitalWrite(LED_BLUE, LOW);
      pauseCueShown = true;
    }
    return;
  }

  if (pressStart == 0) return;
  uint32_t held = nowMs - pressStart;
  pressStart = 0;
  if (pauseCueShown) {
    ledsOff();
    pauseCueShown = false;
  }
  if (held < kDebounceMs) return;

  if (held < kPauseHoldMs) {
    if (state == STATE_PAUSED) resumeStreaming(nowMs);
    else clickCount++;
  } else if (state == STATE_STREAMING) {
    enterPause();
  }
}

// 연결 대기 중 파랑, 스트리밍 중 초록, 일시정지 중 청록(초록+파랑)이 2초마다 짧게 깜빡인다.
// delay()를 쓰면 그동안 샘플이 빠지므로 켜고 끄는 시점을 나눠 처리한다.
static void pollLed(uint32_t nowMs) {
  if (pressStart != 0) return;  // 누르는 동안에는 버튼 안내 LED가 우선
  if (gestureLedOn) {
    if (static_cast<int32_t>(nowMs - gestureLedUntil) < 0) return;
    ledsOff();
    gestureLedOn = false;
  }
  if (blinkLit && nowMs - lastBlink >= 30) {
    ledsOff();
    blinkLit = false;
  }
  if (nowMs - lastBlink < 2000) return;
  lastBlink = nowMs;
  if (state == STATE_PAUSED) {
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_BLUE, LOW);
  } else {
    digitalWrite(dataSubscribed() ? LED_GREEN : LED_BLUE, LOW);
  }
  blinkLit = true;
}

void setup() {
  Serial.begin(115200);  // 시리얼을 기다리지 않는다. USB 없이 배터리만으로도 시작해야 한다.
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  ledsOff();
  pinMode(kCenterPin, INPUT_PULLUP);
  pinMode(kChargeCurrentPin, INPUT);  // 기본값과 같은 상태를 명시. 실제 충전 전류는 미측정
  // USB를 꽂으면 System OFF에서 깨어나 충전 중에도 동작한다. Seeed 문서는 충전 중 P0.14를 HIGH로 두면
  // P0.31이 3.6V 한계에 닿을 수 있다고 경고하므로, 켜져 있는 동안은 LOW(분압 회로 켬)로 둔다.
  pinMode(VBAT_ENABLE, OUTPUT);
  digitalWrite(VBAT_ENABLE, LOW);
  waitForRelease();

  if (!imuStart()) {
    // IMU가 없으면 빨간 LED를 계속 깜빡인다. BLE는 시작하지 않는다.
    while (true) {
      digitalWrite(LED_RED, LOW);
      delay(150);
      digitalWrite(LED_RED, HIGH);
      delay(850);
    }
  }

  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);  // 큰 MTU와 긴 연결 이벤트 허용
  Bluefruit.begin(1, 0);
  Bluefruit.autoConnLed(false);  // 라이브러리 기본 파란 LED 깜빡임이 상태 LED와 겹치므로 끈다
  Bluefruit.setName("RingPilot-IMU");
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnInterval(6, 12);  // 7.5~15 ms
  Bluefruit.Periph.setConnectCallback(onConnect);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);

  imuService.begin();
  imuStream.setProperties(CHR_PROPS_NOTIFY);
  imuStream.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  imuStream.setMaxLen(kHeaderBytes + kMaxSamplesPerPacket * kSampleBytes);
  imuStream.begin();
  imuStatus.setProperties(CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  imuStatus.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  imuStatus.setFixedLen(10);
  imuStatus.setCccdWriteCallback(onStatusCccd);
  imuStatus.begin();
  gestureEvent.setProperties(CHR_PROPS_NOTIFY);
  gestureEvent.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  gestureEvent.setFixedLen(8);
  gestureEvent.setCccdWriteCallback(onGestureCccd);
  gestureEvent.begin();
  gr_reset();
  startCycleCounter();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(imuService);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);  // 처음 30초는 20 ms 간격으로 빠르게 광고
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);

  triggerMs = 0;  // 부팅 시점. 부트로더 시간은 포함되지 않는다
  awaitingFirstData = true;
  imuMutex = xSemaphoreCreateMutex();
  xTaskCreate(samplerTask, "imu", 512, nullptr, TASK_PRIO_HIGH, nullptr);
}

static uint32_t transportClock(void* context) {
  (void) context;
  return millis();
}

static void dispatchImu(void* context) {
  (void) context;
  if (dataSubscribed()) pollSending();
}

void loop() {
  applyLinkMailbox();
  uint32_t nowMs = millis();
  pollCenterSwitch(nowMs);
  pollLed(nowMs);

  while (Serial.available()) {
    const int command = Serial.read();
    if (command == '?') printStatus();
    else if (command == 'l') printLatency();
    else if (command == 'r') resetLatency();
  }

  if (state == STATE_STREAMING) {
    drainGesture();               // 추론은 구독과 상관없이 돈다
    applyLinkMailbox();
    transport.runCycle(transportClock, sendStatusPacket, sendGesturePacket, dispatchImu, nullptr);
    if (!dataSubscribed()) ringTail = ringHead; // 구독 전에 쌓인 과거 데이터는 보내지 않는다
    delay(1);                     // 할 일이 없을 때 CPU를 쉬게 한다. 읽기는 태스크가 하므로 밀리지 않는다
  } else {
    applyLinkMailbox();
    transport.sendStatus(sendStatusPacket, nullptr);
    ringTail = ringHead;          // 일시정지 중 쌓인 과거 데이터는 보내지 않는다
    delay(kIdleLoopDelayMs);      // 코어가 저전력 대기에 들어갈 수 있게 쉰다
  }
}
