# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

Explore an authorized Java/Spring or Python codebase as a spatial 3D map. Find symbols, follow source-backed dependency paths, and see what changed between snapshots.

**Astra launch update · 0.6.0.** Celebrating GPT-6 Astra with more precise retrieval, traceable evidence and focused skill instructions. A cinematic interface for people; structured ontology data for AI. [Release details](docs/ASTRA_RELEASE.md).

## Install / Use

[Install from the plugin directory](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [Download GitHub packages](https://github.com/battle-doll/code-ontology-companion/releases)

This source is version 0.6.0. The directory has a separate review and publication process; its available version may differ. The official skills-only bundle contains the analyzer, workbench and local MCP setup guidance. The complete GitHub package also contains the read-only stdio MCP server. No cloud endpoint is required.

## Explore the actual self-ontology

[**Open the 3D explorer →**](https://battle-doll.github.io/code-ontology-companion/)

Generated from this plugin’s own supported source, with a committed revision and inspectable evidence. Select a module, focus a symbol, then inspect its connections and source locations. The scene shows a static snapshot. Command-click or Ctrl-click opens the demo in another tab.

[Snapshot provenance](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [Architecture](docs/ARCHITECTURE_AND_ROADMAP.md)

## Version 0.6.0 capabilities

- A 3D-first offline workbench with structure, impact and changes views, camera focus and progressive exploration.
- Ranked exact-symbol search, structural filters, pagination and snapshot-pinned reads.
- Directional dependency paths with evidence for each step and explicit traversal limits.
- Consistent additions, removals and modifications, including changed evidence.
- Java/Spring types, imports, conservative calls, injection and proxy signals; Python modules, functions, calls and pipeline-role heuristics.
- Selected Code references with immutable evidence locators for Context and explicit Contracts compatibility.
- Keyboard and text exploration, reduced-motion support and a safe 2D fallback.

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

## Evidence and compatibility

`graph.html`, `ontology.json` and `ontology.ttl` share the same source ontology. RDF 1.1 Turtle includes `RelationshipEvidence`; PROV-O-compatible lineage preserves evidence history. `inferred` is not validated, and `runtime_unknown` is not proof of execution. Evidence attachment coverage is not accuracy.

Code owns source structure; Context owns decisions and their validity over time; Contracts validates supported exchange shapes. Products remain independently usable. [AI data contract](skills/manage-code-ontology/references/ai-data-contract.md) · [Reference exchange](skills/manage-code-ontology/references/code-reference.md).

Context handoff retains a reference to the original artifact. Direct conversion of real snapshots into the stricter Contracts draft remains unsupported; see the reference guide for the verified scope.

Optional existing Ollama at `127.0.0.1:11434` requires separate consent and keeps suggestions outside observed evidence. No model is needed for deterministic analysis.

## License and privacy

Apache-2.0. The analyzer does not execute target code, send telemetry or make direct network requests. User workspaces stay local; the public demo is an explicit publication of this public repository only. Source bodies, comments and secrets are not retained.

[Privacy](PRIVACY.md) · [Security](SECURITY.md) · [Support](SUPPORT.md) · [Terms](TERMS.md) · [Changelog](CHANGELOG.md)
