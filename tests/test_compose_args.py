import unittest
from pathlib import Path

from clipwright import compose, sounds, style

ROOT = Path(__file__).resolve().parent.parent
BASE_TEMPLATE = {"font_family": "x", "font_size": 32, "font_color": "#FFFFFF", "highlight_color": "#FFE000",
                 "emphasis_color": "#FFE000", "stroke_color": "#000000", "stroke_width": 3,
                 "background": False, "background_color": None, "word_box": False, "word_box_color": None,
                 "animation": "karaoke", "word_pop": True, "emoji": True, "uppercase": False,
                 "shadow": True, "glow": False, "max_words_per_line": 4, "position_y": 0.8}


def resolved(override=None, profile=None):
    brand = style.load_brand(ROOT / "brand.json")
    return style.resolve_style(brand, profile, override, where="segment 1")


def args_for(st=None, mix=None, duration=10.0, has_audio=True, ass=("c.ass", "t.ass")):
    st = st or resolved()
    mix = mix if mix is not None else sounds.MixPlan()
    return compose.build_ffmpeg_args(
        Path("p1.mp4"), Path("out.mp4"), [Path(a) for a in ass], st, mix, duration, has_audio,
        fonts_dir="/app/fonts", sounds_dir=Path("/work/sounds"))


class CaptionTemplateTest(unittest.TestCase):
    def test_caption_template_uses_accent_and_text(self):
        st = resolved({"caption": {"words_per_line": 2, "uppercase": False, "outline_px": 5}})
        tpl = compose.caption_template(st, BASE_TEMPLATE)
        self.assertEqual(tpl["font_family"], "Anton-Regular")
        self.assertEqual(tpl["highlight_color"], "#FFD400")
        self.assertEqual(tpl["emphasis_color"], "#FFD400")
        self.assertEqual(tpl["font_color"], "#FFFFFF")
        self.assertEqual(tpl["stroke_color"], "#000000")
        self.assertEqual(tpl["stroke_width"], 5)
        self.assertEqual(tpl["max_words_per_line"], 2)
        self.assertFalse(tpl["uppercase"])
        self.assertFalse(tpl["emoji"])
        self.assertFalse(tpl["word_box"])
        self.assertEqual(tpl["shadow"], BASE_TEMPLATE["shadow"])  # untouched keys carry over


class AssTest(unittest.TestCase):
    def test_ass_colour_is_bgr(self):
        self.assertEqual(compose.ass_color("#FFD400"), "&H0000D4FF")

    def test_ass_time_format(self):
        self.assertEqual(compose.ass_time(1.7), "0:00:01.70")
        self.assertEqual(compose.ass_time(65.25), "0:01:05.25")

    def test_title_ass_box_uses_accent_and_tilt(self):
        ass = compose.title_ass("Why System of a Down needed John Dolmayan", resolved(), 30.0, "Anton")
        self.assertIn("&H0000D4FF", ass)          # accent as the box colour
        self.assertIn("\\frz-2", ass)             # tilt from title.tilt_degrees
        self.assertIn("Style: Title,Anton,", ass)
        self.assertRegex(ass, r"Style: Title,[^\n]*,3,")  # BorderStyle 3 = opaque box

    def test_title_text_colour_is_dark(self):
        ass = compose.title_ass("Hello world", resolved(), 30.0, "Anton")
        self.assertIn(compose.ass_color("#111111"), ass.split("Style: Title,")[1].split("\n")[0])

    def test_title_uppercases_and_limits_lines(self):
        text = "one two three four five six seven eight nine ten eleven twelve"
        ass = compose.title_ass(text, resolved({"title": {"max_lines": 2}}), 30.0, "Anton")
        line = [l for l in ass.splitlines() if l.startswith("Dialogue") and ",Title," in l][0]
        self.assertLessEqual(line.count("\\N"), 1)
        self.assertIn("ONE", line)

    def test_title_shortened_for_short_clip(self):
        # RF5: a 2 s clip cannot hold a 4 s title
        ass = compose.title_ass("Short clip", resolved(), 2.0, "Anton")
        line = [l for l in ass.splitlines() if ",Title," in l and l.startswith("Dialogue")][0]
        end = line.split(",")[2]
        self.assertEqual(end, "0:00:01.70")

    def test_title_uses_configured_seconds(self):
        ass = compose.title_ass("Normal clip", resolved({"title": {"seconds": 3}}), 30.0, "Anton")
        line = [l for l in ass.splitlines() if ",Title," in l and l.startswith("Dialogue")][0]
        self.assertEqual(line.split(",")[2], "0:00:03.00")

    def test_title_disabled_has_no_title_event(self):
        ass = compose.title_ass("Hidden", resolved({"title": {"enabled": False}}), 30.0, "Anton")
        self.assertNotIn(",Title,", "\n".join(l for l in ass.splitlines() if l.startswith("Dialogue")))

    def test_handle_sits_above_the_bottom_safe_zone(self):
        ass = compose.title_ass("T", resolved(), 30.0, "Anton")
        self.assertIn("@yourchannel", ass)
        self.assertIn("\\pos(40,1613)", ass)  # 0.84 of 1920, outside the bottom 15%

    def test_ass_text_is_escaped(self):
        ass = compose.title_ass("Braces {here} and \\slash", resolved(), 30.0, "Anton")
        self.assertNotIn("{here}", ass)


