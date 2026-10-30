"""Neutral source-bound local initializer type inference, never runtime values."""
import copy
import hashlib
import json
import unittest

from test_policy_java_contracts import extract, returns, bindings, core, pipeline_java, policy_semantics
from test_policy_dependency_closure import analyzed_files, finish
from test_policy_literal_review import reviewed, occurrence, walk

PREFIX = 'import java.math.BigDecimal; '


def local(result, name='amount'):
    return next(row for row in result['fragments'] if row.get('category') == 'local_declaration' and row.get('name') == name)


def last_return(result):
    return returns(result)[-1]


def methods(row):
    return {contract['method'] for _, contract in bindings(row)}


def typed_source(body, extra=''):
    return PREFIX + 'class Rules {' + extra + ' Object f(BigDecimal input){' + body + '}}'


class LocalInitializerTypeTests(unittest.TestCase):
    def test_parameter_initializer_preserves_declared_type_and_definition_binding(self):
        source=typed_source('var amount=input; return amount.abs();')
        result,_=extract(source); declaration=local(result); returned=last_return(result)
        self.assertEqual(methods(returned),{'abs'})
        binding=declaration['localTypeInference']
        self.assertEqual(binding['status'],'source_initializer_static_type')
        self.assertEqual(binding['inferredType'],'java.math.BigDecimal')
        self.assertEqual(binding['declarationFragmentId'],declaration['id'])
        self.assertEqual(binding['path'],'Rules.java')
        self.assertEqual(binding['sourceDigest'],hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(source[binding['initializerRange']['charStart']:binding['initializerRange']['charEnd']],'input')
        self.assertEqual(returned['expression']['callee']['receiverStaticType']['localTypeBinding'],binding)
        self.assertEqual(binding['runtimeValue'],'UNKNOWN')
        self.assertEqual(binding['definiteAssignment'],'UNKNOWN')
        self.assertNotIn('parameterName',returned['expression']['callee']['receiverStaticType'])
        self.assertIn(declaration['id'],returned['expression']['staticContract']['sourceEvidenceIds'])

    def test_standard_constructor_exact_source_call_and_primitive_initializers(self):
        sources=[
            typed_source('var amount=new BigDecimal("3"); return amount.abs();'),
            typed_source('var amount=make(input); return amount.abs();','BigDecimal make(BigDecimal n){return n;}'),
            'class Rules{int f(){var amount=3;return Math.max(amount,1);}}',
        ]
        for source in sources:
            with self.subTest(source=source):
                result,_=extract(source)
                self.assertTrue(methods(last_return(result)))
                self.assertEqual(local(result)['localTypeInference']['status'],'source_initializer_static_type')

    def test_transitive_local_initializers_keep_each_provider(self):
        result,_=extract(typed_source('var first=input; var amount=first; return amount.abs();'))
        self.assertEqual(methods(last_return(result)),{'abs'})
        evidence=last_return(result)['expression']['staticContract']['sourceEvidenceIds']
        self.assertNotIn(local(result,'first')['id'],evidence)
        self.assertIn(local(result)['id'],evidence)
        self.assertEqual(local(result)['expression']['staticType']['sourceEvidenceIds'],[local(result,'first')['id']])

    def test_assignment_does_not_reinfer_type_or_runtime_value(self):
        source=typed_source('var amount=input; amount=unknown(); return amount.abs();','BigDecimal unknown(){return null;}')
        result,_=extract(source)
        self.assertEqual(methods(last_return(result)),{'abs'})
        self.assertEqual(local(result)['localTypeInference']['runtimeValue'],'UNKNOWN')
        self.assertEqual(last_return(result)['dataFlow']['resolution'],'lexical_candidates_not_reaching_definitions')

    def test_final_var_and_codepoint_ranges(self):
        source=typed_source('// 한국어 😀\r\nfinal var amount=input;\r\nreturn amount.abs();')
        result,_=extract(source); binding=local(result)['localTypeInference']
        self.assertEqual(methods(last_return(result)),{'abs'})
        self.assertEqual(source[binding['sourceRange']['charStart']:binding['sourceRange']['charEnd']],'final var amount=input;')
        self.assertGreater(len(source[:binding['sourceRange']['charStart']].encode()),binding['sourceRange']['charStart'])

    def test_unresolved_overloaded_factory_and_null_remain_unknown(self):
        cases=[
            typed_source('var amount=null; return amount.abs();'),
            typed_source('var amount=unknown(); return amount.abs();'),
            typed_source('var amount=make(null); return amount.abs();','BigDecimal make(String s){return null;} BigDecimal make(Integer n){return null;}'),
            typed_source('var amount; return amount.abs();'),
        ]
        for source in cases:
            with self.subTest(source=source):
                result,_=extract(source)
                self.assertFalse(methods(last_return(result)))
                self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')

    def test_multiple_declarators_and_malformed_modifiers_are_unknown(self):
        for body in ('var amount=input, other=input; return amount.abs();',
                     'public var amount=input; return amount.abs();',
                     'static var amount=input; return amount.abs();',
                     'var amount+=input; return amount.abs();'):
            with self.subTest(body=body):
                result,_=extract(typed_source(body))
                self.assertFalse(methods(last_return(result)))
                self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')

    def test_unbraced_control_body_does_not_claim_legal_local_declaration(self):
        for prefix in ('if(true) ', 'while(true) ', 'label: '):
            with self.subTest(prefix=prefix):
                result,_=extract(typed_source(prefix+'var amount=input;return amount.abs();'))
                self.assertFalse(methods(last_return(result)))
                self.assertFalse(any(f.get('localTypeInference',{}).get('status')=='source_initializer_static_type' for f in result['fragments']))

    def test_no_initializer_semicolon_does_not_claim_local_type(self):
        source=typed_source('var amount=input')
        result,_=extract(source)
        self.assertFalse(any(row.get('localTypeInference',{}).get('status')=='source_initializer_static_type' for row in result['fragments']))

    def test_self_and_forward_reference_do_not_fall_back_to_outer_declaration(self):
        cases=[
            typed_source('var amount=amount; return amount.abs();','BigDecimal amount;'),
            typed_source('var amount=next; var next=input; return amount.abs();'),
        ]
        for source in cases:
            with self.subTest(source=source):
                result,_=extract(source)
                self.assertFalse(methods(last_return(result)))
                self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')

    def test_scope_shadowing_and_unknown_local_block_outer_type(self):
        cases=[
            typed_source('{var amount=input;} return amount.abs();'),
            typed_source('var amount=input; {var amount=unknown(); return amount.abs();}'),
            typed_source('var amount=unknown(); return amount.abs();','BigDecimal amount;'),
            PREFIX+'class Rules{BigDecimal f(BigDecimal input){var amount=input;return amount;}Object g(){return amount.abs();}}',
        ]
        for source in cases:
            with self.subTest(source=source):
                result,_=extract(source)
                self.assertFalse(methods(last_return(result)))

    def test_lambda_binder_does_not_inherit_local_type(self):
        source=typed_source('var amount=input; return apply(amount -> amount.abs());')
        result,_=extract(source)
        self.assertFalse(methods(last_return(result)))

    def test_anonymous_and_unsupported_generic_initializers_remain_unknown(self):
        cases=[
            typed_source('var amount=new BigDecimal(3){public String toString(){return null;}};return amount.abs();'),
            'import java.util.ArrayList;class Rules{Object f(){var amount=new ArrayList<>();return amount.get(0);}}',
            'import java.util.function.Supplier;class Rules{Object f(){var amount=()->3;return amount.get();}}',
        ]
        for source in cases:
            with self.subTest(source=source):
                result,_=extract(source)
                self.assertFalse(methods(last_return(result)))
                self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')

    def test_sensitive_structure_does_not_supply_inferred_type(self):
        source=typed_source('var secretAmount=input; return secretAmount.abs();')
        result,_=extract(source)
        self.assertTrue(local(result,'secretAmount')['structuralOnly'])
        self.assertFalse(methods(last_return(result)))
        self.assertEqual(local(result,'secretAmount')['localTypeInference']['status'],'UNKNOWN')

    def test_no_java_index_never_claims_inferred_type(self):
        source=typed_source('var amount=input;return amount.abs();');digest=hashlib.sha256(source.encode()).hexdigest()
        result=policy_semantics.extract_semantics(source,'Java','Rules.java',digest)
        self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
        self.assertFalse(methods(last_return(result)))

    def test_missing_or_mutated_initializer_withdraws_derived_contracts(self):
        source=typed_source('var amount=input;return amount.abs();')
        for fault in ('missing','expression','static_type','structural','digest','name','range','catalog'):
            with self.subTest(fault=fault):
                results,facts=analyzed_files({'Rules.java':source});result=results['Rules.java'];provider=local(result)
                self.assertEqual(methods(last_return(result)),{'abs'})
                if fault=='missing':result['fragments'].remove(provider)
                elif fault=='expression':provider['expression']=None
                elif fault=='static_type':provider['expression'].pop('staticType')
                elif fault=='structural':provider['structuralOnly']=True
                elif fault=='digest':provider['sourceDigest']='0'*64
                elif fault=='name':provider['name']='other'
                elif fault=='range':provider['sourceRange']['charStart']+=1
                elif fault=='catalog':provider['localTypeInference']['inferredType']='java.lang.String'
                finish(results,facts)
                returned=last_return(result)
                self.assertFalse(methods(returned))
                self.assertEqual(returned['expression']['callee']['name'],'amount.abs')
                self.assertEqual(returned['dependencyClosure']['status'],'invalidated')
                self.assertFalse(any(n.get('basis')=='source_local_initializer_type' for n in walk(returned)))

    def test_budget_omission_and_transitive_provider_loss_are_explicit(self):
        source=typed_source('var first=input; var amount=first; return amount.abs();')
        results,facts=analyzed_files({'Rules.java':source});result=results['Rules.java'];provider=local(result,'first')
        result['fragments'].remove(provider)
        result['omissions'].append({'id':provider['id'],'reason':'fragment_budget_exceeded','status':'not_processed'})
        result['coverage']['inventoryComplete']=False
        finish(results,facts)
        self.assertFalse(methods(last_return(result)))
        self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
        self.assertFalse(result['coverage']['inventoryComplete'])
        self.assertEqual(result['omissions'][0]['id'],provider['id'])

    def test_late_literal_revocation_withdraws_only_dependent_local_proofs(self):
        source=typed_source('var amount=new BigDecimal("3"); return combine(amount.abs(),input.abs());')
        review,_=reviewed(source,[occurrence(source,'"3"')])
        results,facts=analyzed_files({'Rules.java':source},review=review);result=results['Rules.java']
        self.assertEqual(methods(last_return(result)),{'abs'})
        original=copy.deepcopy(last_return(result)['expression']['arguments'][1])
        review.reject(0,'fragment_redacted')
        policy_semantics.finalize_literal_review(result,review);finish(results,facts)
        self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
        self.assertNotIn('staticContract',last_return(result)['expression']['arguments'][0])
        self.assertEqual(last_return(result)['expression']['arguments'][1],original)
        self.assertFalse(any(n.get('basis')=='source_local_initializer_type' for n in walk(result)))

    def test_explicit_this_field_is_not_local_self_reference(self):
        result,_=extract(typed_source('var amount=this.amount;return amount.abs();','BigDecimal amount;'))
        self.assertEqual(methods(last_return(result)),{'abs'})
        self.assertEqual(local(result)['localTypeInference']['status'],'source_initializer_static_type')

    def test_compact_chain_respects_existing_dependency_depth_budget(self):
        body='var item0=input;'+''.join('var item'+str(i)+'=item'+str(i-1)+';' for i in range(1,256))+'return item255.abs();'
        result,_=extract(typed_source(body))
        declarations=[f for f in result['fragments'] if f.get('declaredType')=='var']
        self.assertEqual(len(declarations),256)
        self.assertEqual(sum(f['localTypeInference']['status']=='source_initializer_static_type' for f in declarations),policy_semantics.MAX_EXPRESSION_DEPTH)
        self.assertEqual(declarations[policy_semantics.MAX_EXPRESSION_DEPTH]['localTypeInference']['reason'],'local_initializer_dependency_depth_exceeded')
        self.assertFalse(methods(last_return(result)))
        self.assertLess(len(json.dumps(result).encode()),1024*1024)
        for declaration in declarations[:policy_semantics.MAX_EXPRESSION_DEPTH]:
            self.assertEqual(declaration['localTypeInference']['sourceEvidenceIds'],[declaration['id']])
            self.assertLess(len(json.dumps(declaration['localTypeInference']).encode()),1400)
        coverage=result['coverage']['localTypeInference']
        self.assertEqual(coverage['denominator'],256)
        self.assertEqual(coverage['unknown'],256-policy_semantics.MAX_EXPRESSION_DEPTH)
        self.assertEqual(coverage['wholeTypeCoverage'],'UNKNOWN')

    def test_mutated_use_scope_cannot_keep_inferred_type(self):
        results,facts=analyzed_files({'Rules.java':typed_source('var amount=input;return amount.abs();')})
        returned=last_return(results['Rules.java'])
        returned['sourceRange']['charStart']=0
        finish(results,facts)
        self.assertFalse(methods(returned))
        self.assertEqual(returned['dependencyClosure']['status'],'invalidated')

    def test_explicit_types_are_unchanged_by_local_inference(self):
        source=typed_source('BigDecimal amount=input; return amount.abs();')
        result,_=extract(source)
        self.assertNotIn('localTypeInference',local(result))
        self.assertEqual(methods(last_return(result)),{'abs'})


class LocalInitializerOwnershipTests(unittest.TestCase):
    EXACT = 'import java.math.BigDecimal;class Rules{BigDecimal local;Object probe(BigDecimal input){class Nested{String local;Object read(){var nested=local;return nested;}}var result=input;return result.abs();}}'
    GOOD = 'Object good(BigDecimal input){var amount=input;return amount.abs();}'

    def test_local_class_counterexample_never_promotes_outer_field(self):
        result,_=extract(self.EXACT)
        nested=local(result,'nested')
        self.assertEqual(nested['localTypeInference']['status'],'UNKNOWN')
        self.assertEqual(nested['localTypeInference']['reason'],'local_initializer_owner_unproven')
        self.assertNotIn('staticType',nested['expression'])
        self.assertFalse(any(methods(row) for row in result['fragments']))
        # Existing statement scanning does not emit the trailing declaration;
        # preserve that unsupported region instead of claiming it is fixed.
        self.assertFalse(any(row.get('name')=='result' for row in result['fragments']))
        self.assertTrue(any(row['representationStatus']=='unsupported' for row in result['fragments']))
        self.assertFalse(result['coverage']['semanticComplete'])

    def test_local_class_and_this_keep_independent_positive_method(self):
        for reference in ['local','this.local']:
            source=self.EXACT.replace('var nested=local','var nested='+reference)[:-1]+self.GOOD+'}'
            result,_=extract(source)
            self.assertEqual(local(result,'nested')['localTypeInference']['status'],'UNKNOWN')
            self.assertEqual(methods(last_return(result)),{'abs'})
            self.assertEqual(local(result)['localTypeInference']['status'],'source_initializer_static_type')
        source=PREFIX+'class Rules{BigDecimal local;Object f(BigDecimal input){var amount=input;amount.abs();class Nested{String local;Object read(){var nested=local;return nested;}}}}'
        result,_=extract(source)
        self.assertEqual(local(result)['localTypeInference']['status'],'source_initializer_static_type')
        self.assertTrue(any(methods(row)=={'abs'} for row in result['fragments']))
        self.assertEqual(local(result,'nested')['localTypeInference']['status'],'UNKNOWN')

    def test_named_member_type_nearest_field_and_this_are_not_outer_field(self):
        for reference in ['local','this.local']:
            source=PREFIX+'class Rules{BigDecimal local;class Nested{String local;Object read(){var nested='+reference+';return nested;}}'+self.GOOD+'}'
            result,_=extract(source)
            nested=local(result,'nested')
            self.assertEqual(nested['localTypeInference']['inferredType'],'java.lang.String')
            self.assertEqual(methods(last_return(result)),{'abs'})
            self.assertNotEqual(nested['localTypeInference']['lexicalOwner']['callableSymbolId'],local(result)['localTypeInference']['lexicalOwner']['callableSymbolId'])

    def test_inherited_member_prevents_enclosing_field_fallback(self):
        for parent in ['Base','NotSelected']:
            for reference in ['local','this.local']:
                source=PREFIX+'class Base{String local;}class Rules{BigDecimal local;class Nested extends '+parent+'{Object read(){var nested='+reference+';return nested;}}'+self.GOOD+'}'
                result,_=extract(source)
                self.assertEqual(local(result,'nested')['localTypeInference']['status'],'UNKNOWN')
                self.assertNotIn('staticType',local(result,'nested')['expression'])
                self.assertEqual(methods(last_return(result)),{'abs'})
        # Enclosing capture may be legal, but the selected bridge does not
        # prove the absence of a nearer inherited/member declaration.
        result,_=extract(PREFIX+'class Rules{BigDecimal local;class Nested{Object read(){var nested=local;return nested;}}'+self.GOOD+'}')
        self.assertEqual(local(result,'nested')['localTypeInference']['status'],'UNKNOWN')
        self.assertEqual(methods(last_return(result)),{'abs'})

    def test_anonymous_class_does_not_gain_unproven_owner(self):
        source=PREFIX+'class Rules{BigDecimal local;Object make(){return new Object(){String local;Object read(){var nested=local;return nested;}};}'+self.GOOD+'}'
        result,_=extract(source)
        nested=local(result,'nested')
        self.assertEqual(nested['localTypeInference']['status'],'UNKNOWN')
        self.assertNotIn('staticType',nested['expression'])
        self.assertEqual(methods(last_return(result)),{'abs'})

    def test_missing_or_disagreeing_index_owner_is_unknown(self):
        source=typed_source('var amount=input;return amount.abs();')
        digest=hashlib.sha256(source.encode()).hexdigest()
        index=core.build_java_index({'Rules.java':source})
        facts={'path':'Rules.java','sourceDigest':digest,'module':'synthetic','modulePath':'.','language':'Java','records':[]}
        pipeline_java.enrich(facts,index)
        for fault in ['missing','callable_range','type_range']:
            context=pipeline_java.semantic_type_context(facts,index)
            correct=context['lexicalCallableOwner'](source.index('var amount'))
            if fault=='missing':context.pop('lexicalCallableOwner')
            else:
                wrong=copy.deepcopy(correct)
                wrong['callableBodyRange' if fault=='callable_range' else 'typeBodyRange']['charStart']+=1
                context['lexicalCallableOwner']=lambda *_,proof=wrong:proof
            result=policy_semantics.extract_semantics(source,'Java','Rules.java',digest,java_type_context=context)
            self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
            self.assertNotIn('staticType',local(result)['expression'])
            self.assertFalse(methods(last_return(result)))

    def test_owner_catalog_loss_mutation_and_use_owner_revoke_only_dependents(self):
        source=typed_source('var amount=input;amount.abs();return input.abs();')
        for fault in ['missing_type','missing_method','method_owner','symbol_digest','binding_owner','use_owner']:
            with self.subTest(fault=fault):
                results,facts=analyzed_files({'Rules.java':source});result=results['Rules.java']
                declaration=local(result);proof=declaration['localTypeInference']['lexicalOwner']
                dependent=next(row for row in result['fragments'] if methods(row) and row['category']!='return')
                independent=copy.deepcopy(last_return(result))
                if fault=='binding_owner':proof['callableSymbolId']='p:'+'0'*64
                if fault=='use_owner':dependent['controlFlow']['owner']['id']='semantic:'+'0'*64
                def alter(row):
                    if fault=='missing_type' and row['id']==proof['typeSymbolId']:return None
                    if fault=='missing_method' and row['id']==proof['callableSymbolId']:return None
                    if row['id']==proof['callableSymbolId']:
                        row=copy.deepcopy(row)
                        if fault=='method_owner':row['owner']='Different'
                        if fault=='symbol_digest':row['sourceDigest']='0'*64
                    return row
                finish(results,facts,alter)
                self.assertFalse(methods(dependent))
                # The direct parameter API proof is independent of the new
                # local owner catalog. It survives when its symbol survives.
                if fault not in {'missing_method','symbol_digest'}:
                    self.assertEqual(last_return(result),independent)

    def test_captured_outer_var_use_in_local_class_is_not_same_callable(self):
        source=PREFIX+'class Rules{Object f(BigDecimal input){var amount=input;amount.abs();class Nested{Object read(){return amount.abs();}}}}'
        result,_=extract(source)
        self.assertEqual(local(result)['localTypeInference']['status'],'source_initializer_static_type')
        self.assertEqual(sum(bool(methods(row)) for row in result['fragments']),1)
        self.assertFalse(methods(last_return(result)))


class LocalInitializerDefinitionTests(unittest.TestCase):
    SOURCE = PREFIX+'class Rules{Object probe(BigDecimal input){var amount=input;return amount.abs();}Object sibling(BigDecimal input){return input.abs();}}'

    def analyzed(self,source=None):
        results,facts=analyzed_files({'Rules.java':source or self.SOURCE})
        return results,facts,results['Rules.java']

    def assert_withdrawn(self,results,facts,result,transform=None):
        independent=copy.deepcopy(returns(result)[-1])
        finish(results,facts,transform)
        self.assertFalse(methods(returns(result)[0]))
        self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
        self.assertEqual(returns(result)[-1],independent)
        self.assertFalse(result['coverage']['semanticComplete'])
        self.assertEqual(result['coverage']['localTypeInference']['unknown'],1)

    def test_projected_ranges_are_full_declarations_and_codepoints(self):
        source='// 한국어 😀\r\n'+PREFIX+'class Rules {\r\n Object probe(BigDecimal input) {\r\n var amount=input;\r\n return amount.abs();\r\n }\r\n}'
        results,facts,result=self.analyzed(source);finish(results,facts)
        declaration=local(result);proof=declaration['localTypeInference']['lexicalOwner']
        records={row['id']:row for row in facts['Rules.java']['records']}
        self.assertNotIn('callableId',proof)
        self.assertIn(declaration['controlFlow']['owner']['id'],records)
        self.assertEqual(declaration['controlFlow']['owner']['id'],proof['callableSymbolId'])
        for prefix in ['type','callable']:
            record=records[proof[prefix+'SymbolId']]
            self.assertEqual(record['sourceRange'],record['declarationRange'])
            self.assertEqual(record['declarationRange'],proof[prefix+'DeclarationRange'])
            self.assertEqual(record['bodyRange'],proof[prefix+'BodyRange'])
            region=record['sourceRange'];body=record['bodyRange']
            self.assertEqual(source[body['charStart']],'{')
            self.assertEqual(source[body['charEnd']-1],'}')
            self.assertEqual(source[region['charStart']:region['charEnd']].count('return amount.abs();'),1)
            self.assertEqual(record['declarationSpan']['lineStart'],source[:region['charStart']].count('\n')+1)
            self.assertEqual(record['declarationSpan']['lineEnd'],source[:region['charEnd']-1].count('\n')+1)
            self.assertGreater(len(source[:region['charStart']].encode()),region['charStart'])
        method=records[proof['callableSymbolId']]
        self.assertGreater(method['declarationSpan']['lineEnd'],method['headerSpan']['lineEnd'])
        self.assertEqual(methods(returns(result)[0]),{'abs'})
        self.assertEqual(result['sourceLength'],len(source))

    def test_all_copied_owner_ranges_still_require_actual_definition(self):
        for field,edge,delta in [('typeBodyRange','charEnd',100),('typeBodyRange','charEnd',-1),
                                 ('callableBodyRange','charStart',-1),('callableBodyRange','charEnd',1),
                                 ('typeDeclarationRange','charStart',-1),('callableDeclarationRange','charStart',-1)]:
            with self.subTest(field=field,edge=edge):
                results,facts,result=self.analyzed()
                target=local(result)['localTypeInference']['lexicalOwner']['callableSymbolId']
                for node in walk(result):
                    proof=node.get('lexicalOwner')
                    if isinstance(proof,dict):proof[field][edge]+=delta
                    owner=node.get('owner')
                    if field=='callableDeclarationRange' and isinstance(owner,dict) and owner.get('id')==target:
                        owner['sourceRange'][edge]+=delta
                self.assert_withdrawn(results,facts,result)

    def test_missing_or_disagreeing_projected_ranges_revoke(self):
        for owner_kind in ['type','callable']:
            for field in ['sourceRange','declarationRange','bodyRange']:
                for mutation in ['remove','mismatch']:
                    with self.subTest(owner=owner_kind,field=field,mutation=mutation):
                        results,facts,result=self.analyzed()
                        target=local(result)['localTypeInference']['lexicalOwner'][owner_kind+'SymbolId']
                        def alter(row):
                            if row['id']!=target:return row
                            row=copy.deepcopy(row)
                            if mutation=='remove':row.pop(field,None)
                            else:row[field]={'charStart':0,'charEnd':1}
                            return row
                        self.assert_withdrawn(results,facts,result,alter)

    def test_sibling_symbol_substitution_is_not_owner_evidence(self):
        results,facts,result=self.analyzed()
        previous=local(result)['localTypeInference']['lexicalOwner']['callableSymbolId']
        sibling=next(row['id'] for row in facts['Rules.java']['records'] if row.get('type')=='Method' and row.get('name')=='sibling')
        for node in walk(result):
            proof=node.get('lexicalOwner')
            if isinstance(proof,dict):proof['callableSymbolId']=sibling
            owner=node.get('owner')
            if isinstance(owner,dict) and owner.get('id')==previous:owner['id']=sibling
        self.assert_withdrawn(results,facts,result)

    def test_consistently_fabricated_identity_has_no_definition(self):
        for bogus in ['semantic:'+'f'*64,'p:'+'f'*64]:
            results,facts,result=self.analyzed()
            previous=local(result)['localTypeInference']['lexicalOwner']['callableSymbolId']
            for node in walk(result):
                proof=node.get('lexicalOwner')
                if isinstance(proof,dict):proof['callableSymbolId']=bogus
                owner=node.get('owner')
                if isinstance(owner,dict) and owner.get('id')==previous:owner['id']=bogus
            self.assert_withdrawn(results,facts,result)

    def test_legacy_phantom_callable_id_is_not_an_accepted_owner_contract(self):
        results,facts,result=self.analyzed()
        for node in walk(result):
            proof=node.get('lexicalOwner')
            if isinstance(proof,dict):proof['callableId']='semantic:'+'f'*64
        self.assert_withdrawn(results,facts,result)

    def test_revoked_structural_and_spoofed_named_definitions_revoke(self):
        for fault in ['revoked','structural','owner','name','declaration_span']:
            results,facts,result=self.analyzed()
            target=local(result)['localTypeInference']['lexicalOwner']['callableSymbolId']
            def alter(row):
                if row['id']!=target:return row
                row=copy.deepcopy(row)
                if fault=='revoked':row['status']='revoked'
                if fault=='structural':row['structuralOnly']=True
                if fault=='owner':row['owner']='Different'
                if fault=='name':row['name']='different'
                if fault=='declaration_span':row['declarationSpan']={'lineStart':0,'lineEnd':1}
                return row
            self.assert_withdrawn(results,facts,result,alter)

    def test_standalone_finalization_requires_actual_owner_records(self):
        result,_=extract(self.SOURCE)
        self.assertEqual(methods(returns(result)[0]),{'abs'})
        independent=copy.deepcopy(returns(result)[-1])
        policy_semantics.finalize_dependencies(result)
        self.assertFalse(methods(returns(result)[0]))
        self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
        self.assertEqual(returns(result)[-1],independent)

    def test_missing_or_duplicate_extraction_owner_record_is_unknown(self):
        for fault in ['callback_missing','symbol_missing','duplicate_symbol']:
            source=self.SOURCE;digest=hashlib.sha256(source.encode()).hexdigest()
            index=core.build_java_index({'Rules.java':source})
            facts={'path':'Rules.java','sourceDigest':digest,'module':'synthetic','modulePath':'.','language':'Java','records':[]}
            pipeline_java.enrich(facts,index)
            type_record=next(row for row in facts['records'] if row.get('type')=='Class')
            if fault=='symbol_missing':facts['records'].remove(type_record)
            if fault=='duplicate_symbol':facts['records'].append(copy.deepcopy(type_record))
            context=pipeline_java.semantic_type_context(facts,index)
            if fault=='callback_missing':context.pop('sourceDefinition')
            result=policy_semantics.extract_semantics(source,'Java','Rules.java',digest,java_type_context=context)
            self.assertEqual(local(result)['localTypeInference']['status'],'UNKNOWN')
            self.assertFalse(methods(returns(result)[0]))
            self.assertEqual(methods(returns(result)[-1]),{'abs'})


if __name__=='__main__':unittest.main()
