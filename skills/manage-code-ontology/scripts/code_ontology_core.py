#!/usr/bin/env python3
"""Build and explore a privacy-preserving local code ontology.

This utility uses only the Python standard library. It performs static analysis;
it never imports, builds, or executes the target repository.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import html
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter, deque
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


# Preserve the Explorer 1.0 vocabulary and URIs so previously exported RDF
# remains importable without a migration. Companion provenance uses a separate
# namespace in companion.py.
SCHEMA_VERSION = "1.0"
QUALITY_CONTRACT_VERSION = "1.0"
PLUGIN_VERSION = "0.5.2"
ONTOLOGY_NS = "https://battle-doll.github.io/code-ontology-explorer/schema#"
VISUALIZATION_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
VISUALIZATION_MAX_VISIBLE_NODES = 240
VISUALIZATION_DIFF_ITEM_LIMIT = 500
VISUALIZATION_VENDOR_ASSETS = {
    "cytoscape": (
        "vendor/cytoscape-3.34.0.min.js",
        "9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3",
    ),
    "elk": (
        "vendor/elkjs-0.12.0.bundled.js",
        "1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3",
    ),
}
SUPPORTED_SUFFIXES = {".java": "Java", ".py": "Python"}
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_FILES = 25_000
MAX_TOTAL_SOURCE_BYTES = 512 * 1024 * 1024
MAX_GRAPH_NODES = 500_000
MAX_GRAPH_EDGES = 1_000_000
MAX_IMPACT_RESULTS = 2_000
MAX_EDGE_EVIDENCE_ITEMS = 16
MAX_EVIDENCE_LIMITATIONS = 16
MAX_EVIDENCE_PATH_LENGTH = 4_096
MAX_EVIDENCE_LINE = 10_000_000
MAX_PYTHON_AST_NODES = 250_000
MAX_PYTHON_AST_DEPTH = 200
WINDOWS_REPARSE_POINT = 0x400
EVIDENCE_BASES = {
    "direct_syntax",
    "resolved_static",
    "framework_semantic",
    "name_heuristic",
}
RUNTIME_STATUSES = {"not_applicable", "runtime_unknown"}
RUNTIME_SENSITIVE_RELATIONSHIPS = {
    "INJECTS",
    "MANAGED_AS",
    "MAY_BE_PROXIED_BY",
    "DECLARES_BEAN",
    "GUARDS_RUNTIME_BRANCH",
}
EDGE_EVIDENCE_DEFAULTS = {
    "DECLARES": ("core.declares", "direct_syntax"),
    "IMPORTS": ("core.imports", "direct_syntax"),
    "EXTENDS": ("core.extends", "resolved_static"),
    "IMPLEMENTS": ("java.implements", "resolved_static"),
    "ANNOTATED_BY": ("java.annotation", "direct_syntax"),
    "DECORATED_BY": ("python.decorator", "direct_syntax"),
    "INJECTS": ("java.spring.injection", "framework_semantic"),
    "DECLARES_BEAN": ("java.spring.bean_factory", "framework_semantic"),
    "MANAGED_AS": ("java.spring.managed", "framework_semantic"),
    "MAY_BE_PROXIED_BY": ("java.spring.proxy_signal", "framework_semantic"),
    "CALLS": ("core.calls", "resolved_static"),
    "HAS_PIPELINE_ROLE": ("python.pipeline_role", "name_heuristic"),
    "READS_POLICY_LEAF": ("java.policy.read", "direct_syntax"),
    "DECLARES_RUNTIME_BRANCH": ("java.policy.branch", "direct_syntax"),
    "GUARDS_RUNTIME_BRANCH": ("java.policy.guard", "resolved_static"),
}
EXCLUDED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".gradle",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "target",
    "build",
    "dist",
    "out",
    ".next",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "coverage",
}
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".kdbx",
}
SPRING_STEREOTYPES = {
    "Component",
    "Service",
    "Repository",
    "Controller",
    "RestController",
    "Configuration",
    "SpringBootApplication",
}
SPRING_INJECTION = {"Autowired", "Inject", "Resource"}
SPRING_AOP = {"Aspect", "Before", "After", "AfterReturning", "AfterThrowing", "Around", "Pointcut"}
SPRING_PROXY = {
    "Transactional",
    "Async",
    "Cacheable",
    "CacheEvict",
    "CachePut",
    "Secured",
    "PreAuthorize",
    "PostAuthorize",
    "Retryable",
}
JAVA_ANNOTATION_PATTERN = (
    r"@[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
    r"(?:\s*\((?:[^()]|\([^()]*\))*\))?"
)
SPRING_ANNOTATION_TYPES = {
    "Component": {"org.springframework.stereotype.Component"},
    "Service": {"org.springframework.stereotype.Service"},
    "Repository": {"org.springframework.stereotype.Repository"},
    "Controller": {"org.springframework.stereotype.Controller"},
    "RestController": {"org.springframework.web.bind.annotation.RestController"},
    "Configuration": {"org.springframework.context.annotation.Configuration"},
    "SpringBootApplication": {"org.springframework.boot.autoconfigure.SpringBootApplication"},
    "Bean": {"org.springframework.context.annotation.Bean"},
    "Autowired": {"org.springframework.beans.factory.annotation.Autowired"},
    "Inject": {"jakarta.inject.Inject", "javax.inject.Inject"},
    "Resource": {"jakarta.annotation.Resource", "javax.annotation.Resource"},
    "Aspect": {"org.aspectj.lang.annotation.Aspect"},
    "Before": {"org.aspectj.lang.annotation.Before"},
    "After": {"org.aspectj.lang.annotation.After"},
    "AfterReturning": {"org.aspectj.lang.annotation.AfterReturning"},
    "AfterThrowing": {"org.aspectj.lang.annotation.AfterThrowing"},
    "Around": {"org.aspectj.lang.annotation.Around"},
    "Pointcut": {"org.aspectj.lang.annotation.Pointcut"},
    "Transactional": {
        "org.springframework.transaction.annotation.Transactional",
        "jakarta.transaction.Transactional",
        "javax.transaction.Transactional",
    },
    "Async": {"org.springframework.scheduling.annotation.Async"},
    "Cacheable": {"org.springframework.cache.annotation.Cacheable"},
    "CacheEvict": {"org.springframework.cache.annotation.CacheEvict"},
    "CachePut": {"org.springframework.cache.annotation.CachePut"},
    "Secured": {"org.springframework.security.access.annotation.Secured"},
    "PreAuthorize": {"org.springframework.security.access.prepost.PreAuthorize"},
    "PostAuthorize": {"org.springframework.security.access.prepost.PostAuthorize"},
    "Retryable": {"org.springframework.retry.annotation.Retryable"},
}
JAVA_LANG_TYPES = {
    "void",
    "boolean",
    "byte",
    "short",
    "int",
    "long",
    "float",
    "double",
    "char",
    "String",
    "Object",
    "Integer",
    "Long",
    "Double",
    "Float",
    "Short",
    "Byte",
    "Boolean",
    "Character",
    "Number",
    "Enum",
    "Record",
    "Class",
    "Throwable",
    "Exception",
    "RuntimeException",
    "Iterable",
}
JAVA_UTIL_TYPES = {
    "Collection",
    "Collections",
    "List",
    "ArrayList",
    "LinkedList",
    "Set",
    "HashSet",
    "Map",
    "HashMap",
    "Optional",
    "Queue",
    "Deque",
    "Iterator",
}
JAVA_TYPE_RE = re.compile(
    rf"(?P<annotations>(?:{JAVA_ANNOTATION_PATTERN}\s*)*)"
    r"(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed)\s+)*"
    r"(?P<kind>class|interface|enum|record)\s+(?P<name>[A-Za-z_]\w*)",
    re.MULTILINE,
)
JAVA_METHOD_RE = re.compile(
    r"^[ \t]*"
    rf"(?P<annotations>(?:{JAVA_ANNOTATION_PATTERN}\s*)*)"
    r"(?:(?:public|protected|private|abstract|final|static|synchronized|native|default|strictfp)\s+)*"
    r"(?!return\b|throw\b|new\b|if\b|for\b|while\b|switch\b|catch\b|do\b|else\b)"
    r"(?:<[^>{};]+>\s+)?"
    r"(?P<return>[A-Za-z_][\w.$<>\[\], ?]*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>(?:[^()]|\([^()]*\))*)\)"
    r"\s*(?:throws\s+[^{;]+)?(?P<ending>\{|;)",
    re.MULTILINE,
)
JAVA_FIELD_RE = re.compile(
    rf"(?P<annotations>(?:{JAVA_ANNOTATION_PATTERN}\s*)+)"
    r"(?:(?:public|protected|private|final|static|volatile|transient)\s+)*"
    r"(?P<type>[A-Za-z_][\w.$<>\[\], ?]*)\s+(?P<name>[A-Za-z_]\w*)\s*(?:=[^;]*)?;",
    re.MULTILINE,
)
JAVA_ANNOTATION_RE = re.compile(r"@([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
JAVA_POLICY_ACCESSORS = ("policyBool", "policyDecimal", "policyInt")
JAVA_POLICY_LEAF_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*){1,15}"
)
JAVA_POLICY_READ_RE = re.compile(
    r"(?:(?P<variable>[A-Za-z_]\w*)\s*=\s*)?"
    r"(?:this\s*\.\s*)?"
    r"(?P<accessor>" + "|".join(JAVA_POLICY_ACCESSORS) + r")\s*\("
    r"(?:(?![;{}]).)*?"
    r'"(?P<leaf>[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*){1,15})"',
    re.DOTALL,
)
JAVA_ASSIGNMENT_RE = re.compile(
    r"(?:^|[;{}])\s*"
    r"(?:final\s+)?"
    r"(?:[A-Za-z_][\w.$<>\[\], ?]*\s+)?"
    r"(?P<variable>[A-Za-z_]\w*)\s*=(?!=)"
    r"(?P<expression>[^;{}]*);",
    re.MULTILINE,
)
JAVA_CONTROL_RE = re.compile(r"\b(?P<kind>if|while|switch|for)\s*\(")
JAVA_CALL_RE = re.compile(
    r"(?<![\w$.])"
    r"(?:(?P<qualifier>[A-Za-z_]\w*)\s*\.\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\("
)
JAVA_ANNOTATION_TOKEN_RE = re.compile(r"@[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
JAVA_NON_CALL_KEYWORDS = {
    "assert",
    "catch",
    "do",
    "else",
    "for",
    "if",
    "new",
    "super",
    "switch",
    "synchronized",
    "this",
    "throw",
    "try",
    "while",
}


class OntologyError(RuntimeError):
    """Expected, user-actionable failure."""


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _resolve_dir(raw_path: str, label: str) -> Path:
    raw = Path(raw_path).expanduser()
    try:
        directory_stat = raw.lstat()
    except OSError:
        raise OntologyError(f"{label} is not a readable directory.")
    if _is_link_like(directory_stat):
        raise OntologyError(f"{label} may not be a symbolic link or reparse point.")
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise OntologyError(f"{label} is not a readable directory.")
    return raw.resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_sensitive_file(path: Path) -> bool:
    lowered = path.name.lower()
    normalized_stem = path.stem.lower().replace("-", "_").replace(".", "_")
    if lowered in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    sensitive_stems = {
        "api_key",
        "access_token",
        "auth_token",
        "credential",
        "credentials",
        "id_ed25519",
        "id_rsa",
        "key",
        "private_key",
        "secret",
        "secrets",
        "token",
    }
    return (
        lowered.startswith(".env.")
        or "credential" in lowered
        or "secret" in lowered
        or normalized_stem in sensitive_stems
        or normalized_stem.endswith(("_token", "_secret", "_key", "_credentials"))
    )


def _is_link_like(file_stat: os.stat_result) -> bool:
    attributes = getattr(file_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(file_stat.st_mode) or bool(attributes & WINDOWS_REPARSE_POINT)


def discover_sources(repo: Path) -> tuple[list[Path], Counter[str]]:
    """Return safe source files and skip statistics without following symlinks."""

    sources: list[Path] = []
    skipped: Counter[str] = Counter()
    total_source_bytes = 0
    for current, directories, filenames in os.walk(repo, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(directories):
            candidate = current_path / name
            if name in EXCLUDED_DIRECTORIES:
                skipped["excluded_directory"] += 1
                continue
            try:
                directory_stat = candidate.lstat()
            except OSError:
                skipped["unreadable"] += 1
                continue
            if _is_link_like(directory_stat):
                skipped["symlink_or_reparse"] += 1
            elif not stat.S_ISDIR(directory_stat.st_mode):
                skipped["special_file"] += 1
            else:
                kept_dirs.append(name)
        directories[:] = kept_dirs

        for name in sorted(filenames):
            candidate = current_path / name
            if _is_sensitive_file(candidate):
                skipped["sensitive_name"] += 1
                continue
            if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                file_stat = candidate.lstat()
            except OSError:
                skipped["unreadable"] += 1
                continue
            if _is_link_like(file_stat):
                skipped["symlink_or_reparse"] += 1
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                skipped["special_file"] += 1
                continue
            size = file_stat.st_size
            if size > MAX_SOURCE_BYTES:
                skipped["too_large"] += 1
                continue
            if len(sources) >= MAX_SOURCE_FILES:
                raise OntologyError(
                    f"Repository exceeds the {MAX_SOURCE_FILES}-source-file limit."
                )
            if total_source_bytes + size > MAX_TOTAL_SOURCE_BYTES:
                raise OntologyError(
                    "Repository exceeds the total supported source-byte limit."
                )
            sources.append(candidate)
            total_source_bytes += size
    return sorted(sources), skipped


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    try:
        return os.path.samestat(left, right)
    except (AttributeError, OSError):
        return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _stable_file_metadata(file_stat: os.stat_result) -> tuple[int, ...]:
    metadata = (
        file_stat.st_size,
        getattr(file_stat, "st_mtime_ns", int(file_stat.st_mtime * 1_000_000_000)),
    )
    if os.name == "nt":
        # Python 3.12 deprecates st_ctime[_ns] on Windows, where it still means
        # creation time and may differ between path and handle stat calls. File
        # identity is checked separately; size and mtime remain change guards.
        return metadata
    return metadata + (
        getattr(file_stat, "st_ctime_ns", int(file_stat.st_ctime * 1_000_000_000)),
    )


def _safe_read_bytes(path: Path) -> bytes:
    try:
        initial_stat = path.lstat()
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        raise OntologyError(f"Could not read {path.name}: {reason}") from exc
    if _is_link_like(initial_stat) or not stat.S_ISREG(initial_stat.st_mode):
        raise OntologyError(f"Refusing to read a linked or non-regular source: {path.name}")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        raise OntologyError(f"Could not read {path.name}: {reason}") from exc
    try:
        handle = os.fdopen(descriptor, "rb", closefd=True)
    except Exception:
        os.close(descriptor)
        raise
    try:
        with handle:
            opened_stat = os.fstat(handle.fileno())
            if _is_link_like(opened_stat) or not stat.S_ISREG(opened_stat.st_mode):
                raise OntologyError(f"Refusing to read a non-regular source: {path.name}")
            if not _same_file(initial_stat, opened_stat):
                raise OntologyError(f"Source changed before it could be read: {path.name}")
            if _stable_file_metadata(initial_stat) != _stable_file_metadata(opened_stat):
                raise OntologyError(f"Source changed before it could be read: {path.name}")
            if opened_stat.st_size > MAX_SOURCE_BYTES:
                raise OntologyError(
                    f"Source exceeds the {MAX_SOURCE_BYTES}-byte limit: {path.name}"
                )
            raw = handle.read(MAX_SOURCE_BYTES + 1)
            final_stat = os.fstat(handle.fileno())
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        raise OntologyError(f"Could not read {path.name}: {reason}") from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise OntologyError(f"Source exceeds the {MAX_SOURCE_BYTES}-byte limit: {path.name}")
    if not _same_file(opened_stat, final_stat):
        raise OntologyError(f"Source changed while it was being read: {path.name}")
    if _stable_file_metadata(opened_stat) != _stable_file_metadata(final_stat):
        raise OntologyError(f"Source changed while it was being read: {path.name}")
    try:
        current_stat = path.lstat()
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        raise OntologyError(f"Could not verify {path.name}: {reason}") from exc
    if _is_link_like(current_stat) or not stat.S_ISREG(current_stat.st_mode):
        raise OntologyError(f"Refusing to read a linked or non-regular source: {path.name}")
    if not _same_file(final_stat, current_stat):
        raise OntologyError(f"Source changed while it was being read: {path.name}")
    if _stable_file_metadata(final_stat) != _stable_file_metadata(current_stat):
        raise OntologyError(f"Source changed while it was being read: {path.name}")
    return raw


def _safe_read(path: Path) -> str:
    raw = _safe_read_bytes(path)
    return raw.decode("utf-8", errors="replace")


def _node_id(language: str, kind: str, qualified_name: str) -> str:
    return f"{language.lower()}:{kind.lower()}:{qualified_name}"


def _line_span(source: str, start: int, end: int | None = None) -> tuple[int, int]:
    """Return a stable one-based line span without retaining source text."""

    bounded_start = max(0, min(int(start), len(source)))
    bounded_end = max(bounded_start, min(int(end if end is not None else start), len(source)))
    return source.count("\n", 0, bounded_start) + 1, source.count("\n", 0, bounded_end) + 1


def _portable_relative_path(value: str) -> bool:
    if (
        not value
        or len(value) > MAX_EVIDENCE_PATH_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value)
    ):
        return False
    normalized = value.replace("\\", "/")
    return not Path(normalized).is_absolute() and ".." not in normalized.split("/")


def _edge_evidence_key(item: dict[str, Any]) -> str:
    return json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _bounded_edge_evidence(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate, canonically order, and bound evidence independent of set order."""

    unique: dict[str, dict[str, Any]] = {}
    for item in values:
        key = _edge_evidence_key(item)
        unique.setdefault(key, item)
    return [unique[key] for key in sorted(unique)[:MAX_EDGE_EVIDENCE_ITEMS]]


