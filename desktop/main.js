'use strict';

/**
 * Habit Quest, as a desktop app.
 *
 * The window loads the Python server's own URL, so the front end and the API
 * share an origin and nothing about the web app has to change: no CORS, no
 * proxying, no second copy of the UI. The renderer stays a plain web page with
 * no Node access at all.
 */

const { app, BrowserWindow, dialog, shell } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const { startBackend } = require('./backend');

// In a packaged build the Python sources and the static folder are copied next
// to the executable (resources/habitquest, resources/static), so that is the
// working directory the backend is started from. From source it is the repo.
const PROJECT_ROOT = app.isPackaged
  ? process.resourcesPath
  : path.resolve(__dirname, '..');
// Matches --bg-1 in static/styles.css, so there is no flash before paint.
const BACKGROUND = '#0b0a14';

let backend = null;
let mainWindow = null;
let shuttingDown = false;

/** A packaged build ships the Python core as one executable, if it exists. */
function bundledBackend() {
  if (!app.isPackaged) return null;
  const name = process.platform === 'win32' ? 'habit-quest-backend.exe' : 'habit-quest-backend';
  const candidate = path.join(process.resourcesPath, 'backend', name);
  return fs.existsSync(candidate) ? candidate : null;
}

function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 880,
    minWidth: 360,
    minHeight: 540,
    title: 'Habit Quest',
    backgroundColor: BACKGROUND,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });

  // Show the frame only once there is something to show.
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  const origin = new URL(url).origin;

  // The window is the app, not a browser: anything leaving the local server
  // goes to the user's real browser instead of replacing the app.
  mainWindow.webContents.on('will-navigate', (event, target) => {
    let targetOrigin = null;
    try { targetOrigin = new URL(target).origin; } catch (_) { /* malformed */ }
    if (targetOrigin !== origin) {
      event.preventDefault();
      if (targetOrigin && /^https?:$/.test(new URL(target).protocol)) shell.openExternal(target);
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
    return { action: 'deny' };
  });

  mainWindow.loadURL(url);
  mainWindow.on('closed', () => { mainWindow = null; });
}

async function boot() {
  const dbPath = path.join(app.getPath('userData'), 'habitquest.db');
  const bundled = bundledBackend();

  try {
    backend = await startBackend({
      dbPath,
      projectRoot: PROJECT_ROOT,
      binary: bundled || undefined,
      onLog: (line) => console.log('[habit-quest]', line),
      onExit: (code, signal) => {
        if (shuttingDown) return;
        dialog.showErrorBox(
          'Habit Quest stopped',
          `The game server exited unexpectedly (${signal || code}). Your save is in:\n${dbPath}`,
        );
        app.quit();
      },
    });
  } catch (err) {
    dialog.showErrorBox('Habit Quest could not start', err.message);
    app.quit();
    return;
  }

  createWindow(backend.url);
}

if (!app.requestSingleInstanceLock()) {
  // A second copy would fight the first over the same save file.
  app.quit();
} else {
  app.setAppUserModelId('com.habitquest.desktop');

  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(boot);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && backend) createWindow(backend.url);
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  // Stop the backend before the app goes away, so the save file is closed
  // cleanly rather than torn down with the process.
  app.on('before-quit', (event) => {
    if (!backend || shuttingDown) return;
    event.preventDefault();
    shuttingDown = true;
    const server = backend;
    backend = null;
    server.stop().catch(() => {}).finally(() => app.quit());
  });
}
