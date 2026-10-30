"""Bounded Java SE 21 member inventories for static name-resolution checks.

This is an explicit language-model assumption, not discovery of the target JDK.
Only fields, member types and direct parents are inventoried; methods, execution
and runtime class loading are outside this contract. No document prose is copied.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache

VERSION = "java-se21-member-inventory-1"
MODEL = {"effectivePlatform": "Java SE 21", "actualTargetJdk": "UNKNOWN",
         "basis": "bounded_documented_platform_assumption", "catalogVersion": VERSION}
DOC = "https://docs.oracle.com/en/java/javase/21/docs/api/java.base/"
# Explicit FQNs only. A selected source declaration always prevents this trust.
_DECLARATIONS = {
    "java.lang.Object": ("class", (), (), ()),
    "java.lang.AutoCloseable": ("interface", (), (), ()),
    "java.lang.Runnable": ("interface", (), (), ()),
    "java.lang.Comparable": ("interface", (), (), ()),
    "java.io.Closeable": ("interface", ("java.lang.AutoCloseable",), (), ()),
    "java.util.Map": ("interface", (), (), ("Entry",)),
}
MAX_SCOPES = 16
MAX_CHECKS = 64
MAX_CATALOG_BYTES = 64 * 1024
MAX_SOURCE_MEMBERS = 1024
# Reserved Java tokens cannot establish declaration identifiers. Restricted
# type/contextual identifiers are also withheld by this bounded grammar.
JAVA_RESERVED = frozenset("""abstract assert boolean break byte case catch char class const continue default
    do double else enum extends final finally float for goto if implements import instanceof int interface
    long native new package private protected public return short static strictfp super switch synchronized
    this throw throws transient try void volatile while true false null _ var yield record sealed permits""".split())


def declaration_identifier(value):
    return bool(re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value)) and value not in JAVA_RESERVED



def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def contract(name):
    item = _DECLARATIONS.get(name)
    if item is None:
        return None
    kind, parents, fields, members = item
    entry = {"catalogVersion": VERSION, "module": "java.base", "qualifiedName": name,
             "kind": kind, "directParents": list(parents), "fields": list(fields),
             "memberTypes": list(members), "inventoryComplete": {"directParents": True, "fields": True, "memberTypes": True},
             "scope": "documented_public_and_protected_inheritable_names", **MODEL,
             "specification": DOC + name.replace(".", "/") + ".html",
             "inheritanceSpecification": "https://docs.oracle.com/javase/specs/jls/se21/html/jls-9.html#jls-9.2" if kind == "interface" else "https://docs.oracle.com/javase/specs/jls/se21/html/jls-8.html#jls-8.2"}
    return {"id": "jdk21-members:" + hashlib.sha256(canonical(entry)).hexdigest()[:24], **entry}


def source_type_matches(raw, name, owner):
    """Existing bounded spelling/import rules, using the actual emitted owner.

    This checks a declaration spelling against a supplied static type; it does
    not evaluate an initializer, solve generic types or inspect runtime values.
    """
    if not isinstance(raw,str) or len(raw)>1024 or not isinstance(owner,dict):return False
    depth=0; result=[]
    for char in raw:
        if char=='<':depth+=1
        elif char=='>':
            depth-=1
            if depth<0:return False
        elif not depth:result.append(char)
        if depth>32:return False
    if depth:return False
    spelling=re.sub(r"\s+","",''.join(result)).replace('...','[]')
    if not spelling or not isinstance(name,str):return False
    normalized=lambda value:re.sub(r"^java\.lang\.(boolean|byte|char|short|int|long|float|double)(?=(?:\[\])*$)",r"\1",value)
    if normalized(spelling)==normalized(name):return True
    h=spelling.split('.',1)[0].split('[',1)[0]
    imports=owner.get('typeImports',[])
    if (not isinstance(imports,list) or any(not isinstance(item,dict) or not isinstance(item.get('qualifiedName'),str) for item in imports)
            or not isinstance(owner.get('typeImportCoverage'),dict) or not isinstance(owner.get('sourcePackage',''),str)):return False
    if not owner.get('typeImportCoverage',{}).get('complete'):return False
    explicit={i['qualifiedName'] for i in imports if i.get('kind')=='type' and not i['qualifiedName'].endswith('.*') and i['qualifiedName'].rsplit('.',1)[-1]==h}
    if len(explicit)==1:
        return next(iter(explicit))+spelling[len(h):]==name
    if explicit:return False
    if name == (owner.get('sourcePackage','') + '.' + spelling).strip('.'):
        return True
    on_demand={i['qualifiedName'][:-2] for i in imports if i.get('kind')=='type' and i['qualifiedName'].endswith('.*')}
    if name in {'java.time.Instant','java.time.Duration','java.time.temporal.Temporal'}:
        package=name.rsplit('.',1)[0]
        if package in on_demand and not on_demand-{package,'java.lang'} and name==package+'.'+spelling:return True
    return name=='java.lang.'+spelling and h in {'Object','String','Boolean','Byte','Short','Integer','Long','Float','Double','Character','Math','System','Throwable','Exception','RuntimeException','AutoCloseable','Runnable','Comparable'}


class Inheritance:
    """Source-scoped absence queries; unknown edges never establish absence."""
    def __init__(self, index, symbol, record_header=None):
        self.index, self.symbol = index, symbol
        self.record_header = record_header
        self.stack = []

    def capture(self, action):
        self.stack.append({})
        try:
            value = action()
            checks = list(self.stack[-1].values())
        finally:
            self.stack.pop()
        if self.stack:
            self.stack[-1].update((c["id"], c) for c in checks)
        return value, checks

    def cached(self, function):
        # Cache the proof as well as the value; replay it into each caller's
        # bounded projection. Inactive legacy checks never share an active key.
        @lru_cache(maxsize=20_000)
        def compute(active, *args):
            return self.capture(lambda: function(*args)) if active else (function(*args), [])
        def wrapped(*args):
            value, checks = compute(bool(self.stack), *args)
            if self.stack:
                self.stack[-1].update((c["id"], c) for c in checks)
            return value
        return wrapped

    @lru_cache(maxsize=20_000)
    def imports(self, path):
        names = {}
        ident = r"[A-Za-z_$][A-Za-z0-9_$]*"
        for m in re.finditer(r"\bimport\s+(?!static\b)(" + ident + r"(?:\s*\.\s*" + ident + r")+)\s*;", self.index.files[path]["code"]):
            name = re.sub(r"\s*\.\s*", ".", m[1])
            names.setdefault(name.rsplit(".", 1)[-1], set()).add(name)
        return names

    def parent(self, raw, scope):
        index = self.index; file = index.files[scope["path"]]
        clean = index.core._clean_java_type(re.sub(r"\s*\.\s*", ".", raw))
        head = clean.split(".", 1)[0]
        if head in index._type_variables(scope["qualified_name"]):
            return None, "parent_type_variable"
        explicit = self.imports(scope["path"]).get(head, set())
        if len(explicit) > 1:
            return None, "parent_import_ambiguous"
        ref = index.type_reference(file, raw, scope["qualified_name"], context="platform_parent")
        candidate = ref.get("resolvedType") if ref.get("resolution") == "resolved" else None
        if candidate not in _DECLARATIONS and candidate not in index.types:
            return None, "parent_declaration_unavailable"
        if candidate in _DECLARATIONS:
            if candidate in index.types or any(candidate.startswith(q + ".") for q in index.types):
                return None, "selected_platform_identity_conflict"
            current = scope["qualified_name"]
            while current:
                if current + "." + head in index.types or current.rsplit(".", 1)[-1] == head:
                    return None, "parent_lexical_type_shadow"
                current = current.rsplit(".", 1)[0] if "." in current else ""
            if (file["package"] + "." + head).strip(".") in index.types:
                return None, "parent_same_package_type_shadow"
        # A single static import may name a member type. A conflicting
        # unselected declaration cannot be dismissed as a field or method.
        if explicit and any(not imported.endswith(".*")
                            and imported.rsplit(".", 1)[-1] == head and imported != candidate
                            for imported in file["staticImports"]):
            return None, "parent_static_import_unverified"
        # A fully qualified declaration and a single explicit type import do
        # not depend on unrelated on-demand import inventories. For a simple
        # name, selected lexical/same-package declarations also have precedence.
        anchored = ("." in clean or bool(explicit) or
                    ref.get("reason") in {"selected_declaration", "same_package_declaration",
                                           "enclosing_member_type", "enclosing_type"})
        if not anchored:
            for imported in file["staticImports"]:
                if not imported.endswith(".*"):
                    if imported.rsplit(".", 1)[-1] == head:
                        # Only the exact selected static member type can anchor
                        # this binding; an external declaration remains unknown.
                        if imported != candidate or imported not in index.types:
                            return None, "parent_static_import_unverified"
                    continue
                # A selected imported owner's absence inventory would need
                # its own source-proof edge. Until that independent proof is
                # projected, even a known owner remains UNKNOWN.
                return None, "parent_static_import_unverified"
            if file["wildcards"] - {"java.lang", candidate.rsplit(".", 1)[0]}:
                return None, "parent_on_demand_import_unverified"
        if explicit and next(iter(explicit)) + clean[len(head):] != candidate:
            return None, "parent_import_identity_mismatch"
        return candidate, None

    @staticmethod
    def type_tokens(raw):
        tokens = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|\.\.\.|[.<>?,\[\]&()]|\s+", raw)
        return [token for token in tokens if not token.isspace()] if "".join(tokens) == raw else None

    @staticmethod
    def type_end(tokens, cursor=0, depth=0, *, reference=False, wildcard=False, creation=False):
        """Consume one bounded Java type; primitive arrays are reference types.

        Creation types additionally admit a final diamond, but never a direct
        wildcard argument. Nested reference arguments may contain wildcards.
        This is syntax evidence only, without class or constructor resolution.
        """
        if depth > 32 or cursor >= len(tokens): return None
        if tokens[cursor] == "?":
            if not wildcard: return None
            cursor += 1
            return Inheritance.type_end(tokens, cursor + 1, depth + 1, reference=True) if cursor < len(tokens) and tokens[cursor] in {"extends", "super"} else cursor
        primitives = {"boolean", "byte", "char", "short", "int", "long", "float", "double"}
        primitive = tokens[cursor] in primitives
        if not declaration_identifier(tokens[cursor]) and not primitive: return None
        cursor += 1; parameterized = False
        while True:
            if cursor < len(tokens) and tokens[cursor] == "<":
                if primitive: return None
                cursor += 1; parameterized = True
                if cursor < len(tokens) and tokens[cursor] == ">":
                    if not creation: return None
                else:
                    cursor = Inheritance.type_end(tokens, cursor, depth + 1, reference=True, wildcard=not creation)
                    while cursor is not None and cursor < len(tokens) and tokens[cursor] == ",":
                        cursor = Inheritance.type_end(tokens, cursor + 1, depth + 1, reference=True, wildcard=not creation)
                if cursor is None or cursor >= len(tokens) or tokens[cursor] != ">": return None
                cursor += 1
            if cursor < len(tokens) and tokens[cursor] == ".":
                if primitive or creation and parameterized or cursor + 1 >= len(tokens) or not declaration_identifier(tokens[cursor + 1]): return None
                cursor += 2
            else: break
        arrays = 0
        while cursor + 1 < len(tokens) and tokens[cursor:cursor + 2] == ["[", "]"]:
            arrays += 1; cursor += 2
        if creation and (primitive or arrays) or reference and primitive and not arrays: return None
        return cursor

    @staticmethod
    def field_type_syntax(raw):
        tokens = Inheritance.type_tokens(raw)
        return bool(tokens) and Inheritance.type_end(tokens) == len(tokens)

    @staticmethod
    def constructor_header_parts(raw, scope):
        """Parse one bounded header, without body or constructor resolution.

        Annotations and receiver parameters remain unsupported. Parameter types
        retain their source spelling; they are never interpreted as values.
        """
        tokens = Inheritance.type_tokens(raw)
        if not tokens: return None
        cursor = 0; modifiers = []
        while cursor < len(tokens) and tokens[cursor] in {"public", "protected", "private"}:
            modifiers.append(tokens[cursor]); cursor += 1
        if len(modifiers) > 1 or scope["kind"] == "enum" and any(m != "private" for m in modifiers): return None
        if scope["kind"] not in {"class", "enum", "record"}: return None
        generic = cursor < len(tokens) and tokens[cursor] == "<"
        if generic:
            cursor += 1; parameters = set()
            while True:
                if cursor >= len(tokens) or not declaration_identifier(tokens[cursor]) or tokens[cursor] in parameters: return None
                parameters.add(tokens[cursor]); cursor += 1
                if cursor < len(tokens) and tokens[cursor] == "extends":
                    cursor += 1
                    while True:
                        cursor = Inheritance.type_end(tokens, cursor, reference=True)
                        if cursor is None or tokens[cursor - 1] == "]": return None
                        if cursor >= len(tokens) or tokens[cursor] != "&": break
                        cursor += 1
                if cursor >= len(tokens): return None
                if tokens[cursor] != ",": break
                cursor += 1
            if tokens[cursor] != ">": return None
            cursor += 1
        if cursor >= len(tokens) or tokens[cursor] != scope["name"]: return None
        cursor += 1
        result = {"access": modifiers[0] if modifiers else "package", "generic": generic,
                  "compact": cursor == len(tokens), "parameters": [], "throws": False}
        if result["compact"]:
            return result if scope["kind"] == "record" and not generic else None
        if cursor >= len(tokens) or tokens[cursor] != "(": return None
        cursor += 1; names = set(); varargs = False
        if cursor < len(tokens) and tokens[cursor] != ")":
            while True:
                if cursor < len(tokens) and tokens[cursor] == "final": cursor += 1
                type_start = cursor
                cursor = Inheritance.type_end(tokens, cursor)
                if cursor is None: return None
                declared_type = tokens[type_start:cursor]
                if cursor < len(tokens) and tokens[cursor] == "...": varargs = True; cursor += 1
                if cursor >= len(tokens) or not declaration_identifier(tokens[cursor]) or tokens[cursor] in names: return None
                name = tokens[cursor]; names.add(name); cursor += 1
                if not varargs:
                    while cursor + 1 < len(tokens) and tokens[cursor:cursor + 2] == ["[", "]"]:
                        declared_type += ["[", "]"]; cursor += 2
                result["parameters"].append({"name": name, "type": declared_type,
                                             "varargs": varargs})
                if cursor >= len(tokens): return None
                if tokens[cursor] != ",": break
                if varargs: return None
                cursor += 1
        if cursor >= len(tokens) or tokens[cursor] != ")": return None
        cursor += 1
        if cursor < len(tokens) and tokens[cursor] == "throws":
            result["throws"] = True; cursor += 1
            while True:
                start = cursor
                cursor = Inheritance.type_end(tokens, cursor, reference=True)
                if cursor is None or any(t in {"<", "["} for t in tokens[start:cursor]): return None
                if cursor >= len(tokens) or tokens[cursor] != ",": break
                cursor += 1
        return result if cursor == len(tokens) else None

    @staticmethod
    def constructor_header_supported(raw, scope, record_access="package", record_components=None):
        """Boolean names-only contract, including bounded normal record headers.

        No constructor body, delegation, initialization, implicit parameter map
        or compilation is modeled. For records, only exact canonical spelling
        or a different arity establishes a supported signature. Same-arity
        alternatives needing type/erasure equivalence remain UNKNOWN.
        """
        header = Inheritance.constructor_header_parts(raw, scope)
        if header is None: return False
        if scope["kind"] != "record": return True
        if header["generic"]: return False
        allowed = {"public": {"public"}, "protected": {"public", "protected"},
                   "package": {"public", "protected", "package"},
                   "private": {"public", "protected", "package", "private"}}
        canonical_access = header["access"] in allowed.get(record_access, set())
        if header["compact"]: return canonical_access
        if record_components is None: return False
        parameters = header["parameters"]
        if len(parameters) != len(record_components): return True
        for parameter, component in zip(parameters, record_components):
            component_type = Inheritance.type_tokens(component.get("rawType") or "")
            variable = bool(component_type and component_type[-1] == "...")
            if variable: component_type = component_type[:-1]
            if (parameter["name"] != component.get("name") or parameter["type"] != component_type
                    or parameter["varargs"] != variable): return False
        return canonical_access and not header["throws"]

    def initializer_tokens(self, original, semantics):
        """Validate and collapse creation types for the shared expression IR.

        The collapsed token is local to this names-only check. Neither the IR
        emitted by policy_semantics nor its source/type/value evidence changes.
        """
        tokens = semantics._tokens(original); result = []; cursor = 0
        values = []; positions = []; offsets = []
        for position, token in enumerate(tokens):
            offsets.append(len(values))
            pieces = list(token.value) if token.value in {">>", ">>>"} else [token.value]
            values.extend(pieces); positions.extend([position] * len(pieces))
        while cursor < len(tokens):
            token = tokens[cursor]; result.append(token); cursor += 1
            if token.value != "new": continue
            start = offsets[cursor] if cursor < len(tokens) else len(values)
            end = self.type_end(values, start, creation=True)
            if end is not None and end < len(values) and values[end] == "(":
                # A close-angle token may never be partially consumed.
                if end and positions[end - 1] == positions[end]: raise semantics._Unsupported("creation_type_unsupported")
                after = positions[end]
                result.append(semantics._Token("InventoryCreationType", tokens[cursor].start, tokens[after - 1].end, "name"))
                cursor = after
            else:
                # Existing array grammar is retained, including its separate
                # generic-array, dimension and initializer restrictions.
                end = self.type_end(values, start)
                if end is None or end >= len(values) or values[end] not in {"[", "{"}: raise semantics._Unsupported("creation_type_unsupported")
        return result

    @staticmethod
    def quoted_literal_supported(literal):
        if len(literal) < 2 or literal[0] not in {"'", '"'} or literal[-1] != literal[0]: return False
        cursor = 1; units = 0
        while cursor < len(literal) - 1:
            char = literal[cursor]
            if char in {"\r", "\n", literal[0]}: return False
            if char == "\\":
                cursor += 1
                if cursor >= len(literal) - 1: return False
                if literal[cursor] in "btnfrs\"'\\": cursor += 1
                elif literal[cursor] in "01234567":
                    maximum = 3 if literal[cursor] in "0123" else 2
                    count = 0
                    while cursor < len(literal) - 1 and count < maximum and literal[cursor] in "01234567":
                        cursor += 1; count += 1
                else: return False
                units += 1
            else:
                units += 2 if ord(char) > 0xffff else 1
                cursor += 1
        return literal[0] != "'" or units == 1

    def lambda_initializer_supported(self, tokens, original, semantics):
        """Only bounded untyped lambda boundaries; no body/type/value proof.

        Parameters must be unique identifiers. A block is empty or a sequence
        of supported return/throw/expression statements, fully consumed through
        its final brace. Typed/annotated parameters, local declarations, nested
        lambdas and unknown bodies remain unsupported for member absence.
        """
        values = [token.value for token in tokens]
        if not values or len(values) > semantics.MAX_EXPRESSION_TOKENS:
            return False
        if values[0] == "(":
            closing = next((i for i, value in enumerate(values) if value == ")"), None)
            if closing is None or closing + 1 >= len(values) or values[closing + 1] != "->":
                return False
            parameter_tokens = values[1:closing]
            if parameter_tokens:
                if len(parameter_tokens) % 2 != 1 or any(value != "," for value in parameter_tokens[1::2]):
                    return False
                parameters = parameter_tokens[::2]
            else:
                parameters = []
            start = closing + 2
        elif len(values) >= 3 and values[1] == "->":
            parameters, start = [values[0]], 2
        else:
            return False
        if (len(parameters) > MAX_CHECKS or len(set(parameters)) != len(parameters)
                or any(not declaration_identifier(name) for name in parameters) or start >= len(tokens)):
            return False
        body = tokens[start:]
        if any(token.value == "->" for token in body):
            return False

        def expression(selected, statement=False):
            if not selected:
                return False
            source = original[selected[0].start:selected[-1].end]
            if not self.initializer_supported(source):
                return False
            if statement:
                try:
                    node = semantics._Expression(selected, False, structural_only=True).parse()
                except semantics._Unsupported:
                    return False
                if node.get("op") not in {"call", "construct", "update"}:
                    return False
            return True

        if body[0].value != "{":
            return expression(body)
        if body[-1].value != "}":
            return False
        pairs, stack, first, statements = {"(": ")", "[": "]", "{": "}"}, [], 1, 0
        for position in range(1, len(body) - 1):
            value = body[position].value
            if value in pairs:
                stack.append(pairs[value])
                if len(stack) > 32:
                    return False
            elif value in {")", "]", "}"}:
                if not stack or stack.pop() != value:
                    return False
            elif value == ";" and not stack:
                selected = body[first:position]
                if not selected:
                    return False
                if selected[0].value == "return":
                    if len(selected) > 1 and not expression(selected[1:]):
                        return False
                elif selected[0].value == "throw":
                    if not expression(selected[1:]):
                        return False
                elif not expression(selected, statement=True):
                    return False
                statements += 1
                if statements > MAX_CHECKS:
                    return False
                first = position + 1
        return not stack and first == len(body) - 1

    def initializer_supported(self, original, *, arguments=False):
        """Shared bounded expression grammar, with syntax-only node checks.

        Balanced delimiters alone never prove an initializer. A complete bounded
        untyped lambda may establish a field boundary only; unknown blocks,
        method references and anonymous member bodies remain UNKNOWN.
        No parsed expression/value is retained in the member inventory.
        """
        semantics = self.index.core._load_bundled_helper("policy_semantics")
        try:
            tokens = self.initializer_tokens(original, semantics)
            values = [token.value for token in tokens]
            # Generic method arguments and adjacent parenthesized invocations
            # lose grammar distinctions in the shared IR; do not infer them.
            if any(values[i:i + 2] in ([".", "<"], [")", "("]) for i in range(len(values) - 1)): return False
            if values[:1] == ["new"] and "[" in values:
                first = next((i for i, value in enumerate(values) if value in {"(", "["}), len(values))
                if first < len(values) and values[first] == "[" and "<" in values[:first]: return False
            for token in tokens:
                if token.kind == "number" and "_" in token.value: return False
                if token.kind in {"redacted_literal", "decimal_string"}:
                    literal = original[token.start:token.end]
                    if literal.startswith('"""') or not self.quoted_literal_supported(literal): return False
            if any(token.value == "->" for token in tokens):
                return not arguments and self.lambda_initializer_supported(tokens, original, semantics)
            empty_anonymous = (not arguments and len(tokens) >= 4 and tokens[0].value == "new"
                               and [token.value for token in tokens[-2:]] == ["{", "}"])
            if empty_anonymous: tokens = tokens[:-2]
            parser = semantics._Expression(tokens, False, structural_only=True)
            nodes = parser.arguments(0) if arguments else [parser.parse()]
            if parser.index != len(tokens): return False
            if empty_anonymous and nodes[0].get("op") != "construct": return False
        except semantics._Unsupported:
            return False

        def reference(name):
            parts = name.split(".")
            return bool(parts) and all(declaration_identifier(part) or position == 0 and part in {"this", "super"}
                                       for position, part in enumerate(parts)) and name != "super"

        def valid(node, depth=0):
            if not isinstance(node, dict) or depth > 32: return False
            operation = node.get("op")
            if node.get("typeArguments") and operation != "construct": return False
            if operation in {"literal", "redacted"}: return True
            if operation == "reference": return reference(node.get("name", ""))
            if operation == "member": return declaration_identifier(node.get("name", "")) and valid(node.get("receiver"), depth + 1)
            if operation == "call":
                callee = node.get("callee", {})
                return (callee.get("op") in {"reference", "member"} and callee.get("name") not in {"this", "super"}
                        and valid(callee, depth + 1) and all(valid(arg, depth + 1) for arg in node.get("arguments", [])))
            if operation == "construct":
                raw = node.get("type", "")
                args = node.get("typeArguments", [])
                if "?" in args: return False
                if args: raw += "<" + " ".join(args) + ">"
                return (self.field_type_syntax(raw) and raw not in {"boolean", "byte", "char", "short", "int", "long", "float", "double"}
                        and all(valid(arg, depth + 1) for arg in node.get("arguments", [])))
            if operation == "array_construct":
                dims = node.get("dimensions", [])
                initializer = node.get("initializer")
                if not dims or node.get("typeArguments") or not self.field_type_syntax(node.get("elementType", "")): return False
                if initializer is not None:
                    return all(dim is None for dim in dims) and valid(initializer, depth + 1)
                if dims[0] is None: return False
                unbounded = False
                for dim in dims:
                    if dim is None: unbounded = True
                    elif unbounded or not valid(dim, depth + 1): return False
                return True
            if operation == "array_initializer": return all(valid(item, depth + 1) for item in node.get("elements", []))
            if operation == "index": return valid(node.get("receiver"), depth + 1) and valid(node.get("index"), depth + 1)
            if operation == "cast": return self.field_type_syntax(node.get("type", "")) and valid(node.get("operand"), depth + 1)
            if operation in {"unary", "update"}:
                operand = node.get("operand", {})
                if node.get("operator") in {"++", "--"} and operand.get("op") not in {"reference", "member", "index"}: return False
                return valid(operand, depth + 1)
            if operation == "binary":
                if node.get("operator") == "instanceof": return False
                return valid(node.get("left"), depth + 1) and valid(node.get("right"), depth + 1)
            if operation == "conditional": return all(valid(node.get(key), depth + 1) for key in ("condition", "then", "else"))
            return False
        return all(valid(node) for node in nodes)

    def field_names(self, statement, original):
        """Names from one bounded direct field statement; values stay masked.

        The common declared type is consumed before splitting declarators, so
        generic argument commas are not mistaken for new fields. Initializers
        are skipped only as balanced syntax, never evaluated or used as types.
        Unsupported annotations/type syntax fail closed.
        """
        ident = r"[A-Za-z_$][A-Za-z0-9_$]*"
        type_part = ident + r"(?:\s*\.\s*" + ident + r")*(?:\s*<[^;{}=()]*>)?(?:\s*\[\s*\])*"
        match = re.match(r"(?P<mods>(?:(?:public|protected|private|static|final|volatile|transient)\s+)*)(?P<type>" + type_part + r")\s+", statement)
        if not match or match["type"] in {"void", "var", "return", "throw", "new", "package", "import"}:
            return None
        modifiers = match["mods"].split()
        if (len(modifiers) != len(set(modifiers)) or len(set(modifiers) & {"public", "protected", "private"}) > 1
                or {"final", "volatile"} <= set(modifiers) or not self.field_type_syntax(match["type"])): return None
        cursor = match.end(); names = []
        pairs = {"(": ")", "[": "]", "{": "}"}
        while cursor < len(statement):
            name = re.match(ident, statement[cursor:])
            if not name: return None
            if not declaration_identifier(name[0]): return None
            names.append(name[0]); cursor += name.end()
            if len(names) > MAX_SOURCE_MEMBERS or len(set(names)) != len(names): return None
            while cursor < len(statement) and statement[cursor].isspace(): cursor += 1
            while cursor < len(statement) and statement[cursor] == "[":
                dimensions = re.match(r"\[\s*\]\s*", statement[cursor:])
                if not dimensions: return None
                cursor += dimensions.end()
            if cursor == len(statement): return names
            if statement[cursor] == "=":
                cursor += 1; stack = []; initializer_start = cursor
                semantics = self.index.core._load_bundled_helper("policy_semantics")
                try:
                    initializer_tokens = self.initializer_tokens(original[cursor:], semantics)
                except semantics._Unsupported:
                    return None
                creation_ends = {cursor + token.start: cursor + token.end for token in initializer_tokens
                                 if token.value == "InventoryCreationType"}
                while cursor < len(statement):
                    if cursor in creation_ends:
                        cursor = creation_ends[cursor]; continue
                    char = statement[cursor]
                    if char in pairs: stack.append(pairs[char])
                    elif char in ")]}":
                        if not stack or stack.pop() != char: return None
                    elif char == "," and not stack: break
                    if len(stack) > 32: return None
                    cursor += 1
                if stack or not self.initializer_supported(original[initializer_start:cursor]): return None
            if cursor == len(statement): return names
            if statement[cursor] != ",": return None
            cursor += 1
            while cursor < len(statement) and statement[cursor].isspace(): cursor += 1
            if cursor == len(statement): return None
        return None

    @lru_cache(maxsize=20_000)
    def source_inventory(self, owner):
        """Check the supported direct-member inventory before using absence.

        This does not extend JavaIndex or resolve any new CALLS. Every direct
        member must match an indexed method/type, a plain initializer, or one
        complete bounded field statement. Record component fields and enum
        constants are inventoried as names only, without runtime values.
        Initializers and bodies are skipped as balanced groups, never emitted.
        """
        scope = self.index.types[owner]
        file = self.index.files[scope["path"]]
        code = file["code"]
        fields, members, reasons = True, True, set()
        observed = 0; field_names = set(); constructor_regions = []; direct_type_ids = set()
        left, right = scope["body_start"] + 1, scope["body_end"]
        if file["issues"] or re.search(r"\\u+[0-9a-fA-F]{4}", file["original"]):
            return {"fields": "UNKNOWN", "memberTypes": "UNKNOWN", "observedDirectDeclarationRegions": 0,
                    "reasons": ["selected_source_lexical_inventory_unverified"]}
        methods = [m for m in file["methods"] if m["owner"] == owner]
        def declaration_start(method):
            start = method["match_start"]
            return start + len(code[start:method["match"].end()]) - len(code[start:method["match"].end()].lstrip())
        method_bodies = {m["body_start"] - 1: declaration_start(m) for m in methods if "body_start" in m}
        abstract_ends = {m["match"].end(): declaration_start(m) for m in methods if "body_start" not in m}
        nested_bodies = {t["body_start"] for t in file["scopes"]
                         if left <= t["start"] < right and t["qualified_name"].rsplit(".", 1)[0] == owner}
        pairs = {"(": ")", "[": "]", "{": "}"}

        def group(start):
            stack = []
            for position in range(start, right):
                char = code[position]
                if char in pairs:
                    stack.append(pairs[char])
                    if len(stack) > 32: return None
                elif char in ")]}":
                    if not stack or stack.pop() != char: return None
                    if not stack: return position + 1
            return None

        def space(position):
            while position < right and code[position].isspace(): position += 1
            return position

        record_access = "package"; record_header = None
        if scope["kind"] == "record":
            record_header = self.record_header(scope) if self.record_header else None
            record_modifiers = re.findall(r"\b(public|protected|private)\b", re.split(r"\brecord\b", code[scope["start"]:scope["body_start"]], maxsplit=1)[0])
            enclosing = self.index.types.get(owner.rsplit(".", 1)[0]) if "." in owner else None
            record_access = record_modifiers[0] if len(record_modifiers) == 1 else ("public" if enclosing and enclosing["kind"] == "interface" else "package")
        compact_constructors = 0; canonical_constructors = 0; constructor_signatures = set()
        start = cursor = space(left)
        # Enum constants precede the ordinary direct-member region. They may
        # have balanced arguments and anonymous bodies but declare field names,
        # not member types. Unsupported annotations remain UNKNOWN.
        if scope["kind"] == "enum":
            while cursor < right and code[cursor] != ";":
                constant = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", code[cursor:right])
                if not constant:
                    fields = members = False; reasons.add("selected_enum_constant_inventory_unverified"); break
                name = constant[0]
                if not declaration_identifier(name):
                    fields = members = False; reasons.add("selected_enum_constant_inventory_unverified"); break
                if name in field_names or len(field_names) >= MAX_SOURCE_MEMBERS:
                    fields = members = False; reasons.add("selected_enum_constant_inventory_unverified"); break
                field_names.add(name); cursor = space(cursor + constant.end())
                for opening in ("(", "{"):
                    if cursor < right and code[cursor] == opening:
                        after = group(cursor)
                        if after is None:
                            fields = members = False; reasons.add("selected_enum_constant_inventory_unverified"); break
                        if (opening == "(" and not self.initializer_supported(file["original"][cursor:after], arguments=True)
                                or opening == "{" and code[cursor + 1:after - 1].strip()):
                            fields = members = False; reasons.add("selected_enum_constant_inventory_unverified"); break
                        cursor = space(after)
                if not fields or not members: break
                if cursor >= right or code[cursor] == ";": break
                if code[cursor] != ",":
                    fields = members = False; reasons.add("selected_enum_constant_inventory_unverified"); break
                cursor = space(cursor + 1)
            if field_names: observed += 1
            if fields and members:
                start = cursor = space(cursor + 1) if cursor < right and code[cursor] == ";" else cursor
            else:
                start = cursor = right
        while cursor < right:
            char = code[cursor]
            if char in "([":
                after = group(cursor)
                if after is None:
                    fields = members = False; reasons.add("selected_source_member_boundary_unverified"); break
                cursor = after; continue
            if char == "{":
                after = group(cursor)
                if after is None:
                    fields = members = False; reasons.add("selected_source_member_boundary_unverified"); break
                prefix = code[start:cursor].strip()
                record_components = record_header.get("components", []) if record_header and not record_header.get("reasons") and record_header.get("detected") is not None else None
                constructor = self.constructor_header_supported(prefix, scope, record_access, record_components)
                header = self.constructor_header_parts(prefix, scope) if constructor else None
                if constructor:
                    kind = ("record_compact" if header["compact"] else "record_explicit") if scope["kind"] == "record" else "ordinary"
                    constructor_regions.append({"kind": kind,
                        "sourceRange": {"charStart": start, "charEnd": after},
                        "headerRange": {"charStart": start, "charEnd": cursor},
                        "bodyRange": {"charStart": cursor, "charEnd": after},
                        "status": "constructor_body_semantics_not_modeled"})
                if constructor and scope["kind"] == "record":
                    compact_constructors += bool(header["compact"])
                    canonical_constructors += bool(header["compact"] or len(header["parameters"]) == len(record_components))
                    # Equal-arity noncanonical alternatives are unsupported
                    # above, so an arity identifies the bounded signature here.
                    signature = "canonical" if header["compact"] or len(header["parameters"]) == len(record_components) else len(header["parameters"])
                    if compact_constructors > 1 or canonical_constructors > 1 or signature in constructor_signatures:
                        fields = members = False; reasons.add("selected_source_member_inventory_unverified")
                    constructor_signatures.add(signature)
                is_body = (method_bodies.get(cursor) == start or cursor in nested_bodies or prefix in {"", "static"} or constructor)
                if is_body:
                    if cursor in nested_bodies:
                        direct_type_ids.update(t["id"] for t in file["scopes"] if t["body_start"] == cursor)
                    observed += 1
                    start = cursor = space(after)
                elif "=" in prefix:
                    # Array/anonymous/lambda initializer: its trailing declaration
                    # still has to match a complete field statement at the semicolon.
                    cursor = after
                else:
                    fields = members = False; reasons.add("selected_source_member_inventory_unverified")
                    observed += 1
                    start = cursor = space(after)
            elif char == ";":
                if code[start:cursor].strip():
                    observed += 1
                    if abstract_ends.get(cursor + 1) != start:
                        names = self.field_names(code[start:cursor], file["original"][start:cursor])
                        if names is None or field_names.intersection(names):
                            fields = False; reasons.add("selected_source_field_inventory_unverified")
                        else:
                            field_names.update(names)
                start = cursor = space(cursor + 1)
            elif char in ")]}":
                fields = members = False; reasons.add("selected_source_member_boundary_unverified"); break
            else:
                cursor += 1
            if len(field_names) > MAX_SOURCE_MEMBERS:
                field_names = set(sorted(field_names)[:MAX_SOURCE_MEMBERS])
                fields = False; reasons.add("selected_source_field_inventory_budget_exceeded"); break
            if observed >= MAX_SOURCE_MEMBERS and cursor < right:
                fields = members = False; reasons.add("selected_source_member_inventory_budget_exceeded"); break
        if code[start:right].strip():
            fields = members = False; reasons.add("selected_source_member_inventory_unverified")
        if scope["kind"] == "record":
            header = record_header
            components = header.get("components", []) if header else []
            names = [component["name"] for component in components]
            if (not header or header.get("detected") is None or header.get("reasons")
                    or len(names) > MAX_SOURCE_MEMBERS or any(not name or not declaration_identifier(name) for name in names)
                    or any(not self.field_type_syntax(re.sub(r"\.\.\.$", "[]", component.get("rawType") or "")) for component in components)
                    or len(set(names)) != len(names) or field_names.intersection(names)):
                fields = False; reasons.add("selected_record_implicit_field_inventory_unverified")
            else:
                field_names.update(names)
                if len(field_names) > MAX_SOURCE_MEMBERS:
                    field_names = set(sorted(field_names)[:MAX_SOURCE_MEMBERS])
                    fields = False; reasons.add("selected_source_field_inventory_budget_exceeded")
        if scope["kind"] not in {"class", "interface", "record", "enum"}:
            fields = members = False; reasons.add("selected_source_member_kind_unverified")
        return {"fields": "complete" if fields else "UNKNOWN", "memberTypes": "complete" if members else "UNKNOWN",
                "observedDirectDeclarationRegions": observed, "reasons": sorted(reasons),
                "fieldNames": sorted(field_names), "_constructorRegions": constructor_regions,
                "_directTypeIds": sorted(direct_type_ids)}

    @lru_cache(maxsize=20_000)
    def query(self, owner, name, values=False):
        index = self.index; scopes = {}; contracts = {}; edges = []; reasons = set()
        present = False
        observed_edges = omitted_edges = 0
        def visit(current, seen, parent=False):
            nonlocal present, observed_edges, omitted_edges
            if current in seen:
                reasons.add("inheritance_cycle"); return
            if len(scopes) + len(contracts) >= MAX_SCOPES:
                reasons.add("inheritance_scope_budget_exceeded"); return
            scope = index.types.get(current)
            if scope is None:
                entry = contract(current)
                if not entry:
                    reasons.add("parent_declaration_unavailable"); return
                contracts[entry["id"]] = entry
                present |= name in entry["memberTypes"] or (values and name in entry["fields"])
                for ancestor in entry["directParents"]:
                    ancestor_entry = contract(ancestor)
                    conflict = ancestor in index.types or any(ancestor.startswith(q + ".") for q in index.types)
                    edge = {"fromContractId": entry["id"], "parentType": ancestor,
                            "parentContractId": ancestor_entry["id"]}
                    if conflict:
                        contracts[ancestor_entry["id"]] = ancestor_entry
                        edge.update(status="UNKNOWN", reason="selected_platform_identity_conflict")
                        reasons.add("selected_platform_identity_conflict")
                    edges.append(edge)
                    if not conflict: visit(ancestor, seen | {current}, True)
                return
            source_file = index.files[scope["path"]]
            identity = self.symbol(scope["id"])
            inventory = self.source_inventory(current)
            if inventory["memberTypes"] != "complete" or (values and inventory["fields"] != "complete"):
                reasons.update(inventory["reasons"])
            scopes[identity] = {"memberInventory": {k: v for k, v in inventory.items() if not k.startswith("_")}, "sourceEvidenceId": identity, "qualifiedName": current, "kind": scope["kind"].title(),
                "path": scope["path"], "sourceDigest": source_file["sourceHash"],
                "sourceRange": {"charStart": scope["start"], "charEnd": scope["body_start"] + 1}}
            # Direct names matter too: JavaIndex deliberately leaves some
            # declarators out of CALLS accounting, which is not absence proof.
            present |= (parent and current + "." + name in index.types) or (values and name in inventory.get("fieldNames", []))
            parents = index.core._java_hierarchy(scope["header"], scope["kind"])
            for position, raw in enumerate(parents[0] + parents[1]):
                observed_edges += 1
                reference = {"relation": "extends" if position < len(parents[0]) else "implements",
                    "index": position if position < len(parents[0]) else position - len(parents[0])}
                if observed_edges > 64:
                    omitted_edges += 1; reasons.add("inheritance_edge_budget_exceeded"); continue
                target, reason = self.parent(raw, scope)
                if reason:
                    reasons.add(reason)
                    edges.append({"fromSourceId": identity, "sourceParentReference": reference,
                        "parentType": None, "status": "UNKNOWN", "reason": reason})
                    continue
                edges.append({"fromSourceId": identity, "sourceParentReference": reference, "parentType": target,
                    **({"parentContractId": contract(target)["id"]} if target not in index.types else {"parentSourceId": self.symbol(index.types[target]["id"])})})
                visit(target, seen | {current}, True)
        if owner: visit(owner, set())
        status = "UNKNOWN" if reasons else "present" if present else "absent"
        data = {"scope": "inherited_name_lookup", "ownerType": owner, "queriedName": name,
                "namespace": "field_or_member_type" if values else "member_type", "status": status,
                "reasons": sorted(reasons), "sourceScopes": list(scopes.values()), "parentEdges": edges,
                "catalogIds": sorted(contracts), "sourceEvidenceIds": sorted(scopes),
                "observedSourceParentEdges": observed_edges, "omittedSourceParentEdges": omitted_edges,
                "transitiveInventoryComplete": not reasons,
                "selectedSourceMembers": "bounded_direct_member_inventory",
                "runtimeNameResolution": "UNKNOWN"}
        return {"id": "platform-lookup:" + hashlib.sha256(canonical(data)).hexdigest()[:24], **data}, list(contracts.values())

    def possible(self, owner, name, values=False):
        check, entries = self.query(owner, name, values)
        if self.stack and (entries or values and check["sourceScopes"] or check["reasons"]):
            self.stack[-1][check["id"]] = {**check, "_catalog": entries}
        return check["status"] != "absent"


