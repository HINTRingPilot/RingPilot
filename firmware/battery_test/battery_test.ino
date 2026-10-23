// 배터리 전원 확인용 테스트.
// USB 없이 배터리만 연결해도 파란 LED가 1초 주기로 깜빡이면 배터리 전원이 돌고 있는 것.
// USB가 연결돼 있으면 배터리 전압 추정값을 시리얼(115200)로 출력한다.
// 주의: 전압 환산 비율(분압 약 2.96배)은 가정값이라 오차가 있을 수 있다. 멀티미터가 아니다.

#include <Adafruit_TinyUSB.h>

static const float kDividerRatio = 1510.0f / 510.0f;  // 가정값
static const float kAdcRefVolt = 3.0f;                // AR_INTERNAL_3_0
static const uint32_t kBlinkMs = 500;
static const uint32_t kPrintMs = 1000;

static uint32_t lastBlink = 0;
static uint32_t lastPrint = 0;
static bool blueLit = false;

static float readBatteryVolt(int* rawOut) {
  digitalWrite(VBAT_ENABLE, LOW);  // 분압 회로 켜기
  delay(5);
  int raw = analogRead(PIN_VBAT);
  *rawOut = raw;  // 분압 회로는 LOW(켬)로 유지. 충전 중 HIGH 금지(Seeed 문서)
  return raw * (kAdcRefVolt / 4095.0f) * kDividerRatio;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BLUE, OUTPUT);
  digitalWrite(LED_BLUE, HIGH);  // 이 보드의 LED는 LOW에서 켜짐
  pinMode(VBAT_ENABLE, OUTPUT);
  digitalWrite(VBAT_ENABLE, LOW);
  analogReference(AR_INTERNAL_3_0);
  analogReadResolution(12);
}

void loop() {
  uint32_t now = millis();

  if (now - lastBlink >= kBlinkMs) {
    lastBlink = now;
    blueLit = !blueLit;
    digitalWrite(LED_BLUE, blueLit ? LOW : HIGH);
  }

  if (now - lastPrint >= kPrintMs) {
    lastPrint = now;
    if (Serial) {
      int raw = 0;
      float volt = readBatteryVolt(&raw);
      Serial.print("uptime_ms=");
      Serial.print(now);
      Serial.print(" vbat_raw=");
      Serial.print(raw);
      Serial.print(" vbat_est=");
      Serial.print(volt, 2);
      Serial.println("V (추정)");
    }
  }
}
