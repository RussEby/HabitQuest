#!/usr/bin/env python3
"""Habit Quest - live your habits, level your hero.

    python app.py                 # play (opens your browser)
    python app.py --demo          # start with a month of history pre-loaded
    python app.py --port 9000     # different port
    python app.py --no-browser    # just run the server

No third-party packages required. Python 3.10+.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from habitquest.server import serve
from habitquest.store import Game

DEFAULT_DB = Path(__file__).resolve().parent / "habitquest.db"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="habit-quest",
        description="An RPG habit tracker: do the habit, earn the gold, level the hero.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port to serve on (default: 8765)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite save file location")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--demo", action="store_true",
                        help="seed a demo character with a month of quest history")
    parser.add_argument("--reset", action="store_true", help="wipe the save file before starting")
    parser.add_argument("--verbose", action="store_true", help="log every HTTP request")
    return parser.parse_args(argv)


def configure_console() -> None:
    """Make emoji and box-drawing characters safe on legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - exotic consoles
            pass


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = parse_args(argv)

    if sys.version_info < (3, 10):
        print("Habit Quest needs Python 3.10 or newer.", file=sys.stderr)
        return 1

    game = Game(args.db)
    if args.reset:
        game.reset()
        print("  Save file wiped. A fresh legend begins.")
    if args.demo:
        game.seed_demo()

    try:
        serve(game, host=args.host, port=args.port,
              open_browser=not args.no_browser, verbose=args.verbose)
    except OSError as exc:
        print(f"\n  Could not start the server on {args.host}:{args.port} -> {exc}", file=sys.stderr)
        print("  Try a different port, e.g. python app.py --port 8899", file=sys.stderr)
        return 1
    finally:
        game.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
