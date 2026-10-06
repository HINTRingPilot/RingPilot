#!/usr/bin/env node
'use strict';

// Fixed-time augmentation: labels and completion times remain unchanged.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const input = path.resolve('data/windows');
const output = path.resolve(process.argv[2] || 'data/windows-augmented-5x');
if (fs.existsSync(output)) throw new Error(`Output already exists: ${output}`);
const lines = fs.readFileSync(path.join(input, 'manifest.csv'), 'utf8').trim().split(/\r?\n/);
const keys = lines.shift().split(',');
const records = lines.map(line => Object.fromEntries(line.split(',').map((v, i) => [keys[i], v])));
const groups = new Map();
for (const r of records) {
  if (!['training', 'testing'].includes(r.category)) throw new Error('Unexpected category');
  if (groups.has(r.sample_id) && groups.get(r.sample_id) !== r.category) throw new Error('Source split leakage');
  groups.set(r.sample_id, r.category);
}
function rng(key) {
  let state = crypto.createHash('sha256').update(`20261006:${key}`).digest().readUInt32LE();
  return () => { state = (Math.imul(1664525, state) + 1013904223) >>> 0; return (state + 0.5) / 4294967296; };
}
function normal(random) { return Math.sqrt(-2 * Math.log(random())) * Math.cos(2 * Math.PI * random()); }
function rotate(v, axis, angle) {
  const c = Math.cos(angle), s = Math.sin(angle);
  const dot = v.reduce((n, x, i) => n + x * axis[i], 0);
  const cross = [axis[1]*v[2]-axis[2]*v[1], axis[2]*v[0]-axis[0]*v[2], axis[0]*v[1]-axis[1]*v[0]];
  return v.map((x, i) => x*c + cross[i]*s + axis[i]*dot*(1-c));
}
const manifest = ['file,category,label,sample_id,source,window_end_ms,parent_file,variant'];
const counts = {};
for (const r of records) {
  const sourceFile = path.resolve(input, r.file);
  if (!sourceFile.startsWith(input + path.sep)) throw new Error('Invalid input path');
  const original = fs.readFileSync(sourceFile);
  const csv = original.toString('utf8').trim().split(/\r?\n/);
  const header = csv.shift();
  const rows = csv.map(line => line.split(',').map(Number));
  if (rows.length !== 160 || rows.some((row, i) => row.length !== 7 || row[0] !== i*10 || row.some(x => !Number.isFinite(x)))) throw new Error(`Invalid input ${r.file}`);
  for (let variant = 0; variant < (r.category === 'training' ? 5 : 1); variant++) {
    const file = variant === 0 ? r.file : r.file.replace(/\.csv$/, `.aug${variant}.csv`);
    let content = original;
    if (variant) {
      // One rigid rotation per original recording and variant, shared across its windows.
      const random = rng(`${r.sample_id}:${variant}`);
      const rawAxis = [normal(random), normal(random), normal(random)];
      const length = Math.hypot(...rawAxis);
      const axis = rawAxis.map(x => x/length);
      const angle = (random()*2-1) * 5 * Math.PI/180;
      const changed = rows.map(row => {
        const absoluteMs = Number(r.window_end_ms) - 1600 + row[0];
        // Shared overlapping timestamps get identical noise.
        const noise = rng(`${r.sample_id}:${variant}:${absoluteMs}`);
        const acc = rotate(row.slice(1,4), axis, angle);
        const gyro = rotate(row.slice(4,7), axis, angle);
        return [row[0], ...acc.map(x => (x + Math.max(-3, Math.min(3, normal(noise)))*0.02).toFixed(6)), ...gyro.map(x => (x + Math.max(-3, Math.min(3, normal(noise)))*0.2).toFixed(6))].join(',');
      });
      content = Buffer.from([header, ...changed, ''].join('\n'));
    }
    fs.mkdirSync(path.dirname(path.join(output, file)), {recursive:true});
    fs.writeFileSync(path.join(output, file), content);
    manifest.push([file,r.category,r.label,r.sample_id,r.source,r.window_end_ms,r.file,variant].join(','));
    const key = `${r.category}/${r.label}`;
    counts[key] = (counts[key] || 0)+1;
  }
}
fs.writeFileSync(path.join(output,'manifest.csv'), manifest.join('\n')+'\n');
const summary = {seed:20261006, input:'data/windows', factor_including_original:5, rotation_max_degrees:5, noise_std:{acc_m_s2:0.02,gyro_deg_s:0.2}, noise_clip_sigma:3, counts, note:'Exploratory strengths, not calibrated sensor noise. Training only. Original/test bytes preserved. Source IDs retained for grouped validation.'};
fs.writeFileSync(path.join(output,'augmentation.json'), JSON.stringify(summary,null,2)+'\n');
console.log(JSON.stringify(summary,null,2));
