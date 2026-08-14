#!/usr/bin/env python3
"""Read-only stdio MCP server for registered Code Ontology workspaces."""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = PLUGIN_ROOT / "skills" / "manage-code-ontology" / "scripts"
if not SCRIPT_DIR.is_dir():
    raise SystemExit("Bundled Companion scripts are missing.")
sys.path.insert(0, str(SCRIPT_DIR))

import code_ontology_core as core  # noqa: E402
import companion  # noqa: E402


SERVER_NAME = "code-ontology-companion"
SERVER_VERSION = "0.5.2"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({DEFAULT_PROTOCOL_VERSION})

MAX_WORKSPACES = 200
MAX_SEARCH_RESULTS = 200
MAX_IMPACT_RESULTS = 500
MAX_HISTORY_RESULTS = 200
MAX_CHANGE_RESULTS = 500
MAX_LINEAGE_RESULTS = 500
MAX_ERROR_TEXT = 300
MAX_COUNT = 1_000_000_000
MAX_EDGE_EVIDENCE_ITEMS = 16
MAX_EVIDENCE_LIMITATIONS = 16
MAX_EVIDENCE_PATH_LENGTH = 4_096
MAX_EVIDENCE_LINE = 10_000_000
MAX_ADAPTER_CAPABILITIES = 32
MAX_UNSUPPORTED_RUNTIME_ITEMS = 32

POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<!http:)(?<!https:)(?<![\w./\\-])/{1,2}(?=[^\s/])",
    flags=re.IGNORECASE,
)
WINDOWS_DRIVE_PATH_RE = re.compile(
    r"(?<![\w.])[A-Za-z]:[\\/](?=\S)"
)
WINDOWS_UNC_PATH_RE = re.compile(
    r"(?<![\w.\\])\\\\(?=[^\\\s]+\\)"
)
WINDOWS_ROOTED_PATH_RE = re.compile(
    r"(?<![\w.\\])\\(?!\\)(?=\S)"
)
FILE_ABSOLUTE_URI_RE = re.compile(
    r"(?<![\w])file:(?:/{2,}|\\{2,})(?=\S)",
    flags=re.IGNORECASE,
)


def _string_schema(maximum: int, *, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "maxLength": maximum}
    if enum is not None:
        schema["enum"] = enum
    return schema


def _integer_schema(maximum: int = MAX_COUNT, minimum: int = 0) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def _number_schema(maximum: float, minimum: float = 0.0) -> dict[str, Any]:
    return {"type": "number", "minimum": minimum, "maximum": maximum}


def _counts_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "sourceFiles": _integer_schema(25_000),
            "nodes": _integer_schema(500_000),
            "edges": _integer_schema(1_000_000),
            "warnings": _integer_schema(),
            "skippedFiles": _integer_schema(),
        },
        "required": ["sourceFiles", "nodes", "edges", "warnings", "skippedFiles"],
        "additionalProperties": False,
    }


def _node_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "returnType": _string_schema(500),
            "parameterTypes": {
                "type": "array",
                "items": _string_schema(500),
                "maxItems": 64,
            },
            "parameterCount": _integer_schema(1_000),
            "semanticGroups": {
                "type": "array",
                "items": _string_schema(100),
                "maxItems": 20,
            },
            "accessor": _string_schema(100),
            "controlKind": _string_schema(100),
            "ordinal": _integer_schema(1_000_000),
        },
        "additionalProperties": False,
    }


def _node_schema(*, reference_only: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": _string_schema(1_000),
        "name": _string_schema(500),
        "qualifiedName": _string_schema(1_000),
    }
    required = ["id", "name"]
    if not reference_only:
        properties.update(
            {
                "type": _string_schema(100),
                "language": _string_schema(100),
                "path": _string_schema(1_000),
                "metadata": _node_metadata_schema(),
            }
        )
        required.extend(["type", "language"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _edge_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source": _string_schema(1_000),
            "type": _string_schema(100),
            "target": _string_schema(1_000),
        },
        "required": ["source", "type", "target"],
        "additionalProperties": False,
    }


EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "ruleId": _string_schema(80),
        "basis": _string_schema(
            50,
            enum=[
                "direct_syntax",
                "resolved_static",
                "framework_semantic",
                "name_heuristic",
            ],
        ),
        "runtimeStatus": _string_schema(
            50, enum=["not_applicable", "runtime_unknown"]
        ),
        "path": _string_schema(MAX_EVIDENCE_PATH_LENGTH),
        "lineStart": _integer_schema(MAX_EVIDENCE_LINE, 1),
        "lineEnd": _integer_schema(MAX_EVIDENCE_LINE, 1),
        "limitations": {
            "type": "array",
            "items": _string_schema(200),
            "maxItems": MAX_EVIDENCE_LIMITATIONS,
        },
    },
    "required": ["ruleId", "basis", "runtimeStatus"],
    "additionalProperties": False,
}

