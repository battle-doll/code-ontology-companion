"""Neutral portable policy projection: exact data, bounded transport and denial.

The transport fixture injects the actual MCP record/metadata projectors. Store
integration below exercises the verified query module's closed producer contract.
No actual source, profile, external fixture or runtime deployment is used.
"""
from contextlib import contextmanager
import copy
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, unquote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_export as exporter
import business_query as query
import business_semantics as semantics
import privacy_guard as guard
import pipeline_policy as policy
from windows_fixture import protect_private_path

PINS={key:('ps-neutral' if key=='sourceSnapshotId' else 'bs-neutral' if key=='businessSnapshotId' else 'a'*64) for key in exporter.PIN_KEYS}


class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.links=[];self.scripts=0;self.rows=[];self.current=None;self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':self.scripts+=1
        self.links.extend(attrs[key] for key in ('href','src') if key in attrs)
        if tag=='pre' and attrs.get('class')=='record-json':self.current=''
    def handle_data(self,data):
        if self.current is not None:self.current+=data
    def handle_endtag(self,tag):
        if tag=='pre' and self.current is not None:self.rows.append(json.loads(self.current));self.current=None


def record(index=0,kind='business_policy'):
    row=semantics._base('neutral','allocation',kind,'concept-'+str(index),'Same-looking label',
        [dict(recordId='p:'+'b'*64,inlinePointer='/program',path='neutral.py',sourceSha256='c'*64)])
    row['facets'][next(iter(row['facets']))]={'status':'UNKNOWN','reason':'business_meaning_not_reviewed'}
    return semantics.seal_record(row)


class Reader:
    def __init__(self,rows):
        self.rows=rows;self.metadata={**PINS,'schemaVersion':1,'status':'ready','recordCount':len(rows),
            'sourceAccess':'not_read','businessCompletion':'PARTIAL',
            'coverage':{'state':'PARTIAL','scope':'selected_source_snapshot_records','denominator':len(rows),
                        'numerator':0,'unknownDenominator':False,'globalCompleteness':'UNKNOWN'}}
    def iter_records(self,*,page_size):yield from copy.deepcopy(self.rows)


class AuthorizedPolicyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();protect_private_path(self.root)
        self.profile=guard.build_profile(['Synthetic Portable Custodian'],[],key=b'n'*32,values=['Unrelated neutral veto'])
        self.profile_patch=patch.object(guard,'load_profile',return_value=self.profile);self.profile_mock=self.profile_patch.start();self.addCleanup(self.profile_patch.stop)
        semantics.configure(privacy_guard=guard)
        query.configure(store=None,semantics=semantics,pipeline_store=None,policy=policy,acl=None,privacy_guard=guard)
        # Explicit injected boundary fixture for independent transport tests.
        # Production wiring must use query's verified closed producer helpers.
        def validate(value,*,kind):
            if kind=='record':
                allowed=set(record())|{'subject','object','role','cardinality','aliases','reviewedMeaning','approvalReceiptId','canonicalContracts','inputIndex','processingScopeId'}
                if set(value)-allowed:raise ValueError('future_producer_field')
            elif set(value)-set(Reader([]).metadata)-{'currentReviewDiagnostics'}:raise ValueError('future_producer_field')
        def diagnostics(raw):
            return {'selectedInputs':raw['selectedInputs'],'outcomeCounts':copy.deepcopy(raw['outcomeCounts']),
                'rejectedInputs':len(raw['entries']),'offset':0,'returned':len(raw['entries']),
                'entries':[{key:copy.deepcopy(item[key]) for key in ('inputIndex','status','attemptedRecordId','diagnosticCodes','rejectionReason')} for item in raw['entries']]}
        self.api=SimpleNamespace(export_projection_contract=lambda:exporter.POLICY_PROJECTION_CONTRACT,
            validate_policy_projection_input=validate,policy_projection_record=lambda row:query.project_record(row,evidence=False),
            policy_projection_metadata=query._metadata,policy_projection_diagnostics=diagnostics)
        exporter.configure(privacy_guard=guard,canonical=semantics.canonical,validate_record=semantics.validate_record_values,policy_projection=self.api)
        self.reader=Reader([record()]);self.revision=1;self.profile_same=True;self.snapshot=True;self.closed=False;self.actions=[]
    def authorize(self,action):self.actions.append(action);return {'decision':'allow','revision':self.revision}
    @contextmanager
    def lock(self):yield
    def run_export(self,name='portable',**extra):
        params=dict(pins=PINS,profile=self.profile,authorize=self.authorize,publication_guard=self.lock,
            check_profile=lambda:self.profile_same,check_snapshot=lambda:self.snapshot,projection='policy_projection')
        params.update(extra);return exporter.export_business(self.reader,self.root/name,**params)
    def decoded(self,name='portable'):
        manifest=json.loads((self.root/name/'policy-projection.json').read_text(encoding='utf-8'))
        return manifest,[json.loads(line) for chunk in manifest['chunks'] for line in (self.root/name/chunk['path']).read_text(encoding='utf-8').splitlines()]
    def rejects(self,name='portable',**extra):
        with self.assertRaises(exporter.BusinessExportError) as caught:self.run_export(name,**extra)
        self.assertFalse((self.root/name).exists());self.assertFalse(list(self.root.glob('.business-export-*')))
        self.assertEqual(caught.exception.selected,self.reader.metadata['recordCount'])
        self.assertEqual(caught.exception.report['selectedRecords'],self.reader.metadata['recordCount'])
        self.assertEqual(caught.exception.report['processedRecords'],caught.exception.processed)
        return caught.exception

    def test_exact_projector_types_absence_candidates_and_all_eight_pins(self):
        a=record(1,'business_property');b=record(2,'business_property');r=record(3)
        r['namespace']='source';r['conceptKey']='source:p:'+'b'*64
        r['facets']['formula']={'status':'SOURCE_SUPPORTED','value':{'type':'ontology_reference','valueKind':'program'},'sourceAnchors':r['sourceAnchors']}
        r['facets']['inputs']={'status':'SOURCE_SUPPORTED','value':{'type':'parameters','items':[{'name':'amount','valueType':'int'}]}}
        mapping={'type':'formula_mapping','sourceRuleId':'p:'+'b'*64,'sourcePins':{key:PINS[key] for key in semantics.PIN_KEYS},
                 'sourceRuleDigest':'d'*64,'numericContextDigest':'e'*64,'inputs':[{'parameter':'amount','propertyId':a['id']}],'outputPropertyId':b['id']}
        r['facets']['outcome']={'status':'DECLARED','value':{'type':'sequence','items':[mapping]},'basis':'Neutral private rationale'}
        r['aliases']=[{'target':a['id'],'relation':'alias','basis':'Neutral private alias'}]
        self.reader=Reader([a,b,semantics.seal_record(r)])
        result=self.run_export();manifest,rows=self.decoded()
        self.assertEqual(rows,[query.project_record(row,evidence=False) for row in self.reader.rows])
        self.assertEqual(manifest['metadata'],query._metadata(self.reader.metadata))
        for key in PINS:self.assertEqual(manifest['metadata'][key],PINS[key])
        self.assertEqual(rows[-1]['facets']['outcome']['value']['items'][0],{key:mapping[key] for key in ('type','sourceRuleId','inputs','outputPropertyId')})
        self.assertEqual(rows[-1]['sourceAnchors'],[{'recordId':'p:'+'b'*64}]);self.assertNotIn('contentDigest',rows[-1])
        self.assertEqual(result['selectedRecords'],3);self.assertEqual(result['processedRecords'],3)
        self.assertEqual(set(self.actions),{'read_policy','export_html'})
        text='\n'.join(p.read_text(encoding='utf-8') for p in (self.root/'portable').rglob('*') if p.is_file())
        for forbidden in ('Neutral private rationale','Neutral private alias','neutral.py','sourceSha256','sourceRuleDigest'):
            self.assertNotIn(forbidden,text)

    def test_chunks_pages_and_all_locales_reconstruct_identical_data(self):
        self.reader=Reader([record(index) for index in range(205)])
        result=self.run_export();manifest,rows=self.decoded();root=self.root/'portable'
        self.assertEqual([chunk['recordCount'] for chunk in manifest['chunks']],[100,100,5])
        self.assertEqual(result['fileCount'],3+5*3+3)
        self.assertEqual(manifest['htmlPageCountPerLanguage'],3)
        for language in exporter.LANGUAGES:
            actual=[]
            for path in sorted((root/language).glob('*.html')):actual.extend(Page(path.read_text(encoding='utf-8')).rows)
            self.assertEqual(actual,rows)
        for path in root.rglob('*.html'):
            page=Page(path.read_text(encoding='utf-8'));self.assertEqual(page.scripts,0)
            for href in page.links:
                link=urlsplit(href);self.assertFalse(link.scheme or link.netloc)
                if link.path:self.assertTrue((path.parent/unquote(link.path)).is_file(),(path,href))
        for path in root.rglob('*'):
            if os.name!='nt':self.assertEqual(path.stat().st_mode&0o777,0o700 if path.is_dir() else 0o600)

    def test_byte_caps_split_chunks_before_record_cap(self):
        self.reader=Reader([record(index) for index in range(7)])
        one=len(semantics.canonical(query.project_record(self.reader.rows[0],evidence=False)))+1
        with patch.object(exporter,'POLICY_CHUNK_BYTES',one*2+100):self.run_export()
        manifest,rows=self.decoded();self.assertEqual(len(rows),7)
        self.assertGreater(len(manifest['chunks']),1)
        self.assertTrue(all(chunk['recordCount']<=2 for chunk in manifest['chunks']))

    def test_html_escaping_byte_cap_splits_pages_without_changing_record_ids(self):
        rows=[]
        for index in range(9):
            row=record(index);row['facets']['units']={'status':'DECLARED','value':{'type':'sequence','items':[{'type':'text','value':"'"*20} for _ in range(100)]},'basis':'Neutral vocabulary'}
            rows.append(semantics.seal_record(row))
        self.reader=Reader(rows)
        with patch.object(exporter,'MAX_PAGE_BYTES',48*1024),patch.object(exporter,'POLICY_CHUNK_BYTES',48*1024):
            self.run_export();manifest,decoded=self.decoded()
            self.assertGreater(manifest['htmlPageCountPerLanguage'],1)
            self.assertGreater(manifest['htmlPageCountPerLanguage'],len(manifest['chunks']))
            for language in exporter.LANGUAGES:
                actual=[]
                for path in sorted((self.root/'portable'/language).glob('*.html')):
                    self.assertLessEqual(path.stat().st_size,48*1024);actual.extend(Page(path.read_text(encoding='utf-8')).rows)
                self.assertEqual(actual,decoded)
            self.assertEqual(set(manifest['routes']),{row['id'] for row in rows})

    def test_review_denominator_is_preserved_and_private_entries_are_withheld(self):
        counts={'accepted':0,'conflicted':1,'unsupported':0,'rejected':1,'omitted':1,'duplicate':0}
        self.reader.metadata['currentReviewDiagnostics']={'schemaVersion':1,'reviewManifestDigest':'f'*64,'selectedInputs':3,'outcomeCounts':counts,
            'entries':[{'inputIndex':1,'status':'rejected','attemptedRecordId':record()['id'],'diagnosticCodes':['review_schema_rejected'],
                        'rejectionReason':'review_contract_rejected','sourceAnchors':self.reader.rows[0]['sourceAnchors']}]}
        self.run_export();manifest,_=self.decoded();review=manifest['currentReviewDiagnostics']
        self.assertEqual(review['selectedInputs'],3);self.assertEqual(review['outcomeCounts'],counts)
        self.assertNotIn('sourceAnchors',review['entries'][0]);self.assertEqual(review['rejectedInputs'],1)

    def test_empty_selection_and_original_approval_states_remain_unknown(self):
        self.reader=Reader([]);self.run_export();manifest,rows=self.decoded()
        self.assertEqual(rows,[]);self.assertEqual(manifest['chunks'],[]);self.assertEqual(manifest['selectedRecords'],0)
        for state in ('unreviewed','rejected','revoked','approved'):
            row=record();row.update(businessApproval=state,support='revoked' if state=='revoked' else 'candidate')
            self.reader=Reader([semantics.seal_record(row)]);self.run_export(state)
            _,rows=self.decoded(state);self.assertEqual(rows[0]['businessApproval'],state)
            self.assertFalse(rows[0]['businessMeaningComplete'])

    def test_duplicate_keys_ids_truncation_changed_order_and_dangling_edges(self):
        with self.assertRaises(exporter.BusinessExportError):exporter._strict_projection_json(b'{"id":"a","id":"b"}')
        self.reader=Reader([record(),record()]);self.assertEqual(self.rejects().code,'export_duplicate_identity')
        self.reader=Reader([record()]);self.reader.metadata['recordCount']=2
        self.assertEqual(self.rejects().code,'export_record_denominator_mismatch')
        self.reader=Reader([record(1),record(2)]);calls=[0];original=self.reader.iter_records
        def changed(*,page_size):
            calls[0]+=1
            yield from (list(original(page_size=page_size)) if calls[0]==1 else reversed(list(original(page_size=page_size))))
        with patch.object(self.reader,'iter_records',changed):self.assertEqual(self.rejects().code,'export_projection_roundtrip_mismatch')
        row=record();row['aliases']=[{'target':record(9)['id'],'relation':'alias','basis':'Neutral basis'}]
        self.reader=Reader([semantics.seal_record(row)]);self.assertEqual(self.rejects().code,'export_projection_dangling_reference')

    def test_callbacks_are_required_and_future_fields_cannot_silently_copy(self):
        exporter.configure(privacy_guard=guard,canonical=semantics.canonical,validate_record=semantics.validate_record_values)
        with self.assertRaises(exporter.BusinessExportError) as caught:self.run_export()
        self.assertEqual(caught.exception.code,'export_projection_dependencies_required')
        exporter.configure(privacy_guard=guard,canonical=semantics.canonical,validate_record=semantics.validate_record_values,policy_projection=self.api)
        self.reader.rows[0]['futureUnclassified']='Neutral surprise';self.reader.rows[0]=semantics.seal_record(self.reader.rows[0])
        self.rejects()

    def test_each_grant_cancel_and_record_total_budgets_fail_closed(self):
        for denied in ('read_policy','export_html'):
            def authorize(action):return {'decision':'deny' if action==denied else 'allow','revision':1}
            self.rejects(authorize=authorize)
        self.rejects(cancel=lambda:True)
        with patch.object(exporter,'MAX_RECORD_BYTES',20):self.rejects()
        self.rejects(max_output_bytes=20)

    def test_each_write_validation_reader_exit_promotion_and_final_checks(self):
        self.run_export('previous');before={str(p.relative_to(self.root/'previous')):p.read_bytes() for p in (self.root/'previous').rglob('*') if p.is_file()}
        original=exporter._BoundArtifacts.write
        baseline=self.run_export('baseline')['fileCount']
        for boundary in range(1,baseline+1):
            count=[0]
            def change(bound,name,raw):
                value=original(bound,name,raw);count[0]+=1
                if count[0]==boundary:self.profile_same=False
                return value
            self.profile_same=True
            with patch.object(exporter._BoundArtifacts,'write',change):self.rejects('write-'+str(boundary))
        self.profile_same=True
        original_validate=exporter._BoundArtifacts.validate
        def changed(bound,files):original_validate(bound,files);self.revision=2
        with patch.object(exporter._BoundArtifacts,'validate',changed):self.rejects('validation')
        self.revision=1
        def exit_failure():raise RuntimeError('Neutral reader exit failure')
        self.rejects('exit-failure',finish_reader=exit_failure)
        original_promote=exporter._promote
        def promote(bound,output):original_promote(bound,output);self.profile_same=False
        with patch.object(exporter,'_promote',promote):self.rejects('promoted-then-change')
        self.profile_same=True
        def authorize(action):
            result=self.authorize(action)
            if self.closed and action=='export_html':self.profile_same=False
            return result
        def finish():self.closed=True
        self.rejects('last-acl-profile',authorize=authorize,finish_reader=finish)
        self.assertEqual(before,{str(p.relative_to(self.root/'previous')):p.read_bytes() for p in (self.root/'previous').rglob('*') if p.is_file()})

    def test_source_policy_acl_changes_after_each_write_and_exclusive_publication(self):
        original=exporter._BoundArtifacts.write
        baseline=self.run_export('baseline')['fileCount']
        for kind in ('source','policy','acl'):
            for boundary in range(1,baseline+1):
                self.reader=Reader([record()]);self.revision=1;self.snapshot=True;count=[0]
                def change(bound,name,raw):
                    value=original(bound,name,raw);count[0]+=1
                    if count[0]==boundary:
                        if kind=='source':self.snapshot=False
                        elif kind=='policy':self.reader.metadata['businessDigest']='b'*64
                        else:self.revision=2
                    return value
                with patch.object(exporter._BoundArtifacts,'write',change):self.rejects(kind+'-'+str(boundary))
        before=(self.root/'baseline/policy-projection.json').read_bytes()
        with self.assertRaises(exporter.BusinessExportError):self.run_export('baseline')
        self.assertEqual((self.root/'baseline/policy-projection.json').read_bytes(),before)

    def test_all_eight_escape_families_allow_unregistered_deny_registered_and_digest(self):
        for index,character in enumerate(('"','\\','/','\b','\f','\n','\r','\t')):
            value='Neutral portable '+str(index)+':left'+character+'right'
            row=record();row['facets']['units']={'status':'DECLARED','value':{'type':'text','value':json.dumps(value)},'basis':'Neutral declared vocabulary'}
            self.reader=Reader([semantics.seal_record(row)])
            self.run_export('escape-'+str(index));_,decoded=self.decoded('escape-'+str(index))
            self.assertEqual(json.loads(decoded[0]['facets']['units']['value']['value']),value)
            with patch.object(guard,'load_profile',return_value=guard.build_profile([],[],key=b't'*32,values=[value])):
                # A previously issued snapshot must obey the new current profile.
                with self.assertRaises(guard.PrivacyError):query.project_record(self.reader.rows[0],evidence=False)
            protected=guard.build_profile([],[],key=b't'*32,values=[value])
            self.profile=protected
            self.profile_mock.return_value=protected
            self.rejects('registered-'+str(index))
            self.profile=guard.build_profile([],[],key=b'n'*32,values=['Unrelated neutral veto'])
            self.profile_mock.return_value=self.profile
        self.reader=Reader([record()]);self.profile=guard.build_profile([],[],key=b'd'*32,values=[PINS['businessDigest']]);self.profile_mock.return_value=self.profile
        self.rejects('registered-pin')

    def test_projected_file_hash_and_registered_profile_digest_are_not_exempt(self):
        result=self.run_export('before')
        file_hash=result['files']['records/part-000001.jsonl']['sha256']
        self.profile=guard.build_profile([],[],key=b'd'*32,values=[file_hash]);self.profile_mock.return_value=self.profile
        self.rejects('registered-file-hash')
        material=self.profile['denyValues'][0]['digest']
        self.reader.metadata['businessDigest']=material
        self.rejects('profile-digest',pins={**PINS,'businessDigest':material})


