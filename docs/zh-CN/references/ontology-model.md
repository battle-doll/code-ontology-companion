# 本体模型

[English](../../../skills/manage-code-ontology/references/ontology-model.md) | [한국어](../../ko/references/ontology-model.md) | [日本語](../../ja/references/ontology-model.md) | [简体中文](ontology-model.md) | [Русский](../../ru/references/ontology-model.md)

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

## 关系 evidence 与 quality contract

版本 0.8.3 保留原有 direct triple 和稳定 node/edge identity。每个 JSON edge 的附加 `evidence` array 条目具有稳定 `rule_id`、定性 `basis`（`direct_syntax`、`resolved_static`、`framework_semantic`、`name_heuristic`）和 `runtime_status`（`not_applicable`、`runtime_unknown`）。Source-derived 条目可包含仓库相对 `path`、`line_start`、`line_end`，有界 `limitations` 用于说明重要不确定性。

`document.quality` contract version `1.0` 报告关系 evidence 的 total/documented/missing/percentage、basis/runtime-status count，以及 Java/Python adapter `status`、`capabilities`、`unsupported_runtime`。RDF 保留 direct triple，并添加表示相同 attribution 的 `RelationshipEvidence` resource。定性 basis 不是 probability，`runtime_unknown` 也不是 runtime proof。

## 可移植性

`ontology.ttl` 可以加载到兼容 RDF 1.1 的存储中，例如 Apache Jena、RDF4J、GraphDB 或 Stardog。加载和配置这些产品超出本插件 v0.8.3 的范围，并可能引入独立许可证、服务、端口或资源要求。

不可变 JSON 快照是内置工具的操作索引。Turtle 是交换格式。迁移期间应保留稳定节点 URN；如果目标本体使用不同类别或 predicate，再映射自定义 `co:` term。

Companion 有意保留 Explorer 1.0 的 `co:` 命名空间，使现有导出保持兼容。来源信息在 `lineage.ttl` 中单独导出，使用 W3C PROV-O 加：

`https://battle-doll.github.io/code-ontology-companion/provenance#`

Observed、declared、inferred、validated 和 approved 证据保持区分。参见 [lineage-model.md](lineage-model.md)。

## 静态分析限制

一条边表示分析器发现了静态结构信号。`GUARDS_RUNTIME_BRANCH` 边表示已识别的策略访问器值或简单本地数据流衍生值出现在 Java 控制条件中。它不是 trace、运行时调用图、漏洞结论、分支已执行的证明，也不是 Spring proxy 或 bean 处于活动状态的证明。


## 0.8.3 读取、交换和谱系范围

本地stdio MCP读取不可变 `ontology.json` snapshot及workspace `lineage.jsonl`，返回固定snapshot的有界结构化证据。人用的 `graph.html` 也内嵌同一JSON的portable projection。`ontology.ttl` 是并行RDF 1.1 Turtle代码图/`RelationshipEvidence` 输出；仅声明PROV prefix不产生谱系triple。单独workspace `lineage.ttl` 导出谱系指南中的PROV-O子集：记录为Entity，校对的snapshot build具备源码/snapshot生成关系；不提供人员Agent归属、完整谱系链或合规认证。

证据附着率、部分adapter metadata和 `runtime_unknown` 是诊断边界，不证明准确或执行。部分诊断不会自动阻止snapshot确认；质量回归属于独立release检查。已配置HMAC-SHA256拒绝不安全的支持输出，可选身份配置检测范围有限。当前代码输入MVP不等于任意数据摄入或完整AI数据平台。

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
