#!/usr/bin/env python3
"""Run CI validation with genuine current-user ownership and private temp ACLs.

This is test infrastructure, not a runtime permissions bypass. Elevated Windows
CI tokens may default new file owners to Administrators. Configure the ordinary
current-user owner for the validation child, then restore the prior token owner.
The production open-handle owner/DACL checks remain unchanged and active.
Native identities are transient bytes only; diagnostics contain booleans/enums.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


class WindowsValidationError(RuntimeError):
    pass


class WindowsSecurity:
    """Small native-only helper shared by synthetic permission fixtures."""

    def __init__(self):
        if os.name != "nt":
            raise WindowsValidationError("windows_validation_platform_required")
        import ctypes
        from ctypes import wintypes
        self.c, self.w = ctypes, wintypes
        self.a = ctypes.WinDLL("advapi32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        p, d = ctypes.c_void_p, wintypes.DWORD
        self.a.OpenProcessToken.argtypes = [wintypes.HANDLE, d, ctypes.POINTER(wintypes.HANDLE)]
        self.a.OpenProcessToken.restype = wintypes.BOOL
        self.a.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, p, d, ctypes.POINTER(d)]
        self.a.GetTokenInformation.restype = wintypes.BOOL
        self.a.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, p, d]
        self.a.SetTokenInformation.restype = wintypes.BOOL
        self.a.GetLengthSid.argtypes = [p]
        self.a.GetLengthSid.restype = d
        self.a.InitializeAcl.argtypes = [p, d, d]
        self.a.InitializeAcl.restype = wintypes.BOOL
        self.a.AddAccessAllowedAceEx.argtypes = [p, d, d, d, p]
        self.a.AddAccessAllowedAceEx.restype = wintypes.BOOL
        self.a.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, d, p, p, p, p]
        self.a.SetNamedSecurityInfoW.restype = d
        self.k.GetCurrentProcess.argtypes = []
        self.k.GetCurrentProcess.restype = wintypes.HANDLE
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k.CloseHandle.restype = wintypes.BOOL
        self.token = wintypes.HANDLE()
        # TOKEN_QUERY | TOKEN_ADJUST_DEFAULT, without changing group privileges.
        if not self.a.OpenProcessToken(self.k.GetCurrentProcess(), 0x0088, ctypes.byref(self.token)):
            raise WindowsValidationError("windows_validation_token_open_failed")

    def close(self):
        if self.token.value:
            self.k.CloseHandle(self.token)
            self.token = self.w.HANDLE()

    def token_sid(self, information_class):
        needed = self.w.DWORD()
        self.a.GetTokenInformation(self.token, information_class, None, 0, self.c.byref(needed))
        if not 0 < needed.value <= 65536:
            raise WindowsValidationError("windows_validation_token_size_invalid")
        buffer = self.c.create_string_buffer(needed.value)
        if not self.a.GetTokenInformation(self.token, information_class, buffer, needed.value, self.c.byref(needed)):
            raise WindowsValidationError("windows_validation_token_read_failed")
        sid = self.c.cast(buffer, self.c.POINTER(self.c.c_void_p))[0]
        size = self.a.GetLengthSid(sid) if sid else 0
        if not 8 <= size <= 68:
            raise WindowsValidationError("windows_validation_sid_invalid")
        return self.c.string_at(sid, size)

    def set_token_owner(self, sid):
        # TOKEN_OWNER is one pointer; SID bytes must outlive SetTokenInformation.
        buffer = self.c.create_string_buffer(sid)
        owner = self.c.c_void_p(self.c.addressof(buffer))
        if not self.a.SetTokenInformation(self.token, 4, self.c.byref(owner), self.c.sizeof(owner)):
            raise WindowsValidationError("windows_validation_owner_set_failed")
        if self.token_sid(4) != sid:
            raise WindowsValidationError("windows_validation_owner_readback_failed")

    def protect(self, path, *, world_read=False):
        path = Path(path)
        info = path.lstat()
        directory = stat.S_ISDIR(info.st_mode)
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or not (directory or stat.S_ISREG(info.st_mode))
                or (not directory and info.st_nlink != 1)):
            raise WindowsValidationError("windows_fixture_path_invalid")
        user = self.token_sid(1)
        principals = [user, bytes.fromhex("010100000000000512000000"),
                      bytes.fromhex("01020000000000052000000020020000")]
        if world_read:
            principals.append(bytes.fromhex("010100000000000100000000"))
        buffers = [self.c.create_string_buffer(value) for value in principals]
        acl = self.c.create_string_buffer(1024)
        if not self.a.InitializeAcl(acl, len(acl), 2):
            raise WindowsValidationError("windows_fixture_acl_init_failed")
        for index, principal in enumerate(buffers):
            mask = 0x120089 if world_read and index == 3 else 0x1F01FF
            if not self.a.AddAccessAllowedAceEx(acl, 2, 0x03 if directory else 0, mask, principal):
                raise WindowsValidationError("windows_fixture_acl_entry_failed")
        # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | PROTECTED_DACL.
        if self.a.SetNamedSecurityInfoW(str(path), 1, 0x80000005, buffers[0], None, acl, None):
            raise WindowsValidationError("windows_fixture_acl_set_failed")


@contextmanager
def current_user_owner():
    security = WindowsSecurity()
    previous = None
    try:
        previous = security.token_sid(4)
        security.set_token_owner(security.token_sid(1))
        yield security
    finally:
        try:
            if previous is not None:
                security.set_token_owner(previous)
        finally:
            security.close()


def protect_private_path(path, *, world_read=False):
    """Provision real private fixture permissions; never bypass verification."""
    path = Path(path)
    if os.name == "nt":
        security = WindowsSecurity()
        try:
            security.protect(path, world_read=world_read)
        finally:
            security.close()
    else:
        path.chmod(0o755 if world_read and path.is_dir() else 0o644 if world_read else 0o700 if path.is_dir() else 0o600)


def main():
    result = 1
    entered = False
    try:
        with current_user_owner() as security:
            entered = True
            with tempfile.TemporaryDirectory(prefix="code-ontology-windows-validation-") as temporary:
                security.protect(temporary)
                # Verify real inherited file permissions before starting tests.
                # This imports the unchanged production check, never a mock.
                root = Path(__file__).resolve().parents[1]
                sys.path.insert(0, str(root / "skills/manage-code-ontology/scripts"))
                import privacy_guard
                probe = Path(temporary) / "permission-check"
                descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    privacy_guard._check_private_file_metadata(os.fstat(descriptor))
                    privacy_guard._windows_profile_security(descriptor)
                except privacy_guard.PrivacyError:
                    raise WindowsValidationError("windows_validation_inherited_permissions_invalid") from None
                finally:
                    os.close(descriptor)
                    probe.unlink()
                environment = dict(os.environ, TEMP=temporary, TMP=temporary, PYTHONUTF8="1")
                print(json.dumps({"validationEnvironment": "windows_current_user_private_temp",
                                  "ownerReadbackVerified": True, "privateTempAclProvisioned": True,
                                  "inheritedFilePermissionsVerified": True}), flush=True)
                result = subprocess.run([sys.executable, str(root / "scripts/validate_package.py")],
                                        cwd=root, env=environment, check=False).returncode
        print(json.dumps({"defaultOwnerRestored": True, "validationPassed": result == 0}), flush=True)
    except (WindowsValidationError, OSError):
        print(json.dumps({"validationEnvironmentFailed": True, "ownerScopeEntered": entered}), flush=True)
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
