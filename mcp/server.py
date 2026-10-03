#!/usr/bin/env python3
"""Read-only stdio MCP server for registered Code Ontology workspaces."""

from __future__ import annotations

import copy
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
SERVER_VERSION = "0.8.0"
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
MAX_LARGE_MODULES = 128
MAX_LARGE_OCCURRENCES = MAX_LARGE_MODULES * 500_000
MAX_BUNDLE_REQUESTS = 8
MAX_BUNDLE_RESULTS = 200
MAX_BUNDLE_PAYLOAD_BYTES = 256 * 1024

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
            "lineStart": _integer_schema(MAX_EVIDENCE_LINE, 1),
            "lineEnd": _integer_schema(MAX_EVIDENCE_LINE, 1),
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
        "evidenceId": _string_schema(40),
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
    "properties": {"id": _string_schema(100), "label": _string_schema(300),
                   "mode": _string_schema(20, enum=["normal", "large"])},
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
            "sourceRoots": {"type": "array", "items": _string_schema(1_000), "maxItems": 1_000},
            "snapshotSourceRoots": {"type": "array", "items": _string_schema(1_000), "maxItems": 1_000},
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
                    "source_scope_change",
                    "analyzer_reinterpretation",
                    "analysis_refresh",
                    "mixed",
                    "no_change",
                    "legacy_unknown",
                ],
            ),
            "quality": QUALITY_SCHEMA,
            "sourceScopeChanged": {"type": "boolean"},
            "beforeSourceRoots": {"type": "array", "items": _string_schema(1_000), "maxItems": 1_000},
            "afterSourceRoots": {"type": "array", "items": _string_schema(1_000), "maxItems": 1_000},
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

# Additive 0.6 fields remain optional for readable pre-0.6 snapshots.
SCOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "basis": _string_schema(30, enum=["static_snapshot"]),
        "completeness": _string_schema(30, enum=["unknown"]),
        "returnedNodes": _integer_schema(500_000),
        "externalOrUnresolvedNodes": _integer_schema(500_000),
        "snapshotWarningCount": _integer_schema(),
        "unresolvedCallCountKnown": {"type": "boolean"},
        "unresolvedCallCount": _integer_schema(),
        "interpretation": _string_schema(300),
    },
    "required": ["basis", "completeness", "unresolvedCallCountKnown"],
    "additionalProperties": False,
}
PATH_STEP_SCHEMA = _edge_schema()
PATH_STEP_SCHEMA["properties"].update({
    "direction": _string_schema(20, enum=["incoming", "outgoing"]),
    "evidence": {"type": "array", "items": EVIDENCE_SCHEMA, "maxItems": MAX_EDGE_EVIDENCE_ITEMS},
})
PATH_STEP_SCHEMA["required"].extend(["direction", "evidence"])
for tool_name in ("ontology_search", "ontology_neighbors"):
    OUTPUT_SCHEMAS[tool_name]["properties"].update({"scope": SCOPE_SCHEMA, "quality": QUALITY_SCHEMA})
OUTPUT_SCHEMAS["ontology_search"]["properties"].update({
    "offset": _integer_schema(500_000), "nextOffset": _integer_schema(500_000),
})
OUTPUT_SCHEMAS["ontology_neighbors"]["properties"].update({
    "direction": _string_schema(20, enum=["incoming", "outgoing", "both"]),
    "relationships": {"type": "array", "items": _string_schema(100), "maxItems": 32},
    "excludedEdges": _integer_schema(1_000_000),
    "excludedEdgesScope": _string_schema(40, enum=["encountered_during_traversal"]),
})
OUTPUT_SCHEMAS["ontology_neighbors"]["properties"]["impact"]["items"]["properties"].update({
    "via": _string_schema(1_000),
    "path": {"type": "array", "items": PATH_STEP_SCHEMA, "maxItems": 5},
})
MODIFIED_EDGE_SCHEMA = _edge_schema()
for evidence_field in ("evidence", "previousEvidence"):
    MODIFIED_EDGE_SCHEMA["properties"][evidence_field] = {
        "type": "array", "items": EVIDENCE_SCHEMA, "maxItems": MAX_EDGE_EVIDENCE_ITEMS,
    }
OUTPUT_SCHEMAS["ontology_changes"]["properties"].update({
    "nodesModified": {"type": "array", "items": _node_schema(), "maxItems": MAX_CHANGE_RESULTS},
    "edgesModified": {"type": "array", "items": MODIFIED_EDGE_SCHEMA, "maxItems": MAX_CHANGE_RESULTS},
})
OUTPUT_SCHEMAS["ontology_changes"]["properties"]["counts"]["properties"].update({
    "nodesModified": _integer_schema(), "edgesModified": _integer_schema(),
})

