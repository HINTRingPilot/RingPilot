#!/usr/bin/env node

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const CLASS_NAMES = ['NONE', 'UP', 'DOWN', 'LEFT', 'RIGHT'];
const DEFAULT_LENGTHS_MS = [800, 1200, 1600];
const STRIDE_MS = 50;
const SAMPLE_INTERVAL_MS = 10;
const FEATURE_BINS = 10;
const FOLDS = 5;
const EPOCHS = 80;

function parseArgs(argv) {
  const args = {
    projectId: 1122630,
    annotations: path.join('data', 'annotations', 'gesture-completions.csv'),
    lengths: DEFAULT_LENGTHS_MS,
    folds: FOLDS,
    epochs: EPOCHS,
  };

  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--project-id') args.projectId = Number(argv[++ix]);
    else if (arg === '--annotations') args.annotations = argv[++ix];
    else if (arg === '--lengths') args.lengths = argv[++ix].split(',').map(Number);
    else if (arg === '--folds') args.folds = Number(argv[++ix]);
    else if (arg === '--epochs') args.epochs = Number(argv[++ix]);
    else if (arg === '--help' || arg === '-h') args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  if (!Number.isInteger(args.projectId) || args.projectId <= 0) {
    throw new Error('--project-id must be a positive integer');
  }
  if (!args.lengths.every(value => Number.isInteger(value) && value > 0 && value % STRIDE_MS === 0)) {
    throw new Error(`Every window length must be a positive multiple of ${STRIDE_MS} ms`);
  }
  if (!Number.isInteger(args.folds) || args.folds < 2) throw new Error('--folds must be at least 2');
  if (!Number.isInteger(args.epochs) || args.epochs < 1) throw new Error('--epochs must be positive');
  return args;
}

