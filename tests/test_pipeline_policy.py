"""Independent synthetic goldens for source-derived, sealed policy knowledge."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline_policy as policy


SIX_DOMAINS = {
    "product": "def product_available(stock: int, reserved: int) -> bool:\n    return stock > reserved and stock > 0\n",
    "order": "from decimal import Decimal, ROUND_HALF_UP\ndef order_payment(amount: Decimal, employee: bool, used: int, cap: Decimal) -> Decimal:\n    if not employee or used >= 2:\n        return amount\n    discount = amount * Decimal('0.15')\n    if discount > cap:\n        discount = cap\n    payment = amount - discount\n    return payment.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)\n",
    "display": "def display_visible(active: bool, suspended: bool) -> bool:\n    if suspended:\n        return False\n    return active\n",
    "claim": "def claim_allowed(days: int, damaged: bool) -> bool:\n    return days >= 0 and (days <= 7 or damaged)\n",
    "settlement": "from decimal import Decimal, ROUND_HALF_EVEN\ndef settlement_amount(amount: Decimal, fee: Decimal) -> Decimal:\n    value = amount - fee\n    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)\n",
    "delivery": "def delivery_ready(paid: bool, stock: bool, blocked: bool) -> bool:\n    if blocked:\n        return False\n    return paid and stock\n",
}
FINITE = """from decimal import Decimal
def order_discount(employee: bool, member: bool) -> Decimal:
    if not employee:
        return Decimal('0.00')
    if member:
        return Decimal('0.20')
    return Decimal('0.10')
"""


def extract(source, path="synthetic.py", **kwargs):
    return policy.extract_policy_rules(source, "Python", path, hashlib.sha256(source.encode()).hexdigest(), **kwargs)


def extract_language(source, language, path=None, **kwargs):
    return policy.extract_policy_rules(source, language, path or ("Synthetic.java" if language == "Java" else "synthetic.ts"), hashlib.sha256(source.encode()).hexdigest(), **kwargs)


def seal_extraction(extraction):
    return policy.seal_policy_snapshot([extraction], catalog_snapshot_id="catalog:synthetic-boolean",
        policy_snapshot_id="policy:synthetic-boolean", created_at="2030-01-01T00:00:00Z")


def sealed(source=FINITE, path="synthetic.py"):
    return policy.seal_policy_snapshot([extract(source, path)], catalog_snapshot_id="catalog:synthetic-1",
        policy_snapshot_id="policy-snapshot:synthetic-1", created_at="2030-01-01T00:00:00Z", source_last_verified_at="2030-01-01T00:00:00Z")


def pins(snapshot):
    return {"catalog_snapshot_id": snapshot["catalogSnapshotId"], "policy_snapshot_id": snapshot["policySnapshotId"], "ruleset_digest": snapshot["rulesetDigest"]}


def reseal(snapshot):
    snapshot["rulesetDigest"] = policy.policy_ruleset_digest(snapshot)
    return snapshot


class PipelinePolicyTests(unittest.TestCase):
    def test_actual_source_extracts_six_domains_with_source_assertions(self):
        extractions = []
        for domain, source in SIX_DOMAINS.items():
            with self.subTest(domain=domain):
                result = extract(source, domain + ".py")
                self.assertEqual(result["coverage"]["analyzedRules"], 1)
                self.assertTrue(result["coverage"]["complete"])
                rule = result["rules"][0]
                self.assertIn(domain, [d["name"] for d in rule["domains"]])
                self.assertEqual(rule["status"], "extraction_verified")
                self.assertEqual(rule["sourceDigest"], hashlib.sha256(source.encode()).hexdigest())
                self.assertEqual(rule["sourceAssertionIds"], [result["evidence"][0]["id"]])
                self.assertNotIn("source", rule)
                self.assertNotIn("sourceText", rule)
                self.assertFalse(result["coverage"]["businessPolicyComplete"])
                extractions.append(result)
        snapshot = policy.seal_policy_snapshot(extractions, catalog_snapshot_id="catalog:synthetic-six", policy_snapshot_id="policy:synthetic-six", created_at="2030-01-01T00:00:00Z")
        domains = policy.list_domain_policies(snapshot)
        self.assertTrue(all(next(r for r in domains["domains"] if r["domain"] == name)["verifiedRuleCount"] == 1 for name in policy.DOMAINS))
        self.assertEqual(domains["modelIdentity"], "modelNotUsed")
        self.assertEqual(domains["repeatability"], "N/A")

    def test_independently_authored_boundary_cases_for_each_domain(self):
        cases = {
            "product": [({"stock": 2, "reserved": 1}, True), ({"stock": 1, "reserved": 1}, False), ({"stock": -1, "reserved": -2}, False)],
            "order": [({"amount": "10.05", "employee": True, "used": 0, "cap": "100.00"}, "8.54"), ({"amount": "100.00", "employee": True, "used": 0, "cap": "3.00"}, "97.00"), ({"amount": "100.00", "employee": True, "used": 2, "cap": "3.00"}, "100.00")],
            "display": [({"active": True, "suspended": True}, False), ({"active": True, "suspended": False}, True)],
            "claim": [({"days": -1, "damaged": True}, False), ({"days": 8, "damaged": False}, False), ({"days": 8, "damaged": True}, True), ({"days": 7, "damaged": False}, True)],
            "settlement": [({"amount": "10.025", "fee": "0.00"}, "10.02"), ({"amount": "10.035", "fee": "0.00"}, "10.04")],
            "delivery": [({"paid": True, "stock": True, "blocked": True}, False), ({"paid": True, "stock": False, "blocked": False}, False), ({"paid": True, "stock": True, "blocked": False}, True)],
        }
        for domain, examples in cases.items():
            snapshot = sealed(SIX_DOMAINS[domain], domain + ".py")
            for context, expected in examples:
                with self.subTest(domain=domain, context=context):
                    result = policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], context, **pins(snapshot))
                    self.assertEqual(result["status"], "evaluated")
                    self.assertEqual(result["value"]["value"], expected)
                    self.assertFalse(result["businessPolicyApproved"])
                    self.assertEqual(result["businessValidity"], "UNKNOWN")

    def test_negation_alias_reassignment_early_return_short_circuit(self):
        source = """def order_value(active: bool, amount: int, divisor: int) -> int:
    eligible = not active
    value = amount
    if eligible:
        return 0
    value += 3
    if divisor != 0 and value // divisor > 2:
        value = value - 1
    return value
