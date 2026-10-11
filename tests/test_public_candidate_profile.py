from __future__ import annotations
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_release
import build_skills_only_release

class PublicCandidateProfileTests(unittest.TestCase):
    def test_public_candidate_requires_profile_before_source_or_output_actions(self):
        for module in (build_release, build_skills_only_release):
            with self.subTest(profile=module.PROFILE), mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(sys, 'argv', ['builder', '--public']), \
                    mock.patch.object(module, '_run_source_validator') as validate, \
                    mock.patch.object(module, 'build_archive') as build, \
                    contextlib.redirect_stderr(io.StringIO()) as diagnostic:
                self.assertEqual(1, module.main())
                validate.assert_not_called(); build.assert_not_called()
                self.assertEqual('FAIL: public candidate requires a valid private identity profile.\n', diagnostic.getvalue())

    def test_partial_identity_profile_cannot_prepare_public_candidate(self):
        for module in (build_release, build_skills_only_release):
            for profile in ({"denyNames": [{}], "denyEmails": []}, {"denyNames": [], "denyEmails": [{}]}):
                with self.subTest(profile=module.PROFILE), \
                        mock.patch.object(sys, 'argv', ['builder', '--public']), \
                        mock.patch('validate_public_privacy.load_profile', return_value=profile), \
                        mock.patch.object(module, '_run_source_validator') as validate, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(1, module.main())
                    validate.assert_not_called()

if __name__ == '__main__':
    unittest.main()
