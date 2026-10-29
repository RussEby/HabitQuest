"""Tests for the nightly reckoning.

Days are scored when the first state after a date change is built; the tests
seed the ``reckoned_day`` ledger and backdate tasks to make the past real,
rather than sleeping or patching the clock.
"""

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from habitquest import data as D
from habitquest import engine as E
from habitquest.store import Game

YESTERDAY = lambda: (date.today() - timedelta(days=1)).isoformat()
TWO_DAYS_AGO = lambda: (date.today() - timedelta(days=2)).isoformat()


class ReckoningTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-reckoning-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def add_task(self, name="Sweep", difficulty="easy", mode="instant",
                 duration=None, created=TWO_DAYS_AGO()):
        payload = {"name": name, "stat": "agi", "xp": 5, "coins": 5,
                   "difficulty": difficulty, "mode": mode,
                   "description": "test", "icon": "🧹", "color": "#84cc16"}
        if duration:
            payload["duration_minutes"] = duration
        self.game._insert_task(payload)
        if created:
            self.game._conn.execute(
                "UPDATE tasks SET created_at = ? WHERE name = ?", (created + "T08:00:00", name))
            self.game._conn.commit()
        return self.game._one("SELECT * FROM tasks WHERE name = ?", (name,))

    def seed_ledger(self, day=None):
        """Point the ledger at ``day`` (default: two days ago) so yesterday is unscored."""
        self.game._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reckoned_day', ?)",
            (day or TWO_DAYS_AGO(),))
        self.game._conn.commit()


class TestPerLevelHealth(ReckoningTestBase):
    def test_max_hp_grows_with_level(self):
        self.assertEqual(E.max_hp({"vit": 0}, 1), D.MAX_HP_BASE)
        self.assertEqual(E.max_hp({"vit": 0}, 4),
                         D.MAX_HP_BASE + 3 * D.MAX_HP_PER_LEVEL)
        self.assertEqual(E.max_hp({"vit": 5}, 3),
                         D.MAX_HP_BASE + 5 * D.MAX_HP_PER_VIT + 2 * D.MAX_HP_PER_LEVEL)

    def test_level_arg_is_optional_for_old_callers(self):
        self.assertEqual(E.max_hp({"vit": 2}), D.MAX_HP_BASE + 2 * D.MAX_HP_PER_VIT)

    def test_store_uses_level_in_max_hp(self):
        self.game._conn.execute("UPDATE character SET xp = 3000 WHERE id = 1")
        self.game._conn.commit()
        meta = self.game.character_meta()
        vit = D.ARCHETYPE_BY_ID["warrior"]["stats"]["vit"]
        expected = (D.MAX_HP_BASE + vit * D.MAX_HP_PER_VIT
                    + (meta["level"] - 1) * D.MAX_HP_PER_LEVEL)
        self.assertEqual(meta["max_hp"], expected)

    def test_existing_hp_survives_a_level_up(self):
        self.game._set_hp(30)
        self.game._conn.execute("UPDATE character SET xp = 5000 WHERE id = 1")
        self.game._conn.commit()
        meta = self.game.character_meta()
        self.assertGreater(meta["max_hp"], D.MAX_HP_BASE + 5 * D.MAX_HP_PER_VIT)
        self.assertEqual(meta["hp"], 30)  # damage is not healed by a bigger bar


