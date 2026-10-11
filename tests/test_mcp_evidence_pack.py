"""Bounded compact delivery parity, privacy, wire framing and pinned pagination."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_mcp_contract as contract

server = contract.server


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def expand(pack, item):
    nodes = {row["ref"]: row["node"] for row in pack["nodes"]}
    evidence = {row["ref"]: row["evidence"] for row in pack["evidence"]}
    data = copy.deepcopy(item[item["operation"]])
    for key in ("matches", "candidates"):
        if key in data:
            data[key] = [nodes[ref] for ref in data[key]]
    if "root" in data:
        data["root"] = nodes[data["root"]]
    for row in data.get("impact", []):
        row["node"] = nodes[row["node"]]
        row["evidence"] = [evidence[ref] for ref in row["evidence"]]
        for step in row.get("path", []):
            step["evidence"] = [evidence[ref] for ref in step["evidence"]]
    data.update({key: pack[key] for key in ("workspaceId", "snapshotId", "freshness", "quality")})
    return data


class EvidencePackTests(unittest.TestCase):
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
        patcher = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.base / "data")})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.repo / "flow.py").write_text(
            "def shared_leaf(value: int) -> int:\n    return value\n\n"
            "def shared_entry(value: int) -> int:\n    return shared_leaf(value)\n\n"
            + "\n".join("def batch_%03d():\n    return shared_entry(%d)\n" % (i, i) for i in range(35)), encoding="utf-8")
        self.workspace = self.base / "workspace"
        self.initial = server.companion.initialize(str(self.repo), str(self.workspace), authorized=True, label="synthetic-pack")
        self.arguments = {"workspace_id": self.initial["workspaceId"]}
        search = self.call("ontology_search", {**self.arguments, "term": "shared_entry"})["structuredContent"]
        self.symbol = search["matches"][0]["id"]

    def pack(self, requests, **options):
        response = self.call("ontology_evidence_pack", {**self.arguments, "requests": requests, **options})
        return self.assert_safe_result("ontology_evidence_pack", response, is_error=False)

    def test_full_fields_reconstruct_legacy_results_and_deduplicate_exact_representations(self):
        requests = [
            {"id": "one", "operation": "search", "term": "shared"},
            {"id": "two", "operation": "neighbors", "symbol": self.symbol, "direction": "both", "relationships": ["CALLS"]},
            {"id": "three", "operation": "search", "term": "shared"},
        ]
        pack = self.pack(requests)
        for item, request in zip(pack["items"], requests):
            legacy = self.call("ontology_" + request["operation"], {**self.arguments,
                **{key: value for key, value in request.items() if key not in {"id", "operation"}}})["structuredContent"]
            legacy.pop("nextOffset", None)
            self.assertEqual(expand(pack, item), legacy)
        self.assertEqual(pack["status"], "ok")
        self.assertEqual(pack["items"][0]["search"]["matches"], pack["items"][2]["search"]["matches"])
        self.assertEqual(len({node["ref"] for node in pack["nodes"]}), len(pack["nodes"]))
        self.assertEqual(len({canonical(row["evidence"]) for row in pack["evidence"]}), len(pack["evidence"]))
        self.assertNotIn("quality", pack["items"][0]["search"])

    def test_payload_and_wire_bytes_include_request_id_text_fallback_and_newline(self):
        request = {"jsonrpc": "2.0", "id": "long-id-" + "가" * 40, "method": "tools/call", "params": {
            "name": "ontology_evidence_pack", "arguments": {**self.arguments, "requests": [
                {"id": "search", "operation": "search", "term": "batch"}], "max_wire_bytes": 22000}}}
        response = server._handle(request)
        pack = self.assert_safe_result("ontology_evidence_pack", response["result"], is_error=False)
        self.assertEqual(pack["payloadBytes"], len(canonical(pack)))
        actual_wire = len(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        self.assertEqual(pack["wireBytes"], actual_wire)
        self.assertLessEqual(actual_wire, 22000)
        self.assertGreater(actual_wire, pack["payloadBytes"] * 2)

    def test_search_pages_keep_pin_and_exact_selectors_across_refresh_without_duplicates(self):
        request = {"id": "search", "operation": "search", "term": "batch", "limit": 9,
                   "language": "Python", "node_type": "Function", "path_prefix": "flow.py"}
        first = self.pack([request], max_results=4)
        (self.repo / "later.py").write_text("def batch_later():\n    return 1\n", encoding="utf-8")
        server.companion.sync(str(self.workspace))
        page, collected, positions = first, [], []
        for _ in range(40):
            self.assertEqual(page["snapshotId"], self.initial["snapshotId"])
            item = page["items"][0]
            positions.append((item["search"]["offset"], item["pageOffset"]))
            collected.extend(node["id"] for node in expand(page, item)["matches"])
            if "continuation" not in page:
                break
            continuation = page["continuation"]
            resumed = continuation["arguments"]["requests"][0]
            for key in ("id", "operation", "term", "limit", "language", "node_type", "path_prefix"):
                self.assertEqual(resumed[key], request[key])
            page = self.assert_safe_result("ontology_evidence_pack", self.call(
                continuation["tool"], continuation["arguments"]), is_error=False)
        else:
            self.fail("Continuation made no progress")
        self.assertEqual(len(collected), 35)
        self.assertEqual(len(set(collected)), 35)
        self.assertEqual(positions, sorted(set(positions)))

    def test_neighbor_rows_page_without_splitting_paths_or_dangling_evidence(self):
        request = {"id": "impact", "operation": "neighbors", "symbol": self.symbol,
                   "direction": "incoming", "relationships": ["CALLS"], "depth": 1, "limit": 10}
        page = self.pack([request], max_results=3)
        rows = []
        for _ in range(10):
            item = page["items"][0]
            rows.extend(expand(page, item)["impact"])
            # Expanding every row resolves every node and evidence reference, including paths.
            if "continuation" not in page:
                self.assertIn("query_limit", item["excludedReasons"])
                self.assertEqual(item["completeness"], "partial")
                break
            page = self.assert_safe_result("ontology_evidence_pack", self.call(
                "ontology_evidence_pack", page["continuation"]["arguments"]), is_error=False)
        legacy = self.call("ontology_neighbors", {**self.arguments,
            **{key: value for key, value in request.items() if key not in {"id", "operation"}}})["structuredContent"]
        self.assertEqual(rows, legacy["impact"])
        self.assertEqual(len(rows), 10)

    def test_complete_page_endpoint_fits_even_when_removing_cursor_changes_budget_monotonicity(self):
        requests = [{"id": "one", "operation": "search", "term": "batch", "limit": 200}]
        full = self.pack(requests)
        limited = self.pack(requests, max_wire_bytes=full["wireBytes"])
        self.assertEqual(limited["returnedResults"], full["returnedResults"])
        self.assertNotIn("continuation", limited)
        self.assertLessEqual(limited["wireBytes"], full["wireBytes"])

    def test_fields_projection_is_explicit_and_refs_remain_stable(self):
        requests = [{"id": "one", "operation": "search", "term": "shared"}]
        full = self.pack(requests)
        narrow = self.pack(requests, node_fields=[])
        self.assertEqual(narrow["omittedNodeFields"], list(server.PACK_NODE_FIELDS))
        for row in narrow["nodes"]:
            self.assertEqual(set(row["node"]), {"id", "name", "type", "language"})
        repeated = self.pack(requests, node_fields=[])
        self.assertEqual(narrow["nodes"], repeated["nodes"])
        self.assertLess(narrow["payloadBytes"], full["payloadBytes"])

    def test_duplicate_request_ids_bad_options_and_overrides_fail_safely(self):
        valid = {"id": "one", "operation": "search", "term": "shared"}
        cases = [
            {"requests": []}, {"requests": [valid, valid]}, {"requests": [valid] * 9},
            {"requests": [valid], "max_results": True}, {"requests": [valid], "max_results": 201},
            {"requests": [valid], "max_wire_bytes": 16383},
            {"requests": [valid], "max_payload_bytes": 262145},
            {"requests": [valid], "node_fields": ["path", "path"]},
            {"requests": [valid], "node_fields": ["secret"]},
            {"requests": [{**valid, "page_offset": True}]},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assert_safe_result("ontology_evidence_pack", self.call("ontology_evidence_pack", {
                    **self.arguments, **case}), is_error=True)
        mixed = self.pack([{**valid, "snapshot_id": "other"}, {**valid, "id": "two"}])
        self.assertEqual(mixed["status"], "partial")
        self.assertEqual([item["status"] for item in mixed["items"]], ["error", "ok"])

    def test_private_backend_data_and_errors_never_escape(self):
        request = {"id": "one", "operation": "search", "term": "shared"}
        original = server.companion.query
        def unsafe(*args, **kwargs):
            result = original(*args, **kwargs)
            result["matches"][0]["name"] = "synthetic-private" + "@" + "privacy-sentinel.testmail.org"
            return result
        with mock.patch.object(server.companion, "query", side_effect=unsafe):
            reply = self.call("ontology_evidence_pack", {**self.arguments, "requests": [request]})
        self.assertTrue(reply["isError"])
        self.assertNotIn("testmail.org", json.dumps(reply))
        with mock.patch.object(server.companion, "query", side_effect=server.companion.CompanionError(
                "synthetic-private" + "@" + "privacy-sentinel.testmail.org")):
            pack = self.pack([request])
        self.assertEqual(pack["items"][0]["status"], "error")
        self.assertNotIn("testmail.org", json.dumps(pack))

    def test_byte_budget_paginates_and_reconstructs_every_bounded_search_row(self):
        request = {"id": "search", "operation": "search", "term": "batch", "limit": 200}
        original = server.companion.query
        def heavy(*args, **kwargs):
            result = original(*args, **kwargs)
            for node in result["matches"]:
                node["metadata"]["parameter_types"] = ["LongSyntheticType" + str(i) + "x" * 90 for i in range(10)]
            return result
        with mock.patch.object(server.companion, "query", side_effect=heavy):
            page = self.pack([request], max_payload_bytes=22000, max_wire_bytes=48000)
            collected = []
            for _ in range(40):
                self.assertLessEqual(page["payloadBytes"], 22000)
                self.assertLessEqual(page["wireBytes"], 48000)
                collected.extend(node["id"] for node in expand(page, page["items"][0])["matches"])
                if "continuation" not in page:
                    break
                self.assertIn("byte_budget", page["items"][0]["excludedReasons"])
                page = self.assert_safe_result("ontology_evidence_pack", self.call(
                    "ontology_evidence_pack", page["continuation"]["arguments"]), is_error=False)
            else:
                self.fail("Byte continuation made no progress")
        self.assertEqual(len(collected), 35)
        self.assertEqual(len(set(collected)), 35)

    def test_references_bind_exact_representations_even_when_ids_duplicate(self):
        original = server.companion.query
        def duplicate(*args, **kwargs):
            result = original(*args, **kwargs)
            if len(result["matches"]) >= 2:
                result["matches"][1]["id"] = result["matches"][0]["id"]
            return result
        with mock.patch.object(server.companion, "query", side_effect=duplicate):
            page = self.pack([{"id": "search", "operation": "search", "term": "shared"}])
        self.assertEqual(len(page["nodes"]), 2)
        self.assertEqual(len({row["node"]["id"] for row in page["nodes"]}), 1)
        self.assertEqual(len({row["ref"] for row in page["nodes"]}), 2)
        for row in page["nodes"]:
            self.assertEqual(row["ref"], "n:" + hashlib.sha256(canonical(row["node"])).hexdigest())

    def test_read_only_byte_failure_is_actionable_and_has_no_nonprogress_cursor(self):
        def tree():
            return {str(path.relative_to(self.base)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.base.rglob("*") if path.is_file()}
        original = server.companion.query
        before = tree()
        def enormous(*args, **kwargs):
            result = original(*args, **kwargs)
            for node in result["matches"]:
                node["metadata"]["parameter_types"] = ["SyntheticType" + str(i) + "x" * 450 for i in range(64)]
            return result
        with mock.patch.object(server.companion, "query", side_effect=enormous):
            result = self.call("ontology_evidence_pack", {**self.arguments, "max_wire_bytes": 16384,
                "requests": [{"id": "one", "operation": "search", "term": "shared", "limit": 1}]})
        self.assertTrue(result["isError"])
        self.assertIn("increase the byte budget", result["structuredContent"]["message"])
        self.assertNotIn("continuation", result["structuredContent"])
        self.assertEqual(tree(), before)

    def test_projected_row_loss_fails_closed_instead_of_inventing_complete_pagination(self):
        original = server.companion.query
        def malformed(*args, **kwargs):
            result = original(*args, **kwargs)
            result["matches"][0].pop("id")
            return result
        with mock.patch.object(server.companion, "query", side_effect=malformed):
            pack = self.pack([{"id": "one", "operation": "search", "term": "shared"}])
        self.assertEqual(pack["items"][0]["status"], "error")
        self.assertNotIn("continuation", pack)

    def test_snapshot_mismatch_is_error_and_other_valid_reads_survive(self):
        original = server.companion.query
        def mismatch(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1] == "batch":
                result["snapshotId"] = "different-snapshot"
            return result
        with mock.patch.object(server.companion, "query", side_effect=mismatch):
            pack = self.pack([{"id": "first", "operation": "search", "term": "batch"},
                              {"id": "second", "operation": "search", "term": "shared"}])
        self.assertEqual(pack["status"], "partial")
        self.assertEqual([item["status"] for item in pack["items"]], ["error", "ok"])

    def test_current_alias_resolves_once_even_when_sources_refresh_mid_read(self):
        original = server.companion.query
        observed = []
        def refresh(*args, **kwargs):
            observed.append(kwargs["snapshot"])
            result = original(*args, **kwargs)
            if len(observed) == 1:
                (self.repo / "later.py").write_text("def brand_new():\n    return 2\n", encoding="utf-8")
                server.companion.sync(str(self.workspace))
            return result
        with mock.patch.object(server.companion, "query", side_effect=refresh):
            pack = self.pack([{"id": "one", "operation": "search", "term": "shared"},
                              {"id": "two", "operation": "search", "term": "brand_new"}])
        self.assertEqual(observed, [self.initial["snapshotId"]] * 2)
        self.assertEqual(pack["items"][1]["returnedRows"], 0)


if __name__ == "__main__":
    unittest.main()
