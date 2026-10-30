"""Generic enum argument/field source mappings, never initialized values."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import policy_semantics


def extract(source, **kwargs):
    return policy_semantics.extract_semantics(source, "Java", "example/Settings.java", hashlib.sha256(source.encode()).hexdigest(), **kwargs)


def constants(result):
    return [r for r in result["fragments"] if r["category"] == "enum_constant"]


def mappings(row):
    return [mapping for candidate in row["expression"]["constructorBindings"]["candidates"] for mapping in candidate["fieldMappings"]]


class EnumPolicySourceTests(unittest.TestCase):
    def test_constant_arguments_link_only_through_explicit_parameter_field_assignments(self):
        result = extract("enum Setting { SMALL(2,true), LARGE(5,false); final int quota; final boolean active; Setting(int q, boolean a) { this.quota=q; this.active=a; }}")
        rows = constants(result)
        self.assertEqual([r["name"] for r in rows], ["SMALL", "LARGE"])
        self.assertEqual([[a["value"] for a in r["expression"]["arguments"]] for r in rows], [["2", True], ["5", False]])
        ids = {r["id"] for r in result["fragments"]}
        names = {r["id"]: r.get("name") for r in result["fragments"]}
        for row in rows:
            links = mappings(row)
            self.assertEqual([(names[m["fieldDeclarationId"]], m["argumentIndex"]) for m in links], [("quota", 0), ("active", 1)])
            self.assertTrue(all(m["resolution"] == "direct_source_argument_field_mapping" for m in links))
            self.assertTrue(all(set(m["sourceEvidenceIds"]) <= ids for m in links))
            self.assertTrue(all(m["initialValueStatus"] == "UNKNOWN" for m in links))
            self.assertFalse(row["businessMeaningVerified"])
        self.assertEqual(result["coverage"]["detectedFragments"], 6)

    def test_no_argument_enum_without_semicolon_and_trailing_comma_is_recorded(self):
        result = extract("enum Setting { A, B, }")
        self.assertEqual([r["name"] for r in constants(result)], ["A", "B"])
        self.assertTrue(all(r["expression"]["arguments"] == [] for r in constants(result)))
        self.assertTrue(result["coverage"]["inventoryComplete"])

    def test_overloaded_constructor_and_delegation_are_candidates(self):
        result = extract("enum Setting { A(2); int quota; Setting(int q) { this(q, true); } Setting(int q, boolean a) { this.quota=q; }}")
        row = constants(result)[0]
        candidates = row["expression"]["constructorBindings"]["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertIn("constructor_delegation_unresolved", candidates[0]["limitations"])
        self.assertTrue(all(m["resolution"] == "candidate_source_assignment" for m in mappings(row)))
        self.assertTrue(all(m["argumentIndex"] is None for m in mappings(row)))

    def test_conditional_repeated_mutated_and_effectful_constructors_never_prove_mapping(self):
        cases = [("if(q>0) this.quota=q;", "conditional_assignment"),
                 ("this.quota=q; this.quota=q;", "multiple_field_writes"),
                 ("q=q+1; this.quota=q;", "parameter_reassigned"),
                 ("this.quota=q; publish();", "constructor_body_effects_unresolved")]
        for body, reason in cases:
            with self.subTest(body=body):
                row = constants(extract("enum Setting { A(2); int quota; Setting(int q) { " + body + " }}"))[0]
                links = mappings(row)
                self.assertTrue(links)
                self.assertTrue(all(m["resolution"] == "candidate_source_assignment" and reason in m["limitations"] for m in links))

    def test_constant_subclass_preserves_body_and_marks_effects_unknown(self):
        result = extract("enum Setting { A(2) { int get(){ return 7; } }, B(3); final int quota; Setting(int q){this.quota=q;} }")
        first, second = constants(result)
        ref = first["expression"]["constantBody"]
        self.assertEqual(ref["bodyKind"], "enum_constant_subclass")
        self.assertIn("enum_constant_subclass_effects_unresolved", first["unsupportedReasons"])
        child = next(r for r in result["fragments"] if r["category"] == "return")
        self.assertTrue(any(c["fragmentId"] == ref["bodyId"] for c in child["controlFlow"]["contexts"]))
        self.assertEqual(mappings(first)[0]["resolution"], "candidate_source_assignment")
        self.assertEqual(mappings(second)[0]["resolution"], "direct_source_argument_field_mapping")

    def test_distinct_nested_enum_names_do_not_cross_link(self):
        source = "class First { enum Setting { A(2); int quota; Setting(int q){this.quota=q;} }} class Second { enum Setting { B(3); int limit; Setting(int n){this.limit=n;} }}"
        result = extract(source)
        names = {r["id"]: r.get("name") for r in result["fragments"]}
        first, second = constants(result)
        self.assertEqual(names[mappings(first)[0]["fieldDeclarationId"]], "quota")
        self.assertEqual(names[mappings(second)[0]["fieldDeclarationId"]], "limit")

    def test_argument_expressions_and_redacted_strings_are_retained_without_evaluation(self):
        result = extract('enum Setting { A(2*3, "private-synthetic-value"), B(4, "private-synthetic-value"); int quota; String label; Setting(int n,String label){this.quota=n;this.label=label;} }')
        first, second = constants(result)
        self.assertEqual(first["expression"]["arguments"][0]["op"], "binary")
        opaque = first["expression"]["arguments"][1]
        self.assertEqual(opaque["op"], "redacted")
        self.assertEqual(opaque["opaqueLiteralId"], second["expression"]["arguments"][1]["opaqueLiteralId"])
        self.assertNotIn("private-synthetic-value", json.dumps(result))

    def test_budget_omissions_prevent_definite_source_mapping(self):
        result = extract("enum Setting { A(2); int quota; Setting(int q){this.quota=q;publish();} }", max_fragments=3)
        self.assertFalse(result["coverage"]["inventoryComplete"])
        link = mappings(constants(result)[0])[0]
        self.assertEqual(link["resolution"], "candidate_source_assignment")
        self.assertIn("fragment_inventory_incomplete", link["limitations"])

    def test_nonparameter_expression_and_compound_assignment_do_not_link(self):
        for body in ("this.quota=q*2;", "this.quota+=q;", "this.quota=get(q);"):
            row = constants(extract("enum Setting { A(2); int quota; Setting(int q){" + body + "} }"))[0]
            self.assertEqual(mappings(row), [])

    def test_annotation_and_multiline_constructor_keep_source_spans(self):
        result = extract('enum Setting {\n @Hint("opaque-private")\n A(2),\n B(3);\n int quota;\n @Hint("constructor-private") private Setting(int q){\n this.quota=q;\n }\n}')
        first, second = constants(result)
        self.assertEqual(first["span"], {"lineStart": 2, "lineEnd": 3})
        self.assertEqual(second["span"], {"lineStart": 4, "lineEnd": 4})
        self.assertEqual(mappings(first)[0]["resolution"], "direct_source_argument_field_mapping")
        self.assertNotIn("opaque-private", json.dumps(result))

    def test_large_derived_join_is_explicit_gap_without_dropping_source_statements(self):
        fields = "".join("int field" + str(i) + ";" for i in range(140))
        assignments = "".join("this.field" + str(i) + "=q;" for i in range(140))
        result = extract("enum Setting { A(2); " + fields + "Setting(int q){" + assignments + "}}")
        binding = constants(result)[0]["expression"]["constructorBindings"]
        self.assertEqual(binding["resolution"], "UNKNOWN")
        self.assertEqual(binding["reason"], "enum_constructor_binding_budget_exceeded")
        self.assertEqual(binding["mappingCount"], 140)
        self.assertEqual(sum(r["category"] == "assignment" for r in result["fragments"]), 140)
        self.assertTrue(result["coverage"]["inventoryComplete"])


if __name__ == "__main__":
    unittest.main()
