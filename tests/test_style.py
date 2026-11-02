import copy
import json
import tempfile
import unittest
from pathlib import Path

from clipwright import style
from clipwright.style import StyleError

ROOT = Path(__file__).resolve().parent.parent


def brand():
    return style.load_brand(ROOT / "brand.json")


class ResolveStyleTest(unittest.TestCase):
    def test_clip_override_beats_profile_beats_base(self):
        b = brand()
        self.assertEqual(b["base"]["caption"]["words_per_line"], 3)
        profile = {"caption": {"words_per_line": 5}}
        override = {"caption": {"words_per_line": 2}}
        base_only = style.resolve_style(b, None, None, where="segment 1")
        with_profile = style.resolve_style(b, profile, None, where="segment 1")
        with_both = style.resolve_style(b, profile, override, where="segment 1")
        self.assertEqual(base_only["caption"]["words_per_line"], 3)
        self.assertEqual(with_profile["caption"]["words_per_line"], 5)
        self.assertEqual(with_both["caption"]["words_per_line"], 2)

    def test_deep_merge_keeps_sibling_keys(self):
        b = brand()
        resolved = style.resolve_style(b, None, {"sound": {"music": "off"}}, where="segment 1")
        self.assertEqual(resolved["sound"]["music"], "off")
        self.assertEqual(resolved["sound"]["pop"], b["base"]["sound"]["pop"])
        self.assertEqual(resolved["caption"]["size"], b["base"]["caption"]["size"])

    def test_out_of_bounds_names_segment_and_field(self):
        with self.assertRaises(StyleError) as cm:
            style.resolve_style(brand(), None, {"caption": {"words_per_line": 9}}, where="segment 2")
        self.assertIn("segment 2", str(cm.exception))
        self.assertIn("caption.words_per_line", str(cm.exception))

    def test_unknown_field_rejected(self):
        with self.assertRaises(StyleError) as cm:
            style.resolve_style(brand(), None, {"caption": {"bogus": 1}}, where="segment 1")
        self.assertIn("caption.bogus", str(cm.exception))

    def test_unknown_profile_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StyleError) as cm:
                style.load_profile("nope", Path(d))
        self.assertIn("nope", str(cm.exception))

    def test_identity_locked_in_clip_style(self):
        for override in ({"accent": "#FF0000"}, {"title": {"text_color": "#000000"}}, {"handle": "@x"}):
            with self.subTest(override=override):
                with self.assertRaises(StyleError) as cm:
                    style.resolve_style(brand(), None, override, where="segment 1")
                self.assertIn("locked", str(cm.exception))

    def test_identity_locked_in_profile(self):
        with self.assertRaises(StyleError) as cm:
            style.resolve_style(brand(), {"accent": "#FF0000"}, None, where="segment 1")
        self.assertIn("locked", str(cm.exception))

    def test_allow_brand_override_lifts_lock(self):
        resolved = style.resolve_style(
            brand(), None, {"accent": "#FF0000"}, where="segment 1", allow_brand_override=True
        )
        self.assertEqual(resolved["identity"]["accent"], "#FF0000")

    def test_invalid_style_in_one_segment_reports_segment_number(self):
        b = brand()
        errors = []
        for number, override in ((1, {}), (2, {}), (3, {"title": {"seconds": 99}})):
            try:
                style.resolve_style(b, None, override, where=f"segment {number}")
            except StyleError as exc:
                errors.append(str(exc))
        self.assertEqual(len(errors), 1)
        self.assertIn("segment 3", errors[0])
        self.assertIn("title.seconds", errors[0])


