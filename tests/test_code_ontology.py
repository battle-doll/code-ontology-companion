from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "manage-code-ontology" / "scripts" / "code_ontology_core.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample-app"

SPEC = importlib.util.spec_from_file_location("code_ontology_core", SCRIPT)
assert SPEC and SPEC.loader
code_ontology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(code_ontology)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CodeOntologyTests(unittest.TestCase):
    def test_preflight_is_read_only_and_excludes_secret_like_file(self) -> None:
        before = tree_digest(FIXTURE)
        result = code_ontology.preflight_document(FIXTURE.resolve())
        after = tree_digest(FIXTURE)

        self.assertEqual(before, after)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["source_file_count"], 5)
        self.assertEqual(result["supported_languages"], {"Java": 4, "Python": 1})
        self.assertGreaterEqual(result["skipped"]["sensitive_name"], 1)
        self.assertFalse(result["limits"]["network_access"])
        self.assertFalse(result["limits"]["executes_source"])

    def test_index_requires_authorization_and_external_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "ontology"
            with self.assertRaises(code_ontology.OntologyError):
                code_ontology.write_index(FIXTURE.resolve(), external, authorized=False)

        with self.assertRaises(code_ontology.OntologyError):
            code_ontology.write_index(
                FIXTURE.resolve(),
                FIXTURE / "generated-ontology",
                authorized=True,
            )

    def test_java_spring_and_python_pipeline_are_mapped(self) -> None:
        document = code_ontology.build_document(FIXTURE.resolve())
        node_names = {node["name"] for node in document["nodes"]}
        edge_types = {edge["type"] for edge in document["edges"]}

        self.assertIn("OrderService", node_names)
        self.assertIn("@Service", node_names)
        self.assertIn("@Transactional", node_names)
        self.assertIn("@Aspect", node_names)
        self.assertIn("Extract", node_names)
        self.assertIn("Transform", node_names)
        self.assertIn("Load", node_names)
        self.assertIn("INJECTS", edge_types)
        self.assertIn("MAY_BE_PROXIED_BY", edge_types)
        self.assertIn("HAS_PIPELINE_ROLE", edge_types)
        self.assertFalse(document["privacy"]["contains_source_text"])
        payment_types = [
            node
            for node in document["nodes"]
            if node.get("qualified_name") == "com.example.demo.PaymentClient"
        ]
        self.assertEqual(len(payment_types), 1)
        self.assertEqual(payment_types[0]["type"], "Interface")

    def test_artifacts_are_portable_and_contain_no_source_literals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ontology"
            result = code_ontology.write_index(
                FIXTURE.resolve(),
                output,
                authorized=True,
            )
            self.assertEqual(result["status"], "indexed")
            for name in ("ontology.json", "ontology.ttl", "report.md"):
                self.assertTrue((output / name).is_file())

            serialized = (output / "ontology.json").read_text(encoding="utf-8")
            turtle = (output / "ontology.ttl").read_text(encoding="utf-8")
            self.assertNotIn("this file must never be read", serialized)
            self.assertNotIn("execution(* com.example.demo", serialized)
            self.assertNotIn(str(FIXTURE.resolve()), serialized)
            self.assertIn("@prefix rdf:", turtle)
            self.assertIn("urn:code-ontology:node:", turtle)
            with self.assertRaises(code_ontology.OntologyError):
                code_ontology.write_index(FIXTURE.resolve(), output, authorized=True)

    def test_query_impact_and_offline_visualization(self) -> None:
        document = code_ontology.build_document(FIXTURE.resolve())
        query = code_ontology.query_document(document, "OrderService", 20)
        self.assertGreater(query["match_count"], 0)

        impact = code_ontology.impact_document(document, "OrderService", 2)
        self.assertEqual(impact["status"], "ok")
        self.assertGreater(impact["impact_count"], 0)

        page = code_ontology.render_visualization(document, 500)
        self.assertIn("<!doctype html>", page)
        self.assertNotIn("https://cdn.", page)
        self.assertNotIn("<script src=", page)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            index = directory / "ontology.json"
            index.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(code_ontology.OntologyError):
                code_ontology.write_visualization(
                    str(index),
                    str(directory.parent / "outside.html"),
                    500,
                )

    def test_impact_reports_multiple_exact_names_as_ambiguous(self) -> None:
        document = {
            "schema_version": "1.0",
            "nodes": [
                {"id": "one", "type": "Class", "name": "Shared", "language": "Java"},
                {"id": "two", "type": "Class", "name": "Shared", "language": "Python"},
            ],
            "edges": [],
        }
        result = code_ontology.impact_document(document, "Shared", 2)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)

    def test_token_and_key_named_sources_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "safe.py").write_text("VALUE = 1\n", encoding="utf-8")
            (repo / "access_token.py").write_text("TOKEN = 'hidden'\n", encoding="utf-8")
            (repo / "api_key.java").write_text("class Key {}\n", encoding="utf-8")
            sources, skipped = code_ontology.discover_sources(repo)
            self.assertEqual([path.name for path in sources], ["safe.py"])
            self.assertEqual(skipped["sensitive_name"], 2)

    def test_reparse_points_are_treated_as_links(self) -> None:
        file_stat = SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        self.assertTrue(code_ontology._is_link_like(file_stat))

    def test_read_errors_do_not_embed_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "vanished.py"
            with self.assertRaises(code_ontology.OntologyError) as caught:
                code_ontology._safe_read(missing)
            self.assertNotIn(str(Path(temporary)), str(caught.exception))
            self.assertIn("vanished.py", str(caught.exception))

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_repository_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            actual = base / "actual"
            actual.mkdir()
            linked = base / "linked"
            linked.symlink_to(actual, target_is_directory=True)
            with self.assertRaises(code_ontology.OntologyError):
                code_ontology._resolve_dir(str(linked), "Repository")

    def test_multiple_java_types_interface_methods_and_bean_graph_integrity(self) -> None:
        source = """package demo;
class First {
    public void one() {}
}
class Second {
    void two() {}
}
interface Port {
    Result call(Input input);
}
class Factory {
    @Bean
    Thing thing() { return null; }
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "Types.java").write_text(source, encoding="utf-8")
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        first = next(node for node in nodes.values() if node.get("qualified_name") == "demo.First")
        second = next(node for node in nodes.values() if node.get("qualified_name") == "demo.Second")
        port = next(node for node in nodes.values() if node.get("qualified_name") == "demo.Port")
        one = next(node for node in nodes.values() if node["name"] == "one")
        two = next(node for node in nodes.values() if node["name"] == "two")
        call = next(node for node in nodes.values() if node["name"] == "call")
        self.assertIn((first["id"], one["id"], "DECLARES"), edges)
        self.assertIn((second["id"], two["id"], "DECLARES"), edges)
        self.assertIn((port["id"], call["id"], "DECLARES"), edges)
        self.assertIn("framework:spring:bean", nodes)
        for source_id, target_id, _ in edges:
            self.assertIn(source_id, nodes)
            self.assertIn(target_id, nodes)

    def test_java_policy_leaf_requires_a_real_control_flow_use(self) -> None:
        source = """package demo;
