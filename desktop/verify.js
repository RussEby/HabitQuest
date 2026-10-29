'use strict';

// Verifies the desktop shell without a visible window: start the backend the
// same way main.js does, load the real app into a BrowserWindow, and check that
// the renderer can reach the API from its own origin.
//
//     npm run verify

const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { startBackend } = require('./backend');

app.disableHardwareAcceleration();

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok, detail });
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}${detail ? ` -> ${detail}` : ''}`);
}

app.whenReady().then(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hq-verify-'));
  let backend = null;
  let win = null;

  try {
    backend = await startBackend({
      dbPath: path.join(dir, 'habitquest.db'),
      projectRoot: path.resolve(__dirname, '..'),
    });

    win = new BrowserWindow({
      show: false,
      width: 1200,
      height: 800,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    });

    await win.loadURL(backend.url);
    const webContents = win.webContents;

    const title = await webContents.executeJavaScript('document.title');
    check('the app loads in the window', /habit quest/i.test(title), title);

    const origin = await webContents.executeJavaScript('location.origin');
    check('the page is served by the backend', origin === backend.url.replace(/\/$/, ''), origin);

    const sheets = await webContents.executeJavaScript('Array.from(document.styleSheets).length');
    check('stylesheet applied', sheets > 0, `${sheets} sheet(s)`);

    const buttons = await webContents.executeJavaScript("document.querySelectorAll('button').length");
    check('interface rendered', buttons > 0, `${buttons} button(s)`);

    // The whole point of loading the server's URL: same-origin API access.
    const state = await webContents.executeJavaScript("fetch('/api/state').then(r => r.json())");
    check('renderer can read the API', state && 'has_character' in state, Object.keys(state || {}).join(', '));

    const created = await webContents.executeJavaScript(
      "fetch('/api/tasks', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
      + "body: JSON.stringify({name: 'Verify from renderer', mode: 'pomodoro'})}).then(r => r.json())",
    );
    check('renderer can write through the API', created && created.ok === true,
      created && created.task ? created.task.name : JSON.stringify(created));
  } catch (err) {
    check('shell boots', false, err.message);
  } finally {
    if (win && !win.isDestroyed()) win.destroy();
    if (backend) await backend.stop().catch(() => {});
    fs.rmSync(dir, { recursive: true, force: true });
  }

  const failed = checks.filter((c) => !c.ok).length;
  console.log(failed === 0
    ? `\n${checks.length}/${checks.length} checks passed`
    : `\n${failed} of ${checks.length} checks failed`);
  app.exit(failed === 0 ? 0 : 1);
});
