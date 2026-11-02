"""Cover extraction and the package command inside the image, with real ffmpeg."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from clipwright import package

if not Path("/app/src").exists():
    raise unittest.SkipTest("container tests: run tests/container.sh")

WORK = Path("/work")


def make_clip(path, seconds=6):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=360x640:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}", "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)


class CoverTest(unittest.TestCase):
    def test_three_distinct_jpeg_covers_of_the_clip_size(self):
        post = {"title": "t", "description": "d", "hashtags": ["#a", "#b", "#c"], "caption": "c"}
        with tempfile.TemporaryDirectory(dir=WORK / "tmp") as d:
            video = Path(d) / "clip.mp4"
            make_clip(video)
            folder = Path(d) / "pkg"
            package.write_clip_package(folder, video, post, package.cover_times(6.0, None), "c")
            covers = [(folder / f"cover_{x}.jpg").read_bytes() for x in "abc"]
            for data in covers:
                self.assertEqual(data[:3], b"\xff\xd8\xff")
            self.assertEqual(len(set(covers)), 3)
            self.assertEqual((folder / "cover.jpg").read_bytes(), covers[2])
            size = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                                   str(folder / "cover_a.jpg")], capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(size, "360,640")


class PackageCommandTest(unittest.TestCase):
    JOB = "package-test"

    def tearDown(self):
        shutil.rmtree(WORK / "jobs" / self.JOB, ignore_errors=True)
        shutil.rmtree(WORK / "out" / self.JOB, ignore_errors=True)

    def run_package(self, segments, edits=None):
        job, out = WORK / "jobs" / self.JOB, WORK / "out" / self.JOB
        job.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
        (job / "state.json").write_text(json.dumps({"source": "https://www.youtube.com/watch?v=abc", "title": "Talk",
                                                    "channel": "Chan", "license_kind": "standard",
                                                    "license_label": "Standard YouTube licence (all rights reserved)"}))
        (job / "segments.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
        if edits:
            (job / "post_edits.json").write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
        manifest = []
        for n in range(1, len(segments) + 1):
            clip = out / f"{n:02d}_clip_0000-0006.mp4"
            make_clip(clip)
            manifest.append({"file": str(clip), "hook_title": "x", "duration": 6.0, "profile": None, "credits": []})
        (out / "manifest.json").write_text(json.dumps(manifest))
        proc = subprocess.run([sys.executable, "/work/clip.py", "package", self.JOB], capture_output=True, text=True, cwd="/app")
        return proc, out / "upload"

    def good(self, **over):
        seg = {"start_time": "00:00", "end_time": "00:06", "title": "Rāma aur Sītā ki kahānī",
               "description": "Ek chhoti kahānī.", "hashtags": ["#rama", "#sita", "#katha"]}
        seg.update(over)
        return seg

    def test_packages_good_clips_and_skips_bad_ones_without_stopping(self):
        proc, upload = self.run_package([self.good(), self.good(title="")])
        self.assertNotEqual(proc.returncode, 0)  # one clip was skipped
        self.assertIn("segment 2", proc.stderr)
        folders = sorted(p.name for p in upload.iterdir() if p.is_dir())
        self.assertEqual(folders, ["01_rama_aur_sita_ki_kahani"])
        post = json.loads((upload / folders[0] / "post.json").read_text(encoding="utf-8"))
        self.assertEqual(post["title"], "Rāma aur Sītā ki kahānī")
        self.assertIn("Source: Talk by Chan", post["description"])
        readme = (upload / "README.md").read_text(encoding="utf-8")
        self.assertIn("permission", readme)

    def test_a_missing_video_skips_that_clip_and_packages_the_rest(self):
        job, out = WORK / "jobs" / self.JOB, WORK / "out" / self.JOB
        proc, upload = self.run_package([self.good(), self.good(title="Second clip")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for stale in upload.iterdir():
            if stale.is_dir():
                shutil.rmtree(stale)
        next(out.glob("01_*.mp4")).unlink()  # clip 1's video is gone, its manifest entry remains
        proc = subprocess.run([sys.executable, "/work/clip.py", "package", self.JOB], capture_output=True, text=True, cwd="/app")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("segment 1", proc.stderr)
        self.assertEqual([p.name for p in upload.iterdir() if p.is_dir()], ["02_second_clip"])
        self.assertTrue((upload / "README.md").exists())

    def test_ui_edits_win_and_renaming_removes_the_old_folder(self):
        proc, upload = self.run_package([self.good()], {"1": {"title": "A new title", "cover": "b"}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([p.name for p in upload.iterdir() if p.is_dir()], ["01_a_new_title"])
        folder = upload / "01_a_new_title"
        self.assertEqual((folder / "cover.jpg").read_bytes(), (folder / "cover_b.jpg").read_bytes())


if __name__ == "__main__":
    unittest.main()
