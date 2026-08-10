# 血缘模型

[English](../../../skills/manage-code-ontology/references/lineage-model.md) | [한국어](../../ko/references/lineage-model.md) | [日本語](../../ja/references/lineage-model.md) | [简体中文](lineage-model.md)

使用血缘来区分实际发生的变化和仅针对该变化作出的推断。本地日志仅追加。`lineage.ttl` 使用兼容 PROV-O 的 activity 加 Companion 证据类来导出事件。

## 证据类别

- `observed`：从源代码或工作区状态确定性提取。
- `declared`：由用户陈述或由所提供的决策记录声明。
- `inferred`：由分析器或模型提出，未经独立确认。
- `validated`：得到具名测试、审查、replay 或其他可复现检查支持。
- `approved`：由责任人或治理流程明确授权。

绝不能仅凭置信度或重复出现把 `inferred` 改写为 `validated`。可选本地 LLM 建议存储在私有增强 sidecar 中，而不是此血缘日志中。在明确记录独立的可复现验证或责任人批准之前，它们始终为 `inferred`；模型置信度值属于来源信息，不是验证。

## 核心事件序列

```text
决策
  -> 变更
  -> 验证
  -> 激活
  -> 观察
  -> 结果
  -> 保留 / 回滚 / 被取代
```

代码、部署、激活和结果是不同事件。commit 不能证明部署；部署不能证明运行时激活；与变更时间接近的结果不能证明该变更导致了结果。

## 时间语义

当前版本记录事务时间，即 Companion 存储事件的时间。如果事实更早生效，请在易读摘要中写入该日期。不要覆盖旧事件来模拟修正后的生效日期；应追加一条纠正事件。

## 可移植标识符

- 工作区 ID 和事件 ID 是随机本地 UUID。
- 快照 ID 由 UTC 时间和源指纹前缀组成。
- 代码实体 ID 保留 Explorer 1.0 词汇表以兼容 RDF。
- 仓库绝对路径和完整源指纹保留在私有本地配置或清单中；普通 RDF、HTML 和 MCP 响应不会公开它们。
