import json
import tempfile
import unittest
from pathlib import Path

from clipwright import domains
from clipwright.domains import DomainError

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "domains"


def minimal(name="x", **over):
    pack = {
        "name": name, "description": "d",
        "clip_seconds": {"min": 10, "max": 60},
        "verification": {"text": [], "true": [], "time_inside": [], "flags": []},
        "overlays": {"speaker": False, "disclaimer": None},
        "sources": {"queries": ["q"], "watchlist": [], "min_minutes": 10, "min_views": 1000,
                    "max_age_days": None, "per_query": 5},
    }
    pack.update(over)
    return pack


class ShippedPacksTest(unittest.TestCase):
    def test_shipped_packs_load(self):
        for name in ("tech", "health", "mythology"):
            with self.subTest(name=name):
                self.assertEqual(domains.load_pack(name, PACKS)["name"], name)

    def test_health_pack_values(self):
        p = domains.load_pack("health", PACKS)
        self.assertEqual(p["clip_seconds"], {"min": 30, "max": 90})
        self.assertEqual(p["verification"]["text"], ["speaker", "credential", "context_excerpt"])
        self.assertEqual(p["verification"]["true"], ["context_checked"])
        self.assertEqual(p["verification"]["time_inside"], ["framing_time"])
        self.assertEqual(p["verification"]["flags"], ["risk_flags"])
        self.assertEqual(p["overlays"], {"speaker": True, "disclaimer": "General information, not medical advice."})

    def test_tech_pack_values(self):
        p = domains.load_pack("tech", PACKS)
        self.assertEqual(p["verification"]["text"], ["speaker"])
        self.assertEqual(p["verification"]["true"], ["claims_checked"])
        self.assertEqual(p["verification"]["flags"], ["dated_claims"])
        self.assertEqual(p["clip_seconds"]["min"], 15)
        self.assertEqual(p["overlays"], {"speaker": False, "disclaimer": None})

    def test_mythology_pack_values(self):
        p = domains.load_pack("mythology", PACKS)
        self.assertEqual(p["verification"]["text"], ["source_text", "variant_note"])
        self.assertEqual(p["verification"]["true"], ["verses_checked", "respect_check"])
        self.assertEqual(p["clip_seconds"], {"min": 20, "max": 75})


class LoaderTest(unittest.TestCase):
    def test_unknown_domain_lists_available(self):
        with self.assertRaises(DomainError) as cm:
            domains.load_pack("nope", PACKS)
        self.assertEqual(str(cm.exception), "unknown domain 'nope'; available: health, mythology, tech")

    def test_bad_name_rejected(self):
        for name in ("../x", "A", "", "a b"):
            with self.subTest(name=name):
                with self.assertRaises(DomainError):
                    domains.load_pack(name, PACKS)

    def test_invalid_pack_reports_every_problem(self):
        bad = minimal(clip_seconds={"min": 90, "max": 30}, extra_key=1)
        bad["sources"] = dict(bad["sources"], queries="not a list")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.json").write_text(json.dumps(bad))
            with self.assertRaises(DomainError) as cm:
                domains.load_pack("x", Path(d))
        text = str(cm.exception)
        self.assertIn("clip_seconds", text)
        self.assertIn("queries", text)
        self.assertIn("extra_key", text)

    def test_name_must_match_filename(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.json").write_text(json.dumps(minimal(name="y")))
            with self.assertRaises(DomainError) as cm:
                domains.load_pack("x", Path(d))
        self.assertIn("name", str(cm.exception))

    def test_valid_minimal_pack_loads(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.json").write_text(json.dumps(minimal()))
            self.assertEqual(domains.load_pack("x", Path(d))["name"], "x")

    def test_list_packs_sorted(self):
        self.assertEqual(domains.list_packs(PACKS), ["health", "mythology", "tech"])


if __name__ == "__main__":
    unittest.main()