def _normalized_edge_evidence(
    *,
    edge_type: str,
    rule_id: str | None,
    basis: str | None,
    runtime_status: str | None,
    path: str | None,
    line_start: int | None,
    line_end: int | None,
    limitations: Iterable[str] | None,
) -> dict[str, Any]:
    default_rule, default_basis = EDGE_EVIDENCE_DEFAULTS.get(
        edge_type,
        (f"core.{edge_type.casefold()}", "direct_syntax"),
    )
    selected_rule = rule_id or default_rule
    selected_basis = basis or default_basis
    selected_runtime = runtime_status or (
        "runtime_unknown" if edge_type in RUNTIME_SENSITIVE_RELATIONSHIPS else "not_applicable"
    )
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", selected_rule):
        raise OntologyError(f"Invalid relationship evidence rule identifier: {selected_rule}")
    if selected_basis not in EVIDENCE_BASES:
        raise OntologyError(f"Unsupported relationship evidence basis: {selected_basis}")
    if selected_runtime not in RUNTIME_STATUSES:
        raise OntologyError(f"Unsupported relationship runtime status: {selected_runtime}")

    item: dict[str, Any] = {
        "rule_id": selected_rule,
        "basis": selected_basis,
        "runtime_status": selected_runtime,
    }
    if isinstance(path, str) and _portable_relative_path(path):
        item["path"] = path.replace("\\", "/")
    if (
        isinstance(line_start, int)
        and not isinstance(line_start, bool)
        and 1 <= line_start <= MAX_EVIDENCE_LINE
    ):
        item["line_start"] = line_start
        selected_line_end = line_end if isinstance(line_end, int) else line_start
        item["line_end"] = min(
            MAX_EVIDENCE_LINE,
            max(line_start, int(selected_line_end)),
        )
    normalized_limitations = {
        value
        for value in (limitations or ())
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", value)
    }
    required_limitation = None
    if selected_runtime == "runtime_unknown":
        required_limitation = "runtime.activation_not_observed"
        normalized_limitations.add(required_limitation)
    bounded_limitations = sorted(normalized_limitations)[:MAX_EVIDENCE_LIMITATIONS]
    if required_limitation and required_limitation not in bounded_limitations:
        bounded_limitations[-1:] = [required_limitation]
        bounded_limitations.sort()
    if bounded_limitations:
        item["limitations"] = bounded_limitations
    return item


def _adapter_quality(language: str) -> dict[str, Any]:
    """Describe bounded analyzer support without implying completeness."""

    if language == "Java":
        return {
            "status": "partial",
            "capabilities": {
                "annotations": "partial",
                "calls": "partial",
                "declarations": "partial",
                "dependency_injection": "partial",
                "explicit_type_imports": "supported",
                "imports": "partial",
                "inheritance": "partial",
                "runtime_activation": "unsupported",
                "runtime_dispatch": "unsupported",
            },
            "unsupported_runtime": [
                "active_application_context",
                "dynamic_dispatch",
                "generated_code",
                "reflection",
                "runtime_conditions",
            ],
        }
    if language == "Python":
        return {
            "status": "partial",
            "capabilities": {
                "calls": "partial",
                "decorators": "partial",
                "declarations": "partial",
                "imports": "partial",
                "inheritance": "partial",
                "pipeline_roles": "partial",
                "runtime_dispatch": "unsupported",
                "runtime_imports": "unsupported",
            },
            "unsupported_runtime": [
                "dynamic_imports",
                "descriptor_dispatch",
                "generated_code",
                "monkey_patching",
                "runtime_metaprogramming",
            ],
        }
    return {
        "status": "unsupported",
        "capabilities": {},
        "unsupported_runtime": ["adapter_not_available"],
    }


class Graph:
    def __init__(self, repository_name: str) -> None:
        self.repository_name = repository_name
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str]] = set()
        self.edge_evidence: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self.warnings: list[dict[str, str]] = []

    def add_node(
        self,
        node_id: str,
        node_type: str,
        name: str,
        language: str,
        path: str | None = None,
        qualified_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        record: dict[str, Any] = {
            "id": node_id,
            "type": node_type,
            "name": name,
            "language": language,
        }
        if path:
            record["path"] = path
        if qualified_name:
            record["qualified_name"] = qualified_name
        if metadata:
            clean_metadata = {
                key: value
                for key, value in metadata.items()
                if value not in (None, "", [], {})
            }
            if clean_metadata:
                record["metadata"] = clean_metadata
        if node_id in self.nodes:
            current = self.nodes[node_id]
            if current.get("type") in {
                "ExternalModule",
                "ExternalType",
                "ExternalCallable",
            } and record.get("type") not in {
                "ExternalModule",
                "ExternalType",
                "ExternalCallable",
            }:
                current["type"] = record["type"]
            for key, value in record.items():
                if key not in current or not current[key]:
                    current[key] = value
        else:
            if len(self.nodes) >= MAX_GRAPH_NODES:
                raise OntologyError(
                    f"Ontology exceeds the {MAX_GRAPH_NODES}-node safety limit."
                )
            self.nodes[node_id] = record
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        rule_id: str | None = None,
        basis: str | None = None,
        runtime_status: str | None = None,
        path: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        limitations: Iterable[str] | None = None,
    ) -> None:
        if source != target:
            edge = (source, target, edge_type)
            if (
                edge not in self.edges
                and len(self.edges) >= MAX_GRAPH_EDGES
            ):
                raise OntologyError(
                    f"Ontology exceeds the {MAX_GRAPH_EDGES}-edge safety limit."
                )
            self.edges.add(edge)
            source_node = self.nodes.get(source, {})
            target_node = self.nodes.get(target, {})
            selected_path = path or source_node.get("path") or target_node.get("path")
            source_metadata = source_node.get("metadata", {})
            if not isinstance(source_metadata, dict):
                source_metadata = {}
            selected_line_start = line_start or source_metadata.get("line_start")
            selected_line_end = line_end or source_metadata.get("line_end")
            item = _normalized_edge_evidence(
                edge_type=edge_type,
                rule_id=rule_id,
                basis=basis,
                runtime_status=runtime_status,
                path=selected_path if isinstance(selected_path, str) else None,
                line_start=(
                    selected_line_start if isinstance(selected_line_start, int) else None
                ),
                line_end=(selected_line_end if isinstance(selected_line_end, int) else None),
                limitations=limitations,
            )
            existing = self.edge_evidence.setdefault(edge, [])
            if item not in existing:
                self.edge_evidence[edge] = _bounded_edge_evidence((*existing, item))

    def add_external_type(self, language: str, qualified_name: str) -> str:
        simple_name = qualified_name.rsplit(".", 1)[-1]
        return self.add_node(
            _node_id(language, "external_type", qualified_name),
            "ExternalType",
            simple_name,
            language,
            qualified_name=qualified_name,
        )

    def add_annotation(
        self,
        annotation: str,
        *,
        qualified_name: str | None = None,
        semantic_name: str | None = None,
    ) -> str:
        groups: list[str] = []
        if semantic_name in SPRING_STEREOTYPES:
            groups.append("SpringBean")
        if semantic_name in SPRING_INJECTION:
            groups.append("DependencyInjection")
        if semantic_name in SPRING_AOP:
            groups.append("AspectOrAdvice")
        if semantic_name in SPRING_PROXY:
            groups.append("ProxyOrInterceptor")
        identity = qualified_name or annotation
        return self.add_node(
            f"framework:annotation:{identity}",
            "FrameworkAnnotation",
            f"@{annotation}",
            "Framework",
            qualified_name=identity,
            metadata={"semantic_groups": groups},
        )

    def add_warning(self, relative_path: str, message: str) -> None:
        self.warnings.append({"path": relative_path, "message": message})

    def reconcile_references(self) -> None:
        """Redirect external Java placeholders to analyzed internal types."""

        internal_by_name: dict[tuple[str, str], str] = {}
        internal_by_simple: dict[tuple[str, str], list[str]] = {}
        for node_id, node in self.nodes.items():
            if node["type"] in {
                "Class",
                "Interface",
                "Enum",
                "Record",
                "Function",
                "AsyncFunction",
                "Method",
                "AsyncMethod",
            }:
                qualified_name = node.get("qualified_name")
                if qualified_name:
                    internal_by_name[(node["language"], qualified_name)] = node_id
                    internal_by_simple.setdefault(
                        (node["language"], node["name"]), []
                    ).append(node_id)
        redirects: dict[str, str] = {}
        for node_id, node in self.nodes.items():
            if node["type"] not in {"ExternalType", "ExternalCallable"}:
                continue
            qualified_name = node.get("qualified_name")
            target = internal_by_name.get((node["language"], qualified_name))
            if (
                target is None
                and node["type"] == "ExternalType"
                and node["language"] == "Java"
                and isinstance(qualified_name, str)
                and "." not in qualified_name
            ):
                candidates = internal_by_simple.get(("Java", node["name"]), [])
                if len(candidates) == 1:
                    target = candidates[0]
            if target:
                redirects[node_id] = target
        if not redirects:
            return
        reconciled: set[tuple[str, str, str]] = set()
        reconciled_evidence: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for source, target, edge_type in self.edges:
            new_source = redirects.get(source, source)
            new_target = redirects.get(target, target)
            if new_source != new_target:
                old_edge = (source, target, edge_type)
                new_edge = (new_source, new_target, edge_type)
                reconciled.add(new_edge)
                merged = reconciled_evidence.setdefault(new_edge, [])
                for item in self.edge_evidence.get(old_edge, []):
                    if item not in merged:
                        merged.append(item)
        self.edges = reconciled
        self.edge_evidence = {
            edge: _bounded_edge_evidence(items)
            for edge, items in reconciled_evidence.items()
        }
        for node_id in redirects:
            self.nodes.pop(node_id, None)

    def document(self, source_counts: Counter[str], skipped: Counter[str]) -> dict[str, Any]:
        self.reconcile_references()
        nodes = sorted(self.nodes.values(), key=lambda item: item["id"])
        edges = []
        for source, target, edge_type in sorted(self.edges):
            edge = (source, target, edge_type)
            evidence = _bounded_edge_evidence(self.edge_evidence.get(edge, []))
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "type": edge_type,
                    "evidence": evidence,
                }
            )
        documented_edges = sum(bool(edge["evidence"]) for edge in edges)
        span_documented_edges = sum(
            any("path" in item and "line_start" in item for item in edge["evidence"])
            for edge in edges
        )
        basis_counts = Counter(
            item["basis"] for edge in edges for item in edge["evidence"]
        )
        runtime_status_counts = Counter(
            item["runtime_status"] for edge in edges for item in edge["evidence"]
        )
        adapters = {
            language: {
                **_adapter_quality(language),
                "detected": language in source_counts,
            }
            for language in ("Java", "Python")
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _iso_now(),
            "generator": {"name": "Code Ontology Companion", "version": PLUGIN_VERSION},
            "repository": {
                "name": self.repository_name,
                "path_policy": "repository-relative-only",
            },
            "privacy": {
                "contains_source_text": False,
                "contains_comments": False,
                "contains_absolute_paths": False,
                "contains_file_hashes": False,
                "contains_arbitrary_string_literals": False,
                "contains_policy_identifiers": any(
                    node["type"] == "PolicyLeaf" for node in nodes
                ),
            },
            "statistics": {
                "source_files": dict(sorted(source_counts.items())),
                "nodes": len(nodes),
                "edges": len(edges),
                "node_types": dict(sorted(Counter(node["type"] for node in nodes).items())),
                "edge_types": dict(sorted(Counter(edge["type"] for edge in edges).items())),
                "skipped": dict(sorted(skipped.items())),
                "warnings": len(self.warnings),
            },
            "quality": {
                "contract_version": QUALITY_CONTRACT_VERSION,
                "relationship_evidence": {
                    "total_edges": len(edges),
                    "documented_edges": documented_edges,
                    "missing_evidence": len(edges) - documented_edges,
                    "coverage_percent": round(
                        (documented_edges * 100.0 / len(edges)) if edges else 100.0,
                        3,
                    ),
                    "source_span_edges": span_documented_edges,
                    "source_span_coverage_percent": round(
                        (span_documented_edges * 100.0 / len(edges)) if edges else 100.0,
                        3,
                    ),
                    "basis_counts": dict(sorted(basis_counts.items())),
                    "runtime_status_counts": dict(sorted(runtime_status_counts.items())),
                },
                "adapters": adapters,
                "interpretation": (
                    "Qualitative static evidence, not a probability or runtime verdict. "
                    "Unsupported and runtime-unknown capabilities require independent evidence."
                ),
            },
            "nodes": nodes,
            "edges": edges,
            "warnings": sorted(self.warnings, key=lambda item: (item["path"], item["message"])),
        }


