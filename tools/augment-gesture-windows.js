#!/usr/bin/env node

'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const WINDOW_SAMPLES = 160; // 1600 ms at 10 ms steps
const AUGMENT_FACTOR = 5; // original + 4 variants, training only; testing stays 1x
const ROTATION_MAX_DEGREES = 5;
const NOISE_STD_ACC_MS2 = 0.02;
const NOISE_STD_GYRO_DPS = 0.2;
const NOISE_CLIP_SIGMA = 3;
const SEED = 20261006;

function parseArgs(argv) {
  const args = {
    input: path.join('data', 'windows'),
    output: path.join('data', 'windows-augmented-5x'),
  };

  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--help' || arg === '-h') args.help = true;
    else if (arg.startsWith('--')) throw new Error(`Unknown argument: ${arg}`);
    else args.output = arg; // positional output path, kept for backward compatibility
  }
  return args;
}

function printHelp() {
  process.stdout.write([
    'Augment RingPilot training windows with small rigid rotations and sensor noise.',
    '',
    'Usage:',
    '  node tools/augment-gesture-windows.js [output-dir]',
    '',
    `Fixed-time augmentation: labels and completion times stay unchanged. Reads`,
    `data/windows/manifest.csv and writes ${AUGMENT_FACTOR}x training windows (the`,
    `original plus ${AUGMENT_FACTOR - 1} variants); testing windows are copied`,
    'byte-identical to the input. Refuses to run if the output directory already exists.',
    '',
  ].join('\n'));
}

function rng(key) {
  let state = crypto.createHash('sha256').update(`${SEED}:${key}`).digest().readUInt32LE();
  return () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0;
    return (state + 0.5) / 4294967296;
  };
}

function normal(random) {
  return Math.sqrt(-2 * Math.log(random())) * Math.cos(2 * Math.PI * random());
}

function rotate(v, axis, angle) {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const dot = v.reduce((sum, value, ix) => sum + value * axis[ix], 0);
  const cross = [
    axis[1] * v[2] - axis[2] * v[1],
    axis[2] * v[0] - axis[0] * v[2],
    axis[0] * v[1] - axis[1] * v[0],
  ];
  return v.map((value, ix) => value * c + cross[ix] * s + axis[ix] * dot * (1 - c));
}

function clampedNormal(random) {
  return Math.max(-NOISE_CLIP_SIGMA, Math.min(NOISE_CLIP_SIGMA, normal(random)));
}

function readManifest(inputDir) {
  const lines = fs.readFileSync(path.join(inputDir, 'manifest.csv'), 'utf8').trim().split(/\r?\n/);
  const keys = lines.shift().split(',');
  const records = lines.map(line => Object.fromEntries(line.split(',').map((value, ix) => [keys[ix], value])));

  // One source sample must land entirely in training or entirely in testing.
  const categoryBySample = new Map();
  for (const record of records) {
    if (!['training', 'testing'].includes(record.category)) throw new Error('Unexpected category');
    if (categoryBySample.has(record.sample_id) && categoryBySample.get(record.sample_id) !== record.category) {
      throw new Error('Source split leakage');
    }
    categoryBySample.set(record.sample_id, record.category);
  }
  return records;
}

function loadWindowCsv(filePath) {
  const text = fs.readFileSync(filePath, 'utf8');
  const lines = text.trim().split(/\r?\n/);
  const header = lines.shift();
  const rows = lines.map(line => line.split(',').map(Number));
  const valid = rows.length === WINDOW_SAMPLES
    && rows.every((row, ix) => row.length === 7 && row[0] === ix * 10 && row.every(value => Number.isFinite(value)));
  if (!valid) throw new Error(`Invalid input window: ${filePath}`);
  return { header, rows, bytes: Buffer.from(text) };
}

function makeVariant(record, header, rows, variant) {
  const random = rng(`${record.sample_id}:${variant}`);
  const rawAxis = [normal(random), normal(random), normal(random)];
  const length = Math.hypot(...rawAxis);
  const axis = rawAxis.map(value => value / length);
  const angle = (random() * 2 - 1) * ROTATION_MAX_DEGREES * Math.PI / 180;

  const lines = rows.map(row => {
    const absoluteMs = Number(record.window_end_ms) - WINDOW_SAMPLES * 10 + row[0];
    // Overlapping windows from the same recording share noise at the same
    // absolute timestamp, since that timestamp is physically one moment.
    const noise = rng(`${record.sample_id}:${variant}:${absoluteMs}`);
    const acc = rotate(row.slice(1, 4), axis, angle);
    const gyro = rotate(row.slice(4, 7), axis, angle);
    return [
      row[0],
      ...acc.map(value => (value + clampedNormal(noise) * NOISE_STD_ACC_MS2).toFixed(6)),
      ...gyro.map(value => (value + clampedNormal(noise) * NOISE_STD_GYRO_DPS).toFixed(6)),
    ].join(',');
  });
  return Buffer.from([header, ...lines, ''].join('\n'));
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const input = path.resolve(args.input);
  const output = path.resolve(args.output);
  if (fs.existsSync(output)) throw new Error(`Output already exists: ${output}`);

  const records = readManifest(input);
  const manifest = ['file,category,label,sample_id,source,window_end_ms,parent_file,variant'];
  const counts = {};

  for (const record of records) {
    const sourcePath = path.resolve(input, record.file);
    if (!sourcePath.startsWith(input + path.sep)) throw new Error('Invalid input path');
    const { header, rows, bytes } = loadWindowCsv(sourcePath);
    const variantCount = record.category === 'training' ? AUGMENT_FACTOR : 1;

    for (let variant = 0; variant < variantCount; variant += 1) {
      const file = variant === 0 ? record.file : record.file.replace(/\.csv$/, `.aug${variant}.csv`);
      const content = variant === 0 ? bytes : makeVariant(record, header, rows, variant);

      fs.mkdirSync(path.dirname(path.join(output, file)), { recursive: true });
      fs.writeFileSync(path.join(output, file), content);
      manifest.push([file, record.category, record.label, record.sample_id, record.source, record.window_end_ms, record.file, variant].join(','));
      const key = `${record.category}/${record.label}`;
      counts[key] = (counts[key] || 0) + 1;
    }
  }

  fs.writeFileSync(path.join(output, 'manifest.csv'), `${manifest.join('\n')}\n`);
  const summary = {
    seed: SEED,
    input: path.relative(process.cwd(), input).replaceAll('\\', '/'),
    factor_including_original: AUGMENT_FACTOR,
    rotation_max_degrees: ROTATION_MAX_DEGREES,
    noise_std: { acc_m_s2: NOISE_STD_ACC_MS2, gyro_deg_s: NOISE_STD_GYRO_DPS },
    noise_clip_sigma: NOISE_CLIP_SIGMA,
    counts,
    note: 'Exploratory strengths, not calibrated sensor noise. Training only. Original/test bytes preserved. Source IDs retained for grouped validation.',
  };
  fs.writeFileSync(path.join(output, 'augmentation.json'), `${JSON.stringify(summary, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

try {
  main();
}
catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
}
