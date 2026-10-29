'use strict';

// Starts a frozen backend executable and talks to it over HTTP, then shuts it
// down. The packaging script runs this against the freshly built
// habit-quest-backend.exe, so a broken executable fails the build instead of
// shipping.
//
//     node smoke-backend.js ../desktop/backend-dist/habit-quest-backend.exe

const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const { startBackend } = require('./backend');

const binary = path.resolve(process.argv[2] || path.join(__dirname, 'backend-dist', 'habit-quest-backend.exe'));

function get(port, urlPath) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: urlPath, timeout: 5000 }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('timeout', () => req.destroy(new Error('timed out')));
    req.on('error', reject);
  });
}

(async () => {
  if (!fs.existsSync(binary)) {
    console.error(`missing backend: ${binary}`);
    process.exit(1);
  }

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hq-smoke-'));
  const dbPath = path.join(dir, 'habitquest.db');
  let backend = null;
  let failed = 0;
  const check = (name, ok, detail) => {
    console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}${detail ? ` -> ${detail}` : ''}`);
    if (!ok) failed += 1;
  };

  try {
    const started = Date.now();
    backend = await startBackend({ dbPath, projectRoot: path.dirname(binary), binary });
    check('frozen backend starts', Boolean(backend.port), `${backend.port} in ${Date.now() - started} ms`);

    const health = await get(backend.port, '/api/health');
    check('health endpoint answers', health.status === 200, health.body.slice(0, 60));

    const state = await get(backend.port, '/api/state');
    check('state endpoint answers', state.status === 200 && 'has_character' in JSON.parse(state.body));

    const index = await get(backend.port, '/');
    check('front end is bundled', index.status === 200 && /Habit Quest/.test(index.body),
      `${index.status}, ${index.body.length} bytes`);

    const created = await get(backend.port, '/api/health');
    check('still alive after requests', created.status === 200);
  } catch (err) {
    check('frozen backend starts', false, err.message);
  } finally {
    if (backend) await backend.stop().catch(() => {});
    fs.rmSync(dir, { recursive: true, force: true });
  }

  console.log(failed === 0 ? '\nbackend smoke test passed' : `\n${failed} backend check(s) failed`);
  process.exit(failed === 0 ? 0 : 1);
})();
