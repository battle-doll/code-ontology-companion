# 온톨로지 모델

[English](../../../skills/manage-code-ontology/references/ontology-model.md) | [한국어](ontology-model.md) | [日本語](../../ja/references/ontology-model.md) | [简体中文](../../zh-CN/references/ontology-model.md)

exporter는 RDF 1.1 Turtle과 일반적인 W3C vocabulary를 사용합니다. namespace는 다음과 같습니다.

`https://battle-doll.github.io/code-ontology-explorer/schema#`

## 주요 node class

- `Package`, `Module`
- `Class`, `Interface`, `Enum`, `Record`
- `Function`, `AsyncFunction`, `Method`, `AsyncMethod`
- `FrameworkAnnotation`, `Decorator`
- `ExternalType`, `ExternalModule`, `ExternalCallable`
- `FrameworkConcept`, `PipelineRole`
- `PolicyLeaf`, `RuntimeBranch`

## 주요 relationship

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

RDF predicate name은 예를 들어 `co:AnnotatedBy`처럼 UpperCamelCase 형식으로 방출됩니다.

## 이식성

`ontology.ttl`은 Apache Jena, RDF4J, GraphDB 또는 Stardog 같은 RDF 1.1-compatible store로 load할 수 있습니다. 이러한 제품의 loading과 configuration은 이 plugin의 v0.3.4 범위 밖에 있으며 별도 license, service, port 또는 resource requirement가 생길 수 있습니다.

immutable JSON snapshot은 bundled tool의 operational index입니다. Turtle은 interchange format입니다. migration 중 stable node URN을 보존한 다음 destination ontology가 다른 class 또는 predicate를 사용한다면 custom `co:` term을 mapping합니다.

Companion은 기존 export의 호환성을 유지하기 위해 Explorer 1.0 `co:` namespace를 의도적으로 보존합니다. Provenance는 W3C PROV-O와 다음 namespace를 사용하여 `lineage.ttl`로 별도 export됩니다.

`https://battle-doll.github.io/code-ontology-companion/provenance#`

Observed, declared, inferred, validated, approved evidence는 구분된 상태로 유지됩니다. [lineage-model.md](lineage-model.md)를 참고하십시오.

## 정적 분석 한계

edge는 analyzer가 static structural signal을 찾았다는 뜻입니다. `GUARDS_RUNTIME_BRANCH` edge는 인식된 policy accessor value 또는 단순한 local data-flow derivative가 Java control condition에 나타남을 뜻합니다. trace, runtime call graph, vulnerability verdict, branch가 실행되었다는 증명, Spring proxy 또는 bean이 활성 상태라는 증명이 아닙니다.
