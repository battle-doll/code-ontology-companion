"""Synthetic standard API contracts; no application policy or runtime claims."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import code_ontology_core as core
import pipeline_java
import policy_semantics
import pipeline_delivery

IMPORTS = "import java.math.BigDecimal; import java.math.RoundingMode; import java.math.MathContext; import java.lang.Math; import java.time.Duration;\n"


def extract(source, others=None):
    digest = hashlib.sha256(source.encode()).hexdigest()
    facts = {"path": "Rules.java", "sourceDigest": digest, "module": "synthetic", "modulePath": ".", "records": []}
    index = core.build_java_index({"Rules.java": source, **(others or {})})
    pipeline_java.enrich(facts, index)
    result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest,
        java_type_context=pipeline_java.semantic_type_context(facts, index))
    return result, facts


def expression_result(expression, parameters="BigDecimal n, BigDecimal d, RoundingMode rounding, MathContext mc"):
    return extract(IMPORTS + "class Rules { Object calculate(" + parameters + ") { return " + expression + "; }}")[0]


def returns(result):
    return [f for f in result["fragments"] if f["category"] == "return"]


def bindings(row):
    pending, found = [row.get("expression")], []
    catalog = {c["id"]: c for c in row.get("standardApiContracts", [])}
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if "staticContract" in node:
                found.append((node, catalog[node["staticContract"]["contractId"]]))
            pending.extend(v for k, v in node.items() if k in {"callee", "receiver", "arguments", "left", "right", "body", "operand", "then", "else", "condition"})
        elif isinstance(node, list): pending.extend(node)
    return found


class JavaPolicyContractTests(unittest.TestCase):
    def test_pattern_and_resource_binders_do_not_gain_platform_contracts(self):
        cases = [
            'class Fake { Object max(int a,int b){return null;} } class Rules { Object f(Object x){if(x instanceof Fake Math) return Math.max(1,2); return null;}}',
            IMPORTS + 'class Fake { Object add(BigDecimal d){return null;} } class Rules { BigDecimal n; Object f(Object x,BigDecimal d){if(x instanceof Fake n) return n.add(d); return null;}}',
            'class Fake implements AutoCloseable { public void close(){} Object max(int a,int b){return null;} } class Rules { Object f(){try(Fake Math=new Fake()){return Math.max(1,2);}}}',
            'class Fake { Fake lang; Fake Math; Object max(int a,int b){return null;} } class Rules { Object f(Object x){if(x instanceof Fake java) return java.lang.Math.max(1,2); return null;}}',
            'class Fake { Object max(int a,int b){return null;} } class Rules { Object f(Object x){if(!(x instanceof Fake Math)) return null; return Math.max(1,2);}}',
            'class Rules { Object f(Object x){if(x instanceof Box(Fake Math)) return Math.max(1,2); return null;}}',
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertFalse(any(bindings(row) for row in extract(source)[0]['fragments']))

    def test_inherited_and_static_import_names_do_not_gain_platform_contracts(self):
        cases = [
            ('class Fake { long nanoTime(){return 0;} } class Base { Fake System; } class Rules extends Base { long f(){return System.nanoTime();}}', None),
            ('class Base { static class Math {static Object max(int a,int b){return null;}} } class Rules extends Base { Object f(){return Math.max(1,2);}}', None),
            ('class Root { Object Math; } class Middle extends Root {} class Rules extends Middle { Object f(){return Math.max(1,2);}}', None),
            ('class Rules extends NotSelected { Object f(){return Math.max(1,2);}}', None),
            ('import static sample.Values.Math; class Rules { Object f(){return Math.max(1,2);}}', {'Values.java':'package sample; public class Values { public static Object Math; }'}),
            ('import static sample.Values.*; class Rules { Object f(){return Math.max(1,2);}}', {'Values.java':'package sample; public class Values { public static Object Math; }'}),
            ('import static unselected.Values.*; class Rules { Object f(){return Math.max(1,2);}}', None),
        ]
        for source, others in cases:
            with self.subTest(source=source):
                self.assertFalse(any(bindings(row) for row in returns(extract(source, others)[0])))
        safe = 'class Base {} class Rules extends Base { Object f(){return Math.max(1,2);}}'
        self.assertEqual(bindings(returns(extract(safe)[0])[0])[0][1]['method'], 'max')
        safe = 'import static sample.Values.*; class Rules { Object f(){return Math.max(1,2);}}'
        self.assertTrue(bindings(returns(extract(safe, {'Values.java':'package sample; public class Values { public static int other; }'})[0])[0]))
        packaged = 'package example.nested; import java.math.BigDecimal; class Rules { Object f(BigDecimal n) {return n.abs().add(BigDecimal.ONE);} Object g(){return Math.max(1,2);} }'
        self.assertEqual(sum(len(bindings(row)) for row in returns(extract(packaged)[0])), 3)

    def test_future_lambda_contracts_preserve_distinct_stages_and_body(self):
        source = 'import java.util.concurrent.CompletableFuture; class Rules { Object f(CompletableFuture<String> raw) { return raw.whenComplete((value,error)->{ observe(value); }).thenApply(value->value).cancel(true); }}'
        result, _ = extract(source)
        pairs = {c['method']: (node,c) for node,c in bindings(returns(result)[0])}
        self.assertEqual(set(pairs), {'whenComplete','thenApply','cancel'})
        observer = pairs['whenComplete'][0]['staticContract']
        transform = pairs['thenApply'][0]['staticContract']
        self.assertNotEqual(observer['stageRelation']['receiver']['id'], observer['stageRelation']['dependent']['id'])
        self.assertEqual(transform['stageRelation']['receiver']['id'], observer['stageRelation']['dependent']['id'])
        self.assertNotEqual(transform['stageRelation']['receiver']['id'], transform['stageRelation']['dependent']['id'])
        self.assertIn(observer['callbackBinding']['bodyId'], {r['id'] for r in result['fragments']})
        self.assertEqual(transform['callbackBinding']['genericTypes'], 'UNKNOWN')
        self.assertEqual(pairs['cancel'][1]['rules']['mayInterruptIfRunning'], 'no_effect_in_standard_implementation')
        self.assertEqual(pairs['whenComplete'][1]['rules']['callbackTrigger'], 'receiver_normal_or_exceptional_completion')
        self.assertEqual(pairs['thenApply'][1]['rules']['callbackTrigger'], 'receiver_normal_completion')
        self.assertFalse(any(row['businessMeaningVerified'] for row in result['fragments']))

    def test_future_declared_callbacks_preserve_generics_but_reject_mismatch(self):
        prefix = 'import java.util.concurrent.CompletableFuture; import java.util.function.Function; import java.util.function.BiConsumer; '
        source = prefix + 'class Rules { Object f(CompletableFuture<String> raw, BiConsumer<String,Throwable> observer, Function<String,Integer> mapper) { return raw.whenComplete(observer).thenApply(mapper); }}'
        row = returns(extract(source)[0])[0]
        self.assertEqual(row['expression']['staticType']['typeArguments'], ['java.lang.Integer'])
        self.assertEqual(len(bindings(row)), 2)
        for callback in ('Function<Integer,Integer> fn', 'BiConsumer<Integer,Throwable> fn', 'Function<String,?> fn'):
            method = 'whenComplete' if callback.startswith('BiConsumer') else 'thenApply'
            source = prefix + 'class Rules { Object f(CompletableFuture<String> raw, ' + callback + ') {return raw.' + method + '(fn);}}'
            self.assertFalse(bindings(returns(extract(source)[0])[0]))

    def test_future_custom_shadow_or_unsupported_callback_remains_unknown(self):
        prefix = 'import java.util.concurrent.CompletableFuture; '
        cases = [
            prefix + 'class Rules { Object f(Object raw) { return raw.whenComplete((a,b)->a); }}',
            prefix + 'class CompletableFuture<T> {} class Rules { Object f(CompletableFuture<String> raw) { return raw.thenApply(a->a); }}',
            prefix + 'class Rules { Object f(CompletableFuture<String> raw) { return raw.whenComplete(a->a); }}',
            prefix + 'class Rules { Object f(CompletableFuture<String> raw) { return raw.thenApply((a,b)->a); }}',
            prefix + 'class Rules { Object f(CompletableFuture<String> raw) { return raw.thenApply((Integer a)->a); }}',
            prefix + 'class Rules { Object f(CompletableFuture<String> raw) { return raw.thenApply(this::transform); }}',
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_future_source_slots_join_initializers_without_claiming_runtime_alias(self):
        source = 'import java.util.concurrent.CompletableFuture; class Rules { Object f(CompletableFuture<String> raw) { raw.whenComplete((v,e)->observe(v)); CompletableFuture<String> dependent=raw.thenApply(v->v); return dependent.cancel(false); }}'
        result, _ = extract(source)
        initialized = next(row for row in result['fragments'] if row.get('name') == 'dependent')
        cancel = bindings(returns(result)[0])[0][0]['staticContract']
        self.assertEqual(cancel['stageReceiver']['id'], initialized['stageInitializer']['declarationStage']['id'])
        self.assertEqual(initialized['stageInitializer']['runtimeAliasAnalysis'], 'UNKNOWN')
        stages = [node['staticContract']['stageRelation'] for row in result['fragments'] for node, contract in bindings(row) if contract['method'] in {'whenComplete','thenApply'}]
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[0]['receiver']['id'], stages[1]['receiver']['id'])
        self.assertNotEqual(stages[0]['dependent']['id'], stages[1]['dependent']['id'])

    def test_future_chain_reuses_catalog_with_bounded_wire_size(self):
        source = 'import java.util.concurrent.CompletableFuture; class Rules { Object f(CompletableFuture<String> raw) {return raw' + '.thenApply(v->v)' * 40 + ';}}'
        row = returns(extract(source)[0])[0]
        self.assertEqual(len(bindings(row)), 40)
        self.assertEqual(len(row['standardApiContracts']), 1)
        self.assertLess(len(json.dumps(pipeline_delivery.normalize_response({'records':[row]})).encode()), 256 * 1024)

    def test_parameter_bound_division_chain_has_source_symbols_and_scale(self):
        source = IMPORTS + "class Rules { BigDecimal ratio(BigDecimal n, BigDecimal d) { return n.divide(d, 4, RoundingMode.HALF_UP).multiply(BigDecimal.TEN); }}"
        result, facts = extract(source)
        row = returns(result)[0]
        pairs = bindings(row)
        self.assertEqual({c["operation"] for _, c in pairs}, {"decimal_divide", "decimal_multiply"})
        division = next(c for _, c in pairs if c["method"] == "divide")
        self.assertEqual(division["parameterTypes"], ["java.math.BigDecimal", "int", "java.math.RoundingMode"])
        self.assertEqual(division["rules"]["scaleArgument"], 1)
        self.assertEqual(division["rules"]["roundingArgument"], 2)
        symbol = next(r for r in facts["records"] if r.get("name") == "ratio" and r.get("kind") == "symbol")
        for node, contract in pairs:
            self.assertIn(symbol["id"], node["staticContract"]["sourceEvidenceIds"])
            self.assertEqual(contract["runtimeDispatch"], "UNKNOWN")
            self.assertEqual(contract["executionSuccess"], "UNKNOWN")
        self.assertEqual(row["representationStatus"], "partial")
        self.assertFalse(row["businessMeaningVerified"])
        self.assertIn("call_semantics_unresolved", row["unsupportedReasons"])

    def test_decimal_overloads_preserve_scale_rounding_and_exceptions(self):
        cases = [
            ("n.divide(d)", ["java.math.BigDecimal"], "exact"),
            ("n.divide(d, mc)", ["java.math.BigDecimal", "java.math.MathContext"], "math_context"),
            ("n.divide(d, rounding)", ["java.math.BigDecimal", "java.math.RoundingMode"], "argument"),
            ("n.divide(d, 2)", ["java.math.BigDecimal", "int"], "argument"),
            ("n.divide(d, 3, 2)", ["java.math.BigDecimal", "int", "int"], "argument"),
            ("n.divide(d, 3, rounding)", ["java.math.BigDecimal", "int", "java.math.RoundingMode"], "argument"),
            ("n.setScale(3)", ["int"], "exact"),
            ("n.setScale(3, 2)", ["int", "int"], "argument"),
            ("n.setScale(3, rounding)", ["int", "java.math.RoundingMode"], "argument"),
        ]
        for expression, signature, rounding in cases:
            with self.subTest(expression=expression):
                contract = bindings(returns(expression_result(expression))[0])[0][1]
                self.assertEqual(contract["parameterTypes"], signature)
                self.assertEqual(contract["rules"]["rounding"], rounding)
                self.assertIn("java.lang.ArithmeticException", contract["exceptionConditions"])
                if signature[-1] == "int" and len(signature) >= 2:
                    self.assertIn("java.lang.IllegalArgumentException", contract["exceptionConditions"])

    def test_decimal_arithmetic_comparison_unary_catalog(self):
        cases = {"n.add(d)": "decimal_add", "n.subtract(d,mc)": "decimal_subtract",
                 "n.multiply(d,mc)": "decimal_multiply", "n.compareTo(d)": "decimal_compare",
                 "n.min(d)": "decimal_min", "n.max(d)": "decimal_max", "n.signum()": "decimal_sign",
                 "n.abs()": "decimal_abs", "n.abs(mc)": "decimal_abs", "n.negate()": "decimal_negate", "n.negate(mc)": "decimal_negate"}
        for expression, operation in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(bindings(returns(expression_result(expression))[0])[0][1]["operation"], operation)

    def test_math_widening_selects_most_specific_supported_overload(self):
        cases = {"Math.max(1, 2L)": ("long", ["long", "long"]), "Math.min(1, 2.0)": ("double", ["double", "double"]),
                 "Math.abs(2.0f)": ("float", ["float"]), "Math.multiplyExact(2L, 3)": ("long", ["long", "int"]),
                 "Math.round(2.0f)": ("int", ["float"]), "Math.floor(2.0)": ("double", ["double"])}
        for expression, (result_type, params) in cases.items():
            with self.subTest(expression=expression):
                contract = bindings(returns(expression_result(expression))[0])[0][1]
                self.assertEqual(contract["parameterTypes"], params)
                self.assertEqual(contract["result"]["type"], result_type)

    def test_duration_unit_conversion_and_overflow(self):
        result = expression_result("Duration.ofSeconds(2).plus(Duration.ofMillis(300)).toMillis()")
        found = {c["method"]: c for _, c in bindings(returns(result)[0])}
        self.assertEqual(found["ofSeconds"]["parameterTypes"], ["long"])
        self.assertEqual(found["toMillis"]["rules"]["unit"], "millisecond")
        self.assertEqual(found["toMillis"]["rules"]["precision"], "truncate_toward_zero")
        self.assertIn("long_overflow", found["toMillis"]["exceptionConditions"]["java.lang.ArithmeticException"])
        for expr, result_type in (("span.dividedBy(2)", "java.time.Duration"), ("span.dividedBy(other)", "long")):
            contract = bindings(returns(expression_result(expr, "Duration span, Duration other"))[0])[0][1]
            self.assertEqual(contract["result"]["type"], result_type)

    def test_unknown_or_custom_receivers_do_not_gain_arithmetic(self):
        sources = ["class Rules { Object f(Custom n, Custom d) { return n.add(d); }}",
                   IMPORTS + "class Custom extends BigDecimal { Custom(){super(1);} } class Rules { Object f(Custom n, BigDecimal d) { return n.add(d); }}",
                   IMPORTS + "class Rules { Object f(Object n, BigDecimal d) { return n.add(d); }}"]
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_shadowed_platform_heads_and_type_variables_fail_closed(self):
        cases = [
            "class Rules { Object f(Object java) { return java.lang.Math.max(1,2); }}",
            IMPORTS + "class Rules { Object f(Object Math) { return Math.max(1,2); }}",
            IMPORTS + "class Rules { class BigDecimal {} Object f(BigDecimal n, BigDecimal d) { return n.add(d); }}",
            IMPORTS + "class Rules { <BigDecimal> Object f(BigDecimal n, BigDecimal d) { return n.add(d); }}",
            IMPORTS + "class Rules { Object f(Object BigDecimal) { return BigDecimal.valueOf(2); }}",
            IMPORTS + "class Rules { Object java; Object f() { return java.time.Duration.ofSeconds(1); }}",
            IMPORTS + "class Rules { Object Math; Object f() { return stream.map(Math -> Math.max(1,2)); }}",
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_nested_binder_never_reuses_outer_decimal(self):
        for body in ("return stream.map(n -> n.add(d));", "stream.accept(n -> { n.add(d); });", "for(Object n: items) { n.add(d); }"):
            result, _ = extract(IMPORTS + "class Rules { BigDecimal n; Object f(BigDecimal d) { " + body + " }}")
            self.assertFalse(any(bindings(row) for row in result["fragments"]))

    def test_unresolved_overload_and_null_never_become_exact(self):
        for expression in ("n.divide(d,null)", "n.divide(d,2L)", "n.add(other)", "n.setScale(2,other)", "Math.max(1,null)"):
            with self.subTest(expression=expression):
                self.assertEqual(bindings(returns(expression_result(expression))[0]), [])

    def test_lexical_locals_fields_and_this_have_declared_types(self):
        result, _ = extract(IMPORTS + "class Rules { BigDecimal value; Object f(BigDecimal d) { BigDecimal local=d; return this.value.add(local); }}")
        pair = bindings(returns(result)[0])[0]
        self.assertEqual(pair[1]["operation"], "decimal_add")
        self.assertTrue(any(e.startswith("semantic:") for e in pair[0]["staticContract"]["sourceEvidenceIds"]))
        result, _ = extract(IMPORTS + "class Rules { BigDecimal value; class Inner extends Other { Object f(BigDecimal d) { return this.value.add(d); } }}")
        self.assertEqual(bindings(returns(result)[0]), [])

    def test_exact_factory_and_getter_return_type_requires_callsite_evidence(self):
        source = IMPORTS + "class Rules { BigDecimal make(BigDecimal n) { return n; } BigDecimal get() { return BigDecimal.ONE; } Object f(BigDecimal n) { return make(n).add(get()); }}"
        result, facts = extract(source)
        row = returns(result)[-1]
        pairs = bindings(row)
        self.assertEqual(len(pairs), 1)
        source_calls = {r["id"] for r in facts["records"] if r["kind"] == "callsite"}
        self.assertTrue(set(pairs[0][0]["staticContract"]["sourceEvidenceIds"]) & source_calls)
        self.assertEqual(pairs[0][0]["callee"]["receiver"]["staticType"]["evidenceKinds"], ["callsite", "symbol"])

    def test_ambiguous_factory_stays_unknown_and_record_accessor_has_type_evidence(self):
        source = IMPORTS + "class Rules { BigDecimal make(String x) { return BigDecimal.ONE; } BigDecimal make(Integer x) { return BigDecimal.ZERO; } Object f() { return make(null).abs(); }}"
        self.assertEqual(bindings(returns(extract(source)[0])[-1]), [])
        source = IMPORTS + "record Row(BigDecimal value) {} class Rules { Object f(Row row) { return row.value().abs(); }}"
        pairs = bindings(returns(extract(source)[0])[-1])
        self.assertEqual(pairs[0][1]["method"], "abs")
        self.assertEqual(pairs[0][0]["callee"]["receiver"]["staticAccessorBinding"]["kind"], "implicit_component_accessor")

    def test_abstract_methods_and_interface_headers_do_not_crash_context(self):
        result, _ = extract(IMPORTS + "interface Contract { BigDecimal calc(BigDecimal n); default BigDecimal f(BigDecimal n) { return n.abs(); }}")
        self.assertEqual(bindings(returns(result)[0])[0][1]["operation"], "decimal_abs")

    def test_no_context_is_no_contract_and_inventory_does_not_change(self):
        source = IMPORTS + "class Rules { Object f(BigDecimal n, BigDecimal d) { return n.divide(d); }}"
        enriched, _ = extract(source)
        plain = policy_semantics.extract_semantics(source, "Java", "Rules.java", hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(enriched["coverage"], plain["coverage"])
        self.assertEqual([f["id"] for f in enriched["fragments"]], [f["id"] for f in plain["fragments"]])
        self.assertNotIn("standardApiContracts", plain["fragments"][0])

    def test_metadata_never_exposes_opaque_strings_or_sensitive_values(self):
        result = expression_result('n.add(read("private-test-vocabulary"))')
        self.assertNotIn("private-test-vocabulary", json.dumps(result))
        self.assertFalse(bindings(returns(result)[0]))

    def test_repeated_chain_reuses_catalog_and_stays_within_delivery_budgets(self):
        row = returns(expression_result("n" + ".abs()" * 100))[0]
        self.assertEqual(len(bindings(row)), 100)
        self.assertEqual(len(row["standardApiContracts"]), 1)
        encoded = json.dumps(row, separators=(",", ":")).encode()
        self.assertLess(len(encoded), 256 * 1024)
        # Exercise actual delivery normalization, retaining every call.
        response = pipeline_delivery.normalize_response({"records": [row]})
        self.assertLess(len(json.dumps(response).encode()), 256 * 1024)

    def test_implicit_math_and_shadowed_or_static_import_alternatives(self):
        row = returns(extract("class Rules { long f() { return Math.max(1,2L); }}")[0])[0]
        self.assertEqual(bindings(row)[0][1]["declaringType"], "java.lang.Math")
        cases = [
            ("package sample; class Rules { Object f() { return Math.max(1,2); }}", {"Math.java": "package sample; class Math { static Object max(int a,int b) { return null; }}"}),
            ("class Rules { Object Math; Object f() { return Math.max(1,2); }}", {}),
            ("import static java.lang.Math.max; class Rules { int f() { return max(1,2); }}", {}),
            ("class Rules<java> { Object f() { return java.lang.Math.max(1,2); }}", {}),
        ]
        for source, others in cases:
            with self.subTest(source=source):
                self.assertEqual(bindings(returns(extract(source, others)[0])[-1]), [])

    def test_constructor_chain_requires_known_overload(self):
        cases = [("new BigDecimal(2L).abs()", True), ("new BigDecimal(2.0).negate()", True),
                 ("new BigDecimal(other).abs()", False), ("new BigDecimal(2) { }.abs()", False)]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                found = bindings(returns(expression_result(expression))[0])
                self.assertEqual(bool(found), expected)
                if expected:
                    self.assertIn("staticConstructorBinding", found[0][0]["callee"]["receiver"])

    def test_factory_return_shadow_and_nested_argument_binding_fail_closed(self):
        source = IMPORTS + "class Rules { class BigDecimal {} BigDecimal get() { return null; } Object f() { return get().abs(); }}"
        self.assertEqual(bindings(returns(extract(source)[0])[-1]), [])
        source = IMPORTS + "class Rules { BigDecimal n; BigDecimal make(BigDecimal n) { return n; } Object make(Object n) { return n; } Object f() { return stream.map(n -> make(n).abs()); }}"
        self.assertEqual(bindings(returns(extract(source)[0])[-1]), [])

    def test_named_standard_constants_carry_specification_rules_only(self):
        row = returns(expression_result("n.divide(d,2,RoundingMode.HALF_EVEN).add(BigDecimal.ONE,MathContext.DECIMAL64)"))[0]
        outer = row["expression"]
        self.assertEqual(outer["arguments"][0]["standardConstant"]["value"], 1)
        self.assertEqual(outer["arguments"][1]["standardConstant"]["precision"], 16)
        self.assertEqual(outer["callee"]["receiver"]["arguments"][2]["standardConstant"]["roundingRule"], "nearest_ties_even")

    def test_parameter_scope_body_position_constant_and_typed_arrays(self):
        source = IMPORTS + "class Rules { static final int DIGITS=3; BigDecimal f(BigDecimal n, BigDecimal d) { return n.divide(d,DIGITS,RoundingMode.DOWN); } Object f(BigDecimal[] n, BigDecimal d) { return n.add(d); }}"
        result, _ = extract(source)
        rows = returns(result)
        self.assertEqual(len(bindings(rows[0])), 1)
        self.assertEqual(len(bindings(rows[1])), 0)

    def test_mismatched_context_rejected_without_source_data_in_error(self):
        source = "class Rules {}"
        digest = hashlib.sha256(source.encode()).hexdigest()
        for context in ({"path": "Else.java"}, object()):
            with self.assertRaisesRegex(policy_semantics.SemanticError, "java_type_context_binding_mismatch"):
                policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, java_type_context=context)

    def test_instant_api_contracts_preserve_units_order_and_exception_classes(self):
        source = "import java.time.Instant; class Rules { boolean f(Instant start, Instant end) { return start.plusMillis(-2L).plusSeconds(3).isBefore(end); }}"
        row = returns(extract(source)[0])[0]
        by_name = {c["method"]: c for _, c in bindings(row)}
        self.assertEqual(set(by_name), {"plusMillis", "plusSeconds", "isBefore"})
        self.assertEqual(by_name["isBefore"]["rules"]["comparison"], "strict_timeline_order")
        self.assertEqual(by_name["plusMillis"]["rules"]["unit"], "millisecond")
        self.assertEqual(by_name["plusSeconds"]["parameterTypes"], ["long"])
        for name in ("plusMillis", "plusSeconds"):
            self.assertIn("java.time.DateTimeException", by_name[name]["exceptionConditions"])
            self.assertIn("java.lang.ArithmeticException", by_name[name]["exceptionConditions"])

    def test_time_unit_enum_receiver_scales_signed_values_and_saturates(self):
        for member, factor in (("SECONDS", 1000000000), ("MILLISECONDS", 1000000), ("DAYS", 86400000000000)):
            with self.subTest(member=member):
                source = "import java.util.concurrent.TimeUnit; class Rules { long f(long count) { return TimeUnit." + member + ".toNanos(-count); }}"
                row = returns(extract(source)[0])[0]
                expression, contract = bindings(row)[0]
                self.assertEqual(expression["callee"]["receiverStandardConstant"]["nanosecondsPerUnit"], factor)
                self.assertEqual(contract["rules"]["overflow"], {"negative": "java.lang.Long.MIN_VALUE", "positive": "java.lang.Long.MAX_VALUE"})
                self.assertNotIn("java.lang.ArithmeticException", contract["exceptionConditions"])
                self.assertEqual(contract["rules"]["precisionLoss"], "none_before_saturation")
        source = "import java.util.concurrent.TimeUnit; class Rules { long f(TimeUnit unit, long count) { return unit.toNanos(count); }}"
        expression, contract = bindings(returns(extract(source)[0])[0])[0]
        self.assertNotIn("receiverStandardConstant", expression["callee"])
        self.assertEqual(contract["rules"]["inputUnit"], "receiver_enum_unit")

    def test_nano_time_means_elapsed_arbitrary_origin_without_observed_value(self):
        row = returns(extract("class Rules { long f() { return System.nanoTime(); }}")[0])[0]
        expression, contract = bindings(row)[0]
        self.assertEqual(contract["rules"]["origin"], "arbitrary_per_jvm_not_epoch")
        self.assertEqual(contract["rules"]["strictlyIncreasing"], "not_guaranteed")
        self.assertEqual(contract["runtimeValue"], "UNKNOWN")
        self.assertEqual(expression["staticType"]["name"], "long")

    def test_time_api_shadowing_and_wrong_arguments_never_gain_contracts(self):
        sources = [
            "import java.util.concurrent.TimeUnit; class Rules { Object TimeUnit; long f() { return TimeUnit.SECONDS.toNanos(1); }}",
            "class Rules { Object System; long f() { return System.nanoTime(); }}",
            "class Rules { long f(Object java) { return java.lang.System.nanoTime(); }}",
            "import java.time.Instant; class Rules { Object f(Instant t) { return t.plusSeconds(1.5); }}",
            "import java.util.concurrent.TimeUnit; class Rules { Object f() { return TimeUnit.SECONDS.toNanos(1.5); }}",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(bindings(returns(extract(source)[0])[0]))


if __name__ == "__main__":
    unittest.main()
