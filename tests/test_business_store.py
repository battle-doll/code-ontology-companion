"""Synthetic sealed pipeline integration and immutable business overlays."""
import copy
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_store as store
import business_semantics as sem
import pipeline_store as source
import privacy_guard

class ACL:
    def __init__(self):self.revision=1;self.actions={'read_policy','manage_knowledge'}
    def authorize(self,workspace,action,snapshot):
        if action not in self.actions:raise store.BusinessStoreError('access_denied')
        return {'decision':'allow','revision':self.revision,'policyDigest':str(self.revision)*64}
    def _principal(self):return 'neutral-reviewer'
    def publication_guard(self,workspace):
        import companion
        return companion._snapshot_write_lock(workspace)

class BusinessStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        profile=privacy_guard.build_profile([],[],key=b't'*32)
        self.profilepatch=patch.object(privacy_guard,'load_profile',return_value=profile);self.profilepatch.start()
        self.repo=self.root/'source';self.repo.mkdir();(self.repo/'catalog.py').write_text('def eligible(active: bool) -> bool:\n    return active\n')
        self.workspace=self.root/'knowledge';self.source_snapshot=source.initialize(self.repo,self.workspace)['snapshotId']
        self.acl=ACL();self.spec={'businessSpecId':'neutral-v1','businessSpecHash':'a'*64}
        store.configure(pipeline_store=source,semantics=sem,acl=self.acl,privacy_guard=privacy_guard,business_spec=self.spec)
    def tearDown(self):self.profilepatch.stop();self.temp.cleanup()
    def build(self):return store.build(self.workspace,self.source_snapshot)
    def reader(self,result):return store.open_reader(self.workspace,self.source_snapshot,result['businessSnapshotId'],result['businessDigest'])
    def manifest(self,result,key='catalog-policy'):
        with self.reader(result) as reader:
            row=next(x for x in reader.iter_records() if x['kind']=='business_policy')
        return {'schemaVersion':1,'sourcePins':{k:result[k] for k in sem.PIN_KEYS},'concepts':[{'namespace':'review','domain':'catalog','kind':'business_policy','conceptKey':key,'label':'Eligibility','sourceAnchors':row['sourceAnchors'],'facets':{'formula':row['facets']['formula'],'inputs':row['facets']['inputs'],'outcome':row['facets']['outcome']}}]}
    def review(self,result,manifest=None):
        return store.review(self.workspace,self.source_snapshot,result['businessSnapshotId'],result['businessDigest'],manifest or self.manifest(result))
    def files(self):
        return {str(p.relative_to(self.workspace)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.workspace/'snapshots').rglob('*') if p.is_file()}

    def test_source_record_and_run_budgets_keep_prior_pointer(self):
        initial=self.build();original=source.SnapshotReader.__enter__
        for budget,maximum,reason in [('max_records',1,'record_budget'),('max_run_seconds',0,'deadline')]:
            def bounded(reader):
                result=original(reader);reader.config=copy.deepcopy(reader.config)
                reader.config['budgets'][budget]=maximum;return result
            with patch.object(source.SnapshotReader,'__enter__',bounded),self.assertRaisesRegex(store.BusinessStoreError,reason):
                self.build()
            self.assertEqual(store.status(self.workspace,self.source_snapshot)['businessDigest'],initial['businessDigest'])
            self.assertEqual(store._read(self.workspace/'business-last-attempt.json',self.workspace)[0]['coverage']['denominator'],initial['coverage']['denominator'])

    def test_source_free_candidate_build_and_exact_page_pins(self):
        before=self.files();self.repo.rename(self.root/'source-offline')
        result=self.build()
        self.assertEqual(before,self.files());self.assertEqual(result['businessCompletion'],'PARTIAL')
        with self.reader(result) as reader:
            first=reader.query(limit=1);second=reader.query(offset=1,limit=1)
            self.assertEqual(first['queryDigest'],second['queryDigest'])
            self.assertEqual(first['businessDigest'],result['businessDigest'])
            self.assertTrue(first['truncated']);self.assertEqual(first['nextOffset'],1)
            self.assertEqual(len(list(reader.iter_records(page_size=1))),result['recordCount'])
        self.assertEqual(store.status(self.workspace,self.source_snapshot)['businessDigest'],result['businessDigest'])

    def test_review_is_authorized_immutable_child_with_unknowns(self):
        initial=self.build();oldfiles={p.name:p.read_bytes() for p in (self.workspace/'business-snapshots'/initial['businessSnapshotId']).iterdir()}
        reviewed=self.review(initial)
        self.assertEqual(reviewed['parentBusinessSnapshotId'],initial['businessSnapshotId'])
        with self.reader(reviewed) as reader:
            row=next(x for x in reader.iter_records() if x.get('reviewedMeaning'))
            self.assertEqual(row['businessApproval'],'approved');self.assertEqual(row['facets']['units']['status'],'UNKNOWN')
        self.assertEqual(oldfiles,{p.name:p.read_bytes() for p in (self.workspace/'business-snapshots'/initial['businessSnapshotId']).iterdir()})
        with self.assertRaisesRegex(store.BusinessStoreError,'not_current'):
            with self.reader(initial):pass

    def test_revoke_and_no_old_approval_resurrection(self):
        initial=self.build();reviewed=self.review(initial)
        with self.reader(reviewed) as reader:rid=next(r['id'] for r in reader.iter_records() if r.get('reviewedMeaning'))
        revoked=store.revoke(self.workspace,self.source_snapshot,reviewed['businessSnapshotId'],reviewed['businessDigest'],[rid])
        with self.reader(revoked) as reader:self.assertEqual(reader.get_record(rid)['businessApproval'],'revoked')
        with self.assertRaises(store.BusinessStoreError):
            with self.reader(reviewed):pass

    def test_permission_and_revision_recheck(self):
        initial=self.build();manifest=self.manifest(initial);self.acl.actions.remove('manage_knowledge')
        with self.assertRaisesRegex(store.BusinessStoreError,'access_denied'):self.review(initial,manifest)
        with self.assertRaisesRegex(store.BusinessStoreError,'authorization_changed'):
            with self.reader(initial) as reader:
                self.acl.revision+=1;reader.query()

    def test_failed_validation_preserves_old_pointer(self):
        initial=self.build();manifest=self.manifest(initial);manifest['schemaVersion']=True
        with self.assertRaises(sem.BusinessError):self.review(initial,manifest)
        self.assertEqual(store.status(self.workspace,self.source_snapshot)['businessDigest'],initial['businessDigest'])

    def test_source_and_spec_changes_fail_closed(self):
        initial=self.build()
        store.configure(pipeline_store=source,semantics=sem,acl=self.acl,privacy_guard=privacy_guard,business_spec={**self.spec,'businessSpecHash':'b'*64})
        with self.assertRaisesRegex(store.BusinessStoreError,'stale'):
            with self.reader(initial):pass
        store.configure(pipeline_store=source,semantics=sem,acl=self.acl,privacy_guard=privacy_guard,business_spec=self.spec)
        (self.repo/'catalog.py').write_text('def eligible(active: bool) -> bool:\n    return not active\n')
        source.sync(self.workspace)
        with self.assertRaisesRegex(store.BusinessStoreError,'source_snapshot_not_current'):
            with self.reader(initial):pass

    def test_corruption_and_symlink_are_not_read(self):
        initial=self.build();directory=self.workspace/'business-snapshots'/initial['businessSnapshotId']
        with self.assertRaisesRegex(store.BusinessStoreError,'changed'):
            with self.reader(initial) as reader:
                p=next(directory.glob('records-*.sqlite'));p.write_bytes(p.read_bytes()+b' ');reader.query()
        with self.assertRaises(store.BusinessStoreError):
            with self.reader(initial):pass

    def test_boundaries_and_original_denominator(self):
        initial=store.build(self.workspace,self.source_snapshot,max_records=1)
        self.assertGreater(initial['coverage']['denominator'],initial['recordCount'])
        self.assertGreater(initial['coverage']['omitted'],0)
        for p in (self.workspace/'business-snapshots'/initial['businessSnapshotId']).iterdir():
            if os.name!='nt':self.assertEqual(p.stat().st_mode&0o077,0)
        with self.reader(initial) as reader:
            for args in ({'offset':True},{'limit':False},{'limit':201}):
                with self.assertRaises(store.BusinessStoreError):reader.query(**args)

    def test_duplicate_review_keeps_inputs_rejected(self):
        initial=self.build();manifest=self.manifest(initial);manifest['concepts'].append(copy.deepcopy(manifest['concepts'][0]))
        result=self.review(initial,manifest)
        self.assertEqual(result['coverage']['denominator'],2);self.assertEqual(result['coverage']['reviewAccepted'],0)
        self.assertEqual(result['coverage']['state'],'PARTIAL')

    def test_private_review_duplicate_keys_and_self_approval(self):
        p=self.root/'review.json';p.write_text('{"schemaVersion":1,"schemaVersion":2}');p.chmod(0o600)
        with self.assertRaises(sem.BusinessError):store.load_review(p)
        initial=self.build();manifest=self.manifest(initial);manifest['concepts'][0]['approved']=True
        result=self.review(initial,manifest);self.assertEqual(result['coverage']['reviewAccepted'],0)

    def test_neutral_common_policy_language_variants(self):
        (self.repo/'Rules.java').write_text('class Rules { static boolean eligible(boolean active) { return active; } }')
        (self.repo/'scheduling.ts').write_text('export function eligible(active: boolean): boolean { return active; }')
        self.source_snapshot=source.sync(self.workspace)['snapshotId'];result=self.build()
        with self.reader(result) as reader:
            rows=list(reader.iter_records(kind='business_policy'))
            self.assertEqual(len(rows),3)
            self.assertEqual(len({r['id'] for r in rows}),3)
            self.assertTrue(all(r['facets']['outcome']['value']['name']=='bool' for r in rows))

    def test_publish_failure_keeps_prior_current_and_source(self):
        initial=self.build();before=self.files();original=source._atomic
        def fail(path,value):
            if path.name=='business-state.json':raise OSError('synthetic publication failure')
            return original(path,value)
        with patch.object(source,'_atomic',side_effect=fail),self.assertRaises(OSError):self.build()
        self.assertEqual(store.status(self.workspace,self.source_snapshot)['businessDigest'],initial['businessDigest'])
        self.assertEqual(before,self.files())

    def test_revoke_reference_closure_preserves_independent_sibling(self):
        initial=self.build();manifest=self.manifest(initial)
        template=manifest['concepts'][0];template['kind']='business_object_type';template['facets']={};template['conceptKey']='one'
        other=copy.deepcopy(template);other['conceptKey']='two'
        relation=copy.deepcopy(template);relation.update(kind='business_relation',conceptKey='link',subject=sem.concept_id('review','catalog','business_object_type','one'),object=sem.concept_id('review','catalog','business_object_type','two'),role='contains')
        manifest['concepts']=[template,other,relation];reviewed=self.review(initial,manifest)
        one=relation['subject'];two=relation['object'];link=sem.concept_id('review','catalog','business_relation','link')
        with self.reader(reviewed) as reader:oldreceipt=reader.get_record(two)['approvalReceiptId']
        result=store.revoke(self.workspace,self.source_snapshot,reviewed['businessSnapshotId'],reviewed['businessDigest'],[one])
        with self.reader(result) as reader:
            self.assertEqual(reader.get_record(one)['businessApproval'],'revoked')
            self.assertEqual(reader.get_record(link)['businessApproval'],'revoked')
            self.assertEqual(reader.get_record(two)['businessApproval'],'approved')
            self.assertEqual(reader.get_record(two)['approvalReceiptId'],oldreceipt)
        self.assertEqual(result['coverage']['revoked'],2)

    def test_review_replacement_invalidations_visible(self):
        initial=self.build();first=self.review(initial);second=self.review(first,self.manifest(first,key='replacement'))
        self.assertEqual(second['coverage']['previousReviewInvalidated'],1)
        self.assertTrue(any(x['reason']=='review_layer_replaced' for x in second['coverage']['entries']))

    def test_public_directory_or_linked_review_rejected(self):
        initial=self.build();path=self.workspace/'business-snapshots'
        if os.name!='nt':
            path.chmod(0o755)
            with self.assertRaisesRegex(store.BusinessStoreError,'permissions'):
                with self.reader(initial):pass
            path.chmod(0o700)
        target=self.root/'review.json';target.write_text('{}');target.chmod(0o600)
        link=self.root/'link.json';link.symlink_to(target)
        with self.assertRaises(Exception):store.load_review(link)

    def test_conflicted_meaning_does_not_receive_effective_approval(self):
        initial=self.build();manifest=self.manifest(initial)
        manifest['concepts'][0]['facets']['conflicts']={'status':'DECLARED','value':{'type':'boolean','value':True},'basis':'explicit conflict'}
        result=self.review(initial,manifest)
        with self.reader(result) as reader:
            row=next(r for r in reader.iter_records() if r.get('reviewedMeaning'))
            self.assertEqual(row['support'],'conflicted');self.assertEqual(row['businessApproval'],'unreviewed')

if __name__=='__main__':unittest.main()
