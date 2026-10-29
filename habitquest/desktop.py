"""Desktop entry point: the same server, launched by the Electron shell.

``app.py`` is built for humans -- it prints a banner and opens a browser. The
desktop app needs the opposite: pick a free port, say which one on stdout, and
keep quiet. The Electron main process reads that one JSON line, then points a
window at the URL.

    python -m habitquest.desktop --db <path>

Binding port 0 lets the OS choose a port that is actually free, so the app never
collides with something else already using 8765.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import types
from http.server import ThreadingHTTPServer
from pathlib import Path

from .server import build_server
from .store import Game


def _watch_stdin(stop: threading.Event) -> None:
    """Treat the parent's pipe as a lifeline.

    Closing it is how the shell asks us to quit on every platform (SIGTERM is
    a hard kill on Windows), and it also means an Electron crash can never
    leave an orphaned server behind: the pipe closes, we exit.
    """
    try:
        for line in sys.stdin:
            if line.strip().lower() in ("quit", "stop", "exit"):
                break
    except (OSError, ValueError):  # pragma: no cover - closed mid-read
        pass
    stop.set()


def _quiet_client_disconnects(server, request, client_address) -> None:
    """Closing the window resets its keep-alive sockets; that is not an error.

    Without this, socketserver prints a traceback for every connection the
    renderer drops on quit, straight into the desktop app's console.
    """
    exc = sys.exc_info()[1]
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return
    ThreadingHTTPServer.handle_error(server, request, client_address)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="habit-quest-desktop")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=0, help="port to serve on (default: 0 = any free port)")
    parser.add_argument("--db", default="habitquest.db", help="SQLite save file location")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    db_path = Path(args.db).expanduser()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Could not create the save folder {db_path.parent}: {exc}", file=sys.stderr)
        return 1

    game = Game(str(db_path))
    try:
        httpd = build_server(game, host=args.host, port=args.port)
    except OSError as exc:
        game.close()
        print(f"Could not bind {args.host}:{args.port} -> {exc}", file=sys.stderr)
        return 1

    httpd.handle_error = types.MethodType(_quiet_client_disconnects, httpd)

    host, port = httpd.server_address[:2]
    stop = threading.Event()

    def request_stop(signum=None, frame=None):
        stop.set()

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):  # pragma: no cover - exotic platforms
                pass

    # serve_forever() must not run on the main thread: shutdown() is called from
    # here, and calling it from the serving thread would deadlock.
    worker = threading.Thread(target=httpd.serve_forever, name="habitquest-http", daemon=True)
    worker.start()

    if not sys.stdin.isatty():
        threading.Thread(target=_watch_stdin, args=(stop,), name="habitquest-stdin", daemon=True).start()

    # The handshake line. Everything before this on stdout is ignored by the
    # shell; everything after is just log noise.
    print(json.dumps({"ok": True, "url": f"http://{host}:{port}/", "port": port}), flush=True)

    try:
        stop.wait()
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        pass
    finally:
        httpd.shutdown()
        worker.join(timeout=5)
        httpd.server_close()
        game.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