class Projection:
    """One record's bounded, deduplicated check definitions and API catalogs."""
    def __init__(self, capture, location="fragment", owner_id=None):
        self.capture = capture
        self.owner_id = owner_id
        self.location = location
        self.checks, self.catalog = {}, {}
        self.omitted = 0

    def call(self, function, *args):
        if not self.capture:
            return function(*args)
        value, captured = self.capture(lambda: function(*args))
        checks = {c["id"]: {k: v for k, v in c.items() if k != "_catalog"} for c in captured}
        catalog = {e["id"]: e for c in captured for e in c["_catalog"]}
        merged_checks, merged_catalog = {**self.checks, **checks}, {**self.catalog, **catalog}
        if len(merged_checks) > MAX_CHECKS or len(canonical([merged_checks, merged_catalog])) > MAX_CATALOG_BYTES:
            self.omitted += len(checks)
            return None  # No evidence from a lookup whose definitions cannot fit.
        self.checks, self.catalog = merged_checks, merged_catalog
        active = [c for c in checks.values() if c["status"] == "absent" and (c["catalogIds"] or c["sourceScopes"])]
        if value is not None and active:
            refs = {"checkIds": sorted(c["id"] for c in active), "catalogLocation": self.location + ".platformInheritanceChecks"}
            if not any(check["catalogIds"] for check in active):
                refs["proofScope"] = "source_value_name_absence"
            evidence = sorted({s for c in active for s in c["sourceEvidenceIds"]})
            if isinstance(value, dict):
                value = dict(value)
                target = value
                if "resultType" in value:
                    target = value["resultType"] = dict(value["resultType"])
                refs["_origin"] = target.pop("_platformOrigin", None)
                target["platformInheritance"] = refs
                if "sourceEvidenceIds" in target:
                    target["sourceEvidenceIds"] = sorted(set(target["sourceEvidenceIds"] + evidence))
        if isinstance(value, dict):
            value = dict(value)
            value.pop("_platformOrigin", None)
            if isinstance(value.get("resultType"), dict):
                value["resultType"] = dict(value["resultType"])
                value["resultType"].pop("_platformOrigin", None)
        return value

    def local_initializer(self, typed, provider):
        """Import bounded definitions, keeping the actual initializer as origin.

        A record-local proof ID cannot authorize another record's consumer.
        The new consumer receives its own proof at sealing; only the exact
        upstream static-type slot is referenced across records.
        """
        ref = typed.get("platformInheritance")
        if not isinstance(ref, dict):
            return typed
        if not isinstance(provider, dict):
            return None
        upstream = pointer(provider, "/expression/staticType")
        binding = typed.get("localTypeBinding")
        if (not isinstance(upstream, dict) or upstream.get("platformInheritance") != ref
                or provider.get("localTypeInference") != binding
                or not isinstance(binding, dict) or binding.get("declarationFragmentId") != provider.get("id")):
            return None
        wanted = ref.get("checkIds")
        if not isinstance(wanted, list) or not wanted or len(wanted) > MAX_CHECKS:
            return None
        checks, catalog = {}, {}
        for key, selected in (("platformInheritanceChecks", checks), ("platformTypeContracts", catalog)):
            entries = provider.get(key, [])
            if not isinstance(entries, list) or len(entries) > MAX_CHECKS:
                return None
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                    return None
                identity = entry["id"]
                if identity in selected and canonical(selected[identity]) != canonical(entry):
                    return None
                selected[identity] = entry
        if any(identity not in checks for identity in wanted):
            return None
        checks = {identity: checks[identity] for identity in wanted}
        required_catalog = {identity for check in checks.values() for identity in check.get("catalogIds", [])}
        if any(identity not in catalog for identity in required_catalog):
            return None
        catalog = {identity: catalog[identity] for identity in required_catalog}
        if (any(key in self.checks and canonical(self.checks[key]) != canonical(value) for key, value in checks.items())
                or any(key in self.catalog and canonical(self.catalog[key]) != canonical(value) for key, value in catalog.items())):
            return None
        merged_checks, merged_catalog = {**self.checks, **checks}, {**self.catalog, **catalog}
        if len(merged_checks) > MAX_CHECKS or len(canonical([merged_checks, merged_catalog])) > MAX_CATALOG_BYTES:
            self.omitted += len(checks)
            return None
        self.checks, self.catalog = merged_checks, merged_catalog
        typed["platformInheritance"] = {"checkIds": list(wanted),
            "catalogLocation": self.location + ".platformInheritanceChecks",
            "_origin": {"kind": "local_initializer", "recordId": provider["id"],
                "path": provider["path"], "sourceDigest": provider["sourceDigest"],
                "selector": "/expression/staticType", "proofId": ref.get("proofId")}}
        return typed

    def finish(self, output):
        if self.checks:
            output["platformInheritanceChecks"] = list(self.checks.values())
        if self.catalog:
            output["platformTypeContracts"] = list(self.catalog.values())
        seal_type_proofs(output, self.location, self.owner_id)
        if self.omitted:
            output["platformInheritanceCoverage"] = {**output.get("platformInheritanceCoverage", {}), "status": "PARTIAL", "omittedChecks": self.omitted,
                "reason": "platform_inheritance_projection_budget_exceeded", "runtimeStatus": "UNKNOWN"}


