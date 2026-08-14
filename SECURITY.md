# Security Policy

[English](SECURITY.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/SECURITY.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/SECURITY.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/SECURITY.md)

## Supported version

Security fixes are provided for the latest released version.

## Report a vulnerability

Do not include private source, secrets, credentials, local absolute paths, or
ontology artifacts in a public issue.

Use GitHub private vulnerability reporting for:

https://github.com/battle-doll/code-ontology-companion

If private reporting is unavailable, open a minimal public issue asking for a
private channel without exploit details or confidential data.

## Security model

Version 0.5.2:

The deterministic core and supported extensions:

- performs static parsing and never imports or executes target code;
- rejects repository and workspace roots that are links/reparse points;
- skips link-like, special, sensitive-name, dependency, VCS, and generated files;
- enforces per-file, total-source, source-count, graph, impact, HTTP, candidate,
  and suggestion limits;
- keeps the optional 3D constellation within explicit node, edge, depth, and
  frame budgets, pauses it while hidden, and fails safely to the default 2D
  view without adding a CDN, WebGL dependency, worker, or network primitive;
- creates artifacts only in a new, explicit workspace outside the repository;
- builds refreshes in staging and atomically promotes immutable snapshots;
- refreshes an unchanged repository when the analyzer or Companion version changes;
- retains the last known-good snapshot after failed refreshes;
- keeps deterministic analysis, workspace operations, workbench, and MCP
  network-free and collects no telemetry;
- detects optional Ollama without executing it, probing a port, or writing;
- requires explicit workspace-scoped consent before a separate helper contacts
  only `127.0.0.1:11434`, rejects reported remote/cloud markers or missing API
  metadata, and stores output only as unvalidated create-only inferred sidecars;
- starts a read-only stdio MCP process when enabled by the Codex host;
- opens no port, accepts registered workspace
  IDs rather than filesystem paths, and exposes no write, refresh, install,
  delete, upload, or execution tool;
- installs no runtime, package, database, model, daemon, or background watcher.

The optional helper does not make Ollama part of the trusted analyzer. Ollama's
own networking, logging, model behavior, and security remain outside the
Companion boundary. Leave enrichment disabled or enforce operating-system
controls when loopback-only delivery is not a sufficient guarantee.
Enrichment runs the selected model and may allocate CPU/GPU memory; the helper
sends `keep_alive=0` to request immediate unload after the response, but cannot
attest the separately managed service's resource release.
`localMetadataVerified=true` is validation of Ollama-reported API metadata, not
attestation of model weights, loopback-service identity, local execution, or
absence of outbound Ollama traffic.

Generated output is not automatically safe to publish. Symbols and relative
paths can reveal confidential architecture.
