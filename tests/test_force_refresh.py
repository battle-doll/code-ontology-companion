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
COMPANION = SCRIPT_DIR / "companion.py"


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class ForceRefreshTests(unittest.TestCase):
    def test_force_refresh_promotes_new_immutable_snapshot_through_api_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            workspace = base / "workspace"
            data_home = base / "data"
            shutil.copytree(FIXTURE, repo)
            with mock.patch.dict(
                os.environ,
                {"CODE_ONTOLOGY_HOME": str(data_home)},
                clear=False,
            ):
                initial = companion.initialize(
                    str(repo),
                    str(workspace),
                    authorized=True,
                    source_roots=["python_pipeline"],
                )
                initial_path = workspace / "snapshots" / initial["snapshotId"]
                initial_digest = tree_digest(initial_path)
                initial_manifest = json.loads(
                    (initial_path / "source-manifest.json").read_text(encoding="utf-8")
                )

                unchanged = companion.sync(str(workspace))
                self.assertEqual(unchanged["status"], "no_change")
                self.assertEqual(unchanged["snapshotId"], initial["snapshotId"])

                forced = companion.sync(str(workspace), trigger="api-force", force=True)
                forced_path = workspace / "snapshots" / forced["snapshotId"]
                forced_manifest = json.loads(
                    (forced_path / "source-manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(forced["status"], "promoted")
                self.assertNotEqual(forced["snapshotId"], initial["snapshotId"])
                self.assertEqual(forced["previousSnapshotId"], initial["snapshotId"])
                self.assertEqual(forced["sourceRoots"], ["python_pipeline"])
                self.assertEqual(forced_manifest, initial_manifest)
                self.assertEqual(tree_digest(initial_path), initial_digest)
                forced_digest = tree_digest(forced_path)

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(COMPANION),
                        "sync",
                        "--workspace",
                        str(workspace),
                        "--trigger",
                        "cli-force",
                        "--force",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={**os.environ, "CODE_ONTOLOGY_HOME": str(data_home)},
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                cli_forced = json.loads(completed.stdout)
                cli_path = workspace / "snapshots" / cli_forced["snapshotId"]
                cli_manifest = json.loads(
                    (cli_path / "source-manifest.json").read_text(encoding="utf-8")
                )
                state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
                lineage = [
                    json.loads(line)
                    for line in (workspace / "lineage.jsonl").read_text(encoding="utf-8").splitlines()
                ]

                self.assertEqual(cli_forced["status"], "promoted")
                self.assertNotEqual(cli_forced["snapshotId"], forced["snapshotId"])
                self.assertEqual(cli_forced["previousSnapshotId"], forced["snapshotId"])
                self.assertEqual(cli_forced["sourceRoots"], ["python_pipeline"])
                self.assertEqual(cli_manifest, initial_manifest)
                self.assertEqual(state["currentSnapshot"], cli_forced["snapshotId"])
                self.assertEqual(state["previousSnapshot"], forced["snapshotId"])
                self.assertEqual(state["sourceRoots"], ["python_pipeline"])
                self.assertEqual(lineage[-1]["snapshotId"], cli_forced["snapshotId"])
                self.assertEqual(lineage[-1]["previousSnapshotId"], forced["snapshotId"])
                self.assertEqual(lineage[-1]["trigger"], "cli-force")
                self.assertEqual(tree_digest(initial_path), initial_digest)
                self.assertEqual(tree_digest(forced_path), forced_digest)


if __name__ == "__main__":
    unittest.main()
