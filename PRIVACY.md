# Privacy Policy

Effective date: August 1, 2026

Code Ontology Companion processes supported source files locally only after a
user identifies an authorized repository and requests analysis.

## Data categories and purposes

The analyzer may read regular `.java` and `.py` files to derive:

- symbol, annotation, decorator, and qualified names;
- validated dotted policy identifiers used by recognized Java policy accessors;
- static structural relationships and language labels;
- repository-relative paths, counts, and parse warnings.

It does not intentionally retain source bodies, comments, arbitrary string
literals, credentials, API keys, environment variables, raw prompts, or raw
model responses. A dotted policy identifier is retained only as a semantic
`PolicyLeaf`; its configured value and surrounding source text are not stored
in the ontology.

For local refresh and integrity, the private workspace retains:

- the absolute repository path;
- per-file relative paths, sizes, language labels, and SHA-256 values;
- local snapshot, workspace, event, and optional Git revision identifiers.

These private fields are used only to locate an authorized repository, detect
changes, preserve snapshot integrity, and maintain lineage. Portable RDF,
offline HTML, and normal MCP results omit the absolute repository path and full
file fingerprints.

If the user explicitly enables optional local LLM enrichment for one
workspace, private local state additionally retains:

- the fixed loopback provider and endpoint, consent/data-scope versions, and
  selected model name, digest, format, size, and completion capability;
- normalized model suggestions that reference existing ontology node IDs,
  their suggested pipeline roles and confidence values;
- snapshot, prompt-schema, input, and ontology digests needed to identify the
  exact inferred run.

These suggestions are labeled `inferred`, grant no authority, and are stored in
separate create-only sidecars. They are not merged into observed ontology,
RDF, runtime-binding, or MCP data. Raw prompts and raw responses are not stored.

Secret-like filenames, private-key and keystore extensions, symbolic
links/reparse points, common VCS/dependency/build/cache/virtual-environment
directories, special files, and files over the configured limit are excluded.

## Local storage, retention, and deletion

`doctor` and `preflight` create no files. With explicit confirmation,
initialization writes a local workspace with an immutable initial snapshot
outside the target repository. Refresh creates new immutable snapshots and retains older
snapshots; lineage records append to a local journal. An explicitly authorized
runtime-binding operation may read one local JSON or `policy-json` policy
document and create one canonical, read-only receipt at a new user-selected
path outside the target repository. It does not modify the policy or target.

The publisher receives no copy of these artifacts. They remain until the user
deletes the selected workspace and, if desired, its entry from the local
Companion registry using normal local file-management tools. Version 0.3.1 does
not provide automatic retention or cloud backup.

## Network, recipients, and third parties

The deterministic analyzer, workspace CLI, workbench, launcher, and MCP server:

- make no network requests;
- collect no telemetry, analytics, cookies, advertising identifiers, or IP logs;
- call no external API and send no source or ontology data to the publisher;
- install no package, model, database, daemon, or background watcher;
- open no listening network port.

The optional `local_llm.py` helper is a separate boundary. Detection runs no
process, makes no connection, and writes no file. Only after the user sees the
data disclosure and explicitly consents may the helper:

- connect to the literal IPv4 loopback endpoint `127.0.0.1:11434`;
- inspect existing Ollama model metadata and reject responses that report
  remote/cloud markers or omit required metadata;
- send at most a bounded portable subset of symbol names, qualified names,
  repository-relative paths, node types, and observed relationship metadata;
- receive a bounded JSON completion and retain only normalized inferred output.

It does not send source bodies, comments, arbitrary strings, secrets,
credentials, absolute paths, private manifests, source fingerprints, or raw
file hashes. It accepts no arbitrary URL, LAN/public host, proxy, redirect, or
API key, and never installs or downloads a model or starts the Ollama service.
Authorized enrichment executes the selected model, may allocate CPU/GPU memory,
and sends `keep_alive=0` to request immediate unload after the response. The
loopback service presented as Ollama and its selected model are a third-party recipient managed
by the user. Companion cannot authenticate that service or guarantee or control
its external network behavior or retention; users must review and constrain
their Ollama environment or leave enrichment disabled.

`localMetadataVerified=true` records only that fields reported by Ollama's
`/api/tags` and `/api/show` responses passed bounded validation. It does not
attest the model weight bytes, authenticate the loopback service, prove that
inference ran locally, or prove that Ollama made no outbound connection. A
remote marker in the chat response is rejected, but that response arrives only
after the disclosed metadata has already been sent to the service.

The read-only MCP server communicates with the local Codex host over stdio and
accepts only registered workspace IDs. It cannot initialize, refresh, record,
delete, or upload a workspace.

When Codex invokes the skill or MCP tools, selected command or tool output such
as symbols, qualified names, counts, warnings, snapshot IDs, and relative paths
may be processed by OpenAI to provide the requested functionality. OpenAI is a
separate recipient governed by its
[applicable terms](https://openai.com/policies/terms-of-use/) and
[privacy policy](https://openai.com/policies/privacy-policy/). The operating
system and Codex host are governed by their providers' terms.

## User controls

Users can:

- stop before initialization after reviewing a read-only preflight;
- choose the local workspace location;
- decline runtime installation or external transfer;
- decline optional local LLM inspection without losing core functionality;
- inspect or disable per-workspace local LLM configuration while preserving or
  manually deleting prior inferred sidecars;
- inspect the JSON, Turtle, Markdown, and HTML artifacts;
- stop foreground watching at any time;
- delete local workspaces and registry data;
- keep exports local or separately authorize sharing.

## Contact

Privacy questions:

https://github.com/battle-doll/code-ontology-companion/issues
