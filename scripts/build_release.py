#!/usr/bin/env python3
"""Create a deterministic public plugin ZIP from an explicit allowlist."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
NAME = MANIFEST["name"]
VERSION = MANIFEST["version"]
OUTPUT_DIR = ROOT / "dist"
OUTPUT = OUTPUT_DIR / f"{NAME}-{VERSION}.zip"
PREFIX = f"{NAME}/"
ROOT_FILES = {
    "LICENSE",
    "NOTICE",
    "README.md",
    "CONTRIBUTING.md",
    "PRIVACY.md",
    "TERMS.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "SUPPORT.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "SBOM.spdx.json",
    "SUBMISSION.md",
    ".mcp.json",
}
INCLUDED_PREFIXES = {
    ".codex-plugin/",
    "assets/",
    "evals/",
    "mcp/",
    "skills/",
}
EXCLUDED_PARTS = {"__pycache__", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_ASSETS = {"assets/logo-source.svg", "assets/logo-dark-source.svg"}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES or relative in EXCLUDED_ASSETS:
        return False
    if relative in ROOT_FILES:
        return True
    return any(relative.startswith(prefix) for prefix in INCLUDED_PREFIXES)


def main() -> int:
    subprocess_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_package.py")],
        cwd=ROOT,
        check=False,
    )
    if subprocess_result.returncode:
        return subprocess_result.returncode

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)
    paths = sorted(path for path in ROOT.rglob("*") if path.is_file() and included(path))
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            relative = PREFIX + path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 7, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix in {".py", ".mjs"} else 0o644) << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    checksum = OUTPUT.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    print(OUTPUT)
    print(f"sha256={digest}")
    print(f"files={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
