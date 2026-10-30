"""Private offline business views and RDF/PROV from one pinned sealed reader.

Loaded through the verified sibling loader; dependencies and authority are
explicitly injected. Exported copies retain export-time access, not revocation.
"""
from __future__ import annotations

import copy
import ctypes
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import uuid
from contextlib import contextmanager
import sys

MAX_OUTPUT_BYTES = 1024 ** 3
MAX_PAGE_BYTES = 32 * 1024 ** 2
MAX_RECORD_BYTES = 512 * 1024
MAX_RECORDS = 10000
PAGE_SIZE = 50
LANGUAGES = ('en', 'ko', 'ja', 'zh-CN', 'ru')
PIN_KEYS = ('sourceSnapshotId','sourceManifestSha256','sourceFingerprint','analysisSpecId',
            'businessSnapshotId','businessDigest','businessSpecId','businessSpecHash')
KINDS = ('business_object_type','business_property','business_relation','business_policy',
         'business_transition','business_claim','business_conflict','business_coverage')
POLICY_FACETS = ('subject_scope','eligibility','exclusions','inputs','formula','constants','units',
                 'rounding_stage','outcome','priority','exclusivity','stackability','caps_floors',
                 'effective_interval','clock_timezone','conflicts','missing_context')
TEXT = {
'en': ('Business knowledge','Records','Authority','Policy facets','Evidence and lineage','Directed relation',
       'Source map','Previous','Next','Raw JSON','Static knowledge only. Runtime execution NOT_OBSERVED; execution authorization NOT_PROVIDED. Approval concerns a knowledge statement only.',
       'Private export: access was checked at export time. Later ACL changes cannot revoke already exported copies.',
       'UNKNOWN is missing evidence or context, not zero or permission. Names do not establish identity.', 'Coverage and pins'),
'ko': ('업무 지식','레코드','권한과 근거 상태','정책 요소','증거와 계보','방향 관계',
       '소스 지도','이전','다음','원본 JSON','정적 지식입니다. 실행은 NOT_OBSERVED, 실행 승인은 NOT_PROVIDED입니다. 승인은 지식 명제에만 적용됩니다.',
       '비공개 내보내기: 생성 당시 접근 권한을 확인했습니다. 이후 ACL 변경으로 이미 내보낸 사본을 철회할 수 없습니다.',
       'UNKNOWN은 증거나 문맥이 부족하다는 뜻이며 0이나 허가가 아닙니다. 이름만으로 동일성을 판단하지 않습니다.','범위와 고정 핀'),
'ja': ('業務知識','レコード','権限と根拠の状態','ポリシー要素','証拠と来歴','有向関係',
       'ソースマップ','前へ','次へ','元の JSON','静的知識です。実行は NOT_OBSERVED、実行許可は NOT_PROVIDED です。承認は知識の記述だけに適用されます。',
       '非公開エクスポート: 出力時のアクセス権を確認しました。後の ACL 変更で既存のコピーを取り消すことはできません。',
       'UNKNOWN は証拠や文脈の不足であり、ゼロや許可ではありません。名前だけで同一性を判断しません。','範囲と固定ピン'),
'zh-CN': ('业务知识','记录','权限与依据状态','策略要素','证据与沿袭','有向关系',
       '源代码地图','上一页','下一页','原始 JSON','仅为静态知识。执行为 NOT_OBSERVED，执行授权为 NOT_PROVIDED。批准仅适用于知识陈述。',
       '私有导出：已在导出时检查访问权限。后续 ACL 更改无法撤销已经导出的副本。',
       'UNKNOWN 表示缺少证据或上下文，并非零或许可。名称本身不能证明身份相同。','范围与固定标识'),
'ru': ('Бизнес-знания','Записи','Полномочия и основания','Аспекты политики','Доказательства и происхождение','Направленная связь',
       'Карта исходного кода','Назад','Далее','Исходный JSON','Только статические знания. Исполнение: NOT_OBSERVED; разрешение на исполнение: NOT_PROVIDED. Одобрение касается лишь утверждения о знании.',
       'Частный экспорт: права проверены при экспорте. Последующее изменение ACL не отзывает уже экспортированные копии.',
       'UNKNOWN означает отсутствие доказательств или контекста, а не ноль или разрешение. Одного имени недостаточно для тождества.','Охват и закреплённые идентификаторы'),
}
_guard = None
_canonical = None
_validate_record = None
_policy_projection = None
POLICY_PROJECTION_CONTRACT = 'companion.authorized-policy-projection.v1'
POLICY_CHUNK_RECORDS = 100
POLICY_CHUNK_BYTES = 8 * 1024 ** 2


class BusinessExportError(ValueError):
    def __init__(self, code='business_export_failed', *, selected=None, processed=0):
        self.code = code if re.fullmatch('[a-z_]{1,100}', code) else 'business_export_failed'
        self.selected = selected
        self.processed = processed
        super().__init__(self.code)


def configure(*, privacy_guard, canonical, validate_record=None, policy_projection=None):
    global _guard, _canonical, _validate_record, _policy_projection
    if not callable(getattr(privacy_guard, 'ensure_public_safe', None)) or not callable(canonical):
        raise BusinessExportError('export_dependencies_required')
    for key in ('_link_like','_check_private_file_metadata'):
        if not callable(getattr(privacy_guard,key,None)):
            raise BusinessExportError('export_security_dependency_required')
    if validate_record is not None and not callable(validate_record):raise BusinessExportError('export_semantic_validator_required')
    _guard, _canonical, _validate_record = privacy_guard, canonical, validate_record
    # The verified query module owns the closed policy projection grammar. Its
    # bytes participate in businessSpecHash; exporters never copy that grammar.
    _policy_projection = policy_projection


def _raw(value):
    raw = _canonical(value)
    if not isinstance(raw, bytes):
        raise BusinessExportError('export_canonical_bytes_required')
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _e(value):
    return html.escape(str(value), quote=True)


def _filename(identity):
    return _sha(identity.encode('utf-8'))


def _iri(identity):
    return '<urn:companion:business:record:' + _filename(identity) + '>'


def _lit(value):
    # JSON string escapes are also Turtle string escapes; non-BMP Unicode is
    # written directly, never as invalid surrogate escape pairs.
    return json.dumps(str(value),ensure_ascii=False)


NS='urn:companion:business:v1:'
RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
PROV='http://www.w3.org/ns/prov#'
XSD='http://www.w3.org/2001/XMLSchema#'
SH='http://www.w3.org/ns/shacl#'


def _triple(subject, predicate, value):
    return subject+' <'+predicate+'> '+value+' .\n'


def _rdf_record(record, pins, known):
    subject=_iri(record['id']);lines=[]
    lines.append(_triple(subject,RDF+'type','<'+NS+'BusinessRecord>'))
    lines.append(_triple(subject,RDF+'type','<'+PROV+'Entity>'))
    # Canonical JSON is the lossless authoritative payload. RDF fields below
    # are an explicit limited mapping, not a new domain ontology or rule engine.
    for key in ('id','kind','name','namespace','domain','conceptKey','support','businessApproval','contentDigest'):
        if key in record:lines.append(_triple(subject,NS+key,_lit(record[key])))
    lines.append(_triple(subject,NS+'canonicalJson',_lit(_raw(record).decode('utf-8'))))
    for key in ('subject','predicate','object','objectOrExpression','role','cardinality'):
        if key not in record:continue
        value=record[key]
        if isinstance(value,str) and value in known:target=_iri(value)
        else:target=_lit(_raw(value).decode('utf-8'))
        lines.append(_triple(subject,NS+key,target))
    source='<urn:companion:business:source:'+_filename(pins['sourceSnapshotId'])+'>'
    lines.append(_triple(subject,PROV+'wasDerivedFrom',source))
    for anchor in record.get('sourceAnchors',[]):
        resource='<urn:companion:business:anchor:'+_sha(_raw(anchor))+'>'
        lines.append(_triple(subject,PROV+'wasDerivedFrom',resource))
        lines.append(_triple(resource,RDF+'type','<'+PROV+'Entity>'))
        lines.append(_triple(resource,NS+'canonicalJson',_lit(_raw(anchor).decode('utf-8'))))
    return ''.join(lines)


def _shapes():
    shape='<'+NS+'RecordShape>';node='<'+NS+'RequiredId>'
    return (_triple(shape,RDF+'type','<'+SH+'NodeShape>')+
            _triple(shape,SH+'targetClass','<'+NS+'BusinessRecord>')+
            _triple(shape,SH+'property',node)+
            _triple(node,SH+'path','<'+NS+'id>')+
            _triple(node,SH+'minCount','"1"^^<'+XSD+'integer>')+
            _triple(node,SH+'maxCount','"1"^^<'+XSD+'integer>'))


def _safe_parent(output):
    parent=output.parent
    if not parent.is_dir():raise BusinessExportError('export_parent_missing')
    for path in (parent,*parent.parents):
        if _guard._link_like(path.lstat()):raise BusinessExportError('export_link_boundary')
    if output.exists() or output.is_symlink():raise BusinessExportError('export_destination_exists')
    return parent.stat()


class _WinFileInfo(ctypes.Structure):
    _fields_=[('attributes',ctypes.c_uint32),('times',ctypes.c_uint32*6),('volume',ctypes.c_uint32),('sizeHigh',ctypes.c_uint32),('sizeLow',ctypes.c_uint32),('links',ctypes.c_uint32),('indexHigh',ctypes.c_uint32),('indexLow',ctypes.c_uint32)]


class _WinRenameInfo(ctypes.Structure):
    # Windows DWORD/WCHAR retain 32/16-bit widths even in non-Windows ABI tests.
    _fields_=[('flags',ctypes.c_uint32),('root',ctypes.c_void_p),('length',ctypes.c_uint32),('name',ctypes.c_uint16*1)]


class _WinIoValue(ctypes.Union):
    _fields_=[('status',ctypes.c_int32),('pointer',ctypes.c_void_p)]


