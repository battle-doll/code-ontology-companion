"""Bounded static policy compilation and source-free deterministic evaluation.

This module never imports/executes target code or requests a model. Supported
Python is a small typed fragment; Java/TypeScript support only pure boolean
functions. Domain names
are lexical candidates, not business approval. Unknown syntax is not a rule.
"""
from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import itertools
import json
import re
from decimal import Decimal, DecimalException, localcontext
from pathlib import PurePosixPath
from typing import Any

import privacy_guard


SCHEMA_VERSION = 1
RULE_VERSION = "typed-static-policy-v1"
RULESET_AUTHORITY = "typed-static-v1"
DECLARATION_EXTRACTOR_VERSION = "source-policy-declarations-1"
DOMAINS = ("product", "order", "display", "claim", "settlement", "delivery")
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_AST_NODES = 20_000
MAX_AST_BUDGET = 200_000
MAX_RULES = 256
MAX_IR_NODES = 4096
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_CASES = 256
TYPES = {"bool", "int", "decimal"}
ROUNDINGS = {"ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_HALF_DOWN", "ROUND_DOWN", "ROUND_UP", "ROUND_FLOOR", "ROUND_CEILING", "ROUND_05UP"}
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,95}\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]{0,37})(?:\.[0-9]{1,28})?\Z")
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]{0,37})\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SENSITIVE_IDENTIFIER = re.compile(r"(?:password|passwd|secret|credential|private_key|api_key|access_token|email)", re.I)
_DOMAIN_WORDS = {"product": {"product", "catalog", "sku"}, "order": {"order", "checkout", "discount", "cancel"},
                 "display": {"display", "merchandising", "listing"}, "claim": {"claim", "refund", "return"},
                 "settlement": {"settlement", "payout", "invoice"}, "delivery": {"delivery", "shipping", "shipment"}}


class PolicyError(ValueError):
    """Messages are fixed categories: never include inspected values or source."""
    def __init__(self, code="policy_rejected"):
        self.code = code if code in {"invalid_arguments", "source_digest_mismatch", "source_quota", "snapshot_quota", "invalid_snapshot",
            "snapshot_digest_mismatch", "snapshot_pin_mismatch", "invalid_ir", "rule_not_found", "case_budget_exceeded",
            "invalid_policy_view", "authority_required", "privacy_denied", "invalid_proposal"} else "policy_rejected"
        super().__init__("Policy request rejected: " + self.code + ".")


class _Unsupported(Exception):
    def __init__(self, reason):
        self.reason = reason


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise PolicyError("invalid_arguments") from None


def _safe(value):
    try:
        privacy_guard.ensure_public_safe(value)
    except privacy_guard.PrivacyError:
        raise PolicyError("privacy_denied") from None
    return value


def _identifier(value):
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value)) and not _SENSITIVE_IDENTIFIER.search(value)


def _relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value or ":" in value or "\x00" in value:
        raise PolicyError("invalid_arguments")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise PolicyError("invalid_arguments")
    _safe(value)
    return value


def _literal(kind, value):
    if kind == "bool":
        if type(value) is not bool:
            raise PolicyError("invalid_ir")
    elif kind == "int":
        value = str(value)
        if not _INTEGER.fullmatch(value):
            raise PolicyError("invalid_ir")
    elif kind == "decimal":
        value = str(value)
        if not _DECIMAL.fullmatch(value):
            raise PolicyError("invalid_ir")
    else:
        raise PolicyError("invalid_ir")
    return {"op": "literal", "type": kind, "value": value}


def _value(literal):
    kind = literal["type"]
    if kind == "bool":
        return literal["value"]
    if kind == "int":
        return int(literal["value"])
    return Decimal(literal["value"])


def _typed(value, kind):
    if kind == "decimal":
        value = format(value, "f")
    return {key: val for key, val in _literal(kind, value).items() if key != "op"}


def _count_tree(value, max_nodes=MAX_IR_NODES):
    pending = [(value, 0)]; count = 0
    while pending:
        item, depth = pending.pop(); count += 1
        if count > max_nodes or depth > 64:
            raise _Unsupported("ir_budget")
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
    return count


class _Compiler:
    def __init__(self, imports, globals_, function):
        self.imports = imports
        self.globals = globals_
        self.steps = 0
        self.bound = {n.id for n in ast.walk(function) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        self.bound.update(arg.arg for arg in function.args.args + function.args.posonlyargs + function.args.kwonlyargs)

    def step(self):
        self.steps += 1
        if self.steps > 768:
            raise _Unsupported("ir_budget")

    def annotation(self, node):
        if isinstance(node, ast.Name):
            if node.id in {"int", "bool"} and node.id not in self.imports:
                return node.id
            if self.imports.get(node.id) == "decimal.Decimal" and node.id not in self.bound:
                return "decimal"
        raise _Unsupported("unsupported_type")

    def expression(self, node, env):
        self.step()
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return _literal("bool", node.value)
            if type(node.value) is int and len(str(node.value)) <= 38:
                return _literal("int", node.value)
            raise _Unsupported("unsupported_literal")
        if isinstance(node, ast.Name):
            if node.id in env:
                return copy.deepcopy(env[node.id])
            if node.id in self.globals and node.id not in self.bound:
                return copy.deepcopy(self.globals[node.id])
            raise _Unsupported("unresolved_reference")
        if isinstance(node, ast.UnaryOp):
            arg = self.expression(node.operand, env)
            if isinstance(node.op, ast.Not) and arg["type"] == "bool":
                return {"op": "not", "type": "bool", "arg": arg}
            if isinstance(node.op, (ast.USub, ast.UAdd)) and arg["type"] in {"int", "decimal"}:
                return {"op": "neg" if isinstance(node.op, ast.USub) else "pos", "type": arg["type"], "arg": arg}
            raise _Unsupported("unsupported_unary")
        if isinstance(node, ast.BoolOp):
            args = [self.expression(x, env) for x in node.values]
            if not all(x["type"] == "bool" for x in args):
                raise _Unsupported("non_boolean_short_circuit")
            return {"op": "and" if isinstance(node.op, ast.And) else "or", "type": "bool", "args": args}
        if isinstance(node, ast.BinOp):
            left, right = self.expression(node.left, env), self.expression(node.right, env)
            operators = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.FloorDiv: "floordiv", ast.Mod: "mod"}
            op = operators.get(type(node.op))
            if op is None or left["type"] not in {"int", "decimal"} or right["type"] not in {"int", "decimal"}:
                raise _Unsupported("unsupported_arithmetic")
            kind = "decimal" if "decimal" in {left["type"], right["type"]} else "int"
            if (op == "div" and kind == "int") or (op in {"floordiv", "mod"} and kind != "int"):
                raise _Unsupported("float_or_decimal_integer_semantics")
            return {"op": op, "type": kind, "left": left, "right": right}
        if isinstance(node, ast.Compare):
            left = self.expression(node.left, env); conditions = []
            operators = {ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge"}
            for operator, target in zip(node.ops, node.comparators):
                right = self.expression(target, env); op = operators.get(type(operator))
                if op is None or ("bool" in {left["type"], right["type"]} and (left["type"] != right["type"] or op not in {"eq", "ne"})):
                    raise _Unsupported("unsupported_comparison")
                conditions.append({"op": "compare", "type": "bool", "operator": op, "left": left, "right": right}); left = right
            return conditions[0] if len(conditions) == 1 else {"op": "and", "type": "bool", "args": conditions}
        if isinstance(node, ast.IfExp):
            condition, yes, no = self.expression(node.test, env), self.expression(node.body, env), self.expression(node.orelse, env)
            if condition["type"] != "bool" or yes["type"] != no["type"]:
                raise _Unsupported("inconsistent_conditional_type")
            return {"op": "select", "type": yes["type"], "condition": condition, "then": yes, "else": no}
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and self.imports.get(node.func.id) == "decimal.Decimal" and node.func.id not in self.bound:
                if len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant):
                    literal = node.args[0].value
                    if type(literal) is int or (type(literal) is str and _DECIMAL.fullmatch(literal)):
                        return _literal("decimal", literal)
                raise _Unsupported("unsupported_decimal_constructor")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "quantize" and len(node.args) == 1 and len(node.keywords) == 1:
                rounding = node.keywords[0]
                if rounding.arg != "rounding" or not isinstance(rounding.value, ast.Name) or rounding.value.id in self.bound:
                    raise _Unsupported("unsupported_rounding")
                mode = self.imports.get(rounding.value.id, "").removeprefix("decimal.")
                value, quantum = self.expression(node.func.value, env), self.expression(node.args[0], env)
                if mode not in ROUNDINGS or value["type"] != "decimal" or quantum["op"] != "literal" or quantum["type"] != "decimal":
                    raise _Unsupported("unsupported_rounding")
                return {"op": "quantize", "type": "decimal", "value": value, "quantum": quantum, "rounding": mode}
            raise _Unsupported("unresolved_call")
        raise _Unsupported("unsupported_expression")

    def sequence(self, statements, env, return_type):
        self.step()
        if not statements:
            raise _Unsupported("implicit_return")
        node, rest = statements[0], statements[1:]
        if isinstance(node, ast.Return):
            value = self.expression(node.value, env)
            if value["type"] != return_type:
                raise _Unsupported("return_type_mismatch")
            _count_tree(value)
            return {"op": "return", "value": value}
        if isinstance(node, ast.If):
            condition = self.expression(node.test, env)
            if condition["type"] != "bool":
                raise _Unsupported("implicit_truthiness")
            program = {"op": "if", "condition": condition,
                    "then": self.sequence(node.body + rest, env.copy(), return_type),
                    "else": self.sequence(node.orelse + rest, env.copy(), return_type)}
            _count_tree(program)
            return program
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) != 1 or not isinstance(targets[0], ast.Name) or not _identifier(targets[0].id):
                raise _Unsupported("unsupported_assignment")
            target = targets[0].id
            if isinstance(node, ast.AugAssign):
                value = self.expression(ast.BinOp(left=ast.Name(id=target, ctx=ast.Load()), op=node.op, right=node.value), env)
            else:
                value = self.expression(node.value, env)
            if isinstance(node, ast.AnnAssign) and self.annotation(node.annotation) != value["type"]:
                raise _Unsupported("assignment_type_mismatch")
            _count_tree(value)
            env = env.copy(); env[target] = value
            return self.sequence(rest, env, return_type)
        if isinstance(node, ast.Pass):
            return self.sequence(rest, env, return_type)
        raise _Unsupported("unsupported_statement")


