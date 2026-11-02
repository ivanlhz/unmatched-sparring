// Builds the bot as a standalone Windows program with PyInstaller (one folder: sparring-bot.exe + _internal\).
// The bot uses only the standard library, so a throwaway uv environment with PyInstaller is all it needs.
// --system-certs: uv trusts the Windows certificate store (also on machines that inspect TLS).

const { spawnSync } = require('node:child_process');
const path = require('node:path');

const PYINSTALLER = 'pyinstaller==6.22.3';
const PYTHON = '3.11';

const launcher = path.resolve(__dirname, '..');
const repo = path.resolve(launcher, '..');
const build = path.join(launcher, 'build');

const args = [
  'run', '--system-certs', '--no-project', '--python', PYTHON, '--with', PYINSTALLER,
  'pyinstaller', '--noconfirm', '--clean', '--console',
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

const result = spawnSync('uv', args, { cwd: repo, stdio: 'inherit' });
if (result.error) {
  console.error(`Could not run uv (${result.error.code}). Install uv: https://docs.astral.sh/uv/`);
  process.exit(1);
}
process.exit(result.status);
