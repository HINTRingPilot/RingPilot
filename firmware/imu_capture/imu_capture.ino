#include <LSM6DS3.h>
#include <Wire.h>

namespace {

constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kSampleRateHz = 100;
constexpr uint32_t kSampleIntervalUs = 1000000UL / kSampleRateHz;
constexpr float kGravityMs2 = 9.80665f;

// XIAO nRF52840 Sense onboard LSM6DS3TR-C address.
LSM6DS3 imu(I2C_MODE, 0x6A);
uint32_t nextSampleUs = 0;

void haltWithImuError() {
  // Do not print a numeric-looking line: Edge Impulse must not interpret an
  // error as sensor data.
  Serial.println("ERROR: IMU initialization failed");

#ifdef LED_RED
  pinMode(LED_RED, OUTPUT);
  while (true) {
    digitalWrite(LED_RED, LOW);
    delay(150);
    digitalWrite(LED_RED, HIGH);
    delay(850);
  }
#else
  while (true) {
    delay(1000);
  }
#endif
}

void printSample() {
  // Accelerometer values are converted from g to m/s^2. Gyroscope values are
  // emitted in deg/s. Keep this order synchronized with the Edge Impulse axis
  // names: accX,accY,accZ,gyrX,gyrY,gyrZ.
  Serial.print(imu.readFloatAccelX() * kGravityMs2, 5);
  Serial.print(',');
  Serial.print(imu.readFloatAccelY() * kGravityMs2, 5);
  Serial.print(',');
  Serial.print(imu.readFloatAccelZ() * kGravityMs2, 5);
  Serial.print(',');
  Serial.print(imu.readFloatGyroX(), 4);
  Serial.print(',');
  Serial.print(imu.readFloatGyroY(), 4);
  Serial.print(',');
  Serial.println(imu.readFloatGyroZ(), 4);
}

}  // namespace

void setup() {
  Serial.begin(kSerialBaud);

  // Give the USB serial port time to enumerate, but still allow standalone
  // startup instead of waiting forever for a host.
  const uint32_t serialWaitStartedMs = millis();
  while (!Serial && millis() - serialWaitStartedMs < 3000) {
    delay(10);
  }

  // The sensor's closest hardware output data rate is 104 Hz. Samples are
  // forwarded over USB at a stable 100 Hz for the Edge Impulse project.
  imu.settings.accelEnabled = 1;
  imu.settings.accelRange = 4;
  imu.settings.accelSampleRate = 104;
  imu.settings.accelBandWidth = 50;
  imu.settings.gyroEnabled = 1;
  imu.settings.gyroRange = 1000;
  imu.settings.gyroSampleRate = 104;
  imu.settings.gyroBandWidth = 50;

  if (imu.begin() != 0) {
    haltWithImuError();
  }

  nextSampleUs = micros();
}

void loop() {
  const uint32_t nowUs = micros();
  if (static_cast<int32_t>(nowUs - nextSampleUs) < 0) {
    return;
  }

  printSample();
  nextSampleUs += kSampleIntervalUs;

  // If serial output ever stalls, resume from the current time instead of
  // emitting a burst of stale back-to-back samples.
  if (static_cast<int32_t>(micros() - nextSampleUs) >
      static_cast<int32_t>(kSampleIntervalUs * 2)) {
    nextSampleUs = micros() + kSampleIntervalUs;
  }
}
