import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clipwright import postqueue as pq
from clipwright.publish import auth, run_due
from clipwright.publish.base import PublishError
from clipwright.publish.meta import Facebook, Instagram
from clipwright.publish.tiktok import TikTok, chunks
from clipwright.publish.youtube import CHUNK, YouTube, video_body

CREDIT = "Credit: TEDx Talks (https://youtu.be/x)"
POST = {"brand": "mind", "file": "out/mind/j/01.mp4", "duration": 50, "source_url": "https://youtu.be/x",
        "credit": CREDIT,
        "platforms": {"youtube": {"title": "T", "description": CREDIT, "tags": ["a"]},
                      "tiktok": {"caption": f"hook {CREDIT}"}, "facebook": {"caption": f"fb {CREDIT}"},
                      "instagram": {"caption": f"ig {CREDIT}"}}}


class Fake:
    """Replays scripted responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, method, url, headers, body, timeout):
        self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
        if not self.responses:
            raise AssertionError(f"unexpected request {method} {url}")
        status, resp_headers, data = self.responses.pop(0)
        return status, resp_headers, data if isinstance(data, bytes) else json.dumps(data).encode()


def ok(data, headers=None, status=200):
    return status, headers or {}, data


class Env:
    def __init__(self):
        self.work = Path(tempfile.mkdtemp())
        sec = self.work / "secrets"
        (sec / "mind").mkdir(parents=True)
        (sec / "apps.json").write_text(json.dumps({
            "google": {"client_id": "g", "client_secret": "gs"}, "tiktok": {"client_key": "t", "client_secret": "ts"},
            "meta": {"app_id": "m", "app_secret": "ms", "graph_version": "v23.0"}}))
        far = 4_000_000_000
        (sec / "mind" / "google.json").write_text(json.dumps({"access_token": "GA", "refresh_token": "GR", "expires_at": far}))
        (sec / "mind" / "tiktok.json").write_text(json.dumps({"access_token": "TA", "refresh_token": "TR", "expires_at": far}))
        (sec / "mind" / "meta.json").write_text(json.dumps({"pages": {"111": {"name": "P", "access_token": "PT", "ig_user_id": "222"}}}))
        self.video = self.work / "v.mp4"
        self.video.write_bytes(b"x" * 1000)

    def tokens(self, transport):
        return auth.TokenStore(self.work / "secrets", "mind", transport)


def soon(hours=0, minutes=0):
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours, minutes=minutes)


class YouTubeTest(unittest.TestCase):
    def test_resumable_upload_scheduled(self):
        env = Env()
        fake = Fake(ok(b"", {"location": "https://up/session"}), ok({"id": "VID"}))
        db = pq.connect(env.work / "q.db")
        res = YouTube(fake, env.tokens(fake), db).publish(POST, env.video, soon(hours=5), {"category_id": "28"})
        self.assertEqual((res.status, res.url), ("scheduled", "https://youtube.com/shorts/VID"))
        meta = json.loads(fake.requests[0]["body"])
        self.assertEqual(meta["status"]["privacyStatus"], "private")
        self.assertIn("publishAt", meta["status"])
        self.assertEqual(meta["snippet"]["categoryId"], "28")
        self.assertEqual(fake.requests[1]["headers"]["Content-Range"], "bytes 0-999/1000")
        self.assertEqual(pq.used_quota(db, "youtube"), 1600)

    def test_past_slot_goes_public_and_308_resumes(self):
        self.assertEqual(video_body(POST, soon(minutes=-5), {})["status"]["privacyStatus"], "public")
        env = Env()
        env.video.write_bytes(b"x" * (CHUNK + 10))
        fake = Fake(ok(b"", {"location": "https://up/s"}), ok(b"", {"range": f"bytes=0-{CHUNK - 1}"}, 308),
                    ok({"id": "V2"}))
        YouTube(fake, env.tokens(fake)).publish(POST, env.video, soon(minutes=-5), {})
        self.assertEqual(fake.requests[2]["headers"]["Content-Range"], f"bytes {CHUNK}-{CHUNK + 9}/{CHUNK + 10}")

    def test_quota_guard(self):
        env = Env()
        db = pq.connect(env.work / "q.db")
        pq.add_quota(db, "youtube", 9000)
        with self.assertRaisesRegex(PublishError, "quota"):
            YouTube(Fake(), env.tokens(Fake()), db).publish(POST, env.video, soon(hours=5), {})

    def test_expired_token_is_refreshed_and_saved(self):
        env = Env()
        path = env.work / "secrets/mind/google.json"
        path.write_text(json.dumps({"access_token": "OLD", "refresh_token": "GR", "expires_at": 0}))
        fake = Fake(ok({"access_token": "NEW", "expires_in": 3600}))
        self.assertEqual(env.tokens(fake).access("google"), "NEW")
        self.assertIn(b"refresh_token=GR", fake.requests[0]["body"])
        self.assertEqual(json.loads(path.read_text())["access_token"], "NEW")
        self.assertEqual(oct(path.stat().st_mode)[-3:], "600")


class TikTokTest(unittest.TestCase):
    def test_chunking_rules(self):
        mb = 1024 * 1024
        self.assertEqual(chunks(3 * mb), [(0, 3 * mb - 1)])
        self.assertEqual(chunks(25 * mb), [(0, 10 * mb - 1), (10 * mb, 25 * mb - 1)])

    def test_unaudited_posts_private_and_polls(self):
        env = Env()
        fake = Fake(ok({"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
                                 "max_video_post_duration_sec": 600}, "error": {"code": "ok"}}),
                    ok({"data": {"publish_id": "P1", "upload_url": "https://up/t"}, "error": {"code": "ok"}}),
                    ok(b"", status=201),
                    ok({"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}}),
                    ok({"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [77]},
                        "error": {"code": "ok"}}))
        res = TikTok(fake, env.tokens(fake), sleep=lambda s: None).publish(POST, env.video, soon(), {})
        init = json.loads(fake.requests[1]["body"])
        self.assertEqual(init["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertEqual(init["source_info"], {"source": "FILE_UPLOAD", "video_size": 1000,
                                               "chunk_size": 1000, "total_chunk_count": 1})
        self.assertEqual((res.status, res.url), ("posted", "https://www.tiktok.com/video/77"))

    def test_api_error_is_not_retried(self):
        env = Env()
        fake = Fake(ok({"data": {}, "error": {"code": "spam_risk_too_many_posts", "message": "slow down"}}))
        with self.assertRaises(PublishError) as cm:
            TikTok(fake, env.tokens(fake)).publish(POST, env.video, soon(), {})
        self.assertFalse(cm.exception.retry)


class MetaTest(unittest.TestCase):
    def test_facebook_reel_scheduled(self):
        env = Env()
        fake = Fake(ok({"video_id": "FV", "upload_url": "x"}), ok({"success": True}), ok({"success": True}))
        res = Facebook(fake, env.tokens(fake)).publish(POST, env.video, soon(hours=3), {"page_id": "111"})
        self.assertEqual(res.status, "scheduled")
        self.assertEqual(fake.requests[1]["url"], "https://rupload.facebook.com/video-upload/v23.0/FV")
        self.assertEqual(fake.requests[1]["headers"]["Authorization"], "OAuth PT")
        self.assertIn(b"video_state=SCHEDULED", fake.requests[2]["body"])

    def test_instagram_reel_waits_then_publishes(self):
        env = Env()
        fake = Fake(ok({"id": "C1"}), ok({"success": True}), ok({"status_code": "IN_PROGRESS"}),
                    ok({"status_code": "FINISHED"}), ok({"id": "M1"}), ok({"permalink": "https://instagram.com/reel/abc"}))
        res = Instagram(fake, env.tokens(fake), sleep=lambda s: None).publish(POST, env.video, soon(), {"ig_user_id": "222"})
        self.assertEqual((res.status, res.remote_id, res.url), ("posted", "M1", "https://instagram.com/reel/abc"))
        self.assertIn(b"upload_type=resumable", fake.requests[0]["body"])
        self.assertIn(b"creation_id=C1", fake.requests[4]["body"])

    def test_unknown_page_is_an_auth_error(self):
        env = Env()
        with self.assertRaisesRegex(auth.AuthError, "999"):
            Facebook(Fake(), env.tokens(Fake())).publish(POST, env.video, soon(hours=3), {"page_id": "999"})


class RunDueTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        w = self.env.work
        (w / "brands/mind").mkdir(parents=True)
        (w / "brands/mind/accounts.json").write_text(json.dumps({
            "timezone": "UTC", "slots": ["00:00"], "platforms": {"tiktok": {}, "youtube": {}}}))
        (w / "out/mind/j").mkdir(parents=True)
        (w / "out/mind/j/01.mp4").write_bytes(b"v")
        (w / "out/mind/j/post.json").write_text(json.dumps(POST))
        self.db = pq.connect(w / "q.db")
        stamp = pq.iso(soon(minutes=-1))
        for p in ("tiktok", "youtube"):
            self.db.execute("INSERT INTO posts (brand, post_json, platform, slot_base, slot_at, created_at, updated_at) "
                            "VALUES ('mind', 'out/mind/j/post.json', ?, ?, ?, ?, ?)", (p, stamp, stamp, stamp, stamp))

    def adapters(self, behaviour):
        class A:
            def __init__(self, *a):
                pass

            def publish(self, post, video, slot_at, cfg):
                return behaviour()
        return {"tiktok": A, "youtube": A}

    def test_dry_run_touches_nothing(self):
        lines = []
        run_due(self.env.work, self.db, dry_run=True, log=lines.append)
        self.assertEqual(len(lines), 2)
        self.assertEqual({r["status"] for r in pq.rows(self.db)}, {"pending"})

    def test_success_then_second_run_posts_nothing(self):
        from clipwright.publish.base import Result
        run_due(self.env.work, self.db, log=lambda s: None, adapters=self.adapters(lambda: Result("posted", "R", "u")))
        self.assertEqual({r["status"] for r in pq.rows(self.db)}, {"posted"})
        again = run_due(self.env.work, self.db, log=lambda s: None,
                        adapters=self.adapters(lambda: self.fail("posted twice")))
        self.assertEqual(again, [])

    def test_unexpected_error_is_final(self):
        def boom():
            raise KeyError("id")
        run_due(self.env.work, self.db, log=lambda s: None, adapters=self.adapters(boom))
        rows = pq.rows(self.db)
        self.assertEqual({r["status"] for r in rows}, {"failed"})
        self.assertIn("check the platform", rows[0]["last_error"])

    def test_retryable_error_backs_off(self):
        def flaky():
            raise PublishError("HTTP 503", retry=True)
        run_due(self.env.work, self.db, log=lambda s: None, adapters=self.adapters(flaky))
        self.assertEqual({r["status"] for r in pq.rows(self.db)}, {"pending"})
        self.assertEqual(pq.due(self.db), [])


if __name__ == "__main__":
    unittest.main()
