from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "mcp" / "server.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample-app"
SPEC = importlib.util.spec_from_file_location("code_ontology_mcp_contract", SERVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load MCP server module.")
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


def node(*, path: str = "pkg/service.py") -> dict:
    return {
        "id": "python:function:pkg.service.run",
        "type": "Function",
        "name": "run",
        "language": "Python",
        "path": path,
        "qualified_name": "pkg.service.run",
        "metadata": {
            "parameter_count": 2,
            "parameter_types": ["str", "int"],
            "semantic_groups": ["PipelineStage"],
            "return_type": "Result",
            "accessor": "policyDecimal",
            "control_kind": "guard",
            "ordinal": 1,
            "private_metadata": "/Users/alice/private.py",
        },
        "unknown_node_key": "private-value",
    }


def counts() -> dict:
    return {
        "source_files": {"Java": 2, "Python": 3, "private": 999_999_999_999},
        "nodes": 8,
        "edges": 9,
        "warnings": 1,
        "skipped": {"hidden": 2},
        "private_count": 123,
    }


class McpContractTests(unittest.TestCase):
    maxDiff = None

    def call(self, name: str, arguments: dict) -> dict:
        response = server._handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        self.assertIsNotNone(response)
        return response["result"]

    def assert_matches_contract(self, value, schema) -> None:
        expected_type = schema.get("type")
        if expected_type == "object":
            self.assertIsInstance(value, dict)
            properties = schema.get("properties", {})
            self.assertLessEqual(set(value), set(properties))
            self.assertTrue(set(schema.get("required", [])) <= set(value))
            for key, item in value.items():
                self.assert_matches_contract(item, properties[key])
            variants = schema.get("oneOf")
            if variants:
                matching = [
                    variant
                    for variant in variants
                    if variant.get("properties", {}).get("status", {}).get("const")
                    == value.get("status")
                ]
                self.assertEqual(len(matching), 1)
                self.assertTrue(set(matching[0].get("required", [])) <= set(value))
        elif expected_type == "array":
            self.assertIsInstance(value, list)
            self.assertLessEqual(len(value), schema["maxItems"])
            for item in value:
                self.assert_matches_contract(item, schema["items"])
        elif expected_type == "string":
            self.assertIsInstance(value, str)
            self.assertLessEqual(len(value), schema["maxLength"])
            if "enum" in schema:
                self.assertIn(value, schema["enum"])
            if "const" in schema:
                self.assertEqual(value, schema["const"])
        elif expected_type == "integer":
            self.assertIsInstance(value, int)
            self.assertNotIsInstance(value, bool)
            self.assertGreaterEqual(value, schema.get("minimum", value))
            self.assertLessEqual(value, schema.get("maximum", value))
        elif expected_type == "boolean":
            self.assertIsInstance(value, bool)
        else:
            self.fail(f"Unsupported test schema: {schema}")

    def assert_safe_result(self, name: str, result: dict, *, is_error: bool) -> dict:
        self.assertEqual(result["isError"], is_error)
        structured = result["structuredContent"]
        self.assertEqual(json.loads(result["content"][0]["text"]), structured)
        self.assert_matches_contract(structured, server.OUTPUT_SCHEMAS[name])
        serialized = json.dumps(structured, ensure_ascii=False)
        for forbidden in (
            "/Users/alice",
            "/opt/private",
            "C:\\\\Users\\\\alice",
            "private-value",
            "private_metadata",
            "sourceFingerprint",
            "repositoryRevision",
            "registryContainsAbsolutePaths",
            "portableRdf",
            "visualization",
            '"workspace"',
        ):
            self.assertNotIn(forbidden, serialized)
        self.assert_no_unsafe_strings(structured)
        return structured

    def assert_no_unsafe_strings(self, value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                self.assertFalse(server._unsafe_output_text(key))
                self.assert_no_unsafe_strings(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_no_unsafe_strings(item)
        elif isinstance(value, str):
            self.assertFalse(server._unsafe_output_text(value), value)

    def test_tool_list_has_seven_strict_bounded_output_contracts(self) -> None:
        response = server._handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        tools = response["result"]["tools"]
        self.assertEqual(server.SERVER_VERSION, "0.3.1")
        self.assertEqual(len(tools), 7)
        self.assertEqual({tool["name"] for tool in tools}, set(server.OUTPUT_SCHEMAS))
        for tool in tools:
            with self.subTest(tool=tool["name"]):
                schema = tool["outputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                self.assertIn("status", schema["required"])
                self.assertIn("message", schema["properties"])
                self.assertTrue(schema["oneOf"])
                self.assertTrue(tool["annotations"]["readOnlyHint"])
                self.assertFalse(tool["annotations"]["openWorldHint"])

    def test_initialize_negotiates_only_allowlisted_protocol_versions(self) -> None:
        supported = server.DEFAULT_PROTOCOL_VERSION
        self.assertEqual(server.SUPPORTED_PROTOCOL_VERSIONS, frozenset({supported}))
        cases = (
            (supported, supported),
            ("2099-01-01,/opt/private/protocol", supported),
            ("2025-06-18\x00private", supported),
            (123, supported),
            (None, supported),
        )
        for requested, expected in cases:
            with self.subTest(requested=requested):
                params = {"capabilities": {}}
                if requested is not None:
                    params["protocolVersion"] = requested
                response = server._handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": params,
                    }
                )
                result = response["result"]
                self.assertEqual(result["protocolVersion"], expected)
                self.assertIn(result["protocolVersion"], server.SUPPORTED_PROTOCOL_VERSIONS)
                if isinstance(requested, str) and requested != supported:
                    self.assertNotIn(requested, json.dumps(result))

    def test_all_tools_project_success_results_through_allowlists_and_bounds(self) -> None:
        workspaces = [
            {
                "id": f"ws-{index}",
                "label": f"Workspace {index}",
                "workspace": "/Users/alice/private",
                "unknown": "private-value",
            }
            for index in range(server.MAX_WORKSPACES + 1)
        ]
        impact_item = {
            "depth": 1,
            "relationship": "CALLS",
            "direction": "outgoing",
            "node": node(path="/Users/alice/private.py"),
            "unknown": "private-value",
        }
        snapshot = {
            "snapshotId": "snap-1",
            "createdAt": "2026-08-01T00:00:00Z",
            "repositoryRevision": "private-revision",
            "trigger": "manual",
            "counts": counts(),
            "unknown": "private-value",
        }
        edge = {
            "source": "python:function:a",
            "type": "CALLS",
            "target": "python:function:b",
            "unknown": "private-value",
        }
        event = {
            "eventId": "event-1",
            "kind": "snapshot",
            "evidenceType": "observed",
            "summary": "Snapshot promoted.",
            "subject": "pkg.service.run",
            "snapshotId": "snap-1",
            "previousSnapshotId": "snap-0",
            "recordedAt": "2026-08-01T00:00:00Z",
            "recordedBy": "/Users/alice/private",
            "unknown": "private-value",
        }
        payloads = {
            "ontology_list_workspaces": {
                "status": "ok",
                "workspaces": workspaces,
                "staleRegistrations": workspaces,
                "registryContainsAbsolutePaths": True,
                "unknown": "private-value",
            },
            "ontology_status": {
                "status": "ok",
                "workspaceId": "ws-1",
                "repositoryLabel": "Fixture",
                "snapshotId": "snap-1",
                "previousSnapshotId": "snap-0",
                "generatedAt": "2026-08-01T00:00:00Z",
                "freshness": "current",
                "snapshotAnalyzerVersion": "0.3.1",
                "currentAnalyzerVersion": "0.3.1",
                "snapshotCompanionVersion": "0.3.1",
                "currentCompanionVersion": "0.3.1",
                "evidenceType": "observed",
                "counts": counts(),
                "pipelineStatus": "healthy",
                "workspace": "/Users/alice/private",
                "sourceFingerprint": "private-value",
                "unknown": "private-value",
            },
            "ontology_search": {
                "term": "run",
                "match_count": 999,
                "returned": server.MAX_SEARCH_RESULTS + 1,
                "matches": [node()] * (server.MAX_SEARCH_RESULTS + 1),
                "workspaceId": "ws-1",
                "snapshotId": "snap-1",
                "freshness": "snapshot",
                "evidenceType": "observed",
                "unknown": "private-value",
            },
            "ontology_neighbors": {
                "symbol": "pkg.service.run",
                "status": "ok",
                "root": node(),
                "depth": 2,
                "impact_count": server.MAX_IMPACT_RESULTS + 1,
                "truncated": False,
                "impact": [impact_item] * (server.MAX_IMPACT_RESULTS + 1),
                "interpretation": "Static relationship neighborhood.",
                "workspaceId": "ws-1",
                "snapshotId": "snap-1",
                "freshness": "snapshot",
                "evidenceType": "observed",
                "unknown": "private-value",
            },
            "ontology_history": {
                "status": "ok",
                "workspaceId": "ws-1",
                "snapshots": [snapshot] * (server.MAX_HISTORY_RESULTS + 1),
                "truncated": False,
                "unknown": "private-value",
            },
            "ontology_changes": {
                "status": "ok",
                "workspaceId": "ws-1",
                "beforeSnapshotId": "snap-0",
                "afterSnapshotId": "snap-1",
                "counts": {
                    "nodesAdded": 1,
                    "nodesRemoved": 2,
                    "edgesAdded": 3,
                    "edgesRemoved": 4,
                    "unknown": 5,
                },
                "nodesAdded": [node()] * (server.MAX_CHANGE_RESULTS + 1),
                "nodesRemoved": [node()] * (server.MAX_CHANGE_RESULTS + 1),
                "edgesAdded": [edge] * (server.MAX_CHANGE_RESULTS + 1),
                "edgesRemoved": [edge] * (server.MAX_CHANGE_RESULTS + 1),
                "truncated": False,
                "interpretation": "Structural static diff.",
                "unknown": "private-value",
            },
            "ontology_lineage": {
                "status": "ok",
                "workspaceId": "ws-1",
                "events": [event] * (server.MAX_LINEAGE_RESULTS + 1),
                "truncated": False,
                "lineage": "/Users/alice/private.ttl",
                "unknown": "private-value",
            },
        }
        arguments = {
            "ontology_list_workspaces": {},
            "ontology_status": {"workspace_id": "ws-1"},
            "ontology_search": {"workspace_id": "ws-1", "term": "run", "limit": 200},
            "ontology_neighbors": {"workspace_id": "ws-1", "symbol": "run", "depth": 2},
            "ontology_history": {"workspace_id": "ws-1", "limit": 200},
            "ontology_changes": {
                "workspace_id": "ws-1",
                "before": "previous",
                "after": "current",
                "limit": 500,
            },
            "ontology_lineage": {"workspace_id": "ws-1", "limit": 500},
        }
        companion_functions = {
            "ontology_list_workspaces": "list_workspaces",
            "ontology_status": "status",
            "ontology_search": "query",
            "ontology_neighbors": "impact",
            "ontology_history": "history",
            "ontology_changes": "diff",
            "ontology_lineage": "lineage",
        }
        with mock.patch.object(
            server.companion,
            "resolve_registered_workspace",
            return_value=Path("/safe-workspace"),
        ):
            for name, payload in payloads.items():
                with self.subTest(tool=name), mock.patch.object(
                    server.companion,
                    companion_functions[name],
                    return_value=payload,
                ):
                    result = self.call(name, arguments[name])
                    structured = self.assert_safe_result(name, result, is_error=False)
                    if name != "ontology_status":
                        self.assertNotIn("unknown", structured)
                    if name in {
                        "ontology_list_workspaces",
                        "ontology_search",
                        "ontology_neighbors",
                        "ontology_history",
                        "ontology_changes",
                        "ontology_lineage",
                    }:
                        self.assertTrue(structured["truncated"])

    def test_neighbors_preserves_bounded_not_found_and_ambiguous_results(self) -> None:
        for status in ("not_found", "ambiguous"):
            raw = {
                "status": status,
                "symbol": "run",
                "candidates": [node()] * 30,
                "impact": [],
                "workspaceId": "ws-1",
                "snapshotId": "snap-1",
                "freshness": "snapshot",
                "evidenceType": "observed",
            }
            with self.subTest(status=status), mock.patch.object(
                server.companion,
                "resolve_registered_workspace",
                return_value=Path("/safe-workspace"),
            ), mock.patch.object(server.companion, "impact", return_value=raw):
                result = self.call(
                    "ontology_neighbors", {"workspace_id": "ws-1", "symbol": "run"}
                )
                structured = self.assert_safe_result(
                    "ontology_neighbors", result, is_error=False
                )
                self.assertEqual(structured["status"], status)
                self.assertLessEqual(len(structured["candidates"]), 20)

    def test_text_projection_rejects_control_characters_and_absolute_paths(self) -> None:
        safe_node_with_private_qualified_name = node()
        safe_node_with_private_qualified_name["qualified_name"] = (
            "pkg.Safe,/opt/private.Symbol"
        )
        safe_node_with_control_qualified_name = node()
        safe_node_with_control_qualified_name["id"] = "python:function:pkg.safe"
        safe_node_with_control_qualified_name["qualified_name"] = "pkg.safe\u202esecret"
        posix_name = node()
        posix_name["id"] = "python:function:posix"
        posix_name["name"] = "Method,/Users/alice/private.py"
        windows_name = node()
        windows_name["id"] = "python:function:windows"
        windows_name["name"] = r"Method;C:\Users\alice\private.py"
        safe_event = {
            "eventId": "event-safe",
            "kind": "snapshot",
            "evidenceType": "observed",
            "summary": "Snapshot promoted.",
            "subject": r"source=C:\Users\alice\private.py",
        }
        payloads = {
            "ontology_list_workspaces": {
                "status": "ok",
                "workspaces": [
                    {"id": "safe", "label": "Safe workspace"},
                    {"id": "posix", "label": "Workspace,/Users/alice/private"},
                    {"id": "windows", "label": r"Workspace;C:\Users\alice\private"},
                    {"id": "unc", "label": r"Workspace,\\server\share\private"},
                    {"id": "control", "label": "private\x00label"},
                ],
                "staleRegistrations": [],
            },
            "ontology_status": {
                "status": "ok",
                "workspaceId": "ws-1",
                "repositoryLabel": "Fixture,/opt/private/repository",
                "snapshotId": "snap-1",
                "freshness": "current",
                "counts": counts(),
                "pipelineStatus": "healthy",
            },
            "ontology_search": {
                "status": "ok",
                "workspaceId": "ws-1",
                "snapshotId": "snap-1",
                "term": "safe",
                "match_count": 4,
                "matches": [
                    safe_node_with_private_qualified_name,
                    safe_node_with_control_qualified_name,
                    posix_name,
                    windows_name,
                ],
                "evidenceType": "observed",
            },
            "ontology_lineage": {
                "status": "ok",
                "workspaceId": "ws-1",
                "events": [
                    {
                        "eventId": "event-posix",
                        "kind": "snapshot",
                        "evidenceType": "observed",
                        "summary": "Read,/Users/alice/private.py",
                    },
                    {
                        "eventId": "event-control",
                        "kind": "snapshot",
                        "evidenceType": "observed",
                        "summary": "private\nsummary",
                    },
                    safe_event,
                ],
            },
        }
        for name, payload in payloads.items():
            with self.subTest(tool=name), mock.patch.object(
                server, "_dispatch", return_value=payload
            ):
                result = self.call(name, {})
                structured = self.assert_safe_result(
                    name,
                    result,
                    is_error=name == "ontology_status",
                )
                if name == "ontology_list_workspaces":
                    self.assertEqual(structured["workspaces"], [{"id": "safe", "label": "Safe workspace"}])
                elif name == "ontology_status":
                    self.assertEqual(structured["status"], "error")
                elif name == "ontology_search":
                    self.assertEqual(len(structured["matches"]), 2)
                    self.assertTrue(
                        all("qualifiedName" not in item for item in structured["matches"])
                    )
                elif name == "ontology_lineage":
                    self.assertEqual(len(structured["events"]), 1)
                    self.assertNotIn("subject", structured["events"][0])

        malformed_search = {
            "workspaceId": "ws-1",
            "snapshotId": "snap-1",
            "term": "safe",
            "match_count": 0,
            "matches": [],
        }
        with self.assertRaises(server.companion.CompanionError):
            server._project_search(malformed_search)

        for unsafe in (
            "label,/opt/private/file",
            "label;/Users/alice/private/file",
            r"label,C:\Users\alice\private.txt",
            r"label,\\server\share\private.txt",
            r"label,\Users\alice\private.txt",
            r"label,\secret.txt",
            r"label;\Windows",
            "label,file:///Users/alice/private.txt",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertTrue(server._unsafe_output_text(unsafe))
        for safe in (
            "pkg.service.OrderService",
            "src/main/java/OrderService.java",
            "https://example.com/reference",
        ):
            with self.subTest(safe=safe):
                self.assertFalse(server._unsafe_output_text(safe))

    def test_all_seven_tools_satisfy_contract_against_real_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repository"
            workspace = base / "workspace"
            data_home = base / "data"
            shutil.copytree(FIXTURE, repository)
            with mock.patch.dict(
                os.environ,
                {"CODE_ONTOLOGY_HOME": str(data_home)},
                clear=False,
            ):
                initialized = server.companion.initialize(
                    str(repository),
                    str(workspace),
                    authorized=True,
                    label="fixture",
                )
                source = repository / "python_pipeline" / "orders.py"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + "\n\ndef contract_probe():\n    return None\n",
                    encoding="utf-8",
                )
                server.companion.sync(str(workspace), trigger="contract-test")
                workspace_id = initialized["workspaceId"]
                calls = {
                    "ontology_list_workspaces": {},
                    "ontology_status": {"workspace_id": workspace_id},
                    "ontology_search": {
                        "workspace_id": workspace_id,
                        "term": "OrderService",
                        "limit": 20,
                    },
                    "ontology_neighbors": {
                        "workspace_id": workspace_id,
                        "symbol": "OrderService",
                        "depth": 2,
                    },
                    "ontology_history": {"workspace_id": workspace_id, "limit": 20},
                    "ontology_changes": {
                        "workspace_id": workspace_id,
                        "before": "previous",
                        "after": "current",
                        "limit": 100,
                    },
                    "ontology_lineage": {"workspace_id": workspace_id, "limit": 50},
                }
                for name, arguments in calls.items():
                    with self.subTest(tool=name):
                        result = self.call(name, arguments)
                        self.assert_safe_result(name, result, is_error=False)

    def test_every_tool_rejects_its_invalid_input_with_schema_safe_error(self) -> None:
        invalid_calls = {
            "ontology_list_workspaces": {"unexpected": True},
            "ontology_status": {},
            "ontology_search": {"workspace_id": "ws-1", "term": ""},
            "ontology_neighbors": {
                "workspace_id": "ws-1",
                "symbol": "run",
                "depth": 0,
            },
            "ontology_history": {"workspace_id": "ws-1", "limit": True},
            "ontology_changes": {"workspace_id": "ws-1", "limit": 501},
            "ontology_lineage": {"workspace_id": "ws-1", "evidence_type": "secret"},
        }
        with mock.patch.object(
            server.companion,
            "resolve_registered_workspace",
            return_value=Path("/safe-workspace"),
        ):
            for name, arguments in invalid_calls.items():
                with self.subTest(tool=name):
                    result = self.call(name, arguments)
                    structured = self.assert_safe_result(name, result, is_error=True)
                    self.assertEqual(structured["status"], "error")
                    self.assertLessEqual(len(structured["message"]), server.MAX_ERROR_TEXT)

    def test_every_tool_redacts_private_backend_error_details(self) -> None:
        for name in server.OUTPUT_SCHEMAS:
            with self.subTest(tool=name), mock.patch.object(
                server,
                "_dispatch",
                side_effect=server.companion.CompanionError(
                    "Registry is unreadable: /Users/alice/private/registry.json"
                ),
            ):
                result = self.call(name, {})
                structured = self.assert_safe_result(name, result, is_error=True)
                self.assertEqual(
                    structured["message"],
                    "The local ontology request could not be completed.",
                )


if __name__ == "__main__":
    unittest.main()
