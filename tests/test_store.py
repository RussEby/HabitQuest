"""Behavioural tests for :class:`habitquest.store.Game`."""

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from habitquest import data as D
from habitquest import engine as E
from habitquest.store import Game, GameError


class GameTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-test-")
        self.game = Game(os.path.join(self.tmp, "save.db"))

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fresh_character(self, name="Tester", archetype="warrior", starter=True):
        state = self.game.create_character(name, archetype, starter_tasks=starter)
        return state


class TestCharacterCreation(GameTestBase):
    def test_a_new_save_has_no_character(self):
        state = self.game.state()
        self.assertFalse(state["has_character"])
        self.assertIn("archetypes", state["meta"])

    def test_creating_a_character_seeds_the_world(self):
        state = self.fresh_character()
        self.assertTrue(state["has_character"])
        char = state["character"]
        self.assertEqual(char["name"], "Tester")
        self.assertEqual(char["level"], 1)
        self.assertEqual(char["coins"], 100)
        self.assertEqual(len(state["tasks"]), 3)
        self.assertEqual(len(state["shop"]), len(D.ITEMS))
        self.assertEqual(char["stats"], D.ARCHETYPE_BY_ID["warrior"]["stats"])

    def test_blank_name_falls_back(self):
        state = self.game.create_character("   ", "mage")
        self.assertEqual(state["character"]["name"], "Adventurer")

    def test_unknown_archetype_falls_back_to_warrior(self):
        state = self.game.create_character("Odd", "necromancer")
        self.assertEqual(state["character"]["archetype"], "warrior")

    def test_a_second_character_is_rejected(self):
        self.fresh_character()
        with self.assertRaises(GameError):
            self.game.create_character("Impostor", "rogue")


class TestTasks(GameTestBase):
    def setUp(self):
        super().setUp()
        self.fresh_character()

    def test_create_read_update_delete(self):
        task = self.game.create_task({
            "name": "Floss", "stat": "vit", "xp": 4, "coins": 3,
            "icon": "🦷", "color": "#22d3ee", "difficulty": "tiny", "description": "Daily.",
        })
        self.assertEqual(task["name"], "Floss")
        self.assertEqual(task["stat_abbr"], "VIT")
        self.assertFalse(task["completed_today"])
        self.assertEqual(task["reward_xp"], 2)  # 4 base @ tiny (x0.5)

        updated = self.game.update_task(task["id"], {"name": "Floss daily", "xp": 6})
        self.assertEqual(updated["name"], "Floss daily")
        self.assertEqual(updated["xp"], 6)

        self.game.delete_task(task["id"])
        self.assertNotIn(task["id"], [t["id"] for t in self.game.list_tasks()])

    def test_a_task_needs_a_name(self):
        with self.assertRaises(GameError):
            self.game.create_task({"name": "   "})

    def test_invalid_stat_and_difficulty_are_normalised(self):
        task = self.game.create_task({"name": "Weird", "stat": "luck", "difficulty": "insane"})
        self.assertEqual(task["stat"], "str")
        self.assertEqual(task["difficulty"], "easy")
        self.assertIn(task["stat"], D.STAT_KEYS)

    def test_reward_values_are_clamped(self):
        task = self.game.create_task({"name": "Huge", "xp": 99999, "coins": -5})
        self.assertLessEqual(task["xp"], 500)
        self.assertGreaterEqual(task["coins"], 0)

    def test_editing_a_missing_task_raises(self):
        with self.assertRaises(GameError):
            self.game.update_task(999999, {"name": "ghost"})


