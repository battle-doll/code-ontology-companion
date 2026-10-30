"""Neutral whole-inventory storage, immutable paging and bounded failure tests."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import companion
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as source
import business_semantics as sem
import business_store as store


class BusinessPartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory();cls.fixture_root=Path(cls.fixture.name)
        cls.profile=companion.privacy_guard.build_profile([],[],key=b'p'*32)
        cls.profile_patch=patch.object(companion.privacy_guard,'load_profile',return_value=cls.profile);cls.profile_patch.start()
        cls.env=patch.dict(os.environ,{acl.PRINCIPAL_ENV:'partition-owner','CODE_ONTOLOGY_HOME':str(cls.fixture_root/'registry')});cls.env.start()
        repo=cls.fixture_root/'neutral-source';repo.mkdir()
        for batch in range(9):
            (repo/('items%d.py'%batch)).write_text(''.join('class Item%d:\n    value: int = %d\n    def eligible(self, active: bool) -> bool:\n        return active\n'%(i,i) for i in range(batch*300,(batch+1)*300)))
        cls.base=cls.fixture_root/'base'
        cls.sid=source.initialize(repo,cls.base,prepare_workspace=acl.initialize_access)['snapshotId']
        cls.store,cls.query,_=access._business()
        cls.initial=cls.store.build(cls.base,cls.sid)
        if cls.initial['recordCount']<=10000:raise AssertionError('fixture must exceed the old total cap')
        repo.rename(cls.fixture_root/'source-offline')
    @classmethod
    def tearDownClass(cls):
        cls.env.stop();cls.profile_patch.stop();cls.fixture.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.workspace=self.root/'knowledge';shutil.copytree(self.base,self.workspace)
        self.store,self.query,_=access._business();self.meta=copy.deepcopy(self.initial)
    def reader(self,meta=None):
        meta=meta or self.meta
        return self.store.open_reader(self.workspace,self.sid,meta['businessSnapshotId'],meta['businessDigest'])
    def source_hashes(self):
        return {str(p.relative_to(self.workspace)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.workspace/'snapshots').rglob('*') if p.is_file()}
    def test_whole_inventory_last_page_exact_ids_and_bounded_shards(self):
        meta=self.meta;coverage=meta['coverage']
        self.assertEqual(coverage['denominator'],meta['recordCount']+coverage['unsupported']);self.assertEqual(coverage['omitted'],0)
        self.assertEqual(coverage['unsupported'],0)
        with self.reader() as reader:
            self.assertEqual(reader.coverage(limit=100)['total'],0)
        self.assertEqual(coverage['storageCompleteness'],'COMPLETE');self.assertEqual(meta['businessCompletion'],'PARTIAL')
        with self.reader() as reader:
            self.assertFalse(hasattr(reader,'rows'));self.assertFalse(hasattr(reader,'index'))
            ids=[r['id'] for r in reader.iter_records(page_size=200)]
            self.assertEqual(len(ids),len(set(ids)));self.assertEqual(ids,sorted(ids))
            page=reader.query(offset=len(ids)-3,limit=3)
            self.assertEqual([r['id'] for r in page['records']],ids[-3:]);self.assertIsNone(page['nextOffset'])
            exact=reader.query(record_ids=[ids[0],ids[-1]],limit=2)
            self.assertEqual([r['id'] for r in exact['records']],[ids[0],ids[-1]])
            self.assertEqual(reader.get_record(ids[-1])['id'],ids[-1])
        shards=meta['storage']['shards'];self.assertGreater(len(shards),1)
        self.assertTrue(all(s['count']<=10000 and s['bytes']<=64*1024*1024 for s in shards))
    def test_registered_mcp_last_page_with_source_offline(self):
        access.register(str(self.workspace));wid=access.config(self.workspace)['workspaceId']
        args={'workspace_id':wid,'snapshot_id':self.sid,'knowledge_view':'business',
              'business_snapshot_id':self.meta['businessSnapshotId'],'business_digest':self.meta['businessDigest'],
              'offset':self.meta['recordCount']-1,'limit':1}
        page=access.dispatch('ontology_pipeline_search',args)['data']
        self.assertEqual(page['returned'],1);self.assertIsNone(page['nextOffset'])
        self.assertEqual(page['total'],self.meta['recordCount']);self.assertEqual(page['globalCompleteness'],'UNKNOWN')
    def review_manifest(self):
        with self.reader() as reader:row=next(reader.iter_records())
        a={'namespace':'review','domain':'catalog','kind':'business_object_type','conceptKey':'one',
           'label':'Item','sourceAnchors':row['sourceAnchors'],'facets':{}}
        b=copy.deepcopy(a);b['conceptKey']='two'
        relation=copy.deepcopy(a);relation.update(kind='business_relation',conceptKey='link',
            subject=sem.concept_id('review','catalog','business_object_type','one'),
            object=sem.concept_id('review','catalog','business_object_type','two'),role='contains')
        return {'schemaVersion':1,'sourcePins':{k:self.meta[k] for k in sem.PIN_KEYS},'concepts':[a,b,relation]},relation
    def test_review_revoke_preserve_whole_base_denominator_and_independent_receipt(self):
        before=self.source_hashes();manifest,relation=self.review_manifest()
        reviewed=self.store.review(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'],manifest)
        self.assertEqual(reviewed['recordCount'],self.meta['recordCount']+3)
        self.assertEqual(reviewed['coverage']['sourceCandidates']['denominator'],self.meta['coverage']['denominator'])
        with self.reader(reviewed) as reader:
            sibling_receipt=reader.get_record(relation['object'])['approvalReceiptId']
            self.assertEqual(sum(r['namespace']=='source' for r in reader.iter_records()),self.meta['recordCount'])
        revoked=self.store.revoke(self.workspace,self.sid,reviewed['businessSnapshotId'],reviewed['businessDigest'],[relation['subject']])
        with self.reader(revoked) as reader:
            self.assertEqual(reader.get_record(relation['subject'])['businessApproval'],'revoked')
            self.assertEqual(reader.get_record(relation['object'])['approvalReceiptId'],sibling_receipt)
            self.assertEqual(sum(r['namespace']=='source' for r in reader.iter_records()),self.meta['recordCount'])
        self.assertEqual(revoked['coverage']['sourceCandidates']['denominator'],self.meta['coverage']['denominator'])
        self.assertEqual(before,self.source_hashes())
    def test_cancellation_keeps_pointer_source_and_original_denominator(self):
        before=self.source_hashes();calls=[0]
        def cancel():calls[0]+=1;return calls[0]>25
        with self.assertRaisesRegex(self.store.BusinessStoreError,'cancelled'):
            self.store.build(self.workspace,self.sid,cancel=cancel)
        self.assertEqual(self.store.status(self.workspace,self.sid)['businessDigest'],self.meta['businessDigest'])
        attempt=json.loads((self.workspace/'business-last-attempt.json').read_text())
        self.assertEqual(attempt['coverage']['denominator'],self.meta['coverage']['denominator'])
        self.assertEqual(attempt['coverage']['storageCompleteness'],'UNPUBLISHED')
        self.assertEqual(attempt['coverage']['omitted']+attempt['coverage']['processed'],self.meta['coverage']['denominator'])
        self.assertEqual(before,self.source_hashes())
    def test_output_boundary_leaves_old_pointer(self):
        original=source.SnapshotReader.__enter__
        def small(reader):
            result=original(reader);reader.config=copy.deepcopy(reader.config);reader.config['budgets']['max_output_bytes']=1024
            return result
        with patch.object(source.SnapshotReader,'__enter__',small),self.assertRaisesRegex(self.store.BusinessStoreError,'output_budget'):
            self.store.build(self.workspace,self.sid)
        self.assertEqual(self.store.status(self.workspace,self.sid)['businessDigest'],self.meta['businessDigest'])
    def test_corrupted_later_shard_fails_closed(self):
        directory=self.workspace/'business-snapshots'/self.meta['businessSnapshotId']
        shard=sorted(directory.glob('records-*.sqlite'))[-1]
        with self.assertRaisesRegex(self.store.BusinessStoreError,'changed'):
            with self.reader() as reader:
                with shard.open('ab') as handle:handle.write(b'x')
                reader.get_record('business:'+'f'*64)
        # __exit__ also checks immutable identities.
    def test_revoked_reader_and_publication_race_fail_closed(self):
        original=source._atomic;changed=[False]
        def atomic(path,value):
            result=original(path,value)
            if Path(path).name=='coverage.json' and 'business-snapshots' in Path(path).parts and not changed[0]:
                changed[0]=True
                acl.update_access(self.workspace,'partition-owner',sorted(acl.ACTIONS-{'manage_knowledge'}),['*'])
            return result
        with patch.object(source,'_atomic',side_effect=atomic),self.assertRaises(acl.AccessDenied):self.store.build(self.workspace,self.sid)
        self.assertEqual(self.store.status(self.workspace,self.sid)['businessDigest'],self.meta['businessDigest'])
    def test_unsupported_outcome_preserves_exact_id_kind_and_denominator(self):
        with source.open_reader(self.workspace,self.sid) as reader:
            selected=next(reader.iter_records())
        original=self.store._semantics.candidate_record
        def unsupported(row,**kwargs):
            if row['id']==selected['id']:raise self.store._semantics.BusinessError('neutral_unsupported_projection')
            return original(row,**kwargs)
        with patch.object(self.store._semantics,'candidate_record',side_effect=unsupported):
            result=self.store.build(self.workspace,self.sid)
        self.assertEqual(result['recordCount']+1,self.meta['recordCount'])
        self.assertEqual(result['coverage']['denominator'],self.meta['coverage']['denominator'])
        with self.reader(result) as reader:
            outcomes=reader.coverage(limit=100)
            self.assertEqual(outcomes['total'],1)
            self.assertEqual(outcomes['entries'][0]['sourceRecordId'],selected['id'])
            self.assertEqual(outcomes['entries'][0]['sourceKind'],selected['kind'])
            self.assertEqual(outcomes['entries'][0]['reason'],'neutral_unsupported_projection')

    def test_explicit_preview_visits_every_input_and_pages_all_omissions(self):
        preview=self.store.build(self.workspace,self.sid,max_records=2)
        coverage=preview['coverage']
        self.assertEqual(coverage['visited'],self.meta['coverage']['denominator'])
        self.assertEqual(coverage['processed'],2)
        self.assertEqual(coverage['omitted'],coverage['denominator']-2)
        self.assertEqual(coverage['storageCompleteness'],'INCOMPLETE')
        with self.reader(preview) as reader:
            self.assertEqual(reader.report['entryCount']+preview['recordCount'],coverage['denominator'])
            last=reader.coverage(offset=reader.report['entryCount']-2,limit=2)
            self.assertEqual(last['returned'],2);self.assertIsNone(last['nextOffset'])
            self.assertEqual(last['entries'][-1]['inputIndex'],coverage['denominator']-1)
    def test_fatal_inventory_reader_keeps_known_denominator_unpublished(self):
        original=source.SnapshotReader.iter_records
        def broken(reader,**kwargs):
            for index,row in enumerate(original(reader,**kwargs)):
                if index==4:raise source.PipelineError('neutral_reader_failure')
                yield row
        with patch.object(source.SnapshotReader,'iter_records',broken),self.assertRaises(source.PipelineError):
            self.store.build(self.workspace,self.sid)
        attempt=json.loads((self.workspace/'business-last-attempt.json').read_text())
        self.assertEqual(attempt['coverage']['denominator'],self.meta['coverage']['denominator'])
        self.assertEqual(attempt['coverage']['processed'],4)
        self.assertEqual(attempt['coverage']['omitted']+4,attempt['coverage']['denominator'])
        self.assertEqual(self.store.status(self.workspace,self.sid)['businessDigest'],self.meta['businessDigest'])
    def test_reader_permission_revocation_and_invalid_chunk_do_not_widen_caps(self):
        with self.assertRaises(acl.AccessDenied):
            with self.reader() as reader:
                acl.update_access(self.workspace,'partition-owner',sorted(acl.ACTIONS-{'read_policy'}),['*'])
                reader.query()
        for value in (0,10001,True):
            with self.assertRaises(self.store.BusinessStoreError):self.store.build(self.workspace,self.sid,partition_size=value)
    def test_pointer_compare_and_swap_rejects_changed_current(self):
        original=self.store._state;calls=[0]
        def changed(workspace):
            value=original(workspace);calls[0]+=1
            if calls[0]>1:return {**value,'businessDigest':'0'*64}
            return value
        with patch.object(self.store,'_state',side_effect=changed),self.assertRaisesRegex(self.store.BusinessStoreError,'pointer_changed'):
            self.store.build(self.workspace,self.sid,max_records=1)
        self.assertEqual(self.store.status(self.workspace,self.sid)['businessDigest'],self.meta['businessDigest'])

    def test_legacy_v1_reader_remains_supported(self):
        with source._lock(self.workspace),source.open_reader(self.workspace,self.sid) as reader:
            previous=self.store._state(self.workspace);grant=self.store._authorize(self.workspace,'manage_knowledge',self.sid)
            payload=self.store._semantics.build_candidates(reader,source_pins=self.store._pins(reader),max_records=1)
            result=self.store._publish_v1(self.workspace,reader,payload,self.store._receipt(self.workspace,self.sid,'legacy_fixture',grant),previous,grant)
        with self.reader(result) as reader:
            self.assertEqual(reader.metadata['schemaVersion'],1);self.assertEqual(reader.query()['returned'],1)

if __name__=='__main__':unittest.main()
