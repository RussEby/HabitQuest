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
from datetime import date, datetime, timedelta

from . import data as D
from . import engine as E

SCHEMA_VERSION = 2

# Columns added after the first release. ``_migrate`` adds any that are missing
# so an existing save keeps working without being rebuilt.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "character": {"hp": "INTEGER NOT NULL DEFAULT 0"},
    "tasks": {
        "mode": "TEXT NOT NULL DEFAULT 'instant'",
        "duration_minutes": "INTEGER NOT NULL DEFAULT 0",
        "sessions_won": "INTEGER NOT NULL DEFAULT 0",
        "sessions_lost": "INTEGER NOT NULL DEFAULT 0",
    },
    "completions": {"hp_delta": "INTEGER NOT NULL DEFAULT 0"},
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
    sessions_lost   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS completions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL,
    ts         TEXT    NOT NULL,
    day        TEXT    NOT NULL,
    xp         INTEGER NOT NULL DEFAULT 0,
    coins      INTEGER NOT NULL DEFAULT 0,
    multiplier REAL    NOT NULL DEFAULT 1.0,
    hp_delta   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_completions_day ON completions(day);
CREATE INDEX IF NOT EXISTS idx_completions_task ON completions(task_id);

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
    wounded           INTEGER NOT NULL DEFAULT 0
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


class GameError(Exception):
    """Raised for user-facing problems (bad input, not enough coins, ...)."""


