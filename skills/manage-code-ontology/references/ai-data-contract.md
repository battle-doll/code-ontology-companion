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
