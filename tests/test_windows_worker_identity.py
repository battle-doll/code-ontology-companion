"""Native-provider IPC models; real mixed-Python Windows CI is separate."""
import copy
import ctypes
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_windows_artifact_metadata import WindowsProviders, export, partitioned, privacy_guard
from test_business_export import Function
from test_windows_stage_custody import SharingApi


class NativeIdentityApi:
    def __init__(self):
        self.volume=0x9988776655443322;self.high=0x123456789abcdef0
        self.handles={};self.closed=[];self.changes={};self.unsupported=False;self.close_ok=True
        self.security_value=b'k'*32;self.queries=[]
        self.CreateFileW=Function(self.open);self.CloseHandle=Function(self.close)
        self.GetFileInformationByHandleEx=Function(self.query)
    def open(self,path,*args):
        handle=100000+len(self.handles);self.handles[handle]=Path(path);return handle
    def close(self,handle):self.closed.append(handle);self.handles.pop(handle,None);return self.close_ok
    def security(self,handle,**kwargs):return self.security_value
    def query(self,handle,kind,pointer,size):
        if self.unsupported:return 0
        self.queries.append(kind)
        info=self.handles[handle].stat()if handle in self.handles else os.fstat(handle)
        values=dict(volume=self.volume,id=(self.high<<64)|info.st_ino,attributes=0x10 if __import__('stat').S_ISDIR(info.st_mode)else 0x20,
                    links=info.st_nlink,size=info.st_size,created=10000,modified=20000,changed=30000)
        for key,value in self.changes.items():values[key]=value(values[key])if callable(value)else value
        target=pointer._obj
        if kind==18:
            target.volume=values['volume'];target.identity[:]=values['id'].to_bytes(16,'little')
        elif kind==0:
            target.created=values['created'];target.modified=values['modified'];target.changed=values['changed'];target.attributes=values['attributes']
        elif kind==1:
            target.size=values['size'];target.links=values['links'];target.directory=bool(values['attributes']&0x10)
        else:return 0
        return 1


class WindowsWorkerIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.path=self.root/'policy-projection-set.json'
        self.raw=b'neutral\r\n\x1a\x00tail';self.path.write_bytes(self.raw);self.path.chmod(0o600)
        self.api=NativeIdentityApi();self.view=WindowsProviders()
        self.sharing=SharingApi();boundary_class=export._WindowsBoundary
        guard=SimpleNamespace(_link_like=privacy_guard._link_like,
            _check_private_file_metadata=privacy_guard._check_private_file_metadata,
            _windows_profile_security=self.api.security)
        original_lstat=type(self.root).lstat
        def lstat(path,*args,**kwargs):return self.view.path_stat(original_lstat(path,*args,**kwargs))
        for replacement in (patch.object(export,'_guard',guard),patch.object(export,'os',self.view),
                patch.object(partitioned,'os',self.view),patch.object(partitioned,'_exporter',export),
                patch.object(type(self.root),'lstat',lstat),
                patch.object(export,'_WindowsBoundary',side_effect=lambda path:boundary_class(path,library=self.sharing))):
            replacement.start();self.addCleanup(replacement.stop)
    def file_proof(self,**kwargs):
        return export._windows_worker_attestation(self.path,maximum=1024,library=self.api,**kwargs)
    def directory_proof(self,**kwargs):
        return export._windows_worker_attestation(self.root,directory=True,library=self.api,**kwargs)
    def response(self):
        directory,_=self.directory_proof();manifest,digest=self.file_proof()
        return dict(outputIdentity=directory,manifestIdentity=manifest,manifestSha256=digest)
    def test_full_native_identity_is_stable_across_python_width_models(self):
        proofs=[]
        for device in (self.api.volume&0xffffffff,self.api.volume):
            self.view.path_changes={'st_dev':device};self.view.fd_changes={'st_dev':device}
            proof,digest=self.file_proof();proofs.append(proof)
            self.assertEqual(digest,hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(proofs[0],proofs[1]);self.assertEqual(proofs[0]['volume'],self.api.volume)
        self.assertEqual(int.from_bytes(bytes.fromhex(proofs[0]['id']),'little')>>64,self.api.high)
        self.assertEqual((ctypes.sizeof(export._WinFileIdInfo),export._WinFileIdInfo.identity.offset),(24,8))
    def test_strict_provider_and_high_bits_mismatches_never_fall_back(self):
        original=self.response()
        with patch.object(partitioned,'_windows_policy_attestation',return_value=original):
            partitioned._verify_windows_policy_attestation(self.root,copy.deepcopy(original),lambda:None)
            for field in ('volume','id'):
                changed=copy.deepcopy(original)
                if field=='volume':changed['manifestIdentity']['volume']^=1<<40
                else:
                    value=int.from_bytes(bytes.fromhex(changed['manifestIdentity']['id']),'little')^(1<<100)
                    changed['manifestIdentity']['id']=value.to_bytes(16,'little').hex()
                with self.assertRaisesRegex(ValueError,'partitioned_worker_output_changed'):
                    partitioned._verify_windows_policy_attestation(self.root,changed,lambda:None)
            for bad in ('unknown_provider','bool_volume','extra','short_id'):
                changed=copy.deepcopy(original);proof=changed['manifestIdentity']
                if bad=='unknown_provider':proof['provider']='legacy'
                elif bad=='bool_volume':proof['volume']=True
                elif bad=='extra':proof['unexpected']=0
                else:proof['id']='1'
                with self.assertRaisesRegex(ValueError,'partitioned_worker_result_invalid'):
                    partitioned._verify_windows_policy_attestation(self.root,changed,lambda:None)
    def test_unsupported_api_and_directory_close_failure_are_explicit(self):
        self.api.unsupported=True
        with self.assertRaisesRegex(ValueError,'export_identity_provider_unsupported'):self.directory_proof()
        self.assertEqual(len(self.api.closed),1);self.assertFalse(self.api.handles)
        self.api.unsupported=False;self.api.close_ok=False
        with self.assertRaisesRegex(ValueError,'export_identity_handle_close_failed'):self.directory_proof()
        with self.assertRaisesRegex(ValueError,'export_identity_provider_unsupported'):
            export._windows_worker_attestation(self.root,directory=True,library=SimpleNamespace())
        class WrongAbi(ctypes.Structure):_fields_=[('identity',ctypes.c_ubyte)]
        with patch.object(export,'_WinFileIdInfo',WrongAbi):
            with self.assertRaisesRegex(ValueError,'export_identity_provider_unsupported'):self.file_proof()
        original_close=self.view.close
        def failed_close(fd):original_close(fd);raise OSError('neutral close failure')
        with patch.object(self.view,'close',side_effect=failed_close):
            with self.assertRaisesRegex(ValueError,'export_identity_handle_close_failed'):self.file_proof()
    def test_native_and_provider_mutations_during_hash_are_rejected(self):
        for field in ('volume','id','attributes','links','size','created','modified','changed','security'):
            with self.subTest(field=field):
                self.api.changes={};self.api.security_value=b'k'*32
                def mutate():
                    if field=='security':self.api.security_value=b'x'*32
                    else:self.api.changes[field]=lambda value:value+1
                self.view.read_hook=mutate
                with self.assertRaises(ValueError):self.file_proof()
        self.api.changes={};self.api.security_value=b'k'*32
        self.view.read_hook=lambda:self.view.path_changes.update({'st_ctime_ns':1001})
        with self.assertRaisesRegex(ValueError,'export_artifact_changed'):self.file_proof()
        self.view.path_changes={};self.api.changes={'attributes':0x420}
        with self.assertRaises(ValueError):self.file_proof()
    def test_original_producer_handle_and_manifest_are_bound_before_close(self):
        borrowed=self.api.open(str(self.root));identity=export._artifact_file_identity(self.path.lstat())
        checked=[];boundary=SimpleNamespace(bound=SimpleNamespace(
            windows=SimpleNamespace(stage_handle=borrowed,stage_security=b'k'*32),
            verify_published=lambda:checked.append(True)),saved=lambda name:('file',identity),
            info=lambda name:{'sha256':hashlib.sha256(self.raw).hexdigest()})
        real=export._windows_worker_attestation
        def native(path,**kwargs):return real(path,library=self.api,**kwargs)
        with patch.object(export,'_windows_worker_attestation',side_effect=native):
            result=partitioned._windows_policy_attestation(self.root,lambda:None,boundary=boundary)
            self.assertEqual(result['manifestSha256'],hashlib.sha256(self.raw).hexdigest())
            self.assertEqual(checked,[True,True]);self.assertNotIn(borrowed,self.api.closed)
            wrong=list(identity);wrong[1]+=1;boundary.saved=lambda name:('file',tuple(wrong))
            with self.assertRaisesRegex(ValueError,'partitioned_worker_output_changed'):
                partitioned._windows_policy_attestation(self.root,lambda:None,boundary=boundary)
        self.api.close(borrowed)
    def test_directory_contract_ignores_child_times_and_posix_wire_is_unchanged(self):
        first,_=self.directory_proof();self.api.changes={'modified':99999,'changed':88888,'size':77777}
        second,_=self.directory_proof();self.assertEqual(first,second)
        self.assertNotIn('modified',first);self.assertNotIn('size',first)
        self.assertEqual(partitioned._policy_worker_response_format(),'companion.private-policy-worker-response.v2')
        with patch.object(partitioned,'os',SimpleNamespace(name='posix')):
            self.assertEqual(partitioned._policy_worker_response_format(),'companion.private-policy-worker-response.v1')
    def test_parent_root_swap_is_blocked_until_comparison_and_locks_release(self):
        original=self.response();attempts=[]
        def observe(*args,**kwargs):
            handle=self.sharing.CreateFileW(str(self.root),0x10000,7,None,3,0x02200000,None)
            attempts.append(handle);self.assertEqual(handle,ctypes.c_void_p(-1).value)
            return original
        with patch.object(partitioned,'_windows_policy_attestation',side_effect=observe):
            partitioned._verify_windows_policy_attestation(self.root,original,lambda:None)
            self.assertFalse(self.sharing.live)
            changed=copy.deepcopy(original);changed['manifestSha256']='a'*64
            with self.assertRaisesRegex(ValueError,'partitioned_worker_output_changed'):
                partitioned._verify_windows_policy_attestation(self.root,changed,lambda:None)
            self.assertFalse(self.sharing.live);self.assertEqual(len(attempts),2)
            close=self.sharing.CloseHandle.function
            self.sharing.CloseHandle=Function(lambda handle:close(handle)and 0)
            with self.assertRaisesRegex(ValueError,'partitioned_identity_handle_close_failed'):
                partitioned._verify_windows_policy_attestation(self.root,original,lambda:None)
    def test_single_temporary_close_failure_is_not_masked_by_final_closes(self):
        original=self.response();close=self.sharing.CloseHandle.function;returns=[]
        def once(handle):
            result=close(handle);returns.append(0 if not returns else result);return returns[-1]
        self.sharing.CloseHandle=Function(once)
        with patch.object(partitioned,'_windows_policy_attestation',return_value=original):
            with self.assertRaisesRegex(partitioned.PartitionedExportError,'partitioned_identity_handle_close_failed'):
                partitioned._verify_windows_policy_attestation(self.root,original,lambda:None)
        self.assertGreater(len(returns),1);self.assertEqual(returns[0],0)
        self.assertTrue(all(returns[1:]));self.assertFalse(self.sharing.live)


if __name__=='__main__':unittest.main()
