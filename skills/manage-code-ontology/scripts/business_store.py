"""Immutable local business overlays over verified, read-only source snapshots.

Only one atomic state pointer publishes a fully written sidecar. Failed writes
leave the previous pointer intact; unreferenced staging directories are not read.
An OS owner able to rewrite all artifacts remains outside this integrity model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import OrderedDict
from threading import RLock
import os
import re
import stat
import sqlite3
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

_source = _semantics = _acl = _guard = _spec = None
MAX_BYTES = 64 * 1024 * 1024
BOUNDED_METADATA_BYTES = 32 * 1024 * 1024
ID = re.compile(r"bs-[0-9a-f]{32}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
_INDEX_COHERENCE_VERSION = "business-index-coherence-v1"
_INDEX_CACHE_LIMIT = 64
_INDEX_CACHE = OrderedDict()
_INDEX_CACHE_LOCK = RLock()


class BusinessStoreError(ValueError):
    def __init__(self, code="business_store_invalid"):
        self.code = code if re.fullmatch(r"[a-z_]{1,100}", code) else "business_store_invalid"
        super().__init__(self.code)


def configure(*, pipeline_store, semantics, acl, privacy_guard, business_spec):
    global _source, _semantics, _acl, _guard, _spec
    if (type(business_spec) is not dict or set(business_spec) != {"businessSpecId", "businessSpecHash"}
            or not isinstance(business_spec["businessSpecId"], str)
            or not HASH.fullmatch(business_spec.get("businessSpecHash", ""))):
        raise BusinessStoreError("business_spec_invalid")
    for dependency, names in ((pipeline_store, ("open_reader", "status", "_read", "_atomic", "_mkdir", "_directory", "_lock", "_state", "_private_file")),
                              (semantics, ("canonical", "digest", "loads", "build_candidates", "validate_review")),
                              (acl, ("authorize", "_principal", "publication_guard")), (privacy_guard, ("ensure_public_safe", "_check_private_file_metadata"))):
        if any(not callable(getattr(dependency, name, None)) for name in names):
            raise BusinessStoreError("dependency_invalid")
    _source, _semantics, _acl, _guard, _spec = pipeline_store, semantics, acl, privacy_guard, copy.deepcopy(business_spec)
    _semantics.configure(privacy_guard=privacy_guard)


def _ready():
    if _source is None: raise BusinessStoreError("dependencies_not_configured")


def _safe(value):
    _guard.ensure_public_safe(value)
    return value


def _read(path, root, maximum=MAX_BYTES):
    raw = _source._read(path, maximum, root)
    _guard._check_private_file_metadata(path.lstat())
    if os.name == "nt":
        with path.open("rb") as handle: _guard._windows_profile_security(handle.fileno())
    result = _semantics.loads(raw)
    _safe(result)
    return result, raw


def _private_directory(path):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:
        raise BusinessStoreError("business_directory_boundary")
    if os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
        raise BusinessStoreError("business_directory_permissions")


def _workspace(path):
    _ready()
    workspace = _source._directory(path)
    for parent in (workspace, *workspace.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BusinessStoreError("linked_workspace_forbidden")
    return workspace


def _authorize(workspace, action, snapshot):
    result = _acl.authorize(workspace, action, snapshot)
    if result.get("decision") != "allow": raise BusinessStoreError("authorization_required")
    return result


def _same_access(workspace, action, snapshot, previous):
    if _semantics.canonical(_authorize(workspace, action, snapshot)) != _semantics.canonical(previous):
        raise BusinessStoreError("authorization_changed")


def _state(workspace):
    path = workspace / "business-state.json"
    if not path.exists() and not path.is_symlink(): return None
    value, _ = _read(path, workspace, 1024*1024)
    if type(value) is not dict or set(value) != {"schemaVersion", "businessSnapshotId", "businessDigest", "sourceSnapshotId"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise BusinessStoreError("business_state_invalid")
    if not ID.fullmatch(value.get("businessSnapshotId", "")) or not HASH.fullmatch(value.get("businessDigest", "")):
        raise BusinessStoreError("business_state_invalid")
    return value


def _pins(reader):
    raw = _source._read(reader.directory / "manifest.json", MAX_BYTES, reader.workspace)
    metadata = reader.metadata
    return {"sourceSnapshotId": reader.snapshot_id, "sourceManifestSha256": hashlib.sha256(raw).hexdigest(),
            "sourceFingerprint": metadata["sourceFingerprint"], "analysisSpecId": metadata["analysisSpecId"]}


def _source_current(workspace, snapshot):
    # Check the registered pointer, not source files. No raw source read or refresh.
    if _source._state(workspace).get("currentSnapshot") != snapshot:
        raise BusinessStoreError("source_snapshot_not_current")


def _summary(manifest):
    return _safe({k: copy.deepcopy(v) for k,v in manifest.items() if k not in ("artifacts", "receiptDigest")})


def _publish_v1(workspace, source_reader, payload, receipt, previous, access):
    pins = _pins(source_reader)
    bid = "bs-" + uuid.uuid4().hex
    root = _source._mkdir(workspace, "business-snapshots")
    _private_directory(root)
    stage = _source._mkdir(root, ".stage-" + uuid.uuid4().hex)
    _private_directory(stage)
    records = copy.deepcopy(payload["records"])
    for i,record in enumerate(records):
        _semantics.validate_record_values(record)
        if record.get("businessApproval") in ("approved","rejected","revoked") and "approvalReceiptId" not in record:
            record["approvalReceiptId"]="business-receipt:"+bid
            records[i]=_semantics.seal_record(record)
    coverage = copy.deepcopy(payload["coverage"])
    coverage["semanticStatus"]={
        "candidateRecords":sum(r.get("support")=="candidate" for r in records),
        "approvedMeanings":sum(r.get("businessApproval")=="approved" for r in records),
        "unknownFacets":sum(f.get("status")=="UNKNOWN" for r in records for f in r.get("facets",{}).values()),
        "supportedFacets":sum(f.get("status")=="SOURCE_SUPPORTED" for r in records for f in r.get("facets",{}).values()),
        "declaredFacets":sum(f.get("status")=="DECLARED" for r in records for f in r.get("facets",{}).values()),
        "conflictedRecords":sum(r.get("support")=="conflicted" for r in records),
        "revokedRecords":sum(r.get("support")=="revoked" for r in records)}
    receipt = {"schemaVersion": 1, "id":"business-receipt:"+bid, "businessSnapshotId": bid, **pins, **_spec, **receipt,
               "executionAuthorization": "NOT_PROVIDED", "runtimeStatus": "NOT_OBSERVED",
               "claimApprovalReceipts": {r["id"]:r["approvalReceiptId"] for r in records if "approvalReceiptId" in r},
               "parentBusinessSnapshotId":previous["businessSnapshotId"] if previous else None,
               "parentBusinessDigest":previous["businessDigest"] if previous else None}
    artifacts = {"records.json": records, "coverage.json": coverage, "receipt.json": receipt}
    manifest = {"schemaVersion": 1, "status": "ready", "businessSnapshotId": bid, **pins, **_spec,
                "parentBusinessSnapshotId": previous["businessSnapshotId"] if previous else None,
                "parentBusinessDigest": previous["businessDigest"] if previous else None,
                "recordCount": len(records), "coverage": coverage,
                "reviewManifestDigest": payload.get("reviewManifestDigest"),
                "sourceAccess": "not_read", "sourceCompletion": "source_snapshot_preserved",
                "businessCompletion": coverage["state"], "globalCompleteness": "UNKNOWN",
                "dependencyClosureDigest": _semantics.digest([r.get("sourceAnchors", []) for r in records]),
                "receiptDigest": _semantics.digest(receipt),
                "artifacts": {name: _semantics.digest(value) for name,value in artifacts.items()}}
    if "currentReviewDiagnostics" in payload: manifest["currentReviewDiagnostics"] = payload["currentReviewDiagnostics"]
    manifest["businessDigest"] = _semantics.digest(manifest)
    for name,value in {**artifacts, "manifest.json": manifest}.items():
        _safe(value)
        raw = _semantics.canonical(value)
        if len(raw) > MAX_BYTES: raise BusinessStoreError("business_artifact_budget")
        _source._atomic(stage / name, raw)
        _guard._check_private_file_metadata((stage/name).lstat())
    # The source writer lock is already held; the independent ACL publication
    # lock prevents a supported permission change between authorization and the
    # approval pointer commit. Never transfer the caller's old grant implicitly.
    with _acl.publication_guard(workspace):
        # No mutation to the source snapshot is made at any point.
        source_reader._stable()
        _source_current(workspace, pins["sourceSnapshotId"])
        _same_access(workspace, "manage_knowledge", pins["sourceSnapshotId"], access)
        if _state(workspace) != previous: raise BusinessStoreError("business_pointer_changed")
        final = root / bid
        if final.exists(): raise BusinessStoreError("business_identity_collision")
        os.rename(stage, final)
        _source._sync_dir(root)
        _same_access(workspace, "manage_knowledge", pins["sourceSnapshotId"], access)
        _source._atomic(workspace / "business-state.json", {"schemaVersion": 1, "businessSnapshotId": bid,
                        "businessDigest": manifest["businessDigest"], "sourceSnapshotId": pins["sourceSnapshotId"]})
    return _summary(manifest)


def _cancel(cancel, deadline=None):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise BusinessStoreError("business_cancelled")
    if deadline is not None and time.monotonic()>=deadline:raise BusinessStoreError("business_deadline_exceeded")


_RECORD_SQL = "CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,namekey TEXT NOT NULL,domain TEXT NOT NULL,payload TEXT NOT NULL)"
_ENTRY_SQL = "CREATE TABLE entries(position INTEGER PRIMARY KEY,payload TEXT NOT NULL)"
_PROCESSING_SQL = "CREATE TABLE processing(position INTEGER PRIMARY KEY,payload TEXT NOT NULL)"


def _reader_resource_policy(resource_policy):
    if resource_policy is None:return
    if type(resource_policy)is not str or resource_policy!="bounded_memory_v1":raise BusinessStoreError("business_resource_policy_invalid")
    helper=getattr(_source,"configure_reader_resource_policy",None)
    if not callable(helper):raise BusinessStoreError("business_resource_policy_unsupported")
    probe=sqlite3.connect(":memory:")
    try:helper(probe,resource_policy)
    finally:probe.close()


def _database(path, *, readonly=False, resource_policy=None):
    if resource_policy is not None:
        if not readonly:raise BusinessStoreError("business_resource_policy_readonly_required")
        _reader_resource_policy(resource_policy)
    if readonly:
        _source._private_file(path)
        connection=sqlite3.connect(path.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        connection=sqlite3.connect(str(path))
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
    try:
        if resource_policy is not None:_source.configure_reader_resource_policy(connection,resource_policy)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA cache_size=-1024")
        if resource_policy is None:connection.execute("PRAGMA temp_store=FILE")
        if readonly: connection.execute("PRAGMA query_only=ON")
    except BaseException:connection.close();raise
    return connection


def _publish(workspace, source_reader, payload, receipt, previous, access, *, chunk_records=10000, cancel=None):
    """Bounded disk staging, then immutable sorted <=10000-row/64MiB shards.

    The private staging database is temporary workspace, not a published
    artifact. Its bytes plus finished shards count against the unchanged source
    workspace output budget. No unbounded list, canonical document or index is
    constructed for the complete candidate inventory.
    """
    if type(chunk_records) is not int or not 1<=chunk_records<=10000: raise BusinessStoreError("business_chunk_budget")
    budgets=source_reader.config["budgets"]
    deadline=time.monotonic()+budgets["max_run_seconds"]
    pins=_pins(source_reader);bid="bs-"+uuid.uuid4().hex
    root=_source._mkdir(workspace,"business-snapshots");_private_directory(root)
    stage=_source._mkdir(root,".stage-"+uuid.uuid4().hex);_private_directory(stage)
    spool=None
    def budget():
        total=sum(p.stat().st_size for p in stage.iterdir() if p.is_file())
        if total>budgets["max_output_bytes"]: raise BusinessStoreError("business_output_budget")
    try:
        spool=_database(stage/".spool.sqlite")
        spool.execute(_RECORD_SQL);spool.execute(_ENTRY_SQL)
        processing=payload["coverage"].get("processingContract") is True
        if processing:spool.execute("CREATE TABLE outcomes(identity TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        priorities={"accepted":0,"conflicted":1,"unsupported":2,"rejected":3,"omitted":4,"duplicate":5}
        def outcome(value):
            if not processing:return
            item=copy.deepcopy(value);scope=item.get("processingScopeId",payload["coverage"].get("processingScopeId"));index=item.get("inputIndex")
            state=item.get("outcomeClass",item.get("status"))
            if item.get("reason")=="duplicate_concept_identity":state="duplicate"
            if type(scope)is not str or not re.fullmatch(r"processing:[0-9a-f]{64}",scope):return
            if state in ("revoked","invalidated"):
                identity=scope+"/event/"+_semantics.digest(item)
            elif state in priorities and type(index)is int and index>=0:identity=scope+"/input/"+str(index)
            else:return
            item.update(processingScopeId=scope,outcomeClass=state,status=state)
            _safe(item);previous=spool.execute("SELECT payload FROM outcomes WHERE identity=?",(identity,)).fetchone()
            if previous and priorities.get(_semantics.loads(previous[0])["outcomeClass"],99)>priorities.get(state,99):return
            spool.execute("INSERT OR REPLACE INTO outcomes VALUES(?,?)",(identity,_semantics.canonical(item).decode()))
        if processing and callable(payload.get("priorProcessing")):
            for item in payload["priorProcessing"]():outcome(item)
        count=entry_count=claim_count=0;claims={}
        semantic={key:0 for key in ("candidateRecords","approvedMeanings","unknownFacets","supportedFacets","declaredFacets","conflictedRecords","revokedRecords")}
        closure=hashlib.sha256();preview=[]
        events=payload.get("events")
        if events is None:
            events=((record,None) for record in payload["records"])
        for record,entry in events:
            _cancel(cancel,deadline)
            if record is not None:
                record=copy.deepcopy(record)
                _semantics.validate_record_values(record)
                if record.get("businessApproval") in ("approved","rejected","revoked") and "approvalReceiptId" not in record:
                    record["approvalReceiptId"]="business-receipt:"+bid
                    record=_semantics.seal_record(record)
                if processing and "processingScopeId" in record:
                    state="conflicted"if record.get("support")=="conflicted"else"rejected"if record.get("businessApproval")=="rejected"else"accepted"
                    outcome({"processingScopeId":record["processingScopeId"],"inputIndex":record["inputIndex"],"recordId":record["id"],"status":state,"reason":"validated_record"})
                if _semantics.canonical(record)!=_semantics.canonical(_semantics.seal_record(record)):
                    raise BusinessStoreError("business_record_integrity")
                _safe(record);encoded=_semantics.canonical(record)
                try: spool.execute("INSERT INTO records VALUES(?,?,?,?,?)",(record["id"],record["kind"],record["name"].casefold(),record["domain"],encoded.decode()))
                except sqlite3.IntegrityError: raise BusinessStoreError("duplicate_business_identity") from None
                count+=1
                if count>budgets["max_records"]: raise BusinessStoreError("business_record_budget")
                if "approvalReceiptId" in record:
                    claim_count+=1
                    if len(claims)<100:claims[record["id"]]=record["approvalReceiptId"]
                semantic["candidateRecords"]+=record.get("support")=="candidate"
                semantic["approvedMeanings"]+=record.get("businessApproval")=="approved"
                semantic["conflictedRecords"]+=record.get("support")=="conflicted"
                semantic["revokedRecords"]+=record.get("support")=="revoked"
                for facet in record.get("facets",{}).values():
                    for status,key in (("UNKNOWN","unknownFacets"),("SOURCE_SUPPORTED","supportedFacets"),("DECLARED","declaredFacets")):
                        semantic[key]+=facet.get("status")==status
                raw=_semantics.canonical(record.get("sourceAnchors",[]));closure.update(len(raw).to_bytes(8,"big"));closure.update(raw)
            if entry is not None:
                outcome(entry)
                _safe(entry);raw=_semantics.canonical(entry)
                spool.execute("INSERT INTO entries VALUES(?,?)",(entry_count,raw.decode()));entry_count+=1
                if len(preview)<100:preview.append(copy.deepcopy(entry))
            budget()
            if (count+entry_count)%100==0:spool.commit()
        for entry in payload["coverage"].get("entries",[]):
            outcome(entry)
            _safe(entry);spool.execute("INSERT INTO entries VALUES(?,?)",(entry_count,_semantics.canonical(entry).decode()));entry_count+=1
            if len(preview)<100:preview.append(copy.deepcopy(entry))
        spool.commit();budget()
        processing_count=0;processing_counts={};scope_counts={}
        if processing:
            spool.execute(_PROCESSING_SQL)
            for position,(encoded,)in enumerate(spool.execute("SELECT payload FROM outcomes ORDER BY identity")):
                item=_semantics.loads(encoded);state=item["outcomeClass"];scope=item["processingScopeId"]
                processing_counts[state]=processing_counts.get(state,0)+1
                if state in priorities:scope_counts[scope]=scope_counts.get(scope,0)+1
                spool.execute("INSERT INTO processing VALUES(?,?)",(position,encoded));processing_count+=1
            spool.commit()
        shards=[];artifacts={}
        def partitions(table):
            nonlocal spool
            columns="id,kind,namekey,domain,payload" if table=="records" else "position,payload"
            cursor=spool.execute("SELECT "+columns+" FROM "+table+" ORDER BY "+("id" if table=="records" else "position"))
            db=None;descriptor=None;logical=0
            try:
                for row in cursor:
                    _cancel(cancel,deadline)
                    row_bytes=len(row[-1].encode())
                    if db is None or descriptor["count"]>=chunk_records or (logical+row_bytes>16*1024*1024 and descriptor["count"]):
                        if db is not None:
                            db.commit();db.close();db=None
                            finish(descriptor)
                        name=("records" if table=="records" else"processing"if table=="processing"else "coverage")+"-%06d.sqlite"%len(shards)
                        db=_database(stage/name);db.execute(_RECORD_SQL if table=="records" else _PROCESSING_SQL if table=="processing"else _ENTRY_SQL)
                        descriptor={"name":name,"table":table,"count":0,"first":row[0],"last":row[0]};logical=0
                    db.execute("INSERT INTO "+table+" VALUES("+",".join("?" for _ in row)+")",row)
                    descriptor["count"]+=1;descriptor["last"]=row[0];logical+=row_bytes
                if db is not None:db.commit();db.close();db=None;finish(descriptor)
            finally:
                if db is not None:db.close()
        def finish(descriptor):
            path=stage/descriptor["name"]
            _source._private_file(path)
            fd=os.open(path,os.O_RDWR|getattr(os,"O_NOFOLLOW",0))
            try:os.fsync(fd)
            finally:os.close(fd)
            digest,size,_=_source._hash_file(path)
            if size>MAX_BYTES: raise BusinessStoreError("business_artifact_budget")
            descriptor["bytes"]=size;artifacts[descriptor["name"]]=digest;shards.append(descriptor);budget()
        partitions("records");partitions("entries")
        if processing:partitions("processing")
        spool.close();spool=None;(stage/".spool.sqlite").unlink()
        coverage=copy.deepcopy(payload["coverage"])
        coverage.update(semanticStatus=semantic,entries=preview,entryCount=entry_count,
                        entriesTruncated=entry_count>len(preview),entriesStorage="partitioned")
        if processing:
            scopes=coverage.get("processingScopes",[])
            coverage.update(processingEntryCount=processing_count,processingOutcomeCounts=processing_counts,
                processingReconciled=bool(scopes)and all(type(s.get("denominator"))is int and scope_counts.get(s["scopeId"],0)==s["denominator"]for s in scopes),
                processingScopeCounts=[{**scope,"accounted":scope_counts.get(scope["scopeId"],0)}for scope in scopes])
        receipt={"schemaVersion":1,"id":"business-receipt:"+bid,"businessSnapshotId":bid,**pins,**_spec,**receipt,
            "executionAuthorization":"NOT_PROVIDED","runtimeStatus":"NOT_OBSERVED","claimApprovalReceipts":claims,
            "claimApprovalReceiptCount":claim_count,"claimApprovalReceiptsTruncated":claim_count>len(claims),
            "claimApprovalReceiptStorage":"record.approvalReceiptId",
            "parentBusinessSnapshotId":previous["businessSnapshotId"] if previous else None,
            "parentBusinessDigest":previous["businessDigest"] if previous else None}
        for name,value in (("coverage.json",coverage),("receipt.json",receipt)):
            raw=_semantics.canonical(_safe(value))
            if len(raw)>MAX_BYTES:raise BusinessStoreError("business_artifact_budget")
            _source._atomic(stage/name,raw);artifacts[name]=hashlib.sha256(raw).hexdigest()
        manifest={"schemaVersion":2,"status":"ready","businessSnapshotId":bid,**pins,**_spec,
            "parentBusinessSnapshotId":previous["businessSnapshotId"] if previous else None,
            "parentBusinessDigest":previous["businessDigest"] if previous else None,
            "recordCount":count,"coverage":coverage,"reviewManifestDigest":payload.get("reviewManifestDigest"),
            "sourceAccess":"not_read","sourceCompletion":"source_snapshot_preserved","businessCompletion":coverage["state"],
            "globalCompleteness":"UNKNOWN","dependencyClosureDigest":closure.hexdigest(),"dependencyClosureEncoding":"framed-record-anchors-v2",
            "receiptDigest":_semantics.digest(receipt),"storage":{"format":"sqlite-shards-v2","chunkRecordLimit":chunk_records,"artifactByteLimit":MAX_BYTES,"shards":shards},
            "artifacts":artifacts}
        if "currentReviewDiagnostics" in payload: manifest["currentReviewDiagnostics"] = payload["currentReviewDiagnostics"]
        manifest["businessDigest"]=_semantics.digest(manifest)
        _source._atomic(stage/"manifest.json",_semantics.canonical(_safe(manifest)));budget();_cancel(cancel,deadline)
        _source._sync_dir(stage)
        with _acl.publication_guard(workspace):
            source_reader._stable();_source_current(workspace,pins["sourceSnapshotId"])
            _same_access(workspace,"manage_knowledge",pins["sourceSnapshotId"],access)
            if _state(workspace)!=previous:raise BusinessStoreError("business_pointer_changed")
            final=root/bid
            if final.exists():raise BusinessStoreError("business_identity_collision")
            os.rename(stage,final);_source._sync_dir(root)
            _same_access(workspace,"manage_knowledge",pins["sourceSnapshotId"],access);_cancel(cancel,deadline)
            _source._atomic(workspace/"business-state.json",{"schemaVersion":1,"businessSnapshotId":bid,
                "businessDigest":manifest["businessDigest"],"sourceSnapshotId":pins["sourceSnapshotId"]})
        return _summary(manifest)
    finally:
        if spool is not None:spool.close()
        if stage.exists():shutil.rmtree(stage)


def _receipt(workspace, snapshot, action, access, **extra):
    # Principal is provided by the server's trusted environment binding, never input.
    principal = _acl._principal()
    _safe(principal)
    return {"action": action, "authority": "trusted_local_manage_knowledge", "approvalScope": "knowledge_statement_only",
            "principalDigest": _semantics.digest(principal), "accessRevision": access["revision"],
            "accessPolicyDigest": access["policyDigest"], "identityAssurance": "local_process_alias_only", **extra}


def build(workspace, source_snapshot_id, *, max_records=None, partition_size=10000, processing_contract=False, cancel=None):
    """Default to the whole inventory; an explicit max_records is a preview."""
    workspace = _workspace(workspace)
    if type(processing_contract)is not bool:raise BusinessStoreError("processing_contract_invalid")
    if max_records is not None and (type(max_records) is not int or not 1 <= max_records <= _semantics.MAX_RECORDS):
        raise BusinessStoreError("candidate_budget_invalid")
    if type(partition_size) is not int or not 1<=partition_size<=10000:raise BusinessStoreError("business_chunk_budget")
    access = _authorize(workspace, "manage_knowledge", source_snapshot_id)
    with _source._lock(workspace):
        previous = _state(workspace)
        _source_current(workspace, source_snapshot_id)
        with _source.open_reader(workspace, source_snapshot_id) as reader:
            expected = reader.metadata.get("recordCount")
            if type(expected) is not int or expected < 0: raise BusinessStoreError("source_inventory_invalid")
            coverage = _semantics._coverage(expected, 0, [], scope="selected_source_snapshot_records")
            coverage.update(processed=0, visited=0, unsupported=0, omitted=expected,
                            storageCompleteness="INCOMPLETE", inventoryAccounting="all_selected_records")
            if processing_contract:
                scope="processing:"+_semantics.digest(["source_inputs",_pins(reader)])
                coverage.update(processingContract=True,processingScopeId=scope,processingScopes=[{"scopeId":scope,"denominator":expected,"kind":"selected_source_snapshot_records"}])
            import pipeline_policy
            read_policy = getattr(reader, "read_policy_records", None)
            policy_coverage = read_policy().get("coverage", {}) if callable(read_policy) else {}
            coverage["sourceDeclarationCoverage"] = pipeline_policy.declaration_coverage_summary(policy_coverage.get("sourceDeclarationCoverage"))
            coverage["sourceFunctionProcessing"] = pipeline_policy.function_processing_summary(policy_coverage.get("sourceFunctionProcessing"))
            def events():
                for index, record, entry in _semantics.iter_candidate_events(reader, source_pins=_pins(reader)):
                    _cancel(cancel)
                    coverage["visited"] += 1
                    if processing_contract:
                        if record is not None:record=_semantics.seal_record({**record,"inputIndex":index,"processingScopeId":scope})
                        if entry is not None:entry={**entry,"processingScopeId":scope}
                    if max_records is not None and index>=max_records:
                        identity=_semantics.outcome_source_fields(record.get("sourceRecordId"),record.get("sourceKind")) if record is not None else _semantics.outcome_source_fields(entry.get("sourceRecordId"),entry.get("sourceKind"))
                        yield None,{"inputIndex":index,**identity,"status":"omitted","reason":"candidate_record_budget",**({"processingScopeId":scope}if processing_contract else{})}
                        continue
                    coverage["processed"] += 1
                    coverage["omitted"] = max(0, expected-coverage["processed"])
                    if entry is not None:coverage["unsupported"] += 1
                    yield record,entry
                if coverage["visited"] != expected:raise BusinessStoreError("source_inventory_count_mismatch")
                coverage.update(numerator=coverage["processed"]-coverage["unsupported"],rejected=coverage["unsupported"],
                    storageCompleteness="COMPLETE" if coverage["omitted"]==0 else "INCOMPLETE")
            receipt = _receipt(workspace, source_snapshot_id, "build_candidates", access,
                               invalidation={"previousApprovalTransfer": "none", "reason": "new_candidate_generation"})
            try:
                return _publish(workspace, reader, {"events":events(), "coverage":coverage}, receipt, previous, access,
                                chunk_records=partition_size, cancel=cancel)
            except BaseException as exc:
                attempt = {**_pins(reader), "schemaVersion":1, "status":"unpublished",
                    "reason":"cancelled" if isinstance(exc, BusinessStoreError) and exc.code=="business_cancelled" else "build_failed",
                    "coverage":{**{k:v for k,v in coverage.items() if k!="entries"},"storageCompleteness":"UNPUBLISHED"},
                    "previousBusinessSnapshotId":previous["businessSnapshotId"] if previous else None}
                _source._atomic(workspace/"business-last-attempt.json", _semantics.canonical(_safe(attempt)))
                raise


def load_review(path):
    _ready()
    path = Path(path)
    root = _source._directory(path.parent)
    for parent in (root, *root.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BusinessStoreError("linked_review_forbidden")
    value, _ = _read(root/path.name, root, 16*1024*1024)
    if type(value) is not dict: raise BusinessStoreError("review_manifest_invalid")
    return value


def _all_entries(reader):
    offset=0
    while True:
        page=reader.coverage(offset=offset,limit=100)
        yield from page["entries"]
        if page["nextOffset"] is None: return
        offset=page["nextOffset"]


def _all_processing(reader):
    offset=0
    while True:
        page=reader.processing(offset=offset,limit=100)
        yield from page["entries"]
        if page["nextOffset"] is None:return
        offset=page["nextOffset"]


def review(workspace, source_snapshot_id, business_snapshot_id, business_digest, manifest, *, decision="approve", max_records=10000, cancel=None):
    workspace = _workspace(workspace)
    if decision not in ("approve", "reject"): raise BusinessStoreError("review_decision_invalid")
    access = _authorize(workspace, "manage_knowledge", source_snapshot_id)
    with _source._lock(workspace):
        previous = _state(workspace)
        with open_reader(workspace, source_snapshot_id, business_snapshot_id, business_digest) as old:
            original_coverage=copy.deepcopy(old.metadata["coverage"])
            removed=[r["id"] for r in old.iter_records() if r.get("reviewedMeaning")=="declared_attestation"]
            if len(removed)>10000: raise BusinessStoreError("review_layer_budget")
        with _source.open_reader(workspace, source_snapshot_id) as reader:
            payload = _semantics.validate_review(manifest, reader, source_pins=_pins(reader), candidates=(), max_records=max_records)
            if "currentReviewDiagnostics" not in payload:
                payload["currentReviewDiagnostics"]={"schemaVersion":1,"reviewManifestDigest":payload["reviewManifestDigest"],
                    "selectedInputs":len(manifest["concepts"]),"entries":[],
                    "outcomeCounts":_semantics.processing_reconciliation(len(manifest["concepts"]),payload["records"],payload["coverage"]["entries"],scope_id=None)["outcomeCounts"]}
            accepted=[]
            for record in payload["records"]:
                record["businessApproval"] = ("unreviewed" if record.get("support")=="conflicted" else "approved") if decision=="approve" else "rejected"
                record["approvalScope"]="knowledge_statement_only"
                accepted.append(_semantics.seal_record(record))
            replacements={r["id"] for r in accepted}
            entries=payload["coverage"].pop("entries")
            payload["coverage"].update(sourceCandidates=copy.deepcopy(original_coverage.get("sourceCandidates",original_coverage)),
                                      reviewAccepted=len(accepted),previousReviewInvalidated=len(removed))
            if original_coverage.get("processingContract") or payload["coverage"].get("processingContract"):
                current_scopes=payload["coverage"].get("processingScopes",[])
                scopes={s["scopeId"]:s for s in original_coverage.get("processingScopes",[])+current_scopes}
                payload["coverage"].update(processingContract=True,processingScopes=list(scopes.values()))
                if not original_coverage.get("processingContract") or not current_scopes:
                    payload["coverage"]["processingPriorScopeUnknown"]=True
                def prior_processing():
                    with open_reader(workspace,source_snapshot_id,business_snapshot_id,business_digest)as old:yield from _all_processing(old)
                payload["priorProcessing"]=prior_processing
                entries=[{**e,"processingScopeId":payload["coverage"].get("processingScopeId")}for e in entries]
            # The complete base is streamed from the pinned disk reader. Only
            # the bounded explicit review request is retained in memory.
            def events():
                with open_reader(workspace,source_snapshot_id,business_snapshot_id,business_digest) as old:
                    for row in old.iter_records():
                        if row["id"] not in replacements and row.get("reviewedMeaning")!="declared_attestation": yield row,None
                    for entry in _all_entries(old): yield None,entry
                for row in accepted: yield row,None
                for entry in entries: yield None,entry
                for rid in removed: yield None,{"recordId":rid,"status":"invalidated","reason":"review_layer_replaced",**({"processingScopeId":payload["coverage"].get("processingScopeId",original_coverage.get("processingScopeId"))}if payload["coverage"].get("processingContract")else{})}
            payload["events"]=events()
            receipt=_receipt(workspace,source_snapshot_id,"review_"+decision,access,
                reviewManifestDigest=payload["reviewManifestDigest"], selectedCount=len(manifest["concepts"]),
                acceptedCount=len(accepted),invalidatedClaimIds=removed,approvalIsNotSourceValidation=True)
            return _publish(workspace,reader,payload,receipt,previous,access,cancel=cancel)


def revoke(workspace, source_snapshot_id, business_snapshot_id, business_digest, claim_ids, *, reason="operator_revocation", cancel=None):
    workspace = _workspace(workspace)
    if type(claim_ids) is not list or not 1 <= len(claim_ids) <= 10000 or any(type(x) is not str for x in claim_ids) or len(set(claim_ids)) != len(claim_ids):
        raise BusinessStoreError("revoke_selection_invalid")
    if type(reason) is not str or not re.fullmatch(r"[a-z_]{1,100}",reason): raise BusinessStoreError("revoke_reason_invalid")
    access=_authorize(workspace,"manage_knowledge",source_snapshot_id)
    with _source._lock(workspace):
        previous=_state(workspace)
        with open_reader(workspace,source_snapshot_id,business_snapshot_id,business_digest) as old:
            coverage=copy.deepcopy(old.metadata["coverage"])
            current_diagnostics=copy.deepcopy(old.metadata.get("currentReviewDiagnostics"))
            current_review_digest=old.metadata.get("reviewManifestDigest")
            if any(old.get_record(rid) is None for rid in claim_ids): raise BusinessStoreError("revoke_claim_missing")
            # Automatic source candidates have no concept references. The
            # explicit review layer remains bounded by its existing 10000 cap.
            relations=[]
            for row in old.iter_records():
                targets=_semantics.concept_targets(row)
                if targets: relations.append((row["id"],targets))
                if len(relations)>10000: raise BusinessStoreError("review_layer_budget")
        revoked=set(claim_ids)
        changed=True
        while changed:
            changed=False
            for rid,targets in relations:
                if rid not in revoked and any(t in revoked for t in targets): revoked.add(rid);changed=True
        coverage.pop("entries",None)
        coverage.update(state="PARTIAL",semanticCompleteness="PARTIAL",revoked=len(revoked))
        def prior_processing():
            with open_reader(workspace,source_snapshot_id,business_snapshot_id,business_digest)as old:yield from _all_processing(old)
        def events():
            with open_reader(workspace,source_snapshot_id,business_snapshot_id,business_digest) as old:
                for row in old.iter_records():
                    if row["id"] in revoked:
                        row.update(support="revoked",businessApproval="revoked")
                        row.pop("approvalReceiptId",None)
                        row["limitations"]=[*row["limitations"],"knowledge_approval_revoked"]
                        row=_semantics.seal_record(row)
                    yield row,None
                for entry in _all_entries(old): yield None,entry
            for rid in sorted(revoked): yield None,{"recordId":rid,"status":"revoked","reason":reason,**({"processingScopeId":coverage.get("processingScopeId")}if coverage.get("processingContract")else{})}
        with _source.open_reader(workspace,source_snapshot_id) as reader:
            receipt=_receipt(workspace,source_snapshot_id,"revoke",access,reason=reason,
                selectedCount=len(claim_ids),invalidatedClaimIds=sorted(revoked),offlineCopiesRevoked=False)
            payload={"events":events(),"coverage":coverage,"priorProcessing":prior_processing,"reviewManifestDigest":current_review_digest}
            if current_diagnostics is not None:payload["currentReviewDiagnostics"]=current_diagnostics
            return _publish(workspace,reader,payload,receipt,previous,access,cancel=cancel)


class BusinessReader:
    def __init__(self, workspace, source_snapshot_id, business_snapshot_id, business_digest, *, resource_policy=None):
        _reader_resource_policy(resource_policy);self.resource_policy=resource_policy
        self.workspace = _workspace(workspace)
        if type(business_snapshot_id) is not str or not ID.fullmatch(business_snapshot_id) or type(business_digest) is not str or not HASH.fullmatch(business_digest):
            raise BusinessStoreError("business_pin_required")
        self.source_snapshot_id, self.business_snapshot_id, self.business_digest = source_snapshot_id, business_snapshot_id, business_digest
        self.access = _authorize(self.workspace, "read_policy", source_snapshot_id)
        self.source_reader = None
        self.opened = False

    def __enter__(self):
        self.source_reader = (_source.open_reader(self.workspace,self.source_snapshot_id,resource_policy=self.resource_policy)
            if self.resource_policy is not None else _source.open_reader(self.workspace, self.source_snapshot_id))
        self.source_reader.__enter__()
        try:
            self.pointer = _state(self.workspace)
            if not self.pointer or self.pointer["businessSnapshotId"] != self.business_snapshot_id or self.pointer["businessDigest"] != self.business_digest:
                raise BusinessStoreError("business_snapshot_not_current")
            _source_current(self.workspace, self.source_snapshot_id)
            self.directory = self.workspace / "business-snapshots" / self.business_snapshot_id
            _private_directory(self.directory.parent)
            _private_directory(self.directory)
            manifest_identity=self._identity(self.directory/"manifest.json")
            if self.resource_policy is not None and manifest_identity[3]>BOUNDED_METADATA_BYTES:
                failure=BusinessStoreError("business_partitioned_metadata_budget")
                failure.selected="UNKNOWN"
                failure.report={"status":"BLOCKED","reason":failure.code,"selectedRecords":"UNKNOWN",
                    "projectedRecords":0,"spooledRecords":0,"parityVerifiedRecords":0,"selectionTraversal":"INCOMPLETE",
                    "wholeBusinessCompleteness":"UNKNOWN","storageRequirement":"schema2_partitioned_manifest_at_most_32MiB",
                    "alternatives":["ordinary_policy_projection_if_at_most_10000","manager_explicit_partitioned_business_build"]}
                raise failure
            self.metadata, raw = _read(self.directory/"manifest.json", self.workspace,
                BOUNDED_METADATA_BYTES if self.resource_policy is not None else MAX_BYTES)
            if self._identity(self.directory/"manifest.json")!=manifest_identity:raise BusinessStoreError("pinned_business_snapshot_changed")
            manifest = self.metadata
            if manifest.get("businessDigest") != self.business_digest or _semantics.digest({k:v for k,v in manifest.items() if k != "businessDigest"}) != self.business_digest:
                raise BusinessStoreError("business_manifest_integrity")
            for key,value in {**_pins(self.source_reader), **_spec}.items():
                if _semantics.canonical(manifest.get(key)) != _semantics.canonical(value): raise BusinessStoreError("business_source_or_spec_stale")
            if self.resource_policy is not None and manifest.get("schemaVersion")!=2:
                failure=BusinessStoreError("business_partitioned_storage_required")
                failure.selected=manifest.get("recordCount") if type(manifest.get("recordCount"))is int else "UNKNOWN"
                failure.report={"status":"BLOCKED","reason":failure.code,"selectedRecords":failure.selected,
                    "projectedRecords":0,"spooledRecords":0,"parityVerifiedRecords":0,"selectionTraversal":"INCOMPLETE",
                    "wholeBusinessCompleteness":"UNKNOWN","storageRequirement":"schema2_partitioned",
                    "alternatives":["ordinary_policy_projection_if_at_most_10000","manager_explicit_partitioned_business_build"]}
                raise failure
            _semantics.validate_review_diagnostics(manifest.get("currentReviewDiagnostics"), self.source_reader,
                                                   _pins(self.source_reader), manifest.get("reviewManifestDigest"))
            self.file_digests = {"manifest.json": hashlib.sha256(raw).hexdigest()}
            if manifest.get("schemaVersion")==2:
                self._open_partitioned(manifest)
            elif manifest.get("schemaVersion")==1:
                artifacts = {}
                if set(manifest.get("artifacts", {})) != {"records.json", "coverage.json", "receipt.json"}:
                    raise BusinessStoreError("business_artifact_manifest_invalid")
                for name,expected in manifest["artifacts"].items():
                    value, raw = _read(self.directory/name, self.workspace)
                    if hashlib.sha256(raw).hexdigest() != expected: raise BusinessStoreError("business_artifact_integrity")
                    self.file_digests[name] = expected; artifacts[name] = value
                self.rows, self.report = artifacts["records.json"], artifacts["coverage.json"]
                if type(self.rows) is not list or len(self.rows) != manifest.get("recordCount") or _semantics.canonical(self.report) != _semantics.canonical(manifest["coverage"]):
                    raise BusinessStoreError("business_inventory_mismatch")
                self.index = {}
                for record in self.rows:
                    if type(record) is not dict or record.get("id") in self.index or _semantics.canonical(record) != _semantics.canonical(_semantics.seal_record(record)):
                        raise BusinessStoreError("business_record_integrity")
                    self._index_fields(record)
                    _semantics.validate_record_values(record)
                    self.index[record["id"]] = record
            else: raise BusinessStoreError("business_manifest_version")
            self.identities = self.verified_identities if hasattr(self,"verified_identities") else {name:self._identity(self.directory/name) for name in self.file_digests}
            self.identities["manifest.json"]=manifest_identity
            self.opened = True
            self._stable()
            # A failed reader never commits pending validation metadata.
            if manifest.get("schemaVersion")==2:
                with _INDEX_CACHE_LOCK:
                    for key in self._pending_index_cache:
                        _INDEX_CACHE[key]=None;_INDEX_CACHE.move_to_end(key)
                    while len(_INDEX_CACHE)>_INDEX_CACHE_LIMIT:_INDEX_CACHE.popitem(last=False)
                self._pending_index_cache.clear()
            return self
        except BaseException:
            self.source_reader.__exit__(None, None, None)
            self.source_reader = None
            raise

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.opened: self._stable()
        finally:
            self.opened = False
            if self.source_reader: self.source_reader.__exit__(exc_type, exc, tb)

    def _stable(self):
        if not self.opened: raise BusinessStoreError("business_reader_not_open")
        self.source_reader._stable()
        if _state(self.workspace) != self.pointer: raise BusinessStoreError("business_pointer_changed")
        _source_current(self.workspace, self.source_snapshot_id)
        _same_access(self.workspace, "read_policy", self.source_snapshot_id, self.access)
        _source._ancestors(self.workspace, self.directory/"manifest.json")
        for name, expected in self.identities.items():
            if self._identity(self.directory/name) != expected: raise BusinessStoreError("pinned_business_snapshot_changed")
            if os.name == "nt": _source._private_file(self.directory/name)

    def _open_partitioned(self,manifest):
        storage=manifest.get("storage",{})
        if (type(storage) is not dict or set(storage)!={"format","chunkRecordLimit","artifactByteLimit","shards"}
                or storage["format"]!="sqlite-shards-v2" or type(storage["chunkRecordLimit"]) is not int
                or not 1<=storage["chunkRecordLimit"]<=10000 or storage["artifactByteLimit"]!=MAX_BYTES
                or type(storage["shards"]) is not list): raise BusinessStoreError("business_storage_invalid")
        self._pending_index_cache=OrderedDict()
        self.shards=storage["shards"]
        names={"coverage.json","receipt.json"}
        totals={"records":0,"entries":0,"processing":0};last={key:None for key in totals}
        for shard in self.shards:
            if (type(shard) is not dict or set(shard)!={"name","table","count","first","last","bytes"}
                    or type(shard["name"]) is not str or not re.fullmatch(r"(?:records|coverage|processing)-[0-9]{6}\.sqlite",shard["name"])
                    or shard["name"] in names or shard["table"] not in totals
                    or type(shard["count"]) is not int or not 1<=shard["count"]<=storage["chunkRecordLimit"]
                    or type(shard["bytes"]) is not int or not 0<shard["bytes"]<=MAX_BYTES):
                raise BusinessStoreError("business_storage_invalid")
            table=shard["table"];first,end=shard["first"],shard["last"]
            if table=="records":
                if any(type(x) is not str or not re.fullmatch(r"business:[0-9a-f]{64}",x) for x in (first,end)):
                    raise BusinessStoreError("business_storage_invalid")
            elif any(type(x) is not int or x<0 for x in (first,end)):
                raise BusinessStoreError("business_storage_invalid")
            if first>end or last[table] is not None and first<=last[table]:raise BusinessStoreError("business_storage_order")
            last[table]=end;totals[table]+=shard["count"];names.add(shard["name"])
        if set(manifest.get("artifacts",{}))!=names: raise BusinessStoreError("business_artifact_manifest_invalid")
        self.verified_identities={}
        for name,expected in manifest["artifacts"].items():
            if type(expected) is not str or not HASH.fullmatch(expected):raise BusinessStoreError("business_artifact_manifest_invalid")
            path=self.directory/name
            identity=self._identity(path)
            if name.endswith(".sqlite"):
                digest,size,_=_source._hash_file(path)
                if size>MAX_BYTES or digest!=expected:raise BusinessStoreError("business_artifact_integrity")
            else:
                value,raw=_read(path,self.workspace)
                if hashlib.sha256(raw).hexdigest()!=expected:raise BusinessStoreError("business_artifact_integrity")
                if name=="coverage.json":self.report=value
            if self._identity(path)!=identity:raise BusinessStoreError("pinned_business_snapshot_changed")
            self.verified_identities[name]=identity
            self.file_digests[name]=expected
        if totals["records"]!=manifest.get("recordCount") or totals["entries"]!=self.report.get("entryCount") or _semantics.canonical(self.report)!=_semantics.canonical(manifest.get("coverage")):
            raise BusinessStoreError("business_inventory_mismatch")
        if totals["processing"]!=self.report.get("processingEntryCount",0) or totals["processing"] and self.report.get("processingContract")is not True:
            raise BusinessStoreError("business_processing_inventory_mismatch")
        if totals["records"]>self.source_reader.config["budgets"]["max_records"]:
            raise BusinessStoreError("business_record_budget")
        if sum((self.directory/name).stat().st_size for name in names|{"manifest.json"})>self.source_reader.config["budgets"]["max_output_bytes"]:
            raise BusinessStoreError("business_output_budget")
        for shard in self.shards:
            with self._shard(shard) as db:
                table=shard["table"];key="id" if table=="records" else "position"
                count,first,end=db.execute("SELECT count(*),min("+key+"),max("+key+") FROM "+table).fetchone()
                if (count,first,end)!=(shard["count"],shard["first"],shard["last"]):raise BusinessStoreError("business_inventory_mismatch")
                if (self.directory/shard["name"]).stat().st_size!=shard["bytes"]:raise BusinessStoreError("business_inventory_mismatch")
                if table=="records":self._verify_index_coherence(shard,db)

    @contextmanager
    def _shard(self,shard):
        db=None
        try:
            db=_database(self.directory/shard["name"],readonly=True,resource_policy=self.resource_policy)
            expected=_RECORD_SQL if shard["table"]=="records" else _PROCESSING_SQL if shard["table"]=="processing"else _ENTRY_SQL
            schema=db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
            if schema!=[("table",shard["table"],expected)]:raise BusinessStoreError("business_database_schema")
            yield db
        except sqlite3.DatabaseError:
            raise BusinessStoreError("business_database_integrity") from None
        finally:
            if db is not None:db.close()

    @staticmethod
    def _index_fields(record):
        """Exact canonical concept identity and the four SQL selector columns."""
        try:
            if type(record) is not dict:raise BusinessStoreError("business_index_payload_mismatch")
            rid=record.get("id");kind=record.get("kind")
            if type(rid) is not str or not re.fullmatch(r"business:[0-9a-f]{64}",rid):
                raise BusinessStoreError("business_index_payload_mismatch")
            for name in ("namespace","domain","conceptKey","name"):
                _semantics._text(record.get(name))
            if kind not in _semantics.KINDS or type(kind) is not str:
                raise BusinessStoreError("business_index_payload_mismatch")
            expected=_semantics.concept_id(record["namespace"],record["domain"],kind,record["conceptKey"])
            if rid!=expected:raise BusinessStoreError("business_index_payload_mismatch")
            return rid,kind,record["name"].casefold(),record["domain"]
        except (TypeError,ValueError,KeyError,RecursionError):
            raise BusinessStoreError("business_index_payload_mismatch") from None

    @staticmethod
    def _index_json(encoded):
        # JSON is parsed once per uncached shard, one bounded record at a time.
        # This checks the unchanged JSON structural caps without hashing,
        # encoding or applying the full privacy/semantic record projection.
        def pairs(items):
            value={}
            for key,item in items:
                if key in value:raise BusinessStoreError("business_index_json_invalid")
                value[key]=item
            return value
        def constant(_):raise BusinessStoreError("business_index_json_invalid")
        nodes=[0]
        def bounds(value,depth=0):
            nodes[0]+=1
            if nodes[0]>2000000 or depth>32:raise BusinessStoreError("business_index_json_invalid")
            if type(value) is dict:
                for key,item in value.items():
                    if type(key) is not str or len(key)>512:raise BusinessStoreError("business_index_json_invalid")
                    key.encode("utf-8");bounds(item,depth+1)
            elif type(value) is list:
                for item in value:bounds(item,depth+1)
            elif type(value) is str:
                if len(value)>131072:raise BusinessStoreError("business_index_json_invalid")
                value.encode("utf-8")
            elif type(value) is float:
                if not math.isfinite(value):raise BusinessStoreError("business_index_json_invalid")
            elif value is not None and type(value) not in (bool,int):
                raise BusinessStoreError("business_index_json_invalid")
        try:
            if type(encoded) is not str or len(encoded)>_semantics.MAX_BYTES or len(encoded.encode("utf-8"))>_semantics.MAX_BYTES:
                raise BusinessStoreError("business_index_json_invalid")
            value=json.loads(encoded,object_pairs_hook=pairs,parse_constant=constant)
            bounds(value)
            return value
        except (ValueError,UnicodeError,OverflowError,RecursionError):
            raise BusinessStoreError("business_index_json_invalid") from None

    def _verify_index_coherence(self,shard,db):
        """Reject hidden selector errors before totals or filters are trusted.

        Only successful metadata is cached. No record values enter this
        process-local LRU. Full artifact hashing and stable identities remain
        mandatory on every open/operation, including cache hits.
        """
        name=shard["name"];path=self.directory/name
        expected=self.verified_identities[name]
        cache_key=(str(self.workspace),str(path),expected,self.file_digests[name],
                   _RECORD_SQL,self.metadata["schemaVersion"],self.metadata["businessSpecId"],
                   self.metadata["businessSpecHash"],_INDEX_COHERENCE_VERSION)
        if self._identity(path)!=expected:raise BusinessStoreError("pinned_business_snapshot_changed")
        with _INDEX_CACHE_LOCK:
            cached=cache_key in _INDEX_CACHE
            if cached:_INDEX_CACHE.move_to_end(cache_key)
        if cached:return
        cursor=db.execute("SELECT id,kind,namekey,domain,payload FROM records ORDER BY id")
        for indexed in cursor:
            if any(type(value) is not str for value in indexed):raise BusinessStoreError("business_index_payload_mismatch")
            record=self._index_json(indexed[4])
            if indexed[:4]!=self._index_fields(record):raise BusinessStoreError("business_index_payload_mismatch")
        if self._identity(path)!=expected:raise BusinessStoreError("pinned_business_snapshot_changed")
        self._pending_index_cache[cache_key]=None
        while len(self._pending_index_cache)>_INDEX_CACHE_LIMIT:self._pending_index_cache.popitem(last=False)

    def _decode_indexed(self,indexed):
        if len(indexed)!=5 or any(type(value) is not str for value in indexed):
            raise BusinessStoreError("business_index_payload_mismatch")
        record=self._decode(indexed[4])
        if indexed[:4]!=self._index_fields(record):raise BusinessStoreError("business_index_payload_mismatch")
        return record

    def _decode(self,encoded):
        record=_semantics.loads(encoded)
        if (type(record) is not dict or type(record.get("id")) is not str or record.get("kind") not in _semantics.KINDS
                or _semantics.canonical(record)!=_semantics.canonical(_semantics.seal_record(record))):
            raise BusinessStoreError("business_record_integrity")
        self._index_fields(record)
        _semantics.validate_record_values(record)
        _safe(record)
        return record

    def _where(self,kind=None,term="",domain=None,record_ids=None):
        clauses=[];args=[]
        for column,value in (("kind",kind),("domain",domain)):
            if value is not None:clauses.append(column+"=?");args.append(value)
        if term:clauses.append("instr(namekey,?)>0");args.append(term.casefold())
        if record_ids is not None:
            clauses.append("id IN ("+",".join("?" for _ in record_ids)+")");args.extend(record_ids)
        return (" WHERE "+" AND ".join(clauses) if clauses else ""),args

    def _query_partitioned(self,*,kind,term,offset,limit,domain,record_ids):
        expression,args=self._where(kind,term,domain,record_ids)
        total=0;remaining=offset;records=[]
        for shard in self.shards:
            if shard["table"]!="records":continue
            self._stable()
            with self._shard(shard) as db:
                count=db.execute("SELECT count(*) FROM records"+expression,args).fetchone()[0];total+=count
                if remaining>=count:remaining-=count;continue
                if len(records)<limit:
                    rows=db.execute("SELECT id,kind,namekey,domain,payload FROM records"+expression+" ORDER BY id LIMIT ? OFFSET ?",(*args,limit-len(records),remaining))
                    records.extend(self._decode_indexed(row) for row in rows)
                    remaining=0
        next_offset=offset+len(records) if offset+len(records)<total else None
        result={**self._pins(),"records":records,"total":total,"offset":offset,"returned":len(records),
            "truncated":next_offset is not None,"nextOffset":next_offset,"coverage":copy.deepcopy(self.report),
            "queryDigest":_semantics.digest([self._pins(),kind,term,domain,sorted(record_ids) if record_ids else None])}
        _safe(result);self._stable();return result

    def _get_partitioned(self,record_id):
        self._stable();result=None
        for shard in self.shards:
            if shard["table"]!="records" or not shard["first"]<=record_id<=shard["last"]:continue
            with self._shard(shard) as db:
                row=db.execute("SELECT id,kind,namekey,domain,payload FROM records WHERE id=?",(record_id,)).fetchone()
                if row:result=self._decode_indexed(row)
            break
        self._stable();return result

    def _iter_partitioned(self,*,kind=None,domain=None,page_size=100):
        expression,args=self._where(kind=kind,domain=domain)
        for shard in self.shards:
            if shard["table"]!="records":continue
            self._stable()
            with self._shard(shard) as db:
                cursor=db.execute("SELECT id,kind,namekey,domain,payload FROM records"+expression+" ORDER BY id",args)
                while True:
                    self._stable();rows=cursor.fetchmany(page_size)
                    if not rows:break
                    for row in rows:yield self._decode_indexed(row)
            self._stable()

    def _coverage_partitioned(self,offset,limit):
        remaining=offset;entries=[];total=self.report["entryCount"]
        for shard in self.shards:
            if shard["table"]!="entries":continue
            if remaining>=shard["count"]:remaining-=shard["count"];continue
            with self._shard(shard) as db:
                rows=db.execute("SELECT payload FROM entries ORDER BY position LIMIT ? OFFSET ?",(limit-len(entries),remaining))
                for row in rows:
                    value=_semantics.loads(row[0]);_safe(value);entries.append(value)
            remaining=0
            if len(entries)==limit:break
        next_offset=offset+len(entries) if offset+len(entries)<total else None
        result={**self._pins(),"summary":{k:copy.deepcopy(v) for k,v in self.report.items() if k!="entries"},
            "entries":entries,"total":total,"offset":offset,"returned":len(entries),"truncated":next_offset is not None,
            "nextOffset":next_offset,"queryDigest":_semantics.digest([self._pins(),"coverage"])}
        _safe(result);self._stable();return result

    @staticmethod
    def _identity(path):
        info=path.lstat()
        _guard._check_private_file_metadata(info)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info,"st_file_attributes",0)&0x400:
            raise BusinessStoreError("business_file_boundary")
        return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_nlink)

    def _pins(self):
        return {k: self.metadata[k] for k in (*_semantics.PIN_KEYS, "businessSnapshotId", "businessDigest", "businessSpecId", "businessSpecHash")}

    def query(self, *, kind=None, term="", offset=0, limit=50, domain=None, record_ids=None):
        self._stable()
        if type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 200 or type(term) is not str or len(term)>200:
            raise BusinessStoreError("business_query_budget")
        if kind is not None and kind not in _semantics.KINDS: raise BusinessStoreError("business_query_kind")
        if domain is not None and (type(domain) is not str or not 1 <= len(domain) <= 120): raise BusinessStoreError("business_query_domain")
        if record_ids is not None and (type(record_ids) is not list or not 1<=len(record_ids)<=100 or any(type(x) is not str for x in record_ids) or len(set(record_ids)) != len(record_ids)):
            raise BusinessStoreError("business_query_ids")
        if self.metadata.get("schemaVersion")==2:
            return self._query_partitioned(kind=kind,term=term,offset=offset,limit=limit,domain=domain,record_ids=record_ids)
        selected = [r for r in self.rows if (kind is None or r["kind"]==kind) and (domain is None or r["domain"]==domain)
                    and (not term or term.casefold() in r["name"].casefold()) and (record_ids is None or r["id"] in record_ids)]
        selected.sort(key=lambda r:r["id"])
        rows = copy.deepcopy(selected[offset:offset+limit]); total=len(selected); next_offset=offset+len(rows) if offset+len(rows)<total else None
        result = {**self._pins(), "records": rows, "total": total, "offset": offset, "returned": len(rows),
                  "truncated": next_offset is not None, "nextOffset": next_offset, "coverage": copy.deepcopy(self.report),
                  "queryDigest": _semantics.digest([self._pins(),kind,term,domain,sorted(record_ids) if record_ids else None])}
        _safe(result); self._stable()
        return result

    def get_record(self, record_id):
        if type(record_id) is not str or not 1 <= len(record_id) <= 256: raise BusinessStoreError("business_record_selector")
        if self.metadata.get("schemaVersion")==2:
            return self._get_partitioned(record_id)
        self._stable(); result=copy.deepcopy(self.index.get(record_id)); _safe(result); self._stable(); return result

    def iter_records(self, *, kind=None, domain=None, page_size=100):
        if self.metadata.get("schemaVersion")==2:
            if type(page_size) is not int or not 1<=page_size<=200: raise BusinessStoreError("business_query_budget")
            self.query(kind=kind,domain=domain,limit=1)
            yield from self._iter_partitioned(kind=kind,domain=domain,page_size=page_size)
            return
        offset=0
        while True:
            page=self.query(kind=kind,domain=domain,offset=offset,limit=page_size)
            yield from page["records"]
            if page["nextOffset"] is None: return
            offset=page["nextOffset"]

    def coverage(self, offset=0, limit=50):
        self._stable()
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100: raise BusinessStoreError("business_coverage_page")
        if self.metadata.get("schemaVersion")==2:
            return self._coverage_partitioned(offset,limit)
        entries=self.report.get("entries",[]); rows=copy.deepcopy(entries[offset:offset+limit]); total=len(entries)
        next_offset=offset+len(rows) if offset+len(rows)<total else None
        result={**self._pins(),"summary":{k:v for k,v in self.report.items() if k!="entries"},"entries":rows,"total":total,
                "offset":offset,"returned":len(rows),"truncated":next_offset is not None,"nextOffset":next_offset,
                "queryDigest":_semantics.digest([self._pins(),"coverage"])}
        _safe(result);self._stable();return result

    def processing(self,offset=0,limit=50):
        """Opt-in original input outcomes; lifecycle events are a separate class."""
        self._stable()
        if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=100:raise BusinessStoreError("business_coverage_page")
        total=self.report.get("processingEntryCount",0);remaining=offset;entries=[]
        for shard in getattr(self,"shards",[]):
            if shard["table"]!="processing":continue
            if remaining>=shard["count"]:remaining-=shard["count"];continue
            with self._shard(shard)as db:
                for(row,)in db.execute("SELECT payload FROM processing ORDER BY position LIMIT ? OFFSET ?",(limit-len(entries),remaining)):
                    value=_semantics.loads(row);_safe(value);entries.append(value)
            remaining=0
            if len(entries)==limit:break
        next_offset=offset+len(entries)if offset+len(entries)<total else None
        summary={"scope":"original_selected_inputs","processingContract":self.report.get("processingContract")is True,
            "processingScopes":copy.deepcopy(self.report.get("processingScopeCounts",[])),
            "outcomeCounts":copy.deepcopy(self.report.get("processingOutcomeCounts",{})),
            "reconciled":self.report.get("processingReconciled",False)and not self.report.get("processingPriorScopeUnknown",False),
            "globalCompleteness":"UNKNOWN","priorScope":"UNKNOWN"if self.report.get("processingPriorScopeUnknown")or not self.report.get("processingContract")else"explicit"}
        result={**self._pins(),"summary":summary,"entries":entries,"total":total if self.report.get("processingContract")is True else None,"offset":offset,"returned":len(entries),
            "truncated":next_offset is not None,"nextOffset":next_offset,"queryDigest":_semantics.digest([self._pins(),"processing"])}
        _safe(result);self._stable();return result


def open_reader(workspace, source_snapshot_id, business_snapshot_id, business_digest, *, resource_policy=None):
    return BusinessReader(workspace, source_snapshot_id, business_snapshot_id, business_digest,resource_policy=resource_policy)


def unpublished_build_status(workspace, source_snapshot_id):
    """Read the last recorded failed build, never infer the latest operation.

    This diagnostic has a source-record progress denominator. It neither
    publishes an attempt nor attributes the failure to an unprocessed record.
    """
    workspace = _workspace(workspace)
    access = _authorize(workspace, "read_evidence", source_snapshot_id)
    base = {"schemaVersion": 1, "scope": "most_recent_recorded_unpublished_build",
            "publication": False, "wholeAttemptHistory": "UNKNOWN",
            "perInputFailureAttribution": "NOT_RECORDED", "sourceMeaning": "UNKNOWN"}
    path = workspace / "business-last-attempt.json"
    if not path.exists() and not path.is_symlink():
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "NOT_RECORDED"}
    try:
        value, raw = _read(path, workspace, 64 * 1024)
    except _guard.PrivacyError:
        raise
    except (ValueError, RuntimeError, OSError):
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "UNAVAILABLE", "reason": "native_receipt_boundary_or_encoding_invalid"}
    required = set(_semantics.PIN_KEYS) | {"schemaVersion", "status", "reason", "coverage", "previousBusinessSnapshotId"}
    if (type(value) is not dict or set(value) != required or type(value.get("schemaVersion")) is not int
            or value["schemaVersion"] != 1 or value.get("status") != "unpublished"
            or value.get("reason") not in ("build_failed", "cancelled")):
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "INVALID", "reason": "native_receipt_schema_invalid"}
    with _source.open_reader(workspace, source_snapshot_id) as reader:
        current = _pins(reader)
        source_records = reader.metadata.get("recordCount")
        if type(source_records) is not int or source_records < 0:
            raise BusinessStoreError("source_inventory_invalid")
    # A grant for S does not grant access to T. Do not return a digest of a
    # different snapshot's receipt, its pins/counts, or an old business ID.
    if any(value.get(key) != current[key] for key in _semantics.PIN_KEYS):
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "SOURCE_MISMATCH", "sourceSnapshotId": source_snapshot_id}
    coverage = value.get("coverage")
    allowed = {"state", "scope", "denominator", "numerator", "numeratorMeaning", "rejected", "omitted", "conflicted",
        "unknownDenominator", "semanticCompleteness", "globalCompleteness", "limitations", "processed", "visited",
        "unsupported", "storageCompleteness", "inventoryAccounting", "processingContract", "processingScopeId",
        "processingScopes", "sourceDeclarationCoverage", "sourceFunctionProcessing"}
    progress_keys = ("denominator", "processed", "visited", "omitted", "unsupported")
    valid = (type(coverage) is dict and set(coverage) <= allowed
        and all(type(coverage.get(key)) is int and coverage[key] >= 0 for key in progress_keys)
        and coverage.get("denominator") == source_records
        and coverage.get("scope") == "selected_source_snapshot_records"
        and coverage.get("state") == "PARTIAL" and coverage.get("storageCompleteness") == "UNPUBLISHED"
        and coverage.get("unknownDenominator") is False
        and coverage.get("inventoryAccounting") == "all_selected_records")
    if valid:
        valid = (coverage["unsupported"] <= coverage["processed"] <= coverage["visited"] <= source_records
            and coverage["omitted"] == source_records - coverage["processed"])
    parent = value.get("previousBusinessSnapshotId")
    valid = valid and (parent is None or type(parent) is str and ID.fullmatch(parent))
    processing = coverage.get("processingContract") if type(coverage) is dict else None
    if processing is not None:
        expected_scope = "processing:" + _semantics.digest(["source_inputs", current])
        valid = valid and processing is True and coverage.get("processingScopeId") == expected_scope
        valid = valid and coverage.get("processingScopes") == [{"scopeId": expected_scope,
            "denominator": source_records, "kind": "selected_source_snapshot_records"}]
    elif type(coverage) is dict and any(key in coverage for key in ("processingScopeId", "processingScopes")):
        valid = False
    if not valid:
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "INVALID", "reason": "native_receipt_progress_invalid"}
    import pipeline_policy
    try:
        function_progress = pipeline_policy.function_processing_summary(coverage.get("sourceFunctionProcessing"))
        pipeline_policy.declaration_coverage_summary(coverage.get("sourceDeclarationCoverage"))
    except pipeline_policy.PolicyError:
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "INVALID", "reason": "native_receipt_declaration_summary_invalid"}
    # The same private-file checks and current privacy policy apply again at
    # the use boundary. A concurrent replacement cannot be returned as stable.
    again, again_raw = _read(path, workspace, 64 * 1024)
    if again_raw != raw:
        _same_access(workspace, "read_evidence", source_snapshot_id, access)
        return {**base, "state": "UNAVAILABLE", "reason": "native_receipt_changed"}
    result = {**base, "state": "RECORDED_UNPUBLISHED", **current,
        "reason": value["reason"],
        "progress": {key: coverage[key] for key in progress_keys},
        "progressMeaning": "source_record_progress_before_unpublished_failure_not_published_success",
        "processingScopeId": coverage.get("processingScopeId"), "sourceFunctionProcessing": function_progress}
    _same_access(workspace, "read_evidence", source_snapshot_id, access)
    # Hidden receipt fields contribute neither an exported fingerprint nor a
    # parent relationship. Revalidate the whole native input at the last local
    # use boundary, while returning only the permitted structural diagnostic.
    _safe({"nativeReceipt": again, "response": result})
    return result


def status(workspace, source_snapshot_id=None, *, resource_policy=None):
    _reader_resource_policy(resource_policy)
    if resource_policy is not None and source_snapshot_id is None:raise BusinessStoreError("business_source_pin_required")
    workspace=_workspace(workspace)
    snapshot=source_snapshot_id or _source.status(workspace).get("snapshotId")
    _authorize(workspace,"read_policy",snapshot)
    pointer=_state(workspace)
    if not pointer: return {"status":"not_ready","sourceSnapshotId":snapshot,"businessSnapshotId":None,"businessCompletion":"UNKNOWN"}
    if pointer["sourceSnapshotId"] != snapshot:
        # Verify the selected sealed source without opening an incompatible
        # old business snapshot or exposing its identity under the new grant.
        with (_source.open_reader(workspace,snapshot,resource_policy=resource_policy) if resource_policy is not None else _source.open_reader(workspace, snapshot)):
            pass
        return {"status":"not_ready_for_selected_source", "sourceSnapshotId":snapshot,
                "businessSnapshotId":None, "businessCompletion":"UNKNOWN"}
    with open_reader(workspace,snapshot,pointer["businessSnapshotId"],pointer["businessDigest"],resource_policy=resource_policy) as reader:
        return _summary(reader.metadata)
