"""Neutral staged failure, sealed generation, and source-deleted stdio MCP read."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_policy_conditional_type_precision import SOURCE, returned, reject_call
from test_literal_review_pipeline import store, privacy_guard, protect_private_path
from test_pipeline_delivery import restore
import pipeline_access as access
import pipeline_acl as acl


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt", "Native Windows privacy ACL evidence is separate")
class PipelineConditionalTypePrecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.repo = self.root / "source"
        self.repo.mkdir(mode=0o700); self.workspace = self.root / "knowledge"
        source = self.repo / "Capacity.java"; source.write_text(SOURCE); os.chmod(source, 0o600)
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps(privacy_guard.build_profile(["Neutral Example Person"],
            ["neutral@example.test"], key=b"n" * 32)))
        protect_private_path(self.profile)
        env = patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(self.profile),
            "CODE_ONTOLOGY_HOME": str(self.root / "registry"), acl.PRINCIPAL_ENV: "local-owner"})
        env.start(); self.addCleanup(env.stop)

    def generate_with_rejected_condition(self, repeat=None):
        real_finalizer = store._finalize_semantic_dependencies
        rejected = []
        def stage_rejection(dbs, *args, **kwargs):
            for db in dbs:
                for path, encoded in db.execute("SELECT path,facts FROM files").fetchall():
                    facts = json.loads(encoded)
                    if path != "Capacity.java": continue
                    expression = returned(facts["semantics"])["expression"]
                    records = {row["id"]: row for row in facts["records"]}
                    reject_call(records, expression["condition"])
                    facts["records"] = list(records.values())
                    # Persist the single rejecting callsite change through the
                    # real staging writer; all other definitions remain real.
                    rejected.append(expression["condition"]["sourceInvocationOffset"])
                    store._write_facts(db, facts)
            completed = real_finalizer(dbs, *args, **kwargs)
            if repeat is not None:
                for db in dbs:
                    for path, encoded in db.execute("SELECT path,facts FROM files").fetchall():
                        if path != "Capacity.java": continue
                        current = returned(json.loads(encoded)["semantics"])
                        self.assertEqual(current["expression"]["staticType"]["name"], "int")
                        self.assertEqual(current["dependencyClosure"]["status"], "invalidated")
                        if repeat == "missing_owner":
                            # The second real DB lookup cannot supply the old
                            # owner, while the file still supplies the current IR.
                            db.execute("DELETE FROM records WHERE id=?", (current["id"],))
                completed = real_finalizer(dbs, *args, **kwargs)
            return completed
        with patch.object(store, "_finalize_semantic_dependencies", side_effect=stage_rejection):
            result = store.initialize(self.repo, self.workspace)
        self.assertEqual(len(rejected), 1)
        acl.initialize_access(self.workspace); access.register(str(self.workspace))
        rows = list(store.iter_records(self.workspace, result["snapshotId"]))
        original = returned({"fragments": rows})
        if repeat == "missing_owner":
            self.assertNotIn("staticType", original["expression"])
            self.assertNotIn("retainedEvidence", original["expression"]["staticEvidenceStatus"])
        else: self.assertEqual(original["expression"]["staticType"]["name"], "int")
        self.assertNotIn("staticType", original["expression"]["condition"])
        self.assertEqual(original["representationStatus"], "partial")
        self.assertEqual(original["dependencyClosure"]["status"], "invalidated")
        self.assertFalse(original["businessMeaningVerified"])
        self.assertEqual(original["runtimeStatus"], "not_observed")
        return result, original

    def call(self, result, record, snapshot=None, allow_rpc_rejection=False):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "ontology_pipeline_search", "arguments": {"workspace_id": result["workspaceId"],
                "snapshot_id": snapshot or result["snapshotId"], "kind": "semantic_fragment",
                "record_ids": [record["id"]], "limit": 1}}}
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        process = subprocess.run([sys.executable, "-E", "-s", "-B", "-X",
            "pycache_prefix=" + str(self.root / "pycache"), str(ROOT / "mcp/server.py")],
            input=json.dumps(request) + "\n", text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, timeout=30, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        wire = json.loads(process.stdout)
        if "error" in wire and allow_rpc_rejection:
            self.assertEqual(wire["error"]["message"], "Response rejected by the privacy guard.")
            self.assertNotIn("result", wire)
            return wire
        self.assertNotIn("error", wire)
        answer = wire["result"]
        if not answer["isError"]:
            self.assertEqual(json.loads(answer["content"][0]["text"]), answer["structuredContent"])
        return answer

    def test_source_deleted_actual_mcp_preserves_type_and_fail_closed_boundaries(self):
        result, original = self.generate_with_rejected_condition()
        snapshot = self.workspace / "snapshots" / result["snapshotId"]
        def hashes():
            return {str(path.relative_to(snapshot)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in snapshot.rglob("*") if path.is_file()}
        before = hashes(); shutil.rmtree(self.repo)
        answer = self.call(result, original)
        self.assertFalse(answer["isError"], answer)
        delivered = answer["structuredContent"]["data"]["records"][0]
        expression = delivered["expression"]
        if expression.get("format") == "companion.flat-json.v1": expression = restore(expression)
        self.assertEqual(expression, original["expression"])
        self.assertEqual(delivered["representationStatus"], "partial")
        self.assertFalse(delivered["businessMeaningVerified"])
        self.assertEqual(delivered["runtimeStatus"], "not_observed")
        self.assertEqual(delivered["dependencyClosure"], original["dependencyClosure"])
        self.assertEqual(answer["structuredContent"]["snapshotId"], result["snapshotId"])
        self.assertTrue(self.call(result, original, snapshot="ps-not-the-pinned-snapshot")["isError"])
        acl.update_access(self.workspace, "precision-reader", ["read_structure", "read_policy", "read_evidence"], [result["snapshotId"]])
        with patch.dict(os.environ, {acl.PRINCIPAL_ENV: "precision-reader"}):
            self.assertFalse(self.call(result, original)["isError"])
        acl.update_access(self.workspace, "precision-reader", ["read_policy"], [result["snapshotId"]])
        with patch.dict(os.environ, {acl.PRINCIPAL_ENV: "precision-reader"}):
            self.assertTrue(self.call(result, original)["isError"])
        self.profile.unlink()
        self.assertIn("error", self.call(result, original, allow_rpc_rejection=True))
        self.assertEqual(hashes(), before)

    def assert_repeated_source_deleted_mcp(self, repeat):
        result, original = self.generate_with_rejected_condition(repeat=repeat)
        shutil.rmtree(self.repo)
        answer = self.call(result, original)
        self.assertFalse(answer["isError"], answer)
        delivered = answer["structuredContent"]["data"]["records"][0]
        expression = delivered["expression"]
        if expression.get("format") == "companion.flat-json.v1": expression = restore(expression)
        self.assertEqual(expression, original["expression"])
        self.assertEqual(delivered["dependencyClosure"], original["dependencyClosure"])
        self.assertEqual(delivered["representationStatus"], "partial")
        self.assertFalse(delivered["businessMeaningVerified"])
        self.assertEqual(delivered["runtimeStatus"], "not_observed")

    def test_repeated_fresh_partial_owner_survives_source_deleted_mcp(self):
        self.assert_repeated_source_deleted_mcp("fresh_owner")

    def test_repeated_missing_owner_withdrawal_survives_source_deleted_mcp(self):
        self.assert_repeated_source_deleted_mcp("missing_owner")


if __name__ == "__main__": unittest.main()
