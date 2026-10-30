# Privacy Policy

[English](PRIVACY.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/PRIVACY.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/PRIVACY.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/PRIVACY.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/PRIVACY.md)

Effective / updated: **2026-10-30** · Version **0.9.3** · Developer: **battle-doll**

Code Ontology Companion processes explicitly selected, authorized local code using static analysis. It does not execute the target project. This policy describes the plugin's local data handling; authorization to analyze is separate from permission to disclose or publish the results.

## Data read and retained locally

Adapters have declared support tiers for Java/Spring, Python, JavaScript/TypeScript, Bash and additional languages; see the [implementation guide](docs/PIPELINE_0_9_0.md). The selected-scope inventory retains outcomes for unsupported, excluded, failed and blocked files as well as analyzed files. Inaccessible or bounded traversal can leave the original denominator UNKNOWN. A secret-like word in a code filename does not automatically remove selected structural code. Unsafe paths, protected non-source formats, configured exclusions and resource limits retain their own outcomes.

Private workspaces can contain:

- selected paths, language/support labels, file sizes, source hashes, source spans, evidence IDs, counts, warnings and omissions;
- declarations, relationships, bounded static fragments, condition IR, supported constants and schema expressions, typed policy inputs and source-linked business concepts/properties;
- business claims and review/revocation records, source/business snapshot bindings, immutable partitioned SQLite/JSON, RDF projections and lineage;
- the absolute source location and private configuration, access policy, registry entries, cache/recovery metadata and integrity material needed for local operation.

These are source and policy data and can be confidential. Comments and quoted literals are opaque by default. Exact original text can nevertheless be retained locally for permitted occurrences under an explicitly selected private literal/documentation review or local-source-analysis permission. Such permission does not establish business meaning, instruction authority or publication permission; source text remains untrusted data. Structured fragments and authorized original text must not be treated as anonymous merely because the whole source file was not copied.

The application workflow uses the selected workspace, query, changed paths and host-observed tool availability. It does not automatically archive conversation history. Optional Context and Contracts operations remain separately authorized workflows.

## Protection and access boundaries

`CODE_ONTOLOGY_PRIVACY_FILE` selects a private HMAC-SHA256 protection profile. Its key and registered fingerprints must stay protected outside source/output roots and must not be printed, committed or exported. Supported checks reject matches for configured names/emails and registered protected values, as well as recognized unsafe patterns. Detected protected material is a hard veto: administrator approval, aliases, knowledge review and local occurrence permission cannot override it.

Required export profiles must be present and valid or export is refused. Older ordinary local-exploration paths may allow an optional profile; omitting it does not establish personal-name protection. Bounded text/encoding checks are not complete DLP, OCR or a guarantee of detecting all unregistered secrets, identities, binary/image content or third-party output. See [privacy operations](skills/manage-code-ontology/references/privacy-operations.md).

Current source/business snapshot pins, bindings, access grants and privacy protection are checked for the requested read or export. Policy-only views withhold restricted source evidence and locators. Full record/evidence exports require their broader read permissions and export grant; explicitly projected business/policy HTML can use `read_policy` plus `export_html` while withholding restricted evidence. Private profiles, access configuration and keys are not portable knowledge artifacts. A summary view is not permission to publish. Later ACL changes or revocation cannot remotely revoke copies already exported.

## Local storage and user controls

Authorized `analyze`/`refresh` and other operator CLI commands write the selected local workspace, immutable snapshot history and associated local state. Older snapshots remain until the user removes the selected workspace/history and, if desired, its local registry entry using local file-management tools. Exported copies and inferred sidecars require separate deletion. The plugin supplies no hosted user-data storage service or automatic cloud backup.

The local stdio MCP tools are read-only over registered workspaces: they do not initialize, refresh, delete or upload knowledge, or open a listening network service. Users can restrict the selected roots and recipients, stop analysis, withhold export or optional enrichment consent, review local artifacts and manually remove their own local data. Review/permission revocation affects subsequent authorized reads, not independently retained copies.

## Network and other recipients

Deterministic analysis and generated offline HTML send no telemetry and make no direct network uploads. The plugin has no feature that uploads installed users' private workspace artifacts to the publisher. Opening an external link or choosing to share an export is separate from local analysis.

An AI host can process or forward selected command/MCP results, including source-derived text or locators allowed by the chosen view. Local analysis permission does not authorize that transfer. When OpenAI receives such output, its [applicable terms](https://openai.com/policies/terms-of-use/) and [privacy policy](https://openai.com/policies/privacy-policy/) apply separately; the host and operating system also have their own providers' policies.

Optional Ollama enrichment is separate and requires disclosure plus explicit consent. It uses an existing service at `127.0.0.1:11434` and a bounded portable metadata subset, such as symbol/qualified names, relative paths, node types and observed relationships—not source bodies, comments, secrets, private manifests or raw file hashes. It does not discover arbitrary endpoints, download models or start Ollama. Private state may retain consent/model metadata and normalized `inferred` sidecars, separately from observed evidence; the helper does not retain raw prompts/responses. See the [local-model guide](skills/manage-code-ontology/references/local-llm.md) for its exact supported boundary.

Reported Ollama metadata checks do not authenticate the service or model weights, prove local inference or guarantee no outbound connection. The user-managed service/model is a separate recipient; Companion cannot control its external network behavior or retention. Leave enrichment disabled if that environment is not trusted.

## Contact

Privacy support: [GitHub issues](https://github.com/battle-doll/code-ontology-companion/issues). Do not post personal names/emails, secrets, protection profiles or private artifacts in public issues. The public developer alias is **battle-doll**.
