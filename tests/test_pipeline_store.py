"""Synthetic durable publication, source-free queries and bounded analysis."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'))
import pipeline_store as store
import pipeline_policy
import privacy_guard


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.workspace = self.root / 'workspace'
        self.write('orders.py', 'def order_discount(total: int) -> int:\n    if total >= 100:\n        return total - 10\n    return total\n')

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding='utf-8')

    def init(self, **options):
        return store.initialize(self.repo, self.workspace, **options)

    def records(self, snapshot=None):
        return list(store.iter_records(self.workspace, snapshot, page_size=2))

    def digest_tree(self):
        return {str(p.relative_to(self.workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.workspace.rglob('*') if p.is_file()}

    def test_no_change_source_free_pin_and_readonly_queries(self):
        result = self.init(label='Synthetic map')
        first = result['snapshotId']
        self.assertEqual(store.sync(self.workspace)['status'], 'no_change')
        self.write('other.py', 'class Other:\n    pass\n')
        second = store.sync(self.workspace)['snapshotId']
        self.assertNotEqual(first, second)
        before = self.digest_tree()
        self.repo.rename(self.root / 'source-hidden')
        with store.open_reader(self.workspace, first) as reader:
            rows = list(reader.iter_records(page_size=2))
            self.assertEqual(len(rows), reader.metadata['recordCount'])
            self.assertEqual(reader.get_record(rows[0]['id']), rows[0])
            self.assertTrue(reader.modules()['modules'])
            policy = reader.read_policy_records()
            answer = pipeline_policy.query_policy_rules(policy)
            self.assertTrue(answer['rules'])
        self.assertEqual(before, self.digest_tree())
        self.assertEqual(store.status(self.workspace)['snapshotId'], second)

    def test_incremental_matches_full_after_delete_rename_config_and_import_change(self):
        self.write('api.py', 'from orders import order_discount\n')
        first = self.init()
        self.write('orders.py', 'def order_discount(total: int) -> int:\n    return total - 5\n')
        self.write('settings.json', '{"mode":"synthetic"}')
        result = store.sync(self.workspace)
        self.assertEqual(result['buildStats']['reusedFiles'], 1)
        incremental = self.records()
        full = store.sync(self.workspace, force=True)
        self.assertEqual(full['buildStats']['reusedFiles'], 0)
        self.assertEqual(full['buildStats']['parsedFiles'], 3)
        self.assertEqual(incremental, self.records(full['snapshotId']))
        (self.repo / 'orders.py').rename(self.repo / 'renamed.py')
        store.sync(self.workspace)
        rows = self.records()
        self.assertFalse(any(r['path'] == 'orders.py' for r in rows))
        self.assertTrue(any(r['name'] == 'IMPORTS' and r.get('resolution') == 'unresolved' for r in rows))
        (self.repo / 'renamed.py').unlink()
        store.sync(self.workspace)
        self.assertFalse(any(r['path'] == 'renamed.py' for r in self.records()))
        self.assertTrue(store.query(self.workspace, first['snapshotId'])['total'])

    def test_failure_boundaries_recover_without_duplicate_events(self):
        self.init()
        for boundary in ('after_file', 'after_manifest', 'after_prepared_receipt', 'after_snapshot_rename', 'after_pointer', 'after_ledger'):
            with self.subTest(boundary=boundary):
                previous = store.status(self.workspace)['snapshotId']
                self.write('extra.py', 'class Extra:\n    value = ' + str(len(boundary)) + '\n# ' + boundary)
                def interrupt(stage):
                    if stage == boundary:
                        raise OSError('synthetic_crash')
                with patch.object(store, '_checkpoint', interrupt), self.assertRaises(OSError):
                    store.sync(self.workspace)
                if boundary not in ('after_pointer', 'after_ledger'):
                    self.assertEqual(store.status(self.workspace)['snapshotId'], previous)
                self.assertEqual(store.recover(self.workspace)['recoveredRunCount'], 1)
                self.assertEqual(store.recover(self.workspace)['recoveredRunCount'], 0)
                ledger = json.loads((self.workspace / 'ledger.json').read_text())['events']
                self.assertEqual(len({r['runId'] for r in ledger}), len(ledger))
                self.assertNotEqual(store.status(self.workspace)['snapshotId'], previous)

    def test_stale_source_never_promotes(self):
        old = self.init()['snapshotId']
        self.write('extra.py', 'class Extra: pass')
        def mutate(stage):
            if stage == 'before_source_recheck':
                self.write('extra.py', 'class Changed: pass')
        with patch.object(store, '_checkpoint', mutate), self.assertRaisesRegex(store.PipelineError, 'changed'):
            store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'], old)

    def test_cancel_and_checkpoint_resume(self):
        self.init()
        for i in range(70):
            self.write(f'package/file{i}.py', f'class Item{i}: pass')
        calls = [0]
        def cancel():
            calls[0] += 1
            return calls[0] > 150
        with self.assertRaises(store.PipelineCancelled):
            store.sync(self.workspace, cancel=cancel)
        self.assertEqual(store.status(self.workspace)['status'], 'recovery_required')
        recovered = store.recover(self.workspace)
        self.assertEqual(recovered['recoveredRunCount'], 1)
        self.assertEqual(len(self.records()), recovered['recordCount'])

    def test_corruption_and_snapshot_selector_denied(self):
        result = self.init()
        path = self.workspace / 'snapshots' / result['snapshotId'] / 'policy.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(store.PipelineError, 'integrity'):
            store.query(self.workspace)
        with self.assertRaises(store.PipelineError):
            store.query(self.workspace, '../escape')

    def test_source_symlink_xml_and_quotas_never_publish(self):
        self.init()
        original = store.status(self.workspace)['snapshotId']
        outside = self.root / 'outside.py'
        outside.write_text('class Private: pass')
        (self.repo / 'link.py').symlink_to(outside)
        with self.assertRaises(store.PipelineError):
            store.sync(self.workspace)
        (self.repo / 'link.py').unlink()
        self.write('mapper.xml', '<!DOCTYPE mapper SYSTEM "https://example.invalid"><mapper/>')
        with self.assertRaises(Exception):
            store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'], original)
        other = self.root / 'bounded'
        with self.assertRaises(store.PipelineError):
            store.initialize(self.repo, other, max_files=1)
        attempt = json.loads((other / 'last-coverage-attempt.json').read_text(encoding='utf-8'))
        self.assertEqual(attempt['summary']['state'], 'BLOCKED')
        self.assertEqual(attempt['summary']['denominator'], 2)
        self.assertTrue(any(row['reason'] == 'source_count_or_byte_budget'
                            for row in attempt['entries']))
        self.assertIsNone(json.loads((other / 'state.json').read_text(encoding='utf-8'))['currentSnapshot'])

    def test_private_workspace_and_secret_output_guard(self):
        self.init()
        if os.name != 'nt':
            os.chmod(self.workspace / 'pipeline.json', 0o644)
            with self.assertRaises(privacy_guard.PrivacyError):
                store.status(self.workspace)
            os.chmod(self.workspace / 'pipeline.json', 0o600)
        self.write('unsafe.py', 'def contact_alice_example_com():\n    return "alice@example.test"\n')
        # Raw strings are not retained by the source graph.
        result = store.sync(self.workspace)
        self.assertNotIn('alice@example.test', json.dumps(result))
        self.assertNotIn('alice@example.test', json.dumps(self.records()))

    def test_domain_query_and_complete_policy_record_integrity(self):
        self.init()
        rows = store.query(self.workspace, kind='policy_rule', domain='orders')['records']
        # Domain vocabulary is controlled by the policy compiler.
        policy = store.read_policy_records(self.workspace)
        domain = policy['rules'][0]['domains'][0]['name']
        self.assertTrue(store.query(self.workspace, kind='policy_rule', domain=domain)['records'])
        filtered = store.read_policy_records(self.workspace, domain=domain)
        self.assertFalse(filtered['coverage']['complete'])
        self.assertTrue(pipeline_policy.query_policy_rules(filtered)['rules'])

    def test_extended_budgets_are_explicit_not_default_capacity(self):
        self.assertEqual(store._budgets({})['max_files'], 25000)
        self.assertEqual(store._budgets({'max_files': 100000})['max_files'], 100000)
        self.assertEqual(store._budgets({})['max_ast_nodes'],20000)
        self.assertEqual(store._budgets({'max_ast_nodes':200000})['max_ast_nodes'],200000)
        for invalid in (200001,True,0):
            with self.assertRaises(store.PipelineError):
                store._budgets({'max_ast_nodes':invalid})
        with self.assertRaises(store.PipelineError):
            store._budgets({'workers': 2})

    def test_extensionless_shell_discovered(self):
        self.write('build', '#!/usr/bin/env bash\nrun() { echo safe; }\n')
        self.init()
        self.assertTrue(any(r['path'] == 'build' and r['language'] == 'Shell' for r in self.records()))

    def test_recovery_source_drift_abandons_unpublished_candidate(self):
        original = self.init()['snapshotId']
        self.write('extra.py', 'class Candidate: pass')
        def interrupt(stage):
            if stage == 'after_prepared_receipt':
                raise OSError('synthetic_crash')
        with patch.object(store, '_checkpoint', interrupt), self.assertRaises(OSError):
            store.sync(self.workspace)
        self.write('extra.py', 'class Later: pass')
        result = store.recover(self.workspace)
        self.assertEqual(result['snapshotId'], original)
        self.assertEqual(store.status(self.workspace)['pendingRecoveryRuns'], 0)
        self.assertNotEqual(store.sync(self.workspace)['snapshotId'], original)

    def test_writer_lock_and_catalog_cas_reject_other_publishers(self):
        self.init()
        with store._lock(self.workspace), self.assertRaisesRegex(store.PipelineError, 'busy'):
            store.sync(self.workspace)
        self.write('new.py', 'class New: pass')
        def interrupt(stage):
            if stage == 'after_snapshot_rename':
                raise OSError('synthetic_crash')
        with patch.object(store, '_checkpoint', interrupt), self.assertRaises(OSError):
            store.sync(self.workspace)
        state_path = self.workspace / 'state.json'
        state = json.loads(state_path.read_text())
        state['currentSnapshot'] = 'ps-' + 'a' * 32
        store._atomic(state_path, state)
        with self.assertRaisesRegex(store.PipelineError, 'compare_and_swap'):
            store.recover(self.workspace)

    def test_windows_dacl_hook_denies_before_payload_write(self):
        path = self.root / 'protected.json'
        with patch.object(store.os, 'name', 'nt'), patch.object(privacy_guard, '_windows_profile_security', side_effect=privacy_guard.PrivacyError('profile_permissions')) as check:
            with self.assertRaises(privacy_guard.PrivacyError):
                store._atomic(path, {'payload': 'synthetic-private'})
            self.assertTrue(check.called)
        self.assertFalse(path.exists())
        self.assertFalse(list(self.root.glob('.tmp-*')))

    def test_rdf_assertion_provenance_and_shapes_emitted(self):
        snapshot = self.init()['snapshotId']
        folder = self.workspace / 'snapshots' / snapshot
        rdf = (folder / 'ontology.ttl').read_text()
        shapes = (folder / 'shapes.ttl').read_text()
        for text in ('prov:wasGeneratedBy', 'prov:wasDerivedFrom', 'co:lineStart', 'co:sourceDigest'):
            self.assertIn(text, rdf)
        for text in ('co:RelationShape', 'co:subject', 'co:predicate', 'co:object', 'sh:minInclusive'):
            self.assertIn(text, shapes)
        self.assertEqual(store.status(self.workspace)['rdfValidation']['shacl'], 'not_run')

    def test_actual_process_exit_recovers_committed_batch_and_hot_journals(self):
        self.init()
        for index in range(70):
            self.write(f'package/item{index:03d}.py', f'class Item{index}: pass')
        script = '''import os,sys
sys.path.insert(0, sys.argv[1])
import pipeline_store as store
count = 0
def checkpoint(stage):
    global count
    if stage == "after_file":
        count += 1
        if count == 65:
            os._exit(73)
store._checkpoint = checkpoint
store.sync(sys.argv[2])
'''
        result = subprocess.run([sys.executable, '-c', script, str(Path(store.__file__).parent), str(self.workspace)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 73)
        result = store.recover(self.workspace)
        self.assertGreaterEqual(result['buildStats']['resumedFiles'], 64)
        self.assertEqual(len(self.records()), result['recordCount'])
        self.assertEqual(store.status(self.workspace)['pendingRecoveryRuns'], 0)

    def test_initial_hard_exit_retains_prepared_acl_for_recovery(self):
        script = '''import os,sys
sys.path.insert(0,sys.argv[1])
import pipeline_store as store
import pipeline_acl
def checkpoint(stage):
    if stage == "after_file":
        os._exit(73)
store._checkpoint = checkpoint
store.initialize(sys.argv[2],sys.argv[3],prepare_workspace=pipeline_acl.initialize_access)
'''
        result = subprocess.run([sys.executable,'-c',script,str(Path(store.__file__).parent),str(self.repo),str(self.workspace)],
                                capture_output=True,timeout=30)
        self.assertEqual(result.returncode,73)
        import pipeline_acl
        self.assertEqual(pipeline_acl.authorize(self.workspace,'manage_access')['decision'],'allow')
        self.assertEqual(store.recover(self.workspace)['status'],'created')

    def test_config_changed_during_analysis_cannot_promote(self):
        old = self.init()['snapshotId']
        self.write('extra.py','class Extra: pass')
        def mutate(stage):
            if stage == 'before_source_recheck':
                path=self.workspace/'pipeline.json'
                config=json.loads(path.read_text());config['repositoryLabel']='Changed synthetic label'
                store._atomic(path,config)
        with patch.object(store,'_checkpoint',mutate),self.assertRaisesRegex(store.PipelineError,'changed'):
            store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'],old)

    def test_resumed_rdf_link_does_not_overwrite_external_file(self):
        self.init()
        outside=self.root/'preserved.txt';outside.write_text('preserved synthetic fixture')
        for hardlink in (False,True):
            with self.subTest(hardlink=hardlink):
                self.write('extra.py','class Extra: pass\n# '+str(hardlink))
                done=[False]
                def inject(stage):
                    if stage=='after_file' and not done[0]:
                        job,_=store._receipts(self.workspace.resolve())[0]
                        target=job/'snapshot'/'ontology.ttl'
                        if hardlink:os.link(outside,target)
                        else:target.symlink_to(outside)
                        done[0]=True
                with patch.object(store,'_checkpoint',inject),self.assertRaisesRegex(store.PipelineError,'destination'):
                    store.sync(self.workspace)
                self.assertEqual(outside.read_text(),'preserved synthetic fixture')

    def test_explicit_large_ast_allows_large_file_without_partial_promotion(self):
        self.write('large.py','x = 1\n' * 5000)
        with self.assertRaisesRegex(store.adapters.AdapterError,'ast_budget'):
            self.init()
        self.workspace=self.root/'large-workspace'
        result=self.init(max_ast_nodes=200000)
        self.assertEqual(result['coverage']['analyzedFiles'],2)
        old=result['snapshotId']
        self.write('large.py','x = 1\n' * 50000)
        with self.assertRaisesRegex(store.adapters.AdapterError,'ast_budget'):
            store.sync(self.workspace)
        self.assertEqual(store.status(self.workspace)['snapshotId'],old)


if __name__ == '__main__':
    unittest.main()
