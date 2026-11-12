package com.hintringpilot.ringpilot;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

/**
 * 페어링된 RingPilot-IMU에 연결해 알림을 받는다: 상태(일시정지·재개 등), IMU 원시값, 보드가 발행한 제스처, 5방향 스위치 포인터.
 * 패킷 형식은 firmware/gesture_infer/src/ble_link.h·pointer.h·dev/imu_stream.h에 있다. 펌웨어마다 있는 특성이 다르다:
 * 사용자 빌드(gesture_infer 기본)는 상태·제스처·포인터, 개발 빌드(RINGPILOT_IMU_STREAM=1)는 IMU까지, 수집 펌웨어(imu_ble_stream)는 상태·IMU.
 * 있는 특성만 SUBSCRIBE_ORDER 순서로 하나씩 구독하고, 마지막 구독이 끝나면 "수신 중"이 된다.
 * 끊기면 자동으로 다시 연결하고, 연결·일시정지·재개·제스처와 지연 측정값을 connection_log.csv에 남긴다(앱 쪽 판단 기록도 record로 같은 파일에 쓴다).
 * 콜백은 Bluetooth 스레드에서 호출된다.
 */
final class ImuBleClient {
    interface Listener {
        /** raw에는 샘플마다 accX,accY,accZ,gyrX,gyrY,gyrZ 원시값이 이어서 들어 있다. */
        void onSamples(long generation, long firstSlot, short[] raw, int count);

        void onStreamReady(long generation);

        /** Delivered synchronously before closing the old GATT, including manual stop. */
        void onStreamBoundary(long generation, String reason);

        void onConnectionText(String text);

        /** 보드(firmware/gesture_infer)가 발행한 제스처. direction은 UP, DOWN, LEFT, RIGHT다. */
        void onGesture(String direction, int sequence, double score);

        /**
         * 5방향 스위치 상태(비트 1 위, 2 아래, 4 왼쪽, 8 오른쪽)와 누적 클릭 수(0~255에서 돈다).
         * baseline이면 구독 직후 첫 패킷이라 클릭 수를 기준으로만 쓴다(보드가 재부팅했을 수도 있다).
         */
        void onPointer(int state, int clicks, boolean baseline);
    }