def inherit(typed, *parents):
    if typed is None: return typed
    # A source value-name absence guards the exact source slot. The ordinary
    # dependency walk checks that child before retaining a derived API/type.
    # It is not an inherited platform type fact to replicate up every chain.
    refs = [p["platformInheritance"] for p in parents if isinstance(p, dict) and "platformInheritance" in p
        and p["platformInheritance"].get("proofScope") != "source_value_name_absence"]
    if refs:
        typed["platformInheritance"] = {"checkIds": sorted({key for ref in refs for key in ref["checkIds"]}),
            "catalogLocation": refs[0]["catalogLocation"], "_parentKeys": [id(ref) for ref in refs]}
    return typed



def pointer(value, location):
    """Strict RFC6901-style pointer; no arbitrary attribute/path access."""
    if not isinstance(location, str) or not location.startswith("/"):
        return None
    parts = location[1:].split("/")
    if len(parts) > 512 or len(location) > 4096: return None
    for token in parts:
        if "~" in token and re.search(r"~(?![01])", token): return None
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(token)
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            position = int(token)
            value = value[position] if position < len(value) else None
        else: return None
    return value


def _type_slots(output):
    result = []; pending = [(output, "", 0)]; examined = 0
    while pending:
        value, location, depth = pending.pop()
        examined += 1
        if examined > 20_000 or len(location) > 4096: return None
        if isinstance(value, dict):
            if isinstance(value.get("platformInheritance"), dict): result.append((location, value))
            for key, item in value.items():
                if key.startswith("_") or key in {"platformInheritance", "platformTypeProofs", "platformInheritanceChecks", "platformTypeContracts"}: continue
                if isinstance(item, (dict, list)):
                    pending.append((item, location + "/" + key.replace("~", "~0").replace("/", "~1"), depth + 1))
        elif isinstance(value, list):
            pending.extend((item, location + "/" + str(i), depth + 1) for i, item in enumerate(value) if isinstance(item, (dict, list)))
    return result


