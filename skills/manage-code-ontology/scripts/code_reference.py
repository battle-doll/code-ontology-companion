#!/usr/bin/env python3
"""Portable selected Code references; never execute sources or contact a consumer.

The native profile preserves incomplete references. Contracts compatibility is
reported without inventing source-to-commit verification. Context receives only
immutable locators; retaining the native artifact recovers its rich evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any

import code_ontology_core as core
import companion

PROFILE = "code-ontology-reference"
PROFILE_VERSION = "1.0.0"
CONTRACT_VERSION = "0.1.0-draft.1"
MAX_SYMBOLS = 100
MAX_RELATIONS = 200
MAX_BYTES = 524_288
REVISION_LIMITATION = "revision.snapshot_binding_not_verified"


class ReferenceError(ValueError):
    """Bounded diagnostic without echoing user data."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def _text(value: Any, maximum: int = 512) -> str:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ReferenceError("invalid_portable_text")
    return value


def _identity(value: Any) -> str:
    value = _text(value, 160)
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}", value)
            or value.startswith(("/", "file:")) or "://" in value or re.match(r"^[A-Za-z]:[/\\]", value)):
        raise ReferenceError("invalid_repository_identity")
    return value


def _path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 1024:
        return None
    if (value.startswith(("/", "\\")) or "\\" in value or re.match(r"^[A-Za-z]:", value)
            or any(p in ("", ".", "..") for p in value.split("/"))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return None
    return value


def _source(node: dict) -> dict | None:
    path = _path(node.get("path"))
    metadata = node.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    start, end = metadata.get("line_start"), metadata.get("line_end")
    if path is None or type(start) is not int or type(end) is not int or not 1 <= start <= end <= 10_000_000:
        return None
    return {"path": path, "line_start": start, "line_end": end}


def _locator(source: dict | None, fallback: str) -> str:
    if source:
        return f"{source['path']}:{source['line_start']}-{source['line_end']}"
    return "symbol:" + fallback


def _artifact_id(artifact: dict) -> str:
    return "urn:code-ontology-reference:" + _digest({key: value for key, value in artifact.items() if key != "artifact_id"})


def verify_artifact(artifact: dict) -> None:
    """Check content addressing and profile before resolving a local locator.

    This is not a general schema validator or an author/permission check.
    """
    if not isinstance(artifact, dict) or artifact.get("profile") != PROFILE or artifact.get("profile_version") != PROFILE_VERSION:
        raise ReferenceError("unsupported_reference_profile")
    try:
        serialized = canonical(artifact)
    except (TypeError, ValueError, RecursionError):
        raise ReferenceError("invalid_reference_artifact") from None
    if len(serialized.encode("ascii")) > MAX_BYTES:
        raise ReferenceError("reference_byte_limit")
    if artifact.get("artifact_id") != _artifact_id(artifact):
        raise ReferenceError("artifact_digest_mismatch")


def build_reference(document: dict, metadata: dict, repository_id: str,
                    symbols: list[str], module_root: str = ".") -> dict:
    """Select exact legacy IDs and a bounded one-hop neighborhood from one snapshot."""
    if document.get("schema_version") != core.SCHEMA_VERSION:
        raise ReferenceError("unsupported_source_schema")
    repository_id = _identity(repository_id)
    if module_root != "." and _path(module_root) is None:
        raise ReferenceError("invalid_module_root")
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise ReferenceError("select_between_one_and_100_symbols")
    selected = sorted({_text(value) for value in symbols})
    snapshot_id = _text(metadata.get("snapshotId"), 160)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", snapshot_id):
        raise ReferenceError("invalid_snapshot_identity")
    analyzer_version = _text(metadata.get("analyzerVersion"), 160)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,159}", analyzer_version):
        raise ReferenceError("invalid_analyzer_version")
    document_snapshot = document.get("companion", {}).get("snapshotId")
    if document_snapshot != snapshot_id:
        raise ReferenceError("snapshot_identity_mismatch")
    nodes = {row["id"]: row for row in document.get("nodes", []) if isinstance(row, dict) and isinstance(row.get("id"), str)}
    if not all(value in nodes for value in selected):
        raise ReferenceError("selected_symbol_not_found")
    for value in selected:
        path = nodes[value].get("path")
        if module_root != "." and path and not str(path).startswith(module_root + "/"):
            raise ReferenceError("selected_symbol_outside_module")
    module_id = "module:" + _digest([repository_id, module_root])[:24]
    revision = metadata.get("repositoryRevision")
    revision = revision.lower() if isinstance(revision, str) and re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", revision) else None
    included = set(selected)
    edges = []
    omitted = 0
    candidates = sorted((row for row in document.get("edges", []) if isinstance(row, dict)
                         and (row.get("source") in included or row.get("target") in included)),
                        key=lambda row: (str(row.get("source")), str(row.get("target")), str(row.get("type"))))
    # `candidates` is materialized before expanding `included`: exactly one hop.
    for edge in candidates:
        endpoints = {edge.get("source"), edge.get("target")}
        if (not all(isinstance(value, str) and value in nodes for value in endpoints)
                or len(included | endpoints) > MAX_SYMBOLS or len(edges) >= MAX_RELATIONS):
            omitted += 1
            continue
        included.update(endpoints)
        edges.append(edge)
    evidence: dict[str, dict] = {}
    rows = []
    for symbol_id in sorted(included):
        node = nodes[symbol_id]
        source = _source(node)
        kind = _text(node.get("type"), 160)
        resolution = "source_located" if source else "external" if kind.startswith("External") else "source_unresolved"
        if source and module_root != "." and not source["path"].startswith(module_root + "/"):
            resolution = "outside_module"
        refs = []
        if source:
            item = {"origin": "source_observed", "review_status": "not_assessed",
                    "locator": _locator(source, symbol_id), "source": source,
                    "code": {"rule_id": "bridge.symbol_reference", "basis": "resolved_static",
                             "runtime_status": "runtime_unknown",
                             "limitations": [REVISION_LIMITATION, "runtime.activation_not_observed"]}}
            eid = "evidence:" + _digest([symbol_id, item])[:24]
            evidence[eid] = {"id": eid, **item}
            refs.append(eid)
        rows.append({"id": symbol_id,
                     "reference_id": "symbol:" + _digest([repository_id, module_id, snapshot_id, symbol_id])[:24],
                     "kind": kind, "qualified_name": _text(node.get("qualified_name") or node.get("name"), 1024),
                     "source": source, "resolution": resolution, "runtime_status": "runtime_unknown",
                     "evidence_refs": refs})
    relations = []
    for edge in edges:
        triple = [_text(edge.get("source")), _text(edge.get("target")), _text(edge.get("type"), 160)]
        refs = []
        for item in core.relationship_evidence(edge):
            source = None
            path, start, end = _path(item.get("path")), item.get("line_start"), item.get("line_end")
            if path and type(start) is int and type(end) is int and 1 <= start <= end <= 10_000_000:
                source = {"path": path, "line_start": start, "line_end": end}
            eid = core.relationship_evidence_id(*triple, item)
            evidence[eid] = {"id": eid, "origin": "source_observed", "review_status": "not_assessed",
                             "locator": _locator(source, triple[0]), "source": source,
                             "code": {"rule_id": item["rule_id"], "basis": item["basis"],
                                      "runtime_status": item["runtime_status"],
                                      "limitations": list(item.get("limitations", []))}}
            refs.append(eid)
        relations.append({"id": "relation:" + _digest(triple)[:24], "source": triple[0], "target": triple[1],
                          "type": triple[2], "evidence_refs": refs,
                          "resolution": "evidenced" if refs else "evidence_unavailable"})
    artifact = {"profile": PROFILE, "profile_version": PROFILE_VERSION,
                "co_namespace": core.ONTOLOGY_NS, "source_schema_version": document["schema_version"],
                "producer": {"name": "code-ontology-companion", "version": core.PLUGIN_VERSION},
                "scope": {"repository_id": repository_id, "module_id": module_id, "module_root": module_root},
                "snapshot": {"id": snapshot_id, "repository_revision": revision,
                             "revision_binding": "not_checked" if revision else "unavailable",
                             "source_state": "not_checked", "analyzer_version": analyzer_version},
                "selection": {"requested_ids": selected, "mode": "bounded_one_hop",
                              "omitted_relationships": omitted, "whole_repository": False},
                "symbols": rows, "relations": relations, "evidence": [evidence[key] for key in sorted(evidence)],
                "authority": {"content": "untrusted_data", "current_authorization": "not_checked",
                              "runtime_behavior": "not_checked", "approval": "not_transferred"}}
    artifact["artifact_id"] = _artifact_id(artifact)
    verify_artifact(artifact)
    return artifact


