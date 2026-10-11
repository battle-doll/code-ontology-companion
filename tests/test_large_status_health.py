"""Large status must not hide stale generators or interrupted child writes."""
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
import code_ontology_core as core
import companion
import large_project


class LargeStatusHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.workspace = self.base / "ontology"
        for name in ("alpha", "beta"):
            module = self.repo / name
            module.mkdir(parents=True)
            (module / "sample.py").write_text("def first():\n    return 1\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(self.base / "registry")})
        self.env.start()
        large_project.initialize(str(self.repo), str(self.workspace), authorized=True,
                                 label="synthetic", module_roots=["alpha", "beta"])
        self.initial = large_project.status(str(self.workspace))
        self.child = (self.workspace / "modules" / self.initial["modules"][0]["moduleId"]).resolve()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def digest(self):
        return {path.relative_to(self.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.rglob("*") if path.is_file()}

    def test_unchanged_sources_do_not_hide_changed_generator_and_status_is_read_only(self):
        before = self.digest()
        self.assertEqual(self.initial["pipelineStatus"], "healthy")
        with mock.patch.object(core, "generator_fingerprint", return_value="f" * 64):
            status = large_project.status(str(self.workspace))
        self.assertEqual(status["freshness"], "current")
        self.assertEqual(status["generatorFreshness"], "stale")
        self.assertEqual(status["pipelineStatus"], "refresh_required")
        self.assertTrue(all(module["generatorFreshness"] == "stale" for module in status["modules"]))
        self.assertEqual(before, self.digest())

    def test_child_lineage_export_failure_requires_recovery_with_zero_pending_runs(self):
        original = companion._atomic_write

        def fail(path, content, mode=0o600):
            if path == self.child / "lineage.ttl":
                raise OSError("injected synthetic export failure")
            return original(path, content, mode)

        with mock.patch.object(companion, "_atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                companion.record(str(self.child), "note", "Synthetic local check", "declared")
        before = self.digest()
        status = large_project.status(str(self.workspace))
        self.assertEqual(status["status"], "attention_required")
        self.assertEqual(status["pipelineStatus"], "recovery_required")
        self.assertEqual(status["pendingRecoveryRuns"], 0)
        self.assertEqual(status["recoveryStatus"], "recovery_required")
        self.assertEqual(status["modules"][0]["recoveryStatus"], "recovery_required")
        self.assertEqual(status["modules"][1]["recoveryStatus"], "healthy")
        self.assertEqual(before, self.digest())
        companion.recover(str(self.child))
        repaired = large_project.status(str(self.workspace))
        self.assertEqual(repaired["status"], "ok")
        self.assertEqual(repaired["pipelineStatus"], "healthy")
        self.assertEqual(repaired["recoveryStatus"], "healthy")

    def test_pending_child_recovery_takes_priority_over_stale_source_and_generator(self):
        (self.repo / "alpha" / "sample.py").write_text("def second():\n    return 2\n", encoding="utf-8")
        original = companion._atomic_write

        def fail(path, content, mode=0o600):
            original(path, content, mode)
            if path.parent == self.child / ".transactions" and json.loads(content)["status"] == "prepared":
                raise OSError("injected synthetic receipt failure")

        with mock.patch.object(companion, "_atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                companion.sync(str(self.child))
        with mock.patch.object(core, "generator_fingerprint", return_value="f" * 64):
            status = large_project.status(str(self.workspace))
        self.assertEqual(status["freshness"], "stale")
        self.assertEqual(status["generatorFreshness"], "stale")
        self.assertEqual(status["pipelineStatus"], "recovery_required")
        self.assertEqual(status["pendingRecoveryRuns"], 1)
        self.assertEqual([module["pendingRecoveryRuns"] for module in status["modules"]], [1, 0])
        companion.recover(str(self.child))
        recovered = large_project.status(str(self.workspace))
        self.assertEqual(recovered["pipelineStatus"], "refresh_required")
        self.assertEqual(recovered["pendingRecoveryRuns"], 0)
        self.assertEqual(recovered["modules"][0]["catalogBinding"], "child_advanced")
        large_project.sync(str(self.workspace))
        self.assertEqual(large_project.status(str(self.workspace))["pipelineStatus"], "healthy")

    def test_generator_freshness_is_bound_to_pinned_catalog_artifact(self):
        with mock.patch.object(core, "generator_fingerprint", return_value="f" * 64):
            companion.sync(str(self.child), force=True)
            self.assertEqual(companion.status(str(self.child))["generatorFreshness"], "current")
            status = large_project.status(str(self.workspace))
        self.assertEqual(status["modules"][0]["catalogBinding"], "child_advanced")
        self.assertEqual(status["modules"][0]["generatorFreshness"], "stale")
        self.assertEqual(status["modules"][0]["pinnedSnapshotId"], self.initial["modules"][0]["pinnedSnapshotId"])
        self.assertEqual(status["pipelineStatus"], "refresh_required")

    def test_large_sync_refreshes_all_children_after_generator_only_change(self):
        old_pins = [module["pinnedSnapshotId"] for module in self.initial["modules"]]
        with mock.patch.object(core, "generator_fingerprint", return_value="f" * 64):
            result = large_project.sync(str(self.workspace))
            status = large_project.status(str(self.workspace))
            unchanged = large_project.sync(str(self.workspace))
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(status["pipelineStatus"], "healthy")
        self.assertEqual(status["generatorFreshness"], "current")
        self.assertTrue(all(old != new["pinnedSnapshotId"] for old, new in zip(old_pins, status["modules"])))
        self.assertEqual(unchanged["status"], "no_change")

    def test_legacy_generator_absence_is_reported_as_unknown(self):
        original = companion._snapshot_metadata

        def legacy(path):
            metadata = original(path)
            metadata.pop("generatorFingerprint", None)
            return metadata

        with mock.patch.object(companion, "_snapshot_metadata", side_effect=legacy):
            status = large_project.status(str(self.workspace))
        self.assertEqual(status["generatorFreshness"], "unknown")
        self.assertTrue(all(module["generatorFreshness"] == "unknown" for module in status["modules"]))
        self.assertEqual(status["freshness"], "current")


if __name__ == "__main__":
    unittest.main()