SUPPORT_STATUS_SCHEMA = _string_schema(
    30, enum=["supported", "partial", "unsupported"]
)
CAPABILITY_NAMES = {
    "annotations",
    "calls",
    "declarations",
    "decorators",
    "dependency_injection",
    "explicit_type_imports",
    "imports",
    "inheritance",
    "pipeline_roles",
    "runtime_activation",
    "runtime_dispatch",
    "runtime_imports",
}
ADAPTER_DETAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "status": SUPPORT_STATUS_SCHEMA,
        "detected": {"type": "boolean"},
        "capabilities": {
            "type": "object",
            "properties": {
                name: SUPPORT_STATUS_SCHEMA for name in sorted(CAPABILITY_NAMES)
            },
            "additionalProperties": False,
        },
        "unsupportedRuntime": {
            "type": "array",
            "items": _string_schema(80),
            "maxItems": MAX_UNSUPPORTED_RUNTIME_ITEMS,
        },
    },
    "required": ["status", "detected", "capabilities", "unsupportedRuntime"],
    "additionalProperties": False,
}
ADAPTER_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "Java": ADAPTER_DETAIL_SCHEMA,
        "Python": ADAPTER_DETAIL_SCHEMA,
    },
    "additionalProperties": False,
}

QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "status": _string_schema(30, enum=["documented", "legacy_unknown"]),
        "contractVersion": _string_schema(50),
        "totalEdges": _integer_schema(1_000_000),
        "documentedEdges": _integer_schema(1_000_000),
        "missingEvidence": _integer_schema(1_000_000),
        "coveragePercent": _number_schema(100.0),
        "adapters": ADAPTER_STATUS_SCHEMA,
    },
    "required": [
        "status",
        "contractVersion",
        "totalEdges",
        "documentedEdges",
        "missingEvidence",
        "coveragePercent",
        "adapters",
    ],
    "additionalProperties": False,
}


def _contract_schema(
    properties: dict[str, Any],
    success_contracts: list[tuple[str, list[str]]],
) -> dict[str, Any]:
    all_properties = {
        "status": _string_schema(
            30, enum=[status for status, _ in success_contracts] + ["error"]
        ),
        "message": _string_schema(MAX_ERROR_TEXT),
        **properties,
    }
    variants = [
        {
            "properties": {"status": {"const": status}},
            "required": ["status", *required],
        }
        for status, required in success_contracts
    ]
    variants.append(
        {
            "properties": {"status": {"const": "error"}},
            "required": ["status", "message"],
        }
    )
    return {
        "type": "object",
        "properties": all_properties,
        "required": ["status"],
        "oneOf": variants,
        "additionalProperties": False,
    }


WORKSPACE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {"id": _string_schema(100), "label": _string_schema(300)},
    "required": ["id", "label"],
    "additionalProperties": False,
}
SNAPSHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "snapshotId": _string_schema(100),
        "createdAt": _string_schema(100),
        "trigger": _string_schema(100),
        "counts": _counts_schema(),
    },
    "required": ["snapshotId", "counts"],
    "additionalProperties": False,
}
LINEAGE_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "eventId": _string_schema(100),
        "kind": _string_schema(100),
        "evidenceType": _string_schema(50),
        "summary": _string_schema(1_000),
        "subject": _string_schema(300),
        "snapshotId": _string_schema(100),
        "previousSnapshotId": _string_schema(100),
        "recordedAt": _string_schema(100),
    },
    "required": ["eventId", "kind", "evidenceType", "summary"],
    "additionalProperties": False,
}

