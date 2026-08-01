# Changelog

## 0.3.2 - 2026-08-02

- Require every tracked release change to receive a new semantic version and a
  dated changelog entry, with baseline-aware CI enforcement, synchronized
  metadata, and deterministic artifacts.
- Add a release checklist that refreshes the plugin's registered self-ontology
  from the final source state and records declared and validated lineage.
- Preserve compatible, consented local-LLM workspace configuration across patch
  releases while rejecting malformed or future-version provenance.

## 0.3.1 - 2026-08-01

- Improve deterministic Java accuracy for generic and record declarations,
  multi-interface hierarchies, nested imports, verified Spring annotations,
  same-package wildcard shadowing, compact/generic constructor detection,
  conservative constructor injection, and `@Bean` parameter injection.
- Improve Python accuracy for relative and aliased imports, internal calls,
  lexical shadowing, nested functions, explicit `self`/`cls` calls, `src/`
  layouts, comprehension scopes, bounded AST depth/count, and token-based
  pipeline-role classification.
- Add fail-closed source, graph, impact, and output resource limits.
- Add optional, workspace-scoped Ollama enrichment after explicit consent. It
  uses fixed IPv4 loopback only, rejects reported cloud/remote markers or
  missing required metadata, sends a bounded portable metadata subset, requests
  immediate model unload with `keep_alive=0`, and stores create-only `inferred`
  sidecars without modifying observed ontology evidence.
- Harden Git revision metadata reads and bounded MCP response contracts.
- Add exact, reproducible validation for full and public Skills-only release
  archives, including extracted smoke checks.
- Normalize text checkouts across platforms and keep Windows file-change checks
  compatible with Python 3.12 while retaining file identity, size, and mtime guards.

## 0.3.0 - 2026-07-31

- Replace the ID-ordered ring graph with a self-contained interactive ontology
  workbench: full-index search, bounded relationship lenses, guided exploration,
  human-readable details, and current-versus-previous snapshot changes.
- Vendor and integrity-pin Cytoscape.js 3.34.0 and ELK.js 0.12.0 for local
  same-thread layout with no CDN, install step, telemetry, or network access.
- Keep the core ontology/RDF 1.0 vocabulary stable and preserve the static
  evidence boundary: displayed relationships do not establish runtime causality.

## 0.2.0 - 2026-07-31

- Add Java `PolicyLeaf` to `RuntimeBranch` static data-flow edges while retaining
  no arbitrary string literals.
- Add an explicitly authorized, local-only producer for exact
  `aether.runtime-effective-ontology-binding/v1` immutable receipts.
- Fail closed on stale/tampered graphs, test-only or unused paths, known active
  ladder shadows, disabled trailing configuration, ambiguous paths, and
  existing outputs.
- Document that runtime-binding evidence is static reachability, not runtime,
  order, safety, or profit-causation proof.

## 0.1.1 - 2026-07-30

- Refuse lineage journal symlinks, reparse points, hard links, and file-swap
  races before append or read.
- Reuse descriptor-based, bounded source reads for snapshot manifests so
  discovery-to-read symlink swaps and oversize growth fail closed.
- Verify file identity and stable metadata before, during, and after protected
  reads, including on platforms without `O_NOFOLLOW`.
- Add regression coverage for symlink targets, open-time swaps, oversize
  growth, and raw-byte manifest hashing.

## 0.1.0 - 2026-07-29

- Add deterministic Java/Spring and Python static ontology extraction.
- Add immutable snapshots, stable refresh fingerprints, staging validation,
  atomic promotion, and last-known-good recovery.
- Add RDF 1.1 Turtle export and PROV-O-compatible lineage.
- Add structural query, bounded impact, snapshot history, and diff commands.
- Add a self-contained offline graph.
- Add seven registered-workspace-only, read-only local MCP tools.
- Add privacy, terms, security, threat-model, SBOM, reviewer evals, and
  deterministic release packaging.
