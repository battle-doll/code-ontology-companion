from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import companion  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample-app"
MCP_SERVER = ROOT / "mcp" / "server.py"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        shutil.copytree(FIXTURE, self.repo)
        self.workspace = self.base / "workspace"
        self.data_home = self.base / "data"
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
        return companion.initialize(
            str(self.repo),
            str(self.workspace),
            authorized=True,
            label="fixture",
        )

    def write_runtime_policy_source(self, *, use_take_profit: bool = True) -> Path:
        source = self.repo / "src" / "main" / "java" / "com" / "example" / "demo" / "TradingEngine.java"
        take_profit_branch = """
        if (takeProfitPct != null && takeProfitPct.doubleValue() > 0) {
            return triggered();
        }
""" if use_take_profit else ""
        source.write_text(
            """package com.example.demo;
public class TradingEngine {
    Object evaluateExit(Object policy) {
        Integer timeStopMinutes = this.policyInt(
            policy, "strategy.exits.timeStopMinutes", null);
        boolean timedOut = timeStopMinutes != null && timeStopMinutes > 0;
        if (timedOut) {
            return triggered();
        }
        Double stopLossPct = this.policyDecimal(
            policy, "strategy.exits.stopLossPct", null);
        if (stopLossPct != null && stopLossPct.doubleValue() > 0) {
            return triggered();
        }
        Double takeProfitPct = this.policyDecimal(
            policy, "strategy.exits.takeProfitPct", null);
"""
            + take_profit_branch
            + """
        boolean trailingEnabled = this.policyBool(
            policy, "strategy.exits.trailing.enabled", false);
        Double activatePct = this.policyDecimal(
            policy, "strategy.exits.trailing.activatePct", null);
        Double trailPct = this.policyDecimal(
            policy, "strategy.exits.trailing.trailPct", null);
        if (trailingEnabled && activatePct != null && trailPct != null) {
            return triggered();
        }
        return null;
    }
}
""",
            encoding="utf-8",
        )
        return source

    def write_policy_document(
        self,
        *,
        stop_ladder: list | None = None,
        take_ladder: list | None = None,
        trailing_enabled: bool = True,
    ) -> Path:
        path = self.base / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "strategy": {
                        "exits": {
                            "stopLossPct": 1.0,
                            "stopLossLadder": stop_ladder or [],
                            "takeProfitPct": 1.5,
                            "takeProfitLadder": take_ladder or [],
                            "timeStopMinutes": 10,
                            "trailing": {
                                "enabled": trailing_enabled,
                                "activatePct": 0.35,
                                "trailPct": 0.25,
                            },
                        },
                        "dca": {},
                    }
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def test_doctor_and_preflight_are_read_only(self) -> None:
        before = tree_digest(self.repo)
        doctor = companion.doctor(str(self.repo))
        preflight = companion.preflight(str(self.repo))
        after = tree_digest(self.repo)

        self.assertEqual(before, after)
        self.assertTrue(doctor["python"]["compatible"])
        self.assertEqual(doctor["requiredDependencies"], [])
        self.assertFalse(doctor["defaults"]["localLlmRequired"])
        self.assertEqual(preflight["status"], "ready")
        self.assertFalse(self.workspace.exists())

    def test_initialize_requires_authorization_and_external_new_workspace(self) -> None:
        with self.assertRaises(companion.CompanionError):
            companion.initialize(str(self.repo), str(self.workspace), authorized=False)
        with self.assertRaises(companion.CompanionError):
            companion.initialize(
                str(self.repo),
                str(self.repo / "workspace"),
                authorized=True,
            )
        self.workspace.mkdir()
        with self.assertRaises(companion.CompanionError):
            companion.initialize(str(self.repo), str(self.workspace), authorized=True)

    def test_initialize_promotes_immutable_snapshot_without_changing_repo(self) -> None:
        before = tree_digest(self.repo)
        result = self.initialize()
        after = tree_digest(self.repo)

        self.assertEqual(before, after)
        self.assertEqual(result["status"], "promoted")
        snapshot = self.workspace / "snapshots" / result["snapshotId"]
        for name in (
            "ontology.json",
            "ontology.ttl",
            "report.md",
            "graph.html",
            "source-manifest.json",
            "snapshot.json",
        ):
            self.assertTrue((snapshot / name).is_file(), name)
        self.assertTrue((self.workspace / "lineage.jsonl").is_file())
        self.assertTrue((self.workspace / "lineage.ttl").is_file())
        self.assertNotIn(str(self.repo.resolve()), (snapshot / "ontology.json").read_text())
        registry = json.loads((self.data_home / "registry.json").read_text())
        self.assertEqual(registry["workspaces"][0]["id"], result["workspaceId"])

    def test_unchanged_sync_is_idempotent(self) -> None:
        first = self.initialize()
        second = companion.sync(str(self.workspace))
        history = companion.history(str(self.workspace))

        self.assertEqual(second["status"], "no_change")
        self.assertEqual(second["snapshotId"], first["snapshotId"])
        self.assertEqual(len(history["snapshots"]), 1)

    def test_analyzer_version_change_refreshes_unchanged_source(self) -> None:
        first = self.initialize()
        with mock.patch.object(companion.core, "PLUGIN_VERSION", "next-analyzer"):
            stale = companion.status(str(self.workspace), check_freshness=False)
            self.assertEqual("stale", stale["freshness"])
            self.assertEqual("refresh_required", stale["pipelineStatus"])
            second = companion.sync(str(self.workspace), trigger="version-change")
        self.assertEqual("promoted", second["status"])
        self.assertNotEqual(first["snapshotId"], second["snapshotId"])

    def test_runtime_binding_receipt_matches_lab_exact_contract(self) -> None:
        source = self.write_runtime_policy_source()
        policy = self.write_policy_document()
        initialized = self.initialize()
        receipt_root = self.base / "receipts"
        receipt_root.mkdir(mode=0o700)
        output = receipt_root / "time-stop.json"

        result = companion.create_runtime_effective_binding(
            str(self.workspace),
            "strategy.exits.timeStopMinutes",
            str(policy),
            str(output),
            authorized=True,
        )
        raw = output.read_bytes()
        receipt = json.loads(raw)
        snapshot = (
            self.workspace
            / "snapshots"
            / initialized["snapshotId"]
            / "ontology.json"
        )

        self.assertEqual(
            {
                "schema_version",
                "state",
                "policy_leaf",
                "runtimeEffective",
                "binding_method",
                "source_snapshot_sha256",
                "source_code_sha256",
                "ontology_snapshot_sha256",
                "ontology_edge_refs",
                "authority",
                "binding_receipt_sha256",
            },
            set(receipt),
        )
        self.assertEqual("aether.runtime-effective-ontology-binding/v1", receipt["schema_version"])
        self.assertEqual("FROZEN_RUNTIME_EFFECTIVE", receipt["state"])
        self.assertTrue(receipt["runtimeEffective"])
        self.assertEqual(
            hashlib.sha256(source.read_bytes()).hexdigest(),
            receipt["source_code_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            receipt["ontology_snapshot_sha256"],
        )
        self.assertEqual(
            sorted(set(receipt["ontology_edge_refs"])),
            receipt["ontology_edge_refs"],
        )
        self.assertTrue(
            all(
                item.startswith("urn:code-ontology:edge:sha256:")
                for item in receipt["ontology_edge_refs"]
            )
        )
        self.assertTrue(all(value is False for value in receipt["authority"].values()))
        self.assertEqual(
            {
                "candidate_generation": False,
                "candidate_gate_input": False,
                "funds_transfer": False,
                "live_write": False,
                "network_access": False,
                "order_submission": False,
                "policy_apply": False,
                "policy_approval": False,
                "promotion": False,
                "runtime_write": False,
            },
            receipt["authority"],
        )
        material = {
            key: value
            for key, value in receipt.items()
            if key != "binding_receipt_sha256"
        }
        self.assertEqual(
            hashlib.sha256(companion._json_bytes(material)).hexdigest(),
            receipt["binding_receipt_sha256"],
        )
        self.assertEqual(companion._json_bytes(receipt) + b"\n", raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result["externalSha256"])
        self.assertEqual(0o400, output.stat().st_mode & 0o777)
        self.assertEqual(1, output.stat().st_nlink)
        self.assertFalse(result["targetCodeExecuted"])
        self.assertFalse(result["networkAccess"])
        self.assertFalse(result["liveWrite"])
        self.assertEqual("observed-static", result["evidenceType"])
        self.assertIn(
            "does_not_prove_profit_causation",
            result["limitations"],
        )
        original = output.read_bytes()
        with self.assertRaisesRegex(companion.CompanionError, "already exists"):
            companion.create_runtime_effective_binding(
                str(self.workspace),
                "strategy.exits.timeStopMinutes",
                str(policy),
                str(output),
                authorized=True,
            )
        self.assertEqual(original, output.read_bytes())

    def test_runtime_binding_fails_closed_for_shadow_unused_and_stale_source(self) -> None:
        self.write_runtime_policy_source(use_take_profit=False)
        shadowed = self.write_policy_document(stop_ladder=[{"lossPct": 1.0, "allocPct": 1.0}])
        self.initialize()
        receipt_root = self.base / "receipts"
        receipt_root.mkdir(mode=0o700)

        with self.assertRaisesRegex(companion.CompanionError, "shadowed"):
            companion.create_runtime_effective_binding(
                str(self.workspace),
                "strategy.exits.stopLossPct",
                str(shadowed),
                str(receipt_root / "shadowed.json"),
                authorized=True,
            )
        with self.assertRaisesRegex(companion.CompanionError, "runtime branch"):
            companion.create_runtime_effective_binding(
                str(self.workspace),
                "strategy.exits.takeProfitPct",
                str(shadowed),
                str(receipt_root / "unused.json"),
                authorized=True,
            )

        source = next(self.repo.rglob("TradingEngine.java"))
        source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(companion.CompanionError, "stale"):
            companion.create_runtime_effective_binding(
                str(self.workspace),
                "strategy.exits.timeStopMinutes",
                str(shadowed),
                str(receipt_root / "stale.json"),
                authorized=True,
            )
        self.assertEqual([], list(receipt_root.iterdir()))

    def test_runtime_binding_fails_closed_without_posix_receipt_semantics(self) -> None:
        with mock.patch.object(companion.os, "name", "nt"):
            with self.assertRaisesRegex(
                companion.CompanionError,
                "POSIX owner and mode-0400 semantics",
            ):
                companion.create_runtime_effective_binding(
                    "unused-workspace",
                    "strategy.exits.timeStopMinutes",
                    "unused-policy",
                    "unused-output",
                    authorized=True,
                )

    def test_changed_sync_creates_snapshot_and_structural_diff(self) -> None:
        first = self.initialize()
        new_source = self.repo / "src" / "main" / "java" / "com" / "example" / "demo" / "NewService.java"
        new_source.write_text(
            "package com.example.demo;\n"
            "import org.springframework.stereotype.Service;\n"
            "@Service public class NewService { public void run() {} }\n",
            encoding="utf-8",
        )
        second = companion.sync(str(self.workspace), trigger="test")
        comparison = companion.diff(str(self.workspace))

        self.assertEqual(second["status"], "promoted")
        self.assertNotEqual(first["snapshotId"], second["snapshotId"])
        self.assertEqual(comparison["beforeSnapshotId"], first["snapshotId"])
        self.assertEqual(comparison["afterSnapshotId"], second["snapshotId"])
        self.assertGreater(comparison["counts"]["nodesAdded"], 0)
        self.assertTrue(any(item["name"] == "NewService" for item in comparison["nodesAdded"]))

    def test_failed_refresh_keeps_last_known_good_snapshot(self) -> None:
        first = self.initialize()
        with mock.patch.object(companion.core, "write_index", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                companion._create_snapshot(
                    self.workspace.resolve(),
                    json.loads((self.workspace / "companion.json").read_text()),
                    trigger="test-failure",
                    planned_manifest={"fingerprint": "different", "files": [], "skipped": {}},
                )
        state = json.loads((self.workspace / "state.json").read_text())
        self.assertEqual(state["currentSnapshot"], first["snapshotId"])
        self.assertTrue((self.workspace / "snapshots" / first["snapshotId"]).is_dir())

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_manifest_rejects_source_replaced_by_symlink_after_discovery(self) -> None:
        source = next(self.repo.rglob("*.java"))
        outside = self.base / "outside.java"
        outside.write_text("class Outside {}\n", encoding="utf-8")
        original_discover = companion.core.discover_sources

        def replace_after_discovery(repo: Path):
            sources, skipped = original_discover(repo)
            source.unlink()
            source.symlink_to(outside)
            return sources, skipped

        with mock.patch.object(
            companion.core,
            "discover_sources",
            side_effect=replace_after_discovery,
        ):
            with self.assertRaises(companion.CompanionError):
                companion._manifest(self.repo.resolve())

    def test_manifest_rejects_source_grown_after_discovery(self) -> None:
        source = next(self.repo.rglob("*.java"))
        original_discover = companion.core.discover_sources

        def grow_after_discovery(repo: Path):
            sources, skipped = original_discover(repo)
            source.write_bytes(b"x" * (companion.core.MAX_SOURCE_BYTES + 1))
            return sources, skipped

        with mock.patch.object(
            companion.core,
            "discover_sources",
            side_effect=grow_after_discovery,
        ):
            with self.assertRaises(companion.CompanionError):
                companion._manifest(self.repo.resolve())

    def test_manifest_hashes_raw_invalid_utf8_bytes(self) -> None:
        source = next(self.repo.rglob("*.java"))
        content = b"class RawBytes { /* \xff */ }\n"
        source.write_bytes(content)

        manifest = companion._manifest(self.repo.resolve())
        relative = source.relative_to(self.repo).as_posix()
        item = next(entry for entry in manifest["files"] if entry["path"] == relative)

        self.assertEqual(item["bytes"], len(content))
        self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())

    def test_policy_document_rejects_duplicate_keys_and_oversize_input(self) -> None:
        policy = self.base / "policy.json"
        policy.write_text('{"strategy":{},"strategy":{}}\n', encoding="utf-8")
        with self.assertRaisesRegex(companion.CompanionError, "duplicate object key"):
            companion._read_policy_document(policy)

        policy.write_bytes(b"x" * (companion.MAX_POLICY_DOCUMENT_BYTES + 1))
        with self.assertRaisesRegex(companion.CompanionError, "allowed size"):
            companion._read_policy_document(policy)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_lineage_append_rejects_symlink_without_touching_target(self) -> None:
        self.initialize()
        target = self.base / "outside-lineage.jsonl"
        original = b"outside\n"
        target.write_bytes(original)
        journal = self.workspace / "lineage.jsonl"
        journal.unlink()
        journal.symlink_to(target)

        with self.assertRaises(companion.CompanionError):
            companion.record(
                str(self.workspace),
                "decision",
                "Do not write through the symlink.",
                "declared",
                "SecurityBoundary",
            )

        self.assertEqual(target.read_bytes(), original)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_lineage_append_rejects_swap_between_check_and_open(self) -> None:
        self.initialize()
        target = self.base / "outside-race.jsonl"
        original = b"outside\n"
        target.write_bytes(original)
        journal = self.workspace / "lineage.jsonl"
        journal_resolved = self.workspace.resolve() / "lineage.jsonl"
        real_open = os.open
        swapped = False

        def swap_then_open(path, flags, mode=0o777):
            nonlocal swapped
            if Path(path) == journal_resolved and not swapped and flags & os.O_WRONLY:
                swapped = True
                journal.unlink()
                journal.symlink_to(target)
            return real_open(path, flags, mode)

        with mock.patch.object(companion.os, "open", side_effect=swap_then_open):
            with self.assertRaises(companion.CompanionError):
                companion.record(
                    str(self.workspace),
                    "decision",
                    "Reject the swapped journal.",
                    "declared",
                    "SecurityBoundary",
                )

        self.assertTrue(swapped)
        self.assertEqual(target.read_bytes(), original)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_runtime_receipt_publish_rejects_target_swap(self) -> None:
        receipt_root = self.base / "receipts"
        receipt_root.mkdir(mode=0o700)
        output = receipt_root / "binding.json"
        outside = self.base / "outside.json"
        original = b"outside\n"
        outside.write_bytes(original)
        real_link = os.link
        swapped = False

        def swap_then_link(source, target, *args, **kwargs):
            nonlocal swapped
            if target == output.name and not swapped:
                swapped = True
                output.symlink_to(outside)
            return real_link(source, target, *args, **kwargs)

        with mock.patch.object(companion.os, "link", side_effect=swap_then_link):
            with self.assertRaisesRegex(companion.CompanionError, "already exists"):
                companion._publish_immutable_receipt(output, b'{"safe":true}\n')

        self.assertTrue(swapped)
        self.assertTrue(output.is_symlink())
        self.assertEqual(original, outside.read_bytes())

    def test_record_preserves_evidence_class_and_exports_prov(self) -> None:
        self.initialize()
        recorded = companion.record(
            str(self.workspace),
            "decision",
            "Change declared stop-loss threshold from 2% to 3%.",
            "declared",
            "OrderPolicy",
        )
        events = companion.lineage(str(self.workspace), evidence_type="declared")
        turtle = (self.workspace / "lineage.ttl").read_text(encoding="utf-8")

        self.assertEqual(recorded["status"], "recorded")
        self.assertEqual(len(events["events"]), 1)
        self.assertEqual(events["events"][0]["evidenceType"], "declared")
        self.assertIn("@prefix prov:", turtle)
        self.assertIn('"declared"', turtle)
        self.assertIn('"OrderPolicy"', turtle)

    def test_mcp_lists_read_only_tools_and_hides_private_paths(self) -> None:
        initialized = self.initialize()
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ontology_status",
                    "arguments": {"workspace_id": initialized["workspaceId"]},
                },
            },
        ]
        payload = "".join(json.dumps(item) + "\n" for item in requests)
        process = subprocess.run(
            [sys.executable, str(MCP_SERVER)],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "CODE_ONTOLOGY_HOME": str(self.data_home)},
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        tools = responses[1]["result"]["tools"]
        self.assertGreaterEqual(len(tools), 6)
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))
        self.assertTrue(all(not tool["annotations"]["openWorldHint"] for tool in tools))
        serialized_status = json.dumps(responses[2], ensure_ascii=False)
        self.assertNotIn(str(self.repo.resolve()), serialized_status)
        self.assertNotIn("sourceFingerprint", serialized_status)
        self.assertNotIn("portableRdf", serialized_status)

    def test_mcp_rejects_unregistered_workspace_without_path_input(self) -> None:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ontology_status",
                "arguments": {"workspace_id": "not-registered"},
            },
        }
        process = subprocess.run(
            [sys.executable, str(MCP_SERVER)],
            input=json.dumps(request) + "\n",
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "CODE_ONTOLOGY_HOME": str(self.data_home)},
        )
        response = json.loads(process.stdout)
        self.assertTrue(response["result"]["isError"])
        self.assertIn("Unknown workspace id", response["result"]["structuredContent"]["message"])

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_workspace_symlink_is_rejected(self) -> None:
        self.initialize()
        linked = self.base / "linked-workspace"
        linked.symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(companion.CompanionError):
            companion.status(str(linked))


if __name__ == "__main__":
    unittest.main()
