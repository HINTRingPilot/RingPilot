// 제스처 추론 펌웨어(firmware/imu_ble_stream 복사본 + 추론). 기존 IMU 스트림·상태 알림은 그대로라 지금 앱이 그대로 붙는다.
// 추가: 100 Hz 샘플마다 src/gesture_runtime(온라인 영점·입력 처리·TCN·발행 규칙)을 돌리고, 발행을 BLE 알림으로 보낸다.
// 발행 패킷: [순번 uint8][클래스 uint8(1=UP 2=DOWN 3=LEFT 4=RIGHT)][점수×1000 uint16 LE][슬롯 uint32 LE].
// 시리얼 명령: l = 지연 통계, r = 통계 초기화, ? = 상태. 측정 조건·기록은 docs/experiments/ble-v2/latency-01/README.md.
// 샘플링은 구독 여부와 상관없이 돌아 BLE 없이도 추론 시간을 잴 수 있다. 판정이 샘플 주기를 넘겨 건너뛴 슬롯은 직전 값으로 채우고 센다.
//
// IMU 6축을 BLE 알림으로 스트리밍하는 펌웨어. 100 Hz, ±4 g, ±2000 dps로 읽어
// (빠른 동작에서 ±1000 dps 포화를 피하려고 자이로 범위를 이전 USB 수집 펌웨어의 ±1000보다 넓혔다)
// 여러 샘플을 한 알림에 묶어 보낸다. USB 없이 배터리만으로 무선 수집을 시험하기 위한 것이다.
// 센터 스위치(D1): 짧게(1초 미만) = 클릭(일시정지 중이면 재개), 1~3초 = 일시정지(연결 유지), 3초 이상 = System OFF.
// System OFF에서는 센터를 누르면 재부팅한다. 일시정지는 BLE 연결을 유지한 채 IMU를 끄고 연결 간격을 늘린다.
// 데이터 패킷: [첫 샘플 슬롯 uint32 LE][샘플 수 uint8] + 샘플마다 accX,accY,accZ,gyrX,gyrY,gyrZ 센서 원시값 int16 LE.
// 원시값 환산(±4 g, ±2000 dps 설정): 가속도 1 LSB = 0.122 mg, 자이로 1 LSB = 0.070 dps (LSM6DS3 라이브러리 calcAccel/calcGyro와 동일).
// 범위를 바꾸면 android MainActivity의 환산 계수도 같이 바꿔야 한다.
// 상태 패킷: [상태 uint8][이벤트 uint8][부팅 후 ms uint32 LE][트리거 후 ms uint32 LE] (재개·재연결 지연 측정용).

#include <Adafruit_TinyUSB.h>  // 업로드 시 자동 리셋(1200bps)을 유지하려고 포함
#include <bluefruit.h>
#include <LSM6DS3.h>
#include <Wire.h>

#include "src/gesture_runtime.h"

static const uint32_t kSampleIntervalUs = 10000;  // 100 Hz
static const uint8_t kCenterPin = 1;               // D1, 사용자 확인
static const uint32_t kDebounceMs = 30;            // 이보다 짧은 누름은 접점 튐으로 무시
static const uint32_t kPauseHoldMs = 1000;         // 이 시간 미만은 클릭, 이상은 일시정지
static const uint32_t kPowerOffHoldMs = 3000;      // 누르고 있는 동안 이 시간에 도달하면 System OFF
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
static uint32_t ringHead = 0;  // 다음에 쓸 위치(누적 개수)
static uint32_t ringTail = 0;  // 다음에 보낼 위치(누적 개수)
static uint32_t droppedSamples = 0;
static uint32_t sentPackets = 0;
static uint32_t lastSlot = 0;
static bool haveSample = false;
static uint64_t elapsedUs = 0;
static uint32_t lastMicros = 0;
static uint16_t connHandle = BLE_CONN_HANDLE_INVALID;

