#!/usr/bin/env node

'use strict';

// Derive a return-based event time for each direction clip in data/annotations/ble-v2/records.json.
//
// r (new event time): first sample after the return-lobe peak where the dominant gyro axis has
// fallen to half of that peak. The scoring window is [return peak, r + 500 ms].
// The existing completion_ms (settled after the return) is kept for reference only.
//
// Usage: node tools/derive-return-labels.js [--ratio 0.5] [--out data/annotations/ble-v2-return/records.json]

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SAMPLE_MS = 10;
const WINDOW = 160;
const STRIDE = 5;
const FIRST_T = (WINDOW - 1) * SAMPLE_MS;
const POSITIVE_MS = 150;
const SCORE_AFTER_MS = 500;

function parseArgs(argv) {
  const args = {
    records: 'data/annotations/ble-v2/records.json',
    candidates: 'data/annotations/ble-v2',
    ratio: 0.5,
    out: 'data/annotations/ble-v2-return/records.json',
  };
  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--ratio') args.ratio = Number(argv[++ix]);
    else if (arg === '--out') args.out = argv[++ix];
    else throw new Error(`Unknown argument: ${arg}`);
  }
  if (!(args.ratio > 0 && args.ratio < 1)) throw new Error('--ratio must be between 0 and 1');
  return args;
}

// Same as ml/v2.py digest(): SHA-256 over bytes with CRLF folded to LF (core.autocrlf differs per checkout).
function digest(file) {
  const bytes = fs.readFileSync(file).toString('latin1').replaceAll('\r\n', '\n');
  return crypto.createHash('sha256').update(Buffer.from(bytes, 'latin1')).digest('hex');
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return (sorted[(sorted.length - 1) >> 1] + sorted[sorted.length >> 1]) / 2;
}

function movingAverage(values, width) {
  const radius = width >> 1;
  return values.map((_, ix) => {
    const start = Math.max(0, ix - radius);
    const end = Math.min(values.length, ix + radius + 1);
    let sum = 0;
    for (let k = start; k < end; k += 1) sum += values[k];
    return sum / (end - start);
  });
}

function readRows(file) {
  return fs.readFileSync(file, 'utf8').trim().split(/\r?\n/).slice(1).map(line => line.split(',').map(Number));
}

function loadMotionStarts(dir) {
  const starts = new Map();
  for (const name of fs.readdirSync(dir).filter(n => n.endsWith('-candidates.json'))) {
    for (const a of JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8')).annotations) {
      starts.set(a.source_path, a.main_motion_start_ms);
    }
  }
  return starts;
}

function analyze(record, motionStartMs, ratio) {
  const rows = readRows(record.source_path);
  const settled = record.completion_ms;
  const i0 = Math.round(motionStartMs / SAMPLE_MS);
  const i1 = Math.round(settled / SAMPLE_MS);

  // Bias-removed, 50 ms smoothed gyro per axis; the dominant axis has the most energy in the motion.
  const gyro = [4, 5, 6].map(col => {
    const bias = median(rows.map(row => row[col]));
    return movingAverage(rows.map(row => row[col] - bias), 5);
  });
  const energy = gyro.map(axis => axis.slice(i0, i1 + 1).reduce((s, v) => s + v * v, 0));
  const axis = energy.indexOf(Math.max(...energy));
  const g = gyro[axis];

  // The earlier of the largest positive and negative excursions is the outbound lobe, the later one the return.
  let hi = i0;
  let lo = i0;
  for (let i = i0; i <= i1; i += 1) {
    if (g[i] > g[hi]) hi = i;
    if (g[i] < g[lo]) lo = i;
  }
  const outbound = Math.min(hi, lo);
  const ret = Math.max(hi, lo);
  const outSign = Math.sign(g[outbound]);
  let extreme = null;
  for (let i = outbound; i < ret; i += 1) {
    if (Math.sign(g[i]) === outSign && Math.sign(g[i + 1]) !== outSign) extreme = i + 1;
  }

  const returnPeak = Math.abs(g[ret]);
  let r = ret;
  while (r < g.length - 1 && Math.abs(g[r]) > returnPeak * ratio) r += 1;

  const rMs = r * SAMPLE_MS;
  const decisions = [];
  for (let t = FIRST_T; t < rows.length * SAMPLE_MS; t += STRIDE * SAMPLE_MS) decisions.push(t);
  const positiveWindows = decisions.filter(t => t >= rMs && t < rMs + POSITIVE_MS).length;
  const flags = [];
  if (positiveWindows < 3) flags.push('fewer_than_3_positive_windows');
  if (rMs >= settled) flags.push('r_not_before_settled');
  if (extreme === null) flags.push('no_zero_cross');

  return {
    source_path: record.source_path,
    sha256: digest(record.source_path),
    session: record.session,
    direction: record.direction,
    dominant_axis: `gyr${'XYZ'[axis]}`,
    outbound_sign: outSign > 0 ? '+' : '-',
    outbound_peak_ms: outbound * SAMPLE_MS,
    extreme_ms: extreme === null ? null : extreme * SAMPLE_MS,
    return_peak_ms: ret * SAMPLE_MS,
    return_peak_dps: Number(returnPeak.toFixed(1)),
    event_ms: rMs,
    positive_end_ms: rMs + POSITIVE_MS,
    score_start_ms: ret * SAMPLE_MS,
    score_end_ms: rMs + SCORE_AFTER_MS,
    settled_ms: settled,
    positive_windows: positiveWindows,
    flags: flags.join('|'),
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const source = JSON.parse(fs.readFileSync(args.records, 'utf8'));
  const starts = loadMotionStarts(args.candidates);
  const clips = source.records.filter(r => r.completion_ms != null);
  const records = clips.map(r => analyze(r, starts.get(r.source_path), args.ratio));

  const out = {
    version: 'ble-v2-return',
    created_kst: new Date(Date.now() + 9 * 3600e3).toISOString().replace('Z', '+09:00'),
    based_on: args.records,
    based_on_sha256: digest(args.records),
    definition: `event_ms (r): first sample after the return-lobe peak where the dominant gyro axis falls to ${args.ratio} of that peak. `
      + 'Direction label: event_ms <= t < event_ms + 150 ms; everything else NONE (no ignore zone). '
      + 'Scoring: issued in [score_start_ms (return peak), score_end_ms (event_ms + 500 ms)]. '
      + 'settled_ms is the previous completion_ms, kept for reference. Sensor-derived; no video or human check.',
    ratio: args.ratio,
    tool: 'tools/derive-return-labels.js',
    records,
  };
  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  if (fs.existsSync(args.out)) throw new Error(`Refusing to overwrite ${args.out}`);
  fs.writeFileSync(args.out, `${JSON.stringify(out, null, 2)}\n`);

  const lead = records.map(r => r.settled_ms - r.event_ms).sort((a, b) => a - b);
  const q = p => lead[Math.floor((lead.length - 1) * p)];
  const flagged = records.filter(r => r.flags);
  process.stdout.write(`${records.length} clips -> ${args.out}\n`);
  process.stdout.write(`settled - r (ms): min ${lead[0]} median ${q(0.5)} p90 ${q(0.9)} max ${lead.at(-1)}\n`);
  process.stdout.write(`flagged ${flagged.length}${flagged.length ? `: ${flagged.map(r => `${path.basename(r.source_path)}(${r.flags})`).join(', ')}` : ''}\n`);
}

try {
  main();
}
catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
}
