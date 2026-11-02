import json
import tempfile
import unittest
from pathlib import Path

from clipwright import domains, package

ROOT = Path(__file__).resolve().parent.parent
HEALTH = domains.load_pack("health", ROOT / "domains")
TAGS = ["#heart", "#health", "#cardiology"]


def segment(**over):
    seg = {"title": "Why this heart tip matters", "description": "A cardiologist explains one habit in 40 seconds.",
           "hashtags": list(TAGS), "thumbnail_time": 1.5}
    seg.update(over)
    return seg


STATE = {"source": "https://www.youtube.com/watch?v=abc", "title": "Heart Talk", "channel": "Dr Podcast",
         "attribution": None}


class CheckPostTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(package.check_post(segment(), 1), [])

    def test_title_limit(self):
        self.assertEqual(package.check_post(segment(title="x" * 100), 1), [])
        self.assertTrue(any("title" in p for p in package.check_post(segment(title="x" * 101), 1)))
        self.assertTrue(any("title" in p for p in package.check_post(segment(title="  "), 1)))
        problems = package.check_post({k: v for k, v in segment().items() if k != "title"}, 3)
        self.assertTrue(problems[0].startswith("segment 3:"))

    def test_hashtags_rules(self):
        cases = {
            "missing hash": ["heart", "#health", "#cardio"],
            "too few": ["#heart", "#health"],
            "too many": [f"#t{i}" for i in range(7)],
            "has a space": ["#heart", "#hea lth", "#cardio"],
            "bare hash": ["#heart", "#", "#cardio"],
            "not a list": "#heart #health #cardio",
        }
        for label, tags in cases.items():
            with self.subTest(label):
                self.assertTrue(any("hashtags" in p for p in package.check_post(segment(hashtags=tags), 1)))
        self.assertEqual(package.check_post(segment(hashtags=["#राम", "#Rāma", "#snake_case1"]), 1), [])
        self.assertEqual(package.check_post(segment(hashtags=[f"#t{i}" for i in range(6)]), 1), [])

    def test_missing_description_blocked(self):
        self.assertTrue(any("description" in p for p in package.check_post(segment(description=""), 1)))

    def test_bad_thumbnail_time(self):
        for bad in (-1, "soon", True):
            with self.subTest(bad=bad):
                self.assertTrue(any("thumbnail_time" in p for p in package.check_post(segment(thumbnail_time=bad), 1)))
        seg = segment()
        del seg["thumbnail_time"]
        self.assertEqual(package.check_post(seg, 1), [])


class MergeBuildTest(unittest.TestCase):
    def test_merge_edits_wins(self):
        merged = package.merge_edits(segment(), {"title": "Edited", "hashtags": ["#a", "#b", "#c"], "cover": "b"})
        self.assertEqual((merged["title"], merged["hashtags"], merged["cover"]), ("Edited", ["#a", "#b", "#c"], "b"))
        self.assertEqual(merged["description"], segment()["description"])
        self.assertNotIn("cover", package.merge_edits(segment(), None))
        self.assertNotIn("cover", package.merge_edits(segment(), {"cover": "z"}))

    def test_build_post_description_order(self):
        post = package.build_post(segment(), state=STATE, pack=HEALTH, credits=["Whoosh by alice (CC-BY)"])
        d = post["description"]
        positions = [d.index(x) for x in ("A cardiologist explains", "Source: Heart Talk by Dr Podcast",
                                          "Sound: Whoosh by alice", "General information, not medical advice.",
                                          "#heart #health #cardiology")]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(post["title"], "Why this heart tip matters")

    def test_cc_by_uses_attribution_line(self):
        state = dict(STATE, attribution='"Heart Talk" by Dr Podcast, licensed under Creative Commons Attribution (CC BY)')
        d = package.build_post(segment(), state=state, pack=None, credits=[])["description"]
        self.assertIn("licensed under Creative Commons Attribution (CC BY)", d)
        self.assertNotIn("Source: Heart Talk", d)

    def test_no_disclaimer_without_pack_and_none_for_tech(self):
        d = package.build_post(segment(), state=STATE, pack=None, credits=[])["description"]
        self.assertNotIn("not medical advice", d)

    def test_local_source_has_no_source_line(self):
        d = package.build_post(segment(), state={"source": "/work/video.mp4"}, pack=None, credits=[])["description"]
        self.assertNotIn("Source:", d)

    def test_caption_has_five_hashtags_at_most(self):
        post = package.build_post(segment(hashtags=[f"#t{i}" for i in range(6)]), state=STATE, pack=None, credits=[])
        self.assertTrue(post["caption"].startswith("Why this heart tip matters\n\n"))
        self.assertEqual(post["caption"].count("#"), 5)

    def test_post_text_has_labelled_sections(self):
        text = package.post_text(package.build_post(segment(), state=STATE, pack=None, credits=[]))
        for label in ("TITLE", "DESCRIPTION", "CAPTION"):
            self.assertIn(label, text)
        self.assertIn("Why this heart tip matters", text)


