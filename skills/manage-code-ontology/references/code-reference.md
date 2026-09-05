# Selected Code references

`scripts/code_reference.py` reads an existing authorized immutable snapshot and
prints a bounded, canonical JSON artifact. It does not index source, execute a
repository, create a file, upload metadata, or contact Context/Contracts. Shell
redirection to a user-selected local file is a separate explicit file operation.

```bash
python3 "$SKILL_DIR/scripts/code_reference.py" \
  --workspace "/absolute/path/to/initialized-workspace" \
  --repository-id "github:owner/repository" \
  --symbol "python:function:package.module.function" \
  --snapshot "immutable-snapshot-id"
```

Select exact legacy symbol IDs returned by query. Repeated `--symbol` arguments
select up to 100 symbols; their one-hop neighborhood is bounded to 100 symbols
and 200 relationships in total. Omitted relationships are counted. This is a
selected reference, not a complete repository export. `--module-root path/to/module`
provides an explicit repository-relative module boundary. The repository identity
is supplied by the user: it is never guessed from a folder name or credential-bearing
Git remote. Preserve it across sessions and use different identities for different
repositories. Changing it intentionally creates different external references.

## Native profile 1.0.0

[code-reference.schema.json](code-reference.schema.json) describes
`code-ontology-reference` version `1.0.0`. This version is independent of the
plugin version, legacy `co:` vocabulary version, and Contracts draft version.

Legacy node IDs and relationship triples remain unchanged. External reference
IDs additionally bind repository, module and snapshot. Artifact URNs contain a
SHA-256 of the canonical selected artifact. This detects a changed retained
artifact; it is not a signature, source access check, or author authentication.
It is not the private repository fingerprint or a per-file hash manifest.

Portable data contains selected symbol names, relative source paths, source spans,
static extraction rules, qualitative evidence bases and runtime limitations.
It never includes source bodies, absolute repository paths, the private workspace
UUID, full source fingerprints, per-file hashes, credentials, or lineage summaries.
Names and relative paths can still be confidential: publishing them requires an
explicitly authorized scope.

Source metadata that does not contain a valid path and span stays `external` or
`source_unresolved`; nothing fabricates a file or line. `outside_module` identifies
neighbors outside the selected module. Empty relationship evidence remains
`evidence_unavailable`. `runtime_unknown` is preserved.

A stored Git revision can be absent. A present revision records the snapshot's
HEAD observation, **not proof that the analyzed working tree equals that commit**.
`revision_binding` and `source_state` explicitly stay `not_checked`; non-Git or
unavailable revisions are `null` / `unavailable`. This remains honest for dirty
working trees, worktrees, packed references and older snapshots. No Git command,
repository scan or network request is performed during export.

`source_observed` describes the static extraction provenance. It does not turn a
name heuristic into an observed runtime relation. Code `approved` / `validated`
lineage is not copied into origin or review status. Native authority is always
untrusted data, with current authorization and runtime behavior not checked.

## Contracts projection

`--format contracts` returns a compatibility report for Contracts
`0.1.0-draft.1`. The native profile and the Contracts profile are different.
Current snapshots lack the source-to-commit binding needed to safely populate
that draft's mandatory revision. The report therefore returns `unsupported`
and no draft artifact, including when a HEAD SHA is present. There is no
`--assume-clean` override. Dirty/non-Git source snapshots remain native references.
Module/selection/authority and unresolved references also have no complete
equivalent in that draft. A separately authored synthetic fixture tests a valid
source-located subset; it is not evidence that real Code exports are compatible.

The current draft is pinned as a compatibility target, not a runtime dependency.
Unknown future versions are not silently accepted. Code can be installed alone;
installing the Contracts plugin is optional. The separately maintained Contracts
validator is exercised against the synthetic code-profile fixture and the
Context consumer's actual draft export when its development source is supplied.

## Context reference handoff

`context_evidence_projection(artifact, exact_symbol_id)` produces the currently
supported `{id, origin, locator}` shape. The locator is an immutable native-artifact
URN and symbol reference, not an external URL. It does not copy the rich evidence
into Context, does not create a decision, and does not approve anything.

The caller retains the native artifact separately. After Context stores and
returns the selected locator, `resolve_context_locator(artifact, locator)` checks
the artifact digest and recovers the symbol, relationships, rules, bases and
limitations without fetching anything. Missing or changed artifacts must not be
reported as verified. Native Code import into Context remains unsupported;
reference handoff is a narrower workflow.

Consumer tests may be enabled by supplying the explicitly selected development
source directories; the shipped plugin never imports these repositories:

```bash
COMPANION_CONTRACTS_SOURCE="/authorized/ontology-companion-contracts/src" \
COMPANION_CONTEXT_SOURCE="/authorized/context-ontology-companion/src" \
python3 -m unittest discover -s tests -p 'test_code_reference.py' -v
```

The optional tests use only synthetic fixtures and temporary Context storage,
with simulated approval clearly separated from human authorization. They test
selected-reference continuity, not ChatGPT authentication, host UI, full backup
restoration, cloud retention, or a public plugin review.
