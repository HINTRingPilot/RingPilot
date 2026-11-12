#include <RingPilotTransport.h>
#include <RingPilotBleMailbox.h>
#include <cassert>
#include <cstring>
#include <cstdio>
#include <vector>

using ringpilot::Transport;
int transportCriticalDepth = 0;
struct Sender {
  bool accept = true;
  unsigned calls = 0;
  std::vector<std::vector<uint8_t> > packets;
  static bool send(void* context, const uint8_t* bytes, uint8_t length) {
    assert(transportCriticalDepth == 0);
    Sender& self = *static_cast<Sender*>(context);
    ++self.calls;
    self.packets.push_back(std::vector<uint8_t>(bytes, bytes + length));
    return self.accept;
  }
};
static void bind(Transport& transport, uint32_t link = 1, uint32_t subscription = 1,
                 bool status = true, bool gesture = true) {
  transport.synchronize(link, subscription, true, status, gesture);
}
static void status_packet(uint8_t packet[10], uint8_t event) {
  std::memset(packet, 0, 10);
  packet[1] = event;
}

static void status_queue_and_resume_barrier() {
  Transport transport;
  bind(transport);
  Sender sender;
  uint8_t packet[10];
  assert(transport.sendStatus(Sender::send, &sender) == Transport::Idle);
  status_packet(packet, 1); transport.enqueueStatus(packet);
  status_packet(packet, 0); transport.enqueueStatus(packet);
  status_packet(packet, 2); transport.enqueueStatus(packet, true);
  assert(!transport.imuReady());
  sender.accept = false;
  assert(transport.sendStatus(Sender::send, &sender) == Transport::Blocked);
  assert(transport.statusCount() == 3);
  sender.accept = true;
  assert(transport.sendStatus(Sender::send, &sender) == Transport::Sent);
  assert(!transport.imuReady());
  assert(transport.sendStatus(Sender::send, &sender) == Transport::Sent);
  assert(!transport.imuReady());
  assert(transport.sendStatus(Sender::send, &sender) == Transport::Sent);
  assert(transport.imuReady());
  assert(transport.statusCount() == 0);
  for (unsigned i = 0; i < 300; ++i) transport.sendStatus(Sender::send, &sender);
  assert(transport.statusCount() == 0); // no empty-pop uint8 underflow
}

static void protected_resume_survives_overflow_and_unsubscribe() {
  Transport transport;
  bind(transport);
  uint8_t packet[10];
  status_packet(packet, 2); transport.enqueueStatus(packet, true);
  for (unsigned i = 0; i < 12; ++i) {
    status_packet(packet, 0); transport.enqueueStatus(packet);
    assert(transport.statusCount() <= Transport::Capacity);
  }
  assert(!transport.imuReady());
  bind(transport, 1, 1, false, true);
  assert(transport.statusCount() == 1);
  Sender sender;
  transport.sendStatus(Sender::send, &sender);
  assert(sender.calls == 0 && !transport.imuReady());
  bind(transport);
  assert(transport.sendStatus(Sender::send, &sender) == Transport::Sent);
  assert(sender.packets[0][1] == 2 && transport.imuReady());
}

static void retries_keep_bytes_and_sequence() {
  Transport transport;
  bind(transport);
  uint8_t packet[8] = {7, 1, 0xB6, 3, 11, 0, 0, 0};
  assert(transport.enqueueGesture(packet, 1000));
  Sender sender;
  sender.accept = false;
  assert(transport.sendGesture(1000, Sender::send, &sender) == Transport::Blocked);
  assert(transport.sendGesture(1010, Sender::send, &sender) == Transport::Blocked);
  sender.accept = true;
  assert(transport.sendGesture(1020, Sender::send, &sender) == Transport::Sent);
  assert(sender.calls == 3 && sender.packets[0] == sender.packets[1] && sender.packets[1] == sender.packets[2]);
  assert(transport.stats().accepted == 1 && transport.stats().retries == 2);
  assert(transport.sendGesture(1030, Sender::send, &sender) == Transport::Idle);
  assert(sender.calls == 3);
}

