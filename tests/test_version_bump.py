from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_version_bump as policy  # noqa: E402


class VersionBumpPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "version-policy@example.invalid")
        self.git("config", "user.name", "Version Policy Test")
        (self.repo / ".codex-plugin").mkdir()
        self.write_version("0.3.1")
        (self.repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 0.3.1 - 2026-08-01\n\n- Baseline.\n",
            encoding="utf-8",
        )
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def write_version(self, version: str) -> None:
        (self.repo / policy.MANIFEST).write_text(
            json.dumps({"version": version}) + "\n",
            encoding="utf-8",
        )

    def commit(self, message: str) -> None:
        self.git("add", ".")
        self.git("commit", "-qm", message)

    def test_unchanged_revision_does_not_require_a_bump(self) -> None:
        result = policy.validate_version_bump(self.repo, self.base)
        self.assertEqual("unchanged", result["status"])

    def test_tracked_change_without_version_bump_fails(self) -> None:
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        self.commit("change without bump")
        with self.assertRaisesRegex(policy.VersionPolicyError, "require a version greater"):
            policy.validate_version_bump(self.repo, self.base)

    def test_tracked_deletion_without_version_bump_fails(self) -> None:
        (self.repo / "README.md").unlink()
        self.git("add", "-u")
        self.git("commit", "-qm", "delete without bump")
        with self.assertRaisesRegex(policy.VersionPolicyError, "require a version greater"):
            policy.validate_version_bump(self.repo, self.base)

    def test_advanced_version_requires_and_accepts_first_changelog_entry(self) -> None:
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        self.write_version("0.3.2")
        self.commit("bump without changelog")
        with self.assertRaisesRegex(policy.VersionPolicyError, "first dated changelog"):
            policy.validate_version_bump(self.repo, self.base)

        (self.repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 0.3.2 - 2026-08-02\n\n- Changed.\n\n"
            "## 0.3.1 - 2026-08-01\n\n- Baseline.\n",
            encoding="utf-8",
        )
        self.commit("record release")
        result = policy.validate_version_bump(self.repo, self.base)
        self.assertEqual("version-advanced", result["status"])
        self.assertEqual("0.3.1", result["baseVersion"])
        self.assertEqual("0.3.2", result["currentVersion"])

    def test_divergent_history_compares_the_exact_previous_revision(self) -> None:
        self.write_version("0.3.2")
        (self.repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 0.3.2 - 2026-08-02\n\n- Released.\n\n"
            "## 0.3.1 - 2026-08-01\n\n- Baseline.\n",
            encoding="utf-8",
        )
        self.commit("release 0.3.2")
        released = self.git("rev-parse", "HEAD").strip()

        self.git("checkout", "-qb", "rewritten", self.base)
        self.write_version("0.3.2")
        (self.repo / "README.md").write_text("divergent change\n", encoding="utf-8")
        (self.repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 0.3.2 - 2026-08-02\n\n- Reused.\n\n"
            "## 0.3.1 - 2026-08-01\n\n- Baseline.\n",
            encoding="utf-8",
        )
        self.commit("rewrite without advancing version")
        with self.assertRaisesRegex(policy.VersionPolicyError, "greater than 0.3.2"):
            policy.validate_version_bump(self.repo, released)


if __name__ == "__main__":
    unittest.main()
