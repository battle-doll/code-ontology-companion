"""New neutral policy-only export and rejected-review delivery boundaries."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import companion
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as source
from windows_fixture import protect_private_path


class BusinessProjectionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();protect_private_path(self.root)
        self.profile=companion.privacy_guard.build_profile(['Synthetic Boundary Custodian'],['boundary@neutral.invalid'],key=b'v'*32)
        self.profilepatch=patch.object(companion.privacy_guard,'load_profile',return_value=self.profile);self.profilepatch.start();self.addCleanup(self.profilepatch.stop)
        self.env=patch.dict(os.environ,{acl.PRINCIPAL_ENV:'local-owner','CODE_ONTOLOGY_HOME':str(self.root/'registry')});self.env.start();self.addCleanup(self.env.stop)
        self.repo=self.root/'neutral-source';self.repo.mkdir(mode=0o700)
        (self.repo/'capacity.py').write_text('def admit(enabled: bool) -> bool:\n    return enabled\n',encoding='utf-8')
        (self.repo/'capacity.py').chmod(0o600)
        self.workspace=self.root/'knowledge';self.sid=source.initialize(self.repo,self.workspace,prepare_workspace=acl.initialize_access)['snapshotId']
        access.register(str(self.workspace));self.wid=access.config(self.workspace)['workspaceId']
        self.store,self.query,self.exporter=access._business();self.sem=self.store._semantics
        self.meta=self.store.build(self.workspace,self.sid,processing_contract=True)
        with self.reader() as reader:self.base=next(reader.iter_records(kind='business_policy'))
        shutil.rmtree(self.repo)  # The subprocess cannot read the original source.

    def reader(self):return self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'])
    def item(self,key='capacity'):
        return dict(namespace='review',domain='allocation',kind='business_policy',conceptKey=key,label=key,
            sourceAnchors=self.base['sourceAnchors'],facets={**{k:self.base['facets'][k] for k in ('formula','inputs','outcome')},
            'caps_floors':dict(status='DECLARED',value=dict(type='integer',value=37),basis='Neutral declared limit')})
    def review(self,items):
        self.meta=self.store.review(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'],
            dict(schemaVersion=1,sourcePins={k:self.meta[k] for k in self.sem.PIN_KEYS},concepts=items,processingContract={'schemaVersion':1,'scope':'original_selected_inputs'}))
    def args(self,**extra):return dict(workspace_id=self.wid,snapshot_id=self.sid,knowledge_view='business',business_snapshot_id=self.meta['businessSnapshotId'],business_digest=self.meta['businessDigest'],**extra)
    def call(self,name='explain_policy_result',**extra):return access.dispatch(name,self.args(**extra))['data']
    def export(self,name='projected',**extra):
        return access.export_business_view(self.workspace,self.sid,self.meta,self.root/name,max_output_bytes=1024**2,
            profile=self.profile,profile_roots=[self.workspace],projection='business_only',**extra)
    def grant(self,actions):acl.update_access(self.workspace,'reader',actions,[self.sid])
    def mcp(self,arguments):
        path=self.root/'profile.json';path.write_text(json.dumps(self.profile),encoding='utf-8');path.chmod(0o600)
        env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
        env.update({acl.PRINCIPAL_ENV:'reader',companion.privacy_guard.PROFILE_ENV:str(path)})
        cache=Path(tempfile.mkdtemp(prefix='mcp-pycache-',dir=self.root))
        request={'jsonrpc':'2.0','id':9,'method':'tools/call','params':{'name':'explain_policy_result','arguments':arguments}}
        completed=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),str(Path(__file__).resolve().parents[1]/'mcp/server.py')],
            input=json.dumps(request)+'\n',text=True,capture_output=True,env=env,timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)
        response=json.loads(completed.stdout);self.assertIn('result',response,completed.stdout)
        return response['result']

    def test_minimum_grants_projection_and_private_binding(self):
        self.review([self.item()]);self.grant(['read_policy','export_html'])
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
            result=self.export()
            with self.assertRaises(acl.AccessDenied):access.read_business_export_binding(self.workspace,self.sid,result['exportId'])
            with self.assertRaises(self.exporter.BusinessExportError):
                access.export_business_view(self.workspace,self.sid,self.meta,self.root/'full',max_output_bytes=1024**2,profile=self.profile,profile_roots=[self.workspace])
        artifact=self.root/'projected';text='\n'.join(p.read_text(encoding='utf-8') for p in artifact.rglob('*') if p.is_file())+json.dumps(result)
        for key in self.query.PINS:self.assertNotIn(self.meta[key],text)
        for forbidden in ('sourceAnchors','sourceSha256','contentDigest','approvalReceiptId','Neutral declared limit','capacity.py','sourceRuleId','processingScopeId'):
            self.assertNotIn(forbidden,text)
        self.assertEqual(result['inputBusinessRecordCount'],result['exportedBusinessRecordCount']+result['withheldSourceCandidateCount'])
        self.assertEqual(result['exportedBusinessRecordCount'],1);self.assertEqual(result['sourceTraceability'],'UNKNOWN')
        for lang in ('en','ko','ja','zh-CN','ru'):
            self.assertIn('lang="'+lang+'"',(artifact/lang/'index.html').read_text(encoding='utf-8'))
        for p in artifact.rglob('*'):
            if os.name!='nt':self.assertEqual(p.stat().st_mode&0o777,0o700 if p.is_dir() else 0o600)
        receipt=access.read_business_export_binding(self.workspace,self.sid,result['exportId'])
        self.assertEqual(receipt['pins'],{k:self.meta[k] for k in self.query.PINS})
        self.assertEqual(receipt['status'],'binding_only_publication_not_attested')
        self.assertEqual(receipt['projectionDigest'],result['projectionDigest'])

    def test_private_binding_read_rechecks_current_profile(self):
        self.review([self.item()]);result=self.export()
        protected=companion.privacy_guard.build_profile([result['projectionDigest']],[],key=b'z'*32)
        with patch.object(companion.privacy_guard,'load_profile',return_value=protected),self.assertRaises(companion.privacy_guard.PrivacyError):
            access.read_business_export_binding(self.workspace,self.sid,result['exportId'])
        alternate=companion.privacy_guard.build_profile(['Third Neutral Custodian'],[],key=b'y'*32)
        changed=[False];original=self.store._read
        def read(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if Path(path).name=='binding.json':changed[0]=True
            return value
        def profile(*args,**kwargs):return alternate if changed[0] else self.profile
        with patch.object(self.store,'_read',read),patch.object(companion.privacy_guard,'load_profile',side_effect=profile),self.assertRaises(companion.CompanionError):
            access.read_business_export_binding(self.workspace,self.sid,result['exportId'])

    def test_binding_profile_changed_during_final_acl_is_not_returned(self):
        self.review([self.item()]);result=self.export()
        profile_path=self.root/'active-profile.json'
        profile_path.write_text(json.dumps(self.profile),encoding='utf-8');protect_private_path(profile_path)
        denied=companion.privacy_guard.build_profile([result['projectionDigest']],[],key=b'x'*32)
        self.profilepatch.stop()
        original_read,original_authorize=self.store._read,acl.authorize
        observed={'bindingRead':False,'swapped':False}
        binding=self.workspace/'business-export-bindings'/result['exportId']/'binding.json'
        before=binding.read_bytes()
        def read(path,*args,**kwargs):
            value=original_read(path,*args,**kwargs)
            if Path(path)==binding:observed['bindingRead']=True
            return value
        def authorize(workspace,action,*args,**kwargs):
            permit=original_authorize(workspace,action,*args,**kwargs)
            if observed['bindingRead'] and action=='export_html' and not observed['swapped']:
                replacement=self.root/'next-profile.json'
                replacement.write_text(json.dumps(denied),encoding='utf-8');protect_private_path(replacement)
                os.replace(replacement,profile_path);observed['swapped']=True
            return permit
        with patch.dict(os.environ,{companion.privacy_guard.PROFILE_ENV:str(profile_path)}),patch.object(self.store,'_read',read),patch.object(acl,'authorize',authorize):
            with self.assertRaises((companion.CompanionError,companion.privacy_guard.PrivacyError)):
                access.read_business_export_binding(self.workspace,self.sid,result['exportId'])
        self.assertTrue(observed['swapped'])
        self.assertEqual(binding.read_bytes(),before)

    def test_denied_profile_change_and_revoked_acl_never_publish(self):
        self.review([self.item()])
        for index,actions in enumerate((['read_policy'],['export_html'])):
            self.grant(actions)
            with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}),self.assertRaises((acl.AccessDenied,self.exporter.BusinessExportError)):
                self.export('denied'+str(index))
            self.assertFalse((self.root/('denied'+str(index))).exists())
        self.grant(['read_policy','export_html'])
        changed=companion.privacy_guard.build_profile(['Another Synthetic Custodian'],[],key=b'w'*32)
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}),patch.object(companion.privacy_guard,'load_profile',return_value=changed),self.assertRaises(self.exporter.BusinessExportError):self.export('profile-changed')
        self.assertFalse((self.root/'profile-changed').exists())
        original=self.exporter._BoundArtifacts.write;counter=[0]
        def revoke(bound,name,raw):
            counter[0]+=1
            if counter[0]==1:
                with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'local-owner'}):self.grant(['read_policy'])
            return original(bound,name,raw)
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}),patch.object(self.exporter._BoundArtifacts,'write',revoke),self.assertRaises((self.exporter.BusinessExportError,self.store.BusinessStoreError)):self.export('revoked')
        self.assertFalse((self.root/'revoked').exists());self.assertFalse(list(self.root.glob('.business-export-*')))

    def rejected_composition(self):
        top=self.item('combined');top['facets']['priority']=dict(status='DECLARED',basis='Neutral combination',value=dict(type='policy_composition',
            members=[dict(policyId=self.sem.concept_id('review','allocation','business_policy',key),priority=19) for key in ('morning','evening')],
            priorityOrder='higher_first',exclusivity='at_most_one',onConflict='UNKNOWN'))
        self.review([self.item('morning'),self.item('evening'),top])
        return self.sem.concept_id('review','allocation','business_policy','combined')

    def test_source_deleted_mcp_delivers_rejection_without_execution_or_evidence(self):
        rid=self.rejected_composition();self.grant(['read_policy'])
        response=self.mcp(self.args(rule_id=rid,context={}))
        self.assertFalse(response['isError'],response);data=response['structuredContent']['data']
        self.assertEqual(data['status'],'business_review_rejected')
        self.assertEqual(set(data['businessDecision']['diagnosticCodes']),{'composition_stacking_missing','composition_priority_tie'})
        self.assertEqual(data['businessDecision']['status'],'UNKNOWN');self.assertIsNone(data['sourceEvaluation'])
        self.assertFalse(data['compositionEvaluated']);self.assertFalse(data['businessDecision']['conflictProven'])
        self.assertNotIn('sourceAnchors',json.dumps(data));self.assertNotIn('policy',data)
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
            coverage=self.call('ontology_pipeline_coverage',coverage_view='processing')
            self.assertEqual(coverage['currentReviewDiagnostics']['selectedInputs'],3)
            self.assertEqual(coverage['currentReviewDiagnostics']['rejectedInputs'],1)
            self.assertEqual(self.call('query_policy_rules')['total'],3)  # source candidate plus two reviewed neighbors
        self.grant([])
        denied=self.mcp(self.args(rule_id=rid,context={}))
        absent=self.mcp(self.args(rule_id='business:'+'0'*64,context={}))
        self.assertTrue(denied['isError']);self.assertEqual(denied,absent)

    def test_review_replacement_and_duplicate_identity_are_not_selected(self):
        rid=self.rejected_composition();old=self.meta['businessDigest']
        self.review([self.item('replacement')]);self.assertNotEqual(old,self.meta['businessDigest'])
        self.assertEqual(self.call(rule_id=rid,context={})['status'],'business_policy_unavailable')
        self.review([self.item('duplicate'),self.item('duplicate')])
        rid=self.sem.concept_id('review','allocation','business_policy','duplicate')
        result=self.call(rule_id=rid,context={})
        self.assertEqual(result['businessDecision']['reason'],'ambiguous_rejected_review_identity')
        self.assertEqual(result['rejectedInputCount'],2)

    def test_rejected_and_valid_duplicate_identity_cannot_select_neighbor(self):
        valid=self.item('overlap');invalid=copy.deepcopy(valid)
        invalid['facets']['priority']={'status':'DECLARED','basis':'Neutral malformed combination',
            'value':{'type':'policy_composition','members':[]}}
        self.review([valid,invalid])
        rid=self.sem.concept_id('review','allocation','business_policy','overlap')
        result=self.call(rule_id=rid,context={})
        self.assertEqual(result['businessDecision']['reason'],'ambiguous_rejected_review_identity')
        self.assertEqual(result['rejectedInputCount'],2)
        self.assertIsNone(result['businessDecision']['value']);self.assertNotIn('policy',result)
        self.assertEqual(self.meta['coverage']['reviewAccepted'],0)

    def test_no_protected_value_or_forged_declassification_bypasses_review(self):
        before=self.meta['businessDigest'];item=self.item()
        item['facets']['caps_floors']=dict(status='DECLARED',value=dict(type='text',value='Synthetic Boundary Custodian'),basis='Approved business text')
        with self.assertRaises(companion.privacy_guard.PrivacyError):self.review([item])
        self.assertEqual(self.store.status(self.workspace,self.sid)['businessDigest'],before)
        item=self.item();item['declassified']=True
        self.review([item]);self.assertEqual(self.meta['coverage']['reviewAccepted'],0)

    def test_cli_explicit_mode_with_source_deleted(self):
        self.review([self.item()]);self.grant(['read_policy','export_html'])
        path=self.root/'profile.json';path.write_text(json.dumps(self.profile),encoding='utf-8');path.chmod(0o600)
        env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')};env.update({acl.PRINCIPAL_ENV:'reader',companion.privacy_guard.PROFILE_ENV:str(path)})
        command=Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts/companion.py'
        cache=Path(tempfile.mkdtemp(prefix='cli-pycache-',dir=self.root))
        result=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),str(command),'business-html','--workspace',str(self.workspace),'--snapshot',self.sid,
            '--business-snapshot',self.meta['businessSnapshotId'],'--business-digest',self.meta['businessDigest'],'--output',str(self.root/'cli-output')],capture_output=True,text=True,env=env,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout);self.assertEqual(data['projection'],'business_only')
        self.assertNotIn(self.meta['businessDigest'],result.stdout)

    def test_approved_unclassified_text_and_nested_source_mapping_projection(self):
        item=self.item();item['facets']['units']=dict(status='DECLARED',value=dict(type='text',value='admit'),basis='Explicit business vocabulary')
        self.review([item]);self.grant(['read_policy','export_html'])
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):result=self.export()
        rows=json.loads((self.root/'projected/records.json').read_text(encoding='utf-8'))
        self.assertEqual(rows[0]['facets']['units']['value']['value'],'admit')
        with self.reader() as reader:original=next(r for r in reader.iter_records() if r.get('reviewedMeaning'))
        nested=copy.deepcopy(original);nested['facets']['inputs']={'status':'DECLARED','value':{'type':'sequence','items':[
            {'type':'formula_mapping','sourceRuleId':'p:'+'a'*64,'sourcePins':{k:self.meta[k] for k in self.sem.PIN_KEYS}}]}}
        projected,_=self.exporter._business_only_record(nested,{nested['id']})
        self.assertNotIn('sourceRuleId',json.dumps(projected));self.assertIn('projectionLoss',projected['facets']['inputs'])
        malformed=copy.deepcopy(original);malformed['name']={'sourceAnchors':original['sourceAnchors']}
        with self.assertRaises(self.exporter.BusinessExportError):self.exporter._business_only_record(malformed,{original['id']})
        nested['facets']['inputs']['value']={'type':'future_source_payload','path':'neutral/hidden.py'}
        projected,_=self.exporter._business_only_record(nested,{nested['id']})
        self.assertNotIn('neutral/hidden.py',json.dumps(projected))

    def test_profile_change_at_publication_and_bounds_leave_no_artifact(self):
        self.review([self.item()]);self.grant(['read_policy','export_html'])
        original=self.exporter._BoundArtifacts.validate;changed=[False]
        alternate=companion.privacy_guard.build_profile(['Second Neutral Custodian'],[],key=b'r'*32)
        def validate(bound,files):
            original(bound,files)
            if bound.output==self.root/'late-profile':changed[0]=True
        def profile(*args,**kwargs):return alternate if changed[0] else self.profile
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}),patch.object(self.exporter._BoundArtifacts,'validate',validate),patch.object(companion.privacy_guard,'load_profile',side_effect=profile),self.assertRaises(self.exporter.BusinessExportError):self.export('late-profile')
        self.assertFalse((self.root/'late-profile').exists())
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}),self.assertRaises(self.exporter.BusinessExportError):
            access.export_business_view(self.workspace,self.sid,self.meta,self.root/'tiny',max_output_bytes=1,profile=self.profile,profile_roots=[self.workspace],projection='business_only')
        self.assertFalse((self.root/'tiny').exists())

    def test_diagnostic_counts_and_source_anchor_revalidation(self):
        self.rejected_composition()
        with self.reader() as reader:
            diagnostic=copy.deepcopy(reader.metadata['currentReviewDiagnostics'])
            self.assertEqual(sum(diagnostic['outcomeCounts'].values()),3)
            self.assertEqual(diagnostic['outcomeCounts']['rejected'],1)
            # C36 admits the uniquely completed shape, but these public test
            # neighbors still have no source-bound formula_mapping.
            self.assertEqual(diagnostic['entries'][0]['rejectionReason'],'composition_member_mapping_required')
            diagnostic['entries'][0]['sourceAnchors'][0]['sourceSha256']='0'*64
            with self.assertRaises(self.sem.BusinessError):self.sem.validate_review_diagnostics(diagnostic,reader.source_reader,{k:self.meta[k] for k in self.sem.PIN_KEYS},reader.metadata['reviewManifestDigest'])

    def test_reader_exit_failure_precedes_publication(self):
        self.review([self.item()]);self.grant(['read_policy','export_html'])
        original=self.store.BusinessReader.__exit__
        def fail(reader,*args):
            original(reader,*args)
            raise self.store.BusinessStoreError('neutral_reader_exit_failure')
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}),patch.object(self.store.BusinessReader,'__exit__',fail),self.assertRaises(self.exporter.BusinessExportError):self.export('exit-failure')
        self.assertFalse((self.root/'exit-failure').exists());self.assertFalse(list(self.root.glob('.business-export-*')))


if __name__=='__main__':unittest.main()
