const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = path.join(__dirname, '..', 'scripts', 'build-bot.js');

function build() {
  const child = Object.assign(new EventEmitter(), {
    pid: 12345,
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
  });
  let log = '';
  let output = '';
  const process = Object.assign(new EventEmitter(), {
    env: {}, platform: 'win32',
    stdout: { write: (text) => { output += text; } },
    stderr: { write: (text) => { output += text; } },
  });
  const kills = [];
  const timers = new Set();
  const timer = (callback, ms) => {
    const handle = { callback, ms };
    timers.add(handle);
    return handle;
  };
  vm.runInNewContext(fs.readFileSync(script, 'utf8'), {
    __dirname: path.dirname(script), process,
    setInterval: timer, setTimeout: timer,
    clearInterval: (handle) => timers.delete(handle),
    clearTimeout: (handle) => timers.delete(handle),
    require: (name) => {
      if (name === 'node:child_process') return {
        spawn: () => child,
        spawnSync: (file, args) => { kills.push({ file, args: Array.from(args) }); return { status: 0 }; },
      };
      if (name === 'node:fs') return {
        mkdirSync() {}, writeFileSync() { log = ''; },
        appendFileSync: (_, chunk) => { log += chunk; },
      };
      return require(name);
    },
  });
  return { child, process, timers, kills, log: () => log, output: () => output };
}

test('build streams tool output to the console and log, then releases its timers', () => {
  const run = build();
  run.child.stdout.emit('data', Buffer.from('Build complete!\n'));
  run.child.stderr.emit('data', Buffer.from('tool warning\n'));
  run.child.emit('close', 0, null);
  assert.equal(run.process.exitCode, 0);
  assert.match(run.log(), /Build complete!\ntool warning\n/);
  assert.equal(run.log(), run.output());
  assert.equal(run.timers.size, 0);
  assert.equal(run.process.listenerCount('SIGINT'), 0);
});

test('a signal exit cannot report a successful build', () => {
  const run = build();
  run.child.emit('close', null, 'SIGTERM');
  assert.equal(run.process.exitCode, 1);
  assert.match(run.log(), /Build failed \(SIGTERM\)/);
});

test('missing uv reports an actionable error and terminates', () => {
  const run = build();
  run.child.emit('error', Object.assign(new Error('missing'), { code: 'ENOENT' }));
  run.child.emit('close', -2, null);
  assert.equal(run.process.exitCode, 1);
  assert.match(run.log(), /Could not find uv/);
  assert.equal(run.timers.size, 0);
});

test('a timeout stops the whole Windows build tree and cannot become a success', () => {
  const run = build();
  [...run.timers].find(({ ms }) => ms === 600000).callback();
  run.process.emit('SIGINT');
  assert.deepEqual(run.kills, [{ file: 'taskkill', args: ['/pid', '12345', '/T', '/F'] }]);
  run.child.emit('close', 0, null);
  assert.equal(run.process.exitCode, 1);
  assert.equal(run.timers.size, 0);
});

test('Ctrl+C stops the build tree and returns a cancellation status', () => {
  const run = build();
  run.process.emit('SIGINT');
  run.child.emit('close', null, 'SIGTERM');
  assert.equal(run.kills.length, 1);
  assert.equal(run.process.exitCode, 130);
});
