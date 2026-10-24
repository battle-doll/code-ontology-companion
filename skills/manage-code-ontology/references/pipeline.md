# 0.9.0 local ontology pipeline

[English](pipeline.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/PIPELINE_0_9_0.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/PIPELINE_0_9_0.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/PIPELINE_0_9_0.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/PIPELINE_0_9_0.md)

Developer: **battle-doll (배틀돌)**. Local MCP serves AI clients; people use generated offline HTML. Windows, macOS and Linux remain targets. Native operating-system results and measured capacity are reported separately from unit tests. Nothing in this workflow submits or publishes a plugin.

**0.9.1 HTML** — The generated HTML opens directly in the animated 3D workbench again. Use All records to open the catalog and policies; the map keeps bounded pages, full/focus controls and reduced-motion support.

## Start and refresh

Use Python 3.9 or newer and the trusted installed bundle. `COMPANION` below means its `skills/manage-code-ontology/scripts/companion.py`; Windows can use `py -3`. Choose a new workspace outside the authorized source. Set `CODE_ONTOLOGY_PRIVACY_FILE` to your private identity-deny profile outside source and output roots before HTML or portable export. The profile is never copied into knowledge artifacts. Missing protection is an error for export.

```sh
python3 "$COMPANION" analyze --repo /path/to/source --workspace /path/to/knowledge --authorized --language en
python3 "$COMPANION" refresh --workspace /path/to/knowledge --language en
python3 "$COMPANION" pipeline-status --workspace /path/to/knowledge
```

For a large source collection, add `--capacity large` to `analyze`: ceilings become 250,000 files, 4 GiB input, 5 million records, 8 GiB snapshot output and 7,200 seconds. Defaults remain 25,000 files and 512 MiB input. This is explicit budget selection, not proof that every workload fits. HTML and portable exports keep their separate 1 GiB output limit; use `--no-html` when only sealed knowledge is needed. The per-file AST limit is 20,000 nodes by default and 200,000 with `--capacity large`; source bytes, rule IR and depth limits still apply.

The first command builds sealed knowledge, creates the private owner access policy, registers the workspace for MCP and generates five-language HTML. `--source-root` may be repeated. `--no-html` performs analysis only. `--label` accepts a safe project alias. Refresh keeps old snapshots and reuses unchanged file facts while rebuilding cross-file resolution. Cancellation or failure preserves the prior published snapshot; `pipeline-recover --workspace /path/to/knowledge` resumes or completes a verified interrupted local run. A new generation is not published if source or catalog identity changed during the run.

New pipeline workspaces use `pipeline.json` and immutable partitioned SQLite snapshots. Existing `init`/`sync` workspaces and large-project catalogs remain compatible; they are not silently converted or merged. Pipeline status verifies saved artifacts without opening source files and reports `freshness=not_checked`. Refresh is the operation that verifies the source again.

## What is analyzed

| Family | Implemented boundary |
| --- | --- |
| Python | AST-based declarations, imports and supported static relationships; restricted typed pure-function policy extraction. Dynamic execution remains unknown. |
| Java, JavaScript/TypeScript, SQL, Vue, XML/MyBatis | Conservative syntax/declaration/import and selected framework patterns. These are not full compiler, SQL-dialect or whole-program proofs. Dynamic SQL and reflection remain unresolved. |
| Kotlin, C#, Go, Rust, C/C++, PHP | Bounded declaration/import recognition, with explicit partial coverage and unresolved semantics. |
| Swift, Dart, Ruby, Scala | Bounded declaration/import recognition; complete language semantics and policy extraction are not implied. |
| Bash/POSIX shell, PowerShell | Bash functions, source references, command/pipeline and control-flow boundaries; PowerShell declarations/imports. No script execution, expansion or secret argument collection. Ambiguous quote/heredoc regions are withheld. |
| LangChain/LangGraph, Kafka, Redis | Selected declared agent/tool/graph or messaging/cache relationships. Environment-unknown resources stay separate; raw prompts, keys, values, credentials and runtime success are not collected. |

Each file exposes language, adapter/rule version, source digest, evidence span, analysis level and limitations. An unsupported construct is never silently promoted to resolved knowledge. The broader framework backlog in the archived design remains a roadmap, not a claim that every SDK or version is supported.

The engine uses bounded file batches, one writer and disk partitions. `workers=1` is the implemented execution profile. Explicit higher file/byte/record budgets are available through the engine API; larger limits are safety ceilings, not demonstrated capacity. Graph queries are paged. Complete policy evaluation has a separate rule budget and fails instead of calculating with a silently truncated ruleset.

## Policy knowledge and AI use

