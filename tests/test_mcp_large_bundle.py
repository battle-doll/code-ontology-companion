"""Read-only MCP contracts for catalog scopes and coherent bounded bundles."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_mcp_contract as contract

server = contract.server


def tree_bytes(path: Path) -> dict:
    return {str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
            for item in path.rglob("*") if item.is_file()}


class McpLargeBundleTests(unittest.TestCase):
    maxDiff = None
    call = contract.McpContractTests.call
    assert_matches_contract = contract.McpContractTests.assert_matches_contract
    assert_safe_result = contract.McpContractTests.assert_safe_result
    assert_no_unsafe_strings = contract.McpContractTests.assert_no_unsafe_strings

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repository"
        self.repo.mkdir()
        self.data = self.base / "data"
        patcher = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.data)}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.roots = ["services/first", "services/second"]
        for root in self.roots:
            directory = self.repo / root
            directory.mkdir(parents=True)
            (directory / "flow.py").write_text(
                "def shared_leaf():\n    return 1\n\ndef shared_entry():\n    return shared_leaf()\n", encoding="utf-8")
        self.large = server.companion._large_project()

    def initialize_large(self):
        self.large_workspace = self.base / "large-workspace"
        self.large_result = self.large.initialize(str(self.repo), str(self.large_workspace),
                                                   authorized=True, module_roots=self.roots, label="synthetic-fixture")
        return self.large_result

    def initialize_normal(self):
        self.workspace = self.base / "normal-workspace"
        self.normal = server.companion.initialize(str(self.repo), str(self.workspace),
                                                  authorized=True, label="synthetic-fixture")
        return self.normal

    def invoke(self, name, arguments):
        return self.assert_safe_result(name, self.call(name, arguments), is_error=False)

    def test_parent_and_children_register_atomically_and_modes_keep_normal_compatibility(self):
        result = self.initialize_large()
        listing = self.invoke("ontology_list_workspaces", {})
        parent = next(item for item in listing["workspaces"] if item["id"] == result["workspaceId"])
        self.assertEqual(parent["mode"], "large")
        children = [item for item in listing["workspaces"] if item["id"] != parent["id"]]
        self.assertEqual(len(children), 2)
        self.assertTrue(all("mode" not in item for item in children))
        for child in children:
            self.invoke("ontology_search", {"workspace_id": child["id"], "term": "shared"})
        self.assert_safe_result("ontology_status", self.call("ontology_status", {"workspace_id": parent["id"]}), is_error=True)
        self.assert_safe_result("ontology_large_modules", self.call("ontology_large_modules", {"workspace_id": children[0]["id"]}), is_error=True)

    def test_modules_are_metadata_only_and_all_large_routes_are_read_only_safe_contracts(self):
        result = self.initialize_large()
        workspace_id = result["workspaceId"]
        before = tree_bytes(self.base)
        with mock.patch.object(server.companion, "_snapshot_view", side_effect=AssertionError("loaded graph")):
            modules = self.invoke("ontology_large_modules", {"workspace_id": workspace_id, "limit": 1})
        self.assertTrue(modules["metadataOnly"])
        self.assertEqual(modules["catalogSnapshotId"], result["catalogSnapshotId"])
        self.assertEqual(modules["nextOffset"], 1)
        self.assertTrue(modules["truncated"])
        search = self.invoke("ontology_large_search", {"workspace_id": workspace_id, "module_roots": self.roots,
                                                       "term": "shared", "limit": 1, "language": "Python"})
        self.assertEqual(search["returned"], 1)
        self.assertTrue(search["truncated"])
        match = search["matches"][0]
        neighbors = self.invoke("ontology_large_neighbors", {"workspace_id": workspace_id,
                                "module_root": match["moduleRoot"], "symbol": match["node"]["id"],
                                "relationships": ["CALLS"], "direction": "both"})
        self.assertEqual(neighbors["moduleSnapshotId"], match["moduleSnapshotId"])
        self.assertEqual(neighbors["crossModuleResolution"], "unsupported")
        self.assertEqual(neighbors["relationships"], ["CALLS"])
        self.assertFalse(neighbors["targetCodeExecuted"])
        self.assertFalse(neighbors["networkAccess"])
        self.assertEqual(tree_bytes(self.base), before)

    def test_large_pages_and_neighbors_remain_on_old_catalog_across_refresh(self):
        result = self.initialize_large()
        arguments = {"workspace_id": result["workspaceId"], "module_roots": self.roots,
                     "catalog_snapshot_id": result["catalogSnapshotId"], "term": "shared"}
        old = self.invoke("ontology_large_search", {**arguments, "limit": 200})
        first = self.invoke("ontology_large_search", {**arguments, "limit": 1})
        (self.repo / self.roots[1] / "new.py").write_text("def shared_new():\n    return 2\n", encoding="utf-8")
        changed = self.large.sync(str(self.large_workspace))
        self.assertNotEqual(changed["catalogSnapshotId"], result["catalogSnapshotId"])
        rest = self.invoke("ontology_large_search", {**arguments, "offset": first["nextOffset"]})
        self.assertEqual(first["matches"] + rest["matches"], old["matches"])
        absent = self.invoke("ontology_large_neighbors", {"workspace_id": result["workspaceId"],
                            "catalog_snapshot_id": result["catalogSnapshotId"], "module_root": self.roots[1], "symbol": "shared_new"})
        self.assertEqual(absent["status"], "not_found")
        self.assertEqual(absent["catalogSnapshotId"], result["catalogSnapshotId"])

    def test_large_inputs_reject_paths_nonconfigured_roots_and_bad_bounded_values(self):
        result = self.initialize_large()
        workspace_id = result["workspaceId"]
        cases = [
            ("ontology_large_modules", {"workspace_id": str(self.large_workspace)}),
            ("ontology_large_modules", {"workspace_id": workspace_id, "offset": True}),
            ("ontology_large_modules", {"workspace_id": workspace_id, "catalog_snapshot_id": "missing"}),
            ("ontology_large_search", {"workspace_id": workspace_id, "module_roots": ["services"], "term": "shared"}),
            ("ontology_large_search", {"workspace_id": workspace_id, "module_roots": ["../escape"], "term": "shared"}),
            ("ontology_large_search", {"workspace_id": workspace_id, "module_roots": self.roots * 2, "term": "shared"}),
            ("ontology_large_neighbors", {"workspace_id": workspace_id, "module_root": self.roots[0], "symbol": "shared", "relationships": ["invented"]}),
            ("ontology_large_neighbors", {"workspace_id": workspace_id, "module_root": self.roots[0], "symbol": "shared", "depth": False}),
        ]
        before = tree_bytes(self.base)
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                self.assert_safe_result(name, self.call(name, arguments), is_error=True)
        self.assertEqual(tree_bytes(self.base), before)

    def test_registered_large_identity_substitution_and_linked_parent_fail_closed(self):
        result = self.initialize_large()
        config_path = self.large_workspace / "large-project.json"
        original = config_path.read_bytes()
        config = json.loads(original)
        config["workspaceId"] = "00000000-0000-4000-8000-000000000001"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        arguments = {"workspace_id": result["workspaceId"]}
        self.assert_safe_result("ontology_large_modules", self.call("ontology_large_modules", arguments), is_error=True)
        config_path.write_bytes(original)
        relocated = self.base / "relocated"
        self.large_workspace.rename(relocated)
        try:
            self.large_workspace.symlink_to(relocated, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        self.assert_safe_result("ontology_large_modules", self.call("ontology_large_modules", arguments), is_error=True)

    def test_bundle_matches_individual_reads_uses_one_pin_and_never_writes(self):
        result = self.initialize_normal()
        workspace_id = result["workspaceId"]
        snapshot = result["snapshotId"]
        before = tree_bytes(self.base)
        args = {"workspace_id": workspace_id, "snapshot_id": snapshot}
        search = self.invoke("ontology_search", {**args, "term": "shared_entry"})
        symbol = search["matches"][0]["id"]
        neighbors = self.invoke("ontology_neighbors", {**args, "symbol": symbol, "direction": "outgoing", "relationships": ["CALLS"]})
        bundle = self.invoke("ontology_evidence_bundle", {**args, "requests": [
            {"id": "search-1", "operation": "search", "term": "shared_entry"},
            {"id": "impact-1", "operation": "neighbors", "symbol": symbol, "direction": "outgoing", "relationships": ["CALLS"]},
        ]})
        self.assertEqual(bundle["items"][0]["search"], search)
        self.assertEqual(bundle["items"][1]["neighbors"], neighbors)
        self.assertEqual(bundle["succeeded"], 2)
        self.assertEqual(bundle["failed"], 0)
        self.assertEqual(bundle["payloadBytes"], len(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
        self.assertEqual(tree_bytes(self.base), before)

    def test_bundle_resolves_current_once_despite_mid_bundle_refresh(self):
        result = self.initialize_normal()
        original = server.companion.query
        calls = []
        def query_and_refresh(*args, **kwargs):
            calls.append(kwargs["snapshot"])
            response = original(*args, **kwargs)
            if len(calls) == 1:
                (self.repo / self.roots[0] / "new.py").write_text("def shared_later():\n    return 2\n", encoding="utf-8")
                server.companion.sync(str(self.workspace))
            return response
        with mock.patch.object(server.companion, "query", side_effect=query_and_refresh):
            bundle = self.invoke("ontology_evidence_bundle", {"workspace_id": result["workspaceId"], "requests": [
                {"id": "first", "operation": "search", "term": "shared"},
                {"id": "second", "operation": "search", "term": "shared_later"},
            ]})
        self.assertEqual(calls, [result["snapshotId"], result["snapshotId"]])
        self.assertEqual(bundle["items"][1]["search"]["returned"], 0)
        self.assertEqual(bundle["snapshotId"], result["snapshotId"])

    def test_bundle_item_failure_is_safe_and_does_not_stop_following_read(self):
        result = self.initialize_normal()
        bundle = self.invoke("ontology_evidence_bundle", {"workspace_id": result["workspaceId"], "requests": [
            {"id": "invalid", "operation": "neighbors", "symbol": "shared", "depth": True},
            {"id": "override", "operation": "search", "term": "shared", "snapshot_id": "other"},
            {"id": "valid", "operation": "search", "term": "shared"},
        ]})
        self.assertEqual(bundle["status"], "partial")
        self.assertEqual([item["status"] for item in bundle["items"]], ["error", "error", "ok"])
        self.assertEqual(bundle["failed"], 2)
        self.assertNotIn("snapshot_id", bundle["items"][1]["message"])

    def test_bundle_envelope_rejects_duplicate_ids_unknown_operations_and_oversized_request_lists(self):
        result = self.initialize_normal()
        valid = {"id": "one", "operation": "search", "term": "shared"}
        bad_requests = [[], [valid, valid], [valid] * 9,
                        [{**valid, "operation": "write"}], [{**valid, "id": "../private"}], [False]]
        before = tree_bytes(self.base)
        for requests in bad_requests:
            with self.subTest(requests=requests):
                self.assert_safe_result("ontology_evidence_bundle", self.call("ontology_evidence_bundle",
                                        {"workspace_id": result["workspaceId"], "requests": requests}), is_error=True)
        self.assertEqual(tree_bytes(self.base), before)

    def test_bundle_shared_result_budget_reports_oversized_item_without_silent_truncation(self):
        result = self.initialize_normal()
        source = self.repo / self.roots[0] / "many.py"
        source.write_text("\n".join("def batch_%03d():\n    return 1\n" % i for i in range(120)), encoding="utf-8")
        server.companion.sync(str(self.workspace))
        bundle = self.invoke("ontology_evidence_bundle", {"workspace_id": result["workspaceId"], "requests": [
            {"id": "first", "operation": "search", "term": "batch_", "limit": 120},
            {"id": "second", "operation": "search", "term": "batch_", "limit": 120},
            {"id": "last", "operation": "search", "term": "batch_", "limit": 5},
        ]})
        self.assertEqual(bundle["returnedResults"], 125)
        self.assertEqual([item["status"] for item in bundle["items"]], ["ok", "error", "ok"])
        self.assertIn("result budget", bundle["items"][1]["message"])

    def test_bundle_shared_byte_budget_redacts_oversized_result_and_keeps_small_following_item(self):
        result = self.initialize_normal()
        original = server.companion.query
        def large_query(*args, **kwargs):
            response = original(*args, **kwargs)
            if args[1] == "oversized":
                response["term"] = "oversized"
                template = response["matches"][0] if response["matches"] else {"id": "x", "name": "x", "type": "Function", "language": "Python"}
                response["matches"] = [{**template, "id": "n" + str(index) + "x" * 900,
                                        "name": "n" * 450, "qualified_name": "q" * 900,
                                        "path": "pkg/" + "p" * 900 + ".py"} for index in range(150)]
                response["match_count"] = 150
            return response
        with mock.patch.object(server.companion, "query", side_effect=large_query):
            bundle = self.invoke("ontology_evidence_bundle", {"workspace_id": result["workspaceId"], "requests": [
                {"id": "big", "operation": "search", "term": "oversized", "limit": 150},
                {"id": "small", "operation": "search", "term": "shared", "limit": 1},
            ]})
        self.assertEqual(bundle["items"][0]["status"], "error")
        self.assertIn("byte budget", bundle["items"][0]["message"])
        self.assertEqual(bundle["items"][1]["status"], "ok")
        self.assertLessEqual(bundle["payloadBytes"], server.MAX_BUNDLE_PAYLOAD_BYTES)

    def test_bundle_backend_private_error_is_item_scoped_and_snapshot_mismatch_fails_closed(self):
        result = self.initialize_normal()
        original = server.companion.query
        def unsafe_query(*args, **kwargs):
            if args[1] == "error":
                raise server.companion.CompanionError("Unreadable /Users/alice/private/secret.py")
            response = original(*args, **kwargs)
            response["snapshotId"] = "different"
            return response
        with mock.patch.object(server.companion, "query", side_effect=unsafe_query):
            bundle = self.invoke("ontology_evidence_bundle", {"workspace_id": result["workspaceId"], "requests": [
                {"id": "private-error", "operation": "search", "term": "error"},
                {"id": "mismatch", "operation": "search", "term": "shared"},
            ]})
        self.assertEqual(bundle["failed"], 2)
        self.assertEqual(bundle["items"][0]["message"], "The local ontology request could not be completed.")


if __name__ == "__main__":
    unittest.main()
