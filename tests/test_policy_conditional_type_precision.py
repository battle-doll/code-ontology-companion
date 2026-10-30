"""Independent numeric branch proofs; all sources and failed definitions are neutral."""
import copy
import unittest

from test_policy_dependency_closure import analyzed_files, policy_semantics


SOURCE = ('class Capacity { boolean ready(){return true;} int quota(){return 13;} '
          'int choose(){return ready() ? 13 : 37;} '
          'int sibling(boolean enabled){return enabled ? 19 : 43;} }')


def returned(result, name="choose"):
    return next(row for row in result["fragments"] if row.get("category") == "return"
                and row.get("controlFlow", {}).get("owner", {}).get("name") == name)


def fixture(source=SOURCE):
    results, facts = analyzed_files({"Capacity.java": source})
    result = results["Capacity.java"]
    records = {row["id"]: copy.deepcopy(row) for row in facts["Capacity.java"]["records"]}
    records.update({row["id"]: dict(copy.deepcopy(row), kind="semantic_fragment") for row in result["fragments"]})
    return result, records


def reject_call(records, node):
    identity = next(i for i in node["staticType"]["sourceEvidenceIds"] if i.startswith("java-callsite:"))
    original = records[identity]
    assert original["kind"] == "callsite" and original["resolution"] == "exact"
    # Actual parser evidence remains bound. Only an emitted definition's
    # resolution is rejected; no passing type or provenance guard is fabricated.
    records[identity] = dict(original, resolution="unresolved")
    assert all(records[identity][key] == value for key, value in original.items() if key != "resolution")


def finalize(result, records, alter=None):
    def lookup(identity, path=None):
        value = records.get(identity)
        if value is None or (path is not None and value["path"] != path): return None
        return alter(copy.deepcopy(value)) if alter else copy.deepcopy(value)
    return policy_semantics.finalize_dependencies(result, lookup=lookup)