function printHelp() {
  process.stdout.write([
    'Compare causal window lengths on RingPilot completion-time annotations.',
    '',
    'Usage:',
    '  node tools/compare-window-lengths.js [options]',
    '',
    'Options:',
    '  --project-id N          Edge Impulse project ID (default: 1122630)',
    '  --annotations PATH      Completion CSV path',
    '  --lengths A,B,C         Window lengths in ms (default: 800,1200,1600)',
    '  --folds N               Grouped stratified folds (default: 5)',
    '  --epochs N              Softmax baseline epochs (default: 80)',
    '',
    'Remote samples are read only. REVIEW rows are excluded from training and',
    'cross-validation, then evaluated separately as a stress set.',
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

function classIndex(name) {
  const ix = CLASS_NAMES.indexOf(name);
  if (ix < 0) throw new Error(`Unknown class: ${name}`);
  return ix;
}

function makeFeatures(rows, start, end, bins = FEATURE_BINS) {
  const scales = [9.80665, 9.80665, 9.80665, 500, 500, 500];
  const features = [];
  const length = end - start;

  for (let bin = 0; bin < bins; bin += 1) {
    const binStart = start + Math.floor(length * bin / bins);
    const binEnd = start + Math.floor(length * (bin + 1) / bins);
    const count = Math.max(1, binEnd - binStart);

    for (let axis = 0; axis < 6; axis += 1) {
      let sum = 0;
      let squareSum = 0;
      for (let ix = binStart; ix < binEnd; ix += 1) {
        const value = rows[ix][axis] / scales[axis];
        sum += value;
        squareSum += value * value;
      }
      const average = sum / count;
      const variance = Math.max(0, squareSum / count - average * average);
      features.push(average, Math.sqrt(variance));
    }
  }

  for (let axis = 0; axis < 6; axis += 1) {
    features.push((rows[end - 1][axis] - rows[start][axis]) / scales[axis]);
  }
  return Float64Array.from(features);
}

function makeWindows(record, windowMs) {
  const windowSamples = windowMs / SAMPLE_INTERVAL_MS;
  const strideSamples = STRIDE_MS / SAMPLE_INTERVAL_MS;
  const windows = [];

  for (let end = windowSamples; end <= record.rows.length; end += strideSamples) {
    const endMs = end * SAMPLE_INTERVAL_MS;
    const target = endMs >= record.completionMs && endMs < record.positiveEndMs
      ? record.direction
      : 'NONE';
    windows.push({
      sampleId: record.sampleId,
      filename: record.filename,
      direction: record.direction,
      completionMs: record.completionMs,
      positiveEndMs: record.positiveEndMs,
      endMs,
      target: classIndex(target),
      features: makeFeatures(record.rows, end - windowSamples, end),
    });
  }
  return windows;
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

function selectTrainingWindows(windows) {
  const bySample = new Map();
  for (const window of windows) {
    if (!bySample.has(window.sampleId)) bySample.set(window.sampleId, []);
    bySample.get(window.sampleId).push(window);
  }

  const selected = [];
  for (const sampleWindows of bySample.values()) {
    const none = sampleWindows.filter(window => window.target === 0);
    const positive = sampleWindows.filter(window => window.target !== 0);
    selected.push(...positive);

    for (let ix = 0; ix < none.length; ix += 1) {
      const window = none[ix];
      const nearBefore = window.endMs >= window.completionMs - 250 && window.endMs < window.completionMs;
      const nearAfter = window.endMs >= window.positiveEndMs && window.endMs <= window.positiveEndMs + 250;
      if (ix % 4 === 0 || nearBefore || nearAfter) selected.push(window);
    }
  }
  return selected;
}

function fitStandardizer(windows) {
  const size = windows[0].features.length;
  const means = new Float64Array(size);
  const deviations = new Float64Array(size);

  for (const window of windows) {
    for (let ix = 0; ix < size; ix += 1) means[ix] += window.features[ix];
  }
  for (let ix = 0; ix < size; ix += 1) means[ix] /= windows.length;
  for (const window of windows) {
    for (let ix = 0; ix < size; ix += 1) {
      const delta = window.features[ix] - means[ix];
      deviations[ix] += delta * delta;
    }
  }
  for (let ix = 0; ix < size; ix += 1) {
    deviations[ix] = Math.max(1e-5, Math.sqrt(deviations[ix] / windows.length));
  }
  return { means, deviations };
}

function standardize(features, standardizer) {
  const output = new Float64Array(features.length);
  for (let ix = 0; ix < features.length; ix += 1) {
    output[ix] = (features[ix] - standardizer.means[ix]) / standardizer.deviations[ix];
  }
  return output;
}

function softmax(logits) {
  const maximum = Math.max(...logits);
  const exponentials = logits.map(value => Math.exp(value - maximum));
  const total = exponentials.reduce((sum, value) => sum + value, 0);
  return exponentials.map(value => value / total);
}

function trainModel(windows, epochs, seed) {
  const training = selectTrainingWindows(windows);
  const standardizer = fitStandardizer(training);
  const examples = training.map(window => ({
    x: standardize(window.features, standardizer),
    y: window.target,
  }));
  const featureCount = examples[0].x.length;
  const parameterCount = CLASS_NAMES.length * (featureCount + 1);
  const weights = new Float64Array(CLASS_NAMES.length * featureCount);
  const biases = new Float64Array(CLASS_NAMES.length);
  const moment1 = new Float64Array(parameterCount);
  const moment2 = new Float64Array(parameterCount);
  const classCounts = new Array(CLASS_NAMES.length).fill(0);
  for (const example of examples) classCounts[example.y] += 1;
  const classWeights = classCounts.map(count => examples.length / (CLASS_NAMES.length * Math.max(1, count)));
  const random = makeRng(seed);
  const indices = examples.map((_, ix) => ix);
  const batchSize = 32;
  let update = 0;

  for (let epoch = 0; epoch < epochs; epoch += 1) {
    shuffle(indices, random);
    const learningRate = 0.012 / (1 + epoch * 0.025);

    for (let batchStart = 0; batchStart < indices.length; batchStart += batchSize) {
      const batch = indices.slice(batchStart, batchStart + batchSize);
      const gradients = new Float64Array(parameterCount);

      for (const exampleIx of batch) {
        const example = examples[exampleIx];
        const logits = new Array(CLASS_NAMES.length).fill(0);
        for (let cls = 0; cls < CLASS_NAMES.length; cls += 1) {
          let value = biases[cls];
          const offset = cls * featureCount;
          for (let feature = 0; feature < featureCount; feature += 1) {
            value += weights[offset + feature] * example.x[feature];
          }
          logits[cls] = value;
        }
        const probabilities = softmax(logits);
        const exampleWeight = classWeights[example.y];
        for (let cls = 0; cls < CLASS_NAMES.length; cls += 1) {
          const error = exampleWeight * (probabilities[cls] - (cls === example.y ? 1 : 0));
          const offset = cls * featureCount;
          for (let feature = 0; feature < featureCount; feature += 1) {
            gradients[offset + feature] += error * example.x[feature];
          }
          gradients[CLASS_NAMES.length * featureCount + cls] += error;
        }
      }

      update += 1;
      const correction1 = 1 - Math.pow(0.9, update);
      const correction2 = 1 - Math.pow(0.999, update);
      for (let ix = 0; ix < parameterCount; ix += 1) {
        let gradient = gradients[ix] / batch.length;
        if (ix < weights.length) gradient += 0.0002 * weights[ix];
        moment1[ix] = 0.9 * moment1[ix] + 0.1 * gradient;
        moment2[ix] = 0.999 * moment2[ix] + 0.001 * gradient * gradient;
        const step = learningRate * (moment1[ix] / correction1) / (Math.sqrt(moment2[ix] / correction2) + 1e-8);
        if (ix < weights.length) weights[ix] -= step;
        else biases[ix - weights.length] -= step;
      }
    }
  }

  return { weights, biases, featureCount, standardizer, trainingWindowCount: examples.length };
}

function predict(model, features) {
  const x = standardize(features, model.standardizer);
  const logits = new Array(CLASS_NAMES.length).fill(0);
  for (let cls = 0; cls < CLASS_NAMES.length; cls += 1) {
    let value = model.biases[cls];
    const offset = cls * model.featureCount;
    for (let feature = 0; feature < model.featureCount; feature += 1) {
      value += model.weights[offset + feature] * x[feature];
    }
    logits[cls] = value;
  }
  const probabilities = softmax(logits);
  let best = 0;
  for (let cls = 1; cls < probabilities.length; cls += 1) {
    if (probabilities[cls] > probabilities[best]) best = cls;
  }
  return { classIndex: best, probabilities };
}

function makeEvents(predictions) {
  const events = [];
  let armed = true;
  let candidate = 0;
  let candidateCount = 0;
  let noneCount = 0;

  for (const prediction of predictions) {
    const current = prediction.predicted;
    if (current === 0) {
      candidate = 0;
      candidateCount = 0;
      noneCount += 1;
      if (noneCount >= 2) armed = true;
      continue;
    }

    noneCount = 0;
    if (!armed) continue;
    if (candidate === current) candidateCount += 1;
    else {
      candidate = current;
      candidateCount = 1;
    }
    if (candidateCount >= 2) {
      events.push({ direction: CLASS_NAMES[current], timeMs: prediction.endMs });
      armed = false;
      candidate = 0;
      candidateCount = 0;
    }
  }
  return events;
}

function emptyConfusion() {
  return CLASS_NAMES.map(() => new Array(CLASS_NAMES.length).fill(0));
}

function mergeConfusion(target, source) {
  for (let row = 0; row < target.length; row += 1) {
    for (let column = 0; column < target[row].length; column += 1) {
      target[row][column] += source[row][column];
    }
  }
}

function percentileSorted(values, ratio) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * ratio))];
}

