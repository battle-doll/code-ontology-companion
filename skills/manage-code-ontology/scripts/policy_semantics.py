"""Source-bound Java policy fragments, never executable or approved policies.

The grammar preserves bounded source structure, without evaluating it. Quoted
values are opaque unless an exact occurrence passes the optional private review;
sensitive expressions retain structure with masked value terminals. Comments,
evaluated values and inferred units are absent. Fragment counts are not business rules.
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
if "policy_java_flow" not in globals():
    import policy_java_flow
if "policy_java_contracts" not in globals():
    import policy_java_contracts

EXTRACTOR_VERSION = "policy-fragments-2"
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
_ASSIGN = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", ">>>="}
_JAVA_RESERVED_NAMES = set(("abstract assert boolean break byte case catch char class const continue default "
                           "do double else enum extends final finally float for goto if implements import "
                           "instanceof int interface long native new package private protected public return "
                           "short static strictfp super switch synchronized this throw throws transient try "
                           "void volatile while true false null _").split())
_BINARY = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
           "<": 7, "<=": 7, ">": 7, ">=": 7, "instanceof": 7,
           "<<": 8, ">>": 8, ">>>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}


class SemanticError(ValueError):
    """Fixed diagnostics only, never interpolated source or filenames."""


class _Unsupported(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _assignment_variable_syntax(target):
    """Reject reserved pseudo-values without claiming name/type resolution."""
    if target.get("op") == "index":
        return True
    if target.get("op") not in {"reference", "member"}:
        return False
    name = target.get("name", "").rsplit(".", 1)[-1]
    return bool(_NAME.fullmatch(name)) and name not in _JAVA_RESERVED_NAMES


@dataclass(frozen=True)
class _Token:
    value: str
    start: int
    end: int
    kind: str = "token"
    literal_id: int | str | None = None
    payload: Any = None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _id(*parts: Any) -> str:
    return "semantic:" + hashlib.sha256(_canonical(parts)).hexdigest()


def _tokens(source: str, literal_binding=None) -> list[_Token]:
    tokens: list[_Token] = []
    opaque_literals: dict[str, int] = {}
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
            raw_literal = source[start:position]
            opaque_literals.setdefault(raw_literal, len(opaque_literals) + 1)
            tokens.append(_Token("", start, position, "redacted_literal",
                                 literal_binding.opaque_id(start, position) if literal_binding else opaque_literals[raw_literal]))
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
            raw_literal = source[start:position]
            opaque_literals.setdefault(raw_literal, len(opaque_literals) + 1)
            tokens.append(_Token(value if decimal else "", start, position,
                                 "decimal_string" if decimal else "redacted_literal",
                                 literal_binding.opaque_id(start, position) if literal_binding else opaque_literals[raw_literal]))
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
            operator = next((item for item in (">>>=", "<<=", ">>=", ">>>", "<<", ">>", "->", "::", "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=") if source.startswith(item, position)), char)
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


def _instanceof_type_syntax(tokens, start):
    """Read a bounded reference-type spelling, never a resolved runtime type.

    Generic arguments are unbounded wildcards only. Qualified nested segments
    and reference arrays keep their source shape; no erasure, declaration,
    cast-compatibility or actual match is inferred from that spelling.
    """
    cursor = start; segments = []; extended = False; wildcard_count = 0
    def value():
        return tokens[cursor].value if cursor < len(tokens) else ""
    def advance():
        nonlocal cursor
        if cursor - start >= MAX_EXPRESSION_TOKENS:
            raise _Unsupported("instanceof_type_budget_exceeded")
        cursor += 1
    while True:
        if (cursor >= len(tokens) or tokens[cursor].kind != "name"
                or not _NAME.fullmatch(value()) or value() in _JAVA_RESERVED_NAMES
                or value() in {"var", "yield", "record", "sealed", "permits"}):
            raise _Unsupported("instanceof_type_syntax_unsupported")
        name = value(); advance(); arguments = []
        if value() == "<":
            extended = True; advance()
            while True:
                if value() != "?":
                    raise _Unsupported("instanceof_type_nonreifiable_or_unsupported")
                arguments.append("?"); advance(); wildcard_count += 1
                if wildcard_count > MAX_EXPRESSION_DEPTH:
                    raise _Unsupported("instanceof_type_budget_exceeded")
                if value() != ",": break
                advance()
            if value() != ">":
                raise _Unsupported("instanceof_type_nonreifiable_or_unsupported")
            advance()
        segments.append({"name": name, "typeArguments": arguments})
        if value() != ".": break
        advance()
    dimensions = 0
    while value() == "[":
        extended = True; advance()
        if value() != "]": raise _Unsupported("instanceof_type_syntax_unsupported")
        dimensions += 1; advance()
        if dimensions > MAX_EXPRESSION_DEPTH:
            raise _Unsupported("instanceof_type_budget_exceeded")
    name = ".".join(segment["name"] for segment in segments)
    if not extended:
        return {"op": "reference", "name": name}, cursor, False
    if len(segments) > MAX_EXPRESSION_DEPTH:
        raise _Unsupported("instanceof_type_budget_exceeded")
    return {"op": "type_reference", "syntaxVersion": "java.instanceof.type.v1", "name": name, "segments": segments,
            "arrayDimensions": dimensions, "resolution": "syntax_only",
            "reifiableForm": "unbounded_wildcard_or_reference_array_syntax",
            "runtimeTypeCheck": "UNKNOWN", "compileValidity": "UNKNOWN",
            "sourceRange": {"charStart": tokens[start].start, "charEnd": tokens[cursor - 1].end}}, cursor, True


class _Expression:
    def __init__(self, tokens: list[_Token], decimal_bound: bool, base_depth: int = 0, *, structural_only=False):
        self.tokens = tokens
        self.index = 0
        self.decimal_bound = decimal_bound
        self.base_depth = base_depth
        self.structural_only = structural_only
        self.reasons: set[str] = set()
        self.references: set[str] = set()
        # Internal parser observations only; never serialized as source IR.
        self.lambda_scopes = []
        if len(tokens) > MAX_EXPRESSION_TOKENS:
            raise _Unsupported("expression_budget_exceeded")
        if not structural_only and any(token.kind == "name" and _SENSITIVE.search(token.value) for token in tokens):
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

    def arguments(self, depth: int) -> list[dict[str, Any]]:
        self.consume("(")
        result = []
        if self.peek() != ")":
            while True:
                result.append(self.expression(0, depth + 1))
                if self.peek() != ",":
                    break
                self.consume()
        self.consume(")")
        return result

    def type_arguments(self) -> list[str]:
        self.consume("<")
        result = []
        nesting = 1
        while nesting:
            token = self.consume()
            if token.value == "<": nesting += 1
            elif token.value in {">", ">>", ">>>"}: nesting -= len(token.value)
            elif token.kind != "name" and token.value not in {".", ",", "?", "[", "]", "&"}:
                raise _Unsupported("type_arguments_unsupported")
            if nesting < 0:
                raise _Unsupported("type_arguments_unsupported")
            if nesting: result.append(token.value)
        return result

    def array_initializer(self, depth: int) -> dict[str, Any]:
        if self.base_depth + depth > MAX_EXPRESSION_DEPTH:
            raise _Unsupported("expression_depth_exceeded")
        self.consume("{")
        items = []
        while self.peek() != "}":
            items.append(self.array_initializer(depth + 1) if self.peek() == "{" else self.expression(0, depth + 1))
            if self.peek() != ",": break
            self.consume()
        self.consume("}")
        return {"op": "array_initializer", "elements": items, "resolution": "syntax_only"}

    def block(self, depth: int) -> dict[str, Any]:
        """Flat statement IR for lambda and switch blocks, with local contexts."""
        opening = self.index - 1
        parens, braces, stack = {}, {}, []
        closing = None
        for index in range(opening, len(self.tokens)):
            value = self.tokens[index].value
            if value in {"(", "{"}: stack.append((value, index))
            elif value in {")", "}"}:
                wanted = "(" if value == ")" else "{"
                if not stack or stack[-1][0] != wanted:
                    raise _Unsupported("unsupported_block_syntax")
                _, first = stack.pop()
                if wanted == "(": parens[first] = index; parens[index] = first
                else: braces[first] = index
                if not stack:
                    closing = index
                    break
        if closing is None:
            raise _Unsupported("unsupported_block_syntax")
        nodes, _ = policy_java_flow.scan(self.tokens, parens, braces, body_range=(opening + 1, closing))
        indices = {(node["start"], node["kind"]): i for i, node in enumerate(nodes)}
        statements = []
        for node in nodes:
            first, last = node["expressionStart"], node["expressionEnd"]
            selected = self.tokens[first:last]
            kind = node["kind"]
            item = {"kind": kind, "sourceOffsets": {"start": self.tokens[node["start"]].start,
                                                       "end": self.tokens[node["end"]].end},
                    "contexts": [{"statementIndex": indices.get((c["start"], c["kind"])),
                                  "kind": c["kind"], "branch": c["branch"],
                                  **{k: v for k, v in c.items() if k in {"relation", "logic", "group", "fallthroughPossible"}}}
                                 for c in node["contexts"]]}
            if kind in {"try", "finally", "else", "break", "continue"}:
                item["expression"] = {"op": "control", "kind": kind}
            elif kind == "catch":
                item["expression"] = {"op": "catch_binding", "declaration": [t.value for t in selected]}
            elif not selected:
                item["expression"] = {"op": "void"}
            else:
                eq = _top_level_operator(self.tokens, first, last, _ASSIGN) if kind == "statement" else None
                if eq is not None:
                    lhs = self.tokens[first:eq]
                    clean = [t for t in lhs if t.value not in _MODIFIERS]
                    declaration = len(clean) >= 2 and clean[-1].kind == "name" and clean[-2].value != "." and all(t.kind == "name" or t.value in {".", "<", ">", "[", "]", ",", "?"} for t in clean[:-1])
                    item["assignmentOperator"] = self.tokens[eq].value
                    if declaration:
                        item.update(kind="local_declaration", name=clean[-1].value, declaredType="".join(t.value for t in clean[:-1]))
                    else:
                        try:
                            target = _Expression(lhs, self.decimal_bound, self.base_depth + depth + 1, structural_only=self.structural_only)
                            item["target"] = target.parse(); self.reasons.update(target.reasons)
                        except _Unsupported as error:
                            item["target"] = {"op": "unresolved", "reason": error.reason}
                            self.reasons.add(error.reason)
                    selected = self.tokens[eq + 1:last]
                try:
                    parser = _Expression(selected, self.decimal_bound, self.base_depth + depth + 1, structural_only=self.structural_only)
                    item["expression"] = parser.parse()
                    self.reasons.update(parser.reasons)
                    self.lambda_scopes.extend(parser.lambda_scopes)
                except _Unsupported as error:
                    item["expression"] = {"op": "unresolved", "reason": error.reason}
                    self.reasons.add(error.reason)
            statements.append(item)
        self.index = closing + 1
        return {"op": "block", "statements": statements, "orderMeaning": "lexical_order_not_runtime_execution"}

    def expression(self, minimum: int, depth: int) -> dict[str, Any]:
        if self.base_depth + depth > MAX_EXPRESSION_DEPTH:
            raise _Unsupported("expression_depth_exceeded")
        token = self.consume()
        if token.kind == "body_reference":
            left = dict(token.payload)
        elif token.kind == "masked_value":
            left = dict(token.payload)
        elif token.value == "{":
            left = self.block(depth)
        elif token.value in {"!", "-", "+", "~", "++", "--"}:
            left = {"op": "unary", "operator": token.value, "operand": self.expression(11, depth + 1)}
        elif token.value == "(":
            # Lambda parameters are syntax, not an invocation. Keep typed
            # parameter declarations separate from expression references.
            closing = self.index
            nesting = 1
            while closing < len(self.tokens):
                if self.tokens[closing].value == "(": nesting += 1
                if self.tokens[closing].value == ")": nesting -= 1
                if nesting == 0: break
                closing += 1
            if closing + 1 < len(self.tokens) and self.tokens[closing + 1].value == "->":
                params = [[part.value for part in self.tokens[first:last]]
                          for first, last in _split(self.tokens, self.index, closing, ",")]
                self.index = closing + 2
                body_start = self.index
                left = {"op": "lambda", "parameters": params,
                        "body": self.expression(0, depth + 1), "execution": "not_observed"}
                left["sourceRange"] = {"charStart":token.start,"charEnd":self.tokens[self.index-1].end}
                left["parameterRanges"] = [{"charStart":self.tokens[first].start,"charEnd":self.tokens[last-1].end}
                    for first,last in _split(self.tokens, self.tokens.index(token)+1, closing, ",") if first<last]
                self.lambda_scopes.append((left, self.tokens[body_start].start, self.tokens[self.index - 1].end))
                self.reasons.add("lambda_execution_unresolved")
            else:
                # Primitive and qualified/reference casts are retained only
                # when the token following ')' cannot be a binary continuation.
                inside = self.tokens[self.index:closing]
                after = self.tokens[closing + 1] if closing + 1 < len(self.tokens) else None
                cast = (inside and all(t.kind == "name" or t.value in {".", "[", "]", "<", ">", ",", "?"} for t in inside)
                        and after is not None and (after.kind in {"name", "number", "masked_value"} or after.value in {"!", "~", "("}))
                if cast:
                    self.index = closing + 1
                    left = {"op": "cast", "type": "".join(t.value for t in inside),
                            "operand": self.expression(11, depth + 1), "resolution": "syntax_only"}
                    self.reasons.add("cast_type_unresolved")
                else:
                    left = self.expression(0, depth + 1)
                    self.consume(")")
        elif token.kind == "number":
            left = _numeric(token)
        elif token.value in {"true", "false"}:
            left = {"op": "literal", "type": "boolean", "value": token.value == "true"}
        elif token.value == "null":
            left = {"op": "literal", "type": "null", "value": None}
            if self.structural_only:
                left["meaning"] = "source_null_marker_not_observed_state"
        elif token.value == "switch":
            self.consume("(")
            selector = self.expression(0, depth + 1)
            self.consume(")"); self.consume("{")
            arms = []
            while self.peek() != "}":
                marker = self.consume().value
                if marker not in {"case", "default"}:
                    raise _Unsupported("switch_expression_syntax_unsupported")
                labels = []
                if marker == "case":
                    while True:
                        labels.append(self.expression(1, depth + 1))
                        if self.peek() != ",": break
                        self.consume()
                self.consume("->")
                thrown = self.peek() == "throw"
                if thrown: self.consume()
                body = self.expression(0, depth + 1)
                if body.get("op") not in {"block", "body_reference"} or self.peek() == ";":
                    self.consume(";")
                arms.append({"labels": labels, "default": marker == "default",
                             "action": "throw" if thrown else "value", "value": body})
            self.consume("}")
            left = {"op": "switch", "selector": selector, "arms": arms,
                    "selection": "source_case_structure"}
        elif token.value == "new":
            name = self.consume().value
            while self.peek() == ".":
                self.consume(); name += "." + self.consume().value
            if name == "BigDecimal" and not self.decimal_bound and not self.structural_only:
                raise _Unsupported("constructor_semantics_unresolved")
            if (name in {"BigDecimal", "java.math.BigDecimal"} and self.peek() == "("
                    and self.index + 2 < len(self.tokens) and self.tokens[self.index + 1].kind == "decimal_string"
                    and self.tokens[self.index + 2].value == ")"):
                self.consume("("); literal = self.consume(); self.consume(")")
                left = {"op": "literal", "type": "decimal", "value": literal.value,
                        "binding": "java.math.BigDecimal.String"}
            else:
                # Constructor argument order is source evidence. It does not
                # establish overload resolution, immutability or side effects.
                type_arguments = self.type_arguments() if self.peek() == "<" else []
                if self.peek() == "[":
                    dimensions = []
                    while self.peek() == "[":
                        self.consume()
                        dimensions.append(None if self.peek() == "]" else self.expression(0, depth + 1))
                        self.consume("]")
                    left = {"op": "array_construct", "elementType": name, "dimensions": dimensions,
                            "initializer": self.array_initializer(depth) if self.peek() == "{" else None,
                            "resolution": "syntax_only"}
                else:
                    left = {"op": "construct", "type": name,
                            "arguments": self.arguments(depth), "resolution": "syntax_only", "sourceConstructionOffset": token.start}
                    if self.index < len(self.tokens) and self.tokens[self.index].kind == "body_reference":
                        left["anonymousBody"] = dict(self.consume().payload)
                        self.reasons.add("anonymous_class_semantics_unresolved")
                if type_arguments:
                    left["typeArguments"] = type_arguments
                self.reasons.add("constructor_semantics_unresolved")
        elif token.kind == "name" and _NAME.fullmatch(token.value):
            left = {"op": "reference", "name": token.value}
        elif token.kind == "reviewed_literal":
            left = dict(token.payload)
        elif token.kind in {"decimal_string", "redacted_literal"}:
            self.reasons.add("string_or_character_value_redacted")
            left = {"op": "redacted", "reason": "string_or_character_value_redacted",
                    "opaqueLiteralId": token.literal_id,
                    "identityScope": "source_occurrence" if isinstance(token.literal_id, str) else "same_source_raw_literal_spelling"}
        else:
            raise _Unsupported("unsupported_expression_syntax")
        while self.index < len(self.tokens):
            operator = self.peek()
            if operator == ".":
                self.consume()
                type_arguments = self.type_arguments() if self.peek() == "<" else []
                member = self.consume()
                if member.kind != "name" or not _NAME.fullmatch(member.value):
                    raise _Unsupported("unsupported_member_access")
                if left.get("op") == "reference":
                    left = {"op": "reference", "name": left["name"] + "." + member.value}
                else:
                    left = {"op": "member", "receiver": left, "name": member.value}
                if type_arguments:
                    left["typeArguments"] = type_arguments
                continue
            if operator == "(":
                invocation_offset = self.tokens[self.index - 1].start
                arguments = self.arguments(depth)
                # The source structure is retained; neither a method name nor
                # receiver spelling establishes arithmetic or authorization.
                self.reasons.add("call_semantics_unresolved")
                left = {"op": "call", "callee": left, "arguments": arguments,
                        "resolution": "syntax_only", "sourceInvocationOffset": invocation_offset}
                continue
            if operator == "[":
                self.consume()
                subscript = self.expression(0, depth + 1)
                self.consume("]")
                left = {"op": "index", "receiver": left, "index": subscript}
                self.reasons.add("array_access_runtime_unresolved")
                continue
            if operator == "::":
                self.consume()
                member = self.consume()
                if member.kind != "name":
                    raise _Unsupported("unsupported_method_reference")
                left = {"op": "method_reference", "receiver": left, "name": member.value,
                        "resolution": "syntax_only", "sourceRange":{"charStart":token.start,"charEnd":member.end}}
                self.reasons.add("method_reference_target_unresolved")
                continue
            if operator == "->" and minimum <= 0:
                self.consume()
                body_start = self.index
                left = {"op": "lambda", "parameters": [left],
                        "body": self.expression(0, depth + 1), "execution": "not_observed"}
                left["sourceRange"] = {"charStart":token.start,"charEnd":self.tokens[self.index-1].end}
                left["parameterRanges"] = [{"charStart":token.start,"charEnd":token.end}]
                self.lambda_scopes.append((left, self.tokens[body_start].start, self.tokens[self.index - 1].end))
                self.reasons.add("lambda_execution_unresolved")
                continue
            if operator in {"++", "--"}:
                self.consume()
                left = {"op": "update", "operator": operator, "operand": left, "position": "postfix"}
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
            if operator == "instanceof":
                # Preserve the previous RHS recursion-entry budget. This is
                # not a bound on the final left-folded AST's child-edge depth.
                if self.base_depth + depth + 1 > MAX_EXPRESSION_DEPTH:
                    raise _Unsupported("expression_depth_exceeded")
                right, self.index, extended = _instanceof_type_syntax(self.tokens, self.index)
                if self.peek() == "(":
                    raise _Unsupported("record_pattern_semantics_unresolved")
                if self.index < len(self.tokens) and self.tokens[self.index].kind == "name":
                    binding = self.consume()
                    if not _NAME.fullmatch(binding.value) or binding.value in _JAVA_RESERVED_NAMES:
                        raise _Unsupported("instanceof_pattern_binding_unsupported")
                    right = {"op": "type_pattern", "type": right, "binding": binding.value}
                    if extended: right["scopeResolution"] = "flow_scope_unresolved"
                if extended: self.reasons.add("instanceof_runtime_unresolved")
            else:
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
                      *, max_fragments: int = MAX_FRAGMENTS, java_type_context=None, literal_review=None,
                      defer_external_dependencies: bool = False, max_source_relations: int = 40_000,
                      source_relation_context=None) -> dict[str, Any]:
    """Return a bounded fragment inventory; never reread source or evaluate it.

    `represented` means the restricted expression grammar retained the syntax,
    not complete policy semantics. `partial` preserves calls as syntax with an
    unresolved-semantics reason. Unsupported values are absent, not guessed.
    """
    if (not isinstance(source, str) or not isinstance(path, str) or not path or len(path) > 1024
            or PurePosixPath(path).is_absolute() or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path or ":" in path or "\x00" in path
            or not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
            or type(max_fragments) is not int or not 1 <= max_fragments <= MAX_FRAGMENTS
            or type(defer_external_dependencies) is not bool or type(max_source_relations) is not int
            or not 0 <= max_source_relations <= 40_000
            or (source_relation_context is not None and type(source_relation_context) is not SourceRelationBuildContext)):
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
    if java_type_context is not None and (not isinstance(java_type_context, dict) or java_type_context.get("path") != path
            or java_type_context.get("sourceDigest") != source_digest
            or not callable(java_type_context.get("resolve")) or not callable(java_type_context.get("callResult"))):
        raise SemanticError("java_type_context_binding_mismatch")
    if literal_review is not None and any(not callable(getattr(literal_review, name, None)) for name in ("bind_source", "reject", "coverage")):
        raise SemanticError("literal_review_binding_invalid")
    literal_binding = literal_review.bind_source(path, source, source_digest) if literal_review is not None else None
    coverage = {"scope": "detected_java_expression_fragments", "detectedFragments": 0,
                "representedFragments": 0, "partialFragments": 0, "unsupportedFragments": 0,
                "recordedFragments": 0, "inventoryComplete": False, "semanticComplete": False,
                "wholePolicyDenominator": "UNKNOWN", "businessPolicyComplete": False,
                "complete": False, "reasons": []}
    result = {"schemaVersion": 1, "extractorVersion": EXTRACTOR_VERSION, "path": path,
              "sourceDigest": source_digest, "language": language, "sourceLength": len(source),
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
        tokens = _tokens(source, literal_binding)
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
    local_type_candidates: dict[str, dict[str, Any]] = {}
    body_references: dict[int, tuple[int, dict[str, Any]]] = {}
    lambda_regions = []
    fragment_lambda_nodes = {}
    fragment_call_nodes = {}
    token_starts = [token.start for token in tokens]
    scopes: dict[int, tuple[int, ...]] = {}
    scope_stack: list[int] = []
    for index, token in enumerate(tokens):
        scopes[index] = tuple(scope_stack)
        if token.value == "{":
            scope_stack.append(index)
        elif token.value == "}" and scope_stack:
            scope_stack.pop()
    type_declarations = []
    type_bodies = set()
    for index, value in enumerate(values[:-1]):
        if value not in {"class", "interface", "enum", "record"} or tokens[index + 1].kind != "name":
            continue
        cursor = index + 2
        while cursor < len(tokens) and values[cursor] not in {"{", ";", "="}:
            if cursor in parens and values[cursor] == "(":
                cursor = parens[cursor] + 1
            else:
                cursor += 1
        if cursor not in braces:
            continue
        type_bodies.add(cursor)
        type_declarations.append({"name": values[index + 1], "kind": value, "scope": scopes[index],
                                  "position": index, "body": cursor})

    def mask_value_terminals(selected):
        masked = []
        for token in selected:
            if (token.kind == "reviewed_literal" and token.payload.get("type") == "string" and token.payload.get("value") == ""
                    and token.payload.get("literalReview", {}).get("emptySensitiveMarker") is True):
                masked.append(token)
                continue
            kind = ("number" if token.kind == "number" else "quoted" if token.literal_id is not None
                    else "boolean" if token.value in {"true", "false"} else None)
            if kind:
                occurrence = _id("masked_occurrence", path, source_digest, token.start, token.end).replace("semantic:", "literal-occurrence:", 1)
                masked.append(_Token("", token.start, token.end, "masked_value", occurrence,
                    {"op": "masked_value", "literalKind": kind, "reason": "sensitive_value_redacted",
                     "opaqueOccurrenceId": occurrence, "identityScope": "source_occurrence",
                     "sourceRange": {"charStart": token.start, "charEnd": token.end}}))
            else:
                masked.append(token)
        return masked

    def prepare_expression_tokens(expression_tokens, sensitive_context=False, admitted_requests=None):
        admitted_requests = admitted_requests if admitted_requests is not None else []
        prepared = []
        position = 0
        while position < len(expression_tokens):
            token = expression_tokens[position]
            body = body_references.get(token.start)
            if body:
                closing_offset, reference = body
                prepared.append(_Token("", token.start, closing_offset, "body_reference", payload=reference))
                position += 1
                while position < len(expression_tokens) and expression_tokens[position].start < closing_offset:
                    position += 1
            else:
                prepared.append(token); position += 1
        sensitive_context = sensitive_context or any(token.kind == "name" and _SENSITIVE.search(token.value) for token in prepared)
        if literal_binding:
            for token_index, token in enumerate(prepared):
                if token.literal_id is not None:
                    admission = literal_binding.admit(token.start, token.end, sensitive_context=sensitive_context, allow_reviewed_empty=True)
                    if admission["status"] == "admitted":
                        admitted_requests.append(admission["requestIndex"])
                        prepared[token_index] = _Token("", token.start, token.end, "reviewed_literal", token.literal_id,
                            {"op": "literal", "type": admission["literalType"], "value": admission["value"],
                             "opaqueOccurrenceId": admission["opaqueOccurrenceId"],
                             "literalReview": {**admission["review"], "requestIndex": admission["requestIndex"]}})
                    else:
                        # An active occurrence review governs quoted
                        # numerics too: the legacy decimal shortcut cannot
                        # bypass a rejected or unreviewed token.
                        prepared[token_index] = _Token("", token.start, token.end, "redacted_literal", token.literal_id)
        return (mask_value_terminals(prepared) if sensitive_context else prepared), sensitive_context

    def add_fragment(category: str, start: int, end: int, expression_tokens: list[_Token], *,
            name: str | None = None, declared_type: str | None = None,
            reason: str | None = None, operator: str | None = None,
            structure: dict[str, Any] | None = None, structural_context=False) -> dict[str, Any] | None:
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
                    "sourceRange": {"charStart": tokens[start].start, "charEnd": tokens[end].end},
                    "representationStatus": "unsupported", "expression": None,
                    "references": [], "unsupportedReasons": [],
                    "unit": {"status": "UNKNOWN", "reason": "unit_not_explicitly_bound"},
                    "businessMeaningVerified": False, "runtimeStatus": "not_observed",
                    "extractorVersion": EXTRACTOR_VERSION}
        opaque = sorted({token.literal_id for token in expression_tokens if token.kind in {"decimal_string", "redacted_literal"} and token.literal_id is not None})
        if opaque:
            fragment["literalIdentities"] = {"scope": "source_occurrence" if literal_binding else "same_source_raw_literal_spelling", "opaqueIds": opaque,
                "equality": "no_cross_occurrence_equality_claim" if literal_binding else "same_raw_spelling_only_escape_equivalence_not_resolved"}
        if name and _NAME.fullmatch(name):
            fragment["name"] = name
        if declared_type:
            fragment["declaredType"] = declared_type
        if operator:
            fragment["assignmentOperator"] = operator
        admitted_requests = []
        sensitive_context = bool(structural_context or (name and _SENSITIVE.search(name)) or (declared_type and _SENSITIVE.search(declared_type)))
        try:
            if reason:
                raise _Unsupported(reason)
            prepared, sensitive_context = prepare_expression_tokens(expression_tokens, sensitive_context, admitted_requests)
            if sensitive_context:
                fragment["structuralOnly"] = True
                fragment["structureScope"] = "source_structure_with_masked_value_terminals"
                fragment["sourceRange"] = {"charStart": tokens[start].start, "charEnd": tokens[end].end}
                identities = [token.literal_id for token in prepared if token.kind == "masked_value"]
                fragment.pop("literalIdentities", None)
                if identities:
                    fragment["literalIdentities"] = {"scope": "source_occurrence", "opaqueIds": sorted(set(identities)),
                        "equality": "no_cross_occurrence_equality_claim"}
            parser = _Expression(prepared, decimal_bound, structural_only=sensitive_context)
            if sensitive_context:
                parser.reasons.add("sensitive_value_redacted")
            if structure is None and declared_type and "[]" in declared_type and prepared and prepared[0].value == "{":
                expression = parser.array_initializer(0)
                if parser.index != len(prepared):
                    raise _Unsupported("unsupported_array_initializer_syntax")
                parser.reasons.add("array_initialization_not_evaluated")
            else:
                expression = structure if structure is not None else parser.parse()
            if expression.get("op") == "redacted":
                raise _Unsupported("string_or_character_value_redacted")
            fragment["expression"] = expression
            fragment["representationStatus"] = "partial" if parser.reasons else "represented"
            fragment["unsupportedReasons"] = sorted(parser.reasons)
            fragment["references"] = [{"name": ref, "resolution": "unresolved", "declarations": []}
                                      for ref in _walk_references(expression)]
            fragment_lambda_nodes[fragment["id"]] = {id(node): (first, last) for node, first, last in parser.lambda_scopes}
            lambda_regions.extend((first, last) for _, first, last in parser.lambda_scopes)
            call_offsets, pending = {}, [expression]
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    if item.get("op") == "call":
                        call_offsets[id(item)] = item.get("sourceInvocationOffset")
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
            fragment_call_nodes[fragment["id"]] = call_offsets
        except (_Unsupported, RecursionError) as error:
            fragment["unsupportedReasons"] = [error.reason if isinstance(error, _Unsupported) else "expression_depth_exceeded"]
            for request in admitted_requests:
                literal_review.reject(request, "fragment_redacted")
        # No input-derived payload can bypass configured privacy enforcement.
        try:
            privacy_guard.ensure_public_safe(fragment)
        except privacy_guard.PrivacyError:
            for request in admitted_requests:
                literal_review.reject(request, "privacy_denied")
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
                                 "position": start, "field": category != "local_declaration",
                                 "declaredType": declared_type})
        return fragment

    flow_nodes, methods = policy_java_flow.scan(tokens, parens, braces)
    def split_declarations(nodes):
        expanded = []
        for node in nodes:
            parts = _declarators(tokens, node["start"], node["expressionEnd"]) if node["kind"] == "statement" else []
            if len(parts) <= 1:
                expanded.append(node)
                continue
            for part in parts:
                expanded.append({**node, "start": part["start"], "end": part["end"] - 1,
                                 "expressionStart": part["start"], "expressionEnd": part["end"],
                                 "declarator": part,
                                 "declarationGroup": span(tokens[node["start"]].start, tokens[node["end"]].end)})
        return expanded
    flow_nodes = split_declarations(flow_nodes)
    # Annotation arguments are declaration syntax, not method invocations or
    # framework routes. Each argument has its own bounded source fragment.
    annotations = []
    for index, value in enumerate(values[:-1]):
        if value != "@" or values[index + 1] == "interface" or tokens[index + 1].kind != "name":
            continue
        cursor = index + 2
        annotation_name = values[index + 1]
        while cursor + 1 < len(tokens) and values[cursor] == "." and tokens[cursor + 1].kind == "name":
            annotation_name += "." + values[cursor + 1]
            cursor += 2
        if cursor not in parens or values[cursor] != "(":
            continue
        closing = parens[cursor]
        nested = next((item for item in reversed(annotations) if item["start"] < index < closing < item["end"]), None)
        descriptor = {"start": index, "end": closing, "name": annotation_name, "typeStart": index + 1, "typeEnd": cursor - 1}
        annotations.append(descriptor)
        context_end = closing + 1
        while context_end < len(tokens) and values[context_end] not in {";", "{", "}", "="}:
            if values[context_end] == "(" and context_end in parens:
                context_end = parens[context_end] + 1
            else:
                context_end += 1
        # A nested annotation value has no independent declaration boundary.
        # Its privacy interval follows the outermost annotation's complete
        # balanced prefix, including array delimiters and later annotations.
        descriptor["privacyStart"] = nested["privacyStart"] if nested else index
        descriptor["contextEnd"] = max(context_end, nested["contextEnd"]) if nested else context_end
        context_end = descriptor["contextEnd"]
        enclosing = [node for node in flow_nodes if node["start"] <= index <= closing <= node["end"]]
        parent = min(enclosing, key=lambda node: node["end"] - node["start"]) if enclosing else None
        target = (java_type_context.get("annotationTarget", lambda *_: {"resolution": "UNKNOWN", "reason": "annotation_target_not_proven"})(tokens[index].start)
                  if java_type_context and not nested else {"resolution": "UNKNOWN", "reason": "nested_annotation_target" if nested else "java_index_not_supplied"})
        context_names = [method["name"] for method in methods.values() if method["start"] <= index < method["parameterEnd"]]
        context_names += [decl["name"] for decl in type_declarations if decl["position"] <= index < decl["body"]]
        if java_type_context:
            context_names += java_type_context.get("annotationContext", lambda *_: [])(tokens[index].start)
        for argument_index, (first, last) in enumerate(_split(tokens, cursor + 1, closing, ",", angles=False)):
            eq = _top_level_operator(tokens, first, last, {"="})
            valid_key = eq == first + 1 and tokens[first].kind == "name" if eq is not None else True
            key = values[first] if eq is not None and valid_key else "value" if eq is None else None
            flow_nodes.append({"kind": "annotation_argument", "start": first, "end": last - 1,
                "expressionStart": eq + 1 if eq is not None else first, "expressionEnd": last,
                "contexts": list(parent["contexts"]) if parent else [], "owner": parent["owner"] if parent else None,
                "sequence": 0, "annotation": descriptor, "annotationKey": key, "annotationArgumentIndex": argument_index,
                "annotationTarget": target, "annotationContextEnd": context_end,
                "annotationContextNames": context_names, "nestedAnnotation": nested})
    annotation_offsets = set()
    for node in flow_nodes:
        if node.get("annotation"):
            descriptor = node["annotation"]
            annotation_offsets.update((tokens[node["start"]].start, tokens[node["end"]].end,
                tokens[descriptor["start"]].start, tokens[descriptor["end"]].end,
                tokens[descriptor["typeStart"]].start, tokens[descriptor["typeEnd"]].end))
    annotation_byte_offsets = {}
    char_cursor = byte_cursor = 0
    for offset in sorted(annotation_offsets):
        byte_cursor += len(source[char_cursor:offset].encode("utf-8"))
        annotation_byte_offsets[offset] = byte_cursor
        char_cursor = offset

    def annotation_range(left, right):
        return {"charStart": left, "charEnd": right,
                "byteStart": annotation_byte_offsets[left], "byteEnd": annotation_byte_offsets[right]}
    enum_class_bodies = {node["constantBody"] for node in flow_nodes if node["kind"] == "enum_constant" and node.get("constantBody") is not None}
    # Deferred lambda/switch bodies are separate bounded records. Compress only
    # syntactically delimited bodies, never truncate expressions or raise their
    # token limit. Child records retain their exact source ranges and contexts.
    body_nodes = []
    body_parent_nodes = {}
    for opening, closing in sorted(braces.items()):
        if opening < 1:
            continue
        body_kind = ("enum_constant_subclass" if opening in enum_class_bodies else
                     "lambda_or_switch_arm" if values[opening - 1] == "->" else None)
        if values[opening - 1] == ")" and opening - 1 in parens:
            constructor_open = parens[opening - 1]
            cursor = constructor_open - 1
            while cursor >= max(0, constructor_open - 64) and (tokens[cursor].kind == "name" or values[cursor] in {".", "<", ">", ">>", ">>>", ",", "?", "[", "]"}):
                if values[cursor] == "new":
                    body_kind = "anonymous_class"
                    break
                cursor -= 1
        if body_kind is None:
            continue
        parents = [node for node in flow_nodes + body_nodes if node["expressionStart"] <= opening < closing < node["expressionEnd"]]
        if not parents:
            continue
        parent = min(parents, key=lambda node: node["end"] - node["start"])
        body_parent_nodes[opening] = parent
        ancestor_bodies = [node for node in body_nodes if node["kind"] == "embedded_body" and node["start"] < opening < closing < node["end"]]
        inherited = list(parent["contexts"])
        for ancestor in ancestor_bodies:
            inherited.append({"start": ancestor["start"], "end": ancestor["end"], "kind": "embedded_body", "branch": "deferred_body"})
        unique_contexts = {}
        for context in inherited:
            unique_contexts.setdefault((context["start"], context["end"], context["kind"], context["branch"], context.get("handlerIndex")), context)
        inherited = list(unique_contexts.values())
        body_id = _id(path, source_digest, "control_boundary", tokens[opening].start, tokens[closing].end)
        body_references[tokens[opening].start] = (tokens[closing].end,
            {"op": "body_reference", "bodyId": body_id, "span": span(tokens[opening].start, tokens[closing].end),
             "resolution": "source_body_records", "bodyKind": body_kind, "execution": "not_observed"})
        owner = {"name": None, "start": opening, "end": closing, "body": opening,
                 "parameterStart": opening, "parameterEnd": opening, "bodyId": body_id}
        if body_kind in {"anonymous_class", "enum_constant_subclass"}:
            type_bodies.add(opening)
            children, _ = policy_java_flow.scan(tokens, parens, braces, member_range=(opening + 1, closing))
            existing_children = [node for node in flow_nodes if opening < node["start"] <= node["end"] < closing]
            for child in existing_children:
                child["contexts"] = inherited + [{"start": opening, "end": closing, "kind": "embedded_body", "branch": "member_declaration"}] + child["contexts"]
        else:
            children, _ = policy_java_flow.scan(tokens, parens, braces, body_range=(opening + 1, closing))
        children = split_declarations(children)
        body_node = {"kind": "embedded_body", "start": opening, "end": closing,
                     "expressionStart": opening, "expressionEnd": opening, "contexts": inherited,
                     "owner": parent["owner"], "sequence": 0, "memberCount": len(children), "bodyKind": body_kind}
        body_nodes.append(body_node)
        for child in children:
            child["contexts"] = inherited + [{"start": opening, "end": closing, "kind": "embedded_body", "branch": "deferred_body"}] + child["contexts"]
            if body_kind not in {"anonymous_class", "enum_constant_subclass"}:
                child["owner"] = owner
        body_nodes.extend(children)
    flow_nodes.extend(body_nodes)
    flow_nodes.sort(key=lambda node: (node["start"], node["end"]))
    for index, node in enumerate(flow_nodes):
        node["sequence"] = index
    for node in flow_nodes:
        if node["kind"] == "embedded_body":
            node["memberCount"] = sum(any(c["kind"] == "embedded_body" and c["start"] == node["start"] for c in other["contexts"]) for other in flow_nodes)
    method_bodies = set(methods)
    named_type_bodies = {decl["body"]: decl for decl in type_declarations}

    def local_initializer_owner(position, node_owner):
        scope = scopes[position]
        type_scope = [body for body in scope if body in type_bodies]
        if (not type_scope or any(body not in named_type_bodies for body in type_scope)
                or any(body not in type_bodies for body in scopes[type_scope[-1]])):
            return None
        # A named member type is supported; a type inside a callable/block,
        # anonymous body, lambda body or unidentified callable is not.
        bodies = [body for body in scope if body in methods]
        if len(bodies) != 1:
            return None
        body = bodies[0]
        method = methods[body]
        if (node_owner != method or scopes[body] != scopes[type_scope[-1]] + (type_scope[-1],)
                or not java_type_context):
            return None
        proof = java_type_context.get("lexicalCallableOwner", lambda *_: None)(tokens[position].start)
        if (not proof or proof.get("typeBodyRange") != {"charStart": tokens[type_scope[-1]].start, "charEnd": tokens[braces[type_scope[-1]]].end}
                or proof.get("callableBodyRange") != {"charStart": tokens[body].start, "charEnd": tokens[braces[body]].end}):
            return None
        return proof

    for following, method in methods.items():
        for first, last in _split(tokens, method["parameterStart"], method["parameterEnd"], ","):
            names = [index for index in range(first, last) if tokens[index].kind == "name"]
            if len(names) >= 2:
                idx = names[-1]
                declarations.append({"name": values[idx], "id": _id(path, source_digest, "parameter", tokens[idx].start),
                                     "span": span(tokens[idx].start, tokens[idx].end), "sourceDigest": source_digest,
                                     "scope": scopes[following] + (following,), "position": following,
                                     "field": False, "parameter": True, "declaredType": "".join(values[first:idx])})

    # These binders are tracked conservatively by source range. Until every
    # nested reference carries its own expression scope, they prevent a false
    # binding to an outer field instead of pretending that flattened name lists
    # are an exact Java symbol table.
    scoped_binders = []
    pattern_scope_gaps = []
    def remember_binder(name_index, first, last, kind):
        if name_index < 0 or name_index >= len(tokens) or tokens[name_index].kind != "name":
            return
        scoped_binders.append({"name": values[name_index], "start": first, "end": last, "kind": kind,
                               "span": span(tokens[name_index].start, tokens[name_index].end)})

    for node in flow_nodes:
        if node["kind"] == "catch":
            names = [i for i in range(node["expressionStart"], node["expressionEnd"]) if tokens[i].kind == "name"]
            if names:
                remember_binder(names[-1], node["start"], node.get("bodyEnd", node["end"] + 1), "catch_parameter")
        elif node["kind"] == "try" and node.get("resources"):
            for first, last in _split(tokens, node["expressionStart"], node["expressionEnd"], ";"):
                assignment = _top_level_operator(tokens, first, last, {"="})
                if assignment is not None:
                    names = [i for i in range(first, assignment) if tokens[i].kind == "name" and values[i] not in _MODIFIERS]
                    if len(names) >= 2:
                        remember_binder(names[-1], node["start"], node.get("bodyEnd", node["end"] + 1), "resource_local")
        elif node.get("controlKind") == "for":
            first, last = node["expressionStart"], node["expressionEnd"]
            header_end = _top_level_operator(tokens, first, last, {";", ":"})
            header_end = last if header_end is None else header_end
            init_end = _top_level_operator(tokens, first, header_end, {"="})
            init_end = header_end if init_end is None else init_end
            names = [i for i in range(first, init_end) if tokens[i].kind == "name" and values[i] not in _MODIFIERS]
            if header_end < last and values[header_end] == ":":
                # JLS 6.3: an enhanced-for variable is in scope only in the
                # contained statement, not its iterable expression.
                if len(names) >= 2:
                    idx = names[-1]
                    remember_binder(idx, node["end"] + 1, node.get("bodyEnd", node["end"] + 1), "enhanced_for_local")
                    scoped_binders[-1].update(declaredType="".join(v for v in values[first:idx] if v != "final"),
                        declarationPosition=idx, loopStart=node["start"],
                        receiverScope=next((tuple(scopes[node["start"]][:i + 1]) for i in range(len(scopes[node["start"]]) - 1, -1, -1)
                            if scopes[node["start"]][i] in type_bodies), ()))
                continue
            if len(names) >= 2:
                remember_binder(names[-1], node["start"], node.get("bodyEnd", node["end"] + 1), "for_local")
            for part in _declarators(tokens, first, header_end):
                candidates = [i for i in range(part["start"], part["end"]) if values[i] == part["name"]]
                if candidates:
                    remember_binder(candidates[0], node["start"], node.get("bodyEnd", node["end"] + 1), "for_local")
        elif node["kind"] == "embedded_body" and node.get("bodyKind") == "lambda_or_switch_arm":
            arrow = node["start"] - 1
            if arrow > 0 and values[arrow - 1] == ")" and arrow - 1 in parens:
                opening = parens[arrow - 1]
                for first, last in _split(tokens, opening + 1, arrow - 1, ","):
                    names = [i for i in range(first, last) if tokens[i].kind == "name" and values[i] not in _MODIFIERS]
                    if names:
                        remember_binder(names[-1], node["start"], node["end"], "lambda_parameter")
            elif arrow > 0 and tokens[arrow - 1].kind == "name":
                cursor = arrow - 2
                while cursor >= 0 and values[cursor] not in {";", "{", "}", "(", "=", ",", "case", "default"}:
                    cursor -= 1
                if cursor < 0 or values[cursor] not in {"case", "default"}:
                    remember_binder(arrow - 1, node["start"], node["end"], "lambda_parameter")

    def pattern_owner(position):
        candidates = []
        for first, last in lambda_regions:
            if first <= tokens[position].start < last:
                opening = bisect.bisect_left(token_starts, first)
                closing = bisect.bisect_left(token_starts, last)
                if (opening < closing and tokens[opening].start == first
                        and tokens[closing - 1].end == last):
                    candidates.append((opening, closing))
        for node in body_nodes:
            if (node["kind"] == "embedded_body" and node.get("bodyKind") == "lambda_or_switch_arm"
                    and node["start"] < position < node["end"]):
                candidates.append((node["start"], node["end"] + 1))
        enclosing = [method for method in methods.values() if method["body"] < position < method["end"]]
        candidates.extend((method["start"], method["end"]) for method in enclosing)
        if java_type_context:
            proof = java_type_context.get("lexicalCallableOwner", lambda *_: None)(tokens[position].start)
            body = proof.get("callableBodyRange") if isinstance(proof, dict) else None
            if isinstance(body, dict) and set(body) == {"charStart", "charEnd"}:
                indexed_bodies = [opening for opening, closing in braces.items()
                    if body == {"charStart": tokens[opening].start, "charEnd": tokens[closing].end}
                    and opening < position < closing]
                if len(indexed_bodies) == 1:
                    opening = indexed_bodies[0]
                    # Keep the indexed callable alongside smaller parser and
                    # deferred-body candidates, rather than preferring it.
                    candidates.append((opening, braces[opening] + 1))
        # A failed selected expression cannot justify extending an uncertain
        # lambda name into the enclosing method. Its own interpretation is
        # already withheld; preserve a local uncertainty frontier instead.
        failed = [fragment for fragment in result["fragments"]
            if fragment.get("expression") is None
            and fragment["sourceRange"]["charStart"] <= tokens[position].start < fragment["sourceRange"]["charEnd"]]
        for fragment in sorted(failed, key=lambda item: item["sourceRange"]["charEnd"] - item["sourceRange"]["charStart"]):
            first = bisect.bisect_left(token_starts, fragment["sourceRange"]["charStart"])
            last = bisect.bisect_left(token_starts, fragment["sourceRange"]["charEnd"])
            if "->" in values[first:position]:
                return first, last, "pattern_scope_owner_unresolved"
        if candidates:
            first, last = min(candidates, key=lambda item: item[1] - item[0])
            return first, last, None
        blocks = [opening for opening in scopes[position] if opening not in type_bodies and opening in braces]
        if blocks:
            opening = blocks[-1]
            return opening, braces[opening] + 1, None
        expressions = [node for node in flow_nodes if node["expressionStart"] <= position < node["expressionEnd"]]
        if expressions:
            node = min(expressions, key=lambda node: node["end"] - node["start"])
            return node["start"], node["end"] + 1, None
        # No callable/block/recorded expression is established. Keep the
        # uncertainty inside this lexical statement, never the entire file or
        # named type. All namespace enrichment in that region is withheld.
        first = position
        while first > 0 and values[first - 1] not in {";", "{", "}"}:
            first -= 1
        last = position + 1
        while last < len(tokens) and values[last] not in {";", "{", "}"}:
            last += 1
        return first, min(last + 1, len(tokens)), "pattern_scope_owner_unresolved"

    def lambda_names(expression):
        names = set()
        pending = [expression]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if item.get("op") == "lambda":
                    for parameter in item.get("parameters", []):
                        if isinstance(parameter, dict) and parameter.get("op") == "reference":
                            names.add(parameter["name"])
                        elif isinstance(parameter, list) and parameter:
                            names.add(parameter[-1])
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return names

    def lambda_pattern_names(expression):
        # Aggregate reference rows have no per-occurrence lexical location.
        # Keep a mixed outer/lambda name unresolved there; API lookups below
        # use their actual source context instead of this aggregate fence.
        names = set()
        pending = [(expression, False)]
        while pending:
            item, nested = pending.pop()
            if isinstance(item, dict):
                nested = nested or item.get("op") == "lambda"
                if nested and item.get("op") == "type_pattern":
                    names.add(item["binding"])
                pending.extend((value, nested) for value in item.values())
            elif isinstance(item, list):
                pending.extend((value, nested) for value in item)
        return names

    flow_fragments = {}
    emitted_nodes = []
    enhanced_loops = {}
    sensitive_type_bodies = {decl["body"] for decl in type_declarations if _SENSITIVE.search(decl["name"])}
    direct_sensitivity = {}
    def source_sensitive(node):
        identity = id(node)
        if identity not in direct_sensitivity:
            start, end = node["start"], node["end"]
            ranges = [(start, end + 1)] + [(c["start"], c["end"] + 1) for c in node["contexts"] if c["kind"] != "embedded_body"]
            if node.get("annotation"):
                ranges.append((node["annotation"]["privacyStart"], node["annotationContextEnd"]))
                if node.get("nestedAnnotation"):
                    ranges.append((node["nestedAnnotation"]["start"], node["nestedAnnotation"]["end"] + 1))
            direct_sensitivity[identity] = bool(
                any(tokens[i].kind == "name" and _SENSITIVE.search(values[i])
                    for first, last in ranges for i in range(first, min(last, len(tokens))))
                or any(body in sensitive_type_bodies for body in scopes[start])
                or _SENSITIVE.search(node.get("enumName", ""))
                or any(_SENSITIVE.search(name) for name in node.get("annotationContextNames", []))
                or _SENSITIVE.search(node.get("annotationTarget", {}).get("name", ""))
                or (node.get("owner") and _SENSITIVE.search(node["owner"].get("name") or "")))
        return direct_sensitivity[identity]

    # Partitioning deferred bodies must preserve the parent expression's
    # privacy context. Source order puts every enclosing body before nested
    # bodies, so this closure is bounded and needs no recursion or execution.
    sensitive_bodies = {}
    for opening, parent in sorted(body_parent_nodes.items()):
        sensitive_bodies[opening] = source_sensitive(parent) or any(
            sensitive_bodies.get(context["start"], True) for context in parent["contexts"]
            if context["kind"] == "embedded_body")

    for node in flow_nodes:
        start, end = node["start"], node["end"]
        exstart, exend = node["expressionStart"], node["expressionEnd"]
        kind = node["kind"]
        node_sensitive = (source_sensitive(node)
            or (kind == "embedded_body" and sensitive_bodies.get(start, True))
            or any(sensitive_bodies.get(context["start"], True) for context in node["contexts"]
                   if context["kind"] == "embedded_body"))

        def add(*args, **kwargs):
            return add_fragment(*args, structural_context=node_sensitive, **kwargs)

        fragment = None
        expression_tokens = tokens[exstart:exend]
        if kind == "annotation_argument":
            def annotation_value(selected, depth=0):
                if depth > MAX_EXPRESSION_DEPTH or len(selected) > MAX_EXPRESSION_TOKENS:
                    raise _Unsupported("annotation_argument_budget_exceeded")
                if not selected:
                    raise _Unsupported("missing_annotation_argument")
                if any(token.value == "@" for token in selected):
                    raise _Unsupported("nested_annotation_value_unsupported")
                if selected[0].value == "{" and selected[-1].value == "}":
                    elements, reasons = [], set()
                    for first, last in _split(selected, 1, len(selected) - 1, ",", angles=False):
                        element, flags = annotation_value(selected[first:last], depth + 1)
                        elements.append(element); reasons.update(flags)
                    return {"op": "annotation_array", "elements": elements, "meaning": "source_element_order"}, reasons
                parser = _Expression(prepare_expression_tokens(selected, node_sensitive)[0], decimal_bound, structural_only=node_sensitive)
                return parser.parse(), parser.reasons

            try:
                if node["annotationKey"] is None:
                    raise _Unsupported("annotation_argument_key_unsupported")
                expression, reasons = annotation_value(expression_tokens)
                fragment = add("annotation_argument", start, end, [], structure=expression)
                if fragment:
                    fragment["unsupportedReasons"] = sorted(set(fragment["unsupportedReasons"]) | reasons | {"annotation_meaning_not_evaluated"})
                    fragment["representationStatus"] = "partial"
            except _Unsupported as error:
                fragment = add("annotation_argument", start, end, [], reason=error.reason)
            if fragment:
                descriptor = node["annotation"]
                left, right = tokens[start].start, tokens[end].end
                fragment["annotation"] = {"name": descriptor["name"], "argumentKey": node["annotationKey"],
                    "argumentIndex": node["annotationArgumentIndex"], "target": node["annotationTarget"],
                    "span": span(tokens[descriptor["start"]].start, tokens[descriptor["end"]].end),
                    "sourceRange": annotation_range(tokens[descriptor["start"]].start, tokens[descriptor["end"]].end),
                    "typeRange": annotation_range(tokens[descriptor["typeStart"]].start, tokens[descriptor["typeEnd"]].end),
                    "argumentRange": annotation_range(left, right),
                    "runtimeMeaning": "UNKNOWN", "attributeDeclaration": "UNKNOWN"}
                if java_type_context and not fragment.get("structuralOnly"):
                    resolved = java_type_context["resolve"](descriptor["name"], tokens[descriptor["start"]].start)
                    if resolved:
                        fragment["annotation"]["typeBinding"] = resolved
                if node["nestedAnnotation"]:
                    ancestor = node["nestedAnnotation"]
                    fragment["annotation"]["parentAnnotationSpan"] = span(tokens[ancestor["start"]].start, tokens[ancestor["end"]].end)
        elif kind == "embedded_body":
            fragment = add("control_boundary", start, end, [], structure={"op": "embedded_body",
                           "memberCount": node["memberCount"], "bodyKind": node["bodyKind"], "execution": "not_observed",
                           "membership": "detected_descendant_fragments_with_body_context"})
        elif kind == "enum_constant":
            name = values[node["nameIndex"]]
            fragment = add("enum_constant", start, end, tokens[node["nameIndex"]:node["argumentEnd"]], name=name)
            if fragment and fragment.get("expression") is not None:
                parsed = fragment["expression"]
                args = parsed.get("arguments", []) if parsed.get("op") == "call" else []
                fragment["expression"] = {"op": "enum_constant", "enumType": node["enumName"], "arguments": args,
                    "initialization": "source_argument_order_only", "runtimeValue": "UNKNOWN"}
                fragment["references"] = [{"name": ref, "resolution": "unresolved", "declarations": []}
                                          for ref in _walk_references(fragment["expression"])]
                reasons = set(fragment["unsupportedReasons"]) - {"call_semantics_unresolved"}
                reasons.add("enum_constructor_semantics_unresolved")
                if node.get("constantBody") is not None:
                    body = body_references.get(tokens[node["constantBody"]].start)
                    fragment["expression"]["constantBody"] = body[1] if body else {
                        "op": "unresolved", "reason": "enum_constant_subclass_body_not_recorded",
                        "span": span(tokens[node["constantBody"]].start, tokens[braces[node["constantBody"]]].end)}
                    reasons.add("enum_constant_subclass_effects_unresolved")
                fragment.update(representationStatus="partial", unsupportedReasons=sorted(reasons))
        elif kind == "condition":
            fragment = add("condition", start, end, expression_tokens)
        elif kind in {"return", "throw", "yield"}:
            fragment = add(kind, start, end, expression_tokens,
                           structure={"op": "void"} if not expression_tokens else None)
        elif kind in {"break", "continue"}:
            label = values[exstart] if exstart < exend and tokens[exstart].kind == "name" else None
            fragment = add("control_boundary", start, end, [], structure={"op": "control", "kind": kind, "label": label})
        elif kind in {"else", "try", "finally", "label"}:
            fragment = add("control_boundary", start, end, [],
                           reason="try_resource_semantics_unresolved" if node.get("resources") else None,
                           structure={"op": "control", "kind": kind})
        elif kind == "catch":
            header = [token.value for token in expression_tokens]
            fragment = add("control_boundary", start, end, [], structure={"op": "catch_binding", "declaration": header})
        elif kind == "switch":
            fragment = add("condition", start, end, expression_tokens)
        elif kind == "switch_case":
            labels = []
            reasons = set()
            for first, last in _split(tokens, exstart, exend, ","):
                parser = _Expression(prepare_expression_tokens(tokens[first:last], node_sensitive)[0], decimal_bound, structural_only=node_sensitive)
                try:
                    labels.append(parser.parse())
                    reasons.update(parser.reasons)
                except _Unsupported as error:
                    labels.append({"op": "unresolved", "reason": error.reason})
                    reasons.add(error.reason)
            fragment = add("control_boundary", start, end, [], structure={"op": "switch_labels", "labels": labels,
                "default": node["default"], "style": node["style"]})
            if fragment and reasons:
                fragment.update(representationStatus="partial", unsupportedReasons=sorted(reasons | set(fragment["unsupportedReasons"])))
        elif kind in {"loop", "synchronized"}:
            if node.get("controlKind") in {"while", "synchronized"}:
                fragment = add("condition", start, end, expression_tokens)
            else:
                separator = _top_level_operator(tokens, exstart, exend, {";", ":"})
                if (node.get("controlKind") == "for" and separator is not None and values[separator] == ":"
                        and exstart < separator < exend - 1 and node["bodyStart"] < node["bodyEnd"] <= len(tokens)):
                    header = [t for t in tokens[exstart:separator] if t.value != "final"]
                    simple = (len(header) >= 2 and header[-1].kind == "name" and header[-2].value != "."
                        and all(t.kind == "name" or t.value in {".", "<", ">", ">>", ">>>", "?", "[", "]", ","} for t in header[:-1]))
                    reasons = {"loop_execution_unresolved", "iterator_protocol_not_verified"}
                    requests = []
                    try:
                        prepared, _ = prepare_expression_tokens(tokens[separator + 1:exend], node_sensitive, requests)
                        # This new source path never uses the legacy numeric
                        # string shortcut to disclose an unreviewed literal.
                        prepared = [_Token("", t.start, t.end, "redacted_literal", t.literal_id)
                            if t.kind == "decimal_string" else t for t in prepared]
                        parser = _Expression(prepared, decimal_bound, structural_only=node_sensitive)
                        iterable = parser.parse(); reasons.update(parser.reasons)
                    except (_Unsupported, RecursionError) as error:
                        why = error.reason if isinstance(error, _Unsupported) else "expression_depth_exceeded"
                        iterable = {"op": "unresolved", "reason": why}; reasons.add(why)
                        for request in requests:
                            literal_review.reject(request, "fragment_redacted")
                    body_first, body_end = node["bodyStart"], node["bodyEnd"]
                    body_left, body_right = tokens[body_first].start, tokens[body_end - 1].end
                    body_id = _id(path, source_digest, "loop_body", body_left, body_right).replace("semantic:", "source-body:", 1)
                    variable_id = _id(path, source_digest, "iteration_variable", tokens[exstart].start, tokens[separator - 1].end).replace("semantic:", "source-binding:", 1)
                    variable = {"op": "iteration_variable", "id": variable_id,
                        "binding": "explicit_source_declaration" if simple else "UNKNOWN",
                        "sourceRange": {"charStart": tokens[exstart].start, "charEnd": tokens[separator - 1].end},
                        "value": "UNKNOWN", "scope": "contained_statement_only"}
                    if simple:
                        variable.update(name=header[-1].value, declaredType="".join(t.value for t in header[:-1]),
                            modifiers=["final"] if "final" in values[exstart:separator] else [])
                    else:
                        reasons.add("enhanced_for_declaration_syntax_unsupported")
                    structure = {"op": "enhanced_for", "variable": variable, "iterable": iterable,
                        "iterableSourceRange": {"charStart": tokens[separator + 1].start, "charEnd": tokens[exend - 1].end},
                        "body": {"id": body_id, "definition": "inline_source_range",
                            "path": path, "sourceDigest": source_digest, "span": span(body_left, body_right),
                            "sourceRange": {"charStart": body_left, "charEnd": body_right},
                            "memberLink": "controlFlow.contexts.loopBodyId", "execution": "not_observed"},
                        "iteration": {"count": "UNKNOWN", "traversal": "UNKNOWN", "elementValues": "UNKNOWN",
                            "iterableEvaluation": "not_observed", "arrayElementOrder": "source_initializer_order_only"}}
                    fragment = add("condition", start, end, [], structure=structure)
                    if fragment:
                        fragment.update(representationStatus="partial" if fragment.get("expression") is not None else "unsupported",
                            unsupportedReasons=sorted(reasons | set(fragment["unsupportedReasons"])))
                        enhanced_loops[fragment["id"]] = (node, fragment)
                    if not fragment or fragment.get("expression") is None:
                        for request in requests:
                            literal_review.reject(request, "fragment_redacted")
                else:
                    # Preserve classic/unsupported clauses independently.
                    clauses = []
                    reasons = {"loop_execution_unresolved"}
                    for first, last in _split(tokens, exstart, exend, ";", angles=False):
                        try:
                            parser = _Expression(prepare_expression_tokens(tokens[first:last], node_sensitive)[0], decimal_bound, structural_only=node_sensitive)
                            clauses.append(parser.parse()); reasons.update(parser.reasons)
                        except _Unsupported as error:
                            clauses.append({"op": "unresolved", "reason": error.reason}); reasons.add(error.reason)
                    fragment = add("condition", start, end, [], structure={"op": "loop_header", "kind": node.get("controlKind"), "clauses": clauses})
                    if fragment:
                        fragment.update(representationStatus="partial", unsupportedReasons=sorted(reasons | set(fragment["unsupportedReasons"])))
        elif kind == "unsupported_region":
            fragment = add("control_boundary", start, end, [], reason=node["reason"])
        elif kind == "assert":
            fragment = add("assert", start, end, expression_tokens)
        else:
            eq = _top_level_operator(tokens, start, exend, _ASSIGN)
            lhs_end = eq if eq is not None else exend
            lhs = tokens[start:lhs_end]
            clean = [item for item in lhs if item.value not in _MODIFIERS]
            declaration = (len(clean) >= 2 and clean[-1].kind == "name" and clean[-2].value != "."
                           and all(item.kind == "name" or item.value in {".", "<", ">", ">>", ">>>", "?", "[", "]", ","} for item in clean[:-1]))
            if declaration or node.get("declarator"):
                declarator = node.get("declarator")
                name = declarator["name"] if declarator else clean[-1].value
                dtype = declarator["declaredType"] if declarator else "".join(item.value for item in clean[:-1])
                is_local = node["owner"] is not None
                is_final = declarator["final"] if declarator else "final" in values[start:lhs_end]
                category = "local_declaration" if is_local else "constant" if is_final else "field"
                fragment = add(category, start, end, tokens[eq + 1:exend] if eq is not None else [], name=name,
                    declared_type=dtype, reason="initializer_absent" if eq is None else None,
                    operator=values[eq] if eq is not None else None)
                if fragment and eq is not None and values[eq] != "=":
                    fragment.update(representationStatus="partial" if fragment.get("expression") else "unsupported",
                        unsupportedReasons=sorted(set(fragment["unsupportedReasons"]) | {"compound_assignment_in_declaration_not_valid"}))
                if fragment and node.get("declarationGroup"):
                    fragment["declarationGroupSpan"] = node["declarationGroup"]
                if fragment and category == "local_declaration" and dtype == "var":
                    # The initializer's existing static type is the only input
                    # to local inference. This does not evaluate the initializer.
                    reason = "initializer_type_not_proven"
                    body_scope = scopes[start][-1] if scopes[start] else None
                    lexical_owner = local_initializer_owner(start, node.get("owner"))
                    if node.get("declarationGroup"):
                        reason = "var_multiple_declarators_unsupported"
                    elif eq is None or eq + 1 >= exend:
                        reason = "initializer_absent"
                    elif values[eq] != "=" or values[end] != ";" or [t.value for t in lhs] not in (["var", name], ["final", "var", name]):
                        reason = "var_declaration_syntax_unsupported"
                    elif lexical_owner is None:
                        reason = "local_initializer_owner_unproven"
                    elif body_scope is None or body_scope not in braces:
                        reason = "local_scope_not_proven"
                    elif start == 0 or values[start - 1] not in {"{", ";", "}"}:
                        reason = "local_declaration_block_boundary_unproven"
                    elif any(ref == name or ref.startswith(name + ".") for ref in _walk_references(fragment.get("expression") or {})):
                        reason = "var_self_reference_unsupported"
                    else:
                        local_type_candidates[fragment["id"]] = {
                            "declarationFragmentId": fragment["id"], "name": name,
                            "path": path, "sourceDigest": source_digest, "lexicalOwner": lexical_owner,
                            "sourceRange": dict(fragment["sourceRange"]),
                            "initializerRange": {"charStart": tokens[eq + 1].start, "charEnd": tokens[exend - 1].end},
                            "lexicalScopeRange": {"charStart": tokens[body_scope].start, "charEnd": tokens[braces[body_scope]].end}}
                    fragment["localTypeInference"] = {"status": "UNKNOWN", "reason": reason,
                        "specification": "https://docs.oracle.com/javase/specs/jls/se21/html/jls-14.html#jls-14.4",
                        "runtimeValue": "UNKNOWN", "definiteAssignment": "UNKNOWN"}
            elif eq is not None:
                name = values[eq - 1] if eq > start and tokens[eq - 1].kind == "name" else None
                fragment = add("assignment", start, end, tokens[eq + 1:exend], name=name, operator=values[eq])
                if fragment and fragment["expression"] is not None:
                    try:
                        target_parser = _Expression(prepare_expression_tokens(tokens[start:eq], node_sensitive)[0], decimal_bound, structural_only=node_sensitive)
                        fragment["target"] = target_parser.parse()
                        target_reasons = set(target_parser.reasons)
                        variable_syntax = _assignment_variable_syntax(fragment["target"])
                        if not variable_syntax:
                            target_reasons.add("assignment_target_not_variable")
                        if target_reasons:
                            fragment.update(representationStatus="partial",
                                unsupportedReasons=sorted(set(fragment["unsupportedReasons"]) | target_reasons))
                        if (values[eq] != "=" and variable_syntax
                                and not fragment.get("structuralOnly")):
                            # Operator syntax is retained independently of type
                            # validity, values, aliasing and successful execution.
                            fragment["assignmentSemantics"] = {
                                "scope": "java_compound_operator_contract_if_well_typed",
                                "operator": values[eq], "binaryOperator": values[eq][:-1],
                                "targetPointer": "/target", "rightHandSidePointer": "/expression",
                                "targetEvaluationCountOnNormalPath": 1,
                                "targetValueRead": "saved_before_right_hand_side",
                                "rightHandSideSkippedByBooleanShortCircuit": False,
                                "resultConversion": "to_left_hand_variable_type",
                                "typeCompatibility": "UNKNOWN", "resultValue": "UNKNOWN",
                                "atomicity": "UNKNOWN", "execution": "not_observed",
                                "exceptionConditionsComplete": False,
                                "specification": "https://docs.oracle.com/javase/specs/jls/se21/html/jls-15.html#jls-15.26.2"}
                    except _Unsupported as error:
                        fragment["target"] = {"op": "unresolved", "reason": error.reason}
                        fragment.update(representationStatus="partial",
                            unsupportedReasons=sorted(set(fragment["unsupportedReasons"]) | {"assignment_target_unsupported", error.reason}))
            else:
                fragment = add("statement", start, end, expression_tokens)
        if fragment:
            flow_fragments[(start, kind)] = fragment
            emitted_nodes.append((node, fragment))
    for node, fragment in emitted_nodes:
        owner = node["owner"]
        control = {"sourceOrder": node["sequence"], "orderMeaning": "lexical_order_not_runtime_execution",
                   "kind": node.get("controlKind", node["kind"]), "contexts": [],
                   "owner": None}
        if owner:
            control["owner"] = {"id": _id(path, source_digest, "callable", tokens[owner["start"]].start),
                                "name": owner["name"] if owner.get("name") and not _SENSITIVE.search(owner["name"]) else None,
                                "span": span(tokens[owner["start"]].start, tokens[owner["end"]].end),
                                "resolution": "lexical_callable_only"}
            definition = local_initializer_owner(node["start"], owner)
            if definition:
                control["owner"].update(id=definition["callableSymbolId"], resolution="source_callable_definition",
                    sourceRange=dict(definition["callableDeclarationRange"]),
                    declarationSpan=span(definition["callableDeclarationRange"]["charStart"],
                                         definition["callableDeclarationRange"]["charEnd"]))
            if owner.get("bodyId"):
                control["owner"]["bodyId"] = owner["bodyId"]
        for context in node["contexts"]:
            referenced = flow_fragments.get((context["start"], context["kind"]))
            control["contexts"].append({"fragmentId": referenced["id"] if referenced else None,
                "resolution": "recorded_source_control" if referenced else "control_not_recorded",
                "kind": context["kind"], "branch": context["branch"],
                "span": span(tokens[context["start"]].start, tokens[context["end"]].end),
                **{key: value for key, value in context.items() if key in {"relation", "fallthroughPossible", "handlerIndex", "logic", "group"}}})
        fragment["controlFlow"] = control
    body_counts = {}
    for fragment in result["fragments"]:
        for body_id in {context["fragmentId"] for context in fragment.get("controlFlow", {}).get("contexts", []) if context["kind"] == "embedded_body"}:
            body_counts[body_id] = body_counts.get(body_id, 0) + 1
    for fragment in result["fragments"]:
        if (fragment.get("expression") or {}).get("op") == "embedded_body":
            fragment["expression"]["recordedMemberCount"] = body_counts.get(fragment["id"], 0)
    # Pattern scope depends on boolean flow and abrupt completion (including
    # negated guards). Conservatively suppress conflicting outer bindings in
    # the containing callable rather than claiming a precise flow scope.
    for index, value in enumerate(values):
        if value != "instanceof":
            continue
        first, last, owner_gap = pattern_owner(index)
        if owner_gap:
            pattern_scope_gaps.append((first, last, owner_gap))
            scoped_binders.append({"name": None, "start": first, "end": last,
                "kind": "pattern_scope_unresolved", "span": span(tokens[index].start, tokens[index].end)})
        try:
            _, cursor, _ = _instanceof_type_syntax(tokens, index + 1)
            if (cursor < len(tokens) and tokens[cursor].kind == "name"
                    and _NAME.fullmatch(values[cursor]) and values[cursor] not in _JAVA_RESERVED_NAMES):
                remember_binder(cursor, first, last, "pattern_scope_unresolved")
            if cursor >= len(tokens) or values[cursor] != "(":
                continue
        except _Unsupported:
            pass
        # Unsupported/non-reifiable and record-pattern forms still introduce
        # possible binders. Wildcard '?' is inside the type's angle group, not
        # a conditional-expression boundary. Never let lost syntax restore an
        # outer/platform binding. This scan is conservative, not Java flow scope.
        cursor, nesting, angles = index + 1, 0, 0
        scan_end = min(len(tokens), cursor + MAX_EXPRESSION_TOKENS)
        while cursor < scan_end:
            value = values[cursor]
            if value in {"&&", "||", ";", "{", "}", ":"} or (value == "?" and not angles) or (value == ")" and nesting == 0):
                break
            if value == "<": angles += 1
            elif value in {">", ">>", ">>>"}: angles = max(0, angles - len(value))
            if value == "(": nesting += 1
            elif value == ")": nesting -= 1
            if tokens[cursor].kind == "name" and value not in _JAVA_RESERVED_NAMES:
                remember_binder(cursor, first, last, "pattern_scope_unresolved")
            cursor += 1
        if cursor == scan_end and cursor < len(tokens):
            # A bounded scan cannot prove the remaining binder names. Suppress
            # every unqualified value namespace in the containing callable.
            scoped_binders.append({"name": None, "start": first, "end": last,
                "kind": "pattern_scope_unresolved", "span": span(tokens[index].start, tokens[index].end)})
            pattern_scope_gaps.append((first, last, "pattern_scope_budget_exceeded"))


    # Bind only same-file lexical declarations. Cross-file/reference values,
    # overwritten locals and runtime values remain explicitly unresolved.
    fragment_scopes = {}
    for fragment in result["fragments"]:
        scope = fragment.pop("_scope")
        position = fragment.pop("_position")
        scope_gaps = {reason for first, last, reason in pattern_scope_gaps if first <= position < last}
        if scope_gaps:
            fragment["unsupportedReasons"] = sorted(set(fragment["unsupportedReasons"]) | scope_gaps)
            if fragment["representationStatus"] == "represented":
                fragment["representationStatus"] = "partial"
        fragment_scopes[fragment["id"]] = (scope, position)
        nested_names = lambda_names(fragment.get("expression")) | lambda_pattern_names(fragment.get("expression"))
        receiver_scope = next((tuple(scope[:i + 1]) for i in range(len(scope) - 1, -1, -1) if scope[i] in type_bodies), ())
        for reference in fragment["references"]:
            ref = reference["name"]
            if "." in ref and not ref.startswith("this."):
                continue
            name = ref.removeprefix("this.")
            shadowing = [binder for binder in scoped_binders if binder["name"] in {name, None} and binder["start"] <= position < binder["end"]]
            if not ref.startswith("this.") and (name in nested_names or shadowing):
                reference["resolution"] = "nested_scope_binding_unresolved"
                reference["reason"] = "nested_binder_prevents_outer_declaration_claim"
                continue
            choices = [decl for decl in declarations if decl["name"] == name
                       and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                       and (not ref.startswith("this.") or (decl["field"] and decl["scope"] == receiver_scope))
                       and (decl["field"] or decl["position"] < position)]
            if choices:
                depth = max(len(item["scope"]) for item in choices)
                nearest = [item for item in choices if len(item["scope"]) == depth]
                if len(nearest) == 1:
                    chosen = nearest[0]
                    reference["resolution"] = "lexical_declaration_only"
                    reference["declarations"] = [{"id": chosen["id"], "path": path,
                                                  "span": chosen["span"], "sourceDigest": source_digest,
                                                  "declaredType": chosen.get("declaredType")}]
        status = fragment["representationStatus"]
        coverage[status + "Fragments"] += 1
    # Source-bound immutable collection and record argument shape. No arbitrary
    # constructor is declared immutable and no overload/effect is evaluated.
    imports = {match.group(2): match.group(1) + "." + match.group(2)
               for match in re.finditer(r"\bimport ((?:[A-Za-z_$][A-Za-z0-9_$]* \. )+)([A-Za-z_$][A-Za-z0-9_$]*) ;", text)}
    imports = {name: target.replace(" ", "").replace("..", ".") for name, target in imports.items()}
    records = {}
    for index, value in enumerate(values[:-2]):
        if value != "record" or index + 2 not in parens:
            continue
        closing = parens[index + 2]
        components = []
        for first, last in _split(tokens, index + 3, closing, ","):
            names = [i for i in range(first, last) if tokens[i].kind == "name"]
            if len(names) >= 2:
                name_index = names[-1]
                components.append({"name": values[name_index], "declaredType": "".join(values[first:name_index]),
                                   "span": span(tokens[first].start, tokens[last - 1].end)})
        records.setdefault(values[index + 1], []).append({"components": components,
            "span": span(tokens[index].start, tokens[closing].end), "position": index, "scope": scopes[index]})

    def visible_types(name, scope, position):
        return [decl for decl in type_declarations if decl["name"] == name
                and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                and (not decl["scope"] or decl["scope"][-1] in type_bodies or decl["position"] <= position)]

    def value_name_shadowed(name, scope, position, nested_names):
        return (name in nested_names
                or any(binder["name"] in {name, None} and binder["start"] <= position < binder["end"] for binder in scoped_binders)
                or any(decl["name"] == name and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                       and (decl["field"] or decl["position"] <= position) for decl in declarations)
                or bool(java_type_context and java_type_context.get("valueHeadShadowed", lambda *_: False)(name, tokens[position].start)))

    def canonical_name(name, scope, position, nested_names):
        head, separator, tail = name.partition(".")
        if value_name_shadowed(head, scope, position, nested_names) or visible_types(head, scope, position):
            return None
        if head in imports:
            return imports[head] + ("." + tail if separator else "")
        return name if name.startswith(("java.time.", "java.util.")) else None

    for fragment in result["fragments"]:
        if fragment.get("structuralOnly"):
            continue
        scope, position = fragment_scopes[fragment["id"]]
        nested_names = lambda_names(fragment.get("expression"))
        pending = [fragment.get("expression")]
        constructor_catalog = {}
        while pending:
            expression = pending.pop()
            if isinstance(expression, list):
                pending.extend(expression)
                continue
            if not isinstance(expression, dict):
                continue
            pending.extend(expression.values())
            if expression.get("op") == "construct":
                if java_type_context and "anonymousBody" not in expression and not expression.get("typeArguments"):
                    binding = java_type_context.get("recordConstruction", lambda *_: None)(expression["type"],
                        len(expression["arguments"]), expression.get("sourceConstructionOffset", tokens[position].start))
                    declaration = binding.get("declaration") if binding else None
                    if declaration and not any(_SENSITIVE.search(p["name"]) for p in declaration["parameters"]):
                        constructor_catalog[declaration["id"]] = declaration
                        expression["recordConstruction"] = {"declarationId":declaration["id"],
                            "catalogLocation":"fragment.recordConstructorDeclarations", "resolution":binding["resolution"],
                            "argumentBindings":[{"argumentIndex":i,"parameterIndex":i} for i in range(len(expression["arguments"]))]
                                if binding["resolution"]=="implicit_canonical_parameter_order" else [],
                            "argumentApplicability":"UNKNOWN", "storedComponentValues":"UNKNOWN", "executionSuccess":"UNKNOWN",
                            "limitations":binding["limitations"], "sourceEvidenceIds":declaration["sourceEvidenceIds"]}
                    elif binding and not declaration:
                        expression["recordConstruction"] = binding
                type_candidates = visible_types(expression["type"], scope, position)
                if type_candidates:
                    nearest_depth = max(len(decl["scope"]) for decl in type_candidates)
                    type_candidates = [decl for decl in type_candidates if len(decl["scope"]) == nearest_depth]
                candidates = [record for record in records.get(expression["type"], [])
                              if len(type_candidates) == 1 and type_candidates[0]["kind"] == "record"
                              and type_candidates[0]["position"] == record["position"]]
                if (not expression.get("recordConstruction") and len(candidates) == 1 and len(candidates[0]["components"]) == len(expression["arguments"])
                        and not any(_SENSITIVE.search(c["name"]) for c in candidates[0]["components"])):
                    expression["recordShape"] = {"binding": "same_file_record_component_order",
                        "declarationSpan": candidates[0]["span"], "constructorOverload": "unresolved",
                        "components": [{**component, "argumentIndex": i} for i, component in enumerate(candidates[0]["components"])]}
            if expression.get("op") != "call" or expression.get("callee", {}).get("op") != "reference":
                continue
            canonical = canonical_name(expression["callee"]["name"], scope, position, nested_names)
            args = expression["arguments"]
            if canonical in {"java.util.Map.of", "java.util.Map.entry", "java.util.Map.ofEntries", "java.util.List.of", "java.util.Set.of"}:
                shape = {"binding": canonical, "resolution": "explicit_source_type_binding",
                         "runtimeStatus": "not_observed"}
                if canonical in {"java.util.Map.of", "java.util.Map.entry"} and len(args) % 2 == 0:
                    shape.update(kind="map_entries", entries=[{"keyArgument": i, "valueArgument": i + 1} for i in range(0, len(args), 2)])
                else:
                    shape.update(kind="map_entry_arguments" if canonical.endswith("ofEntries") else "ordered_arguments",
                                 argumentIndices=list(range(len(args))))
                expression["collectionShape"] = shape
            units = {"java.time.Duration.ofNanos": "nanosecond", "java.time.Duration.ofMillis": "millisecond",
                     "java.time.Duration.ofSeconds": "second", "java.time.Duration.ofMinutes": "minute",
                     "java.time.Duration.ofHours": "hour", "java.time.Duration.ofDays": "day"}
            if canonical in units:
                expression["unitEvidence"] = {"status": "EXPLICIT_SOURCE_BINDING", "dimension": "time",
                                               "unit": units[canonical], "binding": canonical}
                if expression is fragment.get("expression"):
                    fragment["unit"] = dict(expression["unitEvidence"])
        if constructor_catalog:
            if len(_canonical(constructor_catalog)) <= 64 * 1024:
                fragment["recordConstructorDeclarations"] = list(constructor_catalog.values())
            else:
                # The original constructors/arguments remain intact; only this
                # optional declaration join is explicitly unavailable.
                pending = [fragment.get("expression")]
                while pending:
                    item = pending.pop()
                    if isinstance(item,dict):
                        if "recordConstruction" in item:
                            item["recordConstruction"]={"resolution":"UNKNOWN","reason":"record_constructor_catalog_budget_exceeded"}
                        pending.extend(item.values())
                    elif isinstance(item,list): pending.extend(item)
                fragment["unsupportedReasons"]=sorted(set(fragment["unsupportedReasons"])|{"record_constructor_catalog_budget_exceeded"})
    # The syntax-only extractor remains usable independently. Platform API
    # contracts require the same source-bound Java index used for symbols.
    if java_type_context is not None:
        inferred_local_types = {}
        initializer_providers = {f['id']: f for f in result['fragments']}
        for fragment in result["fragments"]:
            if fragment.get("structuralOnly"):
                continue
            if (fragment.get("category") == "local_declaration" and fragment.get("declaredType") == "var"
                    and fragment["id"] not in local_type_candidates):
                # A known invalid/unowned local initializer must not retain
                # an outer declaration's type, even before local propagation.
                continue
            scope, position = fragment_scopes[fragment["id"]]
            nested_names = lambda_names(fragment.get("expression"))
            receiver_scope = next((tuple(scope[:i + 1]) for i in range(len(scope) - 1, -1, -1) if scope[i] in type_bodies), ())

            def resolve_type(raw, value_context=False, at=None, type_scope=None, parameter=None):
                at = position if at is None else at
                type_scope = scope if type_scope is None else type_scope
                head = raw.split(".", 1)[0]
                if visible_types(head, type_scope, at):
                    return None
                if value_context and value_name_shadowed(head, scope, position, nested_names):
                    return None
                return java_type_context["resolve"](raw, tokens[at].start, parameter)

            def reference_type(raw):
                if "." in raw and not raw.startswith("this."):
                    return None
                name = raw.removeprefix("this.")
                active_binders = [b for b in scoped_binders if b["name"] in {name, None} and b["start"] <= position < b["end"]]
                if not raw.startswith("this.") and name in nested_names:
                    return None
                if not raw.startswith("this.") and active_binders:
                    if len(active_binders) != 1 or active_binders[0]["kind"] != "enhanced_for_local":
                        return None
                    binder = active_binders[0]
                    if binder["receiverScope"] != receiver_scope or any(
                            decl["name"] == name and not decl["field"] and decl["position"] >= binder["start"]
                            and decl["position"] < position and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                            for decl in declarations):
                        return None
                    declared = binder["declaredType"]
                    if "@" in declared or declared == "var":
                        return None
                    typed = java_type_context.get("recordType", lambda *_: None)(declared, tokens[binder["declarationPosition"]].start)
                    loop = flow_fragments.get((binder["loopStart"], "loop"))
                    if not typed or not loop:
                        return None
                    origin = typed.get("_platformOrigin")
                    if origin:
                        typed = {**typed, "_platformOrigin": {**origin, "kind": "loop_variable", "recordId": loop["id"], "selector": "/expression/variable"}}
                    return {**typed, "basis": "explicit_enhanced_for_variable_type",
                        "sourceEvidenceIds": sorted(set(typed["sourceEvidenceIds"] + [loop["id"]])),
                        "variableScope": {"kind": "enhanced_for_body", "charStart": tokens[binder["start"]].start,
                            "charEnd": tokens[binder["end"] - 1].end, "runtimeValue": "UNKNOWN"}}
                choices = [decl for decl in declarations if decl["name"] == name
                           and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                           and (decl["field"] or decl["position"] < position)
                           and (not raw.startswith("this.") or (decl["field"] and decl["scope"] == receiver_scope))]
                if not choices:
                    # Component fields are source declarations even though the
                    # syntax-only expression inventory has no explicit field
                    # statement for them. The bridge checks the exact receiver.
                    if any(c.get("kind") == "embedded_body" and c.get("branch") == "member_declaration"
                           for c in fragment.get("controlFlow", {}).get("contexts", [])):
                        return None
                    typed = java_type_context.get("recordField", lambda *_: None)(raw, tokens[position].start)
                    if typed is None and not raw.startswith("this."):
                        typed = java_type_context.get("importedSourceField", lambda *_: None)(raw, tokens[position].start)
                    return typed
                depth = max(len(decl["scope"]) for decl in choices)
                choices = [decl for decl in choices if len(decl["scope"]) == depth]
                if len(choices) != 1:
                    return None
                decl = choices[0]
                local_candidate = local_type_candidates.get(fragment["id"])
                if local_candidate is not None:
                    # Do not turn an outer field fallback into a local type.
                    # Unselected inherited members can shadow an enclosing
                    # field; nearest type/callable ownership must be proven.
                    owner_range = local_candidate["lexicalOwner"]["callableBodyRange"]
                    decl_bodies = [body for body in decl["scope"] if body in methods]
                    if ((decl["field"] and decl["scope"] != receiver_scope)
                            or (not decl["field"] and (len(decl_bodies) != 1
                                or tokens[decl_bodies[0]].start != owner_range["charStart"]))):
                        return None
                if decl.get("declaredType") == "var" and not decl["field"] and not decl.get("parameter"):
                    typed = inferred_local_types.get(decl["id"])
                    if typed is not None and (fragment.get("controlFlow", {}).get("owner") or {}).get("id") != typed["localTypeBinding"]["lexicalOwner"]["callableSymbolId"]:
                        typed = None
                    if typed is not None:
                        # Return an independent annotation. Later value writes
                        # do not change the source-declared local variable type.
                        typed = json.loads(_canonical(typed))
                        if typed.get('platformInheritance'):
                            typed = (platform_projection.local_initializer(typed, initializer_providers.get(decl['id']))
                                     if platform_projection else None)
                else:
                    typed = resolve_type(decl.get("declaredType") or "", at=decl["position"], type_scope=decl["scope"],
                                         parameter=name if decl.get("parameter") else None)
                if decl.get("declaredType") != "var" and (not decl["field"] or decl["scope"] == receiver_scope):
                    record_typed = java_type_context.get("recordType", lambda *_: None)(decl.get("declaredType") or "",
                        tokens[decl["position"]].start, name if decl.get("parameter") else None)
                    if record_typed:
                        typed = record_typed
                if typed:
                    if typed.get('basis') == 'source_local_initializer_type' and typed.get('platformInheritance'):
                        if not any(ref.get('name') == raw for ref in fragment['references']):
                            fragment['references'].append({'name': raw, 'resolution': 'lexical_declaration_only',
                                'usage': 'typed_local_receiver', 'declarations': [{'id': decl['id'], 'path': path,
                                    'span': decl['span'], 'sourceDigest': source_digest, 'declaredType': 'var'}]})
                    typed = {**typed, "sourceEvidenceIds": sorted(set(typed["sourceEvidenceIds"] +
                             ([fragment["id"]] if decl.get("parameter") else [decl["id"]])))}
                    if decl.get("parameter"):
                        typed["parameterName"] = name
                    elif typed.get("_platformOrigin"):
                        typed["_platformOrigin"] = {**typed["_platformOrigin"], "kind": "declaration", "recordId": decl["id"], "selector": "/declaredType"}
                        if not any(ref.get('name')==raw for ref in fragment['references']):
                            # Qualified call spelling is stored separately; its
                            # actual receiver read has the same lexical binding
                            # selected above, not an inferred CALLS target.
                            fragment['references'].append({'name':raw,'resolution':'lexical_declaration_only',
                                'usage':'typed_call_receiver','declarations':[{'id':decl['id'],'path':path,
                                    'span':decl['span'],'sourceDigest':source_digest,'declaredType':decl.get('declaredType')}]})
                    if typed["name"] == "java.util.concurrent.CompletableFuture":
                        typed["sourceStageIdentity"] = {"id": _id("stage_slot", decl["id"]),
                            "kind": "declaration_slot", "runtimeObjectIdentity": "UNKNOWN"}
                return typed

            def imported_constant(name, known_members):
                if (name in nested_names or visible_types(name, scope, position)
                        or any(b["name"] in {name, None} and b["start"] <= position < b["end"] for b in scoped_binders)
                        or any(d["name"] == name and tuple(scope[:len(d["scope"])]) == d["scope"]
                               and (d["field"] or d["position"] <= position) for d in declarations)):
                    return None
                return java_type_context.get("staticImport", lambda *_: None)(name, tokens[position].start, known_members)

            # The call index intentionally has no nested-binder inference;
            # don't reuse an apparently exact factory target through that gap.
            binder_active = bool(nested_names) or any(b["start"] <= position < b["end"] for b in scoped_binders)
            source_owner = java_type_context.get("lexicalCallableOwner", lambda *_: None)(tokens[position].start)
            if source_owner:
                fragment["javaSourceOwner"] = {"typeSymbolId": source_owner["typeSymbolId"],
                    "callableSymbolId": source_owner["callableSymbolId"]}
            syntax_nodes = [fragment.get("expression")]
            while syntax_nodes:
                syntax_node = syntax_nodes.pop()
                if isinstance(syntax_node, dict):
                    at = syntax_node.get("sourceInvocationOffset")
                    if type(at) is int and 0 <= at < len(source):
                        invocation_line = bisect.bisect_left(line_offsets, at)
                        syntax_node["sourceInvocationSpan"] = {"line": invocation_line,
                            "column": at - line_offsets[invocation_line - 1]}
                    syntax_nodes.extend(v for v in syntax_node.values() if isinstance(v, (dict, list)))
                elif isinstance(syntax_node, list):
                    syntax_nodes.extend(syntax_node)
            platform_projection = java_type_context.get("platformProjection", lambda: None)()
            overlapping_patterns = any(first < bisect.bisect_left(token_starts, fragment["sourceRange"]["charEnd"])
                and last > bisect.bisect_left(token_starts, fragment["sourceRange"]["charStart"])
                for first, last in ((binder["start"], binder["end"]) for binder in scoped_binders
                                    if binder["kind"] == "pattern_scope_unresolved"))
            private_lambdas = fragment_lambda_nodes.get(fragment["id"], {})
            private_calls = fragment_call_nodes.get(fragment["id"], {})

            def in_node_scope(node, evaluate):
                nonlocal position, scope, receiver_scope
                if node.get("op") == "lambda":
                    boundary = private_lambdas.get(id(node))
                    offset = boundary[0] if boundary else None
                else:
                    offset = node.get("sourceInvocationOffset")
                    if id(node) not in private_calls or private_calls[id(node)] != offset:
                        offset = None
                at = bisect.bisect_left(token_starts, offset) if type(offset) is int else len(tokens)
                if (at >= len(tokens) or tokens[at].start != offset
                        or not fragment["sourceRange"]["charStart"] <= offset < fragment["sourceRange"]["charEnd"]):
                    node["staticContractStatus"] = {"status": "UNKNOWN", "reason": "pattern_scope_owner_unresolved"}
                    return None
                previous = position, scope, receiver_scope
                position, scope = at, scopes[at]
                receiver_scope = next((tuple(scope[:i + 1]) for i in range(len(scope) - 1, -1, -1) if scope[i] in type_bodies), ())
                try:
                    return evaluate()
                finally:
                    position, scope, receiver_scope = previous

            def scoped_call_result(offset):
                active = bool(nested_names) or any(binder["start"] <= position < binder["end"] for binder in scoped_binders)
                callback = java_type_context.get("callInBinder", lambda *_: None) if active else java_type_context["callResult"]
                return callback(offset)

            def callback_shadowed(raw, callback):
                head=raw.split(".",1)[0]
                at=bisect.bisect_left(token_starts,callback.get("sourceRange",{}).get("charStart",-1))
                if at>=len(tokens):return True
                local_scope=scopes[at]
                return (any(b["name"] in {head,None} and b["start"]<=at<b["end"] for b in scoped_binders)
                    or any(d["name"]==head and tuple(local_scope[:len(d["scope"])])==d["scope"]
                        and (d["field"] or d["position"]<=at) for d in declarations))

            catalog = policy_java_contracts.enrich(fragment.get("expression"), reference_type=reference_type,
                type_name=resolve_type, call_result=scoped_call_result if overlapping_patterns else
                    java_type_context.get("callInBinder", lambda offset: None) if binder_active else java_type_context["callResult"],
                fragment_id=fragment["id"], record_accessor=java_type_context.get("recordAccessor"), static_import=imported_constant,
                record_call_result=java_type_context.get("recordCallResult"), platform_projection=platform_projection,
                node_scope=in_node_scope if overlapping_patterns else None,
                callback_signature=java_type_context.get("callbackSignature"), callback_shadowed=callback_shadowed)
            if catalog:
                fragment["standardApiContracts"] = catalog
            if platform_projection:
                platform_projection.finish(fragment)
            expression_type = (fragment.get("expression") or {}).get("staticType", {})
            candidate = local_type_candidates.get(fragment["id"])
            if candidate is not None:
                expression_nodes = list(_dependency_nodes(fragment.get("expression")))
                supported = (expression_type.get("resolution") == "resolved_static_type"
                    and isinstance(expression_type.get("name"), str)
                    and expression_type["name"] not in {"void", "java.lang.void", "null", "UNKNOWN"}
                    and bool(expression_type.get("sourceEvidenceIds"))
                    and expression_type.get("typeArgumentsStatus", "resolved") in {"resolved", "raw"}
                    and not any("anonymousBody" in node or node.get("op") in {"lambda", "body_reference", "redacted", "masked_value"}
                                or node.get("typeArguments") and node.get("op") == "construct"
                                or node.get("staticEvidenceStatus", {}).get("status") == "UNKNOWN"
                                for node in expression_nodes))
                # Compact edges, not a copied transitive proof tree. Existing
                # initializer ASTs retain every predecessor for closure checks.
                dependency_depth = 1 + max((node.get("localTypeBinding", {}).get("dependencyDepth", 0)
                    for node in expression_nodes if node.get("basis") == "source_local_initializer_type"), default=0)
                if dependency_depth > MAX_EXPRESSION_DEPTH:
                    supported = False
                    fragment["localTypeInference"]["reason"] = "local_initializer_dependency_depth_exceeded"
                if supported:
                    evidence = [fragment["id"]]
                    binding = {**candidate, "status": "source_initializer_static_type", "dependencyDepth": dependency_depth,
                        "catalogLocation": "fragment.localTypeInference", "inferredType": expression_type["name"],
                        "sourceEvidenceIds": evidence,
                        "specification": "https://docs.oracle.com/javase/specs/jls/se21/html/jls-14.html#jls-14.4",
                        "runtimeValue": "UNKNOWN", "definiteAssignment": "UNKNOWN"}
                    fragment["localTypeInference"] = binding
                    typed = {key: value for key, value in expression_type.items()
                             if key not in {"basis", "parameterName", "fieldBinding", "variableScope", "localTypeBinding"}}
                    inferred_local_types[fragment["id"]] = {**typed, "basis": "source_local_initializer_type",
                        "localTypeBinding": binding, "sourceEvidenceIds": evidence}
            if fragment["category"] in {"field", "constant", "local_declaration"} and expression_type.get("sourceStageIdentity"):
                fragment["stageInitializer"] = {"declarationStage": {"id": _id("stage_slot", fragment["id"]),
                    "kind": "declaration_slot", "runtimeObjectIdentity": "UNKNOWN"},
                    "expressionStage": expression_type["sourceStageIdentity"], "relation": "source_initializer_expression",
                    "runtimeAliasAnalysis": "UNKNOWN", "sourceEvidenceIds": [fragment["id"]]}
    # Preserve assignment lineage as conservative lexical candidates. Branches,
    # aliases, loops and interprocedural writes make reaching values UNKNOWN.
    writes = []
    for fragment in result["fragments"]:
        owner = fragment.get("controlFlow", {}).get("owner")
        owner_id = owner.get("id") if owner else None
        reads = []
        for reference in fragment["references"]:
            name = reference["name"].removeprefix("this.")
            declaration_ids = [item["id"] for item in reference["declarations"]]
            candidates = [write["id"] for write in writes if write["name"] == name
                          and write["ownerId"] == owner_id and write["declarationIds"] == declaration_ids]
            reads.append({"name": reference["name"], "declarationIds": declaration_ids,
                          "precedingWriteCandidates": candidates})
        fragment["dataFlow"] = {"resolution": "lexical_candidates_not_reaching_definitions",
                                "reads": reads, "writes": [], "valueSubstitution": False}
        if fragment["category"] in {"field", "constant", "local_declaration", "assignment"} and fragment.get("name"):
            name = fragment["name"]
            declaration_ids = [fragment["id"]] if fragment["category"] != "assignment" else []
            if fragment["category"] == "assignment":
                scope, position = fragment_scopes[fragment["id"]]
                target = fragment.get("target", {})
                target_name = target.get("name") if target.get("op") == "reference" else None
                receiver_scope = next((tuple(scope[:i + 1]) for i in range(len(scope) - 1, -1, -1) if scope[i] in type_bodies), ())
                binder_shadow = any(binder["name"] in {name, None} and binder["start"] <= position < binder["end"] for binder in scoped_binders)
                choices = [decl for decl in declarations if decl["name"] == name
                           and tuple(scope[:len(decl["scope"])]) == decl["scope"]
                           and (decl["field"] or decl["position"] < position)
                           and ((target_name == name and not binder_shadow)
                                or (target_name == "this." + name and decl["field"] and decl["scope"] == receiver_scope))]
                if choices:
                    depth = max(len(decl["scope"]) for decl in choices)
                    nearest = [decl for decl in choices if len(decl["scope"]) == depth]
                    if len(nearest) == 1:
                        declaration_ids = [nearest[0]["id"]]
            write = {"name": name, "declarationIds": declaration_ids,
                     "operator": fragment.get("assignmentOperator"), "valueStatus": "not_evaluated"}
            fragment["dataFlow"]["writes"].append(write)
            writes.append({**write, "id": fragment["id"], "ownerId": owner_id})
    # Enum tables are source argument -> parameter -> field links, not evaluated
    # values. Only one plain constructor consisting of unconditional, unique,
    # direct parameter assignments can give a definite *source mapping*.
    enum_cache = {}
    for enum_node, fragment in emitted_nodes:
        if enum_node["kind"] != "enum_constant" or (fragment.get("expression") or {}).get("op") != "enum_constant":
            continue
        enum_body = enum_node["enumBody"]
        enum_scope = scopes[enum_body] + (enum_body,)
        if enum_body not in enum_cache:
            constructors = []
            for body, method in methods.items():
                if method["name"] != enum_node["enumName"] or scopes[body] != enum_scope:
                    continue
                first = method["start"] - 1
                while first >= 0 and values[first] not in {";", "{", "}"}:
                    first -= 1
                cursor, header_supported = first + 1, True
                while cursor < method["start"]:
                    if values[cursor] in _MODIFIERS:
                        cursor += 1
                    elif values[cursor] == "@":
                        cursor += 2
                        while cursor + 1 < method["start"] and values[cursor] == ".": cursor += 2
                        if cursor in parens: cursor = parens[cursor] + 1
                    else:
                        header_supported = False
                        break
                parameters = [decl for decl in declarations if decl.get("parameter") and decl["position"] == body]
                members = [(node, row) for node, row in emitted_nodes if node.get("owner") and node["owner"].get("body") == body]
                field_decls = {decl["id"]: decl for decl in declarations if decl["field"] and decl["scope"] == enum_scope}
                parameter_indices = {decl["name"]: i for i, decl in enumerate(parameters)}
                mutated_parameters = {row["name"] for _, row in members if row.get("category") == "assignment"
                    and row.get("target", {}).get("op") == "reference" and row["target"].get("name") in parameter_indices}
                field_writes = {}
                for _, row in members:
                    for write in row["dataFlow"]["writes"]:
                        for identity in write["declarationIds"]:
                            if identity in field_decls:
                                field_writes[identity] = field_writes.get(identity, 0) + 1
                mappings = []
                direct_assignment_ids = set()
                for node, row in members:
                    expr = row.get("expression") or {}
                    if (row["category"] != "assignment" or row.get("assignmentOperator") != "="
                            or expr.get("op") != "reference" or expr.get("name") not in parameter_indices):
                        continue
                    targets = [identity for write in row["dataFlow"]["writes"] for identity in write["declarationIds"] if identity in field_decls]
                    if len(targets) != 1:
                        continue
                    parameter_index = parameter_indices[expr["name"]]
                    parameter = parameters[parameter_index]
                    references = [ref for ref in row["references"] if ref["name"] == expr["name"]]
                    if not any(ref["resolution"] == "lexical_declaration_only" and any(d["id"] == parameter["id"] for d in ref["declarations"]) for ref in references):
                        continue
                    identity = targets[0]
                    mappings.append({"fieldDeclarationId": identity, "assignmentFragmentId": row["id"],
                        "parameterIndex": parameter_index, "parameterName": expr["name"], "operator": "=",
                        "assignmentSpan": row["span"], "unconditionalSourceStatement": not bool(node["contexts"]),
                        "parameterUnmodifiedInConstructor": expr["name"] not in mutated_parameters,
                        "fieldWriteCountInConstructor": field_writes[identity]})
                    direct_assignment_ids.add(row["id"])
                delegation = any((row.get("expression") or {}).get("op") == "call"
                    and row["expression"].get("callee", {}).get("name") in {"this", "super"} for _, row in members)
                constructors.append({"method": method, "headerSupported": header_supported, "parameters": parameters,
                    "mappings": mappings, "simpleBody": bool(members) and all(row["id"] in direct_assignment_ids for _, row in members),
                    "delegation": delegation})
            enum_cache[enum_body] = constructors
        constructors = enum_cache[enum_body]
        mapping_count = sum(len(c["mappings"]) for c in constructors)
        parameter_count = sum(len(c["parameters"]) for c in constructors)
        binding_budget_exceeded = len(constructors) > 64 or mapping_count > 128 or parameter_count > 256
        candidates = []
        for constructor in ([] if binding_budget_exceeded else constructors):
            method = constructor["method"]
            params = constructor["parameters"]
            arity_matches = len(params) == len(fragment["expression"]["arguments"])
            reasons = []
            if not constructor["headerSupported"]: reasons.append("constructor_header_not_proven")
            if len(constructors) != 1: reasons.append("constructor_overload_unresolved")
            if not arity_matches: reasons.append("constructor_arity_mismatch")
            if len(result["fragments"]) != coverage["detectedFragments"]: reasons.append("fragment_inventory_incomplete")
            if constructor["delegation"]: reasons.append("constructor_delegation_unresolved")
            if not constructor["simpleBody"]: reasons.append("constructor_body_effects_unresolved")
            if enum_node.get("constantBody") is not None: reasons.append("enum_constant_subclass_effects_unresolved")
            field_mappings = []
            for mapping in constructor["mappings"]:
                limitations = list(reasons)
                if not mapping["unconditionalSourceStatement"]: limitations.append("conditional_assignment")
                if not mapping["parameterUnmodifiedInConstructor"]: limitations.append("parameter_reassigned")
                if mapping["fieldWriteCountInConstructor"] != 1: limitations.append("multiple_field_writes")
                field_mappings.append({**mapping, "argumentIndex": mapping["parameterIndex"] if arity_matches else None,
                    "resolution": "direct_source_argument_field_mapping" if not limitations else "candidate_source_assignment",
                    "limitations": limitations, "initialValueStatus": "UNKNOWN",
                    "sourceEvidenceIds": [fragment["id"], mapping["fieldDeclarationId"], mapping["assignmentFragmentId"]]})
            candidates.append({"constructorSpan": span(tokens[method["start"]].start, tokens[method["end"]].end),
                "arityMatches": arity_matches, "parameterOrder": [{"name": p["name"], "declaredType": p["declaredType"],
                    "span": p["span"]} for p in params], "fieldMappings": field_mappings,
                "resolution": "single_source_constructor_matching_arity" if len(constructors) == 1 and constructor["headerSupported"] and arity_matches else "candidate",
                "limitations": reasons, "executionSuccess": "UNKNOWN"})
        binding_budget_exceeded = binding_budget_exceeded or len(_canonical(candidates)) > 64 * 1024
        fragment["expression"]["constructorBindings"] = {"candidates": candidates if not binding_budget_exceeded else [],
            "resolution": "source_constructor_candidates" if candidates else "implicit_or_unrepresented_constructor",
            "valueSubstitution": False, "initialValueStatus": "UNKNOWN",
            "reason": "source_mapping_not_runtime_initialization"}
        if binding_budget_exceeded:
            # The argument AST, declarations and every constructor statement
            # remain in the inventory. Only this optional derived join is
            # unrepresented; never truncate its rows and call it complete.
            fragment["expression"]["constructorBindings"].update(resolution="UNKNOWN",
                reason="enum_constructor_binding_budget_exceeded", candidateCount=len(constructors),
                mappingCount=mapping_count, parameterCount=parameter_count,
                sourceTypeSpan=span(tokens[enum_node["enumStart"]].start, tokens[braces[enum_body]].end))
            fragment["unsupportedReasons"] = sorted(set(fragment["unsupportedReasons"]) | {"enum_constructor_binding_budget_exceeded"})
    if literal_review is not None:
        admitted_entries = {entry["requestIndex"]: entry for entry in literal_review.coverage(path)["entries"] if entry["status"] == "admitted"}
        admitted = set(admitted_entries)
        for fragment in result["fragments"]:
            pending = [fragment]
            revoked = False
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    if "literalReview" in item and item["literalReview"]["requestIndex"] not in admitted:
                        revoked = True
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
            if revoked:
                fragment.update(expression=None, references=[], representationStatus="unsupported", unsupportedReasons=["literal_review_revoked"])
                for key in ("target", "assignmentSemantics", "standardApiContracts", "platformTypeContracts", "platformInheritanceChecks", "platformTypeProofs", "platformInheritanceCoverage", "stageInitializer", "recordConstructorDeclarations"):
                    fragment.pop(key, None)
    # Check the final tree too, including prebuilt flow/enum structures and
    # assignment targets added after parsing. A later adapter must not bypass
    # value masking or add semantic contracts to a structural-only fragment.
    for fragment in result["fragments"]:
        if not fragment.get("structuralOnly"):
            continue
        pending = [fragment]
        invalid = False
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                proof = item.get("literalReview", {})
                binding = proof.get("sourceBinding", {})
                empty_marker = (literal_review is not None and item.get("type") == "string" and item.get("value") == ""
                    and proof.get("emptySensitiveMarker") is True and proof.get("requestIndex") in admitted
                    and binding.get("path") == path and binding.get("sourceSha256") == source_digest
                    and type(binding.get("tokenByteStart")) is int and type(binding.get("tokenByteEnd")) is int
                    and all(binding[key] == admitted_entries[proof["requestIndex"]][key] for key in ("tokenByteStart", "tokenByteEnd"))
                    and raw[binding["tokenByteStart"]:binding["tokenByteEnd"]] == b'""')
                invalid = invalid or (item.get("op") == "literal" and not empty_marker and (item.get("type") != "null" or item.get("value") is not None))
                invalid = invalid or (item.get("op") == "masked_value" and "value" in item)
                invalid = invalid or bool(set(item) & {"staticContract", "staticType", "standardConstant", "standardApiContracts", "platformTypeContracts", "platformInheritanceChecks", "recordShape", "collectionShape", "unitEvidence"})
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        if invalid:
            fragment.update(expression=None, references=[], representationStatus="unsupported", unsupportedReasons=["structural_safety_veto"])
            for key in ("target", "assignmentSemantics", "standardApiContracts", "platformTypeContracts", "platformInheritanceChecks", "platformTypeProofs", "platformInheritanceCoverage", "stageInitializer", "recordConstructorDeclarations"):
                fragment.pop(key, None)
    # Link surviving inline loop definitions after all revocation/privacy gates.
    # No copied initializer values, guessed iteration counts or reaching values.
    live_loops = {identity: row for identity, (_, row) in enhanced_loops.items()
                  if (row.get("expression") or {}).get("op") == "enhanced_for"}
    for fragment in result["fragments"]:
        control = fragment.get("controlFlow", {})
        contexts = control.get("contexts", [])
        relations = []
        for context_index, context in enumerate(contexts):
            loop = live_loops.get(context.get("fragmentId"))
            if loop is None or context.get("kind") != "loop" or context.get("branch") != "body":
                continue
            expression = loop["expression"]
            body_id = expression["body"]["id"]
            context["loopBodyId"] = body_id
            context["bodyDefinition"] = {"fragmentId": loop["id"], "jsonPath": "expression.body"}
            deferred = (any(c.get("kind") == "embedded_body" for c in contexts[context_index + 1:])
                        or control.get("owner") != loop.get("controlFlow", {}).get("owner"))
            relation = {"loopFragmentId": loop["id"], "bodyId": body_id,
                "membership": "deferred_callable_source_nesting" if deferred else "lexical_body_statement",
                "execution": "UNKNOWN" if deferred else "per_iteration_if_reached_not_observed",
                "bindingId": expression["variable"]["id"],
                "guardContexts": [{"fragmentId": c.get("fragmentId"), "branch": c.get("branch"),
                    "resolution": c.get("resolution")} for c in contexts[context_index + 1:] if c.get("kind") == "condition"],
                "role": "source_statement"}
            if not deferred:
                kind = control.get("kind")
                if kind in {"condition", "if"}:
                    relation["role"] = "iteration_guard"
                elif kind in {"for", "while", "do"}:
                    relation["role"] = "nested_loop_header"
                elif kind in {"return", "throw", "break", "continue"}:
                    relation.update(role="abrupt_completion_syntax", completionKind=kind,
                        runtimeTaken="UNKNOWN", loopExit="UNKNOWN")
                    if kind in {"break", "continue"}:
                        label = (fragment.get("expression") or {}).get("label")
                        targets = [c for c in contexts if c.get("kind") in ({"loop", "switch"} if kind == "break" else {"loop"})]
                        if label is None and targets:
                            relation.update(targetFragmentId=targets[-1].get("fragmentId"),
                                targetKind=targets[-1]["kind"], targetResolution="nearest_lexical_control" if targets[-1].get("fragmentId") else "control_not_recorded")
                        else:
                            relation["targetResolution"] = "UNKNOWN"
                    elif kind == "return":
                        relation["targetResolution"] = "enclosing_callable_syntax"
                    else:
                        relation["exceptionHandling"] = "UNKNOWN"
                elif fragment.get("category") == "assignment":
                    data = fragment.get("dataFlow", {})
                    writes = data.get("writes", [])
                    write_ids = {i for write in writes for i in write.get("declarationIds", [])}
                    self_read = bool(write_ids and any(write_ids & set(read.get("declarationIds", [])) for read in data.get("reads", [])))
                    target_name = (fragment.get("target") or {}).get("name")
                    pending = [fragment.get("expression")]
                    while pending and write_ids and target_name and not self_read:
                        item = pending.pop()
                        if isinstance(item, dict):
                            if item.get("op") in {"lambda", "body_reference"}:
                                continue
                            if item.get("op") == "reference" and (item.get("name") == target_name or item.get("name", "").startswith(target_name + ".")):
                                self_read = True
                            pending.extend(item.values())
                        elif isinstance(item, list):
                            pending.extend(item)
                    compound = fragment.get("assignmentOperator") in _ASSIGN - {"="}
                    relation.update(role="accumulator_update_candidate" if write_ids and (self_read or compound) else "assignment_in_loop",
                        declarationIds=sorted(write_ids), selfRead="compound_assignment" if compound else "rhs_reference" if self_read else "not_proven",
                        recurrenceValue="UNKNOWN", reachingDefinitions="UNKNOWN")
            relations.append(relation)
        if relations:
            fragment["loopRelations"] = relations
    for status in ("represented", "partial", "unsupported"):
        coverage[status + "Fragments"] = sum(f["representationStatus"] == status for f in result["fragments"])
    if literal_review is not None:
        retained = set()
        pending = list(result["fragments"])
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if isinstance(item.get("literalReview"), dict):
                    retained.add(item["literalReview"]["requestIndex"])
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        coverage["literalReviewDelivery"] = {"scope": "emitted_fragment_tree", "admittedEntries": len(admitted),
            "retainedOccurrences": len(retained & admitted), "notRetainedRequestIndices": sorted(admitted - retained),
            "completeForAdmitted": admitted <= retained, "semanticCompleteness": "UNKNOWN",
            "admissionMeaning": "permission_not_delivery_or_policy_completeness"}
    coverage["recordedFragments"] = len(result["fragments"])
    coverage["inventoryComplete"] = coverage["recordedFragments"] == coverage["detectedFragments"]
    coverage["reasons"] = sorted(set(coverage["reasons"]) | {"whole_policy_denominator_unknown", "static_fragments_not_business_rules"})
    for fragment in result["fragments"]:
        checks = fragment.get("platformInheritanceChecks")
        if isinstance(checks, list) and all(isinstance(check, dict) and isinstance(check.get("id"), str) for check in checks):
            checks.sort(key=lambda check: check["id"])
    finalize_dependencies(result, defer_external_dependencies=defer_external_dependencies,
        source_lookup=java_type_context.get("sourceDefinition") if java_type_context else None,
        owner_lookup=java_type_context.get("sourceDefinition") if java_type_context else None)
    relation_context = dict(java_type_context or {})
    if source_relation_context is not None and defer_external_dependencies:
        relation_context["sourceRelationBuildContext"] = source_relation_context
    _build_source_relations(result, tokens, relation_context, max_source_relations,
        defer_external_dependencies=defer_external_dependencies)
    privacy_guard.ensure_public_safe(result)
    return result


_DERIVED_EVIDENCE = frozenset({"staticType", "receiverStaticType", "staticContract",
    "ownerStaticType", "constantOwnerStaticType", "receiverConstantOwnerStaticType", "constructorStaticType", "accessorReturnStaticType",
    "staticAccessorBinding", "staticConstructorBinding", "staticFieldBinding", "receiverStaticFieldBinding",
    "standardConstant", "receiverStandardConstant", "recordConstruction", "constructorBindings", "recordShape", "collectionShape", "unitEvidence"})


def _dependency_nodes(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            yield item
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def finalize_literal_review(result, review):
    """Apply the final occurrence decision before snapshot-wide proof closure.

    A later file can revoke an earlier occurrence. Admission remains permission,
    never delivery: all copies of a revoked occurrence are retired together.
    """
    entries = review.coverage(result["path"])
    admitted = {e["requestIndex"] for e in entries["entries"] if e["status"] == "admitted"}
    for fragment in result.get("fragments", []):
        if any(isinstance(n.get("literalReview"), dict) and n["literalReview"].get("requestIndex") not in admitted
               for n in _dependency_nodes(fragment)):
            fragment.update(expression=None, references=[], representationStatus="unsupported", unsupportedReasons=["literal_review_revoked"])
            for key in ("target", "assignmentSemantics", "standardApiContracts", "platformTypeContracts", "platformInheritanceChecks", "platformTypeProofs", "platformInheritanceCoverage", "stageInitializer", "recordConstructorDeclarations", "loopRelations"):
                fragment.pop(key, None)
    retained = {n["literalReview"]["requestIndex"] for n in _dependency_nodes(result.get("fragments", []))
                if isinstance(n.get("literalReview"), dict)}
    coverage = result["coverage"]
    coverage["literalReview"] = entries
    coverage["literalReviewDelivery"] = {"scope": "emitted_fragment_tree", "admittedEntries": len(admitted),
        "retainedOccurrences": len(retained & admitted), "notRetainedRequestIndices": sorted(admitted - retained),
        "completeForAdmitted": admitted <= retained, "semanticCompleteness": "UNKNOWN",
        "admissionMeaning": "permission_not_delivery_or_policy_completeness"}
    return result


def finalize_dependencies(result, lookup=None, *, defer_external_dependencies=False, owner_lookup=None, source_lookup=None, inventory_lookup=None, source_relation_context=None):
    """Withdraw derived proof whose *emitted* source definition is unavailable.

    Mutates only derived annotations, never source syntax/literals or inventory.
    ``lookup(id, path)`` reads staged records, not source. The pipeline alone may
    defer cross-file checks while staging; it must call this again before seal.
    Cyclic/unbounded proof chains fail closed, without following runtime values.
    """
    fragments = result.get("fragments", [])
    seal_permit = None
    if source_relation_context is not None:
        if type(source_relation_context) is not SourceRelationBuildContext:
            raise SemanticError("source_relation_build_context_invalid")
        seal_permit = source_relation_context._consume(result, inventory_lookup)
    local = {f["id"]: f for f in fragments}
    duplicates = set()
    seen = set()
    for row in fragments:
        if row["id"] in seen: duplicates.add(row["id"])
        seen.add(row["id"])
    cache, loaded, examined = {}, {}, set()
    deferred_reason = "dependency_pending_snapshot_finalization"

    def source_range(value):
        return (isinstance(value, dict) and type(value.get("charStart")) is int
                and type(value.get("charEnd")) is int and 0 <= value["charStart"] < value["charEnd"])

    def load(identity, path=None):
        if identity in duplicates: return None
        if identity in local:
            return {**local[identity], "kind": "semantic_fragment"}
        key = (identity, path)
        if key not in loaded:
            # Cache only a small window of actual records, not every provider
            # AST in the scope. The independent evidence-visit budget remains
            # the existing per-file fragment bound.
            if len(loaded) >= 64: loaded.pop(next(iter(loaded)))
            loaded[key] = lookup(identity, path) if lookup is not None else source_lookup(identity, path) if source_lookup is not None else owner_lookup(identity, path) if owner_lookup is not None else None
        return loaded[key]

    def requirements(node, owner):
        items, field_ids, loop_ids, local_ids = [], set(), set(), set()
        for type_key, binding_key in (("staticType", "staticFieldBinding"), ("receiverStaticType", "receiverStaticFieldBinding")):
            typed, binding = node.get(type_key), node.get(binding_key)
            if (isinstance(typed, dict) and typed.get("basis") == "selected_static_final_field_declaration"
                    and (not isinstance(binding, dict) or binding.get("resolution") != "selected_static_final_field")):
                items.append((None, "field", {}))  # missing subproof never bypasses its validator
        for key in _DERIVED_EVIDENCE:
            value = node.get(key)
            if not isinstance(value, dict): continue
            if key in {"staticFieldBinding", "receiverStaticFieldBinding"} and value.get("resolution") == "selected_static_final_field":
                identity = value.get("declarationFragmentId")
                reported = node.get("staticType" if key == "staticFieldBinding" else "receiverStaticType")
                field_ids.add(identity); items.append((identity, "field", {**value, "_reportedStaticType": reported}))
            if key in {"staticType", "receiverStaticType"} and value.get("basis") == "explicit_enhanced_for_variable_type":
                for identity in value.get("sourceEvidenceIds", []):
                    if isinstance(identity, str) and identity.startswith("semantic:"):
                        loop_ids.add(identity); items.append((identity, "loop", value))
            if key in {"staticType", "receiverStaticType"} and value.get("basis") == "source_local_initializer_type":
                binding = value.get("localTypeBinding", {})
                identity = binding.get("declarationFragmentId")
                local_ids.add(identity); items.append((identity, "local_initializer", binding))
        emitted = set(field_ids | loop_ids | local_ids)
        for key in _DERIVED_EVIDENCE:
            for proof in _dependency_nodes(node.get(key)):
                for identity in proof.get("sourceEvidenceIds", []):
                    if not isinstance(identity, str) or identity in emitted: continue
                    if identity.startswith("semantic:") and identity != owner["id"]:
                        items.append((identity, "semantic", {})); emitted.add(identity)
                    elif lookup is not None and identity.startswith(("p:", "java-callsite:")):
                        items.append((identity, "symbol" if identity.startswith("p:") else "callsite", {})); emitted.add(identity)
        if lookup is not None:
            source_scopes, _ = policy_java_contracts.policy_java_platform.requirements(
                {key: node[key] for key in _DERIVED_EVIDENCE if key in node}, owner,
                lookup=load, api_validator=policy_java_contracts.validate_catalog_entry, allow_pending=defer_external_dependencies)
            items.extend((scope["sourceEvidenceId"], "platform_scope", scope) for scope in source_scopes)
        return items

    def validate(identity, kind, proof, owner, trail=()):
        if not isinstance(identity, str): return "source_dependency_definition_invalid"
        if identity not in examined and len(examined) >= MAX_FRAGMENTS:
            return "source_dependency_budget_exceeded"
        examined.add(identity)
        expected_path = proof.get("path") if kind in {"field", "local_initializer", "platform_scope"} else owner.get("path") if kind == "loop" else None
        expected_digest = proof.get("sourceDigest") if kind in {"field", "local_initializer", "platform_scope"} else owner.get("sourceDigest") if kind == "loop" else None
        # A propagated semantic ID may be cross-file. Its explicit binding,
        # encountered on the original child, supplies exact path/hash checks.
        row = load(identity, expected_path)
        if row is None and kind == "semantic" and lookup is not None:
            row = load(identity)
            expected_path = expected_digest = None
        if row is None:
            if lookup is None and defer_external_dependencies and kind == "field" and expected_path != result.get("path"):
                return deferred_reason
            if lookup is None and defer_external_dependencies and kind == "semantic" and identity not in local:
                # Only explicitly bound cross-file fields may be deferred.
                if identity in external_fields: return deferred_reason
            return "source_dependency_not_emitted"
        if (row.get("id") != identity or row.get("kind") != ("semantic_fragment" if kind in {"field", "loop", "semantic", "local_initializer"} else "symbol" if kind == "platform_scope" else kind)
                or not isinstance(row.get("path"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sourceDigest", "")))
                or (expected_path is not None and row.get("path") != expected_path)
                or (expected_digest is not None and row.get("sourceDigest") != expected_digest)):
            return "source_dependency_binding_mismatch"
        if kind == "platform_scope":
            if (row.get("qualifiedName") != proof.get("qualifiedName") or row.get("type") != proof.get("kind")
                    or row.get("declarationHeaderRange") != proof.get("sourceRange")):
                return "platform_source_scope_mismatch"
            if len(proof.get("parents", [])) != len(row.get("extendsTypes", [])) + len(row.get("implementsTypes", [])):
                return "platform_source_parent_mismatch"
            for edge in proof.get("parents", []):
                reference = edge.get("sourceParentReference", {})
                references = row.get(reference.get("relation", "") + "Types", [])
                position = reference.get("index")
                if (type(position) is not int or not 0 <= position < len(references)
                        or references[position].get("resolution") != "resolved"
                        or references[position].get("resolvedType") != edge.get("parentType")):
                    return "platform_source_parent_mismatch"
            return None
        if kind in {"symbol", "callsite"}:
            bounds = row.get("span", {})
            if kind == "callsite" and (row.get("resolution") != "exact" or not row.get("target")):
                return "source_dependency_definition_unavailable"
            return None if (type(bounds.get("lineStart")) is int and type(bounds.get("lineEnd")) is int
                            and 1 <= bounds["lineStart"] <= bounds["lineEnd"]) else "source_dependency_definition_invalid"
        bounds = row.get("sourceRange")
        if (not source_range(bounds) or identity != _id(row["path"], row["sourceDigest"], row.get("category"), bounds["charStart"], bounds["charEnd"])):
            return "source_dependency_definition_invalid"
        if kind == "field":
            initializer = proof.get("initializerEvidence", {})
            init_range = initializer.get("sourceRange")
            if (row.get("category") != "constant" or row.get("name") != proof.get("name") or bounds != proof.get("sourceRange")
                    or initializer.get("fragmentId") != identity or not source_range(init_range)
                    or not bounds["charStart"] < init_range["charStart"] < init_range["charEnd"] < bounds["charEnd"]):
                return "source_dependency_definition_invalid"
            # The index selected a declaration, but the final consumer must
            # join its exact actual emitted type and owner on every use. FQN
            # types may need no platform-absence catalog, so that optional
            # projection cannot be the only provenance validation path.
            reported = proof.get("_reportedStaticType")
            owner_proof = proof.get("declaringOwner")
            owner_keys = {"id", "qualifiedName", "type", "path", "sourceDigest", "declarationHeaderRange",
                          "sourceRange", "declarationRange", "bodyRange"}
            if (type(proof.get("declarationProofVersion")) is not int or proof["declarationProofVersion"] != 1
                    or not isinstance(proof.get("declaredType"), str) or row.get("declaredType") != proof["declaredType"]
                    or not isinstance(reported, dict) or reported.get("resolution") != "resolved_static_type"
                    or not isinstance(proof.get("resolvedType"), str) or reported.get("name") != proof["resolvedType"]
                    or not isinstance(owner_proof, dict) or set(owner_proof) != owner_keys
                    or not isinstance(owner_proof.get("id"), str) or not owner_proof["id"].startswith("p:")
                    or owner_proof.get("qualifiedName") != proof.get("declaringType")
                    or owner_proof.get("path") != row["path"] or owner_proof.get("sourceDigest") != row["sourceDigest"]
                    or not isinstance(reported.get("sourceEvidenceIds"), list)
                    or any(not isinstance(item, str) for item in reported["sourceEvidenceIds"])
                    or owner_proof["id"] not in reported["sourceEvidenceIds"]
                    or identity not in reported.get("sourceEvidenceIds", [])
                    or proof.get("runtimeValue") != "UNKNOWN" or proof.get("valueSubstitution") is not False):
                return "source_field_declaration_type_or_owner_proof_invalid"
            owner_identity = owner_proof["id"]
            if owner_identity not in examined and len(examined) >= MAX_FRAGMENTS:
                return "source_dependency_budget_exceeded"
            examined.add(owner_identity)
            definition = load(owner_identity, row["path"])
            if definition is None:
                return deferred_reason if defer_external_dependencies and row["path"] != result.get("path") else "source_field_owner_not_emitted"
            if (definition.get("id") != owner_identity or definition.get("kind") != "symbol"
                    or definition.get("basis") != "declared" or definition.get("status") != "runtime_unknown"
                    or definition.get("structuralOnly") or definition.get("representationStatus") == "unsupported"
                    or definition.get("dependencyClosure", {}).get("status") in {"invalidated", "pending_snapshot_finalization"}
                    or any(definition.get(key) != owner_proof[key] for key in owner_keys)):
                return "source_field_owner_definition_mismatch"
            if not policy_java_contracts.policy_java_platform.source_type_matches(
                    row["declaredType"], proof["resolvedType"], definition):
                return "source_field_declared_type_resolution_mismatch"
            header, declaration, body = (owner_proof[key] for key in ("declarationHeaderRange", "declarationRange", "bodyRange"))
            if (owner_proof["type"] not in {"Class", "Interface", "Record", "Enum", "Annotation"}
                    or not all(source_range(value) for value in (header, declaration, body))
                    or owner_proof["sourceRange"] != declaration
                    or not declaration["charStart"] == header["charStart"] < body["charStart"] < header["charEnd"]
                    or header["charEnd"] != body["charStart"] + 1
                    or not body["charStart"] < bounds["charStart"] < bounds["charEnd"] < body["charEnd"] == declaration["charEnd"]):
                return "source_field_owner_containment_invalid"
        expr = row.get("expression")
        if kind == "local_initializer":
            init_range, scope_range = proof.get("initializerRange"), proof.get("lexicalScopeRange")
            inferred = (expr or {}).get("staticType", {})
            if (row.get("category") != "local_declaration" or row.get("declaredType") != "var"
                    or row.get("declarationGroupSpan") or row.get("name") != proof.get("name")
                    or proof.get("sourceRange") != bounds or proof.get("declarationFragmentId") != identity
                    or proof.get("status") != "source_initializer_static_type"
                    or type(proof.get("dependencyDepth")) is not int or not 1 <= proof["dependencyDepth"] <= MAX_EXPRESSION_DEPTH
                    or proof.get("sourceEvidenceIds") != [identity]
                    or row.get("localTypeInference") != proof or not source_range(init_range) or not source_range(scope_range)
                    or not scope_range["charStart"] <= bounds["charStart"] < init_range["charStart"] < init_range["charEnd"] <= bounds["charEnd"] <= scope_range["charEnd"]
                    or inferred.get("resolution") != "resolved_static_type"
                    or inferred.get("name") != proof.get("inferredType")
                    or inferred.get("name") in {None, "void", "java.lang.void", "null", "UNKNOWN"}
                    or inferred.get("typeArgumentsStatus", "resolved") not in {"resolved", "raw"}):
                return "source_local_initializer_definition_unavailable"
            lexical = proof.get("lexicalOwner")
            lexical = lexical if isinstance(lexical, dict) else {}
            owner_keys = {"kind", "typeSymbolId", "callableSymbolId", "typeDeclarationRange", "typeBodyRange",
                          "callableDeclarationRange", "callableBodyRange"}
            callable_range, type_range = lexical.get("callableBodyRange"), lexical.get("typeBodyRange")
            callable_declaration, type_declaration = lexical.get("callableDeclarationRange"), lexical.get("typeDeclarationRange")
            source_length = result.get("sourceLength")
            def bounded_range(value):
                return source_range(value) and type(source_length) is int and value["charEnd"] <= source_length
            row_owner = row.get("controlFlow", {}).get("owner") or {}
            if (set(lexical) != owner_keys or lexical.get("kind") != "indexed_named_type_callable"
                    or not all(bounded_range(value) for value in (callable_range, type_range, callable_declaration, type_declaration, scope_range, bounds))
                    or lexical.get("callableSymbolId") != row_owner.get("id")
                    or row_owner.get("resolution") != "source_callable_definition" or row_owner.get("sourceRange") != callable_declaration
                    or not type_declaration["charStart"] < type_range["charStart"] < callable_declaration["charStart"] < callable_range["charStart"]
                    or not callable_range["charStart"] <= scope_range["charStart"] <= bounds["charStart"]
                    or not bounds["charEnd"] <= scope_range["charEnd"] <= callable_range["charEnd"] == callable_declaration["charEnd"] < type_range["charEnd"] == type_declaration["charEnd"]
                    or not all(isinstance(lexical.get(key), str) and lexical[key].startswith("p:") for key in ("typeSymbolId", "callableSymbolId"))):
                return "source_local_initializer_owner_unavailable"
            # Only actual projected owner definitions can support a join. A
            # staged lookup, when supplied, always wins over extraction state.
            symbols = []
            for key in ("typeSymbolId", "callableSymbolId"):
                owner_identity = lexical[key]
                if owner_identity not in examined and len(examined) >= MAX_FRAGMENTS:
                    return "source_dependency_budget_exceeded"
                examined.add(owner_identity)
                definition = load(owner_identity, row["path"])
                symbols.append(definition)
            type_symbol, callable_symbol = symbols
            for definition, identity_key, declaration_range, body_range in (
                    (type_symbol, "typeSymbolId", type_declaration, type_range),
                    (callable_symbol, "callableSymbolId", callable_declaration, callable_range)):
                if (not isinstance(definition, dict) or definition.get("id") != lexical[identity_key]
                        or definition.get("kind") != "symbol" or definition.get("path") != row["path"]
                        or definition.get("sourceDigest") != row["sourceDigest"] or definition.get("basis") != "declared"
                        or definition.get("status") != "runtime_unknown" or definition.get("structuralOnly")
                        or definition.get("dependencyClosure", {}).get("status") in {"invalidated", "pending_snapshot_finalization"}
                        or definition.get("sourceRange") != declaration_range or definition.get("declarationRange") != declaration_range
                        or definition.get("bodyRange") != body_range):
                    return "source_local_initializer_definition_range_unavailable"
                declaration_span, body_span = definition.get("declarationSpan", {}), definition.get("bodySpan", {})
                if (not all(type(value) is int and value >= 1 for value in (declaration_span.get("lineStart"), declaration_span.get("lineEnd"), body_span.get("lineStart"), body_span.get("lineEnd")))
                        or not declaration_span["lineStart"] <= body_span["lineStart"] <= body_span["lineEnd"] <= declaration_span["lineEnd"]):
                    return "source_local_initializer_definition_range_unavailable"
            if (callable_symbol.get("type") not in {"Method", "Constructor"}
                    or type_symbol.get("type") not in {"Class", "Interface", "Enum", "Record"}
                    or callable_symbol.get("owner") != type_symbol.get("qualifiedName")
                    or callable_symbol.get("name") != row_owner.get("name")):
                return "source_local_initializer_owner_unavailable"
            usage, use_owner = owner.get("sourceRange"), owner.get("controlFlow", {}).get("owner") or {}
            if owner.get("id") != identity and (owner.get("path") != row["path"]
                    or owner.get("sourceDigest") != row["sourceDigest"] or not bounded_range(usage)
                    or use_owner.get("id") != lexical["callableSymbolId"] or use_owner.get("name") != callable_symbol.get("name")
                    or use_owner.get("resolution") != "source_callable_definition" or use_owner.get("sourceRange") != callable_declaration
                    or not bounds["charEnd"] <= usage["charStart"] < usage["charEnd"] <= scope_range["charEnd"]):
                return "source_local_initializer_use_scope_unproven"
        if kind == "loop" or row.get("category") == "condition":
            if not isinstance(expr, dict) or expr.get("op") != "enhanced_for":
                return "source_dependency_definition_unavailable"
            variable, body = expr.get("variable", {}), expr.get("body", {})
            vr, br = variable.get("sourceRange"), body.get("sourceRange")
            if (variable.get("binding") != "explicit_source_declaration" or not source_range(vr) or not source_range(br)
                    or variable.get("id") != _id(row["path"], row["sourceDigest"], "iteration_variable", vr["charStart"], vr["charEnd"]).replace("semantic:", "source-binding:", 1)
                    or body.get("id") != _id(row["path"], row["sourceDigest"], "loop_body", br["charStart"], br["charEnd"]).replace("semantic:", "source-body:", 1)
                    or body.get("path") != row["path"] or body.get("sourceDigest") != row["sourceDigest"]
                    or not bounds["charStart"] <= vr["charStart"] < vr["charEnd"] <= bounds["charEnd"] <= br["charStart"]):
                return "source_dependency_definition_invalid"
            scope = proof.get("variableScope")
            if scope and (not source_range(scope) or not br["charStart"] <= scope["charStart"] < scope["charEnd"] <= br["charEnd"]):
                return "source_dependency_definition_invalid"
        if (row.get("structuralOnly") or row.get("dependencyClosure", {}).get("status") == "invalidated"
                or (expr is None and not (kind == "semantic" and row.get("declaredType") and row.get("unsupportedReasons") == ["initializer_absent"]))):
            return "source_dependency_definition_unavailable"
        key = (identity, row["sourceDigest"])
        if key in trail: return "source_dependency_cycle"
        if len(trail) >= MAX_EXPRESSION_DEPTH: return "source_dependency_depth_exceeded"
        if key not in cache:
            reasons = set()
            for child in _dependency_nodes(expr):
                constructor_failure = constructor_reason(child, row)
                if constructor_failure: reasons.add(constructor_failure)
                for next_id, next_kind, next_proof in requirements(child, row):
                    reason = validate(next_id, next_kind, next_proof, row, trail + (key,))
                    if reason: reasons.add(reason)
            cache[key] = (sorted(reasons - {deferred_reason}) or sorted(reasons) or [None])[0]
        return cache[key]

    def constructor_reason(node, fragment):
        binding = node.get("recordConstruction")
        if not isinstance(binding, dict) or not binding.get("declarationId"): return None
        declarations = [d for d in fragment.get("recordConstructorDeclarations", []) if d.get("id") == binding["declarationId"]]
        if len(declarations) != 1: return "source_constructor_definition_unavailable"
        declaration = declarations[0]; bounds = declaration.get("sourceRange")
        if (not source_range(bounds) or not isinstance(declaration.get("path"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(declaration.get("sourceDigest", "")))
                or declaration["id"] != "source-record-constructor:" + hashlib.sha256(_canonical([
                    declaration["path"], declaration["sourceDigest"], bounds["charStart"]])).hexdigest()):
            return "source_constructor_definition_invalid"
        for index, parameter in enumerate(declaration.get("parameters", [])):
            pr = parameter.get("sourceRange")
            if (parameter.get("index") != index or not source_range(pr)
                    or not bounds["charStart"] <= pr["charStart"] < pr["charEnd"] <= bounds["charEnd"]):
                return "source_constructor_definition_invalid"
        if lookup is not None:
            record = load(declaration.get("recordDeclarationId"), declaration["path"])
            if (not record or record.get("kind") != "symbol" or record.get("path") != declaration["path"]
                    or record.get("sourceDigest") != declaration["sourceDigest"]):
                return "source_constructor_definition_unavailable"
        return None

    retained_marker = "independent_numeric_literal_branch_type_only"
    retained_status = {"status": "UNKNOWN", "reason": "source_dependency_unavailable", "retainedEvidence": retained_marker}

    def independent_conditional_type(node, fragment, location, *, revalidate=False):
        """Revalidate just a literal-branch type after dependent child cleanup.

        A basis label is not a proof. Re-read the emitted owner at this exact
        consumer, then rederive both literal types using the producer's rules.
        Platform/source-dependent origins and reviewed/redacted literals are
        deliberately outside this small independent closure.
        """
        typed = node.get("staticType")
        bounds = fragment.get("sourceRange")
        allowed = {"op", "condition", "then", "else"} | _DERIVED_EVIDENCE
        if revalidate:
            if node.get("staticEvidenceStatus") != retained_status: return False
            allowed = allowed | {"staticEvidenceStatus"}

        def unavailable_owner(owner, consumer):
            closure = owner.get("dependencyClosure", {})
            if owner.get("structuralOnly") or owner.get("representationStatus") == "unsupported": return True
            if closure.get("status") == "pending_snapshot_finalization": return True
            if closure.get("status") != "invalidated": return False
            # A previously emitted partial owner is usable only for this same
            # retained slot, never as a generally restored dependency provider.
            return not (revalidate and isinstance(consumer, dict)
                and consumer.get("staticEvidenceStatus") == retained_status
                and owner.get("representationStatus") == "partial"
                and closure.get("scope") == "derived_static_evidence"
                and isinstance(closure.get("reasons"), list) and bool(closure["reasons"])
                and type(closure.get("invalidatedNodes")) is int and closure["invalidatedNodes"] > 0)

        if (lookup is None or defer_external_dependencies or node.get("op") != "conditional"
                or set(node) - allowed
                or not isinstance(typed, dict) or typed.get("basis") != "identical_conditional_operand_types"
                or fragment.get("id") in duplicates or unavailable_owner(fragment, node)
                or fragment.get("path") != result.get("path") or fragment.get("sourceDigest") != result.get("sourceDigest")
                or not isinstance(fragment.get("path"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(fragment.get("sourceDigest", "")))
                or not source_range(bounds)
                or fragment.get("id") != _id(fragment["path"], fragment["sourceDigest"], fragment.get("category"), bounds["charStart"], bounds["charEnd"])):
            return False
        # Do not use load(): its local-record shortcut cannot independently
        # establish that the current consumer was actually emitted.
        emitted = lookup(fragment["id"], fragment["path"])
        if (not isinstance(emitted, dict) or emitted is fragment or emitted.get("kind") != "semantic_fragment"
                or any(emitted.get(key) != fragment.get(key) for key in
                       ("id", "path", "sourceDigest", "sourceRange", "category", "span", "controlFlow"))):
            return False
        platform = policy_java_contracts.policy_java_platform
        original = platform.pointer(emitted, location)
        if (platform.pointer(fragment, location) is not node or not isinstance(original, dict) or original is node
                or set(original) - allowed or unavailable_owner(emitted, original)
                or ("staticEvidenceStatus" in original and original["staticEvidenceStatus"] != retained_status)
                or original.get("op") != "conditional" or original.get("staticType") != typed):
            return False
        probe = {"op": "conditional", "condition": None}
        for branch in ("then", "else"):
            literal = node.get(branch)
            if (not isinstance(literal, dict) or set(literal) != {"op", "type", "value", "javaSuffix", "staticType"}
                    or literal is original.get(branch) or literal != original.get(branch) or literal.get("op") != "literal"
                    or literal.get("type") not in ("integer", "floating")
                    or not isinstance(literal.get("value"), str)
                    or literal.get("javaSuffix") not in (None, "l", "L", "f", "F", "d", "D")
                    or (literal["type"] == "floating" and literal["javaSuffix"] in {"l", "L"})):
                return False
            raw = {key: value for key, value in literal.items() if key != "staticType"}
            spelling = literal["value"] + (literal["javaSuffix"] or "")
            try:
                if _numeric(_Token(spelling, 0, len(spelling), "number")) != raw: return False
            except _Unsupported:
                return False
            probe[branch] = raw
        # These callbacks cannot supply source, platform, or call evidence.
        unavailable = lambda *_: None
        policy_java_contracts.enrich(probe, reference_type=unavailable,
            type_name=unavailable, call_result=unavailable, fragment_id=fragment["id"])
        if (probe.get("staticType") != typed
                or any(probe[branch].get("staticType") != node[branch].get("staticType") for branch in ("then", "else"))):
            return False
        # Validate current consumers again, after cleanup. Any added platform
        # origin must pass the ordinary validator; absent proof never suffices.
        for current in (node, node["then"], node["else"]):
            value = {"staticType": current["staticType"]}
            if any(validate(identity, kind, proof, fragment)
                   for identity, kind, proof in requirements(value, fragment)):
                return False
            _, failure = platform.requirements(value, fragment, lookup=load,
                api_validator=policy_java_contracts.validate_catalog_entry, _complete_lookup=True)
            if failure: return False
        return True

    external_fields = {n[key].get("declarationFragmentId") for row in fragments for n in _dependency_nodes(row.get("expression"))
        for key in ("staticFieldBinding", "receiverStaticFieldBinding") if isinstance(n.get(key), dict)
        and n[key].get("resolution") == "selected_static_final_field" and n[key].get("path") != result.get("path")}
    total_invalidated = total_pending = 0
    for fragment in fragments:
        reasons, pending_reasons = set(), set()
        prior = fragment.get("dependencyClosure", {})
        invalidated = 0

        def clean(node, location):
            nonlocal invalidated
            if isinstance(node, list):
                return any_flags([clean(child, location + "/" + str(index)) for index, child in enumerate(node)])
            if not isinstance(node, dict): return False
            was_retained = (isinstance(node.get("staticEvidenceStatus"), dict)
                and node["staticEvidenceStatus"].get("retainedEvidence") == retained_marker)
            own_reasons = {reason for identity, kind, proof in requirements(node, fragment)
                           if (reason := validate(identity, kind, proof, fragment))}
            _, platform_failure = policy_java_contracts.policy_java_platform.requirements(
                {key: node[key] for key in _DERIVED_EVIDENCE if key in node}, fragment,
                lookup=load, api_validator=policy_java_contracts.validate_catalog_entry,
                allow_pending=defer_external_dependencies, _complete_lookup=lookup is not None)
            if platform_failure: own_reasons.add(platform_failure)
            constructor_failure = constructor_reason(node, fragment)
            if constructor_failure: own_reasons.add(constructor_failure)
            pending_reasons.update(own_reasons & {deferred_reason})
            own_reasons.discard(deferred_reason)
            child_invalid = any_flags([clean(child, location + "/" + key.replace("~", "~0").replace("/", "~1"))
                for key, child in list(node.items()) if key not in _DERIVED_EVIDENCE])
            invalid = bool(own_reasons or child_invalid)
            retained_type = (not own_reasons and (invalid or was_retained)
                and independent_conditional_type(node, fragment, location, revalidate=was_retained))
            if invalid and any(key in node for key in _DERIVED_EVIDENCE):
                withdrawn = [key for key in _DERIVED_EVIDENCE if key in node and not (key == "staticType" and retained_type)]
                for key in withdrawn: node.pop(key, None)
                node["staticEvidenceStatus"] = {"status": "UNKNOWN", "reason": "source_dependency_unavailable"}
                if retained_type:
                    node["staticEvidenceStatus"]["retainedEvidence"] = retained_marker
                if node.get("op") == "call":
                    node["staticContractStatus"] = {"status": "UNKNOWN", "reason": "source_dependency_unavailable"}
                invalidated += bool(withdrawn)
            elif was_retained and not retained_type:
                # A previous pass already removed the failing condition proof.
                # Recheck this positive slot even when there is no new child
                # failure; freshness loss alone must not clear unrelated slots.
                withdrawn = "staticType" in node
                node.pop("staticType", None)
                node["staticEvidenceStatus"].pop("retainedEvidence", None)
                invalidated += withdrawn
                invalid = invalid or withdrawn
            reasons.update(own_reasons)
            return invalid

        def any_flags(flags):
            return any(flags)  # materialize first: every sibling must be checked

        clean(fragment.get("expression"), "/expression")
        clean(fragment.get("target"), "/target")
        local_binding = fragment.get("localTypeInference", {})
        if local_binding.get("status") == "source_initializer_static_type":
            local_reason = validate(fragment["id"], "local_initializer", local_binding, fragment)
            if local_reason and local_reason != deferred_reason:
                fragment["localTypeInference"] = {"status": "UNKNOWN", "reason": local_reason,
                    "specification": local_binding["specification"], "runtimeValue": "UNKNOWN", "definiteAssignment": "UNKNOWN"}
        if "stageInitializer" in fragment and not (fragment.get("expression") or {}).get("staticType", {}).get("sourceStageIdentity"):
            fragment.pop("stageInitializer")
        if invalidated or prior.get("status") == "invalidated":
            reasons.update(prior.get("reasons", []))
            fragment["dependencyClosure"] = {"status": "invalidated", "scope": "derived_static_evidence",
                "reasons": sorted(reasons), "invalidatedNodes": invalidated + prior.get("invalidatedNodes", 0)}
            if fragment.get("expression") is not None: fragment["representationStatus"] = "partial"
            fragment["unsupportedReasons"] = sorted(set(fragment.get("unsupportedReasons", [])) | {"source_dependency_unavailable"})
        elif pending_reasons:
            fragment["dependencyClosure"] = {"status": "pending_snapshot_finalization", "scope": "derived_static_evidence"}
        else:
            fragment.pop("dependencyClosure", None)
        # Catalog entries are retained only when a surviving node references
        # them. Independent sibling contracts and literals remain unchanged.
        live_nodes = list(_dependency_nodes(fragment.get("expression")))
        used_contracts = {n["staticContract"]["contractId"] for n in live_nodes if isinstance(n.get("staticContract"), dict)}
        used_constructors = {n["recordConstruction"].get("declarationId") for n in live_nodes if isinstance(n.get("recordConstruction"), dict)}
        for key, used in (("standardApiContracts", used_contracts), ("recordConstructorDeclarations", used_constructors)):
            if key in fragment:
                fragment[key] = [item for item in fragment[key] if item["id"] in used]
                if not fragment[key]: fragment.pop(key)
        policy_java_contracts.policy_java_platform.prune(fragment)
        total_invalidated += fragment.get("dependencyClosure", {}).get("status") == "invalidated"
        total_pending += fragment.get("dependencyClosure", {}).get("status") == "pending_snapshot_finalization"
    # Revocation can occur after the first extraction of a different file. Do
    # not retain body/binder joins to a header whose inline definitions retired.
    for fragment in fragments:
        for context in fragment.get("controlFlow", {}).get("contexts", []):
            if "loopBodyId" in context and validate(context.get("fragmentId"), "loop", {}, fragment):
                context.pop("loopBodyId", None); context.pop("bodyDefinition", None)
                context["bodyBindingStatus"] = {"status": "UNKNOWN", "reason": "source_dependency_unavailable"}
        if "loopRelations" in fragment:
            fragment["loopRelations"] = [r for r in fragment["loopRelations"]
                if not validate(r.get("loopFragmentId"), "loop", {}, fragment)]
            if not fragment["loopRelations"]: fragment.pop("loopRelations")
    coverage = result["coverage"]
    local_declarations = [f for f in fragments if f.get("category") == "local_declaration" and f.get("declaredType") == "var"]
    if local_declarations:
        inferred_count = sum(f.get("localTypeInference", {}).get("status") == "source_initializer_static_type" for f in local_declarations)
        coverage["localTypeInference"] = {"scope": "emitted_var_local_declarations", "denominator": len(local_declarations),
            "resolved": inferred_count, "unknown": len(local_declarations) - inferred_count,
            "omittedDeclarations": "reported_separately_in_original_fragment_inventory", "wholeTypeCoverage": "UNKNOWN"}
    coverage["dependencyClosure"] = {"status": "pending_snapshot_finalization" if total_pending else "finalized",
        "scope": "emitted_source_definitions_not_runtime_values", "invalidatedFragments": total_invalidated,
        "pendingFragments": total_pending, "runtimeMeaning": "UNKNOWN"}
    for status in ("represented", "partial", "unsupported"):
        coverage[status + "Fragments"] = sum(f["representationStatus"] == status for f in fragments)
    if total_invalidated:
        coverage["reasons"] = sorted(set(coverage.get("reasons", [])) | {"source_dependency_unavailable"})
    finalize_source_relations(result, lookup=load, inventory_lookup=inventory_lookup, _seal_permit=seal_permit)
    return result


def _split(tokens: list[_Token], start: int, end: int, separator: str, *, angles: bool = True):
    depth = 0
    first = start
    for index in range(start, end):
        if tokens[index].value in {"(", "[", "{"} or (angles and tokens[index].value == "<"):
            depth += 1
        elif tokens[index].value in {")", "]", "}"}:
            depth -= 1
        elif angles and tokens[index].value in {">", ">>", ">>>"}:
            depth -= len(tokens[index].value)
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


def _declarators(tokens: list[_Token], start: int, end: int) -> list[dict[str, Any]]:
    """Split one Java declaration without mistaking generic/argument commas."""
    eq = _top_level_operator(tokens, start, end, {"="})
    if eq is None:
        return []
    header = [t for t in tokens[start:eq] if t.value not in _MODIFIERS]
    if (len(header) < 2 or header[-1].kind != "name" or header[-2].value == "."
            or not all(t.kind == "name" or t.value in {".", "<", ">", ">>", ">>>", "?", "[", "]", ","} for t in header[:-1])):
        return []
    declared_type = "".join(t.value for t in header[:-1])
    is_final = any(t.value == "final" for t in tokens[start:eq])
    boundaries = []
    depth = 0
    for index in range(eq + 1, end):
        value = tokens[index].value
        if value in {"(", "[", "{"}: depth += 1
        elif value in {")", "]", "}"}: depth -= 1
        elif depth == 0 and value == "," and index + 1 < end and tokens[index + 1].kind == "name":
            following = index + 2
            while following + 1 < end and tokens[following].value == "[" and tokens[following + 1].value == "]":
                following += 2
            if following == end or tokens[following].value in {"=", ","}:
                boundaries.append(index)
    if not boundaries:
        return []
    parts = []
    first = start
    name = header[-1].value
    for boundary in boundaries + [end]:
        parts.append({"start": first, "end": boundary, "name": name, "declaredType": declared_type, "final": is_final})
        first = boundary + 1
        if first < end:
            name = tokens[first].value
    return parts

# Versioned, bounded source relations reference the emitted IR. No source body,
# literal value, evaluated value or application interpretation is copied here.
SOURCE_RELATION_VERSION = "source-relations-3"
MAX_SOURCE_RELATIONS = 40_000
MAX_SOURCE_RELATION_REFS = 256
MAX_SOURCE_RELATION_FRAGMENT_BYTES = 48 * 1024
MAX_SOURCE_RELATION_RECORD_BYTES = 192 * 1024
_SOURCE_RELATION_KINDS = frozenset({"constructor_parameter_component_transfer", "helper_return_source_summary",
    "straight_line_reaching_definition", "lexical_return_guard", "enum_constant_declaration_position",
    "array_element_source_position", "enum_array_initial_source_association", "callback_body_reference"})


def _source_pointer(value, pointer):
    # RFC 6901 root pointers bind the complete non-recursive provider record.
    # A semantic-fragment root would recursively include its own relations.
    if pointer == "":
        if isinstance(value, dict) and value.get("kind") in {"symbol", "callsite"} and "sourceRelations" not in value:
            return value
        raise ValueError("source_relation_root_pointer_invalid")
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("source_relation_pointer_invalid")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdigit() or str(int(part)) != part:
                raise ValueError("source_relation_pointer_invalid")
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise ValueError("source_relation_pointer_invalid")
    return value


_SOURCE_INPUT_TRANSPORT_KEYS = frozenset({"kind", "module", "modulePath", "language", "basis", "status"})


def _source_fragment_input(row):
    """Closed original fragment input, with only specified transport excluded.

    The name-presence marker distinguishes an absent source name from the
    serializer's category-name fallback. Unknown/new source fields are included
    automatically; optional absence therefore cannot silently evade the seal.
    """
    if not isinstance(row, dict) or type(row.get("sourceRelationInputNamePresent")) is not bool:
        raise ValueError("source_relation_input_marker_invalid")
    # Availability diagnostics are bound separately for every owner/provider.
    # They are not the source syntax of unrelated fragments in this file.
    value = {k: v for k, v in row.items() if k not in _SOURCE_INPUT_TRANSPORT_KEYS
        and k not in {"sourceRelations", "dependencyClosure", "representationStatus", "unsupportedReasons"}}
    if not row["sourceRelationInputNamePresent"]:
        if "name" in value and value["name"] != row.get("category"):
            raise ValueError("source_relation_input_name_invalid")
        value.pop("name", None)
    elif "name" not in value:
        raise ValueError("source_relation_input_name_invalid")
    return value


def _source_input_closure(result, inventory):
    fragments = result.get("fragments", [])
    if (not isinstance(inventory, (list, tuple)) or any(not isinstance(row, dict) for row in inventory)
            or any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or row.get("path") != result["path"] or row.get("sourceDigest") != result["sourceDigest"] for row in fragments)):
        raise ValueError("source_relation_input_inventory_invalid")
    ids = [row["id"] for row in fragments]
    if len(ids) != len(set(ids)):
        raise ValueError("source_relation_input_duplicate")
    coverage = result.get("coverage", {})
    selected = {key: coverage[key] for key in ("detectedFragments", "recordedFragments", "inventoryComplete")}
    if (type(selected["detectedFragments"]) is not int or type(selected["recordedFragments"]) is not int
            or type(selected["inventoryComplete"]) is not bool or selected["recordedFragments"] != len(fragments)
            or selected["detectedFragments"] < selected["recordedFragments"]
            or selected["inventoryComplete"] != (selected["detectedFragments"] == selected["recordedFragments"])):
        raise ValueError("source_relation_input_coverage_invalid")
    payload = {"version": "source-relation-inputs-2", "path": result["path"], "sourceDigest": result["sourceDigest"],
        "inventoryCoverage": selected, "fragments": [_source_fragment_input(row) for row in sorted(fragments, key=lambda row: row["id"])]}
    providers = [row for row in inventory if row.get("kind") in {"symbol", "callsite"}]
    if (len({row["id"] for row in providers}) != len(providers)
            or any(row.get("path") != result["path"] or row.get("sourceDigest") != result["sourceDigest"]
                or "sourceRelations" in row for row in providers)):
        raise ValueError("source_relation_provider_inventory_invalid")
    provider_payload = {"version": "source-relation-providers-1", "path": result["path"], "sourceDigest": result["sourceDigest"],
        "providers": sorted(providers, key=lambda row: row["id"])}
    return {"version": "source-relation-inputs-2", "fragmentCount": len(ids), "providerCount": len(providers), "inventoryCoverage": selected,
        "fragmentInventorySha256": hashlib.sha256(_canonical(payload)).hexdigest(),
        "providerInventorySha256": hashlib.sha256(_canonical(provider_payload)).hexdigest()}


def _source_admissibility(row, *, semantic=False):
    """Fixed cause codes only; never copy a provider's payload into diagnostics."""
    raw_reasons = row.get("unsupportedReasons", [])
    if not isinstance(raw_reasons, list) or any(not isinstance(reason, str) for reason in raw_reasons):
        return "unknown", "representation_unavailable"
    reasons = set(raw_reasons)
    if reasons & {"literal_review_revoked", "local_source_access_revoked", "source_disclosure_permission_revoked"}:
        return "denied", "permission_revoked"
    if reasons & {"sensitive_value_redacted", "privacy_denied", "metadata_privacy_denied", "protected_source_evidence"}:
        return "denied", "privacy_withheld"
    closure = row.get("dependencyClosure", {})
    if not isinstance(closure, dict): return "unknown", "representation_unavailable"
    dependency = closure.get("status")
    if dependency == "invalidated": return "unknown", "dependency_invalidated"
    if dependency == "pending_snapshot_finalization": return "unknown", "dependency_pending"
    if "dependencyClosure" in row: return "unknown", "representation_unavailable"
    if row.get("representationStatus") == "unsupported": return "unsupported", "parser_unsupported"
    if semantic and row.get("representationStatus") not in {"represented", "partial"}:
        return "unknown", "representation_unavailable"
    return None