OUTPUT_SCHEMAS = {
    "ontology_list_workspaces": _contract_schema(
        {
            "workspaces": {
                "type": "array",
                "items": WORKSPACE_ITEM_SCHEMA,
                "maxItems": MAX_WORKSPACES,
            },
            "staleRegistrations": {
                "type": "array",
                "items": WORKSPACE_ITEM_SCHEMA,
                "maxItems": MAX_WORKSPACES,
            },
            "truncated": {"type": "boolean"},
        },
        [("ok", ["workspaces", "staleRegistrations", "truncated"])],
    ),
    "ontology_status": _contract_schema(
        {
            "workspaceId": _string_schema(100),
            "repositoryLabel": _string_schema(300),
            "snapshotId": _string_schema(100),
            "previousSnapshotId": _string_schema(100),
            "generatedAt": _string_schema(100),
            "freshness": _string_schema(
                30, enum=["current", "stale", "unknown", "partial", "snapshot"]
            ),
            "snapshotAnalyzerVersion": _string_schema(50),
            "currentAnalyzerVersion": _string_schema(50),
            "snapshotCompanionVersion": _string_schema(50),
            "currentCompanionVersion": _string_schema(50),
            "evidenceType": _string_schema(50),
            "counts": _counts_schema(),
            "quality": QUALITY_SCHEMA,
            "pipelineStatus": _string_schema(
                30, enum=["healthy", "refresh_required", "partial", "unknown"]
            ),
        },
        [
            (
                "ok",
                [
                    "workspaceId",
                    "repositoryLabel",
                    "snapshotId",
                    "freshness",
                    "counts",
                    "quality",
                    "pipelineStatus",
                ],
            ),
            ("partial", ["workspaceId", "repositoryLabel", "freshness", "message"]),
        ],
    ),
    "ontology_search": _contract_schema(
        {
            "workspaceId": _string_schema(100),
            "snapshotId": _string_schema(100),
            "freshness": _string_schema(30, enum=["snapshot"]),
            "evidenceType": _string_schema(50),
            "term": _string_schema(300),
            "matchCount": _integer_schema(500_000),
            "returned": _integer_schema(MAX_SEARCH_RESULTS),
            "matches": {
                "type": "array",
                "items": _node_schema(),
                "maxItems": MAX_SEARCH_RESULTS,
            },
            "truncated": {"type": "boolean"},
        },
        [
            (
                "ok",
                [
                    "workspaceId",
                    "snapshotId",
                    "freshness",
                    "evidenceType",
                    "term",
                    "matchCount",
                    "returned",
                    "matches",
                    "truncated",
                ],
            )
        ],
    ),
    "ontology_neighbors": _contract_schema(
        {
            "workspaceId": _string_schema(100),
            "snapshotId": _string_schema(100),
            "freshness": _string_schema(30, enum=["snapshot"]),
            "evidenceType": _string_schema(50),
            "symbol": _string_schema(500),
            "candidates": {
                "type": "array",
                "items": _node_schema(reference_only=True),
                "maxItems": 20,
            },
            "root": _node_schema(),
            "depth": _integer_schema(5, 1),
            "impactCount": _integer_schema(MAX_IMPACT_RESULTS),
            "truncated": {"type": "boolean"},
            "impact": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "depth": _integer_schema(5, 1),
                        "relationship": _string_schema(100),
                        "direction": _string_schema(
                            20, enum=["incoming", "outgoing"]
                        ),
                        "node": _node_schema(),
                        "evidence": {
                            "type": "array",
                            "items": EVIDENCE_SCHEMA,
                            "maxItems": MAX_EDGE_EVIDENCE_ITEMS,
                        },
                    },
                    "required": ["depth", "relationship", "direction", "node", "evidence"],
                    "additionalProperties": False,
                },
                "maxItems": MAX_IMPACT_RESULTS,
            },
            "interpretation": _string_schema(500),
        },
        [
            (
                "ok",
                [
                    "workspaceId",
                    "snapshotId",
                    "freshness",
                    "evidenceType",
                    "symbol",
                    "root",
                    "depth",
                    "impactCount",
                    "truncated",
                    "impact",
                    "interpretation",
                ],
            ),
            (
                "not_found",
                ["workspaceId", "snapshotId", "symbol", "candidates", "impact"],
            ),
            (
                "ambiguous",
                ["workspaceId", "snapshotId", "symbol", "candidates", "impact"],
            ),
        ],
    ),
    "ontology_history": _contract_schema(
        {
            "workspaceId": _string_schema(100),
            "snapshots": {
                "type": "array",
                "items": SNAPSHOT_SCHEMA,
                "maxItems": MAX_HISTORY_RESULTS,
            },
            "truncated": {"type": "boolean"},
        },
        [("ok", ["workspaceId", "snapshots", "truncated"])],
    ),
    "ontology_changes": _contract_schema(
        {
            "workspaceId": _string_schema(100),
            "beforeSnapshotId": _string_schema(100),
            "afterSnapshotId": _string_schema(100),
            "changeBasis": _string_schema(
                30,
                enum=[
                    "source_change",
                    "analyzer_reinterpretation",
                    "analysis_refresh",
                    "mixed",
                    "no_change",
                    "legacy_unknown",
                ],
            ),
            "quality": QUALITY_SCHEMA,
            "counts": {
                "type": "object",
                "properties": {
                    "nodesAdded": _integer_schema(),
                    "nodesRemoved": _integer_schema(),
                    "edgesAdded": _integer_schema(),
                    "edgesRemoved": _integer_schema(),
                },
                "required": ["nodesAdded", "nodesRemoved", "edgesAdded", "edgesRemoved"],
                "additionalProperties": False,
            },
            "nodesAdded": {
                "type": "array",
                "items": _node_schema(),
                "maxItems": MAX_CHANGE_RESULTS,
            },
            "nodesRemoved": {
                "type": "array",
                "items": _node_schema(),
                "maxItems": MAX_CHANGE_RESULTS,
            },
            "edgesAdded": {
                "type": "array",
                "items": _edge_schema(),
                "maxItems": MAX_CHANGE_RESULTS,
            },
            "edgesRemoved": {
                "type": "array",
                "items": _edge_schema(),
                "maxItems": MAX_CHANGE_RESULTS,
            },
            "truncated": {"type": "boolean"},
            "interpretation": _string_schema(500),
        },
        [
            (
                "ok",
                [
                    "workspaceId",
                    "beforeSnapshotId",
                    "afterSnapshotId",
                    "changeBasis",
                    "quality",
                    "counts",
                    "nodesAdded",
                    "nodesRemoved",
                    "edgesAdded",
                    "edgesRemoved",
                    "truncated",
                    "interpretation",
                ],
            )
        ],
    ),
    "ontology_lineage": _contract_schema(
        {
            "workspaceId": _string_schema(100),
            "events": {
                "type": "array",
                "items": LINEAGE_EVENT_SCHEMA,
                "maxItems": MAX_LINEAGE_RESULTS,
            },
            "truncated": {"type": "boolean"},
        },
        [("ok", ["workspaceId", "events", "truncated"])],
    ),
}


def _tool(
    name: str,
    title: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        "outputSchema": OUTPUT_SCHEMAS[name],
        "annotations": {
            "title": title,
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
            "idempotentHint": True,
        },
    }


WORKSPACE_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 100,
    "description": "Local workspace identifier returned by ontology_list_workspaces.",
}
LIMIT_200 = {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}

