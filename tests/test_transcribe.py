import unittest
from collections import namedtuple
from pathlib import Path

from clipwright import transcribe
from clipwright.transcribe import TranscribeError

Word = namedtuple("Word", "start end word probability")
Segment = namedtuple("Segment", "start end text words")


def segments():
    return [
        Segment(0.0, 2.1, " Alright, so here we are,", [Word(0.0, 0.4, " Alright,", 0.9), Word(0.4, 0.7, " so", 0.8)]),
        Segment(2.1, 4.0, " one of the elephants.", [Word(2.1, 2.3, " one", 0.7), Word(2.7, 3.4, " elephants.", 0.95)]),
    ]


class ToWhisperResultTest(unittest.TestCase):
    def test_shape_matches_what_supoclip_reads(self):
        result = transcribe.to_whisper_result(segments(), "en")
        self.assertEqual(result["language"], "en")
        self.assertEqual(len(result["segments"]), 2)
        first = result["segments"][0]
        self.assertEqual((first["start"], first["end"]), (0.0, 2.1))
        self.assertEqual(first["text"], " Alright, so here we are,")
        self.assertEqual(first["words"][0], {"word": " Alright,", "start": 0.0, "end": 0.4, "probability": 0.9})

    def test_text_is_the_segments_joined(self):
        result = transcribe.to_whisper_result(segments(), "en")
        self.assertEqual(result["text"], "Alright, so here we are, one of the elephants.")

    def test_segment_without_words_gets_an_empty_list(self):
        result = transcribe.to_whisper_result([Segment(0.0, 1.0, " Hi.", None)], "en")
        self.assertEqual(result["segments"][0]["words"], [])

    def test_empty_input_gives_empty_result(self):
        result = transcribe.to_whisper_result([], None)
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["text"], "")

    def test_a_generator_is_consumed_once(self):
        result = transcribe.to_whisper_result((s for s in segments()), "en")
        self.assertEqual(len(result["segments"]), 2)


class PickBackendTest(unittest.TestCase):
    def test_auto_prefers_faster_when_installed(self):
        for requested in (None, "", "auto"):
            self.assertEqual(transcribe.pick_backend(requested, True), "faster")
            self.assertEqual(transcribe.pick_backend(requested, False), "openai")

    def test_explicit_choices(self):
        self.assertEqual(transcribe.pick_backend("openai", True), "openai")
        self.assertEqual(transcribe.pick_backend("faster", True), "faster")

    def test_asking_for_faster_when_missing_is_a_clear_error(self):
        with self.assertRaises(TranscribeError) as cm:
            transcribe.pick_backend("faster", False)
        self.assertIn("setup.sh", str(cm.exception))

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(TranscribeError) as cm:
            transcribe.pick_backend("whisperx", True)
        self.assertIn("whisperx", str(cm.exception))


class DecodeCommandTest(unittest.TestCase):
    def test_decodes_to_16khz_mono_float(self):
        cmd = transcribe.decode_command(Path("/v/with space.mp4"))
        self.assertEqual(cmd[0], "ffmpeg")
        text = " ".join(cmd)
        for part in ("-vn", "-ac 1", "-ar 16000", "-f f32le"):
            self.assertIn(part, text)
        self.assertIn("/v/with space.mp4", cmd)  # passed as one argument, no shell quoting needed
        self.assertEqual(cmd[-1], "-")


if __name__ == "__main__":
    unittest.main()