def _source_admissibility_state(row):
    kind = row.get("kind")
    if kind is None and "category" in row: kind = "semantic_fragment"
    if kind not in {"symbol", "callsite", "semantic_fragment"}: raise ValueError("source_relation_provider_kind_invalid")
    return {"version": "source-relation-admissibility-1", "recordId": row["id"], "path": row["path"],
        "sourceDigest": row["sourceDigest"], "kind": kind,
        "fields": {key: {"present": key in row, "value": row.get(key)}
            for key in ("representationStatus", "unsupportedReasons", "dependencyClosure")}}


def _source_admissibility_descriptor(owner, relation, load, cache=None):
    identities = sorted(set(relation.get("sourceEvidenceIds", [])) | {owner["id"]})
    paths = {ref["recordId"]: ref["path"] for ref in relation.get("sourceEvidenceRefs", [])}
    states = []
    for identity in identities:
        row = owner if identity == owner["id"] else load(identity, paths.get(identity))
        if not isinstance(row, dict): raise ValueError("source_relation_provider_unavailable")
        if cache is None or identity not in cache:
            state = _source_admissibility_state(row)
            if cache is not None: cache[identity] = state
        else: state = cache[identity]
        states.append(state)
    payload = {"version": "source-relation-admissibility-1", "ownerRecordId": owner["id"], "states": states}
    return {"version": "source-relation-admissibility-1", "status": "sealed", "ownerRecordId": owner["id"],
        "recordCount": len(states), "statesSha256": hashlib.sha256(_canonical(payload)).hexdigest()}


