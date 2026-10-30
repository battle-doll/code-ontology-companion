"""Read-only, permission-projected business knowledge over immutable source pins.

Business approval is an independent operator decision. It never changes the
authority of an extracted function or proves runtime behavior.
"""
from __future__ import annotations

import copy
import re
from decimal import Decimal

_store = _semantics = _source = _policy = _acl = _guard = None
PINS = ("sourceSnapshotId", "sourceManifestSha256", "sourceFingerprint", "analysisSpecId",
        "businessSnapshotId", "businessDigest", "businessSpecId", "businessSpecHash")
KINDS = ("business_object_type", "business_property", "business_relation", "business_policy",
         "business_transition", "business_claim", "business_conflict")


class BusinessQueryError(ValueError):
    pass


def configure(*, store, semantics, pipeline_store, policy, acl, privacy_guard):
    global _store, _semantics, _source, _policy, _acl, _guard
    _store, _semantics, _source, _policy, _acl, _guard = store, semantics, pipeline_store, policy, acl, privacy_guard


def _safe(value):
    _guard.ensure_public_safe(value)
    return value


def _pick(value, fields):
    return {k: copy.deepcopy(value[k]) for k in fields if k in value}


def _coverage(value):
    # No free-form source locator or receipt can pass this summary boundary.
    fields = ("state", "scope", "denominator", "numerator", "ratio", "selected", "accepted",
              "omitted", "unsupported", "rejected", "unknown", "globalCompleteness",
              "semanticCompleteness", "reviewAccepted", "previousReviewInvalidated", "revoked",
              "conflicted", "unknownDenominator", "numeratorMeaning")
    result = {k: copy.deepcopy(value[k]) for k in fields if k in value and
              (value[k] is None or type(value[k]) in (str, int, float, bool))}
    if "sourceDeclarationCoverage" in value:
        result["sourceDeclarationCoverage"] = _policy.declaration_coverage_summary(value["sourceDeclarationCoverage"])
    if "sourceFunctionProcessing" in value:
        result["sourceFunctionProcessing"] = _policy.function_processing_summary(value["sourceFunctionProcessing"])
    if isinstance(value.get("sourceCandidates"), dict):
        result["sourceCandidates"] = _coverage(value["sourceCandidates"])
    if isinstance(value.get("semanticStatus"), dict):
        allowed = ("candidateRecords", "approvedMeanings", "unknownFacets", "supportedFacets", "declaredFacets", "conflictedRecords", "revokedRecords")
        result["semanticStatus"] = {k:value["semanticStatus"][k] for k in allowed if type(value["semanticStatus"].get(k)) is int}
    result["globalCompleteness"] = "UNKNOWN"
    if isinstance(value.get("processingReconciliation"),dict):
        raw=value["processingReconciliation"]
        result["processingReconciliation"]=_pick(raw,("scopeId","selectedInputs","accountedInputs","missingInputs","reconciled","wholeBusinessCompleteness"))
        for key,allowed in (("outcomeCounts",("accepted","unsupported","rejected","conflicted","duplicate","omitted")),("lifecycleCounts",("revoked","invalidated"))):
            result["processingReconciliation"][key]={name:raw[key][name]for name in allowed if type(raw.get(key,{}).get(name))is int and raw[key][name]>=0}
    if value.get("processingContract")is True:
        result["processingAccounting"]={"scope":"recorded_original_inputs","historicalScope":"UNKNOWN"if value.get("processingPriorScopeUnknown")else"explicit",
            "reconciled":value.get("processingReconciled",False)and not value.get("processingPriorScopeUnknown",False),
            "scopes":[_pick(s,("scopeId","kind","denominator","accounted"))for s in value.get("processingScopeCounts",[])],
            "outcomeCounts":{key:number for key,number in value.get("processingOutcomeCounts",{}).items()if key in("accepted","unsupported","rejected","conflicted","duplicate","omitted","revoked","invalidated")and type(number)is int},
            "wholeBusinessCompleteness":"UNKNOWN"}
    return result


def _coverage_entry(value):
    result=_pick(value,("recordId","inputIndex","status","reason","count","processingScopeId","outcomeClass"))
    if "sourceRecordId" in value or "sourceKind" in value:
        result.update(_semantics.outcome_source_fields(value.get("sourceRecordId"),value.get("sourceKind")))
    return result


def _anchor(value, evidence):
    keys = ("recordId", "inlinePointer", "targetDigest", "recordDigest") if evidence else ("recordId",)
    if evidence:
        keys += ("sourceSnapshotId", "sourceManifestSha256", "sourceFingerprint", "analysisSpecId",
                 "path", "sourceSha256", "sourceRangeOrSpan", "dependencyClosureDigest")
    return _pick(value, keys)


