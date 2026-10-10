"""A tiny JSON API. Routes match on method + path, handlers return (status, body)."""

from __future__ import annotations

import json
import re
from typing import Callable

from .store import Game, GameError


class Api:
    def __init__(self, game: Game):
        self.game = game
        self.routes: list[tuple[str, re.Pattern, Callable]] = []
        self._register()

    def _route(self, method: str, pattern: str, handler: Callable) -> None:
        self.routes.append((method, re.compile("^" + pattern + "$"), handler))

    def _register(self) -> None:
        g = self.game

        self._route("GET", r"/api/state", lambda m, q, b: (200, g.state()))
        self._route("GET", r"/api/tasks", lambda m, q, b: (200, {"tasks": g.list_tasks()}))
        self._route("GET", r"/api/shop", lambda m, q, b: (200, {"shop": g.shop_list()}))
        self._route("GET", r"/api/achievements",
                    lambda m, q, b: (200, {"achievements": g.achievements_state()}))
        self._route("GET", r"/api/activity",
                    lambda m, q, b: (200, {"activity": g.activity(int(q.get("limit", 25)))}))
        self._route("GET", r"/api/history",
                    lambda m, q, b: (200, g.history(int(q.get("days", 30)))))

        self._route("POST", r"/api/character", self._create_character)
        self._route("POST", r"/api/demo", self._demo)
        self._route("POST", r"/api/reset", self._reset)

        self._route("POST", r"/api/tasks", self._create_task)
        self._route("PUT", r"/api/tasks/(\d+)", self._update_task)
        self._route("PATCH", r"/api/tasks/(\d+)", self._update_task)
        self._route("DELETE", r"/api/tasks/(\d+)", self._delete_task)
        self._route("POST", r"/api/tasks/(\d+)/complete", self._complete_task)
        self._route("POST", r"/api/tasks/(\d+)/undo", self._undo_task)

        self._route("POST", r"/api/skills/upgrade", self._upgrade_stat)

        self._route("POST", r"/api/shop/buy", self._buy)
        self._route("POST", r"/api/shop/equip", self._equip)
        self._route("POST", r"/api/shop/unequip", self._unequip)

    # -- handlers ---------------------------------------------------------
    def _create_character(self, m, q, body):
        name = body.get("name", "Adventurer")
        archetype = body.get("archetype", "warrior")
        state = self.game.create_character(name, archetype)
        return 201, {"ok": True, "state": state}

    def _demo(self, m, q, body):
        force = bool(body.get("force"))
        return 200, {"ok": True, "state": self.game.seed_demo(force=force)}

    def _reset(self, m, q, body):
        self.game.reset()
        return 200, {"ok": True, "state": self.game.state()}

    def _create_task(self, m, q, body):
        task = self.game.create_task(body)
        return 201, {"ok": True, "task": task, "state": self.game.state()}

    def _update_task(self, m, q, body):
        task = self.game.update_task(int(m.group(1)), body)
        return 200, {"ok": True, "task": task, "state": self.game.state()}

    def _delete_task(self, m, q, body):
        state = self.game.delete_task(int(m.group(1)))
        return 200, {"ok": True, "state": state}

    def _complete_task(self, m, q, body):
        return 200, self.game.complete_task(int(m.group(1)))

    def _undo_task(self, m, q, body):
        return 200, self.game.undo_task(int(m.group(1)))

    def _upgrade_stat(self, m, q, body):
        stat = body.get("stat", "")
        amount = body.get("amount", 1)
        return 200, self.game.upgrade_stat(stat, amount)

    def _buy(self, m, q, body):
        return 200, self.game.buy_item(body.get("item_id", ""))

    def _equip(self, m, q, body):
        return 200, self.game.equip_item(body.get("item_id", ""))

    def _unequip(self, m, q, body):
        return 200, self.game.unequip_slot(body.get("slot", ""))

    # -- dispatch ---------------------------------------------------------
    def handle(self, method: str, path: str, query: dict, body: dict) -> tuple[int, dict]:
        if path == "/api/health":
            return 200, {"ok": True, "service": "habitquest"}
        for route_method, pattern, handler in self.routes:
            if route_method != method:
                continue
            match = pattern.match(path)
            if match:
                try:
                    return handler(match, query, body)
                except GameError as exc:
                    return 400, {"ok": False, "error": str(exc)}
                except Exception as exc:  # pragma: no cover - defensive
                    return 500, {"ok": False, "error": f"Internal error: {exc}"}
        return 404, {"ok": False, "error": f"No route for {method} {path}"}


def dumps(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
