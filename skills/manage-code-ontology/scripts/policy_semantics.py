"""Source-bound Java policy fragments, never executable or approved policies.

The grammar intentionally preserves only bounded numeric/boolean expression
structure. Strings, comments, sensitive values, evaluation and inferred units
are absent. A fragment inventory is not the denominator of business rules.
Unsupported fragments retain their source location and a fixed reason code.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

if "privacy_guard" not in globals():
    import privacy_guard

EXTRACTOR_VERSION = "policy-fragments-1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_TOKENS = 250_000
MAX_FRAGMENTS = 20_000
MAX_EXPRESSION_TOKENS = 512
MAX_EXPRESSION_DEPTH = 32
_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]{0,127}\Z")
_SENSITIVE = re.compile(r"password|passwd|secret|credential|private_?key|api_?key|access_?token|authorization|email", re.I)
_NUMBER = re.compile(r"(?:0|[1-9][0-9_]*)(?:\.[0-9_]+)?(?:[eE][+-]?[0-9]+)?[lLfFdD]?\Z")
_MODIFIERS = {"public", "private", "protected", "static", "final", "transient", "volatile"}
_CONTROL = {"if", "while", "for", "switch", "catch", "synchronized"}
_ASSIGN = {"=", "+=", "-=", "*=", "/=", "%="}
_BINARY = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
           "<": 7, "<=": 7, ">": 7, ">=": 7, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}


class SemanticError(ValueError):
    """Fixed diagnostics only, never interpolated source or filenames."""


class _Unsupported(Exception):
    def __init__(self, reason: str):
        self.reason = reason


@dataclass(frozen=True)
class _Token:
    value: str
    start: int
    end: int
    kind: str = "token"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _id(*parts: Any) -> str:
    return "semantic:" + hashlib.sha256(_canonical(parts)).hexdigest()


def _tokens(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(source):
        char = source[position]
        if char.isspace():
            position += 1
            continue
        if source.startswith("//", position):
            following = source.find("\n", position)
            position = len(source) if following < 0 else following
            continue
        if source.startswith("/*", position):
            end = source.find("*/", position + 2)
            if end < 0:
                raise _Unsupported("unterminated_comment")
            position = end + 2
            continue
        start = position
        if source.startswith('"""', position):
            end = source.find('"""', position + 3)
            if end < 0:
                raise _Unsupported("unterminated_literal")
            position = end + 3
            tokens.append(_Token("", start, position, "redacted_literal"))
        elif char in "\"'":
            position += 1
            while position < len(source):
                if source[position] == "\\":
                    position += 2
                elif source[position] == char:
                    position += 1
                    break
                elif source[position] in "\r\n":
                    raise _Unsupported("unterminated_literal")
                else:
                    position += 1
            else:
                raise _Unsupported("unterminated_literal")
            # Numeric constructor literals remain internal until a proven
            # java.math.BigDecimal constructor consumes them. Every other
            # string/character is opaque, including numeric-looking secrets.
            value = source[start + 1:position - 1]
            decimal = char == '"' and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?", value)
            tokens.append(_Token(value if decimal else "", start, position,
                                 "decimal_string" if decimal else "redacted_literal"))
        elif char.isdigit():
            match = re.match(r"(?:0[xX][0-9a-fA-F_]+|[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][+-]?[0-9_]+)?)[lLfFdD]?", source[position:])
            assert match
            position += len(match.group())
            tokens.append(_Token(match.group(), start, position, "number"))
        elif char.isalpha() or char in "_$":
            match = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", source[position:])
            if not match:
                position += 1
                tokens.append(_Token("", start, position, "unsupported_character"))
            else:
                position += len(match.group())
                tokens.append(_Token(match.group(), start, position, "name"))
        else:
            operator = next((item for item in (">>>", "<<", ">>", "->", "::", "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%=") if source.startswith(item, position)), char)
            position += len(operator)
            tokens.append(_Token(operator, start, position))
        if len(tokens) > MAX_TOKENS:
            raise _Unsupported("token_budget_exceeded")
    return tokens


def _numeric(token: _Token) -> dict[str, Any]:
    value = token.value.replace("_", "")
    if not _NUMBER.fullmatch(value):
        raise _Unsupported("unsupported_numeric_literal")
    # Large/high-entropy numbers may be credentials, identifiers or personal
    # values. Preserve an explicit gap instead of copying them into knowledge.
    if len(re.sub(r"[^0-9]", "", value)) > 12:
        raise _Unsupported("numeric_value_redacted")
    suffix = value[-1:] if value[-1:] in "lLfFdD" else ""
    value = value[:-1] if suffix else value
    kind = "floating" if "." in value or "e" in value.lower() or suffix.lower() in {"f", "d"} else "integer"
    return {"op": "literal", "type": kind, "value": value, "javaSuffix": suffix or None}


