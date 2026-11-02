import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clipwright import tracker
from clipwright.tracker import TrackerError

NOW = "2026-11-02T10:00:00"
LATER = "2026-11-03T10:00:00"


def cand(video_id="abc", views=1000, title="A talk"):
    return {"id": video_id, "title": title, "channel": "Chan", "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration": 3600, "views": views, "license_label": "Standard YouTube licence (all rights reserved)"}


class StoreTest(unittest.TestCase):
    def test_load_missing_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tracker.load(Path(d) / "state.json"), {"sources": {}, "clips": {}})

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tracker" / "state.json"
            state = tracker.load(path)
            tracker.upsert_source(state, cand(), "tech", NOW)
            tracker.save(path, state)
            self.assertEqual(tracker.load(path), state)

    def test_save_is_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            state = tracker.load(path)
            tracker.upsert_source(state, cand("one"), "tech", NOW)
            tracker.save(path, state)
            before = path.read_text()
            tracker.upsert_source(state, cand("two"), "tech", NOW)
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    tracker.save(path, state)
            self.assertEqual(path.read_text(), before)
            self.assertEqual(sorted(os.listdir(d)), ["state.json"])  # no temp file left behind

    def test_corrupt_file_names_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text("{not json")
            with self.assertRaises(TrackerError) as cm:
                tracker.load(path)
            self.assertIn(str(path), str(cm.exception))

    def test_wrong_shape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text("[1, 2]")
            with self.assertRaises(TrackerError):
                tracker.load(path)

    def test_non_ascii_note_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            state = tracker.load(path)
            tracker.upsert_source(state, cand(), "mythology", NOW)
            tracker.set_source(state, "abc", note="Rāma kathā, राम", now=NOW)
            tracker.save(path, state)
            self.assertIn("राम", path.read_text(encoding="utf-8"))
            self.assertEqual(tracker.load(path)["sources"]["abc"]["note"], "Rāma kathā, राम")


class SourcesTest(unittest.TestCase):
    def test_new_source_defaults(self):
        state = tracker.load(Path("/nonexistent/state.json"))
        row = tracker.upsert_source(state, cand(), "tech", NOW)
        self.assertEqual((row["status"], row["permission"], row["note"], row["domain"]),
                         ("found", "unchecked", "", "tech"))
        self.assertEqual(row["found_at"], NOW)

    def test_upsert_keeps_user_edits(self):
        state = {"sources": {}, "clips": {}}
        tracker.upsert_source(state, cand(views=1000), "tech", NOW)
        tracker.set_source(state, "abc", status="approved", permission="granted", note="emailed", now=NOW)
        row = tracker.upsert_source(state, cand(views=2000, title="Renamed"), "tech", LATER)
        self.assertEqual((row["status"], row["permission"], row["note"]), ("approved", "granted", "emailed"))
        self.assertEqual((row["views"], row["title"]), (2000, "Renamed"))
        self.assertEqual(row["found_at"], NOW)

    def test_upsert_keeps_the_first_domain(self):
        state = {"sources": {}, "clips": {}}
        tracker.upsert_source(state, cand(), "tech", NOW)
        row = tracker.upsert_source(state, cand(), "health", LATER)
        self.assertEqual(row["domain"], "tech")

    def test_invalid_values_rejected(self):
        state = {"sources": {}, "clips": {}}
        tracker.upsert_source(state, cand(), "tech", NOW)
        for kwargs in ({"status": "done"}, {"permission": "yes"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TrackerError):
                    tracker.set_source(state, "abc", now=NOW, **kwargs)
        with self.assertRaises(TrackerError):
            tracker.set_clip(state, "job", 1, mark="great", now=NOW)

    def test_unknown_source_raises(self):
        with self.assertRaises(TrackerError):
            tracker.set_source({"sources": {}, "clips": {}}, "missing", status="approved", now=NOW)

    def test_rejected_ids(self):
        state = {"sources": {}, "clips": {}}
        for vid in ("a", "b", "c"):
            tracker.upsert_source(state, cand(vid), "tech", NOW)
        tracker.set_source(state, "a", status="rejected", now=NOW)
        tracker.set_source(state, "c", status="approved", now=NOW)
        self.assertEqual(tracker.rejected_ids(state), {"a"})


class ClipsTest(unittest.TestCase):
    def test_set_clip_keys_and_posted(self):
        state = {"sources": {}, "clips": {}}
        row = tracker.set_clip(state, "J1", 2, mark="ok", note="good", now=NOW)
        self.assertIn("J1/02", state["clips"])
        self.assertEqual((row["mark"], row["note"]), ("ok", "good"))
        row = tracker.set_clip(state, "J1", 2, posted={"platform": "youtube", "url": "https://youtu.be/x"}, now=LATER)
        self.assertEqual(row["mark"], "ok")  # earlier fields survive
        self.assertEqual(row["posted"]["platform"], "youtube")
        self.assertEqual(row["posted"]["at"], LATER)


class SyncTest(unittest.TestCase):
    def state_with(self, *ids):
        state = {"sources": {}, "clips": {}}
        for vid in ids:
            tracker.upsert_source(state, cand(vid), "tech", NOW)
        return state

    def test_sync_advances_only(self):
        state = self.state_with("a", "b", "c", "d", "e")
        tracker.set_source(state, "b", status="rejected", now=NOW)
        tracker.set_source(state, "d", status="posted", now=NOW)
        tracker.set_source(state, "e", status="approved", now=NOW)
        tracker.sync_statuses(state, {
            "a": {"fetched": True, "clips": 0, "verified": False},
            "b": {"fetched": True, "clips": 3, "verified": True},
            "c": {"fetched": True, "clips": 2, "verified": False},
            "d": {"fetched": True, "clips": 2, "verified": False},
            "e": {"fetched": False, "clips": 0, "verified": False},
        })
        status = {k: v["status"] for k, v in state["sources"].items()}
        self.assertEqual(status, {"a": "fetched", "b": "rejected", "c": "clipped", "d": "posted", "e": "approved"})

    def test_sync_marks_verified_and_ignores_unknown_jobs(self):
        state = self.state_with("a")
        tracker.sync_statuses(state, {"a": {"fetched": True, "clips": 2, "verified": True}, "zzz": {"fetched": True, "clips": 1, "verified": True}})
        self.assertEqual(state["sources"]["a"]["status"], "verified")
        self.assertNotIn("zzz", state["sources"])


if __name__ == "__main__":
    unittest.main()
