"""Neutral C36 contracts; no external original/gold/actual-source inputs."""
import copy
import itertools
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_business_explicit_contracts as base
import test_business_projection_boundaries as boundary

sem = base.sem


class CompositionContractTests(unittest.TestCase):
    setUp = base.ExplicitContractTests.setUp
    tearDown = base.ExplicitContractTests.tearDown
    validated = base.ExplicitContractTests.validated
    decide = base.ExplicitContractTests.decide

    def manifest(self, mode='first_applicable', missing=False, tie=True):
        value = copy.deepcopy(self.manifest_data)
        contract = value['concepts'][-1]['facets']['priority']['value']
        contract.update(exclusivity=mode, stacking='none')
        if missing: contract.pop('stacking')
        if tie: contract['members'][1]['priority'] = contract['members'][0]['priority']
        return value

    def setUp(self):
        base.ExplicitContractTests.setUp(self)
        self.manifest_data = self.manifest
        base.query._semantics = sem; base.query._guard = base.privacy_guard
        # Do not shadow the helper above with the baseline's instance attribute.
        del self.manifest

    def validated(self, manifest=None):
        return sem.validate_review(manifest or self.manifest_data, self.reader,
                                   source_pins=base.PINS, candidates=[])

    def top(self, result):
        return next(row for row in result['records'] if row['id'] == base.identity('composition'))

    def test_unique_completion_preserves_declared_input_and_review_digest(self):
        for mode in ('first_applicable', 'at_most_one'):
            manifest = self.manifest(mode, missing=True)
            before = copy.deepcopy(manifest)
            result = self.validated(manifest)
            record = self.top(result)
            self.assertEqual(manifest, before)
            self.assertEqual(result['reviewManifestDigest'], sem.digest(before))
            self.assertEqual(record['facets']['priority']['value'], before['concepts'][-1]['facets']['priority']['value'])
            self.assertNotIn('stacking', record['facets']['priority']['value'])
            self.assertEqual(record['canonicalContracts'], [dict(
                path='/facets/priority/value/stacking', value='none', basis='CONSTRAINT_ENTAILED',
                rule='non_all_stacking_constraint_v1', premisePath='/facets/priority/value/exclusivity',
                premiseValue=mode)])
            projected = base.query.project_record(record, evidence=False)
            self.assertEqual(projected['canonicalContracts'], record['canonicalContracts'])
            self.assertNotIn('stacking', projected['facets']['priority']['value'])

    def test_nonunique_missing_invalid_and_explicit_contradictions_reject(self):
        mutations = [lambda c: c.update(exclusivity='all'),
                     lambda c: c.pop('exclusivity'), lambda c: c.pop('onConflict'),
                     lambda c: c.pop('priorityOrder'), lambda c: c.update(stacking=None),
                     lambda c: c.update(stacking='sum'), lambda c: c.update(extra='value'),
                     lambda c: c['members'][0].update(priority=True)]
        for mutate in mutations:
            manifest = self.manifest(missing=True)
            mutate(manifest['concepts'][-1]['facets']['priority']['value'])
            with self.subTest(mutate=mutate):
                self.assertNotIn(base.identity('composition'), {r['id'] for r in self.validated(manifest)['records']})
        manifest = self.manifest(missing=True)
        manifest['concepts'][-1]['canonicalContracts'] = []
        self.assertNotIn(base.identity('composition'), {r['id'] for r in self.validated(manifest)['records']})

    def test_stored_missing_forged_stale_and_extra_metadata_fail_closed(self):
        record = self.top(self.validated(self.manifest(missing=True)))
        mutations = [lambda r: r.pop('canonicalContracts'),
                     lambda r: r['canonicalContracts'][0].update(value='sum'),
                     lambda r: r['canonicalContracts'][0].update(basis='DECLARED'),
                     lambda r: r['canonicalContracts'][0].update(premiseValue='at_most_one'),
                     lambda r: r['facets']['priority']['value'].update(stacking='none'),
                     lambda r: r['canonicalContracts'].append(copy.deepcopy(r['canonicalContracts'][0]))]
        for mutate in mutations:
            forged = copy.deepcopy(record); mutate(forged)
            with self.subTest(mutate=mutate), self.assertRaises(sem.BusinessError):
                sem.validate_record_values(sem.seal_record(forged))
            with self.assertRaises(sem.BusinessError): base.query.project_record(forged, evidence=False)

    def assert_conflict(self, decision, reason):
        self.assertEqual(decision['status'], 'UNKNOWN')
        self.assertEqual(decision['reason'], reason)
        self.assertTrue(decision['conflictProven'])
        self.assertEqual(decision['conflictAssessment'], 'PROVEN')
        self.assertEqual(decision['conflictScope'], 'static_supplied_context_only')
        self.assertEqual(decision['memberPolicyDenominator'], 2)
        self.assertEqual(decision['evaluatedMemberPolicyNumerator'], 2)
        self.assertEqual(decision['selectedPolicyDenominator'], 3)
        self.assertEqual(set(decision['activeMemberPolicyIds']), {base.identity('leaf1'), base.identity('leaf2')})
        self.assertEqual(set(decision['activeSourceRuleIds']), {r['id'] for r in self.reader.rows})
        for key in ('selectedMemberPolicyIds', 'contributingPolicyIds', 'contributingSourceRuleIds', 'value', 'finiteBest'):
            self.assertIsNone(decision[key])
        self.assertEqual(len(decision['conflictWitnesses']), 2)
        for witness in decision['conflictWitnesses']:
            self.assertEqual(len(witness['applicableLeafWitnesses']), 1)
            leaf = witness['applicableLeafWitnesses'][0]
            self.assertEqual(leaf['policyId'], witness['memberPolicyId'])
            self.assertEqual(leaf['compositionPath'], [base.identity('composition'), leaf['policyId']])
            self.assertIn(leaf['sourceRuleId'], decision['selectedSourceRuleIds'])

    def test_tied_top_and_at_most_one_need_complete_actual_member_outcomes(self):
        for mode, tie, reason in [('first_applicable', True, 'priority_selection_ambiguity'),
                                  ('at_most_one', True, 'explicit_exclusivity_conflict'),
                                  ('at_most_one', False, 'explicit_exclusivity_conflict')]:
            for missing in (False, True):
                result = self.validated(self.manifest(mode, missing=missing, tie=tie))
                self.assert_conflict(self.decide(result, context=self.cases[0]), reason)

    def test_same_values_and_permutations_never_select_tied_identity(self):
        semantic = []
        for mode in ('first_applicable', 'at_most_one'):
            for order in ('higher_first', 'lower_first'):
                manifest = self.manifest(mode, missing=True)
                value = manifest['concepts'][-1]['facets']['priority']['value']; value['priorityOrder'] = order
                for members in itertools.permutations(value['members']):
                    changed = copy.deepcopy(manifest); changed['concepts'][-1]['facets']['priority']['value']['members'] = list(members)
                    result = self.validated(changed); records = {r['id']: r for r in result['records']}
                    decision = sem.optional_decision(records[base.identity('composition')], get_record=records.get,
                        source_reader=self.reader, source_pins=base.PINS, context=self.cases[0],
                        evaluate_source=lambda *args: dict(status='evaluated', value=dict(type='int', value=7)))
                    self.assertTrue(decision['conflictProven']); self.assertIsNone(decision['value'])
                    semantic.append((mode, order, decision['conflictWitnesses']))
        for mode, order, witness in semantic:
            self.assertEqual(witness, next(w for m, o, w in semantic if m == mode and o == order))

    def test_unknown_context_or_partial_source_never_proves_conflict(self):
        result = self.validated(self.manifest('at_most_one', missing=True))
        decision = self.decide(result, context={})
        self.assertEqual(decision['reason'], 'partial_composition')
        self.assertFalse(decision['conflictProven']); self.assertEqual(decision['conflictAssessment'], 'UNDETERMINED')
        self.assertEqual(decision['evaluatedMemberPolicyNumerator'], 0)
        self.assertEqual({m['memberPolicyId'] for m in decision['members']}, {base.identity('leaf1'), base.identity('leaf2')})
        records = {r['id']: r for r in result['records']}; called = []
        def evaluate(rid, values, instant):
            called.append(rid)
            return dict(status='UNKNOWN', reason='unsupported') if rid == self.reader.rows[0]['id'] else dict(status='evaluated', value=dict(type='int', value=4))
        decision = sem.optional_decision(self.top(result), get_record=records.get, source_reader=self.reader,
            source_pins=base.PINS, context=self.cases[0], evaluate_source=evaluate)
        self.assertEqual(len(called), 2); self.assertEqual(decision['evaluatedMemberPolicyNumerator'], 1)
        self.assertFalse(decision['conflictProven']); self.assertIsNone(decision['activeMemberPolicyIds'])
        self.assertEqual(decision['selectedPolicyDenominator'], 3); self.assertIsNone(decision['finiteBest'])

    def test_inactive_tie_and_lower_tie_do_not_conflict(self):
        manifest = self.manifest(missing=True)
        leaf = manifest['concepts'][2]
        leaf['facets']['effective_interval'] = base.declared(dict(type='time_interval', start='2026-01-01T00:00:00Z', end='2026-01-02T00:00:00Z', timezone='UTC', clock='business', bounds='closed'))
        leaf['facets']['clock_timezone'] = base.declared(dict(type='clock_basis', clock='business', timezone='UTC'))
        result = self.validated(manifest)
        decision = self.decide(result, context={**self.cases[0], '$clock': 'business', '$timezone': 'UTC'}, as_of='2026-01-03T00:00:00Z')
        self.assertEqual(decision['selectedMemberPolicyIds'], [base.identity('leaf2')])
        self.assertFalse(decision.get('conflictProven', False))
        manifest = self.manifest(missing=True)
        third = copy.deepcopy(manifest['concepts'][2]); third['conceptKey'] = 'leaf3'
        manifest['concepts'].insert(-1, third)
        manifest['concepts'][-1]['facets']['priority']['value']['members'].append(dict(policyId=base.identity('leaf3'), priority=10))
        result = self.validated(manifest); decision = self.decide(result, context=self.cases[0])
        self.assertEqual(decision['selectedMemberPolicyIds'], [base.identity('leaf3')])
        self.assertEqual(decision['memberPolicyDenominator'], 3)

    def test_finite_conflict_and_forged_source_never_become_best(self):
        result = self.validated(self.manifest('at_most_one', missing=True))
        decision = self.decide(result, cases=self.cases)
        self.assertEqual(decision['selectedContextDenominator'], 2); self.assertIsNone(decision['finiteBest'])
        self.assertTrue(all(c['conflictProven'] for c in decision['cases']))
        next(r for r in result['records'] if r['id'] == base.identity('leaf1'))['facets']['formula']['sourceAnchors'][0]['targetDigest'] = 'f' * 64
        decision = self.decide(result, context=self.cases[0])
        self.assertFalse(decision['conflictProven']); self.assertIsNone(decision['finiteBest'])

    def test_invalid_caller_values_keep_all_member_outcomes_without_conflict_proof(self):
        manifest = self.manifest('at_most_one', missing=True)
        second = copy.deepcopy(manifest['concepts'][0]); second['conceptKey'] = 'second_input'
        manifest['concepts'].insert(1, second)
        leaf2 = next(c for c in manifest['concepts'] if c['conceptKey'] == 'leaf2')
        leaf2['facets']['inputs']['value']['inputs'][0]['propertyId'] = base.identity('second_input', 'business_property')
        result = self.validated(manifest)
        for bad in (dict(type='integer', value=True), dict(type='integer', value=1, unexpected='neutral'),
                    dict(type='quantity', value='1', unit='crate'), dict(type='decimal', value='1.0', precision=0, scale=1),
                    dict(type='future', value='never echoed'), None):
            context = {base.identity('input', 'business_property'): bad,
                       base.identity('second_input', 'business_property'): dict(type='integer', value=1)}
            decision = self.decide(result, context=context)
            with self.subTest(bad=bad):
                self.assertEqual(decision['reason'], 'partial_composition')
                self.assertEqual(decision['memberPolicyDenominator'], 2)
                self.assertEqual(decision['evaluatedMemberPolicyNumerator'], 1)
                self.assertEqual(decision['selectedPolicyDenominator'], 3)
                self.assertEqual(len(decision['members']), 2)
                self.assertFalse(decision['conflictProven']); self.assertIsNone(decision['value']); self.assertIsNone(decision['finiteBest'])
                self.assertNotIn('never echoed', json.dumps(decision))

    def test_context_recovery_whitelist_is_confined_to_supplied_value_seam(self):
        result = self.validated(self.manifest('at_most_one', missing=True))
        # An identical whitelisted code from spec validation must escape the
        # local context catch to the unchanged outer fail-closed boundary.
        with patch.object(sem, '_property', side_effect=sem.BusinessError('semantic_scalar_invalid')):
            decision = self.decide(result, context=self.cases[0])
        self.assertEqual(decision['reason'], 'semantic_scalar_invalid')
        self.assertNotIn('contextFailureCode', decision); self.assertNotIn('members', decision)
        with patch.object(sem, 'validate_anchor', side_effect=sem.BusinessError('semantic_scalar_invalid')):
            decision = self.decide(result, context=self.cases[0])
        self.assertEqual(decision['reason'], 'semantic_scalar_invalid')
        self.assertNotIn('contextFailureCode', decision); self.assertNotIn('members', decision)
        records = {r['id']: r for r in result['records']}
        def source_failure(*args): raise sem.BusinessError('semantic_scalar_invalid')
        decision = sem.optional_decision(self.top(result), get_record=records.get, source_reader=self.reader,
            source_pins=base.PINS, context=self.cases[0], evaluate_source=source_failure)
        self.assertEqual(decision['reason'], 'semantic_scalar_invalid')
        self.assertNotIn('contextFailureCode', decision); self.assertNotIn('members', decision)
        for code in ('source_anchor_mismatch', 'canonical_contract_metadata_mismatch', 'json_budget_exceeded',
                     'mapping_actual_source_rule_mismatch', 'business_record_integrity', 'explicit_decimal_contract_required'):
            with patch.object(sem, '_source_property_value', side_effect=sem.BusinessError(code)):
                decision = self.decide(result, context=self.cases[0])
            self.assertEqual(decision['reason'], code)
            self.assertNotIn('contextFailureCode', decision); self.assertNotIn('members', decision)
            self.assertFalse(decision['conflictProven']); self.assertIsNone(decision['value'])

    def test_nested_witness_presentation_is_invariant_under_all_member_permutations(self):
        original = self.manifest(missing=True)
        leaves = copy.deepcopy(original['concepts'][2:4])
        third, fourth = copy.deepcopy(leaves)
        third['conceptKey'] = 'leaf3'; fourth['conceptKey'] = 'leaf4'
        leaves += [third, fourth]
        first = copy.deepcopy(original['concepts'][-1]); first['conceptKey'] = 'group_a'; first['facets'].pop('missing_context')
        first['facets']['priority']['value'].update(exclusivity='all', stacking='sum')
        second = copy.deepcopy(first); second['conceptKey'] = 'group_b'
        second['facets']['priority']['value']['members'] = [dict(policyId=base.identity(k), priority=2) for k in ('leaf3', 'leaf4')]
        outer = copy.deepcopy(original['concepts'][-1])
        outer['facets']['priority']['value']['members'] = [dict(policyId=base.identity(k), priority=5) for k in ('group_a', 'group_b')]
        expected = None; permutations = 0
        for a, b, top in itertools.product((False, True), repeat=3):
            groups = copy.deepcopy([first, second, outer])
            for reverse, group in zip((a, b, top), groups):
                if reverse: group['facets']['priority']['value']['members'].reverse()
            manifest = {**original, 'concepts': copy.deepcopy(original['concepts'][:2]) + leaves + groups}
            result = self.validated(manifest); decision = self.decide(result, context=self.cases[0])
            self.assertTrue(decision['conflictProven']); self.assertIsNone(decision['value'])
            self.assertEqual(decision['selectedPolicyDenominator'], 7)
            witness = decision['conflictWitnesses']
            if expected is None: expected = witness
            self.assertEqual(witness, expected)
            permutations += 1
        self.assertEqual(permutations, 8)