def export_reference(workspace_path: str, repository_id: str, symbols: list[str],
                     snapshot: str = "current", module_root: str = ".") -> dict:
    """Read only an initialized workspace. No source scan, new snapshot, or writes."""
    workspace, _ = companion._workspace(workspace_path)
    snapshot_id = companion._resolve_snapshot_alias(workspace, snapshot)
    location = companion._snapshot_path(workspace, snapshot_id)
    document = companion._read_json(location / "ontology.json", "Ontology snapshot")
    metadata = companion._snapshot_metadata(location)
    if metadata.get("snapshotId") != snapshot_id:
        raise ReferenceError("snapshot_identity_mismatch")
    return build_reference(document, metadata, repository_id, symbols, module_root)


def contracts_projection(artifact: dict) -> dict:
    """Report why this native profile cannot assert the draft's commit binding.

    Existing snapshots record HEAD, not a proof that the working tree equals it.
    Native v1 deliberately has no caller-settable `verified` escape hatch.
    """
    verify_artifact(artifact)
    report = {"target": "ontology-companion-contracts", "contract_version": CONTRACT_VERSION,
              "profile": "code-reference", "status": "unsupported", "artifact": None,
              "source_artifact_id": artifact["artifact_id"],
              "not_checked": ["producer_identity", "revision_snapshot_equivalence", "runtime_behavior", "current_authorization"],
              "losses": []}
    report["losses"] = ["target_requires_repository_revision" if artifact["snapshot"]["repository_revision"] is None
                        else "repository_revision_binding_not_verified"]
    report["losses"].extend(["native_module_and_authority_metadata_not_represented",
                             "native_resolution_and_selection_metadata_not_represented"])
    return report


