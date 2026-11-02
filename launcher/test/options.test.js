const test = require('node:test');
const assert = require('node:assert/strict');

const { DEFAULTS, buildArgs, normalize, validate } = require('../src/options');

test('the defaults give the plain command line of the README', () => {
  assert.deepEqual(buildArgs(DEFAULTS), [
    '--launcher', '--language', 'es', '--send-port', '39999', '--listen-port', '39998',
    '--first', 'random', '--ai', 'heuristic',
  ]);
});

test('every option maps to its flag', () => {
  const o = { ...DEFAULTS, first: 'human', botHero: 'medusa', humanHero: 'hellboy', language: 'en', ai: 'ismcts',
    aiTime: 3, botPause: 0, resume: true, sendPort: 40001, listenPort: 40002, config: 'C:\\t.json', timing: true };
  assert.deepEqual(buildArgs(o), [
    '--launcher', '--language', 'en', '--config', 'C:\\t.json', '--bot-hero', 'medusa', '--human-hero', 'hellboy',
    '--send-port', '40001', '--listen-port', '40002', '--first', 'human', '--ai', 'ismcts', '--ai-time', '3',
    '--bot-pause', '0', '--resume', '--timing',
  ]);
});

test('the table check passes only what reading the table uses', () => {
  const o = { ...DEFAULTS, botHero: 'medusa', resume: true, timing: true, ai: 'ismcts' };
  assert.deepEqual(buildArgs(o, { readOnly: true }), [
    '--launcher', '--language', 'es', '--bot-hero', 'medusa', '--send-port', '39999', '--listen-port', '39998',
    '--read-only',
  ]);
});

test('validation: same hero on both sides, ports, think time and pause', () => {
  assert.equal(validate(DEFAULTS), null);
  assert.equal(validate({ ...DEFAULTS, botHero: 'medusa', humanHero: 'medusa' }).key, 'error.same_hero');
  assert.equal(validate({ ...DEFAULTS, sendPort: 39998 }).key, 'error.ports');
  assert.equal(validate({ ...DEFAULTS, listenPort: 70000 }).key, 'error.ports');
  assert.equal(validate({ ...DEFAULTS, ai: 'ismcts', aiTime: 0 }).key, 'error.ai_time');
  assert.equal(validate({ ...DEFAULTS, ai: 'heuristic', aiTime: 0 }), null);
  assert.equal(validate({ ...DEFAULTS, botPause: 31 }).key, 'error.bot_pause');
});

test('saved options: unknown or invalid values fall back one by one', () => {
  const o = normalize({ first: 'bot', language: 'fr', botHero: 'gone', humanHero: 'hellboy', botPause: 2, aiTime: 'x' },
    ['medusa', 'hellboy']);
  assert.equal(o.first, 'bot');
  assert.equal(o.language, 'es');
  assert.equal(o.botHero, 'auto');
  assert.equal(o.humanHero, 'hellboy');
  assert.equal(o.botPause, 2);
  assert.equal(o.aiTime, DEFAULTS.aiTime);
  assert.deepEqual(normalize(null, []), DEFAULTS);
});
