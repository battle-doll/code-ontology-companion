# Code Ontology Companion architecture

[English](ARCHITECTURE_AND_ROADMAP.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/ARCHITECTURE_AND_ROADMAP.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/ARCHITECTURE_AND_ROADMAP.md)

This document describes the implemented version 0.5.1 product. Code Ontology Companion turns
an authorized Java/Spring or Python repository into immutable local ontology
snapshots without importing, building, testing, or executing the target code.
The deterministic analyzer and read-only MCP server make no direct network
requests. The supported runtime is Python 3.9 or newer on Windows, macOS, and
Linux.

## 1. Components

| Component | Supported responsibility |
| --- | --- |
| `manage-code-ontology` skill | Authorization, preflight, workspace lifecycle, query, evidence, local MCP setup, and optional local-LLM consent workflow |
| `code_ontology_core.py` | Deterministic Java/Spring and Python static extraction, relationship-evidence attribution, adapter coverage, and bounded JSON, RDF, report, and workbench data |
| `companion.py` | Read-only checks, immutable snapshot creation, atomic refresh, query, impact, history, diff, and lineage |
| `mcp/server.py` | Seven registered-workspace-only read tools over local stdio |
| `local_llm.py` | Separately authorized, fixed-loopback Ollama metadata enrichment stored as inferred sidecars |
| Offline workbench | Full-index search, accessible 2D structure view, optional 3D constellation, bounded relationship neighborhoods, semantic lenses, details, and current/previous comparison |

The implementation uses the Python standard library. Cytoscape.js and ELK.js
are integrity-pinned inside the generated self-contained HTML workbench. The
optional 3D projection uses the browser's built-in Canvas2D API rather than a
new library or WebGL. The browser view needs no CDN, package installation,
worker, telemetry, or network service.

## 2. Data flow

```text
authorized source repository
  -> protected source discovery
  -> private stable source manifest
  -> deterministic staging analysis
  -> JSON / RDF Turtle / report / offline workbench validation
  -> immutable snapshot promotion
  -> current snapshot pointer
  -> CLI and registered-workspace local MCP reads
  -> optional consented Ollama inferred sidecar
```

`doctor` and `preflight` are read-only. `init` requires explicit authorization
and a new workspace outside the repository. `sync` analyzes in staging and
promotes only a complete, stable snapshot. If the source changes or validation
fails, the last known-good snapshot remains current.

## 3. Supported static analysis

### Java and Spring

The analyzer maps packages, imports, classes, interfaces, records, methods,
constructors, fields, inheritance, annotations, calls, and basic dependencies.
It recognizes common Spring stereotypes, `@Bean`, constructor and field
injection, AspectJ advice, transaction, async, cache, authorization, and retry
proxy signals. It also maps validated dotted policy accessor identifiers to the
control-flow branches they guard without retaining surrounding arbitrary string
literals.

Java call resolution remains conservative. An unqualified call or
`this.method(...)` resolves to a method declared by the same owner only when
exactly one candidate matches the method name and argument count. A recognized
imported `Type.method(...)` call becomes an `ExternalCallable`. Overloaded
same-arity methods, dynamic receivers, declarations, constructors, annotations,
control keywords, comments, and literals do not create speculative call edges.

### Python

The analyzer maps modules, imports, classes, functions, async functions,
decorators, calls, and inheritance. It resolves common aliases, relative
imports, lexical scopes, nested functions, explicit `self` and `cls` calls, and
`src/` layouts. Deterministic heuristics label Extract, Transform, Load,
Validate, and Orchestrate pipeline roles.

### Resource and filesystem protections

Only regular `.java` and `.py` files within documented size, count, and graph
limits are read. Secret-like names, environment files, private keys, links,
Windows reparse points, special files, dependencies, VCS data, generated
outputs, IDE data, caches, and virtual environments are excluded. Repository,
workspace, snapshot, and staging containment checks fail closed.

### Relationship evidence and adapter coverage

Version 0.5.1 retains the legacy `source`, `target`, and `type` relationship
triple and all stable node/edge identities. Each relationship additionally has
an `evidence` array. Every evidence item contains:

- a stable `rule_id` for the deterministic extraction rule;
- a qualitative `basis`: `direct_syntax`, `resolved_static`,
  `framework_semantic`, or `name_heuristic`;
- a `runtime_status`: `not_applicable` or `runtime_unknown`;
- optional repository-relative `path`, `line_start`, and `line_end` fields;
- bounded `limitations` that explain material uncertainty or unsupported
  runtime conditions.