def _project_value(value, evidence):
    """Project validated values recursively, including contracts nested in lists.

    Source digests bind executable mappings internally. A policy-only view is
    a presentation projection, not a reusable review/provenance manifest.
    """
    if evidence:
        return copy.deepcopy(value)
    if isinstance(value, list):
        return [_project_value(item, False) for item in value]
    if isinstance(value, dict):
        if value.get("type") == "formula_mapping":
            value = _pick(value, ("type", "sourceRuleId", "inputs", "outputPropertyId"))
        return {key: _project_value(item, False) for key, item in value.items()}
    return value


def project_record(record, *, evidence=False):
    # Preserve legacy UNKNOWN projection for unsupported typed values. Only the
    # new server-derived metadata is an integrity boundary at this seam.
    _semantics._validate_canonical_contracts(record)
    result = _pick(record, ("id", "kind", "name", "namespace", "domain", "conceptKey", "support",
                           "businessApproval", "subject", "object", "role", "cardinality", "aliases"))
    # These values are validated by the store grammar; revalidate nested values
    # before consumption so future producer additions cannot widen this boundary.
    facets = {}; omissions = []
    for name in _semantics.FACETS.get(record.get("kind"), ()):
        facet = record.get("facets", {}).get(name, {})
        status = facet.get("status", "UNKNOWN")
        if status not in ("UNKNOWN", "NOT_APPLICABLE", "SOURCE_SUPPORTED", "DECLARED"):
            status = "UNKNOWN"
        item = {"status": status}
        if status in ("SOURCE_SUPPORTED", "DECLARED"):
            try:
                item["value"] = _project_value(_semantics._typed_value(facet["value"], allow_reference=status == "SOURCE_SUPPORTED"), evidence)
            except (ValueError, KeyError, TypeError):
                item = {"status": "UNKNOWN", "reason": "unsupported_consumer_value"}
                omissions.append(name)
        for key in ("reason", "basis"):
            if isinstance(facet.get(key), str):
                if evidence or (key == "reason" and facet[key] in {"business_meaning_not_reviewed"}):
                    item[key] = facet[key]
                else:
                    item[key] = "review_details_require_evidence"
        item["sourceAnchors"] = [_anchor(a, evidence) for a in facet.get("sourceAnchors", [])]
        facets[name] = item
    if not evidence and "aliases" in result:
        result["aliases"] = [_pick(alias, ("target", "relation")) for alias in result["aliases"]]
    result["facets"] = facets
    if "canonicalContracts" in record: result["canonicalContracts"] = copy.deepcopy(record["canonicalContracts"])
    result["sourceAnchors"] = [_anchor(a, evidence) for a in record.get("sourceAnchors", [])]
    result["projectionOmissions"] = omissions
    result["evidenceDetailsWithheld"] = not evidence
    result["businessMeaningComplete"] = False
    result["runtimeStatus"] = "NOT_OBSERVED"
    result["executionAuthorization"] = "NOT_PROVIDED"
    if evidence:
        result.update(_pick(record, ("contentDigest", "approvalReceiptId", "limitations")))
    return _safe(result)


def _metadata(raw):
    return {**_pick(raw, PINS + ("status", "recordCount", "sourceAccess", "businessCompletion")),
            "coverage": _coverage(raw.get("coverage", {})), "globalCompleteness": "UNKNOWN",
            "runtimeStatus": "NOT_OBSERVED", "executionAuthorization": "NOT_PROVIDED"}


def export_projection_contract():
    """Explicit export profile; the verified module hash pins its implementation."""
    return "companion.authorized-policy-projection.v1"


def _projection_keys(value, allowed, required=()):
    if type(value) is not dict or set(value)-set(allowed) or set(required)-set(value):
        raise BusinessQueryError("policy_projection_producer_unclassified")


def _projection_anchor(value):
    keys=(*_semantics.PIN_KEYS,"recordId","recordDigest","inlinePointer","targetDigest",
          "path","sourceSha256","sourceRangeOrSpan","dependencyClosureDigest")
    _projection_keys(value,keys,keys)
    if any(type(child) is not str for key,child in value.items() if key!="sourceRangeOrSpan"):
        raise BusinessQueryError("policy_projection_producer_unclassified")
    span=value["sourceRangeOrSpan"]
    if type(span) is not dict or set(span) not in ({"charStart","charEnd"},
            {"lineStart","lineEnd"},{"charStart","charEnd","byteStart","byteEnd"}):
        raise BusinessQueryError("policy_projection_producer_unclassified")
    if any(type(number) is not int for number in span.values()):
        raise BusinessQueryError("policy_projection_producer_unclassified")


def _projection_counts(value, allowed):
    _projection_keys(value,allowed)
    if any(type(number) is not int or number<0 for number in value.values()):
        raise BusinessQueryError("policy_projection_producer_unclassified")


