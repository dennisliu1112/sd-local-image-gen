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
// We no longer ship a PyInstaller-packed server.exe (it tripped antivirus
// heuristics and got quarantined). Instead we bundle an embedded CPython
// runtime + the server.py source and run `python.exe server.py` directly.
// python.exe is signed by the Python Software Foundation, so AV leaves it
// alone; server.py is plain source, nothing to flag.
function backendCmd() {
  if (app.isPackaged) {
    const res = process.resourcesPath;
    const script = path.join(res, 'backend', 'server.py');
    const cwd = path.join(res, 'backend');
    if (process.platform === 'win32') {
      const py = path.join(res, 'python', 'python.exe');
      return { cmd: py, args: [script], cwd };
    }
    // macOS / Linux packaged: embedded python lives in python/bin/python3
    const py = path.join(res, 'python', 'bin', 'python3');
    return { cmd: py, args: [script], cwd };
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
// Where the backend keeps user data (models, engines, config, logs). Kept
// OUTSIDE the install payload so app updates/reinstalls never wipe the user's
// downloaded models. Windows uses a fixed ASCII path; other platforms use the
// per-user app-data dir. In dev (not packaged) we leave it unset so the
// backend keeps data next to the source.
function dataDir() {
  if (!app.isPackaged) return null;
  return process.platform === 'win32'
    ? 'C:\\AiG-data'
    : path.join(app.getPath('userData'), 'data');
}

function startBackend() {
  const { cmd, args, cwd } = backendCmd();
  logBackend(`launching: ${cmd}\ncwd: ${cwd}\n`);
  const env = { ...process.env, PORT: String(PORT), ELECTRON_PID: String(process.pid) };
  const dd = dataDir();
  if (dd) env.AIG_DATA_DIR = dd;
  try {
    backend = spawn(cmd, args, {
      cwd,
      env,
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
    // Backend died (not a normal quit) → replace the UI with a diagnostic page.
    if (!quitting && win && !win.isDestroyed()) showBackendError();
  });
}

function showBackendError() {
  const html =
    `<!doctype html><meta charset="utf-8">
     <body style="background:#0f0f12;color:#e9e9f1;font-family:-apple-system,'Microsoft JhengHei',sans-serif;padding:36px">
     <h2 style="color:#e05050">生圖伺服器啟動失敗</h2>
     <p>後端程序已結束${backendExit !== null ? `（代碼 ${backendExit}）` : ''}。下方是後端輸出，請回報給開發者：</p>
     <pre style="background:#16161f;border:1px solid #2a2a3a;border-radius:8px;padding:14px;white-space:pre-wrap;font-size:11px;max-height:62vh;overflow:auto">${backendLog.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</pre>
     </body>`;
  win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
}

// Path to the UI shell on disk. We load this directly so the window shows the
// real interface instantly — the page itself polls the backend and shows its
// own "啟動中…" / first-run setup state. No blocking loading screen.
function indexPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'static', 'index.html')
    : path.join(__dirname, '..', 'windows-app', 'static', 'index.html');
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

  // Load the real UI from disk immediately — no waiting on the backend. The
  // page shows a "啟動中…" status and opens its own setup screen as soon as
  // the backend reports what (if anything) needs downloading.
  await win.loadFile(indexPath());
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
