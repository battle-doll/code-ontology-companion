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
