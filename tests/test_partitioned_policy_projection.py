"""Bounded actual policy coordinator tests. Large one-shot proof is private."""
import ast
import copy
import hashlib
import stat
from types import SimpleNamespace
from contextlib import contextmanager
from html.parser import HTMLParser
import json
import os
import shutil
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import companion
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as source


class Pages(HTMLParser):
    def __init__(self,text):super().__init__();self.ids=[];self.links=[];self.scripts=0;self.data=[];self.current=None;self.feed(text)
    def handle_starttag(self,tag,items):
        attrs=dict(items)
        if tag=='script':self.scripts+=1
        if 'id' in attrs:self.ids.append(attrs['id'])
        if 'href' in attrs:self.links.append(attrs['href'])
        if tag=='pre' and attrs.get('class')=='record-json':self.current=''
    def handle_data(self,value):
        if self.current is not None:self.current+=value
    def handle_endtag(self,tag):
        if tag=='pre' and self.current is not None:self.data.append(json.loads(self.current));self.current=None


class PartitionedPolicyTests(unittest.TestCase):
    def setUp(self):
        from test_business_projection_boundaries import BusinessProjectionBoundaryTests
        self.f=BusinessProjectionBoundaryTests('runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;f.meta=f.store.build(f.workspace,f.sid,partition_size=10000)
        f.review([f.item('one'),f.item('two')]);f.grant(['read_policy','export_html'])
        self.module=companion.core._load_bundled_helper('pipeline_partitioned')
        self.module.configure(store=f.store,exporter=f.exporter,privacy_guard=companion.privacy_guard)
        self.runtime=os.environ.get('CODE_ONTOLOGY_TEST_EXPORT_PYTHON',sys.executable)
        profile_path=f.root/'worker-profile.json';profile_path.write_text(json.dumps(f.profile));profile_path.chmod(0o600)
        env=patch.dict(os.environ,{companion.privacy_guard.PROFILE_ENV:str(profile_path)});env.start();self.addCleanup(env.stop)
    def run_export(self,name='set',**extra):
        f=self.f;params=dict(max_output_bytes=256*1024**2,profile=f.profile,profile_roots=[f.workspace],
            projection='policy_projection',partitioned=True,partition_size=2,export_python=self.runtime);params.update(extra)
        with patch.dict(os.environ,{acl.PRINCIPAL_ENV:'reader'}):return access.export_business_view(f.workspace,f.sid,f.meta,f.root/name,**params)
    def rows(self,name='set'):
        root=self.f.root/name;manifest=json.loads((root/'policy-projection-set.json').read_text(encoding='utf-8'))
        def walk(desc):
            value=json.loads((root/desc['path']).read_text(encoding='utf-8'))['rows']
            if desc['level']:
                for child in value:yield from walk(child)
            else:yield from value
        chunks=list(walk(manifest['catalogRoots']['chunks']))
        return manifest,[json.loads(line) for chunk in chunks for line in (root/chunk['path']).read_text(encoding='utf-8').splitlines()],walk
    def _worker_hash(self):
        tree=ast.parse(self.module._POLICY_WORKER_BOOTSTRAP)
        functions={node.name:node for node in ast.walk(tree)if isinstance(node,ast.FunctionDef)and node.name in ('identity','same_open_file','sha')}
        self.assertEqual(set(functions),{'identity','same_open_file','sha'})
        body=ast.Module(body=[functions[name]for name in ('identity','same_open_file','sha')],type_ignores=[])
        namespace=dict(os=os,stat=stat,time=time,hashlib=hashlib,deadline=time.monotonic()+30)
        exec(compile(ast.fix_missing_locations(body),'<trusted-worker-hash-regression>','exec'),namespace)
        return namespace['sha']
    def test_windows_stat_provider_binding_keeps_each_provider_change_guards(self):
        path=self.f.root/'metadata.exe';path.write_bytes(b'neutral')
        before=path.lstat();real_fstat=os.fstat;real_lstat=type(path).lstat
        names=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns','st_uid','st_file_attributes','st_reparse_tag','st_birthtime_ns')
        def fields(info):return {name:getattr(info,name)for name in names if hasattr(info,name)}
        for helper in (self.module._policy_bounded_hash,self._worker_hash()):
            for mutation in (None,'fd_ctime','fd_mode','path_ctime','path_mode','inode','nlink','size','mtime','type','reparse'):
                with self.subTest(helper=helper.__name__,mutation=mutation):
                    calls=[0];path_calls=[0]
                    def observed_fd(fd):
                        calls[0]+=1;values=fields(real_fstat(fd));values['st_mode']=stat.S_IFREG|0o600
                        values['st_ctime_ns']=before.st_ctime_ns+100
                        if mutation=='fd_ctime'and calls[0]>1:values['st_ctime_ns']+=1
                        if mutation=='fd_mode'and calls[0]>1:values['st_mode']^=0o200
                        if mutation=='inode':values['st_ino']+=1
                        if mutation=='nlink':values['st_nlink']+=1
                        if mutation=='size':values['st_size']+=1
                        if mutation=='mtime':values['st_mtime_ns']+=1
                        if mutation=='type':values['st_mode']=stat.S_IFDIR|0o600
                        if mutation=='reparse':values['st_file_attributes']=0x400
                        return SimpleNamespace(**values)
                    def observed_path(selected,*args,**kwargs):
                        result=real_lstat(selected,*args,**kwargs)
                        if selected!=path:return result
                        path_calls[0]+=1;values=fields(result)
                        if path_calls[0]>1 and mutation=='path_ctime':values['st_ctime_ns']+=1
                        if path_calls[0]>1 and mutation=='path_mode':values['st_mode']^=0o100
                        return SimpleNamespace(**values)
                    with patch.object(os,'name','nt'),patch.object(os,'fstat',observed_fd),patch.object(type(path),'lstat',observed_path):
                        if mutation is None:
                            digest,amount=helper(path,1024)[:2]
                            self.assertEqual((digest,amount),(hashlib.sha256(b'neutral').hexdigest(),7))
                        else:
                            with self.assertRaises(ValueError):helper(path,1024)

    def test_real_store_global_projection_and_five_locale_native_routes(self):
        f=self.f;result=self.run_export();manifest,rows,walk=self.rows()
        with f.reader() as reader:expected=[f.query.project_record(row,evidence=False) for row in reader.iter_records(page_size=100)]
        self.assertEqual(rows,expected);self.assertEqual(result['recordCount'],f.meta['recordCount'])
        self.assertGreater(result['windowCount'],1);self.assertEqual(manifest['metadata'],f.query._metadata(f.meta))
        self.assertNotIn('files',result);self.assertEqual(manifest['permissionsChecked'],['read_policy','export_html'])
        routes=list(walk(manifest['catalogRoots']['routes']))
        for lang in self.module.LANGUAGES:
            actual=[]
            for path in sorted((f.root/'set/parts').glob('*/'+lang+'/page-*.html')):actual.extend(Pages(path.read_text(encoding='utf-8')).data)
            self.assertEqual(actual,rows)
            for route in routes:
                path=f.root/'set/parts'/self.module._part(route['window'])/lang/('page-%08d.html'%route['page'])
                self.assertIn(route['anchor'],Pages(path.read_text(encoding='utf-8')).ids)
        for path in (f.root/'set').rglob('*.html'):
            page=Pages(path.read_text(encoding='utf-8'));self.assertEqual(page.scripts,0)
            for link in page.links:
                target=link.split('#')[0]
                self.assertNotIn('://',link)
                if target:self.assertTrue((path.parent/target).is_file(),(path,link))
        self.assertFalse((f.workspace/'business-export-bindings').exists())
        cache=Path(tempfile.mkdtemp(prefix='partition-mcp-cache-',dir=f.root))
        env={key:value for key,value in os.environ.items()if not key.startswith(('PYTHON','CODE_ONTOLOGY'))}
        env.update({acl.PRINCIPAL_ENV:'reader',companion.privacy_guard.PROFILE_ENV:str(f.root/'worker-profile.json'),'CODE_ONTOLOGY_HOME':str(f.root/'registry')})
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':f.args(limit=100)}}
        wire=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),str(Path(__file__).resolve().parents[1]/'mcp/server.py')],
            input=json.dumps(request)+'\n',capture_output=True,text=True,env=env,timeout=30)
        self.assertEqual(wire.returncode,0);self.assertEqual(wire.stderr,'')
        reply=json.loads(wire.stdout)['result'];self.assertFalse(reply.get('isError'))
        self.assertEqual(reply['structuredContent']['data']['records'],rows)
    def test_explicit_flags_and_configured_capacity_cannot_be_raised(self):
        for kwargs in ({'partition_size':10001},{'max_output_bytes':8*1024**3+1}):
            with self.assertRaises((ValueError,RuntimeError)):self.run_export(**kwargs)
        with self.assertRaises(companion.CompanionError):self.run_export(projection='business_only')
        with self.assertRaises(companion.CompanionError):self.run_export(partitioned=False)
        with self.assertRaises(ValueError):self.run_export(max_output_bytes=1024)
        self.assertFalse((self.f.root/'set').exists())
    def test_cross_window_edge_occurrences_and_source_opaque_graph(self):
        f=self.f
        with f.reader() as reader:rows=list(reader.iter_records(page_size=100))
        self.assertTrue(any(row.get('namespace')=='source' for row in rows))
        pointer=(f.workspace/'business-state.json').read_bytes();self.run_export(partition_size=1)
        _,projected,_=self.rows();self.assertEqual(len(projected),len(rows))
        self.assertTrue(any(row['sourceAnchors'] for row in projected));self.assertEqual((f.workspace/'business-state.json').read_bytes(),pointer)
    def legacy_storage(self):
        f=self.f
        with source._lock(f.workspace),source.open_reader(f.workspace,f.sid) as reader:
            previous=f.store._state(f.workspace);grant=f.store._authorize(f.workspace,'manage_knowledge',f.sid)
            payload=f.sem.build_candidates(reader,source_pins=f.store._pins(reader),max_records=1)
            f.meta=f.store._publish_v1(f.workspace,reader,payload,f.store._receipt(f.workspace,f.sid,'legacy_fixture',grant),previous,grant)
    def test_schema1_is_rejected_before_records_json_is_opened(self):
        self.legacy_storage();f=self.f
        folder=f.workspace/'business-snapshots'/f.meta['businessSnapshotId'];records=folder/'records.json'
        records.rename(folder/'records-held.json')
        with self.assertRaises(ValueError) as caught:self.run_export('legacy-storage')
        self.assertEqual(caught.exception.code,'business_partitioned_storage_required')
        self.assertEqual(caught.exception.report['selectedRecords'],f.meta['recordCount'])
        self.assertEqual(caught.exception.report['storageRequirement'],'schema2_partitioned')
        self.assertFalse((f.root/'legacy-storage').exists())
        result=self.cli_export('legacy-cli')
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['reason'],'business_partitioned_storage_required')
        self.assertEqual(result['report']['selectedRecords'],f.meta['recordCount'])
    def test_input_manifest_cap_blocks_before_json_decode_with_unknown_denominator(self):
        f=self.f;path=f.workspace/'business-snapshots'/f.meta['businessSnapshotId']/'manifest.json'
        with path.open('r+b') as handle:handle.truncate(32*1024**2+1)
        with self.assertRaises(ValueError) as caught:self.run_export('metadata-cap')
        self.assertEqual(caught.exception.code,'business_partitioned_metadata_budget')
        self.assertEqual(caught.exception.report['selectedRecords'],'UNKNOWN')
        self.assertEqual(caught.exception.report['storageRequirement'],'schema2_partitioned_manifest_at_most_32MiB')
        self.assertFalse((f.root/'metadata-cap').exists())
    def test_bounded_reader_policy_rejects_writes_and_unknown_policy_before_file_creation(self):
        f=self.f;path=f.root/'must-not-create.sqlite'
        with self.assertRaisesRegex(f.store.BusinessStoreError,'readonly_required'):
            f.store._database(path,resource_policy='bounded_memory_v1')
        with self.assertRaisesRegex(f.store.BusinessStoreError,'policy_invalid'):
            f.store.open_reader(f.workspace,f.sid,f.meta['businessSnapshotId'],f.meta['businessDigest'],resource_policy='future_policy')
        self.assertFalse(path.exists())
    def test_closed_runtime_namespace_rejects_packages_extensions_caches_and_future_files(self):
        f=self.f;bundle=f.root/'neutral-runtime';bundle.mkdir(mode=0o700)
        actual=Path(self.module.__file__).resolve().parent.parent
        for directory,names in self.module._POLICY_RUNTIME_NAMES.items():
            (bundle/directory).mkdir(mode=0o700)
            for name in names:shutil.copyfile(actual/directory/name,bundle/directory/name);(bundle/directory/name).chmod(0o600)
        with patch.object(self.module,'__file__',str(bundle/'scripts/pipeline_partitioned.py')):
            _,files=self.module._policy_runtime_files()
            for name in ('future_helper.py','companion.so','companion.pyd','companion.pyc'):
                extra=bundle/'scripts'/name;extra.write_bytes(b'neutral unexpected entry');extra.chmod(0o600)
                with self.assertRaisesRegex(ValueError,'partitioned_runtime_changed'):self.module._policy_runtime_files()
                extra.unlink()
            package=bundle/'scripts/companion';package.mkdir(mode=0o700)
            (package/'__init__.py').write_text("raise AssertionError('unverified package executed')\n");(package/'__init__.py').chmod(0o600)
            with self.assertRaisesRegex(ValueError,'partitioned_runtime_changed'):self.module._policy_runtime_files()
            executable=Path(self.runtime).resolve();cache=Path(tempfile.mkdtemp(prefix='namespace-cache-',dir=f.root))
            request={'format':'companion.private-policy-worker-request.v1','nonce':'f'*32,'bundle':str(bundle),'files':files,
                'executableSha256':self.module._policy_bounded_hash(executable,self.module.POLICY_EXECUTABLE_BYTES)[0],
                'workspace':str(f.workspace),'snapshotId':f.sid,'businessSnapshotId':f.meta['businessSnapshotId'],
                'businessDigest':f.meta['businessDigest'],'output':str(f.root/'must-not-publish'),'partitionSize':2,'maxOutputBytes':256*1024**2,
                'profileBinding':self.module._sha(self.module._raw(f.profile)),'principal':'reader','control':str(cache),'timeoutSeconds':10}
            result=subprocess.run([str(executable),'-I','-E','-s','-S','-B','-X','pycache_prefix='+str(cache),'-c',self.module._POLICY_WORKER_BOOTSTRAP],
                input=self.module._raw(request)+b'\n',capture_output=True,cwd=cache,env={'PATH':os.environ.get('PATH','')},timeout=15)
            self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout)['reason'],'worker_runtime_changed')
    def test_critical_hash_caps_mutation_and_cancel_close_the_descriptor(self):
        f=self.f;path=f.root/'neutral-hash.bin';path.write_bytes(b'a'*4096);path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'partitioned_runtime_changed'):self.module._policy_bounded_hash(path,100)
        calls=[0]
        def mutate():
            calls[0]+=1
            if calls[0]==2:
                with path.open('ab')as handle:handle.write(b'changed')
        with self.assertRaisesRegex(ValueError,'partitioned_runtime_changed'):self.module._policy_bounded_hash(path,8192,mutate)
        original=os.open;opened=[];calls=[0]
        def observe(*args,**kwargs):fd=original(*args,**kwargs);opened.append(fd);return fd
        def cancel():
            calls[0]+=1
            if calls[0]==2:raise self.module.PartitionedExportError('partitioned_cancelled')
        with patch.object(os,'open',observe),self.assertRaisesRegex(ValueError,'partitioned_cancelled'):
            self.module._policy_bounded_hash(path,8192,cancel)
        self.assertTrue(opened)
        for fd in opened:
            with self.assertRaises(OSError):os.fstat(fd)
    def test_compile_temp_store_disk_unknown_or_ambiguous_is_unsupported_before_data(self):
        f=self.f
        class Result(list):
            def fetchone(self):return self[0]
        class Probe:
            def execute(self,sql):return Result([(134217728,)])if sql=='PRAGMA hard_heap_limit'else Result(modes)
            def close(self):pass
        for modes in ([('TEMP_STORE=0',)],[],[('TEMP_STORE=4',)],[('TEMP_STORE=1',),('TEMP_STORE=1',)]):
            with patch.object(self.module,'_POLICY_WORKER_ACTIVE',True),patch.object(self.module.sqlite3,'connect',return_value=Probe()),\
                    patch.object(f.store,'open_reader',side_effect=AssertionError('data opened'))as opened:
                with self.assertRaisesRegex(ValueError,'partitioned_runtime_unsupported'):
                    self.module._run_policy_projection_partitioned(f.workspace,f.sid,f.meta['businessSnapshotId'],f.meta['businessDigest'],f.root/'compile-block')
                opened.assert_not_called()
    def test_full_stdin_pipe_does_not_block_cancellation_or_wait_for_child_consumption(self):
        f=self.f;real_popen=subprocess.Popen;transport={'spawned':False,'filled':0,'full':False};children=[]
        def cleanup(child):
            if child.poll()is None:child.kill()
            child.wait(timeout=2)
            for stream in (child.stdin,child.stdout,child.stderr):
                if stream is not None:
                    try:stream.close()
                    except (OSError,ValueError):pass
        def stalled(command,**kwargs):
            # A neutral stock-Python child intentionally consumes no input.
            child=real_popen([command[0],'-I','-E','-s','-S','-B','-c','import time;time.sleep(60)'],**kwargs)
            children.append(child);self.addCleanup(cleanup,child);fd=child.stdin.fileno()
            if os.name=='nt':
                # Python 3.9 does not expose os.set_blocking for Windows pipes.
                # Anonymous pipes support these native wait modes. A successful
                # zero-byte nonblocking write proves the byte pipe is full.
                import _winapi,msvcrt
                handle=msvcrt.get_osfhandle(fd);_winapi.SetNamedPipeHandleState(handle,1,None,None)
                try:
                    for _ in range(1025):
                        self.assertLess(transport['filled'],1024**2)
                        amount,error=_winapi.WriteFile(handle,b'x'*min(1024,1024**2-transport['filled']))
                        self.assertEqual(error,0)
                        if amount==0:transport['full']=True;break
                        transport['filled']+=amount
                        self.assertLessEqual(transport['filled'],1024**2)
                finally:_winapi.SetNamedPipeHandleState(handle,0,None,None)
            else:
                os.set_blocking(fd,False)
                try:
                    while transport['filled']<1024**2:
                        try:transport['filled']+=os.write(fd,b'x'*1024)
                        except BlockingIOError:break
                    # EAGAIN on a 1024-byte atomic write can leave a small tail.
                    # Exhaust it before asserting the product cannot write.
                    for _ in range(1025):
                        self.assertLess(transport['filled'],1024**2)
                        try:transport['filled']+=os.write(fd,b'x')
                        except BlockingIOError:transport['full']=True;break
                        self.assertLessEqual(transport['filled'],1024**2)
                finally:os.set_blocking(fd,True)
            self.assertTrue(transport['full']);transport['spawned']=True;return child
        started=time.monotonic()
        with patch.object(subprocess,'Popen',stalled),self.assertRaises(ValueError)as caught:
            self.run_export('stalled-input',cancel=lambda:transport['spawned'])
        self.assertEqual(caught.exception.code,'partitioned_cancelled');self.assertGreater(transport['filled'],0)
        self.assertTrue(children);self.assertIsNotNone(children[0].poll())
        self.assertLess(time.monotonic()-started,6);self.assertFalse((f.root/'stalled-input').exists())
    def test_parent_late_profile_change_preserves_previous(self):
        f=self.f;self.run_export('previous');before=(f.root/'previous/policy-projection-set.json').read_bytes()
        alternate=companion.privacy_guard.build_profile(['Different Neutral Custodian'],[],key=b'z'*32)
        calls=[0]
        def profile(*args,**kwargs):return alternate if calls[0] else f.profile
        def cancel():calls[0]+=1;return False
        with patch.object(companion.privacy_guard,'load_profile',profile),self.assertRaises(ValueError) as caught:self.run_export('changed',cancel=cancel)
        self.assertEqual(caught.exception.code,'partitioned_privacy_profile_changed')
        self.assertFalse((f.root/'changed').exists())
        self.assertEqual((f.root/'previous/policy-projection-set.json').read_bytes(),before)
    def test_cancel_is_blocked_without_publication(self):
        with self.assertRaises(ValueError) as caught:self.run_export(cancel=lambda:True)
        self.assertEqual(caught.exception.code,'partitioned_cancelled')
        self.assertFalse((self.f.root/'set').exists())
    def test_rejected_worker_result_retains_unattested_artifact_and_original_pointer(self):
        f=self.f;before=(f.workspace/'business-state.json').read_bytes()
        error=self.module.PartitionedExportError('partitioned_worker_result_invalid')
        with patch.object(self.module,'_validate_policy_set_result',side_effect=error),self.assertRaises(ValueError) as caught:
            self.run_export('unattested')
        self.assertEqual(caught.exception.report['publicationAttestation'],'UNATTESTED')
        self.assertEqual(caught.exception.report['cleanup'],'UNVERIFIED_RETAINED')
        self.assertEqual(caught.exception.report['selectedRecords'],f.meta['recordCount'])
        self.assertTrue((f.root/'unattested/policy-projection-set.json').is_file())
        self.assertEqual((f.workspace/'business-state.json').read_bytes(),before)
    def test_source_only_mcp_dispatch_creates_no_export_child(self):
        f=self.f
        with patch.object(subprocess,'Popen',side_effect=AssertionError('source-only child forbidden')) as spawn:
            result=access.dispatch('query_policy_rules',{'workspace_id':f.wid,'snapshot_id':f.sid,'limit':1})
        self.assertEqual(result['status'],'ok');spawn.assert_not_called()
    def test_native_incompatible_runtime_returns_explicit_unsupported_and_no_artifact(self):
        if Path(self.runtime).resolve()==Path(sys.executable).resolve():
            # A compatible current runtime is tested by the ordinary success
            # cases; never invent a second system executable or add a skip.
            self.run_export('current-compatible');return
        import sqlite3
        conn=sqlite3.connect(':memory:');before=conn.execute('PRAGMA hard_heap_limit').fetchone()[0];conn.close()
        with self.assertRaises(ValueError) as caught:self.run_export('native-incompatible',export_python=sys.executable)
        self.assertEqual(caught.exception.code,'partitioned_runtime_unsupported')
        conn=sqlite3.connect(':memory:');after=conn.execute('PRAGMA hard_heap_limit').fetchone()[0];conn.close()
        self.assertEqual(before,after);self.assertFalse((self.f.root/'native-incompatible').exists())
    def cli_export(self,name):
        f=self.f;path=f.root/'explicit-profile.json';path.write_text(json.dumps(f.profile));path.chmod(0o600)
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','CODE_ONTOLOGY'))}
        env.update({acl.PRINCIPAL_ENV:'reader',companion.privacy_guard.PROFILE_ENV:str(path),'CODE_ONTOLOGY_HOME':str(f.root/'registry')})
        cache=Path(tempfile.mkdtemp(prefix='c39-cli-cache-',dir=f.root))
        command=Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts/companion.py'
        result=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),str(command),'business-html',
            '--workspace',str(f.workspace),'--snapshot',f.sid,'--business-snapshot',f.meta['businessSnapshotId'],'--business-digest',f.meta['businessDigest'],
            '--output',str(f.root/name),'--projection','policy_projection','--partitioned','--partition-size','10000','--export-python',self.runtime],
            env=env,text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);return json.loads(result.stdout)
    def test_cli_explicit_global_mode_with_source_deleted(self):
        result=self.cli_export('cli-set')
        self.assertEqual(result['format'],self.module.POLICY_SET_FORMAT)
        self.assertEqual(result['recordCount'],self.f.meta['recordCount'])


if __name__=='__main__':unittest.main()
