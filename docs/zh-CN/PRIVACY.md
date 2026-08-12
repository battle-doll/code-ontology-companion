<!-- informational-translation; english-authoritative -->
# 隐私政策

[English](../../PRIVACY.md) | [한국어](../ko/PRIVACY.md) | [日本語](../ja/PRIVACY.md) | [简体中文](PRIVACY.md)

> 本译文仅为方便阅读而提供。如本译文与英文原文存在任何差异，以英文原文为准。

生效日期：2026 年 8 月 1 日

只有在用户指定已获授权的仓库并请求分析后，Code Ontology Companion 才会在本地处理受支持的源文件。

## 数据类别与目的

分析器可能读取普通 `.java` 和 `.py` 文件，以推导：

- 符号、注解、装饰器和限定名称；
- 已识别 Java 策略访问器使用的、经验证的点分策略标识符；
- 静态结构关系和语言标签；
- stable extraction rule ID、定性 evidence basis、runtime-status indicator、
  bounded limitation 与 adapter-coverage summary；
- 仓库相对路径、可选的 relationship-evidence line span、计数和解析警告。

它不会有意保留源代码正文、注释、任意字符串字面量、凭据、API key、环境变量、原始提示词或原始模型响应。点分策略标识符仅作为语义 `PolicyLeaf` 保留；其配置值和周围源代码文本不会存入本体。

为进行本地刷新和完整性验证，私有工作区会保留：

- 仓库绝对路径；
- 每个文件的相对路径、大小、语言标签和 SHA-256 值；
- 本地快照、工作区、事件以及可选 Git revision 标识符。

这些私有字段仅用于定位已授权仓库、检测变更、保护快照完整性和维护血缘。可移植 RDF、离线 HTML 和普通 MCP 结果会省略仓库绝对路径和完整文件指纹。Portable evidence 中的仓库相对 path 与 line span 仍可能透露机密 project structure。

如果用户为某个工作区明确启用可选本地 LLM 增强，私有本地状态还会保留：

- 固定回环 provider 和 endpoint、同意/数据范围版本，以及选定模型的名称、digest、format、size 和 completion capability；
- 引用现有本体节点 ID 的规范化模型建议、其建议的管线角色和置信度值；
- 标识确切 inferred 运行所需的快照、prompt-schema、输入和本体 digest。

这些建议标记为 `inferred`，不授予任何权限，并存储在独立的仅创建 sidecar 中。它们不会合并到 observed 本体、RDF、血缘或 MCP 数据中。不存储原始提示词或原始响应。

会排除疑似机密的文件名、私钥和 keystore 扩展名、符号链接/重解析点、常见 VCS/依赖/构建/缓存/虚拟环境目录、特殊文件以及超过配置限制的文件。

## 本地存储、保留与删除

`doctor` 和 `preflight` 不创建文件。在明确确认后，初始化会在目标仓库之外写入一个包含不可变初始快照的本地工作区。刷新会创建新的不可变快照并保留旧快照；血缘记录追加到本地日志。

发布者不会收到这些制品的副本。它们会一直保留，直到用户使用普通本地文件管理工具删除所选工作区，并可选择删除本地 Companion registry 中的相应条目。版本 0.5.1 不提供自动保留或云备份。

## 网络、接收方与第三方

确定性分析器、工作区 CLI、工作台、启动器和 MCP 服务器：

- 不发起网络请求；
- 不收集遥测、analytics、cookie、广告标识符或 IP 日志；
- 不调用外部 API，也不向发布者发送源代码或本体数据；
- 不安装软件包、模型、数据库、守护进程或后台 watcher；
- 不开放监听网络端口。

可选 `local_llm.py` 辅助程序属于独立边界。检测时不运行进程、不建立连接、不写入文件。只有在用户查看数据披露并明确同意后，该辅助程序才可以：

- 连接到字面 IPv4 回环端点 `127.0.0.1:11434`；
- 检查现有 Ollama 模型元数据，并拒绝报告 remote/cloud 标记或省略必要元数据的响应；
- 最多发送一个有界、可移植的子集，其中包含符号名称、限定名称、仓库相对路径、节点类型和 observed 关系元数据；
- 接收有界 JSON completion，并且只保留规范化 inferred 输出。

它不会发送源代码正文、注释、任意字符串、机密、凭据、绝对路径、私有清单、源指纹或原始文件哈希。它不接受任意 URL、LAN/公网 host、proxy、redirect 或 API key，并且绝不安装或下载模型，也不启动 Ollama 服务。经过授权的增强会执行选定模型，可能分配 CPU/GPU 内存，并发送 `keep_alive=0` 请求在响应后立即卸载。呈现为 Ollama 的回环服务及其选定模型是由用户管理的第三方接收方。Companion 无法认证该服务，也无法保证或控制其外部网络行为或保留方式；用户必须审查并约束其 Ollama 环境，或保持增强禁用。

`localMetadataVerified=true` 只记录 Ollama 的 `/api/tags` 和 `/api/show` 响应所报告字段通过了有界验证。它不能证明模型权重字节、认证回环服务、证明推理在本地运行，或证明 Ollama 未建立出站连接。chat 响应中的 remote 标记会被拒绝，但该响应是在已披露元数据已经发送到服务之后才到达。

只读 MCP 服务器通过 stdio 与本地 Codex 宿主通信，并且只接受已注册工作区 ID。它提供工作区列表、状态、搜索、邻居、历史、快照比较和血缘查询，且无法初始化、刷新、记录、删除或上传工作区。

当 Codex 调用 skill 或 MCP 工具时，为提供所请求的功能，OpenAI 可能处理选定的命令或工具输出，例如符号、限定名称、计数、警告、快照 ID 和相对路径。OpenAI 是独立接收方，受其[适用条款](https://openai.com/policies/terms-of-use/)和[隐私政策](https://openai.com/policies/privacy-policy/)约束。操作系统和 Codex 宿主受其提供商条款约束。

## 用户控制

用户可以：

- 查看只读 preflight 后，在初始化前停止；
- 选择本地工作区位置；
- 拒绝安装运行时或外部传输；
- 拒绝可选本地 LLM 检查，同时不失去核心功能；
- 检查或禁用每工作区的本地 LLM 配置，同时保留或手动删除先前 inferred sidecar；
- 检查 JSON、Turtle、Markdown 和 HTML 制品；
- 随时停止前台监视；
- 删除本地工作区和 registry 数据；
- 将导出保留在本地，或另行授权共享。

## 联系方式

隐私问题：

https://github.com/battle-doll/code-ontology-companion/issues