TOOLS = [
    _tool(
        "ontology_list_workspaces",
        "List code ontology workspaces",
        "List locally registered, explicitly initialized code ontology workspaces. "
        "This does not scan arbitrary directories or create files.",
        {},
    ),
    _tool(
        "ontology_status",
        "Get code ontology status",
        "Read the current snapshot, pipeline health, and source freshness for one registered workspace.",
        {"workspace_id": WORKSPACE_ID},
        ["workspace_id"],
    ),
    _tool(
        "ontology_search",
        "Search a code ontology",
        "Search symbols and concepts in the current immutable ontology snapshot.",
        {
            "workspace_id": WORKSPACE_ID,
            "term": {
                "type": "string",
                "minLength": 1,
                "maxLength": 300,
                "description": "Case-insensitive symbol, annotation, framework, or pipeline term.",
            },
            "limit": LIMIT_200,
        },
        ["workspace_id", "term"],
    ),
    _tool(
        "ontology_neighbors",
        "Inspect possible static impact",
        "Return a bounded relationship neighborhood for an exact or uniquely matched symbol. "
        "Results are static evidence and are not runtime proof.",
        {
            "workspace_id": WORKSPACE_ID,
            "symbol": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
                "description": "Node id, qualified name, or unambiguous symbol name.",
            },
            "depth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
        },
        ["workspace_id", "symbol"],
    ),
    _tool(
        "ontology_history",
        "List ontology snapshots",
        "List immutable snapshots for a registered workspace without reading source bodies.",
        {"workspace_id": WORKSPACE_ID, "limit": LIMIT_200},
        ["workspace_id"],
    ),
    _tool(
        "ontology_changes",
        "Compare ontology snapshots",
        "Compare structural nodes and relationships between two immutable snapshots. "
        "Use current and previous aliases or snapshot identifiers returned by ontology_history.",
        {
            "workspace_id": WORKSPACE_ID,
            "before": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "default": "previous",
            },
            "after": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "default": "current",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
        ["workspace_id"],
    ),
    _tool(
        "ontology_lineage",
        "Read ontology lineage",
        "Read observed, declared, inferred, validated, or approved provenance events "
        "recorded in a registered local workspace.",
        {
            "workspace_id": WORKSPACE_ID,
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            "evidence_type": {
                "type": "string",
                "enum": sorted(companion.EVIDENCE_TYPES),
                "description": "Optional provenance evidence class.",
            },
        },
        ["workspace_id"],
    ),
]

TOOL_ARGUMENTS = {
    tool["name"]: set(tool["inputSchema"]["properties"])
    for tool in TOOLS
}


def _unsafe_output_text(value: str) -> bool:
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        return True
    return any(
        pattern.search(value) is not None
        for pattern in (
            POSIX_ABSOLUTE_PATH_RE,
            WINDOWS_DRIVE_PATH_RE,
            WINDOWS_UNC_PATH_RE,
            WINDOWS_ROOTED_PATH_RE,
            FILE_ABSOLUTE_URI_RE,
        )
    )


def _bounded_text(value: Any, maximum: int, *, required: bool = False) -> str | None:
    if not isinstance(value, str):
        if required:
            raise companion.CompanionError("Malformed local ontology response.")
        return None
    if _unsafe_output_text(value):
        if required:
            raise companion.CompanionError("Malformed local ontology response.")
        return None
    clean = value.strip()
    if not clean:
        if required:
            raise companion.CompanionError("Malformed local ontology response.")
        return None
    return clean[:maximum]


def _bounded_integer(value: Any, maximum: int = MAX_COUNT) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, maximum))


