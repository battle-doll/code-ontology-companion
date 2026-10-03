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
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = "battle-doll"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".json", ".md", ".txt", ".yaml", ".yml",
                 ".html", ".css", ".svg", ".ttl", ".toml", ""}
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
        if (domain not in SAFE_EMAIL_DOMAINS and not domain.endswith(".invalid")
                and address != PUBLISHER + "@users.noreply.github.com"):
            findings.append(_finding("non-synthetic-email", name, text, match.start()))
    return findings


def scan_bytes(name: str, data: bytes) -> list[dict]:
    if len(data) > MAX_FILE_BYTES:
        return [_finding("file-too-large", name)]
    if PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES:
        # Binary images may have identifying EXIF/text chunks; fixed release icons
        # have separate exact-content checks in the artifact validator.
        for token in (str(Path.home()).encode(), b"-----BEGIN " + b"PRIVATE KEY-----"):
            if token and token in data:
                return [_finding("private-binary-metadata", name)]
        return []
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


def scan_source(root: Path) -> tuple[list[dict], int]:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
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
        ["git", "log", "HEAD", "--format=%an%x00%ae%x00%cn%x00%ce"], cwd=root
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
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true")
    parser.add_argument("--git-history", action="store_true")
    parser.add_argument("--archive", type=Path, action="append", default=[])
    args = parser.parse_args()
    if not args.source and not args.git_history and not args.archive:
        parser.error("Select source, git history or archive")
    findings = []
    checked = {}
    try:
        if args.source:
            current, checked["sourceFiles"] = scan_source(ROOT); findings.extend(current)
        if args.git_history:
            findings.extend(scan_git_identity(ROOT)); checked["gitHistory"] = True
        for archive in args.archive:
            current, count = scan_zip(archive); findings.extend(current)
            checked[_safe_name(archive.name)] = count
    except (OSError, ValueError, RuntimeError, RecursionError, EOFError, zipfile.BadZipFile, subprocess.SubprocessError):
        findings.append(_finding("unreadable-public-input", "<input>"))
    print(json.dumps({"status": "FAIL" if findings else "PASS", "checked": checked,
                      "findings": findings}, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
