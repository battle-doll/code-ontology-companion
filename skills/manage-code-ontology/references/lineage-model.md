# Lineage model

Use lineage to distinguish what changed from what was merely inferred about the
change. The local journal is append-only. `lineage.ttl` exports events using
PROV-O-compatible activities plus Companion evidence classes.

## Evidence classes

- `observed`: deterministically extracted from source or workspace state.
- `declared`: stated by a user or supplied decision record.
- `inferred`: proposed by an analyzer or model and not independently confirmed.
- `validated`: supported by a named test, review, replay, or other reproducible check.
- `approved`: explicitly authorized by the responsible person or governance process.

Never rewrite `inferred` as `validated` based only on confidence or repetition.

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
If a fact became effective earlier, put that date in the human-readable summary
until a future schema adds a separate valid-time property. Do not overwrite old
events to simulate a corrected effective date; append a correcting event.

## Portable identifiers

- Workspace IDs and event IDs are random local UUIDs.
- Snapshot IDs combine UTC time with a source fingerprint prefix.
- Code entity IDs retain the Explorer 1.0 vocabulary for RDF compatibility.
- Absolute repository paths and full source fingerprints stay in private local
  configuration or manifests; normal RDF, HTML, and MCP responses do not expose
  them.
