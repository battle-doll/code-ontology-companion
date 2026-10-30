"""Neutral consumer-location proof integrity; no application-specific data."""
import copy
import json
import unittest
from unittest.mock import patch
from test_java_platform_inheritance import platform, source, row
from test_policy_java_contracts import returns, bindings, extract
from test_policy_literal_review import walk
from test_policy_dependency_closure import analyzed_files, finish

SOURCE = ('import java.math.BigDecimal;import java.time.Duration;'
    'class Rules implements AutoCloseable{public void close(){}'
    'Object f(BigDecimal n){return join(n.abs(),Math.abs(3));}'
    'long duration(Duration d){return d.toNanos();}}'
    'class Other implements AutoCloseable{public void close(){}'
    'BigDecimal f(BigDecimal n){return n.abs();}'
    'long duration(Duration d){return d.toNanos();}'
    'int math(){return Math.abs(7);}}')


def replace_check(fragment, old, donor):
    # Keep the new definition/consumer reference graph internally consistent;
    # rejection must come from actual declaration and consumer correspondence.
    for node in walk(fragment):
        if isinstance(node.get('checkIds'), list):
            node['checkIds'] = sorted({donor['id'] if key == old else key for key in node['checkIds']})
    if not any(c['id'] == donor['id'] for c in fragment['platformInheritanceChecks']):
        fragment['platformInheritanceChecks'].append(copy.deepcopy(donor))


class PlatformTypeProofTests(unittest.TestCase):
    def test_real_donor_checks_cannot_rebind_name_owner_or_namespace(self):
        changes = [
            ('BigDecimal','member_type','Rules','Duration','member_type','Rules','java.math.BigDecimal'),
            ('BigDecimal','member_type','Rules','BigDecimal','member_type','Other','java.math.BigDecimal'),
            ('BigDecimal','member_type','Rules','Duration','member_type','Other','java.math.BigDecimal'),
            ('Math','field_or_member_type','Rules','Math','member_type','Rules','java.lang.Math'),
            ('Math','field_or_member_type','Rules','Duration','member_type','Other','java.lang.Math'),
        ]
        for old_name,old_ns,old_owner,new_name,new_ns,new_owner,removed in changes:
            with self.subTest(change=(old_name,old_ns,new_name,new_ns,new_owner)):
                results,facts=analyzed_files({'Rules.java':SOURCE})
                rows=returns(results['Rules.java']); item=rows[0]
                all_checks=[c for f in rows for c in f.get('platformInheritanceChecks',[])]
                old=next(c for c in item['platformInheritanceChecks'] if (c['queriedName'],c['namespace'],c['ownerType'])==(old_name,old_ns,old_owner))
                donor=next(c for c in all_checks if (c['queriedName'],c['namespace'],c['ownerType'])==(new_name,new_ns,new_owner))
                replace_check(item,old['id'],donor)
                finish(results,facts)
                owners=[c['declaringType'] for _,c in bindings(item)]
                self.assertNotIn(removed,owners)
                self.assertIn('java.lang.Math' if removed=='java.math.BigDecimal' else 'java.math.BigDecimal',owners)
                self.assertIn('platform_type_consumer_binding_invalid',json.dumps(item))
                self.assertTrue(any(n.get('value') in (3,'3') for n in walk(item)))

    def test_primitive_api_result_keeps_receiver_and_argument_proof_parents(self):
        item=row(source('implements AutoCloseable',expression='n.compareTo(n.abs())'))
        self.assertEqual(len(bindings(item)),2)
        self.assertEqual(item['expression']['staticType']['name'],'int')
        definitions={d['id']:d for d in item['platformTypeProofs']}
        root=definitions[item['expression']['staticType']['platformInheritance']['proofId']]
        self.assertEqual(root['mode'],'propagated')
        self.assertEqual([p['consumer'] for p in root['parents']],['/expression/callee/receiverStaticType','/expression/arguments/0/staticType'])
        self.assertTrue(all(c['queriedName']=='BigDecimal' for c in item['platformInheritanceChecks']))

    def test_same_type_sibling_is_not_an_interchangeable_propagation_parent(self):
        text=source('implements AutoCloseable',expression='join(n.abs(),n.negate())')
        results,facts=analyzed_files({'Rules.java':text});item=returns(results['Rules.java'])[-1]
        definitions={d['consumer']:d for d in item['platformTypeProofs']}
        first=definitions['/expression/arguments/0/staticType']
        donor=definitions['/expression/arguments/1/callee/receiverStaticType']
        first['parents']=[{'proofId':donor['id'],'consumer':donor['consumer']}]
        finish(results,facts)
        self.assertEqual([c['method'] for _,c in bindings(item)],['negate'])
        self.assertIn('platform_type_consumer_binding_invalid',json.dumps(item))

    def test_missing_origin_or_legacy_reference_is_unknown(self):
        for fault in ('origin','schema'):
            results,facts=analyzed_files({'Rules.java':source('implements AutoCloseable')})
            item=returns(results['Rules.java'])[-1]
            if fault=='origin':
                next(d for d in item['platformTypeProofs'] if d['mode']=='direct').pop('origin')
            else:
                for n in walk(item['expression']):
                    if 'platformInheritance' in n:n['platformInheritance'].pop('schemaVersion',None)
            finish(results,facts)
            self.assertFalse(bindings(item))
            self.assertIn('platform_type_origin_not_emitted',json.dumps(item))

    def test_canonical_equal_proof_duplicates_and_conflicts(self):
        for conflict in (False,True):
            results,facts=analyzed_files({'Rules.java':source('implements AutoCloseable')})
            item=returns(results['Rules.java'])[-1]
            duplicate=copy.deepcopy(item['platformTypeProofs'][0])
            if conflict:duplicate['typeName']='int'
            item['platformTypeProofs'].insert(0,duplicate)
            finish(results,facts)
            self.assertEqual(bool(bindings(item)),not conflict)
            if conflict:self.assertIn('platform_inheritance_definition_conflict',json.dumps(item))

    def test_array_parameter_origin_uses_declared_array_type(self):
        result,facts=extract('import java.math.BigDecimal;class Rules implements AutoCloseable{public void close(){}Object f(BigDecimal[] values){return values;}}')
        item=returns(result)[-1]
        self.assertEqual(item['expression']['staticType']['name'],'java.math.BigDecimal[]')
        direct=next(d for d in item['platformTypeProofs'] if d['mode']=='direct')
        self.assertEqual(direct['origin']['selector'],'/parameterTypeReferences/0')
        self.assertEqual(direct['typeName'],'java.math.BigDecimal[]')

    def test_graph_metadata_stays_within_existing_budgets_for_deep_chain(self):
        item=row(source('implements AutoCloseable',expression='n'+'.abs()'*24))
        self.assertEqual(len(bindings(item)),24)
        metadata=[item['platformTypeProofs'],item['platformInheritanceChecks'],item['platformTypeContracts']]
        self.assertLessEqual(len(item['platformTypeProofs']),64)
        self.assertLessEqual(len(platform.canonical(metadata)),64*1024)
        self.assertLess(len(json.dumps(item).encode()),256*1024)


