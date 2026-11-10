#include "pointer.h"

#include <Arduino.h>
#include <bluefruit.h>

static const uint32_t kMoveIntervalMs = 20;  // 이동 보고 간격
static const int8_t kStepPx = 10;            // 한 번에 옮기는 거리(약 500 px/s). 폰의 포인터 속도 설정도 곱해진다
static const uint32_t kClickHoldMs = 40;     // 누름과 뗌을 별도 보고로 보내려고 둔 간격

struct Direction {
  uint8_t pin;
  int8_t dx;
  int8_t dy;
  const char* name;
};

// 스위치 단자 A·B·C·D와 XIAO 핀 배선은 docs/HardwareBuild.md 3절. 방향은 미확인 가정이다.
static const Direction kDirections[] = {
  {0, 0, -1, "UP"},     // D0 = 단자 A
  {3, 1, 0, "RIGHT"},   // D3 = 단자 B
  {2, 0, 1, "DOWN"},    // D2 = 단자 C
  {6, -1, 0, "LEFT"},   // D6 = 단자 D
};
static const int kDirectionCount = sizeof(kDirections) / sizeof(kDirections[0]);

static BLEHidAdafruit hid;
static uint32_t lastMoveMs = 0;
static bool wasPressed[kDirectionCount] = {};
static bool releasePending = false;
static uint32_t clickedAt = 0;

void pointer_begin() {
  for (int i = 0; i < kDirectionCount; i++) pinMode(kDirections[i].pin, INPUT_PULLUP);  // 공통선이 GND라 누르면 LOW
  hid.begin();
}

BLEService& pointer_service() {
  return hid;
}

void pointer_poll(uint32_t nowMs) {
  if (releasePending && nowMs - clickedAt >= kClickHoldMs) {
    // 연결 중이면 뗌이 실패해도 다시 보내 클릭이 눌린 채로 남지 않게 한다.
    if (!Bluefruit.connected() || hid.mouseButtonRelease()) releasePending = false;
  }

  int dx = 0;
  int dy = 0;
  for (int i = 0; i < kDirectionCount; i++) {
    const bool pressed = digitalRead(kDirections[i].pin) == LOW;
    if (pressed && !wasPressed[i] && Serial) {
      Serial.print("pointer D"); Serial.print(kDirections[i].pin); Serial.print(" -> "); Serial.println(kDirections[i].name);
    }
    wasPressed[i] = pressed;
    if (pressed) {
      dx += kDirections[i].dx;
      dy += kDirections[i].dy;
    }
  }
  if ((dx == 0 && dy == 0) || nowMs - lastMoveMs < kMoveIntervalMs) return;
  lastMoveMs = nowMs;
  if (Bluefruit.connected()) hid.mouseMove(dx * kStepPx, dy * kStepPx);  // 실패하면 다음 간격에 다시 옮긴다
}

void pointer_click() {
  if (!Bluefruit.connected()) return;
  hid.mouseButtonPress(MOUSE_BUTTON_LEFT);
  releasePending = true;
  clickedAt = millis();
}
