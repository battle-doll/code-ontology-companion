#!/usr/bin/env python3
"""Maintain a local, versioned code ontology without executing target code.

The companion uses only the Python standard library and the bundled
``code_ontology_core`` analyzer. It stores immutable snapshots, a durable
lineage journal, and a small local registry used by the read-only MCP server.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import code_ontology_core as core


COMPANION_VERSION = "0.5.2"
OLLAMA_MACOS_APP = Path("/Applications/Ollama.app")
WORKSPACE_SCHEMA_VERSION = 1
PROVENANCE_NS = "https://battle-doll.github.io/code-ontology-companion/provenance#"
PROV_NS = "http://www.w3.org/ns/prov#"
EVIDENCE_TYPES = {"observed", "declared", "inferred", "validated", "approved"}
ADAPTER_SUPPORT_STATUSES = {"supported", "partial", "unsupported"}
MAX_ADAPTER_CAPABILITIES = 32
MAX_UNSUPPORTED_RUNTIME_ITEMS = 32
EVENT_KINDS = {
    "decision",
    "change",
    "validation",
    "activation",
    "observation",
    "outcome",
    "rollback",
    "note",
}


class CompanionError(RuntimeError):
    """Expected, user-actionable failure."""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _timestamp_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _is_link_like(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(attributes & core.WINDOWS_REPARSE_POINT)


def _read_regular_bytes(
    path: Path,
    label: str,
    maximum: int | None = None,
) -> bytes:
    try:
        initial_stat = path.lstat()
    except FileNotFoundError:
        raise CompanionError(f"{label} is missing.")
    except OSError as exc:
        raise CompanionError(f"{label} is unreadable: {exc}") from exc
    if _is_link_like(initial_stat) or not stat.S_ISREG(initial_stat.st_mode):
        raise CompanionError(f"{label} must be a regular file.")
    if getattr(initial_stat, "st_nlink", 1) != 1:
        raise CompanionError(f"{label} may not have multiple filesystem links.")
    if maximum is not None and initial_stat.st_size > maximum:
        raise CompanionError(f"{label} exceeds the allowed size.")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        raise CompanionError(f"{label} could not be opened safely: {exc}") from exc
    try:
        try:
            opened_stat = os.fstat(descriptor)
            if _is_link_like(opened_stat) or not stat.S_ISREG(opened_stat.st_mode):
                raise CompanionError(f"{label} must be a regular file.")
            if getattr(opened_stat, "st_nlink", 1) != 1:
                raise CompanionError(f"{label} may not have multiple filesystem links.")
            if not core._same_file(initial_stat, opened_stat):
                raise CompanionError(f"{label} changed before it could be read.")
            if core._stable_file_metadata(initial_stat) != core._stable_file_metadata(opened_stat):
                raise CompanionError(f"{label} changed before it could be read.")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                content = handle.read(maximum + 1) if maximum is not None else handle.read()
            final_stat = os.fstat(descriptor)
        except OSError as exc:
            raise CompanionError(f"{label} is unreadable: {exc}") from exc
    finally:
        os.close(descriptor)
    if not core._same_file(opened_stat, final_stat):
        raise CompanionError(f"{label} changed while it was being read.")
    if core._stable_file_metadata(opened_stat) != core._stable_file_metadata(final_stat):
        raise CompanionError(f"{label} changed while it was being read.")
    if maximum is not None and len(content) > maximum:
        raise CompanionError(f"{label} exceeds the allowed size.")
    try:
        current_stat = path.lstat()
    except OSError as exc:
        raise CompanionError(f"{label} could not be verified: {exc}") from exc
    if _is_link_like(current_stat) or not stat.S_ISREG(current_stat.st_mode):
        raise CompanionError(f"{label} must be a regular file.")
    if getattr(current_stat, "st_nlink", 1) != 1:
        raise CompanionError(f"{label} may not have multiple filesystem links.")
    if not core._same_file(final_stat, current_stat):
        raise CompanionError(f"{label} changed while it was being read.")
    if core._stable_file_metadata(final_stat) != core._stable_file_metadata(current_stat):
        raise CompanionError(f"{label} changed while it was being read.")
    return content


def _resolve_existing_dir(raw_path: str | Path, label: str) -> Path:
    path = Path(raw_path).expanduser()
    try:
        path_stat = path.lstat()
    except OSError:
        raise CompanionError(f"{label} is not a readable directory.")
    if _is_link_like(path_stat):
        raise CompanionError(f"{label} may not be a symbolic link or reparse point.")
    if not stat.S_ISDIR(path_stat.st_mode):
        raise CompanionError(f"{label} is not a readable directory.")
    return path.resolve()


def _resolve_managed_directory(
    workspace: Path,
    name: str,
    *,
    create: bool = False,
    required: bool = True,
) -> Path | None:
    """Resolve a Companion-owned directory without following links or reparse points."""
    if name not in {"snapshots", ".staging"}:
        raise CompanionError("Unsupported managed directory.")
    workspace_resolved = workspace.resolve()
    candidate = workspace_resolved / name
    if create:
        try:
            candidate.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CompanionError(f"Managed directory could not be created: {name}: {exc}") from exc
    try:
        candidate_stat = candidate.lstat()
    except FileNotFoundError:
        if required:
            raise CompanionError(f"Managed directory is missing: {name}")
        return None
    except OSError as exc:
        raise CompanionError(f"Managed directory is unreadable: {name}: {exc}") from exc
    if _is_link_like(candidate_stat) or not stat.S_ISDIR(candidate_stat.st_mode):
        raise CompanionError(
            f"Managed directory may not be a symbolic link or reparse point: {name}"
        )
    resolved = candidate.resolve()
    if resolved.parent != workspace_resolved or resolved.name != name:
        raise CompanionError(f"Managed directory escaped the workspace: {name}")
    return resolved


def _resolve_new_workspace(raw_path: str | Path, repo: Path) -> Path:
    raw = Path(raw_path).expanduser()
    if raw.exists() or raw.is_symlink():
        raise CompanionError("Workspace already exists; refusing to replace it.")
    parent = raw.parent
    parent_resolved = _resolve_existing_dir(parent, "Workspace parent")
    workspace = parent_resolved / raw.name
    if core._is_relative_to(workspace, repo):
        raise CompanionError("Workspace must be outside the target repository.")
    if core._is_relative_to(repo, workspace):
        raise CompanionError("Workspace may not contain the target repository.")
    return workspace


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_name, mode)
        except OSError:
            pass
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    _atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8") + b"\n", mode)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    return _json_object_from_bytes(_read_regular_bytes(path, label), label)


def _json_object_from_bytes(content: bytes, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite number {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate object key {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            content.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise CompanionError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise CompanionError(f"{label} must contain a JSON object.")
    return value


def _workspace(raw_path: str | Path) -> tuple[Path, dict[str, Any]]:
    workspace = _resolve_existing_dir(raw_path, "Workspace")
    config = _read_json(workspace / "companion.json", "Workspace configuration")
    if config.get("schemaVersion") != WORKSPACE_SCHEMA_VERSION:
        raise CompanionError("Unsupported workspace schema version.")
    repo = _resolve_existing_dir(config.get("repositoryRoot", ""), "Configured repository")
    if core._is_relative_to(workspace, repo) or core._is_relative_to(repo, workspace):
        raise CompanionError("Workspace and repository boundaries overlap.")
    return workspace, config


def _data_home() -> Path:
    override = os.environ.get("CODE_ONTOLOGY_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "CodeOntologyCompanion"
        return Path.home() / "AppData" / "Local" / "CodeOntologyCompanion"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CodeOntologyCompanion"
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share") / (
        "code-ontology-companion"
    )


def _registry_path() -> Path:
    return _data_home() / "registry.json"


def _load_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return {"schemaVersion": 1, "workspaces": []}
    value = _read_json(path, "Companion registry")
    if value.get("schemaVersion") != 1 or not isinstance(value.get("workspaces"), list):
        raise CompanionError("Unsupported companion registry.")
    return value


def _register_workspace(workspace: Path, config: dict[str, Any]) -> None:
    registry = _load_registry()
    items = [
        item
        for item in registry["workspaces"]
        if isinstance(item, dict) and item.get("id") != config["workspaceId"]
    ]
    items.append(
        {
            "id": config["workspaceId"],
            "label": config["repositoryLabel"],
            "workspace": str(workspace),
            "registeredAt": _now(),
        }
    )
    registry["workspaces"] = sorted(items, key=lambda item: (item["label"].lower(), item["id"]))
    _atomic_json(_registry_path(), registry)


def list_workspaces() -> dict[str, Any]:
    registry = _load_registry()
    available: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for item in registry["workspaces"]:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("workspace", ""))).expanduser()
        summary = {"id": item.get("id"), "label": item.get("label")}
        if path.is_dir() and (path / "companion.json").is_file():
            available.append(summary)
        else:
            stale.append(summary)
    return {
        "status": "ok",
        "workspaces": available,
        "staleRegistrations": stale,
        "registryContainsAbsolutePaths": True,
    }


def resolve_registered_workspace(workspace_id: str) -> Path:
    registry = _load_registry()
    matches = [
        item
        for item in registry["workspaces"]
        if isinstance(item, dict) and item.get("id") == workspace_id
    ]
    if not matches:
        raise CompanionError(f"Unknown workspace id: {workspace_id}")
    workspace, _ = _workspace(str(matches[-1].get("workspace", "")))
    return workspace


def _manifest(repo: Path) -> dict[str, Any]:
    sources, skipped = core.discover_sources(repo)
    files: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for source in sources:
        try:
            content = core._safe_read_bytes(source)
            relative = source.relative_to(repo).as_posix()
        except (OSError, ValueError, core.OntologyError):
            raise CompanionError("A source changed or became unreadable during snapshot planning.")
        file_hash = hashlib.sha256(content).hexdigest()
        item = {
            "path": relative,
            "language": core.SUPPORTED_SUFFIXES[source.suffix.lower()],
            "bytes": len(content),
            "sha256": file_hash,
        }
        files.append(item)
        digest.update(_json_bytes(item))
    return {
        "algorithm": "sha256",
        "fingerprint": digest.hexdigest(),
        "files": files,
        "skipped": dict(sorted(skipped.items())),
    }


def _git_revision(repo: Path) -> str | None:
    git_dir = repo / ".git"
    try:
        git_stat = git_dir.lstat()
    except OSError:
        return None
    if _is_link_like(git_stat) or not stat.S_ISDIR(git_stat.st_mode):
        return None
    head = git_dir / "HEAD"
    try:
        value = _read_regular_bytes(head, "Git HEAD", 4096).decode("utf-8").strip()
    except (CompanionError, UnicodeError):
        return None
    if value.startswith("ref: "):
        ref_name = value[5:].strip()
        if (
            "\\" in ref_name
            or not re.fullmatch(r"refs/(?:heads|tags)/[A-Za-z0-9._/-]+", ref_name)
            or any(part in {"", ".", ".."} for part in ref_name.split("/"))
        ):
            return None
        try:
            git_root = git_dir.resolve()
            refs_root = (git_dir / "refs").resolve()
            if not core._is_relative_to(refs_root, git_root):
                return None
            ref_path = (git_dir / ref_name).resolve()
            if not core._is_relative_to(ref_path, refs_root):
                return None
            value = _read_regular_bytes(ref_path, "Git reference", 4096).decode(
                "utf-8"
            ).strip()
        except (CompanionError, OSError, UnicodeError):
            return None
    return value if len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value) else None


def _state(workspace: Path) -> dict[str, Any]:
    path = workspace / "state.json"
    if not path.exists():
        return {"schemaVersion": 1, "currentSnapshot": None, "previousSnapshot": None}
    value = _read_json(path, "Workspace state")
    if value.get("schemaVersion") != 1:
        raise CompanionError("Unsupported workspace state.")
    return value


def _append_journal(workspace: Path, event: dict[str, Any]) -> None:
    path = workspace / "lineage.jsonl"
    payload = _json_bytes(event) + b"\n"
    flags = os.O_APPEND | os.O_WRONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        initial_stat = path.lstat()
    except FileNotFoundError:
        initial_stat = None
        flags |= os.O_CREAT | os.O_EXCL
    except OSError as exc:
        raise CompanionError(f"Lineage journal is unreadable: {exc}") from exc
    if initial_stat is not None and (
        _is_link_like(initial_stat) or not stat.S_ISREG(initial_stat.st_mode)
    ):
        raise CompanionError("Lineage journal must be a regular file.")
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except OSError as exc:
        raise CompanionError(f"Lineage journal could not be opened safely: {exc}") from exc
    try:
        opened_stat = os.fstat(descriptor)
        if _is_link_like(opened_stat) or not stat.S_ISREG(opened_stat.st_mode):
            raise CompanionError("Lineage journal must be a regular file.")
        if getattr(opened_stat, "st_nlink", 1) != 1:
            raise CompanionError("Lineage journal may not have multiple filesystem links.")
        try:
            current_stat = path.lstat()
        except OSError as exc:
            raise CompanionError(f"Lineage journal could not be verified: {exc}") from exc
        if _is_link_like(current_stat) or not stat.S_ISREG(current_stat.st_mode):
            raise CompanionError("Lineage journal must be a regular file.")
        if getattr(current_stat, "st_nlink", 1) != 1:
            raise CompanionError("Lineage journal may not have multiple filesystem links.")
        if not core._same_file(opened_stat, current_stat):
            raise CompanionError("Lineage journal changed before append.")
        if initial_stat is not None and not core._same_file(initial_stat, opened_stat):
            raise CompanionError("Lineage journal changed before append.")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _render_lineage_turtle(workspace)


def _read_journal(workspace: Path) -> list[dict[str, Any]]:
    path = workspace / "lineage.jsonl"
    try:
        path.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        raise CompanionError("Lineage journal is unreadable.")
    events: list[dict[str, Any]] = []
    try:
        content = _read_regular_bytes(path, "Lineage journal").decode("utf-8")
        for line_number, line in enumerate(content.splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} is not an object")
            events.append(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CompanionError(f"Lineage journal is invalid: {exc}")
    return events


def _ttl_literal(value: Any) -> str:
    return core._turtle_literal(value)


def _render_lineage_turtle(workspace: Path) -> None:
    lines = [
        f"@prefix coc: <{PROVENANCE_NS}> .",
        f"@prefix prov: <{PROV_NS}> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for event in _read_journal(workspace):
        event_id = str(event.get("eventId", "")).replace("-", "")
        if not event_id:
            continue
        subject = f"coc:event-{event_id}"
        lines.extend(
            [
                f"{subject} a prov:Activity ;",
                f"  rdfs:label {_ttl_literal(event.get('summary', ''))} ;",
                f"  coc:eventKind {_ttl_literal(event.get('kind', ''))} ;",
                f"  coc:evidenceType {_ttl_literal(event.get('evidenceType', ''))} ;",
                f"  prov:generatedAtTime {_ttl_literal(event.get('recordedAt', ''))} ;",
            ]
        )
        optional_values = [
            ("coc:subject", event.get("subject")),
            ("coc:snapshotId", event.get("snapshotId")),
            ("coc:previousSnapshotId", event.get("previousSnapshotId")),
            ("coc:repositoryRevision", event.get("repositoryRevision")),
        ]
        present = [(predicate, value) for predicate, value in optional_values if value]
        for index, (predicate, value) in enumerate(present):
            terminal = " ." if index == len(present) - 1 else " ;"
            lines.append(f"  {predicate} {_ttl_literal(value)}{terminal}")
        if not present:
            lines[-1] = lines[-1][:-1] + "."
        lines.append("")
    _atomic_write(workspace / "lineage.ttl", ("\n".join(lines) + "\n").encode("utf-8"), 0o600)


def _ollama_runtime_indicator() -> bool:
    if shutil.which("ollama"):
        return True
    if sys.platform != "darwin":
        return False
    try:
        metadata = OLLAMA_MACOS_APP.lstat()
    except OSError:
        return False
    return not _is_link_like(metadata) and stat.S_ISDIR(metadata.st_mode)


def doctor(repo_path: str | None = None) -> dict[str, Any]:
    commands = {
        name: shutil.which(name)
        for name in ("git", "java", "ollama", "lms", "docker", "podman")
    }
    commands["ollama"] = commands["ollama"] or (
        "known-macos-app" if _ollama_runtime_indicator() else None
    )
    result: dict[str, Any] = {
        "status": "ok",
        "companionVersion": COMPANION_VERSION,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "python": {
            "version": platform.python_version(),
            "compatible": sys.version_info >= (3, 9),
            "executableLabel": Path(sys.executable).name,
        },
        "requiredDependencies": [],
        "optionalRuntimesDetected": {
            name: bool(path) for name, path in commands.items() if name in {"java", "ollama", "lms", "docker", "podman"}
        },
        "defaults": {
            "graphStore": "immutable JSON snapshots",
            "portableExport": "RDF 1.1 Turtle",
            "localLlmRequired": False,
            "networkRequired": False,
            "backgroundServiceInstalled": False,
        },
    }
    if repo_path:
        repo = _resolve_existing_dir(repo_path, "Repository")
        preflight = core.preflight_document(repo)
        result["repository"] = {
            "label": preflight["repository_name"],
            "sourceFileCount": preflight["source_file_count"],
            "supportedLanguages": preflight["supported_languages"],
        }
    return result


def preflight(repo_path: str) -> dict[str, Any]:
    repo = _resolve_existing_dir(repo_path, "Repository")
    result = core.preflight_document(repo)
    result["companion"] = {
        "version": COMPANION_VERSION,
        "writesDuringPreflight": False,
        "requiresLocalLlm": False,
        "requiresGraphDatabase": False,
        "nextStep": "Obtain authorization and choose a workspace outside the repository.",
    }
    return result


def _snapshot_metadata(path: Path) -> dict[str, Any]:
    return _read_json(path / "snapshot.json", "Snapshot metadata")


def _snapshot_path(workspace: Path, snapshot_id: str) -> Path:
    if not snapshot_id or snapshot_id in {".", ".."} or "/" in snapshot_id or "\\" in snapshot_id:
        raise CompanionError("Invalid snapshot id.")
    snapshots_root = _resolve_managed_directory(workspace, "snapshots")
    assert snapshots_root is not None
    path = snapshots_root / snapshot_id
    resolved = _resolve_existing_dir(path, "Snapshot")
    if resolved.parent != snapshots_root:
        raise CompanionError("Snapshot escaped the workspace.")
    return resolved


def _resolve_snapshot_alias(workspace: Path, value: str) -> str:
    state = _state(workspace)
    if value == "current":
        snapshot_id = state.get("currentSnapshot")
    elif value == "previous":
        snapshot_id = state.get("previousSnapshot")
    else:
        snapshot_id = value
    if not snapshot_id:
        raise CompanionError(f"Snapshot alias has no value: {value}")
    return str(snapshot_id)


def _create_snapshot(
    workspace: Path,
    config: dict[str, Any],
    trigger: str,
    planned_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = _resolve_existing_dir(config["repositoryRoot"], "Configured repository")
    before_manifest = planned_manifest or _manifest(repo)
    current_state = _state(workspace)
    current_id = current_state.get("currentSnapshot")
    previous_index_path: str | None = None
    if current_id:
        current_path = _snapshot_path(workspace, str(current_id))
        previous_index_path = str(current_path / "ontology.json")
        current_manifest = _read_json(current_path / "source-manifest.json", "Source manifest")
        current_snapshot = _snapshot_metadata(current_path)
        if (
            current_manifest.get("fingerprint") == before_manifest["fingerprint"]
            and current_snapshot.get("analyzerVersion") == core.PLUGIN_VERSION
            and current_snapshot.get("companionVersion") == COMPANION_VERSION
        ):
            return {
                "status": "no_change",
                "workspaceId": config["workspaceId"],
                "snapshotId": current_id,
                "fingerprint": before_manifest["fingerprint"],
            }

    run_id = str(uuid.uuid4())
    snapshots_root = _resolve_managed_directory(workspace, "snapshots", create=True)
    staging_root = _resolve_managed_directory(workspace, ".staging", create=True)
    assert snapshots_root is not None
    assert staging_root is not None
    staging = staging_root / run_id
    snapshot_id = f"{_timestamp_id()}-{before_manifest['fingerprint'][:12]}"
    final = snapshots_root / snapshot_id
    if final.exists():
        snapshot_id = f"{snapshot_id}-{run_id[:8]}"
        final = snapshots_root / snapshot_id

    started_at = _now()
    try:
        result = core.write_index(repo, staging, authorized=True, overwrite=False)
        after_manifest = _manifest(repo)
        if after_manifest["fingerprint"] != before_manifest["fingerprint"]:
            raise CompanionError(
                "Repository changed during analysis; staged artifacts were not promoted. Run sync again."
            )
        document = _read_json(staging / "ontology.json", "Staged ontology")
        document["companion"] = {
            "workspaceId": config["workspaceId"],
            "snapshotId": snapshot_id,
            "sourceFingerprint": before_manifest["fingerprint"],
            "evidenceType": "observed",
        }
        _atomic_json(staging / "ontology.json", document, 0o600)
        core.write_visualization(
            str(staging / "ontology.json"),
            str(staging / "graph.html"),
            max_nodes=core.VISUALIZATION_MAX_VISIBLE_NODES,
            overwrite=False,
            previous_index_path=previous_index_path,
        )
        snapshot = {
            "schemaVersion": 1,
            "snapshotId": snapshot_id,
            "workspaceId": config["workspaceId"],
            "repositoryLabel": config["repositoryLabel"],
            "repositoryRevision": _git_revision(repo),
            "sourceFingerprint": before_manifest["fingerprint"],
            "createdAt": _now(),
            "trigger": trigger,
            "analyzerVersion": core.PLUGIN_VERSION,
            "companionVersion": COMPANION_VERSION,
            "counts": result["statistics"],
        }
        _atomic_json(staging / "source-manifest.json", after_manifest, 0o600)
        _atomic_json(staging / "snapshot.json", snapshot, 0o600)
        os.replace(staging, final)
        state = {
            "schemaVersion": 1,
            "currentSnapshot": snapshot_id,
            "previousSnapshot": current_id,
            "promotedAt": snapshot["createdAt"],
            "lastRunId": run_id,
        }
        _atomic_json(workspace / "state.json", state, 0o600)
        _append_journal(
            workspace,
            {
                "eventId": str(uuid.uuid4()),
                "kind": "observation",
                "evidenceType": "observed",
                "summary": f"Promoted ontology snapshot {snapshot_id}",
                "subject": config["repositoryLabel"],
                "snapshotId": snapshot_id,
                "previousSnapshotId": current_id,
                "repositoryRevision": snapshot["repositoryRevision"],
                "recordedAt": snapshot["createdAt"],
                "runId": run_id,
                "trigger": trigger,
            },
        )
        return {
            "status": "promoted",
            "workspaceId": config["workspaceId"],
            "snapshotId": snapshot_id,
            "previousSnapshotId": current_id,
            "counts": result["statistics"],
            "sourceFileCount": len(before_manifest["files"]),
            "portableRdf": str(final / "ontology.ttl"),
            "visualization": str(final / "graph.html"),
            "lineage": str(workspace / "lineage.ttl"),
            "targetCodeExecuted": False,
            "networkAccess": False,
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if staging_root.exists():
            try:
                staging_root.rmdir()
            except OSError:
                pass


def initialize(
    repo_path: str,
    workspace_path: str,
    authorized: bool,
    label: str | None = None,
) -> dict[str, Any]:
    if not authorized:
        raise CompanionError("Initialization requires --authorized.")
    repo = _resolve_existing_dir(repo_path, "Repository")
    workspace = _resolve_new_workspace(workspace_path, repo)
    planned = _manifest(repo)
    if not planned["files"]:
        raise CompanionError("No supported Java or Python source files were found.")
    workspace.mkdir(mode=0o700, parents=False, exist_ok=False)
    config = {
        "schemaVersion": WORKSPACE_SCHEMA_VERSION,
        "workspaceId": str(uuid.uuid4()),
        "repositoryLabel": (label or repo.name).strip() or repo.name,
        "repositoryRoot": str(repo),
        "createdAt": _now(),
        "privacy": {
            "storesAbsoluteRepositoryPathLocally": True,
            "storesSourceBodies": False,
            "storesPerFileSha256Locally": True,
            "networkAccess": False,
        },
    }
    try:
        _atomic_json(workspace / "companion.json", config, 0o600)
        result = _create_snapshot(workspace, config, trigger="initialize", planned_manifest=planned)
        _register_workspace(workspace, config)
        result["workspace"] = str(workspace)
        result["repositoryLabel"] = config["repositoryLabel"]
        return result
    except Exception:
        # Initialization owns the newly-created, previously nonexistent path.
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def sync(workspace_path: str, trigger: str = "manual") -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    return _create_snapshot(workspace, config, trigger=trigger)


def status(workspace_path: str, check_freshness: bool = True) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    state = _state(workspace)
    current_id = state.get("currentSnapshot")
    if not current_id:
        return {
            "status": "partial",
            "workspaceId": config["workspaceId"],
            "repositoryLabel": config["repositoryLabel"],
            "freshness": "partial",
            "message": "No promoted snapshot exists.",
        }
    snapshot_path = _snapshot_path(workspace, str(current_id))
    snapshot = _snapshot_metadata(snapshot_path)
    document = _read_json(snapshot_path / "ontology.json", "Ontology index")
    version_current = (
        snapshot.get("analyzerVersion") == core.PLUGIN_VERSION
        and snapshot.get("companionVersion") == COMPANION_VERSION
    )
    freshness = "stale" if not version_current else "unknown"
    if check_freshness and version_current:
        repo = _resolve_existing_dir(config["repositoryRoot"], "Configured repository")
        current_manifest = _manifest(repo)
        freshness = (
            "current"
            if current_manifest["fingerprint"] == snapshot["sourceFingerprint"]
            else "stale"
        )
    return {
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "repositoryLabel": config["repositoryLabel"],
        "snapshotId": current_id,
        "previousSnapshotId": state.get("previousSnapshot"),
        "generatedAt": snapshot.get("createdAt"),
        "freshness": freshness,
        "snapshotAnalyzerVersion": snapshot.get("analyzerVersion"),
        "currentAnalyzerVersion": core.PLUGIN_VERSION,
        "snapshotCompanionVersion": snapshot.get("companionVersion"),
        "currentCompanionVersion": COMPANION_VERSION,
        "evidenceType": "observed",
        "counts": snapshot.get("counts", {}),
        "quality": _quality_summary(document),
        "pipelineStatus": "healthy" if freshness != "stale" else "refresh_required",
        "message": (
            "Run sync to rebuild with the current analyzer and Companion."
            if not version_current
            else None
        ),
        "portableRdf": str(snapshot_path / "ontology.ttl"),
        "visualization": str(snapshot_path / "graph.html"),
    }


def history(workspace_path: str, limit: int = 20) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    snapshots_root = _resolve_managed_directory(
        workspace,
        "snapshots",
        required=False,
    )
    items: list[dict[str, Any]] = []
    if snapshots_root is not None:
        for child in sorted(snapshots_root.iterdir(), key=lambda path: path.name, reverse=True):
            if len(items) >= limit:
                break
            try:
                child_stat = child.lstat()
            except OSError as exc:
                raise CompanionError(f"Snapshot entry is unreadable: {child.name}: {exc}") from exc
            if _is_link_like(child_stat):
                raise CompanionError(
                    f"Snapshot may not be a symbolic link or reparse point: {child.name}"
                )
            if not stat.S_ISDIR(child_stat.st_mode):
                continue
            try:
                snapshot = _snapshot_path(workspace, child.name)
                metadata = _snapshot_metadata(snapshot)
            except CompanionError:
                continue
            items.append(
                {
                    "snapshotId": metadata.get("snapshotId"),
                    "createdAt": metadata.get("createdAt"),
                    "repositoryRevision": metadata.get("repositoryRevision"),
                    "trigger": metadata.get("trigger"),
                    "counts": metadata.get("counts", {}),
                }
            )
    return {
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "snapshots": items,
        "truncated": len(items) >= limit,
    }


def _current_document(workspace: Path) -> tuple[str, dict[str, Any]]:
    current_id = _resolve_snapshot_alias(workspace, "current")
    snapshot = _snapshot_path(workspace, current_id)
    return current_id, _read_json(snapshot / "ontology.json", "Ontology index")


def _bounded_nonnegative_integer(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, maximum))


def _quality_summary(document: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, backward-compatible relationship-quality summary."""

    edges = document.get("edges")
    edge_count = min(len(edges), core.MAX_GRAPH_EDGES) if isinstance(edges, list) else 0
    quality = document.get("quality")
    if not isinstance(quality, dict):
        return {
            "status": "legacy_unknown",
            "contractVersion": "legacy_unknown",
            "totalEdges": edge_count,
            "documentedEdges": 0,
            "missingEvidence": edge_count,
            "coveragePercent": 0.0,
            "adapters": {},
        }

    relationship = quality.get("relationship_evidence")
    if not isinstance(relationship, dict):
        relationship = {}
    total_edges = _bounded_nonnegative_integer(
        relationship.get("total_edges"), core.MAX_GRAPH_EDGES
    )
    documented_edges = min(
        _bounded_nonnegative_integer(
            relationship.get("documented_edges"), core.MAX_GRAPH_EDGES
        ),
        total_edges,
    )
    missing_evidence = min(
        _bounded_nonnegative_integer(
            relationship.get("missing_evidence"), core.MAX_GRAPH_EDGES
        ),
        total_edges,
    )
    raw_coverage = relationship.get("coverage_percent")
    coverage_percent = 0.0
    if isinstance(raw_coverage, (int, float)) and not isinstance(raw_coverage, bool):
        numeric_coverage = float(raw_coverage)
        if math.isfinite(numeric_coverage):
            coverage_percent = round(max(0.0, min(numeric_coverage, 100.0)), 2)
    contract_version = quality.get("contract_version")
    if not isinstance(contract_version, str) or not contract_version.strip():
        contract_version = "unknown"
    else:
        contract_version = contract_version.strip()[:50]

    adapters: dict[str, dict[str, Any]] = {}
    raw_adapters = quality.get("adapters")
    if isinstance(raw_adapters, dict):
        for language in ("Java", "Python"):
            adapter = raw_adapters.get(language)
            if not isinstance(adapter, dict):
                continue
            adapter_status = adapter.get("status")
            if adapter_status not in ADAPTER_SUPPORT_STATUSES:
                continue
            raw_capabilities = adapter.get("capabilities")
            capabilities = (
                {
                    name: value
                    for name, value in sorted(raw_capabilities.items())[
                        :MAX_ADAPTER_CAPABILITIES
                    ]
                    if isinstance(name, str)
                    and re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", name)
                    and value in ADAPTER_SUPPORT_STATUSES
                }
                if isinstance(raw_capabilities, dict)
                else {}
            )
            raw_unsupported = adapter.get("unsupported_runtime")
            unsupported_runtime = (
                [
                    value
                    for value in raw_unsupported[:MAX_UNSUPPORTED_RUNTIME_ITEMS]
                    if isinstance(value, str)
                    and re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", value)
                ]
                if isinstance(raw_unsupported, list)
                else []
            )
            adapters[language] = {
                "status": adapter_status,
                "detected": adapter.get("detected") is True,
                "capabilities": capabilities,
                "unsupportedRuntime": unsupported_runtime,
            }
    return {
        "status": "documented",
        "contractVersion": contract_version,
        "totalEdges": total_edges,
        "documentedEdges": documented_edges,
        "missingEvidence": missing_evidence,
        "coveragePercent": coverage_percent,
        "adapters": adapters,
    }


