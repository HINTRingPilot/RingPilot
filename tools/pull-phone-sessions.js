#!/usr/bin/env node

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const PACKAGE = 'com.hintringpilot.ringpilot';
const REMOTE_ROOT = `/sdcard/Android/data/${PACKAGE}/files`;
const REMOTE_SESSIONS = `${REMOTE_ROOT}/sessions`;
const REMOTE_CONNECTION_LOG = `${REMOTE_ROOT}/connection_log.csv`;
const DONE_MARKER = 'SESSION_DONE';

function parseArgs(argv) {
  const localAdb = path.join('.tools', 'android-sdk', 'platform-tools', 'adb.exe');
  const args = {
    adb: fs.existsSync(localAdb) ? localAdb : 'adb',
    out: path.join('data', 'sessions'),
    includeOpen: false,
    keep: false,
    dryRun: false,
  };

  for (let ix = 0; ix < argv.length; ix += 1) {
    const arg = argv[ix];
    if (arg === '--adb') args.adb = argv[++ix];
    else if (arg === '--out') args.out = argv[++ix];
    else if (arg === '--include-open') args.includeOpen = true;
    else if (arg === '--keep') args.keep = true;
    else if (arg === '--dry-run') args.dryRun = true;
    else if (arg === '--help' || arg === '-h') args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function printHelp() {
  process.stdout.write([
    'Move RingPilot app recordings from the phone to the PC, then delete them from the phone.',
    '',
    'Usage:',
    '  node tools/pull-phone-sessions.js [options]',
    '',
    'Options:',
    '  --adb PATH        adb executable (default: .tools/android-sdk/platform-tools/adb.exe, else adb)',
    '  --out DIR         Local destination (default: data/sessions)',
    '  --include-open    Also move sessions without the SESSION_DONE marker (still being recorded)',
    '  --keep            Copy and verify, but do not delete from the phone',
    '  --dry-run         Only list what would be moved',
    '',
    'Each session lands in <out>/phone-<session>/. A phone file is deleted only after every',
    'file in that session has been copied and its md5 matches the phone copy. The connection',
    'log is moved to <out>/phone-connection-logs/ the same way.',
    '',
  ].join('\n'));
}

function makeAdb(adbPath) {
  return (...adbArgs) => execFileSync(adbPath, adbArgs, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

function remoteList(adb, dir) {
  try {
    return adb('shell', `ls -1 ${dir}`).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  }
  catch {
    return [];  // 폴더가 없으면 옮길 것이 없다
  }
}

function remoteHashes(adb, dir) {
  const output = adb('shell', `cd ${dir} && md5sum *`);
  const hashes = new Map();
  for (const line of output.split(/\r?\n/)) {
    const match = line.trim().match(/^([0-9a-f]{32})\s+(.+)$/);
    if (match) hashes.set(match[2], match[1]);
  }
  return hashes;
}

function localHash(file) {
  return crypto.createHash('md5').update(fs.readFileSync(file)).digest('hex');
}

function verifyCopy(remote, localDir) {
  const problems = [];
  for (const [name, hash] of remote) {
    const file = path.join(localDir, name);
    if (!fs.existsSync(file)) problems.push(`${name}: missing on PC`);
    else if (localHash(file) !== hash) problems.push(`${name}: md5 mismatch`);
  }
  return problems;
}

function moveSession(adb, args, name) {
  const remoteDir = `${REMOTE_SESSIONS}/${name}`;
  const files = remoteList(adb, remoteDir);
  const done = files.includes(DONE_MARKER);
  if (!done && !args.includeOpen) return { name, status: 'skipped (not finished on phone)' };
  if (args.dryRun) return { name, status: `would move ${files.length} files` };

  const remote = remoteHashes(adb, remoteDir);
  const finalDir = path.join(args.out, `phone-${name}`);
  if (fs.existsSync(finalDir)) {
    // 이전 실행에서 복사는 됐지만 삭제 전에 멈춘 경우. 내용이 같을 때만 휴대폰 쪽을 지운다.
    const problems = verifyCopy(remote, finalDir);
    if (problems.length) return { name, status: `kept on phone: ${finalDir} already exists and differs (${problems.join('; ')})` };
  }
  else {
    const tempDir = path.join(args.out, `.pulling-${name}`);
    fs.rmSync(tempDir, { recursive: true, force: true });
    fs.mkdirSync(args.out, { recursive: true });
    adb('pull', remoteDir, tempDir);
    const problems = verifyCopy(remote, tempDir);
    if (problems.length) return { name, status: `kept on phone: verification failed (${problems.join('; ')})` };
    fs.renameSync(tempDir, finalDir);
  }

  if (args.keep) return { name, status: `copied and verified ${remote.size} files (kept on phone)` };
  adb('shell', `rm -r ${remoteDir}`);
  return { name, status: `moved ${remote.size} files, deleted from phone` };
}

function moveLogFile(adb, args, name) {
  const remoteFile = `${REMOTE_ROOT}/${name}`;
  if (args.dryRun) return `would move ${name}`;

  const remoteHash = adb('shell', `md5sum ${remoteFile}`).trim().split(/\s+/)[0];
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const dir = path.join(args.out, 'phone-connection-logs');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${path.basename(name, '.csv')}-${stamp}.csv`);
  adb('pull', remoteFile, file);
  if (localHash(file) !== remoteHash) return `${name} kept on phone: md5 mismatch (${file})`;
  if (args.keep) return `${name} copied to ${file} (kept on phone)`;
  adb('shell', `rm ${remoteFile}`);
  return `${name} moved to ${file}, deleted from phone`;
}

function moveConnectionLogs(adb, args) {
  const present = remoteList(adb, REMOTE_ROOT);
  // imu_reconnect_log.csv는 이전 측정 화면이 남긴 파일이다. 같은 방식으로 옮겨 휴대폰을 비운다.
  const names = [REMOTE_CONNECTION_LOG, `${REMOTE_ROOT}/imu_reconnect_log.csv`]
    .map(remote => path.posix.basename(remote))
    .filter(name => present.includes(name));
  if (names.length === 0) return ['no connection log on phone'];
  return names.map(name => moveLogFile(adb, args, name));
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const adb = makeAdb(args.adb);
  const devices = adb('devices').split(/\r?\n/).slice(1).filter(line => /\tdevice$/.test(line.trim()));
  if (devices.length !== 1) throw new Error(`Expected exactly one connected phone, found ${devices.length}. Check USB debugging.`);

  const sessions = remoteList(adb, REMOTE_SESSIONS);
  const results = sessions.map(name => moveSession(adb, args, name));
  for (const result of results) process.stdout.write(`${result.name}: ${result.status}\n`);
  if (sessions.length === 0) process.stdout.write('no sessions on phone\n');
  for (const line of moveConnectionLogs(adb, args)) process.stdout.write(`${line}\n`);
}

try {
  main();
}
catch (error) {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
}
