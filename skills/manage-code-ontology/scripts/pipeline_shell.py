"""Non-executing shell structure and command-boundary analysis.

Bash/POSIX shell syntax is recognized conservatively. Expansions, eval, sourced
runtime state and command substitutions remain unresolved. Arguments, variable
values, heredoc bodies and command output are never stored as ontology facts.
"""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

import code_ontology_core as core

VERSION = "shell-structure-1"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
COMMAND = re.compile(r"[A-Za-z_][A-Za-z0-9_.+-]*")
RELATIVE = re.compile(r"(?:\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:sh|bash|zsh|ksh|ps1|psm1)")


def _dynamic_expansion(text):
    single, double, index = False, False, 0
    while index < len(text):
        char = text[index]
        if char == "\\" and not single:
            index += 2
            continue
        if char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif char == "#" and not single and not double and (index == 0 or text[index - 1].isspace()):
            return False
        elif not single and (char == "`" or text.startswith("$(", index) or (not double and text[index:index+2] in {"<(", ">("})):
            return True
        index += 1
    return False


def _literal(text):
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        return text[1:-1]
    return text


def analyze_shell(relative_path, source, source_digest, *, max_records=20000, max_ast_nodes=20000, **_opts):
    from pipeline_adapters import AdapterError, identifier
    if not core._portable_relative_path(relative_path) or not re.fullmatch(r"[a-f0-9]{64}", source_digest):
        raise AdapterError("invalid_shell_identity")
    if len(source.encode("utf-8")) > core.MAX_SOURCE_BYTES:
        raise AdapterError("shell_source_budget")
    powershell = PurePosixPath(relative_path).suffix.lower() in {".ps1", ".psm1", ".psd1"}
    language = "PowerShell" if powershell else "Shell"
    module_path = relative_path.split("/", 1)[0] if "/" in relative_path else "."
    module = identifier("module", module_path)
    records, imports, exports = [], [], []
    limitations = {"shell_expansion_and_environment_unresolved", "external_command_runtime_unknown",
                   "shell_policy_semantics_unsupported"}
    count = 0

    def add(kind, name, line, **fields):
        if len(records) >= max_records:
            raise AdapterError("shell_record_budget")
        record = {"id": identifier(relative_path, kind, name, line, len(records)),
                  "kind": kind, "name": name, "path": relative_path, "language": language,
                  "module": module, "modulePath": module_path,
                  "span": {"lineStart": line, "lineEnd": line}, "sourceDigest": source_digest,
                  "ruleVersion": VERSION, "basis": "declared", "status": "runtime_unknown"}
        record.update(fields)
        records.append(record)
        return record["id"]

    file_id = add("symbol", PurePosixPath(relative_path).name, 1, type="Script", id=identifier("file", relative_path))
    functions = {}
    pending_calls = []
    owner = file_id
    depth = 0
    function_depth = None
    heredocs = []
    logical = ""
    first_line = 1
    pipeline_left = None

    def edge(subject, predicate, target, line, resolution="declared_candidate"):
        return add("assertion", predicate, line, subject=subject, predicate=predicate,
                   object=target, resolution=resolution, limitations=["execution_not_observed"])

    if powershell:
        limitations.add("powershell_declarations_only")
        # Quote/comment masking prevents documentation examples from becoming
        # declarations. Here strings are explicitly skipped in their entirety.
        block = False
        here = None
        for number, line in enumerate(source.splitlines(), 1):
            if here:
                if line.strip() == here:
                    here = None
                continue
            if re.search(r"@['\"]\s*$", line):
                here = "'@" if "@'" in line else '"@'
                limitations.add("powershell_here_string_ignored")
                continue
            out = []
            quote = None
            i = 0
            while i < len(line):
                if block:
                    end = line.find("#>", i)
                    if end < 0:
                        break
                    i, block = end + 2, False
                elif quote:
                    if line[i] == "`":
                        i += 2
                    elif line[i] == quote:
                        quote = None
                        i += 1
                    else:
                        i += 1
                elif line.startswith("<#", i):
                    block, i = True, i + 2
                elif line[i] == "#":
                    break
                elif line[i] in "'\"":
                    quote, i = line[i], i + 1
                    out.append(" ")
                else:
                    out.append(line[i])
                    i += 1
            masked = "".join(out)
            for match in re.finditer(r"(?i)(?:^|[;{}])\s*(function|filter|class|enum)\s+([A-Za-z_][\w-]*)", masked):
                name = match.group(2)
                symbol = add("symbol", name, number, type=match.group(1).title(), qualifiedName=name)
                edge(file_id, "DECLARES", symbol, number, "syntax")
                exports.append(name)
            for match in re.finditer(r"(?i)(?:^|;)\s*(Import-Module|using\s+module)\s+([A-Za-z_][\w.-]*)\s*(?:$|;)", masked):
                imports.append({"module": match.group(2), "name": "", "alias": ""})
                target = add("symbol", match.group(2), number, type="ExternalModule")
                edge(file_id, "IMPORTS", target, number)
            if quote or block:
                limitations.add("powershell_multiline_or_comment_boundary")
    else:
        for number, raw in enumerate(source.splitlines(), 1):
            if heredocs:
                terminator, strip_tabs = heredocs[0]
                if (raw.lstrip("\t") if strip_tabs else raw) == terminator:
                    heredocs.pop(0)
                continue
            if not logical:
                first_line = number
            logical += raw
            if logical.endswith("\\"):
                logical = logical[:-1] + " "
                if len(logical) > 65536:
                    raise AdapterError("shell_logical_line_budget")
                continue
            # Substitution bodies are not misinterpreted as top-level commands.
            # Supporting nested expansion requires a full shell grammar; record
            # this boundary explicitly rather than guessing its execution path.
            if _dynamic_expansion(logical):
                add("framework", "DynamicSubstitution", first_line, type="ExecutionBoundary", resolution="unresolved")
                limitations.add("shell_dynamic_substitution")
                logical = ""
                continue
            try:
                lexer = shlex.shlex(logical, posix=False, punctuation_chars="();|&<>{}")
                lexer.whitespace_split = True
                tokens = []
                for item in lexer:
                    if re.fullmatch(r"[();|&<>{}]+", item):
                        tokens.extend(re.findall(r"\(\)|<<<|<<|>>|&&|\|\||\|&|;;|[();|&<>{}]", item))
                    else:
                        tokens.append(item)
            except ValueError:
                limitations.add("shell_multiline_quote_or_unsupported_syntax")
                # Without the quote state, later text could be string data.
                # Never resume scanning it as executable shell syntax.
                break
            logical = ""
            count += len(tokens)
            if count > max_ast_nodes:
                raise AdapterError("shell_token_budget")
            i = 0
            expect_command = True
            last_command = None
            while i < len(tokens):
                token = tokens[i]
                if token.startswith("<<"):
                    if i + 1 < len(tokens) and re.fullmatch(r"-?[A-Za-z_][A-Za-z0-9_.-]*", _literal(tokens[i + 1])):
                        delimiter = _literal(tokens[i + 1])
                        heredocs.append((delimiter.lstrip("-"), token.endswith("-") or delimiter.startswith("-")))
                        limitations.add("heredoc_body_not_collected")
                        i += 2
                        continue
                    limitations.add("dynamic_heredoc_unresolved")
                    # Unrecognized terminator: conservatively consume all
                    # remaining lines as data, not new command declarations.
                    heredocs.append(("\x00unresolved", False))
                    break
                if token == "function" and i + 1 < len(tokens) and NAME.fullmatch(tokens[i + 1]):
                    name = tokens[i + 1]
                    end = i + 2
                    if end < len(tokens) and tokens[end] == "()":
                        end += 1
                    if end < len(tokens) and tokens[end] == "{":
                        fid = add("symbol", name, first_line, type="Function", qualifiedName=name)
                        functions[name] = fid
                        exports.append(name)
                        edge(file_id, "DECLARES", fid, first_line, "syntax")
                        owner, depth, function_depth = fid, depth + 1, depth + 1
                        i, expect_command = end + 1, True
                        continue
                if expect_command and NAME.fullmatch(token) and i + 2 < len(tokens) and tokens[i + 1] == "()" and tokens[i + 2] == "{":
                    fid = add("symbol", token, first_line, type="Function", qualifiedName=token)
                    functions[token] = fid
                    exports.append(token)
                    edge(file_id, "DECLARES", fid, first_line, "syntax")
                    owner, depth, function_depth = fid, depth + 1, depth + 1
                    i, expect_command = i + 3, True
                    continue
                if token in {";", ";;", "&", "&&", "||", "|", "|&", "(", ")"}:
                    if token in {"|", "|&"}:
                        pipeline_left = last_command
                    elif token in {"&&", "||"}:
                        add("framework", "ConditionalExecution", first_line, operator=token, resolution="syntax")
                    else:
                        pipeline_left = None
                    expect_command = True
                elif token == "{":
                    depth += 1
                    expect_command = True
                elif token == "}":
                    if function_depth is not None and depth == function_depth:
                        owner, function_depth = file_id, None
                    depth = max(0, depth - 1)
                    expect_command = True
                elif expect_command and token in {"if", "elif", "while", "until", "for", "case", "select"}:
                    add("framework", token, first_line, type="ControlFlow", resolution="syntax")
                    expect_command = token in {"if", "elif", "while", "until"}
                elif token in {"then", "do", "else"} and (expect_command or last_command is None):
                    expect_command = True
                elif expect_command and token in {"fi", "done", "esac", "in", "!"}:
                    pass
                elif expect_command and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                    name = token.split("=", 1)[0]
                    add("symbol", name, first_line, type="Variable", valueCollected=False)
                elif expect_command:
                    expect_command = False
                    if token in {"source", "."}:
                        target = _literal(tokens[i + 1]) if i + 1 < len(tokens) else ""
                        if RELATIVE.fullmatch(target) and ".." not in PurePosixPath(target).parts:
                            target = target.removeprefix("./")
                            imports.append({"module": target, "name": "", "alias": ""})
                            sid = add("symbol", PurePosixPath(target).name, first_line, type="ScriptReference", relativeReference=target)
                            edge(owner, "SOURCES", sid, first_line)
                        else:
                            add("framework", "DynamicSource", first_line, resolution="unresolved")
                            limitations.add("dynamic_or_external_source_unresolved")
                    if COMMAND.fullmatch(token) or (RELATIVE.fullmatch(token) and ".." not in PurePosixPath(token).parts):
                        command_name = PurePosixPath(token).name
                        cid = add("symbol", command_name, first_line, type="Command", executableResolution="unresolved")
                        edge(owner, "INVOKES", cid, first_line)
                        pending_calls.append((owner, token, first_line))
                        if pipeline_left:
                            edge(pipeline_left, "PIPES_TO", cid, first_line, "syntax")
                        last_command, pipeline_left = cid, None
                        if token in {"eval", "exec", "bash", "sh", "zsh", "ksh", "env", "sudo"}:
                            add("framework", "ExternalExecution", first_line, command=token, resolution="unresolved")
                            limitations.add("dynamic_execution_unresolved")
                    else:
                        add("framework", "DynamicCommand", first_line, resolution="unresolved")
                        limitations.add("dynamic_command_unresolved")
                i += 1
            pipeline_left = None
        if heredocs or logical:
            limitations.add("unterminated_shell_input")
        for caller, name, line in pending_calls:
            if name in functions:
                edge(caller, "MAY_CALL", functions[name], line, "name_match_only")
    result = {"schemaVersion": 1, "adapterVersion": VERSION, "path": relative_path,
              "sourceDigest": source_digest, "language": language, "module": module, "modulePath": module_path,
              "records": records, "imports": imports, "exports": sorted(set(exports)),
              "coverage": {"detected": 1, "analyzed": 1, "unsupported": 0, "excluded": 0,
                           "syntax": "partial", "semanticComplete": False, "limitations": sorted(limitations)}}
    core.privacy_guard.ensure_public_safe(result)
    return result
