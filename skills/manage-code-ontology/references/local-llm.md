# Optional local LLM enrichment

[English](local-llm.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/references/local-llm.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/references/local-llm.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/references/local-llm.md)

Version 0.5.2 can use an existing Ollama installation as an optional, local
inference sidecar. The deterministic ontology remains complete without it and
is always the source of observed evidence.

## Consent sequence

1. For an existing initialized workspace, run `status` first. If it is enabled,
   do not ask, probe, or configure again. If it is disabled, do not ask again
   unless the user explicitly requests re-enablement. Continue this sequence
   only for `not_configured` or a new workspace.
2. `doctor` or `local_llm.py detect` may inspect only known executable/app
   indicators. Detection does not run a process, connect to a port, or write a
   file.
3. Ask only when supported Ollama is detected and an initialized workspace is
   available. For a new workspace, wait until authorized `init` succeeds.
   Before asking, disclose the
   fixed endpoint, data scope, output path, evidence class, and residual risk.
4. Only after an affirmative answer, run `probe --authorized`. This contacts
   only `127.0.0.1:11434` and lists model candidates whose Ollama tag metadata
   passes bounded validation. It does not start Ollama or install/download a
   model.
5. If exactly one candidate exists, show its name and digest and configure it;
   configuration additionally requires Ollama-reported model information and
   completion capability from `/api/show`. If several candidates exist, ask
   the user to select one. If none exists, verification fails, or Ollama is
   unavailable, write nothing and keep the deterministic workflow enabled.
6. Configuration is workspace-scoped. `disable --authorized` stops future
   enrichment while preserving existing evidence sidecars.

The consent disclosure must say:

> Existing Ollama was detected. If enabled, Companion will contact the existing
> service only at 127.0.0.1:11434 and send bounded portable ontology metadata,
> not source bodies, comments, arbitrary strings, secrets, absolute paths, or
> private file hashes. It will not install or download a model or start the
> Ollama service. An authorized enrichment will execute the selected model,
> may allocate CPU/GPU memory, and will request immediate unload after the
> response with `keep_alive=0`. Valid normalized suggestions are stored as
> unvalidated `inferred` evidence under this workspace, never merged into the
> observed graph. Ollama's own network
> behavior is outside Companion's control. May I inspect existing local models
> and configure this workspace?

Declining, timing out, or an unavailable service is not an error for the core
ontology workflow. Do not repeatedly ask after a decline in the same workflow.

## Commands

Resolve `LOCAL_LLM` next to the bundled Companion script:

```bash
LOCAL_LLM="$SKILL_DIR/scripts/local_llm.py"

python3 "$LOCAL_LLM" detect
python3 "$LOCAL_LLM" probe --authorized
python3 "$LOCAL_LLM" configure \
  --workspace "/absolute/path/to/workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 "$LOCAL_LLM" status --workspace "/absolute/path/to/workspace"
python3 "$LOCAL_LLM" enrich \
  --workspace "/absolute/path/to/workspace" \
  --authorized
python3 "$LOCAL_LLM" disable \
  --workspace "/absolute/path/to/workspace" \
  --authorized
```

Once enabled, use `enrich` only during a relevant user-requested ontology
analysis and only after the deterministic snapshot is current. The saved
workspace consent permits future on-demand enrichment for that workspace, but
report each use. `init`, `sync`, `watch`, and all MCP tools never call the
helper implicitly.

## Fixed data and network boundary

The helper:

- supports only Ollama through the literal IPv4 loopback host
  `127.0.0.1` and port `11434`;
- rejects arbitrary URLs, DNS names, LAN/public addresses, proxy routing,
  redirects, API keys, reported remote/cloud markers, and missing or invalid
  Ollama-reported model metadata;
- considers at most 80 code-symbol candidates and 12 observed relations per
  candidate, then partitions them in stable order into requests containing at
  most 20 candidates and at most 16 KiB of serialized portable metadata;
- excludes source bodies, comments, arbitrary string literals, environment
  variables, credentials, absolute paths, source fingerprints, private source
  manifests, and raw file hashes;
- requests a non-streaming, temperature-zero JSON response with a strict
  schema, `think=false`, `num_ctx=8192`, `num_predict=2048`, a bounded response
  size, a maximum 180-second timeout per request, and `keep_alive=0` so Ollama
  is asked to unload the model immediately after each response;
- discards and counts unsupported role labels, conservatively merges duplicate
  identical-role suggestions, and omits conflicting-role nodes, while rejecting
  duplicate keys, non-finite numbers, unknown nodes, malformed JSON, and
  oversized output.

`localMetadataVerified=true` has a deliberately narrow meaning: the digest,
size, format, model information, completion capability, and remote-marker
fields reported by Ollama's `/api/tags` and `/api/show` responses passed these
checks. It does not verify the model weight bytes, authenticate the process
listening on loopback, prove that inference ran locally, or prove that Ollama
made no outbound request. A remote/cloud marker in `/api/chat` is also rejected,
but only after the disclosed candidate metadata has reached the service.

Loopback proves only where Companion sends the request. It cannot prove that a
separately managed Ollama process never communicates externally. Users who
require an air-gapped guarantee must enforce that at the operating-system and
Ollama configuration layers or leave enrichment disabled.

Inference is a real local compute action: Ollama may load model weights into
CPU or GPU memory and consume compute while answering. `keep_alive=0` asks for
immediate unload after the response, but Companion cannot attest Ollama's
resource release or override behavior outside the API contract.

## Evidence and retention

Configuration is stored as private `local-llm.json` in the selected workspace.
POSIX systems enforce mode `0600`; on Windows the file inherits the access
control list of the user-selected workspace. It contains the provider, fixed endpoint, selected model name and
digest, capability metadata, consent version, and data-scope version. It
contains no API key, executable path, arbitrary URL, or repository path.

Only after every batch succeeds and validates does a run atomically create one
private, create-only sidecar at the same platform-specific permission boundary:

```text
enrichments/<snapshot-id>/<run-id>.json
```

A failed, incomplete, or partial batch sequence leaves no sidecar.

The sidecar retains only normalized suggestions, model and schema provenance,
input/ontology digests, and exact false authority. Raw prompts and raw model
responses are not retained. It never modifies `ontology.json`, RDF, target
source, lineage evidence, or any downstream extension artifact. A
suggestion is `inferred`; its confidence does not make it observed, validated,
or approved.
