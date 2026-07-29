#!/usr/bin/env python3
"""Validate the public plugin source without third-party dependencies."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".codex-plugin" / "plugin.json"
SKILL_PATH = ROOT / "skills" / "manage-code-ontology"
CORE_PATH = SKILL_PATH / "scripts" / "code_ontology_core.py"
COMPANION_PATH = SKILL_PATH / "scripts" / "companion.py"
MCP_SERVER_PATH = ROOT / "mcp" / "server.py"
MCP_LAUNCHER_PATH = ROOT / "mcp" / "launcher.mjs"
VERSION = "0.1.1"
REQUIRED_FILES = [
    ".mcp.json",
    "LICENSE",
    "NOTICE",
    "README.md",
    "PRIVACY.md",
    "TERMS.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "SUPPORT.md",
    "CONTRIBUTING.md",
    "SUBMISSION.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "SBOM.spdx.json",
    "evals/cases.json",
    "assets/logo.png",
    "assets/logo-dark.png",
    "assets/composer-icon.png",
    "skills/manage-code-ontology/SKILL.md",
    "skills/manage-code-ontology/agents/openai.yaml",
    "skills/manage-code-ontology/references/data-boundaries.md",
    "skills/manage-code-ontology/references/lineage-model.md",
    "skills/manage-code-ontology/references/ontology-model.md",
    "skills/manage-code-ontology/references/provenance-schema.ttl",
    "skills/manage-code-ontology/references/schema.ttl",
    "skills/manage-code-ontology/scripts/code_ontology_core.py",
    "skills/manage-code-ontology/scripts/companion.py",
    "mcp/launcher.mjs",
    "mcp/server.py",
]
FORBIDDEN_IMPORT_ROOTS = {
    "requests",
    "httpx",
    "aiohttp",
    "boto3",
    "paramiko",
    "socket",
    "subprocess",
    "http.client",
    "ftplib",
    "urllib.request",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def validate_required_files() -> None:
    missing = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    if missing:
        fail(f"Missing required files: {', '.join(missing)}")


def validate_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["name"] != "code-ontology-companion":
        fail("Unexpected manifest name")
    if manifest["version"] != VERSION:
        fail("Manifest version mismatch")
    if manifest["license"] != "Apache-2.0":
        fail("Unexpected license identifier")
    if manifest.get("mcpServers") != "./.mcp.json":
        fail("Manifest must reference the bundled MCP configuration")
    if set(manifest).intersection({"hooks", "apps"}):
        fail("Version 0.1 must not bundle hooks or apps")
    prompts = manifest["interface"]["defaultPrompt"]
    if not 1 <= len(prompts) <= 3 or any(len(prompt) > 128 for prompt in prompts):
        fail("Default prompt count or length is invalid")
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if not manifest["interface"][field].startswith("https://"):
            fail(f"{field} must use HTTPS")
    for field in ("composerIcon", "logo", "logoDark"):
        asset = (ROOT / manifest["interface"][field]).resolve()
        if not asset.is_file() or ROOT not in asset.parents:
            fail(f"Invalid manifest asset: {field}")
    mcp_config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    expected = {
        "cwd": ".",
        "command": "node",
        "args": ["./mcp/launcher.mjs"],
    }
    if mcp_config.get("mcpServers", {}).get("code-ontology-companion") != expected:
        fail("Unexpected bundled MCP launch configuration")


def validate_evals() -> None:
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    if cases["plugin_version"] != VERSION:
        fail("Eval version mismatch")
    if len(cases["positive_cases"]) < 5:
        fail("At least five positive evaluation cases are required")
    if len(cases["negative_cases"]) < 3:
        fail("At least three negative evaluation cases are required")
    identifiers = [
        item["id"] for group in ("positive_cases", "negative_cases") for item in cases[group]
    ]
    if len(identifiers) != len(set(identifiers)):
        fail("Evaluation case IDs must be unique")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def validate_runtime_boundaries() -> None:
    for path in (CORE_PATH, COMPANION_PATH, MCP_SERVER_PATH):
        imports = imported_modules(path)
        forbidden = {
            module
            for module in imports
            if module in FORBIDDEN_IMPORT_ROOTS
            or module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS
        }
        if forbidden:
            fail(f"Network or process imports are not allowed in {path.name}: {sorted(forbidden)}")
        source = path.read_text(encoding="utf-8")
        for token in ("eval(", "exec(", "os.system(", "Popen(", "shell=True"):
            if token in source:
                fail(f"Target execution primitive found in {path.name}: {token}")
    source = CORE_PATH.read_text(encoding="utf-8")
    if f'PLUGIN_VERSION = "{VERSION}"' not in source:
        fail("Analyzer version mismatch")
    companion_source = COMPANION_PATH.read_text(encoding="utf-8")
    if f'COMPANION_VERSION = "{VERSION}"' not in companion_source:
        fail("Companion version mismatch")
    launcher = MCP_LAUNCHER_PATH.read_text(encoding="utf-8")
    for forbidden in ('from "node:http"', 'from "node:https"', 'from "node:net"', "fetch(", "exec("):
        if forbidden in launcher:
            fail(f"Network or shell primitive found in launcher: {forbidden}")
    if "shell: false" not in launcher or 'path.join(launcherDir, "server.py")' not in launcher:
        fail("Launcher must use a fixed bundled server path without a shell")


def validate_text_hygiene() -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "dist", "__pycache__"} for part in path.parts):
            continue
        if path.suffix.lower() not in {".md", ".json", ".yaml", ".yml", ".py", ".ttl", ".svg", ""}:
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        placeholder = "TO" + "DO"
        if re.search(rf"\[{placeholder}(?::|\])|{placeholder}:", text, flags=re.IGNORECASE):
            fail(f"Unresolved placeholder found: {path.relative_to(ROOT)}")
        local_posix = "/Users/" + "aether/"
        local_windows = "\\Users\\" + "aether\\"
        if local_posix in text or local_windows in text:
            fail(f"Local absolute path leaked: {path.relative_to(ROOT)}")


def run(command: list[str]) -> None:
    process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if process.returncode:
        sys.stderr.write(process.stdout)
        sys.stderr.write(process.stderr)
        fail(f"Command failed: {' '.join(command)}")


def validate_skill_metadata() -> None:
    openai_yaml = (SKILL_PATH / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if "$manage-code-ontology" not in openai_yaml:
        fail("openai.yaml default prompt must mention $manage-code-ontology")
    skill_text = (SKILL_PATH / "SKILL.md").read_text(encoding="utf-8")
    if not skill_text.startswith("---\nname: manage-code-ontology\n"):
        fail("Unexpected skill frontmatter")


def main() -> int:
    validate_required_files()
    validate_manifest()
    validate_evals()
    validate_runtime_boundaries()
    validate_text_hygiene()
    validate_skill_metadata()
    run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(CORE_PATH),
            str(COMPANION_PATH),
            str(MCP_SERVER_PATH),
        ]
    )
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    print("PASS: source package, safety boundaries, metadata, evals, and tests")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
