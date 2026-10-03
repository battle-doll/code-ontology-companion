from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import companion  # noqa: E402
import code_ontology_core as core  # noqa: E402
import large_project  # noqa: E402


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class LargeProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repo = self.base / "private-repository"
        self.workspace = self.base / "large-workspace"
        self.data_home = self.base / "data"
        (self.repo / "services" / "java").mkdir(parents=True)
        (self.repo / "services" / "python").mkdir(parents=True)
        (self.repo / "services" / "java" / "Shared.java").write_text(
            "package sample; public class Shared { String secret = \"PRIVATE_SOURCE_BODY\"; }\n",
            encoding="utf-8",
        )
        (self.repo / "services" / "python" / "shared.py").write_text(
            "def shared():\n    return 'PRIVATE_SOURCE_BODY'\n",
            encoding="utf-8",
        )
        self.roots = ["services/java", "services/python"]
        self.environment = mock.patch.dict(
            os.environ,
            {"CODE_ONTOLOGY_HOME": str(self.data_home)},
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def initialize(self) -> dict:
        return large_project.initialize(
            str(self.repo),
            str(self.workspace),
            authorized=True,
            label="Private <Catalog>",
            module_roots=self.roots,
        )

    def state(self) -> dict:
        return json.loads((self.workspace / "state.json").read_text(encoding="utf-8"))

    def catalog(self, snapshot_id: str) -> dict:
        path = self.workspace / "catalog-snapshots" / snapshot_id / "catalog.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_preflight_is_read_only_and_authorization_precedes_writes(self) -> None:
        checked = large_project.preflight(str(self.repo), self.roots)
        self.assertEqual(checked["status"], "ready")
        self.assertEqual(checked["moduleCount"], 2)
        self.assertEqual(
            checked["perModuleLimits"]["maxTotalSourceBytes"],
            core.MAX_TOTAL_SOURCE_BYTES,
        )
        self.assertTrue(all(item["supportedSourceBytes"] > 0 for item in checked["modules"]))
        self.assertFalse(self.workspace.exists())
        with self.assertRaises(companion.CompanionError):
            large_project.initialize(
                str(self.repo),
                str(self.workspace),
                authorized=False,
                module_roots=self.roots,
            )
        self.assertFalse(self.workspace.exists())
        self.assertFalse((self.data_home / "registry.json").exists())

    def test_initialize_builds_pinned_children_and_private_portable_catalog(self) -> None:
        result = self.initialize()
        catalog = self.catalog(result["catalogSnapshotId"])
        page = (Path(result["index"])).read_text(encoding="utf-8")
        registry = json.loads((self.data_home / "registry.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "promoted")
        self.assertEqual(catalog["moduleCount"], 2)
        self.assertEqual([item["root"] for item in catalog["modules"]], self.roots)
        self.assertEqual(len(registry["workspaces"]), 3)
        parent = [item for item in registry["workspaces"] if item.get("mode") == "large"]
        self.assertEqual(len(parent), 1)
        self.assertEqual(parent[0]["id"], result["workspaceId"])
        self.assertEqual(companion.resolve_registered_large_workspace(parent[0]["id"]), self.workspace.resolve())
        for module in catalog["modules"]:
            child = self.workspace / "modules" / module["moduleId"]
            child_config = json.loads((child / "companion.json").read_text(encoding="utf-8"))
            child_state = json.loads((child / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(child_config["repositoryRoot"], str(self.repo.resolve()))
            self.assertEqual(child_state["sourceRoots"], [module["root"]])
            self.assertEqual(child_state["currentSnapshot"], module["snapshotId"])
            self.assertEqual(module["analyzerVersion"], core.PLUGIN_VERSION)
            self.assertEqual(module["companionVersion"], companion.COMPANION_VERSION)
        self.assertIn("Content-Security-Policy", page)
        self.assertIn("script-src 'none'", page)
        self.assertIn("../../modules/", page)
        self.assertIn("<table>", page)
        self.assertIn("Supported bytes", page)
        self.assertIn("Pinned snapshot", page)
        self.assertIn("Large analysis mode", page)
        self.assertIn("normal-mode module graph", page)
        self.assertIn("large-modules", page)
        self.assertIn("large-impact", page)
        self.assertEqual(result["mode"], "large")
        self.assertEqual(catalog["workflow"]["moduleGraphMode"], "normal")
        self.assertNotIn(str(self.repo.resolve()), page)
        self.assertNotIn("PRIVATE_SOURCE_BODY", page)
        self.assertNotIn("<script", page.lower())

    def test_incremental_sync_changes_only_one_module_and_preserves_old_catalog(self) -> None:
        initial = self.initialize()
        initial_id = initial["catalogSnapshotId"]
        initial_catalog = self.catalog(initial_id)
        initial_path = self.workspace / "catalog-snapshots" / initial_id
        initial_digest = tree_digest(initial_path)

        unchanged = large_project.sync(str(self.workspace))
        self.assertEqual(unchanged["status"], "no_change")
        self.assertEqual(unchanged["catalogSnapshotId"], initial_id)

        (self.repo / "services" / "python" / "changed.py").write_text(
            "def changed_symbol():\n    return 1\n",
            encoding="utf-8",
        )
        changed = large_project.sync(str(self.workspace))
        changed_catalog = self.catalog(changed["catalogSnapshotId"])
        before = {item["root"]: item["snapshotId"] for item in initial_catalog["modules"]}
        after = {item["root"]: item["snapshotId"] for item in changed_catalog["modules"]}

        self.assertEqual(changed["status"], "promoted")
        self.assertEqual(changed["previousCatalogSnapshotId"], initial_id)
        self.assertEqual(before["services/java"], after["services/java"])
        self.assertNotEqual(before["services/python"], after["services/python"])
        self.assertEqual(tree_digest(initial_path), initial_digest)
        current = large_project.status(str(self.workspace))
        self.assertEqual(current["freshness"], "current")
        self.assertTrue(all(item["catalogBinding"] == "pinned_current" for item in current["modules"]))

    def test_force_rebuilds_every_module_and_promotes_new_catalog(self) -> None:
        initial = self.initialize()
        before = {item["root"]: item["snapshotId"] for item in initial["modules"]}
        forced = large_project.sync(str(self.workspace), force=True)
        after = {item["root"]: item["snapshotId"] for item in forced["modules"]}
        self.assertEqual(forced["status"], "promoted")
        self.assertEqual(forced["previousCatalogSnapshotId"], initial["catalogSnapshotId"])
        self.assertEqual(set(before), set(after))
        self.assertTrue(all(before[root] != after[root] for root in before))

    def test_module_failure_preserves_catalog_and_reports_advanced_child(self) -> None:
        initial = self.initialize()
        initial_id = initial["catalogSnapshotId"]
        (self.repo / "services" / "java" / "Advanced.java").write_text(
            "package sample; public class AdvancedOnly {}\n",
            encoding="utf-8",
        )
        real_sync = companion.sync
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise companion.CompanionError("synthetic second module failure")
            return real_sync(*args, **kwargs)

        with mock.patch.object(large_project.companion, "sync", side_effect=fail_second):
            with self.assertRaisesRegex(companion.CompanionError, "prior catalog remains current"):
                large_project.sync(str(self.workspace))

        self.assertEqual(self.state()["currentCatalogSnapshot"], initial_id)
        report = json.loads((self.workspace / "last-run.json").read_text(encoding="utf-8"))
        self.assertFalse(report["catalogPromoted"])
        self.assertEqual(report["preservedCatalogSnapshotId"], initial_id)
        self.assertEqual(len(report["advancedModules"]), 1)
        current = large_project.status(str(self.workspace))
        self.assertEqual(current["freshness"], "stale")
        self.assertIn("child_advanced", {item["catalogBinding"] for item in current["modules"]})
        pinned = large_project.query(str(self.workspace), "AdvancedOnly", limit=5)
        self.assertEqual(pinned["returned"], 0)

    def test_query_is_globally_bounded_and_uses_pinned_module_provenance(self) -> None:
        initial = self.initialize()
        result = large_project.query(str(self.workspace), "shared", limit=1)
        pins = {item["moduleId"]: item["snapshotId"] for item in initial["modules"]}

        self.assertEqual(result["returned"], 1)
        self.assertGreaterEqual(result["moduleMatchOccurrences"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["modules"]), 2)
        match = result["matches"][0]
        self.assertEqual(match["moduleSnapshotId"], pins[match["moduleId"]])
        self.assertIn(match["moduleRoot"], self.roots)
        self.assertIn("node", match)

    def test_modules_are_paginated_metadata_only_and_do_not_claim_source_freshness(self) -> None:
        initial = self.initialize()
        (self.repo / "services" / "python" / "changed.py").write_text(
            "def new_source_after_snapshot():\n    return 1\n", encoding="utf-8",
        )
        before = tree_digest(self.workspace)
        with mock.patch.object(companion, "_snapshot_view", side_effect=AssertionError("ontology loaded")), \
                mock.patch.object(companion, "_manifest", side_effect=AssertionError("source scanned")):
            first = large_project.modules(str(self.workspace), limit=1)
            second = large_project.modules(str(self.workspace), offset=first["nextOffset"], limit=1)
            filtered = large_project.modules(str(self.workspace), term="PYTHON", limit=1)
            empty = large_project.modules(str(self.workspace), offset=2, limit=1)
        self.assertEqual(tree_digest(self.workspace), before)
        self.assertEqual(first["catalogSnapshotId"], initial["catalogSnapshotId"])
        self.assertTrue(first["metadataOnly"])
        self.assertTrue(first["truncated"])
        self.assertEqual(first["moduleCount"], 2)
        self.assertEqual(first["modules"][0]["root"], self.roots[0])
        self.assertEqual(second["modules"][0]["root"], self.roots[1])
        self.assertFalse(second["truncated"])
        self.assertIsNone(second["nextOffset"])
        self.assertEqual(filtered["matchedModuleCount"], 1)
        self.assertEqual(filtered["modules"][0]["root"], self.roots[1])
        self.assertEqual(filtered["modules"][0]["sourceFileCount"], 1)
        self.assertGreater(filtered["modules"][0]["supportedSourceBytes"], 0)
        self.assertEqual(filtered["freshness"], "pinned_snapshot")
        self.assertIn("not checked", filtered["freshnessCaveat"])
        self.assertEqual(empty["returned"], 0)
        self.assertIsNone(empty["nextOffset"])

    def test_query_pages_across_modules_without_duplicates_and_selects_exact_roots(self) -> None:
        initial = self.initialize()
        before = tree_digest(self.workspace)
        complete = large_project.query(str(self.workspace), "shared", 200)
        assembled = []
        offset = 0
        while True:
            page = large_project.query(str(self.workspace), "shared", 1, offset=offset)
            self.assertEqual(page["catalogSnapshotId"], initial["catalogSnapshotId"])
            self.assertEqual(page["returned"], 1)
            self.assertEqual(page["offset"], offset)
            self.assertLessEqual(len(page["matches"]), 1)
            assembled.extend(page["matches"])
            if page["nextOffset"] is None:
                self.assertFalse(page["truncated"])
                break
            self.assertGreater(page["nextOffset"], offset)
            offset = page["nextOffset"]
        self.assertEqual(assembled, complete["matches"])
        self.assertEqual(len({(item["moduleId"], item["node"]["id"]) for item in assembled}), len(assembled))
        with mock.patch.object(companion, "query", wraps=companion.query) as child_query:
            selected = large_project.query(
                str(self.workspace), "shared", 20, module_roots=[self.roots[1]],
            )
        self.assertEqual(child_query.call_count, 1)
        self.assertEqual(selected["selectedModuleRoots"], [self.roots[1]])
        self.assertEqual(selected["moduleCount"], 1)
        self.assertTrue(all(item["moduleRoot"] == self.roots[1] for item in selected["matches"]))
        self.assertEqual(selected["moduleMatchOccurrences"], complete["modules"][1]["matchOccurrences"])
        beyond = large_project.query(str(self.workspace), "shared", 1, offset=core.MAX_GRAPH_NODES + 1)
        self.assertEqual(beyond["returned"], 0)
        self.assertFalse(beyond["truncated"])
        self.assertIsNone(beyond["nextOffset"])
        self.assertEqual(tree_digest(self.workspace), before)

    def test_retrieval_rejects_invalid_pages_and_nonconfigured_module_paths(self) -> None:
        self.initialize()
        for options in ({"offset": -1}, {"offset": True}, {"limit": 0}, {"limit": True},
                        {"offset": large_project.MAX_MODULES * core.MAX_GRAPH_NODES + 1}):
            with self.subTest(options=options), self.assertRaises(core.OntologyError):
                large_project.query(str(self.workspace), "shared", **options)
        for roots in (["services"], ["services/java/../python"], ["../outside"],
                      [str(self.repo / "services" / "java")], ["services/java/"], [],
                      [self.roots[0], self.roots[0]], self.roots[0], [None]):
            with self.subTest(roots=roots), mock.patch.object(companion, "query") as child_query:
                with self.assertRaises(core.OntologyError):
                    large_project.query(str(self.workspace), "shared", module_roots=roots)
                child_query.assert_not_called()
        for options in ({"offset": -1}, {"offset": True}, {"offset": 129}, {"limit": 201}, {"term": None}):
            with self.subTest(options=options), self.assertRaises(core.OntologyError):
                large_project.modules(str(self.workspace), **options)

    def test_all_retrieval_routes_can_pin_an_old_catalog_across_refresh(self) -> None:
        initial = self.initialize()
        pin = initial["catalogSnapshotId"]
        old = large_project.query(str(self.workspace), "shared", 200, catalog_snapshot=pin)
        first = large_project.query(str(self.workspace), "shared", 1, catalog_snapshot=pin)
        (self.repo / "services" / "python" / "shared_new.py").write_text(
            "def shared_new_entry():\n    return 1\n", encoding="utf-8",
        )
        refreshed = large_project.sync(str(self.workspace))
        self.assertNotEqual(refreshed["catalogSnapshotId"], pin)
        second = large_project.query(
            str(self.workspace), "shared", 200, offset=first["nextOffset"], catalog_snapshot=pin,
        )
        self.assertEqual(first["matches"] + second["matches"], old["matches"])
        self.assertEqual(second["catalogSnapshotId"], pin)
        current = large_project.query(str(self.workspace), "shared", 200)
        self.assertGreater(current["moduleMatchOccurrences"], old["moduleMatchOccurrences"])
        old_modules = large_project.modules(str(self.workspace), catalog_snapshot=pin)
        self.assertEqual(old_modules["modules"][1]["sourceFileCount"], 1)
        self.assertEqual(large_project.modules(str(self.workspace))["modules"][1]["sourceFileCount"], 2)
        old_impact = large_project.impact(
            str(self.workspace), self.roots[1], "shared_new_entry", catalog_snapshot=pin,
        )
        self.assertEqual(old_impact["status"], "not_found")
        self.assertEqual(old_impact["catalogSnapshotId"], pin)
        self.assertEqual(
            large_project.impact(str(self.workspace), self.roots[1], "shared_new_entry")["status"], "ok",
        )
        for invalid in ("../catalog", "current", "", [], 1):
            with self.subTest(snapshot=invalid), self.assertRaises(companion.CompanionError):
                large_project.modules(str(self.workspace), catalog_snapshot=invalid)

    def test_impact_is_bounded_read_only_and_keeps_catalog_pin_after_child_advances(self) -> None:
        source = self.repo / "services" / "python" / "shared.py"
        source.write_text(
            "def leaf():\n    return 1\n\ndef branch():\n    return leaf()\n\ndef entry():\n    return branch()\n",
            encoding="utf-8",
        )
        initial = self.initialize()
        pinned = initial["modules"][1]
        child = self.workspace / "modules" / pinned["moduleId"]
        source.write_text(source.read_text(encoding="utf-8") + "\ndef advanced_only():\n    return entry()\n",
                          encoding="utf-8")
        advanced = companion.sync(str(child))
        self.assertNotEqual(advanced["snapshotId"], pinned["snapshotId"])
        before = tree_digest(self.workspace)
        with mock.patch.object(companion, "impact", wraps=companion.impact) as child_impact:
            result = large_project.impact(
                str(self.workspace), self.roots[1], "entry", depth=2, limit=1, direction="outgoing",
            )
        self.assertEqual(child_impact.call_count, 1)
        self.assertEqual(child_impact.call_args.kwargs["snapshot"], pinned["snapshotId"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["impact_count"], 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["moduleSnapshotId"], pinned["snapshotId"])
        self.assertEqual(result["moduleWorkspaceId"], pinned["workspaceId"])
        self.assertEqual(result["workspaceId"], initial["workspaceId"])
        self.assertEqual(result["crossModuleResolution"], "unsupported")
        self.assertEqual(result["freshness"], "pinned_snapshot")
        missing = large_project.impact(str(self.workspace), self.roots[1], "advanced_only")
        self.assertEqual(missing["status"], "not_found")
        self.assertEqual(tree_digest(self.workspace), before)
        for root in ("services", "../outside", str(child), "services/python/", None):
            with self.subTest(root=root), mock.patch.object(companion, "impact") as child_impact:
                with self.assertRaises(core.OntologyError):
                    large_project.impact(str(self.workspace), root, "entry")
                child_impact.assert_not_called()
        for options in ({"depth": 0}, {"depth": True}, {"limit": 0}, {"limit": 2001},
                        {"direction": "sideways"}, {"direction": []}, {"symbol": ""}):
            call = {"workspace_path": str(self.workspace), "module_root": self.roots[1], "symbol": "entry"}
            call.update(options)
            with self.subTest(options=options), self.assertRaises(core.OntologyError):
                large_project.impact(**call)

    def test_rejects_duplicate_overlap_traversal_excluded_links_and_workspace_overlap(self) -> None:
        invalid_sets = [
            ["services/java", "services/java"],
            ["services", "services/java"],
            ["../private-repository"],
            ["."],
        ]
        (self.repo / "build").mkdir()
        invalid_sets.append(["build"])
        outside = self.base / "outside"
        outside.mkdir()
        link = self.repo / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            link = None
        if link is not None:
            invalid_sets.append(["linked"])
        for roots in invalid_sets:
            with self.subTest(roots=roots), self.assertRaises(core.OntologyError):
                large_project.preflight(str(self.repo), roots)
        with self.assertRaises(companion.CompanionError):
            large_project.initialize(
                str(self.repo),
                str(self.repo / "catalog"),
                authorized=True,
                module_roots=self.roots,
            )

    def test_linked_child_and_tampered_config_fail_closed(self) -> None:
        result = self.initialize()
        module = result["modules"][0]
        child = self.workspace / "modules" / module["moduleId"]
        moved = self.base / "moved-child"
        child.rename(moved)
        try:
            child.symlink_to(moved, target_is_directory=True)
        except OSError as exc:
            self.skipTest("Directory symlinks unavailable: %s" % exc)
        with self.assertRaises(companion.CompanionError):
            large_project.status(str(self.workspace))

    def test_child_repository_substitution_is_rejected_before_sync(self) -> None:
        result = self.initialize()
        module = result["modules"][0]
        child = self.workspace / "modules" / module["moduleId"]
        alternate = self.base / "alternate-repository"
        (alternate / module["root"]).mkdir(parents=True)
        config_path = child / "companion.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repositoryRoot"] = str(alternate)
        companion._atomic_json(config_path, config)
        with mock.patch.object(large_project.companion, "sync") as child_sync:
            with self.assertRaisesRegex(companion.CompanionError, "binding"):
                large_project.sync(str(self.workspace))
        child_sync.assert_not_called()

    def test_status_marks_pinned_analyzer_or_companion_version_stale(self) -> None:
        self.initialize()
        with mock.patch.object(core, "PLUGIN_VERSION", "next-analyzer"):
            current = large_project.status(str(self.workspace))
        self.assertEqual(current["freshness"], "stale")
        self.assertEqual(current["pipelineStatus"], "refresh_required")
        self.assertIn("stale", {item["versionFreshness"] for item in current["modules"]})

    def test_registration_failure_removes_only_children_created_by_this_init(self) -> None:
        unrelated = {
            "id": "unrelated",
            "label": "Unrelated",
            "workspace": str(self.base / "unrelated"),
            "registeredAt": "earlier",
        }
        companion._atomic_json(
            companion._registry_path(),
            {"schemaVersion": 1, "workspaces": [unrelated]},
        )
        real_atomic = companion._atomic_json

        def fail_registry(path, value, mode=0o600):
            if Path(path) == companion._registry_path():
                raise companion.CompanionError("synthetic registry failure")
            return real_atomic(path, value, mode)

        with mock.patch.object(large_project.companion, "_atomic_json", side_effect=fail_registry):
            with self.assertRaisesRegex(companion.CompanionError, "registry failure"):
                self.initialize()
        self.assertFalse(self.workspace.exists())
        self.assertEqual(companion._load_registry()["workspaces"], [unrelated])

    def test_pre_promotion_os_error_preserves_pointer_and_reports_advanced_child(self) -> None:
        initial = self.initialize()
        initial_id = initial["catalogSnapshotId"]
        (self.repo / "services" / "java" / "Changed.java").write_text(
            "package sample; public class Changed {}\n",
            encoding="utf-8",
        )
        with mock.patch.object(
            large_project,
            "_promote_catalog",
            side_effect=OSError("synthetic promotion failure"),
        ):
            with self.assertRaisesRegex(companion.CompanionError, "prior catalog remains current"):
                large_project.sync(str(self.workspace))
        self.assertEqual(self.state()["currentCatalogSnapshot"], initial_id)
        report = json.loads((self.workspace / "last-run.json").read_text(encoding="utf-8"))
        self.assertFalse(report["catalogPromoted"])
        self.assertEqual(report["preservedCatalogSnapshotId"], initial_id)
        self.assertEqual(len(report["advancedModules"]), 1)

    def test_post_promotion_report_failure_does_not_claim_catalog_rollback(self) -> None:
        initial = self.initialize()
        (self.repo / "services" / "python" / "changed.py").write_text(
            "def report_failure_change():\n    return 1\n",
            encoding="utf-8",
        )
        real_atomic = companion._atomic_json

        def fail_last_run(path, value, mode=0o600):
            if Path(path).name == "last-run.json":
                raise OSError("synthetic report failure")
            return real_atomic(path, value, mode)

        with mock.patch.object(large_project.companion, "_atomic_json", side_effect=fail_last_run):
            result = large_project.sync(str(self.workspace))
        self.assertEqual(result["status"], "promoted")
        self.assertIn("reportWarning", result)
        self.assertNotEqual(result["catalogSnapshotId"], initial["catalogSnapshotId"])
        self.assertEqual(self.state()["currentCatalogSnapshot"], result["catalogSnapshotId"])

    def test_module_file_limit_is_not_relaxed_and_failed_init_registers_nothing(self) -> None:
        (self.repo / "services" / "java" / "Second.java").write_text(
            "package sample; public class Second {}\n",
            encoding="utf-8",
        )
        with mock.patch.object(core, "MAX_SOURCE_FILES", 1):
            with self.assertRaises(core.OntologyError):
                self.initialize()
        self.assertFalse(self.workspace.exists())
        registry = companion._load_registry()
        self.assertEqual(registry["workspaces"], [])

    def test_partition_allows_aggregate_over_total_byte_limit_but_not_large_leaf(self) -> None:
        java_size = (self.repo / "services" / "java" / "Shared.java").stat().st_size
        python_size = (self.repo / "services" / "python" / "shared.py").stat().st_size
        per_module_limit = max(java_size, python_size) + 1
        self.assertLess(per_module_limit, java_size + python_size)

        with mock.patch.object(core, "MAX_TOTAL_SOURCE_BYTES", per_module_limit):
            with self.assertRaises(core.OntologyError):
                core.preflight_document(self.repo)
            result = self.initialize()
            self.assertEqual(result["status"], "promoted")

            (self.repo / "services" / "java" / "TooMuch.java").write_text(
                "package sample; public class TooMuch {}\n",
                encoding="utf-8",
            )
            leaf_workspace = self.base / "large-leaf-workspace"
            with self.assertRaises(core.OntologyError):
                large_project.initialize(
                    str(self.repo),
                    str(leaf_workspace),
                    authorized=True,
                    module_roots=["services/java"],
                )
            self.assertFalse(leaf_workspace.exists())


if __name__ == "__main__":
    unittest.main()
