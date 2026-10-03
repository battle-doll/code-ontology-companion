# Normal and large analysis modes

Normal mode maintains one scoped ontology and graph. Large analysis mode composes independent module snapshots into a local catalog, with separate workflows for producing evidence, retrieving it for AI, and browsing it as a person. Both use the same deterministic Java/Spring and Python adapters. Neither mode uses a language model to generate observed structure, runs the target, downloads dependencies, or sends source over the network.

| Workflow | Normal mode | Large analysis mode |
| --- | --- | --- |
| Produce ontology | One workspace and immutable snapshot | Explicit modules, sequential analysis, consistent catalog of pinned snapshots |
| AI retrieval | Search and bounded impact in that workspace | Discover module metadata, search selected modules in pages, inspect impact within one module |
| Human browsing | One graph with cumulative layers | Catalog of module counts and sizes, then a chosen module's cumulative layers |

## Choose the module boundaries

Use 1–128 explicit, repository-relative directories, such as `services/orders/src/main` and `services/catalog/src/main`. The roots must exist, contain supported source, and not overlap. Duplicate roots, traversal, links/reparse points, excluded paths and ancestor/descendant selections are rejected. Select source directories rather than generated output, dependency caches, vendored copies, datasets or images. Unsupported languages remain unsupported. Selection describes analysis scope, not deployment truth.

Normal limits apply separately to each module: at most 25,000 supported source files, 512 MiB of supported source bytes and 2 MiB per source file, plus the existing graph limits. The aggregate may exceed a single module's byte limit; an oversized individual module still needs a smaller explicit partition. Repository disk size alone cannot establish feasibility. Performance on a 1–2 GiB production source tree has not been measured.

## Run the workflow

Resolve `$COMPANION` to the trusted bundle's absolute `scripts/companion.py` path, as described in the parent skill. Begin with the no-write preflight:

```bash
python3 "$COMPANION" large-preflight --repo "/path/to/repo" \
  --module-root services/orders/src/main --module-root services/catalog/src/main
```

Review module scope and supported-source counts. After authorization, create a new workspace outside the repository:

```bash
python3 "$COMPANION" large-init --repo "/path/to/repo" \
  --workspace "/path/to/large-workspace" --label "Service catalog" \
  --module-root services/orders/src/main --module-root services/catalog/src/main \
  --authorized
python3 "$COMPANION" large-status --workspace "/path/to/large-workspace"
python3 "$COMPANION" large-sync --workspace "/path/to/large-workspace"
```

Each selected module has an ordinary child workspace. Processing is sequential; unchanged modules reuse their existing immutable snapshots. `large-sync --force` rebuilds every selected module, including display assets. Module definitions are fixed for a workspace; use a new catalog workspace when the intended partition changes. Ordinary registered-workspace MCP tools can inspect child workspaces. Version 0.8.0 also exposes registered large parents through `ontology_list_workspaces` with `mode: "large"` and provides `ontology_large_modules`, `ontology_large_search` and `ontology_large_neighbors` over the same pinned catalog reads. Use local MCP when actually exposed, with the verified CLI as fallback. See [local-mcp.md](local-mcp.md) for the exact registered-ID contracts.

## Retrieve evidence for AI

Start with `large-modules`. It reads snapshot metadata and source manifests, without loading ontology graphs or rescanning source. The result includes module roots, pinned workspace and snapshot IDs, analyzer versions, file counts, supported-source bytes, and node/edge counts. Filter module names with `--term`; use `--offset` and `--limit` to retrieve a bounded page.

```bash
python3 "$COMPANION" large-modules --workspace "/path/to/large-workspace" \
  --term "orders" --offset 0 --limit 20
```

Keep the returned `catalogSnapshotId` as `$CATALOG_SNAPSHOT` for this investigation. Pass it to every subsequent retrieval call with `--catalog-snapshot`; this preserves one aggregate view even if another operation refreshes the workspace between pages. If omitted, each call selects the current catalog independently.

```bash
python3 "$COMPANION" large-query --workspace "/path/to/large-workspace" \
  --catalog-snapshot "$CATALOG_SNAPSHOT" \
  --module-root services/orders/src/main --term "OrderService" --offset 0 --limit 20
python3 "$COMPANION" large-impact --workspace "/path/to/large-workspace" \
  --catalog-snapshot "$CATALOG_SNAPSHOT" \
  --module-root services/orders/src/main --symbol "EXACT_NODE_ID_FROM_QUERY" \
  --depth 2 --direction both --limit 100
```

Repeat `--module-root` on `large-query` to search several exact configured roots; omitting it searches all modules sequentially. Ancestor paths, aliases, traversal, duplicate roots, and roots outside the catalog are rejected. One shared result limit of 1–200 applies across the selected modules. Pages follow configured module order, then each module's search ranking. Use the returned `nextOffset`; `null` means no later page. Results carry module scope, snapshot provenance, external/unresolved scope information, and truncation. Module occurrence counts are not globally deduplicated symbol counts.

`large-impact` requires one exact configured module root and follows its pinned snapshot, with depth 1–5, incoming/outgoing/both direction and a CLI result limit of 1–200. Prefer the exact node ID returned by search; ambiguous names require selection. Impact remains within that module, explicitly reports unsupported cross-module resolution, and never merges graphs or infers links between modules. Ordinary child-workspace MCP tools can also use the module workspace ID and pinned snapshot ID returned by discovery.

Discovery, search and impact are read-only and report `freshness: pinned_snapshot`. They do not claim the source is still current: use `large-status` for a source freshness check. Missing matches and missing paths do not establish absence in the actual program.

## Browse as a person

Open the returned catalog's `index.html`. It identifies **Large analysis mode**, shows each module's source count, supported-source bytes, node/edge counts and pinned snapshot, and links to that module's normal-mode graph. The catalog has no scripts or network dependencies and does not load all module graphs at once.

Use the graph's separate **Add layer** and **Remove layer** buttons to control cumulative depth across all regions of that module. Earlier layers remain visible as the next layer is added. Adding a layer expands its layout and view; removing one reduces them. Entering layer 4 or any deeper layer requires a load-warning confirmation. The ordinary zoom controls remain separate. Layer expansion covers the selected module; it does not combine every module in the catalog into one graph.

## Consistency and partial failure

A catalog pins each child workspace, snapshot ID, source fingerprint and analyzer version. It is promoted only after every module succeeds and final source-manifest checks pass. Unchanged runs preserve the current catalog. A failed refresh leaves the previous catalog selected; already refreshed child workspaces can be newer than that catalog. Treat the catalog's pinned snapshots as the aggregate result, not each child's independent current pointer. Retry `large-sync` to finish the update. Old catalogs and their pinned snapshots remain immutable.

Search uses the pinned snapshots and a shared result limit, reports module provenance and truncation, and does not synthesize links between modules. Identical package or external symbol IDs can occur in multiple modules. Summed node/edge counts are module totals, not a globally deduplicated ontology. A call to another selected module may still appear as an unresolved or external boundary inside the caller's snapshot. This first large-project mode is a module catalog, not compiler-wide cross-module call resolution.

## Local data

The parent workspace stores private repository location and selected roots. Child workspaces store source hashes, names, relative paths, line evidence, graphs and immutable history under the same ordinary data boundaries. The portable catalog uses relative module links and no source bodies. It still exposes module names and counts; do not upload it or its children without the user's authorization. Refreshes retain history, so disk use grows as modules change.
