"""Source-bound record component declarations without constructor-call demand."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_policy_java_contracts import core, extract, pipeline_java, returns, bindings
from test_policy_literal_review import walk
import pipeline_delivery
import pipeline_store
import privacy_guard


def records(facts):
    return [r for r in facts['records'] if r.get('type') == 'Record']


class RecordComponentProjectionTests(unittest.TestCase):
    def test_conflicting_explicit_imports_are_unknown_without_rewriting_the_index(self):
        others = {'one/Value.java': 'package one;public class Value{}',
                  'two/Value.java': 'package two;public class Value{}'}
        for imports in ('import one.Value;import two.Value;',
                        'import two.Value;import one.Value;',
                        'import one . Value;import two . Value;'):
            with self.subTest(imports=imports):
                source = imports + 'record Box(Value value){}'
                declaration = records(extract(source, others)[1])[0]
                component = declaration['recordComponents'][0]
                self.assertEqual((component['type'], component['typeResolution']), (None, 'UNKNOWN'))
                self.assertEqual(component['typeReason'], 'conflicting_explicit_imports')
                self.assertEqual(component['declaredType'], 'Value')
                self.assertEqual(component['declarationStatus'], 'declared')
                self.assertTrue(declaration['recordComponentCoverage']['inventoryComplete'])

    def test_import_near_variants_keep_proven_and_unknown_pairs_separate(self):
        others = {'one/Value.java': 'package one;public class Value{}',
                  'two/Value.java': 'package two;public class Value{}',
                  'one/Outer.java': 'package one;public class Outer{public static class Value{}}',
                  'two/Outer.java': 'package two;public class Outer{public static class Value{}}'}
        cases = [
            ('import one.Value;', 'record Box(Value value){}', 'one.Value'),
            ('import one.Value;import one.Value;', 'record Box(Value value){}', 'one.Value'),
            ('import one.Value;import unknown.api.*;', 'record Box(Value value){}', 'one.Value'),
            ('import one.*;', 'record Box(Value value){}', 'one.Value'),
            ('import one.*;import two.*;', 'record Box(Value value){}', None),
            ('', 'record Box(one.Value value){}', 'one.Value'),
            ('import one.Outer;', 'record Box(Outer.Value value){}', 'one.Outer.Value'),
            ('import one.Outer;import two.Outer;', 'record Box(Outer.Value value){}', None),
            ('import one.Outer;import two.Outer;', 'record Box(Outer . Value value){}', None),
            ('import one.Value;import two.Value;', 'record Box(java.util.List<Value> value){}', None),
            ('import one.Value;', 'record Box<Value>(Value value){}', None),
        ]
        for imports, record, expected in cases:
            with self.subTest(imports=imports, record=record):
                component = records(extract(imports + record, others)[1])[0]['recordComponents'][0]
                self.assertEqual(component['type'], expected)
                self.assertEqual(component['typeResolution'], 'resolved' if expected else 'UNKNOWN')

    def test_void_and_nonfinal_varargs_remain_counted_but_unsupported(self):
        for body, reason in (('void value', 'record_component_void_type_invalid'),
                             ('void[] value', 'record_component_void_type_invalid'),
                             ('java.util.List<void> value', 'record_component_void_type_invalid'),
                             ('String... values,int count', 'record_varargs_component_not_last')):
            with self.subTest(body=body):
                declaration = records(extract('record Broken(' + body + '){}')[1])[0]
                coverage = declaration['recordComponentCoverage']
                self.assertIn(reason, coverage['reasons'])
                self.assertEqual(coverage['status'], 'PARTIAL')
                self.assertFalse(coverage['declarationsComplete'])
                self.assertEqual(coverage['detectedComponents'], coverage['recordedComponents'])
                self.assertTrue(all(c['type'] is None and c['typeResolution'] == 'UNKNOWN' and c['declarationStatus'] == 'unsupported' for c in declaration['recordComponents']))

    def test_final_varargs_and_boxed_void_are_valid_declaration_type_observations(self):
        declaration = records(extract('record Values(java.lang.Void marker,int count,String... values){}')[1])[0]
        self.assertTrue(declaration['recordComponentCoverage']['declarationsComplete'])
        self.assertEqual([c['type'] for c in declaration['recordComponents']],
                         ['java.lang.Void', 'java.lang.int', 'java.lang.String[]'])

    def test_component_field_has_independent_declaration_without_any_constructor_call(self):
        source = 'record Amount(java.math.BigDecimal left,java.math.BigDecimal right){java.math.BigDecimal sum(){return left.add(right);}}'
        result, facts = extract(source)
        declaration = records(facts)[0]
        self.assertFalse(any(r.get('recordConstructorDeclarations') for r in result['fragments']))
        self.assertEqual([c['name'] for c in declaration['recordComponents']], ['left', 'right'])
        self.assertTrue(declaration['recordComponentCoverage']['declarationsComplete'])
        for node in walk(returns(result)[0]):
            proof = node.get('staticFieldBinding', node.get('receiverStaticFieldBinding', {}))
            if proof.get('resolution') != 'declared_record_component_field_type': continue
            self.assertIn(declaration['id'], proof['sourceEvidenceIds'])
            component = next(c for c in declaration['recordComponents'] if c['name'] == proof['name'])
            self.assertEqual(component['sourceRange'], proof['sourceRange'])
            self.assertEqual(component['type'], 'java.math.BigDecimal')
            self.assertEqual(declaration['qualifiedName'], proof['recordType'])
            self.assertEqual(declaration['sourceDigest'], proof['sourceDigest'])
        self.assertTrue(bindings(returns(result)[0]))

    def test_declared_primitive_resolved_and_unknown_pairs_remain_distinct(self):
        source = 'record Values(int count,java.math.BigDecimal amount,Missing value){}'
        declaration = records(extract(source)[1])[0]
        components = declaration['recordComponents']
        self.assertEqual([(c['type'], c['typeResolution']) for c in components],
                         [('java.lang.int', 'primitive'), ('java.math.BigDecimal', 'resolved'), (None, 'UNKNOWN')])
        self.assertEqual(components[-1]['declaredType'], 'Missing')
        self.assertTrue(declaration['recordComponentCoverage']['declarationsComplete'])
        self.assertEqual(declaration['recordComponentCoverage']['runtimeFieldValues'], 'UNKNOWN')

    def test_generic_component_declarations_preserve_unknown_type_variable(self):
        declaration = records(extract('record Holder<T>(T value, java.util.List<T> values){}')[1])[0]
        self.assertEqual(declaration['recordComponents'][0]['declaredType'], 'T')
        self.assertIsNone(declaration['recordComponents'][0]['type'])
        self.assertEqual(declaration['recordComponents'][0]['typeResolution'], 'UNKNOWN')
        self.assertEqual(declaration['recordComponents'][0]['typeReason'], 'lexical_type_parameter')
        self.assertEqual(declaration['recordComponents'][1]['type'], 'java.util.List')

    def test_method_type_shadow_does_not_rewrite_record_header_or_gain_value_contract(self):
        source = 'import java.math.BigDecimal;record Values(BigDecimal amount){<BigDecimal> Object f(){return amount.abs();}}'
        result, facts = extract(source)
        self.assertEqual(records(facts)[0]['recordComponents'][0]['type'], 'java.math.BigDecimal')
        self.assertFalse(any(bindings(r) for r in returns(result)))
        source = 'record Values<BigDecimal>(BigDecimal amount){}'
        component = records(extract(source)[1])[0]['recordComponents'][0]
        self.assertEqual((component['type'], component['typeResolution']), (None, 'UNKNOWN'))

    def test_time_import_proof_and_unknown_wildcard_ambiguity_match_binding(self):
        for imports, expected in (
                ('import java.time.*;', 'java.time.Instant'),
                ('import java.time.Instant;', 'java.time.Instant'),
                ('import java.time.*;import unknown.api.*;', None)):
            with self.subTest(imports=imports):
                declaration = records(extract(imports + 'record TimeCase(Instant start){}')[1])[0]
                self.assertEqual(declaration['recordComponents'][0]['type'], expected)

    def test_crlf_and_nonascii_source_positions_bind_exact_component_tokens(self):
        source = '// 한글 😀\r\nrecord Values(\r\n @Flag("문자열") java.math.BigDecimal amount,\r\n int count\r\n){}'
        declaration = records(extract(source)[1])[0]
        header = declaration['recordHeaderRange']; outer = declaration['sourceRange']
        self.assertEqual(source[header['charStart']], '(')
        self.assertEqual(source[header['charEnd'] - 1], ')')
        self.assertLess(outer['charStart'], header['charStart'])
        self.assertGreater(outer['charEnd'], header['charEnd'])
        for component in declaration['recordComponents']:
            span = component['sourceRange']
            self.assertTrue(source[span['charStart']:span['charEnd']].endswith(component['name']))
            self.assertLessEqual(header['charStart'], span['charStart'])
            self.assertLessEqual(span['charEnd'], header['charEnd'])
        self.assertNotIn('문자열', json.dumps(declaration['recordComponents'], ensure_ascii=False))
        self.assertEqual(declaration['sourceDigest'], hashlib.sha256(source.encode()).hexdigest())

    def test_annotation_values_are_removed_before_any_new_type_metadata(self):
        bodies = [
            '@Flag("ANNOTATION_SENTINEL") java.math.BigDecimal amount',
            '@Flag(number=87162345, nested=@Other(value="NESTED_SENTINEL")) String label',
            '@Flag(values={"ARRAY_SENTINEL","SECOND_SENTINEL"}) String label',
            'java.util.List<@Flag("TYPE_SENTINEL") String> labels',
            'String @Flag(number=87162345) [] labels',
        ]
        for body in bodies:
            with self.subTest(body=body):
                declaration = records(extract('record Values(' + body + '){}')[1])[0]
                text = json.dumps({k: v for k, v in declaration.items() if k.startswith('record')})
                self.assertNotIn('SENTINEL', text); self.assertNotIn('87162345', text)
                self.assertNotIn('@Flag', text); self.assertNotIn('@Other', text)
                self.assertEqual(declaration['recordComponents'][0]['declarationStatus'], 'declared')

    def test_malformed_duplicate_and_empty_slots_are_explicit_without_positive_types(self):
        for body in ('int same, String same', 'int first,,String second', 'int count,',
                     'java.util.List<> values', 'int extra String count', 'int value=87162345'):
            with self.subTest(body=body):
                declaration = records(extract('record Values(' + body + '){}')[1])[0]
                coverage = declaration['recordComponentCoverage']
                self.assertEqual(coverage['status'], 'PARTIAL')
                self.assertFalse(coverage['declarationsComplete'])
                self.assertTrue(coverage['reasons'])
                self.assertEqual(coverage['detectedComponents'], coverage['recordedComponents'])
                self.assertTrue(all(c['type'] is None and c['typeResolution'] == 'UNKNOWN' for c in declaration['recordComponents']))
                self.assertNotIn('87162345', json.dumps(declaration['recordComponents']))

    def test_unrecognized_header_does_not_claim_zero_complete_components(self):
        declaration = records(extract('record Broken {}')[1])[0]
        self.assertIsNone(declaration['recordComponentCoverage']['detectedComponents'])
        self.assertFalse(declaration['recordComponentCoverage']['inventoryComplete'])
        self.assertNotIn('recordHeaderRange', declaration)

    def test_unrecognized_malformed_record_headers_do_not_gain_catalogs(self):
        for body in ('java.util.List<String first,int second', 'String[ first,int second',
                     '@Flag(test=1<2) String first,int second'):
            with self.subTest(body=body):
                # The existing declaration index cannot establish this record
                # boundary. The projection must not invent a complete catalog.
                self.assertEqual(records(extract('record Broken(' + body + '){}')[1]), [])

    def test_empty_header_is_a_complete_observed_empty_inventory(self):
        declaration = records(extract('record Empty(){}')[1])[0]
        coverage = declaration['recordComponentCoverage']
        self.assertEqual(declaration['recordComponents'], [])
        self.assertEqual((coverage['detectedComponents'], coverage['recordedComponents'], coverage['omittedComponents']), (0, 0, 0))
        self.assertTrue(coverage['declarationsComplete'])

    def test_projection_limit_does_not_truncate_shared_field_binding_state(self):
        parameters = ','.join('java.math.BigDecimal amount' + str(i) for i in range(65))
        source = 'record Many(' + parameters + '){java.math.BigDecimal last(){return amount64.abs();}}'
        result, facts = extract(source); declaration = records(facts)[0]
        self.assertEqual(len(declaration['recordComponents']), 64)
        coverage = declaration['recordComponentCoverage']
        self.assertEqual((coverage['detectedComponents'], coverage['recordedComponents'], coverage['omittedComponents']), (65, 64, 1))
        self.assertFalse(coverage['inventoryComplete']); self.assertEqual(coverage['status'], 'PARTIAL')
        self.assertTrue(bindings(returns(result)[0]))
        proofs = [n.get('receiverStaticFieldBinding', n.get('staticFieldBinding', {})) for n in walk(returns(result)[0])]
        self.assertTrue(any(p.get('name') == 'amount64' for p in proofs))
        self.assertNotIn('amount64', [c['name'] for c in declaration['recordComponents']])
        self.assertLess(len(json.dumps(pipeline_delivery.normalize_response({'records': [declaration]})).encode()), 256 * 1024)

    def test_enrichment_never_mutates_index_calls_or_creates_accessor_call_edges(self):
        source = 'record Values(int count){int twice(){return count+count;}}class Rules{int f(Values v){return v.twice()+v.count();}}'
        index = core.build_java_index({'Rules.java': source})
        calls = copy.deepcopy(index.calls)
        facts = {'path': 'Rules.java', 'sourceDigest': hashlib.sha256(source.encode()).hexdigest(), 'module': 'synthetic', 'modulePath': '.', 'records': []}
        pipeline_java.enrich(facts, index)
        self.assertEqual(index.calls, calls)
        projected = [r for r in facts['records'] if r['kind'] == 'callsite']
        self.assertEqual({r['id']: r['resolution'] for r in projected},
                         {r['id']: r['resolution'] for r in calls['Rules.java']})
        self.assertFalse(any(r.get('predicate') == 'CALLS' and r.get('object') == records(facts)[0]['id'] for r in facts['records']))

    def test_oversized_projection_text_is_withheld_with_original_inventory_and_ranges(self):
        for body in ('int ' + 'x' * 1025, 'example.' + 'Type' * 257 + ' value'):
            declaration = records(extract('record Bounded(' + body + '){}')[1])[0]
            component = declaration['recordComponents'][0]
            self.assertIsNone(component['name']); self.assertIsNone(component['declaredType'])
            self.assertEqual(component['declarationStatus'], 'unsupported')
            self.assertEqual(component['typeReason'], 'record_component_projection_text_budget_exceeded')
            coverage = declaration['recordComponentCoverage']
            self.assertEqual((coverage['detectedComponents'], coverage['recordedComponents'], coverage['omittedComponents']), (1, 1, 0))
            self.assertEqual(coverage['unsupportedComponents'], 1)
            self.assertFalse(coverage['declarationsComplete'])
            self.assertGreater(component['sourceRange']['charEnd'], component['sourceRange']['charStart'])

    def test_explicit_profile_veto_still_applies_to_declaration_identifiers(self):
        declaration = records(extract('record Values(FictionalIdentity value){}')[1])[0]
        profile = privacy_guard.build_profile(['FictionalIdentity'], [], key=b'x' * 32)
        with self.assertRaises(privacy_guard.PrivacyError):
            privacy_guard.ensure_public_safe(declaration, profile=profile)

    def test_snapshot_read_retains_catalog_after_source_is_hidden(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve(); repo = root / 'source'; repo.mkdir()
            source = 'record Values(java.math.BigDecimal amount){java.math.BigDecimal absolute(){return amount.abs();}}'
            (repo / 'Values.java').write_text(source)
            profile = root / 'profile.json'
            pipeline_store._atomic(profile, privacy_guard.build_profile([], [], key=b'x' * 32))
            with patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile)}):
                workspace = root / 'workspace'
                result = pipeline_store.initialize(repo, workspace)
                rows = list(pipeline_store.iter_records(workspace))
                declaration = next(row for row in rows if row.get('type') == 'Record')
                self.assertEqual(declaration['recordComponents'][0]['type'], 'java.math.BigDecimal')
                self.assertFalse(any(row.get('recordConstructorDeclarations') for row in rows))
                repo.rename(root / 'source-hidden')
                self.assertEqual(pipeline_store.get_record(workspace, result['snapshotId'], declaration['id']), declaration)


if __name__ == '__main__': unittest.main()
