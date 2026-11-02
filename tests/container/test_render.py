"""Pass 2 end to end inside the supoclip-backend image, on the cached 19 s test job."""
import asyncio
import json
import re
import subprocess
import unittest
from pathlib import Path

from clipwright import compose, sounds, style

if not Path("/app/src").exists():
    raise unittest.SkipTest("container tests: run tests/container.sh")

WORK = Path("/work")
SOURCE = WORK / "tmp/youtube-cache/jNQXAC9IVRw/full-1080.mp4"
CACHE = WORK / "tmp/test-pass1"
KEY_WORDS = ["elephants", "trunks", "zzzz-not-spoken"]  # last one never appears (RF1)
ACCENT = (255, 212, 0)


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + [
        "-show_entries", entries, "-of", "csv=p=0", str(path)]
    return run(cmd, check=True).stdout.strip()


def accent_fraction(path, t, y0, rows, width=1080):
    """Fraction of pixels near the accent colour in a horizontal band of the frame at time t."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
         "-vf", f"crop={width}:{rows}:0:{y0}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    px = [raw[i:i + 3] for i in range(0, len(raw), 3)]
    near = sum(1 for p in px if all(abs(p[k] - ACCENT[k]) < 40 for k in range(3)))
    return near / max(1, len(px))


def mean_lufs(path):
    out = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"]).stderr
    return float(re.findall(r"I:\s+(-?[0-9.]+) LUFS", out)[-1])


class ComposeRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CACHE.mkdir(parents=True, exist_ok=True)
        entry_file = CACHE / "entry.json"
        if entry_file.exists() and Path(json.loads(entry_file.read_text())["pass1"]).exists():
            entry = json.loads(entry_file.read_text())
        else:
            entry = cls.make_pass1(entry_file)
        entry = dict(entry, hook_title="The cool thing about elephants", key_words=KEY_WORDS)
        cls.entry = entry

        brand = style.load_brand(WORK / "brand.json")
        cls.style = style.resolve_style(brand, None, None, where="segment 1")
        sounds_dir = WORK / "tmp/test-sounds"
        cls.sounds_dir = sounds_dir
        library = sounds.load_library(sounds_dir, ensure=True)
        cls.analysis = compose.analyze_clip(entry)
        plan = sounds.plan_mix(cls.style, entry["duration"], cls.analysis["pops"], cls.analysis["shots"],
                               library, 0, False)
        cls.plan = plan
        cls.out = CACHE / "composed.mp4"
        compose.compose_clip(entry, cls.style, plan, cls.out, CACHE / "work", sounds_dir)

    @staticmethod
    def make_pass1(entry_file):
        from src.services.video_service import VideoService
        seg = {"start_time": "00:00", "end_time": "00:18", "text": "x", "relevance_score": 0.8, "reasoning": "",
               "virality_score": 0, "hook_title": None, "hook_start_time": None, "hook_end_time": None}
        clips = asyncio.run(VideoService.create_video_clips(SOURCE, [seg], add_subtitles=False,
                                                            output_format="vertical", max_clip_seconds=60.0))
        clip = clips[0]
        kept = CACHE / "pass1.mp4"
        kept.write_bytes(Path(clip["path"]).read_bytes())
        entry = {"pass1": str(kept), "source": str(SOURCE), "keep_ranges": clip["keep_ranges"],
                 "duration": float(clip["duration"])}
        entry_file.write_text(json.dumps(entry))
        return entry

    def test_output_is_1080x1920_h264_aac_with_matching_duration(self):
        self.assertEqual(probe(self.out, "stream=width,height,codec_name", "v:0"), "h264,1080,1920")
        self.assertEqual(probe(self.out, "stream=codec_name", "a:0"), "aac")
        self.assertAlmostEqual(float(probe(self.out, "format=duration")), self.entry["duration"], delta=0.2)

    def test_unmatched_key_word_is_reported_and_clip_still_rendered(self):  # RF1
        self.assertEqual(self.analysis["unmatched"], ["zzzz-not-spoken"])
        self.assertTrue(self.out.exists())
        self.assertGreaterEqual(len(self.analysis["pops"]), 1)

    def test_title_accent_present_at_1s_and_absent_at_6s(self):
        title_band = dict(y0=96, rows=260)
        self.assertGreater(accent_fraction(self.out, 1.0, **title_band), 0.02)
        self.assertLess(accent_fraction(self.out, 6.0, **title_band), 0.002)

    def test_progress_bar_grows_across_the_clip(self):
        # 3 interior rows: yuv420 chroma subsampling shifts the colour of the outermost row of a 5 px bar
        bar = dict(y0=1916, rows=3)
        d = self.entry["duration"]
        self.assertLess(accent_fraction(self.out, 0.2, **bar), 0.05)
        self.assertGreater(accent_fraction(self.out, d - 0.3, **bar), 0.9)

    def test_loudness_is_near_target(self):
        # single-pass loudnorm on a short clip; the spec allows about 1 LU, measured here with margin
        self.assertAlmostEqual(mean_lufs(self.out), -14.0, delta=2.0)

    def test_sound_events_were_planned(self):
        kinds = {e.kind for e in self.plan.events}
        self.assertTrue({"sting", "outro"} <= kinds)
        self.assertIsNotNone(self.plan.music)

    def test_clip_without_audio_track_renders_with_sound_effects_only(self):  # RF5
        silent = CACHE / "pass1-silent.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-i", self.entry["pass1"], "-an", "-c:v", "copy", str(silent)], check=True)
        entry = dict(self.entry, pass1=str(silent))
        out = CACHE / "composed-silent.mp4"
        compose.compose_clip(entry, self.style, self.plan, out, CACHE / "work", self.sounds_dir)
        self.assertEqual(probe(out, "stream=codec_name", "a:0"), "aac")
        self.assertEqual(probe(out, "stream=width,height", "v:0"), "1080,1920")


if __name__ == "__main__":
    unittest.main()
