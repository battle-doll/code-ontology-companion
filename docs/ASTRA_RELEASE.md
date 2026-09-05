# Astra launch update

Code Ontology Companion 0.6.0 celebrates the launch of GPT-6 Astra with focused
improvements to structured code retrieval, traceable static dependency paths,
consistent snapshot comparison and concise skill instructions. The human-facing
workbench uses a 3D-first spatial interface over the same ontology evidence.

This is an independent project release. It does not imply OpenAI endorsement,
change the user's selected model, or claim a measured Astra performance gain.
The deterministic analyzer continues to work without a model or API account.

## Public self-ontology

[Explore Code Ontology Companion in 3D](https://battle-doll.github.io/code-ontology-companion/)

The demo is generated from an isolated archive of this repository's committed Java/Python source with
the same shipped analyzer and workbench. The public snapshot manifest identifies
the source revision, analyzer version, counts and artifact checksums. JavaScript,
CSS, deployment behavior and runtime effects are outside that analyzer coverage.
The source includes scripts, tests and public synthetic fixtures. The 3D scene
shows the supported source graph, not a hand-authored architecture.

The Pages workflow keeps absolute repository paths, registry state and full
source fingerprints in an isolated private build workspace. Only the portable
HTML, JSON, Turtle and a public snapshot manifest are published. Ordinary user
workspaces are never included or uploaded.

GitHub sanitizes README anchors and removes `target="_blank"`. The demo link
opens a directly viewable HTML page; use Ctrl-click or Command-click to keep
the README in its existing tab. The hosted page itself does not need a download.

## Validation meanings

Source tests check deterministic extraction, privacy boundaries, filtering,
dependency paths, snapshot pinning, modified evidence and local interoperability.
Browser checks assess the visible workbench and navigation. Neither is a
model-quality benchmark.

A reproducible model comparison should use the same model/effort, repository
snapshot, task set and resource budget for: plain repository tools, the previous
Companion release, and this release. Measure correct answers, source citations,
false impact claims, appropriate uncertainty, tool calls, tokens and elapsed time.
Report unmeasured results as unmeasured; do not infer them from test counts or
evidence attachment coverage.
