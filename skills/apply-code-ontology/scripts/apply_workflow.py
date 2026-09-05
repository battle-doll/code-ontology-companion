#!/usr/bin/env python3
"""Session-scoped application routing and verified, local Code checkpoints.

Capability inputs are observations supplied by the host, not execution receipts.
Only the trusted sibling Code implementation is callable here. Other products
and exposed MCP tools are handed back to the host without being executed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import stat
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any


PRODUCTS = ("code", "context", "contracts")
CAPABILITY_KEYS = ("installed", "skill_exposed", "mcp_exposed", "verified_cli")
MAX_CHANGED_PATHS = 256
MAX_CAPABILITIES_BYTES = 16_384


class ApplicationError(ValueError):
    """Invalid observations, inputs, or an untrusted helper layout."""


def _scope(*, sync_authorized: bool = False) -> dict[str, Any]:
    return {
        "application": "session_only",
        "persistentActivation": False,
        "agentsFilesChanged": False,
        "globalConfigurationChanged": False,
        "otherProductsExecuted": False,
        "targetCodeExecuted": False,
        "networkAccess": False,
        "deployment": False,
        "restart": False,
        "databaseAccess": False,
        "automationCreated": False,
        "workspaceWrites": "authorized_snapshot_sync" if sync_authorized else "none",
    }


def _observations(value: dict[str, Any]) -> dict[str, dict[str, bool]]:
    if not isinstance(value, dict) or set(value) - set(PRODUCTS):
        raise ApplicationError("Capabilities must be an object keyed by code, context, or contracts.")
    result = {}
    for product in PRODUCTS:
        entry = value.get(product, {})
        if not isinstance(entry, dict) or set(entry) - set(CAPABILITY_KEYS):
            raise ApplicationError(f"Unsupported capability fields for {product}.")
        if any(type(flag) is not bool for flag in entry.values()):
            raise ApplicationError("Capability observations must be JSON booleans.")
        result[product] = {key: entry.get(key, False) for key in CAPABILITY_KEYS}
    return result


def _availability_reason(product: str, observation: dict[str, bool]) -> str:
    if product != "code" and not observation["skill_exposed"]:
        return "optional_product_workflow_not_exposed"
    if not (observation["mcp_exposed"] or observation["verified_cli"]):
        return "no_observed_execution_route"
    return "observed_route_requires_actual_execution"


def _available(product: str, observation: dict[str, bool]) -> bool:
    return _availability_reason(product, observation) == "observed_route_requires_actual_execution"


def _route(product: str, observation: dict[str, bool], already_applied: bool) -> dict[str, Any]:
    executable = _available(product, observation)
    route = (
        "unavailable" if not executable else
        "already_applied" if already_applied else
        "host_mcp_handoff" if observation["mcp_exposed"] else
        "verified_sibling_cli" if product == "code" else
        "host_cli_handoff"
    )
    return {
        "product": product,
        "route": route,
        "observedAvailable": executable,
        "reason": _availability_reason(product, observation),
        "workflowDiscovered": observation["skill_exposed"],
        "capabilityBasis": "host_observation_only",
        "alreadyAppliedBasis": "host_session_report" if already_applied else None,
        "executionPerformed": False,
        "activationStatus": "NOT_EXECUTED",
    }


def plan(
    capabilities: dict[str, Any], *, explicit_product: str | None = None,
    already_applied: list[str] | None = None,
) -> dict[str, Any]:
    observed = _observations(capabilities)
    if explicit_product is not None and explicit_product not in PRODUCTS:
        raise ApplicationError("Unknown explicit product.")
    if any(product not in PRODUCTS for product in (already_applied or [])):
        raise ApplicationError("Unknown already-applied product.")
    available = [product for product in PRODUCTS if _available(product, observed[product])]
    selected = [explicit_product] if explicit_product else available
    return {
        "status": "planned",
        "activationStatus": "NOT_EXECUTED",
        "executionPerformed": False,
        "selectionBasis": "explicit_product" if explicit_product else "observed_availability",
        "availableCount": len(available),
        "observedAvailableProducts": available,
        "selectedProducts": selected,
        "unavailableProducts": [product for product in PRODUCTS if product not in available],
        "observations": observed,
        "availability": {product: {"observedAvailable": _available(product, observed[product]),
                                   "reason": _availability_reason(product, observed[product])}
                         for product in PRODUCTS},
        "routes": [_route(product, observed[product], product in (already_applied or []))
                   for product in selected],
        "scope": _scope(),
    }


def _checked_bundle_file(root: Path, relative: str) -> Path:
    candidate = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ApplicationError(f"Bundled file is unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ApplicationError("Bundled implementation may not traverse filesystem links.")
        if current != candidate and not stat.S_ISDIR(metadata.st_mode):
            raise ApplicationError("Bundled implementation has an invalid directory layout.")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ApplicationError("Bundled implementation must be an ordinary, single-link file.")
    if candidate.resolve().parent != (root / PurePosixPath(relative).parent).resolve():
        raise ApplicationError("Bundled implementation escaped its plugin.")
    return candidate


def _load_module(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ApplicationError("Bundled implementation cannot be loaded.")
    module = importlib.util.module_from_spec(specification)
    # Dataclasses and type resolvers require their defining module to be present.
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _load_companion() -> ModuleType:
    """Verify the fixed same-plugin layout; never search PATH or target sys.path."""
    root = Path(__file__).absolute().parents[3]
    helper = _checked_bundle_file(root, "skills/apply-code-ontology/scripts/apply_workflow.py")
    if helper.resolve() != Path(__file__).resolve():
        raise ApplicationError("Unexpected application helper location.")
    manifest_path = _checked_bundle_file(root, ".codex-plugin/plugin.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApplicationError("Plugin manifest cannot be verified.") from exc
    if not isinstance(manifest, dict) or manifest.get("name") != "code-ontology-companion":
        raise ApplicationError("Application helper must belong to Code Ontology Companion.")
    prefix = "skills/manage-code-ontology/scripts/"
    core_path = _checked_bundle_file(root, prefix + "code_ontology_core.py")
    companion_path = _checked_bundle_file(root, prefix + "companion.py")
    # Suppress import bytecode writes even when called without python -B.
    old_bytecode = sys.dont_write_bytecode
    old_core = sys.modules.get("code_ontology_core")
    sys.dont_write_bytecode = True
    try:
        core = _load_module("_code_ontology_application_core", core_path)
        sys.modules["code_ontology_core"] = core
        companion = _load_module("_code_ontology_application_companion", companion_path)
    finally:
        sys.dont_write_bytecode = old_bytecode
        if old_core is None:
            sys.modules.pop("code_ontology_core", None)
        else:
            sys.modules["code_ontology_core"] = old_core
    if companion.core is not core:
        raise ApplicationError("Companion did not load the verified sibling analyzer.")
    return companion


def _base_result() -> dict[str, Any]:
    return {
        "status": "incomplete", "activationStatus": "NOT_EXECUTED",
        "executionPerformed": False, "operations": [], "issues": [], "scope": _scope(),
        "evidenceType": "static_source_evidence",
    }


def _code_route(capabilities: dict[str, Any], result: dict[str, Any]) -> bool:
    observation = _observations(capabilities)["code"]
    result["capabilityObservation"] = observation
    result["capabilityBasis"] = "host_observation_only"
    if observation["mcp_exposed"]:
        result.update({
            "status": "handoff_required", "route": "host_mcp_handoff",
            "handoff": {
                "product": "code", "executor": "host",
                "operations": ["ontology_status", "ontology_search and/or ontology_neighbors"],
                "snapshotPolicy": "Pin every task read to the status snapshot_id.",
                "completionEvidence": "Actual tool results and source corroboration; a plan is insufficient.",
                "syncPolicy": "Read-only MCP cannot sync; use separately authorized verified sibling CLI.",
            },
        })
        return False
    if not observation["verified_cli"]:
        result.update({"status": "unavailable", "route": "unavailable"})
        result["issues"].append("Code execution requires exposed MCP or a host-verified bundled CLI.")
        return False
    result["route"] = "verified_sibling_cli"
    return True


def _record(result: dict[str, Any], operation: str, callback: Any) -> dict[str, Any]:
    result["executionPerformed"] = True
    try:
        value = callback()
    except Exception as exc:
        result["operations"].append({"operation": operation, "status": "failed",
                                     "error": f"{type(exc).__name__}: {exc}"})
        raise
    result["operations"].append({"operation": operation, "result": value})
    return value


def _status_issues(value: dict[str, Any], snapshot_id: str | None = None) -> list[str]:
    issues = []
    if value.get("status") != "ok" or not value.get("snapshotId"):
        issues.append("A promoted snapshot was not verified.")
    if value.get("freshness") != "current":
        issues.append("Source freshness is not current.")
    if snapshot_id is not None and value.get("snapshotId") != snapshot_id:
        issues.append("The selected snapshot is not the current status snapshot.")
    count = value.get("counts", {}).get("warnings")
    if type(count) is not int or count != 0:
        issues.append("Analyzer warnings are present or their count is unknown.")
    return issues


def _task_text(value: str | None, label: str, maximum: int) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip()
                              or len(value) > maximum or any(ord(char) < 32 for char in value)):
        raise ApplicationError(f"{label} must be nonempty bounded text without control characters.")
    return value


def run_code(
    capabilities: dict[str, Any], workspace: str, *, term: str | None = None,
    symbol: str | None = None, snapshot: str | None = None,
) -> dict[str, Any]:
    term = _task_text(term, "Term", 300)
    symbol = _task_text(symbol, "Symbol", 500)
    snapshot = _task_text(snapshot, "Snapshot", 100)
    if term is None and symbol is None:
        raise ApplicationError("A task-relevant term or symbol is required.")
    result = _base_result()
    if not _code_route(capabilities, result):
        result["requestedReads"] = {"term": term, "symbol": symbol, "snapshotId": snapshot}
        return result
    try:
        companion = _load_companion()
        result["implementationVerified"] = "same_plugin_sibling"
        initial = _record(result, "status", lambda: companion.status(workspace))
        selected = snapshot or initial.get("snapshotId")
        if not selected or selected in {"current", "previous"}:
            raise ApplicationError("Select a concrete snapshot ID returned by status or history.")
        result["snapshotId"] = selected
        result["workspaceId"] = initial.get("workspaceId")
        if term is not None:
            query = _record(result, "query", lambda: companion.query(workspace, term, limit=20, snapshot=selected))
            if query.get("snapshotId") != selected:
                result["issues"].append("Query returned a different snapshot.")
            if not query.get("matches"):
                result["issues"].append("The requested term has no matches; this does not establish absence.")
        if symbol is not None:
            impact = _record(result, "impact", lambda: companion.impact(
                workspace, symbol, depth=2, snapshot=selected, direction="both", limit=100))
            if impact.get("snapshotId") != selected or impact.get("status") != "ok":
                result["issues"].append("Impact did not resolve one symbol in the selected snapshot.")
        final = _record(result, "status_after_reads", lambda: companion.status(workspace))
        result["freshness"] = final.get("freshness", "unknown")
        result["warningCount"] = final.get("counts", {}).get("warnings")
        result["issues"].extend(_status_issues(initial, selected))
        result["issues"].extend(_status_issues(final, selected))
        if final.get("workspaceId") != initial.get("workspaceId"):
            result["issues"].append("Workspace identity changed during the reads.")
    except Exception as exc:
        result["issues"].append(f"Code operation failed: {type(exc).__name__}: {exc}")
    result["issues"] = list(dict.fromkeys(result["issues"]))
    result["activationStatus"] = "INCOMPLETE" if result["issues"] else "PASS"
    result["status"] = "incomplete" if result["issues"] else "applied"
    result["activationMeaning"] = "Requested Code static reads executed; task completion and runtime behavior are not established."
    return result


def _relative_paths(paths: list[str]) -> list[str]:
    if not isinstance(paths, list) or not paths or len(paths) > MAX_CHANGED_PATHS:
        raise ApplicationError(f"Provide between 1 and {MAX_CHANGED_PATHS} changed relative paths.")
    result = []
    for raw in paths:
        if (not isinstance(raw, str) or not raw or len(raw) > 1000 or "\\" in raw or ":" in raw
                or any(ord(char) < 32 for char in raw)):
            raise ApplicationError("Changed paths must be normalized repository-relative paths.")
        path = PurePosixPath(raw)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in raw.split("/")):
            raise ApplicationError("Changed paths may not escape the repository or contain aliases.")
        if raw not in result:
            result.append(raw)
    return result


def _classify_paths(companion: ModuleType, workspace: str, paths: list[str], snapshot_id: str) -> dict[str, Any]:
    root, config = companion._workspace(workspace)
    repo = companion._resolve_existing_dir(config["repositoryRoot"], "Configured repository")
    old_manifest = companion._read_json(
        companion._snapshot_path(root, snapshot_id) / "source-manifest.json", "Source manifest")
    previous_paths = {entry.get("path") for entry in old_manifest.get("files", [])}
    supported, unsupported, expected = [], [], {}
    for raw in paths:
        path = PurePosixPath(raw)
        reason = None
        source_state = "present"
        if path.suffix.lower() not in companion.core.SUPPORTED_SUFFIXES:
            reason = "unsupported_language"
        elif any(part in companion.core.EXCLUDED_DIRECTORIES for part in path.parts[:-1]):
            reason = "excluded_directory"
        elif companion.core._is_sensitive_file(Path(raw)):
            reason = "sensitive_filename_excluded"
        else:
            current = repo
            for part in path.parts:
                current = current / part
                try:
                    metadata = current.lstat()
                except FileNotFoundError:
                    reason = None if raw in previous_paths else "source_not_found_in_snapshot_or_repository"
                    source_state = "deleted"
                    break
                if companion._is_link_like(metadata):
                    reason = "filesystem_link_excluded"
                    break
                if current == repo / raw and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
                    reason = "nonregular_or_multilink_source_excluded"
                    break
                if current == repo / raw and metadata.st_size > companion.core.MAX_SOURCE_BYTES:
                    reason = "source_size_limit_exceeded"
                    break
        if reason is None:
            supported.append(raw)
            expected[raw] = source_state
        else:
            unsupported.append({"path": raw, "reason": reason})
    return {"supported": supported, "unsupported": unsupported, "expectedSnapshotState": expected}


def _verify_changed_snapshot_paths(
    companion: ModuleType, workspace: str, snapshot_id: str, expected: dict[str, str],
) -> list[str]:
    root, _ = companion._workspace(workspace)
    manifest = companion._read_json(
        companion._snapshot_path(root, snapshot_id) / "source-manifest.json", "Source manifest")
    snapshot_paths = {entry.get("path") for entry in manifest.get("files", [])}
    return [f"Changed source was not verified {state} in the final snapshot: {path}"
            for path, state in expected.items()
            if (path in snapshot_paths) != (state == "present")]


def checkpoint(
    capabilities: dict[str, Any], workspace: str, changed_paths: list[str], *, sync_authorized: bool = False,
) -> dict[str, Any]:
    paths = _relative_paths(changed_paths)
    if type(sync_authorized) is not bool:
        raise ApplicationError("Sync authorization must be explicit boolean true or false.")
    result = _base_result()
    result.update({"checkpointStatus": "NOT_EXECUTED", "syncAttempts": 0,
                   "syncAuthorized": sync_authorized, "requestedChangedPaths": paths,
                   "changedPaths": {"supported": [], "unsupported": []}})
    if not _code_route(capabilities, result):
        return result
    try:
        companion = _load_companion()
        result["implementationVerified"] = "same_plugin_sibling"
        initial = _record(result, "status", lambda: companion.status(workspace))
        result["workspaceId"] = initial.get("workspaceId")
        if not initial.get("snapshotId"):
            raise ApplicationError("Checkpoint requires an initialized, promoted snapshot.")
        classified = _classify_paths(companion, workspace, paths, initial["snapshotId"])
        result["changedPaths"] = classified
        if classified["unsupported"]:
            result["issues"].append("Some changed paths are outside supported analysis; the whole change set is incomplete.")
        if not classified["supported"]:
            result["issues"].append("No supported changed source paths were identified.")
        selected_status = initial
        if classified["supported"] and initial.get("freshness") != "current":
            if sync_authorized:
                result["syncAttempts"] = 1
                result["scope"] = _scope(sync_authorized=True)
                synced = _record(result, "sync", lambda: companion.sync(workspace, trigger="application_checkpoint"))
                if synced.get("status") not in {"promoted", "no_change"}:
                    result["issues"].append("Sync did not report promotion or a verified no-change result.")
                selected_status = _record(result, "status_after_sync", lambda: companion.status(workspace))
                if synced.get("snapshotId") != selected_status.get("snapshotId"):
                    result["issues"].append("The status snapshot differs from the synchronization result.")
            else:
                result["issues"].append("Source refresh is needed; snapshot sync is not authorized.")
        result["snapshotId"] = selected_status.get("snapshotId")
        result["issues"].extend(_status_issues(selected_status))
        result["issues"].extend(_verify_changed_snapshot_paths(
            companion, workspace, selected_status["snapshotId"], classified["expectedSnapshotState"]))
        # Classification and manifest reads can race with edits or another sync,
        # including when the initial status was current and no sync was needed.
        final = _record(result, "status_after_checkpoint", lambda: companion.status(workspace))
        result["freshness"] = final.get("freshness", "unknown")
        result["warningCount"] = final.get("counts", {}).get("warnings")
        result["issues"].extend(_status_issues(final, result["snapshotId"]))
        if (selected_status.get("workspaceId") != initial.get("workspaceId")
                or final.get("workspaceId") != initial.get("workspaceId")):
            result["issues"].append("Workspace identity changed during the checkpoint.")
    except Exception as exc:
        result["issues"].append(f"Checkpoint failed: {type(exc).__name__}: {exc}")
    result["issues"] = list(dict.fromkeys(result["issues"]))
    result["checkpointStatus"] = "INCOMPLETE" if result["issues"] else "PASS"
    result["status"] = "incomplete" if result["issues"] else "complete"
    result["analysisScope"] = "Supported changed Java/Python source paths only; not runtime or all-language validation."
    return result


def _capabilities_json(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_CAPABILITIES_BYTES:
        raise ApplicationError("Capabilities input is too large.")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ApplicationError("Capabilities must be valid JSON.") from exc
    return _observations(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="Route host observations without executing or activating products.")
    planning.add_argument("--capabilities", required=True)
    planning.add_argument("--explicit-product", choices=PRODUCTS)
    planning.add_argument("--already-applied", action="append", choices=PRODUCTS, default=[])
    running = commands.add_parser("run-code", help="Read Code status and task symbols through verified bundled CLI logic.")
    running.add_argument("--capabilities", required=True)
    running.add_argument("--workspace", required=True)
    running.add_argument("--term")
    running.add_argument("--symbol")
    running.add_argument("--snapshot", help="Concrete immutable snapshot ID; defaults to the initial status snapshot.")
    checking = commands.add_parser("checkpoint", help="Check changed source scope and optionally perform one authorized sync.")
    checking.add_argument("--capabilities", required=True)
    checking.add_argument("--workspace", required=True)
    checking.add_argument("--changed-path", action="append", required=True)
    checking.add_argument("--sync-authorized", action="store_true")
    args = parser.parse_args(argv)
    try:
        capabilities = _capabilities_json(args.capabilities)
        if args.command == "plan":
            result = plan(capabilities, explicit_product=args.explicit_product, already_applied=args.already_applied)
        elif args.command == "run-code":
            result = run_code(capabilities, args.workspace, term=args.term, symbol=args.symbol, snapshot=args.snapshot)
        else:
            result = checkpoint(capabilities, args.workspace, args.changed_path, sync_authorized=args.sync_authorized)
    except ApplicationError as exc:
        result = {**_base_result(), "status": "invalid_input", "issues": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if result["status"] in {"incomplete", "invalid_input", "unavailable"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
