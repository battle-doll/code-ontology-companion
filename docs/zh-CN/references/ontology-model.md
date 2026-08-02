# 本体模型

[English](../../../skills/manage-code-ontology/references/ontology-model.md) | [한국어](../../ko/references/ontology-model.md) | [日本語](../../ja/references/ontology-model.md) | [简体中文](ontology-model.md)

导出器使用 RDF 1.1 Turtle 和常见 W3C 词汇表。其命名空间为：

`https://battle-doll.github.io/code-ontology-explorer/schema#`

## 主要节点类别

- `Package`, `Module`
- `Class`, `Interface`, `Enum`, `Record`
- `Function`, `AsyncFunction`, `Method`, `AsyncMethod`
- `FrameworkAnnotation`, `Decorator`
- `ExternalType`, `ExternalModule`, `ExternalCallable`
- `FrameworkConcept`, `PipelineRole`
- `PolicyLeaf`, `RuntimeBranch`

## 主要关系

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

RDF predicate 名称以 UpperCamelCase 形式输出，例如 `co:AnnotatedBy`。

## 可移植性

`ontology.ttl` 可以加载到兼容 RDF 1.1 的存储中，例如 Apache Jena、RDF4J、GraphDB 或 Stardog。加载和配置这些产品超出本插件 v0.3.4 的范围，并可能引入独立许可证、服务、端口或资源要求。

不可变 JSON 快照是内置工具的操作索引。Turtle 是交换格式。迁移期间应保留稳定节点 URN；如果目标本体使用不同类别或 predicate，再映射自定义 `co:` term。

Companion 有意保留 Explorer 1.0 的 `co:` 命名空间，使现有导出保持兼容。来源信息在 `lineage.ttl` 中单独导出，使用 W3C PROV-O 加：

`https://battle-doll.github.io/code-ontology-companion/provenance#`

Observed、declared、inferred、validated 和 approved 证据保持区分。参见 [lineage-model.md](lineage-model.md)。

## 静态分析限制

一条边表示分析器发现了静态结构信号。`GUARDS_RUNTIME_BRANCH` 边表示已识别的策略访问器值或简单本地数据流衍生值出现在 Java 控制条件中。它不是 trace、运行时调用图、漏洞结论、分支已执行的证明，也不是 Spring proxy 或 bean 处于活动状态的证明。
