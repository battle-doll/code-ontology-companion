"""Bounded, source-free business knowledge contracts. No inferred business approval.

Dependencies are supplied by the verified bundled loader. A source anchor proves
an ontology observation, not the truth of an operator's business interpretation.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation, localcontext

VERSION = "business-semantics-v1"
MAX_RECORDS = 10000
MAX_BYTES = 32 * 1024 * 1024
PIN_KEYS = ("sourceSnapshotId", "sourceManifestSha256", "sourceFingerprint", "analysisSpecId")
KINDS = frozenset(("business_object_type", "business_property", "business_relation", "business_policy", "business_transition", "business_claim", "business_conflict"))
POLICY_FACETS = ("subject_scope", "eligibility", "exclusions", "inputs", "formula", "constants", "units", "rounding_stage", "outcome", "priority", "exclusivity", "stackability", "caps_floors", "effective_interval", "clock_timezone", "conflicts", "missing_context")
FACETS = {
    "business_policy": POLICY_FACETS,
    "business_object_type": ("identity", "properties", "state"),
    "business_property": ("scalar_type", "quantity_kind", "unit", "currency", "time_basis", "nullable"),
    "business_relation": ("direction", "role", "cardinality", "equivalence"),
    "business_transition": ("subject_type", "from_state", "trigger", "guard", "effect", "to_state", "ordering", "exceptional_outcome"),
    "business_claim": ("meaning",), "business_conflict": ("conflict",),
}
HASH = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_.:/#@+ -]{1,256}\Z")
CONTRACT_TAGS = frozenset(("property_type", "formula_mapping", "policy_composition", "finite_contexts", "clock_basis"))
ROUNDINGS = frozenset(("ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_HALF_DOWN", "ROUND_UP", "ROUND_DOWN", "ROUND_CEILING", "ROUND_FLOOR", "ROUND_05UP"))
_CONTEXT_VALUE_ERROR_CODES = frozenset(("object_shape_invalid", "semantic_value_grammar_invalid",
    "semantic_scalar_invalid", "semantic_unit_invalid", "decimal_contract_invalid",
    "decimal_value_contract_mismatch", "property_value_type_or_dimension_mismatch",
    "property_value_unit_currency_mismatch", "property_precision_scale_mismatch", "exact_integer_dimension_required"))
_guard = None


class BusinessError(ValueError):
    """Codes only: never echo supplied paths, secrets or review content."""
    def __init__(self, code="business_contract_invalid"):
        self.code = code if re.fullmatch(r"[a-z_]{1,100}", code) else "business_contract_invalid"
        super().__init__(self.code)


def configure(*, privacy_guard):
    global _guard
    if not callable(getattr(privacy_guard, "ensure_public_safe", None)):
        raise BusinessError("privacy_dependency_required")
    _guard = privacy_guard


def _safe(value):
    if _guard is None:
        raise BusinessError("dependencies_not_configured")
    _guard.ensure_public_safe(value)


def _bounded_canonical(value, *, max_depth):
    budget = [0]
    def check(node, depth=0):
        budget[0] += 1
        if budget[0] > 2000000 or depth > max_depth:
            raise BusinessError("json_budget_exceeded")
        if node is None or type(node) in (bool, int):
            return
        if type(node) is float and math.isfinite(node):
            return
        if type(node) is str and len(node) <= 131072:
            return
        if type(node) is list:
            for child in node: check(child, depth+1)
            return
        if type(node) is dict and all(type(k) is str and len(k) <= 512 for k in node):
            for child in node.values(): check(child, depth+1)
            return
        raise BusinessError("json_type_invalid")
    check(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, OverflowError):
        raise BusinessError("json_encoding_invalid") from None
    if len(raw) > MAX_BYTES:
        raise BusinessError("json_budget_exceeded")
    return raw


def canonical(value):
    return _bounded_canonical(value, max_depth=32)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _source_digest(value):
    """Hash source structures without admitting them as inline business values.

    IR nesting and JSON container nesting are different measures. Source
    anchors retain only this digest; business values and wire limits stay
    unchanged. This separate finite ceiling still rejects oversized sources.
    """
    return hashlib.sha256(_bounded_canonical(value, max_depth=128)).hexdigest()


def loads(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result: raise BusinessError("duplicate_json_key")
            result[key] = value
        return result
    def constant(_): raise BusinessError("nonfinite_number")
    if not isinstance(raw, (str, bytes)) or len(raw) > MAX_BYTES:
        raise BusinessError("json_budget_exceeded")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, BusinessError): raise
        raise BusinessError("json_invalid") from None


def _keys(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise BusinessError("object_shape_invalid")


def _text(value, maximum=256):
    if type(value) is not str or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        raise BusinessError("text_invalid")
    return value


def _pins(pins):
    _keys(pins, PIN_KEYS)
    for key in PIN_KEYS: _text(pins[key])
    if not HASH.fullmatch(pins["sourceManifestSha256"]): raise BusinessError("source_pin_invalid")
    return pins


def concept_id(namespace, domain, kind, concept_key):
    for value in (namespace, domain, concept_key): _text(value)
    if type(kind) is not str or kind not in KINDS: raise BusinessError("kind_invalid")
    return "business:" + digest([namespace, domain, kind, concept_key])


def _pointer(value, pointer):
    if type(pointer) is not str or len(pointer) > 2048 or (pointer and not pointer.startswith("/")):
        raise BusinessError("inline_pointer_invalid")
    if not pointer: return value
    for part in pointer[1:].split("/"):
        if re.search(r"~(?![01])", part): raise BusinessError("inline_pointer_invalid")
        token = part.replace("~1", "/").replace("~0", "~")
        if type(value) is dict and token in value:
            value = value[token]
        elif type(value) is list and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(value):
            value = value[int(token)]
        else: raise BusinessError("inline_pointer_missing")
    return value


def _location(record):
    path, sha = record.get("path", record.get("relativePath")), record.get("sourceDigest")
    if type(path) is not str or not path or "\\" in path or path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")) or ":" in path:
        raise BusinessError("source_location_invalid")
    if type(sha) is not str or not HASH.fullmatch(sha): raise BusinessError("source_hash_invalid")
    span = record.get("sourceRange", record.get("span"))
    if span is None and "lineStart" in record:
        span = {"lineStart": record["lineStart"], "lineEnd": record.get("lineEnd")}
    if type(span) is not dict or not span: raise BusinessError("source_span_missing")
    if set(span) == {"charStart", "charEnd", "byteStart", "byteEnd"}:
        # Both coordinate systems are source-produced evidence. Validate them
        # independently and preserve all four original values without guessing
        # conversions or falling back to a different location field.
        for prefix in ("char", "byte"):
            a,b=span[prefix+"Start"],span[prefix+"End"]
            if type(a) is not int or type(b) is not int or a<0 or b<a:
                raise BusinessError("source_span_invalid")
        return path,sha,copy.deepcopy(span)
    if set(span) == {"charStart", "charEnd"}: minimum = 0; a,b = span["charStart"],span["charEnd"]
    elif set(span) == {"lineStart", "lineEnd"}: minimum = 1; a,b = span["lineStart"],span["lineEnd"]
    else: raise BusinessError("source_span_invalid")
    if type(a) is not int or type(b) is not int or a < minimum or b < a:
        raise BusinessError("source_span_invalid")
    return path, sha, copy.deepcopy(span)


def _closure(record):
    return _source_digest({"recordDigest": _source_digest(record), "dependencyClosure": record.get("dependencyClosure"),
                   "sourceEvidence": record.get("sourceEvidence", []), "sourceAssertionIds": record.get("sourceAssertionIds", [])})


def make_anchor(record, *, source_pins, inline_pointer=""):
    _pins(source_pins)
    _text(record.get("id"))
    path, sha, span = _location(record)
    target = _pointer(record, inline_pointer)
    return {**source_pins, "recordId": record["id"], "recordDigest": _source_digest(record),
            "inlinePointer": inline_pointer, "targetDigest": _source_digest(target), "path": path,
            "sourceSha256": sha, "sourceRangeOrSpan": span, "dependencyClosureDigest": _closure(record)}


def validate_anchor(anchor, reader, *, source_pins):
    _keys(anchor, (*PIN_KEYS, "recordId", "recordDigest", "inlinePointer", "targetDigest", "path", "sourceSha256", "sourceRangeOrSpan", "dependencyClosureDigest"))
    if canonical({k: anchor[k] for k in PIN_KEYS}) != canonical(_pins(source_pins)):
        raise BusinessError("source_pin_mismatch")
    record = reader.get_record(_text(anchor["recordId"]))
    if not record: raise BusinessError("source_record_missing")
    expected = make_anchor(record, source_pins=source_pins, inline_pointer=anchor["inlinePointer"])
    if canonical(expected) != canonical(anchor): raise BusinessError("source_anchor_mismatch")
    return copy.deepcopy(_pointer(record, anchor["inlinePointer"]))


def _supported(record):
    if type(record) is not dict or type(record.get("dependencyClosure", {})) is not dict: return False
    if record.get("structuralOnly") or record.get("dependencyClosure", {}).get("status") in ("invalidated", "pending_snapshot_finalization"):
        return False
    if record.get("kind") == "policy_rule": return record.get("status") == "extraction_verified" and type(record.get("program")) is dict
    if record.get("kind") == "semantic_fragment": return record.get("representationStatus") in ("represented",) and not record.get("unsupportedReasons")
    return record.get("kind") == "symbol" and record.get("resolution") in ("lexical_declaration", "declared", "exact")


def _unknown(reason="business_meaning_not_reviewed"):
    return {"status": "UNKNOWN", "reason": reason}


def seal_record(record):
    value = {k: copy.deepcopy(v) for k,v in record.items() if k != "contentDigest"}
    value["contentDigest"] = digest(value)
    return value


def _base(namespace, domain, kind, key, name, anchors):
    return {"id": concept_id(namespace, domain, kind, key), "kind": kind, "name": name,
            "namespace": namespace, "domain": domain, "conceptKey": key, "support": "candidate",
            "businessApproval": "unreviewed", "sourceAnchors": anchors,
            "facets": {f: _unknown() for f in FACETS[kind]},
            "runtimeStatus": "NOT_OBSERVED", "executionAuthorization": "NOT_PROVIDED",
            "limitations": ["business_interpretation_not_source_proof", "global_completeness_unknown"]}


def _coverage(selected, accepted, entries, *, scope, omitted=0):
    return {"state": "PARTIAL", "scope": scope, "denominator": selected, "numerator": accepted,
            "rejected": sum(e.get("status") in ("rejected","unsupported") for e in entries), "conflicted": sum(e.get("status")=="conflicted" for e in entries), "omitted": omitted, "unknownDenominator": selected == "UNKNOWN",
            "globalCompleteness": "UNKNOWN", "semanticCompleteness": "PARTIAL",
            "numeratorMeaning": "validated_records_not_business_completeness",
            "entries": entries, "limitations": ["selected_inputs_are_not_all_business_rules", "approval_is_not_execution_authorization"]}


def processing_reconciliation(selected, records, entries, *, scope_id):
    """Disjoint original-input classes; historical lifecycle events stay separate."""
    states={r["inputIndex"]:"accepted" for r in records if type(r.get("inputIndex")) is int}
    order={"accepted":0,"conflicted":1,"unsupported":2,"rejected":3,"omitted":4,"duplicate":5}
    lifecycle={"revoked":0,"invalidated":0}; conflicts=[]
    for entry in entries:
        state=entry.get("status"); index=entry.get("inputIndex")
        if state in lifecycle:lifecycle[state]+=1;continue
        if type(index) is not int or not 0<=index<selected:continue
        if entry.get("reason")=="duplicate_concept_identity":state="duplicate"
        if state not in order:continue
        if order[state]>=order.get(states.get(index),-1):states[index]=state
    counts={state:sum(value==state for value in states.values())for state in order}
    missing=selected-len(states)
    return {"scopeId":scope_id,"selectedInputs":selected,"accountedInputs":len(states),"missingInputs":missing,
            "outcomeCounts":counts,"lifecycleCounts":lifecycle,"reconciled":missing==0,"wholeBusinessCompleteness":"UNKNOWN",
            "identity":"processingScopeId plus original inputIndex; record IDs and lifecycle events remain separate"}


def _contract_token(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}",value):raise BusinessError("contract_token_invalid")
    return value


def _concept_reference(value):
    if type(value) is not str or not re.fullmatch(r"business:[0-9a-f]{64}",value):raise BusinessError("contract_concept_reference_invalid")


def _precision(value):
    if (type(value.get("precision")) is not int or not 1<=value["precision"]<=100 or type(value.get("scale")) is not int
            or not 0<=value["scale"]<=value["precision"]):raise BusinessError("decimal_contract_invalid")


def _property_precision(value):
    # Descriptive knowledge may be partial. Concrete value validation and
    # property_value still require their existing executable contracts.
    known = []
    for key, lower in (("precision", 1), ("scale", 0)):
        item = value[key]
        if type(item) is str and item == "UNKNOWN":
            continue
        if type(item) is not int or not lower <= item <= 100:
            raise BusinessError("decimal_contract_invalid")
        known.append(key)
    if len(known) == 2:
        _precision(value)
    elif len(known) == 1 and value["scalarType"] not in ("int", "decimal"):
        raise BusinessError("decimal_contract_invalid")


def _fixed_zone(zone):
    return type(zone) is str and (zone=="UTC" or re.fullmatch(r"[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00)",zone) is not None)


def _zone_label(value):
    if not _fixed_zone(value) and (type(value)is not str or not re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z_+-]+){1,3}",value)) and value!="UNKNOWN":raise BusinessError("timezone_label_invalid")


def _contract_value(value,depth):
    tag=value["type"]
    if tag=="property_type":
        _keys(value,("type","scalarType","precision","scale","quantityKind","unit","currency","rounding","clock","timezone","nullable"))
        if value["scalarType"] not in ("bool","int","decimal","string","UNKNOWN") or value["quantityKind"] not in ("scalar","quantity","money","time","UNKNOWN") or not(type(value["nullable"])is bool or type(value["nullable"])is str and value["nullable"]=="UNKNOWN"):raise BusinessError("property_contract_invalid")
        _property_precision(value)
        for key in ("unit","currency","rounding","clock","timezone"):_text(value[key],64)
        _contract_token(value["clock"]);_zone_label(value["timezone"])
        if value["rounding"] not in ROUNDINGS|{"UNKNOWN"}:raise BusinessError("property_rounding_invalid")
        if value["currency"]!="UNKNOWN" and not re.fullmatch(r"[A-Z]{3}",value["currency"]):raise BusinessError("property_currency_invalid")
        if value["unit"]!="UNKNOWN" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.%/-]{0,31}",value["unit"]):raise BusinessError("property_unit_invalid")
        if value["quantityKind"]=="money" and value["currency"]=="UNKNOWN" or value["quantityKind"]=="quantity" and value["unit"]=="UNKNOWN":raise BusinessError("property_dimension_required")
        if value["quantityKind"] not in ("money","UNKNOWN") and value["currency"]!="UNKNOWN" or value["quantityKind"] not in ("quantity","money","UNKNOWN") and value["unit"]!="UNKNOWN":raise BusinessError("property_dimension_conflict")
        if value["quantityKind"] in ("quantity","money") and value["scalarType"] not in ("int","decimal"):raise BusinessError("property_dimension_scalar_unsupported")
        if value["scalarType"]=="int" and value["scale"] not in ("UNKNOWN",0):raise BusinessError("integer_scale_unsupported")
    elif tag=="formula_mapping":
        _keys(value,("type","sourcePins","sourceRuleId","sourceRuleDigest","inputs","outputPropertyId","numericContextDigest"))
        _pins(value["sourcePins"])
        if type(value["sourceRuleId"])is not str or not _SOURCE_OUTCOME_ID.fullmatch(value["sourceRuleId"]):raise BusinessError("mapping_opaque_source_id_required")
        if any(type(value[key])is not str or not HASH.fullmatch(value[key])for key in ("sourceRuleDigest","numericContextDigest")):raise BusinessError("mapping_digest_invalid")
        _concept_reference(value["outputPropertyId"])
        if type(value["inputs"]) is not list or len(value["inputs"])>16:raise BusinessError("mapping_inputs_invalid")
        parameters=[];properties=[]
        for item in value["inputs"]:
            _keys(item,("parameter","propertyId"));_concept_reference(item["propertyId"])
            if type(item["parameter"])is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}",item["parameter"]):raise BusinessError("mapping_parameter_invalid")
            parameters.append(item["parameter"]);properties.append(item["propertyId"])
        if len(set(parameters))!=len(parameters) or len(set(properties))!=len(properties):raise BusinessError("mapping_duplicate_input")
    elif tag=="policy_composition":
        _keys(value,("type","members","priorityOrder","exclusivity","onConflict"),("stacking",))
        if "stacking" not in value and value["exclusivity"] not in ("first_applicable","at_most_one"):raise BusinessError("object_shape_invalid")
        if type(value["members"]) is not list or not 1<=len(value["members"])<=16:raise BusinessError("composition_budget_invalid")
        identities=[];ranks=[]
        for item in value["members"]:
            _keys(item,("policyId","priority"));_concept_reference(item["policyId"])
            if type(item["priority"]) is not int or abs(item["priority"])>100000:raise BusinessError("composition_priority_invalid")
            identities.append(item["policyId"]);ranks.append(item["priority"])
        if len(set(identities))!=len(identities):raise BusinessError("composition_duplicate_policy")
        if value["priorityOrder"] not in ("higher_first","lower_first") or value["exclusivity"] not in ("first_applicable","at_most_one","all") or value.get("stacking","none") not in ("none","sum","min","max") or value["onConflict"]!="UNKNOWN":raise BusinessError("composition_mode_unsupported")
        if value["exclusivity"]!="all" and value.get("stacking","none")!="none":raise BusinessError("composition_mode_conflict")
    elif tag=="clock_basis":
        _keys(value,("type","clock","timezone"));_contract_token(value["clock"]);_zone_label(value["timezone"])
    elif tag=="finite_contexts":
        _keys(value,("type","scope","contexts"))
        if value["scope"]!="explicit_reviewed_supplied_set" or type(value["contexts"]) is not list or not 1<=len(value["contexts"])<=100:raise BusinessError("finite_context_budget_invalid")
        names=[];hashes=[]
        for item in value["contexts"]:
            _keys(item,("contextId","values","asOf","clock","timezone"));_contract_token(item["contextId"]);names.append(item["contextId"])
            if type(item["values"]) is not dict or len(item["values"])>16:raise BusinessError("finite_context_values_invalid")
            for prop,typed in item["values"].items():
                _concept_reference(prop);_typed_value(typed,depth=depth+1)
                if typed["type"] not in ("boolean","integer","decimal","quantity","money"):raise BusinessError("finite_context_scalar_required")
            if item["asOf"] is not None:_instant(item["asOf"])
            _contract_token(item["clock"]);_zone_label(item["timezone"]);hashes.append(digest([item["values"],item["asOf"],item["clock"],item["timezone"]]))
        if len(set(names))!=len(names) or len(set(hashes))!=len(hashes):raise BusinessError("finite_context_duplicate")
    else:raise BusinessError("semantic_value_tag_unsupported")
    return copy.deepcopy(value)


def _instant(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})",value):raise BusinessError("explicit_aware_time_required")
    try:return datetime.datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:raise BusinessError("explicit_aware_time_required") from None


def _expected_canonical_contracts(record):
    """Server-derived unique completions; never rewrite a DECLARED input."""
    result=[]
    def visit(value,path):
        if type(value) is dict:
            if value.get("type")=="policy_composition" and "stacking" not in value:
                # Typed validation must establish every other field first.
                _typed_value(value)
                if len(result)>=16:raise BusinessError("canonical_contract_budget")
                result.append({"path":path+"/stacking","value":"none","basis":"CONSTRAINT_ENTAILED",
                    "rule":"non_all_stacking_constraint_v1","premisePath":path+"/exclusivity",
                    "premiseValue":value["exclusivity"]})
            for key in sorted(value):visit(value[key],path+"/"+key.replace("~","~0").replace("/","~1"))
        elif type(value) is list:
            for index,child in enumerate(value):visit(child,path+"/"+str(index))
    visit(record.get("facets",{}),"/facets")
    return result


def _validate_canonical_contracts(record):
    expected=_expected_canonical_contracts(record)
    if expected:
        if "canonicalContracts" not in record or canonical(record["canonicalContracts"])!=canonical(expected):
            raise BusinessError("canonical_contract_metadata_mismatch")
    elif "canonicalContracts" in record:raise BusinessError("canonical_contract_metadata_mismatch")
    return expected


def _composition_contract(record):
    raw=_declared(record,"priority","policy_composition")
    if raw is None:return None
    _typed_value(raw)
    _validate_canonical_contracts(record)
    value=copy.deepcopy(raw)
    if "stacking" not in value:value["stacking"]="none"
    return value


def validate_record_values(record):
    """Shared closed typed grammar for storage, querying and JSON/RDF export."""
    if type(record) is not dict or record.get("kind") not in KINDS or type(record.get("facets")) is not dict:raise BusinessError("business_record_values_invalid")
    for name,facet in record["facets"].items():
        if name not in FACETS[record["kind"]] or type(facet) is not dict:raise BusinessError("business_record_facet_invalid")
        if facet.get("status") in ("DECLARED","SOURCE_SUPPORTED"):_typed_value(facet.get("value"),allow_reference=facet["status"]=="SOURCE_SUPPORTED")
    _validate_canonical_contracts(record)
    return record


def candidate_record(source, *, source_pins):
    """One bounded candidate. The store owns inventory and duplicate accounting."""
    rid = _text(source.get("id") if type(source) is dict else None)
    anchor = make_anchor(source, source_pins=source_pins)
    kind = "business_policy" if source.get("kind") == "policy_rule" else "business_object_type" if source.get("kind") == "symbol" and source.get("type") in ("Class", "Interface", "Record", "Enum", "Struct") else "business_property" if source.get("kind") == "symbol" and source.get("type") in ("Field", "Property") else "business_claim"
    record = _base("source", "unclassified", kind, "source:" + rid, _text(source.get("name", "Source candidate")), [anchor])
    if not _supported(source): record["limitations"].append("source_semantics_not_supported")
    record.update(sourceKind=source.get("kind", "unknown"), sourceRecordId=rid)
    if kind == "business_policy" and _supported(source):
        for facet, pointer in (("formula", "/program"), ("inputs", "/parameters"), ("outcome", "/returnType")):
            a = make_anchor(source, source_pins=source_pins, inline_pointer=pointer)
            record["facets"][facet] = {"status": "SOURCE_SUPPORTED", "value": _project_source(source, pointer), "sourceAnchors": [a]}
        record["ruleId"] = rid
    record = seal_record(record)
    _safe(record)
    return record


_SOURCE_OUTCOME_ID = re.compile(r"(?:(?:p|semantic|semantic:policy-declaration|semantic-documentation):[0-9a-f]{64}|(?:policy|assertion:policy):[0-9a-f]{32})\Z")
SOURCE_KINDS = frozenset(("symbol","assertion","framework","semantic_fragment","policy_rule"))


def outcome_source_fields(record_id, kind):
    """Only opaque source identities and closed kinds cross outcome metadata."""
    return {"sourceRecordId":record_id if type(record_id) is str and _SOURCE_OUTCOME_ID.fullmatch(record_id) else None,
            "sourceKind":kind if type(kind) is str and kind in SOURCE_KINDS else "UNKNOWN"}


def iter_candidate_events(reader, *, source_pins):
    """Visit the complete selected inventory; emit a result for every input.

    This generator never collects the inventory or truncates it. A fatal reader,
    privacy or cancellation failure aborts publication; its denominator remains
    the selected snapshot inventory in the store's bounded attempt receipt.
    """
    _pins(source_pins)
    for index, source in enumerate(reader.iter_records()):
        try:
            yield index, candidate_record(source, source_pins=source_pins), None
        except BusinessError as exc:
            rid=source.get("id") if type(source) is dict else None
            kind=source.get("kind") if type(source) is dict else None
            entry={"inputIndex":index,**outcome_source_fields(rid,kind),"status":"unsupported","reason":exc.code}
            _safe(entry)
            yield index,None,entry


def build_candidates(reader, *, source_pins, max_records=MAX_RECORDS):
    _pins(source_pins)
    if type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS: raise BusinessError("candidate_budget_invalid")
    expected = reader.metadata.get("recordCount")
    if type(expected) is not int or expected < 0: expected = "UNKNOWN"
    records, entries, seen, count = [], [], set(), 0
    for source in reader.iter_records():
        count += 1
        if count > max_records:
            break
        rid = source.get("id") if type(source) is dict else None
        try:
            _text(rid)
            if rid in seen: raise BusinessError("duplicate_source_identity")
            seen.add(rid)
            anchor = make_anchor(source, source_pins=source_pins)
            kind = "business_policy" if source.get("kind") == "policy_rule" else "business_object_type" if source.get("kind") == "symbol" and source.get("type") in ("Class", "Interface", "Record", "Enum", "Struct") else "business_property" if source.get("kind") == "symbol" and source.get("type") in ("Field", "Property") else "business_claim"
            record = _base("source", "unclassified", kind, "source:" + rid, _text(source.get("name", "Source candidate")), [anchor])
            if not _supported(source): record["limitations"].append("source_semantics_not_supported")
            record["sourceKind"] = source.get("kind", "unknown")
            record["sourceRecordId"] = rid
            if kind == "business_policy" and _supported(source):
                for facet, pointer in (("formula", "/program"), ("inputs", "/parameters"), ("outcome", "/returnType")):
                    a = make_anchor(source, source_pins=source_pins, inline_pointer=pointer)
                    record["facets"][facet] = {"status": "SOURCE_SUPPORTED", "value": _project_source(source, pointer), "sourceAnchors": [a]}
                record["ruleId"] = rid
            records.append(seal_record(record))
        except BusinessError as exc:
            entries.append({"inputIndex": count-1, "status": "unsupported", "reason": exc.code})
    capped = count > max_records
    processed = min(count, max_records)
    if expected != "UNKNOWN" and not capped and expected != count:
        entries.append({"status": "unknown", "reason": "source_inventory_count_mismatch"})
    denominator = expected if capped and expected != "UNKNOWN" else "UNKNOWN" if capped else max(expected, count) if expected != "UNKNOWN" else count
    omitted = max(0, denominator-processed) if type(denominator) is int else "UNKNOWN"
    if capped: entries.append({"status": "omitted", "reason": "candidate_record_budget", "count": omitted})
    result = {"records": records, "coverage": _coverage(denominator, len(records), entries, scope="selected_source_snapshot_records", omitted=omitted), "omissions": entries}
    import pipeline_policy
    read_policy = getattr(reader, "read_policy_records", None)
    policy_coverage = read_policy().get("coverage", {}) if callable(read_policy) else {}
    result["coverage"]["sourceDeclarationCoverage"] = pipeline_policy.declaration_coverage_summary(
        policy_coverage.get("sourceDeclarationCoverage"))
    _safe(result)
    return result


def _typed_value(value, *, allow_reference=False, depth=0):
    if depth > 4 or type(value) is not dict or type(value.get("type")) is not str:
        raise BusinessError("semantic_value_grammar_invalid")
    tag = value["type"]
    if tag in CONTRACT_TAGS:return _contract_value(value,depth)
    if tag in ("boolean", "integer", "decimal", "text", "enum"):
        _keys(value, ("type", "value"), ("precision","scale") if tag=="decimal" else ()); payload = value["value"]
        valid = (tag == "boolean" and type(payload) is bool or
                 tag == "integer" and type(payload) is int and abs(payload) <= 10**100 or
                 tag == "decimal" and type(payload) is str and len(payload) <= 128 and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", payload) or
                 tag == "text" and type(payload) is str and 1 <= len(payload) <= 256 and not any(c in payload for c in ("\n", "\r", "\x00")) or
                 tag == "enum" and type(payload) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", payload))
        if not valid: raise BusinessError("semantic_scalar_invalid")
        if "precision" in value or "scale" in value:
            _precision(value)
            digits=value["value"].lstrip("-").replace(".","");scale=len(value["value"].split(".",1)[1]) if "." in value["value"] else 0
            if len(digits.lstrip("0") or "0")>value["precision"] or scale!=value["scale"]:raise BusinessError("decimal_value_contract_mismatch")
    elif tag in ("quantity", "money"):
        key = "unit" if tag == "quantity" else "currency"
        _keys(value, ("type", "value", key), ("precision","scale","unit") if tag=="money" else ("precision","scale"))
        _typed_value({"type":"decimal", "value":value["value"],**{k:value[k]for k in ("precision","scale")if k in value}})
        if type(value[key]) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.%/-]{0,31}" if key=="unit" else r"[A-Z]{3}", value[key]): raise BusinessError("semantic_unit_invalid")
        if tag=="money" and "unit"in value and(type(value["unit"])is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.%/-]{0,31}",value["unit"])):raise BusinessError("semantic_unit_invalid")
    elif tag == "concept_reference":
        _keys(value, ("type", "conceptId"))
        if type(value["conceptId"]) is not str or not re.fullmatch(r"business:[0-9a-f]{64}", value["conceptId"]): raise BusinessError("semantic_concept_reference_invalid")
    elif tag == "sequence":
        _keys(value,("type","items"))
        if type(value["items"]) is not list or len(value["items"])>100: raise BusinessError("semantic_sequence_invalid")
        for item in value["items"]: _typed_value(item, allow_reference=allow_reference, depth=depth+1)
    elif tag == "time_interval":
        _keys(value,("type","start","end","timezone","clock","bounds"))
        for key in ("start","end","timezone","clock","bounds"):
            _text(value[key],128)
        if value["bounds"] not in ("closed", "open", "left_closed", "right_closed"): raise BusinessError("semantic_time_bounds_invalid")
        # Declared ISO strings retain their clock basis; no temporal solver implied.
        for key in ("start","end"):
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})",value[key]): raise BusinessError("semantic_time_invalid")
        try:
            if datetime.datetime.fromisoformat(value["start"].replace("Z","+00:00")) > datetime.datetime.fromisoformat(value["end"].replace("Z","+00:00")):
                raise BusinessError("semantic_time_order_invalid")
        except ValueError:
            raise BusinessError("semantic_time_invalid") from None
    elif tag == "ontology_reference" and allow_reference:
        _keys(value,("type","valueKind"))
        if value["valueKind"] not in ("program", "expression"): raise BusinessError("semantic_reference_invalid")
    elif tag == "scalar_type":
        _keys(value,("type","name"))
        if value["name"] not in ("bool","int","decimal","string","UNKNOWN"): raise BusinessError("semantic_scalar_type_invalid")
    elif tag == "parameters":
        _keys(value,("type","items"))
        if type(value["items"]) is not list or len(value["items"])>16: raise BusinessError("semantic_parameters_invalid")
        names=set()
        for item in value["items"]:
            _keys(item,("name","valueType"))
            if type(item["name"]) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}",item["name"]) or item["name"] in names or item["valueType"] not in ("bool","int","decimal"):
                raise BusinessError("semantic_parameter_invalid")
            names.add(item["name"])
    else: raise BusinessError("semantic_value_tag_unsupported")
    return copy.deepcopy(value)


def _project_source(record, pointer):
    target = _pointer(record, pointer)
    if record.get("kind") == "policy_rule" and pointer == "/program":
        result={"type":"ontology_reference","valueKind":"program"}
    elif record.get("kind") == "semantic_fragment" and pointer == "/expression" and type(target) is dict:
        result={"type":"ontology_reference","valueKind":"expression"}
    elif record.get("kind") == "policy_rule" and pointer == "/parameters":
        result={"type":"parameters","items":[{"name":p["name"],"valueType":p["type"]} for p in target]}
    elif record.get("kind") == "policy_rule" and pointer == "/returnType":
        result={"type":"scalar_type","name":target}
    else: raise BusinessError("source_value_projection_unsupported")
    return _typed_value(result,allow_reference=True)


def _facet(value, reader, pins, facet_name):
    _keys(value, ("status",), ("value", "reason", "sourceAnchors", "basis"))
    state = value["status"]
    if state not in ("UNKNOWN", "NOT_APPLICABLE", "SOURCE_SUPPORTED", "DECLARED"): raise BusinessError("facet_status_invalid")
    if state in ("UNKNOWN", "NOT_APPLICABLE"):
        _text(value.get("reason"), 2000)
        if "value" in value or "sourceAnchors" in value or "basis" in value: raise BusinessError("unknown_facet_has_value")
    else:
        if "value" not in value: raise BusinessError("facet_value_missing")
        _typed_value(value["value"], allow_reference=state == "SOURCE_SUPPORTED")
        if state == "DECLARED":
            _text(value.get("basis"), 2000)
            if "sourceAnchors" in value: raise BusinessError("declared_facet_evidence_ambiguous")
        else:
            anchors = value.get("sourceAnchors")
            if type(anchors) is not list or not 1 <= len(anchors) <= 32: raise BusinessError("facet_anchors_invalid")
            projections = []
            for anchor in anchors:
                validate_anchor(anchor, reader, source_pins=pins)
                row = reader.get_record(anchor["recordId"])
                if not _supported(row): raise BusinessError("source_semantics_not_supported")
                allowed={"formula":("/program","/expression"),"inputs":("/parameters",),"outcome":("/returnType",),
                         "scalar_type":("/returnType",),"eligibility":("/program",),"guard":("/program",)}
                if anchor["inlinePointer"] not in allowed.get(facet_name,()): raise BusinessError("source_facet_role_unsupported")
                if facet_name in ("eligibility","guard") and row.get("returnType")!="bool": raise BusinessError("source_condition_type_unsupported")
                projections.append(_project_source(row, anchor["inlinePointer"]))
            if not any(canonical(value["value"]) == canonical(x) for x in projections):
                raise BusinessError("facet_value_not_source_projection")
    return copy.deepcopy(value)


def concept_targets(record):
    targets = [record[k] for k in ("subject", "object") if k in record] + [a["target"] for a in record.get("aliases", [])]
    def visit(value):
        if type(value) is dict:
            if value.get("type") == "concept_reference": targets.append(value["conceptId"])
            if value.get("type")=="formula_mapping":targets.extend([value["outputPropertyId"],*[x["propertyId"]for x in value["inputs"]]])
            if value.get("type")=="policy_composition":targets.extend(x["policyId"]for x in value["members"])
            if value.get("type")=="finite_contexts":targets.extend(key for context in value["contexts"]for key in context["values"])
            for child in value.values(): visit(child)
        elif type(value) is list:
            for child in value: visit(child)
    visit(record.get("facets", {}))
    return targets


def _declared(record,facet,tag=None):
    value=record.get("facets",{}).get(facet,{})
    if value.get("status")!="DECLARED":return None
    result=value.get("value")
    if tag is not None and (type(result)is not dict or result.get("type")!=tag):return None
    return result


def _property(record):
    value=_declared(record,"scalar_type","property_type")
    if record.get("kind")!="business_property" or value is None:raise BusinessError("explicit_property_contract_required")
    return _typed_value(value)


def validate_contract_links(record,records,source_reader,pins,trail=()):
    """No lexical matching: exact scoped IDs, current pins and actual rule roles."""
    if record["id"] in trail or len(trail)>16:raise BusinessError("composition_cycle_or_depth")
    validate_record_values(record)
    for facet,value in record.get("facets",{}).items():
        typed=value.get("value",{});tag=typed.get("type") if type(typed)is dict else None
        roles={"property_type":("business_property","scalar_type"),"formula_mapping":("business_policy","inputs"),
               "policy_composition":("business_policy","priority"),"finite_contexts":("business_policy","missing_context"),"clock_basis":("business_policy","clock_timezone")}
        if tag in roles and (record["kind"],facet)!=roles[tag]:raise BusinessError("optional_contract_facet_role_invalid")
    if record["kind"]=="business_property" and _declared(record,"scalar_type","property_type"):
        prop=_property(record)
        for facet,key in (("quantity_kind","quantityKind"),("unit","unit"),("currency","currency"),("nullable","nullable")):
            other=record["facets"].get(facet,{})
            if other.get("status")in("DECLARED","SOURCE_SUPPORTED"):
                typed=other.get("value",{})
                if typed.get("type")not in("enum","text","boolean")or typed.get("value")!=prop[key]:raise BusinessError("property_existing_facet_conflict")
        other=record["facets"].get("time_basis",{})
        if other.get("status")in("DECLARED","SOURCE_SUPPORTED"):
            typed=other.get("value",{})
            if typed.get("type")!="time_interval"or any(typed.get(key)!=prop[key]for key in("clock","timezone")):raise BusinessError("property_existing_time_facet_conflict")
    mapping=_declared(record,"inputs","formula_mapping")
    if mapping and _declared(record,"priority","policy_composition"):raise BusinessError("multiple_computation_contracts")
    if mapping:
        if canonical(mapping["sourcePins"])!=canonical(pins):raise BusinessError("mapping_source_pins_mismatch")
        rule=source_reader.get_record(mapping["sourceRuleId"])
        if not _supported(rule) or rule.get("kind")!="policy_rule" or _source_digest(rule)!=mapping["sourceRuleDigest"] or _source_digest(rule.get("numericContext"))!=mapping["numericContextDigest"]:raise BusinessError("mapping_actual_source_rule_mismatch")
        for facet,pointer in (("formula","/program"),("outcome","/returnType")):
            source=record["facets"].get(facet,{})
            matches=[a for a in source.get("sourceAnchors",[])if a.get("recordId")==rule["id"]and a.get("inlinePointer")==pointer]
            if source.get("status")!="SOURCE_SUPPORTED" or len(matches)!=1:raise BusinessError("mapping_source_anchor_role_missing")
            validate_anchor(matches[0],source_reader,source_pins=pins)
            if canonical(source.get("value"))!=canonical(_project_source(rule,pointer)):raise BusinessError("mapping_source_value_role_mismatch")
        declared={item["parameter"]:item["propertyId"]for item in mapping["inputs"]}
        params=rule.get("parameters",[])
        if set(declared)!={item["name"]for item in params} or len(params)!=len(declared):raise BusinessError("mapping_parameters_incomplete")
        for parameter in params:
            prop=_property(records[declared[parameter["name"]]])
            if prop["scalarType"]!=parameter["type"]:raise BusinessError("mapping_property_source_type_mismatch")
        output=_property(records[mapping["outputPropertyId"]])
        if output["scalarType"]!=rule["returnType"]:raise BusinessError("mapping_output_source_type_mismatch")
        for prop in [_property(records[x["propertyId"]])for x in mapping["inputs"]]+[output]:
            if prop["scalarType"]=="decimal" and prop["rounding"]!="UNKNOWN" and prop["rounding"]!=rule.get("numericContext",{}).get("rounding"):raise BusinessError("mapping_rounding_mismatch")
            if prop["scalarType"]=="decimal" and prop["precision"]!="UNKNOWN" and prop["precision"]>rule.get("numericContext",{}).get("precision",0):raise BusinessError("mapping_precision_unsupported")
    composition=_composition_contract(record)
    if composition:
        for facet,key in (("exclusivity","exclusivity"),("stackability","stacking")):
            other=record["facets"].get(facet,{})
            if other.get("status")in("DECLARED","SOURCE_SUPPORTED"):
                typed=other.get("value",{})
                if typed.get("type")not in("enum","text")or typed.get("value")!=composition[key]:raise BusinessError("composition_existing_facet_conflict")
        for member in composition["members"]:
            target=records[member["policyId"]]
            if target.get("kind")!="business_policy" or not (_declared(target,"inputs","formula_mapping") or _declared(target,"priority","policy_composition")):raise BusinessError("composition_member_mapping_required")
            validate_contract_links(target,records,source_reader,pins,trail+(record["id"],))
    contexts=_declared(record,"missing_context","finite_contexts")
    if contexts and not (mapping or composition):raise BusinessError("finite_context_rule_mapping_required")
    if composition:_contract_selection(record,records)
    if contexts:
        _,_,properties=_contract_selection(record,records)
        for context in contexts["contexts"]:
            if set(context["values"])-properties:raise BusinessError("finite_context_unmapped_property")
            for identity,value in context["values"].items():property_value(_property(records[identity]),value)
    return True


def _contract_selection(record,records,seen=None,depth=0):
    seen=set()if seen is None else seen
    if record["id"]in seen or depth>16:raise BusinessError("composition_duplicate_cycle_or_depth")
    seen.add(record["id"]);identities=[record["id"]];source=[];properties=set()
    mapping=_declared(record,"inputs","formula_mapping")
    if mapping:source.append(mapping["sourceRuleId"]);properties.update(x["propertyId"]for x in mapping["inputs"])
    composition=_composition_contract(record)
    if composition:
        for member in composition["members"]:
            ids,rules,props=_contract_selection(records[member["policyId"]],records,seen,depth+1)
            identities.extend(ids);source.extend(rules);properties.update(props)
    return identities,source,properties


def temporal_decision(record,as_of,clock,timezone):
    period=record.get("facets",{}).get("effective_interval",{});basis=record.get("facets",{}).get("clock_timezone",{})
    if period.get("status")==basis.get("status")=="NOT_APPLICABLE":return {"status":"NOT_APPLICABLE","valid":True}
    interval=_declared(record,"effective_interval","time_interval");declared=_declared(record,"clock_timezone","clock_basis")
    if interval is None or declared is None:return {"status":"UNKNOWN","reason":"explicit_temporal_contract_missing","valid":None}
    if as_of is None or clock is None or timezone is None:return {"status":"UNKNOWN","reason":"explicit_clock_as_of_required","valid":None}
    if clock!=declared["clock"] or clock!=interval["clock"] or timezone!=declared["timezone"] or timezone!=interval["timezone"]:return {"status":"UNKNOWN","reason":"clock_timezone_mismatch","valid":None}
    if not _fixed_zone(timezone):return {"status":"UNKNOWN","reason":"timezone_or_dst_unsupported","valid":None}
    try:
        instant,start,end=(_instant(value)for value in (as_of,interval["start"],interval["end"]))
        expected=datetime.timedelta() if timezone=="UTC" else datetime.timedelta(minutes=(1 if timezone[0]=="+"else-1)*(int(timezone[1:3])*60+int(timezone[4:])))
        if any(value.utcoffset()!=expected for value in (instant,start,end)):return {"status":"UNKNOWN","reason":"explicit_offset_mismatch","valid":None}
    except BusinessError:return {"status":"UNKNOWN","reason":"explicit_aware_time_required","valid":None}
    lower=instant>=start if interval["bounds"] in ("closed","left_closed") else instant>start
    upper=instant<=end if interval["bounds"] in ("closed","right_closed") else instant<end
    return {"status":"valid" if lower and upper else "outside_interval","valid":lower and upper,"asOf":as_of,"clock":clock,"timezone":timezone,"bounds":interval["bounds"]}


def property_value(spec,value,*,source_output=False):
    _typed_value(spec)
    _typed_value(value)
    if spec["quantityKind"]in("time","UNKNOWN"):raise BusinessError("time_or_unknown_dimension_evaluation_unsupported")
    kind=spec["scalarType"];tag={"bool":"boolean","int":"integer","decimal":"decimal","string":"text"}.get(kind)
    expected="money" if spec["quantityKind"]=="money" else "quantity" if spec["quantityKind"]=="quantity" else tag
    result=copy.deepcopy(value)
    if source_output and kind in ("int","decimal") and value.get("type")==tag and expected in ("money","quantity"):
        result["type"]=expected;result["currency"if expected=="money"else"unit"]=spec["currency"if expected=="money"else"unit"]
        if kind=="int":result["value"]=str(result["value"])
        if expected=="money" and spec["unit"]!="UNKNOWN":result["unit"]=spec["unit"]
    if result.get("type")!=expected:raise BusinessError("property_value_type_or_dimension_mismatch")
    if expected in ("money","quantity"):
        key="currency"if expected=="money"else"unit"
        if result[key]!=spec[key]:raise BusinessError("property_value_unit_currency_mismatch")
        if expected=="money" and result.get("unit")!=(None if spec["unit"]=="UNKNOWN"else spec["unit"]):raise BusinessError("property_value_unit_currency_mismatch")
    if kind=="decimal":
        if spec["precision"]=="UNKNOWN" or spec["scale"]=="UNKNOWN" or spec["rounding"]=="UNKNOWN":raise BusinessError("explicit_decimal_contract_required")
        if any(k in result and result[k]!=spec[k] for k in ("precision","scale")):raise BusinessError("property_precision_scale_mismatch")
        _typed_value({"type":"decimal","value":result["value"],"precision":spec["precision"],"scale":spec["scale"]})
    if kind=="int":
        # Dimensional wire values retain decimal-string transport. Only an
        # exact whole-number spelling maps to a source int; never round,
        # rescale currencies, coerce floats or infer unit conversions.
        raw=result["value"]
        if expected in ("money","quantity"):
            if type(raw)is not str or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,100})",raw):raise BusinessError("exact_integer_dimension_required")
            raw=int(raw)
        _typed_value({"type":"integer","value":raw})
        if any(k in result and result[k]!=spec[k] for k in ("precision","scale")):raise BusinessError("property_precision_scale_mismatch")
        if spec["precision"]!="UNKNOWN":
            _typed_value({"type":"decimal","value":str(raw),"precision":spec["precision"],"scale":spec["scale"]})
    return result


def _source_property_value(spec,value):
    typed=property_value(spec,value)
    return int(typed["value"]) if spec["scalarType"]=="int" and spec["quantityKind"]in("money","quantity") else typed["value"]


def _source_typed(value):
    if type(value)is not dict or value.get("type") not in ("bool","int","decimal"):raise BusinessError("source_result_not_comparable")
    payload=value.get("value")
    if value["type"]=="bool":result={"type":"boolean","value":payload}
    elif value["type"]=="int":
        if type(payload)is not int and(type(payload)is not str or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,100})",payload)):raise BusinessError("source_result_not_comparable")
        result={"type":"integer","value":int(payload)}
    else:result={"type":"decimal","value":payload}
    return _typed_value(result)


def optional_decision(record,*,get_record,source_reader,source_pins,context=None,cases=None,objective="maximize_value",as_of=None,evaluate_source=None,approved_only=False):
    """Explicit bounded contracts only; supplied callback is the existing source evaluator."""
    if not (_declared(record,"inputs","formula_mapping") or _declared(record,"priority","policy_composition")):return None
    class Records:
        def __getitem__(self,identity):
            result=get_record(identity)
            if result is None:raise BusinessError("contract_record_missing")
            validate_record_values(result)
            return result
    records=Records()
    base={"authority":"explicit_reviewed_contract_plus_implemented_source","scope":"explicit_contract_selection_only","businessPolicyComplete":False,
          "globalOptimum":"UNKNOWN","runtimeStatus":"NOT_OBSERVED","executionAuthorization":"NOT_PROVIDED","policyIds":[record["id"]]}
    def unknown(reason,**extra):return {"status":"UNKNOWN","reason":reason,"value":None,
        "memberSelectionStatus":"UNKNOWN","activeMemberPolicyIds":None,"selectedMemberPolicyIds":None,
        "contributingPolicyIds":None,"contributingSourceRuleIds":None,"memberSelections":None,
        "activeSourceRuleIds":None,"conflictProven":False,"conflictAssessment":"UNDETERMINED",**extra}
    def selection(chosen=(),active=(),leaf=None,source=None):
        # The complete dependency inventory stays in selectedPolicyIds.
        # These separate fields describe only value-contributing members.
        return {"memberSelectionStatus":"RESOLVED","activeMemberPolicyIds":list(active),
            "selectedMemberPolicyIds":[identity for identity,_ in chosen],
            "contributingPolicyIds":sorted({leaf}if leaf is not None else {identity for _,item in chosen for identity in item["contributingPolicyIds"]}),
            "contributingSourceRuleIds":sorted({source}if source is not None else {identity for _,item in chosen for identity in item["contributingSourceRuleIds"]}),
            "memberSelections":[{"policyId":identity,"selectedMemberPolicyIds":item["selectedMemberPolicyIds"],
                "contributingPolicyIds":item["contributingPolicyIds"],"contributingSourceRuleIds":item["contributingSourceRuleIds"]}for identity,item in chosen]}
    def conflict_result(reason,active_pairs,*,policy_ids,source_ids,member_counts):
        # Sorting is presentation only. No tied identity is ever selected.
        witnesses=[{"memberPolicyId":identity,"applicableLeafWitnesses":sorted(item["applicabilityWitnesses"],
                key=lambda witness:(witness["compositionPath"],witness["policyId"],witness["sourceRuleId"]))}
            for identity,item in sorted(active_pairs,key=lambda pair:pair[0])]
        return unknown(reason,conflictProven=True,conflictAssessment="PROVEN",
            conflictKind="priority_selection_ambiguity" if reason=="priority_selection_ambiguity" else "at_most_one_violation",
            conflictScope="static_supplied_context_only",evaluationCompleteness="COMPLETE",
            policyIds=policy_ids,sourceRuleIds=source_ids,**member_counts,
            activeMemberPolicyIds=sorted(identity for identity,_ in active_pairs),
            activeSourceRuleIds=sorted({w["sourceRuleId"] for _,item in active_pairs for w in item["applicabilityWitnesses"]}),
            conflictWitnesses=witnesses)

    def one(policy,values,instant,clock,zone,trail=()):
        if policy["id"] in trail or len(trail)>=16:return unknown("composition_cycle_or_depth")
        if policy.get("support") in ("conflicted","revoked","stale","unsupported") or policy.get("businessApproval") in ("rejected","revoked"):return unknown("policy_conflicted_or_revoked")
        if approved_only and policy.get("businessApproval")!="approved":return unknown("business_approval_required")
        temporal=temporal_decision(policy,instant,clock,zone)
        if temporal["valid"] is None:return unknown(temporal["reason"],temporalDecision=temporal)
        if not temporal["valid"]:return {"status":"evaluated","applicable":False,"value":None,"temporalDecision":temporal,"policyIds":[policy["id"]],"sourceRuleIds":[],**selection()}
        conflict=policy["facets"].get("conflicts",{})
        if not(conflict.get("status")=="NOT_APPLICABLE" or conflict.get("status")=="DECLARED" and conflict.get("value")=={"type":"boolean","value":False}):return unknown("conflict_contract_missing_or_conflicted")
        if policy["facets"].get("exclusions",{}).get("status")!="NOT_APPLICABLE":return unknown("exclusion_contract_unsupported_or_missing")
        if policy["facets"].get("eligibility",{}).get("status")!="NOT_APPLICABLE":return unknown("eligibility_contract_unsupported_or_missing")
        composition=_composition_contract(policy)
        if composition:
            ordered=sorted(composition["members"],key=lambda item:item["priority"],reverse=composition["priorityOrder"]=="higher_first")
            outcomes=[{"memberPolicyId":item["policyId"],**one(records[item["policyId"]],values,instant,clock,zone,trail+(policy["id"],))}for item in ordered]
            member_counts={"memberPolicyDenominator":len(ordered),"evaluatedMemberPolicyNumerator":sum(item["status"]=="evaluated"for item in outcomes)}
            if any(item["status"]!="evaluated"for item in outcomes):return unknown("partial_composition",**member_counts,members=outcomes)
            active_pairs=[(member["policyId"],item)for member,item in zip(ordered,outcomes)if item.get("applicable")]
            applicable_ids=[identity for identity,_ in active_pairs]
            ids=[policy["id"]]+[identity for item in outcomes for identity in item.get("policyIds",[])];source_ids=[identity for item in outcomes for identity in item.get("sourceRuleIds",[])]
            if not active_pairs:return {"status":"evaluated","applicable":False,"value":None,"policyIds":ids,"sourceRuleIds":source_ids,**member_counts,**selection()}
            applicability_witnesses=[w for _,item in active_pairs for w in item["applicabilityWitnesses"]]
            if composition["exclusivity"]=="first_applicable":
                best_rank=next(member["priority"] for member in ordered if member["policyId"]==active_pairs[0][0])
                top_ids={member["policyId"] for member in ordered if member["priority"]==best_rank}
                top_pairs=[pair for pair in active_pairs if pair[0] in top_ids]
                if len(top_pairs)>1:
                    conflict=conflict_result("priority_selection_ambiguity",top_pairs,
                        policy_ids=ids,source_ids=source_ids,member_counts=member_counts)
                    conflict["activeMemberPolicyIds"]=sorted(applicable_ids)
                    conflict["activeSourceRuleIds"]=sorted({w["sourceRuleId"] for w in applicability_witnesses})
                    return conflict
                active_pairs=top_pairs
            if composition["exclusivity"]=="at_most_one" and len(active_pairs)>1:return conflict_result("explicit_exclusivity_conflict",active_pairs,
                policy_ids=ids,source_ids=source_ids,member_counts=member_counts)
            active=[item for _,item in active_pairs];chosen=active_pairs
            if len(active)>1:
                if composition["stacking"]=="none":return unknown("stacking_not_declared",policyIds=ids,**member_counts)
                if len({digest(item["propertyContract"])for item in active})!=1:return unknown("incomparable_property_contracts",policyIds=ids,**member_counts)
                try:
                    numbers=[Decimal(item["value"]["value"])for item in active]
                    if active[0]["propertyContract"]["scalarType"] not in ("int","decimal"):return unknown("composition_values_not_numeric",**member_counts)
                    with localcontext() as decimal_context:
                        # Inputs have <=128 characters and <=16 members. This
                        # computes the exact sum before checking declared bounds.
                        decimal_context.prec=256;decimal_context.rounding="ROUND_HALF_EVEN"
                        number=sum(numbers) if composition["stacking"]=="sum"else min(numbers)if composition["stacking"]=="min"else max(numbers)
                    if composition["stacking"]in("min","max"):chosen=[pair for pair,numeric in zip(active_pairs,numbers)if numeric==number]
                    value=copy.deepcopy(active[0]["value"]);value["value"]=int(number)if value["type"]=="integer"else format(number,'f')
                    value=property_value(active[0]["propertyContract"],value)
                except (BusinessError,InvalidOperation):return unknown("composition_numeric_contract_mismatch",**member_counts)
            else:value=active[0]["value"]
            return {"status":"evaluated","applicable":True,"value":value,"propertyContract":active[0]["propertyContract"],"policyIds":ids,"sourceRuleIds":source_ids,
                    **member_counts,"temporalDecision":temporal,"applicabilityWitnesses":applicability_witnesses,
                    **({"canonicalContracts":copy.deepcopy(policy["canonicalContracts"])} if "canonicalContracts" in policy else {}),
                    **selection(chosen,applicable_ids)}
        mapping=_declared(policy,"inputs","formula_mapping")
        if mapping is None:return unknown("explicit_source_mapping_missing")
        required={item["propertyId"]for item in mapping["inputs"]}
        missing=sorted(required-set(values))
        if missing:return unknown("missing_property_context",missingPropertyIds=missing)
        converted={}
        for item in mapping["inputs"]:
            prop=records[item["propertyId"]]
            if approved_only and prop.get("businessApproval")!="approved":return unknown("property_approval_required")
            if prop.get("support") in ("conflicted","revoked") or prop.get("businessApproval") in ("rejected","revoked"):return unknown("property_conflicted_or_revoked")
            # Store/property/source/spec validation stays outside the caller-
            # context recovery seam. The same code from those boundaries must
            # never be classified as a recoverable supplied value.
            spec=_property(prop);supplied=values[item["propertyId"]]
            if type(supplied) is not dict or supplied.get("type") not in ("boolean","integer","decimal","text","enum","quantity","money"):
                return unknown("unsupported_property_context",invalidPropertyIds=[item["propertyId"]])
            try:
                _typed_value(supplied)
                converted[item["parameter"]]=_source_property_value(spec,supplied)
            except BusinessError as exc:
                if exc.code not in _CONTEXT_VALUE_ERROR_CODES:raise
                return unknown("invalid_property_context",contextFailureCode=exc.code,invalidPropertyIds=[item["propertyId"]])
        result=evaluate_source(mapping["sourceRuleId"],converted,instant)
        if result.get("status")!="evaluated":return unknown("source_evaluation_partial",missingInputs=result.get("missingInputs",[]),
            sourceEvaluationStatus=result.get("status"),sourceEvaluationReason=result.get("reason"))
        output=records[mapping["outputPropertyId"]]
        if output.get("support") in ("conflicted","revoked") or output.get("businessApproval") in ("rejected","revoked") or approved_only and output.get("businessApproval")!="approved":return unknown("output_property_unavailable")
        spec=_property(output);value=property_value(spec,_source_typed(result["value"]),source_output=True)
        return {"status":"evaluated","applicable":True,"value":value,"propertyContract":spec,"outputPropertyId":output["id"],
                "policyIds":[policy["id"]],"sourceRuleIds":[mapping["sourceRuleId"]],"memberPolicyDenominator":1,"evaluatedMemberPolicyNumerator":1,"temporalDecision":temporal,
                "applicabilityWitnesses":[{"policyId":policy["id"],"sourceRuleId":mapping["sourceRuleId"],
                    "compositionPath":[*trail,policy["id"]],"status":"evaluated","applicable":True}],
                **selection(leaf=policy["id"],source=mapping["sourceRuleId"])}
    try:
        validate_contract_links(record,records,source_reader,source_pins)
        selected_ids,source_ids,required_properties=_contract_selection(record,records)
        base.update(selectedPolicyIds=selected_ids,selectedSourceRuleIds=source_ids,selectedPolicyDenominator=len(selected_ids))
        if cases is None:
            values=copy.deepcopy(context or {});clock=values.pop("$clock",None);zone=values.pop("$timezone",None)
            if set(values)-required_properties:return {**base,**unknown("unmapped_property_context"),"finiteBest":None}
            result=one(record,values,as_of,clock,zone)
            return {**base,**result,"selectedContextDenominator":1,"evaluatedContextNumerator":int(result["status"]=="evaluated"),"finiteBest":None}
        finite=_declared(record,"missing_context","finite_contexts")
        if finite is None or canonical(cases)!=canonical([item["values"]for item in finite["contexts"]]):return {**base,**unknown("reviewed_finite_context_set_mismatch"),"selectedContextDenominator":len(cases),"evaluatedContextNumerator":0,"finiteBest":None}
        outcomes=[]
        for item in finite["contexts"]:
            if as_of is not None and item["asOf"]!=as_of:result=unknown("finite_as_of_mismatch")
            else:result=one(record,item["values"],item["asOf"],item["clock"],item["timezone"])
            outcomes.append({"contextId":item["contextId"],**result})
        complete=all(item["status"]=="evaluated"and item.get("applicable")for item in outcomes)
        best=None
        if complete and objective in ("maximize_value","minimize_value") and len({digest(item["propertyContract"])for item in outcomes})==1:
            try:
                comparable=[item["value"]["value"]for item in outcomes]if outcomes[0]["propertyContract"]["scalarType"]=="bool"else[Decimal(item["value"]["value"])for item in outcomes]
                selected=max(comparable)if objective=="maximize_value"else min(comparable)
                best={"contextIds":[item["contextId"]for item,number in zip(outcomes,comparable)if number==selected],"value":outcomes[comparable.index(selected)]["value"],"scope":"explicit_reviewed_supplied_set_only","globalMaximum":False,"optimum":False}
                best["selections"]=[{key:item[key]for key in("contextId","selectedMemberPolicyIds","contributingPolicyIds","contributingSourceRuleIds")}for item,number in zip(outcomes,comparable)if number==selected]
            except (InvalidOperation,TypeError,ValueError):pass
        return {**base,"status":"finite_set_evaluated"if complete and best is not None else"UNKNOWN","reason":None if complete and best is not None else"partial_or_incomparable_finite_contexts", "cases":outcomes,
                "selectedContextDenominator":len(finite["contexts"]),"evaluatedContextNumerator":sum(item["status"]=="evaluated"for item in outcomes),"finiteBest":best}
    except (BusinessError,KeyError,TypeError,ValueError) as exc:return {**base,**unknown(getattr(exc,"code","optional_contract_unsupported")),"finiteBest":None}


REVIEW_DIAGNOSTIC_CODES = frozenset(("review_schema_rejected", "composition_stacking_missing",
    "composition_priority_tie", "composition_mode_contradiction", "duplicate_concept_identity"))
REVIEW_REJECTION_REASONS = frozenset(("object_shape_invalid", "composition_priority_tie", "composition_mode_conflict",
    "composition_mode_unsupported", "unresolved_concept_endpoint", "invalidated_concept_endpoint",
    "composition_member_mapping_required", "duplicate_concept_identity", "review_contract_rejected"))
REVIEW_OUTCOMES = frozenset(("accepted", "conflicted", "unsupported", "rejected", "omitted", "duplicate"))


def _review_diagnostic_codes(item):
    """Closed observations of a rejected request; never admit an invalid policy."""
    facet = item.get("facets", {}).get("priority") if type(item.get("facets")) is dict else None
    value = facet.get("value") if type(facet) is dict else None
    if type(value) is not dict or value.get("type") != "policy_composition": return ["review_schema_rejected"]
    codes = []
    if "stacking" not in value: codes.append("composition_stacking_missing")
    members = value.get("members")
    if (type(members) is list and 1 <= len(members) <= 16 and
            all(type(m) is dict and type(m.get("priority")) is int and abs(m["priority"]) <= 100000 for m in members)):
        ranks = [m["priority"] for m in members]
        if len(set(ranks)) != len(ranks): codes.append("composition_priority_tie")
    if value.get("exclusivity") in ("first_applicable", "at_most_one") and value.get("stacking") in ("sum", "min", "max"):
        codes.append("composition_mode_contradiction")
    return codes or ["review_schema_rejected"]


def validate_review_diagnostics(value, reader, source_pins, review_digest):
    if value is None: return
    _keys(value, ("schemaVersion", "reviewManifestDigest", "selectedInputs", "outcomeCounts", "entries"))
    if (type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["reviewManifestDigest"] != review_digest
            or type(review_digest) is not str or not HASH.fullmatch(review_digest)
            or type(value["selectedInputs"]) is not int or not 0 <= value["selectedInputs"] <= MAX_RECORDS
            or type(value["entries"]) is not list or len(value["entries"]) > value["selectedInputs"]):
        raise BusinessError("review_diagnostics_invalid")
    counts=value["outcomeCounts"]
    if (type(counts) is not dict or set(counts)!=REVIEW_OUTCOMES
            or any(type(n) is not int or n<0 for n in counts.values()) or sum(counts.values())!=value["selectedInputs"]):
        raise BusinessError("review_diagnostics_invalid")
    seen = set()
    for entry in value["entries"]:
        _keys(entry, ("inputIndex", "status", "attemptedRecordId", "diagnosticCodes", "rejectionReason", "sourceAnchors"))
        index = entry["inputIndex"]
        if (type(index) is not int or not 0 <= index < value["selectedInputs"] or index in seen
                or entry["status"] != "rejected" or type(entry["attemptedRecordId"]) is not str
                or not re.fullmatch(r"business:[0-9a-f]{64}", entry["attemptedRecordId"])
                or type(entry["diagnosticCodes"]) is not list or not 1 <= len(entry["diagnosticCodes"]) <= 3
                or any(type(code) is not str or code not in REVIEW_DIAGNOSTIC_CODES for code in entry["diagnosticCodes"])
                or type(entry["rejectionReason"]) is not str or entry["rejectionReason"] not in REVIEW_REJECTION_REASONS
                or type(entry["sourceAnchors"]) is not list or not 1 <= len(entry["sourceAnchors"]) <= 32):
            raise BusinessError("review_diagnostics_invalid")
        seen.add(index)
        for anchor in entry["sourceAnchors"]: validate_anchor(anchor, reader, source_pins=source_pins)


def validate_review(manifest, reader, *, source_pins, candidates, max_records=MAX_RECORDS):
    _safe(manifest)
    canonical(manifest)
    _keys(manifest, ("schemaVersion", "sourcePins", "concepts"),("processingContract",))
    processing=manifest.get("processingContract")
    if processing is not None and (type(processing)is not dict or type(processing.get("schemaVersion"))is not int or processing!={"schemaVersion":1,"scope":"original_selected_inputs"}):raise BusinessError("processing_contract_invalid")
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1: raise BusinessError("review_schema_invalid")
    if canonical(_pins(manifest["sourcePins"])) != canonical(_pins(source_pins)): raise BusinessError("source_pin_mismatch")
    selected = manifest["concepts"]
    if type(selected) is not list or type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS or len(selected) > MAX_RECORDS:
        raise BusinessError("review_budget_invalid")
    entries, records, identities, attempted = [], [], {}, {}
    for index, item in enumerate(selected):
        if index >= max_records:
            entries.append({"inputIndex": index, "status": "omitted", "reason": "review_record_budget"}); continue
        try:
            _keys(item, ("namespace", "domain", "kind", "conceptKey", "label", "sourceAnchors", "facets"), ("subject", "object", "role", "cardinality", "aliases"))
            for key in ("namespace", "domain", "conceptKey", "label"): _text(item[key])
            if item["namespace"] == "source": raise BusinessError("reserved_namespace")
            kind = item["kind"]
            if type(kind) is not str or kind not in KINDS or kind == "business_conflict": raise BusinessError("kind_invalid")
            anchors = item["sourceAnchors"]
            if type(anchors) is not list or not 1 <= len(anchors) <= 32: raise BusinessError("concept_anchors_invalid")
            for anchor in anchors: validate_anchor(anchor, reader, source_pins=source_pins)
            if len({digest(a) for a in anchors}) != len(anchors): raise BusinessError("duplicate_source_anchor")
            record = _base(item["namespace"], item["domain"], kind, item["conceptKey"], item["label"], copy.deepcopy(anchors))
            attempted[index] = {"attemptedRecordId": record["id"], "sourceAnchors": copy.deepcopy(anchors),
                                "diagnosticCodes": _review_diagnostic_codes(item)}
            if type(item["facets"]) is not dict or set(item["facets"]) - set(FACETS[kind]): raise BusinessError("facet_name_invalid")
            for key,value in item["facets"].items(): record["facets"][key] = _facet(value, reader, source_pins, key)
            derived=_expected_canonical_contracts(record)
            if derived:record["canonicalContracts"]=derived
            for key in ("subject", "object", "role"):
                if key in item: record[key] = _text(item[key])
            if kind == "business_relation" and not all(key in record for key in ("subject", "object", "role")):
                raise BusinessError("relation_endpoint_missing")
            if "cardinality" in item:
                card = item["cardinality"]
                if card != "UNKNOWN":
                    _keys(card, ("min", "max"))
                    if type(card["min"]) is not int or card["min"] < 0 or (card["max"] is not None and (type(card["max"]) is not int or card["max"] < card["min"])):
                        raise BusinessError("cardinality_invalid")
                record["cardinality"] = copy.deepcopy(card)
            elif kind == "business_relation": record["cardinality"] = "UNKNOWN"
            if "aliases" in item:
                aliases = item["aliases"]
                if type(aliases) is not list or len(aliases) > 32: raise BusinessError("aliases_invalid")
                for alias in aliases:
                    _keys(alias, ("target", "relation", "basis"))
                    for v in alias.values(): _text(v)
                    if alias["relation"] not in ("alias", "equivalent"): raise BusinessError("alias_relation_invalid")
                record["aliases"] = copy.deepcopy(aliases)
            record["support"] = "source_supported" if any(f["status"] == "SOURCE_SUPPORTED" for f in record["facets"].values()) and all(f["status"] in ("SOURCE_SUPPORTED", "NOT_APPLICABLE") for f in record["facets"].values()) else "candidate"
            conflict=record["facets"].get("conflicts",{})
            value=conflict.get("value",{})
            if conflict.get("status") in ("DECLARED","SOURCE_SUPPORTED") and (value=={"type":"boolean","value":True} or value.get("type")=="sequence" and value.get("items")):
                record["support"]="conflicted"
                entries.append({"inputIndex":index,"status":"conflicted","reason":"explicit_policy_conflict"})
            record["reviewedMeaning"] = "declared_attestation"
            record["inputIndex"] = index
            if processing is not None:record["processingScopeId"]="processing:"+digest(["explicit_review_concepts",digest(manifest)])
            identities.setdefault(record["id"], []).append(len(records))
            records.append(record)
        except BusinessError as exc:
            entries.append({"inputIndex": index, "status": "rejected", "reason": exc.code})
    ids = {r["id"] for r in records}
    # Every duplicate remains an original input entry, and none is approved.
    # A shape-rejected input with a validated identity/anchor still makes that
    # identity ambiguous; do not silently choose its otherwise valid neighbor.
    attempted_counts = {}
    for entry in attempted.values():
        rid = entry["attemptedRecordId"]
        attempted_counts[rid] = attempted_counts.get(rid, 0) + 1
    rejected_indices = set()
    for rid, positions in identities.items():
        if attempted_counts.get(rid, 0) > 1:
            for pos in positions:
                rejected_indices.add(pos)
                entries.append({"inputIndex": records[pos]["inputIndex"], "status": "conflicted", "reason": "duplicate_concept_identity"})
    for pos, record in enumerate(records):
        targets = concept_targets(record)
        if any(t not in ids or len(identities.get(t, [])) != 1 for t in targets):
            rejected_indices.add(pos); entries.append({"inputIndex": record["inputIndex"], "status": "rejected", "reason": "unresolved_concept_endpoint"})
        if pos not in rejected_indices:
            try:validate_contract_links(record,{r["id"]:r for r in records},reader,source_pins)
            except (BusinessError,KeyError) as exc:
                rejected_indices.add(pos);entries.append({"inputIndex":record["inputIndex"],"status":"rejected","reason":getattr(exc,"code","contract_endpoint_missing")})
    # Reference closure: rejecting an endpoint also rejects dependent relations.
    changed = True
    while changed:
        changed = False
        invalid = {records[i]["id"] for i in rejected_indices}
        for pos, record in enumerate(records):
            targets = concept_targets(record)
            if pos not in rejected_indices and any(t in invalid for t in targets):
                rejected_indices.add(pos); changed = True
                entries.append({"inputIndex": record["inputIndex"], "status": "rejected", "reason": "invalidated_concept_endpoint"})
    accepted = [seal_record(r) for i,r in enumerate(records) if i not in rejected_indices]
    omitted_inputs={entry["inputIndex"]for entry in entries if entry.get("status")=="omitted" and type(entry.get("inputIndex"))is int}
    result = {"records": accepted, "coverage": _coverage(len(selected), len(accepted), entries, scope="explicit_review_concepts",omitted=len(omitted_inputs)),
              "omissions": entries, "reviewManifestDigest": digest(manifest)}
    diagnostics = []
    for entry in entries:
        index = entry.get("inputIndex")
        if index in attempted and entry.get("status") in ("rejected", "conflicted"):
            diagnostics.append({"inputIndex": index, "status": "rejected", **attempted[index],
                "rejectionReason": entry["reason"] if entry.get("reason") in REVIEW_REJECTION_REASONS else "review_contract_rejected",
                "diagnosticCodes": (["duplicate_concept_identity"] if entry.get("reason") == "duplicate_concept_identity"
                                    else attempted[index]["diagnosticCodes"])})
    # One entry per original input, even when closure adds another rejection.
    diagnostics = list({entry["inputIndex"]: entry for entry in diagnostics}.values())
    if diagnostics:
        result["currentReviewDiagnostics"] = {"schemaVersion": 1, "reviewManifestDigest": result["reviewManifestDigest"],
            "selectedInputs": len(selected), "outcomeCounts": processing_reconciliation(len(selected),accepted,entries,scope_id=None)["outcomeCounts"],
            "entries": diagnostics}
    if processing is not None:
        scope_id="processing:"+digest(["explicit_review_concepts",digest(manifest)])
        result["coverage"].update(processingContract=True,processingScopeId=scope_id,
            processingScopes=[{"scopeId":scope_id,"denominator":len(selected),"kind":"explicit_review_concepts"}])
        result["coverage"]["processingReconciliation"]=processing_reconciliation(len(selected),accepted,entries,scope_id=scope_id)
    _safe(result)
    return result
