"""Project the same repository-scoped Java facts into sealed pipeline records."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import re

import pipeline_adapters as adapters
policy_java_platform = adapters.core._load_bundled_helper("policy_java_platform")


def _source_definition_ranges(index, item):
    """Exact Unicode codepoint ranges shared by projection and owner joins."""
    code = index.files[item["path"]]["code"]
    callable_item = "match" in item
    if callable_item:
        match = item["match"]
        start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
        end = item.get("body_end", match.end() - 1) + 1
        opening = item.get("body_start")
        opening = opening - 1 if opening is not None else None
    else:
        start, end, opening = item["start"], item["body_end"] + 1, item["body_start"]
    if not 0 <= start < end <= len(code):
        return {}
    declaration = {"charStart": start, "charEnd": end}
    ranges = {"sourceRange": dict(declaration), "declarationRange": dict(declaration)}
    if opening is not None:
        if not start <= opening < end - 1 or code[opening] != "{" or code[end - 1] != "}":
            return {}
        ranges["bodyRange"] = {"charStart": opening, "charEnd": end}
    return ranges


def _type_import_bindings(index, path):
    code = index.files[path]["code"]
    matches = list(re.finditer(r"\bimport\s+(?P<static>static\s+)?(?P<name>[\w.]+(?:\.\*)?)\s*;", code))
    rows = [{"qualifiedName": m["name"], "kind": "static" if m["static"] else "type",
             "sourceRange": {"charStart": m.start(), "charEnd": m.end()}}
            for m in matches[:64] if len(m["name"]) <= 1024]
    return {"typeImports": rows, "typeImportCoverage": {"detected": len(matches), "recorded": len(rows),
            "complete": len(rows) == len(matches), "status": "declared" if len(rows) == len(matches) else "PARTIAL"}}


def _type_declaration_eligibility(index, scope, symbol):
    """Bounded source access metadata, without compiler or runtime claims."""
    file = index.files[scope["path"]]
    match = index.core.JAVA_TYPE_RE.match(file["code"], scope["start"])
    prefix = re.split(r"\b(?:class|interface|record|enum)\b|@interface", match.group(0), maxsplit=1)[0] if match else ""
    modifiers = re.findall(r"\b(?:public|protected|private|static|abstract|final|strictfp|sealed|non-sealed)\b", prefix)
    valid = bool(match) and len(modifiers) == len(set(modifiers)) and len(set(modifiers) & {"public", "protected", "private"}) <= 1
    parents = [item for item in file["scopes"] if item["start"] < scope["start"] < scope["body_end"] <= item["body_end"]
        and scope["qualified_name"].startswith(item["qualified_name"] + ".")]
    parent = min(parents, key=lambda item: item["body_end"] - item["start"]) if parents else None
    return {"schemaVersion": 1, "status": "source_header_only" if valid else "UNKNOWN",
        "modifiers": sorted(modifiers), "enclosingTypeId": symbol(parent["id"]) if parent else None,
        "scope": "named_type_access_not_compiler_validity"}


def _callback_declaration(index, method, symbol, *, source_modifiers=None):
    """Names/header evidence for a callback, never a synthesized invocation."""
    match = method["match"]
    prefix = index.files[method["path"]]["code"][match.end("annotations"):match.start("return")]
    generic = match.group("type_parameters") or ""
    if generic: prefix = prefix.replace(generic, "", 1)
    modifiers = prefix.split()
    allowed = {"public", "protected", "private", "abstract", "final", "static", "synchronized", "native", "default", "strictfp"}
    access = set(modifiers) & {"public", "protected", "private"}
    valid = (all(m in allowed for m in modifiers) and len(set(modifiers)) == len(modifiers)
        and len(access) <= 1 and bool(method["static"]) == ("static" in modifiers)
        and ("default" not in modifiers or index.types.get(method["owner"],{}).get("kind")=="interface"))
    ranges = _source_definition_ranges(index, method)
    # Keep the existing closed callback-header contract byte-for-byte shaped.
    # Source helper eligibility has a separate, root-Method-bound metadata field.
    if source_modifiers is not None:
        source_modifiers.extend(sorted(modifiers) if valid else [])
    return {"schemaVersion": 1, "scope": "bounded_source_method_header",
        "ownerTypeId": symbol(method["owner_id"]),
        "headerRange": {"charStart": ranges.get("sourceRange", {}).get("charStart", match.start()), "charEnd": match.end()},
        "invocationKind": "static" if method["static"] else "instance",
        "access": next(iter(access)) if valid and access else "package" if valid else "UNKNOWN",
        "varargs": bool(method["varargs"]), "generic": bool(method["type_parameters"]),
        "hasBody": "bodyRange" in ranges and not ({"abstract", "native"} & set(modifiers)),
        "declarationValidity": "bounded_header_only" if valid else "UNKNOWN"}


def _callback_inventory(index, scope, inventory, symbol):
    cached=getattr(index,"_callback_inventory_index",None)
    if cached is None:
        counts={};grouped={}
        for file in index.files.values():
            for selected in file["scopes"]:
                name=selected["qualified_name"];counts[name]=counts.get(name,0)+1
            for method in file["methods"]:
                grouped.setdefault((method["path"],method["owner"]),[]).append(method)
        cached=(counts,grouped);index._callback_inventory_index=cached
    methods = cached[1].get((scope["path"],scope["qualified_name"]),[])
    identities = [symbol(m["id"]) for m in methods]
    count = cached[0].get(scope["qualified_name"],0)
    reason = ("duplicate_type_declaration" if count != 1 else "duplicate_method_identity" if len(set(identities)) != len(identities)
        else "method_inventory_budget_exceeded" if len(identities) > 64 else "source_member_inventory_unverified"
        if inventory.get("fields") != "complete" or inventory.get("memberTypes") != "complete" or inventory.get("reasons") else None)
    return {"schemaVersion": 1, "scope": "bounded_direct_indexed_method_headers",
        "sourceDigest": index.files[scope["path"]]["sourceHash"], "declarationIds": list(dict.fromkeys(identities[:64])),
        "detectedDeclarations": len(identities), "omittedDeclarations": max(0, len(identities) - len(set(identities[:64]))),
        "selectedTypeDeclarationCount": count, "status": "UNKNOWN" if reason else "complete", "reason": reason}


def _callback_type_namespace(index, scope, inventory, symbol):
    """Finite names already inventoried in selected type headers, not a resolver."""
    cached=getattr(index,"_callback_type_namespace_index",None)
    if cached is None:
        children={};packages={}
        for file in index.files.values():
            for declaration in file["scopes"]:
                parent=_type_declaration_eligibility(index,declaration,symbol).get("enclosingTypeId")
                if parent:children.setdefault(parent,[]).append(declaration)
                else:packages.setdefault(file["package"],[]).append(declaration)
        cached=(children,packages);index._callback_type_namespace_index=cached
    direct=set(inventory.get("_directTypeIds",[]));source_file=index.files[scope["path"]]
    candidates=[(item,"direct_member" if item["id"] in direct else "local_or_nonmember")
        for item in cached[0].get(symbol(scope["id"]),[])]
    candidates += [(item,"same_package_top_level") for item in cached[1].get(source_file["package"],[])]
    candidates.sort(key=lambda pair:(pair[1],pair[0]["path"],pair[0]["start"],pair[0]["id"]))
    identities=[symbol(item["id"]) for item,relation in candidates]
    duplicate=len(set(identities))!=len(identities)
    reason=("duplicate_type_namespace_identity" if duplicate else "type_namespace_budget_exceeded" if len(candidates)>64
        else "source_type_namespace_unverified" if inventory.get("fields")!="complete" or inventory.get("memberTypes")!="complete"
        or inventory.get("reasons") else None)
    declarations=[];seen=set()
    for item,relation in candidates:
        identity=symbol(item["id"])
        if identity in seen or len(declarations)>=64:continue
        seen.add(identity)
        declarations.append({"recordId":identity,"name":item["name"],"qualifiedName":item["qualified_name"],
            "path":item["path"],"sourceDigest":index.files[item["path"]]["sourceHash"],
            "sourceRange":{"charStart":item["start"],"charEnd":item["body_end"]+1},"relation":relation})
    return {"schemaVersion":1,"scope":"bounded_selected_lexical_and_package_type_names",
        "sourceDigest":source_file["sourceHash"],"declarations":declarations,"detectedDeclarations":len(candidates),
        "omittedDeclarations":len(candidates)-len(declarations),"status":"UNKNOWN" if reason else "complete","reason":reason}


def _selected_static_field_declaration(index, declaration, inventory):
    """One exact, direct, unannotated static-final field declaration.

    This shared syntax projection supplies both the actual type catalog and
    each selection reference. It never evaluates the initializer or turns a
    callable/local/initializer declaration into a direct member.
    """
    scope = index.types.get(declaration["owner"])
    if scope is None or scope["path"] != declaration["path"]:
        return None
    modifiers = declaration["modifiers"]
    if (not {"static", "final"} <= set(modifiers) or len(modifiers) != len(set(modifiers))
            or len(set(modifiers) & {"public", "protected", "private"}) > 1 or "volatile" in modifiers):
        return None
    file = index.files[declaration["path"]]
    code, cursor = file["code"], declaration["headerEnd"]
    while cursor < scope["body_end"] and code[cursor].isspace(): cursor += 1
    if cursor >= scope["body_end"] or code[cursor] != "=": return None
    assignment = cursor; cursor += 1
    while cursor < scope["body_end"]:
        if code[cursor] == ";": break
        if code[cursor] == ",": return None
        if code[cursor] == "(": cursor = index.core._matching_java_parenthesis(code, cursor, scope["body_end"])
        elif code[cursor] == "{": cursor = index.core._matching_java_brace(code, cursor)
        cursor += 1
    if cursor >= scope["body_end"]: return None
    start, end = declaration["start"], cursor + 1
    before = start - 1
    while before >= scope["body_start"] and code[before].isspace(): before -= 1
    if before < scope["body_start"] or code[before] not in "{};": return None
    # This is declaration-role evidence. Initializer semantics remain a
    # separate actual fragment obligation; array/type-only declarations must
    # not inherit the stronger whole-initializer inventory grammar here.
    if inventory.field_names(code[start:assignment].rstrip(), file["original"][start:assignment].rstrip()) != [declaration["name"]]: return None
    return {"schemaVersion": 1, "role": "direct_type_static_final_field", "name": declaration["name"],
        "declaredType": declaration["typeReference"]["rawType"],
        "sourceRange": {"charStart": start, "charEnd": end},
        "initializerRange": {"charStart": assignment + 1, "charEnd": cursor}, "modifiers": sorted(modifiers)}


def _static_field_catalog(index, declarations, inventory):
    candidates = [item for item in declarations if {"static", "final"} <= set(item["modifiers"])]
    entries, unsupported, omitted = [], 0, 0
    for position, item in enumerate(candidates):
        if position >= policy_java_platform.MAX_SOURCE_MEMBERS:
            omitted += 1; continue
        entry = _selected_static_field_declaration(index, item, inventory)
        if entry is None:
            unsupported += 1; continue
        if len(adapters.canonical(entries + [entry])) > policy_java_platform.MAX_CATALOG_BYTES:
            omitted += 1; continue
        entries.append(entry)
    return {"schemaVersion": 1, "scope": "bounded_indexed_direct_static_final_declarations",
        "detectedCandidates": len(candidates), "declarations": entries, "unsupportedCandidates": unsupported,
        "budgetOmittedCandidates": omitted, "completeForDetectedCandidates": unsupported == omitted == 0,
        "wholeFieldDeclarationDenominator": "UNKNOWN", "initializerValues": "not_evaluated"}




def _record_component_header(index, record):
    """Source positions and sanitized type syntax shared by both projections.

    The index's masked code has the original character offsets. Annotation
    arguments are removed structurally, including numeric values; no raw
    component/annotation text is exposed on an unsupported path.
    """
    file = index.files[record["path"]]; code = file["code"]
    unknown = {"components": [], "detected": None, "reasons": ["record_component_header_unsupported"]}
    match = index.core.JAVA_TYPE_RE.match(code, record["start"])
    if not match:
        return unknown
    cursor = match.end()
    while cursor < record["body_start"] and code[cursor].isspace(): cursor += 1
    if cursor < record["body_start"] and code[cursor] == "<":
        depth = 0
        while cursor < record["body_start"]:
            depth += (code[cursor] == "<") - (code[cursor] == ">")
            cursor += 1
            if depth == 0: break
        if depth: return unknown
        while cursor < record["body_start"] and code[cursor].isspace(): cursor += 1
    opening = cursor
    if opening >= record["body_start"] or code[opening] != "(": return unknown
    closing = index.core._matching_java_parenthesis(code, opening, record["body_start"])
    if closing >= record["body_start"] or code[closing] != ")": return unknown
    header = code[opening + 1:closing]
    pieces = index.core._split_java_parameters(header)
    if header.rstrip().endswith(","): pieces.append("")

    def without_annotations(value):
        output = []; cursor = 0
        while cursor < len(value):
            if value[cursor] != "@":
                output.append(value[cursor]); cursor += 1; continue
            annotation = re.match(r"@[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*", value[cursor:])
            if not annotation: return None
            cursor += annotation.end()
            while cursor < len(value) and value[cursor].isspace(): cursor += 1
            if cursor < len(value) and value[cursor] == "(":
                end = index.core._matching_java_parenthesis(value, cursor, len(value))
                if end == len(value): return None
                cursor = end + 1
            output.append(" ")
        return "".join(output)

    sanitized_header = without_annotations(header)
    stack = []
    if sanitized_header is not None:
        for char in sanitized_header:
            if char in "<[": stack.append(">" if char == "<" else "]")
            elif char in ">]":
                if not stack or stack.pop() != char:
                    sanitized_header = None; break
    sanitized_pieces = index.core._split_java_parameters(sanitized_header) if sanitized_header is not None else []
    if sanitized_header is not None and sanitized_header.rstrip().endswith(","):
        sanitized_pieces.append("")
    if sanitized_header is None or stack or len(sanitized_pieces) != len(pieces):
        # Unbalanced type punctuation or annotation expressions that confuse
        # the bounded splitter do not establish the original component count.
        return {**unknown, "sourceRange": {"charStart": opening, "charEnd": closing + 1}}

    def type_syntax_supported(raw):
        tokens = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|\.\.\.|[.<>?,\[\]]|\s+", raw)
        if "".join(tokens) != raw: return False
        tokens = [t for t in tokens if not t.isspace()]
        def parse(cursor, depth=0, wildcard=False):
            if depth > 32 or cursor >= len(tokens): return None
            if tokens[cursor] == "?":
                if not wildcard: return None
                cursor += 1
                return parse(cursor + 1, depth + 1) if cursor < len(tokens) and tokens[cursor] in {"extends", "super"} else cursor
            while True:
                if cursor >= len(tokens) or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", tokens[cursor]) or tokens[cursor] in {"extends", "super", "final", "var", "void"}: return None
                cursor += 1
                if cursor < len(tokens) and tokens[cursor] == "<":
                    cursor = parse(cursor + 1, depth + 1, True)
                    while cursor is not None and cursor < len(tokens) and tokens[cursor] == ",":
                        cursor = parse(cursor + 1, depth + 1, True)
                    if cursor is None or cursor >= len(tokens) or tokens[cursor] != ">": return None
                    cursor += 1
                if cursor < len(tokens) and tokens[cursor] == ".": cursor += 1
                else: break
            while cursor + 1 < len(tokens) and tokens[cursor:cursor + 2] == ["[", "]"]: cursor += 2
            if cursor < len(tokens) and tokens[cursor] == "...": cursor += 1
            return cursor
        return bool(tokens) and parse(0) == len(tokens)

    components = []; cursor = opening + 1
    forbidden = {"_", "clone", "finalize", "getClass", "hashCode", "notify", "notifyAll", "toString", "wait"}
    for piece in pieces:
        start = code.find(piece, cursor, closing) if piece else cursor
        if start < 0: return unknown
        end = start + len(piece); cursor = end
        clean = without_annotations(piece)
        parsed = re.fullmatch(r"\s*(?P<type>.+?)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*", clean or "", re.S)
        component = {"start": start, "end": end, "name": parsed["name"] if parsed else None,
                     "rawType": None, "reasons": []}
        raw = parsed["type"].strip() if parsed else ""
        # Type syntax contains identifiers and type punctuation, not values,
        # quoted data, annotation bodies or arbitrary malformed source text.
        if re.search(r"\bvoid\b", raw):
            component["reasons"].append("record_component_void_type_invalid")
        elif not parsed or not type_syntax_supported(raw):
            component["reasons"].append("record_component_syntax_unsupported")
        elif parsed["name"] in forbidden:
            component["reasons"].append("record_component_name_invalid")
        else:
            component["rawType"] = raw
        components.append(component)
    names = set(); duplicates = set()
    for component in components:
        name = component["name"]
        if name is not None:
            if name in names: duplicates.add(name)
            names.add(name)
    for component in components:
        if component["name"] in duplicates:
            component["reasons"].append("duplicate_record_component_name")
    for component in components[:-1]:
        if component["rawType"] and "..." in component["rawType"]:
            component["reasons"].append("record_varargs_component_not_last")
    return {"components": components, "detected": len(components),
            "sourceRange": {"charStart": opening, "charEnd": closing + 1},
            "reasons": sorted({reason for c in components for reason in c["reasons"]})}


def semantic_type_context(facts, index):
    """In-process type evidence bridge; no source text or callbacks are emitted.

    Uses the very same index as the symbol/callsite projection. Offsets identify
    lexical owners even when multiple overloads share a source line.
    """
    path = facts["path"]
    file = index.files[path]
    if file["sourceHash"] != facts["sourceDigest"]:
        raise adapters.AdapterError("java_source_binding_mismatch")
    methods = file["methods"]
    types = [item for item in index.types.values() if item["path"] == path]
    line_offsets = [0] + [i + 1 for i, ch in enumerate(file["code"]) if ch == "\n"]
    calls = {line_offsets[row["line_start"] - 1] + row["column"] - 1: row
             for row in index.calls.get(path, [])}
    annotation_prefixes = []
    for method in methods:
        left, right = method["match"].span("annotations")
        if left >= 0 and right > left:
            annotation_prefixes.append((left, right, method, "method"))
    type_by_start = {item["start"]: item for item in types}
    for match in index.core.JAVA_TYPE_RE.finditer(file["code"]):
        item = type_by_start.get(match.start())
        left, right = match.span("annotations")
        if item and left >= 0 and right > left:
            annotation_prefixes.append((left, right, item, item["kind"]))

    def symbol(identity):
        return adapters.identifier("java-declaration", identity)

    def annotation_target(offset):
        matches = [(item, kind) for left, right, item, kind in annotation_prefixes if left <= offset < right]
        if len(matches) != 1:
            return {"resolution": "UNKNOWN", "reason": "annotation_target_not_proven"}
        item, kind = matches[0]
        return {"resolution": "source_declaration_prefix", "kind": kind, "name": item["name"],
                "sourceEvidenceIds": [symbol(item["id"])], "annotationApplicability": "UNKNOWN"}

    def annotation_context(offset):
        # Privacy context is broader than a proven annotation target: a
        # parameter/type-use annotation still occurs in its callable/type.
        return ([m["name"] for m in methods if m["match_start"] <= offset < m["match"].end()]
                + [t["name"] for t in types if t["start"] <= offset <= t["body_end"]])

    inheritance = policy_java_platform.Inheritance(index, symbol, lambda scope: _record_component_header(index, scope))

    @lru_cache(maxsize=20_000)
    def legacy_inherited_name_possible(owner, name, values=False):
        """An absent selected declaration is not proof of an absent member."""
        def visit(current, seen):
            if current in seen:
                return True
            scope = index.types.get(current)
            if scope is None:
                return current not in {"Object", "java.lang.Object"}
            parents = index.core._java_hierarchy(scope["header"], scope["kind"])
            for raw_parent in parents[0] + parents[1]:
                parent = index.type_name(index.files[scope["path"]], raw_parent, current)
                if parent + "." + name in index.types or (values and (parent, name) in index.fields):
                    return True
                if visit(parent, seen | {current}):
                    return True
            return False
        return visit(owner, set()) if owner else False

    def inherited_name_possible(owner, name, values=False):
        return (inheritance.possible(owner, name, values) if inheritance.stack
                else legacy_inherited_name_possible(owner, name, values))

    def lexical_owner(offset):
        enclosing = [t for t in types if t["start"] <= offset <= t["body_end"]]
        return min(enclosing, key=lambda t: t["body_end"] - t["start"])["qualified_name"] if enclosing else ""

    @inheritance.cached
    def value_head_shadowed(name, offset):
        current = lexical_owner(offset)
        while current:
            if (current, name) in index.fields or (current in index.types and inherited_name_possible(current, name, True)):
                return True
            current = current.rsplit(".", 1)[0] if "." in current else ""
        for imported in file["staticImports"]:
            if not imported.endswith(".*"):
                if imported.rsplit(".", 1)[-1] == name:
                    return True
                continue
            owner = imported[:-2]
            if owner not in index.types or (owner, name) in index.fields or owner + "." + name in index.types:
                return True
            if inherited_name_possible(owner, name, True):
                return True
        return False

    def type_head_shadowed(raw, owner, method=None, reference_file=None):
        reference_file = reference_file or file
        head = index.core._clean_java_type(raw).split(".", 1)[0].strip()
        variables = {**index._type_variables(owner), **({p["name"]: p["rawBounds"] for p in method["type_parameters"]} if method else {})}
        if head in variables:
            return True
        if len(inheritance.imports(reference_file["path"]).get(head, ())) > 1:
            return True
        current = owner
        while current:
            if current + "." + head in index.types or current.rsplit(".", 1)[-1] == head:
                return True
            if current in index.types and inherited_name_possible(current, head):
                return True
            current = current.rsplit(".", 1)[0] if "." in current else ""
        return (reference_file["package"] + "." + head).strip(".") in index.types

    def platform_time_reference(ref, reference_file, owner, method=None):
        """Semantic-only evidence for bounded platform on-demand imports.

        Do not rewrite JavaIndex signatures or CALLS. Unknown additional
        on-demand packages/member types may contain the same simple name.
        A single explicit type import has precedence over on-demand imports.
        """
        raw = index.core._clean_java_type(ref["rawType"])
        known = {"Instant": "java.time.Instant", "Duration": "java.time.Duration",
                 "Temporal": "java.time.temporal.Temporal"}
        if raw not in known:
            return ref
        candidate = known[raw]
        explicit = {m.group(1) for m in re.finditer(r"\bimport\s+([\w.]+)\s*;", reference_file["code"])
                    if m.group(1).rsplit(".", 1)[-1] == raw}
        if len(explicit) > 1:
            return {**ref, "resolution": "ambiguous", "resolvedType": None}
        if explicit or ref["resolution"] not in {"unresolved", "resolved"}:
            return ref
        package = candidate.rsplit(".", 1)[0]
        if package not in reference_file["wildcards"]:
            return ref
        if (type_head_shadowed(raw, owner, method, reference_file)
                or reference_file["wildcards"] - {package, "java.lang"}
                or any(q.endswith(".*") or q.rsplit(".", 1)[-1] == raw for q in reference_file["staticImports"])
                or candidate in index.types):
            return {**ref, "resolution": "ambiguous", "resolvedType": None}
        name = candidate + "[]" * ref.get("arrayDimensions", 0)
        return {**ref, "resolution": "resolved", "resolvedType": name, "erasedType": name,
                "reason": "bounded_platform_on_demand_import", "candidates": [candidate]}

    def static_import(name, offset, known_members):
        owner = lexical_owner(offset)
        containing = [m for m in methods if m["match_start"] <= offset <= m.get("body_end", m["match"].end())]
        method = min(containing, key=lambda m: m.get("body_end", m["match"].end()) - m["match_start"]) if containing else None
        if type_head_shadowed(name, owner, method) or name in file["imports"]:
            return None
        current = owner
        while current:
            if ((current, name) in index.fields
                    or (current in index.types and inherited_name_possible(current, name, True))):
                return None
            current = current.rsplit(".", 1)[0] if "." in current else ""
        explicit = {q for q in file["staticImports"] if not q.endswith(".*") and q.rsplit(".", 1)[-1] == name}
        if explicit:
            if len(explicit) != 1:
                return None
            imported = next(iter(explicit)); target = imported.rsplit(".", 1)[0]
            if name not in known_members.get(target, set()):
                return None
            basis = "single_static_import"
        else:
            on_demand = {q[:-2] for q in file["staticImports"] if q.endswith(".*")}
            # No completeness claim for unselected external wildcard owners.
            if any(q not in known_members for q in on_demand):
                return None
            candidates = {q for q in on_demand if name in known_members[q]}
            if len(candidates) != 1:
                return None
            target = candidates.pop(); imported = target + ".*"; basis = "bounded_static_on_demand_import"
        if target in index.types or any(target.startswith(q + ".") for q in index.types):
            return None
        matches = [m for m in re.finditer(r"\bimport\s+static\s+([\w.]+(?:\.\*)?)\s*;", file["code"])
                   if m.group(1) == imported]
        if not matches:
            return None
        match = matches[0]
        return {"name": target, "_platformOrigin": type_origin(owner, path, "static_import", sourcePosition=offset), "sourceEvidenceIds": [symbol(method["id"])] if method else [symbol(t["id"]) for t in types if t["start"] <= offset <= t["body_end"]],
            "sourceImport": {"binding": basis, "path": path, "sourceDigest": file["sourceHash"],
                "sourceRange": {"charStart": match.start(), "charEnd": match.end(),
                    "byteStart": len(file["original"][:match.start()].encode("utf-8")),
                    "byteEnd": len(file["original"][:match.end()].encode("utf-8"))},
                "identicalDeclarationCount": len(matches), "runtimeValue": "UNKNOWN"}}

    def imported_source_field(name, offset):
        """A unique selected static-final declaration; initializer stays a ref."""
        caller = lexical_owner(offset)
        containing = [m for m in methods if m["match_start"] <= offset <= m.get("body_end", m["match"].end())]
        method = min(containing, key=lambda m: m.get("body_end", m["match"].end())-m["match_start"]) if containing else None
        if type_head_shadowed(name, caller, method) or name in file["imports"]:
            return None
        current = caller
        while current:
            if (current, name) in index.fields or (current in index.types and inherited_name_possible(current, name, True)):
                return None
            current = current.rsplit(".", 1)[0] if "." in current else ""
        explicit = {q for q in file["staticImports"] if not q.endswith(".*") and q.rsplit(".",1)[-1] == name}
        if explicit:
            if len(explicit) != 1: return None
            owners = {next(iter(explicit)).rsplit(".",1)[0]}
        else:
            owners = {q[:-2] for q in file["staticImports"] if q.endswith(".*")}
            if any(owner not in index.types for owner in owners):
                return None
        candidates = [d for owner in owners for d in index.field_declarations.get((owner,name), [])]
        if len(candidates) != 1:
            return None
        declaration = candidates[0]; owner = declaration["owner"]; scope = index.types[owner]
        if owner.startswith("java.") or not {"static","final"} <= set(declaration["modifiers"]):
            return None
        source_file = index.files[declaration["path"]]
        enclosing = [t for t in source_file["scopes"] if t["start"] <= scope["start"] <= t["body_end"]]
        if not enclosing or caller not in index.types:
            return None
        nest = min(enclosing,key=lambda t:t["start"])["qualified_name"]
        same_nest = caller == nest or caller.startswith(nest + ".")
        same_package = file["package"] == source_file["package"]
        for t in enclosing:
            match = index.core.JAVA_TYPE_RE.match(source_file["code"],t["start"])
            if not match or (re.search(r"\bprivate\b",match.group(0)) and not same_nest): return None
            if not same_nest and not same_package and not re.search(r"\bpublic\b",match.group(0)): return None
        modifiers = declaration["modifiers"]
        if "private" in modifiers and not same_nest: return None
        if "public" not in modifiers and not same_nest and not same_package: return None
        ref = platform_time_reference(declaration["typeReference"],source_file,owner)
        if (ref["resolution"] not in {"resolved","primitive"} or not ref.get("resolvedType")
                or type_head_shadowed(ref["rawType"],owner,reference_file=source_file)
                or ref["resolvedType"] in index.types):
            return None
        member = _selected_static_field_declaration(index, declaration, inheritance)
        if member is None: return None
        start, end = member["sourceRange"]["charStart"], member["sourceRange"]["charEnd"]
        identity = "semantic:" + hashlib.sha256(adapters.canonical([declaration["path"], source_file["sourceHash"], "constant", start, end])).hexdigest()
        if not explicit:
            for imported_owner in owners:
                if imported_owner != owner:
                    if inherited_name_possible(imported_owner,name,True): return None
                    continue
                # A selected direct field is the declaration being imported,
                # not an inherited-name absence claim. Keep the complete bounded
                # inventory and reject genuine inherited/unknown alternatives.
                check,_ = inheritance.query(owner,name,True)
                selected = [s for s in check["sourceScopes"] if s["qualifiedName"] == owner]
                if (declaration["name"] != name or scope["path"] != declaration["path"]
                        or check["status"] != "present" or not check["transitiveInventoryComplete"] or check["reasons"]
                        or len(selected) != 1 or selected[0]["sourceEvidenceId"] != symbol(scope["id"])
                        or selected[0]["path"] != declaration["path"] or selected[0]["sourceDigest"] != source_file["sourceHash"]
                        or selected[0]["memberInventory"].get("fields") != "complete"
                        or name not in selected[0]["memberInventory"].get("fieldNames", [])
                        or any(s["qualifiedName"] != owner and name in s["memberInventory"].get("fieldNames", []) for s in check["sourceScopes"])
                        or legacy_inherited_name_possible(owner,name,True)):
                    return None
        name_type = ref["resolvedType"]
        if name_type.startswith("java.lang.") and name_type[10:] in {"boolean","byte","char","short","int","long","float","double"}: name_type = name_type[10:]
        owner_ranges = _source_definition_ranges(index, scope)
        if not all(key in owner_ranges for key in ("sourceRange", "declarationRange", "bodyRange")):
            return None
        declaring_owner = {"id": symbol(scope["id"]), "qualifiedName": owner, "type": scope["kind"].title(),
            "path": declaration["path"], "sourceDigest": source_file["sourceHash"],
            "declarationHeaderRange": {"charStart": scope["start"], "charEnd": scope["body_start"] + 1},
            **owner_ranges}
        # Keep the relevant source-index observations for later comparison
        # with actual delivered namespaces. Unknown unused wildcards do not
        # override an exact single import; a later wildcard selection must
        # have complete source-bound observations for every active namespace.
        namespace_names = owners | {value[:-2] for value in file["staticImports"] if value.endswith(".*")}
        if len(namespace_names) > policy_java_platform.MAX_CHECKS: return None
        namespace_checks, namespace_sources = [], {owner}
        for namespace in sorted(namespace_names):
            observed, _ = inheritance.query(namespace, name, True)
            namespace_checks.append(observed)
            namespace_sources.update(item["qualifiedName"] for item in observed["sourceScopes"])
        caller_scope = index.types[caller]
        caller_declaration = {"id":symbol(caller_scope["id"]),"qualifiedName":caller,"type":caller_scope["kind"].title(),
            "path":path,"sourceDigest":file["sourceHash"],
            "declarationHeaderRange":{"charStart":caller_scope["start"],"charEnd":caller_scope["body_start"]+1},
            **_source_definition_ranges(index,caller_scope)}
        caller_namespace = {"schemaVersion":1,"selection":"static_import","name":name,"selectedOwner":owner,
            "callerTypeId":symbol(index.types[caller]["id"]),"callerDeclaration":caller_declaration,"path":path,"sourceDigest":file["sourceHash"],
            "namespaceOwners":[{"id":symbol(index.types[item]["id"]),"qualifiedName":item,
                "path":index.types[item]["path"],"sourceDigest":index.files[index.types[item]["path"]]["sourceHash"]}
                for item in sorted(namespace_sources)], "namespaceChecks":namespace_checks}
        if len(adapters.canonical(caller_namespace)) > policy_java_platform.MAX_CATALOG_BYTES: return None
        return {"name":name_type,"resolution":"resolved_static_type","basis":"selected_static_final_field_declaration",
            "sourceEvidenceIds":[symbol(scope["id"]),identity],"evidenceKinds":["symbol","semantic_fragment"],
            "_platformOrigin": type_origin(owner, declaration["path"], "selected_field", identity, "/declaredType", useOwnerId=symbol(index.types[caller]["id"])),
            "fieldBinding":{"resolution":"selected_static_final_field","declaringType":owner,"name":name,
                "path":declaration["path"],"sourceDigest":source_file["sourceHash"],"declarationFragmentId":identity,
                "declarationProofVersion":1,"declaredType":declaration["typeReference"]["rawType"],
                "resolvedType":name_type,"declaringOwner":declaring_owner,"memberDeclaration":member,
                "callerNamespace":caller_namespace,
                "sourceRange":{"charStart":start,"charEnd":end},
                "initializerEvidence":{"fragmentId":identity,"sourceRange":member["initializerRange"],
                    "value":"UNKNOWN","execution":"not_observed"},"valueSubstitution":False,"runtimeValue":"UNKNOWN"}}

    def functional_type_arguments(ref, owner, method=None, reference_file=None):
        if ref.get("resolvedType") not in {"java.util.concurrent.CompletableFuture", "java.util.function.Function", "java.util.function.BiConsumer"}:
            return {}
        arguments = ref.get("genericArguments", [])
        known = (ref.get("genericArgumentsStatus") == "captured" and all(
            a.get("resolution") == "resolved" and not a.get("wildcard") and not a.get("genericArguments")
            and not type_head_shadowed(a["rawType"], owner, method, reference_file) for a in arguments))
        return {"typeArguments": [a["resolvedType"] for a in arguments] if known else [],
                "typeArgumentsStatus": "resolved" if known and arguments else "raw" if "<" not in ref["rawType"] else "UNKNOWN"}

    @lru_cache(maxsize=20_000)
    def record_accessible(candidate, reference_path, owner, kinds=("record",)):
        """Source access modifiers at the actual use site (JLS 6.6.1).

        Name resolution in a component/factory declaration does not establish
        access for its caller. This check uses the bound declaration identity,
        so it does not re-resolve an already typed result through caller imports.
        Cross-package protected access remains unsupported conservatively.
        """
        record = index.types.get(candidate)
        if not record or record["kind"] not in kinds or owner not in index.types:
            return False
        record_file = index.files[record["path"]]
        reference_file = index.files[reference_path]
        enclosing = [t for t in record_file["scopes"] if t["start"] <= record["start"] <= t["body_end"]]
        if not enclosing:
            return False
        outer = min(enclosing, key=lambda t: t["start"])
        same_nest = owner == outer["qualified_name"] or owner.startswith(outer["qualified_name"] + ".")
        for scope in enclosing:
            match = index.core.JAVA_TYPE_RE.match(record_file["code"], scope["start"])
            if not match:
                return False
            modifiers = match.group(0)
            if re.search(r"\bprivate\b", modifiers) and not same_nest:
                return False
            if not re.search(r"\bpublic\b", modifiers) and not same_nest and reference_file["package"] != record_file["package"]:
                return False
        return True

    def record_reference(ref, reference_file, owner, offset, method=None):
        """Selected, accessible, non-generic record type; not a call target."""
        candidate = ref.get("resolvedType")
        record = index.types.get(candidate)
        if (not record or record["kind"] != "record" or ref.get("resolution") != "resolved"
                or ref.get("arrayDimensions") or ref.get("genericArguments") or "<" in ref["rawType"]
                or record["header"].lstrip().startswith("<") or candidate.startswith("java.")):
            return None
        raw = index.core._clean_java_type(ref["rawType"])
        head, _, tail = raw.partition(".")
        variables = {**index._type_variables(owner), **({p["name"]: p["rawBounds"] for p in method["type_parameters"]} if method else {})}
        if head in variables:
            return None
        current = owner
        while current:
            visible = current + "." + head if current + "." + head in index.types else current if current.rsplit(".", 1)[-1] == head else None
            if visible:
                if candidate != visible + ("." + tail if tail else ""):
                    return None
                break
            if current in index.types and inherited_name_possible(current, head):
                return None
            current = current.rsplit(".", 1)[0] if "." in current else ""
        same_package_head = (reference_file["package"] + "." + head).strip(".")
        if same_package_head in index.types and candidate != same_package_head + ("." + tail if tail else ""):
            return None
        record_file = index.files[record["path"]]
        # The index deliberately does not model block-local type visibility.
        if any(m.get("body_start", 10**20) <= record["start"] < m.get("body_end", -1) for m in record_file["methods"]):
            return None
        # A local class of the same name may obscure an import even though the
        # declaration index conservatively retains the import's spelling.
        for local in reference_file["scopes"]:
            if local["name"] != head:
                continue
            if any(m.get("body_start", 10**20) <= local["start"] <= offset < m.get("body_end", -1) for m in reference_file["methods"]):
                return None
        if not record_accessible(candidate, reference_file["path"], owner):
            return None
        return {"name": candidate, "resolution": "resolved_static_type", "basis": "selected_record_declaration",
                "sourceEvidenceIds": [symbol(record["id"])], "recordDeclarationId": symbol(record["id"]),
                "_platformOrigin": type_origin(owner, reference_file["path"], "syntax_type", sourcePosition=offset)}

    @inheritance.cached
    def record_type(raw, offset, parameter=None):
        containing = [m for m in methods if m["match_start"] <= offset <= m.get("body_end", m["match"].end())]
        method = min(containing, key=lambda m: m.get("body_end", m["match"].end()) - m["match_start"]) if containing else None
        owner = method["owner"] if method else lexical_owner(offset)
        if parameter is not None:
            refs = [p for p in method["parameter_references"] if p.get("name") == parameter] if method else []
            if len(refs) != 1:
                return None
            ref = refs[0]
        else:
            ref = index.type_reference(file, raw, owner, context="record_receiver")
        typed = record_reference(ref, file, owner, offset, method)
        if typed and method:
            typed = {**typed, "sourceEvidenceIds": typed["sourceEvidenceIds"] + [symbol(method["id"])]}
            if parameter is not None:
                typed["_platformOrigin"] = type_origin(owner, path, "parameter", symbol(method["id"]),
                    "/parameterTypeReferences/" + str(method["parameter_references"].index(refs[0])), sourcePosition=offset)
        return typed

    @lru_cache(maxsize=20_000)
    def component_header(owner):
        return _record_component_header(index, index.types[owner])

    @inheritance.cached
    def record_components(owner):
        record = index.types.get(owner)
        if not record or record["kind"] != "record" or not record["header"].lstrip().startswith("("):
            return None
        record_file = index.files[record["path"]]
        header = component_header(owner)
        if header["reasons"]: return None
        components = {}
        for component in header["components"]:
            ref = platform_time_reference(index.type_reference(record_file, component["rawType"], owner, context="record_component"), record_file, owner)
            components[component["name"]] = {"reference": ref, "start": component["start"], "end": component["end"]}
        return components

    @lru_cache(maxsize=20_000)
    def component_explicit_imports(reference_path):
        # JavaIndex keeps the historical import map for call signatures. This
        # projection must not turn its last-import entry into definite type
        # evidence when the selected source contains conflicting declarations.
        imports = {}
        ident = r"[A-Za-z_$][A-Za-z0-9_$]*"
        pattern = r"\bimport\s+(?!static\b)(" + ident + r"(?:\s*\.\s*" + ident + r")+)\s*;"
        for match in re.finditer(pattern, index.files[reference_path]["code"]):
            name = re.sub(r"\s*\.\s*", ".", match[1])
            imports.setdefault(name.rsplit(".", 1)[-1], set()).add(name)
        return imports

    def component_import_ambiguity(ref, reference_path):
        if ref["resolution"] != "type_variable":
            normalized = re.sub(r"\s*\.\s*", ".", ref["rawType"])
            head = index.core._clean_java_type(normalized).split(".", 1)[0]
            if len(component_explicit_imports(reference_path).get(head, ())) > 1:
                return "conflicting_explicit_imports"
        for argument in ref.get("genericArguments", []):
            reason = component_import_ambiguity(argument, reference_path)
            if reason: return reason
            if argument.get("resolution") == "ambiguous":
                return "record_component_type_argument_ambiguous"
        return None

    def record_component_declarations(owner):
        record = index.types[owner]; source_file = index.files[record["path"]]
        header = component_header(owner); definitions = []
        projection = policy_java_platform.Projection(inheritance.capture, "record", symbol(record["id"]))
        reasons = list(header["reasons"])
        for component in header["components"][:64]:
            raw = component["rawType"]
            name = component["name"]
            bounded = all(value is None or len(value) <= 1024 for value in (raw, name))
            if not bounded:
                reasons.append("record_component_projection_text_budget_exceeded")
                raw = None; name = None
            valid = not header["reasons"] and raw is not None and bounded
            ref = None
            def component_type():
                nonlocal ref
                ref = platform_time_reference(index.type_reference(source_file, raw, owner, context="record_component"), source_file, owner) if valid else None
                ambiguity = component_import_ambiguity(ref, source_file["path"]) if ref else None
                if ambiguity:
                    ref = {**ref, "resolvedType": None, "resolution": "ambiguous", "reason": ambiguity}
                if ref and ref["resolution"] in {"resolved", "primitive"} and not type_head_shadowed(raw, owner, reference_file=source_file):
                    return {"type": ref["resolvedType"], "typeResolution": ref["resolution"],
                            "_platformOrigin": type_origin(owner, source_file["path"], "record_component", symbol(record["id"]),
                                "/recordComponents/" + str(len(definitions)))}
                return None
            proof = projection.call(component_type)
            resolved = proof is not None
            definitions.append({"index": len(definitions), "name": name,
                "declaredType": raw, "type": ref["resolvedType"] if resolved else None,
                "typeResolution": ref["resolution"] if resolved else "UNKNOWN",
                "typeReason": ("record_component_projection_text_budget_exceeded" if not bounded else ref["reason"] if resolved else "lexical_type_shadow" if ref and ref["resolution"] in {"resolved", "primitive"} else ref["reason"] if ref else "record_component_header_unsupported"),
                "declarationStatus": "declared" if valid else "unsupported",
                "sourceRange": {"charStart": component["start"], "charEnd": component["end"]},
                **({"platformInheritance": proof["platformInheritance"]} if proof and "platformInheritance" in proof else {})})
        detected = header["detected"]
        omitted = max(0, detected - len(definitions)) if detected is not None else None
        if omitted: reasons.append("record_component_projection_budget_exceeded")
        output = {"recordComponents": definitions, "recordComponentCoverage": {
            "scope": "record_header_component_declarations", "detectedComponents": detected,
            "recordedComponents": len(definitions), "omittedComponents": omitted,
            "unsupportedComponents": sum(c["declarationStatus"] != "declared" for c in definitions),
            "inventoryComplete": detected is not None and not omitted,
            "declarationsComplete": detected is not None and not reasons,
            "status": "declared" if detected is not None and not reasons else "PARTIAL",
            "reasons": sorted(set(reasons)), "runtimeFieldValues": "UNKNOWN"}}
        if "sourceRange" in header: output["recordHeaderRange"] = header["sourceRange"]
        projection.finish(output)
        return output

    def record_field(raw, offset):
        """Direct instance component field type, never an implicit runtime value."""
        name = raw.removeprefix("this.")
        if "." in name:
            return None
        owner = lexical_owner(offset)
        record = index.types.get(owner)
        if not record or record["kind"] != "record" or record["header"].lstrip().startswith("<"):
            return None
        containing = [m for m in methods if m.get("body_start", 10**20) <= offset <= m.get("body_end", -1)]
        method = min(containing, key=lambda m: m["body_end"] - m["body_start"]) if containing else None
        # Constructors/initializers, static methods and nested types require
        # distinct receiver rules; no component binding is claimed there.
        if not method or method["owner"] != owner or method["static"]:
            return None
        components = record_components(owner)
        if not components or name not in components:
            return None
        component = components[name]; ref = component["reference"]
        if (ref["resolution"] not in {"resolved", "primitive"} or not ref.get("resolvedType")
                or type_head_shadowed(ref["rawType"], owner, method)):
            return None
        result = record_reference(ref, file, owner, offset, method)
        if result is None:
            if ref["resolvedType"] in index.types:
                return None
            name_type = ref["resolvedType"]
            if name_type.startswith("java.lang.") and name_type[10:] in {"boolean", "byte", "char", "short", "int", "long", "float", "double"}:
                name_type = name_type[10:]
            result = {"name": name_type, "resolution": "resolved_static_type", "sourceEvidenceIds": []}
        return {**result, "basis": "declared_record_component_instance_field_type",
            "sourceEvidenceIds": sorted(set(result["sourceEvidenceIds"] + [symbol(record["id"]), symbol(method["id"])])),
            "_platformOrigin": type_origin(owner, path, "record_component", symbol(record["id"]),
                "/recordComponents/" + str(list(components).index(name))),
            "fieldBinding": {"resolution": "declared_record_component_field_type", "recordType": owner, "name": name,
                "path": path, "sourceDigest": file["sourceHash"],
                "sourceRange": {"charStart": component["start"], "charEnd": component["end"]},
                "sourceEvidenceIds": [symbol(record["id"])], "callResolution": "java_index_unchanged",
                "runtimeValue": "UNKNOWN", "specification": "https://docs.oracle.com/javase/specs/jls/se21/html/jls-8.html#jls-8.10.3"}}

    @inheritance.cached
    def record_construction(raw, argument_count, offset):
        typed = record_type(raw,offset)
        if not typed:
            return None
        owner=typed["name"]; record=index.types[owner]; source_file=index.files[record["path"]]
        components=record_components(owner)
        if components is None:
            return None
        if len(components)>64:
            return {"resolution":"UNKNOWN","reason":"record_parameter_binding_budget_exceeded","recordDeclarationId":symbol(record["id"])}
        code=source_file["code"]
        # A direct name followed by '(' or '{' conservatively includes every
        # normal/compact constructor. Unusual direct-member syntax can make
        # this a candidate, never false proof of an implicit constructor.
        pattern=re.compile(r"\b"+re.escape(record["name"])+r"\s*(?P<delimiter>\(|\{)")
        matches=index.core._java_direct_member_matches(code,pattern,record["body_start"],record["body_end"])
        candidates=[]
        for match in matches[:64]:
            end=match.end()-1
            if match["delimiter"]=="(": end=index.core._matching_java_parenthesis(code,end,record["body_end"])
            cursor=end+1 if match["delimiter"]=="(" else end
            while cursor<record["body_end"] and code[cursor].isspace(): cursor+=1
            if cursor<record["body_end"] and code[cursor]=="{": end=index.core._matching_java_brace(code,cursor)
            candidates.append({"kind":"compact_or_direct_member_candidate" if match["delimiter"]=="{" else "normal_or_direct_member_candidate",
                "sourceRange":{"charStart":match.start(),"charEnd":end+1},"effects":"UNKNOWN"})
        parameters=[]
        for name,component in components.items():
            ref=component["reference"]
            resolved=ref["resolution"] in {"resolved","primitive"} and not type_head_shadowed(ref["rawType"],owner,reference_file=source_file)
            parameters.append({"index":len(parameters),"name":name,"declaredType":ref["rawType"],
                "type":ref["resolvedType"] if resolved else None,
                "typeResolution":ref["resolution"] if resolved else "UNKNOWN","sourceRange":{"charStart":component["start"],"charEnd":component["end"]}})
        resolution="implicit_canonical_parameter_order" if not matches and argument_count==len(parameters) else "UNKNOWN"
        reasons=[]
        if matches: reasons.append("explicit_or_unclassified_record_constructor_source")
        if len(matches)>64: reasons.append("record_constructor_candidate_budget_exceeded")
        if argument_count!=len(parameters): reasons.append("canonical_parameter_arity_mismatch")
        identity="source-record-constructor:"+hashlib.sha256(adapters.canonical([record["path"],source_file["sourceHash"],record["start"]])).hexdigest()
        return {"resolution":resolution,"limitations":reasons,"declaration":{"id":identity,
            "recordDeclarationId":symbol(record["id"]),"recordType":owner,"path":record["path"],"sourceDigest":source_file["sourceHash"],
            "sourceRange":{"charStart":record["start"],"charEnd":record["body_end"]+1},"parameters":parameters,
            "constructorKind":"implicit_canonical" if not matches else "explicit_or_unclassified",
            "constructorCandidates":candidates,"candidateCount":len(matches),
            "parameterToField":"implicit_assignment_on_success" if not matches else "UNKNOWN",
            "sourceEvidenceIds":[symbol(record["id"])],"runtimeFieldValues":"UNKNOWN",
            "specification":"https://docs.oracle.com/javase/specs/jls/se21/html/jls-8.html#jls-8.10.4"}}

    def record_accessor(receiver, name, argument_count, offset):
        if not receiver or argument_count != 0 or receiver.get("recordDeclarationId") is None:
            return None
        owner = receiver["name"]
        record = index.types.get(owner)
        if not record or symbol(record["id"]) != receiver["recordDeclarationId"]:
            return None
        if not isinstance(offset, int) or not 0 <= offset < len(file["code"]):
            return None
        caller_owner = lexical_owner(offset)
        if not record_accessible(owner, path, caller_owner):
            return None
        # Explicit zero-argument declarations always win. Their exact source
        # call return type is handled by call_result, never synthesized here.
        if any(not method["parameter_types"] for method in index.methods_by_key.get((owner, name), [])):
            return None
        components = record_components(owner)
        if not components or name not in components:
            return None
        component = components[name]; ref = component["reference"]
        record_file = index.files[record["path"]]
        if ref["resolution"] not in {"resolved", "primitive"} or not ref.get("resolvedType"):
            return None
        result = record_reference(ref, record_file, owner, component["start"])
        if result is not None and not record_accessible(result["name"], path, caller_owner):
            return None
        if result is None:
            if type_head_shadowed(ref["rawType"], owner, reference_file=record_file):
                return None
            result_name = ref["resolvedType"]
            if result_name in {"void", "java.lang.void"}:
                return None
            if result_name in index.types:
                return None
            if result_name.startswith("java.lang.") and result_name[10:] in {"boolean","byte","char","short","int","long","float","double"}:
                result_name = result_name[10:]
            result = {"name": result_name, "resolution": "resolved_static_type", "sourceEvidenceIds": []}
        result = {**result, "basis": "implicit_record_accessor_component_type",
            "_platformOrigin": type_origin(owner, record["path"], "record_component", symbol(record["id"]),
                "/recordComponents/" + str(list(components).index(name))),
            "sourceEvidenceIds": sorted(set(result["sourceEvidenceIds"] + receiver["sourceEvidenceIds"] + [symbol(record["id"])]))}
        return {"resultType": result, "binding": {"resolution": "declared_record_accessor_return_type",
            "signature": owner + "#" + name + "():" + result["name"], "kind": "implicit_component_accessor",
            "component": {"name": name, "recordType": owner, "path": record["path"], "sourceDigest": record_file["sourceHash"],
                "span": dict(zip(("lineStart","lineEnd"), index.core._line_span(record_file["code"], component["start"], component["end"]))),
                "sourceRange": {"charStart": component["start"], "charEnd": component["end"]}},
            "sourceEvidenceIds": [symbol(record["id"])], "callResolution": "java_index_unchanged",
            "specification": "https://docs.oracle.com/javase/specs/jls/se21/html/jls-8.html#jls-8.10.3",
            "runtimeValue": "UNKNOWN", "executionSuccess": "UNKNOWN"}}

    def lexical_callable_owner(offset):
        # Independent index ownership for a bounded local type annotation.
        # The consumer also checks token scopes; local/anonymous types are not
        # accepted merely because an enclosing method range contains them.
        containing = [m for m in methods if m.get("body_start", offset + 1) <= offset < m.get("body_end", -1)]
        if not containing:
            return None
        method = min(containing, key=lambda m: m["body_end"] - m["body_start"])
        owner = index.types.get(lexical_owner(offset))
        if (owner is None or method["owner"] != owner["qualified_name"]
                or sum(m["body_start"] == method["body_start"] for m in containing) != 1):
            return None
        type_ranges, callable_ranges = _source_definition_ranges(index, owner), _source_definition_ranges(index, method)
        if "bodyRange" not in type_ranges or "bodyRange" not in callable_ranges:
            return None
        return {"kind": "indexed_named_type_callable", "typeSymbolId": symbol(owner["id"]),
            "callableSymbolId": symbol(method["id"]),
            "typeDeclarationRange": type_ranges["declarationRange"], "typeBodyRange": type_ranges["bodyRange"],
            "callableDeclarationRange": callable_ranges["declarationRange"], "callableBodyRange": callable_ranges["bodyRange"]}

    source_definitions = {}
    for row in facts["records"]:
        if row.get("kind") in {"symbol", "callsite"}:
            identity = row.get("id")
            source_definitions[identity] = None if identity in source_definitions else row

    def source_definition(identity, selected_path=None):
        if selected_path is not None and selected_path != path:
            return None
        return source_definitions.get(identity)

    def type_origin(owner, reference_path, kind, record_id=None, selector=None, **extra):
        scope = index.types.get(owner)
        if scope is None:
            return None
        return {"kind": kind, "ownerId": symbol(scope["id"]), "path": reference_path,
                "sourceDigest": index.files[reference_path]["sourceHash"],
                **({"recordId": record_id, "selector": selector} if record_id else {}), **extra}

    def callback_signature(raw, name, offset, value_context=True, expected_input_type=None, explicit_context=False):
        if not isinstance(raw, str) or not isinstance(name, str) or type(offset) is not int:
            return None
        caller = lexical_owner(offset)
        calling = [m for m in methods if m.get("body_start", offset+1) <= offset < m.get("body_end", -1)]
        if not caller or not calling: return None
        method = min(calling, key=lambda m: m["body_end"] - m["body_start"])
        variables = {**index._type_variables(caller), **{p["name"]:p["rawBounds"] for p in method["type_parameters"]}}
        head = raw.split(".", 1)[0]
        if head in variables or value_context and value_head_shadowed(head, offset): return None
        ref = index.type_reference(file, raw, caller, context="callback_input_type", type_variables=variables)
        target = ref.get("resolvedType"); selected = index.types.get(target)
        if expected_input_type is not None and target!=expected_input_type:return None
        if (ref.get("resolution") != "resolved" or ref.get("genericArguments") or ref.get("arrayDimensions")
                or "<" in raw or not selected or selected["kind"] not in {"class", "record"}
                or target.startswith(("java.", "org.springframework.http.")) or index._type_variables(target)
                or not record_accessible(target, path, caller, ("class", "record"))): return None
        target_file = index.files[selected["path"]]
        if any(m.get("body_start", 10**20) <= selected["start"] < m.get("body_end", -1) for m in target_file["methods"]): return None
        current = caller
        while current:
            visible = current + "." + head if current + "." + head in index.types else current if current.rsplit(".",1)[-1] == head else None
            if visible:
                if target != visible + (raw[len(head):] if "." in raw else ""): return None
                break
            if current in index.types and inherited_name_possible(current, head): return None
            current = current.rsplit(".",1)[0] if "." in current else ""
        parents = index.core._java_hierarchy(selected["header"], selected["kind"])
        if any(parents): return None
        inventory = _callback_inventory(index, selected, inheritance.source_inventory(target), symbol)
        if inventory["status"] != "complete": return None
        found = [m for m in target_file["methods"] if m["owner"] == target and m["name"] == name]
        if len(found) == 0 and selected["kind"] == "record":
            receiver = record_type(raw, offset)
            accessor = record_accessor(receiver, name, 0, offset) if receiver else None
            if not accessor: return None
            result = accessor["resultType"]; component = accessor["binding"]["component"]
            components = record_components(target)
            evidence = {"recordId": symbol(selected["id"]), "selector": "/recordComponents/" + str(list(components).index(name)),
                "path": selected["path"], "sourceDigest": target_file["sourceHash"], "sourceRange": component["sourceRange"],
                "returnTypeSelector": "/recordComponents/" + str(list(components).index(name)), "evidenceKind": "existing_record_component_accessor"}
        elif len(found) == 1:
            getter = found[0]; declaration = _callback_declaration(index, getter, symbol)
            access = declaration["access"]
            package = target_file["package"]
            local = target[len(package)+1:] if package else target
            nest = ((package + ".") if package else "") + local.split(".",1)[0]
            same_nest = caller == nest or caller.startswith(nest + ".")
            if (getter["parameter_types"] or declaration["invocationKind"] != "instance" or declaration["varargs"]
                    or declaration["generic"] or not declaration["hasBody"] or declaration["declarationValidity"] != "bounded_header_only"
                    or access == "UNKNOWN" or access == "private" and not same_nest
                    or access in {"protected", "package"} and file["package"] != package): return None
            returned = getter["return_reference"]
            if (returned.get("resolution") not in {"resolved", "primitive"} or returned.get("genericArguments")
                    or returned.get("arrayDimensions") or type_head_shadowed(returned["rawType"], target, getter, target_file)): return None
            result_name = returned["resolvedType"]
            if result_name in index.types: return None
            if result_name.startswith("java.lang.") and result_name[10:] in {"int", "long", "double"}: result_name=result_name[10:]
            result = {"name":result_name}
            evidence = {"recordId":symbol(getter["id"]), "selector":"/callbackDeclaration", "path":selected["path"],
                "sourceDigest":target_file["sourceHash"], "sourceRange":_source_definition_ranges(index,getter)["sourceRange"],
                "returnTypeSelector":"/returnTypeReference", "evidenceKind":"selected_method_signature"}
        else: return None
        enclosing_ids=[]
        for start in (selected, index.types[caller]):
            scope=start;seen=set()
            while scope:
                if scope["id"] in seen or len(seen)>=16:return None
                seen.add(scope["id"]);enclosing_ids.append(symbol(scope["id"]))
                parent_id=_type_declaration_eligibility(index,scope,symbol).get("enclosingTypeId")
                scope=next((t for t in index.files[scope["path"]]["scopes"] if symbol(t["id"])==parent_id),None) if parent_id else None
        ids = sorted(set(enclosing_ids + inventory["declarationIds"]))
        if explicit_context:
            scope=index.types[caller];seen=set()
            while scope:
                if scope["id"] in seen or len(seen)>=16:return None
                seen.add(scope["id"])
                if any(index.core._java_hierarchy(scope["header"],scope["kind"])):return None
                namespace=_callback_type_namespace(index,scope,inheritance.source_inventory(scope["qualified_name"]),symbol)
                if namespace["status"]!="complete":return None
                ids=sorted(set(ids+[entry["recordId"] for entry in namespace["declarations"]]))
                parent_id=_type_declaration_eligibility(index,scope,symbol).get("enclosingTypeId")
                scope=next((t for t in index.files[scope["path"]]["scopes"] if symbol(t["id"])==parent_id),None) if parent_id else None
        if len(ids) > 62: return None
        return {"inputType":target, "returnType":result["name"], "declarationEvidence":evidence, "sourceEvidenceIds":ids}

    @inheritance.cached
    def resolve(raw, offset, parameter=None):
        containing = [m for m in methods if m["match_start"] <= offset <= m.get("body_end", m["match"].end())]
        method = min(containing, key=lambda m: m.get("body_end", m["match"].end()) - m["match_start"]) if containing else None
        enclosing = [t for t in types if t["start"] <= offset <= t["body_end"]]
        owner = method["owner"] if method else min(enclosing, key=lambda t: t["body_end"] - t["start"])["qualified_name"] if enclosing else ""
        variables = {p["name"]: p["rawBounds"] for p in method["type_parameters"]} if method else {}
        if parameter is not None:
            refs = [p for p in method["parameter_references"] if p.get("name") == parameter] if method else []
            if len(refs) != 1:
                return None
            ref = refs[0]
            raw = ref["rawType"]
        else:
            ref = index.type_reference(file, raw, owner, context="policy_expression_type", type_variables=variables)
        ref = platform_time_reference(ref, file, owner, method)
        if type_head_shadowed(raw, owner, method):
            return None
        if ref["resolution"] not in {"resolved", "primitive"} or not ref.get("resolvedType"):
            return None
        name = ref["resolvedType"]
        # Selected source declarations can never impersonate platform APIs.
        if name in index.types and name.startswith(("java.", "org.springframework.http.")):
            return None
        if name.startswith("java.lang.") and name[10:] in {"boolean", "byte", "char", "short", "int", "long", "float", "double", "void"}:
            name = name[10:]
        evidence = [symbol(method["id"])] if method else [symbol(t["id"]) for t in enclosing]
        return {"name": name, "resolution": "resolved_static_type", "basis": ref["reason"],
                "sourceEvidenceIds": evidence, **functional_type_arguments(ref, owner, method),
                "_platformOrigin": type_origin(owner, path, "parameter" if parameter is not None else "syntax_type",
                    symbol(method["id"]) if parameter is not None else None,
                    "/parameterTypeReferences/" + str(method["parameter_references"].index(refs[0])) if parameter is not None else None,
                    sourcePosition=offset)}

    def call_result(offset):
        call = calls.get(offset)
        if not call or call["resolution"] != "exact" or call.get("target") not in index.methods:
            return None
        target = index.methods[call["target"]]
        caller_owner = lexical_owner(offset)
        if index.types.get(target["owner"], {}).get("kind") == "record":
            receiver_ref = index.type_reference(file, target["owner"], caller_owner, context="record_method_owner")
            if record_reference(receiver_ref, file, caller_owner, offset) is None:
                return None
        ref = platform_time_reference(target["return_reference"], index.files[target["path"]], target["owner"], target)
        record_result = record_reference(ref, index.files[target["path"]], target["owner"], target["match_start"], target)
        if index.types.get(ref.get("resolvedType"), {}).get("kind") == "record" and not record_accessible(ref["resolvedType"], path, caller_owner):
            return None
        if record_result is None and type_head_shadowed(ref["rawType"], target["owner"], target, index.files[target["path"]]):
            return None
        if ref["resolution"] not in {"resolved", "primitive"} or not ref.get("resolvedType"):
            return None
        name = ref["resolvedType"]
        if name in index.types and name.startswith(("java.", "org.springframework.http.")):
            return None
        if name.startswith("java.lang.") and name[10:] in {"boolean", "byte", "char", "short", "int", "long", "float", "double", "void"}:
            name = name[10:]
        return {**(record_result or {}), "name": name, "resolution": "resolved_static_type", "basis": "exact_source_call_return_declaration",
                "sourceEvidenceIds": [call["id"], symbol(target["id"])] + (record_result["sourceEvidenceIds"] if record_result else []),
                "evidenceKinds": ["callsite", "symbol"],
                "runtimeDispatch": "not_observed",
                "_platformOrigin": type_origin(target["owner"], target["path"], "source_return",
                    symbol(target["id"]), "/returnTypeReference", callsiteId=call["id"]),
                **functional_type_arguments(ref, target["owner"], target, index.files[target["path"]])}

    def record_call_result(receiver, name, argument_count, offset):
        # A typed enhanced-for receiver may recover a pre-existing exact
        # zero-argument source call, without trusting unrelated binder-based
        # resolution or adding a new exact target to the Java call index.
        if not receiver or not receiver.get("recordDeclarationId") or argument_count != 0:
            return None
        call = calls.get(offset)
        target = index.methods.get(call.get("target")) if call and call["resolution"] == "exact" else None
        record = index.types.get(receiver["name"])
        if (not target or not record or symbol(record["id"]) != receiver["recordDeclarationId"]
                or target["owner"] != receiver["name"] or target["name"] != name
                or target["parameter_types"] or target["static"]):
            return None
        return call_result(offset)

    def call_in_binder(offset):
        """Reuse a unique exact unqualified declaration in the lexical class.

        A local binder does not change an unqualified method's declaration.
        Receiver chains, inherited methods and overloaded names remain closed
        here; their argument/receiver scopes need separate evidence.
        """
        call = calls.get(offset)
        target = index.methods.get(call.get("target")) if call and call["resolution"] == "exact" else None
        if not target or target["owner"] != lexical_owner(offset) or target["varargs"]:
            return None
        cursor = offset - 1
        while cursor >= 0 and file["code"][cursor].isspace():
            cursor -= 1
        if cursor >= 0 and (file["code"][cursor] == "." or file["code"][cursor] == ":"):
            return None
        if len(index.methods_by_key.get((target["owner"], target["name"]), [])) != 1:
            return None
        return call_result(offset)

    return {"path": path, "sourceDigest": facts["sourceDigest"], "resolve": resolve,
            "callResult": call_result, "valueHeadShadowed": value_head_shadowed,
            "lexicalCallableOwner": lexical_callable_owner, "sourceDefinition": source_definition,
            "annotationTarget": annotation_target, "annotationContext": annotation_context,
            "recordType": record_type, "recordAccessor": record_accessor, "recordField": record_field,
            "staticImport": static_import, "recordCallResult": record_call_result,
            "callInBinder": call_in_binder, "importedSourceField": imported_source_field,
            "callbackSignature": callback_signature,
            "recordConstruction": record_construction,
            "recordComponentDeclarations": record_component_declarations, "indexHash": index.fingerprint,
            "sourceDefinition": source_definition, "lexicalCallableOwner": lexical_callable_owner,
            "sourceRelationInventory": lambda: [source_definitions[k] for k in sorted(source_definitions) if source_definitions[k] is not None],
            "platformProjection": lambda location="fragment": policy_java_platform.Projection(inheritance.capture, location)}


def enrich(facts, index):
    path = facts["path"]
    if index.files[path]["sourceHash"] != facts["sourceDigest"]:
        raise adapters.AdapterError("java_source_binding_mismatch")
    records = [r for r in facts["records"] if r["kind"] == "framework" or
               (r["kind"] == "symbol" and r.get("type") == "File")]

    def symbol_id(identity):
        return adapters.identifier("java-declaration", identity)

    def base(identity, kind, name, start, end=None):
        return {"id": symbol_id(identity) if kind == "symbol" else identity, "kind": kind, "name": name, "path": path,
            "language": "Java", "module": facts["module"], "modulePath": facts["modulePath"],
            "sourceDigest": facts["sourceDigest"], "ruleVersion": "java-resolution-1",
            "span": {"lineStart": start, "lineEnd": end or start},
            "basis": "declared", "status": "runtime_unknown"}

    component_context = None
    member_inventory = policy_java_platform.Inheritance(index, symbol_id,
        lambda scope: _record_component_header(index, scope))
    direct_fields = {}
    for (owner, _), declarations in index.field_declarations.items():
        if owner in index.types and index.types[owner]["path"] == path:
            direct_fields.setdefault(owner, []).extend(declarations)
    for item in index.types.values():
        if item["path"] != path:
            continue
        record = base(item["id"], "symbol", item["name"], item["line_start"])
        record.update(type=item["kind"].title(), qualifiedName=item["qualified_name"], originalSymbolId=item["id"])
        file = index.files[path]
        record["sourceRange"] = {"charStart": item["start"], "charEnd": item["body_end"] + 1}
        record["declarationHeaderRange"] = {"charStart": item["start"], "charEnd": item["body_start"] + 1}
        record.update(_type_import_bindings(index, path))
        record["sourcePackage"] = file["package"]
        # Bounded constructor headers establish only member-name boundaries.
        # Keep their source-bound omissions once on the type, never on every
        # namespace proof, and never emit a constructor symbol or CALLS edge.
        inventory = member_inventory.source_inventory(item["qualified_name"])
        constructors = inventory.get("_constructorRegions", [])
        # One source-bound names catalog per actual type definition lets later
        # consumers compare an absence check with its emitted owner, including
        # classes that need no explicit platform-parent catalog.
        record["directMemberInventory"] = {key: value for key, value in inventory.items() if not key.startswith("_")}
        record["callbackMemberInventory"] = _callback_inventory(index, item, inventory, symbol_id)
        record["callbackTypeNamespace"] = _callback_type_namespace(index, item, inventory, symbol_id)
        record["typeDeclarationEligibility"] = _type_declaration_eligibility(index, item, symbol_id)
        record["staticFieldDeclarations"] = _static_field_catalog(index,
            sorted(direct_fields.get(item["qualified_name"], []), key=lambda entry: entry["start"]), member_inventory)
        record["constructorInventory"] = {
            "scope": "bounded_direct_constructor_headers_only",
            "detectedBoundedConstructors": len(constructors),
            "modeledConstructorBodies": 0,
            "wholeJavaDeclarationDenominator": "UNKNOWN",
            "memberScanStatus": "complete" if inventory["fields"] == inventory["memberTypes"] == "complete" else "UNKNOWN",
            "memberScanReasons": inventory["reasons"],
            "bodySemantics": "constructor_body_semantics_not_modeled",
            "constructorCalls": "not_added",
            "sourceDigest": facts["sourceDigest"],
            "regions": constructors}
        record["sourceBodyShape"] = {"schemaVersion": 1, "scope": "masked_source_type_body_tokens",
            "shape": "empty" if not file["code"][item["body_start"]+1:item["body_end"]].strip() else "nonempty",
            "runtimeInitialization": "UNKNOWN"}
        record["declarationSpan"] = dict(zip(("lineStart", "lineEnd"), index.core._line_span(file["code"], item["start"], item["body_end"] + 1)))
        record["bodySpan"] = dict(zip(("lineStart", "lineEnd"), index.core._line_span(file["code"], item["body_start"], item["body_end"] + 1)))
        record.update(_source_definition_ranges(index, item))
        record["annotations"] = [index.type_reference(file, name, item["qualified_name"], context="annotation") for name in item["annotations"]]
        record["typeParameters"] = [{"name": name, "rawBounds": bound,
            "bounds": [index.type_reference(file, value.strip(), item["qualified_name"], context="type_parameter_bound")
                       for value in bound.split("&") if value.strip()]} for name, bound in index._type_parameters(item["header"]).items()]
        extends, implements = index.core._java_hierarchy(item["header"], item["kind"])
        record["extendsTypes"] = [index.type_reference(file, value, item["qualified_name"], context="extends") for value in extends]
        record["implementsTypes"] = [index.type_reference(file, value, item["qualified_name"], context="implements") for value in implements]
        if item["kind"] == "record":
            if component_context is None:
                component_context = semantic_type_context(facts, index)
            record.update(component_context["recordComponentDeclarations"](item["qualified_name"]))
        records.append(record)
    for item in index.files[path]["methods"]:
        record = base(item["id"], "symbol", item["name"], item["line_start"], item["line_end"])
        record.update(type="Method", qualifiedName=item["qualified_name"], originalSymbolId=item["id"], owner=item["owner"],
            parameterTypes=item["parameter_types"], returnType=item["return_type"],
            parameterTypeReferences=item["parameter_references"], returnTypeReference=item["return_reference"],
            typeParameters=item["type_parameters"], annotations=item["annotations"], throwsTypes=item["throws"],
            declarationSpan=item["declaration_span"], headerSpan=record["span"])
        if "body_span" in item:
            record["bodySpan"] = item["body_span"]
        record.update(_source_definition_ranges(index, item))
        source_modifiers = []
        record["callbackDeclaration"] = _callback_declaration(index, item, symbol_id, source_modifiers=source_modifiers)
        record["sourceMethodModifiers"] = source_modifiers
        records.append(record)
    for call in index.calls.get(path, []):
        record = base(call["id"], "callsite", call["name"], call["line_start"], call["line_end"])
        record.update({k: v for k, v in call.items() if k not in {"sourceHash", "line_start", "line_end"}})
        records.append(record)
        if call["resolution"] == "exact" and call.get("target") in index.methods:
            edge = base(adapters.identifier("exact-java-call", call["id"]), "assertion", "CALLS",
                        call["line_start"], call["line_end"])
            edge.update(subject=symbol_id(call["caller"]), predicate="CALLS", object=symbol_id(call["target"]),
                resolution="exact", basis="resolved_static", callsiteId=call["id"],
                runtimeDispatch="not_observed", limitations=["static_declaration_target_not_runtime_dispatch"])
            records.append(edge)
    facts["records"] = records
    facts["javaIndexHash"] = index.fingerprint
    return facts
