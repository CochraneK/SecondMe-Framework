"""Offline tests for no-overwrite behavior. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "secondme_updater.py"
spec = importlib.util.spec_from_file_location("secondme_updater", MODULE)
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "framework").mkdir()
        (self.root / ".secondme").mkdir()
        self.old = b"# Original official framework\n"
        self.new = b"# Updated official framework\n"
        self.name = "framework/example.md"
        (self.root / self.name).write_bytes(self.old)
        self.lock = {
            "schema": 1, "source": up.UPSTREAM,
            "version": "0.2.0",
            "files": {self.name: up.git_blob_sha(self.old)}
        }
        (self.root / up.LOCK_PATH).write_text(json.dumps(self.lock), encoding="utf-8")
        self.manifest = dict(self.lock, version="0.3.0",
                             files={self.name: up.git_blob_sha(self.new)})

    def tearDown(self):
        self.tmp.cleanup()

    def retrieve(self, name, sha):
        self.assertEqual(name, self.name)
        self.assertEqual(sha, up.git_blob_sha(self.new))
        return self.new

    def test_clean_official_file_upgrades(self):
        r = up.produce_update(self.root, self.lock, self.manifest, self.retrieve, apply=True)
        self.assertEqual((self.root / self.name).read_bytes(), self.new)
        self.assertEqual(r["modified"], [self.name])
        self.assertEqual(json.loads((self.root / up.LOCK_PATH).read_text())["version"], "0.3.0")
        self.assertEqual(r["stage_paths"], [self.name, up.LOCK_PATH, up.NOTICE_PATH])

    def test_custom_edit_never_overwritten(self):
        custom = b"My personal edits: keep this unchanged"
        (self.root / self.name).write_bytes(custom)
        r = up.produce_update(self.root, self.lock, self.manifest, self.retrieve, apply=True)
        self.assertEqual((self.root / self.name).read_bytes(), custom)
        self.assertEqual(r["conflicts"], [self.name])
        self.assertEqual(json.loads((self.root / up.LOCK_PATH).read_text())["version"], "0.2.0")
        self.assertTrue((self.root / up.NOTICE_PATH).exists())

    def test_dry_run_never_writes(self):
        r = up.produce_update(self.root, self.lock, self.manifest, self.retrieve, apply=False)
        self.assertEqual((self.root / self.name).read_bytes(), self.old)
        self.assertEqual(r["modified"], [self.name])
        self.assertFalse((self.root / up.NOTICE_PATH).exists())

    def test_new_file_is_added_without_modifying_other_files(self):
        name = "framework/new-topic.md"
        data = b"# New topic\n"
        manifest = dict(self.manifest, files={
            self.name: up.git_blob_sha(self.old), name: up.git_blob_sha(data)
        })
        r = up.produce_update(
            self.root, self.lock, manifest,
            lambda _name, _sha: data,
            apply=True
        )
        self.assertEqual((self.root / name).read_bytes(), data)
        self.assertEqual((self.root / self.name).read_bytes(), self.old)
        self.assertEqual(r["conflicts"], [])

    def test_deleted_locally_does_not_get_restored(self):
        (self.root / self.name).unlink()
        r = up.produce_update(self.root, self.lock, self.manifest, self.retrieve, apply=True)
        self.assertFalse((self.root / self.name).exists())
        self.assertEqual(r["conflicts"], [self.name])

    def test_removed_upstream_does_not_delete_user_files(self):
        manifest = dict(self.manifest, files={})
        r = up.produce_update(self.root, self.lock, manifest, self.retrieve, apply=True)
        self.assertTrue((self.root / self.name).exists())
        self.assertEqual(r["upstream_removed"], [self.name])

    def test_same_version_is_noop_after_user_edit(self):
        (self.root / self.name).write_bytes(b"# Customized locally")
        same = dict(self.lock)
        r = up.produce_update(self.root, self.lock, same, self.retrieve, apply=True)
        self.assertEqual(r["stage_paths"], [])
        self.assertFalse((self.root / up.NOTICE_PATH).exists())

    def test_reject_path_traversal_and_executable(self):
        self.assertFalse(up.allowed_path("framework/../../my/private.md"))
        self.assertFalse(up.allowed_path("prompts/start.py"))
        self.assertFalse(up.allowed_path("custom/private.md"))
        self.assertFalse(up.allowed_path("framework/.hidden.md"))
        with self.assertRaises(up.UpdateError):
            up.validate_record(
                dict(self.manifest, files={"../secret.md": "a" * 40}), remote=True
            )

    def test_hash_verification_stops_on_mismatch(self):
        orig = up.fetch_bytes
        try:
            up.fetch_bytes = lambda url: b"wrong bytes"
            with self.assertRaises(up.UpdateError):
                up.fetch_official_file(self.name, "a" * 40)
        finally:
            up.fetch_bytes = orig

    def test_symlink_is_never_overwritten(self):
        outside = self.root / "external.md"
        outside.write_bytes(b"Private data")
        (self.root / self.name).unlink()
        (self.root / self.name).symlink_to(outside)
        with self.assertRaises(up.UpdateError):
            up.produce_update(self.root, self.lock, self.manifest, self.retrieve, apply=True)
        self.assertEqual(outside.read_bytes(), b"Private data")


if __name__ == "__main__":
    unittest.main()