"""
        snapshot = sealed(source); identifier = snapshot["rules"][0]["id"]
        for context, expected in [({"active": False, "amount": 99, "divisor": 0}, "0"), ({"active": True, "amount": 4, "divisor": 0}, "7"), ({"active": True, "amount": 4, "divisor": 2}, "6")]:
            self.assertEqual(policy.explain_policy_result(snapshot, identifier, context)["value"]["value"], expected)

    def test_default_values_and_keyword_only_arguments(self):
        snapshot = sealed("def product_quantity(stock: int = 2, *, active: bool = True) -> int:\n    return stock if active else 0\n")
        result = policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], {})
        self.assertEqual(result["value"], {"type": "int", "value": "2"})

    def test_missing_runtime_inputs_never_become_eligibility_or_maximum(self):
        snapshot = sealed(SIX_DOMAINS["order"], "order.py"); identifier = snapshot["rules"][0]["id"]
        result = policy.explain_policy_result(snapshot, identifier, {"amount": "100.00"})
        self.assertEqual(result["status"], "needs_context")
        self.assertEqual(result["missingInputs"], ["employee", "used", "cap"])
        compared = policy.compare_policy_cases(snapshot, identifier, [{"amount": "100.00"}], **pins(snapshot))
        self.assertEqual(compared["status"], "needs_context")
        self.assertFalse(compared["optimality"]["optimum"])
        self.assertIsNone(compared["maximum"])

    def test_source_free_queries_survive_deleted_source_and_deny_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "order.py"; path.write_text(FINITE)
            snapshot = sealed(path.read_text(), "order.py"); path.unlink()
            encoded = json.dumps(snapshot)
            restored = json.loads(encoded)
            with mock.patch("builtins.open", side_effect=AssertionError("source access forbidden")), mock.patch.object(Path, "read_text", side_effect=AssertionError("source access forbidden")), mock.patch.object(policy.privacy_guard, "load_profile", return_value=None):
                context = {"employee": True, "member": True}
                first = policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], context)
                second = policy.explain_policy_result(restored, restored["rules"][0]["id"], context)
                self.assertEqual(first, second)

    def test_numeric_samples_cannot_claim_a_universal_maximum(self):
        snapshot = sealed("def order_value(amount: int) -> int:\n    return amount * 2\n")
        result = policy.compare_policy_cases(snapshot, snapshot["rules"][0]["id"], [{"amount": 2}, {"amount": 3}], **pins(snapshot))
        self.assertEqual(result["status"], "maximum_over_provided_cases")
        self.assertEqual(result["maximum"]["value"]["value"], "6")
        self.assertFalse(result["optimality"]["optimum"])
        self.assertFalse(result["optimality"]["finiteDeclaredInputs"])
        with self.assertRaises(policy.PolicyError):
            policy.compare_policy_cases(snapshot, snapshot["rules"][0]["id"], [{"amount": 2, "complete": True}], **pins(snapshot))

    def test_proof_requires_compiled_finite_domain_all_cases_and_all_pins(self):
        snapshot = sealed(); identifier = snapshot["rules"][0]["id"]
        cases = [dict(zip(("employee", "member"), pair)) for pair in itertools.product((False, True), repeat=2)]
        full = policy.compare_policy_cases(snapshot, identifier, cases, **pins(snapshot))
        self.assertEqual(full["status"], "proven_maximum")
        self.assertEqual(full["maximum"]["value"]["value"], "0.20")
        self.assertEqual(full["optimality"]["scope"], "declared_function_boolean_inputs")
        self.assertFalse(full["optimality"]["organizationWide"])
        self.assertFalse(full["optimality"]["stackingSearched"])
        for kwargs, selected in [({}, cases), (pins(snapshot), cases[:-1]), (pins(snapshot), [cases[0]] * 4)]:
            result = policy.compare_policy_cases(snapshot, identifier, selected, **kwargs)
            self.assertFalse(result["optimality"]["optimum"])
        minimum = policy.compare_policy_cases(snapshot, identifier, cases, objective="minimize_value", **pins(snapshot))
        self.assertEqual(minimum["status"], "proven_minimum")
        self.assertIsNone(minimum["maximum"])
        self.assertEqual(minimum["minimum"]["value"]["value"], "0.00")

    def test_incomplete_coverage_blocks_even_exhaustive_finite_maximum(self):
        snapshot = sealed(FINITE + "\ndef unsupported(value):\n    return external(value)\n")
        cases = [dict(zip(("employee", "member"), p)) for p in itertools.product((False, True), repeat=2)]
        result = policy.compare_policy_cases(snapshot, snapshot["rules"][0]["id"], cases, **pins(snapshot))
        self.assertEqual(result["status"], "incomplete_coverage")
        self.assertFalse(result["optimality"]["optimum"])

    def test_unsupported_constructs_do_not_generate_partial_rules(self):
        sources = [
            "def order_x(x: int) -> int:\n    for i in range(x):\n        x += i\n    return x\n",
            "def order_x(x: int) -> int:\n    return callback(x)\n",
            "def order_x(x: int) -> int:\n    if x < 0:\n        raise ValueError('synthetic exception')\n    return x\n",
            "@decorator\ndef order_x(x: int) -> int:\n    return x\n",
            "def order_x(x: float) -> float:\n    return x * 0.1\n",
            "def order_x(x: int) -> int:\n    return x / 2\n",
            "class Holder:\n    def order_x(self, x: int) -> int:\n        return x\n",
            "def order_x(x: int) -> int:\n    if x > 0:\n        return x\n",
            "def order_x(x: int) -> int:\n    return x\ndef order_x(x: int) -> int:\n    return x + 1\n",
            "from decimal import Decimal, getcontext\ngetcontext().prec=4\ndef order_x(x: Decimal) -> Decimal:\n    return x\n",
        ]
        for source in sources:
            with self.subTest(source_index=sources.index(source)):
                result = extract(source)
                self.assertEqual(result["rules"], [])
                self.assertFalse(result["coverage"]["complete"])
                self.assertTrue(result["coverage"]["reasons"])
        java = "class Synthetic { int orderValue(int x) { return x; } }"
        result = policy.extract_policy_rules(java, "Java", "Synthetic.java", hashlib.sha256(java.encode()).hexdigest())
        self.assertEqual(result["rules"], [])
        self.assertEqual(result["coverage"]["unsupportedRules"], 1)
        self.assertFalse(result["coverage"]["complete"])
        result = extract_language("function orderValue(x) { return x; }", "JavaScript")
        self.assertEqual(result["coverage"]["reasons"], ["unsupported_policy_language"])
        self.assertTrue(result["coverage"]["unknownDenominator"])

    def test_source_digest_parse_and_quotas_fail_without_source_diagnostics(self):
        with self.assertRaisesRegex(policy.PolicyError, "source_digest_mismatch"):
            policy.extract_policy_rules(FINITE, "Python", "source.py", "0" * 64)
        malformed = "def synthetic():\n    return (\n"
        result = extract(malformed)
        self.assertEqual(result["coverage"]["reasons"], ["parse_failure"])
        self.assertNotIn(malformed, json.dumps(result))
        self.assertEqual(extract(FINITE, max_ast_nodes=2)["coverage"]["reasons"], ["ast_budget"])
        limited = extract("def first(x: int) -> int:\n    return x\ndef second(x: int) -> int:\n    return x\n", max_rules=1)
        self.assertEqual(limited["coverage"]["unsupportedRules"], 1)
        self.assertFalse(limited["coverage"]["complete"])
        snapshot = sealed()
        with self.assertRaisesRegex(policy.PolicyError, "case_budget_exceeded"):
            policy.compare_policy_cases(snapshot, snapshot["rules"][0]["id"], [{"employee": True, "member": True}] * 2, max_cases=1)

    def test_explicit_large_ast_budget_preserves_default_and_ir_limits(self):
        source = "".join(f"FLAG_{index} = True\n" for index in range(5000))
        source += "def order_allowed(active: bool) -> bool:\n    return active\n"
        self.assertGreater(sum(1 for _ in ast.walk(ast.parse(source))), 20000)
        self.assertLess(len(source.encode()), policy.MAX_SOURCE_BYTES)
        self.assertEqual(extract(source)["coverage"]["reasons"], ["ast_budget"])
        result = extract(source, max_ast_nodes=200000)
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(result["coverage"]["analyzedRules"], 1)
        snapshot = seal_extraction(result)
        answer = policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], {"active": True})
        self.assertEqual(answer["value"], {"type": "bool", "value": True})
        with self.assertRaisesRegex(policy.PolicyError, "invalid_arguments"):
            extract(source, max_ast_nodes=200001)
        # The larger file budget does not relax per-rule expression expansion.
        expansion = "def order_expand(value: int) -> int:\n" + "    value = value + value\n" * 30 + "    return value\n"
        self.assertIn("ir_budget", extract(expansion, max_ast_nodes=200000)["coverage"]["reasons"])

    def test_mutation_missing_evidence_duplicate_ids_and_invalid_ir_are_rejected(self):
        snapshot = sealed()
        for mutate, refresh in [
            (lambda s: s["rules"][0].update(name="changed"), False),
            (lambda s: s["evidence"].clear(), True),
            (lambda s: s["rules"].append(copy.deepcopy(s["rules"][0])), True),
            (lambda s: s["rules"][0].update(program={"op": "execute", "value": "denied"}), True),
            (lambda s: s["rules"][0]["parameters"][0].update(finiteValues=[True]), True),
            (lambda s: s["evidence"][0].update(sourceDigest="0" * 64), True),
        ]:
            damaged = copy.deepcopy(snapshot); mutate(damaged)
            if refresh: reseal(damaged)
            with self.assertRaises(policy.PolicyError): policy.query_policy_rules(damaged)
        with self.assertRaisesRegex(policy.PolicyError, "snapshot_pin_mismatch"):
            policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], {}, policy_snapshot_id="stale")

    def test_ai_proposed_and_business_authority_are_never_implicitly_mixed(self):
        snapshot = sealed(); rule = snapshot["rules"][0]; context = {"employee": True, "member": True}
        proposed = copy.deepcopy(snapshot); proposed["rules"][0]["status"] = "AI-proposed"; reseal(proposed)
        self.assertEqual(policy.explain_policy_result(proposed, rule["id"], context)["status"], "ineligible_policy_view")
        approved = copy.deepcopy(snapshot)
        approved["rules"][0]["authority"] = {"kind": "approved-business-policy", "rulesetAuthority": "synthetic-owner-v1", "approvalVersion": "synthetic-approval-1"}
        reseal(approved)
        self.assertEqual(policy.explain_policy_result(approved, rule["id"], context)["status"], "ineligible_policy_view")
        with self.assertRaisesRegex(policy.PolicyError, "authority_required"):
            policy.explain_policy_result(approved, rule["id"], context, policy_view="approved_business")
        result = policy.explain_policy_result(approved, rule["id"], context, policy_view="approved_business", ruleset_authority="synthetic-owner-v1")
        self.assertEqual(result["status"], "evaluated")
        approved["rules"][0]["status"] = "owner-reviewed"; reseal(approved)
        self.assertEqual(policy.explain_policy_result(approved, rule["id"], context, policy_view="approved_business", ruleset_authority="synthetic-owner-v1")["status"], "ineligible_policy_view")

    def test_profiles_dates_conflicts_are_explicit_and_do_not_use_wall_clock(self):
        snapshot = sealed(); rule = snapshot["rules"][0]; context = {"employee": True, "member": True}
        self.assertEqual(policy.explain_policy_result(snapshot, rule["id"], context, config_profile="other")["status"], "unknown_profile")
        rule["validity"] = {"from": "2030-01-01", "to": "2030-02-01", "status": "declared"}; reseal(snapshot)
        self.assertEqual(policy.explain_policy_result(snapshot, rule["id"], context)["status"], "needs_context")
        self.assertEqual(policy.explain_policy_result(snapshot, rule["id"], context, as_of="2030-02-01")["status"], "outside_validity")
        self.assertEqual(policy.explain_policy_result(snapshot, rule["id"], context, as_of="2030-01-01")["status"], "evaluated")
        rule["conflicts"] = ["synthetic-conflict"]; reseal(snapshot)
        self.assertEqual(policy.explain_policy_result(snapshot, rule["id"], context, as_of="2030-01-01")["status"], "unknown_conflict")

    def test_privacy_rejects_email_secrets_paths_and_never_stores_arbitrary_literals(self):
        marker = "synthetic-person@example.invalid"
        result = extract("def order_x() -> int:\n    ignored = '" + marker + "'\n    return 1\n")
        self.assertEqual(result["rules"], [])
        self.assertNotIn(marker, json.dumps(result))
        for path in ("../outside.py", "/absolute.py", "C:\\outside.py", marker + ".py"):
            with self.assertRaises(policy.PolicyError): extract(FINITE, path)
        snapshot = sealed()
        with self.assertRaises(policy.PolicyError) as raised:
            policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], {"employee": marker, "member": True})
        self.assertNotIn(marker, str(raised.exception))
        with self.assertRaisesRegex(policy.PolicyError, "privacy_denied"):
            policy.explain_policy_result(snapshot, snapshot["rules"][0]["id"], {"employee": "sk-" + "x" * 32, "member": True})
        source = "def order_x(api_key: int) -> int:\n    return api_key\n"
        self.assertEqual(extract(source)["rules"], [])

    def test_proposals_are_quarantined_without_execution_or_model_claims(self):
        snapshot = sealed(); rule = snapshot["rules"][0]
        proposal = {"ruleId": rule["id"], "sourceAssertionIds": rule["sourceAssertionIds"], "program": rule["program"], "returnType": rule["returnType"]}
        result = policy.quarantine_ai_proposal(proposal, snapshot, run_id="synthetic-run-1")
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["modelIdentity"], "unverified")
        self.assertFalse(result["evaluationEligible"])
        self.assertFalse(result["automaticCrossRunReuse"])
        self.assertEqual(result["cacheScope"], "run:synthetic-run-1")
        invented = copy.deepcopy(proposal); invented["sourceAssertionIds"] = ["assertion:invented"]
        self.assertIn("evidence_mismatch", policy.quarantine_ai_proposal(invented, snapshot)["reasons"])
        altered = copy.deepcopy(proposal); altered["program"] = {"op": "return", "value": {"op": "literal", "type": "decimal", "value": "999"}}
        self.assertIn("source_support_unverified", policy.quarantine_ai_proposal(altered, snapshot)["reasons"])
        self.assertEqual(snapshot["rules"][0]["status"], "extraction_verified")

    def test_numeric_bounds_zero_division_and_float_inputs_do_not_leak_exceptions(self):
        snapshot = sealed("from decimal import Decimal\ndef order_ratio(amount: Decimal, divisor: Decimal) -> Decimal:\n    return amount / divisor\n")
        identifier = snapshot["rules"][0]["id"]
        result = policy.explain_policy_result(snapshot, identifier, {"amount": "1", "divisor": "0"})
        self.assertEqual(result["status"], "unknown_evaluation")
        self.assertIsNone(result["value"])
        for context in ({"amount": 0.1, "divisor": "2"}, {"amount": "NaN", "divisor": "2"}, {"amount": "1e999999", "divisor": "2"}):
            with self.assertRaises(policy.PolicyError): policy.explain_policy_result(snapshot, identifier, context)

    def test_paging_is_stable_and_does_not_change_evaluation(self):
        source = "\n".join(f"def order_value_{i}(x: int) -> int:\n    return x + {i}\n" for i in range(4))
        snapshot = sealed(source)
        first = policy.query_policy_rules(snapshot, limit=2)
        second = policy.query_policy_rules(snapshot, offset=first["nextOffset"], limit=2)
        self.assertEqual(len({r["id"] for r in first["rules"] + second["rules"]}), 4)
        self.assertIsNone(second["nextOffset"])
        self.assertEqual(first["rulesetDigest"], second["rulesetDigest"])
        self.assertEqual(len(first["evidence"]), 2)

    def test_repeated_alias_expansion_stays_bounded_without_claiming_a_rule(self):
        source = "def order_expand(value: int) -> int:\n" + "    value = value + value\n" * 30 + "    return value\n"
        result = extract(source)
        self.assertEqual(result["rules"], [])
        self.assertIn("ir_budget", result["coverage"]["reasons"])

    def test_unknown_module_initializers_cannot_change_decimal_context_silently(self):
        source = "from decimal import Decimal, getcontext as selected_context\nselected_context().prec = 4\ndef order_value(x: Decimal) -> Decimal:\n    return x * Decimal('0.125')\n"
        result = extract(source)
        self.assertEqual(result["rules"], [])
        self.assertIn("dynamic_module_scope", result["coverage"]["reasons"])

    def test_coverage_claim_cannot_contradict_sealed_rule_denominator(self):
        snapshot = sealed()
        for field, value in (("analyzedRules", 999), ("detectedRules", 0), ("unknownDenominator", True), ("unsupportedRules", 1)):
            corrupt = copy.deepcopy(snapshot); corrupt["coverage"][field] = value; reseal(corrupt)
            with self.assertRaisesRegex(policy.PolicyError, "invalid_snapshot"):
                policy.list_domain_policies(corrupt)

    def test_java_six_domain_functions_have_independent_boolean_goldens(self):
        source = """package synthetic;
