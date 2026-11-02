import unittest
from pathlib import Path

from clipwright import domains

ROOT = Path(__file__).resolve().parent.parent
EM_DASH = "—"


def skill_text(name):
    return (ROOT / "skill" / "domains" / name / "SKILL.md").read_text(encoding="utf-8")


class DomainSkillTest(unittest.TestCase):
    def test_every_pack_has_a_skill_with_frontmatter(self):
        for name in domains.list_packs(ROOT / "domains"):
            with self.subTest(name=name):
                text = skill_text(name)
                self.assertTrue(text.startswith("---\n"))
                self.assertIn(f"\nname: clip-{name}\n", text)
                self.assertIn("\ndescription: ", text)
                self.assertIn("__CLIP_DIR__", text)
                self.assertIn(f"clip fetch --domain {name}", text)
                self.assertIn("supoclip", text)  # the base skill that holds the common steps

    def test_skill_names_every_verification_field_and_overlay(self):
        for name in domains.list_packs(ROOT / "domains"):
            pack = domains.load_pack(name, ROOT / "domains")
            text = skill_text(name)
            fields = [k for group in pack["verification"].values() for k in group]
            for field in fields:
                with self.subTest(name=name, field=field):
                    self.assertIn(field, text)
            if pack["overlays"]["disclaimer"]:
                self.assertIn(pack["overlays"]["disclaimer"], text)
            if pack["overlays"]["speaker"]:
                self.assertIn("speaker", text.lower())
            self.assertIn("commentary", text)

    def test_skills_state_the_clip_length_limits(self):
        for name in domains.list_packs(ROOT / "domains"):
            pack = domains.load_pack(name, ROOT / "domains")
            secs = pack["clip_seconds"]
            with self.subTest(name=name):
                self.assertIn(f"{secs['min']}", skill_text(name))
                self.assertIn(f"{secs['max']}", skill_text(name))

    def test_no_em_dashes_in_any_skill(self):
        paths = [ROOT / "skill" / "SKILL.md"] + [ROOT / "skill" / "domains" / n / "SKILL.md"
                                                  for n in domains.list_packs(ROOT / "domains")]
        for path in paths:
            with self.subTest(path=path.name):
                self.assertNotIn(EM_DASH, path.read_text(encoding="utf-8"))

    def test_setup_installs_the_domain_skills(self):
        setup = (ROOT / "setup.sh").read_text()
        self.assertIn("skill/domains", setup)
        self.assertIn("clip-", setup)


if __name__ == "__main__":
    unittest.main()
