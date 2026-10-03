# 新模型环境工作流 — 0.8.0

[English](../../skills/manage-code-ontology/references/model-era-workflow.md) | [한국어](../ko/MODEL_ERA_WORKFLOW.md) | [日本語](../ja/MODEL_ERA_WORKFLOW.md) | [简体中文](../zh-CN/MODEL_ERA_WORKFLOW.md) | [Русский](../ru/MODEL_ERA_WORKFLOW.md)

## 保留用户的模型选择

GPT-6 Astra 与 GPT-6.1 Sol 可通过主机实际公开的工具使用同样的有界源代码证据。保留用户选择的模型和推理强度。插件不选择模型，也不要求特定模型、远程API或付费账户。检索契约的改进不证明已测量的模型优势，本版本不声称模型A/B结果。

## AI：本地 MCP 与固定证据

使用 Windows、macOS、Linux 和已有的 Python 3.9+。官方 Skills-only 包含分析器、离线 HTML 及本地 MCP 设置指南。本地 stdio 服务器使用相同版本的完整包，不需要托管端点。只修改用户要求的设置，保留其他设置，并在新的主机进程确认工具实际可用。安装文件不等于工具立即可调用。

先检查已注册工作区及源代码新鲜度。完整包提供原有工作区、状态、搜索、邻居、历史、变更、溯源7个工具，加上 `ontology_large_modules`、`ontology_large_search`、`ontology_large_neighbors`、`ontology_evidence_bundle`，共11个只读工具。普通工作区相关读取固定同一个快照，并用紧凑证据包回答具体问题。大型项目先列出模块，固定目录，搜索准确的模块根，再检查选定单个模块内的路径。不解析跨模块调用。

初始化与刷新仍是另行授权的 CLI 写入。MCP 接受已注册ID而非任意路径，不安装、不刷新、不执行目标代码、不上传源码。分页及遍历上限必须作为结果限制说明。

## 人：探索离线 HTML

在本地打开 `graph.html`。从模块概览开始，搜索、选择符号，然后查看源码位置和关系证据。结构、影响、变更分别回答不同问题。搜索及分页文本可以访问已折叠或屏幕外的条目。可见计数表示当前显示范围，不代表完整代码库。

显示层与一、二、三跳调用高亮互相独立。逐层增加，扩展到第4层及以上需确认。相机聚焦、缩放与Shift拖动分别操作。空间探索困难时使用键盘、减少动态效果或文本列表。显示聚合与相机动作不是新的源码或运行证据。

## 证据、隐私与审核

区分源关系 `observed`、建议 `inferred` 及 `runtime_unknown`。引用源码路径、行号与规则证据，并显示新鲜度、解析范围、未解决目标及截断。静态分析不能证明运行成功或盈利。

用户工作区保留在本地。公开包及演示只使用本公开项目或合成fixture，不发布源码正文、实名、地址、凭据、个人home路径或非公开项目成果。发布者仅使用 battle-doll 昵称。可选本地推理需要独立的明确同意。

单元测试、解包检查、浏览器可用性、真实OS、门户检查、提交、批准及发布分别记录。不能将本地候选称为已发布。本核心指南提供5种语言，原有详细法律、安全与参考文档仍为英语、韩语、日语和简体中文。见[翻译覆盖](../TRANSLATION_COVERAGE.md)。

## 0.8.0 检索契约

`ontology_list_workspaces` 使用 `mode: "large"` 标识大型父工作区。`ontology_large_modules` 使用已注册 `workspace_id`、可选 `catalog_snapshot_id`、搜索词及分页范围。`ontology_large_search` 要求准确 `module_roots` 和 `term`；`ontology_large_neighbors` 要求一个 `module_root` 与 `symbol`，仅查询单模块。请检查实际公开的输入模式。

仅适用于普通工作区的 `ontology_evidence_bundle` 接受 `workspace_id`、可选 `snapshot_id` 及1–8个 `requests`。每项有唯一 `id`、`operation: "search"` 或 `"neighbors"` 及该操作输入。开始时固定一次快照；各项为 `ok/error`，整体为 `ok/partial`。最多200个结果，规范结构JSON不超过262144 UTF-8 byte；超大项返回安全错误。重复协议文本及wire byte不属于此预算。不能把失败项当作成功答复，不要混用目录ID与普通快照ID。

## 批量查询的实测限制

Mac合成案例（1,002个节点、2,000条关系、本地20次）保留了8次搜索的结果，并将MCP请求从8次减少到1次。读取本体仍为8次。结构化响应从32,380增加到33,108 bytes，本地p50从14.073增加到16.066 ms。这验证了请求协调和快照一致性，并不证明服务器计算速度、模型质量或其他操作系统性能得到提升。