static DeviceState state = STATE_STREAMING;
static uint32_t triggerMs = 0;            // 부팅(0) 또는 재개 클릭을 뗀 시각
static bool awaitingFirstData = true;     // 트리거 이후 첫 데이터 패킷을 아직 못 보냈는지
static uint32_t clickCount = 0;           // 짧은 클릭 수. 마우스 클릭 연결 전까지는 세기만 한다

static float lastGyro[3] = {0.0f, 0.0f, 0.0f};
static uint32_t decisionUs[kLatencyHistory];
static uint32_t decisionCount = 0;
static uint32_t sampleOnlyMaxUs = 0;
static uint32_t filledSlots = 0;
static uint32_t resetGaps = 0;
static uint32_t issuedCount = 0;
static uint8_t gestureSeq = 0;

static uint32_t pressStart = 0;
static bool pauseCueShown = false;
static uint32_t lastBlink = 0;
static bool blinkLit = false;

static void ledsOff() {
  digitalWrite(LED_RED, HIGH);  // 이 보드의 LED는 LOW에서 켜짐
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(LED_BLUE, HIGH);
}

static bool connected() {
  return connHandle != BLE_CONN_HANDLE_INVALID;
}

static bool dataSubscribed() {
  return connected() && imuStream.notifyEnabled(connHandle);
}

// 상태 알림은 데이터 알림 직후라 송신 버퍼가 차서 실패할 수 있다. 실패하면 대기열에 두고 loop에서 순서대로 다시 보낸다.
// 재개 직후 "재개"와 "첫 데이터"가 연달아 생기므로 하나만 보관하면 앞의 알림을 덮어쓴다.
static const uint8_t kStatusQueueSize = 4;
static uint8_t statusQueue[kStatusQueueSize][10];
static uint8_t statusQueueHead = 0;  // 다음에 보낼 위치
static uint8_t statusQueueCount = 0;

static void flushStatus() {
  if (statusQueueCount == 0) return;
  if (!connected() || !imuStatus.notifyEnabled(connHandle)) {
    statusQueueCount = 0;  // 구독자가 없으면 버린다. 마지막 값은 read로도 읽을 수 있다
    return;
  }
  while (statusQueueCount > 0) {
    if (!imuStatus.notify(connHandle, statusQueue[statusQueueHead], 10)) return;  // 다음 loop에서 재시도
    statusQueueHead = (statusQueueHead + 1) % kStatusQueueSize;
    statusQueueCount--;
  }
}

static void sendStatus(StatusEvent event) {
  uint32_t now = millis();
  uint32_t sinceTrigger = now - triggerMs;
  uint8_t packet[10];
  packet[0] = state;
  packet[1] = event;
  memcpy(packet + 2, &now, 4);
  memcpy(packet + 6, &sinceTrigger, 4);
  imuStatus.write(packet, sizeof(packet));

  if (statusQueueCount == kStatusQueueSize) {  // 가득 차면 가장 오래된 알림을 버린다
    statusQueueHead = (statusQueueHead + 1) % kStatusQueueSize;
    statusQueueCount--;
  }
  memcpy(statusQueue[(statusQueueHead + statusQueueCount) % kStatusQueueSize], packet, sizeof(packet));
  statusQueueCount++;
  flushStatus();
}

static void requestConnParams(uint16_t interval, uint16_t latency, uint16_t timeout) {
  if (!connected()) return;
  Bluefruit.Connection(connHandle)->requestConnectionParameter(interval, latency, timeout);
}

static void onConnect(uint16_t handle) {
  connHandle = handle;
  BLEConnection* conn = Bluefruit.Connection(handle);
  conn->requestPHY();
  conn->requestDataLengthUpdate();
  conn->requestMtuExchange(247);
}

static void onDisconnect(uint16_t handle, uint8_t reason) {
  (void) handle;
  (void) reason;
  connHandle = BLE_CONN_HANDLE_INVALID;
}

