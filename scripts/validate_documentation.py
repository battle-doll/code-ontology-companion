#!/usr/bin/env python3
"""Validate multilingual, human-readable documentation parity."""

from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("ko", "ja", "zh-CN")
README_LOCALES = (*LOCALES, "ru")
ALL_LOCALES = README_LOCALES
LANGUAGE_NAVIGATION_TOKENS = ("English", "한국어", "日本語", "简体中文")
README_LANGUAGE_NAVIGATION_TOKENS = (*LANGUAGE_NAVIGATION_TOKENS, "Русский")
README_LANGUAGE_NAVIGATION = (
    "[English](README.md) | [한국어](README.ko.md) | "
    "[日本語](README.ja.md) | [简体中文](README.zh-CN.md) | "
    "[Русский](README.ru.md)"
)
README_PARITY_TOKENS = (
    "Java/Spring",
    "Python",
    "Python 3.9",
    "RDF 1.1",
    "PROV-O",
    "MCP",
    "Ollama",
    "127.0.0.1:11434",
    "--authorized",
    "graph.html",
    "ontology.json",
    "ontology.ttl",
    "inferred",
    "runtime_unknown",
    "RelationshipEvidence",
    "Apache-2.0",
)
LEGAL_TRANSLATION_MARKER = "<!-- informational-translation; english-authoritative -->"

ROOT_DOCUMENTS = (
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "PRIVACY.md",
    "SECURITY.md",
    "SUBMISSION.md",
    "SUPPORT.md",
    "TERMS.md",
    "THREAT_MODEL.md",
    "TRADEMARKS.md",
    "THIRD_PARTY_NOTICES.md",
    "NOTICE",
)
REFERENCE_DOCUMENTS = (
    "data-boundaries.md",
    "lineage-model.md",
    "local-llm.md",
    "local-mcp.md",
    "ontology-model.md",
)
LEGAL_DOCUMENTS = (
    "PRIVACY.md",
    "TERMS.md",
    "TRADEMARKS.md",
    "THIRD_PARTY_NOTICES.md",
    "NOTICE",
)
VENDOR_LICENSE_STEMS = (
    "cytoscape-mit",
    "elkjs-epl-2.0",
    "web-worker-apache-2.0",
)


class DocumentationValidationError(ValueError):
    """Raised when the multilingual documentation set is not publishable."""


def _fail(message: str) -> None:
    raise DocumentationValidationError(message)


def document_families() -> tuple[tuple[str, str], ...]:
    """Return English source paths and their locale-path templates."""

    families: list[tuple[str, str]] = [
        ("docs/README.md", "docs/{locale}/README.md"),
    ]
    families.extend(
        (
            relative,
            f"docs/{{locale}}/{'NOTICE.md' if relative == 'NOTICE' else Path(relative).name}",
        )
        for relative in ROOT_DOCUMENTS
    )
    families.extend(
        (
            (
                "docs/ARCHITECTURE_AND_ROADMAP.md",
                "docs/{locale}/ARCHITECTURE_AND_ROADMAP.md",
            ),
            (
                "skills/manage-code-ontology/SKILL.md",
                "docs/{locale}/SKILL_GUIDE.md",
            ),
        )
    )
    families.extend(
        (
            f"skills/manage-code-ontology/references/{name}",
            f"docs/{{locale}}/references/{name}",
        )
        for name in REFERENCE_DOCUMENTS
    )
    return tuple(families)


def expected_document_paths() -> tuple[str, ...]:
    """Return every English and localized human-readable document path."""

    paths: list[str] = list(root_readme_paths())
    for english_path, localized_template in document_families():
        paths.append(english_path)
        paths.extend(localized_template.format(locale=locale) for locale in LOCALES)
    if len(paths) != len(set(paths)):
        _fail("Internal documentation map contains duplicate paths.")
    return tuple(paths)


def root_readme_paths() -> tuple[str, ...]:
    """Return the canonical README and its complete root-level translations."""

    return ("README.md", *(f"README.{locale}.md" for locale in README_LOCALES))


def legal_translation_paths() -> tuple[str, ...]:
    """Return policy translations that must disclaim English authority."""

    return tuple(
        f"docs/{locale}/{'NOTICE.md' if name == 'NOTICE' else name}"
        for locale in LOCALES
        for name in LEGAL_DOCUMENTS
    )