class _WinIoStatus(ctypes.Structure):
    _fields_=[('value',_WinIoValue),('information',ctypes.c_size_t)]


# A native request with unknown completion must never race Python cleanup.
# At most one fixed native allocation and its handles are retained per module;
# further exports require a fresh process, never an automatic retry.
_WINDOWS_PENDING_RENAMES=[]
_WINDOWS_PUBLICATION_LOCK=threading.RLock()


def _windows_rename_buffer(parent_handle,name):
    if not isinstance(name,str) or not name or any(c in name for c in '/\\:\x00') or name in ('.','..'):
        raise BusinessExportError('export_publication_name_invalid')
    try:raw=name.encode('utf-16-le')
    except UnicodeEncodeError:raise BusinessExportError('export_publication_name_invalid') from None
    if len(raw)//2>255:raise BusinessExportError('export_publication_name_invalid')
    offset=_WinRenameInfo.name.offset
    buffer=ctypes.create_string_buffer(max(ctypes.sizeof(_WinRenameInfo),offset+len(raw)+2))
    header=_WinRenameInfo.from_buffer(buffer);header.flags=0;header.root=parent_handle;header.length=len(raw)
    ctypes.memmove(ctypes.addressof(buffer)+offset,raw,len(raw))
    return buffer


class _WindowsBoundary:
    """Documented Win32 handles; no delete sharing on parent/ancestor handles.

    The source directory handle is renamed relative to the held parent handle.
    Native Windows execution is required separately from ABI mocks.
    """
    def __init__(self,parent,library=None):
        with _WINDOWS_PUBLICATION_LOCK:
            if _WINDOWS_PENDING_RENAMES:raise BusinessExportError('export_publication_completion_unknown')
        self.api=library if library is not None else ctypes.WinDLL('kernel32',use_last_error=True)
        self.native=library if library is not None else ctypes.WinDLL('ntdll',use_last_error=True)
        self.handles=[];self.parent=parent;self.stage_handle=None;self.pending_rename=False
        self.api.CreateFileW.argtypes=(ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p)
        self.api.CreateFileW.restype=ctypes.c_void_p
        self.api.GetFileInformationByHandle.argtypes=(ctypes.c_void_p,ctypes.POINTER(_WinFileInfo));self.api.GetFileInformationByHandle.restype=ctypes.c_int
        self.native.NtSetInformationFile.argtypes=(ctypes.c_void_p,ctypes.POINTER(_WinIoStatus),ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int)
        self.native.NtSetInformationFile.restype=ctypes.c_int32
        self.api.LocalAlloc.argtypes=(ctypes.c_uint32,ctypes.c_size_t);self.api.LocalAlloc.restype=ctypes.c_void_p
        self.api.LocalFree.argtypes=(ctypes.c_void_p,);self.api.LocalFree.restype=ctypes.c_void_p
        self.api.CloseHandle.argtypes=(ctypes.c_void_p,);self.api.CloseHandle.restype=ctypes.c_int
        try:
            for path in reversed((parent,*parent.parents)):
                handle=self.open_directory(path,source=False)
                self.handles.append((path,handle,self.identity(handle)))
            self.parent_handle=self.handles[-1][1]
        except Exception:self.close();raise
    def open_directory(self,path,*,source):
        # The stage is synchronous (no OVERLAPPED), with DELETE, READ_CONTROL
        # and SYNCHRONIZE. Ancestors still deny delete sharing.
        handle=self.api.CreateFileW(str(path),0xA0|(0x130000 if source else 0),7 if source else 3,None,3,0x02200000,None)
        if handle in (None,ctypes.c_void_p(-1).value):raise BusinessExportError('export_windows_directory_open_failed')
        try:self.identity(handle)
        except Exception:self.api.CloseHandle(handle);raise
        return handle
    def identity(self,handle):
        info=_WinFileInfo()
        if not self.api.GetFileInformationByHandle(handle,ctypes.byref(info)):raise BusinessExportError('export_windows_directory_identity_failed')
        if not info.attributes&0x10 or info.attributes&0x400:raise BusinessExportError('export_link_boundary')
        if not (info.indexHigh or info.indexLow):raise BusinessExportError('export_windows_directory_identity_failed')
        return info.volume,info.indexHigh,info.indexLow
    def stable(self):
        for path,handle,expected in self.handles:
            current=self.open_directory(path,source=False)
            try:
                if self.identity(current)!=expected or self.identity(handle)!=expected:raise BusinessExportError('export_parent_changed')
            finally:self.api.CloseHandle(current)
    def bind_stage(self,path):
        self.stage_handle=self.open_directory(path,source=True);self.stage_identity=self.identity(self.stage_handle)
    def verify_stage(self,path):
        current=self.open_directory(path,source=True)
        try:
            if self.identity(self.stage_handle)!=self.stage_identity or self.identity(current)!=self.stage_identity:
                raise BusinessExportError('export_stage_changed')
            try:
                before=_guard._windows_profile_security(self.stage_handle,os_handle=True)
                if _guard._windows_profile_security(current,os_handle=True)!=before:
                    raise BusinessExportError('export_directory_permissions_changed')
            except _guard.PrivacyError:
                raise BusinessExportError('export_directory_permissions_changed') from None
        finally:self.api.CloseHandle(current)
    def rename(self,name):
        with _WINDOWS_PUBLICATION_LOCK:
            if self.pending_rename or _WINDOWS_PENDING_RENAMES:raise BusinessExportError('export_publication_completion_unknown')
            return self._rename(name)
    def _rename(self,name):
        if self.identity(self.stage_handle)!=self.stage_identity:raise BusinessExportError('export_stage_changed')
        buffer=_windows_rename_buffer(self.parent_handle,name)
        alignment=ctypes.alignment(_WinRenameInfo)
        offset=(ctypes.sizeof(_WinIoStatus)+alignment-1)//alignment*alignment
        size=offset+len(buffer)
        if size>1024:raise BusinessExportError('export_native_memory_budget')
        allocation=self.api.LocalAlloc(0x40,size)
        if not allocation:raise BusinessExportError('export_native_memory_unavailable')
        io=_WinIoStatus.from_address(allocation);issued=False;completed=False
        def retain():
            if not self.pending_rename:
                self.pending_rename=True;self.pending_allocation=allocation;self.pending_io=io
                _WINDOWS_PENDING_RENAMES.append(self)
        try:
            ctypes.memmove(allocation+offset,buffer,len(buffer))
            issued=True
            status=self.native.NtSetInformationFile(self.stage_handle,ctypes.byref(io),ctypes.c_void_p(allocation+offset),len(buffer),10)
            observed=io.value.status
            if status==0x103 or observed==0x103:
                retain();error=BusinessExportError('export_publication_completion_unknown')
                error.ntstatus=status&0xffffffff;error.io_status=observed&0xffffffff;raise error
            completed=True
            if status!=0 or observed!=0:
                error=BusinessExportError('export_destination_or_publication_changed')
                error.ntstatus=status&0xffffffff;error.io_status=observed&0xffffffff;raise error
        finally:
            if issued and not completed:retain()
            if not self.pending_rename and self.api.LocalFree(allocation):
                retain();raise BusinessExportError('export_native_memory_cleanup_failed')
    def close(self):
        with _WINDOWS_PUBLICATION_LOCK:self._close()
    def _close(self):
        # LocalAlloc memory has native process lifetime even during Python
        # module teardown. Never LocalFree/CloseHandle an uncertain request.
        if self.pending_rename:return
        if self.stage_handle is not None:self.api.CloseHandle(self.stage_handle);self.stage_handle=None
        for _,handle,_ in reversed(self.handles):self.api.CloseHandle(handle)
        self.handles=[]


