"""Unit tests for the pure rules in :mod:`habitquest.engine`."""

import unittest

from habitquest import data as D
from habitquest import engine as E


class TestXpCurve(unittest.TestCase):
    def test_xp_to_next_grows_with_level(self):
        values = [E.xp_to_next(l) for l in range(1, 12)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(v > 0 for v in values))

    def test_level_one_needs_no_xp(self):
        self.assertEqual(E.cumulative_xp(1), 0)
        self.assertEqual(E.level_from_xp(0)["level"], 1)

    def test_level_boundaries_are_exact(self):
        need = E.xp_to_next(1)
        self.assertEqual(E.level_from_xp(need - 1)["level"], 1)
        self.assertEqual(E.level_from_xp(need)["level"], 2)
        self.assertEqual(E.level_from_xp(need)["level_xp"], 0)

    def test_cumulative_equals_sum_of_steps(self):
        total = sum(E.xp_to_next(l) for l in range(1, 5))
        self.assertEqual(E.cumulative_xp(5), total)
        self.assertEqual(E.level_from_xp(total)["level"], 5)
        self.assertEqual(E.level_from_xp(total - 1)["level"], 4)

    def test_progress_is_a_fraction_between_zero_and_one(self):
        for xp in (0, 1, 57, 99, 100, 245, 1000, 12345):
            info = E.level_from_xp(xp)
            self.assertGreaterEqual(info["level_progress"], 0.0)
            self.assertLessEqual(info["level_progress"], 1.0)
            self.assertLessEqual(info["level_xp"], info["level_xp_needed"])
            self.assertEqual(info["next_level_xp"], info["level_floor_xp"] + info["level_xp_needed"])

    def test_level_is_capped(self):
        huge = E.cumulative_xp(D.MAX_LEVEL) * 10
        self.assertEqual(E.level_from_xp(huge)["level"], D.MAX_LEVEL)
        self.assertTrue(E.level_from_xp(huge)["max_level"])


class TestRewards(unittest.TestCase):
    def task(self, xp=10, coins=10, difficulty="easy"):
        return {"xp": xp, "coins": coins, "difficulty": difficulty}

    def test_easy_difficulty_with_no_bonuses_is_one_to_one(self):
        r = E.compute_rewards(self.task(), streak=1, is_first_today=False)
        self.assertEqual(r["xp"], 10)
        self.assertEqual(r["coins"], 10)
        self.assertEqual(r["multiplier"], 1.0)

    def test_difficulty_scales_rewards(self):
        for difficulty, mult in ((d["id"], d["multiplier"]) for d in D.DIFFICULTIES):
            r = E.compute_rewards(self.task(difficulty=difficulty), 1, False)
            self.assertEqual(r["xp"], round(10 * mult))
            self.assertEqual(r["difficulty_multiplier"], mult)

    def test_first_quest_of_the_day_adds_a_bonus(self):
        plain = E.compute_rewards(self.task(), 1, False)
        first = E.compute_rewards(self.task(), 1, True)
        self.assertTrue(first["daily_bonus"])
        self.assertGreater(first["xp"], plain["xp"])
        self.assertGreater(first["coins"], plain["coins"])

    def test_streak_multiplier_is_capped(self):
        self.assertEqual(E.streak_multiplier(1), 1.0)
        self.assertAlmostEqual(E.streak_multiplier(2), 1.05, places=3)
        capped = E.streak_multiplier(500)
        self.assertAlmostEqual(capped, 1.0 + D.STREAK_BONUS_CAP, places=3)

    def test_long_streak_beats_short_streak(self):
        short = E.compute_rewards(self.task(), 1, False)
        long = E.compute_rewards(self.task(), 30, False)
        self.assertGreater(long["xp"], short["xp"])

    def test_unknown_difficulty_falls_back_to_easy(self):
        r = E.compute_rewards(self.task(difficulty="banana"), 1, False)
        self.assertEqual(r["difficulty_multiplier"], 1.0)

    def test_zero_value_task_stays_zero(self):
        r = E.compute_rewards(self.task(xp=0, coins=0), 9, True)
        self.assertEqual(r["xp"], 0)
        self.assertEqual(r["coins"], 0)


