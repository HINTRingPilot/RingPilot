#!/usr/bin/env node

'use strict';

// Reads the imu_capture firmware's serial CSV output ("accX,accY,accZ,gyrX,gyrY,gyrZ")
// and writes local files shaped like the existing Edge Impulse raw_* samples:
// "timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ" with 300 rows at a 10 ms step. See printHelp().

const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');

const SAMPLE_INTERVAL_MS = 10;
const GESTURE_MS = 3000;
const CONTINUOUS_MS = 10000;
const AXES = ['accX', 'accY', 'accZ', 'gyrX', 'gyrY', 'gyrZ'];
const KEY_TO_LABEL = {
  u: { label: 'raw_up', durationMs: GESTURE_MS },
  d: { label: 'raw_down', durationMs: GESTURE_MS },
  l: { label: 'raw_left', durationMs: GESTURE_MS },
  r: { label: 'raw_right', durationMs: GESTURE_MS },
  o: { label: 'other', durationMs: CONTINUOUS_MS },
  i: { label: 'idle', durationMs: CONTINUOUS_MS },
};

function parseArgs(argv) {
  const args = {
    port: process.env.RINGPILOT_PORT || null,
    baud: 115200,
    out: null,
    session: new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19),
  };
  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--port') args.port = argv[++ix];
    else if (arg === '--baud') args.baud = Number(argv[++ix]);
    else if (arg === '--out') args.out = argv[++ix];
    else if (arg === '--session') args.session = argv[++ix];
    else if (arg === '--help' || arg === '-h') args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  if (!args.out) args.out = path.join('data', 'sessions', args.session);
  return args;
}

function printHelp() {
  process.stdout.write([
    'Record RingPilot IMU samples from the imu_capture firmware over serial.',
    '',
    'Usage:',
    '  node tools/record-gesture-samples.js --port COM6 [options]',
    '',
    'Options:',
    '  --port NAME     Serial port (e.g. COM6). Required unless RINGPILOT_PORT is set.',
    '  --baud N        Baud rate (default: 115200)',
    '  --out DIR       Output directory (default: data/sessions/<timestamp>)',
    '  --session NAME  Session id used in the default output path',
    '',
    'Keys once connected: u/d/l/r = 3s direction, o = 10s other, i = 10s idle, q = quit.',
    'Writes local CSV files only; nothing is uploaded to Edge Impulse.',
    '',
  ].join('\n'));
}

async function listPorts(SerialPort) {
  const ports = await SerialPort.list();
  return ports;
}

function toCsv(rows) {
  const lines = [['timestamp', ...AXES].join(',')];
  rows.forEach((row, ix) => {
    lines.push([ix * SAMPLE_INTERVAL_MS, ...row.map(v => v.toFixed(5))].join(','));
  });
  return `${lines.join('\n')}\n`;
}

function nextIndex(dir, label) {
  if (!fs.existsSync(dir)) return 1;
  const existing = fs.readdirSync(dir).filter(f => f.startsWith(`${label}.`) && f.endsWith('.csv'));
  const indices = existing.map(f => Number(f.split('.')[1])).filter(Number.isFinite);
  return (indices.length ? Math.max(...indices) : 0) + 1;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const cliSerialPath = process.env.EDGE_IMPULSE_SERIALPORT || path.join(
    process.env.APPDATA || '', 'npm', 'node_modules', 'edge-impulse-cli', 'node_modules', 'serialport',
  );
  // edge-impulse-cli bundles serialport v8, whose module export is the
  // SerialPort constructor itself (with a static .list()), not a named export.
  const SerialPort = require(cliSerialPath);

  if (!args.port) {
    const ports = await listPorts(SerialPort);
    process.stdout.write('No --port given. Available ports:\n');
    for (const port of ports) {
      process.stdout.write(`  ${port.path}  ${port.manufacturer || ''} ${port.vendorId ? `(VID ${port.vendorId})` : ''}\n`);
    }
    process.stdout.write('\nRe-run with --port COM_X\n');
    return;
  }

  const outDir = path.resolve(args.out);
  fs.mkdirSync(outDir, { recursive: true });

  const port = new SerialPort(args.port, { baudRate: args.baud, autoOpen: false });
  await new Promise((resolve, reject) => port.open(err => (err ? reject(err) : resolve())));
  process.stdout.write(`Connected to ${args.port} @ ${args.baud}. Output: ${path.relative(process.cwd(), outDir)}\n`);

  let buffer = '';
  let recording = null; // { label, durationMs, rows: [] }

  port.on('data', chunk => {
    buffer += chunk.toString('utf8');
    let newlineIx;
    // eslint-disable-next-line no-cond-assign
    while ((newlineIx = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newlineIx).trim();
      buffer = buffer.slice(newlineIx + 1);
      if (!line) continue;
      if (line.startsWith('ERROR')) {
        process.stdout.write(`\n[firmware] ${line}\n`);
        continue;
      }
      const values = line.split(',').map(Number);
      if (values.length !== 6 || values.some(v => !Number.isFinite(v))) continue;
      if (recording) recording.rows.push(values);
    }
  });

  port.on('error', err => {
    process.stderr.write(`Serial error: ${err.message}\n`);
  });

  function startRecording(key) {
    if (recording) {
      process.stdout.write('Already recording, ignoring key.\n');
      return;
    }
    const spec = KEY_TO_LABEL[key];
    const seconds = spec.durationMs / 1000;
    process.stdout.write(`\n[${spec.label}] recording ${seconds}s... `);
    recording = { label: spec.label, durationMs: spec.durationMs, rows: [] };
    setTimeout(() => finishRecording(spec), spec.durationMs);
  }

  function finishRecording(spec) {
    const rec = recording;
    recording = null;
    const expectedRows = spec.durationMs / SAMPLE_INTERVAL_MS;
    const index = nextIndex(outDir, spec.label);
    const filename = `${spec.label}.${index}.csv`;
    fs.writeFileSync(path.join(outDir, filename), toCsv(rec.rows));
    const note = rec.rows.length === 0
      ? ' NO DATA — check the port/firmware.'
      : rec.rows.length < expectedRows * 0.9
        ? ` short (${rec.rows.length}/${expectedRows} rows — check serial throughput).`
        : ` done (${rec.rows.length} rows).`;
    process.stdout.write(`saved ${filename}${note}\n`);
  }

  process.stdout.write('\nKeys: u=up d=down l=left r=right (3s)  o=other i=idle (10s)  q=quit\n');
  readline.emitKeypressEvents(process.stdin);
  if (process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.on('keypress', (str, key) => {
    if (key && key.ctrl && key.name === 'c') {
      process.stdout.write('\nInterrupted.\n');
      port.close(() => process.exit(0));
      return;
    }
    const lowered = (str || '').toLowerCase();
    if (lowered === 'q') {
      process.stdout.write('\nQuitting.\n');
      port.close(() => process.exit(0));
      return;
    }
    if (KEY_TO_LABEL[lowered]) startRecording(lowered);
  });
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
