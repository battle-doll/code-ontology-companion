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

## Version 0.2 capabilities

- Map Java packages, imports, types, methods, inheritance, and basic dependencies.
- Recognize common Spring stereotypes, `@Bean`, constructor/field injection,
  AspectJ advice, transaction, async, cache, authorization, and retry proxy signals.
- Map Python modules, imports, types, functions, decorators, calls, inheritance,
  and heuristic Extract/Transform/Load/Validate/Orchestrate roles.
- Skip unchanged refreshes using a private source fingerprint.
- Refresh unchanged source when the analyzer or Companion version changes.
- Build changed repositories in staging and atomically promote an immutable snapshot.
- Preserve the last known-good snapshot when analysis or validation fails.
- Compare snapshots and maintain observed/declared/inferred/validated/approved lineage.
- Export portable RDF/Turtle and a self-contained HTML/SVG graph with no CDN.
- Query registered workspaces through seven read-only local MCP tools.
- Map recognized Java policy accessor reads to the control-flow branches they
  guard, without retaining arbitrary string literals.
- On explicit request, create a create-only, mode-`0400` AETHER Lab runtime
  binding receipt from a fresh ontology snapshot and an unshadowed local policy.

Changed repositories are fully reanalyzed in version 0.2. The fingerprint
avoids unnecessary unchanged runs; per-file incremental parsing is a future
optimization.

## Privacy and safety defaults

- Analyze only code you own or are authorized to inspect.
- `doctor` and `preflight` are read-only.
- Initialization requires `--authorized` and a new workspace outside the repository.
- Source bodies, comments, and arbitrary string literals are not retained.
  Validated dotted policy identifiers passed to recognized Java policy accessors
  may be retained as `PolicyLeaf` nodes.
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

### Optional AETHER Lab runtime binding

This local CLI operation is deliberately not exposed through the read-only MCP
server. Version 0.2 supports this exact mode-`0400` receipt on macOS/POSIX, not
Windows. It requires a fresh current snapshot, a supported policy leaf, an exact
duplicate-free local JSON or `policy-json` document, a new output path outside the source
repository, and explicit authorization:

```bash
mkdir -m 700 "/private/path/runtime-bindings"

python3 skills/manage-code-ontology/scripts/companion.py \
  runtime-binding \
  --workspace "/path/to/ontology-workspace" \
  --policy-leaf "strategy.exits.timeStopMinutes" \
  --policy-document "/path/to/authorized/repository/policies/policy.md" \
  --output "/private/path/runtime-bindings/time-stop.json" \
  --authorized
```

The output implements `aether.runtime-effective-ontology-binding/v1` exactly:
canonical JSON plus one LF, a self-hash, an external file hash returned by the
command, sorted hashed ontology-edge references, frozen source/snapshot hashes,
exact false authority, create-only publication, and mode `0400`.

For this receipt, `runtimeEffective=true` has one narrow meaning: in the frozen
active source, the named leaf reaches a production control-flow branch under
static analysis, and the supplied policy document has no known AETHER
shadow/enable condition that disables that leaf. The producer rebuilds the
graph from the active source and requires exact node/edge equality with the
snapshot. Test/fixture-only paths, stale source, unused reads, active
stop-loss/take-profit ladders, disabled trailing, ambiguous paths, or a changed
output fail closed.

It does **not** prove that the branch ran, an order was submitted, the policy is
safe, or profit changed. It grants no candidate-generation, gate, approval,
promotion, policy-write, order, network, runtime-write, or funds authority. The
v1 receipt cannot include a policy-document hash without breaking the Lab's
exact schema, so the consuming Lab must independently recheck the exact
baseline policy and shadow conditions at use time.

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
security verdict, causal proof, or correctness guarantee. A runtime-binding
receipt narrows static source reachability and known policy shadowing only; it
does not establish runtime execution or outcome causation. Reflection,
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
