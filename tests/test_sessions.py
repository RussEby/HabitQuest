"""Tests for timed sessions: the two modes, the bell, hits and healing.

Elapsed time is simulated by moving a session's ``started_at`` in the database
rather than by sleeping, so the suite stays fast and deterministic.
"""

import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from habitquest import data as D
from habitquest import engine as E
from habitquest.server import build_server
from habitquest.store import Game, GameError

# The schema as it shipped in version 1, used to prove old saves still open.
LEGACY_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE character (
    id INTEGER PRIMARY KEY CHECK (id = 1), name TEXT NOT NULL, archetype TEXT NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0, coins INTEGER NOT NULL DEFAULT 0,
    coins_earned INTEGER NOT NULL DEFAULT 0, stats TEXT NOT NULL DEFAULT '{}',
    total_completions INTEGER NOT NULL DEFAULT 0, day_streak INTEGER NOT NULL DEFAULT 0,
    best_day_streak INTEGER NOT NULL DEFAULT 0, last_active_day TEXT, created_at TEXT NOT NULL);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    stat TEXT NOT NULL DEFAULT 'str', xp INTEGER NOT NULL DEFAULT 5, coins INTEGER NOT NULL DEFAULT 5,
    icon TEXT NOT NULL DEFAULT 'x', color TEXT NOT NULL DEFAULT '#f59e0b',
    difficulty TEXT NOT NULL DEFAULT 'easy', streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0, completions INTEGER NOT NULL DEFAULT 0,
    last_completed TEXT, created_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, ts TEXT NOT NULL,
    day TEXT NOT NULL, xp INTEGER NOT NULL DEFAULT 0, coins INTEGER NOT NULL DEFAULT 0,
    multiplier REAL NOT NULL DEFAULT 1.0);
CREATE TABLE inventory (item_id TEXT PRIMARY KEY, acquired_at TEXT NOT NULL);
CREATE TABLE equipped (slot TEXT PRIMARY KEY, item_id TEXT NOT NULL);
CREATE TABLE achievements (id TEXT PRIMARY KEY, unlocked_at TEXT NOT NULL);
CREATE TABLE activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, day TEXT NOT NULL,
    kind TEXT NOT NULL, icon TEXT NOT NULL DEFAULT 'x', text TEXT NOT NULL);
