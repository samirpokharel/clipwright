import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from clipwright import sounds, style
from clipwright.sounds import SoundError

ROOT = Path(__file__).resolve().parent.parent


def entry(id_, kind, source="synthesized", license_="none", file=None, **extra):
    base = {"id": id_, "kind": kind, "file": file or f"synth/{id_}.wav",
            "source": source, "license": license_, "author": None, "url": None}
    base.update(extra)
    return base


def synth_library():
    return list(sounds.SYNTH_ENTRIES)


def resolved(**sound):
    b = style.load_brand(ROOT / "brand.json")
    return style.resolve_style(b, None, {"sound": sound} if sound else None, where="segment 1")


def plan(st=None, duration=30.0, pops=(), shots=(), library=None, clip_index=0, source_music=False):
    return sounds.plan_mix(st or resolved(), duration, list(pops), list(shots),
                           library or synth_library(), clip_index, source_music)


def kinds(p, kind):
    return [e for e in p.events if e.kind == kind]


class MixPlanTest(unittest.TestCase):
    def test_whoosh_spacing_at_least_four_seconds(self):
        p = plan(shots=[1, 2, 3, 9])
        self.assertEqual([e.start for e in kinds(p, "whoosh")], [1, 9])

    def test_pops_capped_at_three(self):
        p = plan(pops=[1, 2, 3, 4, 5])
        self.assertEqual([e.start for e in kinds(p, "pop")], [1, 2, 3])

    def test_sting_at_zero_and_outro_before_end(self):
        p = plan(duration=20.0)
        self.assertEqual(kinds(p, "sting")[0].start, 0.0)
        self.assertAlmostEqual(kinds(p, "outro")[0].start, 19.4)

    def test_outro_start_never_below_zero_for_short_clip(self):
        p = plan(duration=0.4)
        self.assertGreaterEqual(kinds(p, "outro")[0].start, 0.0)

    def test_events_past_the_end_are_dropped(self):
        p = plan(duration=5.0, shots=[6.0], pops=[7.0])
        self.assertEqual(kinds(p, "whoosh") + kinds(p, "pop"), [])

    def test_off_removes_sound_and_low_adds_offset(self):
        normal = plan(resolved(pop="normal"), pops=[1])
        low = plan(resolved(pop="low"), pops=[1])
        off = plan(resolved(pop="off"), pops=[1])
        self.assertEqual(kinds(off, "pop"), [])
        mix = resolved()["mix"]
        self.assertAlmostEqual(kinds(low, "pop")[0].gain_db - kinds(normal, "pop")[0].gain_db,
                               mix["low_offset_db"])
        self.assertAlmostEqual(kinds(normal, "pop")[0].gain_db, mix["pop_db"])

    def test_outro_uses_sting_level(self):
        p = plan(resolved(sting="low"))
        mix = resolved()["mix"]
        self.assertAlmostEqual(kinds(p, "outro")[0].gain_db, mix["sting_db"] + mix["low_offset_db"])

    def test_source_music_forces_no_music_bed(self):
        self.assertIsNone(plan(source_music=True).music)

    def test_music_off_gives_no_bed(self):
        self.assertIsNone(plan(resolved(music="off")).music)

    def test_empty_library_uses_builtin_pad(self):
        music = plan().music
        self.assertTrue(music["file"].endswith("synth/pad.wav"))
        self.assertAlmostEqual(music["gain_db"], resolved()["mix"]["music_db"] + resolved()["mix"]["low_offset_db"])

    def test_real_music_track_beats_pad(self):
        track = entry("fs-1", "music", "freesound", "CC-BY", "music/fs-1.mp3", author="a", attribution="T by a")
        music = plan(library=synth_library() + [track]).music
        self.assertEqual(music["id"], "fs-1")

    def test_music_pick_is_deterministic_by_clip_index(self):
        tracks = [entry(f"m{i}", "music", "own", "own", f"music/m{i}.mp3") for i in range(3)]
        lib = synth_library() + tracks
        picks = [plan(library=lib, clip_index=i).music["id"] for i in range(4)]
        self.assertEqual(picks, ["m0", "m1", "m2", "m0"])
        self.assertEqual(plan(library=lib, clip_index=1).music["id"], "m1")


