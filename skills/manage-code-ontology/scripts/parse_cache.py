"""Private, disposable parse-operation cache. No source text or network access."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_OPERATIONS = 300_000
_ALLOWED_METHODS = {"add_node", "add_edge", "add_warning"}


class CacheError(ValueError):
    """Sanitized cache boundary failure."""


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _private(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if _linked(info) or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise CacheError("Unsafe parse cache entry.")
    if not directory and info.st_nlink != 1:
        raise CacheError("Unsafe parse cache entry.")
    if os.name != "nt" and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
        raise CacheError("Parse cache requires owner-only access.")
    return info


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class ParseCache:
    def __init__(self, directory: Path, repository: Path):
        raw = directory.expanduser().absolute()
        # Reject an existing link at every boundary before mkdir/resolve.
        for part in (raw, *raw.parents):
            if part.exists() or part.is_symlink():
                if _linked(part.lstat()):
                    raise CacheError("Linked parse cache boundary.")
        repo = repository.resolve()
        resolved = raw.resolve()
        if resolved == repo or repo in resolved.parents or resolved in repo.parents:
            raise CacheError("Parse cache must be separate from source.")
        raw.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private(raw, directory=True)
        self.directory = raw
        self.hits = 0
        self.misses = 0
        self.rejected = 0
        key_path = raw / "key.bin"
        try:
            descriptor = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(os.urandom(32))
                handle.flush()
                os.fsync(handle.fileno())
        self.key = self._read(key_path, 32)
        if len(self.key) != 32:
            raise CacheError("Invalid private parse cache key.")

    def _read(self, path: Path, limit: int) -> bytes:
        _private(self.directory, directory=True)
        before = _private(path)
        if before.st_size > limit:
            raise CacheError("Parse cache size limit.")
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or _linked(opened):
                raise CacheError("Parse cache changed while reading.")
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        final = _private(path)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if len(raw) > limit or identity(before) != identity(after) or identity(after) != identity(final):
            raise CacheError("Parse cache changed while reading.")
        return raw

    @staticmethod
    def key_for(relative_path: str, source_hash: str, context: dict[str, Any]) -> str:
        return hashlib.sha256(_canonical({"path": relative_path, "source": source_hash, "context": context})).hexdigest()

    def load(self, key: str) -> list[list[Any]] | None:
        path = self.directory / (key + ".json")
        if not path.exists() and not path.is_symlink():
            self.misses += 1
            return None
        try:
            value = json.loads(self._read(path, MAX_CACHE_BYTES).decode("utf-8"))
            if not isinstance(value, dict) or set(value) != {"schemaVersion", "key", "operations", "mac"}:
                raise CacheError("Invalid parse cache.")
            ops = value["operations"]
            expected = hmac.new(self.key, _canonical({"key": key, "operations": ops}), hashlib.sha256).hexdigest()
            if value["schemaVersion"] != 1 or value["key"] != key or not isinstance(value["mac"], str) or not hmac.compare_digest(expected, value["mac"]):
                raise CacheError("Invalid parse cache authentication.")
            if not isinstance(ops, list) or len(ops) > MAX_OPERATIONS:
                raise CacheError("Invalid parse cache operations.")
            for op in ops:
                if not isinstance(op, list) or len(op) != 3 or op[0] not in _ALLOWED_METHODS or not isinstance(op[1], list) or not isinstance(op[2], dict):
                    raise CacheError("Invalid parse cache operation.")
            self.hits += 1
            return ops
        except (OSError, ValueError, TypeError, RecursionError):
            self.rejected += 1
            self.misses += 1
            return None

    def save(self, key: str, operations: list[list[Any]]) -> None:
        if len(operations) > MAX_OPERATIONS:
            return  # Large files remain valid; only this optional optimization is skipped.
        value = {"schemaVersion": 1, "key": key, "operations": operations,
                 "mac": hmac.new(self.key, _canonical({"key": key, "operations": operations}), hashlib.sha256).hexdigest()}
        raw = _canonical(value)
        if len(raw) > MAX_CACHE_BYTES:
            return
        _private(self.directory, directory=True)
        destination = self.directory / (key + ".json")
        if destination.exists() or destination.is_symlink():
            _private(destination)
        descriptor, name = tempfile.mkstemp(prefix=".fragment-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            _private(self.directory, directory=True)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