"""


class SessionTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-session-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def make(self, name, mode, minutes, difficulty="easy", xp=20, coins=15):
        return self.game.create_task({
            "name": name, "stat": "str", "xp": xp, "coins": coins,
            "mode": mode, "duration_minutes": minutes, "difficulty": difficulty,
        })

    def rewind(self, seconds):
        """Pretend the running session started ``seconds`` ago."""
        session = self.game.active_session()
        started = datetime.now() - timedelta(seconds=seconds)
        self.game._conn.execute(
            "UPDATE sessions SET started_at = ?, ends_at = ? WHERE id = ?",
            (started.isoformat(timespec="milliseconds"),
             (started + timedelta(seconds=session["duration_seconds"])).isoformat(
                 timespec="milliseconds"),
             session["id"]),
        )
        self.game._conn.commit()

    def hp(self):
        char = self.game._character()
        return self.game._hp_for(char)


class TestSessionMaths(unittest.TestCase):
    """The pure rules behind the timer."""

    def test_speed_bonus_scales_with_time_to_spare(self):
        self.assertEqual(E.speed_bonus(100, 100), 0.0)          # no time left
        self.assertAlmostEqual(E.speed_bonus(50, 100), 0.25, 3)  # half the window
        self.assertAlmostEqual(E.speed_bonus(0, 100), 0.5, 3)    # finished instantly

    def test_speed_bonus_is_capped(self):
        self.assertLessEqual(E.speed_bonus(0, 3600), D.SPEED_BONUS_CAP)

    def test_speed_bonus_survives_a_zero_length_window(self):
        self.assertEqual(E.speed_bonus(10, 0), 0.0)

    def test_session_bonus_per_mode(self):
        self.assertAlmostEqual(E.session_bonus("beat_clock", 0, 100), 0.5, 3)
        self.assertEqual(E.session_bonus("endure", 100, 100), D.ENDURE_BONUS)
        self.assertEqual(E.session_bonus("instant", 0, 0), 0.0)

    def test_rewards_include_the_mode_bonus(self):
        task = {"xp": 20, "coins": 10, "difficulty": "easy"}
        base = E.compute_rewards(task, 1, False)
        endure = E.session_rewards(task, 1, False, "endure", 600, 600)
        swift = E.session_rewards(task, 1, False, "beat_clock", 50, 100)
        self.assertEqual(endure["xp"], int(round(base["xp"] * (1 + D.ENDURE_BONUS))))
        self.assertGreater(swift["xp"], base["xp"])
        self.assertEqual(endure["endure_bonus"], D.ENDURE_BONUS)
        self.assertEqual(swift["speed_bonus"], 0.25)
        self.assertEqual(endure["speed_bonus"], 0.0)

    def test_outcome_classification(self):
        self.assertEqual(E.session_outcome("beat_clock", 599, 600), "won")
        self.assertEqual(E.session_outcome("beat_clock", 601, 600), "won")   # inside grace
        self.assertEqual(E.session_outcome("beat_clock", 700, 600), "hit")
        self.assertEqual(E.session_outcome("endure", 700, 600), "won")
        self.assertEqual(E.session_outcome("endure", 60, 600), "too_early")

    def test_wounded_penalty_halves_gold_only(self):
        rewards = {"xp": 10, "coins": 20}
        hurt = E.apply_wounded_penalty(rewards, True)
        self.assertEqual(hurt["coins"], 10)
        self.assertEqual(hurt["xp"], 10)
        self.assertTrue(hurt["wounded"])
        self.assertEqual(E.apply_wounded_penalty(rewards, False)["coins"], 20)

    def test_health_grows_with_vitality(self):
        self.assertEqual(E.max_hp({"vit": 0}), D.MAX_HP_BASE)
        self.assertEqual(E.max_hp({"vit": 6}), D.MAX_HP_BASE + 6 * D.MAX_HP_PER_VIT)

    def test_hit_damage_scales_with_difficulty(self):
        maximum = 100
        easy = E.hit_damage("easy", maximum)
        hard = E.hit_damage("hard", maximum)
        epic = E.hit_damage("epic", maximum)
        self.assertLess(easy, hard)
        self.assertLess(hard, epic)
        self.assertEqual(easy, 8)
        self.assertGreaterEqual(E.hit_damage("tiny", 1), 1)   # never zero damage

    def test_healing_is_proportional_but_never_trivial(self):
        self.assertGreaterEqual(E.heal_per_completion(1), D.HEAL_MIN_PER_COMPLETION)
        self.assertEqual(E.heal_per_completion(100), 6)
        self.assertEqual(E.rest_heal(100), 10)

    def test_timestamp_helpers(self):
        self.assertGreaterEqual(E.seconds_between(None, E.now_stamp()), 0.0)
        start = E.now_stamp()
        self.assertLess(E.seconds_between(start, E.now_stamp()), 2.0)
        self.assertIsNone(E.parse_stamp("rubbish"))


class TestTaskModes(SessionTestBase):
    def test_defaults_to_an_instant_quest(self):
        task = self.game.create_task({"name": "Plain"})
        self.assertEqual(task["mode"], "instant")
        self.assertFalse(task["is_timed"])
        self.assertEqual(task["duration_minutes"], 0)
        self.assertEqual(task["duration_label"], "")

    def test_timed_task_keeps_its_duration(self):
        task = self.make("Read", "endure", 30)
        self.assertTrue(task["is_timed"])
        self.assertEqual(task["duration_minutes"], 30)
        self.assertEqual(task["duration_label"], "30 min")
        self.assertEqual(task["mode_label"], "Stay the Course")

    def test_unknown_mode_falls_back_to_instant(self):
        task = self.game.create_task({"name": "Odd", "mode": "teleport"})
        self.assertEqual(task["mode"], "instant")

    def test_duration_is_clamped_and_defaulted(self):
        self.assertEqual(self.make("Long", "endure", 99999)["duration_minutes"],
                         D.SESSION_MAX_MINUTES)
        self.assertEqual(self.make("Short", "beat_clock", 0)["duration_minutes"], 20)

    def test_switching_to_instant_clears_the_timer(self):
        task = self.make("Read", "endure", 30)
        updated = self.game.update_task(task["id"], {"mode": "instant"})
        self.assertFalse(updated["is_timed"])
        self.assertEqual(updated["duration_minutes"], 0)

    def test_switching_to_timed_gets_a_duration(self):
        task = self.game.create_task({"name": "Plain"})
        updated = self.game.update_task(task["id"], {"mode": "beat_clock"})
        self.assertTrue(updated["is_timed"])
        self.assertGreaterEqual(updated["duration_minutes"], D.SESSION_MIN_MINUTES)

    def test_instant_completion_is_refused_on_a_timed_quest(self):
        task = self.make("Sweep", "beat_clock", 20)
        with self.assertRaises(GameError):
            self.game.complete_task(task["id"])

    def test_sessions_cannot_start_on_an_instant_quest(self):
        task = self.game.create_task({"name": "Plain"})
        with self.assertRaises(GameError):
            self.game.start_session(task["id"])

    def test_duration_labels(self):
        self.assertEqual(self.make("a", "endure", 20)["duration_label"], "20 min")
        self.assertEqual(self.make("b", "endure", 60)["duration_label"], "1 hr")
        self.assertEqual(self.make("c", "endure", 90)["duration_label"], "1 hr 30 min")


class TestSessionLifecycle(SessionTestBase):
    def test_starting_a_session_arms_the_clock(self):
        task = self.make("Sweep", "beat_clock", 20)
        result = self.game.start_session(task["id"])
        session = result["session"]
        self.assertEqual(result["outcome"], "started")
        self.assertEqual(session["task_id"], task["id"])
        self.assertEqual(session["mode"], "beat_clock")
        self.assertEqual(session["duration_seconds"], 1200)
        self.assertFalse(session["ready"])
        self.assertAlmostEqual(session["remaining_seconds"], 1200, delta=3)
        self.assertEqual(self.game.active_session()["id"], session["id"])

    def test_only_one_session_runs_at_a_time(self):
        first = self.make("Sweep", "beat_clock", 20)
        second = self.make("Read", "endure", 30)
        self.game.start_session(first["id"])
        with self.assertRaises(GameError):
            self.game.start_session(second["id"])

    def test_a_quest_cannot_be_restarted_the_same_day(self):
        task = self.make("Sweep", "beat_clock", 20)
        self.game.start_session(task["id"])
        self.rewind(1190)
        self.game.finish_session(task["id"])
        with self.assertRaises(GameError):
            self.game.start_session(task["id"])

    def test_beat_the_clock_win_pays_a_speed_bonus(self):
        task = self.make("Sweep", "beat_clock", 20, xp=20, coins=10)
        self.game.start_session(task["id"])
        self.rewind(600)                      # 10 of 20 minutes to spare
        result = self.game.finish_session(task["id"])
        self.assertEqual(result["outcome"], "won")
        self.assertAlmostEqual(result["rewards"]["speed_bonus"], 0.25, 2)
        self.assertGreater(result["rewards"]["xp"], 20)
        state = result["state"]
        self.assertTrue([t for t in state["tasks"] if t["id"] == task["id"]][0]["completed_today"])
        self.assertIsNone(state["session"])

    def test_a_win_counts_as_a_normal_completion(self):
        task = self.make("Sweep", "beat_clock", 20)
        self.game.start_session(task["id"])
        self.rewind(600)
        state = self.game.finish_session(task["id"])["state"]
        self.assertEqual(state["character"]["total_completions"], 1)
        self.assertEqual(state["history"]["series"][-1]["count"], 1)
        self.assertEqual(state["tasks"][0]["streak"], 1)

    def test_beating_the_clock_late_is_a_hit(self):
        task = self.make("Sweep", "beat_clock", 10, difficulty="hard")
        self.game.start_session(task["id"])
        before, maximum = self.hp()
        self.rewind(700)
        result = self.game.finish_session(task["id"])
        self.assertEqual(result["outcome"], "hit")
        self.assertEqual(result["damage"], E.hit_damage("hard", maximum))
        after = result["state"]["character"]
        self.assertEqual(after["hp"], before - result["damage"])
        self.assertEqual(self.game.active_session(), None)

    def test_a_hit_breaks_the_task_streak_and_awards_nothing(self):
        task = self.make("Sweep", "beat_clock", 10)
        self.game.start_session(task["id"])
        xp_before = self.game.state()["character"]["xp"]
        self.rewind(700)
        state = self.game.finish_session(task["id"])["state"]
        entry = [t for t in state["tasks"] if t["id"] == task["id"]][0]
        self.assertEqual(entry["streak"], 0)
        self.assertEqual(entry["sessions_lost"], 1)
        self.assertEqual(state["character"]["xp"], xp_before)
        self.assertEqual(state["character"]["total_completions"], 0)

    def test_a_hit_is_written_to_the_log(self):
        task = self.make("Sweep", "beat_clock", 10)
        self.game.start_session(task["id"])
        self.rewind(700)
        self.game.finish_session(task["id"])
        self.assertEqual(self.game.activity(1)[0]["kind"], "hit")

    def test_endure_refuses_to_finish_early(self):
        task = self.make("Read", "endure", 30)
        self.game.start_session(task["id"])
        with self.assertRaises(GameError) as ctx:
            self.game.finish_session(task["id"])
        self.assertIn("Not yet", str(ctx.exception))
        self.assertIsNotNone(self.game.active_session())   # still running

    def test_endure_wins_once_the_time_is_served(self):
        task = self.make("Read", "endure", 30, xp=20, coins=10)
        self.game.start_session(task["id"])
        self.rewind(30 * 60 + 45)
        result = self.game.finish_session(task["id"])
        self.assertEqual(result["outcome"], "won")
        self.assertEqual(result["rewards"]["endure_bonus"], D.ENDURE_BONUS)
        self.assertGreater(result["rewards"]["xp"], 20)

    def test_endure_can_run_over(self):
        task = self.make("Read", "endure", 30)
        self.game.start_session(task["id"])
        self.rewind(30 * 60 + 3600)
        session = self.game.state()["session"]
        self.assertTrue(session["ready"])
        self.assertTrue(session["overdue"])
        self.assertEqual(session["remaining_seconds"], 0)
        self.assertEqual(self.game.finish_session(task["id"])["outcome"], "won")

    def test_giving_up_early_costs_nothing(self):
        task = self.make("Read", "endure", 30)
        self.game.start_session(task["id"])
        before = self.game.state()["character"]
        result = self.game.abandon_session(task["id"])
        self.assertEqual(result["outcome"], "abandoned")
        self.assertIsNone(self.game.active_session())
        after = result["state"]["character"]
        self.assertEqual(after["hp"], before["hp"])
        self.assertEqual(after["xp"], before["xp"])

    def test_giving_up_after_the_bell_still_takes_the_hit(self):
        task = self.make("Sweep", "beat_clock", 5)
        self.game.start_session(task["id"])
        self.rewind(5 * 60 + 30)
        result = self.game.abandon_session(task["id"])
        self.assertEqual(result["outcome"], "hit")
        self.assertGreater(result["damage"], 0)

    def test_finishing_without_a_session_is_an_error(self):
        task = self.make("Sweep", "beat_clock", 10)
        with self.assertRaises(GameError):
            self.game.finish_session(task["id"])

    def test_a_window_that_closed_while_away_is_settled_on_next_read(self):
        task = self.make("Sweep", "beat_clock", 5, difficulty="tiny")
        self.game.start_session(task["id"])
        before, _ = self.hp()
        self.rewind(5 * 60 + 120)

        state = self.game.state()             # what a page load sees
        self.assertEqual(state["character"]["hp"], before - E.hit_damage("tiny", state["character"]["max_hp"]))
        self.assertIsNone(state["session"])
        self.assertTrue(state["settled"])
        self.assertEqual(state["settled"][0]["task_id"], task["id"])
        self.assertEqual(self.game.state()["settled"], [])   # reported once only

    def test_pressing_finish_at_the_buzzer_reports_the_hit(self):
        """The settle sweep must not swallow the outcome the hero earned."""
        task = self.make("Sweep", "beat_clock", 10)
        self.game.start_session(task["id"])
        self.rewind(10 * 60 + 30)
        result = self.game.finish_session(task["id"])
        self.assertEqual(result["outcome"], "hit")
        self.assertGreater(result["damage"], 0)

    def test_endure_is_never_settled_in_the_background(self):
        task = self.make("Read", "endure", 30)
        self.game.start_session(task["id"])
        self.rewind(30 * 60 + 3600)
        self.assertIsNotNone(self.game.active_session())
        self.assertEqual(self.game.state()["settled"], [])

    def test_deleting_a_quest_clears_its_sessions(self):
        task = self.make("Sweep", "beat_clock", 10)
        self.game.start_session(task["id"])
        self.game.delete_task(task["id"])
        self.assertIsNone(self.game.active_session())
        rows = self.game._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        self.assertEqual(rows, 0)


class TestHealth(SessionTestBase):
    def test_a_new_hero_starts_at_full_health(self):
        char = self.game.state()["character"]
        self.assertEqual(char["hp"], char["max_hp"])
        self.assertFalse(char["downed"])
        self.assertEqual(char["hp_pct"], 1.0)

    def test_gear_raises_maximum_health(self):
        before = self.game.state()["character"]["max_hp"]
        self.game._conn.execute("UPDATE character SET coins = 5000 WHERE id = 1")
        self.game._conn.commit()
        self.game.buy_item("wooden_sword")            # +1 STR, no VIT
        self.assertEqual(self.game.state()["character"]["max_hp"], before)
        self.game._conn.execute("UPDATE character SET coins = 5000 WHERE id = 1")
        self.game._conn.commit()
        self.game.buy_item("leather_cap")             # +1 VIT
        self.game.equip_item("leather_cap")
        self.assertGreater(self.game.state()["character"]["max_hp"], before)

    def test_completing_a_quest_heals(self):
        task = self.make("Sweep", "beat_clock", 10)
        self.game.start_session(task["id"])
        self.rewind(700)
        self.game.finish_session(task["id"])         # take a hit first
        hurt = self.game.state()["character"]["hp"]
        inst = self.game.create_task({"name": "Water", "xp": 1, "coins": 1})
        healed = self.game.complete_task(inst["id"])["state"]["character"]["hp"]
        self.assertGreater(healed, hurt)

    def test_health_never_exceeds_the_maximum(self):
        for name in ("a", "b", "c", "d"):
            task = self.game.create_task({"name": name, "xp": 1, "coins": 1})
            self.game.complete_task(task["id"])
        char = self.game.state()["character"]
        self.assertLessEqual(char["hp"], char["max_hp"])

    def test_a_level_up_is_a_full_rest(self):
        big = self.game.create_task({"name": "Epic", "xp": 500, "coins": 10})
        self.game._conn.execute("UPDATE character SET hp = 1 WHERE id = 1")
        self.game._conn.commit()
        char = self.game.complete_task(big["id"])["state"]["character"]
        self.assertGreater(char["level"], 1)
        self.assertEqual(char["hp"], char["max_hp"])

    def test_a_wounded_hero_earns_half_gold(self):
        task = self.game.create_task({"name": "Water", "xp": 10, "coins": 20})
        self.game._conn.execute("UPDATE character SET hp = 0 WHERE id = 1")
        self.game._conn.commit()
        state = self.game.state()
        self.assertTrue(state["character"]["downed"])
        result = self.game.complete_task(task["id"])
        self.assertTrue(result["rewards"]["wounded"])
        # This is the first quest of the day, so the +20% daily bonus applies
        # first and the wounded penalty halves what is left.
        full = E.compute_rewards({"xp": 10, "coins": 20, "difficulty": "easy"}, 1, True)
        self.assertEqual(result["rewards"]["coins"],
                         int(round(full["coins"] * D.WOUNDED_COIN_MULTIPLIER)))
        self.assertEqual(result["rewards"]["xp"], full["xp"])   # XP is untouched

    def test_undo_reverses_the_healing_too(self):
        task = self.game.create_task({"name": "Water", "xp": 10, "coins": 10})
        self.game._conn.execute("UPDATE character SET hp = 50 WHERE id = 1")
        self.game._conn.commit()
        before = self.game.state()["character"]["hp"]
        self.game.complete_task(task["id"])
        after_undo = self.game.undo_task(task["id"])["state"]["character"]["hp"]
        self.assertEqual(after_undo, before)


class TestSessionAchievements(SessionTestBase):
    def test_winning_a_session_feeds_the_metrics(self):
        task = self.make("Sweep", "beat_clock", 20)
        self.game.start_session(task["id"])
        self.rewind(600)
        unlocked = self.game.finish_session(task["id"])["unlocked"]
        self.assertIn("first_session", {a["id"] for a in unlocked})

    def test_a_swift_win_needs_half_the_time_spare(self):
        task = self.make("Sweep", "beat_clock", 20)
        self.game.start_session(task["id"])
        self.rewind(19 * 60)          # very little to spare
        self.game.finish_session(task["id"])
        counts = self.game._session_metrics()
        self.assertEqual(counts["sessions_won"], 1)
        self.assertEqual(counts["swift_wins"], 0)

        second = self.make("Quick", "beat_clock", 20)
        self.game.start_session(second["id"])
        self.rewind(60)
        self.game.finish_session(second["id"])
        self.assertEqual(self.game._session_metrics()["swift_wins"], 1)

    def test_endure_wins_are_counted_separately(self):
        task = self.make("Read", "endure", 30)
        self.game.start_session(task["id"])
        self.rewind(30 * 60)
        self.game.finish_session(task["id"])
        counts = self.game._session_metrics()
        self.assertEqual(counts["endure_won"], 1)
        self.assertEqual(counts["sessions_won"], 1)
        self.assertEqual(counts["sessions_lost"], 0)

    def test_winning_while_wounded_counts(self):
        task = self.make("Sweep", "beat_clock", 20)
        self.game._conn.execute("UPDATE character SET hp = 0 WHERE id = 1")
        self.game._conn.commit()
        self.game.start_session(task["id"])
        self.rewind(600)
        self.game.finish_session(task["id"])
        self.assertEqual(self.game._session_metrics()["wounded_wins"], 1)

    def test_hits_are_counted(self):
        task = self.make("Sweep", "beat_clock", 5)
        self.game.start_session(task["id"])
        self.rewind(400)
        self.game.finish_session(task["id"])
        self.assertEqual(self.game._session_metrics()["sessions_lost"], 1)


class TestLegacySaveMigration(unittest.TestCase):
    """A save written by version 1 must open, upgrade and keep the hero."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-legacy-")
        self.path = os.path.join(self.tmp, "legacy.db")
        con = sqlite3.connect(self.path)
        con.executescript(LEGACY_SCHEMA)
        con.execute(
            """INSERT INTO character (id, name, archetype, xp, coins, coins_earned, stats,
                   total_completions, day_streak, best_day_streak, last_active_day, created_at)
               VALUES (1, 'Veteran', 'ranger', 1500, 400, 900,
                       '{"str": 5, "int": 4, "vit": 7, "agi": 6, "cha": 2}', 42, 3, 10,
                       '2026-01-01', '2026-01-01T09:00:00')""")
        con.execute(
            """INSERT INTO tasks (name, description, stat, xp, coins, icon, color, difficulty,
                   streak, best_streak, completions, created_at, sort_order)
               VALUES ('Old habit', 'from v1', 'vit', 12, 9, 'x', '#22c55e', 'normal',
                       4, 7, 20, '2026-01-01T09:00:00', 0)""")
        con.execute(
            """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier)
               VALUES (1, '2026-01-02T08:00:00', '2026-01-02', 12, 9, 1.0)""")
        con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        con.commit()
        con.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_old_save_opens_and_keeps_its_history(self):
        game = Game(self.path)
        try:
            state = game.state()
            self.assertTrue(state["has_character"])
            char = state["character"]
            self.assertEqual(char["name"], "Veteran")
            self.assertEqual(char["xp"], 1500)
            self.assertEqual(char["coins"], 400)
            self.assertEqual(char["total_completions"], 42)
            self.assertEqual(char["level"], E.level_from_xp(1500)["level"])

            task = state["tasks"][0]
            self.assertEqual(task["name"], "Old habit")
            self.assertEqual(task["streak"], 4)
            self.assertEqual(task["best_streak"], 7)

            # The history series only covers a recent window, so this January
            # completion is outside it - the lifetime total still counts it.
            self.assertEqual(state["history"]["total_completions"], 0)
            self.assertEqual(game._conn.execute(
                "SELECT COUNT(*) FROM completions").fetchone()[0], 1)
            self.assertIn("inventory", state)
        finally:
            game.close()

    def test_migration_gives_the_hero_health_and_new_task_fields(self):
        game = Game(self.path)
        try:
            char = game.state()["character"]
            # 40 base + 7 VIT * 10; the old 0 must be read as "not set yet".
            self.assertEqual(char["max_hp"], D.MAX_HP_BASE + 7 * D.MAX_HP_PER_VIT)
            self.assertEqual(char["hp"], char["max_hp"])
            self.assertFalse(char["downed"])

            task = game.state()["tasks"][0]
            self.assertEqual(task["mode"], "instant")
            self.assertFalse(task["is_timed"])
            self.assertEqual(task["duration_minutes"], 0)
            self.assertEqual(task["sessions_won"], 0)
        finally:
            game.close()

    def test_migration_is_idempotent(self):
        for _ in range(3):
            game = Game(self.path)
            char = game.state()["character"]
            self.assertEqual(char["hp"], char["max_hp"])
            game.close()

    def test_a_migrated_save_can_run_sessions(self):
        game = Game(self.path)
        try:
            task = game.create_task({"name": "Sweep", "xp": 10, "coins": 5,
                                     "mode": "beat_clock", "duration_minutes": 5})
            game.start_session(task["id"])
            self.assertIsNotNone(game.active_session())
            started = datetime.now() - timedelta(seconds=60)
            game._conn.execute(
                "UPDATE sessions SET started_at = ? WHERE status = 'active'",
                (started.isoformat(timespec="milliseconds"),))
            game._conn.commit()
            result = game.finish_session(task["id"])
            self.assertEqual(result["outcome"], "won")
        finally:
            game.close()

    def test_schema_version_is_bumped(self):
        game = Game(self.path)
        try:
            row = game._one("SELECT value FROM meta WHERE key = 'schema_version'")
            self.assertEqual(row["value"], "2")
        finally:
            game.close()


