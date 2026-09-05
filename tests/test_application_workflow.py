from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/apply-code-ontology/scripts/apply_workflow.py"
COMPANION = ROOT / "skills/manage-code-ontology/scripts/companion.py"
SPEC = importlib.util.spec_from_file_location("application_workflow_under_test", HELPER)
assert SPEC is not None and SPEC.loader is not None
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)

CLI_CAPABILITIES = {"code": {"installed": True, "skill_exposed": True, "verified_cli": True}}


def digest_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file() and not item.is_symlink():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()


class ApplicationPlanningTests(unittest.TestCase):
    def test_all_eight_capability_subsets_select_only_observed_execution_routes(self) -> None:
        for flags in itertools.product((False, True), repeat=3):
            with self.subTest(flags=flags):
                capabilities = {
                    product: {"installed": True, "skill_exposed": True, "mcp_exposed": flag}
                    for product, flag in zip(workflow.PRODUCTS, flags)
                }
                expected = [product for product, flag in zip(workflow.PRODUCTS, flags) if flag]
                result = workflow.plan(capabilities)
                self.assertEqual(result["selectedProducts"], expected)
                self.assertEqual(result["availableCount"], sum(flags))
                self.assertEqual(result["activationStatus"], "NOT_EXECUTED")
                self.assertFalse(result["executionPerformed"])

    def test_installation_or_skill_discovery_is_not_execution_availability(self) -> None:
        result = workflow.plan({product: {"installed": True, "skill_exposed": True}
                                for product in workflow.PRODUCTS})
        self.assertEqual(result["availableCount"], 0)
        self.assertEqual(result["selectedProducts"], [])

    def test_explicit_unavailable_product_does_not_silently_fallback(self) -> None:
        result = workflow.plan(CLI_CAPABILITIES, explicit_product="context")
        self.assertEqual(result["selectedProducts"], ["context"])
        self.assertEqual(result["routes"][0]["route"], "unavailable")
        self.assertEqual(result["activationStatus"], "NOT_EXECUTED")

    def test_explicit_choice_overrides_three_available_products(self) -> None:
        capabilities = {product: {"skill_exposed": True, "verified_cli": True}
                        for product in workflow.PRODUCTS}
        result = workflow.plan(capabilities, explicit_product="contracts")
        self.assertEqual(result["selectedProducts"], ["contracts"])
        self.assertEqual(result["routes"][0]["route"], "host_cli_handoff")

    def test_already_applied_session_observation_avoids_duplicate_application(self) -> None:
        result = workflow.plan(CLI_CAPABILITIES, already_applied=["code"])
        self.assertEqual(result["routes"][0]["route"], "already_applied")
        self.assertEqual(result["routes"][0]["alreadyAppliedBasis"], "host_session_report")
        self.assertEqual(result["activationStatus"], "NOT_EXECUTED")

    def test_mcp_handoff_does_not_execute_or_claim_application(self) -> None:
        capabilities = {"code": {"mcp_exposed": True, "verified_cli": True}}
        with mock.patch.object(workflow, "_load_companion", side_effect=AssertionError("must not import")):
            result = workflow.run_code(capabilities, "unused", term="order")
            checked = workflow.checkpoint(capabilities, "unused", ["order.py"], sync_authorized=True)
        for item in (result, checked):
            self.assertEqual(item["status"], "handoff_required")
            self.assertEqual(item["activationStatus"], "NOT_EXECUTED")
            self.assertFalse(item["executionPerformed"])
            self.assertEqual(item["operations"], [])
        self.assertEqual(checked["syncAttempts"], 0)

    def test_unknown_fields_and_nonboolean_observations_are_rejected(self) -> None:
        for value in ({"code": {"mcp_exposed": "true"}}, {"code": {"cli_path": "/tmp/evil.py"}},
                      {"unrelated": {}}, [], {"code": {"installed": 1}}):
            with self.subTest(value=value), self.assertRaises(workflow.ApplicationError):
                workflow.plan(value)

    def test_direct_cli_observation_does_not_require_installed_or_skill_exposed(self) -> None:
        result = workflow.plan({"code": {"verified_cli": True}})
        self.assertEqual(result["selectedProducts"], ["code"])
        self.assertEqual(result["routes"][0]["route"], "verified_sibling_cli")
        self.assertFalse(result["executionPerformed"])

    def test_optional_execution_route_without_exposed_workflow_remains_pending(self) -> None:
        for product in ("context", "contracts"):
            for route in ("mcp_exposed", "verified_cli"):
                with self.subTest(product=product, route=route):
                    result = workflow.plan({product: {route: True}}, explicit_product=product)
                    self.assertEqual(result["availableCount"], 0)
                    self.assertEqual(result["routes"][0]["route"], "unavailable")
                    self.assertEqual(result["routes"][0]["reason"], "optional_product_workflow_not_exposed")
                    self.assertFalse(result["executionPerformed"])


class ApplicationExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repository"
        self.repo.mkdir()
        self.source = self.repo / "orders.py"
        self.source.write_text(
            "def normalize(value):\n    return value.strip()\n\n"
            "def deliver(value):\n    return normalize(value)\n\n"
            "raise RuntimeError('target code must never execute')\n", encoding="utf-8")
        self.workspace = self.base / "ontology-workspace"
        self.data_home = self.base / "ontology-data"
        self.scope_file = self.repo / "AGENTS.md"
        self.scope_file.write_text("Fixture scope must remain session-only.\n", encoding="utf-8")
        self.environment = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.data_home)})
        self.environment.start()
        self.companion = workflow._load_companion()
        self.initial = self.companion.initialize(str(self.repo), str(self.workspace), authorized=True, label="apply-fixture")

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> tuple[subprocess.CompletedProcess, dict]:
        completed = subprocess.run(
            [sys.executable, "-B", str(HELPER), *arguments], cwd=self.repo,
            env=os.environ.copy(), capture_output=True, text=True, timeout=30,
        )
        return completed, json.loads(completed.stdout)

    def test_real_cli_executes_status_query_and_impact_pinned_without_mcp_or_target_execution(self) -> None:
        before = digest_tree(self.base)
        completed, result = self.run_cli(
            "run-code", "--capabilities", json.dumps(CLI_CAPABILITIES), "--workspace", str(self.workspace),
            "--term", "deliver", "--symbol", "deliver")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual(result["activationStatus"], "PASS")
        self.assertTrue(result["executionPerformed"])
        self.assertEqual(result["implementationVerified"], "same_plugin_sibling")
        self.assertEqual(result["snapshotId"], self.initial["snapshotId"])
        self.assertEqual([item["operation"] for item in result["operations"]],
                         ["status", "query", "impact", "status_after_reads"])
        for item in result["operations"]:
            self.assertEqual(item["result"]["snapshotId"], self.initial["snapshotId"])
        self.assertEqual(digest_tree(self.base), before)
        self.assertEqual(result["scope"]["application"], "session_only")
        self.assertFalse(result["scope"]["targetCodeExecuted"])
        self.assertFalse(result["scope"]["globalConfigurationChanged"])
        self.assertFalse(result["scope"]["agentsFilesChanged"])

    def test_real_companion_cli_initialization_and_helper_execution(self) -> None:
        alternate = self.base / "cli-initialized-workspace"
        completed = subprocess.run(
            [sys.executable, "-B", str(COMPANION), "init", "--repo", str(self.repo),
             "--workspace", str(alternate), "--authorized"],
            capture_output=True, text=True, timeout=30, env=os.environ.copy())
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        run, result = self.run_cli("run-code", "--capabilities", json.dumps(CLI_CAPABILITIES),
                                   "--workspace", str(alternate), "--term", "normalize")
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertEqual(result["activationStatus"], "PASS")

    def test_stale_reads_are_executed_but_not_activation_pass(self) -> None:
        self.source.write_text(self.source.read_text() + "\ndef added():\n    return 1\n")
        result = workflow.run_code(CLI_CAPABILITIES, str(self.workspace), term="deliver")
        self.assertTrue(result["executionPerformed"])
        self.assertEqual(result["activationStatus"], "INCOMPLETE")
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["scope"]["workspaceWrites"], "none")

    def test_explicit_historical_snapshot_stays_pinned_and_cannot_claim_current(self) -> None:
        self.source.write_text(self.source.read_text() + "\ndef added():\n    return 1\n")
        self.companion.sync(str(self.workspace))
        result = workflow.run_code(CLI_CAPABILITIES, str(self.workspace), term="deliver", snapshot=self.initial["snapshotId"])
        self.assertEqual(result["snapshotId"], self.initial["snapshotId"])
        query = next(item for item in result["operations"] if item["operation"] == "query")
        self.assertEqual(query["result"]["snapshotId"], self.initial["snapshotId"])
        self.assertEqual(result["activationStatus"], "INCOMPLETE")

    def test_missing_term_and_ambiguous_or_missing_symbol_do_not_pass(self) -> None:
        query = workflow.run_code(CLI_CAPABILITIES, str(self.workspace), term="absent_symbol_098765")
        impact = workflow.run_code(CLI_CAPABILITIES, str(self.workspace), symbol="absent_symbol_098765")
        self.assertEqual(query["activationStatus"], "INCOMPLETE")
        self.assertEqual(impact["activationStatus"], "INCOMPLETE")
        with self.assertRaises(workflow.ApplicationError):
            workflow.run_code(CLI_CAPABILITIES, str(self.workspace))

    def test_no_sync_authorization_preserves_repository_workspace_and_registry_bytes(self) -> None:
        self.source.write_text(self.source.read_text() + "\ndef added():\n    return 1\n")
        before = digest_tree(self.base)
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py"])
        self.assertEqual(result["syncAttempts"], 0)
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(digest_tree(self.base), before)

    def test_authorized_sync_happens_once_then_rechecks_and_preserves_session_scope(self) -> None:
        self.source.write_text(self.source.read_text() + "\ndef added():\n    return 1\n")
        source_before = digest_tree(self.repo)
        with mock.patch.object(workflow, "_load_companion", return_value=self.companion), \
                mock.patch.object(self.companion, "sync", wraps=self.companion.sync) as sync:
            result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py"], sync_authorized=True)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(result["syncAttempts"], 1)
        self.assertEqual(result["checkpointStatus"], "PASS", result)
        self.assertEqual(result["activationStatus"], "NOT_EXECUTED")
        self.assertEqual(result["freshness"], "current")
        self.assertEqual(result["warningCount"], 0)
        self.assertEqual(result["scope"]["application"], "session_only")
        self.assertFalse(result["scope"]["agentsFilesChanged"])
        self.assertEqual(digest_tree(self.repo), source_before)
        repeat = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py"], sync_authorized=True)
        self.assertEqual(repeat["syncAttempts"], 0)

    def test_unsupported_only_never_syncs_or_claims_analysis_complete(self) -> None:
        (self.repo / "view.js").write_text("export const page = 1;\n")
        before = digest_tree(self.base)
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["view.js"], sync_authorized=True)
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertEqual(result["changedPaths"]["supported"], [])
        self.assertEqual(result["changedPaths"]["unsupported"], [{"path": "view.js", "reason": "unsupported_language"}])
        self.assertEqual(result["syncAttempts"], 0)
        self.assertEqual(digest_tree(self.base), before)

    def test_mixed_changes_sync_supported_scope_once_but_remain_incomplete(self) -> None:
        self.source.write_text(self.source.read_text() + "\ndef added():\n    return 1\n")
        (self.repo / "view.html").write_text("<main>Changed</main>\n")
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py", "view.html"], sync_authorized=True)
        self.assertEqual(result["syncAttempts"], 1)
        self.assertEqual(result["freshness"], "current")
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertEqual(result["changedPaths"]["supported"], ["orders.py"])

    def test_sync_failure_is_incomplete_and_is_not_retried(self) -> None:
        self.source.write_text(self.source.read_text() + "\ndef added():\n    return 1\n")
        before = digest_tree(self.base)
        with mock.patch.object(workflow, "_load_companion", return_value=self.companion), \
                mock.patch.object(self.companion, "sync", side_effect=self.companion.CompanionError("fixture sync failure")) as sync:
            result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py"], sync_authorized=True)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(result["syncAttempts"], 1)
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertIn("fixture sync failure", " ".join(result["issues"]))
        self.assertEqual(digest_tree(self.base), before)

    def test_warning_after_refresh_prevents_checkpoint_pass(self) -> None:
        self.source.write_text("def broken(:\n")
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py"], sync_authorized=True)
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertGreater(result.get("warningCount", 0), 0)

    def test_deleted_previously_analyzed_source_is_supported_but_unknown_missing_path_is_not(self) -> None:
        spare = self.repo / "spare.py"
        spare.write_text("def spare():\n    return 1\n")
        self.companion.sync(str(self.workspace))
        spare.unlink()
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["spare.py"], sync_authorized=True)
        self.assertEqual(result["checkpointStatus"], "PASS", result)
        missing = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["missing.py"], sync_authorized=True)
        self.assertEqual(missing["checkpointStatus"], "INCOMPLETE")
        self.assertEqual(missing["syncAttempts"], 0)

    def test_excluded_sensitive_and_symlink_sources_are_not_reported_analyzed(self) -> None:
        try:
            (self.repo / "alias.py").symlink_to(self.source)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Host cannot create fixture symlinks: {exc}")
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace),
                                     ["alias.py", "secrets.py", "build/generated.py"], sync_authorized=True)
        self.assertEqual(result["changedPaths"]["supported"], [])
        self.assertEqual({item["reason"] for item in result["changedPaths"]["unsupported"]},
                         {"filesystem_link_excluded", "sensitive_filename_excluded", "excluded_directory"})
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertEqual(result["syncAttempts"], 0)

    def test_oversized_supported_extension_is_not_mistaken_for_analyzed_source(self) -> None:
        oversized = self.repo / "oversized.py"
        oversized.write_bytes(b"#" * (self.companion.core.MAX_SOURCE_BYTES + 1))
        current = self.companion.status(str(self.workspace))
        self.assertEqual(current["freshness"], "current")
        self.assertEqual(current["counts"]["warnings"], 0)
        before = digest_tree(self.base)
        result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["oversized.py"], sync_authorized=True)
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertEqual(result["changedPaths"]["supported"], [])
        self.assertEqual(result["changedPaths"]["unsupported"],
                         [{"path": "oversized.py", "reason": "source_size_limit_exceeded"}])
        self.assertEqual(result["syncAttempts"], 0)
        self.assertEqual(digest_tree(self.base), before)

    def test_final_manifest_omission_prevents_checkpoint_pass_even_with_current_status(self) -> None:
        original_read = self.companion._read_json
        manifest_reads = 0

        def omit_final_path(path, label, *args, **kwargs):
            nonlocal manifest_reads
            value = original_read(path, label, *args, **kwargs)
            if label == "Source manifest":
                manifest_reads += 1
                if manifest_reads > 1:
                    value = {**value, "files": []}
            return value

        with mock.patch.object(workflow, "_load_companion", return_value=self.companion), \
                mock.patch.object(self.companion, "_read_json", side_effect=omit_final_path):
            result = workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), ["orders.py"])
        self.assertEqual(result["freshness"], "current")
        self.assertEqual(result["checkpointStatus"], "INCOMPLETE")
        self.assertTrue(any("final snapshot" in issue for issue in result["issues"]))

    def test_path_escape_and_scope_escalation_inputs_are_rejected_before_execution(self) -> None:
        before = digest_tree(self.base)
        for paths in (["../outside.py"], ["/absolute.py"], ["a/../b.py"], ["C:\\other.py"],
                      ["a//b.py"], ["./orders.py"], [], ["orders.py\n"]):
            with self.subTest(paths=paths), self.assertRaises(workflow.ApplicationError):
                workflow.checkpoint(CLI_CAPABILITIES, str(self.workspace), paths, sync_authorized=True)
        completed = subprocess.run(
            [sys.executable, "-B", str(HELPER), "plan", "--capabilities", "{}", "--scope", "global"],
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(digest_tree(self.base), before)

    def test_loaded_foreign_core_is_not_used_and_is_restored(self) -> None:
        impostor = types.ModuleType("code_ontology_core")
        with mock.patch.dict(sys.modules, {"code_ontology_core": impostor}):
            loaded = workflow._load_companion()
            self.assertIsNot(loaded.core, impostor)
            self.assertEqual(Path(loaded.core.__file__).resolve(),
                             ROOT / "skills/manage-code-ontology/scripts/code_ontology_core.py")
            self.assertIs(sys.modules["code_ontology_core"], impostor)

    def test_missing_or_linked_sibling_is_not_replaced_with_target_or_path_cli(self) -> None:
        isolated = self.base / "isolated-plugin"
        helper = isolated / "skills/apply-code-ontology/scripts/apply_workflow.py"
        helper.parent.mkdir(parents=True)
        shutil.copyfile(HELPER, helper)
        manifest = isolated / ".codex-plugin/plugin.json"
        manifest.parent.mkdir()
        manifest.write_text('{"name":"code-ontology-companion"}')
        with mock.patch.object(workflow, "__file__", str(helper)):
            result = workflow.run_code(CLI_CAPABILITIES, str(self.workspace), term="deliver")
        self.assertFalse(result["executionPerformed"])
        self.assertEqual(result["activationStatus"], "INCOMPLETE")
        core = isolated / "skills/manage-code-ontology/scripts/code_ontology_core.py"
        core.parent.mkdir(parents=True)
        try:
            core.symlink_to(ROOT / "skills/manage-code-ontology/scripts/code_ontology_core.py")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Host cannot create fixture symlinks: {exc}")
        with mock.patch.object(workflow, "__file__", str(helper)):
            result = workflow.run_code(CLI_CAPABILITIES, str(self.workspace), term="deliver")
        self.assertFalse(result["executionPerformed"])
        self.assertIn("links", " ".join(result["issues"]))


if __name__ == "__main__":
    unittest.main()
