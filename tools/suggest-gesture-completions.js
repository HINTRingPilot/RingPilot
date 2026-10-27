#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const { median, mean, movingAverage } = require('./lib/signal');

const LABELS = ['raw_up', 'raw_down', 'raw_left', 'raw_right'];
const QUIET_HOLD_MS = 180;
const SAMPLE_INTERVAL_MS = 10;

function parseArgs(argv) {
  const args = { format: 'json', localDir: null, exclude: [], localIdStart: 9000000000 };

  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--format') {
      args.format = argv[++ix];
    }
    else if (arg === '--local-dir') {
      args.localDir = argv[++ix];
    }
    else if (arg === '--exclude') {
      args.exclude = argv[++ix].split(',').map(value => value.trim()).filter(Boolean);
    }
    else if (arg === '--id-start') {
      args.localIdStart = Number(argv[++ix]);
    }
    else if (arg === '--help' || arg === '-h') {
      args.help = true;
    }
    else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!args.help && !args.localDir) {
    throw new Error('--local-dir is required (see --help)');
  }
  if (!['json', 'csv'].includes(args.format)) {
    throw new Error('--format must be json or csv');
  }
  return args;
}

function printHelp() {
  process.stdout.write([
    'Suggest natural-return completion timestamps for RingPilot raw gesture samples.',
    '',
    'Usage (session folder with raw_up/down/left/right.N.csv, as the Android collection app writes):',
    '  node tools/suggest-gesture-completions.js --local-dir data/sessions/phone-<세션> [--format json|csv]',
    '',
    'Options:',
    '  --local-dir PATH   Session folder to read raw_*.csv files from (required)',
    '  --format F         json (default) or csv',
    '  --exclude A,B      Filenames (within --local-dir) to skip, e.g. raw_up.1.csv',
    '  --id-start N       First sample_id (default: 9000000000). Give each session its own range.',
    '',
    'Clip length, cue time and gyro range come from session_info.txt when present;',
    'otherwise 300 rows, 500 ms and ±1000 dps are assumed.',
    '',
  ].join('\n'));
}

function magnitude(values) {
  return Math.hypot(...values);
}

function percentile(values, ratio) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))];
}

function vectorMedian(rows, offset) {
  return [0, 1, 2].map(axis => median(rows.map(row => row[offset + axis])));
}

function vectorMean(rows, start, end, offset) {
  return [0, 1, 2].map(axis => mean(rows.slice(start, end).map(row => row[offset + axis])));
}

function subtract(left, right) {
  return left.map((value, ix) => value - right[ix]);
}

function angleDegrees(left, right) {
  const denominator = magnitude(left) * magnitude(right);
  if (denominator === 0) return 0;
  const cosine = left.reduce((sum, value, ix) => sum + value * right[ix], 0) / denominator;
  return Math.acos(Math.max(-1, Math.min(1, cosine))) * 180 / Math.PI;
}

function findRuns(mask, minimumLength) {
  const runs = [];
  let start = -1;

  for (let ix = 0; ix <= mask.length; ix += 1) {
    if (ix < mask.length && mask[ix]) {
      if (start < 0) start = ix;
    }
    else if (start >= 0) {
      if (ix - start >= minimumLength) runs.push([start, ix - 1]);
      start = -1;
    }
  }
  return runs;
}

function mergeRuns(runs, maximumGap) {
  const merged = [];
  for (const run of runs) {
    const previous = merged[merged.length - 1];
    if (previous && run[0] - previous[1] - 1 <= maximumGap) {
      previous[1] = run[1];
    }
    else {
      merged.push([...run]);
    }
  }
  return merged;
}

function runEnergy(run, energy) {
  return energy.slice(run[0], run[1] + 1).reduce((sum, value) => sum + value, 0);
}

function energyIndex(energy, ratio) {
  const total = energy.reduce((sum, value) => sum + value, 0);
  let cumulative = 0;
  for (let ix = 0; ix < energy.length; ix += 1) {
    cumulative += energy[ix];
    if (cumulative >= total * ratio) return ix;
  }
  return energy.length - 1;
}

function findQuietStart(quietMask, startIndex, holdSamples) {
  for (let start = startIndex; start + holdSamples <= quietMask.length; start += 1) {
    const violations = quietMask.slice(start, start + holdSamples).filter(value => !value).length;
    if (violations <= 1) return start;
  }
  return null;
}

// The phone app writes recording conditions to session_info.txt (4 s clips, 1 s cue,
// ±2000 dps from 2026-10-21). Older sessions without those fields were 3 s clips with
// motion allowed after 0.5 s and a ±1000 dps gyro.
const DEFAULT_RECORDING = { clipSamples: 300, preRollMs: 500, gyroRangeDps: 1000 };

