# Model-era workflow — 0.8.0

[English](model-era-workflow.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/v0.8.0/docs/ko/MODEL_ERA_WORKFLOW.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/v0.8.0/docs/ja/MODEL_ERA_WORKFLOW.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/v0.8.0/docs/zh-CN/MODEL_ERA_WORKFLOW.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/v0.8.0/docs/ru/MODEL_ERA_WORKFLOW.md)

## Preserve the user's choice

GPT-6 Astra and GPT-6.1 Sol can consume the same bounded source evidence through the host's exposed tools. Keep the user's chosen model and reasoning effort. The plugin selects neither and requires no particular model, remote API or paid account. Better retrieval contracts do not establish a measured model advantage; no model A/B result is claimed.

## AI: use local MCP with pinned evidence

Use Windows, macOS or Linux with existing Python 3.9+. The official Skills-only package includes the analyzer, offline HTML and local MCP configuration instructions. Use the same-version complete package for the local stdio server; no hosted endpoint is required. Configure only the requested local entry, preserve unrelated entries and verify actual tool availability in a fresh host process. Installing files does not make MCP tools immediately callable.

Check the registered workspace and source freshness first. The complete package has eleven read-only tools: the seven existing workspace/status/search/neighbors/history/changes/lineage tools plus `ontology_large_modules`, `ontology_large_search`, `ontology_large_neighbors` and `ontology_evidence_bundle`. For an ordinary workspace, pin related reads to the same snapshot and use the bounded evidence bundle for a focused question. For a large project, list modules, pin one catalog, search exact selected module roots, then inspect paths within a selected module. Catalog queries do not resolve cross-module calls.

Initialization and refresh remain separately authorized CLI writes. MCP accepts registered IDs, not arbitrary paths; it never installs packages, refreshes data, executes target code or uploads source. Bounded pages and traversal limits must be reported as limits.

## People: explore the offline HTML

Open `graph.html` locally. Start with the module overview, search for a symbol, select it, then inspect source locations and relationship evidence. Structure, impact and changes answer different questions. Search and paged text routes reach indexed entries that are folded or outside the visible scene. Visible counts describe the displayed scope, not the entire codebase.

Display layers and one/two/three-hop call highlighting are independent. Add one layer at a time; confirm expansion to layer four or deeper. Use camera focus, zoom and Shift-drag panning separately. Use keyboard controls, reduced motion or the text-list fallback when spatial exploration is difficult. Presentation aggregates and camera motion are not new source or runtime evidence.

## Evidence, privacy and review

Keep `observed` source relationships separate from `inferred` suggestions and `runtime_unknown`. Cite a source path/span and material rule evidence; show freshness, parser coverage, unresolved targets and truncation. Static analysis does not establish runtime success or profitability.

User workspaces stay local. Public packages and demos may contain only this public project or synthetic fixtures; source bodies, personal names, addresses, credentials, private home paths and private-project artifacts must not be published. The publisher uses only the battle-doll alias. Optional local inference requires separate explicit consent.

Unit tests, extracted-package checks, browser usability, native OS checks, portal validation, submission, approval and publication are separate evidence states. Do not call a local candidate published. The guide is available in five languages; the pre-existing detailed legal/security/reference matrix remains English/Korean/Japanese/Simplified Chinese. See the [coverage map](https://github.com/battle-doll/code-ontology-companion/blob/v0.8.0/docs/TRANSLATION_COVERAGE.md).

## 0.8.0 pinned retrieval contracts

The seven existing normal-workspace tools retain their names and read boundaries. `ontology_list_workspaces` also identifies registered large parents with `mode: "large"`. Use actual exposed schemas for optional values; never substitute a filesystem path for `workspace_id`.

| Tool | Required inputs | Pin and scope |
| --- | --- | --- |
| `ontology_large_modules` | `workspace_id` | Optional `catalog_snapshot_id`; `term`, `offset`, `limit` page modules |
| `ontology_large_search` | `workspace_id`, exact `module_roots`, `term` | Optional `catalog_snapshot_id`, language/type/path filters and pagination |
| `ontology_large_neighbors` | `workspace_id`, one `module_root`, `symbol` | Optional `catalog_snapshot_id`, direction/depth/relationships/limit; paths stay within one module |
| `ontology_evidence_bundle` | normal `workspace_id`, 1–8 `requests` | Optional `snapshot_id`; each request has a unique `id`, `operation: "search"` or `"neighbors"` and that operation's selectors |

A bundle resolves one normal snapshot at the start. Each item reports `ok` or `error`, and the outer result reports `ok` or `partial`. It bounds total results to 200 and canonical structured JSON to 262144 UTF-8 bytes; duplicated protocol text/wire bytes are outside that payload budget. An oversized item becomes a safe item error rather than an unbounded response. A partial bundle is not a successful answer for a failed item. Catalog and normal snapshot IDs are distinct; do not mix them or fabricate cross-module call paths.

## Measured limits of the bundle

A synthetic Mac fixture (1,002 nodes, 2,000 edges; 20 local samples) preserved the eight-search results while reducing MCP requests from 8 to 1. Ontology reads remained 8. Structured bytes increased from 32,380 to 33,108; local p50 increased from 14.073 to 16.066 ms. This measures request coordination and snapshot consistency, not faster server computation, model quality or cross-platform performance.

The models’ tool capabilities are documented by [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) and [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol). Host reasoning settings and API reasoning settings are distinct; preserve the actual host selection.