class Game:
    def __init__(self, path: str = "habitquest.db"):
        self.path = str(path)
        self._lock = threading.RLock()
        self._settled: list[dict] = []
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
            for row in self._query("SELECT id, stats FROM character"):
                stats = json.loads(row["stats"] or "{}")
                self._conn.execute(
                    "UPDATE character SET hp = ? WHERE id = ?",
                    (E.max_hp(stats), row["id"]),
                )

        self._conn.execute(
            "UPDATE tasks SET duration_minutes = 20 "
            "WHERE mode IN ('beat_clock', 'endure') AND duration_minutes <= 0"
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        self._conn.commit()

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
        return E.max_hp(E.total_stats(self._raw_stats(char_row), bonus))

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
        done_today = self._one(
            "SELECT id FROM completions WHERE task_id = ? AND day = ?",
            (row["id"], today),
        ) is not None
        base["completed_today"] = done_today
        preview_streak = E.next_streak(row["last_completed"], today, row["streak"])
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
        cur = self._conn.execute(
            """INSERT INTO tasks
               (name, description, stat, xp, coins, icon, color, difficulty,
                streak, best_streak, completions, last_completed, created_at, archived,
                sort_order, mode, duration_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, ?, 0, ?, ?, ?)""",
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
            return self.state_for_task(task_id)

    def delete_task(self, task_id: int) -> dict:
        with self._lock:
            row = self._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
            if row is None:
                raise GameError("That quest no longer exists.")
            self._conn.execute("DELETE FROM completions WHERE task_id = ?", (int(task_id),))
            self._conn.execute("DELETE FROM sessions WHERE task_id = ?", (int(task_id),))
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
            self._conn.commit()
            self._log("task", f"Quest abandoned: {row['name'][:60]}", "🗑️")
            return self.state()

    # -- completing -------------------------------------------------------
    def _apply_completion(self, task_row, rewards: dict, streak: int) -> dict | None:
        """Shared bookkeeping for any success, instant or timed.

        Records the completion, moves the task's streak, pays the hero, mends a
        little health and logs a level-up. Callers log their own activity line,
        update anything session-specific, then check achievements.
        """
        today = _today()
        best_streak = max(int(task_row["best_streak"]), streak)
        self._conn.execute(
            """UPDATE tasks SET streak = ?, best_streak = ?, completions = completions + 1,
               last_completed = ? WHERE id = ?""",
            (streak, best_streak, today, task_row["id"]),
        )

        char = self._character()
        level_before = E.level_from_xp(char["xp"])["level"]
        new_xp = int(char["xp"]) + int(rewards["xp"])
        day_streak = self._day_streak(char["last_active_day"], char["day_streak"], today)
        best_day = max(int(char["best_day_streak"]), day_streak)

        # A new active day lets the hero rest up; every completion mends a bit more.
        hp_before, maximum = self._hp_for(char)
        hp = hp_before
        if char["last_active_day"] != today:
            hp += E.rest_heal(maximum)
        hp = min(maximum, hp + E.heal_per_completion(maximum))

        self._conn.execute(
            """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier, hp_delta)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_row["id"], _now(), today, int(rewards["xp"]), int(rewards["coins"]),
             float(rewards.get("multiplier", 1.0)), hp - hp_before),
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
            if (row["mode"] or "instant") in D.TIMED_MODES:
                raise GameError("That's a timed session - start the clock and finish it.")

            already_today = self._one(
                "SELECT id FROM completions WHERE task_id = ? AND day = ?", (row["id"], today)
            )
            if already_today:
                raise GameError("Already completed today. Come back tomorrow!")

            char = self._character()
            is_first_today = self._one(
                "SELECT id FROM completions WHERE day = ? LIMIT 1", (today,)
            ) is None

            streak = E.next_streak(row["last_completed"], today, row["streak"])
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

            level_up = self._apply_completion(row, rewards, streak)

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
                "state": self._build_state(),
            }

    # -- timed sessions ---------------------------------------------------
    def _session_dict(self, row: sqlite3.Row) -> dict:
        duration = int(row["duration_seconds"] or 0)
        elapsed = E.seconds_between(row["started_at"], _now_ms())
        remaining = max(0.0, duration - elapsed)
        mode = row["mode"] or "instant"
        info = D.SESSION_MODE_BY_ID.get(mode, D.SESSION_MODES[0])
        task = self._one(
            "SELECT id, name, icon, color FROM tasks WHERE id = ?", (row["task_id"],)
        )
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
            "wounded_at_start": bool(row["wounded"]),
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
            mode = row["mode"] or "instant"
            if mode not in D.TIMED_MODES:
                raise GameError("That quest isn't a timed session.")
            if self._active_session_row() is not None:
                raise GameError("A session is already running - finish it or give up first.")

            today = _today()
            if self._one("SELECT id FROM completions WHERE task_id = ? AND day = ?",
                         (row["id"], today)) is not None:
                raise GameError("You've already done this one today.")

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
            streak = E.next_streak(task_row["last_completed"], today, task_row["streak"])
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
            level_up = self._apply_completion(task_row, rewards, streak)

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
                    "unlocked": unlocked, "state": self._build_state()}

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

    def _day_streak(self, last_day: str | None, current: int, today: str) -> int:
        if not last_day:
            return 1
        if last_day == today:
            return max(1, int(current))
        last = E.parse_date(last_day)
        now = E.parse_date(today)
        if last and now and (now - last).days == 1:
            return max(1, int(current)) + 1
        return 1

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
            streak = self._current_streak(days)
            best = E.longest_day_run(days)
            count = len(days)
            self._conn.execute(
                """UPDATE tasks SET streak = ?, best_streak = ?, completions = ?,
                   last_completed = ? WHERE id = ?""",
                (streak, best, count, days[-1] if days else None, row["id"]),
            )

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

    def _current_streak(self, days: list[str]) -> int:
        """Consecutive-day run ending today or yesterday."""
        parsed = sorted({d for d in (E.parse_date(x) for x in days) if d})
        if not parsed:
            return 0
        today = date.today()
        if (today - parsed[-1]).days > 1:
            return 0
        run = 1
        for prev, cur in zip(reversed(parsed), reversed(parsed[:-1])):
            if (prev - cur).days == 1:
                run += 1
            else:
                break
        return run

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
        return {
            "total_completions": char["total_completions"],
            "best_task_streak": max([int(t["best_streak"]) for t in tasks] + [0]),
            "level": char["level"],
            "top_stat": max(list(char["total_stats"].values()) + [0]),
            "items_owned": len(self.owned_item_ids()),
            "slots_filled": len([v for v in self.equipped_map().values() if v]),
            "coins": char["coins"],
            "longest_day_run": E.longest_day_run(all_days),
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
                self._log("achievement", f"Achievement unlocked: {ach['name']}", ach["icon"])
                newly.append({**ach, "unlocked_at": _now()})
        if newly:
            self._conn.commit()
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
        return {
            "has_character": True,
            "character": char,
            "session": self._session_dict(self._active_session_row())
                       if self._active_session_row() else None,
            "server_now": _now_ms(),
            "settled": settled,
            "tasks": tasks,
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
                "today": _today(),
            },
        }

    def state(self) -> dict:
        with self._lock:
            if not self.has_character():
                return {
                    "has_character": False,
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
                        "today": _today(),
                    },
                }
            self._settle_sessions()
            self._check_achievements()
            return self._build_state()

    # -- maintenance ------------------------------------------------------
    def reset(self) -> dict:
        with self._lock:
            for table in ("character", "tasks", "completions", "sessions", "inventory",
                          "equipped", "achievements", "activity"):
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
            for row in self._query("SELECT id, last_completed FROM tasks"):
                days = [r["day"] for r in self._query(
                    "SELECT day FROM completions WHERE task_id = ? ORDER BY day", (row["id"],))]
                self._conn.execute(
                    "UPDATE tasks SET streak = ?, best_streak = ? WHERE id = ?",
                    (self._current_streak(days), E.longest_day_run(days), row["id"]),
                )
            self._conn.commit()
            self._log("demo", "Demo save loaded: a month of quests already logged.", "🎲")
            self._check_achievements()
            return self.state()
