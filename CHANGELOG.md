# Changelog

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
