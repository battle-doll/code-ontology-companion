# Code Ontology Companion: Full Architecture and Version Roadmap

[English](ARCHITECTURE_AND_ROADMAP.md) | [한국어](ko/ARCHITECTURE_AND_ROADMAP.md) | [日本語](ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](zh-CN/ARCHITECTURE_AND_ROADMAP.md)

## 1. Purpose

Code Ontology Companion is evolving toward a local-first AI data pipeline that
turns authorized application source, configuration, build metadata, and bounded
runtime evidence into a portable, versioned code ontology. The pipeline should
support low-cost code understanding, change impact analysis, evidence lineage,
and carefully governed improvement workflows without granting an LLM direct
write, deployment, order, credential, or funds authority.

Version 0.3.2 established the first stable functional baseline and version
0.3.3 published its multilingual architecture and release documentation.
Version 0.3.4 is the current public baseline: its Skills-only/OpenAI submission
profile contains only the general-purpose ontology workflow, while optional
downstream personal-project compatibility code remains in the separate
full/local GitHub profile. The current product includes deterministic
Java/Spring and Python static analysis, immutable ontology snapshots, RDF 1.1
Turtle export, PROV-O-compatible lineage, offline visualization, CLI
exploration, optional consent-based Ollama enrichment, and a read-only local
MCP profile. It is not yet the complete always-on pipeline described below.

## 2. Engineering principles

- **Local first:** use local storage, analysis, visualization, and models by
  default. External resources are optional fallbacks configured explicitly by
  the user.
- **KISS:** keep the zero-dependency file snapshot path useful even when no
  graph database, model, daemon, or network service is available.
- **YAGNI:** add Graph DB, SPARQL, REST, CI automation, and model installation as
  optional adapters only when a validated use case needs them.
- **DRY:** keep one canonical ontology and provenance model. Every storage,
  query, visualization, and improvement component consumes the same immutable
  identities and receipts.
- **Deterministic core:** static analysis, fingerprints, candidate identities,
  validation, and promotion gates remain deterministic. LLM output is advisory.
- **Fail closed:** stale source, ambiguous bindings, malformed evidence,
  unsupported runtime state, signature failure, or partial mutation must never
  be interpreted as approval.
- **Portable by design:** RDF 1.1 Turtle and documented provenance remain the
  migration boundary between file storage and optional ontology stores.

## 3. Target architecture

```text
Authorized application
  source + build + configuration + bounded runtime evidence
                         |
                         v
  Host preflight and explicit setup orchestrator
  - OS/CPU/RAM/disk/runtime detection
  - existing Python, Java, Ollama, and store discovery
  - preview and consent before any installation or service change
                         |
                         v
  Input adapters
  - Java/Spring       - Python           - future language adapters
  - build metadata    - configuration    - authenticated read-only runtime facts
                         |
                         v
  Deterministic analysis and normalization
  - symbols, calls, imports, inheritance, DI/AOP/proxy signals
  - pipeline roles, policy leaves, runtime branches, evidence bindings
                         |
                         v
  Canonical ontology and provenance model
  - RDF 1.1 / optional OWL profile / SHACL validation profile
  - observed, declared, inferred, validated, approved evidence classes
  - immutable snapshots, diffs, lineage, release and policy identities
                         |
          +--------------+---------------+
          |                              |
          v                              v
  Default file snapshot store     Optional store adapters
  JSON + Turtle + lineage         Jena/RDF4J/GraphDB/Stardog or compatible
          |                              |
          +--------------+---------------+
                         |
                         v
  Query and presentation plane
  - Codex Skill/CLI       - read-only MCP
  - optional SPARQL/REST  - interactive graph and version comparison
                         |
                         v
  Optional advisory intelligence
  - existing local LLM discovery and user-selected enrichment
  - numberless hypotheses and explanations only
  - inferred sidecars remain separate from observed facts
                         |
                         v
  Separate governed improvement controller
  - preregistered candidates and deterministic fingerprints
  - paired replay, purged OOS, cost calibration, natural shadow evidence
  - domain policy gates, signed admission, CAS, canary, rollback
  - issue/PR or policy activation only through independent authority gates
                         |
                         v
  New observed outcomes and source changes return to the evidence pipeline
```

The application server is one producer and consumer within this system; it is
not the whole AI data pipeline. A Spring Boot/Tomcat application may expose
authenticated read-only runtime facts and consume a verified policy, while the
ontology, experiment, validation, and governance stages remain separate.

## 4. Architectural planes

### 4.1 Setup and host discovery

