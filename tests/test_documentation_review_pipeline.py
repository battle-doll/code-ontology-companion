"""Private documentation claims remain distinct from executable policy."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from windows_fixture import protect_private_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'))
import pipeline_store as store
import pipeline_documentation
import privacy_guard


class DocumentationReviewPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.workspace = self.root / 'knowledge'
        self.comment = '/** Declares a bounded decision; execution is not established. */'
        self.source = self.comment + '\nclass Rule { String state="READY"; }'
        self.path = self.repo / 'Rule.java'
        self.path.write_text(self.source, encoding='utf-8')
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps(privacy_guard.build_profile(['Synthetic Private Person'], [], key=b'd' * 32)))
        protect_private_path(profile)
        environment = patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile)})
        environment.start(); self.addCleanup(environment.stop)

    def review(self, literal=False):
        files, _ = store._discover(self.repo, ['.'], store.DEFAULT_BUDGETS)
        token = '"READY"' if literal else self.comment
        start = self.source.index(token)
        entry = {'path': 'Rule.java', 'sourceSha256': hashlib.sha256(self.source.encode()).hexdigest(),
                 'tokenByteStart': len(self.source[:start].encode()), 'tokenByteEnd': len(self.source[:start + len(token)].encode()),
                 'tokenSha256': hashlib.sha256(token.encode()).hexdigest(),
                 'classification': 'nonsecret_policy' if literal else 'nonsecret_documentation',
                 'reasonCode': 'synthetic_contract', 'usageContext': 'synthetic_test', 'reviewId': 'synthetic-review'}
        return {'format': 'companion.reviewed-literals.v1' if literal else 'companion.reviewed-documentation.v1',
                'purpose': 'private-policy-analysis', 'sourceFingerprint': store._fingerprint(files),
                'review': {'reviewId': 'synthetic-review', 'reviewerKind': 'independent_source_review',
                           'reviewedAt': '2026-01-01T00:00:00Z'}, 'entries': [entry]}

    def claims(self, snapshot=None):
        return [row for row in store.iter_records(self.workspace, snapshot)
                if row.get('category') == 'source_documentation']

    def test_default_opaque_then_reviewed_source_free_claim_and_explicit_clear(self):
        initial = store.initialize(self.repo, self.workspace)
        self.assertEqual(len(self.claims()), 1)
        self.assertNotIn('sourceText', self.claims()[0])
        reviewed = store.sync(self.workspace, documentation_review=self.review())
        self.assertNotEqual(initial['analysisSpecId'], reviewed['analysisSpecId'])
        claim = self.claims()[0]
        self.assertEqual(claim['sourceText'], self.comment)
        self.assertEqual(claim['instructionAuthority'], 'none')
        self.assertEqual(claim['evidence']['enforcement'], 'UNKNOWN')
        self.assertFalse(claim['businessMeaningVerified'])
        self.assertEqual(reviewed['coverage']['documentationReview']['admittedEntries'], 1)
        self.assertEqual(reviewed['coverage']['documentation']['reviewedFragments'], 1)
        self.assertFalse(reviewed['coverage']['documentation']['semanticComplete'])
        self.repo.rename(self.root / 'hidden-source')
        self.assertEqual(self.claims(reviewed['snapshotId'])[0]['sourceText'], self.comment)
        (self.root / 'hidden-source').rename(self.repo)
        cleared = store.sync(self.workspace, clear_documentation_review=True)
        self.assertNotIn('documentationReview', cleared['coverage'])
        self.assertNotIn('sourceText', self.claims()[0])
        self.assertEqual(self.claims(reviewed['snapshotId'])[0]['sourceText'], self.comment)

    def test_stale_documentation_review_blocks_and_preserves_original_scope(self):
        store.initialize(self.repo, self.workspace, documentation_review=self.review())
        before = {name: (self.workspace / name).read_bytes() for name in ('state.json', 'pipeline.json')}
        self.path.write_text(self.source + '\n// changed\n', encoding='utf-8')
        with self.assertRaisesRegex(store.PipelineError, 'documentation_review_source_or_contract_invalid'):
            store.sync(self.workspace)
        self.assertEqual(before, {name: (self.workspace / name).read_bytes() for name in before})
        outcome = json.loads((self.workspace / 'last-coverage-attempt.json').read_text())
        self.assertEqual(len(outcome['entries']), 1)
        self.assertEqual(outcome['entries'][0]['status'], 'blocked')
        self.assertEqual(outcome['entries'][0]['reason'], 'documentation_review_source_or_contract_invalid')

    def test_separate_literal_and_documentation_reviews_can_be_cleared_independently(self):
        original = store.initialize(self.repo, self.workspace, literal_review=self.review(True), documentation_review=self.review())
        cleared = store.sync(self.workspace, clear_documentation_review=True)
        self.assertNotIn('sourceText', self.claims()[0])
        self.assertEqual(cleared['coverage']['literalReview']['admittedEntries'], 1)
        self.assertIn('READY', json.dumps(list(store.iter_records(self.workspace))))
        self.assertEqual(self.claims(original['snapshotId'])[0]['sourceText'], self.comment)

    def test_documentation_inventory_budget_failure_is_not_a_successful_snapshot(self):
        initial = store.initialize(self.repo, self.workspace)
        original = pipeline_documentation.extract_documentation

        def exhausted(*args, **kwargs):
            kwargs['max_fragments'] = 0
            return original(*args, **kwargs)

        with patch.object(pipeline_documentation, 'extract_documentation', side_effect=exhausted):
            with self.assertRaisesRegex(store.PipelineError, 'documentation_inventory_incomplete'):
                store.sync(self.workspace, force=True)
        self.assertEqual(store.status(self.workspace)['snapshotId'], initial['snapshotId'])
        outcome = json.loads((self.workspace / 'last-coverage-attempt.json').read_text())
        self.assertEqual(len(outcome['entries']), 1)
        self.assertEqual(outcome['entries'][0]['status'], 'failed')
        self.assertIn('documentationFailures', outcome)
        self.assertFalse(outcome['documentationFailures'][0]['coverage']['inventoryComplete'])

    def test_recovery_rechecks_review_and_preserves_one_comment_occurrence(self):
        def stop(label):
            if label == 'after_file':
                raise store.PipelineCancelled('synthetic_stop')

        with patch.object(store, '_checkpoint', side_effect=stop):
            with self.assertRaises(store.PipelineCancelled):
                store.initialize(self.repo, self.workspace, documentation_review=self.review())
        recovered = store.recover(self.workspace)
        self.assertEqual(recovered['recoveredRunCount'], 1)
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(recovered['coverage']['documentationReview']['admittedEntries'], 1)

    def test_unsupported_comment_language_retains_file_and_explicit_limitation(self):
        (self.repo / 'worker.py').write_text('# Synthetic contract\nanswer = 42\n', encoding='utf-8')
        result = store.initialize(self.repo, self.workspace)
        self.assertEqual(result['coverage']['sourceProcessing']['numerator'], 2)
        self.assertEqual(result['coverage']['sourceProcessing']['denominator'], 2)
        self.assertFalse(result['coverage']['documentation']['semanticComplete'])
        rows = [row for row in store.iter_records(self.workspace) if row.get('path') == 'worker.py']
        coverage = next(row for row in rows if row.get('name') == 'DocumentationCoverage')
        self.assertFalse(coverage['coverage']['lexicalComplete'])
        limitations = [row for row in rows if row.get('category') == 'documentation_omission']
        self.assertEqual(len(limitations), 1)
        self.assertEqual(limitations[0]['representationStatus'], 'unsupported')
        self.assertEqual(limitations[0]['sourceDigest'], hashlib.sha256((self.repo / 'worker.py').read_bytes()).hexdigest())
        self.assertNotIn('sourceText', limitations[0])


if __name__ == '__main__':
    unittest.main()
