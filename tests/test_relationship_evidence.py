from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "manage-code-ontology" / "scripts" / "code_ontology_core.py"

SPEC = importlib.util.spec_from_file_location("code_ontology_quality", SCRIPT)
assert SPEC and SPEC.loader
code_ontology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(code_ontology)


class RelationshipEvidenceTests(unittest.TestCase):
    def test_evidence_is_bounded_canonical_and_rejects_absolute_path_variants(self) -> None:
        graph = code_ontology.Graph("fixture")
        graph.add_node("source", "Method", "source", "Java", path="safe/Source.java")
        graph.add_node("target", "Method", "target", "Java", path="safe/Target.java")
        for index in reversed(range(code_ontology.MAX_EDGE_EVIDENCE_ITEMS + 20)):
            graph.add_edge(
                "source",
                "target",
                "CALLS",
                rule_id=f"java.call.rule{index:02d}",
                path="safe/Source.java",
                limitations=(f"java.limit{index:02d}",),
            )

        document = graph.document(Counter({"Java": 1}), Counter())
        evidence = document["edges"][0]["evidence"]
        self.assertEqual(code_ontology.MAX_EDGE_EVIDENCE_ITEMS, len(evidence))
        self.assertEqual(
            sorted(evidence, key=code_ontology._edge_evidence_key),
            evidence,
        )
        for unsafe in (
            "/Users/private/Source.java",
            "\\Users\\private\\Source.java",
            "\\\\server\\share\\Source.java",
            "C:\\private\\Source.java",
            "safe/../private/Source.java",
        ):
            self.assertFalse(code_ontology._portable_relative_path(unsafe), unsafe)

    def _document(self) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "Service.java").write_text(
                """package demo;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
@Service class Worker {
    @Transactional void run() { helper(); }
    void helper() {}
}
""",
                encoding="utf-8",
            )
            (repo / "pipeline.py").write_text(
                """from util import fetch
def transform_orders():
    return fetch()
""",
                encoding="utf-8",
            )
            return code_ontology.build_document(repo)

    def test_every_analyzer_edge_has_bounded_explainable_evidence(self) -> None:
        document = self._document()
        self.assertTrue(document["edges"])
        allowed_basis = {
            "direct_syntax",
            "resolved_static",
            "framework_semantic",
            "name_heuristic",
        }
        allowed_runtime = {"not_applicable", "runtime_unknown"}

        for edge in document["edges"]:
            with self.subTest(edge=(edge["source"], edge["target"], edge["type"])):
                evidence = edge.get("evidence")
                self.assertIsInstance(evidence, list)
                self.assertGreater(len(evidence), 0)
                for item in evidence:
                    self.assertRegex(item["rule_id"], r"^[a-z][a-z0-9_.-]{2,79}$")
                    self.assertIn(item["basis"], allowed_basis)
                    self.assertIn(item["runtime_status"], allowed_runtime)
                    if "path" in item:
                        self.assertFalse(Path(item["path"]).is_absolute())
                        self.assertNotIn("..", item["path"].replace("\\", "/").split("/"))
                    if "line_start" in item:
                        self.assertGreaterEqual(item["line_start"], 1)
                        self.assertGreaterEqual(item["line_end"], item["line_start"])

    def test_quality_manifest_reports_coverage_and_unsupported_runtime(self) -> None:
        document = self._document()
        quality = document["quality"]
        self.assertEqual(quality["contract_version"], "1.0")
        relationship = quality["relationship_evidence"]
        self.assertEqual(relationship["total_edges"], len(document["edges"]))
        self.assertEqual(relationship["documented_edges"], len(document["edges"]))
        self.assertEqual(relationship["missing_evidence"], 0)
        self.assertEqual(relationship["coverage_percent"], 100.0)
        self.assertEqual(set(quality["adapters"]), {"Java", "Python"})
        self.assertTrue(quality["adapters"]["Java"]["detected"])
        self.assertTrue(quality["adapters"]["Python"]["detected"])
        self.assertEqual(quality["adapters"]["Java"]["status"], "partial")
        self.assertEqual(quality["adapters"]["Python"]["status"], "partial")
        self.assertEqual(quality["adapters"]["Java"]["capabilities"]["imports"], "partial")
        self.assertEqual(
            quality["adapters"]["Java"]["capabilities"]["explicit_type_imports"],
            "supported",
        )
        self.assertEqual(
            quality["adapters"]["Python"]["capabilities"]["decorators"],
            "partial",
        )
        self.assertIn("runtime_dispatch", quality["adapters"]["Java"]["capabilities"])
        self.assertEqual(
            quality["adapters"]["Java"]["capabilities"]["runtime_dispatch"],
            "unsupported",
        )

        runtime_sensitive = [
            edge
            for edge in document["edges"]
            if edge["type"] in {"MANAGED_AS", "MAY_BE_PROXIED_BY", "INJECTS"}
        ]
        self.assertTrue(runtime_sensitive)
        for edge in runtime_sensitive:
            self.assertTrue(
                all(item["runtime_status"] == "runtime_unknown" for item in edge["evidence"])
            )

    def test_adapter_matrix_marks_languages_not_present_in_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "only_python.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            quality = code_ontology.build_document(repo)["quality"]
        self.assertEqual(set(quality["adapters"]), {"Java", "Python"})
        self.assertFalse(quality["adapters"]["Java"]["detected"])
        self.assertTrue(quality["adapters"]["Python"]["detected"])

    def test_rule_and_basis_are_exported_without_replacing_legacy_triples(self) -> None:
        document = self._document()
        turtle = code_ontology.render_turtle(document)
        self.assertIn("co:RelationshipEvidence", turtle)
        self.assertIn("rdf:Statement", turtle)
        self.assertIn("co:evidencePath", turtle)
        self.assertIn("co:ruleId", turtle)
        self.assertIn("co:evidenceBasis", turtle)
        self.assertIn("co:detected", turtle)
        self.assertIn("co:capability", turtle)
        for edge in document["edges"]:
            predicate = re.sub(r"[^A-Za-z0-9]", "", edge["type"].title())
            legacy = (
                f"{code_ontology._turtle_uri(edge['source'])} co:{predicate} "
                f"{code_ontology._turtle_uri(edge['target'])} ."
            )
            self.assertIn(legacy, turtle)

        report = code_ontology.render_report(document)
        self.assertIn("Java adapter: `partial` (detected: `yes`)", report)
        self.assertIn("`explicit_type_imports`: `supported`", report)
        self.assertIn("Unsupported runtime evidence", report)

    def test_rdf_quality_resources_are_graph_scoped(self) -> None:
        first = self._document()
        second = json.loads(json.dumps(first))
        second["edges"] = second["edges"][:-1]
        first_turtle = code_ontology.render_turtle(first)
        second_turtle = code_ontology.render_turtle(second)
        pattern = re.compile(r"urn:code-ontology:quality:[0-9a-f]{64}")
        first_uri = pattern.search(first_turtle)
        second_uri = pattern.search(second_turtle)
        self.assertIsNotNone(first_uri)
        self.assertIsNotNone(second_uri)
        self.assertNotEqual(first_uri.group(0), second_uri.group(0))

    def test_workbench_payload_keeps_sanitized_quality_and_edge_evidence(self) -> None:
        document = self._document()
        page = code_ontology.render_visualization(document, 100)
        match = re.search(
            r'<script id="ontology-data" type="application/json">(.*?)</script>',
            page,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertEqual(payload["quality"]["contract_version"], "1.0")
        self.assertTrue(any(edge.get("evidence") for edge in payload["edges"]))
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn("@Service class Worker", serialized)


if __name__ == "__main__":
    unittest.main()