`document.quality` has contract version `1.0`. Its
`relationship_evidence` summary reports `total_edges`, `documented_edges`,
`missing_evidence`, `coverage_percent`, `basis_counts`, and
`runtime_status_counts`. Its `adapters` matrix reports Java and Python
`status`, deterministic `capabilities`, and `unsupported_runtime` areas.
Each adapter also reports whether that language was `detected` in the snapshot;
the matrix still exposes both bounded product adapters when only one language
is present.
The `interpretation` text keeps these indicators inside the static-evidence
boundary. Qualitative bases are not numeric probabilities, and zero parse
warnings do not prove complete static or runtime coverage.

## 4. Snapshot and lineage model

Every immutable snapshot contains:

- `ontology.json`, the operational search and relationship index;
- `ontology.ttl`, the RDF 1.1 Turtle exchange representation;
- `report.md`, a human-readable summary;
- `graph.html`, the self-contained interactive workbench;
- `snapshot.json`, snapshot metadata and counts;
- `source-manifest.json`, the private freshness and integrity manifest.

The workspace also maintains append-only `lineage.jsonl` and portable
`lineage.ttl`. Evidence classes remain distinct: `observed`, `declared`,
`inferred`, `validated`, and `approved`. RDF uses the stable `co:` vocabulary
and PROV-O-compatible lineage. RDF 1.1 stores can import the Turtle files; each
store can map its own indexes, rules, and extensions.

RDF remains backward compatible: every legacy direct triple is preserved, and
additional `RelationshipEvidence` resources express rule, basis, source span,
runtime status, and limitations. Consumers that understand only the legacy
triples can continue to read version 0.5.1 exports.

### Offline 2D and 3D presentation

The visualization plane consumes the portable, sanitized snapshot payload; it
does not create a second ontology or change relationship semantics. The default
`2D structure` view and optional `3D space` constellation display the same
selected, bounded neighborhood and keep the same stable identities, filters,
details, evidence, and source limitations. The complete repository index stays
searchable, but the rendered view has explicit node, edge, depth, and frame
budgets so visual density cannot turn an immutable snapshot into an unbounded
browser workload.

The 3D view uses a deterministic static layout projected onto Canvas2D. Pointer
orbit and zoom have keyboard equivalents for orbit, zoom, camera reset, node
traversal, selection, and return to the root symbol. Node and edge selection
continues into the existing DOM details and relationship-evidence panels.
Search results, relationship lists, details, and the 2D graph remain equivalent
navigation paths because a spatial canvas is not itself a screen-reader model.

The workbench honors `prefers-reduced-motion` and forced-colors/high-contrast
preferences, presents mode and selection status through assistive semantics,
pauses rendering when its page is hidden, and returns safely to 2D when canvas
rendering cannot start or fails. Accessibility is a tested product contract and
WCAG 2.2 AA design target; it is not represented as a blanket conformance claim
without separate manual assistive-technology and browser verification.

## 5. Read-only local MCP

The local server communicates over stdio, opens no listening port, and accepts
random registered `workspace_id` values instead of arbitrary filesystem paths.
It exposes exactly seven read tools:

| Tool | Result |
| --- | --- |
| `ontology_list_workspaces` | Registered and stale workspace entries |
| `ontology_status` | Snapshot identity, freshness, counts, and pipeline health |
| `ontology_search` | Bounded static symbol matches |
| `ontology_neighbors` | Bounded relationship neighborhood |
| `ontology_history` | Immutable snapshot history |
| `ontology_changes` | Structural current/previous changes |
| `ontology_lineage` | Existing provenance events and evidence classes |

All tools declare `readOnlyHint=true`, `openWorldHint=false`,
`destructiveHint=false`, and `idempotentHint=true`. Initialization, refresh,
lineage writes, deletion, upload, package installation, and target execution
remain explicit CLI workflows rather than MCP tools.

The complete plugin package bundles the server and launcher. Direct Python stdio
configuration supports Windows (`py -3`), macOS, and Linux (`python3`). The skill
includes the exact configuration and fresh-process verification workflow in
`references/local-mcp.md`.

## 6. Optional local Ollama enrichment

Deterministic analysis is complete without a model. Detection executes nothing,
connects nowhere, and writes nothing. For an initialized workspace, the skill
checks existing configuration first. Only after the user sees the fixed
`127.0.0.1:11434` endpoint, portable-metadata scope, resource impact, retention,
and residual Ollama risks may it inspect existing models and configure one
eligible completion model.

