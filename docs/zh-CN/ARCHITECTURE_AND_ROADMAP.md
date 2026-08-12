# Code Ontology Companion：架构与当前功能

[English](../ARCHITECTURE_AND_ROADMAP.md) | [한국어](../ko/ARCHITECTURE_AND_ROADMAP.md) | [日本語](../ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](ARCHITECTURE_AND_ROADMAP.md)

## 1. 概述

Code Ontology Companion 0.5.0 为已授权的 Java/Spring 和 Python 仓库构建注重隐私的本地代码本体。它通过确定性静态分析生成带明确关系证据与 adapter coverage 的不可变快照、RDF 1.1 Turtle、兼容 PROV-O 的血缘信息，以及提供默认 2D 和可选 3D 的自包含无障碍离线工作台，并提供 CLI 与只读本地 MCP 查询。

核心分析无需图数据库、LLM、常驻服务或目标项目运行环境。可选 Ollama 增强仅在用户明确同意后使用既有的本地安装，并将结果作为独立的 `inferred` sidecar 保存。

## 2. 当前实现架构

```text
已授权的 Java/Spring 或 Python 仓库
                    |
                    v
          安全预检与源文件发现
          - 敏感路径与链接防护
          - 文件大小和数量限制
          - 不导入、不构建、不执行目标代码
                    |
                    v
             确定性静态分析
          - Java/Spring 结构与保守信号
          - Python 结构与数据管线关系
                    |
                    v
            规范化本体与来源信息
          - 稳定标识符和关系
          - observed / declared / inferred
          - PROV-O 兼容血缘
                    |
                    v
             原子不可变快照发布
          - JSON
          - RDF 1.1 Turtle
          - 报告与离线工作台
          - 私有 manifest 与 current 指针
                    |
          +---------+----------+
          |                    |
          v                    v
       CLI 查询          只读本地 MCP
          |                    |
          +---------+----------+
                    |
                    v
        可选、经同意的本地 Ollama 增强
        - 有界可移植元数据
        - 独立 inferred sidecar
```

## 3. 支持的分析范围

### 3.1 Java 与 Spring

分析器支持 Java 包、类型、record、方法、导入、继承和调用关系，并提取 Spring 组件、Bean 声明、依赖注入、注解、事务、异步、缓存、授权、重试、AOP 与代理相关的保守静态信号。

Java 的 unqualified call 或 `this.method(...)` 仅在同一 owner 中恰好有一个 method name 和 argument count 匹配的 candidate 时解析。已识别 imported `Type.method(...)` 会记录为 `ExternalCallable`；相同 arity overload 和 dynamic receiver 会保守省略。

这些关系表示源代码中可观察到的结构和潜在连接，不表示活动 ApplicationContext、代理解析结果或实际执行路径。

### 3.2 Python

分析器支持 Python 模块、类、函数、装饰器、调用、导入、继承，以及面向数据管线的 source、transform、sink 等角色关系。角色与关系由确定性规则生成，并保留解析警告和覆盖范围信息。

### 3.3 版本与变更

每次初始化或同步都会在 staging 中完成分析和验证，再原子提升新的不可变快照。私有源指纹用于检测变化；历史、差异和血缘命令可以比较当前与先前快照。分析期间源文件发生变化时，系统保留最后一个已知良好的快照。

### 3.4 关系 evidence 与 adapter coverage

版本 0.5.0 保留原有 `source`/`target`/`type` relation triple 和稳定 identity。每条 relation 的附加 `evidence` array 包含稳定的 `rule_id`、定性 `basis`（`direct_syntax`、`resolved_static`、`framework_semantic`、`name_heuristic`）、`runtime_status`（`not_applicable`、`runtime_unknown`）、可选的仓库相对 `path`/`line_start`/`line_end`，以及有界 `limitations`。

`document.quality` contract version `1.0` 报告 `relationship_evidence` 的 `total_edges`、`documented_edges`、`missing_evidence`、`coverage_percent`、`basis_counts`、`runtime_status_counts`，以及 Java/Python adapter 的 `status`、`detected`、`capabilities`、`unsupported_runtime`。两个 adapter 始终显示，`detected` 用于区分该语言是否实际存在。定性 basis 不是数值概率，parse warning 为 0 也不能证明静态或 runtime coverage 完整。

## 4. 存储与可移植性

文件快照是默认存储：

- JSON 保存规范化本体和查询索引；
- RDF 1.1 Turtle 提供标准可移植边界；
- PROV-O 兼容血缘连接源修订、分析器版本和快照；
- 私有 manifest 保存绝对仓库路径和逐文件 SHA-256；
- 原子 `current` 指针指向已验证快照。

Turtle 可以导入兼容 RDF 的存储，但特定存储的索引、推理和认证配置需要单独映射。版本 0.5.0 保留所有原有 direct triple，并通过附加 `RelationshipEvidence` resource 表示 rule、basis、source span、runtime status 与 limitation。推断结果不会自动提升为 observed 事实。

