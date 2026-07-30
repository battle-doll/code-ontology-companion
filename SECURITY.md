# Security Policy

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

Version 0.2:

- performs static parsing and never imports or executes target code;
- rejects repository and workspace roots that are links/reparse points;
- skips link-like, special, sensitive-name, dependency, VCS, and generated files;
- enforces a 2 MiB source-file limit and bounded query/graph results;
- creates artifacts only in a new, explicit workspace outside the repository;
- builds refreshes in staging and atomically promotes immutable snapshots;
- refreshes an unchanged repository when the analyzer or Companion version changes;
- retains the last known-good snapshot after failed refreshes;
- creates optional runtime-binding receipts only after active-source graph
  reconstruction, production-path proof, known policy-shadow checks, explicit
  authorization, and create-only mode-`0400` publication;
- makes no direct network requests and collects no telemetry;
- starts only a read-only stdio MCP process when enabled by the Codex host;
- opens no port and accepts registered workspace IDs rather than filesystem paths;
- exposes no MCP write, refresh, install, delete, upload, or execution tool;
- installs no runtime, package, database, model, daemon, or background watcher.

`runtimeEffective=true` is limited to static production-branch reachability
with known supplied-policy shadowing absent. It is not proof of runtime
execution, order submission, policy safety, or profit causation, and every
receipt carries exact false authority.

Generated output is not automatically safe to publish. Symbols and relative
paths can reveal confidential architecture.
