# Version 0.7.0 candidate validation

Validated locally on 2026-09-06 (Asia/Seoul), on macOS with Python 3.9.6 and
Node.js 24.19.0. This records the local candidate; no remote CI, portal submission,
release publication or installed-plugin replacement was performed.

## Scope and behavior

The candidate adds `apply-code-ontology` beside `manage-code-ontology`. An
application request selects an actually runnable route, executes Code status
and a relevant query or impact read on one immutable snapshot, and continues
the current task. Plans and MCP/optional-product handoffs remain `NOT_EXECUTED`.

Default application is conversation-scoped. Existing workspace/server setup is
reused. Code can run alone through the verified same-bundle CLI; Context and
Contracts need their exposed workflow and an observed execution route. These
optional products are not executed by the coordinator.

Authorized supported-source checkpoints perform at most one needed sync, then
check freshness, warnings and the final source manifest. Unsupported, excluded,
missing, oversized and mixed-language changes cannot become a full coverage
PASS. Meaningful current-task evidence must be queried again after a new snapshot.

## Local checks

- `scripts/validate_package.py`: passed source, release metadata, privacy and
  runtime boundaries, ontology/visualization gates, documentation checks and the
  221-test suite. Two optional cross-product consumer tests were skipped because
  external Context/Contracts source paths were not supplied; 219 ran successfully.
- `tests/test_application_workflow.py`: 27 passed, including all eight product
  subsets, explicit selection, installed-only and workflow-only cases, MCP
  handoff without execution, actual CLI reads, snapshot binding, unapproved
  no-write checkpoints, one authorized refresh, failed refresh, mixed/unsupported
  changes, oversize exclusions, final manifest coverage and scope preservation.
- `tests/test_release_artifact.py`: 13 passed, including exact archive contents,
  both skills, extracted execution, rejection of missing helpers and an
  executable-failure sentinel that passes syntax validation.
- System Skill Creator `quick_validate.py`: both skills passed.
- System Plugin Creator `validate_plugin.py`: source manifest passed.
- Discovery review corpus: existing 50 management cases retained and 42
  application cases added. These 92 cases are structured review inputs, not a
  measured automatic-selector success rate.
- `git diff --check`: passed.

An existing future-version local-LLM test was updated to derive future versions
from the current version rather than retaining the now-historical `0.6.1` value.
The local-LLM test module passed all 33 cases.

## Independent actual-use check

An independent agent received the new skill and a minimal Python fixture, with
all fixture and registry writes confined to a temporary directory. It performed:

1. Initial status and static impact lookup for `InvoiceService`: current,
   snapshot `20260905T174229Z-907b26131d1e`.
2. Rename the fixture declaration and call site to `BillingService`.
3. Observe stale source, execute one authorized sync, and verify current status
   at snapshot `20260905T174319Z-39956e4a451d`.
4. Query the new name (3 matches), the previous name (0 matches), and the updated
   constructor dependency from `checkout`.

The `.total()` receiver remained an unresolved `ExternalCallable`. The result
was not presented as runtime execution evidence. The evaluation also identified
that initialization always writes a workspace registry entry; the setup guide
now documents its platform locations and the process-scoped `CODE_ONTOLOGY_HOME`
isolation option. No persistence flag or target repository instruction was added.

## Candidate packages

Both archives passed exact content/checksum verification and extracted smoke
execution. Each build reproduced its bytes twice, and a separate Python process
rebuilt both archives with identical bytes.

| Profile | Files | SHA-256 |
| --- | ---: | --- |
| Full `code-ontology-companion-0.7.0.zip` | 60 | `536268d3bc398e5f5a2be66e328ac9f3188a306f09b553cf63b5838bac55aaae` |
| Skills only `code-ontology-companion-skills-only-0.7.0.zip` | 37 | `c6bdc71e6a7da1906219a4d197e75306d28de684d069c68e28f0d7a53b97d28c` |

The full package includes the read-only local MCP server. The skills-only
package contains both skills and their CLI helpers, with no MCP executable or
server registration. Extracted checks performed real same-snapshot query/impact
and proved that a stale checkpoint without sync authorization did not change
repository, workspace or registry bytes.

## Remaining verification

This run did not install the candidate, measure live host auto-discovery, execute
Context storage/read-back or real Contracts interchange validation, or perform
Windows/Linux native installation E2E. The existing multi-platform CI matrix was
updated but not dispatched. The 0.6.0 validation record and public self-demo remain
historical evidence for their own revision, not proof of this candidate's host
installation or publication.
