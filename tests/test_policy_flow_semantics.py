"""Source structure goldens: no fixture contains a private application policy."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import policy_semantics as semantics


def extract(source, **kwargs):
    return semantics.extract_semantics(source, "Java", "example/Rules.java", hashlib.sha256(source.encode()).hexdigest(), **kwargs)


def calls(result, callee):
    return [row for row in result["fragments"] if (row.get("expression") or {}).get("callee", {}).get("name") == callee]


class PolicyFlowTests(unittest.TestCase):
    def test_guard_action_return_and_following_false_path_are_linked(self):
        result = extract("class Rules { void act(int amount) { if(amount<10) { reject(); return; } save(); send(); } }")
        condition = result["fragments"][0]
        rejected = calls(result, "reject")[0]
        saved, sent = calls(result, "save")[0], calls(result, "send")[0]
        self.assertEqual(rejected["controlFlow"]["contexts"][0]["fragmentId"], condition["id"])
        self.assertEqual(rejected["controlFlow"]["contexts"][0]["branch"], "true")
        self.assertEqual(saved["controlFlow"]["contexts"][0]["branch"], "false")
        self.assertEqual(saved["controlFlow"]["contexts"][0]["relation"], "prior_branch_abrupt_completion")
        self.assertLess(saved["controlFlow"]["sourceOrder"], sent["controlFlow"]["sourceOrder"])
        self.assertEqual(saved["controlFlow"]["owner"], sent["controlFlow"]["owner"])
        self.assertEqual(saved["unsupportedReasons"], ["call_semantics_unresolved"])

    def test_dangling_else_binds_nearest_if(self):
        result = extract("class Rules { void act(boolean a, boolean b) { if(a) if(b) yes(); else no(); after(); }}")
        conditions = [row for row in result["fragments"] if row["category"] == "condition"]
        context = calls(result, "no")[0]["controlFlow"]["contexts"]
        self.assertEqual([(c["fragmentId"], c["branch"]) for c in context],
                         [(conditions[0]["id"], "true"), (conditions[1]["id"], "false")])
        self.assertEqual(calls(result, "after")[0]["controlFlow"]["contexts"], [])

    def test_catch_and_finally_keep_try_identity_and_order(self):
        result = extract("class Rules { void act() { try { store(); publish(); } catch(First | Second err) { fail(err); throw err; } finally { release(); } }}")
        tried = next(r for r in result["fragments"] if r["controlFlow"]["kind"] == "try")
        catch = next(r for r in result["fragments"] if r["controlFlow"]["kind"] == "catch")
        self.assertEqual(catch["expression"]["declaration"], ["First", "|", "Second", "err"])
        for callee, branch in [("store", "try"), ("publish", "try"), ("fail", "catch"), ("release", "finally")]:
            row = calls(result, callee)[0]
            self.assertEqual(row["controlFlow"]["contexts"][0]["fragmentId"], tried["id"])
            self.assertEqual(row["controlFlow"]["contexts"][0]["branch"], branch)
        self.assertTrue(any(r["category"] == "throw" for r in result["fragments"]))

    def test_constructor_and_record_table_preserve_argument_alignment(self):
        source = "import java.util.Map; record Row(int count, boolean active) {} class Rules { final Map<Mode,Row> TABLE=Map.of(Mode.A,new Row(2,true),Mode.B,new Row(4,false)); }"
        result = extract(source)
        expression = result["fragments"][0]["expression"]
        self.assertEqual(expression["collectionShape"]["entries"], [{"keyArgument": 0, "valueArgument": 1}, {"keyArgument": 2, "valueArgument": 3}])
        row = expression["arguments"][1]
        self.assertEqual(row["type"], "Row")
        self.assertEqual([(c["name"], c["argumentIndex"]) for c in row["recordShape"]["components"]], [("count", 0), ("active", 1)])
        self.assertEqual(row["recordShape"]["constructorOverload"], "unresolved")
        self.assertFalse(result["coverage"]["businessPolicyComplete"])

    def test_shadowed_library_name_never_claims_standard_factory(self):
        source = "import java.util.Map; class Map {} class Rules { Object value=Map.of(Mode.A,2); }"
        expression = extract(source)["fragments"][0]["expression"]
        self.assertNotIn("collectionShape", expression)

    def test_switch_expression_grouped_labels_default_throw_and_block_yield(self):
        source = 'class Rules { int value(Mode mode) { return switch(mode) { case A,B -> 2; case C -> { int x=3; yield x; } default -> throw new IllegalStateException("private-note"); }; }}'
        result = extract(source)
        expression = result["fragments"][0]["expression"]
        self.assertEqual(expression["op"], "switch")
        self.assertEqual([v["name"] for v in expression["arms"][0]["labels"]], ["A", "B"])
        self.assertEqual(expression["arms"][1]["value"]["op"], "body_reference")
        self.assertTrue(any(row["category"] == "yield" for row in result["fragments"]))
        self.assertEqual(expression["arms"][2]["action"], "throw")
        self.assertNotIn("private-note", json.dumps(result))

    def test_switch_statement_preserves_label_context_and_fallthrough_uncertainty(self):
        result = extract("class Rules { void act(Mode mode) { switch(mode) { case A: one(); case B: two(); break; default: other(); } } }")
        second = calls(result, "two")[0]
        labels = [c for c in second["controlFlow"]["contexts"] if c["kind"] == "switch_case"]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(c["fallthroughPossible"] and c["logic"] == "ANY" for c in labels))

    def test_redacted_literal_identity_retains_equality_without_value_hash(self):
        result = extract('class Rules { int act(String mode) { return switch(mode) { case "alpha-private" -> check("alpha-private") ? 1 : 2; default -> check("beta-private") ? 3 : 4; }; } }')
        expression = result["fragments"][0]["expression"]
        first = expression["arms"][0]
        self.assertEqual(first["labels"][0]["opaqueLiteralId"], first["value"]["condition"]["arguments"][0]["opaqueLiteralId"])
        other = expression["arms"][1]["value"]["condition"]["arguments"][0]
        self.assertNotEqual(first["labels"][0]["opaqueLiteralId"], other["opaqueLiteralId"])
        encoded = json.dumps(result)
        self.assertNotIn("alpha-private", encoded)
        self.assertNotIn(hashlib.sha256(b"alpha-private").hexdigest(), encoded)

    def test_caller_cannot_bypass_literal_privacy_with_an_unverified_allowlist(self):
        source = 'class Rules { String mode="ACTIVE"; }'
        self.assertIsNone(extract(source)["fragments"][0]["expression"])
        with self.assertRaises(TypeError):
            extract(source, safe_symbolic_values=("ACTIVE",))

    def test_call_chain_rounding_and_method_reference_remain_source_bound(self):
        source = "class Rules { Object f(Object xs, Object amount, Object fee) { return xs.map(Row::amount).reduce(amount.subtract(fee).multiply(SCALE).divide(amount,18,RoundingMode.HALF_EVEN), Decimal::max); } }"
        result = extract(source)
        expression = result["fragments"][0]["expression"]
        self.assertEqual(expression["arguments"][1]["op"], "method_reference")
        divide = expression["arguments"][0]
        self.assertEqual(divide["arguments"][1]["value"], "18")
        self.assertEqual(divide["arguments"][2]["name"], "RoundingMode.HALF_EVEN")
        self.assertIn("method_reference_target_unresolved", result["fragments"][0]["unsupportedReasons"])

    def test_lambda_block_preserves_internal_guard_without_claiming_execution(self):
        source = "class Rules { void f() { future.whenComplete((value,error)-> { if(error!=null) { fail(); return; } save(value); send(); }); }}"
        result = extract(source)
        row = result["fragments"][0]
        body = row["expression"]["arguments"][0]["body"]
        self.assertEqual(body["op"], "body_reference")
        saved = calls(result, "save")[0]
        self.assertEqual(saved["controlFlow"]["owner"]["bodyId"], body["bodyId"])
        self.assertEqual(saved["controlFlow"]["contexts"][-1]["branch"], "false")
        self.assertEqual(len(calls(result, "send")), 1)
        self.assertIn("lambda_execution_unresolved", row["unsupportedReasons"])

    def test_dataflow_keeps_conditional_write_candidates_without_substitution(self):
        result = extract("class Rules { int f(boolean flag,int input) { int x=input; if(flag) x=2; x+=3; return x; } int g(int x) { return x; } }")
        returns = [r for r in result["fragments"] if r["category"] == "return"]
        read = returns[0]["dataFlow"]["reads"][0]
        self.assertEqual(len(read["precedingWriteCandidates"]), 3)
        self.assertEqual(returns[1]["dataFlow"]["reads"][0]["precedingWriteCandidates"], [])
        self.assertFalse(returns[0]["dataFlow"]["valueSubstitution"])
        self.assertEqual(returns[0]["expression"], {"op": "reference", "name": "x"})

    def test_explicit_duration_binding_is_distinct_from_guessed_names(self):
        source = "import java.time.Duration; class Rules { final Duration age=Duration.ofMillis(300); long countMillis=300; }"
        result = extract(source)
        self.assertEqual(result["fragments"][0]["unit"]["unit"], "millisecond")
        self.assertEqual(result["fragments"][1]["unit"]["status"], "UNKNOWN")
        shadowed = extract("import java.time.Duration; class Duration {} class Rules { Object age=Duration.ofMillis(300); }")
        self.assertEqual(shadowed["fragments"][0]["unit"]["status"], "UNKNOWN")

    def test_sensitive_assignment_receiver_hides_rhs_and_keeps_explicit_gap(self):
        result = extract("class Rules { void f() { secretBox.value=846221; } }")
        self.assertNotIn("846221", json.dumps(result))
        self.assertEqual(result["fragments"][0]["unsupportedReasons"], ["sensitive_value_redacted"])

    def test_long_callback_is_split_into_lossless_bounded_body_records(self):
        body = "".join(f"apply({i});" for i in range(180))
        source = "class Rules { void f() { future.thenRun(() -> {" + body + "}); }}"
        result = extract(source)
        outer = calls(result, "future.thenRun")[0]
        self.assertEqual(semantics.MAX_EXPRESSION_TOKENS, 512)
        self.assertEqual(outer["expression"]["arguments"][0]["body"]["op"], "body_reference")
        rows = calls(result, "apply")
        self.assertEqual(len(rows), 180)
        self.assertEqual([r["expression"]["arguments"][0]["value"] for r in rows], [str(i) for i in range(180)])
        self.assertTrue(result["coverage"]["inventoryComplete"])
        self.assertFalse(result["coverage"]["businessPolicyComplete"])
        self.assertFalse(any("expression_budget_exceeded" in r["unsupportedReasons"] for r in result["fragments"]))

    def test_nested_callback_partition_does_not_duplicate_children_or_disclose_secret_rhs(self):
        source = "class Rules { void f() { outer(() -> { first(); inner(() -> { secretBox.value=836527; last(); }); after(); }); }}"
        result = extract(source)
        for callee in ("outer", "first", "inner", "last", "after"):
            self.assertEqual(len(calls(result, callee)), 1)
        self.assertNotIn("836527", json.dumps(result))
        last = calls(result, "last")[0]
        ancestors = [c for c in last["controlFlow"]["contexts"] if c["kind"] == "embedded_body"]
        self.assertEqual(len(ancestors), 2)
        self.assertEqual(len({c["fragmentId"] for c in ancestors}), 2)

    def test_long_expression_without_partitionable_body_keeps_original_limit(self):
        source = "class Rules { int value=" + "+".join("1" for _ in range(300)) + "; }"
        result = extract(source)
        self.assertEqual(result["fragments"][0]["unsupportedReasons"], ["expression_budget_exceeded"])

    def test_multi_declarator_constants_and_generic_commas_keep_values_and_types(self):
        source = "class Rules { static final int FIRST=2, SECOND=3, THIRD; Map<A,B> first=Map.of(A.ONE,B.TWO), second=new Map<A,B>(); void f(){ int a=1,b=2; use(a+b); } }"
        rows = extract(source)["fragments"]
        named = {r.get("name"): r for r in rows if r.get("name")}
        self.assertEqual([named[n]["category"] for n in ("FIRST", "SECOND", "THIRD")], ["constant"]*3)
        self.assertEqual(named["SECOND"]["expression"]["value"], "3")
        self.assertEqual(named["THIRD"]["unsupportedReasons"], ["initializer_absent"])
        self.assertEqual(named["first"]["declaredType"], named["second"]["declaredType"])
        self.assertEqual(named["b"]["category"], "local_declaration")
        self.assertEqual(named["b"]["declaredType"], "int")

    def test_type_witness_and_array_construction_preserve_source_shape(self):
        source = "class Rules { Object a=Factory.<Map<A,B>>create(); int[] sizes=new int[]{2,3,4}; Object[][] cells=new Object[2][3]; }"
        rows = extract(source)["fragments"]
        self.assertEqual(rows[0]["expression"]["callee"]["name"], "Factory.create")
        self.assertTrue(rows[0]["expression"]["callee"]["typeArguments"])
        self.assertEqual([v["value"] for v in rows[1]["expression"]["initializer"]["elements"]], ["2", "3", "4"])
        self.assertEqual([v["value"] for v in rows[2]["expression"]["dimensions"]], ["2", "3"])

    def test_anonymous_class_body_and_field_are_separate_source_bound_records(self):
        source = "class Rules { void f() { Object action=new Action(){ final int count=3; @Override public void run(){ save(count); } }; after(); } }"
        result = extract(source)
        declared = next(r for r in result["fragments"] if r.get("name") == "action")
        self.assertEqual(declared["expression"]["anonymousBody"]["bodyKind"], "anonymous_class")
        self.assertEqual(len(calls(result, "save")), 1)
        field = next(r for r in result["fragments"] if r.get("name") == "count")
        self.assertEqual(field["category"], "constant")
        self.assertEqual(field["expression"]["value"], "3")
        self.assertIn("anonymous_class_semantics_unresolved", declared["unsupportedReasons"])

    def test_annotation_assignment_does_not_hide_class_or_nested_fields(self):
        source = '@Configuration(enabled=false) class Rules { final int count=3; static class Nested { int value; } void f() { apply(); } }'
        rows = extract(source)["fragments"]
        named = {r.get("name"): r for r in rows if r.get("name")}
        self.assertEqual(named["count"]["category"], "constant")
        self.assertEqual(named["value"]["category"], "field")
        self.assertEqual(named["value"]["unsupportedReasons"], ["initializer_absent"])

    def test_injected_helpers_support_standalone_module_loading(self):
        import importlib.util
        import sys
        from unittest import mock
        spec = importlib.util.spec_from_file_location("policy_semantic_injection_test", SCRIPTS / "policy_semantics.py")
        module = importlib.util.module_from_spec(spec)
        module.privacy_guard = semantics.privacy_guard
        module.policy_java_flow = semantics.policy_java_flow
        sys.modules[spec.name] = module
        source = "class Rules { void f() { run(() -> { done(); }); }}"
        try:
            with mock.patch.dict(sys.modules, {"policy_java_flow": None}):
                spec.loader.exec_module(module)
                result = module.extract_semantics(source, "Java", "Rules.java", hashlib.sha256(source.encode()).hexdigest())
            self.assertEqual(len(calls(result, "done")), 1)
        finally:
            sys.modules.pop(spec.name, None)

    def test_switch_abrupt_completion_removes_dead_fallthrough_candidates(self):
        for stop in ("break;", "return;", "throw failure;", "{ break; }"):
            source = "class Use { void run(int mode) { switch(mode) { case 1: first(); " + stop + " case 2: second(); break; default: fallback(); } } }"
            result = extract(source)
            labels = [r for r in result["fragments"] if (r.get("expression") or {}).get("op") == "switch_labels"]
            for callee, expected in (("first", labels[0]), ("second", labels[1]), ("fallback", labels[2])):
                contexts = [c for c in calls(result, callee)[0]["controlFlow"]["contexts"] if c["kind"] == "switch_case"]
                self.assertEqual([c["fragmentId"] for c in contexts], [expected["id"]])

    def test_nested_loop_break_does_not_cancel_outer_switch_fallthrough(self):
        result = extract("class Use { void run(int mode) { switch(mode) { case 1: while(active){ break; } first(); case 2: second(); } } }")
        contexts = [c for c in calls(result, "second")[0]["controlFlow"]["contexts"] if c["kind"] == "switch_case"]
        self.assertEqual(len(contexts), 2)

    def test_record_shape_requires_lexically_visible_unshadowed_record(self):
        sources = [
            "import outside.Row; class Other { record Row(int count, boolean active) {} } class Use { Object value=new Row(2,true); }",
            "record Row(int count, boolean active) {} class Use { class Row {} Object value=new Row(2,true); }",
            "class Other { private record Row(int count, boolean active) {} } class Use { Object value=new Other.Row(2,true); }",
        ]
        for source in sources:
            row = next(r for r in extract(source)["fragments"] if r.get("name") == "value")
            self.assertNotIn("recordShape", row["expression"])
        valid = extract("class Use { record Row(int count, boolean active) {} Object value=new Row(2,true); }")
        row = next(r for r in valid["fragments"] if r.get("name") == "value")
        self.assertEqual(row["expression"]["recordShape"]["binding"], "same_file_record_component_order")

    def test_qualified_library_bindings_respect_package_prefix_shadowing(self):
        sources = [
            "class Use { Object java; Object run() { return java.util.Map.of(1,2); } }",
            "class Use { Object run(Object java) { return java.util.Map.of(1,2); } }",
            "class Use { Object run() { Object java=other; return java.util.Map.of(1,2); } }",
            "class Use { Object java; Object run() { return java.time.Duration.ofMillis(300); } }",
            "class Use { Object run(Object java) { return java.time.Duration.ofSeconds(2); } }",
        ]
        for source in sources:
            row = next(r for r in extract(source)["fragments"] if r["category"] == "return")
            self.assertNotIn("collectionShape", row["expression"])
            self.assertNotIn("unitEvidence", row["expression"])
            self.assertEqual(row["unit"]["status"], "UNKNOWN")
        valid = extract("class Other { Object java; } class Use { Object run(){ return java.util.Map.of(1,2); } }")
        row = next(r for r in valid["fragments"] if r["category"] == "return")
        self.assertEqual(row["expression"]["collectionShape"]["binding"], "java.util.Map.of")

    def test_lambda_catch_and_for_shadowing_never_bind_to_outer_field(self):
        cases = [
            ("class Use { int value=4; Object run(Object stream) { return stream.map(value -> value+1); } }", "value"),
            ("class Use { int value=4; Object run(Object stream) { return stream.map(value -> { return value+1; }); } }", "value"),
            ("class Use { int error=4; void run() { try { work(); } catch(Exception error) { handle(error); } } }", "error"),
            ("class Use { int index=4; void run() { for(int index=0;index<3;index++) { handle(index); } } }", "index"),
            ("class Use { int item=4; void run() { for(Item item:items) handle(item); } }", "item"),
        ]
        for source, name in cases:
            rows = extract(source)["fragments"]
            refs = [ref for row in rows for ref in row["references"] if ref["name"] == name]
            self.assertTrue(refs)
            self.assertTrue(all(ref["resolution"] == "nested_scope_binding_unresolved" and not ref["declarations"] for ref in refs))

    def test_shadow_binder_ends_with_its_body_and_does_not_hide_following_field(self):
        source = "class Use { int index=4; void run(){ for(int index=0;index<2;index++) handle(index); after(index); } }"
        result = extract(source)
        inside = next(r for r in calls(result, "handle")[0]["references"] if r["name"] == "index")
        outside = next(r for r in calls(result, "after")[0]["references"] if r["name"] == "index")
        self.assertEqual(inside["resolution"], "nested_scope_binding_unresolved")
        self.assertEqual(outside["resolution"], "lexical_declaration_only")

    def test_qualified_this_never_resolves_to_enclosing_class_field(self):
        source = "class Base { int cap=7; } class Outer { int cap=2; class Inner extends Base { int read() { this.cap=9; return this.cap; } } }"
        result = extract(source)
        returned = next(r for r in result["fragments"] if r["category"] == "return")
        reference = next(r for r in returned["references"] if r["name"] == "this.cap")
        self.assertEqual(reference["resolution"], "unresolved")
        assigned = next(r for r in result["fragments"] if r["category"] == "assignment")
        self.assertEqual(assigned["dataFlow"]["writes"][0]["declarationIds"], [])

    def test_nested_lambda_preserves_its_definition_guard_without_duplicate_contexts(self):
        source = "class Use { void run() { outer(() -> { if(active) { inner(() -> { done(); }); } }); } }"
        result = extract(source)
        guard = next(r for r in result["fragments"] if r["category"] == "condition")
        done = calls(result, "done")[0]
        self.assertIn((guard["id"], "true"), [(c["fragmentId"], c["branch"]) for c in done["controlFlow"]["contexts"]])
        identities = [(c["fragmentId"], c["branch"]) for c in done["controlFlow"]["contexts"]]
        self.assertEqual(len(identities), len(set(identities)))

    def test_anonymous_body_counts_match_detected_and_recorded_descendants(self):
        source = "class Use { void run() { Object action=new Action(){ void work(){ done(); } }; } }"
        result = extract(source)
        anchor = next(r for r in result["fragments"] if (r.get("expression") or {}).get("op") == "embedded_body")
        descendants = [r for r in result["fragments"] if any(c["fragmentId"] == anchor["id"] for c in r["controlFlow"]["contexts"])]
        self.assertEqual(anchor["expression"]["memberCount"], len(descendants))
        self.assertEqual(anchor["expression"]["recordedMemberCount"], len(descendants))
        self.assertEqual(len(descendants), 1)

    def test_qualified_library_name_inside_lambda_parameter_scope_is_unknown(self):
        sources = [
            "class Use { Object run(Object stream){ return stream.map(java -> java.util.Map.of(1,2)); } }",
            "class Use { Object run(Object stream){ return stream.map(java -> { return java.time.Duration.ofMillis(2); }); } }",
        ]
        for source in sources:
            result = extract(source)
            encoded = json.dumps(result)
            self.assertNotIn("collectionShape", encoded)
            self.assertNotIn("unitEvidence", encoded)


if __name__ == "__main__":
    unittest.main()
