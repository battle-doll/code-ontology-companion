#!/usr/bin/env python3
"""Read-only stdio MCP server for registered Code Ontology workspaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = PLUGIN_ROOT / "skills" / "manage-code-ontology" / "scripts"
if not SCRIPT_DIR.is_dir():
    raise SystemExit("Bundled Companion scripts are missing.")
sys.path.insert(0, str(SCRIPT_DIR))

import code_ontology_core as core  # noqa: E402
import companion  # noqa: E402


SERVER_NAME = "code-ontology-companion"
SERVER_VERSION = "0.2.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
DROP_KEYS = {
    "workspace",
    "portableRdf",
    "visualization",
    "lineage",
    "fingerprint",
    "sourceFingerprint",
    "repositoryRevision",
    "registryContainsAbsolutePaths",
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
        "outputSchema": {"type": "object", "additionalProperties": True},
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


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if key not in DROP_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _workspace_path(arguments: dict[str, Any]) -> str:
    workspace_id = arguments.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise companion.CompanionError("workspace_id is required.")
    return str(companion.resolve_registered_workspace(workspace_id.strip()))


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


def _dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "ontology_list_workspaces":
        return companion.list_workspaces()
    workspace = _workspace_path(arguments)
    if name == "ontology_status":
        return companion.status(workspace, check_freshness=True)
    if name == "ontology_search":
        return companion.query(
            workspace,
            _string(arguments, "term", maximum=300),
            _integer(arguments, "limit", 20, 1, 200),
        )
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
        protocol = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
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
            result = _sanitize(_dispatch(name, arguments))
            return _response(
                message_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                        }
                    ],
                    "structuredContent": result,
                    "isError": False,
                },
            )
        except (companion.CompanionError, core.OntologyError) as exc:
            result = {"status": "error", "message": str(exc)}
            return _response(
                message_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                        }
                    ],
                    "structuredContent": result,
                    "isError": True,
                },
            )
    return _error(message_id, -32601, f"Method not found: {method}")


def main() -> int:
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
