# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

[Architecture and supported workflows](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ARCHITECTURE_AND_ROADMAP.md)

Code Ontology Companion is an independent Codex plugin for maintaining a
privacy-conscious local knowledge graph of an authorized Java/Spring or Python
repository.

It combines deterministic static analysis, auditable relationship evidence,
immutable snapshots, RDF 1.1 Turtle export, PROV-O-compatible lineage, an
interactive offline workbench, and a read-only local MCP server. The
deterministic analyzer and MCP server do not
execute target code, install software, send telemetry, or make network
requests. An
optional, separately authorized helper can send bounded portable ontology
metadata to an existing Ollama service at the fixed loopback address
`127.0.0.1:11434`; its unvalidated suggestions remain outside the observed graph.

Use the plugin to reverse-engineer an existing authorized codebase at source
level into a navigable ontology. It reads supported Java/Spring and Python
structure without executing the target, records symbols and static
relationships in an immutable snapshot, and produces JSON, RDF/Turtle, and an
offline interactive workbench for exploration and change planning.

Codex may process command output such as symbols, counts, and
repository-relative paths to carry out a requested workflow. That platform
processing is governed by OpenAI's
[applicable terms](https://openai.com/policies/terms-of-use/) and
[privacy policy](https://openai.com/policies/privacy-policy/). Installing this
plugin does not make Codex an offline product.

## Version 0.5.2 capabilities

The plugin provides the following supported workflows:

- Map Java packages, imports, types, methods, inheritance, and basic dependencies.
- Recognize common Spring stereotypes, `@Bean`, constructor/field injection,
  AspectJ advice, transaction, async, cache, authorization, and retry proxy signals.
- Map Python modules, imports, types, functions, decorators, calls, inheritance,
  and heuristic Extract/Transform/Load/Validate/Orchestrate roles.
- Attach an additive `evidence` array to every relationship. Each evidence item
  contains a stable `rule_id`, one qualitative `basis` value
  (`direct_syntax`, `resolved_static`, `framework_semantic`, or
  `name_heuristic`), a `runtime_status` of `not_applicable` or
  `runtime_unknown`, optional repository-relative `path`, `line_start`, and
  `line_end`, and bounded `limitations`.
- Publish `document.quality` contract version `1.0` with relationship-evidence
  coverage and counts plus Java and Python adapter status, capabilities, and
  unsupported-runtime indicators. Zero parse warnings do not mean complete
  static or runtime coverage.
- Resolve conservative Java same-owner calls and explicit calls through
  recognized imported types while
  omitting ambiguous call candidates instead of manufacturing relationships.
- Parse Java generic, record, nested-type, multi-interface, and Spring
  annotation/injection cases more conservatively, and resolve Python alias,
  relative-import, lexical-shadowing, nested-function, and `src/` layout cases.
- Enforce bounded source, graph, impact, and output limits.
- Optionally configure one existing Ollama completion model after explicit
  workspace-scoped consent and validation of Ollama-reported model metadata,
  then store only normalized `inferred` sidecars without changing the
  deterministic ontology.
- Skip unchanged refreshes using a private source fingerprint.
- Refresh unchanged source when the analyzer or Companion version changes.
- Build changed repositories in staging and atomically promote an immutable snapshot.
- Preserve the last known-good snapshot when analysis or validation fails.
- Compare snapshots and maintain observed/declared/inferred/validated/approved lineage.
- Export portable RDF/Turtle and a self-contained interactive HTML workbench with
  full-index search, bounded relationship lenses, human-readable details, and no CDN.
- Switch one selected bounded neighborhood between the default 2D structure
  view and an optional 3D constellation. The 3D view uses local Canvas2D
  perspective rendering, deterministic static positions, and explicit
  node/edge/frame budgets; it adds no WebGL, package, worker, telemetry, or
  network requirement.
- Explore 3D with pointer orbit/zoom or equivalent keyboard controls for orbit,
  zoom, camera reset, node traversal, selection, and return to root. The DOM
  search, relationship lists, details, and 2D graph remain the authoritative
  accessible paths to the same nodes and relationships.
- Honor reduced-motion and forced-colors/high-contrast preferences, expose mode
  and selection status to assistive technology, pause rendering in hidden tabs,
  and return safely to 2D if canvas rendering fails.
- Compare the current and previous snapshots directly in the workbench while
  keeping source fingerprints and absolute workspace paths private.
- Query registered workspaces through seven read-only local MCP tools.
- Map recognized Java policy accessor reads to the control-flow branches they
  guard, without retaining arbitrary string literals.
- Run the deterministic analyzer, local MCP server, and optional Ollama helper
  on Windows, macOS, and Linux with Python 3.9 or newer.
- Apply an executable golden/forbidden quality gate to expected and prohibited
  nodes, relationships, evidence metadata, adapter coverage, and deterministic
  output without executing the target repository.

Version 0.5.2 fully reanalyzes changed repositories. Private fingerprints avoid
unnecessary unchanged runs.

## Privacy and safety defaults

- Analyze only code you own or are authorized to inspect.
- `doctor` and `preflight` are read-only.
- Initialization requires `--authorized` and a new workspace outside the repository.
- Source bodies, comments, and arbitrary string literals are not retained.
  Validated dotted policy identifiers passed to recognized Java policy accessors
  may be retained as `PolicyLeaf` nodes.
- A private local configuration stores the absolute repository path, and a
  private manifest stores per-file sizes and SHA-256 values for freshness checks.
- Portable RDF, HTML, and normal MCP responses omit absolute paths and full
  fingerprints. Relationship evidence may contain repository-relative paths
  and line spans, which can still be confidential.
- Secret-like files, links/reparse points, dependencies, VCS contents, and
  generated outputs are excluded.
- Target projects are never imported, built, tested, or run.
- The MCP process uses stdio, opens no listening port, and accepts workspace IDs
  rather than arbitrary filesystem paths.
- No daemon, graph database, local model, package, or watcher is installed.
Cytoscape.js and ELK.js are pinned inside the generated HTML; the optional 3D
  projection uses built-in Canvas2D. No npm install, CDN, browser worker,
  WebGL dependency, telemetry, or network service is used.
- Local LLM detection executes nothing, connects nowhere, and writes nothing.
  Only after consent may the optional helper contact fixed IPv4 loopback,
  validate Ollama-reported metadata, reject responses carrying remote/cloud
  markers, and write workspace-scoped private configuration and create-only
  inferred evidence. POSIX uses mode `0600`; Windows inherits the access-control
  list of the user-selected workspace.

Symbol names and repository-relative paths may still be confidential. Keep
workspaces and exports local unless sharing is separately authorized.

## Requirements

- Codex with plugin and skill support
- Python 3.9 or newer
- No third-party Python package, graph database, Java runtime, or local LLM
  is required

The bundled MCP launcher can locate Python without invoking a shell when Node.js
is available. Direct Python stdio configuration is supported on every platform.

## Reverse-engineer existing code into an ontology

On macOS or Linux, use `python3` in the commands below. On Windows, use an
existing Python 3.9 or newer interpreter such as `py -3`.

1. Run `doctor` and `preflight` against the existing repository to confirm the
   supported source set without writing files.
2. Review the result, choose a new workspace outside the repository, and run
   the authorized `init` command. This performs source-level reverse engineering
   and creates the first immutable ontology snapshot.
3. Explore `graph.html`, load `ontology.ttl` into an RDF-compatible workflow,
   or use the CLI and optional read-only local MCP tools to search symbols and
   relationships.
4. After the code changes, run `sync` and `diff` to create and compare a new
   snapshot while preserving the previous one and its lineage.

### Manual commands

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  doctor --repo "/path/to/authorized/repository"

python3 skills/manage-code-ontology/scripts/companion.py \
  preflight --repo "/path/to/authorized/repository"
```

After reviewing the preflight and authorizing local artifact creation:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  init \
  --repo "/path/to/authorized/repository" \
  --workspace "/path/outside/repository/ontology-workspace" \
  --authorized
```

Refresh and query:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  sync --workspace "/path/to/ontology-workspace"

python3 skills/manage-code-ontology/scripts/companion.py \
  query --workspace "/path/to/ontology-workspace" --term "OrderService"

python3 skills/manage-code-ontology/scripts/companion.py \
  diff --workspace "/path/to/ontology-workspace"
```

### Optional read-only local MCP

The complete plugin package bundles a seven-tool stdio server. It opens no
listening port and accepts registered `workspace_id` values rather than
arbitrary repository paths. When the bundled launcher is unavailable, configure
the server directly in Codex with the Python command for the current platform.

macOS or Linux:

```toml
[mcp_servers.code-ontology-companion]
command = "python3"
args = ["/absolute/path/to/code-ontology-companion/mcp/server.py"]
```

Windows:

```toml
[mcp_servers.code-ontology-companion]
command = "py"
args = ["-3", "C:\\absolute\\path\\to\\code-ontology-companion\\mcp\\server.py"]
```

Restart Codex or open a fresh Codex process after changing MCP configuration,
then verify workspace listing, status, and search. See
[local-mcp.md](skills/manage-code-ontology/references/local-mcp.md) for the full
setup and verification workflow.

### Optional existing Ollama enrichment

The deterministic workflow never requires a model. On the first relevant
workflow, detection is read-only. Only if Ollama is detected should Companion
ask whether to inspect existing local models. Consent permits fixed-loopback
model inspection and workspace configuration; it does not permit installation,
download, server start, or arbitrary endpoints. Models and results reported by
Ollama as remote/cloud are rejected.

```bash
python3 skills/manage-code-ontology/scripts/local_llm.py detect

# Run only after the disclosure and explicit consent described in the skill.
python3 skills/manage-code-ontology/scripts/local_llm.py probe --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py configure \
  --workspace "/path/to/ontology-workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py enrich \
  --workspace "/path/to/ontology-workspace" \
  --authorized
```

The helper sends bounded symbol metadata and observed relations, never source
bodies, comments, arbitrary strings, secrets, absolute paths, or private file
hashes. It stores normalized suggestions under
`enrichments/<snapshot-id>/<run-id>.json` as `inferred` evidence. Raw prompts
and raw responses are not retained. Version 0.5.2 partitions that metadata in
stable order into requests of at most 20 candidates and 16 KiB, disables model
thinking, caps each request context at 8,192 tokens, limits each response to
2,048 output tokens, and permits up to 180 seconds per request. It publishes
the sidecar atomically only after every batch validates, so a failed or partial
run leaves no artifact. Unsupported or conflicting role suggestions are omitted
and counted rather than linked. Ollama's own network behavior remains outside
Companion's control. Enrichment executes the selected model and may
allocate CPU/GPU memory; the helper sends `keep_alive=0` to request immediate
unload after each response. `localMetadataVerified=true` means only that the
digest, size, format, model information, capability, and remote-marker fields
reported by the Ollama API passed Companion's checks. It does not attest the
model weight bytes, the identity of the loopback service, local-only execution,
or absence of outbound Ollama traffic. See
[local-llm.md](skills/manage-code-ontology/references/local-llm.md).

## Workspace pipeline

```text
authorized source
  -> private source manifest
  -> isolated staging analysis
  -> artifact validation
  -> immutable snapshot promotion
  -> current snapshot pointer
  -> RDF / interactive offline HTML / read-only MCP
```

Each snapshot contains `ontology.json`, `ontology.ttl`, `report.md`,
`graph.html`, `snapshot.json`, and a private `source-manifest.json`. The
workspace also contains an append-only `lineage.jsonl` and portable
`lineage.ttl`.

## RDF portability and lineage

The core vocabulary preserves the Explorer 1.0 `co:` namespace so older
exports remain compatible. Lineage uses W3C PROV-O plus a documented Companion
namespace. Turtle exports can be imported into RDF 1.1-compatible stores.
Store-specific indexes, reasoning rules, and extensions may need mapping.
Version 0.5.2 keeps every legacy direct relationship triple and stable identity,
then adds `RelationshipEvidence` resources for rule, basis, source-span,
runtime-status, and limitation metadata.

## Static-analysis limits

The graph is navigation and change-planning evidence, not a runtime trace,
security verdict, causal proof, or correctness guarantee. Reflection, generated
code, runtime Spring conditions, dynamic proxies, external configuration,
dependency versions, and Python metaprogramming may be incomplete.
Inspect each relationship's qualitative basis, runtime status, limitations, and
the adapter coverage matrix before using it for change planning. A
`runtime_unknown` relationship is static evidence, not proof of runtime
activation.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
python3 scripts/build_release.py
python3 scripts/build_skills_only_release.py
```

Security issues: [SECURITY.md](SECURITY.md). Support: [SUPPORT.md](SUPPORT.md).

## License and independence

Source is licensed under Apache-2.0. This project is independent and is not
affiliated with or endorsed by OpenAI, Broadcom, VMware, the Spring project,
Oracle, or the Python Software Foundation. Product names describe
compatibility only.
