"""Bounded function outcome accounting; diagnostics are never policy proof."""
import copy
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'))
import pipeline_policy as policy
import pipeline_store as store
import privacy_guard


def extract(text, language='Python', path='neutral.py', **options):
    return policy.extract_policy_rules(text, language, path, hashlib.sha256(text.encode()).hexdigest(), **options)


class FunctionOutcomeTests(unittest.TestCase):
    def setUp(self):
        profile = privacy_guard.build_profile(['Neutral C31 Private Person'], [], key=b'k' * 32)
        self.guard = patch.object(privacy_guard, 'load_profile', return_value=profile)
        self.guard.start(); self.addCleanup(self.guard.stop)

    def test_each_neighbor_has_original_locator_and_outcome(self):
        text = ('def before(n: int) -> int:\n    return external(n)\n'
                'def middle(n: int) -> int:\n    return n + 3\n'
                'def after(n: int) -> int:\n    return missing(n)\n')
        result = extract(text)
        rows = result['sourceFunctionOutcomes']
        self.assertEqual([r['span'] for r in rows], [dict(lineStart=n, lineEnd=n+1) for n in (1, 3, 5)])
        self.assertEqual([r['expression']['disposition'] for r in rows], ['unsupported', 'extracted', 'unsupported'])
        self.assertEqual([r['expression']['reason'] for r in rows], ['unresolved_call', None, 'unresolved_call'])
        self.assertEqual(rows[1]['expression']['acceptedPolicyRuleId'], result['rules'][0]['id'])
        self.assertEqual(len({r['id'] for r in rows}), 3)
        summary = result['coverage']['sourceFunctionProcessing']
        self.assertEqual((summary['recognizedFunctions'], summary['unsupportedFunctions'], summary['serializedOutcomes']), (3, 2, 3))
        self.assertTrue(summary['inventoryComplete'])
        self.assertFalse(result['coverage']['complete'])
        self.assertFalse(summary['businessPolicyComplete'])
        self.assertEqual(summary['wholeSourceFunctionDenominator'], 'UNKNOWN')
        self.assertTrue(all(r['representationStatus'] == 'coverage_metadata' for r in rows))

    def test_nested_class_and_async_functions_keep_diagnostic_denominator(self):
        text = ('def outer(n: int) -> int:\n    def inner(v: int) -> int:\n        return v\n    return n\n'
                'class Container:\n    def member(self, v: int) -> int:\n        return v\n'
                'async def async_value(v: int) -> int:\n    return v\n')
        result = extract(text)
        rows = result['sourceFunctionOutcomes']
        self.assertEqual(len(rows), 4)
        self.assertEqual([r['span']['lineStart'] for r in rows], [1, 2, 6, 8])
        self.assertTrue(all(r['expression']['disposition'] == 'unsupported' for r in rows))
        self.assertEqual(result['coverage']['sourceFunctionProcessing']['unsupportedFunctions'], 4)

    def test_rule_budget_does_not_silently_drop_remaining_candidates(self):
        text = ''.join('def f%d(n: int) -> int:\n    return n + %d\n' % (i, i) for i in range(4))
        result = extract(text, max_rules=1)
        self.assertEqual(len(result['rules']), 1)
        outcomes = [r['expression'] for r in result['sourceFunctionOutcomes']]
        self.assertEqual([o['disposition'] for o in outcomes], ['extracted'] + ['not_analyzed'] * 3)
        self.assertTrue(all(o['reason'] == 'rule_budget' for o in outcomes[1:]))
        self.assertEqual(result['coverage']['sourceFunctionProcessing']['notAnalyzedFunctions'], 3)

    def test_zero_one_and_maximum_outcome_capacity_preserve_summary(self):
        text = 'def one(n: int) -> int:\n    return n\ndef two(n: int) -> int:\n    return lookup(n)\n'
        for cap in (0, 1, policy.MAX_RULES):
            with self.subTest(cap=cap):
                result = extract(text, max_declarations=cap)
                count = min(cap, 2)
                summary = result['coverage']['sourceFunctionProcessing']
                self.assertEqual((summary['recognizedFunctions'], summary['serializedOutcomes'], summary['omittedOutcomes']), (2, count, 2-count))
                self.assertEqual(len(result['sourceFunctionOutcomes']), count)
                self.assertEqual(summary['inventoryComplete'], count == 2)
                snapshot = policy.seal_policy_snapshot([result], catalog_snapshot_id='catalog:neutral', policy_snapshot_id='policy:neutral', created_at='2030-01-01T00:00:00Z')
                self.assertEqual(policy.query_policy_rules(snapshot)['coverage']['sourceFunctionProcessing'], summary)

    def test_existing_typescript_declarations_get_capacity_first(self):
        text = 'class Row { value: number; } export function check(active: boolean): boolean { return active; }'
        result = extract(text, 'TypeScript', 'neutral.ts', max_declarations=1)
        self.assertEqual(result['coverage']['sourceDeclarationCoverage']['recordedDeclarations'], 1)
        self.assertNotEqual(result['sourceDeclarations'][0]['expression'].get('declarationKind'), 'policy_function_processing')
        self.assertEqual(result['sourceFunctionOutcomes'], [])
        summary = result['coverage']['sourceFunctionProcessing']
        self.assertGreater(summary['recognizedFunctions'], 0)
        self.assertEqual(summary['serializedOutcomes'], 0)
        self.assertEqual(summary['omittedOutcomes'], summary['recognizedFunctions'])

    def test_java_same_line_candidates_have_distinct_ordinals(self):
        text = 'class Test { static boolean first(boolean x) { return x; } static boolean last(boolean y) { return external(y); } }'
        result = extract(text, 'Java', 'Test.java')
        rows = result['sourceFunctionOutcomes']
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r['id'] for r in rows}), 2)
        self.assertEqual([r['expression']['inputIndex'] for r in rows], [0, 1])
        self.assertTrue(any(r['expression']['disposition'] == 'unsupported' for r in rows))

    def test_parse_and_ast_limits_never_claim_complete_enumeration(self):
        for text, options in [('def broken(', {}), ('def good(n: int) -> int:\n    return n + 2\n', {'max_ast_nodes': 1})]:
            result = extract(text, **options)
            summary = result['coverage']['sourceFunctionProcessing']
            self.assertTrue(summary['unknownDenominator'])
            self.assertFalse(summary['inventoryComplete'])
            self.assertFalse(result['coverage']['complete'])
            self.assertTrue(summary['reasons'])

    def test_denied_function_name_is_not_repeated_or_hashed_in_outcome(self):
        marker = 'PrivateNeutralFunction'
        profile = privacy_guard.build_profile([marker], [], key=b'z' * 32)
        with patch.object(privacy_guard, 'load_profile', return_value=profile):
            result = extract('def ' + marker + '(n: int) -> int:\n    return n\n')
        row = result['sourceFunctionOutcomes'][0]
        self.assertEqual(row['expression']['reason'], 'privacy_denied')
        self.assertNotIn(marker, json.dumps(row))
        self.assertIsNone(row['expression']['acceptedPolicyRuleId'])

    def test_summary_rejects_boolean_counts_and_conservation_forgery(self):
        summary = extract('def f(n: int) -> int:\n    return n\n')['coverage']['sourceFunctionProcessing']
        invalid = []
        for field in policy.FUNCTION_PROCESSING_COUNTS:
            item = copy.deepcopy(summary); item[field] = True; invalid.append(item)
        item = copy.deepcopy(summary); item['serializedOutcomes'] = 0; invalid.append(item)
        item = copy.deepcopy(summary); item['extra'] = 'not allowed'; invalid.append(item)
        unknown = policy.function_processing_summary(None)
        for field, value in [('schemaVersion', True), ('inventoryComplete', 0), ('unknownDenominator', 1), ('businessPolicyComplete', 0)]:
            item = copy.deepcopy(unknown); item[field] = value; invalid.append(item)
        for item in invalid:
            with self.assertRaises(policy.PolicyError): policy.function_processing_summary(item)
        self.assertEqual(policy.function_processing_summary(unknown), unknown)

    def test_legacy_merge_is_unknown_instead_of_zero(self):
        target = {}
        policy.merge_function_processing(target, extract('def f(n: int) -> int:\n    return n\n')['coverage'])
        policy.merge_function_processing(target, {})
        self.assertEqual(target['sourceFunctionProcessing']['recognizedFunctions'], 'UNKNOWN')

    def test_actual_sealed_store_keeps_cap_frontier_and_rows_without_source(self):
        original = policy.extract_policy_rules
        text = 'def ok(n: int) -> int:\n    return n\ndef unknown(n: int) -> int:\n    return remote(n)\n'
        for cap in (0, 1, policy.MAX_RULES):
            with self.subTest(cap=cap), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); repo = root/'repo'; repo.mkdir(); (repo/'rules.py').write_text(text)
                def limited(*args, **kwargs):
                    kwargs['max_declarations'] = cap
                    return original(*args, **kwargs)
                with patch.object(policy, 'extract_policy_rules', side_effect=limited):
                    sid = store.initialize(repo, root/'knowledge')['snapshotId']
                repo.rename(root/'source-offline')
                with store.open_reader(root/'knowledge', sid) as reader:
                    sealed = reader.read_policy_records()
                    summary = policy.query_policy_rules(sealed)['coverage']['sourceFunctionProcessing']
                    self.assertEqual((summary['recognizedFunctions'], summary['serializedOutcomes'], summary['omittedOutcomes']), (2, min(cap, 2), 2-min(cap, 2)))
                    rows = [row for row in reader.iter_records() if (row.get('expression') or {}).get('declarationKind') == 'policy_function_processing']
                    self.assertEqual(len(rows), min(cap, 2))

    def test_source_deleted_offline_html_and_sqlite_keep_exact_outcomes(self):
        import pipeline_acl as acl
        import pipeline_export
        import pipeline_html
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {acl.PRINCIPAL_ENV:'local-owner'}):
            root = Path(directory).resolve(); repo = root/'repo'; repo.mkdir()
            profile_file = root/'profile.json'
            profile_file.write_text(json.dumps(privacy_guard.load_profile())); profile_file.chmod(0o600)
            environment = patch.dict(os.environ, {privacy_guard.PROFILE_ENV:str(profile_file)})
            environment.start(); self.addCleanup(environment.stop)
            (repo/'rules.py').write_text('def first(v: int) -> int:\n    return v\ndef last(v: int) -> int:\n    return external(v)\n')
            workspace = root/'workspace'
            sid = store.initialize(repo, workspace, prepare_workspace=acl.initialize_access)['snapshotId']
            repo.rename(root/'source-offline')
            with store.open_reader(workspace, sid) as reader:
                expected = {r['id']:r for r in reader.iter_records() if r.get('category') == 'source_policy_function_processing'}
            self.assertEqual(len(expected), 2)
            output = root/'human'; pipeline_html.render_pipeline(workspace, sid, output)
            delivered = {}
            for file in (output/'data').glob('*.json'):
                rows = json.loads(file.read_text())['records']
                for row in rows:
                    if row['id'] in expected: delivered[row['id']] = row
                if any(row['id'] in expected for row in rows):
                    for locale in ('ko', 'en', 'ja', 'zh-CN', 'ru'):
                        page = (output/locale/(file.stem+'.html')).read_text()
                        self.assertIn('../data/'+file.name, page)
                        self.assertIn('../data/'+file.stem+'.js', page)
            self.assertEqual(delivered, expected)
            portable = root/'portable'; pipeline_export.export_bundle(workspace, sid, portable)
            with closing(sqlite3.connect('file:'+str(portable/'knowledge.sqlite')+'?mode=ro&immutable=1', uri=True)) as db:
                records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM records ORDER BY id')]
            self.assertEqual({r['id']:r for r in records if r['id'] in expected}, expected)
            self.assertEqual(json.loads((portable/'policy.json').read_text())['coverage']['sourceFunctionProcessing']['recognizedFunctions'], 2)


if __name__ == '__main__':
    unittest.main()
