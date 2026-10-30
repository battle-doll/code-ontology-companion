"""Synthetic Java declaration evidence; no application fixtures or execution."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/manage-code-ontology/scripts"
SPEC = importlib.util.spec_from_file_location("java_declaration_fidelity_core", SCRIPTS / "code_ontology_core.py")
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
sys.path.insert(0, str(SCRIPTS))
import pipeline_java


def project(source: str, others: dict[str, str] | None = None):
    index = core.build_java_index({"Use.java": source, **(others or {})})
    facts = {"path": "Use.java", "sourceDigest": hashlib.sha256(source.encode()).hexdigest(),
             "module": "synthetic", "modulePath": ".", "records": []}
    return index, pipeline_java.enrich(facts, index)["records"]


class JavaDeclarationFidelityTests(unittest.TestCase):
    def test_static_wildcard_nested_types_resolve_without_same_package_guess(self):
        index, rows = project("""package caller; import static library.Container.*;
class Use { Inner echo(Inner input) { return input; } void execute(Inner input) { input.go(); } }
""", {"Container.java": "package library; class Container { static class Inner { void go() {} } }"})
        method = next(r for r in rows if r["name"] == "echo")
        self.assertEqual("library.Container.Inner", method["parameterTypes"][0])
        self.assertEqual("library.Container.Inner", method["returnTypeReference"]["resolvedType"])
        self.assertEqual("on_demand_import", method["returnTypeReference"]["reason"])
        self.assertEqual("exact", index.calls["Use.java"][0]["resolution"])

    def test_static_explicit_nested_type_and_two_wildcards_are_distinct(self):
        declarations = {"One.java": "package first; class Outer { static class Inner { void go() {} } }",
                        "Two.java": "package second; class Outer { static class Inner { void go() {} } }"}
        index, _ = project("""package caller; import static first.Outer.Inner;
class Use { void execute(Inner input) { input.go(); } }""", declarations)
        self.assertEqual("exact", index.calls["Use.java"][0]["resolution"])
        index, rows = project("""package caller; import static first.Outer.*; import static second.Outer.*;
class Use { void execute(Inner input) { input.go(); } }""", declarations)
        ref = next(r for r in rows if r["name"] == "execute")["parameterTypeReferences"][0]
        self.assertEqual("ambiguous", ref["resolution"])
        self.assertIsNone(ref["resolvedType"])
        self.assertEqual(2, len(ref["candidates"]))
        self.assertEqual("unresolved", index.calls["Use.java"][0]["resolution"])

    def test_nonstatic_member_cannot_supply_static_import_target(self):
        index, rows = project("""package caller; import static library.Outer.*;
class Use { void execute(Inner input) { input.go(); } }""",
            {"Outer.java": "package library; class Outer { class Inner { void go() {} } }"})
        self.assertEqual("unresolved", index.calls["Use.java"][0]["resolution"])
        ref = next(r for r in rows if r["name"] == "execute")["parameterTypeReferences"][0]
        self.assertEqual("unresolved", ref["resolution"])

    def test_unresolved_slots_keep_legacy_identity_with_explicit_status(self):
        index, rows = project("""package caller;
class Use { Mystery echo(Mystery input) { return input; } void execute() { echo(null); } }""")
        method = next(r for r in rows if r["name"] == "echo")
        self.assertEqual("caller.Use#echo(caller.Mystery)", method["qualifiedName"])
        self.assertEqual("unresolved", method["returnTypeReference"]["resolution"])
        self.assertIsNone(method["returnTypeReference"]["resolvedType"])
        # Partial type evidence does not make this unique declaration ambiguous.
        self.assertEqual("exact", index.calls["Use.java"][0]["resolution"])
        self.assertEqual("java:method:caller.Use#echo(caller.Mystery)", index.calls["Use.java"][0]["target"])

    def test_generic_arguments_annotations_throws_and_whole_declaration_spans(self):
        source = """package caller;
