# 变更日志

[English](../../CHANGELOG.md) | [한국어](../ko/CHANGELOG.md) | [日本語](../ja/CHANGELOG.md) | [简体中文](CHANGELOG.md)

## 0.5.1 - 2026-08-13

- 在官方 Skills-only manifest 中明确说明 rule-attributed relationship evidence
  和有界 Java/Python adapter coverage，使其与 canonical listing 保持一致。
- 将随附的 skill agent metadata 与无障碍默认 2D／可选 3D workbench 以及
  evidence／coverage workflow 对齐。
- 已发布的 v0.5.0 tag 和 artifact 保持不变。此 patch 仅更改 release
  metadata；analyzer semantics、ontology schema、visualization behavior、
  权限与 privacy 边界以及 vendored dependency 均未改变。

## 0.5.0 - 2026-08-13

- 添加可选的交互式 **3D 星座**视图，用于探索与现有 2D 视图相同的有界关系邻域。
  2D 仍是默认和永久 fallback；两种视图共享所选符号、本体 identity、关系
  evidence、详情、筛选条件与限制。
- 仅使用 `graph.html` 中已嵌入的确定性数据和浏览器内置 canvas API 在本地绘制
  3D projection。不会新增 CDN、package、WebGL、worker、telemetry 或 network
  要求，也不声称支持 graph database、SPARQL 或 runtime tracing。
- 支持 pointer orbit/zoom，以及通过 keyboard 进行 orbit、zoom、camera reset、
  node 遍历与选择和返回 root。遵循 reduced-motion 和
  forced-colors/high-contrast 偏好，向 assistive technology 提供状态和操作说明，
  页面隐藏时暂停绘制；canvas 不可用时安全回退到 keyboard-accessible 的 2D 视图。
- 可视化始终限制在所选关系邻域，不尝试一次绘制完整仓库图谱。

- 在每条生成关系的 `evidence` array 中记录稳定的 `rule_id`、定性 `basis`、
  `runtime_status`、可选的仓库相对 `path` 和 line span，以及有界的
  `limitations`。为兼容现有使用方，保留原有关系三元组以及 node/edge identity。
- 发布带版本的 `document.quality` contract 与有界的 Java/Python adapter
  coverage matrix，使快照、报告、查询、离线
  工作台和只读 MCP 结果能区分 supported、partial、heuristic 与
  runtime-unknown 区域；没有 parse warning 不再被视为 coverage 完整的证明。
- 保守地解析同一 owner method 的 Java call，以及通过已识别 import type 发出的
  显式 `Type.method` call；对有歧义的
  candidate 不创建关系。
- 添加可执行的 golden/forbidden ontology quality gate，检查预期和禁止的 node、
  relationship、evidence metadata、coverage 与确定性行为，同时不执行目标仓库。
- 保持基于 Python standard library 的 zero-dependency analyzer、稳定 RDF
  vocabulary、immutable snapshot、禁止执行 target code 与禁止 direct network
  的边界，以及独立且需同意的 inferred Ollama sidecar。

## 0.4.0 - 2026-08-10

- 将产品、策略、提交、架构、参考资料和多语言文档统一为当前支持的通用本体
  工作流，并移除旧的项目专用命令、实现、测试和评估案例。
- 添加使用说明：通过源代码级静态逆向工程，把已获授权的现有 Java/Spring 或
  Python 代码构建为不可变 JSON、RDF/Turtle、血缘和交互式离线本体，并进行更新与比较。
- 在官方 Skills 包中加入适用于 Windows、macOS 和 Linux 的可选只读本地 MCP
  配置指南与提示词；完整 GitHub 包继续提供相同版本的服务器和启动器。
- 在 Windows 上实际验证 Python 3.9 或更高版本，将 MCP stdio 固定为 UTF-8，
  并对快照、staging 和发布源目录中的链接及重解析点执行失败关闭处理。
- 让本地 Ollama 提示词的角色列表与规范 schema 保持一致，保留 `Validate` 角色和
  0.3.5 引入的有界确定性批处理。

## 0.3.5 - 2026-08-03

- 将可选的本地 Ollama 增强确定性地分批，每个请求最多包含 20 个候选项和
  16 KiB 序列化可移植元数据。
- 关闭模型思考，将每个请求的上下文限制为 8,192 个 token、每个响应的输出限制为
  2,048 个 token，并允许每个本地请求最长运行 180 秒，使有界增强能在受支持的
  本地硬件上完成。
- 仅在所有批次均通过验证后，才原子发布一个 inferred sidecar；失败、未完成或
  部分执行不会留下增强制品。仅关联允许的角色词汇并记录丢弃数量；同角色重复项
  采用较低置信度，角色冲突的节点会被排除。