def _proof_id(record_id, location):
    return "platform-type-proof:" + hashlib.sha256(canonical([record_id, location])).hexdigest()[:24]


def _consumer_type(value, output):
    name = value.get("type") if "typeResolution" in value and "declaredType" in value else value.get("name", value.get("type"))
    if isinstance(name, str): return name
    if isinstance(value.get("contractId"), str):
        entries = [c for c in output.get("standardApiContracts", []) if c.get("id") == value["contractId"]]
        if entries and all(canonical(c) == canonical(entries[0]) for c in entries):
            return entries[0].get("result", {}).get("type")
    return None


def seal_type_proofs(output, location="fragment", owner_id=None):
    """Replace temporary producer links with bounded, actual IR locations."""
    slots = _type_slots(output)
    if slots is None:
        raise ValueError("platform_type_proof_traversal_budget_exceeded")
    record_id = output.get("id", owner_id)
    definitions, locations = [], {}
    for place, value in slots:
        locations.setdefault(id(value["platformInheritance"]), []).append(place)
    for place, value in slots:
        ref = value["platformInheritance"]
        identity = _proof_id(record_id, place)
        parents = ref.get("_parentKeys")
        definition = {"id": identity, "consumer": place, "typeName": _consumer_type(value, output),
                      "checkIds": ref.get("checkIds", []), "mode": "propagated" if parents else "direct"}
        if parents:
            selected = []
            for parent in parents:
                candidates = locations.get(parent, [])
                selected.append(candidates[0] if len(candidates) == 1 else None)
            definition["parents"] = [{"proofId": _proof_id(record_id, item), "consumer": item} for item in selected if item is not None]
            if any(item is None for item in selected): definition["unsupportedReason"] = "platform_type_parent_not_emitted"
            definition["operation"] = value.get("basis", "standard_api_contract" if "contractId" in value else "UNKNOWN")
        else:
            definition["origin"] = ref.get("_origin")
            if not definition["origin"]: definition["unsupportedReason"] = "platform_type_origin_not_emitted"
        definitions.append(definition)
        # Delay mutation until every temporary parent has been located.
    for (place, value), definition in zip(slots, definitions):
        ref = value["platformInheritance"]
        value["platformInheritance"] = {"schemaVersion": 2, "proofId": definition["id"],
            "proofLocation": location + ".platformTypeProofs", "checkIds": list(ref.get("checkIds", [])),
            "catalogLocation": location + ".platformInheritanceChecks"}
        if ref.get("proofScope") == "source_value_name_absence":
            value["platformInheritance"]["proofScope"] = "source_value_name_absence"
        value.pop("_platformOrigin", None)
    if (len(definitions) + len(output.get("platformInheritanceChecks", [])) > MAX_CHECKS or len(canonical([output.get("platformInheritanceChecks", []),
            output.get("platformTypeContracts", []), definitions])) > MAX_CATALOG_BYTES):
        output["platformInheritanceCoverage"] = {"status": "PARTIAL", "omittedProofs": len(definitions),
            "reason": "platform_type_proof_projection_budget_exceeded", "runtimeStatus": "UNKNOWN"}
        if location == "record":
            for _, value in slots:
                value.pop("platformInheritance", None)
                value.update(type=None, typeResolution="UNKNOWN", typeReason="platform_type_proof_projection_budget_exceeded")
    elif definitions:
        output["platformTypeProofs"] = definitions


def prune(output):
    """Withdrawing a type also withdraws its positive absence definitions."""
    pending, used = [output.get("expression"), output.get("target")], set()
    used_proofs = set()
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            ref = item.get("platformInheritance")
            if isinstance(ref, dict):
                used.update(ref.get("checkIds", []))
                if isinstance(ref.get("proofId"), str): used_proofs.add(ref["proofId"])
            pending.extend(item.values())
        elif isinstance(item, list): pending.extend(item)
    if "platformTypeProofs" in output:
        by_id = {d.get("id"): d for d in output["platformTypeProofs"] if isinstance(d, dict)}
        work = list(used_proofs)
        while work and len(used_proofs) <= MAX_CHECKS:
            current = by_id.get(work.pop(), {})
            for parent in current.get("parents", []):
                identity = parent.get("proofId")
                if identity not in used_proofs:
                    used_proofs.add(identity); work.append(identity)
        retained = [d for d in output["platformTypeProofs"] if d.get("id") in used_proofs]
        if retained: output["platformTypeProofs"] = retained
        else: output.pop("platformTypeProofs", None)
    if "platformInheritanceChecks" in output:
        checks = [c for c in output["platformInheritanceChecks"] if c["id"] in used or c["status"] != "absent"]
        if checks: output["platformInheritanceChecks"] = checks
        else: output.pop("platformInheritanceChecks")
        catalog_ids = {identity for check in checks for identity in check["catalogIds"]}
        catalog = [entry for entry in output.get("platformTypeContracts", []) if entry["id"] in catalog_ids]
        if catalog: output["platformTypeContracts"] = catalog
        else: output.pop("platformTypeContracts", None)