class _BoundArtifacts:
    """Owned entries under a fixed directory fd (or locked Win32 parent handles)."""
    def __init__(self,output,parent_identity):
        self.output=output;self.parent=output.parent;self.parent_identity=parent_identity
        self.parent_fd=None;self.stage_fd=None;self.windows=None;self.stage=None;self.entries={};self.published=False;self.root_identity=None
        try:
            if os.name=='nt':
                self.windows=_WindowsBoundary(self.parent)
            else:
                flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,'O_CLOEXEC',0)
                fd=os.open(self.parent.anchor,flags)
                try:
                    for part in self.parent.parts[1:]:
                        if part in ('.','..'):raise BusinessExportError('export_parent_changed')
                        following=os.open(part,flags,dir_fd=fd);os.close(fd);fd=following
                    self.parent_fd=fd;fd=None
                finally:
                    if fd is not None:os.close(fd)
                if not _same(os.fstat(self.parent_fd),parent_identity):raise BusinessExportError('export_parent_changed')
            self.verify_parent()
        except Exception:self.close();raise
    def verify_parent(self):
        for path in (self.parent,*self.parent.parents):
            if _guard._link_like(path.lstat()):raise BusinessExportError('export_parent_changed')
        if not _same(self.parent.stat(),self.parent_identity):raise BusinessExportError('export_parent_changed')
        if self.windows:self.windows.stable()
        elif not _same(os.fstat(self.parent_fd),self.parent_identity):raise BusinessExportError('export_parent_changed')
    def verify_stage(self):
        """Reject changed identity, owner or privacy before any final rename."""
        self.verify_parent()
        if self.windows:
            self.windows.verify_stage(self.stage)
            values=(self.stage.lstat(),)
        else:
            values=(os.fstat(self.stage_fd),os.stat(self.name,dir_fd=self.parent_fd,follow_symlinks=False))
        for info in values:
            if _guard._link_like(info) or not stat.S_ISDIR(info.st_mode) or not _same(info,self.root_identity):
                raise BusinessExportError('export_stage_changed')
            if os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077):
                raise BusinessExportError('export_directory_permissions_changed')
    def verify_published(self):
        self.verify_parent()
        if self.windows:self.windows.verify_stage(self.output)
        current=self.output.lstat() if self.windows else os.stat(self.output.name,dir_fd=self.parent_fd,follow_symlinks=False)
        if _guard._link_like(current) or not _same(current,self.root_identity):raise BusinessExportError('export_published_entry_changed')
        if os.name!='nt' and (current.st_uid!=os.getuid() or current.st_mode&0o077):raise BusinessExportError('export_directory_permissions_changed')
    def create_stage(self):
        self.name='.business-export-'+uuid.uuid4().hex;self.stage=self.parent/self.name
        if self.windows:
            self.stage.mkdir(mode=0o700);self.windows.bind_stage(self.stage);self.root_identity=self.stage.stat()
        else:
            os.mkdir(self.name,0o700,dir_fd=self.parent_fd)
            self.stage_fd=os.open(self.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.parent_fd)
            self.root_identity=os.fstat(self.stage_fd)
        self.verify_parent()
        return self.stage
    @contextmanager
    def directory(self,parts,*,create=False):
        if any(p in ('','..','.') or '/' in p or '\\' in p for p in parts):raise BusinessExportError('export_artifact_path_invalid')
        if self.windows:
            self.verify_parent();path=self.output if self.published else self.stage
            if not _same(path.lstat(),self.root_identity) or _guard._link_like(path.lstat()):raise BusinessExportError('export_stage_changed')
            for i,part in enumerate(parts):
                path=path/part;key='/'.join(parts[:i+1])
                if create and not path.exists():path.mkdir(mode=0o700);self.entries[key]=path.lstat()
                if key not in self.entries or not _same(path.lstat(),self.entries[key]) or _guard._link_like(path.lstat()):raise BusinessExportError('export_artifact_changed')
            yield path
            return
        fd=os.dup(self.stage_fd)
        try:
            for i,part in enumerate(parts):
                key='/'.join(parts[:i+1])
                if create:
                    try:os.mkdir(part,0o700,dir_fd=fd);self.entries[key]=os.stat(part,dir_fd=fd,follow_symlinks=False)
                    except FileExistsError:pass
                if key not in self.entries:raise BusinessExportError('export_artifact_changed')
                next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                if not _same(os.fstat(next_fd),self.entries[key]):os.close(next_fd);raise BusinessExportError('export_artifact_changed')
                os.close(fd);fd=next_fd
            yield fd
        finally:os.close(fd)
    def write(self,name,raw):
        parts=Path(name).parts
        with self.directory(parts[:-1],create=True) as parent:
            fd=os.open(parent/parts[-1] if self.windows else parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,**({} if self.windows else dict(dir_fd=parent)))
            try:
                self.entries[name]=os.fstat(fd)
                if self.windows:_guard._windows_profile_security(fd)
                _guard._check_private_file_metadata(os.fstat(fd))
                with os.fdopen(fd,'wb',closefd=False) as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
                return os.fstat(fd)
            finally:os.close(fd)
    def read(self,name):
        parts=Path(name).parts
        with self.directory(parts[:-1]) as parent:
            fd=os.open(parent/parts[-1] if self.windows else parts[-1],os.O_RDONLY|getattr(os,'O_NOFOLLOW',0),**({} if self.windows else dict(dir_fd=parent)))
            try:
                if name not in self.entries or not _same(os.fstat(fd),self.entries[name]):raise BusinessExportError('export_artifact_changed')
                _guard._check_private_file_metadata(os.fstat(fd))
                with os.fdopen(fd,'rb',closefd=False) as stream:return stream.read(MAX_PAGE_BYTES+1)
            finally:os.close(fd)
    def validate(self,files):
        self.verify_published() if self.published else self.verify_stage()
        for name,info in self.entries.items():
            parts=Path(name).parts
            with self.directory(parts[:-1]) as parent:
                current=(parent/parts[-1]).lstat() if self.windows else os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
                if _guard._link_like(current) or not _same(current,info):raise BusinessExportError('export_artifact_changed')
                if stat.S_ISDIR(current.st_mode):
                    if os.name!='nt' and (current.st_uid!=os.getuid() or current.st_mode&0o077):raise BusinessExportError('export_directory_permissions_changed')
                elif name not in files or _sha(self.read(name))!=files[name]['sha256']:raise BusinessExportError('export_artifact_changed')
        # Reject extra entries, but never delete them in cleanup.
        for key in ['',*[n for n,i in self.entries.items() if stat.S_ISDIR(i.st_mode)]]:
            parts=tuple(Path(key).parts) if key else ()
            with self.directory(parts) as parent:
                actual=set(os.listdir(parent));expected={PurePosixPath(n).name for n in self.entries if str(PurePosixPath(n).parent)==(key or '.')}
                if actual!=expected:raise BusinessExportError('export_artifact_set_changed')
    def cleanup(self):
        """Only recorded owned inodes; unknown/replaced entries are left untouched."""
        removed=0;retained=0
        if self.stage is None:return dict(status='NO_STAGE',removed=0,retained=0)
        if self.windows and self.windows.pending_rename:
            return dict(status='UNKNOWN_WINDOWS_PUBLICATION_RETAINED',removed=0,retained=len(self.entries))
        if self.root_identity is None:return dict(status='UNVERIFIED_RETAINED',removed=0,retained=len(self.entries))
        if self.windows:
            try:self.verify_parent()
            except Exception:return dict(status='UNVERIFIED_RETAINED',removed=0,retained=len(self.entries))
        for name,expected in sorted(self.entries.items(),key=lambda item:(item[0].count('/'),item[0]),reverse=True):
            parts=Path(name).parts
            try:
                with self.directory(parts[:-1]) as parent:
                    path=parent/parts[-1] if self.windows else parts[-1]
                    options={} if self.windows else dict(dir_fd=parent)
                    current=path.lstat() if self.windows else os.stat(path,follow_symlinks=False,**options)
                    if not _same(current,expected) or _guard._link_like(current):retained+=1;continue
                    if stat.S_ISDIR(current.st_mode):os.rmdir(path,**options)
                    else:os.unlink(path,**options)
                    removed+=1
            except (OSError,BusinessExportError):retained+=1
        for name in (self.name,self.output.name):
            try:
                current=(self.parent/name).lstat() if self.windows else os.stat(name,dir_fd=self.parent_fd,follow_symlinks=False)
                if _same(current,self.root_identity) and not _guard._link_like(current):
                    if self.windows:os.rmdir(self.parent/name)
                    else:os.rmdir(name,dir_fd=self.parent_fd)
            except OSError:pass
        return dict(status='OWN_ENTRIES_REMOVED' if retained==0 else 'UNKNOWN_OR_CHANGED_ENTRIES_RETAINED',removed=removed,retained=retained)
    def close(self):
        if self.stage_fd is not None:os.close(self.stage_fd);self.stage_fd=None
        if self.parent_fd is not None:os.close(self.parent_fd);self.parent_fd=None
        if self.windows:self.windows.close();self.windows=None


def _promote(bound,output):
    """No path traversal during the rename itself; both endpoints are bound."""
    bound.verify_stage()
    if bound.windows:
        bound.windows.rename(output.name)
    else:
        current=os.stat(bound.name,dir_fd=bound.parent_fd,follow_symlinks=False)
        if not _same(current,bound.root_identity):raise BusinessExportError('export_stage_changed')
        library=ctypes.CDLL(None,use_errno=True)
        if sys.platform=='darwin':
            operation=getattr(library,'renameatx_np',None)
            if operation is None:raise BusinessExportError('export_exclusive_publication_unavailable')
            operation.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint);operation.restype=ctypes.c_int
            result=operation(bound.parent_fd,os.fsencode(bound.name),bound.parent_fd,os.fsencode(output.name),4)
        elif sys.platform.startswith('linux'):
            operation=getattr(library,'renameat2',None)
            if operation is None:raise BusinessExportError('export_exclusive_publication_unavailable')
            operation.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint);operation.restype=ctypes.c_int
            result=operation(bound.parent_fd,os.fsencode(bound.name),bound.parent_fd,os.fsencode(output.name),1)
        else:raise BusinessExportError('export_exclusive_publication_unavailable')
        if result!=0:raise BusinessExportError('export_destination_or_publication_changed')
        current=os.stat(output.name,dir_fd=bound.parent_fd,follow_symlinks=False)
        if not _same(current,bound.root_identity):raise BusinessExportError('export_stage_changed')
    bound.published=True


def _same(a,b):
    return (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino)


def _page(language,title,body,*,depth=0):
    labels=TEXT[language];prefix='../'*(depth+1)
    css=prefix+'style.css'
    nav=' | '.join('<a lang="'+lang+'" href="'+('../'*(depth+1))+lang+'/index.html">'+_e(lang)+'</a>' for lang in LANGUAGES)
    return ('<!doctype html><html lang="'+language+'"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'self\'; base-uri \'none\'; form-action \'none\'">'
            '<title>'+_e(title)+'</title><link rel="stylesheet" href="'+css+'"></head>'
            '<body><a class="skip" href="#main">'+_e(labels[1])+'</a><header><nav aria-label="Language">'+nav+'</nav></header>'
            '<main id="main"><h1>'+_e(title)+'</h1><p>'+_e(labels[10])+'</p><p>'+_e(labels[11])+'</p><p>'+_e(labels[12])+'</p>'+body+
            '</main><footer>battle-doll · '+_e(labels[0])+'</footer></body></html>')


PROJECTION_TEXT = {
    'en': 'Business-only projection. Source traceability UNKNOWN; source evidence, original pins and original JSON are withheld. Projected JSON is not a review manifest.',
    'ko': '업무 전용 투영입니다. 소스 추적성은 UNKNOWN이며 소스 증거·원본 핀·원본 JSON은 제외됩니다. 투영 JSON은 검토 명세가 아닙니다.',
    'ja': '業務専用の投影です。ソース追跡性は UNKNOWN です。ソース証拠・元の固定識別子・元の JSON は含みません。投影 JSON はレビュー定義ではありません。',
    'zh-CN': '仅业务投影。源代码可追溯性为 UNKNOWN；不包含源证据、原始固定标识和原始 JSON。投影 JSON 不是审核清单。',
    'ru': 'Проекция только бизнес-знаний. Прослеживаемость исходного кода: UNKNOWN. Доказательства, исходные идентификаторы и JSON исключены. Проекция JSON не является документом одобрения.',
}


