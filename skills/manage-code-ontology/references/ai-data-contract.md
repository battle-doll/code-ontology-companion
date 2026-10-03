# AI-facing evidence contract

Use the tool's declared input/output schema as the executable contract. JSON and
RDF represent the same static source evidence as the human-facing workbench.

## Read scope

- Resolve `workspace_id` from the local workspace registry, never from a supplied path.
- Check source freshness separately from snapshot existence. `freshness: snapshot`
  says which immutable material was read; it does not say that the source is current.
- Pin related calls to a returned snapshot identifier. A missing snapshot is an
  error, not permission to silently read a different revision.
- Use exact IDs/FQNs first. `language`, type and path filters narrow structure,
  while pagination bounds the answer. Check returned, total and truncation fields.

## Relations and paths

Every relationship keeps its actual direction, type and extraction evidence.
Each path step must refer to a real edge. Shared annotations and framework
concepts are not dependency-propagation edges by default.

| Field | Meaning |
| --- | --- |
| rule_id / ruleId | Stable extraction rule, not a model confidence score |
| basis | direct_syntax, resolved_static, framework_semantic or name_heuristic |
| runtime_status / runtimeStatus | not_applicable or runtime_unknown |
| path + line span | Repository-relative evidence location, when available |
| limitations | Material unresolved or unsupported conditions |
| evidence identifier | Reference to one precise relationship evidence item |

Do not equate evidence attachment percentage with precision, recall or runtime
coverage. Report parse failures and bounded language/framework support when they
change the answer. An unresolved dynamic call is unknown, not an absent dependency.

## Changes

The canonical structural diff includes additions, removals and modifications of
nodes and edges, including evidence changes. Compare actual fields and preserve
the source-change versus analyzer-change basis. A rename is not established just
because one node was removed and a similar one appeared.

## Cross-product references

[code-reference.md](code-reference.md) defines the local selected-reference
envelope. Keep the original artifact immutable when a consumer accepts only its
locator. Repository identity and snapshot scope qualify legacy symbol IDs.
Contract validity, source observation, inference and current user approval are
different facts. A consumer must not silently promote any of them.

## Response composition

Answer the requested question first. Cite only supporting nodes, path steps and
source spans, then state a compact scope/limitation note. Retrieve another page
only when it can materially change the answer. Do not send full graphs, private
manifests or unrelated source names to fill context.

## 0.8.0 pinned retrieval contracts

The seven existing normal-workspace tools retain their names and read boundaries. `ontology_list_workspaces` also identifies registered large parents with `mode: "large"`. Use actual exposed schemas for optional values; never substitute a filesystem path for `workspace_id`.

| Tool | Required inputs | Pin and scope |
| --- | --- | --- |
| `ontology_large_modules` | `workspace_id` | Optional `catalog_snapshot_id`; `term`, `offset`, `limit` page modules |
| `ontology_large_search` | `workspace_id`, exact `module_roots`, `term` | Optional `catalog_snapshot_id`, language/type/path filters and pagination |
| `ontology_large_neighbors` | `workspace_id`, one `module_root`, `symbol` | Optional `catalog_snapshot_id`, direction/depth/relationships/limit; paths stay within one module |
| `ontology_evidence_bundle` | normal `workspace_id`, 1–8 `requests` | Optional `snapshot_id`; each request has a unique `id`, `operation: "search"` or `"neighbors"` and that operation's selectors |

A bundle resolves one normal snapshot at the start. Each item reports `ok` or `error`, and the outer result reports `ok` or `partial`. It bounds total results to 200 and canonical structured JSON to 262144 UTF-8 bytes; duplicated protocol text/wire bytes are outside that payload budget. An oversized item becomes a safe item error rather than an unbounded response. A partial bundle is not a successful answer for a failed item. Catalog and normal snapshot IDs are distinct; do not mix them or fabricate cross-module call paths.
