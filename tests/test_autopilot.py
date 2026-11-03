import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from clipwright import brands, discover, postqueue as pq, postspec

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS = {"timezone": "Asia/Kathmandu", "slots": ["09:00", "19:30"], "stagger_minutes": 20,
            "platforms": {"youtube": {}, "tiktok": {}}}
# 2026-11-03 08:00 in Kathmandu (UTC+5:45)
NOW = datetime(2026, 11, 3, 2, 15, tzinfo=timezone.utc)


def post(**extra):
    credit = "Credit: TEDx Talks (https://youtu.be/x)"
    base = {"brand": "mind", "file": "out/mind/j/01.mp4", "duration": 53.5, "source_url": "https://youtu.be/x",
            "credit": credit,
            "platforms": {"youtube": {"title": "T", "description": f"d\n{credit}", "tags": ["a", "b c"]},
                          "tiktok": {"caption": f"hook {credit}"}}}
    base.update(extra)
    return base


class AccountsTest(unittest.TestCase):
    def write(self, data):
        tmp = Path(tempfile.mkdtemp()) / "accounts.json"
        tmp.write_text(json.dumps(data))
        return tmp

    def test_example_is_valid(self):
        acc = brands.load_accounts(ROOT / "brands/example/accounts.json")
        self.assertEqual(acc["slots"], ["09:00", "13:00", "19:30"])

    def test_errors_are_listed_together(self):
        bad = dict(ACCOUNTS, timezone="Mars/Base", slots=["9am"], platforms={"facebook": {}, "myspace": {}})
        with self.assertRaises(brands.BrandError) as cm:
            brands.load_accounts(self.write(bad))
        msg = str(cm.exception)
        for part in ("timezone", "slots", "facebook.page_id", "myspace"):
            self.assertIn(part, msg)


class IdeasTest(unittest.TestCase):
    def test_next_and_mark(self):
        path = Path(tempfile.mkdtemp()) / "ideas.md"
        path.write_text("# notes\n- [x] old  <!-- done: a -->\n- [ ] first idea\n- [ ] second\n")
        self.assertEqual(brands.next_idea(path), "first idea")
        brands.mark_idea(path, "first idea", False, "no good source --> really")
        self.assertEqual(brands.next_idea(path), "second")
        self.assertIn("- [!] first idea  <!-- failed: no good source  really -->", path.read_text())
        self.assertTrue(path.read_text().startswith("# notes\n"))
        with self.assertRaises(brands.BrandError):
            brands.mark_idea(path, "first idea", True, "x")


class PostSpecTest(unittest.TestCase):
    def test_valid_post_passes(self):
        postspec.validate(post())

    def test_missing_credit_in_text_is_refused(self):
        p = post()
        p["platforms"]["tiktok"]["caption"] = "no credit here"
        with self.assertRaisesRegex(postspec.PostError, "tiktok: the credit line"):
            postspec.validate(p)

    def test_limits(self):
        p = post(duration=120)
        p["platforms"]["youtube"]["title"] = "x" * 101 + "<"
        p["platforms"]["facebook"] = {"caption": p["credit"]}
        with self.assertRaises(postspec.PostError) as cm:
            postspec.validate(p)
        msg = str(cm.exception)
        self.assertIn("101", msg.replace("102", "101"))
        self.assertIn("< and >", msg)
        self.assertIn("facebook: clip is 120s", msg)

    def test_tag_length_counts_quotes_and_commas(self):
        self.assertEqual(postspec._tags_length(["a", "b c"]), 1 + 5 + 1)


class SlotTest(unittest.TestCase):
    def test_first_free_slot_today_with_stagger(self):
        slots = pq.next_slots(ACCOUNTS, ["youtube", "tiktok"], [], NOW)
        self.assertEqual(slots["base"], "2026-11-03T03:15:00Z")          # 09:00 local
        self.assertEqual(slots["at"]["tiktok"], "2026-11-03T03:35:00Z")  # +20 min

    def test_taken_and_too_close_slots_are_skipped(self):
        late = NOW + timedelta(minutes=55)                                  # 08:55 local: 09:00 is within lead
        slots = pq.next_slots(ACCOUNTS, ["youtube"], ["2026-11-03T13:45:00Z"], late)
        self.assertEqual(slots["base"], "2026-11-04T03:15:00Z")          # 19:30 taken -> tomorrow 09:00


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.db = pq.connect(Path(tempfile.mkdtemp()) / "q.db")

    def test_enqueue_books_distinct_slots_and_refuses_duplicates(self):
        a = pq.enqueue(self.db, "mind", "a.json", ACCOUNTS, ["youtube", "tiktok"], NOW)
        b = pq.enqueue(self.db, "mind", "b.json", ACCOUNTS, ["youtube"], NOW)
        self.assertNotEqual(a["youtube"], b["youtube"])
        with self.assertRaisesRegex(pq.QueueError, "already queued"):
            pq.enqueue(self.db, "mind", "a.json", ACCOUNTS, ["youtube"], NOW)

    def test_due_uses_native_schedule_window(self):
        pq.enqueue(self.db, "mind", "a.json", ACCOUNTS, ["youtube", "tiktok"], NOW)
        self.assertEqual([r["platform"] for r in pq.due(self.db, NOW)], ["youtube"])
        later = NOW + timedelta(hours=2)
        self.assertEqual({r["platform"] for r in pq.due(self.db, later)}, {"youtube", "tiktok"})

    def test_claim_once_then_backoff_then_failed(self):
        pq.enqueue(self.db, "mind", "a.json", ACCOUNTS, ["tiktok"], NOW)
        row = pq.rows(self.db)[0]
        self.assertTrue(pq.claim(self.db, row["id"]))
        self.assertFalse(pq.claim(self.db, row["id"]))
        self.assertEqual(pq.fail(self.db, row["id"], "503", now=NOW), "pending")
        self.assertEqual(pq.rows(self.db)[0]["next_try_at"], pq.iso(NOW + timedelta(minutes=15)))
        for _ in range(2):
            pq.claim(self.db, row["id"])
            status = pq.fail(self.db, row["id"], "503", now=NOW)
        self.assertEqual(status, "failed")

    def test_stale_upload_fails_without_retry(self):
        pq.enqueue(self.db, "mind", "a.json", ACCOUNTS, ["tiktok"], NOW)
        rid = pq.rows(self.db)[0]["id"]
        pq.claim(self.db, rid)
        stale = pq.recover_stale(self.db, pq.now_utc() + timedelta(hours=2))
        self.assertEqual(len(stale), 1)
        self.assertEqual(pq.rows(self.db)[0]["status"], "failed")
        self.assertEqual(pq.due(self.db, NOW + timedelta(days=1)), [])
        pq.retry(self.db, rid)
        self.assertEqual(pq.rows(self.db)[0]["status"], "pending")

    def test_quota(self):
        pq.add_quota(self.db, "youtube", 1600)
        self.assertEqual(pq.add_quota(self.db, "youtube", 1600), 3200)


