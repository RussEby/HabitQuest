"""The portable hero sheet: what leaves Habit Quest, and in what shape.

A second app consumes this document (a story or battle site), so these tests
pin the contract: the format name and version, the fields a battle needs, the
stable identity of the hero, and the promise that quests and journal data stay
behind.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from habitquest import __version__
from habitquest import data as D
from habitquest import engine as E
from habitquest.server import build_server
from habitquest.store import Game


class ExportTestBase(unittest.TestCase):
    archetype = "ranger"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-export-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Rowan", self.archetype)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self):
        return self.game.character_export()


class TestDocumentShape(ExportTestBase):
    def test_the_document_names_its_format_and_version(self):
        doc = self.export()
        self.assertEqual(doc["format"], D.EXPORT_FORMAT)
        self.assertEqual(doc["format"], "habitquest.character")
        self.assertEqual(doc["format_version"], 1)
        self.assertEqual(doc["source"]["app"], "Habit Quest")
        self.assertEqual(doc["source"]["app_version"], __version__)
        self.assertRegex(doc["exported_at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_the_document_explains_its_own_stat_keys(self):
        meta = self.export()["stats_meta"]
        self.assertEqual([m["key"] for m in meta], D.STAT_KEYS)
        self.assertEqual([m["label"] for m in meta], [D.STAT_LABELS[k] for k in D.STAT_KEYS])
        self.assertEqual([m["abbr"] for m in meta], [D.STAT_ABBR[k] for k in D.STAT_KEYS])

    def test_the_hero_carries_identity_and_progress(self):
        char = self.export()["character"]
        for key in ("uid", "name", "created_at", "archetype", "level", "xp", "power",
                    "skill_points", "stats", "health", "gold", "equipment", "record"):
            self.assertIn(key, char)
        self.assertEqual(char["name"], "Rowan")
        self.assertEqual(char["archetype"]["id"], "ranger")
        self.assertEqual(char["level"], 1)
        self.assertEqual(char["xp"], 0)
        self.assertEqual(char["gold"]["current"], 100)
        self.assertEqual(char["gold"]["earned"], 100)

    def test_the_hero_base_stats_are_the_archetype_numbers(self):
        char = self.export()["character"]
        self.assertEqual(char["stats"]["base"], D.ARCHETYPE_BY_ID["ranger"]["stats"])
        self.assertEqual(char["archetype"]["base_stats"], D.ARCHETYPE_BY_ID["ranger"]["stats"])

    def test_quests_the_journal_and_achievements_are_not_exported(self):
        doc = self.export()
        self.assertEqual(set(doc), {"format", "format_version", "exported_at", "source",
                                    "stats_meta", "character"})
        self.assertEqual(set(doc["character"]), {
            "uid", "name", "created_at", "archetype", "level", "xp",
            "level_floor_xp", "level_xp", "level_xp_needed", "level_progress",
            "next_level_xp", "max_level", "power", "skill_points", "stats",
            "health", "gold", "equipment", "record",
        })
        # The save has starter quests and a log; none of it may ride along.
        self.assertNotIn("tasks", json.dumps(doc))
        self.assertNotIn("achievements", json.dumps(doc))

    def test_level_fields_match_the_game_curve(self):
        self.game._conn.execute("UPDATE character SET xp = 1500 WHERE id = 1")
        self.game._conn.commit()
        char = self.export()["character"]
        info = E.level_from_xp(1500)
        self.assertEqual(char["level"], info["level"])
        self.assertEqual(char["level_xp"], info["level_xp"])
        self.assertEqual(char["level_xp_needed"], info["level_xp_needed"])
        self.assertEqual(char["next_level_xp"], info["next_level_xp"])
        self.assertEqual(char["level_progress"], info["level_progress"])
        self.assertFalse(char["max_level"])


class TestStatsAndGear(ExportTestBase):
    def test_gear_bonuses_are_included_in_the_totals(self):
        self.game.buy_item("wooden_sword")      # +1 STR
        self.game.equip_item("wooden_sword")
        char = self.export()["character"]

        self.assertEqual(char["stats"]["gear"]["str"], 1)
        self.assertEqual(char["stats"]["gear"]["vit"], 0)
        self.assertEqual(char["stats"]["total"]["str"],
                         char["stats"]["base"]["str"] + 1)
        self.assertEqual(char["stats"]["total"],
                         E.total_stats(char["stats"]["base"], char["stats"]["gear"]))

    def test_power_uses_the_same_formula_as_the_app(self):
        self.game.buy_item("wooden_sword")
        self.game.equip_item("wooden_sword")
        char = self.export()["character"]
        expected = E.power_score({"str": char["stats"]["base"]["str"],
                                  "int": char["stats"]["base"]["int"],
                                  "vit": char["stats"]["base"]["vit"],
                                  "agi": char["stats"]["base"]["agi"],
                                  "cha": char["stats"]["base"]["cha"]},
                                 char["stats"]["gear"], char["level"])
        self.assertEqual(char["power"], expected)
        self.assertGreater(char["power"], 0)

    def test_every_slot_is_present_and_empty_slots_are_null(self):
        equipment = self.export()["character"]["equipment"]
        self.assertEqual(list(equipment), D.SLOT_IDS)
        self.assertTrue(all(equipment[slot] is None for slot in D.SLOT_IDS))

    def test_an_equipped_item_travels_with_its_bonuses(self):
        self.game.buy_item("wooden_sword")
        self.game.equip_item("wooden_sword")
        item = self.export()["character"]["equipment"]["weapon"]
        self.assertEqual(item["id"], "wooden_sword")
        self.assertEqual(item["name"], "Wooden Sword")
        self.assertEqual(item["slot"], "weapon")
        self.assertEqual(item["rarity"], "common")
        self.assertEqual(item["rarity_label"], "Common")
        self.assertEqual(item["bonus"], {"str": 1})
        self.assertEqual(item["bonus_text"], "+1 STR")
        self.assertGreater(item["price"], 0)

    def test_unequipping_removes_the_bonus_from_the_export(self):
        self.game.buy_item("wooden_sword")
        self.game.equip_item("wooden_sword")
        self.game.unequip_slot("weapon")
        char = self.export()["character"]
        self.assertIsNone(char["equipment"]["weapon"])
        self.assertEqual(sum(char["stats"]["gear"].values()), 0)

    def test_health_reports_current_and_maximum(self):
        char = self.export()["character"]
        self.assertEqual(char["health"]["max_hp"],
                         E.max_hp(char["stats"]["total"], char["level"]))
        self.assertEqual(char["health"]["hp"], char["health"]["max_hp"])
        self.assertEqual(char["health"]["pct"], 1.0)
        self.assertFalse(char["health"]["wounded"])

        self.game._apply_damage(5)
        wounded = self.export()["character"]["health"]
        self.assertEqual(wounded["hp"], char["health"]["max_hp"] - 5)
        self.assertFalse(wounded["wounded"])


class TestIdentity(ExportTestBase):
    def test_the_uid_is_stable_across_exports(self):
        first = self.export()["character"]["uid"]
        second = self.export()["character"]["uid"]
        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_a_new_hero_gets_a_new_uid(self):
        first = self.export()["character"]["uid"]
        self.game.reset()
        self.game.create_character("Bramble", "mage")
        third = self.export()["character"]["uid"]
        self.assertNotEqual(first, third)


class TestExportOverHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-export-api-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Rowan the Swift", "rogue")
        self.httpd = build_server(self.game, host="127.0.0.1", port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetch(self):
        req = urllib.request.Request(self.base + "/api/character/export")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, json.loads(resp.read().decode("utf-8"))

    def test_the_export_downloads_as_a_named_json_file(self):
        status, headers, doc = self.fetch()
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        self.assertIn("habit-quest-rowan-the-swift-", headers["Content-Disposition"])
        self.assertTrue(headers["Content-Disposition"].endswith('.json"'))
        self.assertEqual(doc["format"], "habitquest.character")
        self.assertEqual(doc["character"]["name"], "Rowan the Swift")

    def test_exporting_before_a_hero_exists_is_a_client_error(self):
        self.game.reset()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 400)
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertIn("character", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()
