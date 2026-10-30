"""Neutral Windows stat-provider emulation; native Windows CI is separate."""
from contextlib import contextmanager
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_export as export
import pipeline_partitioned as partitioned
import privacy_guard


def changed(info,updates=None):
    values={key:getattr(info,key)for key in dir(info)if key.startswith('st_')}
    for key,value in (updates or {}).items():
        values[key]=value(values.get(key,0))if callable(value)else value
    return SimpleNamespace(**values)


class WindowsProviders:
    name='nt'
    O_BINARY=getattr(os,'O_BINARY',0x08000000)
    def __init__(self):
        self.native=os;self.fd_changes={};self.path_changes={};self.read_hook=None
        self.close_hook=None;self.writers={};self.binary={};self.bytes_read=0;self.direntry_stats=0
    def __getattr__(self,name):return getattr(self.native,name)
    def fstat(self,fd):
        info=self.native.fstat(fd)
        if stat.S_ISREG(info.st_mode):
            info=changed(info,{'st_mode':info.st_mode&~0o111,'st_ctime_ns':info.st_ctime_ns+1000000,
                               'st_birthtime_ns':300000,'st_file_attributes':0})
            return changed(info,self.fd_changes)
        return info
    def path_stat(self,info):
        if not stat.S_ISREG(info.st_mode):return info
        # Path mode/creation time differ from handle mode/change time.
        info=changed(info,{'st_mode':info.st_mode|0o100,'st_ctime_ns':1000,
                           'st_birthtime_ns':300000,'st_file_attributes':0})
        return changed(info,self.path_changes)
    def open(self,path,flags,*args,**kwargs):
        native_flags=flags if hasattr(os,'O_BINARY')else flags&~self.O_BINARY
        fd=self.native.open(path,native_flags,*args,**kwargs);self.binary[fd]=bool(flags&self.O_BINARY)
        if flags&os.O_WRONLY:self.writers[fd]=Path(path)
        return fd
    def close(self,fd):
        path=self.writers.pop(fd,None);self.binary.pop(fd,None);self.native.close(fd)
        if path is not None and self.close_hook:self.close_hook(path)
    def observed_read(self,raw):
        self.bytes_read+=len(raw)
        if self.read_hook:
            hook=self.read_hook;self.read_hook=None;hook()
        return raw
    def read(self,fd,maximum):
        raw=self.native.read(fd,maximum)
        if not self.binary.get(fd):raw=raw.replace(b'\r\n',b'\n').split(b'\x1a',1)[0]
        return self.observed_read(raw)
    def fdopen(self,*args,**kwargs):
        stream=self.native.fdopen(*args,**kwargs);owner=self
        class Observed:
            def __getattr__(self,name):return getattr(stream,name)
            def __enter__(self):stream.__enter__();return self
            def __exit__(self,*values):return stream.__exit__(*values)
            def read(self,*values):return owner.observed_read(stream.read(*values))
        return Observed()
    @contextmanager
    def scandir(self,path):
        owner=self
        class Entry:
            def __init__(self,entry):self.entry=entry;self.name=entry.name
            def stat(self,**kwargs):
                owner.direntry_stats+=1
                return changed(self.entry.stat(**kwargs),{'st_dev':0,'st_ino':0,'st_nlink':0})
        with self.native.scandir(path)as entries:yield (Entry(entry)for entry in entries)


class WindowsArtifactMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.counter=0;self.io=WindowsProviders()
        self.security=b'neutral-private-owner-and-dacl';self.security_hook=None
        original=(export._guard,export._canonical,export._validate_record,export._policy_projection,
                  partitioned._store,partitioned._exporter,partitioned._guard)
        def restore():
            (export._guard,export._canonical,export._validate_record,export._policy_projection,
             partitioned._store,partitioned._exporter,partitioned._guard)=original
        self.addCleanup(restore)
        def security(fd,**kwargs):return self.security_hook(fd)if self.security_hook else self.security
        guard=SimpleNamespace(ensure_public_safe=privacy_guard.ensure_public_safe,
            _link_like=privacy_guard._link_like,_check_private_file_metadata=privacy_guard._check_private_file_metadata,
            _windows_profile_security=security)
        export.configure(privacy_guard=guard,canonical=lambda value:json.dumps(value,sort_keys=True).encode())
        partitioned.configure(store=None,exporter=export,privacy_guard=guard)
        original_lstat=type(self.root).lstat;original_bound=export._BoundArtifacts
        def path_lstat(path,*args,**kwargs):return self.io.path_stat(original_lstat(path,*args,**kwargs))
        def bound(output,parent_identity):
            value=original_bound.__new__(original_bound)
            value.output=output;value.parent=output.parent;value.parent_identity=parent_identity
            value.parent_fd=None;value.stage_fd=None;value.stage=None;value.entries={}
            value.published=False;value.root_identity=None
            # Provider-shape fixture only; native handle custody is verified
            # separately by the Windows boundary and native CI tests.
            value.windows=SimpleNamespace(pending_rename=False,stable=lambda:None,bind_stage=lambda path:None,
                verify_stage=lambda path:None,remove_stage=lambda path:self.io.rmdir(path),close=lambda:None)
            return value
        for replacement in (patch.object(export,'os',self.io),patch.object(partitioned,'os',self.io),
                            patch.object(type(self.root),'lstat',path_lstat),patch.object(export,'_BoundArtifacts',side_effect=bound)):
            replacement.start();self.addCleanup(replacement.stop)
    def boundary(self,policy=False):
        self.counter+=1;db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        cls=partitioned._PolicyBoundary if policy else partitioned._SetBoundary
        value=cls(self.root/('set-'+str(self.counter)),db);self.addCleanup(value.close);return value
    def child(self,output):
        value=export._BoundArtifacts(output,export._safe_parent(output));value.create_stage()
        self.addCleanup(value.close);return value
    def test_postclose_observer_adoption_read_validation_and_cleanup(self):
        for policy in (False,True):
            with self.subTest(policy=policy):
                boundary=self.boundary(policy);boundary.mkdir('parts')
                child=self.child(boundary.stage/'parts/business');observe=boundary.observer('parts/business')
                raw=b'{"neutral":true}'
                for language in export.LANGUAGES:
                    name=language+'/records/one.json';start=self.io.bytes_read
                    info=child.write(name,raw)
                    self.assertEqual(info.st_ctime_ns,1000)
                    self.assertEqual(self.io.bytes_read-start,len(raw))
                    observe(name,{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},info)
                os.rename(child.stage,child.output);child.published=True
                boundary.adopt('parts/business',lambda:None)
                self.assertEqual(self.io.direntry_stats,0)
                for language in export.LANGUAGES:
                    name='parts/business/'+language+'/records/one.json'
                    self.assertEqual(boundary.read_record(name),raw)
                boundary.write('index.json',raw)
                if policy:boundary.validate_policy(lambda:None,lambda value:None)
                else:boundary.validate(lambda:None)
                self.assertEqual(boundary.cleanup()['status'],'OWN_ENTRIES_REMOVED')
    def test_hash_and_record_reject_late_full_provider_changes(self):
        for operation in ('hash','record'):
            for provider in ('fd','path'):
                for field in ('st_mode','st_ctime_ns','st_birthtime_ns','st_file_attributes','st_ino'):
                    with self.subTest(operation=operation,provider=provider,field=field):
                        self.io.fd_changes={};self.io.path_changes={}
                        boundary=self.boundary();boundary.write('one.json',b'neutral')
                        changes=self.io.fd_changes if provider=='fd'else self.io.path_changes
                        # Mode remains private and regular; attrs remain non-reparse.
                        value=(lambda mode:mode^0o100)if field=='st_mode'else(lambda number:number+1)
                        self.io.read_hook=lambda:changes.update({field:value})
                        with self.assertRaises(ValueError):
                            if operation=='hash':boundary._hash_open(boundary.stage,'one.json',lambda:None)
                            else:boundary.read_record('one.json')
                        self.io.fd_changes={};self.io.path_changes={}
    def test_reparse_and_content_mutations_are_rejected(self):
        for operation in ('hash','record'):
            for provider in ('fd','path'):
                boundary=self.boundary();boundary.write('one.json',b'neutral')
                changes=self.io.fd_changes if provider=='fd'else self.io.path_changes
                self.io.read_hook=lambda:changes.update({'st_file_attributes':0x400})
                with self.assertRaises(ValueError):
                    if operation=='hash':boundary._hash_open(boundary.stage,'one.json',lambda:None)
                    else:boundary.read_record('one.json')
                self.io.fd_changes={};self.io.path_changes={}
        boundary=self.boundary();boundary.write('one.json',b'neutral')
        before=(boundary.stage/'one.json').stat();(boundary.stage/'one.json').write_bytes(b'changed')
        os.utime(boundary.stage/'one.json',ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'partitioned_artifact_changed'):boundary.read_record('one.json')
    def test_closed_writer_cannot_reseal_replacement_owner_size_or_bytes(self):
        for mutation in ('replacement','owner','size','bytes','reparse','security'):
            with self.subTest(mutation=mutation):
                self.io.fd_changes={};self.io.path_changes={};self.security_hook=None
                boundary=self.boundary();raw=b'neutral'
                def change(path):
                    self.io.close_hook=None
                    if mutation=='replacement':
                        other=path.with_name('replacement');other.write_bytes(raw);other.chmod(0o600);os.replace(other,path)
                    elif mutation=='owner':self.io.path_changes={'st_uid':lambda uid:uid+1}
                    elif mutation=='size':path.write_bytes(raw+b'!')
                    elif mutation=='bytes':path.write_bytes(b'changed')
                    elif mutation=='reparse':self.io.path_changes={'st_file_attributes':0x400}
                    else:self.security_hook=lambda fd:b'changed-private-owner-and-dacl'
                self.io.close_hook=change;start=self.io.bytes_read
                with self.assertRaises(ValueError):boundary.write('one.json',raw)
                self.assertLessEqual(self.io.bytes_read-start,len(raw)+1)
                self.assertIsNone(boundary.saved('one.json'))
                self.io.fd_changes={};self.io.path_changes={};self.security_hook=None
                cleanup=boundary.cleanup()
                self.assertEqual(cleanup['status'],'UNKNOWN_OR_CHANGED_ENTRIES_RETAINED')
                self.assertGreater(cleanup['retained'],0)
                self.assertTrue((boundary.stage/'one.json').exists())
    def test_uncertain_stage_handoff_and_pending_cleanup_preserve_all_files(self):
        for flag in ('pending_rename','stage_handoff_failed'):
            with self.subTest(flag=flag):
                boundary=self.boundary();boundary.write('one.json',b'neutral')
                setattr(boundary.bound.windows,flag,True)
                with patch.object(partitioned.os,'unlink') as unlink,patch.object(partitioned.os,'rmdir') as rmdir:
                    result=boundary.cleanup()
                unlink.assert_not_called();rmdir.assert_not_called()
                self.assertEqual(result['status'],'UNVERIFIED_RETAINED')
                self.assertEqual(result['removed'],0);self.assertTrue((boundary.stage/'one.json').exists())
    def test_postclose_reread_preserves_binary_payload(self):
        raw=b'neutral\r\n\x1a\x00tail';boundary=self.boundary();boundary.write('one.json',raw)
        self.assertEqual(boundary.read_record('one.json'),raw)
        child=self.child(self.root/'binary-child');child.write('one.json',raw)
        self.assertEqual((child.stage/'one.json').read_bytes(),raw)
    def test_parent_and_exact_worker_hash_preserve_binary_bytes(self):
        raw=b'neutral\r\n\x1a\x00tail';path=self.root/'raw-runtime.bin';path.write_bytes(raw);path.chmod(0o600)
        expected=hashlib.sha256(raw).hexdigest()
        self.assertEqual(partitioned._policy_bounded_hash(path,1024),(expected,len(raw)))
        # Execute the actual isolated bootstrap hash definitions, not a second
        # test implementation. Full process isolation remains a separate gate.
        names={'identity','same_open_file','sha'}
        definitions=[node for node in ast.walk(ast.parse(partitioned._POLICY_WORKER_BOOTSTRAP))
                     if isinstance(node,ast.FunctionDef)and node.name in names]
        self.assertEqual({node.name for node in definitions},names)
        namespace={'os':self.io,'stat':stat,'hashlib':hashlib,'time':time,'deadline':time.monotonic()+5}
        exec(compile(ast.Module(body=definitions,type_ignores=[]),'<verified-worker-hash>','exec'),namespace)
        digest,amount,retained,_=namespace['sha'](path,1024,True)
        self.assertEqual((digest,amount,retained),(expected,len(raw),raw))
    def test_unknown_entries_are_preserved_and_reported(self):
        boundary=self.boundary();boundary.write('one.json',b'neutral')
        foreign=boundary.stage/'foreign.json';foreign.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'partitioned_artifact_set_changed'):boundary.validate(lambda:None)
        cleanup=boundary.cleanup();self.assertNotEqual(cleanup['status'],'OWN_ENTRIES_REMOVED')
        self.assertGreater(cleanup['retained'],0);self.assertTrue(foreign.exists())


if __name__=='__main__':unittest.main()