def _business_only_record(row, identities):
    """Separate presentation grammar: never serialize source-derived metadata."""
    fields=('id','kind','name','namespace','domain','conceptKey','support','businessApproval')
    if any(type(row.get(key)) is not str for key in fields): raise BusinessExportError('export_projection_record_invalid')
    result = {key: row[key] for key in fields}
    if result['support'] not in ('candidate','source_supported','conflicted','revoked','stale','unsupported'):result['support']='UNKNOWN'
    if result['businessApproval'] not in ('approved','unreviewed','rejected','revoked'):result['businessApproval']='UNKNOWN'
    losses = 0
    def value(item):
        if type(item) is list: return [value(child) for child in item]
        if type(item) is not dict: return item
        tag = item.get('type')
        allowed = {
            'boolean':('type','value'),'integer':('type','value'),'text':('type','value'),'enum':('type','value'),
            'decimal':('type','value','precision','scale'),'quantity':('type','value','unit','precision','scale'),
            'money':('type','value','currency','unit','precision','scale'),'concept_reference':('type','conceptId'),
            'sequence':('type','items'),'time_interval':('type','start','end','timezone','clock','bounds'),
            'scalar_type':('type','name'),'property_type':('type','scalarType','precision','scale','quantityKind','unit','currency','rounding','clock','timezone','nullable'),
            'policy_composition':('type','members','priorityOrder','exclusivity','stacking','onConflict'),
            'finite_contexts':('type','scope','contexts'),'clock_basis':('type','clock','timezone'),
        }
        if tag not in allowed or set(item)-set(allowed[tag]):
            raise ValueError('source_material_withheld')
        if tag == 'concept_reference' and item.get('conceptId') not in identities:
            raise ValueError('target_withheld')
        if tag == 'policy_composition' and any(member.get('policyId') not in identities for member in item['members']):
            raise ValueError('target_withheld')
        if tag == 'policy_composition':
            if any(set(member)!={'policyId','priority'} for member in item['members']):raise ValueError('source_material_withheld')
            return {key:copy.deepcopy(child) for key,child in item.items()}
        if tag == 'finite_contexts' and any(set(context['values'])-identities for context in item['contexts']):
            raise ValueError('target_withheld')
        if tag == 'finite_contexts':
            contexts=[]
            for context in item['contexts']:
                if set(context)!={'contextId','values','asOf','clock','timezone'}:raise ValueError('source_material_withheld')
                contexts.append({**{key:context[key] for key in ('contextId','asOf','clock','timezone')},
                                 'values':{key:value(typed) for key,typed in context['values'].items()}})
            return {'type':tag,'scope':item['scope'],'contexts':contexts}
        return {key: value(child) for key,child in item.items()}
    for key in ('subject','object'):
        if key in row: result[key] = row[key] if type(row[key]) is str and row[key] in identities else 'target_withheld'
    if 'role' in row:
        if type(row['role']) is not str: raise BusinessExportError('export_projection_record_invalid')
        result['role']=row['role']
    if 'cardinality' in row:
        card=row['cardinality']
        if card=='UNKNOWN':result['cardinality']='UNKNOWN'
        elif (type(card) is dict and set(card)=={'min','max'} and type(card['min']) is int and card['min']>=0
                and (card['max'] is None or type(card['max']) is int and card['max']>=card['min'])):
            result['cardinality']=copy.deepcopy(card)
        else:raise BusinessExportError('export_projection_record_invalid')
    if 'aliases' in row:
        result['aliases'] = [{'target': a['target'] if a['target'] in identities else 'target_withheld',
                             'relation': a['relation'] if a['relation'] in ('alias','equivalent') else 'UNKNOWN'} for a in row['aliases']]
    facets = {}
    for name,facet in row.get('facets',{}).items():
        state = facet.get('status','UNKNOWN')
        if state not in ('UNKNOWN','NOT_APPLICABLE','DECLARED','SOURCE_SUPPORTED'):state='UNKNOWN'
        projected = {'status':state}
        if state == 'DECLARED':
            try: projected['value'] = value(facet['value'])
            except ValueError:
                projected['projectionLoss'] = 'source_or_unselected_reference_withheld'; losses += 1
        elif state == 'SOURCE_SUPPORTED':
            projected['projectionLoss'] = 'source_material_withheld'; losses += 1
        facets[name] = projected
    result.update(facets=facets, sourceTraceability='UNKNOWN', originalJsonRetained=False,
        businessMeaningComplete=False, approvalScope='knowledge_statement_only',runtimeStatus='NOT_OBSERVED', executionAuthorization='NOT_PROVIDED')
    return result, losses


