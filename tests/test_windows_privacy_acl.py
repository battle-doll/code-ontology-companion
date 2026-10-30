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
    OWNER_RIGHTS = bytes.fromhex("010100000000000304000000")
    CREATOR_OWNER = bytes.fromhex("010100000000000300000000")
    EVERYONE = bytes.fromhex("010100000000000100000000")
    USERS = bytes.fromhex("01020000000000052000000021020000")
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

    def test_owner_rights_only_applies_to_the_verified_current_owner(self):
        entries = [(0, 0x10, 0x1F01FF, self.OWNER_RIGHTS), (0, 0x10, 0x1F01FF, self.SYSTEM),
                   (0, 0x10, 0x1F01FF, self.ADMIN)]
        self.validate(entries)
        with self.assertRaises(privacy_guard.PrivacyError) as caught:
            self.validate(entries, owner=self.OTHER)
        self.assertEqual(caught.exception.category, "profile_permissions")

    def test_owner_rights_does_not_authorize_other_or_creator_principals(self):
        for principal in (self.CREATOR_OWNER, self.EVERYONE, self.USERS, self.OTHER):
            for flags in (0, 0x10):
                with self.subTest(flags=flags), self.assertRaises(privacy_guard.PrivacyError) as caught:
                    self.validate([(0, 0, 0x1F01FF, self.OWNER_RIGHTS), (0, flags, 0x1, principal)])
                self.assertEqual(caught.exception.category, "profile_permissions")

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

    def test_raw_windows_handle_path_does_not_reinterpret_it_as_a_crt_descriptor(self):
        import ctypes
        from types import SimpleNamespace
        names=('GetSecurityInfo','GetLengthSid','GetSecurityDescriptorLength','GetAclInformation','GetAce',
            'OpenProcessToken','GetTokenInformation')
        advapi=SimpleNamespace(**{name:mock.Mock(return_value=0) for name in names});advapi.GetSecurityInfo.return_value=1
        kernel=SimpleNamespace(**{name:mock.Mock(return_value=0) for name in ('GetCurrentProcess','CloseHandle','LocalFree')})
        crt=SimpleNamespace(get_osfhandle=mock.Mock(return_value=456))
        for raw,expected in ((True,123),(False,456)):
            with self.subTest(rawHandle=raw),mock.patch.dict(sys.modules,{'msvcrt':crt}),mock.patch.object(ctypes,'WinDLL',side_effect=lambda name,**kw:advapi if name=='advapi32' else kernel,create=True):
                with self.assertRaises(privacy_guard.PrivacyError):privacy_guard._windows_profile_security(123,os_handle=raw)
                self.assertEqual(advapi.GetSecurityInfo.call_args.args[0],expected)
                if raw:crt.get_osfhandle.assert_not_called()
                else:crt.get_osfhandle.assert_called_once_with(123)

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

    def test_native_directory_handle_dacl_is_checked_without_crt_conversion(self):
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.CreateFileW.argtypes=(ctypes.c_wchar_p,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE)
        api.CreateFileW.restype=wintypes.HANDLE;api.CloseHandle.argtypes=(wintypes.HANDLE,);api.CloseHandle.restype=wintypes.BOOL
        handle=api.CreateFileW(str(self.path.parent),0x20080,7,None,3,0x02200000,None)
        self.assertNotIn(handle,(None,ctypes.c_void_p(-1).value),'native_directory_handle_open_failed')
        try:
            self.assertTrue(privacy_guard._windows_profile_security(handle,os_handle=True))
            protect_private_path(self.path.parent,world_read=True)
            with self.assertRaises(privacy_guard.PrivacyError):privacy_guard._windows_profile_security(handle,os_handle=True)
        finally:api.CloseHandle(handle)

    def test_native_owner_only_profile_can_be_read_repeatedly(self):
        self.set_dacl()
        self.assertIsNotNone(privacy_guard.load_profile(required=True))
        self.assertIsNotNone(privacy_guard.load_profile(required=True))

    def test_native_world_read_profile_is_rejected(self):
        self.set_dacl(world_read=True)
        with self.assertRaises(privacy_guard.PrivacyError) as caught:
            privacy_guard.load_profile(required=True)
        self.assertEqual(caught.exception.category, "profile_permissions")

    def test_native_nested_mkdir_private_acl_is_accepted_without_rewriting_it(self):
        with current_user_owner():
            nested = self.path.parent / "private-directory"
            nested.mkdir(mode=0o700)
            inner = nested / "nested-directory"
            inner.mkdir(mode=0o700)
            profile = inner / "synthetic-profile.json"
            profile.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
            # Do not provision/rewrite this file's ACL: exercise CPython's
            # inherited OWNER RIGHTS grant with the unchanged native reader.
            with mock.patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile)}):
                self.assertIsNotNone(privacy_guard.load_profile(required=True))
                self.assertIsNotNone(privacy_guard.load_profile(required=True))

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
