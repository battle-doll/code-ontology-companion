"""Neutral source-type bridges; no application text or runtime assertions."""
import copy
import hashlib
import json
import unittest

from test_policy_java_contracts import extract, returns, bindings, core, pipeline_java, policy_semantics, pipeline_delivery
from test_policy_literal_review import walk

BD = "java.math.BigDecimal"
PREFIX = "import java.math.BigDecimal; import static java.math.BigDecimal.ZERO; "
RECORD = "record Amount(java.math.BigDecimal left,java.math.BigDecimal right) {} "


def methods(row):
    return {contract["method"] for _, contract in bindings(row)}


class AmountCaseTests(unittest.TestCase):
    def test_imported_constant_completes_identical_conditional_type(self):
        source = PREFIX + "class AmountCase {BigDecimal select(){return ZERO;} Object f(boolean active){return (active ? select() : ZERO).add(BigDecimal.ONE).subtract(ZERO).min(BigDecimal.TEN).max(ZERO);}}"
        row = returns(extract(source)[0])[-1]
        self.assertEqual(methods(row), {"add", "subtract", "min", "max"})
        conditional = next(n for n in walk(row) if n.get("op") == "conditional")
        self.assertEqual(conditional["staticType"]["basis"], "identical_conditional_operand_types")
        self.assertEqual(conditional["then"]["staticType"]["basis"], "exact_source_call_return_declaration")
        for node in walk(row):
            constant = node.get("standardConstant", {})
            if constant.get("sourceImport"):
                proof = constant["sourceImport"]
                span = proof["sourceRange"]
                self.assertEqual(source[span["charStart"]:span["charEnd"]], "import static java.math.BigDecimal.ZERO;")
                self.assertEqual(proof["sourceDigest"], hashlib.sha256(source.encode()).hexdigest())
                self.assertEqual(proof["runtimeValue"], "UNKNOWN")
        self.assertFalse(row["businessMeaningVerified"])

    def test_duplicate_identical_static_import_keeps_single_binding(self):
        source = PREFIX + "import static java.math.BigDecimal.ZERO; class AmountCase {Object f(){return ZERO.abs();}}"
        row = returns(extract(source)[0])[0]
        self.assertEqual(methods(row), {"abs"})
        proof = row["expression"]["callee"]["receiverStandardConstant"]["sourceImport"]
        self.assertEqual(proof["identicalDeclarationCount"], 2)

    def test_static_import_precedence_and_wildcard_ambiguity(self):
        cases = [
            ("import static java.math.BigDecimal.*;", True),
            ("import static java.math.BigDecimal.*; import static java.math.MathContext.*;", True),
            ("import static java.math.BigDecimal.ZERO; import static unknown.Owner.*;", True),
            ("import static java.math.BigDecimal.*; import static unknown.Owner.*;", False),
            ("import static java.math.BigDecimal.*; import static java.time.Duration.*;", False),
            ("import static java.math.BigDecimal.ZERO; import static java.time.Duration.ZERO;", False),
            ("import static unknown.Owner.ZERO;", False),
            ("import static java.math.BigDecimal.ZERO; import static unknown.Owner.ZERO;", False),
        ]
        for imports, expected in cases:
            with self.subTest(imports=imports):
                row = returns(extract(imports + "class AmountCase {Object f(){return ZERO.abs();}}")[0])[0]
                self.assertEqual(methods(row), {"abs"} if expected else set())

    def test_imported_constant_value_type_and_pattern_shadows_fail_closed(self):
        bodies = [
            "Object f(Object ZERO){return ZERO.abs();}",
            "Object ZERO;Object f(){return ZERO.abs();}",
            "<ZERO> Object f(){return ZERO.abs();}",
            "class ZERO {} Object f(){return ZERO.abs();}",
            "Object f(){Object ZERO;return ZERO.abs();}",
            "Object f(Object x){if(x instanceof Fake ZERO)return ZERO.abs();return null;}",
            "Object f(){return stream.map(ZERO -> ZERO.abs());}",
            "Object f(){try(Fake ZERO = open()){return ZERO.abs();}}",
            "Object f(){for(Fake ZERO:items){return ZERO.abs();}return null;}",
        ]
        for body in bodies:
            with self.subTest(body=body):
                result, _ = extract(PREFIX + "class AmountCase {" + body + "}")
                self.assertFalse(any(bindings(r) for r in returns(result)))
        for base in ("class Base {Object ZERO;}", "class Base extends Unknown {}"):
            result, _ = extract(PREFIX + base + "class AmountCase extends Base {Object f(){return ZERO.abs();}}")
            self.assertFalse(any(bindings(r) for r in returns(result)))

    def test_local_same_typed_value_is_not_the_imported_constant(self):
        row = returns(extract(PREFIX + "class AmountCase {Object f(BigDecimal ZERO){return ZERO.abs();}}")[0])[0]
        self.assertEqual(methods(row), {"abs"})
        self.assertFalse(any(n.get("standardConstant") or n.get("receiverStandardConstant") for n in walk(row)))

    def test_unequal_conditional_types_do_not_gain_decimal_contract(self):
        row = returns(extract(PREFIX + "class AmountCase {Object f(boolean active){return (active ? 1 : ZERO).abs();}}")[0])[0]
        self.assertEqual(methods(row), set())
        self.assertNotIn("staticType", next(n for n in walk(row) if n.get("op") == "conditional"))

    def test_source_platform_impostor_does_not_gain_imported_constant(self):
        row = returns(extract("import static java.math.BigDecimal.ZERO; class AmountCase {Object f(){return ZERO.abs();}}",
            {"BigDecimal.java": "package java.math; public class BigDecimal {public static BigDecimal ZERO; Object abs(){return null;}}"})[0])[0]
        self.assertEqual(methods(row), set())
        self.assertFalse(any(n.get("standardConstant") or n.get("receiverStandardConstant") for n in walk(row)))