The six domain candidates are `product`, `order`, `display`, `claim`, `settlement` and `delivery`. Classification from identifiers is a candidate, not business ownership approval. Policies retain conditions, typed inputs, program order, source assertions and unsupported boundaries. The supported Python fragment includes typed booleans/integers/Decimal, assignment, early returns, boolean conditions and explicitly supported arithmetic/rounding. Unsupported calls, exceptions and loops do not become verified policies. Java and TypeScript support pure, explicitly typed boolean condition functions; numeric, framework-driven, and dynamically dispatched policies remain unsupported. See the generated coverage for the exact supported fragment.

The four policy MCP tools are `list_domain_policies`, `query_policy_rules`, `compare_policy_cases` and `explain_policy_result`. Three additional tools are `ontology_pipeline_status`, `ontology_pipeline_search` and `ontology_pipeline_modules`. The full package has 19 read-only tools, including the 12 existing tools. Skills-only includes setup guidance and the analyzer, not the MCP server.

1. Use `ontology_list_workspaces` and choose a `pipeline` workspace.
2. Obtain a concrete snapshot ID from `ontology_pipeline_status`.
3. Pin that ID in all related reads. `current` or arbitrary filesystem paths are not accepted as query pins.
4. Read a rule, then supply explicit typed context to explain or compare. Amounts use decimal strings where the rule declares Decimal.

`verified_implemented` is the default authority view. `AI-proposed` is excluded from calculation. `approved_business` requires independent explicit approval metadata and is never inferred from extraction success. Model identity and semantic verification are distinct. The default engine uses no model: `modelNotUsed` / `N/A`. No cloud API, model installation, automatic model switch or source transmission is added.

Policy questions use the sealed policy snapshot; they do not reread code or query live databases, brokers or caches. Missing eligibility, usage counts, configuration or time inputs remain `needs_context` or `UNKNOWN`. A maximum over supplied samples is `best_found`. `proven_maximum`/`proven_minimum` requires complete supported scope, exact snapshot/ruleset pins and exhaustive independently known finite inputs; its stated scope never means every policy in an organization. Source-extracted behavior is not business approval or proof of live eligibility.

Local MCP responses may be forwarded by the host to a remote model. Authorizing local source analysis does not authorize that transmission. Select and approve the evidence to send separately.

## Knowledge access

`access.json` is a private local policy. Initialization grants only the operator-bound pseudonymous owner. The trusted launch environment selects `CODE_ONTOLOGY_PRINCIPAL`; its default is `local-owner`. A tool argument cannot select a principal or role. Run separately configured MCP processes for different trusted principal bindings. This is a local process/OS account boundary, not a remote login service or identity provider.

Permissions are `read_structure`, `read_policy`, `read_evidence`, `export_html`, `export_bundle` and `manage_access`, optionally pinned to specific snapshot IDs. Unknown principals, missing or unsafe ACLs, unsupported actions and snapshot mismatches fail closed. Policy-only query responses keep opaque evidence IDs but withhold source locator details; the separate evidence permission is required for those details. Legacy workspaces remain local-owner-only. Permission changes are reread on subsequent requests, not cached as permanent grants.

An explicitly invoked local operator command replaces a principal's grant; it is absent from MCP:

```sh
python3 "$COMPANION" pipeline-access --workspace /path/to/knowledge --principal policy-reader --action read_policy --snapshot SNAPSHOT_ID
```

Omitting `--action` revokes that alias's operations. At least one unrestricted access administrator must remain. Use aliases, never personal names or emails. Domain inference is not an authorization label: this release does not claim trustworthy row-level domain isolation. Use distinct authorized workspaces for separate confidentiality boundaries.

HTML export requires `export_html` plus all three read permissions. A portable export requires `export_bundle` plus all three read permissions. Generated HTML is an offline copy: later ACL changes cannot revoke copies already made. Protect export files and their recipients separately. POSIX ownership/modes and available Windows handle ACL checks fail closed; native Windows execution requires independent verification.

## Human HTML, lineage and interchange

The generated HTML has Korean, English, Japanese, Simplified Chinese and Russian versions. Catalogs, modules, records and policy decisions use bounded pages and exact evidence anchors. Search and 3D cover the displayed page, with complete records reachable through pagination. Existing 3D focus/full controls, reduced motion, text navigation and mobile touch targets remain. Relative links work offline without `fetch` or a required HTTP server. A static page does not imply current source or runtime behavior.

RDF 1.1 Turtle represents assertions and provenance using [PROV-O](https://www.w3.org/TR/prov-o/). [SHACL](https://www.w3.org/TR/shacl/) checks required shape properties; it does not certify truth. Snapshot manifests bind artifact checksums, analysis specification, coverage and source verification time. Checksums are integrity evidence, not trusted signatures. Private source manifests, caches, access policy and local configuration are excluded from portable export. Portability never grants permission to upload.

The earlier [0.9.0 design baseline](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/NEXT_ARCHITECTURE_0_9_0.md) records the intended architecture and acceptance targets. This implementation guide and generated validation receipts state actual support; unmeasured performance, native device checks and future adapters remain explicitly unverified. Official submission, approval and publication are not part of this local workflow.
