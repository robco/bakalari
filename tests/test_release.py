"""Release tooling checks; only run in a checkout containing .github/scripts."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "check_release.py"


@unittest.skipUnless(SCRIPT.is_file(), "release tooling is not included in distributions")
class ReleaseValidationTest(unittest.TestCase):
    def validate(self, changelog, *, ref_type="tag", ref_name="v1.0.0"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bakalari").mkdir()
            (root / "bakalari" / "_version.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
            (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
            shutil.copyfile(SCRIPT, root / "check_release.py")
            return subprocess.run(
                [sys.executable, "check_release.py"], cwd=root, capture_output=True, text=True, timeout=30,
                env={**os.environ, "GITHUB_REF_TYPE": ref_type, "GITHUB_REF_NAME": ref_name},
            )

    def test_matching_tag_and_complete_release_notes(self):
        result = self.validate("## [Unreleased]\n\n## [1.0.0] - 2026-10-26\n\nRelease notes.\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_branch_and_mismatched_tag_are_rejected(self):
        notes = "## [1.0.0] - 2026-10-26\n\nRelease notes.\n"
        for ref_type, ref_name in (("branch", "main"), ("tag", "v1.0.1"), ("tag", "1.0.0")):
            with self.subTest(ref_type=ref_type, ref_name=ref_name):
                result = self.validate(notes, ref_type=ref_type, ref_name=ref_name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Publish from the tag v1.0.0", result.stderr)

    def test_missing_empty_undated_or_invalid_release_notes_are_rejected(self):
        for notes in ("## [Unreleased]\n", "## [1.0.0] - 2026-10-26\n\n",
                      "## [1.0.0]\n\nNotes\n", "## [1.0.0] - 2026-02-30\n\nNotes\n"):
            with self.subTest(notes=notes):
                self.assertNotEqual(self.validate(notes).returncode, 0)

    def test_unreleased_changes_cannot_be_omitted_from_release_notes(self):
        result = self.validate("## [Unreleased]\n\n### Security\n\nA fix.\n\n"
                               "## [1.0.0] - 2026-10-26\n\nOld notes.\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Move Unreleased notes", result.stderr)