def _projection_scopes(value):
    if type(value) is not list:raise BusinessQueryError("policy_projection_producer_unclassified")
    for scope in value:
        _projection_keys(scope,("scopeId","kind","denominator","accounted"))
        if any(type(child) in (dict,list) for child in scope.values()):raise BusinessQueryError("policy_projection_producer_unclassified")


def _projection_coverage(value):
    # Known private producer fields are classified here even when _coverage
    # withholds them. Unknown fields never silently inherit that classification.
    scalar=("state","scope","denominator","numerator","ratio","selected","accepted","omitted",
        "unsupported","rejected","unknown","globalCompleteness","semanticCompleteness","reviewAccepted",
        "previousReviewInvalidated","revoked","conflicted","unknownDenominator","numeratorMeaning",
        "processed","visited","storageCompleteness","inventoryAccounting","entryCount","entriesTruncated",
        "entriesStorage","processingEntryCount","processingContract","processingScopeId",
        "processingPriorScopeUnknown","processingReconciled")
    nested=("entries","limitations","sourceDeclarationCoverage","sourceFunctionProcessing","sourceCandidates",
        "semanticStatus","processingReconciliation","processingScopes","processingScopeCounts","processingOutcomeCounts")
    _projection_keys(value,scalar+nested)
    if any(type(value[key]) in (dict,list) for key in scalar if key in value):
        raise BusinessQueryError("policy_projection_producer_unclassified")
    if "entries" in value:
        if type(value["entries"]) is not list:raise BusinessQueryError("policy_projection_producer_unclassified")
        for entry in value["entries"]:
            _projection_keys(entry,("recordId","inputIndex","status","reason","count","processingScopeId",
                "outcomeClass","sourceRecordId","sourceKind"))
            if any(type(child) in (dict,list) for child in entry.values()):
                raise BusinessQueryError("policy_projection_producer_unclassified")
    if "limitations" in value and (type(value["limitations"]) is not list or any(type(v) is not str for v in value["limitations"])):
        raise BusinessQueryError("policy_projection_producer_unclassified")
    if "sourceDeclarationCoverage" in value:_policy.declaration_coverage_summary(value["sourceDeclarationCoverage"])
    if "sourceFunctionProcessing" in value:_policy.function_processing_summary(value["sourceFunctionProcessing"])
    if "sourceCandidates" in value:_projection_coverage(value["sourceCandidates"])
    if "semanticStatus" in value:_projection_counts(value["semanticStatus"],
        ("candidateRecords","approvedMeanings","unknownFacets","supportedFacets","declaredFacets","conflictedRecords","revokedRecords"))
    outcomes=("accepted","unsupported","rejected","conflicted","duplicate","omitted","revoked","invalidated")
    if "processingOutcomeCounts" in value:_projection_counts(value["processingOutcomeCounts"],outcomes)
    for key in ("processingScopes","processingScopeCounts"):
        if key in value:_projection_scopes(value[key])
    if "processingReconciliation" in value:
        item=value["processingReconciliation"]
        _projection_keys(item,("scopeId","selectedInputs","accountedInputs","missingInputs","reconciled",
            "wholeBusinessCompleteness","outcomeCounts","lifecycleCounts","identity"))
        for key,allowed in (("outcomeCounts",outcomes[:6]),("lifecycleCounts",outcomes[6:])):
            if key in item:_projection_counts(item[key],allowed)
        if any(type(child) in (dict,list) for key,child in item.items() if key not in ("outcomeCounts","lifecycleCounts")):
            raise BusinessQueryError("policy_projection_producer_unclassified")


def _projection_diagnostics(value):
    _projection_keys(value,("schemaVersion","reviewManifestDigest","selectedInputs","outcomeCounts","entries"),
        ("schemaVersion","reviewManifestDigest","selectedInputs","outcomeCounts","entries"))
    if (type(value["schemaVersion"]) is not int or value["schemaVersion"]!=1
            or type(value["selectedInputs"]) is not int or not 0<=value["selectedInputs"]<=10000
            or type(value["entries"]) is not list or len(value["entries"])>value["selectedInputs"]
            or type(value["reviewManifestDigest"]) is not str or not re.fullmatch(r"[0-9a-f]{64}",value["reviewManifestDigest"])):
        raise BusinessQueryError("policy_projection_producer_unclassified")
    _projection_counts(value["outcomeCounts"],_semantics.REVIEW_OUTCOMES)
    if set(value["outcomeCounts"])!=_semantics.REVIEW_OUTCOMES or sum(value["outcomeCounts"].values())!=value["selectedInputs"]:
        raise BusinessQueryError("policy_projection_producer_unclassified")
    seen=set()
    for entry in value["entries"]:
        keys=("inputIndex","status","attemptedRecordId","diagnosticCodes","rejectionReason","sourceAnchors")
        _projection_keys(entry,keys,keys)
        index=entry["inputIndex"]
        if (type(index) is not int or not 0<=index<value["selectedInputs"] or index in seen or entry["status"]!="rejected"
                or type(entry["diagnosticCodes"]) is not list or not 1<=len(entry["diagnosticCodes"])<=3
                or any(type(code) is not str or code not in _semantics.REVIEW_DIAGNOSTIC_CODES for code in entry["diagnosticCodes"])
                or entry["rejectionReason"] not in _semantics.REVIEW_REJECTION_REASONS
                or type(entry["attemptedRecordId"]) is not str or not re.fullmatch(r"business:[0-9a-f]{64}",entry["attemptedRecordId"])
                or type(entry["sourceAnchors"]) is not list):
            raise BusinessQueryError("policy_projection_producer_unclassified")
        seen.add(index)
        for anchor in entry["sourceAnchors"]:_projection_anchor(anchor)


