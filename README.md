# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

Explore an authorized Java/Spring or Python codebase as a spatial 3D map. Find symbols, follow source-backed dependency paths, and see what changed between snapshots.

**0.8.0** · Keep your selected GPT-6 Astra or GPT-6.1 Sol model and reasoning effort.

## Use it in your current task

> Apply Code Ontology Companion here and use it while we work on this project.

Codex checks the available tools, reuses your authorized workspace, and starts with its current status plus a relevant symbol search or impact lookup. Related reads use one snapshot. After meaningful Java/Python changes, it refreshes within the authorized scope and reports freshness, coverage and warnings. The default scope is this conversation; project-wide guidance is saved only when you explicitly request it.

> Set up ontology here for this task.

For a general request, it checks which of Code, Context and Contracts can actually run. Code works on its own. An explicitly named product takes priority; a missing product is reported without automatic installation. Context saves only your selected, confirmed decisions or constraints and verifies them by reading them back. Contracts checks the actual selected exchange JSON and preserves unsupported, loss and not-checked results.

[Application workflow](skills/apply-code-ontology/SKILL.md)

## Install / Use

[Install from the plugin directory](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [Download GitHub packages](https://github.com/battle-doll/code-ontology-companion/releases)

This source is version 0.8.0. The directory has a separate review and publication process; its available version may differ. Both application and management skills are included in the skills-only bundle, with the analyzer, workbench and local MCP setup guidance; it does not include an MCP server. The complete GitHub package also contains the read-only stdio MCP server. No cloud endpoint is required.

## Explore the actual self-ontology

[**Open the 3D explorer →**](https://battle-doll.github.io/code-ontology-companion/)

Generated from this plugin’s own supported source, with a committed revision and inspectable evidence. Select a module, focus a symbol, then inspect its connections and source locations. The scene shows a static snapshot. Command-click or Ctrl-click opens the demo in another tab.

[Snapshot provenance](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [Architecture](docs/ARCHITECTURE_AND_ROADMAP.md)

## Version 0.8.0 capabilities

- Apply ontology to the current conversation with a real first lookup and authorized change checkpoints.
- A 3D-first offline workbench with structure, impact and changes views, camera focus and progressive exploration.
- Ranked exact-symbol search, structural filters, pagination and snapshot-pinned reads.
- Directional dependency paths with evidence for each step and explicit traversal limits.
- Consistent additions, removals and modifications, including changed evidence.
- Java/Spring types, imports, conservative calls, injection and proxy signals; Python modules, functions, calls and pipeline-role heuristics.
- Selected Code references with immutable evidence locators for Context and explicit Contracts compatibility.
- Keyboard and text exploration, reduced-motion support and a safe text-list fallback.

## Quick start

Requires Python 3.9+. First inspect support without writing. Initialize an outside-repository workspace only for code you own or are authorized to analyze, after approving the proposed local artifacts.

```bash
python3 skills/manage-code-ontology/scripts/companion.py doctor --repo "/path/to/repo"
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo"
```

```bash
python3 skills/manage-code-ontology/scripts/companion.py init --repo "/path/to/repo" --workspace "/path/outside/repo/ontology" --authorized
python3 skills/manage-code-ontology/scripts/companion.py query --workspace "/path/outside/repo/ontology" --term "OrderService"
python3 skills/manage-code-ontology/scripts/companion.py impact --workspace "/path/outside/repo/ontology" --symbol "OrderService" --direction incoming
python3 skills/manage-code-ontology/scripts/companion.py diff --workspace "/path/outside/repo/ontology"
```

Select production source explicitly when a repository also contains tests or copied code. Repeat `--source-root` for multiple relative directories. The scope is retained on refresh; `sync --source-root .` explicitly restores whole-repository discovery. Conflicting declarations from different files stop analysis instead of merging. The workbench exposes all groups through paging and search, then drills into members and source-backed relationships; overview connections are labeled aggregates, and path filters are heuristics, not deployment evidence.

Display depth has three levels: all modules, the selected module’s components, and the selected component’s members. Other areas stay collapsed. Call highlighting independently follows one, two or three actual static CALLS hops. Complete indexed inventory remains available through explicit expansion and pages, with collapsed and off-page counts.

```bash
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo" --source-root src/main
python3 skills/manage-code-ontology/scripts/companion.py sync --workspace "/path/outside/repo/ontology" --source-root src/main
```

## Evidence and compatibility

`graph.html`, `ontology.json` and `ontology.ttl` share the same source ontology. RDF 1.1 Turtle includes `RelationshipEvidence`; PROV-O-compatible lineage preserves evidence history. `inferred` is not validated, and `runtime_unknown` is not proof of execution. Evidence attachment coverage is not accuracy.

Code owns source structure; Context owns decisions and their validity over time; Contracts validates supported exchange shapes. Products remain independently usable. [AI data contract](skills/manage-code-ontology/references/ai-data-contract.md) · [Reference exchange](skills/manage-code-ontology/references/code-reference.md).

Context handoff retains a reference to the original artifact. Direct conversion of real snapshots into the stricter Contracts draft remains unsupported; see the reference guide for the verified scope.

Optional existing Ollama at `127.0.0.1:11434` requires separate consent and keeps suggestions outside observed evidence. No model is needed for deterministic analysis.

## Model-era local workflow

Keep your selected GPT-6 Astra or GPT-6.1 Sol model and reasoning effort. Use local MCP for AI evidence and the offline HTML for people on Windows, macOS and Linux. The complete package preserves seven tools and adds `ontology_large_modules`, `ontology_large_search`, `ontology_large_neighbors` and `ontology_evidence_bundle` for eleven bounded read-only tools. Related reads stay pinned; large-project paths stay within one selected module. No measured model advantage or runtime success is claimed.

[Five-language workflow guide](skills/manage-code-ontology/references/model-era-workflow.md) · [Translation coverage](docs/TRANSLATION_COVERAGE.md)

## License and privacy

Apache-2.0. The analyzer does not execute target code, send telemetry or make direct network requests. User workspaces stay local; the public demo is an explicit publication of this public repository only. Source bodies, comments and secrets are not retained.

[Privacy](PRIVACY.md) · [Security](SECURITY.md) · [Support](SUPPORT.md) · [Terms](TERMS.md) · [Changelog](CHANGELOG.md)
