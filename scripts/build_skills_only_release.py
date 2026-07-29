#!/usr/bin/env python3
"""Create the deterministic skills-only archive accepted by the public portal."""

from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = json.loads(
    (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
)
NAME = SOURCE_MANIFEST["name"]
VERSION = SOURCE_MANIFEST["version"]
OUTPUT_DIR = ROOT / "dist"
OUTPUT = OUTPUT_DIR / f"{NAME}-skills-only-{VERSION}.zip"
PREFIX = f"{NAME}/"
ROOT_FILES = {"LICENSE", "NOTICE"}
INCLUDED_PREFIXES = {"assets/", "skills/"}
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


def skills_only_manifest() -> dict:
    manifest = copy.deepcopy(SOURCE_MANIFEST)
    manifest.pop("mcpServers", None)
    manifest.pop("apps", None)
    manifest["keywords"] = [
        keyword for keyword in manifest.get("keywords", []) if keyword.lower() != "mcp"
    ]
    manifest["description"] = (
        "Build and maintain privacy-conscious local code ontologies with "
        "portable RDF, versioned lineage, and offline visualization."
    )
    interface = manifest["interface"]
    interface["shortDescription"] = "Local code graphs with lineage"
    interface["longDescription"] = (
        "Statically map an authorized Java, Spring, or Python repository into "
        "immutable local knowledge-graph snapshots. Search symbols, inspect "
        "possible change impact, compare versions, preserve evidence lineage, "
        "export RDF 1.1 Turtle, and open a self-contained offline visualization. "
        "The bundled skill does not execute target code, install software, send "
        "telemetry, or make direct network requests."
    )
    interface["capabilities"] = [
        "Local static analysis",
        "Versioned RDF lineage",
        "Static impact and snapshot comparison",
        "Offline graph visualization",
    ]
    return manifest


def skills_only_skill(content: bytes) -> bytes:
    text = content.decode("utf-8")
    text = text.replace(
        ", version comparison, or local MCP ontology search.",
        ", or version comparison.",
    )
    text = text.replace(
        "The plugin's MCP server is read-only and can access only workspaces "
        "previously initialized through this workflow.",
        "All bundled operations run through the explicit local workflow below.",
    )
    text = text.replace(
        "It also registers a random local workspace ID so the read-only MCP "
        "server can query it without accepting arbitrary filesystem paths.",
        "It also registers a random local workspace ID for bounded local lookup "
        "without accepting arbitrary filesystem paths.",
    )
    text = text.replace(
        "Use MCP read tools when available for these same read-only operations. ",
        "",
    )
    return text.encode("utf-8")


def skills_only_content(relative: str, content: bytes) -> bytes:
    if relative == "skills/manage-code-ontology/SKILL.md":
        return skills_only_skill(content)
    if relative == "skills/manage-code-ontology/scripts/companion.py":
        return content.replace(
            b"lineage journal, and a small local registry used by the read-only MCP server.",
            b"lineage journal, and a small local registry for bounded workspace lookup.",
        )
    if relative == "skills/manage-code-ontology/references/data-boundaries.md":
        text = content.decode("utf-8")
        text = text.replace(
            "Portable RDF, offline HTML, and normal MCP responses do not intentionally",
            "Portable RDF, offline HTML, and normal CLI summaries do not intentionally",
        )
        text = text.replace(
            "When the plugin is enabled, Codex may start the bundled read-only stdio MCP\n"
            "process. It opens no listening port, accepts no arbitrary filesystem path, and\n"
            "queries only workspaces already registered by an explicitly authorized\n"
            "initialization workflow.",
            "The skills-only package starts no background process and opens no listening "
            "port.\nAll operations use explicit CLI commands against workspaces created by "
            "an\nauthorized initialization workflow.",
        )
        return text.encode("utf-8")
    if relative == "skills/manage-code-ontology/references/lineage-model.md":
        return content.replace(
            b"normal RDF, HTML, and MCP responses do not expose",
            b"normal RDF, HTML, and CLI summaries do not expose",
        )
    return content


def archive_entry(name: str, content: bytes, executable: bool = False) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(PREFIX + name, date_time=(2026, 7, 30, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o755 if executable else 0o644) << 16
    return info, content


def main() -> int:
    manifest = skills_only_manifest()
    if set(manifest).intersection({"mcpServers", "apps"}):
        raise SystemExit("Skills-only manifest contains excluded server configuration.")
    if "mcp" in json.dumps(manifest, ensure_ascii=False).lower():
        raise SystemExit("Skills-only manifest still contains MCP-only metadata.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(path for path in ROOT.rglob("*") if path.is_file() and included(path))
    if not any(
        path.relative_to(ROOT).as_posix().startswith("skills/")
        and path.name == "SKILL.md"
        for path in paths
    ):
        raise SystemExit("No bundled skill was selected.")

    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        manifest_info, manifest_content = archive_entry(
            ".codex-plugin/plugin.json",
            json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
        )
        archive.writestr(manifest_info, manifest_content)
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            content = skills_only_content(relative, path.read_bytes())
            if b"mcp" in content.lower():
                raise SystemExit(f"Skills-only file still contains MCP-only text: {relative}")
            info, content = archive_entry(
                relative,
                content,
                executable=path.suffix == ".py",
            )
            archive.writestr(info, content)

    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    checksum = OUTPUT.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    print(OUTPUT)
    print(f"sha256={digest}")
    print(f"files={len(paths) + 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
