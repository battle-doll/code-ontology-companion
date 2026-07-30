# Data boundaries

## Authorized inputs

Analyze only a local repository the user owns, administers, or is explicitly permitted to inspect. A path supplied by another person is not proof of authorization.

## Data read

Version 0.2 reads regular `.java` and `.py` files up to 2 MiB. It does not follow symbolic links or Windows reparse points. It skips common dependency, VCS, generated-output, IDE, virtual-environment, and cache directories.

Files whose names suggest credentials, secrets, tokens, private keys, keystores, or `.env` configuration are excluded even if they use a supported extension.

The optional `runtime-binding` command additionally reads one explicitly named,
regular local JSON or Markdown file up to 2 MiB and accepts only a complete JSON
object or exactly one `policy-json` fence. It does not discover or scan other
configuration files.

## Data retained

Portable ontology artifacts may retain:

- symbol and annotation names;
- language and node/relationship types;
- qualified names;
- validated dotted policy identifiers used by recognized Java policy accessors;
- repository-relative source paths;
- aggregate counts and parse warnings.

Private local workspace files additionally retain:

- the absolute repository path needed for refresh;
- per-file byte counts and SHA-256 values used for change detection;
- snapshot, event, and workspace identifiers;
- an optional local Git revision read directly from regular `.git` metadata.

Portable RDF, offline HTML, and normal MCP responses do not intentionally
expose the absolute repository path or full file fingerprints.

No artifact intentionally retains:

- source bodies, arbitrary string literals, or comments;
- file contents;
- environment variables, credentials, API keys, or tokens;
- prompts or model outputs.

Identifiers and relative paths can still be confidential. Keep artifacts local by default and obtain separate authorization before sharing them.

## Writes

Doctor and preflight write nothing. Initialization creates a new explicit
workspace that is neither inside nor a parent of the target repository.
Refresh builds a complete staging snapshot, validates it, and atomically
promotes a new immutable snapshot while retaining the last known-good version.
Decision and validation records append to the local lineage journal.

On explicit authorization, `runtime-binding` reads one exact local JSON or
`policy-json` document and writes one create-only canonical receipt outside the
target repository. The graph retains the policy identifier but not its
configured value. The policy file is not modified. The exact v1 receipt cannot
carry a policy-document hash, so the consumer must recheck the baseline and
shadow conditions at use time.

## Network and execution

The bundled analyzer makes no direct network requests and does not import,
compile, build, test, or execute target code. It installs no packages, models,
databases, daemons, or permanent watchers.

When the plugin is enabled, Codex may start the bundled read-only stdio MCP
process. It opens no listening port, accepts no arbitrary filesystem path, and
queries only workspaces already registered by an explicitly authorized
initialization workflow.

Codex may process analyzer command output to provide the requested workflow. That platform processing is governed by OpenAI's applicable terms and privacy policy. The v0.2 skill does not invoke a separate remote data service or upload generated artifacts.

## Interpretation

The graph is static evidence. `runtimeEffective=true` in the optional AETHER
receipt means only frozen active-source reachability to a production
control-flow branch with known supplied-policy shadowing absent. It is not
evidence that the branch executed, an order was submitted, a policy is safe, or
profit changed. Reflection, runtime bean conditions, generated proxies,
external configuration, dynamic imports, monkey-patching, dependency
injection containers, and generated code may change actual runtime behavior.
Version 0.2 emits the exact create-only mode-`0400` receipt only on
macOS/POSIX. It fails closed on Windows because equivalent owner and permission
semantics are not asserted there.