def declared_type_accessible(row, caller, lookup):
    """Bounded existing named-type eligibility, using emitted owners only."""
    def contained(outer,inner):
        return (isinstance(outer,dict) and isinstance(inner,dict)
            and all(type(v) is int for v in (outer.get("charStart"),outer.get("charEnd"),inner.get("charStart"),inner.get("charEnd")))
            and 0<=outer["charStart"]<=inner["charStart"]<inner["charEnd"]<=outer["charEnd"])
    def named_type(value):
        return (isinstance(value,dict) and value.get("kind")=="symbol" and value.get("type") in {"Class","Interface","Record","Enum"}
            and value.get("basis")=="declared" and value.get("status")=="runtime_unknown"
            and isinstance(value.get("qualifiedName"),str) and isinstance(value.get("sourcePackage"),str)
            and value.get("name")==value["qualifiedName"].rsplit(".",1)[-1]
            and (not value["sourcePackage"] or value["qualifiedName"].startswith(value["sourcePackage"]+"."))
            and contained(value.get("sourceRange"),value.get("bodyRange"))
            and not value.get("structuralOnly") and value.get("dependencyClosure",{}).get("status") not in {"invalidated","pending_snapshot_finalization"})
    seen=set()
    while row is not None:
        if not named_type(row) or row.get("id") in seen or len(seen)>=MAX_SCOPES:return False
        seen.add(row["id"])
        eligibility=row.get("typeDeclarationEligibility",{})
        if (set(eligibility)!={"schemaVersion","status","modifiers","enclosingTypeId","scope"}
                or type(eligibility.get("schemaVersion")) is not int or eligibility.get("schemaVersion")!=1 or eligibility.get("status")!="source_header_only"
                or eligibility.get("scope")!="named_type_access_not_compiler_validity"):return False
        mods=eligibility.get("modifiers")
        if not isinstance(mods,list) or any(not isinstance(m,str) for m in mods) or mods!=sorted(set(mods)) or len(set(mods)&{"public","protected","private"})>1:return False
        package=row["sourcePackage"];local=row["qualifiedName"][len(package)+1:] if package else row["qualifiedName"]
        nest=(package+"." if package else "")+local.split(".",1)[0]
        same_nest=caller.get("qualifiedName")==nest or caller.get("qualifiedName","").startswith(nest+".")
        if "private" in mods and not same_nest:return False
        if "public" not in mods and not same_nest and caller.get("sourcePackage")!=package:return False
        identity=eligibility.get("enclosingTypeId")
        if identity is None:return True
        parent=lookup(identity,row["path"]) if lookup else None
        if (not named_type(parent) or parent.get("id")!=identity or parent.get("path")!=row.get("path")
                or parent.get("sourceDigest")!=row.get("sourceDigest") or parent.get("sourcePackage")!=package
                or not row["qualifiedName"].startswith(parent.get("qualifiedName","")+".")
                or not contained(parent.get("bodyRange"),row.get("sourceRange"))):return False
        row=parent
    return False


def _selected_field_requirements(value, output, lookup, allow_pending=False):
    """Actual declaration membership and caller selection, not initializer values.

    The type-local catalog contains bounded source syntax/ranges, not invented
    semantic record IDs. A use joins its existing exact semantic identity to
    that catalog and to actual delivered source owners. Unused import namespaces
    never override a valid explicit single import.
    """
    invalid = "source_field_role_or_namespace_unverified"
    pending = "dependency_pending_snapshot_finalization"

    def walk(item):
        work, count = [item], 0
        while work:
            node = work.pop(); count += 1
            if count > 20_000: raise ValueError("source_field_proof_traversal_budget_exceeded")
            if isinstance(node, dict):
                yield node
                work.extend(child for child in node.values() if isinstance(child, (dict, list)))
            elif isinstance(node, list): work.extend(node)

    def contained(outer, inner):
        return (isinstance(outer, dict) and isinstance(inner, dict)
            and all(type(item) is int for item in (outer.get("charStart"), outer.get("charEnd"), inner.get("charStart"), inner.get("charEnd")))
            and 0 <= outer["charStart"] <= inner["charStart"] < inner["charEnd"] <= outer["charEnd"])

    def actual(identity, path):
        row = lookup(identity, path) if lookup else None
        if row is None: return None
        if (not isinstance(row, dict) or row.get("id") != identity or row.get("path") != path
                or row.get("structuralOnly") or row.get("dependencyClosure", {}).get("status") in {"invalidated", "pending_snapshot_finalization"}):
            raise ValueError(invalid)
        return row

    def named_type(row):
        return (isinstance(row, dict) and row.get("kind") == "symbol" and row.get("type") in {"Class", "Interface", "Record", "Enum"}
            and row.get("basis") == "declared" and row.get("status") == "runtime_unknown"
            and isinstance(row.get("qualifiedName"), str) and isinstance(row.get("sourcePackage"), str)
            and row.get("name") == row["qualifiedName"].rsplit(".",1)[-1]
            and (not row["sourcePackage"] or row["qualifiedName"].startswith(row["sourcePackage"]+"."))
            and contained(row.get("sourceRange"), row.get("bodyRange")))

    def access_chain(row, caller):
        return declared_type_accessible(row,caller,actual)

    def namespace_check(check, root, name, expected, table):
        if (not isinstance(check, dict) or check.get("scope") != "inherited_name_lookup" or check.get("ownerType") != root
                or check.get("queriedName") != name or check.get("namespace") != "field_or_member_type"
                or check.get("status") != expected or check.get("reasons") != [] or check.get("transitiveInventoryComplete") is not True
                or check.get("omittedSourceParentEdges") != 0
                or check.get("id") != "platform-lookup:" + hashlib.sha256(canonical({key: item for key, item in check.items() if key != "id"})).hexdigest()[:24]):
            return False
        scopes, ids = {}, {}
        for scope in check.get("sourceScopes", []):
            qname = scope.get("qualifiedName")
            if qname not in table or qname in scopes: return False
            row = table[qname]
            if (scope.get("sourceEvidenceId") != row["id"] or scope.get("path") != row["path"]
                    or scope.get("sourceDigest") != row["sourceDigest"] or scope.get("kind") != row["type"]
                    or scope.get("sourceRange") != row.get("declarationHeaderRange")
                    or scope.get("memberInventory") != row.get("directMemberInventory")): return False
            inventory = scope["memberInventory"]
            names = inventory.get("fieldNames")
            if (inventory.get("fields") != "complete" or inventory.get("memberTypes") != "complete"
                    or not isinstance(names, list) or len(names) > MAX_SOURCE_MEMBERS
                    or any(not isinstance(item, str) or not declaration_identifier(item) for item in names)
                    or names != sorted(set(names))): return False
            if name in names and (expected != "present" or qname != root): return False
            scopes[qname], ids[row["id"]] = row, qname
        if root not in scopes or expected == "present" and name not in scopes[root]["directMemberInventory"]["fieldNames"]: return False
        if check.get("sourceEvidenceIds") != sorted(ids): return False
        platform = {entry["id"]: entry for entry in (contract(qname) for qname in _DECLARATIONS)}
        catalog_ids = check.get("catalogIds")
        if (not isinstance(catalog_ids, list) or catalog_ids != sorted(set(catalog_ids))
                or any(identity not in platform for identity in catalog_ids) or len(scopes) + len(catalog_ids) > MAX_SCOPES): return False
        for identity in catalog_ids:
            if name in platform[identity]["fields"] or name in platform[identity]["memberTypes"]: return False
        graph = {identity: [] for identity in list(ids) + catalog_ids}
        consumed, source_edges = set(), 0
        for edge in check.get("parentEdges", []):
            if "fromSourceId" in edge:
                identity, reference = edge["fromSourceId"], edge.get("sourceParentReference", {})
                if identity not in ids or set(reference) != {"relation", "index"}: return False
                relation, position = reference["relation"], reference["index"]
                if relation not in {"extends", "implements"} or type(position) is not int: return False
                refs = scopes[ids[identity]].get(relation + "Types", [])
                if not 0 <= position < len(refs) or (identity, relation, position) in consumed: return False
                consumed.add((identity, relation, position)); source_edges += 1
                ref = refs[position]
                if ref.get("resolution") != "resolved" or ref.get("resolvedType") != edge.get("parentType"): return False
            elif "fromContractId" in edge:
                identity = edge["fromContractId"]
                if identity not in catalog_ids or edge.get("parentType") not in platform[identity]["directParents"]: return False
                marker = (identity, edge["parentType"])
                if marker in consumed: return False
                consumed.add(marker)
            else: return False
            target = edge.get("parentSourceId", edge.get("parentContractId"))
            if target not in graph or edge.get("status", "resolved") == "UNKNOWN": return False
            if target in ids and scopes[ids[target]]["qualifiedName"] != edge["parentType"]: return False
            if target in platform and platform[target]["qualifiedName"] != edge["parentType"]: return False
            graph[identity].append(target)
        if (source_edges != check.get("observedSourceParentEdges")
                or source_edges != sum(len(row.get("extendsTypes", [])) + len(row.get("implementsTypes", [])) for row in scopes.values())): return False
        for identity in catalog_ids:
            if len(graph[identity]) != len(platform[identity]["directParents"]): return False
        reached, active = set(), set()
        def visit(identity):
            if identity in active: return False
            if identity in reached: return True
            if len(reached) >= MAX_SCOPES: return False
            active.add(identity); reached.add(identity)
            if not all(visit(parent) for parent in graph[identity]): return False
            active.remove(identity); return True
        return visit(scopes[root]["id"]) and reached == set(graph)

    pairs = (("staticFieldBinding", "staticType"), ("receiverStaticFieldBinding", "receiverStaticType"))
    for node in walk(value):
        for binding_key, type_key in pairs:
            binding, typed = node.get(binding_key), node.get(type_key)
            if isinstance(typed, dict) and typed.get("basis") == "selected_static_final_field_declaration" and not isinstance(binding, dict): return invalid
            if not isinstance(binding, dict) or binding.get("resolution") != "selected_static_final_field": continue
            binding_keys = {"resolution", "declaringType", "name", "path", "sourceDigest", "declarationFragmentId", "declarationProofVersion",
                "declaredType", "resolvedType", "declaringOwner", "memberDeclaration", "callerNamespace", "sourceRange", "initializerEvidence", "valueSubstitution", "runtimeValue"}
            if (set(binding) != binding_keys or type(binding.get("declarationProofVersion")) is not int or binding["declarationProofVersion"] != 1
                    or not isinstance(typed, dict) or typed.get("resolution") != "resolved_static_type"
                    or typed.get("name") != binding.get("resolvedType") or not isinstance(typed.get("sourceEvidenceIds"), list)
                    or binding.get("runtimeValue") != "UNKNOWN" or binding.get("valueSubstitution") is not False): return invalid
            provider = actual(binding.get("declarationFragmentId"), binding.get("path"))
            if provider is None: return pending if allow_pending and binding.get("path") != output.get("path") else invalid
            if (provider.get("sourceDigest") != binding.get("sourceDigest") or provider.get("declaredType") != binding.get("declaredType")
                    or provider.get("name") != binding.get("name") or provider["id"] not in typed["sourceEvidenceIds"]
                    or not contained(provider.get("sourceRange"), binding.get("sourceRange"))
                    or provider["id"] != "semantic:" + hashlib.sha256(canonical([provider["path"],provider["sourceDigest"],"constant",
                        provider["sourceRange"]["charStart"],provider["sourceRange"]["charEnd"]])).hexdigest()): return invalid
            initializer = binding.get("initializerEvidence", {})
            if (initializer.get("fragmentId") != provider["id"] or initializer.get("value") != "UNKNOWN" or initializer.get("execution") != "not_observed"
                    or not contained(provider["sourceRange"], initializer.get("sourceRange"))
                    or not provider["sourceRange"]["charStart"] < initializer["sourceRange"]["charStart"] < initializer["sourceRange"]["charEnd"] < provider["sourceRange"]["charEnd"]): return invalid
            member, namespace = binding.get("memberDeclaration"), binding.get("callerNamespace")
            if (not isinstance(member, dict) or set(member) != {"schemaVersion", "role", "name", "declaredType", "sourceRange", "initializerRange", "modifiers"}
                    or type(member.get("schemaVersion")) is not int or member["schemaVersion"] != 1
                    or member.get("role") != "direct_type_static_final_field"
                    or member.get("name") != provider.get("name") or member.get("declaredType") != provider.get("declaredType")
                    or member.get("sourceRange") != provider.get("sourceRange") or member.get("sourceRange") != binding.get("sourceRange")
                    or member.get("initializerRange") != binding.get("initializerEvidence", {}).get("sourceRange")
                    or provider.get("kind") != "semantic_fragment" or provider.get("category") != "constant"): return invalid
            control = provider.get("controlFlow")
            if (not isinstance(control, dict) or "owner" not in control or control["owner"] is not None
                    or control.get("kind") != "statement" or control.get("contexts") != [] or provider.get("javaSourceOwner") is not None): return invalid
            mods = member.get("modifiers")
            if (not isinstance(mods, list) or any(not isinstance(item, str) for item in mods) or mods != sorted(set(mods))
                    or not {"static", "final"} <= set(mods) or "volatile" in mods
                    or not set(mods) <= {"public", "protected", "private", "static", "final", "transient"}
                    or len(set(mods) & {"public", "protected", "private"}) > 1): return invalid
            owner_proof = binding.get("declaringOwner", {})
            if (not isinstance(owner_proof, dict) or set(owner_proof) != {"id", "qualifiedName", "type", "path", "sourceDigest", "declarationHeaderRange", "sourceRange", "declarationRange", "bodyRange"}
                    or owner_proof["id"] not in typed["sourceEvidenceIds"] or owner_proof["qualifiedName"] != binding["declaringType"]
                    or owner_proof["sourceDigest"] != provider["sourceDigest"] or owner_proof["path"] != provider["path"]): return invalid
            owner = actual(owner_proof.get("id"), binding.get("path"))
            if owner is None: return pending if allow_pending and binding.get("path") != output.get("path") else invalid
            if (not named_type(owner) or any(owner.get(key) != item for key, item in owner_proof.items())
                    or not contained(owner.get("bodyRange"), provider.get("sourceRange"))
                    or not source_type_matches(provider["declaredType"], typed["name"], owner)): return invalid
            catalog = owner.get("staticFieldDeclarations")
            if (not isinstance(catalog, dict) or set(catalog) != {"schemaVersion", "scope", "detectedCandidates", "declarations", "unsupportedCandidates", "budgetOmittedCandidates", "completeForDetectedCandidates", "wholeFieldDeclarationDenominator", "initializerValues"}
                    or type(catalog.get("schemaVersion")) is not int or catalog["schemaVersion"] != 1
                    or catalog.get("scope") != "bounded_indexed_direct_static_final_declarations"
                    or catalog.get("wholeFieldDeclarationDenominator") != "UNKNOWN" or catalog.get("initializerValues") != "not_evaluated"): return invalid
            entries = catalog.get("declarations")
            counters = [catalog.get(key) for key in ("detectedCandidates", "unsupportedCandidates", "budgetOmittedCandidates")]
            if (not isinstance(entries, list) or len(entries) > MAX_SOURCE_MEMBERS or len(canonical(entries)) > MAX_CATALOG_BYTES
                    or any(type(item) is not int or item < 0 for item in counters)
                    or counters[0] != len(entries) + counters[1] + counters[2]
                    or catalog.get("completeForDetectedCandidates") is not (counters[1] == counters[2] == 0)
                    or sum(entry == member for entry in entries) != 1): return invalid
            if (not isinstance(namespace, dict) or set(namespace) != {"schemaVersion", "selection", "name", "selectedOwner", "callerTypeId", "callerDeclaration", "path", "sourceDigest", "namespaceOwners", "namespaceChecks"}
                    or type(namespace.get("schemaVersion")) is not int or namespace["schemaVersion"] != 1
                    or namespace.get("selection") != "static_import" or namespace.get("name") != binding.get("name")
                    or namespace.get("selectedOwner") != binding.get("declaringType")
                    or namespace.get("path") != output.get("path") or namespace.get("sourceDigest") != output.get("sourceDigest")
                    or len(canonical(namespace)) > MAX_CATALOG_BYTES): return invalid
            namespace_checks = namespace.get("namespaceChecks")
            check_keys = {"id", "scope", "ownerType", "queriedName", "namespace", "status", "reasons", "sourceScopes", "parentEdges", "catalogIds", "sourceEvidenceIds", "observedSourceParentEdges", "omittedSourceParentEdges", "transitiveInventoryComplete", "selectedSourceMembers", "runtimeNameResolution"}
            if (not isinstance(namespace_checks,list) or len(namespace_checks)>MAX_CHECKS
                    or any(not isinstance(check,dict) or set(check)!=check_keys or check.get("scope")!="inherited_name_lookup"
                        or check.get("namespace")!="field_or_member_type" or check.get("status") not in {"present","absent","UNKNOWN"}
                        or check.get("id")!="platform-lookup:"+hashlib.sha256(canonical({key:item for key,item in check.items()if key!="id"})).hexdigest()[:24]
                        for check in namespace_checks)): return invalid
            caller = actual(namespace.get("callerTypeId"), output.get("path"))
            caller_declaration = namespace.get("callerDeclaration")
            if (not isinstance(caller_declaration,dict) or set(caller_declaration) != set(owner_proof)
                    or not named_type(caller) or any(caller.get(key)!=item for key,item in caller_declaration.items())
                    or caller_declaration["id"] != namespace["callerTypeId"] or caller.get("sourceDigest") != output.get("sourceDigest")
                    or not contained(caller.get("bodyRange"), output.get("sourceRange"))
                    or output.get("javaSourceOwner") is not None and output["javaSourceOwner"].get("typeSymbolId") != caller["id"]): return invalid
            if not access_chain(owner, caller): return invalid
            package, qname = owner["sourcePackage"], owner["qualifiedName"]
            local = qname[len(package) + 1:] if package else qname
            nest = (package + "." if package else "") + local.split(".", 1)[0]
            same_nest = caller["qualifiedName"] == nest or caller["qualifiedName"].startswith(nest + ".")
            if "private" in mods and not same_nest: return invalid
            if "public" not in mods and not same_nest and caller["sourcePackage"] != package: return invalid
            uses = [(candidate, key) for root in (output.get("expression"), output.get("target")) for candidate in walk(root)
                for key, _ in pairs if candidate.get(key) is binding]
            if not uses:
                uses = [(candidate, key) for root in (output.get("expression"), output.get("target")) for candidate in walk(root)
                    for key, _ in pairs if candidate.get(key) == binding]
            if not uses or any(candidate.get("op") != "reference" or
                    (candidate.get("name", "").rsplit(".", 1)[0] if key == "receiverStaticFieldBinding" else candidate.get("name")) != binding["name"]
                    for candidate, key in uses): return invalid
            imports, coverage = caller.get("typeImports"), caller.get("typeImportCoverage", {})
            if (not isinstance(imports, list) or len(imports) > MAX_CHECKS or coverage.get("complete") is not True
                    or coverage.get("status") != "declared" or any(type(coverage.get(key)) is not int or coverage[key] != len(imports) for key in ("detected", "recorded"))
                    or any(not isinstance(item, dict) or item.get("kind") not in {"static", "type"}
                        or not isinstance(item.get("qualifiedName"), str) for item in imports)): return invalid
            table = {}
            entries = namespace.get("namespaceOwners")
            if not isinstance(entries, list) or len(entries) > MAX_CHECKS * MAX_SCOPES: return invalid
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"id", "qualifiedName", "path", "sourceDigest"} or entry["qualifiedName"] in table: return invalid
                row = actual(entry["id"], entry["path"])
                if not named_type(row) or any(row.get(key) != item for key, item in entry.items()): return invalid
                table[entry["qualifiedName"]] = row
            if table.get(binding["declaringType"], {}).get("id") != owner["id"]: return invalid
            explicit = {item["qualifiedName"] for item in imports if item["kind"] == "static" and not item["qualifiedName"].endswith(".*")
                and item["qualifiedName"].rsplit(".", 1)[-1] == binding["name"]}
            if explicit:
                if explicit != {binding["declaringType"] + "." + binding["name"]}: return invalid
                continue
            wildcards = {item["qualifiedName"][:-2] for item in imports if item["kind"] == "static" and item["qualifiedName"].endswith(".*")}
            if binding["declaringType"] not in wildcards or not wildcards <= set(table): return invalid
            checks = namespace.get("namespaceChecks")
            if not isinstance(checks, list) or len(checks) > MAX_CHECKS: return invalid
            for imported in wildcards:
                selected = [check for check in checks if check.get("ownerType") == imported]
                if len(selected) != 1 or not namespace_check(selected[0], imported, binding["name"],
                        "present" if imported == binding["declaringType"] else "absent", table): return invalid
    return None


