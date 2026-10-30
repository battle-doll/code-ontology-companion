"""Explicit bounded offline export sets over immutable source/business pins.

The ordinary exporter keeps its limits. This opt-in coordinator uses the
workspace's existing output capacity, disk indexes and directory-bound atomic
publication. No target source file, ACL configuration or principal is exported.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import threading
import signal
import time
import uuid
from contextlib import contextmanager, ExitStack

import companion
import pipeline_acl
import pipeline_store

_store = _exporter = _guard = None
PART_RECORDS = 10000
PART_BYTES = 1024 ** 3
LOOKUP_ROWS = 500
CATALOG_ROWS = 50
FILE_ROWS = 1000
LANGUAGES = ('en','ko','ja','zh-CN','ru')
TITLE = {'en':'Partitioned export','ko':'\ubd84\ud560 \ub0b4\ubcf4\ub0b4\uae30','ja':'\u5206\u5272\u30a8\u30af\u30b9\u30dd\u30fc\u30c8','zh-CN':'\u5206\u7247\u5bfc\u51fa','ru':'\u042d\u043a\u0441\u043f\u043e\u0440\u0442 \u0447\u0430\u0441\u0442\u044f\u043c\u0438'}


class PartitionedExportError(ValueError):
    def __init__(self,code='partitioned_export_failed',report=None):
        self.code=code if type(code) is str and re.fullmatch('[a-z_]{1,100}',code) else 'partitioned_export_failed'
        self.report=report or {};super().__init__(self.code)


def configure(*,store,exporter,privacy_guard):
    global _store,_exporter,_guard
    _store,_exporter,_guard=store,exporter,privacy_guard


def _raw(value):return _exporter._raw(value)
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _part(index):return 'part-%08d'%index


def _parts(name):
    if type(name) is not str or not name or '\\' in name or name.startswith('/'):
        raise PartitionedExportError('partitioned_path_invalid')
    values=name.split('/')
    if any(value in ('','.','..') or ':' in value for value in values):raise PartitionedExportError('partitioned_path_invalid')
    return tuple(values)


def _identity(info,directory=False):
    if _guard._link_like(info):raise PartitionedExportError('partitioned_link_boundary')
    if directory:
        if not stat.S_ISDIR(info.st_mode):raise PartitionedExportError('partitioned_directory_boundary')
        if os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077):raise PartitionedExportError('partitioned_directory_permissions')
        return (info.st_dev,info.st_ino,info.st_mode,getattr(info,'st_uid',0))
    _guard._check_private_file_metadata(info)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise PartitionedExportError('partitioned_file_boundary')
    identity=(info.st_dev,info.st_ino,info.st_mode,getattr(info,'st_uid',0),info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_nlink)
    if os.name=='nt':identity+=(getattr(info,'st_birthtime_ns',None),getattr(info,'st_file_attributes',0))
    return identity


class _SetBoundary:
    """Reuse fixed parent/stage handles; keep the complete inode/hash index on disk."""
    def __init__(self,output,db):
        self.output=output;self.db=db;self.total_bytes=0;self.total_files=0;self.bound=_exporter._BoundArtifacts(output,_exporter._safe_parent(output));self.catalog_mutation_denied=False
        try:
            self.stage=self.bound.create_stage()
            db.execute('CREATE TABLE entries(path TEXT PRIMARY KEY,parent TEXT NOT NULL,depth INTEGER NOT NULL,kind TEXT NOT NULL,identity TEXT NOT NULL,bytes INTEGER NOT NULL,sha TEXT,role TEXT NOT NULL)')
            db.execute('CREATE INDEX entry_parent ON entries(parent,path)')
            db.execute('CREATE INDEX entry_role ON entries(role,path)')
            db.execute('CREATE TABLE expected(path TEXT PRIMARY KEY,root TEXT NOT NULL,bytes INTEGER NOT NULL,sha TEXT NOT NULL,identity TEXT NOT NULL)')
            db.execute('CREATE INDEX expected_root ON expected(root,path)')
        except BaseException:
            try:self.bound.cleanup()
            finally:self.bound.close()
            raise
    def saved(self,name):
        row=self.db.execute('SELECT kind,identity FROM entries WHERE path=?',(name,)).fetchone()
        return (row[0],tuple(json.loads(row[1]))) if row else None
    def record(self,name,info,kind,*,size=0,sha=None,role='payload'):
        parts=_parts(name);identity=_identity(info,kind=='directory')
        previous=self.saved(name)
        if previous is not None and previous!=(kind,identity):raise PartitionedExportError('partitioned_artifact_changed')
        changed=self.db.execute('INSERT OR IGNORE INTO entries VALUES(?,?,?,?,?,?,?,?)',(name,'/'.join(parts[:-1]),len(parts),kind,json.dumps(identity),size,sha,role)).rowcount
        if changed and kind=='file':self.total_bytes+=size;self.total_files+=1
    @contextmanager
    def directory(self,parts,*,create=False,verify_parent=True):
        if verify_parent:self.bound.verify_parent()
        if any(p in ('','.','..') or '/' in p or '\\' in p for p in parts):raise PartitionedExportError('partitioned_path_invalid')
        if self.bound.windows:
            root=self.output if self.bound.published else self.stage
            if not _exporter._same(root.lstat(),self.bound.root_identity):raise PartitionedExportError('partitioned_stage_changed')
            current=root
            for index,part in enumerate(parts):
                current=current/part;name='/'.join(parts[:index+1])
                if create and not current.exists():current.mkdir(mode=0o700);self.record(name,current.lstat(),'directory')
                saved=self.saved(name)
                if saved is None or saved!=('directory',_identity(current.lstat(),True)):raise PartitionedExportError('partitioned_artifact_changed')
            yield current;return
        fd=os.dup(self.bound.stage_fd)
        try:
            for index,part in enumerate(parts):
                name='/'.join(parts[:index+1])
                if create:
                    try:
                        os.mkdir(part,0o700,dir_fd=fd)
                        self.record(name,os.stat(part,dir_fd=fd,follow_symlinks=False),'directory')
                    except FileExistsError:pass
                saved=self.saved(name)
                if saved is None or saved[0]!='directory':raise PartitionedExportError('partitioned_artifact_changed')
                following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                if _identity(os.fstat(following),True)!=saved[1]:os.close(following);raise PartitionedExportError('partitioned_artifact_changed')
                os.close(fd);fd=following
            yield fd
        finally:os.close(fd)
    def mkdir(self,name):
        with self.directory(_parts(name),create=True):pass
    def write(self,name,raw,*,role='payload'):
        parts=_parts(name)
        with self.directory(parts[:-1],create=True) as parent:
            options={} if self.bound.windows else {'dir_fd':parent}
            target=parent/parts[-1] if self.bound.windows else parts[-1]
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,**options)
            try:
                created=os.fstat(fd) if self.bound.windows else None
                if self.bound.windows:security=_guard._windows_profile_security(fd)
                _guard._check_private_file_metadata(os.fstat(fd))
                with os.fdopen(fd,'wb',closefd=False) as handle:handle.write(raw);handle.flush();os.fsync(fd)
                written=os.fstat(fd)
                if self.bound.windows:
                    if (not _exporter._same(created,written) or created.st_mode!=written.st_mode
                            or getattr(created,'st_uid',0)!=getattr(written,'st_uid',0)
                            or created.st_nlink!=written.st_nlink
                            or _guard._windows_profile_security(fd)!=security):
                        raise PartitionedExportError('partitioned_artifact_changed')
                    _identity(written)
                else:self.record(name,written,'file',size=len(raw),sha=_sha(raw),role=role)
            finally:os.close(fd)
            if self.bound.windows:
                try:written=_exporter._closed_written_artifact(target,written,raw,security)
                except _exporter.BusinessExportError:
                    raise PartitionedExportError('partitioned_artifact_changed') from None
                self.record(name,written,'file',size=len(raw),sha=_sha(raw),role=role)
    def _hash_open(self,parent,name,checkpoint):
        options={} if self.bound.windows else {'dir_fd':parent}
        target=parent/name if self.bound.windows else name
        path_before=target.lstat() if self.bound.windows else None
        if self.bound.windows:_identity(path_before)
        fd=os.open(target,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0),**options)
        try:
            before=os.fstat(fd);_identity(before)
            if self.bound.windows:
                security=_guard._windows_profile_security(fd)
                if not _exporter._artifact_same_open_file(path_before,before):
                    raise PartitionedExportError('partitioned_artifact_changed')
            digest=hashlib.sha256();size=0
            with os.fdopen(fd,'rb',closefd=False) as handle:
                while True:
                    block=handle.read(1024*1024)
                    if not block:break
                    checkpoint();size+=len(block);digest.update(block)
            after=os.fstat(fd)
            current=target.lstat() if self.bound.windows else os.stat(name,dir_fd=parent,follow_symlinks=False)
            if _identity(before)!=_identity(after):raise PartitionedExportError('partitioned_artifact_changed')
            if self.bound.windows:
                if (_identity(path_before)!=_identity(current)
                        or _guard._windows_profile_security(fd)!=security):
                    raise PartitionedExportError('partitioned_artifact_changed')
            elif _identity(after)!=_identity(current):raise PartitionedExportError('partitioned_artifact_changed')
            return current,size,digest.hexdigest()
        finally:os.close(fd)
    def observer(self,root):
        _parts(root)
        def observe(name,descriptor,info):
            _parts(name)
            if (type(descriptor) is not dict or set(descriptor)!={'bytes','sha256'}
                    or type(descriptor['bytes']) is not int or descriptor['bytes']<0
                    or type(descriptor['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',descriptor['sha256'])):
                raise PartitionedExportError('partitioned_child_attestation_invalid')
            identity=_identity(info)
            if info.st_size!=descriptor['bytes']:raise PartitionedExportError('partitioned_child_attestation_invalid')
            try:self.db.execute('INSERT INTO expected VALUES(?,?,?,?,?)',(root+'/'+name,root,descriptor['bytes'],descriptor['sha256'],json.dumps(identity)))
            except sqlite3.IntegrityError:raise PartitionedExportError('partitioned_child_attestation_duplicate') from None
        return observe
    def forget_expected(self,root):
        self.db.execute('DELETE FROM expected WHERE root=?',(root,));self.db.commit()
    def expected_summary(self,root):
        return self.db.execute('SELECT count(*),coalesce(sum(bytes),0) FROM expected WHERE root=?',(root,)).fetchone()
    def check_returned_files(self,root,files):
        if type(files) is not dict or len(files)!=self.expected_summary(root)[0]:raise PartitionedExportError('partitioned_child_attestation_mismatch')
        for name,info in files.items():
            _parts(name)
            expected=self.db.execute('SELECT bytes,sha FROM expected WHERE path=? AND root=?',(root+'/'+name,root)).fetchone()
            if expected is None or info!={'bytes':expected[0],'sha256':expected[1]}:
                raise PartitionedExportError('partitioned_child_attestation_mismatch')
    def adopt(self,name,checkpoint):
        """Compare the original producer attestations; never re-seal changed bytes."""
        if self.expected_summary(name)[0]<1:raise PartitionedExportError('partitioned_child_attestation_missing')
        parts=_parts(name)
        with self.directory(parts[:-1]) as parent:
            info=(parent/parts[-1]).lstat() if self.bound.windows else os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
        self.record(name,info,'directory');failure=None;found=0
        def walk(prefix):
            nonlocal failure,found
            with self.directory(_parts(prefix)) as parent:
                with os.scandir(parent) as entries:
                    for item in entries:
                        checkpoint();path=prefix+'/'+item.name
                        # Windows DirEntry.stat omits inode/device/link ids.
                        info=(parent/item.name).lstat() if self.bound.windows else item.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):self.record(path,info,'directory');walk(path)
                        else:
                            expected=self.db.execute('SELECT bytes,sha,identity FROM expected WHERE path=? AND root=?',(path,name)).fetchone()
                            current,size,sha=self._hash_open(parent,item.name,checkpoint)
                            if expected is None:
                                failure='partitioned_child_artifact_set_changed';continue
                            original=tuple(json.loads(expected[2]));found+=1
                            # A changed known inode remains owned for cleanup;
                            # foreign replacements are retained and reported.
                            if _identity(current)[:2]==original[:2]:self.record(path,current,'file',size=size,sha=sha)
                            if (size,sha,_identity(current))!=(expected[0],expected[1],original):failure='partitioned_child_artifact_changed'
        walk(name);self.db.commit()
        if found!=self.expected_summary(name)[0]:failure='partitioned_child_artifact_set_changed'
        if failure is not None:raise PartitionedExportError(failure)
    def read_document(self,name):
        return _store._semantics.loads(self.read_record(name,max_bytes=_exporter.MAX_PAGE_BYTES))
    def freeze_catalog(self):
        """Freeze selector truth after all memberships and child seals exist."""
        protected={'records','parts','expected'}
        schema_actions={getattr(sqlite3,name) for name in ('SQLITE_CREATE_INDEX','SQLITE_CREATE_TABLE','SQLITE_CREATE_TEMP_INDEX',
            'SQLITE_CREATE_TEMP_TABLE','SQLITE_CREATE_TEMP_TRIGGER','SQLITE_CREATE_TEMP_VIEW','SQLITE_CREATE_TRIGGER','SQLITE_CREATE_VIEW',
            'SQLITE_DROP_INDEX','SQLITE_DROP_TABLE','SQLITE_DROP_TEMP_INDEX','SQLITE_DROP_TEMP_TABLE','SQLITE_DROP_TEMP_TRIGGER',
            'SQLITE_DROP_TEMP_VIEW','SQLITE_DROP_TRIGGER','SQLITE_DROP_VIEW','SQLITE_ALTER_TABLE','SQLITE_ATTACH','SQLITE_DETACH')}
        def authorize(action,first,second,database,trigger):
            if ((action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE) and first in protected)
                    or action in schema_actions or action==sqlite3.SQLITE_PRAGMA):
                self.catalog_mutation_denied=True;return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.db.commit();self.db.set_authorizer(authorize)
    def verify_catalog(self,selected,spooled,inventory,pins,checkpoint):
        digest=hashlib.sha256();count=0;part=None;scope=None;offset=0
        for position,identity,key,index in self.db.execute('SELECT position,id,key,part FROM records ORDER BY position'):
            checkpoint()
            if position!=count or key!=_exporter._filename(identity):raise PartitionedExportError('partitioned_catalog_changed')
            if index!=part:
                if scope is not None and offset!=scope['recordCount']:raise PartitionedExportError('partitioned_catalog_changed')
                if type(index) is not int or index!=(part or 0)+1:raise PartitionedExportError('partitioned_catalog_changed')
                metadata=self.read_document('business/'+_part(index)+'/metadata.json');scope=metadata.get('partition');offset=0;part=index
                if (type(scope) is not dict or scope.get('index')!=index or type(scope.get('recordIds')) is not list
                        or type(scope.get('recordCount')) is not int or not 1<=scope['recordCount']<=PART_RECORDS
                        or len(scope['recordIds'])!=scope['recordCount'] or scope.get('globalRecordCount')!=selected
                        or any(metadata.get(k)!=v for k,v in pins.items())):raise PartitionedExportError('partitioned_catalog_changed')
            if offset>=scope['recordCount'] or scope['recordIds'][offset]!=identity:raise PartitionedExportError('partitioned_catalog_changed')
            for lang in LANGUAGES:
                target='business/'+_part(index)+'/'+lang+'/records/'+key+'.html'
                original=self.db.execute('SELECT bytes,sha FROM expected WHERE path=?',(target,)).fetchone()
                actual=self.info(target)
                if original is None or original!=(actual['bytes'],actual['sha256']):raise PartitionedExportError('partitioned_lookup_target_changed')
            encoded=identity.encode();digest.update(len(encoded).to_bytes(8,'big'));digest.update(encoded);count+=1;offset+=1
        if (count!=selected or count!=spooled or digest.digest()!=inventory.digest()
                or (scope is not None and offset!=scope['recordCount'])):raise PartitionedExportError('partitioned_catalog_changed')
        bucket=None;ordinal=0
        for key,current,page in self.db.execute('SELECT key,bucket,page FROM records ORDER BY key'):
            if current!=bucket:bucket=current;ordinal=0
            if current!=key[:2] or page!=ordinal//LOOKUP_ROWS+1:raise PartitionedExportError('partitioned_catalog_changed')
            ordinal+=1
    def size(self):return self.total_bytes
    def count(self):return self.total_files
    def info(self,name):
        row=self.db.execute("SELECT bytes,sha FROM entries WHERE path=? AND kind='file'",(name,)).fetchone()
        if row is None:raise PartitionedExportError('partitioned_artifact_missing')
        return {'path':name,'bytes':row[0],'sha256':row[1]}
    def read_record(self,name,*,max_bytes=None):
        max_bytes=_exporter.MAX_RECORD_BYTES if max_bytes is None else max_bytes
        parts=_parts(name);saved=self.saved(name)
        if saved is None or saved[0]!='file':raise PartitionedExportError('partitioned_artifact_missing')
        with self.directory(parts[:-1]) as parent:
            options={} if self.bound.windows else {'dir_fd':parent}
            target=parent/parts[-1] if self.bound.windows else parts[-1]
            path_before=target.lstat() if self.bound.windows else None
            if self.bound.windows and _identity(path_before)!=saved[1]:
                raise PartitionedExportError('partitioned_artifact_changed')
            fd=os.open(target,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0),**options)
            try:
                opened=os.fstat(fd);before=_identity(opened)
                if self.bound.windows:
                    security=_guard._windows_profile_security(fd)
                    if not _exporter._artifact_same_open_file(path_before,opened):
                        raise PartitionedExportError('partitioned_artifact_changed')
                elif before!=saved[1]:raise PartitionedExportError('partitioned_artifact_changed')
                with os.fdopen(fd,'rb',closefd=False) as handle:raw=handle.read(max_bytes+1)
                if len(raw)>max_bytes or _identity(os.fstat(fd))!=before:raise PartitionedExportError('partitioned_record_budget')
                if self.bound.windows and (_identity(target.lstat())!=_identity(path_before)
                        or _guard._windows_profile_security(fd)!=security):
                    raise PartitionedExportError('partitioned_artifact_changed')
                if _sha(raw)!=self.info(name)['sha256']:raise PartitionedExportError('partitioned_artifact_changed')
                return raw
            finally:os.close(fd)

    def validate(self,checkpoint):
        self.bound.verify_stage()
        for name,kind,encoded,amount,sha in self.db.execute('SELECT path,kind,identity,bytes,sha FROM entries ORDER BY path'):
            checkpoint();parts=_parts(name);expected=tuple(json.loads(encoded))
            with self.directory(parts[:-1]) as parent:
                current=(parent/parts[-1]).lstat() if self.bound.windows else os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
                if _identity(current,kind=='directory')!=expected:raise PartitionedExportError('partitioned_artifact_changed')
                if kind=='file':
                    _,size,digest=self._hash_open(parent,parts[-1],checkpoint)
                    if size!=amount or digest!=sha:raise PartitionedExportError('partitioned_artifact_changed')
        # Each directory is checked independently with a streaming scandir; no
        # catalog-sized expected/actual filename set is built in memory.
        def check_directory(name):
            parts=_parts(name) if name else ()
            with self.directory(parts) as parent:
                count=0
                with os.scandir(parent) as entries:
                    for item in entries:
                        count+=1;relative=(name+'/' if name else '')+item.name
                        if self.saved(relative) is None:raise PartitionedExportError('partitioned_artifact_set_changed')
                expected=self.db.execute('SELECT count(*) FROM entries WHERE parent=?',(name,)).fetchone()[0]
                if count!=expected:raise PartitionedExportError('partitioned_artifact_set_changed')
        check_directory('')
        for (name,) in self.db.execute("SELECT path FROM entries WHERE kind='directory' ORDER BY path"):check_directory(name)
        self.bound.verify_stage()
    def cleanup(self):
        removed=retained=0
        if self.bound.windows:
            if self.bound.windows.pending_rename:
                return {'status':'UNVERIFIED_RETAINED','removed':0,'retained':self.count()}
            try:self.bound.verify_parent()
            except Exception:return {'status':'UNVERIFIED_RETAINED','removed':0,'retained':self.count()}
        for name,kind,encoded in self.db.execute('SELECT path,kind,identity FROM entries ORDER BY depth DESC,path DESC'):
            parts=_parts(name)
            try:
                with self.directory(parts[:-1],verify_parent=False) as parent:
                    options={} if self.bound.windows else {'dir_fd':parent};target=parent/parts[-1] if self.bound.windows else parts[-1]
                    current=target.lstat() if self.bound.windows else os.stat(target,dir_fd=parent,follow_symlinks=False)
                    if _identity(current,kind=='directory')!=tuple(json.loads(encoded)):retained+=1;continue
                    if kind=='directory':os.rmdir(target,**options)
                    else:os.unlink(target,**options)
                    removed+=1
            except (OSError,ValueError):retained+=1
        for name in (self.bound.name,self.output.name):
            try:
                options={} if self.bound.windows else {'dir_fd':self.bound.parent_fd}
                target=self.bound.parent/name if self.bound.windows else name
                current=target.lstat() if self.bound.windows else os.stat(name,dir_fd=self.bound.parent_fd,follow_symlinks=False)
                if _exporter._same(current,self.bound.root_identity):os.rmdir(target,**options)
                else:retained+=1
            except FileNotFoundError:pass
            except OSError:retained+=1
        return {'status':'OWN_ENTRIES_REMOVED' if not retained else 'UNKNOWN_OR_CHANGED_ENTRIES_RETAINED','removed':removed,'retained':retained}
    def close(self):self.bound.close()


class _SubsetReader:
    def __init__(self,reader,db,start,count,index,ids_digest,processing_ledger=None):
        self.reader,self.db,self.start,self.count=reader,db,start,count
        ids=[row[0] for row in db.execute('SELECT id FROM records WHERE position>=? AND position<? ORDER BY position',(start,start+count))]
        if len(ids)!=count or count>PART_RECORDS:raise PartitionedExportError('partitioned_subset_mismatch')
        self.metadata=copy.deepcopy(reader.metadata);self.metadata['recordCount']=count
        self.metadata['partition']={'index':index,'scope':'exact_business_record_ids','recordIds':ids,
            'recordIdsDigest':ids_digest,'recordCount':count,'globalRecordCount':reader.metadata['recordCount'],
            'originalSourceDenominator':reader.metadata.get('coverage',{}).get('sourceCandidates',reader.metadata.get('coverage',{})).get('denominator','UNKNOWN')}
        if processing_ledger is not None:
            self.metadata['processingLedger']={**copy.deepcopy(processing_ledger),'path':'../../processing/manifest.json'}
    def iter_records(self,*,page_size=100):
        if type(page_size) is not int or not 1<=page_size<=200:raise PartitionedExportError('partitioned_page_budget')
        cursor=self.db.execute('SELECT id,key,name,kind,payload FROM records WHERE position>=? AND position<? ORDER BY position',(self.start,self.start+self.count))
        while True:
            self.reader._stable();rows=cursor.fetchmany(page_size)
            if not rows:return
            for identity,key,name,kind,encoded in rows:
                record=_store._semantics.loads(encoded)
                if (record.get('id')!=identity or _exporter._filename(identity)!=key or record.get('name')!=name or record.get('kind')!=kind):
                    raise PartitionedExportError('partitioned_subset_mismatch')
                _store.BusinessReader._index_fields(record)
                yield record


def _document(lang,title,body,depth):
    t=_exporter.TEXT[lang];prefix='../'*depth
    nav=' '.join('<a lang="'+code+'" href="'+prefix+code+'/index.html">'+code+'</a>' for code in LANGUAGES)
    return ('<!doctype html><html lang="'+lang+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'self\'; base-uri \'none\'; form-action \'none\'">'
        '<title>'+_exporter._e(title)+'</title><link rel="stylesheet" href="'+prefix+'style.css"></head><body><header><nav>'+nav+'</nav></header>'
        '<main id="main"><h1>'+_exporter._e(title)+'</h1><p>'+_exporter._e(t[10])+'</p><p>'+_exporter._e(t[11])+'</p><p>'+_exporter._e(t[12])+'</p>'+body+'</main><footer>battle-doll</footer></body></html>')


def export_partitioned(workspace_path,snapshot_id,output_dir,*,language='ko',include_maps=True,
                       part_records=PART_RECORDS,max_output_bytes=None,part_max_bytes=PART_BYTES,
                       cancel=None,source_render=None,source_export=None):
    """Explicit atomic source atlas + complete bounded business export set."""
    if _store is None:raise PartitionedExportError('partitioned_dependencies_required')
    workspace,config=pipeline_store._config(workspace_path);output=Path(output_dir).absolute()
    if language not in LANGUAGES or type(include_maps) is not bool:raise PartitionedExportError('partitioned_language_invalid')
    if type(part_records) is not int or not 1<=part_records<=PART_RECORDS:raise PartitionedExportError('partitioned_record_budget')
    if type(part_max_bytes) is not int or not 1<=part_max_bytes<=PART_BYTES:raise PartitionedExportError('partitioned_part_budget')
    configured=config['budgets']['max_output_bytes'];budget=configured if max_output_bytes is None else max_output_bytes
    if type(budget) is not int or not 1<=budget<=configured:raise PartitionedExportError('partitioned_total_budget_invalid')
    if output==workspace or workspace in output.parents:raise PartitionedExportError('partitioned_destination_inside_workspace')
    if source_render is None:
        from pipeline_html import render_pipeline
        source_render=render_pipeline
    if source_export is None:
        from pipeline_export import export_bundle
        source_export=export_bundle
    profile=_guard.load_profile((workspace,output),required=True)
    _guard.ensure_public_safe({},profile=profile,require_profile=True)
    job_id='pe-'+uuid.uuid4().hex;jobs=pipeline_store._mkdir(workspace,'.export-jobs');job=pipeline_store._mkdir(jobs,job_id)
    path=job/'catalog.sqlite';pipeline_store._atomic(path,b'')
    db=sqlite3.connect(str(path));db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-2048')
    db.execute('CREATE TABLE records(position INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,key TEXT UNIQUE NOT NULL,bucket TEXT NOT NULL,page INTEGER NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,part INTEGER)')
    db.execute('CREATE INDEX lookup_page ON records(bucket,page,key)')
    db.execute('CREATE TABLE parts(number INTEGER PRIMARY KEY,start INTEGER NOT NULL,count INTEGER NOT NULL,descriptor TEXT NOT NULL)')
    boundary=None;reader=None;success=False;pins={};selected=None;processed=0;spooled=0;original_denominator="UNKNOWN";source_selected="UNKNOWN";current_part=0;attempts=[];revision=None;component="business_inventory";current_size=0;failure=None;source_metrics={};source_rdf_metrics={}
    started=time.monotonic()
    def progress(status,reason=None):
        value={'schemaVersion':1,'jobId':job_id,'status':status,'reason':reason,'pins':pins,
            'selectedSourceRecords':source_selected,'selectedBusinessRecords':selected,'processedBusinessRecords':processed,'spooledRecords':spooled,'originalSourceDenominator':original_denominator,'remainingBusinessRecords':max(0,selected-processed) if type(selected) is int else 'UNKNOWN',
            'part':current_part,'targetComponent':component,'attemptedStart':processed,'attemptedCount':current_size,'attempts':attempts,'configuredOutputBytes':configured,'effectiveOutputBytes':budget,
            'sourceComponent':source_metrics,'sourceRdfComponent':source_rdf_metrics,'stagingToken':boundary.bound.name if boundary is not None else None,
            'elapsedSeconds':round(time.monotonic()-started,6),'outputBytes':boundary.size() if boundary is not None else 0,'workingCatalogBytes':path.stat().st_size if path.exists() else 0,
            'sourceAccess':'not_read','businessCompleteness':'PARTIAL','wholeBusinessRuleCoverage':'UNKNOWN',
            'alternatives':['review_existing_capacity_configuration','explicitly_select_a_different_export_scope'] if status=='BLOCKED' else []}
        _guard.ensure_public_safe(value,profile=profile,require_profile=True)
        pipeline_store._atomic(job/'progress.json',_raw(value));return value
    def checkpoint():
        nonlocal revision
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):raise PartitionedExportError('partitioned_cancelled')
        if boundary is not None:boundary.bound.verify_parent()
        try:grant=pipeline_acl.authorize_many(workspace,('export_html','export_bundle','read_structure','read_policy','read_evidence'),snapshot_id)
        except pipeline_acl.AccessDenied:raise PartitionedExportError('partitioned_access_denied') from None
        if grant.get('decision')!='allow':raise PartitionedExportError('partitioned_access_denied')
        current=grant.get('revision')
        if revision is not None and current!=revision:raise PartitionedExportError('partitioned_acl_revision_changed')
        revision=current
        if reader is not None:
            try:reader._stable()
            except pipeline_store.PipelineError:raise PartitionedExportError('partitioned_source_snapshot_changed') from None
            except _store.BusinessStoreError as exc:
                if exc.code in ('source_snapshot_not_current','business_source_or_spec_stale'):raise PartitionedExportError('partitioned_source_snapshot_changed') from None
                raise PartitionedExportError('partitioned_business_snapshot_changed') from None
        return False
    def check_budget(extra=0):
        amount=boundary.size() if boundary is not None else 0
        if amount+path.stat().st_size+extra>budget:raise PartitionedExportError('partitioned_total_budget')
    def write(name,value,*,role='payload'):
        checkpoint();raw=value.encode('utf-8') if isinstance(value,str) else value
        if len(raw)>_exporter.MAX_PAGE_BYTES:raise PartitionedExportError('partitioned_page_budget')
        check_budget(len(raw));_guard.ensure_public_safe(raw.decode('utf-8'),profile=profile,allow_local_paths=False,require_profile=True)
        boundary.write(name,raw,role=role)
    def observe(root):
        original=boundary.observer(root);observed=0
        def capture(name,descriptor,info):
            nonlocal observed
            original(name,descriptor,info);observed+=descriptor['bytes'];check_budget(observed)
        return capture
    def stable_profile():return _guard.load_profile((workspace,output),required=True)==profile
    try:
        checkpoint();metadata=_store.status(workspace,snapshot_id)
        if metadata.get('status')!='ready':raise PartitionedExportError('partitioned_business_not_ready')
        pins={key:metadata[key] for key in _exporter.PIN_KEYS};selected=metadata['recordCount']
        original_denominator=metadata.get('coverage',{}).get('sourceCandidates',metadata.get('coverage',{})).get('denominator','UNKNOWN')
        if type(selected) is not int or not 0<=selected<=config['budgets']['max_records']:raise PartitionedExportError('partitioned_inventory_budget')
        with _store.open_reader(workspace,snapshot_id,metadata['businessSnapshotId'],metadata['businessDigest']) as opened:
            reader=opened;source_selected=reader.source_reader.metadata['recordCount'];boundary=_SetBoundary(output,db);progress('STAGING')
            processing_ledger=None
            if reader.metadata.get('coverage',{}).get('processingContract')is True:
                # One global ledger, independent of record partition count.
                # Existing payload catalogs attest every bounded page hash.
                component='processing_ledger';offset=0;pages=0;outcomes=0;ledger_hash=hashlib.sha256();summary=None
                while True:
                    checkpoint();page=reader.processing(offset=offset,limit=100)
                    if page.get('offset')!=offset or page.get('returned')!=len(page.get('entries',[])):raise PartitionedExportError('partitioned_processing_paging')
                    if summary is None:summary=page['summary']
                    if page['summary']!=summary:raise PartitionedExportError('partitioned_processing_scope_changed')
                    raw=_raw(page);write('processing/page-%08d.json'%pages,raw)
                    ledger_hash.update(len(raw).to_bytes(8,'big'));ledger_hash.update(raw);pages+=1;outcomes+=len(page['entries'])
                    if page['nextOffset']is None:break
                    if type(page['nextOffset'])is not int or page['nextOffset']<=offset:raise PartitionedExportError('partitioned_processing_paging')
                    offset=page['nextOffset']
                if outcomes!=reader.metadata['coverage'].get('processingEntryCount'):raise PartitionedExportError('partitioned_processing_denominator')
                ledger={'schemaVersion':1,'scope':'global_original_inputs','pins':pins,'summary':summary,'entryCount':outcomes,'pageCount':pages,
                    'pageLimit':100,'pagePattern':'page-%08d.json','pagesDigest':ledger_hash.hexdigest(),'pagesDigestEncoding':'length-prefixed-canonical-json-page-order-v1'}
                write('processing/manifest.json',_raw(ledger))
                processing_ledger={**boundary.info('processing/manifest.json'),'scope':'global_original_inputs','pins':pins,'entryCount':outcomes,'scopeDigest':_sha(_raw(summary))}
                check_budget()
            inventory=hashlib.sha256();payload_inventory=hashlib.sha256();count=0
            for row in reader.iter_records(page_size=100):
                checkpoint();raw=_raw(row)
                if len(raw)>_exporter.MAX_RECORD_BYTES:raise PartitionedExportError('partitioned_record_budget')
                key=_exporter._filename(row['id'])
                try:db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,NULL)',(count,row['id'],key,key[:2],0,row['name'],row['kind'],raw.decode()))
                except sqlite3.IntegrityError:raise PartitionedExportError('partitioned_duplicate_identity') from None
                identity=row['id'].encode();inventory.update(len(identity).to_bytes(8,'big'));inventory.update(identity)
                payload_inventory.update(len(raw).to_bytes(8,'big'));payload_inventory.update(raw);count+=1;spooled=count
                if count>selected:raise PartitionedExportError('partitioned_inventory_mismatch')
                if count%100==0:db.commit();check_budget()
            db.commit();check_budget()
            if count!=selected:raise PartitionedExportError('partitioned_inventory_mismatch')
            bucket=None;ordinal=0
            for key,current in db.execute('SELECT key,bucket FROM records ORDER BY key'):
                if current!=bucket:bucket=current;ordinal=0
                db.execute('UPDATE records SET page=? WHERE key=?',(ordinal//LOOKUP_ROWS+1,key));ordinal+=1
            db.commit();checkpoint()
            component='source_atlas';source_started=time.monotonic();source_budget=budget-boundary.size()-path.stat().st_size
            source_metrics={'sourceRecordDenominator':source_selected,'status':'STAGING','maxOutputBytes':source_budget}
            if source_budget<1:raise PartitionedExportError('partitioned_total_budget')
            source=source_render(workspace,snapshot_id,boundary.stage/'source',language=language,include_maps=include_maps,
                max_output_bytes=source_budget,cancel=checkpoint,include_business=False,catalog_scope='partitioned',artifact_observer=observe('source'))
            boundary.adopt('source',checkpoint)
            if boundary.expected_summary('source')!=(source.get('fileCount'),source.get('outputBytes')):
                raise PartitionedExportError('partitioned_child_summary_mismatch')
            source_metrics={'recordCount':source['recordCount'],'outputBytes':source['outputBytes'],'fileCount':source['fileCount'],
                'maxOutputBytes':source_budget,'elapsedSeconds':round(time.monotonic()-source_started,6),'status':'COMPLETE'}
            check_budget();progress('SOURCE_READY')
            # Source RDF/interchange is preserved once through the existing
            # portable exporter. Its default still includes business; only this
            # explicit container uses the separately exported business parts.
            component='source_rdf';rdf_started=time.monotonic()
            rdf_budget=budget-boundary.size()-path.stat().st_size
            source_rdf_metrics={'sourceRecordDenominator':source_selected,'status':'STAGING','maxOutputBytes':rdf_budget}
            if rdf_budget<1024:raise PartitionedExportError('partitioned_total_budget')
            progress('SOURCE_RDF_STAGING')
            before_bytes,before_files=boundary.size(),boundary.count()
            source_bundle=source_export(workspace,snapshot_id,boundary.stage/'source-rdf',
                max_output_bytes=rdf_budget,cancel=checkpoint,include_business=False,artifact_observer=observe('source-rdf'))
            boundary.adopt('source-rdf',checkpoint)
            bundle_manifest=boundary.read_document('source-rdf/bundle.json')
            source_meta=reader.source_reader.metadata
            if (bundle_manifest.get('format')!='code-ontology-bundle/1' or bundle_manifest.get('businessScope')!='explicit_source_only_bundle'
                    or bundle_manifest.get('recordCount')!=source_meta['recordCount']
                    or any(bundle_manifest.get(k)!=source_meta[k] for k in ('snapshotId','analysisSpecId','sourceFingerprint'))):
                raise PartitionedExportError('partitioned_child_scope_mismatch')
            bundle_files=bundle_manifest.get('artifacts')
            if type(bundle_files) is not dict or len(bundle_files)+1!=boundary.expected_summary('source-rdf')[0]:
                raise PartitionedExportError('partitioned_child_attestation_mismatch')
            for name,info in bundle_files.items():
                _parts(name);actual=boundary.info('source-rdf/'+name)
                if info!={'bytes':actual['bytes'],'sha256':actual['sha256']}:raise PartitionedExportError('partitioned_child_attestation_mismatch')
            if source_bundle.get('recordCount')!=source.get('recordCount') or source.get('recordCount')!=reader.source_reader.metadata['recordCount']:
                raise PartitionedExportError('partitioned_source_inventory_mismatch')
            source_rdf_metrics={'recordCount':source_bundle['recordCount'],'outputBytes':boundary.size()-before_bytes,
                'fileCount':boundary.count()-before_files,'maxOutputBytes':rdf_budget,
                'elapsedSeconds':round(time.monotonic()-rdf_started,6),'status':'COMPLETE'}
            check_budget();progress('SOURCE_RDF_READY')
            boundary.mkdir('business');limit=part_records
            def lookup(identity):
                if type(identity) is not str:return None
                row=db.execute('SELECT bucket,page FROM records WHERE id=?',(identity,)).fetchone()
                return {'bucket':row[0],'page':row[1]} if row else None
            while processed<selected:
                checkpoint();component="business_part";current_part+=1;size=min(limit,selected-processed);attempts=[]
                while True:
                    current_size=size;checkpoint();ids=[row[0] for row in db.execute('SELECT id FROM records WHERE position>=? AND position<? ORDER BY position',(processed,processed+size))]
                    ids_digest=_sha(_raw(ids));subset=_SubsetReader(reader,db,processed,size,current_part,ids_digest,processing_ledger)
                    remaining=budget-boundary.size()-path.stat().st_size
                    part_cap=min(part_max_bytes,PART_BYTES);available=min(part_cap,remaining)
                    binding='global_remaining' if remaining<=part_cap else 'part_cap'
                    attempt={'records':size,'budgetBytes':available,'remainingTotalBytes':remaining,'partCapBytes':part_cap,'budgetBinding':binding}
                    name='business/'+_part(current_part)
                    if available<1:raise PartitionedExportError('partitioned_total_budget')
                    progress('PART_STAGING')
                    try:
                        result=_exporter.export_business(subset,boundary.stage/'business'/_part(current_part),pins=pins,profile=profile,
                            authorize=lambda action:pipeline_acl.authorize(workspace,action,snapshot_id),
                            publication_guard=lambda:companion._snapshot_write_lock(workspace),check_profile=stable_profile,
                            check_snapshot=lambda:(checkpoint() is False),max_output_bytes=available,cancel=checkpoint,
                            source_entries={lang:'../../../source/'+lang+'/index.html' for lang in LANGUAGES},
                            link_scope='partitioned',global_lookup=lookup,artifact_observer=observe(name))
                        attempts.append({**attempt,'status':'EXPORTED','outputBytes':result['outputBytes'],'retryDecision':'not_needed'});break
                    except _exporter.BusinessExportError as exc:
                        is_budget=exc.code in ('export_total_budget','export_page_budget')
                        decision=('blocked_global_total' if exc.code=='partitioned_total_budget' else 'blocked_export_error' if not is_budget else 'blocked_global_total' if binding=='global_remaining'
                            else 'blocked_single_record' if size<=1 else 'blocked_cleanup' if getattr(exc,'cleanup',{}).get('retained',0) else 'halve_part_records')
                        attempts.append({**attempt,'status':'FAILED','reason':exc.code,'retryDecision':decision})
                        boundary.forget_expected(name)
                        pipeline_store._atomic(job/(_part(current_part)+'-attempts.json'),_raw({'part':current_part,'globalSelected':selected,
                            'originalSourceDenominator':original_denominator,'pins':pins,'processedBusinessRecords':processed,'start':processed,'attempts':attempts}))
                        if decision=='blocked_global_total':raise PartitionedExportError('partitioned_total_budget') from None
                        if decision=='blocked_cleanup':raise PartitionedExportError('partitioned_retry_cleanup_incomplete') from None
                        if decision!='halve_part_records':raise
                        size=max(1,size//2)
                boundary.check_returned_files(name,result.get('files'))
                if (result.get('status')!='exported' or result.get('pins')!=pins or result.get('recordCount')!=size or result.get('selectedRecords')!=size
                        or boundary.expected_summary(name)!=(result.get('fileCount'),result.get('outputBytes'))):
                    raise PartitionedExportError('partitioned_child_summary_mismatch')
                boundary.adopt(name,checkpoint);check_budget()
                child_manifest=boundary.read_document(name+'/business-export.json');child_metadata=boundary.read_document(name+'/metadata.json')
                if (child_metadata!=subset.metadata or child_manifest.get('pins')!=pins or child_manifest.get('partition')!=subset.metadata['partition']
                        or child_manifest.get('selectedRecords')!=size or child_manifest.get('recordCount')!=size
                        or child_manifest.get('format')!='companion.business-export.v1'):
                    raise PartitionedExportError('partitioned_child_scope_mismatch')
                child_files=child_manifest.get('files')
                if type(child_files) is not dict or len(child_files)+1!=len(result['files']):raise PartitionedExportError('partitioned_child_attestation_mismatch')
                for child_name,info in child_files.items():
                    if child_name=='business-export.json' or result['files'].get(child_name)!=info:raise PartitionedExportError('partitioned_child_attestation_mismatch')
                loss=boundary.read_document(name+'/mapping-loss.json');losses=loss.get('records')
                if (loss.get('allOriginalJsonRetained') is not True or type(losses) is not list or len(losses)!=size
                        or {entry.get('recordId') for entry in losses if type(entry) is dict}!=set(ids)):
                    raise PartitionedExportError('partitioned_child_mapping_scope_mismatch')
                for entry in losses:
                    key=_exporter._filename(entry['recordId'])
                    if entry.get('json')!='records/'+key+'.json' or entry.get('rdf')!='rdf/'+key+'.ttl':raise PartitionedExportError('partitioned_child_mapping_scope_mismatch')
                descriptor={'part':current_part,'path':name,'start':processed,'recordCount':size,'recordIdsDigest':ids_digest,
                    'globalRecordCount':selected,'originalSourceDenominator':subset.metadata['partition']['originalSourceDenominator'],
                    'metadata':boundary.info(name+'/metadata.json'),'manifest':boundary.info(name+'/business-export.json'),
                    'outputBytes':result['outputBytes'],'fileCount':result['fileCount'],'attempts':attempts}
                db.execute('INSERT INTO parts VALUES(?,?,?,?)',(current_part,processed,size,_raw(descriptor).decode()))
                db.execute('UPDATE records SET part=? WHERE position>=? AND position<?',(current_part,processed,processed+size))
                processed+=size;limit=min(limit,size);db.commit();progress('PART_EXPORTED')
            if db.execute('SELECT count(*) FROM records WHERE part IS NULL').fetchone()[0] or db.execute('SELECT coalesce(sum(count),0) FROM parts').fetchone()[0]!=selected:
                raise PartitionedExportError('partitioned_union_mismatch')
            boundary.freeze_catalog()
            # Verify the actual exported JSON union and canonical payload
            # bytes against the original reader stream, not only spool counts.
            component="union_verification";current_size=0
            exported_ids=hashlib.sha256();exported_payloads=hashlib.sha256();exported_count=0
            for identity,key,index in db.execute('SELECT id,key,part FROM records ORDER BY position'):
                checkpoint();raw=boundary.read_record('business/'+_part(index)+'/records/'+key+'.json')
                record=_store._semantics.loads(raw)
                if record.get('id')!=identity or _exporter._filename(identity)!=key:raise PartitionedExportError('partitioned_union_mismatch')
                encoded=identity.encode();exported_ids.update(len(encoded).to_bytes(8,'big'));exported_ids.update(encoded)
                exported_payloads.update(len(raw).to_bytes(8,'big'));exported_payloads.update(raw);exported_count+=1
            if (exported_count!=selected or exported_ids.digest()!=inventory.digest() or exported_payloads.digest()!=payload_inventory.digest()):
                raise PartitionedExportError('partitioned_union_mismatch')
            # Trusted deterministic global lookup: every endpoint resolves even
            # when the referenced concept is in another bounded business part.
            component='global_lookup'
            for bucket,page in db.execute('SELECT bucket,page FROM records GROUP BY bucket,page ORDER BY bucket,page'):
                rows=db.execute('SELECT id,key,name,part FROM records WHERE bucket=? AND page=? ORDER BY key',(bucket,page)).fetchall()
                if len(rows)>LOOKUP_ROWS:raise PartitionedExportError('partitioned_lookup_budget')
                for lang in LANGUAGES:
                    body='<p><a href="../../'+lang+'/index.html">'+_exporter._e(TITLE[lang])+'</a></p><ol>'
                    for identity,key,name,index in rows:
                        body+='<li id="r-'+key+'"><a href="../../business/'+_part(index)+'/'+lang+'/records/'+key+'.html">'+_exporter._e(name)+'</a> <code>'+_exporter._e(identity)+'</code></li>'
                    write('lookup/'+lang+'/'+bucket+'-%06d.html'%page,_document(lang,TITLE[lang],body+'</ol>',2))
            component="root_catalog"
            pages=max(1,(current_part+CATALOG_ROWS-1)//CATALOG_ROWS)
            for lang in LANGUAGES:
                t=_exporter.TEXT[lang]
                for page in range(pages):
                    rows=db.execute('SELECT number,count FROM parts ORDER BY number LIMIT ? OFFSET ?',(CATALOG_ROWS,page*CATALOG_ROWS)).fetchall()
                    body='<p>'+str(processed)+' / '+str(selected)+'; PARTIAL; UNKNOWN</p><p><a href="../source/'+lang+'/index.html">'+_exporter._e(t[6])+'</a> · <a href="../source-rdf/bundle.json">'+_exporter._e(t[6])+' · RDF / PROV / SHACL</a></p><h2>'+_exporter._e(t[0])+'</h2><ol>'
                    for index,amount in rows:body+='<li><a href="../business/'+_part(index)+'/'+lang+'/index.html">'+_part(index)+'</a> '+str(amount)+'</li>'
                    body+='</ol><nav>'
                    if page:body+='<a href="'+('index.html' if page==1 else 'page-%06d.html'%page)+'">'+_exporter._e(t[7])+'</a>'
                    if page+1<pages:body+='<a href="page-%06d.html">'% (page+2)+_exporter._e(t[8])+'</a>'
                    body+='</nav><p><a href="../export-set.json">export-set.json</a></p><pre>'+_exporter._e(_raw(pins).decode())+'</pre>'
                    write(lang+'/'+('index.html' if page==0 else 'page-%06d.html'%(page+1)),_document(lang,TITLE[lang],body,1))
            write('style.css','body{font:1rem system-ui,sans-serif;max-width:72rem;margin:auto;padding:1rem;line-height:1.6;background:#101827;color:#eef4ff}a{color:#9dd7ff}nav{display:flex;flex-wrap:wrap;gap:1rem}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}li{padding:.4rem}')
            write('index.html',_document(language,TITLE[language],'<nav>'+''.join('<a href="'+lang+'/index.html">'+lang+'</a> ' for lang in LANGUAGES)+'</nav>',0))
            part_catalogs=[]
            cursor=db.execute('SELECT descriptor FROM parts ORDER BY number');number=0
            while True:
                rows=cursor.fetchmany(100)
                if not rows:break
                number+=1;name='catalog/parts-%06d.json'%number
                write(name,_raw({'parts':[json.loads(row[0]) for row in rows]}));part_catalogs.append(boundary.info(name))
            # Inventory files are paged. Catalog pages describe payload files;
            # their own hashes are explicitly listed by the small root manifest.
            file_catalogs=[];cursor=db.execute("SELECT path,bytes,sha FROM entries WHERE kind='file' AND role='payload' ORDER BY path");number=0
            while True:
                rows=cursor.fetchmany(FILE_ROWS)
                if not rows:break
                number+=1;name='catalog/files-%06d.json'%number
                write(name,_raw({'files':[{'path':row[0],'bytes':row[1],'sha256':row[2]} for row in rows]}),role='catalog');file_catalogs.append(boundary.info(name))
            manifest={'format':'companion.partitioned-export.v1','pins':pins,'mode':'explicit_partitioned',
                'configuredOutputBytes':configured,'effectiveOutputBytes':budget,'ordinaryPartByteLimit':PART_BYTES,'partRecordLimit':part_records,
                'globalBusinessRecordCount':selected,'processedBusinessRecordCount':processed,'partCount':current_part,
                'globalCanonicalRecordsDigest':payload_inventory.hexdigest(),'globalCanonicalRecordsDigestEncoding':'length-prefixed-canonical-json-source-order-v1',
                'globalRecordIdsDigest':inventory.hexdigest(),'globalRecordIdsDigestEncoding':'length-prefixed-utf8-id-source-order-v1',
                'originalSourceDenominator':metadata.get('coverage',{}).get('sourceCandidates',metadata.get('coverage',{})).get('denominator','UNKNOWN'),
                'source':{'path':'source',**source_metrics,'languages':list(LANGUAGES),'includeMaps':include_maps,'sourceAccess':'not_read'},
                'sourceRdf':{'path':'source-rdf',**source_rdf_metrics,'manifest':boundary.info('source-rdf/bundle.json'),
                    'rawRecords':'knowledge.sqlite records.payload canonical JSON','jsonl':'not_emitted_by_existing_source_bundle',
                    'rdf':'ontology.ttl','lineage':'lineage.ttl','shapes':'shapes.ttl','mappingLoss':'not_emitted_by_existing_source_bundle'},
                'rdfScopes':{'sourceRecordCount':source_bundle['recordCount'],'businessRecordCount':selected,'separateGraphs':True},
                'sourceBudgetPolicy':'remaining_existing_workspace_output_capacity','businessPartBudgetPolicy':'min_1GiB_remaining_existing_capacity',
                'partCatalogs':part_catalogs,'payloadFileCatalogs':file_catalogs,
                'payloadCatalogScope':'all files except catalog/files-*.json and export-set.json; catalog hashes are listed here',
                'languages':list(LANGUAGES),'lookup':'lookup/<language>/<sha256-prefix>-<page>.html#r-<sha256-record-id>',
                'sourceAccess':'not_read','execution':'NOT_OBSERVED','executionAuthorization':'NOT_PROVIDED','approvalScope':'knowledge_statement_only',
                'businessCompleteness':'PARTIAL','wholeBusinessRuleCoverage':'UNKNOWN','shapeValidation':'NOT_RUN','browserVerification':'NOT_RUN',
                'exportedCopiesRemotelyRevocable':False,'accessRevision':revision}
            if processing_ledger is not None:manifest['processingLedger']=processing_ledger
            write('export-set.json',_raw(manifest),role='root_manifest');db.commit();check_budget();component='publication_validation';progress('VALIDATING')
            boundary.verify_catalog(selected,spooled,inventory,pins,checkpoint)
            boundary.validate(checkpoint);checkpoint();progress('READY_TO_PUBLISH')
            if not stable_profile():raise PartitionedExportError('partitioned_privacy_profile_changed')
        # Reader context exit must also pass before publishing the complete set.
        reader=None
        component="publication"
        with pipeline_store._lock(workspace):
            with companion._snapshot_write_lock(workspace):
                checkpoint()
                if pipeline_store._state(workspace).get('currentSnapshot')!=snapshot_id:raise PartitionedExportError('partitioned_source_not_current')
                current=_store.status(workspace,snapshot_id)
                if any(current.get(key)!=value for key,value in pins.items()):raise PartitionedExportError("partitioned_snapshot_changed")
                if not stable_profile():raise PartitionedExportError('partitioned_privacy_profile_changed')
                boundary.verify_catalog(selected,spooled,inventory,pins,checkpoint)
                boundary.validate(checkpoint)
                # The catalog/file walk can be long. Re-observe current source,
                # authority and the exact rendering profile after it completes.
                checkpoint()
                if pipeline_store._state(workspace).get('currentSnapshot')!=snapshot_id:raise PartitionedExportError('partitioned_source_not_current')
                current=_store.status(workspace,snapshot_id)
                if any(current.get(key)!=value for key,value in pins.items()):raise PartitionedExportError('partitioned_snapshot_changed')
                checkpoint()
                if not stable_profile():raise PartitionedExportError('partitioned_privacy_profile_changed')
                _exporter._promote(boundary.bound,output);boundary.bound.verify_published()
        success=True;receipt_status='EXPORTED'
        try:progress('EXPORTED')
        except Exception:receipt_status='READY_TO_PUBLISH_RETAINED'
        return {'status':'exported','mode':'explicit_partitioned','pins':pins,'entrypoint':str(output/language/'index.html'),
            'outputDirectory':str(output),'languages':list(LANGUAGES),'recordCount':selected,'processedRecords':processed,'partCount':current_part,
            'elapsedSeconds':round(time.monotonic()-started,6),'outputBytes':boundary.size(),'fileCount':boundary.count(),'maxOutputBytes':budget,'configuredOutputBytes':configured,
            'sourceComponent':source_metrics,'sourceRdfComponent':source_rdf_metrics,'manifestSha256':boundary.info('export-set.json')['sha256'],'sourceAccess':'not_read','businessCompleteness':'PARTIAL',
            'wholeBusinessRuleCoverage':'UNKNOWN','browserVerification':'NOT_RUN','shapeValidation':'NOT_RUN','progressReceipt':str(job/'progress.json'),'progressReceiptStatus':receipt_status}
    except BaseException as exc:
        code=getattr(exc,'code',None)
        if isinstance(exc,sqlite3.DatabaseError) and boundary is not None and boundary.catalog_mutation_denied:code='partitioned_catalog_changed'
        if code is None and component=='source_rdf' and isinstance(exc,companion.CompanionError):
            code={'Portable export exceeds its byte budget.':'partitioned_source_rdf_budget','Portable export cancelled.':'partitioned_cancelled'}.get(str(exc))
        if code is None and isinstance(exc,pipeline_store.PipelineError):code=str(exc)
        if code is None and type(exc).__name__=='PipelineHtmlError' and str(exc).startswith('html_'):code=str(exc)
        if type(code) is not str or not re.fullmatch('[a-z_]{1,100}',code):code='partitioned_export_failed'
        observed=getattr(exc,'exportProgress',None)
        if component=='source_atlas' and type(observed) is dict:
            allowed={'generatedOutputBytes','generatedFileCount','processedSourceRecords','sourceRecordDenominator','workingSourceSpoolBytes','nextFileBytes'}
            if set(observed)<=allowed and all(type(value) is int and value>=0 or value=='UNKNOWN' for value in observed.values()):
                source_metrics={**observed,'status':'INCOMPLETE'}
        report=progress('BLOCKED',code)
        failure=PartitionedExportError(code,report);failure.progressReceipt=str(job/'progress.json')
        raise failure from None
    finally:
        if boundary is not None:
            if not success:
                try:cleanup=boundary.cleanup()
                except Exception:cleanup={'status':'UNVERIFIED_RETAINED'}
                if failure is not None:
                    failure.report['cleanup']=cleanup
                    try:pipeline_store._atomic(job/'progress.json',_raw(failure.report))
                    except Exception:pass
            boundary.close()
        db.close()
        if path.exists():path.unlink()


POLICY_SET_FORMAT='companion.partitioned-authorized-policy-projection.v1'
POLICY_GLOBAL_RECORDS=5000000
POLICY_GLOBAL_BYTES=8*1024**3
POLICY_CATALOG_ROWS=1000
POLICY_CATALOG_BYTES=8*1024**2
POLICY_SQLITE_HEAP=128*1024**2
_POLICY_WORKER_ACTIVE=False
_POLICY_WORKER_PROGRESS=None
_POLICY_WORKER_CANCEL=None
_POLICY_WORKER_RUNTIME_CHECK=None
POLICY_WORKER_CONTROL_RESERVE=512*1024
POLICY_RUNTIME_FILE_BYTES=8*1024**2
POLICY_RUNTIME_TOTAL_BYTES=32*1024**2
POLICY_EXECUTABLE_BYTES=256*1024**2
_POLICY_RUNTIME_NAMES={
    'scripts':('business_export.py','business_query.py','business_semantics.py','business_store.py','code_ontology_core.py',
        'code_reference.py','companion.py','coverage_contract.py','java_resolution.py','large_project.py','local_llm.py',
        'parse_cache.py','pipeline_access.py','pipeline_acl.py','pipeline_adapters.py','pipeline_delivery.py',
        'pipeline_documentation.py','pipeline_export.py','pipeline_html.py','pipeline_java.py','pipeline_literals.py',
        'pipeline_partitioned.py','pipeline_policy.py','pipeline_shell.py','pipeline_store.py','policy_java_contracts.py',
        'policy_java_flow.py','policy_java_platform.py','policy_semantics.py','privacy_guard.py','source_inventory.py'),
    'references':('ai-data-contract.md','business-semantics.md','business-semantics.schema.json','code-reference.md',
        'code-reference.schema.json','data-boundaries.md','large-project.md','lineage-model.md','local-llm.md','local-mcp.md',
        'local-source-analysis-access.schema.json','model-era-workflow.md','ontology-model.md','pipeline.md',
        'privacy-operations.md','provenance-schema.ttl','schema.ttl','source-relations.md','source-relations.schema.json',
        'v090-workflow.md','validation-shapes.ttl','workspace-setup.md')}


class _PolicyBoundary(_SetBoundary):
    """The existing custody mechanism, with published-root validation support."""
    def __init__(self,output,db):
        self.output=output;self.db=db;self.total_bytes=0;self.total_files=0;self.catalog_mutation_denied=False
        self.bound=_exporter._BoundArtifacts(output,_exporter._safe_parent(output))
        try:
            self.stage=self.bound.create_stage()
            db.execute('CREATE TABLE entries(path TEXT PRIMARY KEY ON CONFLICT ROLLBACK,parent TEXT NOT NULL,depth INTEGER NOT NULL,kind TEXT NOT NULL,identity TEXT NOT NULL,bytes INTEGER NOT NULL,sha TEXT,role TEXT NOT NULL)')
            db.execute('CREATE INDEX entry_parent ON entries(parent,path)')
            db.execute('CREATE INDEX entry_role ON entries(role,path)')
            db.execute('CREATE TABLE expected(path TEXT PRIMARY KEY ON CONFLICT ROLLBACK,root TEXT NOT NULL,bytes INTEGER NOT NULL,sha TEXT NOT NULL,identity TEXT NOT NULL)')
            db.execute('CREATE INDEX expected_root ON expected(root,path)')
        except BaseException:
            self.bound.cleanup();self.bound.close();raise
    def record(self,name,info,kind,*,size=0,sha=None,role='payload'):
        parts=_parts(name);identity=_identity(info,kind=='directory');previous=self.saved(name)
        if previous is not None:
            if previous!=(kind,identity):raise PartitionedExportError('partitioned_artifact_changed')
            return
        self.db.execute('INSERT OR ROLLBACK INTO entries VALUES(?,?,?,?,?,?,?,?)',
            (name,'/'.join(parts[:-1]),len(parts),kind,json.dumps(identity),size,sha,role))
        if kind=='file':self.total_bytes+=size;self.total_files+=1
    def validate_policy(self,checkpoint,scan):
        self.bound.verify_published() if self.bound.published else self.bound.verify_stage()
        for name,kind,encoded,amount,sha in self.db.execute('SELECT path,kind,identity,bytes,sha FROM entries ORDER BY path'):
            checkpoint();parts=_parts(name)
            with self.directory(parts[:-1]) as parent:
                current=(parent/parts[-1]).lstat() if self.bound.windows else os.stat(parts[-1],dir_fd=parent,follow_symlinks=False)
                if _identity(current,kind=='directory')!=tuple(json.loads(encoded)):raise PartitionedExportError('partitioned_artifact_changed')
                if kind=='file':
                    _,size,digest=self._hash_open(parent,parts[-1],checkpoint)
                    if size!=amount or digest!=sha:raise PartitionedExportError('partitioned_artifact_changed')
                    scan(self.read_record(name,max_bytes=_exporter.MAX_PAGE_BYTES).decode('utf-8'))
        for (name,) in self.db.execute("SELECT '' UNION ALL SELECT path FROM entries WHERE kind='directory'"):
            parts=_parts(name) if name else ()
            with self.directory(parts) as parent:
                count=0
                with os.scandir(parent) as entries:
                    for item in entries:
                        count+=1;relative=(name+'/' if name else '')+item.name
                        if self.saved(relative) is None:raise PartitionedExportError('partitioned_artifact_set_changed')
                if count!=self.db.execute('SELECT count(*) FROM entries WHERE parent=?',(name,)).fetchone()[0]:
                    raise PartitionedExportError('partitioned_artifact_set_changed')
        self.bound.verify_published() if self.bound.published else self.bound.verify_stage()


def _run_policy_projection_partitioned(workspace_path,snapshot_id,business_snapshot_id,business_digest,output_dir,
                                         *,partition_size=PART_RECORDS,max_output_bytes=None,cancel=None,expected_profile=None):
    """Explicit complete policy view; ordinary exporters and their caps stay intact.

    No source atlas, source/RDF payload, private binding or extra permission is
    requested. All inventory, routes, edges and file membership live on disk.
    """
    if _store is None or _exporter is None or _guard is None:raise PartitionedExportError('partitioned_dependencies_required')
    if not _POLICY_WORKER_ACTIVE:raise PartitionedExportError('partitioned_dedicated_worker_required')
    heap_probe=sqlite3.connect(':memory:')
    try:
        heap_limit=heap_probe.execute('PRAGMA hard_heap_limit').fetchone()[0]
        temp_modes=[row[0]for row in heap_probe.execute('PRAGMA compile_options')if row[0].startswith('TEMP_STORE=')]
    finally:heap_probe.close()
    if not 0<heap_limit<=POLICY_SQLITE_HEAP or temp_modes not in (['TEMP_STORE=1'],['TEMP_STORE=2'],['TEMP_STORE=3']):
        raise PartitionedExportError('partitioned_runtime_unsupported')
    api=_exporter._policy_projection
    if (api is None or not all(callable(getattr(api,n,None)) for n in ('export_projection_contract','validate_policy_projection_input',
            'policy_projection_record','policy_projection_metadata','policy_projection_diagnostics'))
            or api.export_projection_contract()!=_exporter.POLICY_PROJECTION_CONTRACT):
        raise PartitionedExportError('partitioned_projection_dependencies_required')
    if type(partition_size) is not int or not 1<=partition_size<=PART_RECORDS:raise PartitionedExportError('partitioned_record_budget')
    workspace,config=pipeline_store._config(workspace_path);output=Path(output_dir).absolute()
    if output==workspace or workspace in output.parents:raise PartitionedExportError('partitioned_destination_inside_workspace')
    repository=Path(config['repositoryRoot']).resolve()
    if output==repository or repository in output.parents:raise PartitionedExportError('partitioned_destination_inside_source')
    initial_budget=copy.deepcopy(config['budgets'])
    configured=initial_budget['max_output_bytes'];record_limit=initial_budget['max_records'];seconds=initial_budget['max_run_seconds']
    if (type(configured) is not int or configured<1 or type(record_limit) is not int or record_limit<1
            or type(seconds) not in (int,float) or not 0<seconds<=7200):raise PartitionedExportError('partitioned_trusted_budget_invalid')
    budget=min(configured,POLICY_GLOBAL_BYTES)
    if max_output_bytes is not None:
        if type(max_output_bytes) is not int or not 1<=max_output_bytes<=budget:raise PartitionedExportError('partitioned_total_budget_invalid')
        budget=max_output_bytes
    effective_records=min(record_limit,POLICY_GLOBAL_RECORDS)
    if budget<=POLICY_SQLITE_HEAP+POLICY_WORKER_CONTROL_RESERVE:raise PartitionedExportError('partitioned_total_budget')
    profile_roots=(workspace,Path(config['repositoryRoot']))
    profile=_guard.load_profile(profile_roots,required=True)
    if expected_profile is not None and profile!=expected_profile:raise PartitionedExportError('partitioned_privacy_profile_changed')
    _guard.ensure_public_safe({},profile=profile,require_profile=True)
    started=time.monotonic();deadline=started+seconds
    job_id='pp-'+uuid.uuid4().hex;jobs=pipeline_store._mkdir(workspace,'.export-jobs');job=pipeline_store._mkdir(jobs,job_id)
    path=job/'catalog.sqlite';progress_path=job/'progress.json';pipeline_store._atomic(path,b'')
    catalog_inode=_identity(path.lstat())[:2]
    db=sqlite3.connect(str(path));db.execute('PRAGMA trusted_schema=OFF')
    # Consume the result before releasing the cursor: otherwise some native
    # SQLite builds leave DELETE journaling active on a new empty database.
    journal_mode=db.execute('PRAGMA journal_mode=MEMORY').fetchall()
    if journal_mode!=[('memory',)]:
        db.close();raise PartitionedExportError('partitioned_sqlite_mode_unsupported')
    db.execute('PRAGMA temp_store=MEMORY')
    if db.execute('PRAGMA temp_store').fetchone()[0]!=2:db.close();raise PartitionedExportError('partitioned_sqlite_mode_unsupported')
    db.execute('PRAGMA cache_size=-2048');db.execute('PRAGMA automatic_index=OFF')
    if db.execute('PRAGMA automatic_index').fetchone()[0]!=0:
        db.close();raise PartitionedExportError('partitioned_sqlite_mode_unsupported')
    if not callable(getattr(db,'setconfig',None)) or not callable(getattr(db,'getconfig',None)) or not hasattr(sqlite3,'SQLITE_DBCONFIG_DEFENSIVE'):
        db.close();raise PartitionedExportError('partitioned_runtime_unsupported')
    db.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE,True)
    if db.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE)is not True:
        db.close();raise PartitionedExportError('partitioned_runtime_unsupported')
    page_size=db.execute('PRAGMA page_size').fetchone()[0]
    initial_page_limit=(budget-POLICY_SQLITE_HEAP-POLICY_WORKER_CONTROL_RESERVE)//page_size
    if db.execute('PRAGMA max_page_count=%d'%initial_page_limit).fetchone()[0]>initial_page_limit:
        db.close();raise PartitionedExportError('partitioned_total_budget')
    db.executescript('''
      CREATE TABLE policy_records(position INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,key TEXT UNIQUE NOT NULL,
        chunk INTEGER NOT NULL,line INTEGER NOT NULL,window INTEGER,page INTEGER,bucket TEXT,lookup_page INTEGER);
      CREATE INDEX policy_lookup ON policy_records(bucket,lookup_page,key);
      CREATE TABLE policy_edges(position INTEGER NOT NULL,ordinal INTEGER NOT NULL,pointer TEXT NOT NULL,
        target TEXT NOT NULL,kind TEXT NOT NULL,PRIMARY KEY(position,ordinal));
      CREATE INDEX policy_edge_target ON policy_edges(kind,target);
      CREATE TABLE policy_chunks(number INTEGER PRIMARY KEY,path TEXT UNIQUE NOT NULL,start INTEGER NOT NULL,
        count INTEGER NOT NULL,bytes INTEGER NOT NULL,sha TEXT NOT NULL,window INTEGER);
      CREATE TABLE policy_pages(window INTEGER NOT NULL,page INTEGER NOT NULL,chunk INTEGER NOT NULL,
        first_line INTEGER NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(window,page));
      CREATE TABLE policy_windows(number INTEGER PRIMARY KEY,start INTEGER NOT NULL,count INTEGER NOT NULL,
        reserved INTEGER NOT NULL,bytes INTEGER NOT NULL);
      CREATE TABLE policy_catalogs(kind TEXT NOT NULL,level INTEGER NOT NULL,number INTEGER NOT NULL,
        path TEXT UNIQUE NOT NULL,bytes INTEGER NOT NULL,sha TEXT NOT NULL,rows INTEGER NOT NULL,PRIMARY KEY(kind,level,number));
    ''')
    boundary=None;active=None;scope=ExitStack();success=False;failure=None;permits=None;pins={};selected=None;metadata_hash=None;catalog_trusted=True
    counters={'visitedRecords':0,'projectedRecords':0,'spooledRecords':0,'parityVerifiedRecords':0}
    rendered={lang:0 for lang in LANGUAGES};phase='reader';sealed=False;catalog_allocated=0;edge_count=0;current_window=0;page_limit=0
    sealed_catalog_identity=None
    def safe(value):_guard.ensure_public_safe(value,profile=profile,allow_local_paths=False,require_profile=True)
    def catalog_size():
        nonlocal catalog_allocated
        info=path.lstat()
        if _identity(info)[:2]!=catalog_inode:raise PartitionedExportError('partitioned_catalog_changed')
        if sealed_catalog_identity is not None and _identity(info)!=sealed_catalog_identity:raise PartitionedExportError('partitioned_catalog_changed')
        if not sealed:catalog_allocated=max(catalog_allocated,db.execute('PRAGMA page_count').fetchone()[0]*page_size)
        for name in ('catalog.sqlite-wal','catalog.sqlite-shm','catalog.sqlite-journal'):
            sidecar=job/name
            if sidecar.exists() or sidecar.is_symlink():
                raise PartitionedExportError('partitioned_unexpected_sqlite_sidecar')
        return max(catalog_allocated,info.st_size)+(progress_path.stat().st_size if progress_path.exists() else 0)
    def space(extra=0):
        nonlocal page_limit
        amount=boundary.size() if boundary else 0
        if amount+catalog_size()+POLICY_SQLITE_HEAP+POLICY_WORKER_CONTROL_RESERVE+extra>budget:raise PartitionedExportError('partitioned_total_budget')
        if not sealed:
            available=(budget-amount-POLICY_SQLITE_HEAP-POLICY_WORKER_CONTROL_RESERVE-extra)//page_size
            if available<1:raise PartitionedExportError('partitioned_total_budget')
            requested=min(available,page_limit or available)
            actual=db.execute('PRAGMA max_page_count=%d'%requested).fetchone()[0]
            if actual>requested:raise PartitionedExportError('partitioned_total_budget')
            page_limit=actual
    def checkpoint():
        nonlocal permits
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):raise PartitionedExportError('partitioned_cancelled')
        if _POLICY_WORKER_CANCEL is not None and _POLICY_WORKER_CANCEL():raise PartitionedExportError('partitioned_cancelled')
        if time.monotonic()>deadline:raise PartitionedExportError('partitioned_deadline')
        current=[pipeline_acl.authorize(workspace,action,snapshot_id) for action in ('read_policy','export_html')]
        if any(type(p) is not dict or p.get('decision')!='allow' or type(p.get('revision')) is not int for p in current):
            raise PartitionedExportError('partitioned_access_denied')
        if len({p['revision'] for p in current})!=1 or permits is not None and current!=permits:
            raise PartitionedExportError('partitioned_acl_revision_changed')
        if permits is None:permits=copy.deepcopy(current)
        if boundary is not None:boundary.bound.verify_parent()
        if pipeline_store._config(workspace)[1]['budgets']!=initial_budget:raise PartitionedExportError('partitioned_budget_binding_changed')
        if active is not None:
            active._stable()
            if pins and any(active.metadata.get(k)!=v for k,v in pins.items()):raise PartitionedExportError('partitioned_snapshot_changed')
            if metadata_hash is not None and _sha(_raw(active.metadata))!=metadata_hash:raise PartitionedExportError('partitioned_snapshot_changed')
        elif pins:
            current_metadata=_store.status(workspace,snapshot_id,resource_policy='bounded_memory_v1')
            if any(current_metadata.get(k)!=v for k,v in pins.items()):raise PartitionedExportError('partitioned_snapshot_changed')
        if current!=[pipeline_acl.authorize(workspace,action,snapshot_id) for action in ('read_policy','export_html')]:
            raise PartitionedExportError('partitioned_acl_revision_changed')
        if _guard.load_profile(profile_roots,required=True)!=profile:raise PartitionedExportError('partitioned_privacy_profile_changed')
        space()
        return False
    def report(status,reason=None):
        value={'format':'companion.private-policy-export-progress.v1','status':status,'reason':reason,'phase':phase,
            'selectedRecords':selected if type(selected)is int else 'UNKNOWN',**counters,'renderedRecordsByLocale':rendered.copy(),'referenceOccurrences':edge_count,
            'remainingSelectedRecords':max(0,selected-counters['projectedRecords']) if type(selected) is int else 'UNKNOWN',
            'firstUnprocessedPosition':counters['projectedRecords'],'window':current_window,
            'configuredOutputBytes':configured,'effectiveOutputBytes':budget,'workingCatalogBytes':catalog_size(),
            'outputBytes':boundary.size() if boundary else 0,'fileCount':boundary.count() if boundary else 0,
            'selectionTraversal':'COMPLETE' if status=='EXPORTED' else 'INCOMPLETE','wholeBusinessCompleteness':'UNKNOWN'}
        safe(value);raw=_raw(value)
        if (boundary.size() if boundary else 0)+catalog_size()+POLICY_SQLITE_HEAP+POLICY_WORKER_CONTROL_RESERVE+len(raw)>budget:raise PartitionedExportError('partitioned_total_budget')
        pipeline_store._atomic(progress_path,raw)
        if _POLICY_WORKER_PROGRESS is not None:pipeline_store._atomic(_POLICY_WORKER_PROGRESS,raw)
        return value
    def write(name,value,role='payload'):
        if _POLICY_WORKER_RUNTIME_CHECK is not None:_POLICY_WORKER_RUNTIME_CHECK()
        checkpoint();raw=value.encode('utf-8') if type(value) is str else value
        if type(raw) is not bytes or len(raw)>_exporter.MAX_PAGE_BYTES:raise PartitionedExportError('partitioned_page_budget')
        space(len(raw));safe(name);safe(raw.decode('utf-8'));safe(_sha(raw))
        boundary.write(name,raw,role=role);checkpoint()
        return boundary.info(name)
    def project(row):
        safe(row);api.validate_policy_projection_input(row,kind='record');_exporter._validate_record(row)
        raw=_raw(row)
        if len(raw)>_exporter.MAX_RECORD_BYTES:raise PartitionedExportError('partitioned_record_budget')
        if row.get('contentDigest')!=_sha(_raw({k:v for k,v in row.items() if k!='contentDigest'})):
            raise PartitionedExportError('partitioned_record_digest_mismatch')
        value=api.policy_projection_record(row);safe(value);encoded=_raw(value)
        if len(encoded)>_exporter.MAX_RECORD_BYTES:raise PartitionedExportError('partitioned_record_budget')
        return value,encoded
    def chunk_rows(number):
        row=db.execute('SELECT path,count,bytes,sha FROM policy_chunks WHERE number=?',(number,)).fetchone()
        if row is None:raise PartitionedExportError('partitioned_chunk_missing')
        raw=boundary.read_record(row[0],max_bytes=_exporter.POLICY_CHUNK_BYTES)
        if len(raw)!=row[2] or _sha(raw)!=row[3] or not raw.endswith(b'\n'):raise PartitionedExportError('partitioned_chunk_changed')
        lines=raw.splitlines()
        if len(lines)!=row[1] or len(lines)>_exporter.POLICY_CHUNK_RECORDS:raise PartitionedExportError('partitioned_chunk_denominator')
        return lines
    def article(line):
        row=_exporter._strict_projection_json(line)
        return '<article id="record-'+_exporter._filename(row['id'])+'"><h2>'+_exporter._e(row.get('name','UNKNOWN'))+'</h2><pre class="record-json">'+_exporter._e(line.decode('utf-8'))+'</pre></article>'
    def document(lang,body,*,depth=2,previous=None,next_page=None):
        prefix='../'*(depth+1)
        body='<p>'+_exporter._e(_exporter.POLICY_PROJECTION_TEXT[lang])+'</p><p><a href="'+prefix+'policy-projection-set.json">JSON</a> · <a href="'+prefix+'lookup/'+lang+'/index.html">ID</a></p>'+body+'<nav>'
        if previous:body+='<a href="'+previous+'">'+_exporter._e(_exporter.TEXT[lang][7])+'</a> '
        if next_page:body+='<a href="'+next_page+'">'+_exporter._e(_exporter.TEXT[lang][8])+'</a>'
        return _exporter._page(lang,_exporter.TEXT[lang][0],body+'</nav>',depth=depth)
    def route(window,page,lang,*,lookup=False):
        return ('../../' if lookup else '../../')+_part(window)+'/'+lang+'/page-%08d.html'%page
    try:
        checkpoint();active=scope.enter_context(_store.open_reader(workspace,snapshot_id,business_snapshot_id,business_digest,resource_policy='bounded_memory_v1'))
        selected=active.metadata.get('recordCount')
        if type(selected) is not int or not 0<=selected<=effective_records:raise PartitionedExportError('partitioned_inventory_budget')
        pins={key:active.metadata[key] for key in _exporter.PIN_KEYS};metadata_hash=_sha(_raw(active.metadata))
        safe(active.metadata);api.validate_policy_projection_input(active.metadata,kind='metadata')
        data={'metadata':api.policy_projection_metadata(active.metadata)};data['coverage']=copy.deepcopy(data['metadata']['coverage'])
        if 'currentReviewDiagnostics' in active.metadata:data['currentReviewDiagnostics']=api.policy_projection_diagnostics(active.metadata['currentReviewDiagnostics'])
        safe(data);data_raw=_raw(data)
        digest=hashlib.sha256(b'companion.authorized-policy-projection.v1\x00');digest.update(len(data_raw).to_bytes(8,'big'));digest.update(data_raw)
        boundary=_PolicyBoundary(output,db);phase='spool';pending=[];pending_bytes=0;chunk_number=0
        report('STAGING')
        def flush():
            nonlocal pending,pending_bytes,chunk_number
            if not pending:return
            chunk_number+=1;name='records/chunk-%08d.jsonl'%chunk_number;raw=b''.join(line+b'\n' for line in pending)
            info=write(name,raw);start=counters['projectedRecords']-len(pending)
            db.execute('INSERT OR ROLLBACK INTO policy_chunks VALUES(?,?,?,?,?,?,NULL)',(chunk_number,name,start,len(pending),len(raw),info['sha256']))
            counters['spooledRecords']+=len(pending);db.commit();pending=[];pending_bytes=0;space()
        for row in active.iter_records(page_size=100):
            checkpoint();counters['visitedRecords']+=1;value,raw=project(row);position=counters['projectedRecords']
            if position>=selected:raise PartitionedExportError('partitioned_record_denominator')
            if pending and (len(pending)>=min(_exporter.POLICY_CHUNK_RECORDS,partition_size) or pending_bytes+len(raw)+1>_exporter.POLICY_CHUNK_BYTES):flush()
            if len(raw)+1>_exporter.POLICY_CHUNK_BYTES:raise PartitionedExportError('partitioned_record_budget')
            try:db.execute('INSERT OR ROLLBACK INTO policy_records VALUES(?,?,?,?,?,NULL,NULL,NULL,NULL)',(position,value['id'],_exporter._filename(value['id']),chunk_number+1,len(pending)))
            except sqlite3.IntegrityError:raise PartitionedExportError('partitioned_duplicate_identity') from None
            for ordinal,(pointer,target,kind) in enumerate(_exporter._policy_reference_occurrences(value)):
                db.execute('INSERT OR ROLLBACK INTO policy_edges VALUES(?,?,?,?,?)',(position,ordinal,pointer,target,kind));edge_count+=1
            pending.append(raw);pending_bytes+=len(raw)+1;counters['projectedRecords']+=1
            digest.update(len(raw).to_bytes(8,'big'));digest.update(raw);space()
            if counters['projectedRecords']%10000==0:db.commit();report('STAGING')
        flush()
        if any(counters[k]!=selected for k in ('visitedRecords','projectedRecords','spooledRecords')):raise PartitionedExportError('partitioned_record_denominator')
        if db.execute("SELECT 1 FROM policy_edges e LEFT JOIN policy_records r ON r.id=e.target WHERE e.kind='business' AND r.id IS NULL LIMIT 1").fetchone():
            raise PartitionedExportError('partitioned_dangling_reference')
        # All intended global traversals use persistent indexes; no temporary
        # sorter/automatic index is silently accepted as an uncharged spool.
        for sql in ('SELECT position,id FROM policy_records ORDER BY position','SELECT key,id FROM policy_records ORDER BY key',
                    'SELECT position,ordinal,target FROM policy_edges ORDER BY position,ordinal'):
            if any('TEMP B-TREE' in row[3].upper() or 'AUTOMATIC' in row[3].upper() for row in db.execute('EXPLAIN QUERY PLAN '+sql)):
                raise PartitionedExportError('partitioned_unbounded_query_plan')
        phase='layout';wrapper=max(len(document(lang,'',previous='page-00000000.html',next_page='page-00000000.html').encode()) for lang in LANGUAGES)
        current_window=0;window_count=0;window_reserved=0;window_start=0;local_page=0
        for number,start,count,amount in db.execute('SELECT number,start,count,bytes FROM policy_chunks ORDER BY number'):
            checkpoint();lines=chunk_rows(number);ranges=[];first=0;page_amount=wrapper
            for offset,line in enumerate(lines):
                cost=len(article(line).encode())
                if cost+wrapper>_exporter.MAX_PAGE_BYTES:raise PartitionedExportError('partitioned_record_page_budget')
                if offset>first and page_amount+cost>_exporter.MAX_PAGE_BYTES:ranges.append((first,offset-first,page_amount));first=offset;page_amount=wrapper
                page_amount+=cost
            ranges.append((first,len(lines)-first,page_amount));reserved=amount+len(LANGUAGES)*sum(row[2] for row in ranges)
            if reserved>PART_BYTES:raise PartitionedExportError('partitioned_window_bytes')
            if not current_window or window_count+count>partition_size or window_reserved+reserved>PART_BYTES:
                current_window+=1;window_count=0;window_reserved=0;window_start=start;local_page=0
                db.execute('INSERT OR ROLLBACK INTO policy_windows VALUES(?,?,?,?,?)',(current_window,start,0,0,0))
            window_count+=count;window_reserved+=reserved
            db.execute('UPDATE OR ROLLBACK policy_windows SET count=?,reserved=?,bytes=bytes+? WHERE number=?',(window_count,window_reserved,amount,current_window))
            db.execute('UPDATE OR ROLLBACK policy_chunks SET window=? WHERE number=?',(current_window,number))
            for first,count,_ in ranges:
                local_page+=1;db.execute('INSERT OR ROLLBACK INTO policy_pages VALUES(?,?,?,?,?)',(current_window,local_page,number,first,count))
                db.execute('UPDATE OR ROLLBACK policy_records SET window=?,page=? WHERE position>=? AND position<?',(current_window,local_page,start+first,start+first+count))
        bucket=None;ordinal=0
        for position,key in db.execute('SELECT position,key FROM policy_records ORDER BY key'):
            current=key[:2]
            if current!=bucket:bucket=current;ordinal=0
            db.execute('UPDATE OR ROLLBACK policy_records SET bucket=?,lookup_page=? WHERE position=?',(bucket,ordinal//LOOKUP_ROWS+1,position));ordinal+=1
        db.commit();space();phase='render'
        write('style.css','body{font:1rem system-ui;max-width:75rem;margin:auto;padding:1rem;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere}nav{display:flex;gap:1rem;flex-wrap:wrap}.skip{position:absolute;top:-4rem}.skip:focus{top:0}')
        for window,page,chunk,first,count in db.execute('SELECT window,page,chunk,first_line,count FROM policy_pages ORDER BY window,page'):
            checkpoint();lines=chunk_rows(chunk);body=''.join(article(line) for line in lines[first:first+count])
            previous='page-%08d.html'%(page-1) if page>1 else None
            next_page='page-%08d.html'%(page+1) if db.execute('SELECT 1 FROM policy_pages WHERE window=? AND page=?',(window,page+1)).fetchone() else None
            for lang in LANGUAGES:
                info=write('parts/'+_part(window)+'/'+lang+'/page-%08d.html'%page,document(lang,body,previous=previous,next_page=next_page))
                db.execute('UPDATE OR ROLLBACK policy_windows SET bytes=bytes+? WHERE number=?',(info['bytes'],window));rendered[lang]+=count
        if db.execute('SELECT 1 FROM policy_windows WHERE bytes>reserved OR bytes>? OR count>?',(PART_BYTES,partition_size)).fetchone():
            raise PartitionedExportError('partitioned_window_bytes')
        # Native-file ID lookup: paged by existing hashed bucket/ordinal pattern.
        for bucket,page in db.execute('SELECT bucket,lookup_page FROM policy_records GROUP BY bucket,lookup_page ORDER BY bucket,lookup_page'):
            rows=db.execute('SELECT id,key,window,page FROM policy_records WHERE bucket=? AND lookup_page=? ORDER BY key',(bucket,page)).fetchall()
            if len(rows)>LOOKUP_ROWS:raise PartitionedExportError('partitioned_lookup_budget')
            for lang in LANGUAGES:
                body='<ol>'+''.join('<li id="r-'+key+'"><a href="../../parts/'+_part(window)+'/'+lang+'/page-%08d.html#record-'%target_page+key+'">'+_exporter._e(identity)+'</a></li>' for identity,key,window,target_page in rows)+'</ol><nav>'
                if page>1:body+='<a href="'+bucket+'-%06d.html">'% (page-1)+_exporter._e(_exporter.TEXT[lang][7])+'</a> '
                if db.execute('SELECT 1 FROM policy_records WHERE bucket=? AND lookup_page=? LIMIT 1',(bucket,page+1)).fetchone():body+='<a href="'+bucket+'-%06d.html">'%(page+1)+_exporter._e(_exporter.TEXT[lang][8])+'</a>'
                write('lookup/'+lang+'/'+bucket+'-%06d.html'%page,_exporter._page(lang,TITLE[lang],body+'</nav>',depth=1))
        for lang in LANGUAGES:
            body='<nav>'+''.join('<a href="'+bucket+'-000001.html">'+bucket+'</a> ' for (bucket,) in db.execute('SELECT DISTINCT bucket FROM policy_records ORDER BY bucket'))+'</nav>'
            write('lookup/'+lang+'/index.html',_exporter._page(lang,TITLE[lang],body,depth=1))
            body='<p>'+_exporter._e(_exporter.POLICY_PROJECTION_TEXT[lang])+'</p><a href="../policy-projection-set.json">JSON</a> <a href="../lookup/'+lang+'/index.html">ID</a>'
            if selected:body+=' <a href="../parts/'+_part(1)+'/'+lang+'/page-00000001.html">'+_exporter._e(_exporter.TEXT[lang][1])+'</a>'
            write(lang+'/index.html',_exporter._page(lang,TITLE[lang],body))
        write('index.html',_exporter._page('en',TITLE['en'],'<nav>'+''.join('<a href="'+lang+'/index.html">'+lang+'</a> ' for lang in LANGUAGES)+'</nav>',depth=-1))
        phase='parity';position=0
        def stored_records():
            for (number,) in db.execute('SELECT number FROM policy_chunks ORDER BY number'):
                for ordinal,line in enumerate(chunk_rows(number)):yield number,ordinal,line
        stored=iter(stored_records())
        for row in active.iter_records(page_size=100):
            checkpoint();value,raw=project(row)
            stored_row=next(stored,None)
            if stored_row is None or stored_row[2]!=raw:raise PartitionedExportError('partitioned_projection_roundtrip_mismatch')
            original=db.execute('SELECT id,key,window,page,chunk,line FROM policy_records WHERE position=?',(position,)).fetchone()
            if original is None or original[0]!=value['id'] or original[1]!=_exporter._filename(value['id']) or original[4:]!=stored_row[:2]:
                raise PartitionedExportError('partitioned_catalog_changed')
            page_membership=db.execute('SELECT first_line,count FROM policy_pages WHERE window=? AND page=? AND chunk=?',(original[2],original[3],original[4])).fetchone()
            if page_membership is None or not page_membership[0]<=original[5]<sum(page_membership):raise PartitionedExportError('partitioned_route_changed')
            expected=iter(db.execute('SELECT pointer,target,kind FROM policy_edges WHERE position=? ORDER BY ordinal',(position,)))
            for edge in _exporter._policy_reference_occurrences(value):
                if next(expected,None)!=edge:raise PartitionedExportError('partitioned_reference_occurrence_mismatch')
            if next(expected,None) is not None:raise PartitionedExportError('partitioned_reference_occurrence_mismatch')
            position+=1;counters['parityVerifiedRecords']=position
        if position!=selected or next(stored,None) is not None:raise PartitionedExportError('partitioned_record_denominator')
        if db.execute('SELECT count(*) FROM policy_records').fetchone()[0]!=selected or db.execute('SELECT count(*) FROM policy_edges').fetchone()[0]!=edge_count:
            raise PartitionedExportError('partitioned_catalog_changed')
        if db.execute('SELECT coalesce(sum(count),0) FROM policy_pages').fetchone()[0]!=selected:
            raise PartitionedExportError('partitioned_route_changed')
        if db.execute('SELECT 1 FROM policy_edges e LEFT JOIN policy_records r ON r.position=e.position WHERE r.position IS NULL LIMIT 1').fetchone():
            raise PartitionedExportError('partitioned_reference_occurrence_mismatch')
        if any(count!=selected for count in rendered.values()):raise PartitionedExportError('partitioned_render_denominator')
        selector_tables=('policy_records','policy_edges','policy_chunks','policy_pages','policy_windows')
        def selector_digest():
            result=hashlib.sha256()
            for table,order in zip(selector_tables,('position','position,ordinal','number','window,page','number')):
                result.update(table.encode())
                for row in db.execute('SELECT * FROM '+table+' ORDER BY '+order):result.update(_raw(list(row)))
            return result.digest()
        selector_seal=selector_digest()
        phase='catalogs'
        def catalog(kind,rows):
            level=0;number=0;batch=[];batch_bytes=0
            def put(items,level,number):
                name='catalog/'+kind+'-%02d-%08d.json'%(level,number);info=write(name,_raw({'rows':items}),role='catalog')
                db.execute('INSERT OR ROLLBACK INTO policy_catalogs VALUES(?,?,?,?,?,?,?)',(kind,level,number,name,info['bytes'],info['sha256'],len(items)))
            for row in rows:
                cost=len(_raw(row))+1
                if cost+32>POLICY_CATALOG_BYTES:raise PartitionedExportError('partitioned_catalog_row_budget')
                if batch and (len(batch)>=POLICY_CATALOG_ROWS or batch_bytes+cost+32>POLICY_CATALOG_BYTES):number+=1;put(batch,level,number);batch=[];batch_bytes=0
                batch.append(row);batch_bytes+=cost
            if batch or number==0:number+=1;put(batch,level,number)
            while number>1:
                level+=1
                if level>3:raise PartitionedExportError('partitioned_catalog_depth')
                previous=number;number=0;batch=[]
                for path,amount,sha,rows_count in db.execute('SELECT path,bytes,sha,rows FROM policy_catalogs WHERE kind=? AND level=? ORDER BY number',(kind,level-1)):
                    batch.append({'path':path,'bytes':amount,'sha256':sha,'level':level-1,'rowCount':rows_count})
                    if len(batch)>=POLICY_CATALOG_ROWS:number+=1;put(batch,level,number);batch=[]
                if batch:number+=1;put(batch,level,number)
            row=db.execute('SELECT path,bytes,sha,rows FROM policy_catalogs WHERE kind=? AND level=? AND number=1',(kind,level)).fetchone()
            return {'path':row[0],'bytes':row[1],'sha256':row[2],'level':level,'rowCount':row[3]}
        roots={}
        roots['chunks']=catalog('chunks',({'number':n,'path':path,'globalStart':start,'recordCount':count,'bytes':amount,'sha256':sha,'window':window}
            for n,path,start,count,amount,sha,window in db.execute('SELECT * FROM policy_chunks ORDER BY number')))
        roots['routes']=catalog('routes',({'recordId':identity,'position':position,'window':window,'page':page,'anchor':'record-'+key}
            for position,identity,key,window,page in db.execute('SELECT position,id,key,window,page FROM policy_records ORDER BY position')))
        roots['windows']=catalog('windows',({'number':n,'globalStart':start,'recordCount':count,'bytes':amount}
            for n,start,count,amount in db.execute('SELECT number,start,count,bytes FROM policy_windows ORDER BY number')))
        roots['lookup']=catalog('lookup',({'bucket':bucket,'page':page,'recordCount':count}
            for bucket,page,count in db.execute('SELECT bucket,lookup_page,count(*) FROM policy_records GROUP BY bucket,lookup_page ORDER BY bucket,lookup_page')))
        roots['files']=catalog('files',({'path':path,'bytes':amount,'sha256':sha}
            for path,amount,sha in db.execute("SELECT path,bytes,sha FROM entries WHERE kind='file' AND role='payload' ORDER BY path")))
        manifest={'format':POLICY_SET_FORMAT,'projection':'policy_projection','projectionContract':api.export_projection_contract(),**data,
            'selectedRecords':selected,'processedRecords':selected,'recordCount':selected,'chunkCount':chunk_number,'windowCount':current_window,
            'htmlPageCountByLanguage':{lang:db.execute('SELECT count(*) FROM policy_pages').fetchone()[0] for lang in LANGUAGES},
            'catalogRoots':roots,'recordsOrder':'verified_reader_order','projectionDigest':digest.hexdigest(),
            'projectionDigestScope':'framed_metadata_coverage_diagnostics_and_ordered_record_json_v1',
            'budgetBinding':{'contract':'trusted_workspace_capacity_v1','configuredMaxRecords':record_limit,'configuredMaxOutputBytes':configured,
                'effectiveMaxRecords':effective_records,'effectiveMaxOutputBytes':budget,'windowMaxRecords':partition_size,'windowMaxBytes':PART_BYTES,
                'maxRecordBytes':_exporter.MAX_RECORD_BYTES,'maxPageBytes':_exporter.MAX_PAGE_BYTES,'maxChunkRecords':_exporter.POLICY_CHUNK_RECORDS,
                'maxBusinessManifestBytes':32*1024**2,
                'maxChunkBytes':_exporter.POLICY_CHUNK_BYTES,'deadlineSeconds':seconds},
            'permissionsChecked':['read_policy','export_html'],'accessRevision':permits[0]['revision'],'selectionTraversal':'COMPLETE',
            'sourceEvidenceDetails':'WITHHELD','originalJsonRetained':False,'fullSourceLossless':False,'offlineIssuerAuthenticity':'NOT_ESTABLISHED',
            'publicationAttestation':'NOT_PROVIDED','runtimeStatus':'NOT_OBSERVED','executionAuthorization':'NOT_PROVIDED','globalCompleteness':'UNKNOWN',
            'exportedCopiesRemotelyRevocable':False,'approvalScope':'knowledge_statement_only','exactnessClaim':'lossless for authorized policy projection',
            'browserVerification':'NOT_RUN','shapeValidation':'NOT_RUN'}
        manifest['budgetBinding'].update(sqliteNativeAllocationLimitBytes=POLICY_SQLITE_HEAP,workerIsolation='dedicated_process')
        write('policy-projection-set.json',_raw(manifest),role='root_manifest');db.commit();space()
        # Read/compare all catalog bytes to selector truth, then freeze every
        # selector/artifact table. Mutation after this point is never re-sealed.
        catalog_seal=hashlib.sha256()
        for kind,level,number,name,amount,sha,rows in db.execute('SELECT * FROM policy_catalogs ORDER BY kind,level,number'):
            raw=boundary.read_record(name,max_bytes=POLICY_CATALOG_BYTES)
            if _sha(raw)!=sha or len(raw)!=amount or len(_exporter._strict_projection_json(raw)['rows'])!=rows:raise PartitionedExportError('partitioned_catalog_changed')
            catalog_seal.update(_raw([kind,level,number,name,amount,sha,rows]))
        sealed_digest=catalog_seal.digest()
        if selector_digest()!=selector_seal:raise PartitionedExportError('partitioned_catalog_changed')
        def sql_authorizer(action,first,second,database,trigger):
            if (action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE) or action in
                    tuple(getattr(sqlite3,name) for name in ('SQLITE_CREATE_INDEX','SQLITE_CREATE_TABLE','SQLITE_CREATE_TRIGGER','SQLITE_CREATE_VIEW',
                        'SQLITE_DROP_INDEX','SQLITE_DROP_TABLE','SQLITE_DROP_TRIGGER','SQLITE_DROP_VIEW','SQLITE_ALTER_TABLE','SQLITE_ATTACH','SQLITE_DETACH','SQLITE_PRAGMA'))):
                boundary.catalog_mutation_denied=True;return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.commit();sealed_catalog_identity=_identity(path.lstat());sealed=True;db.set_authorizer(sql_authorizer);phase='validation'
        def validate():
            if _POLICY_WORKER_RUNTIME_CHECK is not None:_POLICY_WORKER_RUNTIME_CHECK()
            checkpoint();current=hashlib.sha256()
            for row in db.execute('SELECT * FROM policy_catalogs ORDER BY kind,level,number'):current.update(_raw(list(row)))
            if current.digest()!=sealed_digest:raise PartitionedExportError('partitioned_catalog_changed')
            if selector_digest()!=selector_seal:raise PartitionedExportError('partitioned_catalog_changed')
            if _exporter._strict_projection_json(boundary.read_record('policy-projection-set.json',max_bytes=_exporter.MAX_PAGE_BYTES))!=manifest:
                raise PartitionedExportError('partitioned_manifest_changed')
            boundary.validate_policy(checkpoint,safe);checkpoint()
        with pipeline_store._lock(workspace):
            with companion._snapshot_write_lock(workspace):
                validate();scope.close();active=None;checkpoint()
                with _store.open_reader(workspace,snapshot_id,business_snapshot_id,business_digest,resource_policy='bounded_memory_v1') as current:
                    active=current;validate()
                active=None;checkpoint();_exporter._promote(boundary.bound,output);boundary.bound.verify_published()
                with _store.open_reader(workspace,snapshot_id,business_snapshot_id,business_digest,resource_policy='bounded_memory_v1') as current:
                    active=current;validate()
                active=None;checkpoint();boundary.bound.verify_published()
                result={'status':'exported','format':POLICY_SET_FORMAT,'projection':'policy_projection','entrypoint':'index.html',
                    'manifest':'policy-projection-set.json','recordCount':selected,'selectedRecords':selected,'processedRecords':selected,
                    'windowCount':current_window,'chunkCount':chunk_number,'projectionDigest':digest.hexdigest(),'catalogRoots':roots,
                    'outputBytes':boundary.size(),'fileCount':boundary.count(),'effectiveOutputBytes':budget,
                    'browserVerification':'NOT_RUN','shapeValidation':'NOT_RUN','offlineIssuerAuthenticity':'NOT_ESTABLISHED'}
                safe(result);checkpoint()
        report('EXPORTED');checkpoint();success=True
        return result
    except BaseException as exc:
        code=getattr(exc,'code',None)
        if selected is None and type(getattr(exc,'selected',None))is int:selected=exc.selected
        if code is None and isinstance(exc,ValueError)and str(exc)=='policy_projection_producer_unclassified':
            code='policy_projection_producer_unclassified'
        if code is None and isinstance(exc,pipeline_store.PipelineError) and str(exc) in (
                'reader_resource_policy_invalid','reader_resource_policy_heap_unavailable','reader_resource_policy_unsupported'):
            code=str(exc)
        if isinstance(exc,(sqlite3.DatabaseError,MemoryError)):catalog_trusted=False
        if boundary is not None and catalog_trusted:
            try:
                count,amount=db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM entries WHERE kind='file'").fetchone()
                if count!=boundary.count()or amount!=boundary.size():catalog_trusted=False
            except Exception:catalog_trusted=False
        if isinstance(exc,sqlite3.DatabaseError) and boundary is not None and boundary.catalog_mutation_denied:code='partitioned_catalog_changed'
        if type(code) is not str or not re.fullmatch('[a-z_]{1,100}',code):code='partitioned_policy_export_failed'
        # A full budget must still yield a bounded in-memory report. Never mask
        # its original frontier merely because writing progress is impossible.
        value={'status':'BLOCKED','reason':code,'phase':phase,'selectedRecords':selected if type(selected)is int else 'UNKNOWN',**counters,
            'renderedRecordsByLocale':rendered.copy(),'referenceOccurrences':edge_count,
            'remainingSelectedRecords':max(0,selected-counters['projectedRecords']) if type(selected) is int else 'UNKNOWN',
            'firstUnprocessedPosition':counters['projectedRecords'],'selectionTraversal':'INCOMPLETE','wholeBusinessCompleteness':'UNKNOWN',
            'configuredOutputBytes':configured,'effectiveOutputBytes':budget,'outputBytes':boundary.size() if boundary else 0}
        failure=PartitionedExportError(code,value)
        if type(getattr(exc,'report',None))is dict:
            for name in ('storageRequirement','alternatives'):
                if name in exc.report:failure.report[name]=exc.report[name]
        try:report('BLOCKED',code)
        except Exception:pass
        raise failure from None
    finally:
        try:scope.close()
        except Exception:pass
        if boundary is not None:
            if not success:
                if not catalog_trusted:cleanup={'status':'UNVERIFIED_RETAINED','knownCreatedFiles':boundary.count()}
                else:
                    try:cleanup=boundary.cleanup()
                    except Exception:cleanup={'status':'UNVERIFIED_RETAINED'}
                if failure is not None:failure.report['cleanup']=cleanup
            boundary.close()
        db.close()
        # Fixed trusted job file only, with its original identity. No wildcard
        # unlink and no unknown/replaced entry cleanup.
        try:
            if _identity(path.lstat())[:2]==catalog_inode:path.unlink()
        except (OSError,ValueError):pass


# Stdlib-only, isolated-process bootstrap. The request supplies data and expected
# hashes, never executable code. No product import occurs before verification.
_POLICY_WORKER_BOOTSTRAP=r'''
import hashlib,importlib.abc,importlib.util,json,os,pathlib,sqlite3,stat,sys,time
def pairs(items):
 d={}
 for k,v in items:
  if k in d:raise ValueError('duplicate_request_key')
  d[k]=v
 return d
request=None
try:
 raw=sys.stdin.buffer.readline(65537)
 if len(raw)>65536 or not raw.endswith(b'\n'):raise ValueError('worker_request_budget')
 request=json.loads(raw,object_pairs_hook=pairs)
 fields={'format','nonce','bundle','files','executableSha256','workspace','snapshotId','businessSnapshotId','businessDigest','output','partitionSize','maxOutputBytes','profileBinding','principal','control','timeoutSeconds'}
 if type(request)is not dict or set(request)!=fields or request['format']!='companion.private-policy-worker-request.v1':raise ValueError('worker_request_invalid')
 if type(request['nonce'])is not str or len(request['nonce'])!=32:raise ValueError('worker_request_invalid')
 if type(request['timeoutSeconds'])not in (int,float)or not 0<request['timeoutSeconds']<=7200:raise ValueError('worker_request_invalid')
 deadline=time.monotonic()+request['timeoutSeconds']
 probe=sqlite3.connect(':memory:');probe.execute('PRAGMA hard_heap_limit=134217728').fetchall()
 limit=probe.execute('PRAGMA hard_heap_limit').fetchone()[0]
 if not 0<limit<=134217728:raise ValueError('partitioned_runtime_unsupported')
 temp_modes=[row[0]for row in probe.execute('PRAGMA compile_options')if row[0].startswith('TEMP_STORE=')]
 if temp_modes not in (['TEMP_STORE=1'],['TEMP_STORE=2'],['TEMP_STORE=3']):raise ValueError('partitioned_runtime_unsupported')
 if not callable(getattr(probe,'setconfig',None)) or not hasattr(sqlite3,'SQLITE_DBCONFIG_DEFENSIVE'):raise ValueError('partitioned_runtime_unsupported')
 probe.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE,True)
 if probe.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE)is not True:raise ValueError('partitioned_runtime_unsupported')
 source_id=probe.execute('SELECT sqlite_source_id()').fetchone()[0];probe.close()
 exe=pathlib.Path(sys.executable).resolve()
 def identity(info):return(info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
 def same_open_file(path_info,opened):
  if getattr(opened,'st_file_attributes',0)&0x400:return False
  if os.name!='nt':return identity(path_info)==identity(opened)
  # Win32 path stat and CRT fstat have different executable mode/ctime
  # meanings. Link providers by file identity, then monitor each separately.
  def shared(info):return(info.st_dev,info.st_ino,stat.S_IFMT(info.st_mode),info.st_nlink,info.st_size,info.st_mtime_ns)
  if shared(path_info)!=shared(opened):return False
  birth=[getattr(info,'st_birthtime_ns',None)for info in (path_info,opened)]
  return None in birth or birth[0]==birth[1]
 def sha(path,maximum,keep=False):
  before=path.lstat()
  if not stat.S_ISREG(before.st_mode)or before.st_nlink!=1 or before.st_size>maximum or getattr(before,'st_file_attributes',0)&0x400:raise ValueError('worker_runtime_changed')
  fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0));h=hashlib.sha256();amount=0;blocks=[]
  try:
   opened=os.fstat(fd)
   if not same_open_file(before,opened):raise ValueError('worker_runtime_changed')
   while True:
    if time.monotonic()>deadline:raise ValueError('partitioned_deadline')
    block=os.read(fd,min(1048576,maximum-amount+1))
    if not block:break
    amount+=len(block)
    if amount>maximum:raise ValueError('worker_runtime_changed')
    h.update(block)
    if keep:blocks.append(block)
   after_fd=os.fstat(fd);after_path=path.lstat()
   if (identity(after_fd)!=identity(opened)or identity(after_path)!=identity(before)
       or getattr(after_fd,'st_file_attributes',0)&0x400 or getattr(after_path,'st_file_attributes',0)&0x400):raise ValueError('worker_runtime_changed')
  finally:os.close(fd)
  return h.hexdigest(),amount,b''.join(blocks)if keep else None,identity(before)
 if sha(exe,268435456)[0]!=request['executableSha256']:raise ValueError('worker_runtime_changed')
 root=pathlib.Path(request['bundle'])
 if not root.is_absolute()or root.resolve()!=root:raise ValueError('worker_runtime_changed')
 names=set();namespace=__POLICY_NAMESPACE__
 for directory,expected in namespace.items():
  parent=root/directory;di=parent.lstat()
  if not stat.S_ISDIR(di.st_mode)or stat.S_ISLNK(di.st_mode)or getattr(di,'st_file_attributes',0)&0x400:raise ValueError('worker_runtime_changed')
  seen=set()
  for path in parent.iterdir():
   if path.name not in expected or path.name in seen:raise ValueError('worker_runtime_changed')
   seen.add(path.name);info=path.lstat()
   if not stat.S_ISREG(info.st_mode)or info.st_nlink!=1 or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('worker_runtime_changed')
   names.add(directory+'/'+path.name)
  if seen!=set(expected):raise ValueError('worker_runtime_changed')
 if type(request['files'])is not dict or set(request['files'])!=names or len(names)>256:raise ValueError('worker_runtime_changed')
 total=0;sources={};runtime_bytes={};runtime_identities={}
 for name,expected in request['files'].items():
  digest,amount,source,observed=sha(root/name,min(8388608,33554432-total),True);total+=amount
  if type(expected)is not str or digest!=expected:raise ValueError('worker_runtime_changed')
  runtime_bytes[str(root/name)]=source;runtime_identities[str(root/name)]=observed
  if name.startswith('scripts/'):sources[str(root/name)]=source
 # Execute only the bytes verified above. Never add the product directory to
 # sys.path, read an existing pyc, or let a newly inserted package win a race.
 original_spec=importlib.util.spec_from_file_location
 class VerifiedLoader(importlib.abc.Loader):
  def __init__(self,path):self.path=path
  def create_module(self,spec):return None
  def exec_module(self,module):exec(compile(sources[self.path],self.path,'exec',dont_inherit=True),module.__dict__)
 def verified_spec(name,location=None,*,loader=None,submodule_search_locations=None):
  path=str(pathlib.Path(location).absolute())if location is not None else None
  if path not in sources or loader is not None or submodule_search_locations is not None:raise ValueError('worker_runtime_changed')
  return original_spec(name,path,loader=VerifiedLoader(path))
 class VerifiedFinder(importlib.abc.MetaPathFinder):
  def find_spec(self,fullname,path=None,target=None):
   selected=str(root/'scripts'/(fullname+'.py'))
   if selected in sources:return verified_spec(fullname,selected)
 importlib.util.spec_from_file_location=verified_spec
 sys.meta_path.insert(0,VerifiedFinder())
 original_read_bytes=pathlib.Path.read_bytes
 def verified_read_bytes(path):
  selected=str(path.absolute())
  if selected in runtime_bytes:
   if identity(path.lstat())!=runtime_identities[selected]:raise ValueError('worker_runtime_changed')
   return runtime_bytes[selected]
  return original_read_bytes(path)
 pathlib.Path.read_bytes=verified_read_bytes
 import companion,pipeline_access
 store,query,exporter=pipeline_access._business()
 module=companion.core._load_bundled_helper('pipeline_partitioned')
 module.configure(store=store,exporter=exporter,privacy_guard=companion.privacy_guard)
 module._policy_worker_entry(request,{'sqliteSourceId':source_id,'sqliteVersion':sqlite3.sqlite_version,'sqliteNativeAllocationLimitBytes':limit})
except BaseException as exc:
 reason=getattr(exc,'code',None)
 if reason is None and str(exc) in ('partitioned_runtime_unsupported','partitioned_deadline','worker_runtime_changed','worker_request_invalid','worker_request_budget','duplicate_request_key'):reason=str(exc)
 if not isinstance(reason,str)or len(reason)>100:reason='partitioned_worker_failed'
 value={'format':'companion.private-policy-worker-response.v1','nonce':request.get('nonce')if type(request)is dict else None,'status':'blocked','reason':reason}
 report=getattr(exc,'_policy_safe_report',None)
 if type(report)is dict:
  allowed={'status','reason','phase','selectedRecords','visitedRecords','projectedRecords','spooledRecords','parityVerifiedRecords','renderedRecordsByLocale','referenceOccurrences','remainingSelectedRecords','firstUnprocessedPosition','selectionTraversal','wholeBusinessCompleteness','configuredOutputBytes','effectiveOutputBytes','outputBytes','cleanup','storageRequirement','alternatives'}
  if set(report)<=allowed:
   value['report']=report
 data=json.dumps(value,separators=(',',':')).encode()
 sys.stdout.buffer.write(data+b'\n');sys.stdout.buffer.flush()
'''.replace('__POLICY_NAMESPACE__',repr(_POLICY_RUNTIME_NAMES))


def _policy_bounded_hash(path,maximum,checkpoint=None):
    def identity(info):return(info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    def same_open_file(path_info,opened):
        if _guard._link_like(opened):return False
        if os.name!='nt':return identity(path_info)==identity(opened)
        # Preserve full checks within each stat provider. Do not compare CRT
        # handle ChangeTime/mode with Win32 path creation-time/executable bits.
        def shared(info):return(info.st_dev,info.st_ino,stat.S_IFMT(info.st_mode),info.st_nlink,info.st_size,info.st_mtime_ns)
        if shared(path_info)!=shared(opened):return False
        birth=[getattr(info,'st_birthtime_ns',None)for info in (path_info,opened)]
        return None in birth or birth[0]==birth[1]
    if checkpoint is not None:checkpoint()
    before=path.lstat()
    if (_guard._link_like(before)or not stat.S_ISREG(before.st_mode)or before.st_nlink!=1 or before.st_size>maximum):
        raise PartitionedExportError('partitioned_runtime_changed')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_BINARY',0));digest=hashlib.sha256();amount=0
    try:
        opened=os.fstat(fd)
        if not same_open_file(before,opened):raise PartitionedExportError('partitioned_runtime_changed')
        while True:
            if checkpoint is not None:checkpoint()
            block=os.read(fd,min(1024**2,maximum-amount+1))
            if not block:break
            amount+=len(block)
            if amount>maximum:raise PartitionedExportError('partitioned_runtime_changed')
            digest.update(block)
        after_fd=os.fstat(fd);after_path=path.lstat()
        if (identity(after_fd)!=identity(opened)or identity(after_path)!=identity(before)
                or _guard._link_like(after_fd)or _guard._link_like(after_path)):raise PartitionedExportError('partitioned_runtime_changed')
    finally:os.close(fd)
    return digest.hexdigest(),amount


def _policy_runtime_files(*,checkpoint=None):
    root=Path(__file__).resolve().parent.parent;files={};total=0
    for directory,expected in _POLICY_RUNTIME_NAMES.items():
        parent=root/directory;info=parent.lstat()
        if _guard._link_like(info) or not stat.S_ISDIR(info.st_mode):raise PartitionedExportError('partitioned_runtime_changed')
        seen=set()
        for path in parent.iterdir():
            if path.name not in expected or path.name in seen:raise PartitionedExportError('partitioned_runtime_changed')
            seen.add(path.name)
            info=path.lstat()
            if _guard._link_like(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
                raise PartitionedExportError('partitioned_runtime_changed')
            digest,amount=_policy_bounded_hash(path,min(POLICY_RUNTIME_FILE_BYTES,POLICY_RUNTIME_TOTAL_BYTES-total),checkpoint)
            files[directory+'/'+path.name]=digest;total+=amount
        if seen!=set(expected):raise PartitionedExportError('partitioned_runtime_changed')
    if len(files)>256:raise PartitionedExportError('partitioned_runtime_contract_budget')
    return root,files


def _validate_policy_set_result(value,record_limit,byte_limit):
    keys={'status','format','projection','entrypoint','manifest','recordCount','selectedRecords','processedRecords',
        'windowCount','chunkCount','projectionDigest','catalogRoots','outputBytes','fileCount','effectiveOutputBytes',
        'browserVerification','shapeValidation','offlineIssuerAuthenticity'}
    if type(value)is not dict or set(value)!=keys:raise PartitionedExportError('partitioned_worker_result_invalid')
    fixed={'status':'exported','format':POLICY_SET_FORMAT,'projection':'policy_projection','entrypoint':'index.html',
        'manifest':'policy-projection-set.json','browserVerification':'NOT_RUN','shapeValidation':'NOT_RUN','offlineIssuerAuthenticity':'NOT_ESTABLISHED'}
    if any(value[k]!=v for k,v in fixed.items()):raise PartitionedExportError('partitioned_worker_result_invalid')
    for key in ('recordCount','selectedRecords','processedRecords','windowCount','chunkCount','outputBytes','fileCount','effectiveOutputBytes'):
        if type(value[key])is not int or value[key]<0:raise PartitionedExportError('partitioned_worker_result_invalid')
    if (value['recordCount']>record_limit or value['selectedRecords']!=value['recordCount']or value['processedRecords']!=value['recordCount']
            or value['windowCount']>value['recordCount']or value['chunkCount']>value['recordCount']
            or value['outputBytes']>byte_limit or value['effectiveOutputBytes']!=byte_limit
            or not re.fullmatch('[0-9a-f]{64}',value['projectionDigest'])):raise PartitionedExportError('partitioned_worker_result_invalid')
    if type(value['catalogRoots'])is not dict or set(value['catalogRoots'])!={'chunks','routes','windows','files','lookup'}:
        raise PartitionedExportError('partitioned_worker_result_invalid')
    for kind,row in value['catalogRoots'].items():
        if (type(row)is not dict or set(row)!={'path','bytes','sha256','level','rowCount'}
                or type(row['path'])is not str or not re.fullmatch('catalog/'+kind+r'-[0-9]{2}-[0-9]{8}\.json',row['path'])
                or type(row['bytes'])is not int or not 1<=row['bytes']<=POLICY_CATALOG_BYTES
                or type(row['level'])is not int or not 0<=row['level']<=3
                or type(row['rowCount'])is not int or not 0<=row['rowCount']<=POLICY_CATALOG_ROWS
                or type(row['sha256'])is not str or not re.fullmatch('[0-9a-f]{64}',row['sha256'])):
            raise PartitionedExportError('partitioned_worker_result_invalid')
    return value


def _policy_worker_entry(request,runtime_proof):
    global _POLICY_WORKER_ACTIVE,_POLICY_WORKER_CANCEL,_POLICY_WORKER_PROGRESS,_POLICY_WORKER_RUNTIME_CHECK
    workspace,config=pipeline_store._config(request['workspace']);control=Path(request['control'])
    _store._private_directory(control)
    profile=_guard.load_profile((workspace,Path(config['repositoryRoot'])),required=True)
    if _sha(_raw(profile))!=request['profileBinding'] or pipeline_acl._principal()!=request['principal']:
        raise PartitionedExportError('partitioned_worker_context_changed')
    cancelled=[False]
    def terminate(*unused):cancelled[0]=True
    signal.signal(signal.SIGTERM,terminate)
    _POLICY_WORKER_ACTIVE=True
    # Different interpreter builds need not share a monotonic epoch. Transfer
    # a duration; the parent independently enforces its original deadline.
    child_deadline=time.monotonic()+request['timeoutSeconds']
    _POLICY_WORKER_CANCEL=lambda:cancelled[0]or time.monotonic()>child_deadline
    _POLICY_WORKER_PROGRESS=control/'progress.json'
    def runtime_io_checkpoint():
        if cancelled[0]:raise PartitionedExportError('partitioned_cancelled')
        if time.monotonic()>child_deadline:raise PartitionedExportError('partitioned_deadline')
    def runtime_check():
        root,files=_policy_runtime_files(checkpoint=runtime_io_checkpoint)
        if str(root)!=request['bundle']or files!=request['files']:raise PartitionedExportError('partitioned_runtime_changed')
    _POLICY_WORKER_RUNTIME_CHECK=runtime_check;runtime_check()
    runtime_proof.update(workerPid=os.getpid(),workerParentPid=os.getppid())
    try:
        result=_run_policy_projection_partitioned(workspace,request['snapshotId'],request['businessSnapshotId'],request['businessDigest'],request['output'],
            partition_size=request['partitionSize'],max_output_bytes=request['maxOutputBytes'],expected_profile=profile)
    except BaseException as exc:
        if type(getattr(exc,'report',None))is dict:
            try:
                current_profile=_guard.load_profile((workspace,Path(config['repositoryRoot'])),required=True)
                _guard.ensure_public_safe(exc.report,profile=current_profile,require_profile=True,allow_local_paths=False)
                exc._policy_safe_report=exc.report
            except Exception:pass
        raise
    runtime_check()
    output=Path(request['output']);info=output.lstat();manifest=output/'policy-projection-set.json';mi=manifest.lstat()
    response={'format':'companion.private-policy-worker-response.v1','nonce':request['nonce'],'status':'exported','result':result,
        'outputIdentity':[info.st_dev,info.st_ino,info.st_mode,getattr(info,'st_uid',0)],
        'manifestIdentity':[mi.st_dev,mi.st_ino,mi.st_size,mi.st_mtime_ns,mi.st_ctime_ns],
        'manifestSha256':_policy_bounded_hash(manifest,_exporter.MAX_PAGE_BYTES,lambda:runtime_check())[0],'runtimeProof':runtime_proof}
    raw=_raw(response)
    if len(raw)>65536:raise PartitionedExportError('partitioned_worker_result_budget')
    sys.stdout.buffer.write(raw+b'\n');sys.stdout.buffer.flush()


def export_policy_projection_partitioned(workspace_path,snapshot_id,business_snapshot_id,business_digest,output_dir,
                                         *,partition_size=PART_RECORDS,max_output_bytes=None,cancel=None,expected_profile=None,export_python=None):
    """Launch exactly one explicit export worker; never change host SQLite limits."""
    if _store is None:raise PartitionedExportError('partitioned_dependencies_required')
    if type(partition_size)is not int or not 1<=partition_size<=PART_RECORDS:raise PartitionedExportError('partitioned_record_budget')
    workspace,config=pipeline_store._config(workspace_path);initial_budget=copy.deepcopy(config['budgets'])
    deadline=time.monotonic()+initial_budget['max_run_seconds']
    def io_checkpoint():
        if cancel is not None and (cancel()if callable(cancel)else cancel.is_set()):raise PartitionedExportError('partitioned_cancelled')
        if time.monotonic()>deadline:raise PartitionedExportError('partitioned_deadline')
    ceiling=min(initial_budget['max_output_bytes'],POLICY_GLOBAL_BYTES)
    if max_output_bytes is not None and (type(max_output_bytes)is not int or not 1<=max_output_bytes<=ceiling):raise PartitionedExportError('partitioned_total_budget_invalid')
    if max_output_bytes is not None:ceiling=max_output_bytes
    if ceiling<=POLICY_SQLITE_HEAP+POLICY_WORKER_CONTROL_RESERVE:raise PartitionedExportError('partitioned_total_budget')
    roots=(workspace,Path(config['repositoryRoot']));profile=_guard.load_profile(roots,required=True)
    if expected_profile is not None and profile!=expected_profile:raise PartitionedExportError('partitioned_privacy_profile_changed')
    permits=[pipeline_acl.authorize(workspace,action,snapshot_id)for action in ('read_policy','export_html')]
    if any(p.get('decision')!='allow'for p in permits)or len({p['revision']for p in permits})!=1:raise PartitionedExportError('partitioned_access_denied')
    chosen=Path(sys.executable if export_python is None else export_python)
    if not chosen.is_absolute():raise PartitionedExportError('partitioned_runtime_path_required')
    executable=chosen.resolve(strict=True);info=executable.lstat()
    if not stat.S_ISREG(info.st_mode)or os.name!='nt'and info.st_mode&0o022 or info.st_size>256*1024**2:
        raise PartitionedExportError('partitioned_runtime_path_invalid')
    executable_digest=_policy_bounded_hash(executable,POLICY_EXECUTABLE_BYTES,io_checkpoint)[0]
    bundle,files=_policy_runtime_files(checkpoint=io_checkpoint)
    output=Path(output_dir).absolute();_exporter._safe_parent(output)
    jobs=pipeline_store._mkdir(workspace,'.export-jobs');control=pipeline_store._mkdir(jobs,'pw-'+uuid.uuid4().hex)
    cache=pipeline_store._mkdir(control,'cache');nonce=uuid.uuid4().hex
    request={'format':'companion.private-policy-worker-request.v1','nonce':nonce,'bundle':str(bundle),'files':files,
        'executableSha256':executable_digest,'workspace':str(workspace),'snapshotId':snapshot_id,'businessSnapshotId':business_snapshot_id,
        'businessDigest':business_digest,'output':str(output),'partitionSize':partition_size,'maxOutputBytes':max_output_bytes,
        'profileBinding':_sha(_raw(profile)),'principal':pipeline_acl._principal(),'control':str(control),'timeoutSeconds':initial_budget['max_run_seconds']}
    raw=_raw(request)+b'\n'
    if len(raw)>65536:raise PartitionedExportError('partitioned_worker_request_budget')
    env={}
    for name in ('PATH','SystemRoot','WINDIR','LANG','LC_ALL',_guard.PROFILE_ENV):
        if name in os.environ:env[name]=os.environ[name]
    env[pipeline_acl.PRINCIPAL_ENV]=request['principal']
    proc=subprocess.Popen([str(executable),'-I','-E','-s','-S','-B','-X','pycache_prefix='+str(cache),'-c',_POLICY_WORKER_BOOTSTRAP],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(control),env=env)
    buffers={'stdout':bytearray(),'stderr':bytearray()};overflow=threading.Event()
    def collect(stream,name,limit):
        try:
            while True:
                block=stream.read(4096)
                if not block:break
                if len(buffers[name])+len(block)>limit:overflow.set();break
                buffers[name].extend(block)
        finally:stream.close()
    threads=[threading.Thread(target=collect,args=(proc.stdout,'stdout',65536),daemon=True),threading.Thread(target=collect,args=(proc.stderr,'stderr',16384),daemon=True)]
    for thread in threads:thread.start()
    writer_errors=[]
    def send_request():
        try:proc.stdin.write(raw);proc.stdin.flush()
        except (OSError,ValueError)as exc:writer_errors.append(type(exc).__name__)
        finally:
            try:proc.stdin.close()
            except (OSError,ValueError):pass
    writer=threading.Thread(target=send_request,daemon=True);writer.start()
    reason=None;observed_report=None
    def current_context():
        if [pipeline_acl.authorize(workspace,action,snapshot_id)for action in ('read_policy','export_html')]!=permits:
            raise PartitionedExportError('partitioned_acl_revision_changed')
        if pipeline_store._config(workspace)[1]['budgets']!=initial_budget:raise PartitionedExportError('partitioned_budget_binding_changed')
        if _guard.load_profile(roots,required=True)!=profile:raise PartitionedExportError('partitioned_privacy_profile_changed')
        if (_policy_runtime_files(checkpoint=io_checkpoint)!=(bundle,files)
                or _policy_bounded_hash(executable,POLICY_EXECUTABLE_BYTES,io_checkpoint)[0]!=executable_digest):
            raise PartitionedExportError('partitioned_runtime_changed')
    try:
        last_check=0
        while proc.poll()is None:
            if overflow.is_set():raise PartitionedExportError('partitioned_worker_result_budget')
            if cancel is not None and (cancel()if callable(cancel)else cancel.is_set()):raise PartitionedExportError('partitioned_cancelled')
            if time.monotonic()>deadline:raise PartitionedExportError('partitioned_deadline')
            if time.monotonic()-last_check>=1:current_context();last_check=time.monotonic()
            time.sleep(.05)
        writer.join(timeout=1)
        if writer.is_alive()or writer_errors:raise PartitionedExportError('partitioned_worker_request_failed')
        for thread in threads:thread.join(timeout=1)
        if overflow.is_set():raise PartitionedExportError('partitioned_worker_result_budget')
        if buffers['stderr']or proc.returncode!=0:raise PartitionedExportError('partitioned_worker_failed')
        response=_exporter._strict_projection_json(bytes(buffers['stdout']))
        if type(response)is not dict or response.get('format')!='companion.private-policy-worker-response.v1'or response.get('nonce')!=nonce:
            raise PartitionedExportError('partitioned_worker_result_invalid')
        if response.get('status')!='exported':
            if set(response)-{'format','nonce','status','reason','report'}:raise PartitionedExportError('partitioned_worker_result_invalid')
            if type(response.get('report'))is dict:
                _guard.ensure_public_safe(response['report'],profile=profile,require_profile=True,allow_local_paths=False)
                observed_report=response['report']
            raise PartitionedExportError(response.get('reason','partitioned_worker_failed'))
        expected={'format','nonce','status','result','outputIdentity','manifestIdentity','manifestSha256','runtimeProof'}
        if set(response)!=expected:raise PartitionedExportError('partitioned_worker_result_invalid')
        if response['runtimeProof'].get('workerPid')!=proc.pid or response['runtimeProof'].get('workerParentPid')!=os.getpid():
            raise PartitionedExportError('partitioned_worker_result_invalid')
        current_context();oi=output.lstat();mi=(output/'policy-projection-set.json').lstat()
        if ([oi.st_dev,oi.st_ino,oi.st_mode,getattr(oi,'st_uid',0)]!=response['outputIdentity']
                or [mi.st_dev,mi.st_ino,mi.st_size,mi.st_mtime_ns,mi.st_ctime_ns]!=response['manifestIdentity']
                or _policy_bounded_hash(output/'policy-projection-set.json',_exporter.MAX_PAGE_BYTES,io_checkpoint)[0]!=response['manifestSha256']):
            raise PartitionedExportError('partitioned_worker_output_changed')
        result=_validate_policy_set_result(response['result'],min(initial_budget['max_records'],POLICY_GLOBAL_RECORDS),ceiling)
        _guard.ensure_public_safe(result,profile=profile,allow_local_paths=False,require_profile=True)
        current_context()
        pipeline_store._atomic(control/'runtime-proof.json',_raw({**response['runtimeProof'],'executableSha256':executable_digest}))
        return result
    except BaseException as exc:
        reason=getattr(exc,'code','partitioned_worker_failed')
        if proc.poll()is None:
            proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)
        report={'status':'BLOCKED','reason':reason,'publicationAttestation':'UNATTESTED','cleanup':'UNVERIFIED_RETAINED',
            'selectedRecords':'UNKNOWN','processedRecords':'UNKNOWN','frontier':'UNKNOWN_AFTER_WORKER_LOSS','wholeBusinessCompleteness':'UNKNOWN'}
        if observed_report is not None:report.update(observed_report)
        else:
            try:
                progress=control/'progress.json'
                fd=os.open(progress,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                try:
                    before=os.fstat(fd);_guard._check_private_file_metadata(before)
                    payload=os.read(fd,65537)
                    if len(payload)>65536 or _identity(os.fstat(fd))!=_identity(before):raise ValueError('worker_progress_invalid')
                finally:os.close(fd)
                last=_exporter._strict_projection_json(payload)
                allowed={'format','status','reason','phase','selectedRecords','visitedRecords','projectedRecords','spooledRecords','parityVerifiedRecords','renderedRecordsByLocale','referenceOccurrences','remainingSelectedRecords','firstUnprocessedPosition','window','configuredOutputBytes','effectiveOutputBytes','workingCatalogBytes','outputBytes','fileCount','selectionTraversal','wholeBusinessCompleteness'}
                if type(last)is not dict or set(last)-allowed:raise ValueError('worker_progress_invalid')
                _guard.ensure_public_safe(last,profile=profile,require_profile=True,allow_local_paths=False)
                report.update(selectedRecords=last.get('selectedRecords','UNKNOWN'),lastObservedProgress=last,frontier='UNKNOWN_AFTER_LAST_OBSERVATION')
            except Exception:pass
        raise PartitionedExportError(reason,report)from None
    finally:
        if proc.poll()is None:proc.kill();proc.wait(timeout=2)
        writer.join(timeout=1)
        for thread in threads:thread.join(timeout=1)
