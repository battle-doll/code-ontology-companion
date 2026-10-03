"""Exercise command dispatch/imports and module pins through separate processes."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / "skills/manage-code-ontology/scripts/companion.py"


class LargeProjectCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        self.workspace = self.base / "catalog"
        self.registry = self.base / "registry"
        self.environment = {**os.environ, "CODE_ONTOLOGY_HOME": str(self.registry)}
        for name in ("alpha", "beta"):
            module = self.repo / name
            module.mkdir(parents=True)
            (module / "sample.py").write_text("def shared_name():\n    pass\n", encoding="utf-8")
        self.roots = ["--repo", str(self.repo), "--module-root", "alpha", "--module-root", "beta"]

    def invoke(self, *arguments: str, expected_exit: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(COMPANION), *arguments], cwd=self.base,
            env=self.environment, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, expected_exit, completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
        return json.loads(completed.stdout if expected_exit == 0 else completed.stderr)

    def test_lifecycle_pins_incremental_changes_and_forced_refresh(self) -> None:
        checked = self.invoke("large-preflight", *self.roots)
        self.assertEqual(checked["moduleCount"], 2)
        self.assertFalse(self.registry.exists())
        self.assertFalse(self.workspace.exists())
        initial = self.invoke("large-init", *self.roots, "--workspace", str(self.workspace), "--authorized")
        snapshot = initial["catalogSnapshotId"]
        initial_catalog_path = Path(initial["catalog"])
        initial_bytes = initial_catalog_path.read_bytes()
        before = {item["root"]: item["snapshotId"] for item in initial["modules"]}
        result = self.invoke("large-query", "--workspace", str(self.workspace), "--term", "shared_name", "--limit", "1")
        self.assertEqual(result["returned"], 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["catalogSnapshotId"], snapshot)
        discovered = self.invoke("large-modules", "--workspace", str(self.workspace), "--limit", "1", "--catalog-snapshot", snapshot)
        self.assertTrue(discovered["metadataOnly"])
        self.assertEqual(discovered["nextOffset"], 1)
        scoped = self.invoke("large-query", "--workspace", str(self.workspace), "--term", "shared_name", "--module-root", "beta", "--catalog-snapshot", snapshot)
        self.assertEqual(scoped["selectedModuleRoots"], ["beta"])
        self.assertTrue(all(item["moduleRoot"] == "beta" for item in scoped["matches"]))
        influence = self.invoke("large-impact", "--workspace", str(self.workspace), "--module-root", "beta", "--symbol", "shared_name", "--catalog-snapshot", snapshot)
        self.assertEqual(influence["catalogSnapshotId"], snapshot)
        self.assertEqual(influence["moduleSnapshotId"], before["beta"])
        self.assertEqual(influence["crossModuleResolution"], "unsupported")
        unchanged = self.invoke("large-sync", "--workspace", str(self.workspace))
        self.assertEqual(unchanged["status"], "no_change")
        self.assertEqual(unchanged["catalogSnapshotId"], snapshot)
        (self.repo / "beta" / "added.py").write_text("def new_symbol():\n    pass\n", encoding="utf-8")
        stale = self.invoke("large-status", "--workspace", str(self.workspace))
        self.assertEqual(stale["freshness"], "stale")
        changed = self.invoke("large-sync", "--workspace", str(self.workspace))
        after = {item["root"]: item["snapshotId"] for item in changed["modules"]}
        self.assertEqual(after["alpha"], before["alpha"])
        self.assertNotEqual(after["beta"], before["beta"])
        self.assertEqual(changed["previousCatalogSnapshotId"], snapshot)
        self.assertEqual(initial_catalog_path.read_bytes(), initial_bytes)
        pinned = self.invoke("large-query", "--workspace", str(self.workspace), "--term", "new_symbol", "--module-root", "beta", "--catalog-snapshot", snapshot)
        self.assertEqual(pinned["returned"], 0)
        fresh = self.invoke("large-status", "--workspace", str(self.workspace))
        self.assertEqual(fresh["freshness"], "current")
        forced = self.invoke("large-sync", "--workspace", str(self.workspace), "--force")
        self.assertEqual(forced["status"], "promoted")
        self.assertTrue(all(item["snapshotId"] != after[item["root"]] for item in forced["modules"]))

    def test_missing_authorization_and_invalid_scope_fail_without_writes(self) -> None:
        denied = self.invoke("large-init", *self.roots, "--workspace", str(self.workspace), expected_exit=2)
        self.assertEqual(denied["status"], "error")
        invalid = self.invoke(
            "large-preflight", "--repo", str(self.repo), "--module-root", "alpha",
            "--module-root", "alpha", expected_exit=2,
        )
        self.assertEqual(invalid["status"], "error")
        self.assertFalse(self.workspace.exists())
        self.assertFalse(self.registry.exists())


if __name__ == "__main__":
    unittest.main()