class SourceOfflineConflictTests(unittest.TestCase):
    setUp = boundary.BusinessProjectionBoundaryTests.setUp
    reader = boundary.BusinessProjectionBoundaryTests.reader
    review = boundary.BusinessProjectionBoundaryTests.review
    args = boundary.BusinessProjectionBoundaryTests.args
    call = boundary.BusinessProjectionBoundaryTests.call
    grant = boundary.BusinessProjectionBoundaryTests.grant
    mcp = boundary.BusinessProjectionBoundaryTests.mcp

    def identity(self, key, kind='business_policy'):
        return self.sem.concept_id('review', 'allocation', kind, key)

    def mapped(self, mode='first_applicable', missing=True):
        with self.reader() as reader:
            rule = reader.source_reader.get_record(self.base['sourceRecordId'])
        pins = {k: self.meta[k] for k in self.sem.PIN_KEYS}
        def row(key, kind='business_policy'):
            return dict(namespace='review', domain='allocation', kind=kind, conceptKey=key, label=key,
                        sourceAnchors=copy.deepcopy(self.base['sourceAnchors']), facets={})
        props = []
        for key in ('input', 'output'):
            item = row(key, 'business_property'); item['facets']['scalar_type'] = base.declared(base.ptype('bool')); props.append(item)
        leaves = []
        for key in ('morning', 'evening'):
            item = row(key); item['facets'] = {name: base.na() for name in ('eligibility', 'exclusions', 'conflicts', 'effective_interval', 'clock_timezone')}
            item['facets'].update({name: copy.deepcopy(self.base['facets'][name]) for name in ('formula', 'outcome')})
            item['facets']['inputs'] = base.declared(dict(type='formula_mapping', sourcePins=pins, sourceRuleId=rule['id'],
                sourceRuleDigest=self.sem.digest(rule), numericContextDigest=self.sem.digest(rule.get('numericContext')),
                inputs=[dict(parameter=rule['parameters'][0]['name'], propertyId=self.identity('input', 'business_property'))],
                outputPropertyId=self.identity('output', 'business_property')))
            leaves.append(item)
        top = row('combined'); top['facets'] = {name: base.na() for name in ('eligibility', 'exclusions', 'conflicts', 'effective_interval', 'clock_timezone')}
        top['facets']['priority'] = base.declared(dict(type='policy_composition', members=[dict(policyId=self.identity(k), priority=11) for k in ('morning', 'evening')], priorityOrder='higher_first', exclusivity=mode, onConflict='UNKNOWN'))
        if not missing: top['facets']['priority']['value']['stacking'] = 'none'
        return props + leaves + [top]

    def test_actual_source_offline_stdio_proves_tie_without_evidence_leak(self):
        self.review(self.mapped()); self.grant(['read_policy'])
        response = self.mcp(self.args(rule_id=self.identity('combined'), context={self.identity('input', 'business_property'): dict(type='boolean', value=False)}, policy_view='approved_business'))
        self.assertFalse(response['isError'], response)
        data = response['structuredContent']['data']; decision = data['businessDecision']
        self.assertTrue(decision['conflictProven']); self.assertEqual(decision['reason'], 'priority_selection_ambiguity')
        self.assertEqual(decision['evaluatedMemberPolicyNumerator'], 2)
        self.assertEqual(decision['selectedPolicyDenominator'], 3)
        self.assertIsNone(decision['selectedMemberPolicyIds']); self.assertIsNone(decision['value'])
        self.assertNotIn('path', json.dumps(decision)); self.assertNotIn('targetDigest', json.dumps(decision))
        self.assertNotIn('explicit reviewed neutral contract', json.dumps(data))
        self.assertEqual(data['policy']['canonicalContracts'][0]['basis'], 'CONSTRAINT_ENTAILED')

    def test_actual_at_most_one_missing_context_and_reader_metadata_recheck(self):
        self.review(self.mapped('at_most_one')); self.grant(['read_policy'])
        context = {self.identity('input', 'business_property'): dict(type='boolean', value=True)}
        decision = self.call(rule_id=self.identity('combined'), context=context)['businessDecision']
        self.assertTrue(decision['conflictProven']); self.assertEqual(decision['reason'], 'explicit_exclusivity_conflict')
        unknown = self.call(rule_id=self.identity('combined'), context={})['businessDecision']
        self.assertFalse(unknown['conflictProven']); self.assertEqual(unknown['reason'], 'partial_composition')
        before = copy.deepcopy(self.meta)
        with self.reader() as reader:
            record = reader.get_record(self.identity('combined'))
            for mutate in (lambda r: r.pop('canonicalContracts'), lambda r: r['canonicalContracts'][0].update(value='sum')):
                forged = copy.deepcopy(record); mutate(forged); forged = self.sem.seal_record(forged)
                with self.assertRaises(self.sem.BusinessError): reader._decode(self.sem.canonical(forged).decode())
        self.assertEqual(self.meta, before)

    def test_genuinely_rejected_shape_retains_c33_diagnostics_and_denominator(self):
        items = self.mapped(); items[-1]['facets']['priority']['value'].pop('onConflict')
        self.review(items); self.grant(['read_policy'])
        data = self.call(rule_id=self.identity('combined'), context={})
        self.assertEqual(data['status'], 'business_review_rejected')
        self.assertFalse(data['businessDecision']['conflictProven']); self.assertFalse(data['compositionEvaluated'])
        self.assertIn('object_shape_invalid', data['businessDecision']['rejectionReasons'])
        with self.reader() as reader:
            diagnostic = reader.metadata['currentReviewDiagnostics']
            self.assertEqual(diagnostic['selectedInputs'], 5)
            self.assertEqual(sum(diagnostic['outcomeCounts'].values()), 5)

    def test_single_source_export_wrappers_preserve_every_current_policy_field(self):
        self.review(self.mapped()); self.grant(['read_policy'])
        self.assertEqual(self.query.export_projection_contract(), 'companion.authorized-policy-projection.v1')
        with self.reader() as reader:
            metadata = copy.deepcopy(reader.metadata)
            self.assertEqual(self.query.policy_projection_metadata(metadata), self.query._metadata(metadata))
            for record in reader.iter_records():
                self.assertEqual(self.query.policy_projection_record(record), self.query.project_record(record, evidence=False))
            for mutate in (lambda m: m.update(futureMetadata='value'),
                           lambda m: m['coverage'].update(futureCoverage='value'),
                           lambda m: m['coverage']['semanticStatus'].update(futureCount=1),
                           lambda m: m['storage']['shards'][0].update(futurePrivate='value')):
                unknown = copy.deepcopy(metadata); mutate(unknown)
                with self.assertRaises(self.query.BusinessQueryError): self.query.policy_projection_metadata(unknown)
            record = reader.get_record(self.identity('combined'))
            for mutate in (lambda r: r.update(futureRecord='value'),
                           lambda r: r['facets']['priority'].update(futureFacet='value'),
                           lambda r: r['sourceAnchors'][0].update(futureAnchor='value'),
                           lambda r: r['facets']['priority']['value'].update(futureContract='value')):
                unknown = copy.deepcopy(record); mutate(unknown)
                with self.assertRaises(self.query.BusinessQueryError): self.query.policy_projection_record(unknown)

    def test_export_diagnostics_are_same_policy_projection_without_evidence(self):
        items = self.mapped(); items[-1]['facets']['priority']['value'].pop('onConflict')
        self.review(items); self.grant(['read_policy'])
        with self.reader() as reader:
            raw = copy.deepcopy(reader.metadata['currentReviewDiagnostics'])
            projected = self.query.policy_projection_diagnostics(raw)
            self.assertEqual(projected['selectedInputs'], raw['selectedInputs'])
            self.assertEqual(projected['outcomeCounts'], raw['outcomeCounts'])
            self.assertNotIn('sourceAnchors', json.dumps(projected))
            self.assertNotIn('reviewManifestDigest', projected)
            unknown = copy.deepcopy(raw); unknown['entries'][0]['sourceAnchors'][0]['futureEvidence'] = 'value'
            with self.assertRaises(self.query.BusinessQueryError): self.query.policy_projection_diagnostics(unknown)