import java.util.Map;
import java.util.List;
import java.io.IOException;
import sample.Mark;
class Use<T extends Number> {
    @Mark("PRIVATE_ANNOTATION_VALUE")
    public <R extends T> Map<String, List<? extends R[]>> convert(@Mark("HIDDEN") final List<T[]> values)
            throws IOException, IllegalStateException {
        return null;
    }
}
"""
        _, rows = project(source)
        method = next(r for r in rows if r["name"] == "convert")
        self.assertEqual("java.util.Map", method["returnType"])
        self.assertEqual("java.util.List", method["parameterTypes"][0])
        self.assertEqual("sample.Mark", method["annotations"][0]["resolvedType"])
        self.assertEqual("T[]", method["parameterTypeReferences"][0]["genericArguments"][0]["rawType"])
        wildcard = method["returnTypeReference"]["genericArguments"][1]["genericArguments"][0]
        self.assertEqual("extends", wildcard["wildcard"])
        self.assertEqual("type_variable", wildcard["resolution"])
        self.assertEqual(1, wildcard["arrayDimensions"])
        self.assertEqual("R", method["typeParameters"][0]["name"])
        self.assertEqual("T", method["typeParameters"][0]["bounds"][0]["rawType"])
        self.assertEqual("java.io.IOException", method["throwsTypes"][0]["resolvedType"])
        self.assertEqual("unresolved", method["throwsTypes"][1]["resolution"])
        self.assertEqual({"lineStart": 7, "lineEnd": 11}, method["declarationSpan"])
        self.assertEqual({"lineStart": 9, "lineEnd": 11}, method["bodySpan"])
        self.assertEqual(method["span"], method["headerSpan"])
        self.assertLess(method["span"]["lineEnd"], method["declarationSpan"]["lineEnd"])
        self.assertNotIn("PRIVATE_ANNOTATION_VALUE", str(rows))
        self.assertNotIn("HIDDEN", str(rows))
        owner = next(r for r in rows if r.get("type") == "Class")
        self.assertEqual("java.lang.Number", owner["typeParameters"][0]["bounds"][0]["resolvedType"])

    def test_primitive_signature_identity_and_varargs_array_details(self):
        _, rows = project("class Use { void take(int value, String... names) {} }")
        method = next(r for r in rows if r["name"] == "take")
        self.assertEqual("Use#take(java.lang.int,java.lang.String[])", method["qualifiedName"])
        self.assertEqual("primitive", method["parameterTypeReferences"][0]["resolution"])
        self.assertEqual(1, method["parameterTypeReferences"][1]["arrayDimensions"])
        self.assertTrue(method["parameterTypeReferences"][1]["varargs"])

    def test_type_variable_shadow_never_resolves_to_same_named_class(self):
        index, rows = project("""class T { void go() {} }
class Use<T> { T field; T value() { return null; }
void execute(T param) { param.go(); field.go(); value().go(); T.go(); } }""")
        calls = [c for c in index.calls["Use.java"] if c["name"] == "go"]
        self.assertEqual(4, len(calls))
        self.assertTrue(all(c["resolution"] == "unresolved" for c in calls))
        method = next(r for r in rows if r["name"] == "value")
        self.assertEqual("type_variable", method["returnTypeReference"]["resolution"])

    def test_generic_metadata_depth_limit_is_explicit(self):
        raw = "List<" * 40 + "String" + ">" * 40
        _, rows = project("import java.util.List; class Use { " + raw + " value() { return null; } }")
        ref = next(r for r in rows if r["name"] == "value")["returnTypeReference"]
        depth = 0
        while ref["genericArguments"]:
            ref = ref["genericArguments"][0]
            depth += 1
        self.assertEqual(32, depth)
        self.assertEqual("depth_limit", ref["genericArgumentsStatus"])

    def test_unique_external_parameter_keeps_resolved_return_chain(self):
        index, rows = project("""package demo; import outside.*;
class Worker { void go() {} }
class Use { Worker factory(Path path) { return null; }
void execute(Path path) { factory(path).go(); } }""")
        calls = index.calls["Use.java"]
        self.assertEqual(2, len(calls))
        self.assertTrue(all(c["resolution"] == "exact" for c in calls))
        factory = next(r for r in rows if r["name"] == "factory")
        self.assertEqual("unresolved", factory["parameterTypeReferences"][0]["resolution"])
        self.assertEqual("demo.Worker", factory["returnTypeReference"]["resolvedType"])

    def test_unique_generic_declaration_does_not_require_type_inference(self):
        index, rows = project("""class Use { <T> void consume(T value) {}
void execute() { consume("known"); } }""")
        call = index.calls["Use.java"][0]
        self.assertEqual("exact", call["resolution"])
        self.assertEqual("java:method:Use#consume(T)", call["target"])
        target = next(r for r in rows if r["name"] == "consume")
        self.assertEqual("type_variable", target["parameterTypeReferences"][0]["resolution"])

    def test_unresolved_return_only_blocks_the_subsequent_receiver(self):
        index, _ = project("""class Use { Missing factory() { return null; }
void execute() { factory().go(); } }""")
        calls = {r["name"]: r for r in index.calls["Use.java"]}
        self.assertEqual("exact", calls["factory"]["resolution"])
        self.assertEqual("unresolved", calls["go"]["resolution"])
        self.assertEqual("receiver_type_unresolved", calls["go"]["reason"])
        self.assertNotIn("target", calls["go"])

    def test_overload_with_unresolved_type_is_not_exact_even_for_known_string(self):
        index, _ = project("""class Use { void pick(String value) {} void pick(Missing value) {}
void execute() { pick("known"); } }""")
        call = index.calls["Use.java"][0]
        self.assertEqual("candidate", call["resolution"])
        self.assertEqual(2, len(call["candidateTargets"]))
        self.assertNotIn("target", call)


if __name__ == "__main__":
    unittest.main()
