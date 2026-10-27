'use strict';

// Small numeric helpers shared by the gesture annotation tools.

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const hi = sorted.length >> 1;
  const lo = (sorted.length - 1) >> 1;
  return (sorted[lo] + sorted[hi]) / 2;
}

function mean(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

// Centered moving average; the window shrinks at the edges.
function movingAverage(values, width) {
  const radius = Math.floor(width / 2);
  return values.map((_, ix) => {
    const start = Math.max(0, ix - radius);
    const end = Math.min(values.length, ix + radius + 1);
    return mean(values.slice(start, end));
  });
}

module.exports = { median, mean, movingAverage };
