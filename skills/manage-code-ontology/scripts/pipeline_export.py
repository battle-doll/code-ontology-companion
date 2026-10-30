"""Private portable ontology export; no configuration, ACL or parse cache."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import time
import uuid
from pathlib import Path

import companion
import pipeline_acl
import pipeline_store


MAX_POLICY_BYTES = 64 * 1024 * 1024
MAX_INTERCHANGE_LINE = 4 * 1024 * 1024
INTERCHANGE_CHECK_BYTES = 64 * 1024
INTERCHANGE_CHECK_LINES = 128
INTERCHANGE_CHECK_SECONDS = 0.05


def _digest(path, checkpoint=lambda: None):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checkpoint()
            digest.update(block)
    return digest.hexdigest()


def _file(path, content):
    guard = companion.privacy_guard
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600), "wb") as handle:
        guard._check_private_file_metadata(os.fstat(handle.fileno()))
        if os.name == "nt":
            guard._windows_profile_security(handle.fileno())
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _private_file(path):
    guard = companion.privacy_guard
    before = path.lstat()
    guard._check_private_file_metadata(before)
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)), "rb") as handle:
        opened = os.fstat(handle.fileno())
        guard._check_private_file_metadata(opened)
        if not companion.core._same_file(before, opened):
            raise companion.CompanionError("Portable export file changed.")
        if os.name == "nt":
            guard._windows_profile_security(handle.fileno())


def _copy_interchange(original, target, info, *, profile, roots, checkpoint):
    """JSON has one bounded document; RDF remains streamed by bounded lines.

    Privacy inspection uses decoded JSON values, so JSON escapes and identities
    spanning copy blocks cannot evade it. Never split a logical RDF record just
    to satisfy the byte budget. All copied bytes retain the sealed artifact hash.
    """
    guard = companion.privacy_guard
    _private_file(original)
    if target.name == "policy.json":
        if type(info.get("bytes")) is not int or not 0 <= info["bytes"] <= MAX_POLICY_BYTES:
            raise companion.CompanionError("Portable policy document exceeds its byte budget.")
        # This is the same explicit document ceiling as the sealed store reader;
        # unlike the old 4 MiB line cap it permits a valid 10,000-rule document.
        raw = pipeline_store._read(original, MAX_POLICY_BYTES, roots[0])
        if len(raw) != info["bytes"] or hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise companion.CompanionError("Pinned interchange artifact changed.")
        checkpoint()
        policy = json.loads(raw)
        if not isinstance(policy, dict) or not isinstance(policy.get("rules"), list) or not isinstance(policy.get("evidence"), list) or len(policy["rules"]) > 10000 or len(policy["evidence"]) > 20000:
            raise companion.CompanionError("Portable policy document is invalid.")
        metadata = {key: value for key, value in policy.items() if key not in {"rules", "evidence"}}
        for collection in ((metadata,), policy["rules"], policy["evidence"]):
            for record in collection:
                checkpoint()
                if not isinstance(record, dict) or len(companion._json_bytes(record)) > MAX_INTERCHANGE_LINE:
                    raise companion.CompanionError("Portable policy record exceeds its byte budget.")
                guard.ensure_public_safe(record, profile=profile, context_roots=roots, require_profile=True)
        checkpoint()
        del policy, raw
    _file(target, b"")
    digest = hashlib.sha256()
    with original.open("rb") as source, target.open("ab") as sink:
        if target.name == "policy.json":
            while True:
                checkpoint()
                block = source.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                sink.write(block)
                sink.flush()
                checkpoint()
        else:
            # Every logical record is privacy checked. The heavier callback
            # revalidates fresh state at bounded I/O boundaries, never from a
            # cached authorization decision. A large record remains indivisible.
            checkpoint()
            checked_at = time.monotonic()
            pending_bytes = pending_lines = 0
            while True:
                block = source.readline(MAX_INTERCHANGE_LINE + 1)
                if not block:
                    break
                if len(block) > MAX_INTERCHANGE_LINE:
                    raise companion.CompanionError("Portable interchange record exceeds its budget.")
                if pending_bytes and pending_bytes + len(block) > INTERCHANGE_CHECK_BYTES:
                    sink.flush()
                    checkpoint()
                    checked_at = time.monotonic()
                    pending_bytes = pending_lines = 0
                guard.ensure_public_safe(block, profile=profile, context_roots=roots, require_profile=True)
                digest.update(block)
                sink.write(block)
                pending_bytes += len(block)
                pending_lines += 1
                if (pending_bytes >= INTERCHANGE_CHECK_BYTES or pending_lines >= INTERCHANGE_CHECK_LINES
                        or time.monotonic() - checked_at >= INTERCHANGE_CHECK_SECONDS):
                    sink.flush()
                    checkpoint()
                    checked_at = time.monotonic()
                    pending_bytes = pending_lines = 0
            # Includes empty input and an incomplete last batch. The clock is
            # cooperative: a blocking read or one privacy check is not preempted.
            sink.flush()
            checkpoint()
        os.fsync(sink.fileno())
    if digest.hexdigest() != info["sha256"] or target.stat().st_size != info["bytes"]:
        raise companion.CompanionError("Pinned interchange artifact changed.")


def export_bundle(workspace_path, snapshot_id, output_dir, *, max_output_bytes=1024 * 1024 * 1024, cancel=None, include_business=True, artifact_observer=None):
    if not isinstance(snapshot_id, str) or not pipeline_acl.SNAPSHOT.fullmatch(snapshot_id):
        raise companion.CompanionError("Provide a concrete sealed snapshot for portable export.")
    if type(include_business) is not bool:raise companion.CompanionError("Invalid portable business scope.")
    if artifact_observer is not None and (not callable(artifact_observer) or include_business):
        raise companion.CompanionError("Invalid portable observer scope.")
    actions = ("export_bundle", "read_structure", "read_policy", "read_evidence")
    permits = [pipeline_acl.authorize(workspace_path, action, snapshot_id) for action in actions]
    if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 8 * 1024 ** 3:
        raise companion.CompanionError("Invalid portable export budget.")
    workspace = Path(workspace_path).resolve(strict=True)
    output = Path(output_dir).expanduser()
    parent = companion._resolve_existing_dir(output.parent, "Export parent")
    parent_identity = parent.stat()
    output = parent / output.name
    if output.exists() or output.is_symlink() or companion.core._is_relative_to(output, workspace):
        raise companion.CompanionError("Choose a new portable export outside the private workspace.")
    guard = companion.privacy_guard
    profile = guard.load_profile((workspace, output), required=True)
    guard.ensure_public_safe("", profile=profile, require_profile=True)
    import pipeline_access
    business_metadata = pipeline_access.business_export_state(workspace, snapshot_id) if include_business else {"status":"not_included","businessCompletion":"UNKNOWN"}
    stage = parent / (".ontology-export-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    connection = None

    def checkpoint():
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
            raise companion.CompanionError("Portable export cancelled.")
        if sum(path.stat().st_size for path in stage.rglob("*") if path.is_file()) > max_output_bytes:
            raise companion.CompanionError("Portable export exceeds its byte budget.")

    try:
        with pipeline_store.open_reader(workspace, snapshot_id) as reader:
            checkpoint()
            database = stage / "knowledge.sqlite"
            _file(database, b"")
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("CREATE TABLE records(id TEXT PRIMARY KEY, kind TEXT NOT NULL, module TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX records_kind ON records(kind,id)")
            connection.execute("CREATE INDEX records_module ON records(module,id)")
            count = 0
            for row in reader.iter_records(page_size=100):
                checkpoint()
                guard.ensure_public_safe(row, profile=profile, context_roots=(workspace, output), require_profile=True)
                encoded = companion._json_bytes(row).decode("utf-8")
                connection.execute("INSERT INTO records VALUES(?,?,?,?,?)", (row["id"], row["kind"], row["module"], pipeline_store.indexed_record_name(row), encoded))
                count += 1
                if count % 100 == 0:
                    connection.commit()
            connection.commit()
            if count != reader.metadata["recordCount"]:
                raise companion.CompanionError("Portable record count does not match the pinned snapshot.")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise companion.CompanionError("Portable index integrity failed.")
            connection.close()
            connection = None
            for name in ("policy.json", "ontology.ttl", "lineage.ttl", "shapes.ttl") + (("coverage.json",) if "coverage.json" in reader.metadata["artifacts"] else ()):
                checkpoint()
                original = reader.directory / name
                info = reader.metadata["artifacts"][name]
                if info["bytes"] > max_output_bytes:
                    raise companion.CompanionError("Portable export exceeds its byte budget.")
                _copy_interchange(original, stage / name, info, profile=profile, roots=(workspace, output), checkpoint=checkpoint)
            remaining = max_output_bytes - sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
            business = pipeline_access.export_business_view(workspace, snapshot_id, business_metadata,
                stage / "business", max_output_bytes=remaining, profile=profile,
                profile_roots=(workspace, output), action="export_bundle", cancel=cancel) if include_business else {
                    "status":"not_included","businessCompletion":"UNKNOWN"}
            artifacts = {file.relative_to(stage).as_posix(): {"sha256": _digest(file, checkpoint), "bytes": file.stat().st_size}
                         for file in sorted(stage.rglob("*")) if file.is_file()}
            manifest = {"format": "code-ontology-bundle/1", "pluginVersion": "0.9.3", "developer": "battle-doll",
                "snapshotId": snapshot_id, "analysisSpecId": reader.metadata["analysisSpecId"],
                "sourceFingerprint": reader.metadata["sourceFingerprint"],
                "sourceLastVerifiedAt": reader.metadata["sourceLastVerifiedAt"],
                "createdAt": reader.metadata["createdAt"], "rulesetDigest": reader.metadata["rulesetDigest"],
                "coverage": reader.metadata["coverage"], "recordCount": count, "artifacts": artifacts,
                "businessScope":"included_if_available" if include_business else "explicit_source_only_bundle",
                "business": {key:business[key] for key in ("status", "pins", "recordCount", "outputBytes", "businessCompletion") if key in business},
                "access": "private_local_copy_permissions_do_not_travel", "sourceAccess": "not_read",
                "excluded": ["private_source_manifest", "parse_cache", "local_configuration", "access_policy", "resource_key"]}
            guard.ensure_public_safe(manifest, profile=profile, require_profile=True)
            manifest_raw=companion._json_bytes(manifest)
            _file(stage / "bundle.json", manifest_raw)
            if artifact_observer is not None:
                for name,info in artifacts.items():artifact_observer(name,info,(stage/name).lstat())
                artifact_observer("bundle.json",{"bytes":len(manifest_raw),"sha256":hashlib.sha256(manifest_raw).hexdigest()},(stage/"bundle.json").lstat())
            checkpoint()
            staged_identities = {path.relative_to(stage).as_posix(): companion.core._stable_file_metadata(path.lstat()) for path in stage.rglob("*") if path.is_file()}
        # The reader's final integrity check must succeed before any promotion.
        # Use the ACL writer's lock to serialize supported revocations with this
        # authorization/promotion boundary. Same-account arbitrary file mutation
        # is outside this local application boundary; offline copies are not revoked.
        with companion._snapshot_write_lock(workspace):
            checkpoint()
            for action, initial in zip(actions, permits):
                if pipeline_acl.authorize(workspace, action, snapshot_id) != initial:
                    raise companion.CompanionError("Export authorization changed.")
            if guard.load_profile((workspace, output), required=True) != profile:
                raise companion.CompanionError("Export privacy policy changed.")
            reader._stable()
            current_parent = companion._resolve_existing_dir(output.parent, "Export parent")
            if not companion.core._same_file(parent_identity, current_parent.stat()):
                raise companion.CompanionError("Export parent changed.")
            stage_info = stage.lstat()
            if companion._is_link_like(stage_info) or not stat.S_ISDIR(stage_info.st_mode) or (os.name != "nt" and (stage_info.st_mode & 0o077 or stage_info.st_uid != os.getuid())):
                raise companion.CompanionError("Portable export staging permissions changed.")
            if {file.relative_to(stage).as_posix() for file in stage.rglob("*") if file.is_file()} != set(staged_identities):
                raise companion.CompanionError("Portable export artifact set changed.")
            for file in stage.rglob("*"):
                info = file.lstat()
                if companion._is_link_like(info):
                    raise companion.CompanionError("Portable export linked entry.")
                if file.is_dir():
                    if os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
                        raise companion.CompanionError("Portable export directory permissions changed.")
                    continue
                _private_file(file)
                if companion.core._stable_file_metadata(info) != staged_identities[file.relative_to(stage).as_posix()]:
                    raise companion.CompanionError("Portable export artifact changed.")
            if output.exists() or output.is_symlink():
                raise companion.CompanionError("Export destination appeared concurrently.")
            checkpoint()
            pipeline_access.check_business_export(workspace, snapshot_id, business_metadata)
            reader._stable()
            checkpoint()
            for action, initial in zip(actions, permits):
                if pipeline_acl.authorize(workspace, action, snapshot_id) != initial:
                    raise companion.CompanionError("Export authorization changed.")
            if guard.load_profile((workspace, output), required=True) != profile:
                raise companion.CompanionError("Export privacy policy changed.")
            os.rename(stage, output)
            return {"status": "exported", "snapshotId": snapshot_id, "recordCount": count,
                    "outputDirectory": str(output), "manifest": "bundle.json", "sourceAccess": "not_read"}
    except companion.CompanionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, pipeline_store.PipelineError,
            pipeline_store.privacy_guard.PrivacyError, companion.privacy_guard.PrivacyError) as exc:
        code=getattr(exc,"code",None)
        if not include_business and type(code) is str and re.fullmatch("partitioned_[a-z_]{1,80}",code):raise
        raise companion.CompanionError("Portable export failed validation; no bundle was promoted.") from None
    finally:
        if connection is not None:
            connection.close()
        if stage.exists():
            shutil.rmtree(stage)
