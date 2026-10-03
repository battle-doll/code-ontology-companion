#!/usr/bin/env python3
"""Sequential, module-partitioned Companion snapshots for large repositories.

This module coordinates ordinary scoped Companion workspaces. It never builds a
combined ontology graph, executes target code, or performs network access.
"""
from __future__ import annotations

import copy
import hashlib
import html
import os
import re
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

import code_ontology_core as core
import companion


SCHEMA_VERSION = 1
MAX_MODULES = 128
CATALOG_DIR = "catalog-snapshots"
MODULES_DIR = "modules"
STAGING_DIR = ".catalog-staging"
LIMITATIONS = [
    "Modules are analyzed independently; cross-module edges are not inferred.",
    "Counts are reported per module and are not claimed as globally unique.",
    "Static source evidence does not prove runtime behavior.",
    "Each module retains the ordinary Companion source and graph safety limits.",
]
FRESHNESS_CAVEAT = (
    "Results describe catalog-pinned snapshots; source freshness is not checked by retrieval. "
    "Use large-status for a current source check."
)
WORKFLOW = {
    "produce": ["large-preflight", "large-init", "large-sync"],
    "ai": ["large-modules", "large-query", "large-impact"],
    "human": "Open the catalog, choose a pinned module, and add or remove cumulative layers.",
    "moduleGraphMode": "normal",
    "crossModuleResolution": "unsupported",
}


def _module_id(root: str) -> str:
    return "module-" + hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]


def _managed_directory(
    workspace: Path, name: str, create: bool = False, required: bool = True,
) -> Optional[Path]:
    if name not in {MODULES_DIR, CATALOG_DIR, STAGING_DIR}:
        raise companion.CompanionError("Unsupported large-project managed directory.")
    workspace = workspace.resolve()
    candidate = workspace / name
    if create:
        try:
            candidate.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            pass
        except OSError as exc:
            raise companion.CompanionError(
                "Large-project managed directory could not be created: %s: %s" % (name, exc)
            ) from exc
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        if required:
            raise companion.CompanionError("Large-project managed directory is missing: %s" % name)
        return None
    except OSError as exc:
        raise companion.CompanionError(
            "Large-project managed directory is unreadable: %s: %s" % (name, exc)
        ) from exc
    if companion._is_link_like(info) or not stat.S_ISDIR(info.st_mode):
        raise companion.CompanionError(
            "Large-project managed directory may not be a symbolic link or reparse point: %s" % name
        )
    resolved = candidate.resolve()
    if resolved.parent != workspace or resolved.name != name:
        raise companion.CompanionError("Large-project managed directory escaped the workspace: %s" % name)
    return resolved


def _validate_module_roots(repo: Path, module_roots: Iterable[str]) -> list[str]:
    if module_roots is None or isinstance(module_roots, (str, bytes, dict)):
        raise core.OntologyError(
            "Large-project mode requires a list of repository-relative module roots."
        )
    try:
        requested = list(module_roots)
    except TypeError as exc:
        raise core.OntologyError(
            "Large-project mode requires a list of repository-relative module roots."
        ) from exc
    if not 1 <= len(requested) <= MAX_MODULES:
        raise core.OntologyError("Large-project mode requires from 1 to 128 module roots.")
    if any(not isinstance(root, str) for root in requested):
        raise core.OntologyError("Module roots must be repository-relative directory paths.")
    if len(set(requested)) != len(requested):
        raise core.OntologyError("Duplicate module roots are not allowed.")

    normalized = []
    for raw in requested:
        roots = core.normalize_source_roots(repo, [raw])
        if len(roots) != 1:
            raise core.OntologyError("Each module root must name one directory below the repository root.")
        normalized.append(roots[0])
    for index, root in enumerate(normalized):
        for other in normalized[index + 1:]:
            if root.startswith(other + "/") or other.startswith(root + "/"):
                raise core.OntologyError("Module roots may not overlap.")
    return normalized


def _per_module_limits() -> dict[str, Any]:
    return {
        "maxSourceBytes": core.MAX_SOURCE_BYTES,
        "maxSourceFiles": core.MAX_SOURCE_FILES,
        "maxTotalSourceBytes": core.MAX_TOTAL_SOURCE_BYTES,
        "maxGraphNodes": core.MAX_GRAPH_NODES,
        "maxGraphEdges": core.MAX_GRAPH_EDGES,
        "followsSymlinks": False,
        "executesTargetCode": False,
        "networkAccess": False,
    }


