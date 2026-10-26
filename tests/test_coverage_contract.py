"""Independent negative coverage/lineage examples without target private data."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import coverage_contract as coverage

BINDING = {"snapshotId": "snapshot:fixed", "sourceFingerprint": "a" * 64,
           "scopeDigest": "b" * 64, "analysisSpecId": "analysis:fixed"}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def pages(records, size=2):
    rows = list(records)
    result = []
    for offset in range(0, max(1, len(rows)), size):
        selected = rows[offset:offset + size]
        following = offset + len(selected) if offset + len(selected) < len(rows) else None
        result.append({**BINDING, "queryDigest": "query:fixed", "offset": offset,
                       "returned": len(selected), "total": len(rows), "records": selected,
                       "nextOffset": following, "truncated": following is not None})
    return result


def fixture():
    source_digest = digest("static final int CAP = 6;")
    expression = {"op": "literal", "type": "integer", "value": "6", "javaSuffix": None}
    fragment = {"id": "fragment:cap", "path": "example/Rules.java", "sourceDigest": source_digest,
                "span": {"lineStart": 2, "lineEnd": 2}, "expression": expression,
                "representationStatus": "represented"}
    expected = {"id": "R01", "semanticReview": "independent_source_review",
                "sourceEvidence": [{"path": fragment["path"], "sourceDigest": source_digest,
                                    "lineStart": 2, "lineEnd": 2}],
                "requiredFacets": [{"id": "cap_value", "expressionDigest": coverage.sha(expression)}]}
    document = "The declared cap is 6.\n"
    claim = {**BINDING, "ruleId": "R01", "lineStart": 1, "lineEnd": 1,
             "documentDigest": digest(document), "paragraphDigest": digest(document.rstrip("\n")),
             "ontologyIds": [fragment["id"]], "describedFacetIds": ["cap_value"],
             "claimedStatus": "full", "directSourceSupplemented": False,
             "semanticReviewId": "review:independent:1"}
    review = {**BINDING, "id": claim["semanticReviewId"], "ruleId": "R01",
              "reviewKind": "independent_source_and_paragraph_review", "reviewerId": "reviewer:synthetic",
              "verdict": "entailed", "expectationDigest": coverage.sha(expected),
              "sourceEvidenceDigest": coverage.sha(expected["sourceEvidence"]),
              "documentDigest": claim["documentDigest"], "paragraphDigest": claim["paragraphDigest"],
              "lineStart": 1, "lineEnd": 1, "coveredFacetIds": ["cap_value"]}
    return {"binding": copy.deepcopy(BINDING), "source_files": {fragment["path"]: source_digest},
            "expectations": [expected], "fragments": [fragment], "pages": pages([copy.deepcopy(fragment)]),
            "document": document, "claims": [claim], "semantic_reviews": [review]}


class CoverageContractTests(unittest.TestCase):
    def test_all_six_dimensions_and_report_are_separate_and_never_universal_complete(self):
        rows = [coverage.metric(name, 1, 1, scope="one fixed item", evidence=["synthetic"]) for name in coverage.STAGES]
        result = coverage.report(BINDING, rows)
        self.assertEqual(result["completeness"], "PARTIAL")
        self.assertEqual(result["wholeScopeCompleteness"], "UNKNOWN")
        self.assertEqual(result["measurementStatus"], "completed")
        self.assertIsNone(result["partialWeight"])
        markdown = coverage.render_markdown(result)
        self.assertEqual(markdown.count("| Numerator | Denominator |"), 6)
        self.assertEqual(markdown.count("Evidence:"), 6)
        self.assertEqual(markdown.count("Limits:"), 6)
        self.assertEqual(markdown.count("Missing:"), 6)

    def test_missing_or_duplicate_stage_rejected(self):
        rows = [coverage.metric(name, 0, None, scope="unknown") for name in coverage.STAGES]
        for malformed in (rows[:-1], rows + [rows[0]], [rows[0]] * 6):
            with self.assertRaisesRegex(ValueError, "six_separate"):
                coverage.report(BINDING, malformed)

    def test_unknown_denominator_is_not_zero_or_one_hundred_percent(self):
        for numerator, denominator in [(None, None), (1, None), (0, 0), (None, 10)]:
            result = coverage.metric("scope_files", numerator, denominator, scope="unknown")
            self.assertIsNone(result["percent"])
            self.assertEqual(result["state"], "UNKNOWN")

    def test_fractional_partial_weights_and_false_complete_rejected(self):
        for numerator, denominator in [(0.5, 1), (1, 0.5), (True, 1), (2, 1), (-1, 1)]:
            with self.assertRaises(ValueError):
                coverage.metric("policy_document", numerator, denominator, scope="sample")
        for args in [(0, 1, []), (1, 1, ["omitted"]), (None, None, [])]:
            with self.assertRaisesRegex(ValueError, "cannot_claim_complete"):
                coverage.metric("scope_files", args[0], args[1], scope="sample", missing=args[2], state="COMPLETE")
        self.assertEqual(coverage.metric("scope_files", 1, 1, scope="sample", missing=["unprocessed"])["state"], "PARTIAL")

    def test_report_does_not_trust_forged_metric_percent_or_complete(self):
        rows = [coverage.metric(name, 1, 1, scope="sample") for name in coverage.STAGES]
        rows[0]["percent"] = 999
        with self.assertRaisesRegex(ValueError, "percent_mismatch"):
            coverage.report(BINDING, rows)
        rows[0]["percent"] = 100
        rows[0]["missing"] = ["omitted"]
        with self.assertRaisesRegex(ValueError, "cannot_claim_complete"):
            coverage.report(BINDING, rows)

    def test_complete_query_delivery_binds_every_payload(self):
        records = [{"id": str(n), "sourceDigest": "c" * 64, "value": n} for n in range(5)]
        result = coverage.validate_pages(BINDING, pages(records), {r["id"]: r for r in records})
        self.assertEqual(result["state"], "COMPLETE")
        self.assertEqual(result["numerator"], 5)
        self.assertEqual(result["denominator"], 5)
        self.assertIn("not source coverage", result["scope"])

    def test_missing_first_interior_and_last_pages_cannot_pass(self):
        records = [{"id": str(n)} for n in range(5)]
        chain = pages(records)
        for selected in (chain[1:], chain[:-1], [chain[0], chain[-1]], []):
            with self.subTest(page_count=len(selected)):
                result = coverage.validate_pages(BINDING, selected)
                self.assertEqual(result["state"], "BLOCKED")
                self.assertIn("incomplete_page_chain", result["failures"])

    def test_mixed_snapshot_source_scope_spec_or_query_rejected(self):
        for key in [*coverage.BINDING_KEYS, "queryDigest", "total"]:
            chain = pages([{"id": str(n)} for n in range(4)])
            chain[1][key] = 99 if key == "total" else "changed"
            self.assertEqual(coverage.validate_pages(BINDING, chain)["state"], "BLOCKED", key)
        self.assertEqual(coverage.validate_pages(BINDING, pages([]), query_digest="different")["state"], "BLOCKED")

    def test_truncated_false_does_not_excuse_missing_rows(self):
        chain = pages([{"id": "a"}, {"id": "b"}], size=1)[:1]
        chain[0].update(truncated=False, nextOffset=None)
        result = coverage.validate_pages(BINDING, chain)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("pagination_metadata_inconsistent", result["failures"])

    def test_duplicate_empty_terminal_and_bad_counts_rejected(self):
        records = [{"id": "a"}, {"id": "b"}]
        variants = []
        chain = pages(records, size=1); chain[1]["records"] = [records[0]]; variants.append(chain)
        chain = pages(records); chain[0]["returned"] = True; variants.append(chain)
        chain = pages(records); chain[0]["offset"] = False; variants.append(chain)
        chain = pages(records); chain.append({**chain[0], "offset": 2, "records": [], "returned": 0}); variants.append(chain)
        chain = pages(records); del chain[0]["returned"]; variants.append(chain)
        chain = pages(records); chain[0]["records"][0]["id"] = ""; variants.append(chain)
        for chain in variants:
            self.assertEqual(coverage.validate_pages(BINDING, chain)["state"], "BLOCKED")

    def test_same_id_payload_and_source_digest_mutation_rejected(self):
        records = [{"id": "a", "expression": {"value": "6"}, "sourceDigest": "c" * 64}]
        for mutate in (lambda row: row["expression"].update(value="7"), lambda row: row.update(sourceDigest="d" * 64)):
            chain = pages(copy.deepcopy(records)); mutate(chain[0]["records"][0])
            result = coverage.validate_pages(BINDING, chain, {r["id"]: r for r in records})
            self.assertEqual(result["state"], "BLOCKED")
            self.assertIn("record_payload_or_source_digest_mismatch", result["failures"])

    def test_matching_reviewed_source_ontology_mcp_paragraph_chain(self):
        result = coverage.validate_policy_document(**fixture())
        self.assertEqual(result["counts"], {"full": 1, "partial": 0, "missing": 0, "unsupported": 0})
        self.assertEqual(result["ontologyOnlyFull"], 1)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertIsNone(result["weightedScore"])

    def test_graph_and_matching_hashes_without_independent_prose_review_cannot_be_full(self):
        args = fixture(); args["semantic_reviews"] = []
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["counts"]["unsupported"], 1)
        self.assertEqual(result["ontologyOnlyFull"], 0)
        self.assertIn("independent_paragraph_semantic_review_missing_or_stale", result["rows"][0]["reasons"])

    def test_nonsense_prose_with_refreshed_claim_hashes_invalidates_previous_review(self):
        args = fixture(); args["document"] = "Unrelated statement.\n"
        args["claims"][0].update(documentDigest=digest(args["document"]), paragraphDigest=digest(args["document"].strip()))
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["counts"]["unsupported"], 1)

    def test_claim_inline_self_attestation_is_not_independent_review(self):
        args = fixture(); args["claims"][0]["semanticReviewReceipt"] = args["semantic_reviews"][0]
        args["semantic_reviews"] = []
        self.assertEqual(coverage.validate_policy_document(**args)["ontologyOnlyFull"], 0)

    def test_source_file_document_paragraph_and_binding_changes_invalidate(self):
        mutations = [lambda a: a["source_files"].update({"example/Rules.java": "d" * 64}),
                     lambda a: a.update(document=a["document"] + "New paragraph.\n"),
                     lambda a: a["claims"][0].update(paragraphDigest="d" * 64),
                     lambda a: a["binding"].update(snapshotId="new-snapshot"),
                     lambda a: a["binding"].update(sourceFingerprint="e" * 64)]
        for mutate in mutations:
            args = fixture(); mutate(args)
            result = coverage.validate_policy_document(**args)
            self.assertEqual(result["state"], "BLOCKED")
            self.assertEqual(result["ontologyOnlyFull"], 0)

    def test_same_id_mcp_forgery_cannot_pass_document_checks(self):
        args = fixture(); args["pages"][0]["records"][0]["expression"]["value"] = "99"
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["ontologyOnlyFull"], 0)
        self.assertEqual(result["counts"]["unsupported"], 1)

    def test_direct_source_supplementation_may_be_document_full_but_never_ontology_only_full(self):
        args = fixture(); args["claims"][0]["directSourceSupplemented"] = True
        args["fragments"] = []; args["pages"] = pages([]); args["claims"][0]["ontologyIds"] = []
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["counts"]["full"], 1)
        self.assertEqual(result["ontologyOnlyFull"], 0)
        self.assertEqual(result["rows"][0]["basis"], "direct_source_supplemented")

    def test_missing_or_nonboolean_source_supplementation_cannot_be_ontology_only_full(self):
        for value in (None, "false", "true", 0, 1):
            args = fixture()
            if value is None:
                del args["claims"][0]["directSourceSupplemented"]
            else:
                args["claims"][0]["directSourceSupplemented"] = value
            result = coverage.validate_policy_document(**args)
            self.assertEqual(result["ontologyOnlyFull"], 0)
            self.assertEqual(result["rows"][0]["basis"], "unverified")
            self.assertIn("source_supplementation_basis_unverified", result["rows"][0]["reasons"])

    def test_partial_and_missing_are_separate_without_half_scores(self):
        args = fixture()
        args["expectations"][0]["requiredFacets"].append({"id": "additional_condition", "expressionDigest": "e" * 64})
        args["semantic_reviews"][0]["expectationDigest"] = coverage.sha(args["expectations"][0])
        args["claims"][0]["claimedStatus"] = "partial"
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["counts"]["partial"], 1)
        self.assertEqual(result["counts"]["full"], 0)
        self.assertIsNone(result["weightedScore"])
        args["claims"] = []
        self.assertEqual(coverage.validate_policy_document(**args)["counts"]["missing"], 1)

    def test_partial_expression_is_never_exact_semantic_support(self):
        args = fixture(); args["fragments"][0]["representationStatus"] = "partial"
        args["pages"] = pages(copy.deepcopy(args["fragments"]))
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["counts"]["unsupported"], 1)
        self.assertIn("claimed_full_not_supported", result["rows"][0]["reasons"])

    def test_duplicate_claim_fragment_expectation_or_review_ids_are_not_overwritten(self):
        for key in ("claims", "fragments", "expectations", "semantic_reviews"):
            args = fixture(); args[key].append(copy.deepcopy(args[key][0]))
            result = coverage.validate_policy_document(**args)
            self.assertEqual(result["state"], "BLOCKED", key)
            self.assertTrue(result["failures"], key)
            self.assertEqual(result["ontologyOnlyFull"], 0, key)

    def test_missing_source_identity_cannot_match_missing_mapping_keys(self):
        args = fixture(); args["expectations"][0]["sourceEvidence"] = [{"path": "absent.java", "lineStart": 1, "lineEnd": 2}]
        args["semantic_reviews"][0].update(expectationDigest=coverage.sha(args["expectations"][0]), sourceEvidenceDigest=coverage.sha(args["expectations"][0]["sourceEvidence"]))
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["ontologyOnlyFull"], 0)
        self.assertIn("source_changed_or_unbound", result["rows"][0]["reasons"])

    def test_review_cannot_cover_unknown_or_duplicate_facets(self):
        for names in (["cap_value", "not-reviewed"], ["cap_value", "cap_value"]):
            args = fixture(); args["semantic_reviews"][0]["coveredFacetIds"] = names
            self.assertEqual(coverage.validate_policy_document(**args)["ontologyOnlyFull"], 0)

    def test_unmatched_claim_is_unsupported_and_blocks_completion(self):
        args = fixture(); args["claims"].append({**args["claims"][0], "ruleId": "invented"})
        result = coverage.validate_policy_document(**args)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["unmatchedClaims"], ["invented"])


if __name__ == "__main__":
    unittest.main()
