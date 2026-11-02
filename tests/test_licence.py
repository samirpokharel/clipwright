import unittest

from clipwright import licence


class ClassifyTest(unittest.TestCase):
    def test_creative_commons_attribution_is_reusable(self):
        c = licence.classify("Creative Commons Attribution license (reuse allowed)")
        self.assertEqual(c["kind"], "cc-by")
        self.assertTrue(c["reuse_ok"])
        self.assertIn("CC BY", c["label"])

    def test_nothing_reported_means_standard_youtube_licence(self):
        for raw in (None, "", "   "):
            c = licence.classify(raw)
            self.assertEqual(c["kind"], "standard")
            self.assertFalse(c["reuse_ok"])

    def test_other_creative_commons_variants_are_not_assumed_safe(self):
        c = licence.classify("Creative Commons Attribution-NonCommercial license")
        self.assertEqual(c["kind"], "cc-other")
        self.assertFalse(c["reuse_ok"])

    def test_unrecognised_text_is_treated_as_standard(self):
        self.assertEqual(licence.classify("Some custom licence")["kind"], "standard")

    def test_local_file_is_its_own_kind(self):
        c = licence.classify(None, local=True)
        self.assertEqual(c["kind"], "local")
        self.assertFalse(c["reuse_ok"])


class AttributionTest(unittest.TestCase):
    def test_cc_by_attribution_names_work_creator_link_and_licence(self):
        line = licence.attribution("Big Buck Bunny", "Blender", "https://www.youtube.com/watch?v=aqz-KE-bpKQ", "cc-by")
        for part in ("Big Buck Bunny", "Blender", "https://www.youtube.com/watch?v=aqz-KE-bpKQ", "CC BY"):
            self.assertIn(part, line)

    def test_no_attribution_line_for_other_licences(self):
        for kind in ("standard", "cc-other", "local"):
            self.assertIsNone(licence.attribution("T", "C", "u", kind))

    def test_missing_channel_still_gives_a_line(self):
        line = licence.attribution("T", None, "https://u", "cc-by")
        self.assertIn("https://u", line)
        self.assertNotIn("None", line)


class WarningTest(unittest.TestCase):
    def test_standard_licence_warns_about_permission(self):
        w = licence.warning("standard")
        self.assertIn("permission", w)

    def test_cc_by_has_no_warning(self):
        self.assertIsNone(licence.warning("cc-by"))

    def test_other_cc_says_check_the_terms(self):
        self.assertIn("terms", licence.warning("cc-other"))

    def test_local_file_reminds_you_you_are_responsible(self):
        self.assertIn("responsible", licence.warning("local"))


if __name__ == "__main__":
    unittest.main()
