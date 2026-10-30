"""Declaration accounting survives source-offline human and policy views."""
import copy
import html
import json
import unittest
from unittest.mock import patch

import test_business_query as fixture
import pipeline_policy as policy


class DeclarationCoverageChannelsTests(unittest.TestCase):
    setUp = fixture.BusinessQueryTests.setUp
    args = fixture.BusinessQueryTests.args
    call = fixture.BusinessQueryTests.call
    candidate = fixture.BusinessQueryTests.candidate
    reviewed = fixture.BusinessQueryTests.reviewed

    def typescript(self, text):
        root = self.root / 'declaration-source'
        root.mkdir()
        (root / 'model.ts').write_text(text)
        self.workspace = self.root / 'declaration-knowledge'
        self.sid = fixture.source.initialize(root, self.workspace,
            prepare_workspace=fixture.acl.initialize_access)['snapshotId']
        fixture.access.register(str(self.workspace))
        self.wid = fixture.access.config(self.workspace)['workspaceId']
        self.meta = self.store.build(self.workspace, self.sid)
        root.rename(self.root / 'declaration-source-offline')

    def table(self):
        return self.call('ontology_pipeline_coverage')['summary']['sourceDeclarationCoverage']

    def test_source_offline_mcp_and_all_five_human_views_preserve_counts(self):
        self.typescript('class First {} class Last {active: boolean;} '
                        'function eligible(active: boolean): boolean {return active;}')
        table = self.table()
        self.assertEqual(table['detectedDeclarations'], 2)
        self.assertEqual(table['recordedDeclarations'], 2)
        self.assertEqual(table['omittedDeclarations'], 0)
        self.assertFalse(table['businessPolicyComplete'])
        with fixture.source.open_reader(self.workspace, self.sid) as reader:
            source = reader.read_policy_records()
        self.assertEqual(table, source['coverage']['sourceDeclarationCoverage'])
        self.assertEqual(source['coverage']['analyzedRules'], 1)
        import pipeline_html
        output = self.root / 'declaration-human'
        profile = fixture.companion.privacy_guard.load_profile()
        with patch.object(pipeline_html.privacy_guard, 'load_profile', return_value=profile):
            result = pipeline_html.render_pipeline(self.workspace, self.sid, output)
        for language in ('ko', 'en', 'ja', 'zh-CN', 'ru'):
            for page in (output / language / 'catalog.html',
                         output / 'business' / language / 'index.html'):
                content = html.unescape(page.read_text())
                self.assertIn('sourceDeclarationCoverage', content)
                for key in ('detectedDeclarations', 'recordedDeclarations', 'omittedDeclarations'):
                    self.assertIn(json.dumps(key), content)
            self.assertIn('ontology-data', (output / language / 'index.html').read_text())
        self.assertEqual(result['outputBytes'], sum(p.stat().st_size for p in output.rglob('*') if p.is_file()))

    def test_absent_or_legacy_table_is_unknown_and_never_invented_zero(self):
        table = self.table()
        for key in ('detectedDeclarations', 'recordedDeclarations', 'unsupportedDeclarations', 'omittedDeclarations'):
            self.assertEqual(table[key], 'UNKNOWN')
        self.assertTrue(table['unknownDenominator'])
        self.assertFalse(table['inventoryComplete'])
        self.assertEqual(policy.declaration_coverage_summary(None), table)

    def test_review_and_revocation_retain_original_source_denominator(self):
        self.typescript('class Model {} function eligible(active: boolean): boolean {return active;}')
        original = self.table()
        reviewed = self.reviewed()
        summary = self.call('ontology_pipeline_coverage')['summary']
        self.assertEqual(summary['sourceCandidates']['sourceDeclarationCoverage'], original)
        self.meta = self.store.revoke(self.workspace, self.sid, self.meta['businessSnapshotId'],
            self.meta['businessDigest'], [reviewed['id']])
        summary = self.call('ontology_pipeline_coverage')['summary']
        self.assertEqual(summary['sourceCandidates']['sourceDeclarationCoverage'], original)
        self.assertEqual(summary['globalCompleteness'], 'UNKNOWN')

    def test_unsupported_inventory_and_closed_projection_keep_failures_visible(self):
        self.typescript('class Model {active: boolean = true;} '
                        'function eligible(active: boolean): boolean {return active;}')
        table = self.table()
        self.assertEqual(table['detectedDeclarations'], 1)
        self.assertEqual(table['unsupportedDeclarations'], 1)
        self.assertIn('unsupported_typescript_declaration', table['reasons'])
        for key, value in (('detectedDeclarations', True), ('scope', 'PRIVATE_SENTINEL'),
                           ('reasons', ['PRIVATE_SENTINEL']), ('reasons', [{}]),
                           ('omittedDeclarations', -1), ('unexpected', 'PRIVATE_SENTINEL')):
            broken = copy.deepcopy(table)
            broken[key] = value
            with self.subTest(field=key), self.assertRaises(policy.PolicyError) as raised:
                self.query._coverage({'sourceDeclarationCoverage': broken})
            self.assertNotIn('PRIVATE_SENTINEL', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
