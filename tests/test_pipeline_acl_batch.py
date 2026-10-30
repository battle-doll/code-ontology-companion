"""One fresh policy observation for conjunctive export permissions."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import pipeline_acl as acl


class AuthorizationBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.chmod(0o700)
        self.path = self.workspace/'access.json'
        self.guard = acl.companion.privacy_guard
        profile = self.guard.build_profile(['Synthetic Batch Private Person'], [], key=b'b'*32)
        self.profile = patch.object(self.guard, 'load_profile', return_value=profile)
        self.loader = self.profile.start()
        self.addCleanup(self.profile.stop)
        env = patch.dict(os.environ, {acl.PRINCIPAL_ENV:'reader'})
        env.start()
        self.addCleanup(env.stop)
        self.policy = {'schemaVersion':1, 'revision':7, 'principals':{
            'reader':{'actions':sorted(acl.ACTIONS), 'snapshots':['one']}}}
        self.write(self.policy)

    def write(self, value):
        self.path.write_text(json.dumps(value,sort_keys=True,separators=(',',':')))
        self.path.chmod(0o600)

    def test_same_decision_as_all_individual_permissions(self):
        actions = sorted(acl.ACTIONS)
        requests = [tuple(actions), ('read_policy','read_evidence'), ('export_html','export_bundle')]
        requests += [(action,) for action in actions]
        for grants in (actions, actions[:3], []):
            for scopes in (['one'], ['*']):
                value = copy.deepcopy(self.policy)
                value['principals']['reader'] = {'actions':grants,'snapshots':scopes}
                self.write(value)
                for snapshot in ('one','two',None):
                    for requested in requests:
                        with self.subTest(grants=grants,scopes=scopes,snapshot=snapshot,requested=requested):
                            try:
                                individual = [acl.authorize(self.workspace,action,snapshot) for action in requested]
                            except acl.AccessDenied:
                                with self.assertRaises(acl.AccessDenied):
                                    acl.authorize_many(self.workspace,requested,snapshot)
                            else:
                                batch = acl.authorize_many(self.workspace,requested,snapshot)
                                self.assertTrue(all(decision == batch for decision in individual))

    def test_one_fresh_read_each_call_not_a_decision_cache(self):
        requested = ('export_html','export_bundle','read_structure','read_policy','read_evidence')
        self.loader.reset_mock()
        with patch.object(acl,'_read',wraps=acl._read) as read:
            first = acl.authorize_many(self.workspace,requested,'one')
            second = acl.authorize_many(self.workspace,requested,'one')
            self.assertEqual(first,second)
            self.assertEqual(read.call_count,2)
            self.assertEqual(self.loader.call_count,2)

    def test_each_required_permission_can_deny_the_whole_batch(self):
        requested = ('export_html','export_bundle','read_structure','read_policy','read_evidence')
        for missing in requested:
            value = copy.deepcopy(self.policy)
            value['principals']['reader']['actions'].remove(missing)
            self.write(value)
            with self.subTest(missing=missing), self.assertRaises(acl.AccessDenied):
                acl.authorize_many(self.workspace,requested,'one')

    def test_same_revision_revoke_with_restored_mtime_is_observed(self):
        requested = ('read_policy','read_evidence')
        acl.authorize_many(self.workspace,requested,'one')
        before = self.path.stat()
        value = copy.deepcopy(self.policy)
        value['principals']['reader']['actions'] = ['read_policy']
        self.write(value)
        os.utime(self.path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaises(acl.AccessDenied):
            acl.authorize_many(self.workspace,requested,'one')

    def test_principal_rebound_between_calls(self):
        acl.authorize_many(self.workspace,('read_policy',),'one')
        for principal in ('unknown','Not An Alias'):
            with patch.dict(os.environ,{acl.PRINCIPAL_ENV:principal}), self.assertRaises(acl.AccessDenied):
                acl.authorize_many(self.workspace,('read_policy',),'one')

    def test_caller_sequence_cannot_shrink_during_policy_read(self):
        value = copy.deepcopy(self.policy)
        value['principals']['reader']['actions'] = ['read_policy']
        self.write(value)
        requested = ['read_policy','read_evidence']
        original = acl._read
        def mutate(workspace):
            requested.pop()
            return original(workspace)
        with patch.object(acl,'_read',side_effect=mutate), self.assertRaises(acl.AccessDenied):
            acl.authorize_many(self.workspace,requested,'one')

    def test_invalid_requests_fail_before_policy_read(self):
        for requested in (None, '', 'read_policy', {}, set(), (), [], ['read_policy']*8,
                          ('read_policy','read_policy'), ('unknown',), ([],), (None,)):
            with self.subTest(requested=requested), patch.object(acl,'_read') as read:
                with self.assertRaises(acl.AccessDenied):
                    acl.authorize_many(self.workspace,requested,'one')
                read.assert_not_called()

    def test_returned_receipt_is_not_reused(self):
        first = acl.authorize_many(self.workspace,('read_policy',),'one')
        first['decision'] = 'changed'
        first['revision'] = 999
        second = acl.authorize_many(self.workspace,('read_policy',),'one')
        self.assertEqual(second['decision'],'allow')
        self.assertEqual(second['revision'],7)

    def test_policy_deleted_after_previous_allow_denies(self):
        acl.authorize_many(self.workspace,('read_policy',),'one')
        self.path.unlink()
        with self.assertRaises(acl.AccessDenied):
            acl.authorize_many(self.workspace,('read_policy',),'one')

    def test_invalid_policy_after_previous_allow_denies(self):
        acl.authorize_many(self.workspace,('read_policy',),'one')
        self.path.write_text('{invalid')
        with self.assertRaises(acl.AccessDenied):
            acl.authorize_many(self.workspace,('read_policy',),'one')

    @unittest.skipIf(os.name=='nt','POSIX mode check; native Windows DACL is separate')
    def test_unsafe_mode_after_previous_allow_denies(self):
        acl.authorize_many(self.workspace,('read_policy',),'one')
        self.path.chmod(0o644)
        with self.assertRaises(acl.AccessDenied):
            acl.authorize_many(self.workspace,('read_policy',),'one')

    def test_profile_changes_are_observed_each_call(self):
        acl.authorize_many(self.workspace,('read_policy',),'one')
        self.loader.side_effect = self.guard.PrivacyError('profile_changed')
        with self.assertRaises(acl.AccessDenied):
            acl.authorize_many(self.workspace,('read_policy',),'one')


if __name__ == '__main__':
    unittest.main()