def preflight(repo_path: str, module_roots: Iterable[str]) -> dict[str, Any]:
    repo = companion._resolve_existing_dir(repo_path, "Repository")
    roots = _validate_module_roots(repo, module_roots)
    modules = []
    ready = True
    for root in roots:
        checked = core.preflight_document(repo, [root])
        manifest = companion._manifest(repo, [root])
        ready = ready and checked["status"] == "ready"
        modules.append(
            {
                "moduleId": _module_id(root),
                "root": root,
                "status": checked["status"],
                "sourceFileCount": len(manifest.get("files", [])),
                "supportedSourceBytes": sum(
                    item.get("bytes", 0) for item in manifest.get("files", [])
                    if isinstance(item, dict) and isinstance(item.get("bytes"), int)
                ),
                "supportedLanguages": checked["supported_languages"],
                "skipped": checked["skipped"],
            }
        )
    return {
        "mode": "large",
        "status": "ready" if ready else "no_supported_sources",
        "repositoryLabel": repo.name,
        "moduleCount": len(modules),
        "modules": modules,
        "perModuleLimits": _per_module_limits(),
        "limitations": list(LIMITATIONS),
        "writesDuringPreflight": False,
        "targetCodeExecuted": False,
        "networkAccess": False,
        "workflow": copy.deepcopy(WORKFLOW),
    }


def _large_workspace(raw_path: str) -> tuple[Path, dict[str, Any], Path]:
    workspace = companion._resolve_existing_dir(raw_path, "Large-project workspace")
    config = companion._read_json(workspace / "large-project.json", "Large-project configuration")
    if config.get("schemaVersion") != SCHEMA_VERSION:
        raise companion.CompanionError("Unsupported large-project workspace schema.")
    workspace_id = config.get("workspaceId")
    try:
        valid_workspace_id = str(uuid.UUID(workspace_id)) == workspace_id
    except (AttributeError, TypeError, ValueError):
        valid_workspace_id = False
    if not valid_workspace_id:
        raise companion.CompanionError("Invalid large-project workspace id.")
    repository_root = config.get("repositoryRoot")
    if not isinstance(repository_root, str):
        raise companion.CompanionError("Invalid configured repository path.")
    repository_label = config.get("repositoryLabel")
    if (
        not isinstance(repository_label, str)
        or not repository_label.strip()
        or len(repository_label) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in repository_label)
    ):
        raise companion.CompanionError("Invalid large-project repository label.")
    repo = companion._resolve_existing_dir(repository_root, "Configured repository")
    if core._is_relative_to(workspace, repo) or core._is_relative_to(repo, workspace):
        raise companion.CompanionError("Workspace and repository boundaries overlap.")
    raw_modules = config.get("modules")
    if not isinstance(raw_modules, list):
        raise companion.CompanionError("Large-project module configuration is invalid.")
    roots = []
    for item in raw_modules:
        if not isinstance(item, dict) or set(item) != {"moduleId", "root"}:
            raise companion.CompanionError("Large-project module configuration is invalid.")
        roots.append(item.get("root"))
    try:
        normalized = _validate_module_roots(repo, roots)
    except core.OntologyError as exc:
        raise companion.CompanionError("Large-project module configuration is invalid: %s" % exc) from exc
    for item, root in zip(raw_modules, normalized):
        if item.get("root") != root or item.get("moduleId") != _module_id(root):
            raise companion.CompanionError("Large-project module identity is invalid.")
    _managed_directory(workspace, MODULES_DIR)
    _managed_directory(workspace, CATALOG_DIR)
    return workspace, config, repo


def _child_path(workspace: Path, module_id: str, require_existing: bool = True) -> Path:
    if module_id != module_id.strip() or not re.fullmatch(r"module-[0-9a-f]{16}", module_id):
        raise companion.CompanionError("Invalid large-project module id.")
    root = _managed_directory(workspace, MODULES_DIR)
    assert root is not None
    candidate = root / module_id
    if not require_existing:
        if candidate.exists() or candidate.is_symlink():
            raise companion.CompanionError("Module workspace already exists.")
        return candidate
    child = companion._resolve_existing_dir(candidate, "Module workspace")
    if child.parent != root or child.name != module_id:
        raise companion.CompanionError("Module workspace escaped the large-project workspace.")
    return child


def _state(workspace: Path) -> dict[str, Any]:
    value = companion._read_json(workspace / "state.json", "Large-project state")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise companion.CompanionError("Unsupported large-project state.")
    current = value.get("currentCatalogSnapshot")
    previous = value.get("previousCatalogSnapshot")
    for snapshot_id in (current, previous):
        if snapshot_id is not None and (
            not isinstance(snapshot_id, str)
            or snapshot_id in {"", ".", ".."}
            or "/" in snapshot_id
            or "\\" in snapshot_id
        ):
            raise companion.CompanionError("Invalid catalog snapshot id.")
    return value


def _catalog_path(workspace: Path, snapshot_id: str) -> Path:
    if (
        not isinstance(snapshot_id, str)
        or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}(?:-[0-9a-f]{8})?", snapshot_id)
    ):
        raise companion.CompanionError("Invalid catalog snapshot id.")
    root = _managed_directory(workspace, CATALOG_DIR)
    assert root is not None
    path = companion._resolve_existing_dir(root / snapshot_id, "Catalog snapshot")
    if path.parent != root or path.name != snapshot_id:
        raise companion.CompanionError("Catalog snapshot escaped the workspace.")
    return path


