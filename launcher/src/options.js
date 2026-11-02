// The launcher's options and how they become the bot's command line (sparring/play.py --help).

const DEFAULTS = Object.freeze({
  first: 'random',
  botHero: 'auto',
  humanHero: 'auto',
  language: 'en',   // the launcher starts in English; the bot's own command line default stays Spanish
  ai: 'heuristic',
  aiTime: 1.5,
  botPause: '',
  resume: false,
  sendPort: 39999,
  listenPort: 39998,
  config: '',
  timing: false,
});

const CHOICES = {
  first: ['human', 'bot', 'random'],
  language: ['es', 'en'],
  ai: ['heuristic', 'ismcts'],
};

function isPort(value) {
  return Number.isInteger(value) && value >= 1 && value <= 65535;
}

// Settings saved by an older launcher may lack keys or hold values that are no longer valid: each falls back alone.
function normalize(saved, heroSlugs) {
  const o = { ...DEFAULTS };
  for (const key of Object.keys(DEFAULTS)) {
    if (saved && saved[key] !== undefined && typeof saved[key] === typeof DEFAULTS[key]) o[key] = saved[key];
  }
  if (saved && typeof saved.botPause === 'number') o.botPause = saved.botPause;
  for (const [key, allowed] of Object.entries(CHOICES)) if (!allowed.includes(o[key])) o[key] = DEFAULTS[key];
  for (const key of ['botHero', 'humanHero']) if (o[key] !== 'auto' && !heroSlugs.includes(o[key])) o[key] = 'auto';
  return o;
}

// null when the options can start the bot, else { key, vars } of the launcher's catalog.
function validate(o) {
  if (o.botHero !== 'auto' && o.botHero === o.humanHero) return { key: 'error.same_hero' };
  if (!isPort(o.sendPort) || !isPort(o.listenPort) || o.sendPort === o.listenPort) return { key: 'error.ports' };
  if (o.ai === 'ismcts' && !(o.aiTime >= 0.1 && o.aiTime <= 60)) return { key: 'error.ai_time' };
  if (o.botPause !== '' && !(o.botPause >= 0 && o.botPause <= 30)) return { key: 'error.bot_pause' };
  return null;
}

function buildArgs(o, { readOnly = false } = {}) {
  const args = ['--launcher', '--language', o.language];
  if (o.config) args.push('--config', o.config);
  if (o.botHero !== 'auto') args.push('--bot-hero', o.botHero);
  if (o.humanHero !== 'auto') args.push('--human-hero', o.humanHero);
  args.push('--send-port', String(o.sendPort), '--listen-port', String(o.listenPort));
  if (readOnly) return [...args, '--read-only'];
  args.push('--first', o.first, '--ai', o.ai);
  if (o.ai === 'ismcts') args.push('--ai-time', String(o.aiTime));
  if (o.botPause !== '') args.push('--bot-pause', String(o.botPause));
  if (o.resume) args.push('--resume');
  if (o.timing) args.push('--timing');
  return args;
}

module.exports = { DEFAULTS, normalize, validate, buildArgs };
