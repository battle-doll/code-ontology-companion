# Public Plugin Submission Notes

[English](SUBMISSION.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/SUBMISSION.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/SUBMISSION.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/SUBMISSION.md)

## Listing

- Name: Code Ontology Companion
- Version: 0.4.0
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

> Local code graphs with RDF lineage

Long description:

> Statically map an authorized Java, Spring, or Python repository into immutable local knowledge-graph snapshots. Inspect possible change impact, compare versions, preserve evidence lineage, export RDF 1.1 Turtle, and open a self-contained offline visualization. Deterministic analysis executes no target code and makes no network request. If existing Ollama is detected, the user may separately authorize bounded loopback-only inference that remains unvalidated and separate from observed evidence. Nothing installs a model or starts Ollama; authorized enrichment runs the selected model and requests immediate unload after the response.

## Access and data-use declaration

| Area | Version 0.4.0 behavior |
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
| Portable artifacts | Symbols, relationships, language, qualified names, validated policy identifiers, relative paths, counts, RDF/Turtle, lineage, offline HTML |
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

The analyzer independently enforces authorization flags, output separation,
link/reparse/special-file avoidance, sensitive-path exclusions, source-size
limits, no deterministic-path network access, and no target execution. Refresh uses stable
manifests, staging, validation, immutable snapshots, and atomic promotion.
Source and release-artifact validation also checks supported component metadata,
documentation, deterministic package contents, and extracted smoke behavior.

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
cases covering preflight, initialization, Spring/Python analysis, version
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
