"""Fail-closed public-output guard using a private, hashed local deny profile.

No network, target execution, identity lookup, or automatic full-name detection.
Known names/emails need an explicitly configured deny profile. Generic checks
cover email-shaped values, common home paths and recognizable secret tokens.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import stat
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


PROFILE_ENV = "CODE_ONTOLOGY_PRIVACY_FILE"
MAX_PROFILE_BYTES = 64 * 1024
MAX_IDENTITIES = 256
MAX_IDENTITY_CHARS = 120
MAX_DECODE_ROUNDS = 3
ALLOWED_PUBLIC_EMAIL = "battle-doll@users.noreply.github.com"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_NAME_STRIP_RE = re.compile(r"[\W_]")
_EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^_`{|}~-]{1,64}@[\w](?:[\w.-]{0,251}[\w])?\.[^\W\d_]{2,63}")
_HOME_RE = re.compile(r"(?:/(?:Users|home)/[^/\s<>\"']+|/root(?:/|(?=$|[\s<>\"']))|(?:[A-Za-z]:)?[\\/]+Users[\\/]+[^\\/\s<>\"']+)", re.IGNORECASE)
_SECRET_RE = re.compile(r"(?:\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}|\bAKIA[A-Z0-9]{16}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})|\\x([0-9a-fA-F]{2})")
_CATEGORIES = frozenset({"privacy_failure", "profile_schema", "profile_required", "profile_boundary",
                         "profile_link", "profile_file", "profile_permissions", "profile_size",
                         "profile_changed", "profile_unreadable", "unsupported_payload", "denied_identity",
                         "personal_email", "private_home_path", "secret_token", "encoding_depth", "private_profile_material"})


class PrivacyError(ValueError):
    """A bounded diagnostic which never contains inspected text or file paths."""
    def __init__(self, category: str):
        self.category = category if category in _CATEGORIES else "privacy_failure"
        super().__init__("Public privacy guard rejected output: " + self.category + ".")


def _name(value: str) -> str:
    # Python Unicode word characters are letters/numbers plus underscore.
    return _NAME_STRIP_RE.sub("", unicodedata.normalize("NFKC", value).casefold())


def _remove_format(value: str) -> str:
    if value.isascii():
        return value
    mapping = {ord(character): None for character in set(value) if unicodedata.category(character) == "Cf"}
    return value.translate(mapping) if mapping else value


def _email(value: str) -> str:
    return _remove_format(unicodedata.normalize("NFKC", value).casefold()).strip()


def _identity_digest(key: bytes, kind: str, value: str) -> str:
    return hmac.new(key, ("code-ontology-privacy/" + kind + "/" + value).encode("utf-8"), hashlib.sha256).hexdigest()


def build_profile(names: Iterable[str], emails: Iterable[str], key: bytes | None = None) -> dict[str, Any]:
    """Return only keyed digests; inputs are transient and never printed/stored."""
    if isinstance(names, (str, bytes)) or isinstance(emails, (str, bytes)):
        raise PrivacyError("profile_schema")
    key = secrets.token_bytes(32) if key is None else key
    if not isinstance(key, bytes) or len(key) != 32:
        raise PrivacyError("profile_schema")
    result: dict[str, Any] = {"schemaVersion": 1, "algorithm": "hmac-sha256",
                              "key": base64.urlsafe_b64encode(key).decode("ascii").rstrip("="),
                              "denyNames": [], "denyEmails": []}
    for kind, values, minimum in (("name", names, 2), ("email", emails, 3)):
        rows = set()
        try:
            for value in values:
                if not isinstance(value, str):
                    raise PrivacyError("profile_schema")
                normalized = _name(value) if kind == "name" else _email(value)
                if not minimum <= len(normalized) <= MAX_IDENTITY_CHARS:
                    raise PrivacyError("profile_schema")
                if kind == "email" and not _EMAIL_RE.fullmatch(normalized):
                    raise PrivacyError("profile_schema")
                rows.add((len(normalized), _identity_digest(key, kind, normalized),
                          _identity_digest(key, "initial", normalized[0]) if kind == "name" else None))
                if len(rows) > MAX_IDENTITIES:
                    raise PrivacyError("profile_schema")
        except (TypeError, UnicodeError):
            raise PrivacyError("profile_schema") from None
        result["denyNames" if kind == "name" else "denyEmails"] = [
            {"chars": length, "digest": digest, **({"prefixDigest": prefix} if prefix else {})}
            for length, digest, prefix in sorted(rows)
        ]
    return result


def _validated_profile(value: Any) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {"schemaVersion", "algorithm", "key", "denyNames", "denyEmails"}
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1
            or value.get("algorithm") != "hmac-sha256"):
        raise PrivacyError("profile_schema")
    encoded = value.get("key")
    if not isinstance(encoded, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded):
        raise PrivacyError("profile_schema")
    try:
        key = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise PrivacyError("profile_schema") from None
    if len(key) != 32:
        raise PrivacyError("profile_schema")
    for field, minimum in (("denyNames", 2), ("denyEmails", 3)):
        rows = value.get(field)
        if not isinstance(rows, list) or len(rows) > MAX_IDENTITIES:
            raise PrivacyError("profile_schema")
        for row in rows:
            if (not isinstance(row, dict) or set(row) not in ({"chars", "digest"}, {"chars", "digest", "prefixDigest"})
                    or type(row.get("chars")) is not int or not minimum <= row["chars"] <= MAX_IDENTITY_CHARS
                    or not isinstance(row.get("digest"), str) or not _DIGEST_RE.fullmatch(row["digest"])
                    or ("prefixDigest" in row and (field != "denyNames" or not isinstance(row["prefixDigest"], str)
                                                    or not _DIGEST_RE.fullmatch(row["prefixDigest"])))):
                raise PrivacyError("profile_schema")
    return value


def _link_like(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_windows_acl(owner: bytes, user: bytes, entries: list[tuple[int, int, int, bytes]] | None) -> None:
    """Conservative DACL policy: current owner, no grants to other principals.

    Local System and the built-in Administrators group are operating-system
    principals. OWNER RIGHTS denotes this object's already-verified owner (and
    is emitted by CPython's Windows mkdir(0o700)); it is not CREATOR OWNER.
    Arbitrary groups, callback/object ACEs and null DACLs fail closed.
    Raw SIDs are inspected transiently and never appear in diagnostics.
    """
    system_sid = bytes.fromhex("010100000000000512000000")
    administrators_sid = bytes.fromhex("01020000000000052000000020020000")
    owner_rights_sid = bytes.fromhex("010100000000000304000000")  # S-1-3-4
    if not owner or not user or owner != user or entries is None:
        raise PrivacyError("profile_permissions")
    for ace_type, flags, mask, principal in entries:
        if ace_type not in (0, 1):  # ACCESS_ALLOWED_ACE / ACCESS_DENIED_ACE only.
            raise PrivacyError("profile_permissions")
        if ace_type == 0 and mask and not flags & 0x08:  # INHERIT_ONLY_ACE is not effective here.
            if principal not in (user, system_sid, administrators_sid, owner_rights_sid):
                raise PrivacyError("profile_permissions")


def _windows_profile_security(descriptor: int) -> bytes:
    """Check the actual open handle and return a transient descriptor fingerprint."""
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p
        dword = wintypes.DWORD
        advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, dword, ctypes.POINTER(pointer),
                                         ctypes.POINTER(pointer), ctypes.POINTER(pointer), ctypes.POINTER(pointer),
                                         ctypes.POINTER(pointer)]
        advapi.GetSecurityInfo.restype = dword
        advapi.GetLengthSid.argtypes = [pointer]
        advapi.GetLengthSid.restype = dword
        advapi.GetSecurityDescriptorLength.argtypes = [pointer]
        advapi.GetSecurityDescriptorLength.restype = dword
        advapi.GetAclInformation.argtypes = [pointer, pointer, dword, ctypes.c_int]
        advapi.GetAclInformation.restype = wintypes.BOOL
        advapi.GetAce.argtypes = [pointer, dword, ctypes.POINTER(pointer)]
        advapi.GetAce.restype = wintypes.BOOL
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, dword, ctypes.POINTER(wintypes.HANDLE)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, pointer, dword, ctypes.POINTER(dword)]
        advapi.GetTokenInformation.restype = wintypes.BOOL
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [pointer]
        kernel.LocalFree.restype = pointer
        owner, dacl, security = pointer(), pointer(), pointer()
        if advapi.GetSecurityInfo(msvcrt.get_osfhandle(descriptor), 1, 0x1 | 0x4,
                                  ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(security)):
            raise PrivacyError("profile_permissions")
        token = wintypes.HANDLE()
        try:
            if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)):
                raise PrivacyError("profile_permissions")
            needed = dword()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if not 0 < needed.value <= 65536:
                raise PrivacyError("profile_permissions")
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token, 1, buffer, needed.value, ctypes.byref(needed)):
                raise PrivacyError("profile_permissions")
            user = ctypes.cast(buffer, ctypes.POINTER(pointer))[0]

            def sid_bytes(value):
                if not value:
                    raise PrivacyError("profile_permissions")
                size = advapi.GetLengthSid(value)
                if not 8 <= size <= 68:
                    raise PrivacyError("profile_permissions")
                return ctypes.string_at(value, size)

            entries = None
            if dacl.value:
                sizes = (dword * 3)()
                if not advapi.GetAclInformation(dacl, sizes, ctypes.sizeof(sizes), 2) or sizes[0] > 4096:
                    raise PrivacyError("profile_permissions")
                entries = []
                for index in range(sizes[0]):
                    ace = pointer()
                    if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
                        raise PrivacyError("profile_permissions")
                    header = ctypes.string_at(ace, 4)
                    ace_type, flags = header[0], header[1]
                    size = int.from_bytes(header[2:4], "little")
                    if ace_type not in (0, 1) or size < 16:
                        raise PrivacyError("profile_permissions")
                    mask = int.from_bytes(ctypes.string_at(ace.value + 4, 4), "little")
                    principal = sid_bytes(ace.value + 8)
                    if len(principal) + 8 > size:
                        raise PrivacyError("profile_permissions")
                    entries.append((ace_type, flags, mask, principal))
            _validate_windows_acl(sid_bytes(owner), sid_bytes(user), entries)
            size = advapi.GetSecurityDescriptorLength(security)
            if not 20 <= size <= 1024 * 1024:
                raise PrivacyError("profile_permissions")
            # Hash self-contained owner/DACL facts, not pointer-bearing descriptor
            # memory, so repeated GetSecurityInfo allocations compare consistently.
            payload = repr((sid_bytes(owner), entries)).encode("ascii")
            return hashlib.sha256(payload).digest()
        finally:
            if token.value:
                kernel.CloseHandle(token)
            if security.value:
                kernel.LocalFree(security)
    except PrivacyError:
        raise
    except (OSError, ImportError, AttributeError, ValueError, TypeError):
        raise PrivacyError("profile_permissions") from None


def _check_private_file_metadata(info: os.stat_result) -> None:
    if _link_like(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PrivacyError("profile_file")
    if os.name != "nt" and (info.st_mode & 0o077 or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
        raise PrivacyError("profile_permissions")


def load_profile(context_roots: Iterable[str | Path] = (), required: bool = False) -> dict[str, Any] | None:
    """Read afresh; verify POSIX ownership/modes or the open Windows handle DACL."""
    configured = os.environ.get(PROFILE_ENV)
    if not configured:
        if required:
            raise PrivacyError("profile_required")
        return None
    try:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise PrivacyError("profile_boundary")
        for ancestor in (path, *path.parents):
            if _link_like(ancestor.lstat()):
                raise PrivacyError("profile_link")
        resolved = path.resolve(strict=True)
        if any(_inside(resolved, Path(root).expanduser().resolve()) for root in context_roots):
            raise PrivacyError("profile_boundary")
        info = path.lstat()
        _check_private_file_metadata(info)
        if not 1 <= info.st_size <= MAX_PROFILE_BYTES:
            raise PrivacyError("profile_size")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            _check_private_file_metadata(opened)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                raise PrivacyError("profile_changed")
            security_before = _windows_profile_security(handle.fileno()) if os.name == "nt" else None
            content = handle.read(MAX_PROFILE_BYTES + 1)
            if os.name == "nt" and _windows_profile_security(handle.fileno()) != security_before:
                raise PrivacyError("profile_changed")
            after = os.fstat(handle.fileno())
            _check_private_file_metadata(after)
        if len(content) > MAX_PROFILE_BYTES or (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise PrivacyError("profile_changed")
        for ancestor in (path, *path.parents):
            if _link_like(ancestor.lstat()):
                raise PrivacyError("profile_link")
        final = path.lstat()
        _check_private_file_metadata(final)
        if (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise PrivacyError("profile_changed")
        return _validated_profile(json.loads(content.decode("utf-8")))
    except PrivacyError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise PrivacyError("profile_unreadable") from None


def _strings(payload: Any, visited: set[int] | None = None):
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, bytes):
        try:
            yield payload.decode("utf-8")
        except UnicodeError:
            raise PrivacyError("unsupported_payload") from None
    elif isinstance(payload, (dict, list, tuple)):
        visited = set() if visited is None else visited
        identity = id(payload)
        if identity in visited:
            raise PrivacyError("unsupported_payload")
        visited.add(identity)
        if isinstance(payload, dict):
            for key, value in payload.items():
                if not isinstance(key, str):
                    raise PrivacyError("unsupported_payload")
                yield key
                yield from _strings(value, visited)
        else:
            for value in payload:
                yield from _strings(value, visited)
        visited.remove(identity)
    elif payload is not None and not isinstance(payload, (bool, int, float)):
        raise PrivacyError("unsupported_payload")


def _decode_once(value: str) -> str:
    decoded = html.unescape(unquote(value, encoding="utf-8", errors="replace"))
    def character(match):
        number = int(next(group for group in match.groups() if group is not None), 16)
        return chr(number) if number <= 0x10FFFF else match.group(0)
    return _UNICODE_ESCAPE_RE.sub(character, decoded)


def _variants(value: str):
    yield value
    for _ in range(MAX_DECODE_ROUNDS):
        decoded = _decode_once(value)
        if decoded == value:
            return
        yield decoded
        value = decoded
    if _decode_once(value) != value:
        raise PrivacyError("encoding_depth")


def _allowed_email(value: str) -> bool:
    if re.fullmatch(r"(?:[0-9]+\+)?battle-doll@users\.noreply\.github\.com", value):
        return True
    domain = value.rsplit("@", 1)[-1]
    return (domain in {"example.com", "example.net", "example.org"}
            or domain.endswith((".example", ".test", ".invalid")))


def _scan(value: str, key: bytes | None, names: dict[int, set[str]], emails: set[str], allow_local_paths: bool,
          prefixes: dict[int, set[str]], legacy_lengths: set[int], private_material: tuple[str, ...]):
    for variant in _variants(value):
        email_text = _remove_format(unicodedata.normalize("NFKC", variant))
        folded = email_text.casefold() if private_material else ""
        if any(material.casefold() in folded for material in private_material):
            raise PrivacyError("private_profile_material")
        normalized = _name(variant) if names else ""
        initial_cache = ({character: _identity_digest(key, "initial", character) for character in set(normalized)}
                         if prefixes else {})
        for length, denied in names.items():
            cache = set()
            if length in legacy_lengths:
                offsets = range(max(0, len(normalized) - length + 1))
            else:
                initials = {character for character, digest in initial_cache.items() if digest in prefixes[length]}
                if not initials:
                    continue
                candidates = re.finditer("[" + re.escape("".join(sorted(initials))) + "]", normalized)
                offsets = (match.start() for match in candidates if match.start() + length <= len(normalized))
            for offset in offsets:
                atom = normalized[offset:offset + length]
                if atom in cache:
                    continue
                if _identity_digest(key, "name", atom) in denied:
                    raise PrivacyError("denied_identity")
                if len(cache) >= 8192:
                    cache.clear()
                cache.add(atom)
        for match in (_EMAIL_RE.finditer(email_text) if "@" in email_text else ()):
            address = _email(match.group(0))
            if key is not None and _identity_digest(key, "email", address) in emails:
                raise PrivacyError("denied_identity")
            if not _allowed_email(address):
                raise PrivacyError("personal_email")
        if not allow_local_paths and _HOME_RE.search(email_text):
            raise PrivacyError("private_home_path")
        if _SECRET_RE.search(email_text):
            raise PrivacyError("secret_token")


def ensure_public_safe(payload: Any, profile: dict[str, Any] | None = None,
                       context_roots: Iterable[str | Path] = (), *, allow_local_paths: bool = False,
                       require_profile: bool = False) -> None:
    """Reject the entire output before return/write; never remove evidence fields."""
    profile = load_profile(context_roots, required=require_profile) if profile is None else _validated_profile(profile)
    if require_profile and not (profile and (profile["denyNames"] or profile["denyEmails"])):
        raise PrivacyError("profile_required")
    key, names, emails, prefixes, legacy_lengths = None, {}, set(), {}, set()
    private_material = ()
    if profile is not None:
        private_material = tuple({profile["key"], *(row["digest"] for field in ("denyNames", "denyEmails") for row in profile[field]),
                                  *(row["prefixDigest"] for row in profile["denyNames"] if "prefixDigest" in row)})
        key = base64.urlsafe_b64decode(profile["key"] + "=")
        for row in profile["denyNames"]:
            names.setdefault(row["chars"], set()).add(row["digest"])
            if "prefixDigest" in row:
                prefixes.setdefault(row["chars"], set()).add(row["prefixDigest"])
            else:
                legacy_lengths.add(row["chars"])
        emails = {row["digest"] for row in profile["denyEmails"]}
    for value in _strings(payload):
        _scan(value, key, names, emails, allow_local_paths, prefixes, legacy_lengths, private_material)


assert_public_safe = ensure_public_safe


def safe_error_message(value: Any, *, allow_local_paths: bool = True) -> str:
    """Keep ordinary local diagnostics while suppressing inspected identities."""
    if isinstance(value, PrivacyError):
        return str(value)
    text = str(value)
    try:
        ensure_public_safe(text, allow_local_paths=allow_local_paths)
    except PrivacyError:
        return "The local ontology request was rejected by the privacy guard."
    return text
