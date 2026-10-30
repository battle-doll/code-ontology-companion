"""Native failed-build progress stays distinct from published knowledge."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_business_query as base


class UnpublishedBuildTests(unittest.TestCase):
    setUp = base.BusinessQueryTests.setUp

    def fail_build(self, after=3):
        original = self.store._semantics.iter_candidate_events
        yielded = []
        def failing(*args, **kwargs):
            for event in original(*args, **kwargs):
                yielded.append(event[0]); yield event
                if len(yielded) == after: raise OSError('neutral failure injection')
        with patch.object(self.store._semantics, 'iter_candidate_events', side_effect=failing), self.assertRaises(OSError):
            self.store.build(self.workspace, self.sid, processing_contract=True)
        self.assertEqual(len(yielded), after)
        return self.workspace/'business-last-attempt.json'

    def status(self):
        return base.access.dispatch('ontology_pipeline_status', {'workspace_id':self.wid, 'snapshot_id':self.sid, 'knowledge_view':'business'})['data']

    def write_receipt(self, path, value):
        path.write_bytes(self.store._semantics.canonical(value)); path.chmod(0o600)

    def test_positive_failed_build_keeps_parent_and_source_record_denominator(self):
        pointer = (self.workspace/'business-state.json').read_bytes()
        before = {str(p.relative_to(self.workspace)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for directory in ('snapshots', 'business-snapshots')
                  for p in (self.workspace/directory).rglob('*') if p.is_file()}
        path = self.fail_build()
        raw = path.read_bytes(); result = self.status()
        diag = result['lastRecordedUnpublishedBuild']
        self.assertEqual(diag['state'], 'RECORDED_UNPUBLISHED')
        self.assertEqual(result['businessDigest'], self.meta['businessDigest'])
        self.assertNotIn('nativeReceiptSha256', diag)
        with base.source.open_reader(self.workspace, self.sid) as reader: records = reader.metadata['recordCount']
        self.assertGreater(records, 1)
        self.assertEqual(diag['progress'], {'denominator':records, 'processed':3, 'visited':3, 'omitted':records-3, 'unsupported':0})
        self.assertNotIn('publishedParentRelation', diag)
        self.assertFalse(diag['publication'])
        self.assertEqual(diag['perInputFailureAttribution'], 'NOT_RECORDED')
        self.assertEqual(diag['sourceMeaning'], 'UNKNOWN')
        self.assertEqual(pointer, (self.workspace/'business-state.json').read_bytes())
        self.assertEqual(before, {str(p.relative_to(self.workspace)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for directory in ('snapshots', 'business-snapshots')
                  for p in (self.workspace/directory).rglob('*') if p.is_file()})
        self.assertEqual(raw, path.read_bytes())

    def test_no_receipt_is_not_recorded_not_success(self):
        self.assertEqual(self.status()['lastRecordedUnpublishedBuild']['state'], 'NOT_RECORDED')

    def test_policy_only_reader_does_not_probe_receipt(self):
        self.fail_build()
        base.acl.update_access(self.workspace, 'reader', ['read_policy'], [self.sid])
        with patch.dict(os.environ, {base.acl.PRINCIPAL_ENV:'reader'}), patch.object(self.store, 'unpublished_build_status', side_effect=AssertionError('receipt inspected')):
            self.assertEqual(self.status()['lastRecordedUnpublishedBuild'], {'schemaVersion':1, 'state':'WITHHELD'})

    def test_foreign_receipt_returns_no_foreign_digest_count_or_id(self):
        path = self.fail_build(); value = json.loads(path.read_bytes())
        value['sourceSnapshotId'] = 'ps-' + 'd'*32
        value['sourceManifestSha256'] = 'e'*64
        value['coverage']['denominator'] = 123456
        self.write_receipt(path, value)
        result = self.status()['lastRecordedUnpublishedBuild']
        self.assertEqual(result['state'], 'SOURCE_MISMATCH')
        self.assertEqual(result['sourceSnapshotId'], self.sid)
        for key in ('nativeReceiptSha256', 'progress', 'sourceManifestSha256', 'previousBusinessSnapshotId'):
            self.assertNotIn(key, result)
        self.assertNotIn('123456', json.dumps(result))

    def test_invalid_counts_schema_and_summary_are_explicit(self):
        path = self.fail_build(); original = json.loads(path.read_bytes())
        variants = []
        for field, value in [('denominator', 1), ('processed', True), ('omitted', -1), ('visited', 0), ('unsupported', 999)]:
            item = copy.deepcopy(original); item['coverage'][field] = value; variants.append(item)
        item = copy.deepcopy(original); item['schemaVersion'] = True; variants.append(item)
        item = copy.deepcopy(original); item['extra'] = 'unknown'; variants.append(item)
        item = copy.deepcopy(original); item['coverage']['sourceFunctionProcessing']['recognizedFunctions'] = False; variants.append(item)
        for item in variants:
            self.write_receipt(path, item)
            self.assertEqual(self.status()['lastRecordedUnpublishedBuild']['state'], 'INVALID')

    def test_malformed_oversized_and_symlink_receipts_are_unavailable(self):
        path = self.fail_build(); raw = path.read_bytes()
        for content in (b'{bad json', b' '*65537):
            path.write_bytes(content)
            self.assertEqual(self.status()['lastRecordedUnpublishedBuild']['state'], 'UNAVAILABLE')
        path.unlink(); target = self.root/'native-receipt.json'; target.write_bytes(raw); target.chmod(0o600)
        try: path.symlink_to(target)
        except OSError: self.skipTest('symlink unavailable')
        self.assertEqual(self.status()['lastRecordedUnpublishedBuild']['state'], 'UNAVAILABLE')

    def test_hardlinked_receipt_does_not_pass_private_boundary(self):
        path = self.fail_build(); target = self.root/'linked-receipt.json'
        try: os.link(path, target)
        except OSError: self.skipTest('hardlink unavailable')
        self.assertEqual(self.status()['lastRecordedUnpublishedBuild']['state'], 'UNAVAILABLE')

    def test_receipt_replacement_during_read_does_not_publish_unstable_hash(self):
        path = self.fail_build(); original = self.store._read; counts = [0]
        def changing(candidate, *args, **kwargs):
            value, raw = original(candidate, *args, **kwargs)
            if candidate == path:
                counts[0] += 1
                if counts[0] == 2: raw += b'\n'
            return value, raw
        with patch.object(self.store, '_read', side_effect=changing):
            diag = self.status()['lastRecordedUnpublishedBuild']
        self.assertEqual(diag['state'], 'UNAVAILABLE')
        self.assertEqual(diag['reason'], 'native_receipt_changed')
        self.assertNotIn('nativeReceiptSha256', diag)

    def test_denied_receipt_value_rejected_before_digest(self):
        path = self.fail_build(); value = json.loads(path.read_bytes())
        value['reason'] = 'Synthetic Query Private Person'; self.write_receipt(path, value)
        with patch.object(self.store.hashlib, 'sha256', wraps=hashlib.sha256) as hashed:
            with self.assertRaises(base.companion.CompanionError): self.status()
        native = path.read_bytes()
        self.assertFalse(any(call.args and call.args[0] == native for call in hashed.call_args_list))

    def test_evidence_revocation_at_return_rejects_diagnostic(self):
        self.fail_build(); original = self.store._same_access
        def revoked(workspace, action, snapshot, previous):
            if action == 'read_evidence': raise self.store.BusinessStoreError('authorization_changed')
            return original(workspace, action, snapshot, previous)
        with patch.object(self.store, '_same_access', side_effect=revoked), self.assertRaises(base.companion.CompanionError):
            self.status()

    def test_first_failure_with_no_parent_remains_not_ready(self):
        # The fixture's previous artifacts are retained; remove only its pointer
        # to model a first publication in this isolated temporary workspace.
        (self.workspace/'business-state.json').unlink()
        self.fail_build(); result = self.status()
        self.assertEqual(result['status'], 'not_ready')
        self.assertIsNone(result['businessSnapshotId'])
        self.assertEqual(result['lastRecordedUnpublishedBuild']['state'], 'RECORDED_UNPUBLISHED')
        self.assertNotIn('publishedParentRelation', result['lastRecordedUnpublishedBuild'])

    def test_new_source_does_not_expose_old_business_parent_as_current(self):
        (self.root/'source-offline').rename(self.repo)
        (self.repo/'second.py').write_text('def extra(v: int) -> int:\n    return v + 3\n')
        self.sid = base.source.sync(self.workspace)['snapshotId']
        self.repo.rename(self.root/'source-offline')
        self.fail_build(); result = self.status()
        self.assertEqual(result['status'], 'not_ready_for_selected_source')
        self.assertIsNone(result['businessSnapshotId'])
        self.assertEqual(result['businessCompletion'], 'UNKNOWN')
        self.assertEqual(result['lastRecordedUnpublishedBuild']['state'], 'RECORDED_UNPUBLISHED')
        self.assertNotIn(self.meta['businessSnapshotId'], json.dumps(result))

    def test_actual_stdio_without_source_retains_failure_and_function_summary(self):
        self.fail_build()
        profile = self.root/'neutral-profile.json'
        profile.write_text(json.dumps(base.companion.privacy_guard.load_profile())); profile.chmod(0o600)
        cache = self.root/'fresh-empty-cache'; cache.mkdir(mode=0o700)
        requests = [
            ('ontology_pipeline_status', {'knowledge_view':'business'}),
            ('query_policy_rules', {}),
            ('ontology_pipeline_search', {'kind':'semantic_fragment', 'term':'SourcePolicyFunctionProcessing', 'limit':1})]
        wire = '\n'.join(json.dumps({'jsonrpc':'2.0', 'id':i, 'method':'tools/call', 'params':{
            'name':name, 'arguments':{'workspace_id':self.wid, 'snapshot_id':self.sid, **extra}}})
            for i, (name, extra) in enumerate(requests)) + '\n'
        env = {k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
        env.update({base.companion.privacy_guard.PROFILE_ENV:str(profile), 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPYCACHEPREFIX':str(cache)})
        run = subprocess.run([sys.executable, '-E', '-s', '-B', '-X', 'pycache_prefix='+str(cache),
            str(Path(__file__).resolve().parents[1]/'mcp/server.py')], input=wire, text=True,
            capture_output=True, timeout=30, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        replies = [json.loads(line)['result'] for line in run.stdout.splitlines()]
        self.assertEqual(len(replies), 3)
        for reply in replies:
            self.assertFalse(reply.get('isError'), reply)
            self.assertEqual(json.loads(reply['content'][0]['text']), reply['structuredContent'])
        self.assertEqual(replies[0]['structuredContent']['data']['lastRecordedUnpublishedBuild']['state'], 'RECORDED_UNPUBLISHED')
        summary = replies[1]['structuredContent']['data']['coverage']['sourceFunctionProcessing']
        self.assertEqual(summary['recognizedFunctions'], 1)
        row = replies[2]['structuredContent']['data']['records'][0]
        self.assertEqual(row['expression']['declarationKind'], 'policy_function_processing')
        self.assertEqual(row['representationStatus'], 'coverage_metadata')
        self.assertFalse(any(cache.rglob('*')))

    def test_hidden_native_parent_has_no_public_fingerprint_or_relationship(self):
        path=self.fail_build(); original=json.loads(path.read_bytes())
        first=self.status()['lastRecordedUnpublishedBuild']
        changed=copy.deepcopy(original);changed['previousBusinessSnapshotId']='bs-'+'b'*32
        self.write_receipt(path,changed);native=path.read_bytes()
        with patch.object(self.store.hashlib,'sha256',wraps=hashlib.sha256) as hashed:
            second=self.status()['lastRecordedUnpublishedBuild']
        self.assertEqual(first,second)
        self.assertNotIn('nativeReceiptSha256',second);self.assertNotIn('publishedParentRelation',second)
        self.assertFalse(any(call.args and call.args[0]==native for call in hashed.call_args_list))

    def test_profile_change_after_native_reread_rejects_hidden_field(self):
        path=self.fail_build();hidden=json.loads(path.read_bytes())['previousBusinessSnapshotId']
        self.meta=self.store.build(self.workspace,self.sid)
        guard=self.store._guard;profiles=[guard.load_profile()]
        denied=guard.build_profile([hidden],[],key=b'd'*32)
        original=self.store._read;reads=[0]
        def late(candidate,*args,**kwargs):
            answer=original(candidate,*args,**kwargs)
            if candidate==path:
                reads[0]+=1
                if reads[0]==2:profiles[0]=denied
            return answer
        with patch.object(guard,'load_profile',side_effect=lambda *a,**k:profiles[0]),patch.object(self.store,'_read',side_effect=late):
            with self.assertRaises(base.companion.CompanionError):self.status()
        self.assertEqual(reads[0],2)

    def test_post_helper_profile_change_cannot_emit_hidden_parent_derived_fields(self):
        path=self.fail_build();hidden=json.loads(path.read_bytes())['previousBusinessSnapshotId']
        self.meta=self.store.build(self.workspace,self.sid)
        guard=self.store._guard;profiles=[guard.load_profile()]
        denied=guard.build_profile([hidden],[],key=b'g'*32)
        original=self.store.unpublished_build_status
        def late(*args,**kwargs):
            result=original(*args,**kwargs);profiles[0]=denied;return result
        with patch.object(guard,'load_profile',side_effect=lambda *a,**k:profiles[0]),patch.object(self.store,'unpublished_build_status',side_effect=late):
            result=self.status()['lastRecordedUnpublishedBuild']
        self.assertNotIn(hidden,json.dumps(result))
        self.assertNotIn('nativeReceiptSha256',result);self.assertNotIn('publishedParentRelation',result)


if __name__ == '__main__':
    unittest.main()
