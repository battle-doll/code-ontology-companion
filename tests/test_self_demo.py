from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_self_demo", ROOT / "scripts/build_self_demo.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CommittedSourceTests(unittest.TestCase):
    def test_archive_binds_tracked_bytes_and_excludes_ignored_working_tree(self):
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            repo = parent / "repo"
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
            git("init", "--quiet")
            (repo / "entry.py").write_text("def committed(): pass\n")
            (repo / ".gitignore").write_text("ignored.py\n")
            git("add", "entry.py", ".gitignore")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                "commit", "--quiet", "-m", "fixture")
            revision = git("rev-parse", "HEAD")
            (repo / "entry.py").write_text("def changed_after_check(): pass\n")
            (repo / "ignored.py").write_text("def private_ignored(): pass\n")
            output = parent / "source"
            builder.committed_source(revision, output, repo=repo)
            self.assertEqual((output / "entry.py").read_text(), "def committed(): pass\n")
            self.assertFalse((output / "ignored.py").exists())


if __name__ == "__main__":
    unittest.main()
