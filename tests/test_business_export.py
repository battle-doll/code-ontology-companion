"""Neutral offline export/integrity/authority regressions; no holdout/source reads."""
from contextlib import contextmanager
import copy
from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit, unquote

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'
sys.path.insert(0,str(SCRIPTS))
import business_export as export
import business_semantics as semantics
import privacy_guard as guard
import pipeline_store as source
from windows_fixture import protect_private_path


class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.links=[];self.scripts=0;self.language=None;self.ids=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='html':self.language=a.get('lang')
        if tag=='script':self.scripts+=1
        self.links.extend(a[k] for k in ('href','src') if k in a)
        if 'id' in a:self.ids.append(a['id'])


PINS={key:('ps-neutral' if key=='sourceSnapshotId' else 'bs-neutral' if key=='businessSnapshotId' else 'a'*64) for key in export.PIN_KEYS}


def record(index=0,kind='business_policy'):
    value=dict(id='business:'+str(index),kind=kind,name='Neutral '+str(index),namespace='neutral',domain='sample',conceptKey='concept-'+str(index),
               support='candidate',businessApproval='unreviewed',sourceAnchors=[dict(recordId='semantic:neutral',inlinePointer='/expression',path='neutral.java',sourceSha256='b'*64)],
               facets=dict(units=dict(status='UNKNOWN',reason='unit_not_bound'),outcome=dict(status='DECLARED',value=dict(type='string',value='description'),basis='operator_statement')),
               limitations=['source_only'],runtime='NOT_OBSERVED',executionAuthorization='NOT_PROVIDED')
    value['contentDigest']=semantics.digest(value);return value


class Reader:
    def __init__(self,rows):
        self.rows=rows;self.metadata=dict(PINS,recordCount=len(rows),coverage=dict(selectedRecords=len(rows),omitted=0,status='PARTIAL'),parentBusinessSnapshotId='bs-before');self.pages=[]
    def iter_records(self,*,page_size):
        self.pages.append(page_size)
        yield from copy.deepcopy(self.rows)


class BusinessExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name).resolve()
        self.profile=guard.build_profile(['Synthetic Private Reviewer'],['private-reviewer@neutral-fixture.test'],key=b'e'*32)
        export.configure(privacy_guard=guard,canonical=semantics.canonical)
        self.reader=Reader([record()]);self.calls=[];self.revision=1;self.snapshot=True;self.profile_same=True
    def permit(self,action):
        self.calls.append(action);return dict(decision='allow',revision=self.revision)
    @contextmanager
    def lock(self):yield
    def run_export(self,**kwargs):
        params=dict(pins=PINS,profile=self.profile,authorize=self.permit,publication_guard=self.lock,check_profile=lambda:self.profile_same,check_snapshot=lambda:self.snapshot)
        params.update(kwargs)
        return export.export_business(self.reader,self.base/'business',**params)
    def rejects(self,code=None,**kwargs):
        with self.assertRaises(export.BusinessExportError) as got:self.run_export(**kwargs)
        if code:self.assertEqual(got.exception.code,code)
        self.assertFalse((self.base/'business').exists())
        self.assertEqual(list(self.base.glob('.business-export-*')),[])
        return got.exception
    def test_all_records_five_locales_and_json_roundtrip(self):
        rows=[record(i,k) for i,k in enumerate(export.KINDS)];self.reader=Reader(rows)
        result=self.run_export();root=self.base/'business'
        self.assertEqual(result['recordCount'],8);self.assertEqual(self.reader.pages,[100])
        for row in rows:
            key=export._filename(row['id']);self.assertEqual(json.loads((root/'records'/ (key+'.json')).read_text()),row)
            for lang in export.LANGUAGES:
                page=Page((root/lang/'records'/ (key+'.html')).read_text());self.assertEqual(page.language,lang);self.assertEqual(page.scripts,0);self.assertIn('main',page.ids)
        for file in root.rglob('*.html'):
            page=Page(file.read_text())
            for href in page.links:
                link=urlsplit(href);self.assertFalse(link.scheme or link.netloc)
                if link.path:self.assertTrue((file.parent/unquote(link.path)).is_file(),(file,href))
        for action in ('export_html','read_structure','read_policy','read_evidence'):self.assertIn(action,self.calls)
        manifest=json.loads((root/'business-export.json').read_text());self.assertEqual(manifest['selectedRecords'],8)
        self.assertFalse(manifest['exportedCopiesRemotelyRevocable']);self.assertEqual(manifest['shapeValidation'],'NOT_RUN')
    def test_rdf_json_roundtrip_direction_and_prov(self):
        a=record(0,'business_object_type');b=record(1,'business_object_type');r=record(2,'business_relation')
        r.update(subject=a['id'],predicate='relates',object=b['id'],role='recipient',cardinality=dict(status='UNKNOWN'))
        r['contentDigest']=semantics.digest({k:v for k,v in r.items() if k!='contentDigest'});self.reader=Reader([a,b,r]);self.run_export()
        root=self.base/'business';text=(root/'rdf'/ (export._filename(r['id'])+'.ttl')).read_text();payload=None
        for line in text.splitlines():
            match=re.fullmatch(r'(<[^>]+>) <([^>]+)> (.+) \.',line);self.assertIsNotNone(match,line)
            obj=match.group(3)
            if obj.startswith('"'):
                value=json.loads(obj)
                if match.group(2)==export.NS+'canonicalJson' and match.group(1)==export._iri(r['id']):payload=json.loads(value)
            else:self.assertRegex(obj,r'^<[^>]+>$')
        self.assertEqual(payload,r)
        self.assertIn(export._triple(export._iri(r['id']),export.NS+'subject',export._iri(a['id'])),text)
        self.assertIn(export._triple(export._iri(r['id']),export.NS+'object',export._iri(b['id'])),text)
        self.assertIn(export.PROV+'wasDerivedFrom',text)
        lineage=(root/'lineage.ttl').read_text();self.assertIn(export.PROV+'wasRevisionOf',lineage)
        loss=json.loads((root/'mapping-loss.json').read_text());self.assertEqual(loss['status'],'EXPLICIT_PARTIAL_SEMANTIC_MAPPING');self.assertTrue(loss['allOriginalJsonRetained'])
        self.assertEqual(len(loss['records']),3);self.assertIn('facets',loss['records'][0]['fields'])
    def test_text_is_inert_and_unknown_units_visible(self):
        self.reader.rows[0]['name']='</script><script>alert(1)</script>😀'
        self.reader.rows[0]['contentDigest']=semantics.digest({k:v for k,v in self.reader.rows[0].items() if k!='contentDigest'})
        self.run_export();path=self.base/'business/en/records'/ (export._filename('business:0')+'.html');text=path.read_text()
        self.assertEqual(Page(text).scripts,0);self.assertIn('&lt;script&gt;',text);self.assertIn('UNKNOWN',text);self.assertIn('rounding_stage',text);self.assertIn('units',text)
    def test_pagination_retains_all_ids(self):
        self.reader=Reader([record(i) for i in range(51)]);self.run_export();root=self.base/'business'
        for lang in export.LANGUAGES:
            first=Page((root/lang/'index.html').read_text());second=Page((root/lang/'page-2.html').read_text())
            records=[h for h in first.links+second.links if h.startswith('records/')]
            self.assertEqual(len(set(records)),51)
    def test_private_files_and_manifest_hashes(self):
        result=self.run_export();root=self.base/'business'
        self.assertEqual(sum(x.stat().st_size for x in root.rglob('*') if x.is_file()),result['outputBytes'])
        for name,info in result['files'].items():
            path=root/name;self.assertEqual(export._sha(path.read_bytes()),info['sha256'])
            if os.name!='nt':self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        if os.name!='nt':self.assertEqual(stat.S_IMODE(root.stat().st_mode),0o700)
    def test_each_permission_is_required(self):
        for denied in ('export_html','read_structure','read_policy','read_evidence'):
            with self.subTest(denied=denied):
                def authorize(action):return dict(decision='deny' if action==denied else 'allow',revision=1)
                self.rejects('export_access_denied',authorize=authorize)
    def test_acl_revision_change_aborts(self):
        def authorize(action):
            self.calls.append(action);return dict(decision='allow',revision=1 if len(self.calls)<10 else 2)
        self.rejects('export_acl_revision_changed',authorize=authorize)
    def test_mixed_pins_aborts(self):
        self.reader.metadata['sourceFingerprint']='c'*64;self.rejects('export_snapshot_mismatch')
    def test_profile_and_snapshot_rechecks_abort(self):
        self.profile_same=False;self.rejects('export_context_changed');self.profile_same=True;self.snapshot=False;self.rejects('export_context_changed')
    def test_late_snapshot_change_under_publication_guard(self):
        @contextmanager
        def changed():
            self.snapshot=False;yield
        self.rejects('export_context_changed',publication_guard=changed)
    def test_overwrite_never_allowed(self):
        path=self.base/'business';path.mkdir();(path/'keep').write_text('keep')
        with self.assertRaises(export.BusinessExportError):self.run_export()
        self.assertEqual((path/'keep').read_text(),'keep')
    def test_atomic_promotion_never_overwrites_concurrent_empty_directory(self):
        target=self.base/'appeared';bound=export._BoundArtifacts(target,self.base.stat());bound.create_stage();target.mkdir()
        try:
            with self.assertRaises((export.BusinessExportError,OSError)):export._promote(bound,target)
            self.assertEqual(list(target.iterdir()),[])
        finally:bound.cleanup();bound.close()
    @unittest.skipIf(os.name=='nt','symlink privilege differs on Windows')
    def test_symlink_parent_rejected(self):
        target=self.base/'target';target.mkdir();link=self.base/'link';link.symlink_to(target,target_is_directory=True)
        with self.assertRaises(export.BusinessExportError):export.export_business(self.reader,link/'business',pins=PINS,profile=self.profile,authorize=self.permit,publication_guard=self.lock,check_profile=lambda:True,check_snapshot=lambda:True)
        self.assertEqual(list(target.iterdir()),[])
    def test_total_budget_preserves_denominator(self):
        error=self.rejects('export_total_budget',max_output_bytes=10);self.assertEqual(error.selected,1)
    def test_cap_cannot_be_raised(self):self.rejects('export_budget_invalid',max_output_bytes=1024**3+1)
    def test_cancel_aborts(self):self.rejects('export_cancelled',cancel=lambda:True)
    def test_original_count_mismatch_is_not_empty_success(self):
        self.reader.metadata['recordCount']=2;error=self.rejects('export_record_denominator_mismatch');self.assertEqual((error.selected,error.processed),(2,1))
    def test_duplicate_identity_rejected(self):
        self.reader=Reader([record(),record()]);self.rejects('export_duplicate_identity')
    def test_record_and_page_limits_fail_without_losing_selected_count(self):
        with mock.patch.object(export,'MAX_RECORD_BYTES',10):
            error=self.rejects('export_record_budget');self.assertEqual(error.selected,1)
        with mock.patch.object(export,'MAX_PAGE_BYTES',10):
            error=self.rejects('export_page_budget');self.assertEqual(error.selected,1)
    def test_late_acl_revision_change_prevents_publication(self):
        @contextmanager
        def changed():
            self.revision=2;yield
        self.rejects('export_acl_revision_changed',publication_guard=changed)
    def test_record_digest_tamper_rejected(self):
        self.reader.rows[0]['name']='changed';self.rejects('export_record_digest_mismatch')
    def test_privacy_failure_exposes_code_only(self):
        self.reader.rows[0]['name']='Synthetic Private Reviewer';self.reader.rows[0]['contentDigest']=semantics.digest({k:v for k,v in self.reader.rows[0].items() if k!='contentDigest'})
        error=self.rejects();self.assertNotIn('Synthetic',str(error))
    def test_unsafe_source_link_rejected(self):
        self.rejects('export_source_link_invalid',source_entries={k:'https://example.invalid' for k in export.LANGUAGES})
    def test_relative_source_map_link_is_explicit(self):
        result=self.run_export(source_entries={k:'../../'+k+'/index.html' for k in export.LANGUAGES})
        self.assertIn('../../en/index.html',Page((self.base/'business/en/index.html').read_text()).links)
    def test_bundle_permission_is_distinct(self):
        self.run_export(export_action='export_bundle');self.assertIn('export_bundle',self.calls);self.assertNotIn('export_html',self.calls)
    def test_empty_inventory_preserves_zero_denominator(self):
        self.reader=Reader([]);result=self.run_export();self.assertEqual((result['selectedRecords'],result['recordCount']),(0,0))
    def test_native_browser_and_shape_validation_not_claimed(self):
        result=self.run_export();self.assertEqual(result['browserVerification'],'NOT_RUN');self.assertEqual(result['shapeValidation'],'NOT_RUN')

    def test_linux_renameat2_mock_uses_held_fd_and_basename(self):
        output=self.base/'linux-abi';bound=export._BoundArtifacts(output,self.base.stat());bound.create_stage();calls=[]
        def rename(source_fd,source,target_fd,target,flags):
            calls.append((source_fd,source,target_fd,target,flags));os.rename(source,target,src_dir_fd=source_fd,dst_dir_fd=target_fd);return 0
        library=type('Library',(),{})();library.renameat2=Function(rename)
        try:
            with mock.patch.object(export.sys,'platform','linux'),mock.patch.object(export.ctypes,'CDLL',return_value=library):export._promote(bound,output)
            source_fd,source,target_fd,target,flags=calls[0]
            self.assertEqual((source_fd,target_fd,flags),(bound.parent_fd,bound.parent_fd,1))
            self.assertEqual(source,os.fsencode(bound.name));self.assertEqual(target,b'linux-abi');bound.verify_published()
        finally:bound.cleanup();bound.close()
    def test_linux_missing_primitive_fails_without_path_fallback(self):
        output=self.base/'linux-unavailable';bound=export._BoundArtifacts(output,self.base.stat());bound.create_stage()
        try:
            with mock.patch.object(export.sys,'platform','linux'),mock.patch.object(export.ctypes,'CDLL',return_value=object()):
                with self.assertRaises(export.BusinessExportError):export._promote(bound,output)
            self.assertFalse(output.exists())
        finally:bound.cleanup();bound.close()
    def test_parent_replaced_between_final_check_and_promotion_rejected(self):
        approved=self.base/'approved';approved.mkdir();moved=self.base/'moved';output=approved/'business';real=export._promote;changed=[]
        def race(bound,out):
            try:approved.rename(moved)
            except PermissionError:
                # Native Windows ancestor handles prohibit this operation.
                changed.append('blocked_by_os_handle');return real(bound,out)
            approved.symlink_to(moved,target_is_directory=True);changed.append('replaced');real(bound,out)
        with mock.patch.object(export,'_promote',side_effect=race):
            try:
                export.export_business(self.reader,output,pins=PINS,profile=self.profile,authorize=self.permit,publication_guard=self.lock,check_profile=lambda:True,check_snapshot=lambda:True)
            except export.BusinessExportError as error:
                self.assertEqual(changed,['replaced']);self.assertEqual(error.code,'export_parent_changed')
                self.assertFalse((moved/'business').exists());self.assertTrue(approved.is_symlink())
            else:self.assertEqual(changed,['blocked_by_os_handle'])
    def test_parent_redirect_to_foreign_directory_never_publishes_there(self):
        approved=self.base/'approved';approved.mkdir();moved=self.base/'moved';foreign=self.base/'foreign';foreign.mkdir();(foreign/'sentinel').write_text('keep')
        real=export._promote;blocked=[]
        def race(bound,out):
            try:approved.rename(moved)
            except PermissionError:blocked.append(True);return real(bound,out)
            approved.symlink_to(foreign,target_is_directory=True);real(bound,out)
        with mock.patch.object(export,'_promote',side_effect=race):
            try:export.export_business(self.reader,approved/'business',pins=PINS,profile=self.profile,authorize=self.permit,publication_guard=self.lock,check_profile=lambda:True,check_snapshot=lambda:True)
            except export.BusinessExportError:
                self.assertFalse((moved/'business').exists());self.assertFalse((foreign/'business').exists())
            else:self.assertEqual(blocked,[True])
        self.assertEqual((foreign/'sentinel').read_text(),'keep')
    def test_parent_changed_after_promotion_before_guard_exit_rejected(self):
        output=self.base/'business';moved=self.base.with_name(self.base.name+'-moved')
        @contextmanager
        def changed():
            yield
            try:self.base.rename(moved)
            except PermissionError:return
            self.base.symlink_to(moved,target_is_directory=True)
        try:
            try:self.run_export(publication_guard=changed)
            except export.BusinessExportError as error:
                self.assertEqual(error.code,'export_parent_changed');self.assertFalse((moved/'business').exists())
            else:self.assertFalse(moved.exists())
        finally:
            if self.base.is_symlink():self.base.unlink();moved.rename(self.base)
    def test_post_promotion_replacement_never_returns_foreign_entrypoint(self):
        real=export._promote;relocated=self.base/'relocated-owned'
        def replace(bound,output):
            real(bound,output);output.rename(relocated);output.mkdir();(output/'sentinel').write_text('foreign')
        with mock.patch.object(export,'_promote',side_effect=replace):
            with self.assertRaises(export.BusinessExportError) as got:self.run_export()
        self.assertEqual(got.exception.code,'export_published_entry_changed')
        self.assertEqual((self.base/'business/sentinel').read_text(),'foreign')
        if os.name!='nt':self.assertEqual(list(relocated.iterdir()),[])
    @unittest.skipIf(os.name=='nt','POSIX fd mode and publication primitive')
    def test_stage_root_private_mode_checked_before_publication_primitive(self):
        target=self.base/'unsafe';bound=export._BoundArtifacts(target,self.base.stat());stage=bound.create_stage()
        try:
            stage.chmod(0o755)
            with mock.patch.object(export.ctypes,'CDLL') as library:
                with self.assertRaises(export.BusinessExportError) as caught:export._promote(bound,target)
            self.assertEqual(caught.exception.code,'export_directory_permissions_changed');library.assert_not_called()
            self.assertFalse(target.exists());self.assertFalse(bound.published)
        finally:bound.cleanup();bound.close()
    @unittest.skipIf(os.name=='nt','POSIX held-fd versus root pathname')
    def test_stage_path_replacement_checked_against_held_root_fd(self):
        target=self.base/'unsafe';bound=export._BoundArtifacts(target,self.base.stat());stage=bound.create_stage();moved=self.base/'original-stage'
        try:
            stage.rename(moved);stage.mkdir(mode=0o700)
            with mock.patch.object(export.ctypes,'CDLL') as library:
                with self.assertRaises(export.BusinessExportError) as caught:export._promote(bound,target)
            self.assertEqual(caught.exception.code,'export_stage_changed');library.assert_not_called();self.assertFalse(target.exists())
        finally:bound.cleanup();bound.close()

    def test_native_profile_change_after_file_validation_blocks_direct_business_promotion(self):
        profile_file=self.base/'owned-profile.json';source._atomic(profile_file,self.profile);protect_private_path(profile_file)
        replacement=guard.build_profile([self.reader.rows[0]['name']],[],key=b'w'*32)
        with self.assertRaises(guard.PrivacyError):guard.ensure_public_safe(self.reader.rows[0],profile=replacement,require_profile=True)
        original=export._BoundArtifacts.validate;calls=[]
        def changed(bound,files):
            result=original(bound,files);calls.append(True);source._atomic(profile_file,replacement);return result
        with mock.patch.dict(os.environ,{guard.PROFILE_ENV:str(profile_file)}),mock.patch.object(export._BoundArtifacts,'validate',new=changed),mock.patch.object(export,'_promote') as promote:
            self.rejects('export_context_changed',check_profile=lambda:guard.load_profile(required=True)==self.profile)
        self.assertEqual(calls,[True]);promote.assert_not_called()
    def test_late_authority_snapshot_and_cancel_checks_follow_file_validation(self):
        original=export._BoundArtifacts.validate
        for change,expected in (('acl','export_acl_revision_changed'),('snapshot','export_context_changed'),('cancel','export_cancelled')):
            with self.subTest(change=change):
                changed=[]
                def mutate(bound,files):
                    result=original(bound,files);changed.append(True)
                    if change=='acl':self.revision+=1
                    elif change=='snapshot':self.snapshot=False
                    return result
                with mock.patch.object(export._BoundArtifacts,'validate',new=mutate),mock.patch.object(export,'_promote') as promote:
                    self.rejects(expected,cancel=(lambda:bool(changed)) if change=='cancel' else None)
                self.assertEqual(changed,[True]);promote.assert_not_called();self.snapshot=True

    def test_cleanup_keeps_foreign_replacement_and_extra_entries(self):
        output=self.base/'output';bound=export._BoundArtifacts(output,self.base.stat());stage=bound.create_stage()
        try:
            bound.write('owned.txt',b'owned');(stage/'foreign.txt').write_text('foreign')
            moved=self.base/'own-relocated';stage.rename(moved);stage.mkdir();(stage/'sentinel').write_text('keep')
            summary=bound.cleanup()
            self.assertEqual((stage/'sentinel').read_text(),'keep');self.assertEqual((moved/'foreign.txt').read_text(),'foreign');
            if os.name=='nt':self.assertEqual(summary['status'],'UNKNOWN_OR_CHANGED_ENTRIES_RETAINED')
            else:self.assertFalse((moved/'owned.txt').exists())
        finally:bound.close()


