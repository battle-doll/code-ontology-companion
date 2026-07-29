# Public Plugin Submission Notes

## Listing

- Name: Code Ontology Companion
- Version: 0.1.1
- Developer: battle-doll
- Category: Developer Tools
- Distribution: Public
- Components: one skill plus a bundled local read-only stdio MCP server
- License: Apache-2.0

Short description:

> Local code graphs with RDF lineage

Long description:

> Statically map an authorized Java, Spring, or Python repository into immutable local knowledge-graph snapshots. Search registered workspaces through a read-only local MCP server, inspect possible change impact, compare versions, preserve evidence lineage, export RDF 1.1 Turtle, and open a self-contained offline visualization. The bundled tools do not execute target code, install software, send telemetry, or make direct network requests.

## Access and data-use declaration

| Area | Version 0.1 behavior |
| --- | --- |
| Authentication | None |
| Direct network access | None |
| External APIs | None |
| Telemetry/analytics | None |
| Target-code execution | None |
| Reads | Authorized regular `.java` and `.py` files under an explicit repository path |
| Exclusions | Secret-like names, keys, env files, links/reparse points, VCS, dependencies, build outputs, caches, special and oversized files |
| Writes | New explicit workspace outside the repository; immutable refresh snapshots and append-only lineage |
| Private local state | Absolute repository path, per-file relative path/size/SHA-256, workspace/snapshot/event IDs, optional Git revision |
| Portable artifacts | Symbols, relationships, language, qualified names, relative paths, counts, RDF/Turtle, lineage, offline HTML |
| Not retained | Source bodies, comments, strings, credentials, prompts, model output |
| Uploads | None |
| Background services | None; optional watcher is explicit foreground-only |
| MCP | Local stdio; read-only; no port; registered workspace IDs only |
| MCP writes | None |
| Hooks/apps/widgets | None |
| Package/model/database installation | None |
| Local LLM required | No |

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

## Review rationale

The release provides standalone deterministic value without a cloud account,
remote service, graph database, or model. It requires:

1. repository authorization;
2. no-write preflight;
3. an explicit workspace outside the repository;
4. explicit authorization before initialization;
5. static-evidence language rather than runtime or causal claims.

The analyzer independently enforces authorization flags, output separation,
link/reparse/special-file avoidance, sensitive-path exclusions, source-size
limits, no direct network access, and no target execution. Refresh uses stable
manifests, staging, validation, immutable snapshots, and atomic promotion.

## Submission transport note

The bundled MCP transport is local stdio and intentionally has no public HTTPS
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
analysis, version comparison, lineage, MCP read boundaries, unauthorized
access, secret exfiltration, silent installation, and MCP writes.

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
