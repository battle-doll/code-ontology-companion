"""Conservative repository-scoped Java declaration and invocation accounting.

This is a bounded syntax resolver, not javac. Recognized invocations in
recognized methods have explicit outcomes. Ambiguous/unresolved sites never
become exact CALLS. Interface targets are declarations, not runtime dispatch.
No source bodies or literal values are emitted.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

IDENT = r"[A-Za-z_$][\w$]*"
TYPE = rf"{IDENT}(?:\s*\.\s*{IDENT})*(?:\s*<[^;{{}}=()]*>)?(?:\s*\[\s*\])*"
MEMBER = re.compile(
    rf"(?<![\w$.])(?P<mods>(?:(?:public|protected|private|static|final|volatile|transient)\s+)*)"
    rf"(?P<type>{TYPE})\s+(?P<name>{IDENT})\s*(?=[=;])"
)
LOCAL = re.compile(rf"(?<![\w$.])(?:final\s+)?(?P<type>{TYPE})\s+(?P<name>{IDENT})\s*(?=[=;:,])")
INVOKE = re.compile(rf"(?<![\w$])(?P<name>{IDENT})\s*\(")
PRIMITIVES = {"void", "boolean", "byte", "char", "short", "int", "long", "float", "double"}
# Only standard platform interfaces with a fixed member-name contract are used
# to exclude unrelated inherited overloads. They never supply exact targets.
PLATFORM_INTERFACES = {
    "java.lang.AutoCloseable": {"close"},
    "java.lang.Runnable": {"run"},
    "java.lang.Comparable": {"compareTo"},
    "java.lang.Cloneable": set(),
    "java.io.Closeable": {"close"},
    "java.io.Serializable": set(),
}
UNSUPPORTED = ["reflection", "runtime_dispatch", "generated_code", "constructor_and_initializer_bodies", "anonymous_class_bodies",
               "method_references", "full_java_grammar", "generic_type_inference", "multi_declarator_fields"]
MAX_RECEIVER_CHAIN_DEPTH = 12
MAX_TYPE_REFERENCE_DEPTH = 32


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _reverse_open(text: str, end: int) -> int:
    depth = 0
    for position in range(end - 1, -1, -1):
        if text[position] == ")":
            depth += 1
        elif text[position] == "(":
            depth -= 1
            if depth == 0:
                return position
    return -1


def _statement_extent(code, start, limit, pairs, cache, depth=0):
    """End-exclusive extent of one bounded statement, not Java validity.

    Input has comments/literals masked. Balanced groups are precomputed once
    per method. Recursion associates an else with its nearest unmatched if;
    no control-flow execution, reachability or runtime effects are inferred.
    Unsupported/malformed boundaries return None, never an estimated end.
    JLS 14.5, 14.9, 14.13, 14.14 and 14.20 describe these source boundaries.
    """
    def space(position):
        while position < limit and code[position].isspace(): position += 1
        return position

    def word(position):
        match = re.compile(IDENT).match(code, position, limit)
        return (match.group(), match.end()) if match else (None, position)

    def group(position, opening):
        position = space(position)
        closing = pairs.get(position)
        return closing + 1 if position < limit and code[position] == opening and closing is not None and closing < limit else None

    start = space(start)
    if start >= limit or depth >= MAX_TYPE_REFERENCE_DEPTH: return None
    if start in cache: return cache[start]
    result = None
    head, after_head = word(start)
    if code[start] == ";":
        result = start + 1
    elif code[start] == "{":
        result = group(start, "{")
    elif head in {"if", "for", "while", "switch", "synchronized"}:
        after_header = group(after_head, "(")
        if after_header is not None:
            body = space(after_header)
            if head in {"switch", "synchronized"}:
                result = group(body, "{")
            else:
                result = _statement_extent(code, body, limit, pairs, cache, depth + 1)
            if result is not None and head == "if":
                following = space(result)
                keyword, after_keyword = word(following)
                if keyword == "else":
                    result = _statement_extent(code, after_keyword, limit, pairs, cache, depth + 1)
    elif head == "do":
        after_body = _statement_extent(code, after_head, limit, pairs, cache, depth + 1)
        if after_body is not None:
            keyword, after_keyword = word(space(after_body))
            after_condition = group(after_keyword, "(") if keyword == "while" else None
            if after_condition is not None:
                semicolon = space(after_condition)
                if semicolon < limit and code[semicolon] == ";": result = semicolon + 1
    elif head == "try":
        body = space(after_head)
        resources = body < limit and code[body] == "("
        body = group(body, "(") if resources else body
        following = group(body, "{") if body is not None else None
        handlers = 0
        if following is not None:
            while True:
                keyword, after_keyword = word(space(following))
                if keyword != "catch": break
                after_parameter = group(after_keyword, "(")
                following = group(after_parameter, "{") if after_parameter is not None else None
                if following is None: break
                handlers += 1
            if following is not None:
                keyword, after_keyword = word(space(following))
                if keyword == "finally":
                    following = group(after_keyword, "{")
                    handlers += 1
                if resources or handlers: result = following
    elif head not in {"else", "catch", "finally", "case", "default", "class", "interface", "enum", "record"}:
        following = space(after_head)
        if head and following < limit and code[following] == ":" and code[following:following + 2] != "::":
            result = _statement_extent(code, following + 1, limit, pairs, cache, depth + 1)
        else:
            cursor = start
            while cursor < limit:
                char = code[cursor]
                if char == ";":
                    result = cursor + 1
                    break
                if char in "([{":
                    closing = pairs.get(cursor)
                    if closing is None or closing >= limit: break
                    cursor = closing + 1
                    continue
                if char in ")]}":
                    break
                keyword, after_keyword = word(cursor)
                if keyword:
                    if keyword in {"else", "catch", "finally", "case", "default"}: break
                    cursor = after_keyword
                    continue
                cursor += 1
    cache[start] = result
    return result


class JavaIndex:
    """Build once from selected file text; reuse for the legacy and pipeline paths."""

    def __init__(self, core: Any, sources: dict[str, str]):
        self.core = core
        self.files: dict[str, dict[str, Any]] = {}
        self.types: dict[str, dict[str, Any]] = {}
        self.methods: dict[str, dict[str, Any]] = {}
        self.methods_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.fields: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.field_declarations: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.calls: dict[str, list[dict[str, Any]]] = {}
        if len(sources) > core.MAX_SOURCE_FILES or sum(len(s.encode("utf-8")) for s in sources.values()) > core.MAX_TOTAL_SOURCE_BYTES:
            raise core.OntologyError("Java declaration index exceeds the selected-source budget.")
        for path, original in sorted(sources.items()):
            code = core._strip_java_comments_and_literals(original)
            package = re.search(r"\bpackage\s+([\w.]+)\s*;", code)
            imports = list(re.finditer(r"\bimport\s+(?P<static>static\s+)?(?P<q>[\w.]+(?:\.\*)?)\s*;", code))
            file = {"path": path, "original": original, "code": code,
                    "sourceHash": _hash(original), "package": package.group(1) if package else "",
                    "imports": {m.group("q").rsplit(".", 1)[-1]: m.group("q") for m in imports
                                if not m.group("static") and not m.group("q").endswith(".*")},
                    "wildcards": {m.group("q")[:-2] for m in imports
                                  if not m.group("static") and m.group("q").endswith(".*")},
                    "staticImports": [m.group("q") for m in imports if m.group("static")],
                    "scopes": [], "methods": [], "issues": []}
            if code.count("{") != code.count("}"):
                file["issues"].append("java_unbalanced_braces")
            for match in core.JAVA_TYPE_RE.finditer(code):
                header, opening = core._java_type_header(code, match.end())
                if opening < 0:
                    continue
                parent = core._java_scope_for(file["scopes"], match.start())
                q = ((parent["qualified_name"] if parent else file["package"]) + "." + match.group("name")).strip(".")
                scope = {"id": core._node_id("java", match.group("kind"), q), "qualified_name": q,
                         "name": match.group("name"), "kind": match.group("kind"), "path": path,
                         "start": match.start(), "body_start": opening,
                         "body_end": core._matching_java_brace(code, opening), "header": header,
                         "line_start": core._line_span(code, match.start(), match.end())[0],
                         "static_member": bool(parent and (parent["kind"] == "interface" or match.group("kind") in {"interface", "enum", "record"} or re.search(r"\bstatic\b", match.group(0)))),
                         "annotations": re.findall(r"@(" + IDENT + r"(?:\." + IDENT + r")*)", match.group("annotations"))}
                if q in self.types:
                    raise core.DuplicateDeclarationError("Duplicate Java type declaration in selected source scope.")
                file["scopes"].append(scope)
                self.types[q] = scope
            self.files[path] = file
        for file in self.files.values():
            self._declarations(file)
            if len(self.types) + len(self.methods) > core.MAX_GRAPH_NODES:
                raise core.OntologyError("Java declaration index exceeds the declaration safety budget.")
        callsite_count = 0
        for file in self.files.values():
            self.calls[file["path"]] = self._calls(file)
            callsite_count += len(self.calls[file["path"]])
            if callsite_count > core.MAX_GRAPH_EDGES:
                raise core.OntologyError("Java invocation index exceeds the global result safety budget.")
        self.source_fingerprint = _hash("\n".join(f"{p}:{f['sourceHash']}" for p, f in sorted(self.files.items())))
        self.analyzer_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.fingerprint = _hash(self.source_fingerprint + "\n" + self.analyzer_hash)

    def _type_parameters(self, raw: str) -> dict[str, str]:
        """Retain lexical type variables; bounds do not prove concrete types."""
        raw = raw.lstrip()
        if not raw.startswith("<"):
            return {}
        depth, end = 0, 0
        for end, char in enumerate(raw):
            depth += (char == "<") - (char == ">")
            if depth == 0:
                break
        if depth:
            return {}
        result = {}
        for part in self.core._split_java_parameters(raw[1:end]):
            match = re.match(rf"(?P<name>{IDENT})(?:\s+extends\s+(?P<bound>.+))?$", part.strip(), re.S)
            if match:
                result[match.group("name")] = match.group("bound") or ""
        return result

    def _type_variables(self, owner: str) -> dict[str, str]:
        result = {}
        current = owner
        while current:
            if current in self.types:
                result = {**self._type_parameters(self.types[current]["header"]), **result}
            current = current.rsplit(".", 1)[0] if "." in current else ""
        return result

    def _resolve_type(self, file: dict[str, Any], raw: str, owner: str = "",
                      type_variables: dict[str, str] | None = None) -> tuple[str, str, str, list[str]]:
        normalized = re.sub(r"\[\s*\]", "[]", raw)
        normalized = re.sub(r"\s*\.\s*", ".", normalized)
        clean = self.core._clean_java_type(normalized)
        if not clean or clean in {"var", "?"}:
            return "unknown", "unresolved", "inferred_or_missing_type", []
        if clean in PRIMITIVES:
            return "java.lang." + clean, "primitive", "legacy_primitive_signature", []
        if clean in {**self._type_variables(owner), **(type_variables or {})}:
            return clean, "type_variable", "lexical_type_parameter", []
        first, _, rest = clean.partition(".")
        explicit = set()
        if first in file["imports"]:
            explicit.add(file["imports"][first] + ("." + rest if rest else ""))
        # Static imports may name member types as well as methods/fields. Only
        # selected declarations prove the member-type interpretation.
        explicit.update(q + ("." + rest if rest else "") for q in file["staticImports"]
                        if not q.endswith(".*") and q.rsplit(".", 1)[-1] == first
                        and q + ("." + rest if rest else "") in self.types
                        and self.types[q]["static_member"])
        if explicit:
            if len(explicit) == 1:
                return next(iter(explicit)), "resolved", "explicit_import", sorted(explicit)
            return clean, "ambiguous", "conflicting_explicit_imports", sorted(explicit)
        if clean in self.types:
            return clean, "resolved", "selected_declaration", [clean]
        if "." in clean and first[:1].islower():
            return clean, "resolved", "qualified_lexical_reference", [clean]
        current = owner
        while current:
            candidate = current + "." + clean
            if candidate in self.types:
                return candidate, "resolved", "enclosing_member_type", [candidate]
            if current.rsplit(".", 1)[-1] == clean and current in self.types:
                return current, "resolved", "enclosing_type", [current]
            current = current.rsplit(".", 1)[0] if "." in current else ""
        same_package = (file["package"] + "." + clean).strip(".")
        if same_package in self.types:
            return same_package, "resolved", "same_package_declaration", [same_package]
        candidates = {prefix + "." + clean for prefix in file["wildcards"] if prefix + "." + clean in self.types}
        candidates.update(q[:-2] + "." + clean for q in file["staticImports"]
                          if q.endswith(".*") and q[:-2] + "." + clean in self.types
                          and self.types[q[:-2] + "." + first]["static_member"])
        if clean in self.core.JAVA_LANG_TYPES or "java.lang." + clean in PLATFORM_INTERFACES:
            candidates.add("java.lang." + clean)
        if clean in self.core.JAVA_UTIL_TYPES and "java.util" in file["wildcards"]:
            candidates.add("java.util." + clean)
        if len(candidates) == 1:
            return next(iter(candidates)), "resolved", "on_demand_import", sorted(candidates)
        if len(candidates) > 1:
            return "unknown", "ambiguous", "on_demand_import_ambiguous", sorted(candidates)
        # Keep historical signature identities while exposing that this is only
        # an unresolved lexical token. They cannot establish an exact target.
        identity = clean if file["wildcards"] else same_package
        return identity, "unresolved", "declaration_not_in_selected_scope", []

    def type_name(self, file: dict[str, Any], raw: str, owner: str = "") -> str:
        return self._resolve_type(file, raw, owner)[0]

    def type_reference(self, file: dict[str, Any], raw: str, owner: str = "", *,
                       context: str = "type", type_variables: dict[str, str] | None = None,
                       extra_dimensions: int = 0, _depth: int = 0) -> dict[str, Any]:
        """Source syntax and conservative resolution, independent of legacy IDs."""
        raw = raw.strip()
        identity, status, reason, candidates = self._resolve_type(file, raw, owner, type_variables)
        erased_syntax = self.core._strip_balanced_java_generics(raw)
        dimensions = len(re.findall(r"\[\s*\]", erased_syntax)) + (1 if "..." in erased_syntax else 0) + extra_dimensions
        arguments = []
        opening = raw.find("<")
        if opening >= 0 and _depth < MAX_TYPE_REFERENCE_DEPTH:
            depth, closing = 0, -1
            for cursor in range(opening, len(raw)):
                depth += (raw[cursor] == "<") - (raw[cursor] == ">")
                if depth == 0:
                    closing = cursor
                    break
            if closing >= 0:
                for piece in self.core._split_java_parameters(raw[opening + 1:closing]):
                    bound = re.match(r"^\?\s*(?:(extends|super)\s+(.+))?$", piece, re.S)
                    value = bound.group(2) if bound else piece
                    ref = self.type_reference(file, value or "?", owner, context="generic_argument", type_variables=type_variables, _depth=_depth + 1)
                    if bound:
                        ref["wildcard"] = bound.group(1) or "unbounded"
                        ref["rawType"] = piece
                    arguments.append(ref)
        return {"rawType": raw, "erasedType": identity + "[]" * dimensions,
                "resolvedType": identity + "[]" * dimensions if status in {"resolved", "primitive"} else None,
                "resolution": status, "reason": reason, "candidates": candidates,
                "context": context, "genericArguments": arguments,
                "genericArgumentsStatus": "depth_limit" if opening >= 0 and _depth >= MAX_TYPE_REFERENCE_DEPTH else "captured",
                "arrayDimensions": dimensions,
                "varargs": "..." in raw,
                "annotations": re.findall(r"@(" + IDENT + r"(?:\." + IDENT + r")*)", raw)}

    def _parameters(self, file: dict[str, Any], raw: str, owner: str, type_variables: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
        types, bindings = [], {}
        for parameter in self.core._split_java_parameters(raw):
            cleaned = re.sub(self.core.JAVA_ANNOTATION_PATTERN + r"\s*", "", parameter)
            cleaned = re.sub(r"\bfinal\s+", "", cleaned).strip()
            match = re.match(rf"(?P<type>.+?)\s+(?P<name>{IDENT})(?:\s*\[\s*\])*\s*$", cleaned, re.S)
            if not match:
                types.append("unknown")
                continue
            resolved, resolution, _, _ = self._resolve_type(file, match.group("type"), owner, type_variables)
            erased_syntax = self.core._strip_balanced_java_generics(cleaned)
            dimensions = len(re.findall(r"\[\s*\]", erased_syntax)) + (1 if "..." in match.group("type") else 0)
            resolved += "[]" * dimensions
            types.append(resolved)
            bindings[match.group("name")] = resolved if resolution in {"resolved", "primitive"} else "unknown"
        return types, bindings

    def _declarations(self, file: dict[str, Any]) -> None:
        code = file["code"]
        if file["issues"]:
            return
        # Several members may share a line. Direct-member depth rejects method
        # statements, nested bodies and anonymous-class statements.
        pattern = re.compile(self.core.JAVA_METHOD_RE.pattern.replace(r"^[ \t]*", r"(?<![\w$.])\s*", 1)
                             .replace(r"(?:<[^>{};]+>\s+)?", r"(?P<type_parameters><[^>{};]+>\s*)?", 1), re.M)
        for scope in file["scopes"]:
            owner = scope["qualified_name"]
            for match in self.core._java_direct_member_matches(code, pattern, scope["body_start"], scope["body_end"]):
                if match.group("name") == scope["name"] or self.core._clean_java_type(match.group("return")) in {"class", "interface", "record", "enum"}:
                    continue
                type_variables = {**self._type_variables(owner), **self._type_parameters(match.group("type_parameters") or "")}
                types, params = self._parameters(file, match.group("params"), owner, type_variables)
                parameter_refs = []
                for parameter in self.core._split_java_parameters(match.group("params")):
                    cleaned = re.sub(self.core.JAVA_ANNOTATION_PATTERN + r"\s*", "", parameter)
                    cleaned = re.sub(r"\bfinal\s+", "", cleaned).strip()
                    parsed = re.match(rf"(?P<type>.+?)\s+(?P<name>{IDENT})(?P<array>(?:\s*\[\s*\])*)\s*$", cleaned, re.S)
                    if parsed:
                        raw_type = parsed.group("type")
                        ref = self.type_reference(file, raw_type, owner, context="parameter", type_variables=type_variables,
                                                  extra_dimensions=len(re.findall(r"\[\s*\]", parsed.group("array"))))
                        ref.update(name=parsed.group("name"), annotations=re.findall(r"@(" + IDENT + r"(?:\." + IDENT + r")*)", parameter))
                    else:
                        ref = self.type_reference(file, "?", owner, context="parameter", type_variables=type_variables)
                    parameter_refs.append(ref)
                return_ref = self.type_reference(file, match.group("return"), owner, context="return", type_variables=type_variables)
                throws = re.search(r"\bthrows\s+(.+?)[{;]\s*$", match.group(0)[match.end("params") - match.start():], re.S)
                thrown_refs = [self.type_reference(file, value, owner, context="throws", type_variables=type_variables)
                               for value in self.core._split_java_parameters(throws.group(1))] if throws else []
                q = owner + "#" + match.group("name") + "(" + ",".join(types) + ")"
                entry = {"id": self.core._node_id("java", "method", q), "qualified_name": q,
                         "owner_id": scope["id"], "owner": owner, "name": match.group("name"),
                         "path": file["path"], "match_start": match.start(), "match": match,
                         "parameter_types": types, "parameter_names": list(params), "parameters": params,
                         "parameter_count": len(types), "return_type": return_ref["erasedType"],
                         "parameter_references": parameter_refs, "return_reference": return_ref,
                         "type_parameters": [{"name": name, "rawBounds": bound,
                             "bounds": [self.type_reference(file, value.strip(), owner, context="type_parameter_bound", type_variables=type_variables)
                                        for value in bound.split("&") if value.strip()]} for name, bound in self._type_parameters(match.group("type_parameters") or "").items()],
                         "annotations": [self.type_reference(file, name, owner, context="annotation", type_variables=type_variables)
                                         for name in re.findall(r"@(" + IDENT + r"(?:\." + IDENT + r")*)", match.group("annotations"))],
                         "throws": thrown_refs,
                         "static": bool(re.search(r"\bstatic\b", match.group(0).split("(", 1)[0])),
                         "varargs": "..." in match.group("params"),
                         "owner_body_start": scope["body_start"], "owner_body_end": scope["body_end"],
                         "line_start": self.core._line_span(code, match.start(), match.end())[0],
                         "line_end": self.core._line_span(code, match.start(), match.end())[1]}
                if match.group("ending") == "{":
                    entry["body_start"] = match.end()
                    entry["body_end"] = self.core._matching_java_brace(code, match.end() - 1)
                    entry["body_span"] = dict(zip(("lineStart", "lineEnd"), self.core._line_span(code, match.end() - 1, entry["body_end"] + 1)))
                declaration_start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
                entry["declaration_span"] = dict(zip(("lineStart", "lineEnd"), self.core._line_span(code, declaration_start, entry.get("body_end", match.end() - 1) + 1)))
                if entry["id"] in self.methods:
                    raise self.core.DuplicateDeclarationError("Duplicate Java method declaration in selected source scope.")
                file["methods"].append(entry)
                self.methods[entry["id"]] = entry
                self.methods_by_key[(owner, entry["name"])].append(entry)
            for match in self.core._java_direct_member_matches(code, MEMBER, scope["body_start"], scope["body_end"]):
                if match.group("type") in {"return", "throw", "package", "import", "new"}:
                    continue
                ref = self.type_reference(file, match.group("type"), owner)
                self.fields[(owner, match.group("name"))].add(ref["resolvedType"] or "unknown")
                self.field_declarations[(owner, match.group("name"))].append({"owner": owner, "path": file["path"],
                    "name": match.group("name"), "start": match.start(), "headerEnd": match.end(),
                    "modifiers": match.group("mods").split(), "typeReference": ref})
            if scope["kind"] == "record":
                header = self.core._remove_leading_balanced(scope["header"], "<", ">")
                if header.lstrip().startswith("("):
                    opening = header.index("(")
                    closing = self.core._matching_java_parenthesis(header, opening, len(header))
                    _, components = self._parameters(file, header[opening + 1:closing], owner)
                    for name, type_name in components.items():
                        self.fields[(owner, name)].add(type_name)

    def reference_type(self, file: dict[str, Any], raw: str, owner: str) -> str:
        return self.type_reference(file, raw, owner)["erasedType"]

    def _bindings(self, file: dict[str, Any], method: dict[str, Any], position: int) -> dict[str, set[str]]:
        bindings = {name: set(values) for (owner, name), values in self.fields.items() if owner == method["owner"]}
        bindings.update({ref["name"]: {ref["resolvedType"] or "unknown"} for ref in method["parameter_references"] if "name" in ref})
        code = file["code"]
        if "_locals" not in method:
            locals_ = []
            # Derive all lexical block ends once per method; avoid rescanning a
            # large method for each call (quadratic in real service code).
            stack, ends, blocks = [], {}, []
            delimiter_stack, pairs, balanced = [], {}, True
            for cursor in range(method["body_start"] - 1, method["body_end"] + 1):
                if code[cursor] == "{":
                    stack.append(cursor)
                elif code[cursor] == "}" and stack:
                    ends[stack.pop()] = cursor
                if code[cursor] in "([{":
                    delimiter_stack.append(cursor)
                elif code[cursor] in ")]}":
                    if not delimiter_stack or "([{".index(code[delimiter_stack[-1]]) != ")]}".index(code[cursor]):
                        balanced = False
                    else:
                        pairs[delimiter_stack.pop()] = cursor
            enhanced_headers = []
            statement_cache = {}
            for for_match in re.finditer(r"\bfor\s*\(", code[method["body_start"]:method["body_end"]]):
                opening = method["body_start"] + for_match.end() - 1
                closing = self.core._matching_java_parenthesis(code, opening, method["body_end"])
                if closing >= method["body_end"] or code[closing] != ")":
                    continue
                body = closing + 1
                while body < method["body_end"] and code[body].isspace():
                    body += 1
                body_end = (_statement_extent(code, body, method["body_end"], pairs, statement_cache)
                            if balanced and not delimiter_stack else None)
                enhanced_headers.append((opening, closing, body, body_end))
            for match in LOCAL.finditer(code, method["body_start"], method["body_end"]):
                if match.group("type") in {"return", "throw", "new", "case", "yield"}:
                    continue
                active = [(a, b) for a, b in ends.items() if a < match.start() < b]
                block_end = max(active, key=lambda span: span[0])[1] if active else method["body_end"]
                value = self.type_reference(file, match.group("type"), method["owner"])["resolvedType"] or "unknown"
                if match.group("type") == "var":
                    created = re.match(r"\s*=\s*new\s+(" + TYPE + r")\s*\(", code[match.end():match.end() + 1024])
                    value = self.type_name(file, created.group(1), method["owner"]) if created else "unknown"
                enhanced = [header for header in enhanced_headers if header[0] < match.start() < match.end() < header[1]
                            and re.match(r"\s*:", code[match.end():header[1]])]
                if enhanced:
                    opening, closing, body, body_end = min(enhanced, key=lambda header: header[1] - header[0])
                    if not code[opening + 1:match.start()].strip() and body_end is not None:
                        # The iterable expression is outside the binder scope.
                        locals_.append((body - 1, body_end, match.group("name"), value))
                    else:
                        # Complex/unsupported statement boundaries must not
                        # leave an apparently exact receiver after the loop.
                        locals_.append((closing, method["body_end"], match.group("name"), "unknown"))
                else:
                    locals_.append((match.start(), block_end, match.group("name"), value))
            # Untyped lambda variables may shadow fields. Decline them rather
            # than inheriting an unrelated outer type.
            for match in re.finditer(rf"(?P<one>{IDENT})\s*->|\((?P<many>[^()]*)\)\s*->", code[method["body_start"]:method["body_end"]]):
                raw = match.group("one") or match.group("many") or ""
                for piece in self.core._split_java_parameters(raw):
                    names = re.findall(IDENT, piece)
                    if names:
                        locals_.append((method["body_start"] + match.start(), method["body_end"], names[-1], "unknown"))
            method["_locals"] = sorted(locals_)
        for start, end, name, value in method["_locals"]:
            if start < position < end:
                bindings[name] = {value}
        return bindings

    def _lexical_receiver(self, file: dict[str, Any], method: dict[str, Any], text: str, position: int) -> tuple[set[str], bool]:
        text = re.sub(r"\s+", "", text)
        if not text:
            return {method["owner"]}, False
        parts = text.split(".")
        bindings = self._bindings(file, method, position)
        if parts[0] == "this":
            types, rest = {method["owner"]}, parts[1:]
        elif parts[0] in bindings:
            types, rest = bindings[parts[0]], parts[1:]
        elif parts[0] == "super":
            return set(), False
        else:
            name, resolution, _, _ = self._resolve_type(file, text, method["owner"],
                {p["name"]: p["rawBounds"] for p in method["type_parameters"]})
            if resolution == "resolved" and (name in self.types or parts[0] in file["imports"]):
                return {name}, True
            return set(), True
        for field in rest:
            types = set().union(*(self.fields.get((owner, field), set()) for owner in types))
        return types - {"unknown"}, False

    def _receiver(self, file: dict[str, Any], method: dict[str, Any], end: int, position: int, depth: int = 0) -> tuple[set[str], bool]:
        if depth > MAX_RECEIVER_CHAIN_DEPTH:
            method["_receiver_limit_hit"] = True
            return set(), False
        code = file["code"]
        while end > method["body_start"] and code[end - 1].isspace():
            end -= 1
        if end <= method["body_start"]:
            return set(), False
        if code[end - 1] == ")":
            opening = _reverse_open(code, end)
            if opening < method["body_start"]:
                return set(), False
            prefix_start = max(method["body_start"], opening - 4096)
            prefix = code[prefix_start:opening]
            name_match = re.search(rf"(?P<name>{IDENT})\s*$", prefix)
            if not name_match:
                return self._receiver(file, method, end - 1, position, depth + 1)
            name, cursor = name_match.group("name"), prefix_start + name_match.start()
            created = re.search(r"\bnew\s+(" + TYPE + r")\s*$", prefix)
            if created:
                return {self.type_name(file, created.group(1), method["owner"])}, False
            while cursor > 0 and code[cursor - 1].isspace():
                cursor -= 1
            if cursor > 0 and code[cursor - 1] == ".":
                owners, static = self._receiver(file, method, cursor - 1, position, depth + 1)
            else:
                owners, static = {method["owner"]}, False
            arity = self.core._java_call_argument_count(file["original"], opening, end - 1)
            targets, reason = self._targets(file, method, owners, name, arity, opening, end - 1, static, position)
            return ({targets[0]["return_reference"]["resolvedType"]} if len(targets) == 1 and reason == "resolved_declaration" and targets[0]["return_reference"]["resolvedType"] else set()), False
        match = re.search(rf"(?P<value>{IDENT}(?:\s*\.\s*{IDENT})*)\s*$", code[max(method["body_start"], end - 4096):end])
        if match:
            return self._lexical_receiver(file, method, match.group("value"), position)
        return set(), False

    def _argument_types(self, file: dict[str, Any], method: dict[str, Any], opening: int, closing: int, position: int) -> list[str | None]:
        raw, code = file["original"][opening + 1:closing], file["code"][opening + 1:closing]
        result, start, levels, spans = [], 0, [0, 0, 0], []
        for i, char in enumerate(code):
            if char in "([{":
                levels["([{".index(char)] += 1
            elif char in ")]}":
                levels[")]}".index(char)] -= 1
            elif char == "," and not any(levels):
                spans.append((start, i))
                start = i + 1
        if raw.strip():
            spans.append((start, len(code)))
        bindings = self._bindings(file, method, position)
        for a, b in spans:
            expr, original = code[a:b].strip(), raw[a:b].strip()
            kind = None
            if re.fullmatch(r'"(?:[^"\\]|\\.)*"', original, re.S):
                kind = "java.lang.String"
            elif re.fullmatch(r"'(?:[^'\\]|\\.)'", original, re.S):
                kind = "java.lang.char"
            elif expr in {"true", "false"}:
                kind = "java.lang.boolean"
            elif re.fullmatch(r"[-+]?\d+[lL]", expr):
                kind = "java.lang.long"
            elif re.fullmatch(r"[-+]?\d+", expr):
                kind = "java.lang.int"
            elif expr in bindings and len(bindings[expr]) == 1:
                kind = next(iter(bindings[expr]))
                if kind == "unknown":
                    kind = None
            else:
                created = re.match(r"new\s+(" + TYPE + r")\s*\(", expr)
                if created:
                    kind = self.type_name(file, created.group(1), method["owner"])
            result.append(kind)
        return result

    def _targets(self, file: dict[str, Any], method: dict[str, Any], owners: set[str], name: str, arity: int | None,
                 opening: int, closing: int, static: bool, position: int) -> tuple[list[dict[str, Any]], str]:
        if not owners:
            return [], "receiver_type_unresolved"
        declared, incomplete = [], False
        for owner in owners:
            values, missing = self._inherited_methods(owner, name, set())
            declared.extend(values)
            incomplete = incomplete or missing
        candidates = [m for m in declared if
                      (arity == m["parameter_count"] or (m["varargs"] and arity is not None and arity >= m["parameter_count"] - 1))]
        if static:
            candidates = [m for m in candidates if m["static"]]
        if not candidates:
            return [], "target_declaration_outside_index_or_inherited"
        if incomplete:
            return candidates, "inherited_overload_scope_incomplete"
        # A unique declaration in a complete owner scope does not require its
        # parameter or return types to be fully resolved. Those types remain
        # explicitly partial evidence; they matter when selecting overloads or
        # deriving the receiver of a subsequent chained invocation.
        if len(candidates) == 1 and not candidates[0]["varargs"] and len(owners) == 1:
            return candidates, "resolved_declaration"
        if any(ref["resolution"] not in {"resolved", "primitive"} for candidate in candidates for ref in candidate["parameter_references"]):
            return candidates, "parameter_type_resolution_incomplete"
        args = self._argument_types(file, method, opening, closing, position)
        exact = [m for m in candidates if not m["varargs"] and all(x is not None for x in args) and args == m["parameter_types"]]
        if len(exact) == 1 and len(owners) == 1:
            return exact, "resolved_declaration"
        return candidates, "overload_or_receiver_ambiguous"

    def _inherited_methods(self, owner: str, name: str, seen: set[str]) -> tuple[list[dict[str, Any]], bool]:
        if owner in seen:
            return [], True
        scope = self.types.get(owner)
        if scope is None:
            if owner in PLATFORM_INTERFACES and name not in PLATFORM_INTERFACES[owner]:
                return [], False
            return [], True
        seen = seen | {owner}
        methods = list(self.methods_by_key.get((owner, name), []))
        signatures = {tuple(m["parameter_types"]) for m in methods}
        file = self.files[scope["path"]]
        parents = self.core._java_hierarchy(scope["header"], scope["kind"])
        incomplete = False
        for raw_parent in parents[0] + parents[1]:
            parent = self.type_name(file, raw_parent, owner)
            if parent in {"java.lang.Object", "Object"}:
                continue
            inherited, missing = self._inherited_methods(parent, name, seen)
            incomplete = incomplete or missing
            for item in inherited:
                signature = tuple(item["parameter_types"])
                if signature not in signatures:
                    methods.append(item)
                    signatures.add(signature)
        return methods, incomplete

    def _calls(self, file: dict[str, Any]) -> list[dict[str, Any]]:
        rows, code = [], file["code"]
        for method in file["methods"]:
            if "body_start" not in method:
                continue
            start, end = method["body_start"], method["body_end"]
            annotations = self.core._java_annotation_spans(code, start, end)
            nested = [(s["start"], s["body_end"]) for s in file["scopes"] if start <= s["start"] < end]
            for match in INVOKE.finditer(code, start, end):
                position, name = match.start(), match.group("name")
                if name in self.core.JAVA_NON_CALL_KEYWORDS or any(a <= position < b for a, b in annotations + nested):
                    continue
                opening = code.find("(", match.start(), match.end())
                closing = self.core._matching_java_parenthesis(code, opening, end)
                if closing >= end or code[closing] != ")":
                    reason, targets, owners = "unbalanced_invocation", [], set()
                    closing, constructor = opening, False
                else:
                    cursor = match.start()
                    while cursor > start and code[cursor - 1].isspace():
                        cursor -= 1
                    constructor = bool(re.search(r"\bnew\s*(?:" + IDENT + r"\s*\.\s*)*$", code[max(start, cursor - 4096):cursor]))
                    after = closing + 1
                    while after < end and code[after].isspace():
                        after += 1
                    if after < end and code[after] == "{" and not constructor:
                        continue
                    if constructor:
                        owners, targets, reason = set(), [], "constructor_target_not_indexed"
                        if after < end and code[after] == "{":
                            nested.append((after, self.core._matching_java_brace(code, after)))
                    else:
                        method["_receiver_limit_hit"] = False
                        owners, static = self._receiver(file, method, cursor - 1, position) if cursor > start and code[cursor - 1] == "." else ({method["owner"]}, False)
                        arity = self.core._java_call_argument_count(file["original"], opening, closing)
                        targets, reason = self._targets(file, method, owners, name, arity, opening, closing, static, position)
                        if not targets and method["_receiver_limit_hit"]:
                            reason = "receiver_chain_depth_limit"
                resolved = reason == "resolved_declaration"
                lines = self.core._line_span(code, position, closing)
                row = {"id": "java-callsite:" + _hash(file["path"] + ":" + str(position) + ":" + file["sourceHash"])[:24],
                       "path": file["path"], "sourceHash": file["sourceHash"], "caller": method["id"],
                       "line_start": lines[0], "line_end": lines[1], "column": position - code.rfind("\n", 0, position),
                       "name": name, "invocationKind": "constructor" if constructor else "method",
                       "resolution": "exact" if resolved else "candidate" if targets else "unresolved",
                       "reason": reason, "candidateTargets": sorted(m["id"] for m in targets),
                       "receiverTypes": sorted(owners), "runtimeDispatch": "not_observed"}
                if resolved:
                    row["target"] = targets[0]["id"]
                rows.append(row)
                if len(rows) > self.core.MAX_GRAPH_EDGES:
                    raise self.core.OntologyError("Java invocation accounting exceeds the result safety budget.")
        return sorted(rows, key=lambda row: (row["line_start"], row["column"], row["id"]))

    def summary(self) -> dict[str, Any]:
        rows = [r for path in sorted(self.calls) for r in self.calls[path]]
        counts = Counter(r["resolution"] for r in rows)
        return {"schemaVersion": 1, "indexHash": self.fingerprint, "sourceIndexHash": self.source_fingerprint,
                "analyzerHash": self.analyzer_hash, "status": "PARTIAL",
                "denominatorDefinition": "Recognized invocation sites inside recognized method bodies in selected Java files; not all Java invocations.",
                "denominator": len(rows), "numerator": counts["exact"], "counts": dict(sorted(counts.items())),
                "wholeSourceDenominator": None, "unsupported": UNSUPPORTED, "callsites": rows,
                "fileIssues": [{"path": path, "reasons": file["issues"]} for path, file in self.files.items() if file["issues"]],
                "signatureConvention": "Legacy java.lang-prefixed primitive tokens are signature identities, not Java class declarations.",
                "limits": {"sourceFiles": self.core.MAX_SOURCE_FILES,
                           "sourceBytes": self.core.MAX_TOTAL_SOURCE_BYTES,
                           "declarations": self.core.MAX_GRAPH_NODES,
                           "callsites": self.core.MAX_GRAPH_EDGES,
                           "receiverChainDepth": MAX_RECEIVER_CHAIN_DEPTH,
                           "typeReferenceDepth": MAX_TYPE_REFERENCE_DEPTH}}
