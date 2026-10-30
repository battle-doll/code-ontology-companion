from __future__ import annotations
import importlib.util
import hashlib
import subprocess
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/manage-code-ontology/scripts"))
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as store
import companion
spec = importlib.util.spec_from_file_location("pipeline_mcp_contract", ROOT / "mcp/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


@unittest.skipIf(os.name == "nt", "Native Windows private ACL provisioning is a separate check")
class PipelineMcpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        (self.repo / "order.py").write_text("def order_discount(employee: bool, promotion: bool) -> int:\n    if employee:\n        return 20\n    if promotion:\n        return 10\n    return 0\n")
        self.workspace = self.base / "workspace"
        self.env = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.base / "registry"), acl.PRINCIPAL_ENV: "local-owner"})
        self.env.start()
        self.addCleanup(self.env.stop)
        result = store.initialize(self.repo, self.workspace)
        self.snapshot = result["snapshotId"]
        self.workspace_id = result["workspaceId"]
        acl.initialize_access(self.workspace)
        access.register(str(self.workspace))
        self.args = {"workspace_id": self.workspace_id, "snapshot_id": self.snapshot}

    def call(self, name, arguments=None):
        response = server._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": name, "arguments": arguments if arguments is not None else self.args}})
        return response["result"]

    def test_registered_source_free_policy_and_snapshot_identity(self):
        before = self.call("query_policy_rules")
        self.assertFalse(before["isError"], before)
        row = before["structuredContent"]["data"]["rules"][0]
        shutil.rmtree(self.repo)
        after = self.call("query_policy_rules")
        self.assertEqual(before, after)
        result = self.call("explain_policy_result", {**self.args, "rule_id": row["id"],
            "context": {"employee": True, "promotion": False}})
        self.assertFalse(result["isError"], result)
        self.assertEqual(result["structuredContent"]["data"]["value"]["value"], "20")
        self.assertEqual(result["structuredContent"]["snapshotId"], self.snapshot)
        comparison = self.call("compare_policy_cases", {**self.args, "rule_id": row["id"],
            "cases": [{"employee": a, "promotion": b} for a in (False, True) for b in (False, True)],
            "objective": "maximize_value"})
        self.assertFalse(comparison["isError"], comparison)
        self.assertFalse(comparison["structuredContent"]["data"]["optimality"]["organizationWide"])

    def test_limited_reader_cannot_self_assert_or_get_source_details(self):
        acl.update_access(self.workspace, "policy-reader", ["read_policy"], [self.snapshot])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "policy-reader"}):
            result = self.call("query_policy_rules")
            self.assertFalse(result["isError"], result)
            data = result["structuredContent"]["data"]
            self.assertTrue(data["evidenceDetailsWithheld"])
            self.assertNotIn("relativePath", json.dumps(data))
            self.assertNotIn("lineStart", json.dumps(data))
            self.assertTrue(data["rules"][0]["sourceAssertionIds"])
            self.assertTrue(self.call("ontology_pipeline_search")["isError"])
            self.assertTrue(self.call("query_policy_rules", {**self.args, "role": "local-owner"})["isError"])
            self.assertTrue(self.call("ontology_search", {"workspace_id": self.workspace_id, "term": "order"})["isError"])
        acl.update_access(self.workspace, "policy-reader", [], [self.snapshot])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "policy-reader"}):
            self.assertTrue(self.call("query_policy_rules")["isError"])
            self.assertEqual(self.call("ontology_list_workspaces", {})["structuredContent"]["workspaces"], [])

    def test_malformed_budget_and_arbitrary_paths_rejected_before_backend(self):
        for extra in ({"snapshot_id": "current"}, {"workspace_id": str(self.workspace)},
                      {"offset": -1}, {"limit": 0}, {"limit": True}, {"term": []}, {"kind": "secrets"},
                      {"snapshot_id": "../escaped"}):
            with self.subTest(extra=extra), mock.patch.object(store, "query", side_effect=AssertionError("must not query")):
                self.assertTrue(self.call("ontology_pipeline_search", {**self.args, **extra})["isError"])

    def test_no_grant_or_corrupted_snapshot_fails_without_source_fallback(self):
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "unknown"}), mock.patch.object(store, "query", side_effect=AssertionError("must not query")):
            self.assertTrue(self.call("ontology_pipeline_search")["isError"])
        path = self.workspace / "snapshots" / self.snapshot / "policy.json"
        path.write_text('{}')
        result = self.call("query_policy_rules")
        self.assertTrue(result["isError"])
        self.assertNotIn(str(self.workspace), json.dumps(result))

    def test_tool_catalog_readonly_boundaries_and_source_free_status(self):
        tools = {x["name"]: x for x in server.TOOLS}
        self.assertEqual(len(tools), 20)
        for name in access.PIPELINE_TOOLS:
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"])
            self.assertFalse(tools[name]["inputSchema"]["additionalProperties"])
        shutil.rmtree(self.repo)
        result = self.call("ontology_pipeline_status", {"workspace_id": self.workspace_id})
        self.assertFalse(result["isError"], result)
        self.assertEqual(result["structuredContent"]["data"]["sourceAccess"], "not_read")

    def test_deep_sealed_semantic_record_delivered_over_real_source_free_stdio(self):
        # A left-associative expression recreates the old single-record depth
        # failure without including any private project names or source data.
        (self.repo / "Threshold.java").write_text(
            "class Threshold { int measure(int a) { return " + " + ".join(["a"] * 32) + "; } }")
        generated = store.sync(str(self.workspace))
        snapshot_id = generated["snapshotId"]
        data = store.query(str(self.workspace), snapshot_id=snapshot_id, kind="semantic_fragment", limit=100)
        original = next(row for row in data["records"] if row.get("expression") is not None)
        with self.assertRaisesRegex(companion.CompanionError, "structural budget"):
            access.bounded_json({"status": "ok", "snapshotId": snapshot_id, "data": {"records": [original]}}, output=True)
        snapshot_root = self.workspace / "snapshots" / snapshot_id
        def hashes():
            return {str(path.relative_to(snapshot_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in snapshot_root.rglob("*") if path.is_file()}
        before = hashes()
        shutil.rmtree(self.repo)
        request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "ontology_pipeline_search", "arguments": {"workspace_id": self.workspace_id,
                "snapshot_id": snapshot_id, "kind": "semantic_fragment", "record_ids": [original["id"]], "limit": 1}}}
        process = subprocess.run([sys.executable, str(ROOT / "mcp/server.py")],
            input=(json.dumps(request) + "\n").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ), timeout=30, check=False)
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        wire = json.loads(process.stdout)
        result = wire["result"]
        self.assertFalse(result["isError"], result)
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        projected = result["structuredContent"]
        self.assertEqual(projected["snapshotId"], snapshot_id)
        self.assertEqual(projected["data"]["returned"], 1)
        delivered = projected["data"]["records"][0]
        from test_pipeline_delivery import restore
        self.assertEqual(restore(delivered["expression"]), original["expression"])
        self.assertEqual(delivered["expression"]["sourceBinding"]["sourceDigest"], original["sourceDigest"])
        self.assertEqual(hashes(), before)
