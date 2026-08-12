#!/usr/bin/env python3
"""Execute deterministic ontology relation-quality regression cases."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "ontology-quality-cases.json"
ANALYZER_PATH = (
    ROOT
    / "skills"
    / "manage-code-ontology"
    / "scripts"
    / "code_ontology_core.py"
)
ALLOWED_EVIDENCE_BASES = {
    "direct_syntax",
    "resolved_static",
    "framework_semantic",
    "name_heuristic",
}
ALLOWED_RUNTIME_STATUSES = {"not_applicable", "runtime_unknown"}
ALLOWED_ADAPTER_STATUSES = {"supported", "partial", "unsupported"}
MAX_EDGE_EVIDENCE_ITEMS = 16
MAX_EVIDENCE_LIMITATIONS = 16
MAX_EVIDENCE_PATH_LENGTH = 4_096
MAX_EVIDENCE_LINE = 10_000_000
REQUIRED_ADAPTERS = {"Java", "Python"}
RELATIONSHIP = tuple[str, str, str]
NODE = tuple[str, str, str]


class QualityGateError(ValueError):
    """Raised for a malformed corpus or a failed ontology quality gate."""


def _load_analyzer(path: Path = ANALYZER_PATH) -> Any:
    spec = importlib.util.spec_from_file_location("ontology_quality_analyzer", path)
    if spec is None or spec.loader is None:
        raise QualityGateError(f"Could not load bundled analyzer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build_document", None)):
        raise QualityGateError("Bundled analyzer does not expose build_document().")
    return module


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityGateError(f"Quality corpus is unreadable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise QualityGateError("Quality corpus root must be an object.")
    return value


def _triple(value: Any, *, label: str) -> tuple[str, str, str]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise QualityGateError(f"{label} must be a three-string array.")
    return value[0], value[1], value[2]


def validate_corpus(corpus: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the executable corpus and return its ordered cases."""

    if corpus.get("schema_version") != "1.0":
        raise QualityGateError("Unsupported quality corpus schema_version.")
    if corpus.get("quality_contract_version") != "1.0":
        raise QualityGateError("Unsupported quality contract version.")
    partial = corpus.get("partial_relationships")
    if not isinstance(partial, dict):
        raise QualityGateError("partial_relationships must be an object.")
    java_partial = partial.get("Java", {})
    calls_contract = java_partial.get("CALLS") if isinstance(java_partial, dict) else None
    if (
        not isinstance(calls_contract, dict)
        or calls_contract.get("status") != "partial"
        or any(
            not isinstance(calls_contract.get(field), str)
            or not calls_contract[field].strip()
            for field in ("supported", "excluded")
        )
    ):
        raise QualityGateError("Java CALLS must document its partial boundary.")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise QualityGateError("Quality corpus must contain cases.")
    identifiers: set[str] = set()
    saw_java_calls_boundary = False
    for case in cases:
        if not isinstance(case, dict):
            raise QualityGateError("Every quality case must be an object.")
        case_id = case.get("id")
        if (
            not isinstance(case_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case_id)
            or case_id in identifiers
        ):
            raise QualityGateError(f"Invalid or duplicate quality case id: {case_id!r}")
        identifiers.add(case_id)
        if case.get("language") not in REQUIRED_ADAPTERS:
            raise QualityGateError(f"Unsupported case language: {case_id}")
        if not isinstance(case.get("description"), str) or not case["description"].strip():
            raise QualityGateError(f"Case description is missing: {case_id}")
        files = case.get("files")
        if not isinstance(files, dict) or not files:
            raise QualityGateError(f"Case files are missing: {case_id}")
        for relative, content in files.items():
            if (
                not isinstance(relative, str)
                or not relative.endswith((".java", ".py"))
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not isinstance(content, str)
            ):
                raise QualityGateError(f"Unsafe synthetic file in case: {case_id}")
        for field in (
            "required_nodes",
            "forbidden_nodes",
            "required_edges",
            "forbidden_edges",
        ):
            values = case.get(field)
            if not isinstance(values, list):
                raise QualityGateError(f"Case field must be an array: {case_id}.{field}")
            for index, value in enumerate(values):
                _triple(value, label=f"{case_id}.{field}[{index}]")
        boundary = case.get("partial_boundary")
        if boundary is not None:
            if (
                not isinstance(boundary, dict)
                or set(boundary) != {"relation", "supported", "excluded"}
                or any(not isinstance(value, str) or not value for value in boundary.values())
            ):
                raise QualityGateError(f"Malformed partial_boundary entry: {case_id}")
            if case["language"] == "Java" and boundary["relation"] == "CALLS":
                saw_java_calls_boundary = True
    if not saw_java_calls_boundary:
        raise QualityGateError("Corpus must exercise the partial Java CALLS boundary.")
    return cases