def validate_policy_projection_input(value, *, kind="record"):
    """Closed producer classifier for export, separate from legacy MCP fallback.

    Store/reader pin and source integrity checks remain mandatory. This function
    never grants access, infers approval, reads a source or returns private data.
    """
    try:
        _semantics.canonical(value)
        if kind=="record":
            allowed=("id","kind","name","namespace","domain","conceptKey","support","businessApproval",
                "subject","object","role","cardinality","aliases","facets","sourceAnchors","runtimeStatus",
                "executionAuthorization","limitations","contentDigest","approvalReceiptId","reviewedMeaning",
                "inputIndex","processingScopeId","approvalScope","sourceKind","sourceRecordId","ruleId","canonicalContracts")
            _projection_keys(value,allowed,("id","kind","facets","sourceAnchors"))
            _semantics.validate_record_values(value)
            for facet in value["facets"].values():
                _projection_keys(facet,("status","value","reason","basis","sourceAnchors"),("status",))
                for anchor in facet.get("sourceAnchors",[]):_projection_anchor(anchor)
                for key in ("reason","basis"):
                    if key in facet and type(facet[key]) is not str:raise BusinessQueryError("policy_projection_producer_unclassified")
            for anchor in value["sourceAnchors"]:_projection_anchor(anchor)
            for alias in value.get("aliases",[]):
                _projection_keys(alias,("target","relation","basis"))
                if any(type(child) is not str for child in alias.values()):raise BusinessQueryError("policy_projection_producer_unclassified")
            if "limitations" in value and (type(value["limitations"]) is not list or any(type(child) is not str for child in value["limitations"])):
                raise BusinessQueryError("policy_projection_producer_unclassified")
            if type(value.get("cardinality")) is dict:_projection_keys(value["cardinality"],("min","max"))
            nested={"aliases","facets","sourceAnchors","limitations","cardinality","canonicalContracts"}
            if any(type(child) in (dict,list) for key,child in value.items() if key not in nested):
                raise BusinessQueryError("policy_projection_producer_unclassified")
        elif kind=="metadata":
            allowed=PINS+("schemaVersion","status","parentBusinessSnapshotId","parentBusinessDigest","recordCount",
                "coverage","reviewManifestDigest","sourceAccess","sourceCompletion","businessCompletion","globalCompleteness",
                "dependencyClosureDigest","receiptDigest","artifacts","currentReviewDiagnostics","dependencyClosureEncoding","storage")
            _projection_keys(value,allowed,PINS+("schemaVersion","coverage","recordCount"))
            if (type(value["schemaVersion"]) is not int or value["schemaVersion"] not in (1,2)
                    or value["businessSpecId"]!=_semantics.VERSION):
                raise BusinessQueryError("policy_projection_producer_unclassified")
            _projection_coverage(value["coverage"])
            if "currentReviewDiagnostics" in value:_projection_diagnostics(value["currentReviewDiagnostics"])
            if "storage" in value:
                storage=value["storage"]
                _projection_keys(storage,("format","chunkRecordLimit","artifactByteLimit","shards"),
                    ("format","chunkRecordLimit","artifactByteLimit","shards"))
                if storage["format"]!="sqlite-shards-v2" or type(storage["shards"]) is not list:
                    raise BusinessQueryError("policy_projection_producer_unclassified")
                if any(type(child) in (dict,list) for key,child in storage.items() if key!="shards"):
                    raise BusinessQueryError("policy_projection_producer_unclassified")
                for shard in storage["shards"]:
                    _projection_keys(shard,("name","table","count","first","last","bytes"))
                    if any(type(child) in (dict,list) for child in shard.values()):raise BusinessQueryError("policy_projection_producer_unclassified")
            if "artifacts" in value:
                if type(value["artifacts"]) is not dict or any(not re.fullmatch(
                        r"(?:records|coverage|processing)-[0-9]{6}\.sqlite|(?:records|coverage|receipt)\.json",name)
                        or type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}",digest) for name,digest in value["artifacts"].items()):
                    raise BusinessQueryError("policy_projection_producer_unclassified")
            nested={"coverage","currentReviewDiagnostics","storage","artifacts"}
            if any(type(child) in (dict,list) for key,child in value.items() if key not in nested):
                raise BusinessQueryError("policy_projection_producer_unclassified")
        else:raise BusinessQueryError("policy_projection_producer_unclassified")
    except (ValueError,KeyError,TypeError,RecursionError):
        raise BusinessQueryError("policy_projection_producer_unclassified") from None
    return True


