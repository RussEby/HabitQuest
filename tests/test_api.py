"""End-to-end tests: drive the real HTTP server over a real socket.

These exercise the interface the browser actually talks to - routing, JSON
encoding, static asset serving and error status codes - rather than calling the
store directly.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import date, timedelta
import urllib.error
import urllib.request

from habitquest.server import build_server
from habitquest.store import Game


class ApiTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-api-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.httpd = build_server(self.game, host="127.0.0.1", port=0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method, path, body=None, raw=False):
        url = self.base + path
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload.decode("utf-8")))
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, (payload if raw else json.loads(payload.decode("utf-8")))

    def get(self, path, raw=False):
        return self.request("GET", path, raw=raw)

    def post(self, path, body=None):
        return self.request("POST", path, body or {})


class TestRoutingAndStatic(ApiTestBase):
    def test_health_check(self):
        status, payload = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_unknown_api_route_is_a_404(self):
        status, payload = self.get("/api/nonsense")
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_index_is_served_with_the_shell(self):
        status, body = self.get("/", raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b"Habit Quest", body)
        self.assertIn(b"app.js", body)

    def test_static_assets_are_served_with_useful_content_types(self):
        for path, expected in (("/styles.css", "text/css"), ("/app.js", "javascript")):
            req = urllib.request.Request(self.base + path)
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn(expected, resp.headers.get("Content-Type", ""))
                self.assertGreater(len(resp.read()), 500)

    def test_a_missing_asset_is_a_404(self):
        status, _ = self.get("/nope.js", raw=True)
        self.assertEqual(status, 404)

    def test_directory_traversal_is_refused(self):
        status, _ = self.get("/../app.py", raw=True)
        self.assertIn(status, (403, 404))

    def test_client_errors_are_reported_as_json(self):
        status, payload = self.post("/api/tasks/999999/complete")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("no longer exists", payload["error"])


class TestCharacterFlow(ApiTestBase):
    def test_playthrough(self):
        status, payload = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertFalse(payload["has_character"])

        status, payload = self.post("/api/character", {"name": "Ada", "archetype": "mage"})
        self.assertEqual(status, 201)
        state = payload["state"]
        self.assertTrue(state["has_character"])
        self.assertEqual(state["character"]["name"], "Ada")
        self.assertEqual(state["character"]["archetype"], "mage")
        self.assertEqual(len(state["tasks"]), 3)

        # Complete the first quest.
        task_id = state["tasks"][0]["id"]
        status, payload = self.post(f"/api/tasks/{task_id}/complete")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["rewards"]["xp"], 0)
        self.assertEqual(payload["state"]["character"]["total_completions"], 1)

        # Completing it again the same day is a user-facing error.
        status, payload = self.post(f"/api/tasks/{task_id}/complete")
        self.assertEqual(status, 400)
        self.assertIn("Already completed", payload["error"])

        # Undo the completion.
        status, payload = self.post(f"/api/tasks/{task_id}/undo")
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["character"]["total_completions"], 0)

    def test_create_update_delete_task(self):
        self.post("/api/character", {"name": "Ada", "archetype": "rogue"})
        status, payload = self.post("/api/tasks", {
            "name": "Journal", "stat": "cha", "xp": 8, "coins": 6, "difficulty": "easy",
        })
        self.assertEqual(status, 201)
        task = payload["task"]
        self.assertEqual(task["stat"], "cha")

        status, payload = self.request("PUT", f"/api/tasks/{task['id']}", {"name": "Journal nightly"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["name"], "Journal nightly")

        status, payload = self.request("DELETE", f"/api/tasks/{task['id']}")
        self.assertEqual(status, 200)
        self.assertNotIn(task["id"], [t["id"] for t in payload["state"]["tasks"]])

    def test_shop_and_skills_endpoints(self):
        self.post("/api/character", {"name": "Ada", "archetype": "warrior"})
        status, payload = self.get("/api/shop")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["shop"]), len(self.game.shop_list()))

        status, payload = self.post("/api/shop/buy", {"item_id": "wooden_sword"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["character"]["coins"], 40)

        status, payload = self.post("/api/shop/equip", {"item_id": "wooden_sword"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["equipped"]["weapon"]["id"], "wooden_sword")

        status, payload = self.post("/api/shop/unequip", {"slot": "weapon"})
        self.assertEqual(status, 200)
        self.assertIsNone(payload["state"]["equipped"]["weapon"])

        status, payload = self.post("/api/skills/upgrade", {"stat": "str"})
        self.assertEqual(status, 400)
        self.assertIn("No skill points", payload["error"])

    def test_unaffordable_purchase_returns_a_readable_error(self):
        self.post("/api/character", {"name": "Ada", "archetype": "warrior"})
        status, payload = self.post("/api/shop/buy", {"item_id": "excalibur"})
        self.assertEqual(status, 400)
        self.assertTrue(payload["error"])

    def test_history_and_activity_endpoints(self):
        self.post("/api/character", {"name": "Ada", "archetype": "ranger"})
        status, payload = self.get("/api/history?days=14")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["series"]), 14)
        status, payload = self.get("/api/activity?limit=5")
        self.assertEqual(status, 200)
        self.assertLessEqual(len(payload["activity"]), 5)
        status, payload = self.get("/api/achievements")
        self.assertEqual(status, 200)
        self.assertTrue(payload["achievements"])

    def test_demo_and_reset_endpoints(self):
        status, payload = self.post("/api/demo", {"force": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["state"]["character"]["total_completions"] > 0)

        status, payload = self.post("/api/reset")
        self.assertEqual(status, 200)
        self.assertFalse(payload["state"]["has_character"])

    def test_garbage_body_does_not_crash_the_server(self):
        req = urllib.request.Request(
            self.base + "/api/tasks", data=b"not json at all",
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 400)
        # and the server is still healthy afterwards
        self.assertEqual(self.get("/api/health")[0], 200)


class TestDayProbe(ApiTestBase):
    """The cheap date check the window polls instead of rebuilding all state."""

    def test_probe_answers_before_a_character_exists(self):
        status, payload = self.get("/api/day")
        self.assertEqual(status, 200)
        self.assertEqual(payload["today"], date.today().isoformat())
        self.assertIn("server_now", payload)
        self.assertIsNone(payload["armed_day"])

    def test_probe_agrees_with_the_full_state(self):
        self.post("/api/character", {"name": "Ada", "archetype": "warrior"})
        _, probe = self.get("/api/day")
        _, state = self.get("/api/state")
        self.assertEqual(probe["today"], state["today"])
        self.assertEqual(probe["armed_day"], date.today().isoformat())

    def test_probe_does_not_advance_the_ledger(self):
        self.post("/api/character", {"name": "Ada", "archetype": "warrior"})
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.game._conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'reckoned_day'", (yesterday,))
        self.game._conn.commit()
        for _ in range(3):
            status, probe = self.get("/api/day")
            self.assertEqual(status, 200)
            self.assertEqual(probe["armed_day"], yesterday)


class TestPomodoroPauseRoutes(ApiTestBase):
    """Pausing the timer and banking a quest, over the real HTTP interface."""

    def setUp(self):
        super().setUp()
        self.post("/api/character", {"name": "Ada", "archetype": "mage"})
        _, created = self.post("/api/tasks", {
            "name": "Deep work", "xp": 20, "coins": 10, "mode": "pomodoro",
            "duration_minutes": 25, "break_minutes": 5, "pomodoro_sessions": 3,
        })
        self.task_id = created["task"]["id"]

    def test_pause_and_resume_the_timer(self):
        status, _ = self.post(f"/api/tasks/{self.task_id}/session/start")
        self.assertEqual(status, 200)

        status, paused = self.post(f"/api/tasks/{self.task_id}/session/pause")
        self.assertEqual(status, 200)
        self.assertTrue(paused["session"]["paused"])

        status, resumed = self.post(f"/api/tasks/{self.task_id}/session/resume")
        self.assertEqual(status, 200)
        self.assertFalse(resumed["session"]["paused"])

    def test_pausing_the_quest_keeps_its_rounds_for_later(self):
        self.post(f"/api/tasks/{self.task_id}/session/start")
        self.post(f"/api/tasks/{self.task_id}/session/cycle")

        status, quest = self.post(f"/api/tasks/{self.task_id}/session/pause-quest")
        self.assertEqual(status, 200)
        self.assertEqual(quest["outcome"], "quest_paused")
        self.assertEqual(quest["rounds"], 1)
        self.assertIsNone(quest["state"]["session"])

        status, again = self.post(f"/api/tasks/{self.task_id}/session/start")
        self.assertEqual(status, 200)
        self.assertEqual(again["outcome"], "resumed")
        self.assertEqual(again["session"]["pomodoro"]["completed"], 1)


if __name__ == "__main__":
    unittest.main()
