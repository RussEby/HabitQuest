"""SQLite persistence and game-state assembly.

``Game`` owns one connection guarded by a re-entrant lock so it is safe behind
the threaded HTTP server. Every public method that mutates state commits before
returning, and every method that reads returns plain JSON-ready structures.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__ as APP_VERSION
from . import data as D
from . import engine as E

SCHEMA_VERSION = 7

# Columns added after the first release. ``_migrate`` adds any that are missing
# so an existing save keeps working without being rebuilt.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "character": {"hp": "INTEGER NOT NULL DEFAULT 0"},
    "tasks": {
        "mode": "TEXT NOT NULL DEFAULT 'instant'",
        "duration_minutes": "INTEGER NOT NULL DEFAULT 0",
        "sessions_won": "INTEGER NOT NULL DEFAULT 0",
        "sessions_lost": "INTEGER NOT NULL DEFAULT 0",
        "pomodoro_sessions": "INTEGER NOT NULL DEFAULT 0",
        "break_minutes": "INTEGER NOT NULL DEFAULT 0",
        # ISO weekday numbers the quest is available on; '' means every day.
        "days": "TEXT NOT NULL DEFAULT ''",
        # How many days an occurrence stays finishable, counting its start day.
        # 1 means it has to be done the day it opens.
        "window_days": "INTEGER NOT NULL DEFAULT 1",
        # How many occurrences the quest owes before it archives itself. 0 means
        # ongoing - it repeats until the player deletes or archives it.
        "recurrences": "INTEGER NOT NULL DEFAULT 0",
        "recurrences_done": "INTEGER NOT NULL DEFAULT 0",
        "archived_at": "TEXT",
        "archive_reason": "TEXT NOT NULL DEFAULT ''",
    },
    "sessions": {
        "pomodoro_phase": "TEXT NOT NULL DEFAULT 'pomodoro'",
        "pomodoro_completed": "INTEGER NOT NULL DEFAULT 0",
        "pomodoro_target": "INTEGER NOT NULL DEFAULT 0",
        # Seconds left on the clock while the timer is paused. Above zero means
        # the countdown is frozen; the row itself may be active or paused.
        "paused_seconds": "INTEGER NOT NULL DEFAULT 0",
    },
    "completions": {
        "hp_delta": "INTEGER NOT NULL DEFAULT 0",
        # The quest's mode at the moment it was completed, so achievements can
        # tell an instant tick from a timed session.
        "mode": "TEXT NOT NULL DEFAULT 'instant'",
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS character (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    name              TEXT    NOT NULL,
    archetype         TEXT    NOT NULL,
    xp                INTEGER NOT NULL DEFAULT 0,
    coins             INTEGER NOT NULL DEFAULT 0,
    coins_earned      INTEGER NOT NULL DEFAULT 0,
    stats             TEXT    NOT NULL DEFAULT '{}',
    total_completions INTEGER NOT NULL DEFAULT 0,
    day_streak        INTEGER NOT NULL DEFAULT 0,
    best_day_streak   INTEGER NOT NULL DEFAULT 0,
    last_active_day   TEXT,
    created_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    stat          TEXT    NOT NULL DEFAULT 'str',
    xp            INTEGER NOT NULL DEFAULT 5,
    coins         INTEGER NOT NULL DEFAULT 5,
    icon          TEXT    NOT NULL DEFAULT '📚',
    color         TEXT    NOT NULL DEFAULT '#f59e0b',
    difficulty    TEXT    NOT NULL DEFAULT 'easy',
    streak        INTEGER NOT NULL DEFAULT 0,
    best_streak   INTEGER NOT NULL DEFAULT 0,
    completions   INTEGER NOT NULL DEFAULT 0,
    last_completed TEXT,
    created_at    TEXT    NOT NULL,
    archived      INTEGER NOT NULL DEFAULT 0,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    mode            TEXT    NOT NULL DEFAULT 'instant',
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    sessions_won    INTEGER NOT NULL DEFAULT 0,
    sessions_lost   INTEGER NOT NULL DEFAULT 0,
    pomodoro_sessions INTEGER NOT NULL DEFAULT 0,
    break_minutes    INTEGER NOT NULL DEFAULT 0,
    days             TEXT    NOT NULL DEFAULT '',
    window_days      INTEGER NOT NULL DEFAULT 1,
    recurrences      INTEGER NOT NULL DEFAULT 0,
    recurrences_done INTEGER NOT NULL DEFAULT 0,
    archived_at      TEXT,
    archive_reason   TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS completions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL,
    ts         TEXT    NOT NULL,
    day        TEXT    NOT NULL,
    xp         INTEGER NOT NULL DEFAULT 0,
    coins      INTEGER NOT NULL DEFAULT 0,
    multiplier REAL    NOT NULL DEFAULT 1.0,
    hp_delta   INTEGER NOT NULL DEFAULT 0,
    mode       TEXT    NOT NULL DEFAULT 'instant'
);
CREATE INDEX IF NOT EXISTS idx_completions_day ON completions(day);
CREATE INDEX IF NOT EXISTS idx_completions_task ON completions(task_id);

-- A skipped quest was due and deliberately left alone for a reason outside the
-- hero's control. It earns nothing, but the day behaves exactly like a day the
-- quest was never scheduled on, so streaks survive it.
CREATE TABLE IF NOT EXISTS skips (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    day     TEXT    NOT NULL,
    ts      TEXT    NOT NULL,
    reason  TEXT    NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skips_task_day ON skips(task_id, day);
CREATE INDEX IF NOT EXISTS idx_skips_day ON skips(day);

CREATE TABLE IF NOT EXISTS sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           INTEGER NOT NULL,
    mode              TEXT    NOT NULL,
    started_at        TEXT    NOT NULL,
    ends_at           TEXT    NOT NULL,
    finished_at       TEXT,
    duration_seconds  INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds   INTEGER NOT NULL DEFAULT 0,
    remaining_seconds INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'active',
    xp                INTEGER NOT NULL DEFAULT 0,
    coins             INTEGER NOT NULL DEFAULT 0,
    damage            INTEGER NOT NULL DEFAULT 0,
    wounded           INTEGER NOT NULL DEFAULT 0,
    paused_seconds    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS inventory (
    item_id     TEXT PRIMARY KEY,
    acquired_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipped (
    slot    TEXT PRIMARY KEY,
    item_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS achievements (
    id          TEXT PRIMARY KEY,
    unlocked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   TEXT NOT NULL,
    day  TEXT NOT NULL,
    kind TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '✨',
    text TEXT NOT NULL
);
"""

