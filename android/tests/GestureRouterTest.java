package com.hintringpilot.ringpilot;
public final class GestureRouterTest {
  static void check(boolean yes) { if (!yes) throw new AssertionError(); }
  static void same(String actual, String expected) { if (!expected.equals(actual)) throw new AssertionError(actual + " != " + expected); }
  public static void main(String[] args) {
    // 시작은 상하 모드이고 위·아래는 그대로 나간다
    GestureRouter r = new GestureRouter();
    GestureRouter.Action up = r.route("UP", true, true);
    check(up.kind == GestureRouter.Kind.SWIPE);
    same(up.swipe, "UP");
    same(r.route("DOWN", true, true).swipe, "DOWN");

    // 좌우는 방향과 상관없이 모드를 바꾸고 스와이프를 내지 않는다
    GestureRouter.Action toHorizontal = r.route("LEFT", true, true);
    check(toHorizontal.kind == GestureRouter.Kind.MODE_CHANGED);
    check(toHorizontal.swipe == null);
    check(!toHorizontal.horizontalBefore && toHorizontal.horizontalAfter);

    // 좌우 모드: 위 = 왼쪽, 아래 = 오른쪽
    same(r.route("UP", true, true).swipe, "LEFT");
    same(r.route("DOWN", true, true).swipe, "RIGHT");

    // 오른쪽 제스처도 같은 전환이다
    GestureRouter.Action toVertical = r.route("RIGHT", true, true);
    check(toVertical.kind == GestureRouter.Kind.MODE_CHANGED);
    check(toVertical.horizontalBefore && !toVertical.horizontalAfter);
    same(r.route("UP", true, true).swipe, "UP");

    // 제어가 꺼져 있으면 아무것도 나가지 않고 모드도 그대로다
    GestureRouter off = new GestureRouter();
    GestureRouter.Action ignored = off.route("LEFT", false, true);
    check(ignored.kind == GestureRouter.Kind.RECEIVE_ONLY);
    check(!ignored.horizontalAfter);
    check(off.route("UP", false, true).swipe == null);
    same(off.route("UP", true, true).swipe, "UP");

    // 접근성 서비스가 꺼져 있어도 모드를 바꾸지 않는다
    GestureRouter noService = new GestureRouter();
    GestureRouter.Action blocked = noService.route("RIGHT", true, false);
    check(blocked.kind == GestureRouter.Kind.NO_SERVICE);
    check(!blocked.horizontalAfter);
    check(noService.route("UP", true, false).swipe == null);
    same(noService.route("UP", true, true).swipe, "UP");

    // 기록 한 줄: 순번으로 연결 기록의 gesture 행과 맞출 수 있고, CSV를 깨는 쉼표가 없다
    GestureRouter log = new GestureRouter();
    same(log.route("LEFT", true, true).logDetail(7, 0.999), "seq=7 dir=LEFT score=0.999 control=1 service=1 mode=V>H action=mode_changed swipe=-");
    same(log.route("UP", true, true).logDetail(8, 0.5), "seq=8 dir=UP score=0.500 control=1 service=1 mode=H>H action=swipe swipe=LEFT");
    same(log.route("DOWN", false, true).logDetail(9, 0.9), "seq=9 dir=DOWN score=0.900 control=0 service=1 mode=H>H action=receive_only swipe=-");
    same(log.route("DOWN", true, false).logDetail(10, 0.9), "seq=10 dir=DOWN score=0.900 control=1 service=0 mode=H>H action=no_service swipe=-");
    same(GestureRouter.swipeDetail(8, "LEFT", "completed"), "seq=8 swipe=LEFT result=completed");
    System.out.println("gesture router tests passed");
  }
}
