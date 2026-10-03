# Privacy operations — 0.8.1

[English](privacy-operations.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/PRIVACY_OPERATIONS.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/PRIVACY_OPERATIONS.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/PRIVACY_OPERATIONS.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/PRIVACY_OPERATIONS.md)

## Keep private identifiers local

The supported generated ontology artifacts, local MCP results and offline HTML use local privacy checks. A configured private profile can reject specified personal names and emails; generic checks also reject email-like private values. Public code, fixtures, package metadata, reports and test output must not contain actual personal values. Use battle-doll as the public publisher alias.

`CODE_ONTOLOGY_PRIVACY_FILE` selects a private profile outside the protected source/output roots. The profile stores a private key and HMAC-SHA256 fingerprints with bounded lengths, not the original identity text. It is private material: do not commit, upload, print or embed its key or fingerprints in HTML/JSON/MCP output. The loader reads the file afresh, rejects links/reparse points and malformed or oversized profiles, and requires mode `0600` on POSIX. Windows still uses its existing local ACL; this check does not establish ACL correctness. Use the actual runtime contract instead of inventing a setup command.

Runtime failures expose a category, not a matched private value. A missing optional profile does not provide personal-name protection, and no profile can discover every unknown name. Supported JSON/HTML entity/percent/unicode-escape decoding is bounded to three rounds; a still-decodable value is rejected with `encoding_depth`. Normalization remains bounded; arbitrary binary metadata, visual text, third-party output and every possible encoding are outside this guarantee. Do not convert a local PASS into a promise of zero personal data everywhere.

## Review every publication channel

Before a public PR, require a fresh trusted receipt that verifies GitHub account email privacy for the actual account. A manually written receipt, local `git config`, configured artifact or unit test is not current provider evidence. Audit every selected source/provider-generated commit ref; local HEAD alone excludes some automatically retained PR merge refs. A direct branch test validates that branch's code, not the safety of future provider-generated commits.

For the official directory, verify the live public developer identity separately. If it would expose any personal identity instead of battle-doll only, use **HOLD** before upload/submission/publication. Uploaded files, portal draft checks, approval and public listing are different states. An unresolved retained-ref exposure remains unresolved until the provider confirms removal; do not claim global cleanup from changing a branch or local repository.

## Preserve the product and its limits

From a complete source checkout or full release, after securely configuring `CODE_ONTOLOGY_PRIVACY_FILE`, run the read-only maintainer preflight with Python 3.9 or later and an authenticated GitHub CLI:

```sh
python scripts/check_publication_privacy.py
```

The script requires nonempty known-name and email deny lists. It checks the alias-only manifest, local Git `--all` identities/messages/ref names through the shared scanner, the public GitHub profile (name null/empty/battle-doll/배틀돌, email null), PR titles/bodies and each recorded REST `merge_commit_sha` author/committer/message. It reads at most 100 PRs with at most two API calls per PR; a full 100-entry page, unreadable data or exhausted time budget remains UNKNOWN. It excludes unfetched/deleted/provider-internal refs, historical source blobs, issue/comments, CI logs and image pixels. It cannot verify GitHub email-privacy UI controls or the selected OpenAI verified identity, so **HOLD** and exit code 1 remain even if its mechanical checks pass. There is no manual `--verified` bypass. Optional `--output` writes a sanitized JSON receipt outside the source tree; findings contain rule, PR number and count only. The receipt does not authorize a PR or upload. This release-maintenance CLI is absent from the skills-only profile and does not add network behavior to ontology generation, MCP or HTML.

Windows, macOS and Linux remain supported. AI uses the local read-only MCP; people use the requested generated offline HTML. This privacy patch creates no separate HTML report, remote endpoint, telemetry service or identity upload workflow. The user's model and reasoning effort remain unchanged.

The HTML selection-copy field uses a relative snapshot/entity/edge query instead of a full local file URL. Free search text is not saved or replayed through URL/history; native JSON parse errors are not echoed in the UI.

Run the source, selected-ref and extracted-package privacy gates on the final candidate and verify both exact release profiles. Keep the existing 0.8.0 tag immutable. Synthetic regression tests establish detector behavior for those cases; native host E2E, professional translation review, complete accessibility and external-service deletion require their own evidence. The five-language guides and [coverage map](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/TRANSLATION_COVERAGE.md) state the supported scope.