class FfmpegArgsTest(unittest.TestCase):
    def joined(self, **kw):
        return " ".join(args_for(**kw))

    def test_progress_bar_uses_overlay_expression_not_drawbox_t(self):
        text = self.joined()
        self.assertIn("overlay=x='-w+w*t/10.0'", text)
        self.assertNotIn("w='iw*t", text)
        self.assertIn("color=c=0xFFD400", text)

    def test_progress_bar_disabled_has_no_bar(self):
        text = self.joined(st=resolved({"progress_bar": {"enabled": False}}))
        self.assertNotIn("overlay=", text)
        self.assertNotIn("color=c=0xFFD400", text)

    def test_subtitles_filters_use_fontsdir(self):
        text = self.joined()
        self.assertEqual(text.count("subtitles="), 2)
        self.assertIn("fontsdir=/app/fonts", text)

    def test_audio_graph_has_sidechain_and_loudnorm_when_music(self):
        mix = sounds.MixPlan(music={"id": "synth-pad", "file": "synth/pad.wav", "gain_db": -26.0})
        text = self.joined(mix=mix)
        self.assertIn("sidechaincompress", text)
        self.assertIn("loudnorm=I=-14:TP=-1.5", text)
        self.assertIn("-stream_loop -1", text)
        self.assertIn("volume=-26.0dB", text)

    def test_no_music_no_sidechain(self):
        text = self.joined()
        self.assertNotIn("sidechaincompress", text)
        self.assertIn("loudnorm=I=-14:TP=-1.5", text)

    def test_no_audio_track_uses_anullsrc(self):
        text = self.joined(has_audio=False)
        self.assertIn("anullsrc", text)
        self.assertNotIn("[0:a]", text)

    def test_events_are_delayed_and_gained(self):
        mix = sounds.MixPlan(events=[sounds.Event("whoosh", "synth/whoosh.wav", 2.5, -18.0, "synth-whoosh")])
        text = self.joined(mix=mix)
        self.assertIn("adelay=2500|2500", text)
        self.assertIn("volume=-18.0dB", text)
        self.assertIn("/work/sounds/synth/whoosh.wav", text)
        self.assertIn("amix=inputs=2:normalize=0", text)

    def test_output_is_h264_aac_1080_wide_and_trimmed(self):
        text = self.joined(duration=12.5)
        for part in ("-c:v libx264", "-pix_fmt yuv420p", "-c:a aac", "-t 12.5", "-map [vout]", "-map [aout]"):
            self.assertIn(part, text)
        self.assertEqual(args_for()[-1], "out.mp4")


if __name__ == "__main__":
    unittest.main()
