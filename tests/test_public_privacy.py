from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile
import zlib
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_public_privacy as privacy
from privacy_guard import build_profile, PROFILE_ENV


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

    def test_private_name_encodings_and_filenames_never_enter_reports(self):
        with tempfile.TemporaryDirectory() as raw:
            policy = Path(raw).resolve() / "policy.json"
            name = "FictionPersonZQ"
            policy.write_text(json.dumps(build_profile([name], [])))
            policy.chmod(0o600)
            with mock.patch.dict(os.environ, {PROFILE_ENV: str(policy)}):
                for value in (name, "Fiction Person ZQ", "Fiction_Person-ZQ",
                              "FictionPerson%5A%51", "FictionPerson&#90;&#81;",
                              "FictionPerson\\u005a\\u0051"):
                    with self.subTest(value=value):
                        findings = privacy.scan_text(value + ".txt", value)
                        self.assertIn("known-private-identity", {f["rule"] for f in findings})
                        self.assertEqual("<redacted-path>", findings[0]["file"])
                        self.assertNotIn(name, json.dumps(findings))

    def test_binary_metadata_and_zero_width_email_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            policy = Path(raw).resolve() / "policy.json"
            name = "FictionPersonZQ"
            policy.write_text(json.dumps(build_profile([name], [])))
            policy.chmod(0o600)
            with mock.patch.dict(os.environ, {PROFILE_ENV: str(policy)}):
                for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
                    findings = privacy.scan_bytes("image.png", b"\x89PNG\0" + name.encode(encoding))
                    self.assertIn("known-private-identity", {f["rule"] for f in findings})
                email = "fiction-person" + "\u200b" + "@" + "private-provider.org"
                findings = privacy.scan_text("test.md", email)
                self.assertIn("non-synthetic-email", {f["rule"] for f in findings})
                self.assertNotIn(email, json.dumps(findings))

    def test_generated_tree_rejects_links_and_checks_hidden_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "outputs"
            root.mkdir()
            (root / "snapshot.json").write_text(json.dumps({"historical": {"contact": "fiction-person" + "@" + "private-provider.org"}}))
            (root / "pointer").symlink_to(root / "snapshot.json")
            findings, count = privacy.scan_directory(root)
            self.assertEqual(1, count)
            self.assertTrue({"generated-link", "non-synthetic-email"}.issubset({f["rule"] for f in findings}))

    def test_git_audit_covers_all_refs_and_annotated_taggers(self):
        alias_email = "battle-doll" + "@users.noreply.github.com"
        with mock.patch.object(privacy.subprocess, "check_output", side_effect=[
            ("battle-doll\0" + alias_email + "\0battle-doll\0" + alias_email + "\n").encode(),
            b"Safe release message\n",
            ("refs/tags/test\0FictionPersonZQ\0<fiction-person" + "@" + "private-provider.org>\n").encode(),
        ]) as captured:
            findings = privacy.scan_git_identity(Path("."))
            self.assertIn("--all", captured.call_args_list[0].args[0])
            self.assertIn("--all", captured.call_args_list[1].args[0])
            self.assertIn("git-tagger-identity", {f["rule"] for f in findings})
            self.assertNotIn("FictionPersonZQ", json.dumps(findings))

    def test_compressed_png_metadata_is_checked_without_scanning_pixel_stream(self):
        def chunk(kind, content):
            return len(content).to_bytes(4, "big") + kind + content + zlib.crc32(kind + content).to_bytes(4, "big")
        email = ("fiction-person" + "@" + "private-provider.org").encode()
        prefix = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", b"\0" * 13)
        suffix = chunk(b"IEND", b"")
        pixels = prefix + chunk(b"IDAT", zlib.compress(email)) + suffix
        self.assertEqual([], privacy.scan_bytes("image.png", pixels))
        metadata = prefix + chunk(b"zTXt", b"Contact\0\0" + zlib.compress(email)) + suffix
        findings = privacy.scan_bytes("image.png", metadata)
        self.assertIn("non-synthetic-email", {f["rule"] for f in findings})
        self.assertNotIn(email.decode(), json.dumps(findings))

    def test_malformed_png_and_jpeg_metadata_fail_closed(self):
        self.assertIn("unsupported-public-binary", {f["rule"] for f in privacy.scan_bytes("image.png", b"\x89PNG\r\n\x1a\n\0")})
        email = ("fiction-person" + "@" + "private-provider.org").encode()
        data = b"\xff\xd8\xff\xfe" + (len(email) + 2).to_bytes(2, "big") + email + b"\xff\xd9"
        self.assertIn("non-synthetic-email", {f["rule"] for f in privacy.scan_bytes("image.jpg", data)})

    def test_profile_keys_and_fingerprints_are_private_output_material(self):
        from privacy_guard import PrivacyError, ensure_public_safe
        profile = build_profile(["FictionPersonZQ"], ["fiction-person@example.invalid"])
        values = [profile, profile["key"], profile["denyNames"][0]["digest"].upper(),
                  profile["denyNames"][0]["prefixDigest"], profile["denyEmails"][0]["digest"],
                  "<script>" + json.dumps(profile) + "</script>"]
        for value in values:
            with self.assertRaises(PrivacyError) as raised:
                ensure_public_safe(value, profile=profile)
            self.assertEqual("private_profile_material", raised.exception.category)
            self.assertNotIn(profile["key"], str(raised.exception))


if __name__ == "__main__":
    unittest.main()
