"""Public, source-offline business view and unchanged source query contract."""
import copy
import json
import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import companion
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as source


class BusinessQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        guard = companion.privacy_guard
        profile = guard.build_profile(['Synthetic Query Private Person'], [], key=b'q'*32)
        self.profile = patch.object(guard, 'load_profile', return_value=profile)
        self.profile.start(); self.addCleanup(self.profile.stop)
        self.env = patch.dict(os.environ, {acl.PRINCIPAL_ENV:'local-owner', 'CODE_ONTOLOGY_HOME':str(self.root/'registry')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.repo = self.root/'source'; self.repo.mkdir()
        (self.repo/'catalog.py').write_text('def eligible(active: bool) -> bool:\n    return active\n')
        self.workspace = self.root/'knowledge'
        self.sid = source.initialize(self.repo, self.workspace, prepare_workspace=acl.initialize_access)['snapshotId']
        access.register(str(self.workspace))
        self.wid = access.config(self.workspace)['workspaceId']
        self.store, self.query, self.exporter = access._business()
        self.meta = self.store.build(self.workspace, self.sid)
        self.repo.rename(self.root/'source-offline')

    def args(self, **extra):
        return {'workspace_id':self.wid, 'snapshot_id':self.sid, 'knowledge_view':'business',
                'business_snapshot_id':self.meta['businessSnapshotId'], 'business_digest':self.meta['businessDigest'], **extra}

    def call(self, name='ontology_pipeline_search', **extra):
        return access.dispatch(name, self.args(**extra))['data']

    def candidate(self):
        return self.call(kind='business_policy')['records'][0]

    def reviewed(self):
        with self.store.open_reader(self.workspace, self.sid, self.meta['businessSnapshotId'], self.meta['businessDigest']) as reader:
            row = next(reader.iter_records(kind='business_policy'))
        self.meta = self.store.review(self.workspace, self.sid, self.meta['businessSnapshotId'], self.meta['businessDigest'], {
            'schemaVersion':1, 'sourcePins':{k:self.meta[k] for k in ('sourceSnapshotId','sourceManifestSha256','sourceFingerprint','analysisSpecId')},
            'concepts':[{'namespace':'review','domain':'catalog','kind':'business_policy','conceptKey':'eligibility',
                         'label':'Eligibility', 'sourceAnchors':row['sourceAnchors'],
                         'facets':{k:row['facets'][k] for k in ('formula','inputs','outcome')}}]})
        return next(r for r in self.call(kind='business_policy')['records'] if r['namespace']=='review')

    def test_coverage_outcome_projection_drops_paths_names_and_unknown_kinds(self):
        record={'sourceRecordId':'p:'+'a'*64,'sourceKind':'semantic_fragment','inputIndex':0,
                'status':'unsupported','reason':'source_span_invalid','path':'src/private.py',
                'name':'Hidden name','privateReviewNote':'Hidden note'}
        projected=self.query._coverage_entry(record)
        self.assertEqual(projected['sourceRecordId'],record['sourceRecordId'])
        self.assertEqual(projected['sourceKind'],'semantic_fragment')
        self.assertFalse(set(projected)&{'path','name','privateReviewNote'})
        record.update(sourceRecordId='src/private.py',sourceKind='private_review_note')
        projected=self.query._coverage_entry(record)
        self.assertIsNone(projected['sourceRecordId']);self.assertEqual(projected['sourceKind'],'UNKNOWN')
        self.assertNotIn('private',str(projected))

    def test_status_discovery_and_page_pins_without_source(self):
        response = access.dispatch('ontology_pipeline_status', {'workspace_id':self.wid,'knowledge_view':'business'})
        self.assertEqual(response['data']['businessDigest'], self.meta['businessDigest'])
        page = self.call(limit=1)
        self.assertTrue(page['truncated']); self.assertEqual(page['nextOffset'],1)
        second = self.call(limit=1, offset=1)
        self.assertEqual(page['queryDigest'],second['queryDigest'])
        self.assertEqual(page['globalCompleteness'],'UNKNOWN')

    def test_source_view_default_is_unchanged(self):
        args={'workspace_id':self.wid,'snapshot_id':self.sid,'kind':'symbol','limit':1}
        self.assertEqual(access.dispatch('ontology_pipeline_search',args), access.dispatch('ontology_pipeline_search',{**args,'knowledge_view':'source'}))
        self.assertEqual(len(access.tool_definitions()),8)

    def test_mixed_selectors_missing_pins_and_module_rejected(self):
        for args in ({**self.args(),'knowledge_view':'source'}, {k:v for k,v in self.args().items() if k!='business_digest'},
                     self.args(module='ignored'), self.args(kind='symbol')):
            with self.assertRaises(companion.CompanionError): access.dispatch('ontology_pipeline_search',args)

    def test_policy_reader_cannot_receive_source_locators_or_approve(self):
        acl.update_access(self.workspace,'reader',['read_policy'],[self.sid])
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
            record=self.candidate()
            self.assertTrue(record['evidenceDetailsWithheld'])
            text=json.dumps(record)
            for field in ('"path"','"sourceSha256"','"sourceRangeOrSpan"','"approvalReceiptId"'):
                self.assertNotIn(field,text)
            self.assertEqual(set(record['sourceAnchors'][0]),{'recordId'})
            with self.assertRaises(acl.AccessDenied): self.store.build(self.workspace,self.sid)

    def test_approved_mapping_does_not_promote_source_authority(self):
        row=self.reviewed()
        result=self.call('explain_policy_result',rule_id=row['id'],context={'active':True},policy_view='approved_business')
        self.assertEqual(result['businessApproval'],'approved')
        self.assertFalse(result['businessPolicyComplete'])
        self.assertEqual(result['sourceEvaluation']['status'],'evaluated')
        self.assertEqual(result['sourceEvaluation']['value']['value'],True)
        self.assertFalse(result['sourceEvaluation']['businessPolicyApproved'])
        self.assertEqual(result['globalOptimum'],'UNKNOWN')
        self.assertIn('units',result['missingBusinessFacets'])

    def test_missing_context_and_finite_comparison_not_business_maximum(self):
        rid=self.candidate()['id']
        result=self.call('explain_policy_result',rule_id=rid,context={})
        self.assertEqual(result['sourceEvaluation']['status'],'needs_context')
        result=self.call('compare_policy_cases',rule_id=rid,cases=[{'active':False},{'active':True}],objective='maximize_value')
        self.assertEqual(result['globalOptimum'],'UNKNOWN')
        self.assertFalse(result['compositionEvaluated'])

    def test_unreviewed_and_stale_business_are_not_approved(self):
        rid=self.candidate()['id']
        result=self.call('explain_policy_result',rule_id=rid,context={'active':True},policy_view='approved_business')
        self.assertEqual(result['status'],'business_approval_required')
        old=self.args(); self.reviewed()
        with self.assertRaises(companion.CompanionError):access.dispatch('ontology_pipeline_search',old)

    def test_unknown_typed_payload_never_crosses_projection(self):
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            raw=next(reader.iter_records(kind='business_policy'))
        raw['facets']['formula']['value']={'type':'ontology_reference','valueKind':'program','sourceText':'hidden_marker'}
        result=self.query.project_record(raw,evidence=False)
        self.assertEqual(result['facets']['formula']['status'],'UNKNOWN')
        self.assertEqual(result['projectionOmissions'],['formula'])
        self.assertNotIn('hidden_marker',json.dumps(result))

    def test_review_basis_and_free_prose_require_evidence_permission(self):
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            raw=next(reader.iter_records(kind='business_policy'))
        raw['facets']['units']={'status':'DECLARED','value':{'type':'enum','value':'boolean'},'basis':'Internal note at src/catalog.py'}
        raw['facets']['conflicts']={'status':'UNKNOWN','reason':'See src/constraints.py'}
        raw['aliases']=[{'target':raw['id'],'relation':'alias','basis':'Review at src/alias.py'}]
        hidden=self.query.project_record(raw,evidence=False)
        self.assertNotIn('src/',json.dumps(hidden))
        self.assertEqual(hidden['facets']['units']['value']['value'],'boolean')
        visible=self.query.project_record(raw,evidence=True)
        self.assertIn('src/catalog.py',json.dumps(visible))

    def test_lowercase_review_prose_is_not_an_internal_reason_code(self):
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            raw=next(reader.iter_records(kind='business_policy'))
        raw['facets']['conflicts']={'status':'UNKNOWN','reason':'private_review_words'}
        self.assertEqual(self.query.project_record(raw,evidence=False)['facets']['conflicts']['reason'],'review_details_require_evidence')
        raw['facets']['conflicts']['reason']='business_meaning_not_reviewed'
        self.assertEqual(self.query.project_record(raw,evidence=False)['facets']['conflicts']['reason'],'business_meaning_not_reviewed')

    def test_review_commit_serializes_supported_acl_revocation(self):
        original=source._atomic
        observed=[]
        def atomic(path,value):
            if Path(path).name=='business-state.json':
                try:
                    acl.update_access(self.workspace,'local-owner',sorted(acl.ACTIONS-{'manage_knowledge'}),['*'])
                except companion.CompanionError:
                    observed.append('concurrent_acl_write_blocked')
                else:
                    observed.append('race_allowed')
            return original(path,value)
        with patch.object(source,'_atomic',side_effect=atomic):
            row=self.reviewed()
        self.assertEqual(observed,['concurrent_acl_write_blocked'])
        self.assertEqual(row['businessApproval'],'approved')
        acl.update_access(self.workspace,'local-owner',sorted(acl.ACTIONS-{'manage_knowledge'}),['*'])
        with self.assertRaises(acl.AccessDenied):self.reviewed()

    def test_read_only_tools_reject_approval_arguments(self):
        for key in ('actor','approved','decision'):
            with self.assertRaises(companion.CompanionError):
                access.dispatch('query_policy_rules',self.args(**{key:'untrusted'}))

    def test_coverage_is_separate_from_business_completeness(self):
        result=self.call('ontology_pipeline_coverage',limit=1)
        self.assertEqual(result['summary']['globalCompleteness'],'UNKNOWN')
        self.assertIn('denominator',result['summary'])
        self.assertEqual(result['businessCompletion'],'PARTIAL')

    def test_human_html_keeps_source_map_and_links_all_five_business_views(self):
        import pipeline_html
        profile=companion.privacy_guard.load_profile()
        output=self.root/'human'
        with patch.object(pipeline_html.privacy_guard,'load_profile',return_value=profile):
            result=pipeline_html.render_pipeline(self.workspace,self.sid,output)
        self.assertEqual(result['business']['recordCount'],self.meta['recordCount'])
        for language in ('ko','en','ja','zh-CN','ru'):
            source_html=(output/language/'index.html').read_text()
            self.assertIn('../business/'+language+'/index.html',source_html)
            self.assertIn('ontology-data',source_html)
            business_html=(output/'business'/language/'index.html').read_text()
            self.assertIn('../../'+language+'/index.html',business_html)
        self.assertEqual(result['outputBytes'],sum(p.stat().st_size for p in output.rglob('*') if p.is_file()))

    def test_human_combined_budget_failure_never_promotes_partial_tree(self):
        import pipeline_html
        profile=companion.privacy_guard.load_profile()
        output=self.root/'too-small'
        with patch.object(pipeline_html.privacy_guard,'load_profile',return_value=profile):
            with self.assertRaises(ValueError):
                pipeline_html.render_pipeline(self.workspace,self.sid,output,max_output_bytes=1024)
        self.assertFalse(output.exists())

    def test_portable_bundle_includes_exact_business_records_without_acl(self):
        import pipeline_export
        output=self.root/'portable'
        result=pipeline_export.export_bundle(self.workspace,self.sid,output)
        manifest=json.loads((output/'bundle.json').read_text())
        self.assertEqual(result['status'],'exported')
        self.assertEqual(manifest['business']['pins']['businessDigest'],self.meta['businessDigest'])
        copies=[json.loads(p.read_text()) for p in (output/'business'/'records').glob('*.json')]
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            expected=list(reader.iter_records())
        self.assertEqual(sorted(copies,key=lambda r:r['id']),sorted(expected,key=lambda r:r['id']))
        self.assertFalse((output/'access.json').exists())
        self.assertFalse((output/'business-state.json').exists())

    def test_actual_stdio_source_offline_business_projection(self):
        profile=self.root/'profile.json'
        profile.write_text(json.dumps(companion.privacy_guard.load_profile()))
        profile.chmod(0o600)
        acl.update_access(self.workspace,'reader',['read_policy'],[self.sid])
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':self.args(kind='business_policy')}}
        env={**os.environ,acl.PRINCIPAL_ENV:'reader',companion.privacy_guard.PROFILE_ENV:str(profile)}
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'mcp/server.py')],
            input=json.dumps(request)+'\n',text=True,capture_output=True,timeout=30,env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        reply=json.loads(result.stdout)['result']
        self.assertFalse(reply.get('isError'),reply)
        data=reply['structuredContent']['data']
        self.assertEqual(data['businessDigest'],self.meta['businessDigest'])
        self.assertTrue(data['evidenceDetailsWithheld'])
        self.assertNotIn('sourceSha256',json.dumps(data))

    def test_cli_analyze_builds_candidates_without_automatic_approval(self):
        profile=self.root/'profile.json'
        profile.write_text(json.dumps(companion.privacy_guard.load_profile()));profile.chmod(0o600)
        repo=self.root/'neutral-cli';repo.mkdir();(repo/'rules.py').write_text('def ready(ok: bool) -> bool:\n    return ok\n')
        command=Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts/companion.py'
        result=subprocess.run([sys.executable,str(command),'analyze','--repo',str(repo),'--workspace',str(self.root/'cli-knowledge'),
            '--authorized','--no-html'],text=True,capture_output=True,timeout=30,
            env={**os.environ,companion.privacy_guard.PROFILE_ENV:str(profile)})
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertEqual(data['business']['status'],'ready')
        self.assertEqual(data['business']['businessCompletion'],'PARTIAL')


if __name__=='__main__': unittest.main()