def _boolean_tokens(source, language, budget):
    """Lex source without retaining string/comment contents or preprocessing it."""
    if re.search(r"\\u[0-9a-fA-F]{4}", source) or (language == "Java" and '"""' in source) or (language == "TypeScript" and "`" in source):
        raise _Unsupported("unsupported_lexical_preprocessing")
    tokens = []; index = 0; line = 1
    pattern = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+|===|!==|&&|\|\||==|!=|[{}();,:.!<>+*/=\[\]@?&|%-]")
    while index < len(source):
        char = source[index]
        if char.isspace():
            line += char == "\n"; index += 1; continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2); index = len(source) if end < 0 else end; continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0: raise _Unsupported("unterminated_comment")
            line += source[index:end + 2].count("\n"); index = end + 2; continue
        if char in "\"'":
            start_line = line; quote = char; index += 1; closed = False
            while index < len(source):
                if source[index] == "\\":
                    if index + 1 < len(source) and source[index + 1] == "\n": line += 1
                    index += 2
                elif source[index] == quote:
                    index += 1; closed = True; break
                elif source[index] in "\r\n":
                    raise _Unsupported("multiline_literal")
                else: index += 1
            if not closed: raise _Unsupported("unterminated_literal")
            tokens.append(("#literal", start_line))
        else:
            match = pattern.match(source, index)
            if not match: raise _Unsupported("unsupported_token")
            tokens.append((match.group(), line)); index = match.end()
        if len(tokens) > budget: raise _Unsupported("ast_budget")
    return tokens


