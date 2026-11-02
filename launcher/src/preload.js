const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('sparring', {
  init: () => ipcRenderer.invoke('init'),
  start: (options, readOnly) => ipcRenderer.invoke('start', options, readOnly),
  stop: () => ipcRenderer.invoke('stop'),
  saveOptions: (options) => ipcRenderer.invoke('save-options', options),
  onBot: (listener) => ipcRenderer.on('bot', (_event, message) => listener(message)),
});
