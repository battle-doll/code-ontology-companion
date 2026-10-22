# 0.9.0 本地工作流程

[English](../../../skills/manage-code-ontology/references/v090-workflow.md) | [한국어](../../ko/references/v090-workflow.md) | [日本語](../../ja/references/v090-workflow.md) | [简体中文](v090-workflow.md) | [Русский](../../ru/references/v090-workflow.md)

保留 `v090-workflow.md` 文件名以兼容已有链接。未发布开发编号 0.9.0 对应 0.8.2；本指南描述当前 0.9.0 行为。

Code Ontology Companion 是将 Java/Spring、Python 源代码转换为本体的本地数据流水线，支持 Python 3.9+ 和 Windows、macOS、Linux。AI 通过本地 MCP 读取知识，人通过生成的离线 HTML 查看。开发者身份为 **battle-doll（배틀돌）**。保留所选模型与推理强度，不宣称特定模型的质量、令牌量或速度优势。

## 0.9.0 生成的人用 HTML

生成的离线 HTML 默认进入**聚焦模式**，同时提供独立的**全图模式**。聚焦第 1 级显示模块入口；在地图或列表中选择并进入某项后，仅显示该项声明的子项，最多 4 级。路径按钮可以返回父级。移动端与桌面端的每个聚焦地图页面均最多显示 **60 个节点和 160 条边**；其他项目与关系可通过明确分页和文本列表访问。这是显示上限，不是源码分析上限。既有全图与累积探索保留各自限制以及第 4 级及更深层级的确认操作。

聚焦模式只布局并动画显示选中的有界图，但仍解析全部嵌入数据并构造层级。这不表示对任意大型仓库提供完整惰性加载。减少动态效果设置会抑制进入动画，导航会取消过时的动画。地图保留静态源码证据，不证明运行时行为。本地 DOM、几何或单元测试不证明真实设备可用性或实测速度提升。继续支持本地 MCP、五种 UI/文档语言以及 Windows、macOS、Linux。

## 检查现行状态并恢复中断的工作

`ontology_status` 分别报告源码 `freshness` 和生成器 `generatorFreshness`（`current`、`stale`、`unknown`）。生成器指纹包含分析辅助程序和界面资源。源码可能已是最新，但 HTML 仍需重新生成。没有指纹的旧快照报告 `unknown`；`sync` 会创建当前格式的快照，不把缺失元数据当作最新状态的证据。

先完成快照文件和 SHA-256 产物 manifest，再使用已准备的运行记录追加血缘并原子替换当前指针。中断可能留下未完成记录或不一致的派生血缘导出。`doctor --workspace` 只读取完整性与恢复状态。`recover` 验证同一次运行的哈希和绑定，完成工作而不重复血缘事件，并修复派生 Turtle。哈希不符、状态冲突或多个未完成运行会阻止恢复。这不是覆盖所有文件的单一文件系统事务；Windows 报告 file-flush-only 持久性，而不是 POSIX 目录 fsync。

仅在获授权工作区的诊断发现中断时使用 `recover`；源码或生成器过期时再运行 `sync`。MCP 保持只读，不执行恢复或刷新。

```bash
python3 skills/manage-code-ontology/scripts/companion.py status --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py doctor --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py recover --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py sync --workspace "/path/outside/repo/ontology"
```

## 私有增量分析

macOS、Linux 使用源码仓库之外、仅所有者可访问的 `.parse-cache`。当源码与分析上下文一致时，复用经过认证的解析操作；缓存不是源码正文备份。系统从操作重新构建图谱并重新解析关系。范围、导入/类型上下文、分析器变化会使相关缓存失效。缓存命中不证明分析准确性。Windows 在具备私有缓存 DACL 配置功能之前不保存缓存，采用等价的全量分析，继续保持平台支持。

缓存、身份配置、运行记录和 `source-manifest.json` 应保持私有。`CODE_ONTOLOGY_PRIVACY_FILE` 检查已知身份和常见敏感模式，但不能识别所有未知真实姓名。使用 `--public` 构建公开候选包必须提供受保护的身份配置并通过隐私检查。不要上传私有工作区内部文件、真实姓名或个人邮箱。

## 向 AI 传递有界证据

保留原有 11 个只读工具，新增可选的第12个工具 `ontology_evidence_pack`。它对同一不可变快照执行 1–8 个具有唯一请求 ID 的搜索/邻域查询。快照与质量信息只传递一次，`n:`、`e:` 引用标识投影后的确切节点/证据表示。请使用返回的引用，不要假定一个节点 ID 可以代替所有表示。

```json
{
  "workspace_id": "registered-workspace-id",
  "requests": [
    {"id": "symbols", "operation": "search", "term": "OrderService", "limit": 20},
    {"id": "callers", "operation": "neighbors", "symbol": "OrderService", "direction": "incoming", "limit": 100}
  ],
  "node_fields": ["qualifiedName", "path", "metadata"],
  "max_results": 100,
  "max_payload_bytes": 65536,
  "max_wire_bytes": 150000
}
```

- `node_fields` 可选择 `qualifiedName`、`path`、`metadata`，默认全部保留，`[]` 省略这些可选字段。可用的身份字段仍保留，`omittedNodeFields` 明确列出省略项。
- `max_results` 限定 1–200 个返回行；`max_payload_bytes` 限定规范化 UTF-8 结构化 JSON 为 16384–262144 字节；`max_wire_bytes` 限定真实 JSON-RPC 响应为 16384–1048576 字节，包含请求 ID、为兼容性复制的文本及换行。`payloadBytes` 与 `wireBytes` 分别实测，不是令牌估算。
- 原样使用 `continuation.tool` 和 `continuation.arguments`。快照、选择条件与预算保持固定。搜索推进原查询 offset；邻域分页仅覆盖最初限定的遍历范围。末页的 `query_limit` 仍表示部分结果，不能证明图谱完整。
- `excludedReasons`、条目错误和字段省略均明确显示。一行与其路径证据一起纳入响应。如果一行也装不下，则返回调整预算的错误，而不是无法前进的游标。scope 描述原始查询，而非仅当前页。

## 人用 HTML 与 RDF 验证

在本地打开生成的 `graph.html`。可选择英语、韩语、日语、简体中文、俄语，并在地图与独立分页列表之间保留选择和筛选条件。变更视图显示之前/当前值，关系检查显示静态路径证据。空结果、缺失和截断仍保留其限制。离线 HTML 表示生成时的快照，不检查今天的源码或实际运行状况。

RDF 1.1 Turtle、`RelationshipEvidence` 和有限的 PROV-O 血缘继续导出同一个本体。开发/CI 可以使用 `requirements-validation.txt` 中固定版本的可选依赖，进行独立 RDF 解析、SHACL 和 JSON/Turtle 三元组精确一致性检查。插件运行时不需要这些依赖；依赖缺失表示无法验证，不视为通过。

```bash
python3 scripts/validate_rdf_contract.py --json "/path/ontology.json" --turtle "/path/ontology.ttl" --lineage "/path/lineage.ttl"
```

RDF 结构验证通过不代表源码分析准确、完整 PROV 合规或运行成功。保守 Java 分派以及 Python 定义时/动态行为仍保留部分支持边界。JS/TS 分析和跨模块解析仍不在本次发布支持的图谱分析范围内。

[本地 MCP 设置](local-mcp.md) · [隐私操作](../PRIVACY_OPERATIONS.md)