class TestCompleting(GameTestBase):
    def setUp(self):
        super().setUp()
        self.fresh_character()
        self.task = self.game.create_task(
            {"name": "Push ups", "stat": "str", "xp": 20, "coins": 15, "difficulty": "easy"}
        )

    def test_completing_awards_xp_and_gold(self):
        before = self.game.state()["character"]
        result = self.game.complete_task(self.task["id"])
        after = result["state"]["character"]
        rewards = result["rewards"]
        # This is the first quest of the day, so the payout carries the +20% bonus.
        self.assertTrue(rewards["daily_bonus"])
        self.assertEqual(rewards["xp"], round(20 * 1.2))
        self.assertEqual(rewards["coins"], round(15 * 1.2))
        self.assertEqual(after["xp"], before["xp"] + rewards["xp"])
        self.assertEqual(after["coins"], before["coins"] + rewards["coins"])
        self.assertEqual(after["total_completions"], before["total_completions"] + 1)

    def test_first_completion_of_the_day_grants_a_bonus(self):
        # Consume the daily bonus with a different task first.
        self.game.complete_task(self.task["id"])
        second = self.game.create_task({"name": "Squats", "xp": 10, "coins": 10})
        result = self.game.complete_task(second["id"])
        self.assertFalse(result["rewards"]["daily_bonus"])
        self.assertEqual(result["rewards"]["multiplier"], 1.0)

    def test_the_same_task_cannot_be_completed_twice_in_a_day(self):
        self.game.complete_task(self.task["id"])
        with self.assertRaises(GameError):
            self.game.complete_task(self.task["id"])

    def test_completing_marks_the_task_for_today(self):
        self.game.complete_task(self.task["id"])
        task = self.game.state_for_task(self.task["id"])
        self.assertTrue(task["completed_today"])
        self.assertEqual(task["streak"], 1)
        self.assertEqual(task["completions"], 1)
        self.assertEqual(task["last_completed"], date.today().isoformat())

    def test_undo_rolls_back_the_rewards_and_the_task(self):
        before = self.game.state()["character"]
        self.game.complete_task(self.task["id"])
        state = self.game.undo_task(self.task["id"])["state"]
        after = state["character"]
        self.assertEqual(after["xp"], before["xp"])
        self.assertEqual(after["coins"], before["coins"])
        self.assertEqual(after["total_completions"], before["total_completions"])
        task = self.game.state_for_task(self.task["id"])
        self.assertFalse(task["completed_today"])
        self.assertEqual(task["completions"], 0)
        self.assertIsNone(task["last_completed"])

    def test_undo_without_a_completion_raises(self):
        with self.assertRaises(GameError):
            self.game.undo_task(self.task["id"])

    def test_level_up_reports_skill_points(self):
        big = self.game.create_task({"name": "Epic", "xp": 500, "coins": 10, "difficulty": "easy"})
        result = self.game.complete_task(big["id"])
        self.assertIsNotNone(result["level_up"])
        self.assertGreater(result["level_up"]["to_level"], 1)
        self.assertEqual(result["level_up"]["points"],
                         (result["level_up"]["to_level"] - result["level_up"]["from_level"])
                         * D.SKILL_POINTS_PER_LEVEL)
        self.assertEqual(result["state"]["character"]["level"], result["level_up"]["to_level"])

    def test_undo_lowers_the_level_again(self):
        big = self.game.create_task({"name": "Epic", "xp": 500, "coins": 10})
        self.game.complete_task(big["id"])
        self.assertGreater(self.game.state()["character"]["level"], 1)
        self.game.undo_task(big["id"])
        self.assertEqual(self.game.state()["character"]["level"], 1)


