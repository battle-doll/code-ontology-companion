# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[完整架构与路线图](docs/zh-CN/ARCHITECTURE_AND_ROADMAP.md)

Code Ontology Companion 是一个独立的 Codex 插件，用于为已获授权的 Java/Spring 或 Python 代码仓库维护注重隐私的本地知识图谱。

它结合了确定性静态分析、不可变快照、RDF 1.1 Turtle 导出、兼容 PROV-O 的血缘、交互式离线工作台，以及完整/本地 GitHub profile 中的只读本地 MCP 服务器。确定性分析器和 MCP 服务器不会执行目标代码、安装软件、发送遥测或发起网络请求。一个可选且需另行授权的辅助程序可以向固定回环地址 `127.0.0.1:11434` 上现有的 Ollama 服务发送有界的可移植本体元数据；其未经验证的建议始终位于已观察图谱之外。

提交到 OpenAI 的公开 **Skills-only** profile 只包含通用代码本体工作流。它不包含也不宣传下游项目专用的 AETHER Lab `runtime-binding` 命令、策略文档 schema 或回执生成器。该可选扩展仅随完整/本地 GitHub profile 提供，不托管于 OpenAI，且不授予运行时、策略写入、订单或资金权限。

为执行所请求的工作流，Codex 可能会处理命令输出，例如符号、计数和仓库相对路径。该平台处理受 OpenAI 的[适用条款](https://openai.com/policies/terms-of-use/)和[隐私政策](https://openai.com/policies/privacy-policy/)约束。安装此插件不会使 Codex 成为离线产品。

## 版本 0.3.4 的公开功能

- 映射 Java 包、导入、类型、方法、继承和基本依赖关系。
- 识别常见 Spring stereotype、`@Bean`、构造器/字段注入、AspectJ advice，以及事务、异步、缓存、授权和重试代理信号。
- 映射 Python 模块、导入、类型、函数、装饰器、调用、继承，以及启发式 Extract/Transform/Load/Validate/Orchestrate 角色。
- 更保守地解析 Java 泛型、record、嵌套类型、多接口以及 Spring 注解/注入情形，并处理 Python 别名、相对导入、词法遮蔽、嵌套函数和 `src/` 布局情形。
- 强制执行有界的源代码、图谱、影响分析和输出限制。
- 在获得明确的工作区级同意并验证 Ollama 报告的模型元数据后，可选择配置一个现有 Ollama completion 模型；仅存储规范化的 `inferred` sidecar，不改变确定性本体。
- 使用私有源指纹跳过未发生变化的刷新。
- 当分析器或 Companion 版本变化时，即使源代码未变也会刷新。
- 在 staging 中构建已变更仓库的分析，并以原子方式提升不可变快照。
- 在分析或验证失败时保留最后一个已知良好的快照。
- 比较快照并维护 observed/declared/inferred/validated/approved 血缘。
- 导出可移植的 RDF/Turtle，以及自包含的交互式 HTML 工作台；支持完整索引搜索、有界关系视角、易读详情且不使用 CDN。
- 直接在工作台中比较当前和上一快照，同时保持源指纹和绝对工作区路径私密。
- 将已识别的 Java 策略访问器读取映射到其保护的控制流分支，同时不保留任意字符串字面量。

版本 0.3.4 会对发生变化的仓库进行完整重新分析。指纹可避免不必要的未变更运行；按文件增量解析属于未来优化。

## 默认隐私与安全设置

- 仅分析您拥有或获准检查的代码。
- `doctor` 和 `preflight` 为只读操作。
- 初始化要求提供 `--authorized`，并使用仓库之外的新工作区。
- 不保留源代码正文、注释和任意字符串字面量。传递给已识别 Java 策略访问器且经验证的点分策略标识符可作为 `PolicyLeaf` 节点保留。
- 私有本地配置存储仓库绝对路径，私有清单存储每个文件的大小和 SHA-256 值，用于新鲜度检查。
- 可移植 RDF、HTML 和普通 MCP 响应省略绝对路径和完整指纹。
- 排除疑似机密文件、链接/重解析点、依赖项、VCS 内容和生成输出。
- 永远不会导入、构建、测试或运行目标项目。
- 完整/本地 GitHub profile 的 MCP 进程使用 stdio，不开放监听端口，并接受工作区 ID 而非任意文件系统路径；公开 Skills-only profile 不包含 MCP。
- 不安装守护进程、图数据库、本地模型、软件包或 watcher。Cytoscape.js 和 ELK.js 固定嵌入生成的 HTML；不使用 npm install、CDN、浏览器 worker、遥测或网络服务。
- 本地 LLM 检测不执行任何程序、不连接任何位置、也不写入任何内容。仅在取得同意后，可选辅助程序才可联系固定 IPv4 回环地址，验证 Ollama 报告的元数据，拒绝含远程/云标记的响应，并写入工作区级、模式为 `0600` 的配置和仅创建的 inferred 证据。

符号名称和仓库相对路径仍可能属于机密信息。除非另行获准共享，否则请将工作区和导出文件保留在本地。

## 要求

- 支持插件和 skill 的 Codex；使用完整/本地 GitHub profile 的内置 MCP 时，还需支持本地 stdio MCP
- Python 3.9 或更高版本
- 不需要第三方 Python 软件包、图数据库、Java 运行时或本地 LLM

MCP 启动器使用受支持 Codex 插件宿主提供的 JavaScript 运行时来定位 Python，不调用 shell。

## 手动快速开始

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  doctor --repo "/path/to/authorized/repository"

python3 skills/manage-code-ontology/scripts/companion.py \
  preflight --repo "/path/to/authorized/repository"
```

查看 preflight 结果并授权创建本地制品后：

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  init \
  --repo "/path/to/authorized/repository" \
  --workspace "/path/outside/repository/ontology-workspace" \
  --authorized
```

刷新并查询：

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  sync --workspace "/path/to/ontology-workspace"

python3 skills/manage-code-ontology/scripts/companion.py \
  query --workspace "/path/to/ontology-workspace" --term "OrderService"

python3 skills/manage-code-ontology/scripts/companion.py \
  diff --workspace "/path/to/ontology-workspace"
```

### 可选的现有 Ollama 增强

确定性工作流从不要求使用模型。在第一次相关工作流中，检测为只读操作。只有检测到 Ollama 时，Companion 才应询问是否检查现有本地模型。同意仅允许检查固定回环地址上的模型并配置工作区；不允许安装、下载、启动服务器或使用任意端点。Ollama 报告为远程/云端的模型和结果会被拒绝。

```bash
python3 skills/manage-code-ontology/scripts/local_llm.py detect

# 仅在完成 skill 中所述披露并取得明确同意后运行。
python3 skills/manage-code-ontology/scripts/local_llm.py probe --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py configure \
  --workspace "/path/to/ontology-workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py enrich \
  --workspace "/path/to/ontology-workspace" \
  --authorized
```

辅助程序仅发送有界的符号元数据和 observed 关系，绝不发送源代码正文、注释、任意字符串、机密、绝对路径或私有文件哈希。它将规范化建议作为 `inferred` 证据存储在 `enrichments/<snapshot-id>/<run-id>.json` 下。不保留原始提示词和原始响应。Ollama 自身的网络行为不在 Companion 控制范围内。增强会执行选定模型并可能分配 CPU/GPU 内存；辅助程序发送 `keep_alive=0`，以请求在每次响应后立即卸载。`localMetadataVerified=true` 仅表示 Ollama API 报告的 digest、size、format、model information、capability 和 remote-marker 字段通过了 Companion 的检查。它不证明模型权重字节、回环服务身份、仅本地执行或 Ollama 未进行出站通信。参见 [local-llm.md](docs/zh-CN/references/local-llm.md)。

### 仅适用于完整/本地 GitHub profile 的可选 AETHER Lab 运行时绑定

此下游项目专用扩展不包含在公开 Skills-only/OpenAI 提交制品中，也不在 OpenAI 上托管或宣传。它只随完整/本地 GitHub profile 提供，并被有意排除在只读 MCP 服务器之外。版本 0.3.4 仅在 macOS/POSIX（不包括 Windows）上支持此精确的模式 `0400` 回执。它要求最新的当前快照、受支持的策略叶、一个完全无重复键的本地 JSON 或 `policy-json` 文档、源代码仓库之外的新输出路径，以及明确授权：

```bash
mkdir -m 700 "/private/path/runtime-bindings"

python3 skills/manage-code-ontology/scripts/companion.py \
  runtime-binding \
  --workspace "/path/to/ontology-workspace" \
  --policy-leaf "strategy.exits.timeStopMinutes" \
  --policy-document "/path/to/authorized/repository/policies/policy.md" \
  --output "/private/path/runtime-bindings/time-stop.json" \
  --authorized
```

输出严格实现 `aether.runtime-effective-ontology-binding/v1`：规范 JSON 后加一个 LF、自哈希、命令返回的外部文件哈希、已排序且带哈希的本体边引用、冻结的源/快照哈希、精确的 false authority、仅创建发布以及模式 `0400`。

对于此回执，`runtimeEffective=true` 只有一个狭义含义：在冻结的活动源代码中，经静态分析，指定的叶可到达生产控制流分支，并且所提供的策略文档没有会禁用该叶的已知 AETHER 遮蔽/启用条件。生成方根据活动源代码重建图谱，并要求节点/边与快照完全一致。仅测试/fixture 路径、陈旧源代码、未使用的读取、活动的止损/止盈阶梯、已禁用的 trailing、歧义路径或已发生变化的输出都会以失败关闭方式处理。

它**不能**证明分支已运行、订单已提交、策略安全或利润发生变化。它不授予候选生成、gate、批准、提升、策略写入、订单、网络、运行时写入或资金权限。v1 回执无法在不破坏 Lab 精确 schema 的情况下包含策略文档哈希，因此消费方 Lab 必须在使用时独立复核精确基线策略和遮蔽条件。

## 工作区管线

```text
已授权源代码
  -> 私有源清单
  -> 隔离的 staging 分析
  -> 制品验证
  -> 不可变快照提升
  -> 当前快照指针
  -> RDF / 交互式离线 HTML / 只读 MCP
```

每个快照包含 `ontology.json`、`ontology.ttl`、`report.md`、`graph.html`、`snapshot.json` 和私有的 `source-manifest.json`。工作区还包含仅追加的 `lineage.jsonl` 和可移植的 `lineage.ttl`。

## RDF 可移植性与血缘

核心词汇表保留 Explorer 1.0 的 `co:` 命名空间，使旧导出保持兼容。血缘使用 W3C PROV-O 以及有文档说明的 Companion 命名空间。Turtle 导出可导入兼容 RDF 1.1 的存储。特定存储的索引、推理规则和扩展可能需要映射。

## 静态分析限制

图谱是导航和变更规划证据，不是运行时跟踪、安全结论、因果证明或正确性保证。完整/本地 GitHub profile 中的可选运行时绑定回执仅缩小静态源代码可达性和已知策略遮蔽的范围；它不证明运行时执行或结果因果关系。反射、生成代码、运行时 Spring 条件、动态代理、外部配置、依赖版本和 Python 元编程可能不完整。

## 开发

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
python3 scripts/build_release.py
python3 scripts/build_skills_only_release.py
```

安全问题：[SECURITY.md](docs/zh-CN/SECURITY.md)。支持：[SUPPORT.md](docs/zh-CN/SUPPORT.md)。

## 许可证与独立性

源代码采用 Apache-2.0 许可证。本项目独立开发，与 OpenAI、Broadcom、VMware、Spring project、Oracle 或 Python Software Foundation 无隶属关系，也未获得其认可。产品名称仅用于说明兼容性。