class TestStreaks(unittest.TestCase):
    def test_first_ever_completion_starts_a_streak(self):
        self.assertEqual(E.next_streak(None, "2026-05-01", 0), 1)

    def test_consecutive_day_extends_the_streak(self):
        self.assertEqual(E.next_streak("2026-05-01", "2026-05-02", 4), 5)

    def test_a_missed_day_resets_the_streak(self):
        self.assertEqual(E.next_streak("2026-05-01", "2026-05-03", 9), 1)

    def test_same_day_repeat_does_not_inflate_the_streak(self):
        self.assertEqual(E.next_streak("2026-05-05", "2026-05-05", 3), 3)

    def test_bad_dates_are_survivable(self):
        self.assertEqual(E.next_streak("nonsense", "2026-05-05", 3), 1)


class TestCalendarHelpers(unittest.TestCase):
    def test_longest_day_run_counts_consecutive_days(self):
        self.assertEqual(E.longest_day_run([]), 0)
        self.assertEqual(E.longest_day_run(["2026-01-01"]), 1)
        self.assertEqual(
            E.longest_day_run(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-09"]), 3)

    def test_longest_day_run_ignores_duplicates(self):
        self.assertEqual(E.longest_day_run(["2026-01-01", "2026-01-01", "2026-01-02"]), 2)

    def test_date_range_is_inclusive_and_ordered(self):
        days = E.date_range(5, end="2026-03-10")
        self.assertEqual(len(days), 5)
        self.assertEqual(days[0], "2026-03-06")
        self.assertEqual(days[-1], "2026-03-10")
        self.assertEqual(days, sorted(days))

    def test_heat_level_bands(self):
        self.assertEqual([E.heat_level(n) for n in (0, 1, 2, 5, 9)], [0, 1, 2, 3, 4])


class TestPowerAndSkills(unittest.TestCase):
    def test_power_rewards_stats_gear_and_level(self):
        stats = {"str": 5, "int": 5, "vit": 5, "agi": 5, "cha": 5}
        bare = E.power_score(stats, {}, 1)
        geared = E.power_score(stats, {"str": 4}, 1)
        levelled = E.power_score(stats, {}, 5)
        self.assertGreater(geared, bare)
        self.assertGreater(levelled, bare)
        # Gear counts twice on purpose: it raises the stat it boosts (x3) and is
        # separately weighted as gear (x5), so a point of gear gear is worth 8.
        self.assertEqual(geared - bare, 4 * 3 + 4 * 5)
        self.assertEqual(levelled - bare, 4 * 10)

    def test_total_stats_merges_equipment_bonuses(self):
        merged = E.total_stats({"str": 3, "int": 1}, {"str": 2, "cha": 4})
        self.assertEqual(merged, {"str": 5, "int": 1, "vit": 0, "agi": 0, "cha": 4})

    def test_aggregate_bonuses_reads_json_strings(self):
        total = E.aggregate_bonuses([{"bonus": '{"str": 2}'}, {"bonus": {"str": 1, "int": 3}}])
        self.assertEqual(total["str"], 3)
        self.assertEqual(total["int"], 3)

    def test_skill_points_award_then_spend(self):
        base = dict(D.ARCHETYPE_BY_ID["warrior"]["stats"])
        self.assertEqual(E.available_skill_points(1, base, base), 0)
        self.assertEqual(E.available_skill_points(3, base, base), 2 * D.SKILL_POINTS_PER_LEVEL)
        spent = dict(base, str=base["str"] + 2)
        self.assertEqual(E.available_skill_points(3, spent, base),
                         2 * D.SKILL_POINTS_PER_LEVEL - 2)


class TestAchievements(unittest.TestCase):
    def test_every_achievement_has_a_unique_id_and_a_track(self):
        ids = [a["id"] for a in D.ACHIEVEMENTS]
        self.assertEqual(len(ids), len(set(ids)))
        for ach in D.ACHIEVEMENTS:
            self.assertGreater(int(ach["goal"]), 0)

    def test_progress_unlocks_at_the_goal(self):
        evaluated = E.evaluate_achievements({"total_completions": 10})
        self.assertTrue(evaluated["warming_up"]["unlocked"])
        self.assertFalse(evaluated["centurion"]["unlocked"])
        self.assertEqual(evaluated["centurion"]["percent"], 10)

    def test_percent_is_clamped(self):
        evaluated = E.evaluate_achievements({"level": 999})
        self.assertEqual(evaluated["level_5"]["percent"], 100)

    def test_missing_metrics_are_treated_as_zero(self):
        evaluated = E.evaluate_achievements({})
        self.assertFalse(any(v["unlocked"] for v in evaluated.values()))


if __name__ == "__main__":
    unittest.main()