static void expiry_budget_and_wrap() {
  Transport transport;
  bind(transport);
  uint8_t packet[8] = {1};
  Sender sender;
  sender.accept = false;
  transport.enqueueGesture(packet, 0);
  transport.sendGesture(0, Sender::send, &sender);
  transport.sendGesture(100, Sender::send, &sender);
  assert(transport.sendGesture(200, Sender::send, &sender) == Transport::Discarded);
  assert(sender.calls == 2 && transport.stats().expired == 1);
  transport.enqueueGesture(packet, 1000);
  transport.sendGesture(1250, Sender::send, &sender);
  assert(sender.calls == 2 && transport.gestureCount() == 0);
  transport.enqueueGesture(packet, UINT32_MAX - 10);
  sender.accept = true;
  assert(transport.sendGesture(5, Sender::send, &sender) == Transport::Sent);
}

static void boundaries_pause_and_capacity() {
  {
    Transport fifo;
    bind(fifo);
    Sender delivered;
    for (uint8_t sequence = 0; sequence < Transport::Capacity; ++sequence) {
      uint8_t unique[8] = {sequence};
      assert(fifo.enqueueGesture(unique, 0));
    }
    uint8_t overflow[8] = {99};
    assert(!fifo.enqueueGesture(overflow, 0));
    for (unsigned i = 0; i < Transport::Capacity; ++i) {
      assert(fifo.sendGesture(0, Sender::send, &delivered) == Transport::Sent);
      assert(delivered.packets.back()[0] == i);
    }
  }
  Transport transport;
  bind(transport);
  uint8_t packet[8] = {1};
  Sender sender;
  for (unsigned i = 0; i < Transport::Capacity; ++i) assert(transport.enqueueGesture(packet, 0));
  assert(!transport.enqueueGesture(packet, 0));
  assert(transport.stats().overflow == 1);
  bind(transport, 2, 1); // same physical handle may be reused, generation is different
  assert(transport.gestureCount() == 0 && transport.stats().linkDiscard == 4);
  transport.enqueueGesture(packet, 0);
  bind(transport, 2, 2); // unsubscribe+subscribe coalesced, epoch still changed
  assert(transport.gestureCount() == 0 && transport.stats().subscriptionDiscard == 1);
  transport.enqueueGesture(packet, 0);
  transport.pause();
  assert(transport.gestureCount() == 0 && transport.stats().pausedDiscard == 1);
  transport.sendGesture(0, Sender::send, &sender);
  assert(sender.calls == 0);
  uint8_t resumed[10]; status_packet(resumed, 2);
  transport.enqueueStatus(resumed, true);
  transport.pause();
  assert(!transport.imuReady());
  transport.enqueueStatus(resumed, true);
  transport.sendStatus(Sender::send, &sender);
  assert(transport.imuReady()); // canceled resume cannot leave a permanent barrier
  transport.synchronize(3, 3, false, false, false);
  assert(!transport.imuReady() && !transport.enqueueGesture(packet, 0));
  transport.pause();
  transport.enqueueStatus(resumed, true); // resume while disconnected
  bind(transport, 4, 4);
  assert(transport.imuReady() && transport.enqueueGesture(packet, 10));
}