class CreditsTest(unittest.TestCase):
    def test_credits_lists_only_cc_by_used(self):
        by = entry("fs-1", "music", "freesound", "CC-BY", "music/fs-1.mp3",
                   author="alice", url="https://freesound.org/s/1/", attribution="Calm by alice (CC BY)")
        zero = entry("fs-2", "whoosh", "freesound", "CC0", "fx/fs-2.mp3", author="bob")
        unused = entry("fs-3", "pop", "freesound", "CC-BY", "fx/fs-3.mp3", author="carol", attribution="Pop by carol")
        lib = synth_library() + [by, zero, unused]
        p1 = sounds.MixPlan(events=[sounds.Event("whoosh", "fx/fs-2.mp3", 1.0, -18.0, "fs-2")],
                            music={"id": "fs-1", "file": "music/fs-1.mp3", "gain_db": -20.0})
        lines = sounds.credits([p1, p1], lib)
        self.assertEqual(len(lines), 1)
        self.assertIn("Calm by alice (CC BY)", lines[0])
        self.assertNotIn("carol", lines[0])


class LibraryTest(unittest.TestCase):
    def write_library(self, d, entries):
        (Path(d) / "library.json").write_text(json.dumps(entries))

    def test_missing_library_file_is_error_naming_entry(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_library(d, [entry("lost-track", "music", "own", "own", "music/lost.mp3")])
            with self.assertRaises(SoundError) as cm:
                sounds.load_library(Path(d))
        self.assertIn("lost-track", str(cm.exception))

    def test_disallowed_licence_fails_validation(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "music").mkdir()
            (Path(d) / "music" / "x.mp3").write_bytes(b"x")
            self.write_library(d, [entry("x", "music", "freesound", "CC-BY-NC", "music/x.mp3")])
            with self.assertRaises(SoundError) as cm:
                sounds.load_library(Path(d))
        self.assertIn("CC-BY-NC", str(cm.exception))

    def test_cc_by_requires_author(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "music").mkdir()
            (Path(d) / "music" / "x.mp3").write_bytes(b"x")
            self.write_library(d, [entry("x", "music", "freesound", "CC-BY", "music/x.mp3")])
            with self.assertRaises(SoundError) as cm:
                sounds.load_library(Path(d))
        self.assertIn("author", str(cm.exception))

    def test_empty_library_json_loads_synth_entries(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_library(d, [])
            lib = sounds.load_library(Path(d))
        self.assertEqual({e["kind"] for e in lib}, {"whoosh", "pop", "sting", "outro", "music"})


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class FfmpegTest(unittest.TestCase):
    def test_ensure_synth_writes_files_with_expected_durations(self):
        with tempfile.TemporaryDirectory() as d:
            sounds.ensure_synth(Path(d))
            expected = {"whoosh": 0.4, "pop": 0.08, "sting": 0.6, "outro": 0.6, "pad": 30.0}
            for name, seconds in expected.items():
                with wave.open(str(Path(d) / "synth" / f"{name}.wav")) as w:
                    self.assertAlmostEqual(w.getnframes() / w.getframerate(), seconds, delta=0.05)

    def test_detect_shot_changes_maps_through_keep_ranges(self):
        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "two.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2:r=25",
                 "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=25",
                 "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(video)],
                check=True)
            full = sounds.detect_shot_changes(video, [(0.0, 4.0)])
            tail = sounds.detect_shot_changes(video, [(1.0, 4.0)])
        self.assertEqual(len(full), 1)
        self.assertAlmostEqual(full[0], 2.0, delta=0.1)
        self.assertAlmostEqual(tail[0], 1.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
