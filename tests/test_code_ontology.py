from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "manage-code-ontology" / "scripts" / "code_ontology_core.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample-app"

SPEC = importlib.util.spec_from_file_location("code_ontology_core", SCRIPT)
assert SPEC and SPEC.loader
code_ontology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(code_ontology)


def workbench_payload_text(page: str) -> str:
    match = re.search(
        r'<script id="ontology-data" type="application/json">(.*?)</script>',
        page,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("workbench payload script is missing")
    return match.group(1)


def workbench_payload(page: str) -> dict:
    return json.loads(workbench_payload_text(page))


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CodeOntologyTests(unittest.TestCase):
    def test_windows_stable_metadata_ignores_deprecated_ctime_only(self) -> None:
        left = SimpleNamespace(
            st_size=12,
            st_mtime=3.0,
            st_mtime_ns=3_000_000_000,
            st_ctime=4.0,
            st_ctime_ns=4_000_000_000,
        )
        right = SimpleNamespace(
            st_size=12,
            st_mtime=3.0,
            st_mtime_ns=3_000_000_000,
            st_ctime=5.0,
            st_ctime_ns=5_000_000_000,
        )
        modified = SimpleNamespace(
            st_size=12,
            st_mtime=6.0,
            st_mtime_ns=6_000_000_000,
            st_ctime=5.0,
            st_ctime_ns=5_000_000_000,
        )

        with mock.patch.object(code_ontology.os, "name", "nt"):
            self.assertEqual(
                code_ontology._stable_file_metadata(left),
                code_ontology._stable_file_metadata(right),
            )
            self.assertNotEqual(
                code_ontology._stable_file_metadata(left),
                code_ontology._stable_file_metadata(modified),
            )
        with mock.patch.object(code_ontology.os, "name", "posix"):
            self.assertNotEqual(
                code_ontology._stable_file_metadata(left),
                code_ontology._stable_file_metadata(right),
            )

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
        payload = workbench_payload(page)
        self.assertEqual(len(payload["nodes"]), len(document["nodes"]))
        self.assertEqual(len(payload["edges"]), len(document["edges"]))
        self.assertEqual(
            payload["limits"]["maxVisibleNodes"],
            min(len(document["nodes"]), code_ontology.VISUALIZATION_MAX_VISIBLE_NODES),
        )

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
            result = code_ontology.write_visualization(
                str(index),
                str(directory / "workbench.html"),
                500,
            )
            self.assertEqual(result["nodes_indexed"], len(document["nodes"]))
            self.assertEqual(
                result["nodes_rendered"],
                min(len(document["nodes"]), code_ontology.VISUALIZATION_MAX_VISIBLE_NODES),
            )
            self.assertEqual(result["network_dependencies"], 0)

    def test_workbench_payload_is_portable_and_source_data_cannot_escape_markup(self) -> None:
        document = {
            "schema_version": "1.0",
            "generated_at": "2026-07-31T00:00:00+00:00",
            "generator": {"name": "Code Ontology Companion", "version": "0.4.0"},
            "repository": {"name": "demo </title><script>alert(1)</script>"},
            "statistics": {"source_files": {"Python": 1}, "skipped": {}},
            "nodes": [
                {
                    "id": "python:function:__CODE_ONTOLOGY_APP__</script>",
                    "type": "Function",
                    "name": "<img src=x onerror=alert(1)>",
                    "language": "Python",
                    "path": "safe/demo.py",
                    "qualified_name": "demo.run",
                    "metadata": {"parameter_count": 0, "secret": "must-not-appear"},
                    "secret": "must-not-appear",
                }
            ],
            "edges": [],
            "warnings": [],
            "companion": {
                "workspaceId": "private-workspace-id",
                "snapshotId": "snapshot-safe",
                "sourceFingerprint": "private-source-fingerprint",
                "evidenceType": "observed",
            },
        }
        page = code_ontology.render_visualization(document, 20)
        payload = workbench_payload(page)

        self.assertEqual(payload["meta"]["snapshotId"], "snapshot-safe")
        self.assertEqual(payload["nodes"][0]["name"], "<img src=x onerror=alert(1)>")
        self.assertEqual(payload["nodes"][0]["id"], "python:function:__CODE_ONTOLOGY_APP__</script>")
        self.assertNotIn("secret", payload["nodes"][0])
        self.assertNotIn("secret", payload["nodes"][0].get("metadata", {}))
        serialized_payload = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("workspaceId", serialized_payload)
        self.assertNotIn("private-workspace-id", page)
        self.assertNotIn("private-source-fingerprint", page)
        self.assertNotIn("</script>", workbench_payload_text(page))

    def test_visualization_diff_is_deterministic_and_hides_fingerprints(self) -> None:
        previous = {
            "nodes": [
                {"id": "b", "type": "Class", "name": "Before", "language": "Java"},
                {"id": "a", "type": "Class", "name": "Stable", "language": "Java"},
            ],
            "edges": [{"source": "a", "target": "b", "type": "DECLARES"}],
            "companion": {"sourceFingerprint": "same", "snapshotId": "before"},
        }
        current = {
            "nodes": [
                {"id": "c", "type": "Class", "name": "Added", "language": "Java"},
                {"id": "a", "type": "Class", "name": "Stable", "language": "Java"},
            ],
            "edges": [{"source": "a", "target": "c", "type": "DECLARES"}],
            "companion": {"sourceFingerprint": "same", "snapshotId": "after"},
        }
        change = code_ontology._visualization_diff(current, previous)

        self.assertTrue(change["available"])
        self.assertEqual(change["basis"], "analysis_refresh")
        self.assertEqual(
            change["counts"],
            {
                "nodesAdded": 1,
                "nodesRemoved": 1,
                "nodesModified": 0,
                "edgesAdded": 1,
                "edgesRemoved": 1,
            },
        )
        self.assertEqual([node["id"] for node in change["nodesAdded"]], ["c"])
        self.assertEqual([node["id"] for node in change["nodesRemoved"]], ["b"])
        self.assertNotIn("same", json.dumps(change))

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
import org.springframework.context.annotation.Bean;
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

    def test_java_hierarchy_generics_records_and_annotation_provenance(self) -> None:
        source = """package demo;
import java.util.List;
import a.b.Outer;
import com.acme.Service;
import com.foo.*;
import org.springframework.stereotype.*;
class Base {}
interface One {}
interface Two {}
class Child<T extends Base> extends Base implements One, Two {}
interface Combined<T extends Base> extends One, Two {}
record Entry(@Deprecated(values={One.class, Two.class}) List<? extends Base> items)
        implements One {}
class Nested extends Outer.Inner {}
class WildcardPort implements Port {}
@Service class NotSpringManaged {}
"""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "Hierarchy.java").write_text(source, encoding="utf-8")
            (repo / "Ambiguous.java").write_text(
                "package other;\n"
                "import com.acme.*;\n"
                "import org.springframework.stereotype.*;\n"
                "@Service class AmbiguousService {}\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        by_name = {
            node.get("qualified_name"): node["id"]
            for node in nodes.values()
            if node.get("qualified_name")
        }
        child = by_name["demo.Child"]
        combined = by_name["demo.Combined"]
        entry = by_name["demo.Entry"]
        self.assertIn((child, by_name["demo.Base"], "EXTENDS"), edges)
        self.assertIn((child, by_name["demo.One"], "IMPLEMENTS"), edges)
        self.assertIn((child, by_name["demo.Two"], "IMPLEMENTS"), edges)
        self.assertIn((combined, by_name["demo.One"], "EXTENDS"), edges)
        self.assertIn((combined, by_name["demo.Two"], "EXTENDS"), edges)
        self.assertIn((entry, by_name["demo.One"], "IMPLEMENTS"), edges)
        self.assertIn(
            (by_name["demo.Nested"], by_name["a.b.Outer.Inner"], "EXTENDS"),
            edges,
        )
        self.assertIn(
            (by_name["demo.WildcardPort"], by_name["Port"], "IMPLEMENTS"),
            edges,
        )
        self.assertNotIn("demo.Port", by_name)
        self.assertFalse(
            any(
                source_id == entry and edge_type == "EXTENDS"
                for source_id, _, edge_type in edges
            )
        )
        not_spring = by_name["demo.NotSpringManaged"]
        self.assertNotIn((not_spring, "framework:spring:bean", "MANAGED_AS"), edges)
        ambiguous = by_name["other.AmbiguousService"]
        self.assertNotIn((ambiguous, "framework:spring:bean", "MANAGED_AS"), edges)
        self.assertFalse(any("Bound>" in value for value in by_name))

    def test_java_same_package_annotations_shadow_spring_wildcards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "LocalService.java").write_text(
                "package demo;\npublic @interface Service {}\n",
                encoding="utf-8",
            )
            (repo / "UseLocal.java").write_text(
                "package demo;\n"
                "import org.springframework.stereotype.*;\n"
                "@Service class UseLocal {}\n",
                encoding="utf-8",
            )
            (repo / "SameFile.java").write_text(
                "package same;\n"
                "import org.springframework.stereotype.*;\n"
                "@interface Component {}\n"
                "@Component class UseSameFile {}\n",
                encoding="utf-8",
            )
            (repo / "UseSpring.java").write_text(
                "package actual;\n"
                "import org.springframework.stereotype.*;\n"
                "@Service class UseSpring {}\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)

        by_name = {
            node.get("qualified_name"): node["id"]
            for node in document["nodes"]
            if node.get("qualified_name")
        }
        managed = {
            edge["source"]
            for edge in document["edges"]
            if edge["type"] == "MANAGED_AS"
        }
        self.assertNotIn(by_name["demo.UseLocal"], managed)
        self.assertNotIn(by_name["same.UseSameFile"], managed)
        self.assertIn(by_name["actual.UseSpring"], managed)

    def test_java_spring_injection_is_conservative_and_parses_parameter_annotations(self) -> None:
        source = """package demo;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.stereotype.Service;
import jakarta.transaction.Transactional;
@SpringBootApplication
class Application {}
@Service
class Managed {
    @Transactional
    void commit() {}
    Managed(@Qualifier("primary") Client client) {}
}
class Plain {
    Plain(Client client) {}
}
@Configuration
class Factory {
    @Bean
    Widget widget(@Qualifier("primary") Client client) { return null; }
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "Injection.java").write_text(source, encoding="utf-8")
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        by_name = {
            node.get("qualified_name"): node["id"]
            for node in nodes.values()
            if node.get("qualified_name")
        }
        client = by_name["demo.Client"]
        self.assertIn((by_name["demo.Managed"], client, "INJECTS"), edges)
        self.assertNotIn((by_name["demo.Plain"], client, "INJECTS"), edges)
        self.assertIn(
            (by_name["demo.Application"], "framework:spring:bean", "MANAGED_AS"),
            edges,
        )
        commit = next(node["id"] for node in nodes.values() if node["name"] == "commit")
        self.assertIn((commit, "framework:spring:proxy", "MAY_BE_PROXIED_BY"), edges)
        widget = next(node["id"] for node in nodes.values() if node["name"] == "widget")
        self.assertIn((widget, client, "INJECTS"), edges)

    def test_java_constructor_detection_handles_compact_and_generic_declarations(self) -> None:
        source = """package demo;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
class Client {}
@Service class Compact { Compact(Client client) {} }
@Service
class Overloaded {
    Overloaded(Client client) {}
    <T> Overloaded(T alternate) {}
}
@Service
class ExplicitGeneric {
    @Autowired
    <T> ExplicitGeneric(Client client) {}
    ExplicitGeneric() {}
}
@Service
class MethodNamed {
    void MethodNamed(Client client) {}
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "Constructors.java").write_text(source, encoding="utf-8")
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        by_name = {
            node.get("qualified_name"): node["id"]
            for node in nodes.values()
            if node.get("qualified_name")
        }
        client = by_name["demo.Client"]
        self.assertIn((by_name["demo.Compact"], client, "INJECTS"), edges)
        self.assertNotIn((by_name["demo.Overloaded"], client, "INJECTS"), edges)
        self.assertIn((by_name["demo.ExplicitGeneric"], client, "INJECTS"), edges)
        self.assertNotIn((by_name["demo.MethodNamed"], client, "INJECTS"), edges)

    def test_python_import_aliases_relative_calls_and_lexical_scope_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            package = repo / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "helpers.py").write_text(
                "def fetch_orders():\n    return []\n",
                encoding="utf-8",
            )
            (package / "consumer.py").write_text(
                "from .helpers import fetch_orders as fetch\n"
                "def run_pipeline():\n    return fetch()\n",
                encoding="utf-8",
            )
            (repo / "scope.py").write_text(
                "import pkg.tools as tools\n"
                "def b():\n    return 1\n"
                "def use(tools):\n    return tools.fetch()\n"
                "def reassigned(callback):\n    helper = callback\n    return helper()\n"
                "def outer():\n    def inner():\n        return 3\n    return inner()\n"
                "class C:\n"
                "    def a(self):\n        b()\n        self.b()\n"
                "    def b(self):\n        return 2\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        by_name = {
            node.get("qualified_name"): node["id"]
            for node in nodes.values()
            if node.get("qualified_name")
        }
        run_pipeline = by_name["pkg.consumer.run_pipeline"]
        self.assertIn((run_pipeline, by_name["pkg.helpers.fetch_orders"], "CALLS"), edges)
        use = by_name["scope.use"]
        self.assertTrue(
            any(
                source_id == use
                and nodes[target_id].get("qualified_name") == "tools.fetch"
                and edge_type == "CALLS"
                for source_id, target_id, edge_type in edges
            )
        )
        self.assertFalse(
            any(
                source_id == use
                and nodes[target_id].get("qualified_name") == "pkg.tools.fetch"
                for source_id, target_id, _ in edges
            )
        )
        method_a = by_name["scope.C.a"]
        self.assertIn((method_a, by_name["scope.b"], "CALLS"), edges)
        self.assertIn((method_a, by_name["scope.C.b"], "CALLS"), edges)
        reassigned = by_name["scope.reassigned"]
        self.assertNotIn((reassigned, by_name["scope.b"], "CALLS"), edges)
        self.assertIn(
            (by_name["scope.outer"], by_name["scope.outer.inner"], "CALLS"),
            edges,
        )

    def test_python_nested_and_shadowed_import_bindings_are_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            package = repo / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "mod.py").write_text(
                "def run():\n    return 1\n",
                encoding="utf-8",
            )
            (repo / "scopes.py").write_text(
                "import pkg as caught\n"
                "import pkg as rebound\n"
                "import pkg as comprehension_name\n"
                "rebound = object()\n"
                "def local_import():\n"
                "    import pkg.mod as local_mod\n"
                "    return local_mod.run()\n"
                "def closure():\n"
                "    def helper():\n"
                "        return 1\n"
                "    def inner():\n"
                "        return helper()\n"
                "    return inner()\n"
                "def exception_shadow():\n"
                "    try:\n"
                "        raise RuntimeError()\n"
                "    except RuntimeError as caught:\n"
                "        return caught.run()\n"
                "def rebound_call():\n"
                "    return rebound.run()\n"
                "def after_comprehension(values):\n"
                "    [comprehension_name.run() for comprehension_name in values]\n"
                "    return comprehension_name.run()\n"
                "def lambda_shadow(value):\n"
                "    return (lambda caught: caught.run())(value)\n"
                "def global_outer():\n"
                "    caught = object()\n"
                "    def global_inner():\n"
                "        global caught\n"
                "        return caught.run()\n"
                "    return global_inner()\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)

        nodes = {node["id"]: node for node in document["nodes"]}
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        by_name = {
            node.get("qualified_name"): node["id"]
            for node in nodes.values()
            if node.get("qualified_name")
        }
        self.assertIn(
            (by_name["scopes.local_import"], by_name["pkg.mod.run"], "CALLS"),
            edges,
        )
        self.assertIn(
            (
                by_name["scopes.closure.inner"],
                by_name["scopes.closure.helper"],
                "CALLS",
            ),
            edges,
        )
        exception_calls = {
            nodes[target].get("qualified_name")
            for source, target, edge_type in edges
            if source == by_name["scopes.exception_shadow"] and edge_type == "CALLS"
        }
        self.assertIn("caught.run", exception_calls)
        self.assertNotIn("pkg.run", exception_calls)
        rebound_calls = {
            nodes[target].get("qualified_name")
            for source, target, edge_type in edges
            if source == by_name["scopes.rebound_call"] and edge_type == "CALLS"
        }
        self.assertIn("rebound.run", rebound_calls)
        self.assertNotIn("pkg.run", rebound_calls)
        self.assertIn(
            (
                by_name["scopes.after_comprehension"],
                by_name["pkg.run"],
                "CALLS",
            ),
            edges,
        )
        lambda_calls = {
            nodes[target].get("qualified_name")
            for source, target, edge_type in edges
            if source == by_name["scopes.lambda_shadow"] and edge_type == "CALLS"
        }
        self.assertIn("caught.run", lambda_calls)
        self.assertNotIn("pkg.run", lambda_calls)
        self.assertIn(
            (
                by_name["scopes.global_outer.global_inner"],
                by_name["pkg.run"],
                "CALLS",
            ),
            edges,
        )
        self.assertIn(
            (
                by_name["scopes.after_comprehension"],
                by_name["comprehension_name.run"],
                "CALLS",
            ),
            edges,
        )

    def test_python_pipeline_roles_use_tokens_not_substrings(self) -> None:
        source = """def breadth(): pass
def sparse_matrix(): pass
def restore_backup(): pass
def fetch_orders(): pass
"""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "roles.py").write_text(source, encoding="utf-8")
            document = code_ontology.build_document(repo)

        role_sources = {
            edge["source"]
            for edge in document["edges"]
            if edge["type"] == "HAS_PIPELINE_ROLE"
        }
        ids = {
            node["name"]: node["id"]
            for node in document["nodes"]
            if node["type"] in {"Function", "AsyncFunction"}
        }
        self.assertIn(ids["fetch_orders"], role_sources)
        self.assertNotIn(ids["breadth"], role_sources)
        self.assertNotIn(ids["sparse_matrix"], role_sources)
        self.assertNotIn(ids["restore_backup"], role_sources)

    def test_python_internal_module_replaces_earlier_external_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "a_consumer.py").write_text(
                "import z_provider\ndef use():\n    return z_provider.helper()\n",
                encoding="utf-8",
            )
            (repo / "z_provider.py").write_text(
                "def helper():\n    return 1\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)

        provider = next(
            node
            for node in document["nodes"]
            if node.get("qualified_name") == "z_provider"
        )
        self.assertEqual("Module", provider["type"])
        self.assertEqual("z_provider.py", provider["path"])

    def test_python_src_layout_uses_importable_package_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            package = repo / "src" / "pkg"
            package.mkdir(parents=True)
            (package / "a.py").write_text(
                "from pkg.b import helper\ndef run():\n    return helper()\n",
                encoding="utf-8",
            )
            (package / "b.py").write_text(
                "def helper():\n    return 1\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)

        nodes = {
            node.get("qualified_name"): node["id"]
            for node in document["nodes"]
            if node.get("qualified_name")
        }
        edges = {
            (edge["source"], edge["target"], edge["type"])
            for edge in document["edges"]
        }
        self.assertIn("pkg.a", nodes)
        self.assertIn("pkg.b.helper", nodes)
        self.assertNotIn("src.pkg.a", nodes)
        self.assertIn((nodes["pkg.a.run"], nodes["pkg.b.helper"], "CALLS"), edges)

    def test_repository_and_graph_resource_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "one.py").write_text("x = 1\n", encoding="utf-8")
            (repo / "two.py").write_text("y = 2\n", encoding="utf-8")
            with mock.patch.object(code_ontology, "MAX_SOURCE_FILES", 1):
                with self.assertRaisesRegex(code_ontology.OntologyError, "source-file limit"):
                    code_ontology.discover_sources(repo)
            with mock.patch.object(code_ontology, "MAX_TOTAL_SOURCE_BYTES", 8):
                with self.assertRaisesRegex(code_ontology.OntologyError, "source-byte limit"):
                    code_ontology.discover_sources(repo)

        graph = code_ontology.Graph("bounded")
        with mock.patch.object(code_ontology, "MAX_GRAPH_NODES", 1):
            graph.add_node("one", "Class", "One", "Java")
            graph.add_node("one", "Class", "One", "Java")
            with self.assertRaisesRegex(code_ontology.OntologyError, "node safety limit"):
                graph.add_node("two", "Class", "Two", "Java")

        graph = code_ontology.Graph("bounded-edges")
        for identifier in ("one", "two", "three"):
            graph.add_node(identifier, "Class", identifier.title(), "Java")
        with mock.patch.object(code_ontology, "MAX_GRAPH_EDGES", 1):
            graph.add_edge("one", "two", "CALLS")
            graph.add_edge("one", "two", "CALLS")
            with self.assertRaisesRegex(code_ontology.OntologyError, "edge safety limit"):
                graph.add_edge("one", "three", "CALLS")

        document = {
            "nodes": [
                {"id": identifier, "name": identifier, "type": "Class"}
                for identifier in ("root", "one", "two", "three")
            ],
            "edges": [
                {"source": "root", "target": identifier, "type": "CALLS"}
                for identifier in ("one", "two", "three")
            ],
        }
        with mock.patch.object(code_ontology, "MAX_IMPACT_RESULTS", 2):
            impact = code_ontology.impact_document(document, "root", 1)
        self.assertEqual(2, impact["impact_count"])
        self.assertTrue(impact["truncated"])

    def test_python_ast_depth_and_node_limits_fail_closed_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "deep.py").write_text(
                "value = root" + ".child" * 500 + "\n",
                encoding="utf-8",
            )
            document = code_ontology.build_document(repo)
        self.assertTrue(
            any("depth safety limit" in warning["message"] for warning in document["warnings"])
        )
        self.assertFalse(
            any(node.get("qualified_name") == "deep" for node in document["nodes"])
        )

        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "wide.py").write_text("first = 1\nsecond = 2\n", encoding="utf-8")
            with mock.patch.object(code_ontology, "MAX_PYTHON_AST_NODES", 3):
                document = code_ontology.build_document(repo)
        self.assertTrue(
            any("node safety limit" in warning["message"] for warning in document["warnings"])
        )

        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "parser.py").write_text("value = 1\n", encoding="utf-8")
            with mock.patch.object(code_ontology.ast, "parse", side_effect=RecursionError):
                document = code_ontology.build_document(repo)
        self.assertTrue(
            any(
                "parser nesting safety limit" in warning["message"]
                for warning in document["warnings"]
            )
        )

    def test_java_policy_leaf_requires_a_real_control_flow_use(self) -> None:
        source = """package demo;
class RuntimePolicy {
    Object evaluate(Object policy) {
        Integer timeStopMinutes = this.policyInt(
            policy, "service.retry.timeoutSeconds", null);
        boolean timedOut = timeStopMinutes != null && timeStopMinutes > 0;
        if (timedOut) {
            return triggerExit();
        }
        Integer unused = this.policyInt(
            policy, "service.retry.unusedSeconds", null);
        Integer empty = this.policyInt(
            policy, "service.retry.emptySeconds", null);
        if (empty != null) {}
        Integer overwritten = this.policyInt(
            policy, "service.retry.overwrittenSeconds", null);
        overwritten = 0;
        if (overwritten > 0) {
            return triggerExit();
        }
        String decoy = "policyInt(policy, \\"service.retry.decoySeconds\\", null)";
        // policyInt(policy, "service.retry.commentSeconds", null)
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
        self.assertIn("service.retry.timeoutSeconds", leaves)
        self.assertIn("service.retry.unusedSeconds", leaves)
        self.assertIn("service.retry.emptySeconds", leaves)
        self.assertIn("service.retry.overwrittenSeconds", leaves)
        self.assertNotIn("service.retry.decoySeconds", leaves)
        self.assertNotIn("service.retry.commentSeconds", leaves)
        guarded = {
            source_id
            for source_id, _, edge_type in edges
            if edge_type == "GUARDS_RUNTIME_BRANCH"
        }
        self.assertIn(leaves["service.retry.timeoutSeconds"], guarded)
        self.assertNotIn(leaves["service.retry.unusedSeconds"], guarded)
        self.assertNotIn(leaves["service.retry.emptySeconds"], guarded)
        self.assertNotIn(leaves["service.retry.overwrittenSeconds"], guarded)
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
