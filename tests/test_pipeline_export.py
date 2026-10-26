"""Synthetic portable export permissions, source-free data and rollback tests."""
from __future__ import annotations

from contextlib import closing, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
from windows_fixture import protect_private_path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import companion
import pipeline_acl as acl
import pipeline_export as exporter
import pipeline_policy as policy
import pipeline_store as store
guard = companion.privacy_guard


class PipelineExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "source"
        self.repo.mkdir()
        self.workspace = self.base / "workspace"
        self.output = self.base / "portable"
        self.profile_path = self.base / "profile.json"
        self.profile = guard.build_profile(["Synthetic Private Person"], ["synthetic-person@privacy-fixture.test"], key=b"p" * 32)
        self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
        protect_private_path(self.profile_path)
        patcher = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(self.profile_path), acl.PRINCIPAL_ENV: "local-owner"})
        patcher.start(); self.addCleanup(patcher.stop)
        (self.repo / "orders.py").write_text("def order_allowed(active: bool, blocked: bool) -> bool:\n    return active and not blocked\n", encoding="utf-8")
        self.snapshot = store.initialize(self.repo, self.workspace)["snapshotId"]
        acl.initialize_access(self.workspace)
        self.directory = self.workspace / "snapshots" / self.snapshot

    def export(self, **kwargs):
        return exporter.export_bundle(self.workspace, self.snapshot, self.output, **kwargs)

    def assert_rolled_back(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".ontology-export-*")), [])

    def reader_with_exit(self, callback):
        original = store.open_reader
        @contextmanager
        def wrapped(*args, **kwargs):
            with original(*args, **kwargs) as reader:
                yield reader
            callback()
        return mock.patch.object(store, "open_reader", side_effect=wrapped)

    def test_source_deleted_bundle_contains_records_only_and_verified_artifacts(self):
        expected = list(store.iter_records(self.workspace, self.snapshot))
        private = self.workspace / "private-cache-marker"
        private.write_text("SYNTHETIC-CACHE-EXCLUDED", encoding="utf-8"); private.chmod(0o600)
        shutil.rmtree(self.repo)
        result = self.export()
        self.assertEqual(result["sourceAccess"], "not_read")
        self.assertEqual(set(p.name for p in self.output.iterdir()), {"knowledge.sqlite", "policy.json", "coverage.json", "ontology.ttl", "lineage.ttl", "shapes.ttl", "bundle.json"})
        manifest = json.loads((self.output / "bundle.json").read_text())
        self.assertEqual(manifest["developer"], "battle-doll")
        self.assertEqual(manifest["snapshotId"], self.snapshot)
        self.assertEqual(manifest["recordCount"], len(expected))
        for name, artifact in manifest["artifacts"].items():
            raw = (self.output / name).read_bytes()
            self.assertEqual(artifact, {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            self.assertNotIn(b"SYNTHETIC-CACHE-EXCLUDED", raw)
            if os.name != "nt": self.assertEqual((self.output / name).stat().st_mode & 0o077, 0)
        database = self.output / "knowledge.sqlite"
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("records",)])
            actual = [json.loads(row[0]) for row in db.execute("SELECT payload FROM records ORDER BY id")]
        self.assertEqual(actual, sorted(expected, key=lambda row: row["id"]))
        # SQLite's transaction context does not close its connection. Verify
        # deterministic handle release, including Windows rename semantics.
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        inspected_database = database.with_name("inspected.sqlite")
        database.rename(inspected_database)
        inspected_database.rename(database)
        snapshot = json.loads((self.output / "policy.json").read_text())
        answer = policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], {"active": True, "blocked": False})
        self.assertEqual(answer["value"], {"type": "bool", "value": True})

    def test_each_required_permission_and_snapshot_scope_are_enforced(self):
        required = {"export_bundle", "read_structure", "read_policy", "read_evidence"}
        for excluded in sorted(required):
            acl.update_access(self.workspace, "reader", sorted(required - {excluded}), [self.snapshot])
            with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
                with self.assertRaises(acl.AccessDenied): self.export()
            self.assert_rolled_back()
        acl.update_access(self.workspace, "reader", sorted(required), ["other-snapshot"])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            with self.assertRaises(acl.AccessDenied): self.export()
        self.assert_rolled_back()

    def test_missing_profile_and_unpinned_snapshot_are_rejected(self):
        self.profile_path.unlink()
        with self.assertRaises(companion.CompanionError): self.export()
        for snapshot in (None, "", "../other"):
            with self.assertRaises(companion.CompanionError):
                exporter.export_bundle(self.workspace, snapshot, self.output)
        self.assert_rolled_back()

    def test_revocation_during_export_prevents_promotion(self):
        def revoke():
            acl.update_access(self.workspace, "local-owner", sorted(acl.ACTIONS - {"export_bundle"}), ["*"])
        with self.reader_with_exit(revoke):
            with self.assertRaises(companion.CompanionError): self.export()
        self.assert_rolled_back()

    def test_acl_change_that_retains_permissions_also_requires_restart(self):
        with self.reader_with_exit(lambda: acl.update_access(self.workspace, "another-reader", ["read_structure"], [self.snapshot])):
            with self.assertRaisesRegex(companion.CompanionError, "authorization changed"):
                self.export()
        self.assert_rolled_back()

    def test_supported_acl_writer_cannot_race_final_authorization_and_promotion(self):
        original = acl.authorize; count = [0]; blocked = []
        def authorize(*args, **kwargs):
            result = original(*args, **kwargs); count[0] += 1
            if count[0] == 8:
                try:
                    acl.update_access(self.workspace, "late-reader", ["read_policy"], [self.snapshot])
                except companion.CompanionError:
                    blocked.append(True)
                else:
                    self.fail("ACL update crossed promotion lock")
            return result
        with mock.patch.object(acl, "authorize", side_effect=authorize): self.export()
        self.assertEqual(blocked, [True])
        # Lock must be released after successful export.
        self.assertEqual(acl.update_access(self.workspace, "late-reader", ["read_policy"], [self.snapshot])["status"], "ok")

    def test_reader_exit_integrity_failure_never_leaves_output(self):
        def fail(): raise store.PipelineError("synthetic_final_integrity_failure")
        with self.reader_with_exit(fail):
            with self.assertRaises(companion.CompanionError): self.export()
        self.assert_rolled_back()

    def test_staged_tamper_and_unlisted_file_prevent_promotion(self):
        def corrupt_stage():
            stage = next(self.base.glob(".ontology-export-*"))
            path = stage / "ontology.ttl"
            path.write_bytes(path.read_bytes() + b"\n")
        with self.reader_with_exit(corrupt_stage):
            with self.assertRaisesRegex(companion.CompanionError, "artifact changed"): self.export()
        self.assert_rolled_back()
        def add_file():
            stage = next(self.base.glob(".ontology-export-*"))
            path = stage / "unexpected.txt"; path.write_text("synthetic"); path.chmod(0o600)
        with self.reader_with_exit(add_file):
            with self.assertRaisesRegex(companion.CompanionError, "artifact set changed"): self.export()
        self.assert_rolled_back()

    def test_profile_change_and_destination_creation_prevent_promotion(self):
        def change_profile():
            replacement = guard.build_profile(["Other Synthetic Person"], ["other@privacy-fixture.test"], key=b"z" * 32)
            self.profile_path.write_text(json.dumps(replacement))
        with self.reader_with_exit(change_profile):
            with self.assertRaisesRegex(companion.CompanionError, "privacy policy changed"): self.export()
        self.assert_rolled_back()
        self.profile_path.write_text(json.dumps(self.profile))
        def create_destination():
            self.output.mkdir()
            (self.output / "existing").write_text("preserve")
        with self.reader_with_exit(create_destination):
            with self.assertRaisesRegex(companion.CompanionError, "destination appeared"): self.export()
        self.assertEqual((self.output / "existing").read_text(), "preserve")
        self.assertEqual(list(self.base.glob(".ontology-export-*")), [])

    def test_cancel_at_start_during_copy_and_before_promotion_rolls_back(self):
        event = threading.Event(); event.set()
        with self.assertRaisesRegex(companion.CompanionError, "cancelled"): self.export(cancel=event)
        self.assert_rolled_back(); event.clear()
        original = exporter._copy_interchange
        def copy_then_cancel(*args, **kwargs):
            original(*args, **kwargs); event.set()
        with mock.patch.object(exporter, "_copy_interchange", side_effect=copy_then_cancel):
            with self.assertRaisesRegex(companion.CompanionError, "cancelled"): self.export(cancel=event)
        self.assert_rolled_back(); event.clear()
        private_check = exporter._private_file
        def cancel_at_final_file(path):
            private_check(path)
            if path.name == "bundle.json": event.set()
        with mock.patch.object(exporter, "_private_file", side_effect=cancel_at_final_file):
            with self.assertRaisesRegex(companion.CompanionError, "cancelled"): self.export(cancel=event)
        self.assert_rolled_back()

    def test_byte_budget_rollback_and_no_private_workspace_destination(self):
        with self.assertRaisesRegex(companion.CompanionError, "byte budget"): self.export(max_output_bytes=1024)
        self.assert_rolled_back()
        with self.assertRaises(companion.CompanionError):
            exporter.export_bundle(self.workspace, self.snapshot, self.workspace / "export")
        self.assertFalse((self.workspace / "export").exists())

    def test_sealed_tamper_before_and_during_copy_is_rejected(self):
        path = self.directory / "ontology.ttl"; raw = path.read_bytes()
        path.write_bytes(raw + b"\n")
        with self.assertRaises(companion.CompanionError): self.export()
        self.assert_rolled_back()
        path.write_bytes(raw)
        original = exporter._copy_interchange
        def mutate_after_copy(*args, **kwargs):
            original(*args, **kwargs)
            if args[0].name == "ontology.ttl": path.write_bytes(raw + b"\n")
        with mock.patch.object(exporter, "_copy_interchange", side_effect=mutate_after_copy):
            with self.assertRaises(companion.CompanionError): self.export()
        self.assert_rolled_back()

    @unittest.skipIf(os.name == "nt", "POSIX mode weakening; Windows DACL is enforced by native helper")
    def test_staged_permission_weakening_and_hardlink_are_rejected(self):
        def weaken():
            next(self.base.glob(".ontology-export-*" )).joinpath("knowledge.sqlite").chmod(0o644)
        with self.reader_with_exit(weaken):
            with self.assertRaises(companion.CompanionError): self.export()
        self.assert_rolled_back()
        def link():
            path = next(self.base.glob(".ontology-export-*")).joinpath("knowledge.sqlite")
            os.link(path, self.base / "linked.sqlite")
        with self.reader_with_exit(link):
            with self.assertRaises(companion.CompanionError): self.export()
        self.assert_rolled_back()

    def test_record_count_mismatch_and_duplicate_ids_fail_closed(self):
        original = store.open_reader
        @contextmanager
        def missing(*args, **kwargs):
            with original(*args, **kwargs) as reader:
                reader.metadata["recordCount"] += 1
                yield reader
        with mock.patch.object(store, "open_reader", side_effect=missing):
            with self.assertRaisesRegex(companion.CompanionError, "record count"): self.export()
        self.assert_rolled_back()
        iterator = store.SnapshotReader.iter_records
        def duplicate(reader, **kwargs):
            for row in iterator(reader, **kwargs):
                yield row; yield row
        with mock.patch.object(store.SnapshotReader, "iter_records", duplicate):
            with self.assertRaisesRegex(companion.CompanionError, "failed validation"): self.export()
        self.assert_rolled_back()

    def test_private_identity_is_rejected_without_echoing_payload(self):
        iterator = store.SnapshotReader.iter_records
        def inject(reader, **kwargs):
            for row in iterator(reader, **kwargs):
                yield {**row, "note": "Synthetic Private Person"}
        with mock.patch.object(store.SnapshotReader, "iter_records", inject):
            with self.assertRaises(companion.CompanionError) as result: self.export()
        self.assertNotIn("Synthetic Private Person", str(result.exception))
        self.assert_rolled_back()

    def test_single_line_ten_thousand_rule_json_is_copied_without_line_cap(self):
        snapshot = store.read_policy_records(self.workspace, self.snapshot)
        base_rule, base_evidence = snapshot["rules"][0], snapshot["evidence"][0]
        snapshot["rules"], snapshot["evidence"] = [], []
        for index in range(10000):
            rule, evidence = copy.deepcopy(base_rule), copy.deepcopy(base_evidence)
            rule["id"] = f"policy:synthetic-{index}"; rule["name"] = f"order_rule_{index}"
            evidence["id"] = f"assertion:synthetic-{index}"
            rule["sourceAssertionIds"] = [evidence["id"]]
            for domain in rule["domains"]: domain["evidenceIds"] = [evidence["id"]]
            snapshot["rules"].append(rule); snapshot["evidence"].append(evidence)
        snapshot["coverage"].update(detectedRules=10000, analyzedRules=10000)
        snapshot["rulesetDigest"] = policy.policy_ruleset_digest(snapshot)
        raw = companion._json_bytes(snapshot)
        self.assertGreater(len(raw), 4 * 1024 * 1024)
        self.assertLessEqual(len(raw), exporter.MAX_POLICY_BYTES)
        original = self.workspace / "large-policy.json"; original.write_bytes(raw); original.chmod(0o600)
        target = self.base / "policy.json"
        info = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        exporter._copy_interchange(original, target, info, profile=self.profile, roots=(self.workspace, self.base), checkpoint=lambda: None)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), info["sha256"])

    def test_policy_decoding_and_rdf_line_boundaries_preserve_privacy_checks(self):
        original = self.workspace / "test-policy.json"
        value = {"rules": [{"note": "Synthetic Private Person"}], "evidence": []}
        raw = json.dumps(value).replace("Synthetic", "\\u0053ynthetic").encode()
        original.write_bytes(raw); original.chmod(0o600)
        info = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        with self.assertRaises(guard.PrivacyError):
            exporter._copy_interchange(original, self.base / "policy.json", info, profile=self.profile, roots=(self.workspace, self.base), checkpoint=lambda: None)
        self.assertFalse((self.base / "policy.json").exists())
        raw = b"#" + b"x" * (exporter.MAX_INTERCHANGE_LINE + 1)
        original.write_bytes(raw)
        info = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        with self.assertRaisesRegex(companion.CompanionError, "record exceeds"):
            exporter._copy_interchange(original, self.base / "ontology.ttl", info, profile=self.profile, roots=(self.workspace, self.base), checkpoint=lambda: None)


if __name__ == "__main__":
    unittest.main()
