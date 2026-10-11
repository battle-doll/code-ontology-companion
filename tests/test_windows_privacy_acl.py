"""Synthetic DACL policy tests and actual Windows security-descriptor checks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        self.path = Path(self.temp.name) / "synthetic-profile.json"
        self.path.write_text(json.dumps(privacy_guard.build_profile(["Fictional Identity"], [], key=b"x" * 32)))
        self.env = mock.patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def set_dacl(self, world_read=False):
        # Transient native owner SID is used to create a test-only DACL. Never
        # print/serialize it or include any identity value in test assertions.
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p
        owner, security, converted = pointer(), pointer(), pointer()
        owner_string = wintypes.LPWSTR()
        advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
            ctypes.POINTER(pointer), pointer, pointer, pointer, ctypes.POINTER(pointer)]
        advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
        advapi.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR)]
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.POINTER(pointer), pointer]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, pointer]
        advapi.SetFileSecurityW.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [pointer]
        kernel.LocalFree.restype = pointer
        try:
            self.assertEqual(advapi.GetNamedSecurityInfoW(str(self.path), 1, 1,
                ctypes.byref(owner), None, None, None, ctypes.byref(security)), 0)
            self.assertTrue(advapi.ConvertSidToStringSidW(owner, ctypes.byref(owner_string)))
            dacl = "D:P(A;;FA;;;" + owner_string.value + ")(A;;FA;;;SY)(A;;FA;;;BA)"
            if world_read:
                dacl += "(A;;FR;;;WD)"
            self.assertTrue(advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(dacl, 1,
                ctypes.byref(converted), None))
            self.assertTrue(advapi.SetFileSecurityW(str(self.path), 0x80000004, converted))
        finally:
            for value in (converted, owner_string, security):
                if value:
                    kernel.LocalFree(value)

    def test_native_owner_only_profile_can_be_read_repeatedly(self):
        self.set_dacl()
        self.assertIsNotNone(privacy_guard.load_profile(required=True))
        self.assertIsNotNone(privacy_guard.load_profile(required=True))

    def test_native_world_read_profile_is_rejected(self):
        self.set_dacl(world_read=True)
        with self.assertRaises(privacy_guard.PrivacyError) as caught:
            privacy_guard.load_profile(required=True)
        self.assertEqual(caught.exception.category, "profile_permissions")


if __name__ == "__main__":
    unittest.main()
