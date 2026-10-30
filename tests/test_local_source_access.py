"""Explicit neutral source disclosure, source-free transport and revocation."""
import copy,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/manage-code-ontology/scripts'))
import pipeline_store as store,pipeline_acl as acl,pipeline_access as access,pipeline_documentation as docs
import pipeline_export,privacy_guard
from windows_fixture import protect_private_path

class LocalSourceAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name).resolve()
        self.repo=self.base/'source';self.repo.mkdir();self.workspace=self.base/'knowledge'
        self.token='/** A restored sample is a source claim; it grants no mutation permission. */'
        self.source=self.token+'\nrecord Box(int count){}\nclass Rules{Box make(int n){return helper(n);}private Box helper(int n){return new Box(n);}}\n'
        (self.repo/'Rules.java').write_text(self.source)
        (self.repo/'extra.py').write_text('def neutral(n):\n    return n + 2\n')
        self.profile=privacy_guard.build_profile(['Neutral Protected Person'],[],key=b'l'*32,values=['neutral-denied-value'])
        self.profilepath=self.base/'profile.json';self.profilepath.write_text(json.dumps(self.profile));protect_private_path(self.profilepath)
        environment=patch.dict(os.environ,{privacy_guard.PROFILE_ENV:str(self.profilepath),acl.PRINCIPAL_ENV:'local-owner','CODE_ONTOLOGY_HOME':str(self.base/'registry')})
        environment.start();self.addCleanup(environment.stop)
        initial=store.initialize(self.repo,self.workspace);self.workspace_id=initial['workspaceId']
        acl.initialize_access(self.workspace);acl.update_access(self.workspace,'policy-reader',['read_policy'],['*'])
        access.register(str(self.workspace))
    def receipt(self,token=None):
        config=json.loads((self.workspace/'pipeline.json').read_text());files,counts=store._discover(self.repo,config['sourceRoots'],store.DEFAULT_BUDGETS)
        token=self.token if token is None else token
        return {'format':docs.LOCAL_ACCESS_FORMAT,'purpose':'local-source-analysis','permissionId':'neutral-user-scope','sourceFingerprint':store._fingerprint(files),
            'scopeDigest':counts['inventory']['scopeDigest'],'selectedScope':sorted(config['sourceRoots'] or ['.']),'privateDestinationId':config['workspaceId'],
            'profileSha256':hashlib.sha256(store._json(self.profile)).hexdigest(),'aclSha256':hashlib.sha256((self.workspace/'access.json').read_bytes()).hexdigest(),
            'revocationId':'neutral-revision-1','revoked':False,'expiresAt':None,
            'entries':[{'path':'Rules.java','sourceSha256':hashlib.sha256((self.repo/'Rules.java').read_bytes()).hexdigest(),'tokenByteStart':0,'tokenByteEnd':len(token.encode()),'tokenSha256':hashlib.sha256(token.encode()).hexdigest()}]}
    def capture(self):
        receipt=self.receipt();return store.sync(self.workspace,local_source_access=receipt)
    def documentation(self,snapshot):
        return [r for r in store.iter_records(self.workspace,snapshot)if r.get('category')=='source_documentation']
    def test_default_unchanged_then_independent_capture_counts(self):
        initial=store.status(self.workspace);self.assertNotIn('sourceText',self.documentation(initial['snapshotId'])[0])
        captured=self.capture();claim=self.documentation(captured['snapshotId'])[0]
        self.assertEqual(claim['sourceText'],self.token);self.assertEqual(claim['semanticReview'],'UNREVIEWED');self.assertEqual(claim['instructionAuthority'],'none')
        self.assertEqual(claim['evidence']['enforcement'],'UNKNOWN');self.assertNotIn('documentationReview',claim)
        coverage=captured['coverage']['documentation'];self.assertEqual(coverage['reviewedFragments'],0);self.assertEqual(coverage['localCapturedFragments'],1);self.assertEqual(coverage['unreviewedFragments'],1)
        self.assertNotEqual(initial['analysisSpecId'],captured['analysisSpecId'])
        self.assertFalse(captured['coverage']['semantics']['sourceRelations']['semanticComplete'])
        relations=[relation for row in store.iter_records(self.workspace,captured['snapshotId'])
                   for relation in row.get('sourceRelations',{}).get('relations',[])]
        for kind in ['helper_return_source_summary','constructor_parameter_component_transfer']:
            self.assertTrue(any(r['relationKind']==kind and r['resolution']=='represented'and r['validation']['status']=='verified_emitted_ir'for r in relations),kind)
    def test_metadata_only_occurrence_builder_keeps_complete_utf8_crlf_tokens(self):
        token='/** neutral 한글 source claim */'
        source='class Rules{String text="/* not a comment */";}\r\n'+token+'\r\n'
        digest=hashlib.sha256(source.encode()).hexdigest();inventory=docs.local_source_occurrences(source,'Java','neutral/Rules.java',digest)
        self.assertEqual(inventory['detectedComments'],1);entry=inventory['entries'][0]
        encoded=source.encode();self.assertEqual(encoded[entry['tokenByteStart']:entry['tokenByteEnd']],token.encode())
        self.assertEqual(entry['tokenSha256'],hashlib.sha256(token.encode()).hexdigest());self.assertFalse(inventory['sourceTextIncluded'])
        self.assertNotIn(token,json.dumps(inventory))
        unsupported=docs.local_source_occurrences('x=2','Python','neutral/rules.py',hashlib.sha256(b'x=2').hexdigest())
        self.assertEqual(unsupported['status'],'unsupported');self.assertEqual(unsupported['commentDenominator'],'UNKNOWN')

    def test_independent_review_and_local_capture_remain_separate(self):
        first='/** An independently reviewed neutral source statement. */'
        second='/** A locally permitted neutral source statement. */'
        self.source=first+'\n'+second+'\nclass Rules{}';(self.repo/'Rules.java').write_text(self.source)
        receipt=self.receipt(first);entry=copy.deepcopy(receipt['entries'][0]);entry.update(tokenByteStart=len((first+'\n').encode()),tokenByteEnd=len((first+'\n'+second).encode()),tokenSha256=hashlib.sha256(second.encode()).hexdigest());receipt['entries'].append(entry)
        review={'format':docs.FORMAT,'purpose':docs.PURPOSE,'sourceFingerprint':receipt['sourceFingerprint'],
            'review':{'reviewId':'neutral-independent-review','reviewerKind':'independent_source_review','reviewedAt':'2026-01-01T00:00:00Z'},
            'entries':[{**receipt['entries'][0],'classification':'nonsecret_documentation','reasonCode':'neutral_claim','usageContext':'neutral_test','reviewId':'neutral-independent-review'}]}
        outcome=store.sync(self.workspace,documentation_review=review,local_source_access=receipt)
        claims=self.documentation(outcome['snapshotId']);self.assertEqual(len(claims),2)
        coverage=outcome['coverage']['documentation'];self.assertEqual(coverage['reviewedFragments'],1);self.assertEqual(coverage['localCapturedFragments'],1);self.assertEqual(coverage['unreviewedFragments'],1)
        summary=outcome['localSourceAccess'];self.assertFalse(summary['publicDisclosureAuthorized'])

    def test_exact_occurrence_and_protected_full_token_denial(self):
        self.token='/** neutral-denied-value */';self.source=self.token+'\nclass Rules{}';(self.repo/'Rules.java').write_text(self.source)
        outcome=self.capture();claim=self.documentation(outcome['snapshotId'])[0]
        self.assertNotIn('sourceText',claim);self.assertEqual(claim['sourceDisclosure']['reason'],'privacy_denied')
        self.assertEqual(outcome['coverage']['documentation']['detectedFragments'],1)
        self.assertEqual(outcome['coverage']['documentation']['blockedFragments'],1)
    def test_source_deleted_real_stdio_low_role_negative_authorized_positive_and_roundtrip(self):
        outcome=self.capture();snapshot=outcome['snapshotId'];claim=self.documentation(snapshot)[0]
        allrows=list(store.iter_records(self.workspace,snapshot));relations=[r for r in allrows if 'sourceRelations'in r]
        self.assertTrue(relations);self.assertTrue(any(x['resolution']=='represented'for row in relations for x in row['sourceRelations']['relations']))
        shutil.rmtree(self.repo)
        request={'jsonrpc':'2.0','id':7,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':{'workspace_id':self.workspace_id,'snapshot_id':snapshot,'kind':'semantic_fragment','record_ids':[claim['id']],'limit':1}}}
        def call(principal):
            env={**os.environ,acl.PRINCIPAL_ENV:principal}
            result=subprocess.run([sys.executable,'-E','-s','-B',str(ROOT/'mcp/server.py')],input=json.dumps(request)+'\n',text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr);return json.loads(result.stdout)['result']
        positive=call('local-owner');self.assertFalse(positive['isError'],positive);self.assertEqual(positive['structuredContent']['data']['records'][0]['sourceText'],self.token)
        denied=call('policy-reader');self.assertTrue(denied['isError']);self.assertNotIn(self.token,json.dumps(denied))
        bundle=self.base/'bundle';pipeline_export.export_bundle(self.workspace,snapshot,bundle,include_business=False)
        database=sqlite3.connect(str(bundle/'knowledge.sqlite'))
        try: portable=[json.loads(row[0])for row in database.execute('SELECT payload FROM records ORDER BY id')]
        finally: database.close()
        self.assertEqual(sorted(portable,key=lambda r:r['id']),sorted(allrows,key=lambda r:r['id']))
        self.assertIn('sourceText',json.dumps(portable))
        # Parse the RDF literals and recover the exact authorized record fields.
        import rdflib
        graph=rdflib.Graph();graph.parse(str(bundle/'ontology.ttl'),format='turtle')
        claims=[json.loads(str(value))for value in graph.objects(None,rdflib.URIRef('urn:code-ontology:pipeline:documentationEvidence'))]
        self.assertEqual(claims[0]['sourceText'],self.token)
        values=[json.loads(str(value))for value in graph.objects(None,rdflib.URIRef('urn:code-ontology:pipeline:sourceRelations'))]
        self.assertEqual(sorted(json.dumps(x,sort_keys=True)for x in values),sorted(json.dumps(row['sourceRelations'],sort_keys=True)for row in relations))
    def test_profile_and_acl_change_fail_before_reader_or_export(self):
        outcome=self.capture();snapshot=outcome['snapshotId']
        self.profilepath.write_text(json.dumps(privacy_guard.build_profile(['Another Neutral Person'],[],key=b'q'*32)));protect_private_path(self.profilepath)
        with self.assertRaisesRegex(store.PipelineError,'local_source_access_snapshot_invalid'):store.query(self.workspace,snapshot,kind='semantic_fragment')
        with self.assertRaisesRegex(Exception,'Portable export failed validation'):pipeline_export.export_bundle(self.workspace,snapshot,self.base/'denied-bundle',include_business=False)
        self.assertFalse((self.base/'denied-bundle').exists())
        self.profilepath.write_text(json.dumps(self.profile));protect_private_path(self.profilepath)
        acl.update_access(self.workspace,'policy-reader',[],['*'])
        with self.assertRaisesRegex(store.PipelineError,'local_source_access_snapshot_invalid'):store.query(self.workspace,snapshot,kind='semantic_fragment')
    def test_revoked_scope_expired_receipt_and_clear_never_reuse_capture(self):
        outcome=self.capture();snapshot=outcome['snapshotId'];config=json.loads((self.workspace/'pipeline.json').read_text())
        changed=copy.deepcopy(config);changed['localSourceAccess']['revoked']=True;store._atomic(self.workspace/'pipeline.json',changed)
        with self.assertRaisesRegex(store.PipelineError,'local_source_access_snapshot_invalid'):store.query(self.workspace,snapshot,kind='semantic_fragment')
        store._atomic(self.workspace/'pipeline.json',config)
        revoked=store.sync(self.workspace,clear_local_source_access=True);self.assertFalse(revoked['generationPerformed'])
        with self.assertRaisesRegex(store.PipelineError,'local_source_access_snapshot_invalid'):store.query(self.workspace,snapshot,kind='semantic_fragment')
        cleared=store.sync(self.workspace);self.assertNotIn('sourceText',self.documentation(cleared['snapshotId'])[0])
        receipt=self.receipt();receipt['expiresAt']='2000-01-01T00:00:00Z'
        with self.assertRaisesRegex(store.PipelineError,'local_source_access_binding_invalid'):store.sync(self.workspace,local_source_access=receipt)
    def test_warm_stdio_process_cannot_reuse_captured_text_after_revoke(self):
        outcome=self.capture();snapshot=outcome['snapshotId'];claim=self.documentation(snapshot)[0];shutil.rmtree(self.repo)
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':{'workspace_id':self.workspace_id,'snapshot_id':snapshot,'kind':'semantic_fragment','record_ids':[claim['id']],'limit':1}}}
        process=subprocess.Popen([sys.executable,'-E','-s','-B',str(ROOT/'mcp/server.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ))
        try:
            process.stdin.write(json.dumps(request)+'\n');process.stdin.flush();first=json.loads(process.stdout.readline())['result']
            self.assertFalse(first['isError']);self.assertEqual(first['structuredContent']['data']['records'][0]['sourceText'],self.token)
            store.revoke_local_source_access(self.workspace)
            request['id']=2;process.stdin.write(json.dumps(request)+'\n');process.stdin.flush();second=json.loads(process.stdout.readline())['result']
            self.assertTrue(second['isError']);self.assertNotIn(self.token,json.dumps(second))
        finally:
            process.stdin.close();process.wait(timeout=10);process.stdout.close();process.stderr.close()

    def test_revocation_does_not_require_source_or_generation(self):
        outcome=self.capture();shutil.rmtree(self.repo)
        revoked=store.revoke_local_source_access(self.workspace)
        self.assertEqual(revoked['sourceAccess'],'not_read');self.assertFalse(revoked['generationPerformed'])
        with self.assertRaisesRegex(store.PipelineError,'local_source_access_snapshot_invalid'):store.query(self.workspace,outcome['snapshotId'],kind='semantic_fragment')

    def test_scope_destination_and_occurrence_hash_cannot_be_substituted(self):
        for key,value in [('sourceFingerprint','0'*64),('scopeDigest','0'*64),('privateDestinationId','pw-'+'0'*32),('aclSha256','0'*64),('profileSha256','0'*64),('selectedScope',['other'])]:
            receipt=self.receipt();receipt[key]=value
            with self.assertRaisesRegex(store.PipelineError,'local_source_access_binding_invalid'):store.sync(self.workspace,local_source_access=receipt)
        receipt=self.receipt();receipt['entries'][0]['tokenSha256']='0'*64
        outcome=store.sync(self.workspace,local_source_access=receipt)
        claim=self.documentation(outcome['snapshotId'])[0];self.assertNotIn('sourceText',claim);self.assertEqual(claim['sourceDisclosure']['reason'],'occurrence_digest_mismatch')

    def test_v3_declared_typed_name_store_mcp_sqlite_html_rdf_roundtrip(self):
        # Synthetic declared-input wrapper, not a claim that Java parsing
        # naturally emits null or empty return names.
        import policy_semantics as sem,pipeline_html,rdflib
        for state,value in [('absent',None),('empty',''),('null',None)]:
            repo=self.base/('source-'+state);repo.mkdir();(repo/'Rules.java').write_text('class Rules{int g(int n){return h(n);}private int h(int x){return x+1;}}')
            workspace=self.base/('typed-'+state);original=sem._build_source_relations
            def inject(result,*args,**kwargs):
                for row in result['fragments']:
                    if row['category']=='return':
                        if state=='absent':row.pop('name',None)
                        else:row['name']=value
                return original(result,*args,**kwargs)
            with patch.object(sem,'_build_source_relations',inject):outcome=store.initialize(repo,workspace)
            acl.initialize_access(workspace);access.register(str(workspace));snapshot=outcome['snapshotId']
            rows=list(store.iter_records(workspace,snapshot));marked=[row for row in rows if 'sourceRelationInputNamePresent'in row]
            for row in marked:
                if row['category']=='return':
                    self.assertEqual(row['sourceRelationInputNamePresent'],state!='absent')
                    self.assertEqual(row['name'],row['category']if state=='absent'else value)
            coverage=next(row['coverage']for row in rows if row.get('name')=='SemanticCoverage')
            result={'path':'Rules.java','sourceDigest':marked[0]['sourceDigest'],'coverage':coverage,'fragments':marked}
            closure=sem._source_input_closure(result,[row for row in rows if row['kind']in{'symbol','callsite'}])
            for row in marked:
                for relation in row.get('sourceRelations',{}).get('relations',[]):self.assertEqual(relation['inputClosure'],closure)
            shutil.rmtree(repo)
            selected=[row['id']for row in marked]
            request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':{'workspace_id':outcome['workspaceId'],'snapshot_id':snapshot,'kind':'semantic_fragment','record_ids':selected,'limit':100}}}
            response=subprocess.run([sys.executable,'-E','-s','-B',str(ROOT/'mcp/server.py')],input=json.dumps(request)+'\n',text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ),timeout=30)
            self.assertEqual(response.returncode,0,response.stderr);delivered=json.loads(response.stdout)['result'];self.assertFalse(delivered['isError'],delivered)
            self.assertEqual(sorted(delivered['structuredContent']['data']['records'],key=lambda row:row['id']),sorted(marked,key=lambda row:row['id']))
            bundle=self.base/('bundle-'+state);pipeline_export.export_bundle(workspace,snapshot,bundle,include_business=False)
            with sqlite3.connect(str(bundle/'knowledge.sqlite'))as db:
                actual=[json.loads(row[0])for row in db.execute('SELECT payload FROM records ORDER BY id')]
                indices=dict(db.execute('SELECT id,name FROM records'))
            self.assertEqual(actual,sorted(rows,key=lambda row:row['id']))
            for row in marked:self.assertEqual(indices[row['id']],store.indexed_record_name(row))
            html=self.base/('html-'+state);pipeline_html.render_pipeline(workspace,snapshot,html,include_maps=False,include_business=False,catalog_scope="partitioned")
            raw=[]
            for path in (html/'data').glob('*.json'):
                document=json.loads(path.read_text())
                if isinstance(document,dict):raw.extend(document.get('records',[]))
            self.assertEqual(sorted(raw,key=lambda row:row['id']),sorted(rows,key=lambda row:row['id']))
            graph=rdflib.Graph();graph.parse(str(bundle/'ontology.ttl'),format='turtle')
            values=[json.loads(str(v))for v in graph.objects(None,rdflib.URIRef('urn:code-ontology:pipeline:sourceRelations'))]
            self.assertEqual(sorted(json.dumps(v,sort_keys=True)for v in values),sorted(json.dumps(row['sourceRelations'],sort_keys=True)for row in rows if'sourceRelations'in row))
        self.assertRaises(store.PipelineError,store.indexed_record_name,{'kind':'symbol','name':None})

    def test_v3_existing_callback_order_time_constructor_type_positive_floor(self):
        text=('import java.util.Comparator; import java.time.Duration; record Box(int count){} '
              'class Entry{int rank(){return 1;}String label(){return null;}} '
              'class Rules{Object order(){return Comparator.comparingInt(Entry::rank).thenComparing(Entry::label);} '
              'long clock(){return Duration.ofSeconds(2).plus(Duration.ofMillis(300)).toMillis();} '
              'Box make(int n){return new Box(n);}int number(int n){return helper(n);}private int helper(int x){return x+1;}}')
        (self.repo/'Rules.java').write_text(text);outcome=store.sync(self.workspace);snapshot=outcome['snapshotId'];shutil.rmtree(self.repo)
        rows=list(store.iter_records(self.workspace,snapshot));pending=[row.get('expression')for row in rows];counts={'callback':0,'ordering':0,'time':0,'constructor':0,'type':0}
        catalog={entry['id']:entry for row in rows for entry in row.get('standardApiContracts',[])}
        while pending:
            node=pending.pop()
            if isinstance(node,dict):
                contract=node.get('staticContract',{})
                if isinstance(contract,dict):
                    counts['callback']+=isinstance(contract.get('callbackBinding'),dict)
                    counts['ordering']+=isinstance(contract.get('orderingContract'),dict)
                    counts['time']+=catalog.get(contract.get('contractId'),{}).get('declaringType')=='java.time.Duration'
                counts['constructor']+=isinstance(node.get('recordConstruction'),dict)
                counts['type']+=node.get('staticType',{}).get('resolution')=='resolved_static_type'
                pending.extend(node.values())
            elif isinstance(node,list):pending.extend(node)
        for key,value in counts.items():self.assertGreater(value,0,key)
        print(json.dumps({'existingFamilyPositiveFloor':counts,'sourceDeleted':True}))
        relations=[r for row in rows for r in row.get('sourceRelations',{}).get('relations',[])]
        for kind in ['helper_return_source_summary','constructor_parameter_component_transfer']:self.assertTrue(any(r['relationKind']==kind and r['resolution']=='represented'for r in relations),kind)
        legacy={'schemaVersion','scope','ownerTypeId','headerRange','invocationKind','access','varargs','generic','hasBody','declarationValidity'}
        for row in rows:
            if row.get('type')=='Method':self.assertEqual(set(row['callbackDeclaration']),legacy);self.assertIsInstance(row['sourceMethodModifiers'],list)
        bundle=self.base/'positive-floor';pipeline_export.export_bundle(self.workspace,snapshot,bundle,include_business=False)
        with sqlite3.connect(str(bundle/'knowledge.sqlite'))as db:self.assertEqual([json.loads(r[0])for r in db.execute('SELECT payload FROM records ORDER BY id')],sorted(rows,key=lambda r:r['id']))

    def rdf_fixture(self):
        receipt=self.receipt()
        context=docs.prepare_local_source_access(receipt,source_fingerprint=receipt['sourceFingerprint'],selected_scope=receipt['selectedScope'],
                    scope_digest=receipt['scopeDigest'],destination_id=receipt['privateDestinationId'],profile=self.profile,acl_sha256=receipt['aclSha256'])
        result=docs.extract_documentation(self.source,'Java','Rules.java',hashlib.sha256(self.source.encode()).hexdigest(),local_access=context)
        row={**result['fragments'][0],'kind':'semantic_fragment','module':'neutral','modulePath':'.','basis':'declared','status':'runtime_unknown'}
        return row,context
    def rdf_emit(self,row,bindings=None):
        import rdflib
        directory=self.base/('rdf-'+str(len(list(self.base.glob('rdf-*')))));directory.mkdir()
        db=sqlite3.connect(':memory:');db.execute('CREATE TABLE records(id TEXT,kind TEXT,path TEXT,name TEXT,payload TEXT)')
        db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(row['id'],row['kind'],row['path'],row['name'],json.dumps(row)))
        try:store._rdf(directory,[db],'ps-neutral','run-neutral',documentation_bindings=bindings)
        finally:db.close()
        graph=rdflib.Graph();graph.parse(str(directory/'ontology.ttl'),format='turtle')
        return [json.loads(str(v))for v in graph.objects(None,rdflib.URIRef('urn:code-ontology:pipeline:documentationEvidence'))]
    def test_v4_rdf_default_opaque_and_exact_current_occurrence_positive(self):
        row,context=self.rdf_fixture();self.assertEqual(self.rdf_emit(row),[])
        bindings=docs.RdfDocumentationBindings([row],local_access=context)
        self.assertEqual(self.rdf_emit(row,bindings),[docs.RdfDocumentationBindings.claim(row)])
        self.assertEqual(bindings.coverage()['serialized'],1)
        with self.assertRaisesRegex(store.PipelineError,'rdf_documentation_permission_unavailable'):
            self.rdf_emit(row,docs.RdfDocumentationBindings([],local_access=context))
    def test_v4_rdf_token_claim_proof_status_mutations_are_explicit_failures(self):
        probes=['token','partial_token','path','digest','range','comment_hash','proof_hash','claim_authority','disclosure_status','permission_receipt','permission_status']
        for probe in probes:
            row,context=self.rdf_fixture();bindings=docs.RdfDocumentationBindings([row],local_access=context);changed=copy.deepcopy(row)
            if probe=='token':changed['sourceText']=changed['sourceText'].replace('restored','altered')
            elif probe=='partial_token':changed['sourceText']=changed['sourceText'][:-2]
            elif probe=='path':changed['path']='Other.java'
            elif probe=='digest':changed['sourceDigest']='0'*64
            elif probe=='range':changed['sourceRange']['byteEnd']-=1
            elif probe=='comment_hash':changed['commentSha256']='0'*64
            elif probe=='proof_hash':changed['localCapturePermission']['receiptSha256']='0'*64
            elif probe=='claim_authority':changed['instructionAuthority']='enforcement'
            elif probe=='disclosure_status':changed['sourceDisclosure']['status']='unreviewed'
            elif probe=='permission_receipt':context.receipt['revoked']=True
            else:context._entries[0]['status']='rejected'
            with self.assertRaisesRegex(store.PipelineError,'rdf_documentation_binding_changed',msg=probe):self.rdf_emit(changed,bindings)
            self.assertEqual(bindings.coverage()['withdrawnAfterBinding'],1)
    def test_v4_rdf_binding_budget_is_distinct_and_snapshot_never_promotes_mismatch(self):
        row,context=self.rdf_fixture()
        with patch.object(docs.RdfDocumentationBindings,'MAX_BINDING_BYTES',0):bindings=docs.RdfDocumentationBindings([row],local_access=context)
        self.assertEqual(bindings.coverage()['omitted'],1)
        with self.assertRaisesRegex(store.PipelineError,'rdf_documentation_binding_budget'):self.rdf_emit(row,bindings)
        before=(self.workspace/'state.json').read_bytes();original=docs.RdfDocumentationBindings.allows
        with patch.object(docs.RdfDocumentationBindings,'allows',return_value=False):
            with self.assertRaisesRegex(store.PipelineError,'rdf_documentation_binding_changed'):self.capture()
        self.assertEqual(before,(self.workspace/'state.json').read_bytes())
        attempt=json.loads((self.workspace/'last-coverage-attempt.json').read_text())
        self.assertEqual(attempt['documentationFailures'][0]['reason'],'rdf_documentation_binding_changed')

    def test_v4_source_reader_resource_policy_default_is_noop_and_closed(self):
        class Connection:
            def __init__(self,heap=None,temp=2,compiled=None):self.heap=heap;self.temp=temp;self.compiled=[('TEMP_STORE=1',)]if compiled is None else compiled;self.sql=[];self.last=''
            def execute(self,sql):
                self.sql.append(sql);self.last=sql
                if 'hard_heap_limit='in sql:raise AssertionError('helper must never set global heap')
                return self
            def fetchone(self):return self.heap if self.last=='PRAGMA hard_heap_limit'else(self.temp,)
            def fetchall(self):return self.compiled
        empty=Connection();self.assertIsNone(store.configure_reader_resource_policy(empty));self.assertEqual(empty.sql,[])
        for policy in ['',True,{},'memory','bounded_memory_v2']:
            with self.assertRaisesRegex(store.PipelineError,'reader_resource_policy_invalid'):store.configure_reader_resource_policy(empty,policy)
        self.assertEqual(empty.sql,[])
        for heap in [None,(0,),(134217729,),(True,)]:
            connection=Connection(heap)
            with self.assertRaisesRegex(store.PipelineError,'reader_resource_policy_heap_unavailable'):store.configure_reader_resource_policy(connection,'bounded_memory_v1')
            self.assertEqual(connection.sql,['PRAGMA hard_heap_limit'])
        with self.assertRaisesRegex(store.PipelineError,'reader_resource_policy_unsupported'):store.configure_reader_resource_policy(Connection((134217728,),1),'bounded_memory_v1')
        for compiled in [[],[('TEMP_STORE=0',)],[('TEMP_STORE=unknown',)],[('TEMP_STORE=1',),('TEMP_STORE=2',)]]:
            connection=Connection((134217728,),compiled=compiled)
            with self.assertRaisesRegex(store.PipelineError,'reader_resource_policy_unsupported'):store.configure_reader_resource_policy(connection,'bounded_memory_v1')
            self.assertEqual(connection.sql,['PRAGMA hard_heap_limit','PRAGMA compile_options'])
        connection=Connection((134217728,));self.assertEqual(store.configure_reader_resource_policy(connection,'bounded_memory_v1'),{'policy':'bounded_memory_v1','hardHeapLimit':134217728,'tempStore':2})
        self.assertEqual(connection.sql,['PRAGMA hard_heap_limit','PRAGMA compile_options','PRAGMA temp_store=MEMORY','PRAGMA temp_store'])
        with store.open_reader(self.workspace)as ordinary:
            self.assertEqual(ordinary.resource_policy,None);self.assertEqual(ordinary.connection.execute('PRAGMA temp_store').fetchone(),(0,))
        with self.assertRaisesRegex(store.PipelineError,'reader_resource_policy_invalid'):store.open_reader(self.workspace,resource_policy='unknown')

if __name__=='__main__':unittest.main()