def policy_projection_record(value):
    validate_policy_projection_input(value,kind="record")
    return project_record(value,evidence=False)


def policy_projection_metadata(value):
    validate_policy_projection_input(value,kind="metadata")
    return _safe(_metadata(value))


def policy_projection_diagnostics(value):
    try:
        _semantics.canonical(value);_projection_diagnostics(value)
    except (ValueError,KeyError,TypeError,RecursionError):
        raise BusinessQueryError("policy_projection_producer_unclassified") from None
    entries=[_pick(entry,("inputIndex","status","attemptedRecordId","diagnosticCodes","rejectionReason")) for entry in value["entries"]]
    return _safe({"selectedInputs":value["selectedInputs"],"outcomeCounts":copy.deepcopy(value["outcomeCounts"]),
        "rejectedInputs":len(entries),"offset":0,"returned":len(entries),"entries":entries})


def _page(args):
    offset, limit = args.get("offset", 0), args.get("limit", 50)
    if type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 100:
        raise BusinessQueryError("invalid_business_page")
    return offset, limit


def _source_date_context(rule, as_of):
    """Keep an aware business instant distinct from date-only source validity.

    A source function without date bounds has no source date gate to satisfy.
    With source date bounds, converting an instant needs an explicit source
    clock mapping that this version does not support. Never guess that mapping
    by truncating the timestamp or using the host clock/timezone.
    """
    if as_of is None or isinstance(as_of, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of):
        return as_of, None
    try:
        _semantics._instant(as_of)
    except _semantics.BusinessError:
        return None, "explicit_aware_time_required"
    validity = rule.get("validity", {})
    if not isinstance(validity, dict) or validity.get("from") is not None or validity.get("to") is not None:
        return None, "source_date_validity_clock_mapping_unsupported"
    return None, None