def _export_business_only(reader, output_dir, *, pins, profile, authorize, publication_guard,
                          check_profile, check_snapshot, max_output_bytes, cancel, private_binding, finish_reader):
    """A separately authorized, lossy artifact; full pins stay in a private binding."""
    if _validate_record is None or not callable(private_binding): raise BusinessExportError('export_projection_dependencies_required')
    if type(pins) is not dict or set(pins) != set(PIN_KEYS) or any(type(pins[k]) is not str or not pins[k] for k in PIN_KEYS):
        raise BusinessExportError('export_pins_invalid')
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES: raise BusinessExportError('export_budget_invalid')
    if not all(callable(fn) for fn in (authorize,publication_guard,check_profile,check_snapshot)): raise BusinessExportError('export_authority_callbacks_required')
    pins=copy.deepcopy(pins); profile=copy.deepcopy(profile)
    output=Path(output_dir).absolute(); parent_identity=_safe_parent(output)
    selected=None; processed=0; revision=None; bound=None; success=False; failure=None; files={}; size=0
    export_id='projection-'+uuid.uuid4().hex
    def checkpoint(*, snapshot=True):
        nonlocal revision
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()): raise BusinessExportError('export_cancelled')
        permits=[authorize(action) for action in ('export_html','read_policy')]
        if any(type(p) is not dict or p.get('decision') != 'allow' or type(p.get('revision')) is not int for p in permits): raise BusinessExportError('export_access_denied')
        versions={p['revision'] for p in permits}
        if len(versions) != 1 or revision is not None and revision not in versions: raise BusinessExportError('export_acl_revision_changed')
        revision=versions.pop()
        if any(reader.metadata.get(k) != v for k,v in pins.items()): raise BusinessExportError('export_snapshot_mismatch')
        if check_profile() is not True or snapshot and check_snapshot() is not True: raise BusinessExportError('export_context_changed')
    def write(name, data):
        nonlocal size
        checkpoint(); raw=data.encode('utf-8') if type(data) is str else data
        if len(raw)>MAX_PAGE_BYTES or size+len(raw)>max_output_bytes: raise BusinessExportError('export_total_budget')
        _guard.ensure_public_safe(raw.decode('utf-8'),profile=profile,allow_local_paths=False,require_profile=True)
        bound.write(name,raw); files[name]={'sha256':_sha(raw),'bytes':len(raw)}; size+=len(raw)
    try:
        checkpoint(); selected=reader.metadata.get('recordCount')
        if type(selected) is not int or not 0 <= selected <= MAX_RECORDS: raise BusinessExportError('export_record_denominator_invalid')
        rows=[]; seen=set(); withheld=0; retained_bytes=0
        for row in reader.iter_records(page_size=100):
            checkpoint(); _validate_record(row)
            _guard.ensure_public_safe(row,profile=profile,allow_local_paths=False,require_profile=True)
            raw=_raw(row); retained_bytes+=len(raw)
            if len(raw)>MAX_RECORD_BYTES or retained_bytes>max_output_bytes: raise BusinessExportError('export_record_budget')
            if row.get('contentDigest') != _sha(_raw({k:v for k,v in row.items() if k!='contentDigest'})): raise BusinessExportError('export_record_digest_mismatch')
            if row['id'] in seen: raise BusinessExportError('export_duplicate_identity')
            seen.add(row['id']); processed+=1
            if processed>selected: raise BusinessExportError('export_record_denominator_mismatch')
            if row.get('namespace')=='source' or row.get('reviewedMeaning')!='declared_attestation': withheld+=1
            else: rows.append(row)
        if processed != selected: raise BusinessExportError('export_record_denominator_mismatch')
        identities={row['id'] for row in rows}; projected=[]; facet_losses=0
        for row in rows:
            checkpoint()
            item,loss=_business_only_record(row,identities); projected.append(item); facet_losses+=loss
        bound=_BoundArtifacts(output,parent_identity); bound.create_stage()
        projected_raw=_raw(projected); projection_digest=_sha(projected_raw)
        write('records.json',projected_raw)
        summary=dict(format='companion.business-only-export.v1',projection='business_only',exportId=export_id,
            projectionDigest=projection_digest,projectionDigestScope='records_json_only',inputBusinessRecordCount=selected,exportedBusinessRecordCount=len(projected),
            withheldSourceCandidateCount=withheld,withheldFacetCount=facet_losses,selectionTraversal='COMPLETE',
            wholeBusinessCompleteness='UNKNOWN',sourceTraceability='UNKNOWN',traceability='projected_artifact_only',
            currentPinsVerifiedInternally=True,sourceMaterialIncluded=False,originalJsonRetained=False,
            losses=['source_candidates','source_evidence','source_pins','original_json','private_review_basis','source_processing_ledger','rdf_provenance'],
            permissionsChecked=['export_html','read_policy'],accessRevision=revision,
            exportedCopiesRemotelyRevocable=False,runtimeStatus='NOT_OBSERVED',executionAuthorization='NOT_PROVIDED',
            approvalScope='knowledge_statement_only',
            shapeValidation='NOT_RUN',browserVerification='NOT_RUN')
        review=reader.metadata.get('currentReviewDiagnostics')
        if review is not None:
            outcomes=review.get('outcomeCounts') if type(review) is dict else None
            if (type(review) is not dict or type(review.get('selectedInputs')) is not int or not 0<=review['selectedInputs']<=MAX_RECORDS
                    or type(outcomes) is not dict or set(outcomes)!={'accepted','conflicted','unsupported','rejected','omitted','duplicate'}
                    or any(type(n) is not int or n<0 for n in outcomes.values()) or sum(outcomes.values())!=review['selectedInputs']):
                raise BusinessExportError('export_projection_accounting_invalid')
            summary['reviewValidation']={'scope':'current_review_original_inputs','selectedInputs':review['selectedInputs'],
                'outcomeCounts':copy.deepcopy(outcomes),'wholeBusinessCompleteness':'UNKNOWN'}
        write('style.css','body{font:1rem system-ui;max-width:75rem;margin:auto;padding:1rem;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere}nav{display:flex;gap:1rem;flex-wrap:wrap}.skip{position:absolute;top:-4rem}.skip:focus{top:0}')
        for language in LANGUAGES:
            pages=max(1,(len(projected)+PAGE_SIZE-1)//PAGE_SIZE)
            for page in range(pages):
                body='<p>'+_e(PROJECTION_TEXT[language])+'</p><p><a href="../records.json">JSON</a></p>'
                body+='<pre>'+_e(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'
                for row in projected[page*PAGE_SIZE:(page+1)*PAGE_SIZE]:
                    body+='<article><h2>'+_e(row.get('name','UNKNOWN'))+'</h2><pre>'+_e(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></article>'
                body+='<nav>'+''.join('<a href="'+('index.html' if i==0 else 'page-'+str(i+1)+'.html')+'">'+str(i+1)+'</a>' for i in range(pages))+'</nav>'
                write(language+'/'+('index.html' if page==0 else 'page-'+str(page+1)+'.html'),_page(language,TEXT[language][0],body))
        write('index.html',_page('en',TEXT['en'][0],'<p>'+_e(PROJECTION_TEXT['en'])+'</p><nav>'+''.join('<a href="'+lang+'/index.html">'+lang+'</a>' for lang in LANGUAGES)+'</nav>',depth=-1))
        write('business-export.json',_raw({**summary,'files':files.copy()}))
        with publication_guard():
            checkpoint(); bound.validate(files)
            if output.exists() or output.is_symlink(): raise BusinessExportError('export_destination_exists')
            # This callback belongs to trusted server code, never a user artifact.
            binding=dict(format='companion.private-business-export-binding.v1',exportId=export_id,pins=pins,
                         projectionDigest=projection_digest,projectionDigestScope='records_json_only',accessRevision=revision,status='binding_only_publication_not_attested')
            private_binding(copy.deepcopy(binding)); checkpoint(); bound.validate(files)
            # The API closes its pinned reader while this publication lock is
            # held, before exposing an artifact. A failing context exit aborts.
            if finish_reader is not None:finish_reader()
            checkpoint(snapshot=finish_reader is None)
            _promote(bound,output); bound.verify_published()
            checkpoint(snapshot=finish_reader is None); bound.verify_published()
        success=True
        return {**summary,'status':'exported','entrypoint':str(output/'index.html'),'languages':list(LANGUAGES),
                'outputBytes':size,'fileCount':len(files),'files':files}
    except BusinessExportError as exc:
        failure=exc; exc.selected=selected; exc.processed=processed; raise
    except Exception:
        failure=BusinessExportError('export_validation_failed',selected=selected,processed=processed); raise failure from None
    finally:
        if bound is not None:
            if not success:
                cleanup=bound.cleanup()
                if failure is not None: failure.cleanup=cleanup
            bound.close()


POLICY_PROJECTION_TEXT = {
    'en': 'Lossless for authorized policy projection. Source evidence details are withheld. Offline issuer authenticity is not established; this is not a review manifest.',
    'ko': '허가된 정책 투영을 손실 없이 보존합니다. 소스 증거 세부사항은 제외됩니다. 오프라인 발행자 진위는 확인되지 않았으며 검토 명세가 아닙니다.',
    'ja': '許可されたポリシー投影を損失なく保持します。ソース証拠の詳細は含みません。オフライン発行者の真正性は未確認で、レビュー定義ではありません。',
    'zh-CN': '无损保留已授权的策略投影。不包含源证据详情。离线发布者身份未经证实，且本文件不是审核清单。',
    'ru': 'Проекция разрешённой политики сохранена без потерь. Подробности исходных доказательств скрыты. Подлинность издателя офлайн не установлена; это не документ одобрения.',
}


def _strict_projection_json(raw):
    """Reject duplicate keys and non-JSON constants during roundtrip checks."""
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise BusinessExportError('export_projection_duplicate_key')
            result[key]=value
        return result
    def constant(_):raise BusinessExportError('export_projection_invalid_json')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant)


def _policy_references(value):
    """Business identities are closed; sourceRuleId/anchor IDs stay opaque."""
    if type(value) is list:
        for item in value:yield from _policy_references(item)
    elif type(value) is dict:
        for key,item in value.items():
            if key in ('subject','object','target','conceptId','policyId','propertyId','outputPropertyId'):
                if type(item) is str:yield item
            yield from _policy_references(item)


def _policy_reference_occurrences(value, pointer=''):
    """Occurrence-preserving companion to the reviewed policy ID extractor.

    Input must already pass the verified query's closed producer projection.
    Opaque source identities never become business lookup requirements.
    """
    if type(value) is list:
        for index,item in enumerate(value):
            yield from _policy_reference_occurrences(item,pointer+'/'+str(index))
    elif type(value) is dict:
        for key,item in value.items():
            path=pointer+'/'+key.replace('~','~0').replace('/','~1')
            if type(item) is str:
                if key in ('subject','object','target','conceptId','policyId','propertyId','outputPropertyId'):
                    yield path,item,'business'
                elif key in ('sourceRuleId','recordId'):
                    yield path,item,'opaque_source'
            yield from _policy_reference_occurrences(item,path)


def _export_policy_projection(reader, output_dir, *, pins, profile, authorize, publication_guard,
                              check_profile, check_snapshot, max_output_bytes, cancel, finish_reader):
    """One exact authorized snapshot view, in bounded inert offline transports.

    No private binding receipt is created or copied. File hashes establish byte
    consistency only; no issuance attestation or publisher identity is claimed.
    """
    api=_policy_projection
    methods=('export_projection_contract','validate_policy_projection_input',
             'policy_projection_record','policy_projection_metadata','policy_projection_diagnostics')
    if (_validate_record is None or api is None or any(not callable(getattr(api,name,None)) for name in methods)
            or api.export_projection_contract()!=POLICY_PROJECTION_CONTRACT):
        raise BusinessExportError('export_projection_dependencies_required')
    if type(pins) is not dict or set(pins)!=set(PIN_KEYS) or any(type(pins[k]) is not str or not pins[k] for k in PIN_KEYS):
        raise BusinessExportError('export_pins_invalid')
    if type(max_output_bytes) is not int or not 1<=max_output_bytes<=MAX_OUTPUT_BYTES:raise BusinessExportError('export_budget_invalid')
    if not all(callable(fn) for fn in (authorize,publication_guard,check_profile,check_snapshot)):
        raise BusinessExportError('export_authority_callbacks_required')
    pins=copy.deepcopy(pins);profile=copy.deepcopy(profile)
    output=Path(output_dir).absolute();parent_identity=_safe_parent(output)
    selected=reader.metadata.get('recordCount') if type(reader.metadata.get('recordCount')) is int else None
    processed=0;permits=None;bound=None;success=False;failure=None;files={};total=0
    metadata_identity=_sha(_raw(reader.metadata))
    chunks=[];pages=[];routes={};record_hashes=[];references=[]
    def safe(value):
        _guard.ensure_public_safe(value,profile=profile,allow_local_paths=False,require_profile=True)
    def checkpoint():
        nonlocal permits
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):raise BusinessExportError('export_cancelled')
        current=[authorize(action) for action in ('read_policy','export_html')]
        if any(type(p) is not dict or p.get('decision')!='allow' or type(p.get('revision')) is not int for p in current):
            raise BusinessExportError('export_access_denied')
        if len({p['revision'] for p in current})!=1 or permits is not None and current!=permits:
            raise BusinessExportError('export_acl_revision_changed')
        if permits is None:permits=copy.deepcopy(current)
        if any(reader.metadata.get(k)!=v for k,v in pins.items()):raise BusinessExportError('export_snapshot_mismatch')
        if _sha(_raw(reader.metadata))!=metadata_identity:raise BusinessExportError('export_snapshot_mismatch')
        if check_snapshot() is not True:raise BusinessExportError('export_context_changed')
        # End with the current profile after the last authority callback, which
        # itself may observe or accompany a profile replacement.
        if current!=[authorize(action) for action in ('read_policy','export_html')]:
            raise BusinessExportError('export_acl_revision_changed')
        if check_profile() is not True:raise BusinessExportError('export_context_changed')
    def write(name,raw):
        nonlocal total
        checkpoint();raw=raw.encode('utf-8') if type(raw) is str else raw
        if type(raw) is not bytes or len(raw)>MAX_PAGE_BYTES or total+len(raw)>max_output_bytes:
            raise BusinessExportError('export_total_budget')
        safe(name);safe(raw.decode('utf-8'))
        digest=_sha(raw);safe(digest)
        bound.write(name,raw);files[name]={'sha256':digest,'bytes':len(raw)};total+=len(raw)
        checkpoint()
    def record_projection(row):
        checkpoint();safe(row);_validate_record(row)
        api.validate_policy_projection_input(row,kind='record')
        raw=_raw(row)
        if len(raw)>MAX_RECORD_BYTES:raise BusinessExportError('export_record_budget')
        if row.get('contentDigest')!=_sha(_raw({k:v for k,v in row.items() if k!='contentDigest'})):
            raise BusinessExportError('export_record_digest_mismatch')
        value=api.policy_projection_record(row);safe(value);raw=_raw(value)
        if len(raw)>MAX_RECORD_BYTES:raise BusinessExportError('export_record_budget')
        if type(value) is not dict or type(value.get('id')) is not str or not value['id']:
            raise BusinessExportError('export_record_invalid')
        if _strict_projection_json(raw)!=value:raise BusinessExportError('export_projection_roundtrip_mismatch')
        return value,raw
    def html_body(rows,page_number,page_count):
        body='<p>'+_e(POLICY_PROJECTION_TEXT[language])+'</p><p><a href="../policy-projection.json">JSON</a></p>'
        for row in rows:
            body+='<article id="record-'+_filename(row['id'])+'"><h2>'+_e(row.get('name','UNKNOWN'))+'</h2><pre class="record-json">'+_e(_raw(row).decode('utf-8'))+'</pre></article>'
        body+='<nav>'
        for number,label in ((page_number-1,TEXT[language][7]),(page_number+1,TEXT[language][8])):
            if 0<=number<page_count:body+='<a href="'+('index.html' if number==0 else 'page-%06d.html'%(number+1))+'">'+_e(label)+'</a> '
        return body+'</nav>'
    try:
        checkpoint();selected=reader.metadata.get('recordCount')
        if type(selected) is not int or not 0<=selected<=MAX_RECORDS:raise BusinessExportError('export_record_denominator_invalid')
        safe(reader.metadata);api.validate_policy_projection_input(reader.metadata,kind='metadata')
        metadata=api.policy_projection_metadata(reader.metadata);safe(metadata)
        if any(metadata.get(k)!=v for k,v in pins.items()):raise BusinessExportError('export_snapshot_mismatch')
        data={'metadata':metadata,'coverage':copy.deepcopy(metadata['coverage'])}
        if 'currentReviewDiagnostics' in reader.metadata:
            data['currentReviewDiagnostics']=api.policy_projection_diagnostics(reader.metadata['currentReviewDiagnostics'])
        safe(data);data_raw=_raw(data)
        if len(data_raw)>MAX_PAGE_BYTES:raise BusinessExportError('export_total_budget')
        bound=_BoundArtifacts(output,parent_identity);bound.create_stage()
        pending=[];pending_bytes=0
        def flush():
            nonlocal pending,pending_bytes
            if not pending:return
            name='records/part-%06d.jsonl'%(len(chunks)+1);raw=b''.join(item[1]+b'\n' for item in pending)
            write(name,raw);chunks.append({'path':name,'recordCount':len(pending),**files[name]})
            pages.append([item[0] for item in pending]);pending=[];pending_bytes=0
        for row in reader.iter_records(page_size=100):
            value,raw=record_projection(row)
            if value['id'] in routes:raise BusinessExportError('export_duplicate_identity')
            if processed>=selected:raise BusinessExportError('export_record_denominator_mismatch')
            if pending and (len(pending)>=POLICY_CHUNK_RECORDS or pending_bytes+len(raw)+1>min(POLICY_CHUNK_BYTES,MAX_PAGE_BYTES)):
                flush()
            if len(raw)+1>min(POLICY_CHUNK_BYTES,MAX_PAGE_BYTES):raise BusinessExportError('export_record_budget')
            routes[value['id']]={'page':len(chunks)+1,'anchor':'record-'+_filename(value['id'])}
            references.extend(_policy_references(value));record_hashes.append((value['id'],_sha(raw)))
            pending.append((value,raw));pending_bytes+=len(raw)+1;processed+=1
        flush()
        if processed!=selected:raise BusinessExportError('export_record_denominator_mismatch')
        if any(identity not in routes for identity in references):raise BusinessExportError('export_projection_dangling_reference')
        # Re-read the verified producer, retaining the exact current MCP view.
        # This also detects order changes, lost records/edges and extra records.
        digest=hashlib.sha256(b'companion.authorized-policy-projection.v1\x00')
        digest.update(len(data_raw).to_bytes(8,'big'));digest.update(data_raw)
        expected=iter(record_hashes);count=0
        for chunk in chunks:
            raw=bound.read(chunk['path'])
            if len(raw)!=chunk['bytes'] or _sha(raw)!=chunk['sha256'] or not raw.endswith(b'\n'):
                raise BusinessExportError('export_projection_chunk_mismatch')
            lines=raw.splitlines()
            if len(lines)!=chunk['recordCount']:raise BusinessExportError('export_record_denominator_mismatch')
            for line in lines:
                value=_strict_projection_json(line);entry=next(expected,None)
                if entry!=(value.get('id'),_sha(line)):raise BusinessExportError('export_projection_roundtrip_mismatch')
                digest.update(len(line).to_bytes(8,'big'));digest.update(line);count+=1
        if count!=selected or next(expected,None) is not None:raise BusinessExportError('export_record_denominator_mismatch')
        expected=iter(record_hashes)
        def stored_lines():
            for chunk in chunks:
                checkpoint()
                for line in bound.read(chunk['path']).splitlines():yield line
        stored=iter(stored_lines())
        for row in reader.iter_records(page_size=100):
            value,raw=record_projection(row)
            if next(expected,None)!=(value['id'],_sha(raw)) or next(stored,None)!=raw:
                raise BusinessExportError('export_projection_roundtrip_mismatch')
        if next(expected,None) is not None or next(stored,None) is not None:raise BusinessExportError('export_record_denominator_mismatch')
        if not pages:pages=[[]]
        # A JSONL chunk can need smaller HTML pages because escaping increases
        # byte size. Page routing is separate from the original record identity.
        html_pages=[]
        for rows in pages:
            batch=[]
            for row in rows:
                trial=batch+[row]
                # Reserve bounded document/navigation overhead before writing.
                escaped=sum(len(_e(_raw(item).decode('utf-8')).encode('utf-8'))+1024 for item in trial)
                if batch and escaped+16384>MAX_PAGE_BYTES:html_pages.append(batch);batch=[]
                if len(_e(_raw(row).decode('utf-8')).encode('utf-8'))+17408>MAX_PAGE_BYTES:raise BusinessExportError('export_record_budget')
                batch.append(row)
            if batch:html_pages.append(batch)
        if not html_pages:html_pages=[[]]
        routes={row['id']:{'page':number+1,'anchor':'record-'+_filename(row['id'])} for number,rows in enumerate(html_pages) for row in rows}
        write('style.css','body{font:1rem system-ui;max-width:75rem;margin:auto;padding:1rem;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere}nav{display:flex;gap:1rem;flex-wrap:wrap}.skip{position:absolute;top:-4rem}.skip:focus{top:0}')
        for language in LANGUAGES:
            for number,rows in enumerate(html_pages):
                write(language+'/'+('index.html' if number==0 else 'page-%06d.html'%(number+1)),_page(language,TEXT[language][0],html_body(rows,number,len(html_pages))))
        summary=dict(format=POLICY_PROJECTION_CONTRACT,projection='policy_projection',projectionContract=api.export_projection_contract(),
            projectionDigest=digest.hexdigest(),projectionDigestScope='framed_metadata_coverage_diagnostics_and_ordered_record_json_v1',
            selectedRecords=selected,processedRecords=processed,recordCount=processed,selectionTraversal='COMPLETE',
            recordsOrder='verified_reader_order',recordsPerChunkLimit=POLICY_CHUNK_RECORDS,chunkByteLimit=POLICY_CHUNK_BYTES,
            permissionsChecked=['read_policy','export_html'],accessRevision=permits[0]['revision'],
            sourceEvidenceDetails='WITHHELD',originalJsonRetained=False,fullSourceLossless=False,
            offlineIssuerAuthenticity='NOT_ESTABLISHED',publicationAttestation='NOT_PROVIDED',
            runtimeStatus='NOT_OBSERVED',executionAuthorization='NOT_PROVIDED',globalCompleteness='UNKNOWN',
            exportedCopiesRemotelyRevocable=False,approvalScope='knowledge_statement_only',
            exactnessClaim='lossless for authorized policy projection',browserVerification='NOT_RUN',shapeValidation='NOT_RUN')
        write('index.html',_page('en',TEXT['en'][0],'<p>'+_e(POLICY_PROJECTION_TEXT['en'])+'</p><nav>'+''.join('<a href="'+lang+'/index.html">'+lang+'</a>' for lang in LANGUAGES)+'</nav>',depth=-1))
        manifest={**summary,**data,'chunks':chunks,'routes':routes,'htmlPageCountPerLanguage':len(html_pages),'files':copy.deepcopy(files)}
        write('policy-projection.json',_raw(manifest))
        def validate():
            checkpoint();bound.validate(files)
            for name in files:safe(bound.read(name).decode('utf-8'))
            if _strict_projection_json(bound.read('policy-projection.json'))!=manifest:
                raise BusinessExportError('export_projection_roundtrip_mismatch')
            checkpoint()
        with publication_guard():
            validate()
            if output.exists() or output.is_symlink():raise BusinessExportError('export_destination_exists')
            if finish_reader is not None:finish_reader()
            checkpoint();validate();_promote(bound,output);validate()
            result={**summary,'status':'exported','entrypoint':'index.html','languages':list(LANGUAGES),
                    'outputBytes':total,'fileCount':len(files),'files':copy.deepcopy(files)}
            safe(result);checkpoint();bound.verify_published()
        success=True
        return result
    except BusinessExportError as exc:
        failure=exc;exc.selected=selected;exc.processed=processed
        exc.report={'status':'blocked','projection':'policy_projection','reason':exc.code,
                    'selectedRecords':selected,'processedRecords':processed,'selectionTraversal':'INCOMPLETE'}
        raise
    except Exception:
        failure=BusinessExportError('export_validation_failed',selected=selected,processed=processed)
        failure.report={'status':'blocked','projection':'policy_projection','reason':failure.code,
                        'selectedRecords':selected,'processedRecords':processed,'selectionTraversal':'INCOMPLETE'}
        raise failure from None
    finally:
        if bound is not None:
            if not success:
                cleanup=bound.cleanup()
                if failure is not None:failure.cleanup=cleanup
            bound.close()


def export_business(reader, output_dir, *, pins, profile, authorize, publication_guard,
                    check_profile, check_snapshot, export_action='export_html',
                    max_output_bytes=MAX_OUTPUT_BYTES, cancel=None, source_entries=None,
                    link_scope='ordinary', global_lookup=None, artifact_observer=None,
                    projection='full', private_binding=None, finish_reader=None):
    """Write a new business child tree; caller budgets source+business together.

    authorize(action) is trusted server ACL context and must return allow/revision.
    publication_guard() uses the same trusted lock as ACL writes. The reader is
    already open; its successful context exit remains the caller's responsibility.
    """
    if _guard is None or _canonical is None:raise BusinessExportError('export_dependencies_required')
    if projection not in ('full','business_only','policy_projection'):raise BusinessExportError('export_projection_invalid')
    if projection=='policy_projection':
        if finish_reader is not None and not callable(finish_reader):raise BusinessExportError('export_projection_dependencies_required')
        if export_action!='export_html' or source_entries is not None or link_scope!='ordinary' or global_lookup is not None or artifact_observer is not None or private_binding is not None:
            raise BusinessExportError('export_projection_scope_invalid')
        return _export_policy_projection(reader,output_dir,pins=pins,profile=profile,authorize=authorize,
            publication_guard=publication_guard,check_profile=check_profile,check_snapshot=check_snapshot,
            max_output_bytes=max_output_bytes,cancel=cancel,finish_reader=finish_reader)
    if projection=='business_only':
        if finish_reader is not None and not callable(finish_reader):raise BusinessExportError('export_projection_dependencies_required')
        if export_action!='export_html' or source_entries is not None or link_scope!='ordinary' or global_lookup is not None or artifact_observer is not None:
            raise BusinessExportError('export_projection_scope_invalid')
        return _export_business_only(reader,output_dir,pins=pins,profile=profile,authorize=authorize,
            publication_guard=publication_guard,check_profile=check_profile,check_snapshot=check_snapshot,
            max_output_bytes=max_output_bytes,cancel=cancel,private_binding=private_binding,finish_reader=finish_reader)
    if export_action not in ('export_html','export_bundle'):raise BusinessExportError('export_action_invalid')
    if type(max_output_bytes) is not int or not 1<=max_output_bytes<=MAX_OUTPUT_BYTES:raise BusinessExportError('export_budget_invalid')
    if not all(callable(x) for x in (authorize,publication_guard,check_profile,check_snapshot)):
        raise BusinessExportError('export_authority_callbacks_required')
    if type(pins) is not dict or set(pins)!=set(PIN_KEYS) or any(not isinstance(pins[k],str) or not pins[k] for k in PIN_KEYS):
        raise BusinessExportError('export_pins_invalid')
    if link_scope not in ('ordinary','partitioned') or (link_scope=='ordinary' and global_lookup is not None) or (link_scope=='partitioned' and not callable(global_lookup)):
        raise BusinessExportError('export_link_scope_invalid')
    if artifact_observer is not None and (not callable(artifact_observer) or link_scope!='partitioned'):
        raise BusinessExportError('export_observer_scope_invalid')
    expected_source={lang:('../../'+lang+'/index.html' if link_scope=='ordinary' else '../../../source/'+lang+'/index.html') for lang in LANGUAGES}
    if source_entries is not None and (type(source_entries) is not dict or set(source_entries)!=set(LANGUAGES) or any(source_entries[k]!=expected_source[k] for k in LANGUAGES)):
        raise BusinessExportError('export_source_link_invalid')
    if link_scope=="partitioned" and source_entries is None:raise BusinessExportError("export_source_link_invalid")
    pins=copy.deepcopy(pins);profile=copy.deepcopy(profile)
    output=Path(output_dir).absolute();parent_identity=_safe_parent(output)
    selected=None;processed=0;revision=None;total_bytes=0;files={};unknown=0;stage=None;bound=None;success=False;failure=None
    def checkpoint():
        nonlocal revision
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):raise BusinessExportError('export_cancelled')
        permits=[authorize(action) for action in (export_action,'read_structure','read_policy','read_evidence')]
        if any(type(p) is not dict or p.get('decision')!='allow' or type(p.get('revision')) is not int for p in permits):raise BusinessExportError('export_access_denied')
        current={p['revision'] for p in permits}
        if len(current)!=1:raise BusinessExportError('export_acl_revision_changed')
        current=current.pop()
        if revision is not None and revision!=current:raise BusinessExportError('export_acl_revision_changed')
        revision=current
        if any(reader.metadata.get(k)!=v for k,v in pins.items()):raise BusinessExportError('export_snapshot_mismatch')
    def write(name,raw):
        nonlocal total_bytes
        checkpoint()
        if isinstance(raw,str):raw=raw.encode('utf-8')
        if len(raw)>MAX_PAGE_BYTES:raise BusinessExportError('export_page_budget')
        if total_bytes+len(raw)>max_output_bytes:raise BusinessExportError('export_total_budget')
        _guard.ensure_public_safe(raw.decode('utf-8'),profile=profile,allow_local_paths=False,require_profile=True)
        info=bound.write(name,raw)
        files[name]=dict(sha256=_sha(raw),bytes=len(raw));total_bytes+=len(raw)
        if artifact_observer is not None:artifact_observer(name,files[name],info)
    try:
        checkpoint()
        selected=reader.metadata.get('recordCount')
        if type(selected) is not int or not 0<=selected<=MAX_RECORDS:raise BusinessExportError('export_record_denominator_invalid')
        if check_profile() is not True or check_snapshot() is not True:raise BusinessExportError('export_context_changed')
        _guard.ensure_public_safe(pins,profile=profile,require_profile=True)
        bound=_BoundArtifacts(output,parent_identity);stage=bound.create_stage()
        index={};counts={kind:0 for kind in KINDS}
        for row in reader.iter_records(page_size=100):
            checkpoint()
            if _validate_record is not None:_validate_record(row)
            elif any(isinstance(f,dict) and isinstance(f.get('value'),dict) and f['value'].get('type') in {'property_type','formula_mapping','policy_composition','finite_contexts','clock_basis'} for f in row.get('facets',{}).values()):raise BusinessExportError('export_semantic_validator_required')
            raw=_raw(row)
            if len(raw)>MAX_RECORD_BYTES:raise BusinessExportError('export_record_budget')
            if type(row) is not dict or row.get('kind') not in KINDS or not isinstance(row.get('id'),str) or not row['id']:raise BusinessExportError('export_record_invalid')
            if row['id'] in index:raise BusinessExportError('export_duplicate_identity')
            if row.get('contentDigest')!=_sha(_raw({k:v for k,v in row.items() if k!='contentDigest'})):raise BusinessExportError('export_record_digest_mismatch')
            if processed>=selected or processed>=MAX_RECORDS:raise BusinessExportError('export_record_denominator_mismatch')
            key=_filename(row['id']);index[row['id']]=dict(key=key,name=row.get('name','UNKNOWN'),kind=row['kind'])
            write('records/'+key+'.json',raw)
            counts[row['kind']]+=1;processed+=1
        if processed!=selected:raise BusinessExportError('export_record_denominator_mismatch')
        write('metadata.json',_raw(reader.metadata))
        processing_reference=reader.metadata.get('processingLedger')
        if processing_reference is not None:
            if (link_scope!='partitioned' or type(processing_reference)is not dict or set(processing_reference)!={'path','bytes','sha256','scope','pins','entryCount','scopeDigest'}
                    or processing_reference['path']!='../../processing/manifest.json' or processing_reference['scope']!='global_original_inputs'
                    or processing_reference['pins']!=pins or processing_reference['entryCount']!=reader.metadata.get('coverage',{}).get('processingEntryCount')
                    or any(type(processing_reference[key])is not str or not re.fullmatch('[0-9a-f]{64}',processing_reference[key])for key in('sha256','scopeDigest'))
                    or type(processing_reference['bytes'])is not int or processing_reference['bytes']<=0):raise BusinessExportError('export_processing_reference_invalid')
            write('processing-reference.json',_raw(processing_reference))
        elif reader.metadata.get('coverage',{}).get('processingContract')is True:
            if link_scope=='partitioned':raise BusinessExportError('export_global_processing_reference_required')
            offset=0;seen=0
            while True:
                page=reader.processing(offset=offset,limit=100)
                if page.get('offset')!=offset or page.get('returned')!=len(page.get('entries',[])):raise BusinessExportError('export_processing_denominator_mismatch')
                write('processing/%06d.json'%(offset//100),_raw(page));seen+=len(page['entries'])
                if page['nextOffset']is None:break
                if type(page['nextOffset'])is not int or page['nextOffset']<=offset:raise BusinessExportError('export_processing_paging_invalid')
                offset=page['nextOffset']
            if seen!=reader.metadata['coverage'].get('processingEntryCount'):raise BusinessExportError('export_processing_denominator_mismatch')
        source='<urn:companion:business:source:'+_filename(pins['sourceSnapshotId'])+'>'
        business='<urn:companion:business:snapshot:'+_filename(pins['businessSnapshotId'])+'>'
        lineage=_triple(source,RDF+'type','<'+PROV+'Entity>')+_triple(business,RDF+'type','<'+PROV+'Entity>')+_triple(business,PROV+'wasDerivedFrom',source)
        for key,value in pins.items():lineage+=_triple(business,NS+key,_lit(value))
        previous=reader.metadata.get('parentBusinessSnapshotId')
        if previous:lineage+=_triple(business,PROV+'wasRevisionOf','<urn:companion:business:snapshot:'+_filename(previous)+'>')
        write('lineage.ttl',lineage);write('shapes.ttl',_shapes())
        def lookup(identity):
            if global_lookup is None or not isinstance(identity,str):return None
            result=global_lookup(identity)
            if result is None:return None
            if (type(result) is not dict or set(result)!={'bucket','page'} or result['bucket']!=_filename(identity)[:2]
                    or type(result['page']) is not int or not 1<=result['page']<=1000000):
                raise BusinessExportError('export_lookup_invalid')
            return result
        class Known:
            def __contains__(self,identity):return identity in index or lookup(identity) is not None
        known=Known()
        losses=[];entries=[]
        for identity,entry in index.items():
            key=entry['key'];row=json.loads(bound.read('records/'+key+'.json').decode('utf-8'))
            write('rdf/'+key+'.ttl',_rdf_record(row,pins,known))
            losses.append(dict(recordId=identity,json='records/'+key+'.json',rdf='rdf/'+key+'.ttl',
                fields=sorted(k for k in row if k not in ('id','kind','name','namespace','domain','conceptKey','support','businessApproval','contentDigest','subject','predicate','object','objectOrExpression','role','cardinality')),
                structuredRelationFields=[k for k in ('subject','predicate','object','objectOrExpression','role','cardinality') if k in row and not isinstance(row[k],str)],
                meaning='Complete canonical JSON is retained as xsd:string-compatible literal and original JSON. Domain-specific facet/interval/alias semantics are not asserted as RDF axioms; no OWL inference or executable policy mapping.'))
            facets=row.get('facets',{})
            if not isinstance(facets,dict):raise BusinessExportError('export_facets_invalid')
            unknown+=sum(isinstance(v,dict) and v.get('status')=='UNKNOWN' for v in facets.values())
            entries.append(dict(id=identity,**entry))
            for lang in LANGUAGES:
                t=TEXT[lang]
                def endpoint(value):
                    if isinstance(value,str) and value in index:return '<a href="'+index[value]['key']+'.html">'+_e(value)+'</a>'
                    target=lookup(value)
                    if target is not None:
                        href='../../../../lookup/'+lang+'/'+target['bucket']+'-%06d.html'%target['page']+'#r-'+_filename(value)
                        return '<a href="'+href+'">'+_e(value)+'</a>'
                    return '<code>'+_e(json.dumps(value,ensure_ascii=False))+'</code>'
                body='<p><a href="../index.html">'+_e(t[1])+'</a> · <a href="../../records/'+key+'.json">'+_e(t[9])+'</a></p>'
                if source_entries:body+='<p><a href="../'+source_entries[lang]+'">'+_e(t[6])+'</a></p>'
                body+='<h2>'+_e(t[2])+'</h2><dl>'
                for name in ('id','kind','namespace','domain','conceptKey','support','businessApproval','runtime','executionAuthorization'):
                    default='NOT_OBSERVED' if name=='runtime' else 'NOT_PROVIDED' if name=='executionAuthorization' else 'UNKNOWN'
                    body+='<dt>'+_e(name)+'</dt><dd><code>'+_e(row.get(name,default))+'</code></dd>'
                body+='</dl>'
                if row['kind']=='business_relation' or any(k in row for k in ('subject','object','predicate')):
                    body+='<h2>'+_e(t[5])+'</h2><p>'+endpoint(row.get('subject','UNKNOWN'))+' → '+endpoint(row.get('predicate','UNKNOWN'))+' → '+endpoint(row.get('object',row.get('objectOrExpression','UNKNOWN')))+'</p>'
                    body+='<p>role: '+endpoint(row.get('role','UNKNOWN'))+'; cardinality: '+endpoint(row.get('cardinality','UNKNOWN'))+'</p>'
                body+='<h2>'+_e(t[3])+'</h2><dl>'
                keys=list(POLICY_FACETS) if row['kind']=='business_policy' else list(facets)
                keys+= [k for k in facets if k not in keys]
                for name in keys:
                    facet=facets.get(name,dict(status='UNKNOWN',reason='not_provided'))
                    body+='<dt>'+_e(name)+'</dt><dd><pre>'+_e(json.dumps(facet,ensure_ascii=False,sort_keys=True,indent=2))+'</pre></dd>'
                body+='</dl><h2>'+_e(t[4])+'</h2><pre>'+_e(json.dumps(row.get('sourceAnchors',[]),ensure_ascii=False,indent=2))+'</pre>'
                body+='<details><summary>'+_e(t[9])+'</summary><pre>'+_e(_raw(row).decode('utf-8'))+'</pre></details>'
                write(lang+'/records/'+key+'.html',_page(lang,str(row.get('name',identity)),body,depth=1))
        write('mapping-loss.json',_raw(dict(status='EXPLICIT_PARTIAL_SEMANTIC_MAPPING',records=losses,allOriginalJsonRetained=True,shapeValidation='NOT_RUN',rdfSyntax='RDF 1.1 Turtle; full-IRI N-Triples subset',semanticTruthValidated=False)))
        write('style.css','body{font:1rem system-ui,sans-serif;max-width:75rem;margin:auto;padding:1rem;line-height:1.6;background:#101827;color:#eef4ff}a{color:#9dd7ff}a:focus-visible,summary:focus-visible{outline:3px solid #ffd36a;outline-offset:3px}.skip{position:absolute;top:-5rem}.skip:focus{top:0}nav{display:flex;flex-wrap:wrap;gap:.7rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #526078;padding:.7rem}dt{font-weight:bold}dd{margin:0 0 1rem}li{padding:.4rem}footer{margin-top:2rem}code{overflow-wrap:anywhere}@media(max-width:40rem){body{padding:.7rem}dd{margin-left:0}}')
        pages=max(1,(len(entries)+PAGE_SIZE-1)//PAGE_SIZE)
        for lang in LANGUAGES:
            t=TEXT[lang]
            for page in range(pages):
                name='index.html' if page==0 else 'page-'+str(page+1)+'.html'
                body='<p>'+_e(t[1])+': '+str(processed)+' / '+str(selected)+'; UNKNOWN facets: '+str(unknown)+'</p>'
                if source_entries:body+='<p><a href="'+source_entries[lang]+'">'+_e(t[6])+'</a></p>'
                body+='<h2>'+_e(t[1])+'</h2><ol start="'+str(page*PAGE_SIZE+1)+'">'
                for entry in entries[page*PAGE_SIZE:(page+1)*PAGE_SIZE]:body+='<li><a href="records/'+entry['key']+'.html">'+_e(entry['name'])+'</a> <code>'+_e(entry['id'])+'</code> ('+_e(entry['kind'])+')</li>'
                body+='</ol><nav aria-label="Pagination">'
                if page>0:body+='<a rel="prev" href="'+('index.html' if page==1 else 'page-'+str(page)+'.html')+'">'+_e(t[7])+'</a>'
                if page+1<pages:body+='<a rel="next" href="page-'+str(page+2)+'.html">'+_e(t[8])+'</a>'
                body+='</nav><h2>'+_e(t[13])+'</h2><pre>'+_e(_raw(dict(pins=pins,coverage=reader.metadata.get('coverage','UNKNOWN'),counts=counts)).decode('utf-8'))+'</pre>'
                body+='<p><a href="../metadata.json">metadata.json</a> · <a href="../mapping-loss.json">mapping-loss.json</a> · <a href="../lineage.ttl">PROV</a> · <a href="../shapes.ttl">SHACL</a></p>'
                write(lang+'/'+name,_page(lang,t[0],body))
        write('index.html',_page('en',TEXT['en'][0],'<nav>'+''.join('<a lang="'+lang+'" href="'+lang+'/index.html">'+lang+'</a> ' for lang in LANGUAGES)+'</nav>',depth=-1))
        manifest=dict(format='companion.business-export.v1',pins=pins,selectedRecords=selected,recordCount=processed,counts=counts,
            unknownFacetObservations=unknown,sourceCoverage=reader.metadata.get('coverage','UNKNOWN'),files=files.copy(),accessRevision=revision,
            sourceAccess='not_read',execution='NOT_OBSERVED',executionAuthorization='NOT_PROVIDED',approvalScope='knowledge_statement_only',
            permissionsChecked=[export_action,'read_structure','read_policy','read_evidence'],exportedCopiesRemotelyRevocable=False,
            mappingLoss='mapping-loss.json',shapeValidation='NOT_RUN',browserVerification='NOT_RUN',wholePolicyCompleteness='UNKNOWN')
        if link_scope=='partitioned':manifest['partition']=copy.deepcopy(reader.metadata.get('partition'))
        write('business-export.json',_raw(manifest))
        with publication_guard():
            checkpoint()
            if check_profile() is not True or check_snapshot() is not True:raise BusinessExportError('export_context_changed')
            bound.verify_parent()
            if output.exists() or output.is_symlink():raise BusinessExportError('export_destination_exists')
            bound.validate(files)
            checkpoint()
            if check_snapshot() is not True or check_profile() is not True:raise BusinessExportError('export_context_changed')
            _promote(bound,output)
            bound.verify_published()
        bound.verify_published()
        success=True
        return dict(status='exported',pins=pins,entrypoint=str(output/'index.html'),languages=list(LANGUAGES),recordCount=processed,
                    selectedRecords=selected,outputBytes=total_bytes,fileCount=len(files),files=files,sourceAccess='not_read',
                    mappingLoss='mapping-loss.json',browserVerification='NOT_RUN',shapeValidation='NOT_RUN')
    except BusinessExportError as exc:
        failure=exc;exc.selected=selected;exc.processed=processed;raise
    except Exception as exc:
        code=getattr(exc,'code',None)
        if link_scope!='partitioned' or type(code) is not str or not re.fullmatch('partitioned_[a-z_]{1,80}',code):code='export_validation_failed'
        failure=BusinessExportError(code,selected=selected,processed=processed)
        raise failure from None
    finally:
        if bound is not None:
            if not success:
                cleanup=bound.cleanup()
                if failure is not None:failure.cleanup=cleanup
            bound.close()
