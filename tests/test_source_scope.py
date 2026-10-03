"""Synthetic scope, identity, and atomic snapshot boundary regressions."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import code_ontology_core as core  # noqa: E402
import companion  # noqa: E402


class SourceScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.workspace = self.base / "workspace"
        self.environment = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.base / "data")})
        self.environment.start()
        self.write("src/main/java/demo/Main.java", "package demo; public class Main extends Helper { public void run() {} }\n")
        self.write("src/main/java/demo/Helper.java", "package demo; public class Helper {}\n")
        self.write("src/test/java/demo/Check.java", "package demo; public class Check {}\n")

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def write(self, relative: str, source: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def initialize(self, roots=None) -> dict:
        return companion.initialize(str(self.repo), str(self.workspace), authorized=True, source_roots=roots)

    def state(self) -> dict:
        return json.loads((self.workspace / "state.json").read_text(encoding="utf-8"))

    def current_document(self) -> dict:
        return json.loads((self.workspace / "snapshots" / self.state()["currentSnapshot"] / "ontology.json").read_text())

    def add_copy(self) -> None:
        self.write("validation/prechange/Main.java", "package demo; public class Main { public void stale() {} }\n")

    def test_same_java_identity_across_files_fails_without_publishing(self) -> None:
        self.add_copy()
        output = self.base / "standalone"
        with self.assertRaises(core.DuplicateDeclarationError) as caught:
            core.write_index(self.repo, output, authorized=True)
        message = str(caught.exception)
        self.assertIn("demo.Main", message)
        self.assertIn("src/main/java/demo/Main.java", message)
        self.assertIn("validation/prechange/Main.java", message)
        self.assertIn("--source-root", message)
        self.assertFalse(output.exists())
        with self.assertRaises(core.DuplicateDeclarationError):
            self.initialize()
        self.assertFalse(self.workspace.exists())

    def test_java_cross_kind_duplicates_share_type_namespace(self) -> None:
        for kind, declaration in (("interface", "interface Main {}"), ("enum", "enum Main { ONE }"), ("record", "record Main(int value) {}")):
            with self.subTest(kind=kind):
                self.write("copies/Main.java", "package demo; " + declaration)
                with self.assertRaises(core.DuplicateDeclarationError):
                    core.build_document(self.repo)
                self.assertTrue(core.build_document(self.repo, ["src/main"])["nodes"])

    def test_recursive_calls_survive_source_index_and_visualization_payload(self) -> None:
        self.write("recursive/loop.py", "def recurse(n):\n    return recurse(n-1) if n else 0\n")
        self.write("recursive/Loop.java", "package demo;\nclass Loop {\n public int recurse(int n) {\n return n > 0 ? recurse(n-1) : 0;\n }\n}\n")
        document = core.build_document(self.repo, ["recursive"])
        self.assertEqual(document["warnings"], [])
        loops = [edge for edge in document["edges"] if edge["type"] == "CALLS" and edge["source"] == edge["target"]]
        self.assertEqual(len(loops), 2)
        self.assertTrue(any(edge["source"].startswith("java:") for edge in loops))
        self.assertTrue(any(edge["source"].startswith("python:") for edge in loops))
        payload = core._visualization_payload(document, 10)
        self.assertEqual(sum(edge["type"] == "CALLS" and edge["source"] == edge["target"] for edge in payload["edges"]), 2)

    def test_watch_discards_plan_superseded_by_explicit_scope_change(self) -> None:
        self.initialize(["src/main"])
        planned, resume = threading.Event(), threading.Event()
        original = companion._manifest
        paused, failures = [], []
        def manifest(repo, roots=None):
            value = original(repo, roots)
            if threading.current_thread().name == "scope-review-watch" and not paused:
                paused.append(True)
                planned.set()
                if not resume.wait(5):
                    raise RuntimeError("watch resume timeout")
            return value
        def run():
            try:
                companion.watch(str(self.workspace), 1, 1)
            except BaseException as exc:
                failures.append(exc)
        with mock.patch.object(companion, "_manifest", side_effect=manifest):
            thread = threading.Thread(target=run, name="scope-review-watch")
            thread.start()
            try:
                self.assertTrue(planned.wait(5))
                explicit = companion.sync(str(self.workspace), source_roots=["src/test"])
            finally:
                resume.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(self.state()["sourceRoots"], ["src/test"])
        self.assertEqual(self.state()["currentSnapshot"], explicit["snapshotId"])

    def test_snapshot_lock_excludes_other_process_and_releases_after_error(self) -> None:
        self.initialize(["src/main"])
        child = "import sys; sys.path.insert(0,sys.argv[1]); import companion; from pathlib import Path\nwith companion._snapshot_write_lock(Path(sys.argv[2])): pass\n"
        with companion._snapshot_write_lock(self.workspace):
            result = subprocess.run([sys.executable, "-c", child, str(SCRIPTS), str(self.workspace)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Another snapshot writer", result.stderr)
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with companion._snapshot_write_lock(self.workspace):
                raise RuntimeError("synthetic")
        with companion._snapshot_write_lock(self.workspace):
            pass

    def test_stale_explicit_writer_cannot_replace_promoted_state(self) -> None:
        self.initialize(["src/main"])
        root, previous = companion._workspace(self.workspace)
        explicit = companion.sync(str(self.workspace), source_roots=["src/test"])
        with self.assertRaises(companion.StaleSnapshotPlan):
            companion._create_snapshot(root, previous, "manual")
        self.assertEqual(self.state()["currentSnapshot"], explicit["snapshotId"])

    def test_same_python_module_identity_is_not_silently_coalesced(self) -> None:
        self.write("src/work.py", "class Worker:\n    def run(self): pass\n")
        self.write("work.py", "class Worker:\n    def old(self): pass\n")
        with self.assertRaises(core.DuplicateDeclarationError) as caught:
            core.build_document(self.repo)
        self.assertIn("src/work.py", str(caught.exception))
        self.assertIn("'work.py'", str(caught.exception))
        document = core.build_document(self.repo, ["src"])
        workers = [node for node in document["nodes"] if node.get("qualified_name") == "work.Worker"]
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["path"], "src/work.py")

    def test_scoped_python_identity_does_not_depend_on_out_of_scope_package_marker(self) -> None:
        self.write("src/app/work.py", "class Worker: pass\n")
        before = core.build_document(self.repo, ["src/app"])
        fingerprint = companion._manifest(self.repo, ["src/app"])["fingerprint"]
        self.write("src/__init__.py", "# Marker outside the selected roots.\n")
        after = core.build_document(self.repo, ["src/app"])
        self.assertEqual(before["nodes"], after["nodes"])
        self.assertEqual(before["edges"], after["edges"])
        self.assertEqual(companion._manifest(self.repo, ["src/app"])["fingerprint"], fingerprint)
        whole = core.build_document(self.repo)
        self.assertTrue(any(node.get("qualified_name") == "src.app.work.Worker" for node in whole["nodes"]))

    def test_scoped_index_keeps_all_selected_declarations_and_resolves_shared_package(self) -> None:
        self.add_copy()
        document = core.build_document(self.repo, ["src/main"])
        declarations = {node.get("qualified_name"): node for node in document["nodes"]}
        self.assertIn("demo.Main", declarations)
        self.assertIn("demo.Helper", declarations)
        self.assertNotIn("demo.Check", declarations)
        self.assertEqual(sum(node["type"] == "Package" for node in document["nodes"]), 1)
        main, helper = declarations["demo.Main"], declarations["demo.Helper"]
        self.assertTrue(any(edge["type"] == "EXTENDS" and edge["source"] == main["id"] and edge["target"] == helper["id"] for edge in document["edges"]))
        self.assertEqual(document["repository"]["source_roots"], ["src/main"])
        payload = core._visualization_payload(document, 10)
        self.assertEqual(payload["meta"]["sourceRoots"], ["src/main"])
        self.assertEqual(payload["meta"]["sourceScope"], "selected_roots")
        self.assertEqual(len(payload["nodes"]), len(document["nodes"]))
        self.assertEqual(len(payload["edges"]), len(document["edges"]))

    def test_overlapping_roots_deduplicate_before_limits_and_are_order_independent(self) -> None:
        roots = ["src/main/java", "src/main", "src/main", "src/test"]
        with mock.patch.object(core, "MAX_SOURCE_FILES", 3):
            sources, _ = core.discover_sources(self.repo, roots)
        self.assertEqual(len(sources), 3)
        self.assertEqual(core.normalize_source_roots(self.repo, roots), ["src/main", "src/test"])
        self.assertEqual(companion._manifest(self.repo, roots), companion._manifest(self.repo, list(reversed(roots))))

    def test_scope_never_bypasses_sensitive_build_or_link_exclusions(self) -> None:
        self.write("src/main/build/Generated.java", "class Generated {}")
        self.write("src/main/secrets/Hidden.java", "class Hidden {}")
        self.write("src/main/private_key.py", "class HiddenKey: pass")
        self.write("src/main/.git/Metadata.java", "class Metadata {}")
        self.write("src/main/TARGET/Compiled.java", "class Compiled {}")
        sources, skipped = core.discover_sources(self.repo, ["src/main"])
        self.assertEqual(len(sources), 2)
        self.assertEqual(skipped["sensitive_name"], 2)
        self.assertEqual(skipped["excluded_directory"], 3)
        for root in ("src/main/build", "src/main/secrets", "src/main/.git", "src/main/TARGET"):
            with self.subTest(root=root), self.assertRaises(core.OntologyError):
                core.discover_sources(self.repo, [root])

    def test_unsafe_or_missing_root_is_rejected_before_any_output(self) -> None:
        invalid = ["/tmp", "../repo", "src/../src/main", "src//main", "src/./main", "src\\main", "C:/src", "src/main/", "src/main.", "src/main\x00", "src/main\x7f", "missing", "src/main/java/demo/Main.java"]
        for root in invalid:
            with self.subTest(root=root), self.assertRaises(core.OntologyError):
                self.initialize([root])
            self.assertFalse(self.workspace.exists())
        for roots in (["src", "src/../src/main"], [".", "../repo"], "src/main", 4, [None]):
            with self.subTest(roots=roots), self.assertRaises(core.OntologyError):
                core.normalize_source_roots(self.repo, roots)

    def test_root_cannot_traverse_internal_or_external_symlink(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Leak.java").write_text("class Leak {}")
        for name, target in (("linked", outside), ("alias", self.repo / "src")):
            try:
                (self.repo / name).symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Directory symlinks unavailable: {exc}")
            with self.subTest(name=name), self.assertRaises(core.OntologyError):
                core.discover_sources(self.repo, [name])
        with self.assertRaises(core.OntologyError):
            core.discover_sources(self.repo, ["alias/main"])
        sources, skipped = core.discover_sources(self.repo)
        self.assertEqual(len(sources), 3)
        self.assertEqual(skipped["symlink_or_reparse"], 2)

    def test_windows_reparse_ancestor_is_rejected(self) -> None:
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            if path == self.repo / "src":
                return types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=core.WINDOWS_REPARSE_POINT)
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "lstat", reparse), self.assertRaisesRegex(core.OntologyError, "reparse"):
            core.discover_sources(self.repo, ["src/main"])

    def test_directory_replaced_after_discovery_is_rejected_before_source_read(self) -> None:
        original = core.discover_sources
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Main.java").write_text("class Leak {}")
        def replace(repo, roots=None):
            sources, skipped = original(repo, roots)
            folder = self.repo / "src/main/java/demo"
            shutil.rmtree(folder)
            try:
                folder.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Directory symlinks unavailable: {exc}")
            return sources, skipped
        with mock.patch.object(core, "discover_sources", side_effect=replace), mock.patch.object(core, "_safe_read_bytes", wraps=core._safe_read_bytes) as reader:
            with self.assertRaises(companion.CompanionError):
                companion._manifest(self.repo, ["src/main"])
            reader.assert_not_called()

    def test_preflight_manifest_and_snapshot_share_scope(self) -> None:
        self.add_copy()
        preflight = companion.preflight(str(self.repo), ["src/main"])
        result = self.initialize(["src/main"])
        snapshot = self.workspace / "snapshots" / result["snapshotId"]
        manifest = json.loads((snapshot / "source-manifest.json").read_text())
        metadata = json.loads((snapshot / "snapshot.json").read_text())
        self.assertEqual(preflight["source_file_count"], result["sourceFileCount"])
        self.assertEqual(len(manifest["files"]), 2)
        for record in (result, manifest, metadata, self.state()):
            self.assertEqual(record["sourceRoots"], ["src/main"])
        current = companion.status(str(self.workspace))
        self.assertEqual(current["freshness"], "current")
        self.assertEqual(current["snapshotSourceRoots"], current["sourceRoots"])

    def test_changes_outside_selected_roots_do_not_make_scope_stale(self) -> None:
        first = self.initialize(["src/main"])
        self.add_copy()
        self.write("src/test/java/demo/Check.java", "package demo; public class ChangedTest {}")
        self.assertEqual(companion.status(str(self.workspace))["freshness"], "current")
        unchanged = companion.sync(str(self.workspace))
        self.assertEqual(unchanged["snapshotId"], first["snapshotId"])
        self.assertEqual(unchanged["status"], "no_change")
        self.write("src/main/java/demo/Helper.java", "package demo; public class Helper { void newMethod() {} }")
        self.assertEqual(companion.status(str(self.workspace))["freshness"], "stale")
        second = companion.sync(str(self.workspace))
        self.assertNotEqual(second["snapshotId"], first["snapshotId"])
        self.assertEqual(companion.diff(str(self.workspace))["changeBasis"], "source_change")

    def test_missing_selected_root_marks_snapshot_stale_without_expanding_scope(self) -> None:
        first = self.initialize(["src/main"])
        before = self.state()
        shutil.rmtree(self.repo / "src/main")
        current = companion.status(str(self.workspace))
        self.assertEqual(current["snapshotId"], first["snapshotId"])
        self.assertEqual(current["freshness"], "stale")
        self.assertEqual(current["sourceRoots"], ["src/main"])
        self.assertIn("could not be verified", current["message"])
        self.assertTrue(companion.query(str(self.workspace), "demo.Main")["matches"])
        with self.assertRaises(core.OntologyError):
            companion.sync(str(self.workspace))
        self.assertEqual(self.state(), before)
        repaired = companion.sync(str(self.workspace), source_roots=["src/test"])
        self.assertEqual(repaired["sourceRoots"], ["src/test"])
        self.assertEqual(companion.status(str(self.workspace))["freshness"], "current")

    def test_scope_change_rebuilds_even_when_selected_files_are_identical(self) -> None:
        first = self.initialize(["src/main"])
        before = self.current_document()
        second = companion.sync(str(self.workspace), source_roots=["src/main/java"])
        self.assertNotEqual(first["snapshotId"], second["snapshotId"])
        self.assertEqual(before["nodes"], self.current_document()["nodes"])
        comparison = companion.diff(str(self.workspace))
        self.assertEqual(comparison["changeBasis"], "source_scope_change")
        self.assertTrue(comparison["sourceScopeChanged"])
        self.assertEqual(comparison["beforeSourceRoots"], ["src/main"])
        self.assertEqual(comparison["afterSourceRoots"], ["src/main/java"])
        self.assertEqual(core.canonical_diff(self.current_document(), before)["basis"], "source_scope_change")
        self.assertEqual(companion.sync(str(self.workspace))["status"], "no_change")

    def test_failed_scope_change_keeps_old_scope_and_current_snapshot(self) -> None:
        self.initialize(["src/main"])
        before = self.state()
        before_config = (self.workspace / "companion.json").read_bytes()
        with mock.patch.object(core, "write_visualization", side_effect=core.OntologyError("render failed")):
            with self.assertRaisesRegex(core.OntologyError, "render failed"):
                companion.sync(str(self.workspace), source_roots=["src/test"])
        self.assertEqual(self.state(), before)
        self.assertEqual((self.workspace / "companion.json").read_bytes(), before_config)
        self.assertEqual(companion.status(str(self.workspace))["sourceRoots"], ["src/main"])
        self.assertEqual(companion.sync(str(self.workspace))["status"], "no_change")

    def test_duplicate_on_scope_widening_does_not_replace_snapshot(self) -> None:
        self.initialize(["src/main"])
        before = self.state()
        self.add_copy()
        with self.assertRaises(core.DuplicateDeclarationError):
            companion.sync(str(self.workspace), source_roots=["."])
        self.assertEqual(self.state(), before)
        self.assertEqual(companion.status(str(self.workspace))["freshness"], "current")

    def test_explicit_dot_resets_scope_and_legacy_default_stays_whole_repository(self) -> None:
        self.initialize(["src/main"])
        result = companion.sync(str(self.workspace), source_roots=["."])
        self.assertEqual(result["sourceRoots"], [])
        self.assertEqual(result["sourceFileCount"], 3)
        self.assertEqual(self.current_document()["repository"]["source_scope"], "whole_repository")
        self.assertEqual(companion.sync(str(self.workspace))["status"], "no_change")

    def test_whole_repository_manifest_preserves_legacy_hash_encoding(self) -> None:
        manifest = companion._manifest(self.repo)
        legacy = hashlib.sha256()
        for item in manifest["files"]:
            # The v0.6.1 manifest hash was the ordered JSON file records only.
            legacy.update(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertEqual(manifest["fingerprint"], legacy.hexdigest())
        self.assertEqual(manifest, companion._manifest(self.repo, ["."]))
        subset = companion._manifest(self.repo, ["src"])
        self.assertEqual(manifest["files"], subset["files"])
        self.assertNotEqual(manifest["fingerprint"], subset["fingerprint"])

    def test_legacy_workspace_upgrade_retains_source_identity_and_reports_analyzer_change(self) -> None:
        with mock.patch.object(core, "PLUGIN_VERSION", "0.6.1"), mock.patch.object(companion, "COMPANION_VERSION", "0.6.1"):
            old = self.initialize()
        state = self.state()
        state.pop("sourceRoots")
        companion._atomic_json(self.workspace / "state.json", state)
        snapshot = self.workspace / "snapshots" / old["snapshotId"]
        metadata = json.loads((snapshot / "snapshot.json").read_text())
        metadata.pop("sourceRoots")
        companion._atomic_json(snapshot / "snapshot.json", metadata)
        document = self.current_document()
        document["repository"].pop("source_roots")
        document["repository"].pop("source_scope")
        document["companion"].pop("sourceRoots")
        companion._atomic_json(snapshot / "ontology.json", document)
        stale = companion.status(str(self.workspace))
        self.assertEqual(stale["freshness"], "stale")
        self.assertIn("current analyzer", stale["message"])
        upgraded = companion.sync(str(self.workspace))
        self.assertEqual(upgraded["sourceRoots"], [])
        self.assertEqual(self.current_document()["companion"]["sourceFingerprint"], metadata["sourceFingerprint"])
        self.assertEqual(companion.diff(str(self.workspace))["changeBasis"], "analyzer_reinterpretation")

    def test_foreground_watch_uses_saved_scope(self) -> None:
        first = self.initialize(["src/main"])
        self.add_copy()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            companion.watch(str(self.workspace), interval_seconds=1, max_cycles=1)
        event = json.loads(output.getvalue())
        self.assertEqual(event["status"], "no_change")
        self.assertEqual(event["snapshotId"], first["snapshotId"])
        self.assertEqual(event["sourceRoots"], ["src/main"])

    def test_visualization_inventory_is_full_index_retention_not_source_completeness(self) -> None:
        self.write("src/main/broken.py", "def missing(:\n")
        document = core.build_document(self.repo, ["src/main"])
        self.assertTrue(document["warnings"])
        output = self.base / "visualization"
        output.mkdir()
        index = output / "ontology.json"
        index.write_text(json.dumps(document), encoding="utf-8")
        result = core.write_visualization(str(index), str(output / "graph.html"), max_nodes=1)
        self.assertTrue(result["payload_preserves_indexed_inventory"])
        self.assertEqual(result["nodes_indexed"], len(document["nodes"]))
        self.assertEqual(result["relationships_indexed"], len(document["edges"]))
        self.assertGreater(result["nodes_indexed"], result["nodes_rendered"])
        self.assertEqual(result["nodes_rendered_basis"], "legacy_visible_budget_upper_bound")
        self.assertEqual(result["render_mode"], "hierarchical_paginated")
        self.assertFalse(result["initial_render_observed"])

    def test_visualization_reports_when_invalid_index_relationship_was_not_preserved(self) -> None:
        document = core.build_document(self.repo, ["src/main"])
        document["edges"].append({"source": "missing", "target": "missing-too", "type": "CALLS"})
        output = self.base / "visualization"
        output.mkdir()
        index = output / "ontology.json"
        index.write_text(json.dumps(document), encoding="utf-8")
        result = core.write_visualization(str(index), str(output / "graph.html"), max_nodes=10)
        self.assertFalse(result["payload_preserves_indexed_inventory"])
        self.assertEqual(result["relationships_indexed"], len(document["edges"]))

    def test_cli_roots_reach_preflight_index_init_and_sync(self) -> None:
        self.add_copy()
        commands = [
            ("code_ontology_core.py", ["preflight", "--repo", str(self.repo), "--source-root", "src/main"]),
            ("companion.py", ["preflight", "--repo", str(self.repo), "--source-root", "src/main"]),
            ("code_ontology_core.py", ["index", "--repo", str(self.repo), "--output", str(self.base / "index"), "--source-root", "src/main", "--authorized"]),
            ("companion.py", ["init", "--repo", str(self.repo), "--workspace", str(self.workspace), "--source-root", "src/main", "--authorized"]),
            ("companion.py", ["sync", "--workspace", str(self.workspace), "--source-root", "src/main", "--source-root", "src/test"]),
        ]
        for script, arguments in commands:
            with self.subTest(command=arguments[0], script=script):
                result = subprocess.run([sys.executable, str(SCRIPTS / script), *arguments], text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                body = json.loads(result.stdout)
                self.assertIn(body["status"], {"ready", "indexed", "promoted"})
        self.assertEqual(self.state()["sourceRoots"], ["src/main", "src/test"])
        self.assertEqual(len(companion._manifest(self.repo, self.state()["sourceRoots"])["files"]), 3)


if __name__ == "__main__":
    unittest.main()