class BrandAndProfilesTest(unittest.TestCase):
    def test_brand_json_validates(self):
        b = brand()
        self.assertEqual(b["accent"], "#FFD400")
        self.assertIn("mix", b)

    def test_bad_hex_rejected(self):
        data = json.loads((ROOT / "brand.json").read_text())
        data["accent"] = "yellow"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "brand.json"
            p.write_text(json.dumps(data))
            with self.assertRaises(StyleError) as cm:
                style.load_brand(p)
        self.assertIn("accent", str(cm.exception))

    def test_unknown_brand_key_rejected(self):
        data = json.loads((ROOT / "brand.json").read_text())
        data["surprise"] = 1
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "brand.json"
            p.write_text(json.dumps(data))
            with self.assertRaises(StyleError) as cm:
                style.load_brand(p)
        self.assertIn("surprise", str(cm.exception))

    def test_missing_font_rejected_when_fonts_dir_given(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StyleError) as cm:
                style.load_brand(ROOT / "brand.json", fonts_dir=Path(d))
        self.assertIn("headline_font", str(cm.exception))

    def test_starter_profiles_validate(self):
        b = brand()
        profiles = style.list_profiles(ROOT / "profiles")
        self.assertEqual(set(profiles), {"explainer", "performance", "interview", "tutorial"})
        for name, profile in profiles.items():
            with self.subTest(profile=name):
                resolved = style.resolve_style(b, profile["style"], None, where=name)
                self.assertEqual(resolved["identity"]["accent"], b["accent"])

    def test_profiles_differ_as_designed(self):
        b = brand()
        profiles = style.list_profiles(ROOT / "profiles")
        perf = style.resolve_style(b, profiles["performance"]["style"], None, where="p")
        expl = style.resolve_style(b, profiles["explainer"]["style"], None, where="e")
        self.assertEqual(perf["sound"]["music"], "off")
        self.assertEqual(expl["sound"]["music"], "low")
        self.assertEqual(perf["title"]["size"], "large")


class LayoutModeTest(unittest.TestCase):
    def test_base_layout_mode_is_auto(self):
        self.assertEqual(style.resolve_style(brand(), None, None, where="s")["layout"]["mode"], "auto")

    def test_clip_can_choose_fill_or_fit(self):
        for mode in ("fill", "fit", "auto"):
            resolved = style.resolve_style(brand(), None, {"layout": {"mode": mode}}, where="segment 1")
            self.assertEqual(resolved["layout"]["mode"], mode)

    def test_unknown_layout_mode_names_the_field(self):
        with self.assertRaises(StyleError) as cm:
            style.resolve_style(brand(), None, {"layout": {"mode": "zoom"}}, where="segment 4")
        self.assertIn("segment 4", str(cm.exception))
        self.assertIn("layout.mode", str(cm.exception))

    def test_interview_profile_fills_and_others_stay_auto(self):
        b = brand()
        profiles = style.list_profiles(ROOT / "profiles")
        self.assertEqual(style.resolve_style(b, profiles["interview"]["style"], None, where="i")["layout"]["mode"], "fill")
        for name in ("explainer", "performance", "tutorial"):
            self.assertEqual(style.resolve_style(b, profiles[name]["style"], None, where=name)["layout"]["mode"], "auto")


class SchemaTest(unittest.TestCase):
    def test_schema_lists_every_bound(self):
        s = style.schema()
        for path in style.BOUNDS:
            self.assertIn(path, s["fields"])
        for locked in ("handle", "accent", "text", "outline", "headline_font", "title.text_color"):
            self.assertIn(locked, s["locked"])
        json.dumps(s)  # must be JSON serialisable

    def test_schema_describes_segment_level_fields_including_layout_ranges(self):
        seg = style.schema()["segment_fields"]
        for name in ("hook_title", "key_words", "source_music", "style", "layout_ranges"):
            self.assertIn(name, seg)
        self.assertIn("fill", seg["layout_ranges"])
        self.assertIn("fit", seg["layout_ranges"])

    def test_schema_documents_the_spec_table(self):
        f = style.schema()["fields"]
        self.assertEqual(f["caption.words_per_line"]["min"], 1)
        self.assertEqual(f["caption.words_per_line"]["max"], 6)
        self.assertEqual(f["sound.music"]["values"], ["off", "low", "normal"])
        self.assertEqual(f["title.tilt_degrees"]["min"], -5)


if __name__ == "__main__":
    unittest.main()
