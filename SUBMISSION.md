# Public Plugin Submission Notes

## Listing

- Name: Code Ontology Companion
- Version: 0.3.1
- Developer: battle-doll
- Category: Developer Tools
- Distribution: Public
- Public profile: Skills-only
- Local/full profile: one skill plus a bundled local read-only stdio MCP server
- License: Apache-2.0

Short description:

> Local code graphs with RDF lineage

Long description:

> Statically map an authorized Java, Spring, or Python repository into immutable local knowledge-graph snapshots. Inspect possible change impact, compare versions, preserve evidence lineage, export RDF 1.1 Turtle, and open a self-contained offline visualization. Deterministic analysis executes no target code and makes no network request. If existing Ollama is detected, the user may separately authorize bounded loopback-only inference that remains unvalidated and separate from observed evidence. Nothing installs a model or starts Ollama; authorized enrichment runs the selected model and requests immediate unload after the response.

## Access and data-use declaration

| Area | Version 0.3.1 behavior |
| --- | --- |
| Authentication | None |
| Direct network access | Deterministic analyzer/workspace/MCP: none. Optional helper after explicit consent: fixed `127.0.0.1:11434` only |
| External APIs | Optional existing local Ollama API only; no remote or publisher API |
| Telemetry/analytics | None |
| Target-code execution | None |
| Reads | Authorized regular `.java` and `.py` files under an explicit repository path; for optional runtime binding, one explicit JSON or `policy-json` document |
| Exclusions | Secret-like names, keys, env files, links/reparse points, VCS, dependencies, build outputs, caches, special and oversized files |
| Writes | New explicit workspace outside the repository; immutable refresh snapshots and append-only lineage; on explicit authorization, one create-only mode-`0400` runtime-binding receipt; after separate local-LLM consent, mode-`0600` workspace configuration and create-only inferred sidecars |
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

## Tool annotations

All seven MCP tools set:

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

Tools list workspaces, read status, search, inspect static neighbors, list
history, compare snapshots, and read lineage. Initialization, refresh, lineage
writes, installation, deletion, upload, target execution, and arbitrary path
access are not exposed through MCP.

The optional `runtime-binding` command remains CLI-only. Its exact false
authority prohibits candidate generation/gating, approval, promotion, policy
or runtime writes, order submission, network access, and funds transfer.
Version 0.3.1 creates the exact receipt only on macOS/POSIX, where owner and
mode-`0400` semantics can be enforced; the command fails closed on Windows.

## Review rationale

The release provides standalone deterministic value without a cloud account,
remote service, graph database, or model. It requires:

1. repository authorization;
2. no-write preflight;
3. an explicit workspace outside the repository;
4. explicit authorization before initialization;
5. explicit authorization before a create-only runtime-binding receipt;
6. static-evidence language rather than runtime or causal claims.
7. a separate, explicit disclosure and consent before any optional loopback
   model inspection or workspace configuration.

The analyzer independently enforces authorization flags, output separation,
link/reparse/special-file avoidance, sensitive-path exclusions, source-size
limits, no deterministic-path network access, and no target execution. Refresh uses stable
manifests, staging, validation, immutable snapshots, and atomic promotion.
Runtime-binding additionally rebuilds the graph from active source, compares
exact semantic nodes/edges with the frozen snapshot, rejects test-only or
unused paths and known active-policy shadows, and publishes canonical
self-/externally-hashed mode-`0400` output. `runtimeEffective=true` means only
static production-branch reachability with known supplied-policy shadowing
absent. It does not prove execution, orders, safety, or profit causation.

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
omits `.mcp.json` and `mcp/`, as required for a skills-only upload. Do not
replace this with the full local ZIP in the skills-only submission form.

## Evaluation cases

[evals/cases.json](evals/cases.json) contains at least five positive and three
negative reviewer cases covering preflight, initialization, Spring/Python
analysis, version comparison, lineage, local-LLM consent/decline/absence and
malformed response handling, MCP read boundaries, unauthorized access, secret
exfiltration, silent installation, and MCP writes. Local-LLM cases use bounded
fake responses and do not require reviewer infrastructure.

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