def _validate_type_proofs(value, output, checks, lookup, api_validator, allow_pending=False, proof_trail=(), complete_lookup=True):
    """Validate consumers against actual IR slots and emitted declarations."""
    invalid = "platform_type_consumer_binding_invalid"
    missing = "platform_type_origin_not_emitted"
    pending_reason = "dependency_pending_snapshot_finalization"
    entries = output.get("platformTypeProofs", [])
    if not isinstance(entries, list) or len(entries) > MAX_CHECKS: return invalid
    if (len(entries)+len(output.get('platformInheritanceChecks',[]))>MAX_CHECKS
            or len(canonical([entries,output.get('platformInheritanceChecks',[]),output.get('platformTypeContracts',[])]))>MAX_CATALOG_BYTES):
        return 'platform_type_proof_projection_budget_exceeded'
    definitions, encodings, conflicts = {}, {}, set()
    for definition in entries:
        if not isinstance(definition, dict) or not isinstance(definition.get("id"), str): return invalid
        identity = definition["id"]; encoded = canonical(definition)
        if identity in encodings and encodings[identity] != encoded: conflicts.add(identity)
        else: definitions[identity], encodings[identity] = definition, encoded
    consumers = []; work = [value]; examined=0
    while work:
        examined+=1
        if examined>20_000:return 'platform_type_proof_traversal_budget_exceeded'
        item = work.pop()
        if isinstance(item, dict):
            if isinstance(item.get("platformInheritance"), dict): consumers.append(item)
            work.extend(v for k,v in item.items() if k != "platformInheritance" and isinstance(v,(dict,list)))
        elif isinstance(item,list): work.extend(item)
    if not consumers: return None
    record_id = output.get("id")
    record_location = "record" if output.get("kind") == "symbol" else "fragment"
    cache = {}; active = set()

    def get_record(identity, path=None):
        if identity == record_id: return output
        return lookup(identity, path) if lookup else None

    def bound(row, origin):
        return (isinstance(row,dict) and row.get("path") == origin.get("path")
                and row.get("sourceDigest") == origin.get("sourceDigest"))

    def contains(outer, inner):
        return (isinstance(outer,dict) and isinstance(inner,dict)
                and all(type(x) is int for x in (outer.get("charStart"),outer.get("charEnd"),inner.get("charStart"),inner.get("charEnd")))
                and 0 <= outer["charStart"] <= inner["charStart"] < inner["charEnd"] <= outer["charEnd"])

    def type_equal(a,b):
        def normalized(name):
            if not isinstance(name,str): return None
            return re.sub(r"^java\.lang\.(boolean|byte|char|short|int|long|float|double)(?=(?:\[\])*$)",r"\1",name)
        return normalized(a) is not None and normalized(a) == normalized(b)

    def erased(raw):
        if not isinstance(raw,str) or len(raw)>1024: return None
        depth=0; result=[]
        for ch in raw:
            if ch=='<': depth+=1
            elif ch=='>':
                depth-=1
                if depth<0:return None
            elif not depth: result.append(ch)
            if depth>32:return None
        if depth:return None
        return re.sub(r"\s+","",''.join(result)).replace('...','[]')

    def head(raw):
        spelling=erased(raw)
        return spelling.split('.',1)[0].split('[',1)[0] if spelling else None

    def source_heads(reference):
        result=set(); work=[reference]; depth=0
        while work:
            item=work.pop();depth+=1
            if depth>64:return set()
            if isinstance(item,dict):
                name=head(item.get('rawType',item.get('declaredType')))
                if name:result.add(name)
                work.extend(item.get('genericArguments',[]))
        return result

    def matches_spelling(raw, name, owner):
        return source_type_matches(raw, name, owner)

    def node_at(place):
        parent,_,slot=place.rpartition('/')
        return pointer(output,parent),parent,slot

    def actual_use_name(place):
        node,_,slot=node_at(place)
        if not isinstance(node,dict):return None
        name=node.get('name')
        if slot in {'receiverStaticType','receiverConstantOwnerStaticType','ownerStaticType'}:
            return name.rsplit('.',1)[0] if isinstance(name,str) and '.' in name else None
        return name if node.get('op')=='reference' else None

    def local_initializer_origin(definition, typed, origin):
        provider = get_record(origin.get('recordId'), origin.get('path'))
        if not isinstance(provider, dict): return missing
        binding = typed.get('localTypeBinding')
        if (typed.get('basis') != 'source_local_initializer_type' or typed.get('resolution') != 'resolved_static_type'
                or not isinstance(binding, dict)
                or not bound(provider, origin) or not bound(output, origin)
                or provider.get('kind') != 'semantic_fragment' or provider.get('category') != 'local_declaration'
                or provider.get('declaredType') != 'var' or provider.get('structuralOnly')
                or provider.get('dependencyClosure', {}).get('status') == 'invalidated'
                or provider.get('id') != binding.get('declarationFragmentId')
                or provider.get('localTypeInference') != binding
                or binding.get('status') != 'source_initializer_static_type'
                or binding.get('path') != origin.get('path') or binding.get('sourceDigest') != origin.get('sourceDigest')
                or binding.get('sourceRange') != provider.get('sourceRange')
                or binding.get('sourceEvidenceIds') != [provider.get('id')]
                or provider.get('id') not in typed.get('sourceEvidenceIds', [])
                or origin.get('selector') != '/expression/staticType'
                or actual_use_name(definition['consumer']) != provider.get('name')
                or binding.get('name') != provider.get('name')): return invalid
        upstream = pointer(provider, origin['selector'])
        upstream_ref = upstream.get('platformInheritance', {}) if isinstance(upstream, dict) else {}
        if (not isinstance(upstream, dict) or upstream.get('resolution') != 'resolved_static_type'
                or upstream_ref.get('proofId') != origin.get('proofId')
                or upstream_ref.get('checkIds') != definition.get('checkIds')
                or not type_equal(upstream.get('name'), definition.get('typeName'))
                or not type_equal(binding.get('inferredType'), definition.get('typeName'))): return invalid
        declaration, usage = provider.get('sourceRange'), output.get('sourceRange')
        scope, initializer = binding.get('lexicalScopeRange'), binding.get('initializerRange')
        lexical = binding.get('lexicalOwner', {})
        if (not contains(scope, declaration) or not contains(declaration, initializer) or not contains(scope, usage)
                or declaration['charEnd'] > usage['charStart']
                or lexical.get('kind') != 'indexed_named_type_callable'
                or provider.get('javaSourceOwner') != output.get('javaSourceOwner')
                or output.get('javaSourceOwner') != {key: lexical.get(key) for key in ('typeSymbolId', 'callableSymbolId')}
                or not any(r.get('resolution') == 'lexical_declaration_only'
                    and r.get('name') == provider.get('name')
                    and r.get('declarations') == [{'id': provider['id'], 'path': provider['path'],
                        'span': provider['span'], 'sourceDigest': provider['sourceDigest'], 'declaredType': 'var'}]
                    for r in output.get('references', []))): return invalid
        for prefix, kinds in (('type', {'Class', 'Interface', 'Record', 'Enum'}), ('callable', {'Method', 'Constructor'})):
            owner = get_record(lexical.get(prefix + 'SymbolId'), origin['path'])
            if (not bound(owner, origin) or owner.get('kind') != 'symbol' or owner.get('type') not in kinds
                    or owner.get('basis') != 'declared' or owner.get('structuralOnly')
                    or owner.get('sourceRange') != lexical.get(prefix + 'DeclarationRange')
                    or owner.get('declarationRange') != lexical.get(prefix + 'DeclarationRange')
                    or owner.get('bodyRange') != lexical.get(prefix + 'BodyRange')
                    or not contains(owner.get('bodyRange'), scope)): return invalid
        key = (provider['id'], origin['selector'])
        if key in proof_trail or len(proof_trail) >= 32: return 'platform_type_proof_cycle_or_depth_exceeded'
        _, reason = requirements(upstream, provider, lookup=lookup, api_validator=api_validator,
            allow_pending=allow_pending, _proof_trail=proof_trail + (key,), _complete_lookup=complete_lookup)
        return reason

    def origin_check(definition,typed):
        origin=definition.get('origin')
        if not isinstance(origin,dict):return missing
        if origin.get('kind') == 'local_initializer':
            return local_initializer_origin(definition, typed, origin)
        owner=get_record(origin.get('ownerId'),origin.get('path'))
        if owner is None:return pending_reason if allow_pending and origin.get('path')!=output.get('path') else missing
        if not bound(owner,origin) or owner.get('kind')!='symbol' or owner.get('type') not in {'Class','Interface','Record','Enum'}:return invalid
        kind=origin.get('kind'); place=definition['consumer']; node,node_path,slot=node_at(place)
        if record_location=='record' and re.fullmatch(r'/recordComponents/(0|[1-9][0-9]*)',place):node=typed
        if not isinstance(node,dict):return invalid
        reference=None; raw=None; expected_name=None; required_namespace='member_type'
        reference_range=None
        if kind in {'parameter','source_return','record_component','declaration','selected_field','loop_variable'}:
            provider=get_record(origin.get('recordId'),origin.get('path'))
            if provider is None:return pending_reason if allow_pending and origin.get('path')!=output.get('path') else missing
            if not bound(provider,origin):return invalid
            reference=pointer(provider,origin.get('selector'))
            reference_range=provider.get('sourceRange')
            if kind=='parameter':
                if (provider.get('type')!='Method' or provider.get('owner')!=owner.get('qualifiedName')
                        or not re.fullmatch(r'/parameterTypeReferences/(0|[1-9][0-9]*)',origin.get('selector',''))
                        or not isinstance(reference,dict) or actual_use_name(place)!=reference.get('name')
                        or typed.get('parameterName')!=reference.get('name')
                        or not contains(provider.get('bodyRange'),output.get('sourceRange'))):return invalid
                raw,expected_name=reference.get('rawType'),reference.get('resolvedType')
                if reference.get('resolution') not in {'resolved','primitive'} or not matches_spelling(raw,expected_name,owner):return invalid
            elif kind=='source_return':
                if (provider.get('type')!='Method' or provider.get('owner')!=owner.get('qualifiedName')
                        or origin.get('selector')!='/returnTypeReference' or not isinstance(reference,dict)
                        or node.get('op')!='call' or slot!='staticType'):return invalid
                call=get_record(origin.get('callsiteId'),output.get('path'))
                if call is None:return pending_reason if allow_pending else missing
                callee=node.get('callee',{}); called=callee.get('name','').rsplit('.',1)[-1]
                if (call.get('kind')!='callsite' or call.get('path')!=output.get('path') or call.get('sourceDigest')!=output.get('sourceDigest')
                        or call.get('resolution')!='exact' or call.get('target')!=provider.get('originalSymbolId')
                        or call.get('name')!=called):return invalid
                position=node.get('sourceInvocationSpan')
                if not isinstance(position,dict) or position.get('line')!=call.get('span',{}).get('lineStart') or position.get('column')!=call.get('column'):return invalid
                raw,expected_name=reference.get('rawType'),reference.get('resolvedType')
                if raw=='void' and reference.get('resolution')=='primitive' and expected_name=='java.lang.void':expected_name='void'
                if reference.get('resolution') not in {'resolved','primitive'} or not matches_spelling(raw,expected_name,owner):return invalid
            elif kind=='record_component':
                if (provider.get('type')!='Record' or provider.get('id')!=owner.get('id')
                        or not re.fullmatch(r'/recordComponents/(0|[1-9][0-9]*)',origin.get('selector',''))
                        or not isinstance(reference,dict) or reference.get('declarationStatus')!='declared'
                        or reference.get('typeResolution') not in {'resolved','primitive'}):return invalid
                raw,expected_name=reference.get('declaredType'),reference.get('type')
                if not matches_spelling(raw,expected_name,owner):return invalid
                reference_range=reference.get('sourceRange')
                if provider.get('id')!=output.get('id') and isinstance(reference.get('platformInheritance'),dict):
                    key=(provider.get('id'),origin.get('selector'))
                    if key in proof_trail or len(proof_trail)>=32:return 'platform_type_proof_cycle_or_depth_exceeded'
                    _, reason=requirements(reference,provider,lookup=lookup,api_validator=api_validator,
                        allow_pending=allow_pending,_proof_trail=proof_trail+(key,),_complete_lookup=complete_lookup)
                    if reason:return reason
                if record_location=='record':
                    if pointer(output,place) is not reference:return invalid
                elif slot=='accessorReturnStaticType':
                    component=node.get('staticAccessorBinding',{}).get('component',{})
                    if component.get('name')!=reference.get('name') or component.get('sourceRange')!=reference_range or component.get('recordType')!=provider.get('qualifiedName'):return invalid
                else:
                    field=node.get('staticFieldBinding',node.get('receiverStaticFieldBinding',{}))
                    if field.get('name')!=reference.get('name') or field.get('sourceRange')!=reference_range:return invalid
            elif kind in {'declaration','selected_field'}:
                if provider.get('kind')!='semantic_fragment' or origin.get('selector')!='/declaredType' or not isinstance(reference,str):return invalid
                raw=reference; expected_name=typed.get('name')
                use=actual_use_name(place)
                if use not in {provider.get('name'),'this.'+str(provider.get('name'))}:return invalid
                if kind=='selected_field':
                    field=node.get('staticFieldBinding',node.get('receiverStaticFieldBinding',{}))
                    if field.get('declarationFragmentId')!=provider.get('id') or field.get('sourceRange')!=reference_range:return invalid
                elif (output.get('javaSourceOwner',{}).get('typeSymbolId')!=owner.get('id')
                        or not any(d.get('id')==provider.get('id') for r in output.get('references',[]) if r.get('name')==use for d in r.get('declarations',[]))):
                    return invalid
                if not matches_spelling(raw,expected_name,owner):return invalid
            else:
                expression=provider.get('expression')
                if (provider.get('category')!='condition' or not isinstance(expression,dict)
                        or expression.get('op')!='enhanced_for' or origin.get('selector')!='/expression/variable'
                        or not isinstance(reference,dict)):return invalid
                raw=reference.get('declaredType'); expected_name=typed.get('name')
                body=expression.get('body',{})
                scope=typed.get('variableScope',{})
                if (actual_use_name(place)!=reference.get('name') or not isinstance(scope,dict)
                        or {key:scope.get(key) for key in ('charStart','charEnd')}!=body.get('sourceRange')
                        or not contains(body.get('sourceRange'),output.get('sourceRange'))):return invalid
                reference_range=reference.get('sourceRange')
                if not matches_spelling(raw,expected_name,owner) and expected_name!=raw:return invalid
            if not type_equal(expected_name,definition.get('typeName')) or not contains(owner.get('sourceRange'),reference_range):return invalid
        elif kind in {'syntax_type','static_import'}:
            if not contains(owner.get('sourceRange'),output.get('sourceRange')):return invalid
            if output.get('javaSourceOwner',{}).get('typeSymbolId') not in {None,owner.get('id')}:return invalid
            if kind=='static_import':
                if slot not in {'constantOwnerStaticType','receiverConstantOwnerStaticType'}:return invalid
                raw=actual_use_name(place)
                if not raw or '.' in raw:return invalid
                imported=[i for i in owner.get('typeImports',[]) if i.get('kind')=='static' and i.get('qualifiedName') in {definition['typeName']+'.'+raw,definition['typeName']+'.*'}]
                if not imported or not owner.get('typeImportCoverage',{}).get('complete'):return invalid
                required_namespace='field_or_member_type'
            else:
                if slot=='constructorStaticType' and node.get('op')=='construct':raw=node.get('type')
                elif slot=='staticType' and node.get('op')=='cast':raw=node.get('type')
                elif slot=='staticType' and node.get('op')=='literal' and node.get('binding')=='java.math.BigDecimal.String':raw='java.math.BigDecimal'
                elif slot in {'constantOwnerStaticType','receiverConstantOwnerStaticType'}:
                    use=actual_use_name(place)
                    raw=use.rsplit('.',1)[0] if isinstance(use,str) and '.' in use else None
                    required_namespace='field_or_member_type'
                elif slot=='ownerStaticType':raw=actual_use_name(place);required_namespace='field_or_member_type'
                else:return invalid
                if not matches_spelling(raw,definition.get('typeName'),owner):return invalid
            reference_range=output.get('sourceRange')
        else:return missing
        heads=source_heads(reference) if isinstance(reference,dict) else {head(raw)}
        if not heads or None in heads:return invalid
        expected_groups=[(owner,heads,required_namespace,reference_range)]
        if kind=='selected_field':
            use_owner=get_record(origin.get('useOwnerId'),output.get('path'))
            if (not isinstance(use_owner,dict) or use_owner.get('path')!=output.get('path')
                    or use_owner.get('sourceDigest')!=output.get('sourceDigest')
                    or output.get('javaSourceOwner',{}).get('typeSymbolId')!=use_owner.get('id')):return invalid
            expected_groups.append((use_owner,{provider.get('name')},'field_or_member_type',output.get('sourceRange')))
        groups={}
        for identity in definition.get('checkIds',[]):
            check=checks.get(identity)
            if not check:return invalid
            selected=[s for s in check.get('sourceScopes',[]) if s.get('qualifiedName')==check.get('ownerType')]
            if len(selected)!=1:return invalid
            namespace_owner=use_owner if kind=='selected_field' else owner
            namespace_names={provider.get('name')} if kind=='selected_field' else heads
            imports=namespace_owner.get('typeImports',[])
            imported_namespace=(required_namespace=='field_or_member_type' or kind=='selected_field') and (
                namespace_owner.get('typeImportCoverage',{}).get('complete') is True
                and selected[0].get('qualifiedName')+'.*' in {item.get('qualifiedName') for item in imports
                    if isinstance(item,dict) and item.get('kind')=='static'}
                and check.get('queriedName') in namespace_names and check.get('namespace')=='field_or_member_type')
            actual=get_record(selected[0].get('sourceEvidenceId'),selected[0].get('path'))
            if actual is None:
                # Initial index-backed extraction can verify its selected
                # import namespace before the external owner is staged. This
                # does not manufacture a delivered record; final lookup must
                # resolve and compare the actual owner and its catalog.
                if not complete_lookup and selected[0].get('path')!=output.get('path') and imported_namespace:
                    continue
                return pending_reason if allow_pending else missing
            matched=[]
            for group_owner,group_heads,group_namespace,group_range in expected_groups:
                if (check.get('queriedName') in group_heads and actual.get('path')==group_owner.get('path')
                        and actual.get('sourceDigest')==group_owner.get('sourceDigest')
                        and actual.get('qualifiedName')==check.get('ownerType')
                        and contains(actual.get('sourceRange'),group_range)
                        and (group_owner.get('qualifiedName')==actual.get('qualifiedName') or group_owner.get('qualifiedName','').startswith(actual.get('qualifiedName','')+'.'))):
                    matched.append(group_namespace)
            if not matched and imported_namespace:
                # Cross-namespace absence is authorized by the exact actual
                # caller import and the same queried value name only.
                if (actual.get('kind')=='symbol' and actual.get('type') in {'Class','Interface','Record','Enum'}
                        and actual.get('id')==selected[0].get('sourceEvidenceId')
                        and actual.get('qualifiedName')==check.get('ownerType')
                        and bound(actual,selected[0])
                        and actual.get('declarationHeaderRange')==selected[0].get('sourceRange')):
                    matched.append('field_or_member_type')
            if not matched:return invalid
            required='field_or_member_type' if 'field_or_member_type' in matched else 'member_type'
            namespace=check.get('namespace')
            if namespace not in ({'member_type'} if required=='member_type' else {'member_type','field_or_member_type'}):return invalid
            groups.setdefault((check['ownerType'],check['queriedName'],required),set()).add(namespace)
        if any(required=='field_or_member_type' and 'field_or_member_type' not in group for (_,_,required),group in groups.items()):return invalid
        return None

    def propagated_inputs(definition,typed):
        place=definition['consumer'];node,path,slot=node_at(place)
        if not isinstance(node,dict):return None
        operation=definition.get('operation')
        if operation != typed.get('basis','standard_api_contract' if 'contractId' in typed else 'UNKNOWN'):return None
        inputs=[]
        if operation in {'standard_api_return_signature','standard_api_contract','record_accessor_result'}:
            if node.get('op')!='call':return None
            callee=node.get('callee',{})
            if callee.get('op')=='member':receiver=path+'/callee/receiver/staticType'
            elif 'receiverStaticType' in callee:receiver=path+'/callee/receiverStaticType'
            else:receiver=path+'/callee/ownerStaticType'
            inputs=[receiver]+[path+'/arguments/'+str(i)+'/staticType' for i in range(len(node.get('arguments',[])))]
            if operation=='record_accessor_result':
                inputs=[path+'/accessorReturnStaticType',receiver]
                if not type_equal(pointer(output,inputs[0]).get('name') if isinstance(pointer(output,inputs[0]),dict) else None,definition['typeName']):return None
            else:
                binding=node.get('staticContract',{})
                catalog=[c for c in output.get('standardApiContracts',[]) if c.get('id')==binding.get('contractId')]
                if not catalog or any(canonical(c)!=canonical(catalog[0]) for c in catalog):return None
                entry=catalog[0];owner_type=pointer(output,receiver)
                arguments=[pointer(output,p) for p in inputs[1:]]
                callback=binding.get('callbackBinding',{})
                if (len(arguments)==1 and arguments[0] is None
                        and callback.get('basis')=='unique_standard_method_and_lambda_arity'):
                    expression=node.get('arguments',[None])[0]
                    formal=callback.get('targetFunctionalInterface')
                    arity={'java.util.function.Function':1,'java.util.function.BiConsumer':2}.get(formal)
                    parameters=expression.get('parameters',[]) if isinstance(expression,dict) else []
                    names=[p.get('name') if isinstance(p,dict) and p.get('op')=='reference'
                        else p[0] if isinstance(p,list) and len(p)==1 else None for p in parameters]
                    if (not isinstance(expression,dict) or expression.get('op')!='lambda' or arity is None
                            or len(names)!=arity or any(not isinstance(n,str) for n in names) or len(set(names))!=arity
                            or callback.get('arity')!=arity or callback.get('callbackArgument')!=0
                            or callback.get('genericTypes')!='UNKNOWN' or callback.get('bodyTypeCheck')!='UNKNOWN'
                            or callback.get('bodyExecution')!='UNKNOWN'):return None
                    body=expression.get('body',{})
                    if body.get('op')=='body_reference' and callback.get('bodyId')!=body.get('bodyId'):return None
                    arguments=[{'name':formal}]
                if not isinstance(owner_type,dict) or any(not isinstance(arg,dict) for arg in arguments):return None
                name=callee.get('name','').rsplit('.',1)[-1];static=receiver.endswith('/ownerStaticType')
                if not api_validator or not api_validator(entry,owner_type.get('name'),name,static,[a.get('name') for a in arguments]):return None
                if not type_equal(entry.get('result',{}).get('type'),definition['typeName']):return None
                operands=binding.get('operands',[]);expected=([('receiver',owner_type.get('name'))] if not static else [])+[('argument',a.get('name')) for a in arguments]
                if len(operands)!=len(expected) or any(o.get('role')!=role or not type_equal(o.get('actualType'),name) for o,(role,name) in zip(operands,expected)):return None
                offset=0 if static else 1
                if any(o.get('argumentIndex')!=i or o.get('formalType')!=entry['parameterTypes'][i]
                    for i,o in enumerate(operands[offset:])):return None
        elif operation=='standard_named_constant':
            parent=path+('/receiverConstantOwnerStaticType' if slot=='receiverStaticType' else '/constantOwnerStaticType')
            owner_type=pointer(output,parent);constant=node.get('receiverStandardConstant' if slot=='receiverStaticType' else 'standardConstant',{})
            if not isinstance(owner_type,dict) or not type_equal(owner_type.get('name'),definition['typeName']) or constant.get('declaringType')!=owner_type.get('name'):return None
            use=actual_use_name(place)
            if not isinstance(use,str) or use.rsplit('.',1)[-1]!=constant.get('member'):return None
            inputs=[parent]
        elif operation=='standard_constructor_signature':
            if node.get('op')!='construct':return None
            inputs=[path+'/constructorStaticType']+[path+'/arguments/'+str(i)+'/staticType' for i in range(len(node.get('arguments',[])))]
            owner_type=pointer(output,inputs[0])
            if not isinstance(owner_type,dict) or not type_equal(owner_type.get('name'),definition['typeName']):return None
            args=[pointer(output,p) for p in inputs[1:]]
            if (any(not isinstance(a,dict) for a in args) or not api_validator
                    or not api_validator(node.get('staticConstructorBinding'),owner_type['name'],'<init>',False,[a.get('name') for a in args])):return None
        elif operation in {'java_unary_numeric_promotion','java_boolean_negation'}:
            if node.get('op')!='unary':return None
            inputs=[path+'/operand/staticType'];operand=pointer(output,inputs[0])
            if not isinstance(operand,dict):return None
            if operation=='java_boolean_negation':
                if node.get('operator')!='!' or operand.get('name')!='boolean':return None
            elif (operand.get('name') not in {'byte','short','char','int','long','float','double'}
                    or node.get('operator') not in {'+','-','~'}
                    or (node.get('operator')=='~' and operand.get('name') in {'float','double'})):return None
            expected='boolean' if operation=='java_boolean_negation' else 'int' if operand.get('name') in {'byte','short','char'} else operand.get('name')
            if not type_equal(expected,definition['typeName']):return None
        elif operation in {'java_numeric_comparison','java_binary_numeric_promotion'}:
            if node.get('op')!='binary':return None
            if node.get('operator') not in ({'==','!=','<','<=','>','>='} if operation=='java_numeric_comparison' else {'+','-','*','/','%'}):return None
            inputs=[path+'/left/staticType',path+'/right/staticType'];types=[pointer(output,p) for p in inputs]
            if any(not isinstance(t,dict) or t.get('name') not in {'byte','short','char','int','long','float','double'} for t in types):return None
            names={t['name'] for t in types};expected='boolean' if operation=='java_numeric_comparison' else next((n for n in ('double','float','long') if n in names),'int')
            if not type_equal(expected,definition['typeName']):return None
        elif operation=='identical_conditional_operand_types':
            if node.get('op')!='conditional':return None
            inputs=[path+'/then/staticType',path+'/else/staticType']
            if any(not isinstance(pointer(output,p),dict) or not type_equal(pointer(output,p).get('name'),definition['typeName']) for p in inputs):return None
        else:return None
        return [p for p in inputs if isinstance(pointer(output,p),dict) and isinstance(pointer(output,p).get('platformInheritance'),dict)]

    def visit(typed,trail=()):
        ref=typed.get('platformInheritance',{});identity=ref.get('proofId')
        if identity in conflicts:return 'platform_inheritance_definition_conflict'
        if not isinstance(identity,str) or ref.get('schemaVersion')!=2 or ref.get('proofLocation')!=record_location+'.platformTypeProofs':return missing
        definition=definitions.get(identity)
        if (not definition or definition.get('unsupportedReason') or identity!=_proof_id(record_id,definition.get('consumer'))
                or pointer(output,definition.get('consumer')) is not typed
                or definition.get('checkIds')!=ref.get('checkIds') or definition.get('typeName')!=_consumer_type(typed,output)):return invalid
        # Cache only the definition's dependency validation. Every use must
        # first match its actual consumer slot, role, type and check references;
        # a validated donor ID cannot authorize a different typed object.
        if identity in cache:return cache[identity]
        if identity in active or len(trail)>=32:return 'platform_type_proof_cycle_or_depth_exceeded'
        active.add(identity)
        if definition.get('mode')=='direct':reason=origin_check(definition,typed)
        elif definition.get('mode')=='propagated':
            expected=propagated_inputs(definition,typed);parents=definition.get('parents')
            if expected is None or not isinstance(parents,list) or [p.get('consumer') for p in parents]!=expected:
                reason=invalid
            else:
                reason=None; inherited=set()
                for parent in parents:
                    target=pointer(output,parent.get('consumer'))
                    if not isinstance(target,dict) or target.get('platformInheritance',{}).get('proofId')!=parent.get('proofId'):
                        reason=invalid;break
                    reason=visit(target,trail+(identity,))
                    if reason:break
                    inherited.update(target['platformInheritance']['checkIds'])
                if not reason and sorted(inherited)!=definition.get('checkIds'):reason=invalid
        else:reason=invalid
        active.discard(identity);cache[identity]=reason
        return reason
    for consumer in consumers:
        reason=visit(consumer)
        if reason:return reason
    return None