def _aggregate_fingerprint(modules: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in modules:
        digest.update(
            companion._json_bytes(
                {"moduleId": item["moduleId"], "root": item["root"], "sourceFingerprint": item["sourceFingerprint"]}
            )
        )
    return digest.hexdigest()


def _catalog_html(catalog: dict[str, Any]) -> bytes:
    rows = []
    for module in catalog["modules"]:
        counts = module.get("counts", {})
        link = "../../modules/%s/snapshots/%s/graph.html" % (
            module["moduleId"], module["snapshotId"],
        )
        rows.append(
            "<tr><th scope=\"row\">%s</th><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td><code>%s</code></td><td><a href=\"%s\">Open normal-mode module graph</a></td></tr>"
            % (
                html.escape(module["root"]),
                html.escape(str(module.get("sourceFileCount", "unknown"))),
                html.escape(str(module.get("supportedSourceBytes", "unknown"))),
                html.escape(str(counts.get("nodes", "unknown"))),
                html.escape(str(counts.get("edges", "unknown"))),
                html.escape(module["snapshotId"]),
                html.escape(link, quote=True),
            )
        )
    limitations = "".join("<li>%s</li>" % html.escape(item) for item in LIMITATIONS)
    document = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "script-src 'none'; style-src 'none'; connect-src 'none'; img-src 'none'\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Large analysis mode — module catalog</title></head><body>"
        "<p>Large analysis mode</p><h1>%s</h1><p>Catalog snapshot %s</p><p>Selected modules: %s. "
        "Supported source files: %s. Supported source bytes: %s.</p><p>"
        "Each row is pinned to an immutable module snapshot; counts are per module.</p>"
        "<p>Choose a module to open its normal-mode graph. Add and remove cumulative layers "
        "in that graph; the catalog does not load every graph into one screen.</p>"
        "<p>AI workflow: discover scopes with <code>large-modules</code>, search selected modules "
        "with <code>large-query</code>, then inspect one module with <code>large-impact</code>. "
        "Source freshness is not checked by catalog browsing; use <code>large-status</code>.</p>"
        "<table><caption>Selected module scopes</caption><thead><tr><th>Module</th>"
        "<th>Files</th><th>Supported bytes</th><th>Nodes</th><th>Edges</th>"
        "<th>Pinned snapshot</th><th>Offline graph</th></tr></thead><tbody>%s</tbody></table>"
        "<h2>Limits</h2><ul>%s</ul></body></html>"
        % (
            html.escape(catalog["repositoryLabel"]),
            html.escape(catalog["catalogSnapshotId"]),
            len(catalog["modules"]),
            sum(item["sourceFileCount"] for item in catalog["modules"]),
            sum(item["supportedSourceBytes"] for item in catalog["modules"]),
            "".join(rows),
            limitations,
        )
    )
    return document.encode("utf-8")


def _module_record(
    workspace: Path, repo: Path, configured: dict[str, Any], snapshot_id: str,
) -> dict[str, Any]:
    if (
        not isinstance(snapshot_id, str)
        or snapshot_id in {"", ".", ".."}
        or "/" in snapshot_id
        or "\\" in snapshot_id
    ):
        raise companion.CompanionError("Invalid module snapshot id.")
    child, child_config = _validated_child_workspace(workspace, repo, configured)
    snapshot = companion._snapshot_path(child, snapshot_id)
    metadata = companion._snapshot_metadata(snapshot)
    manifest = companion._read_json(snapshot / "source-manifest.json", "Module source manifest")
    root = configured["root"]
    if (
        child_config.get("sourceRoots") != [root]
        or metadata.get("workspaceId") != child_config.get("workspaceId")
        or metadata.get("snapshotId") != snapshot_id
        or metadata.get("sourceRoots") != [root]
        or manifest.get("sourceRoots") != [root]
        or metadata.get("sourceFingerprint") != manifest.get("fingerprint")
    ):
        raise companion.CompanionError("Module snapshot binding is invalid: %s" % root)
    fingerprint = manifest.get("fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise companion.CompanionError("Module source fingerprint is invalid: %s" % root)
    return {
        "moduleId": configured["moduleId"],
        "root": root,
        "workspaceId": child_config["workspaceId"],
        "snapshotId": snapshot_id,
        "sourceFingerprint": fingerprint,
        "analyzerVersion": metadata.get("analyzerVersion"),
        "companionVersion": metadata.get("companionVersion"),
        "sourceFileCount": len(manifest.get("files", [])) if isinstance(manifest.get("files"), list) else 0,
        "supportedSourceBytes": sum(
            item.get("bytes", 0) for item in manifest.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("bytes"), int)
        ),
        "counts": copy.deepcopy(metadata.get("counts", {})) if isinstance(metadata.get("counts"), dict) else {},
        "graph": "../../modules/%s/snapshots/%s/graph.html" % (configured["moduleId"], snapshot_id),
    }