class TestSessionApi(unittest.TestCase):
    """The HTTP surface the browser actually calls."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-session-api-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.httpd = build_server(self.game, host="127.0.0.1", port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        data = None
        headers = {}
        if body is not None:
            data = __import__("json").dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, __import__("json").loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, __import__("json").loads(exc.read().decode())

    def post(self, path, body=None):
        return self.call("POST", path, body or {})

    def test_full_session_over_http(self):
        self.post("/api/character", {"name": "Ada", "archetype": "mage"})
        status, payload = self.post("/api/tasks", {
            "name": "Read", "stat": "int", "xp": 20, "coins": 10,
            "mode": "endure", "duration_minutes": 30,
        })
        self.assertEqual(status, 201)
        task_id = payload["task"]["id"]
        self.assertTrue(payload["task"]["is_timed"])

        status, payload = self.post(f"/api/tasks/{task_id}/session/start")
        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "started")
        self.assertEqual(payload["session"]["duration_seconds"], 1800)
        self.assertEqual(payload["state"]["session"]["task_id"], task_id)

        # Finishing too early is a readable 400.
        status, payload = self.post(f"/api/tasks/{task_id}/session/finish")
        self.assertEqual(status, 400)
        self.assertIn("Not yet", payload["error"])

        # An instant completion of a timed quest is refused too.
        status, payload = self.post(f"/api/tasks/{task_id}/complete")
        self.assertEqual(status, 400)
        self.assertIn("timed session", payload["error"])

        status, payload = self.post(f"/api/tasks/{task_id}/session/abandon")
        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "abandoned")
        self.assertIsNone(payload["state"]["session"])

    def test_state_exposes_the_clock_and_health(self):
        self.post("/api/character", {"name": "Ada", "archetype": "warrior"})
        status, state = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertIn("session", state)
        self.assertIn("server_now", state)
        self.assertIn("hp", state["character"])
        self.assertIn("max_hp", state["character"])
        self.assertIn("downed", state["character"])
        self.assertIn("session_modes", state["meta"])
        self.assertIn("duration_presets", state["meta"])

    def test_the_active_session_has_its_own_endpoint(self):
        self.post("/api/character", {"name": "Ada", "archetype": "rogue"})
        status, payload = self.call("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertIsNone(payload["session"])

        _, created = self.post("/api/tasks", {
            "name": "Sweep", "xp": 5, "coins": 5, "mode": "beat_clock", "duration_minutes": 15,
        })
        self.post(f"/api/tasks/{created['task']['id']}/session/start")
        status, payload = self.call("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertEqual(payload["session"]["mode"], "beat_clock")

    def test_finishing_a_quest_with_no_session_is_a_readable_error(self):
        self.post("/api/character", {"name": "Ada", "archetype": "rogue"})
        _, created = self.post("/api/tasks", {
            "name": "Sweep", "xp": 5, "coins": 5, "mode": "beat_clock", "duration_minutes": 15,
        })
        status, payload = self.post(f"/api/tasks/{created['task']['id']}/session/finish")
        self.assertEqual(status, 400)
        self.assertIn("No session", payload["error"])


if __name__ == "__main__":
    unittest.main()