class CoverAndSlugTest(unittest.TestCase):
    def test_cover_times(self):
        self.assertEqual(package.cover_times(30.0, None), [1.5, 12.0, 22.5])
        self.assertEqual(package.cover_times(30.0, 40), [29.8, 12.0, 22.5])
        self.assertEqual(package.cover_times(30.0, 0), [0.2, 12.0, 22.5])

    def test_slug(self):
        self.assertEqual(package.slug("Why Karna never...", 1), "01_why_karna_never")
        self.assertEqual(package.slug("", 2), "02_clip")
        self.assertEqual(package.slug("राम कथा", 3), "03_clip")
        self.assertEqual(package.slug("Rāma kathā", 4), "04_rama_katha")
        self.assertLessEqual(len(package.slug("word " * 30, 5)), 40)

    def test_frame_args_exact(self):
        self.assertEqual(package.frame_args("in.mp4", 1.5, "out.jpg"),
                         ["ffmpeg", "-y", "-v", "error", "-ss", "1.50", "-i", "in.mp4",
                          "-frames:v", "1", "-q:v", "2", "out.jpg"])


class WritePackageTest(unittest.TestCase):
    def test_write_clip_package_files(self):
        post = package.build_post(segment(title="Rāma aur Sītā ki kahānī", hashtags=["#rama", "#sita", "#katha"]),
                                  state=STATE, pack=None, credits=[])
        calls = []

        def fake_run(args, **kw):
            calls.append(args)
            Path(args[-1]).write_bytes(b"jpeg:" + args[args.index("-ss") + 1].encode())

        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "clip.mp4"
            video.write_bytes(b"video")
            folder = Path(d) / "upload" / "01_clip"
            package.write_clip_package(folder, video, post, [1.5, 12.0, 22.5], "b", run=fake_run)
            names = sorted(p.name for p in folder.iterdir())
            self.assertEqual(names, ["cover.jpg", "cover_a.jpg", "cover_b.jpg", "cover_c.jpg",
                                     "post.json", "post.txt", "video.mp4"])
            self.assertEqual((folder / "cover.jpg").read_bytes(), (folder / "cover_b.jpg").read_bytes())
            self.assertEqual((folder / "video.mp4").read_bytes(), b"video")
            self.assertEqual(json.loads((folder / "post.json").read_text(encoding="utf-8"))["title"],
                             "Rāma aur Sītā ki kahānī")
            self.assertIn("Rāma aur Sītā ki kahānī", (folder / "post.txt").read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 3)

    def test_unknown_cover_choice_falls_back_to_a(self):
        def fake_run(args, **kw):
            Path(args[-1]).write_bytes(args[-1].encode())

        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "c.mp4"
            video.write_bytes(b"v")
            folder = Path(d) / "f"
            package.write_clip_package(folder, video, {"title": "t", "description": "d", "hashtags": [], "caption": "c"},
                                       [1, 2, 3], "zzz", run=fake_run)
            self.assertEqual((folder / "cover.jpg").read_bytes(), (folder / "cover_a.jpg").read_bytes())


if __name__ == "__main__":
    unittest.main()
