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


def load_profile(context_roots: Iterable[str | Path] = (), required: bool = False) -> dict[str, Any] | None:
    """Read afresh on every call. POSIX modes are checked; Windows ACLs are not."""
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
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PrivacyError("profile_file")
        if os.name != "nt" and (info.st_mode & 0o077 or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            raise PrivacyError("profile_permissions")
        if not 1 <= info.st_size <= MAX_PROFILE_BYTES:
            raise PrivacyError("profile_size")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                raise PrivacyError("profile_changed")
            content = handle.read(MAX_PROFILE_BYTES + 1)
            after = os.fstat(handle.fileno())
        if len(content) > MAX_PROFILE_BYTES or (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise PrivacyError("profile_changed")
        for ancestor in (path, *path.parents):
            if _link_like(ancestor.lstat()):
                raise PrivacyError("profile_link")
        final = path.lstat()
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
                       context_roots: Iterable[str | Path] = (), *, allow_local_paths: bool = False) -> None:
    """Reject the entire output before return/write; never remove evidence fields."""
    profile = load_profile(context_roots) if profile is None else _validated_profile(profile)
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
