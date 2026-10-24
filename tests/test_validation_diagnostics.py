"""Failure locations remain useful without exposing unittest payloads/paths."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from windows_fixture import protect_private_path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_package as validator
import privacy_guard


class ValidationDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "public-source"
        (self.root / "tests").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        self.test_file = self.root / "tests/test_fixture.py"
        self.test_file.write_text("class SafeCases:\n    def test_failure(self):\n        pass\n", encoding="utf-8")
        self.code_file = self.root / "scripts/helper.py"
        self.code_file.write_text("class PublicError(Exception):\n    pass\n", encoding="utf-8")
        self.profile = privacy_guard.build_profile(["Synthetic Diagnostic Identity"],
            ["synthetic-diagnostic@privacy-fixture.test"], key=b"v" * 32)
        profile_path = self.base / "profile.json"
        profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
        protect_private_path(profile_path)
        patcher = mock.patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile_path)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def diagnostic(self, suffix=""):
        return ('ERROR: test_failure (test_fixture.SafeCases.test_failure)' + suffix + '\n'
            'Traceback (most recent call last):\n'
            f'  File "{self.test_file}", line 2, in test_failure\n'
            '    private_source_literal = "Synthetic Diagnostic Identity"\n'
            '  File "/home/private/outside.py", line 1, in private_function\n'
            f'  File "{self.code_file}", line 1, in private_function\n'
            'PublicError: synthetic-diagnostic@privacy-fixture.test\n'
            'AssertionError: sk-' + 'x' * 40 + '\n')

    def test_only_source_backed_ids_exception_classes_and_relative_frames_survive(self):
        raw = self.diagnostic(" (value='Synthetic Diagnostic Identity')")
        with self.assertRaises(privacy_guard.PrivacyError):
            privacy_guard.ensure_public_safe(raw, profile=self.profile)
        summary = validator.safe_unittest_failure_summary(raw, self.root)
        self.assertEqual(summary["failures"], [{"test": "test_fixture.SafeCases.test_failure", "outcome": "error",
            "exceptions": ["PublicError", "AssertionError"],
            "frames": [{"file": "tests/test_fixture.py", "line": 2}, {"file": "scripts/helper.py", "line": 1}]}])
        privacy_guard.ensure_public_safe(summary, profile=self.profile)
        encoded = json.dumps(summary)
        for value in (str(self.base), "Synthetic Diagnostic Identity", "private_source_literal", "private_function",
                      "/home/private/outside.py", "synthetic-diagnostic@privacy-fixture.test", "sk-" + "x" * 40):
            self.assertNotIn(value, encoded)

    def test_unknown_tests_exceptions_and_invalid_code_lines_are_withheld(self):
        raw = self.diagnostic().replace("PublicError:", "UnknownPrivateException:").replace("AssertionError:", "UnknownOther:")
        raw = raw.replace("line 2,", "line 9999999,").replace("line 1,", "line 0,")
        raw += "FAIL: test_private_identity (test_private.PrivateCase)\nAssertionError: private value\n"
        summary = validator.safe_unittest_failure_summary(raw, self.root)
        self.assertEqual(summary["omittedFailures"], 1)
        self.assertEqual(summary["failures"][0]["exceptions"], ["unknown"])
        self.assertEqual(summary["failures"][0]["frames"], [])
        self.assertNotIn("private_identity", json.dumps(summary))

    def test_python39_header_and_bounded_repeated_subtest_failures(self):
        raw = self.diagnostic().replace(".SafeCases.test_failure)", ".SafeCases)")
        summary = validator.safe_unittest_failure_summary(raw * 55, self.root)
        self.assertEqual(len(summary["failures"]), 50)
        self.assertEqual(summary["omittedFailures"], 5)
        self.assertEqual(summary["failures"][0]["test"], "test_fixture.SafeCases.test_failure")

    def test_failed_command_emits_summary_without_echoing_private_diagnostics(self):
        raw = self.diagnostic()
        summary = validator.safe_unittest_failure_summary(raw, self.root)
        result = subprocess.CompletedProcess([], 1, "Synthetic Diagnostic Identity\n", raw)
        with mock.patch.object(validator.subprocess, "run", return_value=result), \
                mock.patch.object(validator, "safe_unittest_failure_summary", return_value=summary), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaisesRegex(AssertionError, "Validation command failed"):
                validator.run([sys.executable, "-m", "unittest", "discover"])
        self.assertIn('"diagnostic":"source_identifier_summary"', output.getvalue())
        self.assertNotIn("Synthetic Diagnostic Identity", output.getvalue())
        self.assertNotIn(str(self.base), output.getvalue())
        privacy_guard.ensure_public_safe(output.getvalue(), profile=self.profile)

    def test_summary_still_has_to_pass_the_existing_privacy_gate(self):
        raw = self.diagnostic()
        result = subprocess.CompletedProcess([], 1, "", raw)
        unsafe_summary = {"test": "Synthetic Diagnostic Identity"}
        with mock.patch.object(validator.subprocess, "run", return_value=result), \
                mock.patch.object(validator, "safe_unittest_failure_summary", return_value=unsafe_summary), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(AssertionError):
                validator.run([sys.executable, "-m", "unittest", "discover"])
        self.assertEqual(output.getvalue(), "Validation diagnostics contain private data or local paths and were withheld.\n")


if __name__ == "__main__":
    unittest.main()
