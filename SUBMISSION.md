# Public Plugin Submission Notes

[English](SUBMISSION.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/SUBMISSION.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/SUBMISSION.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/SUBMISSION.md)

## Listing

- Name: Code Ontology Companion
- Version: 0.3.4
- Developer: battle-doll
- Category: Developer Tools
- Distribution: Public
- Public profile: Skills-only, general-purpose ontology workflow only
- Public-profile exclusions: downstream AETHER Lab runtime-binding command,
  project policy schema, receipt producer, and extension-specific evaluations
- Local/full profile: one skill plus a bundled local read-only stdio MCP server
  and an optional personal-project compatibility extension that is not part of
  the OpenAI submission
- License: Apache-2.0

Short description:

> Local code graphs with RDF lineage

Long description:

> Statically map an authorized Java, Spring, or Python repository into immutable local knowledge-graph snapshots. Inspect possible change impact, compare versions, preserve evidence lineage, export RDF 1.1 Turtle, and open a self-contained offline visualization. Deterministic analysis executes no target code and makes no network request. If existing Ollama is detected, the user may separately authorize bounded loopback-only inference that remains unvalidated and separate from observed evidence. Nothing installs a model or starts Ollama; authorized enrichment runs the selected model and requests immediate unload after the response.

## Access and data-use declaration

| Area | Public Skills-only version 0.3.4 behavior |
| --- | --- |
| Authentication | None |
| Direct network access | Deterministic analyzer/workspace: none. Optional helper after explicit consent: fixed `127.0.0.1:11434` only |
| External APIs | Optional existing local Ollama API only; no remote or publisher API |
| Telemetry/analytics | None |
| Target-code execution | None |
| Reads | Authorized regular `.java` and `.py` files under an explicit repository path |
| Exclusions | Secret-like names, keys, env files, links/reparse points, VCS, dependencies, build outputs, caches, special and oversized files |
| Writes | New explicit workspace outside the repository; immutable refresh snapshots and append-only lineage; after separate local-LLM consent, mode-`0600` workspace configuration and create-only inferred sidecars |
| Private local state | Absolute repository path, per-file relative path/size/SHA-256, workspace/snapshot/event IDs, optional Git revision; if enabled, local model name/digest/capability and normalized inferred suggestions |
| Portable artifacts | Symbols, relationships, language, qualified names, validated policy identifiers, relative paths, counts, RDF/Turtle, lineage, offline HTML |
| Not retained | Source bodies, comments, arbitrary string literals, policy values, credentials, raw prompts, raw model responses |
| Uploads | None |
| Background services | None; optional watcher is explicit foreground-only |
| MCP | Omitted from public Skills-only archive. Full/local profile: stdio, read-only, no port, registered workspace IDs only |
| MCP writes | None |
| Hooks/apps/widgets | None |
| Package/model/database installation | None |
| Local LLM required | No. Optional existing Ollama only after workspace-scoped consent; no install/download/Ollama-service start. Enrichment executes the selected model and sends `keep_alive=0` |

## Full/local MCP annotations (not in the public upload)

The separate full/local profile's seven MCP tools set:

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

Tools list workspaces, read status, search, inspect static neighbors, list
history, compare snapshots, and read lineage. Initialization, refresh, lineage
writes, installation, deletion, upload, target execution, and arbitrary path
access are not exposed through MCP.

The public Skills-only archive has no runtime-binding command, downstream
project policy schema, receipt producer, or extension-specific evaluation
material. The optional personal-project extension remains in the separate
full/local GitHub profile only. It is not OpenAI-hosted, is not claimed by this
submission, and grants no runtime, policy, order, network, or funds authority.

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
Public artifact validation also fails closed if the Skills-only archive exposes
the excluded downstream command, policy schema, receipt producer, or related
capability claims.

Optional local enrichment is not part of the observed analyzer authority. Its
indicator check executes nothing and makes no connection. After consent, the
helper uses only literal IPv4 loopback, rejects reported cloud/remote markers,
missing or invalid required API metadata, and unbounded/malformed responses,
sends no source bodies/secrets/absolute paths or
private hashes, and stores normalized output as create-only `inferred`
sidecars. Ollama's own network behavior remains an explicitly disclosed
residual risk.

## Submission transport note

The full/local profile's bundled MCP transport is local stdio and intentionally has no public HTTPS
endpoint. If the current public submission portal requires a public MCP URL for
every MCP-bearing plugin, do not enter a placeholder or misrepresent the
transport. Submit only through a documented bundled-stdio path, or create a
separately reviewed skills-only package whose listing omits MCP claims.

The current portal's **With MCP** path requires a production HTTPS MCP URL,
domain verification, a current tool scan, and a demo recording. It does not
accept the bundled local stdio server as that URL. The approval-oriented public
profile is therefore **Skills only**; the personal/local distribution retains
the bundled MCP server.

Build the portal-safe archive with:

```bash
python3 scripts/build_skills_only_release.py
```

The generated ZIP contains the manifest, skill, scripts, references, license,
notice, and icons. Its generated manifest omits `mcpServers`, and the archive
omits `.mcp.json`, `mcp/`, the downstream AETHER Lab runtime-binding command,
its project policy schema and receipt producer, and its extension-specific
evaluation material, as required for the public skills-only upload. Do not
replace this with the full local ZIP in the skills-only submission form.

## Evaluation cases

[evals/cases.json](evals/cases.json) contains positive and negative reviewer
cases covering preflight, initialization, Spring/Python analysis, version
comparison, lineage, local-LLM consent/decline/absence and malformed response
handling, MCP read boundaries, unauthorized access, secret exfiltration,
silent installation, and MCP writes. Public-package validation covers only the
general-purpose workflow; any full/local downstream-extension evaluation is
outside the uploaded Skills-only artifact and its submission claims.
Local-LLM cases use bounded fake responses and do not require reviewer
infrastructure.

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

The publisher must personally verify the developer identity, review listing and
availability fields, provide any portal-required domain or credentials, and
accept legal/policy attestations. An automated agent must not attest on the
publisher's behalf.
