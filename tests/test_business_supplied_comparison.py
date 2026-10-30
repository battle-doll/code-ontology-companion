"""Finite caller-supplied observations, separate from source evaluation."""
import copy
import json
import unittest
from unittest.mock import patch

import test_business_query as fixture


class SuppliedComparisonTests(unittest.TestCase):
    setUp=fixture.BusinessQueryTests.setUp
    args=fixture.BusinessQueryTests.args
    call=fixture.BusinessQueryTests.call
    candidate=fixture.BusinessQueryTests.candidate
    reviewed=fixture.BusinessQueryTests.reviewed

    def compare(self,cases,**extra):
        return self.call('compare_policy_cases',rule_id=self.candidate()['id'],cases=cases,
            comparison_mode='supplied_values',objective=extra.pop('objective','maximize_value'),**extra)['suppliedComparison']

    def internal(self,cases,**extra):
        rid=self.candidate()['id']
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            result=self.query._evaluation(reader,self.workspace,self.sid,'compare_policy_cases',
                dict(rule_id=rid,cases=cases,comparison_mode='supplied_values',objective='maximize_value',**extra),True)
        return result['suppliedComparison']

    def conserved(self,result,selected):
        self.assertEqual(result['selected'],selected)
        self.assertEqual(result['accepted']+result['rejected']+result['unknown'],selected)
        self.assertEqual([entry['inputIndex'] for entry in result['entries']],list(range(selected)))
        self.assertEqual([entry['jsonPointer'] for entry in result['entries']],['/cases/'+str(i) for i in range(selected)])

    def test_raw_integer_min_max_ties_do_not_invoke_source_or_claim_eligibility(self):
        cases=[{'id':'cold','value':-2},{'id':'first','value':3},{'id':'second','value':3},{'id':'zero','value':0}]
        before=copy.deepcopy(cases)
        with patch.object(self.query._source,'read_policy_records',side_effect=AssertionError('source must not run')):
            result=self.compare(cases)
        self.assertEqual(result['status'],'COMPLETE');self.conserved(result,4)
        self.assertEqual(result['best'],[{'inputIndex':1,'id':'first'},{'inputIndex':2,'id':'second'}])
        self.assertEqual(result['minimum'],[{'inputIndex':0,'id':'cold'}]);self.assertFalse(result['sourceRuleEvaluated'])
        self.assertIsNone(result['sourceEvaluation']);self.assertEqual(result['eligibility'],'UNKNOWN')
        self.assertEqual(result['globalOptimum'],'UNKNOWN');self.assertFalse(result['businessPolicyComplete'])
        self.assertEqual(result['runtimeStatus'],'NOT_OBSERVED');self.assertEqual(cases,before)
        self.assertEqual(self.compare(cases,objective='minimize_value')['best'],result['minimum'])

    def test_integer_magnitude_is_exact_and_bool_is_not_integer(self):
        result=self.compare([{'id':'low','value':-(10**100)},{'id':'high','value':{'type':'integer','value':10**100}}])
        self.assertEqual(result['status'],'COMPLETE');self.assertEqual(result['best'][0]['id'],'high')
        result=self.compare([{'id':'bool','value':True},{'id':'typed','value':{'type':'integer','value':False}},{'id':'plain','value':1}])
        self.conserved(result,3);self.assertEqual((result['accepted'],result['rejected'],result['unknown']),(1,1,1))
        result=self.internal([{'id':'oversize','value':10**100+1}])
        self.assertEqual(result['rejected'],1)

    def test_exact_decimal_representations_tie_without_invented_precision(self):
        cases=[{'id':'one','value':{'type':'decimal','value':'1.0'}},
               {'id':'two','value':{'type':'decimal','value':'1.00','precision':3,'scale':2}},
               {'id':'three','value':1}]
        result=self.compare(cases)
        self.assertEqual([r['id'] for r in result['best']],['one','two','three'])
        self.assertEqual([r['value'] for r in result['entries']],[r['value'] for r in cases])
        result=self.compare([{'id':'a','value':{'type':'decimal','value':'0.'+'0'*99+'1'}},
            {'id':'b','value':{'type':'decimal','value':'0.'+'0'*99+'2'}}])
        self.assertEqual(result['best'][0]['id'],'b')

    def test_quantity_and_money_require_exact_family_unit_currency(self):
        for tag,identity in [('quantity',{'unit':'kg'}),('money',{'currency':'USD'}),('money',{'currency':'USD','unit':'item'})]:
            with self.subTest(tag=tag,identity=identity):
                result=self.compare([{'id':'a','value':{'type':tag,'value':'1',**identity}},
                                     {'id':'b','value':{'type':tag,'value':'2',**identity}}])
                self.assertEqual(result['status'],'COMPLETE');self.assertEqual(result['best'][0]['id'],'b')
        groups=[(1,{'type':'quantity','value':'2','unit':'kg'}),
            ({'type':'quantity','value':'1','unit':'kg'},{'type':'quantity','value':'2','unit':'g'}),
            ({'type':'money','value':'1','currency':'USD'},{'type':'money','value':'2','currency':'EUR'}),
            ({'type':'money','value':'1','currency':'USD'},{'type':'money','value':'2','currency':'USD','unit':'item'})]
        for first,second in groups:
            with self.subTest(values=(first,second)):
                result=self.compare([{'id':'a','value':first},{'id':'b','value':second}])
                self.assertEqual((result['accepted'],result['unknown']),(0,2));self.assertEqual(result['best'],[])
                self.assertEqual(result['status'],'PARTIAL')

    def test_invalid_unknown_values_remain_in_original_denominator(self):
        values=[None,False,'2',2.5,{'type':'UNKNOWN'}, {'type':'decimal','value':'1e2'},
                {'type':'decimal','value':'2','precision':False,'scale':0}, {'type':'decimal','value':'2','scale':0},
                {'type':'integer','value':1,'unexpected':True}]
        cases=[{'id':'case'+str(i),'value':value} for i,value in enumerate(values)]+[{'id':'missing'},{'id':'good','value':2}]
        result=self.compare(cases);self.conserved(result,len(cases))
        self.assertEqual(result['accepted'],1);self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['best'],[{'inputIndex':len(cases)-1,'id':'good'}])
        self.assertTrue(all(entry.get('reason') for entry in result['entries'][:-1]))

    def test_duplicate_invalid_ids_and_extra_fields_never_overwrite_rows(self):
        cases=[{'id':'same','value':2},{'id':'same','value':3},{'id':'','value':4},
               {'id':'control\n','value':4},{'id':1,'value':5},{'value':6},
               {'id':'extra','value':7,'other':'neutral'},{'id':'valid','value':8}]
        result=self.compare(cases);self.conserved(result,8)
        self.assertEqual((result['accepted'],result['rejected']),(1,7))
        self.assertEqual([entry['reason'] for entry in result['entries'][:2]],['duplicate_case_id']*2)
        self.assertEqual(result['best'],[{'inputIndex':7,'id':'valid'}])

    def test_hundred_cases_and_internal_budget_frontiers_are_distinct_from_protocol(self):
        cases=[{'id':'case'+str(i),'value':i} for i in range(100)];result=self.compare(cases)
        self.conserved(result,100);self.assertEqual(result['status'],'COMPLETE')
        result=self.internal(cases+[{'id':'last','value':101}])
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['selected'],101)
        self.assertEqual(result['processed'],0);self.assertEqual(result['unknown'],101)
        self.assertEqual(result['unprocessedFrontier']['inputIndex'],0);self.assertEqual(result['entries'],[])
        with patch.object(self.query,'_evaluation',side_effect=AssertionError('protocol must reject first')):
            with self.assertRaises(fixture.companion.CompanionError):self.compare(cases+[{'id':'last','value':101}])
        result=self.internal([{'id':'oversize','value':1,'extra':'neutral '*10000}])
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['reason'],'supplied_case_byte_budget')
        self.assertIsNone(result['queryDigest']);self.assertEqual(result['entries'],[])
        result=self.internal([{'id':'nan','value':float('nan')}])
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['reason'],'supplied_cases_not_canonical_json')

    def test_privacy_denies_all_original_cases_before_input_or_query_hash(self):
        marker='Synthetic Query Private Person';cases=[{'id':'safe','value':1},{'id':'bad','value':2,'discarded':marker}]
        digested=[];original=self.query._semantics.digest
        def digest(value):
            self.assertNotIn(marker,json.dumps(value));digested.append(value);return original(value)
        with patch.object(self.query._semantics,'digest',side_effect=digest):
            with self.assertRaises(fixture.companion.privacy_guard.PrivacyError):self.internal(cases)
        self.assertEqual(self.compare([{'id':'safe','value':1}])['status'],'COMPLETE')

    def test_query_identity_binds_values_mode_objective_pins_and_allowed_projection(self):
        cases=[{'id':'a','value':1},{'id':'b','value':2}];first=self.compare(cases)
        self.assertNotEqual(first['queryDigest'],self.compare(cases,objective='minimize_value')['queryDigest'])
        self.assertNotEqual(first['queryDigest'],self.compare([{'id':'a','value':1},{'id':'b','value':3}])['queryDigest'])
        fixture.acl.update_access(self.workspace,'reader',['read_policy'],[self.sid])
        with patch.dict(fixture.os.environ,{fixture.acl.PRINCIPAL_ENV:'reader'}):projected=self.compare(cases)
        self.assertTrue(projected['evidenceDetailsWithheld']);self.assertNotEqual(first['queryDigest'],projected['queryDigest'])
        text=json.dumps(projected)
        for field in ['recordDigest','targetDigest','dependencyClosureDigest','sourceRangeOrSpan','sourceSha256','contentDigest']:
            self.assertNotIn('"'+field+'"',text)

    def test_old_context_mode_and_source_view_are_explicit(self):
        rid=self.candidate()['id'];args=dict(rule_id=rid,cases=[{'active':False},{'active':True}],objective='maximize_value')
        default=self.call('compare_policy_cases',**args)
        self.assertEqual(default,self.call('compare_policy_cases',comparison_mode='source_contexts',**args))
        self.assertIn('sourceEvaluation',default);self.assertNotIn('suppliedComparison',default)
        with patch.object(fixture.access,'_store',side_effect=AssertionError('source view must reject before store')):
            with self.assertRaises(fixture.companion.CompanionError):fixture.access.dispatch('compare_policy_cases',
                {'workspace_id':self.wid,'snapshot_id':self.sid,'rule_id':'neutral','cases':[{'id':'a','value':1}],
                 'objective':'maximize_value','comparison_mode':'supplied_values'})

    def test_existing_lifecycle_approval_acl_and_pin_gates_remain(self):
        rid=self.candidate()['id'];args=dict(rule_id=rid,cases=[{'id':'a','value':1}],objective='maximize_value',comparison_mode='supplied_values')
        result=self.call('compare_policy_cases',policy_view='approved_business',**args)
        self.assertEqual(result['status'],'business_approval_required');self.assertNotIn('suppliedComparison',result)
        fixture.acl.update_access(self.workspace,'denied',[],[self.sid])
        with patch.dict(fixture.os.environ,{fixture.acl.PRINCIPAL_ENV:'denied'}):
            with self.assertRaises(fixture.companion.CompanionError):self.call('compare_policy_cases',**args)
        wrong=self.args(**args);wrong['business_digest']='0'*64
        with self.assertRaises(fixture.companion.CompanionError):fixture.access.dispatch('compare_policy_cases',wrong)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            row=reader.get_record(rid)
            for field,value in [('support','conflicted'),('support','revoked'),('businessApproval','rejected'),('businessApproval','revoked')]:
                changed=copy.deepcopy(row);changed[field]=value
                with patch.object(reader,'get_record',return_value=changed):
                    result=self.query._evaluation(reader,self.workspace,self.sid,'compare_policy_cases',args,True)
                self.assertEqual(result['status'],'conflicted_or_revoked');self.assertNotIn('suppliedComparison',result)

    def test_supplied_branch_precedes_any_optional_contract_calculation(self):
        with patch.object(self.query._semantics,'_declared',side_effect=AssertionError('optional mapping must not run')), \
             patch.object(self.query._semantics,'optional_decision',side_effect=AssertionError('source composition must not run')):
            result=self.compare([{'id':'a','value':1},{'id':'b','value':2}])
        self.assertEqual(result['status'],'COMPLETE')

    def test_internal_canonical_byte_boundary_keeps_frontier_explicit(self):
        cases=[{'id':'a','value':1,'padding':''}]
        overhead=len(self.query._semantics.canonical(cases));cases[0]['padding']='n'*(65536-overhead)
        cases[0]['padding']=cases[0]['padding'][:-1]
        self.assertEqual(self.internal(cases)['processed'],1)
        cases[0]['padding']+='n'
        self.assertEqual(len(self.query._semantics.canonical(cases)),65536)
        result=self.internal(cases)
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['processed'],1)
        cases[0]['padding']+='n';result=self.internal(cases)
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['processed'],0)
        self.assertEqual(result['unprocessedFrontier'],{'inputIndex':0,'jsonPointer':'/cases/0','count':1})

    def test_all_original_malformed_case_fields_are_guarded_before_any_digest(self):
        marker='Synthetic Query Private Person';rid=self.candidate()['id']
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            projection=self.query.project_record(reader.get_record(rid),evidence=False)
            denied=[{'id':marker,'value':1},{'id':'a','value':{'type':'unsupported','nested':[marker]}},
                    {'id':'a','value':1,'ignored':marker},[marker]]
            for item in denied:
                with self.subTest(item=item),patch.object(self.query._semantics,'digest',side_effect=AssertionError('denied input must not be hashed')):
                    with self.assertRaises(fixture.companion.privacy_guard.PrivacyError):
                        self.query._supplied_comparison(reader,projection,{'cases':[{'id':'safe','value':1},item],'objective':'maximize_value'},False)

    def test_policy_projection_digest_uses_only_permitted_record_fields(self):
        rid=self.candidate()['id']
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            record=reader.get_record(rid);changed=copy.deepcopy(record)
            changed['contentDigest']='0'*64;changed['approvalReceiptId']='opaque:other'
            for anchor in changed['sourceAnchors']:
                anchor.update(recordDigest='1'*64,targetDigest='2'*64,dependencyClosureDigest='3'*64)
            first=self.query.project_record(record,evidence=False);second=self.query.project_record(changed,evidence=False)
            self.assertEqual(first,second)
            args={'cases':[{'id':'a','value':1}],'objective':'maximize_value'}
            self.assertEqual(self.query._supplied_comparison(reader,first,args,False)['queryDigest'],
                             self.query._supplied_comparison(reader,second,args,False)['queryDigest'])

    def test_count_neighbors_and_decimal_lexical_boundaries_are_explicit(self):
        result=self.compare([{'id':'case'+str(i),'value':i} for i in range(99)])
        self.assertEqual((result['accepted'],result['selected']),(99,99))
        empty=self.internal([]);self.assertEqual(empty['status'],'BLOCKED');self.assertEqual(empty['selected'],0)
        values=[{'id':'a','value':{'type':'decimal','value':'1'*127}},
                {'id':'b','value':{'type':'decimal','value':'1'*128}},
                {'id':'c','value':{'type':'decimal','value':'1'*129}}]
        result=self.compare(values);self.assertEqual((result['accepted'],result['rejected']),(2,1))
        self.assertEqual(result['best'],[{'inputIndex':1,'id':'b'}])

    def test_legitimate_source_parameters_named_id_value_keep_context_semantics(self):
        repo=self.root/'contexts';repo.mkdir()
        (repo/'contexts.py').write_text('def combine(id: int, value: int) -> int:\n    return id + value\n')
        workspace=self.root/'context-knowledge';built=fixture.source.initialize(repo,workspace,prepare_workspace=fixture.acl.initialize_access)
        fixture.access.register(str(workspace));sid=built['snapshotId'];wid=built['workspaceId']
        rule=fixture.access.dispatch('query_policy_rules',{'workspace_id':wid,'snapshot_id':sid})['data']['rules'][0]
        repo.rename(self.root/'contexts-offline')
        args={'workspace_id':wid,'snapshot_id':sid,'rule_id':rule['id'],'cases':[{'id':1,'value':2},{'id':3,'value':0}],'objective':'maximize_value'}
        first=fixture.access.dispatch('compare_policy_cases',args)
        self.assertEqual(first,fixture.access.dispatch('compare_policy_cases',{**args,'comparison_mode':'source_contexts'}))
        self.assertTrue(all(row['status']=='evaluated' for row in first['data']['cases']))
        self.assertNotIn('suppliedComparison',first['data'])

    def test_current_approval_and_snapshot_identity_change_query_receipt_without_value_approval(self):
        cases=[{'id':'a','value':1}];first=self.compare(cases);reviewed=self.reviewed()
        result=self.call('compare_policy_cases',rule_id=reviewed['id'],cases=cases,comparison_mode='supplied_values',
                         objective='maximize_value',policy_view='approved_business')
        current=result['suppliedComparison'];self.assertNotEqual(first['queryDigest'],current['queryDigest'])
        self.assertNotEqual(first['sourceAndBusinessPins']['businessDigest'],current['sourceAndBusinessPins']['businessDigest'])
        self.assertEqual(result['businessApproval'],'approved');self.assertEqual(current['suppliedValueTruth'],'NOT_VERIFIED')
        self.assertTrue(current['policyApprovalDoesNotApproveSuppliedValues']);self.assertIsNone(result['sourceEvaluation'])

    def test_case_identity_limits_and_unknown_mode_are_explicit(self):
        result=self.compare([{'id':'a'*128,'value':1},{'id':'a'*129,'value':2},{'id':'기록','value':1}])
        self.assertEqual((result['accepted'],result['rejected']),(2,1));self.assertEqual([r['id'] for r in result['best']],['a'*128,'기록'])
        schema=next(tool['inputSchema'] for tool in fixture.access.tool_definitions() if tool['name']=='compare_policy_cases')
        self.assertEqual(schema['properties']['comparison_mode']['enum'],['source_contexts','supplied_values'])
        with self.assertRaises(fixture.companion.CompanionError):
            self.call('compare_policy_cases',rule_id=self.candidate()['id'],cases=[{'id':'a','value':1}],comparison_mode='automatic',objective='maximize_value')


if __name__=='__main__':unittest.main()