class TestShop(GameTestBase):
    def setUp(self):
        super().setUp()
        self.fresh_character()

    def give_gold(self, amount):
        self.game._conn.execute("UPDATE character SET coins = ? WHERE id = 1", (amount,))
        self.game._conn.commit()

    def grant_level(self, level):
        """Jump the hero to ``level`` so level-gated shop items become buyable."""
        self.game._conn.execute(
            "UPDATE character SET xp = ? WHERE id = 1", (E.cumulative_xp(level),))
        self.game._conn.commit()

    def test_buying_costs_gold_and_appears_in_the_inventory(self):
        self.give_gold(500)
        item = D.ITEM_BY_ID["wooden_sword"]
        result = self.game.buy_item("wooden_sword")
        self.assertEqual(result["state"]["character"]["coins"], 500 - item["price"])
        self.assertEqual(len(result["state"]["inventory"]), 1)
        self.assertTrue([i for i in result["state"]["inventory"] if i["id"] == "wooden_sword"])

    def test_you_cannot_buy_what_you_cannot_afford(self):
        self.give_gold(10)
        with self.assertRaises(GameError):
            self.game.buy_item("excalibur")

    def test_level_requirements_are_enforced(self):
        self.give_gold(99999)
        with self.assertRaises(GameError):
            self.game.buy_item("dragonfang")

    def test_buying_twice_is_rejected(self):
        self.give_gold(999)
        self.game.buy_item("wooden_sword")
        with self.assertRaises(GameError):
            self.game.buy_item("wooden_sword")

    def test_equipping_adds_its_stat_bonus_to_power(self):
        self.give_gold(999)
        before = self.game.state()["character"]["power"]
        self.game.buy_item("wooden_sword")
        state = self.game.equip_item("wooden_sword")["state"]
        self.assertEqual(state["equipped"]["weapon"]["id"], "wooden_sword")
        self.assertEqual(state["character"]["equip_bonus"]["str"], 1)
        self.assertEqual(state["character"]["total_stats"]["str"],
                         D.ARCHETYPE_BY_ID["warrior"]["stats"]["str"] + 1)
        self.assertGreater(state["character"]["power"], before)

    def test_you_cannot_equip_something_you_do_not_own(self):
        with self.assertRaises(GameError):
            self.game.equip_item("excalibur")

    def test_unequipping_clears_the_slot(self):
        self.give_gold(999)
        self.game.buy_item("wooden_sword")
        self.game.equip_item("wooden_sword")
        state = self.game.unequip_slot("weapon")["state"]
        self.assertIsNone(state["equipped"]["weapon"])
        self.assertEqual(state["character"]["equip_bonus"]["str"], 0)

    def test_only_one_item_per_slot(self):
        self.give_gold(9999)
        self.grant_level(3)
        self.game.buy_item("wooden_sword")
        self.game.buy_item("iron_sword")
        self.game.equip_item("wooden_sword")
        state = self.game.equip_item("iron_sword")["state"]
        self.assertEqual(state["equipped"]["weapon"]["id"], "iron_sword")
        self.assertEqual(state["character"]["equip_bonus"]["str"], 3)

    def test_unknown_item_is_rejected(self):
        with self.assertRaises(GameError):
            self.game.buy_item("moon_cheese")

    def test_every_item_is_reachable(self):
        for item in D.ITEMS:
            self.assertIn(item["slot"], D.SLOT_IDS, item["id"])
            self.assertIn(item["rarity"], D.RARITIES, item["id"])
            self.assertTrue(item["bonus"], item["id"])
            for stat in item["bonus"]:
                self.assertIn(stat, D.STAT_KEYS, item["id"])


class TestSkills(GameTestBase):
    def setUp(self):
        super().setUp()
        self.fresh_character()
        self.game.create_character  # no-op clarity

    def get_points(self):
        return self.game.state()["character"]["skill_points"]

    def test_no_points_at_level_one(self):
        self.assertEqual(self.get_points(), 0)
        with self.assertRaises(GameError):
            self.game.upgrade_stat("str")

    def test_level_up_grants_spendable_points(self):
        big = self.game.create_task({"name": "Epic", "xp": 500, "coins": 0})
        self.game.complete_task(big["id"])
        self.assertGreater(self.get_points(), 0)

    def test_spending_a_point_raises_the_stat(self):
        big = self.game.create_task({"name": "Epic", "xp": 500, "coins": 0})
        self.game.complete_task(big["id"])
        before = self.game.state()["character"]["stats"]["int"]
        points = self.get_points()
        result = self.game.upgrade_stat("int", 2)
        char = result["state"]["character"]
        self.assertEqual(char["stats"]["int"], before + 2)
        self.assertEqual(char["skill_points"], points - 2)
        self.assertEqual(char["skill_points_spent"], 2)
        self.assertGreater(char["power"], 0)

    def test_cannot_spend_more_points_than_you_have(self):
        big = self.game.create_task({"name": "Epic", "xp": 500, "coins": 0})
        self.game.complete_task(big["id"])
        available = self.get_points()
        self.game.upgrade_stat("str", available + 50)
        self.assertEqual(self.get_points(), 0)

    def test_unknown_stat_is_rejected(self):
        with self.assertRaises(GameError):
            self.game.upgrade_stat("luck")


