"""Domain overlays and the gate inside the supoclip-backend image, on the cached 19 s test job."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from clipwright import compose, sounds, style

if not Path("/app/src").exists():
    raise unittest.SkipTest("container tests: run tests/container.sh")

WORK = Path("/work")
CACHE = WORK / "tmp/test-pass1"


def frame_band(path, t, y0, rows, width=1080):
    """Raw pixels of a horizontal band of the frame at time t."""
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
         "-vf", f"crop={width}:{rows}:0:{y0}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True).stdout


def different(a, b, minimum=200):
    """True when at least ``minimum`` pixels differ clearly between two bands."""
    return sum(1 for x, y in zip(a, b) if abs(x - y) > 40) >= minimum


class OverlayRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        entry_file = CACHE / "entry.json"
        if not entry_file.exists() or not Path(json.loads(entry_file.read_text())["pass1"]).exists():
            raise unittest.SkipTest("needs the cached pass 1 from test_render (run that first)")
        cls.entry = dict(json.loads(entry_file.read_text()), hook_title="The cool thing about elephants")
        brand = style.load_brand(WORK / "brand.json")
        cls.style = style.resolve_style(brand, None, None, where="segment 1")
        cls.sounds_dir = WORK / "tmp/test-sounds"
        sounds.load_library(cls.sounds_dir, ensure=True)
        cls.plain = CACHE / "overlay-plain.mp4"
        cls.over = CACHE / "overlay-on.mp4"
        mix = sounds.MixPlan()
        compose.compose_clip(cls.entry, cls.style, mix, cls.plain, CACHE / "work", cls.sounds_dir)
        compose.compose_clip(
            cls.entry, cls.style, mix, cls.over, CACHE / "work", cls.sounds_dir,
            overlays={"speaker": "Dr Rao, cardiologist", "commentary": "Context: this is the first video ever",
                      "disclaimer": "General information, not medical advice."})

    def test_speaker_line_changes_the_top_band(self):
        self.assertTrue(different(frame_band(self.plain, 0.5, 0, 90), frame_band(self.over, 0.5, 0, 90)))

    def test_disclaimer_changes_the_handle_row(self):
        self.assertTrue(different(frame_band(self.plain, 0.5, 1560, 90), frame_band(self.over, 0.5, 1560, 90)))

    def test_commentary_card_fills_the_title_slot_after_the_title(self):
        self.assertTrue(different(frame_band(self.plain, 6.0, 96, 260), frame_band(self.over, 6.0, 96, 260)))

    def test_overlays_leave_duration_and_size_alone(self):
        def probe(path, entries):
            return subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
                                  capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(probe(self.over, "stream=width,height"), probe(self.plain, "stream=width,height"))
        self.assertAlmostEqual(float(probe(self.over, "format=duration")),
                               float(probe(self.plain, "format=duration")), delta=0.1)


class GateRenderTest(unittest.TestCase):
    """clip render end to end: the gate blocks before pass 1, verified clips render, other jobs are unchanged."""

    SOURCE = WORK / "tmp/youtube-cache/jNQXAC9IVRw/full-1080.mp4"
    JOBS = ("gate-test", "gate-plain")

    @classmethod
    def setUpClass(cls):
        if not cls.SOURCE.exists():
            raise unittest.SkipTest("needs the cached jNQXAC9IVRw video")
        cls.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    @classmethod
    def cleanup(cls):
        import shutil
        for job in cls.JOBS:
            shutil.rmtree(WORK / "jobs" / job, ignore_errors=True)
            shutil.rmtree(WORK / "out" / job, ignore_errors=True)

    def render(self, job, segment, domain):
        state = {"video_path": str(self.SOURCE), "source": "local", "duration": 19.0}
        if domain:
            state["domain"] = domain
        folder = WORK / "jobs" / job
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "state.json").write_text(json.dumps(state))
        seg_file = folder / "segments.json"
        seg_file.write_text(json.dumps([segment]))
        proc = subprocess.run([sys.executable, "/work/clip.py", "render", job, str(seg_file), "--no-subtitles"],
                              capture_output=True, text=True, cwd="/app")
        return proc, sorted((WORK / "out" / job).glob("*.mp4"))

    def segment(self, **over):
        seg = {"start_time": "00:00", "end_time": "00:17", "text": "x", "hook_title": "The first video",
               "relevance_score": 0.8, "reasoning": "", "virality": {"total_score": 70}}
        seg.update(over)
        return seg

    def test_missing_verification_renders_nothing(self):
        proc, clips = self.render("gate-test", self.segment(), "tech")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("tech gate", proc.stdout + proc.stderr)
        self.assertEqual(clips, [])
        self.assertIn("BLOCKED", (WORK / "out/gate-test/verification.md").read_text())

    def test_verified_clip_renders_with_report(self):
        seg = self.segment(verification={"speaker": "Jawed Karim", "claims_checked": True},
                           commentary="The first video ever uploaded to YouTube.")
        proc, clips = self.render("gate-test", seg, "tech")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(clips), 1)
        report = (WORK / "out/gate-test/verification.md").read_text()
        self.assertIn(": OK", report)
        self.assertIn("The first video ever uploaded to YouTube.", report)

    def test_job_without_domain_renders_as_before(self):
        proc, clips = self.render("gate-plain", self.segment(), None)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(clips), 1)
        self.assertFalse((WORK / "out/gate-plain/verification.md").exists())


if __name__ == "__main__":
    unittest.main()
