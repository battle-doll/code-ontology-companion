"""Neutral legacy compatibility and source-relation first-issuance boundaries."""
import copy
import hashlib
import json
import unittest

from test_policy_dependency_closure import core, pipeline_java, policy_semantics as semantics
import test_policy_local_inference as local_tests
from test_policy_local_inference import local, methods, returns, finish
from test_policy_conditional_type_precision import fixture, finalize


HELPER = 'class Parcel{int use(int n){return helper(n);}private int helper(int x){return x+1;}}'


def extract(source=HELPER, **kwargs):
    path = 'neutral/Parcel.java'
    digest = hashlib.sha256(source.encode()).hexdigest()
    index = core.build_java_index({path: source})
    facts = {'path': path, 'sourceDigest': digest, 'module': 'neutral', 'modulePath': '.',
             'language': 'Java', 'records': []}
    pipeline_java.enrich(facts, index)
    result = semantics.extract_semantics(source, 'Java', path, digest,
        java_type_context=pipeline_java.semantic_type_context(facts, index), **kwargs)
    return result, facts


def relations(result):
    return [relation for row in result['fragments']
            for relation in row.get('sourceRelations', {}).get('relations', [])]


def callbacks(facts):
    return {'lookup': lambda identity, path=None: next((row for row in facts['records'] if row['id'] == identity), None),
            'inventory_lookup': lambda path: facts['records']}


