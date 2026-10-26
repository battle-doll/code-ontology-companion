"""Project the same repository-scoped Java facts into sealed pipeline records."""
from __future__ import annotations

import pipeline_adapters as adapters


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

    for item in index.types.values():
        if item["path"] != path:
            continue
        record = base(item["id"], "symbol", item["name"], item["line_start"])
        record.update(type=item["kind"].title(), qualifiedName=item["qualified_name"], originalSymbolId=item["id"])
        records.append(record)
    for item in index.files[path]["methods"]:
        record = base(item["id"], "symbol", item["name"], item["line_start"], item["line_end"])
        record.update(type="Method", qualifiedName=item["qualified_name"], originalSymbolId=item["id"], owner=item["owner"],
            parameterTypes=item["parameter_types"], returnType=item["return_type"])
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
