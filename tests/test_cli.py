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

    def test_check_command_takes_several_urls(self):
        a = pipeline.build_parser().parse_args(["check", "https://y/1", "https://y/2"])
        self.assertEqual((a.cmd, a.urls), ("check", ["https://y/1", "https://y/2"]))

    def test_check_needs_at_least_one_url(self):
        with self.assertRaises(SystemExit):
            pipeline.build_parser().parse_args(["check"])

    def test_fetch_domain_flag(self):
        p = pipeline.build_parser()
        self.assertEqual(p.parse_args(["fetch", "https://y/1", "--domain", "health"]).domain, "health")
        self.assertIsNone(p.parse_args(["fetch", "https://y/1"]).domain)

    def test_domains_command_parses(self):
        self.assertEqual(pipeline.build_parser().parse_args(["domains"]).cmd, "domains")

    def test_sources_command_parses(self):
        a = pipeline.build_parser().parse_args(["sources", "health", "--limit", "5", "--query", "x", "--query", "y"])
        self.assertEqual((a.cmd, a.domain, a.limit, a.query), ("sources", "health", 5, ["x", "y"]))
        d = pipeline.build_parser().parse_args(["sources", "tech"])
        self.assertEqual((d.limit, d.query), (24, []))

    def test_sources_needs_a_domain(self):
        with self.assertRaises(SystemExit):
            pipeline.build_parser().parse_args(["sources"])

    def test_package_command_parses(self):
        a = pipeline.build_parser().parse_args(["package", "job1", "--segments", "s.json"])
        self.assertEqual((a.cmd, a.job, a.segments), ("package", "job1", "s.json"))
        self.assertIsNone(pipeline.build_parser().parse_args(["package", "job1"]).segments)

    def test_frames_command_parses(self):
        p = pipeline.build_parser()
        a = p.parse_args(["frames", "job1", "--segment", "2", "--every", "2"])
        self.assertEqual((a.cmd, a.job, a.segment, a.every), ("frames", "job1", 2, 2.0))
        b = p.parse_args(["frames", "job1", "--from", "05:08", "--to", "05:34"])
        self.assertEqual((b.start, b.end, b.every), ("05:08", "05:34", 3.0))


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

    def test_layout_ranges_are_parsed_into_the_resolved_style(self):
        ranges = [{"from": "00:20", "to": "00:30", "layout": "fit"}]
        styles = self.resolve([seg(layout_ranges=ranges, style={"layout": {"mode": "fill"}})])
        self.assertEqual(styles[0]["layout"]["mode"], "fill")
        self.assertEqual(styles[0]["layout"]["ranges"], [(20.0, 30.0, "fit")])

    def test_segment_without_layout_ranges_gets_an_empty_list(self):
        self.assertEqual(self.resolve([seg()])[0]["layout"]["ranges"], [])

    def test_bad_layout_range_is_reported_with_the_segment_number_alongside_style_errors(self):
        segments = [seg(), seg(layout_ranges=[{"from": "00:20", "to": "09:00", "layout": "fit"}]),
                    seg(style={"title": {"seconds": 99}})]
        with self.assertRaises(StyleError) as cm:
            self.resolve(segments)
        message = str(cm.exception)
        self.assertIn("segment 2: layout_ranges[0]", message)
        self.assertIn("segment 3", message)

    def test_unparseable_segment_time_is_a_clear_error(self):
        with self.assertRaises(StyleError) as cm:
            self.resolve([seg(start_time="soon", layout_ranges=[{"from": "00:20", "to": "00:30", "layout": "fit"}])])
        self.assertIn("segment 1", str(cm.exception))

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

    def test_safe_job_id_replaces_characters_that_break_ffmpeg_filters(self):
        self.assertEqual(pipeline.safe_job_id("Rick's talk, part [1];x:y"), "Rick_s_talk_part_1_x_y")

    def test_safe_job_id_keeps_youtube_ids(self):
        for vid in ("aMoVyJ9_M24", "nEaJ-Md_djM"):
            self.assertEqual(pipeline.safe_job_id(vid), vid)

    def test_safe_job_id_is_never_empty(self):
        self.assertEqual(pipeline.safe_job_id("'';;"), "job")

    def test_describe_plan_summarises_sounds(self):
        from clipwright import sounds
        ev = sounds.Event
        plan = sounds.MixPlan(
            events=[ev("sting", "a", 0.0, -16.0), ev("whoosh", "b", 2.0, -18.0), ev("whoosh", "b", 9.0, -18.0),
                    ev("pop", "c", 3.0, -22.0), ev("outro", "d", 20.0, -16.0)],
            music={"id": "synth-pad", "file": "x", "gain_db": -26.0})
        self.assertEqual(pipeline.describe_plan(plan),
                         "music synth-pad -26.0 dB, 2 whooshes, 1 pop, sting+outro")

    def test_describe_plan_with_nothing(self):
        from clipwright import sounds
        self.assertEqual(pipeline.describe_plan(sounds.MixPlan()), "no music, 0 whooshes, 0 pops, no sting")

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