class CollectionCaseTests(unittest.TestCase):
    def test_explicit_record_binder_supports_implicit_accessors(self):
        source = RECORD + "class CollectionCase {Object f(java.util.List<Amount> amounts){for(final Amount amount:amounts){return amount.left().add(amount.right());}return null;}}"
        row = returns(extract(source)[0])[0]
        self.assertEqual(methods(row), {"add"})
        scopes = [n["receiverStaticType"]["variableScope"] for n in walk(row) if n.get("receiverStaticType", {}).get("variableScope")]
        self.assertTrue(scopes)
        for scope in scopes:
            self.assertTrue(source[scope["charStart"]:scope["charEnd"]].startswith("{return"))
            self.assertNotIn(":amounts", source[scope["charStart"]:scope["charEnd"]])

    def test_existing_exact_zero_arg_method_return_is_reused_for_proven_receiver(self):
        source = "record Amount(java.math.BigDecimal left,java.math.BigDecimal right){java.math.BigDecimal total(){return left.add(right);}} class CollectionCase{Object f(java.util.List<Amount> amounts){for(Amount amount:amounts){return amount.total().abs();}return null;}}"
        rows = returns(extract(source)[0])
        self.assertEqual(methods(rows[0]), {"add"})
        self.assertEqual(methods(rows[1]), {"abs"})
        typed_call = rows[1]["expression"]["callee"]["receiver"]
        self.assertEqual(typed_call["staticType"]["basis"], "exact_source_call_return_declaration")
        self.assertNotIn("staticAccessorBinding", typed_call)

    def test_component_bare_and_this_field_types_keep_source_binding(self):
        for expression in ("left.add(right)", "this.left.add(this.right)"):
            source = "record Amount(java.math.BigDecimal left,java.math.BigDecimal right){Object total(){return " + expression + ";}}"
            row = returns(extract(source)[0])[0]
            self.assertEqual(methods(row), {"add"})
            proofs = [n[key] for n in walk(row) for key in ("staticFieldBinding", "receiverStaticFieldBinding") if key in n]
            self.assertEqual({p["name"] for p in proofs}, {"left", "right"})
            for p in proofs:
                span = p["sourceRange"]
                self.assertTrue(source[span["charStart"]:span["charEnd"]].endswith(p["name"]))
                self.assertEqual(p["runtimeValue"], "UNKNOWN")

    def test_component_binding_rejects_static_constructor_and_nested_receivers(self):
        declarations = [
            "static Object f(){return left.add(right);}",
            "Amount{left.add(right);}",
            "Amount(java.math.BigDecimal left,java.math.BigDecimal right){this.left=left;this.right=right;this.left.add(this.right);}",
            "class Inner{Object f(){return left.add(right);}}",
            "Object f(){return new Object(){Object g(){return left.add(right);}};}",
        ]
        for declaration in declarations:
            result, _ = extract("record Amount(java.math.BigDecimal left,java.math.BigDecimal right){" + declaration + "}")
            self.assertFalse(any(n.get("staticFieldBinding") or n.get("receiverStaticFieldBinding") for row in result["fragments"] for n in walk(row)))

    def test_component_local_parameter_lambda_and_pattern_shadows(self):
        methods_to_check = [
            "Object f(Object left){return left.add(right);}",
            "Object f(){Object left;return left.add(right);}",
            "Object f(){return stream.map(left -> left.add(right));}",
            "Object f(Object value){if(value instanceof Fake left)return left.add(right);return null;}",
            "Object f(){for(Fake left:items){return left.add(right);}return null;}",
        ]
        for method in methods_to_check:
            result, _ = extract("record Amount(java.math.BigDecimal left,java.math.BigDecimal right){" + method + "}")
            self.assertFalse(any(bindings(row) for row in returns(result)))
        row = returns(extract("record Amount(java.math.BigDecimal left,java.math.BigDecimal right){Object f(Object left){return this.left.add(right);}}")[0])[0]
        self.assertEqual(methods(row), {"add"})

    def test_component_custom_array_generic_and_type_shadow_are_unknown(self):
        sources = [
            "class Amount {java.math.BigDecimal left,right;Object f(){return left.add(right);}}",
            "record Amount(java.math.BigDecimal[] left,java.math.BigDecimal[] right){Object f(){return left.add(right);}}",
            "record Amount<T>(T left,T right){Object f(){return left.add(right);}}",
            "import java.math.BigDecimal; record Amount(BigDecimal left,BigDecimal right){static class BigDecimal{} Object f(){return left.add(right);}}",
        ]
        for source in sources:
            self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_binder_scope_is_body_only_with_and_without_braces(self):
        for body in ("return amount.left().abs();", "{return amount.left().abs();}"):
            source = RECORD + "class CollectionCase{Object f(java.util.List<Amount> values){for(Amount amount:values)" + body + "return amount.left().abs();}}"
            rows = returns(extract(source)[0])
            self.assertEqual(methods(rows[0]), {"abs"})
            self.assertEqual(methods(rows[1]), set())
        source = "record Amount(java.math.BigDecimal left){java.math.BigDecimal total(){return left;}} class CollectionCase{Object f(java.util.List<Amount> values){for(Amount amount:values){amount.total();}return amount.total().abs();}}"
        self.assertEqual(methods(returns(extract(source)[0])[-1]), set())

    def test_iterable_and_after_loop_keep_outer_value_not_loop_type(self):
        source = RECORD + "class CollectionCase{java.math.BigDecimal amount;Object f(){for(Amount amount:items(amount.abs())){amount.left().abs();}return amount.abs();}}"
        result, _ = extract(source)
        loop = next(row for row in result["fragments"] if row.get("controlFlow", {}).get("kind") == "for")
        self.assertEqual(loop["expression"]["op"], "enhanced_for")
        self.assertEqual({c["method"] for c in loop.get("standardApiContracts", [])}, {"abs"})
        self.assertNotIn("unsupported_expression_syntax", loop["unsupportedReasons"])
        self.assertEqual(methods(returns(result)[0]), {"abs"})
        self.assertFalse(any(n.get("staticAccessorBinding") for n in walk(loop)))

    def test_unproven_loop_types_and_nested_shadows_are_unknown(self):
        cases = [
            RECORD + "class CollectionCase{Object f(){for(var amount:items){return amount.left().abs();}return null;}}",
            RECORD + "class CollectionCase{<Amount> Object f(){for(Amount amount:items){return amount.left().abs();}return null;}}",
            "record Amount<T>(T left){} class CollectionCase{Object f(){for(Amount<java.math.BigDecimal> amount:items){return amount.left().abs();}return null;}}",
            RECORD + "class CollectionCase{Object f(){for(Amount amount:items){return stream.map(amount -> amount.left().abs());}return null;}}",
            RECORD + "class CollectionCase{Object f(){for(Amount amount:items){Object amount;return amount.left().abs();}return null;}}",
        ]
        for source in cases:
            self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))