STARTER_TASKS = [
    {"name": "Drink 8 glasses of water", "stat": "vit", "xp": 6, "coins": 5,
     "icon": "💧", "color": "#22d3ee", "difficulty": "easy",
     "description": "Hydration is the cheapest stat boost there is."},
    {"name": "Move your body for 20 minutes", "stat": "str", "xp": 12, "coins": 10,
     "icon": "🏃", "color": "#ef4444", "difficulty": "normal",
     "description": "Walk, lift, stretch - just move."},
    {"name": "Read 10 pages", "stat": "int", "xp": 10, "coins": 8,
     "icon": "📚", "color": "#a855f7", "difficulty": "easy",
     "description": "Small pages, compounding mind."},
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_ms() -> str:
    return E.now_stamp()


def _normalise_duration(mode: str, value) -> int:
    """Minutes for a timed session; 0 for an instant quest."""
    if mode not in D.TIMED_MODES:
        return 0
    minutes = E.safe_int(value, 0) or 20
    return E.clamp(minutes, D.SESSION_MIN_MINUTES, D.SESSION_MAX_MINUTES)


def _duration_label(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes <= 0:
        return ""
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} hr" if hours == 1 else f"{hours} hr"
    return f"{hours} hr {rest} min"


def _today() -> str:
    return date.today().isoformat()


def _window_for(days, requested) -> int:
    """Clamp a finish window to a schedule whose occurrences cannot overlap.

    Raising here is the only place the rule lives, so creating, editing and the
    HTTP layer all reject the same impossible combinations. Every-day quests and
    back-to-back days leave no room at all: their window is the day itself.
    """
    width = E.clamp(E.safe_int(requested, 1), 1, 7)
    limit = E.max_window(days)
    if width <= limit:
        return width
    label = E.days_label(days)
    if limit <= 1:
        raise GameError(
            f"{label} leaves no room for a finish window - a quest that starts "
            "that often has to be finished the day it opens. Pick fewer days to "
            "give it one."
        )
    raise GameError(
        f"{label} leaves only {limit} day{'s' if limit != 1 else ''} before the next "
        f"occurrence opens, so the finish window can be at most {limit}."
    )


def _sound_magic_ok(payload: bytes, ext: str) -> bool:
    """Refuse files whose bytes are not actually audio of the claimed type."""
    if ext == "wav":
        return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WAVE"
    if ext == "mp3":
        return payload[:3] == b"ID3" or (
            len(payload) >= 2 and payload[0] == 0xFF and (payload[1] & 0xE0) == 0xE0
        )
    if ext == "ogg":
        return payload[:4] == b"OggS"
    return False


class GameError(Exception):
    """Raised for user-facing problems (bad input, not enough coins, ...)."""


class Game:
    def __init__(self, path: str = "habitquest.db"):
        self.path = str(path)
        self._lock = threading.RLock()
        self._settled: list[dict] = []
        # The missed-day notice is handed to the UI once, then forgotten.
        self._day_reckoning: dict | None = None
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # -- plumbing ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                pass

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self._conn.commit()
            self._migrate()

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> list[str]:
        """Add any missing columns to ``table``; returns the ones it added."""
        existing = {row["name"] for row in self._query(f"PRAGMA table_info({table})")}
        added = []
        for name, ddl in columns.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                added.append(name)
        return added


    def _migrate(self) -> None:
        """Bring an older save file up to date without losing the hero."""
        added_hp = "hp" in self._ensure_columns("character", ADDED_COLUMNS["character"])
        for table in ("tasks", "completions"):
            self._ensure_columns(table, ADDED_COLUMNS[table])

        if added_hp:
            # There was no health before this version, so a 0 is "not set yet",
            # not "knocked out" - fill every hero up.
            for row in self._query("SELECT id, stats, xp FROM character"):
                stats = json.loads(row["stats"] or "{}")
                level = E.level_from_xp(row["xp"])["level"]
                self._conn.execute(
                    "UPDATE character SET hp = ? WHERE id = ?",
                    (E.max_hp(stats, level), row["id"]),
                )

        self._conn.execute(
            "UPDATE tasks SET duration_minutes = 20 "
            "WHERE mode IN ('beat_clock', 'endure') AND duration_minutes <= 0"
        )
        for table, cols in {
            "tasks": {"pomodoro_sessions": "INTEGER NOT NULL DEFAULT 0",
                      "break_minutes": "INTEGER NOT NULL DEFAULT 0"},
            "sessions": {"pomodoro_phase": "TEXT NOT NULL DEFAULT 'pomodoro'",
                         "pomodoro_completed": "INTEGER NOT NULL DEFAULT 0",
                         "pomodoro_target": "INTEGER NOT NULL DEFAULT 0",
                         "paused_seconds": "INTEGER NOT NULL DEFAULT 0"},
        }.items():
            self._ensure_columns(table, cols)

        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        self._conn.commit()

    # -- pomodoro helpers ------------------------------------------------
    def _pomodoro_focus_minutes(self, task_row) -> int:
        return _normalise_duration("pomodoro", task_row["duration_minutes"])

    def _pomodoro_break_seconds(self, task_row) -> int:
        minutes = E.safe_int(task_row["break_minutes"], 0) or D.POMODORO_DEFAULT_BREAK_MINUTES
        return max(1, minutes) * 60

    def _start_pomodoro_session(self, task_row) -> dict:
        break_seconds = self._pomodoro_break_seconds(task_row)
        focus_seconds = self._pomodoro_focus_minutes(task_row) * 60
        now = _now_ms()
        char = self._character()
        cur = self._conn.execute(
            """INSERT INTO sessions
               (task_id, mode, started_at, ends_at, duration_seconds, status, wounded,
                pomodoro_phase, pomodoro_completed, pomodoro_target)
               VALUES (?, 'pomodoro', ?, ?, ?, 'active', ?,
                       'pomodoro', 0, 0)""",
            (task_row["id"], now, (datetime.now() + timedelta(seconds=focus_seconds)).isoformat(timespec="milliseconds"),
             focus_seconds, 1 if self._is_wounded(char) else 0),
        )
        self._conn.commit()
        info = D.SESSION_MODE_BY_ID["pomodoro"]
        self._log("session",
                  f"Pomodoro started: {task_row['name'][:40]} ({_duration_label(focus_seconds // 60)} focus, "
                  f"{_duration_label(break_seconds // 60)} breaks)",
                  info["icon"])
        session = self._session_dict(self._one("SELECT * FROM sessions WHERE id = ?", (cur.lastrowid,)))
        return {"ok": True, "outcome": "started", "session": session, "state": self._build_state()}

    def _active_pomodoro_session(self, task_id: int) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM sessions WHERE status = 'active' AND mode = 'pomodoro' AND task_id = ? ORDER BY id DESC LIMIT 1",
            (int(task_id),),
        )

    def _paused_pomodoro_session(self, task_id: int) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM sessions WHERE status = 'paused' AND mode = 'pomodoro' AND task_id = ? ORDER BY id DESC LIMIT 1",
            (int(task_id),),
        )

    def _pause_remaining(self, session_row: sqlite3.Row) -> int:
        """Seconds left on this phase, whether the timer is running or already paused."""
        duration = int(session_row["duration_seconds"] or 0)
        if int(session_row["paused_seconds"] or 0) > 0:
            return max(0, int(session_row["paused_seconds"]))
        elapsed = int(math.ceil(E.seconds_between(session_row["started_at"], _now_ms())))
        return max(0, duration - elapsed)

    def _resume_pomodoro_quest(self, session_row: sqlite3.Row) -> dict:
        """Pick a banked pomodoro back up where it was left."""
        task_row = self._one("SELECT * FROM tasks WHERE id = ?", (session_row["task_id"],))
        if task_row is None:
            raise GameError("That quest no longer exists.")
        duration = int(session_row["duration_seconds"] or 0)
        remaining = int(session_row["paused_seconds"] or 0)
        if remaining <= 0:
            # Paused right on the bell: restart the phase rather than resuming
            # a zero-length round that would cycle instantly.
            remaining = duration
        remaining = max(1, min(duration, remaining))
        now = _now_ms()
        started = (datetime.now() - timedelta(seconds=duration - remaining)).isoformat(
            timespec="milliseconds")
        ends = (datetime.now() + timedelta(seconds=remaining)).isoformat(timespec="milliseconds")
        self._conn.execute(
            """UPDATE sessions SET status = 'active', paused_seconds = 0,
               started_at = ?, ends_at = ?, finished_at = NULL WHERE id = ?""",
            (started, ends, session_row["id"]),
        )
        self._conn.commit()
        completed = int(session_row["pomodoro_completed"] or 0)
        self._log("session",
                  f"Pomodoro resumed on {task_row['name'][:40]} - "
                  f"{completed} round{'' if completed == 1 else 's'} already banked.",
                  "🍅")
        session = self._session_dict(
            self._one("SELECT * FROM sessions WHERE id = ?", (session_row["id"],)))
        return {"ok": True, "outcome": "resumed", "session": session,
                "state": self._build_state()}

    def _cycle_pomodoro_phase(self, session_row: sqlite3.Row) -> dict:
        """Close the current focus or break round and start the next one.

        There is no round cap: the session keeps alternating until the hero
        finishes it, so every finished round is simply banked.
        """
        task_row = self._one("SELECT * FROM tasks WHERE id = ?", (session_row["task_id"],))
        if task_row is None:
            raise GameError("That quest no longer exists.")
        completed = int(session_row["pomodoro_completed"] or 0)
        focus_seconds = self._pomodoro_focus_minutes(task_row) * 60
        break_seconds = self._pomodoro_break_seconds(task_row)
        now = _now_ms()
        if session_row["pomodoro_phase"] == "pomodoro":
            completed += 1
            phase = "break"
            seconds = break_seconds
            self._log("session",
                      f"Pomodoro round {completed} done on {task_row['name'][:40]} - break time.",
                      "🍅")
        else:
            phase = "pomodoro"
            seconds = focus_seconds
            self._log("session",
                      f"Break over - next focus round on {task_row['name'][:40]}.",
                      "☕")
        next_ends = (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")
        self._conn.execute(
            """UPDATE sessions SET pomodoro_phase = ?, pomodoro_completed = ?,
               duration_seconds = ?, started_at = ?, ends_at = ?, paused_seconds = 0
               WHERE id = ?""",
            (phase, completed, seconds, now, next_ends, session_row["id"]),
        )
        self._conn.commit()
        return self._session_dict(self._one("SELECT * FROM sessions WHERE id = ?", (session_row["id"],)))

    def _finish_pomodoro(self, session_row: sqlite3.Row) -> dict:
        """Cash in a pomodoro session: the payout follows the rounds finished."""
        task_row = self._one("SELECT * FROM tasks WHERE id = ?", (session_row["task_id"],))
        if task_row is None:
            raise GameError("That quest no longer exists.")
        completed = int(session_row["pomodoro_completed"] or 0)
        focus_seconds = self._pomodoro_focus_minutes(task_row) * 60
        now = _now_ms()

        if completed <= 0:
            # Nothing was actually focused: end the session without a reward.
            self._conn.execute(
                """UPDATE sessions SET status = 'abandoned', finished_at = ?,
                   elapsed_seconds = 0, remaining_seconds = 0 WHERE id = ?""",
                (now, session_row["id"]),
            )
            self._conn.commit()
            self._log("session",
                      f"Pomodoro stopped on {task_row['name'][:44]} - no round finished, no reward.",
                      "🏳️")
            return {"ok": True, "outcome": "abandoned", "state": self._build_state()}

        today = _today()
        char = self._character()
        is_first_today = self._one(
            "SELECT id FROM completions WHERE day = ? LIMIT 1", (today,)) is None
        streak = E.next_streak(task_row["last_completed"], today, task_row["streak"],
                               task_row["days"], self._skipped_days(task_row["id"]),
                               self._window(task_row))
        task = self._task_dict(task_row, today)
        estimate = E.safe_int(task_row["pomodoro_sessions"], 0)
        factor = self._pomodoro_reward_factor(completed)
        accuracy = self._pomodoro_estimate_multiplier(completed, estimate)
        rewards = E.compute_rewards(task, streak, is_first_today)
        rewards["xp"] = int(round(rewards["xp"] * factor * accuracy))
        rewards["coins"] = int(round(rewards["coins"] * factor * accuracy))
        rewards["pomodoro_factor"] = round(factor, 3)
        rewards["pomodoro_rounds"] = completed
        rewards["pomodoro_estimate"] = estimate
        rewards["pomodoro_accuracy"] = round(accuracy, 3)
        rewards = E.apply_wounded_penalty(rewards, self._is_wounded(char))

        self._conn.execute(
            """UPDATE sessions SET status = 'won', finished_at = ?, elapsed_seconds = ?,
               remaining_seconds = 0, paused_seconds = 0, xp = ?, coins = ?, damage = 0
               WHERE id = ?""",
            (now, int(focus_seconds * completed), int(rewards["xp"]), int(rewards["coins"]),
             session_row["id"]),
        )
        self._conn.execute(
            "UPDATE tasks SET sessions_won = sessions_won + 1 WHERE id = ?",
            (task_row["id"],),
        )
        level_up = self._apply_completion(task_row, rewards, streak, "pomodoro")

        notes = [f"{completed} round{'' if completed == 1 else 's'}"]
        if estimate > 0:
            notes.append(f"estimate was {estimate}")
        if rewards.get("wounded"):
            notes.append("wounded - half gold")
        self._log("session",
                  f"{task_row['name'][:44]} pomodoro won  ·  +{rewards['xp']} XP  ·  "
                  f"+{rewards['coins']} gold  ({', '.join(notes)})",
                  D.SESSION_MODE_BY_ID["pomodoro"]["icon"])

        unlocked = self._check_achievements()
        return {"ok": True, "outcome": "won", "rewards": rewards, "level_up": level_up,
                "unlocked": unlocked,
                "recurrence": self._recurrence_notice(task_row["id"]),
                "state": self._build_state()}

    def _pomodoro_reward_factor(self, completed: int) -> float:
        """Payout grows with the rounds actually finished, then stops growing."""
        rounds = max(0, int(completed))
        if rounds <= 0:
            return 0.0
        return min(1.0 + D.POMODORO_ROUND_BONUS * (rounds - 1), D.POMODORO_MAX_FACTOR)

    def _pomodoro_estimate_multiplier(self, completed: int, estimate: int) -> float:
        """Pay extra for finishing near the number of rounds you planned for."""
        if int(estimate) <= 0:
            return 1.0
        off_by = abs(int(completed) - int(estimate))
        bonus = max(0.0, D.POMODORO_ESTIMATE_BONUS - off_by * D.POMODORO_ESTIMATE_STEP)
        return 1.0 + bonus

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    # -- character --------------------------------------------------------
    def has_character(self) -> bool:
        with self._lock:
            return self._one("SELECT id FROM character WHERE id = 1") is not None

    def create_character(self, name: str, archetype: str, starter_tasks: bool = True) -> dict:
        name = (name or "").strip()[:32] or "Adventurer"
        if archetype not in D.ARCHETYPE_BY_ID:
            archetype = "warrior"
        base = dict(D.ARCHETYPE_BY_ID[archetype]["stats"])
        with self._lock:
            if self.has_character():
                raise GameError("A character already exists.")
            self._conn.execute(
                """INSERT INTO character
                   (id, name, archetype, xp, coins, coins_earned, stats,
                    total_completions, day_streak, best_day_streak, last_active_day,
                    created_at, hp)
                   VALUES (1, ?, ?, 0, 100, 100, ?, 0, 0, 0, NULL, ?, ?)""",
                (name, archetype, json.dumps(base), _now(), E.max_hp(base)),
            )
            # A fresh hero gets a fresh identity, even after a reset.
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('character_uid', ?)",
                (str(uuid.uuid4()),),
            )
            self._conn.commit()
            if starter_tasks:
                for i, task in enumerate(STARTER_TASKS):
                    self._insert_task(task, sort_order=i)
            self._log("create", f"{name} the {D.ARCHETYPE_BY_ID[archetype]['name']} begins the journey.",
                      D.ARCHETYPE_BY_ID[archetype]["icon"])
            return self.state()

    def _character(self) -> sqlite3.Row:
        row = self._one("SELECT * FROM character WHERE id = 1")
        if row is None:
            raise GameError("No character yet. Create one first.")
        return row

    # -- health -----------------------------------------------------------
    def _raw_stats(self, char_row: sqlite3.Row) -> dict:
        stats = json.loads(char_row["stats"] or "{}")
        archetype = D.ARCHETYPE_BY_ID.get(char_row["archetype"], D.ARCHETYPES[0])
        base = dict(archetype["stats"])
        for key in D.STAT_KEYS:
            stats.setdefault(key, base.get(key, 0))
        return {k: int(stats.get(k, 0)) for k in D.STAT_KEYS}

    def _max_hp_for(self, char_row: sqlite3.Row) -> int:
        """Maximum health includes Vitality from gear, so armour helps."""
        bonus = E.aggregate_bonuses(self.equipped_items().values())
        level = E.level_from_xp(char_row["xp"])["level"]
        return E.max_hp(E.total_stats(self._raw_stats(char_row), bonus), level)

    def _hp_for(self, char_row: sqlite3.Row) -> tuple[int, int]:
        maximum = self._max_hp_for(char_row)
        if char_row["hp"] is None:
            return maximum, maximum
        return max(0, min(int(char_row["hp"]), maximum)), maximum

    def _is_wounded(self, char_row: sqlite3.Row) -> bool:
        hp, _ = self._hp_for(char_row)
        return hp <= 0

    def _set_hp(self, value: int) -> None:
        char = self._character()
        _, maximum = self._hp_for(char)
        self._conn.execute(
            "UPDATE character SET hp = ? WHERE id = 1",
            (max(0, min(int(value), maximum)),),
        )

    def _apply_damage(self, amount: int) -> int:
        """Returns the damage actually taken."""
        char = self._character()
        hp, _ = self._hp_for(char)
        taken = min(hp, max(0, int(amount)))
        self._set_hp(hp - taken)
        return taken

    def character_meta(self) -> dict:
        row = self._character()
        archetype = D.ARCHETYPE_BY_ID.get(row["archetype"], D.ARCHETYPES[0])
        stats = json.loads(row["stats"] or "{}")
        base = dict(archetype["stats"])
        for key in D.STAT_KEYS:
            stats.setdefault(key, base.get(key, 0))

        equipped = self.equipped_items()
        bonus = E.aggregate_bonuses(equipped.values())
        level_info = E.level_from_xp(row["xp"])
        level = level_info["level"]
        hp, maximum_hp = self._hp_for(row)

        return {
            "name": row["name"],
            "archetype": archetype["id"],
            "archetype_name": archetype["name"],
            "archetype_icon": archetype["icon"],
            "archetype_color": archetype["color"],
            "xp": row["xp"],
            "coins": row["coins"],
            "coins_earned": row["coins_earned"],
            "stats": {k: int(stats.get(k, 0)) for k in D.STAT_KEYS},
            "base_stats": {k: int(base.get(k, 0)) for k in D.STAT_KEYS},
            "equip_bonus": bonus,
            "total_stats": E.total_stats(stats, bonus),
            "power": E.power_score(stats, bonus, level),
            "skill_points": E.available_skill_points(level, stats, base),
            "skill_points_spent": E.spent_skill_points(stats, base),
            "total_completions": row["total_completions"],
            "day_streak": row["day_streak"],
            "best_day_streak": row["best_day_streak"],
            "last_active_day": row["last_active_day"],
            "created_at": row["created_at"],
            "hp": hp,
            "max_hp": maximum_hp,
            "hp_pct": round(hp / maximum_hp, 4) if maximum_hp else 0.0,
            "downed": hp <= 0,
            **level_info,
        }

    def character_export(self) -> dict:
        """The hero sheet as a portable, self-describing JSON document.

        Deliberately excludes quests, the journal, sessions and achievements:
        this is the character another app can drop into a story or a fight.
        Values are a snapshot taken at export time. ``uid`` is stable across
        exports of the same hero, so an importing site can recognise a returning
        character instead of creating a duplicate.
        """
        with self._lock:
            row = self._character()
            char = self.character_meta()
            archetype = D.ARCHETYPE_BY_ID.get(row["archetype"], D.ARCHETYPES[0])
            equipped = self.equipped_items()
            equipment = {}
            for slot in D.SLOT_IDS:
                item = equipped.get(slot)
                equipment[slot] = {
                    "id": item["id"],
                    "name": item["name"],
                    "slot": item["slot"],
                    "icon": item["icon"],
                    "rarity": item["rarity"],
                    "rarity_label": D.RARITY_LABELS[item["rarity"]],
                    "level_req": item["level_req"],
                    "price": item["price"],
                    "bonus": {k: int(v) for k, v in item["bonus"].items()},
                    "bonus_text": "  ".join(
                        f"+{v} {D.STAT_ABBR[k]}" for k, v in item["bonus"].items()
                    ),
                    "description": item["desc"],
                } if item else None

            return {
                "format": D.EXPORT_FORMAT,
                "format_version": D.EXPORT_FORMAT_VERSION,
                "exported_at": datetime.now().isoformat(timespec="milliseconds"),
                "source": {"app": "Habit Quest", "app_version": APP_VERSION},
                # Static reference data, repeated so the document explains itself.
                "stats_meta": [
                    {"key": k, "label": D.STAT_LABELS[k], "abbr": D.STAT_ABBR[k],
                     "blurb": D.STAT_BLURBS[k]}
                    for k in D.STAT_KEYS
                ],
                "character": {
                    "uid": self._character_uid(),
                    "name": char["name"],
                    "created_at": char["created_at"],
                    "archetype": {
                        "id": archetype["id"],
                        "name": archetype["name"],
                        "icon": archetype["icon"],
                        "color": archetype["color"],
                        "blurb": archetype["blurb"],
                        "base_stats": {k: int(v) for k, v in archetype["stats"].items()},
                    },
                    "level": char["level"],
                    "xp": char["xp"],
                    "level_floor_xp": char["level_floor_xp"],
                    "level_xp": char["level_xp"],
                    "level_xp_needed": char["level_xp_needed"],
                    "level_progress": char["level_progress"],
                    "next_level_xp": char["next_level_xp"],
                    "max_level": char["max_level"],
                    "power": char["power"],
                    "skill_points": {
                        "available": char["skill_points"],
                        "spent": char["skill_points_spent"],
                    },
                    "stats": {
                        "base": char["stats"],
                        "gear": char["equip_bonus"],
                        "total": char["total_stats"],
                    },
                    "health": {
                        "hp": char["hp"],
                        "max_hp": char["max_hp"],
                        "pct": char["hp_pct"],
                        "wounded": char["downed"],
                    },
                    "gold": {
                        "current": char["coins"],
                        "earned": char["coins_earned"],
                    },
                    "equipment": equipment,
                    "record": {
                        "quests_completed": char["total_completions"],
                        "day_streak": char["day_streak"],
                        "best_day_streak": char["best_day_streak"],
                        "last_active_day": char["last_active_day"],
                    },
                },
            }

    def _character_uid(self) -> str:
        """A persistent identity for this hero, created on first need."""
        row = self._one("SELECT value FROM meta WHERE key = 'character_uid'")
        value = str(row["value"]).strip() if row and row["value"] else ""
        if value:
            return value
        value = str(uuid.uuid4())
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('character_uid', ?)", (value,)
        )
        self._conn.commit()
        return value

    # -- occurrences and finish windows -----------------------------------
    def _window(self, row: sqlite3.Row) -> int:
        """How many days this quest's occurrence stays finishable (at least one)."""
        value = row["window_days"] if "window_days" in row.keys() else 1
        return max(1, min(7, E.safe_int(value, 1)))

    def _window_span(self, row, day: str):
        """The occurrence window covering ``day``, or ``None`` when resting."""
        return E.window_span(day, row["days"], self._window(row))

    def _closing_day(self, task_id: int, start: date, end: date) -> str | None:
        """The day a completion, skip or settled session closed an occurrence."""
        low, high = start.isoformat(), end.isoformat()
        lookups = (
            ("SELECT day FROM completions WHERE task_id = ? AND day BETWEEN ? AND ? "
             "ORDER BY day LIMIT 1", (int(task_id), low, high)),
            ("SELECT day FROM skips WHERE task_id = ? AND day BETWEEN ? AND ? "
             "ORDER BY day LIMIT 1", (int(task_id), low, high)),
            ("SELECT substr(started_at, 1, 10) AS day FROM sessions WHERE task_id = ? "
             "AND status IN ('won', 'lost') AND substr(started_at, 1, 10) BETWEEN ? AND ? "
             "ORDER BY id LIMIT 1", (int(task_id), low, high)),
        )
        for sql, args in lookups:
            found = self._one(sql, args)
            if found is not None:
                return str(found["day"])
        return None

    def _open_occurrence(self, row, day: str) -> dict | None:
        """The occurrence whose window covers ``day``, if nothing has closed it.

        A quest belongs on today's board exactly when this finds something: that
        is what "due today" means once finish windows exist. Monday's occurrence
        is still due on Tuesday, so it can be finished then.
        """
        span = self._window_span(row, day)
        if span is None:
            return None
        if self._closing_day(row["id"], span[0], span[1]) is not None:
            return None
        return {"start": span[0], "end": span[1]}

    def _not_open_message(self, row, day: str) -> str:
        """Say why a quest cannot be worked on today, without guessing."""
        info = self._occurrence_info(row, day)
        name = row["name"][:40]
        if info["window_days"] <= 1:
            # A quest with no window is simply not on today's board.
            return (f"'{name}' isn't scheduled today - it runs on "
                    f"{E.days_label(row['days'])}.")
        if info["window_closed_on"]:
            return (f"'{name}' is already closed for this occurrence - the next one "
                    f"opens on {info['window_opens_label']}."
                    if info["window_opens_label"] else
                    f"'{name}' is already closed for this occurrence.")
        if info["window_opens_label"]:
            return (f"'{name}' isn't open today - it opens again on "
                    f"{info['window_opens_label']}.")
        return f"'{name}' isn't open today."

    def _missed_occurrence(self, row, day: str) -> dict | None:
        """The newest occurrence whose window had closed by ``day`` uncompleted.

        Nothing is late while a window is still open, so a five-day quest is not
        scored as missed on the day it opened - only once the fifth day has
        passed. Walk back to the most recent window that has fully closed and ask
        whether anything was done inside it.
        """
        parsed = E.parse_date(day)
        if parsed is None:
            return None
        created = E.parse_date(str(row["created_at"] or "")[:10])
        width = self._window(row)
        for offset in range(0, 15):
            candidate = parsed - timedelta(days=offset)
            if not E.day_is_due(row["days"], candidate.isoweekday()):
                continue
            # Walking back can reach occurrences from before the quest existed.
            # A one-day window never looks back, so it keeps the old behaviour.
            if width > 1 and created is not None and candidate < created:
                return None
            end = candidate + timedelta(days=width - 1)
            if end > parsed:
                continue
            if self._closing_day(row["id"], candidate, end) is not None:
                return None
            return {"start": candidate, "end": end}
        return None

    def _occurrence_info(self, row, day: str) -> dict:
        """The finish-window facts a quest card needs to explain itself."""
        width = self._window(row)
        today = E.parse_date(day)
        span = self._window_span(row, day)
        info = {
            "window_days": width,
            "window_label": "Same day" if width == 1 else f"{width} days",
            "window_start": None,
            "window_end": None,
            "window_end_label": "",
            "window_day": 0,
            "window_closed_on": None,
            "window_skipped": False,
            "window_open": False,
            "window_opens_label": "",
        }
        if today is not None:
            for offset in range(1, 8):
                candidate = today + timedelta(days=offset)
                if E.day_is_due(row["days"], candidate.isoweekday()):
                    info["window_opens_label"] = candidate.strftime("%a %d %b")
                    break
        if span is None:
            return info
        start, end = span
        info["window_start"] = start.isoformat()
        info["window_end"] = end.isoformat()
        info["window_end_label"] = end.strftime("%a %d %b")
        if today is not None:
            info["window_day"] = (today - start).days + 1
        closed = self._closing_day(row["id"], start, end)
        info["window_closed_on"] = closed
        info["window_open"] = closed is None
        if closed is not None:
            info["window_skipped"] = self._one(
                "SELECT id FROM skips WHERE task_id = ? AND day BETWEEN ? AND ? LIMIT 1",
                (row["id"], start.isoformat(), end.isoformat())) is not None
        return info

    # -- tasks ------------------------------------------------------------
    def _task_dict(self, row: sqlite3.Row, today: str | None = None) -> dict:
        today = today or _today()
        base = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "stat": row["stat"],
            "xp": row["xp"],
            "coins": row["coins"],
            "icon": row["icon"],
            "color": row["color"],
            "difficulty": row["difficulty"],
            "streak": row["streak"],
            "best_streak": row["best_streak"],
            "completions": row["completions"],
            "last_completed": row["last_completed"],
            "created_at": row["created_at"],
            "sort_order": row["sort_order"],
            "sessions_won": int(row["sessions_won"] or 0),
            "sessions_lost": int(row["sessions_lost"] or 0),
        }
        mode = row["mode"] if "mode" in row.keys() else "instant"
        mode = mode or "instant"
        mode_info = D.SESSION_MODE_BY_ID.get(mode, D.SESSION_MODES[0])
        duration = int(row["duration_minutes"] or 0) if "duration_minutes" in row.keys() else 0
        base["mode"] = mode
        base["mode_label"] = mode_info["label"]
        base["mode_icon"] = mode_info["icon"]
        base["mode_blurb"] = mode_info["blurb"]
        base["is_timed"] = mode in D.TIMED_MODES
        base["duration_minutes"] = duration
        base["duration_label"] = _duration_label(duration)
        base["pomodoro_sessions"] = int(row["pomodoro_sessions"] or 0)
        base["pomodoro_estimate"] = int(row["pomodoro_sessions"] or 0)
        base["break_minutes"] = int(row["break_minutes"] or 0)
        # Quest schedules, in ISO weekday numbers (Mon=1 .. Sun=7).
        schedule = row["days"] if "days" in row.keys() else ""
        base["days"] = E.days_list(schedule)
        base["days_label"] = E.days_label(schedule)
        base["is_daily"] = not str(schedule or "").strip()
        # A quest can owe a set number of occurrences instead of running forever.
        target = int(row["recurrences"] or 0) if "recurrences" in row.keys() else 0
        done = int(row["recurrences_done"] or 0) if "recurrences_done" in row.keys() else 0
        base["recurrences"] = target
        base["recurrences_done"] = done
        base["recurrences_left"] = max(0, target - done) if target > 0 else 0
        base["is_recurring"] = target > 0
        base["recurrence_label"] = f"{min(done, target)} of {target}" if target > 0 else "Ongoing"
        base.update(self._occurrence_info(row, today))
        base["archived"] = bool(row["archived"])
        base["archived_at"] = row["archived_at"] if "archived_at" in row.keys() else None
        base["archive_reason"] = ((row["archive_reason"] or "")
                                  if "archive_reason" in row.keys() else "")
        # A quest paused mid-way keeps its rounds, so the card can offer a resume
        # that continues where it left off rather than starting over.
        paused_pomo = self._one(
            "SELECT pomodoro_completed FROM sessions WHERE task_id = ? AND mode = 'pomodoro' "
            "AND status = 'paused' ORDER BY id DESC LIMIT 1",
            (row["id"],),
        )
        base["pomodoro_paused"] = paused_pomo is not None
        base["pomodoro_progress"] = (
            int(paused_pomo["pomodoro_completed"] or 0) if paused_pomo else 0)
        done_today = self._one(
            "SELECT id FROM completions WHERE task_id = ? AND day = ?",
            (row["id"], today),
        ) is not None
        base["completed_today"] = done_today
        skip_row = self._one(
            "SELECT reason FROM skips WHERE task_id = ? AND day = ?",
            (row["id"], today),
        )
        base["skipped_today"] = skip_row is not None
        base["skip_reason"] = (skip_row["reason"] or "") if skip_row else ""
        today_date = E.parse_date(today) or date.today()
        # "Due today" means there is something to do about this quest today: an
        # occurrence is open, or one was closed today and belongs in the Finished
        # or Skipped section. A window closed on an earlier day is resting, even
        # though its window covered today.
        base["due_today"] = bool(base["window_open"] or base["completed_today"]
                                 or base["skipped_today"])
        base["today_weekday"] = today_date.isoweekday()
        preview_streak = E.next_streak(
            row["last_completed"], today, row["streak"], schedule,
            self._skipped_days(row["id"]), self._window(row))
        if base["skipped_today"]:
            # Today is closed: the card shows the run the skip is protecting,
            # not a run that would only exist if the quest were completed.
            preview_streak = max(1, int(row["streak"] or 0))
        rewards = E.compute_rewards(base, preview_streak, is_first_today=False)
        base["reward_xp"] = rewards["xp"]
        base["reward_coins"] = rewards["coins"]
        base["difficulty_multiplier"] = rewards["difficulty_multiplier"]
        base["stat_label"] = D.STAT_LABELS.get(row["stat"], row["stat"].upper())
        base["stat_abbr"] = D.STAT_ABBR.get(row["stat"], row["stat"].upper())
        return base

    def list_tasks(self, include_archived: bool = False) -> list[dict]:
        with self._lock:
            today = _today()
            sql = "SELECT * FROM tasks"
            if not include_archived:
                sql += " WHERE archived = 0"
            sql += " ORDER BY sort_order ASC, id ASC"
            return [self._task_dict(r, today) for r in self._query(sql)]

    def list_archived(self) -> list[dict]:
        """Quests kept aside instead of deleted, most recently archived first."""
        with self._lock:
            today = _today()
            rows = self._query(
                "SELECT * FROM tasks WHERE archived = 1 "
                "ORDER BY archived_at DESC, id DESC")
            return [self._task_dict(row, today) for row in rows]

    def _set_archived(self, task_id: int, reason: str) -> None:
        """Park a quest in the archive; the row keeps everything it earned."""
        self._conn.execute(
            "UPDATE tasks SET archived = 1, archived_at = ?, archive_reason = ? WHERE id = ?",
            (_now(), reason, int(task_id)),
        )

    def _recurrence_notice(self, task_id: int) -> dict | None:
        """How a quest's counted run stands after a completion, for the UI."""
        row = self._one(
            "SELECT recurrences, recurrences_done, archived, archive_reason "
            "FROM tasks WHERE id = ?", (int(task_id),))
        if row is None or not int(row["recurrences"] or 0):
            return None
        return {
            "target": int(row["recurrences"]),
            "done": int(row["recurrences_done"] or 0),
            "archived": bool(row["archived"]),
        }

    def _insert_task(self, payload: dict, sort_order: int | None = None) -> int:
        stat = payload.get("stat", "str")
        if stat not in D.STAT_KEYS:
            stat = "str"
        difficulty = payload.get("difficulty", "easy")
        if difficulty not in D.DIFFICULTY_BY_ID:
            difficulty = "easy"
        mode = payload.get("mode", "instant")
        if mode not in D.SESSION_MODE_BY_ID:
            mode = "instant"
        duration = _normalise_duration(mode, payload.get("duration_minutes"))
        if sort_order is None:
            row = self._one("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM tasks")
            sort_order = row["n"] if row else 0
        pomodoro_sessions = E.safe_int(payload.get("pomodoro_sessions"), 0)
        break_minutes = E.safe_int(payload.get("break_minutes"), 0)
        days = E.normalise_days(payload.get("days"))
        window_days = _window_for(days, payload.get("window_days", 1))
        recurrences = E.clamp(E.safe_int(payload.get("recurrences"), 0), 0, 200)
        cur = self._conn.execute(
            """INSERT INTO tasks
               (name, description, stat, xp, coins, icon, color, difficulty,
                streak, best_streak, completions, last_completed, created_at, archived,
                sort_order, mode, duration_minutes, pomodoro_sessions, break_minutes, days,
                window_days, recurrences, recurrences_done)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                str(payload.get("name", "")).strip()[:80] or "Untitled quest",
                str(payload.get("description", ""))[:280],
                stat,
                E.clamp(E.safe_int(payload.get("xp"), 5), 0, 500),
                E.clamp(E.safe_int(payload.get("coins"), 5), 0, 500),
                str(payload.get("icon", "📚"))[:8] or "📚",
                str(payload.get("color", "#f59e0b"))[:16],
                difficulty,
                _now(),
                sort_order,
                mode,
                duration,
                pomodoro_sessions,
                break_minutes,
                days,
                window_days,
                recurrences,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def create_task(self, payload: dict) -> dict:
        if not str(payload.get("name", "")).strip():
            raise GameError("A quest needs a name.")
        with self._lock:
            task_id = self._insert_task(payload)
            self._log("task", f"New quest tracked: {payload.get('name', '').strip()[:60]}",
                      str(payload.get("icon", "📚")))
            return self.state_for_task(task_id)

    def state_for_task(self, task_id: int) -> dict:
        row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
        if row is None:
            raise GameError("That quest no longer exists.")
        return self._task_dict(row)

    def update_task(self, task_id: int, payload: dict) -> dict:
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            # The schedule and the finish window must agree: a window that reached
            # the next occurrence would put two of them on the board at once.
            effective_days = (E.normalise_days(payload["days"]) if "days" in payload
                              else row["days"])
            _window_for(effective_days, payload.get("window_days", self._window(row)))
            fields, values = [], []
            simple = {
                "name": lambda v: str(v).strip()[:80],
                "description": lambda v: str(v)[:280],
                "icon": lambda v: str(v)[:8],
                "color": lambda v: str(v)[:16],
                "stat": lambda v: v if v in D.STAT_KEYS else row["stat"],
                "difficulty": lambda v: v if v in D.DIFFICULTY_BY_ID else row["difficulty"],
                "xp": lambda v: E.clamp(E.safe_int(v, row["xp"]), 0, 500),
                "coins": lambda v: E.clamp(E.safe_int(v, row["coins"]), 0, 500),
                "mode": lambda v: v if v in D.SESSION_MODE_BY_ID else row["mode"],
                # Without these, editing the break length or round estimate of a
                # pomodoro did nothing.
                "break_minutes": lambda v: E.clamp(E.safe_int(v, row["break_minutes"]), 0, 60),
                "pomodoro_sessions": lambda v: E.clamp(
                    E.safe_int(v, row["pomodoro_sessions"]), 0, 20),
                "days": lambda v: E.normalise_days(v),
                # How many days an occurrence stays finishable; 1 is same-day.
                "window_days": lambda v: E.clamp(E.safe_int(v, self._window(row)), 1, 7),
                # 0 keeps the quest endless; a number caps how many occurrences
                # it owes before it archives itself.
                "recurrences": lambda v: E.clamp(E.safe_int(v, row["recurrences"]), 0, 200),
            }
            for key, cast in simple.items():
                if key in payload:
                    fields.append(f"{key} = ?")
                    values.append(cast(payload[key]))
            if not fields:
                return self._task_dict(row)
            values.append(int(task_id))
            self._conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", tuple(values))

            # Keep mode and duration consistent: instant quests have no timer,
            # and a timed session always needs a length.
            fresh = self._one("SELECT mode, duration_minutes FROM tasks WHERE id = ?", (int(task_id),))
            mode = fresh["mode"]
            if mode not in D.TIMED_MODES:
                duration = 0
            elif "duration_minutes" in payload or not fresh["duration_minutes"]:
                duration = _normalise_duration(mode, payload.get("duration_minutes",
                                                                fresh["duration_minutes"]))
            else:
                duration = fresh["duration_minutes"]
            self._conn.execute("UPDATE tasks SET duration_minutes = ? WHERE id = ?", (duration, int(task_id)))
            self._conn.commit()

            # Lowering the number of times below what is already done finishes
            # the quest on the spot, so it moves to the archive instead of
            # sitting on the board waiting for a repeat it can never earn.
            fresh = self._one(
                "SELECT recurrences, recurrences_done, archived FROM tasks WHERE id = ?",
                (int(task_id),))
            if (fresh and int(fresh["recurrences"] or 0) > 0
                    and not int(fresh["archived"] or 0)
                    and int(fresh["recurrences_done"] or 0) >= int(fresh["recurrences"])):
                self._set_archived(int(task_id), "complete")
                self._conn.commit()
            return self.state_for_task(task_id)

    def archive_task(self, task_id: int) -> dict:
        """Set a quest aside without deleting it or the history it earned.

        Archived quests leave today's board completely: they are not due, they
        cannot cost health, and nothing about them is scored until the player
        re-engages them.
        """
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            if int(row["archived"] or 0):
                raise GameError("That quest is already archived.")
            stuck = self._one(
                "SELECT id FROM sessions WHERE task_id = ? "
                "AND status IN ('active', 'paused') LIMIT 1", (row["id"],))
            if stuck is not None:
                raise GameError(
                    "Finish or give up the running session before archiving that quest."
                )
            self._set_archived(row["id"], "manual")
            self._conn.commit()
            self._log("task", f"Quest archived: {row['name'][:50]}  ·  kept for later", "📦")
            return {"ok": True, "outcome": "archived", "state": self._build_state()}

    def unarchive_task(self, task_id: int) -> dict:
        """Bring an archived quest back to the board.

        A quest that already finished its counted run starts a fresh cycle, so
        re-engaging it gives the full number of occurrences again. One that was
        simply set aside picks up where it left off.
        """
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            if not int(row["archived"] or 0):
                raise GameError("That quest isn't archived.")
            target = int(row["recurrences"] or 0)
            done = int(row["recurrences_done"] or 0)
            finished = target > 0 and done >= target
            self._conn.execute(
                """UPDATE tasks SET archived = 0, archived_at = NULL, archive_reason = '',
                   recurrences_done = ? WHERE id = ?""",
                (0 if finished else done, row["id"]),
            )
            self._conn.commit()
            note = (f"fresh run of {target}" if finished else "picks up where it left off")
            self._log("task", f"Quest re-engaged: {row['name'][:50]}  ·  {note}", "🔁")
            return {"ok": True, "outcome": "unarchived", "state": self._build_state()}

    def delete_task(self, task_id: int) -> dict:
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            self._conn.execute("DELETE FROM completions WHERE task_id = ?", (int(task_id),))
            self._conn.execute("DELETE FROM sessions WHERE task_id = ?", (int(task_id),))
            self._conn.execute("DELETE FROM skips WHERE task_id = ?", (int(task_id),))
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
            self._conn.commit()
            self._log("task", f"Quest abandoned: {row['name'][:60]}", "🗑️")
            return self.state()

    # -- completing -------------------------------------------------------
    def _apply_completion(self, task_row, rewards: dict, streak: int,
                          mode: str = "instant") -> dict | None:
        """Shared bookkeeping for any success, instant or timed.

        Records the completion, moves the task's streak, pays the hero, mends a
        little health and logs a level-up. Callers log their own activity line,
        update anything session-specific, then check achievements.
        """
        today = _today()
        best_streak = max(int(task_row["best_streak"]), streak)
        # A quest with a set number of repeats counts this occurrence toward it.
        target = E.safe_int(task_row["recurrences"], 0)
        done = E.safe_int(task_row["recurrences_done"], 0)
        if target > 0:
            done = min(done + 1, target)
        self._conn.execute(
            """UPDATE tasks SET streak = ?, best_streak = ?, completions = completions + 1,
               recurrences_done = ?, last_completed = ? WHERE id = ?""",
            (streak, best_streak, done, today, task_row["id"]),
        )
        finished_run = target > 0 and done >= target
        if finished_run:
            # The last occurrence pays exactly what every other one paid. The
            # only thing that changes is that the quest leaves the board.
            self._set_archived(task_row["id"], "complete")

        char = self._character()
        level_before = E.level_from_xp(char["xp"])["level"]
        new_xp = int(char["xp"]) + int(rewards["xp"])
        day_streak = self._day_streak(char["last_active_day"], char["day_streak"], today)
        best_day = max(int(char["best_day_streak"]), day_streak)

        # A new active day lets the hero rest up; every completion mends a bit more.
        # A perfect day - nothing left due and nothing skipped by accident - is a
        # full rest, so finishing everything clears the wounds entirely.
        hp_before, maximum = self._hp_for(char)
        hp = hp_before
        if char["last_active_day"] != today:
            hp += E.rest_heal(maximum)
        hp = min(maximum, hp + E.heal_per_completion(maximum))
        perfect = self._perfect_day(today, ignoring=task_row["id"])
        if perfect:
            hp = maximum

        self._conn.execute(
            """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier, hp_delta, mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_row["id"], _now(), today, int(rewards["xp"]), int(rewards["coins"]),
             float(rewards.get("multiplier", 1.0)), hp - hp_before, mode or "instant"),
        )
        self._conn.execute(
            """UPDATE character
               SET xp = ?, coins = coins + ?, coins_earned = coins_earned + ?,
                   total_completions = total_completions + 1, day_streak = ?,
                   best_day_streak = ?, last_active_day = ?, hp = ?
               WHERE id = 1""",
            (new_xp, int(rewards["coins"]), int(rewards["coins"]), day_streak, best_day, today, hp),
        )
        self._conn.commit()

        if finished_run:
            self._log("task",
                      f"{task_row['name'][:50]} finished all {target} repeats  ·  archived",
                      "📦")

        after = E.level_from_xp(new_xp)
        if after["level"] > level_before:
            # A level-up is a full rest: the hero shakes off every wound.
            self._set_hp(self._max_hp_for(self._character()))
            self._conn.commit()
            self._log("level", f"Level up! {char['name']} reached level {after['level']}.", "⬆️")
            return {
                "from_level": level_before,
                "to_level": after["level"],
                "points": (after["level"] - level_before) * D.SKILL_POINTS_PER_LEVEL,
            }
        return None

    def complete_task(self, task_id: int) -> dict:
        with self._lock:
            self._settle_sessions()
            today = _today()
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            if int(row["archived"] or 0):
                raise GameError("That quest is archived - re-engage it from the archive first.")
            if (row["mode"] or "instant") in D.TIMED_MODES:
                raise GameError("That's a timed session - start the clock and finish it.")

            already_today = self._one(
                "SELECT id FROM completions WHERE task_id = ? AND day = ?", (row["id"], today)
            )
            if already_today:
                raise GameError("Already completed today. Come back tomorrow!")

            if self._one("SELECT id FROM skips WHERE task_id = ? AND day = ?",
                         (row["id"], today)) is not None:
                raise GameError(
                    "You skipped this quest today - no reward for it, and it is back "
                    "on its next scheduled day."
                )
            # A finish window keeps an occurrence open for several days, so the
            # question is not "is it scheduled today" but "is one open today".
            if self._open_occurrence(row, today) is None:
                raise GameError(self._not_open_message(row, today))

            char = self._character()
            is_first_today = self._one(
                "SELECT id FROM completions WHERE day = ? LIMIT 1", (today,)
            ) is None

            streak = E.next_streak(row["last_completed"], today, row["streak"], row["days"],
                                   self._skipped_days(row["id"]), self._window(row))
            task = self._task_dict(row, today)
            rewards = E.apply_wounded_penalty(
                E.compute_rewards(task, streak, is_first_today), self._is_wounded(char)
            )

            bonus_note = []
            if rewards["streak"] > 1:
                bonus_note.append(f"{rewards['streak']}-day streak ×{rewards['streak_multiplier']}")
            if rewards["daily_bonus"]:
                bonus_note.append("first quest of the day")
            if rewards.get("wounded"):
                bonus_note.append("wounded - half gold")

            level_up = self._apply_completion(row, rewards, streak, "instant")

            text = f"{row['name'][:50]} complete  ·  +{rewards['xp']} XP  ·  +{rewards['coins']} gold"
            if bonus_note:
                text += f"  ({', '.join(bonus_note)})"
            self._log("complete", text, row["icon"])

            unlocked = self._check_achievements()
            return {
                "ok": True,
                "outcome": "completed",
                "task_id": row["id"],
                "rewards": rewards,
                "level_up": level_up,
                "unlocked": unlocked,
                "recurrence": self._recurrence_notice(row["id"]),
                "state": self._build_state(),
            }

    def skip_task(self, task_id: int, reason: str = "") -> dict:
        """Close today's occurrence without a reward and without breaking anything.

        For the days a quest genuinely could not happen - travel, illness, a
        family emergency. It pays nothing and counts nothing, but the day is
        treated exactly like a day the quest was never scheduled on: the run
        picks up where it left off on the next due day. With a finish window the
        whole occurrence is closed, since half a window cannot be skipped.
        """
        with self._lock:
            self._settle_sessions()
            today = _today()
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            if int(row["archived"] or 0):
                raise GameError("That quest is archived - there is nothing to skip.")
            if self._one("SELECT id FROM completions WHERE task_id = ? AND day = ?",
                         (row["id"], today)) is not None:
                raise GameError("That quest is already done today.")
            if self._one("SELECT id FROM skips WHERE task_id = ? AND day = ?",
                         (row["id"], today)) is not None:
                raise GameError("That quest is already skipped today.")
            # Skipping closes the whole occurrence, not just today: a windowed
            # quest cannot be half-skipped and half-finished.
            if self._open_occurrence(row, today) is None:
                if self._window(row) <= 1:
                    raise GameError(
                        f"'{row['name'][:40]}' isn't scheduled today - there is "
                        "nothing to skip."
                    )
                raise GameError(
                    f"'{row['name'][:40]}' has nothing open to skip today."
                )
            if self._active_session_row(row["id"]) is not None:
                raise GameError(
                    "A session is running for that quest - finish it or give up first."
                )

            self._conn.execute(
                "INSERT INTO skips (task_id, day, ts, reason) VALUES (?, ?, ?, ?)",
                (row["id"], today, _now(), str(reason or "").strip()[:120]),
            )
            # A skipped day does not count toward a quest with a set number of
            # repeats, so the run grows by one: the quest still owes the full
            # number of real completions, just on later days.
            target = E.safe_int(row["recurrences"], 0)
            extended = 0
            if target > 0 and not int(row["archived"] or 0):
                extended = target + 1
                self._conn.execute(
                    "UPDATE tasks SET recurrences = ? WHERE id = ?",
                    (extended, row["id"]),
                )
            self._conn.commit()
            streak = int(row["streak"] or 0)
            note = (f" - {streak}-day streak kept" if streak >= 2
                    else " - no reward, no penalty")
            if extended:
                note += f" - the run now needs {extended} repeats"
            self._log("skip",
                      f"{row['name'][:50]} skipped{note}. It returns on its next day.",
                      "⏭️")
            return {"ok": True, "outcome": "skipped", "streak": streak,
                    "recurrences": extended,
                    "state": self._build_state()}

    def unskip_task(self, task_id: int) -> dict:
        """Take back a skip - the quest is due again for the rest of today."""
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            removed = self._conn.execute(
                "DELETE FROM skips WHERE task_id = ? AND day = ?",
                (row["id"], _today()),
            ).rowcount
            if not removed:
                raise GameError("That quest wasn't skipped today.")
            # Undoing the skip takes back the repeat it added to the run.
            target = E.safe_int(row["recurrences"], 0)
            if target > 0 and not int(row["archived"] or 0):
                floor = max(1, E.safe_int(row["recurrences_done"], 0) + 1)
                self._conn.execute(
                    "UPDATE tasks SET recurrences = MAX(?, recurrences - 1) WHERE id = ?",
                    (floor, row["id"]),
                )
            self._conn.commit()
            self._log("skip", f"Skip undone: {row['name'][:50]} is back on today's board.",
                      "\u21a9\ufe0f")
            return {"ok": True, "outcome": "unskipped", "state": self._build_state()}

    # -- timed sessions ---------------------------------------------------
    def _session_dict(self, row: sqlite3.Row) -> dict:
        duration = int(row["duration_seconds"] or 0)
        paused_seconds = float(row["paused_seconds"] or 0) if "paused_seconds" in row.keys() else 0.0
        elapsed = E.seconds_between(row["started_at"], _now_ms())
        remaining = max(0.0, duration - elapsed)
        if paused_seconds > 0:
            # The clock is frozen: report the moment it stopped, not the wall clock.
            remaining = paused_seconds
            elapsed = max(0.0, duration - paused_seconds)
        mode = row["mode"] or "instant"
        info = D.SESSION_MODE_BY_ID.get(mode, D.SESSION_MODES[0])
        task = self._one(
            "SELECT id, name, icon, color FROM tasks WHERE id = ?", (row["task_id"],)
        )
        pomodoro = None
        if mode == "pomodoro":
            phase = row["pomodoro_phase"] if "pomodoro_phase" in row.keys() else "pomodoro"
            pomodoro = {
                "phase": phase,
                "phase_label": "Break" if phase == "break" else "Focus",
                # The length of the phase that is running right now, focus or break.
                "current_label": _duration_label(int(round(duration / 60))),
                "completed": int(row["pomodoro_completed"] or 0),
                "target": int(row["pomodoro_target"] or 0),
            }
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "task_name": task["name"] if task else "Deleted quest",
            "task_icon": task["icon"] if task else "🗑️",
            "task_color": task["color"] if task else "#f59e0b",
            "mode": mode,
            "mode_label": info["label"],
            "mode_icon": info["icon"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ends_at": row["ends_at"],
            "duration_seconds": duration,
            "duration_minutes": int(round(duration / 60)) if duration else 0,
            "elapsed_seconds": int(elapsed),
            "remaining_seconds": int(math.ceil(remaining)),
            "ready": remaining <= 0,
            "overdue": elapsed > duration,
            "paused": paused_seconds > 0,
            "wounded_at_start": bool(row["wounded"]),
            "pomodoro": pomodoro,
        }

    def _active_session_row(self, task_id: int | None = None) -> sqlite3.Row | None:
        if task_id is None:
            return self._one(
                "SELECT * FROM sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        return self._one(
            "SELECT * FROM sessions WHERE status = 'active' AND task_id = ? ORDER BY id DESC LIMIT 1",
            (int(task_id),),
        )

    def active_session(self) -> dict | None:
        with self._lock:
            row = self._active_session_row()
            return self._session_dict(row) if row else None

    def start_session(self, task_id: int) -> dict:
        with self._lock:
            self._settle_sessions()
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            if int(row["archived"] or 0):
                raise GameError("That quest is archived - re-engage it from the archive first.")
            mode = row["mode"] or "instant"
            if mode not in D.TIMED_MODES:
                raise GameError("That quest isn't a timed session.")
            if self._active_session_row() is not None:
                raise GameError("A session is already running - finish it or give up first.")

            today = _today()
            if self._one("SELECT id FROM completions WHERE task_id = ? AND day = ?",
                         (row["id"], today)) is not None:
                raise GameError("You've already done this one today.")
            if self._one("SELECT id FROM skips WHERE task_id = ? AND day = ?",
                         (row["id"], today)) is not None:
                raise GameError("That quest is skipped today - it returns on its next day.")

            # A paused pomodoro may still be resumed, but nothing new starts on a
            # day the quest is not scheduled for.
            paused = (self._paused_pomodoro_session(row["id"])
                      if mode == "pomodoro" else None)
            if paused is None and self._open_occurrence(row, today) is None:
                raise GameError(self._not_open_message(row, today))

            if mode == "pomodoro":
                # A paused quest is not restarted from zero: it picks up its
                # banked rounds and the phase it was left in.
                if paused is not None:
                    return self._resume_pomodoro_quest(paused)
                return self._start_pomodoro_session(row)

            minutes = _normalise_duration(mode, row["duration_minutes"])
            duration = minutes * 60
            started = _now_ms()
            ends = (datetime.now() + timedelta(seconds=duration)).isoformat(timespec="milliseconds")
            char = self._character()
            cur = self._conn.execute(
                """INSERT INTO sessions
                   (task_id, mode, started_at, ends_at, duration_seconds, status, wounded)
                   VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                (row["id"], mode, started, ends, duration, 1 if self._is_wounded(char) else 0),
            )
            self._conn.commit()
            info = D.SESSION_MODE_BY_ID[mode]
            self._log("session",
                      f"Timer started: {row['name'][:40]} ({_duration_label(minutes)}, "
                      f"{info['label']})", info["icon"])
            session = self._session_dict(
                self._one("SELECT * FROM sessions WHERE id = ?", (cur.lastrowid,)))
            return {"ok": True, "outcome": "started", "session": session,
                    "state": self._build_state()}

    def _just_settled_hit(self, task_id: int) -> dict | None:
        for item in getattr(self, "_settled", []) or []:
            if int(item["task_id"]) == int(task_id):
                return item
        return None

    def finish_session(self, task_id: int) -> dict:
        with self._lock:
            # Look for this task's session before sweeping up stale ones, so an
            # expired Beat the Clock press still reports the hit it earned
            # rather than a confusing "nothing is running".
            session_row = self._active_session_row(task_id)
            if session_row is None:
                self._settle_sessions()
                hit = self._just_settled_hit(task_id)
                if hit is not None:
                    return {"ok": True, "outcome": "hit", "damage": hit["damage"],
                            "state": self._build_state()}
                raise GameError("No session is running for that quest.")

            # A pomodoro is scored by its finished rounds, not by one clock.
            if session_row["mode"] == "pomodoro":
                return self._finish_pomodoro(session_row)

            duration = int(session_row["duration_seconds"] or 0)
            elapsed = E.seconds_between(session_row["started_at"], _now_ms())
            mode = session_row["mode"]
            outcome = E.session_outcome(mode, elapsed, duration)

            if outcome == "too_early":
                left = max(0, int(math.ceil(duration - elapsed)))
                pretty = (_duration_label(max(1, int(round(left / 60)))) if left >= 60
                          else f"{left} second{'s' if left != 1 else ''}")
                raise GameError(f"Not yet - {pretty} still to serve.")

            if outcome == "hit":
                damage = self._lose_session(session_row, elapsed)
                return {"ok": True, "outcome": "hit", "damage": damage,
                        "state": self._build_state()}

            task_row = self._one("SELECT * FROM tasks WHERE id = ?", (session_row["task_id"],))
            if task_row is None:
                raise GameError("That quest no longer exists.")

            today = _today()
            char = self._character()
            is_first_today = self._one(
                "SELECT id FROM completions WHERE day = ? LIMIT 1", (today,)) is None
            streak = E.next_streak(task_row["last_completed"], today, task_row["streak"],
                                   task_row["days"], self._skipped_days(task_row["id"]),
                                   self._window(task_row))
            task = self._task_dict(task_row, today)
            rewards = E.apply_wounded_penalty(
                E.session_rewards(task, streak, is_first_today, mode, elapsed, duration),
                self._is_wounded(char),
            )

            self._conn.execute(
                """UPDATE sessions SET status = 'won', finished_at = ?, elapsed_seconds = ?,
                   remaining_seconds = ?, xp = ?, coins = ?, damage = 0 WHERE id = ?""",
                (_now_ms(), int(elapsed), int(max(0, round(duration - elapsed))),
                 int(rewards["xp"]), int(rewards["coins"]), session_row["id"]),
            )
            self._conn.execute(
                "UPDATE tasks SET sessions_won = sessions_won + 1 WHERE id = ?",
                (task_row["id"],),
            )
            level_up = self._apply_completion(task_row, rewards, streak, mode)

            notes = []
            if rewards.get("speed_bonus"):
                notes.append(f"{int(round(rewards['speed_bonus'] * 100))}% time to spare")
            if rewards.get("endure_bonus"):
                notes.append(f"{int(round(rewards['endure_bonus'] * 100))}% endurance bonus")
            if rewards.get("wounded"):
                notes.append("wounded - half gold")
            text = (f"{task_row['name'][:44]} session won  ·  +{rewards['xp']} XP  ·  "
                    f"+{rewards['coins']} gold")
            if notes:
                text += f"  ({', '.join(notes)})"
            self._log("session", text, D.SESSION_MODE_BY_ID.get(mode, D.SESSION_MODES[0])["icon"])

            unlocked = self._check_achievements()
            return {"ok": True, "outcome": "won", "rewards": rewards, "level_up": level_up,
                    "unlocked": unlocked,
                    "recurrence": self._recurrence_notice(task_row["id"]),
                    "state": self._build_state()}

    def abandon_session(self, task_id: int) -> dict:
        with self._lock:
            session_row = self._active_session_row(task_id)
            if session_row is None:
                self._settle_sessions()
                hit = self._just_settled_hit(task_id)
                if hit is not None:
                    return {"ok": True, "outcome": "hit", "damage": hit["damage"],
                            "state": self._build_state()}
                raise GameError("No session is running for that quest.")

            duration = int(session_row["duration_seconds"] or 0)
            elapsed = E.seconds_between(session_row["started_at"], _now_ms())
            if (session_row["mode"] == "beat_clock"
                    and elapsed > duration + D.SESSION_GRACE_SECONDS):
                # The bell already rang - walking away doesn't dodge the hit.
                damage = self._lose_session(session_row, elapsed)
                return {"ok": True, "outcome": "hit", "damage": damage,
                        "state": self._build_state()}

            self._conn.execute(
                """UPDATE sessions SET status = 'abandoned', finished_at = ?,
                   elapsed_seconds = ?, remaining_seconds = ? WHERE id = ?""",
                (_now_ms(), int(elapsed), int(max(0, round(duration - elapsed))),
                 session_row["id"]),
            )
            self._conn.commit()
            task = self._one("SELECT name, icon FROM tasks WHERE id = ?", (session_row["task_id"],))
            name = task["name"][:44] if task else "a quest"
            self._log("session", f"Gave up on {name} - no reward this time.", "🏳️")
            return {"ok": True, "outcome": "abandoned", "state": self._build_state()}

    def stop_pomodoro_session(self, task_id: int, final: bool = False) -> dict:
        """Stop a pomodoro session, optionally marking it as fully done."""
        with self._lock:
            self._settle_sessions()
            session_row = self._active_pomodoro_session(task_id)
            if session_row is None:
                self._settle_sessions()
                hit = self._just_settled_hit(task_id)
                if hit is not None:
                    return {"ok": True, "outcome": "hit", "damage": hit["damage"],
                            "state": self._build_state()}
                raise GameError("No pomodoro session is running for that quest.")

            if final:
                # Pay for the rounds that were finished and close the session.
                return self._finish_pomodoro(session_row)

            # Otherwise just advance to the next phase (focus -> break -> focus)
            return self._cycle_pomodoro_session(task_id)

    def pause_pomodoro_quest(self, task_id: int) -> dict:
        """Leave the quest unfinished, banking the rounds already completed.

        The session row survives as ``paused``, so starting the quest again
        resumes the same phase with the same round count instead of a fresh
        pomodoro.
        """
        with self._lock:
            self._settle_sessions()
            session_row = self._active_pomodoro_session(task_id)
            if session_row is None:
                raise GameError("No pomodoro session is running for that quest.")
            task_row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            name = task_row["name"][:44] if task_row else "a quest"
            remaining = self._pause_remaining(session_row)
            duration = int(session_row["duration_seconds"] or 0)
            completed = int(session_row["pomodoro_completed"] or 0)

            self._conn.execute(
                """UPDATE sessions SET status = 'paused', paused_seconds = ?,
                   finished_at = ?, elapsed_seconds = ?, remaining_seconds = ?
                   WHERE id = ?""",
                (remaining, _now_ms(), int(max(0, duration - remaining)), remaining,
                 session_row["id"]),
            )
            self._conn.commit()
            self._log("session",
                      f"Pomodoro paused on {name} - {completed} "
                      f"round{'' if completed == 1 else 's'} banked for next time.",
                      "⏸️")
            return {"ok": True, "outcome": "quest_paused", "rounds": completed,
                    "state": self._build_state()}

    def pause_session(self, task_id: int) -> dict:
        """Freeze the running countdown; the session itself stays active."""
        with self._lock:
            session_row = self._active_session_row(task_id)
            if session_row is None:
                raise GameError("No session is running for that quest.")
            if int(session_row["paused_seconds"] or 0) > 0:
                raise GameError("The timer is already paused.")
            remaining = self._pause_remaining(session_row)
            if remaining <= 0:
                raise GameError("That round is already over - advance to the next one.")
            self._conn.execute(
                "UPDATE sessions SET paused_seconds = ? WHERE id = ?",
                (remaining, session_row["id"]),
            )
            self._conn.commit()
            session = self._session_dict(
                self._one("SELECT * FROM sessions WHERE id = ?", (session_row["id"],)))
            return {"ok": True, "outcome": "paused", "session": session,
                    "state": self._build_state()}

    def resume_session(self, task_id: int) -> dict:
        """Restart a frozen countdown from the moment it was paused."""
        with self._lock:
            session_row = self._active_session_row(task_id)
            if session_row is None:
                raise GameError("No session is running for that quest.")
            remaining = int(session_row["paused_seconds"] or 0)
            if remaining <= 0:
                raise GameError("The timer is not paused.")
            duration = int(session_row["duration_seconds"] or 0)
            remaining = max(1, min(duration, remaining)) if duration else remaining
            now = datetime.now()
            started = (now - timedelta(seconds=duration - remaining)).isoformat(
                timespec="milliseconds")
            ends = (now + timedelta(seconds=remaining)).isoformat(timespec="milliseconds")
            self._conn.execute(
                """UPDATE sessions SET paused_seconds = 0, started_at = ?, ends_at = ?
                   WHERE id = ?""",
                (started, ends, session_row["id"]),
            )
            self._conn.commit()
            session = self._session_dict(
                self._one("SELECT * FROM sessions WHERE id = ?", (session_row["id"],)))
            return {"ok": True, "outcome": "resumed", "session": session,
                    "state": self._build_state()}

    def _cycle_pomodoro_session(self, task_id: int) -> dict:
        """Cycle the pomodoro session to the next phase (focus <-> break)."""
        with self._lock:
            self._settle_sessions()
            session_row = self._active_pomodoro_session(task_id)
            if session_row is None:
                raise GameError("No pomodoro session is running for that quest.")
            session = self._cycle_pomodoro_phase(session_row)
            return {"ok": True, "session": session, "state": self._build_state()}

    def _lose_session(self, session_row: sqlite3.Row, elapsed: float) -> int:
        """The bell caught the hero out: take a hit and lose the chain."""
        task_row = self._one("SELECT * FROM tasks WHERE id = ?", (session_row["task_id"],))
        char = self._character()
        _, maximum = self._hp_for(char)
        difficulty = task_row["difficulty"] if task_row else "easy"
        damage = self._apply_damage(E.hit_damage(difficulty, maximum))

        self._conn.execute(
            """UPDATE sessions SET status = 'lost', finished_at = ?, elapsed_seconds = ?,
               remaining_seconds = 0, damage = ? WHERE id = ?""",
            (_now_ms(), int(elapsed), damage, session_row["id"]),
        )
        if task_row is not None:
            self._conn.execute(
                "UPDATE tasks SET streak = 0, sessions_lost = sessions_lost + 1 WHERE id = ?",
                (task_row["id"],),
            )
        self._conn.commit()

        name = task_row["name"][:44] if task_row else "a quest"
        icon = task_row["icon"] if task_row else "💥"
        self._log("hit", f"The bell caught you on {name} - you took {damage} damage.", icon)
        return damage

    def _settle_sessions(self) -> list[dict]:
        """Resolve Beat the Clock windows that closed while nobody was looking.

        Stay the Course sessions are deliberately left open - running over the
        time is allowed, so they only end when the hero finishes or gives up.

        Anything resolved here is remembered on ``_settled`` so the next state
        payload can tell the UI to play the hit - that matters when the window
        closes while the tab is shut.
        """
        settled: list[dict] = []
        self._settled = settled
        now = _now_ms()
        for row in self._query(
            "SELECT * FROM sessions WHERE status = 'active' AND mode = 'beat_clock'"
        ):
            duration = int(row["duration_seconds"] or 0)
            elapsed = E.seconds_between(row["started_at"], now)
            if elapsed <= duration + D.SESSION_GRACE_SECONDS:
                continue
            settled.append({"session_id": row["id"], "task_id": row["task_id"],
                            "damage": self._lose_session(row, elapsed)})
        return settled

    # -- the day's reckoning ----------------------------------------------
    def _perfect_day(self, day: str, ignoring: int | None = None) -> bool:
        """Nothing open today was left undone - skips count as closed, not missed.

        ``ignoring`` skips one quest, for the moment a completion is being
        written: that quest is about to be closed, so it must not count as an
        open quest while the decision is made. A windowed quest whose window is
        still open counts, because there is still time to do it.
        """
        for task in self._query("SELECT * FROM tasks WHERE archived = 0"):
            if ignoring is not None and int(task["id"]) == int(ignoring):
                continue
            if self._open_occurrence(task, day) is not None:
                return False
        return True

    def _ensure_ledger(self) -> str:
        row = self._one("SELECT value FROM meta WHERE key = 'reckoned_day'")
        if row and row["value"]:
            return str(row["value"])
        # A brand-new save arms the ledger today: nothing before it is scored.
        today = _today()
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reckoned_day', ?)",
            (today,),
        )
        self._conn.commit()
        return today

    def _apply_day_reckoning(self) -> None:
        """Score one unscored day, once, the first time the app is opened after it."""
        armed = self._ensure_ledger()
        today = _today()
        if armed >= today:
            return
        self._run_reckoning_for_day(armed)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reckoned_day', ?)",
            (today,),
        )
        self._conn.commit()

    def _run_reckoning_for_day(self, day: str) -> None:
        self._day_reckoning = None
        missed = [
            task for task in self._query("SELECT * FROM tasks WHERE archived = 0")
            if self._missed_occurrence(task, day) is not None
        ]
        if not missed:
            return
        char = self._character()
        _, maximum = self._hp_for(char)
        # No single day can take more than a fifth of the bar: coming back from
        # an absence should sting, not end the run.
        pool = max(1, int(round(maximum * D.OVERLOAD_DAMAGE_FRACTION)))
        total_damage = 0
        missed_items = []
        for task in missed:
            if pool <= 0:
                break
            wanted = E.miss_damage(task["difficulty"] or "easy", maximum)
            taken = self._apply_damage(min(pool, wanted))
            pool -= taken
            total_damage += taken
            missed_items.append({
                "task_id": task["id"],
                "name": task["name"],
                "difficulty": task["difficulty"],
                "damage": taken,
            })
        if not missed_items:
            return
        self._day_reckoning = {
            "day": day,
            "missed": missed_items,
            "total_damage": total_damage,
        }
        self._log(
            "reckoning",
            f"Yesterday's misses cost {total_damage} HP across {len(missed_items)} "
            f"quest{'s' if len(missed_items) != 1 else ''}.",
            "\U0001f494",
        )

    def _overload_summary(self) -> dict | None:
        """Warn when a beaten-down hero still has a pile of quests due today."""
        char = self._character()
        hp, maximum = self._hp_for(char)
        if maximum <= 0 or hp > maximum * D.OVERLOAD_HP_FRACTION:
            return None
        today = _today()
        missed = 0
        for task in self._query("SELECT * FROM tasks WHERE archived = 0"):
            if self._open_occurrence(task, today) is not None:
                missed += 1
        if missed < D.OVERLOAD_MISSED_MIN:
            return None
        return {
            "missed_count": missed,
            "message": ("Your quest log is heavy - %d still due today and the hero "
                        "is battered. Consider trimming it." % missed),
        }

    def _skipped_days(self, task_id: int) -> set[str]:
        """Days this quest was skipped. They behave exactly like rest days."""
        return {
            row["day"] for row in self._query(
                "SELECT day FROM skips WHERE task_id = ?", (int(task_id),))
        }

    def _any_due_on(self, day: date) -> bool:
        """Did any live quest ask for attention on this day?

        A quest skipped that day does not count: the point of a skip is that the
        day is treated as though the quest was never there, so the hero's day
        streak is unaffected too.
        """
        skipped = {
            row["task_id"] for row in self._query(
                "SELECT task_id FROM skips WHERE day = ?", (day.isoformat(),))
        }
        rows = self._query("SELECT id, days FROM tasks WHERE archived = 0")
        return any(E.day_is_due(r["days"], day.isoweekday()) and r["id"] not in skipped
                   for r in rows)

    def _day_streak(self, last_day: str | None, current: int, today: str) -> int:
        if not last_day:
            return 1
        if last_day == today:
            return max(1, int(current))
        last = E.parse_date(last_day)
        now = E.parse_date(today)
        if last is None or now is None:
            return 1
        delta = (now - last).days
        if delta <= 0:
            return max(1, int(current))
        # Days with nothing scheduled are rest days: they do not break the run.
        for offset in range(1, delta):
            if self._any_due_on(last + timedelta(days=offset)):
                return 1
        return max(1, int(current)) + 1

    def undo_task(self, task_id: int) -> dict:
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            last = self._one(
                "SELECT * FROM completions WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (row["id"],),
            )
            if last is None:
                raise GameError("Nothing to undo for that quest.")

            self._conn.execute("DELETE FROM completions WHERE id = ?", (last["id"],))

            days = [r["day"] for r in self._query(
                "SELECT day FROM completions WHERE task_id = ? ORDER BY day ASC", (row["id"],)
            )]
            skipped = self._skipped_days(row["id"])
            streak = E.current_streak(days, row["days"], skipped=skipped,
                                      window=self._window(row))
            best = E.longest_day_run(days, row["days"], skipped=skipped,
                                     window=self._window(row))
            count = len(days)
            self._conn.execute(
                """UPDATE tasks SET streak = ?, best_streak = ?, completions = ?,
                   last_completed = ? WHERE id = ?""",
                (streak, best, count, days[-1] if days else None, row["id"]),
            )

            # Undoing a repeat puts the counted run back where it was, and a
            # quest that this very completion archived returns to the board.
            target = E.safe_int(row["recurrences"], 0)
            if target > 0:
                done = max(0, E.safe_int(row["recurrences_done"], 0) - 1)
                self._conn.execute(
                    "UPDATE tasks SET recurrences_done = ? WHERE id = ?", (done, row["id"]))
                if (int(row["archived"] or 0)
                        and (row["archive_reason"] or "") == "complete"):
                    self._conn.execute(
                        "UPDATE tasks SET archived = 0, archived_at = NULL, "
                        "archive_reason = '' WHERE id = ?", (row["id"],))

            char = self._character()
            new_xp = max(0, int(char["xp"]) - int(last["xp"]))
            new_coins = max(0, int(char["coins"]) - int(last["coins"]))
            # Health mended by that completion is rolled back too, otherwise
            # completing and undoing the same quest would be a free heal.
            hp, maximum = self._hp_for(char)
            restored = max(0, hp - max(0, int(last["hp_delta"] or 0)))
            self._conn.execute(
                """UPDATE character
                   SET xp = ?, coins = ?, coins_earned = MAX(0, coins_earned - ?),
                       total_completions = MAX(0, total_completions - 1), hp = ?
                   WHERE id = 1""",
                (new_xp, new_coins, int(last["coins"]), min(restored, maximum)),
            )
            self._conn.commit()
            self._log("undo", f"Undid '{row['name'][:50]}'  ·  −{last['xp']} XP", "↩️")
            return {"ok": True, "state": self._build_state()}

    # -- skills -----------------------------------------------------------
    def upgrade_stat(self, stat: str, amount: int = 1) -> dict:
        if stat not in D.STAT_KEYS:
            raise GameError("Unknown stat.")
        amount = E.clamp(E.safe_int(amount, 1), 1, 20)
        with self._lock:
            char = self._character()
            stats = json.loads(char["stats"] or "{}")
            archetype = D.ARCHETYPE_BY_ID.get(char["archetype"], D.ARCHETYPES[0])
            base = dict(archetype["stats"])
            for key in D.STAT_KEYS:
                stats.setdefault(key, base.get(key, 0))
            level = E.level_from_xp(char["xp"])["level"]
            available = E.available_skill_points(level, stats, base)
            if available <= 0:
                raise GameError("No skill points available. Complete quests to level up!")
            amount = min(amount, available)
            stats[stat] = int(stats[stat]) + amount
            self._conn.execute("UPDATE character SET stats = ? WHERE id = 1", (json.dumps(stats),))
            self._conn.commit()
            self._log("skill", f"{D.STAT_LABELS[stat]} increased to {stats[stat]}.",
                      D.STAT_ABBR[stat])
            unlocked = self._check_achievements()
            return {"ok": True, "spent": amount, "stat": stat,
                    "unlocked": unlocked, "state": self._build_state()}

    # -- shop -------------------------------------------------------------
    def owned_item_ids(self) -> set[str]:
        return {r["item_id"] for r in self._query("SELECT item_id FROM inventory")}

    def equipped_items(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in self._query("SELECT * FROM equipped"):
            item = D.ITEM_BY_ID.get(row["item_id"])
            if item:
                out[row["slot"]] = item
        return out

    def equipped_map(self) -> dict[str, str | None]:
        equipped = {r["slot"]: r["item_id"] for r in self._query("SELECT * FROM equipped")}
        return {slot: equipped.get(slot) for slot in D.SLOT_IDS}

    def shop_list(self) -> list[dict]:
        with self._lock:
            owned = self.owned_item_ids()
            equipped = self.equipped_map()
            char = self.character_meta() if self.has_character() else {"level": 1, "coins": 0}
            out = []
            for item in D.ITEMS:
                entry = dict(item)
                entry["owned"] = item["id"] in owned
                entry["equipped"] = item["id"] in equipped.values()
                entry["rarity_label"] = D.RARITY_LABELS[item["rarity"]]
                entry["rarity_color"] = D.RARITY_COLORS[item["rarity"]]
                entry["slot_label"] = D.SLOT_LABELS[item["slot"]]
                entry["affordable"] = char["coins"] >= item["price"]
                entry["level_ok"] = char["level"] >= item["level_req"]
                entry["bonus_text"] = "  ".join(
                    f"+{v} {D.STAT_ABBR[k]}" for k, v in item["bonus"].items()
                )
                out.append(entry)
            return out

    def buy_item(self, item_id: str) -> dict:
        item = D.ITEM_BY_ID.get(str(item_id))
        if item is None:
            raise GameError("That item does not exist.")
        with self._lock:
            char = self._character()
            if item_id in self.owned_item_ids():
                raise GameError("You already own that.")
            level = E.level_from_xp(char["xp"])["level"]
            if level < item["level_req"]:
                raise GameError(f"Requires level {item['level_req']}.")
            if int(char["coins"]) < item["price"]:
                raise GameError("Not enough gold.")
            self._conn.execute(
                "UPDATE character SET coins = coins - ? WHERE id = 1", (item["price"],)
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO inventory (item_id, acquired_at) VALUES (?, ?)",
                (item_id, _now()),
            )
            self._conn.commit()
            self._log("purchase", f"Bought {item['name']} for {item['price']} gold.", item["icon"])
            unlocked = self._check_achievements()
            return {"ok": True, "item": item, "unlocked": unlocked,
                    "state": self._build_state()}

    def equip_item(self, item_id: str) -> dict:
        item = D.ITEM_BY_ID.get(str(item_id))
        if item is None:
            raise GameError("That item does not exist.")
        with self._lock:
            if item_id not in self.owned_item_ids():
                raise GameError("You do not own that yet.")
            self._conn.execute(
                "INSERT OR REPLACE INTO equipped (slot, item_id) VALUES (?, ?)",
                (item["slot"], item_id),
            )
            self._conn.commit()
            self._log("equip", f"Equipped {item['name']}.", item["icon"])
            unlocked = self._check_achievements()
            return {"ok": True, "item": item, "unlocked": unlocked,
                    "state": self._build_state()}

    def unequip_slot(self, slot: str) -> dict:
        if slot not in D.SLOT_IDS:
            raise GameError("Unknown equipment slot.")
        with self._lock:
            self._conn.execute("DELETE FROM equipped WHERE slot = ?", (slot,))
            self._conn.commit()
            return {"ok": True, "state": self._build_state()}

    # -- achievements -----------------------------------------------------
    def unlocked_ids(self) -> set[str]:
        return {r["id"] for r in self._query("SELECT id FROM achievements")}

    def _session_metrics(self) -> dict:
        def count(sql: str, params: tuple = ()) -> int:
            row = self._one(sql, params)
            return int(row["n"] or 0) if row else 0

        return {
            "sessions_won": count("SELECT COUNT(*) AS n FROM sessions WHERE status = 'won'"),
            "sessions_lost": count("SELECT COUNT(*) AS n FROM sessions WHERE status = 'lost'"),
            "endure_won": count(
                "SELECT COUNT(*) AS n FROM sessions WHERE status = 'won' AND mode = 'endure'"),
            "swift_wins": count(
                "SELECT COUNT(*) AS n FROM sessions WHERE status = 'won' AND mode = 'beat_clock' "
                "AND remaining_seconds * 2 >= duration_seconds"),
            "wounded_wins": count(
                "SELECT COUNT(*) AS n FROM sessions WHERE status = 'won' AND wounded = 1"),
        }

    def _metrics(self) -> dict:
        char = self.character_meta()
        tasks = self.list_tasks(include_archived=True)
        all_days = [r["day"] for r in self._query("SELECT day FROM completions ORDER BY day ASC")]
        best_day = self._one(
            "SELECT COUNT(*) AS n FROM completions GROUP BY day ORDER BY n DESC LIMIT 1")
        # Older rows were written before completions remembered their mode.
        mode_counts = {
            row["mode"]: int(row["n"])
            for row in self._query(
                "SELECT COALESCE(NULLIF(mode, ''), 'instant') AS mode, COUNT(*) AS n "
                "FROM completions GROUP BY mode")
        }
        total_stats = list(char["total_stats"].values())
        return {
            "total_completions": char["total_completions"],
            "best_task_streak": max([int(t["best_streak"]) for t in tasks] + [0]),
            "best_task_completions": max([int(t["completions"]) for t in tasks] + [0]),
            "best_day_completions": int(best_day["n"] or 0) if best_day else 0,
            "level": char["level"],
            "top_stat": max(total_stats + [0]),
            "min_stat": min(total_stats) if total_stats else 0,
            "items_owned": len(self.owned_item_ids()),
            "slots_filled": len([v for v in self.equipped_map().values() if v]),
            "coins": char["coins"],
            "coins_earned": int(char["coins_earned"]),
            "total_xp": int(char["xp"]),
            "best_day_streak": int(char["best_day_streak"]),
            "longest_day_run": E.longest_day_run(all_days),
            "completions_instant": mode_counts.get("instant", 0),
            "completions_beat_clock": mode_counts.get("beat_clock", 0),
            "completions_endure": mode_counts.get("endure", 0),
            "completions_pomodoro": mode_counts.get("pomodoro", 0),
            **self._session_metrics(),
        }

    def _check_achievements(self) -> list[dict]:
        metrics = self._metrics()
        evaluated = E.evaluate_achievements(metrics)
        known = self.unlocked_ids()
        newly = []
        for ach in D.ACHIEVEMENTS:
            info = evaluated[ach["id"]]
            if info["unlocked"] and ach["id"] not in known:
                self._conn.execute(
                    "INSERT OR IGNORE INTO achievements (id, unlocked_at) VALUES (?, ?)",
                    (ach["id"], _now()),
                )
                newly.append({**ach, "unlocked_at": _now()})
        if newly:
            self._conn.commit()
            # One feed line per stack - the highest tier earned in this pass -
            # so a veteran opening a new batch of tiers does not bury the log.
            top: dict[str, dict] = {}
            for ach in newly:
                key = ach.get("family") or ach["id"]
                if key not in top or int(ach.get("tier", 0)) > int(top[key].get("tier", 0)):
                    top[key] = ach
            for ach in top.values():
                self._log("achievement", f"Achievement unlocked: {ach['name']}", ach["icon"])
        return newly

    def achievements_state(self) -> list[dict]:
        with self._lock:
            metrics = self._metrics()
            evaluated = E.evaluate_achievements(metrics)
            stored = {r["id"]: r["unlocked_at"] for r in self._query("SELECT * FROM achievements")}
            out = []
            for ach in D.ACHIEVEMENTS:
                info = evaluated[ach["id"]]
                out.append({
                    **ach,
                    "progress": info["progress"],
                    "percent": info["percent"],
                    "unlocked": ach["id"] in stored or info["unlocked"],
                    "unlocked_at": stored.get(ach["id"]),
                })
            return out

    # -- activity + history ----------------------------------------------
    def _log(self, kind: str, text: str, icon: str = "✨") -> None:
        self._conn.execute(
            "INSERT INTO activity (ts, day, kind, icon, text) VALUES (?, ?, ?, ?, ?)",
            (_now(), _today(), kind, icon, text[:220]),
        )
        self._conn.commit()

    def activity(self, limit: int = 25) -> list[dict]:
        with self._lock:
            limit = E.clamp(E.safe_int(limit, 25), 1, 200)
            rows = self._query(
                "SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [
                {"ts": r["ts"], "day": r["day"], "kind": r["kind"],
                 "icon": r["icon"], "text": r["text"]}
                for r in rows
            ]

    def history(self, days: int = 30) -> dict:
        with self._lock:
            days = E.clamp(E.safe_int(days, 30), 7, 120)
            window = E.date_range(days)
            counts: dict[str, int] = {d: 0 for d in window}
            for row in self._query(
                "SELECT day, COUNT(*) AS n FROM completions WHERE day >= ? GROUP BY day",
                (window[0],),
            ):
                if row["day"] in counts:
                    counts[row["day"]] = row["n"]
            xp_by_day: dict[str, int] = {d: 0 for d in window}
            for row in self._query(
                "SELECT day, SUM(xp) AS n FROM completions WHERE day >= ? GROUP BY day",
                (window[0],),
            ):
                if row["day"] in xp_by_day:
                    xp_by_day[row["day"]] = int(row["n"] or 0)

            top = self._query(
                """SELECT t.name, t.icon, t.color, COUNT(c.id) AS n, COALESCE(SUM(c.xp),0) AS xp
                   FROM completions c JOIN tasks t ON t.id = c.task_id
                   GROUP BY c.task_id ORDER BY n DESC LIMIT 6"""
            )
            total_xp = self._one("SELECT COALESCE(SUM(xp),0) AS n FROM completions")["n"]
            return {
                "days": days,
                "series": [
                    {"day": d, "count": counts[d], "level": E.heat_level(counts[d]),
                     "xp": xp_by_day[d]}
                    for d in window
                ],
                "total_completions": sum(counts.values()),
                "total_xp": int(total_xp or 0),
                "active_days": len([d for d in window if counts[d] > 0]),
                "top_tasks": [
                    {"name": r["name"], "icon": r["icon"], "color": r["color"],
                     "count": r["n"], "xp": int(r["xp"] or 0)}
                    for r in top
                ],
            }

    # -- settings ---------------------------------------------------------
    # Global preferences, stored as one JSON row in meta so adding a setting
    # never needs a schema migration.
    def _sound_dir(self) -> Path:
        return Path(self.path).resolve().parent / "sounds"

    def _stored_settings(self) -> dict:
        row = self._one("SELECT value FROM meta WHERE key = 'settings'")
        if not row or not row["value"]:
            return {}
        try:
            data = json.loads(row["value"])
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_settings(self, stored: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('settings', ?)",
            (json.dumps(stored, ensure_ascii=False),),
        )
        self._conn.commit()

    def _custom_sound_file(self) -> Path | None:
        folder = self._sound_dir()
        for ext in ("wav", "mp3", "ogg"):
            candidate = folder / f"alarm.{ext}"
            if candidate.is_file():
                return candidate
        return None

    def _settings_unlocked(self) -> dict:
        stored = self._stored_settings()
        custom = self._custom_sound_file()

        sound = stored.get("sound")
        if sound not in D.ALARM_SOUND_BY_ID and sound != D.CUSTOM_ALARM_ID:
            sound = D.DEFAULT_ALARM_SOUND
        # A missing file must not leave the app silent: fall back to a built-in.
        if sound == D.CUSTOM_ALARM_ID and custom is None:
            sound = D.DEFAULT_ALARM_SOUND

        try:
            volume = float(stored.get("volume", D.DEFAULT_ALARM_VOLUME))
        except (TypeError, ValueError):
            volume = D.DEFAULT_ALARM_VOLUME
        if volume != volume:  # NaN
            volume = D.DEFAULT_ALARM_VOLUME
        volume = max(0.0, min(1.0, volume))

        size = 0
        updated = 0
        if custom is not None:
            try:
                stat = custom.stat()
                size, updated = stat.st_size, int(stat.st_mtime)
            except OSError:
                size, updated = 0, 0

        return {
            "sound": sound,
            "volume": round(volume, 2),
            "sounds": D.ALARM_SOUNDS,
            "custom": {
                "present": custom is not None,
                "name": (str(stored.get("custom_name") or "")[:80]
                         if custom is not None else ""),
                "bytes": size,
                # Cache-busting token: the file at /api/sound changes, the URL should too.
                "url": f"/api/sound?v={updated}" if custom is not None else "",
            },
            "limits": {
                "max_bytes": D.ALARM_MAX_BYTES,
                "types": D.ALARM_FILE_LABEL,
                "folder": str(self._sound_dir()),
            },
        }

    def settings(self) -> dict:
        with self._lock:
            return self._settings_unlocked()

    def update_settings(self, patch: dict) -> dict:
        """Change the alarm sound and/or volume. Unknown fields are ignored."""
        with self._lock:
            stored = self._stored_settings()
            if "sound" in patch:
                sound = str(patch.get("sound") or "").strip()
                if sound == D.CUSTOM_ALARM_ID:
                    if self._custom_sound_file() is None:
                        raise GameError("Add a custom sound file first.")
                elif sound not in D.ALARM_SOUND_BY_ID:
                    raise GameError("Unknown alarm sound.")
                stored["sound"] = sound
            if "volume" in patch:
                raw = patch.get("volume")
                try:
                    volume = float(raw)
                except (TypeError, ValueError):
                    raise GameError("Volume must be a number between 0 and 100.")
                if volume != volume:
                    raise GameError("Volume must be a number between 0 and 100.")
                if volume > 1:
                    volume = volume / 100.0
                stored["volume"] = max(0.0, min(1.0, volume))
            self._write_settings(stored)
            return self._settings_unlocked()

    def save_alarm_sound(self, name: str, content_type: str, payload: bytes) -> dict:
        """Store an uploaded alarm beside the save, replacing any previous one."""
        label = (content_type or "").split(";")[0].strip().lower()
        ext = D.ALARM_TYPES.get(label)
        if ext is None:
            # Some browsers send an empty or vague type; trust the extension then.
            suffix = Path(str(name or "")).suffix.lstrip(".").lower()
            ext = suffix if suffix in ("wav", "mp3", "ogg") else None
        if ext is None:
            raise GameError(f"The alarm must be a {D.ALARM_FILE_LABEL} file.")
        if not payload:
            raise GameError("That sound file is empty.")
        if len(payload) > D.ALARM_MAX_BYTES:
            mb = D.ALARM_MAX_BYTES // (1024 * 1024)
            raise GameError(f"Sound files are limited to {mb} MB.")
        if not _sound_magic_ok(payload, ext):
            raise GameError(f"That file doesn't look like a {ext.upper()} audio file.")

        display_name = Path(str(name or "")).name[:80] or f"alarm.{ext}"
        with self._lock:
            folder = self._sound_dir()
            try:
                folder.mkdir(parents=True, exist_ok=True)
                for old in folder.glob("alarm.*"):
                    old.unlink()
                (folder / f"alarm.{ext}").write_bytes(payload)
            except OSError as exc:
                raise GameError(f"Could not save the sound file: {exc}")

            stored = self._stored_settings()
            stored["sound"] = D.CUSTOM_ALARM_ID
            stored["custom_name"] = display_name
            self._write_settings(stored)
            self._log("settings", f"Alarm sound set to {display_name}.", "🔔")
            return self._settings_unlocked()

    def clear_alarm_sound(self) -> dict:
        with self._lock:
            for old in self._sound_dir().glob("alarm.*"):
                try:
                    old.unlink()
                except OSError:
                    pass
            stored = self._stored_settings()
            stored.pop("custom_name", None)
            if stored.get("sound") == D.CUSTOM_ALARM_ID:
                stored["sound"] = D.DEFAULT_ALARM_SOUND
            self._write_settings(stored)
            return self._settings_unlocked()

    def alarm_sound(self) -> tuple[bytes, str] | None:
        """The uploaded alarm's bytes and MIME type, if there is one."""
        with self._lock:
            path = self._custom_sound_file()
            if path is None:
                return None
            mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg"}
            try:
                return path.read_bytes(), mime.get(path.suffix.lstrip("."), "application/octet-stream")
            except OSError:
                return None

    # -- assembling the full state ---------------------------------------
    def _build_state(self) -> dict:
        tasks = self.list_tasks()
        char = self.character_meta()
        equipped = self.equipped_map()
        inventory = {}
        for row in self._query("SELECT * FROM inventory ORDER BY acquired_at DESC"):
            item = D.ITEM_BY_ID.get(row["item_id"])
            if item:
                inventory[row["item_id"]] = {
                    **item, "acquired_at": row["acquired_at"], "equipped": equipped.get(item["slot"]) == item["id"],
                    "rarity_color": D.RARITY_COLORS[item["rarity"]],
                    "slot_label": D.SLOT_LABELS[item["slot"]],
                    "bonus_text": "  ".join(f"+{v} {D.STAT_ABBR[k]}" for k, v in item["bonus"].items()),
                }
        settled = list(getattr(self, "_settled", []) or [])
        self._settled = []
        # The missed-day notice is shown once and then forgotten.
        reckoning = self._day_reckoning
        self._day_reckoning = None
        return {
            "has_character": True,
            "today": _today(),
            "day_reckoning": reckoning,
            "overload": self._overload_summary(),
            "character": char,
            "session": self._session_dict(self._active_session_row())
                       if self._active_session_row() else None,
            "server_now": _now_ms(),
            "settled": settled,
            "tasks": tasks,
            # Quests parked instead of deleted, shown in their own section.
            "archive": self.list_archived(),
            "equipped": {
                slot: (dict(D.ITEM_BY_ID[item_id], slot=slot,
                            slot_label=D.SLOT_LABELS[slot],
                            rarity_color=D.RARITY_COLORS[D.ITEM_BY_ID[item_id]["rarity"]])
                       if item_id else None)
                for slot, item_id in equipped.items()
            },
            "inventory": list(inventory.values()),
            "shop": self.shop_list(),
            "achievements": self.achievements_state(),
            "activity": self.activity(20),
            "history": self.history(30),
            "settings": self._settings_unlocked(),
            "meta": {
                "stats": [{"key": k, "label": D.STAT_LABELS[k], "abbr": D.STAT_ABBR[k],
                           "blurb": D.STAT_BLURBS[k]} for k in D.STAT_KEYS],
                "slots": D.SLOTS,
                "archetypes": D.ARCHETYPES,
                "rarities": D.RARITY_COLORS,
                "icons": D.TASK_ICONS,
                "colors": D.TASK_COLORS,
                "difficulties": D.DIFFICULTIES,
                "stats_per_level": D.SKILL_POINTS_PER_LEVEL,
                "session_modes": D.SESSION_MODES,
                "duration_presets": D.DURATION_PRESETS,
                "session_min_minutes": D.SESSION_MIN_MINUTES,
                "session_max_minutes": D.SESSION_MAX_MINUTES,
                "weekdays": D.WEEKDAYS,
                "today": _today(),
            },
        }

    def day_probe(self) -> dict:
        """Cheap 'has the day turned over?' check: one meta row and the clock.

        Building the whole state settles sessions, scores a missed day and walks
        every achievement. The window polls this instead and only asks for the
        full state when the answer changes - or when the player asks for it.
        Nothing is written here, so probing is always safe.
        """
        with self._lock:
            row = self._one("SELECT value FROM meta WHERE key = 'reckoned_day'")
            return {
                "today": _today(),
                "server_now": _now_ms(),
                "armed_day": str(row["value"]) if row and row["value"] else None,
            }

    def state(self) -> dict:
        with self._lock:
            if not self.has_character():
                return {
                    "has_character": False,
                    "today": _today(),
                    "settings": self._settings_unlocked(),
                    "meta": {
                        "archetypes": D.ARCHETYPES,
                        "stats": [{"key": k, "label": D.STAT_LABELS[k], "abbr": D.STAT_ABBR[k],
                                   "blurb": D.STAT_BLURBS[k]} for k in D.STAT_KEYS],
                        "icons": D.TASK_ICONS,
                        "colors": D.TASK_COLORS,
                        "difficulties": D.DIFFICULTIES,
                        "slots": D.SLOTS,
                        "session_modes": D.SESSION_MODES,
                        "duration_presets": D.DURATION_PRESETS,
                        "session_min_minutes": D.SESSION_MIN_MINUTES,
                        "session_max_minutes": D.SESSION_MAX_MINUTES,
                        "weekdays": D.WEEKDAYS,
                        "today": _today(),
                    },
                }
            self._settle_sessions()
            self._apply_day_reckoning()
            self._check_achievements()
            return self._build_state()

    # -- maintenance ------------------------------------------------------
    def reset(self) -> dict:
        with self._lock:
            for table in ("character", "tasks", "completions", "sessions", "inventory",
                          "equipped", "achievements", "activity", "skips"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.execute("DELETE FROM sqlite_sequence")
            self._conn.commit()
            return {"ok": True}

    def seed_demo(self, force: bool = False) -> dict:
        """Populate a believable save file so the app can be demoed instantly."""
        with self._lock:
            if not self.has_character() or force:
                if force:
                    self.reset()
                self.create_character("Rowan", "ranger", starter_tasks=False)
            rng = random.Random(7)
            demo_tasks = [
                {"name": "Morning run", "stat": "str", "xp": 15, "coins": 12, "icon": "🏃",
                 "color": "#ef4444", "difficulty": "hard", "description": "5km before breakfast."},
                {"name": "Meditate 10 min", "stat": "int", "xp": 10, "coins": 8, "icon": "🧘",
                 "color": "#a855f7", "difficulty": "easy", "description": "Sit. Breathe. Nothing else."},
                {"name": "Study Spanish", "stat": "int", "xp": 12, "coins": 9, "icon": "📚",
                 "color": "#3b82f6", "difficulty": "normal", "description": "One lesson per day."},
                {"name": "No screens after 10pm", "stat": "vit", "xp": 9, "coins": 7, "icon": "📵",
                 "color": "#22d3ee", "difficulty": "normal", "description": "Protect the wind-down."},
                {"name": "Tidy the desk", "stat": "agi", "xp": 5, "coins": 4, "icon": "🧹",
                 "color": "#84cc16", "difficulty": "tiny", "description": "A clear desk, a clear head."},
                {"name": "Call a friend", "stat": "cha", "xp": 11, "coins": 9, "icon": "🤝",
                 "color": "#f97316", "difficulty": "easy", "description": "Keep the bonds strong."},
                {"name": "Read for 30 minutes", "stat": "int", "xp": 16, "coins": 13,
                 "icon": "📖", "color": "#3b82f6", "difficulty": "normal", "mode": "endure",
                 "duration_minutes": 30,
                 "description": "Stay with the book for the whole sitting."},
                {"name": "Sweep the kitchen", "stat": "agi", "xp": 10, "coins": 8,
                 "icon": "🧹", "color": "#84cc16", "difficulty": "easy", "mode": "beat_clock",
                 "duration_minutes": 20,
                 "description": "Twenty minutes to get it done."},
            ]
            existing = {t["name"] for t in self.list_tasks(include_archived=True)}
            task_ids = [t["id"] for t in self.list_tasks(include_archived=True)]
            for t in demo_tasks:
                if t["name"] not in existing:
                    task_ids.append(self._insert_task(t))

            today = date.today()
            for offset in range(29, -1, -1):
                day = (today - timedelta(days=offset)).isoformat()
                if rng.random() < 0.12 and offset > 0:
                    continue
                for task_id in task_ids:
                    if rng.random() < 0.55:
                        row = self._one("SELECT * FROM tasks WHERE id = ?", (task_id,))
                        xp = int(row["xp"] * rng.uniform(0.8, 1.4))
                        coins = int(row["coins"] * rng.uniform(0.8, 1.4))
                        self._conn.execute(
                            """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (task_id, f"{day}T18:00:00", day, xp, coins, 1.0),
                        )
                        self._conn.execute(
                            """UPDATE tasks SET completions = completions + 1,
                               last_completed = CASE WHEN last_completed IS NULL OR last_completed < ?
                                                     THEN ? ELSE last_completed END
                               WHERE id = ?""",
                            (day, day, task_id),
                        )
            totals = self._one(
                "SELECT COALESCE(SUM(xp),0) AS xp, COALESCE(SUM(coins),0) AS coins, COUNT(*) AS n FROM completions"
            )
            self._conn.execute(
                """UPDATE character SET xp = ?, coins = ?, coins_earned = ?, total_completions = ?,
                   day_streak = 4, best_day_streak = 9 WHERE id = 1""",
                (int(totals["xp"]), int(totals["coins"]), int(totals["coins"]), int(totals["n"])),
            )
            for row in self._query(
                    "SELECT id, last_completed, days, window_days FROM tasks"):
                days = [r["day"] for r in self._query(
                    "SELECT day FROM completions WHERE task_id = ? ORDER BY day", (row["id"],))]
                self._conn.execute(
                    "UPDATE tasks SET streak = ?, best_streak = ? WHERE id = ?",
                    (E.current_streak(days, row["days"], window=self._window(row)),
                     E.longest_day_run(days, row["days"], window=self._window(row)),
                     row["id"]),
                )
            self._conn.commit()
            self._log("demo", "Demo save loaded: a month of quests already logged.", "🎲")
            self._check_achievements()
            return self.state()