def _write_case_repository(root: Path, files: dict[str, str]) -> None:
    for relative in sorted(files):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            files[relative].replace("\r\n", "\n").replace("\r", "\n"),
            encoding="utf-8",
        )


def _node_key(node: dict[str, Any]) -> NODE:
    identity = node.get("qualified_name") or node.get("name")
    return str(node.get("type")), str(identity), str(node.get("language"))


def _node_label(nodes: dict[str, dict[str, Any]], node_id: Any) -> str:
    node = nodes.get(str(node_id), {})
    return str(node.get("qualified_name") or node.get("name") or node_id)


def _edge_key(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> RELATIONSHIP:
    return (
        _node_label(nodes, edge.get("source")),
        _node_label(nodes, edge.get("target")),
        str(edge.get("type")),
    )


def _metric(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
    }


def _portable_evidence_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_EVIDENCE_PATH_LENGTH:
        return False
    if (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    return ".." not in value.replace("\\", "/").split("/")


def validate_evidence_contract(
    document: dict[str, Any], *, require_evidence: bool = True
) -> list[str]:
    """Return deterministic canonical evidence-contract violations."""

    quality = document.get("quality")
    if not isinstance(quality, dict):
        return ["document.quality is missing"] if require_evidence else []
    errors: list[str] = []
    if quality.get("contract_version") != "1.0":
        errors.append("quality.contract_version must equal 1.0")
    relationship = quality.get("relationship_evidence")
    if not isinstance(relationship, dict):
        errors.append("quality.relationship_evidence is missing")
        return errors
    edges = document.get("edges")
    if not isinstance(edges, list):
        return [*errors, "document.edges must be an array"]
    documented = 0
    basis_counts: Counter[str] = Counter()
    runtime_counts: Counter[str] = Counter()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edge[{index}] must be an object")
            continue
        evidence = edge.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            if require_evidence:
                errors.append(f"edge[{index}] has no evidence")
            continue
        if len(evidence) > MAX_EDGE_EVIDENCE_ITEMS:
            errors.append(f"edge[{index}] exceeds the evidence item limit")
        documented += 1
        for evidence_index, item in enumerate(evidence):
            if not isinstance(item, dict):
                errors.append(f"edge[{index}].evidence[{evidence_index}] must be an object")
                continue
            rule_id = item.get("rule_id")
            basis = item.get("basis")
            runtime_status = item.get("runtime_status")
            if not isinstance(rule_id, str) or not re.fullmatch(
                r"[a-z][a-z0-9_.-]{2,79}", rule_id
            ):
                errors.append(f"edge[{index}] has invalid evidence rule_id")
            if basis not in ALLOWED_EVIDENCE_BASES:
                errors.append(f"edge[{index}] has invalid evidence basis")
            else:
                basis_counts[basis] += 1
            if runtime_status not in ALLOWED_RUNTIME_STATUSES:
                errors.append(f"edge[{index}] has invalid runtime_status")
            else:
                runtime_counts[runtime_status] += 1
            path = item.get("path")
            if path is not None and not _portable_evidence_path(path):
                errors.append(f"edge[{index}] has invalid evidence path")
            line_start = item.get("line_start")
            line_end = item.get("line_end")
            if (line_start is None) != (line_end is None):
                errors.append(f"edge[{index}] has incomplete evidence line span")
            elif line_start is not None and (
                isinstance(line_start, bool)
                or isinstance(line_end, bool)
                or not isinstance(line_start, int)
                or not isinstance(line_end, int)
                or not 1 <= line_start <= line_end <= MAX_EVIDENCE_LINE
            ):
                errors.append(f"edge[{index}] has invalid evidence line span")
            limitations = item.get("limitations", [])
            if (
                not isinstance(limitations, list)
                or len(limitations) > MAX_EVIDENCE_LIMITATIONS
                or any(
                    not isinstance(value, str)
                    or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", value)
                    for value in limitations
                )
            ):
                errors.append(f"edge[{index}] has invalid evidence limitations")
            if runtime_status == "runtime_unknown" and not limitations:
                errors.append(f"edge[{index}] runtime_unknown lacks a limitation")
    expected_missing = len(edges) - documented
    source_span_edges = sum(
        isinstance(edge, dict)
        and isinstance(edge.get("evidence"), list)
        and any(
            isinstance(item, dict)
            and _portable_evidence_path(item.get("path"))
            and isinstance(item.get("line_start"), int)
            for item in edge["evidence"]
        )
        for edge in edges
    )
    expected_coverage = round((documented * 100.0 / len(edges)) if edges else 100.0, 3)
    expected_span_coverage = round(
        (source_span_edges * 100.0 / len(edges)) if edges else 100.0,
        3,
    )
    expected_summary = {
        "total_edges": len(edges),
        "documented_edges": documented,
        "missing_evidence": expected_missing,
        "coverage_percent": expected_coverage,
        "source_span_edges": source_span_edges,
        "source_span_coverage_percent": expected_span_coverage,
        "basis_counts": dict(sorted(basis_counts.items())),
        "runtime_status_counts": dict(sorted(runtime_counts.items())),
    }
    for field, expected in expected_summary.items():
        actual = relationship.get(field)
        if isinstance(expected, float):
            if not isinstance(actual, (int, float)) or not math.isclose(
                float(actual), expected, abs_tol=0.001
            ):
                errors.append(f"relationship_evidence.{field} does not match edges")
        elif actual != expected:
            errors.append(f"relationship_evidence.{field} does not match edges")
    if require_evidence and relationship.get("missing_evidence") != 0:
        errors.append("relationship_evidence.missing_evidence must equal 0")
    adapters = quality.get("adapters")
    if not isinstance(adapters, dict):
        errors.append("quality.adapters is missing")
    else:
        for language in sorted(REQUIRED_ADAPTERS):
            adapter = adapters.get(language)
            if not isinstance(adapter, dict):
                errors.append(f"quality.adapters.{language} is missing")
                continue
            if adapter.get("status") not in ALLOWED_ADAPTER_STATUSES:
                errors.append(f"quality.adapters.{language}.status is invalid")
            if not isinstance(adapter.get("detected"), bool):
                errors.append(f"quality.adapters.{language}.detected is invalid")
            capabilities = adapter.get("capabilities")
            if (
                not isinstance(capabilities, dict)
                or not capabilities
                or any(
                    not isinstance(name, str)
                    or not name
                    or status not in ALLOWED_ADAPTER_STATUSES
                    for name, status in capabilities.items()
                )
            ):
                errors.append(f"quality.adapters.{language}.capabilities is invalid")
            unsupported_runtime = adapter.get("unsupported_runtime")
            if (
                not isinstance(unsupported_runtime, list)
                or not unsupported_runtime
                or any(
                    not isinstance(value, str)
                    or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", value)
                    for value in unsupported_runtime
                )
            ):
                errors.append(
                    f"quality.adapters.{language}.unsupported_runtime is invalid"
                )
    return sorted(set(errors))


def _evaluate_case(
    analyzer: Any, case: dict[str, Any], *, require_evidence: bool
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"ontology-quality-{case['id']}-") as raw:
        repository = Path(raw) / "repository"
        repository.mkdir()
        _write_case_repository(repository, case["files"])
        document = analyzer.build_document(repository)
    nodes_by_id = {
        str(item.get("id")): item
        for item in document.get("nodes", [])
        if isinstance(item, dict)
    }
    actual_nodes = {_node_key(item) for item in nodes_by_id.values()}
    actual_edges = {
        _edge_key(item, nodes_by_id)
        for item in document.get("edges", [])
        if isinstance(item, dict)
    }
    required_nodes = {
        _triple(item, label=f"{case['id']}.required_nodes")
        for item in case["required_nodes"]
    }
    forbidden_nodes = {
        _triple(item, label=f"{case['id']}.forbidden_nodes")
        for item in case["forbidden_nodes"]
    }
    required_edges = {
        _triple(item, label=f"{case['id']}.required_edges")
        for item in case["required_edges"]
    }
    forbidden_edges = {
        _triple(item, label=f"{case['id']}.forbidden_edges")
        for item in case["forbidden_edges"]
    }
    missing_nodes = sorted(required_nodes - actual_nodes)
    forbidden_nodes_found = sorted(forbidden_nodes & actual_nodes)
    missing_edges = sorted(required_edges - actual_edges)
    forbidden_edges_found = sorted(forbidden_edges & actual_edges)
    relation_metrics: dict[str, dict[str, Any]] = {}
    for relation in sorted({item[2] for item in required_edges | forbidden_edges}):
        required = {item for item in required_edges if item[2] == relation}
        forbidden = {item for item in forbidden_edges if item[2] == relation}
        relation_metrics[relation] = _metric(
            len(required & actual_edges),
            len(forbidden & actual_edges),
            len(required - actual_edges),
        )
    evidence_errors = validate_evidence_contract(
        document, require_evidence=require_evidence
    )
    return {
        "id": case["id"],
        "language": case["language"],
        "passed": not any(
            (
                missing_nodes,
                forbidden_nodes_found,
                missing_edges,
                forbidden_edges_found,
                evidence_errors,
            )
        ),
        "metrics": _metric(
            len(required_edges & actual_edges),
            len(forbidden_edges & actual_edges),
            len(required_edges - actual_edges),
        ),
        "relations": relation_metrics,
        "missing_required_nodes": [list(item) for item in missing_nodes],
        "forbidden_nodes_found": [list(item) for item in forbidden_nodes_found],
        "missing_required_edges": [list(item) for item in missing_edges],
        "forbidden_edges_found": [list(item) for item in forbidden_edges_found],
        "evidence_errors": evidence_errors,
        "partial_boundary": case.get("partial_boundary"),
    }


def evaluate(
    corpus: dict[str, Any], *, require_evidence: bool = True, analyzer: Any | None = None
) -> dict[str, Any]:
    """Run every quality case and return stable aggregate JSON."""

    cases = validate_corpus(corpus)
    analyzer = analyzer or _load_analyzer()
    case_results = [
        _evaluate_case(analyzer, case, require_evidence=require_evidence)
        for case in cases
    ]
    language_counts: dict[str, list[int]] = {}
    relation_counts: dict[str, list[int]] = {}
    for result in case_results:
        language_counts.setdefault(result["language"], [0, 0, 0])
        language_counts[result["language"]][0] += result["metrics"]["tp"]
        language_counts[result["language"]][1] += result["metrics"]["fp"]
        language_counts[result["language"]][2] += result["metrics"]["fn"]
        for relation, metric in result["relations"].items():
            relation_counts.setdefault(relation, [0, 0, 0])
            relation_counts[relation][0] += metric["tp"]
            relation_counts[relation][1] += metric["fp"]
            relation_counts[relation][2] += metric["fn"]
    return {
        "status": "pass" if all(item["passed"] for item in case_results) else "fail",
        "schema_version": corpus["schema_version"],
        "quality_contract_version": corpus["quality_contract_version"],
        "evidence_required": require_evidence,
        "case_count": len(case_results),
        "languages": {
            key: _metric(*language_counts[key]) for key in sorted(language_counts)
        },
        "relations": {
            key: _metric(*relation_counts[key]) for key in sorted(relation_counts)
        },
        "cases": case_results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--allow-missing-evidence",
        action="store_true",
        help=(
            "Temporary integration escape hatch for analyzers without document.quality; "
            "the default requires canonical 100-percent relationship evidence."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = evaluate(
            _read_json(arguments.cases),
            require_evidence=not arguments.allow_missing_evidence,
        )
    except (OSError, QualityGateError) as exc:
        result = {"status": "error", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