def _read_regular_utf8(root: Path, relative: str) -> str:
    path = root / relative
    current = root
    for component in Path(relative).parts[:-1]:
        current /= component
        try:
            component_metadata = current.lstat()
        except FileNotFoundError:
            _fail(f"Missing documentation file: {relative}")
        except OSError as exc:
            _fail(f"Documentation path cannot be inspected: {relative}: {exc}")
        if stat.S_ISLNK(component_metadata.st_mode):
            _fail(
                "Documentation path must not traverse a symlink: "
                f"{relative}: {current.relative_to(root).as_posix()}"
            )
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        _fail(f"Missing documentation file: {relative}")
    except OSError as exc:
        _fail(f"Documentation file cannot be inspected: {relative}: {exc}")
    if not stat.S_ISREG(metadata.st_mode):
        _fail(f"Documentation must be a regular non-symlink file: {relative}")
    try:
        content = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail(f"Documentation must be valid UTF-8: {relative}: {exc}")
    except OSError as exc:
        _fail(f"Documentation file cannot be read: {relative}: {exc}")
    if not content.strip():
        _fail(f"Documentation must not be empty: {relative}")
    return content


def _has_locale_marker(relative: str) -> bool:
    return any(
        re.search(
            rf"(?:^|[./_-]){re.escape(locale)}(?:$|[./_-])",
            relative,
            flags=re.IGNORECASE,
        )
        for locale in ALL_LOCALES
    )


def _validate_no_license_translations(root: Path) -> None:
    ignored_parts = {".git", "dist", "__pycache__"}
    try:
        entries = root.rglob("*")
        for path in entries:
            relative_path = path.relative_to(root)
            if any(part in ignored_parts for part in relative_path.parts):
                continue
            relative = relative_path.as_posix()
            if not _has_locale_marker(relative):
                continue
            name = path.name.casefold()
            is_primary_license = bool(re.match(r"^license(?:[._-]|$)", name))
            is_vendor_license = any(stem in name for stem in VENDOR_LICENSE_STEMS)
            if is_primary_license or is_vendor_license:
                _fail(f"License translations are forbidden: {relative}")
    except OSError as exc:
        _fail(f"Documentation tree cannot be inspected for license translations: {exc}")


def validate_documentation(root: Path = ROOT) -> int:
    """Validate documentation presence, encoding, navigation, and legal markers."""

    root = Path(root)
    documents: dict[str, str] = {}
    readme_paths = set(root_readme_paths())
    for relative in expected_document_paths():
        content = _read_regular_utf8(root, relative)
        navigation_tokens = (
            README_LANGUAGE_NAVIGATION_TOKENS
            if relative in readme_paths
            else LANGUAGE_NAVIGATION_TOKENS
        )
        missing_tokens = [
            token for token in navigation_tokens if token not in content
        ]
        if missing_tokens:
            _fail(
                f"Documentation language navigation is incomplete: {relative}: "
                f"missing {', '.join(missing_tokens)}"
            )
        if relative in readme_paths:
            if README_LANGUAGE_NAVIGATION not in content:
                _fail(
                    "README language navigation must use the canonical five-language "
                    f"switcher: {relative}"
                )
            missing_parity = [
                token for token in README_PARITY_TOKENS if token not in content
            ]
            if missing_parity:
                _fail(
                    f"README capability parity is incomplete: {relative}: "
                    f"missing {', '.join(missing_parity)}"
                )
        documents[relative] = content

    canonical_fence_count = documents["README.md"].count("```")
    canonical_heading_count = len(
        re.findall(r"^#{1,3} ", documents["README.md"], flags=re.MULTILINE)
    )
    for relative in readme_paths:
        if documents[relative].count("```") != canonical_fence_count:
            _fail(
                "README command-example parity is incomplete: "
                f"{relative}: expected {canonical_fence_count} code fences"
            )
        heading_count = len(
            re.findall(r"^#{1,3} ", documents[relative], flags=re.MULTILINE)
        )
        if heading_count != canonical_heading_count:
            _fail(
                "README section parity is incomplete: "
                f"{relative}: expected {canonical_heading_count} headings"
            )

    for relative in legal_translation_paths():
        if LEGAL_TRANSLATION_MARKER not in documents[relative]:
            _fail(
                "Legal translation must declare the English source authoritative: "
                f"{relative}: missing {LEGAL_TRANSLATION_MARKER}"
            )

    _validate_no_license_translations(root)
    return len(documents)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate multilingual human-readable documentation parity."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root to validate (defaults to this checkout).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        count = validate_documentation(arguments.root)
    except DocumentationValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"PASS: {count} English/Korean/Japanese/Simplified-Chinese "
        "documentation files plus the Russian root README validated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