def _supplied_comparison(reader, projection, args, evidence):
    """Compare bounded supplied observations without evaluating source rules."""
    cases = args.get("cases")
    # This guards even malformed/unused fields, before any input-derived hash
    # or partial result. Denied payloads are rejected as a whole request.
    _guard.ensure_public_safe(cases)
    if type(cases) is not list:
        raise BusinessQueryError("comparison_cases_array_required")
    objective = args.get("objective")
    if objective not in ("maximize_value", "minimize_value"):
        raise BusinessQueryError("comparison_objective_invalid")
    selected = len(cases)
    result = {"comparisonMode": "supplied_values", "authority": "caller_supplied_observations_not_source_computed",
        "scope": "original_selected_supplied_values_only", "objective": objective,
        "selected": selected, "accepted": 0, "rejected": 0, "unknown": selected, "processed": 0,
        "entries": [], "minimum": [], "maximum": [], "best": [], "queryDigest": None,
        "sourceRuleEvaluated": False, "sourceEvaluation": None, "globalOptimum": "UNKNOWN",
        "businessPolicyComplete": False, "runtimeStatus": "NOT_OBSERVED", "eligibility": "UNKNOWN",
        "suppliedValueTruth": "NOT_VERIFIED", "policyApprovalDoesNotApproveSuppliedValues": True,
        "evidenceDetailsWithheld": not evidence}

    def blocked(reason):
        return {**result, "status": "BLOCKED", "reason": reason,
            "unprocessedFrontier": {"inputIndex": 0, "jsonPointer": "/cases/0", "count": selected}}

    if not 1 <= selected <= 100:
        return blocked("supplied_case_count_budget")
    try:
        encoded = _semantics.canonical(cases)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return blocked("supplied_cases_not_canonical_json")
    if len(encoded) > 65536:
        return blocked("supplied_case_byte_budget")

    pins = {key: reader.metadata[key] for key in PINS}
    policy_digest = _semantics.digest(projection)
    result.update(sourceAndBusinessPins=pins, policyProjectionDigest=policy_digest,
        queryDigest=_semantics.digest({"comparisonMode": "supplied_values", "objective": objective,
            "cases": cases, "pins": pins, "policyProjectionDigest": policy_digest,
            "policyView": args.get("policy_view", "verified_implemented"),
            "evidenceDetailsWithheld": not evidence}))

    def valid_id(value):
        return type(value) is str and 1 <= len(value) <= 128 and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value)

    counts = {}
    for item in cases:
        if type(item) is dict and valid_id(item.get("id")):
            counts[item["id"]] = counts.get(item["id"], 0) + 1
    numeric = []
    for index, item in enumerate(cases):
        entry = {"inputIndex": index, "jsonPointer": "/cases/" + str(index),
                 "inputDigest": _semantics.digest(item), "status": "rejected"}
        result["entries"].append(entry)
        if type(item) is not dict:
            entry["reason"] = "case_object_required"
            continue
        identity = item.get("id")
        if valid_id(identity):
            entry["id"] = identity
        if not valid_id(identity):
            entry["reason"] = "case_id_invalid"
            continue
        if counts[identity] != 1:
            entry["reason"] = "duplicate_case_id"
            continue
        if set(item) - {"id", "value"}:
            entry["reason"] = "unknown_case_fields"
            continue
        if "value" not in item or item["value"] is None:
            entry.update(status="unknown", reason="supplied_value_unavailable")
            continue
        value = item["value"]
        typed = {"type": "integer", "value": value} if type(value) is int else value
        if type(typed) is not dict or typed.get("type") not in ("integer", "decimal", "quantity", "money"):
            entry.update(status="unknown", reason="supplied_numeric_type_unsupported")
            continue
        try:
            typed = _semantics._typed_value(typed)
        except (ValueError, KeyError, TypeError):
            entry["reason"] = "supplied_numeric_value_invalid"
            continue
        family = (("quantity", typed["unit"]) if typed["type"] == "quantity" else
                  ("money", typed["currency"], typed.get("unit")) if typed["type"] == "money" else ("scalar",))
        entry.update(status="accepted", value=copy.deepcopy(value))
        numeric.append((index, Decimal(typed["value"]), family))
    if len({family for _, _, family in numeric}) > 1:
        for index, _, _ in numeric:
            result["entries"][index].update(status="unknown", reason="incomparable_supplied_dimensions")
        numeric = []
    if numeric:
        least, greatest = min(value for _, value, _ in numeric), max(value for _, value, _ in numeric)
        def references(value):
            return [{"inputIndex": index, "id": result["entries"][index]["id"]}
                    for index, number, _ in numeric if number == value]
        result.update(minimum=references(least), maximum=references(greatest),
            best=references(greatest if objective == "maximize_value" else least))
    for status in ("accepted", "rejected", "unknown"):
        result[status] = sum(entry["status"] == status for entry in result["entries"])
    result.update(processed=selected, status="COMPLETE" if result["accepted"] == selected else "PARTIAL",
                  unprocessedFrontier=None)
    return result