def context_evidence_projection(artifact: dict, symbol_id: str) -> dict:
    """An immutable reference only, never a Context approval or storage action."""
    verify_artifact(artifact)
    symbol = next((row for row in artifact["symbols"] if row["id"] == symbol_id), None)
    if symbol is None:
        raise ReferenceError("selected_symbol_not_found")
    return {"id": symbol["reference_id"], "origin": "source_observed",
            "locator": artifact["artifact_id"] + "#" + symbol["reference_id"]}


def resolve_context_locator(artifact: dict, locator: str) -> dict:
    """Resolve against a supplied retained artifact, without fetching a URI."""
    verify_artifact(artifact)
    prefix = artifact["artifact_id"] + "#"
    if not isinstance(locator, str) or not locator.startswith(prefix):
        raise ReferenceError("locator_artifact_mismatch")
    reference_id = locator[len(prefix):]
    symbol = next((row for row in artifact["symbols"] if row["reference_id"] == reference_id), None)
    if symbol is None:
        raise ReferenceError("locator_symbol_not_found")
    relations = [row for row in artifact["relations"] if symbol["id"] in (row["source"], row["target"])]
    refs = {eid for row in [symbol] + relations for eid in row["evidence_refs"]}
    return {"symbol": symbol, "relations": relations,
            "evidence": [row for row in artifact["evidence"] if row["id"] in refs],
            "authority": artifact["authority"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read a selected immutable Code snapshot as portable references. No uploads or consumer writes.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--repository-id", required=True, help="Explicit stable portable identity, e.g. github:owner/repository; no automatic remote discovery.")
    parser.add_argument("--symbol", action="append", required=True, help="Exact legacy symbol ID; repeat for a bounded selection.")
    parser.add_argument("--snapshot", default="current")
    parser.add_argument("--module-root", default=".")
    parser.add_argument("--format", choices=("native", "contracts"), default="native")
    args = parser.parse_args(argv)
    try:
        artifact = export_reference(args.workspace, args.repository_id, args.symbol, args.snapshot, args.module_root)
        result = contracts_projection(artifact) if args.format == "contracts" else artifact
        print(canonical(result))
        return 2 if result.get("status") == "unsupported" else 0
    except (ReferenceError, companion.CompanionError, core.OntologyError, OSError, ValueError, TypeError, KeyError):
        print('{"error":"reference_export_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