class TimeCaseTests(unittest.TestCase):
    def test_explicit_and_wildcard_time_types_link_exact_temporal_signature(self):
        for imports in ("import java.time.*;", "import java.time.Instant;import java.time.Duration;"):
            source = imports + "record Event(Instant observed){} class TimeCase{long f(Event event,Instant now,long bound){return Math.addExact(1L,Math.min(bound,Duration.between(event.observed(),now).toNanos()));}}"
            row = returns(extract(source)[0])[0]
            self.assertEqual(methods(row), {"addExact", "min", "between", "toNanos"})
            node, contract = next((node, c) for node, c in bindings(row) if c["method"] == "between")
            self.assertEqual(contract["signature"], "java.time.Duration#between(java.time.temporal.Temporal,java.time.temporal.Temporal):java.time.Duration")
            self.assertEqual({arg["actualType"] for arg in node["staticContract"]["operands"]}, {"java.time.Instant"})
            self.assertTrue(all(arg["conversion"]["kind"] == "widening_reference" for arg in node["staticContract"]["operands"]))
            self.assertIn("java.time.DateTimeException", contract["exceptionConditions"])
            self.assertIn("java.lang.ArithmeticException", contract["exceptionConditions"])
            self.assertIn("java.lang.NullPointerException", contract["exceptionConditions"])
            self.assertEqual(contract["runtimeValue"], "UNKNOWN")
            self.assertFalse(contract["exceptionConditionsComplete"])

    def test_declared_temporal_is_supported_without_runtime_dispatch_claim(self):
        source = "import java.time.Duration;import java.time.temporal.Temporal;class TimeCase{long f(Temporal start,Temporal end){return Duration.between(start,end).toNanos();}}"
        row = returns(extract(source)[0])[0]
        self.assertEqual(methods(row), {"between", "toNanos"})
        between = next(c for _, c in bindings(row) if c["method"] == "between")
        self.assertEqual(between["runtimeDispatch"], "UNKNOWN")

    def test_unknown_extra_wildcard_and_conflicting_time_imports_fail_closed(self):
        prefixes = ["import java.time.*;import unknown.*;", "import java.time.*;import static unknown.Owner.*;",
                    "import java.time.Instant;import other.Instant;import java.time.Duration;",
                    "import other.Instant;import java.time.Instant;import java.time.Duration;"]
        for prefix in prefixes:
            source = prefix + "record Event(Instant observed){} class TimeCase{Object f(Event event,Instant now){return Duration.between(event.observed(),now).toNanos();}}"
            self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_explicit_time_import_has_precedence_over_unknown_wildcard(self):
        source = "import java.time.Instant;import java.time.Duration;import unknown.*;record Event(Instant observed){} class TimeCase{Object f(Event e,Instant now){return Duration.between(e.observed(),now).toNanos();}}"
        self.assertEqual(methods(returns(extract(source)[0])[0]), {"between", "toNanos"})

    def test_source_types_type_parameters_and_value_heads_do_not_impersonate_time_api(self):
        cases = [
            "import java.time.*;class Instant{} class TimeCase{Object f(Instant start,Instant end){return Duration.between(start,end).toNanos();}}",
            "import java.time.*;class TimeCase{<Instant> Object f(Instant start,Instant end){return Duration.between(start,end).toNanos();}}",
            "import java.time.*;class TimeCase{Object f(Object Duration,Instant start,Instant end){return Duration.between(start,end).toNanos();}}",
            "class TimeCase{Object f(Object java,java.time.Instant start,java.time.Instant end){return java.time.Duration.between(start,end).toNanos();}}",
            "import java.time.*;class TimeCase{Object f(Instant[] start,Instant[] end){return Duration.between(start,end).toNanos();}}",
            "import java.time.*;class Temporal{} class TimeCase{Object f(Temporal start,Temporal end){return Duration.between(start,end).toNanos();}}",
        ]
        for source in cases:
            self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_wildcard_component_and_source_return_use_their_own_file_imports(self):
        declarations = {"Event.java": "package events;import java.time.*;public record Event(Instant observed){}",
                        "ClockValue.java": "package events;import java.time.*;public class ClockValue{public static Instant read(){return null;}}"}
        source = "class TimeCase{Object f(events.Event event){return java.time.Duration.between(event.observed(),events.ClockValue.read()).toNanos();}}"
        self.assertEqual(methods(returns(extract(source,declarations)[0])[0]), {"between", "toNanos"})