class Pass2LoopTest(unittest.TestCase):
    """The pass 2 loop: failure isolation, early validation, manifest and credits always written."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.segments = [seg(start_time="00:00", end_time="00:10", hook_title="One"),
                         seg(start_time="00:20", end_time="00:30", hook_title="Two"),
                         seg(start_time="00:40", end_time="00:50", hook_title="Three")]
        self.cache = {}
        for i, s in enumerate(self.segments, 1):
            p1 = self.root / f"{i:02d}.mp4"
            p1.write_bytes(b"pass1")
            self.cache[str(i)] = {"pass1": str(p1), "source": "s.mp4", "keep_ranges": [[0, 10]], "duration": 10.0,
                                  "start_time": s["start_time"], "end_time": s["end_time"]}
        self.library = [{"id": "fs-1", "kind": "music", "file": "music/fs-1.mp3", "source": "freesound",
                         "license": "CC-BY", "author": "alice", "attribution": "Calm by alice (CC BY)", "url": None}]

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, fail_on=(), exc=ValueError("boom"), credit_on=()):
        from clipwright import sounds
        calls = []

        def compose_one(i, segment, st, entry, library, part, workdir):
            calls.append(i)
            if i in fail_on:
                raise exc
            part.write_bytes(f"clip{i}".encode())
            music = {"id": "fs-1", "file": "music/fs-1.mp3", "gain_db": -26.0} if i in credit_on else None
            return {"plan": sounds.MixPlan(music=music)}

        compose_one.calls = calls
        return compose_one

    def run_loop(self, compose_one, indexes=(1, 2, 3), previous=(), extra_credits=()):
        return pipeline.compose_all(list(indexes), self.segments, [None] * 3, self.cache, self.library,
                                    self.out, self.work, compose_one, list(previous), log=lambda *a, **k: None,
                                    extra_credits=list(extra_credits))

    def manifest(self):
        return json.loads((self.out / "manifest.json").read_text())

    def test_one_failing_clip_does_not_stop_the_others(self):
        fresh, failed = self.run_loop(self.stub(fail_on={2}, exc=ValueError("bad caption data")))
        self.assertEqual(failed, [2])
        self.assertEqual([Path(m["file"]).name[:2] for m in self.manifest()], ["01", "03"])
        self.assertTrue((self.out / "01_clip_0000-0010.mp4").exists())
        self.assertTrue((self.out / "03_clip_0040-0050.mp4").exists())
        self.assertTrue((self.out / "credits.txt").exists())
        self.assertEqual(list(self.out.glob("*.part.mp4")), [])  # no half-written files left behind

    def test_failure_keeps_the_previous_render_of_that_segment(self):
        old = self.out / "02_clip_0020-0030.mp4"
        old.write_bytes(b"previous good render")
        previous = [{"file": str(old), "hook_title": "Two", "duration": 10.0, "credits": []}]
        _, failed = self.run_loop(self.stub(fail_on={2}), indexes=(2,), previous=previous)
        self.assertEqual(failed, [2])
        self.assertEqual(old.read_bytes(), b"previous good render")
        self.assertEqual([Path(m["file"]).name for m in self.manifest()], [old.name])

    def test_manifest_is_written_even_when_the_run_is_interrupted(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_loop(self.stub(fail_on={2}, exc=KeyboardInterrupt()))
        self.assertEqual([Path(m["file"]).name[:2] for m in self.manifest()], ["01"])

    def test_entries_for_other_segments_are_kept(self):
        kept = self.out / "03_clip_0040-0050.mp4"
        kept.write_bytes(b"x")
        previous = [{"file": str(kept), "hook_title": "Three", "duration": 10.0, "credits": ["Old credit"]}]
        self.run_loop(self.stub(), indexes=(1,), previous=previous)
        self.assertEqual([Path(m["file"]).name[:2] for m in self.manifest()], ["01", "03"])
        self.assertIn("Old credit", (self.out / "credits.txt").read_text())

    def test_credits_list_cc_by_sounds_used(self):
        self.run_loop(self.stub(credit_on={1}))
        self.assertIn("Calm by alice (CC BY)", (self.out / "credits.txt").read_text())

    def test_source_attribution_is_written_even_with_no_sound_credits(self):
        line = '"Big Buck Bunny" by Blender, https://u, licensed under Creative Commons Attribution (CC BY)'
        self.run_loop(self.stub(), extra_credits=[line])
        self.assertEqual((self.out / "credits.txt").read_text(), line + "\n")

    def test_source_attribution_comes_first_and_survives_a_partial_run(self):
        line = '"Video" by Creator, https://u, licensed under Creative Commons Attribution (CC BY)'
        self.run_loop(self.stub(credit_on={1}), indexes=(1,), extra_credits=[line])
        lines = (self.out / "credits.txt").read_text().splitlines()
        self.assertEqual(lines[0], line)
        self.assertIn("Calm by alice (CC BY)", lines)

    def test_credits_file_empty_when_nothing_to_credit(self):
        self.run_loop(self.stub())
        self.assertEqual((self.out / "credits.txt").read_text(), "")


class CacheEntryTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        p1 = Path(self.tmp.name) / "01.mp4"
        p1.write_bytes(b"x")
        self.seg = seg(start_time="00:00", end_time="00:10", hook_title="One", key_words=["a b"])
        self.cache = {"1": {"pass1": str(p1), "start_time": "00:00", "end_time": "00:10", "duration": 10.0}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_entry_for_adds_title_and_key_words_from_the_segment(self):
        entry = pipeline.entry_for(self.cache, 1, self.seg)
        self.assertEqual(entry["hook_title"], "One")
        self.assertEqual(entry["key_words"], ["a b"])

    def test_missing_cache_entry_names_the_segment(self):
        with self.assertRaises(pipeline.PipelineError) as cm:
            pipeline.entry_for({}, 1, self.seg)
        self.assertIn("segment 1", str(cm.exception))
        self.assertIn("--recompose", str(cm.exception))

    def test_changed_times_name_the_segment(self):
        with self.assertRaises(pipeline.PipelineError) as cm:
            pipeline.entry_for(self.cache, 1, dict(self.seg, end_time="00:20"))
        self.assertIn("changed", str(cm.exception))

    def layout_style(self, mode="auto", ranges=()):
        return {"layout": {"mode": mode, "ranges": list(ranges)}}

    def test_signature_describes_mode_and_ranges(self):
        sig = pipeline.layout_signature(self.layout_style("fill", [(310.0, 320.0, "fit")]))
        self.assertEqual(sig, {"mode": "fill", "ranges": [[310.0, 320.0, "fit"]]})

    def test_changed_layout_requires_a_new_pass_1(self):
        self.cache["1"]["layout"] = pipeline.layout_signature(self.layout_style("auto"))
        with self.assertRaises(pipeline.PipelineError) as cm:
            pipeline.entry_for(self.cache, 1, self.seg, self.layout_style("fill"))
        self.assertIn("layout changed", str(cm.exception))
        self.assertIn("segment 1", str(cm.exception))

    def test_unchanged_layout_is_accepted(self):
        self.cache["1"]["layout"] = pipeline.layout_signature(self.layout_style("fill", [(1.0, 2.0, "fit")]))
        entry = pipeline.entry_for(self.cache, 1, self.seg, self.layout_style("fill", [(1.0, 2.0, "fit")]))
        self.assertEqual(entry["hook_title"], "One")

    def test_old_cache_entry_without_layout_counts_as_auto(self):
        pipeline.entry_for(self.cache, 1, self.seg, self.layout_style("auto"))  # no error
        with self.assertRaises(pipeline.PipelineError):
            pipeline.entry_for(self.cache, 1, self.seg, self.layout_style("fit"))

    def test_check_entries_reports_every_problem_before_any_render(self):
        segments = [self.seg, seg(start_time="00:20", end_time="00:30"), dict(self.seg, end_time="00:99")]
        cache = {"1": self.cache["1"], "3": self.cache["1"]}
        with self.assertRaises(pipeline.PipelineError) as cm:
            pipeline.check_entries(cache, [1, 2, 3], segments)
        message = str(cm.exception)
        self.assertIn("segment 2", message)
        self.assertIn("segment 3", message)
        self.assertNotIn("segment 1:", message)
