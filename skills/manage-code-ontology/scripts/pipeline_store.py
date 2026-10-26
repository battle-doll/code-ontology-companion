"""Local, bounded SQLite pipeline with immutable, pinned, source-free reads.

One process publishes at a time. A durable receipt coordinates catalog, ledger
and snapshot files; this is recoverable coordination, not a multi-file atomic
transaction. Hashes provide integrity, not authentication against their owner.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import code_ontology_core as core
import pipeline_adapters as adapters
import privacy_guard

STORE_VERSION = "pipeline-store-1"
SNAPSHOT_RE = re.compile(r"ps-[0-9a-f]{32}\Z")
DEFAULT_BUDGETS = {"max_files": 25000, "max_total_bytes": 512 * 1024 * 1024,
                   "max_source_bytes": 2 * 1024 * 1024, "max_records": 500000,
                   "max_file_records": 20000, "max_ast_nodes": 20000, "max_depth": 64,
                   "max_run_seconds": 600, "max_output_bytes": 1024 * 1024 * 1024,
                   "max_policy_rules": 10000, "partition_count": 8, "workers": 1}
MAX_BUDGETS = {**DEFAULT_BUDGETS, "max_files": 250000, "max_total_bytes": 4 * 1024 ** 3,
               "max_records": 5000000, "max_output_bytes": 8 * 1024 ** 3, "max_run_seconds": 7200,
               "max_ast_nodes": 200000}
SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,digest TEXT NOT NULL,facts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,
 path TEXT NOT NULL,module TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS records_kind ON records(kind,id);
CREATE INDEX IF NOT EXISTS records_path ON records(path,id);
CREATE INDEX IF NOT EXISTS records_module ON records(module,id);
CREATE TABLE IF NOT EXISTS domains(id TEXT NOT NULL,domain TEXT NOT NULL,PRIMARY KEY(id,domain));
CREATE INDEX IF NOT EXISTS domain_name ON domains(domain,id);
"""


class PipelineError(RuntimeError):
    pass


class PipelineCancelled(PipelineError):
    pass


def _json(value: Any) -> bytes:
    return adapters.canonical(value)


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _checkpoint(stage: str) -> None:
    """Failure-injection seam; never executes target code."""


def _link(info: os.stat_result) -> bool:
    return core._is_link_like(info)


def _directory(path: str | Path) -> Path:
    p = Path(path).expanduser()
    try:
        info = p.lstat()
        if _link(info) or not stat.S_ISDIR(info.st_mode):
            raise PipelineError("directory_boundary_invalid")
        return p.resolve(strict=True)
    except OSError:
        raise PipelineError("directory_unavailable") from None