def _bounded_number(value: Any, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return round(max(0.0, min(number, maximum)), 2)


def _mapping_total(
    value: Any,
    maximum: int = MAX_COUNT,
    *,
    allowed_keys: set[str] | None = None,
) -> int:
    if not isinstance(value, dict):
        return 0
    total = sum(
        item
        for key, item in value.items()
        if allowed_keys is None or key in allowed_keys
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    )
    return min(total, maximum)


def _project_counts(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    source_files = raw.get("source_files", raw.get("sourceFiles", 0))
    skipped = raw.get("skipped", raw.get("skippedFiles", 0))
    return {
        "sourceFiles": (
            _mapping_total(
                source_files,
                25_000,
                allowed_keys={"Java", "Python"},
            )
            if isinstance(source_files, dict)
            else _bounded_integer(source_files, 25_000)
        ),
        "nodes": _bounded_integer(raw.get("nodes"), 500_000),
        "edges": _bounded_integer(raw.get("edges"), 1_000_000),
        "warnings": _bounded_integer(raw.get("warnings")),
        "skippedFiles": (
            _mapping_total(
                skipped,
                allowed_keys={
                    "excluded_directory",
                    "unreadable",
                    "symlink_or_reparse",
                    "special_file",
                    "sensitive_name",
                    "too_large",
                },
            )
            if isinstance(skipped, dict)
            else _bounded_integer(skipped)
        ),
    }


def _portable_path(value: Any, maximum: int = 1_000) -> str | None:
    text = _bounded_text(value, maximum)
    if text is None or "\\" in text or text.startswith("/"):
        return None
    if re.match(r"^[A-Za-z]:", text):
        return None
    path = PurePosixPath(text)
    if text in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return text


def _project_quality(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    relationship = raw.get("relationship_evidence")
    relationship = relationship if isinstance(relationship, dict) else {}
    has_contract = isinstance(
        raw.get("contractVersion", raw.get("contract_version")), str
    )
    status = raw.get("status")
    if status not in {"documented", "legacy_unknown"}:
        status = "documented" if has_contract else "legacy_unknown"
    contract_version = _bounded_text(
        raw.get("contractVersion", raw.get("contract_version")), 50
    ) or ("legacy_unknown" if status == "legacy_unknown" else "unknown")
    total_edges = _bounded_integer(
        raw.get("totalEdges", relationship.get("total_edges")), 1_000_000
    )
    documented_edges = min(
        _bounded_integer(
            raw.get("documentedEdges", relationship.get("documented_edges")),
            1_000_000,
        ),
        total_edges,
    )
    missing_evidence = min(
        _bounded_integer(
            raw.get("missingEvidence", relationship.get("missing_evidence")),
            1_000_000,
        ),
        total_edges,
    )
    adapters: dict[str, dict[str, Any]] = {}
    raw_adapters = raw.get("adapters")
    if isinstance(raw_adapters, dict):
        for language in ("Java", "Python"):
            adapter = raw_adapters.get(language)
            adapter_status = adapter.get("status") if isinstance(adapter, dict) else adapter
            text = _bounded_text(adapter_status, 30)
            if text in {"supported", "partial", "unsupported"}:
                raw_capabilities = (
                    adapter.get("capabilities") if isinstance(adapter, dict) else {}
                )
                capabilities: dict[str, str] = {}
                if isinstance(raw_capabilities, dict):
                    for name in sorted(CAPABILITY_NAMES):
                        capability_status = _bounded_text(
                            raw_capabilities.get(name), 30
                        )
                        if capability_status in {
                            "supported",
                            "partial",
                            "unsupported",
                        }:
                            capabilities[name] = capability_status
                        if len(capabilities) >= MAX_ADAPTER_CAPABILITIES:
                            break
                raw_unsupported = (
                    adapter.get(
                        "unsupportedRuntime",
                        adapter.get("unsupported_runtime"),
                    )
                    if isinstance(adapter, dict)
                    else []
                )
                unsupported_runtime = []
                if isinstance(raw_unsupported, list):
                    for value in raw_unsupported[:MAX_UNSUPPORTED_RUNTIME_ITEMS]:
                        clean = _bounded_text(value, 80)
                        if clean is not None and re.fullmatch(
                            r"[a-z][a-z0-9_.-]{2,79}", clean
                        ):
                            unsupported_runtime.append(clean)
                adapters[language] = {
                    "status": text,
                    "detected": (
                        adapter.get("detected") is True
                        if isinstance(adapter, dict)
                        else False
                    ),
                    "capabilities": capabilities,
                    "unsupportedRuntime": unsupported_runtime,
                }
    return {
        "status": status,
        "contractVersion": contract_version,
        "totalEdges": total_edges,
        "documentedEdges": documented_edges,
        "missingEvidence": missing_evidence,
        "coveragePercent": _bounded_number(
            raw.get("coveragePercent", relationship.get("coverage_percent")), 100.0
        ),
        "adapters": adapters,
    }


def _project_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    projected: list[dict[str, Any]] = []
    for item in value[:MAX_EDGE_EVIDENCE_ITEMS]:
        if not isinstance(item, dict):
            continue
        rule_id = _bounded_text(item.get("rule_id", item.get("ruleId")), 80)
        basis = _bounded_text(item.get("basis"), 50)
        runtime_status = _bounded_text(
            item.get("runtime_status", item.get("runtimeStatus")), 50
        )
        if (
            rule_id is None
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", rule_id)
            or basis not in core.EVIDENCE_BASES
            or runtime_status not in core.RUNTIME_STATUSES
        ):
            continue
        evidence: dict[str, Any] = {
            "ruleId": rule_id,
            "basis": basis,
            "runtimeStatus": runtime_status,
        }
        path = _portable_path(item.get("path"), MAX_EVIDENCE_PATH_LENGTH)
        if path is not None:
            evidence["path"] = path
        line_start = _bounded_integer(
            item.get("line_start", item.get("lineStart")), MAX_EVIDENCE_LINE
        )
        line_end = _bounded_integer(
            item.get("line_end", item.get("lineEnd")), MAX_EVIDENCE_LINE
        )
        if line_start >= 1:
            evidence["lineStart"] = line_start
            evidence["lineEnd"] = max(line_start, line_end or line_start)
        limitations = item.get("limitations")
        if isinstance(limitations, list):
            clean_limitations = [
                text
                for limitation in limitations[:MAX_EVIDENCE_LIMITATIONS]
                if (text := _bounded_text(limitation, 200)) is not None
            ]
            if clean_limitations:
                evidence["limitations"] = clean_limitations
        projected.append(evidence)
    return projected


def _project_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    projected: dict[str, Any] = {}
    for source, target, maximum in (
        ("return_type", "returnType", 500),
        ("accessor", "accessor", 100),
        ("control_kind", "controlKind", 100),
    ):
        text = _bounded_text(value.get(source), maximum)
        if text is not None:
            projected[target] = text
    parameter_types = value.get("parameter_types")
    if isinstance(parameter_types, list):
        projected["parameterTypes"] = [
            text
            for item in parameter_types[:64]
            if (text := _bounded_text(item, 500)) is not None
        ]
    semantic_groups = value.get("semantic_groups")
    if isinstance(semantic_groups, list):
        projected["semanticGroups"] = [
            text
            for item in semantic_groups[:20]
            if (text := _bounded_text(item, 100)) is not None
        ]
    if "parameter_count" in value:
        projected["parameterCount"] = _bounded_integer(value.get("parameter_count"), 1_000)
    if "ordinal" in value:
        projected["ordinal"] = _bounded_integer(value.get("ordinal"), 1_000_000)
    return projected or None


def _project_node(value: Any, *, reference_only: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    node_id = _bounded_text(value.get("id"), 1_000)
    name = _bounded_text(value.get("name"), 500)
    if node_id is None or name is None:
        return None
    projected: dict[str, Any] = {"id": node_id, "name": name}
    qualified = _bounded_text(
        value.get("qualified_name", value.get("qualifiedName")), 1_000
    )
    if qualified is not None:
        projected["qualifiedName"] = qualified
    if reference_only:
        return projected
    node_type = _bounded_text(value.get("type"), 100)
    language = _bounded_text(value.get("language"), 100)
    if node_type is None or language is None:
        return None
    projected["type"] = node_type
    projected["language"] = language
    path = _portable_path(value.get("path"))
    if path is not None:
        projected["path"] = path
    metadata = _project_metadata(value.get("metadata"))
    if metadata is not None:
        projected["metadata"] = metadata
    return projected


def _project_nodes(value: Any, maximum: int) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(value, list):
        return [], False
    projected = [
        node
        for item in value[:maximum]
        if (node := _project_node(item)) is not None
    ]
    return projected, len(value) > maximum


def _project_workspace_items(value: Any) -> tuple[list[dict[str, str]], bool]:
    if not isinstance(value, list):
        return [], False
    projected: list[dict[str, str]] = []
    for item in value[:MAX_WORKSPACES]:
        if not isinstance(item, dict):
            continue
        workspace_id = _bounded_text(item.get("id"), 100)
        label = _bounded_text(item.get("label"), 300)
        if workspace_id is not None and label is not None:
            projected.append({"id": workspace_id, "label": label})
    return projected, len(value) > MAX_WORKSPACES


def _required_text(raw: dict[str, Any], name: str, maximum: int) -> str:
    value = _bounded_text(raw.get(name), maximum, required=True)
    assert value is not None
    return value


def _expect_ok(raw: dict[str, Any]) -> None:
    if raw.get("status") != "ok":
        raise companion.CompanionError("Malformed local ontology response.")


def _project_list(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    workspaces, workspaces_truncated = _project_workspace_items(raw.get("workspaces"))
    stale, stale_truncated = _project_workspace_items(raw.get("staleRegistrations"))
    return {
        "status": "ok",
        "workspaces": workspaces,
        "staleRegistrations": stale,
        "truncated": workspaces_truncated or stale_truncated,
    }


def _project_status(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status")
    if status not in {"ok", "partial"}:
        raise companion.CompanionError("Malformed local ontology response.")
    projected: dict[str, Any] = {
        "status": status,
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "repositoryLabel": _required_text(raw, "repositoryLabel", 300),
        "freshness": raw.get("freshness")
        if raw.get("freshness") in {"current", "stale", "unknown", "partial", "snapshot"}
        else "unknown",
    }
    for name, maximum in (
        ("snapshotId", 100),
        ("previousSnapshotId", 100),
        ("generatedAt", 100),
        ("snapshotAnalyzerVersion", 50),
        ("currentAnalyzerVersion", 50),
        ("snapshotCompanionVersion", 50),
        ("currentCompanionVersion", 50),
        ("evidenceType", 50),
    ):
        text = _bounded_text(raw.get(name), maximum)
        if text is not None:
            projected[name] = text
    message = _bounded_text(raw.get("message"), MAX_ERROR_TEXT)
    if message is not None:
        projected["message"] = message
    if status == "partial" and message is None:
        raise companion.CompanionError("Malformed local ontology response.")
    if status == "ok":
        if "snapshotId" not in projected:
            raise companion.CompanionError("Malformed local ontology response.")
        projected["counts"] = _project_counts(raw.get("counts"))
        projected["quality"] = _project_quality(raw.get("quality"))
        pipeline = raw.get("pipelineStatus")
        projected["pipelineStatus"] = (
            pipeline
            if pipeline in {"healthy", "refresh_required", "partial", "unknown"}
            else "unknown"
        )
    return projected


def _project_search(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    matches, truncated_by_boundary = _project_nodes(raw.get("matches"), MAX_SEARCH_RESULTS)
    match_count = _bounded_integer(raw.get("match_count"), 500_000)
    return {
        "status": "ok",
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "snapshotId": _required_text(raw, "snapshotId", 100),
        "freshness": "snapshot",
        "evidenceType": _bounded_text(raw.get("evidenceType"), 50) or "observed",
        "term": _required_text(raw, "term", 300),
        "matchCount": match_count,
        "returned": len(matches),
        "matches": matches,
        "truncated": truncated_by_boundary or match_count > len(matches),
    }


def _project_neighbors(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status")
    if status not in {"ok", "not_found", "ambiguous"}:
        raise companion.CompanionError("Malformed local ontology response.")
    impact_items = raw.get("impact")
    projected_impact: list[dict[str, Any]] = []
    impact_truncated = isinstance(impact_items, list) and len(impact_items) > MAX_IMPACT_RESULTS
    if isinstance(impact_items, list):
        for item in impact_items[:MAX_IMPACT_RESULTS]:
            if not isinstance(item, dict):
                continue
            node = _project_node(item.get("node"))
            relationship = _bounded_text(item.get("relationship"), 100)
            direction = item.get("direction")
            depth = item.get("depth")
            if (
                node is not None
                and relationship is not None
                and direction in {"incoming", "outgoing"}
                and isinstance(depth, int)
                and not isinstance(depth, bool)
                and 1 <= depth <= 5
            ):
                projected_impact.append(
                    {
                        "depth": depth,
                        "relationship": relationship,
                        "direction": direction,
                        "node": node,
                        "evidence": _project_evidence(item.get("evidence")),
                    }
                )
    projected: dict[str, Any] = {
        "status": status,
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "snapshotId": _required_text(raw, "snapshotId", 100),
        "freshness": "snapshot",
        "evidenceType": _bounded_text(raw.get("evidenceType"), 50) or "observed",
        "symbol": _required_text(raw, "symbol", 500),
        "impact": projected_impact,
    }
    if status in {"not_found", "ambiguous"}:
        candidates: list[dict[str, Any]] = []
        raw_candidates = raw.get("candidates")
        if isinstance(raw_candidates, list):
            candidates = [
                node
                for item in raw_candidates[:20]
                if (node := _project_node(item, reference_only=True)) is not None
            ]
        projected["candidates"] = candidates
        return projected
    root = _project_node(raw.get("root"))
    if root is None:
        raise companion.CompanionError("Malformed local ontology response.")
    projected.update(
        {
            "root": root,
            "depth": max(1, min(_bounded_integer(raw.get("depth"), 5), 5)),
            "impactCount": len(projected_impact),
            "truncated": bool(raw.get("truncated")) or impact_truncated,
            "interpretation": _bounded_text(raw.get("interpretation"), 500)
            or "Possible static impact; validate runtime behavior separately.",
        }
    )
    return projected


def _project_history(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    snapshots: list[dict[str, Any]] = []
    raw_snapshots = raw.get("snapshots")
    truncated = isinstance(raw_snapshots, list) and len(raw_snapshots) > MAX_HISTORY_RESULTS
    if isinstance(raw_snapshots, list):
        for item in raw_snapshots[:MAX_HISTORY_RESULTS]:
            if not isinstance(item, dict):
                continue
            snapshot_id = _bounded_text(item.get("snapshotId"), 100)
            if snapshot_id is None:
                continue
            projected: dict[str, Any] = {
                "snapshotId": snapshot_id,
                "counts": _project_counts(item.get("counts")),
            }
            for name in ("createdAt", "trigger"):
                text = _bounded_text(item.get(name), 100)
                if text is not None:
                    projected[name] = text
            snapshots.append(projected)
    return {
        "status": "ok",
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "snapshots": snapshots,
        "truncated": bool(raw.get("truncated")) or truncated,
    }


def _project_diff_counts(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    return {
        name: _bounded_integer(raw.get(name))
        for name in ("nodesAdded", "nodesRemoved", "edgesAdded", "edgesRemoved")
    }


def _project_edges(value: Any) -> tuple[list[dict[str, str]], bool]:
    if not isinstance(value, list):
        return [], False
    projected: list[dict[str, str]] = []
    for item in value[:MAX_CHANGE_RESULTS]:
        if not isinstance(item, dict):
            continue
        source = _bounded_text(item.get("source"), 1_000)
        edge_type = _bounded_text(item.get("type"), 100)
        target = _bounded_text(item.get("target"), 1_000)
        if source is not None and edge_type is not None and target is not None:
            projected.append({"source": source, "type": edge_type, "target": target})
    return projected, len(value) > MAX_CHANGE_RESULTS


def _project_changes(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    nodes_added, nodes_added_truncated = _project_nodes(
        raw.get("nodesAdded"), MAX_CHANGE_RESULTS
    )
    nodes_removed, nodes_removed_truncated = _project_nodes(
        raw.get("nodesRemoved"), MAX_CHANGE_RESULTS
    )
    edges_added, edges_added_truncated = _project_edges(raw.get("edgesAdded"))
    edges_removed, edges_removed_truncated = _project_edges(raw.get("edgesRemoved"))
    change_basis = raw.get("changeBasis")
    if change_basis not in {
        "source_change",
        "analyzer_reinterpretation",
        "analysis_refresh",
        "mixed",
        "no_change",
        "legacy_unknown",
    }:
        change_basis = "legacy_unknown"
    return {
        "status": "ok",
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "beforeSnapshotId": _required_text(raw, "beforeSnapshotId", 100),
        "afterSnapshotId": _required_text(raw, "afterSnapshotId", 100),
        "changeBasis": change_basis,
        "quality": _project_quality(raw.get("quality")),
        "counts": _project_diff_counts(raw.get("counts")),
        "nodesAdded": nodes_added,
        "nodesRemoved": nodes_removed,
        "edgesAdded": edges_added,
        "edgesRemoved": edges_removed,
        "truncated": bool(raw.get("truncated"))
        or nodes_added_truncated
        or nodes_removed_truncated
        or edges_added_truncated
        or edges_removed_truncated,
        "interpretation": _bounded_text(raw.get("interpretation"), 500)
        or "Structural static diff; correlation is not causation.",
    }


def _project_lineage(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    events: list[dict[str, Any]] = []
    raw_events = raw.get("events")
    truncated = isinstance(raw_events, list) and len(raw_events) > MAX_LINEAGE_RESULTS
    if isinstance(raw_events, list):
        for item in raw_events[:MAX_LINEAGE_RESULTS]:
            if not isinstance(item, dict):
                continue
            event_id = _bounded_text(item.get("eventId"), 100)
            kind = _bounded_text(item.get("kind"), 100)
            evidence_type = _bounded_text(item.get("evidenceType"), 50)
            summary = _bounded_text(item.get("summary"), 1_000)
            if None in {event_id, kind, evidence_type, summary}:
                continue
            event: dict[str, Any] = {
                "eventId": event_id,
                "kind": kind,
                "evidenceType": evidence_type,
                "summary": summary,
            }
            for name, maximum in (
                ("subject", 300),
                ("snapshotId", 100),
                ("previousSnapshotId", 100),
                ("recordedAt", 100),
            ):
                text = _bounded_text(item.get(name), maximum)
                if text is not None:
                    event[name] = text
            events.append(event)
    return {
        "status": "ok",
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "events": events,
        "truncated": bool(raw.get("truncated")) or truncated,
    }


PROJECTORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "ontology_list_workspaces": _project_list,
    "ontology_status": _project_status,
    "ontology_search": _project_search,
    "ontology_neighbors": _project_neighbors,
    "ontology_history": _project_history,
    "ontology_changes": _project_changes,
    "ontology_lineage": _project_lineage,
}


def _project_result(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or name not in PROJECTORS:
        raise companion.CompanionError("Malformed local ontology response.")
    return PROJECTORS[name](value)


def _workspace_path(arguments: dict[str, Any]) -> str:
    workspace_id = _string(arguments, "workspace_id", maximum=100)
    return str(companion.resolve_registered_workspace(workspace_id))


def _integer(arguments: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise companion.CompanionError(f"{name} must be an integer from {minimum} to {maximum}.")
    return value


def _string(
    arguments: dict[str, Any],
    name: str,
    *,
    default: str | None = None,
    maximum: int = 500,
) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise companion.CompanionError(f"{name} must contain 1 to {maximum} characters.")
    return value.strip()


def _validate_arguments(name: str, arguments: dict[str, Any]) -> None:
    allowed = TOOL_ARGUMENTS.get(name)
    if allowed is None:
        raise companion.CompanionError(f"Unknown tool: {name}")
    if set(arguments) - allowed:
        raise companion.CompanionError("Unsupported tool argument.")


def _dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _validate_arguments(name, arguments)
    if name == "ontology_list_workspaces":
        return companion.list_workspaces()
    workspace = _workspace_path(arguments)
    if name == "ontology_status":
        return companion.status(workspace, check_freshness=True)
    if name == "ontology_search":
        result = companion.query(
            workspace,
            _string(arguments, "term", maximum=300),
            _integer(arguments, "limit", 20, 1, 200),
        )
        if isinstance(result, dict) and "status" not in result:
            return {"status": "ok", **result}
        return result
    if name == "ontology_neighbors":
        return companion.impact(
            workspace,
            _string(arguments, "symbol", maximum=500),
            _integer(arguments, "depth", 2, 1, 5),
        )
    if name == "ontology_history":
        return companion.history(workspace, _integer(arguments, "limit", 20, 1, 200))
    if name == "ontology_changes":
        return companion.diff(
            workspace,
            _string(arguments, "before", default="previous", maximum=100),
            _string(arguments, "after", default="current", maximum=100),
            _integer(arguments, "limit", 100, 1, 500),
        )
    if name == "ontology_lineage":
        evidence_type = arguments.get("evidence_type")
        if evidence_type is not None and evidence_type not in companion.EVIDENCE_TYPES:
            raise companion.CompanionError("Unsupported evidence_type.")
        return companion.lineage(
            workspace,
            _integer(arguments, "limit", 50, 1, 500),
            evidence_type,
        )
    raise companion.CompanionError(f"Unknown tool: {name}")


def _response(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _public_error(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("Unknown workspace id"):
        return "Unknown workspace id."
    if message in {
        "workspace_id is required.",
        "Unsupported evidence_type.",
        "Unsupported tool argument.",
        "Malformed local ontology response.",
    }:
        return message
    if re.fullmatch(
        r"(?:term|symbol|before|after) must contain 1 to \d+ characters\.", message
    ) or re.fullmatch(
        r"(?:limit|depth) must be an integer from \d+ to \d+\.", message
    ):
        return message[:MAX_ERROR_TEXT]
    return "The local ontology request could not be completed."


def _tool_result(result: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": result,
        "isError": is_error,
    }


def _negotiate_protocol_version(requested: Any) -> str:
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return DEFAULT_PROTOCOL_VERSION


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(message_id, -32602, "params must be an object")

    if method == "initialize":
        requested = params.get("protocolVersion")
        protocol = _negotiate_protocol_version(requested)
        return _response(
            message_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "This local server only reads explicitly initialized ontology workspaces. "
                    "Use the bundled skill for preflight, initialization, refresh, and lineage writes."
                ),
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return _response(message_id, {})
    if method == "tools/list":
        return _response(message_id, {"tools": TOOLS})
    if method == "resources/list":
        return _response(message_id, {"resources": []})
    if method == "prompts/list":
        return _response(message_id, {"prompts": []})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(message_id, -32602, "Tool name and object arguments are required.")
        try:
            result = _project_result(name, _dispatch(name, arguments))
            return _response(message_id, _tool_result(result, is_error=False))
        except (companion.CompanionError, core.OntologyError) as exc:
            result = {"status": "error", "message": _public_error(exc)}
            return _response(message_id, _tool_result(result, is_error=True))
    return _error(message_id, -32601, f"Method not found: {method}")


def _force_utf8_stdio() -> None:
    """Keep the MCP wire UTF-8 regardless of the Windows active code page."""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            raise RuntimeError("MCP stdio does not support explicit UTF-8 configuration.")
        reconfigure(encoding="utf-8", errors="strict", newline="\n")


def main() -> int:
    _force_utf8_stdio()
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError("message must be an object")
            response = _handle(value)
        except (json.JSONDecodeError, ValueError) as exc:
            response = _error(None, -32700, f"Parse error: {exc}")
        except Exception:
            response = _error(None, -32603, "Internal server error")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