class Function:
    def __init__(self,function):self.function=function
    def __call__(self,*args):return self.function(*args)


class WindowsApi:
    def __init__(self):
        self.opened=[];self.closed=[];self.rename=[];self.identities={};self.by_path={};self.fail_rename=False;self.reparse=False
        self.CreateFileW=Function(self.create);self.GetFileInformationByHandle=Function(self.info)
        self.SetFileInformationByHandle=Function(self.set_info);self.CloseHandle=Function(lambda h:self.closed.append(h) or 1)
    def create(self,path,access,share,security,creation,flags,template):
        handle=len(self.opened)+100;index=self.by_path.setdefault(path,len(self.by_path)+1);self.identities[handle]=index
        self.opened.append((path,access,share,creation,flags,handle));return handle
    def info(self,handle,pointer):
        pointer._obj.attributes=0x10|(0x400 if self.reparse else 0);pointer._obj.volume=7;pointer._obj.indexLow=self.identities[handle];return 1
    def set_info(self,handle,kind,buffer,size):
        header=export._WinRenameInfo.from_buffer(buffer);offset=export._WinRenameInfo.name.offset
        raw=bytes(buffer)[offset:offset+header.length]
        self.rename.append(dict(handle=handle,kind=kind,flags=header.flags,root=header.root,length=header.length,name=raw.decode('utf-16-le'),size=size))
        return 0 if self.fail_rename else 1