function evaluate(model, windows) {
  const confusion = emptyConfusion();
  const bySample = new Map();

  for (const window of windows) {
    const result = predict(model, window.features);
    confusion[window.target][result.classIndex] += 1;
    if (!bySample.has(window.sampleId)) bySample.set(window.sampleId, []);
    bySample.get(window.sampleId).push({
      ...window,
      predicted: result.classIndex,
    });
  }

  let correctEvents = 0;
  let missedEvents = 0;
  let wrongDirectionEvents = 0;
  let falseEvents = 0;
  let duplicateEvents = 0;
  const delays = [];
  const clipDetails = [];

  for (const sampleWindows of bySample.values()) {
    sampleWindows.sort((left, right) => left.endMs - right.endMs);
    const sample = sampleWindows[0];
    const events = makeEvents(sampleWindows);
    const matchEnd = sample.positiveEndMs + STRIDE_MS;
    const inTarget = events.filter(event => event.timeMs >= sample.completionMs && event.timeMs <= matchEnd);
    const correct = inTarget.filter(event => event.direction === sample.direction);
    const wrong = inTarget.filter(event => event.direction !== sample.direction);
    const outside = events.filter(event => event.timeMs < sample.completionMs || event.timeMs > matchEnd);

    if (correct.length > 0) {
      correctEvents += 1;
      delays.push(correct[0].timeMs - sample.completionMs);
      duplicateEvents += Math.max(0, correct.length - 1);
    }
    else {
      missedEvents += 1;
    }
    if (wrong.length > 0) wrongDirectionEvents += 1;
    falseEvents += outside.length;
    clipDetails.push({
      filename: sample.filename,
      expected: sample.direction,
      completion_ms: sample.completionMs,
      events,
      matched: correct.length > 0,
    });
  }

  let directionTruePositive = 0;
  let directionFalseNegative = 0;
  let noneFalsePositive = 0;
  let noneTotal = 0;
  const perClassF1 = {};
  for (let cls = 0; cls < CLASS_NAMES.length; cls += 1) {
    const tp = confusion[cls][cls];
    const fp = confusion.reduce((sum, row, rowIx) => sum + (rowIx === cls ? 0 : row[cls]), 0);
    const fn = confusion[cls].reduce((sum, value, columnIx) => sum + (columnIx === cls ? 0 : value), 0);
    const precision = tp + fp === 0 ? 0 : tp / (tp + fp);
    const recall = tp + fn === 0 ? 0 : tp / (tp + fn);
    perClassF1[CLASS_NAMES[cls]] = precision + recall === 0 ? 0 : 2 * precision * recall / (precision + recall);
    if (cls !== 0) {
      directionTruePositive += tp;
      directionFalseNegative += fn;
    }
  }
  noneTotal = confusion[0].reduce((sum, value) => sum + value, 0);
  noneFalsePositive = noneTotal - confusion[0][0];

  const directionF1 = CLASS_NAMES.slice(1).map(name => perClassF1[name]);
  return {
    clip_count: bySample.size,
    event_recall: bySample.size === 0 ? null : correctEvents / bySample.size,
    correct_events: correctEvents,
    missed_events: missedEvents,
    wrong_direction_clips: wrongDirectionEvents,
    false_events_outside_target: falseEvents,
    duplicate_matched_events: duplicateEvents,
    delay_median_ms: percentileSorted(delays, 0.5),
    delay_p95_ms: percentileSorted(delays, 0.95),
    positive_window_recall: directionTruePositive / Math.max(1, directionTruePositive + directionFalseNegative),
    none_window_false_positive_rate: noneFalsePositive / Math.max(1, noneTotal),
    direction_macro_f1: directionF1.reduce((sum, value) => sum + value, 0) / directionF1.length,
    per_class_f1: Object.fromEntries(Object.entries(perClassF1).map(([name, value]) => [name, Number(value.toFixed(4))])),
    confusion,
    clip_details: clipDetails,
  };
}

