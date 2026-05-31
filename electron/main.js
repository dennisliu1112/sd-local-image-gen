'use strict';
const { app, BrowserWindow, Menu, ipcMain, dialog } = require('electron');
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

let backendLog = '';          // recent backend output, shown if startup fails
let backendExit = null;
function logBackend(s) {
  backendLog = (backendLog + s).slice(-4000);
}
function startBackend() {
  const { cmd, args, cwd } = backendCmd();
  logBackend(`launching: ${cmd}\ncwd: ${cwd}\n`);
  try {
    backend = spawn(cmd, args, {
      cwd,
      env: { ...process.env, PORT: String(PORT), ELECTRON_PID: String(process.pid) },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
  } catch (e) {
    logBackend(`spawn failed: ${e}\n`);
    return;
  }
  backend.stdout.on('data', d => { logBackend(d.toString()); process.stdout.write(`[py] ${d}`); });
  backend.stderr.on('data', d => { logBackend(d.toString()); process.stderr.write(`[py] ${d}`); });
  backend.on('error', e => logBackend(`process error: ${e}\n`));
  backend.on('exit', (code) => {
    backendExit = code;
    logBackend(`\n[backend exited, code=${code}]\n`);
    backend = null;
  });
}

// --- Wait until the server answers /health --------------------------------
function waitForHealth(timeoutMs = 180000, interval = 500) {
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

function installMenu() {
  // Minimal menu so clipboard shortcuts (Cmd/Ctrl+C/V/X/A) work in inputs.
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    { role: 'editMenu' },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1024, height: 768, minWidth: 880, minHeight: 620,
    backgroundColor: '#0f0f12',
    show: false,
    autoHideMenuBar: true,           // hide menu bar on Windows; shortcuts still work
    title: 'Amazing image Generator',
    webPreferences: { contextIsolation: true, preload: path.join(__dirname, 'preload.js') },
  });

  try {
    await win.webContents.session.clearCache();          // never show a stale cached UI
    await waitForHealth();
    await win.loadURL(`${BASE}/?v=${Date.now()}`);        // cache-bust the page load
  } catch (e) {
    const html =
      `<!doctype html><meta charset="utf-8">
       <body style="background:#0f0f12;color:#e9e9f1;font-family:-apple-system,'Microsoft JhengHei',sans-serif;padding:36px">
       <h2 style="color:#e05050">無法啟動生圖伺服器</h2>
       <p>${String(e)}${backendExit !== null ? `（後端已結束，代碼 ${backendExit}）` : ''}</p>
       <p style="color:#8b8ba0;font-size:13px">後端輸出（供除錯）：</p>
       <pre style="background:#16161f;border:1px solid #2a2a3a;border-radius:8px;padding:14px;white-space:pre-wrap;font-size:11px;max-height:60vh;overflow:auto">${backendLog.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</pre>
       </body>`;
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  }
  win.show();
}

// --- Lifecycle: kill the whole backend tree on quit -----------------------
function stopBackend(done) {
  if (!backend) return done();
  kill(backend.pid, 'SIGTERM', () => { backend = null; done(); });
}

ipcMain.handle('pick-folder', async () => {
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory', 'createDirectory'] });
  return (r.canceled || !r.filePaths.length) ? null : r.filePaths[0];
});

app.whenReady().then(() => {
  installMenu();
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