class _BooleanGrammar:
    """A strict Java/TypeScript boolean-only grammar, not a general parser.

    Normalized ASTs contain only bool parameters, bool literals, comparisons,
    short circuit conditions, if and return. No calls, numeric coercion,
    assignments, strings, imports, object access or scope-changing constructs
    enter the semantic compiler.
    """
    def __init__(self, tokens, language, max_declarations=MAX_RULES):
        self.tokens = tokens; self.language = language; self.at = 0; self.depth = 0
        self.issues = set(); self.functions = []
        self.classes = []; self.declarations = []; self.detected_declarations = 0; self.unsupported_declarations = 0
        self.typescript_exported = False; self.typescript_bindings = []
        self.typescript_header_unverified = False
        self.max_declarations = max_declarations; self.module_complete = False

    def peek(self):
        return self.tokens[self.at][0] if self.at < len(self.tokens) else ""

    def take(self, expected=None):
        if self.at >= len(self.tokens) or (expected is not None and self.peek() != expected):
            raise _Unsupported("unsupported_boolean_syntax")
        value = self.tokens[self.at]; self.at += 1; return value

    def identifier(self):
        value = self.take()[0]
        reserved = {"if", "else", "return", "class", "function", "true", "false", "boolean", "int", "while", "for", "new", "this", "null", "void", "throw", "try", "let", "const", "var", "async", "await", "package", "import", "export", "default", "static", "public", "private", "protected", "abstract", "assert", "break", "byte", "case", "catch", "char", "continue", "do", "double", "enum", "extends", "final", "finally", "float", "goto", "implements", "instanceof", "interface", "long", "native", "short", "strictfp", "super", "switch", "synchronized", "throws", "transient", "volatile", "with", "yield", "delete", "typeof", "debugger"}
        if not _identifier(value) or value in reserved: raise _Unsupported("unsupported_identifier")
        return value

    def balanced(self, opener="{", closer="}"):
        start = self.take(opener); depth = 1; result = []
        while self.peek():
            value = self.take()
            if value[0] == opener: depth += 1
            if value[0] == closer: depth -= 1
            if depth > 64: raise _Unsupported("ast_budget")
            if depth == 0: return result, start[1], value[1]
            result.append(value)
        raise _Unsupported("unbalanced_source")

    def expression(self, level=0):
        self.depth += 1
        if self.depth > 48: raise _Unsupported("ast_budget")
        try:
            if level < 2:
                op = "||" if level == 0 else "&&"
                values = [self.expression(level + 1)]
                while self.peek() == op:
                    self.take(); values.append(self.expression(level + 1))
                return values[0] if len(values) == 1 else ast.BoolOp(op=ast.Or() if level == 0 else ast.And(), values=values)
            if level == 2:
                value = self.expression(3)
                allowed = {"==", "!="} if self.language == "Java" else {"==", "!=", "===", "!=="}
                while self.peek() in allowed:
                    op = self.take()[0]
                    value = ast.Compare(left=value, ops=[ast.Eq() if op in {"==", "==="} else ast.NotEq()], comparators=[self.expression(3)])
                return value
            if self.peek() == "!":
                self.take(); return ast.UnaryOp(op=ast.Not(), operand=self.expression(3))
            if self.peek() == "(":
                self.take(); value = self.expression(); self.take(")"); return value
            if self.peek() in {"true", "false"}:
                return ast.Constant(value=self.take()[0] == "true")
            return ast.Name(id=self.identifier(), ctx=ast.Load())
        finally:
            self.depth -= 1

    def statement(self):
        token, line = self.take()
        if token == "return":
            value = self.expression(); end = self.take(";")[1]
            return [ast.Return(value=value, lineno=line, end_lineno=end)]
        if token == "if":
            self.take("("); test = self.expression(); self.take(")")
            body = self.block_or_statement(); otherwise = []
            if self.peek() == "else": self.take(); otherwise = self.block_or_statement()
            return [ast.If(test=test, body=body, orelse=otherwise, lineno=line, end_lineno=self.tokens[self.at - 1][1])]
        raise _Unsupported("unsupported_boolean_statement")

    def block_or_statement(self):
        self.depth += 1
        if self.depth > 48: raise _Unsupported("ast_budget")
        try:
            if self.peek() != "{": return self.statement()
            self.take(); body = []
            while self.peek() and self.peek() != "}": body.extend(self.statement())
            self.take("}"); return body
        finally:
            self.depth -= 1

    def function(self, header, body, start, end, class_name=None):
        grammar = _BooleanGrammar(header, self.language); declared_name = None; header_complete = False
        try:
            if self.language == "Java":
                while grammar.peek() in {"public", "private", "protected", "static", "final", "synchronized", "strictfp"}:
                    modifier = grammar.take()[0]
                    if modifier == "synchronized": raise _Unsupported("synchronized_policy")
                grammar.take("boolean"); name = grammar.identifier()
            else:
                if grammar.peek() == "export": grammar.take()
                grammar.take("function"); name = grammar.identifier()
                declared_name = name
                self.typescript_bindings.append(name)
            grammar.take("("); parameters = []
            if grammar.peek() != ")":
                while True:
                    if self.language == "Java":
                        if grammar.peek() == "final": grammar.take()
                        grammar.take("boolean"); parameter = grammar.identifier()
                    else:
                        parameter = grammar.identifier()
                        self.typescript_bindings.append(parameter)
                        grammar.take(":"); grammar.take("boolean")
                    parameters.append(ast.arg(arg=parameter, annotation=ast.Name(id="bool", ctx=ast.Load())))
                    if len(parameters) > 16: raise _Unsupported("unsupported_signature")
                    if grammar.peek() != ",": break
                    grammar.take()
            grammar.take(")")
            if self.language == "TypeScript": grammar.take(":"); grammar.take("boolean")
            if grammar.peek() or len({p.arg for p in parameters}) != len(parameters): raise _Unsupported("unsupported_signature")
            header_complete = True
            statement_parser = _BooleanGrammar(body, self.language)
            statements = []
            while statement_parser.peek(): statements.extend(statement_parser.statement())
            if class_name: name = class_name + "__" + name
            function = ast.FunctionDef(name=name, args=ast.arguments(posonlyargs=[], args=parameters, kwonlyargs=[], kw_defaults=[], defaults=[]),
                body=statements, decorator_list=[], returns=ast.Name(id="bool", ctx=ast.Load()), lineno=start, end_lineno=end)
        except _Unsupported as error:
            if self.language == "TypeScript" and not header_complete:
                self.typescript_header_unverified = True
            self.issues.add(error.reason)
            # Preserve a denominator entry; no source names/text are emitted.
            function = ast.FunctionDef(name=declared_name or "unsupported_" + str(len(self.functions)), args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                body=[ast.Pass()], decorator_list=[], returns=None, lineno=start, end_lineno=end)
            function._policy_processing_reason = error.reason
        self.functions.append(function)

    def java_class(self):
        while self.peek() in {"public", "private", "protected", "final", "abstract", "static"}: self.take()
        self.take("class"); class_name = self.identifier()
        self.take("{")
        while self.peek() and self.peek() != "}":
            header = []; start = self.tokens[self.at][1]
            while self.peek() and self.peek() not in {"{", "}", ";"}: header.append(self.take())
            if self.peek() == ";":
                self.take(); self.issues.add("unsupported_class_member"); continue
            if self.peek() != "{": raise _Unsupported("unsupported_class_boundary")
            body, _, end = self.balanced()
            if any(token == "(" for token, _ in header) and not any(token in {"class", "interface", "enum", "@"} for token, _ in header):
                self.function(header, body, start, end, class_name)
            else: self.issues.add("unsupported_class_member")
        self.take("}")

    def typescript_class(self, start):
        """Observe a bounded declaration; never discard an arbitrary class body."""
        name = None; fields = None; boundary = "UNKNOWN"; reason = None
        self.detected_declarations += 1
        start_line = self.tokens[start][1]
        try:
            self.take("class"); name = self.identifier()
            # Class bindings are strict-mode identifiers even in a script.
            # Property names do not share this binding restriction.
            if name in {"eval", "arguments"}:
                raise _Unsupported("unsupported_typescript_class_binding")
            if self.peek() != "{": raise _Unsupported("unsupported_typescript_class_header")
            body, _, end_line = self.balanced()
            boundary = "balanced_class_body"
            members = _BooleanGrammar(body, self.language); field_names = set(); fields = 0
            while members.peek():
                field = members.identifier()
                if field == "constructor" or field in field_names:
                    raise _Unsupported("ambiguous_typescript_field")
                members.take(":")
                if members.take()[0] not in {"boolean", "number", "string"}:
                    raise _Unsupported("unsupported_typescript_field_type")
                members.take(";"); field_names.add(field); fields += 1
            # Class names participate in the same module binding table as
            # functions. Field values/types do not enter the policy compiler.
            self.classes.append(ast.ClassDef(name=name, bases=[], keywords=[], body=[], decorator_list=[],
                lineno=start_line, end_lineno=end_line))
        except _Unsupported as error:
            reason = error.reason
            self.issues.add("unsupported_typescript_declaration")
            self.issues.add(reason)
            if name is not None:
                self.classes.append(ast.ClassDef(name=name, bases=[], keywords=[], body=[], decorator_list=[],
                    lineno=start_line, end_lineno=self.tokens[max(start,self.at-1)][1]))
            if boundary == "UNKNOWN": raise
        finally:
            if reason:self.unsupported_declarations += 1
            row = {"declarationKind":"class", "name":name,
                "selection":"not_a_source_function", "status":"bounded_non_policy_declaration" if reason is None else "unsupported",
                "boundaryStatus":boundary, "lineStart":start_line,
                "lineEnd":self.tokens[max(start,self.at-1)][1],
                "tokenRange":{"start":start,"end":self.at,"unit":"boolean_lexer_token_index","endExclusive":True},
                "bodyForm":"UNKNOWN" if reason else "empty" if fields==0 else "uninitialized_primitive_type_fields",
                "fieldCount":fields if reason is None else None,
                "fieldTypeResolution":"syntax_only", "runtimeSemantics":"UNKNOWN",
                "limitations":["declaration_observation_not_policy_formula","target_emit_configuration_unknown"],
                "reasons":[reason] if reason else []}
            if len(self.declarations)<self.max_declarations:self.declarations.append(row)
            else:self.issues.add("typescript_declaration_inventory_budget")

    def module(self):
        while self.peek():
            if self.language == "Java":
                if self.peek() in {"package", "import"}:
                    self.take()
                    while self.peek() and self.peek() != ";":
                        value = self.take()[0]
                        if not (_IDENTIFIER.fullmatch(value) or value in {".", "*"}): raise _Unsupported("unsupported_import")
                    self.take(";"); continue
                if self.peek() == "@":
                    self.take(); self.identifier()
                    if self.peek() == "(": self.balanced("(", ")")
                    self.issues.add("java_annotation_semantics_unresolved"); continue
                self.java_class()
            else:
                declaration_start = self.at
                if self.peek()=="export":
                    self.typescript_exported = True
                    following=self.tokens[self.at+1][0] if self.at+1<len(self.tokens) else ''
                    if following=='class':self.take()
                    elif following!='function':raise _Unsupported('unsupported_typescript_module')
                if self.peek()=="class":
                    self.typescript_class(declaration_start); continue
                header = []; start = self.tokens[self.at][1]
                if self.peek() not in {"export", "function"}: raise _Unsupported("unsupported_typescript_module")
                while self.peek() and self.peek() not in {"{", ";", "}"}: header.append(self.take())
                body, _, end = self.balanced(); self.function(header, body, start, end)
        self.module_complete = True
        if self.language=="TypeScript":
            # Any export makes the complete source a strict module, including
            # functions preceding it and unsupported bodies with parsed bindings.
            # A partially parsed signature can hide an invalid strict binding.
            # Withhold the module rather than certify unaffected-looking rules.
            if self.typescript_exported and self.typescript_header_unverified:
                raise _Unsupported("typescript_module_header_unverified")
            if self.typescript_exported and any(name in {"eval", "arguments"} for name in self.typescript_bindings):
                raise _Unsupported("unsupported_typescript_strict_binding")
            names=[n.name for n in self.classes+self.functions]
            if len(names)!=len(set(names)):self.issues.add("ambiguous_typescript_module_binding")
        return ast.Module(body=self.classes+self.functions, type_ignores=[]), self.issues


