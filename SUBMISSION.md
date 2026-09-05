# Public Plugin Submission Notes

[English](SUBMISSION.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/SUBMISSION.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/SUBMISSION.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/SUBMISSION.md)

## Listing

- Name: Code Ontology Companion
- Version: 0.6.1
- Candidate status: local source/package candidate; version 0.6.1 has not been submitted, approved or published
- Published baseline: version 0.5.3 was verified as **Published** in OpenAI Platform on 2026-08-29; this historical verification is not a 0.6.1 approval
- Directory verification: the prior exact-name public search and version detail page succeeded; candidate routing, automatic selector invocation, and broader-query routing remain unmeasured
- Directory: https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c
- Developer: battle-doll
- Category: Developer Tools
- Distribution: Public
- Submission type: Skills only
- Components: application and ontology management skills with a CLI, offline 3D-first workbench,
  selected-reference export, optional consent-based Ollama helper, and local MCP setup workflow
- GitHub package: the same two skills plus a bundled cross-platform read-only stdio
  MCP server
- License: Apache-2.0

Short description:

> Explore code and impact in 3D

Long description:

> Explore an authorized Java, Spring, or Python repository through immutable local knowledge-graph snapshots. Search by symbol, language, type, or relative path; follow bounded static dependency paths with source evidence; and compare structural or evidence changes between selected snapshots. A self-contained 3D workbench brings structure, impact, and changes into three views, with keyboard controls, searchable text alternatives, reduced-motion behavior, and a 2D fallback. The Skills-only package runs locally; the optional complete package also provides read-only MCP tools for registered workspaces. Static evidence does not prove runtime behavior. Deterministic analysis does not execute target code or upload user data, and optional local-model suggestions remain separate inferred records.

## Current-task application

Version 0.6.1 adds the `apply-code-ontology` skill alongside
`manage-code-ontology`. It adapts the workflow to the current conversation and
starts an actual status check and relevant search or impact lookup. It preserves
existing workspace/server setup, prefers actually exposed MCP tools, and uses a
verified sibling CLI when MCP is unavailable. The skill does not hot-load MCP or
claim that installing files made tools callable. Plans and handoffs are reported
separately from executed operations.

A general ontology request considers runnable Code, Context and Contracts
products; an explicitly named product takes priority. Each product remains
independently usable and missing products are not installed. Context accepts
only selected, confirmed records followed by read-back. Contracts validates the
selected real interchange JSON; unsupported, loss and not-checked outcomes are
not converted into success. A meaningful Java/Python change can invoke the
existing sync command within the user's authorization and then check freshness,
coverage and warnings. Unsupported and mixed-language changes remain explicit.

Application defaults to the current conversation. No activation file, global
setting, project instruction, background automation or new task is created by
default. Persistent guidance needs an explicit scope request. The source update
and local candidate packages are not a portal submission or a replacement of an
installed plugin. Host routing and Windows installation E2E remain separate
validation work.

## Astra launch edition

Version 0.6.0 is an independent launch-themed update. The implementation adds
snapshot-pinned and filtered retrieval, ranked symbol matching, evidence-bearing
dependency paths, evidence-aware snapshot differences, compact skill guidance,
and a simpler 3D-first workbench. Rendering uses bounded node/edge counts,
adaptive frame pacing, reduced-motion handling and hidden-page pause.

These are product changes, not a measured model comparison. The plugin does not
select or require Astra, change the user's model or effort, claim an Astra A/B
gain, or imply OpenAI endorsement. Release preparation and test results do not
establish directory approval or publication.

## Access and data-use declaration

| Area | Version 0.6.1 candidate behavior |
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
| Portable artifacts | Symbols, legacy-compatible relationship triples, stable evidence and rule IDs, qualitative evidence bases, runtime-status indicators, bounded limitations, relative paths and optional line spans, adapter coverage, counts, RDF/Turtle `RelationshipEvidence`, lineage and offline HTML. Selected-reference artifacts additionally bind explicit repository/module/snapshot identity without private workspace IDs, source bodies or full source fingerprints |
| Visualization | Default Canvas2D 3D spatial map with structure/impact/changes views; bounded 160-node/480-edge 3D scene, deterministic positions, adaptive frame pacing, searchable text and keyboard routes, reduced-motion, forced-colors/high-contrast, assistive status, hidden-page pause, and 2D failure fallback |
| Not retained | Source bodies, comments, arbitrary string literals, policy values, credentials, raw prompts, raw model responses |
| Uploads | None from the shipped analyzer, workspace, reference export, or MCP tools. The publisher's separate public self-demo build is limited to this public plugin repository and is not a user-workspace upload feature |
| Background services | None; optional watcher is explicit foreground-only |
| MCP | Optional local stdio server, read-only, no listening port, registered workspace IDs only; Windows, macOS, and Linux setup is documented in the skill bundle |
| MCP writes | None |
| Hooks/apps/widgets | None; the offline workbench is not a hosted ChatGPT widget |
| Package/model/database installation | None |
| Local LLM required | No. Optional existing Ollama only after workspace-scoped consent; no install/download/Ollama-service start. Enrichment uses deterministic requests of at most 20 candidates and 16 KiB, `think=false`, `num_ctx=8192`, `num_predict=2048`, a maximum 180-second timeout, atomic sidecar publication, and `keep_alive=0` |

