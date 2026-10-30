"""Neutral complete export-set coverage, cross-part links and atomic failures."""
import copy
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import sys
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from urllib.parse import unquote,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import companion
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as source
import pipeline_html
import pipeline_export

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.links=[];self.ids=set();self.feed(text)
    def handle_starttag(self,tag,attrs):
        fields=dict(attrs)
        for key in ('href','src'):
            if key in fields:self.links.append(fields[key])
        if 'id' in fields:self.ids.add(fields['id'])

class PartitionedCleanupTests(unittest.TestCase):
    """Wiring tests; actual Windows handle disposal is tested separately."""
    def setUp(self):
        self.module=companion.core._load_bundled_helper('pipeline_partitioned')
        previous=(self.module._store,self.module._exporter,self.module._guard)
        self.addCleanup(self.module.configure,store=previous[0],exporter=previous[1],privacy_guard=previous[2])
        self.exporter=access._business()[2]
        self.module.configure(store=None,exporter=self.exporter,privacy_guard=companion.privacy_guard)
    def boundary(self):
        boundary=self.module._SetBoundary.__new__(self.module._SetBoundary)
        boundary.db=sqlite3.connect(':memory:');self.addCleanup(boundary.db.close)
        boundary.db.execute('CREATE TABLE entries(path TEXT,kind TEXT,identity TEXT,depth INTEGER)')
        boundary.total_files=0;boundary.total_bytes=0
        parent=Path('/neutral/parent');boundary.output=parent/'output'
        identity=SimpleNamespace(st_dev=17,st_ino=19,st_mode=stat.S_IFDIR|0o700,st_file_attributes=0)
        windows=SimpleNamespace(pending_rename=False,stage_handoff_failed=False,remove_stage=Mock())
        boundary.bound=SimpleNamespace(windows=windows,root_identity=identity,parent=parent,name='stage',parent_fd=None,verify_parent=Mock())
        return boundary
    def test_unverified_empty_root_is_always_counted_as_retained(self):
        for mode in ('pending','handoff','parent','no_identity'):
            with self.subTest(mode=mode):
                boundary=self.boundary()
                boundary.bound.windows.pending_rename=mode=='pending'
                boundary.bound.windows.stage_handoff_failed=mode=='handoff'
                if mode=='parent':boundary.bound.verify_parent.side_effect=self.exporter.BusinessExportError('export_parent_changed')
                if mode=='no_identity':boundary.bound.root_identity=None
                with patch.object(self.module.os,'unlink') as unlink,patch.object(self.module.os,'rmdir') as rmdir:
                    result=boundary.cleanup()
                self.assertEqual(result,{'status':'UNVERIFIED_RETAINED','removed':0,'retained':1})
                unlink.assert_not_called();rmdir.assert_not_called();boundary.bound.windows.remove_stage.assert_not_called()
    def test_owned_empty_root_uses_native_disposal_and_counts_failure(self):
        for failed in (False,True):
            with self.subTest(failed=failed):
                boundary=self.boundary();stage=boundary.bound.parent/boundary.bound.name
                if failed:boundary.bound.windows.remove_stage.side_effect=self.exporter.BusinessExportError('export_stage_cleanup_failed')
                def locate(path,*args,**kwargs):
                    if path==stage:return boundary.bound.root_identity
                    raise FileNotFoundError
                with patch.object(type(stage),'lstat',new=locate),patch.object(self.module.os,'unlink') as unlink,patch.object(self.module.os,'rmdir') as rmdir:
                    result=boundary.cleanup()
                boundary.bound.windows.remove_stage.assert_called_once_with(stage)
                unlink.assert_not_called();rmdir.assert_not_called()
                self.assertEqual(result['removed'],0);self.assertEqual(result['retained'],1 if failed else 0)
                self.assertEqual(result['status'],'UNKNOWN_OR_CHANGED_ENTRIES_RETAINED'if failed else'OWN_ENTRIES_REMOVED')
    def test_changed_or_reparse_root_is_retained_without_path_deletion(self):
        for changed in ('identity','reparse'):
            with self.subTest(changed=changed):
                boundary=self.boundary();stage=boundary.bound.parent/boundary.bound.name
                observed=SimpleNamespace(**vars(boundary.bound.root_identity))
                if changed=='identity':observed.st_ino+=1
                else:observed.st_file_attributes=0x400
                def locate(path,*args,**kwargs):
                    if path==stage:return observed
                    raise FileNotFoundError
                with patch.object(type(stage),'lstat',new=locate),patch.object(self.module.os,'unlink') as unlink,patch.object(self.module.os,'rmdir') as rmdir:
                    result=boundary.cleanup()
                self.assertEqual(result['retained'],1);self.assertEqual(result['status'],'UNKNOWN_OR_CHANGED_ENTRIES_RETAINED')
                unlink.assert_not_called();rmdir.assert_not_called();boundary.bound.windows.remove_stage.assert_not_called()

