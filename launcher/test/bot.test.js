const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { Bot, botCommand } = require('../src/bot');

// A stand-in for the bot that speaks the --launcher protocol: status lines, output, and a clean exit on `quit`.
const FAKE_BOT = `
process.stdout.write('[sparring:status] connecting\\n[sparring:status] playing\\nPanel creado\\n');
process.stderr.write('Aviso: algo\\n');
let input = '';
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  process.stdout.write('cleaned ' + JSON.stringify(input) + '\\n[sparring:status] exit 0\\n');
  process.exit(0);
});
`;

function fakeBot() {
  return { file: process.execPath, prefix: ['-e', FAKE_BOT], cwd: __dirname };
}

test('streams lines, recognises status lines and stops with a quit line', async () => {
  const bot = new Bot();
  const lines = [];
  const statuses = [];
  bot.on('line', (line) => lines.push(line));
  bot.on('status', (word) => {
    statuses.push(word);
    if (word === 'playing') bot.stop();
  });
  const exited = new Promise((resolve) => bot.on('exit', resolve));
  bot.start(fakeBot(), []);
  assert.equal(bot.running, true);
  assert.equal(await exited, 0);
  assert.equal(bot.running, false);
  assert.deepEqual(statuses, ['connecting', 'playing', 'exit 0']);
  const byText = (a, b) => a.text.localeCompare(b.text);     // stdout and stderr interleave in any order
  assert.deepEqual(lines.sort(byText), [
    { stream: 'stderr', text: 'Aviso: algo' },
    { stream: 'stdout', text: 'cleaned "quit\\n"' },
    { stream: 'stdout', text: 'Panel creado' },
  ].sort(byText));
});

test('a missing program is a spawn error, not a crash', async () => {
  const bot = new Bot();
  const error = await new Promise((resolve) => {
    bot.on('spawn-error', resolve);
    bot.start({ file: path.join(__dirname, 'no-such-bot.exe'), prefix: [], cwd: __dirname }, []);
  });
  assert.equal(error.code, 'ENOENT');
  assert.equal(bot.running, false);
});

test('packaged, the bot is the bundled exe; in development, uv from the repository', () => {
  const packaged = botCommand({ isPackaged: true, resourcesPath: 'C:\\App\\resources', appPath: 'unused' });
  assert.equal(packaged.file, path.join('C:\\App\\resources', 'bot', 'sparring-bot.exe'));
  assert.equal(packaged.dataDir, path.join('C:\\App\\resources', 'bot', '_internal', 'data'));
  const dev = botCommand({ isPackaged: false, resourcesPath: 'unused', appPath: 'C:\\repo\\launcher' });
  assert.deepEqual([dev.file, ...dev.prefix], ['uv', 'run', 'python', '-m', 'sparring.play']);
  assert.equal(dev.cwd, 'C:\\repo');
});
