const test = require('node:test');
const assert = require('node:assert/strict');

const { DEFAULTS, buildArgs, normalize, validate } = require('../src/options');

test('the defaults give the plain command line of the README', () => {
  assert.deepEqual(buildArgs(DEFAULTS), [
    '--launcher', '--language', 'en', '--send-port', '39999', '--listen-port', '39998',
    '--first', 'random', '--ai', 'ismcts', '--ai-eval', 'new', '--ai-time', '1.5',
  ]);
});

test('every option maps to its flag', () => {
  const o = { ...DEFAULTS, first: 'human', botHero: 'medusa', humanHero: 'hellboy', language: 'en', difficulty: 'normal',
    aiTime: 3, botPause: 0, resume: true, sendPort: 40001, listenPort: 40002, config: 'C:\\t.json', timing: true };
  assert.deepEqual(buildArgs(o), [
    '--launcher', '--language', 'en', '--config', 'C:\\t.json', '--bot-hero', 'medusa', '--human-hero', 'hellboy',
    '--send-port', '40001', '--listen-port', '40002', '--first', 'human', '--ai', 'ismcts', '--ai-eval', 'old', '--ai-time', '3',
    '--bot-pause', '0', '--resume', '--timing',
  ]);
});

test('the table check passes only what reading the table uses', () => {
  const o = { ...DEFAULTS, botHero: 'medusa', resume: true, timing: true };
  assert.deepEqual(buildArgs(o, { readOnly: true }), [
    '--launcher', '--language', 'en', '--bot-hero', 'medusa', '--send-port', '39999', '--listen-port', '39998',
    '--read-only',
  ]);
});

test('validation: same hero on both sides, ports, think time and pause', () => {
  assert.equal(validate(DEFAULTS), null);
  assert.equal(validate({ ...DEFAULTS, botHero: 'medusa', humanHero: 'medusa' }).key, 'error.same_hero');
  assert.equal(validate({ ...DEFAULTS, sendPort: 39998 }).key, 'error.ports');
  assert.equal(validate({ ...DEFAULTS, listenPort: 70000 }).key, 'error.ports');
  assert.equal(validate({ ...DEFAULTS, difficulty: 'normal', aiTime: 0 }).key, 'error.ai_time');
  assert.equal(validate({ ...DEFAULTS, difficulty: 'easy', aiTime: 0 }), null);
  assert.equal(validate({ ...DEFAULTS, botPause: 31 }).key, 'error.bot_pause');
});

test('saved options: unknown or invalid values fall back one by one', () => {
  const o = normalize({ first: 'bot', language: 'fr', botHero: 'gone', humanHero: 'hellboy', botPause: 2, aiTime: 'x' },
    ['medusa', 'hellboy']);
  assert.equal(o.first, 'bot');
  assert.equal(o.language, 'en');
  assert.equal(o.botHero, 'auto');
  assert.equal(o.humanHero, 'hellboy');
  assert.equal(o.botPause, 2);
  assert.equal(o.aiTime, DEFAULTS.aiTime);
  assert.deepEqual(normalize(null, []), DEFAULTS);
});

test('language: English on a first run, a saved Spanish choice is kept, and it reaches the bot', () => {
  assert.equal(normalize(null, []).language, 'en');
  assert.equal(normalize({}, []).language, 'en');
  const es = normalize({ language: 'es' }, []);
  assert.equal(es.language, 'es');
  assert.deepEqual(buildArgs(es).slice(0, 3), ['--launcher', '--language', 'es']);
  assert.deepEqual(buildArgs(normalize(null, [])).slice(0, 3), ['--launcher', '--language', 'en']);
});

test('difficulty: Hard by default; Easy is the heuristic bot, Normal the old evaluation, Hard the new one', () => {
  assert.equal(DEFAULTS.difficulty, 'hard');
  const args = (difficulty) => buildArgs({ ...DEFAULTS, difficulty }).slice(-6);
  assert.deepEqual(args('hard'), ['--ai', 'ismcts', '--ai-eval', 'new', '--ai-time', '1.5']);
  assert.deepEqual(args('normal'), ['--ai', 'ismcts', '--ai-eval', 'old', '--ai-time', '1.5']);
  const easy = buildArgs({ ...DEFAULTS, difficulty: 'easy' });
  assert.deepEqual(easy.slice(-4), ['--first', 'random', '--ai', 'heuristic']);
  assert.equal(easy.includes('--ai-eval') || easy.includes('--ai-time'), false);
});

test('difficulty in saved options: kept, migrated from the old ai key, invalid falls back to Hard', () => {
  assert.equal(normalize(null, []).difficulty, 'hard');
  for (const d of ['easy', 'normal', 'hard']) assert.equal(normalize({ difficulty: d }, []).difficulty, d);
  assert.equal(normalize({ ai: 'heuristic' }, []).difficulty, 'easy');
  assert.equal(normalize({ ai: 'ismcts' }, []).difficulty, 'hard');
  assert.equal(normalize({ ai: 'heuristic', difficulty: 'normal' }, []).difficulty, 'normal');
  assert.equal(normalize({ difficulty: 'insane' }, []).difficulty, 'hard');
  assert.equal(normalize({ ai: 'other' }, []).difficulty, 'hard');
  assert.equal('ai' in normalize({ ai: 'heuristic' }, []), false);
});