def query(workspace_path: str, term: str, limit: int = 20) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    snapshot_id, document = _current_document(workspace)
    result = core.query_document(document, term, limit)
    result.update(
        {
            "workspaceId": config["workspaceId"],
            "snapshotId": snapshot_id,
            "freshness": "snapshot",
            "evidenceType": "observed",
        }
    )
    return result


def impact(workspace_path: str, symbol: str, depth: int = 2) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    snapshot_id, document = _current_document(workspace)
    result = core.impact_document(document, symbol, depth)
    for item in result.get("impact", []):
        if isinstance(item, dict) and not isinstance(item.get("evidence"), list):
            item["evidence"] = []
    result.update(
        {
            "workspaceId": config["workspaceId"],
            "snapshotId": snapshot_id,
            "freshness": "snapshot",
            "evidenceType": "observed",
            "interpretation": "possible static impact, not runtime proof",
        }
    )
    return result


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return str(edge.get("source")), str(edge.get("target")), str(edge.get("type"))


def _diff_change_basis(
    before_doc: dict[str, Any],
    after_doc: dict[str, Any],
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
) -> str:
    before_companion = before_doc.get("companion")
    after_companion = after_doc.get("companion")
    before_fingerprint = (
        before_companion.get("sourceFingerprint")
        if isinstance(before_companion, dict)
        else None
    ) or before_snapshot.get("sourceFingerprint")
    after_fingerprint = (
        after_companion.get("sourceFingerprint")
        if isinstance(after_companion, dict)
        else None
    ) or after_snapshot.get("sourceFingerprint")
    if not isinstance(before_fingerprint, str) or not isinstance(after_fingerprint, str):
        return "legacy_unknown"

    before_analyzer = before_snapshot.get("analyzerVersion")
    after_analyzer = after_snapshot.get("analyzerVersion")
    before_companion_version = before_snapshot.get("companionVersion")
    after_companion_version = after_snapshot.get("companionVersion")
    versions = (
        before_analyzer,
        after_analyzer,
        before_companion_version,
        after_companion_version,
    )
    version_known = all(isinstance(value, str) and value for value in versions)
    if before_fingerprint != after_fingerprint:
        if version_known and (
            before_analyzer != after_analyzer
            or before_companion_version != after_companion_version
        ):
            return "mixed"
        return "source_change"
    if not version_known:
        return "legacy_unknown"
    if before_analyzer != after_analyzer:
        return "analyzer_reinterpretation"
    if before_companion_version != after_companion_version:
        return "analysis_refresh"
    return "no_change"


