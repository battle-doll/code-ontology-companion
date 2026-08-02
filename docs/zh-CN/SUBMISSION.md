# 公开插件提交说明

[English](../../SUBMISSION.md) | [한국어](../ko/SUBMISSION.md) | [日本語](../ja/SUBMISSION.md) | [简体中文](SUBMISSION.md)

## 上架信息

- 名称：Code Ontology Companion
- 版本：0.3.3
- 开发者：battle-doll
- 类别：Developer Tools
- 分发：Public
- 公开 profile：Skills-only
- 本地/完整 profile：一个 skill 加一个内置本地只读 stdio MCP 服务器
- 许可证：Apache-2.0

简短描述：

> 带 RDF 血缘的本地代码图谱

详细描述：

> 通过静态分析，将已授权的 Java、Spring 或 Python 仓库映射为不可变的本地知识图谱快照。检查可能的变更影响、比较版本、保留证据血缘、导出 RDF 1.1 Turtle，并打开自包含的离线可视化。确定性分析不执行目标代码，也不发起网络请求。如果检测到现有 Ollama，用户可以另行授权仅限回环的有界推理；该推理保持未经验证，并与 observed 证据分离。任何组件都不会安装模型或启动 Ollama；经过授权的增强会运行选定模型，并请求在响应后立即卸载。

## 访问与数据使用声明

| 领域 | 版本 0.3.3 的行为 |
| --- | --- |
| 认证 | 无 |
| 直接网络访问 | 确定性分析器/工作区/MCP：无。明确同意后的可选辅助程序：仅固定 `127.0.0.1:11434` |
| 外部 API | 仅可选的现有本地 Ollama API；无远程或发布者 API |
| 遥测/analytics | 无 |
| 目标代码执行 | 无 |
| 读取 | 明确仓库路径下已授权的普通 `.java` 和 `.py` 文件；对于可选 runtime binding，一个明确的 JSON 或 `policy-json` 文档 |
| 排除项 | 疑似机密名称、key、env 文件、链接/重解析点、VCS、依赖项、构建输出、缓存、特殊和超限文件 |
| 写入 | 仓库之外新的明确工作区；不可变刷新快照和仅追加血缘；明确授权后，一个仅创建、模式 `0400` 的 runtime-binding 回执；另行取得本地 LLM 同意后，模式 `0600` 的工作区配置和仅创建 inferred sidecar |
| 私有本地状态 | 仓库绝对路径、每个文件的相对路径/大小/SHA-256、工作区/快照/事件 ID、可选 Git revision；启用时，本地模型名称/digest/capability 和规范化 inferred 建议 |
| 可移植制品 | 符号、关系、语言、限定名称、经验证的策略标识符、相对路径、计数、RDF/Turtle、血缘、离线 HTML |
| 不保留 | 源代码正文、注释、任意字符串字面量、策略值、凭据、原始提示词、原始模型响应 |
| 上传 | 无 |
| 后台服务 | 无；可选 watcher 明确且仅以前台方式运行 |
| MCP | 从公开 Skills-only 归档中省略。完整/本地 profile：stdio、只读、无端口、仅已注册工作区 ID |
| MCP 写入 | 无 |
| Hook/app/widget | 无 |
| 软件包/模型/数据库安装 | 无 |
| 是否要求本地 LLM | 否。仅在取得工作区级同意后使用可选的现有 Ollama；不安装/下载/启动 Ollama 服务。增强会执行选定模型并发送 `keep_alive=0` |

## 工具注解

全部七个 MCP 工具均设置：

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

这些工具用于列出工作区、读取状态、搜索、检查静态邻居、列出历史、比较快照和读取血缘。初始化、刷新、血缘写入、安装、删除、上传、目标执行和任意路径访问均不通过 MCP 公开。

