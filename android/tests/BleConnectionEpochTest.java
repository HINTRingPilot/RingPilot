package com.hintringpilot.ringpilot;

/** BleConnectionEpoch는 루트 패키지 전용이라 수집 테스트(dev 패키지)와 따로 둔다. */
public final class BleConnectionEpochTest {
    static int checks;
    static void check(boolean value, String why) { checks++; if (!value) throw new AssertionError(why); }

    public static void main(String[] args) {
        BleConnectionEpoch epoch = new BleConnectionEpoch(); Object oldGatt = new Object(), newGatt = new Object();
        long first = epoch.begin(); epoch.attach(first, oldGatt);
        check(epoch.current(first, oldGatt), "current GATT accepted");
        check(epoch.end(first), "stop delivers boundary without disconnect callback");
        check(!epoch.end(first), "disconnect after stop cannot deliver duplicate boundary");
        long second = epoch.begin(); epoch.attach(second, newGatt);
        check(!epoch.current(first, oldGatt), "stale GATT callback rejected");
        check(!epoch.end(first) && epoch.current(second, newGatt), "stale disconnect cannot close new GATT");
        System.out.println("BleConnectionEpoch: " + checks + " checks passed");
    }
}
