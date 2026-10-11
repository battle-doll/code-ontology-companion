# 血缘模型

[English](../../../skills/manage-code-ontology/references/lineage-model.md) | [한국어](../../ko/references/lineage-model.md) | [日本語](../../ja/references/lineage-model.md) | [简体中文](lineage-model.md) | [Русский](../../ru/references/lineage-model.md)

私有仅追加 `lineage.jsonl` journal区分已记录变更和推断。`lineage.ttl` 是基于证据限定的PROV-O子集的单独交换输出。记录是信息实体，不是所描述的活动本身。

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


## 0.9.0 PROV-O子集及隐私边界

既有event URI的记录类型为 `coc:LineageRecord`, `prov:Entity`。记录时间使用 `coc:recordedAt`：有效带timezone的ISO值转为 `xsd:dateTime`，无效或不带timezone的旧值仍为plain literal；不推测活动开始/结束时间。

只有存储的 `observed` 快照确认记录与普通文件 `snapshot.json`、`source-manifest.json` 相符，才增加独立的 `coc:SnapshotBuild` / `prov:Activity`, `coc:OntologySnapshot` / `prov:Entity`, `coc:ScopedSource` / `prov:Entity`。校对run ID、workspace/snapshot ID、trigger、生成时间、revision、源码范围及重算综合SHA-256。记录→build用 `coc:describesBuild`，build→选定源码用 `prov:used`，snapshot→build用 `prov:wasGeneratedBy`，snapshot→源码用 `prov:wasDerivedFrom`。snapshot的 `prov:generatedAtTime` 来自相符metadata。仅对更早已校对的确认记录增加自定义 `coc:previousSnapshot`，不推测从前一snapshot派生的PROV关系。

条件不足时保留记录但省略生成关系。这是校对存储的本地证据，不重新观察当前源码或对journal作密码认证。不声称 `prov:Agent`/Person、人员归属、推測执行时间、完整谱系或PROV合规认证。MCP读取JSON/JSONL journal契约，Turtle用于交换。每文件hash留在私有manifest，综合指纹也可留在私有snapshot JSON metadata；常规RDF/HTML/MCP隐藏完整指纹和绝对repo根路径。

已配置HMAC-SHA256在追加/替换前检查新raw event、既有journal及准备的Turtle；私有材料整体拒绝，不静默遗漏。记录建议用相对路径。任意I/O失败下不保证两文件单一事务；缺少可选配置不检测所有实名。

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
