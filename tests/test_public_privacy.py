from __future__ import annotations

import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_public_privacy as privacy


class PublicPrivacyTests(unittest.TestCase):
    def test_identity_and_examples_are_safe(self):
        manifest = {"author": {"name": "battle-doll"},
                    "interface": {"developerName": "battle-doll"}}
        self.assertEqual([], privacy.scan_bytes(".codex-plugin/plugin.json", json.dumps(manifest).encode()))
        self.assertEqual([], privacy.scan_text("example.md", "support@example.com /home/user/project"))

    def test_findings_never_echo_private_content(self):
        email = "private-person" + "@" + "mail-provider.org"
        token = "sk-" + "z" * 32
        phone = "010" + "-1234-5678"
        text = email + "\n" + token + "\n" + phone
        findings = privacy.scan_text("guide.md", text)
        self.assertEqual({"non-synthetic-email", "credential", "personal-phone"}, {f["rule"] for f in findings})
        report = json.dumps(findings)
        for private in (email, token, phone):
            self.assertNotIn(private, report)
        self.assertEqual({1, 2, 3}, {f["line"] for f in findings})

    def test_public_manifest_rejects_email_even_noreply(self):
        manifest = {"author": {"name": "battle-doll", "email": "support@example.com"},
                    "interface": {"developerName": "battle-doll"}}
        self.assertIn("publisher-email", {f["rule"] for f in privacy.scan_bytes("plugin.json", json.dumps(manifest).encode())})

    def test_named_paths_and_malformed_text_fail_closed(self):
        path = "/Users/" + "private-person" + "/repo"
        self.assertIn("named-home-path", {f["rule"] for f in privacy.scan_text("file.md", path)})
        self.assertEqual("invalid-public-text", privacy.scan_bytes("file.md", b"\xff")[0]["rule"])

    def test_escaped_json_values_do_not_bypass_privacy_checks(self):
        encoded = ('{"contact":"private-person' + '\\u0040' + 'mail-provider.org"}').encode()
        findings = privacy.scan_bytes("metadata.json", encoded)
        self.assertIn("non-synthetic-email", {f["rule"] for f in findings})
        self.assertTrue(any(f["line"] == 0 for f in findings))

    def test_unicode_home_and_fine_grained_credentials_are_rejected(self):
        path = "/Users/" + "가상사용자" + "/repo"
        token = "github_pat_" + "x" * 80
        findings = privacy.scan_text("guide.md", path + "\n" + token)
        self.assertEqual({"named-home-path", "credential"}, {f["rule"] for f in findings})

    def test_archive_names_cannot_leak_in_reports(self):
        private = "private-person" + "@" + "mail-provider.org"
        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / (private + ".zip")
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(private + ".md", "sk-" + "x" * 40)
                link = zipfile.ZipInfo(private + "-link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                bundle.writestr(link, "/etc/passwd")
            findings, _count = privacy.scan_zip(archive)
            self.assertNotIn(private, json.dumps(findings))
            self.assertEqual("<redacted-path>", privacy._safe_name(archive.name))

    def test_archive_checks_content_names_links_and_traversal(self):
        with tempfile.TemporaryDirectory() as raw:
            archive = Path(raw) / "candidate.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.comment = ("private-person" + "@" + "mail-provider.org").encode()
                bundle.writestr("../outside.md", "example")
                bundle.writestr("inside.md", "person" + "@" + "private-provider.org")
                link = zipfile.ZipInfo("link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                bundle.writestr(link, "/etc/passwd")
            findings, count = privacy.scan_zip(archive)
            self.assertEqual(3, count)
            self.assertTrue({"unsafe-entry-path", "non-synthetic-email", "archive-link"}.issubset({f["rule"] for f in findings}))
            self.assertIn("<archive-comment>.txt", {f["file"] for f in findings})


if __name__ == "__main__":
    unittest.main()
