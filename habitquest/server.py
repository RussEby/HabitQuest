"""HTTP wiring: serve the JSON API under /api and the frontend from /static.

Uses only the standard library so ``python app.py`` always works with no
installs. Loopback-only by default.
"""

from __future__ import annotations

import json
import mimetypes
import posixpath
import re
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .api import Api, dumps
from .store import Game

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Requests are JSON, except an alarm upload: a 2 MB audio file arrives base64
# encoded (about 2.8 MB), so the ceiling has to clear that.
MAX_BODY = 4 * 1024 * 1024


def export_filename(doc: dict) -> str:
    """A readable, ASCII-only file name for a downloaded hero sheet."""
    character = doc.get("character") or {}
    name = str(character.get("name") or "hero")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "hero"
    day = str(doc.get("exported_at") or "")[:10] or date.today().isoformat()
    return f"habit-quest-{slug}-{day}.json"


class Handler(BaseHTTPRequestHandler):
    server_version = "HabitQuest/1.0"
    protocol_version = "HTTP/1.1"

    api: Api
    static_dir: Path = STATIC_DIR

    # -- helpers ----------------------------------------------------------
    def log_message(self, fmt, *args):  # keep the console tidy
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload) -> None:
        self._send(status, dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            # The body stays unread, so this connection must not be reused for
            # another request; the handler still answers with a clean 400.
            self.close_connection = True
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # -- verbs ------------------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}

        if path.startswith("/api"):
            if path == "/api/sound":
                # The uploaded alarm is served as audio bytes, not JSON.
                if method not in ("GET", "HEAD"):
                    self._send_json(405, {"ok": False, "error": "Method not allowed"})
                    return
                sound = self.api.game.alarm_sound()
                if sound is None:
                    self._send_json(404, {"ok": False, "error": "No custom alarm sound."})
                    return
                data, ctype = sound
                self._send(200, data, ctype, {"Accept-Ranges": "none"})
                return
            if path == "/api/character/export":
                # A file download, so the browser is told what to call it.
                status, payload = self.api.handle(method, path, query, {})
                if status != 200:
                    self._send_json(status, payload)
                    return
                self._send(status, dumps(payload).encode("utf-8"),
                           "application/json; charset=utf-8",
                           {"Content-Disposition":
                            f'attachment; filename="{export_filename(payload)}"'})
                return
            body = self._read_body() if method in ("POST", "PUT", "PATCH", "DELETE") else {}
            status, payload = self.api.handle(method, path, query, body)
            self._send_json(status, payload)
            return

        if method not in ("GET", "HEAD"):
            self._send_json(405, {"ok": False, "error": "Method not allowed"})
            return
        self._serve_static(path)

    # -- static -----------------------------------------------------------
    def _serve_static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        relative = posixpath.normpath(relative)
        if relative.startswith("..") or relative.startswith("/"):
            self._send_json(403, {"ok": False, "error": "Forbidden"})
            return

        target = (self.static_dir / relative).resolve()
        try:
            target.relative_to(self.static_dir.resolve())
        except ValueError:
            self._send_json(403, {"ok": False, "error": "Forbidden"})
            return

        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            # Single-page app: unknown paths fall back to the shell.
            fallback = self.static_dir / "index.html"
            if fallback.is_file() and "." not in posixpath.basename(relative):
                target = fallback
            else:
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return

        ctype, _ = mimetypes.guess_type(str(target))
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in (
            "application/javascript", "application/json", "image/svg+xml"
        ):
            ctype += "; charset=utf-8"
        try:
            body = target.read_bytes()
        except OSError:
            self._send(500, b"Could not read asset", "text/plain; charset=utf-8")
            return
        self._send(200, body, ctype)


def build_server(game: Game, host: str = "127.0.0.1", port: int = 8765,
                 verbose: bool = False, static_dir: Path | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"api": Api(game),
                                                "static_dir": static_dir or STATIC_DIR})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    httpd.verbose = verbose  # type: ignore[attr-defined]
    return httpd


def safe_print(text: str) -> None:
    """Print without dying on a legacy console encoding (Windows cp1252) and
    without being swallowed by block buffering when output is redirected."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"), flush=True)


def banner_text(url: str) -> str:
    return (
        "\n"
        "  ==============================================\n"
        "                H A B I T   Q U E S T\n"
        "  ==============================================\n"
        f"   Your adventure is running at:  {url}\n"
        "   Press Ctrl+C to stop.\n"
        "  ==============================================\n"
    )


def serve(game: Game, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          verbose: bool = False) -> None:
    httpd = build_server(game, host, port, verbose)
    url = f"http://{host}:{port}/"
    banner = banner_text(url)
    if sys.stdout.encoding and "utf" in sys.stdout.encoding.lower():
        banner = (
            "\n  \u2554" + "\u2550" * 46 + "\u2557\n"
            "  \u2551            H A B I T   Q U E S T             \u2551\n"
            "  \u2560" + "\u2550" * 46 + "\u2563\n"
            f"  \u2551  Your adventure is running at:               \u2551\n"
            f"  \u2551  {url:<42}\u2551\n"
            "  \u2551  Press Ctrl+C to stop.                       \u2551\n"
            "  \u255a" + "\u2550" * 46 + "\u255d\n"
        )
    safe_print(banner)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        safe_print("\n  Saving your character... goodbye, adventurer.")
    finally:
        httpd.shutdown()
        httpd.server_close()
        game.close()