def _ancestors(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise PipelineError("path_outside_registered_root") from None
    current = root
    for part in relative.parts[:-1]:
        current /= part
        try:
            info = current.lstat()
        except OSError:
            raise PipelineError("ancestor_unavailable") from None
        if _link(info) or not stat.S_ISDIR(info.st_mode):
            raise PipelineError("linked_ancestor_forbidden")


def _read(path: Path, maximum: int, root: Path | None = None) -> bytes:
    if root is not None:
        _ancestors(root, path)
    try:
        before = path.lstat()
        if _link(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise PipelineError("file_boundary_or_budget_invalid")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if core._stable_file_metadata(before) != core._stable_file_metadata(opened) or not core._same_file(before, opened):
                raise PipelineError("file_changed_before_read")
            result = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
        current = path.lstat()
        if (len(result) > maximum or not core._same_file(after, current)
                or core._stable_file_metadata(before) != core._stable_file_metadata(after)
                or core._stable_file_metadata(after) != core._stable_file_metadata(current) or _link(current)):
            raise PipelineError("file_changed_during_read")
        if root is not None:
            _ancestors(root, path)
        return result
    except OSError:
        raise PipelineError("file_read_failed") from None


def _load(path: Path, maximum: int = 1024 * 1024, root: Path | None = None) -> dict[str, Any]:
    try:
        value = json.loads(_read(path, maximum, root))
    except (ValueError, UnicodeError, RecursionError):
        raise PipelineError("invalid_json_artifact") from None
    if not isinstance(value, dict):
        raise PipelineError("invalid_json_shape")
    return value


def _sync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(path: Path, value: Any) -> None:
    raw = value if isinstance(value, bytes) else _json(value)
    if path.exists() and (_link(path.lstat()) or not path.is_file() or path.stat().st_nlink != 1):
        raise PipelineError("write_destination_invalid")
    temporary = path.parent / (".tmp-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            _private_handle(handle.fileno())
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_dir(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextlib.contextmanager
def _atomic_text(path: Path):
    """Stream into an exclusive private file; never truncate a resumed link."""
    temporary = path.parent / (".tmp-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            _private_handle(handle.fileno())
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if _link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PipelineError("write_destination_invalid")
        os.replace(temporary, path)
        _sync_dir(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mkdir(parent: Path, name: str) -> Path:
    path = parent / name
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    if _directory(path).parent != parent:
        raise PipelineError("managed_directory_invalid")
    return path


def _config(workspace_path: str | Path) -> tuple[Path, dict[str, Any]]:
    workspace = _directory(workspace_path)
    if os.name != "nt" and (workspace.stat().st_mode & 0o077 or workspace.stat().st_uid != os.getuid()):
        raise PipelineError("workspace_permissions_invalid")
    _private_file(workspace / "pipeline.json")
    _private_file(workspace / ".resource-key")
    config = _load(workspace / "pipeline.json", root=workspace)
    if (config.get("schemaVersion") != 1 or config.get("mode") != "pipeline"
            or not re.fullmatch(r"pw-[a-f0-9]{32}", str(config.get("workspaceId", "")))
            or not isinstance(config.get("sourceRoots"), list)
            or any(not isinstance(x, str) or (x != "." and not core._portable_relative_path(x)) for x in config["sourceRoots"])
            or not isinstance(config.get("repositoryRoot"), str)
            or not isinstance(config.get("budgets"), dict)):
        raise PipelineError("not_a_pipeline_workspace")
    if _budgets(config["budgets"]) != config["budgets"]:
        raise PipelineError("workspace_budget_invalid")
    return workspace, config


def _private_handle(fd: int) -> None:
    privacy_guard._check_private_file_metadata(os.fstat(fd))
    if os.name == "nt":
        privacy_guard._windows_profile_security(fd)


def _private_file(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        try:
            _private_handle(fd)
            if not core._same_file(os.fstat(fd), path.lstat()) or _link(path.lstat()):
                raise PipelineError("private_file_changed")
        finally:
            os.close(fd)
    except OSError:
        raise PipelineError("private_file_unavailable") from None


@contextlib.contextmanager
def _lock(workspace: Path):
    path = workspace / ".pipeline.lock"
    if path.exists() and (_link(path.lstat()) or path.stat().st_nlink != 1):
        raise PipelineError("lock_boundary_invalid")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise PipelineError("lock_boundary_invalid")
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise PipelineError("pipeline_writer_busy") from None
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _state(workspace: Path) -> dict[str, Any]:
    return _load(workspace / "state.json", root=workspace)


def _budgets(values: dict[str, Any]) -> dict[str, int]:
    result = dict(DEFAULT_BUDGETS)
    if set(values) - set(result):
        raise PipelineError("unsupported_budget_option")
    for key, value in values.items():
        if type(value) is not int or not 1 <= value <= MAX_BUDGETS[key]:
            raise PipelineError("budget_out_of_range")
        result[key] = value
    return result


def _cancelled(cancel: Any, deadline: float | None = None) -> None:
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise PipelineCancelled("pipeline_cancelled_checkpoint_preserved")
    if deadline is not None and time.monotonic() > deadline:
        raise PipelineCancelled("pipeline_time_budget_checkpoint_preserved")


def _discover(repo: Path, roots: list[str], budgets: dict[str, int], cancel: Any = None,
              deadline: float | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    import source_inventory
    languages = {**adapters.LANGUAGES, **{suffix: "Config" for suffix in adapters.CONFIG_SUFFIXES}}
    inventory = source_inventory.inventory(repo, roots, languages,
        max_files=budgets["max_files"], max_source_bytes=budgets["max_source_bytes"],
        max_total_bytes=budgets["max_total_bytes"], max_entries=budgets["max_files"] * 20,
        max_depth=budgets["max_depth"], cancel=cancel, deadline=deadline,
        read_file=lambda path: _read(path, budgets["max_source_bytes"], repo))
    # Extensionless scripts require a safe bounded shebang check, not execution.
    for row in inventory["entries"]:
        if row["status"] == "unsupported" and not Path(row["path"]).suffix:
            try:
                raw = _read(repo / row["path"], budgets["max_source_bytes"], repo)
                if re.match(rb"^#![^\r\n]*(?:/|\s)(?:bash|sh|zsh|ksh)(?:\s|$)", raw[:256]):
                    row.update(status="eligible", reason=None, language="Shell",
                        sourceDigest=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            except PipelineError:
                row.update(status="blocked", reason="extensionless_source_read_failed")
    inventory["summary"] = source_inventory.summarize(inventory["entries"], inventory["frontiers"])
    inventory["scopeDigest"] = source_inventory.digest({k:v for k,v in inventory.items() if k not in {"summary", "scopeDigest"}})
    files = {row["path"]: {"digest": row["sourceDigest"], "size": row["bytes"], "language": row["language"]}
             for row in inventory["entries"] if row["status"] == "eligible"}
    total = sum(row["size"] for row in files.values())
    if len(files) > budgets["max_files"] or total > budgets["max_total_bytes"]:
        for row in inventory["entries"]:
            if row["status"] == "eligible": row.update(status="blocked", reason="source_count_or_byte_budget")
        inventory["summary"] = source_inventory.summarize(inventory["entries"], inventory["frontiers"])
    counts = {"detectedFiles": len(files), "sourceBytes": total,
        "unsupportedFiles": sum(row["status"] == "unsupported" for row in inventory["entries"]),
        "excludedFiles": sum(row["status"] == "excluded" for row in inventory["entries"]),
        "excludedDirectories": sum(row["reason"] == "ignored_directory" for row in inventory["entries"]),
        "inventory": inventory}
    if inventory["summary"]["state"] == "BLOCKED":
        error = PipelineError("selected_scope_blocked_inspect_coverage_report")
        error.inventory = inventory
        raise error
    return dict(sorted(files.items())), counts


def _fingerprint(files: dict[str, Any]) -> str:
    return hashlib.sha256(_json(files)).hexdigest()


def _spec(config: dict[str, Any]) -> str:
    names = ["pipeline_store.py", "pipeline_adapters.py", "pipeline_policy.py", "pipeline_shell.py",
             "code_ontology_core.py", "privacy_guard.py", "source_inventory.py", "coverage_contract.py",
             "policy_semantics.py", "java_resolution.py", "pipeline_java.py"]
    code = {}
    for name in names:
        path = Path(__file__).with_name(name)
        if path.exists():
            code[name] = hashlib.sha256(_read(path, 4 * 1024 * 1024)).hexdigest()
    return "spec:" + hashlib.sha256(_json({"code": code, "scope": config["sourceRoots"],
                                            "budgets": config["budgets"], "modelIdentity": "modelNotUsed"})).hexdigest()


def _hash_file_unchecked(path: Path) -> tuple[str, int, tuple[int, ...]]:
    before = path.lstat()
    if _link(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PipelineError("artifact_boundary_invalid")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as handle:
        if not core._same_file(before, os.fstat(handle.fileno())):
            raise PipelineError("artifact_changed")
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(handle.fileno())
    current = path.lstat()
    if (not core._same_file(after, current) or core._stable_file_metadata(before) != core._stable_file_metadata(after)
            or core._stable_file_metadata(after) != core._stable_file_metadata(current)):
        raise PipelineError("artifact_changed")
    return digest.hexdigest(), current.st_size, core._stable_file_metadata(current)


def _hash_file(path: Path) -> tuple[str, int, tuple[int, ...]]:
    try:
        return _hash_file_unchecked(path)
    except OSError:
        raise PipelineError("artifact_unavailable") from None


def _receipts(workspace: Path) -> list[tuple[Path, dict[str, Any]]]:
    jobs = _directory(workspace / ".jobs")
    rows = []
    for entry in sorted(jobs.iterdir()):
        if not re.fullmatch(r"run-[0-9a-f]{32}", entry.name):
            raise PipelineError("invalid_job_entry")
        _directory(entry)
        receipt = entry / "receipt.json"
        if receipt.exists():
            value = _load(receipt, root=workspace)
            if value.get("runId") != entry.name or not SNAPSHOT_RE.fullmatch(str(value.get("snapshotId", ""))):
                raise PipelineError("receipt_identity_invalid")
            if value.get("status") in {"building", "paused", "prepared"}:
                rows.append((entry, value))
    return rows


def _uri(path: Path) -> str:
    return "file:" + quote(str(path), safe="/:") + "?mode=ro&immutable=1"


def _generation(workspace: Path, snapshot_id: str, expected_hash: str | None = None) -> tuple[Path, dict[str, Any], dict[str, tuple[int, ...]]]:
    if not isinstance(snapshot_id, str) or not SNAPSHOT_RE.fullmatch(snapshot_id):
        raise PipelineError("invalid_snapshot_id")
    parent = _directory(workspace / "snapshots")
    directory = _directory(parent / snapshot_id)
    if directory.parent != parent:
        raise PipelineError("snapshot_boundary_invalid")
    raw = _read(directory / "manifest.json", 2 * 1024 * 1024, workspace)
    if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
        raise PipelineError("manifest_integrity_failed")
    try:
        manifest = json.loads(raw)
        if manifest["snapshotId"] != snapshot_id or manifest["schemaVersion"] != 1:
            raise ValueError()
        artifacts = manifest["artifacts"]
        count = manifest["partitionCount"]
        required = {f"part-{i:02d}.sqlite" for i in range(count)} | {"policy.json", "source-manifest.json", "ontology.ttl", "lineage.ttl", "shapes.ttl"}
        if manifest.get("coverage", {}).get("scopeDigest"):
            required.add("coverage.json")
        if type(count) is not int or not 1 <= count <= 8 or not isinstance(artifacts, dict) or set(artifacts) != required:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise PipelineError("manifest_invalid") from None
    identities = {"manifest.json": core._stable_file_metadata((directory / "manifest.json").lstat())}
    for name, expected in artifacts.items():
        if not re.fullmatch(r"(?:part-[0-9]{2}\.sqlite|policy\.json|coverage\.json|source-manifest\.json|ontology\.ttl|lineage\.ttl|shapes\.ttl)", name):
            raise PipelineError("artifact_name_invalid")
        digest, size, identity = _hash_file(directory / name)
        _private_file(directory / name)
        if digest != expected.get("sha256") or size != expected.get("bytes"):
            raise PipelineError("artifact_integrity_failed")
        identities[name] = identity
    return directory, manifest, identities


def _connect(path: Path) -> sqlite3.Connection:
    if path.exists() and (_link(path.lstat()) or path.stat().st_nlink != 1):
        raise PipelineError("partition_boundary_invalid")
    connection = sqlite3.connect(path, timeout=0.1)
    os.chmod(path, 0o600)
    _private_file(path)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.executescript(SCHEMA)
    return connection


def _partition(path: str, count: int) -> int:
    return int(hashlib.sha256(path.encode()).hexdigest()[:8], 16) % count


def _domains(record: dict[str, Any]) -> list[str]:
    values = record.get("domains", record.get("domain", []))
    if isinstance(values, str):
        values = [values]
    names = [x.get("name") if isinstance(x, dict) else x for x in values]
    return sorted({x for x in names if isinstance(x, str) and len(x) <= 120})


def _write_facts(db: sqlite3.Connection, facts: dict[str, Any]) -> int:
    relative = facts["path"]
    records = list(facts["records"])
    semantics = facts.get("semantics")
    if semantics is not None:
        if semantics.get("path") != relative or semantics.get("sourceDigest") != facts["sourceDigest"]:
            raise PipelineError("semantic_source_binding_mismatch")
        semantic_coverage = semantics["coverage"]
        records.append({"id": adapters.identifier("semantic-coverage", relative, facts["sourceDigest"]),
            "kind": "semantic_fragment", "name": "SemanticCoverage", "category": "coverage",
            "path": relative, "module": facts["module"], "modulePath": facts["modulePath"],
            "language": facts["language"], "sourceDigest": facts["sourceDigest"],
            "span": semantics.get("sourceSpan", {"lineStart": 1, "lineEnd": 1}),
            "coverage": semantic_coverage,
            "unprocessedRegion": semantic_coverage.get("unprocessedRegion"),
            "representationStatus": "coverage_metadata", "expression": None, "references": [],
            "unsupportedReasons": semantic_coverage.get("reasons", []),
            "basis": "declared", "status": "runtime_unknown", "businessMeaningVerified": False,
            "extractorVersion": semantics["extractorVersion"]})
    for fragment in (semantics or {}).get("fragments", []) + (semantics or {}).get("omissions", []):
        if fragment.get("path") != relative or fragment.get("sourceDigest") != facts["sourceDigest"]:
            raise PipelineError("semantic_fragment_binding_mismatch")
        row = dict(fragment)
        row.update(kind="semantic_fragment", name=fragment.get("name", fragment.get("category", "unprocessed")), path=relative,
            module=facts["module"], modulePath=facts["modulePath"], language=facts["language"],
            sourceDigest=facts["sourceDigest"], basis="declared", status="runtime_unknown")
        records.append(row)
    policy = facts.get("policy", {})
    for rule in policy.get("rules", []):
        row = dict(rule)
        row.update(kind="policy_rule", path=relative, module=facts["module"], modulePath=facts["modulePath"],
                   language=facts["language"], name=str(rule.get("name", rule.get("id", "PolicyRule"))), basis="resolved_static")
        records.append(row)
    for evidence in policy.get("evidence", []):
        row = dict(evidence)
        row.update(kind="assertion", name="PolicyEvidence", path=relative, module=facts["module"],
                   modulePath=facts["modulePath"], language=facts["language"],
                   span={"lineStart": evidence.get("lineStart", 1), "lineEnd": evidence.get("lineEnd", 1)})
        records.append(row)
    db.execute("DELETE FROM domains WHERE id IN (SELECT id FROM records WHERE path=?)", (relative,))
    db.execute("DELETE FROM records WHERE path=?", (relative,))
    for record in records:
        if not isinstance(record.get("id"), str) or len(record["id"]) > 256:
            raise PipelineError("record_id_invalid")
        encoded = _json(record).decode()
        db.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", (record["id"], record["kind"], record["name"], relative, facts["module"], encoded))
        db.executemany("INSERT INTO domains VALUES(?,?)", ((record["id"], domain) for domain in _domains(record)))
    db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (relative, facts["sourceDigest"], _json(facts).decode()))
    return len(records)


def _resolve(db_list: list[sqlite3.Connection], scratch: Path, cancel=None, deadline=None) -> dict[str, int]:
    # Recompute every derived binding each generation. Cached file facts contain
    # only file-local observations, so deletions/renames cannot leave stale edges.
    symbols = sqlite3.connect(scratch)
    try:
        os.chmod(scratch, 0o600)
        _private_file(scratch)
        symbols.execute("CREATE TABLE exports(name TEXT NOT NULL,id TEXT NOT NULL)")
        symbols.execute("CREATE INDEX exports_name ON exports(name,id)")
        for db in db_list:
            for index, (encoded,) in enumerate(db.execute("SELECT payload FROM records WHERE kind='symbol' ORDER BY id")):
                if index % 256 == 0:
                    _cancelled(cancel, deadline)
                record = json.loads(encoded)
                if record.get("type") in {"External", "ExternalSymbol", "ExternalModule", "File"}:
                    continue
                for name in {record.get("qualifiedName", "")} - {""}:
                    symbols.execute("INSERT INTO exports VALUES(?,?)", (name, record["id"]))
        symbols.commit()
        counts: Counter[str] = Counter()
        for db in db_list:
            for index, (relative, encoded) in enumerate(db.execute("SELECT path,facts FROM files ORDER BY path")):
                if index % 256 == 0:
                    _cancelled(cancel, deadline)
                facts = json.loads(encoded)
                for item in facts.get("imports", []):
                    target_name = item["module"].strip(".") + ("." + item["name"] if item.get("name") else "")
                    candidates = [row[0] for row in symbols.execute("SELECT DISTINCT id FROM exports WHERE name=? ORDER BY id LIMIT 2", (target_name,))] if not item["module"].startswith(".") else []
                    row = {"id": adapters.identifier(relative, "import-binding", item), "kind": "assertion", "name": "IMPORTS",
                           "path": relative, "module": facts["module"], "modulePath": facts["modulePath"], "language": facts["language"],
                           "span": {"lineStart": 1, "lineEnd": 1}, "subject": adapters.identifier("file", relative),
                           "predicate": "IMPORTS", "targetName": target_name, "basis": "declared", "sourceDigest": facts["sourceDigest"],
                           "ruleVersion": STORE_VERSION, "status": "runtime_unknown", "resolution": "resolved_unique_export" if len(candidates) == 1 else "ambiguous" if candidates else "unresolved",
                           "limitations": ["import_binding_not_runtime_call_resolution"]}
                    if len(candidates) == 1:
                        row["object"] = candidates[0]
                    counts[row["resolution"]] += 1
                    db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?)", (row["id"], row["kind"], row["name"], relative, facts["module"], _json(row).decode()))
            db.commit()
        return dict(counts)
    finally:
        symbols.close()
        if scratch.exists():
            scratch.unlink()


def _policy_snapshot(db_list: list[sqlite3.Connection], snapshot: str, created: str, limit: int, cancel=None, deadline=None) -> dict[str, Any]:
    import pipeline_policy
    rules, evidence = [], []
    coverage = {"detectedRules": 0, "analyzedRules": 0, "unsupportedRules": 0,
                "complete": True, "unknownDenominator": False, "reasons": [],
                "scope": "selected_source_functions", "businessPolicyComplete": False}
    file_count = 0
    for db in db_list:
        for (encoded,) in db.execute("SELECT facts FROM files ORDER BY path"):
            file_count += 1
            if file_count % 256 == 0:
                _cancelled(cancel, deadline)
            policy = json.loads(encoded).get("policy", {})
            rules.extend(policy.get("rules", []))
            evidence.extend(policy.get("evidence", []))
            row = policy.get("coverage", {})
            for key in ("detectedRules", "analyzedRules", "unsupportedRules"):
                coverage[key] += int(row.get(key, 0))
            coverage["complete"] &= row.get("complete") is True
            coverage["unknownDenominator"] |= row.get("unknownDenominator", True) is not False
            coverage["reasons"].extend(row.get("reasons", []))
            if len(rules) > limit or len(evidence) > limit * 20:
                raise PipelineError("policy_snapshot_budget_exceeded")
    rules.sort(key=lambda row: row["id"])
    evidence.sort(key=lambda row: row["id"])
    coverage["reasons"] = sorted(set(coverage["reasons"]))
    if not file_count:
        coverage.update(complete=False, unknownDenominator=True, reasons=["empty_source_scope"])
    value = {"schemaVersion": 1, "rules": rules, "evidence": evidence, "coverage": coverage,
             "catalogSnapshotId": snapshot, "policySnapshotId": snapshot, "createdAt": created,
             "sourceLastVerifiedAt": created, "modelIdentity": "modelNotUsed", "repeatability": "N/A"}
    value["rulesetDigest"] = pipeline_policy.policy_ruleset_digest(value)
    return value


def _semantic_coverage(db_list: list[sqlite3.Connection], cancel=None, deadline=None) -> dict[str, Any]:
    """Aggregate declared fragment inventories without treating them as rules.

    Full per-file failures and unsupported regions are also queryable records;
    a lexical failure with zero fragments must never disappear from delivery.
    """
    summary = {"scope": "Java expression-fragment inventory; other languages not included",
               "files": 0, "incompleteInventoryFiles": 0, "detectedFragments": 0,
               "recordedFragments": 0, "representedFragments": 0, "partialFragments": 0,
               "unsupportedFragments": 0, "omittedFragments": 0,
               "wholePolicyDenominator": "UNKNOWN", "semanticComplete": False,
               "businessPolicyComplete": False, "complete": False, "state": "PARTIAL",
               "reasonCounts": {}}
    reasons = Counter()
    for db in db_list:
        for (encoded,) in db.execute("SELECT payload FROM records WHERE kind='semantic_fragment' AND name='SemanticCoverage' ORDER BY id"):
            if summary["files"] % 256 == 0:
                _cancelled(cancel, deadline)
            record = json.loads(encoded)
            if record.get("category") != "coverage":
                continue
            coverage = record["coverage"]
            summary["files"] += 1
            summary["incompleteInventoryFiles"] += coverage.get("inventoryComplete") is not True
            for key in ("detectedFragments", "recordedFragments", "representedFragments", "partialFragments", "unsupportedFragments"):
                summary[key] += coverage.get(key, 0)
            summary["omittedFragments"] += coverage.get("detectedFragments", 0) - coverage.get("recordedFragments", 0)
            reasons.update(coverage.get("reasons", []))
    summary["reasonCounts"] = dict(sorted(reasons.items()))
    if summary["incompleteInventoryFiles"]:
        summary["state"] = "BLOCKED"
    return summary


def _rdf(stage: Path, db_list: list[sqlite3.Connection], snapshot: str, run_id: str, cancel=None, deadline=None) -> None:
    prefix = '@prefix co: <urn:code-ontology:pipeline:> .\n@prefix prov: <http://www.w3.org/ns/prov#> .\n'
    path = stage / "ontology.ttl"
    with _atomic_text(path) as handle:
        handle.write(prefix)
        for db in db_list:
            for index, (encoded,) in enumerate(db.execute("SELECT payload FROM records ORDER BY id")):
                if index % 256 == 0:
                    _cancelled(cancel, deadline)
                row = json.loads(encoded)
                subject = "<urn:code-ontology:record:" + quote(row["id"], safe="") + ">"
                kind = "Assertion" if row["kind"] == "assertion" else "PolicyRule" if row["kind"] == "policy_rule" else "Symbol"
                handle.write(subject + ' a co:' + kind + ', prov:Entity ; co:label ' + json.dumps(row["name"], ensure_ascii=False) + ' ; prov:wasGeneratedBy <urn:code-ontology:run:' + run_id + '> .\n')
                for key in ("path", "sourceDigest", "ruleVersion", "basis", "resolution", "predicate"):
                    if key in row:
                        handle.write(subject + ' co:' + key + ' ' + json.dumps(str(row[key]), ensure_ascii=False) + ' .\n')
                span = row.get("span", {"lineStart": row.get("lineStart", 1), "lineEnd": row.get("lineEnd", 1)})
                for key in ("lineStart", "lineEnd"):
                    handle.write(subject + ' co:' + key + ' ' + str(max(1, int(span.get(key, 1)))) + ' .\n')
                handle.write(subject + ' prov:wasDerivedFrom <urn:code-ontology:source:' + row["sourceDigest"] + '> .\n')
                for key in ("subject", "object"):
                    if row.get(key):
                        handle.write(subject + ' co:' + key + ' <urn:code-ontology:record:' + quote(str(row[key]), safe="") + '> .\n')
        handle.flush()
        os.fsync(handle.fileno())
    _atomic(stage / "lineage.ttl", (prefix + '<urn:code-ontology:run:' + run_id + '> a prov:Activity ; prov:wasAssociatedWith <urn:code-ontology:software:pipeline> .\n<urn:code-ontology:software:pipeline> a prov:Agent .\n<urn:code-ontology:snapshot:' + snapshot + '> a prov:Entity ; prov:wasGeneratedBy <urn:code-ontology:run:' + run_id + '> .\n').encode())
    shapes = '''@prefix co: <urn:code-ontology:pipeline:> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
co:EvidenceShape a sh:NodeShape ; sh:targetClass co:Assertion, co:PolicyRule, co:Symbol ;
 sh:property [ sh:path co:path ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path co:sourceDigest ; sh:minCount 1 ; sh:pattern "^[a-f0-9]{64}$" ] ;
 sh:property [ sh:path co:ruleVersion ; sh:minCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path co:basis ; sh:minCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path co:lineStart ; sh:minCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 1 ] ;
 sh:property [ sh:path co:lineEnd ; sh:minCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 1 ] ;
 sh:property [ sh:path prov:wasGeneratedBy ; sh:minCount 1 ; sh:nodeKind sh:IRI ] ;
 sh:property [ sh:path prov:wasDerivedFrom ; sh:minCount 1 ; sh:nodeKind sh:IRI ] .
co:RelationShape a sh:NodeShape ; sh:targetSubjectsOf co:predicate ;
 sh:property [ sh:path co:subject ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ;
 sh:property [ sh:path co:predicate ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] ;
 sh:property [ sh:path co:object ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] .
'''
    _atomic(stage / "shapes.ttl", shapes.encode())


def _publish(workspace: Path, receipt_path: Path, receipt: dict[str, Any]) -> None:
    current = _state(workspace)
    if current.get("currentSnapshot") not in {receipt["previousSnapshot"], receipt["snapshotId"]}:
        raise PipelineError("catalog_compare_and_swap_conflict")
    directory, manifest, _identities = _generation(workspace, receipt["snapshotId"], receipt["manifestSha256"])
    if manifest["workspaceId"] != receipt["workspaceId"] or manifest["previousSnapshot"] != receipt["previousSnapshot"]:
        raise PipelineError("receipt_binding_invalid")
    if current.get("currentSnapshot") != receipt["snapshotId"]:
        _atomic(workspace / "state.json", {"schemaVersion": 1, "currentSnapshot": receipt["snapshotId"],
                "manifestSha256": receipt["manifestSha256"], "sourceLastVerifiedAt": _now()})
    _checkpoint("after_pointer")
    ledger = _load(workspace / "ledger.json", 16 * 1024 * 1024, workspace)
    if not any(row.get("runId") == receipt["runId"] for row in ledger["events"]):
        ledger["events"].append({"runId": receipt["runId"], "snapshotId": receipt["snapshotId"],
                               "manifestSha256": receipt["manifestSha256"], "previousSnapshot": receipt["previousSnapshot"],
                               "createdAt": receipt["createdAt"]})
        _atomic(workspace / "ledger.json", ledger)
    _checkpoint("after_ledger")
    receipt["status"] = "completed"
    _atomic(receipt_path, receipt)


def _build(workspace: Path, config: dict[str, Any], files: dict[str, Any], discovery: dict[str, int],
           spec: str, *, cancel: Any = None, resume: tuple[Path, dict[str, Any]] | None = None,
           force_reparse: bool = False) -> dict[str, Any]:
    import pipeline_policy
    repo = _directory(config["repositoryRoot"])
    budgets = config["budgets"]
    deadline = time.monotonic() + budgets["max_run_seconds"]
    previous = _state(workspace).get("currentSnapshot")
    if resume:
        job, receipt = resume
    else:
        run_id = "run-" + uuid.uuid4().hex
        job = _mkdir(_mkdir(workspace, ".jobs"), run_id)
        receipt = {"schemaVersion": 1, "status": "building", "runId": run_id, "snapshotId": "ps-" + uuid.uuid4().hex,
                   "previousSnapshot": previous, "workspaceId": config["workspaceId"], "createdAt": _now(),
                   "sourceFingerprint": _fingerprint(files), "analysisSpecId": spec, "completedFiles": 0,
                   "discovery": discovery, "forceReparse": force_reparse}
        _atomic(job / "receipt.json", receipt)
    stage = _mkdir(job, "snapshot")
    connections: list[sqlite3.Connection] = []
    old = None
    parsed = reused = resumed = 0
    outcomes = {}
    active_relative = None
    try:
        if previous:
            old = SnapshotReader(workspace, previous)
            old.__enter__()
        java_sources = {}
        for relative, info in files.items():
            if info["language"] != "Java":
                continue
            _cancelled(cancel, deadline)
            raw = _read(repo / relative, budgets["max_source_bytes"], repo)
            if hashlib.sha256(raw).hexdigest() != info["digest"]:
                raise PipelineError("source_changed_before_java_index")
            try:
                java_sources[relative] = raw.decode("utf-8")
            except UnicodeError:
                active_relative = relative
                raise PipelineError("source_encoding_unsupported") from None
        java_index = core.build_java_index(java_sources)
        java_sources.clear()
        for index in range(budgets["partition_count"]):
            connections.append(_connect(stage / f"part-{index:02d}.sqlite"))
        count = sum(row.execute("SELECT count(*) FROM records").fetchone()[0] for row in connections)
        completed_since_flush = 0
        for relative, info in files.items():
            active_relative = relative
            _cancelled(cancel, deadline)
            db = connections[_partition(relative, len(connections))]
            existing = db.execute("SELECT digest,facts FROM files WHERE path=?", (relative,)).fetchone()
            if existing and existing[0] == info["digest"] and (info["language"] != "Java" or json.loads(existing[1]).get("javaIndexHash") == java_index.fingerprint):
                resumed += 1
                outcomes[relative] = {"status": "analyzed", "reason": None}
                continue
            facts = old.file_facts(relative) if old and not receipt.get("forceReparse", False) and old.metadata["analysisSpecId"] == spec else None
            if facts is not None and facts["sourceDigest"] == info["digest"] and (info["language"] != "Java" or facts.get("javaIndexHash") == java_index.fingerprint):
                reused += 1
            else:
                raw = _read(repo / relative, budgets["max_source_bytes"], repo)
                if hashlib.sha256(raw).hexdigest() != info["digest"]:
                    raise PipelineError("source_changed_during_analysis")
                try:
                    source = raw.decode("utf-8")
                except UnicodeError:
                    raise PipelineError("source_encoding_unsupported") from None
                facts = adapters.analyze_file(relative, source, info["digest"], resource_key=_read(workspace / ".resource-key", 64, workspace),
                    max_records=budgets["max_file_records"], max_ast_nodes=budgets["max_ast_nodes"])
                if info["language"] == "Java":
                    import pipeline_java
                    import policy_semantics
                    facts = pipeline_java.enrich(facts, java_index)
                    facts["semantics"] = policy_semantics.extract_semantics(source, "Java", relative, info["digest"],
                        max_fragments=budgets["max_file_records"])
                    if facts["semantics"]["coverage"].get("inventoryComplete") is not True:
                        outcomes[relative] = {"status": "failed", "reason": "semantic_fragment_inventory_incomplete"}
                        error = PipelineError("semantic_fragment_inventory_incomplete")
                        error.semantic_failure = {"path": relative, "sourceDigest": info["digest"],
                            "sourceSpan": facts["semantics"]["sourceSpan"],
                            "omissions": facts["semantics"]["omissions"],
                            "coverage": facts["semantics"]["coverage"]}
                        raise error
                facts["policy"] = pipeline_policy.extract_policy_rules(source, info["language"], relative, info["digest"],
                    max_rules=min(256, budgets["max_policy_rules"]), max_ast_nodes=budgets["max_ast_nodes"])
                privacy_guard.ensure_public_safe(facts, context_roots=(repo, workspace))
                parsed += 1
            count += _write_facts(db, facts)
            outcomes[relative] = {"status": "analyzed", "reason": None}
            receipt["completedFiles"] += 1
            completed_since_flush += 1
            if completed_since_flush >= 64:
                for connection in connections:
                    connection.commit()
                _atomic(job / "receipt.json", receipt)
                completed_since_flush = 0
            _checkpoint("after_file")
            if count > budgets["max_records"]:
                raise PipelineError("record_budget_exceeded")
            if completed_since_flush == 0 and sum(path.stat().st_size for path in stage.iterdir() if path.is_file()) > budgets["max_output_bytes"]:
                raise PipelineError("output_budget_exceeded")
        if old:
            old.__exit__(None, None, None)
            old = None
        _cancelled(cancel, deadline)
        for connection in connections:
            connection.commit()
        _atomic(job / "receipt.json", receipt)
        scratch = stage / ".resolution.sqlite"
        # This derived index is rebuildable; remove interrupted scratch state
        # without touching authoritative per-file partitions or their journals.
        for name in (".resolution.sqlite", ".resolution.sqlite-journal", ".resolution.sqlite-wal", ".resolution.sqlite-shm"):
            abandoned = stage / name
            if abandoned.exists() or abandoned.is_symlink():
                _hash_file(abandoned)
                abandoned.unlink()
        resolution = _resolve(connections, scratch, cancel, deadline)
        policy = _policy_snapshot(connections, receipt["snapshotId"], receipt["createdAt"], budgets["max_policy_rules"], cancel, deadline)
        semantic_coverage = _semantic_coverage(connections, cancel, deadline)
        if discovery.get("unsupportedFiles") or discovery.get("excludedFiles") or discovery.get("excludedDirectories"):
            policy["coverage"]["complete"] = False
            policy["coverage"]["unknownDenominator"] = True
            policy["coverage"]["reasons"].append("excluded_or_unsupported_source_scope")
            policy["rulesetDigest"] = pipeline_policy.policy_ruleset_digest(policy)
        privacy_guard.ensure_public_safe(policy, context_roots=(repo, workspace))
        _atomic(stage / "policy.json", policy)
        _atomic(stage / "source-manifest.json", {"files": files, "scopeDigest": discovery["inventory"]["scopeDigest"]})
        import source_inventory
        source_coverage = source_inventory.finish(discovery["inventory"], outcomes)
        _atomic(stage / "coverage.json", source_coverage)
        _rdf(stage, connections, receipt["snapshotId"], receipt["runId"], cancel, deadline)
        record_count = sum(db.execute("SELECT count(*) FROM records").fetchone()[0] for db in connections)
        if record_count > budgets["max_records"]:
            raise PipelineError("record_budget_exceeded")
        for db in connections:
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PipelineError("sqlite_integrity_failed")
            db.close()
        connections.clear()
        _checkpoint("before_source_recheck")
        checked, checked_discovery = _discover(repo, config["sourceRoots"], budgets, cancel, deadline)
        _, current_config = _config(workspace)
        if checked != files or checked_discovery != discovery or _spec(config) != spec or current_config != config:
            raise PipelineError("source_or_generator_changed_during_analysis")
        artifacts = {}
        output_size = 0
        for path in sorted(stage.iterdir()):
            if path.name == "manifest.json":
                continue
            digest, size, _ = _hash_file(path)
            output_size += size
            if output_size > budgets["max_output_bytes"]:
                raise PipelineError("output_budget_exceeded")
            artifacts[path.name] = {"sha256": digest, "bytes": size}
        manifest = {"schemaVersion": 1, "workspaceId": config["workspaceId"], "snapshotId": receipt["snapshotId"],
                    "previousSnapshot": receipt["previousSnapshot"], "analysisSpecId": spec,
                    "sourceFingerprint": receipt["sourceFingerprint"], "createdAt": receipt["createdAt"],
                    "sourceLastVerifiedAt": _now(), "artifacts": artifacts, "recordCount": record_count,
                    "partitionCount": budgets["partition_count"], "rulesetDigest": policy["rulesetDigest"],
                    "coverage": {**{k:v for k,v in discovery.items() if k != "inventory"},
                                 "scopeDigest": source_coverage["scopeDigest"], "sourceProcessing": source_coverage["summary"],
                                 "completeness": "PARTIAL", "analyzedFiles": len(files), "semanticComplete": False,
                                 "runtimeStatus": "runtime_unknown", "resolution": resolution,
                                 "semantics": semantic_coverage,
                                 "calls": {k:v for k,v in java_index.summary().items() if k != "callsites"}},
                    "buildStats": {"parsedFiles": parsed, "reusedFiles": reused, "resumedFiles": resumed,
                                   "resolutionRebuilt": True, "workers": 1},
                    "rdfValidation": {"structural": "emitted", "independentParser": "not_run", "shacl": "not_run"},
                    "durability": "file_flush_only" if os.name == "nt" else "file_and_directory_fsync"}
        privacy_guard.ensure_public_safe(manifest, context_roots=(repo, workspace))
        _atomic(stage / "manifest.json", manifest)
        _checkpoint("after_manifest")
        receipt["manifestSha256"] = hashlib.sha256(_json(manifest)).hexdigest()
        receipt["status"] = "prepared"
        _atomic(job / "receipt.json", receipt)
        _checkpoint("after_prepared_receipt")
        destination = _mkdir(workspace, "snapshots") / receipt["snapshotId"]
        if destination.exists():
            raise PipelineError("snapshot_already_exists")
        os.replace(stage, destination)
        _sync_dir(destination.parent)
        _checkpoint("after_snapshot_rename")
        _publish(workspace, job / "receipt.json", receipt)
        result = status(workspace)
        result["status"] = "created" if previous is None else "updated"
        return result
    except PipelineCancelled:
        import source_inventory
        _atomic(workspace / "last-coverage-attempt.json", source_inventory.finish(discovery["inventory"], outcomes))
        if receipt["status"] == "building":
            receipt["status"] = "paused"
            _atomic(job / "receipt.json", receipt)
        raise
    except (PipelineError, adapters.AdapterError, privacy_guard.PrivacyError, core.OntologyError, sqlite3.Error) as exc:
        import source_inventory
        if active_relative:
            if outcomes.get(active_relative, {}).get("status") != "failed":
                outcomes[active_relative] = {"status": "failed", "reason": "parse_encoding_privacy_or_resource_failure"}
        attempt = source_inventory.finish(discovery["inventory"], outcomes)
        if hasattr(exc, "semantic_failure"):
            attempt["semanticFailures"] = [exc.semantic_failure]
        _atomic(workspace / "last-coverage-attempt.json", attempt)
        if receipt["status"] == "building":
            receipt["status"] = "failed"
            _atomic(job / "receipt.json", receipt)
        raise
    finally:
        for db in connections:
            db.close()
        if old:
            old.__exit__(None, None, None)


def initialize(repo_path: str | Path, workspace_path: str | Path, source_roots=None, *, label="Local ontology",
               prepare_workspace=None, **budgets) -> dict[str, Any]:
    # Trusted in-process initialization hook, never a model-supplied callable.
    # ACL provisioning must precede the first recoverable analysis checkpoint.
    if prepare_workspace is not None and not callable(prepare_workspace):
        raise PipelineError("workspace_preparation_invalid")
    repo = _directory(repo_path)
    raw = Path(workspace_path).expanduser()
    parent = _directory(raw.parent)
    workspace = parent / raw.name
    if workspace.exists() or workspace.is_symlink() or core._is_relative_to(workspace, repo) or core._is_relative_to(repo, workspace):
        raise PipelineError("new_workspace_boundary_invalid")
    try:
        roots = core.normalize_source_roots(repo, source_roots)
    except core.OntologyError:
        raise PipelineError("source_scope_invalid") from None
    config = {"schemaVersion": 1, "mode": "pipeline", "workspaceId": "pw-" + uuid.uuid4().hex,
              "repositoryRoot": str(repo), "repositoryLabel": label, "sourceRoots": roots,
              "budgets": _budgets(budgets)}
    if not isinstance(label, str) or not 1 <= len(label) <= 120:
        raise PipelineError("repository_label_invalid")
    privacy_guard.ensure_public_safe(label, context_roots=(repo,))
    workspace.mkdir(mode=0o700)
    _mkdir(workspace, ".jobs")
    _mkdir(workspace, "snapshots")
    _atomic(workspace / "pipeline.json", config)
    _atomic(workspace / ".resource-key", os.urandom(32))
    _atomic(workspace / "state.json", {"schemaVersion": 1, "currentSnapshot": None})
    _atomic(workspace / "ledger.json", {"schemaVersion": 1, "events": []})
    if prepare_workspace is not None:
        prepare_workspace(workspace)
    return sync(workspace)


def sync(workspace_path: str | Path, *, force: bool = False, cancel: Any = None) -> dict[str, Any]:
    workspace, config = _config(workspace_path)
    with _lock(workspace):
        if _receipts(workspace):
            raise PipelineError("pending_run_requires_recovery")
        repo = _directory(config["repositoryRoot"])
        try:
            files, counts = _discover(repo, config["sourceRoots"], config["budgets"], cancel,
                                      time.monotonic() + config["budgets"]["max_run_seconds"])
        except PipelineError as exc:
            if hasattr(exc, "inventory"):
                _atomic(workspace / "last-coverage-attempt.json", exc.inventory)
            raise
        spec = _spec(config)
        current = _state(workspace)
        if current.get("currentSnapshot"):
            with SnapshotReader(workspace, current["currentSnapshot"]) as reader:
                same_discovery = all(reader.metadata["coverage"].get(key, 0) == counts.get(key, 0)
                                     for key in ("detectedFiles", "sourceBytes", "unsupportedFiles", "excludedFiles", "excludedDirectories"))
                if not force and same_discovery and reader.metadata["coverage"].get("scopeDigest") == counts["inventory"]["scopeDigest"] and reader.metadata["sourceFingerprint"] == _fingerprint(files) and reader.metadata["analysisSpecId"] == spec:
                    current["sourceLastVerifiedAt"] = _now()
                    _atomic(workspace / "state.json", current)
                    result = dict(reader.metadata)
                    result.update(status="no_change", workspaceId=config["workspaceId"], sourceLastVerifiedAt=current["sourceLastVerifiedAt"])
                    return result
        return _build(workspace, config, files, counts, spec, cancel=cancel, force_reparse=force)


def recover(workspace_path: str | Path, *, cancel: Any = None) -> dict[str, Any]:
    workspace, config = _config(workspace_path)
    with _lock(workspace):
        pending = _receipts(workspace)
        if len(pending) > 1:
            raise PipelineError("multiple_pending_runs")
        if not pending:
            result = status(workspace)
            result["recoveredRunCount"] = 0
            return result
        job, receipt = pending[0]
        if receipt.get("workspaceId") != config["workspaceId"]:
            raise PipelineError("receipt_workspace_invalid")
        files, counts = _discover(_directory(config["repositoryRoot"]), config["sourceRoots"], config["budgets"], cancel)
        spec = _spec(config)
        if receipt["sourceFingerprint"] != _fingerprint(files) or receipt["analysisSpecId"] != spec or receipt.get("discovery") != counts:
            if _state(workspace).get("currentSnapshot") == receipt["snapshotId"]:
                _publish(workspace, job / "receipt.json", receipt)
            else:
                receipt["status"] = "abandoned_source_changed"
                _atomic(job / "receipt.json", receipt)
            return {"status": "recovery_finished_source_changed", "workspaceId": config["workspaceId"],
                    "snapshotId": _state(workspace).get("currentSnapshot"), "recoveredRunCount": 1}
        if receipt["status"] == "prepared":
            destination = workspace / "snapshots" / receipt["snapshotId"]
            if not destination.exists():
                staged = _directory(job / "snapshot")
                raw = _read(staged / "manifest.json", 2 * 1024 * 1024, workspace)
                if hashlib.sha256(raw).hexdigest() != receipt["manifestSha256"]:
                    raise PipelineError("prepared_manifest_integrity_failed")
                os.replace(staged, destination)
                _sync_dir(destination.parent)
            _publish(workspace, job / "receipt.json", receipt)
            result = status(workspace)
        else:
            if _state(workspace).get("currentSnapshot") != receipt["previousSnapshot"]:
                raise PipelineError("recovery_predecessor_conflict")
            receipt["status"] = "building"
            _atomic(job / "receipt.json", receipt)
            result = _build(workspace, config, files, counts, spec, cancel=cancel, resume=(job, receipt))
        result["recoveredRunCount"] = 1
        return result


class SnapshotReader:
    """A verified, pinned read session; verification is amortized over pages."""
    def __init__(self, workspace_path: str | Path, snapshot_id: str | None = None):
        self.workspace, self.config = _config(workspace_path)
        state = _state(self.workspace)
        self.snapshot_id = snapshot_id or state.get("currentSnapshot")
        if not self.snapshot_id:
            raise PipelineError("no_completed_snapshot")
        if self.snapshot_id == state.get("currentSnapshot"):
            expected = state.get("manifestSha256")
        else:
            ledger = _load(self.workspace / "ledger.json", 16 * 1024 * 1024, self.workspace)
            event = next((x for x in ledger["events"] if x["snapshotId"] == self.snapshot_id), None)
            if event is None:
                raise PipelineError("snapshot_not_published")
            expected = event["manifestSha256"]
        self.directory, self.metadata, self.identities = _generation(self.workspace, self.snapshot_id, expected)
        if self.metadata["workspaceId"] != self.config["workspaceId"]:
            raise PipelineError("snapshot_workspace_mismatch")
        self.metadata = dict(self.metadata)
        self.metadata.update(workspaceId=self.config["workspaceId"], sourceAccess="not_read", freshness="not_checked")
        if self.snapshot_id == state.get("currentSnapshot"):
            self.metadata["sourceLastVerifiedAt"] = state.get("sourceLastVerifiedAt", self.metadata.get("sourceLastVerifiedAt"))
        self.connection: sqlite3.Connection | None = None

    def __enter__(self):
        self.connection = sqlite3.connect(":memory:", uri=True)
        self.connection.execute("PRAGMA trusted_schema=OFF")
        self.partitions = sorted(name for name in self.metadata["artifacts"] if name.endswith(".sqlite"))
        for i, name in enumerate(self.partitions):
            self.connection.execute(f"ATTACH DATABASE ? AS p{i}", (_uri(self.directory / name),))
        self.connection.execute("PRAGMA query_only=ON")
        self._stable()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
        finally:
            self._stable()

    def _stable(self):
        try:
            _directory(self.directory)
            _ancestors(self.workspace, self.directory / "manifest.json")
            for name, expected in self.identities.items():
                info = (self.directory / name).lstat()
                if _link(info) or core._stable_file_metadata(info) != expected or info.st_nlink != 1:
                    raise PipelineError("pinned_snapshot_changed")
        except OSError:
            raise PipelineError("pinned_snapshot_unavailable") from None

    def _union(self, table="records"):
        return " UNION ALL ".join(f"SELECT * FROM p{i}.{table}" for i in range(len(self.partitions)))

    def _fetch(self, sql: str, values=()):
        if self.connection is None:
            raise PipelineError("reader_session_not_open")
        self._stable()
        try:
            rows = self.connection.execute(sql, values).fetchall()
        except sqlite3.DatabaseError:
            raise PipelineError("snapshot_query_failed") from None
        self._stable()
        return rows

    def query(self, *, kind=None, term="", offset=0, limit=50, module=None, domain=None, record_ids=None):
        if (type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 200
                or not isinstance(term, str) or len(term) > 200):
            raise PipelineError("query_budget_invalid")
        where, args = [], []
        if record_ids is not None:
            if not isinstance(record_ids, list) or not 1 <= len(record_ids) <= 100 or any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in record_ids) or len(set(record_ids)) != len(record_ids):
                raise PipelineError("record_identity_selector_invalid")
            where.append("id IN (" + ",".join("?" for _ in record_ids) + ")")
            args.extend(record_ids)
        for column, value in (("kind", kind), ("module", module)):
            if value is not None:
                if not isinstance(value, str) or len(value) > 256:
                    raise PipelineError("query_selector_invalid")
                where.append(column + "=?")
                args.append(value)
        if term:
            where.append("instr(lower(name),lower(?))>0")
            args.append(term)
        if domain is not None:
            if not isinstance(domain, str) or len(domain) > 120:
                raise PipelineError("query_selector_invalid")
            where.append("id IN (SELECT id FROM (" + self._union("domains") + ") WHERE domain=?)")
            args.append(domain)
        expression = " WHERE " + " AND ".join(where) if where else ""
        table = "(" + self._union() + ")"
        total = self._fetch("SELECT count(*) FROM " + table + expression, args)[0][0]
        rows = self._fetch("SELECT payload FROM " + table + expression + " ORDER BY id LIMIT ? OFFSET ?", (*args, limit, offset))
        records = [json.loads(x[0]) for x in rows]
        result = {"snapshotId": self.snapshot_id, "analysisSpecId": self.metadata["analysisSpecId"],
                  "sourceFingerprint": self.metadata["sourceFingerprint"], "scopeDigest": self.metadata["coverage"].get("scopeDigest"),
                  "coverage": self.metadata["coverage"], "records": records, "total": total, "offset": offset,
                  "returned": len(records), "truncated": offset + len(records) < total,
                  "queryDigest": adapters.identifier("query", kind, term, module, domain, sorted(record_ids) if record_ids else None),
                  "nextOffset": offset + len(records) if offset + len(records) < total else None}
        privacy_guard.ensure_public_safe(result, context_roots=(self.workspace,))
        if len(_json(result)) > 2 * 1024 * 1024:
            raise PipelineError("query_response_budget_exceeded")
        return result

    def coverage(self, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise PipelineError("coverage_page_invalid")
        data = _load(self.directory / "coverage.json", 128 * 1024 * 1024, self.directory)
        rows = data["entries"] + data["frontiers"]
        selected = rows[offset:offset+limit]
        next_offset = offset + len(selected) if offset + len(selected) < len(rows) else None
        return {"snapshotId": self.snapshot_id, "sourceFingerprint": self.metadata["sourceFingerprint"],
            "analysisSpecId": self.metadata["analysisSpecId"], "scopeDigest": data["scopeDigest"],
            "summary": data["summary"], "entries": selected, "total": len(rows), "offset": offset,
            "returned": len(selected), "nextOffset": next_offset, "truncated": next_offset is not None,
            "queryDigest": adapters.identifier("source-coverage"), "completeness": "PARTIAL"}

    def get_record(self, record_id):
        if not isinstance(record_id, str) or not 1 <= len(record_id) <= 256:
            raise PipelineError("record_selector_invalid")
        rows = self._fetch("SELECT payload FROM (" + self._union() + ") WHERE id=? LIMIT 2", (record_id,))
        if len(rows) > 1:
            raise PipelineError("duplicate_record_identity")
        result = json.loads(rows[0][0]) if rows else None
        privacy_guard.ensure_public_safe(result, context_roots=(self.workspace,))
        return result

    def file_facts(self, relative):
        rows = self._fetch("SELECT facts FROM (" + self._union("files") + ") WHERE path=? LIMIT 2", (relative,))
        return json.loads(rows[0][0]) if len(rows) == 1 else None

    def modules(self, *, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise PipelineError("query_budget_invalid")
        rows = self._fetch("SELECT module,count(*) FROM (" + self._union() + ") GROUP BY module ORDER BY module LIMIT ? OFFSET ?", (limit, offset))
        total = self._fetch("SELECT count(DISTINCT module) FROM (" + self._union() + ")")[0][0]
        modules = []
        for mid, count in rows:
            record = self.query(module=mid, limit=1)["records"][0]
            modules.append({"id": mid, "path": record.get("modulePath", "."), "recordCount": count})
        return {"snapshotId": self.snapshot_id, "modules": modules, "total": total,
                "nextOffset": offset + len(modules) if offset + len(modules) < total else None}

    def iter_records(self, *, kind=None, module=None, domain=None, page_size=100) -> Iterator[dict[str, Any]]:
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise PipelineError("query_budget_invalid")
        where, args = [], []
        for column, value in (("kind", kind), ("module", module)):
            if value is not None:
                if not isinstance(value, str) or len(value) > 256:
                    raise PipelineError("query_selector_invalid")
                where.append(column + "=?")
                args.append(value)
        if domain is not None:
            if not isinstance(domain, str) or len(domain) > 120:
                raise PipelineError("query_selector_invalid")
            where.append("id IN (SELECT id FROM (" + self._union("domains") + ") WHERE domain=?)")
            args.append(domain)
        last = ""
        while True:
            expression = " AND ".join([*where, "id>?"])
            rows = self._fetch("SELECT id,payload FROM (" + self._union() + ") WHERE " + expression + " ORDER BY id LIMIT ?", (*args, last, page_size))
            if not rows:
                return
            for rid, encoded in rows:
                record = json.loads(encoded)
                privacy_guard.ensure_public_safe(record, context_roots=(self.workspace,))
                yield record
                last = rid

    def read_policy_records(self, *, domain=None, max_rules=10000):
        import pipeline_policy
        if type(max_rules) is not int or not 1 <= max_rules <= 10000:
            raise PipelineError("policy_query_budget_invalid")
        self._stable()
        value = _load(self.directory / "policy.json", 64 * 1024 * 1024, self.workspace)
        if pipeline_policy.policy_ruleset_digest(value) != value.get("rulesetDigest"):
            raise PipelineError("policy_ruleset_integrity_failed")
        value["sourceLastVerifiedAt"] = self.metadata.get("sourceLastVerifiedAt", value.get("sourceLastVerifiedAt"))
        if len(value["rules"]) > max_rules:
            raise PipelineError("policy_complete_evaluation_budget_exceeded")
        if domain is not None:
            if not isinstance(domain, str) or not 1 <= len(domain) <= 120:
                raise PipelineError("query_selector_invalid")
            value["rules"] = [r for r in value["rules"] if domain in _domains(r)]
            evidence_ids = {eid for rule in value["rules"] for eid in rule.get("sourceAssertionIds", [])}
            value["evidence"] = [e for e in value["evidence"] if e["id"] in evidence_ids]
            # Do not infer a closed domain from filtered classifications.
            value["coverage"] = {**value["coverage"], "complete": False, "unknownDenominator": True,
                                 "analyzedRules": len(value["rules"]),
                                 "reasons": [*value["coverage"].get("reasons", []), "domain_filter_not_coverage_closure"]}
            value["rulesetDigest"] = pipeline_policy.policy_ruleset_digest(value)
        privacy_guard.ensure_public_safe(value, context_roots=(self.workspace,))
        self._stable()
        return value


def open_reader(workspace_path, snapshot_id=None):
    return SnapshotReader(workspace_path, snapshot_id)


def status(workspace_path, snapshot_id=None):
    workspace, config = _config(workspace_path)
    if not _state(workspace).get("currentSnapshot") and snapshot_id is None:
        return {"status": "not_ready", "workspaceId": config["workspaceId"], "snapshotId": None,
                "pendingRecoveryRuns": len(_receipts(workspace))}
    with open_reader(workspace, snapshot_id) as reader:
        result = dict(reader.metadata)
    result.update(status="ready", pendingRecoveryRuns=len(_receipts(workspace)))
    if result["pendingRecoveryRuns"]:
        result["status"] = "recovery_required"
    privacy_guard.ensure_public_safe(result, context_roots=(workspace,))
    return result


def query(workspace_path, snapshot_id=None, **selectors):
    with open_reader(workspace_path, snapshot_id) as reader:
        return reader.query(**selectors)


def modules(workspace_path, snapshot_id=None, **selectors):
    with open_reader(workspace_path, snapshot_id) as reader:
        return reader.modules(**selectors)


def get_record(workspace_path, snapshot_id=None, record_id=None):
    with open_reader(workspace_path, snapshot_id) as reader:
        return reader.get_record(record_id)


def read_policy_records(workspace_path, snapshot_id=None, **selectors):
    with open_reader(workspace_path, snapshot_id) as reader:
        return reader.read_policy_records(**selectors)


def iter_records(workspace_path, snapshot_id=None, **selectors):
    with open_reader(workspace_path, snapshot_id) as reader:
        yield from reader.iter_records(**selectors)
