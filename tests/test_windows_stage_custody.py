"""Windows sharing-rule and stage-handoff emulation; native CI is separate."""
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_business_export import WindowsApi, Function, export, guard


class SharingApi(WindowsApi):
    """Apply the documented two-way DELETE/share compatibility rule."""
    def __init__(self):
        super().__init__();self.live={};self.fail_paths=set();self.security_versions={}
        self.release_handle=None;self.on_release=None;self.closed_at_native=None
        self.CloseHandle=Function(self.close_handle)
    def create(self,path,access,share,*arguments):
        if path in self.fail_paths:return ctypes.c_void_p(-1).value
        identity=self.by_path.get(path)
        for previous in self.live.values():
            if previous['identity']==identity and (
                    access&0x10000 and not previous['share']&4
                    or previous['access']&0x10000 and not share&4):
                return ctypes.c_void_p(-1).value
        handle=super().create(path,access,share,*arguments)
        self.live[handle]={'path':path,'access':access,'share':share,'identity':self.identities[handle]}
        return handle
    def close_handle(self,handle):
        self.live.pop(handle,None);self.closed.append(handle)
        if handle==self.release_handle and self.on_release:
            callback=self.on_release;self.on_release=None;callback()
        return 1
    def security(self,handle,**kwargs):
        return self.security_versions.get(self.identities[handle],b'original-private-owner-dacl')
    def set_info(self,*arguments):
        self.closed_at_native=list(self.closed)
        return super().set_info(*arguments)


class WindowsStageCustodyTests(unittest.TestCase):
    def setUp(self):
        self.api=SharingApi();self.parent=Path('/neutral/parent')
        for replacement in (
                patch.object(export,'_guard',SimpleNamespace(PrivacyError=guard.PrivacyError,
                    _windows_profile_security=self.api.security)),
                patch.object(export,'_WINDOWS_PENDING_RENAMES',[])):
            replacement.start();self.addCleanup(replacement.stop)
    def boundary(self,parent=None):
        value=export._WindowsBoundary(parent or self.parent,library=self.api)
        self.addCleanup(value.close);return value
    def retained_cleanup(self,boundary,path):
        bound=export._BoundArtifacts.__new__(export._BoundArtifacts)
        bound.stage=path;bound.windows=boundary;bound.entries={'neutral':None}
        with patch.object(export.os,'unlink')as unlink,patch.object(export.os,'rmdir')as rmdir:
            result=bound.cleanup()
        unlink.assert_not_called();rmdir.assert_not_called()
        self.assertEqual(result['removed'],0);return result
    def test_nested_construction_remains_locked_and_both_publish(self):
        outer=self.boundary();outer_path=self.parent/'outer';outer.bind_stage(outer_path)
        construction=outer.stage_handle
        self.assertFalse(self.api.live[construction]['access']&0x10000)
        self.assertFalse(self.api.live[construction]['share']&4)
        # An external delete/rename request is denied throughout construction.
        external=self.api.CreateFileW(str(outer_path),0x10000,7,None,3,0x02200000,None)
        self.assertEqual(external,ctypes.c_void_p(-1).value)
        child=self.boundary(outer_path/'business');child_path=outer_path/'business/stage'
        child.bind_stage(child_path);child.rename('part');child.close()
        outer.rename('result')
        self.assertEqual([item['name']for item in self.api.rename],['part','result'])
        self.assertTrue(outer.stage_delete_ready);self.assertFalse(outer.stage_handoff_failed)
        self.assertTrue(self.api.live[outer.stage_handle]['access']&0x10000)
        self.assertTrue(self.api.live[outer.stage_handle]['access']&0x100000)
        # No ancestor lock was relaxed to make nesting work.
        for path,access,share,*_ in self.api.opened:
            if not access&0x20000:self.assertEqual(share,3)
    def test_handoff_replacement_dacl_reparse_missing_and_parent_change_retain(self):
        for mode in ('replacement','dacl','reparse','missing','parent'):
            with self.subTest(mode=mode):
                self.api.reparse=False;self.api.fail_paths.clear()
                boundary=self.boundary();path=self.parent/('stage-'+mode);boundary.bind_stage(path)
                original=boundary.stage_identity;self.api.release_handle=boundary.stage_handle
                def change():
                    if mode=='replacement':self.api.by_path[str(path)]=999
                    elif mode=='dacl':self.api.security_versions[original[-1]]=b'changed-private-dacl'
                    elif mode=='reparse':self.api.reparse=True
                    elif mode=='missing':self.api.fail_paths.add(str(path))
                    else:self.api.by_path[str(self.parent)]=888
                self.api.on_release=change;native_before=len(self.api.rename)
                with self.assertRaises(export.BusinessExportError):boundary.rename('result')
                self.assertTrue(boundary.stage_handoff_failed)
                self.assertEqual(len(self.api.rename),native_before)
                self.assertEqual(self.retained_cleanup(boundary,path)['status'],'UNVERIFIED_RETAINED')
                opened=len(self.api.opened)
                with self.assertRaises(export.BusinessExportError):boundary.rename('again')
                self.assertEqual(len(self.api.opened),opened)
                boundary.close();self.api.reparse=False;self.api.fail_paths.clear()
                # Give the next independent scenario a fresh parent binding.
                self.api.by_path.pop(str(self.parent),None)
    def test_original_creation_dacl_cannot_be_replaced_before_upgrade(self):
        boundary=self.boundary();path=self.parent/'stage';boundary.bind_stage(path)
        self.api.security_versions[boundary.stage_identity[-1]]=b'changed-private-dacl'
        with self.assertRaisesRegex(export.BusinessExportError,'export_directory_permissions_changed'):
            boundary.verify_stage(path)
        self.assertFalse(self.api.rename)
        self.assertIn(boundary.stage_handle,self.api.live)
    def test_final_delete_open_refuses_unclosed_nested_ancestor_locks(self):
        outer=self.boundary();path=self.parent/'outer';outer.bind_stage(path)
        child=self.boundary(path/'business');child.bind_stage(path/'business/stage')
        with self.assertRaisesRegex(export.BusinessExportError,'export_windows_directory_open_failed'):
            outer.rename('result')
        self.assertTrue(outer.stage_handoff_failed);self.assertFalse(self.api.rename)
        self.assertEqual(self.retained_cleanup(outer,path)['status'],'UNVERIFIED_RETAINED')
        child.close()
    def test_pending_keeps_upgraded_handles_memory_and_cleanup_blocked(self):
        boundary=self.boundary();path=self.parent/'stage';boundary.bind_stage(path);self.api.pending=True
        with self.assertRaisesRegex(export.BusinessExportError,'export_publication_completion_unknown'):
            boundary.rename('result')
        self.assertTrue(boundary.pending_rename);self.assertTrue(boundary.stage_delete_ready)
        self.assertEqual(len(self.api.allocations),1);self.assertFalse(self.api.freed)
        boundary.close();self.assertEqual(self.api.closed,self.api.closed_at_native)
        self.assertEqual(self.retained_cleanup(boundary,path)['status'],'UNKNOWN_WINDOWS_PUBLICATION_RETAINED')
        opened=len(self.api.opened);renamed=len(self.api.rename)
        with self.assertRaisesRegex(export.BusinessExportError,'export_publication_completion_unknown'):
            self.boundary()
        self.assertEqual((len(self.api.opened),len(self.api.rename)),(opened,renamed))


if __name__=='__main__':unittest.main()
