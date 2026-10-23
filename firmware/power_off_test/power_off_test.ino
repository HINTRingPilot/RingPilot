// 센터 스위치(D1)로 전원 끄기/켜기 테스트.
// - 켜져 있는 동안 파란 LED가 2초에 한 번 짧게 깜빡인다.
// - 센터를 kHoldMs 이상 누르고 있으면 빨간 LED가 3번 깜빡인 뒤 System OFF(최저 전력)로 들어간다.
// - System OFF에서 센터(D1)를 누르면 깨어나며, 깨어날 때는 처음부터 다시 부팅한다.
// 주의: System OFF에서는 BLE 연결과 RAM 상태가 모두 사라진다. 실제 소모 전류는 측정하지 않았다.

#include <Adafruit_TinyUSB.h>  // 업로드 시 자동 리셋(1200bps)을 유지하려고 포함

static const uint8_t kCenterPin = 1;  // D1
static const uint32_t kHoldMs = 1000;
static const uint32_t kDebounceMs = 30;

static uint32_t pressStart = 0;
static uint32_t lastBlink = 0;

static void ledsOff() {
  digitalWrite(LED_RED, HIGH);  // 이 보드의 LED는 LOW에서 켜짐
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

static void powerOff() {
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_RED, LOW);
    delay(120);
    digitalWrite(LED_RED, HIGH);
    delay(120);
  }
  ledsOff();
  digitalWrite(VBAT_ENABLE, HIGH);  // 배터리 분압 회로 끄기

  waitForRelease();

  // D1이 GND에 닿으면(눌리면) 깨어난다. 내부 풀업 사용.
  systemOff(kCenterPin, 0);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  ledsOff();
  pinMode(kCenterPin, INPUT_PULLUP);
  pinMode(VBAT_ENABLE, OUTPUT);
  digitalWrite(VBAT_ENABLE, LOW);  // 충전 중 HIGH 금지(Seeed 문서). 꺼질 때만 HIGH

  // 깨우는 누름이 아직 눌려 있으면 놓을 때까지 대기(바로 다시 꺼지는 것 방지).
  waitForRelease();
}

void loop() {
  uint32_t now = millis();

  if (now - lastBlink >= 2000) {
    lastBlink = now;
    digitalWrite(LED_BLUE, LOW);
    delay(40);
    digitalWrite(LED_BLUE, HIGH);
  }

  if (digitalRead(kCenterPin) == LOW) {
    if (pressStart == 0) {
      pressStart = now;
    } else if (now - pressStart >= kHoldMs) {
      powerOff();
    }
  } else {
    pressStart = 0;
  }

  delay(10);
}