def _validated_child_workspace(
    workspace: Path, repo: Path, configured: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    child = _child_path(workspace, configured["moduleId"])
    child_workspace, child_config = companion._workspace(child)
    child_repo = child_config.get("repositoryRoot")
    child_id = child_config.get("workspaceId")
    try:
        valid_child_id = str(uuid.UUID(child_id)) == child_id
    except (AttributeError, TypeError, ValueError):
        valid_child_id = False
    if (
        child_workspace != child
        or not isinstance(child_repo, str)
        or Path(child_repo).resolve() != repo
        or child_config.get("sourceRoots") != [configured["root"]]
        or not valid_child_id
    ):
        raise companion.CompanionError(
            "Module workspace binding is invalid: %s" % configured["root"]
        )
    return child, child_config


def _validate_final_manifests(repo: Path, modules: list[dict[str, Any]]) -> None:
    for module in modules:
        current = companion._manifest(repo, [module["root"]])
        if current.get("fingerprint") != module["sourceFingerprint"]:
            raise companion.CompanionError(
                "Repository changed before catalog promotion; prior catalog remains current."
            )


def _promote_catalog(
    workspace: Path,
    config: dict[str, Any],
    modules: list[dict[str, Any]],
    previous_id: Optional[str],
) -> dict[str, Any]:
    fingerprint = _aggregate_fingerprint(modules)
    run_id = str(uuid.uuid4())
    snapshot_id = "%s-%s" % (companion._timestamp_id(), fingerprint[:12])
    catalog_root = _managed_directory(workspace, CATALOG_DIR, create=True)
    staging_root = _managed_directory(workspace, STAGING_DIR, create=True)
    assert catalog_root is not None and staging_root is not None
    final = catalog_root / snapshot_id
    if final.exists():
        snapshot_id = "%s-%s" % (snapshot_id, run_id[:8])
        final = catalog_root / snapshot_id
    staging = staging_root / run_id
    created_at = companion._now()
    catalog = {
        "mode": "large",
        "schemaVersion": SCHEMA_VERSION,
        "catalogSnapshotId": snapshot_id,
        "workspaceId": config["workspaceId"],
        "repositoryLabel": config["repositoryLabel"],
        "createdAt": created_at,
        "previousCatalogSnapshotId": previous_id,
        "sourceFingerprint": fingerprint,
        "moduleCount": len(modules),
        "modules": modules,
        "perModuleLimits": _per_module_limits(),
        "limitations": list(LIMITATIONS),
        "targetCodeExecuted": False,
        "networkAccess": False,
        "workflow": copy.deepcopy(WORKFLOW),
    }
    try:
        staging.mkdir(mode=0o700, parents=False, exist_ok=False)
        companion._atomic_json(staging / "catalog.json", catalog, 0o600)
        companion._atomic_write(staging / "index.html", _catalog_html(catalog), 0o600)
        os.replace(staging, final)
        state = {
            "schemaVersion": SCHEMA_VERSION,
            "currentCatalogSnapshot": snapshot_id,
            "previousCatalogSnapshot": previous_id,
            "promotedAt": created_at,
            "lastRunId": run_id,
        }
        companion._atomic_json(workspace / "state.json", state, 0o600)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        try:
            staging_root.rmdir()
        except OSError:
            pass
    return {
        "mode": "large",
        "status": "promoted",
        "workspaceId": config["workspaceId"],
        "catalogSnapshotId": snapshot_id,
        "previousCatalogSnapshotId": previous_id,
        "moduleCount": len(modules),
        "modules": copy.deepcopy(modules),
        "catalog": str(final / "catalog.json"),
        "index": str(final / "index.html"),
        "targetCodeExecuted": False,
        "networkAccess": False,
        "workflow": copy.deepcopy(WORKFLOW),
    }


def _initialize_child(
    repo: Path, child: Path, root: str, label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    planned = companion._manifest(repo, [root])
    if not planned.get("files"):
        raise companion.CompanionError("No supported Java or Python source files were found: %s" % root)
    child.mkdir(mode=0o700, parents=False, exist_ok=False)
    config = {
        "schemaVersion": companion.WORKSPACE_SCHEMA_VERSION,
        "workspaceId": str(uuid.uuid4()),
        "repositoryLabel": "%s [%s]" % (label, root),
        "repositoryRoot": str(repo),
        "createdAt": companion._now(),
        "privacy": {
            "storesAbsoluteRepositoryPathLocally": True,
            "storesSourceBodies": False,
            "storesPerFileSha256Locally": True,
            "networkAccess": False,
        },
    }
    try:
        companion._atomic_json(child / "companion.json", config, 0o600)
        result = companion._create_snapshot(
            child,
            dict(config, sourceRoots=[root]),
            trigger="large-project-initialize",
            planned_manifest=planned,
        )
        return config, result
    except Exception:
        shutil.rmtree(child, ignore_errors=True)
        raise


def initialize(
    repo_path: str,
    workspace_path: str,
    authorized: bool,
    label: Optional[str] = None,
    module_roots: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    if not authorized:
        raise companion.CompanionError("Large-project initialization requires --authorized.")
    repo = companion._resolve_existing_dir(repo_path, "Repository")
    roots = _validate_module_roots(repo, module_roots)
    summary = preflight(str(repo), roots)
    if summary["status"] != "ready":
        raise companion.CompanionError("Every selected module must contain supported source files.")
    workspace = companion._resolve_new_workspace(workspace_path, repo)
    raw_label = label if label is not None else repo.name
    if not isinstance(raw_label, str) or not raw_label.strip() or len(raw_label.strip()) > 200:
        raise companion.CompanionError("Large-project label must contain from 1 to 200 characters.")
    repository_label = raw_label.strip()
    modules_config = [{"moduleId": _module_id(root), "root": root} for root in roots]
    config = {
        "schemaVersion": SCHEMA_VERSION,
        "workspaceId": str(uuid.uuid4()),
        "repositoryLabel": repository_label,
        "repositoryRoot": str(repo),
        "createdAt": companion._now(),
        "modules": modules_config,
        "privacy": {
            "storesAbsoluteRepositoryPathLocally": True,
            "portableCatalogContainsAbsolutePaths": False,
            "storesSourceBodies": False,
            "networkAccess": False,
        },
    }
    child_configs = []
    workspace.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        companion._atomic_json(workspace / "large-project.json", config, 0o600)
        _managed_directory(workspace, MODULES_DIR, create=True)
        _managed_directory(workspace, CATALOG_DIR, create=True)
        records = []
        for configured in modules_config:
            child = _child_path(workspace, configured["moduleId"], require_existing=False)
            child_config, result = _initialize_child(repo, child, configured["root"], repository_label)
            child_configs.append((child, child_config))
            records.append(_module_record(workspace, repo, configured, result["snapshotId"]))
        _validate_final_manifests(repo, records)
        promoted = _promote_catalog(workspace, config, records, None)
        _register_children(child_configs, parent=(workspace, config))
        promoted["workspace"] = str(workspace)
        promoted["repositoryLabel"] = repository_label
        return promoted
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def _register_children(
    children: list[tuple[Path, dict[str, Any]]],
    *, parent: Optional[tuple[Path, dict[str, Any]]] = None,
) -> None:
    """Publish parent and children with one atomic registry replacement."""
    registry = companion._load_registry()
    child_ids = {config["workspaceId"] for _path, config in children}
    if parent is not None:
        child_ids.add(parent[1]["workspaceId"])
    items = [
        item for item in registry["workspaces"]
        if isinstance(item, dict) and item.get("id") not in child_ids
    ]
    registered_at = companion._now()
    for path, config in children:
        items.append(
            {
                "id": config["workspaceId"],
                "label": config["repositoryLabel"],
                "workspace": str(path),
                "registeredAt": registered_at,
            }
        )
    if parent is not None:
        path, config = parent
        items.append({"id": config["workspaceId"], "label": config["repositoryLabel"],
                      "workspace": str(path), "mode": "large", "registeredAt": registered_at})
    registry["workspaces"] = sorted(
        items, key=lambda item: (str(item.get("label", "")).lower(), str(item.get("id", "")))
    )
    companion._atomic_json(companion._registry_path(), registry)


def _write_failed_run(
    workspace: Path,
    previous_id: Optional[str],
    current_id: Optional[str],
    advanced: list[dict[str, Any]],
    error: Exception,
) -> None:
    promoted = current_id != previous_id
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "failed",
        "recordedAt": companion._now(),
        "catalogPromoted": promoted,
        "preservedCatalogSnapshotId": previous_id if not promoted else None,
        "catalogSnapshotId": current_id,
        "advancedModules": advanced,
        "errorType": type(error).__name__,
        "error": str(error)[:1000],
    }
    companion._atomic_json(workspace / "last-run.json", report, 0o600)


def sync(workspace_path: str, force: bool = False) -> dict[str, Any]:
    if not isinstance(force, bool):
        raise companion.CompanionError("Force must be a boolean.")
    workspace, config, repo = _large_workspace(workspace_path)
    state = _state(workspace)
    previous_id = state.get("currentCatalogSnapshot")
    previous = _read_catalog(workspace, config, previous_id)
    previous_pins = {item["moduleId"]: item["snapshotId"] for item in previous["modules"]}
    records = []
    advanced = []
    try:
        for configured in config["modules"]:
            child, _child_config = _validated_child_workspace(workspace, repo, configured)
            result = companion.sync(
                str(child),
                trigger="large-project-sync",
                force=force,
            )
            record = _module_record(workspace, repo, configured, result["snapshotId"])
            records.append(record)
            pinned = previous_pins.get(configured["moduleId"])
            if record["snapshotId"] != pinned:
                advanced.append(
                    {
                        "moduleId": configured["moduleId"],
                        "root": configured["root"],
                        "pinnedSnapshotId": pinned,
                        "advancedSnapshotId": record["snapshotId"],
                    }
                )
        _validate_final_manifests(repo, records)
        if not force and not advanced:
            result = {
                "mode": "large",
                "status": "no_change",
                "workspaceId": config["workspaceId"],
                "catalogSnapshotId": previous_id,
                "moduleCount": len(records),
                "modules": copy.deepcopy(records),
                "targetCodeExecuted": False,
                "networkAccess": False,
                "workflow": copy.deepcopy(WORKFLOW),
            }
        else:
            result = _promote_catalog(workspace, config, records, previous_id)
        try:
            companion._atomic_json(
                workspace / "last-run.json",
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": result["status"],
                    "recordedAt": companion._now(),
                    "catalogPromoted": result["status"] == "promoted",
                    "catalogSnapshotId": result["catalogSnapshotId"],
                    "advancedModules": advanced,
                },
                0o600,
            )
        except (companion.CompanionError, OSError) as exc:
            result["reportWarning"] = "Catalog result committed, but last-run report failed: %s" % exc
        return result
    except (companion.CompanionError, core.OntologyError, OSError) as exc:
        try:
            current_id = _state(workspace).get("currentCatalogSnapshot")
        except companion.CompanionError:
            current_id = previous_id
        promoted = current_id != previous_id
        report_error = None
        try:
            _write_failed_run(workspace, previous_id, current_id, advanced, exc)
        except (companion.CompanionError, OSError) as write_exc:
            report_error = write_exc
        disposition = (
            "catalog pointer changed during the failed operation"
            if promoted
            else "prior catalog remains current"
        )
        raise companion.CompanionError(
            "Large-project sync failed; %s. Child snapshots advanced before failure: %s. Cause: %s%s"
            % (
                disposition,
                len(advanced),
                exc,
                " Last-run report also failed: %s" % report_error if report_error else "",
            )
        ) from exc


def _read_catalog(
    workspace: Path, config: dict[str, Any], snapshot_id: Optional[str],
) -> dict[str, Any]:
    if not snapshot_id:
        raise companion.CompanionError("No promoted catalog snapshot exists.")
    path = _catalog_path(workspace, snapshot_id)
    catalog = companion._read_json(path / "catalog.json", "Catalog snapshot")
    if (
        catalog.get("schemaVersion") != SCHEMA_VERSION
        or catalog.get("catalogSnapshotId") != snapshot_id
        or catalog.get("workspaceId") != config.get("workspaceId")
        or catalog.get("repositoryLabel") != config.get("repositoryLabel")
        or catalog.get("moduleCount") != len(config.get("modules", []))
    ):
        raise companion.CompanionError("Catalog snapshot binding is invalid.")
    raw_modules = catalog.get("modules")
    if not isinstance(raw_modules, list) or len(raw_modules) != len(config["modules"]):
        raise companion.CompanionError("Catalog module binding is invalid.")
    repository_root = config.get("repositoryRoot")
    if not isinstance(repository_root, str):
        raise companion.CompanionError("Catalog repository binding is invalid.")
    repo = companion._resolve_existing_dir(repository_root, "Configured repository")
    validated = []
    for expected, raw in zip(config["modules"], raw_modules):
        if not isinstance(raw, dict):
            raise companion.CompanionError("Catalog module binding is invalid.")
        if raw.get("moduleId") != expected["moduleId"] or raw.get("root") != expected["root"]:
            raise companion.CompanionError("Catalog module identity is invalid.")
        validated.append(_module_record(workspace, repo, expected, raw.get("snapshotId")))
        if (
            raw.get("workspaceId") != validated[-1]["workspaceId"]
            or raw.get("sourceFingerprint") != validated[-1]["sourceFingerprint"]
            or raw.get("analyzerVersion") != validated[-1]["analyzerVersion"]
            or raw.get("companionVersion") != validated[-1]["companionVersion"]
        ):
            raise companion.CompanionError("Catalog module snapshot provenance is invalid.")
    if catalog.get("sourceFingerprint") != _aggregate_fingerprint(validated):
        raise companion.CompanionError("Catalog source fingerprint is invalid.")
    catalog["modules"] = validated
    return catalog


def status(workspace_path: str) -> dict[str, Any]:
    workspace, config, repo = _large_workspace(workspace_path)
    state = _state(workspace)
    snapshot_id = state.get("currentCatalogSnapshot")
    catalog = _read_catalog(workspace, config, snapshot_id)
    modules = []
    all_current = True
    for pinned in catalog["modules"]:
        child = _child_path(workspace, pinned["moduleId"])
        child_state = companion._state(child)
        current_id = child_state.get("currentSnapshot")
        current_manifest = companion._manifest(repo, [pinned["root"]])
        source_current = current_manifest.get("fingerprint") == pinned["sourceFingerprint"]
        binding = "pinned_current" if current_id == pinned["snapshotId"] else "child_advanced"
        version_current = (
            pinned["analyzerVersion"] == core.PLUGIN_VERSION
            and pinned["companionVersion"] == companion.COMPANION_VERSION
        )
        all_current = all_current and source_current and version_current and binding == "pinned_current"
        modules.append(
            {
                "moduleId": pinned["moduleId"],
                "root": pinned["root"],
                "pinnedSnapshotId": pinned["snapshotId"],
                "childCurrentSnapshotId": current_id,
                "catalogBinding": binding,
                "freshness": "current" if source_current else "stale",
                "versionFreshness": "current" if version_current else "stale",
                "snapshotAnalyzerVersion": pinned["analyzerVersion"],
                "snapshotCompanionVersion": pinned["companionVersion"],
                "sourceFileCount": pinned["sourceFileCount"],
                "supportedSourceBytes": pinned["supportedSourceBytes"],
                "counts": copy.deepcopy(pinned["counts"]),
            }
        )
    return {
        "mode": "large",
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "repositoryLabel": config["repositoryLabel"],
        "catalogSnapshotId": snapshot_id,
        "previousCatalogSnapshotId": state.get("previousCatalogSnapshot"),
        "freshness": "current" if all_current else "stale",
        "pipelineStatus": "healthy" if all_current else "refresh_required",
        "moduleCount": len(modules),
        "modules": modules,
        "limitations": list(LIMITATIONS),
        "targetCodeExecuted": False,
        "networkAccess": False,
        "workflow": copy.deepcopy(WORKFLOW),
    }


def _page_arguments(offset: int, limit: int, maximum_offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= core.MAX_QUERY_RESULTS:
        raise core.OntologyError("Query limit must be from 1 to 200.")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= maximum_offset:
        raise core.OntologyError("Query offset is out of range.")


def _selected_modules(
    catalog: dict[str, Any], module_roots: Optional[Iterable[str]],
) -> list[dict[str, Any]]:
    if module_roots is None:
        return catalog["modules"]
    if isinstance(module_roots, (str, bytes, dict)):
        raise core.OntologyError("Select module roots as a list of exact configured paths.")
    try:
        requested = list(module_roots)
    except TypeError as exc:
        raise core.OntologyError("Select module roots as a list of exact configured paths.") from exc
    if not 1 <= len(requested) <= MAX_MODULES or any(not isinstance(root, str) for root in requested):
        raise core.OntologyError("Select from 1 to 128 exact configured module roots.")
    available = {item["root"] for item in catalog["modules"]}
    if len(set(requested)) != len(requested) or not set(requested) <= available:
        raise core.OntologyError("Module selection must contain unique exact configured roots.")
    return [item for item in catalog["modules"] if item["root"] in requested]


def modules(
    workspace_path: str, term: str = "", offset: int = 0, limit: int = 20,
    *, catalog_snapshot: Optional[str] = None,
) -> dict[str, Any]:
    """Discover pinned scopes using metadata only, without loading any ontology."""
    _page_arguments(offset, limit, MAX_MODULES)
    if not isinstance(term, str) or len(term) > 1000:
        raise core.OntologyError("Module term must contain at most 1000 characters.")
    workspace, config, _repo = _large_workspace(workspace_path)
    snapshot_id = catalog_snapshot if catalog_snapshot is not None else _state(workspace).get("currentCatalogSnapshot")
    catalog = _read_catalog(workspace, config, snapshot_id)
    needle = term.casefold()
    matched = [
        item for item in catalog["modules"]
        if needle in item["root"].casefold() or needle in item["moduleId"]
    ]
    page = copy.deepcopy(matched[offset:offset + limit])
    for item in page:
        item["freshness"] = "pinned_snapshot"
        item["versionFreshness"] = (
            "current"
            if item["analyzerVersion"] == core.PLUGIN_VERSION
            and item["companionVersion"] == companion.COMPANION_VERSION
            else "stale"
        )
        item["graphMode"] = "normal"
    next_offset = offset + len(page)
    return {
        "mode": "large",
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "repositoryLabel": config["repositoryLabel"],
        "catalogSnapshotId": catalog["catalogSnapshotId"],
        "moduleCount": len(catalog["modules"]),
        "matchedModuleCount": len(matched),
        "term": term,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "nextOffset": next_offset if next_offset < len(matched) else None,
        "truncated": next_offset < len(matched),
        "modules": page,
        "metadataOnly": True,
        "freshness": "pinned_snapshot",
        "freshnessCaveat": FRESHNESS_CAVEAT,
        "workflow": copy.deepcopy(WORKFLOW),
        "limitations": list(LIMITATIONS),
        "targetCodeExecuted": False,
        "networkAccess": False,
    }


def query(
    workspace_path: str, term: str, limit: int = 20,
    module_roots: Optional[Iterable[str]] = None, offset: int = 0,
    *, catalog_snapshot: Optional[str] = None,
    language: Optional[str] = None, node_type: Optional[str] = None,
    path_prefix: Optional[str] = None,
) -> dict[str, Any]:
    _page_arguments(offset, limit, MAX_MODULES * core.MAX_GRAPH_NODES)
    if not isinstance(term, str) or not term.strip() or len(term) > 1000:
        raise core.OntologyError("Query term must contain 1 to 1000 characters.")
    workspace, config, _repo = _large_workspace(workspace_path)
    snapshot_id = catalog_snapshot if catalog_snapshot is not None else _state(workspace).get("currentCatalogSnapshot")
    catalog = _read_catalog(workspace, config, snapshot_id)
    selected = _selected_modules(catalog, module_roots)
    matches = []
    module_counts = []
    occurrence_count = 0
    remaining_offset = offset
    for pinned in selected:
        child = _child_path(workspace, pinned["moduleId"])
        remaining = limit - len(matches)
        result = companion.query(
            str(child),
            term,
            remaining if remaining > 0 else 1,
            snapshot=pinned["snapshotId"],
            offset=min(remaining_offset, core.MAX_GRAPH_NODES),
            language=language, node_type=node_type, path_prefix=path_prefix,
        )
        count = result.get("match_count", 0)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= core.MAX_GRAPH_NODES:
            raise companion.CompanionError("Module query result is invalid.")
        occurrence_count += count
        module_counts.append(
            {
                "moduleId": pinned["moduleId"],
                "root": pinned["root"],
                "snapshotId": pinned["snapshotId"],
                "matchOccurrences": count,
                "scope": copy.deepcopy(result.get("scope", {})),
            }
        )
        if remaining_offset >= count:
            remaining_offset -= count
            continue
        remaining_offset = 0
        if remaining > 0:
            for node in result.get("matches", [])[:remaining]:
                matches.append(
                    {
                        "moduleId": pinned["moduleId"],
                        "moduleRoot": pinned["root"],
                        "moduleWorkspaceId": pinned["workspaceId"],
                        "moduleSnapshotId": pinned["snapshotId"],
                        "moduleSourceFingerprint": pinned["sourceFingerprint"],
                        "node": copy.deepcopy(node),
                    }
                )
    return {
        "mode": "large",
        "status": "ok",
        "workspaceId": config["workspaceId"],
        "catalogSnapshotId": catalog["catalogSnapshotId"],
        "term": term,
        "returned": len(matches),
        "limit": limit,
        "offset": offset,
        "nextOffset": offset + len(matches) if offset + len(matches) < occurrence_count else None,
        "order": "configured_module_order_then_module_search_rank",
        "selectedModuleRoots": [item["root"] for item in selected],
        "moduleCount": len(selected),
        "moduleMatchOccurrences": occurrence_count,
        "truncated": offset + len(matches) < occurrence_count,
        "matches": matches,
        "modules": module_counts,
        "evidenceType": "observed",
        "freshness": "pinned_snapshot",
        "freshnessCaveat": FRESHNESS_CAVEAT,
        "workflow": copy.deepcopy(WORKFLOW),
        "limitations": list(LIMITATIONS),
        "targetCodeExecuted": False,
        "networkAccess": False,
    }


def impact(
    workspace_path: str, module_root: str, symbol: str, depth: int = 2,
    limit: int = 100, direction: str = "both",
    *, catalog_snapshot: Optional[str] = None,
    relationships: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Explore one pinned module; never infer a cross-module dependency path."""
    if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 1000:
        raise core.OntologyError("Impact symbol must contain 1 to 1000 characters.")
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 5:
        raise core.OntologyError("Impact depth must be from 1 to 5.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= core.MAX_IMPACT_RESULTS:
        raise core.OntologyError("Impact result limit is out of range.")
    if not isinstance(direction, str) or direction not in {"incoming", "outgoing", "both"}:
        raise core.OntologyError("Impact direction must be incoming, outgoing, or both.")
    workspace, config, _repo = _large_workspace(workspace_path)
    snapshot_id = catalog_snapshot if catalog_snapshot is not None else _state(workspace).get("currentCatalogSnapshot")
    catalog = _read_catalog(workspace, config, snapshot_id)
    pinned = _selected_modules(catalog, [module_root])[0]
    child = _child_path(workspace, pinned["moduleId"])
    result = companion.impact(
        str(child), symbol, depth, snapshot=pinned["snapshotId"],
        direction=direction, limit=limit, relationships=relationships,
    )
    result.update({
        "mode": "large",
        "workspaceId": config["workspaceId"],
        "catalogSnapshotId": catalog["catalogSnapshotId"],
        "moduleId": pinned["moduleId"],
        "moduleRoot": pinned["root"],
        "moduleWorkspaceId": pinned["workspaceId"],
        "moduleSnapshotId": pinned["snapshotId"],
        "moduleSourceFingerprint": pinned["sourceFingerprint"],
        "limit": limit,
        "freshness": "pinned_snapshot",
        "freshnessCaveat": FRESHNESS_CAVEAT,
        "crossModuleResolution": "unsupported",
        "workflow": copy.deepcopy(WORKFLOW),
        "limitations": list(LIMITATIONS),
        "targetCodeExecuted": False,
        "networkAccess": False,
    })
    return result
