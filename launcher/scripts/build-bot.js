// Builds the bot as a standalone Windows program with PyInstaller (one folder: sparring-bot.exe + _internal\).
// The bot uses only the standard library, so a throwaway uv environment with PyInstaller is all it needs.
// --system-certs: uv trusts the Windows certificate store (also on machines that inspect TLS).

const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const PYINSTALLER = 'pyinstaller==6.22.3';
const PYTHON = '3.11';

const launcher = path.resolve(__dirname, '..');
const repo = path.resolve(launcher, '..');
const build = path.join(launcher, 'build');
const logFile = path.join(build, 'build-bot.log');
const started = Date.now();

fs.mkdirSync(build, { recursive: true });
fs.writeFileSync(logFile, '');

function report(message, error = false) {
  const line = `[build:bot] ${message}\n`;
  fs.appendFileSync(logFile, line);
  (error ? process.stderr : process.stdout).write(line);
}

const args = [
  // --no-project alone still adds the repository's .venv to sys.path.
  'run', '--system-certs', '--no-project', '--isolated', '--python', PYTHON, '--with', PYINSTALLER,
  'python', '-m', 'PyInstaller', '--noconfirm', '--clean', '--console',
  '--name', 'sparring-bot',
  '--distpath', path.join(build, 'bot-dist'),
  '--workpath', path.join(build, 'bot-work'),
  '--specpath', build,
  '--paths', repo,
  // next to the code inside the bundle, where sparring\board.py and sparring\i18n look for them
  '--add-data', `${path.join(repo, 'data')};data`,
  '--add-data', `${path.join(repo, 'config', 'table.json')};config`,
  path.join(launcher, 'bot', 'sparring_bot.py'),
];

report(`Preparing Python ${PYTHON} and ${PYINSTALLER} in an isolated environment.`);
report(`Log: ${logFile}`);
const child = spawn('uv', args, {
  cwd: repo,
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true,
  env: {
    ...process.env,
    PYINSTALLER_CONFIG_DIR: process.env.PYINSTALLER_CONFIG_DIR || path.join(build, 'pyinstaller-cache'),
  },
});

for (const [source, destination] of [[child.stdout, process.stdout], [child.stderr, process.stderr]]) {
  source.on('data', (chunk) => {
    fs.appendFileSync(logFile, chunk);
    destination.write(chunk);
  });
}

let stoppedCode;
function stop(code, message) {
  if (stoppedCode !== undefined) return;
  stoppedCode = code;
  report(message, true);
  if (!child.pid) return;
  if (process.platform === 'win32') {
    // Stop Python too, before terminating its uv parent, so it cannot keep writing build output.
    const result = spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
      stdio: 'ignore', windowsHide: true, timeout: 5000,
    });
    if (result.error || result.status !== 0) {
      report(`Could not stop the process tree (PID ${child.pid}); check it before rebuilding.`, true);
      child.kill('SIGKILL');
    }
  } else {
    child.kill('SIGTERM');
  }
}

const progress = setInterval(() => {
  report(`Still running (${Math.round((Date.now() - started) / 1000)}s). Last tool output is in the log.`);
}, 30000);
const deadline = setTimeout(() => stop(1, 'Build exceeded 10 minutes; stopping. Check the log for the last completed step.'), 600000);
const interrupt = () => stop(130, 'Build cancelled.');
process.on('SIGINT', interrupt);
process.on('SIGTERM', interrupt);

child.on('error', (error) => {
  stoppedCode = 1;
  report(error.code === 'ENOENT'
    ? 'Could not find uv. Install it: https://docs.astral.sh/uv/'
    : `Could not run uv: ${error.message}`, true);
});
child.on('close', (code, signal) => {
  clearInterval(progress);
  clearTimeout(deadline);
  process.removeListener('SIGINT', interrupt);
  process.removeListener('SIGTERM', interrupt);
  process.exitCode = stoppedCode ?? code ?? 1;
  report(process.exitCode === 0
    ? `Bot ready (${Math.round((Date.now() - started) / 1000)}s).`
    : `Build failed (${signal || process.exitCode}). See ${logFile}`, process.exitCode !== 0);
});
