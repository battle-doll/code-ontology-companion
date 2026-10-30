"""Synthetic emitted-definition closure; source syntax is never replaced."""
import copy
import hashlib
import json
import unittest

from test_policy_java_contracts import core, pipeline_java, policy_semantics, returns, bindings
from test_policy_literal_review import walk, reviewed, occurrence

CONSTANT = 'package sample;public class Constants{public static final java.math.BigDecimal FLOOR=java.math.BigDecimal.ZERO;}'
IMPORTER = 'import static sample.Constants.FLOOR;class Rules{Object f(java.math.BigDecimal n){return n.add(FLOOR);}}'


def analyzed_files(sources, budgets=None, review=None):
    index = core.build_java_index(sources)
    results, all_facts = {}, {}
    for path, source in sources.items():
        digest = hashlib.sha256(source.encode()).hexdigest()
        facts = {'path':path,'sourceDigest':digest,'module':'synthetic','modulePath':'.','language':'Java','records':[]}
        pipeline_java.enrich(facts,index)
        all_facts[path] = facts
        results[path] = policy_semantics.extract_semantics(source,'Java',path,digest,
            java_type_context=pipeline_java.semantic_type_context(facts,index),literal_review=review,
            max_fragments=(budgets or {}).get(path,20000),defer_external_dependencies=True)
    return results,all_facts


def finish(results,facts,transform=None):
    def lookup(identity,path=None):
        for name,result in results.items():
            if path is not None and name != path: continue
            for row in result['fragments']:
                if row['id']==identity:
                    row={**row,'kind':'semantic_fragment'}
                    return transform(row) if transform else row
            for row in facts[name]['records']:
                if row['id']==identity: return transform(row) if transform else row
    for result in results.values(): policy_semantics.finalize_dependencies(result,lookup)
    return lookup


def row(result): return returns(result)[-1]


