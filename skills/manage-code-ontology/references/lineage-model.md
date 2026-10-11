# Lineage model

[English](lineage-model.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/references/lineage-model.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/references/lineage-model.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/references/lineage-model.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/references/lineage-model.md)

The private append-only `lineage.jsonl` journal distinguishes recorded changes from inferences. `lineage.ttl` is a separate interchange export of an evidence-bounded PROV-O subset. A journal record is an information entity, not the activity it describes.

## Evidence classes

- `observed`: deterministically extracted from source or workspace state.
- `declared`: stated by a user or supplied decision record.
- `inferred`: proposed by an analyzer or model and not independently confirmed.
- `validated`: supported by a named test, review, replay, or other reproducible check.
- `approved`: explicitly authorized by the responsible person or governance process.

Never rewrite `inferred` as `validated` based only on confidence or repetition.
Optional local LLM suggestions are stored in private enrichment sidecars rather
than this lineage journal. They remain `inferred` until a separate reproducible
validation or responsible-person approval is explicitly recorded; the model's
confidence value is provenance, not validation.

## Core event sequence

```text
Decision
  -> Change
  -> Validation
  -> Activation
  -> Observation
  -> Outcome
  -> Retained / Rollback / Superseded
```

Code, deployment, activation, and outcome are separate events. A commit does
not prove deployment; deployment does not prove runtime activation; an outcome
near a change does not prove that the change caused it.

## Time semantics

The current release records transaction time: when Companion stored the event.
If a fact became effective earlier, put that date in the human-readable summary.
Do not overwrite old events to simulate a corrected effective date; append a
correcting event.

## Portable identifiers

- Workspace IDs and event IDs are random local UUIDs.
- Snapshot IDs combine UTC time with a source fingerprint prefix.
- Code entity IDs retain the Explorer 1.0 vocabulary for RDF compatibility.
- Absolute repository paths and full source fingerprints stay in private local
  configuration or manifests; normal RDF, HTML, and MCP responses do not expose
  them.


## 0.9.0 PROV-O subset and privacy boundary

A journal record keeps its existing event URI and is typed `coc:LineageRecord`, `prov:Entity`. Its transaction time is `coc:recordedAt`: a valid timezone-aware ISO value becomes `xsd:dateTime`; an invalid or naive legacy value remains a plain literal. It does not invent activity start/end times.

Only a stored `observed` snapshot-promotion record corroborated against regular `snapshot.json` and `source-manifest.json` files adds a separate `coc:SnapshotBuild` / `prov:Activity`, `coc:OntologySnapshot` / `prov:Entity`, and `coc:ScopedSource` / `prov:Entity`. Checks include run ID, workspace/snapshot IDs, trigger, creation time, revision, source roots and recomputed aggregate SHA-256. `coc:describesBuild` links the record to the build; `prov:used` links build to scoped source; `prov:wasGeneratedBy` links snapshot to build; `prov:wasDerivedFrom` links snapshot to scoped source. Snapshot `prov:generatedAtTime` comes from corroborated metadata. An earlier corroborated promotion can add only custom `coc:previousSnapshot`; predecessor does not imply PROV derivation from the previous snapshot.

Without corroboration, the journal record remains and generation relations are omitted. These checks use stored local evidence, not a fresh source scan or cryptographic journal authentication. No `prov:Agent`/Person, human attribution, guessed runtime time, complete provenance or certified PROV conformance is claimed. MCP reads the JSON/JSONL journal contract; Turtle stays an interchange export. Per-file hashes remain in the private manifest; the scoped aggregate may also remain in private snapshot JSON metadata, while normal RDF/HTML/MCP hide full fingerprints and absolute repository roots.

Configured HMAC-SHA256 checks inspect raw new events, the existing journal and prepared Turtle before appending or replacing either output. Private material is rejected as a whole, never silently skipped. Relative paths are appropriate for records. This privacy precheck does not promise a two-file transaction for arbitrary I/O failures; a missing optional profile does not detect every personal name.

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