## 0.3.4 - 2026-08-02

- 统一插件清单、技能说明、提交资料和多语言文档中的功能描述。
- 添加失败关闭的发布验证，检查归档结构、声明的能力和解压后的 smoke 测试。
- 明确记录本地只读 MCP、不可变快照、RDF、血缘和工作台的支持范围。

## 0.3.3 - 2026-08-02

- 发布完整的本地优先架构说明，同时保持版本 0.3.2 为未改变的功能基线。
- 为所有面向用户的产品、运营、安全、政策、提交和参考文档添加英语、韩语、日语和简体中文入口及译文。
- 保持英文许可证和政策文档为权威来源，将法律译文标注为仅供参考，并在源代码软件包中验证文档语言一致性。

## 0.3.2 - 2026-08-02

- 要求每项受跟踪的发布变更都获得新的语义化版本和注明日期的 `CHANGELOG.md` 条目，并提供感知基线的 CI 强制检查、同步元数据和确定性制品。
- 添加发布检查清单：根据最终源代码状态刷新插件已注册的自本体，并记录 declared 和 validated 血缘。
- 在 patch 版本之间保留兼容且已获同意的本地 LLM 工作区配置，同时拒绝畸形或来自未来版本的来源信息。

## 0.3.1 - 2026-08-01

- 提高确定性 Java 分析对泛型和 record 声明、多接口层次结构、嵌套导入、已验证 Spring 注解、同包通配符遮蔽、紧凑/泛型构造器检测、保守构造器注入和 `@Bean` 参数注入的准确性。
- 提高 Python 分析对相对与别名导入、内部调用、词法遮蔽、嵌套函数、显式 `self`/`cls` 调用、`src/` 布局、推导式作用域、有界 AST 深度/数量和基于 token 的管线角色分类的准确性。
- 添加失败关闭的源代码、图谱、影响分析和输出资源限制。
- 添加在明确同意后启用的、工作区级可选 Ollama 增强。它仅使用固定 IPv4 回环地址，拒绝报告的 cloud/remote 标记或缺失的必要元数据，发送有界的可移植元数据子集，以 `keep_alive=0` 请求立即卸载模型，并在不修改 observed 本体证据的情况下存储仅创建的 `inferred` sidecar。
- 强化 Git revision 元数据读取和有界 MCP 响应契约。
- 为发布归档添加精确、可复现的验证，包括解压后的 smoke 检查。
- 统一跨平台文本 checkout，并使 Windows 文件变更检查兼容 Python 3.12，同时保留文件身份、大小和 mtime 防护。

## 0.3.0 - 2026-07-31

- 用自包含的交互式本体工作台替换按 ID 排序的环形图：完整索引搜索、有界关系视角、引导式探索、易读详情，以及当前与上一快照的变化。
- 在本地内置并进行完整性固定的 Cytoscape.js 3.34.0 和 ELK.js 0.12.0，以在同一线程内布局，且不使用 CDN、安装步骤、遥测或网络访问。
- 保持核心 ontology/RDF 1.0 词汇表稳定，并保留静态证据边界：显示的关系不能证明运行时因果关系。

## 0.2.0 - 2026-07-31

- 增强 Java 策略访问器和静态控制流关系的提取，同时不保留任意字符串字面量。
- 强化图谱完整性、静态关系验证和已存在输出的失败关闭检查。

## 0.1.1 - 2026-07-30

- 在追加或读取前拒绝血缘日志的符号链接、重解析点、硬链接和文件交换竞态。
- 对快照清单复用基于描述符的有界源代码读取，使发现到读取期间的符号链接交换和超限增长以失败关闭方式处理。
- 在受保护读取之前、期间和之后验证文件身份与稳定元数据，包括不支持 `O_NOFOLLOW` 的平台。
- 添加针对符号链接目标、打开时交换、超限增长和原始字节清单哈希的回归覆盖。

## 0.1.0 - 2026-07-29

- 添加确定性 Java/Spring 和 Python 静态本体提取。
- 添加不可变快照、稳定刷新指纹、staging 验证、原子提升和最后已知良好状态恢复。
- 添加 RDF 1.1 Turtle 导出和兼容 PROV-O 的血缘。
- 添加结构查询、有界影响分析、快照历史和 diff 命令。
- 添加自包含离线图谱。
- 添加七个仅限已注册工作区、只读的本地 MCP 工具。
- 添加隐私、条款、安全、威胁模型、SBOM、审查者 eval 和确定性发布打包。