Enrichment sends bounded node identifiers, names, types, qualified names,
repository-relative paths, annotations, and observed relationships. It excludes
source bodies, comments, arbitrary strings, secrets, absolute paths, manifests,
source fingerprints, and raw file hashes. Requests are partitioned in stable
order into at most 20 candidates and 16 KiB, use `think=false`, `num_ctx=8192`,
`num_predict=2048`, and a maximum 180-second timeout. Each response is validated
against a strict JSON schema before one create-only inferred sidecar is
atomically published. Raw prompts and raw responses are not retained, and
inference never changes the observed ontology or RDF.

## 7. Privacy and evidence boundaries

Portable artifacts and normal MCP responses omit the absolute repository path
and full file fingerprints. Private workspace configuration stores the
repository path, while the private source manifest stores relative paths,
sizes, and SHA-256 values for freshness and integrity. Symbols and relative
paths can still be confidential and should remain local unless sharing is
separately authorized.

Static relationships show source structure and change proximity. They do not
establish runtime execution, active framework configuration, security,
correctness, or causation. Reflection, generated code, runtime bean conditions,
dynamic proxies, dependency versions, external configuration, dynamic imports,
and metaprogramming can change runtime behavior and require independent runtime
evidence.

## 8. Distribution and validation

The repository builds two deterministic artifacts:

- the complete plugin ZIP with the skill, local MCP server, launcher, policy
  documents, reviewer cases, and release records;
- the official Skills-only ZIP with the skill workflow, analyzer, workbench,
  optional local-LLM helper, and local MCP setup reference.

Both archives are built twice and must be byte-identical. Source validation,
archive structure and checksum validation, safe extracted smoke tests, document
validation, Python compilation, and the unit suite run before release. CI runs
the supported Python 3.9 and 3.12 matrix on Ubuntu, macOS, and Windows.

The release contract is versioned through `.codex-plugin/plugin.json`, source
constants, MCP metadata, evaluation metadata, `CHANGELOG.md`, SBOM, artifact
names, validators, and CI upload paths.

Version 0.5.1 defines executable ontology and visualization quality gates. The
ontology fixture contract declares expected and prohibited nodes and
relationships plus required evidence and adapter-coverage properties. It is a
deterministic analyzer gate and never imports, builds, tests, or runs the target
repository. The visualization fixture checks the offline/self-contained
contract, 2D default and 3D opt-in mode, finite rendering budgets,
deterministic positioning, motion and hidden-page behavior, keyboard and
pointer controls, assistive markers, high-contrast support, legacy payload
fallback, and safe 2D recovery. Release claims must report actual validation
results separately;
this architecture description does not itself assert that a particular build
or CI run passed.

## 9. Current roadmap

This roadmap is directional, not a promise of dates. Version 0.5.1 advances the
historical 0.5.x larger-graph visualization direction while clearly separating
the shipped bounded offline view from optional storage/query work that remains
future work.

### Shipped since 0.5.0: evidence quality and spatial exploration

- bounded Java and Python adapter coverage reporting;
- clearer static-evidence basis and unsupported-runtime indicators;
- additive, source-attributed relationship evidence with legacy compatibility;
- conservative same-owner Java calls and explicit calls through recognized
  imported types;
- executable golden/forbidden quality gates while preserving the
  zero-dependency default.
- an opt-in Canvas2D 3D constellation over the same bounded neighborhood as the
  default 2D structure view;
- keyboard and pointer exploration, reduced-motion and high-contrast behavior,
  assistive status, and safe 2D fallback without adding a network or worker;
- explicit visualization budgets and deterministic static positioning.

### Directional future work

- improve setup diagnostics, progress reporting, and actionable failures;
- improve foreground watcher control, debouncing, and single-flight behavior;
- consider bounded parser or language adapters only when quality fixtures and
  privacy constraints justify them;
- consider optional RDF-store, SPARQL, or larger-graph profiles without making
  them required or weakening the immutable file-snapshot default;
- consider build, configuration, and authenticated read-only runtime evidence
  only as separately bounded adapters that cannot promote static evidence into
  runtime fact.

New languages, target execution, live runtime tracing, autonomous code changes,
deployment authority, security verdicts, and promotion of local-LLM inference
into observed evidence are not version 0.5.1 capabilities. Version 0.5.1 does
not include a graph database, SPARQL or REST profile, live layout service, or
whole-repository 3D rendering.
