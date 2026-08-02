#!/usr/bin/env python3
"""Validate a release ZIP byte-for-byte against the selected source profile."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAME = "code-ontology-companion"
EXPECTED_VERSION = "0.3.3"
PREFIX = f"{EXPECTED_NAME}/"
RELEASE_DATE = "2026-08-02"
ARCHIVE_TIMESTAMP = tuple(int(part) for part in RELEASE_DATE.split("-")) + (0, 0, 0)
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 512
ROOT_FILES = {
    "full": {
        "CHANGELOG.md",
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
    },
    "skills-only": {
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
        "SBOM.spdx.json",
    },
}
INCLUDED_PREFIXES = {
    "full": {".codex-plugin/", "assets/", "evals/", "mcp/", "skills/"},
    "skills-only": {"assets/", "skills/"},
}
EXCLUDED_PARTS = {"__pycache__", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_ASSETS = {"assets/logo-source.svg", "assets/logo-dark-source.svg"}
COMMON_REQUIRED = {
    ".codex-plugin/plugin.json",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "SBOM.spdx.json",
    "assets/composer-icon.png",
    "assets/logo-dark.png",
    "assets/logo.png",
    "skills/manage-code-ontology/SKILL.md",
    "skills/manage-code-ontology/scripts/code_ontology_core.py",
    "skills/manage-code-ontology/scripts/companion.py",
    "skills/manage-code-ontology/scripts/local_llm.py",
}
FULL_REQUIRED = {
    ".mcp.json",
    "CHANGELOG.md",
    "README.md",
    "PRIVACY.md",
    "TERMS.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "SUPPORT.md",
    "SUBMISSION.md",
    "evals/cases.json",
    "mcp/launcher.mjs",
    "mcp/server.py",
}
SKILLS_ONLY_ENTRIES = {
    ".codex-plugin/plugin.json",
    "LICENSE",
    "NOTICE",
    "SBOM.spdx.json",
    "THIRD_PARTY_NOTICES.md",
    "assets/composer-icon.png",
    "assets/logo-dark.png",
    "assets/logo.png",
    "skills/manage-code-ontology/SKILL.md",
    "skills/manage-code-ontology/agents/openai.yaml",
    "skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js",
    "skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js",
    "skills/manage-code-ontology/assets/vendor/licenses/CYTOSCAPE-MIT.txt",
    "skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.md",
    "skills/manage-code-ontology/assets/vendor/licenses/WEB-WORKER-APACHE-2.0.txt",
    "skills/manage-code-ontology/assets/workbench.css",
    "skills/manage-code-ontology/assets/workbench.html",
    "skills/manage-code-ontology/assets/workbench.js",
    "skills/manage-code-ontology/references/data-boundaries.md",
    "skills/manage-code-ontology/references/lineage-model.md",
    "skills/manage-code-ontology/references/local-llm.md",
    "skills/manage-code-ontology/references/ontology-model.md",
    "skills/manage-code-ontology/references/provenance-schema.ttl",
    "skills/manage-code-ontology/references/schema.ttl",
    "skills/manage-code-ontology/scripts/code_ontology_core.py",
    "skills/manage-code-ontology/scripts/companion.py",
    "skills/manage-code-ontology/scripts/local_llm.py",
}
FULL_ENTRIES = SKILLS_ONLY_ENTRIES | {
    ".mcp.json",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "PRIVACY.md",
    "README.md",
    "SECURITY.md",
    "SUBMISSION.md",
    "SUPPORT.md",
    "TERMS.md",
    "THREAT_MODEL.md",
    "TRADEMARKS.md",
    "evals/cases.json",
    "mcp/launcher.mjs",
    "mcp/server.py",
}
TEXT_SUFFIXES = {"", ".css", ".html", ".js", ".json", ".md", ".py", ".ttl", ".yaml", ".yml"}


class ReleaseValidationError(ValueError):
    """Raised when a source profile or completed archive is not releasable."""


def _fail(message: str) -> None:
    raise ReleaseValidationError(message)


def _source_manifest(root: Path) -> dict[str, Any]:
    path = root / ".codex-plugin" / "plugin.json"
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            _fail("Source manifest must be a regular non-symlink file.")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"Source manifest is not readable JSON: {exc}")
    if not isinstance(value, dict):
        _fail("Source manifest must be a JSON object.")
    if value.get("name") != EXPECTED_NAME or value.get("version") != EXPECTED_VERSION:
        _fail(
            f"Source manifest must identify {EXPECTED_NAME} {EXPECTED_VERSION}."
        )
    return value


def _validate_source_release_record(root: Path) -> None:
    try:
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        sbom = json.loads((root / "SBOM.spdx.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"Source release record is unreadable: {exc}")
    expected_heading = f"## {EXPECTED_VERSION} - {RELEASE_DATE}"
    headings = re.findall(r"^## .+$", changelog, flags=re.MULTILINE)
    if not headings or headings[0] != expected_heading:
        _fail("Source changelog version/date does not match release artifact metadata.")
    if sbom.get("creationInfo", {}).get("created") != f"{RELEASE_DATE}T00:00:00Z":
        _fail("Source SBOM creation date does not match release artifact metadata.")


def _included(relative: str, profile: str) -> bool:
    path = PurePosixPath(relative)
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES or relative in EXCLUDED_ASSETS:
        return False
    if relative in ROOT_FILES[profile]:
        return True
    return any(relative.startswith(prefix) for prefix in INCLUDED_PREFIXES[profile])


def selected_source_files(root: Path, profile: str) -> list[Path]:
    """Return a stable source selection and reject link-like selected entries."""

    if profile not in ROOT_FILES:
        _fail(f"Unknown release profile: {profile}")
    selected: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if not _included(relative, profile):
            continue
        try:
            metadata = path.lstat()
        except OSError as exc:
            _fail(f"Selected source entry cannot be inspected: {relative}: {exc}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            _fail(f"Selected source entry must be a regular non-symlink file: {relative}")
        selected.append(path)
    return sorted(selected, key=lambda item: item.relative_to(root).as_posix())


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        _fail(f"Skills-only transform {label!r} expected one source match, found {count}.")
    return text.replace(old, new, 1)


def skills_only_manifest(source: dict[str, Any]) -> dict[str, Any]:
    manifest = copy.deepcopy(source)
    manifest.pop("mcpServers", None)
    manifest.pop("apps", None)
    manifest["keywords"] = [
        keyword for keyword in manifest.get("keywords", []) if str(keyword).lower() != "mcp"
    ]
    manifest["description"] = (
        "Build privacy-conscious local code ontologies with deterministic analysis, "
        "portable RDF, and optional consent-based local inference."
    )
    interface = manifest["interface"]
    interface["shortDescription"] = "Local code graphs with lineage"
    interface["longDescription"] = (
        "Statically map an authorized Java, Spring, or Python repository into "
        "immutable local knowledge-graph snapshots. Search symbols, inspect "
        "possible change impact, compare versions, preserve evidence lineage, "
        "export RDF 1.1 Turtle, open a self-contained interactive offline workbench, "
        "and optionally create a narrowly scoped immutable static runtime-path receipt. "
        "Deterministic analysis executes no target code and makes no network request. "
        "If existing Ollama is detected, the user may separately authorize bounded "
        "inference through fixed IPv4 loopback; its suggestions stay unvalidated and "
        "separate from observed evidence. Nothing installs a model or starts Ollama; "
        "authorized enrichment runs the selected model and requests immediate unload."
    )
    interface["capabilities"] = [
        "Local static analysis",
        "Versioned RDF lineage",
        "Static impact and snapshot comparison",
        "Interactive offline ontology workbench",
        "Immutable static runtime-path receipts",
        "Optional consent-based local inference sidecars",
    ]
    return manifest


def skills_only_skill(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(f"Skill instructions are not valid UTF-8: {exc}")
    text = _replace_once(
        text,
        ", version comparison, or local MCP ontology search.",
        ", or version comparison.",
        "skill-frontmatter",
    )
    text = _replace_once(
        text,
        "The plugin's MCP server is read-only and can access only workspaces "
        "previously initialized through this workflow.",
        "All bundled operations run through the explicit local workflow below.",
        "skill-runtime-boundary",
    )
    text = _replace_once(
        text,
        "It also registers a random local workspace ID so the read-only MCP "
        "server can query it without accepting arbitrary filesystem paths.",
        "It also registers a random local workspace ID for bounded local lookup "
        "without accepting arbitrary filesystem paths.",
        "skill-workspace-id",
    )
    text = _replace_once(
        text,
        "Use MCP read tools when available for these same read-only operations. ",
        "",
        "skill-query-route",
    )
    text = _replace_once(
        text,
        "`sync`, `watch`, runtime binding, or MCP.",
        "`sync`, `watch`, or runtime binding.",
        "skill-local-llm-implicit-routes",
    )
    return text.encode("utf-8")


def skills_only_content(relative: str, content: bytes) -> bytes:
    if relative == "skills/manage-code-ontology/SKILL.md":
        return skills_only_skill(content)
    if relative == "skills/manage-code-ontology/scripts/companion.py":
        old = b"lineage journal, and a small local registry used by the read-only MCP server."
        new = b"lineage journal, and a small local registry for bounded workspace lookup."
        if content.count(old) != 1:
            _fail(
                "Skills-only transform 'companion-docstring' expected one source match, "
                f"found {content.count(old)}."
            )
        return content.replace(old, new, 1)
    if relative == "skills/manage-code-ontology/references/data-boundaries.md":
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            _fail(f"Data-boundary reference is not valid UTF-8: {exc}")
        text = _replace_once(
            text,
            "Portable RDF, offline HTML, and normal MCP responses do not intentionally",
            "Portable RDF, offline HTML, and normal CLI summaries do not intentionally",
            "data-boundaries-output",
        )
        text = _replace_once(
            text,
            "When the plugin is enabled, Codex may start the bundled read-only stdio MCP\n"
            "process. It opens no listening port, accepts no arbitrary filesystem path, and\n"
            "queries only workspaces already registered by an explicitly authorized\n"
            "initialization workflow.",
            "The skills-only package starts no background process and opens no listening "
            "port.\nAll operations use explicit CLI commands against workspaces created by "
            "an\nauthorized initialization workflow.",
            "data-boundaries-process",
        )
        text = _replace_once(
            text,
            "RDF, runtime binding, lineage, or MCP data.",
            "RDF, runtime binding, lineage, or CLI output.",
            "data-boundaries-local-llm-sidecar",
        )
        return text.encode("utf-8")
    if relative == "skills/manage-code-ontology/references/lineage-model.md":
        old = b"normal RDF, HTML, and MCP responses do not expose"
        new = b"normal RDF, HTML, and CLI summaries do not expose"
        if content.count(old) != 1:
            _fail(
                "Skills-only transform 'lineage-output' expected one source match, "
                f"found {content.count(old)}."
            )
        return content.replace(old, new, 1)
    if relative == "skills/manage-code-ontology/references/local-llm.md":
        old = b"`init`, `sync`, `watch`, and all MCP tools never call the"
        new = b"`init`, `sync`, and `watch` never call the"
        if content.count(old) != 1:
            _fail(
                "Skills-only transform 'local-llm-implicit-routes' expected one source match, "
                f"found {content.count(old)}."
            )
        return content.replace(old, new, 1)
    return content


def expected_archive_contents(root: Path, profile: str) -> dict[str, bytes]:
    """Build the exact expected relative-path-to-content map for a release profile."""

    _validate_source_release_record(root)
    source_manifest = _source_manifest(root)
    contents: dict[str, bytes] = {}
    if profile == "skills-only":
        contents[".codex-plugin/plugin.json"] = (
            json.dumps(skills_only_manifest(source_manifest), indent=2, ensure_ascii=False).encode(
                "utf-8"
            )
            + b"\n"
        )
    elif profile != "full":
        _fail(f"Unknown release profile: {profile}")

    for path in selected_source_files(root, profile):
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_bytes()
        except OSError as exc:
            _fail(f"Selected source file cannot be read: {relative}: {exc}")
        if profile == "skills-only":
            content = skills_only_content(relative, content)
        if relative in contents:
            _fail(f"Duplicate expected release entry: {relative}")
        contents[relative] = content

    required = COMMON_REQUIRED | (FULL_REQUIRED if profile == "full" else set())
    missing = sorted(required.difference(contents))
    if missing:
        _fail(f"Source profile is missing required entries: {', '.join(missing)}")
    exact_entries = FULL_ENTRIES if profile == "full" else SKILLS_ONLY_ENTRIES
    if set(contents) != exact_entries:
        missing = sorted(exact_entries.difference(contents))
        extra = sorted(set(contents).difference(exact_entries))
        _fail(f"Source profile entry set mismatch; missing={missing}, extra={extra}")
    if profile == "skills-only":
        forbidden_names = sorted(
            name
            for name in contents
            if name == ".mcp.json" or name.startswith("mcp/") or "/mcp/" in name.lower()
        )
        if forbidden_names:
            _fail(f"Skills-only source selected forbidden server entries: {forbidden_names}")
        manifest = json.loads(contents[".codex-plugin/plugin.json"].decode("utf-8"))
        if set(manifest).intersection({"mcpServers", "apps"}):
            _fail("Skills-only manifest contains excluded server configuration.")
        if "mcp" in json.dumps(manifest, ensure_ascii=False).lower():
            _fail("Skills-only manifest still contains MCP-only metadata.")
        for relative, content in contents.items():
            path = PurePosixPath(relative)
            is_vendor = relative.startswith("skills/manage-code-ontology/assets/vendor/")
            if not is_vendor and path.suffix.lower() in TEXT_SUFFIXES and b"mcp" in content.lower():
                _fail(f"Skills-only file still contains MCP-only text: {relative}")
    return contents


def validate_skills_only_source(root: Path = ROOT) -> None:
    """Validate all transformations before writing a skills-only archive."""

    expected_archive_contents(root, "skills-only")


def archive_info(relative: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(PREFIX + relative, date_time=ARCHIVE_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if PurePosixPath(relative).suffix in {".py", ".mjs"} else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def _expected_filename(profile: str) -> str:
    marker = "-skills-only" if profile == "skills-only" else ""
    return f"{EXPECTED_NAME}{marker}-{EXPECTED_VERSION}.zip"


def _validate_name(name: str) -> str:
    if "\x00" in name or "\\" in name or not name.startswith(PREFIX):
        _fail(f"Unsafe or unexpected archive path: {name!r}")
    relative = name[len(PREFIX) :]
    path = PurePosixPath(relative)
    if not relative or relative.endswith("/") or path.is_absolute():
        _fail(f"Directory or absolute archive entry is not allowed: {name!r}")
    raw_parts = relative.split("/")
    if (
        any(part in {"", ".", ".."} for part in raw_parts)
        or ":" in raw_parts[0]
    ):
        _fail(f"Archive path traversal is not allowed: {name!r}")
    return relative


def _validate_manifest_and_sbom(contents: dict[str, bytes], profile: str) -> None:
    try:
        manifest = json.loads(contents[".codex-plugin/plugin.json"].decode("utf-8"))
        sbom = json.loads(contents["SBOM.spdx.json"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"Artifact manifest or SBOM is invalid: {exc}")
    if manifest.get("name") != EXPECTED_NAME or manifest.get("version") != EXPECTED_VERSION:
        _fail("Artifact manifest name or version does not match the release.")
    if profile == "full":
        if manifest.get("mcpServers") != "./.mcp.json":
            _fail("Full profile must declare the bundled MCP server configuration.")
    elif set(manifest).intersection({"mcpServers", "apps"}):
        _fail("Skills-only manifest must not declare MCP servers or apps.")
    package_versions = {
        package.get("name"): package.get("versionInfo")
        for package in sbom.get("packages", [])
        if isinstance(package, dict)
    }
    if package_versions.get(EXPECTED_NAME) != EXPECTED_VERSION:
        _fail("Artifact SBOM package version does not match the release.")
    if not str(sbom.get("documentNamespace", "")).endswith(f"/{EXPECTED_VERSION}"):
        _fail("Artifact SBOM document namespace does not match the release.")


def _run_extracted_smoke(archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> None:
    with tempfile.TemporaryDirectory(prefix="code-ontology-release-smoke-") as temporary:
        extraction_root = Path(temporary) / "extracted"
        extraction_root.mkdir()
        for info in infos:
            relative = _validate_name(info.filename)
            target = extraction_root / EXPECTED_NAME / PurePosixPath(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with archive.open(info, "r") as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
            except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
                _fail(f"Safe artifact extraction failed for {relative}: {exc}")
            target.chmod((info.external_attr >> 16) & 0o777)

        package = extraction_root / EXPECTED_NAME
        scripts = package / "skills" / "manage-code-ontology" / "scripts"
        compile_paths = [
            scripts / "code_ontology_core.py",
            scripts / "companion.py",
            scripts / "local_llm.py",
        ]
        if (package / "mcp" / "server.py").is_file():
            compile_paths.append(package / "mcp" / "server.py")
        environment = dict(os.environ)
        for name in (
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "ALL_PROXY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "all_proxy",
            "http_proxy",
            "https_proxy",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            }
        )
        compile_result = subprocess.run(
            [sys.executable, "-m", "py_compile", *map(str, compile_paths)],
            cwd=package,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if compile_result.returncode:
            _fail(f"Extracted Python compile smoke failed: {compile_result.stderr.strip()}")

        repository = Path(temporary) / "authorized-smoke-repository"
        repository.mkdir()
        sample = repository / "sample.py"
        sample.write_text("def release_smoke(value: int) -> int:\n    return value + 1\n", encoding="utf-8")
        before = sorted(path.relative_to(repository).as_posix() for path in repository.rglob("*"))
        preflight = subprocess.run(
            [sys.executable, str(scripts / "companion.py"), "preflight", "--repo", str(repository)],
            cwd=package,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if preflight.returncode:
            _fail(f"Extracted preflight smoke failed: {preflight.stderr.strip()}")
        try:
            result = json.loads(preflight.stdout)
        except json.JSONDecodeError as exc:
            _fail(f"Extracted preflight did not return JSON: {exc}")
        after = sorted(path.relative_to(repository).as_posix() for path in repository.rglob("*"))
        companion = result.get("companion", {}) if isinstance(result, dict) else {}
        if (
            result.get("source_file_count") != 1
            or companion.get("version") != EXPECTED_VERSION
            or companion.get("writesDuringPreflight") is not False
            or before != after
        ):
            _fail("Extracted preflight smoke returned unexpected or write-capable results.")

        server = package / "mcp" / "server.py"
        if server.is_file():
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "release-smoke", "version": "1"},
                    },
                },
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
            mcp_environment = {
                **environment,
                "CODE_ONTOLOGY_HOME": str(Path(temporary) / "empty-mcp-home"),
            }
            node = shutil.which("node")
            launcher = package / "mcp" / "launcher.mjs"
            mcp_command = (
                [node, str(launcher)]
                if node and launcher.is_file()
                else [sys.executable, str(server)]
            )
            mcp_result = subprocess.run(
                mcp_command,
                cwd=package,
                env=mcp_environment,
                input="".join(json.dumps(item) + "\n" for item in messages),
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            if mcp_result.returncode:
                _fail(f"Extracted MCP launcher/stdio smoke failed: {mcp_result.stderr.strip()}")
            try:
                responses = [json.loads(line) for line in mcp_result.stdout.splitlines()]
                initialize = responses[0]["result"]
                tools = responses[1]["result"]["tools"]
            except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
                _fail(f"Extracted MCP stdio smoke returned an invalid contract: {exc}")
            expected_tools = {
                "ontology_list_workspaces",
                "ontology_status",
                "ontology_search",
                "ontology_neighbors",
                "ontology_history",
                "ontology_changes",
                "ontology_lineage",
            }
            actual_tools = {
                item.get("name") for item in tools if isinstance(item, dict)
            } if isinstance(tools, list) else set()
            if (
                not isinstance(initialize, dict)
                or initialize.get("serverInfo")
                != {"name": EXPECTED_NAME, "version": EXPECTED_VERSION}
                or not isinstance(tools, list)
                or len(tools) != 7
                or actual_tools != expected_tools
                or any(
                    not isinstance(item, dict)
                    or item.get("annotations", {}).get("readOnlyHint") is not True
                    or item.get("annotations", {}).get("destructiveHint") is not False
                    or item.get("annotations", {}).get("openWorldHint") is not False
                    or item.get("annotations", {}).get("idempotentHint") is not True
                    or item.get("inputSchema", {}).get("additionalProperties") is not False
                    or item.get("outputSchema", {}).get("additionalProperties") is not False
                    or not item.get("outputSchema", {}).get("oneOf")
                    for item in tools
                )
            ):
                _fail("Extracted MCP stdio smoke did not expose the exact read-only contract.")


def _validate_checksum(path: Path) -> None:
    checksum_path = path.with_suffix(".zip.sha256")
    try:
        metadata = checksum_path.lstat()
    except OSError as exc:
        _fail(f"Checksum file is missing or unreadable: {exc}")
    if not stat.S_ISREG(metadata.st_mode) or checksum_path.is_symlink():
        _fail("Checksum path must be a regular non-symlink file.")
    try:
        text = checksum_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        _fail(f"Checksum file is missing or unreadable: {exc}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if text != f"{digest}  {path.name}\n":
        _fail("Checksum file does not exactly match the release archive.")


def validate_archive(
    path: Path,
    profile: str,
    *,
    root: Path = ROOT,
    run_smoke: bool = True,
    verify_checksum: bool = False,
) -> None:
    """Validate archive structure, bytes, metadata, profile, and extracted behavior."""

    if profile not in {"full", "skills-only"}:
        _fail(f"Unknown release profile: {profile}")
    if path.name != _expected_filename(profile):
        _fail(f"Unexpected archive filename for {profile}: {path.name}")
    try:
        metadata = path.lstat()
    except OSError as exc:
        _fail(f"Release archive cannot be inspected: {exc}")
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        _fail("Release archive must be a regular non-symlink file.")
    if metadata.st_size <= 0 or metadata.st_size > MAX_ARCHIVE_BYTES:
        _fail("Release archive size is outside the permitted bound.")

    expected = expected_archive_contents(root, profile)
    expected_names = {PREFIX + relative for relative in expected}
    try:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.comment:
                _fail("Release archive comment must be empty.")
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ENTRIES:
                _fail("Release archive entry count is outside the permitted bound.")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                _fail("Release archive contains duplicate entry names.")
            if len(names) != len({name.casefold() for name in names}):
                _fail("Release archive contains case-colliding entry names.")
            if names != sorted(names):
                _fail("Release archive entries are not in deterministic lexical order.")
            actual_names = set(names)
            if actual_names != expected_names:
                missing = sorted(expected_names.difference(actual_names))
                extra = sorted(actual_names.difference(expected_names))
                _fail(f"Release archive entry set mismatch; missing={missing}, extra={extra}")

            expanded = 0
            actual_contents: dict[str, bytes] = {}
            for info in infos:
                relative = _validate_name(info.filename)
                if info.date_time != ARCHIVE_TIMESTAMP:
                    _fail(f"Non-deterministic timestamp on archive entry: {relative}")
                if (
                    info.create_system != 3
                    or info.create_version != 20
                    or info.extract_version != 20
                    or info.internal_attr != 0
                    or info.extra
                    or info.comment
                ):
                    _fail(f"Unexpected platform metadata on archive entry: {relative}")
                if info.flag_bits != 0:
                    _fail(f"Unexpected or encrypted archive flags on entry: {relative}")
                if info.compress_type != zipfile.ZIP_DEFLATED:
                    _fail(f"Unexpected compression method on archive entry: {relative}")
                if info.file_size < 0 or info.file_size > MAX_ENTRY_BYTES:
                    _fail(f"Archive entry size is outside the permitted bound: {relative}")
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    _fail("Expanded archive size exceeds the permitted bound.")
                expected_mode = 0o755 if PurePosixPath(relative).suffix in {".py", ".mjs"} else 0o644
                encoded_mode = info.external_attr >> 16
                expected_external_attr = (stat.S_IFREG | expected_mode) << 16
                if (
                    info.external_attr != expected_external_attr
                    or stat.S_IFMT(encoded_mode) != stat.S_IFREG
                    or stat.S_IMODE(encoded_mode) != expected_mode
                ):
                    _fail(f"Unexpected file type or mode on archive entry: {relative}")
                actual_contents[relative] = archive.read(info)

            corrupt = archive.testzip()
            if corrupt is not None:
                _fail(f"Release archive CRC check failed: {corrupt}")
            for relative, expected_content in expected.items():
                if actual_contents.get(relative) != expected_content:
                    _fail(f"Release archive content mismatch: {relative}")
            _validate_manifest_and_sbom(actual_contents, profile)
            if run_smoke:
                _run_extracted_smoke(archive, infos)
    except ReleaseValidationError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        _fail(f"Release archive is unreadable or corrupt: {exc}")

    if verify_checksum:
        _validate_checksum(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--profile", required=True, choices=("full", "skills-only"))
    parser.add_argument("--checksum", action="store_true", help="Verify the sibling .sha256 file.")
    parser.add_argument("--no-smoke", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_archive(
            args.archive,
            args.profile,
            run_smoke=not args.no_smoke,
            verify_checksum=args.checksum,
        )
    except ReleaseValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: exact {args.profile} release artifact {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