public class Synthetic {
    public static boolean productAvailable(boolean active, boolean blocked) { return active && !blocked; }
    public boolean orderCancelable(boolean paid, boolean dispatched) { if (dispatched) return false; return paid; }
    public boolean displayVisible(boolean enabled, boolean hidden) { return enabled && !hidden; }
    public boolean claimAllowed(boolean damaged, boolean expired) { return damaged || !expired; }
    public boolean settlementReady(boolean approved, boolean held) { if (!approved) { return false; } else { return !held; } }
    public boolean deliveryReady(final boolean paid, boolean stocked) { return paid && stocked; }
}
"""
        result = extract_language(source, "Java")
        self.assertTrue(result["coverage"]["complete"], result["coverage"])
        self.assertEqual(result["coverage"]["analyzedRules"], 6)
        snapshot = seal_extraction(result)
        goldens = {
            "productAvailable": ("active", "blocked", [False, False, True, False]),
            "orderCancelable": ("paid", "dispatched", [False, False, True, False]),
            "displayVisible": ("enabled", "hidden", [False, False, True, False]),
            "claimAllowed": ("damaged", "expired", [True, False, True, True]),
            "settlementReady": ("approved", "held", [False, False, True, False]),
            "deliveryReady": ("paid", "stocked", [False, False, False, True]),
        }
        for index, (domain, (name, (first, second, expected))) in enumerate(zip(policy.DOMAINS, goldens.items()), 3):
            rule = next(rule for rule in result["rules"] if rule["name"] == "Synthetic__" + name)
            self.assertEqual(rule["language"], "Java")
            self.assertEqual([d["name"] for d in rule["domains"]], [domain])
            self.assertEqual((rule["lineStart"], rule["lineEnd"]), (index, index))
            evidence = next(e for e in result["evidence"] if e["id"] in rule["sourceAssertionIds"])
            self.assertEqual(evidence["lineStart"], index)
            for pair, value in zip(itertools.product((False, True), repeat=2), expected):
                context = dict(zip((first, second), pair))
                actual = policy.explain_policy_result(snapshot, rule["id"], context)
                self.assertEqual(actual["value"], {"type": "bool", "value": value})

    def test_java_framework_annotations_do_not_certify_runtime_or_full_coverage(self):
        source = """import org.springframework.stereotype.Service;
