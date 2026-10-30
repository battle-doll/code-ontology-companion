"""Finite local initializer proofs retain platform ancestry across records."""
import copy
import json
import os
import shutil
import unittest
from unittest.mock import patch

from test_policy_java_contracts import extract, returns, bindings, policy_semantics
from test_policy_dependency_closure import analyzed_files, finish
from test_policy_literal_review import reviewed, occurrence
from test_java_platform_inheritance import platform


def source(body, parameters='BigDecimal input', extra='', parent='implements Runnable'):
    return ('import java.math.BigDecimal;class Rules ' + parent + '{public void run(){}'
        + extra + 'Object f(' + parameters + '){' + body + '}}')


def declarations(result):
    return [f for f in result['fragments'] if f['category'] == 'local_declaration']


def methods(row):
    return [c['method'] for _, c in bindings(row)]


class LocalPlatformCompositionTests(unittest.TestCase):
    def test_one_and_two_local_edges_reference_actual_upstream_slots(self):
        for body in ('var value=input;return value.abs();',
                     'var first=input;var value=first;return value.abs();'):
            with self.subTest(body=body):
                result, facts = extract(source(body))
                self.assertEqual(methods(returns(result)[-1]), ['abs'])
                providers = {f['id']: f for f in result['fragments']}
                edges = 0
                for consumer in result['fragments']:
                    for proof in consumer.get('platformTypeProofs', []):
                        origin = proof.get('origin', {})
                        if origin.get('kind') != 'local_initializer': continue
                        edges += 1
                        provider = providers[origin['recordId']]
                        typed = platform.pointer(consumer, proof['consumer'])
                        upstream = platform.pointer(provider, origin['selector'])
                        self.assertEqual(origin['selector'], '/expression/staticType')
                        self.assertEqual(origin['proofId'], upstream['platformInheritance']['proofId'])
                        self.assertNotEqual(proof['id'], origin['proofId'])
                        self.assertEqual(typed['localTypeBinding'], provider['localTypeInference'])
                        self.assertEqual(typed['sourceEvidenceIds'], [provider['id']])
                        self.assertEqual(typed['localTypeBinding']['runtimeValue'], 'UNKNOWN')
                        for key in proof['checkIds']:
                            emitted = next(c for c in consumer['platformInheritanceChecks'] if c['id'] == key)
                            upstream_check = next(c for c in provider['platformInheritanceChecks'] if c['id'] == key)
                            self.assertEqual(emitted, upstream_check)
                self.assertEqual(edges, len(declarations(result)))
                self.assertFalse(any(f.get('dependencyClosure') for f in result['fragments']))
                self.assertFalse(any(r.get('kind') == 'callsite' and r.get('name') == 'abs'
                    and r.get('resolution') == 'exact' for r in facts['records']))

    def test_array_primitive_api_constructor_and_exact_source_call_origins(self):
        cases = [
            (source('var value=input;return value;', 'BigDecimal[] input'), [], 'java.math.BigDecimal[]'),
            (source('var sign=input.signum();return Math.max(sign,0);'), ['max'], 'int'),
            (source('var value=new BigDecimal(3);return value.abs();'), ['abs'], 'java.math.BigDecimal'),
            (source('var value=make(input);return value.abs();', extra='BigDecimal make(BigDecimal n){return n;}'), ['abs'], 'java.math.BigDecimal'),
        ]
        for text, expected, typename in cases:
            with self.subTest(text=text):
                result, _ = extract(text); row = returns(result)[-1]
                self.assertEqual(methods(row), expected)
                self.assertEqual(row['expression']['staticType']['name'], typename)

    def test_unknown_and_lexical_boundaries_stay_unknown(self):
        cases = [
            source('var value=missing();return value.abs();'),
            source('var value=null;return value.abs();'),
            source('{var value=input;}return value.abs();'),
            source('var value=input;{Object value=unknown();return value.abs();}'),
            source('var value=input;return value.abs();', parent='extends Unselected'),
            source('class Nested{String input;Object read(){var value=input;return value.abs();}}return null;'),
            source('var value=input;return value.abs();', extra='class BigDecimal{}'),
        ]
        for text in cases:
            with self.subTest(text=text):
                result, _ = extract(text)
                self.assertFalse(any(bindings(f) for f in result['fragments']))

    def test_sensitive_initializer_never_acquires_local_or_api_value_proof(self):
        text = source('var secretValue=new BigDecimal(87162345);return secretValue.abs();')
        result, _ = extract(text)
        self.assertNotIn('87162345', json.dumps(result))
        self.assertFalse(any(bindings(f) for f in result['fragments']))
        self.assertFalse(any(f.get('localTypeInference', {}).get('status') == 'source_initializer_static_type'
            for f in result['fragments']))

    def test_missing_revoked_and_stale_initializer_withdraw_only_dependent_branch(self):
        text = source('var value=input;return join(value.abs(),Math.abs(2));')
        for fault in ('missing', 'revoked', 'digest', 'origin', 'type', 'proof', 'check'):
            with self.subTest(fault=fault):
                results, facts = analyzed_files({'Rules.java': text})
                result = results['Rules.java']; local = declarations(result)[0]
                if fault == 'missing': result['fragments'].remove(local)
                if fault == 'revoked': local.update(expression=None, representationStatus='unsupported', unsupportedReasons=['literal_review_revoked'])
                if fault == 'digest': local['sourceDigest'] = '0' * 64
                if fault == 'origin': local['platformTypeProofs'][0]['origin']['recordId'] = 'p:missing'
                if fault == 'type': local['expression']['staticType']['name'] = 'java.time.Duration'
                if fault == 'proof': local['platformTypeProofs'] = []
                if fault == 'check': local['platformInheritanceChecks'] = []
                finish(results, facts)
                row = returns(result)[-1]
                self.assertEqual([(c['declaringType'], c['method']) for _, c in bindings(row)], [('java.lang.Math', 'abs')])
                self.assertEqual(row['expression']['arguments'][0]['staticContractStatus']['status'], 'UNKNOWN')
                self.assertEqual(row['expression']['arguments'][1]['arguments'][0]['value'], '2')

    def test_wrong_provider_selector_scope_and_lexical_reference_fail_closed(self):
        text = source('var first=input;var value=input;return join(value.abs(),Math.abs(2));')
        for fault in ('donor', 'selector', 'proofId', 'path', 'digest', 'reference', 'scope', 'owner'):
            with self.subTest(fault=fault):
                results, facts = analyzed_files({'Rules.java': text})
                result = results['Rules.java']; row = returns(result)[-1]
                first, local = declarations(result)
                proof = next(d for d in row['platformTypeProofs'] if d.get('origin', {}).get('kind') == 'local_initializer')
                origin = proof['origin']
                if fault == 'donor':
                    origin['recordId'] = first['id']
                    origin['proofId'] = first['expression']['staticType']['platformInheritance']['proofId']
                if fault == 'selector': origin['selector'] = '/expression'
                if fault == 'proofId': origin['proofId'] = first['expression']['staticType']['platformInheritance']['proofId']
                if fault == 'path': origin['path'] = 'Other.java'
                if fault == 'digest': origin['sourceDigest'] = '0' * 64
                if fault == 'reference': row['references'] = [r for r in row['references'] if r['name'] != 'value']
                if fault == 'scope': row['sourceRange']['charStart'] = local['sourceRange']['charStart']
                if fault == 'owner': row['javaSourceOwner']['callableSymbolId'] = 'p:missing'
                finish(results, facts)
                self.assertNotIn('java.math.BigDecimal', [c['declaringType'] for _, c in bindings(row)])
                # A whole-fragment owner/source-range mutation also invalidates
                # Math's own source correspondence, so only local faults assert
                # an independent surviving sibling.
                if fault not in {'scope', 'owner'}:
                    self.assertEqual([c['declaringType'] for _, c in bindings(row)], ['java.lang.Math'])

    def test_consumer_cache_alias_revalidates_local_derived_result(self):
        text = source('var value=input;return value.abs();')
        for donor_first in (False, True):
            for claimed in ('java.time.Duration', 'int', 'java.math.BigDecimal[]'):
                with self.subTest(donor_first=donor_first, claimed=claimed):
                    results, facts = analyzed_files({'Rules.java': text}); row = returns(results['Rules.java'])[-1]
                    lookup = finish(results, facts)
                    call = row['expression']; call['staticType']['name'] = claimed
                    call['staticType']['platformInheritance'] = copy.deepcopy(call['staticContract']['platformInheritance'])
                    # Force both consumer encounter orders without relying on
                    # Python's hash seed or a shared proof-validation cache.
                    value = {'first': call['staticContract'] if donor_first else call['staticType'],
                             'second': call['staticType'] if donor_first else call['staticContract']}
                    _, reason = platform.requirements(value, row, lookup=lookup,
                        api_validator=policy_semantics.policy_java_contracts.validate_catalog_entry)
                    self.assertEqual(reason, 'platform_type_consumer_binding_invalid')
                    finish(results, facts)
                    self.assertFalse(bindings(row))
                    self.assertNotIn('staticType', call)
                    self.assertEqual(call['staticContractStatus']['status'], 'UNKNOWN')

    def test_equal_duplicate_definitions_are_allowed_conflicts_are_not(self):
        text = source('var value=input;return join(value.abs(),Math.abs(2));')
        for key in ('platformTypeProofs', 'platformInheritanceChecks', 'platformTypeContracts'):
            for conflict in (False, True):
                for first in (False, True):
                    with self.subTest(key=key, conflict=conflict, first=first):
                        results, facts = analyzed_files({'Rules.java': text})
                        provider = declarations(results['Rules.java'])[0]
                        duplicate = copy.deepcopy(provider[key][0])
                        if conflict: duplicate['mutation'] = True
                        provider[key].insert(0 if first else len(provider[key]), duplicate)
                        finish(results, facts)
                        row = returns(results['Rules.java'])[-1]
                        owners = [c['declaringType'] for _, c in bindings(row)]
                        self.assertEqual('java.math.BigDecimal' in owners, not conflict)
                        self.assertIn('java.lang.Math', owners)

    def test_cross_record_cycle_and_depth_are_bounded(self):
        text = source('var first=input;var value=first;return value.abs();')
        results, facts = analyzed_files({'Rules.java': text}); result = results['Rules.java']
        first, last = declarations(result)
        origin = next(d['origin'] for d in last['platformTypeProofs'] if d.get('origin', {}).get('kind') == 'local_initializer')
        origin['recordId'] = last['id']; origin['proofId'] = last['expression']['staticType']['platformInheritance']['proofId']
        finish(results, facts)
        self.assertFalse(bindings(returns(result)[-1]))
        # Existing 32-record proof limit is unchanged; no recursive tree copy.
        body = 'var v0=input;' + ''.join('var v%d=v%d;' % (i, i - 1) for i in range(1, 34)) + 'return v33.abs();'
        result, _ = extract(source(body))
        self.assertFalse(bindings(returns(result)[-1]))
        reasons = {f.get('localTypeInference', {}).get('reason') for f in result['fragments']}
        self.assertIn('local_initializer_dependency_depth_exceeded', reasons)
        self.assertEqual(len(declarations(result)), 34)
        results, facts = analyzed_files({'Rules.java': text}); lookup = finish(results, facts)
        row = returns(results['Rules.java'])[-1]
        _, reason = platform.requirements(row['expression'], row, lookup=lookup,
            api_validator=policy_semantics.policy_java_contracts.validate_catalog_entry,
            _proof_trail=(('prior', '/expression/staticType'),) * 32)
        self.assertEqual(reason, 'platform_type_proof_cycle_or_depth_exceeded')

    def test_projection_budget_refuses_import_without_removing_source_ast(self):
        text = source('var value=input;return value.abs();')
        original = platform.Projection.local_initializer
        def limited(projection, typed, provider):
            with patch.object(platform, 'MAX_CATALOG_BYTES', 1):
                return original(projection, typed, provider)
        with patch.object(platform.Projection, 'local_initializer', limited):
            result, _ = extract(text)
        row = returns(result)[-1]
        self.assertFalse(bindings(row))
        self.assertEqual(row['expression']['callee']['name'], 'value.abs')
        self.assertEqual(row['platformInheritanceCoverage']['status'], 'PARTIAL')
        self.assertEqual(len(result['fragments']), 2)

    def test_late_literal_review_revocation_closes_transitive_local_proof(self):
        text = source('var first=new BigDecimal("0.5");var value=first;'
            'consume("TRIGGER_MODE");return join(value.abs(),Math.abs(2));', extra='void consume(String s){}')
        review, digest = reviewed(text, [occurrence(text, '"0.5"'), occurrence(text, '"TRIGGER_MODE"')])
        bound = review.bind_source('Rules.java', text, digest); admit = bound.admit
        def revoke(start, end, **kwargs):
            if start == text.index('"TRIGGER_MODE"'): review.reject(0, 'fragment_redacted')
            return admit(start, end, **kwargs)
        bound.admit = revoke
        results, facts = analyzed_files({'Rules.java': text}, review=review)
        finish(results, facts)
        row = returns(results['Rules.java'])[-1]
        self.assertEqual([c['declaringType'] for _, c in bindings(row)], ['java.lang.Math'])
        self.assertNotIn('0.5', json.dumps(results))

    def test_sealed_source_free_mcp_retains_actual_initializer_definitions(self):
        import test_semantic_delivery as delivery
        import test_pipeline_mcp as mcp
        fixture = delivery.SemanticDeliveryTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        text = source('var first=input;var value=first;return value.abs();')
        (fixture.repo / 'Rules.java').write_text(text)
        with patch.dict(os.environ, {'CODE_ONTOLOGY_HOME': str(fixture.root / 'registry')}):
            snapshot = fixture.initialize()
            mcp.access.register(str(fixture.workspace))
            args = {'workspace_id': snapshot['workspaceId'], 'snapshot_id': snapshot['snapshotId'],
                'kind': 'semantic_fragment', 'limit': 100}
            request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'ontology_pipeline_search', 'arguments': args}}
            before = mcp.server._handle(request)['result']
            self.assertFalse(before['isError'])
            shutil.rmtree(fixture.repo)
            after = mcp.server._handle(request)['result']
            self.assertEqual(before, after)
            rows = after['structuredContent']['data']['records']
            returned = next(r for r in rows if r.get('category') == 'return')
            self.assertEqual(methods(returned), ['abs'])
            providers = {r['id']: r for r in rows}
            for row in rows:
                for proof in row.get('platformTypeProofs', []):
                    origin = proof.get('origin', {})
                    if origin.get('kind') != 'local_initializer': continue
                    provider = providers[origin['recordId']]
                    upstream = platform.pointer(provider, origin['selector'])
                    self.assertEqual(upstream['platformInheritance']['proofId'], origin['proofId'])
                    self.assertEqual(provider['sourceDigest'], row['sourceDigest'])
            self.assertFalse(returned['businessMeaningVerified'])
            self.assertEqual(returned['runtimeStatus'], 'not_observed')


if __name__ == '__main__':
    unittest.main()
