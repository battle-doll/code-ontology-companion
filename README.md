# Code Ontology Companion

Code Ontology Companion is an independent Codex plugin for maintaining a
privacy-conscious local knowledge graph of an authorized Java/Spring or Python
repository.

It combines deterministic static analysis, immutable snapshots, RDF 1.1
Turtle export, PROV-O-compatible lineage, an offline graph, and a read-only
local MCP server. The bundled tools do not execute target code, install
software, send telemetry, or make direct network requests.

Codex may process command output such as symbols, counts, and
repository-relative paths to carry out a requested workflow. That platform
processing is governed by OpenAI's
[applicable terms](https://openai.com/policies/terms-of-use/) and
[privacy policy](https://openai.com/policies/privacy-policy/). Installing this
plugin does not make Codex an offline product.

## Version 0.1 capabilities

- Map Java packages, imports, types, methods, inheritance, and basic dependencies.
- Recognize common Spring stereotypes, `@Bean`, constructor/field injection,
  AspectJ advice, transaction, async, cache, authorization, and retry proxy signals.
- Map Python modules, imports, types, functions, decorators, calls, inheritance,
  and heuristic Extract/Transform/Load/Validate/Orchestrate roles.
- Skip unchanged refreshes using a private source fingerprint.
- Build changed repositories in staging and atomically promote an immutable snapshot.
- Preserve the last known-good snapshot when analysis or validation fails.
- Compare snapshots and maintain observed/declared/inferred/validated/approved lineage.
- Export portable RDF/Turtle and a self-contained HTML/SVG graph with no CDN.
- Query registered workspaces through seven read-only local MCP tools.

Changed repositories are fully reanalyzed in version 0.1. The fingerprint
avoids unnecessary unchanged runs; per-file incremental parsing is a future
optimization.

## Privacy and safety defaults

- Analyze only code you own or are authorized to inspect.
- `doctor` and `preflight` are read-only.
- Initialization requires `--authorized` and a new workspace outside the repository.
- Source bodies, comments, and string literals are not retained.
- A private local configuration stores the absolute repository path, and a
  private manifest stores per-file sizes and SHA-256 values for freshness checks.
- Portable RDF, HTML, and normal MCP responses omit absolute paths and full fingerprints.
- Secret-like files, links/reparse points, dependencies, VCS contents, and
  generated outputs are excluded.
- Target projects are never imported, built, tested, or run.
- The MCP process uses stdio, opens no listening port, and accepts workspace IDs
  rather than arbitrary filesystem paths.
- No daemon, graph database, local model, package, or watcher is installed.

Symbol names and repository-relative paths may still be confidential. Keep
workspaces and exports local unless sharing is separately authorized.

## Requirements

- Codex with plugin, skill, and bundled MCP support
- Python 3.9 or newer
- No third-party Python package, graph database, Java runtime, or local LLM

The MCP launcher uses the JavaScript runtime supplied by supported Codex plugin
hosts to locate Python without invoking a shell.

## Manual quick start

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  doctor --repo "/path/to/authorized/repository"

python3 skills/manage-code-ontology/scripts/companion.py \
  preflight --repo "/path/to/authorized/repository"
```

After reviewing the preflight and authorizing local artifact creation:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  init \
  --repo "/path/to/authorized/repository" \
  --workspace "/path/outside/repository/ontology-workspace" \
  --authorized
```

Refresh and query:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  sync --workspace "/path/to/ontology-workspace"

python3 skills/manage-code-ontology/scripts/companion.py \
  query --workspace "/path/to/ontology-workspace" --term "OrderService"

python3 skills/manage-code-ontology/scripts/companion.py \
  diff --workspace "/path/to/ontology-workspace"
```

## Workspace pipeline

```text
authorized source
  -> private source manifest
  -> isolated staging analysis
  -> artifact validation
  -> immutable snapshot promotion
  -> current snapshot pointer
  -> RDF / HTML / read-only MCP
```

Each snapshot contains `ontology.json`, `ontology.ttl`, `report.md`,
`graph.html`, `snapshot.json`, and a private `source-manifest.json`. The
workspace also contains an append-only `lineage.jsonl` and portable
`lineage.ttl`.

## RDF portability and lineage

The core vocabulary preserves the Explorer 1.0 `co:` namespace so older
exports remain compatible. Lineage uses W3C PROV-O plus a documented Companion
namespace. Turtle exports can be imported into RDF 1.1-compatible stores.
Store-specific indexes, reasoning rules, and extensions may need mapping.

## Static-analysis limits

The graph is navigation and change-planning evidence, not a runtime trace,
security verdict, causal proof, or correctness guarantee. Reflection,
generated code, runtime Spring conditions, dynamic proxies, external
configuration, dependency versions, and Python metaprogramming may be
incomplete.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
python3 scripts/build_release.py
```

Security issues: [SECURITY.md](SECURITY.md). Support: [SUPPORT.md](SUPPORT.md).

## License and independence

Source is licensed under Apache-2.0. This project is independent and is not
affiliated with or endorsed by OpenAI, Broadcom, VMware, the Spring project,
Oracle, or the Python Software Foundation. Product names describe
compatibility only.