def _annotations(text: str) -> list[str]:
    return sorted(set(JAVA_ANNOTATION_RE.findall(text)))


def _annotation_details(
    annotation: str,
    imports: dict[str, str],
    wildcard_imports: set[str],
    package_name: str,
    same_package_types: set[str] | None = None,
) -> tuple[str, str, str | None]:
    simple_name = annotation.rsplit(".", 1)[-1]
    qualified_name: str | None
    if "." in annotation:
        qualified_name = annotation
    else:
        qualified_name = imports.get(simple_name)
    accepted = SPRING_ANNOTATION_TYPES.get(simple_name, set())
    semantic_name = simple_name if qualified_name in accepted else None
    if (
        semantic_name is None
        and qualified_name is None
        and len(wildcard_imports) == 1
        and same_package_types is not None
        and simple_name not in same_package_types
    ):
        wildcard = next(iter(wildcard_imports))
        candidate = f"{wildcard}.{simple_name}"
        if candidate in accepted:
            qualified_name = candidate
            semantic_name = simple_name
    if qualified_name is None:
        qualified_name = f"{package_name}.{simple_name}" if package_name else simple_name
    return simple_name, qualified_name, semantic_name


def _resolved_annotations(
    text: str,
    imports: dict[str, str],
    wildcard_imports: set[str],
    package_name: str,
    same_package_types: set[str] | None = None,
) -> list[tuple[str, str, str | None]]:
    return [
        _annotation_details(
            annotation,
            imports,
            wildcard_imports,
            package_name,
            same_package_types,
        )
        for annotation in _annotations(text)
    ]


def _java_package_and_declared_types(source: str) -> tuple[str, set[str]]:
    stripped = _strip_java_comments_and_literals(source)
    package_match = re.search(r"^\s*package\s+([\w.]+)\s*;", stripped, re.MULTILINE)
    package_name = package_match.group(1) if package_match else ""
    return package_name, {match.group("name") for match in JAVA_TYPE_RE.finditer(stripped)}


