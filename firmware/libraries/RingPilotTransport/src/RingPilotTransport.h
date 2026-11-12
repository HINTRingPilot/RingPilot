#ifndef RINGPILOT_TRANSPORT_H
#define RINGPILOT_TRANSPORT_H

#include <stdint.h>

namespace ringpilot {

// All mutations belong to loop(). BLE callbacks only publish adapter snapshots.
class Transport {
 public:
  static const uint8_t Capacity = 4;
  static const uint32_t GestureTtlMs = 250;
  static const uint32_t NotifyBudgetMs = 120; // core 1.1.13 wait 100ms + margin
  typedef bool (*Sender)(void*, const uint8_t*, uint8_t);
  typedef uint32_t (*Clock)(void*);
  typedef void (*ImuDispatch)(void*);
  enum Result { Idle, Sent, Blocked, Discarded };
  struct Statistics {
    uint32_t accepted, retries, failures, expired, overflow;
    uint32_t linkDiscard, subscriptionDiscard, pausedDiscard;
    uint32_t statusOverflow, inFlightBoundary;
  };

  Transport();
  void synchronize(uint32_t linkEpoch, uint32_t gestureEpoch, bool connected,
                   bool statusEnabled, bool gestureEnabled);
  void pause();
  bool enqueueStatus(const uint8_t packet[10], bool resumeBarrier = false);
  bool enqueueGesture(const uint8_t packet[8], uint32_t issuedMs);
  Result sendStatus(Sender send, void* context);
  Result sendGesture(uint32_t now, Sender send, void* context);
  void runCycle(Clock clock, Sender status, Sender gesture, ImuDispatch imu, void* context);
  bool imuReady() const { return connected_ && !paused_ && !resumePending_; }
  bool gestureReady() const { return connected_ && gestureEnabled_ && !paused_; }
  uint8_t statusCount() const { return statusCount_; }
  uint8_t gestureCount() const { return gestureCount_; }
  const Statistics& stats() const { return stats_; }
  void noteInFlightBoundary() { ++stats_.inFlightBoundary; }
  void resetStatistics();

 private:
  struct Status { uint8_t bytes[10]; bool barrier; };
  struct Gesture {
    uint8_t bytes[8];
    uint32_t issuedMs, linkEpoch, subscriptionEpoch;
    uint16_t attempts;
  };
  Status status_[Capacity];
  Gesture gestures_[Capacity];
  uint8_t statusCount_, gestureCount_;
  uint32_t linkEpoch_, gestureEpoch_;
  bool connected_, statusEnabled_, gestureEnabled_, paused_, resumePending_;
  Statistics stats_;
  void removeStatus(uint8_t index);
  void removeGesture();
};

} // namespace ringpilot
#endif