class PartitionedExportTests(unittest.TestCase):
    source_newline=b'\n'
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.profile=companion.privacy_guard.build_profile(['Neutral Private Person'],['private@example.test'],key=b'z'*32)
        self.profile_patches=[patch.object(companion.privacy_guard,'load_profile',return_value=self.profile),patch.object(pipeline_html.privacy_guard,'load_profile',return_value=self.profile)]
        for item in self.profile_patches:item.start();self.addCleanup(item.stop)
        self.env=patch.dict(os.environ,{acl.PRINCIPAL_ENV:'neutral-owner'});self.env.start();self.addCleanup(self.env.stop)
        self.repo=self.root/'source';self.repo.mkdir();(self.repo/'items.py').write_bytes(b'def eligible(active: bool) -> bool:\n    return active\ndef ready(active: bool) -> bool:\n    return active\n'.replace(b'\n',self.source_newline))
        self.workspace=self.root/'knowledge';self.sid=source.initialize(self.repo,self.workspace,prepare_workspace=acl.initialize_access,max_output_bytes=8*1024**3)['snapshotId']
        self.store,self.query,self.exporter=access._business();self.meta=self.store.build(self.workspace,self.sid)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            self.base_ids=[r['id'] for r in reader.iter_records()];anchor=reader.get_record(self.base_ids[0])['sourceAnchors']
        sem=self.store._semantics
        first={'namespace':'review','domain':'catalog','kind':'business_object_type','conceptKey':'one','label':'Item','sourceAnchors':anchor,'facets':{}}
        second=copy.deepcopy(first);second['conceptKey']='two'
        relation=copy.deepcopy(first);relation.update(kind='business_relation',conceptKey='link',role='contains',subject=sem.concept_id('review','catalog','business_object_type','one'))
        # Choose a neutral key that guarantees a cross-part relation under the
        # small five-record part limit used to exercise the ordinary 10000 cap.
        for index in range(100):
            second['conceptKey']='two'+str(index);relation['object']=sem.concept_id('review','catalog','business_object_type',second['conceptKey'])
            rid=sem.concept_id('review','catalog','business_relation','link');ids=sorted(self.base_ids+[relation['subject'],relation['object'],rid])
            if ids.index(rid)//5!=ids.index(relation['object'])//5:break
        self.relation_id=rid;self.object_id=relation['object']
        review={'schemaVersion':1,'sourcePins':{k:self.meta[k] for k in sem.PIN_KEYS},'concepts':[first,second,relation]}
        self.meta=self.store.review(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'],review)
        self.repo.rename(self.root/'source-offline')
        self.module=companion.core._load_bundled_helper('pipeline_partitioned');self.module.configure(store=self.store,exporter=self.exporter,privacy_guard=companion.privacy_guard)
        self.destination=self.root/'exports';self.destination.mkdir();self.output=self.destination/'output'
    def run_export(self,**kwargs):
        return self.module.export_partitioned(self.workspace,self.sid,self.output,part_records=kwargs.pop('part_records',5),**kwargs)
    def source_hashes(self):return {str(p.relative_to(self.workspace)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.workspace/'snapshots').rglob('*') if p.is_file()}
    def descriptors(self):
        root=json.loads((self.output/'export-set.json').read_text(encoding='utf-8'));parts=[]
        for descriptor in root['partCatalogs']:
            raw=(self.output/descriptor['path']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),descriptor['sha256']);parts.extend(json.loads(raw)['parts'])
        return root,parts
    def test_full_union_original_denominator_and_all_artifacts_with_offline_source(self):
        before=self.source_hashes();result=self.run_export();root,parts=self.descriptors()
        self.assertEqual(result['partCount'],(self.meta['recordCount']+4)//5);self.assertEqual(root['globalBusinessRecordCount'],self.meta['recordCount'])
        self.assertEqual(root['originalSourceDenominator'],self.meta['coverage']['sourceCandidates']['denominator'])
        self.assertEqual(result['maxOutputBytes'],8*1024**3);self.assertEqual(root['ordinaryPartByteLimit'],1024**3)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:expected={r['id']:r for r in reader.iter_records()}
        found={};ids_hash=hashlib.sha256();data_hash=hashlib.sha256()
        for part in parts:
            path=self.output/part['path'];metadata=json.loads((path/'metadata.json').read_text(encoding='utf-8'));scope=metadata['partition']
            self.assertLessEqual(scope['recordCount'],5);self.assertEqual(metadata['recordCount'],scope['recordCount'])
            self.assertEqual(scope['globalRecordCount'],len(expected));self.assertEqual(scope['originalSourceDenominator'],root['originalSourceDenominator'])
            self.assertEqual(metadata['businessDigest'],self.meta['businessDigest'])
            for file in (path/'records').glob('*.json'):
                row=json.loads(file.read_text(encoding='utf-8'));self.assertNotIn(row['id'],found);self.assertEqual(row,expected[row['id']]);found[row['id']]=row
            self.assertEqual(set(scope['recordIds']),{json.loads(f.read_text(encoding='utf-8'))['id'] for f in (path/'records').glob('*.json')})
            self.assertTrue(json.loads((path/'mapping-loss.json').read_text(encoding='utf-8'))['allOriginalJsonRetained'])
            self.assertIn('wasDerivedFrom',(path/'lineage.ttl').read_text(encoding='utf-8'));self.assertIn('NodeShape',(path/'shapes.ttl').read_text(encoding='utf-8'))
            self.assertEqual(len(list((path/'rdf').glob('*.ttl'))),part['recordCount'])
            self.assertLessEqual(part['outputBytes'],1024**3)
        self.assertEqual(set(found),set(expected))
        for identity in sorted(found):
            raw=self.exporter._raw(found[identity]);encoded=identity.encode();ids_hash.update(len(encoded).to_bytes(8,'big'));ids_hash.update(encoded);data_hash.update(len(raw).to_bytes(8,'big'));data_hash.update(raw)
        self.assertEqual(root['globalRecordIdsDigest'],ids_hash.hexdigest());self.assertEqual(root['globalCanonicalRecordsDigest'],data_hash.hexdigest())
        self.assertEqual(result['outputBytes'],sum(f.stat().st_size for f in self.output.rglob('*') if f.is_file()))
        self.assertEqual(result['fileCount'],sum(f.is_file() for f in self.output.rglob('*')))
        self.assertEqual(before,self.source_hashes());self.assertEqual(root['businessCompleteness'],'PARTIAL');self.assertEqual(root['wholeBusinessRuleCoverage'],'UNKNOWN')
        for lang in self.module.LANGUAGES:self.assertTrue((self.output/'source'/lang/'index.html').is_file())
        for file in self.output.rglob('*'):
            if file.is_file():
                if os.name!='nt':self.assertEqual(file.stat().st_mode&0o077,0)
                raw=file.read_bytes()
                for token in (b'neutral-owner',b'private@example.test',b'Neutral Private Person',b'principalDigest'):
                    self.assertNotIn(token,raw)
        names={file.name for file in self.output.rglob('*')}
        self.assertFalse(names&{'pipeline.json','.resource-key','access.json','receipt.json','catalog.sqlite'})
    def test_source_rdf_bundle_and_business_rdf_have_separate_exact_denominators(self):
        self.run_export();root,parts=self.descriptors()
        with source.open_reader(self.workspace,self.sid) as reader:source_rows={r['id']:r for r in reader.iter_records()}
        bundle=self.output/'source-rdf';manifest=json.loads((bundle/'bundle.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['businessScope'],'explicit_source_only_bundle');self.assertFalse((bundle/'business').exists())
        self.assertEqual(root['rdfScopes']['sourceRecordCount'],len(source_rows));self.assertEqual(root['rdfScopes']['businessRecordCount'],self.meta['recordCount'])
        self.assertNotEqual(len(source_rows),self.meta['recordCount'])
        with closing(sqlite3.connect((bundle/'knowledge.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True)) as db, db:
            raw={identity:json.loads(payload) for identity,payload in db.execute('SELECT id,payload FROM records')}
        self.assertEqual(raw,source_rows)
        source_ids={unquote(match.group(1)) for match in re.finditer(r'^<urn:code-ontology:record:([^>]+)> a co:',(bundle/'ontology.ttl').read_text(encoding='utf-8'),re.M)}
        self.assertEqual(source_ids,set(source_rows));self.assertIn('prov:Activity',(bundle/'lineage.ttl').read_text(encoding='utf-8'));self.assertIn('sh:NodeShape',(bundle/'shapes.ttl').read_text(encoding='utf-8'))
        business_ids=set();business_payloads={}
        for part in parts:
            directory=self.output/part['path']
            for rdf in (directory/'rdf').glob('*.ttl'):
                text=rdf.read_text(encoding='utf-8')
                matches=re.findall(r'^<urn:companion:business:record:[0-9a-f]{64}> <'+re.escape(self.exporter.NS)+'id> (.+) \.$',text,re.M)
                self.assertEqual(len(matches),1);identity=json.loads(matches[0]);self.assertNotIn(identity,business_ids);business_ids.add(identity)
                payload=re.findall(r'^<urn:companion:business:record:[0-9a-f]{64}> <'+re.escape(self.exporter.NS)+'canonicalJson> (.+) \.$',text,re.M)
                self.assertEqual(len(payload),1);business_payloads[identity]=json.loads(json.loads(payload[0]))
                self.assertIn(self.exporter.PROV+'wasDerivedFrom',text)
            shape=(directory/'shapes.ttl').read_text(encoding='utf-8')
            self.assertIn(self.exporter.SH+'targetClass',shape);self.assertIn(self.exporter.SH+'minCount',shape);self.assertIn(self.exporter.SH+'maxCount',shape)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:expected={r['id']:r for r in reader.iter_records()}
        self.assertEqual(business_ids,set(expected));self.assertEqual(business_payloads,expected)
        # Full SHACL-engine and browser execution remain explicitly NOT_RUN.
        self.assertEqual(root['shapeValidation'],'NOT_RUN')

    def test_five_language_links_and_cross_part_rdf_reference_are_complete(self):
        self.assert_cross_part_links_and_rdf()

    def test_cross_part_links_with_crlf_source_have_exact_endpoint_coverage(self):
        fixture=type(self)('runTest');fixture.source_newline=b'\r\n'
        try:
            fixture.setUp();fixture.assert_cross_part_links_and_rdf()
        finally:fixture.doCleanups()

    def assert_cross_part_links_and_rdf(self):
        self.run_export();_,parts=self.descriptors();documents={}
        for file in self.output.rglob('*.html'):documents[file]=Page(file.read_text(encoding='utf-8'))
        for file,page in documents.items():
            for href in page.links:
                parsed=urlsplit(href);self.assertFalse(parsed.scheme or parsed.netloc,(file,href))
                target=(file.parent/unquote(parsed.path)).resolve() if parsed.path else file
                self.assertTrue(target.is_file(),(file,href))
                if parsed.fragment:
                    if target.suffix=='.html':self.assertIn(unquote(parsed.fragment),documents[target].ids,(file,href))
        # Source line endings change source identities and their sorted part
        # positions. Both endpoints may cross; count the actual record routes,
        # rather than assuming that only the object crosses on every host.
        routes={}
        for part in parts:
            path=self.output/part['path']
            scope=json.loads((path/'metadata.json').read_text(encoding='utf-8'))['partition']
            for identity in scope['recordIds']:
                self.assertNotIn(identity,routes);routes[identity]=path
        relation_key=self.exporter._filename(self.relation_id);path=routes[self.relation_id]
        relation=json.loads((path/'records'/(relation_key+'.json')).read_text(encoding='utf-8'))
        external=[relation[key] for key in ('subject','object') if routes[relation[key]]!=path]
        self.assertIn(self.object_id,external)
        cross=[]
        for lang in self.module.LANGUAGES:
            page=path/lang/'records'/(relation_key+'.html')
            links=[href for href in documents[page].links if '/lookup/' in href];cross.extend(links)
            self.assertEqual(len(links),len(external))
            self.assertEqual({unquote(urlsplit(href).fragment) for href in links},{'r-'+self.exporter._filename(identity) for identity in external})
            for identity in external:
                key=self.exporter._filename(identity);href=next(href for href in links if unquote(urlsplit(href).fragment)=='r-'+key)
                lookup=(page.parent/unquote(urlsplit(href).path)).resolve()
                target=routes[identity]/lang/'records'/(key+'.html')
                resolved={(lookup.parent/unquote(urlsplit(value).path)).resolve() for value in documents[lookup].links if urlsplit(value).path}
                self.assertIn(target,resolved)
        rdf=(path/'rdf'/(relation_key+'.ttl')).read_text(encoding='utf-8')
        self.assertIn(self.exporter._triple(self.exporter._iri(self.relation_id),self.exporter.NS+'object',self.exporter._iri(self.object_id)),rdf)
        self.assertEqual(len(cross),len(external)*len(self.module.LANGUAGES))
    def blocked(self,**kwargs):
        with self.assertRaises(self.module.PartitionedExportError) as caught:self.run_export(**kwargs)
        self.assertFalse(self.output.exists());report=caught.exception.report
        self.assertEqual(report['selectedBusinessRecords'],self.meta['recordCount'])
        self.assertEqual(report['originalSourceDenominator'],self.meta['coverage']['sourceCandidates']['denominator'])
        self.assertEqual(report['status'],'BLOCKED');self.assertLessEqual(report['processedBusinessRecords'],report['selectedBusinessRecords'])
        progress=json.loads(Path(caught.exception.progressReceipt).read_text(encoding='utf-8'));self.assertEqual(progress['status'],'BLOCKED')
        return caught.exception
    def test_cancel_blocks_whole_root_and_preserves_source(self):
        calls=[0];before=self.source_hashes()
        def cancel():calls[0]+=1;return calls[0]>=5
        error=self.blocked(cancel=cancel);self.assertEqual(error.code,'partitioned_cancelled');self.assertEqual(before,self.source_hashes())
    def test_global_budget_failure_has_original_counts_and_no_partial_root(self):
        error=self.blocked(max_output_bytes=50000);self.assertEqual(error.report['processedBusinessRecords'],0)
        self.assertIn(error.code,('partitioned_total_budget','html_output_budget_exceeded','html_spool_budget_exceeded'))
        if error.code.startswith('html_'):
            self.assertEqual(error.report['sourceComponent']['status'],'INCOMPLETE')
            self.assertIn('sourceRecordDenominator',error.report['sourceComponent'])
    def test_bounded_retry_keeps_same_start_and_exports_every_id(self):
        original=self.exporter.export_business;calls=[]
        def limited(reader,*args,**kwargs):
            calls.append((reader.metadata['partition']['index'],reader.metadata['partition']['recordIds'][0],reader.metadata['recordCount']))
            if reader.metadata['recordCount']>4:raise self.exporter.BusinessExportError('export_total_budget')
            return original(reader,*args,**kwargs)
        with patch.object(self.exporter,'export_business',side_effect=limited):result=self.run_export(part_records=8)
        root,parts=self.descriptors();self.assertEqual(calls[0][1],calls[1][1]);self.assertEqual(calls[0][2:],(8,));self.assertEqual(calls[1][2:],(4,))
        self.assertEqual(parts[0]['attempts'][0]['status'],'FAILED');self.assertEqual(parts[0]['attempts'][1]['status'],'EXPORTED')
        self.assertEqual(sum(p['recordCount'] for p in parts),self.meta['recordCount'])
        recovered_part_records=calls[1][2]
        self.assertEqual(result['partCount'],(self.meta['recordCount']+recovered_part_records-1)//recovered_part_records)
    def test_actual_byte_budget_halves_parts_without_losing_records(self):
        result=self.run_export(part_records=8,part_max_bytes=180000)
        root,parts=self.descriptors()
        self.assertEqual([a['records'] for a in parts[0]['attempts']],[8,4,2,1])
        self.assertEqual(parts[0]['attempts'][-1]['status'],'EXPORTED')
        self.assertTrue(all(a['budgetBinding']=='part_cap' for a in parts[0]['attempts']))
        self.assertEqual([a['retryDecision'] for a in parts[0]['attempts']],['halve_part_records']*3+['not_needed'])
        self.assertTrue(all(part['outputBytes']<=180000 for part in parts))
        self.assertEqual(sum(part['recordCount'] for part in parts),self.meta['recordCount'])
        self.assertEqual(root['processedBusinessRecordCount'],root['globalBusinessRecordCount'])
        self.assertEqual(result['recordCount'],self.meta['recordCount'])

    def test_single_record_unfit_keeps_failed_retry_list_and_blocks(self):
        original=self.exporter.export_business
        def limited(reader,*args,**kwargs):raise self.exporter.BusinessExportError('export_total_budget')
        with patch.object(self.exporter,'export_business',side_effect=limited):error=self.blocked(part_records=8)
        self.assertEqual([a['records'] for a in error.report['attempts']],[8,4,2,1])
        receipt=Path(error.progressReceipt).with_name('part-00000001-attempts.json')
        self.assertEqual(len(json.loads(receipt.read_text(encoding='utf-8'))['attempts']),4)
    @unittest.skipIf(os.name=='nt','POSIX mode and atomic-rename observation')
    def test_outer_root_mode_change_is_rejected_before_any_promotion(self):
        original=self.module._SetBoundary.validate;calls=[];promotions=[]
        def changed(bound,*args,**kwargs):
            calls.append(1)
            if len(calls)==2:os.chmod(bound.stage,0o755)
            return original(bound,*args,**kwargs)
        promote=self.exporter._promote
        def observed(bound,output):
            if output==self.output:promotions.append(output)
            return promote(bound,output)
        with patch.object(self.module._SetBoundary,'validate',new=changed),patch.object(self.exporter,'_promote',new=observed):error=self.blocked()
        self.assertEqual(len(calls),2,'the final-validation mutation must actually run')
        self.assertEqual(error.code,'export_directory_permissions_changed');self.assertEqual(promotions,[])
        self.assertEqual(error.report['processedBusinessRecords'],self.meta['recordCount'])

    @unittest.skipIf(os.name=='nt','POSIX root fd/path and rename syscall observation')
    def test_outer_mode_change_after_validation_cannot_reach_rename_syscall(self):
        promote=self.exporter._promote;mutated=[];syscalls=[];library=self.exporter.ctypes.CDLL
        def observed(bound,output):
            if output==self.output:os.chmod(bound.stage,0o755);mutated.append(True)
            return promote(bound,output)
        # Inner business publications still use the real primitive. Once the
        # outer mutation runs, any later library open would precede a rename.
        def checked(*args,**kwargs):
            if mutated:syscalls.append(True)
            return library(*args,**kwargs)
        with patch.object(self.exporter,'_promote',new=observed),patch.object(self.exporter.ctypes,'CDLL',new=checked):error=self.blocked()
        self.assertEqual(mutated,[True]);self.assertEqual(syscalls,[]);self.assertEqual(error.code,'export_directory_permissions_changed')

    def test_global_remaining_binding_never_retries_a_real_part_byte_failure(self):
        original=self.exporter.export_business;calls=[]
        def observed(reader,*args,**kwargs):
            calls.append((reader.metadata['recordCount'],kwargs['max_output_bytes']))
            return original(reader,*args,**kwargs)
        with patch.object(self.exporter,'export_business',new=observed):error=self.blocked(part_records=16,max_output_bytes=1400000)
        self.assertEqual(error.code,'partitioned_total_budget');self.assertEqual(len(calls),1)
        self.assertLess(calls[0][1],self.module.PART_BYTES);self.assertEqual(error.report['processedBusinessRecords'],0)
        attempt=error.report['attempts'][0];self.assertEqual(attempt['budgetBinding'],'global_remaining')
        self.assertEqual(attempt['retryDecision'],'blocked_global_total');self.assertEqual(attempt['records'],min(16,self.meta['recordCount']))
        self.assertEqual(error.report['pins'],{k:self.meta[k] for k in self.exporter.PIN_KEYS})
        self.assertTrue(all(error.report['sourceComponent'].get(k)==error.report['sourceRdfComponent'].get(k) for k in ('recordCount',)))

    def test_global_2200000_byte_fixture_keeps_all111_selected_and_never_halves(self):
        sem=self.store._semantics
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            anchor=reader.get_record(self.base_ids[0])['sourceAnchors']
        count=111-len(self.base_ids)
        concepts=[{'namespace':'review','domain':'catalog','kind':'business_object_type','conceptKey':'neutral-'+str(i),
            'label':'Neutral item','sourceAnchors':anchor,'facets':{}} for i in range(count)]
        review={'schemaVersion':1,'sourcePins':{k:self.meta[k] for k in sem.PIN_KEYS},'concepts':concepts}
        self.meta=self.store.review(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'],review)
        self.assertEqual(self.meta['recordCount'],111)
        original=self.exporter.export_business;calls=[]
        def observed(reader,*args,**kwargs):
            calls.append((reader.metadata['partition']['index'],reader.metadata['recordCount'],kwargs['max_output_bytes']))
            return original(reader,*args,**kwargs)
        with patch.object(self.exporter,'export_business',new=observed):error=self.blocked(part_records=16,max_output_bytes=2200000)
        self.assertEqual(error.code,'partitioned_total_budget');self.assertTrue(calls)
        self.assertEqual(len(calls),len({index for index,_,_ in calls}),'a globally limited part must not be retried')
        self.assertTrue(all(count==16 for _,count,_ in calls));self.assertEqual(len(error.report['attempts']),1)
        self.assertIn(error.report['attempts'][0]['retryDecision'],('blocked_global_total','not_needed'))
        # A child may finish privately before adoption/index overhead exhausts
        # the aggregate budget. That is still a global failure with no retry.
        if error.report['attempts'][0]['retryDecision']=='not_needed':self.assertEqual(error.report['attempts'][0]['status'],'EXPORTED')
        self.assertEqual(error.report['selectedBusinessRecords'],111)
        self.assertEqual(error.report['selectedSourceRecords'],len(self.base_ids))
        self.assertEqual(error.report['processedBusinessRecords'],16*(len(calls)-1))
        self.assertEqual(error.report['spooledRecords'],111)
        self.assertEqual(error.report['sourceComponent']['recordCount'],len(self.base_ids))
        self.assertEqual(error.report['sourceRdfComponent']['recordCount'],len(self.base_ids))
        self.assertEqual(error.report['pins'],{k:self.meta[k] for k in self.exporter.PIN_KEYS})

    def test_business_handoff_rejects_post_seal_rdf_metadata_mapping_and_manifest_changes(self):
        original=self.exporter.export_business
        for kind in ('rdf','metadata','mapping','manifest','missing','extra','returned'):
            with self.subTest(kind=kind):
                mutations=[]
                def mutate(reader,output,*args,**kwargs):
                    result=original(reader,output,*args,**kwargs);output=Path(output)
                    if kind=='rdf':
                        file=next((output/'rdf').glob('*.ttl'));file.write_bytes(file.read_bytes()+b'\n# neutral post-seal comment\n')
                    elif kind=='missing':next((output/'rdf').glob('*.ttl')).unlink()
                    elif kind=='extra':
                        file=output/'extra.txt';file.write_bytes(b'neutral');file.chmod(0o600)
                    elif kind=='returned':result['files']['style.css']['sha256']='0'*64
                    else:
                        file=output/({'metadata':'metadata.json','mapping':'mapping-loss.json','manifest':'business-export.json'}[kind]);value=json.loads(file.read_text(encoding='utf-8'))
                        if kind=='metadata':value['partition']['globalRecordCount']=0
                        elif kind=='mapping':value['records'].pop()
                        else:value['recordCount']=0
                        file.write_text(json.dumps(value))
                    mutations.append(True);return result
                with patch.object(self.exporter,'export_business',new=mutate):error=self.blocked()
                self.assertEqual(mutations,[True]);self.assertIn(error.code,('partitioned_child_artifact_changed','partitioned_child_artifact_set_changed','partitioned_child_attestation_mismatch'))
                self.assertEqual(error.report['processedBusinessRecords'],0);self.assertEqual(error.report['targetComponent'],'business_part')

    def test_source_html_and_rdf_handoffs_preserve_original_producer_bytes(self):
        for component in ('html','rdf'):
            original=pipeline_html.render_pipeline if component=='html' else pipeline_export.export_bundle
            for kind in ('changed','missing','extra','manifest'):
                if component=='html' and kind=='manifest':continue
                with self.subTest(component=component,kind=kind):
                    mutations=[]
                    def mutate(workspace,sid,output,**kwargs):
                        result=original(workspace,sid,output,**kwargs);output=Path(output)
                        file=output/('en/index.html' if component=='html' else 'ontology.ttl')
                        if kind=='changed':file.write_bytes(file.read_bytes()+b'\n')
                        elif kind=='missing':file.unlink()
                        elif kind=='extra':
                            file=output/'extra.txt';file.write_bytes(b'neutral');file.chmod(0o600)
                        else:
                            file=output/'bundle.json';value=json.loads(file.read_text(encoding='utf-8'));value['recordCount']=0;file.write_text(json.dumps(value))
                        mutations.append(True);return result
                    error=self.blocked(**{'source_render' if component=='html' else 'source_export':mutate})
                    self.assertEqual(mutations,[True]);self.assertIn(error.code,('partitioned_child_artifact_changed','partitioned_child_artifact_set_changed'))
                    self.assertEqual(error.report['processedBusinessRecords'],0)

    def test_catalog_delete_or_wrong_part_after_last_raw_read_blocks_lookup(self):
        original=self.module._SetBoundary.read_record
        for kind in ('delete','part','expected','schema'):
            with self.subTest(kind=kind):
                reads=[];mutations=[]
                def mutate(bound,name,**kwargs):
                    raw=original(bound,name,**kwargs)
                    if name.startswith('business/') and '/records/' in name and name.endswith('.json'):
                        reads.append(name)
                        if len(reads)==self.meta['recordCount']:
                            mutations.append(True)
                            if kind=='delete':bound.db.execute('DELETE FROM records WHERE id=?',(self.object_id,))
                            elif kind=='part':bound.db.execute('UPDATE records SET part=999 WHERE id=?',(self.object_id,))
                            elif kind=='expected':bound.db.execute('DELETE FROM expected WHERE path LIKE ?',('%/records/%',))
                            else:bound.db.execute('DROP TABLE records')
                    return raw
                with patch.object(self.module._SetBoundary,'read_record',new=mutate):error=self.blocked()
                self.assertEqual(mutations,[True]);self.assertEqual(len(reads),self.meta['recordCount'])
                self.assertEqual(error.code,'partitioned_catalog_changed');self.assertEqual(error.report['processedBusinessRecords'],self.meta['recordCount'])
                self.assertEqual(error.report['spooledRecords'],self.meta['recordCount'])

    def test_native_profile_replacement_after_final_validation_blocks_before_promotion(self):
        from windows_fixture import protect_private_path
        profile_file=self.root/'owned-synthetic-profile.json';source._atomic(profile_file,self.profile);protect_private_path(profile_file)
        native_env=patch.dict(os.environ,{companion.privacy_guard.PROFILE_ENV:str(profile_file)});native_env.start();self.addCleanup(native_env.stop)
        for item in reversed(self.profile_patches):item.stop()
        replacement=companion.privacy_guard.build_profile(['Item'],['new-neutral-private@example.test'],key=b'w'*32)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            row=reader.get_record(self.object_id)
        with self.assertRaises(companion.privacy_guard.PrivacyError):companion.privacy_guard.ensure_public_safe(row,profile=replacement,require_profile=True)
        original=self.module._SetBoundary.validate;calls=[];promotions=[];before=self.source_hashes();promote=self.exporter._promote
        def changed(bound,*args,**kwargs):
            result=original(bound,*args,**kwargs);calls.append(True)
            if len(calls)==2:source._atomic(profile_file,replacement)
            return result
        def observe(bound,output):
            if output==self.output:promotions.append(True)
            return promote(bound,output)
        with patch.dict(os.environ,{companion.privacy_guard.PROFILE_ENV:str(profile_file)}),patch.object(self.module._SetBoundary,'validate',new=changed),patch.object(self.exporter,'_promote',new=observe):
            error=self.blocked()
            self.assertEqual(companion.privacy_guard.load_profile(required=True),replacement)
        self.assertEqual(len(calls),2,'both real complete validations must finish before the native profile replacement')
        self.assertEqual(promotions,[]);self.assertEqual(error.code,'partitioned_privacy_profile_changed')
        self.assertEqual(error.report['processedBusinessRecords'],self.meta['recordCount']);self.assertEqual(before,self.source_hashes())

    def after_final_validation(self,change,**kwargs):
        original=self.module._SetBoundary.validate;calls=[];promotions=[];promote=self.exporter._promote
        def changed(bound,*args,**kw):
            result=original(bound,*args,**kw);calls.append(True)
            if len(calls)==2:change()
            return result
        def observe(bound,output):
            if output==self.output:promotions.append(True)
            return promote(bound,output)
        with patch.object(self.module._SetBoundary,'validate',new=changed),patch.object(self.exporter,'_promote',new=observe):error=self.blocked(**kwargs)
        self.assertEqual(len(calls),2);self.assertEqual(promotions,[])
        self.assertEqual(error.report['processedBusinessRecords'],self.meta['recordCount'])
        return error
    def test_cancel_after_final_validation_is_observed_before_promotion(self):
        stopped=[];error=self.after_final_validation(lambda:stopped.append(True),cancel=lambda:bool(stopped))
        self.assertEqual(stopped,[True]);self.assertEqual(error.code,'partitioned_cancelled')
    def test_owned_acl_file_revocation_after_final_validation_is_observed(self):
        def change():
            file=self.workspace/'access.json';policy=json.loads(file.read_text(encoding='utf-8'));policy['revision']+=1
            policy['principals']['neutral-owner']['actions'].remove('export_html');source._atomic(file,policy)
        error=self.after_final_validation(change)
        self.assertEqual(error.code,'partitioned_access_denied')
    def test_source_binding_change_after_final_validation_is_observed(self):
        def change():
            file=next((self.workspace/'snapshots'/self.sid).glob('*.sqlite'))
            with file.open('ab') as handle:handle.write(b'neutral-after-validation')
        error=self.after_final_validation(change)
        self.assertEqual(error.code,'artifact_integrity_failed')

    def test_missing_producer_attestation_cannot_be_laundered_by_adoption(self):
        original=pipeline_html.render_pipeline;called=[]
        def unobserved(*args,**kwargs):
            kwargs.pop('artifact_observer');called.append(True);return original(*args,**kwargs)
        error=self.blocked(source_render=unobserved)
        self.assertEqual(called,[True]);self.assertEqual(error.code,'partitioned_child_attestation_missing')

    def test_acl_revocation_mid_export_blocks_full_set(self):
        calls=[0]
        def revoke():
            calls[0]+=1
            if calls[0]==5:acl.update_access(self.workspace,'neutral-owner',sorted(acl.ACTIONS-{'export_html'}),['*'])
            return False
        self.assertIn(self.blocked(cancel=revoke).code,('partitioned_access_denied','partitioned_acl_revision_changed','authorization_changed'))
    def test_changed_sealed_source_hash_blocks_full_set(self):
        calls=[0]
        def mutate():
            calls[0]+=1
            if calls[0]==5:
                file=next((self.workspace/'snapshots'/self.sid).glob('*.sqlite'))
                with file.open('ab') as handle:handle.write(b'x')
            return False
        self.assertIn(self.blocked(cancel=mutate).code,('partitioned_source_snapshot_changed','pinned_snapshot_changed'))
    @unittest.skipIf(os.name=='nt','POSIX directory-fd parent race; Windows handle tests remain separate')
    def test_outer_parent_replacement_never_publishes_to_foreign_directory(self):
        original=self.exporter._promote;moved=self.root/'moved'
        def race(bound,output):
            if output==self.output:
                self.destination.rename(moved);self.destination.mkdir();(self.destination/'foreign.txt').write_bytes(b'foreign')
            return original(bound,output)
        with patch.object(self.exporter,'_promote',side_effect=race):self.blocked()
        self.assertEqual((self.destination/'foreign.txt').read_bytes(),b'foreign');self.assertFalse((moved/'output').exists())
    @unittest.skipIf(os.name=='nt','POSIX fd publication and symlink redirect')
    def test_outer_parent_symlink_redirect_leaves_foreign_tree_untouched(self):
        original=self.exporter._promote;moved=self.root/'moved';foreign=self.root/'foreign';foreign.mkdir();(foreign/'sentinel').write_bytes(b'foreign')
        def race(bound,output):
            if output==self.output:self.destination.rename(moved);self.destination.symlink_to(foreign,target_is_directory=True)
            return original(bound,output)
        with patch.object(self.exporter,'_promote',side_effect=race):self.blocked()
        self.assertEqual((foreign/'sentinel').read_bytes(),b'foreign');self.assertFalse((foreign/'output').exists());self.assertFalse((moved/'output').exists())
    @unittest.skipIf(os.name=='nt','POSIX descriptor initialization cleanup')
    def test_parent_change_during_outer_stage_initialization_closes_descriptors(self):
        original=self.exporter._BoundArtifacts.create_stage;captured=[];moved=self.root/'moved'
        def fail(bound):
            result=original(bound);captured.extend([bound.parent_fd,bound.stage_fd])
            self.destination.rename(moved);self.destination.mkdir()
            raise self.exporter.BusinessExportError('export_parent_changed')
        with patch.object(self.exporter._BoundArtifacts,'create_stage',new=fail):error=self.blocked()
        self.assertEqual(error.code,'export_parent_changed')
        self.assertEqual(len(captured),2,'the finite initialization-race callback must run')
        self.assertTrue(moved.is_dir(),'the original parent must actually be renamed')
        for descriptor in captured:
            with self.assertRaises(OSError):os.fstat(descriptor)
        self.assertFalse(list(moved.iterdir()))

    def test_existing_root_is_never_overwritten(self):
        self.output.mkdir();sentinel=self.output/'sentinel';sentinel.write_bytes(b'prior')
        with self.assertRaises(self.module.PartitionedExportError) as caught:self.run_export()
        self.assertEqual(sentinel.read_bytes(),b'prior');self.assertEqual(caught.exception.report['selectedBusinessRecords'],self.meta['recordCount'])
    def test_atlas_cannot_disable_business_without_explicit_internal_scope(self):
        with self.assertRaisesRegex(pipeline_html.PipelineHtmlError,'html_export_scope_invalid'):
            pipeline_html.render_pipeline(self.workspace,self.sid,self.root/'disabled',include_business=False)
        self.assertEqual(pipeline_html.DEFAULT_OUTPUT_BYTES,1024**3)
        # The existing positive-budget API remains available. Only the explicit
        # export-set caller passes the remaining configured aggregate capacity.
        import inspect
        self.assertEqual(inspect.signature(pipeline_html.render_pipeline).parameters['max_output_bytes'].default,1024**3)
        self.assertIs(inspect.signature(pipeline_export.export_bundle).parameters['include_business'].default,True)

    def test_source_atlas_rendered_once_with_maps_and_business_disabled_only_here(self):
        with patch.object(pipeline_html,'render_pipeline',wraps=pipeline_html.render_pipeline) as render,patch.object(pipeline_export,'export_bundle',wraps=pipeline_export.export_bundle) as source_export:self.run_export()
        self.assertEqual(source_export.call_count,1);self.assertFalse(source_export.call_args.kwargs['include_business'])
        self.assertGreater(source_export.call_args.kwargs['max_output_bytes'],1024**3)
        self.assertLessEqual(source_export.call_args.kwargs['max_output_bytes'],8*1024**3)
        self.assertEqual(render.call_count,1);self.assertTrue(render.call_args.kwargs['include_maps']);self.assertFalse(render.call_args.kwargs['include_business'])
        self.assertGreater(render.call_args.kwargs['max_output_bytes'],1024**3)
        self.assertLessEqual(render.call_args.kwargs['max_output_bytes'],8*1024**3)
        with patch.object(pipeline_html,'render_pipeline',return_value={'ordinary':True}) as render:
            self.assertEqual(access._render(self.workspace,self.sid,self.root/'ordinary','ko'),{'ordinary':True})
            self.assertNotIn('include_business',render.call_args.kwargs)
    def test_public_cli_flag_executes_full_set_without_expert_options(self):
        reports=[]
        argv=['pipeline-html','--workspace',str(self.workspace),'--snapshot',self.sid,'--output',str(self.output),'--language','ja','--partitioned']
        with patch.object(companion,'_json_print',side_effect=reports.append):code=companion.main(argv)
        self.assertEqual(code,0);self.assertEqual(len(reports),1);self.assertEqual(reports[0]['status'],'exported')
        self.assertEqual(reports[0]['recordCount'],self.meta['recordCount']);self.assertEqual(reports[0]['partCount'],1)
        self.assertTrue((self.output/'ja'/'index.html').is_file());self.assertTrue((self.output/'source-rdf'/'ontology.ttl').is_file())
        self.assertTrue((self.output/'business'/'part-00000001'/'ja'/'index.html').is_file())
    def test_public_cli_blocked_report_returns_nonzero_without_ordinary_change(self):
        reports=[];error=self.module.PartitionedExportError('partitioned_total_budget',{'status':'BLOCKED','selectedBusinessRecords':self.meta['recordCount'],'processedBusinessRecords':0})
        argv=['pipeline-html','--workspace',str(self.workspace),'--snapshot',self.sid,'--output',str(self.output),'--partitioned']
        with patch.object(self.module,'export_partitioned',side_effect=error),patch.object(companion,'_json_print',side_effect=reports.append):code=companion.main(argv)
        self.assertEqual(code,2);self.assertEqual(reports[0]['status'],'BLOCKED');self.assertEqual(reports[0]['selectedBusinessRecords'],self.meta['recordCount'])
        self.assertFalse(self.output.exists())

    def test_ordinary_caps_and_closed_internal_links_are_not_relaxed(self):
        self.assertEqual(self.exporter.MAX_RECORDS,10000);self.assertEqual(self.exporter.MAX_OUTPUT_BYTES,1024**3)
        with self.assertRaises(self.module.PartitionedExportError):self.run_export(part_records=10001)
        with self.assertRaises(self.module.PartitionedExportError):self.run_export(part_max_bytes=1024**3+1)
        with self.assertRaises(self.module.PartitionedExportError):self.run_export(max_output_bytes=8*1024**3+1)
        class Empty:
            metadata={**{k:self.meta[k] for k in self.exporter.PIN_KEYS},'recordCount':10001}
        with self.assertRaises(self.exporter.BusinessExportError) as caught:
            self.exporter.export_business(Empty(),self.root/'ordinary-business',pins={k:self.meta[k] for k in self.exporter.PIN_KEYS},profile=self.profile,
                authorize=lambda action:{'decision':'allow','revision':1},publication_guard=lambda:companion._snapshot_write_lock(self.workspace),check_profile=lambda:True,check_snapshot=lambda:True)
        self.assertEqual(caught.exception.code,'export_record_denominator_invalid')

if __name__=='__main__':unittest.main()