class _Expression:
    def __init__(self, tokens: list[_Token], decimal_bound: bool):
        self.tokens = tokens
        self.index = 0
        self.decimal_bound = decimal_bound
        self.reasons: set[str] = set()
        self.references: set[str] = set()
        if len(tokens) > MAX_EXPRESSION_TOKENS:
            raise _Unsupported("expression_budget_exceeded")
        if any(token.kind == "name" and _SENSITIVE.search(token.value) for token in tokens):
            raise _Unsupported("sensitive_value_redacted")

    def peek(self) -> str:
        return self.tokens[self.index].value if self.index < len(self.tokens) else ""

    def consume(self, expected: str | None = None) -> _Token:
        if self.index >= len(self.tokens) or (expected is not None and self.peek() != expected):
            raise _Unsupported("unsupported_expression_syntax")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parse(self) -> dict[str, Any]:
        if not self.tokens:
            raise _Unsupported("missing_expression")
        value = self.expression(0, 0)
        if self.index != len(self.tokens):
            raise _Unsupported("unsupported_expression_syntax")
        return value

    def expression(self, minimum: int, depth: int) -> dict[str, Any]:
        if depth > MAX_EXPRESSION_DEPTH:
            raise _Unsupported("expression_depth_exceeded")
        token = self.consume()
        if token.value in {"!", "-", "+", "~"}:
            left = {"op": "unary", "operator": token.value, "operand": self.expression(11, depth + 1)}
        elif token.value == "(":
            left = self.expression(0, depth + 1)
            self.consume(")")
        elif token.kind == "number":
            left = _numeric(token)
        elif token.value in {"true", "false"}:
            left = {"op": "literal", "type": "boolean", "value": token.value == "true"}
        elif token.value == "null":
            left = {"op": "literal", "type": "null", "value": None}
        elif token.value == "new":
            name = self.consume().value
            while self.peek() == ".":
                self.consume(); name += "." + self.consume().value
            if name not in {"BigDecimal", "java.math.BigDecimal"} or (name == "BigDecimal" and not self.decimal_bound):
                raise _Unsupported("constructor_semantics_unresolved")
            self.consume("(")
            literal = self.consume()
            if literal.kind != "decimal_string":
                raise _Unsupported("decimal_constructor_overload_unsupported")
            self.consume(")")
            left = {"op": "literal", "type": "decimal", "value": literal.value,
                    "binding": "java.math.BigDecimal.String"}
        elif token.kind == "name" and _NAME.fullmatch(token.value):
            left = {"op": "reference", "name": token.value}
        elif token.kind in {"decimal_string", "redacted_literal"}:
            raise _Unsupported("string_or_character_value_redacted")
        else:
            raise _Unsupported("unsupported_expression_syntax")
        while self.index < len(self.tokens):
            operator = self.peek()
            if operator == ".":
                self.consume()
                member = self.consume()
                if member.kind != "name" or not _NAME.fullmatch(member.value):
                    raise _Unsupported("unsupported_member_access")
                if left.get("op") == "reference":
                    left = {"op": "reference", "name": left["name"] + "." + member.value}
                else:
                    left = {"op": "member", "receiver": left, "name": member.value}
                continue
            if operator == "(":
                self.consume()
                arguments = []
                if self.peek() != ")":
                    while True:
                        arguments.append(self.expression(0, depth + 1))
                        if self.peek() != ",":
                            break
                        self.consume()
                self.consume(")")
                # The source structure is retained; neither a method name nor
                # receiver spelling establishes arithmetic or authorization.
                self.reasons.add("call_semantics_unresolved")
                left = {"op": "call", "callee": left, "arguments": arguments,
                        "resolution": "syntax_only"}
                continue
            if operator == "?" and minimum <= 0:
                self.consume()
                yes = self.expression(0, depth + 1)
                self.consume(":")
                no = self.expression(0, depth + 1)
                left = {"op": "conditional", "condition": left, "then": yes, "else": no}
                continue
            precedence = _BINARY.get(operator, -1)
            if precedence < minimum:
                break
            self.consume()
            right = self.expression(precedence + 1, depth + 1)
            left = {"op": "binary", "operator": operator, "left": left, "right": right}
        return left