def _source_relation_bundle(result):
    return hashlib.sha256(_canonical({"path": result["path"], "sourceDigest": result["sourceDigest"],
        "owners": [{"ownerRecordId": row["id"], "sourceRelations": row["sourceRelations"]}
            for row in sorted(result.get("fragments", []), key=lambda row: row["id"]) if "sourceRelations" in row]})).hexdigest()


class SourceRelationBuildContext:
    """Non-serialized one-build authority for the *first* final-IR seal only."""
    def __init__(self): self._files = {}; self._consumed = set()

    def _register_new_extraction(self, result, input_closure):
        key = (result["path"], result["sourceDigest"])
        if key in self._files or key in self._consumed: raise SemanticError("source_relation_build_context_reused")
        self._files[key] = (_source_relation_bundle(result), json.loads(_canonical(input_closure)))

    def _consume(self, result, inventory_lookup):
        key = (result["path"], result["sourceDigest"])
        registered = self._files.pop(key, None); self._consumed.add(key)
        if registered is None or inventory_lookup is None: return None
        try:
            current = _source_input_closure(result, inventory_lookup(result["path"]))
            if _source_relation_bundle(result) != registered[0] or current != registered[1]: return None
            return _SourceRelationSealPermit(result, current)
        except (KeyError, ValueError, TypeError, RecursionError): return None


