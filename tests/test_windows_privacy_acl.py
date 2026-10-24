"""Synthetic DACL policy tests and actual Windows security-descriptor checks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest import mock
from windows_fixture import protect_private_path
from run_windows_validation import WindowsSecurity, current_user_owner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import privacy_guard


class WindowsAclPolicyTests(unittest.TestCase):
    USER = b"synthetic-current-user"
    SYSTEM = bytes.fromhex("010100000000000512000000")
    ADMIN = bytes.fromhex("01020000000000052000000020020000")
    OTHER = b"synthetic-unrelated-principal"

    def validate(self, entries, owner=None):
        privacy_guard._validate_windows_acl(owner or self.USER, self.USER, entries)

    def test_current_user_system_and_administrators_are_allowed(self):
        self.validate([(0, 0, 0x1F01FF, self.USER), (0, 0x10, 0x1F01FF, self.SYSTEM),
                       (0, 0x10, 0x1F01FF, self.ADMIN)])

    def test_other_principal_read_or_write_grant_is_rejected(self):
        for mask in (0x1, 0x2, 0x10000000, 0x80000000):
            with self.subTest(mask=mask), self.assertRaises(privacy_guard.PrivacyError) as caught:
                self.validate([(0, 0, mask, self.OTHER)])
            self.assertEqual(caught.exception.category, "profile_permissions")
            self.assertNotIn("synthetic", str(caught.exception))

    def test_null_dacl_or_other_owner_fails_closed(self):
        with self.assertRaises(privacy_guard.PrivacyError):
            self.validate(None)
        with self.assertRaises(privacy_guard.PrivacyError):
            self.validate([], owner=self.OTHER)

    def test_deny_does_not_cancel_an_untrusted_allow(self):
        with self.assertRaises(privacy_guard.PrivacyError):
            self.validate([(1, 0, 0x1, self.OTHER), (0, 0, 0x1, self.OTHER)])

    def test_callback_object_and_unknown_aces_are_rejected(self):
        for ace_type in (5, 6, 9, 10, 17, 255):
            with self.subTest(ace_type=ace_type), self.assertRaises(privacy_guard.PrivacyError):
                self.validate([(ace_type, 0, 0x1, self.USER)])

    def test_inherit_only_grants_do_not_apply_to_the_profile_file(self):
        self.validate([(0, 0x08, 0x1F01FF, self.OTHER)])
        with self.assertRaises(privacy_guard.PrivacyError):
            self.validate([(0, 0x10, 0x1F01FF, self.OTHER)])

    def test_public_export_requires_nonempty_profile(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(privacy_guard.PrivacyError) as caught:
                privacy_guard.ensure_public_safe("synthetic public output", require_profile=True)
        self.assertEqual(caught.exception.category, "profile_required")
        with self.assertRaises(privacy_guard.PrivacyError):
            privacy_guard.ensure_public_safe("synthetic public output", require_profile=True,
                                             profile=privacy_guard.build_profile([], [], key=b"x" * 32))
        privacy_guard.ensure_public_safe("synthetic public output", require_profile=True,
                                         profile=privacy_guard.build_profile(["Fictional Identity"], [], key=b"x" * 32))

    def test_local_exploration_without_profile_remains_available(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            privacy_guard.ensure_public_safe("synthetic local output")

    def test_failed_native_security_query_is_bounded(self):
        if os.name != "nt":
            with self.assertRaises(privacy_guard.PrivacyError) as caught:
                privacy_guard._windows_profile_security(-1)
            self.assertEqual(caught.exception.category, "profile_permissions")


@unittest.skipUnless(os.name == "nt", "requires actual Windows security APIs")
class WindowsNativeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        protect_private_path(self.temp.name)
        self.path = Path(self.temp.name) / "synthetic-profile.json"
        self.path.write_text(json.dumps(privacy_guard.build_profile(["Fictional Identity"], [], key=b"x" * 32)))
        self.env = mock.patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def set_dacl(self, world_read=False):
        # Explicit current-token-user owner, not the inherited file owner.
        protect_private_path(self.path, world_read=world_read)

    def test_native_owner_only_profile_can_be_read_repeatedly(self):
        self.set_dacl()
        self.assertIsNotNone(privacy_guard.load_profile(required=True))
        self.assertIsNotNone(privacy_guard.load_profile(required=True))

    def test_native_world_read_profile_is_rejected(self):
        self.set_dacl(world_read=True)
        with self.assertRaises(privacy_guard.PrivacyError) as caught:
            privacy_guard.load_profile(required=True)
        self.assertEqual(caught.exception.category, "profile_permissions")

    def test_native_default_owner_scope_restores_and_child_files_pass_real_guard(self):
        security = WindowsSecurity()
        try:
            original = security.token_sid(4)
            with current_user_owner() as scoped:
                self.assertTrue(scoped.token_sid(4) == scoped.token_sid(1))
                code = """import json,os,sys
from run_windows_validation import WindowsSecurity
import privacy_guard
security=WindowsSecurity()
try:
 owner_matches=security.token_sid(4)==security.token_sid(1)
 descriptor=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  private=bool(privacy_guard._windows_profile_security(descriptor))
 finally:
  os.close(descriptor)
 print(json.dumps({'ownerMatchesCurrentUser':owner_matches,'newFilePrivate':private}))
finally:
 security.close()
"""
                result = subprocess.run([sys.executable, "-c", code, str(self.path.with_name("child-owned.json"))],
                    cwd=Path(privacy_guard.__file__).parent, env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "scripts")),
                    capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
                # Never include stderr, account names, or SID bytes in assertions.
                self.assertTrue(result.returncode == 0, "native_child_owner_check_failed")
                receipt = json.loads(result.stdout)
                self.assertTrue(receipt.get("ownerMatchesCurrentUser") is True)
                self.assertTrue(receipt.get("newFilePrivate") is True)
            self.assertTrue(security.token_sid(4) == original, "native_default_owner_not_restored")
        finally:
            security.close()

    def test_native_owner_scope_restores_after_exception(self):
        security = WindowsSecurity()
        try:
            original = security.token_sid(4)
            with self.assertRaisesRegex(RuntimeError, "synthetic_owner_scope_failure"):
                with current_user_owner():
                    raise RuntimeError("synthetic_owner_scope_failure")
            self.assertTrue(security.token_sid(4) == original, "native_default_owner_not_restored")
        finally:
            security.close()


if __name__ == "__main__":
    unittest.main()
