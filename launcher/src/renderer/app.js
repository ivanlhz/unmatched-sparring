// The launcher's window: options form, START / CHECK / STOP, status line and the bot's console.

const MAX_LOG_LINES = 3000;
const form = document.getElementById('options');
const log = document.getElementById('log');
const formError = document.getElementById('form-error');
const buttons = { start: document.getElementById('start'), check: document.getElementById('check'), stop: document.getElementById('stop') };

let catalogs = {};
let heroes = [];
let status = { key: 'status.idle', vars: {}, state: 'idle' };
let run = null;               // { readOnly, failed, stopping } while the bot process lives

function t(key, vars = {}) {
  const lang = form.elements.language.value || 'en';
  const text = (catalogs[lang] && catalogs[lang][key]) || catalogs.en[key] || key;
  return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? ''));
}

function translate() {
  document.documentElement.lang = form.elements.language.value;
  for (const el of document.querySelectorAll('[data-t]')) el.textContent = t(el.dataset.t);
  log.dataset.empty = t('log.empty');
  fillHeroes();
  showStatus();
  if (!formError.hidden && formError.dataset.key) formError.textContent = t(formError.dataset.key);
}

function fillHeroes() {
  for (const name of ['botHero', 'humanHero']) {
    const select = form.elements[name];
    const current = select.value || select.dataset.value || 'auto';
    select.replaceChildren(new Option(t('hero.auto'), 'auto'), ...heroes.map((h) => new Option(h.name, h.slug)));
    select.value = current;
  }
}

function readOptions() {
  const f = form.elements;
  const number = (input) => (input.value === '' ? '' : Number(input.value));
  return {
    first: f.first.value,
    botHero: f.botHero.value,
    humanHero: f.humanHero.value,
    language: f.language.value,
    ai: f.ai.value,
    aiTime: Number(f.aiTime.value),
    botPause: number(f.botPause),
    resume: f.resume.checked,
    sendPort: Number(f.sendPort.value),
    listenPort: Number(f.listenPort.value),
    config: f.config.value.trim(),
    timing: f.timing.checked,
  };
}

function writeOptions(o) {
  const f = form.elements;
  f.first.value = o.first;
  f.language.value = o.language;
  f.botHero.dataset.value = o.botHero;
  f.humanHero.dataset.value = o.humanHero;
  f.ai.value = o.ai;
  f.aiTime.value = o.aiTime;
  f.botPause.value = o.botPause;
  f.resume.checked = o.resume;
  f.sendPort.value = o.sendPort;
  f.listenPort.value = o.listenPort;
  f.config.value = o.config;
  f.timing.checked = o.timing;
}

function setStatus(state, key, vars = {}) {
  status = { state, key, vars };
  showStatus();
}

function showStatus() {
  const box = document.getElementById('status');
  box.dataset.state = status.state;
  document.getElementById('status-text').textContent = t(status.key, status.vars);
  const busy = run !== null;
  buttons.start.hidden = busy;
  buttons.check.hidden = busy;
  buttons.stop.hidden = !busy || run.stopping;
  for (const el of form.elements) el.disabled = busy;
}

function showFormError(error) {
  formError.hidden = !error;
  formError.dataset.key = error ? error.key : '';
  formError.textContent = error ? t(error.key, error.vars) : '';
}

function syncForm() {
  const o = readOptions();
  document.getElementById('ai-time-field').hidden = o.ai !== 'ismcts';
  showFormError(o.botHero !== 'auto' && o.botHero === o.humanHero ? { key: 'error.same_hero' } : null);
}

function appendLog(text, stream) {
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const line = document.createElement('span');
  line.className = stream === 'stderr' ? 'err' : '';
  line.textContent = `${text}\n`;
  log.append(line);
  while (log.childElementCount > MAX_LOG_LINES) log.firstElementChild.remove();
  if (nearBottom) log.scrollTop = log.scrollHeight;
}

async function start(readOnly) {
  const options = readOptions();
  const result = await window.sparring.start(options, readOnly);
  if (result.error) {
    showFormError(result.error);
    return;
  }
  showFormError(null);
  if (log.childElementCount) appendLog('-'.repeat(40));       // where the output of this run begins
  run = { readOnly, failed: false, stopping: false, listenPort: options.listenPort };
  setStatus('busy', 'status.starting');
}

function onBot(message) {
  if (message.type === 'line') appendLog(message.text, message.stream);
  else if (message.type === 'status') onStatus(message.word);
  else if (message.type === 'stopping' && run) {
    run.stopping = true;
    setStatus('busy', 'status.stopping');
  } else if (message.type === 'spawn-error') {
    run = null;
    setStatus('error', 'error.spawn', { detail: message.detail });
  } else if (message.type === 'exit') onExit(message.code);
}

function onStatus(word) {
  if (!run) return;
  const [kind, detail] = word.split(' ');
  if (kind === 'connecting' && !run.stopping) setStatus('busy', run.readOnly ? 'status.checking' : 'status.connecting');
  else if (kind === 'playing' && !run.stopping) setStatus('playing', 'status.playing');
  else if (kind === 'error') {
    run.failed = true;
    setStatus('error', `error.${detail}`, { port: run.listenPort });
  }
}

function onExit(code) {
  const ended = run;
  run = null;
  if (!ended || ended.failed) showStatus();
  else if (code === 0 && ended.readOnly) setStatus('idle', 'status.checked');
  else if (code === 0 || ended.stopping) setStatus('idle', 'status.stopped');
  else setStatus('error', 'error.crashed', { code });
}

async function init() {
  const state = await window.sparring.init();
  catalogs = state.catalogs;
  heroes = state.heroes;
  writeOptions(state.options);
  document.getElementById('help').open = state.firstRun;
  translate();
  syncForm();
  window.sparring.onBot(onBot);
  const onChange = () => {
    syncForm();
    if (form.elements.language.value !== document.documentElement.lang) translate();
    window.sparring.saveOptions(readOptions());
  };
  form.addEventListener('change', onChange);
  document.querySelector('.lang-switch').addEventListener('change', onChange);
  form.addEventListener('submit', (event) => event.preventDefault());
  buttons.start.addEventListener('click', () => start(false));
  buttons.check.addEventListener('click', () => start(true));
  buttons.stop.addEventListener('click', () => {
    if (!run) return;
    run.stopping = true;
    setStatus('busy', 'status.stopping');
    window.sparring.stop();
  });
  document.getElementById('clear').addEventListener('click', () => log.replaceChildren());
}

init();
