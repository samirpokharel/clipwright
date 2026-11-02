import json
import tempfile
import unittest
from pathlib import Path

from clipwright import freesound
from clipwright.freesound import FreesoundError, LicenceRefused

CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"
CC_BY = "http://creativecommons.org/licenses/by/4.0/"
CC_BY_NC = "http://creativecommons.org/licenses/by-nc/3.0/"
SAMPLING = "http://creativecommons.org/licenses/sampling+/1.0/"


def fake(license_url=CC0, sound_id=123):
    meta = {"id": sound_id, "name": "Whoosh 1", "username": "alice", "license": license_url,
            "url": f"https://freesound.org/people/alice/sounds/{sound_id}/",
            "previews": {"preview-hq-mp3": f"https://cdn.freesound.org/previews/{sound_id}-hq.mp3"}}
    calls = []

    def get(url):
        calls.append(url)
        return json.dumps(meta).encode() if "/apiv2/sounds/" in url else b"MP3DATA"

    return get, calls


class LicenceLabelTest(unittest.TestCase):
    def test_accepted_forms(self):
        for value in (CC0, "Creative Commons 0", "cc0"):
            self.assertEqual(freesound.licence_label(value), "CC0")
        for value in (CC_BY, "http://creativecommons.org/licenses/by/3.0/", "Attribution"):
            self.assertEqual(freesound.licence_label(value), "CC-BY")

    def test_refused_forms_name_the_licence(self):
        for value in (CC_BY_NC, SAMPLING, "Attribution NonCommercial", "http://creativecommons.org/licenses/by-sa/4.0/"):
            with self.subTest(value=value):
                with self.assertRaises(LicenceRefused) as cm:
                    freesound.licence_label(value)
                self.assertIn(value, str(cm.exception))


class ParseIdTest(unittest.TestCase):
    def test_url_and_bare_id(self):
        self.assertEqual(freesound.parse_sound_id("https://freesound.org/s/123456/"), 123456)
        self.assertEqual(freesound.parse_sound_id("https://freesound.org/people/alice/sounds/777/"), 777)
        self.assertEqual(freesound.parse_sound_id("42"), 42)

    def test_garbage_rejected(self):
        with self.assertRaises(FreesoundError):
            freesound.parse_sound_id("not a sound")


class FetchSoundTest(unittest.TestCase):
    def test_cc0_accepted_and_library_updated(self):
        get, _ = fake(CC0)
        with tempfile.TemporaryDirectory() as d:
            entry = freesound.fetch_sound(123, "whoosh", "KEY", Path(d), http_get=get)
            library = json.loads((Path(d) / "library.json").read_text())
            self.assertTrue((Path(d) / entry["file"]).exists())
        self.assertEqual(entry["license"], "CC0")
        self.assertEqual(entry["id"], "fs-123")
        self.assertEqual(library[0]["id"], "fs-123")
        self.assertEqual(entry["file"], "fx/fs-123.mp3")

    def test_music_goes_to_music_folder(self):
        get, _ = fake(CC0)
        with tempfile.TemporaryDirectory() as d:
            entry = freesound.fetch_sound(123, "music", "KEY", Path(d), http_get=get)
        self.assertEqual(entry["file"], "music/fs-123.mp3")

    def test_cc_by_accepted_with_attribution_text(self):
        get, _ = fake(CC_BY)
        with tempfile.TemporaryDirectory() as d:
            entry = freesound.fetch_sound(123, "music", "KEY", Path(d), http_get=get)
        self.assertEqual(entry["license"], "CC-BY")
        self.assertEqual(entry["author"], "alice")
        self.assertIn("Whoosh 1 by alice", entry["attribution"])

    def test_noncommercial_refused_nothing_written_nothing_downloaded(self):
        get, calls = fake(CC_BY_NC)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(LicenceRefused):
                freesound.fetch_sound(123, "whoosh", "KEY", Path(d), http_get=get)
            self.assertEqual(list(Path(d).iterdir()), [])
        self.assertEqual(len(calls), 1)  # metadata only, the preview was never requested

    def test_sampling_plus_refused(self):
        get, _ = fake(SAMPLING)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(LicenceRefused):
                freesound.fetch_sound(123, "pop", "KEY", Path(d), http_get=get)

    def test_missing_api_key_is_clear_error(self):
        get, _ = fake()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FreesoundError) as cm:
                freesound.fetch_sound(123, "pop", "", Path(d), http_get=get)
        self.assertIn("FREESOUND_API_KEY", str(cm.exception))

    def test_unknown_kind_rejected(self):
        get, _ = fake()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FreesoundError):
                freesound.fetch_sound(123, "explosion", "KEY", Path(d), http_get=get)

    def test_duplicate_id_rejected(self):
        get, _ = fake()
        with tempfile.TemporaryDirectory() as d:
            freesound.fetch_sound(123, "pop", "KEY", Path(d), http_get=get)
            with self.assertRaises(FreesoundError) as cm:
                freesound.fetch_sound(123, "pop", "KEY", Path(d), http_get=get)
        self.assertIn("fs-123", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