class _SourceRelationSealPermit:
    def __init__(self, result, input_closure):
        self._input = input_closure
        self._relations = {relation["id"]: (owner["id"], relation["closureSha256"])
            for owner in result.get("fragments", []) for relation in owner.get("sourceRelations", {}).get("relations", [])}

    def _allows(self, owner, relation, current_inputs):
        registered = self._relations.pop(relation.get("id"), None)
        return (registered == (owner["id"], relation.get("closureSha256")) and self._input == current_inputs
            and relation.get("closureSha256") == _relation_closure(relation) and "validation" not in relation
            and "withdrawnClosureSha256" not in relation)


def _relation_closure(relation):
    return hashlib.sha256(_canonical({k: v for k, v in relation.items()
        if k not in {"id", "closureSha256", "validation"}})).hexdigest()


def _source_relation_counts(relations, detected=None, omitted=0):
    counts = {key: 0 for key in ("represented", "partial", "unknown", "denied", "unsupported")}
    for relation in relations:
        state = relation.get("resolution", "unknown")
        counts[state if state in counts else "unknown"] += 1
    return {"scope": "detected_bounded_source_relation_candidates_not_whole_code_or_policy",
        "detected": len(relations) + omitted if detected is None else detected,
        **counts, "omitted": omitted, "recorded": len(relations),
        "wholeCodeDenominator": "UNKNOWN", "wholePolicyDenominator": "UNKNOWN",
        "runtimeStatus": "not_observed", "semanticComplete": False,
        "omissionReasons": ["bounded_source_relation_budget"] if omitted else []}