## Local MCP annotations

The seven MCP tools set:

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

All seven tools declare bounded `inputSchema` and `outputSchema` contracts,
including explicit structured error variants. Search and neighbors accept a
selected snapshot. Search supports language/type/path filters and offsets;
neighbors supports direction, relationship filters and evidence for each path
step. Snapshot changes include modified nodes and relationship evidence.

Tools list workspaces, read status, search, inspect static neighbors, list
history, compare snapshots, and read lineage. Initialization, refresh, lineage
writes, installation, deletion, upload, target execution, and arbitrary path
access are not exposed through MCP. Reference export and Context handoff are
separate local workflows, not additional MCP actions.

`chatgpt-app-submission.json` describes these seven optional complete-package
MCP tools for review. It is preparatory metadata, not a new remote service,
an approval receipt, or a replacement for the Skills-only portal archive.

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
3D default and 2D fallback contract, finite rendering budgets, keyboard and
pointer alternatives, reduced-motion and hidden-page behavior, high-contrast
and assistive markers, legacy payload handling, and safe 2D recovery. DOM search,
relationship lists, details and 2D provide accessible routes to the same bounded
evidence. This release targets WCAG 2.2 AA design behavior
but does not claim blanket conformance without separate manual AT/browser review.

Optional local enrichment is not part of the observed analyzer authority. Its
indicator check executes nothing and makes no connection. After consent, the
helper uses only literal IPv4 loopback, rejects reported cloud/remote markers,
missing or invalid required API metadata, and unbounded/malformed responses,
sends no source bodies/secrets/absolute paths or
private hashes, and stores normalized output as create-only `inferred`
sidecars. Ollama's own network behavior remains an explicitly disclosed
residual risk.

## Interoperability scope

The native selected-reference profile preserves legacy node IDs and `co:`
semantics while adding explicit repository/module/snapshot references. Missing
source locations stay unresolved. A stored HEAD SHA does not prove that a dirty
working tree equals that commit; current exports therefore report the Contracts
draft code profile as unsupported rather than fabricating revision verification.
A separate synthetic source-located fixture exercises that draft's validator.

Context can retain an immutable artifact locator using its existing evidence
shape. A synthetic consumer test covers simulated approval, storage, reopening,
Context export validation and recovery of the original rich Code evidence from
the retained artifact. This is reference handoff, not native Code import,
full-graph migration, actual human authorization, or ChatGPT host E2E proof.
Code, Context and Contracts remain independently installable; data and execution
permissions do not transfer between them. See the
[selected-reference contract](skills/manage-code-ontology/references/code-reference.md).

## Submission package

The official portal upload uses **Skills only**. The two-skill bundle includes the
application workflow and portable analyzer, workspace CLI, selected-reference exporter, workbench, optional local-LLM helper, and the
Windows/macOS/Linux local MCP configuration workflow. The complete GitHub
package additionally bundles the stdio MCP executable and automatic launcher.

Build the portal-safe archive with:

```bash
python3 scripts/build_skills_only_release.py
```

The generated ZIP contains the manifest, both skills, scripts, references, license,
notice, and icons. Use this Skills-only ZIP for the portal's Skills upload and
the full ZIP for local plugin installation and GitHub distribution. Uploading,
submitting, approving and publishing are separate steps; these preparation
instructions do not claim that version 0.6.1 has completed any of them.

## Evaluation cases

[evals/cases.json](evals/cases.json) contains positive and negative reviewer
cases covering preflight, initialization, relationship evidence and adapter
coverage, conservative Java calls, golden/forbidden quality expectations,
offline 3D-first visualization controls and accessibility boundaries, Spring/Python analysis,
filtered and snapshot-pinned search, bounded dependency paths, evidence-aware
version comparison, immutable reference handoff, lineage,
local-LLM consent/decline/absence and malformed response
handling, MCP read boundaries, unauthorized access, secret exfiltration,
silent installation, and MCP writes. Local-LLM cases use bounded fake responses
and do not require reviewer infrastructure. The MCP review JSON contains exactly
five positive and three negative cases using the actual seven tool names. These
are reviewer scenarios, not claims that directory routing or every host flow
has already passed.

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
