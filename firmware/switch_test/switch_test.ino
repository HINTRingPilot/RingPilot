// 납땜 연결 확인용 스위치 테스트.
// D0~D10을 모두 INPUT_PULLUP으로 두고 상태 변화를 USB 시리얼(115200)로 출력한다.
// 스위치 공통선이 GND에 연결돼 있으면 눌렀을 때 해당 핀이 LOW가 된다.
// 명령: ? 현재 전체 핀 상태 출력

#include <Adafruit_TinyUSB.h>

static const uint8_t kPins[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
static const uint8_t kPinCount = sizeof(kPins) / sizeof(kPins[0]);
static const uint32_t kDebounceMs = 20;

static bool stableLow[sizeof(kPins)];
static bool lastRawLow[sizeof(kPins)];
static uint32_t changedAt[sizeof(kPins)];

static void printStates() {
  Serial.println("--- pin states (LOW = GND와 연결됨) ---");
  for (uint8_t i = 0; i < kPinCount; i++) {
    Serial.print("D");
    Serial.print(kPins[i]);
    Serial.println(stableLow[i] ? ": LOW" : ": HIGH");
  }
}

void setup() {
  Serial.begin(115200);
  uint32_t start = millis();
  while (!Serial && millis() - start < 3000) {
  }

  for (uint8_t i = 0; i < kPinCount; i++) {
    pinMode(kPins[i], INPUT_PULLUP);
  }
  delay(50);
  for (uint8_t i = 0; i < kPinCount; i++) {
    stableLow[i] = lastRawLow[i] = (digitalRead(kPins[i]) == LOW);
    changedAt[i] = millis();
  }

  Serial.println("Switch wiring test (D0-D10, INPUT_PULLUP)");
  Serial.println("아무것도 안 누른 상태에서 LOW인 핀은 GND 쇼트이거나 스위치가 눌린 채 고정된 것.");
  bool idleLow = false;
  for (uint8_t i = 0; i < kPinCount; i++) {
    if (stableLow[i]) {
      Serial.print("WARN idle LOW: D");
      Serial.println(kPins[i]);
      idleLow = true;
    }
  }
  if (!idleLow) {
    Serial.println("OK: 대기 상태에서 모든 핀 HIGH");
  }
  Serial.println("이제 스위치를 하나씩 눌러 보세요. ?를 보내면 전체 상태 출력.");
}

void loop() {
  uint32_t now = millis();
  for (uint8_t i = 0; i < kPinCount; i++) {
    bool low = (digitalRead(kPins[i]) == LOW);
    if (low != lastRawLow[i]) {
      lastRawLow[i] = low;
      changedAt[i] = now;
    }
    if (low != stableLow[i] && now - changedAt[i] >= kDebounceMs) {
      stableLow[i] = low;
      Serial.print("D");
      Serial.print(kPins[i]);
      Serial.println(low ? " LOW  (눌림/GND 연결)" : " HIGH (해제)");
    }
  }

  while (Serial.available()) {
    if (Serial.read() == '?') {
      printStates();
    }
  }
}
