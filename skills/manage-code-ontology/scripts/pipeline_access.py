"""Registered, bounded read-only access to immutable pipeline snapshots.

Only the explicit CLI initializes or refreshes an analysis. MCP never discovers
source directories, changes permissions, runs code, or invokes a model.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import companion

MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
MAX_CASES = 100
PIPELINE_TOOLS = (
    "ontology_pipeline_status", "ontology_pipeline_search", "ontology_pipeline_modules",
    "list_domain_policies", "query_policy_rules", "compare_policy_cases", "explain_policy_result",
)


def _store():
    import pipeline_store
    return pipeline_store


def _policy():
    import pipeline_policy
    return pipeline_policy


def config(workspace: Path) -> dict:
    value = companion._read_json(workspace / "pipeline.json", "Pipeline configuration")
    if not isinstance(value, dict) or not isinstance(value.get("workspaceId"), str):
        raise companion.CompanionError("Invalid pipeline configuration.")
    return value


def register(workspace_path: str) -> None:
    workspace = companion._resolve_existing_dir(workspace_path, "Pipeline workspace")
    value = config(workspace)
    label = value.get("repositoryLabel", "Local ontology")
    companion.privacy_guard.ensure_public_safe(label)
    registry = companion._load_registry()
    items = [item for item in registry["workspaces"]
             if isinstance(item, dict) and item.get("id") != value["workspaceId"]]
    items.append({"id": value["workspaceId"], "label": label, "mode": "pipeline",
                  "workspace": str(workspace), "registeredAt": companion._now()})
    registry["workspaces"] = sorted(items, key=lambda item: (str(item.get("label", "")), item["id"]))
    companion._atomic_json(companion._registry_path(), registry)


def resolve(workspace_id: str) -> Path:
    matches = [item for item in companion._load_registry()["workspaces"]
               if isinstance(item, dict) and item.get("id") == workspace_id and item.get("mode") == "pipeline"]
    if not matches:
        raise companion.CompanionError("Unknown registered pipeline workspace id.")
    workspace = companion._resolve_existing_dir(matches[-1]["workspace"], "Pipeline workspace")
    if config(workspace)["workspaceId"] != workspace_id:
        raise companion.CompanionError("Registered pipeline identity does not match its configuration.")
    return workspace


def bounded_json(value: Any, *, output: bool = False) -> Any:
    """Bound depth, nodes and UTF-8 bytes before using caller-controlled values."""
    budget = [20_000 if output else 5_000]
    def visit(item, depth=0):
        budget[0] -= 1
        if depth > 24 or budget[0] < 0:
            raise companion.CompanionError("Pipeline JSON exceeds its structural budget.")
        if isinstance(item, dict):
            if len(item) > 256:
                raise companion.CompanionError("Pipeline object exceeds its field budget.")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 200:
                    raise companion.CompanionError("Invalid pipeline field.")
                visit(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > (10_000 if output else 500):
                raise companion.CompanionError("Pipeline list exceeds its item budget.")
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str):
            if len(item) > (16_384 if output else 2_048):
                raise companion.CompanionError("Pipeline text exceeds its size budget.")
        elif item is None or isinstance(item, bool):
            pass
        elif isinstance(item, int):
            if abs(item) > 10 ** 100:
                raise companion.CompanionError("Pipeline number exceeds its magnitude budget.")
        elif isinstance(item, float):
            if not math.isfinite(item) or abs(item) > 1e100:
                raise companion.CompanionError("Pipeline number is not finite or bounded.")
        else:
            raise companion.CompanionError("Invalid pipeline JSON value.")
    visit(value)
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > (MAX_OUTPUT_BYTES if output else MAX_INPUT_BYTES):
        raise companion.CompanionError("Pipeline response exceeds the byte budget; request a smaller page." if output
                                       else "Pipeline request exceeds the byte budget.")
    companion.privacy_guard.ensure_public_safe(value)
    return value


def _text(arguments, key, default=None, maximum=100):
    value = arguments.get(key, default)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise companion.CompanionError("Invalid pipeline text argument.")
    return value


def _integer(arguments, key, default, maximum):
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise companion.CompanionError("Invalid pipeline page argument.")
    return value


def dispatch(name: str, arguments: dict) -> dict:
    bounded_json(arguments)
    _validate_input(name, arguments)
    workspace = resolve(_text(arguments, "workspace_id"))
    snapshot_id = arguments.get("snapshot_id")
    if name != "ontology_pipeline_status":
        snapshot_id = _text(arguments, "snapshot_id")
        if snapshot_id in {"current", "latest", "previous"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot_id):
            raise companion.CompanionError("Pin a concrete pipeline snapshot id from status.")
    elif snapshot_id is not None and (not isinstance(snapshot_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot_id)):
        raise companion.CompanionError("Invalid pipeline snapshot id.")
    store = _store()
    from pipeline_acl import authorize
    if name in {"list_domain_policies", "query_policy_rules", "compare_policy_cases", "explain_policy_result"}:
        actions = ["read_policy"]
    elif name == "ontology_pipeline_search":
        actions = {"symbol": ["read_structure"], "framework": ["read_structure"],
                   "assertion": ["read_evidence"], "policy_rule": ["read_policy", "read_evidence"]}.get(
                       arguments.get("kind"), ["read_structure", "read_policy", "read_evidence"])
    else:
        actions = ["read_structure"]
    for action in actions:
        authorize(workspace, action, snapshot_id=snapshot_id)
    try:
        if name == "ontology_pipeline_status":
            data = store.status(str(workspace), snapshot_id=snapshot_id)
        elif name == "ontology_pipeline_search":
            data = store.query(str(workspace), snapshot_id=snapshot_id,
                term=arguments.get("term", ""), kind=arguments.get("kind"), module=arguments.get("module"),
                domain=arguments.get("domain"), offset=_integer(arguments, "offset", 0, 10_000_000),
                limit=max(1, _integer(arguments, "limit", 50, 100)))
        elif name == "ontology_pipeline_modules":
            data = store.modules(str(workspace), snapshot_id=snapshot_id,
                offset=_integer(arguments, "offset", 0, 10_000_000), limit=max(1, _integer(arguments, "limit", 50, 100)))
        else:
            data = dispatch_policy(store, workspace, snapshot_id, name, arguments)
            if name == "query_policy_rules":
                from pipeline_acl import AccessDenied
                try:
                    authorize(workspace, "read_evidence", snapshot_id=snapshot_id)
                except AccessDenied:
                    # Preserve opaque evidence references, but source locator
                    # details require the independent evidence permission.
                    excluded = {"evidence", "relativePath", "path", "lineStart", "lineEnd", "span", "sourceDigest"}
                    def hide(item):
                        if isinstance(item, dict):
                            return {key: hide(value) for key, value in item.items() if key not in excluded}
                        if isinstance(item, list):
                            return [hide(value) for value in item]
                        return item
                    data = hide(data)
                    data["evidenceDetailsWithheld"] = True
        bounded_json(data, output=True)
        return {"status": "ok", "snapshotId": snapshot_id or data.get("snapshotId"), "data": data}
    except companion.CompanionError:
        raise
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        # No parser/SQLite exception, source name or value reaches the wire.
        raise companion.CompanionError("The sealed pipeline request could not be completed.") from exc


def dispatch_policy(store, workspace, snapshot_id, name, arguments):
    snapshot = store.read_policy_records(str(workspace), snapshot_id=snapshot_id,
                                         domain=arguments.get("domain"), max_rules=10_000)
    policy = _policy()
    page = {"offset": _integer(arguments, "offset", 0, 1_000_000),
            "limit": max(1, _integer(arguments, "limit", 50, 100))}
    if name == "list_domain_policies":
        return policy.list_domain_policies(snapshot, domain=arguments.get("domain"), **page)
    if name == "query_policy_rules":
        return policy.query_policy_rules(snapshot, domain=arguments.get("domain"), rule_id=arguments.get("rule_id"),
                                         policy_view=arguments.get("policy_view", "verified_implemented"),
                                         ruleset_authority=arguments.get("ruleset_authority"), **page)
    common = {"policy_view": arguments.get("policy_view", "verified_implemented"),
              "catalog_snapshot_id": snapshot.get("catalogSnapshotId"),
              "policy_snapshot_id": snapshot.get("policySnapshotId"),
              "ruleset_digest": snapshot.get("rulesetDigest")}
    for key in ("ruleset_authority", "config_profile", "as_of"):
        if key in arguments:
            common[key] = arguments[key]
    rule_id = _text(arguments, "rule_id", maximum=200)
    if name == "explain_policy_result":
        context = arguments.get("context", {})
        if not isinstance(context, dict):
            raise companion.CompanionError("Policy context must be an object.")
        return policy.explain_policy_result(snapshot, rule_id=rule_id, context=context, **common)
    if name == "compare_policy_cases":
        cases = arguments.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES or any(not isinstance(c, dict) for c in cases):
            raise companion.CompanionError("Provide 1 to 100 policy cases.")
        return policy.compare_policy_cases(snapshot, rule_id=rule_id, cases=cases,
            objective=_text(arguments, "objective", maximum=100), **common)
    raise companion.CompanionError("Unknown pipeline tool.")


def project(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"status", "snapshotId", "data"} or value["status"] != "ok":
        raise companion.CompanionError("Malformed sealed pipeline response.")
    if not isinstance(value["snapshotId"], str) or not isinstance(value["data"], dict):
        raise companion.CompanionError("Malformed sealed pipeline response.")
    return bounded_json(value, output=True)


def tool_definitions() -> list[dict]:
    text = {"type": "string", "minLength": 1, "maxLength": 100}
    page = {"offset": {"type": "integer", "minimum": 0, "maximum": 10_000_000},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100}}
    common = {"workspace_id": text, "snapshot_id": text}
    policy_common = {"domain": text, "policy_view": {**text, "enum": ["verified_implemented", "approved_business"]}}
    policy_page = {**page, "offset": {"type": "integer", "minimum": 0, "maximum": 1_000_000}}
    context = {"type": "object", "maxProperties": 100, "additionalProperties": {}}
    compare = {**policy_common, "rule_id": {**text, "maxLength": 200}, "ruleset_authority": text,
               "config_profile": text, "as_of": text}
    specs = [
        ("ontology_pipeline_status", "Inspect sealed pipeline integrity and snapshot identity. Does not read source freshness.", {}, []),
        ("ontology_pipeline_search", "Page through sealed symbols, assertions, framework declarations and policies; partial coverage stays explicit.",
         {**page, "term": {"type": "string", "maxLength": 300}, "module": text, "domain": text,
          "kind": {**text, "enum": ["symbol", "assertion", "framework", "policy_rule"]}}, ["snapshot_id"]),
        ("ontology_pipeline_modules", "Page through sealed module metadata without loading all ontology graphs.", page, ["snapshot_id"]),
        ("list_domain_policies", "List analyzed domains and policy coverage. Zero extracted rules never proves absence.",
         {**policy_page, "domain": text}, ["snapshot_id"]),
        ("query_policy_rules", "Read typed source-backed policy rules from one pinned authority view, without source access.",
         {**policy_page, **policy_common, "ruleset_authority": text, "rule_id": {**text, "maxLength": 200}}, ["snapshot_id"]),
        ("compare_policy_cases", "Compare finite supplied contexts with deterministic arithmetic. A sampled best case is not a universal maximum.",
         {**compare, "cases": {"type": "array", "minItems": 1, "maxItems": MAX_CASES, "items": context},
          "objective": {**text, "enum": ["maximize_value", "minimize_value"]}},
         ["snapshot_id", "rule_id", "cases", "objective"]),
        ("explain_policy_result", "Evaluate a sealed rule with explicit context and return evidence, missing inputs and limitations.",
         {**compare, "context": context}, ["snapshot_id", "rule_id", "context"]),
    ]
    output = {"type": "object", "properties": {
        "status": {"type": "string", "enum": ["ok", "error"], "maxLength": 10},
        "snapshotId": text, "data": {"type": "object", "maxProperties": 256, "additionalProperties": True},
        "message": {"type": "string", "maxLength": 300}},
        "required": ["status"], "additionalProperties": False,
        "oneOf": [{"properties": {"status": {"const": "ok"}}, "required": ["snapshotId", "data"]},
                  {"properties": {"status": {"const": "error"}}, "required": ["message"]}]}
    return [{"name": name, "title": name.replace("_", " "), "description": description,
             "inputSchema": {"type": "object", "properties": {**common, **props},
                             "required": ["workspace_id", *required], "additionalProperties": False},
             "outputSchema": output, "annotations": {"readOnlyHint": True, "destructiveHint": False,
                         "openWorldHint": False, "idempotentHint": True}}
            for name, description, props, required in specs]


def _validate_input(name: str, arguments: dict) -> None:
    schemas = {tool["name"]: tool["inputSchema"] for tool in tool_definitions()}
    if name not in schemas:
        raise companion.CompanionError("Unknown pipeline tool.")
    def check(value, schema):
        kind = schema.get("type")
        valid = True
        if kind == "object":
            valid = isinstance(value, dict)
            if valid:
                props = schema.get("properties", {})
                valid = set(schema.get("required", [])) <= set(value) and len(value) <= schema.get("maxProperties", 256)
                if schema.get("additionalProperties") is False:
                    valid = valid and set(value) <= set(props)
                for key, item in value.items():
                    check(item, props.get(key, {}))
        elif kind == "array":
            valid = isinstance(value, list) and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 500)
            if valid:
                for item in value:
                    check(item, schema.get("items", {}))
        elif kind == "string":
            valid = isinstance(value, str) and schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 2048)
        elif kind == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool) and schema.get("minimum", 0) <= value <= schema.get("maximum", 10_000_000)
        if "enum" in schema:
            valid = valid and value in schema["enum"]
        if not valid:
            raise companion.CompanionError("Invalid bounded pipeline tool arguments.")
    check(arguments, schemas[name])


CLI_COMMANDS = {"analyze", "refresh", "pipeline-status", "pipeline-search", "pipeline-html", "pipeline-export", "pipeline-recover", "pipeline-access"}


def add_commands(subparsers) -> None:
    command = subparsers.add_parser("analyze", help="Analyze an authorized folder into a disk-backed ontology and offline HTML.")
    command.add_argument("--repo", required=True)
    command.add_argument("--workspace", required=True)
    command.add_argument("--authorized", action="store_true", help="Confirm authorization to read the selected source.")
    command.add_argument("--source-root", action="append")
    command.add_argument("--label", default="Local ontology")
    command.add_argument("--capacity", choices=["standard", "large"], default="standard",
                         help="Explicit bounded source/record budgets; large raises ceilings without changing supported semantics.")
    command.add_argument("--language", default="ko", choices=["ko", "en", "ja", "zh-CN", "ru"])
    command.add_argument("--no-html", action="store_true")
    command = subparsers.add_parser("refresh", help="Incrementally refresh a pipeline workspace; preserve previous snapshots.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--force", action="store_true")
    command.add_argument("--language", default="ko", choices=["ko", "en", "ja", "zh-CN", "ru"])
    command.add_argument("--no-html", action="store_true")
    command = subparsers.add_parser("pipeline-status", help="Read sealed snapshot integrity without opening source files.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--snapshot")
    command = subparsers.add_parser("pipeline-search", help="Query a bounded page of sealed pipeline records.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--snapshot", required=True)
    command.add_argument("--term", default="")
    command.add_argument("--kind", choices=["symbol", "assertion", "framework", "policy_rule"])
    command.add_argument("--offset", type=int, default=0)
    command.add_argument("--limit", type=int, default=50)
    command = subparsers.add_parser("pipeline-html", help="Create a new offline five-language view from one sealed snapshot.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--snapshot", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--language", default="ko", choices=["ko", "en", "ja", "zh-CN", "ru"])
    command = subparsers.add_parser("pipeline-recover", help="Inspect or recover an interrupted local pipeline generation.")
    command.add_argument("--workspace", required=True)
    command = subparsers.add_parser("pipeline-access", help="Explicitly replace a local principal grant; never exposed through MCP.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--principal", required=True, help="Pseudonymous operator-managed alias, not a personal name or email.")
    command.add_argument("--action", action="append", default=[], choices=["read_structure", "read_policy", "read_evidence", "export_html", "export_bundle", "manage_access"])
    command.add_argument("--snapshot", action="append", default=None)
    command = subparsers.add_parser("pipeline-export", help="Create a private portable knowledge bundle without source, cache or ACL configuration.")
    command.add_argument("--workspace", required=True)
    command.add_argument("--snapshot", required=True)
    command.add_argument("--output", required=True)


def _render(workspace, snapshot_id, output, language):
    from pipeline_html import render_pipeline
    return render_pipeline(workspace, snapshot_id, output, language=language)


def run_command(args) -> dict:
    store = _store()
    from pipeline_acl import authorize, initialize_access, update_access
    try:
        if args.command == "analyze":
            if not args.authorized:
                raise companion.CompanionError("Explicit source-read authorization is required; use --authorized after consent.")
            companion.privacy_guard.ensure_public_safe(args.label)
            budgets = ({"max_files": 250000, "max_total_bytes": 4 * 1024 ** 3, "max_records": 5000000,
                        "max_output_bytes": 8 * 1024 ** 3, "max_run_seconds": 7200, "max_ast_nodes": 200000}
                       if args.capacity == "large" else {})
            result = store.initialize(args.repo, args.workspace, source_roots=args.source_root, label=args.label,
                                      prepare_workspace=initialize_access, **budgets)
            register(args.workspace)
        elif args.command == "refresh":
            authorize(args.workspace, "manage_access")
            result = store.sync(args.workspace, force=args.force)
        elif args.command == "pipeline-status":
            authorize(args.workspace, "read_structure", snapshot_id=args.snapshot)
            return store.status(args.workspace, snapshot_id=args.snapshot)
        elif args.command == "pipeline-search":
            actions = {"symbol": ["read_structure"], "framework": ["read_structure"],
                       "assertion": ["read_evidence"], "policy_rule": ["read_policy", "read_evidence"]}.get(
                           args.kind, ["read_structure", "read_policy", "read_evidence"])
            for action in actions:
                authorize(args.workspace, action, snapshot_id=args.snapshot)
            return store.query(args.workspace, snapshot_id=args.snapshot, kind=args.kind,
                               term=args.term, offset=args.offset, limit=args.limit)
        elif args.command == "pipeline-recover":
            authorize(args.workspace, "manage_access")
            result = store.recover(args.workspace)
            if result.get("snapshotId"):
                register(args.workspace)
            return result
        elif args.command == "pipeline-access":
            return update_access(args.workspace, args.principal, args.action, args.snapshot or ["*"])
        elif args.command == "pipeline-export":
            from pipeline_export import export_bundle
            return export_bundle(args.workspace, args.snapshot, args.output)
        elif args.command == "pipeline-html":
            return _render(args.workspace, args.snapshot, args.output, args.language)
        else:
            raise companion.CompanionError("Unknown pipeline command.")
        if not args.no_html:
            snapshot_id = result["snapshotId"]
            output = Path(args.workspace) / "html" / snapshot_id
            if not output.exists():
                output.parent.mkdir(mode=0o700, exist_ok=True)
                result["html"] = _render(args.workspace, snapshot_id, str(output), args.language)
            else:
                result["html"] = {"status": "existing", "entry": str(output / "index.html")}
        return result
    except companion.CompanionError:
        raise
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        if (str(exc) == "python_ast_budget_exceeded" and args.command == "analyze"
                and getattr(args, "capacity", None) == "standard"):
            raise companion.CompanionError(
                "A source file exceeds the standard AST budget. Use --capacity large with a new authorized workspace, "
                "or select narrower source roots. No snapshot was promoted.") from exc
        raise companion.CompanionError("The pipeline operation could not be completed; the previous sealed snapshot is preserved.") from exc