class TestMissedDayDamage(ReckoningTestBase):
    def test_idle_day_costs_health(self):
        self.add_task(difficulty="easy")            # 8% of max
        hp_full = self.game.state()["character"]["max_hp"]
        self.seed_ledger()
        self.game._apply_day_reckoning()
        char = self.game.state()["character"]
        expected = E.miss_damage("easy", hp_full)
        self.assertEqual(char["hp"], hp_full - expected)

    def test_damage_scales_with_difficulty(self):
        self.add_task(name="Tiny", difficulty="tiny")
        self.add_task(name="Epic", difficulty="epic")
        self.seed_ledger()
        self.game._apply_day_reckoning()
        r = self.game.state()["day_reckoning"]
        by_name = {m["name"]: m["damage"] for m in r["missed"]}
        self.assertGreater(by_name["Epic"], by_name["Tiny"])

    def test_scored_exactly_once(self):
        self.add_task()
        self.seed_ledger()
        self.game._apply_day_reckoning()
        first = self.game.state()["character"]["hp"]
        self.game._apply_day_reckoning()
        self.assertEqual(self.game.state()["character"]["hp"], first)

    def test_completion_forgives_that_task(self):
        task = self.add_task()
        self.game._conn.execute(
            "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
            (task["id"], YESTERDAY() + "T10:00:00", YESTERDAY()))
        self.game._conn.commit()
        self.seed_ledger()
        hp_before = self.game.state()["character"]["hp"]
        self.game._apply_day_reckoning()
        st = self.game.state()
        # Nothing was missed: no reckoning event, no damage.
        self.assertEqual(st["day_reckoning"], None)
        self.assertEqual(st["character"]["hp"], hp_before)

    def test_a_timed_session_that_started_forgives_the_task(self):
        self.add_task(mode="beat_clock", duration=20)
        self.seed_ledger()
        y = YESTERDAY()
        self.game._conn.execute(
            """INSERT INTO sessions (task_id, mode, started_at, ends_at, duration_seconds, status)
               VALUES (?, 'beat_clock', ?, ?, 1200, 'won')""",
            (self.game._one("SELECT id FROM tasks")["id"], y + "T10:00:00", y + "T10:20:00"))
        self.game._conn.commit()
        hp_before = self.game.state()["character"]["hp"]
        self.game._apply_day_reckoning()
        st = self.game.state()
        self.assertIsNone(st["day_reckoning"])
        self.assertEqual(st["character"]["hp"], hp_before)

    def test_absence_is_clamped(self):
        for i in range(5):
            self.add_task(name=f"Q{i}")
        self.seed_ledger(day=(date.today() - timedelta(days=D.RECKONING_LOOKBACK_DAYS + 30)).isoformat())
        self.game._apply_day_reckoning()
        char = self.game.state()["character"]
        # Five tasks at ~easy damage cannot wipe a clamped lookback pool.
        self.assertGreater(char["hp"], 0)

    def test_no_fine_for_days_before_the_ledger_existed(self):
        # A brand-new save arms its ledger without scoring anything: even a
        # suspiciously backdated task is not retro-fined on first open.
        self.add_task(created=(date.today() - timedelta(days=3)).isoformat())
        hp_full = self.game.state()["character"]["max_hp"]
        st = self.game.state()
        self.assertEqual(st["character"]["hp"], hp_full)   # untouched
        self.assertIsNone(st["day_reckoning"])
        # and the ledger is armed for the following days
        armed = self.game._one("SELECT value FROM meta WHERE key = 'reckoned_day'")
        self.assertTrue(armed and armed["value"] >= YESTERDAY())


class TestPerfectDay(ReckoningTestBase):
    def test_completing_everything_mends_to_full(self):
        a = self.add_task(name="A")
        self.add_task(name="B")
        self.game._set_hp(40)   # damage the hero first
        for t in (a, self.game._one("SELECT * FROM tasks WHERE name = 'B'")):
            self.game._conn.execute(
                "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
                (t["id"], date.today().isoformat() + "T09:00:00", date.today().isoformat()))
        self.game._conn.commit()
        self.game._apply_completion(
            a, {"xp": 5, "coins": 5, "multiplier": 1.0, "streak": 1,
                "streak_multiplier": 1.0, "daily_bonus": False},
            streak=1)
        char = self.game.character_meta()
        self.assertEqual(char["hp"], char["max_hp"])

    def test_one_miss_breaks_the_perfect_day(self):
        self.add_task(name="A")
        self.add_task(name="B")
        self.game._set_hp(60)
        a = self.game._one("SELECT * FROM tasks WHERE name = 'A'")
        self.game._conn.execute(
            "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
            (a["id"], date.today().isoformat() + "T09:00:00", date.today().isoformat()))
        self.game._conn.commit()
        self.game._apply_completion(
            a, {"xp": 5, "coins": 5, "multiplier": 1.0, "streak": 1,
                "streak_multiplier": 1.0, "daily_bonus": False},
            streak=1)
        char = self.game.character_meta()
        self.assertLess(char["hp"], char["max_hp"])

    def test_perfect_day_heals_wounded_hero(self):
        self.add_task(name="A")
        a = self.game._one("SELECT * FROM tasks WHERE name = 'A'")
        self.game._set_hp(0)            # knocked out
        self.game._conn.execute(
            "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
            (a["id"], date.today().isoformat() + "T09:00:00", date.today().isoformat()))
        self.game._conn.commit()
        self.game._apply_completion(
            a, {"xp": 5, "coins": 5, "multiplier": 1.0, "streak": 1,
                "streak_multiplier": 1.0, "daily_bonus": False},
            streak=1)
        char = self.game.character_meta()
        self.assertEqual(char["hp"], char["max_hp"])
        self.assertFalse(char["downed"])


