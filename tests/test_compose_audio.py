import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from clipwright import compose, sounds, style

ROOT = Path(__file__).resolve().parent.parent


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True)


def band_rms_db(path, t0, t1, low=200, high=340):
    """RMS level in dB of the pad's band (220, 277, 330 Hz) over a time window."""
    out = run(["ffmpeg", "-hide_banner", "-ss", str(t0), "-t", str(t1 - t0), "-i", str(path),
               "-af", f"highpass=f={low}:poles=2,highpass=f={low}:poles=2,"
                      f"lowpass=f={high}:poles=2,lowpass=f={high}:poles=2,volumedetect", "-f", "null", "-"])
    return float(re.search(r"mean_volume: (-?[0-9.]+) dB", out.stderr).group(1))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class DuckingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        sounds.ensure_synth(d / "sounds")
        # 10 s clip: a 3 kHz tone (far above the 200-340 Hz pad band) ("speech") for the first 5 s, then silence
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=1080x1920:d=10:r=30",
             "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*3000*t)*lt(t,5)':d=10:s=48000",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(d / "pass1.mp4")])
        brand = style.load_brand(ROOT / "brand.json")
        cls.style = style.resolve_style(brand, None, {"progress_bar": {"enabled": False}}, where="segment 1")
        mix = sounds.MixPlan(music={"id": "synth-pad", "file": "synth/pad.wav", "gain_db": -12.0})
        args = compose.build_ffmpeg_args(d / "pass1.mp4", d / "out.mp4", [], cls.style, mix, 10.0, True,
                                         "/app/fonts", d / "sounds", normalize=False)
        subprocess.run(args, check=True, capture_output=True)
        cls.out = d / "out.mp4"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_music_is_at_least_6_db_lower_while_speech_plays(self):
        speech = band_rms_db(self.out, 1.5, 4.5)
        silence = band_rms_db(self.out, 6.5, 9.0)  # after the key released
        self.assertGreaterEqual(silence - speech, 6.0, f"speech {speech} dB, silence {silence} dB")

    def test_music_is_audible_in_the_silent_window(self):
        self.assertGreater(band_rms_db(self.out, 6.5, 9.0), -60.0)

    def test_normalize_false_omits_loudnorm(self):
        args = " ".join(compose.build_ffmpeg_args(
            Path("p.mp4"), Path("o.mp4"), [], self.style, sounds.MixPlan(), 5.0, True, "/f", Path("/s"), normalize=False))
        self.assertNotIn("loudnorm", args)
        self.assertIn("[mixed]anull[aout]", args)


if __name__ == "__main__":
    unittest.main()