def _strip_java_comments_and_literals(source: str) -> str:
    """Replace comments and string/char contents while keeping code positions."""

    result = list(source)
    index = 0
    state = "code"
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and next_char == "/":
                result[index] = result[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if char == "/" and next_char == "*":
                result[index] = result[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
            if source.startswith('"""', index):
                result[index] = result[index + 1] = result[index + 2] = " "
                state = "text_block"
                index += 3
                continue
            if char == '"':
                result[index] = " "
                state = "string"
            elif char == "'":
                result[index] = " "
                state = "char"
        elif state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                result[index] = " "
        elif state == "block_comment":
            if char == "*" and next_char == "/":
                result[index] = result[index + 1] = " "
                state = "code"
                index += 2
                continue
            if char != "\n":
                result[index] = " "
        elif state == "text_block":
            if source.startswith('"""', index):
                result[index] = result[index + 1] = result[index + 2] = " "
                state = "code"
                index += 3
                continue
            if char != "\n":
                result[index] = " "
        elif state in {"string", "char"}:
            quote_char = '"' if state == "string" else "'"
            if char == "\\":
                result[index] = " "
                if index + 1 < len(source):
                    if source[index + 1] != "\n":
                        result[index + 1] = " "
                    index += 2
                    continue
            if char == quote_char:
                result[index] = " "
                state = "code"
            elif char != "\n":
                result[index] = " "
        index += 1
    return "".join(result)


def _java_policy_scan_source(source: str) -> str:
    """Keep code and safe dotted policy identifiers, masking all other literals."""

    result = list(source)
    index = 0
    state = "code"
    literal_start = -1
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and next_char == "/":
                result[index] = result[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if char == "/" and next_char == "*":
                result[index] = result[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
            if source.startswith('"""', index):
                result[index] = result[index + 1] = result[index + 2] = " "
                state = "text_block"
                index += 3
                continue
            if char == '"':
                literal_start = index
                state = "string"
            elif char == "'":
                result[index] = " "
                state = "char"
        elif state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                result[index] = " "
        elif state == "block_comment":
            if char == "*" and next_char == "/":
                result[index] = result[index + 1] = " "
                state = "code"
                index += 2
                continue
            if char != "\n":
                result[index] = " "
        elif state == "char":
            if char == "\\":
                result[index] = " "
                if index + 1 < len(source):
                    if source[index + 1] != "\n":
                        result[index + 1] = " "
                    index += 2
                    continue
            result[index] = " "
            if char == "'":
                state = "code"
        elif state == "text_block":
            if source.startswith('"""', index):
                result[index] = result[index + 1] = result[index + 2] = " "
                state = "code"
                index += 3
                continue
            if char != "\n":
                result[index] = " "
        elif state == "string":
            if char == "\\":
                if index + 1 < len(source):
                    index += 2
                    continue
            elif char == '"':
                literal = source[literal_start + 1 : index]
                if not JAVA_POLICY_LEAF_RE.fullmatch(literal):
                    for masked in range(literal_start, index + 1):
                        if source[masked] != "\n":
                            result[masked] = " "
                state = "code"
        index += 1
    if state == "string" and literal_start >= 0:
        for masked in range(literal_start, len(source)):
            if source[masked] != "\n":
                result[masked] = " "
    return "".join(result)


def _matching_java_parenthesis(source: str, opening: int, limit: int) -> int:
    depth = 0
    for index in range(opening, min(limit, len(source))):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return min(limit, len(source))


def _java_identifier_used(text: str, identifier: str) -> bool:
    return bool(re.search(rf"\b{re.escape(identifier)}\b", text))


def _java_branch_has_body(source: str, condition_end: int) -> bool:
    index = condition_end + 1
    while index < len(source) and source[index].isspace():
        index += 1
    if index >= len(source):
        return False
    if source[index] == "{":
        closing = _matching_java_brace(source, index)
        return bool(source[index + 1 : closing].strip())
    statement_end = source.find(";", index)
    if statement_end < 0:
        return False
    return bool(source[index:statement_end].strip())


def _java_previous_identifier(source: str, position: int, lower_bound: int) -> str:
    index = position - 1
    while index >= lower_bound and source[index].isspace():
        index -= 1
    end = index + 1
    while index >= lower_bound and (source[index].isalnum() or source[index] in "_$"):
        index -= 1
    return source[index + 1 : end]


def _java_call_argument_count(
    source: str,
    opening: int,
    closing: int,
) -> int | None:
    """Count top-level call arguments without treating literal commas as syntax."""

    if not (0 <= opening < closing < len(source)):
        return None
    parentheses = brackets = braces = angles = 0
    commas = 0
    has_token = False
    state = "code"
    index = opening + 1
    while index < closing:
        char = source[index]
        next_char = source[index + 1] if index + 1 < closing else ""
        if state == "code":
            if char == "/" and next_char == "/":
                state = "line_comment"
                index += 2
                continue
            if char == "/" and next_char == "*":
                state = "block_comment"
                index += 2
                continue
            if source.startswith('\"\"\"', index):
                has_token = True
                state = "text_block"
                index += 3
                continue
            if char == '"':
                has_token = True
                state = "string"
                index += 1
                continue
            if char == "'":
                has_token = True
                state = "char"
                index += 1
                continue
            if char.isspace():
                index += 1
                continue
            if char == "(":
                parentheses += 1
            elif char == ")":
                if not parentheses:
                    return None
                parentheses -= 1
            elif char == "[":
                brackets += 1
            elif char == "]":
                if not brackets:
                    return None
                brackets -= 1
            elif char == "{":
                braces += 1
            elif char == "}":
                if not braces:
                    return None
                braces -= 1
            elif char == "<":
                angles += 1
            elif char == ">" and angles:
                angles -= 1
            elif char == "," and not (parentheses or brackets or braces or angles):
                commas += 1
                index += 1
                continue
            has_token = True
        elif state == "line_comment":
            if char == "\n":
                state = "code"
        elif state == "block_comment":
            if char == "*" and next_char == "/":
                state = "code"
                index += 2
                continue
        elif state == "text_block":
            if source.startswith('\"\"\"', index):
                state = "code"
                index += 3
                continue
        elif state in {"string", "char"}:
            quote_char = '"' if state == "string" else "'"
            if char == "\\":
                index += 2
                continue
            if char == quote_char:
                state = "code"
        index += 1
    if state != "code" or any((parentheses, brackets, braces, angles)):
        return None
    return commas + 1 if has_token else 0


def _java_annotation_spans(source: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in JAVA_ANNOTATION_TOKEN_RE.finditer(source, start, end):
        cursor = match.end()
        while cursor < end and source[cursor].isspace():
            cursor += 1
        if cursor < end and source[cursor] == "(":
            closing = _matching_java_parenthesis(source, cursor, end)
            spans.append((match.start(), min(closing + 1, end)))
        else:
            spans.append((match.start(), match.end()))
    return spans


def _add_java_call_edges(
    graph: Graph,
    methods: list[dict[str, Any]],
    declared_methods: list[dict[str, Any]],
    code_source: str,
    original_source: str,
    imports: dict[str, str],
    relative_path: str,
) -> None:
    declared_by_owner: dict[tuple[str, str, int], set[str]] = {}
    for declared in declared_methods:
        key = (
            str(declared["owner_id"]),
            str(declared["name"]),
            int(declared["parameter_count"]),
        )
        declared_by_owner.setdefault(key, set()).add(str(declared["id"]))

    nested_ranges: dict[str, list[tuple[int, int]]] = {
        str(method["id"]): [] for method in methods
    }
    method_stack: list[dict[str, Any]] = []
    for method in sorted(methods, key=lambda item: int(item["body_start"])):
        method_start = int(method["body_start"])
        method_end = int(method["body_end"])
        while method_stack and not (
            int(method_stack[-1]["body_start"]) <= method_start
            and method_end <= int(method_stack[-1]["body_end"])
        ):
            method_stack.pop()
        if method_stack:
            nested_ranges[str(method_stack[-1]["id"])].append(
                (method_start, method_end)
            )
        method_stack.append(method)

    for method in methods:
        body_start = int(method["body_start"])
        body_end = int(method["body_end"])
        annotation_spans = _java_annotation_spans(code_source, body_start, body_end)
        for match in JAVA_CALL_RE.finditer(code_source, body_start, body_end):
            position = match.start()
            if any(span_start <= position < span_end for span_start, span_end in annotation_spans):
                continue
            if any(
                nested_start <= position < nested_end
                for nested_start, nested_end in nested_ranges[str(method["id"])]
            ):
                continue

            name = match.group("name")
            qualifier = match.group("qualifier")
            if name in JAVA_NON_CALL_KEYWORDS:
                continue
            if _java_previous_identifier(code_source, position, body_start) == "new":
                continue
            opening = code_source.find("(", match.start(), match.end())
            closing = _matching_java_parenthesis(code_source, opening, body_end)
            if closing >= body_end or code_source[closing] != ")":
                continue
            cursor = closing + 1
            while cursor < body_end and code_source[cursor].isspace():
                cursor += 1
            if cursor < body_end and (
                code_source[cursor] == "{"
                or re.match(r"throws\b", code_source[cursor:body_end])
            ):
                continue

            call_line_start, call_line_end = _line_span(
                code_source,
                position,
                closing,
            )
            if qualifier in {None, "this"}:
                argument_count = _java_call_argument_count(
                    original_source,
                    opening,
                    closing,
                )
                if argument_count is None:
                    continue
                targets = declared_by_owner.get(
                    (str(method["owner_id"]), name, argument_count),
                    set(),
                )
                if len(targets) == 1:
                    graph.add_edge(
                        str(method["id"]),
                        next(iter(targets)),
                        "CALLS",
                        rule_id="java.call.same_owner",
                        basis="resolved_static",
                        path=relative_path,
                        line_start=call_line_start,
                        line_end=call_line_end,
                        limitations=("java.dynamic_dispatch_not_resolved",),
                    )
                continue

            imported_type = imports.get(qualifier)
            if imported_type is None:
                continue
            qualified_name = f"{imported_type}.{name}"
            callable_id = graph.add_node(
                _node_id("java", "callable", qualified_name),
                "ExternalCallable",
                name,
                "Java",
                qualified_name=qualified_name,
            )
            graph.add_edge(
                str(method["id"]),
                callable_id,
                "CALLS",
                rule_id="java.call.imported_static",
                basis="resolved_static",
                path=relative_path,
                line_start=call_line_start,
                line_end=call_line_end,
                limitations=("java.external_overload_not_resolved",),
            )


def _add_java_policy_runtime_edges(
    graph: Graph,
    method: dict[str, Any],
    policy_source: str,
    code_source: str,
    relative_path: str,
) -> None:
    body_start = int(method["body_start"])
    body_end = int(method["body_end"])
    policy_body = policy_source[body_start:body_end]
    code_body = code_source[body_start:body_end]
    reads: list[dict[str, Any]] = []
    for match in JAVA_POLICY_READ_RE.finditer(policy_body):
        leaf = match.group("leaf")
        if not JAVA_POLICY_LEAF_RE.fullmatch(leaf):
            continue
        leaf_id = graph.add_node(
            _node_id("policy", "leaf", leaf),
            "PolicyLeaf",
            leaf.rsplit(".", 1)[-1],
            "Policy",
            qualified_name=leaf,
            metadata={"accessor": match.group("accessor")},
        )
        read_line_start, read_line_end = _line_span(
            policy_source,
            body_start + match.start(),
            body_start + match.end(),
        )
        graph.add_edge(
            method["id"],
            leaf_id,
            "READS_POLICY_LEAF",
            rule_id="java.policy.read",
            basis="direct_syntax",
            path=relative_path,
            line_start=read_line_start,
            line_end=read_line_end,
        )
        reads.append(
            {
                "leaf": leaf,
                "leaf_id": leaf_id,
                "variable": match.group("variable"),
                "start": match.start(),
                "end": match.end(),
            }
        )
    if not reads:
        return

    assignments = [
        {
            "start": match.start(),
            "end": match.end(),
            "variable": match.group("variable"),
            "expression": match.group("expression"),
        }
        for match in JAVA_ASSIGNMENT_RE.finditer(code_body)
    ]
    conditions: list[tuple[int, str, str, int, int]] = []
    for ordinal, match in enumerate(JAVA_CONTROL_RE.finditer(code_body), 1):
        opening = code_body.find("(", match.start(), match.end())
        closing = _matching_java_parenthesis(code_body, opening, len(code_body))
        if closing >= len(code_body):
            continue
        conditions.append(
            (
                ordinal,
                match.group("kind"),
                code_body[opening + 1 : closing],
                opening,
                closing,
            )
        )

    for read in reads:
        for ordinal, control_kind, condition, opening, closing in conditions:
            direct_call = read["start"] >= opening and read["end"] <= closing
            if not direct_call and opening < read["end"]:
                continue
            tainted = {read["variable"]} if read["variable"] else set()
            for assignment in assignments:
                if (
                    assignment["start"] < read["end"]
                    or assignment["end"] > opening
                ):
                    continue
                expression_is_tainted = any(
                    _java_identifier_used(assignment["expression"], variable)
                    for variable in tainted
                )
                assigned = assignment["variable"]
                if assigned in tainted and not expression_is_tainted:
                    tainted.remove(assigned)
                if expression_is_tainted:
                    tainted.add(assigned)
            if not direct_call and not any(
                _java_identifier_used(condition, variable) for variable in tainted
            ):
                continue
            if not _java_branch_has_body(code_body, closing):
                continue
            branch_qualified = f"{method['qualified_name']}#branch:{ordinal}"
            branch_id = graph.add_node(
                _node_id("java", "runtime_branch", branch_qualified),
                "RuntimeBranch",
                f"{control_kind} branch {ordinal}",
                "Java",
                path=relative_path,
                qualified_name=branch_qualified,
                metadata={"control_kind": control_kind, "ordinal": ordinal},
            )
            branch_line_start, branch_line_end = _line_span(
                code_source,
                body_start + opening,
                body_start + closing,
            )
            graph.add_edge(
                method["id"],
                branch_id,
                "DECLARES_RUNTIME_BRANCH",
                rule_id="java.policy.branch",
                basis="direct_syntax",
                path=relative_path,
                line_start=branch_line_start,
                line_end=branch_line_end,
            )
            graph.add_edge(
                read["leaf_id"],
                branch_id,
                "GUARDS_RUNTIME_BRANCH",
                rule_id="java.policy.guard",
                basis="resolved_static",
                runtime_status="runtime_unknown",
                path=relative_path,
                line_start=branch_line_start,
                line_end=branch_line_end,
                limitations=("runtime.branch_execution_not_observed",),
            )


def _strip_balanced_java_generics(value: str) -> str:
    result: list[str] = []
    depth = 0
    for char in value:
        if char == "<":
            depth += 1
            continue
        if char == ">" and depth:
            depth -= 1
            continue
        if depth == 0:
            result.append(char)
    return "".join(result)


def _clean_java_type(raw_type: str) -> str:
    value = re.sub(JAVA_ANNOTATION_PATTERN + r"\s*", "", raw_type)
    value = _strip_balanced_java_generics(value)
    value = value.replace("[]", "").replace("...", "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.split()[-1] if value else ""


def _resolve_java_type(
    type_name: str,
    imports: dict[str, str],
    package_name: str,
    wildcard_imports: set[str] | None = None,
) -> str:
    clean = _clean_java_type(type_name)
    if not clean:
        return "unknown"
    if "." in clean:
        root, remainder = clean.split(".", 1)
        if root in imports:
            return f"{imports[root]}.{remainder}"
        if root[:1].islower():
            return clean
        return f"{package_name}.{clean}" if package_name else clean
    if clean in imports:
        return imports[clean]
    if clean in JAVA_LANG_TYPES:
        return f"java.lang.{clean}"
    if clean in JAVA_UTIL_TYPES:
        return f"java.util.{clean}"
    if wildcard_imports:
        return clean
    return f"{package_name}.{clean}" if package_name else clean


def _add_java_annotation_edges(
    graph: Graph,
    subject: str,
    annotations: Iterable[tuple[str, str, str | None]],
    *,
    path: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> set[str]:
    semantics: set[str] = set()
    for annotation, qualified_name, semantic_name in annotations:
        annotation_id = graph.add_annotation(
            annotation,
            qualified_name=qualified_name,
            semantic_name=semantic_name,
        )
        graph.add_edge(
            subject,
            annotation_id,
            "ANNOTATED_BY",
            rule_id="java.annotation",
            basis="direct_syntax",
            path=path,
            line_start=line_start,
            line_end=line_end,
        )
        if semantic_name:
            semantics.add(semantic_name)
        if semantic_name in SPRING_STEREOTYPES:
            graph.add_edge(
                subject,
                "framework:spring:bean",
                "MANAGED_AS",
                rule_id="java.spring.stereotype",
                basis="framework_semantic",
                runtime_status="runtime_unknown",
                path=path,
                line_start=line_start,
                line_end=line_end,
                limitations=("spring.application_context_not_observed",),
            )
            graph.add_node(
                "framework:spring:bean",
                "FrameworkConcept",
                "Spring-managed bean",
                "Framework",
            )
        if semantic_name in SPRING_PROXY:
            graph.add_edge(
                subject,
                "framework:spring:proxy",
                "MAY_BE_PROXIED_BY",
                rule_id="java.spring.proxy_annotation",
                basis="framework_semantic",
                runtime_status="runtime_unknown",
                path=path,
                line_start=line_start,
                line_end=line_end,
                limitations=("spring.proxy_activation_not_observed",),
            )
            graph.add_node(
                "framework:spring:proxy",
                "FrameworkConcept",
                "Spring proxy or interceptor",
                "Framework",
            )
    return semantics


def _matching_java_brace(source: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(source)


def _java_type_header(source: str, start: int) -> tuple[str, int]:
    parentheses = 0
    brackets = 0
    angles = 0
    nested_braces = 0
    index = start
    while index < len(source):
        char = source[index]
        if char == "(":
            parentheses += 1
        elif char == ")" and parentheses:
            parentheses -= 1
        elif char == "[":
            brackets += 1
        elif char == "]" and brackets:
            brackets -= 1
        elif char == "<":
            angles += 1
        elif char == ">" and angles:
            angles -= 1
        elif char == "{":
            if parentheses or brackets or angles or nested_braces:
                nested_braces += 1
            else:
                return source[start:index], index
        elif char == "}" and nested_braces:
            nested_braces -= 1
        elif char == ";" and not (parentheses or brackets or angles or nested_braces):
            return source[start:index], -1
        index += 1
    return source[start:], -1


def _remove_leading_balanced(value: str, opening: str, closing: str) -> str:
    stripped = value.lstrip()
    if not stripped.startswith(opening):
        return stripped
    depth = 0
    for index, char in enumerate(stripped):
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return stripped[index + 1 :].lstrip()
    return stripped


def _java_scope_for(scopes: list[dict[str, Any]], position: int) -> dict[str, Any] | None:
    candidates = [
        scope
        for scope in scopes
        if scope["body_start"] < position < scope["body_end"]
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda scope: scope["body_start"])


def _java_direct_member_matches(
    source: str,
    pattern: re.Pattern[str],
    body_start: int,
    body_end: int,
) -> list[re.Match[str]]:
    """Return pattern matches at the direct member depth of one Java type."""

    matches: list[re.Match[str]] = []
    depth = 0
    cursor = body_start + 1
    for match in pattern.finditer(source, cursor, body_end):
        for character in source[cursor : match.start()]:
            if character == "{":
                depth += 1
            elif character == "}" and depth:
                depth -= 1
        if depth == 0:
            matches.append(match)
        cursor = match.start()
    return matches


def _split_java_parameters(parameters: str) -> list[str]:
    values: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(parameters):
        if char in "<([{":
            depth += 1
        elif char in ">)]}" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            values.append(parameters[start:index].strip())
            start = index + 1
    final = parameters[start:].strip()
    if final:
        values.append(final)
    return values


def _java_hierarchy(header: str, kind: str) -> tuple[list[str], list[str]]:
    header = _remove_leading_balanced(header, "<", ">")
    if kind == "record":
        header = _remove_leading_balanced(header, "(", ")")
    extends_values: list[str] = []
    implements_values: list[str] = []
    extends_match = re.search(
        r"\bextends\s+(?P<value>.*?)(?=\bimplements\b|\bpermits\b|$)",
        header,
    )
    if extends_match:
        values = _split_java_parameters(extends_match.group("value"))
        extends_values.extend(values if kind == "interface" else values[:1])
    implements_match = re.search(
        r"\bimplements\s+(?P<value>.*?)(?=\bpermits\b|$)",
        header,
    )
    if implements_match:
        implements_values.extend(_split_java_parameters(implements_match.group("value")))
    return extends_values, implements_values


def _java_parameter_types(
    parameters: str,
    imports: dict[str, str],
    package_name: str,
    wildcard_imports: set[str] | None = None,
) -> list[str]:
    resolved: list[str] = []
    for parameter in _split_java_parameters(parameters):
        without_annotations = re.sub(
            JAVA_ANNOTATION_PATTERN + r"\s*",
            "",
            parameter,
        ).strip()
        without_modifiers = re.sub(r"^(?:final|volatile|transient)\s+", "", without_annotations)
        pieces = without_modifiers.split()
        if len(pieces) < 2:
            continue
        resolved.append(
            _resolve_java_type(
                " ".join(pieces[:-1]),
                imports,
                package_name,
                wildcard_imports,
            )
        )
    return resolved


def analyze_java(
    graph: Graph,
    repo: Path,
    path: Path,
    *,
    repository_package_types: dict[str, set[str]] | None = None,
) -> None:
    relative_path = path.relative_to(repo).as_posix()
    original = _safe_read(path)
    source = _strip_java_comments_and_literals(original)
    package_match = re.search(r"^\s*package\s+([\w.]+)\s*;", source, re.MULTILINE)
    package_name = package_match.group(1) if package_match else ""
    _, local_declared_types = _java_package_and_declared_types(original)
    same_package_types = (
        set(repository_package_types.get(package_name, set())) | local_declared_types
        if repository_package_types is not None
        else None
    )
    import_matches = list(
        re.finditer(
            r"^\s*import\s+(?P<static>static\s+)?(?P<qualified>[\w.]+(?:\.\*)?)\s*;",
            source,
            re.MULTILINE,
        )
    )
    imports = {
        match.group("qualified").rsplit(".", 1)[-1]: match.group("qualified")
        for match in import_matches
        if not match.group("static") and not match.group("qualified").endswith(".*")
    }
    wildcard_imports = {
        match.group("qualified")[:-2]
        for match in import_matches
        if not match.group("static") and match.group("qualified").endswith(".*")
    }
    module_name = package_name or relative_path.removesuffix(".java").replace("/", ".")
    module_id = graph.add_node(
        _node_id("java", "package", module_name),
        "Package",
        module_name.rsplit(".", 1)[-1],
        "Java",
        path=relative_path,
        qualified_name=module_name,
        metadata={"line_start": 1, "line_end": 1},
    )
    for imported in sorted(imports.values()):
        imported_id = graph.add_external_type("Java", imported)
        import_match = next(
            (
                match
                for match in import_matches
                if match.group("qualified") == imported
            ),
            None,
        )
        import_lines = (
            _line_span(source, import_match.start(), import_match.end())
            if import_match is not None
            else (1, 1)
        )
        graph.add_edge(
            module_id,
            imported_id,
            "IMPORTS",
            rule_id="java.import",
            basis="direct_syntax",
            path=relative_path,
            line_start=import_lines[0],
            line_end=import_lines[1],
        )

    raw_scopes: list[dict[str, Any]] = []
    for match in JAVA_TYPE_RE.finditer(source):
        header, body_start = _java_type_header(source, match.end())
        if body_start < 0:
            graph.add_warning(relative_path, f"Could not locate body for Java type {match.group('name')}")
            continue
        raw_scopes.append(
            {
                "match": match,
                "header": header,
                "start": match.start(),
                "body_start": body_start,
                "body_end": _matching_java_brace(source, body_start),
            }
        )

    scopes: list[dict[str, Any]] = []
    for raw_scope in sorted(raw_scopes, key=lambda item: item["start"]):
        match = raw_scope["match"]
        type_name = match.group("name")
        parent = _java_scope_for(scopes, raw_scope["start"])
        if parent:
            qualified_name = f"{parent['qualified_name']}.{type_name}"
        else:
            qualified_name = f"{package_name}.{type_name}" if package_name else type_name
        node_type = {
            "class": "Class",
            "interface": "Interface",
            "enum": "Enum",
            "record": "Record",
        }[match.group("kind")]
        type_line_start, type_line_end = _line_span(source, match.start(), match.end())
        type_id = graph.add_node(
            _node_id("java", match.group("kind"), qualified_name),
            node_type,
            type_name,
            "Java",
            path=relative_path,
            qualified_name=qualified_name,
            metadata={"line_start": type_line_start, "line_end": type_line_end},
        )
        graph.add_edge(
            parent["id"] if parent else module_id,
            type_id,
            "DECLARES",
            rule_id="java.type_declaration",
            basis="direct_syntax",
            path=relative_path,
            line_start=type_line_start,
            line_end=type_line_end,
        )
        type_semantics = _add_java_annotation_edges(
            graph,
            type_id,
            _resolved_annotations(
                match.group("annotations") or "",
                imports,
                wildcard_imports,
                package_name,
                same_package_types,
            ),
            path=relative_path,
            line_start=type_line_start,
            line_end=type_line_end,
        )
        scope = {
            **raw_scope,
            "id": type_id,
            "qualified_name": qualified_name,
            "simple_name": type_name,
            "annotation_semantics": type_semantics,
        }
        scopes.append(scope)
        extends_values, implements_values = _java_hierarchy(
            raw_scope["header"],
            match.group("kind"),
        )
        for extends_value in extends_values:
            target_name = _resolve_java_type(
                extends_value, imports, package_name, wildcard_imports
            )
            graph.add_edge(
                type_id,
                graph.add_external_type("Java", target_name),
                "EXTENDS",
                rule_id="java.extends",
                basis="resolved_static",
                path=relative_path,
                line_start=type_line_start,
                line_end=type_line_end,
                limitations=("java.dynamic_type_resolution_not_observed",),
            )
        for interface in implements_values:
            target_name = _resolve_java_type(
                interface, imports, package_name, wildcard_imports
            )
            graph.add_edge(
                type_id,
                graph.add_external_type("Java", target_name),
                "IMPLEMENTS",
                rule_id="java.implements",
                basis="resolved_static",
                path=relative_path,
                line_start=type_line_start,
                line_end=type_line_end,
            )

    if not scopes:
        return

    methods: list[dict[str, Any]] = []
    declared_methods: list[dict[str, Any]] = []
    for match in JAVA_METHOD_RE.finditer(source):
        owner = _java_scope_for(scopes, match.start())
        if owner is None:
            continue
        method_name = match.group("name")
        if method_name == owner["simple_name"]:
            continue
        parameter_types = _java_parameter_types(
            match.group("params"), imports, package_name, wildcard_imports
        )
        signature = ",".join(parameter_types)
        method_qualified = f"{owner['qualified_name']}#{method_name}({signature})"
        annotations = _resolved_annotations(
            match.group("annotations") or "",
            imports,
            wildcard_imports,
            package_name,
            same_package_types,
        )
        method_line_start, method_line_end = _line_span(source, match.start(), match.end())
        method_id = graph.add_node(
            _node_id("java", "method", method_qualified),
            "Method",
            method_name,
            "Java",
            path=relative_path,
            qualified_name=method_qualified,
            metadata={
                "return_type": _resolve_java_type(
                    match.group("return"), imports, package_name, wildcard_imports
                ),
                "parameter_types": parameter_types,
                "line_start": method_line_start,
                "line_end": method_line_end,
            },
        )
        graph.add_edge(
            owner["id"],
            method_id,
            "DECLARES",
            rule_id="java.method_declaration",
            basis="direct_syntax",
            path=relative_path,
            line_start=method_line_start,
            line_end=method_line_end,
        )
        declared_method = {
            "id": method_id,
            "owner_id": owner["id"],
            "name": method_name,
            "parameter_count": len(parameter_types),
        }
        declared_methods.append(declared_method)
        method_semantics = _add_java_annotation_edges(
            graph,
            method_id,
            annotations,
            path=relative_path,
            line_start=method_line_start,
            line_end=method_line_end,
        )
        if match.group("ending") == "{":
            body_start = source.find("{", match.end() - 1, owner["body_end"])
            if body_start >= 0:
                methods.append(
                    {
                        **declared_method,
                        "qualified_name": method_qualified,
                        "body_start": body_start + 1,
                        "body_end": _matching_java_brace(source, body_start),
                    }
                )
        if "Bean" in method_semantics:
            return_type = _resolve_java_type(
                match.group("return"), imports, package_name, wildcard_imports
            )
            bean_id = graph.add_external_type("Java", return_type)
            graph.add_node(
                "framework:spring:bean",
                "FrameworkConcept",
                "Spring-managed bean",
                "Framework",
            )
            graph.add_edge(
                method_id,
                bean_id,
                "DECLARES_BEAN",
                rule_id="java.spring.bean_method",
                basis="framework_semantic",
                runtime_status="runtime_unknown",
                path=relative_path,
                line_start=method_line_start,
                line_end=method_line_end,
                limitations=("spring.bean_registration_not_observed",),
            )
            graph.add_edge(
                bean_id,
                "framework:spring:bean",
                "MANAGED_AS",
                rule_id="java.spring.bean_return_type",
                basis="framework_semantic",
                runtime_status="runtime_unknown",
                path=relative_path,
                line_start=method_line_start,
                line_end=method_line_end,
                limitations=("spring.bean_registration_not_observed",),
            )
            for target_name in parameter_types:
                if target_name.startswith("java.lang."):
                    continue
                graph.add_edge(
                    method_id,
                    graph.add_external_type("Java", target_name),
                    "INJECTS",
                    rule_id="java.spring.bean_parameter",
                    basis="framework_semantic",
                    runtime_status="runtime_unknown",
                    path=relative_path,
                    line_start=method_line_start,
                    line_end=method_line_end,
                    limitations=("spring.bean_resolution_not_observed",),
                )
        if method_semantics.intersection(SPRING_INJECTION):
            for target_name in parameter_types:
                if target_name.startswith("java.lang."):
                    continue
                graph.add_edge(
                    owner["id"],
                    graph.add_external_type("Java", target_name),
                    "INJECTS",
                    rule_id="java.spring.method_injection",
                    basis="framework_semantic",
                    runtime_status="runtime_unknown",
                    path=relative_path,
                    line_start=method_line_start,
                    line_end=method_line_end,
                    limitations=("spring.bean_resolution_not_observed",),
                )

    _add_java_call_edges(
        graph,
        methods,
        declared_methods,
        source,
        original,
        imports,
        relative_path,
    )

    policy_source = _java_policy_scan_source(original)
    for method in methods:
        _add_java_policy_runtime_edges(
            graph,
            method,
            policy_source,
            source,
            relative_path,
        )

    for match in JAVA_FIELD_RE.finditer(source):
        owner = _java_scope_for(scopes, match.start())
        if owner is None:
            continue
        annotations = _resolved_annotations(
            match.group("annotations") or "",
            imports,
            wildcard_imports,
            package_name,
            same_package_types,
        )
        field_line_start, field_line_end = _line_span(source, match.start(), match.end())
        annotation_semantics = _add_java_annotation_edges(
            graph,
            owner["id"],
            annotations,
            path=relative_path,
            line_start=field_line_start,
            line_end=field_line_end,
        )
        if not annotation_semantics.intersection(SPRING_INJECTION):
            continue
        target_name = _resolve_java_type(
            match.group("type"), imports, package_name, wildcard_imports
        )
        target_id = graph.add_external_type("Java", target_name)
        graph.add_edge(
            owner["id"],
            target_id,
            "INJECTS",
            rule_id="java.spring.field_injection",
            basis="framework_semantic",
            runtime_status="runtime_unknown",
            path=relative_path,
            line_start=field_line_start,
            line_end=field_line_end,
            limitations=("spring.bean_resolution_not_observed",),
        )

    for owner in scopes:
        constructor_re = re.compile(
            rf"(?:^[ \t]*|(?<=[{{}};])[ \t]*)"
            rf"(?P<annotations>(?:{JAVA_ANNOTATION_PATTERN}\s*)*)"
            rf"(?:(?:public|protected|private)\s+)?"
            rf"(?:<[^;{{}}]+>\s+)?"
            rf"{re.escape(owner['simple_name'])}\s*"
            rf"\((?P<params>(?:[^()]|\([^()]*\))*)\)"
            rf"\s*(?:throws\s+[^{{;]+)?\{{",
            re.MULTILINE,
        )
        constructors = [
            constructor
            for constructor in _java_direct_member_matches(
                source,
                constructor_re,
                owner["body_start"],
                owner["body_end"],
            )
            if _java_scope_for(scopes, constructor.start()) is owner
        ]
        for constructor in constructors:
            constructor_line_start, constructor_line_end = _line_span(
                source, constructor.start(), constructor.end()
            )
            constructor_annotations = _resolved_annotations(
                constructor.group("annotations") or "",
                imports,
                wildcard_imports,
                package_name,
                same_package_types,
            )
            constructor_semantics = {
                semantic
                for _, _, semantic in constructor_annotations
                if semantic is not None
            }
            is_managed_type = bool(
                owner["annotation_semantics"].intersection(SPRING_STEREOTYPES)
            )
            is_explicit_injection = bool(
                constructor_semantics.intersection(SPRING_INJECTION)
            )
            if not is_explicit_injection and not (is_managed_type and len(constructors) == 1):
                continue
            for target_name in _java_parameter_types(
                constructor.group("params"),
                imports,
                package_name,
                wildcard_imports,
            ):
                if target_name.startswith("java.lang."):
                    continue
                graph.add_edge(
                    owner["id"],
                    graph.add_external_type("Java", target_name),
                    "INJECTS",
                    rule_id=(
                        "java.spring.explicit_constructor_injection"
                        if is_explicit_injection
                        else "java.spring.single_constructor_injection"
                    ),
                    basis="framework_semantic",
                    runtime_status="runtime_unknown",
                    path=relative_path,
                    line_start=constructor_line_start,
                    line_end=constructor_line_end,
                    limitations=("spring.bean_resolution_not_observed",),
                )


def _python_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _python_name(node.func)
    if isinstance(node, ast.Subscript):
        return _python_name(node.value)
    return ""


def _pipeline_role(name: str) -> str | None:
    tokenized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    tokens = {
        token
        for token in re.split(r"[^A-Za-z0-9]+", tokenized.casefold())
        if token
    }
    groups = {
        "Extract": {
            "extract", "extractor", "fetch", "fetcher", "read", "reader",
            "ingest", "ingestion", "collect", "collector", "source",
        },
        "Transform": {
            "transform", "transformer", "clean", "cleaner", "normalize",
            "normalizer", "enrich", "enricher", "map", "mapper", "parse", "parser",
        },
        "Load": {
            "load", "loader", "write", "writer", "persist", "persistence",
            "publish", "publisher", "sink", "store", "storage",
        },
        "Validate": {
            "validate", "validator", "verify", "verifier", "quality", "check", "checker",
        },
        "Orchestrate": {
            "pipeline", "workflow", "orchestrate", "orchestrator", "schedule",
            "scheduler", "run", "runner",
        },
    }
    for role, role_tokens in groups.items():
        if tokens.intersection(role_tokens):
            return role
    return None


def _python_local_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {
        argument.arg
        for argument in (
            [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            + ([node.args.vararg] if node.args.vararg else [])
            + ([node.args.kwarg] if node.args.kwarg else [])
        )
    }
    global_names: set[str] = set()
    nonlocal_names: set[str] = set()

    class Collector(ast.NodeVisitor):
        def visit_Name(self, child: ast.Name) -> None:
            if isinstance(child.ctx, ast.Store):
                names.add(child.id)

        def visit_Import(self, child: ast.Import) -> None:
            for alias in child.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])

        def visit_ImportFrom(self, child: ast.ImportFrom) -> None:
            for alias in child.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            names.add(child.name)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            names.add(child.name)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            names.add(child.name)

        def visit_ExceptHandler(self, child: ast.ExceptHandler) -> None:
            if child.name:
                names.add(child.name)
            self.generic_visit(child)

        def _visit_comprehension(
            self,
            generators: list[ast.comprehension],
            values: list[ast.AST],
        ) -> None:
            # Python 3 comprehension targets have their own implicit scope and
            # must not shadow a binding in the containing function.
            for generator in generators:
                self.visit(generator.iter)
                for condition in generator.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)

        def visit_ListComp(self, child: ast.ListComp) -> None:
            self._visit_comprehension(child.generators, [child.elt])

        def visit_SetComp(self, child: ast.SetComp) -> None:
            self._visit_comprehension(child.generators, [child.elt])

        def visit_GeneratorExp(self, child: ast.GeneratorExp) -> None:
            self._visit_comprehension(child.generators, [child.elt])

        def visit_DictComp(self, child: ast.DictComp) -> None:
            self._visit_comprehension(child.generators, [child.key, child.value])

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return

        def visit_Global(self, child: ast.Global) -> None:
            global_names.update(child.names)

        def visit_Nonlocal(self, child: ast.Nonlocal) -> None:
            nonlocal_names.update(child.names)

    collector = Collector()
    for statement in node.body:
        collector.visit(statement)
    return names - global_names - nonlocal_names


def _python_import_from_module(package_name: str, node: ast.ImportFrom) -> str:
    if node.level <= 0:
        return node.module or ""
    parts = [part for part in package_name.split(".") if part]
    ascents = max(0, node.level - 1)
    if ascents > len(parts):
        return node.module or ""
    if ascents:
        parts = parts[:-ascents]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _python_global_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()

    class Collector(ast.NodeVisitor):
        def visit_Global(self, child: ast.Global) -> None:
            names.update(child.names)

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return

    collector = Collector()
    for statement in node.body:
        collector.visit(statement)
    return names


def _python_import_aliases(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    package_name: str,
) -> dict[str, str]:
    """Collect unambiguous imports for one lexical Python scope."""

    aliases: dict[str, str] = {}
    competing_bindings: set[str] = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        competing_bindings.update(
            argument.arg
            for argument in (
                [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            )
        )

    class Collector(ast.NodeVisitor):
        def _record_import(self, local_name: str, target: str) -> None:
            previous = aliases.get(local_name)
            if previous is not None and previous != target:
                competing_bindings.add(local_name)
            aliases[local_name] = target

        def visit_Name(self, child: ast.Name) -> None:
            if isinstance(child.ctx, ast.Store):
                competing_bindings.add(child.id)

        def visit_Import(self, child: ast.Import) -> None:
            for alias in child.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                target = alias.name if alias.asname else local_name
                self._record_import(local_name, target)

        def visit_ImportFrom(self, child: ast.ImportFrom) -> None:
            target_module = _python_import_from_module(package_name, child)
            for alias in child.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                qualified = f"{target_module}.{alias.name}" if target_module else alias.name
                self._record_import(local_name, qualified)

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            competing_bindings.add(child.name)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            competing_bindings.add(child.name)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            competing_bindings.add(child.name)

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return

        def visit_ExceptHandler(self, child: ast.ExceptHandler) -> None:
            if child.name:
                competing_bindings.add(child.name)
            self.generic_visit(child)

        def _visit_comprehension(
            self,
            generators: list[ast.comprehension],
            values: list[ast.AST],
        ) -> None:
            for generator in generators:
                self.visit(generator.iter)
                for condition in generator.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)

        def visit_ListComp(self, child: ast.ListComp) -> None:
            self._visit_comprehension(child.generators, [child.elt])

        def visit_SetComp(self, child: ast.SetComp) -> None:
            self._visit_comprehension(child.generators, [child.elt])

        def visit_GeneratorExp(self, child: ast.GeneratorExp) -> None:
            self._visit_comprehension(child.generators, [child.elt])

        def visit_DictComp(self, child: ast.DictComp) -> None:
            self._visit_comprehension(child.generators, [child.key, child.value])

    collector = Collector()
    for statement in node.body:
        collector.visit(statement)
    return {
        name: target
        for name, target in aliases.items()
        if name not in competing_bindings
    }


def _python_target_bindings(target: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(target)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }


def _validate_python_ast_limits(tree: ast.AST) -> None:
    """Bound recursive visitor work using an iterative AST walk."""

    stack: list[tuple[ast.AST, int]] = [(tree, 1)]
    discovered = 1
    while stack:
        node, depth = stack.pop()
        if depth > MAX_PYTHON_AST_DEPTH:
            raise OntologyError(
                f"Python AST exceeds the {MAX_PYTHON_AST_DEPTH}-depth safety limit."
            )
        child_depth = depth + 1
        for child in ast.iter_child_nodes(node):
            discovered += 1
            if discovered > MAX_PYTHON_AST_NODES:
                raise OntologyError(
                    f"Python AST exceeds the {MAX_PYTHON_AST_NODES}-node safety limit."
                )
            if child_depth > MAX_PYTHON_AST_DEPTH:
                raise OntologyError(
                    f"Python AST exceeds the {MAX_PYTHON_AST_DEPTH}-depth safety limit."
                )
            stack.append((child, child_depth))


class PythonVisitor(ast.NodeVisitor):
    def __init__(
        self,
        graph: Graph,
        module_id: str,
        module_name: str,
        relative_path: str,
        tree: ast.Module,
        *,
        is_package: bool,
    ) -> None:
        self.graph = graph
        self.module_id = module_id
        self.module_name = module_name
        self.relative_path = relative_path
        self.scope: list[tuple[str, str]] = [(module_id, module_name)]
        self.class_scope: list[str] = []
        self.local_bindings: list[set[str]] = []
        self.local_symbols: list[dict[str, str]] = []
        self.local_import_aliases: list[dict[str, str]] = []
        self.local_globals: list[set[str]] = []
        self.module_functions = {
            child.name
            for child in tree.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.module_classes = {
            child.name for child in tree.body if isinstance(child, ast.ClassDef)
        }
        self.class_methods = {
            f"{module_name}.{child.name}": {
                member.name
                for member in child.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for child in tree.body
            if isinstance(child, ast.ClassDef)
        }
        self.package_name = (
            module_name
            if is_package
            else module_name.rsplit(".", 1)[0] if "." in module_name else ""
        )
        self.import_aliases = _python_import_aliases(tree, self.package_name)

    @property
    def owner(self) -> tuple[str, str]:
        return self.scope[-1]

    def _import_from_module(self, node: ast.ImportFrom) -> str:
        return _python_import_from_module(self.package_name, node)

    def _resolve_reference(self, name: str) -> str:
        if not name:
            return name
        pieces = name.split(".")
        if self.class_scope and pieces[0] in {"self", "cls"} and len(pieces) > 1:
            return ".".join([self.class_scope[-1], *pieces[1:]])
        for index in range(len(self.local_bindings) - 1, -1, -1):
            if pieces[0] in self.local_globals[index]:
                break
            local_symbol = self.local_symbols[index].get(pieces[0])
            if local_symbol:
                return ".".join([local_symbol, *pieces[1:]])
            local_import = self.local_import_aliases[index].get(pieces[0])
            if local_import:
                return ".".join([local_import, *pieces[1:]])
            if pieces[0] in self.local_bindings[index]:
                return name
        imported = self.import_aliases.get(pieces[0])
        if imported:
            return ".".join([imported, *pieces[1:]]) if len(pieces) > 1 else imported
        if len(pieces) == 1:
            if name in self.module_functions or name in self.module_classes:
                return f"{self.module_name}.{name}"
        return name

    def _add_decorators(self, subject_id: str, decorators: list[ast.expr]) -> None:
        for decorator in decorators:
            name = self._resolve_reference(_python_name(decorator))
            if not name:
                continue
            decorator_id = self.graph.add_node(
                _node_id("python", "decorator", name),
                "Decorator",
                name.rsplit(".", 1)[-1],
                "Python",
                qualified_name=name,
            )
            self.graph.add_edge(
                subject_id,
                decorator_id,
                "DECORATED_BY",
                rule_id="python.decorator",
                basis="direct_syntax",
                path=self.relative_path,
                line_start=getattr(decorator, "lineno", None),
                line_end=getattr(decorator, "end_lineno", None),
            )

    def _add_pipeline_role(
        self,
        subject_id: str,
        name: str,
        node: ast.AST | None = None,
    ) -> None:
        role = _pipeline_role(name)
        if role:
            role_id = self.graph.add_node(
                f"pipeline:role:{role.lower()}",
                "PipelineRole",
                role,
                "Concept",
            )
            self.graph.add_edge(
                subject_id,
                role_id,
                "HAS_PIPELINE_ROLE",
                rule_id="python.pipeline_role.name_tokens",
                basis="name_heuristic",
                path=self.relative_path,
                line_start=getattr(node, "lineno", None),
                line_end=getattr(node, "end_lineno", None),
                limitations=("python.role_name_heuristic",),
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            target_id = self.graph.add_node(
                _node_id("python", "module", alias.name),
                "ExternalModule",
                alias.name.rsplit(".", 1)[-1],
                "Python",
                qualified_name=alias.name,
            )
            self.graph.add_edge(
                self.module_id,
                target_id,
                "IMPORTS",
                rule_id="python.import",
                basis="direct_syntax",
                path=self.relative_path,
                line_start=getattr(node, "lineno", None),
                line_end=getattr(node, "end_lineno", None),
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        target_module = self._import_from_module(node)
        if target_module:
            target_id = self.graph.add_node(
                _node_id("python", "module", target_module),
                "ExternalModule",
                target_module.rsplit(".", 1)[-1],
                "Python",
                qualified_name=target_module,
            )
            self.graph.add_edge(
                self.module_id,
                target_id,
                "IMPORTS",
                rule_id="python.import_from",
                basis="resolved_static",
                path=self.relative_path,
                line_start=getattr(node, "lineno", None),
                line_end=getattr(node, "end_lineno", None),
                limitations=("python.import_execution_not_observed",),
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        owner_id, owner_name = self.owner
        qualified = f"{owner_name}.{node.name}"
        class_id = self.graph.add_node(
            _node_id("python", "class", qualified),
            "Class",
            node.name,
            "Python",
            path=self.relative_path,
            qualified_name=qualified,
            metadata={
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
            },
        )
        self.graph.add_edge(
            owner_id,
            class_id,
            "DECLARES",
            rule_id="python.class_declaration",
            basis="direct_syntax",
            path=self.relative_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
        )
        self._add_decorators(class_id, node.decorator_list)
        self._add_pipeline_role(class_id, node.name, node)
        for base in node.bases:
            base_name = self._resolve_reference(_python_name(base))
            if base_name:
                self.graph.add_edge(
                    class_id,
                    self.graph.add_external_type("Python", base_name),
                    "EXTENDS",
                    rule_id="python.inheritance",
                    basis="resolved_static",
                    path=self.relative_path,
                    line_start=getattr(base, "lineno", node.lineno),
                    line_end=getattr(base, "end_lineno", node.lineno),
                    limitations=("python.dynamic_base_resolution_not_observed",),
                )
        self.scope.append((class_id, qualified))
        self.class_scope.append(qualified)
        for child in node.body:
            self.visit(child)
        self.class_scope.pop()
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        owner_id, owner_name = self.owner
        qualified = f"{owner_name}.{node.name}"
        node_type = "AsyncFunction" if isinstance(node, ast.AsyncFunctionDef) else "Function"
        if self.graph.nodes.get(owner_id, {}).get("type") == "Class":
            node_type = "AsyncMethod" if isinstance(node, ast.AsyncFunctionDef) else "Method"
        function_id = self.graph.add_node(
            _node_id("python", node_type, qualified),
            node_type,
            node.name,
            "Python",
            path=self.relative_path,
            qualified_name=qualified,
            metadata={
                "parameter_count": (
                    len(node.args.posonlyargs)
                    + len(node.args.args)
                    + len(node.args.kwonlyargs)
                    + int(node.args.vararg is not None)
                    + int(node.args.kwarg is not None)
                ),
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
            },
        )
        self.graph.add_edge(
            owner_id,
            function_id,
            "DECLARES",
            rule_id="python.function_declaration",
            basis="direct_syntax",
            path=self.relative_path,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
        )
        self._add_decorators(function_id, node.decorator_list)
        self._add_pipeline_role(function_id, node.name, node)
        self.scope.append((function_id, qualified))
        self.local_bindings.append(_python_local_bindings(node))
        self.local_globals.append(_python_global_bindings(node))
        self.local_import_aliases.append(
            _python_import_aliases(node, self.package_name)
        )
        self.local_symbols.append(
            {
                child.name: f"{qualified}.{child.name}"
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
        )
        for child in node.body:
            self.visit(child)
        self.local_symbols.pop()
        self.local_import_aliases.pop()
        self.local_globals.pop()
        self.local_bindings.pop()
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_comprehension(
        self,
        generators: list[ast.comprehension],
        values: list[ast.AST],
    ) -> None:
        pushed = 0
        try:
            for generator in generators:
                # Each iterable is evaluated before its own target is bound;
                # targets from earlier generators remain visible.
                self.visit(generator.iter)
                self.local_bindings.append(_python_target_bindings(generator.target))
                self.local_symbols.append({})
                self.local_import_aliases.append({})
                self.local_globals.append(set())
                pushed += 1
                for condition in generator.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)
        finally:
            for _ in range(pushed):
                self.local_import_aliases.pop()
                self.local_symbols.pop()
                self.local_globals.pop()
                self.local_bindings.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, [node.key, node.value])

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        bindings = {
            argument.arg
            for argument in (
                [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            )
        }
        self.local_bindings.append(bindings)
        self.local_symbols.append({})
        self.local_import_aliases.append({})
        self.local_globals.append(set())
        try:
            self.visit(node.body)
        finally:
            self.local_globals.pop()
            self.local_import_aliases.pop()
            self.local_symbols.pop()
            self.local_bindings.pop()

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._resolve_reference(_python_name(node.func))
        if call_name:
            call_id = self.graph.add_node(
                _node_id("python", "callable", call_name),
                "ExternalCallable",
                call_name.rsplit(".", 1)[-1],
                "Python",
                qualified_name=call_name,
            )
            self.graph.add_edge(
                self.owner[0],
                call_id,
                "CALLS",
                rule_id="python.call.lexical_resolution",
                basis="resolved_static",
                path=self.relative_path,
                line_start=getattr(node, "lineno", None),
                line_end=getattr(node, "end_lineno", None),
                limitations=("python.runtime_dispatch_not_observed",),
            )
        self.generic_visit(node)


def analyze_python(graph: Graph, repo: Path, path: Path) -> None:
    relative_path = path.relative_to(repo).as_posix()
    module_relative = relative_path
    src_is_package = False
    try:
        src_init_stat = (repo / "src" / "__init__.py").lstat()
        src_is_package = not _is_link_like(src_init_stat) and stat.S_ISREG(
            src_init_stat.st_mode
        )
    except OSError:
        pass
    if module_relative.startswith("src/") and not src_is_package:
        module_relative = module_relative[len("src/") :]
    module_name = module_relative.removesuffix(".py").replace("/", ".")
    if module_name.endswith(".__init__"):
        module_name = module_name[: -len(".__init__")]
    try:
        tree = ast.parse(_safe_read(path), filename=relative_path)
    except SyntaxError as exc:
        graph.add_warning(relative_path, f"Python syntax could not be parsed at line {exc.lineno or '?'}")
        return
    except RecursionError as exc:
        raise OntologyError("Python syntax exceeds the parser nesting safety limit.") from exc
    _validate_python_ast_limits(tree)
    module_id = graph.add_node(
        _node_id("python", "module", module_name),
        "Module",
        module_name.rsplit(".", 1)[-1],
        "Python",
        path=relative_path,
        qualified_name=module_name,
        metadata={"line_start": 1, "line_end": 1},
    )
    try:
        PythonVisitor(
            graph,
            module_id,
            module_name,
            relative_path,
            tree,
            is_package=Path(relative_path).name == "__init__.py",
        ).visit(tree)
    except RecursionError as exc:
        raise OntologyError("Python AST traversal exceeded the nesting safety limit.") from exc


def preflight_document(repo: Path) -> dict[str, Any]:
    sources, skipped = discover_sources(repo)
    by_language = Counter(SUPPORTED_SUFFIXES[path.suffix.lower()] for path in sources)
    return {
        "status": "ready" if sources else "no_supported_sources",
        "repository_name": repo.name,
        "supported_languages": dict(sorted(by_language.items())),
        "adapter_coverage": {
            language: _adapter_quality(language) for language in sorted(by_language)
        },
        "source_file_count": len(sources),
        "skipped": dict(sorted(skipped.items())),
        "limits": {
            "max_source_bytes": MAX_SOURCE_BYTES,
            "max_source_files": MAX_SOURCE_FILES,
            "max_total_source_bytes": MAX_TOTAL_SOURCE_BYTES,
            "max_graph_nodes": MAX_GRAPH_NODES,
            "max_graph_edges": MAX_GRAPH_EDGES,
            "max_impact_results": MAX_IMPACT_RESULTS,
            "max_python_ast_nodes": MAX_PYTHON_AST_NODES,
            "max_python_ast_depth": MAX_PYTHON_AST_DEPTH,
            "follows_symlinks": False,
            "executes_source": False,
            "network_access": False,
            "writes_during_preflight": False,
        },
        "next_step": (
            "Review this summary and obtain the repository owner's confirmation before indexing."
            if sources
            else "Point --repo to a Java or Python source repository."
        ),
    }


def build_document(repo: Path) -> dict[str, Any]:
    sources, skipped = discover_sources(repo)
    graph = Graph(repo.name)
    source_counts: Counter[str] = Counter()
    repository_package_types: dict[str, set[str]] | None = {}
    for path in sources:
        if SUPPORTED_SUFFIXES[path.suffix.lower()] != "Java":
            continue
        try:
            package_name, declared_types = _java_package_and_declared_types(
                _safe_read(path)
            )
        except (OntologyError, UnicodeError):
            # An incomplete name index cannot prove that a Spring wildcard is
            # unshadowed, so disable wildcard semantics for this build.
            repository_package_types = None
            break
        repository_package_types.setdefault(package_name, set()).update(declared_types)
    for path in sources:
        language = SUPPORTED_SUFFIXES[path.suffix.lower()]
        source_counts[language] += 1
        try:
            if language == "Java":
                analyze_java(
                    graph,
                    repo,
                    path,
                    repository_package_types=repository_package_types,
                )
            elif language == "Python":
                analyze_python(graph, repo, path)
        except (OntologyError, UnicodeError) as exc:
            graph.add_warning(path.relative_to(repo).as_posix(), str(exc))
    return graph.document(source_counts, skipped)


def _turtle_literal(value: Any) -> str:
    rendered = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{rendered}"'


def _turtle_uri(node_id: str) -> str:
    return f"<urn:code-ontology:node:{quote(node_id, safe='')}>"


def render_turtle(document: dict[str, Any]) -> str:
    lines = [
        "@prefix co: <https://battle-doll.github.io/code-ontology-explorer/schema#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for node in document["nodes"]:
        subject = _turtle_uri(node["id"])
        lines.append(f"{subject} a co:{node['type']} ;")
        predicates = [
            ("rdfs:label", _turtle_literal(node["name"])),
            ("co:language", _turtle_literal(node["language"])),
        ]
        if node.get("qualified_name"):
            predicates.append(("co:qualifiedName", _turtle_literal(node["qualified_name"])))
        if node.get("path"):
            predicates.append(("co:relativePath", _turtle_literal(node["path"])))
        for index, (predicate, value) in enumerate(predicates):
            ending = " ." if index == len(predicates) - 1 else " ;"
            lines.append(f"    {predicate} {value}{ending}")
        lines.append("")
    for edge in document["edges"]:
        predicate = re.sub(r"[^A-Za-z0-9]", "", edge["type"].title())
        lines.append(
            f"{_turtle_uri(edge['source'])} co:{predicate} {_turtle_uri(edge['target'])} ."
        )
        for evidence in edge.get("evidence", []):
            canonical = json.dumps(
                {
                    "source": edge["source"],
                    "target": edge["target"],
                    "type": edge["type"],
                    "evidence": evidence,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            evidence_uri = (
                "<urn:code-ontology:relationship-evidence:"
                f"{hashlib.sha256(canonical).hexdigest()}>"
            )
            evidence_predicates = [
                ("rdf:subject", _turtle_uri(edge["source"])),
                ("rdf:predicate", f"co:{predicate}"),
                ("rdf:object", _turtle_uri(edge["target"])),
                ("co:relationshipType", _turtle_literal(edge["type"])),
                ("co:ruleId", _turtle_literal(evidence["rule_id"])),
                ("co:evidenceBasis", _turtle_literal(evidence["basis"])),
                ("co:runtimeStatus", _turtle_literal(evidence["runtime_status"])),
            ]
            if evidence.get("path"):
                evidence_predicates.append(
                    ("co:evidencePath", _turtle_literal(evidence["path"]))
                )
            if isinstance(evidence.get("line_start"), int):
                evidence_predicates.extend(
                    [
                        ("co:lineStart", f'"{evidence["line_start"]}"^^xsd:integer'),
                        ("co:lineEnd", f'"{evidence["line_end"]}"^^xsd:integer'),
                    ]
                )
            evidence_predicates.extend(
                ("co:limitationId", _turtle_literal(value))
                for value in evidence.get("limitations", [])
            )
            lines.append(f"{evidence_uri} a co:RelationshipEvidence, rdf:Statement ;")
            for index, (quality_predicate, value) in enumerate(evidence_predicates):
                ending = " ." if index == len(evidence_predicates) - 1 else " ;"
                lines.append(f"    {quality_predicate} {value}{ending}")
            lines.append("")

    quality = document.get("quality", {})
    relationship_quality = quality.get("relationship_evidence", {})
    if isinstance(quality, dict) and isinstance(relationship_quality, dict):
        quality_scope = json.dumps(
            {
                "generator": document.get("generator", {}),
                "edges": [
                    (edge.get("source"), edge.get("target"), edge.get("type"))
                    for edge in document.get("edges", [])
                    if isinstance(edge, dict)
                ],
                "quality": quality,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        quality_digest = hashlib.sha256(quality_scope).hexdigest()
        quality_uri = f"<urn:code-ontology:quality:{quality_digest}>"
        lines.extend(
            [
                f"{quality_uri} a co:OntologyQuality ;",
                f"    co:contractVersion {_turtle_literal(quality.get('contract_version', 'unknown'))} ;",
                "    co:documentedEdges "
                f'"{int(relationship_quality.get("documented_edges", 0))}"^^xsd:integer ;',
                "    co:missingEvidence "
                f'"{int(relationship_quality.get("missing_evidence", 0))}"^^xsd:integer ;',
                "    co:coveragePercent "
                f'"{float(relationship_quality.get("coverage_percent", 0.0))}"^^xsd:decimal .',
                "",
            ]
        )
        for language, adapter in sorted(quality.get("adapters", {}).items()):
            adapter_uri = (
                f"<urn:code-ontology:adapter-quality:{quality_digest}:"
                f"{quote(language, safe='')}>"
            )
            adapter_predicates = [
                ("co:language", _turtle_literal(language)),
                ("co:supportStatus", _turtle_literal(adapter.get("status", "unknown"))),
                (
                    "co:detected",
                    f'"{str(adapter.get("detected") is True).lower()}"^^xsd:boolean',
                ),
            ]
            adapter_predicates.extend(
                (
                    "co:capability",
                    _turtle_literal(f"{name}={status}"),
                )
                for name, status in sorted(adapter.get("capabilities", {}).items())
            )
            adapter_predicates.extend(
                ("co:unsupportedRuntime", _turtle_literal(value))
                for value in adapter.get("unsupported_runtime", [])
            )
            lines.append(f"{adapter_uri} a co:AdapterQuality ;")
            for index, (quality_predicate, value) in enumerate(adapter_predicates):
                ending = " ." if index == len(adapter_predicates) - 1 else " ;"
                lines.append(f"    {quality_predicate} {value}{ending}")
            lines.append(f"{quality_uri} co:hasAdapterQuality {adapter_uri} .")
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def render_report(document: dict[str, Any]) -> str:
    stats = document["statistics"]
    quality = document.get("quality", {})
    relationship_quality = quality.get("relationship_evidence", {})
    lines = [
        "# Code Ontology Report",
        "",
        f"- Repository label: `{document['repository']['name']}`",
        f"- Source files analyzed: {sum(stats['source_files'].values())}",
        f"- Nodes: {stats['nodes']}",
        f"- Edges: {stats['edges']}",
        f"- Parse warnings: {stats['warnings']}",
        "- Relationship evidence coverage: "
        f"{relationship_quality.get('coverage_percent', 'unknown')}% "
        f"({relationship_quality.get('documented_edges', 0)}/"
        f"{relationship_quality.get('total_edges', 0)})",
        "- Relationship source-span coverage: "
        f"{relationship_quality.get('source_span_coverage_percent', 'unknown')}%",
        "",
        "## Privacy boundary",
        "",
        "The ontology contains identifiers, relationships, language labels, and repository-relative paths.",
        "It does not contain source bodies, comments, absolute paths, file hashes, credentials, or model prompts.",
        "",
        "## Node types",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in stats["node_types"].items())
    lines.extend(["", "## Relationship types", ""])
    lines.extend(f"- {key}: {value}" for key, value in stats["edge_types"].items())
    lines.extend(["", "## Ontology quality", ""])
    lines.append(
        "Relationship evidence uses qualitative extraction bases, stable rule IDs, "
        "and bounded relative source spans. It is not a probability score."
    )
    for basis, count in relationship_quality.get("basis_counts", {}).items():
        lines.append(f"- Evidence basis `{basis}`: {count}")
    for language, adapter in sorted(quality.get("adapters", {}).items()):
        lines.append(
            f"- {language} adapter: `{adapter.get('status', 'unknown')}` "
            f"(detected: `{'yes' if adapter.get('detected') is True else 'no'}`)"
        )
        for capability, status in sorted(adapter.get("capabilities", {}).items()):
            lines.append(f"  - `{capability}`: `{status}`")
        unsupported = ", ".join(adapter.get("unsupported_runtime", []))
        if unsupported:
            lines.append(f"  - Unsupported runtime evidence: {unsupported}")
    lines.extend(
        [
            "",
            "## Interpretation note",
            "",
            "Static relationships are evidence for exploration, not proof of runtime behavior.",
            "Reflection, generated code, framework configuration, and dynamic dispatch may be incomplete.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        finally:
            raise


def write_index(
    repo: Path,
    output: Path,
    authorized: bool,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not authorized:
        raise OntologyError(
            "Indexing requires --authorized after the repository owner has confirmed the scan."
        )
    raw_output = output.expanduser()
    if raw_output.is_symlink():
        raise OntologyError("The output directory may not be a symbolic link.")
    output = raw_output.resolve()
    if output == repo or _is_relative_to(output, repo) or _is_relative_to(repo, output):
        raise OntologyError(
            "The output directory must be separate from the target repository and its parent directories."
        )
    artifact_paths = [output / name for name in ("ontology.json", "ontology.ttl", "report.md")]
    symlinks = [path.name for path in artifact_paths if path.is_symlink()]
    if symlinks:
        raise OntologyError("Refusing to write through symbolic-link artifacts: " + ", ".join(symlinks))
    existing = [path.name for path in artifact_paths if path.exists()]
    if existing and not overwrite:
        raise OntologyError(
            "Refusing to replace existing artifacts without --overwrite: " + ", ".join(existing)
        )
    document = build_document(repo)
    output.mkdir(parents=True, exist_ok=True)
    _write_text(output / "ontology.json", json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    _write_text(output / "ontology.ttl", render_turtle(document))
    _write_text(output / "report.md", render_report(document))
    return {
        "status": "indexed",
        "output_directory": str(output),
        "artifacts": ["ontology.json", "ontology.ttl", "report.md"],
        "statistics": document["statistics"],
    }


def load_document(index_path: str) -> tuple[Path, dict[str, Any]]:
    path = Path(index_path).expanduser().resolve()
    if not path.is_file():
        raise OntologyError(f"Ontology index does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OntologyError(f"Could not read ontology JSON: {exc}") from exc
    if document.get("schema_version") != SCHEMA_VERSION:
        raise OntologyError(
            f"Unsupported schema version: {document.get('schema_version', 'missing')}"
        )
    if not isinstance(document.get("nodes"), list) or not isinstance(document.get("edges"), list):
        raise OntologyError("Ontology JSON is missing nodes or edges.")
    return path, document


def query_document(document: dict[str, Any], term: str, limit: int) -> dict[str, Any]:
    needle = term.casefold()
    matches = []
    for node in document["nodes"]:
        searchable = " ".join(
            str(node.get(key, ""))
            for key in ("id", "type", "name", "language", "path", "qualified_name", "metadata")
        ).casefold()
        if needle in searchable:
            matches.append(node)
    matches.sort(key=lambda node: (node["name"].casefold(), node["id"]))
    return {
        "term": term,
        "match_count": len(matches),
        "returned": min(len(matches), limit),
        "matches": matches[:limit],
    }


def _portable_relationship_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    portable: list[dict[str, Any]] = []
    for raw in value[:MAX_EDGE_EVIDENCE_ITEMS]:
        if not isinstance(raw, dict):
            continue
        rule_id = raw.get("rule_id")
        basis = raw.get("basis")
        runtime_status = raw.get("runtime_status")
        if (
            not isinstance(rule_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", rule_id)
            or basis not in EVIDENCE_BASES
            or runtime_status not in RUNTIME_STATUSES
        ):
            continue
        item: dict[str, Any] = {
            "rule_id": rule_id,
            "basis": basis,
            "runtime_status": runtime_status,
        }
        path = raw.get("path")
        if isinstance(path, str) and _portable_relative_path(path):
            item["path"] = path.replace("\\", "/")
        line_start = raw.get("line_start")
        line_end = raw.get("line_end")
        if isinstance(line_start, int) and line_start >= 1:
            item["line_start"] = line_start
            item["line_end"] = max(
                line_start,
                line_end if isinstance(line_end, int) else line_start,
            )
        limitations = raw.get("limitations")
        if isinstance(limitations, list):
            clean_limitations = sorted(
                {
                    item
                    for item in limitations[:32]
                    if isinstance(item, str)
                    and re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", item)
                }
            )
            if clean_limitations:
                item["limitations"] = clean_limitations
        portable.append(item)
    return portable


def impact_document(document: dict[str, Any], symbol: str, depth: int) -> dict[str, Any]:
    query = query_document(document, symbol, limit=1000)
    exact = [
        node
        for node in query["matches"]
        if node["id"].casefold() == symbol.casefold()
        or node.get("qualified_name", "").casefold() == symbol.casefold()
        or node["name"].casefold() == symbol.casefold()
    ]
    candidates = exact or query["matches"]
    if not candidates:
        return {"symbol": symbol, "status": "not_found", "candidates": [], "impact": []}
    if len(candidates) > 1:
        return {
            "symbol": symbol,
            "status": "ambiguous",
            "candidates": [
                {
                    "id": node["id"],
                    "name": node["name"],
                    "qualified_name": node.get("qualified_name"),
                }
                for node in candidates[:20]
            ],
            "impact": [],
        }
    start = candidates[0]
    nodes_by_id = {node["id"]: node for node in document["nodes"]}
    adjacency: dict[str, list[tuple[str, str, str, list[dict[str, Any]]]]] = {}
    for edge in document["edges"]:
        adjacency.setdefault(edge["source"], []).append(
            (
                edge["target"],
                edge["type"],
                "outgoing",
                _portable_relationship_evidence(edge.get("evidence")),
            )
        )
        adjacency.setdefault(edge["target"], []).append(
            (
                edge["source"],
                edge["type"],
                "incoming",
                _portable_relationship_evidence(edge.get("evidence")),
            )
        )
    visited = {start["id"]}
    queue: deque[tuple[str, int]] = deque([(start["id"], 0)])
    impact: list[dict[str, Any]] = []
    truncated = False
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor, relationship, direction, evidence in sorted(
            adjacency.get(current, []),
            key=lambda item: (item[0], item[1], item[2]),
        ):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            next_depth = current_depth + 1
            neighbor_node = nodes_by_id.get(
                neighbor,
                {"id": neighbor, "name": neighbor, "type": "Unknown", "language": "Unknown"},
            )
            impact.append(
                {
                    "depth": next_depth,
                    "relationship": relationship,
                    "direction": direction,
                    "evidence": evidence,
                    "node": neighbor_node,
                }
            )
            if len(impact) >= MAX_IMPACT_RESULTS:
                truncated = True
                queue.clear()
                break
            queue.append((neighbor, next_depth))
    impact.sort(key=lambda item: (item["depth"], item["node"]["name"].casefold()))
    return {
        "symbol": symbol,
        "status": "ok",
        "root": start,
        "depth": depth,
        "impact_count": len(impact),
        "truncated": truncated,
        "impact": impact,
        "interpretation": "Static relationship neighborhood; validate runtime behavior separately.",
    }


def _read_visualization_asset(relative_path: str, expected_sha256: str | None = None) -> str:
    """Read a bundled workbench asset and verify pinned third-party bytes."""

    asset_root = VISUALIZATION_ASSET_DIR.resolve()
    raw_asset = VISUALIZATION_ASSET_DIR / relative_path
    if raw_asset.is_symlink():
        raise OntologyError(f"Visualization asset may not be a symbolic link: {relative_path}")
    asset = raw_asset.resolve()
    if not _is_relative_to(asset, asset_root) or asset == asset_root:
        raise OntologyError("Visualization asset escaped the bundled asset directory.")
    if not asset.is_file():
        raise OntologyError(f"Visualization asset is missing: {relative_path}")
    try:
        raw = asset.read_bytes()
    except OSError as exc:
        raise OntologyError(f"Visualization asset is unreadable: {relative_path}") from exc
    if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise OntologyError(f"Visualization asset failed integrity verification: {relative_path}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OntologyError(f"Visualization asset is not UTF-8: {relative_path}") from exc


def _portable_visualization_node(node: dict[str, Any]) -> dict[str, Any]:
    """Copy only ontology fields intended for the portable browser artifact."""

    portable: dict[str, Any] = {
        key: node[key]
        for key in ("id", "type", "name", "language", "qualified_name")
        if key in node and isinstance(node[key], (str, int, float, bool))
    }
    path = node.get("path")
    if isinstance(path, str) and _is_portable_visualization_path(path):
        portable["path"] = path
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        allowed_metadata = {
            key: metadata[key]
            for key in (
                "accessor",
                "control_kind",
                "ordinal",
                "parameter_count",
                "parameter_types",
                "return_type",
                "semantic_groups",
            )
            if key in metadata
            and isinstance(metadata[key], (str, int, float, bool, list, type(None)))
        }
        if allowed_metadata:
            portable["metadata"] = allowed_metadata
    return portable


def _is_portable_visualization_path(value: str) -> bool:
    if not value or Path(value).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    normalized_parts = value.replace("\\", "/").split("/")
    return ".." not in normalized_parts


def _visualization_statistics(document: dict[str, Any]) -> dict[str, Any]:
    nodes = document.get("nodes", [])
    edges = document.get("edges", [])
    original = document.get("statistics", {})
    source_files = original.get("source_files", {}) if isinstance(original, dict) else {}
    skipped = original.get("skipped", {}) if isinstance(original, dict) else {}
    return {
        "sourceFiles": {
            str(key): int(value)
            for key, value in sorted(source_files.items())
            if isinstance(value, int) and value >= 0
        },
        "nodes": len(nodes),
        "edges": len(edges),
        "nodeTypes": dict(sorted(Counter(str(node.get("type", "Unknown")) for node in nodes).items())),
        "edgeTypes": dict(sorted(Counter(str(edge.get("type", "Unknown")) for edge in edges).items())),
        "skipped": {
            str(key): int(value)
            for key, value in sorted(skipped.items())
            if isinstance(value, int) and value >= 0
        },
        "warnings": len(document.get("warnings", [])),
    }


def _portable_quality(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "contract_version": "legacy_unknown",
            "relationship_evidence": {
                "total_edges": 0,
                "documented_edges": 0,
                "missing_evidence": 0,
                "coverage_percent": 0.0,
                "basis_counts": {},
                "runtime_status_counts": {},
            },
            "adapters": {},
            "interpretation": "Legacy snapshot without ontology quality metadata.",
        }
    relationship = value.get("relationship_evidence", {})
    if not isinstance(relationship, dict):
        relationship = {}
    counts = {}
    for field in (
        "total_edges",
        "documented_edges",
        "missing_evidence",
        "source_span_edges",
    ):
        raw = relationship.get(field, 0)
        counts[field] = raw if isinstance(raw, int) and raw >= 0 else 0
    for field in ("coverage_percent", "source_span_coverage_percent"):
        raw = relationship.get(field, 0.0)
        counts[field] = (
            round(max(0.0, min(100.0, float(raw))), 3)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool)
            else 0.0
        )
    for field in ("basis_counts", "runtime_status_counts"):
        raw = relationship.get(field, {})
        counts[field] = (
            {
                str(key): int(count)
                for key, count in sorted(raw.items())
                if isinstance(key, str) and isinstance(count, int) and count >= 0
            }
            if isinstance(raw, dict)
            else {}
        )
    adapters: dict[str, Any] = {}
    raw_adapters = value.get("adapters", {})
    if isinstance(raw_adapters, dict):
        for language, raw_adapter in sorted(raw_adapters.items()):
            if not isinstance(language, str) or not isinstance(raw_adapter, dict):
                continue
            status = raw_adapter.get("status", "unsupported")
            if status not in {"supported", "partial", "unsupported"}:
                status = "unsupported"
            capabilities = raw_adapter.get("capabilities", {})
            clean_capabilities = (
                {
                    str(name): capability_status
                    for name, capability_status in sorted(capabilities.items())
                    if isinstance(name, str)
                    and capability_status in {"supported", "partial", "unsupported"}
                }
                if isinstance(capabilities, dict)
                else {}
            )
            unsupported_runtime = raw_adapter.get("unsupported_runtime", [])
            adapters[language] = {
                "status": status,
                "detected": raw_adapter.get("detected") is True,
                "capabilities": clean_capabilities,
                "unsupported_runtime": [
                    item
                    for item in unsupported_runtime[:32]
                    if isinstance(item, str)
                    and re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", item)
                ]
                if isinstance(unsupported_runtime, list)
                else [],
            }
    interpretation = value.get("interpretation", "")
    return {
        "contract_version": str(value.get("contract_version", "legacy_unknown")),
        "relationship_evidence": counts,
        "adapters": adapters,
        "interpretation": interpretation[:500] if isinstance(interpretation, str) else "",
    }


def _visualization_diff(
    document: dict[str, Any],
    previous_document: dict[str, Any] | None,
) -> dict[str, Any]:
    current_companion = document.get("companion", {})
    after_snapshot = (
        str(current_companion.get("snapshotId", "current"))
        if isinstance(current_companion, dict)
        else "current"
    )
    empty_counts = {
        "nodesAdded": 0,
        "nodesRemoved": 0,
        "nodesModified": 0,
        "edgesAdded": 0,
        "edgesRemoved": 0,
    }
    if previous_document is None:
        return {
            "available": False,
            "basis": "no_previous_snapshot",
            "beforeSnapshotId": "",
            "afterSnapshotId": after_snapshot,
            "counts": empty_counts,
            "nodesAdded": [],
            "nodesRemoved": [],
            "nodesModified": [],
            "edgesAdded": [],
            "edgesRemoved": [],
            "truncated": False,
        }

    current_nodes = {
        str(node["id"]): _portable_visualization_node(node)
        for node in document.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    previous_nodes = {
        str(node["id"]): _portable_visualization_node(node)
        for node in previous_document.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    added_ids = sorted(current_nodes.keys() - previous_nodes.keys())
    removed_ids = sorted(previous_nodes.keys() - current_nodes.keys())
    modified_ids = sorted(
        node_id
        for node_id in current_nodes.keys() & previous_nodes.keys()
        if current_nodes[node_id] != previous_nodes[node_id]
    )

    def edge_keys(value: dict[str, Any]) -> set[tuple[str, str, str]]:
        return {
            (str(edge.get("source", "")), str(edge.get("target", "")), str(edge.get("type", "")))
            for edge in value.get("edges", [])
            if isinstance(edge, dict)
        }

    current_edges = edge_keys(document)
    previous_edges = edge_keys(previous_document)
    previous_companion = previous_document.get("companion", {})
    current_fingerprint = (
        current_companion.get("sourceFingerprint") if isinstance(current_companion, dict) else None
    )
    previous_fingerprint = (
        previous_companion.get("sourceFingerprint") if isinstance(previous_companion, dict) else None
    )
    basis = (
        "analysis_refresh"
        if current_fingerprint and current_fingerprint == previous_fingerprint
        else "source_change"
    )
    limit = VISUALIZATION_DIFF_ITEM_LIMIT
    added_edges = sorted(current_edges - previous_edges)
    removed_edges = sorted(previous_edges - current_edges)

    def portable_edges(values: list[tuple[str, str, str]]) -> list[dict[str, str]]:
        return [
            {"source": source, "target": target, "type": edge_type}
            for source, target, edge_type in values[:limit]
        ]

    before_snapshot = (
        str(previous_companion.get("snapshotId", "previous"))
        if isinstance(previous_companion, dict)
        else "previous"
    )
    return {
        "available": True,
        "basis": basis,
        "beforeSnapshotId": before_snapshot,
        "afterSnapshotId": after_snapshot,
        "counts": {
            "nodesAdded": len(added_ids),
            "nodesRemoved": len(removed_ids),
            "nodesModified": len(modified_ids),
            "edgesAdded": len(added_edges),
            "edgesRemoved": len(removed_edges),
        },
        "nodesAdded": [current_nodes[node_id] for node_id in added_ids[:limit]],
        "nodesRemoved": [previous_nodes[node_id] for node_id in removed_ids[:limit]],
        "nodesModified": [current_nodes[node_id] for node_id in modified_ids[:limit]],
        "edgesAdded": portable_edges(added_edges),
        "edgesRemoved": portable_edges(removed_edges),
        "truncated": any(
            len(values) > limit
            for values in (added_ids, removed_ids, modified_ids, added_edges, removed_edges)
        ),
    }


def _visualization_payload(
    document: dict[str, Any],
    max_nodes: int,
    previous_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    nodes = sorted(
        (
            _portable_visualization_node(node)
            for node in document.get("nodes", [])
            if isinstance(node, dict) and isinstance(node.get("id"), str)
        ),
        key=lambda node: node["id"],
    )
    node_ids = {node["id"] for node in nodes}
    edges = sorted(
        (
            {
                "source": str(edge["source"]),
                "target": str(edge["target"]),
                "type": str(edge["type"]),
                "evidence": _portable_relationship_evidence(edge.get("evidence")),
            }
            for edge in document.get("edges", [])
            if isinstance(edge, dict)
            and all(isinstance(edge.get(key), str) for key in ("source", "target", "type"))
            and edge["source"] in node_ids
            and edge["target"] in node_ids
        ),
        key=lambda edge: (edge["source"], edge["target"], edge["type"]),
    )
    repository = document.get("repository", {})
    generator = document.get("generator", {})
    companion = document.get("companion", {})
    warnings = []
    for warning in document.get("warnings", []):
        if not isinstance(warning, dict):
            continue
        warning_path = warning.get("path")
        message = warning.get("message")
        if (
            isinstance(warning_path, str)
            and _is_portable_visualization_path(warning_path)
            and isinstance(message, str)
        ):
            warnings.append({"path": warning_path, "message": message})
    return {
        "meta": {
            "repositoryName": str(repository.get("name", "repository")),
            "generatedAt": str(document.get("generated_at", "")),
            "generatorVersion": str(generator.get("version", PLUGIN_VERSION)),
            "snapshotId": str(companion.get("snapshotId", "standalone")),
            "evidenceType": str(companion.get("evidenceType", "observed")),
        },
        "statistics": _visualization_statistics(document),
        "quality": _portable_quality(document.get("quality")),
        "warnings": warnings,
        "nodes": nodes,
        "edges": edges,
        "changes": _visualization_diff(document, previous_document),
        "limits": {
            "maxVisibleNodes": min(
                len(nodes), max(1, min(int(max_nodes), VISUALIZATION_MAX_VISIBLE_NODES))
            ),
            "searchResultLimit": 80,
        },
    }


def render_visualization(
    document: dict[str, Any],
    max_nodes: int,
    previous_document: dict[str, Any] | None = None,
) -> str:
    """Render a self-contained, offline, progressive-disclosure workbench."""

    if max_nodes < 1:
        raise OntologyError("Visualization max_nodes must be at least 1.")
    template = _read_visualization_asset("workbench.html")
    stylesheet = _read_visualization_asset("workbench.css")
    application = _read_visualization_asset("workbench.js")
    cytoscape = _read_visualization_asset(*VISUALIZATION_VENDOR_ASSETS["cytoscape"])
    elk = _read_visualization_asset(*VISUALIZATION_VENDOR_ASSETS["elk"])
    data = json.dumps(
        _visualization_payload(document, max_nodes, previous_document),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    # A JSON script element can still be terminated by source-derived HTML.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    title = html.escape(str(document.get("repository", {}).get("name", "repository")), quote=False)
    replacements = {
        "__CODE_ONTOLOGY_TITLE__": title,
        "__CODE_ONTOLOGY_CSS__": stylesheet,
        "__CODE_ONTOLOGY_CYTOSCAPE__": cytoscape,
        "__CODE_ONTOLOGY_ELK__": elk,
        "__CODE_ONTOLOGY_DATA__": data,
        "__CODE_ONTOLOGY_APP__": application,
    }
    missing = [marker for marker in replacements if marker not in template]
    if missing:
        raise OntologyError("Visualization template is missing required placeholders.")
    marker_pattern = re.compile("|".join(re.escape(marker) for marker in replacements))
    return marker_pattern.sub(lambda match: replacements[match.group(0)], template)


def write_visualization(
    index_path: str,
    output_path: str,
    max_nodes: int,
    overwrite: bool = False,
    previous_index_path: str | None = None,
) -> dict[str, Any]:
    index, document = load_document(index_path)
    previous_document = None
    if previous_index_path:
        _, previous_document = load_document(previous_index_path)
    raw_output = Path(output_path).expanduser()
    if raw_output.is_symlink():
        raise OntologyError("The visualization output may not be a symbolic link.")
    output = raw_output.resolve()
    if output.suffix.lower() != ".html":
        raise OntologyError("Visualization output must end in .html")
    if output.parent != index.parent:
        raise OntologyError("Visualization output must be in the ontology index directory.")
    if output.exists() and not overwrite:
        raise OntologyError("Refusing to replace an existing visualization without --overwrite")
    _write_text(output, render_visualization(document, max_nodes, previous_document))
    visible_limit = min(
        len(document["nodes"]), max(1, min(max_nodes, VISUALIZATION_MAX_VISIBLE_NODES))
    )
    return {
        "status": "visualized",
        "index": str(index),
        "output": str(output),
        "nodes_rendered": visible_limit,
        "nodes_indexed": len(document["nodes"]),
        "max_visible_nodes": visible_limit,
        "network_dependencies": 0,
    }


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code_ontology.py",
        description="Build and explore a local static code ontology without executing target code.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="Read-only scan summary; writes nothing.")
    preflight.add_argument("--repo", required=True, help="Authorized repository directory.")

    index = subparsers.add_parser("index", help="Build JSON, RDF/Turtle, and Markdown artifacts.")
    index.add_argument("--repo", required=True, help="Authorized repository directory.")
    index.add_argument("--output", required=True, help="Output directory outside the repository.")
    index.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm the repository owner authorized static analysis.",
    )
    index.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing ontology artifacts after explicit confirmation.",
    )

    query = subparsers.add_parser("query", help="Search nodes in an ontology JSON index.")
    query.add_argument("--index", required=True, help="Path to ontology.json.")
    query.add_argument("--term", required=True, help="Case-insensitive symbol or concept search.")
    query.add_argument("--limit", type=int, default=20, choices=range(1, 201), metavar="1..200")

    impact = subparsers.add_parser("impact", help="Explore the static relationship neighborhood.")
    impact.add_argument("--index", required=True, help="Path to ontology.json.")
    impact.add_argument("--symbol", required=True, help="Name, qualified name, or exact node id.")
    impact.add_argument("--depth", type=int, default=2, choices=range(1, 6), metavar="1..5")

    visualize = subparsers.add_parser(
        "visualize", help="Create a self-contained offline HTML graph."
    )
    visualize.add_argument("--index", required=True, help="Path to ontology.json.")
    visualize.add_argument("--output", required=True, help="Destination .html path.")
    visualize.add_argument(
        "--max-nodes", type=int, default=500, choices=range(1, 2001), metavar="1..2000"
    )
    visualize.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing HTML file after explicit confirmation.",
    )
    visualize.add_argument(
        "--previous-index",
        help="Optional previous ontology.json used for a local snapshot diff.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            repo = _resolve_dir(args.repo, "Repository")
            _json_print(preflight_document(repo))
        elif args.command == "index":
            repo = _resolve_dir(args.repo, "Repository")
            _json_print(
                write_index(
                    repo,
                    Path(args.output),
                    args.authorized,
                    overwrite=args.overwrite,
                )
            )
        elif args.command == "query":
            _, document = load_document(args.index)
            _json_print(query_document(document, args.term, args.limit))
        elif args.command == "impact":
            _, document = load_document(args.index)
            _json_print(impact_document(document, args.symbol, args.depth))
        elif args.command == "visualize":
            _json_print(
                write_visualization(
                    args.index,
                    args.output,
                    args.max_nodes,
                    overwrite=args.overwrite,
                    previous_index_path=args.previous_index,
                )
            )
        else:
            parser.error(f"Unknown command: {args.command}")
    except OntologyError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
