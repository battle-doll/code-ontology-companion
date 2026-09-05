# 0.6.0 validation record

Local validation on 2026-09-05 used Python 3.9 and the available Node runtime.
The complete suite passed **192 tests**, including explicitly enabled local
Context and Contracts consumer tests. The separate skill validator and Draft
2020-12 JSON Schema validation of a generated native reference also passed.

Both complete and Skills-only ZIP profiles passed source validation, exact file
allowlists, extracted-package smoke tests and two independent byte-identical
builds. They contain 56 and 33 files respectively. Published checksums accompany
the release assets; repository CI provides the separate platform matrix results.

Browser review used the generated self-ontology in the Codex in-app browser at
1280×720 and 390×844. The 3D atlas, search ranking and real search continuation
(80 to 160 results), module selection, dependency view, text relationship
selection and source-evidence panel were exercised. A first snapshot correctly
reports that no comparison baseline exists. No browser console warnings/errors
were observed. Mobile document width matched the viewport without horizontal
overflow. This is scoped browser QA, not certification of every browser or
assistive-technology combination.

The public-source builder has a regression test showing that ignored Python
files and working-tree edits cannot enter a committed source archive. Public
deployment is restricted to this repository's main branch. The demo manifest
records the actual source revision, supported-source scope and artifact hashes.

The Context test uses synthetic records in temporary stores, reopens the store,
exports through the current consumer, validates its draft export and resolves
the retained Code artifact locator. This does not establish native Context
import support or direct Code-to-Contracts draft compatibility. Real Code
snapshots still return `unsupported` for that stricter draft projection.

Actual Astra model A/B results, real-repository speed comparisons and peak-memory
measurements remain unmeasured. Functional test counts and source evidence
attachment rates do not demonstrate a model-quality or runtime-correctness gain.