class TestOverload(ReckoningTestBase):
    def test_warning_fires_when_beaten_down_and_behind(self):
        for i, diff in enumerate(("normal", "hard", "epic")):
            self.add_task(name=f"Q{i}", difficulty=diff)
        char = self.game._character()
        self.game._conn.execute("UPDATE character SET hp = 40 WHERE id = 1")
        self.game._conn.commit()
        summary = self.game._overload_summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary["missed_count"], 3)
        self.assertIn("trim", summary["message"])

    def test_warning_stays_silent_when_healthy(self):
        for i in range(3):
            self.add_task(name=f"Q{i}", difficulty="normal")
        self.assertIsNone(self.game._overload_summary())  # full HP, not drowning yet

    def test_warning_clears_when_the_log_is_trimmed(self):
        for i in range(3):
            self.add_task(name=f"Q{i}", difficulty="epic")
        self.game._conn.execute("UPDATE character SET hp = 40 WHERE id = 1")
        self.game._conn.commit()
        self.assertIsNotNone(self.game._overload_summary())
        ids = [t["id"] for t in self.game.list_tasks()]
        for tid in ids[:-1]:
            self.game.delete_task(tid)
        self.assertIsNone(self.game._overload_summary())

    def test_warning_shows_remaining_count_only(self):
        a = self.add_task(name="A", difficulty="normal")
        self.add_task(name="B", difficulty="normal")
        self.game._conn.execute("UPDATE character SET hp = 40 WHERE id = 1")
        self.game._conn.commit()
        self.game._conn.execute(
            "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
            (a["id"], date.today().isoformat() + "T09:00:00", date.today().isoformat()))
        self.game._conn.commit()
        # One completed: missed list drops, so the earlier warning de-escalates.
        summary = self.game._overload_summary()
        if summary is not None:
            self.assertEqual(summary["missed_count"], 1)


class TestStatePayload(ReckoningTestBase):
    def test_reckoning_is_delivered_once(self):
        self.add_task()
        self.seed_ledger()
        self.game._apply_day_reckoning()
        first = self.game.state()
        self.assertIsNotNone(first["day_reckoning"])
        self.assertIsNone(self.game.state()["day_reckoning"])

    def test_overload_rides_every_state(self):
        for i in range(3):
            self.add_task(name=f"Q{i}", difficulty="epic")
        self.game._conn.execute("UPDATE character SET hp = 30 WHERE id = 1")
        self.game._conn.commit()
        self.assertIsNotNone(self.game.state()["overload"])
        self.assertIsNotNone(self.game.state()["overload"])  # stays until fixed


class TestDayProbe(ReckoningTestBase):
    """The once-a-minute date check the window polls. It must be side-effect free:
    every actual day turn is scored by the full state build and only by that."""

    def test_probe_reports_a_pending_day_without_scoring_it(self):
        self.add_task("Sweep", difficulty="easy")
        self.seed_ledger()
        hp_before = self.game.character_meta()["hp"]
        probe = self.game.day_probe()
        self.assertEqual(probe["today"], date.today().isoformat())
        self.assertEqual(probe["armed_day"], TWO_DAYS_AGO())
        self.assertEqual(self.game.character_meta()["hp"], hp_before)
        self.assertIsNone(self.game._day_reckoning)

    def test_probe_never_moves_the_ledger(self):
        self.add_task("Sweep")
        self.seed_ledger()
        for _ in range(5):
            self.game.day_probe()
        row = self.game._one("SELECT value FROM meta WHERE key = 'reckoned_day'")
        self.assertEqual(row["value"], TWO_DAYS_AGO())

    def test_probe_after_the_state_build_reports_the_day_as_armed(self):
        self.add_task("Sweep")
        self.seed_ledger()
        self.game.state()
        probe = self.game.day_probe()
        self.assertEqual(probe["armed_day"], date.today().isoformat())

    def test_a_brand_new_save_has_no_armed_day(self):
        fresh = Game(os.path.join(self.tmp, "fresh.db"))
        try:
            self.assertIsNone(fresh.day_probe()["armed_day"])
        finally:
            fresh.close()


if __name__ == "__main__":
    unittest.main()
