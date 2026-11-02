import re
import unittest
from pathlib import Path

from clipwright import compose, style

ROOT = Path(__file__).resolve().parent.parent

# title_ass output captured before title_window was extracted; the refactor must not change it
TITLE_ASS_BEFORE = (
    '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
    '[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,'
    'Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
    'Style: Title,Anton,72,&H00111111,&H000000FF,&H0000D4FF,&H0000D4FF,0,0,0,0,100,100,0,0,3,12,0,7,60,60,96,1\n'
    'Style: Handle,Anton,34,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,1,40,40,40,1\n\n'
    '[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
    'Dialogue: 1,0:00:00.10,0:00:04.00,Title,,0,0,0,,{\\an7\\pos(60,96)\\frz-2\\fad(150,250)}WHY FOUNDERS QUIT TOO EARLY\n'
    'Dialogue: 2,0:00:00.00,0:00:20.00,Handle,,0,0,0,,{\\an1\\pos(40,1613)\\alpha&H30&}@yourchannel\n'
)


def resolved(override=None):
    return style.resolve_style(style.load_brand(ROOT / "brand.json"), None, override, where="segment 1")


def events(ass, name):
    return [line for line in ass.splitlines() if line.startswith("Dialogue") and f",{name}," in line]


class TitleWindowTest(unittest.TestCase):
    def test_title_window_values(self):
        title = resolved()["title"]  # seconds = 4
        self.assertEqual(compose.title_window(title, 0.5), (0.0, 0.5))
        self.assertEqual(compose.title_window(title, 20.0), (0.1, 4.0))
        self.assertEqual(compose.title_window(title, 3.0), (0.1, 2.7))

    def test_title_ass_unchanged(self):
        self.assertEqual(compose.title_ass("Why founders quit too early", resolved(), 20.0, "Anton"),
                         TITLE_ASS_BEFORE)


class OverlayTest(unittest.TestCase):
    def test_empty_overlays_none(self):
        self.assertIsNone(compose.overlay_ass(resolved(), 20.0, "Anton", {}))

    def test_speaker_event(self):
        ass = compose.overlay_ass(resolved(), 20.0, "Anton", {"speaker": "Dr Rao, cardiologist"})
        (line,) = events(ass, "Speaker")
        self.assertIn("0:00:00.00,0:00:06.00", line)
        self.assertIn("\\an7\\pos(60,29)", line)
        self.assertTrue(line.endswith("Dr Rao, cardiologist"))

    def test_speaker_clamped_to_short_clip(self):
        ass = compose.overlay_ass(resolved(), 4.0, "Anton", {"speaker": "A, b"})
        self.assertIn("0:00:00.00,0:00:04.00", events(ass, "Speaker")[0])

    def test_disclaimer_event(self):
        ass = compose.overlay_ass(resolved(), 20.0, "Anton", {"disclaimer": "General information, not medical advice."})
        (line,) = events(ass, "Disclaimer")
        self.assertIn("0:00:00.00,0:00:20.00", line)
        self.assertIn("\\an3\\pos(1040,1613)", line)

    def test_commentary_starts_when_title_ends(self):
        ass = compose.overlay_ass(resolved(), 20.0, "Anton", {"commentary": "Context from me"})
        (line,) = events(ass, "Commentary")
        self.assertIn("0:00:04.00,0:00:09.00", line)
        self.assertIn("\\an7\\pos(60,96)", line)  # the title slot: top 0.05 of 1920

    def test_commentary_starts_early_when_title_disabled(self):
        ass = compose.overlay_ass(resolved({"title": {"enabled": False}}), 20.0, "Anton", {"commentary": "Context"})
        self.assertIn("0:00:00.10,", events(ass, "Commentary")[0])

    def test_commentary_dropped_when_no_room(self):
        self.assertIsNone(compose.overlay_ass(resolved(), 4.5, "Anton", {"commentary": "too late"}))
        ass = compose.overlay_ass(resolved(), 4.5, "Anton", {"commentary": "too late", "disclaimer": "d"})
        self.assertEqual(events(ass, "Commentary"), [])
        self.assertEqual(len(events(ass, "Disclaimer")), 1)

    def test_commentary_wraps_to_at_most_three_lines(self):
        text = " ".join(["context"] * 20)  # 159 characters, longer than any allowed commentary
        ass = compose.overlay_ass(resolved(), 20.0, "Anton", {"commentary": text[:140]})
        self.assertLessEqual(events(ass, "Commentary")[0].count("\\N") + 1, 3)

    def test_special_characters_escaped(self):
        ass = compose.overlay_ass(resolved(), 20.0, "Anton", {"speaker": "A {b} \\ c"})
        text = events(ass, "Speaker")[0].split("}", 1)[1]
        self.assertNotIn("{", text)
        self.assertNotIn("\\", text)

    def test_non_ascii_kept(self):
        ass = compose.overlay_ass(resolved(), 20.0, "Anton", {"speaker": "Rāma ko kahānī, राम"})
        self.assertIn("Rāma ko kahānī, राम", ass)

    def test_all_three_together_do_not_share_a_slot(self):
        ass = compose.overlay_ass(resolved(), 20.0, "Anton",
                                  {"speaker": "A, b", "commentary": "c", "disclaimer": "d"})
        starts = {n: re.search(r"Dialogue: \d,([^,]+),", events(ass, n)[0]).group(1)
                  for n in ("Speaker", "Commentary", "Disclaimer")}
        self.assertEqual(starts["Speaker"], "0:00:00.00")
        self.assertEqual(starts["Commentary"], "0:00:04.00")


if __name__ == "__main__":
    unittest.main()