LARGE_COMMON_SCHEMA = {
    "workspaceId": _string_schema(100),
    "catalogSnapshotId": _string_schema(100),
    "freshness": _string_schema(30, enum=["pinned_snapshot"]),
    "freshnessCaveat": _string_schema(300),
    "crossModuleResolution": _string_schema(30, enum=["unsupported"]),
    "limitations": {"type": "array", "items": _string_schema(300), "maxItems": 16},
    "targetCodeExecuted": {"type": "boolean", "const": False},
    "networkAccess": {"type": "boolean", "const": False},
}
LARGE_COMMON_REQUIRED = ["workspaceId", "catalogSnapshotId", "freshness", "freshnessCaveat",
                         "crossModuleResolution", "limitations", "targetCodeExecuted", "networkAccess"]
LARGE_MODULE_SCHEMA = {
    "type": "object",
    "properties": {
        "moduleId": _string_schema(100), "root": _string_schema(1_000),
        "snapshotId": _string_schema(100), "workspaceId": _string_schema(100),
        "counts": _counts_schema(), "sourceFileCount": _integer_schema(25_000),
        "supportedSourceBytes": _integer_schema(),
        "versionFreshness": _string_schema(20, enum=["current", "stale"]),
        "analyzerVersion": _string_schema(50), "companionVersion": _string_schema(50),
        "matchOccurrences": _integer_schema(500_000), "scope": SCOPE_SCHEMA,
    },
    "required": ["moduleId", "root", "snapshotId"],
    "additionalProperties": False,
}
OUTPUT_SCHEMAS["ontology_large_modules"] = _contract_schema({
    **LARGE_COMMON_SCHEMA,
    "term": _string_schema(300), "moduleCount": _integer_schema(MAX_LARGE_MODULES),
    "matchedModuleCount": _integer_schema(MAX_LARGE_MODULES),
    "offset": _integer_schema(MAX_LARGE_MODULES), "nextOffset": _integer_schema(MAX_LARGE_MODULES),
    "returned": _integer_schema(MAX_LARGE_MODULES), "truncated": {"type": "boolean"},
    "metadataOnly": {"type": "boolean", "const": True},
    "modules": {"type": "array", "items": LARGE_MODULE_SCHEMA, "maxItems": MAX_LARGE_MODULES},
}, [("ok", [*LARGE_COMMON_REQUIRED, "term", "moduleCount", "matchedModuleCount", "offset",
            "returned", "truncated", "metadataOnly", "modules"])])
LARGE_MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "moduleId": _string_schema(100), "moduleRoot": _string_schema(1_000),
        "moduleWorkspaceId": _string_schema(100), "moduleSnapshotId": _string_schema(100),
        "node": _node_schema(),
    },
    "required": ["moduleId", "moduleRoot", "moduleWorkspaceId", "moduleSnapshotId", "node"],
    "additionalProperties": False,
}
OUTPUT_SCHEMAS["ontology_large_search"] = _contract_schema({
    **LARGE_COMMON_SCHEMA,
    "term": _string_schema(300), "moduleCount": _integer_schema(MAX_LARGE_MODULES),
    "moduleMatchOccurrences": _integer_schema(MAX_LARGE_OCCURRENCES),
    "offset": _integer_schema(MAX_LARGE_OCCURRENCES), "nextOffset": _integer_schema(MAX_LARGE_OCCURRENCES),
    "returned": _integer_schema(MAX_SEARCH_RESULTS), "truncated": {"type": "boolean"},
    "order": _string_schema(80, enum=["configured_module_order_then_module_search_rank"]),
    "selectedModuleRoots": {"type": "array", "items": _string_schema(1_000), "maxItems": MAX_LARGE_MODULES},
    "matches": {"type": "array", "items": LARGE_MATCH_SCHEMA, "maxItems": MAX_SEARCH_RESULTS},
    "modules": {"type": "array", "items": LARGE_MODULE_SCHEMA, "maxItems": MAX_LARGE_MODULES},
}, [("ok", [*LARGE_COMMON_REQUIRED, "term", "moduleCount", "moduleMatchOccurrences", "offset",
            "returned", "truncated", "order", "selectedModuleRoots", "matches", "modules"])])
OUTPUT_SCHEMAS["ontology_large_neighbors"] = copy.deepcopy(OUTPUT_SCHEMAS["ontology_neighbors"])
OUTPUT_SCHEMAS["ontology_large_neighbors"]["properties"].update({
    **LARGE_COMMON_SCHEMA, "moduleId": _string_schema(100), "moduleRoot": _string_schema(1_000),
    "moduleWorkspaceId": _string_schema(100), "moduleSnapshotId": _string_schema(100),
})
for variant in OUTPUT_SCHEMAS["ontology_large_neighbors"]["oneOf"]:
    if variant["properties"]["status"]["const"] != "error":
        variant["required"] = [field for field in variant["required"] if field not in {"snapshotId", "freshness"}]
        variant["required"].extend([*LARGE_COMMON_REQUIRED, "moduleId", "moduleRoot", "moduleWorkspaceId", "moduleSnapshotId"])
