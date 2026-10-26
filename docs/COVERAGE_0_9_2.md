# 0.9.2 omission detection and coverage verification

[English](COVERAGE_0_9_2.md) | [한국어](ko/COVERAGE_0_9_2.md) | [日本語](ja/COVERAGE_0_9_2.md) | [简体中文](zh-CN/COVERAGE_0_9_2.md) | [Русский](ru/COVERAGE_0_9_2.md)

Developer: **battle-doll (배틀돌)**. Local MCP remains for AI clients; generated offline HTML remains for people. Windows, macOS and Linux remain supported targets. Native operating-system validation is reported separately from local regression tests. This workflow does not publish, install or restart a target application.

## Start with the selected scope

Ask your agent: “Inventory my entire selected scope, retain every excluded or failed item in the denominator, then show the six coverage stages and remaining gaps.” The source inventory is read-only:

```sh
python3 "$COMPANION" coverage-inventory --repo /path/to/source --source-root src
```

The default inventory mode uses pipeline adapters; `--mode legacy` measures Java/Python legacy support. Built-in ignored directories remain in the ledger. `.gitignore` patterns are not interpreted by this inventory, so they are not an exclusion or completeness guarantee.

`COMPANION` is the trusted bundle's `skills/manage-code-ontology/scripts/companion.py`. Use an existing Python 3.9 or newer; Windows can use `py -3`. Repeat `--source-root` for additional authorized roots. Keep validation outputs outside the source repository and installation. A sensitive-looking filename is not evidence that the entire source structure must disappear. Secret values, links/reparse points, unsafe paths and unreadable content remain protected. Exclusions, unsupported languages, limits, decoding errors and inaccessible frontiers must remain visible. An inaccessible directory makes the total file denominator `UNKNOWN`; visible files alone cannot establish complete scope.

If an item cannot be processed, retain its target, reason, impact and possible alternative. Ask for the user's decision before advancing past that blocked item; already authorized normal processing does not require another approval.

## Six independent measurements

| Stage | What can count | What does not establish completion |
| --- | --- | --- |
| `scope_files` | Processed files divided by the independently selected file inventory | Only files that passed filters |
| `declarations_types` | Exact declarations/types in a named expectation set | File presence or similarly named symbols |
| `exact_calls` | Exact source callsite and target declaration, with matching evidence | Candidates, placeholders, `IMPORTS`, `IMPLEMENTS`, runtime dispatch guesses |
| `policy_semantics` | Required conditions/formulas independently checked against represented fragments | The existence of a policy node or a numeric constant |
| `mcp_delivery` | All pages of one pinned query, with exact expected payloads | `truncated=false` by itself or a partial page chain |
| `policy_document` | Independently reviewed source facets described in bound paragraph bytes | Citations alone, hashes alone or an unreviewed generated paragraph |

Each stage retains numerator, denominator, percentage, measurement scope, missing items, evidence and limitations. An unknown denominator is `UNKNOWN`, not zero or 100%. A sample ratio applies only to its named sample. Partial prose is a separate category; it never receives an invented 0.5 weight. Evidence attached to every generated relationship is not whole-code coverage. Overall completeness remains `PARTIAL` or `BLOCKED` while gaps, unsupported behavior or unknowns remain, even if command execution and snapshot creation succeed.

## Pinned knowledge and semantics

For a pipeline workspace, obtain a concrete snapshot from `ontology_pipeline_status`, then use `ontology_pipeline_coverage` to page through file outcomes. `ontology_pipeline_search` supports `callsite` and `semantic_fragment` records. Calls retain exact, candidate and unresolved states; a static interface target is not an observed runtime implementation. Semantic fragments preserve restricted Java field/constant, assignment, condition and return-expression structure. Arbitrary strings and sensitive values are withheld. Unresolved calls, unsupported control flow and missing initializers retain spans and reason codes. `represented` means supported expression syntax was retained; it does not certify a whole business rule. Units remain `UNKNOWN` unless an independently supported binding exists. The existing executable typed-policy fragment is a separate contract.

Bind every result to `snapshotId`, `sourceFingerprint`, `scopeDigest` and `analysisSpecId`; bind each source locator to its file digest. Follow `nextOffset` until the terminal page and retain `queryDigest`, offsets, totals, returned counts and exact payloads. Missing first, middle or last pages, mixed pins, changed queries, duplicate IDs and same-ID payload changes invalidate the receipt. A snapshot-bound status read is not a new source freshness check.

`coverage_contract.validate_policy_document` accepts independent source expectations, ontology fragments, MCP pages, document bytes and claims. Prose semantic reviews arrive separately as `semantic_reviews`: each receipt binds the exact expectation, source evidence, document, paragraph, covered facets, reviewer and snapshot. Hashes establish consistency, not whether prose logically entails a rule; independent review remains necessary. Direct-source supplementation is labeled `direct_source_supplemented`; even fully described prose then contributes zero to `ontologyOnlyFull`. Full, partial, missing and unsupported claims are counted separately. Any changed source, snapshot, expectation or paragraph requires revalidation. Every claim explicitly sets `directSourceSupplemented` to the JSON boolean `true` or `false`; a missing or nonboolean value leaves its knowledge basis unverified.

To render already measured six-stage results locally:

```sh
python3 "$COMPANION" coverage-validate --input /path/to/coverage-request.json --output /path/to/new-verification
```

The request contains `binding`, six `metrics`, and `remaining`. The command checks metric consistency and writes `coverage.json` and `coverage.md`; it does not invent denominators, perform an independent prose review or turn supplied measurements into proof of global completeness. Preserve private source and validation artifacts locally. Public fixtures and reports must contain no personal identity, secrets or operational details.
