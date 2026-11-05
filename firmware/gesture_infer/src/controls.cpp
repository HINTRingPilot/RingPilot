#include "controls.h"

#include <Arduino.h>

#include "ble_link.h"
#include "gesture_loop.h"
#include "imu_sampler.h"

static const uint8_t kCenterPin = 1;            // D1, 사용자 확인
static const uint8_t kChargeCurrentPin = 22;    // P0.13(HICHG). 입력(open)이면 50mA로 알려짐
static const uint32_t kDebounceMs = 30;         // 이보다 짧은 누름은 접점 튐으로 무시
static const uint32_t kPauseHoldMs = 500;       // 이 시간 미만은 클릭, 이상은 일시정지
static const uint32_t kPowerOffHoldMs = 2000;   // 누르고 있는 동안 이 시간에 도달하면 System OFF
static const uint32_t kGestureLedMs = 700;
static const uint32_t kBlinkPeriodMs = 2000;
static const uint32_t kBlinkOnMs = 30;

static uint32_t pressStart = 0;   // 0이면 누르고 있지 않다
static bool pauseCueShown = false;
static uint32_t clickCount = 0;   // 짧은 클릭 수. 마우스 클릭 연결 전까지는 세기만 한다
static uint32_t gestureLedUntil = 0;
static bool gestureLedOn = false;
static uint32_t lastBlink = 0;
static bool blinkLit = false;

static void ledsOff() {
  digitalWrite(LED_RED, HIGH);
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(LED_BLUE, HIGH);
}

static void waitForRelease() {
  // 깨우는 데 쓴 누름이나 꺼지는 순간의 누름이 남아 있으면 바로 다시 깨어나므로 놓을 때까지 기다린다.
  while (digitalRead(kCenterPin) == LOW) {
    delay(10);
  }
  delay(kDebounceMs);
}

static void enterPause() {
  sampler_pause();
  gesture_request_reset();
  ble_on_pause();
}

static void resumeStreaming(uint32_t releaseMs) {
  sampler_resume();
  ble_on_resume(releaseMs);
}

static void powerOff() {
  sampler_halt();
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW);
    delay(120);
    digitalWrite(LED_RED, HIGH);
    delay(120);
  }
  ledsOff();
  ble_shutdown();
  digitalWrite(PIN_LSM6DS3TR_C_POWER, LOW);  // IMU 전원 차단. System OFF 중 실제 소모 전류는 미측정
  digitalWrite(VBAT_ENABLE, HIGH);  // 분압 회로 끄기(누설 방지). USB를 꽂으면 깨어나 부팅하면서 다시 LOW가 된다
  waitForRelease();
  systemOff(kCenterPin, 0);
}

// 판정을 뗄 때 하므로 2초 누름이 일시정지를 먼저 거치지 않는다.
static void pollCenterSwitch(uint32_t nowMs) {
  const bool pressed = digitalRead(kCenterPin) == LOW;
  if (pressed) {
    if (pressStart == 0) pressStart = nowMs;
    const uint32_t held = nowMs - pressStart;
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
  const uint32_t held = nowMs - pressStart;
  pressStart = 0;
  if (pauseCueShown) {
    ledsOff();
    pauseCueShown = false;
  }
  if (held < kDebounceMs) return;

  if (held < kPauseHoldMs) {
    if (!sampler_running()) resumeStreaming(nowMs);
    else clickCount++;
  } else if (sampler_running()) {
    enterPause();
  }
}

// delay()를 쓰면 loop가 멈추므로 켜고 끄는 시점을 나눠 처리한다.
static void pollLed(uint32_t nowMs) {
  if (pressStart != 0) return;  // 누르는 동안에는 버튼 안내 LED가 우선
  if (gestureLedOn) {
    if (static_cast<int32_t>(nowMs - gestureLedUntil) < 0) return;
    ledsOff();
    gestureLedOn = false;
  }
  if (blinkLit && nowMs - lastBlink >= kBlinkOnMs) {
    ledsOff();
    blinkLit = false;
  }
  if (nowMs - lastBlink < kBlinkPeriodMs) return;
  lastBlink = nowMs;
  if (!sampler_running()) {
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_BLUE, LOW);
  } else {
    digitalWrite(ble_data_subscribed() ? LED_GREEN : LED_BLUE, LOW);
  }
  blinkLit = true;
}

void controls_begin() {
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
}

void controls_poll(uint32_t nowMs) {
  pollCenterSwitch(nowMs);
  pollLed(nowMs);
}

void controls_fail_forever() {
  while (true) {
    digitalWrite(LED_RED, LOW);
    delay(150);
    digitalWrite(LED_RED, HIGH);
    delay(850);
  }
}

void led_show_gesture(int8_t cls) {
  ledsOff();
  if (cls == 1 || cls == 3 || cls == 4) digitalWrite(LED_RED, LOW);
  if (cls == 2 || cls == 3) digitalWrite(LED_BLUE, LOW);
  if (cls == 3 || cls == 4) digitalWrite(LED_GREEN, LOW);
  gestureLedUntil = millis() + kGestureLedMs;
  gestureLedOn = true;
  blinkLit = false;
}

void controls_print_status(Print& out) {
  out.print("State: "); out.println(sampler_running() ? "STREAMING" : "PAUSED");
  out.print("Short clicks: "); out.println(clickCount);
}
