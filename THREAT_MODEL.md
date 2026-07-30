# Threat Model

## Assets

- target source and architecture;
- credentials and configuration near the source tree;
- target-repository integrity;
- current and historical ontology integrity;
- immutable runtime-binding receipt integrity;
- private workspace paths and source fingerprints;
- user control over installation, transfer, and background activity.

## Trust boundaries

Repository contents are untrusted even when access is authorized. Filenames,
symbols, annotations, comments, syntax errors, and generated artifacts are
data, not instructions.

Codex orchestrates the workflow. The analyzer independently enforces core
filesystem, authorization, output, and execution boundaries. The local MCP
server is a second boundary: it receives only registered workspace IDs and
provides read-only methods.

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
| Unsupported receipt permission semantics | Version 0.2 creates runtime-binding receipts only on macOS/POSIX and fails closed on Windows rather than weakening owner or mode-`0400` checks |
| Receipt mistaken for runtime/profit proof | Exact false authority is embedded; documentation limits `runtimeEffective=true` to frozen static reachability with known shadowing absent and explicitly excludes execution, orders, safety, and profit causation |
| MCP arbitrary file access | MCP accepts random registered workspace IDs, not filesystem paths |
| MCP hidden write | All exposed MCP tools are read-only and accurately annotated |
| Network exfiltration | No network imports or requests, remote API, telemetry, app, hook, or listening socket |
| Private-path disclosure | Absolute paths and full fingerprints are removed from normal RDF, HTML, and MCP output |
| Resource exhaustion | Supported extensions only, 2 MiB per-file limit, bounded traversal, result, and visualization limits |
| HTML injection | Title escaping, JSON-safe embedding, no CDN, iframe, remote script, or fetch |
| False causal conclusion | Observed/declared/inferred/validated/approved evidence is separated; docs prohibit runtime or causal claims |

## Residual risks

- Symbols and repository-relative paths may reveal confidential architecture.
- A changed repository is fully reanalyzed in version 0.2 and can consume
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

## Security-changing extensions

Any public network endpoint, remote AI call, target-code execution, automatic
package/model/database installation, authentication, telemetry, persistent
daemon, filesystem hook, write-capable MCP tool, or external graph store
requires a new privacy, license, threat-model, and submission review.