The future setup orchestrator discovers existing components before proposing
anything new. It should prefer the operating system's supported package manager
and locally available runtimes. Every installation, model download, service
start, port binding, credential use, or external endpoint requires an explicit
preview and user authorization. A plugin installation alone must not silently
modify the host.

Minimum profiles:

1. **Zero-install profile:** bundled Python scripts, immutable files, CLI, and
   offline workbench.
2. **Full local profile:** zero-install profile plus bundled read-only stdio MCP.
3. **Extended local profile:** optional graph store, SPARQL/REST management
   service, foreground or OS-managed refresh trigger, and existing local LLM.
4. **External fallback profile:** user-configured remote RDF or model service
   only when local resources are insufficient and data boundaries are accepted.

Indicative user guidance, not a hard compatibility promise:

| Profile | macOS guide | Windows guide | Intended use |
| --- | --- | --- | --- |
| File-only minimum | 4 CPU cores, 8 GiB RAM, 5 GiB free SSD | x64, 4 CPU cores, 8 GiB RAM, 5 GiB free SSD | Small/medium repositories without a graph DB or local LLM |
| Recommended local | Apple silicon, 16 GiB RAM, 20 GiB free SSD | 6 or more CPU cores, 16 GiB RAM, 20 GiB free SSD | Current full-local workflow and one light optional service at a time |
| Extended local | Apple silicon, 24-32 GiB RAM, 50 GiB or more free SSD | 8 or more CPU cores, 32 GiB RAM, 50 GiB or more free SSD; an 8 GiB or larger GPU is optional | Larger repositories, an RDF store, and a quantized 7-9B-class model together |

Low-spec machines retain the file-only profile with graph storage and model
enrichment disabled. Preflight must measure the actual repository, selected
model, and store rather than approving installation from this table alone.

### 4.2 Input and language adapters

Each language adapter emits the canonical symbol and relationship model rather
than defining its own ontology. Java/Spring analysis covers packages, types,
methods, records, imports, inheritance, bean declarations, injection,
annotations, aspects, transactions, asynchronous execution, cache,
authorization, retry, and proxy signals. Python analysis covers modules,
classes, functions, decorators, calls, imports, inheritance, and data-pipeline
roles.

Future adapters should use a bounded interface for discovery, parsing,
normalization, validation, and capability reporting. Build and configuration
adapters should bind source structure to dependency versions and effective
configuration without executing target code. Runtime adapters must be
authenticated, read-only, sanitized, expiry-bound, and separated from static
evidence.

### 4.3 Canonical ontology

RDF 1.1 Turtle remains the portability baseline. The complete design may add a
documented OWL profile for interoperable semantics and SHACL shapes for
artifact validation, but no reasoner output becomes an observed fact. All
inferences retain their producer, algorithm or model identity, source snapshot,
timestamp, and validation state.

The provenance model links:

```text
source revision
  -> ontology snapshot
  -> hypothesis
  -> candidate and policy pack
  -> dataset, replay, OOS, cost, and shadow evidence
  -> verdict and admission receipt
  -> canary or deployment
  -> observed outcome
  -> rollback or next experiment
```

This is the basis for statements such as “the stop line changed from 2% to 3%
because of the order-policy improvement on this date,” while preserving whether
the statement was observed, inferred, validated, or approved.

### 4.4 Storage and query

The file store remains the default because it is portable, inspectable,
backup-friendly, and requires no service. Optional store adapters import the
same Turtle and provenance into an RDF-compatible graph database. Store-specific
indexes, reasoning extensions, authentication, ports, and licenses remain
outside the canonical model and must be configured explicitly.

Query capabilities evolve in layers:

- deterministic CLI search, impact, history, diff, and lineage;
- registered-workspace-only read-only MCP;
- optional SPARQL for standards-based graph queries;
- optional localhost REST management and health API;
- Codex natural-language orchestration over bounded deterministic tools.

Natural-language output never upgrades evidence strength.

### 4.5 Refresh and data pipeline

The refresh pipeline uses private source fingerprints to skip unchanged work,
builds changed analysis in staging, validates every artifact, atomically
promotes an immutable snapshot, and preserves the last known-good snapshot on
failure.

The full design adds:

- language-aware per-file incremental parsing;
- explicit Git hook, CI, or foreground watcher triggers;
- debouncing and single-flight leases;
- build/config/runtime evidence adapters;
- provenance-bound partial refresh and dependency invalidation;
- retry without duplicate snapshot or lineage publication.

No permanent watcher or daemon is silently installed.

### 4.6 Local LLM boundary

The deterministic ontology does not require an LLM. When explicitly enabled,
the system discovers eligible existing local models, asks the user to select a
model, sends only bounded portable metadata, and stores normalized suggestions
as separate inferred evidence.

