# Threat Model

## Assets

- target source and architecture;
- credentials and configuration near the source tree;
- target-repository integrity;
- current and historical ontology integrity;
- immutable runtime-binding receipt integrity;
- private workspace paths and source fingerprints;
- user control over installation, transfer, and background activity.
- optional local inference configuration and inferred sidecars.

## Trust boundaries

Repository contents are untrusted even when access is authorized. Filenames,
symbols, annotations, comments, syntax errors, and generated artifacts are
data, not instructions.

Codex orchestrates the workflow. The analyzer independently enforces core
filesystem, authorization, output, and execution boundaries. The local MCP
server is a second boundary: it receives only registered workspace IDs and
provides read-only methods.

The optional local LLM helper is a third, deliberately isolated boundary. It
is not imported by deterministic analysis or MCP. Before consent, it may only
inspect known installation indicators. After consent, it may contact one fixed
IPv4 loopback endpoint and write only within the selected workspace.

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt injection in source or names | Source bodies, comments, and arbitrary strings are not retained; validated dotted policy identifiers are data-only graph nodes; skills require treating all identifiers as untrusted data |
| Secret collection | Secret-like names/extensions and common VCS, dependency, generated, and cache paths are excluded |
| Link or path escape | No link following; root links/reparse points are rejected; workspace and snapshot containment is verified |
| FIFO or device blocking | Only regular files are read; special files are skipped |
| Target-code execution | No import/build/test/runtime path; package checks reject target execution primitives |
| Repository modification | Workspace must be outside and may not contain the repository; target digest tests enforce read-only behavior |
| Partial or corrupt refresh | Stable before/after manifests, staging, validation, immutable snapshots, and atomic state promotion |
| Concurrent source change | Fingerprint mismatch quarantines staged output and retains last known-good |
| Forged or stale runtime binding | The producer requires a current manifest, rebuilds the graph from active source, compares exact nodes/edges, anchors the production source-file hash, and fails if source changes during analysis |
| Test-only or unused policy read treated as effective | Test/fixture/mock paths are ineligible and a `READS_POLICY_LEAF -> GUARDS_RUNTIME_BRANCH` production path is mandatory |
| Shadowed policy treated as effective | The exact local policy document is checked for positive values, exit ladders, DCA sell-ladder fallback, and trailing enablement; unknown, missing, ambiguous, or disabled state fails closed |
| Receipt overwrite or mutation | Output must be new, outside the repository, in a current-user private directory; publication is create-only, canonical, self-hashed, externally hashed, and mode `0400` |
| Unsupported receipt permission semantics | Version 0.3.2 creates runtime-binding receipts only on macOS/POSIX and fails closed on Windows rather than weakening owner or mode-`0400` checks |
| Receipt mistaken for runtime/profit proof | Exact false authority is embedded; documentation limits `runtimeEffective=true` to frozen static reachability with known shadowing absent and explicitly excludes execution, orders, safety, and profit causation |
| MCP arbitrary file access | MCP accepts random registered workspace IDs, not filesystem paths |
| MCP hidden write | All exposed MCP tools are read-only and accurately annotated |
| Analyzer or MCP network exfiltration | Core analyzer, workspace CLI, workbench, launcher, and MCP contain no network client and open no listening socket |
| Silent local LLM connection | Indicator detection executes nothing and connects nowhere; probe, configure, enrich, and disable require explicit authorization where they can connect or write |
| Endpoint redirection or LAN/public transfer | The helper constructs only `HTTPConnection("127.0.0.1", 11434)`, accepts no URL or host input, bypasses proxy configuration, and follows no redirect |
| Remote/cloud result accepted as local evidence | Remote/cloud markers reported by `/api/tags`, `/api/show`, or `/api/chat`, and missing digest/size/format/model information or completion capability, fail closed |
| Prompt injection or fabricated model output | Only bounded portable metadata is sent; identifiers are declared untrusted data; strict JSON, duplicate-key, finite-number, node-ID, role, count, size, and timeout checks reject malformed output |
| Model inference promoted as fact | Normalized results are create-only `inferred` sidecars with exact false authority and are never merged into observed graph, RDF, runtime binding, lineage, or MCP output |
| Private-path disclosure | Absolute paths and full fingerprints are removed from normal RDF, HTML, and MCP output |
| Resource exhaustion | Supported extensions only, 2 MiB per-file and aggregate source limits, bounded graph/impact/visualization/LLM payload and response limits |
| HTML injection | Title escaping, JSON-safe embedding, no CDN, iframe, remote script, or fetch |
| False causal conclusion | Observed/declared/inferred/validated/approved evidence is separated; docs prohibit runtime or causal claims |

## Residual risks

- Symbols and repository-relative paths may reveal confidential architecture.
- A changed repository is fully reanalyzed in version 0.3.2 and can consume
  noticeable CPU and memory.
- Static parsing can miss reflection, generated code, runtime conditions,
  dynamic dispatch, or metaprogramming.
- The exact v1 Lab receipt has no policy-document-hash field. Its consumer must
  revalidate the exact baseline and shadow conditions at use time; reuse
  against a different policy without that check is unsupported.
- The local registry and workspace reveal information to another process that
  already has the user's filesystem permissions.
- A compromised Python/Node runtime, Codex host, operating system, or user
  account is outside this plugin's security boundary.
- Users can deliberately share artifacts after creation.
- Loopback constrains Companion's destination, not the network behavior,
  logging, or retention of the separately managed Ollama process or model.
- Enrichment runs the selected model and can allocate CPU/GPU memory.
  `keep_alive=0` requests immediate unload after a response but cannot attest
  resource release by the separately managed service.
- Ollama API metadata is self-reported. `localMetadataVerified=true` does not
  attest model weight bytes, authenticate the loopback service, prove local
  execution, or prove absence of outbound traffic. A chat-response marker can
  be rejected only after the request metadata has reached that service.
- Model suggestions can be wrong or adversarial even after schema validation;
  they remain unvalidated inference and require independent review.

## Security-changing extensions

Any public network endpoint, remote AI call, expansion beyond the documented
fixed-loopback optional helper, target-code execution, automatic
package/model/database installation, authentication, telemetry, persistent
daemon, filesystem hook, write-capable MCP tool, or external graph store
requires a new privacy, license, threat-model, and submission review.