static void callback_mailbox_preserves_revoke_history() {
  ringpilot::BleMailbox mailbox;
  mailbox.onConnect(7);
  mailbox.onGestureCccd(7, 1);
  mailbox.onStatusCccd(7, 1);
  ringpilot::BleMailbox::Snapshot first = mailbox.snapshot(true);
  assert(first.statusSubscribed && mailbox.current(first, true));
  assert(!mailbox.snapshot(true).statusSubscribed);
  mailbox.onGestureCccd(7, 0);
  mailbox.onGestureCccd(7, 1); // the final enabled bit alone cannot show this revocation
  ringpilot::BleMailbox::Snapshot second = mailbox.snapshot();
  assert(second.gestureEnabled && second.gestureEpoch != first.gestureEpoch);
  assert(!mailbox.current(first, true));
  assert(mailbox.current(first, false));
  mailbox.onDisconnect(7);
  mailbox.onConnect(7); // recycled handle must not recycle the connection generation
  assert(!mailbox.current(second));
  mailbox.onStatusCccd(8, 1); // unrelated stale handle is ignored
  assert(!mailbox.snapshot().statusEnabled);
  assert(transportCriticalDepth == 0);
}

// This uses the same dispatcher and epoch-checking adapter as the two sketches.
struct CycleHarness {
  Transport transport;
  ringpilot::BleMailbox mailbox;
  ringpilot::BleMailbox::Snapshot binding;
  std::vector<int> trace;
  uint32_t now = 100;
  uint32_t statusDelayMs = 0;
  bool statusAccepted = true, gestureAccepted = true, dataReady = true;
  int mutateDuringStatus = 0; // 1: off/on gesture, 2: recycle link handle
  unsigned statusCalls = 0, gestureCalls = 0, imuCalls = 0;
  CycleHarness() {
    mailbox.onConnect(7);
    mailbox.onStatusCccd(7, 1);
    mailbox.onGestureCccd(7, 1);
    synchronize();
  }
  void synchronize() {
    binding = mailbox.snapshot(true);
    transport.synchronize(binding.linkEpoch, binding.gestureEpoch,
                          binding.handle != BLE_CONN_HANDLE_INVALID,
                          binding.statusEnabled, binding.gestureEnabled);
  }
  struct Characteristic {
    CycleHarness& harness;
    ringpilot::BleMailbox::Channel kind;
    bool notify(uint16_t, const uint8_t* packet, uint8_t) {
      assert(transportCriticalDepth == 0);
      if (kind == ringpilot::BleMailbox::Status) {
        ++harness.statusCalls;
        harness.now += harness.statusDelayMs;
        if (harness.mutateDuringStatus) {
          assert(harness.transport.statusCount() == 1 && harness.transport.gestureCount() == 1);
          if (harness.mutateDuringStatus == 1) {
            harness.mailbox.onGestureCccd(7, 0);
            harness.mailbox.onGestureCccd(7, 1);
          } else {
            harness.mailbox.onDisconnect(7);
            harness.mailbox.onConnect(7);
          }
          // Callbacks publish only. They never remove or replace the in-flight queue head.
          assert(harness.transport.statusCount() == 1 && harness.transport.gestureCount() == 1);
        }
        if (harness.statusAccepted) harness.trace.push_back(packet[1]);
        return harness.statusAccepted;
      }
      if (kind == ringpilot::BleMailbox::Gesture) {
        ++harness.gestureCalls;
        if (harness.gestureAccepted) harness.trace.push_back(10);
        return harness.gestureAccepted;
      }
      ++harness.imuCalls;
      harness.trace.push_back(20);
      return true;
    }
  };
  static uint32_t clock(void* context) { return static_cast<CycleHarness*>(context)->now; }
  static bool sendStatus(void* context, const uint8_t* packet, uint8_t length) {
    CycleHarness& h = *static_cast<CycleHarness*>(context);
    Characteristic chr = {h, ringpilot::BleMailbox::Status};
    bool boundary;
    const bool result = h.mailbox.notifyCurrent(h.binding, chr.kind, chr, packet, length, boundary);
    if (boundary) h.transport.noteInFlightBoundary();
    return result;
  }
  static bool sendGesture(void* context, const uint8_t* packet, uint8_t length) {
    CycleHarness& h = *static_cast<CycleHarness*>(context);
    Characteristic chr = {h, ringpilot::BleMailbox::Gesture};
    bool boundary;
    const bool result = h.mailbox.notifyCurrent(h.binding, chr.kind, chr, packet, length, boundary);
    if (boundary) h.transport.noteInFlightBoundary();
    return result;
  }
  static void sendImu(void* context) {
    CycleHarness& h = *static_cast<CycleHarness*>(context);
    if (!h.dataReady) return;
    Characteristic chr = {h, ringpilot::BleMailbox::Data};
    uint8_t packet[17] = {0}; // MTU23 permits a single 12-byte sample + header
    bool boundary;
    if (h.mailbox.notifyCurrent(h.binding, chr.kind, chr, packet, 17, boundary)) {
      h.dataReady = false;
      uint8_t firstData[10]; status_packet(firstData, 3);
      h.transport.enqueueStatus(firstData);
    }
  }
  void cycle() { transport.runCycle(clock, sendStatus, sendGesture, sendImu, this); }
};