A future installer may propose an appropriate local model after checking CPU,
GPU, memory, disk, operating system, license, and provenance. Downloading or
starting that model still requires explicit consent. Remote/cloud models are an
optional fallback and must never be selected silently.

LLMs may:

- summarize structural changes;
- propose numberless hypotheses;
- explain deterministic verdicts;
- suggest investigation targets.

LLMs may not:

- manufacture observed evidence;
- choose candidate values or candidate ordering;
- sign, approve, promote, deploy, or submit orders;
- relax safety, reconciliation, idempotency, cost, or OOS gates.

### 4.7 Improvement automation boundary

Code Ontology Companion remains a read-oriented knowledge and evidence
component. A separate improvement controller owns experiments and any write
workflow. Domain-specific experiment, policy, deployment, or trading stacks are
downstream extensions in separate projects. They consume versioned evidence
contracts and define their own deterministic evaluation, admission, canary, and
rollback gates; they are not part of the Companion core or public roadmap.

Companion may produce a narrow immutable binding between a policy leaf and a
static production branch only through an optional downstream extension in the
full/local GitHub profile. The public Skills-only/OpenAI submission artifact
excludes that AETHER Lab runtime-binding command, project policy schema,
receipt producer, and extension-specific evaluations. The retained full/local
receipt does not prove runtime execution, safety, profitability, or
authorization to mutate policy or submit an order, and the extension grants no
runtime, policy, order, network, or funds authority.

## 5. Published baseline: version 0.3.4

| Area | Version 0.3.4 | Relationship to the full design |
| --- | --- | --- |
| Product | Public Skills-only Codex Skill, Python CLI, and offline workbench; full/local read-only stdio MCP | Useful local ontology pipeline; not always-on |
| Inputs | Public profile: authorized `.java` and `.py` only | Source core implemented; build/config/runtime adapters pending |
| Java/Spring | Deterministic structural and conservative DI/AOP/proxy signal extraction | Static possibility, not active ApplicationContext truth |
| Python | Deterministic module, symbol, call, import, inheritance, and pipeline-role extraction | Core implemented; adapter SPI pending |
| Ontology | JSON, RDF 1.1 Turtle, stable `co:` vocabulary, PROV-O-compatible lineage | Core implemented; optional OWL/SHACL pending |
| Storage | Immutable file snapshots, atomic current pointer, append-only lineage | Default store implemented; graph DB optional future work |
| Search | Public profile: CLI query/impact/diff/history/lineage and workbench search; full/local profile: seven read-only MCP tools | MCP implemented locally; SPARQL/REST pending |
| Refresh | Fingerprint skip, foreground watch, full staging reanalysis, atomic promotion | Safe refresh implemented; per-file incrementality and managed triggers pending |
| Local LLM | Existing Ollama detection, consented user-selected enrichment, inferred sidecars | Optional enrichment implemented; installation intentionally absent |
| Visualization | Self-contained Cytoscape/ELK workbench with relationship lenses and current/previous comparison | Substantially implemented |
| Project extension evidence | Public profile: none. Full/local GitHub profile only: static `PolicyLeaf -> RuntimeBranch` and create-only mode-`0400` binding receipt for one downstream lab integration | Narrow personal-project compatibility extension, not public core or OpenAI-hosted automation |
| Improvement | No candidate, approval, policy-write, deployment, order, or funds authority | Separate controller required |

The public Skills-only package contains the general-purpose CLI, analyzer,
workbench, references, and optional local-LLM helper. It intentionally omits
the bundled MCP server because the public portal profile and the local stdio
transport are different distribution models. It also omits and does not
advertise the downstream AETHER Lab runtime-binding command, its project policy
schema, its receipt producer, and extension-specific evaluations. The full
local package retains MCP and that optional personal-project extension; neither
adds runtime, policy, order, network, or funds authority.

## 6. Version roadmap

The roadmap is directional, not a promise of dates. Each release remains useful
and safe without requiring the following phase.

### 0.3.3: multilingual documentation and release continuity

- publish the full architecture and version roadmap;
- provide English, Korean, Japanese, and Simplified Chinese documentation
  entry points;
- preserve English as the authoritative legal and policy source;
- add documentation parity checks and retain deterministic packaging.

### 0.3.4: public-core profile separation

- keep the public Skills-only/OpenAI submission focused on the
  general-purpose ontology workflow;
- exclude the downstream AETHER Lab runtime-binding command, project policy
  schema, receipt producer, and extension-specific evaluations from the public
  artifact and capability claims;
