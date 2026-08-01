# Ontology model

The exporter uses RDF 1.1 Turtle and common W3C vocabularies. Its namespace is:

`https://battle-doll.github.io/code-ontology-explorer/schema#`

## Main node classes

- `Package`, `Module`
- `Class`, `Interface`, `Enum`, `Record`
- `Function`, `AsyncFunction`, `Method`, `AsyncMethod`
- `FrameworkAnnotation`, `Decorator`
- `ExternalType`, `ExternalModule`, `ExternalCallable`
- `FrameworkConcept`, `PipelineRole`
- `PolicyLeaf`, `RuntimeBranch`

## Main relationships

- `DECLARES`
- `IMPORTS`
- `EXTENDS`, `IMPLEMENTS`
- `ANNOTATED_BY`, `DECORATED_BY`
- `INJECTS`, `DECLARES_BEAN`
- `MANAGED_AS`, `MAY_BE_PROXIED_BY`
- `CALLS`
- `HAS_PIPELINE_ROLE`
- `READS_POLICY_LEAF`
- `DECLARES_RUNTIME_BRANCH`
- `GUARDS_RUNTIME_BRANCH`

RDF predicate names are emitted in UpperCamelCase form, for example `co:AnnotatedBy`.

## Portability

`ontology.ttl` can be loaded into RDF 1.1-compatible stores such as Apache Jena, RDF4J, GraphDB, or Stardog. Loading and configuring those products is outside this plugin's v0.3.1 scope and may introduce separate licenses, services, ports, or resource requirements.

The immutable JSON snapshot is the bundled tool's operational index. Turtle is
the interchange format. Preserve stable node URNs during migration, then map
custom `co:` terms if the destination ontology uses different classes or
predicates.

Companion deliberately retains the Explorer 1.0 `co:` namespace so existing
exports remain compatible. Provenance is exported separately in
`lineage.ttl`, using W3C PROV-O plus:

`https://battle-doll.github.io/code-ontology-companion/provenance#`

Observed, declared, inferred, validated, and approved evidence remain distinct.
See [lineage-model.md](lineage-model.md).

## Static-analysis limits

An edge means the analyzer found a static structural signal. A
`GUARDS_RUNTIME_BRANCH` edge means a recognized policy accessor value or a
simple local data-flow derivative appears in a Java control condition. It is
not a trace, runtime call graph, vulnerability verdict, proof that the branch
executed, or proof that a Spring proxy or bean is active.
