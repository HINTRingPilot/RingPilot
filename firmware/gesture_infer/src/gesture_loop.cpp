#include "gesture_loop.h"

#include <Arduino.h>

#include "ble_link.h"
#include "controls.h"
#include "cycle_timer.h"
#include "gesture_runtime.h"
#include "imu_sampler.h"

static const uint16_t kLatencyHistory = 1024;  // 판정 시간 기록 개수(약 51초)
static const uint32_t kMaxFilledSlots = 20;    // 이보다 긴 공백은 채우지 않고 판정 상태를 초기화한다

static volatile bool resetRequested = false;
static bool haveConsumed = false;  // 직전 판정 입력이 있는지
static uint32_t lastConsumedSlot = 0;
static float lastGyro[3] = {0.0f, 0.0f, 0.0f};

static uint32_t decisionUs[kLatencyHistory];
static uint32_t decisionLagUs[kLatencyHistory];  // 판정에 쓴 마지막 샘플을 읽은 순간부터 판정 완료까지
static uint32_t decisionCount = 0;
static uint32_t sampleOnlyMaxUs = 0;             // 판정하지 않은 샘플(넣기만 함)의 최대 시간
static uint32_t filledSlots = 0;
static uint32_t resetGaps = 0;
static uint32_t issuedCount = 0;

// 시리얼 확인용. 발행과, 발행되지 않은 방향 후보(점수 0.5 이상)를 슬롯 시각과 함께 찍는다. 판정 시간 측정에는 들어가지 않는다.
static void printDecision(const GrDecision& d, uint32_t slot) {
  static const char* const kNames[GT_CLASSES] = {"NONE", "UP", "DOWN", "LEFT", "RIGHT"};
  int top = 0;
  for (int n = 1; n < GT_CLASSES; n++) {
    if (d.scores[n] > d.scores[top]) top = n;
  }
  if (d.issued < 0 && (top == 0 || d.scores[top] < 0.5f)) return;
  const int shown = d.issued >= 0 ? d.issued : top;
  Serial.print(d.issued >= 0 ? "GESTURE " : "cand ");
  Serial.print(kNames[shown]);
  Serial.print(" ");
  Serial.print(d.scores[shown], 2);
  Serial.print(" t=");
  Serial.println(slot * 0.01f, 2);
}

static void pushSample(const float gyro[3], uint32_t slot, uint32_t readCycles) {
  GrDecision decision;
  const uint32_t t0 = cycle_now();
  const int decided = gr_push(gyro, &decision);
  const uint32_t t1 = cycle_now();
  const uint32_t us = cycles_to_us(t1 - t0);
  if (!decided) {
    if (us > sampleOnlyMaxUs) sampleOnlyMaxUs = us;
    return;
  }
  decisionUs[decisionCount % kLatencyHistory] = us;
  decisionLagUs[decisionCount % kLatencyHistory] = cycles_to_us(t1 - readCycles);
  decisionCount++;
  if (decision.issued >= 0) {
    issuedCount++;
    led_show_gesture(decision.issued);
    ble_send_gesture(decision.issued, decision.scores[decision.issued], slot);
  }
  if (Serial) printDecision(decision, slot);
}

void gesture_begin() {
  gr_reset();
}

void gesture_request_reset() {
  resetRequested = true;
}

void gesture_poll() {
  if (resetRequested) {
    resetRequested = false;
    gr_reset();
    haveConsumed = false;
  }
  GyroItem item;
  while (sampler_pop_gyro(&item)) {
    if (haveConsumed && item.slot > lastConsumedSlot + 1) {
      const uint32_t missed = item.slot - lastConsumedSlot - 1;
      if (missed > kMaxFilledSlots) {
        gr_reset();
        resetGaps++;
      } else {
        for (uint32_t i = 1; i <= missed; i++) pushSample(lastGyro, lastConsumedSlot + i, item.readCycles);
        filledSlots += missed;
      }
    }
    memcpy(lastGyro, item.gyro, sizeof(lastGyro));
    lastConsumedSlot = item.slot;
    haveConsumed = true;
    pushSample(item.gyro, item.slot, item.readCycles);
  }
}

static void printPercentiles(Print& out, const char* label, const uint32_t* values, uint32_t n) {
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
  out.print(label);
  out.print(" median/p95/max: ");
  out.print(sorted[n / 2]); out.print(" / ");
  out.print(sorted[n * 95 / 100]); out.print(" / ");
  out.println(sorted[n - 1]);
}

void gesture_print_stats(Print& out) {
  const uint32_t n = decisionCount < kLatencyHistory ? decisionCount : kLatencyHistory;
  out.print("Decisions: "); out.println(decisionCount);
  printPercentiles(out, "Decision us", decisionUs, n);
  printPercentiles(out, "Sample-to-decision us", decisionLagUs, n);
  out.print("Sample-only max us: "); out.println(sampleOnlyMaxUs);
  out.print("Filled slots: "); out.println(filledSlots);
  out.print("Reset gaps: "); out.println(resetGaps);
  out.print("Issued: "); out.println(issuedCount);
}

void gesture_reset_stats() {
  decisionCount = 0;
  sampleOnlyMaxUs = 0;
  filledSlots = 0;
  resetGaps = 0;
  issuedCount = 0;
}