- retain the optional personal-project compatibility extension only in the
  full/local GitHub profile, without runtime, policy, order, network, or funds
  authority;
- validate the profile boundary deterministically and fail closed if excluded
  material appears in the public archive.

### 0.4.x: usability and analyzer adapters

- extract an explicit bounded language-adapter contract;
- improve setup diagnostics, progress reporting, and actionable failures;
- improve foreground watcher control, debouncing, and single-flight behavior;
- add clearer static-confidence and unsupported-runtime indicators;
- preserve the zero-dependency default.

### 0.5.x: optional storage and query extensions

- define a graph-store adapter contract around RDF 1.1 import/export;
- support user-selected Jena, RDF4J, GraphDB, Stardog, or compatible stores
  without making any one product mandatory;
- add optional SPARQL and localhost REST management profiles;
- improve large-graph visualization and multi-snapshot comparison;
- keep the file snapshot store fully supported.

### 0.6.x: local AI data-pipeline operations

- add explicit Git, CI, and managed-local refresh trigger adapters;
- implement language-aware per-file incremental invalidation;
- add build metadata, dependency, effective configuration, and authenticated
  read-only runtime evidence adapters;
- add durable pipeline health, recovery, and lineage receipts;
- provide a consent-based host setup assistant with local-first recommendations.

### 0.7.x: governed improvement integration

- define stable evidence contracts for external experiment controllers;
- connect ontology identity to hypothesis, candidate, replay, OOS, cost, and
  natural-shadow receipts;
- support issue or draft-PR preparation through a separately authorized
  adapter;
- keep code merge, deployment, policy mutation, and runtime actuation outside
  Companion authority.

### 0.8.x-0.9.x: production hardening

- validate cross-platform locks, path safety, and service lifecycle adapters;
- add signed evidence and expiry contracts;
- validate CAS, canary, rollback, and mixed-state recovery integrations with
  external controllers;
- benchmark large repositories and graph stores;
- complete migration and backward-compatibility tooling.

### 1.0: complete product criteria

Version 1.0 should be declared only when the following are independently
verified:

1. language adapters, build/config inputs, and authenticated runtime evidence
   share one canonical ontology identity;
2. file storage and at least one optional standard RDF store round-trip without
   losing portable semantics or lineage;
3. foreground, Git/CI, and approved managed-local refresh paths are reliable,
   observable, idempotent, and recoverable;
4. MCP, SPARQL/REST profiles, natural-language orchestration, and visualization
   preserve the same read and evidence boundaries;
5. existing local models can be discovered and safely enriched, while optional
   installation remains explicit and license-aware;
6. external improvement controllers can consume authenticated evidence and
   prove all required validation, CAS, canary, and rollback gates;
7. installation and upgrades preserve user data, rollback lineage, privacy,
   portability, and a useful zero-dependency mode;
8. the product documentation and core workflows are maintained in English,
   Korean, Japanese, and Simplified Chinese.

## 7. Compatibility and migration

- The stable `co:` namespace and RDF 1.1 export are the migration contract.
- New storage adapters must import existing Turtle rather than creating a
  proprietary source of truth.
- Snapshot and provenance identifiers are immutable; adapters may index but not
  rewrite them.
- Analyzer, Companion, schema, canonicalizer, and inference versions remain
  explicit in receipts.
- Old snapshots remain readable when a new analyzer requires a refresh.
- Store-specific features must have a portable fallback or be clearly marked as
  non-portable extensions.

## 8. Permanent safety and privacy boundaries

The project never treats code access as permission to execute target code,
read secrets, upload repositories, mutate policy, deploy software, submit
orders, or move funds. Deterministic analysis excludes sensitive and generated
paths, portable artifacts omit absolute paths and private fingerprints, and
optional LLM data remains bounded and separately classified.

Automated improvement is a composition of independently verified components,
not a capability switch inside the ontology plugin. No roadmap milestone may
weaken that separation merely to make automation easier.

## 9. Publishing strategy

Publish version 0.3.4 as the current public Skills-only baseline, with the
general-purpose ontology workflow isolated from full/local personal-project
extensions. Version 0.3.2 remains the historical functional baseline and
version 0.3.3 remains the multilingual documentation milestone. Continue
through compatible patch and minor releases rather than waiting for the entire
target architecture before collecting real user feedback. Do not market the
current product as a graph database, live runtime tracer, autonomous
refactoring system, deployment agent, or profitability engine.

The intended product statement is:

> Build and maintain privacy-conscious local code knowledge graphs for
> authorized Java/Spring and Python repositories, with portable RDF lineage,
> static impact exploration, version comparison, and offline visualization.
