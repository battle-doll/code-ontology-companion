"""Synthetic staged-source dependency closure and atomic publication."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_policy_dependency_closure import CONSTANT, IMPORTER, bindings, policy_semantics
from test_policy_literal_review import walk
from test_literal_review_pipeline import store, privacy_guard, protect_private_path


class PipelineDependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name).resolve();self.repo=root/'source';self.repo.mkdir();self.workspace=root/'knowledge'
        self.write('Rules.java',IMPORTER);self.write('Constants.java',CONSTANT)
        profile=root/'profile.json'
        profile.write_text(json.dumps(privacy_guard.build_profile(['Synthetic Private Person'],['nobody@privacy-fixture.test'],key=b'x'*32)))
        protect_private_path(profile)
        env=patch.dict(os.environ,{privacy_guard.PROFILE_ENV:str(profile)});env.start();self.addCleanup(env.stop)

    def write(self,path,source): (self.repo/path).write_text(source,encoding='utf-8')
    def rows(self): return list(store.iter_records(self.workspace))
    def consumer(self): return next(r for r in self.rows() if r.get('category')=='return' and r['path']=='Rules.java')

    def test_cross_file_declared_contract_requires_emitted_source_bound_constant(self):
        result=store.initialize(self.repo,self.workspace)
        row=self.consumer();self.assertTrue(bindings(row))
        binding=row['expression']['arguments'][0]['staticFieldBinding']
        constant=store.get_record(self.workspace,result['snapshotId'],binding['declarationFragmentId'])
        self.assertEqual(constant['category'],'constant')
        self.assertEqual(constant['sourceDigest'],binding['sourceDigest'])
        self.assertEqual(constant['sourceRange'],binding['sourceRange'])
        coverage=[r['coverage']['dependencyClosure'] for r in self.rows() if r.get('name')=='SemanticCoverage']
        self.assertTrue(all(c['status']=='finalized' and c['pendingFragments']==0 for c in coverage))
        self.repo.rename(self.repo.with_name('hidden-source'))
        self.assertEqual(row,self.consumer())

    def test_actual_unsupported_initializer_downgrades_consumer_and_keeps_inventory(self):
        source='package sample;public class Constants{public static final java.math.BigDecimal FLOOR=choose('+','.join('1' for _ in range(520))+');static java.math.BigDecimal choose(int... items){return null;}}'
        self.write('Constants.java',source)
        result=store.initialize(self.repo,self.workspace)
        self.assertFalse(bindings(self.consumer()))
        target=next(r for r in self.rows() if r.get('category')=='constant')
        self.assertEqual(target['representationStatus'],'unsupported')
        self.assertIn('expression_budget_exceeded',target['unsupportedReasons'])
        self.assertEqual(result['coverage']['semantics']['incompleteInventoryFiles'],0)
        self.assertIn('source_dependency_unavailable',self.consumer()['unsupportedReasons'])

    def test_missing_budgeted_declaration_blocks_new_snapshot(self):
        original=store.initialize(self.repo,self.workspace)['snapshotId']
        self.write('Constants.java',CONSTANT.replace('public static','int unrelated(){return 0;}public static'))
        extractor=policy_semantics.extract_semantics
        def capped(source,language,path,digest,**kwargs):
            if path=='Constants.java': kwargs['max_fragments']=1
            return extractor(source,language,path,digest,**kwargs)
        with patch.object(policy_semantics,'extract_semantics',side_effect=capped),self.assertRaisesRegex(store.PipelineError,'semantic_fragment_inventory_incomplete'):
            store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'],original)

    def test_bad_staged_digest_blocks_publication(self):
        original=store.initialize(self.repo,self.workspace)['snapshotId'];self.write('Rules.java',IMPORTER+'\n')
        writer=store._write_facts
        def corrupt(db,facts):
            count=writer(db,facts)
            if facts['path']=='Constants.java':
                row=db.execute("SELECT id,payload FROM records WHERE kind='semantic_fragment' AND name='FLOOR'").fetchone()
                value=json.loads(row[1]);value['sourceDigest']='0'*64
                db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(value),row[0]))
            return count
        with patch.object(store,'_write_facts',side_effect=corrupt),self.assertRaisesRegex(store.PipelineError,'semantic_dependency_record_binding_invalid'):
            store.sync(self.workspace,force=True)
        self.assertEqual(store.status(self.workspace)['snapshotId'],original)

    def test_failed_finalizer_and_interrupted_pass_never_publish_pending_proof(self):
        original=store.initialize(self.repo,self.workspace)['snapshotId'];self.write('Rules.java',IMPORTER+'\n')
        def interrupted(stage):
            if stage=='after_semantic_dependencies': raise OSError('synthetic_interrupt')
        with patch.object(store,'_checkpoint',side_effect=interrupted),self.assertRaises(OSError):store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'],original)
        store.recover(self.workspace)
        self.assertNotEqual(store.status(self.workspace)['snapshotId'],original)
        self.assertTrue(bindings(self.consumer()))
        self.write('Rules.java',IMPORTER+'\n\n');before=store.status(self.workspace)['snapshotId']
        with patch.object(store,'_finalize_semantic_dependencies',side_effect=RuntimeError('synthetic_failure')),self.assertRaises(RuntimeError):store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'],before)

    def test_skipped_finalizer_is_blocked_by_seal_coverage_check(self):
        original=store.initialize(self.repo,self.workspace)['snapshotId'];self.write('Rules.java',IMPORTER+'\n')
        with patch.object(store,'_finalize_semantic_dependencies',return_value=None),self.assertRaisesRegex(store.PipelineError,'semantic_dependency_finalization_incomplete'):
            store.sync(self.workspace,force=True)
        self.assertEqual(store.status(self.workspace)['snapshotId'],original)

    def test_later_file_revocation_retires_every_earlier_copy_before_dependency_check(self):
        import pipeline_literals
        constants='package sample;public class Constants{public static final java.math.BigDecimal FLOOR=read("MODE_A");static java.math.BigDecimal read(String label){return java.math.BigDecimal.ZERO;}}'
        signal='class ZSignal{String signal="TRIGGER_MODE";}'
        self.write('Constants.java',constants);self.write('ZSignal.java',signal)
        files,_=store._discover(self.repo,['.'],store.DEFAULT_BUDGETS);fingerprint=store._fingerprint(files)
        entries=[]
        for path,source,token in [('Constants.java',constants,'"MODE_A"'),('ZSignal.java',signal,'"TRIGGER_MODE"')]:
            start=source.index(token)
            entries.append({'path':path,'sourceSha256':hashlib.sha256(source.encode()).hexdigest(),
                'tokenByteStart':len(source[:start].encode()),'tokenByteEnd':len(source[:start+len(token)].encode()),
                'tokenSha256':hashlib.sha256(token.encode()).hexdigest(),'classification':'nonsecret_policy',
                'reasonCode':'synthetic_review','usageContext':'source_ir','reviewId':'synthetic'})
        manifest={'format':pipeline_literals.FORMAT,'purpose':pipeline_literals.PURPOSE,'sourceFingerprint':fingerprint,
            'review':{'reviewId':'synthetic','reviewerKind':'independent_source_review','reviewedAt':'2026-01-01T00:00:00Z'},'entries':entries}
        prepare=pipeline_literals.prepare_review
        def with_revocation(*args,**kwargs):
            review=prepare(*args,**kwargs)
            bind=review.bind_source
            def bind_revoke(path,*a,**k):
                bound=bind(path,*a,**k)
                if path=='ZSignal.java':
                    admit=bound.admit
                    def revoke(*a,**k):
                        review.reject(0,'fragment_redacted')
                        return admit(*a,**k)
                    bound.admit=revoke
                return bound
            review.bind_source=bind_revoke
            return review
        with patch.object(pipeline_literals,'prepare_review',side_effect=with_revocation):
            result=store.initialize(self.repo,self.workspace,literal_review=manifest)
        rows=self.rows()
        self.assertNotIn('MODE_A',json.dumps(rows))
        self.assertFalse(bindings(self.consumer()))
        provider=next(r for r in rows if r.get('category')=='constant' and r.get('name')=='FLOOR')
        self.assertEqual(provider['unsupportedReasons'],['literal_review_revoked'])
        self.assertEqual(result['coverage']['literalReview']['rejectedEntries'],1)
        self.assertEqual(result['coverage']['semantics']['literalReviewRetention']['admittedEntries'],1)

    def test_cycle_is_unknown_in_published_snapshot(self):
        self.write('Constants.java','package sample;import static sample.Leaf.END;public class Constants{public static final java.math.BigDecimal FLOOR=END;}')
        self.write('Leaf.java','package sample;import static sample.Constants.FLOOR;public class Leaf{public static final java.math.BigDecimal END=FLOOR;}')
        store.initialize(self.repo,self.workspace)
        self.assertFalse(bindings(self.consumer()))
        self.assertEqual(self.consumer()['dependencyClosure']['status'],'invalidated')
        self.assertFalse(any(n.get('resolution')=='selected_static_final_field' for n in walk(self.rows())))


if __name__=='__main__':unittest.main()