if __name__=='__main__':unittest.main()

class PlatformTypeProofBoundaryTests(unittest.TestCase):
    def test_neutral_source_paths_remain_supported(self):
        sources=[
            ('BigDecimal f(BigDecimal n){BigDecimal copy=n;return copy.abs();}', {'abs'}),
            ('BigDecimal parse(String text){return new BigDecimal(text);}BigDecimal factor(){return BigDecimal.ONE;}BigDecimal f(String text){return parse(text).multiply(factor());}', {'multiply'}),
            ('Object f(long n){return new BigDecimal(n).abs();}', {'abs'}),
            ('Object f(Object n){return ((BigDecimal)n).abs();}', {'abs'}),
            ('boolean f(BigDecimal n){return -(n.signum()+2)<3;}', {'signum'}),
        ]
        for body,methods in sources:
            text='import java.math.BigDecimal;class Rules implements AutoCloseable{public void close(){}'+body+'}'
            results,facts=analyzed_files({'Rules.java':text});finish(results,facts)
            item=returns(results['Rules.java'])[-1]
            self.assertEqual({c['method'] for _,c in bindings(item)},methods)
            self.assertFalse(any(k.startswith('_') for n in walk(item) for k in n))

    def test_record_loop_definition_and_actual_component_are_required(self):
        text=('import java.math.BigDecimal;record Item(BigDecimal amount)implements AutoCloseable{public void close(){}}'
            'class Rules implements AutoCloseable{public void close(){}void use(BigDecimal n){}'
            'void f(Item[]items){for(Item item:items){use(item.amount().abs());}}}')
        for fault in (None,'header','component','component_proof'):
            results,facts=analyzed_files({'Rules.java':text})
            header=results['Rules.java']['fragments'][0]
            record=next(r for r in facts['Rules.java']['records'] if r.get('type')=='Record')
            if fault=='header':header['expression']=None
            if fault=='component':record['recordComponents'][0]['typeResolution']='UNKNOWN'
            if fault=='component_proof':record['platformTypeProofs'][0].pop('origin')
            finish(results,facts)
            self.assertEqual(any(bindings(r) for r in results['Rules.java']['fragments']),fault is None)

    def test_actual_parameter_declaration_faults_withdraw_only_dependent_sibling(self):
        for fault in ('resolution','raw','digest','range','owner','selector'):
            results,facts=analyzed_files({'Rules.java':SOURCE})
            item=returns(results['Rules.java'])[0]
            definition=next(d for d in item['platformTypeProofs'] if d.get('origin',{}).get('kind')=='parameter')
            origin=definition['origin']; provider=next(r for r in facts['Rules.java']['records'] if r['id']==origin['recordId'])
            if fault=='resolution':provider['parameterTypeReferences'][0]['resolution']='UNKNOWN'
            if fault=='raw':provider['parameterTypeReferences'][0]['rawType']='Duration'
            if fault=='digest':provider['sourceDigest']='0'*64
            if fault=='range':provider['bodyRange']={'charStart':0,'charEnd':1}
            if fault=='owner':provider['owner']='Other'
            if fault=='selector':origin['selector']='/parameterTypeReferences/9'
            finish(results,facts)
            self.assertEqual([c['declaringType'] for _,c in bindings(item)],['java.lang.Math'])

    def test_exact_source_return_callsite_cannot_be_replaced(self):
        text=('import java.math.BigDecimal;class Rules implements AutoCloseable{public void close(){}'
            'BigDecimal make(String text){return new BigDecimal(text);}'
            'BigDecimal f(String text){return make(text).abs();}}')
        for fault in (None,'target','column','resolution'):
            results,facts=analyzed_files({'Rules.java':text});item=returns(results['Rules.java'])[-1]
            direct=next(d for d in item['platformTypeProofs'] if d.get('origin',{}).get('kind')=='source_return')
            call=next(r for r in facts['Rules.java']['records'] if r['id']==direct['origin']['callsiteId'])
            if fault=='target':call['target']='unresolved'
            if fault=='column':call['column']+=1
            if fault=='resolution':call['resolution']='candidate'
            finish(results,facts)
            self.assertEqual(bool(bindings(item)),fault is None)

    def test_cross_file_pending_requires_actual_provider_and_initializer(self):
        sources={'Rules.java':'import java.math.BigDecimal;import static sample.Values.FLOOR;class Rules implements AutoCloseable{public void close(){}BigDecimal f(BigDecimal n){return join(n.add(FLOOR),n.abs());}}',
            'Values.java':'package sample;import java.math.BigDecimal;public class Values{public static final BigDecimal FLOOR=BigDecimal.ZERO;}'}
        for fault in (None,'missing','revoked','stale'):
            results,facts=analyzed_files(sources);item=returns(results['Rules.java'])[-1]
            self.assertEqual(results['Rules.java']['coverage']['dependencyClosure']['status'],'pending_snapshot_finalization')
            if fault=='missing':results['Values.java']['fragments']=[]
            if fault=='revoked':results['Values.java']['fragments'][0]['expression']=None
            if fault=='stale':results['Values.java']['fragments'][0]['sourceDigest']='0'*64
            finish(results,facts)
            self.assertEqual({c['method'] for _,c in bindings(item)},{'add','abs'} if fault is None else {'abs'})

    def test_malformed_empty_cycle_and_missing_graph_fail_closed(self):
        for fault in ('empty','wrong_type','cycle','missing','budget','parent_scalar'):
            results,facts=analyzed_files({'Rules.java':source('implements AutoCloseable')})
            item=returns(results['Rules.java'])[-1]
            definition=next(d for d in item['platformTypeProofs'] if d.get('mode')=='propagated')
            if fault=='empty':
                for n in walk(item['expression']):
                    if 'platformInheritance' in n:n['platformInheritance']['checkIds']=[]
            if fault=='wrong_type':definition['origin']=[];definition['mode']='direct'
            if fault=='cycle':definition['parents']=[{'consumer':definition['consumer'],'proofId':definition['id']}]
            if fault=='missing':item.pop('platformTypeProofs')
            if fault=='budget':item['platformTypeProofs']*=65
            if fault=='parent_scalar':definition['parents']=[7]
            finish(results,facts)
            self.assertFalse(bindings(item))
            self.assertEqual(item['expression']['op'],'call')

    def test_functional_callback_targets_preserve_unknown_body_and_stage_semantics(self):
        text=('import java.util.concurrent.CompletableFuture;class Rules implements AutoCloseable{public void close(){}'
            'Object f(CompletableFuture future){return future.whenComplete((v,e)->done()).thenApply(v->v);}}')
        result,_=extract(text);item=returns(result)[-1]
        self.assertEqual({c['method'] for _,c in bindings(item)},{'whenComplete','thenApply'})
        self.assertTrue(all(n['staticContract']['callbackBinding']['bodyTypeCheck']=='UNKNOWN' for n in walk(item) if 'staticContract' in n))

    def test_sensitive_context_has_no_typed_proof_or_value(self):
        text=('import java.math.BigDecimal;class Rules implements AutoCloseable{public void close(){}'
            'BigDecimal secretAmount(BigDecimal n){return n.add(new BigDecimal(87162345));}}')
        result,_=extract(text)
        self.assertNotIn('87162345',json.dumps(result))
        self.assertFalse(any('platformTypeProofs' in n or 'staticType' in n for n in walk(result)))

