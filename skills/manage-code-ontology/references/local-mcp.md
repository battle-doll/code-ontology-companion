# Optional read-only local MCP

[English](local-mcp.md) | [한국어](../../../docs/ko/references/local-mcp.md) | [日本語](../../../docs/ja/references/local-mcp.md) | [简体中文](../../../docs/zh-CN/references/local-mcp.md)

The complete Code Ontology Companion package includes a local stdio MCP server for
querying workspaces that were explicitly initialized by the Companion CLI. It
opens no listening port, accepts registered workspace IDs rather than arbitrary
filesystem paths, and exposes read-only, idempotent tools. It never initializes
or refreshes a workspace, appends lineage, modifies target code, installs
software, uploads data, or invokes optional local-LLM enrichment.

## Package boundary

The official Skills bundle includes this configuration workflow, the
deterministic analyzer, and the optional local-LLM helper. The matching complete
GitHub package supplies the local server in this file tree:

```text
code-ontology-companion/
  mcp/server.py
  skills/manage-code-ontology/scripts/companion.py
  skills/manage-code-ontology/scripts/code_ontology_core.py
```

Use the same-version complete package from the project's
[GitHub Releases](https://github.com/battle-doll/code-ontology-companion/releases)
page and verify its published checksum before configuration. Keep the server
with its bundled scripts; do not mix versions or silently download or install
anything.

## Prerequisites

1. Use Python 3.9 or newer.
2. Initialize at least one authorized repository through the Companion CLI. The
   initialization creates and registers a random workspace ID.
3. Resolve the complete package's `mcp/server.py` and its bundled Companion scripts
   as regular files. Do not use same-named files from the target repository.
4. Configure MCP only when the user asks. Show the exact Python and server paths
   before editing Codex configuration, and preserve unrelated entries.
5. If the complete plugin package's bundled `.mcp.json` already loads successfully,
   do not add a duplicate manual server entry.

## macOS

Resolve and verify Python without changing the machine:

```bash
command -v python3
python3 --version
```

Put the resolved absolute interpreter and complete-package server paths in
`~/.codex/config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Linux

Resolve the distribution's existing Python 3 interpreter and verify it is 3.9
or newer:

```bash
command -v python3
python3 --version
```

Use its absolute path and the extracted complete-package server in
`~/.codex/config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Windows

Resolve an existing Python interpreter without installing one:

```powershell
py -3 --version
py -3 -c "import sys; print(sys.executable)"
```

Use the printed absolute interpreter path and literal TOML strings in
`%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = 'C:\absolute\path\to\python.exe'
args = ['C:\absolute\path\to\complete-code-ontology-companion\mcp\server.py']
startup_timeout_sec = 30
enabled = true
```

If the Python launcher is unavailable, use another already installed,
explicitly verified Python 3.9+ executable. Companion does not install Python.

## Verify in a fresh Codex process

Fully open a fresh Codex process after adding or changing the MCP entry. A
resident process may retain an older server version or tool list.

1. Call `ontology_list_workspaces` with no arguments.
2. Select the returned workspace `id`.
3. Call `ontology_status` with `{"workspace_id":"<id>"}`.
4. Use the same snake-case `workspace_id` for search, neighbors, history,
   changes, or lineage. Do not use `workspaceId` and do not pass a filesystem
   path.

The seven tools are:

- `ontology_list_workspaces`
- `ontology_status`
- `ontology_search`
- `ontology_neighbors`
- `ontology_history`
- `ontology_changes`
- `ontology_lineage`

Every tool declares `readOnlyHint: true`, `destructiveHint: false`,
`openWorldHint: false`, and `idempotentHint: true`. Initialization, refresh,
lineage recording, deletion, installation, upload, and arbitrary-path access
are not MCP operations; use the explicit Companion CLI workflow where an
authorized write is required.

## Troubleshooting

- If `node ./mcp/launcher.mjs` cannot start because `node` is unavailable, use
  the direct Python stdio configuration above instead of installing Node.
- If the tools are absent or report an old version, fully open a fresh Codex
  process and confirm that the configured paths point to one matching complete
  package.
- If a workspace ID is unknown, list registered workspaces under the same OS
  user that initialized them. Do not replace the ID with a path.
- If startup fails, run only the Python version and regular-file checks first.
  Do not execute target code or weaken workspace, link, permission, or output
  protections while troubleshooting.
