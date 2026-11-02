"""Layout renders inside the image, on the real presenter shot from the cached Drumeo video."""
import json
import subprocess
import unittest
from pathlib import Path

if not Path("/app/src").exists():
    raise unittest.SkipTest("container tests: run tests/container.sh")

from clipwright import layout, render_layout

WORK = Path("/work")
SOURCE = WORK / "tmp/youtube-cache/aMoVyJ9_M24/full-1080.mp4"
FOLDER = WORK / "tmp/test-layout"
KEEP = (308.5, 334.0)  # presenter talking to camera, holds up a book


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True)


def probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + [
        "-show_entries", entries, "-of", "csv=p=0", str(path)]
    return run(cmd).stdout.strip()


def sharpness(path, t, y0, rows, width=1080):
    """Mean absolute horizontal gradient of grey pixels in a band: high for detail, low for blur."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-vf", f"crop={width}:{rows}:0:{y0},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    total = 0
    count = 0
    for r in range(rows):
        row = raw[r * width:(r + 1) * width]
        total += sum(abs(row[i + 1] - row[i]) for i in range(width - 1))
        count += width - 1
    return total / count


class LayoutRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FOLDER.mkdir(parents=True, exist_ok=True)
        cls.fill = FOLDER / "fill.mp4"
        cls.fill_info = render_layout.render_layout_clip(SOURCE, KEEP, {"mode": "fill", "ranges": []}, cls.fill, FOLDER)
        cls.mixed = FOLDER / "mixed.mp4"
        # source 05:20 to 05:28 is clip time 11.5 to 19.5: shown whole, the rest filled
        cls.mixed_info = render_layout.render_layout_clip(
            SOURCE, KEEP, {"mode": "fill", "ranges": [(320.0, 328.0, "fit")]}, cls.mixed, FOLDER)

    def test_fill_is_1080x1920_with_audio_and_the_right_duration(self):
        self.assertEqual(probe(self.fill, "stream=width,height,codec_name", "v:0"), "h264,1080,1920")
        self.assertEqual(probe(self.fill, "stream=codec_name", "a:0"), "aac")
        self.assertAlmostEqual(float(probe(self.fill, "format=duration")), KEEP[1] - KEEP[0], delta=0.25)

    def test_fill_is_one_run_cropped_around_the_presenter(self):
        self.assertEqual([r[2] for r in self.fill_info["runs"]], ["fill"])
        self.assertGreaterEqual(self.fill_info["faces"], 3, "the face tracker found too few faces to place the crop")
        cx = self.fill_info["xs"][0] + layout.crop_width(1080) / 2
        self.assertTrue(700 <= cx <= 1220, f"crop centre {cx} is not near the presenter (centre ~960)")

    def test_mixed_clip_has_three_runs_in_order(self):
        self.assertEqual([r[2] for r in self.mixed_info["runs"]], ["fill", "fit", "fill"])
        self.assertAlmostEqual(self.mixed_info["runs"][1][0], 11.5, delta=0.05)
        self.assertAlmostEqual(self.mixed_info["runs"][1][1], 19.5, delta=0.05)

    def test_fit_run_is_blurred_above_and_below_and_fill_run_is_sharp_everywhere(self):
        in_fit, in_fill = 15.0, 4.0
        fit_ratio = sharpness(self.mixed, in_fit, 0, 400) / sharpness(self.mixed, in_fit, 760, 400)
        fill_ratio = sharpness(self.mixed, in_fill, 0, 400) / sharpness(self.mixed, in_fill, 760, 400)
        # in the fit run the top band is blur while the centre strip is sharp; in the fill run both are picture
        self.assertLess(fit_ratio, 0.5, f"fit top/centre sharpness {fit_ratio:.2f}")
        self.assertGreater(fill_ratio, fit_ratio * 1.5, f"fill {fill_ratio:.2f} vs fit {fit_ratio:.2f}")

    def test_mixed_clip_duration_and_audio_match(self):
        self.assertAlmostEqual(float(probe(self.mixed, "format=duration")), KEEP[1] - KEEP[0], delta=0.25)
        self.assertEqual(probe(self.mixed, "stream=codec_name", "a:0"), "aac")


if __name__ == "__main__":
    unittest.main()
