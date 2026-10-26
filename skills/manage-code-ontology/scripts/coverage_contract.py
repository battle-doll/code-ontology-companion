"""Evidence-bound coverage receipts. Success is never inferred from a graph count.

The validator checks supplied independent expectations and exact provenance. It
does not discover every business rule or judge free-form prose automatically.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

VERSION = "coverage-contract-1"
STAGES = ("scope_files", "declarations_types", "exact_calls", "policy_semantics",
          "mcp_delivery", "policy_document")
BINDING_KEYS = ("snapshotId", "sourceFingerprint", "scopeDigest", "analysisSpecId")


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def metric(name, numerator, denominator, *, scope, missing=(), evidence=(), limits=(), state=None):
    if (numerator is not None and (type(numerator) is not int or numerator < 0)
            or denominator is not None and (type(denominator) is not int or denominator < 0)
            or numerator is not None and denominator is not None and numerator > denominator):
        raise ValueError("invalid_coverage_denominator")
    if state not in {None, "UNKNOWN", "COMPLETE", "PARTIAL", "BLOCKED"}:
        raise ValueError("invalid_coverage_state")
    missing = list(missing)
    percentage = round(100 * numerator / denominator, 2) if numerator is not None and denominator else None
    inferred = "UNKNOWN" if percentage is None else "COMPLETE" if numerator == denominator and not missing else "PARTIAL"
    if state == "COMPLETE" and inferred != "COMPLETE":
        raise ValueError("incomplete_metric_cannot_claim_complete")
    return {"stage": name, "numerator": numerator, "denominator": denominator, "percent": percentage,
            "scope": scope, "missing": missing, "evidence": list(evidence), "limitations": list(limits),
            "state": state or inferred}


def validate_binding(expected, observed):
    return [key + "_mismatch_or_missing" for key in BINDING_KEYS
            if not isinstance(expected.get(key), str) or not expected[key] or observed.get(key) != expected[key]]


def validate_pages(binding, pages, expected_records=None, *, query_digest=None):
    """Validate an entire query, including missing first/last/interior pages.

    A complete subset query proves only that query's delivery. All source rule
    coverage remains separate. Optional expected records are sealed payloads.
    """
    failures, ids, records = [], [], {}
    total = query = None
    offset = 0
    terminal_seen = False
    for page in pages:
        if not isinstance(page, dict):
            failures.append("invalid_page")
            continue
        if terminal_seen:
            failures.append("page_after_terminal")
        failures.extend(validate_binding(binding, page))
        rows = page.get("records")
        if not isinstance(rows, list):
            failures.append("records_missing")
            continue
        if total is None:
            total, query = page.get("total"), page.get("queryDigest")
        if type(total) is not int or total < 0 or type(page.get("total")) is not int or page.get("total") != total or not isinstance(query, str) or not query or page.get("queryDigest") != query:
            failures.append("query_identity_or_total_changed")
        selected_query = query_digest if query_digest is not None else binding.get("queryDigest")
        if selected_query is not None and page.get("queryDigest") != selected_query:
            failures.append("requested_query_digest_mismatch")
        if type(page.get("offset")) is not int or page.get("offset") != offset or type(page.get("returned")) is not int or page.get("returned") != len(rows):
            failures.append("page_gap_overlap_or_count_mismatch")
        for row in rows:
            identity = row.get("id") if isinstance(row, dict) else None
            if not isinstance(identity, str) or not identity or identity in records:
                failures.append("missing_or_duplicate_record_identity")
                continue
            records[identity] = row
            ids.append(identity)
            if expected_records is not None and expected_records.get(identity) != row:
                failures.append("record_payload_or_source_digest_mismatch")
        offset += len(rows)
        expected_next = offset if type(total) is int and offset < total else None
        actual_next = page.get("nextOffset")
        if (actual_next != expected_next or (actual_next is not None and type(actual_next) is not int)
                or page.get("truncated") is not (expected_next is not None)):
            failures.append("pagination_metadata_inconsistent")
        if expected_next is not None and not rows:
            failures.append("nonterminal_empty_page")
        terminal_seen = expected_next is None
    if not pages or type(total) is not int or offset != total:
        failures.append("incomplete_page_chain")
    if expected_records is not None and set(expected_records) != set(records):
        failures.append("expected_record_set_not_delivered")
    return {"state": "BLOCKED" if failures else "COMPLETE", "numerator": len(ids), "denominator": total,
            "queryDigest": query, "recordIds": ids, "failures": sorted(set(failures)),
            "receiptDigest": sha(pages), "scope": "one exact pinned query; not source coverage"}


def validate_policy_document(binding, source_files, expectations, fragments, pages, document, claims,
                             *, semantic_reviews=()):
    """Verify mechanically reviewable facet claims, not arbitrary prose truth.

    Each expectation is independently reviewed against an exact source digest.
    Every full claim must bind its actual paragraph bytes and all reviewed facet
    expression digests to represented ontology fragments delivered by MCP.
    Direct-source supplementation is explicit and excluded from ontology-only
    full counts. Unsupported/free-form meanings remain UNKNOWN.

    Independent prose review receipts are a separate trusted input, never a
    boolean or a self-declared field inside a claim. They bind the exact source
    expectations, paragraph, scope and covered facets. Receipt hashes prove
    freshness only; independent review provenance still requires human trust.
    """
    global_failures = []

    def unique_rows(rows, key, reason):
        values = {}
        for row in rows:
            identity = row.get(key) if isinstance(row, dict) else None
            if not isinstance(identity, str) or not identity or identity in values:
                global_failures.append(reason)
                continue
            values[identity] = row
        return values

    by_id = unique_rows(fragments, "id", "missing_or_duplicate_fragment_identity")
    expectation_map = unique_rows(expectations, "id", "missing_or_duplicate_expectation_identity")
    claim_map = unique_rows(claims, "ruleId", "missing_or_duplicate_claim_identity")
    review_map = unique_rows(semantic_reviews, "id", "missing_or_duplicate_review_identity")
    delivery = validate_pages(binding, pages, expected_records=by_id)
    delivered = set(delivery["recordIds"]) if delivery["state"] == "COMPLETE" else set()
    document_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()
    lines = document.splitlines()
    rows = []
    for expected in expectation_map.values():
        rid = expected["id"]
        claim = claim_map.get(rid)
        reasons = list(global_failures)
        source = expected.get("sourceEvidence", [])
        if not isinstance(source, list):
            source = []
        if not source or any(not isinstance(item, dict) or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sourceDigest"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sourceDigest"])
            or item["path"] not in source_files or source_files[item["path"]] != item["sourceDigest"]
            or type(item.get("lineStart")) is not int or type(item.get("lineEnd")) is not int
            or not 1 <= item["lineStart"] <= item["lineEnd"] for item in source):
            reasons.append("source_changed_or_unbound")
        facets = expected.get("requiredFacets", [])
        if not isinstance(facets, list):
            facets = []
        facet_ids = [facet.get("id") for facet in facets if isinstance(facet, dict)]
        if (not facets or len(facet_ids) != len(facets) or any(not isinstance(x, str) or not x for x in facet_ids)
                or len(set(facet_ids)) != len(facet_ids) or expected.get("semanticReview") != "independent_source_review"):
            reasons.append("semantic_denominator_not_independently_reviewed")
        status = "missing"
        basis = "ontology_only"
        matched = []
        reviewed = []
        if claim:
            if type(claim.get("directSourceSupplemented")) is not bool:
                reasons.append("source_supplementation_basis_unverified")
                basis = "unverified"
            else:
                basis = "direct_source_supplemented" if claim["directSourceSupplemented"] else "ontology_only"
            reasons.extend(validate_binding(binding, claim))
            start, end = claim.get("lineStart"), claim.get("lineEnd")
            valid_span = type(start) is int and type(end) is int and 1 <= start <= end <= len(lines)
            actual = "\n".join(lines[start-1:end]) if valid_span else ""
            if claim.get("documentDigest") != document_hash or not valid_span or claim.get("paragraphDigest") != hashlib.sha256(actual.encode("utf-8")).hexdigest():
                reasons.append("document_or_paragraph_changed")
            review = review_map.get(claim.get("semanticReviewId"), {})
            review_valid = (bool(review) and not validate_binding(binding, review)
                and review.get("ruleId") == rid and review.get("reviewKind") == "independent_source_and_paragraph_review"
                and isinstance(review.get("reviewerId"), str) and bool(review["reviewerId"])
                and review.get("verdict") == "entailed"
                and review.get("expectationDigest") == sha(expected)
                and review.get("sourceEvidenceDigest") == sha(source)
                and review.get("documentDigest") == document_hash
                and review.get("paragraphDigest") == hashlib.sha256(actual.encode("utf-8")).hexdigest()
                and review.get("lineStart") == start and review.get("lineEnd") == end
                and isinstance(review.get("coveredFacetIds"), list)
                and all(isinstance(item, str) for item in review["coveredFacetIds"])
                and len(set(review["coveredFacetIds"])) == len(review["coveredFacetIds"])
                and set(review["coveredFacetIds"]) <= set(facet_ids))
            if not review_valid:
                reasons.append("independent_paragraph_semantic_review_missing_or_stale")
            else:
                reviewed = review["coveredFacetIds"]
            ontology_ids = claim.get("ontologyIds", [])
            if (not isinstance(ontology_ids, list) or any(not isinstance(x, str) for x in ontology_ids)
                    or len(set(ontology_ids)) != len(ontology_ids)):
                reasons.append("invalid_or_duplicate_ontology_references")
                ontology_ids = []
            described = claim.get("describedFacetIds", [])
            if (not isinstance(described, list) or any(not isinstance(x, str) for x in described)
                    or len(set(described)) != len(described) or not set(described) <= set(reviewed)):
                reasons.append("described_facets_not_independently_attested")
                described = []
            for facet in facets:
                if not isinstance(facet, dict):
                    continue
                for identifier in ontology_ids:
                    fragment = by_id.get(identifier, {})
                    span = fragment.get("span", {})
                    locator_matches = (isinstance(span, dict) and type(span.get("lineStart")) is int
                        and type(span.get("lineEnd")) is int and span["lineStart"] >= 1
                        and span["lineEnd"] >= span["lineStart"] and any(isinstance(item, dict)
                        and type(item.get("lineStart")) is int and type(item.get("lineEnd")) is int
                        and fragment.get("path") == item.get("path")
                        and fragment.get("sourceDigest") == item.get("sourceDigest")
                        and span.get("lineStart", 0) >= item.get("lineStart", 1)
                        and span.get("lineEnd", 0) <= item.get("lineEnd", 0) for item in source))
                    if (identifier in delivered and locator_matches and fragment.get("representationStatus") == "represented"
                        and facet.get("expressionDigest") and sha(fragment.get("expression")) == facet["expressionDigest"]
                        and facet.get("id") in described):
                        matched.append(facet["id"])
                        break
            supported = set(described) if basis == "direct_source_supplemented" else set(matched)
            if claim.get("claimedStatus") not in {"full", "partial", "missing"}:
                reasons.append("invalid_claim_status")
            if claim.get("claimedStatus") == "full" and len(supported) != len(facets):
                reasons.append("claimed_full_not_supported")
            if reasons:
                status = "unsupported"
            elif len(supported) == len(facets) and facets:
                status = "full"
            elif supported:
                status = "partial"
            else:
                status = "unsupported"
        rows.append({"id": rid, "status": status, "basis": basis, "matchedFacets": sorted(set(matched)),
            "independentlyReviewedFacets": sorted(set(reviewed)),
            "requiredFacets": len(facets) if facets else None, "reasons": sorted(set(reasons)),
            "sourceEvidence": source, "ontologyIds": claim.get("ontologyIds", []) if claim else [],
            "documentDigest": document_hash, "paragraphDigest": claim.get("paragraphDigest") if claim else None})
    extras = sorted(set(claim_map) - set(expectation_map))
    counts = Counter(row["status"] for row in rows)
    return {"state": "BLOCKED" if global_failures or extras or delivery["state"] != "COMPLETE" or any(row["reasons"] for row in rows) else "PARTIAL",
        "rows": rows, "counts": {key: counts[key] for key in ("full", "partial", "missing", "unsupported")},
        "ontologyOnlyFull": sum(row["status"] == "full" and row["basis"] == "ontology_only" for row in rows),
        "denominator": len(expectations), "unmatchedClaims": extras, "failures": sorted(set(global_failures)), "weightedScore": None,
        "delivery": delivery, "semanticProseJudgment": "Requires independent review; hashes alone do not prove prose entailment."}


def report(binding, metrics, *, unresolved=(), measurement_status="completed"):
    if set(row["stage"] for row in metrics) != set(STAGES) or len(metrics) != len(STAGES):
        raise ValueError("six_separate_coverage_stages_required")
    if any(not binding.get(key) for key in BINDING_KEYS):
        raise ValueError("coverage_binding_incomplete")
    for row in metrics:
        checked = metric(row["stage"], row["numerator"], row["denominator"], scope=row["scope"],
                         missing=row["missing"], evidence=row["evidence"], limits=row["limitations"], state=row["state"])
        if row["percent"] != checked["percent"]:
            raise ValueError("coverage_percent_mismatch")
    state = "BLOCKED" if any(row["state"] == "BLOCKED" for row in metrics) else "PARTIAL"
    # No automatic universal completeness claim: independent scope closure and
    # whole-business semantics cannot be established by these bounded metrics.
    value = {"schemaVersion": 1, "contractVersion": VERSION, **binding,
        "measurementStatus": measurement_status, "completeness": state, "metrics": metrics,
        "remaining": list(unresolved), "wholeScopeCompleteness": "UNKNOWN",
        "runtimeExecution": "NOT_OBSERVED", "partialWeight": None}
    value["reportDigest"] = sha(value)
    return value


def render_markdown(value):
    lines = ["# Coverage verification", "", "Completeness: **" + value["completeness"] + "**",
             "", "Measurement completion is separate from source and policy completeness.", ""]
    for key in BINDING_KEYS:
        lines.append("- " + key + ": `" + str(value[key]) + "`")
    for row in value["metrics"]:
        def text(x):
            return ("UNKNOWN" if x is None else str(x)).replace("|", "\\|").replace("\n", " ")
        lines.extend(["", "## " + row["stage"], "", "| Numerator | Denominator | Percent | State | Scope |",
            "|---:|---:|---:|---|---|", "| " + " | ".join(text(row[k]) for k in ("numerator", "denominator", "percent", "state", "scope")) + " |",
            "", "Missing: " + text(row["missing"]), "", "Evidence: " + text(row["evidence"]), "", "Limits: " + text(row["limitations"])])
    lines.extend(["", "## Remaining", "", *["- " + str(x) for x in value["remaining"]], ""])
    return "\n".join(lines)
