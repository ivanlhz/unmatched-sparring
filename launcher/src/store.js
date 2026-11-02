// Files the launcher reads and writes: the hero list of the bot's data and the last options used.

const fs = require('node:fs');
const path = require('node:path');

// data/heroes/<slug>.json, top level only (effects/ and overlay/ are per-hero detail), sorted by name.
function listHeroes(dataDir) {
  const dir = path.join(dataDir, 'heroes');
  return fs.readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .map((name) => JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8')))
    .map((hero) => ({ slug: hero.slug, name: hero.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function readSettings(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;              // first run or a damaged file: the defaults apply
  }
}

function writeSettings(file, options) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(options, null, 2), 'utf8');
}

module.exports = { listHeroes, readSettings, writeSettings };
