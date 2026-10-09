"""Offline release guardrails for template users; run with unittest discover."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".secondme" / "framework-manifest.json"
LOCK = ROOT / ".secondme" / "framework-lock.json"


def blob_sha(content):
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def domain_ids(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    return re.findall(r"^\| (D\d\d) \|", text, flags=re.MULTILINE)


class ReleaseIntegrityTests(unittest.TestCase):
    def test_public_release_manifest_allows_exactly_official_markdown(self):
        m = json.loads(RELEASE.read_text(encoding="utf-8"))
        self.assertEqual(m["schema"], 1)
        self.assertEqual(m["source"], "CochraneK/Secondme-Framework")
        expected_paths = sorted(
            p.relative_to(ROOT).as_posix()
            for folder in ("framework", "prompts", "templates")
            for p in (ROOT / folder).rglob("*.md")
        )
        self.assertEqual(sorted(m["files"]), expected_paths)
        for name, sha in m["files"].items():
            self.assertEqual(blob_sha((ROOT / name).read_bytes()), sha, name)

    def test_initial_template_lock_matches_official_release(self):
        self.assertEqual(
            json.loads(LOCK.read_text(encoding="utf-8")),
            json.loads(RELEASE.read_text(encoding="utf-8")),
        )

    def test_all_user_domain_indexes_have_same_twenty_ids(self):
        expected = ["D%02d" % i for i in range(1, 21)]
        for name in (
            "framework/personal_domains.md",
            "templates/DOMAIN_INDEX_TEMPLATE.md",
            "my/INDEX.md",
        ):
            self.assertEqual(domain_ids(name), expected, name)

    def test_new_user_index_is_blank(self):
        text = (ROOT / "my/INDEX.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("| EMPTY |"), 20)
        self.assertNotIn("| ESTABLISHED |", text)
        self.assertNotIn("| IN_PROGRESS |", text)


if __name__ == "__main__":
    unittest.main()
