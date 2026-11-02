"""UI tests. They need fastapi and httpx, so they are skipped on a plain interpreter. Run with:

    uv run --with fastapi --with httpx --with jinja2 --with python-multipart python3 -m unittest tests.test_ui
"""
import importlib.util
import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HAVE = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "jinja2", "multipart"))

if HAVE:
    from fastapi.testclient import TestClient
    from ui.app import create_app


def cand(video_id, title):
    return {"id": video_id, "title": title, "channel": "Chan", "channel_id": "UC1", "duration": 3600, "views": 50000,
            "url": f"https://www.youtube.com/watch?v={video_id}", "watchlist": False, "license_kind": "standard",
            "license_label": "Standard YouTube licence (all rights reserved)", "reuse_ok": False,
            "upload_date": "2026-10-01", "age_days": 32, "followers": 10}


def seg(**over):
    base = {"start_time": "00:00", "end_time": "00:20", "hook_title": "A hook",
            "verification": {"speaker": "Jane", "claims_checked": True},
            "title": "A fine title", "description": "A description.", "hashtags": ["#one", "#two", "#three"]}
    base.update(over)
    return base


@unittest.skipUnless(HAVE, "needs fastapi, httpx, jinja2 and python-multipart (see the module docstring)")
class UiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "domains", self.root / "domains")
        (self.root / "sources").mkdir()
        (self.root / "sources/tech.json").write_text(
            json.dumps([cand("idA", "First talk"), cand("idB", "Second talk")]), encoding="utf-8")
        for job, domain, segs in (("J1", "tech", [seg(), seg()]), ("J2", "health", [seg(verification=None)])):
            (self.root / "jobs" / job).mkdir(parents=True)
            (self.root / "jobs" / job / "state.json").write_text(json.dumps(
                {"source": f"https://www.youtube.com/watch?v={job}", "title": "T", "channel": "C", "domain": domain}))
            (self.root / "jobs" / job / "segments.json").write_text(json.dumps(segs))
            out = self.root / "out" / job
            out.mkdir(parents=True)
            manifest = []
            for n in range(1, len(segs) + 1):
                clip = out / f"{n:02d}_clip_0000-0020.mp4"
                clip.write_bytes(b"VIDEO-%d" % n)
                manifest.append({"file": str(clip), "hook_title": "A hook", "duration": 20.0, "credits": []})
            (out / "manifest.json").write_text(json.dumps(manifest))
        self.calls = []
        self.release = threading.Event()
        self.release.set()

        def runner(args):
            self.calls.append(list(args))
            self.release.wait(5)
            return {"code": 0, "output": "2 candidates for tech"}

        self.app = create_app(self.root, runner=runner)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.release.set()
        self.tmp.cleanup()

    def tracker(self):
        return json.loads((self.root / "tracker/state.json").read_text(encoding="utf-8"))

    # media -------------------------------------------------------------
    def test_media_serves_clip_inside_out(self):
        r = self.client.get("/media/J1/01_clip_0000-0020.mp4")
        self.assertEqual((r.status_code, r.content), (200, b"VIDEO-1"))

    def test_media_refuses_traversal(self):
        (self.root / "out/J1/evil.mp4").symlink_to(self.root / "jobs/J1/state.json")
        (self.root / "out/J1/notes.txt").write_text("secret")
        for path in ("/media/../jobs/J1/state.json", "/media/%2e%2e/jobs/J1/state.json",
                     "/media/J1/..%2f..%2fjobs%2fJ1%2fstate.json", "/media//etc/passwd",
                     "/media/J1/notes.txt", "/media/J1/evil.mp4", "/media/J1/.hidden.mp4", "/media/J1"):
            with self.subTest(path=path):
                self.assertNotEqual(self.client.get(path).status_code, 200)

    # sources -----------------------------------------------------------
    def test_sources_page_lists_rows(self):
        html = self.client.get("/sources?domain=tech").text
        for expected in ("First talk", "Second talk", "Approve", "Reject", "Standard YouTube licence"):
            self.assertIn(expected, html)

    def test_unknown_domain_is_404(self):
        self.assertEqual(self.client.get("/sources?domain=nope").status_code, 404)
        self.assertEqual(self.client.post("/sources/search", data={"domain": "nope"}).status_code, 404)

    def test_approve_persists_in_tracker_file(self):
        self.client.get("/sources?domain=tech")
        r = self.client.post("/sources/idA", data={"status": "approved", "permission": "granted", "note": "emailed"})
        self.assertEqual(r.status_code, 200)
        row = self.tracker()["sources"]["idA"]
        self.assertEqual((row["status"], row["permission"], row["note"]), ("approved", "granted", "emailed"))

    def test_invalid_and_derived_statuses_rejected(self):
        self.client.get("/sources?domain=tech")
        for status in ("fetched", "nonsense"):
            with self.subTest(status=status):
                self.assertEqual(self.client.post("/sources/idA", data={"status": status}).status_code, 400)
        self.assertEqual(self.client.post("/sources/zzz", data={"status": "approved"}).status_code, 404)

    def test_search_runs_one_at_a_time(self):
        self.release.clear()
        first = self.client.post("/sources/search", data={"domain": "tech"})
        self.assertEqual(first.status_code, 200)
        second = self.client.post("/sources/search", data={"domain": "tech"})
        self.assertEqual(second.status_code, 409)
        self.release.set()
        self.app.state.search_thread.join(5)
        self.assertEqual(self.calls, [["sources", "tech"]])
        self.assertIn("2 candidates for tech", self.client.get("/sources/search/status").text)

    def test_commands_partial_lists_approved_only(self):
        self.client.get("/sources?domain=tech")
        self.client.post("/sources/idA", data={"status": "approved"})
        text = self.client.get("/sources/tech/commands").text
        self.assertIn("./clip fetch --domain tech https://www.youtube.com/watch?v=idA", text)
        self.assertNotIn("idB", text)

    # clips -------------------------------------------------------------
    def test_mark_ok_persists(self):
        r = self.client.post("/clips/J1/1/mark", data={"mark": "ok", "note": "good"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tracker()["clips"]["J1/01"]["mark"], "ok")
        self.assertEqual(self.client.post("/clips/J1/1/mark", data={"mark": "great"}).status_code, 400)
        self.assertEqual(self.client.post("/clips/J1/9/mark", data={"mark": "ok"}).status_code, 404)

    def test_package_refuses_unmarked_clips(self):
        self.client.post("/clips/J1/1/mark", data={"mark": "ok"})
        r = self.client.post("/clips/J1/package")
        self.assertEqual(r.status_code, 409)
        self.assertIn("2", r.text)
        self.assertEqual(self.calls, [])

    def test_package_runs_when_all_marked(self):
        for n in (1, 2):
            self.client.post(f"/clips/J1/{n}/mark", data={"mark": "ok"})
        r = self.client.post("/clips/J1/package")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.calls, [["package", "J1"]])

    def test_post_edit_writes_file_and_reports_problems(self):
        r = self.client.post("/clips/J1/1/post", data={"title": "x" * 101, "description": "d",
                                                       "hashtags": "a, b c", "cover": "b"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("101 characters", r.text)
        self.assertIn("hashtags", r.text)
        edits = json.loads((self.root / "jobs/J1/post_edits.json").read_text(encoding="utf-8"))
        self.assertEqual(edits["1"]["title"], "x" * 101)
        self.assertEqual(edits["1"]["hashtags"], ["a", "b", "c"])
        self.assertEqual(edits["1"]["cover"], "b")

    def test_good_post_edit_has_no_problems(self):
        r = self.client.post("/clips/J1/1/post", data={"title": "Rāma kathā", "description": "d",
                                                       "hashtags": "#rama #katha, #sita", "cover": "a"})
        self.assertNotIn("class=\"problem\"", r.text)
        self.assertIn("Rāma kathā", r.text)

    def test_clip_page_shows_gate_problems(self):
        html = self.client.get("/clips").text
        self.assertIn("no verification record", html)
        self.assertIn("A fine title", html)
        self.assertIn("/media/J1/01_clip_0000-0020.mp4", html)

    # damaged files and the sources list (final review) ----------------
    def test_corrupt_post_edits_is_not_overwritten(self):
        path = self.root / "jobs/J1/post_edits.json"
        path.write_text('{"2": {"title": "other clip edit"}, BROKEN', encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        r = self.client.post("/clips/J1/1/post", data={"title": "t", "description": "d", "hashtags": "#a #b #c"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("post_edits.json", r.text)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_corrupt_tracker_gives_a_readable_message(self):
        (self.root / "tracker").mkdir()
        (self.root / "tracker/state.json").write_text("{not json", encoding="utf-8")
        for method, url, data in (("get", "/sources?domain=tech", None), ("get", "/clips", None),
                                  ("post", "/sources/idA", {"status": "approved"})):
            with self.subTest(url=url):
                r = getattr(self.client, method)(url, **({"data": data} if data else {}))
                self.assertEqual(r.status_code, 500)
                self.assertIn("fix or move it aside", r.text)
        self.assertEqual((self.root / "tracker/state.json").read_text(encoding="utf-8"), "{not json")

    def test_sources_stay_listed_after_a_later_search_drops_them(self):
        self.client.get("/sources?domain=tech")
        self.client.post("/sources/idA", data={"status": "approved", "note": "emailed"})
        (self.root / "sources/tech.json").write_text(json.dumps([cand("idB", "Second talk")]), encoding="utf-8")
        html = self.client.get("/sources?domain=tech").text
        self.assertIn("First talk", html)
        self.assertIn("emailed", html)
        self.assertIn("Second talk", html)

    def test_status_filter(self):
        self.client.get("/sources?domain=tech")
        self.client.post("/sources/idA", data={"status": "approved"})
        html = self.client.get("/sources?domain=tech&status=approved").text
        self.assertIn("First talk", html)
        self.assertNotIn("Second talk", html)
        self.assertEqual(self.client.get("/sources?domain=tech&status=bogus").status_code, 400)

    def test_video_found_in_two_domains_stays_in_the_first(self):
        (self.root / "sources/health.json").write_text(json.dumps([cand("idA", "First talk")]), encoding="utf-8")
        self.client.get("/sources?domain=tech")
        self.client.post("/sources/idA", data={"status": "approved"})
        self.client.get("/sources?domain=health")
        self.assertIn("idA", self.client.get("/sources/tech/commands").text)
        self.assertNotIn("idA", self.client.get("/sources/health/commands").text)

    # whole pages -------------------------------------------------------
    def test_pages_load_no_external_assets(self):
        for url in ("/sources?domain=tech", "/clips"):
            html = self.client.get(url).text
            with self.subTest(url=url):
                for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
                    self.assertTrue(src.startswith("/static/"), src)
                for href in re.findall(r'<link[^>]+href="([^"]+)"', html):
                    self.assertTrue(href.startswith("/static/"), href)
                self.assertIsNone(re.search(r'\bsrc="https?://', html))

    def test_root_redirects_to_sources(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))
        self.assertTrue(r.headers["location"].endswith("/sources"))


if __name__ == "__main__":
    unittest.main()