class PlatformProofCacheConsumerTests(unittest.TestCase):
    def test_validated_contract_proof_cannot_be_reused_by_result_type(self):
        for type_name in ('java.math.BigDecimal','java.time.Duration','int'):
            for order in ('donor_first','consumer_first'):
                with self.subTest(type_name=type_name,order=order):
                    results,facts=analyzed_files({'Rules.java':source('implements AutoCloseable')})
                    item=returns(results['Rules.java'])[-1];node=item['expression']
                    result_type=node['staticType'];contract=node['staticContract']
                    result_type['name']=type_name
                    result_type['platformInheritance']=copy.deepcopy(contract['platformInheritance'])
                    # Dict traversal order must not determine whether the valid
                    # donor definition masks an invalid consuming location.
                    order_values=[contract,result_type] if order=='donor_first' else [result_type,contract]
                    lookup=lambda identity,path=None:next((r for r in facts['Rules.java']['records']if r['id']==identity),None)
                    from test_policy_java_contracts import policy_semantics
                    _,reason=platform.requirements(list(reversed(order_values)),item,lookup=lookup,
                        api_validator=policy_semantics.policy_java_contracts.validate_catalog_entry)
                    self.assertEqual(reason,'platform_type_consumer_binding_invalid')
                    finish(results,facts)
                    self.assertFalse(bindings(item))
                    self.assertNotIn('staticType',item['expression'])
                    self.assertIn('platform_type_consumer_binding_invalid',json.dumps(item))

    def test_cached_parent_proof_cannot_be_reused_by_sibling_result(self):
        for swap in ('receiver','result'):
            results,facts=analyzed_files({'Rules.java':source('implements AutoCloseable',expression='join(n.abs(),n.negate(),Math.abs(3))')})
            item=returns(results['Rules.java'])[-1];first,second,independent=item['expression']['arguments']
            target=first['callee']['receiverStaticType'] if swap=='receiver' else first['staticType']
            donor=second['callee']['receiverStaticType'] if swap=='receiver' else second['staticType']
            target['platformInheritance']=copy.deepcopy(donor['platformInheritance'])
            before=copy.deepcopy(independent)
            finish(results,facts)
            self.assertNotIn('staticContract',first)
            self.assertEqual(next(c['method'] for c in item['standardApiContracts']
                if c['id']==second['staticContract']['contractId']),'negate')
            self.assertEqual({c['method']for _,c in bindings(item)},{'negate','abs'})
            self.assertEqual(item['expression']['arguments'][2],before)
            self.assertIn('platform_type_consumer_binding_invalid',json.dumps(item))

    def test_repeated_valid_consumer_and_equal_definitions_remain_valid(self):
        results,facts=analyzed_files({'Rules.java':source('implements AutoCloseable',expression='n.compareTo(n.abs())')})
        item=returns(results['Rules.java'])[-1]
        item['platformTypeProofs'].append(copy.deepcopy(item['platformTypeProofs'][0]))
        lookup=lambda identity,path=None:next((r for r in facts['Rules.java']['records']if r['id']==identity),None)
        from test_policy_java_contracts import policy_semantics
        consumer=item['expression']['staticType']
        _,reason=platform.requirements([consumer,consumer,item['expression']['staticContract']],item,lookup=lookup,
            api_validator=policy_semantics.policy_java_contracts.validate_catalog_entry)
        self.assertIsNone(reason)
        finish(results,facts)
        self.assertEqual(len(bindings(item)),2)
        self.assertEqual(item['expression']['staticType']['name'],'int')