class DiscoverTest(unittest.TestCase):
    def runner(self, lines):
        return lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(l) for l in lines), stderr="")

    def test_rank_prefers_reach_and_drops_shorts_and_reuploads(self):
        items = [
            {"id": "a", "title": "Talk", "channel": "TEDx Talks", "view_count": 7_000_000, "duration": 1100},
            {"id": "b", "title": "Speech", "channel": "AlexKaltsMotivation", "view_count": 9_000_000, "duration": 900},
            {"id": "c", "title": "Short", "channel": "X", "view_count": 5_000_000, "duration": 50},
            {"id": "a", "title": "Talk", "channel": "TEDx Talks", "view_count": 7_000_000, "duration": 1100},
            {"id": "d", "title": "AI narration", "channel": "Brain Facts", "view_count": 40, "duration": 400},
        ]
        ranked = discover.discover(["q"], runner=self.runner(items))
        self.assertEqual([r["id"] for r in ranked], ["a", "b", "d"])
        self.assertEqual(ranked[0]["url"], "https://www.youtube.com/watch?v=a")


if __name__ == "__main__":
    unittest.main()


class ReviewAndProduceTest(unittest.TestCase):
    def setUp(self):
        from clipwright import review, produce
        self.review, self.produce = review, produce
        self.work = Path(tempfile.mkdtemp())
        b = self.work / "brands/mind"
        b.mkdir(parents=True)
        (b / "accounts.json").write_text(json.dumps(dict(ACCOUNTS, slots=["00:00", "12:00"])))
        (b / "ideas.md").write_text("- [ ] silence and stress\n- [ ] next one\n")
        (self.work / "out/mind/job1").mkdir(parents=True)
        self.rel = "out/mind/job1/01.post.json"
        (self.work / self.rel).write_text(json.dumps(post(brand="mind")))
        self.db = pq.connect(self.work / "q.db")

    def test_awaiting_then_approve_keeps_all_copy(self):
        self.assertEqual([i["post_json"] for i in self.review.awaiting(self.work, self.db)], [self.rel])
        slots = self.review.approve(self.work, self.db, self.rel, ["tiktok"], {"tiktok": {"caption": f"edited {post()['credit']}"}})
        self.assertEqual(list(slots), ["tiktok"])
        saved = json.loads((self.work / self.rel).read_text())
        self.assertIn("youtube", saved["platforms"])
        self.assertTrue(saved["platforms"]["tiktok"]["caption"].startswith("edited"))
        self.assertEqual(saved["review"]["platforms"], ["tiktok"])
        self.assertEqual(self.review.awaiting(self.work, self.db), [])

    def test_approve_refuses_edits_that_drop_the_credit(self):
        with self.assertRaises(postspec.PostError):
            self.review.approve(self.work, self.db, self.rel, ["tiktok"], {"tiktok": {"caption": "no credit"}})
        self.assertEqual(pq.rows(self.db), [])

    def test_reject_and_path_guard(self):
        self.review.reject(self.work, self.rel, "weak hook")
        self.assertEqual(self.review.awaiting(self.work, self.db), [])
        with self.assertRaises(ValueError):
            self.review.reject(self.work, "brands/mind/accounts.json", "x")

    def test_produce_marks_idea_from_result(self):
        def runner(cmd, cwd, **kw):
            self.assertEqual(cmd[:2], ["claude", "-p"])
            self.assertIn('Idea: "silence and stress"', cmd[2])
            import re
            result = re.search(r"(jobs/_produce/\S+\.json)", cmd[2]).group(1)
            (Path(cwd) / result).write_text(json.dumps({"status": "done", "posts": [self.rel]}))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        out = self.produce.produce_brand(self.work, "mind", runner=runner, log=lambda s: None)
        self.assertEqual(out["posts"], [self.rel])
        self.assertIn("- [x] silence and stress  <!-- done: job1 -->", (self.work / "brands/mind/ideas.md").read_text())

    def test_produce_without_result_flags_idea(self):
        out = self.produce.produce_brand(self.work, "mind", log=lambda s: None,
                                         runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="x"))
        self.assertEqual(out["status"], "failed")
        self.assertEqual(brands.next_idea(self.work / "brands/mind/ideas.md"), "next one")
