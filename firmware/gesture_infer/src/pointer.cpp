#include "pointer.h"

#include <Arduino.h>
#include <bluefruit.h>

#include "ble_link.h"

static const uint32_t kHeldResendMs = 200;  // 누르고 있는 동안 상태를 다시 보내는 간격
static const uint16_t kPacketBytes = 3;

struct Direction {
  uint8_t pin;
  uint8_t bit;
  const char* name;
};

// 스위치 단자와 XIAO 핀 배선은 docs/HardwareBuild.md 3절.
static const Direction kDirections[] = {
  {6, 1, "UP"},     // D6 = 단자 D
  {0, 2, "DOWN"},   // D0 = 단자 A
  {3, 4, "LEFT"},   // D3 = 단자 B
  {2, 8, "RIGHT"},  // D2 = 단자 C
};

static BLECharacteristic pointerEvent("b27a2004-8c5e-4b62-9a21-33dd714e9001");
static uint8_t state = 0;     // 지금 눌린 방향 비트
static uint8_t clicks = 0;
static uint8_t seq = 0;
static bool dirty = false;    // 보낼 것이 있다
static uint32_t lastSentMs = 0;

static void send(uint32_t nowMs) {
  if (!ble_connected() || !pointerEvent.notifyEnabled(ble_conn_handle())) {
    dirty = false;  // 받을 쪽이 없다. 연결되면 다음 변화부터 보낸다
    return;
  }
  const uint8_t packet[kPacketBytes] = {seq, state, clicks};
  if (pointerEvent.notify(ble_conn_handle(), packet, sizeof(packet))) {
    seq++;
    dirty = false;
    lastSentMs = nowMs;
  }
}

// 구독하면 지금 상태를 한 번 보낸다. 앱은 이 첫 패킷의 클릭 수를 기준으로 삼아, 예전 클릭을 탭으로 실행하지 않는다.
static void onCccd(uint16_t handle, BLECharacteristic* chr, uint16_t value) {
  (void) handle;
  (void) chr;
  if (value & BLE_GATT_HVX_NOTIFICATION) dirty = true;
}

void pointer_begin() {
  for (const Direction& d : kDirections) pinMode(d.pin, INPUT_PULLUP);  // 공통선이 GND라 누르면 LOW
  pointerEvent.setProperties(CHR_PROPS_NOTIFY);
  pointerEvent.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  pointerEvent.setFixedLen(kPacketBytes);
  pointerEvent.setCccdWriteCallback(onCccd);
  pointerEvent.begin();
}

void pointer_poll(uint32_t nowMs) {
  uint8_t now = 0;
  for (const Direction& d : kDirections) {
    if (digitalRead(d.pin) != LOW) continue;
    now |= d.bit;
    if (!(state & d.bit) && Serial) {
      Serial.print("pointer D"); Serial.print(d.pin); Serial.print(" -> "); Serial.println(d.name);
    }
  }
  if (now != state) {
    state = now;
    dirty = true;
  }
  if (state != 0 && nowMs - lastSentMs >= kHeldResendMs) dirty = true;
  if (dirty) send(nowMs);
}

void pointer_click() {
  clicks++;
  dirty = true;
}