def _evaluation(reader, workspace, source_sid, name, args, evidence):
    record = reader.get_record(args["rule_id"])
    if not record or record.get("kind") != "business_policy":
        entries = [entry for entry in reader.metadata.get("currentReviewDiagnostics", {}).get("entries", [])
                   if entry["attemptedRecordId"] == args["rule_id"]] if not record else []
        codes = sorted({code for entry in entries for code in entry["diagnosticCodes"]})
        ambiguous = len(entries) > 1
        result = {"ruleId": args["rule_id"], "status": "business_review_rejected" if entries else "business_policy_unavailable",
            "businessValidity": "UNKNOWN", "businessPolicyComplete": False, "sourceEvaluation": None,
            "compositionEvaluated": False, "runtimeStatus": "NOT_OBSERVED", "executionAuthorization": "NOT_PROVIDED",
            "businessDecision": {"status": "UNKNOWN", "reason": "ambiguous_rejected_review_identity" if ambiguous else
                "review_contract_rejected" if entries else "business_policy_not_in_pinned_snapshot",
                "diagnosticCodes": codes, "value": None, "finiteBest": None, "selectedMemberPolicyIds": None,
                "rejectionReasons": sorted({entry["rejectionReason"] for entry in entries}),
                "activeMemberPolicyIds": None, "conflictProven": False},
            "rejectedInputCount": len(entries), "inputIndices": [entry["inputIndex"] for entry in entries]}
        if evidence: result["rejectionEvidence"] = [{"inputIndex": entry["inputIndex"], "sourceAnchors": copy.deepcopy(entry["sourceAnchors"])} for entry in entries]
        return result
    base = {"ruleId": record["id"], "policy": project_record(record, evidence=evidence),
            "businessApproval": record["businessApproval"], "businessValidity": "UNKNOWN",
            "businessPolicyComplete": False, "executionAuthorization": "NOT_PROVIDED",
            "runtimeStatus": "NOT_OBSERVED", "sourceEvaluation": None}
    if record.get("support") in ("conflicted", "revoked") or record.get("businessApproval") in ("rejected", "revoked"):
        return {**base, "status": "conflicted_or_revoked"}
    if args.get("policy_view") == "approved_business" and record.get("businessApproval") != "approved":
        return {**base, "status": "business_approval_required"}
    if name == "compare_policy_cases":
        mode = args.get("comparison_mode", "source_contexts")
        if mode not in ("source_contexts", "supplied_values"):
            raise BusinessQueryError("comparison_mode_invalid")
        if mode == "supplied_values":
            comparison = _supplied_comparison(reader, base["policy"], args, evidence)
            return {**base, "status": "supplied_values_compared" if comparison["status"] != "BLOCKED" else "supplied_comparison_blocked",
                "suppliedComparison": comparison, "scope": "selected_supplied_values_only",
                "sourceRuleEvaluated": False, "globalOptimum": "UNKNOWN", "compositionEvaluated": False}
    optional = (_semantics._declared(record,"inputs","formula_mapping") or _semantics._declared(record,"priority","policy_composition"))
    if optional:
        snapshot=_source.read_policy_records(str(workspace),snapshot_id=source_sid,max_rules=10000)
        def evaluate_source(rule_id,context,as_of):
            matches = [rule for rule in snapshot["rules"] if rule.get("id") == rule_id]
            if len(matches) != 1:
                return {"status":"UNKNOWN", "reason":"unique_source_rule_unavailable", "value":None}
            source_as_of, blocked = _source_date_context(matches[0], as_of)
            if blocked:
                return {"status":"UNKNOWN", "reason":blocked, "value":None}
            return _policy.explain_policy_result(snapshot,rule_id=rule_id,context=context,policy_view="verified_implemented",
                catalog_snapshot_id=snapshot["catalogSnapshotId"],policy_snapshot_id=snapshot["policySnapshotId"],ruleset_digest=snapshot["rulesetDigest"],
                config_profile=args.get("config_profile","source-default"),as_of=source_as_of)
        decision=_semantics.optional_decision(record,get_record=reader.get_record,source_reader=reader.source_reader,
            source_pins={k:reader.metadata[k]for k in _semantics.PIN_KEYS},context=args.get("context"),cases=args.get("cases")if name=="compare_policy_cases"else None,
            objective=args.get("objective","maximize_value"),as_of=args.get("as_of"),evaluate_source=evaluate_source,approved_only=args.get("policy_view")=="approved_business")
        return {**base,"status":"explicit_contract_evaluated"if decision.get("status")in("evaluated","finite_set_evaluated")else"business_contract_unknown",
                "businessDecision":decision,"scope":"explicit_reviewed_contract_and_supplied_contexts_only","globalOptimum":"UNKNOWN","compositionEvaluated":bool(_semantics._declared(record,"priority","policy_composition"))}
    anchors = record.get("facets", {}).get("formula", {}).get("sourceAnchors", [])
    candidates = set()
    for anchor in anchors:
        if anchor.get("inlinePointer") != "/program":
            continue
        _semantics.validate_anchor(anchor, reader.source_reader, source_pins={k:reader.metadata[k] for k in _semantics.PIN_KEYS})
        row = reader.source_reader.get_record(anchor["recordId"])
        if row and row.get("kind") == "policy_rule":
            candidates.add(row["id"])
    if len(candidates) != 1:
        return {**base, "status": "unsupported", "reason": "unique_executable_source_rule_unavailable"}
    snapshot = _source.read_policy_records(str(workspace), snapshot_id=source_sid, max_rules=10000)
    common = {"rule_id": next(iter(candidates)), "policy_view": "verified_implemented",
              "catalog_snapshot_id": snapshot["catalogSnapshotId"], "policy_snapshot_id": snapshot["policySnapshotId"],
              "ruleset_digest": snapshot["rulesetDigest"]}
    for key in ("config_profile", "as_of"):
        if key in args: common[key] = args[key]
    if name == "explain_policy_result":
        raw = _policy.explain_policy_result(snapshot, context=args["context"], **common)
    else:
        raw = _policy.compare_policy_cases(snapshot, cases=args["cases"], objective=args["objective"], **common)
    # Return only evaluator outputs, never its evidence paths, source prose or IR.
    selected = ("status", "value", "missingInputs", "ruleId", "scope", "optimality", "maximum", "minimum", "best",
                "objective", "cases", "catalogSnapshotId", "policySnapshotId", "rulesetDigest", "configProfile", "asOf")
    value = _pick(raw, selected)
    # The evaluator's finite-function optimum is not a business-domain optimum.
    value["authority"] = "implemented-source-function"
    value["businessPolicyApproved"] = False
    missing = [key for key, facet in record.get("facets", {}).items() if facet.get("status") == "UNKNOWN"]
    return {**base, "status": "source_evaluated_business_partial", "missingBusinessFacets": missing,
            "sourceEvaluation": value, "scope": "one_source_function_only",
            "globalOptimum": "UNKNOWN", "compositionEvaluated": False}


