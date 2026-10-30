"""Exact dimensional transport and explicit contributors, without domain guesses."""
import copy
import unittest

import test_business_explicit_contracts as cases


class DimensionSelectionTests(unittest.TestCase):
    setUp = cases.ExplicitContractTests.setUp
    tearDown = cases.ExplicitContractTests.tearDown
    validated = cases.ExplicitContractTests.validated
    decide = cases.ExplicitContractTests.decide

    def test_exact_integer_dimensions_roundtrip_and_reject_loss(self):
        for dimension in ('quantity', 'money'):
            extra = dict(unit='crate') if dimension == 'quantity' else dict(currency='CHF', unit='crate')
            spec = cases.ptype('int', quantityKind=dimension, precision=8, scale=0, **extra)
            for number in (0, -23, 76543210):
                value = dict(type=dimension, value=str(number), **extra)
                self.assertEqual(cases.sem._source_property_value(spec, value), number)
                self.assertIs(type(cases.sem._source_property_value(spec, value)), int)
                result = cases.sem.property_value(spec, dict(type='integer', value=number), source_output=True)
                self.assertEqual(result, value)
            for payload in ('1.5', '2.0', '1e3', '123456789', 3, True):
                with self.subTest(dimension=dimension, payload=payload), self.assertRaises(cases.sem.BusinessError):
                    cases.sem._source_property_value(spec, dict(type=dimension, value=payload, **extra))
            for bad in (dict(spec, scale=1), dict(spec, scalarType='bool')):
                with self.assertRaises(cases.sem.BusinessError): cases.sem._typed_value(bad)
            with self.assertRaises(cases.sem.BusinessError):
                cases.sem.property_value(spec, dict(type='decimal', value='3'), source_output=True)

    def test_money_unit_currency_and_legacy_facets_are_exact(self):
        spec = cases.ptype('decimal', quantityKind='money', currency='CHF', unit='crate', precision=6, scale=2, rounding='ROUND_HALF_EVEN')
        value = dict(type='money', value='12.30', currency='CHF', unit='crate')
        self.assertEqual(cases.sem.property_value(spec, value), value)
        self.assertEqual(cases.sem.property_value(spec, dict(type='decimal', value='12.30'), source_output=True), value)
        for bad in (dict(value, currency='EUR'), dict(value, unit='piece'), {k:v for k,v in value.items() if k!='unit'}):
            with self.assertRaises(cases.sem.BusinessError): cases.sem.property_value(spec, bad)
        with self.assertRaises(cases.sem.BusinessError):
            cases.sem.property_value(dict(spec, unit='UNKNOWN'), value)
        manifest = copy.deepcopy(self.manifest)
        manifest['concepts'] = manifest['concepts'][:1]
        prop = manifest['concepts'][0]
        prop['facets'].update(scalar_type=cases.declared(spec), quantity_kind=cases.declared(dict(type='enum', value='money')),
            unit=cases.declared(dict(type='enum', value='crate')), currency=cases.declared(dict(type='enum', value='CHF')))
        self.assertEqual(len(self.validated(manifest)['records']), 1)
        prop['facets']['unit'] = cases.declared(dict(type='enum', value='piece'))
        self.assertIn('property_existing_facet_conflict', {row['reason'] for row in self.validated(manifest)['omissions']})

    def test_mapped_integer_dimensions_keep_source_int_and_output_tuple(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['concepts'] = manifest['concepts'][:4]
        for prop in manifest['concepts'][:2]:
            prop['facets']['scalar_type'] = cases.declared(cases.ptype('int', quantityKind='money', unit='crate', currency='CHF'))
        result = self.validated(manifest)
        self.assertEqual(len(result['records']), 4, result['omissions'])
        records = {row['id']:row for row in result['records']}
        observed = []
        def callback(rid, values, instant):
            observed.append(values)
            self.assertIs(type(values['amount']), int)
            return dict(status='evaluated', value=dict(type='int', value=values['amount'] + 2))
        decision = cases.sem.optional_decision(records[cases.identity('leaf1')], get_record=records.get,
            source_reader=self.reader, source_pins=cases.PINS, evaluate_source=callback,
            context={cases.identity('input','business_property'):dict(type='money', value='7', currency='CHF', unit='crate')})
        self.assertEqual(observed, [{'amount':7}])
        self.assertEqual(decision['value'], dict(type='money', value='9', currency='CHF', unit='crate'))
        self.assertEqual(decision['contributingPolicyIds'], [cases.identity('leaf1')])
        self.assertEqual(decision['contributingSourceRuleIds'], [self.reader.rows[0]['id']])

    def test_priority_and_extreme_contributors_do_not_shrink_denominators(self):
        for mode, order, wanted in [('none','higher_first',1),('none','lower_first',2),('min','higher_first',1),('max','higher_first',2),('sum','higher_first',None)]:
            result = self.validated()
            top = next(row for row in result['records'] if row['id']==cases.identity('composition'))
            top['facets']['priority']['value'].update(exclusivity='first_applicable' if mode=='none' else 'all', stacking=mode, priorityOrder=order)
            direct = self.decide(result, context=self.cases[0])
            expected = [cases.identity('leaf'+str(wanted))] if wanted else [cases.identity('leaf1'), cases.identity('leaf2')]
            with self.subTest(mode=mode, order=order):
                self.assertEqual(direct['status'], 'evaluated')
                self.assertEqual(direct['memberSelectionStatus'], 'RESOLVED')
                self.assertEqual(set(direct['selectedMemberPolicyIds']), set(expected))
                self.assertEqual(set(direct['contributingPolicyIds']), set(expected))
                self.assertEqual(len(direct['activeMemberPolicyIds']), 2)
                self.assertEqual(direct['memberPolicyDenominator'], 2)
                self.assertEqual(direct['selectedPolicyDenominator'], 3)
                self.assertEqual(len(direct['selectedPolicyIds']), 3)
                self.assertEqual(len(direct['selectedSourceRuleIds']), 2)
                finite = self.decide(result, cases=self.cases)
                self.assertEqual(finite['selectedContextDenominator'], 2)
                self.assertEqual(set(finite['finiteBest']['selections'][0]['contributingPolicyIds']), set(expected))

    def test_ties_nested_selection_unknown_and_conflict_keep_distinct_roles(self):
        result = self.validated()
        records = {row['id']:row for row in result['records']}
        top = records[cases.identity('composition')]
        top['facets']['priority']['value'].update(stacking='max')
        def same(rid, values, instant): return dict(status='evaluated', value=dict(type='int', value=4))
        direct = cases.sem.optional_decision(top, get_record=records.get, source_reader=self.reader, source_pins=cases.PINS,
            evaluate_source=same, context=self.cases[0])
        self.assertEqual(len(direct['selectedMemberPolicyIds']), 2)
        self.assertEqual(len(direct['contributingSourceRuleIds']), 2)
        nested = copy.deepcopy(top); nested['id'] = cases.identity('outer')
        nested['facets'].pop('missing_context')
        nested['facets']['priority']['value'].update(members=[dict(policyId=top['id'], priority=1)], stacking='none', exclusivity='first_applicable')
        records[nested['id']] = nested
        direct = cases.sem.optional_decision(nested, get_record=records.get, source_reader=self.reader, source_pins=cases.PINS,
            evaluate_source=same, context=self.cases[0])
        self.assertEqual(direct['selectedMemberPolicyIds'], [top['id']])
        self.assertEqual(set(direct['contributingPolicyIds']), {cases.identity('leaf1'), cases.identity('leaf2')})
        self.assertEqual(len(direct['memberSelections'][0]['selectedMemberPolicyIds']), 2)
        for mode in ('conflict','unknown'):
            changed = copy.deepcopy(result)
            changed_top = next(row for row in changed['records'] if row['id']==top['id'])
            if mode=='conflict': changed_top['facets']['priority']['value'].update(exclusivity='at_most_one', stacking='none')
            else: changed_top['facets']['eligibility'] = {'status':'UNKNOWN'}
            unknown = self.decide(changed, context=self.cases[0])
            self.assertEqual(unknown['status'], 'UNKNOWN')
            self.assertIsNone(unknown['selectedMemberPolicyIds'])
            self.assertIsNone(unknown['contributingPolicyIds'])
            self.assertIsNone(unknown['finiteBest'])
            self.assertEqual(unknown['selectedPolicyDenominator'], 3)

    def test_review_budget_summary_and_input_receipt_keep_the_same_omissions(self):
        manifest=copy.deepcopy(self.manifest)
        accepted=manifest['concepts'][:2]
        rejected=[]
        for index in range(3):
            row=copy.deepcopy(accepted[0]);row['conceptKey']='invalid'+str(index);row['unexpected']=True;rejected.append(row)
        manifest['concepts']=accepted+rejected+[copy.deepcopy(accepted[0]),copy.deepcopy(accepted[1])]
        manifest['processingContract']={'schemaVersion':1,'scope':'original_selected_inputs'}
        for limit in (1,5,7):
            result=cases.sem.validate_review(manifest,self.reader,source_pins=cases.PINS,candidates=[],max_records=limit)
            coverage=result['coverage'];receipt=coverage['processingReconciliation']
            with self.subTest(limit=limit):
                self.assertEqual(coverage['denominator'],7)
                self.assertEqual(coverage['omitted'],max(0,7-limit))
                self.assertEqual(coverage['omitted'],receipt['outcomeCounts']['omitted'])
                self.assertEqual(receipt['accountedInputs'],7)
                self.assertTrue(receipt['reconciled'])
                self.assertEqual(coverage['state'],'PARTIAL')
                self.assertEqual(coverage['globalCompleteness'],'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