class SourceRelationStagingRegressionTests(unittest.TestCase):
    def test_nonrecord_construct_has_no_nonexistent_record_pointer(self):
        source = ('import java.math.BigDecimal;class Parcel{'
                  'BigDecimal make(String text){return new BigDecimal(text);}'
                  'BigDecimal use(String text){return make(text).abs();}}')
        for deferred in (False, True):
            result, _ = extract(source, defer_external_dependencies=deferred)
            items = relations(result)
            self.assertTrue(items)
            rows = {row['id']: row for row in result['fragments']}
            for relation in items:
                for ref in relation['sourceEvidenceRefs']:
                    if ref['recordId'] in rows:
                        semantics._source_pointer(rows[ref['recordId']], ref['jsonPointer'])
            self.assertFalse(any(ref['jsonPointer'] == '/recordConstructorDeclarations'
                for relation in items for ref in relation['sourceEvidenceRefs']))
            self.assertTrue(any(row['expression'].get('staticType', {}).get('name') == 'java.math.BigDecimal'
                for row in result['fragments'] if row['category'] == 'return'))

    def test_deferred_legacy_has_no_future_relation_validation_authority(self):
        result, facts = extract(defer_external_dependencies=True)
        target = relations(result)[0]
        self.assertEqual(target['resolution'], 'unknown')
        self.assertEqual(target['validation'], {'status': 'invalidated',
            'reason': 'source_relation_admissibility_unsealed'})
        self.assertEqual(result['coverage']['sourceRelations']['unknown'], 1)
        self.assertEqual(result['coverage']['sourceRelations']['detected'], 1)
        # Existing source-declaration type evidence remains a separate proof.
        self.assertEqual(result['fragments'][0]['expression']['staticType']['name'], 'int')
        before = copy.deepcopy(result)
        for kwargs in ({}, {'inventory_lookup': None}):
            semantics.finalize_dependencies(result, lookup=callbacks(facts)['lookup'], **kwargs)
            self.assertEqual(result, before)

    def test_unverified_legacy_candidate_cannot_upgrade_with_later_inventory(self):
        result, facts = extract(defer_external_dependencies=True)
        before = copy.deepcopy(relations(result)[0])
        for context in (None, semantics.SourceRelationBuildContext()):
            semantics.finalize_dependencies(result, source_relation_context=context, **callbacks(facts))
            self.assertEqual(relations(result)[0], before)
            self.assertNotEqual(relations(result)[0]['validation']['status'], 'verified_emitted_ir')

    def test_official_first_seal_requires_complete_current_inventory(self):
        for inventory_mode in ('omitted', 'none', 'empty', 'complete'):
            with self.subTest(inventory=inventory_mode):
                context = semantics.SourceRelationBuildContext()
                result, facts = extract(defer_external_dependencies=True, source_relation_context=context)
                target = relations(result)[0]
                self.assertNotIn('validation', target)
                args = callbacks(facts)
                if inventory_mode == 'omitted': args.pop('inventory_lookup')
                elif inventory_mode == 'none': args['inventory_lookup'] = None
                elif inventory_mode == 'empty': args['inventory_lookup'] = lambda path: []
                semantics.finalize_dependencies(result, source_relation_context=context, **args)
                self.assertEqual(target['resolution'] == 'represented', inventory_mode == 'complete')
                self.assertEqual(result['coverage']['sourceRelations']['detected'], 1)
                if inventory_mode != 'complete':
                    self.assertEqual(target['validation']['status'], 'invalidated')
                    # A consumed/failed permit cannot be reused to make this fresh.
                    semantics.finalize_dependencies(result, source_relation_context=context, **callbacks(facts))
                    self.assertNotEqual(target['resolution'], 'represented')

    def test_serialized_pending_and_legacy_record_flags_cannot_rearm(self):
        context = semantics.SourceRelationBuildContext()
        result, facts = extract(defer_external_dependencies=True, source_relation_context=context)
        serialized = json.loads(json.dumps(result))
        semantics.finalize_dependencies(serialized, **callbacks(facts))
        target = relations(serialized)[0]
        self.assertEqual(target['resolution'], 'unknown')
        self.assertEqual(target['validation']['reason'], 'source_relation_admissibility_unsealed')
        semantics.finalize_dependencies(serialized, source_relation_context=semantics.SourceRelationBuildContext(),
            **callbacks(facts))
        self.assertNotEqual(target['resolution'], 'represented')

    def test_actual_local_security_withdrawal_preserves_full_independent_sibling(self):
        case = local_tests.LocalInitializerDefinitionTests()
        results, facts, result = case.analyzed()
        sibling = copy.deepcopy(returns(result)[-1])
        local(result)['localTypeInference']['lexicalOwner']['typeBodyRange']['charEnd'] += 100
        finish(results, facts)
        # Check the original proof, not an unrelated new relation's withdrawal.
        self.assertFalse(methods(returns(result)[0]))
        self.assertEqual(local(result)['localTypeInference']['status'], 'UNKNOWN')
        self.assertEqual(returns(result)[-1], sibling)
        self.assertTrue(all(relation['resolution'] != 'represented' for relation in relations(result)))

    def test_valid_legacy_conditional_result_is_exact_and_idempotent(self):
        result, records = fixture()
        before = copy.deepcopy(result)
        finalize(result, records)
        self.assertEqual(result, before)
        finalize(result, records)
        self.assertEqual(result, before)

    def test_provider_tamper_never_promotes_legacy_unknown_relation(self):
        for fault in ('return_type', 'name', 'owner', 'privacy', 'revoked'):
            with self.subTest(fault=fault):
                result, facts = extract(defer_external_dependencies=True)
                method = next(row for row in facts['records'] if row.get('name') == 'helper')
                if fault == 'return_type': method['returnTypeReference']['resolvedType'] = 'boolean'
                elif fault == 'name': method['name'] = 'other'
                elif fault == 'owner': method['owner'] = 'Other'
                elif fault == 'privacy': method['unsupportedReasons'] = ['privacy_denied']
                else: method['unsupportedReasons'] = ['literal_review_revoked']
                semantics.finalize_dependencies(result, **callbacks(facts))
                target = relations(result)[0]
                self.assertNotEqual(target['resolution'], 'represented')
                self.assertEqual(target['validation']['status'], 'invalidated')
                self.assertEqual(result['coverage']['sourceRelations']['detected'], 1)

    def test_current_owner_provider_rejection_precedes_unsealed_diagnostic(self):
        source = HELPER.replace('private int helper', 'int helper')
        cases = [('owner_privacy', 'denied', 'source_relation_owner_privacy_withheld'),
                 ('owner_pending', 'unknown', 'source_relation_owner_dependency_pending'),
                 ('provider_privacy', 'denied', 'source_relation_provider_privacy_withheld'),
                 ('provider_revoked', 'denied', 'source_relation_provider_permission_revoked'),
                 ('provider_unsupported', 'unsupported', 'source_relation_provider_parser_unsupported'),
                 ('provider_changed', 'unknown', 'source_relation_provider_unavailable_or_changed'),
                 ('provider_missing', 'unknown', 'source_relation_provider_unavailable_or_changed')]
        for fault, disposition, reason in cases:
            with self.subTest(fault=fault):
                result, facts = extract(source)
                target = relations(result)[0]
                self.assertEqual(target['validation']['reason'], 'source_relation_admissibility_unsealed')
                owner = next(row for row in result['fragments'] if row['id'] == target['admissibility']['ownerRecordId'])
                method = next(row for row in facts['records'] if row.get('name') == 'helper')
                if fault == 'owner_privacy': owner['unsupportedReasons'] = ['privacy_denied']
                elif fault == 'owner_pending': owner['dependencyClosure'] = {'status': 'pending_snapshot_finalization'}
                elif fault == 'provider_privacy': method['unsupportedReasons'] = ['privacy_denied']
                elif fault == 'provider_revoked': method['unsupportedReasons'] = ['literal_review_revoked']
                elif fault == 'provider_unsupported': method['representationStatus'] = 'unsupported'
                elif fault == 'provider_changed': method['returnTypeReference']['resolvedType'] = 'boolean'
                else: facts['records'].remove(method)
                semantics.finalize_source_relations(result, lookup=callbacks(facts)['lookup'])
                self.assertEqual(target['resolution'], disposition)
                self.assertEqual(target['validation']['reason'], reason)
                self.assertEqual(result['coverage']['sourceRelations']['detected'], 1)


if __name__ == '__main__': unittest.main()