static void onStatusCccd(uint16_t handle, BLECharacteristic* chr, uint16_t value) {
  (void) handle;
  (void) chr;
  if (value & BLE_GATT_HVX_NOTIFICATION) sendStatus(EVENT_SUBSCRIBED);
}

static uint16_t samplesPerPacket() {
  if (!connected()) return 1;
  uint16_t payload = Bluefruit.Connection(connHandle)->getMtu() - 3;
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

static void updateClock() {
  uint32_t now = micros();
  elapsedUs += static_cast<uint32_t>(now - lastMicros);  // micros() 순환(약 71분)에 대비해 누적
  lastMicros = now;
}

static void sendGesture(const GrDecision& d, uint32_t slot) {
  issuedCount++;
  if (!connected() || !gestureEvent.notifyEnabled(connHandle)) return;
  uint8_t packet[8];
  const uint16_t score = static_cast<uint16_t>(d.scores[d.issued] * 1000.0f);
  packet[0] = gestureSeq++;
  packet[1] = static_cast<uint8_t>(d.issued);
  memcpy(packet + 2, &score, 2);
  memcpy(packet + 4, &slot, 4);
  gestureEvent.notify(connHandle, packet, sizeof(packet));
}

static void pushGesture(const float gyro[3], uint32_t slot) {
  GrDecision decision;
  const uint32_t t0 = micros();
  const int decided = gr_push(gyro, &decision);
  const uint32_t us = micros() - t0;
  if (!decided) {
    if (us > sampleOnlyMaxUs) sampleOnlyMaxUs = us;
    return;
  }
  decisionUs[decisionCount % kLatencyHistory] = us;
  decisionCount++;
  if (decision.issued >= 0) sendGesture(decision, slot);
}

static void printLatency() {
  static uint32_t sorted[kLatencyHistory];
  const uint32_t n = decisionCount < kLatencyHistory ? decisionCount : kLatencyHistory;
  Serial.print("Decisions: "); Serial.println(decisionCount);
  if (n > 0) {
    memcpy(sorted, decisionUs, n * sizeof(uint32_t));
    for (uint32_t i = 1; i < n; i++) {
      const uint32_t v = sorted[i];
      uint32_t j = i;
      while (j > 0 && sorted[j - 1] > v) {
        sorted[j] = sorted[j - 1];
        j--;
      }
      sorted[j] = v;
    }
    Serial.print("Decision us median/p95/max: ");
    Serial.print(sorted[n / 2]); Serial.print(" / ");
    Serial.print(sorted[n * 95 / 100]); Serial.print(" / ");
    Serial.println(sorted[n - 1]);
  }
  Serial.print("Sample-only max us: "); Serial.println(sampleOnlyMaxUs);
  Serial.print("Filled slots: "); Serial.println(filledSlots);
  Serial.print("Reset gaps: "); Serial.println(resetGaps);
  Serial.print("Issued: "); Serial.println(issuedCount);
  Serial.print("Dropped samples (ring overflow): "); Serial.println(droppedSamples);
  Serial.print("Connected/data subscribed: "); Serial.print(connected()); Serial.print(" / "); Serial.println(dataSubscribed());
  if (connected()) {
    Serial.print("Interval (x1.25 ms): "); Serial.println(Bluefruit.Connection(connHandle)->getConnectionInterval());
  }
}

static void resetLatency() {
  decisionCount = 0;
  sampleOnlyMaxUs = 0;
  filledSlots = 0;
  resetGaps = 0;
  issuedCount = 0;
}

static void takeSample(uint32_t slot) {
  if (ringHead - ringTail >= kRingSize) {
    ringTail++;  // 가장 오래된 샘플을 버린다
    droppedSamples++;
  }
  Sample& s = ring[ringHead % kRingSize];
  s.slot = slot;
  // 단위 환산 없이 센서 원시값을 보낸다. 반올림 손실이 없고 크기(샘플당 12바이트)는 같다.
  s.v[0] = imu.readRawAccelX();
  s.v[1] = imu.readRawAccelY();
  s.v[2] = imu.readRawAccelZ();
  s.v[3] = imu.readRawGyroX();
  s.v[4] = imu.readRawGyroY();
  s.v[5] = imu.readRawGyroZ();
  ringHead++;

  const float gyro[3] = {s.v[3] * kGyroDpsPerLsb, s.v[4] * kGyroDpsPerLsb, s.v[5] * kGyroDpsPerLsb};
  if (haveSample && slot > lastSlot + 1) {
    const uint32_t missed = slot - lastSlot - 1;
    if (missed > kMaxFilledSlots) {
      gr_reset();
      resetGaps++;
    } else {
      for (uint32_t i = 1; i <= missed; i++) pushGesture(lastGyro, lastSlot + i);  // 모델은 끊기지 않은 100 Hz 입력을 가정한다
      filledSlots += missed;
    }
  }
  memcpy(lastGyro, gyro, sizeof(gyro));
  pushGesture(gyro, slot);
}

static void pollSampling() {
  uint32_t slot = static_cast<uint32_t>(elapsedUs / kSampleIntervalUs);
  if (haveSample && slot == lastSlot) return;
  // 늦어서 건너뛴 슬롯은 스트림에서는 채우지 않는다(수신 쪽에서 슬롯 번호 간격으로 확인). 판정 입력만 takeSample에서 채운다.
  takeSample(slot);
  lastSlot = slot;
  haveSample = true;
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

  if (imuStream.notify(connHandle, packet, kHeaderBytes + run * kSampleBytes)) {
    ringTail += run;
    sentPackets++;
    if (awaitingFirstData) {
      awaitingFirstData = false;
      sendStatus(EVENT_FIRST_DATA);  // 트리거부터 첫 데이터 송신까지 걸린 시간을 기기 시계로 보고
    }
  }
}

static void enterPause() {
  state = STATE_PAUSED;
  imuPowerDown();
  ringTail = ringHead;
  haveSample = false;
  gr_reset();
  requestConnParams(kPausedInterval, kPausedLatency, kPausedTimeout);
  sendStatus(EVENT_PAUSED);
}

static void resumeStreaming(uint32_t releaseMs) {
  state = STATE_STREAMING;
  triggerMs = releaseMs;
  awaitingFirstData = true;
  imuStart();
  requestConnParams(kStreamInterval, kStreamLatency, kStreamTimeout);
  sendStatus(EVENT_RESUMED);
}

static void printStatus() {
  Serial.println("RingPilot-IMU: ? 상태 | 센터 <1s 클릭(일시정지 중이면 재개), 1~3s 일시정지, 3s+ System OFF");
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

// 누르는 동안: 1초가 지나면 파란 LED를 켜 "지금 떼면 일시정지"를 알리고, 3초가 되면 바로 System OFF.
// 뗄 때: 1초 미만이면 클릭, 1~3초면 일시정지. 판정을 뗄 때 하므로 3초 누름이 일시정지를 먼저 거치지 않는다.
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
  gestureEvent.begin();
  gr_reset();

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
  lastMicros = micros();
}

void loop() {
  uint32_t nowMs = millis();
  updateClock();
  flushStatus();
  pollCenterSwitch(nowMs);
  pollLed(nowMs);

  while (Serial.available()) {
    const int command = Serial.read();
    if (command == '?') printStatus();
    else if (command == 'l') printLatency();
    else if (command == 'r') resetLatency();
  }

  if (state == STATE_STREAMING) {
    pollSampling();               // 추론은 구독과 상관없이 돈다
    if (dataSubscribed()) pollSending();
    else ringTail = ringHead;     // 구독 전에 쌓인 과거 데이터는 보내지 않는다
  } else {
    ringTail = ringHead;          // 일시정지 중 쌓인 과거 데이터는 보내지 않는다
    haveSample = false;
    delay(kIdleLoopDelayMs);      // 코어가 저전력 대기에 들어갈 수 있게 쉰다
  }
}
