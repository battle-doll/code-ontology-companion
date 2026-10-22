"""Bounded, non-executing file facts for the local pipeline.

Grammar coverage is explicit. The Java/JS/SQL/XML adapters are conservative
syntax recognizers, not compilers, type checkers or runtime evidence.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Any

import code_ontology_core as core

ADAPTER_VERSION = "pipeline-adapters-1"
LANGUAGES = {".py": "Python", ".java": "Java", ".js": "JavaScript", ".mjs": "JavaScript",
             ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
             ".sql": "SQL", ".xml": "XML", ".vue": "Vue", ".kt": "Kotlin", ".kts": "Kotlin",
             ".cs": "CSharp", ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C",
             ".cpp": "Cpp", ".cc": "Cpp", ".cxx": "Cpp", ".hpp": "Cpp", ".php": "PHP",
             ".swift": "Swift", ".dart": "Dart", ".rb": "Ruby", ".scala": "Scala",
             ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ksh": "Shell",
             ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell"}
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".properties", ".ini", ".cfg"}
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:[./:-][A-Za-z0-9_$@-]+)*$")


class AdapterError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def identifier(*parts: Any) -> str:
    return "p:" + hashlib.sha256(canonical(parts)).hexdigest()


def language_for(path: str) -> str | None:
    suffix = PurePosixPath(path).suffix.lower()
    return LANGUAGES.get(suffix, "Config" if suffix in CONFIG_SUFFIXES else None)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return base + "." + node.attr if base else node.attr
    return ""


def _masked(source: str, language: str = "") -> str:
    """Discard comments and string/template contents while retaining line offsets."""
    result = list(source)
    i = 0
    while i < len(source):
        if ((language in {"Ruby", "PHP"} and source[i] == "#") or
                (language == "SQL" and source.startswith("--", i)) or source.startswith("//", i)):
            end = source.find("\n", i)
            end = len(source) if end < 0 else end
        elif source.startswith("/*", i):
            found = source.find("*/", i + 2)
            if found < 0:
                raise AdapterError("unterminated_comment")
            end = found + 2
        elif source.startswith(('"""', "'''"), i):
            delimiter = source[i:i+3]
            found = source.find(delimiter, i+3)
            if found < 0:
                raise AdapterError("unterminated_literal")
            end = found + 3
        elif language == "Rust" and source[i] == "'" and re.match(r"'[A-Za-z_]\w*(?!')", source[i:]) and not re.match(r"'[A-Za-z_]'", source[i:]):
            # Lifetimes are identifiers; character literals still use the
            # ordinary quoted-literal path below.
            i += 1
            continue
        elif source[i] in "\"'`":
            quote = source[i]
            end = i + 1
            while end < len(source):
                if source[end] == "\\":
                    end += 2
                elif source[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
            else:
                raise AdapterError("unterminated_literal")
        else:
            i += 1
            continue
        for pos in range(i, min(end, len(source))):
            if result[pos] not in "\r\n":
                result[pos] = " "
        i = end
    return "".join(result)


def analyze_file(relative_path: str, source: str, source_digest: str, *, resource_key: bytes | None = None,
                 max_records: int = 20000, max_ast_nodes: int = 20000) -> dict[str, Any]:
    if (not isinstance(relative_path, str) or not core._portable_relative_path(relative_path)
            or not re.fullmatch(r"[a-f0-9]{64}", source_digest)):
        raise AdapterError("invalid_file_identity")
    if len(source.encode("utf-8")) > core.MAX_SOURCE_BYTES:
        raise AdapterError("source_budget_exceeded")
    language = language_for(relative_path)
    if language in {"Shell", "PowerShell"} or (language is None and re.match(r"^#![^\r\n]*(?:/|\s)(?:bash|sh|zsh|ksh)(?:\s|$)", source)):
        from pipeline_shell import analyze_shell
        return analyze_shell(relative_path, source, source_digest, max_records=max_records, max_ast_nodes=max_ast_nodes)
    if language is None:
        raise AdapterError("unsupported_language")
    module_path = relative_path.split("/", 1)[0] if "/" in relative_path else "."
    module = identifier("module", module_path)
    records: list[dict[str, Any]] = []
    imports: list[dict[str, str]] = []
    limitations: set[str] = set()
    exports: list[str] = []
    file_id = identifier("file", relative_path)
    module_name = relative_path.rsplit(".", 1)[0].replace("/", ".")
    if module_name.endswith(".__init__"):
        module_name = module_name[:-9]

    def add(kind: str, name: str, line: int = 1, *, key: str = "", **data: Any) -> dict[str, Any]:
        if len(records) >= max_records:
            raise AdapterError("record_budget_exceeded")
        row = {"id": identifier(relative_path, kind, name, line, key), "kind": kind, "name": name,
               "path": relative_path, "language": language, "module": module, "modulePath": module_path,
               "span": {"lineStart": max(1, line), "lineEnd": max(1, line)},
               "sourceDigest": source_digest, "ruleVersion": ADAPTER_VERSION,
               "basis": "declared", "status": "runtime_unknown"}
        row.update(data)
        records.append(row)
        return row

    add("symbol", PurePosixPath(relative_path).name, type="File", qualifiedName=module_name, id=file_id)

    def resource(kind: str, operation: str, line: int, value: Any = None, **extra: Any) -> None:
        # Scope includes path + occurrence: absent broker/environment scope cannot
        # accidentally merge identically named topics/keys across environments.
        if resource_key is None:
            opaque = identifier("unresolved-resource", relative_path, line, kind, operation)
        else:
            opaque = "h:" + hmac.new(resource_key, canonical([relative_path, line, kind, operation, value]), hashlib.sha256).hexdigest()
        add("framework", kind, line, operation=operation, resourceId=opaque,
            environmentScope="unknown", resolution="declared_candidate", runtimeStatus="runtime_unknown", **extra)

    if language == "Python":
        try:
            tree = ast.parse(source, filename="authorized-source")
        except (SyntaxError, RecursionError, MemoryError):
            raise AdapterError("python_syntax_or_depth_error") from None
        pending = [(tree, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if count > max_ast_nodes or depth > 120:
                raise AdapterError("python_ast_budget_exceeded")
            pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
        graph = core.Graph("authorized-source")
        mid = core._node_id("python", "module", module_name)
        graph.add_node(mid, "Module", module_name.rsplit(".", 1)[-1], "Python", path=relative_path,
                       qualified_name=module_name, metadata={"line_start": 1, "line_end": 1})
        core.PythonVisitor(graph, mid, module_name, relative_path, tree,
                           is_package=PurePosixPath(relative_path).name == "__init__.py").visit(tree)
        node_ids = {key: identifier(relative_path, "core-symbol", key) for key in graph.nodes}
        for old_id, node in sorted(graph.nodes.items()):
            metadata = node.get("metadata", {})
            add("symbol", node["name"], int(metadata.get("line_start", 1)), id=node_ids[old_id],
                type=node["type"], qualifiedName=node.get("qualified_name", node["name"]),
                metadata=metadata, basis="observed")
            if node["type"] in {"Function", "Class"}:
                exports.append(node.get("qualified_name", node["name"]))
        for subject, predicate, target in sorted(graph.edges):
            evidence = graph.edge_evidence.get((subject, predicate, target), [])
            line = int(evidence[0].get("line_start", 1)) if evidence else 1
            add("assertion", predicate, line, key=subject + target,
                subject=node_ids.get(subject, subject), predicate=predicate,
                object=node_ids.get(target, target), evidence=evidence,
                resolution="file_static" if subject in node_ids and target in node_ids else "unresolved",
                limitations=["static_analysis_not_runtime"])
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    aliases[local] = alias.name
                    imports.append({"module": alias.name, "name": "", "alias": local})
            elif isinstance(node, ast.ImportFrom):
                mod = "." * node.level + (node.module or "")
                for alias in node.names:
                    local = alias.asname or alias.name
                    aliases[local] = mod + "." + alias.name
                    imports.append({"module": mod, "name": alias.name, "alias": local})
        instances: dict[str, str] = {}
        frameworks = ("langgraph", "langchain", "kafka", "confluent_kafka", "redis")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, "target", None)
                called = _name(node.value.func)
                resolved = aliases.get(called.split(".")[0], called.split(".")[0]) + called[len(called.split(".")[0]):]
                if isinstance(target, ast.Name) and resolved.split(".")[0] in frameworks:
                    instances[target.id] = resolved
            if not isinstance(node, ast.Call):
                continue
            called = _name(node.func)
            head = called.split(".")[0]
            origin = instances.get(head, aliases.get(head, ""))
            line = getattr(node, "lineno", 1)
            if origin.split(".")[0] in {"langgraph", "langchain"}:
                resource("WorkflowStep" if called.endswith(("add_node", "add_edge", "add_conditional_edges")) else "Agent",
                         called.rsplit(".", 1)[-1], line,
                         framework="LangGraph" if origin.startswith("langgraph") else "LangChain",
                         limitations=["binding_and_dynamic_execution_unverified"])
            elif origin.split(".")[0] in {"kafka", "confluent_kafka"}:
                resource("KafkaTopic", called.rsplit(".", 1)[-1], line,
                         value=node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None,
                         declaredOptions=sorted(k.arg for k in node.keywords if k.arg in {"group_id", "value_serializer", "key_serializer", "auto_offset_reset"}))
            elif origin.split(".")[0] == "redis":
                ttl = next((k.value.value for k in node.keywords if k.arg == "ex" and isinstance(k.value, ast.Constant)
                            and type(k.value.value) is int and k.value.value >= 0), None)
                resource("RedisResource", called.rsplit(".", 1)[-1], line,
                         value=node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None,
                         declaredTTLSeconds=ttl, keyShape="opaque", valueCollected=False)
        limitations.update(("dynamic_dispatch_unresolved", "runtime_unknown"))
    elif language == "XML":
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", source, re.I):
            raise AdapterError("external_xml_declaration_forbidden")
        try:
            root = ET.fromstring(source)
        except (ET.ParseError, RecursionError):
            raise AdapterError("xml_syntax_error") from None
        stack = [(root, 0)]
        count = 0
        while stack:
            element, depth = stack.pop()
            count += 1
            if count > max_ast_nodes or depth > 100:
                raise AdapterError("xml_budget_exceeded")
            stack.extend((child, depth + 1) for child in element)
            tag = element.tag.rsplit("}", 1)[-1]
            if root.tag.rsplit("}", 1)[-1] == "mapper" and tag in {"select", "insert", "update", "delete", "resultMap", "sql"}:
                name = element.attrib.get("id", "")
                if _IDENTIFIER.fullmatch(name):
                    line = source[:source.find('id="' + name + '"')].count("\n") + 1
                    add("framework", name, line, framework="MyBatis", operation=tag,
                        resolution="declared", dynamic=any(child.tag in {"if", "choose", "foreach", "bind"} for child in element.iter()),
                        limitations=["dynamic_sql_and_execution_association_unresolved"])
        limitations.add("xml_mapping_only")
    elif language == "Config":
        # Configuration invalidates resolution without persisting configuration
        # values, executing constructors, or interpreting secret-bearing content.
        limitations.add("configuration_values_not_collected")
    else:
        text = source
        if language == "Vue":
            scripts = list(re.finditer(r"<script\b[^>]*>(.*?)</script\s*>", source, re.S | re.I))
            add("framework", "VueSFC", framework="Vue", resolution="declared",
                sections={tag: len(re.findall(r"<" + tag + r"\b", source, re.I)) for tag in ("template", "script", "style")})
            # Keep source line numbers without extracting template text or styles.
            chars = ["\n" if c == "\n" else " " for c in source]
            for match in scripts:
                chars[match.start(1):match.end(1)] = match.group(1)
            text = "".join(chars)
            limitations.add("vue_template_semantics_unsupported")
        masked = _masked(text, language)
        if language == "Java":
            package = re.search(r"\bpackage\s+([\w.]+)\s*;", masked)
            prefix = package.group(1) + "." if package else ""
            declarations = re.finditer(r"\b(class|interface|enum|record)\s+([A-Za-z_$][\w$]*)", masked)
            for match in declarations:
                q = prefix + match.group(2)
                exports.append(q)
                add("symbol", match.group(2), masked[:match.start()].count("\n") + 1,
                    type=match.group(1).title(), qualifiedName=q)
            for match in re.finditer(r"\bimport\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;", masked):
                imports.append({"module": match.group(1).rsplit(".", 1)[0], "name": match.group(1).rsplit(".", 1)[-1], "alias": ""})
            for match in re.finditer(r"\b(?:public|private|protected)\s+(?:(?:static|final|synchronized)\s+)*[\w<>\[\].?, ]+?\s+([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:throws[^{}]+)?\{", masked):
                add("symbol", match.group(1), masked[:match.start()].count("\n") + 1,
                    type="Method", qualifiedName=prefix + match.group(1), resolution="declared_candidate")
            spring = any(x["module"].startswith("org.springframework") for x in imports)
            if spring:
                for match in re.finditer(r"@(RestController|Controller|Service|Repository|Component|SpringBootApplication|GetMapping|PostMapping|RequestMapping)\b", masked):
                    add("framework", match.group(1), masked[:match.start()].count("\n") + 1,
                        framework="SpringBoot" if match.group(1) == "SpringBootApplication" else "Spring",
                        resolution="declared_candidate", limitations=["annotation_binding_unverified"])
            limitations.add("java_conservative_syntax_not_type_resolution")
        elif language == "SQL":
            for match in re.finditer(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w.]*)", masked, re.I):
                exports.append(match.group(1))
                add("symbol", match.group(1), masked[:match.start()].count("\n") + 1, type="SqlRelation", qualifiedName=match.group(1))
            for match in re.finditer(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([A-Za-z_][\w.]*)", masked, re.I):
                add("assertion", "SQL_REFERENCES", masked[:match.start()].count("\n") + 1,
                    subject=file_id, predicate="SQL_REFERENCES", targetName=match.group(1), resolution="unresolved")
            limitations.add("sql_dialect_dynamic_sql_procedures_unresolved")
        elif language in {"JavaScript", "TypeScript", "Vue"}:
            for match in re.finditer(r"\b(?:export\s+(?:default\s+)?)?(?:async\s+)?(class|interface|function|enum|type)\s+([A-Za-z_$][\w$]*)", masked):
                exports.append(match.group(2))
                add("symbol", match.group(2), masked[:match.start()].count("\n") + 1,
                    type=match.group(1).title(), qualifiedName=module_name + "." + match.group(2))
            # Import literals are matched only on lines whose code prefix survived
            # comment/string masking, never arbitrary strings containing code.
            for match in re.finditer(r"\b(?:import\s+(.+?)\s+from\s*|(?:const|let|var)\s+(\w+)\s*=\s*require\s*\()(['\"])([@\w./-]+)\3", text):
                if not masked[match.start():match.start() + 6].strip():
                    continue
                imported = match.group(4)
                imports.append({"module": imported, "name": "", "alias": ""})
                framework = next((label for key, label in (("@langchain/langgraph", "LangGraph"), ("langchain", "LangChain"),
                                   ("@langchain/core", "LangChain"), ("kafkajs", "Kafka"), ("redis", "Redis"), ("react", "React"), ("vue", "Vue")) if imported == key or imported.startswith(key + "/")), None)
                if framework:
                    add("framework", framework, text[:match.start()].count("\n") + 1, framework=framework,
                        operation="import", resolution="declared_import", limitations=["runtime_and_call_binding_unresolved"])
            limitations.add("javascript_typescript_conservative_syntax_only")
        else:
            patterns = {
                "Kotlin": r"\b(class|interface|object|fun|typealias)\s+([A-Za-z_]\w*)",
                "CSharp": r"\b(class|interface|struct|enum|record)\s+([A-Za-z_]\w*)",
                "Go": r"\b(func|type)\s+(?:\([^()]*\)\s*)?([A-Za-z_]\w*)",
                "Rust": r"\b(fn|struct|enum|trait|mod|type)\s+([A-Za-z_]\w*)",
                "C": r"\b(struct|enum|union|typedef)\s+([A-Za-z_]\w*)",
                "Cpp": r"\b(class|struct|enum|union|namespace)\s+([A-Za-z_]\w*)",
                "PHP": r"\b(class|interface|trait|function|enum)\s+([A-Za-z_]\w*)",
                "Swift": r"\b(class|struct|enum|protocol|func|typealias)\s+([A-Za-z_]\w*)",
                "Dart": r"\b(class|mixin|enum|typedef|extension)\s+([A-Za-z_]\w*)",
                "Ruby": r"(?m)^\s*(class|module|def)\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*[!?]?)",
                "Scala": r"\b(class|trait|object|def|type|enum)\s+([A-Za-z_]\w*)"}
            for match in re.finditer(patterns[language], masked):
                exports.append(module_name + "." + match.group(2))
                add("symbol", match.group(2), masked[:match.start()].count("\n") + 1,
                    type=match.group(1).title(), qualifiedName=module_name + "." + match.group(2), resolution="lexical_declaration")
            if language in {"C", "Cpp", "CSharp", "Dart"}:
                for match in re.finditer(r"(?m)^\s*(?:(?:public|private|protected|static|inline|virtual|async|extern)\s+)*[A-Za-z_]\w*(?:[\w<>:*&\[\]?, ]*?)\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{", masked):
                    add("symbol", match.group(1), masked[:match.start()].count("\n") + 1,
                        type="Function", qualifiedName=module_name + "." + match.group(1), resolution="lexical_candidate")
            # Named imports have no literal payload. Quoted imports are accepted
            # only if their keyword prefix survives masking, never from strings.
            import_patterns = {
                "Kotlin": r"\bimport\s+([\w.]+)", "CSharp": r"\busing\s+(?:static\s+)?([\w.]+)\s*;",
                "Rust": r"\buse\s+([\w:]+)", "Swift": r"\bimport\s+([\w.]+)",
                "Scala": r"\bimport\s+([\w.]+)", "PHP": r"\buse\s+([\w\\]+)"}
            if language in import_patterns:
                for match in re.finditer(import_patterns[language], masked):
                    imports.append({"module": match.group(1), "name": "", "alias": ""})
            literal_patterns = {
                "Go": r'\bimport\s+(?:\w+\s+)?"([\w./-]+)"',
                "C": r'#\s*include\s*[<"]([\w./-]+)[>"]',
                "Cpp": r'#\s*include\s*[<"]([\w./-]+)[>"]',
                "Dart": r"\b(?:import|export|part)\s+['\"]([\w:./-]+)['\"]",
                "Ruby": r"\b(?:require|require_relative|load)\s+['\"]([\w./-]+)['\"]"}
            if language in literal_patterns:
                for match in re.finditer(literal_patterns[language], text):
                    if masked[match.start():match.start()+6].strip():
                        imports.append({"module": match.group(1), "name": "", "alias": ""})
            limitations.update(("lexical_declarations_and_imports_only", "types_macros_overloads_dynamic_semantics_unsupported"))
    facts = {"schemaVersion": 1, "adapterVersion": ADAPTER_VERSION, "path": relative_path,
             "sourceDigest": source_digest, "language": language, "module": module, "modulePath": module_path,
             "records": records, "imports": imports, "exports": sorted(set(exports)),
             "coverage": {"detected": 1, "analyzed": 1, "unsupported": 0, "excluded": 0,
                          "syntax": "ast" if language == "Python" else "declared_subset",
                          "semanticComplete": False, "limitations": sorted(limitations)}}
    core.privacy_guard.ensure_public_safe(facts)
    return facts
