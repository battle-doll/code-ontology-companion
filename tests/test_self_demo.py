from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


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


class PublicDemoPrivacyTests(unittest.TestCase):
    def test_late_artifact_failure_publishes_no_earlier_artifact(self):
        checked = []
        def check(payload, **kwargs):
            checked.append(payload)
            if "fixture.person@example.test" in payload:
                raise ValueError("privacy.email")
        guard = SimpleNamespace(ensure_public_safe=check)
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            with self.assertRaisesRegex(ValueError, "privacy.email"):
                builder.publish_validated_artifacts(output, {
                    "index.html": b"<html>safe fixture</html>",
                    "ontology.json": b'{"nodes":[]}',
                    "snapshot.json": b'{"untrusted":"fixture.person@example.test"}',
                }, guard, context_roots=(output,))
            self.assertEqual(list(output.iterdir()), [])
            self.assertEqual(len(checked), 3)

    def test_all_artifacts_are_guarded_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            checked = []
            def check(payload, **kwargs):
                self.assertEqual(list(output.iterdir()), [])
                self.assertEqual(kwargs["context_roots"], (output,))
                checked.append(payload)
            builder.publish_validated_artifacts(output, {
                "index.html": b"safe page", "ontology.json": b"safe data",
                "ontology.ttl": b"safe triples", "snapshot.json": b"safe manifest",
            }, SimpleNamespace(ensure_public_safe=check), context_roots=(output,))
            self.assertEqual(len(checked), 4)
            self.assertEqual(len(list(output.iterdir())), 4)

    def test_literal_private_metadata_gate_also_precedes_all_writes(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            with self.assertRaisesRegex(ValueError, "Private metadata"):
                builder.publish_validated_artifacts(output, {
                    "index.html": b"safe fixture", "ontology.json": b"fixture-local-private-token",
                }, SimpleNamespace(ensure_public_safe=lambda *args, **kwargs: None),
                    forbidden=("fixture-local-private-token",))
            self.assertEqual(list(output.iterdir()), [])

    def test_guard_is_required_in_the_copied_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ValueError, "requires the shipped privacy guard"):
                builder.load_demo_privacy_guard(Path(raw))

    def test_real_guard_rejects_encoded_late_artifact_with_optional_profile(self):
        guard = builder.load_demo_privacy_guard(ROOT / "skills/manage-code-ontology")
        with tempfile.TemporaryDirectory() as raw:
            private = Path(raw).resolve()
            profile = private / "deny-profile.json"
            profile.write_text(json.dumps(guard.build_profile(["Synthetic Private Name"], [], key=b"k" * 32)))
            profile.chmod(0o600)
            output = private / "public"
            output.mkdir()
            with mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(profile)}), \
                 self.assertRaises(guard.PrivacyError):
                builder.publish_validated_artifacts(output, {
                    "ontology.json": b'{"nodes":[]}',
                    "index.html": b'<script type="application/json">{"hidden":"Synthetic%20Private%20Name"}</script>',
                }, guard, context_roots=(output,))
            self.assertEqual(list(output.iterdir()), [])

    def test_arbitrary_artifact_names_cannot_expose_identity_in_filename(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            with self.assertRaisesRegex(ValueError, "fixed basenames"):
                builder.publish_validated_artifacts(output, {
                    "Synthetic Private Name.html": b"safe fixture",
                }, SimpleNamespace(ensure_public_safe=lambda *args, **kwargs: None))
            self.assertEqual(list(output.iterdir()), [])

    def test_cli_never_prints_native_exception_or_private_subprocess_argv(self):
        stderr = io.StringIO()
        secret = "fixture.person@example.test " + "/Users/" + "SyntheticPrivatePerson/fixture"
        with mock.patch.object(builder, "build", side_effect=OSError(secret)), \
             mock.patch.object(builder.sys, "argv", ["build_self_demo.py", "--output", "fixture-output"]), \
             mock.patch.object(builder.sys, "stderr", stderr):
            self.assertEqual(builder.main(), 1)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertNotIn("fixture.person", stderr.getvalue())
        self.assertNotIn("/Users/", stderr.getvalue())
        self.assertIn('"status": "error"', stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