// rows: clipSamples six-axis rows sampled every SAMPLE_INTERVAL_MS (acc x/y/z, gyro x/y/z).
function analyzeSample(label, sample, rows, recording = DEFAULT_RECORDING) {
  const intervalMs = SAMPLE_INTERVAL_MS;
  if (rows.length !== recording.clipSamples
    || rows.some(row => row.length !== 6 || row.some(value => !Number.isFinite(value)))) {
    throw new Error(`${sample.filename}: expected ${recording.clipSamples} finite six-axis rows`);
  }
  const clipMs = rows.length * intervalMs;

  const gyroBias = vectorMedian(rows, 3);
  const gyroMagnitude = rows.map(row => magnitude(subtract(row.slice(3, 6), gyroBias)));
  const smoothGyro = movingAverage(gyroMagnitude, 5);
  const gyroEnergy = gyroMagnitude.map(value => value * value);
  const peakGyro = Math.max(...smoothGyro);
  const activeThreshold = Math.max(12, Math.min(40, peakGyro * 0.08));

  const rawRuns = findRuns(smoothGyro.map(value => value >= activeThreshold), 4);
  const runs = mergeRuns(rawRuns, 35);
  if (runs.length === 0) {
    throw new Error(`${sample.filename}: no gesture-sized motion run found`);
  }

  const rankedRuns = runs
    .map(run => ({ run, energy: runEnergy(run, gyroEnergy) }))
    .sort((left, right) => right.energy - left.energy);
  const mainRun = rankedRuns[0].run;
  const secondaryEnergyRatio = rankedRuns.length > 1
    ? rankedRuns[1].energy / rankedRuns[0].energy
    : 0;
  // Count only samples above the active threshold when taking the 1%/99% energy
  // points. Otherwise the worn-sensor noise of the still head and tail (10-30 dps)
  // adds up with clip length and pulls the start earlier and the end (and so
  // completion) later, e.g. when clips grew from 3 s to 4 s.
  const motionEnergy = gyroEnergy.map((value, ix) => (smoothGyro[ix] >= activeThreshold ? value : 0));
  const energyStart = energyIndex(motionEnergy, 0.01);
  const energyEnd = energyIndex(motionEnergy, 0.99);

  const finalStart = rows.length - 40;
  const finalGyro = vectorMean(rows, finalStart, rows.length, 3);
  const finalAccel = vectorMean(rows, finalStart, rows.length, 0);
  const finalGyroNoise = rows.slice(finalStart).map(row => magnitude(subtract(row.slice(3, 6), finalGyro)));
  const finalAccelNoise = rows.slice(finalStart).map(row => magnitude(subtract(row.slice(0, 3), finalAccel)));
  const quietGyroThreshold = Math.max(10, percentile(finalGyroNoise, 0.95) * 2.5);
  const quietAccelThreshold = Math.max(0.55, percentile(finalAccelNoise, 0.95) * 2.5);
  const settledGyro = movingAverage(
    rows.map(row => magnitude(subtract(row.slice(3, 6), finalGyro))),
    5,
  );
  const settledAccel = movingAverage(
    rows.map(row => magnitude(subtract(row.slice(0, 3), finalAccel))),
    5,
  );
  // A noisy worn tail can loosen quietGyroThreshold to ~50 dps, so also require
  // the gyro to be below the active threshold that defines motion runs.
  const quietMask = settledGyro.map((value, ix) => (
    value <= quietGyroThreshold && smoothGyro[ix] < activeThreshold && settledAccel[ix] <= quietAccelThreshold
  ));
  const holdSamples = Math.round(QUIET_HOLD_MS / intervalMs);
  // A quiet pause at the farthest point is not completion. Search only after
  // 99% of the clip's gyro energy so the return lobe is already behind us.
  const quietStart = findQuietStart(quietMask, energyEnd, holdSamples);
  const completionIndex = quietStart === null
    ? Math.min(rows.length - holdSamples, energyEnd + 1)
    : quietStart;

  const initialAccel = vectorMean(rows, 0, 50, 0);
  const finalAccelMean = vectorMean(rows, rows.length - 50, rows.length, 0);
  const returnAngle = angleDegrees(initialAccel, finalAccelMean);
  const maximumGyro = Math.max(...rows.flatMap(row => row.slice(3, 6).map(value => Math.abs(value))));
  const flags = [];

  if (quietStart === null) flags.push('no_180ms_settle');
  if (energyStart * intervalMs < recording.preRollMs) flags.push('early_motion');
  if (secondaryEnergyRatio >= 0.15) flags.push('second_motion_cluster');
  if (completionIndex * intervalMs >= clipMs - 500) flags.push('late_completion');
  // return_pose_offset (start vs. end gravity angle >= 12 deg) was dropped as
  // an AUTO/REVIEW signal: a gesture's final pose is not required to match
  // its starting pose, so this measured only incidental variation, not a
  // defect in the completion-time estimate. return_angle_deg is still
  // reported for reference.
  if (maximumGyro >= recording.gyroRangeDps * 0.9) flags.push('near_gyro_limit');

  return {
    sample_id: sample.id,
    filename: sample.filename,
    source_path: sample.sourcePath || '',
    direction: label.slice(4).toUpperCase(),
    completion_ms: completionIndex * intervalMs,
    positive_target_end_ms: completionIndex * intervalMs + 150,
    main_motion_start_ms: energyStart * intervalMs,
    main_motion_end_ms: (energyEnd + 1) * intervalMs,
    quiet_hold_ms: QUIET_HOLD_MS,
    return_angle_deg: Number(returnAngle.toFixed(1)),
    peak_gyro_dps: Number(maximumGyro.toFixed(1)),
    status: flags.length === 0 ? 'AUTO' : 'REVIEW',
    flags: flags.join('|'),
  };
}

