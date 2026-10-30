"""Bounded Java statement structure; no source execution or semantic guessing.

The scanner emits flat source ranges and context references. Source order is not
claimed as observed runtime order, and a call's effect is always unresolved.
"""
from __future__ import annotations

MAX_FLOW_DEPTH = 96
CONTROL = {"if", "while", "for", "switch", "catch", "synchronized"}


def _enum_constants(tokens, parens, braces):
    """Recognize only a grammatically delimited enum constant prefix.

    Argument and optional constant-class bodies are source ranges. No enum
    member vocabulary, initializer value or constructor target is inferred.
    """
    values = [token.value for token in tokens]
    enums = []
    for start, token in enumerate(tokens[:-1]):
        if token.value != "enum" or tokens[start + 1].kind != "name":
            continue
        opening = start + 2
        while opening < len(tokens) and values[opening] not in {"{", ";", "="}:
            opening += 1
        if opening not in braces:
            continue
        boundary, cursor, constants = braces[opening], opening + 1, []
        while cursor < boundary and values[cursor] != ";":
            first = cursor
            # Annotation values are still redacted by the semantic parser.
            while cursor < boundary and values[cursor] == "@":
                cursor += 1
                if cursor >= boundary or tokens[cursor].kind != "name": break
                cursor += 1
                while cursor + 1 < boundary and values[cursor] == "." and tokens[cursor + 1].kind == "name": cursor += 2
                if cursor in parens: cursor = parens[cursor] + 1
            if cursor >= boundary or tokens[cursor].kind != "name":
                constants = []
                break
            name_index = cursor
            cursor += 1
            argument_end = cursor
            if cursor in parens:
                argument_end = parens[cursor] + 1
                cursor = argument_end
            body = cursor if cursor in braces else None
            if body is not None: cursor = braces[body] + 1
            if cursor < boundary and values[cursor] not in {",", ";"}:
                constants = []
                break
            constants.append({"start": first, "end": cursor - 1, "nameIndex": name_index,
                "argumentEnd": argument_end, "constantBody": body,
                "enumStart": start, "enumBody": opening, "enumName": values[start + 1]})
            if cursor < boundary and values[cursor] == ",":
                cursor += 1
                continue
            break
        if constants:
            enums.append({"start": opening + 1, "end": cursor + (cursor < boundary and values[cursor] == ";"),
                          "constants": constants})
    return enums


