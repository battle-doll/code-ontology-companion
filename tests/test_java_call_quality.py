from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "manage-code-ontology" / "scripts" / "code_ontology_core.py"

SPEC = importlib.util.spec_from_file_location("java_call_quality_core", SCRIPT)
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def analyze(source: str) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary)
        (repo / "Calls.java").write_text(source, encoding="utf-8")
        return core.build_document(repo)


def call_targets(document: dict, source_qualified_name: str) -> set[str]:
    nodes = {node["id"]: node for node in document["nodes"]}
    source_id = next(
        node_id
        for node_id, node in nodes.items()
        if node.get("qualified_name") == source_qualified_name
    )
    return {
        str(nodes[edge["target"]].get("qualified_name"))
        for edge in document["edges"]
        if edge["source"] == source_id and edge["type"] == "CALLS"
    }


class JavaCallQualityTests(unittest.TestCase):
    def test_resolves_unique_same_owner_calls_by_name_and_argument_count(self) -> None:
        document = analyze(
            """package demo;
class Calls {
    void zero() {}
    void one(String value) {}
    void source() {
        zero();
        this.one("comma,value");
    }
}
"""
        )

        self.assertEqual(
            {
                "demo.Calls#zero()",
                "demo.Calls#one(java.lang.String)",
            },
            call_targets(document, "demo.Calls#source()"),
        )

    def test_omits_same_arity_overload_ambiguity(self) -> None:
        document = analyze(
            """package demo;
class Calls {
    void pick(int value) {}
    void pick(String value) {}
    void source() {
        pick(1);
        this.pick("one");
    }
}
"""
        )

        self.assertEqual(set(), call_targets(document, "demo.Calls#source()"))

    def test_maps_explicitly_imported_type_static_call_only(self) -> None:
        document = analyze(
            """package demo;
import java.util.Collections;
class Calls {
    void source(Worker worker) {
        Collections.emptyList();
        worker.run();
        this.missing();
    }
}
class Worker { void run() {} }
"""
        )

        targets = call_targets(document, "demo.Calls#source(demo.Worker)")
        self.assertEqual({"java.util.Collections.emptyList"}, targets)
        external = next(
            node
            for node in document["nodes"]
            if node.get("qualified_name") == "java.util.Collections.emptyList"
        )
        self.assertEqual("ExternalCallable", external["type"])

    def test_skips_keywords_constructors_declarations_and_annotations(self) -> None:
        document = analyze(
            """package demo;
class Calls {
    void LocalType() {}
    void SuppressWarnings(String value) {}
    void target() {}
    void source(boolean enabled) {
        if (enabled) { while (false) { } }
        new LocalType();
        @SuppressWarnings("target()")
        class Local { void target() {} }
    }
}
class LocalType {}
"""
        )

        self.assertEqual(
            set(),
            call_targets(document, "demo.Calls#source(java.lang.boolean)"),
        )

    def test_comments_and_literals_do_not_create_calls(self) -> None:
        document = analyze(
            """package demo;
class Calls {
    void target() {}
    void source() {
        String text = "target() and this.target()";
        // target();
        /* this.target(); */
        char marker = '(';
    }
}
"""
        )

        self.assertEqual(set(), call_targets(document, "demo.Calls#source()"))


if __name__ == "__main__":
    unittest.main()
