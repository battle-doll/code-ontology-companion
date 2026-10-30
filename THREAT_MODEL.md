# Threat Model

[English](THREAT_MODEL.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/THREAT_MODEL.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/THREAT_MODEL.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/THREAT_MODEL.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/THREAT_MODEL.md)

Version **0.9.3** · Developer: **battle-doll**

## Scope and assets

Code Ontology Companion statically analyzes explicitly selected, authorized local input. It does not import, build, test or execute the target application. Its own bundled helpers and the selected Python/Node runtime are separate trusted components.

Protected assets include source structure and business knowledge, original text retained under explicit occurrence permission, immutable snapshots and lineage, private workspace paths, access/review records, protection profiles and optional inference sidecars. These local artifacts can be confidential without copying a complete source file.

## Trust and access boundaries

Filenames, symbols, comments, literals, annotations, analysis errors and generated knowledge are untrusted data. A source statement or reviewed knowledge claim is not an instruction to the agent. Local analysis permission, access grants, business review, execution authorization and public-sharing permission are distinct.

Authorized CLI operations manage the selected local workspace. Stdio MCP reads registered workspaces; it does not initialize, refresh, delete or upload them. A principal alias is bound to the local process; query arguments cannot grant roles. This is an application boundary within the OS account, not remote identity verification or tenant isolation.

An AI host may process or forward permitted CLI/MCP results to its provider. Local analysis does not authorize that transfer. Optional Ollama enrichment is separately consented, uses a fixed loopback endpoint and bounded portable metadata, and keeps `inferred` results separate from observed evidence.

## Threats and mitigations

| Threat | Implemented boundary |
| --- | --- |
| Prompt or HTML injection | Static analysis avoids target execution. Schema checks and escaped output keep retained source-derived content as data. Review does not make it trusted instructions. |
| Silent scope loss | The inventory retains analyzed, excluded, unsupported, failed and blocked outcomes. Bounded or inaccessible traversal can leave the denominator `UNKNOWN`; a secret-like code filename alone does not cause silent removal. |
| Links, path escapes or special files | Containment checks, link/reparse rejection, regular-file reads and separate source/workspace/output boundaries limit access. Unsafe or unavailable items remain incomplete. |
| Source or artifact replacement during reading | File identities, hashes, bounded descriptor reads and before/after checks bind selected data. Path and handle metadata providers retain their own change checks. |
| Personal identifiers or registered secrets in output | Configured private HMAC-SHA256 profiles and supported pattern checks veto protected material. Administrator approval or occurrence permission cannot override a detected veto. |
| Unauthorized knowledge disclosure | Current grants, selected source/business pins and review/revocation state constrain reads and exports. Policy-only projections withhold restricted evidence; full views require broader permissions. |
| Stale or mixed knowledge | Snapshot/spec/digest bindings identify selected immutable inputs. A valid historical snapshot does not prove that current source or application behavior was rechecked. |
| Generation mistaken for complete meaning | Staging, validation, create-only publication and retained progress/omission counts separate storage completion from semantic completeness. Exact calls, candidates, unresolved cases and `UNKNOWN` stay distinct. |
| Repository writes or hidden MCP mutations | Analysis reads target data; authorized state changes stay in the selected local workspace and explicitly authorized local registry/configuration. Exposed MCP operations remain read-only. |
| Resource exhaustion or transport loss | File, time, record, byte and output budgets bound processing. Pagination, truncation and omitted/frontier counts remain explicit. The partitioned worker's SQLite cap is not a total process-memory guarantee. |
| Unusable whole-corpus browser views | Default human HTML uses depth 2, maximum 3; the initial view is bounded to 32 nodes, 64 aggregate edges and 128 KiB of data. Selected views use local chunks. Current-page search and explicit record/MCP routes have separate scopes and permissions. |
| Unintended network disclosure | Deterministic analysis and offline HTML make no direct uploads or telemetry calls. Host forwarding and consented `127.0.0.1:11434` enrichment are separate recipients and boundaries. |

## Windows publication and runtime integrity

The Windows implementation holds ancestor, parent and stage handles, rejects reparse boundaries, checks current private access, and uses handle-relative native rename without replacing an existing destination. Synchronous stage handles and both native return/status results must confirm completion. Windows path executable bits or creation-time fields are not equated with CRT handle metadata; each provider's full before/after mode and time checks remain active while exact file identity is bound.

Unexpected pending completion or native-memory release failure is `BLOCKED`, not publication success. The implementation retains at most one fixed native allocation of up to 1 KiB and associated handles per module, suppresses cleanup and further exports, and requires a fresh process. It does not automatically delete uncertain artifacts or claim that restarting validates them. Public entry points avoid bytecode writes into the closed runtime bundle; unexpected runtime entries still cause rejection.

## Residual limits

- Symbols, relative paths, structured fragments and permitted original text can reveal confidential architecture or policy. HMAC does not encrypt the knowledge corpus; human abstraction does not grant sharing permission.
- Bounded text/encoding checks are not universal DLP or OCR. Unknown identities, unregistered secrets, binary/image metadata and third-party output can remain undetected. Missing optional profiles do not establish personal-name protection.
- Static support is bounded. Reflection, generated code, dynamic dispatch, units, business intent and runtime conditions can remain unresolved. Schema/RDF validity, evidence links or command success do not prove complete policy meaning or runtime execution.
- Another process with the OS user's permissions may access local files. Compromise of the runtime, host, OS or account is outside this boundary. Ollama metadata does not authenticate service/weights, prove local execution or control that service's outbound traffic and retention.
- Revocation constrains later authorized reads; it cannot remotely recall offline exports or independent copies. Local retention and deletion remain operator-controlled.
- Crash durability is filesystem/platform-specific; the pipeline reports Windows `file_flush_only`. Native behavior requires native verification. ABI mocks, configuration and passing another OS's tests do not establish Windows success.

## Public artifacts and verification

Inspect the exact selected source, ZIP, listing/assets and selected source/provider-generated commit identities before distribution. Keep private profiles, keys and workspace artifacts outside public packages. The public developer alias is **battle-doll**; a manifest alias or local Git setting does not verify the provider-saved directory identity. Unreadable history or provider state remains `UNKNOWN`; retained content is not considered removed without confirmation.

Package checks, native regression, upload, review submission, approval and publication are separate evidence states. See the [Privacy Policy](PRIVACY.md), [privacy operations guide](skills/manage-code-ontology/references/privacy-operations.md) and [security reporting guide](SECURITY.md).

## Changes to the boundary

Reassess privacy, security, licenses and submission eligibility before adding remote endpoints/AI calls, target execution, automatic dependency/model installation, authentication, telemetry, daemons, filesystem hooks, write-capable MCP operations or external knowledge storage.
