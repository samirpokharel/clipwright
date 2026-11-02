"""Domain overlays and the gate inside the supoclip-backend image, on the cached 19 s test job."""
import json
import subprocess
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


if __name__ == "__main__":
    unittest.main()