def requirements(value, output, *, lookup=None, api_validator=None, allow_pending=False, _proof_trail=(), _complete_lookup=True):
    """Malformed inline metadata cannot retain positive derived evidence."""
    try:
        return _requirements(value,output,lookup=lookup,api_validator=api_validator,
            allow_pending=allow_pending,_proof_trail=_proof_trail,_complete_lookup=_complete_lookup)
    except (TypeError,ValueError,KeyError,AttributeError,RecursionError):
        return [], 'platform_type_consumer_binding_invalid'


def _requirements(value, output, *, lookup=None, api_validator=None, allow_pending=False, _proof_trail=(), _complete_lookup=True):
    """Validate inline contracts and return only source declaration dependencies.

    Catalog and lookup identities are inline definitions, never stored-record IDs.
    The bounded direct-name catalog is checked against the emitted source
    type. It does not model member bodies or a complete Java type system.
    ``_complete_lookup=False`` is reserved for initial in-process extraction;
    consumers and snapshot finalization default to strict delivered records.
    """
    field_failure = _selected_field_requirements(value, output, lookup, allow_pending)
    if field_failure: return [], field_failure
    composition_validator = getattr(api_validator, "validate_composition", None)
    if composition_validator:
        failure = composition_validator(value, output, lookup=lookup, allow_pending=allow_pending)
        if failure: return [], failure
    used, source_value_checks = set(), set()
    pending = [value]; examined=0
    while pending:
        examined+=1
        if examined>20_000:return [], 'platform_type_proof_traversal_budget_exceeded'
        item = pending.pop()
        if isinstance(item, dict):
            ref = item.get("platformInheritance")
            if isinstance(ref, dict):
                if ref.get("catalogLocation") != ("record" if output.get("kind") == "symbol" else "fragment") + ".platformInheritanceChecks":
                    return [], "platform_inheritance_definition_invalid"
                if ref.get('proofScope') not in {None, 'source_value_name_absence'}:
                    return [], 'platform_type_consumer_binding_invalid'
                identities=ref.get('checkIds')
                if (not isinstance(identities,list) or not identities or len(identities)>MAX_CHECKS
                        or any(not isinstance(identity,str) for identity in identities)):
                    return [], 'platform_type_consumer_binding_invalid'
                used.update(identities)
                if ref.get('proofScope')=='source_value_name_absence':source_value_checks.update(identities)
            pending.extend(item.values())
        elif isinstance(item, list): pending.extend(item)
    if not used: return [], None
    def definitions(entries):
        # Equal canonical definitions may be repeated, but a conflicting ID
        # never chooses a winner by array order. Keep conflicts local to the
        # referenced ID so independent sibling proofs can remain supported.
        if not isinstance(entries, list) or len(entries) > MAX_CHECKS: return {}, set(), False
        table, encoded, conflicts = {}, {}, set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                return {}, set(), False
            identity = entry["id"]
            try:
                body = canonical(entry)
            except (TypeError, ValueError):
                return {}, set(), False
            if identity in encoded and encoded[identity] != body:
                conflicts.add(identity)
            else:
                table[identity], encoded[identity] = entry, body
        return table, conflicts, True

    checks, check_conflicts, checks_valid = definitions(output.get("platformInheritanceChecks", []))
    catalog, catalog_conflicts, catalog_valid = definitions(output.get("platformTypeContracts", []))
    if not checks_valid or not catalog_valid:
        return [], "platform_inheritance_definition_invalid"
    required = {}
    for identity in used:
        if identity in check_conflicts:
            return [], "platform_inheritance_definition_conflict"
        check = checks.get(identity)
        if not check or check.get("status") != "absent" or check.get("transitiveInventoryComplete") is not True:
            return [], "platform_inheritance_definition_unavailable"
        if identity in source_value_checks and (check.get('catalogIds') or check.get('namespace')!='field_or_member_type'):
            return [], 'platform_type_consumer_binding_invalid'
        data = {k: v for k, v in check.items() if k != "id"}
        if identity != "platform-lookup:" + hashlib.sha256(canonical(data)).hexdigest()[:24]:
            return [], "platform_inheritance_definition_invalid"
        for key in check.get("catalogIds", []):
            if key in catalog_conflicts:
                return [], "platform_inheritance_definition_conflict"
            entry = catalog.get(key)
            expected = contract(entry.get("qualifiedName")) if entry else None
            if not expected or canonical(entry) != canonical(expected):
                return [], "platform_inheritance_definition_invalid"
            if check["queriedName"] in entry["memberTypes"] or (check["namespace"] == "field_or_member_type" and check["queriedName"] in entry["fields"]):
                return [], "platform_inherited_name_not_absent"
        for scope in check.get("sourceScopes", []):
            inventory = scope.get("memberInventory", {})
            if (inventory.get("memberTypes") != "complete"
                    or (check.get("namespace") == "field_or_member_type" and inventory.get("fields") != "complete")
                    or type(inventory.get("observedDirectDeclarationRegions")) is not int
                    or not 0 <= inventory["observedDirectDeclarationRegions"] <= MAX_SOURCE_MEMBERS):
                return [], "platform_source_member_inventory_unverified"
            names = inventory.get("fieldNames")
            if (not isinstance(names, list) or len(names) > MAX_SOURCE_MEMBERS
                    or any(not isinstance(name, str) or not declaration_identifier(name) for name in names)
                    or names != sorted(set(names))
                    or check.get("namespace") == "field_or_member_type" and check.get("queriedName") in names):
                return [], "platform_source_member_inventory_unverified"
            source = scope["sourceEvidenceId"]
            if lookup is not None:
                actual = lookup(source, scope.get("path"))
                # Extraction can see an indexed external owner before its
                # record is staged. Only the final snapshot lookup is an
                # authoritative delivered-record denominator. Same-file and
                # all final consumer checks always require the actual record.
                if actual is None and (_complete_lookup or scope.get("path") == output.get("path")):
                    return [], "dependency_pending_snapshot_finalization" if allow_pending else "platform_type_origin_not_emitted"
                if actual is not None and (actual.get("id") != source or actual.get("kind") != "symbol"
                        or actual.get("qualifiedName") != scope.get("qualifiedName") or actual.get("type") != scope.get("kind")
                        or actual.get("path") != scope.get("path") or actual.get("sourceDigest") != scope.get("sourceDigest")
                        or actual.get("declarationHeaderRange") != scope.get("sourceRange")
                        or actual.get("directMemberInventory") != inventory):
                    return [], "platform_source_member_inventory_unverified"
            proof = {**scope, "parents": [edge for edge in check["parentEdges"] if edge.get("fromSourceId") == source]}
            if source in required and required[source] != proof:
                return [], "platform_inheritance_definition_invalid"
            required[source] = proof
    proof_failure = _validate_type_proofs(value, output, checks, lookup, api_validator, allow_pending, _proof_trail, _complete_lookup)
    return ([], proof_failure) if proof_failure else (list(required.values()), None)