@Service
public class Synthetic {
    public boolean orderCancelable(boolean dispatched) { if (dispatched) return false; return true; }
    public boolean shippingEligible(boolean paid, boolean blocked) { return paid && !blocked; }
}
"""
        result = extract_language(source, "Java")
        self.assertEqual(len(result["rules"]), 2)
        self.assertFalse(result["coverage"]["complete"])
        self.assertIn("java_annotation_semantics_unresolved", result["coverage"]["reasons"])
        self.assertTrue(all(e["runtimeStatus"] == "runtime_unknown" for e in result["evidence"]))
        snapshot = seal_extraction(result); rule = next(r for r in snapshot["rules"] if r["name"] == "Synthetic__orderCancelable")
        compared = policy.compare_policy_cases(snapshot, rule["id"], [{"dispatched": False}, {"dispatched": True}], **pins(snapshot))
        self.assertEqual(compared["status"], "incomplete_coverage")
        self.assertFalse(compared["optimality"]["optimum"])

    def test_typescript_logical_precedence_nested_branches_and_equality(self):
        source = """export function orderAllowed(active: boolean, blocked: boolean, exempt: boolean): boolean {
    if (blocked) {
        if (exempt === true) return active;
        else return false;
    }
    return active && !blocked || exempt !== false;
}
"""
        result = extract_language(source, "TypeScript")
        self.assertTrue(result["coverage"]["complete"], result["coverage"])
        snapshot = seal_extraction(result); rule = snapshot["rules"][0]
        self.assertEqual((rule["lineStart"], rule["lineEnd"]), (1, 7))
        expected = [False, True, False, False, True, True, False, True]
        for values, golden in zip(itertools.product((False, True), repeat=3), expected):
            actual = policy.explain_policy_result(snapshot, rule["id"], dict(zip(("active", "blocked", "exempt"), values)))
            self.assertEqual(actual["value"]["value"], golden)

    def test_boolean_source_free_snapshot_and_complete_finite_domain(self):
        for language, source in [
            ("Java", "class Synthetic { boolean deliveryReady(boolean paid, boolean stock) { return paid && stock; } }"),
            ("TypeScript", "function deliveryReady(paid: boolean, stock: boolean): boolean { return paid && stock; }"),
        ]:
            result = extract_language(source, language); snapshot = json.loads(json.dumps(seal_extraction(result)))
            with mock.patch("builtins.open", side_effect=AssertionError("source access forbidden")), mock.patch.object(Path, "read_text", side_effect=AssertionError("source access forbidden")), mock.patch.object(policy.privacy_guard, "load_profile", return_value=None):
                cases = [dict(zip(("paid", "stock"), pair)) for pair in itertools.product((False, True), repeat=2)]
                actual = policy.compare_policy_cases(snapshot, snapshot["rules"][0]["id"], cases, **pins(snapshot))
            self.assertEqual(actual["status"], "proven_maximum")
            self.assertEqual(actual["maximum"]["value"], {"type": "bool", "value": True})
            self.assertEqual(actual["optimality"]["scope"], "declared_function_boolean_inputs")

    def test_boolean_comments_and_strings_never_create_policy_functions(self):
        fake = "boolean hiddenPolicy(boolean x) { return x; }"
        java = "// " + fake + "\n/* " + fake + " */\nclass Synthetic {\nString marker = \"" + fake + "\";\nboolean orderAllowed(boolean active) { return active; }\n}\n"
        result = extract_language(java, "Java")
        self.assertEqual([r["name"] for r in result["rules"]], ["Synthetic__orderAllowed"])
        self.assertEqual(result["rules"][0]["lineStart"], 5)
        self.assertNotIn("hiddenPolicy", json.dumps(result))
        ts = "// function hiddenPolicy(x: boolean): boolean { return x; }\n/* fake { } */\nfunction orderAllowed(active: boolean): boolean { return active; }"
        result = extract_language(ts, "TypeScript")
        self.assertEqual([r["name"] for r in result["rules"]], ["orderAllowed"])
        self.assertEqual(result["rules"][0]["lineStart"], 3)

    def test_boolean_unsupported_fragments_abstain_without_partial_function(self):
        examples = [
            ("Java", "class Synthetic { java.math.BigDecimal orderValue(java.math.BigDecimal x) { return x; } }"),
            ("Java", "class Synthetic { boolean orderValue(int x) { return x > 0; } }"),
            ("Java", "class Synthetic { boolean orderValue(boolean x) { return callback(x); } }"),
            ("Java", "class Synthetic { boolean orderValue(boolean x) { if(x) throw new RuntimeException(); return true; } }"),
            ("Java", "class Synthetic { boolean orderValue(boolean x) { boolean y = x; return y; } }"),
            ("Java", "class Synthetic { boolean orderValue(boolean x) { return x & true; } }"),
            ("Java", "class Synthetic { synchronized boolean orderValue(boolean x) { return x; } }"),
            ("Java", "class Synthetic { boolean orderValue(boolean x) { if(x) return true; } }"),
            ("TypeScript", "function orderValue(x: number): boolean { return x > 0; }"),
            ("TypeScript", "function orderValue(x: boolean): boolean { return x == 1; }"),
            ("TypeScript", "function orderValue(x: boolean): boolean { x = !x; return x; }"),
            ("TypeScript", "function orderValue(x: boolean): boolean { return callback(x); }"),
            ("TypeScript", "function orderValue(x: boolean): boolean { return x as boolean; }"),
        ]
        for index, (language, source) in enumerate(examples):
            with self.subTest(case=index):
                result = extract_language(source, language)
                self.assertEqual(result["rules"], [])
                self.assertFalse(result["coverage"]["complete"])
                self.assertTrue(result["coverage"]["reasons"])

    def test_boolean_lexical_ambiguity_limits_and_same_line_evidence(self):
        for language, source in [
            ("Java", r"class Synthetic { // \u000a boolean orderValue(boolean x) { return x; } }"),
            ("Java", 'class Synthetic { String text = """boolean fake() { return true; }"""; }'),
            ("Java", 'class Synthetic { String text = "unterminated; boolean fake() { return true; } }'),
            ("Java", "/* unterminated boolean fake() { return true; }"),
            ("TypeScript", "const x = `function fake(): boolean { return true; }`;"),
            ("TypeScript", 'const x = "line one\nfunction fake(): boolean { return true; }";'),
        ]:
            result = extract_language(source, language)
            self.assertEqual(result["rules"], [])
            self.assertTrue(result["coverage"]["unknownDenominator"])
        for language, source in [
            ("Java", "class Synthetic { boolean first(boolean x) { return x; } boolean second(boolean y) { return !y; } }"),
            ("TypeScript", "function first(x: boolean): boolean { return x; } function second(y: boolean): boolean { return !y; }"),
        ]:
            snapshot = seal_extraction(extract_language(source, language))
            self.assertEqual(len(policy.query_policy_rules(snapshot)["evidence"]), 2)
            limited = extract_language(source, language, max_rules=1)
            self.assertEqual(limited["coverage"]["unsupportedRules"], 1)
            self.assertFalse(limited["coverage"]["complete"])
            self.assertEqual(extract_language(source, language, max_ast_nodes=2)["coverage"]["reasons"], ["ast_budget"])

    def test_boolean_duplicate_names_are_rejected_and_distinct_classes_are_unique(self):
        duplicate = "class Synthetic { boolean orderValue(boolean x) { return x; } boolean orderValue(boolean y) { return !y; } }"
        self.assertEqual(extract_language(duplicate, "Java")["rules"], [])
        distinct = "class First { boolean orderValue(boolean x) { return x; } } class Second { boolean orderValue(boolean y) { return !y; } }"
        snapshot = seal_extraction(extract_language(distinct, "Java"))
        self.assertEqual({r["name"] for r in snapshot["rules"]}, {"First__orderValue", "Second__orderValue"})


if __name__ == "__main__":
    unittest.main()
