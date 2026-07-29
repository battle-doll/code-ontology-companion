#!/usr/bin/env python3
"""Build and explore a privacy-preserving local code ontology.

This utility uses only the Python standard library. It performs static analysis;
it never imports, builds, or executes the target repository.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
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
PLUGIN_VERSION = "0.1.1"
ONTOLOGY_NS = "https://battle-doll.github.io/code-ontology-explorer/schema#"
SUPPORTED_SUFFIXES = {".java": "Java", ".py": "Python"}
MAX_SOURCE_BYTES = 2 * 1024 * 1024
WINDOWS_REPARSE_POINT = 0x400
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
JAVA_TYPE_RE = re.compile(
    r"(?P<annotations>(?:@\w+(?:\s*\([^)]*\))?\s*)*)"
    r"(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed)\s+)*"
    r"(?P<kind>class|interface|enum|record)\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\s+extends\s+(?P<extends>[A-Za-z_][\w.$<>?, ]*))?"
    r"(?:\s+implements\s+(?P<implements>[A-Za-z_][\w.$<>?, ]*))?",
    re.MULTILINE,
)
JAVA_METHOD_RE = re.compile(
    r"^[ \t]*"
    r"(?P<annotations>(?:@\w+(?:\s*\([^)]*\))?\s*)*)"
    r"(?:(?:public|protected|private|abstract|final|static|synchronized|native|default|strictfp)\s+)*"
    r"(?!return\b|throw\b|new\b|if\b|for\b|while\b|switch\b|catch\b|do\b|else\b)"
    r"(?:<[^>{};]+>\s+)?"
    r"(?P<return>[A-Za-z_][\w.$<>\[\], ?]*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)"
    r"\s*(?:throws\s+[^{;]+)?(?P<ending>\{|;)",
    re.MULTILINE,
)
JAVA_FIELD_RE = re.compile(
    r"(?P<annotations>(?:@\w+(?:\s*\([^)]*\))?\s*)+)"
    r"(?:(?:public|protected|private|final|static|volatile|transient)\s+)*"
    r"(?P<type>[A-Za-z_][\w.$<>\[\], ?]*)\s+(?P<name>[A-Za-z_]\w*)\s*(?:=[^;]*)?;",
    re.MULTILINE,
)
JAVA_ANNOTATION_RE = re.compile(r"@([A-Za-z_]\w*)")


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
            sources.append(candidate)
    return sorted(sources), skipped


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    try:
        return os.path.samestat(left, right)
    except (AttributeError, OSError):
        return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _stable_file_metadata(file_stat: os.stat_result) -> tuple[int, int, int]:
    return (
        file_stat.st_size,
        getattr(file_stat, "st_mtime_ns", int(file_stat.st_mtime * 1_000_000_000)),
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


class Graph:
    def __init__(self, repository_name: str) -> None:
        self.repository_name = repository_name
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str]] = set()
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
            for key, value in record.items():
                if key not in current or not current[key]:
                    current[key] = value
        else:
            self.nodes[node_id] = record
        return node_id

    def add_edge(self, source: str, target: str, edge_type: str) -> None:
        if source != target:
            self.edges.add((source, target, edge_type))

    def add_external_type(self, language: str, qualified_name: str) -> str:
        simple_name = qualified_name.rsplit(".", 1)[-1]
        return self.add_node(
            _node_id(language, "external_type", qualified_name),
            "ExternalType",
            simple_name,
            language,
            qualified_name=qualified_name,
        )

    def add_annotation(self, annotation: str) -> str:
        groups: list[str] = []
        if annotation in SPRING_STEREOTYPES:
            groups.append("SpringBean")
        if annotation in SPRING_INJECTION:
            groups.append("DependencyInjection")
        if annotation in SPRING_AOP:
            groups.append("AspectOrAdvice")
        if annotation in SPRING_PROXY:
            groups.append("ProxyOrInterceptor")
        return self.add_node(
            f"framework:annotation:{annotation}",
            "FrameworkAnnotation",
            f"@{annotation}",
            "Framework",
            qualified_name=annotation,
            metadata={"semantic_groups": groups},
        )

    def add_warning(self, relative_path: str, message: str) -> None:
        self.warnings.append({"path": relative_path, "message": message})

    def reconcile_references(self) -> None:
        """Redirect external Java placeholders to analyzed internal types."""

        internal_by_name: dict[tuple[str, str], str] = {}
        for node_id, node in self.nodes.items():
            if node["type"] in {"Class", "Interface", "Enum", "Record"}:
                qualified_name = node.get("qualified_name")
                if qualified_name:
                    internal_by_name[(node["language"], qualified_name)] = node_id
        redirects: dict[str, str] = {}
        for node_id, node in self.nodes.items():
            if node["type"] != "ExternalType":
                continue
            qualified_name = node.get("qualified_name")
            target = internal_by_name.get((node["language"], qualified_name))
            if target:
                redirects[node_id] = target
        if not redirects:
            return
        reconciled: set[tuple[str, str, str]] = set()
        for source, target, edge_type in self.edges:
            new_source = redirects.get(source, source)
            new_target = redirects.get(target, target)
            if new_source != new_target:
                reconciled.add((new_source, new_target, edge_type))
        self.edges = reconciled
        for node_id in redirects:
            self.nodes.pop(node_id, None)

    def document(self, source_counts: Counter[str], skipped: Counter[str]) -> dict[str, Any]:
        self.reconcile_references()
        nodes = sorted(self.nodes.values(), key=lambda item: item["id"])
        edges = [
            {"source": source, "target": target, "type": edge_type}
            for source, target, edge_type in sorted(self.edges)
        ]
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
            "nodes": nodes,
            "edges": edges,
            "warnings": sorted(self.warnings, key=lambda item: (item["path"], item["message"])),
        }


def _annotations(text: str) -> list[str]:
    return sorted(set(JAVA_ANNOTATION_RE.findall(text)))


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


def _clean_java_type(raw_type: str) -> str:
    value = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", raw_type)
    value = re.sub(r"<.*>", "", value)
    value = value.replace("[]", "").replace("...", "").strip()
    value = re.sub(r"\s+", " ", value)
    return value.split()[-1] if value else ""


def _resolve_java_type(type_name: str, imports: dict[str, str], package_name: str) -> str:
    clean = _clean_java_type(type_name)
    if not clean:
        return "unknown"
    if "." in clean:
        return clean
    if clean in imports:
        return imports[clean]
    java_builtin = {
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
        "Boolean",
        "List",
        "Set",
        "Map",
        "Optional",
    }
    if clean in java_builtin:
        return f"java.lang.{clean}"
    return f"{package_name}.{clean}" if package_name else clean


def _add_java_annotation_edges(graph: Graph, subject: str, annotation_names: Iterable[str]) -> None:
    for annotation in annotation_names:
        annotation_id = graph.add_annotation(annotation)
        graph.add_edge(subject, annotation_id, "ANNOTATED_BY")
        if annotation in SPRING_STEREOTYPES:
            graph.add_edge(subject, "framework:spring:bean", "MANAGED_AS")
            graph.add_node(
                "framework:spring:bean",
                "FrameworkConcept",
                "Spring-managed bean",
                "Framework",
            )
        if annotation in SPRING_PROXY:
            graph.add_edge(subject, "framework:spring:proxy", "MAY_BE_PROXIED_BY")
            graph.add_node(
                "framework:spring:proxy",
                "FrameworkConcept",
                "Spring proxy or interceptor",
                "Framework",
            )


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


def _java_scope_for(scopes: list[dict[str, Any]], position: int) -> dict[str, Any] | None:
    candidates = [
        scope
        for scope in scopes
        if scope["body_start"] < position < scope["body_end"]
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda scope: scope["body_start"])


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


def _java_parameter_types(
    parameters: str,
    imports: dict[str, str],
    package_name: str,
) -> list[str]:
    resolved: list[str] = []
    for parameter in _split_java_parameters(parameters):
        without_annotations = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", parameter).strip()
        without_modifiers = re.sub(r"^(?:final|volatile|transient)\s+", "", without_annotations)
        pieces = without_modifiers.split()
        if len(pieces) < 2:
            continue
        resolved.append(
            _resolve_java_type(" ".join(pieces[:-1]), imports, package_name)
        )
    return resolved


def analyze_java(graph: Graph, repo: Path, path: Path) -> None:
    relative_path = path.relative_to(repo).as_posix()
    original = _safe_read(path)
    source = _strip_java_comments_and_literals(original)
    package_match = re.search(r"^\s*package\s+([\w.]+)\s*;", source, re.MULTILINE)
    package_name = package_match.group(1) if package_match else ""
    imports = {
        qualified.rsplit(".", 1)[-1]: qualified
        for qualified in re.findall(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", source, re.MULTILINE)
        if not qualified.endswith(".*")
    }
    module_name = package_name or relative_path.removesuffix(".java").replace("/", ".")
    module_id = graph.add_node(
        _node_id("java", "package", module_name),
        "Package",
        module_name.rsplit(".", 1)[-1],
        "Java",
        path=relative_path,
        qualified_name=module_name,
    )
    for imported in sorted(imports.values()):
        imported_id = graph.add_external_type("Java", imported)
        graph.add_edge(module_id, imported_id, "IMPORTS")

    raw_scopes: list[dict[str, Any]] = []
    for match in JAVA_TYPE_RE.finditer(source):
        body_start = source.find("{", match.end())
        if body_start < 0:
            graph.add_warning(relative_path, f"Could not locate body for Java type {match.group('name')}")
            continue
        raw_scopes.append(
            {
                "match": match,
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
        type_id = graph.add_node(
            _node_id("java", match.group("kind"), qualified_name),
            node_type,
            type_name,
            "Java",
            path=relative_path,
            qualified_name=qualified_name,
        )
        graph.add_edge(parent["id"] if parent else module_id, type_id, "DECLARES")
        _add_java_annotation_edges(graph, type_id, _annotations(match.group("annotations") or ""))
        scope = {
            **raw_scope,
            "id": type_id,
            "qualified_name": qualified_name,
            "simple_name": type_name,
        }
        scopes.append(scope)
        extends_value = match.group("extends")
        if extends_value:
            target_name = _resolve_java_type(extends_value.split(",", 1)[0], imports, package_name)
            graph.add_edge(type_id, graph.add_external_type("Java", target_name), "EXTENDS")
        implements_value = match.group("implements")
        if implements_value:
            for interface in implements_value.split(","):
                target_name = _resolve_java_type(interface, imports, package_name)
                graph.add_edge(type_id, graph.add_external_type("Java", target_name), "IMPLEMENTS")

    if not scopes:
        return

    for match in JAVA_METHOD_RE.finditer(source):
        owner = _java_scope_for(scopes, match.start())
        if owner is None:
            continue
        method_name = match.group("name")
        if method_name == owner["simple_name"]:
            continue
        parameter_types = _java_parameter_types(match.group("params"), imports, package_name)
        signature = ",".join(parameter_types)
        method_qualified = f"{owner['qualified_name']}#{method_name}({signature})"
        annotations = _annotations(match.group("annotations") or "")
        method_id = graph.add_node(
            _node_id("java", "method", method_qualified),
            "Method",
            method_name,
            "Java",
            path=relative_path,
            qualified_name=method_qualified,
            metadata={
                "return_type": _resolve_java_type(match.group("return"), imports, package_name),
                "parameter_types": parameter_types,
            },
        )
        graph.add_edge(owner["id"], method_id, "DECLARES")
        _add_java_annotation_edges(graph, method_id, annotations)
        if "Bean" in annotations:
            return_type = _resolve_java_type(match.group("return"), imports, package_name)
            bean_id = graph.add_external_type("Java", return_type)
            graph.add_node(
                "framework:spring:bean",
                "FrameworkConcept",
                "Spring-managed bean",
                "Framework",
            )
            graph.add_edge(method_id, bean_id, "DECLARES_BEAN")
            graph.add_edge(bean_id, "framework:spring:bean", "MANAGED_AS")

    for match in JAVA_FIELD_RE.finditer(source):
        owner = _java_scope_for(scopes, match.start())
        if owner is None:
            continue
        annotations = _annotations(match.group("annotations") or "")
        if not set(annotations).intersection(SPRING_INJECTION):
            continue
        target_name = _resolve_java_type(match.group("type"), imports, package_name)
        target_id = graph.add_external_type("Java", target_name)
        graph.add_edge(owner["id"], target_id, "INJECTS")
        for annotation in annotations:
            graph.add_edge(owner["id"], graph.add_annotation(annotation), "ANNOTATED_BY")

    for owner in scopes:
        constructor_re = re.compile(
            rf"^[ \t]*(?:(?:public|protected|private)\s+)?"
            rf"{re.escape(owner['simple_name'])}\s*\((?P<params>[^()]*)\)",
            re.MULTILINE,
        )
        for constructor in constructor_re.finditer(source):
            if _java_scope_for(scopes, constructor.start()) is not owner:
                continue
            for target_name in _java_parameter_types(
                constructor.group("params"),
                imports,
                package_name,
            ):
                if target_name.startswith("java.lang."):
                    continue
                graph.add_edge(
                    owner["id"],
                    graph.add_external_type("Java", target_name),
                    "INJECTS",
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
    lowered = name.lower()
    groups = {
        "Extract": ("extract", "fetch", "read", "ingest", "collect", "source"),
        "Transform": ("transform", "clean", "normalize", "enrich", "map", "parse"),
        "Load": ("load", "write", "persist", "publish", "sink", "store"),
        "Validate": ("validate", "verify", "quality", "check"),
        "Orchestrate": ("pipeline", "workflow", "orchestr", "schedule", "run"),
    }
    for role, tokens in groups.items():
        if any(token in lowered for token in tokens):
            return role
    return None


class PythonVisitor(ast.NodeVisitor):
    def __init__(self, graph: Graph, module_id: str, module_name: str, relative_path: str) -> None:
        self.graph = graph
        self.module_id = module_id
        self.module_name = module_name
        self.relative_path = relative_path
        self.scope: list[tuple[str, str]] = [(module_id, module_name)]

    @property
    def owner(self) -> tuple[str, str]:
        return self.scope[-1]

    def _add_decorators(self, subject_id: str, decorators: list[ast.expr]) -> None:
        for decorator in decorators:
            name = _python_name(decorator)
            if not name:
                continue
            decorator_id = self.graph.add_node(
                _node_id("python", "decorator", name),
                "Decorator",
                name.rsplit(".", 1)[-1],
                "Python",
                qualified_name=name,
            )
            self.graph.add_edge(subject_id, decorator_id, "DECORATED_BY")

    def _add_pipeline_role(self, subject_id: str, name: str) -> None:
        role = _pipeline_role(name)
        if role:
            role_id = self.graph.add_node(
                f"pipeline:role:{role.lower()}",
                "PipelineRole",
                role,
                "Concept",
            )
            self.graph.add_edge(subject_id, role_id, "HAS_PIPELINE_ROLE")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            target_id = self.graph.add_node(
                _node_id("python", "module", alias.name),
                "ExternalModule",
                alias.name.rsplit(".", 1)[-1],
                "Python",
                qualified_name=alias.name,
            )
            self.graph.add_edge(self.module_id, target_id, "IMPORTS")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            target_id = self.graph.add_node(
                _node_id("python", "module", node.module),
                "ExternalModule",
                node.module.rsplit(".", 1)[-1],
                "Python",
                qualified_name=node.module,
            )
            self.graph.add_edge(self.module_id, target_id, "IMPORTS")

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
        )
        self.graph.add_edge(owner_id, class_id, "DECLARES")
        self._add_decorators(class_id, node.decorator_list)
        self._add_pipeline_role(class_id, node.name)
        for base in node.bases:
            base_name = _python_name(base)
            if base_name:
                self.graph.add_edge(
                    class_id,
                    self.graph.add_external_type("Python", base_name),
                    "EXTENDS",
                )
        self.scope.append((class_id, qualified))
        for child in node.body:
            self.visit(child)
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
            metadata={"parameter_count": len(node.args.args) + len(node.args.kwonlyargs)},
        )
        self.graph.add_edge(owner_id, function_id, "DECLARES")
        self._add_decorators(function_id, node.decorator_list)
        self._add_pipeline_role(function_id, node.name)
        self.scope.append((function_id, qualified))
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _python_name(node.func)
        if call_name:
            call_id = self.graph.add_node(
                _node_id("python", "callable", call_name),
                "ExternalCallable",
                call_name.rsplit(".", 1)[-1],
                "Python",
                qualified_name=call_name,
            )
            self.graph.add_edge(self.owner[0], call_id, "CALLS")
        self.generic_visit(node)


def analyze_python(graph: Graph, repo: Path, path: Path) -> None:
    relative_path = path.relative_to(repo).as_posix()
    module_name = relative_path.removesuffix(".py").replace("/", ".")
    if module_name.endswith(".__init__"):
        module_name = module_name[: -len(".__init__")]
    try:
        tree = ast.parse(_safe_read(path), filename=relative_path)
    except SyntaxError as exc:
        graph.add_warning(relative_path, f"Python syntax could not be parsed at line {exc.lineno or '?'}")
        return
    module_id = graph.add_node(
        _node_id("python", "module", module_name),
        "Module",
        module_name.rsplit(".", 1)[-1],
        "Python",
        path=relative_path,
        qualified_name=module_name,
    )
    PythonVisitor(graph, module_id, module_name, relative_path).visit(tree)


def preflight_document(repo: Path) -> dict[str, Any]:
    sources, skipped = discover_sources(repo)
    by_language = Counter(SUPPORTED_SUFFIXES[path.suffix.lower()] for path in sources)
    return {
        "status": "ready" if sources else "no_supported_sources",
        "repository_name": repo.name,
        "supported_languages": dict(sorted(by_language.items())),
        "source_file_count": len(sources),
        "skipped": dict(sorted(skipped.items())),
        "limits": {
            "max_source_bytes": MAX_SOURCE_BYTES,
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
    for path in sources:
        language = SUPPORTED_SUFFIXES[path.suffix.lower()]
        source_counts[language] += 1
        try:
            if language == "Java":
                analyze_java(graph, repo, path)
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
    lines.append("")
    return "\n".join(lines)


def render_report(document: dict[str, Any]) -> str:
    stats = document["statistics"]
    lines = [
        "# Code Ontology Report",
        "",
        f"- Repository label: `{document['repository']['name']}`",
        f"- Source files analyzed: {sum(stats['source_files'].values())}",
        f"- Nodes: {stats['nodes']}",
        f"- Edges: {stats['edges']}",
        f"- Parse warnings: {stats['warnings']}",
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
    adjacency: dict[str, list[tuple[str, str, str]]] = {}
    for edge in document["edges"]:
        adjacency.setdefault(edge["source"], []).append(
            (edge["target"], edge["type"], "outgoing")
        )
        adjacency.setdefault(edge["target"], []).append(
            (edge["source"], edge["type"], "incoming")
        )
    visited = {start["id"]}
    queue: deque[tuple[str, int]] = deque([(start["id"], 0)])
    impact: list[dict[str, Any]] = []
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        for neighbor, relationship, direction in sorted(adjacency.get(current, [])):
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
                    "node": neighbor_node,
                }
            )
            queue.append((neighbor, next_depth))
    impact.sort(key=lambda item: (item["depth"], item["node"]["name"].casefold()))
    return {
        "symbol": symbol,
        "status": "ok",
        "root": start,
        "depth": depth,
        "impact_count": len(impact),
        "impact": impact,
        "interpretation": "Static relationship neighborhood; validate runtime behavior separately.",
    }


def render_visualization(document: dict[str, Any], max_nodes: int) -> str:
    selected_nodes = document["nodes"][:max_nodes]
    selected_ids = {node["id"] for node in selected_nodes}
    selected_edges = [
        edge
        for edge in document["edges"]
        if edge["source"] in selected_ids and edge["target"] in selected_ids
    ]
    payload = json.dumps(
        {"nodes": selected_nodes, "edges": selected_edges},
        ensure_ascii=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    title = html.escape(document["repository"]["name"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Code Ontology — {title}</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #07111f; color: #e8f0ff; overflow: hidden; }}
header {{ position: fixed; inset: 0 0 auto 0; height: 72px; z-index: 2; display: flex;
  align-items: center; gap: 16px; padding: 12px 18px; background: #07111fee;
  border-bottom: 1px solid #23334d; backdrop-filter: blur(10px); }}
h1 {{ font-size: 17px; margin: 0; white-space: nowrap; }}
input {{ width: min(380px, 40vw); padding: 10px 12px; border: 1px solid #345;
  border-radius: 10px; background: #101d31; color: inherit; }}
#summary {{ margin-left: auto; color: #9fb0c9; font-size: 13px; }}
svg {{ position: fixed; inset: 72px 0 0; width: 100vw; height: calc(100vh - 72px); }}
.edge {{ stroke: #466080; stroke-opacity: .42; stroke-width: 1; }}
.node {{ cursor: pointer; }}
.node circle {{ stroke: #d9e8ff; stroke-width: .7; }}
.node text {{ fill: #e8f0ff; font-size: 10px; pointer-events: none; paint-order: stroke;
  stroke: #07111f; stroke-width: 3px; stroke-linejoin: round; }}
.node.dim {{ opacity: .08; }}
#panel {{ position: fixed; z-index: 3; right: 16px; bottom: 16px; width: min(390px, calc(100vw - 32px));
  max-height: 44vh; overflow: auto; padding: 14px; background: #101d31ee; border: 1px solid #345;
  border-radius: 14px; box-shadow: 0 14px 48px #0009; display: none; }}
#panel pre {{ white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; color: #cfe0fb; }}
.legend {{ color: #9fb0c9; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <div><h1>Code Ontology</h1><div class="legend">{title}</div></div>
  <input id="search" type="search" placeholder="Filter by symbol, type, or path" aria-label="Filter nodes">
  <div id="summary"></div>
</header>
<svg id="graph" role="img" aria-label="Interactive code ontology graph"></svg>
<aside id="panel"><strong id="panelTitle"></strong><pre id="panelBody"></pre></aside>
<script>
const data={payload};
const colors={{Java:"#f59e0b",Python:"#38bdf8",Framework:"#a78bfa",Concept:"#34d399"}};
const svg=document.getElementById("graph"), ns="http://www.w3.org/2000/svg";
const width=innerWidth, height=Math.max(500,innerHeight-72), cx=width/2, cy=height/2;
const radius=Math.max(140,Math.min(width,height)*.38);
const positions=new Map();
data.nodes.forEach((node,index)=>{{
  const ring=1+Math.floor(index/80), slot=index%80, total=Math.min(80,data.nodes.length-(ring-1)*80);
  const angle=(slot/Math.max(total,1))*Math.PI*2 + ring*.23;
  const r=Math.min(radius,110+ring*95);
  positions.set(node.id,{{x:cx+Math.cos(angle)*r,y:cy+Math.sin(angle)*r}});
}});
const edgeGroup=document.createElementNS(ns,"g");
data.edges.forEach(edge=>{{
  const a=positions.get(edge.source), b=positions.get(edge.target); if(!a||!b)return;
  const line=document.createElementNS(ns,"line"); line.setAttribute("class","edge");
  line.setAttribute("x1",a.x); line.setAttribute("y1",a.y); line.setAttribute("x2",b.x); line.setAttribute("y2",b.y);
  const tip=document.createElementNS(ns,"title"); tip.textContent=edge.type; line.appendChild(tip); edgeGroup.appendChild(line);
}});
svg.appendChild(edgeGroup);
const nodeGroup=document.createElementNS(ns,"g");
data.nodes.forEach(node=>{{
  const p=positions.get(node.id), g=document.createElementNS(ns,"g"); g.setAttribute("class","node");
  g.setAttribute("transform",`translate(${{p.x}},${{p.y}})`); g.dataset.search=JSON.stringify(node).toLowerCase();
  const circle=document.createElementNS(ns,"circle"); circle.setAttribute("r",node.type.includes("Class")?7:5);
  circle.setAttribute("fill",colors[node.language]||"#fb7185");
  const label=document.createElementNS(ns,"text"); label.setAttribute("x",9); label.setAttribute("y",3); label.textContent=node.name;
  g.append(circle,label); g.addEventListener("click",()=>show(node)); nodeGroup.appendChild(g);
}});
svg.appendChild(nodeGroup);
document.getElementById("summary").textContent=`${{data.nodes.length}} nodes · ${{data.edges.length}} edges`;
document.getElementById("search").addEventListener("input",event=>{{
  const q=event.target.value.toLowerCase().trim();
  nodeGroup.querySelectorAll(".node").forEach(g=>g.classList.toggle("dim",q&&!g.dataset.search.includes(q)));
}});
function show(node){{
  const panel=document.getElementById("panel"); panel.style.display="block";
  document.getElementById("panelTitle").textContent=node.name;
  document.getElementById("panelBody").textContent=JSON.stringify(node,null,2);
}}
addEventListener("resize",()=>location.reload());
</script>
</body>
</html>
"""


def write_visualization(
    index_path: str,
    output_path: str,
    max_nodes: int,
    overwrite: bool = False,
) -> dict[str, Any]:
    index, document = load_document(index_path)
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
    _write_text(output, render_visualization(document, max_nodes))
    return {
        "status": "visualized",
        "index": str(index),
        "output": str(output),
        "nodes_rendered": min(len(document["nodes"]), max_nodes),
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