    static final String DEVICE_NAME = "RingPilot-IMU";
    private static final UUID SERVICE_UUID = UUID.fromString("b27a2000-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID DATA_UUID = UUID.fromString("b27a2001-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID STATUS_UUID = UUID.fromString("b27a2002-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID GESTURE_UUID = UUID.fromString("b27a2003-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID POINTER_UUID = UUID.fromString("b27a2004-8c5e-4b62-9a21-33dd714e9001");
    /** 알림은 한 번에 하나씩 설정한다(쓰기가 끝나야 다음). 상태가 먼저고, 나머지는 있으면 이 순서로. */
    private static final UUID[] SUBSCRIBE_ORDER = {STATUS_UUID, DATA_UUID, GESTURE_UUID, POINTER_UUID};
    private static final String[] GESTURE_NAMES = {"NONE", "UP", "DOWN", "LEFT", "RIGHT"};
    private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private static final long RETRY_DELAY_MS = 300;

    // 펌웨어 상태 패킷의 이벤트 번호
    private static final int EVENT_SUBSCRIBED = 0;
    private static final int EVENT_PAUSED = 1;
    private static final int EVENT_RESUMED = 2;
    private static final int EVENT_FIRST_DATA = 3;

    private final Context context;
    private final Listener listener;
    private final File logFile;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final BleConnectionEpoch epoch = new BleConnectionEpoch();
    private final Object linkLock = new Object();
    private BluetoothDevice device;
    private BluetoothGatt gatt;
    private boolean running = false;
    private long generation;

    private boolean pointerBaseline = false;  // 다음 포인터 패킷이 구독 직후 첫 패킷이다(linkLock 안에서만 바뀐다)
    private volatile boolean streaming = false;  // IMU 원시값을 받는 중(수집·연속 기록에 필요)
    private volatile boolean devicePaused = false;
    private volatile long missingSamples = 0;
    private volatile double recentRate = 0;

    // 아래 값은 모두 Bluetooth 콜백 스레드에서만 바뀐다. 시각은 SystemClock.elapsedRealtime() 기준 ms.
    private long disconnectedAt = -1;
    private long connectedAt = -1;
    private long resumedStatusAt = -1;
    private boolean resumePending = false;
    private long expectedSlot = -1;
    private long rateWindowStart = -1;
    private long rateWindowSamples = 0;

    ImuBleClient(Context context, File logFile, Listener listener) {
        this.context = context;
        this.logFile = logFile;
        this.listener = listener;
    }

    boolean isStreaming() {
        return streaming;
    }

    boolean isDevicePaused() {
        return devicePaused;
    }

    long missingSamples() {
        return missingSamples;
    }

    double recentRate() {
        return recentRate;
    }

    /** 본딩된 RingPilot-IMU를 찾아 연결을 시작한다. 실패하면 이유를 반환하고, 성공하면 null. */
    String start() {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) return "Bluetooth를 켭니다.";
        device = null;
        for (BluetoothDevice bonded : adapter.getBondedDevices()) {
            if (DEVICE_NAME.equals(bonded.getName())) {
                device = bonded;
                break;
            }
        }
        if (device == null) return DEVICE_NAME + "를 먼저 페어링합니다.";
        synchronized (linkLock) { running = true; }
        record("client_start", "");
        connect();
        return null;
    }

    void stop() {
        synchronized (linkLock) {
            running = false;
            mainHandler.removeCallbacksAndMessages(null);
            closeGatt("stopped");
        }
    }

    private void connect() {
        synchronized (linkLock) {
            if (!running || device == null) return;
            closeGatt("connection_lost");
            generation = epoch.begin();
            expectedSlot = -1; rateWindowStart = -1; rateWindowSamples = 0;
            devicePaused = false;
            listener.onConnectionText("연결 시도 중");
            gatt = device.connectGatt(context, false, callback(generation), BluetoothDevice.TRANSPORT_LE);
            epoch.attach(generation, gatt);
            if (gatt == null) {
                closeGatt("connection_lost");
                scheduleReconnect(generation);
            }
        }
    }

    /** Caller holds linkLock. A stream ends even if Android never sends DISCONNECTED. */
    private void closeGatt(String reason) {
        streaming = false;
        if (epoch.end(generation)) {
            listener.onStreamBoundary(generation, reason);
        }
        if (gatt != null) {
            gatt.close();
            gatt = null;
        }
    }

    private boolean current(BluetoothGatt candidate, long attempt) {
        return running && epoch.current(attempt, candidate);
    }

    private void scheduleReconnect(long attempt) {
        mainHandler.postDelayed(() -> {
            synchronized (linkLock) {
                if (running && generation == attempt && gatt == null) connect();
            }
        }, RETRY_DELAY_MS);
    }

    private BluetoothGattCallback callback(long attempt) {
        return new BluetoothGattCallback() {
            @Override
            public void onConnectionStateChange(BluetoothGatt g, int statusCode, int newState) {
                synchronized (linkLock) {
                    if (!current(g, attempt)) return;
                    long now = SystemClock.elapsedRealtime();
                    if (newState == BluetoothProfile.STATE_CONNECTED && statusCode == BluetoothGatt.GATT_SUCCESS) {
                        connectedAt = now;
                        expectedSlot = -1;
                        record("connected", disconnectedAt >= 0 ? "since_disconnect_ms=" + (now - disconnectedAt) : "");
                        listener.onConnectionText("연결됨, 설정 중");
                        if (!g.requestMtu(247)) g.discoverServices();
                    } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                        closeGatt("connection_lost");
                        if (connectedAt >= 0) {
                            disconnectedAt = now;
                            connectedAt = -1;
                            record("disconnected", "status=" + statusCode);
                        } else {
                            record("connect_failed", "status=" + statusCode);
                        }
                        resumePending = false;
                        listener.onConnectionText("연결 끊김, 다시 연결 중");
                        scheduleReconnect(attempt);
                    }
                }
            }

            @Override
            public void onMtuChanged(BluetoothGatt g, int mtu, int statusCode) {
                synchronized (linkLock) {
                    if (!current(g, attempt)) return;
                    record("mtu", "mtu=" + mtu + " status=" + statusCode);
                    refreshGattCache(g);
                    g.discoverServices();
                }
            }

            @Override
            public void onServicesDiscovered(BluetoothGatt g, int statusCode) {
                synchronized (linkLock) {
                    if (!current(g, attempt)) return;
                    BluetoothGattService service = g.getService(SERVICE_UUID);
                    if (statusCode != BluetoothGatt.GATT_SUCCESS || service == null) {
                        listener.onConnectionText("IMU 서비스를 찾지 못함 (status=" + statusCode + ")");
                        return;
                    }
                    record("characteristics", "imu=" + (service.getCharacteristic(DATA_UUID) != null)
                            + " gesture=" + (service.getCharacteristic(GESTURE_UUID) != null)
                            + " pointer=" + (service.getCharacteristic(POINTER_UUID) != null));
                    enableNotify(g, service.getCharacteristic(STATUS_UUID));
                }
            }

            @Override
            public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor descriptor, int statusCode) {
                synchronized (linkLock) {
                    if (!current(g, attempt)) return;
                    if (statusCode != BluetoothGatt.GATT_SUCCESS) {
                        listener.onConnectionText("알림 설정 실패 (status=" + statusCode + ")");
                        return;
                    }
                    UUID chr = descriptor.getCharacteristic().getUuid();
                    if (DATA_UUID.equals(chr)) {
                        streaming = true;
                        if (!devicePaused) listener.onStreamReady(attempt);
                    }
                    if (GESTURE_UUID.equals(chr)) record("gesture_subscribed", "");
                    if (POINTER_UUID.equals(chr)) pointerBaseline = true;
                    BluetoothGattCharacteristic next = nextToSubscribe(g.getService(SERVICE_UUID), chr);
                    if (next != null) enableNotify(g, next);
                    else subscribed();
                }
            }

            @Override
            public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic characteristic) {
                synchronized (linkLock) {
                    if (!current(g, attempt)) return;
                    handleNotification(attempt, characteristic.getUuid(), characteristic.getValue());
                }
            }