del OUTPUT_SCHEMAS["ontology_large_neighbors"]["properties"]["snapshotId"]

BUNDLE_ITEM_SCHEMA = _contract_schema({
    "id": _string_schema(40), "operation": _string_schema(20, enum=["search", "neighbors"]),
    "search": OUTPUT_SCHEMAS["ontology_search"], "neighbors": OUTPUT_SCHEMAS["ontology_neighbors"],
}, [("ok", ["id", "operation"])])
BUNDLE_ITEM_SCHEMA["oneOf"] = [
    {"properties": {"status": {"const": "ok"}, "operation": {"const": operation}},
     "required": ["status", "id", "operation", operation],
     "not": {"required": ["neighbors" if operation == "search" else "search"]}}
    for operation in ("search", "neighbors")
] + [{"properties": {"status": {"const": "error"}},
      "required": ["status", "id", "operation", "message"],
      "not": {"anyOf": [{"required": ["search"]}, {"required": ["neighbors"]}]}}]
OUTPUT_SCHEMAS["ontology_evidence_bundle"] = _contract_schema({
    "workspaceId": _string_schema(100), "snapshotId": _string_schema(100),
    "freshness": _string_schema(30, enum=["snapshot"]),
    "requestCount": _integer_schema(MAX_BUNDLE_REQUESTS, 1),
    "succeeded": _integer_schema(MAX_BUNDLE_REQUESTS), "failed": _integer_schema(MAX_BUNDLE_REQUESTS),
    "returnedResults": _integer_schema(MAX_BUNDLE_RESULTS),
    "maxResults": _integer_schema(MAX_BUNDLE_RESULTS),
    "maxPayloadBytes": _integer_schema(MAX_BUNDLE_PAYLOAD_BYTES),
    "payloadBytes": _integer_schema(MAX_BUNDLE_PAYLOAD_BYTES),
    "items": {"type": "array", "items": BUNDLE_ITEM_SCHEMA, "maxItems": MAX_BUNDLE_REQUESTS},
}, [(status, ["workspaceId", "snapshotId", "freshness", "requestCount", "succeeded", "failed",
             "returnedResults", "maxResults", "maxPayloadBytes", "payloadBytes", "items"])
    for status in ("ok", "partial")])


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
        "Search symbols and concepts in the current or selected immutable snapshot, "
        "with exact-identity ranking, language/type/path filters, and bounded pagination.",
        {
            "workspace_id": WORKSPACE_ID,
            "term": {
                "type": "string",
                "minLength": 1,
                "maxLength": 300,
                "description": "Case-insensitive symbol, annotation, framework, or pipeline term.",
            },
            "limit": LIMIT_200,
            "snapshot_id": _string_schema(100),
            "offset": _integer_schema(500_000),
            "language": _string_schema(100),
            "node_type": _string_schema(100),
            "path_prefix": _string_schema(1000),
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
            "snapshot_id": _string_schema(100),
            "direction": _string_schema(20, enum=["incoming", "outgoing", "both"]),
            "relationships": {"type": "array", "items": _string_schema(100, enum=sorted(core.EDGE_EVIDENCE_DEFAULTS)), "maxItems": 32},
            "limit": _integer_schema(MAX_IMPACT_RESULTS, 1),
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

MODULE_ROOTS_INPUT = {
    "type": "array", "items": _string_schema(1_000), "minItems": 1, "maxItems": MAX_LARGE_MODULES,
    "uniqueItems": True,
    "description": "Exact configured repository-relative roots returned by ontology_large_modules.",
}
SEARCH_SELECTORS_INPUT = {name: copy.deepcopy(TOOLS[2]["inputSchema"]["properties"][name])
                          for name in ("language", "node_type", "path_prefix")}
NEIGHBOR_SELECTORS_INPUT = {name: copy.deepcopy(TOOLS[3]["inputSchema"]["properties"][name])
                            for name in ("depth", "direction", "relationships")}
TOOLS.extend([
    _tool("ontology_large_modules", "List pinned large-project modules",
          "Read module metadata from an initialized, registered large parent without loading ontology graphs. "
          "Pin subsequent reads with the returned catalogSnapshotId; retrieval does not check source freshness.",
          {"workspace_id": WORKSPACE_ID, "catalog_snapshot_id": _string_schema(100),
           "term": _string_schema(300), "offset": _integer_schema(MAX_LARGE_MODULES), "limit": LIMIT_200},
          ["workspace_id"]),
    _tool("ontology_large_search", "Search selected pinned modules",
          "Search exact configured module scopes using a shared result limit and catalog-pinned child snapshots. "
          "No cross-module relationships are inferred.",
          {"workspace_id": WORKSPACE_ID, "catalog_snapshot_id": _string_schema(100),
           "module_roots": MODULE_ROOTS_INPUT, "term": copy.deepcopy(TOOLS[2]["inputSchema"]["properties"]["term"]),
           "offset": _integer_schema(MAX_LARGE_OCCURRENCES), "limit": LIMIT_200, **SEARCH_SELECTORS_INPUT},
          ["workspace_id", "module_roots", "term"]),
    _tool("ontology_large_neighbors", "Inspect one pinned module's static impact",
          "Follow bounded dependency paths inside one exact module pinned by its catalog. "
          "Cross-module resolution remains unsupported and static evidence is not runtime proof.",
          {"workspace_id": WORKSPACE_ID, "catalog_snapshot_id": _string_schema(100),
           "module_root": _string_schema(1_000), "symbol": copy.deepcopy(TOOLS[3]["inputSchema"]["properties"]["symbol"]),
           "limit": _integer_schema(MAX_IMPACT_RESULTS, 1), **NEIGHBOR_SELECTORS_INPUT},
          ["workspace_id", "module_root", "symbol"]),
    _tool("ontology_evidence_bundle", "Read a bounded bundle from one snapshot",
          "Run up to eight search/neighbor reads against one snapshot resolved once. "
          "Results are projected individually; failed or oversized items report safe errors. "
          "The shared response budget is 200 result nodes and 262144 UTF-8 bytes of canonical structured JSON. "
          "MCP transport wrappers and the duplicated text representation are outside that byte budget.",
          {"workspace_id": WORKSPACE_ID, "snapshot_id": _string_schema(100),
           "requests": {"type": "array", "minItems": 1, "maxItems": MAX_BUNDLE_REQUESTS,
                        "items": {"type": "object", "additionalProperties": False,
                                  "required": ["id", "operation"],
                                  "properties": {
                                      "id": {"type": "string", "minLength": 1, "maxLength": 40,
                                             "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]*$"},
                                      "operation": _string_schema(20, enum=["search", "neighbors"]),
                                      "term": copy.deepcopy(TOOLS[2]["inputSchema"]["properties"]["term"]),
                                      "symbol": copy.deepcopy(TOOLS[3]["inputSchema"]["properties"]["symbol"]),
                                      "offset": _integer_schema(500_000),
                                      "limit": _integer_schema(MAX_BUNDLE_RESULTS, 1),
                                      **SEARCH_SELECTORS_INPUT, **NEIGHBOR_SELECTORS_INPUT,
                                  }}}},
          ["workspace_id", "requests"]),
])

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
        evidence_id = item.get("evidence_id", item.get("evidenceId"))
        if isinstance(evidence_id, str) and re.fullmatch(r"evidence:[0-9a-f]{24}", evidence_id):
            evidence["evidenceId"] = evidence_id
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
    for source, target in (("line_start", "lineStart"), ("line_end", "lineEnd")):
        line = _bounded_integer(value.get(source), MAX_EVIDENCE_LINE)
        if line:
            projected[target] = line
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
            if item.get("mode") in {"normal", "large"}:
                projected[-1]["mode"] = item["mode"]
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


def _project_source_roots(raw: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for name in names:
        if name not in raw:
            continue
        roots = raw[name]
        if not isinstance(roots, list) or len(roots) > 1_000:
            raise companion.CompanionError("Malformed or excessive source scope metadata.")
        if any(_portable_path(root) != root or not isinstance(root, str) for root in roots):
            raise companion.CompanionError("Source scope metadata must use portable relative paths.")
        projected[name] = list(roots)
    return projected


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
    projected.update(_project_source_roots(raw, ("sourceRoots", "snapshotSourceRoots")))
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


def _project_scope(raw: Any) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    unresolved = value.get("unresolved_call_count")
    known = isinstance(unresolved, int) and not isinstance(unresolved, bool) and unresolved >= 0
    result = {
        "basis": "static_snapshot", "completeness": "unknown",
        "returnedNodes": _bounded_integer(value.get("returned_nodes"), 500_000),
        "externalOrUnresolvedNodes": _bounded_integer(value.get("external_or_unresolved_nodes"), 500_000),
        "snapshotWarningCount": _bounded_integer(value.get("snapshot_warning_count")),
        "unresolvedCallCountKnown": known,
        "interpretation": "Missing results do not prove absence; evidence coverage is not accuracy.",
    }
    if known:
        result["unresolvedCallCount"] = _bounded_integer(unresolved)
    return result


def _project_search(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    matches, truncated_by_boundary = _project_nodes(raw.get("matches"), MAX_SEARCH_RESULTS)
    match_count = _bounded_integer(raw.get("match_count"), 500_000)
    projected = {
        "status": "ok",
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "snapshotId": _required_text(raw, "snapshotId", 100),
        "freshness": "snapshot",
        "evidenceType": _bounded_text(raw.get("evidenceType"), 50) or "observed",
        "term": _required_text(raw, "term", 300),
        "matchCount": match_count,
        "returned": len(matches),
        "matches": matches,
        "truncated": truncated_by_boundary or bool(raw.get("truncated")) or match_count > _bounded_integer(raw.get("offset"), 500_000) + len(matches),
        "offset": _bounded_integer(raw.get("offset"), 500_000),
        "scope": _project_scope(raw.get("scope")),
        "quality": _project_quality(raw.get("quality")),
    }
    if isinstance(raw.get("next_offset"), int) and not isinstance(raw["next_offset"], bool):
        projected["nextOffset"] = _bounded_integer(raw["next_offset"], 500_000)
    return projected


def _project_path(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 5:
        return []
    path = []
    for step in value:
        edges, _ = _project_edges([step])
        if not edges or not isinstance(step, dict) or step.get("direction") not in {"incoming", "outgoing"}:
            return []
        path.append({**edges[0], "direction": step["direction"], "evidence": _project_evidence(step.get("evidence"))})
    return path


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
                via = _bounded_text(item.get("via"), 1_000)
                if via is not None:
                    projected_impact[-1]["via"] = via
                if "path" in item:
                    projected_impact[-1]["path"] = _project_path(item["path"])
    projected: dict[str, Any] = {
        "status": status,
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "snapshotId": _required_text(raw, "snapshotId", 100),
        "freshness": "snapshot",
        "evidenceType": _bounded_text(raw.get("evidenceType"), 50) or "observed",
        "symbol": _required_text(raw, "symbol", 500),
        "impact": projected_impact,
        "scope": _project_scope(raw.get("scope")),
        "quality": _project_quality(raw.get("quality")),
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
    if raw.get("direction") in {"incoming", "outgoing", "both"}:
        projected["direction"] = raw["direction"]
    relations = raw.get("relationships")
    if isinstance(relations, list):
        projected["relationships"] = sorted({item for item in relations[:32] if isinstance(item, str) and item in core.EDGE_EVIDENCE_DEFAULTS})
    if "excluded_edges" in raw:
        projected["excludedEdges"] = _bounded_integer(raw["excluded_edges"], 1_000_000)
        projected["excludedEdgesScope"] = "encountered_during_traversal"
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
        for name in ("nodesAdded", "nodesRemoved", "nodesModified", "edgesAdded", "edgesRemoved", "edgesModified")
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
    nodes_modified, nodes_modified_truncated = _project_nodes(raw.get("nodesModified"), MAX_CHANGE_RESULTS)
    edges_modified = []
    raw_modified = raw.get("edgesModified", [])
    if isinstance(raw_modified, list):
        for item in raw_modified[:MAX_CHANGE_RESULTS]:
            edges, _ = _project_edges([item])
            if edges:
                edges_modified.append({**edges[0], "evidence": _project_evidence(item.get("evidence")),
                                       "previousEvidence": _project_evidence(item.get("previousEvidence"))})
    change_basis = raw.get("changeBasis")
    if change_basis not in {
        "source_change",
        "source_scope_change",
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
        **_project_source_roots(raw, ("beforeSourceRoots", "afterSourceRoots")),
        **({"sourceScopeChanged": raw["sourceScopeChanged"]} if type(raw.get("sourceScopeChanged")) is bool else {}),
        "quality": _project_quality(raw.get("quality")),
        "counts": _project_diff_counts(raw.get("counts")),
        "nodesAdded": nodes_added,
        "nodesRemoved": nodes_removed,
        "edgesAdded": edges_added,
        "edgesRemoved": edges_removed,
        "nodesModified": nodes_modified,
        "edgesModified": edges_modified,
        "truncated": bool(raw.get("truncated"))
        or nodes_added_truncated
        or nodes_removed_truncated
        or edges_added_truncated
        or edges_removed_truncated
        or nodes_modified_truncated
        or (isinstance(raw_modified, list) and len(raw_modified) > MAX_CHANGE_RESULTS),
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


def _project_large_common(raw: dict[str, Any]) -> dict[str, Any]:
    limitations = raw.get("limitations")
    return {
        "workspaceId": _required_text(raw, "workspaceId", 100),
        "catalogSnapshotId": _required_text(raw, "catalogSnapshotId", 100),
        "freshness": "pinned_snapshot",
        "freshnessCaveat": _required_text(raw, "freshnessCaveat", 300),
        "crossModuleResolution": "unsupported",
        "limitations": [text for item in (limitations if isinstance(limitations, list) else [])[:16]
                        if (text := _bounded_text(item, 300)) is not None],
        "targetCodeExecuted": False,
        "networkAccess": False,
    }


def _project_large_module(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    root = _portable_path(raw.get("root"))
    module_id = _bounded_text(raw.get("moduleId"), 100)
    snapshot_id = _bounded_text(raw.get("snapshotId"), 100)
    if root is None or module_id is None or snapshot_id is None:
        return None
    result: dict[str, Any] = {"moduleId": module_id, "root": root, "snapshotId": snapshot_id}
    for name, maximum in (("workspaceId", 100), ("analyzerVersion", 50), ("companionVersion", 50)):
        if (value := _bounded_text(raw.get(name), maximum)) is not None:
            result[name] = value
    for name, maximum in (("sourceFileCount", 25_000), ("supportedSourceBytes", MAX_COUNT),
                          ("matchOccurrences", 500_000)):
        if name in raw:
            result[name] = _bounded_integer(raw[name], maximum)
    if "counts" in raw:
        result["counts"] = _project_counts(raw["counts"])
    if "scope" in raw:
        result["scope"] = _project_scope(raw["scope"])
    if raw.get("versionFreshness") in {"current", "stale"}:
        result["versionFreshness"] = raw["versionFreshness"]
    return result


def _project_large_modules(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    raw_modules = raw.get("modules")
    modules = [item for value in (raw_modules if isinstance(raw_modules, list) else [])[:MAX_LARGE_MODULES]
               if (item := _project_large_module(value)) is not None]
    projected = {
        "status": "ok", **_project_large_common(raw),
        "term": _bounded_text(raw.get("term"), 300) or "",
        "moduleCount": _bounded_integer(raw.get("moduleCount"), MAX_LARGE_MODULES),
        "matchedModuleCount": _bounded_integer(raw.get("matchedModuleCount"), MAX_LARGE_MODULES),
        "offset": _bounded_integer(raw.get("offset"), MAX_LARGE_MODULES),
        "returned": len(modules), "modules": modules, "metadataOnly": True,
        "truncated": bool(raw.get("truncated")) or
                     (isinstance(raw_modules, list) and len(raw_modules) != len(modules)),
    }
    if type(raw.get("nextOffset")) is int:
        projected["nextOffset"] = _bounded_integer(raw["nextOffset"], MAX_LARGE_MODULES)
    return projected


def _project_large_search(raw: dict[str, Any]) -> dict[str, Any]:
    _expect_ok(raw)
    raw_matches = raw.get("matches")
    matches = []
    for value in (raw_matches if isinstance(raw_matches, list) else [])[:MAX_SEARCH_RESULTS]:
        if not isinstance(value, dict):
            continue
        root, node = _portable_path(value.get("moduleRoot")), _project_node(value.get("node"))
        if root is None or node is None:
            continue
        matches.append({"moduleRoot": root, "node": node,
                        **{name: _required_text(value, name, 100)
                           for name in ("moduleId", "moduleWorkspaceId", "moduleSnapshotId")}})
    roots = raw.get("selectedModuleRoots")
    if (not isinstance(roots, list) or not 1 <= len(roots) <= MAX_LARGE_MODULES
            or any(_portable_path(root) is None for root in roots)):
        raise companion.CompanionError("Malformed selected module scope.")
    raw_modules = raw.get("modules")
    modules = [item for value in (raw_modules if isinstance(raw_modules, list) else [])[:MAX_LARGE_MODULES]
               if (item := _project_large_module(value)) is not None]
    projected = {
        "status": "ok", **_project_large_common(raw),
        "term": _required_text(raw, "term", 300), "matches": matches, "modules": modules,
        "returned": len(matches), "selectedModuleRoots": list(roots),
        "moduleCount": _bounded_integer(raw.get("moduleCount"), MAX_LARGE_MODULES),
        "moduleMatchOccurrences": _bounded_integer(raw.get("moduleMatchOccurrences"), MAX_LARGE_OCCURRENCES),
        "offset": _bounded_integer(raw.get("offset"), MAX_LARGE_OCCURRENCES),
        "order": "configured_module_order_then_module_search_rank",
        "truncated": bool(raw.get("truncated")) or
                     (isinstance(raw_matches, list) and len(raw_matches) != len(matches)),
    }
    if type(raw.get("nextOffset")) is int:
        projected["nextOffset"] = _bounded_integer(raw["nextOffset"], MAX_LARGE_OCCURRENCES)
    return projected


def _project_large_neighbors(raw: dict[str, Any]) -> dict[str, Any]:
    projected = _project_neighbors(raw)
    projected.pop("snapshotId", None)
    projected.update(_project_large_common(raw))
    root = _portable_path(raw.get("moduleRoot"))
    if root is None:
        raise companion.CompanionError("Malformed module scope.")
    projected["moduleRoot"] = root
    for name in ("moduleId", "moduleWorkspaceId", "moduleSnapshotId"):
        projected[name] = _required_text(raw, name, 100)
    return projected


def _bundle_result_count(item: dict[str, Any]) -> int:
    if item.get("status") != "ok":
        return 0
    if item["operation"] == "search":
        return len(item["search"]["matches"])
    result = item["neighbors"]
    return (len(result.get("impact", [])) + len(result.get("candidates", []))
            + (1 if "root" in result else 0))


def _finish_bundle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["succeeded"] = sum(item["status"] == "ok" for item in payload["items"])
    payload["failed"] = len(payload["items"]) - payload["succeeded"]
    payload["status"] = "partial" if payload["failed"] else "ok"
    payload["returnedResults"] = sum(_bundle_result_count(item) for item in payload["items"])
    # The decimal byte-count field can change its own serialized width.
    for _ in range(5):
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if payload["payloadBytes"] == size:
            break
        payload["payloadBytes"] = size
    return payload


def _project_bundle(raw: dict[str, Any]) -> dict[str, Any]:
    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= MAX_BUNDLE_REQUESTS:
        raise companion.CompanionError("Malformed evidence bundle.")
    pending = []
    for item in raw_items:
        if not isinstance(item, dict) or item.get("operation") not in {"search", "neighbors"}:
            raise companion.CompanionError("Malformed evidence bundle item.")
        pending.append({"id": _required_text(item, "id", 40), "operation": item["operation"],
                        "status": "error", "message": "Item not evaluated."})
    payload = {
        "status": "partial", "workspaceId": _required_text(raw, "workspaceId", 100),
        "snapshotId": _required_text(raw, "snapshotId", 100), "freshness": "snapshot",
        "requestCount": len(pending), "succeeded": 0, "failed": len(pending), "returnedResults": 0,
        "maxResults": MAX_BUNDLE_RESULTS, "maxPayloadBytes": MAX_BUNDLE_PAYLOAD_BYTES,
        "payloadBytes": 0, "items": pending,
    }
    for position, item in enumerate(raw_items):
        candidate = {"id": pending[position]["id"], "operation": item["operation"], "status": "error"}
        try:
            if item.get("status") == "error":
                candidate["message"] = _bounded_text(item.get("message"), MAX_ERROR_TEXT) or "Local ontology query failed."
            else:
                operation = item["operation"]
                result = _project_result("ontology_" + operation, item.get("result"))
                if result.get("snapshotId") != payload["snapshotId"] or result.get("workspaceId") != payload["workspaceId"]:
                    raise companion.CompanionError("Bundle item snapshot binding does not match.")
                candidate.update({"status": "ok", operation: result})
                if sum(_bundle_result_count(value) for value in pending) + _bundle_result_count(candidate) > MAX_BUNDLE_RESULTS:
                    candidate = {"id": candidate["id"], "operation": operation, "status": "error",
                                 "message": "Item exceeds the remaining bundle result budget; request a smaller limit."}
        except (companion.CompanionError, core.OntologyError) as exc:
            candidate["status"] = "error"
            candidate.pop("search", None)
            candidate.pop("neighbors", None)
            candidate["message"] = _public_error(exc)
        pending[position] = candidate
        _finish_bundle_payload(payload)
        if payload["payloadBytes"] > MAX_BUNDLE_PAYLOAD_BYTES:
            pending[position] = {"id": candidate["id"], "operation": candidate["operation"], "status": "error",
                                 "message": "Item exceeds the bundle byte budget; request a smaller limit or depth."}
            _finish_bundle_payload(payload)
    return _finish_bundle_payload(payload)


PROJECTORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "ontology_list_workspaces": _project_list,
    "ontology_status": _project_status,
    "ontology_search": _project_search,
    "ontology_neighbors": _project_neighbors,
    "ontology_history": _project_history,
    "ontology_changes": _project_changes,
    "ontology_lineage": _project_lineage,
    "ontology_large_modules": _project_large_modules,
    "ontology_large_search": _project_large_search,
    "ontology_large_neighbors": _project_large_neighbors,
    "ontology_evidence_bundle": _project_bundle,
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


def _relationship_arguments(arguments: dict[str, Any]) -> list[str] | None:
    relationships = arguments.get("relationships")
    if relationships is not None and (
        not isinstance(relationships, list) or not 1 <= len(relationships) <= 32
        or any(not isinstance(item, str) or item not in core.EDGE_EVIDENCE_DEFAULTS for item in relationships)
    ):
        raise companion.CompanionError("Unsupported relationship filter.")
    return relationships


def _dispatch_large(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    workspace_id = _string(arguments, "workspace_id", maximum=100)
    workspace = str(companion.resolve_registered_large_workspace(workspace_id))
    large = companion._large_project()
    catalog = (_string(arguments, "catalog_snapshot_id", maximum=100)
               if "catalog_snapshot_id" in arguments else None)
    if name == "ontology_large_modules":
        term = arguments.get("term", "")
        if not isinstance(term, str) or len(term) > 300:
            raise companion.CompanionError("term must contain at most 300 characters.")
        return large.modules(workspace, term, _integer(arguments, "offset", 0, 0, MAX_LARGE_MODULES),
                             _integer(arguments, "limit", 20, 1, MAX_SEARCH_RESULTS), catalog_snapshot=catalog)
    if name == "ontology_large_search":
        roots = arguments.get("module_roots")
        if (not isinstance(roots, list) or not 1 <= len(roots) <= MAX_LARGE_MODULES
                or any(_portable_path(root) is None for root in roots)):
            raise companion.CompanionError("Select exact configured repository-relative module roots.")
        return large.query(
            workspace, _string(arguments, "term", maximum=300),
            _integer(arguments, "limit", 20, 1, MAX_SEARCH_RESULTS), roots,
            _integer(arguments, "offset", 0, 0, MAX_LARGE_OCCURRENCES), catalog_snapshot=catalog,
            **{field: _string(arguments, field, maximum=1_000 if field == "path_prefix" else 100)
               for field in ("language", "node_type", "path_prefix") if field in arguments},
        )
    return large.impact(
        workspace, _string(arguments, "module_root", maximum=1_000),
        _string(arguments, "symbol", maximum=500), _integer(arguments, "depth", 2, 1, 5),
        _integer(arguments, "limit", 100, 1, MAX_IMPACT_RESULTS),
        _string(arguments, "direction", default="both", maximum=20),
        catalog_snapshot=catalog, relationships=_relationship_arguments(arguments),
    )


def _dispatch_bundle(arguments: dict[str, Any]) -> dict[str, Any]:
    requests = arguments.get("requests")
    if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_BUNDLE_REQUESTS:
        raise companion.CompanionError("A bundle requires from 1 to 8 requests.")
    seen = set()
    for item in requests:
        if not isinstance(item, dict) or item.get("operation") not in {"search", "neighbors"}:
            raise companion.CompanionError("Each bundle request requires a supported operation.")
        identity = item.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,39}", identity):
            raise companion.CompanionError("Bundle request ids must contain from 1 to 40 portable characters.")
        if identity in seen:
            raise companion.CompanionError("Bundle request ids must be unique.")
        seen.add(identity)
    workspace = _workspace_path(arguments)
    workspace_path, _config = companion._workspace(workspace)
    snapshot = companion._resolve_snapshot_alias(
        workspace_path, _string(arguments, "snapshot_id", default="current", maximum=100)
    )
    companion._snapshot_path(workspace_path, snapshot)
    items = []
    for request in requests:
        operation = request["operation"]
        item = {"id": request["id"], "operation": operation, "status": "ok"}
        try:
            nested = {key: value for key, value in request.items() if key not in {"id", "operation"}}
            # The envelope alone selects workspace/snapshot; nested overrides are forbidden.
            if {"workspace_id", "snapshot_id"} & set(nested):
                raise companion.CompanionError("A bundle item cannot override its workspace or snapshot.")
            _integer(nested, "limit", 20 if operation == "search" else 200, 1, MAX_BUNDLE_RESULTS)
            item["result"] = _dispatch("ontology_" + operation,
                                       {**nested, "workspace_id": arguments["workspace_id"], "snapshot_id": snapshot})
        except (companion.CompanionError, core.OntologyError) as exc:
            item["status"] = "error"
            item["message"] = _public_error(exc)
        items.append(item)
    return {"workspaceId": _config["workspaceId"], "snapshotId": snapshot, "items": items}


def _dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _validate_arguments(name, arguments)
    if name == "ontology_list_workspaces":
        return companion.list_workspaces()
    if name in {"ontology_large_modules", "ontology_large_search", "ontology_large_neighbors"}:
        return _dispatch_large(name, arguments)
    if name == "ontology_evidence_bundle":
        return _dispatch_bundle(arguments)
    workspace = _workspace_path(arguments)
    if name == "ontology_status":
        return companion.status(workspace, check_freshness=True)
    if name == "ontology_search":
        result = companion.query(
            workspace,
            _string(arguments, "term", maximum=300),
            _integer(arguments, "limit", 20, 1, 200),
            snapshot=_string(arguments, "snapshot_id", default="current", maximum=100),
            offset=_integer(arguments, "offset", 0, 0, 500_000),
            **{name: _string(arguments, name, maximum=1000 if name == "path_prefix" else 100)
               for name in ("language", "node_type", "path_prefix") if name in arguments},
        )
        if isinstance(result, dict) and "status" not in result:
            return {"status": "ok", **result}
        return result
    if name == "ontology_neighbors":
        relationships = _relationship_arguments(arguments)
        return companion.impact(
            workspace,
            _string(arguments, "symbol", maximum=500),
            _integer(arguments, "depth", 2, 1, 5),
            snapshot=_string(arguments, "snapshot_id", default="current", maximum=100),
            direction=_string(arguments, "direction", default="both", maximum=20),
            relationships=relationships,
            limit=_integer(arguments, "limit", 200, 1, MAX_IMPACT_RESULTS),
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
