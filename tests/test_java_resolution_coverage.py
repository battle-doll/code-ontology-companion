from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("java_resolution_coverage_core", ROOT / "skills/manage-code-ontology/scripts/code_ontology_core.py")
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class JavaResolutionCoverageTests(unittest.TestCase):
    def test_interface_field_parameter_and_explicit_this_have_declared_targets(self):
        index = core.build_java_index({
            "Gateway.java": "package demo; interface Gateway { void submit(int n); }",
            "Use.java": """package demo;
class Use {
    private final Gateway gateway = null;
    void execute(Gateway parameter) {
        gateway.submit(1); this.gateway.submit(2); parameter.submit(3);
    }
}""",
        })
        calls = index.calls["Use.java"]
        self.assertEqual(3, len(calls))
        self.assertTrue(all(c["resolution"] == "exact" for c in calls))
        self.assertEqual({"java:method:demo.Gateway#submit(java.lang.int)"}, {c["target"] for c in calls})
        self.assertTrue(all(c["runtimeDispatch"] == "not_observed" for c in calls))

    def test_same_package_wildcard_and_nested_type_identity(self):
        index = core.build_java_index({
            "Nested.java": "package library; class Outer { static class Inner { static void work() {} } }",
            "Use.java": "package caller; import library.*; class Use { void execute(Outer.Inner value) { value.work(); Outer.Inner.work(); } }",
        })
        method = next(m for m in index.methods.values() if m["name"] == "execute")
        self.assertEqual(["library.Outer.Inner"], method["parameter_types"])
        self.assertEqual(2, sum(c["resolution"] == "exact" for c in index.calls["Use.java"]))

    def test_ambiguous_wildcard_is_not_guessed_from_global_simple_name(self):
        index = core.build_java_index({
            "First.java": "package first; class Worker { void go() {} }",
            "Second.java": "package second; class Worker { void go() {} }",
            "Use.java": "package caller; import first.*; import second.*; class Use { void execute(Worker w) { w.go(); } }",
        })
        call = index.calls["Use.java"][0]
        self.assertEqual("unresolved", call["resolution"])
        self.assertNotIn("target", call)

    def test_overload_unknown_argument_stays_candidate_with_both_targets(self):
        index = core.build_java_index({"Use.java": """class Use {
void pick(String s) {} void pick(Integer n) {}
void execute() { pick(null); } }"""})
        call = index.calls["Use.java"][0]
        self.assertEqual("candidate", call["resolution"])
        self.assertEqual(2, len(call["candidateTargets"]))
        self.assertNotIn("target", call)

    def test_new_expression_and_chained_return_resolve_without_constructor_claim(self):
        index = core.build_java_index({"Use.java": """class Gateway { void submit() {} }
class Holder { Gateway gateway() { return null; } }
class Use { void execute() { new Holder().gateway().submit(); } }"""})
        calls = index.calls["Use.java"]
        constructor = next(c for c in calls if c["name"] == "Holder")
        self.assertEqual("unresolved", constructor["resolution"])
        self.assertEqual("constructor", constructor["invocationKind"])
        self.assertEqual("exact", next(c for c in calls if c["name"] == "submit")["resolution"])

    def test_local_scope_shadowing_does_not_become_static_type_call(self):
        index = core.build_java_index({
            "Worker.java": "package lib; class Worker { static void go() {} }",
            "Use.java": """package demo; import lib.Worker;
class Other { void go() {} }
class Use { void execute(Other Worker) { Worker.go(); } }""",
        })
        self.assertEqual("java:method:demo.Other#go()", index.calls["Use.java"][0]["target"])

    def test_lambda_unknown_parameter_and_anonymous_body_are_not_outer_calls(self):
        index = core.build_java_index({"Use.java": """class Worker { void go() {} }
class Use {
Worker worker;
void own() {}
void execute() {
    use(worker -> worker.go());
    new Runnable() { public void run() { own(); } };
}
}"""})
        calls = index.calls["Use.java"]
        self.assertEqual("unresolved", next(c for c in calls if c["name"] == "go")["resolution"])
        self.assertFalse(any(c["name"] == "own" for c in calls))

    def test_repeated_sites_keep_independent_identity_and_original_denominator(self):
        source = "class Use { void target() {} void execute() { target(); target(); missing(); } }"
        index = core.build_java_index({"Use.java": source})
        result = index.summary()
        self.assertEqual(3, result["denominator"])
        self.assertEqual(2, result["numerator"])
        self.assertEqual(3, len({c["id"] for c in result["callsites"]}))
        self.assertEqual("PARTIAL", result["status"])
        self.assertIsNone(result["wholeSourceDenominator"])
        self.assertEqual({hashlib.sha256(source.encode()).hexdigest()}, {c["sourceHash"] for c in result["callsites"]})

    def test_literals_and_comments_never_escape_or_create_invocations(self):
        sentinel = "PRIVATE_LITERAL_DO_NOT_RETAIN"
        source = f'class Use {{ void execute() {{ String s = "{sentinel} fakeCall()"; /* hidden() */ }} }}'
        index = core.build_java_index({"Use.java": source})
        self.assertEqual([], index.summary()["callsites"])
        self.assertNotIn(sentinel, json.dumps(index.summary()))

    def test_record_is_not_a_phantom_method_and_duplicate_types_fail_closed(self):
        index = core.build_java_index({"Use.java": "class Use { public record Item(int x) {} void execute() {} }"})
        self.assertEqual(["execute"], [m["name"] for m in index.methods.values()])
        with self.assertRaises(core.DuplicateDeclarationError):
            core.build_java_index({"One.java": "class Same {}", "Two.java": "class Same {}"})
        with self.assertRaises(core.DuplicateDeclarationError):
            core.build_java_index({"One.java": "class Same {} class Same {}"})

    def test_unbalanced_source_is_explicit_issue_not_successful_empty_coverage(self):
        index = core.build_java_index({"Broken.java": "class Broken { void execute() { target(); }"})
        summary = index.summary()
        self.assertEqual("PARTIAL", summary["status"])
        self.assertEqual([{"path": "Broken.java", "reasons": ["java_unbalanced_braces"]}], summary["fileIssues"])

    def test_cross_file_change_invalidates_call_index_fingerprint(self):
        caller = "class Use { void execute(Gateway gateway) { gateway.go(); } }"
        before = core.build_java_index({"Use.java": caller, "Gateway.java": "class Gateway { void go() {} }"})
        after = core.build_java_index({"Use.java": caller, "Gateway.java": "class Gateway { void renamed() {} }"})
        self.assertNotEqual(before.fingerprint, after.fingerprint)
        self.assertEqual("exact", before.calls["Use.java"][0]["resolution"])
        self.assertEqual("unresolved", after.calls["Use.java"][0]["resolution"])

    def test_external_parent_does_not_hide_possible_inherited_overload(self):
        index = core.build_java_index({"Use.java": """class Worker extends ExternalBase {
void go(String value) {}
} class Use { void execute(Worker worker) { worker.go(null); } }"""})
        call = index.calls["Use.java"][0]
        self.assertEqual("candidate", call["resolution"])
        self.assertEqual("inherited_overload_scope_incomplete", call["reason"])
        self.assertNotIn("target", call)

    def test_internal_inherited_overloads_are_considered_before_exact_choice(self):
        index = core.build_java_index({"Use.java": """class Base { void go(Integer value) {} }
class Worker extends Base { void go(String value) {} }
class Use { void execute(Worker worker) { worker.go(null); } }"""})
        call = index.calls["Use.java"][0]
        self.assertEqual("candidate", call["resolution"])
        self.assertEqual(2, len(call["candidateTargets"]))

    def test_array_receiver_is_not_the_element_type(self):
        index = core.build_java_index({"Use.java": """class Worker { void go() {} }
class Use { Worker[] workers; Worker[] all() { return null; }
void execute(Worker param[]) { workers.go(); param.go(); all().go(); } }"""})
        self.assertTrue(all(c["resolution"] != "exact" for c in index.calls["Use.java"] if c["name"] == "go"))

    def test_literal_prefix_is_not_a_literal_argument_type(self):
        index = core.build_java_index({"Use.java": """class Use {
void pick(String x) {} void pick(int n) {}
void execute() { pick("text".length()); }
}"""})
        call = next(c for c in index.calls["Use.java"] if c["name"] == "pick")
        self.assertEqual("candidate", call["resolution"])

    def test_constructor_parameters_do_not_pollute_declared_field_types(self):
        index = core.build_java_index({"Use.java": """class Real { void go() {} }
class Other { void go() {} }
class Use {
Real worker;
Use(Other worker, int count) {}
void execute() { worker.go(); }
}"""})
        self.assertEqual("java:method:Real#go()", index.calls["Use.java"][0]["target"])

    def test_same_package_type_shadows_implicit_java_lang_type(self):
        index = core.build_java_index({"Use.java": """package demo;
class String { void local() {} }
class Use { void execute(String value) { value.local(); } }"""})
        self.assertEqual("java:method:demo.String#local()", index.calls["Use.java"][0]["target"])

    def test_standard_marker_interface_does_not_invent_an_unrelated_overload(self):
        index = core.build_java_index({"Use.java": """class Use implements AutoCloseable {
void target() {} public void close() {}
void execute() { target(); }
}"""})
        self.assertEqual("exact", index.calls["Use.java"][0]["resolution"])

    def test_cross_file_callsite_budget_fails_instead_of_truncating(self):
        with mock.patch.object(core, "MAX_GRAPH_EDGES", 1):
            with self.assertRaisesRegex(core.OntologyError, "global result safety budget"):
                core.build_java_index({
                    "One.java": "class One { void execute() { unknown(); } }",
                    "Two.java": "class Two { void execute() { missing(); } }",
                })

    def test_resolver_content_hash_participates_in_index_identity(self):
        index = core.build_java_index({"One.java": "class One {}"})
        expected = hashlib.sha256((ROOT / "skills/manage-code-ontology/scripts/java_resolution.py").read_bytes()).hexdigest()
        self.assertEqual(expected, index.summary()["analyzerHash"])
        self.assertEqual(hashlib.sha256((index.source_fingerprint + "\n" + expected).encode()).hexdigest(), index.fingerprint)


if __name__ == "__main__":
    unittest.main()