def dispatch(workspace, snapshot_id, name, args):
    if args.get("module") is not None or args.get("ruleset_authority") is not None:
        raise BusinessQueryError("business_selector_unsupported")
    access = _acl.authorize(workspace, "read_policy", snapshot_id)
    try:
        evidence_access = _acl.authorize(workspace, "read_evidence", snapshot_id)
    except _acl.AccessDenied:
        evidence_access = None
    evidence = evidence_access is not None
    if name == "ontology_pipeline_status":
        raw = _store.status(workspace, snapshot_id)
        result = _metadata(raw)
        result["lastRecordedUnpublishedBuild"] = (_store.unpublished_build_status(workspace, raw["sourceSnapshotId"])
            if evidence else {"schemaVersion": 1, "state": "WITHHELD"})
    else:
        bid, digest = args.get("business_snapshot_id"), args.get("business_digest")
        if not isinstance(bid, str) or not re.fullmatch(r"bs-[a-f0-9]{32}", bid) or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise BusinessQueryError("pin_business_snapshot_and_digest")
        offset, limit = _page(args)
        with _store.open_reader(workspace, snapshot_id, bid, digest) as reader:
            result = _metadata(reader.metadata)
            if name in ("ontology_pipeline_search", "query_policy_rules"):
                kind = "business_policy" if name == "query_policy_rules" else args.get("kind")
                if kind is not None and kind not in KINDS:
                    raise BusinessQueryError("business_kind_required")
                ids = [args["rule_id"]] if args.get("rule_id") else args.get("record_ids")
                page = reader.query(kind=kind, term=args.get("term", ""), domain=args.get("domain"), record_ids=ids, offset=offset, limit=limit)
                result.update(_pick(page, ("total", "offset", "returned", "truncated", "nextOffset", "queryDigest")))
                result["records"] = [project_record(r, evidence=evidence) for r in page["records"]]
            elif name == "ontology_pipeline_coverage":
                processing=args.get("coverage_view")=="processing"
                page = reader.processing(offset=offset,limit=limit)if processing else reader.coverage(offset=offset, limit=limit)
                result.update(_pick(page, ("total", "offset", "returned", "truncated", "nextOffset", "queryDigest")))
                result["summary"] = copy.deepcopy(page["summary"])if processing else _coverage(page["summary"])
                result["entries"] = [_coverage_entry(r) for r in page["entries"]]
                diagnostic = reader.metadata.get("currentReviewDiagnostics")
                if diagnostic is not None:
                    entries = diagnostic["entries"][offset:offset+limit]
                    result["currentReviewDiagnostics"] = {"selectedInputs":diagnostic["selectedInputs"],
                        "outcomeCounts":copy.deepcopy(diagnostic["outcomeCounts"]),
                        "rejectedInputs":len(diagnostic["entries"]),"offset":offset,"returned":len(entries),
                        "entries":[{**_pick(entry,("inputIndex","status","attemptedRecordId","diagnosticCodes","rejectionReason")),
                                    **({"sourceAnchors":copy.deepcopy(entry["sourceAnchors"])} if evidence else {})} for entry in entries]}
            elif name in ("list_domain_policies", "ontology_pipeline_modules"):
                # Business namespaces/domains are explicit concepts, not modules.
                if name == "ontology_pipeline_modules":
                    raise BusinessQueryError("business_view_has_domains_not_modules")
                domains = {}
                for r in reader.iter_records(kind="business_policy", domain=args.get("domain")):
                    item = domains.setdefault(r["domain"], {"domain":r["domain"], "policyCount":0, "approvedCount":0, "businessPolicyComplete":False})
                    item["policyCount"] += 1
                    item["approvedCount"] += r.get("businessApproval") == "approved"
                rows = [domains[k] for k in sorted(domains)]
                next_offset = offset+limit if offset+limit < len(rows) else None
                result.update(domains=rows[offset:offset+limit], total=len(rows), offset=offset, returned=len(rows[offset:offset+limit]),
                              nextOffset=next_offset, truncated=next_offset is not None,
                              queryDigest=_semantics.digest([reader._pins(), "domains", args.get("domain")]))
            elif name in ("explain_policy_result", "compare_policy_cases"):
                result.update(_evaluation(reader, workspace, snapshot_id, name, args, evidence))
            else:
                raise BusinessQueryError("unsupported_business_tool")
    if _acl.authorize(workspace, "read_policy", snapshot_id) != access:
        raise BusinessQueryError("business_authorization_changed")
    if evidence and _acl.authorize(workspace, "read_evidence", snapshot_id) != evidence_access:
        raise BusinessQueryError("business_authorization_changed")
    result["evidenceDetailsWithheld"] = not evidence
    result["knowledgeView"] = "business"
    return _safe(result)
