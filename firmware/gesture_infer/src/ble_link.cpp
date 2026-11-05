#include "ble_link.h"

#include <Arduino.h>
#include <bluefruit.h>

#include "imu_sampler.h"
#include "imu_stream.h"

static const uint16_t kStatusBytes = 10;
static const uint16_t kGestureBytes = 8;

// 연결 파라미터 단위: 간격 1.25 ms, 감시 시간 10 ms. 요청일 뿐이고 최종 값은 휴대폰이 정한다.
static const uint16_t kActiveInterval = 9;   // 11.25 ms. 발행이 폰에 닿기까지 기다리는 시간을 줄인다
static const uint16_t kActiveLatency = 0;
static const uint16_t kActiveTimeout = 200;  // 2초
static const uint16_t kPausedInterval = 80;  // 100 ms
static const uint16_t kPausedLatency = 4;    // 최대 4번 연결 이벤트를 건너뛸 수 있음
static const uint16_t kPausedTimeout = 400;  // 4초. (1 + latency) * interval * 2보다 커야 한다

static BLEService imuService("b27a2000-8c5e-4b62-9a21-33dd714e9001");
static BLECharacteristic imuStatus("b27a2002-8c5e-4b62-9a21-33dd714e9001");
static BLECharacteristic gestureEvent("b27a2003-8c5e-4b62-9a21-33dd714e9001");

static uint16_t connHandle = BLE_CONN_HANDLE_INVALID;
static uint32_t triggerMs = 0;  // 부팅(0) 또는 재개 클릭을 뗀 시각
static uint8_t gestureSeq = 0;

// 상태 알림은 다른 알림 직후라 송신 버퍼가 차서 실패할 수 있다. 실패하면 대기열에 두고 loop에서 순서대로 다시 보낸다.
// 재개 직후 "재개"와 "첫 데이터"가 연달아 생기므로 하나만 보관하면 앞의 알림을 덮어쓴다.
static const uint8_t kStatusQueueSize = 4;
static uint8_t statusQueue[kStatusQueueSize][kStatusBytes];
static uint8_t statusQueueHead = 0;  // 다음에 보낼 위치
static uint8_t statusQueueCount = 0;

bool ble_connected() {
  return connHandle != BLE_CONN_HANDLE_INVALID;
}

uint16_t ble_conn_handle() {
  return connHandle;
}

bool ble_ready() {
  return ble_connected() && gestureEvent.notifyEnabled(connHandle);
}

// 제스처 알림도 송신 버퍼가 차면 실패할 수 있다. 발행은 다시 나오지 않으므로 잃지 않게 대기열에 두고 다음 loop에서 먼저 보낸다.
static const uint8_t kGestureQueueSize = 4;
static uint8_t gestureQueue[kGestureQueueSize][kGestureBytes];
static uint8_t gestureQueueHead = 0;
static uint8_t gestureQueueCount = 0;
static uint32_t gestureRetries = 0;  // 첫 시도에 못 보낸 횟수
static uint32_t gestureDropped = 0;  // 대기열이 가득 차 버린 횟수

static void flushGestures() {
  if (gestureQueueCount == 0) return;
  if (!ble_connected() || !gestureEvent.notifyEnabled(connHandle)) {
    gestureQueueCount = 0;  // 받을 쪽이 없으면 버린다
    return;
  }
  while (gestureQueueCount > 0) {
    if (!gestureEvent.notify(connHandle, gestureQueue[gestureQueueHead], kGestureBytes)) return;  // 다음 loop에서 재시도
    gestureQueueHead = (gestureQueueHead + 1) % kGestureQueueSize;
    gestureQueueCount--;
  }
}

static void flushStatus() {
  if (statusQueueCount == 0) return;
  if (!ble_connected() || !imuStatus.notifyEnabled(connHandle)) {
    statusQueueCount = 0;  // 구독자가 없으면 버린다. 마지막 값은 read로도 읽을 수 있다
    return;
  }
  while (statusQueueCount > 0) {
    if (!imuStatus.notify(connHandle, statusQueue[statusQueueHead], kStatusBytes)) return;  // 다음 loop에서 재시도
    statusQueueHead = (statusQueueHead + 1) % kStatusQueueSize;
    statusQueueCount--;
  }
}

void ble_send_status(StatusEvent event) {
  const uint32_t now = millis();
  const uint32_t sinceTrigger = now - triggerMs;
  uint8_t packet[kStatusBytes];
  packet[0] = sampler_running() ? 0 : 1;
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
  if (!ble_connected()) return;
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
  if (value & BLE_GATT_HVX_NOTIFICATION) ble_send_status(EVENT_SUBSCRIBED);
}

static void beginCharacteristic(BLECharacteristic& chr, uint8_t properties) {
  chr.setProperties(properties);
  chr.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
}

