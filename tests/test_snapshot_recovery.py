"""Crash boundaries and idempotent repair, using only synthetic local source."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import companion


class SnapshotRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        (self.repo / "sample.py").write_text("def first():\n    return 1\n", encoding="utf-8")
        self.workspace = self.base / "ontology"
        self.env = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.base / "registry")})
        self.env.start()
        self.first = companion.initialize(str(self.repo), str(self.workspace), authorized=True, label="synthetic")
        self.old_snapshot = self.workspace / "snapshots" / self.first["snapshotId"]
        self.old_bytes = self.digest(self.old_snapshot)
        (self.repo / "sample.py").write_text("def first():\n    return 1\ndef second():\n    return first()\n", encoding="utf-8")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def digest(path):
        return {item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
                for item in path.rglob("*") if item.is_file()}

    def interrupt(self, name, after=True):
        write = companion._atomic_write
        injected = []
        def fail(path, content, mode=0o600):
            target = name == path.name or (name == "prepared-receipt" and path.parent.name == ".transactions"
                                          and json.loads(content)["status"] == "prepared") or (
                name == "completed-receipt" and path.parent.name == ".transactions"
                and json.loads(content)["status"] == "completed")
            if target and not injected:
                injected.append(True)
                if after:
                    write(path, content, mode)
                raise OSError("injected synthetic write failure")
            return write(path, content, mode)
        with mock.patch.object(companion, "_atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                companion.sync(str(self.workspace))
        self.assertTrue(injected)

    def verify_recovery(self):
        result = companion.recover(str(self.workspace))
        self.assertEqual(result["recovery"]["status"], "healthy")
        again = companion.recover(str(self.workspace))
        self.assertEqual(again["recoveredRunCount"], 0)
        events = companion._read_journal(self.workspace)
        self.assertEqual(len(events), 2)
        self.assertEqual(len({event["eventId"] for event in events}), 2)
        self.assertEqual(len({event["runId"] for event in events}), 2)
        self.assertEqual(companion.sync(str(self.workspace))["status"], "no_change")
        self.assertEqual(self.old_bytes, self.digest(self.old_snapshot))
        self.assertEqual(companion.doctor(workspace_path=str(self.workspace))["recovery"]["status"], "healthy")

    def test_completed_artifacts_and_private_source_manifest_are_separated(self):
        manifest = json.loads((self.old_snapshot / "artifact-manifest.json").read_text())
        self.assertNotIn("source-manifest.json", manifest["artifacts"])
        self.assertEqual(set(manifest["artifacts"]), set(companion._SNAPSHOT_ARTIFACT_NAMES))
        for name, digest in manifest["artifacts"].items():
            self.assertEqual(hashlib.sha256((self.old_snapshot / name).read_bytes()).hexdigest(), digest)
        self.assertNotIn(str(self.repo), json.dumps(manifest))

    def test_crash_after_prepared_receipt_recovers_once(self):
        self.interrupt("prepared-receipt")
        self.assertEqual(companion.status(str(self.workspace))["pipelineStatus"], "recovery_required")
        with self.assertRaisesRegex(companion.CompanionError, "needs recovery"):
            companion.sync(str(self.workspace))
        self.verify_recovery()

    def test_crash_after_journal_recovers_once(self):
        self.interrupt("lineage.jsonl")
        self.verify_recovery()

    def test_crash_before_journal_recovers_once(self):
        self.interrupt("lineage.jsonl", after=False)
        self.verify_recovery()

    def test_crash_after_turtle_recovers_once(self):
        self.interrupt("lineage.ttl")
        self.verify_recovery()

    def test_crash_after_pointer_recovers_once(self):
        self.interrupt("state.json")
        self.verify_recovery()

    def test_crash_before_completed_receipt_recovers_once(self):
        self.interrupt("completed-receipt", after=False)
        self.verify_recovery()

    def test_crash_after_completed_receipt_is_already_complete(self):
        self.interrupt("completed-receipt")
        self.verify_recovery()

    def test_crash_before_prepared_receipt_preserves_current_and_can_sync(self):
        self.interrupt("prepared-receipt", after=False)
        self.assertEqual(companion._state(self.workspace)["currentSnapshot"], self.first["snapshotId"])
        self.assertEqual(len(companion._read_journal(self.workspace)), 1)
        self.assertEqual(companion.recover(str(self.workspace))["recoveredRunCount"], 0)
        companion.sync(str(self.workspace))
        self.verify_recovery()

    def test_incomplete_artifact_write_never_changes_current(self):
        self.interrupt("artifact-manifest.json")
        self.assertEqual(companion._state(self.workspace)["currentSnapshot"], self.first["snapshotId"])
        self.assertEqual(len(companion._read_journal(self.workspace)), 1)
        self.assertEqual(self.old_bytes, self.digest(self.old_snapshot))
        self.assertEqual(companion.doctor(workspace_path=str(self.workspace))["status"], "ok")

    def test_corrupted_artifact_cannot_be_promoted_by_recovery(self):
        self.interrupt("prepared-receipt")
        pending = [receipt for _path, receipt in companion._transaction_receipts(self.workspace)
                   if receipt["status"] == "prepared"][0]
        snapshot = self.workspace / "snapshots" / pending["snapshotId"]
        (snapshot / "graph.html").write_text("synthetic-corruption", encoding="utf-8")
        with self.assertRaisesRegex(companion.CompanionError, "integrity"):
            companion.recover(str(self.workspace))
        self.assertEqual(companion._state(self.workspace)["currentSnapshot"], self.first["snapshotId"])
        self.assertEqual(len(companion._read_journal(self.workspace)), 1)

    def test_conflicting_state_is_never_rolled_back(self):
        self.interrupt("prepared-receipt")
        state = companion._state(self.workspace)
        state["lastRunId"] = "synthetic-concurrent-state"
        companion._atomic_json(self.workspace / "state.json", state)
        with self.assertRaisesRegex(companion.CompanionError, "conflicts"):
            companion.recover(str(self.workspace))
        self.assertEqual(companion._state(self.workspace), state)
        self.assertEqual(len(companion._read_journal(self.workspace)), 1)

    def test_journal_event_identity_collision_fails_without_duplicate(self):
        event = companion._read_journal(self.workspace)[0]
        event["summary"] = "synthetic inconsistent duplicate"
        with self.assertRaisesRegex(companion.CompanionError, "conflicts"):
            companion._append_journal(self.workspace, event)
        self.assertEqual(len(companion._read_journal(self.workspace)), 1)

    def test_doctor_is_read_only_and_legacy_snapshot_remains_readable(self):
        # Version 0.8.1 snapshots do not have artifact manifests or receipts.
        for path in (self.workspace / ".transactions").iterdir():
            path.unlink()
        (self.old_snapshot / "artifact-manifest.json").unlink()
        before = self.digest(self.workspace)
        self.assertEqual(companion.doctor(workspace_path=str(self.workspace))["status"], "ok")
        self.assertEqual(before, self.digest(self.workspace))
        self.assertTrue(companion.query(str(self.workspace), "first")["matches"])

    def test_missing_current_run_event_is_detected_and_repaired_once(self):
        companion._atomic_write(self.workspace / "lineage.jsonl", b"")
        companion._render_lineage_turtle(self.workspace)
        self.assertEqual(companion.doctor(workspace_path=str(self.workspace))["status"], "attention_required")
        companion.recover(str(self.workspace))
        companion.recover(str(self.workspace))
        self.assertEqual(len(companion._read_journal(self.workspace)), 1)
        self.assertEqual(companion.doctor(workspace_path=str(self.workspace))["status"], "ok")

    @unittest.skipUnless(hasattr(os, "symlink"), "requires filesystem symlink support")
    def test_transaction_directory_link_fails_closed(self):
        root = self.workspace / ".transactions"
        outside = self.base / "outside-receipts"
        root.rename(outside)
        root.symlink_to(outside, target_is_directory=True)
        before = self.digest(outside)
        with self.assertRaises(companion.CompanionError):
            companion.recover(str(self.workspace))
        self.assertEqual(before, self.digest(outside))
        self.assertEqual(companion._state(self.workspace)["currentSnapshot"], self.first["snapshotId"])

    @unittest.skipUnless(hasattr(os, "symlink"), "requires filesystem symlink support")
    def test_receipt_link_cannot_promote_or_touch_target(self):
        self.interrupt("prepared-receipt")
        receipt_path, _receipt = next((path, receipt) for path, receipt in companion._transaction_receipts(self.workspace)
                                     if receipt["status"] == "prepared")
        outside = self.base / "outside-receipt.json"
        receipt_path.rename(outside)
        receipt_path.symlink_to(outside)
        before = outside.read_bytes()
        with self.assertRaises(companion.CompanionError):
            companion.recover(str(self.workspace))
        self.assertEqual(outside.read_bytes(), before)
        self.assertEqual(companion._state(self.workspace)["currentSnapshot"], self.first["snapshotId"])

    @unittest.skipUnless(hasattr(os, "symlink"), "requires filesystem symlink support")
    def test_turtle_link_rejection_preserves_journal(self):
        self.interrupt("prepared-receipt")
        before = (self.workspace / "lineage.jsonl").read_bytes()
        outside = self.base / "outside-export.ttl"
        outside.write_text("synthetic untouched", encoding="utf-8")
        ttl = self.workspace / "lineage.ttl"
        ttl.unlink()
        ttl.symlink_to(outside)
        with self.assertRaises(companion.CompanionError):
            companion.recover(str(self.workspace))
        self.assertEqual(outside.read_text(), "synthetic untouched")
        self.assertEqual((self.workspace / "lineage.jsonl").read_bytes(), before)

    def test_standalone_record_turtle_failure_can_be_repaired(self):
        original = companion._atomic_write
        def fail(path, content, mode=0o600):
            if path.name == "lineage.ttl":
                raise OSError("injected synthetic failure")
            return original(path, content, mode)
        with mock.patch.object(companion, "_atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                companion.record(str(self.workspace), "note", "Synthetic local check", "declared")
        self.assertEqual(companion.doctor(workspace_path=str(self.workspace))["status"], "attention_required")
        state = companion.status(str(self.workspace))
        self.assertEqual(state["status"], "attention_required")
        self.assertEqual(state["pipelineStatus"], "recovery_required")
        self.assertEqual(state["pendingRecoveryRuns"], 0)
        self.assertEqual(companion.recover(str(self.workspace))["recovery"]["status"], "healthy")
        repaired = companion.status(str(self.workspace))
        self.assertEqual(repaired["status"], "ok")
        self.assertEqual(repaired["pipelineStatus"], "refresh_required")
        self.assertEqual(repaired["freshness"], "stale")
        self.assertEqual(len(companion._read_journal(self.workspace)), 2)


if __name__ == "__main__":
    unittest.main()
