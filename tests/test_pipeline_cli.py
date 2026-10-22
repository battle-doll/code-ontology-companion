"""Actual CLI/MCP subprocess workflow; only synthetic local workspaces."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import privacy_guard


class PipelineCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "synthetic-source"
        self.repo.mkdir()
        self.workspace = self.base / "ontology"
        self.registry = self.base / "registry"
        self.profile = self.base / "privacy.json"
        value = privacy_guard.build_profile(["Synthetic Private Person"], ["synthetic@privacy-fixture.test"], key=b"c" * 32)
        self.profile.write_text(json.dumps(value), encoding="utf-8"); self.profile.chmod(0o600)
        self.env = {**os.environ, "CODE_ONTOLOGY_HOME": str(self.registry), "CODE_ONTOLOGY_PRINCIPAL": "local-owner",
                    privacy_guard.PROFILE_ENV: str(self.profile), "PYTHONUTF8": "1"}
        (self.repo / "order.py").write_text("def order_allowed(active: bool, blocked: bool) -> bool:\n    return active and not blocked\n", encoding="utf-8")

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPTS / "companion.py"), *map(str, args)],
                                cwd=self.base, env=self.env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, expected, "Synthetic CLI return code mismatch")
        return json.loads(result.stdout) if expected == 0 else result

    def analyze(self, *extra):
        return self.cli("analyze", "--repo", self.repo, "--workspace", self.workspace, "--authorized", "--no-html", *extra)

    def mcp(self, name, arguments):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        result = subprocess.run([sys.executable, str(ROOT / "mcp/server.py")], input=json.dumps(request) + "\n",
                                cwd=self.base, env=self.env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, "Synthetic MCP process failed")
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0])["result"]

    def assert_registered_pin(self, result):
        config = json.loads((self.workspace / "pipeline.json").read_text())
        registry = json.loads((self.registry / "registry.json").read_text())
        self.assertEqual(len(registry["workspaces"]), 1)
        self.assertEqual(registry["workspaces"][0]["id"], config["workspaceId"])
        self.assertEqual(registry["workspaces"][0]["mode"], "pipeline")
        arguments = {"workspace_id": config["workspaceId"], "snapshot_id": result["snapshotId"]}
        response = self.mcp("query_policy_rules", arguments)
        self.assertFalse(response["isError"], "Pinned MCP policy read failed")
        self.assertEqual(response["structuredContent"]["snapshotId"], result["snapshotId"])
        self.assertTrue(response["structuredContent"]["data"]["rules"])
        stale = self.mcp("query_policy_rules", {**arguments, "snapshot_id": "ps-" + "0" * 32})
        self.assertTrue(stale["isError"])
        self.assertNotIn(str(self.workspace), json.dumps(stale))
        return arguments, response

    def test_large_capacity_is_explicit_bounded_and_registered_for_source_free_mcp(self):
        result = self.analyze("--capacity", "large")
        self.assertEqual(result["status"], "created")
        config = json.loads((self.workspace / "pipeline.json").read_text())
        expected = {"max_files": 250000, "max_total_bytes": 4 * 1024 ** 3, "max_records": 5000000,
                    "max_output_bytes": 8 * 1024 ** 3, "max_run_seconds": 7200,
                    "max_source_bytes": 2 * 1024 ** 2, "max_ast_nodes": 200000, "workers": 1, "max_policy_rules": 10000}
        for key, value in expected.items(): self.assertEqual(config["budgets"][key], value)
        self.assertFalse((self.workspace / "html").exists())
        arguments, before = self.assert_registered_pin(result)
        shutil.rmtree(self.repo)
        self.assertEqual(self.mcp("query_policy_rules", arguments), before)

    def test_default_capacity_remains_standard_and_never_executes_shell_source(self):
        (self.repo / "build.sh").write_text("#!/bin/sh\ntouch synthetic-executed-marker\nmalicious() { touch synthetic-executed-marker; }\nmalicious\n", encoding="utf-8")
        result = self.analyze()
        config = json.loads((self.workspace / "pipeline.json").read_text())
        for key, value in {"max_files": 25000, "max_total_bytes": 512 * 1024 ** 2, "max_records": 500000,
                           "max_output_bytes": 1024 ** 3, "max_run_seconds": 600}.items():
            self.assertEqual(config["budgets"][key], value)
        self.assertFalse((self.base / "synthetic-executed-marker").exists())
        self.assertFalse((self.repo / "synthetic-executed-marker").exists())
        self.assert_registered_pin(result)

    def test_missing_authorization_and_invalid_capacity_fail_before_writes(self):
        self.cli("analyze", "--repo", self.repo, "--workspace", self.workspace, "--no-html", expected=2)
        self.assertFalse(self.workspace.exists()); self.assertFalse(self.registry.exists())
        self.cli("analyze", "--repo", self.repo, "--workspace", self.workspace, "--authorized", "--no-html", "--capacity", "unbounded", expected=2)
        self.assertFalse(self.workspace.exists()); self.assertFalse(self.registry.exists())

    def test_initial_process_crash_keeps_acl_then_recovery_registers_completed_snapshot_once(self):
        # Run the real companion CLI entry point in a child with one deterministic
        # crash boundary. os._exit bypasses finally blocks as an actual crash does.
        runner = """import os, sys
sys.path.insert(0, sys.argv.pop(1))
import companion, pipeline_store
def checkpoint(stage):
    if stage == 'after_prepared_receipt':
        os._exit(79)
pipeline_store._checkpoint = checkpoint
raise SystemExit(companion.main(sys.argv[1:]))
"""
        result = subprocess.run([sys.executable, "-c", runner, str(SCRIPTS), "analyze", "--repo", str(self.repo),
                                 "--workspace", str(self.workspace), "--authorized", "--no-html", "--capacity", "large"],
                                cwd=self.base, env=self.env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 79, "Synthetic crash boundary was not reached")
        acl = json.loads((self.workspace / "access.json").read_text())
        self.assertIn("manage_access", acl["principals"]["local-owner"]["actions"])
        self.assertFalse((self.registry / "registry.json").exists())
        receipts = [json.loads(path.read_text()) for path in (self.workspace / ".jobs").glob("*/receipt.json")]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["status"], "prepared")
        recovered = self.cli("pipeline-recover", "--workspace", self.workspace)
        self.assertEqual(recovered["recoveredRunCount"], 1)
        self.assertEqual(recovered["snapshotId"], receipts[0]["snapshotId"])
        self.assert_registered_pin(recovered)
        repeated = self.cli("pipeline-recover", "--workspace", self.workspace)
        self.assertEqual(repeated["recoveredRunCount"], 0)
        self.assertEqual(repeated["snapshotId"], recovered["snapshotId"])
        registry = json.loads((self.registry / "registry.json").read_text())
        self.assertEqual(len(registry["workspaces"]), 1)
        ledger = json.loads((self.workspace / "ledger.json").read_text())["events"]
        self.assertEqual(len(ledger), 1)


if __name__ == "__main__":
    unittest.main()
