import unittest
from pathlib import Path

from clipwright import domains, gate

ROOT = Path(__file__).resolve().parent.parent
HEALTH = domains.load_pack("health", ROOT / "domains")
TECH = domains.load_pack("tech", ROOT / "domains")
MYTH = domains.load_pack("mythology", ROOT / "domains")


def health_segment(**over):
    seg = {"start_time": "00:12", "end_time": "00:58", "text": "x", "hook_title": "T",
           "verification": {"speaker": "Dr Rao", "credential": "cardiologist",
                            "context_excerpt": "the doctor adds this applies only to adults",
                            "context_checked": True, "framing_time": "00:15", "risk_flags": []}}
    seg.update(over)
    return seg


def with_ver(seg, **over):
    ver = dict(seg["verification"])
    ver.update(over)
    return dict(seg, verification=ver)


def tech_segment(**over):
    seg = {"start_time": "01:00", "end_time": "01:18",
           "verification": {"speaker": "Jane Doe", "claims_checked": True}}
    seg.update(over)
    return seg


def myth_segment(**over):
    seg = {"start_time": "02:00", "end_time": "02:40",
           "verification": {"source_text": "Ramayana, Yuddha Kanda", "variant_note": "no known variants",
                            "verses_checked": True, "respect_check": True}}
    seg.update(over)
    return seg


class CheckSegmentTest(unittest.TestCase):
    def test_complete_health_segment_passes(self):
        self.assertEqual(gate.check_segment(HEALTH, health_segment(), 1), [])

    def test_missing_verification_blocked(self):
        seg = health_segment()
        del seg["verification"]
        problems = gate.check_segment(HEALTH, seg, 2)
        self.assertEqual(len(problems), 1)
        self.assertIn("segment 2", problems[0])
        self.assertIn("verification", problems[0])

    def test_verification_wrong_type_blocked(self):
        for bad in (None, "ok", [], 5):
            with self.subTest(bad=bad):
                problems = gate.check_segment(HEALTH, health_segment(verification=bad), 2)
                self.assertTrue(problems)
                self.assertIn("segment 2", problems[0])
                self.assertIn("verification", problems[0])

    def test_blank_text_field_blocked(self):
        for blank in ("", "   ", None, 7):
            with self.subTest(blank=blank):
                problems = gate.check_segment(HEALTH, with_ver(health_segment(), speaker=blank), 1)
                self.assertTrue(any("speaker" in p for p in problems))

    def test_true_field_must_be_exactly_true(self):
        for bad in ("yes", 1, None, False):
            with self.subTest(bad=bad):
                problems = gate.check_segment(HEALTH, with_ver(health_segment(), context_checked=bad), 1)
                self.assertTrue(any("context_checked" in p for p in problems))

    def test_framing_inside_clip(self):
        ok = gate.check_segment(HEALTH, with_ver(health_segment(), framing_time="00:12"), 1)
        self.assertEqual(ok, [])  # the clip's own first second counts
        for bad in ("00:58", "00:05", "09:00", "abc", ""):
            with self.subTest(bad=bad):
                problems = gate.check_segment(HEALTH, with_ver(health_segment(), framing_time=bad), 1)
                self.assertTrue(any("framing_time" in p for p in problems), problems)
        seg = health_segment()
        del seg["verification"]["framing_time"]
        self.assertTrue(any("framing_time" in p for p in gate.check_segment(HEALTH, seg, 1)))

    def test_duration_bounds(self):
        short = health_segment(start_time="00:12", end_time="00:32")
        self.assertTrue(any("30-90" in p for p in gate.check_segment(HEALTH, short, 1)))
        long = health_segment(start_time="00:12", end_time="01:52")
        self.assertTrue(any("30-90" in p for p in gate.check_segment(HEALTH, long, 1)))
        for end in ("00:42", "01:42"):  # exactly 30 s and exactly 90 s
            self.assertEqual(gate.check_segment(HEALTH, health_segment(end_time=end), 1), [])

    def test_unparseable_times_reported_not_raised(self):
        problems = gate.check_segment(HEALTH, health_segment(start_time="soon"), 1)
        self.assertTrue(any("start_time" in p for p in problems))

    def test_tech_light_gate(self):
        self.assertEqual(gate.check_segment(TECH, tech_segment(), 1), [])
        self.assertTrue(gate.check_segment(TECH, tech_segment(end_time="01:10"), 1))  # 10 s
        no_claims = tech_segment()
        no_claims["verification"] = {"speaker": "Jane Doe"}
        self.assertTrue(any("claims_checked" in p for p in gate.check_segment(TECH, no_claims, 1)))

    def test_mythology_requires_all_four(self):
        self.assertEqual(gate.check_segment(MYTH, myth_segment(), 1), [])
        for key in ("source_text", "variant_note", "verses_checked", "respect_check"):
            seg = myth_segment()
            del seg["verification"][key]
            with self.subTest(key=key):
                self.assertTrue(any(key in p for p in gate.check_segment(MYTH, seg, 1)))

    def test_commentary_limit(self):
        for pack in (HEALTH, None):
            base = health_segment()
            self.assertEqual(gate.check_segment(pack, dict(base, commentary="x" * 140), 1), [])
            self.assertTrue(any("commentary" in p for p in gate.check_segment(pack, dict(base, commentary="x" * 141), 1)))
            self.assertTrue(any("commentary" in p for p in gate.check_segment(pack, dict(base, commentary=5), 1)))
        self.assertEqual(gate.check_segment(None, {"start_time": "00:00", "end_time": "00:20"}, 1), [])

    def test_flags_must_be_list_of_strings(self):
        self.assertEqual(gate.check_segment(HEALTH, with_ver(health_segment(), risk_flags=["dosage"]), 1), [])
        seg = health_segment()
        del seg["verification"]["risk_flags"]
        self.assertEqual(gate.check_segment(HEALTH, seg, 1), [])
        for bad in ("dosage", [1], {"a": 1}):
            with self.subTest(bad=bad):
                self.assertTrue(any("risk_flags" in p for p in
                                    gate.check_segment(HEALTH, with_ver(health_segment(), risk_flags=bad), 1)))


