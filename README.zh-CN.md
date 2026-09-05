# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

将获准分析的 Java/Spring 或 Python 代码库作为立体3D地图探索。查找符号、追踪有源码依据的依赖路径，并查看快照之间的变化。

**Astra 发布纪念更新 · 0.6.0。** 为迎接 GPT-6 Astra，改进检索、证据追踪和技能指令。为人提供直观的3D界面，为AI提供结构化资料。[更新详情](docs/ASTRA_RELEASE.md)。

## 应用于当前任务

> 在这个项目中应用 Code Ontology Companion，协助我们接下来的工作。

Codex 检查实际可运行的工具，复用已授权的工作区，先执行状态检查以及相关符号检索或影响查询。相关查询使用同一快照。重要的 Java/Python 变更后，在授权范围内刷新，并报告新鲜度、分析范围和警告。默认仅用于当前对话；只有明确要求时才保存项目级指引。

> 在这里为当前任务设置本体。

对于一般请求，它选择 Code、Context 和 Contracts 中实际可运行的产品。Code 可以单独使用，明确指定的产品优先；不会自动安装缺少的产品。Context 只保存用户选择并确认的决策或约束，再次读取以核对；Contracts 检查选定的实际交换 JSON，并保留未支持、信息损失及未检查的结果。

[应用流程](skills/apply-code-ontology/SKILL.md)

## 安装 / 使用

[插件目录](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [GitHub 软件包](https://github.com/battle-doll/code-ontology-companion/releases)

此源码版本为0.6.1。目录有单独的审核与发布流程，因此可用版本可能不同。官方技能包包含应用与管理两项技能、分析器、界面及本地 MCP 设置说明，不包含MCP服务器；GitHub 完整包还包含只读stdio MCP服务器。无需云端接口。

## 探索真实的自身本体

[**打开3D探索器 →**](https://battle-doll.github.io/code-ontology-companion/)

由本插件自身受支持的源码生成，提供对应提交和证据。选择模块与符号即可查看连接和源码位置。界面呈现静态快照。按住Command或Ctrl点击可在新标签页打开。

[快照来源](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [架构](docs/zh-CN/ARCHITECTURE_AND_ROADMAP.md)

## 版本 0.6.1 的支持功能

- 在当前对话中执行首次实际查询，并衔接变更后的授权刷新和状态检查。
- 以3D为主的离线结构、影响和变更视图，带相机聚焦和渐进探索。
- 精确符号优先检索、结构筛选、分页以及固定快照读取。
- 按方向追踪依赖路径，提供每一步的证据和明确的遍历限制。
- 统一比较新增、删除、修改以及证据变化。
- Java/Spring 类型、导入、保守调用解析、注入和代理信号；Python 模块、函数、调用和流水线角色启发式分析。
- 保留原始证据的Code引用、供Context使用的不可变定位符，以及明确的Contracts兼容范围。
- 键盘与文本探索、减少动态效果和安全的2D备用视图。

## 快速开始

需要 Python 3.9+。首先在不写入文件的情况下检查支持范围。仅分析自己拥有或已获授权的代码；确认拟生成的资料后，在代码库之外初始化工作区。

```bash
python3 skills/manage-code-ontology/scripts/companion.py doctor --repo "/path/to/repo"
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo"
```

```bash
python3 skills/manage-code-ontology/scripts/companion.py init --repo "/path/to/repo" --workspace "/path/outside/repo/ontology" --authorized
python3 skills/manage-code-ontology/scripts/companion.py query --workspace "/path/outside/repo/ontology" --term "OrderService"
python3 skills/manage-code-ontology/scripts/companion.py impact --workspace "/path/outside/repo/ontology" --symbol "OrderService" --direction incoming
python3 skills/manage-code-ontology/scripts/companion.py diff --workspace "/path/outside/repo/ontology"
```

## 证据与兼容性

`graph.html`、`ontology.json` 和 `ontology.ttl` 使用同一源码本体。RDF 1.1 Turtle 的 `RelationshipEvidence` 与 PROV-O 谱系保留证据历史。`inferred` 不等于已验证，`runtime_unknown` 不是执行证明。证据附加率不是分析准确率。

Code负责代码结构，Context负责决策及有效时间，Contracts验证受支持的交换格式。各产品可以独立使用。[AI数据契约](skills/manage-code-ontology/references/ai-data-contract.md) · [引用交换](skills/manage-code-ontology/references/code-reference.md)。

向 Context 传递的是原始制品引用。真实快照尚不支持直接转换为严格的 Contracts draft；已验证范围见引用交换指南。

现有 Ollama `127.0.0.1:11434` 仅在单独同意后使用，建议与观测证据分开保存。确定性分析无需模型。

## 许可与隐私

Apache-2.0。分析器不会执行目标代码、发送遥测或直接发起网络请求。用户工作区保持本地；公开演示仅发布这个公开代码库的资料。不保留源码正文、注释或秘密信息。

[隐私](PRIVACY.md) · [安全](SECURITY.md) · [支持](SUPPORT.md) · [条款](TERMS.md) · [更新记录](CHANGELOG.md)
