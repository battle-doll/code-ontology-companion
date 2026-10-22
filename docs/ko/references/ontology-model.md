# 온톨로지 모델

[English](../../../skills/manage-code-ontology/references/ontology-model.md) | [한국어](ontology-model.md) | [日本語](../../ja/references/ontology-model.md) | [简体中文](../../zh-CN/references/ontology-model.md) | [Русский](../../ru/references/ontology-model.md)

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

## 관계 evidence와 quality contract

버전 0.8.3는 기존 direct triple과 안정적인 node/edge identity를 보존합니다. 각 JSON edge의 추가 `evidence` array 항목은 안정적인 `rule_id`, 정성적 `basis`(`direct_syntax`, `resolved_static`, `framework_semantic`, `name_heuristic`), `runtime_status`(`not_applicable`, `runtime_unknown`)를 가집니다. Source-derived 항목에는 저장소 상대 `path`, `line_start`, `line_end`가 들어갈 수 있고, 제한된 `limitations`가 중요한 불확실성을 설명합니다.

`document.quality` contract version `1.0`은 relation evidence total/documented/missing/percentage, basis/runtime-status count, Java/Python adapter `status`, `capabilities`, `unsupported_runtime`을 보고합니다. RDF는 direct triple을 유지하고 같은 attribution을 위한 `RelationshipEvidence` resource를 추가합니다. 정성적 basis는 probability가 아니며 `runtime_unknown`은 runtime proof가 아닙니다.

## 이식성

`ontology.ttl`은 Apache Jena, RDF4J, GraphDB 또는 Stardog 같은 RDF 1.1-compatible store로 load할 수 있습니다. 이러한 제품의 loading과 configuration은 이 plugin의 v0.8.3 범위 밖에 있으며 별도 license, service, port 또는 resource requirement가 생길 수 있습니다.

immutable JSON snapshot은 bundled tool의 operational index입니다. Turtle은 interchange format입니다. migration 중 stable node URN을 보존한 다음 destination ontology가 다른 class 또는 predicate를 사용한다면 custom `co:` term을 mapping합니다.

Companion은 기존 export의 호환성을 유지하기 위해 Explorer 1.0 `co:` namespace를 의도적으로 보존합니다. Provenance는 W3C PROV-O와 다음 namespace를 사용하여 `lineage.ttl`로 별도 export됩니다.

`https://battle-doll.github.io/code-ontology-companion/provenance#`

Observed, declared, inferred, validated, approved evidence는 구분된 상태로 유지됩니다. [lineage-model.md](lineage-model.md)를 참고하십시오.

## 정적 분석 한계

edge는 analyzer가 static structural signal을 찾았다는 뜻입니다. `GUARDS_RUNTIME_BRANCH` edge는 인식된 policy accessor value 또는 단순한 local data-flow derivative가 Java control condition에 나타남을 뜻합니다. trace, runtime call graph, vulnerability verdict, branch가 실행되었다는 증명, Spring proxy 또는 bean이 활성 상태라는 증명이 아닙니다.


## 0.8.3 읽기·교환·계보 지원 범위

로컬 stdio MCP는 불변 `ontology.json` 스냅샷과 작업공간의 `lineage.jsonl`을 읽고, snapshot을 고정한 범위 제한 구조화 근거를 반환합니다. 사람용 `graph.html`도 같은 JSON의 이식 가능한 projection을 내장합니다. `ontology.ttl`은 병렬 RDF 1.1 Turtle 코드 그래프/`RelationshipEvidence` 출력이며 PROV prefix 선언만으로 계보 triple을 생성하지 않습니다. 별도의 작업공간 `lineage.ttl`은 계보 가이드의 PROV-O 부분집합을 사용합니다. 기록은 엔터티로, 대조된 snapshot build는 소스·스냅샷 생성 관계로 표현하며 인간 Agent 귀속·완전한 계보 체인·준수 인증을 제공하지 않습니다.

근거 첨부율·부분 어댑터 metadata·`runtime_unknown`은 진단 경계이며 실행이나 정확도 증명이 아닙니다. 부분 분석만으로 snapshot 확정을 막지 않으며 온톨로지 품질 회귀는 별도 릴리스 검사입니다. 설정된 HMAC-SHA256 개인정보 검사는 위험한 지원 출력을 거부하고 선택적 신원 프로필의 검출 범위는 제한됩니다. 구현된 코드 입력 MVP를 임의 데이터 수집이나 완성된 AI 데이터 플랫폼으로 주장하지 않습니다.

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