class DependencyClosureTests(unittest.TestCase):
    def test_same_file_omitted_constant_withdraws_add_but_keeps_receiver(self):
        source='package sample;import static sample.Constants.FLOOR;class Rules{Object f(java.math.BigDecimal n){return n.add(FLOOR);}}'+CONSTANT.split(';',1)[1]
        results,_=analyzed_files({'Rules.java':source},{'Rules.java':1})
        result=results['Rules.java']; fragment=row(result)
        self.assertFalse(bindings(fragment))
        self.assertEqual(fragment['expression']['callee']['receiverStaticType']['name'],'java.math.BigDecimal')
        self.assertEqual(fragment['expression']['arguments'][0]['name'],'FLOOR')
        self.assertNotIn('staticFieldBinding',fragment['expression']['arguments'][0])
        self.assertEqual(fragment['expression']['staticContractStatus']['status'],'UNKNOWN')
        self.assertFalse(result['coverage']['inventoryComplete'])
        self.assertEqual(result['coverage']['detectedFragments'],2)
        self.assertEqual(len(result['omissions']),1)

    def test_standalone_cross_file_defaults_unknown_and_explicit_stage_is_pending(self):
        results,facts=analyzed_files({'Rules.java':IMPORTER,'Constants.java':CONSTANT})
        self.assertEqual(results['Rules.java']['coverage']['dependencyClosure']['status'],'pending_snapshot_finalization')
        self.assertTrue(bindings(row(results['Rules.java'])))
        digest=hashlib.sha256(IMPORTER.encode()).hexdigest(); index=core.build_java_index({'Rules.java':IMPORTER,'Constants.java':CONSTANT})
        result=policy_semantics.extract_semantics(IMPORTER,'Java','Rules.java',digest,
            java_type_context=pipeline_java.semantic_type_context(facts['Rules.java'],index))
        self.assertFalse(bindings(row(result)))
        self.assertEqual(result['coverage']['dependencyClosure']['status'],'finalized')
        finish(results,facts)
        self.assertTrue(bindings(row(results['Rules.java'])))
        self.assertEqual(results['Rules.java']['coverage']['dependencyClosure']['status'],'finalized')

    def test_cross_file_missing_unsupported_stale_kind_name_range_are_not_positive(self):
        for fault in ('missing','unsupported','stale','kind','name','range'):
            with self.subTest(fault=fault):
                results,facts=analyzed_files({'Rules.java':IMPORTER,'Constants.java':CONSTANT})
                target=results['Constants.java']['fragments'][0]
                if fault=='missing': results['Constants.java']['fragments']=[]
                if fault=='unsupported': target.update(expression=None,representationStatus='unsupported',unsupportedReasons=['literal_review_revoked'])
                def alter(record):
                    if record['id']!=target['id']: return record
                    record=copy.deepcopy(record)
                    if fault=='stale': record['sourceDigest']='0'*64
                    if fault=='kind': record['kind']='symbol'
                    if fault=='name': record['name']='OTHER'
                    if fault=='range': record['sourceRange']['charEnd']-=1
                    return record
                finish(results,facts,alter)
                self.assertFalse(bindings(row(results['Rules.java'])))
                self.assertEqual(row(results['Rules.java'])['dependencyClosure']['status'],'invalidated')

    def test_late_revocation_retires_loop_type_accessor_and_api_evidence(self):
        source='record Item(java.math.BigDecimal amount){}class Rules{Item[] make(String label){return null;}void use(java.math.BigDecimal n){}void consume(String t){}void f(){for(Item item:make("MODE_A")){use(item.amount().abs());consume("TRIGGER_MODE");}}}'
        review,digest=reviewed(source,[occurrence(source,'"MODE_A"'),occurrence(source,'"TRIGGER_MODE"')])
        bound=review.bind_source('Rules.java',source,digest); admit=bound.admit
        def revoke(left,right,**kwargs):
            if left==source.index('"TRIGGER_MODE"'): review.reject(0,'fragment_redacted')
            return admit(left,right,**kwargs)
        bound.admit=revoke
        results,facts=analyzed_files({'Rules.java':source},review=review)
        finish(results,facts); result=results['Rules.java']
        body=next(f for f in result['fragments'] if any(n.get('name')=='item.amount' for n in walk(f)))
        self.assertFalse(bindings(body))
        self.assertFalse(any(n.get('basis')=='explicit_enhanced_for_variable_type' or 'staticAccessorBinding' in n for n in walk(body)))
        self.assertNotIn('MODE_A',json.dumps(result))
        self.assertFalse(any('loopBodyId' in n for n in walk(result)))
        self.assertTrue(any(n.get('name')=='item.amount' for n in walk(body)))

    def test_surviving_sibling_contract_and_literal_are_unchanged(self):
        source=IMPORTER.replace('n.add(FLOOR)','combine(n.add(FLOOR),n.abs(),17)')
        results,facts=analyzed_files({'Rules.java':source,'Constants.java':CONSTANT})
        fragment=row(results['Rules.java']); old=copy.deepcopy(fragment['expression']['arguments'][1:])
        results['Constants.java']['fragments']=[]
        finish(results,facts)
        self.assertEqual(fragment['expression']['arguments'][1:],old)
        self.assertEqual({c['method'] for _,c in bindings(fragment)},{'abs'})
        self.assertEqual(fragment['expression']['arguments'][2]['value'],'17')

    def test_cascade_and_cycle_fail_closed_without_source_replacement(self):
        middle='package sample;import static sample.Leaf.END;public class Constants{public static final java.math.BigDecimal FLOOR=END;}'
        leaf='package sample;public class Leaf{public static final java.math.BigDecimal END=java.math.BigDecimal.ZERO;}'
        for cycle in (False,True):
            last=leaf if not cycle else 'package sample;import static sample.Constants.FLOOR;public class Leaf{public static final java.math.BigDecimal END=FLOOR;}'
            results,facts=analyzed_files({'Rules.java':IMPORTER,'Constants.java':middle,'Leaf.java':last})
            if not cycle: results['Leaf.java']['fragments']=[]
            finish(results,facts)
            self.assertFalse(bindings(row(results['Rules.java'])))
            self.assertEqual(results['Constants.java']['fragments'][0]['expression']['name'],'END')
            self.assertEqual(results['Rules.java']['coverage']['dependencyClosure']['status'],'finalized')

    def test_mutated_inline_loop_definition_cannot_support_typed_child(self):
        source='record Item(java.math.BigDecimal amount){}class Rules{void f(Item[] values){for(Item item:values){use(item.amount().abs());}}}'
        for fault in ('body_id','variable_id','range','digest'):
            results,facts=analyzed_files({'Rules.java':source})
            header=next(f for f in results['Rules.java']['fragments'] if f['category']=='condition')
            if fault=='body_id': header['expression']['body']['id']='source-body:'+'0'*64
            if fault=='variable_id': header['expression']['variable']['id']='source-binding:'+'0'*64
            if fault=='range': header['expression']['variable']['sourceRange']['charEnd']+=100
            if fault=='digest': header['expression']['body']['sourceDigest']='0'*64
            finish(results,facts)
            self.assertFalse(any(bindings(f) for f in results['Rules.java']['fragments']))
            self.assertFalse(any('loopBodyId' in n for n in walk(results)))

    def test_missing_or_stale_constructor_catalog_cannot_keep_positive_mapping(self):
        source='record Pair(java.math.BigDecimal amount){}class Rules{Object f(java.math.BigDecimal n){return new Pair(n);}}'
        for fault in ('missing','range','symbol','digest'):
            results,facts=analyzed_files({'Rules.java':source});fragment=row(results['Rules.java'])
            if fault=='missing': fragment.pop('recordConstructorDeclarations')
            if fault=='range': fragment['recordConstructorDeclarations'][0]['sourceRange']['charStart']+=1
            if fault=='symbol': facts['Rules.java']['records']=[r for r in facts['Rules.java']['records'] if r['id']!=fragment['recordConstructorDeclarations'][0]['recordDeclarationId']]
            if fault=='digest': fragment['recordConstructorDeclarations'][0]['sourceDigest']='0'*64
            finish(results,facts)
            self.assertNotIn('recordConstruction',fragment['expression'])
            self.assertEqual(fragment['expression']['op'],'construct')
            self.assertEqual(fragment['expression']['arguments'][0]['name'],'n')

    def test_revoked_enum_assignment_retires_constructor_mapping_only(self):
        source='enum Mode{A(1);final int amount;Mode(int value){this.amount=value;}}'
        results,facts=analyzed_files({'Rules.java':source})
        declaration=next(f for f in results['Rules.java']['fragments'] if f['category']=='enum_constant')
        self.assertTrue(declaration['expression'].get('constructorBindings'))
        assignment=next(f for f in results['Rules.java']['fragments'] if f['category']=='assignment')
        assignment.update(expression=None,representationStatus='unsupported',unsupportedReasons=['literal_review_revoked'])
        finish(results,facts)
        self.assertNotIn('constructorBindings',declaration['expression'])
        self.assertEqual(declaration['expression']['arguments'][0]['value'],'1')

    def test_failed_initializer_type_removes_dependent_stage_identity(self):
        source='import java.util.concurrent.CompletableFuture;class Rules{void f(CompletableFuture<String> initial){CompletableFuture<String> next=initial.thenApply(value->value);}}'
        results,facts=analyzed_files({'Rules.java':source})
        fragment=next(f for f in results['Rules.java']['fragments'] if f.get('name')=='next')
        self.assertIn('stageInitializer',fragment)
        facts['Rules.java']['records']=[]
        finish(results,facts)
        self.assertNotIn('stageInitializer',fragment)
        self.assertEqual(fragment['expression']['callee']['name'],'initial.thenApply')


if __name__=='__main__': unittest.main()
