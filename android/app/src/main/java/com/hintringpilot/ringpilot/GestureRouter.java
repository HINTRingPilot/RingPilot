package com.hintringpilot.ringpilot;

import java.util.Locale;

/**
 * 받은 제스처를 화면 동작으로 바꾸는 판단만 맡는다. 안드로이드에 의존하지 않아 JDK로 시험한다(android/tests).
 * 좌우 제스처는 방향을 구분하지 않고 상하·좌우 모드를 바꾼다. 위·아래 제스처는 모드에 맞는 스와이프가 된다.
 */
final class GestureRouter {
    enum Kind { RECEIVE_ONLY, NO_SERVICE, MODE_CHANGED, SWIPE }

    static final class Action {
        final Kind kind;
        final String swipe;  // SWIPE일 때만 있다
        final boolean horizontalBefore, horizontalAfter;
        private final String direction;
        private final boolean control, service;

        private Action(Kind kind, String swipe, boolean horizontalBefore, boolean horizontalAfter,
                       String direction, boolean control, boolean service) {
            this.kind = kind;
            this.swipe = swipe;
            this.horizontalBefore = horizontalBefore;
            this.horizontalAfter = horizontalAfter;
            this.direction = direction;
            this.control = control;
            this.service = service;
        }

        /** 연결 기록 한 줄. seq로 같은 제스처의 gesture 행과 맞춘다. */
        String logDetail(int sequence, double score) {
            return String.format(Locale.US, "seq=%d dir=%s score=%.3f control=%d service=%d mode=%s>%s action=%s swipe=%s",
                    sequence, direction, score, control ? 1 : 0, service ? 1 : 0,
                    horizontalBefore ? "H" : "V", horizontalAfter ? "H" : "V",
                    kind.name().toLowerCase(Locale.US), swipe == null ? "-" : swipe);
        }
    }

    private boolean horizontal = false;  // 앱을 다시 시작하면 상하 모드로 돌아간다

    Action route(String direction, boolean control, boolean service) {
        boolean before = horizontal;
        Kind kind;
        String swipe = null;
        if (!control) {
            kind = Kind.RECEIVE_ONLY;
        } else if (!service) {
            kind = Kind.NO_SERVICE;
        } else if ("LEFT".equals(direction) || "RIGHT".equals(direction)) {
            horizontal = !horizontal;
            kind = Kind.MODE_CHANGED;
        } else {
            kind = Kind.SWIPE;
            swipe = !horizontal ? direction : "UP".equals(direction) ? "LEFT" : "RIGHT";
        }
        return new Action(kind, swipe, before, horizontal, direction, control, service);
    }

    /** result: completed, cancelled, not_dispatched. 요청이 끝났다는 뜻이며 화면이 원하는 대로 움직였다는 뜻은 아니다. */
    static String swipeDetail(int sequence, String swipe, String result) {
        return "seq=" + sequence + " swipe=" + swipe + " result=" + result;
    }
}
