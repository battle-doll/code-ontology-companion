"""Private occurrence contracts survive generation, recovery and pinned reads."""
import copy
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
import privacy_guard


class LiteralReviewPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.workspace = self.root / 'knowledge'
        self.source = 'class Rule { String choose(String input) { if (input.equals("READY")) return "PASS"; return "WAIT"; } }'
        self.path = self.repo / 'Rule.java'
        self.path.write_text(self.source, encoding='utf-8')
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps(privacy_guard.build_profile(['Synthetic Private Person'],
            ['person@privacy-fixture.test'], key=b'l' * 32)), encoding='utf-8')
        protect_private_path(profile)
        env = patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile)})
        env.start(); self.addCleanup(env.stop)

    def review(self, values=('READY', 'PASS')):
        files, _ = store._discover(self.repo, ['.'], store.DEFAULT_BUDGETS)
        digest = hashlib.sha256(self.source.encode()).hexdigest()
        entries = []
        for value in values:
            token = json.dumps(value)
            start = self.source.index(token)
            entries.append({'path':'Rule.java', 'sourceSha256':digest,
                'tokenByteStart':len(self.source[:start].encode()),
                'tokenByteEnd':len(self.source[:start + len(token)].encode()),
                'tokenSha256':hashlib.sha256(token.encode()).hexdigest(),
                'classification':'nonsecret_policy', 'reasonCode':'protocol_status',
                'usageContext':'comparison_or_result', 'reviewId':'synthetic-review'})
        return {'format':'companion.reviewed-literals.v1', 'purpose':'private-policy-analysis',
            'sourceFingerprint':store._fingerprint(files),
            'review':{'reviewId':'synthetic-review', 'reviewerKind':'independent_source_review',
                      'reviewedAt':'2026-01-01T00:00:00Z'}, 'entries':entries}

    def values(self, snapshot=None):
        found = []
        pending = list(store.iter_records(self.workspace, snapshot))
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if value.get('op') == 'literal' and value.get('type') in ('string', 'character'):
                    found.append(value['value'])
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return found

    def test_persisted_review_source_free_reads_and_explicit_clear(self):
        original = store.initialize(self.repo, self.workspace)
        self.assertFalse(self.values())
        reviewed = store.sync(self.workspace, literal_review=self.review())
        self.assertNotEqual(original['analysisSpecId'], reviewed['analysisSpecId'])
        self.assertEqual(set(self.values()), {'READY', 'PASS'})
        self.assertEqual(reviewed['coverage']['literalReview']['admittedEntries'], 2)
        self.assertFalse(reviewed['coverage']['literalReview']['publicDisclosureAuthorized'])
        self.assertEqual(store.sync(self.workspace)['status'], 'no_change')
        self.repo.rename(self.root / 'hidden-source')
        self.assertEqual(set(self.values(reviewed['snapshotId'])), {'READY', 'PASS'})
        (self.root / 'hidden-source').rename(self.repo)
        cleared = store.sync(self.workspace, clear_literal_review=True)
        self.assertNotIn('literalReview', cleared['coverage'])
        self.assertFalse(self.values())
        self.assertEqual(set(self.values(reviewed['snapshotId'])), {'READY', 'PASS'})

    def test_changed_source_blocks_without_promoting_or_shrinking_scope(self):
        store.initialize(self.repo, self.workspace, literal_review=self.review())
        state = (self.workspace / 'state.json').read_bytes()
        config = (self.workspace / 'pipeline.json').read_bytes()
        self.path.write_text(self.source + '\n// changed input\n', encoding='utf-8')
        with self.assertRaisesRegex(store.PipelineError, 'literal_review_source_or_contract_invalid'):
            store.sync(self.workspace)
        self.assertEqual((self.workspace / 'state.json').read_bytes(), state)
        self.assertEqual((self.workspace / 'pipeline.json').read_bytes(), config)
        attempt = json.loads((self.workspace / 'last-coverage-attempt.json').read_text())
        self.assertEqual(len(attempt['entries']), 1)
        self.assertEqual(attempt['entries'][0]['status'], 'blocked')
        self.assertEqual(attempt['summary']['state'], 'BLOCKED')

    def test_admitted_but_discarded_occurrence_is_visible_in_pinned_status(self):
        import policy_semantics
        self.source = 'class Rule { Object[] bands={new Band("READY")}; }'
        self.path.write_text(self.source, encoding='utf-8')

        def discard_array(parser, depth):
            parser.index = len(parser.tokens)
            return {'op': 'array_initializer', 'elements': []}

        with patch.object(policy_semantics._Expression, 'array_initializer', discard_array):
            first = store.initialize(self.repo, self.workspace, literal_review=self.review(('READY',)))
        metrics = first['coverage']['semantics']['literalReviewRetention']
        self.assertEqual(first['coverage']['literalReview']['admittedEntries'], 1)
        self.assertEqual((metrics['admittedEntries'], metrics['retainedOccurrences'], metrics['unretainedOccurrences']), (1, 0, 1))
        self.assertEqual(metrics['state'], 'PARTIAL')
        self.assertEqual(metrics['filesWithUnretainedOccurrences'], 1)
        self.assertEqual(first['coverage']['semantics']['reasonCounts']['admitted_literal_not_retained'], 1)
        self.assertFalse(first['coverage']['semanticComplete'])
        self.assertEqual(store.status(self.workspace, first['snapshotId'])['coverage']['semantics']['literalReviewRetention'], metrics)
        coverage = next(row for row in store.iter_records(self.workspace, first['snapshotId'])
                        if row.get('name') == 'SemanticCoverage')
        self.assertEqual(coverage['coverage']['literalReviewDelivery']['notRetainedRequestIndices'], [0])
        repaired = store.sync(self.workspace, force=True)
        after = repaired['coverage']['semantics']['literalReviewRetention']
        self.assertEqual((after['admittedEntries'], after['retainedOccurrences'], after['unretainedOccurrences']), (1, 1, 0))
        self.assertEqual(after['state'], 'COMPLETE')
        self.assertFalse(repaired['coverage']['semanticComplete'])
        self.assertEqual(store.status(self.workspace, first['snapshotId'])['coverage']['semantics']['literalReviewRetention'], metrics)

    def test_invalid_manifest_not_persisted_and_unknown_path_not_silently_skipped(self):
        store.initialize(self.repo, self.workspace)
        original = (self.workspace / 'pipeline.json').read_bytes()
        for invalid in ('extra_value', 'wrong_path', 'duplicate'):
            value = self.review()
            if invalid == 'extra_value':
                value['entries'][0]['rawValue'] = 'not part of contract'
            elif invalid == 'wrong_path':
                value['entries'][0]['path'] = 'Absent.java'
            else:
                value['entries'].append(copy.deepcopy(value['entries'][0]))
            with self.subTest(invalid=invalid), self.assertRaises(store.PipelineError):
                store.sync(self.workspace, literal_review=value)
            self.assertEqual((self.workspace / 'pipeline.json').read_bytes(), original)

    def test_resume_revalidates_occurrences_without_duplicate_records(self):
        def crash(stage):
            if stage == 'after_file':
                raise OSError('synthetic interruption')
        with patch.object(store, '_checkpoint', crash), self.assertRaises(OSError):
            store.initialize(self.repo, self.workspace, literal_review=self.review())
        recovered = store.recover(self.workspace)
        self.assertEqual(recovered['coverage']['literalReview']['admittedEntries'], 2)
        records = list(store.iter_records(self.workspace))
        self.assertEqual(len(records), recovered['recordCount'])
        self.assertEqual(len({row['id'] for row in records}), len(records))
        self.assertEqual(set(self.values()), {'READY', 'PASS'})

    def test_rejected_token_remains_in_source_and_semantic_coverage(self):
        contract = self.review()
        contract['entries'][0]['tokenSha256'] = '0' * 64
        result = store.initialize(self.repo, self.workspace, literal_review=contract)
        self.assertEqual(result['coverage']['literalReview']['requestedEntries'], 2)
        self.assertEqual(result['coverage']['literalReview']['rejectedEntries'], 1)
        self.assertEqual(set(self.values()), {'PASS'})
        with store.open_reader(self.workspace) as reader:
            coverage = reader.coverage()
            self.assertEqual(coverage['total'], 1)
            self.assertEqual(coverage['entries'][0]['literalReview']['rejectedEntries'], 1)
        rows = list(store.iter_records(self.workspace))
        semantic = [row for row in rows if row.get('name') == 'SemanticCoverage']
        self.assertEqual(semantic[0]['coverage']['literalReview']['requestedEntries'], 2)
        self.assertEqual(result['coverage']['completeness'], 'PARTIAL')

    def test_explicit_file_loader_requires_private_contract(self):
        path = self.root / 'review.json'
        path.write_text(json.dumps(self.review()), encoding='utf-8')
        protect_private_path(path)
        self.assertEqual(store.load_literal_review(path), self.review())
        if os.name != 'nt':
            path.chmod(0o644)
            with self.assertRaises((store.PipelineError, privacy_guard.PrivacyError)):
                store.load_literal_review(path)


if __name__ == '__main__':
    unittest.main()
