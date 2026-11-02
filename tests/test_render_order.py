"""clip.py pass 1: segment order survives SupoClip's opening review, and the layout path honours --max-seconds.

Seen on 2026-11-03 with a four-clip health job (interview profile, so every clip took the layout path):
the opening review re-sorted the prepared list, ``zip(custom, prepared)`` paired segment 1 with segment 2's
range, and every clip was cut at 60 s although the health gate allows 90 and --max-seconds 90 was available.
"""

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import clip  # noqa: E402  (imports only clipwright modules at module level)


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


class FakeSrc:
    """A stand-in for the SupoClip ``src`` package, installed into sys.modules for one test."""

    NAMES = ("src", "src.media", "src.media.transcription", "src.services", "src.services.video_service",
             "src.video_utils")

    def __init__(self, refine, clamp):
        self.saved = {name: sys.modules.get(name) for name in self.NAMES}
        video_service = SimpleNamespace(
            _ground_segment_text=staticmethod(lambda payload, data: payload["text"]),
            _refine_segment_openings=staticmethod(refine),
        )
        sys.modules["src"] = _module("src")
        sys.modules["src.media"] = _module("src.media")
        sys.modules["src.media.transcription"] = _module("src.media.transcription",
                                                         load_cached_transcript_data=lambda path: {"words": []})
        sys.modules["src.services"] = _module("src.services")
        sys.modules["src.services.video_service"] = _module("src.services.video_service", VideoService=video_service)
        sys.modules["src.video_utils"] = _module(
            "src.video_utils",
            snap_keep_ranges_to_sentence_start=lambda path, ranges: ranges,
            extend_keep_ranges_to_sentence_boundary=lambda path, ranges: ranges,
            clamp_keep_ranges_to_max_duration=clamp,
        )

    def restore(self):
        for name, mod in self.saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def seg(start, end):
    return {"start_time": start, "end_time": end, "text": f"text {start}", "relevance_score": 0.5, "reasoning": ""}


class PrepareSegmentsOrderTest(unittest.TestCase):
    def test_prepared_payloads_stay_in_segment_order_when_the_opening_review_resorts(self):
        def refine(prepared, transcript_data, clip_length):
            return list(reversed(prepared))  # SupoClip re-sorts when it demotes an opening

        fake = FakeSrc(refine, clamp=lambda path, ranges, *a: ranges)
        try:
            segments = [seg("55:09", "56:36"), seg("77:54", "79:17"), seg("35:57", "37:19")]
            args = SimpleNamespace(exact=False, clip_length="auto")
            prepared = clip._prepare_segments(segments, [1, 2, 3], Path("video.mp4"), args)
        finally:
            fake.restore()
        self.assertEqual([p["start_time"] for p in prepared], ["55:09", "77:54", "35:57"])
        self.assertNotIn("_order", prepared[0])

    def test_only_subset_keeps_its_order_too(self):
        fake = FakeSrc(lambda prepared, *a: list(reversed(prepared)), clamp=lambda path, ranges, *a: ranges)
        try:
            segments = [seg("00:10", "00:40"), seg("01:00", "01:30"), seg("02:00", "02:30"), seg("03:00", "03:30")]
            prepared = clip._prepare_segments(segments, [2, 4], Path("v.mp4"),
                                              SimpleNamespace(exact=False, clip_length="auto"))
        finally:
            fake.restore()
        self.assertEqual([p["start_time"] for p in prepared], ["01:00", "03:00"])


class KeepRangeMaxSecondsTest(unittest.TestCase):
    def test_layout_path_passes_max_seconds_to_the_clamp(self):
        seen = {}

        def clamp(path, ranges, max_seconds=60.0):
            seen["max"] = max_seconds
            return ranges

        fake = FakeSrc(lambda prepared, *a: prepared, clamp)
        try:
            keep = clip._keep_range(Path("v.mp4"), seg("55:09", "56:36"), 90.0)
        finally:
            fake.restore()
        self.assertEqual(seen["max"], 90.0)
        self.assertEqual(keep, (55 * 60 + 9, 56 * 60 + 36))


if __name__ == "__main__":
    unittest.main()
