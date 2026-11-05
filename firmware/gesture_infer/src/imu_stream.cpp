#include "imu_stream.h"

#if RINGPILOT_IMU_STREAM

#include <Arduino.h>
#include <bluefruit.h>

#include "ble_link.h"

static const uint16_t kHeaderBytes = 5;
static const uint16_t kSampleBytes = 12;
static const uint16_t kMaxSamplesPerPacket = 10;  // 묶음 대기 지연을 최대 약 100 ms로 제한
static const uint16_t kRingSize = 256;            // 약 2.56초 분량

struct ImuSample {
  uint32_t slot;  // 부팅 후 10 ms 슬롯 번호
  int16_t v[6];
};

static BLECharacteristic imuStream("b27a2001-8c5e-4b62-9a21-33dd714e9001");

static ImuSample ring[kRingSize];
static volatile uint32_t ringHead = 0;  // 다음에 쓸 위치(누적 개수). 읽기 태스크만 바꾼다
static volatile uint32_t ringTail = 0;  // 다음에 보낼 위치(누적 개수). loop만 바꾼다
static uint32_t ringDropped = 0;
static uint32_t sentPackets = 0;
static bool awaitingFirstData = true;   // 트리거 이후 첫 데이터 패킷을 아직 못 보냈는지

static const ImuSample& peek(uint32_t i) {
  return ring[(ringTail + i) % kRingSize];
}

static uint16_t samplesPerPacket() {
  if (!ble_connected()) return 1;
  const uint16_t payload = Bluefruit.Connection(ble_conn_handle())->getMtu() - 3;
  uint16_t count = (payload - kHeaderBytes) / kSampleBytes;
  if (count < 1) count = 1;
  if (count > kMaxSamplesPerPacket) count = kMaxSamplesPerPacket;
  return count;
}

// 알림 1개를 보낼 수 있으면 보낸다. 한 패킷 안의 샘플은 슬롯이 연속이어야 한다.
static void sendPacket() {
  const uint32_t available = ringHead - ringTail;
  if (available == 0) return;

  const uint16_t limit = samplesPerPacket();
  uint16_t run = 1;
  while (run < limit && run < available) {
    if (peek(run).slot != peek(run - 1).slot + 1) break;
    run++;
  }
  const bool gapFollows = run < available;
  if (run < limit && !gapFollows) return;  // 더 모일 때까지 기다린다

  uint8_t packet[kHeaderBytes + kMaxSamplesPerPacket * kSampleBytes];
  const uint32_t firstSlot = peek(0).slot;
  memcpy(packet, &firstSlot, 4);
  packet[4] = static_cast<uint8_t>(run);
  for (uint16_t i = 0; i < run; i++) {
    memcpy(packet + kHeaderBytes + i * kSampleBytes, peek(i).v, kSampleBytes);
  }

  if (imuStream.notify(ble_conn_handle(), packet, kHeaderBytes + run * kSampleBytes)) {
    ringTail = ringTail + run;
    sentPackets++;
    if (awaitingFirstData) {
      awaitingFirstData = false;
      ble_send_status(EVENT_FIRST_DATA);  // 트리거부터 첫 데이터 송신까지 걸린 시간을 기기 시계로 보고
    }
  }
}

void imu_stream_begin() {
  imuStream.setProperties(CHR_PROPS_NOTIFY);
  imuStream.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  imuStream.setMaxLen(kHeaderBytes + kMaxSamplesPerPacket * kSampleBytes);
  imuStream.begin();
}

void imu_stream_push(uint32_t slot, const int16_t v[6]) {
  if (ringHead - ringTail >= kRingSize) {
    ringDropped++;  // loop가 못 따라오면 새 샘플을 버린다
    return;
  }
  ImuSample& sample = ring[ringHead % kRingSize];
  sample.slot = slot;
  memcpy(sample.v, v, sizeof(sample.v));
  ringHead = ringHead + 1;
}

void imu_stream_poll() {
  if (imu_stream_subscribed()) sendPacket();
  else imu_stream_discard();  // 구독 전에 쌓인 과거 데이터는 보내지 않는다
}

void imu_stream_discard() {
  ringTail = ringHead;
}

void imu_stream_mark_trigger() {
  awaitingFirstData = true;
}

bool imu_stream_subscribed() {
  return ble_connected() && imuStream.notifyEnabled(ble_conn_handle());
}

void imu_stream_print(Print& out) {
  out.print("Data subscribed: "); out.println(imu_stream_subscribed());
  out.print("Samples per packet: "); out.println(samplesPerPacket());
  out.print("Sent packets: "); out.println(sentPackets);
  out.print("Dropped samples (ring overflow): "); out.println(ringDropped);
}

#endif
