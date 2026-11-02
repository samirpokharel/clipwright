import json
import unittest
from pathlib import Path

from clipwright import pipeline, style
from clipwright.style import StyleError

ROOT = Path(__file__).resolve().parent.parent


def brand():
    return style.load_brand(ROOT / "brand.json")


def seg(**extra):
    base = {"start_time": "00:10", "end_time": "00:50", "text": "x", "hook_title": "T"}
    base.update(extra)
    return base


class ParserTest(unittest.TestCase):
    def test_render_flags_parse(self):
        args = pipeline.build_parser().parse_args(
            ["render", "job1", "seg.json", "--recompose", "--allow-brand-override", "--no-music", "--no-pop",
             "--only", "1", "3", "--exact", "--no-subtitles"])
        self.assertEqual(args.cmd, "render")
        self.assertTrue(args.recompose and args.allow_brand_override and args.no_music and args.no_pop)
        self.assertFalse(args.no_whoosh or args.no_sting)
        self.assertEqual(args.only, [1, 3])
        self.assertTrue(args.exact and args.no_subtitles)

    def test_render_defaults(self):
        args = pipeline.build_parser().parse_args(["render", "job1", "seg.json"])
        self.assertFalse(args.recompose or args.allow_brand_override or args.no_music)
        self.assertIsNone(args.only)
        self.assertEqual(args.clip_length, "auto")
        self.assertEqual(args.max_seconds, 60.0)

    def test_other_commands_parse(self):
        p = pipeline.build_parser()
        self.assertEqual(p.parse_args(["schema"]).cmd, "schema")
        self.assertEqual(p.parse_args(["profiles"]).cmd, "profiles")
        prev = p.parse_args(["brand-preview", "job1", "--segment", "2"])
        self.assertEqual((prev.cmd, prev.job, prev.segment), ("brand-preview", "job1", 2))
        add = p.parse_args(["sounds", "add", "123", "--kind", "whoosh"])
        self.assertEqual((add.cmd, add.sounds_cmd, add.target, add.kind), ("sounds", "add", "123", "whoosh"))
        own = p.parse_args(["sounds", "add", "--file", "x.mp3", "--kind", "music", "--license", "own"])
        self.assertEqual((own.file, own.license), ("x.mp3", "own"))
        self.assertEqual(p.parse_args(["sounds", "list"]).sounds_cmd, "list")


class ResolveAllTest(unittest.TestCase):
    def resolve(self, segments, **kw):
        return pipeline.resolve_all(segments, brand(), ROOT / "profiles", **kw)

    def test_segment_without_style_gets_base_style(self):
        styles = self.resolve([seg()])
        self.assertEqual(styles[0]["caption"]["words_per_line"], 3)

    def test_profile_name_resolves_via_directory(self):
        styles = self.resolve([seg(style={"profile": "performance"}), seg(style={"profile": "explainer"})])
        self.assertEqual(styles[0]["sound"]["music"], "off")
        self.assertEqual(styles[1]["sound"]["music"], "low")

    def test_override_applies_on_top_of_profile(self):
        styles = self.resolve([seg(style={"profile": "performance", "sound": {"music": "low"}})])
        self.assertEqual(styles[0]["sound"]["music"], "low")

    def test_validate_all_segments_before_any_render(self):  # RF3
        segments = [seg(), seg(style={"profile": "nope"}), seg(style={"title": {"seconds": 99}})]
        with self.assertRaises(StyleError) as cm:
            self.resolve(segments)
        message = str(cm.exception)
        self.assertIn("segment 2", message)
        self.assertIn("nope", message)
        self.assertIn("segment 3", message)
        self.assertIn("title.seconds", message)
        self.assertNotIn("segment 1:", message)

    def test_no_music_flag_overrides_style(self):
        styles = self.resolve([seg(), seg(style={"profile": "explainer"})], disabled=("music", "pop"))
        for st in styles:
            self.assertEqual(st["sound"]["music"], "off")
            self.assertEqual(st["sound"]["pop"], "off")
            self.assertNotEqual(st["sound"]["whoosh"], "off")

    def test_locked_identity_needs_flag(self):
        with self.assertRaises(StyleError):
            self.resolve([seg(style={"accent": "#FF0000"})])
        styles = self.resolve([seg(style={"accent": "#FF0000"})], allow_brand_override=True)
        self.assertEqual(styles[0]["identity"]["accent"], "#FF0000")


class HelpersTest(unittest.TestCase):
    def test_clip_filename(self):
        self.assertEqual(pipeline.clip_filename(2, seg(start_time="03:42", end_time="04:28")), "02_clip_0342-0428.mp4")

    def test_replace_output_swaps_in_new_clip_and_removes_superseded_ones(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "01_clip_0000-0010.mp4").write_bytes(b"old")      # superseded render of segment 1
            (out / "02_clip_0020-0030.mp4").write_bytes(b"other")    # a different segment, must stay
            part = out / "01_clip_0005-0015.part.mp4"
            part.write_bytes(b"new")
            dest = out / "01_clip_0005-0015.mp4"
            pipeline.replace_output(part, dest, 1)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["01_clip_0005-0015.mp4", "02_clip_0020-0030.mp4"])
            self.assertEqual(dest.read_bytes(), b"new")

    def test_truncate_ranges_stops_at_requested_seconds(self):
        self.assertEqual(pipeline.truncate_ranges([(10.0, 12.0), (20.0, 25.0)], 3.0), [(10.0, 12.0), (20.0, 21.0)])

    def test_truncate_ranges_short_clip_unchanged(self):
        self.assertEqual(pipeline.truncate_ranges([(10.0, 11.0)], 3.0), [(10.0, 11.0)])

    def test_schema_text_is_json_with_fields(self):
        data = json.loads(pipeline.schema_text())
        self.assertIn("caption.words_per_line", data["fields"])

    def test_profiles_text_lists_resolved_values(self):
        data = json.loads(pipeline.profiles_text(brand(), ROOT / "profiles"))
        self.assertEqual(set(data), {"explainer", "performance", "interview", "tutorial"})
        self.assertEqual(data["performance"]["resolved"]["sound"]["music"], "off")
        self.assertIn("description", data["performance"])


if __name__ == "__main__":
    unittest.main()
