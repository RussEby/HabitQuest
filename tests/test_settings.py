"""Global settings: the alarm sound, its volume and an uploaded sound file.

The alarm is app-wide rather than per quest, and a custom file is copied into
the save folder so the user never has to place it anywhere themselves. These
tests cover that contract plus the upload validation the browser relies on.
"""

import base64
import io
import json
import os
import shutil
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave

from habitquest import data as D
from habitquest.server import build_server
from habitquest.store import Game, GameError


def wav_bytes(freq: int = 660, frames: int = 800) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"".join(
            struct.pack("<h", (i % 97) - 48) for i in range(frames)))
    return buf.getvalue()


class SettingsTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-settings-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Ada", "mage", starter_tasks=False)

    def tearDown(self):
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def sound_dir(self) -> str:
        return os.path.join(self.tmp, "sounds")


class TestStoreSettings(SettingsTestBase):
    def test_defaults_are_a_built_in_sound_at_a_sane_volume(self):
        settings = self.game.settings()
        self.assertEqual(settings["sound"], D.DEFAULT_ALARM_SOUND)
        self.assertAlmostEqual(settings["volume"], D.DEFAULT_ALARM_VOLUME)
        self.assertFalse(settings["custom"]["present"])
        self.assertEqual([s["id"] for s in settings["sounds"]],
                         [s["id"] for s in D.ALARM_SOUNDS])
        self.assertEqual(settings["limits"]["max_bytes"], D.ALARM_MAX_BYTES)

    def test_sound_and_volume_persist_and_are_clamped(self):
        self.game.update_settings({"sound": "chime", "volume": 0.35})
        self.assertEqual(self.game.settings()["sound"], "chime")
        self.assertAlmostEqual(self.game.settings()["volume"], 0.35)

        # A percentage is accepted too, and anything silly is clamped.
        self.assertAlmostEqual(self.game.update_settings({"volume": 80})["volume"], 0.8)
        self.assertAlmostEqual(self.game.update_settings({"volume": 500})["volume"], 1.0)
        self.assertAlmostEqual(self.game.update_settings({"volume": -3})["volume"], 0.0)

        self.assertEqual(self.game.settings()["sound"], "chime")

    def test_unknown_sound_is_refused(self):
        with self.assertRaises(GameError):
            self.game.update_settings({"sound": "airhorn"})
        self.assertEqual(self.game.settings()["sound"], D.DEFAULT_ALARM_SOUND)

    def test_custom_cannot_be_selected_before_a_file_exists(self):
        with self.assertRaises(GameError):
            self.game.update_settings({"sound": D.CUSTOM_ALARM_ID})

    def test_uploaded_file_is_copied_beside_the_save_and_becomes_the_alarm(self):
        payload = wav_bytes()
        settings = self.game.save_alarm_sound("My alarm.wav", "audio/wav", payload)

        self.assertEqual(settings["sound"], D.CUSTOM_ALARM_ID)
        self.assertTrue(settings["custom"]["present"])
        self.assertEqual(settings["custom"]["name"], "My alarm.wav")
        self.assertEqual(settings["custom"]["bytes"], len(payload))
        self.assertTrue(os.path.isfile(os.path.join(self.sound_dir, "alarm.wav")))

        served = self.game.alarm_sound()
        self.assertIsNotNone(served)
        self.assertEqual(served[0], payload)
        self.assertEqual(served[1], "audio/wav")

    def test_replacing_the_file_switches_the_extension(self):
        self.game.save_alarm_sound("one.wav", "audio/wav", wav_bytes())
        ogg = b"OggS" + b"\x00" * 128
        settings = self.game.save_alarm_sound("two.ogg", "audio/ogg", ogg)

        self.assertEqual(settings["custom"]["name"], "two.ogg")
        self.assertTrue(os.path.isfile(os.path.join(self.sound_dir, "alarm.ogg")))
        self.assertFalse(os.path.exists(os.path.join(self.sound_dir, "alarm.wav")))
        self.assertEqual(self.game.alarm_sound()[1], "audio/ogg")

    def test_bad_uploads_are_refused_and_leave_the_old_sound_alone(self):
        good = wav_bytes()
        self.game.save_alarm_sound("good.wav", "audio/wav", good)

        bad_cases = [
            ("notes.txt", "text/plain", b"hello", "WAV, MP3 or OGG"),
            ("fake.wav", "audio/wav", b"definitely not audio", "WAV"),
            ("huge.wav", "audio/wav", good + b"\x00" * D.ALARM_MAX_BYTES, "MB"),
            ("empty.wav", "audio/wav", b"", "empty"),
        ]
        for name, ctype, payload, expected in bad_cases:
            with self.assertRaises(GameError) as caught:
                self.game.save_alarm_sound(name, ctype, payload)
            self.assertIn(expected, str(caught.exception))

        self.assertEqual(self.game.settings()["custom"]["name"], "good.wav")
        self.assertEqual(self.game.alarm_sound()[0], good)

    def test_missing_file_falls_back_to_a_built_in_sound(self):
        self.game.save_alarm_sound("gone.wav", "audio/wav", wav_bytes())
        os.remove(os.path.join(self.sound_dir, "alarm.wav"))

        settings = self.game.settings()
        self.assertEqual(settings["sound"], D.DEFAULT_ALARM_SOUND)
        self.assertFalse(settings["custom"]["present"])
        self.assertIsNone(self.game.alarm_sound())

    def test_clearing_removes_the_file_and_the_selection(self):
        self.game.save_alarm_sound("ding.wav", "audio/wav", wav_bytes())
        settings = self.game.clear_alarm_sound()

        self.assertFalse(settings["custom"]["present"])
        self.assertEqual(settings["sound"], D.DEFAULT_ALARM_SOUND)
        self.assertFalse(os.path.exists(os.path.join(self.sound_dir, "alarm.wav")))

    def test_settings_travel_with_the_app_state(self):
        self.game.update_settings({"sound": "woodblock"})
        state = self.game.state()
        self.assertEqual(state["settings"]["sound"], "woodblock")