function assignFolds(records, foldCount) {
  const byDirection = new Map();
  for (const record of records) {
    if (!byDirection.has(record.direction)) byDirection.set(record.direction, []);
    byDirection.get(record.direction).push(record);
  }
  for (const directionRecords of byDirection.values()) {
    directionRecords.sort((left, right) => left.sampleId - right.sampleId);
    directionRecords.forEach((record, ix) => { record.fold = ix % foldCount; });
  }
}

function coverage(records, windowMs) {
  let samplesCovered = 0;
  let positiveWindows = 0;
  let positiveWindowsCovered = 0;
  for (const record of records) {
    const positiveEnds = [];
    for (let endMs = windowMs; endMs <= record.rows.length * SAMPLE_INTERVAL_MS; endMs += STRIDE_MS) {
      if (endMs >= record.completionMs && endMs < record.positiveEndMs) positiveEnds.push(endMs);
    }
    const covered = positiveEnds.filter(endMs => endMs - windowMs <= record.mainMotionStartMs);
    positiveWindows += positiveEnds.length;
    positiveWindowsCovered += covered.length;
    if (covered.length === positiveEnds.length) samplesCovered += 1;
  }
  return {
    all_positive_windows_cover_main_start_samples: samplesCovered,
    sample_coverage_rate: samplesCovered / records.length,
    positive_window_coverage_rate: positiveWindowsCovered / positiveWindows,
  };
}