## 5. 查询与离线工作台

CLI 支持：

- `status` 与 `sync` 检查并刷新工作区；
- `query` 搜索符号和关系；
- `impact` 探索有界静态影响范围；
- `history` 与 `diff` 比较不可变快照；
- `lineage` 查看来源链。

每个快照包含自包含的离线 HTML 工作台，可按结构、Spring、数据管线和变更视角浏览图谱。工作台搜索完整的可移植索引，并按需渲染有界关系邻域。默认 `2D 结构`视图和可选 `3D 空间`星座使用相同的 node、relation、evidence、filter 和详情；3D 仅使用内置 Canvas2D perspective 和确定性静态位置，不新增 CDN、WebGL、package、worker、telemetry 或 network。

Pointer orbit/zoom 有 keyboard orbit、zoom、camera reset、node 遍历与选择、返回 root 等效操作。搜索、DOM 关系列表、详情面板和 2D graph 是包含 screen reader 在内的等效探索路径。工作台遵循 reduced-motion 与 forced-colors/high-contrast 偏好，向 assistive technology 提供 mode 和 selection 状态，页面隐藏时停止绘制；canvas 失败时回退到 2D。这是以 WCAG 2.2 AA 为目标的设计契约，并非在缺少单独手动 AT/browser 验证时作出的全面合规声明。

## 6. 只读本地 MCP

本地 stdio MCP 只接受已通过初始化流程注册的随机工作区 ID，不接受任意文件系统路径。它提供工作区列表、状态、搜索、邻居、历史、变更和血缘查询。

MCP 工具不会初始化或同步工作区，也不会修改源代码、快照、配置或目标系统。需要写入本地工作区的初始化、同步和决策记录仍通过显式 CLI 工作流执行。

## 7. 可选本地 Ollama

确定性分析始终可以独立运行。仅在用户明确同意后，Companion 才会检测既有 Ollama、验证 API 返回的模型元数据，并让用户选择符合条件的模型。

增强请求只向固定回环端点发送有界的可移植本体元数据。所有批次通过验证后，结果才会原子写入独立的 `inferred` sidecar。增强不会安装或启动 Ollama、下载模型，也不会改变 observed 图谱。

## 8. 平台支持

版本 0.5.0 支持 Windows、macOS 和 Linux。Python 3.9 或更高版本用于分析器、CLI 和本地 MCP；离线工作台使用现代浏览器打开。路径处理、链接防护和原子发布遵循各平台的文件系统语义。

## 9. 数据与权限边界

- 仅分析用户拥有或明确授权的仓库。
- 不导入、构建、测试或执行目标代码。
- 分析器不直接发起网络请求。
- 敏感名称、生成目录、链接目标和超限文件按规则排除。
- 可移植制品省略绝对仓库路径和私有源指纹。
- MCP 只读并限定于已注册工作区。
- Ollama 增强需要单独同意，结果保持 `inferred`。
- 插件不修改目标仓库、生产系统、部署、策略或凭据。

## 10. 当前限制

- Java/Spring 和 Python 关系来自静态分析，无法证明实际执行、运行时分派、反射目标或动态框架状态。
- 动态导入、元编程、生成代码、配置驱动绑定和条件 Bean 可能降低覆盖率。
- 静态影响范围表示结构关联，不证明因果关系、正确性或安全性。
- RDF/Turtle 可移植，但存储专用扩展可能需要额外映射。
- 本地模型输出可能不准确，始终作为未验证推断保存。

> Code Ontology Companion 为已授权的 Java/Spring 和 Python 仓库提供确定性本地代码本体、不可变快照、可移植 RDF 血缘、静态影响探索、版本比较、离线可视化、只读本地 MCP 和可选 Ollama 增强。

## 11. 当前路线图

此路线图仅表示方向，不承诺日期。版本 0.5.0 将 v0.3.4 architecture roadmap 的 0.5.x 大规模 visualization 方向推进为有界离线探索，并把可选 storage/query 明确保留为 future work。

版本 0.5.0 已包含 bounded Java/Python adapter coverage、定性 static evidence basis、unsupported-runtime indicator、source-attributed relation evidence、保守 Java call、ontology quality gate、共享同一有界邻域的默认 2D/可选 Canvas2D 3D，以及 visualization quality gate。

未来方向包括 setup diagnostics/progress/actionable failures、foreground watcher debouncing/single-flight、由 quality fixture 证明必要性的 bounded parser/language adapter、可选 RDF store/SPARQL/large-graph profile，以及单独限定范围的 build/config/authenticated read-only runtime evidence adapter。新语言、graph database、SPARQL/REST profile、whole-repository 3D、target execution、live runtime tracing、autonomous code change/deployment、security verdict，以及把 local-LLM inference 提升为 observed evidence，均不是版本 0.5.0 功能。
