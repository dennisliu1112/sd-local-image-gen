'use strict';
const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const kill = require('tree-kill');

const PORT = 8080;
const BASE = `http://127.0.0.1:${PORT}`;

let backend = null;
let win = null;
let quitting = false;

// --- Resolve how to launch the Python backend -----------------------------
function backendCmd() {
  if (app.isPackaged) {
    const exe = process.platform === 'win32' ? 'server.exe' : 'server';
    const bin = path.join(process.resourcesPath, 'server', exe);
    return { cmd: bin, args: [], cwd: path.dirname(bin) };
  }
  // dev: run the repo's Python server via the project venv
  const py = process.platform === 'win32'
    ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
    : path.join(__dirname, '..', '.venv', 'bin', 'python');
  const script = path.join(__dirname, '..', 'windows-app', 'server.py');
  return { cmd: py, args: [script], cwd: path.join(__dirname, '..', 'windows-app') };
}

function startBackend() {
  const { cmd, args, cwd } = backendCmd();
  console.log('[main] launching backend:', cmd, args.join(' '));
  backend = spawn(cmd, args, {
    cwd,
    env: { ...process.env, PORT: String(PORT), ELECTRON_PID: String(process.pid) },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  backend.stdout.on('data', d => process.stdout.write(`[py] ${d}`));
  backend.stderr.on('data', d => process.stderr.write(`[py] ${d}`));
  backend.on('exit', (code) => {
    console.log('[main] backend exited:', code);
    backend = null;
  });
}

// --- Wait until the server answers /health --------------------------------
function waitForHealth(timeoutMs = 60000, interval = 400) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const ping = () => {
      const req = http.get(`${BASE}/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else retry();
      });
      req.on('error', retry);
      req.setTimeout(2000, () => req.destroy());
    };
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error('backend did not start in time'));
      setTimeout(ping, interval);
    };
    ping();
  });
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1180, height: 820, minWidth: 900, minHeight: 640,
    backgroundColor: '#0f0f12',
    show: false,
    title: 'Z-Image Generator',
    webPreferences: { contextIsolation: true },
  });
  win.removeMenu();

  try {
    await waitForHealth();
    await win.loadURL(BASE);
  } catch (e) {
    await win.loadURL('data:text/html,' + encodeURIComponent(
      `<body style="background:#0f0f12;color:#e05050;font-family:sans-serif;padding:40px">
       <h2>無法啟動生圖伺服器</h2><pre>${String(e)}</pre></body>`));
  }
  win.show();
}

// --- Lifecycle: kill the whole backend tree on quit -----------------------
function stopBackend(done) {
  if (!backend) return done();
  kill(backend.pid, 'SIGTERM', () => { backend = null; done(); });
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
});

app.on('before-quit', (e) => {
  if (backend && !quitting) {
    e.preventDefault();
    quitting = true;
    stopBackend(() => app.quit());
  }
});

app.on('window-all-closed', () => app.quit());      // single-purpose app: close = exit
app.on('will-quit', () => { if (backend) kill(backend.pid); });
process.on('exit', () => { if (backend) { try { process.kill(backend.pid); } catch {} } });