class C6EvidenceBoundaryTests(unittest.TestCase):
    def test_index_restores_outer_field_after_enhanced_for_body(self):
        prefix = "class OuterValue{String total(){return null;}} record Amount(java.math.BigDecimal cash){java.math.BigDecimal total(){return cash;}} "
        for body in ("{amount.total();}", "amount.total();"):
            source = prefix + "class CollectionCase{OuterValue amount;Object f(java.util.List<Amount> values){for(Amount amount:values)" + body + "return amount.total();}}"
            index = core.build_java_index({"Rules.java":source})
            calls = [c for c in index.calls["Rules.java"] if c["name"] == "total"]
            self.assertEqual([c.get("target") for c in calls], ["java:method:Amount#total()", "java:method:OuterValue#total()"])
            row = returns(extract(source)[0])[-1]
            self.assertEqual(row["expression"]["staticType"]["name"], "java.lang.String")

    def test_index_iterable_expression_uses_outer_value(self):
        source = "class OuterValue{java.util.List<Amount> items(){return null;}} record Amount(java.math.BigDecimal cash){void total(){}} class CollectionCase{OuterValue amount;void f(){for(Amount amount:amount.items()){amount.total();}}}"
        calls = core.build_java_index({"Rules.java":source}).calls["Rules.java"]
        self.assertEqual(next(c for c in calls if c["name"] == "items")["target"], "java:method:OuterValue#items()")
        self.assertEqual(next(c for c in calls if c["name"] == "total")["target"], "java:method:Amount#total()")

    def test_complex_unbraced_loop_statement_restores_outer_exact_binding(self):
        source = "class OuterValue{String total(){return null;}} record Amount(java.math.BigDecimal cash){java.math.BigDecimal total(){return cash;}} class CollectionCase{OuterValue amount;Object f(java.util.List<Amount> values,boolean active){for(Amount amount:values) if(active) amount.total();return amount.total();}}"
        calls = [c for c in core.build_java_index({"Rules.java":source}).calls["Rules.java"] if c["name"] == "total"]
        self.assertTrue(calls)
        self.assertEqual([c.get("target") for c in calls], ["java:method:Amount#total()", "java:method:OuterValue#total()"])

    def test_index_later_loop_and_other_method_do_not_reuse_previous_binder(self):
        source = "record Amount(java.math.BigDecimal cash){void total(){}} record Other(String label){void total(){}} class CollectionCase{void f(java.util.List<Amount> values,java.util.List<Other> others){for(Amount amount:values){amount.total();}for(Other amount:others){amount.total();}}void g(Other amount){amount.total();}}"
        calls = [c for c in core.build_java_index({"Rules.java":source}).calls["Rules.java"] if c["name"] == "total"]
        self.assertEqual([c.get("target") for c in calls], ["java:method:Amount#total()", "java:method:Other#total()", "java:method:Other#total()"])

    def test_semantic_projection_never_changes_index_calls_or_declaration_identities(self):
        sources = [
            PREFIX + "class AmountCase{Object f(){return ZERO.abs();}}",
            RECORD + "class CollectionCase{Object f(){for(Amount amount:items){return amount.left().abs();}return null;}}",
            "import java.time.*;record Event(Instant observed){} class TimeCase{Object f(Event event,Instant now){return Duration.between(event.observed(),now).toNanos();}}",
        ]
        for source in sources:
            digest = hashlib.sha256(source.encode()).hexdigest()
            index = core.build_java_index({"Rules.java": source})
            calls = copy.deepcopy(index.calls); method_ids = set(index.methods)
            parameter_refs = {key: copy.deepcopy(value["parameter_references"]) for key, value in index.methods.items()}
            facts = {"path":"Rules.java", "sourceDigest":digest,"module":"synthetic","modulePath":".","records":[]}
            pipeline_java.enrich(facts,index)
            policy_semantics.extract_semantics(source,"Java","Rules.java",digest,java_type_context=pipeline_java.semantic_type_context(facts,index))
            self.assertEqual(index.calls,calls)
            self.assertEqual(set(index.methods),method_ids)
            self.assertEqual({key:value["parameter_references"] for key,value in index.methods.items()},parameter_refs)

    def test_sensitive_structures_do_not_gain_constants_field_types_or_contracts(self):
        sources = [
            PREFIX + "class AmountCase{Object secretValue = ZERO.abs();}",
            "record Amount(java.math.BigDecimal secretLeft,java.math.BigDecimal right){Object f(){return secretLeft.add(right);}}",
            "import java.time.*;record Event(Instant secretObserved){} class TimeCase{Object f(Event event,Instant now){return Duration.between(event.secretObserved(),now).toNanos();}}",
        ]
        for source in sources:
            result,_ = extract(source)
            masked = [row for row in result["fragments"] if row.get("structuralOnly")]
            self.assertTrue(masked)
            for row in masked:
                self.assertFalse(any(any(key in n for key in ("staticType","standardConstant","staticFieldBinding","staticContract","receiverStaticType")) for n in walk(row)))

    def test_long_constant_chain_stays_within_existing_delivery_budget(self):
        source = PREFIX + "class AmountCase{Object f(){return ZERO" + ".add(ZERO)" * 24 + ";}}"
        row = returns(extract(source)[0])[0]
        self.assertEqual(len(bindings(row)),24)
        delivered = pipeline_delivery.normalize_response({"records":[row]})
        self.assertLess(len(json.dumps(delivered).encode()),256*1024)


if __name__ == "__main__":
    unittest.main()