def diff(
    workspace_path: str,
    before: str = "previous",
    after: str = "current",
    limit: int = 100,
) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    before_id = _resolve_snapshot_alias(workspace, before)
    after_id = _resolve_snapshot_alias(workspace, after)
    before_path = _snapshot_path(workspace, before_id)
    after_path = _snapshot_path(workspace, after_id)
    before_doc = _read_json(before_path / "ontology.json", "Before ontology")
    after_doc = _read_json(after_path / "ontology.json", "After ontology")
    before_snapshot = _snapshot_metadata(before_path)
    after_snapshot = _snapshot_metadata(after_path)
    before_nodes = {str(node["id"]): node for node in before_doc.get("nodes", [])}
    after_nodes = {str(node["id"]): node for node in after_doc.get("nodes", [])}
    before_edges = {_edge_key(edge) for edge in before_doc.get("edges", [])}
    after_edges = {_edge_key(edge) for edge in after_doc.get("edges", [])}
    added_node_ids = sorted(after_nodes.keys() - before_nodes.keys())
    removed_node_ids = sorted(before_nodes.keys() - after_nodes.keys())
    added_edges = sorted(after_edges - before_edges)
    removed_edges = sorted(before_edges - after_edges)

    def node_summary(node: dict[str, Any]) -> dict[str, Any]:
        summary = {
            key: node.get(key)
            for key in ("id", "name", "type", "language", "path")
            if node.get(key) is not None
        }
        qualified_name = node.get("qualified_name", node.get("qualifiedName"))
        if qualified_name is not None:
            summary["qualifiedName"] = qualified_name
        return summary

    return {
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "beforeSnapshotId": before_id,
        "afterSnapshotId": after_id,
        "changeBasis": _diff_change_basis(
            before_doc,
            after_doc,
            before_snapshot,
            after_snapshot,
        ),
        "quality": _quality_summary(after_doc),
        "counts": {
            "nodesAdded": len(added_node_ids),
            "nodesRemoved": len(removed_node_ids),
            "edgesAdded": len(added_edges),
            "edgesRemoved": len(removed_edges),
        },
        "nodesAdded": [node_summary(after_nodes[node_id]) for node_id in added_node_ids[:limit]],
        "nodesRemoved": [
            node_summary(before_nodes[node_id]) for node_id in removed_node_ids[:limit]
        ],
        "edgesAdded": [
            {"source": source, "type": edge_type, "target": target}
            for source, target, edge_type in added_edges[:limit]
        ],
        "edgesRemoved": [
            {"source": source, "type": edge_type, "target": target}
            for source, target, edge_type in removed_edges[:limit]
        ],
        "truncated": any(
            len(items) > limit
            for items in (added_node_ids, removed_node_ids, added_edges, removed_edges)
        ),
        "interpretation": "structural static diff; correlation is not causation",
    }


