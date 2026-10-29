"""Skipping a quest that could not happen for reasons out of the hero's control.

A skip pays nothing and records no completion, but the day must behave exactly
like a day the quest was never scheduled for: the streak picks up where it left
off on the next due day, the hero's day streak is not punished, and nothing is
scored against the hero in the nightly reckoning.
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


def days_ago(count: int) -> str:
    return (TODAY - timedelta(days=count)).isoformat()


class SkipEngineTests(unittest.TestCase):
    """The streak rules, without a database in the way."""

    def test_a_skipped_wednesday_continues_tuesdays_streak(self):
        # 5-day run through Tuesday, skipped Wednesday, back on Thursday.
        self.assertEqual(E.next_streak("2026-05-05", "2026-05-07", 5, "", {"2026-05-06"}), 6)

    def test_without_the_skip_the_same_gap_breaks_the_streak(self):
        self.assertEqual(E.next_streak("2026-05-05", "2026-05-07", 5, "", set()), 1)

    def test_a_later_missed_day_still_breaks_the_streak(self):
        # Wednesday was skipped but Thursday was simply missed: the run ends.
        self.assertEqual(E.next_streak("2026-05-05", "2026-05-08", 5, "", {"2026-05-06"}), 1)

    def test_a_skip_on_a_scheduled_day_joins_the_rest_days(self):
        # Mon/Wed/Fri quest: Wednesday was skipped, Thursday is a rest day, and
        # Friday is due again - so the run carries on.
        self.assertEqual(E.next_streak("2026-05-04", "2026-05-08", 3, "1,3,5",
                                       {"2026-05-06"}), 4)

    def test_the_live_run_survives_the_skipped_day(self):
        self.assertEqual(
            E.current_streak(["2026-05-04", "2026-05-05"], "", "2026-05-07",
                             skipped={"2026-05-06"}),
            2,
        )

    def test_the_longest_run_counts_a_skip_as_no_gap(self):
        self.assertEqual(
            E.longest_day_run(["2026-05-05", "2026-05-07"], "", {"2026-05-06"}), 2)


class SkipStoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-skip-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_task(self, **overrides):
        payload = {"name": "Daily habit", "xp": 10, "coins": 10}
        payload.update(overrides)
        return self.game.create_task(payload)

    def task_row(self, task_id):
        return self.game._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))

    def seed_run(self, task_id, length=5):
        """A run of ``length`` completions ending two days ago, then yesterday."""
        days = [days_ago(length + 1 - i) for i in range(length)]
        for day in days:
            self.game._conn.execute(
                """INSERT INTO completions (task_id, ts, day, xp, coins, multiplier)
                   VALUES (?, ?, ?, 0, 0, 1.0)""",
                (task_id, day + "T10:00:00", day),
            )
        self.game._conn.execute(
            """UPDATE tasks SET streak = ?, best_streak = MAX(best_streak, ?),
               completions = ?, last_completed = ? WHERE id = ?""",
            (length, length, length, days[-1], task_id),
        )
        self.game._conn.commit()
        return days

    def add_skip(self, task_id, day, reason=""):
        self.game._conn.execute(
            "INSERT INTO skips (task_id, day, ts, reason) VALUES (?, ?, ?, ?)",
            (task_id, day, day + "T12:00:00", reason),
        )
        self.game._conn.commit()

    def card(self, state, task_id):
        return [t for t in state["tasks"] if t["id"] == task_id][0]


class SkipStoreTests(SkipStoreBase):
    def test_skipping_pays_nothing_and_makes_no_completion(self):
        task = self.make_task()
        before = self.game.state()["character"]

        result = self.game.skip_task(task["id"], "travelling")

        self.assertEqual(result["outcome"], "skipped")
        char = result["state"]["character"]
        self.assertEqual(char["xp"], before["xp"])
        self.assertEqual(char["coins"], before["coins"])
        self.assertEqual(char["total_completions"], before["total_completions"])
        self.assertIsNone(self.game._one(
            "SELECT id FROM completions WHERE task_id = ?", (task["id"],)))
        card = self.card(result["state"], task["id"])
        self.assertTrue(card["skipped_today"])
        self.assertFalse(card["completed_today"])
        self.assertEqual(card["skip_reason"], "travelling")

    def test_the_skip_is_logged_without_claiming_the_quest_was_done(self):
        task = self.make_task()
        self.game.skip_task(task["id"])
        kinds = [a["kind"] for a in self.game.activity(10)]
        self.assertIn("skip", kinds)
        text = [a["text"] for a in self.game.activity(10) if a["kind"] == "skip"][0]
        self.assertIn("skipped", text.lower())
        self.assertIn("no reward", text.lower())

    def test_a_skip_holds_the_streak_over_the_gap(self):
        task = self.make_task()
        self.seed_run(task["id"], 5)          # five days, ending two days ago
        self.add_skip(task["id"], days_ago(1))

        result = self.game.complete_task(task["id"])

        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["rewards"]["streak"], 6)
        self.assertEqual(self.card(result["state"], task["id"])["streak"], 6)

    def test_without_the_skip_the_same_gap_resets_the_streak(self):
        task = self.make_task()
        self.seed_run(task["id"], 5)
        # Nothing on the skipped day this time.
        result = self.game.complete_task(task["id"])
        self.assertEqual(result["rewards"]["streak"], 1)

    def test_a_completed_quest_cannot_be_skipped(self):
        task = self.make_task()
        self.game.complete_task(task["id"])
        with self.assertRaises(GameError) as caught:
            self.game.skip_task(task["id"])
        self.assertIn("already done today", str(caught.exception))

    def test_skipping_twice_is_refused(self):
        task = self.make_task()
        self.game.skip_task(task["id"])
        with self.assertRaises(GameError) as caught:
            self.game.skip_task(task["id"])
        self.assertIn("already skipped", str(caught.exception))

    def test_a_skipped_quest_cannot_be_completed_today(self):
        task = self.make_task()
        self.game.skip_task(task["id"])
        with self.assertRaises(GameError) as caught:
            self.game.complete_task(task["id"])
        self.assertIn("skipped", str(caught.exception).lower())

    def test_a_skipped_quest_cannot_start_a_session_today(self):
        task = self.make_task(mode="beat_clock", duration_minutes=20)
        self.game.skip_task(task["id"])
        with self.assertRaises(GameError) as caught:
            self.game.start_session(task["id"])
        self.assertIn("skipped", str(caught.exception).lower())

    def test_a_running_session_cannot_be_skipped(self):
        task = self.make_task(mode="beat_clock", duration_minutes=20)
        self.game.start_session(task["id"])
        with self.assertRaises(GameError) as caught:
            self.game.skip_task(task["id"])
        self.assertIn("session is running", str(caught.exception))

    def test_a_quest_not_scheduled_today_cannot_be_skipped(self):
        off = next(d for d in range(1, 8) if d != TODAY.isoweekday())
        task = self.make_task(days=[off])
        with self.assertRaises(GameError) as caught:
            self.game.skip_task(task["id"])
        self.assertIn("isn't scheduled today", str(caught.exception))

    def test_a_missing_quest_cannot_be_skipped(self):
        with self.assertRaises(GameError):
            self.game.skip_task(9999)

    def test_unskip_reopens_the_quest_for_today(self):
        task = self.make_task()
        self.game.skip_task(task["id"])

        result = self.game.unskip_task(task["id"])
        self.assertEqual(result["outcome"], "unskipped")
        self.assertFalse(self.card(result["state"], task["id"])["skipped_today"])
        self.assertEqual(self.game.complete_task(task["id"])["outcome"], "completed")

    def test_unskip_needs_a_skip_to_take_back(self):
        task = self.make_task()
        with self.assertRaises(GameError) as caught:
            self.game.unskip_task(task["id"])
        self.assertIn("wasn't skipped", str(caught.exception))

    def test_a_skip_does_not_break_the_hero_day_streak(self):
        task = self.make_task()
        self.game._conn.execute(
            "UPDATE character SET last_active_day = ?, day_streak = 4 WHERE id = 1",
            (days_ago(2),),
        )
        self.game._conn.commit()
        self.add_skip(task["id"], days_ago(1))

        result = self.game.complete_task(task["id"])
        self.assertEqual(result["state"]["character"]["day_streak"], 5)

    def test_the_same_gap_without_a_skip_does_break_the_hero_day_streak(self):
        task = self.make_task()
        self.game._conn.execute(
            "UPDATE character SET last_active_day = ?, day_streak = 4 WHERE id = 1",
            (days_ago(2),),
        )
        self.game._conn.commit()

        result = self.game.complete_task(task["id"])
        self.assertEqual(result["state"]["character"]["day_streak"], 1)

    def test_a_skip_is_excused_from_the_reckoning(self):
        task = self.make_task()
        self.add_skip(task["id"], days_ago(1))
        self.game._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reckoned_day', ?)",
            (days_ago(1),),
        )
        self.game._conn.commit()

        state = self.game.state()
        self.assertIsNone(state["day_reckoning"])
        self.assertEqual(state["character"]["hp"], state["character"]["max_hp"])

    def test_a_missed_day_without_a_skip_costs_health(self):
        self.make_task()
        self.game._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('reckoned_day', ?)",
            (days_ago(1),),
        )
        self.game._conn.commit()

        state = self.game.state()
        self.assertIsNotNone(state["day_reckoning"])
        self.assertEqual(state["day_reckoning"]["missed"][0]["task_id"], 1)
        self.assertLess(state["character"]["hp"], state["character"]["max_hp"])

    def test_a_skip_does_not_block_a_perfect_day_heal(self):
        skipped = self.make_task(name="Away")
        done = self.make_task(name="Done")
        self.game.skip_task(skipped["id"])
        self.game._set_hp(10)
        self.game._conn.commit()

        result = self.game.complete_task(done["id"])
        char = result["state"]["character"]
        self.assertEqual(char["hp"], char["max_hp"])


class SkipApiTests(unittest.TestCase):
    """The routes the browser calls."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-skip-api-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)
        self.httpd = build_server(self.game, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, path, body=None):
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_skip_and_unskip_over_http(self):
        task = self.game.create_task({"name": "Daily", "xp": 5, "coins": 5})

        status, payload = self.post("/api/tasks/%d/skip" % task["id"], {"reason": "sick"})
        self.assertEqual(status, 200)
        card = [t for t in payload["state"]["tasks"] if t["id"] == task["id"]][0]
        self.assertTrue(card["skipped_today"])
        self.assertEqual(card["skip_reason"], "sick")

        status, payload = self.post("/api/tasks/%d/skip" % task["id"])
        self.assertEqual(status, 400)
        self.assertIn("already skipped", payload["error"])

        status, payload = self.post("/api/tasks/%d/unskip" % task["id"])
        self.assertEqual(status, 200)
        card = [t for t in payload["state"]["tasks"] if t["id"] == task["id"]][0]
        self.assertFalse(card["skipped_today"])

    def test_skipping_an_unknown_quest_is_a_400(self):
        status, payload = self.post("/api/tasks/424242/skip")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_the_state_payload_carries_skip_fields(self):
        task = self.game.create_task({"name": "Daily"})
        self.post("/api/tasks/%d/skip" % task["id"])
        with urllib.request.urlopen(self.base + "/api/state", timeout=10) as resp:
            state = json.loads(resp.read().decode("utf-8"))
        card = [t for t in state["tasks"] if t["id"] == task["id"]][0]
        self.assertTrue(card["skipped_today"])
        self.assertIn("skip_reason", card)


if __name__ == "__main__":
    unittest.main()
