#!/usr/bin/env node

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const SAMPLE_INTERVAL_MS = 10;
const STRIDE_MS = 50;
const AXES = ['accX', 'accY', 'accZ', 'gyrX', 'gyrY', 'gyrZ'];
const CONTINUOUS_LABELS = ['idle', 'other'];

function parseArgs(argv) {
  const args = {
    projectId: 1122630,
    annotations: [path.join('data', 'annotations', 'gesture-completions.csv')],
    out: path.join('data', 'windows'),
    windowMs: 1600,
    continuousStrideMs: 200,
    testFraction: 0.2,
    seed: 20260928,
    includeReview: false,
    maxNoneTraining: 30,
  };

  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--project-id') args.projectId = Number(argv[++ix]);
    else if (arg === '--annotations') args.annotations = argv[++ix].split(',').map(value => value.trim());
    else if (arg === '--out') args.out = argv[++ix];
    else if (arg === '--window-ms') args.windowMs = Number(argv[++ix]);
    else if (arg === '--continuous-stride-ms') args.continuousStrideMs = Number(argv[++ix]);
    else if (arg === '--test-fraction') args.testFraction = Number(argv[++ix]);
    else if (arg === '--seed') args.seed = Number(argv[++ix]);
    else if (arg === '--max-none-training') args.maxNoneTraining = Number(argv[++ix]);
    else if (arg === '--include-review') args.includeReview = true;
    else if (arg === '--help' || arg === '-h') args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  if (!Number.isInteger(args.projectId) || args.projectId <= 0) throw new Error('--project-id must be a positive integer');
  if (!Number.isInteger(args.windowMs) || args.windowMs % STRIDE_MS !== 0) {
    throw new Error(`--window-ms must be a multiple of ${STRIDE_MS}`);
  }
  if (!Number.isInteger(args.continuousStrideMs) || args.continuousStrideMs % STRIDE_MS !== 0) {
    throw new Error(`--continuous-stride-ms must be a multiple of ${STRIDE_MS}`);
  }
  if (!(args.testFraction > 0 && args.testFraction < 1)) throw new Error('--test-fraction must be between 0 and 1');
  return args;
}

function printHelp() {
  process.stdout.write([
    'Cut RingPilot raw samples into labeled causal windows as local Edge Impulse CSV files.',
    '',
    'Usage:',
    '  node tools/export-gesture-windows.js [options]',
    '',
    'Options:',
    '  --project-id N              Edge Impulse project ID (default: 1122630)',
    '  --annotations PATH[,PATH2]  Completion CSV path(s); rows with a source_path column',
    '                               are read from that local file instead of Edge Impulse',
    '  --out DIR                   Output directory (default: data/windows)',
    '  --window-ms N               Window length in ms (default: 1600)',
    '  --continuous-stride-ms N    Stride for idle/other windows (default: 200)',
    '  --test-fraction F           Share of source samples per label kept for testing (default: 0.2)',
    '  --seed N                    Split seed',
    '  --max-none-training N       NONE windows kept in training; testing keeps N * test-fraction (default: 30)',
    '  --include-review           Also export REVIEW samples (category "review", never uploaded by default)',
    '',
    'Remote samples are read only. Nothing is uploaded; the output directory holds',
    'training/ and testing/ CSV files plus manifest.csv.',
    '',
  ].join('\n'));
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const columns = lines[0].split(',');
  return lines.slice(1).map(line => {
    const values = line.split(',');
    return Object.fromEntries(columns.map((column, ix) => [column, values[ix] || '']));
  });
}

function makeRng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function shuffle(values, random) {
  for (let ix = values.length - 1; ix > 0; ix -= 1) {
    const swap = Math.floor(random() * (ix + 1));
    [values[ix], values[swap]] = [values[swap], values[ix]];
  }
}

// Within each label, hold out ceil(n * fraction) whole source samples so windows
// from one recording never land on both sides of the split.
function assignCategories(records, testFraction, seed) {
  const byLabel = new Map();
  for (const record of records) {
    if (!byLabel.has(record.groupLabel)) byLabel.set(record.groupLabel, []);
    byLabel.get(record.groupLabel).push(record);
  }
  const random = makeRng(seed);
  for (const group of byLabel.values()) {
    const ordered = [...group].sort((a, b) => a.sampleId - b.sampleId);
    shuffle(ordered, random);
    const testCount = Math.max(1, Math.round(ordered.length * testFraction));
    ordered.forEach((record, ix) => {
      record.category = ix < testCount ? 'testing' : 'training';
    });
  }
}

function windowLabel(record, endMs) {
  if (record.kind === 'gesture' && endMs >= record.completionMs && endMs < record.positiveEndMs) {
    return record.direction;
  }
  return 'NONE';
}

function makeWindows(record, windowMs, continuousStrideMs) {
  const windowSamples = windowMs / SAMPLE_INTERVAL_MS;
  const strideMs = record.kind === 'gesture' ? STRIDE_MS : continuousStrideMs;
  const strideSamples = strideMs / SAMPLE_INTERVAL_MS;
  const windows = [];
  for (let end = windowSamples; end <= record.rows.length; end += strideSamples) {
    const endMs = end * SAMPLE_INTERVAL_MS;
    windows.push({ record, endMs, label: windowLabel(record, endMs), rows: record.rows.slice(end - windowSamples, end) });
  }
  return windows;
}

function toCsv(rows) {
  const lines = [['timestamp', ...AXES].join(',')];
  rows.forEach((row, ix) => {
    lines.push([ix * SAMPLE_INTERVAL_MS, ...row.map(value => Number(value.toFixed(6)))].join(','));
  });
  return `${lines.join('\n')}\n`;
}

