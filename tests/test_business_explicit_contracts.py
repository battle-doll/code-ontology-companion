"""Finite source-free optional contracts; no target/oracle/profile fixture."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_semantics as sem
import business_query as query
import privacy_guard
from test_business_semantics import Reader,PINS,RULE
import test_business_store as baseline_store


def declared(value):return {'status':'DECLARED','value':value,'basis':'explicit reviewed neutral contract'}
def na():return {'status':'NOT_APPLICABLE','reason':'explicit reviewed not applicable'}
def ptype(kind='int',**changes):
    value=dict(type='property_type',scalarType=kind,precision='UNKNOWN',scale='UNKNOWN',quantityKind='scalar',unit='UNKNOWN',currency='UNKNOWN',rounding='UNKNOWN',clock='UNKNOWN',timezone='UNKNOWN',nullable=False);value.update(changes);return value

def identity(key,kind='business_policy'):return sem.concept_id('review','catalog',kind,key)

def fixture():
    rules=[]
    for index in (1,2):
        rules.append({**RULE,'id':'p:'+str(index)*64,'parameters':[{'name':'amount','type':'int'}],
            'returnType':'int','program':{'op':'return','value':{'op':'input','name':'amount','type':'int'}}})
    reader=Reader(rules)
    anchor=sem.make_anchor(rules[0],source_pins=PINS)
    def item(key,kind='business_policy'):
        return dict(namespace='review',domain='catalog',kind=kind,conceptKey=key,label=key,sourceAnchors=[anchor],facets={})
    props=[]
    for key in ('input','output'):
        prop=item(key,'business_property');prop['facets']['scalar_type']=declared(ptype());props.append(prop)
    leaves=[]
    for index,rule in enumerate(rules,1):
        row=item('leaf'+str(index));row['sourceAnchors']=[sem.make_anchor(rule,source_pins=PINS)]
        row['facets']={name:na()for name in ('eligibility','exclusions','conflicts','effective_interval','clock_timezone')}
        row['facets']['formula']={'status':'SOURCE_SUPPORTED','value':{'type':'ontology_reference','valueKind':'program'},'sourceAnchors':[sem.make_anchor(rule,source_pins=PINS,inline_pointer='/program')]}
        row['facets']['outcome']={'status':'SOURCE_SUPPORTED','value':{'type':'scalar_type','name':'int'},'sourceAnchors':[sem.make_anchor(rule,source_pins=PINS,inline_pointer='/returnType')]}
        row['facets']['inputs']=declared(dict(type='formula_mapping',sourcePins=copy.deepcopy(PINS),sourceRuleId=rule['id'],sourceRuleDigest=sem.digest(rule),numericContextDigest=sem.digest(rule.get('numericContext')),inputs=[dict(parameter='amount',propertyId=identity('input','business_property'))],outputPropertyId=identity('output','business_property')))
        leaves.append(row)
    top=item('composition');top['facets']={name:na()for name in ('eligibility','exclusions','conflicts','effective_interval','clock_timezone')}
    top['facets']['priority']=declared(dict(type='policy_composition',members=[dict(policyId=identity('leaf1'),priority=2),dict(policyId=identity('leaf2'),priority=1)],priorityOrder='higher_first',exclusivity='all',stacking='sum',onConflict='UNKNOWN'))
    values=[{identity('input','business_property'):{'type':'integer','value':i}}for i in (1,3)]
    top['facets']['missing_context']=declared(dict(type='finite_contexts',scope='explicit_reviewed_supplied_set',contexts=[dict(contextId='case'+str(i),values=value,asOf=None,clock='business',timezone='UTC')for i,value in enumerate(values)]))
    manifest=dict(schemaVersion=1,sourcePins=PINS,concepts=props+leaves+[top])
    return reader,manifest,values

class ExplicitContractTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch.object(privacy_guard,'load_profile',return_value=privacy_guard.build_profile([],[],key=b'e'*32));self.patch.start();sem.configure(privacy_guard=privacy_guard)
        self.reader,self.manifest,self.cases=fixture()
    def tearDown(self):self.patch.stop()
    def validated(self,manifest=None):return sem.validate_review(manifest or self.manifest,self.reader,source_pins=PINS,candidates=[])
    def decide(self,result=None,**kw):
        result=result or self.validated();records={r['id']:r for r in result['records']}
        def evaluate(rid,context,as_of):return {'status':'evaluated','value':{'type':'int','value':context['amount']+int(rid[-1])}}
        return sem.optional_decision(records[identity('composition')],get_record=records.get,source_reader=self.reader,source_pins=PINS,evaluate_source=evaluate,**kw)
    def test_finite_exact_mapping_composition_has_scoped_best_only(self):
        result=self.validated();self.assertEqual(len(result['records']),5,result['omissions'])
        decision=self.decide(cases=self.cases)
        self.assertEqual(decision['status'],'finite_set_evaluated');self.assertEqual(decision['finiteBest']['value'],{'type':'integer','value':9})
        self.assertFalse(decision['finiteBest']['globalMaximum']);self.assertFalse(decision['finiteBest']['optimum']);self.assertEqual(decision['selectedPolicyDenominator'],3)
        self.assertEqual(decision['selectedContextDenominator'],2);self.assertEqual(decision['evaluatedContextNumerator'],2);self.assertEqual(decision['globalOptimum'],'UNKNOWN')
    def test_no_names_infer_mapping_and_every_source_role_is_bound(self):
        mutations=[lambda m:m['concepts'][2]['facets']['inputs']['value'].update(sourceRuleDigest='f'*64),lambda m:m['concepts'][2]['facets']['inputs']['value']['sourcePins'].update(sourceFingerprint='different'),lambda m:m['concepts'][2]['facets']['inputs']['value']['inputs'][0].update(parameter='same_name_is_not_amount'),lambda m:m['concepts'][2]['facets']['outcome'].update(sourceAnchors=[sem.make_anchor(self.reader.rows[0],source_pins=PINS,inline_pointer='/program')]),lambda m:m['concepts'][2]['facets']['inputs']['value'].update(numericContextDigest='f'*64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                m=copy.deepcopy(self.manifest);mutate(m);result=self.validated(m);self.assertNotIn(identity('leaf1'),{r['id']for r in result['records']});self.assertNotIn(identity('composition'),{r['id']for r in result['records']})
    def test_duplicate_cycle_and_incomplete_closure_are_rejected(self):
        for mode in ('duplicate','cycle','missing'):
            m=copy.deepcopy(self.manifest);members=m['concepts'][-1]['facets']['priority']['value']['members']
            if mode=='duplicate':members[1]['policyId']=members[0]['policyId']
            elif mode=='cycle':members[0]['policyId']=identity('composition')
            else:members[0]['policyId']=identity('absent')
            with self.subTest(mode=mode):self.assertNotIn(identity('composition'),{r['id']for r in self.validated(m)['records']})
    def test_unknown_conflicted_missing_context_never_becomes_best(self):
        for mode in ('missing','conflict','eligibility','revoked','incomparable'):
            result=self.validated();records={r['id']:r for r in result['records']}
            if mode=='missing':decision=self.decide(result,context={})
            else:
                leaf=records[identity('leaf1')]
                if mode=='conflict':leaf['facets']['conflicts']=declared({'type':'boolean','value':True})
                elif mode=='eligibility':leaf['facets']['eligibility']={'status':'UNKNOWN'}
                elif mode=='revoked':leaf['support']='revoked'
                else:records[identity('output','business_property')]['facets']['scalar_type']=declared(ptype('bool'))
                decision=self.decide(result,context=self.cases[0])
            with self.subTest(mode=mode):self.assertEqual(decision['status'],'UNKNOWN');self.assertIsNone(decision['finiteBest'])
        altered=copy.deepcopy(self.cases);altered[0][identity('input','business_property')]['value']=2
        self.assertEqual(self.decide(cases=altered)['reason'],'reviewed_finite_context_set_mismatch')
    def test_priority_exclusivity_and_stacking_contracts(self):
        result=self.validated();top=next(r for r in result['records']if r['id']==identity('composition'));value=top['facets']['priority']['value']
        value.update(exclusivity='first_applicable',stacking='none');self.assertEqual(self.decide(result,context=self.cases[0])['value']['value'],2)
        value['exclusivity']='at_most_one';self.assertEqual(self.decide(result,context=self.cases[0])['reason'],'explicit_exclusivity_conflict')
        value.update(exclusivity='all',stacking='none');self.assertEqual(self.decide(result,context=self.cases[0])['reason'],'stacking_not_declared')
    def test_temporal_explicit_bounds_clock_and_dst_unknown(self):
        row=self.validated()['records'][-1]
        row['facets']['effective_interval']=declared(dict(type='time_interval',start='2026-01-01T00:00:00Z',end='2026-01-02T00:00:00Z',timezone='UTC',clock='business',bounds='left_closed'))
        row['facets']['clock_timezone']=declared(dict(type='clock_basis',clock='business',timezone='UTC'))
        self.assertTrue(sem.temporal_decision(row,'2026-01-01T00:00:00Z','business','UTC')['valid'])
        self.assertFalse(sem.temporal_decision(row,'2026-01-02T00:00:00Z','business','UTC')['valid'])
        for args in [(None,'business','UTC'),('2026-01-01T00:00:00','business','UTC'),('2026-01-01T00:00:00Z','wall','UTC')]:self.assertEqual(sem.temporal_decision(row,*args)['status'],'UNKNOWN')
        for f in ('effective_interval','clock_timezone'):row['facets'][f]['value']['timezone']='America/New_York'
        self.assertEqual(sem.temporal_decision(row,'2026-11-01T01:30:00-04:00','business','America/New_York')['reason'],'timezone_or_dst_unsupported')
    def test_decimal_precision_scale_unit_currency_rounding_closed(self):
        spec=ptype('decimal',precision=8,scale=2,quantityKind='money',currency='USD',rounding='ROUND_HALF_EVEN')
        # fixture helper uses explicit replacements rather than duplicate kwargs.
        self.assertEqual(sem.property_value(spec,dict(type='money',value='12.30',currency='USD'))['value'],'12.30')
        for value in (dict(type='money',value='12.3',currency='USD'),dict(type='money',value='12.30',currency='EUR'),dict(type='decimal',value='12.30'),dict(type='money',value='1234567.89',currency='USD'),dict(type='money',value='12.30',currency='USD',precision=7,scale=2)):
            with self.subTest(value=value),self.assertRaises(sem.BusinessError):sem.property_value(spec,value)
        for tag in sem.CONTRACT_TAGS:
            value=next((copy.deepcopy(f['value'])for c in self.manifest['concepts']for f in c['facets'].values()if f.get('value',{}).get('type')==tag),dict(type='clock_basis',clock='business',timezone='UTC'))
            value['sourceText']='payload';self.assertRaises(sem.BusinessError,sem._typed_value,value)
    def test_normal_relation_property_cycles_remain_valid(self):
        base=self.manifest['concepts'][0];a=copy.deepcopy(base);b=copy.deepcopy(base);a['conceptKey']='a';b['conceptKey']='b';a['facets']={};b['facets']={}
        a['facets']['nullable']=declared(dict(type='concept_reference',conceptId=identity('b','business_property')))
        b['facets']['nullable']=declared(dict(type='concept_reference',conceptId=identity('a','business_property')))
        m={**self.manifest,'concepts':[a,b]};result=self.validated(m);self.assertEqual(len(result['records']),2,result['omissions'])
    def test_decimal_rule_rounding_and_existing_property_facet_disagreement(self):
        for mode in ('rounding','precision','facet'):
            reader,m,cases=fixture()
            for rule in reader.rows:
                rule['parameters'][0]['type']='decimal';rule['returnType']='decimal';rule['program']['value']['type']='decimal';rule['numericContext']={'precision':28,'rounding':'ROUND_HALF_EVEN'}
            for prop in m['concepts'][:2]:
                prop['sourceAnchors']=[sem.make_anchor(reader.rows[0],source_pins=PINS)];prop['facets']['scalar_type']=declared(ptype('decimal',precision=29 if mode=='precision'else 8,scale=2,rounding='ROUND_HALF_UP'if mode=='rounding'else'ROUND_HALF_EVEN'))
            if mode=='facet':m['concepts'][0]['facets']['currency']=declared({'type':'enum','value':'EUR'})
            for index,leaf in enumerate(m['concepts'][2:4]):
                rule=reader.rows[index];leaf['sourceAnchors']=[sem.make_anchor(rule,source_pins=PINS)]
                leaf['facets']['formula']['sourceAnchors']=[sem.make_anchor(rule,source_pins=PINS,inline_pointer='/program')]
                leaf['facets']['outcome'].update(value={'type':'scalar_type','name':'decimal'},sourceAnchors=[sem.make_anchor(rule,source_pins=PINS,inline_pointer='/returnType')])
                leaf['facets']['inputs']['value'].update(sourceRuleDigest=sem.digest(rule),numericContextDigest=sem.digest(rule['numericContext']))
            # Each optional computation is rejected by an independent numeric or existing-facet mismatch.
            result=sem.validate_review(m,reader,source_pins=PINS,candidates=[])
            with self.subTest(mode=mode):
                self.assertNotIn(identity('composition'),{r['id']for r in result['records']})
                expected={'rounding':'mapping_rounding_mismatch','precision':'mapping_precision_unsupported','facet':'property_existing_facet_conflict'}[mode]
                self.assertIn(expected,{e['reason']for e in result['omissions']})

    def test_consumer_rechecks_actual_anchors_and_existing_composition_facets(self):
        result=self.validated();leaf=next(r for r in result['records']if r['id']==identity('leaf1'));leaf['facets']['formula']['sourceAnchors'][0]['targetDigest']='f'*64
        self.assertEqual(self.decide(result,context=self.cases[0])['status'],'UNKNOWN')
        for facet,value in (('exclusivity','at_most_one'),('stackability','min')):
            manifest=copy.deepcopy(self.manifest);manifest['concepts'][-1]['facets'][facet]=declared({'type':'enum','value':value})
            result=self.validated(manifest);self.assertIn('composition_existing_facet_conflict',{entry['reason']for entry in result['omissions']})
        for dimension in ('time','UNKNOWN'):
            self.assertRaises(sem.BusinessError,sem.property_value,ptype('int',quantityKind=dimension),dict(type='integer',value=1))

    def test_no_optional_contract_is_byte_for_byte_legacy(self):
        # Frozen generic no-contract C20 outputs. No historical tree is needed.
        legacy=copy.deepcopy(self.manifest);legacy['concepts']=[legacy['concepts'][0]];legacy['concepts'][0]['facets']={}
        result=self.validated(legacy);row=result['records'][0];query._semantics=sem;query._guard=privacy_guard
        self.assertEqual(sem.digest(result),'e366e50285f55c1a36e24508a2780a4af7fab769aeebda0cda4aefcf8f4af64d')
        self.assertEqual(sem.digest(query.project_record(row,evidence=False)),'f02095791c88291641e379186e272ed5ddb7cff36e5da1672cf200eefb427157')
        self.assertEqual(sem.digest(query.project_record(row,evidence=True)),'381613e89fac1a1c4dd8eac3c85ef2da0b7211f4edacb4e9d4593901ef90e7a0')
    def test_processing_duplicate_conflict_omission_disjoint_denominator(self):
        m=copy.deepcopy(self.manifest);m['concepts']=[m['concepts'][0],copy.deepcopy(m['concepts'][0]),m['concepts'][1]];m['processingContract']={'schemaVersion':1,'scope':'original_selected_inputs'}
        result=sem.validate_review(m,self.reader,source_pins=PINS,candidates=[],max_records=2);recon=result['coverage']['processingReconciliation']
        self.assertEqual(recon['selectedInputs'],3);self.assertEqual(recon['accountedInputs'],3);self.assertEqual(recon['outcomeCounts']['duplicate'],2);self.assertEqual(recon['outcomeCounts']['omitted'],1);self.assertTrue(recon['reconciled']);self.assertEqual(recon['wholeBusinessCompleteness'],'UNKNOWN')

class ProcessingIntegrationTests(unittest.TestCase):
    setUp=baseline_store.BusinessStoreTests.setUp;tearDown=baseline_store.BusinessStoreTests.tearDown
    reader=baseline_store.BusinessStoreTests.reader;manifest=baseline_store.BusinessStoreTests.manifest
    def test_processing_is_paged_and_retains_lifecycle_and_old_unknown(self):
        import business_store as store
        initial=store.build(self.workspace,self.source_snapshot,processing_contract=True,partition_size=1)
        with self.reader(initial)as r:
            entries=list(store._all_processing(r));self.assertEqual(len(entries),initial['coverage']['denominator']);self.assertTrue(r.processing()['summary']['reconciled'])
        manifest=self.manifest(initial);manifest['processingContract']={'schemaVersion':1,'scope':'original_selected_inputs'}
        reviewed=store.review(self.workspace,self.source_snapshot,initial['businessSnapshotId'],initial['businessDigest'],manifest)
        with self.reader(reviewed)as r:
            self.assertTrue(r.processing()['summary']['reconciled']);rid=next(row['id']for row in r.iter_records()if row.get('reviewedMeaning'))
        revoked=store.revoke(self.workspace,self.source_snapshot,reviewed['businessSnapshotId'],reviewed['businessDigest'],[rid])
        with self.reader(revoked)as r:
            rows=list(store._all_processing(r));self.assertEqual(sum(x['outcomeClass']=='revoked'for x in rows),1);self.assertTrue(r.processing()['summary']['reconciled'])
        legacy=store.build(self.workspace,self.source_snapshot,max_records=1)
        with self.reader(legacy)as r:
            self.assertFalse(r.processing()['summary']['reconciled']);self.assertIsNone(r.processing()['total']);self.assertEqual(r.processing()['summary']['priorScope'],'UNKNOWN');self.assertGreater(r.coverage()['summary']['omitted'],0);self.assertEqual(r.metadata['businessCompletion'],'PARTIAL')

class ExplicitConsumerIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_business_query as baseline_query
        baseline_query.BusinessQueryTests.setUp(self)
        import os,companion
        native_profile=self.root/'native-contract-test-profile.json'
        native_profile.write_text(json.dumps(companion.privacy_guard.load_profile()));native_profile.chmod(0o600)
        child_profile=patch.dict(os.environ,{companion.privacy_guard.PROFILE_ENV:str(native_profile)})
        child_profile.start();self.addCleanup(child_profile.stop)
        self.args=lambda **extra:{'workspace_id':self.wid,'snapshot_id':self.sid,'knowledge_view':'business','business_snapshot_id':self.meta['businessSnapshotId'],'business_digest':self.meta['businessDigest'],**extra}
        self.meta=self.store.build(self.workspace,self.sid,processing_contract=True)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'])as reader:
            leaf=next(reader.iter_records(kind='business_policy'));rule=reader.source_reader.get_record(leaf['sourceRecordId'])
        pins={k:self.meta[k]for k in sem.PIN_KEYS};props=[]
        for key in ('input','output'):
            props.append(dict(namespace='review',domain='catalog',kind='business_property',conceptKey=key,label=key,sourceAnchors=leaf['sourceAnchors'],facets={'scalar_type':declared(ptype('bool'))}))
        item=dict(namespace='review',domain='catalog',kind='business_policy',conceptKey='mapped',label='Mapped',sourceAnchors=leaf['sourceAnchors'],facets={k:copy.deepcopy(leaf['facets'][k])for k in ('formula','outcome')})
        item['facets'].update({k:na()for k in ('eligibility','exclusions','conflicts','effective_interval','clock_timezone')})
        item['facets']['inputs']=declared(dict(type='formula_mapping',sourcePins=copy.deepcopy(pins),sourceRuleId=rule['id'],sourceRuleDigest=sem.digest(rule),numericContextDigest=sem.digest(rule.get('numericContext')),inputs=[dict(parameter='active',propertyId=identity('input','business_property'))],outputPropertyId=identity('output','business_property')))
        self.cases=[{identity('input','business_property'):dict(type='boolean',value=value)}for value in (False,True)]
        item['facets']['missing_context']=declared(dict(type='finite_contexts',scope='explicit_reviewed_supplied_set',contexts=[dict(contextId='case'+str(i),values=value,asOf=None,clock='business',timezone='UTC')for i,value in enumerate(self.cases)]))
        self.review_manifest=dict(schemaVersion=1,sourcePins=pins,processingContract=dict(schemaVersion=1,scope='original_selected_inputs'),concepts=props+[item])
        self.meta=self.store.review(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'],self.review_manifest)
    def test_neutral_stdio_after_source_deleted_and_policy_only_projection(self):
        import os,shutil,subprocess
        import companion,pipeline_access as access,pipeline_acl as acl
        shutil.rmtree(self.root/'source-offline')
        profile=self.root/'profile.json';profile.write_text(json.dumps(companion.privacy_guard.load_profile()));profile.chmod(0o600)
        acl.update_access(self.workspace,'reader',['read_policy'],[self.sid])
        args=self.args(rule_id=identity('mapped'),cases=self.cases,objective='maximize_value',policy_view='approved_business')
        request=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='compare_policy_cases',arguments=args))
        env={**os.environ,acl.PRINCIPAL_ENV:'reader',companion.privacy_guard.PROFILE_ENV:str(profile),'PYTHONDONTWRITEBYTECODE':'1'}
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'mcp/server.py')],input=json.dumps(request)+'\n',text=True,capture_output=True,timeout=30,env=env)
        self.assertEqual(result.returncode,0,result.stderr);reply=json.loads(result.stdout)['result'];self.assertFalse(reply.get('isError'),reply)
        data=reply['structuredContent']['data'];decision=data['businessDecision']
        self.assertEqual(decision['status'],'finite_set_evaluated',decision);self.assertEqual(decision['finiteBest']['contextIds'],['case1']);self.assertFalse(decision['finiteBest']['globalMaximum'])
        self.assertTrue(data['evidenceDetailsWithheld']);self.assertNotIn('sourceSha256',json.dumps(data));self.assertNotIn('sourceText',json.dumps(data));self.assertEqual(len(access.tool_definitions()),8)
        page=access.dispatch('ontology_pipeline_coverage',self.args(coverage_view='processing',limit=1))['data'];self.assertTrue(page['truncated']);self.assertTrue(page['summary']['reconciled'])
    def test_json_rdf_roundtrip_schema_and_export_share_closed_values(self):
        import rdflib
        import companion
        exporter=self.exporter;profile=companion.privacy_guard.load_profile()
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'])as reader:
            pins=reader._pins();rows=list(reader.iter_records())
            from contextlib import nullcontext
            exporter.export_business(reader,self.root/'export',pins=pins,profile=profile,authorize=lambda action:dict(decision='allow',revision=1),publication_guard=nullcontext,check_profile=lambda:True,check_snapshot=lambda:True)
        schema=json.loads((Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/references/business-semantics.schema.json').read_text())
        variants={v['properties']['type'].get('const'):v for v in schema['$defs']['value']['oneOf']}
        for tag in sem.CONTRACT_TAGS:
            self.assertFalse(variants[tag]['additionalProperties'])
            # C36 raw composition permits only uniquely forced omitted stacking.
            wanted=set(variants[tag]['properties'])-({'stacking'} if tag=='policy_composition' else set())
            self.assertEqual(set(variants[tag]['required']),wanted)
            if tag=='policy_composition':self.assertEqual(variants[tag]['allOf'][0]['then']['required'],['stacking'])
        for row in rows:
            sem.validate_record_values(row);key=exporter._filename(row['id']);raw=json.loads((self.root/'export/records'/(key+'.json')).read_text());self.assertEqual(row,raw)
            graph=rdflib.Graph();graph.parse(str(self.root/'export/rdf'/(key+'.ttl')),format='turtle')
            literals=[str(value)for _,predicate,value in graph if str(predicate).endswith('canonicalJson')and json.loads(str(value)).get('id')==row['id']];self.assertEqual(len(literals),1);self.assertEqual(json.loads(literals[0]),row)
        self.assertTrue(list((self.root/'export/processing').glob('*.json')))
        bad=copy.deepcopy(next(r for r in rows if any(f.get('value',{}).get('type')in sem.CONTRACT_TAGS for f in r['facets'].values())));facet=next(f for f in bad['facets'].values()if f.get('value',{}).get('type')in sem.CONTRACT_TAGS);facet['value']['sourceText']='payload';bad=sem.seal_record(bad)
        self.assertRaises(sem.BusinessError,sem.validate_record_values,bad)
        self.assertIn('unsupported_consumer_value',json.dumps(self.query.project_record(bad)))
    def test_partitioned_global_ledger_written_once_and_subset_denominators_separate(self):
        import companion
        module=companion.core._load_bundled_helper('pipeline_partitioned');module.configure(store=self.store,exporter=self.exporter,privacy_guard=companion.privacy_guard)
        output=self.root/'partitioned';result=module.export_partitioned(self.workspace,self.sid,output,part_records=1)
        root=json.loads((output/'export-set.json').read_text());self.assertGreater(root['partCount'],1)
        descriptor=root['processingLedger'];ledger=json.loads((output/descriptor['path']).read_text());pages=sorted((output/'processing').glob('page-*.json'))
        rows=[row for path in pages for row in json.loads(path.read_text())['entries']]
        self.assertEqual(len(pages),ledger['pageCount']);self.assertEqual(len(rows),self.meta['coverage']['processingEntryCount']);self.assertEqual(ledger['entryCount'],len(rows));self.assertTrue(ledger['summary']['reconciled'])
        self.assertEqual(len({(r['processingScopeId'],r.get('inputIndex'))for r in rows}),len(rows))
        self.assertEqual(len(list(output.glob('business/part-*/processing-reference.json'))),root['partCount']);self.assertFalse(list(output.glob('business/part-*/processing/*.json')))
        for path in output.glob('business/part-*/metadata.json'):
            meta=json.loads(path.read_text());self.assertEqual(meta['recordCount'],1);self.assertEqual(meta['partition']['globalRecordCount'],self.meta['recordCount'])
            reference=meta['processingLedger'];self.assertEqual(reference['entryCount'],len(rows));self.assertEqual(reference['sha256'],descriptor['sha256']);self.assertEqual((path.parent/reference['path']).resolve(),(output/descriptor['path']).resolve())
        self.assertEqual(root['processedBusinessRecordCount'],self.meta['recordCount']);self.assertEqual(root['rdfScopes']['businessRecordCount'],self.meta['recordCount'])
        source_files=[path for path in (output/'source').rglob('*')if path.is_file()]
        source_bytes=sum(path.stat().st_size for path in source_files)
        self.assertEqual(root['source']['fileCount'],len(source_files))
        self.assertEqual(root['source']['outputBytes'],source_bytes)
        self.assertEqual(result['sourceComponent']['fileCount'],len(source_files))
        self.assertEqual(result['sourceComponent']['outputBytes'],source_bytes)
        processing_files=[path for path in (output/'processing').glob('*.json')]
        self.assertGreater(sum(path.stat().st_size for path in processing_files),0)
        self.assertGreater(result['outputBytes'],source_bytes)

    def test_schema_hash_automatically_rebinds_business_and_stale_review_source(self):
        import pipeline_access as access
        schema=Path(access.__file__).resolve().parent.parent/'references/business-semantics.schema.json';original=Path.read_bytes
        expected={name:__import__('hashlib').sha256((Path(access.__file__).parent/(name+'.py')).read_bytes()).hexdigest()for name in ('business_semantics','business_store','business_query','business_export','pipeline_partitioned')};expected['schema']=__import__('hashlib').sha256(schema.read_bytes()).hexdigest()
        self.assertEqual(self.meta['businessSpecHash'],sem.digest(expected))
        with patch.object(Path,'read_bytes',lambda path:original(path)+(b' 'if path==schema else b'')):
            access._business()
            with self.assertRaisesRegex(self.store.BusinessStoreError,'stale'):
                with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']):pass
        access._business()
        stale=copy.deepcopy(self.review_manifest);stale['sourcePins']['sourceFingerprint']='stale'
        with self.assertRaisesRegex(ValueError,'source_pin_mismatch'):self.store.review(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'],stale)

if __name__=='__main__':unittest.main()
