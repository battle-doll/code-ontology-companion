# 数据边界

[English](../../../skills/manage-code-ontology/references/data-boundaries.md) | [한국어](../../ko/references/data-boundaries.md) | [日本語](../../ja/references/data-boundaries.md) | [简体中文](data-boundaries.md)

## 已授权输入

只分析用户拥有、管理或明确获准检查的本地仓库。由他人提供的路径不能证明已获授权。

## 读取的数据

版本 0.5.2 分析器读取不超过 2 MiB 的普通 `.java` 和 `.py` 文件，并对聚合文件数量和字节数实施失败关闭限制。它不跟随符号链接或 Windows 重解析点，并跳过常见依赖、VCS、生成输出、IDE、虚拟环境和缓存目录。

即使文件使用受支持的扩展名，只要其名称暗示凭据、机密、token、私钥、keystore 或 `.env` 配置，也会被排除。

## 保留的数据

可移植本体制品可能保留：

- 符号和注解名称；
- 语言以及节点/关系类型；
- 限定名称；
- 已识别 Java 策略访问器使用的、经验证的点分策略标识符；
- 仓库相对源代码路径和可选的 relationship-evidence line span；
- stable extraction rule ID、定性 evidence basis、runtime-status indicator、
  bounded limitation 与 adapter-coverage summary；
- 聚合计数和解析警告。

私有本地工作区文件还会保留：

- 刷新所需的仓库绝对路径；
- 用于检测变化的每文件字节数和 SHA-256 值；
- 快照、事件和工作区标识符；
- 直接从普通 `.git` 元数据读取的可选本地 Git revision。

可移植 RDF、离线 HTML 和普通 MCP 响应不会有意公开仓库绝对路径或完整文件指纹。

离线 HTML 嵌入完整的可移植节点/边索引用于本地搜索，但画布中只实例化有界子图。它还嵌入经过完整性固定的 Cytoscape.js 和 ELK.js 字节；Content Security Policy 禁用连接和浏览器 worker。

Observed 本体制品有意不保留下列任何内容：

- 源代码正文、任意字符串字面量或注释；
- 文件内容；
- 环境变量、凭据、API key 或 token；
- 提示词或模型输出。

如果明确启用可选本地 LLM 增强，一个独立的私有配置会保留固定回环 provider/endpoint、同意/数据范围版本和经验证的模型名称/digest/capability。POSIX 使用模式 `0600`；Windows 使用用户所选工作区继承的 ACL。每次成功增强都会创建一个私有 sidecar，保留规范化建议角色与置信度、快照/模型/schema 来源以及有界输入/本体 digest。不保留原始提示词和原始响应。Sidecar 是 `inferred` 证据，绝不合并到 observed 本体、RDF、血缘或 MCP 数据中。

标识符和相对路径仍可能属于机密信息。默认将制品保留在本地，并在共享前另行取得授权。

## 写入

Doctor 和 preflight 不写入任何内容。初始化会创建一个明确的新工作区，它既不在目标仓库内，也不是目标仓库的父目录。刷新构建完整 staging 快照、进行验证、以原子方式提升新的不可变快照，同时保留最后一个已知良好版本。决策和验证记录追加到本地血缘日志。

## 网络与执行

内置分析器不发起直接网络请求，也不导入、编译、构建、测试或执行目标代码。它不安装软件包、模型、数据库、守护进程或永久 watcher。

启用插件后，Codex 可以启动内置的只读 stdio MCP 进程。它不开放监听端口、不接受任意文件系统路径，并且只查询已由明确授权初始化工作流注册的工作区。

取得工作区级肯定同意后，独立的可选辅助程序只能联系字面 IPv4 回环 `127.0.0.1:11434` 上的现有 Ollama 服务。它不接受 endpoint 输入、proxy、redirect、API key 或 LAN/公网地址，并拒绝报告的 cloud/remote 标记或缺失的必要模型元数据。有界 payload 可以包含节点 ID、符号/类型/注解名称、限定名称、仓库相对路径和 observed 关系元数据。它排除源代码正文、注释、任意字符串、机密、绝对路径、私有清单、源指纹和原始文件哈希。辅助程序绝不安装或下载模型，也不启动 Ollama 服务。经过授权的增强确实会执行选定模型，可能分配 CPU/GPU 内存，并发送 `keep_alive=0` 请求在响应后立即卸载。Ollama 自身的网络、资源行为和保留不在 Companion 控制范围内。

Codex 可能处理分析器命令输出以提供所请求的工作流。该平台处理受 OpenAI 的适用条款和隐私政策约束。版本 0.5.2 不调用远程数据服务，也不上传生成的制品。

## 解释

图谱是 Java/Spring 和 Python 源代码的静态证据。反射、运行时 bean 条件、生成代理、外部配置、动态导入、monkey-patching、依赖注入容器和生成代码可能改变实际运行时行为，因此关系、变化邻近性和模型建议都不能单独证明运行时因果关系。