async function fetchRows(api, projectId, sampleId, filename) {
  const response = await api.rawData.getSample(projectId, sampleId, {});
  if (!response.success) throw new Error(`Failed to read ${filename}`);
  const rows = response.payload.values;
  if (rows.some(row => row.length !== 6 || row.some(value => !Number.isFinite(value)))) {
    throw new Error(`${filename}: invalid six-axis payload`);
  }
  return rows;
}

function loadLocalRows(sourcePath) {
  const lines = fs.readFileSync(path.resolve(sourcePath), 'utf8').trim().split(/\r?\n/);
  const rows = lines.slice(1).map(line => line.split(',').slice(1).map(Number));
  if (rows.some(row => row.length !== 6 || row.some(value => !Number.isFinite(value)))) {
    throw new Error(`${sourcePath}: invalid six-axis payload`);
  }
  return rows;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const annotations = args.annotations.flatMap(annotationPath => parseCsv(fs.readFileSync(path.resolve(annotationPath), 'utf8')).map(row => ({
    sampleId: Number(row.sample_id),
    filename: row.filename,
    sourcePath: row.source_path || '',
    direction: row.direction,
    completionMs: Number(row.completion_ms),
    positiveEndMs: Number(row.positive_target_end_ms),
    status: row.status,
  })));

  const cliApiPath = process.env.EDGE_IMPULSE_CLI_API || path.join(
    process.env.APPDATA || '', 'npm', 'node_modules', 'edge-impulse-cli', 'build', 'sdk', 'studio', 'api.js',
  );
  const configPath = process.env.EDGE_IMPULSE_CONFIG || path.join(os.homedir(), 'edge-impulse-config.json');
  const { EdgeImpulseApi } = require(cliApiPath);
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  if (!config.jwtToken) throw new Error('Edge Impulse CLI config has no JWT token');
  const api = new EdgeImpulseApi({ endpoint: 'https://studio.edgeimpulse.com' });
  await api.authenticate({ method: 'jwtToken', jwtToken: config.jwtToken });

  const records = [];
  for (const annotation of annotations) {
    if (annotation.status === 'REVIEW' && !args.includeReview) continue;
    const rows = annotation.sourcePath
      ? loadLocalRows(annotation.sourcePath)
      : await fetchRows(api, args.projectId, annotation.sampleId, annotation.filename);
    records.push({
      ...annotation,
      kind: 'gesture',
      groupLabel: annotation.status === 'REVIEW' ? `review_${annotation.direction}` : annotation.direction,
      rows,
    });
  }

  const listed = await api.rawData.listSamples(args.projectId, { category: 'training' });
  for (const sample of listed.samples) {
    if (!CONTINUOUS_LABELS.includes(sample.label)) continue;
    records.push({
      sampleId: sample.id,
      filename: sample.filename,
      kind: 'continuous',
      groupLabel: sample.label,
      source: sample.label,
      rows: await fetchRows(api, args.projectId, sample.id, sample.filename),
    });
  }

  assignCategories(records, args.testFraction, args.seed);
  for (const record of records) {
    if (record.groupLabel.startsWith('review_')) record.category = 'review';
  }

  const outDir = path.resolve(args.out);
  if (path.basename(outDir) === 'windows') fs.rmSync(outDir, { recursive: true, force: true });
  const manifest = [['file', 'category', 'label', 'sample_id', 'source', 'window_end_ms'].join(',')];
  const counts = {};
  const context = { skippedShort: 0 };

  const selected = [];
  for (const record of records) {
    const windows = makeWindows(record, args.windowMs, args.continuousStrideMs);
    if (windows.length === 0) context.skippedShort += 1;
    selected.push(...windows.filter(window => window.label !== 'NONE'));
  }
  const noneCaps = {
    training: args.maxNoneTraining,
    testing: Math.max(1, Math.round(args.maxNoneTraining * args.testFraction)),
  };
  const random = makeRng(args.seed + 1);
  for (const category of ['training', 'testing', 'review']) {
    const pools = records
      .filter(record => record.category === category)
      .map(record => {
        const none = makeWindows(record, args.windowMs, args.continuousStrideMs).filter(window => window.label === 'NONE');
        shuffle(none, random);
        return none;
      });
    // Round-robin across source samples so NONE covers every recording instead of one long clip.
    const cap = noneCaps[category] ?? Infinity;
    let taken = 0;
    for (let round = 0; taken < cap; round += 1) {
      let any = false;
      for (const pool of pools) {
        if (round < pool.length && taken < cap) {
          selected.push(pool[round]);
          taken += 1;
          any = true;
        }
      }
      if (!any) break;
    }
  }

  {
    for (const window of selected) {
      const record = window.record;
      const dir = path.join(outDir, record.category);
      fs.mkdirSync(dir, { recursive: true });
      const source = record.source || record.direction;
      const file = `${window.label}.s${record.sampleId}.e${window.endMs}.csv`;
      fs.writeFileSync(path.join(dir, file), toCsv(window.rows));
      manifest.push([`${record.category}/${file}`, record.category, window.label, record.sampleId, source, window.endMs].join(','));
      const key = `${record.category}/${window.label}`;
      counts[key] = (counts[key] || 0) + 1;
    }
  }
  fs.writeFileSync(path.join(outDir, 'manifest.csv'), `${manifest.join('\n')}\n`);

  const sources = {};
  for (const record of records) {
    const key = `${record.category}/${record.groupLabel}`;
    sources[key] = (sources[key] || 0) + 1;
  }
  process.stdout.write(`${JSON.stringify({
    out: path.relative(process.cwd(), outDir).replaceAll('\\', '/'),
    window_ms: args.windowMs,
    positive_target_ms: 150,
    source_samples: sources,
    windows: Object.fromEntries(Object.entries(counts).sort()),
    sources_without_window: context.skippedShort,
  }, null, 2)}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
