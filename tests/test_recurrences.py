"""A quest can owe a set number of repeats instead of running forever.

The final repeat pays exactly what every other one paid; the only thing that
changes is that the quest leaves the board for the archive. A skipped day does
not count as a repeat, so it pushes the finish one occurrence further out.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from habitquest.server import build_server
from habitquest.store import Game, GameError


class RecurrenceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-repeat-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Tester", "warrior", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, name="Daily walk", repeats=0, days=None, **extra):
        payload = {"name": name, "days": days or [1, 2, 3, 4, 5, 6, 7],
                   "xp": 10, "coins": 5, "recurrences": repeats}
        payload.update(extra)
        return self.game.create_task(payload)

    def complete_on_a_new_day(self, task_id):
        """Complete a quest again by shifting its last completion a day back."""
        row = self.game._one(
            "SELECT id, day FROM completions WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (int(task_id),))
        earlier = (date.fromisoformat(row["day"]) - timedelta(days=1)).isoformat()
        self.game._conn.execute("UPDATE completions SET day = ? WHERE id = ?",
                                (earlier, row["id"]))
        self.game._conn.commit()
        return self.game.complete_task(int(task_id))

    def stored(self, task_id):
        return self.game._one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))


class TestCountedRepeats(RecurrenceTestBase):
    def test_a_quest_repeats_forever_by_default(self):
        task = self.add()
        self.assertEqual(task["recurrences"], 0)
        self.assertEqual(task["recurrences_done"], 0)
        self.assertFalse(task["is_recurring"])
        self.assertEqual(task["recurrence_label"], "Ongoing")

    def test_a_counted_quest_reports_its_run(self):
        task = self.add(repeats=3)
        self.assertTrue(task["is_recurring"])
        self.assertEqual(task["recurrence_label"], "0 of 3")
        self.assertEqual(task["recurrences_left"], 3)

    def test_each_repeat_pays_the_normal_reward(self):
        task = self.add(repeats=2)
        xp_before = self.game.character_meta()["xp"]
        first = self.game.complete_task(task["id"])
        self.assertEqual(self.game.character_meta()["xp"], xp_before + first["rewards"]["xp"])
        self.assertEqual(first["recurrence"], {"target": 2, "done": 1, "archived": False})
        self.assertFalse(self.stored(task["id"])["archived"])

    def test_the_last_repeat_archives_the_quest_without_a_bonus(self):
        task = self.add(repeats=2)
        xp_before = self.game.character_meta()["xp"]
        first = self.game.complete_task(task["id"])
        second = self.complete_on_a_new_day(task["id"])

        self.assertEqual(second["recurrence"], {"target": 2, "done": 2, "archived": True})
        # The payout is the sum of the two completions - finishing the run
        # itself is worth nothing extra.
        self.assertEqual(self.game.character_meta()["xp"],
                         xp_before + first["rewards"]["xp"] + second["rewards"]["xp"])

        state = self.game.state()
        self.assertEqual(state["tasks"], [])
        self.assertEqual(len(state["archive"]), 1)
        kept = state["archive"][0]
        self.assertEqual(kept["name"], "Daily walk")
        self.assertEqual(kept["archive_reason"], "complete")
        self.assertEqual(kept["recurrence_label"], "2 of 2")
        self.assertEqual(kept["completions"], 2)

    def test_an_archived_quest_cannot_be_completed_or_skipped(self):
        task = self.add(repeats=1)
        self.game.complete_task(task["id"])
        with self.assertRaises(GameError):
            self.game.complete_task(task["id"])
        with self.assertRaises(GameError):
            self.game.skip_task(task["id"])

    def test_lowering_the_target_below_what_is_done_archives_it(self):
        task = self.add(repeats=5)
        self.game.complete_task(task["id"])
        updated = self.game.update_task(task["id"], {"recurrences": 1})
        self.assertTrue(updated["archived"])
        self.assertEqual(self.game.state()["tasks"], [])
        self.assertEqual(self.game.state()["archive"][0]["archive_reason"], "complete")


class TestSkipExtendsTheRun(RecurrenceTestBase):
    def test_a_skip_adds_one_repeat(self):
        task = self.add(repeats=3)
        xp_before = self.game.character_meta()["xp"]
        result = self.game.skip_task(task["id"], "out of town")
        self.assertEqual(result["recurrences"], 4)
        self.assertEqual(self.game.character_meta()["xp"], xp_before)  # no reward
        row = self.stored(task["id"])
        self.assertEqual(row["recurrences"], 4)
        self.assertEqual(row["recurrences_done"], 0)
        self.assertEqual(self.game.state()["tasks"][0]["recurrence_label"], "0 of 4")

    def test_undoing_the_skip_takes_the_extension_back(self):
        task = self.add(repeats=3)
        self.game.skip_task(task["id"])
        self.game.unskip_task(task["id"])
        self.assertEqual(self.stored(task["id"])["recurrences"], 3)

    def test_an_ongoing_quest_keeps_no_count_when_skipped(self):
        task = self.add()
        self.game.skip_task(task["id"])
        self.assertEqual(self.stored(task["id"])["recurrences"], 0)


class TestArchive(RecurrenceTestBase):
    def test_archiving_keeps_the_quest_and_its_history(self):
        task = self.add(repeats=5)
        self.game.complete_task(task["id"])
        result = self.game.archive_task(task["id"])
        self.assertEqual(result["outcome"], "archived")

        state = self.game.state()
        self.assertEqual(state["tasks"], [])
        self.assertEqual(len(state["archive"]), 1)
        kept = state["archive"][0]
        self.assertEqual(kept["archive_reason"], "manual")
        self.assertEqual(kept["completions"], 1)
        self.assertIsNotNone(kept["archived_at"])

    def test_archiving_twice_is_rejected(self):
        task = self.add()
        self.game.archive_task(task["id"])
        with self.assertRaises(GameError):
            self.game.archive_task(task["id"])

    def test_unarchiving_a_quest_that_was_set_aside_keeps_its_place(self):
        task = self.add(repeats=5)
        self.game.complete_task(task["id"])
        self.complete_on_a_new_day(task["id"])
        self.game.archive_task(task["id"])
        self.game.unarchive_task(task["id"])

        state = self.game.state()
        self.assertEqual(state["archive"], [])
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["tasks"][0]["recurrence_label"], "2 of 5")

    def test_reengaging_a_finished_quest_starts_a_fresh_run(self):
        task = self.add(repeats=2)
        self.game.complete_task(task["id"])
        self.complete_on_a_new_day(task["id"])
        self.game.unarchive_task(task["id"])

        fresh = self.game.state()["tasks"][0]
        self.assertFalse(fresh["archived"])
        self.assertEqual(fresh["recurrences_done"], 0)
        self.assertEqual(fresh["recurrence_label"], "0 of 2")
        # Lifetime completions are not wiped - only the counted run restarts.
        self.assertEqual(fresh["completions"], 2)

    def test_archiving_a_running_quest_is_rejected(self):
        task = self.add(repeats=3, mode="beat_clock", duration_minutes=5)
        self.game.start_session(task["id"])
        with self.assertRaises(GameError):
            self.game.archive_task(task["id"])

    def test_an_archived_quest_leaves_the_live_board(self):
        task = self.add()
        self.game.archive_task(task["id"])
        live = [t["id"] for t in self.game.list_tasks()]
        self.assertNotIn(task["id"], live)
        self.assertIn(task["id"],
                      [t["id"] for t in self.game.list_tasks(include_archived=True)])
        self.assertEqual([t["id"] for t in self.game.state()["archive"]], [task["id"]])


class TestUndoReopensTheRun(RecurrenceTestBase):
    def test_undoing_the_archiving_repeat_puts_the_quest_back(self):
        task = self.add(repeats=2)
        self.game.complete_task(task["id"])
        self.complete_on_a_new_day(task["id"])
        self.assertEqual(self.game.state()["tasks"], [])

        self.game.undo_task(task["id"])
        state = self.game.state()
        self.assertEqual(len(state["tasks"]), 1)
        self.assertEqual(state["archive"], [])
        self.assertEqual(state["tasks"][0]["recurrences_done"], 1)
        self.assertEqual(state["tasks"][0]["recurrence_label"], "1 of 2")

    def test_undoing_a_middle_repeat_keeps_the_quest_on_the_board(self):
        task = self.add(repeats=3)
        self.game.complete_task(task["id"])
        self.complete_on_a_new_day(task["id"])
        self.game.undo_task(task["id"])
        row = self.stored(task["id"])
        self.assertEqual(row["recurrences_done"], 1)
        self.assertEqual(row["archived"], 0)


class TestTimedQuestsCountOneRepeat(RecurrenceTestBase):
    def test_a_survived_timed_session_counts_as_one_repeat(self):
        task = self.add(repeats=1)
        self.game.update_task(task["id"], {"mode": "beat_clock", "duration_minutes": 5})
        self.game.start_session(task["id"])
        self.game._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE status = 'active'",
            ((datetime.now() - timedelta(seconds=60)).isoformat(timespec="milliseconds"),))
        self.game._conn.commit()

        result = self.game.finish_session(task["id"])
        self.assertEqual(result["outcome"], "won")
        self.assertEqual(result["recurrence"], {"target": 1, "done": 1, "archived": True})
        self.assertEqual(self.game.state()["archive"][0]["name"], "Daily walk")

    def test_finishing_a_pomodoro_quest_counts_as_one_repeat(self):
        task = self.add(repeats=1, mode="pomodoro", duration_minutes=5)
        self.game.start_session(task["id"])
        self.game._cycle_pomodoro_session(task["id"])   # bank one focus round
        result = self.game.stop_pomodoro_session(task["id"], final=True)

        self.assertEqual(result["outcome"], "won")
        self.assertEqual(result["recurrence"]["done"], 1)
        self.assertTrue(result["recurrence"]["archived"])


class TestRecurrenceApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-repeat-api-")
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

    def test_repeat_count_survives_the_round_trip(self):
        status, payload = self.request("POST", "/api/tasks", {
            "name": "Piano", "days": [1, 2, 3, 4, 5, 6, 7], "recurrences": 2})
        self.assertEqual(status, 201)
        self.assertEqual(payload["task"]["recurrence_label"], "0 of 2")
        self.assertTrue(payload["task"]["is_recurring"])

    def test_archive_and_reengage_over_http(self):
        _, created = self.request("POST", "/api/tasks", {"name": "Piano"})
        task_id = created["task"]["id"]

        status, archived = self.request("POST", f"/api/tasks/{task_id}/archive")
        self.assertEqual(status, 200)
        self.assertEqual(archived["outcome"], "archived")
        self.assertEqual(archived["state"]["tasks"], [])
        self.assertEqual(len(archived["state"]["archive"]), 1)

        status, back = self.request("POST", f"/api/tasks/{task_id}/unarchive")
        self.assertEqual(status, 200)
        self.assertEqual(back["state"]["archive"], [])
        self.assertEqual(len(back["state"]["tasks"]), 1)

    def test_completing_an_archived_quest_is_a_client_error(self):
        _, created = self.request("POST", "/api/tasks", {"name": "Piano"})
        task_id = created["task"]["id"]
        self.request("POST", f"/api/tasks/{task_id}/archive")
        status, payload = self.request("POST", f"/api/tasks/{task_id}/complete")
        self.assertEqual(status, 400)
        self.assertIn("archived", payload["error"])


if __name__ == "__main__":
    unittest.main()