static void callback_changes_during_notify_do_not_mutate_queue() {
  for (int mutation = 1; mutation <= 2; ++mutation) {
    CycleHarness h;
    h.mutateDuringStatus = mutation;
    uint8_t status[10]; status_packet(status, 0);
    h.transport.enqueueStatus(status);
    uint8_t gesture[8] = {5}; h.transport.enqueueGesture(gesture, h.now);
    h.cycle();
    assert(h.statusCalls == 1 && h.gestureCalls == 0 && h.imuCalls == 0);
    assert(h.transport.statusCount() == 0 && h.transport.gestureCount() == 1);
    h.synchronize();
    assert(h.transport.gestureCount() == 0);
    assert((mutation == 1 ? h.transport.stats().subscriptionDiscard : h.transport.stats().linkDiscard) == 1);
  }
}

static void dispatcher_resume_order_and_failure_short_circuit() {
  CycleHarness h;
  uint8_t status[10];
  status_packet(status, 1); h.transport.enqueueStatus(status);
  status_packet(status, 0); h.transport.enqueueStatus(status);
  status_packet(status, 2); h.transport.enqueueStatus(status, true);
  h.cycle(); assert(h.imuCalls == 0);
  h.cycle(); assert(h.imuCalls == 0);
  h.cycle(); assert(h.imuCalls == 1);
  h.cycle();
  const int expected[] = {1, 0, 2, 20, 3};
  assert(h.trace == std::vector<int>(expected, expected + 5));

  CycleHarness blocked;
  status_packet(status, 0); blocked.transport.enqueueStatus(status);
  uint8_t gesture[8] = {9}; blocked.transport.enqueueGesture(gesture, blocked.now);
  blocked.statusAccepted = false;
  blocked.cycle();
  assert(blocked.gestureCalls == 0 && blocked.imuCalls == 0);
  blocked.statusAccepted = true;
  blocked.gestureAccepted = false;
  blocked.cycle();
  assert(blocked.gestureCalls == 1 && blocked.imuCalls == 0);
  blocked.gestureAccepted = true;
  blocked.cycle();
  assert(blocked.imuCalls == 1);

  CycleHarness delayed;
  delayed.statusDelayMs = 100;
  status_packet(status, 0); delayed.transport.enqueueStatus(status);
  delayed.transport.enqueueGesture(gesture, 0); // already 100ms old at cycle entry
  delayed.cycle();
  assert(delayed.gestureCalls == 0 && delayed.transport.stats().expired == 1);
}

int main() {
  status_queue_and_resume_barrier();
  protected_resume_survives_overflow_and_unsubscribe();
  retries_keep_bytes_and_sequence();
  expiry_budget_and_wrap();
  boundaries_pause_and_capacity();
  callback_mailbox_preserves_revoke_history();
  callback_changes_during_notify_do_not_mutate_queue();
  dispatcher_resume_order_and_failure_short_circuit();
  std::puts("Transport state tests passed (8 scenario groups)");
}
