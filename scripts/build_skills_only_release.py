#!/usr/bin/env python3
"""Build, independently reproduce, and validate the public skills-only ZIP."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from validate_release_artifact import (
    EXPECTED_NAME,
    EXPECTED_VERSION,
    ROOT,
    archive_info,
    expected_archive_contents,
    validate_skills_only_source,
)


OUTPUT_DIR = ROOT / "dist"
OUTPUT = OUTPUT_DIR / f"{EXPECTED_NAME}-skills-only-{EXPECTED_VERSION}.zip"
PROFILE = "skills-only"


def build_archive(output: Path) -> int:
    """Create one transformed archive from a fresh, exact source selection."""

    contents = expected_archive_contents(ROOT, PROFILE)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative in sorted(contents):
            archive.writestr(archive_info(relative), contents[relative])
    return len(contents)


def _run_source_validator() -> int:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_package.py")],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        return result.returncode
    try:
        validate_skills_only_source(ROOT)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_artifact_validator(path: Path, *, checksum: bool = False, smoke: bool = False) -> int:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_release_artifact.py"),
        str(path),
        "--profile",
        PROFILE,
    ]
    if checksum:
        command.append("--checksum")
    if not smoke:
        command.append("--no-smoke")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _publish(content: bytes, target: Path) -> None:
    descriptor, raw = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=target.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    if _run_source_validator():
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skills-release-double-build-", dir=OUTPUT_DIR) as raw:
        temporary = Path(raw)
        first = temporary / "first" / OUTPUT.name
        second = temporary / "second" / OUTPUT.name
        file_count = build_archive(first)
        if _run_artifact_validator(first):
            return 1
        second_count = build_archive(second)
        if second_count != file_count or _run_artifact_validator(second):
            return 1
        first_bytes = first.read_bytes()
        if first_bytes != second.read_bytes():
            print("FAIL: independent skills-only release builds are not byte-identical.", file=sys.stderr)
            return 1
        digest = hashlib.sha256(first_bytes).hexdigest()
        checksum_content = f"{digest}  {OUTPUT.name}\n".encode("ascii")
        first.with_suffix(".zip.sha256").write_bytes(checksum_content)
        if _run_artifact_validator(first, checksum=True, smoke=True):
            return 1
        _publish(first_bytes, OUTPUT)

    checksum = OUTPUT.with_suffix(".zip.sha256")
    _publish(checksum_content, checksum)
    if _run_artifact_validator(OUTPUT, checksum=True, smoke=False):
        return 1
    print(OUTPUT)
    print(f"sha256={digest}")
    print(f"files={file_count}")
    print("reproducible_builds=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