def record(
    workspace_path: str,
    kind: str,
    summary: str,
    evidence_type: str,
    subject: str | None = None,
) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    if kind not in EVENT_KINDS:
        raise CompanionError(f"Unsupported event kind: {kind}")
    if evidence_type not in EVIDENCE_TYPES:
        raise CompanionError(f"Unsupported evidence type: {evidence_type}")
    clean_summary = summary.strip()
    if not clean_summary or len(clean_summary) > 1000:
        raise CompanionError("Summary must contain 1 to 1000 characters.")
    clean_subject = (subject or "").strip()
    if len(clean_subject) > 300:
        raise CompanionError("Subject must contain at most 300 characters.")
    state = _state(workspace)
    event = {
        "eventId": str(uuid.uuid4()),
        "kind": kind,
        "evidenceType": evidence_type,
        "summary": clean_summary,
        "subject": clean_subject or None,
        "snapshotId": state.get("currentSnapshot"),
        "recordedAt": _now(),
        "recordedBy": "local-user-or-agent",
    }
    _append_journal(workspace, event)
    return {
        "status": "recorded",
        "workspaceId": config["workspaceId"],
        "eventId": event["eventId"],
        "kind": kind,
        "evidenceType": evidence_type,
        "lineage": str(workspace / "lineage.ttl"),
    }


