#include "imu_sampler.h"

#include <Arduino.h>
#include <LSM6DS3.h>
#include <Wire.h>

#include "cycle_timer.h"
#include "dev/imu_stream.h"

static const uint32_t kSampleRateHz = 100;
static const uint16_t kGyroQueueSize = 64;    // 판정 대기열, 약 0.64초 분량
static const float kGyroDpsPerLsb = 0.07f;    // ±2000 dps 설정의 환산값(학습 데이터와 같음)

static LSM6DS3 imu(I2C_MODE, 0x6A);
static SemaphoreHandle_t imuMutex = nullptr;
static volatile bool paused = false;

static GyroItem gyroQueue[kGyroQueueSize];
static volatile uint32_t gyroHead = 0;  // 태스크만 바꾼다
static volatile uint32_t gyroTail = 0;  // loop만 바꾼다

static ReadStats stats = {};
static bool haveRead = false;  // 직전 읽기가 있는지(일시정지하면 끊는다)
static uint32_t lastReadCycles = 0;
static int16_t lastRaw[6] = {0, 0, 0, 0, 0, 0};

static bool configureImu() {
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

static void powerDownImu() {
  imu.writeRegister(LSM6DS3_ACC_GYRO_CTRL1_XL, 0x00);  // 가속도 power-down
  imu.writeRegister(LSM6DS3_ACC_GYRO_CTRL2_G, 0x00);   // 자이로 power-down
}

static void recordReadTiming(const int16_t v[6], uint32_t t0, uint32_t t1) {
  const uint32_t readUs = cycles_to_us(t1 - t0);
  if (readUs > stats.maxReadUs) stats.maxReadUs = readUs;
  if (haveRead) {
    const uint32_t gap = cycles_to_us(t1 - lastReadCycles);
    if (gap > stats.maxGapUs) stats.maxGapUs = gap;
    if (gap > 12000) stats.late++;
    if (gap < 8000) stats.early++;
    if (memcmp(lastRaw, v, sizeof(lastRaw)) == 0) stats.repeated++;
    stats.total++;
  }
  lastReadCycles = t1;
  memcpy(lastRaw, v, sizeof(lastRaw));
  haveRead = true;
}

// 읽기 태스크에서 부른다. 스트림에는 단위 환산 없이 원시값을 보낸다(반올림 손실이 없고 크기는 같다).
static void takeSample(uint32_t slot) {
  const uint32_t t0 = cycle_now();
  int16_t v[6];
  v[0] = imu.readRawAccelX();
  v[1] = imu.readRawAccelY();
  v[2] = imu.readRawAccelZ();
  v[3] = imu.readRawGyroX();
  v[4] = imu.readRawGyroY();
  v[5] = imu.readRawGyroZ();
  const uint32_t t1 = cycle_now();
  recordReadTiming(v, t0, t1);

#if RINGPILOT_IMU_STREAM
  imu_stream_push(slot, v);
#endif

  if (gyroHead - gyroTail >= kGyroQueueSize) {
    stats.gyroDropped++;
  } else {
    GyroItem& item = gyroQueue[gyroHead % kGyroQueueSize];
    item.slot = slot;
    item.readCycles = t1;
    for (int a = 0; a < 3; a++) item.gyro[a] = v[a + 3] * kGyroDpsPerLsb;
    gyroHead = gyroHead + 1;
  }
}

static void samplerTask(void* arg) {
  (void) arg;
  const TickType_t base = xTaskGetTickCount();
  uint32_t slot = 0;
  for (;;) {
    // 틱은 1024 Hz라 슬롯 시각을 올림해서 기다린다(간격 약 9.8~10.7 ms, 평균 10 ms)
    const TickType_t target = base + static_cast<TickType_t>(
        ((static_cast<uint64_t>(slot) + 1) * configTICK_RATE_HZ + kSampleRateHz - 1) / kSampleRateHz);
    const int32_t wait = static_cast<int32_t>(target - xTaskGetTickCount());
    if (wait > 0) vTaskDelay(wait);
    slot = static_cast<uint32_t>(static_cast<uint64_t>(xTaskGetTickCount() - base) * kSampleRateHz / configTICK_RATE_HZ);
    xSemaphoreTake(imuMutex, portMAX_DELAY);
    if (!paused) takeSample(slot);
    xSemaphoreGive(imuMutex);
  }
}

bool imu_begin() {
  return configureImu();
}

void sampler_start() {
  imuMutex = xSemaphoreCreateMutex();
  xTaskCreate(samplerTask, "imu", 512, nullptr, TASK_PRIO_HIGH, nullptr);
}

void sampler_pause() {
  xSemaphoreTake(imuMutex, portMAX_DELAY);
  paused = true;
  powerDownImu();
#if RINGPILOT_IMU_STREAM
  imu_stream_discard();
#endif
  gyroTail = gyroHead;
  haveRead = false;
  xSemaphoreGive(imuMutex);
}

void sampler_resume() {
  xSemaphoreTake(imuMutex, portMAX_DELAY);
  configureImu();
  paused = false;
  xSemaphoreGive(imuMutex);
}

void sampler_halt() {
  xSemaphoreTake(imuMutex, portMAX_DELAY);  // System OFF로 가므로 돌려주지 않는다
}

bool device_paused() {
  return paused;
}

bool sampler_pop_gyro(GyroItem* out) {
  if (gyroTail == gyroHead) return false;
  *out = gyroQueue[gyroTail % kGyroQueueSize];
  gyroTail = gyroTail + 1;
  return true;
}

const ReadStats& sampler_stats() {
  return stats;
}

void sampler_reset_stats() {
  stats = {};
}
