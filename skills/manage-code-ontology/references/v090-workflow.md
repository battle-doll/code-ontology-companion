# Version 0.8.3 local workflow

[English](v090-workflow.md) | [한국어](../../../docs/ko/references/v090-workflow.md) | [日本語](../../../docs/ja/references/v090-workflow.md) | [简体中文](../../../docs/zh-CN/references/v090-workflow.md) | [Русский](../../../docs/ru/references/v090-workflow.md)

This guide keeps its existing `v090-workflow.md` filename for link compatibility. The unpublished development label 0.9.0 maps to 0.8.2; this guide describes current 0.8.3 behavior.

Code Ontology Companion remains a local Java/Spring and Python source-to-ontology data pipeline. Python 3.9+, Windows, macOS and Linux are supported. AI reads the ontology through local MCP; people use the generated offline HTML. The developer identity is **battle-doll (배틀돌)**. Keep the selected model and reasoning effort; no model-specific quality, token or latency advantage is asserted.

## Generated human HTML in 0.8.3

The generated offline HTML starts in **Focus mode**, alongside a separate **Full mode**. Focus level 1 shows module entrances; select an item in the map or list and enter it to show only that item's declared children, up to level 4. Breadcrumb buttons return to a parent. A focused map page contains at most **60 nodes and 160 displayed edges** on mobile and desktop; remaining items and relationships remain accessible through explicit pages and the text list. These are display limits, not source-analysis limits. Existing full/cumulative exploration keeps its own bounds and confirmation at level 4 or deeper.

Focus mode lays out and animates only the bounded selected display graph; it still parses the full embedded payload and constructs the hierarchy. This is not complete lazy loading for arbitrarily large repositories. Reduced-motion settings suppress the entry animation; navigation cancels obsolete motion. The map preserves static source evidence and does not establish runtime behavior. Local DOM, geometry or unit-test results do not establish real-device usability or a measured speed improvement. Local MCP, five UI/documentation languages, Windows, macOS and Linux remain supported.

## Inspect freshness and recover interrupted work

`ontology_status` reports source `freshness` separately from `generatorFreshness` (`current`, `stale`, `unknown`). The generator fingerprint covers the bundled analysis helpers and workbench assets. Source files can be current while generated HTML needs rebuilding. Legacy snapshots without the fingerprint report `unknown`; `sync` creates a current-format snapshot instead of treating missing metadata as proof of freshness.

Complete snapshot files and their SHA-256 artifact manifest are finalized before a prepared run receipt is used to append lineage and atomically replace the current pointer. Interruption can leave a pending receipt or a derived lineage export needing repair. `doctor --workspace` reads integrity and recovery state. `recover` verifies the same run's hashes and bindings, finishes it without duplicate lineage events, and repairs the derived Turtle export. Hash mismatches, conflicting state or multiple pending runs stop recovery. This is recoverable coordination of files, not a single filesystem transaction across all files; Windows reports file-flush-only durability rather than POSIX directory fsync.

Use `recover` only when diagnostics show interrupted work in the authorized workspace, then run `sync` if source or generator state is stale. MCP remains read-only and does not perform recovery or refresh.

```bash
python3 skills/manage-code-ontology/scripts/companion.py status --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py doctor --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py recover --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py sync --workspace "/path/outside/repo/ontology"
```

## Private incremental analysis

On macOS and Linux, Companion keeps a disposable, owner-only `.parse-cache` outside the source repository. Authenticated parser operations are reused when the source and analysis context match; they are not source-text backups. The graph is rebuilt from those operations and relationships are resolved again. A changed scope, import/type context or analyzer invalidates relevant entries. Cache reuse does not prove analysis accuracy. Windows performs the equivalent full analysis and stores no parse-cache material until a private-cache DACL provisioner is available. Full-analysis fallback preserves Windows support.

Keep the cache, identity profile, transaction receipts and `source-manifest.json` private. A configured `CODE_ONTOLOGY_PRIVACY_FILE` checks known identities plus generic sensitive patterns; it cannot recognize every unknown personal name. Public candidate packaging with `--public` requires the protected identity profile and privacy validation. Do not upload private workspace internals, legal names or personal email addresses.

## Bounded evidence for AI

The original 11 read-only tools remain available. The opt-in twelfth tool, `ontology_evidence_pack`, runs 1–8 uniquely identified search/neighbor queries against one immutable snapshot. Snapshot and quality metadata appear once; `n:` and `e:` references identify exact projected node and evidence representations. Reuse the returned references rather than assuming a node ID identifies every representation.

```json
{
  "workspace_id": "registered-workspace-id",
  "requests": [
    {"id": "symbols", "operation": "search", "term": "OrderService", "limit": 20},
    {"id": "callers", "operation": "neighbors", "symbol": "OrderService", "direction": "incoming", "limit": 100}
  ],
  "node_fields": ["qualifiedName", "path", "metadata"],
  "max_results": 100,
  "max_payload_bytes": 65536,
  "max_wire_bytes": 150000
}
```

- `node_fields` selects `qualifiedName`, `path`, `metadata`; all are included by default. `[]` omits those optional fields. Identity fields remain when available; `omittedNodeFields` states the projection.
- `max_results`: 1–200 returned rows. `max_payload_bytes`: 16384–262144 canonical UTF-8 structured bytes. `max_wire_bytes`: 16384–1048576 actual JSON-RPC response bytes, including the request ID, duplicated compatibility text and newline. `payloadBytes` and `wireBytes` report separate measurements, not token estimates.
- Follow `continuation.tool` with its exact `continuation.arguments`. The snapshot, selectors and budgets remain pinned. Search advances its underlying offset; neighbor pages cover only the originally bounded traversal. A final `query_limit` remains partial and does not prove graph completeness.
- `excludedReasons`, item errors and field omissions remain explicit. A row and its path evidence are admitted together. If no row fits, the tool returns an actionable error rather than a cursor that cannot advance. Scope describes the underlying query, not only the current page.

## Human HTML and RDF validation

Open generated `graph.html` locally. Choose English, 한국어, 日本語, 简体中文 or Русский; switch between the map and independent paged list while retaining selection and filters. The change view shows previous/current values, and relationship inspection exposes static path evidence. Empty, missing and truncated results retain their limits. Offline HTML represents its generated snapshot; it does not inspect today's source files or establish runtime execution.

RDF 1.1 Turtle, `RelationshipEvidence` and the bounded PROV-O lineage remain exports of the same ontology. Development/CI validation can use the pinned optional dependencies in `requirements-validation.txt` for an independent RDF parser, SHACL shapes and exact JSON/Turtle triple parity. These dependencies are not needed by the plugin runtime; a missing dependency reports unavailable validation, not a pass.

```bash
python3 scripts/validate_rdf_contract.py --json "/path/ontology.json" --turtle "/path/ontology.ttl" --lineage "/path/lineage.ttl"
```

A structural RDF pass is not source-analysis accuracy, complete PROV conformance or runtime proof. Conservative Java dispatch and Python definition-time/dynamic behavior retain their documented partial boundaries. JS/TS analysis and cross-module resolution remain outside this release's supported graph analysis.

[Local MCP setup](local-mcp.md) · [Privacy operations](privacy-operations.md)