function roundedMetrics(result) {
  const clone = { ...result };
  for (const key of ['event_recall', 'positive_window_recall', 'none_window_false_positive_rate', 'direction_macro_f1']) {
    if (clone[key] !== null) clone[key] = Number(clone[key].toFixed(4));
  }
  delete clone.clip_details;
  return clone;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const annotationPath = path.resolve(args.annotations);
  const annotations = parseCsv(fs.readFileSync(annotationPath, 'utf8')).map(row => ({
    sampleId: Number(row.sample_id),
    filename: row.filename,
    direction: row.direction,
    completionMs: Number(row.completion_ms),
    positiveEndMs: Number(row.positive_target_end_ms),
    mainMotionStartMs: Number(row.main_motion_start_ms),
    mainMotionEndMs: Number(row.main_motion_end_ms),
    status: row.status,
    flags: row.flags,
  }));
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
    const response = await api.rawData.getSample(args.projectId, annotation.sampleId, {});
    if (!response.success) throw new Error(`Failed to read ${annotation.filename}`);
    const rows = response.payload.values;
    if (rows.length !== 300 || rows.some(row => row.length !== 6 || row.some(value => !Number.isFinite(value)))) {
      throw new Error(`${annotation.filename}: invalid six-axis payload`);
    }
    records.push({ ...annotation, rows });
  }

  const autoRecords = records.filter(record => record.status === 'AUTO');
  const reviewRecords = records.filter(record => record.status === 'REVIEW');
  assignFolds(autoRecords, args.folds);
  const comparisons = [];

  for (const windowMs of args.lengths) {
    const windows = autoRecords.flatMap(record => makeWindows(record, windowMs));
    const aggregateConfusion = emptyConfusion();
    const foldResults = [];

    for (let fold = 0; fold < args.folds; fold += 1) {
      const trainIds = new Set(autoRecords.filter(record => record.fold !== fold).map(record => record.sampleId));
      const testIds = new Set(autoRecords.filter(record => record.fold === fold).map(record => record.sampleId));
      const trainWindows = windows.filter(window => trainIds.has(window.sampleId));
      const testWindows = windows.filter(window => testIds.has(window.sampleId));
      const model = trainModel(trainWindows, args.epochs, 20260928 + windowMs + fold);
      const evaluation = evaluate(model, testWindows);
      mergeConfusion(aggregateConfusion, evaluation.confusion);
      foldResults.push({
        fold,
        train_samples: trainIds.size,
        test_samples: testIds.size,
        training_windows_after_sampling: model.trainingWindowCount,
        ...roundedMetrics(evaluation),
      });
    }

    const crossValidation = evaluateFromFoldResults(foldResults, aggregateConfusion);
    const allAutoWindows = autoRecords.flatMap(record => makeWindows(record, windowMs));
    const reviewWindows = reviewRecords.flatMap(record => makeWindows(record, windowMs));
    const stressModel = trainModel(allAutoWindows, args.epochs, 20260928 + windowMs + 99);
    const reviewEvaluation = evaluate(stressModel, reviewWindows);

    comparisons.push({
      window_ms: windowMs,
      input_samples: windowMs / SAMPLE_INTERVAL_MS,
      raw_float32_input_bytes: windowMs / SAMPLE_INTERVAL_MS * 6 * 4,
      feature_count_for_diagnostic_baseline: stressModel.featureCount,
      linear_parameter_count: stressModel.weights.length + stressModel.biases.length,
      context_coverage: coverage(autoRecords, windowMs),
      cross_validation: crossValidation,
      review_stress_set: roundedMetrics(reviewEvaluation),
      folds: foldResults,
    });
  }

  process.stdout.write(`${JSON.stringify({
    generated_at: new Date().toISOString(),
    project_id: args.projectId,
    source_annotations: path.relative(process.cwd(), annotationPath).replaceAll('\\', '/'),
    classes: CLASS_NAMES,
    auto_samples: autoRecords.length,
    review_samples: reviewRecords.length,
    split: `${args.folds}-fold stratified by direction and grouped by source sample`,
    stride_ms: STRIDE_MS,
    positive_target_ms: 150,
    event_postprocessing: '2 consecutive same-direction predictions; rearm after 2 consecutive NONE predictions',
    diagnostic_model: `${FEATURE_BINS} temporal bins x mean/std of 6 axes + endpoint delta, linear softmax`,
    epochs: args.epochs,
    caveats: [
      'Single user and one acquisition session; not a final generalization result.',
      'This linear feature baseline is not the final causal CNN/TCN.',
      'Three-second clips do not measure false positives per hour or continuous-event duplication.',
      'AUTO completion timestamps are algorithmic candidates, not manually verified ground truth.',
    ],
    comparisons,
  }, null, 2)}\n`);
}

