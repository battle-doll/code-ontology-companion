"""Bounded streaming keeps every logical-record privacy and final integrity check."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from windows_fixture import protect_private_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'))
import companion
import pipeline_export as exporter


class InterchangeBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.original = self.root / 'original'
        self.target = self.root / 'ontology.ttl'
        self.profile = companion.privacy_guard.build_profile(
            ['Synthetic Private Person'], ['synthetic-person@privacy-fixture.test'], key=b'p' * 32)
        profile_path = self.root / 'profile.json'
        profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        protect_private_path(profile_path)
        env = mock.patch.dict(os.environ, {companion.privacy_guard.PROFILE_ENV: str(profile_path)})
        env.start()
        self.addCleanup(env.stop)

    def copy(self, raw, checkpoint=None, info=None):
        self.original.write_bytes(raw)
        protect_private_path(self.original)
        info = info or {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        exporter._copy_interchange(self.original, self.target, info, profile=self.profile,
                                   roots=(self.root,), checkpoint=checkpoint or (lambda: None))

    def test_short_records_reduce_checkpoints_without_skipping_privacy_or_bytes(self):
        line = b'#' + b'x' * 126 + b'\n'
        raw = line * 8192
        sizes = []
        guard = companion.privacy_guard.ensure_public_safe
        with mock.patch.object(companion.privacy_guard, 'ensure_public_safe', wraps=guard) as checks, \
                mock.patch.object(exporter.time, 'monotonic', return_value=0):
            self.copy(raw, lambda: sizes.append(self.target.stat().st_size))
        self.assertEqual(self.target.read_bytes(), raw)
        self.assertEqual(checks.call_count, 8192)
        self.assertTrue(all(call.args[0] == line for call in checks.call_args_list))
        self.assertEqual(len(sizes), 66)
        self.assertEqual(sizes[0], 0)
        self.assertEqual(sizes[-1], len(raw))
        self.assertLessEqual(max(b - a for a, b in zip(sizes, sizes[1:])), 128 * len(line))

    def test_byte_boundary_is_flushed_and_observed(self):
        line = b'#' + b'x' * 32766 + b'\n'
        sizes = []
        with mock.patch.object(exporter.time, 'monotonic', return_value=0):
            self.copy(line * 3, lambda: sizes.append(self.target.stat().st_size))
        self.assertEqual(sizes, [0, 65536, 98304])

    def test_large_indivisible_record_is_alone_between_checkpoints(self):
        large = b'#' + b'x' * (exporter.MAX_INTERCHANGE_LINE - 2) + b'\n'
        raw = b'#start\n' + large + b'#end'
        sizes = []
        with mock.patch.object(exporter.time, 'monotonic', return_value=0):
            self.copy(raw, lambda: sizes.append(self.target.stat().st_size))
        self.assertEqual(self.target.read_bytes(), raw)
        self.assertEqual(sizes, [0, 7, 7 + len(large), len(raw)])
        self.assertLessEqual(max(b - a for a, b in zip(sizes, sizes[1:])), exporter.MAX_INTERCHANGE_LINE)

    def test_elapsed_boundary_is_cooperative_after_each_privacy_check(self):
        now = [0.0]
        real_guard = companion.privacy_guard.ensure_public_safe
        def slow_check(*args, **kwargs):
            result = real_guard(*args, **kwargs)
            now[0] += 0.06
            return result
        sizes = []
        with mock.patch.object(exporter.time, 'monotonic', side_effect=lambda: now[0]), \
                mock.patch.object(companion.privacy_guard, 'ensure_public_safe', side_effect=slow_check):
            self.copy(b'#a\n#b\n#c\n', lambda: sizes.append(self.target.stat().st_size))
        self.assertEqual(sizes, [0, 3, 6, 9, 9])

    def test_empty_crlf_and_no_final_newline_remain_exact(self):
        for raw in (b'', b'#a\r\n#b\r\n', b'#no-final-newline'):
            with self.subTest(raw=raw):
                if self.target.exists(): self.target.unlink()
                sizes = []
                self.copy(raw, lambda: sizes.append(self.target.stat().st_size))
                self.assertEqual(self.target.read_bytes(), raw)
                self.assertEqual(sizes[0], 0)
                self.assertEqual(sizes[-1], len(raw))
                self.assertGreaterEqual(len(sizes), 2)

    def test_denied_line_is_never_written_even_inside_batch(self):
        raw = b'#ok\n#Synthetic Private Person\n#later\n'
        with self.assertRaises(companion.privacy_guard.PrivacyError):
            self.copy(raw)
        self.assertEqual(self.target.read_bytes(), b'#ok\n')

    def test_identity_across_io_size_is_checked_as_one_logical_record(self):
        raw = b'#' + b'x' * (1024 * 1024 - 11) + b' Synthetic Private Person\n'
        with self.assertRaises(companion.privacy_guard.PrivacyError):
            self.copy(raw)
        self.assertEqual(self.target.read_bytes(), b'')

    def test_oversize_record_rejected_before_write(self):
        with self.assertRaisesRegex(companion.CompanionError, 'record exceeds'):
            self.copy(b'x' * (exporter.MAX_INTERCHANGE_LINE + 1))
        self.assertEqual(self.target.read_bytes(), b'')

    def test_digest_and_length_are_both_required(self):
        raw = b'#unchanged\n'
        valid = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        for info in ({**valid, 'sha256': '0' * 64}, {**valid, 'bytes': len(raw) + 1}):
            with self.subTest(info=info):
                if self.target.exists(): self.target.unlink()
                with self.assertRaisesRegex(companion.CompanionError, 'Pinned interchange artifact changed'):
                    self.copy(raw, info=info)

    def test_fresh_callback_failure_stops_at_a_bounded_batch(self):
        calls = []
        def revoke():
            calls.append(self.target.stat().st_size)
            if len(calls) == 2:
                raise companion.CompanionError('synthetic_revocation')
        with mock.patch.object(exporter.time, 'monotonic', return_value=0), \
                self.assertRaisesRegex(companion.CompanionError, 'synthetic_revocation'):
            self.copy(b'#x\n' * 1000, revoke)
        self.assertEqual(calls, [0, 384])
        self.assertEqual(self.target.stat().st_size, 384)

    def test_initial_and_final_checks_cannot_be_skipped(self):
        for fail_at in (1, 2):
            with self.subTest(fail_at=fail_at):
                if self.target.exists(): self.target.unlink()
                calls = []
                def check():
                    calls.append(self.target.stat().st_size)
                    if len(calls) == fail_at:
                        raise companion.CompanionError('synthetic_checkpoint_stop')
                with self.assertRaisesRegex(companion.CompanionError, 'synthetic_checkpoint_stop'):
                    self.copy(b'', check)
                self.assertEqual(len(calls), fail_at)

    def test_policy_json_still_checks_decoded_identities_before_output_creation(self):
        self.target = self.root / 'policy.json'
        raw = b'{"rules":[{"note":"\\u0053ynthetic Private Person"}],"evidence":[]}'
        with self.assertRaises(companion.privacy_guard.PrivacyError):
            self.copy(raw)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
