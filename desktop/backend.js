'use strict';

/**
 * Starts the Python core and waits until it actually answers requests.
 *
 * No Electron imports here on purpose: this module can be exercised with plain
 * node, which is how the handshake and shutdown paths are tested.
 */

const { spawn } = require('node:child_process');
const http = require('node:http');

const READY_TIMEOUT_MS = 30000;
const HEALTH_TIMEOUT_MS = 5000;
const STOP_TIMEOUT_MS = 4000;

function defaultCandidates() {
  if (process.env.HABITQUEST_PYTHON) return [process.env.HABITQUEST_PYTHON];
  // Windows installs the launcher as `python`; POSIX systems often only have
  // `python3` on PATH.
  return process.platform === 'win32' ? ['python'] : ['python3', 'python'];
}

function request(port, path) {
  return new Promise((resolve, reject) => {
    const req = http.get(
      { host: '127.0.0.1', port, path, timeout: 2000 },
      (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, body }));
      },
    );
    req.on('timeout', () => req.destroy(new Error('request timed out')));
    req.on('error', reject);
  });
}

function stopChild(child, markStopping) {
  if (child.exitCode !== null || child.signalCode !== null) {
    markStopping();
    return Promise.resolve();
  }
  markStopping();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve();
    };
    child.once('exit', finish);
    try {
      // Closing the pipe is the portable shutdown request: the launcher sees
      // EOF, closes the socket and the save file, and exits. SIGTERM would be
      // an immediate kill on Windows.
      child.stdin.end('quit\n');
    } catch (_) {
      try { child.kill(); } catch (_) { /* already gone */ }
    }
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch (_) { /* nothing left to kill */ }
      finish();
    }, STOP_TIMEOUT_MS);
  });
}

function launch({ candidate, dbPath, projectRoot, frozen, onLog, onExit }) {
  return new Promise((resolve, reject) => {
    // A frozen backend is the program itself, so it takes only its own flags;
    // a source checkout needs Python to run the module.
    const args = frozen
      ? ['--db', dbPath]
      : ['-m', 'habitquest.desktop', '--db', dbPath];

    let child;
    try {
      child = spawn(candidate, args, {
        cwd: projectRoot,
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
        env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
      });
    } catch (err) {
      reject(err);
      return;
    }

    let settled = false;
    let stopping = false;
    let pending = '';
    let stderr = '';
    let ready = false;

    const timer = setTimeout(() => {
      fail(new Error(
        `The Habit Quest server did not answer within ${READY_TIMEOUT_MS / 1000} seconds.`
        + (stderr ? `\n\n${stderr.trim().slice(-800)}` : ''),
      ));
    }, READY_TIMEOUT_MS);

    function fail(err) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { child.kill(); } catch (_) { /* already gone */ }
      reject(err);
    }

    // Writing to a backend that has already exited would otherwise raise an
    // unhandled EPIPE and take the app down with it.
    child.stdin.on('error', () => {});

    child.on('error', (err) => {
      // ENOENT means this interpreter name does not exist; the caller retries.
      fail(err);
    });

    child.on('exit', (code, signal) => {
      if (!settled) {
        fail(new Error(
          `The Habit Quest server stopped before it was ready (${signal || code}).`
          + (stderr ? `\n\n${stderr.trim().slice(-800)}` : ''),
        ));
        return;
      }
      if (!stopping && onExit) onExit(code, signal);
    });

    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
      const line = String(chunk).trim();
      if (line) onLog?.(line);
    });

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      pending += chunk;
      let index;
      while ((index = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, index).trim();
        pending = pending.slice(index + 1);
        if (!line) continue;
        if (ready) { onLog?.(line); continue; }
        let info = null;
        try { info = JSON.parse(line); } catch (_) { /* ordinary log line */ }
        if (info && info.port) {
          ready = true;
          becomeReady(Number(info.port));
        } else {
          onLog?.(line);
        }
      }
    });

    function becomeReady(port) {
      const url = `http://127.0.0.1:${port}/`;
      const deadline = Date.now() + HEALTH_TIMEOUT_MS;

      const poll = () => {
        request(port, '/api/health').then((res) => {
          if (settled) return;
          if (res.status === 200) {
            settled = true;
            clearTimeout(timer);
            resolve({
              url,
              port,
              stop: () => stopChild(child, () => { stopping = true; }),
            });
            return;
          }
          retry();
        }).catch(retry);
      };

      const retry = () => {
        if (settled) return;
        if (Date.now() > deadline) {
          fail(new Error('The Habit Quest server is listening but not answering its health check.'));
          return;
        }
        setTimeout(poll, 100);
      };

      poll();
    }
  });
}

/**
 * Start the backend.
 *
 * @param {object} options
 * @param {string} options.dbPath       Where the save file lives.
 * @param {string} options.projectRoot  Working directory for `python -m ...`.
 * @param {string} [options.python]     Explicit interpreter, skipping detection.
 * @param {string} [options.binary]     Standalone backend executable instead.
 * @param {(line: string) => void} [options.onLog]
 * @param {(code: number|null, signal: string|null) => void} [options.onExit]
 * @returns {Promise<{url: string, port: number, stop: () => Promise<void>}>}
 */
async function startBackend(options) {
  if (options.binary) {
    if (!require('node:fs').existsSync(options.binary)) {
      throw new Error(`The bundled backend is missing: ${options.binary}`);
    }
    return launch({ ...options, candidate: options.binary, frozen: true });
  }

  const candidates = options.python ? [options.python] : defaultCandidates();
  const tried = [];
  for (const candidate of candidates) {
    try {
      return await launch({ ...options, candidate });
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
      tried.push(candidate);
    }
  }

  throw new Error(
    `Could not find a Python interpreter (tried ${tried.join(', ')}).\n\n`
    + 'Habit Quest needs Python 3.10 or newer. Install it, or point the '
    + 'HABITQUEST_PYTHON environment variable at your interpreter.',
  );
}

module.exports = { startBackend, defaultCandidates };