def _build_source_relations(result, tokens, context, maximum, *, defer_external_dependencies=False):
    rows = result.get("fragments", [])
    for row in rows:
        row.setdefault("sourceRelationInputNamePresent", "name" in row)
    local = {row["id"]: row for row in rows}
    inventory = context.get("sourceRelationInventory", lambda: [])() if context else []
    input_closure = _source_input_closure(result, inventory)
    symbols = {row["id"]: row for row in inventory if isinstance(row, dict) and row.get("id")
        and row.get("path") == result["path"] and row.get("sourceDigest") == result["sourceDigest"]}
    records = {**symbols, **local}
    build_context = context.get("sourceRelationBuildContext") if context else None
    if build_context is not None and type(build_context) is not SourceRelationBuildContext:
        raise SemanticError("source_relation_build_context_invalid")
    admissibility_cache = {}
    candidates = []
    inventory_complete = result.get("coverage", {}).get("inventoryComplete") is True
    by_owner = {}
    for row in rows:
        owner = row.get("controlFlow", {}).get("owner") or {}
        if owner.get("id"):
            by_owner.setdefault(owner["id"], []).append(row)
    for group in by_owner.values():
        group.sort(key=lambda row: (row.get("sourceRange", {}).get("charStart", -1), row["id"]))

    def evidence(row, pointer):
        value = _source_pointer(row, pointer)
        return {"recordId": row["id"], "jsonPointer": pointer, "path": row.get("path", result["path"]),
            "sourceDigest": row.get("sourceDigest", result["sourceDigest"]),
            "valueSha256": hashlib.sha256(_canonical(value)).hexdigest()}

    def add(owner, kind, refs, details=None, limitations=(), proven=False, guards=(), effect="not_evaluated"):
        # Only fixed schema keys / source indices / evidence pointers are admitted.
        # Complete provider roots close every decision field, including absence.
        refs = list(refs)
        for identity in {ref["recordId"] for ref in refs}:
            provider = records.get(identity)
            if provider and provider.get("kind") in {"symbol", "callsite"}:
                refs.append(evidence(provider, ""))
        refs = sorted({(r["recordId"], r["jsonPointer"]): r for r in refs}.values(),
            key=lambda r: (r["recordId"], r["jsonPointer"]))
        if len(refs) > MAX_SOURCE_RELATION_REFS:
            details = {"omittedEvidenceRefs": len(refs)}
            refs = []
            limitations = set(limitations) | {"source_relation_evidence_budget_exceeded"}
            proven = False
        limitations = sorted(set(limitations) | ({"fragment_inventory_incomplete"} if not inventory_complete else set()))
        original_reasons = set(owner.get("unsupportedReasons", []))
        privacy_reasons = original_reasons & {"sensitive_value_redacted", "privacy_denied", "metadata_privacy_denied"}
        permission_reasons = original_reasons & {"literal_review_revoked"}
        protected = bool(privacy_reasons or permission_reasons)
        unsupported_owner = owner.get("representationStatus") == "unsupported"
        if privacy_reasons: limitations = sorted(set(limitations) | privacy_reasons | {"source_evidence_privacy_withheld"})
        if permission_reasons: limitations = sorted(set(limitations) | permission_reasons | {"source_disclosure_permission_revoked"})
        if unsupported_owner and not protected: limitations = sorted(set(limitations) | original_reasons | {"source_owner_unsupported"})
        state = "denied" if protected else "unsupported" if unsupported_owner else "represented" if proven and not limitations else "partial" if refs else "unknown"
        relation = {"schemaVersion": 3, "version": SOURCE_RELATION_VERSION, "relationKind": kind,
            "resolution": state, "claimLevel": "source_relation_proven" if state == "represented" else "source_relation_candidate",
            "sourceEvidenceRefs": refs, "sourceEvidenceIds": sorted({r["recordId"] for r in refs}),
            "guardEvidenceIds": sorted(set(guards)), "path": result["path"], "sourceDigest": result["sourceDigest"],
            "sourceRange": dict(owner["sourceRange"]), "limitations": limitations,
            "effectStatus": effect, "runtimeStatus": "not_observed", "runtimeValue": "UNKNOWN",
            "businessMeaningVerified": False, "details": details or {}, "inputClosure": input_closure}
        relation["admissibility"] = {"version": "source-relation-admissibility-1", "status": "pending_emitted_ir",
            "ownerRecordId": owner["id"], "recordCount": len(set(relation["sourceEvidenceIds"]) | {owner["id"]}), "statesSha256": None}
        # Only a complete standalone proof can issue its own immediate seal.
        # Unfinished standalone candidates and legacy deferred extraction have
        # no authority for a future inventory; official staged builds obtain
        # their first seal through the nonserialized build context instead.
        if build_context is None and not defer_external_dependencies and state != "partial":
            try:
                relation["admissibility"] = _source_admissibility_descriptor(owner, relation,
                    lambda identity, path=None: records.get(identity), admissibility_cache)
            except (KeyError, ValueError, TypeError, RecursionError): pass
        if protected:
            relation["limitations"] = sorted(set(relation["limitations"]) | {"protected_source_evidence"})
            relation["details"] = {}
        relation["closureSha256"] = _relation_closure(relation)
        relation["id"] = "source-relation:" + relation["closureSha256"]
        candidates.append((owner, relation))
        return relation

    def nodes(value, pointer="/expression"):
        if isinstance(value, dict):
            yield value, pointer
            # Only source AST branches; never traverse derived annotations.
            for key in ("callee", "receiver", "arguments", "left", "right", "operand", "then", "else", "condition", "elements", "index", "body"):
                child = value.get(key)
                if isinstance(child, dict):
                    yield from nodes(child, pointer + "/" + key)
                elif isinstance(child, list):
                    for index, item in enumerate(child):
                        yield from nodes(item, pointer + "/" + key + "/" + str(index))

    def pure(expression, allowed):
        if not isinstance(expression, dict): return False
        op = expression.get("op")
        if op == "reference": return expression.get("name") in allowed
        if op == "literal": return expression.get("type") in {"integer", "floating", "decimal", "boolean", "null"}
        if op in {"binary", "unary", "conditional"}:
            if expression.get("operator") in {"++", "--"}: return False
            children = [v for k, v in expression.items() if k in {"left", "right", "operand", "then", "else", "condition"}]
            return bool(children) and all(pure(v, allowed) for v in children)
        return False

    def normalize_type(name):
        return name.removeprefix("java.lang.") if isinstance(name, str) else None

    def pure_type(expression, parameters):
        """Conservative primitive expression types, never runtime evaluation."""
        if not isinstance(expression, dict): return None
        op = expression.get("op")
        if op == "reference": return normalize_type(parameters.get(expression.get("name")))
        if op == "literal":
            typed = expression.get("staticType", {})
            return normalize_type(typed.get("name")) if typed.get("resolution") == "resolved_static_type" else None
        numeric = {"byte", "short", "char", "int", "long", "float", "double"}
        rank = {"byte": 0, "short": 0, "char": 0, "int": 0, "long": 1, "float": 2, "double": 3}
        if op == "unary":
            value = pure_type(expression.get("operand"), parameters)
            if expression.get("operator") == "!": return "boolean" if value == "boolean" else None
            if value in numeric and expression.get("operator") in {"+", "-", "~"}:
                if expression.get("operator") == "~" and value in {"float", "double"}: return None
                return value if rank[value] else "int"
        if op == "binary":
            left = pure_type(expression.get("left"), parameters); right = pure_type(expression.get("right"), parameters)
            operator = expression.get("operator")
            if operator in {"&&", "||"}: return "boolean" if left == right == "boolean" else None
            if operator in {"==", "!="} and left == right == "boolean": return "boolean"
            if left not in numeric or right not in numeric: return None
            if operator in {"<", "<=", ">", ">=", "==", "!="}: return "boolean"
            if operator in {"<<", ">>", ">>>"}:
                return ("long" if left == "long" else "int") if left not in {"float", "double"} and right not in {"float", "double"} else None
            if operator not in {"+", "-", "*", "/", "%", "&", "|", "^"}: return None
            if operator in {"&", "|", "^"} and ({left, right} & {"float", "double"}): return None
            return ["int", "long", "float", "double"][max(rank[left], rank[right])]
        if op == "conditional" and pure_type(expression.get("condition"), parameters) == "boolean":
            left = pure_type(expression.get("then"), parameters); right = pure_type(expression.get("else"), parameters)
            return left if left is not None and left == right else None
        return None

    token_starts = [token.start for token in tokens]
    token_ends = [token.end for token in tokens]
    body_cache, complete_body_cache = {}, {}
    def body_tokens(bounds):
        if not isinstance(bounds, dict): return []
        key = (bounds.get("charStart", -1), bounds.get("charEnd", -1))
        if key not in body_cache:
            body_cache[key] = tokens[bisect.bisect_left(token_starts, key[0]):bisect.bisect_right(token_ends, key[1])]
        return body_cache[key]

    def covered_body(method, group, permitted):
        bounds = method.get("bodyRange")
        if not bounds or not inventory_complete or any(r["category"] not in permitted or r.get("controlFlow", {}).get("contexts") for r in group):
            return False
        key = (method["id"], tuple(sorted(permitted)))
        if key not in complete_body_cache:
            covered = [r["sourceRange"] for r in group]
            complete_body_cache[key] = all(token.value in {"{", "}", ";"} or any(r["charStart"] <= token.start and token.end <= r["charEnd"] for r in covered)
                for token in body_tokens(bounds))
        return complete_body_cache[key]

    # Source-declared constructor transfer, independent of runtime construction
    # success and of caller argument applicability. Existing order facts stay as-is.
    for row in rows:
        for node, pointer in nodes(row.get("expression")):
            if node.get("op") != "construct": continue
            binding = node.get("recordConstruction")
            if not isinstance(binding, dict):
                add(row, "constructor_parameter_component_transfer", [evidence(row, pointer)],
                    {"componentTransfers": [], "argumentApplicability": "UNKNOWN", "storedComponentValues": "UNKNOWN"},
                    limitations=["selected_constructor_field_transfer_unavailable"], effect="UNKNOWN")
                continue
            declarations = [(i, d) for i, d in enumerate(row.get("recordConstructorDeclarations", []))
                if d.get("id") == binding.get("declarationId")]
            refs = [evidence(row, pointer + "/recordConstruction")]
            limitations, mappings = [], []
            if len(declarations) != 1:
                limitations.append("constructor_declaration_unavailable")
            else:
                index, declaration = declarations[0]
                refs.append(evidence(row, "/recordConstructorDeclarations/" + str(index)))
                params = declaration.get("parameters", [])
                declared_record = records.get(declaration.get("recordDeclarationId"), {})
                if declared_record: refs.append(evidence(declared_record, ""))
                if (declared_record.get("recordComponentCoverage", {}).get("declarationsComplete") is not True
                        or any(p.get("typeResolution") not in {"primitive", "resolved"} or not p.get("type") or normalize_type(p.get("type")) == "void" for p in params)):
                    limitations.append("constructor_component_declarations_unproven")
                if declaration.get("constructorKind") == "implicit_canonical":
                    mappings = [{"parameterIndex": i, "componentIndex": i, "transfer": "parameter_identity_on_normal_return"}
                        for i in range(len(params))]
                elif declaration.get("candidateCount") == 1 and declaration.get("path") == result["path"]:
                    candidate = declaration["constructorCandidates"][0]
                    ct = body_tokens(candidate.get("sourceRange")); opening = next((i for i, t in enumerate(ct) if t.value == "{"), None)
                    compact = candidate.get("kind") == "compact_or_direct_member_candidate"
                    names = [p.get("name") for p in params]
                    group = [r for r in rows if candidate["sourceRange"]["charStart"] <= r["sourceRange"]["charStart"]
                        and r["sourceRange"]["charEnd"] <= candidate["sourceRange"]["charEnd"]]
                    assignments = [r for r in group if r["category"] == "assignment"]
                    used, valid = set(), opening is not None and bool(ct) and ct[-1].value == "}"
                    if not compact:
                        # Canonical explicit parameter names/types must match the
                        # component header; annotations/varargs/generics are not guessed.
                        header = [t.value for t in ct[:opening]] if opening is not None else []
                        expected = [declaration["recordType"].split(".")[-1], "("]
                        for i, parameter in enumerate(params):
                            if i: expected.append(",")
                            expected.extend(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|[.\[\]]", parameter.get("declaredType", "")))
                            expected.append(parameter.get("name"))
                        expected.append(")")
                        valid = valid and header == expected
                    covered = [r["sourceRange"] for r in assignments]
                    valid = valid and all(t.value in {"{", "}", ";"} or any(b["charStart"] <= t.start and t.end <= b["charEnd"] for b in covered)
                        for t in (ct[opening:] if opening is not None else ct))
                    for assignment in assignments:
                        target = assignment.get("target", {})
                        name = target.get("name", "") if target.get("op") == "reference" else ""
                        component = name if compact else name.removeprefix("this.") if name.startswith("this.") else None
                        valid = valid and component in names and component not in used and assignment.get("assignmentOperator") == "=" and not assignment.get("controlFlow", {}).get("contexts")
                        expr = assignment.get("expression")
                        valid = valid and pure(expr, set(names))
                        if compact and component in names:
                            expected_type = normalize_type(params[names.index(component)].get("type"))
                            valid = valid and expected_type is not None and pure_type(expr, {p.get("name"): p.get("type") for p in params}) == expected_type
                        if not compact:
                            valid = valid and expr == {"op": "reference", "name": component}
                        if component in names:
                            used.add(component); pos = names.index(component)
                            mappings.append({"parameterIndex": pos, "componentIndex": pos,
                                "transfer": "source_expression_on_normal_return", "expressionRef": {"recordId": assignment["id"], "jsonPointer": "/expression"}})
                        refs.extend([evidence(assignment, "/expression"), evidence(assignment, "/target"), evidence(assignment, "/controlFlow")])
                    if compact:
                        mappings.extend({"parameterIndex": i, "componentIndex": i, "transfer": "parameter_identity_on_normal_return"}
                            for i, name in enumerate(names) if name not in used)
                    else:
                        valid = valid and used == set(names)
                    if not valid:
                        mappings = []; limitations.append("constructor_body_transfer_not_proven")
                else:
                    limitations.append("constructor_delegation_overload_or_source_unavailable")
            add(row, "constructor_parameter_component_transfer", refs,
                {"componentTransfers": sorted(mappings, key=lambda m: m["componentIndex"]),
                 "argumentApplicability": "UNKNOWN", "storedComponentValues": "UNKNOWN", "condition": "normal_constructor_return"},
                limitations=limitations, proven=not limitations, effect="source_field_transfer_only")

    # Exact direct helper targets only; body coverage is checked against the
    # token inventory, so a hidden statement/initializer/throw cannot vanish.
    for row in rows:
        for node, pointer in nodes(row.get("expression")):
            if node.get("op") != "call": continue
            typed = node.get("staticType", {})
            ids = typed.get("sourceEvidenceIds", [])
            targets = [records[i] for i in ids if i in records and records[i].get("type") == "Method"]
            sites = [records[i] for i in ids if i in records and records[i].get("kind") == "callsite"]
            refs = [evidence(row, pointer)]
            limitations, details = [], {"argumentApplicability": "UNKNOWN", "returnedValue": "UNKNOWN"}
            if len(targets) != 1 or len(sites) != 1 or sites[0].get("resolution") != "exact" or typed.get("basis") != "exact_source_call_return_declaration":
                limitations.append("exact_source_target_not_proven")
            else:
                method, site = targets[0], sites[0]
                refs.extend([evidence(method, "/callbackDeclaration"),
                    evidence(method, "/parameterTypeReferences"), evidence(method, "/throwsTypes"), evidence(site, "/resolution"), evidence(site, "/target")])
                if "bodyRange" in method: refs.append(evidence(method, "/bodyRange"))
                header = method.get("callbackDeclaration", {}); source_modifiers = method.get("sourceMethodModifiers")
                allowed_modifiers = {"public", "protected", "private", "abstract", "final", "static", "synchronized", "native", "default", "strictfp"}
                modifiers_valid = (isinstance(source_modifiers, list) and all(isinstance(value, str) and value in allowed_modifiers for value in source_modifiers)
                    and source_modifiers == sorted(set(source_modifiers)))
                modifiers = set(source_modifiers) if modifiers_valid else set()
                if not modifiers_valid: limitations.append("source_method_modifiers_unavailable")
                # The selected callsite is already exact. A different overload
                # cannot invalidate this callee's independent body summary.
                if site.get("target") != method.get("originalSymbolId"):
                    limitations.append("exact_callee_identity_not_proven")
                callee = node.get("callee", {})
                receiver = callee.get("name") if callee.get("op") == "reference" else None
                allowed_receivers = {method.get("name"), "this." + method.get("name", "")}
                if "static" in modifiers:
                    allowed_receivers |= {method.get("owner", "") + "." + method.get("name", ""), method.get("owner", "").split(".")[-1] + "." + method.get("name", "")}
                if receiver not in allowed_receivers: limitations.append("helper_receiver_alias_or_dispatch_not_proven")
                group = by_owner.get(method["id"], [])
                returns = [r for r in group if r["category"] == "return"]
                if not (header.get("hasBody") and header.get("declarationValidity") == "bounded_header_only"
                        and (header.get("access") == "private" or modifiers & {"static", "final"})
                        and not modifiers & {"synchronized", "native", "abstract"} and not header.get("varargs")
                        and not header.get("generic") and not method.get("throwsTypes")):
                    limitations.append("nonvirtual_pure_helper_eligibility_not_proven")
                if len(returns) != 1 or not covered_body(method, group, {"return"}):
                    limitations.append("complete_single_return_body_not_proven")
                params = method.get("parameterTypeReferences", [])
                arguments = node.get("arguments", [])
                normalize = lambda name: name.removeprefix("java.lang.") if isinstance(name, str) else None
                if len(arguments) != len(params) or any(p.get("resolution") not in {"primitive", "resolved"} or
                        normalize(p.get("resolvedType")) != normalize(a.get("staticType", {}).get("name"))
                        or a.get("staticType", {}).get("resolution") != "resolved_static_type" for p, a in zip(params, arguments)):
                    limitations.append("helper_argument_applicability_not_proven")
                returned = returns[0] if len(returns) == 1 else None
                if returned:
                    refs.append(evidence(returned, "/expression")); refs.append(evidence(returned, "/controlFlow"))
                    expression = returned.get("expression")
                    safe = pure(expression, {p.get("name") for p in params})
                    if isinstance(expression, dict) and expression.get("op") == "construct":
                        constructors = returned.get("recordConstructorDeclarations", [])
                        binding = expression.get("recordConstruction", {})
                        decls = [d for d in constructors if d.get("id") == binding.get("declarationId") and d.get("constructorKind") == "implicit_canonical"]
                        record = records.get(decls[0].get("recordDeclarationId")) if len(decls) == 1 else None
                        component_params = decls[0].get("parameters", []) if len(decls) == 1 else []
                        arguments_in_return = expression.get("arguments", [])
                        safe = bool(record and record.get("sourceBodyShape", {}).get("shape") == "empty"
                            and record.get("recordComponentCoverage", {}).get("declarationsComplete") is True
                            and binding.get("resolution") == "implicit_canonical_parameter_order"
                            and len(component_params) == len(arguments_in_return)
                            and all(pure(a, {p.get("name") for p in params}) and
                                pure_type(a, {p.get("name"): p.get("resolvedType") for p in params}) == normalize_type(component.get("type"))
                                for a, component in zip(arguments_in_return, component_params)))
                        if record: refs.append(evidence(record, "/sourceBodyShape"))
                        # Ordinary constructors do not have record declarations.
                        # Optional absence remains bound by the parser inventory;
                        # never invent an evidence pointer for an absent field.
                        if "recordConstructorDeclarations" in returned:
                            refs.append(evidence(returned, "/recordConstructorDeclarations"))
                    expected_return = normalize_type(method.get("returnTypeReference", {}).get("resolvedType"))
                    actual_return = normalize_type(decls[0].get("recordType")) if isinstance(expression, dict) and expression.get("op") == "construct" and len(decls) == 1 else pure_type(expression, {p.get("name"): p.get("resolvedType") for p in params})
                    if expected_return is None or actual_return != expected_return:
                        limitations.append("helper_return_type_not_proven")
                    if not safe: limitations.append("helper_effects_or_expression_not_proven")
                    details.update({"targetReturnRef": {"recordId": returned["id"], "jsonPointer": "/expression"},
                        "parameterArguments": [{"parameterIndex": i, "argumentRef": {"recordId": row["id"],
                            "jsonPointer": pointer + "/arguments/" + str(i)}} for i in range(len(arguments))],
                        "argumentApplicability": "exact_static_types" if not any("applicability" in r for r in limitations) else "UNKNOWN",
                        "condition": "normal_helper_return"})
            add(row, "helper_return_source_summary", refs, details, limitations=limitations,
                proven=not limitations, effect="checked_source_return_no_external_calls" if not limitations else "UNKNOWN")

    # Local primitive straight-line reaching definitions. Fields, aliases,
    # branches, binders, loops and writes outside this complete body stay unknown.
    for owner_id, group in by_owner.items():
        method = records.get(owner_id)
        straight = bool(method and covered_body(method, group, {"local_declaration", "assignment", "return"}))
        for row in group:
            for read in row.get("dataFlow", {}).get("reads", []):
                decls = read.get("declarationIds", []); writes = read.get("precedingWriteCandidates", [])
                if len(decls) != 1 or not writes: continue
                declaration = local.get(decls[0]); definition = local.get(writes[-1])
                if not declaration or declaration.get("category") != "local_declaration" or declaration.get("declaredType") not in {"boolean", "byte", "short", "int", "long", "float", "double", "char"}:
                    continue
                if not definition: continue
                valid = straight and definition in group and not definition.get("controlFlow", {}).get("contexts") and all(
                    w.get("declarationIds") == decls for w in definition.get("dataFlow", {}).get("writes", []))
                refs = [evidence(row, "/dataFlow"), evidence(row, "/controlFlow"),
                    evidence(declaration, "/declaredType"), evidence(definition, "/expression"), evidence(definition, "/dataFlow")]
                if method: refs.append(evidence(method, ""))
                add(row, "straight_line_reaching_definition", refs,
                    {"definitionRef": {"recordId": definition["id"], "jsonPointer": "/expression"}, "valueSubstitution": False,
                     "condition": "consumer_statement_reached_normally"},
                    limitations=[] if valid else ["branch_alias_or_complete_body_not_proven"], proven=valid)
        for row in group:
            contexts = row.get("controlFlow", {}).get("contexts", [])
            if row["category"] == "return" and contexts:
                guards = [c["fragmentId"] for c in contexts if c.get("fragmentId") in local]
                refs = [evidence(row, "/controlFlow"), evidence(row, "/expression")]
                refs.extend(evidence(local[i], "/expression") for i in guards)
                add(row, "lexical_return_guard", refs, {"scope": "recorded_lexical_context_only", "returnedValue": "UNKNOWN"},
                    limitations=[] if len(guards) == len(contexts) else ["guard_fragment_unavailable"],
                    proven=len(guards) == len(contexts), guards=guards)

    enum_groups = {}
    for row in rows:
        if row.get("category") != "enum_constant": continue
        enclosing = [symbol for symbol in symbols.values() if symbol.get("type") == "Enum"
            and symbol.get("sourceRange", {}).get("charStart", -1) <= row["sourceRange"]["charStart"]
            and row["sourceRange"]["charEnd"] <= symbol.get("sourceRange", {}).get("charEnd", -1)]
        enclosing.sort(key=lambda symbol: symbol["sourceRange"]["charEnd"] - symbol["sourceRange"]["charStart"])
        declared = enclosing[0] if enclosing and (len(enclosing) == 1 or enclosing[0]["sourceRange"] != enclosing[1]["sourceRange"]) else None
        enum_groups.setdefault(declared["id"] if declared else row["id"], (declared, []))[1].append(row)
    for name, (declared, group) in sorted(enum_groups.items()):
        group.sort(key=lambda row: row["sourceRange"]["charStart"])
        for index, row in enumerate(group):
            within_budget = len(group) + 1 <= MAX_SOURCE_RELATION_REFS
            refs = [evidence(member, "/sourceRange") for member in group] if within_budget else []
            # Every inspected enum symbol is bound, including exclusion by its
            # range. Other kinds cannot become enum candidates unnoticed.
            refs.extend(evidence(symbol, "") for symbol in symbols.values() if symbol.get("kind") == "symbol")
            add(row, "enum_constant_declaration_position", refs, {"declarationPosition": index if declared and within_budget else None,
                "enumScope": "same_lexical_enum_declaration", "runtimeOrdinal": "UNKNOWN"},
                limitations=[] if declared and within_budget else ["enum_declaration_scope_unproven" if not declared else "source_relation_evidence_budget_exceeded"], proven=bool(declared and within_budget))
    arrays = []
    for row in rows:
        for node, pointer in nodes(row.get("expression")):
            if node.get("op") == "array_initializer":
                arrays.append((row, pointer, node))
                for index in range(len(node.get("elements", []))):
                    add(row, "array_element_source_position", [evidence(row, pointer + "/elements/" + str(index))],
                        {"elementIndex": index, "arrayState": "declared_initializer_only", "runtimeElement": "UNKNOWN"}, proven=True)
            if node.get("op") == "lambda":
                add(row, "callback_body_reference", [evidence(row, pointer)],
                    {"bodyRef": {"recordId": row["id"], "jsonPointer": pointer}, "callbackExecution": "UNKNOWN"},
                    limitations=["callback_trigger_and_effects_not_proven"], effect="UNKNOWN")
    # A source association records parallel initializer positions, never a live
    # capacity lookup. Require an explicit selected enum parameter and ordinal
    # call, and an indexed expression using that local definition.
    for row in rows:
        expression = row.get("expression") or {}
        if row.get("category") != "local_declaration" or expression.get("op") != "call" or expression.get("arguments") or row.get("controlFlow", {}).get("contexts"):
            continue
        callee = expression.get("callee", {})
        spelling = callee.get("name", "") if callee.get("op") == "reference" else ""
        if not spelling.endswith(".ordinal") or spelling.count(".") != 1: continue
        receiver = spelling.split(".")[0]; owner = (row.get("controlFlow", {}).get("owner") or {}).get("id")
        method = records.get(owner, {}); params = [p for p in method.get("parameterTypeReferences", []) if p.get("name") == receiver]
        if len(params) != 1 or params[0].get("resolution") != "resolved": continue
        selected_types = [r for r in symbols.values() if r.get("type") == "Enum" and r.get("qualifiedName") == params[0].get("resolvedType")]
        if len(selected_types) != 1: continue
        declared = selected_types[0]
        constants = [r for r in rows if r.get("category") == "enum_constant" and declared["sourceRange"]["charStart"] <= r["sourceRange"]["charStart"] < declared["sourceRange"]["charEnd"]]
        constants.sort(key=lambda r: r["sourceRange"]["charStart"])
        for consumer in by_owner.get(owner, []):
            expr = consumer.get("expression") or {}
            if expr.get("op") != "index" or expr.get("index", {}).get("name") != row.get("name"): continue
            target_name = expr.get("receiver", {}).get("name") or expr.get("target", {}).get("name")
            array_ids = {d["id"] for ref in consumer.get("references", []) if ref.get("name") == target_name
                for d in ref.get("declarations", [])}
            matches = [(a, pointer, node) for a, pointer, node in arrays if a["id"] in array_ids and a.get("name") == target_name and len(node.get("elements", [])) == len(constants)]
            if len(matches) != 1: continue
            array, pointer, node = matches[0]
            add(consumer, "enum_array_initial_source_association", [evidence(row, "/expression"), evidence(method, "/parameterTypeReferences"),
                evidence(declared, "/sourceRange"), evidence(consumer, "/expression"), evidence(array, pointer)],
                {"pairs": [{"enumRecordId": constant["id"], "declarationPosition": i,
                    "arrayElementRef": {"recordId": array["id"], "jsonPointer": pointer + "/elements/" + str(i)}} for i, constant in enumerate(constants)],
                 "runtimeCapacity": "UNKNOWN", "condition": "source_initializer_position_association_only"},
                limitations=["runtime_index_and_array_mutations_not_proven"], effect="not_evaluated")

    # Budgets preserve candidate denominators. Order only evidence collections;
    # source argument/parameter/element order remains unchanged.
    candidates.sort(key=lambda pair: (pair[0]["sourceRange"]["charStart"], pair[1]["relationKind"], pair[1]["id"]))
    omitted_by_owner, owner_bytes, owner_base_bytes = {}, {}, {}
    for index, (owner, relation) in enumerate(candidates):
        identity = owner["id"]
        current = owner_bytes.get(identity, 0)
        if identity not in owner_base_bytes:
            owner_base_bytes[identity] = len(_canonical({k: v for k, v in owner.items() if k != "sourceRelations"}))
        base_bytes = owner_base_bytes[identity]
        capacity = min(MAX_SOURCE_RELATION_FRAGMENT_BYTES, max(0, MAX_SOURCE_RELATION_RECORD_BYTES - base_bytes - 2048))
        size = len(_canonical(relation))
        if index >= maximum or current + size > capacity:
            omitted_by_owner[owner["id"]] = omitted_by_owner.get(owner["id"], 0) + 1
            continue
        owner_bytes[identity] = current + size
        owner.setdefault("sourceRelations", {"schemaVersion": 3, "version": SOURCE_RELATION_VERSION,
            "analysisSpecBinding": "snapshot_metadata", "relations": []})["relations"].append(relation)
    for row in rows:
        relations = row.get("sourceRelations", {}).get("relations", [])
        omitted = omitted_by_owner.get(row["id"], 0)
        if relations or omitted:
            container = row.setdefault("sourceRelations", {"schemaVersion": 3, "version": SOURCE_RELATION_VERSION,
                "analysisSpecBinding": "snapshot_metadata", "relations": []})
            container["coverage"] = _source_relation_counts(relations, omitted=omitted)
    all_relations = [relation for row in rows for relation in row.get("sourceRelations", {}).get("relations", [])]
    result["coverage"]["sourceRelations"] = _source_relation_counts(all_relations, detected=len(candidates), omitted=sum(omitted_by_owner.values()))
    if build_context is not None:
        build_context._register_new_extraction(result, input_closure)
    else:
        # A legacy staged extraction has no authority to promise the future
        # snapshot's complete current inventory. Publish unverified candidates
        # immediately rather than issue a positive seal that its subsequent
        # legacy (no-inventory) finalizer must withdraw. Official staged builds
        # use the nonserialized one-use context above. Standalone extraction
        # still validates its complete immediate emitted IR here.
        finalize_source_relations(result, lookup=lambda identity, path=None: records.get(identity),
            inventory_lookup=None if defer_external_dependencies else lambda path: inventory)


def finalize_source_relations(result, lookup=None, *, inventory_lookup=None, _seal_permit=None):
    """Revalidate relation pointers against emitted IR; never reread source.

    A changed/removed provider invalidates its compact relation rather than
    retaining a source summary through a source-free transport or cache.
    """
    local = {r["id"]: r for r in result.get("fragments", [])}
    if _seal_permit is not None and type(_seal_permit) is not _SourceRelationSealPermit:
        raise SemanticError("source_relation_seal_permit_invalid")
    state_cache = {}
    def load(identity, path=None):
        if identity in local: return local[identity]
        return lookup(identity, path) if lookup is not None else None
    original_detected = result.get("coverage", {}).get("sourceRelations", {}).get("detected", 0)
    current_inputs, input_failure = None, None
    if any("sourceRelations" in row for row in local.values()):
        try:
            if inventory_lookup is None:
                input_failure = "source_relation_current_inventory_unavailable"
            else:
                current_inputs = _source_input_closure(result, inventory_lookup(result["path"]))
        except (ValueError, KeyError, TypeError, RecursionError):
            input_failure = "source_relation_input_inventory_invalid"
    all_relations, omitted = [], 0
    for owner in result.get("fragments", []):
        container = owner.get("sourceRelations")
        if not isinstance(container, dict): continue
        relations = container.get("relations", [])
        for relation in relations:
            if not isinstance(relation, dict): raise SemanticError("source_relation_schema_invalid")
            if (_seal_permit is not None and relation.get("admissibility", {}).get("status") == "pending_emitted_ir"
                    and _seal_permit._allows(owner, relation, current_inputs)):
                try:
                    relation["admissibility"] = _source_admissibility_descriptor(owner, relation, load, state_cache)
                    relation["closureSha256"] = _relation_closure(relation)
                    relation["id"] = "source-relation:" + relation["closureSha256"]
                except (KeyError, ValueError, TypeError, RecursionError): pass
            refs = relation.get("sourceEvidenceRefs")
            failure, disposition, cause, subject = None, "unknown", None, None
            if (not isinstance(refs, list) or any(not isinstance(ref, dict) or not isinstance(ref.get("recordId"), str)
                    or not isinstance(ref.get("jsonPointer"), str) for ref in refs)
                    or relation.get("resolution") not in {"represented", "partial", "unknown", "denied", "unsupported"}
                    or relation.get("claimLevel") != ("source_relation_proven" if relation.get("resolution") == "represented" else "source_relation_candidate")):
                failure = "source_relation_schema_invalid"
            elif relation.get("schemaVersion") != 3 or relation.get("version") != SOURCE_RELATION_VERSION or relation.get("relationKind") not in _SOURCE_RELATION_KINDS:
                failure = "source_relation_schema_invalid"
            elif ((not relation.get("sourceEvidenceRefs") and relation.get("resolution") == "represented") or len(relation["sourceEvidenceRefs"]) > MAX_SOURCE_RELATION_REFS
                    or relation.get("sourceEvidenceIds") != sorted({r.get("recordId") for r in relation["sourceEvidenceRefs"]})
                    or relation.get("runtimeStatus") != "not_observed" or relation.get("runtimeValue") != "UNKNOWN"
                    or relation.get("businessMeaningVerified") is not False):
                failure = "source_relation_schema_invalid"
            elif relation.get("closureSha256") != _relation_closure(relation) or relation.get("id") != "source-relation:" + relation.get("closureSha256", ""):
                failure = "source_relation_closure_invalid"
            elif relation.get("path") != owner.get("path") or relation.get("sourceDigest") != owner.get("sourceDigest") or relation.get("sourceRange") != owner.get("sourceRange"):
                failure = "source_relation_owner_binding_invalid"
            else:
                admissibility = _source_admissibility(owner, semantic=True)
                if admissibility:
                    disposition, cause = admissibility; subject = "owner"
                    failure = "source_relation_owner_" + cause
                for ref in relation.get("sourceEvidenceRefs", []) if not failure else []:
                    provider = local.get(ref.get("recordId"))
                    if provider is None and lookup is not None:
                        provider = lookup(ref.get("recordId"), ref.get("path"))
                    try:
                        if (not isinstance(provider, dict) or provider.get("path") != ref.get("path")
                                or provider.get("sourceDigest") != ref.get("sourceDigest")):
                            failure = "source_relation_provider_unavailable_or_changed"; break
                        admissibility = _source_admissibility(provider, semantic=provider.get("category") is not None)
                        if admissibility:
                            disposition, cause = admissibility; subject = "provider"
                            failure = "source_relation_provider_" + cause; break
                        if hashlib.sha256(_canonical(_source_pointer(provider, ref.get("jsonPointer")))).hexdigest() != ref.get("valueSha256"):
                            failure = "source_relation_provider_unavailable_or_changed"; break
                    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
                        failure = "source_relation_pointer_invalid"; break
                if not failure:
                    try:
                        descriptor = relation.get("admissibility")
                        if not isinstance(descriptor, dict) or descriptor.get("status") != "sealed":
                            failure = "source_relation_admissibility_unsealed"
                        elif descriptor != _source_admissibility_descriptor(owner, relation, load, state_cache):
                            failure = "source_relation_admissibility_changed"
                    except (KeyError, ValueError, TypeError, RecursionError):
                        failure = "source_relation_admissibility_unavailable"
                if not failure and (input_failure or relation.get("inputClosure") != current_inputs):
                    failure = input_failure or "source_relation_input_inventory_changed"
            if failure:
                # Preserve the candidate and its original closure for audit;
                # status is a separate withdrawal, never a relabeled new proof.
                relation.setdefault("withdrawnClosureSha256", relation.get("closureSha256"))
                relation["resolution"] = disposition
                relation["claimLevel"] = "source_relation_candidate"
                relation["limitations"] = sorted(set(relation.get("limitations", [])) | {failure})
                relation["validation"] = {"status": "invalidated", "reason": failure}
                if cause: relation["validation"].update(cause=cause, subject=subject)
                relation["closureSha256"] = _relation_closure(relation)
                relation["id"] = "source-relation:" + relation["closureSha256"]
            elif relation.get("validation", {}).get("status") != "invalidated":
                relation["validation"] = {"status": "verified_emitted_ir"}
        # Final validation/withdrawal metadata is part of the hard byte cap.
        # Re-cap against actual emitted bytes, preserving candidate omissions.
        relations.sort(key=lambda relation: (relation.get("relationKind", ""), relation.get("id", "")))
        prior_omitted = container.get("coverage", {}).get("omitted", 0)
        base_bytes = len(_canonical({k: v for k, v in owner.items() if k != "sourceRelations"}))
        capacity = min(MAX_SOURCE_RELATION_FRAGMENT_BYTES, max(0, MAX_SOURCE_RELATION_RECORD_BYTES - base_bytes - 2048))
        retained, used_bytes, newly_omitted = [], 0, 0
        for relation in relations:
            size = len(_canonical(relation))
            if used_bytes + size > capacity:
                newly_omitted += 1
            else:
                retained.append(relation); used_bytes += size
        container["relations"] = retained
        omitted_here = prior_omitted + newly_omitted
        omitted += omitted_here
        all_relations.extend(retained)
        container["coverage"] = _source_relation_counts(retained, omitted=omitted_here)
    if "sourceRelations" in result.get("coverage", {}):
        # Removal of an input owner cannot erase its original candidate count.
        missing_candidates = max(0, original_detected - len(all_relations) - omitted)
        result["coverage"]["sourceRelations"] = _source_relation_counts(all_relations, omitted=omitted + missing_candidates)
        if missing_candidates:
            reasons = set(result["coverage"]["sourceRelations"]["omissionReasons"])
            if not omitted: reasons.discard("bounded_source_relation_budget")
            result["coverage"]["sourceRelations"]["omissionReasons"] = sorted(reasons | {"source_relation_input_inventory_changed"})
    return result
