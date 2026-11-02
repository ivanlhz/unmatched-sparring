const path = require('node:path');
const { app, BrowserWindow, ipcMain, Menu } = require('electron');

const { Bot, botCommand } = require('./bot');
const { buildArgs, normalize, validate } = require('./options');
const { listHeroes, readSettings, writeSettings } = require('./store');

const CATALOGS = { es: require('./i18n/es.json'), en: require('./i18n/en.json') };

const command = botCommand({ isPackaged: app.isPackaged, resourcesPath: process.resourcesPath, appPath: app.getAppPath() });
const settingsFile = path.join(app.getPath('userData'), 'options.json');
const bot = new Bot();
let win = null;

function send(message) {
  if (win && !win.isDestroyed()) win.webContents.send('bot', message);
}

bot.on('line', (line) => send({ type: 'line', ...line }));
bot.on('status', (word) => send({ type: 'status', word }));
bot.on('exit', (code) => send({ type: 'exit', code }));
bot.on('spawn-error', (error) => send({ type: 'spawn-error', detail: error.code || error.message }));

function heroes() {
  try {
    return listHeroes(command.dataDir);
  } catch {
    return [];                // the hero menus offer only "auto"; the bot itself still says what is wrong
  }
}

ipcMain.handle('init', () => {
  const list = heroes();
  const saved = readSettings(settingsFile);
  return {
    catalogs: CATALOGS,
    heroes: list,
    options: normalize(saved, list.map((h) => h.slug)),
    firstRun: saved === null,
  };
});

ipcMain.handle('save-options', (_event, options) => writeSettings(settingsFile, options));

ipcMain.handle('start', (_event, options, readOnly) => {
  if (bot.running) return { error: { key: 'error.already_running' } };
  const error = validate(options);
  if (error) return { error };
  writeSettings(settingsFile, options);
  bot.start(command, buildArgs(options, { readOnly }));
  return { ok: true };
});

ipcMain.handle('stop', () => bot.stop());

function createWindow() {
  Menu.setApplicationMenu(null);
  win = new BrowserWindow({
    width: 980,
    height: 940,
    minWidth: 720,
    minHeight: 600,
    backgroundColor: '#ffffff',
    title: 'Unmatched Sparring',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  // closing the window while the bot plays stops it first, so the panel and floor labels leave the table
  win.on('close', (event) => {
    if (!bot.running) return;
    event.preventDefault();
    bot.once('exit', () => win.destroy());
    bot.once('spawn-error', () => win.destroy());
    send({ type: 'stopping' });
    bot.stop();
  });
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
