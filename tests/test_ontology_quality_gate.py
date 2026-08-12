from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_ontology_quality.py"
CASES_PATH = ROOT / "evals" / "ontology-quality-cases.json"

SPEC = importlib.util.spec_from_file_location("validate_ontology_quality", VALIDATOR_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class OntologyQualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_corpus_executes_with_per_language_and_relation_metrics(self) -> None:
        result = validator.evaluate(self.corpus)

        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["case_count"], 4)
        self.assertEqual(set(result["languages"]), {"Java", "Python"})
        self.assertIn("CALLS", result["relations"])
        self.assertIn("INJECTS", result["relations"])
        self.assertIn("HAS_PIPELINE_ROLE", result["relations"])
        for group in (result["languages"], result["relations"]):
            for metric in group.values():
                self.assertEqual(metric["fp"], 0)
                self.assertEqual(metric["fn"], 0)
                self.assertEqual(metric["precision"], 1.0)
                self.assertEqual(metric["recall"], 1.0)
        java_calls = next(
            case
            for case in result["cases"]
            if case["id"] == "java-bean-and-calls-boundary"
        )
        self.assertEqual(java_calls["partial_boundary"]["relation"], "CALLS")
        self.assertIn("Dynamic receiver", java_calls["partial_boundary"]["excluded"])

    def test_missing_required_and_forbidden_critical_edges_fail(self) -> None:
        missing = copy.deepcopy(self.corpus)
        missing["cases"] = [copy.deepcopy(self.corpus["cases"][2])]
        missing["cases"][0]["required_edges"].append(
            ["pkg.pipeline.normalize_orders", "does.not.exist", "CALLS"]
        )
        missing["cases"][0]["partial_boundary"] = {
            "relation": "CALLS",
            "supported": "Synthetic same-owner boundary fixture.",
            "excluded": "Synthetic dynamic receiver boundary fixture."
        }
        missing["cases"][0]["language"] = "Java"
        result = validator.evaluate(missing)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["relations"]["CALLS"]["fn"], 1)

        forbidden = copy.deepcopy(self.corpus)
        forbidden["cases"][2]["forbidden_edges"].append(
            ["pkg.pipeline.normalize_orders", "pkg.helpers.fetch_orders", "CALLS"]
        )
        result = validator.evaluate(forbidden)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["relations"]["CALLS"]["fp"], 1)

    def test_evidence_default_is_strict_and_escape_hatch_is_explicit(self) -> None:
        document = {
            "statistics": {"source_files": {"Python": 1}},
            "nodes": [],
            "edges": [{"source": "a", "target": "b", "type": "CALLS"}],
        }
        strict = validator.validate_evidence_contract(document, require_evidence=True)
        permissive = validator.validate_evidence_contract(document, require_evidence=False)
        self.assertIn("document.quality is missing", strict)
        self.assertEqual(permissive, [])

    def test_evidence_summary_and_allowed_enums_are_reconciled(self) -> None:
        document = {
            "statistics": {"source_files": {"Python": 1}},
            "nodes": [],
            "edges": [
                {
                    "source": "a",
                    "target": "b",
                    "type": "CALLS",
                    "evidence": [
                        {
                            "rule_id": "python.call.test",
                            "basis": "resolved_static",
                            "runtime_status": "not_applicable",
                        }
                    ],
                }
            ],
            "quality": {
                "contract_version": "1.0",
                "relationship_evidence": {
                    "total_edges": 1,
                    "documented_edges": 1,
                    "missing_evidence": 0,
                    "coverage_percent": 100.0,
                    "source_span_edges": 0,
                    "source_span_coverage_percent": 0.0,
                    "basis_counts": {"resolved_static": 1},
                    "runtime_status_counts": {"not_applicable": 1},
                },
                "adapters": {
                    "Java": {
                        "status": "partial",
                        "detected": False,
                        "capabilities": {"calls": "partial"},
                        "unsupported_runtime": ["runtime_dispatch"],
                    },
                    "Python": {
                        "status": "partial",
                        "detected": True,
                        "capabilities": {"calls": "partial"},
                        "unsupported_runtime": ["runtime_dispatch"],
                    }
                },
            },
        }
        self.assertEqual(validator.validate_evidence_contract(document), [])
        document["edges"][0]["evidence"][0]["basis"] = "model_guess"
        errors = validator.validate_evidence_contract(document)
        self.assertTrue(any("invalid evidence basis" in item for item in errors))

    def test_evidence_and_adapter_bounds_are_release_gates(self) -> None:
        evidence_count = validator.MAX_EDGE_EVIDENCE_ITEMS + 1
        document = {
            "statistics": {"source_files": {"Python": 1}},
            "nodes": [],
            "edges": [
                {
                    "source": "a",
                    "target": "b",
                    "type": "CALLS",
                    "evidence": [
                        {
                            "rule_id": f"python.call.rule{index}",
                            "basis": "resolved_static",
                            "runtime_status": "not_applicable",
                            "path": "/private/source.py",
                            "line_start": 0,
                            "line_end": validator.MAX_EVIDENCE_LINE + 1,
                            "limitations": [
                                f"python.limit{item}"
                                for item in range(validator.MAX_EVIDENCE_LIMITATIONS + 1)
                            ],
                        }
                        for index in range(evidence_count)
                    ],
                }
            ],
            "quality": {
                "contract_version": "1.0",
                "relationship_evidence": {
                    "total_edges": 1,
                    "documented_edges": 1,
                    "missing_evidence": 0,
                    "coverage_percent": 100.0,
                    "source_span_edges": 0,
                    "source_span_coverage_percent": 0.0,
                    "basis_counts": {"resolved_static": evidence_count},
                    "runtime_status_counts": {"not_applicable": evidence_count},
                },
                "adapters": {
                    "Java": {
                        "status": "partial",
                        "detected": False,
                        "capabilities": {"calls": "partial"},
                        "unsupported_runtime": ["runtime_dispatch"],
                    },
                    "Python": {"status": "partial", "detected": True},
                },
            },
        }
        errors = validator.validate_evidence_contract(document)
        for marker in (
            "evidence item limit",
            "invalid evidence path",
            "invalid evidence line span",
            "invalid evidence limitations",
            "capabilities is invalid",
            "unsupported_runtime is invalid",
        ):
            self.assertTrue(any(marker in error for error in errors), (marker, errors))

    def test_cli_emits_deterministic_json_and_passes(self) -> None:
        command = [sys.executable, str(VALIDATOR_PATH)]
        first = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        second = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(json.loads(first.stdout)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