class TestAchievementsAndHistory(GameTestBase):
    def setUp(self):
        super().setUp()
        self.fresh_character()
        self.task = self.game.create_task({"name": "Read", "xp": 10, "coins": 10})

    def test_first_completion_unlocks_the_first_achievement(self):
        result = self.game.complete_task(self.task["id"])
        unlocked = {a["id"] for a in result["unlocked"]}
        self.assertIn("first_step", unlocked)
        stored = {a["id"] for a in result["state"]["achievements"] if a["unlocked"]}
        self.assertIn("first_step", stored)

    def test_achievements_are_only_announced_once(self):
        second = self.game.create_task({"name": "Second", "xp": 5, "coins": 5})
        first_run = {a["id"] for a in self.game.complete_task(self.task["id"])["unlocked"]}
        second_run = {a["id"] for a in self.game.complete_task(second["id"])["unlocked"]}
        self.assertIn("first_step", first_run)
        self.assertNotIn("first_step", second_run)

    def test_progress_is_reported_for_every_achievement(self):
        for ach in self.game.state()["achievements"]:
            self.assertIn("percent", ach)
            self.assertGreaterEqual(ach["percent"], 0)
            self.assertLessEqual(ach["percent"], 100)

    def test_history_counts_today(self):
        self.game.complete_task(self.task["id"])
        history = self.game.history(30)
        self.assertEqual(history["total_completions"], 1)
        self.assertEqual(len(history["series"]), 30)
        self.assertEqual(history["series"][-1]["count"], 1)
        self.assertEqual(history["series"][-1]["day"], date.today().isoformat())
        self.assertEqual(history["top_tasks"][0]["name"], "Read")
        self.assertGreater(history["total_xp"], 0)

    def test_activity_feed_records_events_newest_first(self):
        self.game.complete_task(self.task["id"])
        feed = self.game.activity(10)
        self.assertTrue(feed)
        kinds = [entry["kind"] for entry in feed]
        self.assertIn("complete", kinds)
        # The completion happened before the achievement it unlocked, so the
        # feed must read newest first.
        self.assertEqual(feed[-1]["kind"], "create")
        self.assertTrue(all(len(entry["text"]) >= 5 for entry in feed))

    def test_day_streak_tracks_consecutive_active_days(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.game._conn.execute(
            "UPDATE character SET last_active_day = ?, day_streak = 6 WHERE id = 1", (yesterday,))
        self.game._conn.commit()
        state = self.game.complete_task(self.task["id"])["state"]
        self.assertEqual(state["character"]["day_streak"], 7)

    def test_a_gap_resets_the_day_streak(self):
        long_ago = (date.today() - timedelta(days=9)).isoformat()
        self.game._conn.execute(
            "UPDATE character SET last_active_day = ?, day_streak = 6 WHERE id = 1", (long_ago,))
        self.game._conn.commit()
        state = self.game.complete_task(self.task["id"])["state"]
        self.assertEqual(state["character"]["day_streak"], 1)


class TestPersistenceAndDemo(GameTestBase):
    def test_state_survives_reopening_the_file(self):
        self.fresh_character("Persist")
        path = self.game.path
        self.game.close()
        reopened = Game(path)
        try:
            state = reopened.state()
            self.assertTrue(state["has_character"])
            self.assertEqual(state["character"]["name"], "Persist")
            self.assertEqual(len(state["tasks"]), 3)
        finally:
            reopened.close()

    def test_demo_seed_creates_a_playable_save(self):
        state = self.game.seed_demo()
        char = state["character"]
        self.assertEqual(char["name"], "Rowan")
        self.assertGreater(char["level"], 1)
        self.assertGreater(char["total_completions"], 20)
        self.assertGreater(len(state["tasks"]), 3)
        self.assertEqual(len(state["history"]["series"]), 30)
        self.assertTrue([a for a in state["achievements"] if a["unlocked"]])

    def test_demo_is_idempotent(self):
        first = self.game.seed_demo()
        second = self.game.seed_demo()
        self.assertEqual(len(first["tasks"]), len(second["tasks"]))

    def test_reset_wipes_everything(self):
        self.game.seed_demo()
        state = self.game.reset() and self.game.state()
        self.assertFalse(state["has_character"])


class TestStateShape(GameTestBase):
    """The frontend is written against these exact keys."""

    def test_state_exposes_everything_the_ui_needs(self):
        state = self.fresh_character()
        for key in ("has_character", "character", "tasks", "equipped", "inventory",
                    "shop", "achievements", "activity", "history", "meta"):
            self.assertIn(key, state)
        for slot in D.SLOT_IDS:
            self.assertIn(slot, state["equipped"])
        for key in ("level", "level_progress", "level_xp", "level_xp_needed", "power",
                    "skill_points", "stats", "total_stats", "equip_bonus", "coins",
                    "day_streak", "total_completions", "archetype_name", "archetype_color"):
            self.assertIn(key, state["character"])
        for key in ("stats", "slots", "archetypes", "icons", "colors", "difficulties", "today"):
            self.assertIn(key, state["meta"])
        self.assertEqual(len(state["meta"]["stats"]), len(D.STAT_KEYS))
        self.assertEqual(len(state["meta"]["archetypes"]), len(D.ARCHETYPES))

    def test_state_is_json_serialisable(self):
        import json
        state = self.game.seed_demo()
        json.dumps(state)  # must not raise


if __name__ == "__main__":
    unittest.main()
