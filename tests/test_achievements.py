"""Achievements: stacked families, the requested ladders and their metrics.

Each family is a stack of tiers on one track; the Journal shows one card per
family (the next tier to earn). These tests pin the ladders the player asked
for, then check the metrics that feed the new tracks.
"""

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta

from habitquest import data as D
from habitquest import engine as E
from habitquest.store import Game


def families() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for ach in D.ACHIEVEMENTS:
        out.setdefault(ach["family"], []).append(ach)
    return out


class AchievementDataTests(unittest.TestCase):
    def test_the_requested_ladders_are_all_present(self):
        fam = families()
        self.assertGreaterEqual({a["goal"] for a in fam["task_streak"]},
                                {3, 7, 30, 90, 180, 365})
        self.assertGreaterEqual({a["goal"] for a in fam["level"]}, {5, 10, 20, 50, 100})
        self.assertGreaterEqual({a["goal"] for a in fam["stat"]}, {5, 10, 20, 50, 100})
        self.assertGreaterEqual({a["goal"] for a in fam["per_quest"]}, {1, 5, 10, 25})
        self.assertGreaterEqual({a["goal"] for a in fam["purchases"]}, {1, 5})
        self.assertGreaterEqual({a["goal"] for a in fam["gold"]}, {1000, 5000, 10000})
        self.assertEqual({a["goal"] for a in fam["loadout"]}, {1, 3, 5})

    def test_the_first_quest_of_every_type_has_an_achievement(self):
        fam = families()
        for mode in ("instant", "beat_clock", "endure", "pomodoro"):
            goals = [a["goal"] for a in fam["mode_" + mode]]
            self.assertIn(1, goals, mode)

    def test_there_are_plenty_of_achievements(self):
        self.assertGreaterEqual(len(D.ACHIEVEMENTS), 90)
        self.assertGreaterEqual(len(families()), 20)

    def test_every_stack_is_contiguous_and_unique(self):
        for family, tiers in families().items():
            self.assertEqual([a["tier"] for a in tiers],
                             list(range(1, len(tiers) + 1)), family)
            self.assertEqual(len({a["id"] for a in tiers}), len(tiers), family)
        ids = [a["id"] for a in D.ACHIEVEMENTS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_achievement_has_family_and_tier_metadata(self):
        for ach in D.ACHIEVEMENTS:
            self.assertTrue(ach["family"])
            self.assertGreaterEqual(int(ach["tier"]), 1)
            self.assertIn(ach["track"], {
                "total_completions", "best_task_streak", "best_task_completions",
                "best_day_completions", "level", "top_stat", "min_stat",
                "items_owned", "slots_filled", "coins", "coins_earned",
                "total_xp", "best_day_streak", "longest_day_run",
                "completions_instant", "completions_beat_clock",
                "completions_endure", "completions_pomodoro",
                "sessions_won", "sessions_lost", "endure_won", "swift_wins",
                "wounded_wins",
            }, ach["id"])

    def test_level_cap_reaches_the_top_level_tier(self):
        self.assertGreaterEqual(D.MAX_LEVEL, 100)
        self.assertEqual(E.level_from_xp(E.cumulative_xp(100))["level"], 100)
        self.assertTrue(E.level_from_xp(E.cumulative_xp(100))["max_level"])


class AchievementMetricTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-ach-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_instant_completion_records_its_mode_and_count(self):
        task = self.game.create_task({"name": "Read", "xp": 10, "coins": 10})
        self.game.complete_task(task["id"])

        metrics = self.game._metrics()
        self.assertEqual(metrics["completions_instant"], 1)
        self.assertEqual(metrics["completions_beat_clock"], 0)
        self.assertEqual(metrics["best_task_completions"], 1)
        self.assertEqual(metrics["best_day_completions"], 1)
        row = self.game._one("SELECT mode FROM completions ORDER BY id DESC LIMIT 1")
        self.assertEqual(row["mode"], "instant")

    def test_a_timed_completion_records_its_mode(self):
        task = self.game.create_task({
            "name": "Sweep", "mode": "beat_clock", "duration_minutes": 5,
            "xp": 10, "coins": 5,
        })
        self.game.start_session(task["id"])
        started = datetime.now() - timedelta(seconds=60)
        self.game._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE status = 'active'",
            (started.isoformat(timespec="milliseconds"),))
        self.game._conn.commit()
        result = self.game.finish_session(task["id"])
        self.assertEqual(result["outcome"], "won")

        metrics = self.game._metrics()
        self.assertEqual(metrics["completions_beat_clock"], 1)
        self.assertEqual(metrics["completions_instant"], 0)
        row = self.game._one("SELECT mode FROM completions ORDER BY id DESC LIMIT 1")
        self.assertEqual(row["mode"], "beat_clock")

    def test_a_single_quest_count_unlocks_its_milestones(self):
        task = self.game.create_task({"name": "Floss"})
        self.game._conn.execute(
            "UPDATE tasks SET completions = 5, best_streak = 5 WHERE id = ?",
            (task["id"],))
        self.game._conn.commit()

        unlocked = {a["id"] for a in self.game._check_achievements()}
        self.assertIn("quest_1", unlocked)
        self.assertIn("quest_5", unlocked)
        self.assertNotIn("quest_10", unlocked)

        cards = {a["id"]: a for a in self.game.state()["achievements"]}
        self.assertTrue(cards["quest_5"]["unlocked"])
        self.assertFalse(cards["quest_10"]["unlocked"])

    def test_stacks_expose_family_and_tier_to_the_api(self):
        cards = self.game.state()["achievements"]
        self.assertTrue(cards)
        for card in cards:
            self.assertIn("family", card)
            self.assertIn("tier", card)
            self.assertIn("progress", card)
        level_cards = [c for c in cards if c["family"] == "level"]
        self.assertEqual([c["tier"] for c in level_cards], [1, 2, 3, 4, 5])
        self.assertEqual([c["goal"] for c in level_cards], [5, 10, 20, 50, 100])

    def test_counts_come_from_the_lifetime_ledger(self):
        self.game._conn.execute(
            """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier, mode)
               VALUES (1, ?, ?, 10, 10, 1.0, 'instant'),
                      (1, ?, ?, 10, 10, 1.0, 'instant'),
                      (1, ?, ?, 10, 10, 1.0, 'instant')""",
            (f"{date.today()}T09:00:00", date.today().isoformat(),
             f"{date.today()}T10:00:00", date.today().isoformat(),
             f"{date.today()}T11:00:00", date.today().isoformat()))
        self.game._conn.commit()

        metrics = self.game._metrics()
        self.assertEqual(metrics["completions_instant"], 3)
        self.assertEqual(metrics["best_day_completions"], 3)

    def test_only_the_highest_new_tier_of_a_stack_is_logged(self):
        self.game._conn.execute("UPDATE character SET xp = ?, coins = ? WHERE id = 1",
                                (E.cumulative_xp(20), 10_000))
        self.game._conn.commit()
        self.game._check_achievements()

        text = " ".join(row["text"] for row in self.game._query(
            "SELECT text FROM activity WHERE kind = 'achievement'"))
        self.assertIn("Mythic", text)          # level 20, the top new tier
        self.assertNotIn("Seasoned", text)     # level 5, buried under it
        self.assertIn("Dragon's Hoard", text)


if __name__ == "__main__":
    unittest.main()
