# オントロジーモデル

[English](../../../skills/manage-code-ontology/references/ontology-model.md) | [한국어](../../ko/references/ontology-model.md) | [日本語](ontology-model.md) | [简体中文](../../zh-CN/references/ontology-model.md)

exporter は RDF 1.1 Turtle と一般的な W3C vocabulary を使用します。namespace は次のとおりです。

`https://battle-doll.github.io/code-ontology-explorer/schema#`

## 主要なノードクラス

- `Package`, `Module`
- `Class`, `Interface`, `Enum`, `Record`
- `Function`, `AsyncFunction`, `Method`, `AsyncMethod`
- `FrameworkAnnotation`, `Decorator`
- `ExternalType`, `ExternalModule`, `ExternalCallable`
- `FrameworkConcept`, `PipelineRole`
- `PolicyLeaf`, `RuntimeBranch`

## 主要な関係

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

RDF predicate name は、たとえば `co:AnnotatedBy` のように UpperCamelCase 形式で生成されます。

## 移植性

`ontology.ttl` は Apache Jena、RDF4J、GraphDB、Stardog などの RDF 1.1 互換 store へ
読み込めます。これらの製品の load と configure は、このプラグインの v0.3.4 の対象外であり、
別の license、service、port、resource requirement が発生する場合があります。

イミュータブルな JSON snapshot は、同梱 tool の operational index です。Turtle は interchange
format です。移行時は stable node URN を維持し、移行先 ontology が異なる class または predicate を
使う場合に custom `co:` term をマッピングしてください。

既存 export との互換性を維持するため、Companion は意図的に Explorer 1.0 の `co:` namespace を
保持します。provenance は `lineage.ttl` へ別途エクスポートされ、W3C PROV-O と次を使用します。

`https://battle-doll.github.io/code-ontology-companion/provenance#`

observed、declared、inferred、validated、approved の evidence は区別されたままです。
[lineage-model.md](lineage-model.md)を参照してください。

## 静的解析の制限

edge は、analyzer が静的な構造シグナルを検出したことを意味します。`GUARDS_RUNTIME_BRANCH` edge は、
認識済み policy accessor の値または単純な local data-flow derivative が Java の control condition に
現れることを意味します。trace、runtime call graph、vulnerability verdict、分岐が実行された証明、
Spring proxy または bean が active である証明ではありません。