class RuntimePolicy {
    Object evaluate(Object policy) {
        Integer timeStopMinutes = this.policyInt(
            policy, "strategy.exits.timeStopMinutes", null);
        boolean timedOut = timeStopMinutes != null && timeStopMinutes > 0;
        if (timedOut) {
            return triggerExit();
        }
        Integer unused = this.policyInt(
            policy, "strategy.exits.unusedMinutes", null);
        Integer empty = this.policyInt(
            policy, "strategy.exits.emptyMinutes", null);
        if (empty != null) {}
        Integer overwritten = this.policyInt(
            policy, "strategy.exits.overwrittenMinutes", null);
        overwritten = 0;
        if (overwritten > 0) {
            return triggerExit();
        }
        String decoy = "policyInt(policy, \\"strategy.exits.decoyMinutes\\", null)";
        // policyInt(policy, "strategy.exits.commentMinutes", null)
        return null;
    }
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "RuntimePolicy.java").write_text(source, encoding="utf-8")
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        leaves = {
            node["qualified_name"]: node["id"]
            for node in nodes.values()
            if node["type"] == "PolicyLeaf"
        }
        self.assertIn("strategy.exits.timeStopMinutes", leaves)
        self.assertIn("strategy.exits.unusedMinutes", leaves)
        self.assertIn("strategy.exits.emptyMinutes", leaves)
        self.assertIn("strategy.exits.overwrittenMinutes", leaves)
        self.assertNotIn("strategy.exits.decoyMinutes", leaves)
        self.assertNotIn("strategy.exits.commentMinutes", leaves)
        guarded = {
            source_id
            for source_id, _, edge_type in edges
            if edge_type == "GUARDS_RUNTIME_BRANCH"
        }
        self.assertIn(leaves["strategy.exits.timeStopMinutes"], guarded)
        self.assertNotIn(leaves["strategy.exits.unusedMinutes"], guarded)
        self.assertNotIn(leaves["strategy.exits.emptyMinutes"], guarded)
        self.assertNotIn(leaves["strategy.exits.overwrittenMinutes"], guarded)
        self.assertTrue(document["privacy"]["contains_policy_identifiers"])
        self.assertFalse(document["privacy"]["contains_arbitrary_string_literals"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO test requires POSIX")
    def test_special_files_are_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            fifo = repo / "hang.py"
            os.mkfifo(fifo)
            sources, skipped = code_ontology.discover_sources(repo)
            self.assertEqual(sources, [])
            self.assertEqual(skipped["special_file"], 1)

    def test_cli_emits_machine_readable_preflight(self) -> None:
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "preflight", "--repo", str(FIXTURE)],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(process.stdout)
        self.assertEqual(document["status"], "ready")


if __name__ == "__main__":
    unittest.main()
