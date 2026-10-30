"""Rehashed immutable SQL selector indexes must match their canonical payloads."""
import copy
from contextlib import closing
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_semantics as sem
import business_store as store
import pipeline_store as source
import privacy_guard

class ACL:
    def authorize(self,workspace,action,snapshot):return {'decision':'allow','revision':1,'policyDigest':'a'*64}
    def _principal(self):return 'neutral-index-reviewer'
    def publication_guard(self,workspace):
        import companion
        return companion._snapshot_write_lock(workspace)

class BusinessIndexCoherenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.repo=self.root/'source';self.repo.mkdir()
        self.profile=patch.object(privacy_guard,'load_profile',return_value=privacy_guard.build_profile([],[],key=b'i'*32))
        self.profile.start();self.addCleanup(self.profile.stop)
        (self.repo/'neutral.py').write_text(''.join('def eligible%d(active: bool) -> bool:\n    return active\n'%i for i in range(12)))
        self.workspace=self.root/'knowledge';self.sid=source.initialize(self.repo,self.workspace)['snapshotId']
        store.configure(pipeline_store=source,semantics=sem,acl=ACL(),privacy_guard=privacy_guard,
                        business_spec={'businessSpecId':'neutral-index-v1','businessSpecHash':'a'*64})
        self.meta=store.build(self.workspace,self.sid);self.repo.rename(self.root/'source-offline')
        self.directory=self.workspace/'business-snapshots'/self.meta['businessSnapshotId']
        self.path=next(self.directory.glob('records-*.sqlite'))
        with closing(sqlite3.connect(str(self.path))) as db, db:self.rows=db.execute('SELECT id,kind,namekey,domain,payload FROM records ORDER BY id').fetchall()
        self.a=self.rows[len(self.rows)//2];self.b=self.rows[len(self.rows)//2+1]
        store._INDEX_CACHE.clear()
    def reader(self,workspace=None):
        return store.open_reader(workspace or self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest'])
    def rehash(self):
        manifest=sem.loads((self.directory/'manifest.json').read_bytes())
        for shard in manifest['storage']['shards']:
            if shard['name']!=self.path.name:continue
            with closing(sqlite3.connect(str(self.path))) as db, db:
                count,first,last=db.execute('SELECT count(*),min(id),max(id) FROM records').fetchone()
            shard.update(count=count,first=first,last=last,bytes=self.path.stat().st_size)
            manifest['artifacts'][shard['name']]=hashlib.sha256(self.path.read_bytes()).hexdigest()
        manifest['businessDigest']=sem.digest({k:v for k,v in manifest.items() if k!='businessDigest'})
        source._atomic(self.directory/'manifest.json',sem.canonical(manifest))
        source._atomic(self.workspace/'business-state.json',{'schemaVersion':1,'businessSnapshotId':manifest['businessSnapshotId'],
                      'businessDigest':manifest['businessDigest'],'sourceSnapshotId':self.sid})
        self.meta=manifest
    def change(self,column,value):
        self.assertIn(column,('id','kind','namekey','domain','payload'))
        with closing(sqlite3.connect(str(self.path))) as db, db:db.execute('UPDATE records SET '+column+'=? WHERE id=?',(value,self.a[0]))
        self.rehash()
    def rejection(self,call):
        with self.assertRaisesRegex(store.BusinessStoreError,'business_index_'):
            with self.reader() as reader:call(reader)
    def test_valid_donor_payload_cannot_answer_get_of_other_identity(self):
        self.change('payload',self.b[4]);self.rejection(lambda r:r.get_record(self.a[0]))
    def test_valid_donor_payload_cannot_answer_exact_identity_query(self):
        self.change('payload',self.b[4]);self.rejection(lambda r:r.query(record_ids=[self.a[0]]))
    def test_wrong_domain_cannot_create_false_positive(self):
        self.change('domain','wrong-domain');self.rejection(lambda r:r.query(domain='wrong-domain'))
    def test_wrong_kind_cannot_create_false_positive(self):
        self.change('kind','business_transition');self.rejection(lambda r:r.query(kind='business_transition'))
    def test_wrong_namekey_cannot_create_false_positive(self):
        self.change('namekey','unrelatedneedle');self.rejection(lambda r:r.query(term='unrelatedneedle'))
    def test_malformed_internal_key_cannot_hide_real_record(self):
        self.change('id',self.a[0]+'x');self.rejection(lambda r:r.get_record(self.a[0]))
    def test_wrong_index_hidden_by_every_original_filter_still_rejects_totals(self):
        for column,index in [('kind',1),('namekey',2),('domain',3)]:
            with self.subTest(column=column):
                original=self.a[index]
                self.change(column,'hidden-wrong-selector')
                self.rejection(lambda r:r.query(kind=self.a[1],domain=self.a[3],term=self.a[2],limit=1))
                self.change(column,original)
    def test_matching_index_and_sealed_payload_still_require_canonical_concept_id(self):
        payload=sem.loads(self.a[4]);payload['conceptKey']='different-canonical-concept'
        payload=sem.seal_record(payload)
        self.change('payload',sem.canonical(payload).decode())
        self.rejection(lambda r:r.query(record_ids=[self.a[0]]))
    def test_index_value_type_is_exact_text(self):
        self.change('kind',sqlite3.Binary(b'business_claim'));self.rejection(lambda r:list(r.iter_records()))
    def test_duplicate_json_metadata_is_not_accepted_or_failure_cached(self):
        payload=self.a[4][:-1]+',"id":"'+self.a[0]+'"}'
        self.change('payload',payload)
        for _ in range(2):self.rejection(lambda r:r.query())
        self.assertEqual(len(store._INDEX_CACHE),0)
    def test_json_depth_and_string_caps_remain_unchanged_for_hidden_rows(self):
        original=self.a[4]
        for alteration in ['"hidden":'+('['*34)+'0'+(']'*34),'"hidden":"'+('x'*131073)+'"']:
            with self.subTest(kind=alteration[:20]):
                self.change('payload',original[:-1]+','+alteration+'}')
                self.rejection(lambda r:r.query(record_ids=[self.b[0]]))
                self.change('payload',original)
    def test_unicode_casefold_matches_original_names_and_query_totals(self):
        payload=sem.loads(self.a[4]);payload['name']='Stra\u00dfe \u0130stanbul \ud56d\ubaa9';payload=sem.seal_record(payload)
        with closing(sqlite3.connect(str(self.path))) as db, db:db.execute('UPDATE records SET namekey=?,payload=? WHERE id=?',
            (payload['name'].casefold(),sem.canonical(payload).decode(),self.a[0]))
        self.rehash()
        with self.reader() as reader:
            for term in ['STRASSE','\u0130STANBUL','\ud56d\ubaa9']:
                page=reader.query(term=term)
                self.assertEqual(page['total'],1);self.assertEqual(page['records'][0]['id'],self.a[0])
            self.assertEqual(len(list(reader.iter_records())),self.meta['recordCount'])
    def test_success_cache_skips_repeat_scan_and_contains_no_records(self):
        original=store.BusinessReader._index_json
        with patch.object(store.BusinessReader,'_index_json',wraps=original) as scan:
            with self.reader():pass
            first=scan.call_count
            with self.reader():pass
            self.assertEqual(first,self.meta['recordCount']);self.assertEqual(scan.call_count,first)
        self.assertTrue(store._INDEX_CACHE);self.assertTrue(all(value is None for value in store._INDEX_CACHE.values()))
    def test_copy_replacement_and_same_hash_metadata_change_require_rescan(self):
        with self.reader():pass
        original=store.BusinessReader._index_json
        copy=self.root/'copy';shutil.copytree(self.workspace,copy)
        with patch.object(store.BusinessReader,'_index_json',wraps=original) as scan:
            with self.reader(copy):pass
            self.assertEqual(scan.call_count,self.meta['recordCount'])
        # Reapplying identical times changes POSIX ctime, but is a metadata
        # no-op on Windows. Exercise an actual observable metadata change on
        # both platforms while retaining exactly the same sealed bytes.
        info=self.path.stat();digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        os.utime(self.path,ns=(info.st_atime_ns,info.st_mtime_ns+2_000_000_000))
        self.assertNotEqual(self.path.stat().st_mtime_ns,info.st_mtime_ns)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),digest)
        with patch.object(store.BusinessReader,'_index_json',wraps=original) as scan:
            with self.reader():pass
            self.assertEqual(scan.call_count,self.meta['recordCount'])
        replacement=self.path.with_name('replacement.sqlite');shutil.copyfile(self.path,replacement);replacement.chmod(0o600);os.replace(replacement,self.path)
        with patch.object(store.BusinessReader,'_index_json',wraps=original) as scan:
            with self.reader():pass
            self.assertEqual(scan.call_count,self.meta['recordCount'])
    def test_rehashed_mutation_misses_success_cache_and_never_failure_caches(self):
        with self.reader():pass
        self.change('domain','hidden-wrong-domain')
        previous=list(store._INDEX_CACHE)
        original=store.BusinessReader._index_json
        with patch.object(store.BusinessReader,'_index_json',wraps=original) as scan:
            for _ in range(2):self.rejection(lambda r:r.query(domain='unclassified'))
            self.assertGreater(scan.call_count,0)
        self.assertEqual(previous,list(store._INDEX_CACHE))
    def test_later_shard_failure_commits_no_pending_success_cache(self):
        self.meta=store.build(self.workspace,self.sid,partition_size=20)
        self.directory=self.workspace/'business-snapshots'/self.meta['businessSnapshotId']
        shards=sorted(self.directory.glob('records-*.sqlite'))
        self.assertGreater(len(shards),1);self.path=shards[1]
        with closing(sqlite3.connect(str(self.path))) as db, db:
            self.rows=db.execute('SELECT id,kind,namekey,domain,payload FROM records ORDER BY id').fetchall()
        self.a=self.rows[len(self.rows)//2]
        self.change('namekey','hidden-wrong-selector');store._INDEX_CACHE.clear()
        self.rejection(lambda r:r.query())
        self.assertEqual(len(store._INDEX_CACHE),0)

    def test_cache_limit_and_eviction_are_bounded_metadata_only(self):
        self.assertEqual(store._INDEX_CACHE_LIMIT,64)
        with self.reader():pass
        for index in range(64):
            clone=self.root/('copy%d'%index);shutil.copytree(self.workspace,clone)
            with self.reader(clone):pass
        self.assertEqual(len(store._INDEX_CACHE),64)
        original=store.BusinessReader._index_json
        with patch.object(store.BusinessReader,'_index_json',wraps=original) as scan:
            with self.reader():pass
            self.assertEqual(scan.call_count,self.meta['recordCount'])
        self.assertEqual(len(store._INDEX_CACHE),64)

if __name__=='__main__':unittest.main()
