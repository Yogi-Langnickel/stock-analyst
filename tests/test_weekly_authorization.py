"""Skill synchronization behavior, without testing the wording of instructions."""

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install-weekly-skill"
_LOADER = importlib.machinery.SourceFileLoader("weekly_skill_installer", str(_SCRIPT))
_SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
installer = importlib.util.module_from_spec(_SPEC)
_LOADER.exec_module(installer)


class WeeklySkillSynchronizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / "canonical"
        self.destination = root / "installed"
        for name in installer.OWNED_FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("reviewed " + name + "\n")

    def install(self, **overrides):
        state = installer.check_bundle(self.source, self.destination)
        arguments = {
            "expected_source_digest": state["sourceDigest"],
            "expected_installed_digest": state["installedDigest"],
        }
        arguments.update(overrides)
        return installer.install_bundle(self.source, self.destination, **arguments)

    def test_exact_owned_bundle_install_and_read_only_drift_check(self):
        initial = installer.check_bundle(self.source, self.destination)
        self.assertEqual(initial["installedDigest"], "absent")
        self.assertFalse(self.destination.exists())
        result = self.install()
        self.assertTrue(result["ok"])
        self.assertEqual(result["changedFileCount"], 5)
        self.assertEqual(result["sourceDigest"], result["installedDigest"])
        changed = self.destination / "SKILL.md"
        changed.write_text("local change\n")
        before = changed.read_bytes()
        check = installer.check_bundle(self.source, self.destination)
        self.assertFalse(check["ok"])
        self.assertEqual(check["differingFiles"], ["SKILL.md"])
        self.assertEqual(changed.read_bytes(), before)

    def test_changed_installation_is_not_overwritten_from_stale_inspection(self):
        self.install()
        inspected = installer.check_bundle(self.source, self.destination)
        path = self.destination / "SKILL.md"
        path.write_text("new local work\n")
        with self.assertRaisesRegex(ValueError, "installed skill changed"):
            self.install(expected_installed_digest=inspected["installedDigest"])
        self.assertEqual(path.read_text(), "new local work\n")

    def test_changed_source_requires_new_review_digest(self):
        inspected = installer.check_bundle(self.source, self.destination)
        (self.source / "SKILL.md").write_text("unreviewed change\n")
        with self.assertRaisesRegex(ValueError, "canonical skill changed"):
            self.install(expected_source_digest=inspected["sourceDigest"])
        self.assertFalse(self.destination.exists())

    def test_unowned_files_are_preserved_and_not_copied(self):
        self.destination.mkdir()
        keep = self.destination / "local-note.txt"
        keep.write_text("preserve user work\n")
        (self.source / "untracked-note.txt").write_text("do not copy\n")
        self.install()
        self.assertEqual(keep.read_text(), "preserve user work\n")
        self.assertFalse((self.destination / "untracked-note.txt").exists())

    def test_owned_symlink_is_rejected_without_touching_target(self):
        self.destination.mkdir()
        target = self.destination.parent / "private-target"
        target.write_text("keep\n")
        (self.destination / "SKILL.md").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            installer.check_bundle(self.source, self.destination)
        self.assertEqual(target.read_text(), "keep\n")

    def test_interrupted_replacement_restores_previous_owned_bytes(self):
        self.install()
        original = installer.read_bundle(self.destination, required=True)
        for name in installer.OWNED_FILES:
            (self.source / name).write_text("new " + name + "\n")
        replace = installer.os.replace
        calls = 0

        def fail_second_replacement(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected interruption")
            return replace(source, destination)

        with mock.patch.object(installer.os, "replace", side_effect=fail_second_replacement):
            with self.assertRaisesRegex(OSError, "injected interruption"):
                self.install()
        self.assertEqual(installer.read_bundle(self.destination, required=True), original)
        self.assertFalse((self.destination.parent / ".installed.install.lock").exists())
        self.assertEqual(list(self.destination.rglob(".weekly-skill-*")), [])


if __name__ == "__main__":
    unittest.main()
