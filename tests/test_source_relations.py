"""Neutral source-relation proofs and fail-closed counterexamples."""
import copy,hashlib,json,os,re,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import policy_semantics as semantics,privacy_guard,code_ontology_core as core,pipeline_java

class SourceRelationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        profile=self.root/'profile.json';profile.write_text(json.dumps(privacy_guard.build_profile(['Neutral Protected Person'],[],key=b'r'*32,values=['neutral-denied-value'])));profile.chmod(0o600)
        env=patch.dict(os.environ,{privacy_guard.PROFILE_ENV:str(profile)});env.start();self.addCleanup(env.stop)
    def extract(self,source,**kwargs):
        path='neutral/Rules.java';digest=hashlib.sha256(source.encode()).hexdigest();facts={'path':path,'sourceDigest':digest,'module':'neutral','modulePath':'.','records':[]}
        index=core.build_java_index({path:source});pipeline_java.enrich(facts,index)
        result=semantics.extract_semantics(source,'Java',path,digest,java_type_context=pipeline_java.semantic_type_context(facts,index),**kwargs)
        return result,facts
    def relations(self,result,kind=None):
        return [r for f in result['fragments']for r in f.get('sourceRelations',{}).get('relations',[])if kind is None or r['relationKind']==kind]
    def finalize(self,result,facts,direct=False):
        function=semantics.finalize_source_relations if direct else semantics.finalize_dependencies
        return function(result,lookup=lambda rid,path=None:next((r for r in facts['records']if r['id']==rid),None),
                        inventory_lookup=lambda path:facts['records'])
    def test_exact_private_single_return_helper_links_ir_without_values(self):
        result,_=self.extract('record Box(int count){} class Rules{int g(int n){return f(n);}private int f(int x){return x+3;}}')
        relation=self.relations(result,'helper_return_source_summary')[0];self.assertEqual(relation['resolution'],'represented')
        self.assertEqual(relation['validation']['status'],'verified_emitted_ir');self.assertIn('targetReturnRef',relation['details'])
        self.assertNotIn('"value":',json.dumps(relation));self.assertFalse(relation['businessMeaningVerified'])
        self.assertEqual(relation['runtimeStatus'],'not_observed')
    def test_mutation_throw_recursive_virtual_and_extra_statement_remain_partial(self):
        cases=['private int f(int x){x++;return x;}','private int f(int x){if(x<0)throw new Error();return x;}',
               'private int f(int x){return f(x);}','int f(int x){return x;}','private int f(int x){side();return x;}']
        for helper in cases:
            result,_=self.extract('class Rules{int g(int n){return f(n);}'+helper+'}')
            rel=self.relations(result,'helper_return_source_summary');self.assertTrue(rel)
            self.assertTrue(all(r['resolution']!='represented'for r in rel))
        result,_=self.extract('class Rules{int g(int n){return f(n);}private int f(int x){return x;}private long f(long x){return x;}}')
        self.assertEqual(self.relations(result,'helper_return_source_summary')[0]['resolution'],'represented')
    def test_record_position_and_checked_explicit_transfer_never_become_stored_values(self):
        sources=['record Box(int count){}','record Box(int count){Box(int count){this.count=count;}}','record Box(int count){Box{count=count+1;}}']
        for declaration in sources:
            result,_=self.extract(declaration+'class Rules{Box g(int n){return new Box(n);}}')
            rel=self.relations(result,'constructor_parameter_component_transfer')[0]
            self.assertEqual(rel['resolution'],'represented');self.assertEqual(rel['details']['storedComponentValues'],'UNKNOWN')
            self.assertEqual(rel['details']['argumentApplicability'],'UNKNOWN')
    def test_constructor_early_throw_repeated_write_delegation_effect_and_overload_partial(self):
        bodies=['Box(int count){if(count<0)throw new Error();this.count=count;}',
                'Box(int count){this.count=count;this.count=count;}',
                'Box(int count){this(count,true);}Box(int count,boolean flag){this.count=count;}',
                'Box(int count){this.count=count;side();}', 'Box{count=Math.max(0,count);}', 'Box{count=count+1L;}']
        for body in bodies:
            result,_=self.extract('record Box(int count){'+body+'}class Rules{Box g(int n){return new Box(n);}}')
            self.assertTrue(all(r['resolution']!='represented'for r in self.relations(result,'constructor_parameter_component_transfer')))
    def test_branch_dataflow_partial_and_straightline_positive(self):
        good,_=self.extract('class Rules{int g(int n){int local=n;local=local+1;return local;}}')
        self.assertTrue(any(r['resolution']=='represented'for r in self.relations(good,'straight_line_reaching_definition')))
        bad,_=self.extract('class Rules{int g(int n){int local=n;if(n>0)local=2;return local;}}')
        self.assertTrue(all(r['resolution']!='represented'for r in self.relations(bad,'straight_line_reaching_definition')))
    def test_enum_nested_names_and_array_scope_are_not_merged(self):
        result,_=self.extract('class Left{enum Tag{A,B}}class Right{enum Tag{X,Y,Z}}')
        relations=self.relations(result,'enum_constant_declaration_position')
        self.assertEqual(sorted(r['details']['declarationPosition']for r in relations),[0,0,1,1,2])
        bad,_=self.extract('enum Tag{A,B}class Left{int[] limits={3,4};}class Rules{int g(Tag tag){int i=tag.ordinal();return limits[i];}}')
        self.assertFalse(self.relations(bad,'enum_array_initial_source_association'))
    def test_closure_and_mutated_provider_are_withdrawn(self):
        source='record Box(int count){} class Rules{Box g(int n){return new Box(n);}}'
        result,facts=self.extract(source);rel=self.relations(result)[0];rel['closureSha256']='0'*64
        semantics.finalize_dependencies(result,lookup=lambda rid,path=None:next((r for r in facts['records']if r['id']==rid),None))
        self.assertEqual(rel['resolution'],'unknown');self.assertEqual(rel['validation']['status'],'invalidated')
        result,facts=self.extract(source);result['fragments'][0]['expression']['recordConstruction']['resolution']='changed'
        semantics.finalize_dependencies(result,lookup=lambda rid,path=None:next((r for r in facts['records']if r['id']==rid),None))
        self.assertTrue(any(r['validation']['status']=='invalidated'for r in self.relations(result)))
    def test_budget_original_denominator_and_other_language_boundaries(self):
        source='record Box(int count){}class Rules{Box g(int n){int a=n;return new Box(a);}}'
        baseline,_=self.extract(source);bounded,_=self.extract(source,max_source_relations=0)
        c=bounded['coverage']['sourceRelations'];self.assertEqual(c['detected'],baseline['coverage']['sourceRelations']['detected']);self.assertEqual(c['omitted'],c['detected']);self.assertEqual(c['recorded'],0)
        for language in ['Python','JavaScript','TypeScript','Vue','Kotlin','C#','Go','Rust','C','C++','PHP','Swift','Dart','Ruby','Scala','Shell','PowerShell']:
            result=semantics.extract_semantics('x=2',language,'neutral/rules.txt',hashlib.sha256(b'x=2').hexdigest())
            self.assertEqual(result['coverage']['reasons'],['unsupported_fragment_language']);self.assertFalse(result['fragments'])
    def test_per_fragment_transport_budget_preserves_omitted_candidates(self):
        declarations=''.join('int local'+str(i)+'='+str(i)+';'for i in range(40))
        expression='+'.join('local'+str(i)for i in range(40))
        result,_=self.extract('class Rules{int g(){'+declarations+'return '+expression+';}}')
        coverage=result['coverage']['sourceRelations'];self.assertGreater(coverage['omitted'],0)
        self.assertEqual(coverage['detected'],coverage['recorded']+coverage['omitted'])
        self.assertEqual(coverage['omissionReasons'],['bounded_source_relation_budget'])
        for row in result['fragments']:
            if 'sourceRelations'in row:
                self.assertLess(len(semantics._canonical(row)),semantics.MAX_SOURCE_RELATION_RECORD_BYTES)
                self.assertLessEqual(sum(len(semantics._canonical(r))for r in row['sourceRelations']['relations']),semantics.MAX_SOURCE_RELATION_FRAGMENT_BYTES)

    def test_parser_unsupported_is_not_privacy_denial(self):
        source='class Rules{int g(int n){return helper(n);}private int helper(int x){return x;}}'
        for reason,expected in [('unsupported_expression_syntax','unsupported'),('sensitive_value_redacted','denied'),('literal_review_revoked','denied')]:
            result,facts=self.extract(source)
            for row in result['fragments']:row.pop('sourceRelations',None)
            owner=result['fragments'][0];owner['representationStatus']='unsupported';owner['unsupportedReasons']=[reason]
            index=core.build_java_index({'neutral/Rules.java':source})
            semantics._build_source_relations(result,semantics._tokens(source),pipeline_java.semantic_type_context(facts,index),semantics.MAX_SOURCE_RELATIONS)
            relation=self.relations(result,'helper_return_source_summary')[0]
            self.assertEqual(relation['resolution'],expected);self.assertIn(reason,relation['limitations'])
            self.assertNotIn('privacy_denied',relation['limitations'])

    def test_outside_scope_and_argument_type_are_explicit_partial(self):
        for source in ['class Rules{int g(int n){return Missing.helper(n);}}',
                       'class Rules{Object g(Object n){return helper(n);}private int helper(int x){return x;}}',
                       'class Rules{int g(int n){return helper(n);}private int helper(int x){return true;}}',
                       'record Box(int count){}class Rules{Box g(long n){return helper(n);}private Box helper(long x){return new Box(x);}}']:
            result,_=self.extract(source);relations=self.relations(result,'helper_return_source_summary')
            self.assertTrue(relations);self.assertTrue(all(r['resolution']!='represented'for r in relations))

    def test_constants_method_order_and_argument_order_controls(self):
        for constant in [3,31]:
            for reverse in [False,True]:
                helper='private int helper(int x,int y){return x-y+'+str(constant)+';}'
                caller='int g(int left,int right){return helper(right,left);}'
                result,_=self.extract('class Rules{'+(helper+caller if reverse else caller+helper)+'}')
                relation=self.relations(result,'helper_return_source_summary')[0]
                self.assertEqual(relation['resolution'],'represented')
                parameters=relation['details']['parameterArguments'];self.assertEqual([r['parameterIndex']for r in parameters],[0,1])
                self.assertTrue(parameters[0]['argumentRef']['jsonPointer'].endswith('/arguments/0'))
                self.assertTrue(parameters[1]['argumentRef']['jsonPointer'].endswith('/arguments/1'))
                self.assertNotIn('"value":',json.dumps(relation))

    def test_metamorphic_names_constants_package_crlf_order(self):
        for package in ['', 'package neutral.variant;']:
            for ending in ['\n','\r\n']:
                source=package+ending+'record Carrier(int tally){}'+ending+'class Sketch{Carrier make(int input){return assemble(input);}private Carrier assemble(int number){return new Carrier(number);}}'
                result,_=self.extract(source);self.assertTrue(any(r['resolution']=='represented'for r in self.relations(result,'helper_return_source_summary')))
                self.assertTrue(all(f['unit']['status']=='UNKNOWN'and f['runtimeStatus']=='not_observed'and not f['businessMeaningVerified']for f in result['fragments']))

    def test_v2_complete_method_and_inventory_closure_matrix(self):
        source='class Rules{int g(int n){return h(n);}private int h(int x){return x+1;}private int spare(long x){return 1;}}'
        probes=['return_type','access','modifiers','params','throws','body','method_name','method_owner','new_overload','site_target','site_resolution','optional_added','optional_removed','inventory_added','inventory_removed']
        for probe in probes:
            result,facts=self.extract(source);target=self.relations(result,'helper_return_source_summary')[0]
            method=next(r for r in facts['records']if r.get('type')=='Method'and r.get('name')=='h')
            site=next(r for r in facts['records']if r.get('kind')=='callsite'and r['id']in target['sourceEvidenceIds'])
            self.assertEqual(target['resolution'],'represented',probe)
            self.assertTrue(any(r['recordId']==method['id']and r['jsonPointer']==''for r in target['sourceEvidenceRefs']))
            if probe=='return_type':method['returnTypeReference']['resolvedType']='boolean'
            elif probe=='access':method['callbackDeclaration']['access']='public'
            elif probe=='modifiers':method['sourceMethodModifiers']=['abstract']
            elif probe=='params':method['parameterTypeReferences'][0]['resolvedType']='long'
            elif probe=='throws':method['throwsTypes']=['Error']
            elif probe=='body':method['bodyRange']['charEnd']-=1
            elif probe=='method_name':method['name']='other'
            elif probe=='method_owner':method['owner']='Other'
            elif probe=='new_overload':next(r for r in facts['records']if r.get('name')=='spare')['name']='h'
            elif probe=='site_target':site['target']='missing'
            elif probe=='site_resolution':site['resolution']='unresolved'
            elif probe=='optional_added':method['newOptionalInput']=True
            elif probe=='optional_removed':method.pop('annotations')
            elif probe=='inventory_added':facts['records'].append(dict(method,id='neutral-added-provider'))
            elif probe=='inventory_removed':facts['records']=[r for r in facts['records']if r.get('name')!='spare']
            self.finalize(result,facts)
            self.assertNotEqual(target['resolution'],'represented',probe);self.assertEqual(target['validation']['status'],'invalidated',probe)
        result,facts=self.extract(source);before=copy.deepcopy(self.relations(result))
        self.finalize(result,facts);self.assertEqual(before,self.relations(result))

    def test_v2_owner_and_provider_admissibility_causes_remain_distinct(self):
        cases=[('unsupported_expression_syntax','unsupported','parser_unsupported'),('sensitive_value_redacted','denied','privacy_withheld'),('literal_review_revoked','denied','permission_revoked'),('dependency','unknown','dependency_invalidated'),('pending','unknown','dependency_pending'),('missing_status','unknown','representation_unavailable')]
        for who in ['owner','provider']:
            for reason,expected,cause in cases:
                result,facts=self.extract('class Rules{int g(boolean good){if(good)return 1;return 0;}}')
                owner=next(r for r in result['fragments']if self.relations({'fragments':[r]},'lexical_return_guard'))
                target=owner['sourceRelations']['relations'][0]
                provider=next(r for r in result['fragments']if r['id']in target['guardEvidenceIds'])
                changed=owner if who=='owner'else provider
                if reason in ['dependency','pending']:changed['dependencyClosure']={'status':'invalidated'if reason=='dependency'else'pending_snapshot_finalization'}
                elif reason=='missing_status':changed.pop('representationStatus')
                else:changed.update(representationStatus='unsupported',unsupportedReasons=[reason])
                # Direct API tests the relation's own admissibility check; the
                # outer validator may legitimately retire dependency metadata.
                self.finalize(result,facts,direct=True)
                self.assertEqual(target['resolution'],expected,(who,reason));self.assertEqual(target['validation']['cause'],cause)
                self.assertEqual(target['validation']['subject'],who)
                self.assertEqual(result['coverage']['sourceRelations']['detected'],result['coverage']['sourceRelations']['recorded']+result['coverage']['sourceRelations']['omitted'])

    def test_v2_all_relation_family_input_and_optional_absence_withdrawal(self):
        cases=[('constructor_parameter_component_transfer','record Box(int n){}class Rules{Box g(int n){return new Box(n);}}'),
               ('helper_return_source_summary','class Rules{int g(int n){return h(n);}private int h(int x){return x+1;}}'),
               ('straight_line_reaching_definition','class Rules{int g(int n){int local=n;return local;}}'),
               ('lexical_return_guard','class Rules{int g(boolean good){if(good)return 1;return 0;}}'),
               ('enum_constant_declaration_position','enum Tag{A,B}'),
               ('array_element_source_position','class Rules{int[] values={3,4};}'),
               ('enum_array_initial_source_association','enum Tag{A,B}class Rules{int[] values={3,4};int g(Tag tag){int i=tag.ordinal();return values[i];}}'),
               ('callback_body_reference','class Rules{void g(){Runnable job=()->doWork();}}')]
        for kind,source in cases:
            for change in ['optional_field','category','range','row_removed','row_added']:
                result,facts=self.extract(source);targets=self.relations(result,kind);self.assertTrue(targets,kind);target=targets[0]
                original=result['coverage']['sourceRelations']['detected'];row=result['fragments'][0]
                if change=='optional_field':row['newSourceDecisionInput']={'present':True}
                elif change=='category':row['category']='changed'
                elif change=='range':row['sourceRange']['charEnd']-=1
                elif change=='row_removed':result['fragments']=[r for r in result['fragments']if r is not row]
                else:
                    added=dict(row,id='neutral-added-fragment');added.pop('sourceRelations',None);result['fragments'].append(added)
                # Keep the target reachable when testing removed other input.
                if not any(target is r for r in self.relations(result)):continue
                self.finalize(result,facts,direct=True)
                self.assertEqual(target['validation']['status'],'invalidated',(kind,change))
                self.assertNotEqual(target['resolution'],'represented',(kind,change))
                self.assertEqual(result['coverage']['sourceRelations']['detected'],original)

    def test_v2_component_root_and_record_body_shape_are_closed(self):
        sources=['record Box(int n){}class Rules{Box g(int n){return new Box(n);}}',
                 'record Box(int n){}class Rules{Box g(int n){return h(n);}private Box h(int x){return new Box(x);}}']
        for source in sources:
            for probe in ['remove','coverage','body_shape']:
                result,facts=self.extract(source);kind='helper_return_source_summary'if'h(n)'in source else'constructor_parameter_component_transfer'
                target=self.relations(result,kind)[0];record=next(r for r in facts['records']if r.get('type')=='Record')
                self.assertEqual(target['resolution'],'represented')
                if probe=='remove':facts['records'].remove(record)
                elif probe=='coverage':record['recordComponentCoverage']['declarationsComplete']=False
                else:record['sourceBodyShape']['shape']='nonempty'
                self.finalize(result,facts,direct=True)
                self.assertEqual(target['validation']['status'],'invalidated');self.assertNotEqual(target['resolution'],'represented')

    def test_v2_missing_current_inventory_is_explicit_fail_closed(self):
        result,facts=self.extract('class Rules{int g(int n){return h(n);}private int h(int x){return x;}}')
        target=self.relations(result,'helper_return_source_summary')[0]
        semantics.finalize_source_relations(result,lookup=lambda rid,path=None:next((r for r in facts['records']if r['id']==rid),None))
        self.assertEqual(target['resolution'],'unknown');self.assertEqual(target['validation']['reason'],'source_relation_current_inventory_unavailable')
        self.assertRaises(ValueError,semantics._source_pointer,result['fragments'][0],'')

    def test_v2_typed_name_presence_and_transport_projection(self):
        for present,name in [(False,None),(True,None),(True,''),(True,'return')]:
            result,facts=self.extract('class Rules{int g(){return 1;}}');row=result['fragments'][0]
            row.pop('sourceRelations',None);row.pop('name',None)
            if present:row['name']=name
            row['sourceRelationInputNamePresent']=present
            original=semantics._source_fragment_input(row)
            transported=dict(row,kind='semantic_fragment',name=row.get('name',row['category']),module='neutral',modulePath='.',language='Java',basis='declared',status='runtime_unknown')
            self.assertEqual(original,semantics._source_fragment_input(transported))
            if present:
                transported.pop('name');self.assertRaises(ValueError,semantics._source_fragment_input,transported)

    def test_v2_scalar_inventory_worstcase_does_not_omit_small_positive_relation(self):
        sizes=[]
        for count in [3,2000]:
            declarations=''.join('int local'+str(i)+'='+str(i)+';'for i in range(count))
            with patch.object(semantics,'_source_input_closure',wraps=semantics._source_input_closure)as counted:
                result,facts=self.extract('class Rules{int g(){'+declarations+'return h(1);}private int h(int x){return x+1;}}')
            self.assertEqual(counted.call_count,2) # initial build + one finalizer, independent of relation count
            target=self.relations(result,'helper_return_source_summary')[0]
            self.assertEqual(target['resolution'],'represented');self.assertEqual(target['inputClosure']['fragmentCount'],count+2)
            self.assertNotIn('fragmentIds',target['inputClosure']);self.assertEqual(result['coverage']['sourceRelations']['omitted'],0)
            sizes.append(len(semantics._canonical(target)))
            self.finalize(result,facts);self.assertEqual(target['resolution'],'represented')
        self.assertLess(sizes[1]-sizes[0],150)

    def test_v4_unrelated_derived_state_never_withdraws_independent_helper(self):
        source='class Rules{int g(int n){return h(n);}private int h(int x){return x+1;}int unrelated(){return 0;}}'
        result,facts=self.extract(source);target=self.relations(result,'helper_return_source_summary')[0]
        other=next(row for row in result['fragments']if row['id']not in target['sourceEvidenceIds']and row['category']=='return')
        original=copy.deepcopy(target)
        for state in [{'status':'pending_snapshot_finalization','scope':'derived_static_evidence'},None,{'status':'invalidated','scope':'derived_static_evidence','reasons':['source_dependency_unavailable']}]:
            if state is None:other.pop('dependencyClosure',None)
            else:other['dependencyClosure']=state
            self.finalize(result,facts)
            self.assertEqual(target,original)
        owner=next(row for row in result['fragments']if row['id']==target['admissibility']['ownerRecordId'])
        owner['dependencyClosure']={'status':'invalidated','scope':'derived_static_evidence'};self.finalize(result,facts)
        self.assertEqual(target['resolution'],'unknown');self.assertEqual(target['validation']['cause'],'dependency_invalidated')

    def test_v4_first_seal_requires_new_nonserialized_build_context(self):
        source='class Rules{int g(int n){return h(n);}private int h(int x){return x+1;}}'
        context=semantics.SourceRelationBuildContext();result,facts=self.extract(source,defer_external_dependencies=True,source_relation_context=context)
        target=self.relations(result,'helper_return_source_summary')[0]
        self.assertEqual(target['admissibility']['status'],'pending_emitted_ir');self.assertNotIn('validation',target)
        kwargs={'lookup':lambda rid,path=None:next((row for row in facts['records']if row['id']==rid),None),'inventory_lookup':lambda path:facts['records']}
        semantics.finalize_dependencies(result,source_relation_context=context,**kwargs)
        self.assertEqual(target['resolution'],'represented');self.assertEqual(target['admissibility']['status'],'sealed')
        target['admissibility'].update(status='pending_emitted_ir',statesSha256=None)
        target['closureSha256']=semantics._relation_closure(target);target['id']='source-relation:'+target['closureSha256']
        semantics.finalize_dependencies(result,source_relation_context=context,**kwargs)
        self.assertEqual(target['resolution'],'unknown');self.assertEqual(target['validation']['reason'],'source_relation_admissibility_unsealed')
        context=semantics.SourceRelationBuildContext();result,facts=self.extract(source,defer_external_dependencies=True,source_relation_context=context)
        target=self.relations(result,'helper_return_source_summary')[0]
        method=next(row for row in facts['records']if row.get('name')=='h');method['returnTypeReference']['resolvedType']='boolean'
        kwargs={'lookup':lambda rid,path=None:next((row for row in facts['records']if row['id']==rid),None),'inventory_lookup':lambda path:facts['records']}
        semantics.finalize_dependencies(result,source_relation_context=context,**kwargs)
        self.assertNotEqual(target['resolution'],'represented')

if __name__=='__main__':unittest.main()