function csvEscape(value) {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function formatCsv(annotations) {
  const columns = [
    'sample_id',
    'filename',
    'source_path',
    'direction',
    'completion_ms',
    'positive_target_end_ms',
    'main_motion_start_ms',
    'main_motion_end_ms',
    'quiet_hold_ms',
    'return_angle_deg',
    'peak_gyro_dps',
    'status',
    'flags',
  ];
  return [
    columns.join(','),
    ...annotations.map(row => columns.map(column => csvEscape(row[column])).join(',')),
  ].join('\n');
}

function loadLocalCsv(filePath, clipSamples) {
  const lines = fs.readFileSync(filePath, 'utf8').trim().split(/\r?\n/);
  const rows = lines.slice(1).map(line => line.split(',').slice(1).map(Number));
  // The old USB recorder timed recordings with setTimeout, so row counts
  // land at 300-304 instead of exactly 300. Trim that small serial-timing excess
  // so every clip in a session has the same length.
  if (rows.length < clipSamples) throw new Error(`${filePath}: only ${rows.length} rows, expected at least ${clipSamples}`);
  return rows.slice(0, clipSamples);
}

// Phone sessions record their clip length, cue time and gyro range in
// session_info.txt; older USB sessions have none and use the 3 s defaults.
function readRecording(localDir) {
  const infoPath = path.join(localDir, 'session_info.txt');
  if (!fs.existsSync(infoPath)) return DEFAULT_RECORDING;
  const info = fs.readFileSync(infoPath, 'utf8');
  const field = (name, fallback) => {
    const match = info.match(new RegExp(`(?:^|\\s)${name}=(\\d+)`, 'm'));
    return match ? Number(match[1]) : fallback;
  };
  return {
    clipSamples: field('gesture_samples', DEFAULT_RECORDING.clipSamples),
    preRollMs: field('pre_roll_cue_ms', DEFAULT_RECORDING.preRollMs),
    gyroRangeDps: field('gyro_range_dps', DEFAULT_RECORDING.gyroRangeDps),
  };
}

function analyzeLocalDir(localDir, exclude, idStart) {
  const excludeSet = new Set(exclude);
  const annotations = [];
  const recording = readRecording(localDir);
  let nextId = idStart;

  for (const label of LABELS) {
    const files = fs.readdirSync(localDir)
      .filter(name => name.startsWith(`${label}.`) && name.endsWith('.csv'))
      .filter(name => !excludeSet.has(name))
      .sort((left, right) => Number(left.split('.')[1]) - Number(right.split('.')[1]));

    for (const filename of files) {
      const fullPath = path.join(localDir, filename);
      const rows = loadLocalCsv(fullPath, recording.clipSamples);
      const sample = { id: nextId, filename, sourcePath: path.relative(process.cwd(), fullPath).replaceAll('\\', '/') };
      nextId += 1;
      annotations.push(analyzeSample(label, sample, rows, recording));
    }
  }
  return annotations;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const annotations = analyzeLocalDir(path.resolve(args.localDir), args.exclude, args.localIdStart);
  if (args.format === 'csv') {
    process.stdout.write(`${formatCsv(annotations)}\n`);
  }
  else {
    const review = annotations.filter(row => row.status === 'REVIEW');
    process.stdout.write(`${JSON.stringify({
      local_dir: path.relative(process.cwd(), path.resolve(args.localDir)).replaceAll('\\', '/'),
      excluded: args.exclude,
      definition: 'Natural return complete, followed by 180 ms of settled IMU data',
      target_width_ms: 150,
      sample_count: annotations.length,
      auto_count: annotations.length - review.length,
      review_count: review.length,
      annotations,
    }, null, 2)}\n`);
  }
}

try {
  main();
}
catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
}
