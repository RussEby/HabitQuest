"""Quests that only run on some weekdays.

A schedule is stored as ISO weekday numbers (Mon=1 .. Sun=7); every day is
stored as ''. The interesting part is streaks: a day the quest is not scheduled
for is a rest day, so it must neither break a quest's streak nor the hero's day
streak.
"""

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from habitquest import engine as E
from habitquest.store import Game, GameError


class ScheduleEngineTests(unittest.TestCase):
    def test_empty_storage_means_every_day(self):
        self.assertEqual(E.days_list(""), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(E.days_list(None), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(E.normalise_days([1, 2, 3, 4, 5, 6, 7]), "")

    def test_days_are_normalised_and_sorted(self):
        self.assertEqual(E.normalise_days([5, 1, 3]), "1,3,5")
        self.assertEqual(E.normalise_days("5,1,3"), "1,3,5")
        self.assertEqual(E.normalise_days([0, 8, "x"]), "")   # nothing valid -> daily

    def test_labels(self):
        self.assertEqual(E.days_label(""), "Every day")
        self.assertEqual(E.days_label("1,2,3,4,5"), "Weekdays")
        self.assertEqual(E.days_label("6,7"), "Weekends")
        self.assertEqual(E.days_label("1,2,3"), "Mon\u2013Wed")
        self.assertEqual(E.days_label("1,3,5"), "Mon, Wed, Fri")

    def test_weekday_streak_survives_the_weekend(self):
        # Friday 2026-05-01 -> Monday 2026-05-04 with Sat/Sun off.
        self.assertEqual(E.next_streak("2026-05-01", "2026-05-04", 3, "1,2,3,4,5"), 4)

    def test_a_daily_streak_still_breaks_on_a_missed_day(self):
        self.assertEqual(E.next_streak("2026-05-01", "2026-05-04", 3, ""), 1)

    def test_weekend_streak_survives_the_working_week(self):
        # Sunday 2026-05-03 -> Saturday 2026-05-09.
        self.assertEqual(E.next_streak("2026-05-03", "2026-05-09", 2, "6,7"), 3)

    def test_missing_a_scheduled_day_still_breaks_the_streak(self):
        # A Mon/Wed/Fri quest completed Friday, then next Wednesday: Monday was due.
        self.assertEqual(E.next_streak("2026-05-01", "2026-05-06", 5, "1,3,5"), 1)

    def test_longest_run_counts_rest_days_as_no_gap(self):
        days = ["2026-05-01", "2026-05-04", "2026-05-05"]
        self.assertEqual(E.longest_day_run(days, "1,2,3,4,5"), 3)
        self.assertEqual(E.longest_day_run(days, ""), 2)

    def test_current_streak_is_still_alive_on_a_rest_day(self):
        # Weekly quest: last completion was a week ago, today is the next due day.
        self.assertEqual(E.current_streak(["2026-05-01"], "5", "2026-05-08"), 1)

    def test_current_streak_ends_after_a_missed_due_day(self):
        self.assertEqual(E.current_streak(["2026-05-01"], "", "2026-05-04"), 0)


class ScheduleStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-schedule-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)
        self.today = date.today().isoweekday()

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_quest_without_a_schedule_runs_every_day(self):
        task = self.game.create_task({"name": "Daily"})
        self.assertEqual(task["days"], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(task["days_label"], "Every day")
        self.assertTrue(task["is_daily"])
        self.assertTrue(task["due_today"])

    def test_a_schedule_round_trips(self):
        task = self.game.create_task({"name": "Weekday", "days": [1, 2, 3, 4, 5]})
        self.assertEqual(task["days"], [1, 2, 3, 4, 5])
        self.assertEqual(task["days_label"], "Weekdays")
        self.assertFalse(task["is_daily"])
        self.assertEqual(task["due_today"], self.today in [1, 2, 3, 4, 5])

        updated = self.game.update_task(task["id"], {"days": "6,7"})
        self.assertEqual(updated["days"], [6, 7])
        self.assertEqual(updated["days_label"], "Weekends")

        back = self.game.update_task(task["id"], {"days": []})
        self.assertEqual(back["days_label"], "Every day")

    def test_an_off_day_quest_cannot_be_completed(self):
        off = next(d for d in range(1, 8) if d != self.today)
        task = self.game.create_task({"name": "Elsewhere", "days": [off]})
        self.assertFalse(task["due_today"])
        with self.assertRaises(GameError) as caught:
            self.game.complete_task(task["id"])
        self.assertIn("isn't scheduled today", str(caught.exception))

    def test_an_off_day_quest_cannot_be_started(self):
        off = next(d for d in range(1, 8) if d != self.today)
        task = self.game.create_task({
            "name": "Elsewhere", "days": [off],
            "mode": "beat_clock", "duration_minutes": 20,
        })
        with self.assertRaises(GameError):
            self.game.start_session(task["id"])

    def test_a_quest_due_today_still_completes(self):
        task = self.game.create_task({"name": "Today", "days": [self.today]})
        self.assertTrue(task["due_today"])
        result = self.game.complete_task(task["id"])
        self.assertEqual(result["outcome"], "completed")

    def test_completing_a_weekly_quest_continues_the_hero_streak(self):
        task = self.game.create_task({"name": "Weekly", "days": [self.today]})
        last = (date.today() - timedelta(days=7)).isoformat()
        self.game._conn.execute(
            "UPDATE character SET last_active_day = ?, day_streak = 4 WHERE id = 1",
            (last,),
        )
        self.game._conn.commit()

        result = self.game.complete_task(task["id"])
        # Nothing was due on the six days in between, so the run continues.
        self.assertEqual(result["state"]["character"]["day_streak"], 5)

    def test_day_streak_ignores_days_with_nothing_scheduled(self):
        self.game.create_task({"name": "Weekday", "days": [1, 2, 3, 4, 5]})
        # Friday 2026-05-01 -> Monday 2026-05-04: the weekend does not count.
        self.assertEqual(self.game._day_streak("2026-05-01", 4, "2026-05-04"), 5)

    def test_day_streak_still_breaks_when_a_scheduled_day_was_missed(self):
        self.game.create_task({"name": "Weekday", "days": [1, 2, 3, 4, 5]})
        # Today is Tuesday; Monday had a quest due and was missed.
        self.assertEqual(self.game._day_streak("2026-05-01", 4, "2026-05-05"), 1)

    def test_a_daily_quest_keeps_the_strict_calendar_streak(self):
        self.game.create_task({"name": "Daily"})
        self.assertEqual(self.game._day_streak("2026-05-01", 4, "2026-05-04"), 1)

    def test_undo_recomputes_a_weekly_streak_without_breaking_it(self):
        # A weekly quest completed today, a week ago and two weeks ago. Undoing
        # today leaves the two older completions as a live run of 2.
        task = self.game.create_task({"name": "Weekly", "days": [self.today]})
        today = date.today()
        for weeks in (2, 1, 0):
            day = (today - timedelta(days=weeks * 7)).isoformat()
            self.game._conn.execute(
                """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier)
                   VALUES (?, ?, ?, 0, 0, 1.0)""",
                (task["id"], day + "T10:00:00", day),
            )
        self.game._conn.commit()

        self.game.undo_task(task["id"])
        updated = self.game.state()["tasks"][0]
        self.assertEqual(updated["streak"], 2)
        self.assertEqual(updated["best_streak"], 2)

    def test_archived_quests_do_not_keep_dead_days_alive(self):
        task = self.game.create_task({"name": "Old", "days": [self.today]})
        self.game._conn.execute("UPDATE tasks SET archived = 1 WHERE id = ?", (task["id"],))
        self.game._conn.commit()
        # With nothing live scheduled on the weekend, Friday -> Monday is fine.
        self.assertEqual(self.game._day_streak("2026-05-01", 1, "2026-05-04"), 2)


if __name__ == "__main__":
    unittest.main()
