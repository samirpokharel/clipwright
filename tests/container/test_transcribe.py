"""faster-whisper inside the image, checked against the cached openai-whisper words for the 19 s zoo clip."""
import json
import re
import tempfile
import unittest
from pathlib import Path

if not Path("/app/src").exists():
    raise unittest.SkipTest("container tests: run tests/container.sh")

from clipwright import transcribe

SOURCE = Path("/work/tmp/youtube-cache/jNQXAC9IVRw/full-1080.mp4")
REFERENCE = SOURCE.with_suffix(".transcript_cache.json")


class FasterWhisperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not transcribe.faster_available():
            raise AssertionError("faster-whisper is not installed in this image; build clipwright-runtime (./setup.sh)")
        cls.result = transcribe.transcribe_faster(SOURCE, "small", None)

    def words(self):
        return [w for seg in self.result["segments"] for w in seg["words"]]

    def test_result_has_language_segments_and_word_timings(self):
        self.assertEqual(self.result["language"], "en")
        self.assertGreaterEqual(len(self.words()), 30)
        for w in self.words():
            self.assertLessEqual(w["start"], w["end"])

    def test_word_times_agree_with_the_openai_whisper_reference(self):
        def key(text):  # punctuation differs between runs ("trunks." against "trunks,"), the timing is what matters
            return re.sub(r"[^a-z0-9]", "", text.lower())

        reference = {key(w["text"]): w["start"] / 1000 for w in json.loads(REFERENCE.read_text())["words"]}
        ours = {key(w["word"]): w["start"] for w in self.words()}
        for word in ("elephants", "trunks", "cool"):
            self.assertIn(word, ours, f"{word!r} not transcribed")
            self.assertAlmostEqual(ours[word], reference[word], delta=0.5, msg=word)

    def test_supoclip_can_format_and_cache_the_result(self):
        from src.media.transcription import cache_transcript_data, format_transcript_for_analysis, load_cached_transcript_data

        lines = format_transcript_for_analysis(self.result)
        self.assertTrue(any("elephants" in line.lower() for line in lines))
        self.assertRegex(lines[0], r"^\[\d\d:\d\d - \d\d:\d\d\] ")
        with tempfile.TemporaryDirectory() as d:
            fake_video = Path(d) / "x.mp4"
            cache_transcript_data(fake_video, self.result)
            cached = load_cached_transcript_data(fake_video)
        self.assertGreaterEqual(len(cached["words"]), 30)
        self.assertTrue({"text", "start", "end"} <= set(cached["words"][0]))
        self.assertGreater(cached["words"][-1]["end"], 10000)  # milliseconds, as SupoClip expects


if __name__ == "__main__":
    unittest.main()