class PartitionTest(unittest.TestCase):
    def test_partition_respects_indexes_and_order(self):
        segs = [health_segment(), health_segment(verification=None), health_segment(verification=None), health_segment()]
        allowed, blocked = gate.partition(HEALTH, segs, [4, 2, 1])
        self.assertEqual(allowed, [4, 1])
        self.assertEqual(sorted(blocked), [2])  # segment 3 was not selected
        self.assertIn("segment 2", blocked[2][0])

    def test_check_all_covers_every_segment(self):
        segs = [health_segment(), health_segment(verification=None), health_segment(verification=None)]
        self.assertEqual(sorted(gate.check_all(HEALTH, segs)), [2, 3])

    def test_partition_without_pack_only_checks_commentary(self):
        segs = [{"start_time": "00:00", "end_time": "00:20"},
                {"start_time": "00:00", "end_time": "00:20", "commentary": "y" * 200}]
        allowed, blocked = gate.partition(None, segs, [1, 2])
        self.assertEqual((allowed, sorted(blocked)), ([1], [2]))


class OverlaysTest(unittest.TestCase):
    def test_health_overlays(self):
        out = gate.overlays_for(HEALTH, dict(health_segment(), commentary="Context: adults only"))
        self.assertEqual(out, {"speaker": "Dr Rao, cardiologist",
                               "disclaimer": "General information, not medical advice.",
                               "commentary": "Context: adults only"})

    def test_health_overlays_without_commentary(self):
        self.assertNotIn("commentary", gate.overlays_for(HEALTH, health_segment()))

    def test_speaker_needs_both_name_and_credential(self):
        out = gate.overlays_for(HEALTH, with_ver(health_segment(), credential=""))
        self.assertNotIn("speaker", out)

    def test_tech_has_no_speaker_or_disclaimer(self):
        self.assertEqual(gate.overlays_for(TECH, tech_segment()), {})
        self.assertEqual(gate.overlays_for(TECH, dict(tech_segment(), commentary="note")), {"commentary": "note"})

    def test_none_pack_only_commentary(self):
        self.assertEqual(gate.overlays_for(None, {"commentary": "hello"}), {"commentary": "hello"})
        self.assertEqual(gate.overlays_for(None, {}), {})

    def test_blank_commentary_ignored(self):
        self.assertEqual(gate.overlays_for(None, {"commentary": "   "}), {})


class ReportTest(unittest.TestCase):
    def test_report_lists_each_clip(self):
        segs = [with_ver(health_segment(commentary="Adults only"), risk_flags=["dosage"]),
                health_segment(verification=None)]
        report = gate.report_markdown(HEALTH, segs, gate.check_all(HEALTH, segs))
        self.assertIn("health", report)
        self.assertIn("OK", report)
        self.assertIn("BLOCKED", report)
        self.assertIn("dosage", report)
        self.assertIn("Adults only", report)
        self.assertIn("the doctor adds this applies only to adults", report)
        self.assertIn("segment 2", report)

    def test_report_keeps_non_ascii(self):
        seg = myth_segment(verification=dict(myth_segment()["verification"], source_text="Rāmāyaṇa"))
        self.assertIn("Rāmāyaṇa", gate.report_markdown(MYTH, [seg], {}))


if __name__ == "__main__":
    unittest.main()