def scan(tokens, parens, braces, *, body_range=None, member_range=None):
    values = [t.value for t in tokens]
    n = len(tokens)
    enum_regions = _enum_constants(tokens, parens, braces) if body_range is None and member_range is None else []
    enum_regions_by_start = {region["start"]: region for region in enum_regions}
    enum_bodies = {item["constantBody"] for region in enum_regions for item in region["constants"] if item["constantBody"] is not None}
    methods = {}
    for opening, closing in sorted(parens.items()):
        if opening > closing or opening < 1 or values[opening - 1] in CONTROL:
            continue
        if tokens[opening - 1].kind != "name" or (opening > 1 and values[opening - 2] in {".", "new"}):
            continue
        following = closing + 1
        if following < n and values[following] == "throws":
            following += 1
            while following < n and (tokens[following].kind == "name" or values[following] in {".", ","}):
                following += 1
        if following < n and values[following] == "{" and following in braces:
            # A record header is a type declaration, not an executing callable.
            if opening > 1 and values[opening - 2] == "record":
                continue
            if following in enum_bodies:
                continue
            methods[following] = {"name": values[opening - 1], "start": opening - 1,
                                  "end": braces[following], "body": following,
                                  "parameterStart": opening + 1, "parameterEnd": closing}
    # Compact record constructors have no parenthesized parameter list.
    record_names = {values[i + 1] for i, v in enumerate(values[:-1]) if v == "record"}
    for opening in braces:
        if opening > 0 and values[opening - 1] in record_names and opening not in methods:
            methods[opening] = {"name": values[opening - 1], "start": opening - 1,
                                  "end": braces[opening], "body": opening,
                                  "parameterStart": opening, "parameterEnd": opening}
    nodes = []
    serial = 0

    def emit(kind, start, end, exstart=None, exend=None, contexts=(), owner=None, **extra):
        nonlocal serial
        serial += 1
        node = {"kind": kind, "start": start, "end": max(start, end),
                "expressionStart": start if exstart is None else exstart,
                "expressionEnd": end if exend is None else exend,
                "contexts": list(contexts), "owner": owner, "sequence": serial, **extra}
        nodes.append(node)
        return node

    def context(node, branch, **extra):
        return {"start": node["start"], "end": node["end"], "kind": node["kind"],
                "branch": branch, **extra}

    def end_statement(start, limit):
        pos = start
        while pos < limit:
            if values[pos] == ";":
                return pos
            if values[pos] == "(" and pos in parens:
                pos = parens[pos] + 1
            elif values[pos] == "{" and pos in braces:
                pos = braces[pos] + 1
            else:
                pos += 1
        return limit

    def sequence(start, limit, contexts, owner, depth):
        pos = start
        active = list(contexts)
        abrupt = False
        while pos < limit:
            following, stops, continuation = statement(pos, limit, active, owner, depth + 1)
            if following <= pos:
                following = pos + 1
            pos = following
            if stops:
                abrupt = True
                active = active + [{"kind": "completion", "branch": "unreachable_after_abrupt_completion",
                                    "start": max(start, pos - 1), "end": max(start, pos - 1)}]
            active.extend(continuation)
        return abrupt

    def statement(start, limit, contexts, owner, depth):
        if depth > MAX_FLOW_DEPTH:
            emit("unsupported_region", start, max(start, limit - 1), contexts=contexts, owner=owner,
                 reason="control_flow_depth_exceeded")
            return limit, False, []
        value = values[start]
        if value == ";":
            return start + 1, False, []
        if value == "{" and start in braces:
            close = min(braces[start], limit)
            return close + 1, sequence(start + 1, close, contexts, owner, depth), []
        if value == "if" and start + 1 in parens:
            close = parens[start + 1]
            node = emit("condition", start, close, start + 2, close, contexts, owner, controlKind="if")
            following, yes_stop, _ = statement(close + 1, limit, contexts + [context(node, "true")], owner, depth + 1)
            no_stop = False
            if following < limit and values[following] == "else":
                emit("else", following, following, following, following, contexts, owner, conditionStart=start)
                following, no_stop, _ = statement(following + 1, limit, contexts + [context(node, "false")], owner, depth + 1)
            continuing = []
            if yes_stop != no_stop:
                continuing = [context(node, "false" if yes_stop else "true", relation="prior_branch_abrupt_completion")]
            return following, yes_stop and no_stop, continuing
        if value in {"while", "for", "synchronized"} and start + 1 in parens:
            close = parens[start + 1]
            node = emit("loop" if value != "synchronized" else "synchronized", start, close, start + 2, close,
                        contexts, owner, controlKind=value)
            following, _, _ = statement(close + 1, limit, contexts + [context(node, "body")], owner, depth + 1)
            node["bodyStart"] = close + 1
            node["bodyEnd"] = following
            return following, False, []
        if value == "do":
            node = emit("loop", start, start, start, start, contexts, owner, controlKind="do")
            following, _, _ = statement(start + 1, limit, contexts + [context(node, "body")], owner, depth + 1)
            if following < limit and values[following] == "while" and following + 1 in parens:
                close = parens[following + 1]
                emit("condition", following, close, following + 2, close, contexts, owner,
                     controlKind="do_while", loopStart=start)
                following = close + 1 + (close + 1 < limit and values[close + 1] == ";")
            return following, False, []
        if value == "try":
            body = start + 1
            if body in parens:
                resource_end = parens[body]
                node = emit("try", start, resource_end, body + 1, resource_end, contexts, owner, resources=True)
                body = resource_end + 1
            else:
                node = emit("try", start, start, start, start, contexts, owner)
            following, _, _ = statement(body, limit, contexts + [context(node, "try")], owner, depth + 1)
            node["bodyEnd"] = following
            handler_index = 0
            while following < limit and values[following] == "catch" and following + 1 in parens:
                close = parens[following + 1]
                handler = emit("catch", following, close, following + 2, close, contexts, owner,
                               tryStart=start, handlerIndex=handler_index)
                following, _, _ = statement(close + 1, limit, contexts + [context(node, "catch", handlerStart=handler["start"], handlerIndex=handler_index)], owner, depth + 1)
                handler["bodyEnd"] = following
                handler_index += 1
            if following < limit and values[following] == "finally":
                final = emit("finally", following, following, following, following, contexts, owner, tryStart=start)
                following, _, _ = statement(following + 1, limit, contexts + [context(node, "finally", handlerStart=final["start"])], owner, depth + 1)
            return following, False, []
        if value == "switch" and start + 1 in parens:
            close = parens[start + 1]
            body = close + 1
            if body in braces:
                node = emit("switch", start, close, start + 2, close, contexts, owner)
                boundary = braces[body]
                pos = body + 1
                labels = []
                arm_contexts = []
                while pos < boundary:
                    if values[pos] in {"case", "default"}:
                        sep = pos + 1
                        nested = 0
                        while sep < boundary:
                            if values[sep] in {"(", "["}: nested += 1
                            elif values[sep] in {")", "]"}: nested -= 1
                            elif nested == 0 and values[sep] in {":", "->"}: break
                            sep += 1
                        case = emit("switch_case", pos, min(sep, boundary - 1), pos + 1, sep,
                                    contexts + [context(node, "case")], owner,
                                    default=values[pos] == "default", style=values[sep] if sep < boundary else "unknown")
                        if sep >= boundary:
                            return boundary + 1, False, []
                        if values[sep] == "->": labels = []
                        arm_contexts = []
                        labels.append(context(case, "match" if values[sep] == "->" else "match_or_prior_fallthrough",
                                              fallthroughPossible=values[sep] == ":", logic="ANY", group="switch_labels"))
                        pos = sep + 1
                    else:
                        pos, stopped, continuation = statement(pos, boundary, contexts + [context(node, "case")] + labels + arm_contexts, owner, depth + 1)
                        if stopped:
                            # A proven abrupt completion cannot fall through to
                            # a later label. Nested-loop breaks return False at
                            # this level and therefore do not clear case paths.
                            labels = []
                            arm_contexts = []
                        else:
                            arm_contexts.extend(continuation)
                return boundary + 1, False, []
        # Labels on loops/blocks retain the source label, never its runtime target.
        if start + 1 < limit and tokens[start].kind == "name" and values[start + 1] == ":":
            node = emit("label", start, start + 1, start, start + 1, contexts, owner)
            return statement(start + 2, limit, contexts + [context(node, "labeled")], owner, depth + 1)
        end = end_statement(start, limit)
        kind = value if value in {"return", "throw", "break", "continue", "assert", "yield"} else "statement"
        emit(kind, start, min(end, limit - 1), start + 1 if kind != "statement" else start, end, contexts, owner)
        return min(end + 1, limit), kind in {"return", "throw", "break", "continue"}, []

    # Callable bodies are scanned independently. Nested callable bodies are not
    # claimed to execute merely because their declaration is encountered.
    if body_range is not None:
        sequence(body_range[0], body_range[1], [], None, 0)
    elif member_range is None:
        for body, method in sorted(methods.items()):
            sequence(body + 1, method["end"], [], method, 0)
    # Field initializers and abstract signatures outside callable bodies.
    pos = member_range[0] if member_range else 0
    first = pos
    member_end = member_range[1] if member_range else n

    def has_initializer(start, end):
        # Annotation arguments may contain '='; they are not field assignment.
        cursor = start
        while cursor < end:
            if values[cursor] == "(" and cursor in parens:
                cursor = parens[cursor] + 1
                continue
            if values[cursor] == "=":
                return True
            cursor += 1
        return False

    while body_range is None and pos < member_end:
        enum_region = enum_regions_by_start.get(pos)
        if enum_region is not None:
            for item in enum_region["constants"]:
                emit("enum_constant", item["start"], item["end"], item["nameIndex"], item["end"] + 1,
                     **{key: value for key, value in item.items() if key not in {"start", "end"}})
            pos = enum_region["end"]
            first = pos
            continue
        if pos in methods:
            pos = methods[pos]["end"] + 1
            first = pos
            continue
        if values[pos] == "{" and pos in braces:
            # Keep initializer braces inside a declaration intact.
            if has_initializer(first, pos):
                pos = braces[pos] + 1
                continue
            first = pos + 1
        elif values[pos] == "}":
            first = pos + 1
        elif values[pos] == ";":
            if first < pos and values[first] not in {"package", "import"}:
                emit("statement", first, pos, first, pos)
            first = pos + 1
        pos += 1
    nodes.sort(key=lambda node: (node["start"], node["end"], node["sequence"]))
    for index, node in enumerate(nodes):
        node["sequence"] = index
    return nodes, methods