function evaluateFromFoldResults(folds, confusion) {
  const clipCount = folds.reduce((sum, fold) => sum + fold.clip_count, 0);
  const correct = folds.reduce((sum, fold) => sum + fold.correct_events, 0);
  const missed = folds.reduce((sum, fold) => sum + fold.missed_events, 0);
  const wrong = folds.reduce((sum, fold) => sum + fold.wrong_direction_clips, 0);
  const falseEvents = folds.reduce((sum, fold) => sum + fold.false_events_outside_target, 0);
  const duplicates = folds.reduce((sum, fold) => sum + fold.duplicate_matched_events, 0);
  let directionTp = 0;
  let directionFn = 0;
  let noneTotal = 0;
  let noneFp = 0;
  const f1 = {};

  for (let cls = 0; cls < CLASS_NAMES.length; cls += 1) {
    const tp = confusion[cls][cls];
    const fp = confusion.reduce((sum, row, rowIx) => sum + (rowIx === cls ? 0 : row[cls]), 0);
    const fn = confusion[cls].reduce((sum, value, columnIx) => sum + (columnIx === cls ? 0 : value), 0);
    const precision = tp + fp === 0 ? 0 : tp / (tp + fp);
    const recall = tp + fn === 0 ? 0 : tp / (tp + fn);
    f1[CLASS_NAMES[cls]] = precision + recall === 0 ? 0 : 2 * precision * recall / (precision + recall);
    if (cls > 0) {
      directionTp += tp;
      directionFn += fn;
    }
  }
  noneTotal = confusion[0].reduce((sum, value) => sum + value, 0);
  noneFp = noneTotal - confusion[0][0];

  const delays = folds.flatMap(fold => {
    if (fold.delay_median_ms === null) return [];
    return [fold.delay_median_ms];
  });
  return {
    clip_count: clipCount,
    event_recall: Number((correct / clipCount).toFixed(4)),
    correct_events: correct,
    missed_events: missed,
    wrong_direction_clips: wrong,
    false_events_outside_target: falseEvents,
    false_events_per_clip: Number((falseEvents / clipCount).toFixed(4)),
    duplicate_matched_events: duplicates,
    fold_median_delay_median_ms: percentileSorted(delays, 0.5),
    positive_window_recall: Number((directionTp / Math.max(1, directionTp + directionFn)).toFixed(4)),
    none_window_false_positive_rate: Number((noneFp / Math.max(1, noneTotal)).toFixed(4)),
    direction_macro_f1: Number((CLASS_NAMES.slice(1).reduce((sum, name) => sum + f1[name], 0) / 4).toFixed(4)),
    per_class_f1: Object.fromEntries(Object.entries(f1).map(([name, value]) => [name, Number(value.toFixed(4))])),
    confusion,
  };
}

main().catch(error => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
