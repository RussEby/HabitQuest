"""A quest can stay open for several days instead of expiring the day it starts.

The finish window is the grace period after an occurrence opens: pick Monday with
a five-day window and Monday's occurrence can be finished any day from Monday to
Friday. Windows may never overlap, so the window is capped by the shortest gap
between scheduled starts. Streaks, skips and the nightly reckoning count
occurrences rather than calendar days.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

from habitquest import engine as E
from habitquest.server import build_server
from habitquest.store import Game, GameError

TODAY = date.today()
# Fixed dates for calendar arithmetic that must not depend on when this runs.
MONDAY = date(2026, 10, 26)


class WindowEngineTests(unittest.TestCase):
    def test_an_every_day_quest_has_no_window(self):
        self.assertEqual(E.max_window(""), 1)
        self.assertEqual(E.max_window([1, 2, 3, 4, 5, 6, 7]), 1)

    def test_a_single_weekday_can_stay_open_all_week(self):
        self.assertEqual(E.max_window([3]), 7)
        self.assertEqual(E.max_window([7]), 7)

    def test_the_window_is_the_shortest_gap_between_starts(self):
        self.assertEqual(E.max_window([1, 3, 5]), 2)      # Mon / Wed / Fri
        self.assertEqual(E.max_window([1, 2, 3, 4, 5]), 1)
        self.assertEqual(E.max_window([6, 7]), 1)         # the weekend
        self.assertEqual(E.max_window([1, 6]), 2)         # Mon, then Sat
        # The gap wraps around the week: Fri -> Mon is three days.
        self.assertEqual(E.max_window([1, 5]), 3)

    def test_a_window_covers_its_start_day_and_the_days_after(self):
        self.assertEqual(E.window_span(MONDAY, [1], 5), (MONDAY, date(2026, 10, 30)))
        self.assertEqual(E.window_span(MONDAY + timedelta(days=4), [1], 5)[0], MONDAY)
        self.assertIsNone(E.window_span(MONDAY + timedelta(days=5), [1], 5))

    def test_windows_never_overlap(self):
        # Mon/Wed/Fri with a two-day window: Mon-Tue, Wed-Thu, Fri-Sat.
        expected = {0: MONDAY, 1: MONDAY, 2: MONDAY + timedelta(days=2),
                    4: MONDAY + timedelta(days=4)}
        for offset, start in expected.items():
            self.assertEqual(
                E.window_span(MONDAY + timedelta(days=offset), [1, 3, 5], 2)[0], start)
        self.assertIsNone(E.window_span(MONDAY + timedelta(days=6), [1, 3, 5], 2))

    def test_a_single_day_window_is_the_old_same_day_behaviour(self):
        self.assertEqual(E.window_span(MONDAY, [1], 1), (MONDAY, MONDAY))
        self.assertIsNone(E.window_span(MONDAY + timedelta(days=1), [1], 1))


class WindowStreakTests(unittest.TestCase):
    def test_finishing_inside_the_window_keeps_the_run(self):
        # Monday's occurrence finished on Tuesday; next one is Wednesday.
        self.assertEqual(
            E.next_streak("2026-10-27", "2026-10-28", 4, [1, 3], window=2), 5)

    def test_a_missed_occurrence_breaks_the_run_even_with_a_window(self):
        # Monday was done; Wednesday's occurrence expired untouched, so the next
        # completion (the following Monday) starts a new run.
        self.assertEqual(
            E.next_streak("2026-10-26", "2026-11-02", 3, [1, 3], window=2), 1)

    def test_a_skipped_occurrence_does_not_break_the_run(self):
        self.assertEqual(
            E.next_streak("2026-10-26", "2026-11-02", 3, [1, 3],
                          {"2026-10-28"}, 2), 4)

    def test_the_board_streak_survives_an_open_window(self):
        # A single Monday with a five-day window: the run is alive all week...
        self.assertEqual(E.current_streak(["2026-10-26"], [1], today="2026-10-30",
                                         window=5), 1)
        # ...still alive the next Monday, whose window has just opened...
        self.assertEqual(E.current_streak(["2026-10-26"], [1], today="2026-11-02",
                                         window=5), 1)
        # ...and gone once that whole window passed without a completion.
        self.assertEqual(E.current_streak(["2026-10-26"], [1], today="2026-11-09",
                                         window=5), 0)

    def test_the_longest_run_counts_occurrences_not_days(self):
        dates = ["2026-10-26", "2026-10-27"]       # one occurrence, done late
        self.assertEqual(E.longest_day_run(dates, [1], window=5), 1)


class WindowStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-window-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, **payload):
        payload.setdefault("name", "Quest")
        payload.setdefault("xp", 10)
        payload.setdefault("coins", 5)
        return self.game.create_task(payload)

    def stored(self, task_id):
        return self.game._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))

    def yesterday_weekday(self):
        return (TODAY - timedelta(days=1)).isoweekday()

    # -- creation and validation ------------------------------------------
    def test_a_new_quest_has_a_one_day_window(self):
        task = self.add()
        self.assertEqual(task["window_days"], 1)
        self.assertEqual(task["window_label"], "Same day")
        self.assertTrue(task["due_today"])

    def test_the_window_is_stored_and_reported(self):
        task = self.add(days=[self.yesterday_weekday()], window_days=2)
        self.assertEqual(task["window_days"], 2)
        self.assertEqual(task["window_label"], "2 days")
        self.assertTrue(task["window_day"] in (1, 2))
        self.assertTrue(task["window_end_label"])

    def test_an_overlapping_window_is_refused(self):
        with self.assertRaises(GameError) as caught:
            self.add(days=[], window_days=2)
        self.assertIn("no room for a finish window", str(caught.exception))

        with self.assertRaises(GameError) as caught:
            self.add(days=[1, 3, 5], window_days=3)
        self.assertIn("at most 2", str(caught.exception))

    def test_a_window_that_fits_is_accepted(self):
        task = self.add(days=[1, 3, 5], window_days=2)
        self.assertEqual(task["window_days"], 2)

    def test_a_single_weekday_takes_the_longest_window(self):
        self.assertEqual(self.add(days=[3], window_days=7)["window_days"], 7)
        self.assertEqual(self.add(name="Wide", days=[3], window_days=40)["window_days"], 7)

    def test_editing_days_cannot_create_an_overlap(self):
        task = self.add(days=[1], window_days=5)
        with self.assertRaises(GameError):
            self.game.update_task(task["id"], {"days": [1, 2]})
        self.assertEqual(self.stored(task["id"])["days"], "1")
        self.assertEqual(self.stored(task["id"])["window_days"], 5)

    def test_editing_the_window_past_the_schedule_is_refused(self):
        task = self.add(days=[1, 2])
        with self.assertRaises(GameError):
            self.game.update_task(task["id"], {"window_days": 2})
        self.assertEqual(self.stored(task["id"])["window_days"], 1)

    def test_a_shorter_window_survives_an_edit(self):
        task = self.add(days=[1, 3, 5], window_days=2)
        changed = self.game.update_task(task["id"], {"window_days": 1})
        self.assertEqual(changed["window_days"], 1)

    # -- the occurrence itself --------------------------------------------
    def test_the_occurrence_stays_open_after_its_start_day(self):
        task = self.add(days=[self.yesterday_weekday()], window_days=2)
        self.assertTrue(task["due_today"])
        self.assertEqual(task["window_day"], 2)
        self.assertEqual(task["window_start"],
                         (TODAY - timedelta(days=1)).isoformat())

    def test_a_same_day_quest_is_not_open_on_its_second_day(self):
        task = self.add(days=[self.yesterday_weekday()])
        self.assertFalse(task["due_today"])
        with self.assertRaises(GameError) as caught:
            self.game.complete_task(task["id"])
        self.assertIn("isn't scheduled today", str(caught.exception))

    def test_the_occurrence_can_be_finished_inside_its_window(self):
        task = self.add(days=[self.yesterday_weekday()], window_days=2)
        result = self.game.complete_task(task["id"])
        self.assertEqual(result["outcome"], "completed")
        self.assertGreater(result["rewards"]["xp"], 0)

        closed = self.game.state_for_task(task["id"])
        self.assertFalse(closed["window_open"])
        # It stays on today's board so it can sit in the Finished section.
        self.assertTrue(closed["due_today"])
        self.assertTrue(closed["completed_today"])
        self.assertEqual(closed["window_closed_on"], TODAY.isoformat())

    def test_a_window_quest_can_start_its_timer_late(self):
        task = self.add(days=[self.yesterday_weekday()], window_days=2,
                        mode="beat_clock", duration_minutes=10)
        started = self.game.start_session(task["id"])
        self.assertEqual(started["outcome"], "started")
        self.game.abandon_session(task["id"])

    def test_skipping_closes_the_whole_occurrence(self):
        task = self.add(days=[self.yesterday_weekday()], window_days=2,
                        recurrences=3)
        result = self.game.skip_task(task["id"])
        self.assertEqual(result["recurrences"], 4)      # a skip extends the run
        skipped = self.game.state_for_task(task["id"])
        self.assertFalse(skipped["window_open"])
        self.assertTrue(skipped["skipped_today"])

        with self.assertRaises(GameError):
            self.game.complete_task(task["id"])

    def test_a_window_closed_on_an_earlier_day_leaves_the_board(self):
        start = TODAY - timedelta(days=1)
        task = self.add(days=[start.isoweekday()], window_days=2)
        self.game._conn.execute(
            "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
            (task["id"], start.isoformat() + "T09:00:00", start.isoformat()))
        self.game._conn.commit()

        card = self.game.state_for_task(task["id"])
        self.assertFalse(card["window_open"])
        self.assertFalse(card["due_today"])
        self.assertEqual(card["window_closed_on"], start.isoformat())
        self.assertFalse(card["window_skipped"])

    def test_a_skipped_window_is_reported_as_skipped(self):
        start = TODAY - timedelta(days=1)
        task = self.add(days=[start.isoweekday()], window_days=2)
        self.game._conn.execute(
            "INSERT INTO skips (task_id, day, ts, reason) VALUES (?, ?, ?, '')",
            (task["id"], start.isoformat(), start.isoformat() + "T09:00:00"))
        self.game._conn.commit()

        card = self.game.state_for_task(task["id"])
        self.assertFalse(card["window_open"])
        self.assertFalse(card["due_today"])
        self.assertTrue(card["window_skipped"])

    def test_undoing_a_skip_reopens_the_window(self):
        task = self.add(days=[self.yesterday_weekday()], window_days=2,
                        recurrences=3)
        self.game.skip_task(task["id"])
        self.game.unskip_task(task["id"])
        reopened = self.game.state_for_task(task["id"])
        self.assertTrue(reopened["window_open"])
        self.assertEqual(reopened["recurrences"], 3)


class WindowReckoningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-window-reckon-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def task_starting(self, days_ago, window):
        start = TODAY - timedelta(days=days_ago)
        task = self.game.create_task({
            "name": "Late quest", "days": [start.isoweekday()],
            "window_days": window, "xp": 5, "coins": 5})
        self.game._conn.execute(
            "UPDATE tasks SET created_at = ? WHERE id = ?",
            (start.isoformat() + "T08:00:00", task["id"]))
        self.game._conn.commit()
        return start, self.game._one("SELECT * FROM tasks WHERE id = ?", (task["id"],))

    def seed_ledger(self, day):
        self.game._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reckoned_day', ?)",
            (day.isoformat(),))
        self.game._conn.commit()

    def hp(self):
        return self.game.state()["character"]["hp"]

    def test_an_open_window_is_not_a_miss(self):
        start, _ = self.task_starting(days_ago=4, window=3)
        before = self.hp()
        self.seed_ledger(start)                 # scored on the day it opened
        self.game._apply_day_reckoning()
        self.assertEqual(self.hp(), before)
        self.assertIsNone(self.game.state()["day_reckoning"])

    def test_the_miss_lands_when_the_window_closes(self):
        start, row = self.task_starting(days_ago=4, window=3)
        self.seed_ledger(start + timedelta(days=2))
        self.game._apply_day_reckoning()
        state = self.game.state()
        self.assertLess(state["character"]["hp"], state["character"]["max_hp"])
        self.assertEqual(state["day_reckoning"]["missed"][0]["task_id"], row["id"])

    def test_a_completion_anywhere_in_the_window_forgives_it(self):
        start, row = self.task_starting(days_ago=4, window=3)
        self.game._conn.execute(
            "INSERT INTO completions (task_id, ts, day, xp, coins) VALUES (?, ?, ?, 5, 5)",
            (row["id"], (start + timedelta(days=1)).isoformat() + "T09:00:00",
             (start + timedelta(days=1)).isoformat()))
        self.game._conn.commit()
        before = self.hp()
        self.seed_ledger(start + timedelta(days=2))
        self.game._apply_day_reckoning()
        self.assertEqual(self.hp(), before)

    def test_a_window_quest_is_still_due_today(self):
        start, _ = self.task_starting(days_ago=1, window=2)
        state = self.game.state()
        self.assertEqual(len(state["tasks"]), 1)
        self.assertTrue(state["tasks"][0]["due_today"])


class WindowApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-window-api-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)
        self.httpd = build_server(self.game, host="127.0.0.1", port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_the_window_survives_the_round_trip(self):
        status, payload = self.request("POST", "/api/tasks", {
            "name": "Piano", "days": [1, 3, 5], "window_days": 2})
        self.assertEqual(status, 201)
        self.assertEqual(payload["task"]["window_days"], 2)
        self.assertEqual(payload["task"]["window_label"], "2 days")

        task_id = payload["task"]["id"]
        status, edited = self.request("PUT", f"/api/tasks/{task_id}",
                                      {"window_days": 1})
        self.assertEqual(status, 200)
        self.assertEqual(edited["task"]["window_days"], 1)

    def test_an_overlapping_window_is_a_client_error(self):
        status, payload = self.request("POST", "/api/tasks", {
            "name": "Impossible", "days": [1, 2, 3, 4, 5, 6, 7], "window_days": 2})
        self.assertEqual(status, 400)
        self.assertIn("finish window", payload["error"])


if __name__ == "__main__":
    unittest.main()
