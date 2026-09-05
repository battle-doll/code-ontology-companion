# Workspace setup

Read for a new workspace or an explicitly requested local runtime configuration.

### 1. Check the local runtime

Run:

```bash
python3 "$COMPANION" doctor --repo "/absolute/path/to/authorized/repository"
```

Use another verified Python 3.9+ executable only when `python3` is missing or too old. The core workflow needs no graph database or LLM.

### Optional existing local LLM

First determine whether the user selected an already initialized workspace. If
one exists, run `local_llm.py status --workspace ...` before detection:

- when it is enabled, do not ask, probe, or configure again; use only the
  on-demand enrichment rule below;
- when it is disabled, do not ask again or re-enable it unless the user
  explicitly requests re-enablement;
- only when it is `not_configured` should the detection and consent sequence
  below run.

Inspect the `optionalRuntimesDetected.ollama` field from `doctor`. Only when it
is true, run the additional read-only indicator check:

```bash
python3 "$LOCAL_LLM" detect
```

If supported Ollama is detected, disclose the fixed `127.0.0.1:11434`
loopback endpoint, exact portable-metadata data scope, inferred sidecar output,
no-install/no-Ollama-service-start behavior, and that enrichment executes the
selected model, may allocate CPU/GPU memory, and requests immediate unload with
`keep_alive=0`. Disclose that Ollama's own network and resource behavior remains
outside Companion's control. For a new workspace, defer the question, probe,
and configuration until Step 3 has successfully initialized that workspace.
For an existing `not_configured` workspace, ask now whether to inspect models
and configure it. Do not connect or write before an affirmative answer.

After both consent and successful workspace initialization, run
`probe --authorized`. Configure automatically only when one
eligible model exists; when several exist, ask which model to use. If Ollama is
absent, declined, unavailable, has no eligible model, or returns unverifiable
metadata, continue with deterministic analysis and write no LLM configuration.
Treat eligibility as validation of Ollama-reported metadata only, not proof of
model weights, loopback-service identity, local execution, or absence of
outbound Ollama traffic.

For a configured workspace, after making the deterministic snapshot current,
run `enrich --authorized` on relevant user-requested analysis. Report every
use and keep the result `inferred`. Never call it implicitly from `init`,
`sync`, `watch`, or MCP. Follow the complete sequence in
[local-llm.md](local-llm.md).

### 2. Preflight without writing

```bash
python3 "$COMPANION" preflight --repo "/absolute/path/to/authorized/repository"
```

Summarize supported languages, file count, exclusions, and limits without listing source names unless requested.

### 3. Initialize after explicit confirmation

Choose a new workspace outside the repository. Include both the workspace and
its local registry entry in the proposed write scope: `init` always registers
the workspace; it has no no-registration flag. The registry is `registry.json`
under `CODE_ONTOLOGY_HOME` when set, otherwise:

- Windows: `%LOCALAPPDATA%\CodeOntologyCompanion` (or the equivalent user-local AppData folder).
- macOS: `~/Library/Application Support/CodeOntologyCompanion`.
- Linux: `$XDG_DATA_HOME/code-ontology-companion`, or `~/.local/share/code-ontology-companion`.

For an explicitly isolated trial, set `CODE_ONTOLOGY_HOME` for those processes
to an approved directory inside the trial boundary before initialization, and
use the same value for any registry-based reads. Preserve the existing registry
for ordinary project use. This registry locates workspaces; it does not enable
permanent conversation instructions or install/configure an MCP server.

After authorization covers these local artifacts, run:

```bash
python3 "$COMPANION" init \
  --repo "/absolute/path/to/authorized/repository" \
  --workspace "/absolute/path/outside/repository/code-ontology-workspace" \
  --authorized
```

Initialization creates an immutable snapshot containing JSON, RDF 1.1 Turtle, a report, a self-contained interactive HTML workbench, a private source manifest, and PROV-O-compatible lineage. The workbench searches the full portable index but renders only a bounded relationship neighborhood at a time. It also registers a random local workspace ID so the read-only MCP server can query it without accepting arbitrary filesystem paths.

### Optional read-only local MCP

Configure the local MCP server only when the user asks to enable or use it.
Read [local-mcp.md](local-mcp.md) first. The official Skills bundle
provides this setup workflow, and the matching complete plugin package on the
project's GitHub Releases page supplies `mcp/server.py` with its bundled
scripts. Keep those files together and do not download, install, relocate, or
synthesize the server without separate authorization.

Before changing Codex configuration, verify Python 3.9 or newer and the exact
complete-package server as regular files, show the resolved paths, preserve all
unrelated configuration, and obtain confirmation. Do not add a duplicate
manual entry when the bundled `.mcp.json` entry already loads successfully.

On macOS, resolve `python3` with `command -v python3`; on Linux, do the same or
use the distribution's verified absolute Python 3 path. Configure the resolved
absolute paths in `~/.codex/config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

On Windows, resolve an existing Python 3.9+ interpreter with
`py -3 -c "import sys; print(sys.executable)"`, then use literal TOML strings in
`%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = 'C:\absolute\path\to\python.exe'
args = ['C:\absolute\path\to\complete-code-ontology-companion\mcp\server.py']
startup_timeout_sec = 30
enabled = true
```

Open a fresh Codex process after configuration. First call
`ontology_list_workspaces`, then use the returned snake-case `workspace_id` with
`ontology_status` or another read tool. Never pass an arbitrary filesystem path
to MCP. Initialization, refresh, and lineage writes remain explicit CLI
operations, and MCP never invokes optional local-LLM enrichment.