            @Override
            public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic characteristic, byte[] value) {
                synchronized (linkLock) {
                    if (!current(g, attempt)) return;
                    handleNotification(attempt, characteristic.getUuid(), value);
                }
            }
        };
    }

    /** SUBSCRIBE_ORDER에서 done 다음에 오는 특성 중 이 펌웨어에 있는 첫 번째. 없으면 null. */
    private static BluetoothGattCharacteristic nextToSubscribe(BluetoothGattService service, UUID done) {
        boolean after = false;
        for (UUID uuid : SUBSCRIBE_ORDER) {
            if (after) {
                BluetoothGattCharacteristic chr = service.getCharacteristic(uuid);
                if (chr != null) return chr;
            }
            if (uuid.equals(done)) after = true;
        }
        return null;
    }

    /** 있는 알림을 모두 구독했다. 재연결 시간 측정의 기준점이다. linkLock 안에서 부른다. */
    private void subscribed() {
        long now = SystemClock.elapsedRealtime();
        record("subscribed", disconnectedAt >= 0 ? "since_disconnect_ms=" + (now - disconnectedAt) : "");
        listener.onConnectionText(devicePaused ? "링 일시정지됨 (연결 유지)" : "수신 중");
    }

    /** 본딩된 기기의 GATT 목록은 휴대폰에 캐시된다. 펌웨어에 특성이 추가돼도 보이도록 비운다(숨은 API, 실패하면 캐시를 그대로 쓴다). */
    private void refreshGattCache(BluetoothGatt g) {
        try {
            Object ok = g.getClass().getMethod("refresh").invoke(g);
            record("gatt_refresh", String.valueOf(ok));
        } catch (ReflectiveOperationException e) {
            record("gatt_refresh", "failed " + e.getClass().getSimpleName());
        }
    }

    private void enableNotify(BluetoothGatt g, BluetoothGattCharacteristic characteristic) {
        BluetoothGattDescriptor cccd = characteristic == null ? null : characteristic.getDescriptor(CCCD_UUID);
        if (cccd == null || !g.setCharacteristicNotification(characteristic, true)) {
            listener.onConnectionText("알림 설정 실패");
            return;
        }
        cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
        if (!g.writeDescriptor(cccd)) listener.onConnectionText("알림 설정 쓰기 실패");
    }

    private void handleNotification(long attempt, UUID uuid, byte[] value) {
        if (value == null) return;
        if (STATUS_UUID.equals(uuid)) handleStatus(attempt, value);
        else if (DATA_UUID.equals(uuid)) handleData(attempt, value);
        else if (GESTURE_UUID.equals(uuid)) handleGesture(value);
        else if (POINTER_UUID.equals(uuid)) handlePointer(value);
    }

    private void handlePointer(byte[] v) {
        if (v.length < 3) return;
        boolean baseline = pointerBaseline;
        pointerBaseline = false;
        listener.onPointer(v[1] & 0x0F, v[2] & 0xFF, baseline);
    }

    private void handleStatus(long attempt, byte[] v) {
        if (v.length < 10) return;
        int state = v[0] & 0xFF;
        int event = v[1] & 0xFF;
        long uptime = readU32(v, 2);
        long sinceTrigger = readU32(v, 6);
        long now = SystemClock.elapsedRealtime();
        devicePaused = state == 1;
        String base = "state=" + (devicePaused ? "PAUSED" : "STREAMING") + " device_uptime_ms=" + uptime;

        switch (event) {
            case EVENT_SUBSCRIBED:
                record("status_subscribed", base);
                break;
            case EVENT_PAUSED:
                listener.onStreamBoundary(attempt, "paused");
                record("paused", base);
                listener.onConnectionText("링 일시정지됨 (연결 유지)");
                break;
            case EVENT_RESUMED:
                if (streaming) listener.onStreamReady(attempt);
                resumePending = true;
                resumedStatusAt = now;
                expectedSlot = -1;  // 일시정지 동안의 슬롯 공백은 누락이 아니다
                record("resumed", base);
                listener.onConnectionText("수신 중");
                break;
            case EVENT_FIRST_DATA:
                if (resumePending) {
                    resumePending = false;
                    record("RESULT_pause_resume", "device_release_to_first_data_ms=" + sinceTrigger
                            + " phone_resumed_status_to_now_ms=" + (now - resumedStatusAt));
                } else if (disconnectedAt < 0) {
                    record("initial_first_data", "device_since_boot_ms=" + sinceTrigger);
                } else {
                    record("RESULT_boot_reconnect", "device_boot_to_first_data_ms=" + sinceTrigger
                            + " phone_disconnect_to_now_ms=" + (now - disconnectedAt));
                }
                break;
            default:
                record("status_unknown", "event=" + event);
        }
    }

    private void handleGesture(byte[] v) {
        if (v.length < 8) return;
        int sequence = v[0] & 0xFF;
        int index = v[1] & 0xFF;
        if (index < 1 || index >= GESTURE_NAMES.length) return;
        double score = ((v[2] & 0xFF) | ((v[3] & 0xFF) << 8)) / 1000.0;
        record("gesture", "seq=" + sequence + " dir=" + GESTURE_NAMES[index] + " score=" + score + " slot=" + readU32(v, 4));
        listener.onGesture(GESTURE_NAMES[index], sequence, score);
    }

    private void handleData(long attempt, byte[] v) {
        if (!streaming || devicePaused || v.length < 5) return;
        long firstSlot = readU32(v, 0);
        int count = v[4] & 0xFF;
        if (v.length < 5 + count * 12) return;

        short[] raw = new short[count * 6];
        for (int i = 0; i < raw.length; i++) {
            int offset = 5 + i * 2;
            raw[i] = (short) ((v[offset] & 0xFF) | (v[offset + 1] << 8));
        }

        if (expectedSlot >= 0 && firstSlot > expectedSlot) missingSamples += firstSlot - expectedSlot;
        expectedSlot = firstSlot + count;
        long now = SystemClock.elapsedRealtime();
        if (rateWindowStart < 0) rateWindowStart = now;
        rateWindowSamples += count;
        if (now - rateWindowStart >= 2000) {
            recentRate = rateWindowSamples * 1000.0 / (now - rateWindowStart);
            rateWindowStart = now;
            rateWindowSamples = 0;
        }
        listener.onSamples(attempt, firstSlot, raw, count);
    }

    private static long readU32(byte[] v, int offset) {
        return (v[offset] & 0xFFL)
                | ((v[offset + 1] & 0xFFL) << 8)
                | ((v[offset + 2] & 0xFFL) << 16)
                | ((v[offset + 3] & 0xFFL) << 24);
    }

    synchronized void record(String event, String detail) {
        String wall = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(new Date());
        boolean header = !logFile.exists();
        try (FileWriter writer = new FileWriter(logFile, true)) {
            if (header) writer.write("wall_time,phone_ms,event,detail\n");
            writer.write(wall + "," + SystemClock.elapsedRealtime() + "," + event + "," + detail.replace(',', ';') + "\n");
        } catch (IOException ignored) {
            // 연결 기록 실패로 수집을 멈추지 않는다
        }
    }
}