class TestSettingsApi(unittest.TestCase):
    """The same contract over HTTP, which is how the UI reaches it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq-settings-api-")
        self.game = Game(os.path.join(self.tmp, "save.db"))
        self.game.create_character("Ada", "mage", starter_tasks=False)
        self.httpd = build_server(self.game, host="127.0.0.1", port=0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.game.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method, path, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload)), resp.headers
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, (payload if raw else json.loads(payload)), exc.headers

    def test_get_settings(self):
        status, payload, _ = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(payload["settings"]["sound"], D.DEFAULT_ALARM_SOUND)

    def test_put_settings_changes_sound_and_volume(self):
        status, payload, _ = self.request(
            "PUT", "/api/settings", {"sound": "ping", "volume": 55})
        self.assertEqual(status, 200)
        self.assertEqual(payload["settings"]["sound"], "ping")
        self.assertAlmostEqual(payload["settings"]["volume"], 0.55)

    def test_rejected_setting_is_a_400(self):
        status, payload, _ = self.request("PUT", "/api/settings", {"sound": "kazoo"})
        self.assertEqual(status, 400)
        self.assertIn("Unknown alarm", payload["error"])

    def test_upload_serve_and_delete(self):
        payload = wav_bytes()
        status, body, _ = self.request("PUT", "/api/settings/sound", {
            "name": "alarm.wav", "type": "audio/wav",
            "data": base64.b64encode(payload).decode(),
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["settings"]["sound"], D.CUSTOM_ALARM_ID)

        status, served, headers = self.request("GET", "/api/sound", raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(served, payload)
        self.assertEqual(headers["Content-Type"], "audio/wav")

        status, body, _ = self.request("DELETE", "/api/settings/sound")
        self.assertEqual(status, 200)
        self.assertFalse(body["settings"]["custom"]["present"])

        status, _, _ = self.request("GET", "/api/sound", raw=True)
        self.assertEqual(status, 404)

    def test_upload_rejects_a_non_audio_file(self):
        status, body, _ = self.request("PUT", "/api/settings/sound", {
            "name": "song.mp3", "type": "audio/mpeg",
            "data": base64.b64encode(b"plain text, not audio").decode(),
        })
        self.assertEqual(status, 400)
        self.assertIn("MP3", body["error"])

    def test_upload_rejects_a_missing_payload(self):
        status, body, _ = self.request("PUT", "/api/settings/sound",
                                       {"name": "alarm.wav", "type": "audio/wav"})
        self.assertEqual(status, 400)
        self.assertIn("No sound file", body["error"])

    def test_state_carries_the_settings(self):
        status, payload, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertIn("settings", payload)
        self.assertEqual(payload["settings"]["sound"], D.DEFAULT_ALARM_SOUND)


if __name__ == "__main__":
    unittest.main()
