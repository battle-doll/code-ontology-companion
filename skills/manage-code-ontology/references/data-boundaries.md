# Data boundaries

[English](data-boundaries.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/references/data-boundaries.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/references/data-boundaries.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/references/data-boundaries.md)

## Authorized inputs

Analyze only a local repository the user owns, administers, or is explicitly permitted to inspect. A path supplied by another person is not proof of authorization.

## Data read

Version 0.5.2 reads regular `.java` and `.py` files up to 2 MiB, with
fail-closed aggregate file-count and byte limits. It does not follow symbolic
links or Windows reparse points. It skips common dependency, VCS,
generated-output, IDE, virtual-environment, and cache directories.

Files whose names suggest credentials, secrets, tokens, private keys, keystores, or `.env` configuration are excluded even if they use a supported extension.

## Data retained

Portable ontology artifacts may retain:

- symbol and annotation names;
- language and node/relationship types;
- qualified names;
- validated dotted policy identifiers used by recognized Java policy accessors;
- repository-relative source paths and optional relationship-evidence line spans;
- stable extraction rule IDs, qualitative evidence bases, runtime-status
  indicators, bounded limitations, and adapter-coverage summaries;
- aggregate counts and parse warnings.

Private local workspace files additionally retain:

- the absolute repository path needed for refresh;
- per-file byte counts and SHA-256 values used for change detection;
- snapshot, event, and workspace identifiers;
- an optional local Git revision read directly from regular `.git` metadata.

Portable RDF, offline HTML, and normal MCP responses do not intentionally
expose the absolute repository path or full file fingerprints.

The offline HTML embeds the full portable node/edge index for local search but
materializes only a bounded subgraph in the canvas. It also embeds integrity-
pinned Cytoscape.js and ELK.js bytes; the Content Security Policy disables
connections and browser workers.

Observed ontology artifacts intentionally retain none of the following:

- source bodies, arbitrary string literals, or comments;
- file contents;
- environment variables, credentials, API keys, or tokens;
- prompts or model outputs.

If optional local LLM enrichment is explicitly enabled, a separate private
configuration (mode `0600` on POSIX and the selected workspace's inherited ACL
on Windows) retains the fixed loopback provider/endpoint,
consent/data-scope version, and verified model name/digest/capabilities. Each
successful enrichment creates one private sidecar retaining normalized
suggested roles and confidence, snapshot/model/schema provenance, and bounded
input/ontology digests. Raw prompts and raw responses are not retained.
Sidecars are `inferred` evidence and are never merged into observed ontology,
RDF, lineage, or MCP data.

Identifiers and relative paths can still be confidential. Keep artifacts local by default and obtain separate authorization before sharing them.

## Writes

Doctor and preflight write nothing. Initialization creates a new explicit
workspace that is neither inside nor a parent of the target repository.
Refresh builds a complete staging snapshot, validates it, and atomically
promotes a new immutable snapshot while retaining the last known-good version.
Decision and validation records append to the local lineage journal.

## Network and execution

The bundled analyzer makes no direct network requests and does not import,
compile, build, test, or execute target code. It installs no packages, models,
databases, daemons, or permanent watchers.

When the plugin is enabled, Codex may start the bundled read-only stdio MCP
process. It opens no listening port, accepts no arbitrary filesystem path, and
queries only workspaces already registered by an explicitly authorized
initialization workflow.

After an affirmative workspace-scoped consent, the separate optional helper may
contact only an existing Ollama service at literal IPv4 loopback
`127.0.0.1:11434`. It accepts no endpoint input, proxy, redirect, API key, or
LAN/public address, and rejects reported cloud/remote markers or missing required
model metadata. The bounded payload can contain
node IDs, symbol/type/annotation names, qualified names, repository-relative
paths, and observed relationship metadata. It excludes source bodies,
comments, arbitrary strings, secrets, absolute paths, private manifests,
source fingerprints, and raw file hashes. The helper never installs or
downloads a model and never starts the Ollama service. Authorized enrichment
does execute the selected model, may allocate CPU/GPU memory, and sends
`keep_alive=0` to request immediate unload after the response. Ollama's own
networking, resource behavior, and retention are outside Companion's control.

Codex may process analyzer command output to provide the requested workflow.
That platform processing is governed by OpenAI's applicable terms and privacy
policy. Version 0.5.2 does not invoke a remote data service or upload generated
artifacts.

## Interpretation

The graph is static evidence. It can show structural correlation and change
proximity, but it does not establish runtime execution, safety, or causation.
Reflection, runtime bean conditions, generated proxies, external configuration,
dynamic imports, monkey-patching, dependency injection containers, and
generated code may change actual runtime behavior.
