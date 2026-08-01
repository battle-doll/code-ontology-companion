#!/usr/bin/env python3
"""Require tracked changes to advance the stable plugin release version."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(".codex-plugin/plugin.json")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$"
)
BASE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+\-]{0,255}$")


class VersionPolicyError(ValueError):
    """Raised when a tracked change has no corresponding release version."""


def _run_git(repo: Path, arguments: list[str]) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise VersionPolicyError(f"Git command failed: {detail or arguments[0]}")
    return process.stdout


def _version(value: Any, label: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise VersionPolicyError(f"{label} version is not a string.")
    match = SEMVER_RE.fullmatch(value)
    if match is None:
        raise VersionPolicyError(f"{label} version is not stable semantic major.minor.patch.")
    return tuple(int(part) for part in match.groups())


def _manifest_version(content: bytes, label: str) -> tuple[str, tuple[int, int, int]]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VersionPolicyError(f"{label} manifest is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VersionPolicyError(f"{label} manifest is not an object.")
    raw = value.get("version")
    parsed = _version(raw, label)
    return raw, parsed


def validate_version_bump(repo: Path, base_ref: str) -> dict[str, Any]:
    if not BASE_REF_RE.fullmatch(base_ref):
        raise VersionPolicyError("Base ref contains unsupported characters.")
    repo = repo.resolve(strict=True)
    changed_raw = _run_git(
        repo,
        ["diff", "--name-only", "-z", base_ref, "HEAD", "--"],
    )
    changed = [item.decode("utf-8", errors="replace") for item in changed_raw.split(b"\0") if item]
    current_raw, current = _manifest_version((repo / MANIFEST).read_bytes(), "Current")
    base_content = _run_git(repo, ["show", f"{base_ref}:{MANIFEST.as_posix()}"])
    base_raw, base = _manifest_version(base_content, "Baseline")
    if not changed:
        return {
            "status": "unchanged",
            "baseRef": base_ref,
            "baseVersion": base_raw,
            "currentVersion": current_raw,
            "changedFiles": 0,
        }
    if current <= base:
        preview = ", ".join(changed[:8])
        raise VersionPolicyError(
            f"Tracked changes require a version greater than {base_raw}; found {current_raw}. "
            f"Changed files: {preview}"
        )
    try:
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise VersionPolicyError(f"Current changelog is unreadable: {exc}") from exc
    headings = re.findall(r"^## (\d+\.\d+\.\d+) - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
    if not headings or headings[0] != current_raw:
        raise VersionPolicyError("The current version must be the first dated changelog entry.")
    return {
        "status": "version-advanced",
        "baseRef": base_ref,
        "baseVersion": base_raw,
        "currentVersion": current_raw,
        "changedFiles": len(changed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = validate_version_bump(ROOT, arguments.base_ref)
    except (OSError, UnicodeDecodeError, VersionPolicyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
