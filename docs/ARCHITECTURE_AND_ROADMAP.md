# Code Ontology Companion architecture

[English](ARCHITECTURE_AND_ROADMAP.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/ARCHITECTURE_AND_ROADMAP.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/ARCHITECTURE_AND_ROADMAP.md)

This document describes the implemented product. Code Ontology Companion turns
an authorized Java/Spring or Python repository into immutable local ontology
snapshots without importing, building, testing, or executing the target code.
The deterministic analyzer and read-only MCP server make no direct network
requests. The supported runtime is Python 3.9 or newer on Windows, macOS, and
Linux.

## 1. Components

| Component | Supported responsibility |
| --- | --- |
| `manage-code-ontology` skill | Authorization, preflight, workspace lifecycle, query, evidence, local MCP setup, and optional local-LLM consent workflow |
| `code_ontology_core.py` | Deterministic Java/Spring and Python static extraction plus bounded JSON, RDF, report, and workbench data |
| `companion.py` | Read-only checks, immutable snapshot creation, atomic refresh, query, impact, history, diff, and lineage |
| `mcp/server.py` | Seven registered-workspace-only read tools over local stdio |
| `local_llm.py` | Separately authorized, fixed-loopback Ollama metadata enrichment stored as inferred sidecars |
| Offline workbench | Full-index search, bounded relationship neighborhoods, semantic lenses, details, and current/previous comparison |

The implementation uses the Python standard library. Cytoscape.js and ELK.js
are integrity-pinned inside the generated self-contained HTML workbench, so the
browser view needs no CDN, package installation, worker, telemetry, or network
service.

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
