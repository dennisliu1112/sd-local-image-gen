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

// Poll /health forever WHILE the backend process is alive. Resolve true on
// the first 200; resolve false only if the backend process has exited (crash).
// No hard time limit — first run legitimately takes a while (downloads).
function waitForHealthOrExit(interval = 500) {
  return new Promise((resolve) => {
    const ping = () => {
      if (backend === null) return resolve(false);   // backend exited → real failure
      const req = http.get(`${BASE}/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve(true);
        else setTimeout(ping, interval);
      });
      req.on('error', () => setTimeout(ping, interval));
      req.setTimeout(2000, function () { this.destroy(); });
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

  // Show a "starting" screen immediately, then swap to the app once the
  // server is up. First run downloads engines/models, so this can take a while.
  const loading =
    `<!doctype html><meta charset="utf-8">
     <body style="margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;background:#0f0f12;color:#e9e9f1;font-family:-apple-system,'Microsoft JhengHei',sans-serif">
     <div style="font-size:18px;font-weight:700;color:#9b7bff">Amazing image Generator</div>
     <div style="font-size:14px;color:#8b8ba0">啟動中… 請稍候</div>
     <div style="font-size:12px;color:#5a5a70;max-width:420px;text-align:center;line-height:1.6">首次啟動會自動下載引擎與模型，可能需要數分鐘到數十分鐘（依網速與模型大小）。</div>
     </body>`;
  await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(loading));
  win.show();

  await win.webContents.session.clearCache();            // never show a stale cached UI
  const ok = await waitForHealthOrExit();
  if (ok) {
    await win.loadURL(`${BASE}/?v=${Date.now()}`);        // cache-bust the page load
  } else {
    const html =
      `<!doctype html><meta charset="utf-8">
       <body style="background:#0f0f12;color:#e9e9f1;font-family:-apple-system,'Microsoft JhengHei',sans-serif;padding:36px">
       <h2 style="color:#e05050">生圖伺服器啟動失敗</h2>
       <p>後端程序已結束${backendExit !== null ? `（代碼 ${backendExit}）` : ''}。下方是後端輸出，請回報給開發者：</p>
       <pre style="background:#16161f;border:1px solid #2a2a3a;border-radius:8px;padding:14px;white-space:pre-wrap;font-size:11px;max-height:62vh;overflow:auto">${backendLog.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</pre>
       </body>`;
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  }
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