class WindowsBoundaryAbiTests(unittest.TestCase):
    def test_relative_root_handle_no_replace_unicode_abi(self):
        api=WindowsApi();boundary=export._WindowsBoundary(Path('/neutral/parent'),library=api)
        try:
            boundary.bind_stage(Path('/neutral/parent/stage'));boundary.rename('业务')
            call=api.rename[-1];self.assertEqual((call['root'],call['flags'],call['kind'],call['length'],call['name']),(boundary.parent_handle,0,3,4,'业务'))
            self.assertEqual(export._WinRenameInfo.root.offset,8 if __import__('ctypes').sizeof(__import__('ctypes').c_void_p)==8 else 4)
            for path,access,share,creation,flags,handle in api.opened[:-1]:
                self.assertEqual(share&4,0);self.assertEqual(flags&0x02200000,0x02200000);self.assertEqual(creation,3)
            self.assertTrue(api.opened[-1][1]&0x10000)
        finally:boundary.close()
        self.assertEqual(len(api.closed),len(api.opened))
    def test_changed_parent_handle_identity_rejected(self):
        api=WindowsApi();boundary=export._WindowsBoundary(Path('/neutral/parent'),library=api)
        try:
            api.by_path[str(boundary.parent)]=999
            with self.assertRaises(export.BusinessExportError):boundary.stable()
        finally:boundary.close()
    def test_reparse_handle_rejected(self):
        api=WindowsApi();api.reparse=True
        with self.assertRaises(export.BusinessExportError):export._WindowsBoundary(Path('/neutral/parent'),library=api)
    def test_rename_failure_has_no_fallback(self):
        api=WindowsApi();boundary=export._WindowsBoundary(Path('/neutral/parent'),library=api)
        try:
            boundary.bind_stage(Path('/neutral/parent/stage'));api.fail_rename=True
            with self.assertRaises(export.BusinessExportError):boundary.rename('business')
            self.assertEqual(len(api.rename),1)
        finally:boundary.close()
    def test_stage_handle_and_fresh_path_dacl_checked_with_existing_guard(self):
        api=WindowsApi();boundary=export._WindowsBoundary(Path('/neutral/parent'),library=api);path=Path('/neutral/parent/stage')
        try:
            boundary.bind_stage(path)
            with mock.patch.object(export._guard,'_windows_profile_security',return_value=b'private') as security:boundary.verify_stage(path)
            self.assertEqual(security.call_count,2);self.assertTrue(all(call.kwargs=={'os_handle':True} for call in security.call_args_list))
            self.assertTrue(all(access&0x20000 for name,access,*_ in api.opened if name==str(path)))
        finally:boundary.close()
        self.assertEqual(len(api.closed),len(api.opened))
    def test_stage_dacl_failure_or_path_replacement_never_reaches_rename(self):
        for mode in ('dacl','identity'):
            api=WindowsApi();boundary=export._WindowsBoundary(Path('/neutral/parent'),library=api);path=Path('/neutral/parent/stage')
            try:
                boundary.bind_stage(path)
                if mode=='identity':api.by_path[str(path)]=999
                with mock.patch.object(export._guard,'_windows_profile_security',side_effect=export._guard.PrivacyError('profile_permissions')):
                    with self.assertRaises(export.BusinessExportError):boundary.verify_stage(path)
                self.assertEqual(api.rename,[])
            finally:boundary.close()
            self.assertEqual(len(api.closed),len(api.opened))
    def test_relative_name_escape_rejected(self):
        for name in ('../other','a/b','a\\b','C:other','', '.', '..'):
            with self.assertRaises(export.BusinessExportError):export._windows_rename_buffer(123,name)


if __name__=='__main__':unittest.main()
