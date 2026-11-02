import unittest

from clipwright import layout
from clipwright.layout import Run
from clipwright.style import StyleError


class ParseTimeTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(layout.parse_time("05:08"), 308.0)
        self.assertEqual(layout.parse_time("1:02:03"), 3723.0)
        self.assertEqual(layout.parse_time("12.5"), 12.5)
        self.assertEqual(layout.parse_time(308), 308.0)

    def test_garbage_raises(self):
        for bad in ("soon", "1:2:3:4", "", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    layout.parse_time(bad)


class ParseRangesTest(unittest.TestCase):
    def parse(self, raw, start=308.0, end=334.0, where="segment 3"):
        return layout.parse_ranges(raw, start, end, where)

    def test_none_and_empty_mean_no_ranges(self):
        self.assertEqual(self.parse(None), [])
        self.assertEqual(self.parse([]), [])

    def test_valid_range_in_source_seconds(self):
        self.assertEqual(self.parse([{"from": "05:10", "to": "05:20", "layout": "fit"}]), [(310.0, 320.0, "fit")])

    def test_ranges_are_sorted(self):
        raw = [{"from": "05:20", "to": "05:30", "layout": "fit"}, {"from": "05:10", "to": "05:15", "layout": "fill"}]
        self.assertEqual([r[2] for r in self.parse(raw)], ["fill", "fit"])

    def test_error_names_segment_and_index(self):
        with self.assertRaises(StyleError) as cm:
            self.parse([{"from": "05:10", "to": "05:20", "layout": "zoom"}])
        self.assertIn("segment 3", str(cm.exception))
        self.assertIn("layout_ranges[0]", str(cm.exception))

    def test_outside_the_segment_is_rejected(self):
        with self.assertRaises(StyleError) as cm:
            self.parse([{"from": "05:10", "to": "06:20", "layout": "fit"}])
        self.assertIn("outside", str(cm.exception))

    def test_overlap_is_rejected(self):
        raw = [{"from": "05:10", "to": "05:20", "layout": "fit"}, {"from": "05:15", "to": "05:25", "layout": "fill"}]
        with self.assertRaises(StyleError) as cm:
            self.parse(raw)
        self.assertIn("overlap", str(cm.exception))

    def test_from_must_be_before_to(self):
        with self.assertRaises(StyleError):
            self.parse([{"from": "05:20", "to": "05:20", "layout": "fit"}])

    def test_missing_keys_and_wrong_shapes_are_rejected(self):
        for bad in ({"from": "05:10", "layout": "fit"}, "fill", [["05:10", "05:20"]], {"from": "x", "to": "y", "layout": "fit"}):
            with self.subTest(bad=bad):
                with self.assertRaises(StyleError):
                    self.parse(bad if isinstance(bad, list) and bad and isinstance(bad[0], list) else [bad])
        with self.assertRaises(StyleError):
            self.parse("not a list")


class PlanRunsTest(unittest.TestCase):
    def test_auto_without_ranges_needs_no_layout_render(self):
        self.assertFalse(layout.needs_layout("auto", []))
        self.assertTrue(layout.needs_layout("fill", []))
        self.assertTrue(layout.needs_layout("auto", [(310.0, 320.0, "fill")]))

    def test_whole_clip_fill(self):
        self.assertEqual(layout.plan_runs("fill", [], 308.0, 334.0), [Run(0.0, 26.0, "fill")])

    def test_auto_with_ranges_defaults_uncovered_time_to_fit(self):
        runs = layout.plan_runs("auto", [(310.0, 320.0, "fill")], 308.0, 334.0)
        self.assertEqual(runs, [Run(0.0, 2.0, "fit"), Run(2.0, 12.0, "fill"), Run(12.0, 26.0, "fit")])

    def test_fill_with_a_fit_range_in_the_middle(self):
        runs = layout.plan_runs("fill", [(312.0, 318.0, "fit")], 308.0, 334.0)
        self.assertEqual([r.kind for r in runs], ["fill", "fit", "fill"])
        self.assertEqual((runs[1].start, runs[1].end), (4.0, 10.0))

    def test_range_is_clipped_to_the_rendered_clip(self):
        # the rendered clip starts at 308.5 (sentence snap), the range starts at 308.0
        runs = layout.plan_runs("fit", [(308.0, 312.0, "fill")], 308.5, 334.0)
        self.assertEqual(runs[0], Run(0.0, 3.5, "fill"))

    def test_adjacent_runs_of_the_same_kind_merge(self):
        runs = layout.plan_runs("fit", [(310.0, 315.0, "fill"), (315.0, 320.0, "fill")], 308.0, 334.0)
        self.assertEqual([r.kind for r in runs], ["fit", "fill", "fit"])

    def test_runs_cover_the_whole_clip_without_gaps(self):
        runs = layout.plan_runs("fill", [(311.0, 313.0, "fit"), (320.0, 322.5, "fit")], 308.0, 334.0)
        self.assertEqual(runs[0].start, 0.0)
        self.assertAlmostEqual(runs[-1].end, 26.0)
        for a, b in zip(runs, runs[1:]):
            self.assertEqual(a.end, b.start)


class CropTest(unittest.TestCase):
    def test_crop_width_is_even_and_nine_by_sixteen(self):
        self.assertEqual(layout.crop_width(1080), 606)
        self.assertEqual(layout.crop_width(720), 404)

    def test_median_of_face_centres_in_the_run(self):
        centres = [(1.0, 900.0), (2.0, 1000.0), (3.0, 1100.0), (9.0, 100.0)]
        self.assertEqual(layout.crop_x(centres, 0.0, 5.0, 1920, 606), 696)  # 1000 - 303, made even

    def test_clamped_to_the_frame(self):
        self.assertEqual(layout.crop_x([(1.0, 50.0)], 0.0, 5.0, 1920, 606), 0)
        self.assertEqual(layout.crop_x([(1.0, 1900.0)], 0.0, 5.0, 1920, 606), 1920 - 606)

    def test_no_face_in_the_run_uses_the_fallback_then_the_frame_centre(self):
        self.assertEqual(layout.crop_x([], 0.0, 5.0, 1920, 606, fallback=400), 400)
        self.assertEqual(layout.crop_x([], 0.0, 5.0, 1920, 606), 656)

    def test_x_is_always_even(self):
        for cx in (801.0, 1001.0, 1234.0):
            self.assertEqual(layout.crop_x([(1.0, cx)], 0.0, 5.0, 1920, 606) % 2, 0)


class FilterTest(unittest.TestCase):
    def test_fill_and_fit_runs_become_one_concat(self):
        runs = [Run(0.0, 5.0, "fill"), Run(5.0, 12.5, "fit")]
        graph = layout.build_filter(runs, 1920, 1080, [656, None])
        self.assertIn("trim=start=0:end=5", graph)
        self.assertIn("crop=606:1080:656:0", graph)
        self.assertIn("trim=start=5:end=12.5", graph)
        self.assertIn("gblur", graph)
        self.assertIn("overlay=(W-w)/2:(H-h)/2", graph)
        self.assertIn("concat=n=2:v=1:a=0[vout]", graph)

    def test_single_run_still_ends_in_vout(self):
        graph = layout.build_filter([Run(0.0, 9.0, "fill")], 1920, 1080, [656])
        self.assertIn("concat=n=1:v=1:a=0[vout]", graph)
        self.assertIn("scale=1080:1920", graph)


    def test_portrait_source_fill_uses_a_cover_scale_not_an_impossible_crop(self):
        graph = layout.build_filter([Run(0.0, 4.0, "fill")], 1080, 1920, [0])
        self.assertRegex(graph, r"force_original_aspect_ratio=increase.*,crop=1080:1920")
        self.assertNotIn("crop=606", graph)


class FramesArgsTest(unittest.TestCase):
    def test_contact_sheet_samples_every_n_seconds_with_source_timestamps(self):
        args = layout.frames_args("/s.mp4", 308.0, 26.0, 3.0, "/out.png", font="/f.ttf")
        text = " ".join(args)
        self.assertIn("-ss 308.0", text)
        self.assertIn("-t 26.0", text)
        self.assertIn("fps=1/3", text)
        self.assertIn("tile=5x2", text)  # 9 frames at 5 per row
        self.assertIn("pts\\:hms\\:308", text)
        self.assertEqual(args[-1], "/out.png")


if __name__ == "__main__":
    unittest.main()