def lineage(
    workspace_path: str,
    limit: int = 50,
    evidence_type: str | None = None,
) -> dict[str, Any]:
    workspace, config = _workspace(workspace_path)
    if evidence_type is not None and evidence_type not in EVIDENCE_TYPES:
        raise CompanionError(f"Unsupported evidence type: {evidence_type}")
    events = _read_journal(workspace)
    if evidence_type is not None:
        events = [event for event in events if event.get("evidenceType") == evidence_type]
    selected = list(reversed(events[-limit:]))
    public_events = [
        {
            key: event.get(key)
            for key in (
                "eventId",
                "kind",
                "evidenceType",
                "summary",
                "subject",
                "snapshotId",
                "previousSnapshotId",
                "recordedAt",
            )
            if event.get(key) is not None
        }
        for event in selected
    ]
    return {
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "events": public_events,
        "truncated": len(events) > limit,
    }


def watch(workspace_path: str, interval_seconds: int, max_cycles: int) -> int:
    workspace, config = _workspace(workspace_path)
    cycles = 0
    last_fingerprint: str | None = None
    while max_cycles == 0 or cycles < max_cycles:
        cycles += 1
        repo = _resolve_existing_dir(config["repositoryRoot"], "Configured repository")
        planned = _manifest(repo)
        if planned["fingerprint"] != last_fingerprint:
            result = _create_snapshot(
                workspace,
                config,
                trigger="foreground-watch",
                planned_manifest=planned,
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            last_fingerprint = planned["fingerprint"]
        if max_cycles and cycles >= max_cycles:
            break
        time.sleep(interval_seconds)
    return 0


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="companion.py",
        description="Maintain a local, versioned code ontology without executing target code.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("doctor", help="Read-only runtime and capability check.")
    command.add_argument("--repo", help="Optional authorized repository to include in the check.")

    command = subparsers.add_parser("preflight", help="Read-only repository scan; writes nothing.")
    command.add_argument("--repo", required=True)

    command = subparsers.add_parser("init", help="Create a local Companion workspace.")
    command.add_argument("--repo", required=True)
    command.add_argument("--workspace", required=True)
    command.add_argument("--label")
    command.add_argument("--authorized", action="store_true")

    command = subparsers.add_parser("sync", help="Create and atomically promote a changed snapshot.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--trigger", default="manual")

    command = subparsers.add_parser("status", help="Inspect workspace and source freshness.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--no-freshness-check", action="store_true")

    subparsers.add_parser("list", help="List registered Companion workspaces.")

    command = subparsers.add_parser("history", help="List immutable ontology snapshots.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--limit", type=int, default=20, choices=range(1, 201), metavar="1..200")

    command = subparsers.add_parser("query", help="Search the current ontology snapshot.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--term", required=True)
    command.add_argument("--limit", type=int, default=20, choices=range(1, 201), metavar="1..200")

    command = subparsers.add_parser("impact", help="Explore bounded possible static impact.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--symbol", required=True)
    command.add_argument("--depth", type=int, default=2, choices=range(1, 6), metavar="1..5")

    command = subparsers.add_parser("diff", help="Compare two immutable snapshots.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--before", default="previous")
    command.add_argument("--after", default="current")
    command.add_argument("--limit", type=int, default=100, choices=range(1, 501), metavar="1..500")

    command = subparsers.add_parser("record", help="Append a declared or validated lineage event.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--kind", required=True, choices=sorted(EVENT_KINDS))
    command.add_argument("--evidence-type", required=True, choices=sorted(EVIDENCE_TYPES))
    command.add_argument("--summary", required=True)
    command.add_argument("--subject")

    command = subparsers.add_parser("lineage", help="List recorded provenance events.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--limit", type=int, default=50, choices=range(1, 501), metavar="1..500")
    command.add_argument("--evidence-type", choices=sorted(EVIDENCE_TYPES))

    command = subparsers.add_parser(
        "watch",
        help="Run an explicit foreground polling loop; never installs a daemon.",
    )
    command.add_argument("--workspace", required=True)
    command.add_argument(
        "--interval-seconds",
        type=int,
        default=10,
        choices=range(2, 3601),
        metavar="2..3600",
    )
    command.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        choices=range(0, 1000001),
        metavar="0..1000000",
        help="0 runs until interrupted; positive values make bounded runs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            _json_print(doctor(args.repo))
        elif args.command == "preflight":
            _json_print(preflight(args.repo))
        elif args.command == "init":
            _json_print(initialize(args.repo, args.workspace, args.authorized, args.label))
        elif args.command == "sync":
            _json_print(sync(args.workspace, args.trigger))
        elif args.command == "status":
            _json_print(status(args.workspace, check_freshness=not args.no_freshness_check))
        elif args.command == "list":
            _json_print(list_workspaces())
        elif args.command == "history":
            _json_print(history(args.workspace, args.limit))
        elif args.command == "query":
            _json_print(query(args.workspace, args.term, args.limit))
        elif args.command == "impact":
            _json_print(impact(args.workspace, args.symbol, args.depth))
        elif args.command == "diff":
            _json_print(diff(args.workspace, args.before, args.after, args.limit))
        elif args.command == "record":
            _json_print(
                record(
                    args.workspace,
                    args.kind,
                    args.summary,
                    args.evidence_type,
                    args.subject,
                )
            )
        elif args.command == "lineage":
            _json_print(lineage(args.workspace, args.limit, args.evidence_type))
        elif args.command == "watch":
            return watch(args.workspace, args.interval_seconds, args.max_cycles)
        else:
            parser.error(f"Unknown command: {args.command}")
    except (CompanionError, core.OntologyError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped", "message": "Foreground watcher stopped."}))
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
