"""Synthetic source-bound goldens; fragment counts are never policy coverage."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import policy_semantics as semantics


def extract(source, **kwargs):
    return semantics.extract_semantics(source, "Java", "synthetic/Rules.java", hashlib.sha256(source.encode()).hexdigest(), **kwargs)


def by_name(result, name):
    return next(row for row in result["fragments"] if row.get("name") == name)


class PolicySemanticTests(unittest.TestCase):
    def test_exact_integer_threshold_and_conjunction_structure(self):
        result = extract("class Rules {\n static final int MINIMUM = 600;\n boolean accept(int amount, boolean active) {\n if (active && amount >= MINIMUM) return true;\n return false;\n }}")
        constant = by_name(result, "MINIMUM")
        self.assertEqual(constant["category"], "constant")
        self.assertEqual(constant["span"], {"lineStart": 2, "lineEnd": 2})
        self.assertEqual(constant["expression"], {"op": "literal", "type": "integer", "value": "600", "javaSuffix": None})
        condition = next(r for r in result["fragments"] if r["category"] == "condition")
        self.assertEqual(condition["expression"]["operator"], "&&")
        self.assertEqual(condition["expression"]["right"]["operator"], ">=")
        self.assertEqual(condition["representationStatus"], "represented")
        self.assertEqual({r["name"] for r in condition["references"]}, {"active", "amount", "MINIMUM"})
        self.assertTrue(all(r["resolution"] == "lexical_declaration_only" for r in condition["references"]))
        origin = next(r for r in condition["references"] if r["name"] == "MINIMUM")["declarations"][0]
        self.assertEqual(origin["id"], constant["id"])
        self.assertEqual(origin["sourceDigest"], result["sourceDigest"])

    def test_bigdecimal_numeric_constructor_and_call_chain_are_separate(self):
        source = 'import java.math.BigDecimal; class Rules { static final BigDecimal CAP = new BigDecimal("0.25"); BigDecimal cost(BigDecimal amount, BigDecimal fee) { return amount.multiply(CAP).subtract(fee); } }'
        result = extract(source)
        literal = by_name(result, "CAP")["expression"]
        self.assertEqual(literal, {"op": "literal", "type": "decimal", "value": "0.25", "binding": "java.math.BigDecimal.String"})
        returned = next(r for r in result["fragments"] if r["category"] == "return")
        self.assertEqual(returned["representationStatus"], "partial")
        self.assertEqual(returned["unsupportedReasons"], ["call_semantics_unresolved"])
        self.assertEqual(returned["expression"]["callee"]["name"], "subtract")
        self.assertEqual(returned["expression"]["callee"]["receiver"]["callee"]["name"], "amount.multiply")
        self.assertFalse(returned["businessMeaningVerified"])
        self.assertEqual(returned["unit"]["status"], "UNKNOWN")

    def test_unbound_or_shadowed_decimal_is_not_trusted(self):
        for header in ("", "import fake.BigDecimal;", "import java.math.*;", "import java.math.BigDecimal; class BigDecimal {}"):
            result = extract(header + ' class Rules { final BigDecimal CAP = new BigDecimal("0.25"); }')
            row = by_name(result, "CAP")
            self.assertIsNone(row["expression"])
            self.assertEqual(row["unsupportedReasons"], ["constructor_semantics_unresolved"])
        explicit = extract('class Rules { final java.math.BigDecimal CAP = new java.math.BigDecimal("0.25"); }')
        self.assertEqual(by_name(explicit, "CAP")["expression"]["value"], "0.25")

    def test_binary_arithmetic_precedence_and_ternary(self):
        result = extract("class Rules { int value(int x) { int total = x+3*2; return total > 10 ? total-1 : 0; }}")
        expression = by_name(result, "total")["expression"]
        self.assertEqual(expression["operator"], "+")
        self.assertEqual(expression["right"]["operator"], "*")
        returned = next(r for r in result["fragments"] if r["category"] == "return")
        self.assertEqual(returned["expression"]["op"], "conditional")
        self.assertEqual(returned["expression"]["then"]["operator"], "-")

    def test_field_local_and_assignment_distinction(self):
        result = extract("class Rules { int count; int value(int input) { int local = input; local += 2; return local; }}")
        self.assertEqual(by_name(result, "count")["category"], "field")
        self.assertEqual(by_name(result, "count")["unsupportedReasons"], ["initializer_absent"])
        self.assertEqual(by_name(result, "local")["category"], "local_declaration")
        update = next(r for r in result["fragments"] if r["category"] == "assignment")
        self.assertEqual(update["assignmentOperator"], "+=")

    def test_same_file_shadowing_uses_closest_declaration_without_value_substitution(self):
        result = extract("class Rules { int cap=2; int first(int cap) { return cap; } int second(int other) { return cap; }}")
        returns = [r for r in result["fragments"] if r["category"] == "return"]
        self.assertNotEqual(returns[0]["references"][0]["declarations"][0]["id"], returns[1]["references"][0]["declarations"][0]["id"])
        self.assertEqual(returns[1]["references"][0]["declarations"][0]["id"], by_name(result, "cap")["id"])
        self.assertEqual(returns[0]["expression"], {"op": "reference", "name": "cap"})

    def test_this_reference_ignores_unrelated_external_member(self):
        result = extract("class Rules { int cap=2; int value(Other other, int cap) { return this.cap+other.cap; }}")
        refs = next(r for r in result["fragments"] if r["category"] == "return")["references"]
        self.assertEqual(next(r for r in refs if r["name"] == "this.cap")["resolution"], "lexical_declaration_only")
        self.assertEqual(next(r for r in refs if r["name"] == "this.cap")["declarations"][0]["id"], by_name(result, "cap")["id"])
        self.assertEqual(next(r for r in refs if r["name"] == "other.cap")["resolution"], "unresolved")

    def test_units_are_never_inferred_from_names_or_method_spelling(self):
        result = extract("class Rules { int seconds=20; long deadlineMillis=30; Object deadline() { return Duration.ofSeconds(20); }}")
        self.assertTrue(all(row["unit"]["status"] == "UNKNOWN" for row in result["fragments"]))
        self.assertTrue(all(row["runtimeStatus"] == "not_observed" for row in result["fragments"]))

    def test_condition_with_external_state_keeps_partial_reason(self):
        result = extract("class Rules { boolean ready(State s) { if (s.isFinal() && s.quantity().compareTo(s.total()) == 0) return true; return false; }}")
        row = next(r for r in result["fragments"] if r["category"] == "condition")
        self.assertEqual(row["representationStatus"], "partial")
        self.assertEqual(row["expression"]["operator"], "&&")
        self.assertEqual(row["expression"]["right"]["operator"], "==")
        self.assertIn("call_semantics_unresolved", row["unsupportedReasons"])

    def test_sensitive_names_redact_numeric_and_boolean_values(self):
        source = 'import java.math.BigDecimal; class Rules { int apiKey=123456; boolean secretFlag=true; BigDecimal credential=new BigDecimal("1234.25"); int get(int password) { return password+2025; } }'
        result = extract(source)
        encoded = json.dumps(result)
        for value in ("123456", "1234.25", "2025"):
            self.assertNotIn(value, encoded)
        self.assertTrue(all(row.get("structuralOnly") and row["representationStatus"] == "partial" for row in result["fragments"]))
        self.assertTrue(all("sensitive_value_redacted" in row["unsupportedReasons"] for row in result["fragments"]))

    def test_arbitrary_string_and_character_values_never_enter_output(self):
        values = ("private-note", "member@example.invalid", "123456", "sensitive payload")
        for value in values:
            source = f'class Rules {{ String label="{value}"; }}'
            result = extract(source)
            self.assertNotIn(value, json.dumps(result))
            self.assertEqual(result["fragments"][0]["unsupportedReasons"], ["string_or_character_value_redacted"])
        result = extract("class Rules { char label='X'; }")
        self.assertEqual(result["fragments"][0]["expression"], None)

    def test_numeric_entropy_and_non_string_decimal_do_not_become_exact_literals(self):
        result = extract("class Rules { long value=123456789012345678L; }")
        self.assertIsNone(result["fragments"][0]["expression"])
        self.assertEqual(result["fragments"][0]["unsupportedReasons"], ["numeric_value_redacted"])
        for argument in ('"123456789012345678"', "0.1", "input"):
            source = "import java.math.BigDecimal; class Rules { BigDecimal value=new BigDecimal(" + argument + "); }"
            result = extract(source)
            row = result["fragments"][0]
            self.assertEqual(row["expression"]["op"], "construct")
            self.assertEqual(row["expression"]["resolution"], "syntax_only")
            self.assertIn("constructor_semantics_unresolved", row["unsupportedReasons"])
            self.assertNotIn("123456789012345678", json.dumps(result))

    def test_comments_and_string_impostors_do_not_create_fragments(self):
        source = '// if (false) return 9;\n class Rules { String text="if (false) return 8;"; /* final int GHOST=7; */ int present=3; }'
        result = extract(source)
        self.assertEqual(len(result["fragments"]), 2)
        self.assertFalse([r for r in result["fragments"] if r["category"] == "condition"])
        self.assertNotIn("GHOST", json.dumps(result))

    def test_control_boundaries_are_structured_without_runtime_claims(self):
        source = "class Rules { void go(int n) { for(int i=0;i<n;i++) { if(i==2) continue; } try { run(); } catch(Exception err) { throw err; } finally { done(); } } }"
        result = extract(source)
        rows = result["fragments"]
        self.assertEqual({r["controlFlow"]["kind"] for r in rows},
                         {"for", "if", "continue", "try", "statement", "catch", "throw", "finally"})
        self.assertTrue(all(r["span"]["lineStart"] >= 1 for r in rows))
        self.assertTrue(all(r["sourceDigest"] == result["sourceDigest"] for r in rows))
        self.assertTrue(all(r["runtimeStatus"] == "not_observed" for r in rows))
        self.assertIn("loop_execution_unresolved", rows[0]["unsupportedReasons"])

    def test_source_changes_invalidate_fragment_identity(self):
        first = extract("class Rules { int cap=1; }")
        second = extract("class Rules { int cap=2; }")
        self.assertNotEqual(first["sourceDigest"], second["sourceDigest"])
        self.assertNotEqual(first["fragments"][0]["id"], second["fragments"][0]["id"])
        self.assertEqual(first, extract("class Rules { int cap=1; }"))

    def test_fragment_limit_retains_original_detected_denominator(self):
        result = extract("class Rules { int a=1; int b=2; int c=3; }", max_fragments=1)
        self.assertEqual(result["coverage"]["detectedFragments"], 3)
        self.assertEqual(result["coverage"]["recordedFragments"], 1)
        self.assertEqual(len(result["omissions"]), 2)
        self.assertTrue(all(row["reason"] == "fragment_budget_exceeded" and row["span"]["lineStart"] == 1 for row in result["omissions"]))
        self.assertFalse(result["coverage"]["inventoryComplete"])
        self.assertIn("fragment_budget_exceeded", result["coverage"]["reasons"])
        self.assertEqual(result["coverage"]["wholePolicyDenominator"], "UNKNOWN")

    def test_fragment_perfection_never_becomes_business_policy_completeness(self):
        result = extract("class Rules { int cap=2; }")
        self.assertEqual(result["coverage"]["representedFragments"], 1)
        self.assertTrue(result["coverage"]["inventoryComplete"])
        self.assertFalse(result["coverage"]["complete"])
        self.assertFalse(result["coverage"]["semanticComplete"])
        self.assertFalse(result["coverage"]["businessPolicyComplete"])
        self.assertEqual(result["coverage"]["wholePolicyDenominator"], "UNKNOWN")

    def test_malformed_and_unterminated_input_retains_failure_region(self):
        for source, reason in [("class Rules {", "unbalanced_source_syntax"), ("class Rules { /*", "unterminated_comment"), ('class Rules { String x="bad;', "unterminated_literal")]:
            result = extract(source)
            self.assertEqual(result["coverage"]["reasons"], [reason])
            self.assertIn("unprocessedRegion", result["coverage"])
            self.assertFalse(result["coverage"]["inventoryComplete"])

    def test_invalid_identity_and_digest_are_rejected(self):
        source = "class Rules {}"
        digest = hashlib.sha256(source.encode()).hexdigest()
        for path in ("../escape.java", "/root/source.java", "C:\\source.java", "./source.java"):
            with self.assertRaises(semantics.SemanticError):
                semantics.extract_semantics(source, "Java", path, digest)
        with self.assertRaisesRegex(semantics.SemanticError, "source_digest_mismatch"):
            semantics.extract_semantics(source, "Java", "Rules.java", "0" * 64)

    def test_no_source_execution_import_or_read_occurs(self):
        source = "class Rules { int cap=2; }"
        with mock.patch("builtins.open", side_effect=AssertionError("source access forbidden")), mock.patch.object(Path, "read_text", side_effect=AssertionError("source access forbidden")), mock.patch.object(semantics.privacy_guard, "load_profile", return_value=None):
            result = extract(source)
        self.assertEqual(result["coverage"]["representedFragments"], 1)

    def test_non_java_is_explicitly_unsupported_by_fragment_extractor(self):
        source = "x=2"
        result = semantics.extract_semantics(source, "Python", "synthetic.py", hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(result["coverage"]["reasons"], ["unsupported_fragment_language"])
        self.assertEqual(result["coverage"]["wholePolicyDenominator"], "UNKNOWN")

    def test_depth_limit_is_reported_without_source_text(self):
        source = "class Rules { int cap=" + "(" * 80 + "1" + ")" * 80 + "; }"
        result = extract(source)
        self.assertEqual(result["fragments"][0]["unsupportedReasons"], ["expression_depth_exceeded"])


if __name__ == "__main__":
    unittest.main()
