"""Selection-first omissions, private source boundaries and snapshot retention."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import code_ontology_core as core
import pipeline_store as store
import source_inventory as inventory


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "source"
        self.repo.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, source=b"class Example {}\n"):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode() if isinstance(source, str) else source)
        return path

    def discover(self, roots=None, **kwargs):
        return inventory.inventory(self.repo, roots or [], {".java": "Java", ".py": "Python"}, **kwargs)

    def rows(self, value):
        return {row["path"]: row for row in value["entries"]}

    def test_ignored_unsupported_and_protected_files_keep_original_denominator(self):
        self.write("src/Main.java")
        self.write("node_modules/deep/Dependency.java")
        self.write(".git/config", b"not for source analysis")
        self.write("README.unknown", b"unsupported")
        self.write("credentials.json", b"private fixture body")
        reads = []
        def reader(path):
            reads.append(path.relative_to(self.repo).as_posix())
            return path.read_bytes()
        value = self.discover(read_file=reader)
        self.assertEqual(value["summary"]["denominator"], 5)
        self.assertEqual(reads, ["src/Main.java"])
        rows = self.rows(value)
        self.assertEqual(rows["node_modules/deep/Dependency.java"]["reason"], "ignored_directory")
        self.assertEqual(rows[".git/config"]["reason"], "ignored_directory")
        self.assertEqual(rows["credentials.json"]["reason"], "protected_nonstructural_file")
        self.assertEqual(rows["README.unknown"]["status"], "unsupported")
        done = inventory.finish(value, {"src/Main.java": {"status": "analyzed", "reason": None}})
        self.assertEqual(done["summary"]["numerator"], 1)
        self.assertEqual(done["summary"]["percent"], 20.0)
        self.assertEqual(done["summary"]["state"], "PARTIAL")

    def test_structural_sensitive_name_is_analyzed_without_literal_output(self):
        literal = "synthetic-private-literal-do-not-emit"
        self.write("CredentialStore.java", 'class CredentialStore { String value() { return "' + literal + '"; } }')
        value = self.discover()
        self.assertEqual(value["summary"]["denominator"], 1)
        self.assertEqual(value["entries"][0]["status"], "eligible")
        self.assertNotIn(literal, json.dumps(value))
        document = core.build_document(self.repo)
        self.assertTrue(any(row.get("name") == "CredentialStore" for row in document["nodes"]))
        self.assertTrue(any(row.get("name") == "value" for row in document["nodes"]))
        self.assertNotIn(literal, json.dumps(document))
        self.assertEqual(document["source_coverage"]["summary"]["numerator"], 1)

    def test_duplicate_and_overlapping_roots_do_not_inflate_denominator(self):
        self.write("src/Main.java")
        self.write("src/nested/Other.java", "class Other {}")
        value = self.discover(["src", "src", "src/nested"])
        self.assertEqual(value["sourceRoots"], ["src"])
        self.assertEqual(value["summary"]["denominator"], 2)
        self.assertEqual(len({row["path"] for row in value["entries"]}), 2)

    def test_selected_ignored_root_is_recorded_but_not_read(self):
        self.write("node_modules/package/Module.java")
        with patch.object(core, "_safe_read_bytes", side_effect=AssertionError("must not read")):
            value = self.discover(["node_modules/package"])
        self.assertEqual(value["summary"]["denominator"], 1)
        self.assertEqual(value["entries"][0]["reason"], "ignored_directory")

    def test_invalid_root_never_reads_an_outside_source(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Other.java").write_text("class Other {}")
        for root in ("../outside", str(outside), "src/../outside", "src\\outside", "src//nested"):
            with self.subTest(root=root), patch.object(core, "_safe_read_bytes", side_effect=AssertionError("outside read")):
                with self.assertRaises(core.OntologyError):
                    self.discover([root])

    def test_invalid_utf8_keeps_hash_denominator_and_reason(self):
        raw = b"class Broken {\xff}\n"
        self.write("Broken.java", raw)
        value = self.discover()
        self.assertEqual(value["summary"]["state"], "BLOCKED")
        self.assertEqual(value["summary"]["denominator"], 1)
        self.assertEqual(value["entries"][0]["reason"], "unsupported_source_encoding")
        self.assertEqual(value["entries"][0]["sourceDigest"], hashlib.sha256(raw).hexdigest())

    def test_unreadable_file_reason_does_not_disclose_exception_body(self):
        self.write("Main.java")
        with patch.object(core, "_safe_read_bytes", side_effect=PermissionError("private fixture detail")):
            value = self.discover()
        self.assertEqual(value["summary"]["denominator"], 1)
        self.assertEqual(value["entries"][0]["reason"], "safe_source_read_failed")
        self.assertNotIn("private fixture detail", json.dumps(value))

    def test_metadata_failure_retains_target_impact_and_alternative(self):
        target = self.write("Main.java")
        original = Path.lstat
        def metadata(path, *args, **kwargs):
            if path == target:
                raise PermissionError("private metadata detail")
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", metadata):
            value = self.discover()
        self.assertEqual(value["summary"]["denominator"], 1)
        self.assertEqual(value["entries"][0]["reason"], "metadata_access_failed")
        self.assertTrue(value["entries"][0]["impact"])
        self.assertTrue(value["entries"][0]["alternative"])
        self.assertNotIn("private metadata detail", json.dumps(value))

    def test_unreadable_subtree_keeps_unknown_frontier(self):
        self.write("hidden/Main.java")
        real = os.scandir
        def scan(path):
            if Path(path).name == "hidden":
                raise PermissionError("private directory detail")
            return real(path)
        with patch.object(inventory.os, "scandir", side_effect=scan):
            value = self.discover()
        self.assertIsNone(value["summary"]["denominator"])
        self.assertEqual(value["summary"]["state"], "BLOCKED")
        self.assertIn({"path": "hidden", "reason": "directory_access_failed"},
            [{"path": r["path"], "reason": r["reason"]} for r in value["frontiers"]])

    def test_size_budget_blocks_without_reading_content(self):
        self.write("Large.java", b"x" * 32)
        with patch.object(core, "_safe_read_bytes", side_effect=AssertionError("over-limit read")):
            value = self.discover(max_source_bytes=16)
        self.assertEqual(value["entries"][0]["reason"], "source_size_budget")
        self.assertEqual(value["summary"]["denominator"], 1)

    def test_file_and_total_byte_limits_keep_every_discovered_file(self):
        for name in ("A.java", "B.java", "C.java"):
            self.write(name, "class X {}\n")
        for budget in ({"max_files": 1}, {"max_total_bytes": 12}):
            with self.subTest(budget=budget):
                value = self.discover(**budget)
                self.assertEqual(value["summary"]["denominator"], 3)
                self.assertEqual(value["summary"]["counts"]["eligible"], 1)
                self.assertEqual(value["summary"]["counts"]["blocked"], 2)
                self.assertEqual(sum(r["reason"] == "source_count_or_byte_budget" for r in value["entries"]), 2)

    def test_discovery_entry_and_depth_limits_mark_unknown_denominator(self):
        self.write("A.java")
        self.write("B.java")
        self.write("nested/deeper/C.java")
        bounded = self.discover(max_entries=1)
        self.assertTrue(bounded["summary"]["unknownDenominator"])
        self.assertIsNone(bounded["summary"]["denominator"])
        self.assertTrue(any(r["reason"] == "inventory_entry_budget" for r in bounded["frontiers"]))
        deep = self.discover(max_depth=0)
        self.assertIsNone(deep["summary"]["denominator"])
        self.assertTrue(any(r["reason"] == "directory_depth_budget" for r in deep["frontiers"]))

    def test_cancel_and_deadline_are_incomplete_before_discovery(self):
        self.write("Main.java")
        for stop in ({"cancel": lambda: True}, {"deadline": time.monotonic() - 1}):
            with self.subTest(stop=list(stop)):
                value = self.discover(**stop)
                self.assertIsNone(value["summary"]["denominator"])
                self.assertEqual(value["summary"]["state"], "BLOCKED")
                self.assertEqual(value["frontiers"][0]["reason"], "discovery_interrupted")

    def test_keyboard_interrupt_during_read_retains_known_files(self):
        self.write("A.java")
        self.write("B.java")
        with patch.object(core, "_safe_read_bytes", side_effect=KeyboardInterrupt):
            value = self.discover()
        self.assertEqual(value["summary"]["denominator"], 2)
        self.assertEqual(value["summary"]["state"], "BLOCKED")
        self.assertEqual(self.rows(value)["A.java"]["reason"], "source_read_interrupted")
        self.assertEqual(self.rows(value)["B.java"]["reason"], "processing_not_started")

    def test_keyboard_interrupt_in_discovery_check_has_frontier(self):
        self.write("Main.java")
        def cancelled():
            raise KeyboardInterrupt
        value = self.discover(cancel=cancelled)
        self.assertEqual(value["summary"]["state"], "BLOCKED")
        self.assertIsNone(value["summary"]["denominator"])
        self.assertEqual(value["frontiers"][0]["reason"], "discovery_interrupted")

    def test_symlink_and_git_link_do_not_follow_target(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Private.java").write_text("class Private {}")
        try:
            (self.repo / ".git").symlink_to(outside, target_is_directory=True)
            (self.repo / "Other.java").symlink_to(outside / "Private.java")
        except (OSError, NotImplementedError):
            self.skipTest("platform does not permit fixture symlinks")
        with patch.object(core, "_safe_read_bytes", side_effect=AssertionError("linked source read")):
            value = self.discover()
        self.assertEqual(value["summary"]["knownEntries"], 2)
        self.assertIsNone(value["summary"]["denominator"])
        self.assertTrue(all(r["reason"] == "symlink_or_reparse_point" for r in value["entries"]))
        self.assertNotIn("Private.java", json.dumps(value))

    def test_replaced_directory_is_not_enumerated_into_receipts(self):
        self.write("sub/Main.java")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Private.java").write_text("class Private {}")
        real = os.scandir
        moved = []
        def scan(path):
            if Path(path).name == "sub" and not moved:
                target = self.repo / "sub"
                target.rename(self.base / "original-sub")
                try:
                    target.symlink_to(outside, target_is_directory=True)
                except (OSError, NotImplementedError):
                    (self.base / "original-sub").rename(target)
                    self.skipTest("platform does not permit fixture symlinks")
                moved.append(True)
            return real(path)
        with patch.object(inventory.os, "scandir", side_effect=scan), patch.object(core, "_safe_read_bytes", side_effect=AssertionError("escaped read")):
            value = self.discover()
        self.assertEqual(value["summary"]["state"], "BLOCKED")
        self.assertNotIn("Private.java", json.dumps(value))

    def test_hardlink_is_reported_without_reading(self):
        self.write("A.java")
        try:
            os.link(self.repo / "A.java", self.repo / "B.java")
        except OSError:
            self.skipTest("platform does not permit fixture hardlinks")
        with patch.object(core, "_safe_read_bytes", side_effect=AssertionError("hardlinked read")):
            value = self.discover()
        self.assertEqual(value["summary"]["denominator"], 2)
        self.assertTrue(all(r["reason"] == "special_or_hardlinked_file" for r in value["entries"]))

    def test_changed_source_is_not_given_a_stable_hash(self):
        path = self.write("Main.java")
        def reader(file):
            raw = file.read_bytes()
            file.write_bytes(raw + b"// changed\n")
            return raw
        value = self.discover(read_file=reader)
        self.assertEqual(value["summary"]["state"], "BLOCKED")
        self.assertIsNone(value["entries"][0]["sourceDigest"])

    def test_finish_cannot_replace_discovery_identity_or_hide_unreached_files(self):
        self.write("A.java")
        self.write("B.java")
        value = self.discover()
        rows = self.rows(value)
        done = inventory.finish(value, {"A.java": {"status": "analyzed", "reason": None,
                "path": "replacement.java", "sourceDigest": "forged"}})
        self.assertEqual(done["scopeDigest"], value["scopeDigest"])
        self.assertEqual(self.rows(done)["A.java"]["sourceDigest"], rows["A.java"]["sourceDigest"])
        self.assertEqual(self.rows(done)["B.java"]["reason"], "processing_not_reached")
        self.assertEqual(done["summary"]["denominator"], 2)
        self.assertEqual(done["summary"]["state"], "BLOCKED")
        self.assertEqual(rows["A.java"]["status"], "eligible")

    def test_empty_source_is_not_completeness_success(self):
        value = self.discover()
        self.assertEqual(value["summary"]["denominator"], 0)
        self.assertEqual(value["summary"]["state"], "PARTIAL")
        self.assertIsNone(value["summary"]["percent"])

    def test_core_encoding_failure_preserves_previous_output(self):
        self.write("Main.java")
        output = self.base / "legacy-output"
        core.write_index(self.repo, output, authorized=True)
        before = (output / "ontology.json").read_bytes()
        self.write("Broken.java", b"class Broken {\xff}")
        with self.assertRaises(core.ScopeIncompleteError) as caught:
            core.write_index(self.repo, output, authorized=True, overwrite=True)
        self.assertEqual(caught.exception.inventory["summary"]["denominator"], 2)
        self.assertEqual((output / "ontology.json").read_bytes(), before)

    def test_pipeline_encoding_failure_retains_snapshot_and_attempt_inventory(self):
        self.write("main.py", "def main():\n    return 1\n")
        workspace = self.base / "pipeline"
        original = store.initialize(self.repo, workspace)["snapshotId"]
        self.write("broken.py", b"def broken():\n    return \xff\n")
        with self.assertRaises(store.PipelineError):
            store.sync(workspace)
        self.assertEqual(store.status(workspace)["snapshotId"], original)
        attempt = json.loads((workspace / "last-coverage-attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(attempt["summary"]["denominator"], 2)
        self.assertEqual(attempt["summary"]["state"], "BLOCKED")
        self.assertEqual(self.rows(attempt)["broken.py"]["reason"], "unsupported_source_encoding")


if __name__ == "__main__":
    unittest.main()
