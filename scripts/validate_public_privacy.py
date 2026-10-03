#!/usr/bin/env python3
"""Fail closed on private identifiers in selected public files and ZIPs.

Reports contain rule, relative file and line only, never matched content.
This is a mechanical release gate, not a claim that all personal data is detectable.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "manage-code-ontology" / "scripts"))
from privacy_guard import PrivacyError, ensure_public_safe, load_profile
PUBLISHER = "battle-doll"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
TEXT_SUFFIXES = {".py", ".java", ".xml", ".gradle", ".properties", ".js", ".mjs", ".json", ".md", ".txt", ".yaml", ".yml",
                 ".html", ".css", ".svg", ".ttl", ".toml", ".sha256", ".csv", ""}
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "example.test", "invalid", "test.invalid"}
HOME_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:[\\/]+Users[\\/]+)([^/\\\s<>\"'{}\[\]()|]+)(?=[\\/]|$)", re.I)
SYNTHETIC_HOME_USERS = {"user", "username", "example", "test-user", "alice", "bob", "private"}
PATTERNS = {
    "credential": re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "personal-phone": re.compile(r"(?<!\d)01[016789][- .]\d{3,4}[- .]\d{4}(?!\d)"),
    "government-identifier": re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)"),
    "private-project": re.compile(r"(?i)(?<![a-z0-9])" + "aeth" + r"er(?![a-z0-9])"),
}


def _safe_name(name: str) -> str:
    try:
        ensure_public_safe(name, context_roots=(ROOT,))
    except PrivacyError:
        return "<redacted-path>"
    if EMAIL.search(name) or HOME_PATH.search(name) or any(p.search(name) for p in PATTERNS.values()):
        return "<redacted-path>"
    return name


def _finding(rule: str, name: str, text: str = "", position: int = 0) -> dict:
    return {"rule": rule, "file": _safe_name(name), "line": text.count("\n", 0, position) + 1}


def scan_text(name: str, text: str) -> list[dict]:
    findings = []
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            findings.append(_finding(rule, name, text, match.start()))
    home = str(Path.home())
    if home not in {"/", "."}:
        for match in re.finditer(re.escape(home + "/"), text):
            findings.append(_finding("current-home-path", name, text, match.start()))
    for match in HOME_PATH.finditer(text):
        if match.group(1).lower() not in SYNTHETIC_HOME_USERS:
            findings.append(_finding("named-home-path", name, text, match.start()))
    for match in EMAIL.finditer(text):
        address = match.group(0)
        domain = address.rsplit("@", 1)[1].lower()
        if (domain not in SAFE_EMAIL_DOMAINS and not domain.endswith((".invalid", ".test", ".example"))
                and not re.fullmatch(r"(?:\d+\+)?" + re.escape(PUBLISHER) + r"@users\.noreply\.github\.com", address)):
            findings.append(_finding("non-synthetic-email", name, text, match.start()))
    try:
        # Source examples can contain generic local paths. The named-home rules
        # above still reject real users; the shared guard also decodes escaped
        # identifiers and applies the private local name/email profile.
        ensure_public_safe(text, context_roots=(ROOT,), allow_local_paths=True)
    except PrivacyError as exc:
        rule = {"personal_email": "non-synthetic-email", "secret_token": "credential",
                "denied_identity": "known-private-identity"}.get(exc.category, "private-profile-" + exc.category)
        if not any(finding["rule"] == rule for finding in findings):
            findings.append({"rule": rule, "file": _safe_name(name), "line": 0})
    return findings


def scan_bytes(name: str, data: bytes) -> list[dict]:
    if len(data) > MAX_FILE_BYTES:
        return [_finding("file-too-large", name)]
    if PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES:
        # Image pixels/compressed pixel streams are not text metadata. Inspect
        # bounded PNG ancillary chunks and JPEG application/comments instead.
        findings = []
        chunks, recognized = _binary_metadata(data)
        if not recognized:
            findings.append(_finding("unsupported-public-binary", name))
        for chunk in chunks:
            for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
                findings.extend(scan_text(name, chunk.decode(encoding, errors="ignore")))
        return list({(f["rule"], f["file"]): f for f in findings}.values())
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [_finding("invalid-public-text", name)]
    findings = scan_text(name, text)
    if PurePosixPath(name).suffix.lower() == ".json":
        try:
            pending = [json.loads(text)]
            while pending:
                value = pending.pop()
                if isinstance(value, str):
                    for finding in scan_text(name, value):
                        finding["line"] = 0  # Decoded JSON string; no raw line claim.
                        findings.append(finding)
                elif isinstance(value, dict):
                    pending.extend(value.keys()); pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
        except (ValueError, RecursionError):
            findings.append(_finding("invalid-public-json", name))
    if name.endswith("plugin.json"):
        try:
            manifest = json.loads(text)
            if manifest.get("author", {}).get("name") != PUBLISHER:
                findings.append(_finding("publisher-identity", name))
            if manifest.get("author", {}).get("email"):
                findings.append(_finding("publisher-email", name))
            if manifest.get("interface", {}).get("developerName") != PUBLISHER:
                findings.append(_finding("developer-identity", name))
        except (ValueError, TypeError, AttributeError):
            findings.append(_finding("invalid-public-manifest", name))
    return findings


def _binary_metadata(data: bytes) -> tuple[list[bytes], bool]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        chunks, offset, ended = [], 8, False
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            stop = offset + 12 + size
            if size > MAX_FILE_BYTES or stop > len(data):
                return chunks, False
            payload = data[offset + 8:stop - 4]
            if kind not in {b"IDAT", b"IHDR", b"IEND", b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs"}:
                chunks.append(payload)
                if kind == b"zTXt":
                    parts = payload.split(b"\0", 1)
                    if len(parts) != 2 or not parts[1] or parts[1][0] != 0:
                        return chunks, False
                    try:
                        decompressor = zlib.decompressobj()
                        decoded = decompressor.decompress(parts[1][1:], MAX_FILE_BYTES + 1)
                        if len(decoded) > MAX_FILE_BYTES or not decompressor.eof:
                            return chunks, False
                        chunks.append(decoded)
                    except zlib.error:
                        return chunks, False
                if kind == b"iTXt":
                    parts = payload.split(b"\0", 1)
                    if len(parts) != 2 or len(parts[1]) < 2:
                        return chunks, False
                    flags, rest = parts[1][:2], parts[1][2:]
                    fields = rest.split(b"\0", 2)
                    if len(fields) != 3 or flags[0] not in {0, 1} or flags[1] != 0:
                        return chunks, False
                    if flags[0] == 1:
                        try:
                            decompressor = zlib.decompressobj()
                            decoded = decompressor.decompress(fields[2], MAX_FILE_BYTES + 1)
                            if len(decoded) > MAX_FILE_BYTES or not decompressor.eof:
                                return chunks, False
                            chunks.append(decoded)
                        except zlib.error:
                            return chunks, False
            offset = stop
            if kind == b"IEND":
                ended = offset == len(data)
                break
        return chunks, ended
    if data.startswith(b"\xff\xd8"):
        chunks, offset = [], 2
        while offset + 2 <= len(data):
            if data[offset] != 255:
                return chunks, False
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                return chunks, False
            kind = data[offset]; offset += 1
            if kind == 0xD9:
                return chunks, offset == len(data)
            if kind == 0xDA:
                return chunks, data.endswith(b"\xff\xd9")
            if kind in {0x01, *range(0xD0, 0xD9)}:
                continue
            if offset + 2 > len(data):
                return chunks, False
            size = int.from_bytes(data[offset:offset + 2], "big")
            if size < 2 or offset + size > len(data):
                return chunks, False
            if kind in {0xFE, *range(0xE0, 0xF0)}:
                chunks.append(data[offset + 2:offset + size])
            offset += size
        return chunks, False
    # Unsupported binary formats fail closed; still check readable metadata so
    # the private name rule can be reported without disclosing the input.
    return [data], False


def scan_source(root: Path) -> tuple[list[dict], int]:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root, stderr=subprocess.PIPE
    ).decode().split("\0")
    findings = []
    total = count = 0
    for name in sorted(set(p for p in paths if p)):
        name_findings = scan_text("<source-name>", name)
        if name_findings:
            findings.extend(name_findings)
            continue
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue  # Tracked deletions are not part of the candidate tree.
        if path.is_symlink() or not path.is_file():
            findings.append(_finding("non-regular-public-file", name)); continue
        size = path.stat().st_size
        total += size
        count += 1
        if total > MAX_TOTAL_BYTES:
            findings.append(_finding("source-too-large", "<source>")); break
        if size > MAX_FILE_BYTES:
            findings.append(_finding("file-too-large", name)); continue
        findings.extend(scan_bytes(name, path.read_bytes()))
    return findings, count


def scan_zip(path: Path) -> tuple[list[dict], int]:
    findings = []
    count = total = 0
    with zipfile.ZipFile(path) as archive:
        findings.extend(scan_bytes("<archive-comment>.txt", archive.comment))
        if len(archive.infolist()) > 512:
            return [_finding("too-many-entries", "<archive>")], 0
        seen = set()
        for entry in archive.infolist():
            name = entry.filename
            relative = PurePosixPath(name)
            count += 1
            if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                findings.append(_finding("unsafe-entry-path", "<archive>")); continue
            if name.casefold() in seen:
                findings.append(_finding("duplicate-entry", "<archive>")); continue
            seen.add(name.casefold())
            findings.extend(scan_bytes("<entry-comment>.txt", entry.comment))
            if stat.S_ISLNK(entry.external_attr >> 16):
                findings.append(_finding("archive-link", name)); continue
            total += entry.file_size
            if total > MAX_TOTAL_BYTES or entry.file_size > MAX_FILE_BYTES:
                findings.append(_finding("archive-too-large", "<archive>")); break
            findings.extend(scan_text("<entry-name>", name))
            if not entry.is_dir():
                findings.extend(scan_bytes(name, archive.read(entry)))
    return findings, count


def scan_git_identity(root: Path) -> list[dict]:
    identities = subprocess.check_output(
        ["git", "log", "--all", "--format=%an%x00%ae%x00%cn%x00%ce"], cwd=root, stderr=subprocess.PIPE
    ).decode().splitlines()
    findings = []
    for number, identity in enumerate(identities, 1):
        values = identity.split("\0")
        if len(values) != 4:
            findings.append(_finding("invalid-git-identity", "<git-history>")); continue
        for name, email in ((values[0], values[1]), (values[2], values[3])):
            public_bot = name == "GitHub" and email in {"noreply" + "@github.com", "web-flow" + "@github.com"}
            if name != PUBLISHER and not public_bot:
                findings.append({"rule": "git-name", "file": "<git-history>", "line": number})
            pseudonymous = bool(re.fullmatch(r"(?:\d+\+)?" + re.escape(PUBLISHER) + r"@users\.noreply\.github\.com", email))
            if not pseudonymous and not public_bot:
                findings.append({"rule": "git-email", "file": "<git-history>", "line": number})
    messages = subprocess.check_output(["git", "log", "--all", "--format=%B"], cwd=root, stderr=subprocess.PIPE).decode()
    findings.extend(scan_text("<git-messages>", messages))
    refs = subprocess.check_output(["git", "for-each-ref", "--format=%(refname)%00%(taggername)%00%(taggeremail)"], cwd=root, stderr=subprocess.PIPE).decode().splitlines()
    for number, entry in enumerate(refs, 1):
        values = entry.split("\0")
        if len(values) != 3:
            findings.append(_finding("invalid-git-ref", "<git-refs>")); continue
        findings.extend(scan_text("<git-ref-name>", values[0]))
        name, email = values[1], values[2].strip("<>")
        if name or email:
            if name != PUBLISHER or not re.fullmatch(r"(?:\d+\+)?" + re.escape(PUBLISHER) + r"@users\.noreply\.github\.com", email):
                findings.append({"rule": "git-tagger-identity", "file": "<git-tags>", "line": number})
    return findings


def scan_directory(root: Path) -> tuple[list[dict], int]:
    """Scan a selected generated artifact tree; do not follow links."""
    findings, count, total = [], 0, 0
    if root.is_symlink() or not root.is_dir():
        return [_finding("non-regular-public-directory", "<directory>")], 0
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            name = path.relative_to(root).as_posix()
            findings.extend(scan_text("<generated-name>", name))
            if path.is_symlink():
                findings.append(_finding("generated-link", name)); continue
            if path.is_dir():
                pending.append(path); continue
            if not path.is_file():
                findings.append(_finding("non-regular-public-file", name)); continue
            count += 1
            total += path.stat().st_size
            if count > 4096 or total > MAX_TOTAL_BYTES:
                return findings + [_finding("directory-too-large", "<directory>")], count
            if path.stat().st_size > MAX_FILE_BYTES:
                findings.append(_finding("file-too-large", name)); continue
            if path.suffix.lower() == ".zip":
                current, _entries = scan_zip(path)
                findings.extend(current)
            else:
                findings.extend(scan_bytes(name, path.read_bytes()))
    return findings, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true")
    parser.add_argument("--git-history", action="store_true")
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--directory", type=Path, action="append", default=[])
    parser.add_argument("--require-private-profile", action="store_true",
                        help="Require the local known-name/email deny profile before publication checks.")
    args = parser.parse_args()
    if not args.source and not args.git_history and not args.archive and not args.directory:
        parser.error("Select source, git history, archive or generated directory")
    findings = []
    checked = {}
    try:
        profile = load_profile((ROOT,), required=args.require_private_profile)
        if args.require_private_profile and (not profile["denyNames"] or not profile["denyEmails"]):
            raise PrivacyError("profile_identity_required")
        checked["knownIdentityProfile"] = profile is not None
        if args.source:
            current, checked["sourceFiles"] = scan_source(ROOT); findings.extend(current)
        if args.git_history:
            findings.extend(scan_git_identity(ROOT)); checked["gitHistory"] = True
        for archive in args.archive:
            current, count = scan_zip(archive); findings.extend(current)
            checked[_safe_name(archive.name)] = count
        for directory in args.directory:
            current, count = scan_directory(directory); findings.extend(current)
            checked[_safe_name(directory.name)] = count
    except PrivacyError as exc:
        findings.append(_finding("private-profile-" + exc.category, "<profile>"))
    except (OSError, ValueError, RuntimeError, RecursionError, EOFError, zipfile.BadZipFile, zlib.error, UnicodeError, subprocess.SubprocessError):
        findings.append(_finding("unreadable-public-input", "<input>"))
    print(json.dumps({"status": "FAIL" if findings else "PASS", "checked": checked,
                      "findings": findings}, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