class AuthorizedPolicyProjectionStoreTests(unittest.TestCase):
    def setUp(self):
        from test_business_projection_boundaries import BusinessProjectionBoundaryTests
        self.fixture=BusinessProjectionBoundaryTests(methodName='runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def subprocess_environment(self,profile):
        import pipeline_acl as acl
        f=self.fixture;path=f.root/'explicit-neutral-profile.json';path.write_text(json.dumps(profile),encoding='utf-8');protect_private_path(path)
        env={key:value for key,value in os.environ.items() if not key.startswith(('PYTHON','CODE_ONTOLOGY'))}
        env.update({acl.PRINCIPAL_ENV:'reader',f.store._guard.PROFILE_ENV:str(path),'CODE_ONTOLOGY_HOME':str(f.root/'registry')})
        return env
    def wire(self,profile):
        f=self.fixture;cache=Path(tempfile.mkdtemp(prefix='neutral-mcp-cache-',dir=f.root))
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':f.args(limit=100)}}
        result=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),str(Path(__file__).resolve().parents[1]/'mcp/server.py')],
            input=json.dumps(request)+'\n',capture_output=True,text=True,timeout=30,env=self.subprocess_environment(profile))
        self.assertEqual(result.returncode,0);self.assertEqual(result.stderr,'')
        return json.loads(result.stdout)['result']
    def test_explicit_cli_selector_source_offline_and_default_stays_lossy(self):
        f=self.fixture;f.review([f.item()]);f.grant(['read_policy','export_html'])
        cache=Path(tempfile.mkdtemp(prefix='neutral-cli-cache-',dir=f.root))
        result=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),
            str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts/companion.py'),'business-html',
            '--workspace',str(f.workspace),'--snapshot',f.sid,'--business-snapshot',f.meta['businessSnapshotId'],
            '--business-digest',f.meta['businessDigest'],'--output',str(f.root/'cli-exact'),'--projection','policy_projection'],
            capture_output=True,text=True,timeout=30,env=self.subprocess_environment(f.profile))
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['projection'],'policy_projection')
        self.assertTrue((f.root/'cli-exact/policy-projection.json').is_file())
    def test_legacy_binding_promotion_failure_preserves_previous_receipt_and_pointer(self):
        f=self.fixture;f.review([f.item()]);f.grant(['read_policy','export_html'])
        previous=f.export('legacy-before');pointer=(f.workspace/'business-state.json').read_bytes()
        binding=f.workspace/'business-export-bindings'/previous['exportId']/'binding.json';before=binding.read_bytes()
        promote=f.exporter._promote
        def fail(bound,output):
            if output.parent.name=='business-export-bindings':raise f.exporter.BusinessExportError('export_destination_or_publication_changed')
            return promote(bound,output)
        with patch.object(f.exporter,'_promote',fail),self.assertRaises(f.exporter.BusinessExportError):f.export('legacy-failed')
        self.assertFalse((f.root/'legacy-failed').exists());self.assertEqual(binding.read_bytes(),before)
        self.assertEqual((f.workspace/'business-state.json').read_bytes(),pointer)
        self.assertEqual(sorted(p.name for p in (f.workspace/'business-export-bindings').iterdir()),[previous['exportId']])
    def test_real_closed_producer_and_source_offline_exact_minimum_grants(self):
        import pipeline_access as access
        import pipeline_acl as acl
        f=self.fixture;f.review([f.item()]);f.grant(['read_policy','export_html'])
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
            result=access.export_business_view(f.workspace,f.sid,f.meta,f.root/'exact',max_output_bytes=4*1024**2,
                profile=f.profile,profile_roots=[f.workspace],projection='policy_projection')
            with f.reader() as reader:
                expected=[f.query.project_record(row,evidence=False) for row in reader.iter_records(page_size=100)]
            manifest=json.loads((f.root/'exact/policy-projection.json').read_text(encoding='utf-8'))
            actual=[json.loads(line) for chunk in manifest['chunks'] for line in (f.root/'exact'/chunk['path']).read_text(encoding='utf-8').splitlines()]
            self.assertEqual(actual,expected);self.assertEqual(result['processedRecords'],f.meta['recordCount'])
            self.assertFalse((f.workspace/'business-export-bindings').exists())
            row=record();row['futureField']='Neutral unclassified value'
            with self.assertRaises(ValueError):f.query.validate_policy_projection_input(row,kind='record')
            with self.assertRaises(acl.AccessDenied):access.read_business_export_binding(f.workspace,f.sid,'projection-'+'0'*32)

    def test_source_offline_eight_current_registered_values_deny_read_and_export(self):
        import pipeline_access as access
        import pipeline_acl as acl
        f=self.fixture
        before=guard.build_profile([],[],key=b'k'*32,values=['Unrelated neutral veto'])
        values=['Neutral portable '+str(index)+':left'+character+'right' for index,character in enumerate(('"','\\','/','\b','\f','\n','\r','\t'))]
        with patch.object(f.store._guard,'load_profile',return_value=before):
            items=[]
            for index,value in enumerate(values):
                item=f.item('portable-'+str(index));item['facets']['units']={'status':'DECLARED','value':{'type':'text','value':json.dumps(value)},'basis':'Neutral declared vocabulary'};items.append(item)
            f.review(items);f.grant(['read_policy','export_html'])
            pointer=(f.workspace/'business-state.json').read_bytes()
            with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
                access.export_business_view(f.workspace,f.sid,f.meta,f.root/'before-registration',max_output_bytes=4*1024**2,
                    profile=before,profile_roots=[f.workspace],projection='policy_projection')
        reply=self.wire(before);self.assertFalse(reply.get('isError'));self.assertEqual(reply['structuredContent']['data']['returned'],f.meta['recordCount'])
        protected=guard.build_profile([],[],key=b'k'*32,values=values)
        with patch.object(f.store._guard,'load_profile',return_value=protected),patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
            with self.assertRaises((ValueError,RuntimeError)):f.call('ontology_pipeline_search')
            with self.assertRaises(f.exporter.BusinessExportError) as caught:
                access.export_business_view(f.workspace,f.sid,f.meta,f.root/'after-registration',max_output_bytes=4*1024**2,
                    profile=protected,profile_roots=[f.workspace],projection='policy_projection')
            self.assertEqual(caught.exception.report['selectedRecords'],f.meta['recordCount'])
            self.assertEqual(caught.exception.report['processedRecords'],caught.exception.processed)
            self.assertLess(caught.exception.processed,f.meta['recordCount'])
        reply=self.wire(protected);self.assertTrue(reply.get('isError'))
        guard.ensure_public_safe(reply,profile=protected,require_profile=True)
        self.assertFalse((f.root/'after-registration').exists())
        self.assertEqual((f.workspace/'business-state.json').read_bytes(),pointer)
        self.assertTrue((f.root/'before-registration/policy-projection.json').is_file())

    def test_initial_reader_current_profile_veto_preserves_zero_processed_denominator(self):
        import pipeline_access as access
        import pipeline_acl as acl
        f=self.fixture;f.grant(['read_policy','export_html'])
        protected=guard.build_profile([],[],key=b'k'*32,values=[f.meta['businessDigest']])
        with patch.object(f.store._guard,'load_profile',return_value=protected),patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):
            with self.assertRaises(f.exporter.BusinessExportError) as caught:
                access.export_business_view(f.workspace,f.sid,f.meta,f.root/'initial-reader-veto',max_output_bytes=4*1024**2,
                    profile=protected,profile_roots=[f.workspace],projection='policy_projection')
        self.assertEqual(caught.exception.code,'export_privacy_veto')
        self.assertEqual(caught.exception.report['selectedRecords'],f.meta['recordCount'])
        self.assertEqual(caught.exception.report['processedRecords'],0)
        self.assertFalse((f.root/'initial-reader-veto').exists())


if __name__=='__main__':unittest.main()
