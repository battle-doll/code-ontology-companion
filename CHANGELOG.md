# Changelog

[English](CHANGELOG.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/CHANGELOG.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/CHANGELOG.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/CHANGELOG.md)

## 0.4.0 - 2026-08-10

- Focus all product, policy, submission, architecture, reference, and localized
  documentation on the supported general-purpose ontology workflows, and
  remove the obsolete project-specific receipt CLI, implementation, tests, and
  evaluation cases.
- Add a source-level reverse-engineering guide for turning existing authorized
  Java/Spring or Python code into immutable JSON, RDF/Turtle, lineage, and an
  interactive offline ontology, including refresh and comparison usage.
- Include Windows, macOS, and Linux setup instructions and discoverable prompts
  for the optional read-only local MCP server in the official Skills bundle;
  keep the matching server and launcher in the complete GitHub package.
- Strengthen Windows behavior with an actual Python 3.9-or-newer launcher probe,
  UTF-8 MCP stdio, and fail-closed link/reparse checks for managed snapshot,
  staging, and release-source directories.
- Generate the local Ollama prompt role vocabulary from the canonical schema,
  keep `Validate` consistent across prompt and validation, and retain the
  bounded deterministic batching introduced in 0.3.5.
- Add source-wide release checks that prevent removed project-specific terms,
  commands, schemas, and profile labels from returning.

## 0.3.5 - 2026-08-03

- Partition optional local Ollama enrichment deterministically into requests of
  at most 20 candidates and at most 16 KiB of serialized portable metadata.
- Disable model thinking, cap each request context at 8,192 tokens and each
  response at 2,048 output tokens, and allow up to 180 seconds per local
  request so bounded enrichment can complete on supported local hardware.
- Validate every batch before atomically publishing one inferred sidecar; a
  failed, incomplete, or partial run leaves no enrichment artifact. Suggestions
  with unsupported role labels are omitted and counted, identical-role
  duplicates use the lower confidence, and conflicting-role nodes are omitted.

## 0.3.4 - 2026-08-02

- Separate the official Skills-only bundle from the complete local plugin
  package while keeping the general-purpose ontology workflow consistent.
- Add deterministic, fail-closed release validation for both package profiles
  and preserve multilingual release documentation.

## 0.3.3 - 2026-08-02

- Publish the full local-first architecture and staged version roadmap while
  keeping version 0.3.2 as the unchanged functional baseline.
- Add English, Korean, Japanese, and Simplified Chinese entry points and
  translations for every human-facing product, operations, safety, policy,
  submission, and reference document.
- Preserve English licenses and policy documents as the authoritative source,
  label legal translations as informational, and validate documentation
  language parity in the source package.

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
- Harden policy-flow extraction against stale graphs, test-only or unused
  paths, and ambiguous static relationships.

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
