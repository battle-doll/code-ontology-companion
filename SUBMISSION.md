# Public Plugin Submission Notes

[English](SUBMISSION.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/SUBMISSION.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/SUBMISSION.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/SUBMISSION.md)

## Listing

- Name: Code Ontology Companion
- Version: 0.5.1
- Developer: battle-doll
- Category: Developer Tools
- Distribution: Public
- Submission type: Skills only
- Components: deterministic ontology skill and CLI, offline workbench,
  optional consent-based Ollama helper, and local MCP setup workflow
- GitHub package: the same skill plus a bundled cross-platform read-only stdio
  MCP server
- License: Apache-2.0

Short description:

> Accessible offline 3D code graphs

Long description:

> Statically map an authorized Java, Spring, or Python repository into immutable local knowledge-graph snapshots with rule-attributed relationship evidence and explicit adapter coverage. Explore one bounded neighborhood in the default accessible 2D view or an optional interactive 3D constellation with keyboard and pointer controls, reduced-motion and high-contrast support, assistive status, and safe 2D fallback. Preserve lineage and export backward-compatible RDF 1.1 Turtle. The self-contained workbench uses no CDN, WebGL, worker, telemetry, or network. Deterministic analysis executes no target code and makes no network request. Separately authorized bounded loopback Ollama inference remains unvalidated and outside observed evidence.

## Access and data-use declaration

| Area | Version 0.5.1 behavior |
| --- | --- |
| Authentication | None |
| Direct network access | Deterministic analyzer/workspace: none. Optional helper after explicit consent: fixed `127.0.0.1:11434` only |
| External APIs | Optional existing local Ollama API only; no remote or publisher API |
| Telemetry/analytics | None |
| Target-code execution | None |
| Reads | Authorized regular `.java` and `.py` files under an explicit repository path |
| Exclusions | Secret-like names, keys, env files, links/reparse points, VCS, dependencies, build outputs, caches, special and oversized files |
| Writes | New explicit workspace outside the repository; immutable refresh snapshots and append-only lineage; after separate local-LLM consent, private workspace configuration and create-only inferred sidecars (mode `0600` on POSIX; inherited workspace ACL on Windows) |
| Private local state | Absolute repository path, per-file relative path/size/SHA-256, workspace/snapshot/event IDs, optional Git revision; if enabled, local model name/digest/capability and normalized inferred suggestions |
| Portable artifacts | Symbols, legacy-compatible relationship triples, stable rule IDs, qualitative evidence bases, runtime-status indicators, bounded limitations, relative paths and optional line spans, adapter coverage, counts, RDF/Turtle `RelationshipEvidence`, lineage, offline HTML |
| Visualization | Default keyboard-accessible 2D structure view plus opt-in Canvas2D 3D constellation over the same bounded neighborhood; deterministic static positions and explicit node/edge/frame budgets; reduced-motion, forced-colors/high-contrast, assistive status, hidden-page pause, and safe 2D failure fallback |
| Not retained | Source bodies, comments, arbitrary string literals, policy values, credentials, raw prompts, raw model responses |
| Uploads | None |
| Background services | None; optional watcher is explicit foreground-only |
| MCP | Optional local stdio server, read-only, no listening port, registered workspace IDs only; Windows, macOS, and Linux setup is documented in the skill bundle |
| MCP writes | None |
| Hooks/apps/widgets | None |
| Package/model/database installation | None |
| Local LLM required | No. Optional existing Ollama only after workspace-scoped consent; no install/download/Ollama-service start. Enrichment uses deterministic requests of at most 20 candidates and 16 KiB, `think=false`, `num_ctx=8192`, `num_predict=2048`, a maximum 180-second timeout, atomic sidecar publication, and `keep_alive=0` |

## Local MCP annotations

The seven MCP tools set:

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

Tools list workspaces, read status, search, inspect static neighbors, list
history, compare snapshots, and read lineage. Initialization, refresh, lineage
writes, installation, deletion, upload, target execution, and arbitrary path
access are not exposed through MCP.

## Review rationale

The release provides standalone deterministic value without a cloud account,
remote service, graph database, or model. It requires:

1. repository authorization;
2. no-write preflight;
3. an explicit workspace outside the repository;
4. explicit authorization before initialization;
5. static-evidence language rather than runtime or causal claims;
6. a separate, explicit disclosure and consent before any optional loopback
   model inspection or workspace configuration.
7. qualitative evidence bases and `runtime_unknown` indicators rather than an
   opaque numeric confidence or a claim that zero warnings means full coverage.

The analyzer independently enforces authorization flags, output separation,
link/reparse/special-file avoidance, sensitive-path exclusions, source-size
limits, no deterministic-path network access, and no target execution. Refresh uses stable
manifests, staging, validation, immutable snapshots, and atomic promotion.
Source and release-artifact validation also checks supported component metadata,
documentation, deterministic package contents, and extracted smoke behavior.
The executable golden/forbidden ontology quality gate checks expected and
prohibited nodes and relationships, required evidence fields, adapter coverage,
and deterministic output without executing the target repository. This
submission note does not itself claim that a particular build or CI run passed.
The companion visualization gate checks the offline/self-contained boundary,
2D default and 3D opt-in contract, finite rendering budgets, keyboard and
pointer alternatives, reduced-motion and hidden-page behavior, high-contrast
and assistive markers, legacy payload handling, and safe 2D recovery. Canvas 3D
is supplemental; DOM search, relationship lists, details, and 2D remain the
equivalent accessible route. This release targets WCAG 2.2 AA design behavior
but does not claim blanket conformance without separate manual AT/browser review.

Optional local enrichment is not part of the observed analyzer authority. Its
indicator check executes nothing and makes no connection. After consent, the
helper uses only literal IPv4 loopback, rejects reported cloud/remote markers,
missing or invalid required API metadata, and unbounded/malformed responses,
sends no source bodies/secrets/absolute paths or
private hashes, and stores normalized output as create-only `inferred`
sidecars. Ollama's own network behavior remains an explicitly disclosed
residual risk.

## Submission package

The official portal upload uses **Skills only**. The skill bundle includes the
portable analyzer, workspace CLI, workbench, optional local-LLM helper, and the
Windows/macOS/Linux local MCP configuration workflow. The complete GitHub
package additionally bundles the stdio MCP executable and automatic launcher.

Build the portal-safe archive with:

```bash
python3 scripts/build_skills_only_release.py
```

The generated ZIP contains the manifest, skill, scripts, references, license,
notice, and icons. Use this Skills-only ZIP for the portal's Skills upload and
the full ZIP for local plugin installation and GitHub distribution.

## Evaluation cases

[evals/cases.json](evals/cases.json) contains positive and negative reviewer
cases covering preflight, initialization, relationship evidence and adapter
coverage, conservative Java calls, golden/forbidden quality expectations,
offline 2D/3D visualization controls and accessibility boundaries, Spring/Python analysis, version
comparison, lineage, local-LLM consent/decline/absence and malformed response
handling, MCP read boundaries, unauthorized access, secret exfiltration,
silent installation, and MCP writes. Local-LLM cases use bounded fake responses
and do not require reviewer infrastructure.

## Legal and policy materials

- [LICENSE](LICENSE)
- [NOTICE](NOTICE)
- [PRIVACY.md](PRIVACY.md)
- [TERMS.md](TERMS.md)
- [SECURITY.md](SECURITY.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [SUPPORT.md](SUPPORT.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TRADEMARKS.md](TRADEMARKS.md)
- [SBOM.spdx.json](SBOM.spdx.json)

Before submission, the publisher must verify the developer identity, listing,
availability, release notes, and applicable legal and policy attestations.