def extract_policy_rules(source: str, language: str, relative_path: str, source_digest: str, *, max_rules=MAX_RULES, max_ast_nodes=MAX_AST_NODES, max_declarations=MAX_RULES) -> dict:
    """Compile actual source; all failures are bounded categories without text."""
    path = _relative_path(relative_path)
    if not isinstance(source, str) or not isinstance(language, str) or not isinstance(source_digest, str):
        raise PolicyError("invalid_arguments")
    if type(max_rules) is not int or not 1 <= max_rules <= MAX_RULES or type(max_ast_nodes) is not int or not 1 <= max_ast_nodes <= MAX_AST_BUDGET:
        raise PolicyError("invalid_arguments")
    if type(max_declarations) is not int or not 0<=max_declarations<=MAX_RULES:raise PolicyError("invalid_arguments")
    grammar = None
    seen = []
    function_outcomes = {}
    def declarations():
        if grammar is None or not grammar.detected_declarations:return
        result['sourceDeclarations']=[]
        for observation in grammar.declarations:
            identity=hashlib.sha256(_canonical([path,digest,observation['tokenRange']])).hexdigest()
            result['sourceDeclarations'].append({'id':'semantic:policy-declaration:'+identity,'path':path,'sourceDigest':digest,
                'category':'source_policy_declaration','span':{'lineStart':observation['lineStart'],'lineEnd':observation['lineEnd']},
                'representationStatus':'partial' if observation['status']=='bounded_non_policy_declaration' else 'unsupported',
                'expression':{'op':'source_declaration',**observation},'references':[],
                'unsupportedReasons':observation['reasons'],'businessMeaningVerified':False,'runtimeStatus':'not_observed',
                'extractorVersion':DECLARATION_EXTRACTOR_VERSION})
        coverage['sourceDeclarationCoverage']={'scope':'recognized_top_level_typescript_class_declarations',
            'detectedDeclarations':grammar.detected_declarations,'recordedDeclarations':len(grammar.declarations),
            'unsupportedDeclarations':grammar.unsupported_declarations,
            'omittedDeclarations':grammar.detected_declarations-len(grammar.declarations),
            'inventoryComplete':grammar.module_complete and grammar.detected_declarations==len(grammar.declarations),
            'unknownDenominator':not grammar.module_complete,'businessPolicyComplete':False,
            'reasons':sorted(grammar.issues & {'unsupported_typescript_declaration','typescript_declaration_inventory_budget'})}
    try:
        raw = source.encode("utf-8")
    except UnicodeError:
        raise PolicyError("invalid_arguments") from None
    if len(raw) > MAX_SOURCE_BYTES:
        raise PolicyError("source_quota")
    digest = source_digest.removeprefix("sha256:")
    if not _DIGEST.fullmatch(digest) or hashlib.sha256(raw).hexdigest() != digest:
        raise PolicyError("source_digest_mismatch")
    result = {"schemaVersion": SCHEMA_VERSION, "ruleVersion": RULE_VERSION, "rules": [], "evidence": [],
        "coverage": {"detectedRules": 0, "analyzedRules": 0, "unsupportedRules": 0, "complete": False, "unknownDenominator": True,
            "scope": "typed_pure_source_functions", "businessPolicyComplete": False, "reasons": []},
        "modelIdentity": "modelNotUsed", "repeatability": "N/A"}
    coverage = result["coverage"]
    def function_processing(functions, *, enumeration_unknown, fallback_reason=None):
        # Locations are diagnostic evidence. Do not emit or hash a rejected
        # function's name, body, parameters, literals or exception text.
        _safe({"path": path, "sourceDigest": digest})
        ordered = sorted(enumerate(functions), key=lambda pair: (
            getattr(pair[1], "lineno", 0), getattr(pair[1], "col_offset", 0), pair[0]))
        rows = result.setdefault("sourceFunctionOutcomes", [])
        available = max(0, max_declarations - len(result.get("sourceDeclarations", [])))
        counts = {"extractedFunctions": 0, "unsupportedFunctions": 0, "notAnalyzedFunctions": 0}
        recorded = 0
        reasons = {fallback_reason} if fallback_reason else set()
        if enumeration_unknown and not ordered and not fallback_reason:
            reasons.add("function_enumeration_incomplete")
        for index, (_, function) in enumerate(ordered):
            outcome = function_outcomes.get(id(function))
            if outcome is None:
                outcome = ("not_analyzed", fallback_reason, None) if fallback_reason else (
                    "unsupported", "nested_class_or_async_function", None)
            disposition, reason, rule_id = outcome
            if reason is not None and not re.fullmatch(r"[a-z_]{1,100}", reason):
                reason = "unsupported_policy"
            counts[{"extracted": "extractedFunctions", "unsupported": "unsupportedFunctions",
                    "not_analyzed": "notAnalyzedFunctions"}[disposition]] += 1
            if reason: reasons.add(reason)
            first, last = getattr(function, "lineno", None), getattr(function, "end_lineno", None)
            if type(first) is not int or type(last) is not int or not 1 <= first <= last:
                reasons.add("function_location_unavailable")
                continue
            if recorded >= available:
                reasons.add("function_outcome_budget")
                continue
            span = {"lineStart": first, "lineEnd": last}
            identity = hashlib.sha256(_canonical([path, digest, span, index])).hexdigest()
            row = {"id": "semantic:policy-function:" + identity, "path": path, "sourceDigest": digest,
                "category": "source_policy_function_processing", "span": span, "representationStatus": "coverage_metadata",
                "expression": {"op": "source_declaration", "schemaVersion": 1,
                    "declarationKind": "policy_function_processing", "inputIndex": index,
                    "disposition": disposition, "reason": reason, "acceptedPolicyRuleId": rule_id,
                    "scope": "recognized_typed_policy_function_candidates"},
                "references": [], "unsupportedReasons": [reason] if reason else [],
                "businessMeaningVerified": False, "runtimeStatus": "not_observed",
                "extractorVersion": "policy-function-outcomes-1"}
            _safe(row)
            rows.append(row); recorded += 1
        recognized = len(ordered)
        coverage["sourceFunctionProcessing"] = function_processing_summary({
            "schemaVersion": 1, "scope": "recognized_typed_policy_function_candidates",
            "recognizedFunctions": recognized, "serializedOutcomes": recorded,
            "omittedOutcomes": recognized - recorded, **counts,
            "inventoryComplete": recorded == recognized and not enumeration_unknown,
            "unknownDenominator": bool(enumeration_unknown), "wholeSourceFunctionDenominator": "UNKNOWN",
            "businessPolicyComplete": False, "reasons": sorted(reasons)})
    language = {"py": "Python", "python": "Python", "java": "Java", "typescript": "TypeScript", "ts": "TypeScript"}.get(language.casefold(), language)
    if language not in {"Python", "Java", "TypeScript"}:
        coverage["reasons"] = ["unsupported_policy_language"]
        function_processing([], enumeration_unknown=True, fallback_reason="unsupported_policy_language")
        return result
    try:
        language_issues = set()
        if language == "Python":
            tree = ast.parse(source)
        else:
            grammar = _BooleanGrammar(_boolean_tokens(source, language, max_ast_nodes), language, max_declarations)
            tree, language_issues = grammar.module()
        pending = [(tree, 0)]; seen = []
        while pending:
            node, depth = pending.pop(); seen.append(node)
            if len(seen) > max_ast_nodes or depth > 64:
                raise _Unsupported("ast_budget")
            pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    except (SyntaxError, ValueError, MemoryError, RecursionError, _Unsupported) as error:
        coverage["reasons"] = [error.reason if isinstance(error, _Unsupported) else "parse_failure"]
        if grammar is not None:
            coverage.update(detectedRules=len(grammar.functions),unsupportedRules=len(grammar.functions))
        declarations()
        known = grammar.functions if grammar is not None else [n for n in seen if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        coverage.update(detectedRules=len(known), unsupportedRules=len(known))
        function_processing(known, enumeration_unknown=True, fallback_reason=coverage["reasons"][0])
        return _safe(result)
    declarations()
    all_functions = [n for n in seen if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    coverage.update(detectedRules=len(all_functions), unknownDenominator=False)
    reasons = set(language_issues)
    if 'unsupported_typescript_declaration' in reasons:
        coverage['unknownDenominator']=True
    if len(functions) != len(all_functions):
        reasons.add("nested_class_or_async_function")
    imports = {}; global_values = {}; counts = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "decimal" and node.level == 0:
            for alias in node.names:
                if alias.name in ROUNDINGS | {"Decimal"}:
                    name = alias.asname or alias.name; imports[name] = "decimal." + alias.name; counts[name] = counts.get(name, 0) + 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            names = [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)] if isinstance(node, (ast.Assign, ast.AnnAssign)) else [a.asname or a.name.split('.')[0] for a in node.names]
            for name in names:
                counts[name] = counts.get(name, 0) + 1
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            reasons.add("dynamic_module_scope")
    imports = {key: value for key, value in imports.items() if counts.get(key) == 1}
    stub = ast.FunctionDef(name="synthetic", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[], decorator_list=[])
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                reasons.add("dynamic_module_scope")
            if len(targets) == 1 and isinstance(targets[0], ast.Name) and counts.get(targets[0].id) == 1 and _identifier(targets[0].id):
                try:
                    value = _Compiler(imports, {}, stub).expression(node.value, {})
                    if value["op"] == "literal":
                        global_values[targets[0].id] = value
                    else:
                        reasons.add("unsupported_module_initializer")
                except (_Unsupported, PolicyError):
                    reasons.add("unsupported_module_initializer")
    decimal_context_mutated = any(isinstance(n, ast.Call) and ((isinstance(n.func, ast.Name) and n.func.id in {"setcontext", "getcontext", "localcontext"}) or (isinstance(n.func, ast.Attribute) and n.func.attr in {"setcontext", "getcontext", "localcontext"})) for n in seen)
    for function in functions:
        if len(result["rules"]) >= max_rules:
            reasons.add("rule_budget")
            function_outcomes[id(function)] = ("not_analyzed", "rule_budget", None)
            continue
        try:
            if "unsupported_typescript_declaration" in reasons or "ambiguous_typescript_module_binding" in reasons:
                raise _Unsupported("typescript_module_binding_unverified")
            if "dynamic_module_scope" in reasons or "unsupported_module_initializer" in reasons:
                raise _Unsupported("dynamic_module_scope")
            if not _identifier(function.name) or counts.get(function.name) != 1 or function.decorator_list:
                raise _Unsupported("ambiguous_or_decorated_function")
            if counts.get("int", 0) or counts.get("bool", 0):
                raise _Unsupported("shadowed_builtin_type")
            if function.args.vararg or function.args.kwarg or len(function.args.args + function.args.posonlyargs + function.args.kwonlyargs) > 16:
                raise _Unsupported("unsupported_signature")
            compiler = _Compiler(imports, global_values, function)
            return_type = compiler.annotation(function.returns)
            parameters = []; env = {}
            positional = function.args.posonlyargs + function.args.args
            defaults = [None] * (len(positional) - len(function.args.defaults)) + list(function.args.defaults)
            for argument, default in zip(positional + function.args.kwonlyargs, defaults + function.args.kw_defaults):
                if not _identifier(argument.arg):
                    raise _Unsupported("unsupported_parameter")
                kind = compiler.annotation(argument.annotation)
                parameter = {"name": argument.arg, "type": kind, "finiteValues": [False, True] if kind == "bool" else None}
                if default is not None:
                    value = compiler.expression(default, {})
                    if value["op"] != "literal" or value["type"] != kind:
                        raise _Unsupported("unsupported_default")
                    parameter["default"] = {key: val for key, val in value.items() if key != "op"}
                parameters.append(parameter); env[argument.arg] = {"op": "input", "name": argument.arg, "type": kind}
            if decimal_context_mutated and (return_type == "decimal" or any(p["type"] == "decimal" for p in parameters)):
                raise _Unsupported("mutable_decimal_context")
            body = function.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            program = compiler.sequence(body, env, return_type); _count_tree(program)
            evidence_id = "assertion:policy:" + hashlib.sha256((path + ":" + digest + ":" + str(function.lineno) + ":" + function.name).encode()).hexdigest()[:32]
            identifier = "policy:" + hashlib.sha256((path + ":" + function.name).encode()).hexdigest()[:32]
            words = set(re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", function.name + "_" + path).lower()))
            domains = [{"name": name, "basis": "identifier_tokens", "evidenceIds": [evidence_id]} for name in DOMAINS if words & _DOMAIN_WORDS[name]]
            if not domains:
                domains = [{"name": "unclassified", "basis": "unclassified", "evidenceIds": [evidence_id]}]
            evidence = {"id": evidence_id, "relativePath": path, "lineStart": function.lineno, "lineEnd": function.end_lineno,
                        "sourceDigest": digest, "ruleVersion": RULE_VERSION, "basis": "resolved_static", "runtimeStatus": "runtime_unknown"}
            rule = {"id": identifier, "name": function.name, "language": language, "domains": domains, "parameters": parameters, "returnType": return_type,
                "program": program, "sourceAssertionIds": [evidence_id], "sourceDigest": digest, "ruleVersion": RULE_VERSION,
                "relativePath": path, "lineStart": function.lineno, "lineEnd": function.end_lineno,
                "status": "extraction_verified", "authority": {"kind": "implemented-rule", "rulesetAuthority": RULESET_AUTHORITY},
                "configProfile": "source-default", "validity": {"from": None, "to": None, "status": "undeclared"},
                "numericContext": {"precision": 28, "rounding": "ROUND_HALF_EVEN", "unit": "unspecified", "currency": None},
                "combinations": {"stackability": "unknown", "precedence": "source-control-flow", "caps": "expression-only"},
                "complete": True, "modelIdentity": "modelNotUsed", "repeatability": "N/A"}
            _safe(rule); _safe(evidence)
            result["rules"].append(rule); result["evidence"].append(evidence)
            function_outcomes[id(function)] = ("extracted", None, identifier)
        except (_Unsupported, PolicyError, RecursionError) as error:
            reason = error.reason if isinstance(error, _Unsupported) else "privacy_denied" if isinstance(error, PolicyError) and error.code == "privacy_denied" else "unsupported_policy"
            reasons.add(reason)
            function_outcomes[id(function)] = ("unsupported", getattr(function, "_policy_processing_reason", reason), None)
    coverage["analyzedRules"] = len(result["rules"])
    coverage["unsupportedRules"] = len(all_functions) - len(result["rules"])
    if not all_functions:
        reasons.add("no_policy_functions"); coverage["unknownDenominator"] = True
    coverage["reasons"] = sorted(reasons)
    function_processing(all_functions, enumeration_unknown=coverage["unknownDenominator"])
    coverage["complete"] = bool(all_functions) and not reasons and not coverage["unsupportedRules"] and not coverage['unknownDenominator'] and coverage["sourceFunctionProcessing"]["inventoryComplete"]
    return _safe(result)


FUNCTION_PROCESSING_COUNTS = ("recognizedFunctions", "serializedOutcomes", "omittedOutcomes",
                              "extractedFunctions", "unsupportedFunctions", "notAnalyzedFunctions")


def function_processing_summary(value):
    """Closed accounting of recognized function attempts, not all code meaning."""
    unavailable = {"schemaVersion": 1, "scope": "recognized_typed_policy_function_candidates",
        **{key: "UNKNOWN" for key in FUNCTION_PROCESSING_COUNTS}, "inventoryComplete": False,
        "unknownDenominator": True, "wholeSourceFunctionDenominator": "UNKNOWN",
        "businessPolicyComplete": False, "reasons": ["function_processing_unavailable"]}
    if value is None or (type(value) is dict and set(value) == set(unavailable)
            and all(type(value[key]) is type(expected) and value[key] == expected
                    for key, expected in unavailable.items())):
        return copy.deepcopy(unavailable)
    if (type(value) is not dict or set(value) != set(unavailable)
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1
            or value.get("scope") != unavailable["scope"]
            or any(type(value.get(key)) is not int or value[key] < 0 for key in FUNCTION_PROCESSING_COUNTS)
            or type(value.get("inventoryComplete")) is not bool or type(value.get("unknownDenominator")) is not bool
            or value.get("wholeSourceFunctionDenominator") != "UNKNOWN" or value.get("businessPolicyComplete") is not False
            or type(value.get("reasons")) is not list or len(value["reasons"]) > 64
            or any(type(reason) is not str or not re.fullmatch(r"[a-z_]{1,100}", reason) for reason in value["reasons"])
            or value["reasons"] != sorted(set(value["reasons"]))):
        raise PolicyError("invalid_snapshot")
    recognized = value["recognizedFunctions"]
    if (recognized != value["serializedOutcomes"] + value["omittedOutcomes"]
            or recognized != sum(value[k] for k in ("extractedFunctions", "unsupportedFunctions", "notAnalyzedFunctions"))
            or value["inventoryComplete"] != (value["omittedOutcomes"] == 0 and not value["unknownDenominator"])):
        raise PolicyError("invalid_snapshot")
    return copy.deepcopy(value)


def merge_function_processing(target, source):
    value = function_processing_summary(source.get("sourceFunctionProcessing"))
    prior = target.get("sourceFunctionProcessing")
    if prior is None:
        target["sourceFunctionProcessing"] = value
        return
    prior = function_processing_summary(prior)
    if prior["recognizedFunctions"] == "UNKNOWN" or value["recognizedFunctions"] == "UNKNOWN":
        target["sourceFunctionProcessing"] = function_processing_summary(None)
        return
    combined = copy.deepcopy(prior)
    for key in FUNCTION_PROCESSING_COUNTS:
        combined[key] += value[key]
    combined["unknownDenominator"] |= value["unknownDenominator"]
    combined["inventoryComplete"] = combined["omittedOutcomes"] == 0 and not combined["unknownDenominator"]
    combined["reasons"] = sorted(set(prior["reasons"]) | set(value["reasons"]))
    target["sourceFunctionProcessing"] = function_processing_summary(combined)


def policy_ruleset_digest(records: dict) -> str:
    payload = {"schemaVersion": records.get("schemaVersion", SCHEMA_VERSION), "rules": records.get("rules", []),
               "evidence": records.get("evidence", []), "coverage": records.get("coverage", {})}
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def declaration_coverage_summary(value):
    """Closed, source-free structural accounting; absence never means zero."""
    scope = "recognized_top_level_typescript_class_declarations"
    counts = ("detectedDeclarations", "recordedDeclarations", "unsupportedDeclarations", "omittedDeclarations")
    unavailable = {"scope": scope, **{key: "UNKNOWN" for key in counts},
                   "inventoryComplete": False, "unknownDenominator": True,
                   "businessPolicyComplete": False, "reasons": ["declaration_coverage_unavailable"]}
    if value is None or value == unavailable:
        return copy.deepcopy(unavailable)
    allowed = set(counts) | {"scope", "inventoryComplete", "unknownDenominator", "businessPolicyComplete", "reasons"}
    if (type(value) is not dict or set(value) != allowed or value.get("scope") != scope
            or any(type(value.get(key)) is not int or value[key] < 0 for key in counts)
            or type(value.get("inventoryComplete")) is not bool
            or type(value.get("unknownDenominator")) is not bool
            or value.get("businessPolicyComplete") is not False
            or value["recordedDeclarations"] + value["omittedDeclarations"] != value["detectedDeclarations"]
            or value["unsupportedDeclarations"] > value["detectedDeclarations"]
            or (value["inventoryComplete"] and (value["unknownDenominator"] or value["omittedDeclarations"]))
            or type(value.get("reasons")) is not list
            or any(type(reason) is not str or reason not in {"unsupported_typescript_declaration", "typescript_declaration_inventory_budget"}
                   for reason in value["reasons"])):
        raise PolicyError("invalid_snapshot")
    return copy.deepcopy(value)


def merge_declaration_coverage(target, source):
    """Separate structural selection accounting; never a policy-rule numerator."""
    row=source.get('sourceDeclarationCoverage')
    if row is None:return
    summary=target.setdefault('sourceDeclarationCoverage',{'scope':'recognized_top_level_typescript_class_declarations',
        'detectedDeclarations':0,'recordedDeclarations':0,'unsupportedDeclarations':0,'omittedDeclarations':0,
        'inventoryComplete':True,'unknownDenominator':False,'businessPolicyComplete':False,'reasons':[]})
    for key in ('detectedDeclarations','recordedDeclarations','unsupportedDeclarations','omittedDeclarations'):
        summary[key]+=row[key]
    summary['inventoryComplete'] &= row['inventoryComplete'] is True
    summary['unknownDenominator'] |= row['unknownDenominator'] is not False
    summary['reasons']=sorted(set(summary['reasons'])|set(row['reasons']))


def seal_policy_snapshot(extractions, *, catalog_snapshot_id, policy_snapshot_id, created_at, source_last_verified_at=None):
    """In-memory sealing helper; the store owns durable atomic publication."""
    rules = []; evidence = []; coverages = []
    for item in extractions:
        rules.extend(copy.deepcopy(item["rules"])); evidence.extend(copy.deepcopy(item["evidence"])); coverages.append(item["coverage"])
    coverage = {"detectedRules": sum(c["detectedRules"] for c in coverages), "analyzedRules": len(rules),
        "unsupportedRules": sum(c["unsupportedRules"] for c in coverages), "complete": bool(coverages) and all(c["complete"] for c in coverages),
        "unknownDenominator": not coverages or any(c["unknownDenominator"] for c in coverages),
        "scope": "selected_source_functions", "businessPolicyComplete": False, "reasons": sorted({r for c in coverages for r in c["reasons"]})}
    for item in coverages:
        merge_declaration_coverage(coverage,item)
        merge_function_processing(coverage,item)
    result = {"schemaVersion": SCHEMA_VERSION, "rules": sorted(rules, key=lambda x: x["id"]), "evidence": sorted(evidence, key=lambda x: x["id"]),
        "coverage": coverage, "catalogSnapshotId": catalog_snapshot_id, "policySnapshotId": policy_snapshot_id,
        "createdAt": created_at, "sourceLastVerifiedAt": source_last_verified_at}
    result["rulesetDigest"] = policy_ruleset_digest(result)
    _snapshot(result)
    return result


def _validate_expression(expr, parameter_types, budget):
    budget[0] += 1
    if budget[0] > MAX_IR_NODES or not isinstance(expr, dict) or expr.get("type") not in TYPES:
        raise PolicyError("invalid_ir")
    op, kind = expr.get("op"), expr["type"]
    def child(name):
        return _validate_expression(expr[name], parameter_types, budget)
    if op == "literal":
        if set(expr) != {"op", "type", "value"} or _literal(kind, expr["value"]) != expr:
            raise PolicyError("invalid_ir")
    elif op == "input":
        if set(expr) != {"op", "type", "name"} or parameter_types.get(expr["name"]) != kind:
            raise PolicyError("invalid_ir")
    elif op in {"not", "neg", "pos"}:
        if set(expr) != {"op", "type", "arg"} or child("arg") != kind or (op == "not") != (kind == "bool"):
            raise PolicyError("invalid_ir")
    elif op in {"and", "or"}:
        if set(expr) != {"op", "type", "args"} or kind != "bool" or not isinstance(expr["args"], list) or not 2 <= len(expr["args"]) <= 128:
            raise PolicyError("invalid_ir")
        if any(_validate_expression(x, parameter_types, budget) != "bool" for x in expr["args"]):
            raise PolicyError("invalid_ir")
    elif op in {"add", "sub", "mul", "div", "floordiv", "mod", "compare"}:
        expected = {"op", "type", "left", "right"} | ({"operator"} if op == "compare" else set())
        if set(expr) != expected:
            raise PolicyError("invalid_ir")
        left, right = child("left"), child("right")
        if op == "compare":
            if kind != "bool" or expr["operator"] not in {"eq", "ne", "lt", "le", "gt", "ge"} or ("bool" in {left, right} and (left != right or expr["operator"] not in {"eq", "ne"})):
                raise PolicyError("invalid_ir")
        elif "bool" in {left, right} or kind != ("decimal" if "decimal" in {left, right} else "int") or (op == "div" and kind != "decimal") or (op in {"mod", "floordiv"} and kind != "int"):
            raise PolicyError("invalid_ir")
    elif op == "select":
        if set(expr) != {"op", "type", "condition", "then", "else"} or child("condition") != "bool" or child("then") != kind or child("else") != kind:
            raise PolicyError("invalid_ir")
    elif op == "quantize":
        if set(expr) != {"op", "type", "value", "quantum", "rounding"} or kind != "decimal" or child("value") != "decimal" or child("quantum") != "decimal" or expr["quantum"]["op"] != "literal" or expr["rounding"] not in ROUNDINGS:
            raise PolicyError("invalid_ir")
    else:
        raise PolicyError("invalid_ir")
    return kind


def _validate_program(program, parameters, return_type, budget):
    budget[0] += 1
    if budget[0] > MAX_IR_NODES or not isinstance(program, dict):
        raise PolicyError("invalid_ir")
    if program.get("op") == "return" and set(program) == {"op", "value"}:
        if _validate_expression(program["value"], parameters, budget) != return_type:
            raise PolicyError("invalid_ir")
    elif program.get("op") == "if" and set(program) == {"op", "condition", "then", "else"}:
        if _validate_expression(program["condition"], parameters, budget) != "bool":
            raise PolicyError("invalid_ir")
        _validate_program(program["then"], parameters, return_type, budget); _validate_program(program["else"], parameters, return_type, budget)
    else:
        raise PolicyError("invalid_ir")


def _snapshot(records, catalog_snapshot_id=None, policy_snapshot_id=None, ruleset_digest=None):
    try:
        if not isinstance(records, dict) or len(_canonical(records)) > MAX_SNAPSHOT_BYTES:
            raise PolicyError("snapshot_quota")
        _safe(records)
        for key in ("catalogSnapshotId", "policySnapshotId"):
            if not isinstance(records.get(key), str) or not _OPAQUE.fullmatch(records[key]):
                raise PolicyError("invalid_snapshot")
        for expected, key in ((catalog_snapshot_id, "catalogSnapshotId"), (policy_snapshot_id, "policySnapshotId"), (ruleset_digest, "rulesetDigest")):
            if expected is not None and expected != records.get(key):
                raise PolicyError("snapshot_pin_mismatch")
        if records.get("rulesetDigest") != policy_ruleset_digest(records):
            raise PolicyError("snapshot_digest_mismatch")
        rules, evidence, coverage = records["rules"], records["evidence"], records["coverage"]
        if not isinstance(rules, list) or not isinstance(evidence, list) or len(rules) > 10000 or len(evidence) > 20000:
            raise PolicyError("invalid_snapshot")
        if not isinstance(coverage, dict) or type(coverage.get("complete")) is not bool:
            raise PolicyError("invalid_snapshot")
        if type(coverage.get("unknownDenominator")) is not bool or any(type(coverage.get(k)) is not int or coverage[k] < 0 for k in ("detectedRules", "analyzedRules", "unsupportedRules")):
            raise PolicyError("invalid_snapshot")
        if coverage["analyzedRules"] != len(rules) or coverage["detectedRules"] < coverage["analyzedRules"] + coverage["unsupportedRules"]:
            raise PolicyError("invalid_snapshot")
        if coverage["complete"] and (coverage["unknownDenominator"] or coverage["unsupportedRules"] or coverage.get("reasons")):
            raise PolicyError("invalid_snapshot")
        if "sourceFunctionProcessing" in coverage:
            processing = function_processing_summary(coverage["sourceFunctionProcessing"])
            if type(processing["recognizedFunctions"]) is int and coverage["complete"] and not processing["inventoryComplete"]:
                raise PolicyError("invalid_snapshot")
        declaration=coverage.get('sourceDeclarationCoverage')
        if declaration is not None:
            keys=('detectedDeclarations','recordedDeclarations','unsupportedDeclarations','omittedDeclarations')
            if (not isinstance(declaration,dict) or any(type(declaration.get(k))is not int or declaration[k]<0 for k in keys)
                    or declaration['recordedDeclarations']+declaration['omittedDeclarations']!=declaration['detectedDeclarations']
                    or declaration['unsupportedDeclarations']>declaration['detectedDeclarations']
                    or type(declaration.get('inventoryComplete'))is not bool or type(declaration.get('unknownDenominator'))is not bool
                    or declaration.get('businessPolicyComplete')is not False
                    or (declaration['inventoryComplete']and(declaration['unknownDenominator']or declaration['omittedDeclarations']))
                    or (coverage['complete']and(not declaration['inventoryComplete']or declaration['unsupportedDeclarations']))):
                raise PolicyError('invalid_snapshot')
        evidence_ids = {item["id"]: item for item in evidence}
        if len(evidence_ids) != len(evidence) or len({rule["id"] for rule in rules}) != len(rules):
            raise PolicyError("invalid_snapshot")
        for item in evidence:
            _relative_path(item["relativePath"])
            if not _OPAQUE.fullmatch(item["id"]) or item["ruleVersion"] != RULE_VERSION or item.get("basis") != "resolved_static" or item.get("runtimeStatus") != "runtime_unknown" or not _DIGEST.fullmatch(item["sourceDigest"]) or type(item["lineStart"]) is not int or type(item["lineEnd"]) is not int or not 1 <= item["lineStart"] <= item["lineEnd"] <= 10_000_000:
                raise PolicyError("invalid_snapshot")
        for rule in rules:
            _count_tree(rule)
            if not _OPAQUE.fullmatch(rule["id"]) or not _identifier(rule["name"]) or rule["returnType"] not in TYPES or rule["ruleVersion"] != RULE_VERSION:
                raise PolicyError("invalid_ir")
            params = rule["parameters"]
            if not isinstance(params, list) or len(params) > 16 or len({p["name"] for p in params}) != len(params):
                raise PolicyError("invalid_ir")
            for parameter in params:
                if not _identifier(parameter["name"]) or parameter["type"] not in TYPES or parameter.get("finiteValues") != ([False, True] if parameter["type"] == "bool" else None):
                    raise PolicyError("invalid_ir")
                if "default" in parameter:
                    if parameter["default"].get("type") != parameter["type"]:
                        raise PolicyError("invalid_ir")
                    _validate_expression({"op": "literal", **parameter["default"]}, {}, [0])
            _validate_program(rule["program"], {p["name"]: p["type"] for p in params}, rule["returnType"], [0])
            refs = rule["sourceAssertionIds"]
            if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
                raise PolicyError("invalid_snapshot")
            for ref in refs:
                item = evidence_ids[ref]
                if any(item[key] != rule[key] for key in ("sourceDigest", "relativePath", "lineStart", "lineEnd", "ruleVersion")):
                    raise PolicyError("invalid_snapshot")
            if not rule["domains"] or any(d["name"] not in DOMAINS + ("unclassified",) or set(d["evidenceIds"]) - set(refs) for d in rule["domains"]):
                raise PolicyError("invalid_snapshot")
            if rule.get("numericContext") != {"precision": 28, "rounding": "ROUND_HALF_EVEN", "unit": "unspecified", "currency": None}:
                raise PolicyError("invalid_ir")
        return records
    except PolicyError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError, _Unsupported):
        raise PolicyError("invalid_snapshot") from None


def _summary(snapshot, policy_view="verified_implemented", ruleset_authority=None):
    return {"catalogSnapshotId": snapshot["catalogSnapshotId"], "policySnapshotId": snapshot["policySnapshotId"],
        "rulesetDigest": snapshot["rulesetDigest"], "coverage": copy.deepcopy(snapshot["coverage"]),
        "transactionTime": snapshot.get("createdAt"), "sourceLastVerifiedAt": snapshot.get("sourceLastVerifiedAt"),
        "policyView": policy_view, "rulesetAuthority": ruleset_authority or RULESET_AUTHORITY,
        "businessValidity": "UNKNOWN", "runtimeStatus": "runtime_unknown", "modelIdentity": "modelNotUsed", "repeatability": "N/A"}


def _view(rule, policy_view, authority):
    if policy_view not in {"verified_implemented", "approved_business"}:
        raise PolicyError("invalid_policy_view")
    if policy_view == "approved_business" and not authority:
        raise PolicyError("authority_required")
    if rule.get("status") != "extraction_verified" or rule.get("complete") is not True:
        return False
    record = rule.get("authority", {})
    if policy_view == "verified_implemented":
        return record.get("kind") == "implemented-rule" and record.get("rulesetAuthority") == (authority or RULESET_AUTHORITY)
    return record.get("kind") == "approved-business-policy" and record.get("rulesetAuthority") == authority and isinstance(record.get("approvalVersion"), str) and bool(record["approvalVersion"])


def _page(offset, limit):
    if type(offset) is not int or not 0 <= offset <= 1_000_000 or type(limit) is not int or not 1 <= limit <= 100:
        raise PolicyError("invalid_arguments")


def list_domain_policies(snapshot, domain=None, *, offset=0, limit=50, policy_view="verified_implemented", ruleset_authority=None):
    snapshot = _snapshot(snapshot); _page(offset, limit)
    if domain is not None and domain not in DOMAINS + ("unclassified",):
        raise PolicyError("invalid_arguments")
    # Validate view even when no rules exist.
    _view({}, policy_view, ruleset_authority)
    rows = []
    for name in DOMAINS + ("unclassified",):
        if domain and name != domain:
            continue
        rules = [r for r in snapshot["rules"] if any(d["name"] == name for d in r["domains"])]
        eligible = [r for r in rules if _view(r, policy_view, ruleset_authority)]
        rows.append({"domain": name, "ruleCount": len(rules), "verifiedRuleCount": len(eligible), "classification": "identifier_candidates",
                     "businessPolicyComplete": False, "evidenceIds": sorted({i for r in rules for i in r["sourceAssertionIds"]})[:100]})
    return _safe({**_summary(snapshot, policy_view, ruleset_authority), "domains": rows[offset:offset + limit], "total": len(rows),
                  "nextOffset": offset + limit if offset + limit < len(rows) else None})


def query_policy_rules(snapshot, domain=None, rule_id=None, *, offset=0, limit=50, policy_view="verified_implemented", ruleset_authority=None):
    snapshot = _snapshot(snapshot); _page(offset, limit); _view({}, policy_view, ruleset_authority)
    if domain is not None and domain not in DOMAINS + ("unclassified",):
        raise PolicyError("invalid_arguments")
    selected = [r for r in snapshot["rules"] if (rule_id is None or r["id"] == rule_id) and (domain is None or any(d["name"] == domain for d in r["domains"]))]
    rows = [{**copy.deepcopy(r), "evaluationEligible": _view(r, policy_view, ruleset_authority)} for r in sorted(selected, key=lambda r: r["id"])]
    rows = rows[offset:offset + limit]; ids = {i for r in rows for i in r["sourceAssertionIds"]}
    return _safe({**_summary(snapshot, policy_view, ruleset_authority), "rules": rows, "total": len(selected),
                  "evidence": [copy.deepcopy(e) for e in snapshot["evidence"] if e["id"] in ids],
                  "nextOffset": offset + limit if offset + limit < len(selected) else None})


def _expression(expr, context, trace, budget):
    budget[0] += 1
    if budget[0] > MAX_IR_NODES:
        raise _Unsupported("evaluation_budget")
    op = expr["op"]
    if op == "literal": return _value(expr)
    if op == "input": return context[expr["name"]]
    if op == "not": return not _expression(expr["arg"], context, trace, budget)
    if op == "neg": return -_expression(expr["arg"], context, trace, budget)
    if op == "pos": return +_expression(expr["arg"], context, trace, budget)
    if op == "and": return all(_expression(e, context, trace, budget) for e in expr["args"])
    if op == "or": return any(_expression(e, context, trace, budget) for e in expr["args"])
    if op == "select":
        return _expression(expr["then"] if _expression(expr["condition"], context, trace, budget) else expr["else"], context, trace, budget)
    if op == "quantize":
        return _expression(expr["value"], context, trace, budget).quantize(_expression(expr["quantum"], context, trace, budget), rounding=expr["rounding"])
    left, right = _expression(expr["left"], context, trace, budget), _expression(expr["right"], context, trace, budget)
    if op == "add": value = left + right
    elif op == "sub": value = left - right
    elif op == "mul": value = left * right
    elif op == "div": value = left / right
    elif op == "floordiv": value = left // right
    elif op == "mod": value = left % right
    elif op == "compare":
        relation = expr["operator"]
        return {"eq": lambda: left == right, "ne": lambda: left != right, "lt": lambda: left < right,
                "le": lambda: left <= right, "gt": lambda: left > right, "ge": lambda: left >= right}[relation]()
    else: raise PolicyError("invalid_ir")
    # Reject expansive intermediates even if a later operation would shrink them.
    _typed(value, expr["type"])
    return value


def _run(rule, context):
    if not isinstance(context, dict) or len(context) > 16 or len(_canonical(context)) > 16 * 1024:
        raise PolicyError("invalid_arguments")
    _safe(context)
    names = {p["name"] for p in rule["parameters"]}
    if set(context) - names:
        raise PolicyError("invalid_arguments")
    converted = {}; missing = []
    for parameter in rule["parameters"]:
        name, kind = parameter["name"], parameter["type"]
        if name not in context:
            if "default" not in parameter:
                missing.append(name); continue
            converted[name] = _value(parameter["default"]); continue
        else: raw = context[name]
        if (kind == "bool" and type(raw) is not bool) or (kind == "int" and type(raw) is not int) or (kind == "decimal" and type(raw) not in {str, int}):
            raise PolicyError("invalid_arguments")
        try: converted[name] = _value(_literal(kind, raw))
        except PolicyError: raise PolicyError("invalid_arguments") from None
    if missing:
        return {"status": "needs_context", "missingInputs": missing, "value": None, "trace": []}
    trace = []; budget = [0]; node = rule["program"]
    try:
        with localcontext() as decimal_context:
            decimal_context.prec = 28; decimal_context.rounding = "ROUND_HALF_EVEN"
            while node["op"] == "if":
                verdict = _expression(node["condition"], converted, trace, budget)
                trace.append({"condition": copy.deepcopy(node["condition"]), "matched": verdict})
                node = node["then"] if verdict else node["else"]
            value = _typed(_expression(node["value"], converted, trace, budget), rule["returnType"])
        return {"status": "evaluated", "missingInputs": [], "value": value, "trace": trace}
    except (DecimalException, ZeroDivisionError, OverflowError, _Unsupported, PolicyError):
        return {"status": "unknown_evaluation", "missingInputs": [], "value": None, "trace": trace,
                "limitations": ["numeric_or_evaluation_budget"]}


def _evaluation_setup(snapshot, rule_id, policy_view, authority, config_profile, as_of):
    _view({}, policy_view, authority)
    matches = [r for r in snapshot["rules"] if r["id"] == rule_id]
    if not matches: raise PolicyError("rule_not_found")
    rule = matches[0]
    if not _view(rule, policy_view, authority):
        return rule, "ineligible_policy_view"
    if config_profile != rule.get("configProfile"):
        return rule, "unknown_profile"
    if rule.get("conflicts"):
        return rule, "unknown_conflict"
    if as_of is not None:
        try: dt.date.fromisoformat(as_of)
        except (ValueError, TypeError): raise PolicyError("invalid_arguments") from None
    validity = rule.get("validity", {})
    for key in ("from", "to"):
        if validity.get(key) is not None:
            try: dt.date.fromisoformat(validity[key])
            except (ValueError, TypeError): raise PolicyError("invalid_snapshot") from None
    if validity.get("from") or validity.get("to"):
        if not as_of: return rule, "needs_context"
        if (validity.get("from") and as_of < validity["from"]) or (validity.get("to") and as_of >= validity["to"]):
            return rule, "outside_validity"
    return rule, None


def explain_policy_result(snapshot, rule_id, context, *, policy_view="verified_implemented", ruleset_authority=None,
                          config_profile="source-default", as_of=None, catalog_snapshot_id=None, policy_snapshot_id=None, ruleset_digest=None):
    snapshot = _snapshot(snapshot, catalog_snapshot_id, policy_snapshot_id, ruleset_digest)
    rule, blocked = _evaluation_setup(snapshot, rule_id, policy_view, ruleset_authority, config_profile, as_of)
    result = {"status": blocked, "value": None, "missingInputs": ["as_of"] if blocked == "needs_context" else [], "trace": []} if blocked else _run(rule, context)
    return _safe({**_summary(snapshot, policy_view, ruleset_authority), **result, "ruleId": rule["id"], "asOf": as_of,
        "configProfile": config_profile, "evidenceIds": rule["sourceAssertionIds"], "assumptions": ["source_function_semantics", "decimal_precision_28_half_even"],
        "scope": "selected_source_function", "businessPolicyApproved": policy_view == "approved_business",
        "combinations": rule["combinations"], "optimality": {"optimum": False, "scope": "not_compared"}})


def compare_policy_cases(snapshot, rule_id, cases, objective="maximize_value", *, max_cases=100, policy_view="verified_implemented",
                         ruleset_authority=None, config_profile="source-default", as_of=None,
                         catalog_snapshot_id=None, policy_snapshot_id=None, ruleset_digest=None):
    """Cases are context dictionaries. Completeness is inferred, never asserted.

    Only exhaustive booleans compiled from the selected function signature can
    establish a declared finite-domain optimum. Numeric samples never can.
    """
    snapshot = _snapshot(snapshot, catalog_snapshot_id, policy_snapshot_id, ruleset_digest)
    if objective not in {"maximize_value", "minimize_value"} or type(max_cases) is not int or not 1 <= max_cases <= MAX_CASES or not isinstance(cases, list) or not cases:
        raise PolicyError("invalid_arguments")
    if len(cases) > max_cases: raise PolicyError("case_budget_exceeded")
    rule, blocked = _evaluation_setup(snapshot, rule_id, policy_view, ruleset_authority, config_profile, as_of)
    summary = {**_summary(snapshot, policy_view, ruleset_authority), "ruleId": rule_id, "objective": objective,
        "asOf": as_of, "configProfile": config_profile, "evidenceIds": rule["sourceAssertionIds"], "cases": [], "maximum": None,
        "optimality": {"optimum": False, "scope": "not_evaluated"}, "businessPolicyApproved": policy_view == "approved_business"}
    if blocked: return _safe({**summary, "status": blocked})
    evaluated = []
    for index, context in enumerate(cases):
        result = _run(rule, context)
        evaluated.append({"caseIndex": index, **{k: v for k, v in result.items() if k != "trace"}})
    summary["cases"] = evaluated
    successful = [r for r in evaluated if r["status"] == "evaluated"]
    if successful:
        chooser = max if objective == "maximize_value" else min
        best = chooser(successful, key=lambda r: _value({"op": "literal", **r["value"]}))
        summary["maximum"] = {"caseIndex": best["caseIndex"], "value": best["value"]}
    complete_cases = len(successful) == len(cases)
    finite = all(p["type"] == "bool" for p in rule["parameters"])
    exhaustive = False
    if finite and 2 ** len(rule["parameters"]) <= max_cases:
        names = [p["name"] for p in rule["parameters"]]
        supplied = {tuple(case.get(name, next((p.get("default", {}).get("value") for p in rule["parameters"] if p["name"] == name), None)) for name in names) for case in cases}
        exhaustive = supplied == set(itertools.product((False, True), repeat=len(names)))
    coverage = snapshot["coverage"]
    closed = coverage.get("complete") is True and coverage.get("unknownDenominator") is False and coverage.get("unsupportedRules", 0) == 0
    pinned = catalog_snapshot_id == snapshot["catalogSnapshotId"] and policy_snapshot_id == snapshot["policySnapshotId"] and ruleset_digest == snapshot["rulesetDigest"]
    optimum = complete_cases and finite and exhaustive and closed and pinned
    summary["optimality"] = {"optimum": optimum, "scope": "declared_function_boolean_inputs" if optimum else "provided_cases",
        "exhaustive": exhaustive, "finiteDeclaredInputs": finite, "snapshotPinsVerified": pinned,
        "organizationWide": False, "stackingSearched": False}
    summary["status"] = "proven_maximum" if optimum and objective == "maximize_value" else "proven_minimum" if optimum else ("maximum_over_provided_cases" if objective == "maximize_value" else "minimum_over_provided_cases") if complete_cases else "needs_context" if any(r["status"] == "needs_context" for r in evaluated) else "best_found"
    summary["best"] = copy.deepcopy(summary["maximum"])
    if objective == "minimize_value":
        summary["minimum"] = summary["maximum"]; summary["maximum"] = None
    if not closed and complete_cases: summary["status"] = "incomplete_coverage"
    return _safe(summary)


def quarantine_ai_proposal(proposal, snapshot, *, model_identity=None, run_id="local-run"):
    """Quarantine only. Identity/approval cannot replace semantic validation."""
    snapshot = _snapshot(snapshot)
    if not isinstance(proposal, dict) or not isinstance(run_id, str) or not _OPAQUE.fullmatch(run_id):
        raise PolicyError("invalid_proposal")
    if len(_canonical(proposal)) > 64 * 1024:
        raise PolicyError("invalid_proposal")
    try: _safe(proposal)
    except PolicyError: return {"status": "quarantined", "reasons": ["privacy_denied"], "evaluationEligible": False}
    allowed = {"ruleId", "sourceAssertionIds", "program", "returnType"}
    reasons = []
    if set(proposal) != allowed: reasons.append("proposal_schema")
    rule = next((r for r in snapshot["rules"] if r["id"] == proposal.get("ruleId")), None)
    if rule is None: reasons.append("unknown_rule")
    else:
        if proposal.get("sourceAssertionIds") != rule["sourceAssertionIds"]: reasons.append("evidence_mismatch")
        if proposal.get("program") != rule["program"] or proposal.get("returnType") != rule["returnType"]: reasons.append("source_support_unverified")
    verified_identity = isinstance(model_identity, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", model_identity))
    return {"status": "quarantined", "proposalStatus": "AI-proposed", "evaluationEligible": False,
        "reasons": sorted(set(reasons or ["independent_semantic_review_required"])),
        "modelIdentity": model_identity if verified_identity else "unverified", "repeatability": "unverified",
        "cacheScope": "immutable_model_spec" if verified_identity else "run:" + run_id, "automaticCrossRunReuse": False,
        "proposalDigest": "sha256:" + hashlib.sha256(_canonical(proposal)).hexdigest()}
