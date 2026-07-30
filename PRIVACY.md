# Privacy Policy

Effective date: July 31, 2026

Code Ontology Companion processes supported source files locally only after a
user identifies an authorized repository and requests analysis.

## Data categories and purposes

The analyzer may read regular `.java` and `.py` files to derive:

- symbol, annotation, decorator, and qualified names;
- validated dotted policy identifiers used by recognized Java policy accessors;
- static structural relationships and language labels;
- repository-relative paths, counts, and parse warnings.

It does not intentionally retain source bodies, comments, arbitrary string
literals, credentials, API keys, environment variables, prompts, or model
output. A dotted policy identifier is retained only as a semantic
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

Secret-like filenames, private-key and keystore extensions, symbolic
links/reparse points, common VCS/dependency/build/cache/virtual-environment
directories, special files, and files over the configured limit are excluded.

## Local storage, retention, and deletion

`doctor` and `preflight` create no files. With explicit confirmation,
initialization writes an immutable local workspace outside the target
repository. Refresh creates new immutable snapshots and retains older
snapshots; lineage records append to a local journal. An explicitly authorized
runtime-binding operation may read one local JSON or `policy-json` policy
document and create one canonical, read-only receipt at a new user-selected
path outside the target repository. It does not modify the policy or target.

The publisher receives no copy of these artifacts. They remain until the user
deletes the selected workspace and, if desired, its entry from the local
Companion registry using normal local file-management tools. Version 0.2 does
not provide automatic retention or cloud backup.

## Network, recipients, and third parties

The bundled Python and JavaScript runtime code:

- makes no direct network requests;
- collects no telemetry, analytics, cookies, advertising identifiers, or IP logs;
- calls no external API and sends no source or ontology data to the publisher;
- installs no package, model, database, daemon, or background watcher;
- opens no listening network port.

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
- inspect the JSON, Turtle, Markdown, and HTML artifacts;
- stop foreground watching at any time;
- delete local workspaces and registry data;
- keep exports local or separately authorize sharing.

## Contact

Privacy questions:

https://github.com/battle-doll/code-ontology-companion/issues
