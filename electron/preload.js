'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Expose a minimal, safe bridge to the renderer (the web UI).
contextBridge.exposeInMainWorld('aig', {
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
});
