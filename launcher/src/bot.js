// The bot as a child process: streams its output line by line, recognises the `--launcher` status lines and stops it
// the way Ctrl+C would (a `quit` line on its stdin), killing the process tree only if it does not exit in time.

const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const path = require('node:path');
const readline = require('node:readline');

const STATUS_PREFIX = '[sparring:status] ';
const STOP_GRACE_MS = 15000;    // a busy TTS can take 5 s + 8 s of late grace to answer the final clean-up

// The bundled executable when packaged; `uv run` from the repository in development.
function botCommand({ isPackaged, resourcesPath, appPath }) {
  if (isPackaged) {
    const dir = path.join(resourcesPath, 'bot');
    return { file: path.join(dir, 'sparring-bot.exe'), prefix: [], cwd: dir, dataDir: path.join(dir, '_internal', 'data') };
  }
  const repo = path.resolve(appPath, '..');
  return { file: 'uv', prefix: ['run', 'python', '-m', 'sparring.play'], cwd: repo, dataDir: path.join(repo, 'data') };
}

class Bot extends EventEmitter {
  constructor() {
    super();
    this.child = null;
    this.killTimer = null;
  }

  get running() {
    return this.child !== null;
  }

  start(command, args) {
    const child = spawn(command.file, [...command.prefix, ...args], {
      cwd: command.cwd,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
    });
    this.child = child;
    for (const stream of ['stdout', 'stderr']) {
      child[stream].setEncoding('utf8');
      readline.createInterface({ input: child[stream] }).on('line', (line) => this.onLine(stream, line));
    }
    child.stdin.on('error', () => {});     // the bot already gone: the exit event tells the rest
    // a failed spawn may also close: only the first of the two events counts
    child.on('error', (error) => {
      if (this.child !== child) return;
      this.finish();
      this.emit('spawn-error', error);
    });
    child.on('close', (code) => {      // after the last line of output, unlike 'exit'
      if (this.child !== child) return;
      this.finish();
      this.emit('exit', code);
    });
  }

  onLine(stream, line) {
    if (line.startsWith(STATUS_PREFIX)) this.emit('status', line.slice(STATUS_PREFIX.length).trim());
    else this.emit('line', { stream, text: line });
  }

  stop() {
    if (!this.child || this.killTimer) return;
    const { child } = this;
    child.stdin.end('quit\n');
    this.killTimer = setTimeout(() => {
      if (this.child === child) spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
    }, STOP_GRACE_MS);
  }

  finish() {
    clearTimeout(this.killTimer);
    this.killTimer = null;
    this.child = null;
  }
}

module.exports = { Bot, botCommand, STATUS_PREFIX };