void ble_begin() {
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);  // 큰 MTU와 긴 연결 이벤트 허용
  Bluefruit.begin(1, 0);
  Bluefruit.autoConnLed(false);  // 라이브러리 기본 파란 LED 깜빡임이 상태 LED와 겹치므로 끈다
  Bluefruit.setName("RingPilot-IMU");
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnInterval(6, 12);  // 7.5~15 ms
  Bluefruit.Periph.setConnectCallback(onConnect);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);

  imuService.begin();
#if RINGPILOT_IMU_STREAM
  imu_stream_begin();  // 기존 특성 순서(스트림, 상태, 제스처)를 유지한다
#endif
  beginCharacteristic(imuStatus, CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  imuStatus.setFixedLen(kStatusBytes);
  imuStatus.setCccdWriteCallback(onStatusCccd);
  imuStatus.begin();
  beginCharacteristic(gestureEvent, CHR_PROPS_NOTIFY);
  gestureEvent.setFixedLen(kGestureBytes);
  gestureEvent.begin();

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(imuService);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);  // 처음 30초는 20 ms 간격으로 빠르게 광고
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);

  triggerMs = 0;  // 부팅 시점. 부트로더 시간은 포함되지 않는다
}

void ble_poll() {
  flushGestures();
  flushStatus();
#if RINGPILOT_IMU_STREAM
  if (sampler_running()) imu_stream_poll();
  else imu_stream_discard();  // 일시정지 중 쌓인 과거 데이터는 보내지 않는다
#endif
}

void ble_send_gesture(int8_t cls, float score, uint32_t slot) {
  if (!ble_connected() || !gestureEvent.notifyEnabled(connHandle)) return;
  if (gestureQueueCount == kGestureQueueSize) {  // 가득 차면 가장 오래된 발행을 버린다
    gestureQueueHead = (gestureQueueHead + 1) % kGestureQueueSize;
    gestureQueueCount--;
    gestureDropped++;
  }
  uint8_t* packet = gestureQueue[(gestureQueueHead + gestureQueueCount) % kGestureQueueSize];
  const uint16_t milli = static_cast<uint16_t>(score * 1000.0f);
  packet[0] = gestureSeq++;
  packet[1] = static_cast<uint8_t>(cls);
  memcpy(packet + 2, &milli, 2);
  memcpy(packet + 4, &slot, 4);
  gestureQueueCount++;
  const uint8_t before = gestureQueueCount;
  flushGestures();
  if (gestureQueueCount == before) gestureRetries++;
}

void ble_on_pause() {
  requestConnParams(kPausedInterval, kPausedLatency, kPausedTimeout);
  ble_send_status(EVENT_PAUSED);
}

void ble_on_resume(uint32_t releaseMs) {
  triggerMs = releaseMs;
#if RINGPILOT_IMU_STREAM
  imu_stream_mark_trigger();
#endif
  requestConnParams(kActiveInterval, kActiveLatency, kActiveTimeout);
  ble_send_status(EVENT_RESUMED);
}

void ble_shutdown() {
  // 끊은 뒤 손을 뗄 때까지 기다리는 동안 광고가 자동 재시작되면 휴대폰이 잠깐 다시 붙었다가
  // System OFF로 응답 없이 끊겨 재연결이 수 초 늦어진다(2026-10-19 측정에서 확인). 광고부터 멈춘다.
  Bluefruit.Advertising.restartOnDisconnect(false);
  Bluefruit.Advertising.stop();
  if (ble_connected()) {
    Bluefruit.disconnect(connHandle);  // 휴대폰이 감시 시간 초과를 기다리지 않도록 먼저 끊는다
    delay(100);
  }
}

void ble_print_status(Print& out) {
  out.print("Connected: "); out.println(ble_connected());
  if (ble_connected()) {
    BLEConnection* conn = Bluefruit.Connection(connHandle);
    out.print("MTU: "); out.println(conn->getMtu());
    out.print("Interval (x1.25 ms): "); out.println(conn->getConnectionInterval());
    out.print("Slave latency: "); out.println(conn->getSlaveLatency());
    out.print("Gesture subscribed: "); out.println(ble_ready());
  }
#if RINGPILOT_IMU_STREAM
  imu_stream_print(out);
#else
  out.println("IMU stream: off (build_config.h)");
#endif
}

void ble_print_link(Print& out) {
  out.print("Gesture notify retried/dropped: "); out.print(gestureRetries); out.print(" / "); out.println(gestureDropped);
  out.print("Connected/gesture subscribed: "); out.print(ble_connected()); out.print(" / "); out.println(ble_ready());
  if (ble_connected()) {
    out.print("Interval (x1.25 ms): "); out.println(Bluefruit.Connection(connHandle)->getConnectionInterval());
  }
}
