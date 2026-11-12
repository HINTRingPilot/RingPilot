#include "ble_link.h"

#include <Arduino.h>
#include <bluefruit.h>
#include <RingPilotBleMailbox.h>
#include <RingPilotTransport.h>

#include "imu_sampler.h"
#include "pointer.h"
#include "dev/imu_stream.h"

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
static ringpilot::Transport transport;
static ringpilot::BleMailbox linkMailbox;
static ringpilot::BleMailbox::Snapshot loopLink = {BLE_CONN_HANDLE_INVALID, 0, 0, false, false, false};
static_assert(ringpilot::Transport::NotifyBudgetMs >= BLE_GENERIC_TIMEOUT + 20,
              "Gesture retry budget must include the core notify timeout");

bool ble_connected() {
  return connHandle != BLE_CONN_HANDLE_INVALID && linkMailbox.current(loopLink);
}

uint16_t ble_conn_handle() {
  return connHandle;
}

bool ble_ready() {
  return linkMailbox.current(loopLink, true);
}

// Called only by loop-owned entry points; callbacks publish facts, never queue operations.
void ble_apply_link() {
  loopLink = linkMailbox.snapshot(true);
  connHandle = loopLink.handle;
  transport.synchronize(loopLink.linkEpoch, loopLink.gestureEpoch, ble_connected(),
                        loopLink.statusEnabled, loopLink.gestureEnabled);
  if (loopLink.statusSubscribed) ble_send_status(EVENT_SUBSCRIBED);
}

static bool sendStatusPacket(void*, const uint8_t* packet, uint8_t length) {
  bool boundary;
  const bool accepted = linkMailbox.notifyCurrent(loopLink, ringpilot::BleMailbox::Status,
                                                  imuStatus, packet, length, boundary);
  if (boundary) transport.noteInFlightBoundary();
  return accepted;
}

static bool sendGesturePacket(void*, const uint8_t* packet, uint8_t length) {
  bool boundary;
  const bool accepted = linkMailbox.notifyCurrent(loopLink, ringpilot::BleMailbox::Gesture,
                                                  gestureEvent, packet, length, boundary);
  if (boundary) transport.noteInFlightBoundary();
  return accepted;
}

bool ble_notify_data(BLECharacteristic& characteristic, const uint8_t* packet, uint8_t length) {
  if (!transport.imuReady()) return false;
  bool boundary;
  const bool accepted = linkMailbox.notifyCurrent(loopLink, ringpilot::BleMailbox::Data,
                                                  characteristic, packet, length, boundary);
  if (boundary) transport.noteInFlightBoundary();
  return accepted;
}

void ble_send_status(StatusEvent event) {
  const uint32_t now = millis();
  const uint32_t sinceTrigger = now - triggerMs;
  uint8_t packet[kStatusBytes];
  packet[0] = device_paused() ? 1 : 0;
  packet[1] = event;
  memcpy(packet + 2, &now, 4);
  memcpy(packet + 6, &sinceTrigger, 4);
  imuStatus.write(packet, sizeof(packet));

  transport.enqueueStatus(packet, event == EVENT_RESUMED);
}

static void requestConnParams(uint16_t interval, uint16_t latency, uint16_t timeout) {
  if (!ble_connected()) return;
  BLEConnection* conn = Bluefruit.Connection(connHandle);
  if (conn) conn->requestConnectionParameter(interval, latency, timeout);
}

static void onConnect(uint16_t handle) {
  linkMailbox.onConnect(handle);
  BLEConnection* conn = Bluefruit.Connection(handle);
  if (!conn) return;
  conn->requestPHY();
  conn->requestDataLengthUpdate();
  conn->requestMtuExchange(247);
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
  gestureEvent.setCccdWriteCallback(onGestureCccd);
  gestureEvent.begin();
  pointer_begin();  // 포인터 특성(b27a2004)은 기존 특성 뒤에 두어 그 핸들을 유지한다

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

static uint32_t transportClock(void*) { return millis(); }

#if RINGPILOT_IMU_STREAM
static void dispatchImu(void*) { imu_stream_poll(); }
#endif

void ble_poll() {
  ble_apply_link();
#if RINGPILOT_IMU_STREAM
  if (device_paused()) imu_stream_discard();
  transport.runCycle(transportClock, sendStatusPacket, sendGesturePacket,
                     device_paused() ? nullptr : dispatchImu, nullptr);
#else
  transport.runCycle(transportClock, sendStatusPacket, sendGesturePacket, nullptr, nullptr);
#endif
}

void ble_send_gesture(int8_t cls, float score, uint32_t slot) {
  ble_apply_link();
  if (!transport.gestureReady()) return;
  uint8_t packet[kGestureBytes];
  const uint16_t milli = static_cast<uint16_t>(score * 1000.0f);
  packet[0] = gestureSeq++;
  packet[1] = static_cast<uint8_t>(cls);
  memcpy(packet + 2, &milli, 2);
  memcpy(packet + 4, &slot, 4);
  transport.enqueueGesture(packet, millis());
}

void ble_on_pause() {
  ble_apply_link();
  transport.pause();
#if RINGPILOT_IMU_STREAM
  imu_stream_discard();
#endif
  requestConnParams(kPausedInterval, kPausedLatency, kPausedTimeout);
  ble_send_status(EVENT_PAUSED);
}

void ble_on_resume(uint32_t releaseMs) {
  ble_apply_link();
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
    if (!conn) return;
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
  const ringpilot::Transport::Statistics& s = transport.stats();
  out.print("TX accepted/retry/failure/expired/overflow: ");
  out.print(s.accepted); out.print(" / "); out.print(s.retries); out.print(" / ");
  out.print(s.failures); out.print(" / "); out.print(s.expired); out.print(" / "); out.println(s.overflow);
  out.print("TX link/subscription/paused discard, in-flight boundary: ");
  out.print(s.linkDiscard); out.print(" / "); out.print(s.subscriptionDiscard); out.print(" / ");
  out.print(s.pausedDiscard); out.print(" / "); out.println(s.inFlightBoundary);
  out.print("Connected/gesture subscribed: "); out.print(ble_connected()); out.print(" / "); out.println(ble_ready());
  if (ble_connected()) {
    BLEConnection* conn = Bluefruit.Connection(connHandle);
    if (conn) { out.print("Interval (x1.25 ms): "); out.println(conn->getConnectionInterval()); }
  }
}

void ble_reset_stats() { transport.resetStatistics(); }
