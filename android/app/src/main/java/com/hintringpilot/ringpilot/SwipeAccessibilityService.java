package com.hintringpilot.ringpilot;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.util.DisplayMetrics;
import android.view.accessibility.AccessibilityEvent;

import java.lang.ref.WeakReference;

public final class SwipeAccessibilityService extends AccessibilityService {
    private static WeakReference<SwipeAccessibilityService> current = new WeakReference<>(null);

    static SwipeAccessibilityService getCurrent() {
        return current.get();
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        current = new WeakReference<>(this);
    }

    @Override
    public void onDestroy() {
        if (current.get() == this) {
            current.clear();
        }
        super.onDestroy();
    }

    boolean swipe(String direction) {
        DisplayMetrics metrics = getResources().getDisplayMetrics();
        float startX = metrics.widthPixels * 0.5f;
        float startY = metrics.heightPixels * 0.5f;
        float endX = startX;
        float endY = startY;

        switch (direction) {
            case "UP":
                startY = metrics.heightPixels * 0.75f;
                endY = metrics.heightPixels * 0.25f;
                break;
            case "DOWN":
                startY = metrics.heightPixels * 0.25f;
                endY = metrics.heightPixels * 0.75f;
                break;
            case "LEFT":
                startX = metrics.widthPixels * 0.80f;
                endX = metrics.widthPixels * 0.20f;
                break;
            case "RIGHT":
                startX = metrics.widthPixels * 0.20f;
                endX = metrics.widthPixels * 0.80f;
                break;
            default:
                return false;
        }

        Path path = new Path();
        path.moveTo(startX, startY);
        path.lineTo(endX, endY);

        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 400))
                .build();
        return dispatchGesture(gesture, null, null);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // This prototype only injects gestures; it does not inspect screen content.
    }

    @Override
    public void onInterrupt() {
        // No continuous accessibility feedback to interrupt.
    }
}
