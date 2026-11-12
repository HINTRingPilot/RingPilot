#include "RingPilotTransport.h"
#include <string.h>

namespace ringpilot {

Transport::Transport()
    : statusCount_(0), gestureCount_(0), linkEpoch_(0), gestureEpoch_(0),
      connected_(false), statusEnabled_(false), gestureEnabled_(false),
      paused_(false), resumePending_(false), stats_() {}

void Transport::resetStatistics() { stats_ = Statistics(); }

void Transport::removeStatus(uint8_t index) {
  if (index >= statusCount_) return;
  for (uint8_t i = index + 1; i < statusCount_; ++i) status_[i - 1] = status_[i];
  --statusCount_;
}

void Transport::removeGesture() {
  if (gestureCount_ == 0) return;
  for (uint8_t i = 1; i < gestureCount_; ++i) gestures_[i - 1] = gestures_[i];
  --gestureCount_;
}

void Transport::synchronize(uint32_t linkEpoch, uint32_t gestureEpoch, bool connected,
                            bool statusEnabled, bool gestureEnabled) {
  if (linkEpoch != linkEpoch_ || connected != connected_) {
    stats_.linkDiscard += gestureCount_;
    gestureCount_ = 0;
    statusCount_ = 0;
    resumePending_ = false;
  } else if (gestureEpoch != gestureEpoch_ || !gestureEnabled) {
    stats_.subscriptionDiscard += gestureCount_;
    gestureCount_ = 0;
  }
  linkEpoch_ = linkEpoch;
  gestureEpoch_ = gestureEpoch;
  connected_ = connected;
  statusEnabled_ = statusEnabled;
  gestureEnabled_ = gestureEnabled;
  if (!statusEnabled_) {
    // A current RESUMED must survive a temporary status subscription loss.
    for (uint8_t i = 0; i < statusCount_;) {
      if (!status_[i].barrier) removeStatus(i);
      else ++i;
    }
  }
}

void Transport::pause() {
  stats_.pausedDiscard += gestureCount_;
  gestureCount_ = 0;
  paused_ = true;
  resumePending_ = false;
  for (uint8_t i = 0; i < statusCount_;) {
    // RESUMED/FIRST_DATA from a canceled streaming phase are no longer useful.
    if (status_[i].barrier || status_[i].bytes[1] == 3) removeStatus(i);
    else ++i;
  }
}

bool Transport::enqueueStatus(const uint8_t packet[10], bool resumeBarrier) {
  if (resumeBarrier) {
    for (uint8_t i = 0; i < statusCount_;) {
      if (status_[i].barrier) removeStatus(i);
      else ++i;
    }
    paused_ = false;
    resumePending_ = connected_;
  }
  if (!connected_) return false;
  if (statusCount_ == Capacity) {
    uint8_t victim = 0;
    while (victim < statusCount_ && status_[victim].barrier) ++victim;
    ++stats_.statusOverflow;
    if (victim == statusCount_) return false;
    removeStatus(victim);
  }
  memcpy(status_[statusCount_].bytes, packet, 10);
  status_[statusCount_].barrier = resumeBarrier;
  ++statusCount_;
  return true;
}

bool Transport::enqueueGesture(const uint8_t packet[8], uint32_t issuedMs) {
  if (!gestureReady()) return false;
  if (gestureCount_ == Capacity) { ++stats_.overflow; return false; }
  Gesture& item = gestures_[gestureCount_++];
  memcpy(item.bytes, packet, 8);
  item.issuedMs = issuedMs;
  item.linkEpoch = linkEpoch_;
  item.subscriptionEpoch = gestureEpoch_;
  item.attempts = 0;
  return true;
}

Transport::Result Transport::sendStatus(Sender send, void* context) {
  if (!connected_ || !statusEnabled_ || statusCount_ == 0) return Idle;
  if (!send(context, status_[0].bytes, 10)) return Blocked;
  if (status_[0].barrier) resumePending_ = false;
  removeStatus(0);
  return Sent;
}

Transport::Result Transport::sendGesture(uint32_t now, Sender send, void* context) {
  if (!gestureReady()) return Idle;
  bool discarded = false;
  while (gestureCount_ > 0) {
    Gesture& item = gestures_[0];
    if (item.linkEpoch != linkEpoch_ || item.subscriptionEpoch != gestureEpoch_) {
      ++stats_.linkDiscard;
      removeGesture();
      discarded = true;
      continue;
    }
    const uint32_t age = now - item.issuedMs;
    if (age >= GestureTtlMs || GestureTtlMs - age < NotifyBudgetMs) {
      ++stats_.expired;
      removeGesture();
      discarded = true;
      continue;
    }
    if (item.attempts++ > 0) ++stats_.retries;
    if (!send(context, item.bytes, 8)) { ++stats_.failures; return Blocked; }
    ++stats_.accepted;
    removeGesture();
    return Sent;
  }
  return discarded ? Discarded : Idle;
}

void Transport::runCycle(Clock clock, Sender status, Sender gesture, ImuDispatch imu, void* context) {
  if (sendStatus(status, context) == Blocked) return;
  // Read the clock after status: that notification may have waited 100ms.
  if (gesture && sendGesture(clock(context), gesture, context) == Blocked) return;
  if (imu && imuReady()) imu(context);
}

} // namespace ringpilot