def _walk_references(expression: Any) -> list[str]:
    result = set()
    pending = [expression]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if item.get("op") == "reference":
                result.add(item["name"])
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return sorted(result)


def extract_semantics(source: str, language: str, path: str, source_digest: str,
                      *, max_fragments: int = MAX_FRAGMENTS) -> dict[str, Any]:
    """Return a bounded fragment inventory; never reread source or evaluate it.

    `represented` means the restricted expression grammar retained the syntax,
    not complete policy semantics. `partial` preserves calls as syntax with an
    unresolved-semantics reason. Unsupported values are absent, not guessed.
    """
    if (not isinstance(source, str) or not isinstance(path, str) or not path or len(path) > 1024
            or PurePosixPath(path).is_absolute() or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path or ":" in path or "\x00" in path
            or not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
            or type(max_fragments) is not int or not 1 <= max_fragments <= MAX_FRAGMENTS):
        raise SemanticError("invalid_semantic_arguments")
    try:
        raw = source.encode("utf-8")
    except UnicodeError:
        raise SemanticError("source_encoding_invalid") from None
    if len(raw) > MAX_SOURCE_BYTES:
        raise SemanticError("source_budget_exceeded")
    if hashlib.sha256(raw).hexdigest() != source_digest:
        raise SemanticError("source_digest_mismatch")
    privacy_guard.ensure_public_safe(path)
    coverage = {"scope": "detected_java_expression_fragments", "detectedFragments": 0,
                "representedFragments": 0, "partialFragments": 0, "unsupportedFragments": 0,
                "recordedFragments": 0, "inventoryComplete": False, "semanticComplete": False,
                "wholePolicyDenominator": "UNKNOWN", "businessPolicyComplete": False,
                "complete": False, "reasons": []}
    result = {"schemaVersion": 1, "extractorVersion": EXTRACTOR_VERSION, "path": path,
              "sourceDigest": source_digest, "language": language,
              "sourceSpan": {"lineStart": 1, "lineEnd": max(1, len(source.splitlines()))},
              "fragments": [], "omissions": [], "coverage": coverage}
    if language != "Java":
        coverage["reasons"] = ["unsupported_fragment_language"]
        return result
    line_offsets = [-1] + [match.start() for match in re.finditer("\n", source)]

    def span(start: int, end: int) -> dict[str, int]:
        return {"lineStart": bisect.bisect_left(line_offsets, start),
                "lineEnd": bisect.bisect_left(line_offsets, max(start, end - 1))}

    try:
        tokens = _tokens(source)
    except _Unsupported as error:
        coverage["reasons"] = [error.reason]
        coverage["unprocessedRegion"] = span(0, len(source))
        return result
    values = [token.value for token in tokens]
    parens: dict[int, int] = {}
    braces: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    balanced = True
    for index, token in enumerate(tokens):
        if token.value in {"(", "[", "{"}:
            stack.append((token.value, index))
        elif token.value in {")", "]", "}"}:
            wanted = {")": "(", "]": "[", "}": "{"}[token.value]
            if not stack or stack[-1][0] != wanted:
                balanced = False
                break
            _, opening = stack.pop()
            if wanted == "(":
                parens[opening] = index
                parens[index] = opening
            elif wanted == "{":
                braces[opening] = index
    if stack or not balanced:
        coverage["reasons"] = ["unbalanced_source_syntax"]
        coverage["unprocessedRegion"] = span(0, len(source))
        return result
    # Only a checked explicit java.math import permits the short constructor.
    text = " ".join(values)
    decimal_bound = bool(re.search(r"\bimport java \. math \. BigDecimal ;", text))
    if re.search(r"\b(?:class|interface|enum|record) BigDecimal\b", text):
        decimal_bound = False
    fragment_keys: set[tuple[int, int, str]] = set()
    declarations: list[dict[str, Any]] = []
    scopes: dict[int, tuple[int, ...]] = {}
    scope_stack: list[int] = []
    for index, token in enumerate(tokens):
        scopes[index] = tuple(scope_stack)
        if token.value == "{":
            scope_stack.append(index)
        elif token.value == "}" and scope_stack:
            scope_stack.pop()

    def add(category: str, start: int, end: int, expression_tokens: list[_Token], *,
            name: str | None = None, declared_type: str | None = None,
            reason: str | None = None, operator: str | None = None) -> None:
        if end < start or start >= len(tokens):
            return
        key = (start, end, category)
        if key in fragment_keys:
            return
        fragment_keys.add(key)
        coverage["detectedFragments"] += 1
        if len(result["fragments"]) >= max_fragments:
            coverage["reasons"] = sorted(set(coverage["reasons"]) | {"fragment_budget_exceeded"})
            result["omissions"].append({"id": _id(path, source_digest, category, tokens[start].start, tokens[end].end),
                                       "path": path, "sourceDigest": source_digest, "category": category,
                                       "span": span(tokens[start].start, tokens[end].end),
                                       "reason": "fragment_budget_exceeded", "status": "not_processed"})
            return
        fragment = {"id": _id(path, source_digest, category, tokens[start].start, tokens[end].end),
                    "path": path, "sourceDigest": source_digest, "category": category,
                    "span": span(tokens[start].start, tokens[end].end),
                    "representationStatus": "unsupported", "expression": None,
                    "references": [], "unsupportedReasons": [],
                    "unit": {"status": "UNKNOWN", "reason": "unit_not_explicitly_bound"},
                    "businessMeaningVerified": False, "runtimeStatus": "not_observed",
                    "extractorVersion": EXTRACTOR_VERSION}
        if name and _NAME.fullmatch(name):
            fragment["name"] = name
        if declared_type:
            fragment["declaredType"] = declared_type
        if operator:
            fragment["assignmentOperator"] = operator
        try:
            if reason:
                raise _Unsupported(reason)
            if name and _SENSITIVE.search(name):
                raise _Unsupported("sensitive_value_redacted")
            parser = _Expression(expression_tokens, decimal_bound)
            expression = parser.parse()
            fragment["expression"] = expression
            fragment["representationStatus"] = "partial" if parser.reasons else "represented"
            fragment["unsupportedReasons"] = sorted(parser.reasons)
            fragment["references"] = [{"name": ref, "resolution": "unresolved", "declarations": []}
                                      for ref in _walk_references(expression)]
        except (_Unsupported, RecursionError) as error:
            fragment["unsupportedReasons"] = [error.reason if isinstance(error, _Unsupported) else "expression_depth_exceeded"]
        # No input-derived payload can bypass configured privacy enforcement.
        try:
            privacy_guard.ensure_public_safe(fragment)
        except privacy_guard.PrivacyError:
            for field in ("name", "declaredType"):
                fragment.pop(field, None)
            fragment.update(expression=None, references=[], representationStatus="unsupported",
                            unsupportedReasons=["privacy_denied"])
            privacy_guard.ensure_public_safe(fragment)
        fragment["_scope"] = scopes[start]
        fragment["_position"] = start
        result["fragments"].append(fragment)
        if category in {"field", "constant", "local_declaration"} and name:
            declarations.append({"name": name, "id": fragment["id"], "span": fragment["span"],
                                 "sourceDigest": source_digest, "scope": scopes[start],
                                 "position": start, "field": category != "local_declaration"})

    method_bodies: set[int] = set()
    # Parameter bindings are declarations, but not policy rules or fragments.
    for opening, closing in sorted(parens.items()):
        if opening > closing or opening < 1 or values[opening - 1] in _CONTROL:
            continue
        following = closing + 1
        while following < len(tokens) and values[following] not in {"{", ";", "="}:
            following += 1
        if following >= len(tokens) or values[following] != "{" or not _NAME.fullmatch(values[opening - 1]):
            continue
        if opening > 1 and values[opening - 2] in {".", "new"}:
            continue
        method_bodies.add(following)
        for first, last in _split(tokens, opening + 1, closing, ","):
            names = [index for index in range(first, last) if tokens[index].kind == "name"]
            if len(names) >= 2:
                idx = names[-1]
                name = values[idx]
                declarations.append({"name": name, "id": _id(path, source_digest, "parameter", tokens[idx].start),
                                     "span": span(tokens[idx].start, tokens[idx].end), "sourceDigest": source_digest,
                                     "scope": scopes[following] + (following,), "position": following,
                                     "field": False})
    for index, token in enumerate(tokens):
        if token.value in _CONTROL and index + 1 in parens and values[index + 1] == "(":
            close = parens[index + 1]
            reason = None if token.value in {"if", "while"} else "control_flow_semantics_unsupported"
            add("condition", index, close, tokens[index + 2:close], reason=reason)
        elif token.value in {"try", "finally", "else"}:
            add("control_boundary", index, index, [], reason="control_flow_semantics_unsupported")
    statement_start = 0
    paren_depth = 0
    for index, token in enumerate(tokens):
        if token.value == "(":
            paren_depth += 1
        elif token.value == ")":
            paren_depth -= 1
        if token.value in {"{", "}"} and paren_depth == 0:
            statement_start = index + 1
        if token.value != ";" or paren_depth:
            continue
        start, end = statement_start, index
        statement_start = index + 1
        if start >= end:
            continue
        parts = values[start:end]
        if parts[0] in {"package", "import"}:
            continue
        # An unbraced conditional can precede return, assignment or throw.
        while start < end and values[start] in {"if", "while", "for"} and start + 1 in parens:
            start = parens[start + 1] + 1
        if start >= end:
            continue
        if values[start] == "return":
            add("return", start, end, tokens[start + 1:end])
            continue
        if values[start] in {"throw", "break", "continue", "assert", "yield"}:
            add("control_boundary", start, end, [], reason="control_flow_semantics_unsupported")
            continue
        eq = _top_level_operator(tokens, start, end, _ASSIGN)
        lhs_end = eq if eq is not None else end
        lhs = tokens[start:lhs_end]
        clean = [item for item in lhs if item.value not in _MODIFIERS]
        declaration = (len(clean) >= 2 and clean[-1].kind == "name"
                       and all(item.kind == "name" or item.value in {".", "<", ">", "?", "[", "]", ","} for item in clean[:-1]))
        if declaration:
            name = clean[-1].value
            dtype = "".join(item.value for item in clean[:-1])
            is_local = any(scope in method_bodies for scope in scopes[start])
            category = "local_declaration" if is_local else "constant" if "final" in values[start:lhs_end] else "field"
            add(category, start, end, tokens[eq + 1:end] if eq is not None else [], name=name,
                declared_type=dtype, reason="initializer_absent" if eq is None else None,
                operator=values[eq] if eq is not None else None)
        elif eq is not None:
            name = values[eq - 1] if eq > start and tokens[eq - 1].kind == "name" else None
            add("assignment", start, end, tokens[eq + 1:end], name=name, operator=values[eq])
        else:
            add("statement", start, end, tokens[start:end], reason="statement_effect_semantics_unsupported")
    # Bind only same-file lexical declarations. Cross-file/reference values,
    # overwritten locals and runtime values remain explicitly unresolved.
    for fragment in result["fragments"]:
        scope = fragment.pop("_scope")
        position = fragment.pop("_position")
        for reference in fragment["references"]:
            ref = reference["name"]
            if "." in ref and not ref.startswith("this."):
                continue
            name = ref.removeprefix("this.")
            choices = [decl for decl in declarations if decl["name"] == name
                       and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                       and (not ref.startswith("this.") or decl["field"])
                       and (decl["field"] or decl["position"] < position)]
            if choices:
                depth = max(len(item["scope"]) for item in choices)
                nearest = [item for item in choices if len(item["scope"]) == depth]
                if len(nearest) == 1:
                    chosen = nearest[0]
                    reference["resolution"] = "lexical_declaration_only"
                    reference["declarations"] = [{"id": chosen["id"], "path": path,
                                                  "span": chosen["span"], "sourceDigest": source_digest}]
        status = fragment["representationStatus"]
        coverage[status + "Fragments"] += 1
    coverage["recordedFragments"] = len(result["fragments"])
    coverage["inventoryComplete"] = coverage["recordedFragments"] == coverage["detectedFragments"]
    coverage["reasons"] = sorted(set(coverage["reasons"]) | {"whole_policy_denominator_unknown", "static_fragments_not_business_rules"})
    privacy_guard.ensure_public_safe(result)
    return result


def _split(tokens: list[_Token], start: int, end: int, separator: str):
    depth = 0
    first = start
    for index in range(start, end):
        if tokens[index].value in {"(", "[", "<"}:
            depth += 1
        elif tokens[index].value in {")", "]", ">"}:
            depth -= 1
        elif not depth and tokens[index].value == separator:
            yield first, index
            first = index + 1
    if first < end:
        yield first, end


def _top_level_operator(tokens: list[_Token], start: int, end: int, wanted: set[str]) -> int | None:
    depth = 0
    for index in range(start, end):
        value = tokens[index].value
        if value in {"(", "["}:
            depth += 1
        elif value in {")", "]"}:
            depth -= 1
        elif depth == 0 and value in wanted:
            return index
    return None