class ConditionalTypePrecisionTests(unittest.TestCase):
    def retained_fixture(self):
        source = 'class Capacity{boolean ready(){return false;}int choose(){return ready()?73:79;}int sibling(boolean b){return b?17:29;}}'
        result, records = fixture(source); row = returned(result)
        reject_call(records, row["expression"]["condition"]); finalize(result, records)
        self.assertEqual(row["expression"]["staticType"]["name"], "int")
        self.assertEqual(row["expression"]["staticEvidenceStatus"]["retainedEvidence"],
            "independent_numeric_literal_branch_type_only")
        return result, records

    def test_repeated_finalization_rechecks_original_four_owner_failures(self):
        for fault in ("missing", "stale", "unsupported", "same_object"):
            with self.subTest(fault=fault):
                result, records = self.retained_fixture(); row = returned(result); identity = row["id"]
                before = copy.deepcopy(row); sibling = copy.deepcopy(returned(result, "sibling")); calls = []
                # A nonpositive unrelated diagnostic slot is not a passing type
                # proof and must not be erased solely by retained-type freshness.
                row["expression"]["unitEvidence"] = {"status": "UNKNOWN"}
                def lookup(requested, path=None):
                    if requested == identity:
                        calls.append((requested, path))
                        if fault == "missing": return None
                        if fault == "same_object": return row
                        owner = copy.deepcopy(records[identity])
                        if fault == "stale": owner["sourceDigest"] = "0" * 64
                        if fault == "unsupported": owner.update(expression=None, representationStatus="unsupported")
                        return owner
                    return copy.deepcopy(records.get(requested))
                policy_semantics.finalize_dependencies(result, lookup=lookup)
                self.assertGreater(len(calls), 0)
                self.assertNotIn("staticType", row["expression"])
                self.assertNotIn("retainedEvidence", row["expression"]["staticEvidenceStatus"])
                self.assertEqual(row["expression"]["unitEvidence"], {"status": "UNKNOWN"})
                self.assertEqual(row["expression"]["condition"], before["expression"]["condition"])
                self.assertEqual(row["expression"]["then"], before["expression"]["then"])
                self.assertEqual(row["expression"]["else"], before["expression"]["else"])
                self.assertEqual(returned(result, "sibling"), sibling)
                self.assertEqual(row["dependencyClosure"]["reasons"], before["dependencyClosure"]["reasons"])
                self.assertEqual(row["dependencyClosure"]["invalidatedNodes"], before["dependencyClosure"]["invalidatedNodes"] + 1)
                self.assert_partial(row)

    def test_repeated_fresh_pre_final_and_retained_partial_owners_are_idempotent(self):
        for owner_state in ("pre_final", "retained_partial"):
            with self.subTest(owner_state=owner_state):
                result, records = self.retained_fixture(); row = returned(result); before = copy.deepcopy(result)
                if owner_state == "retained_partial": records[row["id"]] = dict(copy.deepcopy(row), kind="semantic_fragment")
                calls = []
                def lookup(identity, path=None):
                    if identity == row["id"]: calls.append(identity)
                    return copy.deepcopy(records.get(identity))
                for _ in range(2):
                    policy_semantics.finalize_dependencies(result, lookup=lookup)
                    self.assertEqual(result, before)
                self.assertEqual(len(calls), 2)

    def test_repeated_child_cleanup_and_exact_proof_freshness(self):
        for fault in ("child_dependency", "child_missing_type", "parent_origin", "range", "consumer", "branch_alias", "pending_owner"):
            with self.subTest(fault=fault):
                result, records = self.retained_fixture(); row = returned(result); identity = row["id"]
                records[identity] = dict(copy.deepcopy(row), kind="semantic_fragment")
                if fault == "child_dependency":
                    row["expression"]["then"]["staticType"]["sourceEvidenceIds"].append("semantic:" + "0" * 64)
                elif fault == "child_missing_type": row["expression"]["then"].pop("staticType")
                elif fault == "parent_origin": row["expression"]["staticType"]["sourceEvidenceIds"].append("semantic:" + "0" * 64)
                elif fault == "range": records[identity]["sourceRange"]["charEnd"] -= 1
                elif fault == "consumer": records[identity]["expression"]["staticType"]["consumer"] = "/target/staticType"
                elif fault == "pending_owner": records[identity]["dependencyClosure"]["status"] = "pending_snapshot_finalization"
                def lookup(requested, path=None):
                    value = copy.deepcopy(records.get(requested))
                    if fault == "branch_alias" and requested == identity:
                        value["expression"]["then"] = row["expression"]["then"]
                    return value
                policy_semantics.finalize_dependencies(result, lookup=lookup)
                self.assertNotIn("staticType", row["expression"])
                self.assertNotIn("retainedEvidence", row["expression"]["staticEvidenceStatus"])
                if fault == "child_dependency": self.assertNotIn("staticType", row["expression"]["then"])
                self.assert_partial(row)

    def assert_partial(self, row):
        self.assertEqual(row["representationStatus"], "partial")
        self.assertEqual(row["dependencyClosure"]["status"], "invalidated")
        self.assertIn("source_dependency_definition_unavailable", row["dependencyClosure"]["reasons"])
        self.assertFalse(row["businessMeaningVerified"])
        self.assertEqual(row["runtimeStatus"], "not_observed")

    def test_equal_primitive_numeric_literals_retain_only_independent_type(self):
        for then, otherwise, expected in (("13", "37", "int"), ("13L", "37L", "long"),
                                          ("1.3F", "3.7F", "float"), ("1.3", "3.7", "double")):
            with self.subTest(expected=expected):
                result, records = fixture(SOURCE.replace("? 13 : 37", "? " + then + " : " + otherwise))
                row = returned(result); expression = row["expression"]
                before = copy.deepcopy(expression); sibling = copy.deepcopy(returned(result, "sibling"))
                reject_call(records, expression["condition"])
                finalize(result, records)
                self.assertEqual(expression["staticType"], before["staticType"])
                self.assertEqual(expression["staticType"]["name"], expected)
                self.assertEqual(expression["then"], before["then"])
                self.assertEqual(expression["else"], before["else"])
                self.assertEqual(returned(result, "sibling"), sibling)
                self.assertEqual(set(expression) & policy_semantics._DERIVED_EVIDENCE, {"staticType"})
                self.assertNotIn("staticType", expression["condition"])
                self.assertEqual(expression["staticEvidenceStatus"], {"status": "UNKNOWN",
                    "reason": "source_dependency_unavailable", "retainedEvidence": "independent_numeric_literal_branch_type_only"})
                self.assertEqual(row["dependencyClosure"]["invalidatedNodes"], 1)
                self.assert_partial(row)
                once = copy.deepcopy(result); finalize(result, records)
                self.assertEqual(result, once)

    def test_valid_condition_is_byte_compatible(self):
        result, records = fixture(); before = copy.deepcopy(result)
        finalize(result, records)
        self.assertEqual(result, before)

    def test_different_types_and_source_dependent_branches_are_not_retained(self):
        for expression, failed_role in (("ready() ? 13 : 37L", "condition"),
                                        ("ready() ? quota() : 37", "then"),
                                        ("ready() ? quota() : 37", "condition")):
            with self.subTest(expression=expression, failed_role=failed_role):
                result, records = fixture(SOURCE.replace("ready() ? 13 : 37", expression))
                row = returned(result); reject_call(records, row["expression"][failed_role])
                finalize(result, records)
                self.assertNotIn("staticType", row["expression"])
                self.assert_partial(row)

    def test_invalid_current_literal_or_type_proof_cannot_be_rescued(self):
        faults = {
            "missing_type": lambda n: n["then"].pop("staticType"),
            "wrong_type": lambda n: n["then"]["staticType"].update(name="long"),
            "wrong_literal_type": lambda n: n["then"].update(type="floating"),
            "malformed_number": lambda n: n["then"].update(value="1.2.3"),
            "malformed_suffix": lambda n: n["then"].update(javaSuffix="x"),
            "nonstring_suffix": lambda n: n["then"].update(javaSuffix={}),
            "redacted": lambda n: n["then"].update(op="redacted_literal"),
            "review_metadata": lambda n: n["then"].update(literalReview={"status": "revoked"}),
            "extra_branch_origin": lambda n: n["then"]["staticType"]["sourceEvidenceIds"].append("semantic:" + "0" * 64),
            "extra_parent_origin": lambda n: n["staticType"]["sourceEvidenceIds"].append("semantic:" + "0" * 64),
            "missing_parent_origin": lambda n: n["staticType"].update(sourceEvidenceIds=[]),
            "extra_node_origin": lambda n: n.update(sourceEvidenceIds=["semantic:" + "0" * 64]),
            "duplicate_branch_origin": lambda n: n["then"]["staticType"]["sourceEvidenceIds"].extend(n["then"]["staticType"]["sourceEvidenceIds"][:]),
            "forged_consumer": lambda n: n["staticType"].update(consumer="/target/staticType"),
            "platform_without_proof": lambda n: n["staticType"].update(platformInheritance={"schemaVersion": 2}),
            "forged_basis": lambda n: n["then"]["staticType"].update(basis="identical_conditional_operand_types"),
            "not_conditional": lambda n: n.update(op="binary"),
        }
        for name, fault in faults.items():
            with self.subTest(fault=name):
                result, records = fixture(); row = returned(result)
                reject_call(records, row["expression"]["condition"]); fault(row["expression"])
                finalize(result, records)
                self.assertNotIn("staticType", row["expression"])
                self.assert_partial(row)

    def test_consistent_invalid_numeric_encoding_is_not_a_passing_proof(self):
        for fields in ({"value": "1.2.3"}, {"value": "-13"}, {"javaSuffix": "x"},
                       {"type": "floating", "value": "1.3", "javaSuffix": "L"},
                       {"value": "1234567890123"}, {"value": "2147483648"}):
            with self.subTest(fields=fields):
                result, records = fixture(); row = returned(result); reject_call(records, row["expression"]["condition"])
                for owner in (row, records[row["id"]]): owner["expression"]["then"].update(fields)
                finalize(result, records)
                self.assertNotIn("staticType", row["expression"])

    def test_owner_lookup_pin_range_and_consumer_must_match(self):
        for fault in ("missing", "digest", "path", "id", "range", "kind", "pending", "revoked", "wrong_consumer", "donor"):
            with self.subTest(fault=fault):
                result, records = fixture(); row = returned(result); identity = row["id"]
                reject_call(records, row["expression"]["condition"])
                if fault == "missing": records.pop(identity)
                elif fault == "digest": records[identity]["sourceDigest"] = "0" * 64
                elif fault == "path": records[identity]["path"] = "Other.java"
                elif fault == "id": records[identity]["id"] = "semantic:" + "0" * 64
                elif fault == "range": records[identity]["sourceRange"]["charStart"] += 1
                elif fault == "kind": records[identity]["kind"] = "symbol"
                elif fault == "pending": records[identity]["dependencyClosure"] = {"status": "pending_snapshot_finalization"}
                elif fault == "revoked": records[identity].update(expression=None, representationStatus="unsupported", unsupportedReasons=["literal_review_revoked"])
                elif fault == "wrong_consumer": records[identity]["expression"] = {"op": "conditional", "then": {}}
                else: row["expression"]["staticType"] = copy.deepcopy(returned(result, "sibling")["expression"]["staticType"])
                finalize(result, records)
                self.assertNotIn("staticType", row["expression"])

    def test_current_owner_mismatch_and_aliased_lookup_are_not_independent(self):
        for fault in ("digest", "range", "result_digest", "aliased_lookup"):
            with self.subTest(fault=fault):
                result, records = fixture(); row = returned(result); reject_call(records, row["expression"]["condition"])
                if fault == "digest": row["sourceDigest"] = "0" * 64
                elif fault == "range": row["sourceRange"]["charEnd"] -= 1
                elif fault == "result_digest": result["sourceDigest"] = "0" * 64
                if fault == "aliased_lookup":
                    def lookup(identity, path=None):
                        return dict(row, kind="semantic_fragment") if identity == row["id"] else records.get(identity)
                    policy_semantics.finalize_dependencies(result, lookup=lookup)
                else: finalize(result, records)
                self.assertNotIn("staticType", row["expression"])

    def test_nested_conditionals_do_not_restore_outer_nonliteral_type(self):
        result, records = fixture(SOURCE.replace("ready() ? 13 : 37", "ready() ? (ready() ? 13 : 37) : 47"))
        row = returned(result); inner = row["expression"]["then"]
        reject_call(records, inner["condition"]); finalize(result, records)
        self.assertEqual(inner["staticType"]["name"], "int")
        self.assertNotIn("staticType", row["expression"])
        self.assert_partial(row)

    def test_boolean_and_unreviewed_strings_are_outside_numeric_closure(self):
        for branches in ("true : false", '"ALLOW" : "DENY"'):
            with self.subTest(branches=branches):
                result, records = fixture(SOURCE.replace("13 : 37", branches))
                row = returned(result)
                if row.get("expression") is None:
                    self.assertEqual(row["representationStatus"], "unsupported")
                    continue
                reject_call(records, row["expression"]["condition"])
                finalize(result, records)
                self.assertNotIn("staticType", row["expression"])


if __name__ == "__main__": unittest.main()