可选 `runtime-binding` 命令仍仅限 CLI。其精确 false authority 禁止候选生成/gating、批准、提升、策略或运行时写入、订单提交、网络访问和资金转移。版本 0.3.3 仅在可以强制 owner 和模式 `0400` 语义的 macOS/POSIX 上创建精确回执；该命令在 Windows 上失败关闭。

## 审查理由

此版本无需云账户、远程服务、图数据库或模型即可提供独立的确定性价值。它要求：

1. 仓库授权；
2. 不写入的 preflight；
3. 仓库之外的明确工作区；
4. 初始化前的明确授权；
5. 创建仅创建 runtime-binding 回执前的明确授权；
6. 使用静态证据措辞，而非运行时或因果主张；
7. 在进行任何可选回环模型检查或工作区配置前，另行提供明确披露并取得同意。

分析器独立强制执行授权标志、输出分离、避免链接/重解析点/特殊文件、敏感路径排除、源代码大小限制、确定性路径不联网以及不执行目标代码。刷新使用稳定清单、staging、验证、不可变快照和原子提升。Runtime-binding 还会根据活动源代码重建图谱，将精确语义节点/边与冻结快照比较，拒绝仅测试或未使用路径和已知活动策略遮蔽，并发布规范的、自哈希/外部哈希、模式 `0400` 输出。`runtimeEffective=true` 仅表示不存在已知所提供策略遮蔽时的静态生产分支可达性。它不能证明执行、订单、安全性或利润因果关系。

可选本地增强不属于 observed 分析器权限。其指示器检查不执行任何内容，也不建立连接。同意后，辅助程序仅使用字面 IPv4 回环，拒绝报告的 cloud/remote 标记、缺失或无效的必要 API 元数据以及无界/畸形响应，不发送源代码正文/机密/绝对路径或私有哈希，并将规范化输出存储为仅创建的 `inferred` sidecar。Ollama 自身的网络行为仍是明确披露的剩余风险。

## 提交传输说明

完整/本地 profile 内置的 MCP transport 是本地 stdio，有意不提供公共 HTTPS 端点。如果当前公开提交门户要求每个含 MCP 的插件提供公共 MCP URL，请勿填写占位符或歪曲 transport。仅通过有文档说明的内置 stdio 路径提交，或创建单独审查且上架信息不宣称 MCP 的 skills-only 软件包。

当前门户的 **With MCP** 路径要求生产 HTTPS MCP URL、域名验证、当前工具扫描和演示录像。它不接受内置本地 stdio 服务器作为该 URL。因此，面向批准的公开 profile 为 **Skills only**；个人/本地分发保留内置 MCP 服务器。

使用以下命令构建门户安全归档：

```bash
python3 scripts/build_skills_only_release.py
```

生成的 ZIP 包含 manifest、skill、脚本、参考文档、许可证、notice 和图标。其生成的 manifest 省略 `mcpServers`，且归档按 Skills-only 上传要求省略 `.mcp.json` 和 `mcp/`。请勿在 skills-only 提交表单中用完整本地 ZIP 替换它。

## 评估用例

[evals/cases.json](../../evals/cases.json) 包含至少五个正向和三个负向审查用例，涵盖 preflight、初始化、Spring/Python 分析、版本比较、血缘、本地 LLM 同意/拒绝/缺失与畸形响应处理、MCP 读取边界、未经授权访问、机密外泄、静默安装和 MCP 写入。本地 LLM 用例使用有界模拟响应，不要求审查者基础设施。

## 法律与政策材料

- [LICENSE](../../LICENSE)
- [NOTICE](../../NOTICE)
- [PRIVACY.md](PRIVACY.md)
- [TERMS.md](TERMS.md)
- [SECURITY.md](SECURITY.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [SUPPORT.md](SUPPORT.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TRADEMARKS.md](TRADEMARKS.md)
- [SBOM.spdx.json](../../SBOM.spdx.json)

发布者必须亲自验证开发者身份、审查上架与可用性字段、提供门户要求的任何域名或凭据，并接受法律/政策声明。自动化代理不得代表发布者作出证明。
