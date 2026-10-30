"""Local authorization for sealed knowledge; never trust roles in tool input.

The operator binds one principal alias to an MCP process using its environment.
This is an application boundary inside the OS account, not a remote identity
provider or a replacement for filesystem permissions. Offline copies cannot be
revoked. Missing, unsafe or invalid policy always denies access.
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

import companion

PRINCIPAL_ENV = "CODE_ONTOLOGY_PRINCIPAL"
ACTIONS = frozenset({"read_structure", "read_policy", "read_evidence", "export_html", "export_bundle", "manage_access", "manage_knowledge"})
MAX_ACL_BYTES = 64 * 1024
ALIAS = re.compile(r"[a-z][a-z0-9-]{0,63}")
SNAPSHOT = re.compile(r"[A-Za-z0-9_-]{1,100}")
# This stores validated policy data, never authorization decisions or profiles.
# Bump the validation version whenever schema/privacy validation semantics change.
_VALIDATION_VERSION = 1
_VALIDATION_CACHE_LIMIT = 64
_VALIDATION_CACHE = OrderedDict()
_VALIDATION_CACHE_LOCK = threading.RLock()


class AccessDenied(companion.CompanionError):
    pass


def _principal() -> str:
    value = os.environ.get(PRINCIPAL_ENV, "local-owner")
    if not ALIAS.fullmatch(value):
        raise AccessDenied("Knowledge access denied: invalid operator principal binding.")
    return value


def _validate(value: dict, *, private_profile: dict | None = None) -> dict:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "revision", "principals"} or value["schemaVersion"] != 1:
        raise AccessDenied("Knowledge access denied: invalid access policy.")
    if type(value["revision"]) is not int or not 1 <= value["revision"] <= 1_000_000_000:
        raise AccessDenied("Knowledge access denied: invalid access revision.")
    principals = value["principals"]
    if not isinstance(principals, dict) or not 1 <= len(principals) <= 100:
        raise AccessDenied("Knowledge access denied: invalid principal set.")
    for alias, grant in principals.items():
        if not isinstance(alias, str) or not ALIAS.fullmatch(alias) or not isinstance(grant, dict) or set(grant) != {"actions", "snapshots"}:
            raise AccessDenied("Knowledge access denied: invalid grant.")
        actions, snapshots = grant["actions"], grant["snapshots"]
        if (not isinstance(actions, list) or len(actions) > len(ACTIONS) or
                any(not isinstance(action, str) or action not in ACTIONS for action in actions)):
            raise AccessDenied("Knowledge access denied: invalid action set.")
        if (not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 100 or
                any(not isinstance(s, str) or (s != "*" and not SNAPSHOT.fullmatch(s)) for s in snapshots)):
            raise AccessDenied("Knowledge access denied: invalid snapshot set.")
    companion.privacy_guard.ensure_public_safe(value, profile=private_profile)
    return value


def _read(workspace_path) -> dict:
    try:
        workspace = companion._resolve_existing_dir(workspace_path, "Pipeline workspace")
        path = workspace / "access.json"
        for parent in (path, *path.parents):
            if companion._is_link_like(parent.lstat()):
                raise AccessDenied("Knowledge access denied: linked policy boundary.")
        info = path.lstat()
        guard = companion.privacy_guard
        guard._check_private_file_metadata(info)
        if not 1 <= info.st_size <= MAX_ACL_BYTES:
            raise AccessDenied("Knowledge access denied: access policy size.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            guard._check_private_file_metadata(opened)
            if companion.core._stable_file_metadata(info) != companion.core._stable_file_metadata(opened) or not companion.core._same_file(info, opened):
                raise AccessDenied("Knowledge access denied: policy changed.")
            security = guard._windows_profile_security(handle.fileno()) if os.name == "nt" else None
            content = handle.read(MAX_ACL_BYTES + 1)
            if os.name == "nt" and guard._windows_profile_security(handle.fileno()) != security:
                raise AccessDenied("Knowledge access denied: policy permissions changed.")
            after = os.fstat(handle.fileno())
        final = path.lstat()
        guard._check_private_file_metadata(final)
        if (len(content) > MAX_ACL_BYTES or not companion.core._same_file(opened, final) or
            companion.core._stable_file_metadata(opened) != companion.core._stable_file_metadata(after) or
            companion.core._stable_file_metadata(opened) != companion.core._stable_file_metadata(final)):
            raise AccessDenied("Knowledge access denied: policy changed.")
        # File safety and the full raw-byte digest are checked before every cache
        # lookup. Metadata alone cannot detect an in-place rewrite with restored
        # mtime, and a previous valid policy never makes a later unsafe read safe.
        content_digest = hashlib.sha256(content).digest()
        profile = guard.load_profile()
        if profile is None:
            # None means autoload to ensure_public_safe. Preserve that behavior
            # without caching an ambiguous, potentially changing profile context.
            return _validate(json.loads(content.decode("utf-8")))
        # Keep the fingerprint and the full validation bound to the same private
        # copy. A caller mutating a loader's dictionary cannot change this copy.
        profile = guard._validated_profile(copy.deepcopy(profile))
        profile_digest = hashlib.sha256(companion._json_bytes(profile)).digest()
        identity = (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid,
                    opened.st_gid, opened.st_nlink, *companion.core._stable_file_metadata(opened),
                    getattr(opened, "st_ctime_ns", int(opened.st_ctime * 1_000_000_000)),
                    getattr(opened, "st_file_attributes", 0), security)
        key = (str(path), identity, content_digest, _VALIDATION_VERSION, profile_digest)
        with _VALIDATION_CACHE_LOCK:
            cached = _VALIDATION_CACHE.get(key)
            if cached is not None:
                _VALIDATION_CACHE.move_to_end(key)
                return copy.deepcopy(cached)
        value = _validate(json.loads(content.decode("utf-8")), private_profile=profile)
        with _VALIDATION_CACHE_LOCK:
            _VALIDATION_CACHE[key] = copy.deepcopy(value)
            _VALIDATION_CACHE.move_to_end(key)
            while len(_VALIDATION_CACHE) > _VALIDATION_CACHE_LIMIT:
                _VALIDATION_CACHE.popitem(last=False)
        return value
    except AccessDenied:
        raise
    except (OSError, ValueError, TypeError, companion.CompanionError, companion.privacy_guard.PrivacyError):
        raise AccessDenied("Knowledge access denied: private access policy is unavailable.") from None


def initialize_access(workspace_path) -> dict:
    """Create the private owner grant once, only from authorized initialization."""
    workspace = companion._resolve_existing_dir(workspace_path, "Pipeline workspace")
    value = _validate({"schemaVersion": 1, "revision": 1, "principals": {
        _principal(): {"actions": sorted(ACTIONS), "snapshots": ["*"]}}})
    path = workspace / "access.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as handle:
        companion.privacy_guard._check_private_file_metadata(os.fstat(handle.fileno()))
        security = companion.privacy_guard._windows_profile_security(handle.fileno()) if os.name == "nt" else None
        handle.write(companion._json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
        if os.name == "nt" and companion.privacy_guard._windows_profile_security(handle.fileno()) != security:
            raise AccessDenied("Knowledge access denied: policy permissions changed while writing.")
    return _read(workspace)


def authorize(workspace_path, action: str, snapshot_id: str | None = None) -> dict:
    if action not in ACTIONS:
        raise AccessDenied("Knowledge access denied: unknown permission.")
    value = _read(workspace_path)
    grant = value["principals"].get(_principal())
    if not grant or action not in grant["actions"]:
        raise AccessDenied("Knowledge access denied for this operation.")
    if "*" not in grant["snapshots"] and (snapshot_id is None or snapshot_id not in grant["snapshots"]):
        raise AccessDenied("Knowledge access denied for this snapshot.")
    return {"decision": "allow", "revision": value["revision"],
            "policyDigest": hashlib.sha256(companion._json_bytes(value)).hexdigest()}


def authorize_many(workspace_path, actions: tuple[str, ...] | list[str], snapshot_id: str | None = None) -> dict:
    """Require every permission against one freshly verified policy observation.

    This is one bounded decision, not a reusable grant or authorization cache.
    Subsequent calls read the policy bytes, file safety and privacy profile again.
    A request already observing a valid policy may finish; later checkpoints and
    final publication still re-observe policy changes.
    """
    if type(actions) not in (tuple, list):
        raise AccessDenied("Knowledge access denied: invalid permission set.")
    # Copy the caller's bounded sequence before I/O. No caller mutation can
    # reduce the permissions required by this observation.
    requested = tuple(actions[:len(ACTIONS)+1])
    if (not 1 <= len(requested) <= len(ACTIONS)
            or any(type(action) is not str or action not in ACTIONS for action in requested)
            or len(set(requested)) != len(requested)):
        raise AccessDenied("Knowledge access denied: invalid permission set.")
    value = _read(workspace_path)
    grant = value["principals"].get(_principal())
    if not grant or not all(action in grant["actions"] for action in requested):
        raise AccessDenied("Knowledge access denied for this operation.")
    if "*" not in grant["snapshots"] and (snapshot_id is None or snapshot_id not in grant["snapshots"]):
        raise AccessDenied("Knowledge access denied for this snapshot.")
    return {"decision": "allow", "revision": value["revision"],
            "policyDigest": hashlib.sha256(companion._json_bytes(value)).hexdigest()}


def visible(workspace_path) -> bool:
    try:
        grant = _read(workspace_path)["principals"].get(_principal(), {})
        return bool(set(grant.get("actions", [])) & {"read_structure", "read_policy", "read_evidence"})
    except (AccessDenied, companion.privacy_guard.PrivacyError):
        return False


def legacy_owner_only() -> None:
    if _principal() != "local-owner":
        raise AccessDenied("Legacy workspaces are restricted to the local owner; use a registered pipeline grant.")


def publication_guard(workspace_path):
    """Serialize knowledge approval publication with supported grant updates."""
    return companion._snapshot_write_lock(companion._resolve_existing_dir(workspace_path, "Pipeline workspace"))


def update_access(workspace_path, principal: str, actions: list[str], snapshots: list[str]) -> dict:
    """Explicit local operator operation, deliberately absent from MCP tools."""
    workspace = companion._resolve_existing_dir(workspace_path, "Pipeline workspace")
    with companion._snapshot_write_lock(workspace):
        authorize(workspace, "manage_access")
        value = _read(workspace)
        value["principals"][principal] = {"actions": actions, "snapshots": snapshots}
        value["revision"] += 1
        _validate(value)
        if not any("manage_access" in grant["actions"] and "*" in grant["snapshots"] for grant in value["principals"].values()):
            raise AccessDenied("Retain at least one access administrator.")
        # Check private temporary-file permissions before writing grant data.
        from pipeline_store import _atomic
        _atomic(workspace / "access.json", value)
        _read(workspace)
        return {"status": "ok", "revision": value["revision"]}
