# 可选本地 LLM 增强

[English](../../../skills/manage-code-ontology/references/local-llm.md) | [한국어](../../ko/references/local-llm.md) | [日本語](../../ja/references/local-llm.md) | [简体中文](local-llm.md)

版本 0.3.3 可以把现有 Ollama 安装用作可选的本地推理 sidecar。没有它，确定性本体仍然完整，并且始终是 observed 证据的来源。

## 同意顺序

1. 对于已初始化的现有工作区，先运行 `status`。如果状态为 enabled，不要再次询问、probe 或 configure。如果状态为 disabled，除非用户明确请求重新启用，否则不要再次询问。只有状态为 `not_configured` 或新工作区时才继续此顺序。
2. `doctor` 或 `local_llm.py detect` 只能检查已知 executable/app 指示器。检测不运行进程、不连接端口、不写入文件。
3. 只有检测到受支持的 Ollama 且有已初始化工作区时才询问。对于新工作区，等待经过授权的 `init` 成功。在询问前披露固定 endpoint、数据范围、输出路径、证据类别和剩余风险。
4. 只有得到肯定答复后，才运行 `probe --authorized`。它只联系 `127.0.0.1:11434`，并列出 Ollama tag 元数据通过有界验证的模型候选。它不启动 Ollama，也不安装/下载模型。
5. 如果恰好有一个候选，显示其名称和 digest 并进行配置；配置还要求来自 `/api/show`、由 Ollama 报告的 model information 和 completion capability。如果有多个候选，请用户选择。如果没有候选、验证失败或 Ollama 不可用，则不写入任何内容，并保持确定性工作流启用。
6. 配置限定于工作区。`disable --authorized` 会停止未来增强，同时保留现有证据 sidecar。

同意披露必须说明：

> 检测到现有 Ollama。如果启用，Companion 将仅通过 127.0.0.1:11434 联系现有服务，并发送有界的可移植本体元数据，而非源代码正文、注释、任意字符串、机密、绝对路径或私有文件哈希。它不会安装或下载模型，也不会启动 Ollama 服务。经过授权的增强将执行选定模型，可能分配 CPU/GPU 内存，并会通过 `keep_alive=0` 请求在响应后立即卸载。有效的规范化建议会作为未经验证的 `inferred` 证据存储在此工作区下，绝不合并到 observed 图谱。Ollama 自身的网络行为不在 Companion 控制范围内。是否允许我检查现有本地模型并配置此工作区？

拒绝、超时或服务不可用不属于核心本体工作流错误。在同一工作流中被拒绝后，不要重复询问。

## 命令

在内置 Companion 脚本旁解析 `LOCAL_LLM`：

```bash
LOCAL_LLM="$SKILL_DIR/scripts/local_llm.py"

python3 "$LOCAL_LLM" detect
python3 "$LOCAL_LLM" probe --authorized
python3 "$LOCAL_LLM" configure \
  --workspace "/absolute/path/to/workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 "$LOCAL_LLM" status --workspace "/absolute/path/to/workspace"
python3 "$LOCAL_LLM" enrich \
  --workspace "/absolute/path/to/workspace" \
  --authorized
python3 "$LOCAL_LLM" disable \
  --workspace "/absolute/path/to/workspace" \
  --authorized
```

启用后，只在用户请求的相关本体分析期间、且确定性快照已为当前版本时使用 `enrich`。保存的工作区同意允许未来为该工作区按需增强，但每次使用都要报告。`init`、`sync`、`watch` 和所有 MCP 工具绝不会隐式调用该辅助程序。

## 固定数据与网络边界

辅助程序：

- 仅通过字面 IPv4 回环 host `127.0.0.1` 和端口 `11434` 支持 Ollama；
- 拒绝任意 URL、DNS 名称、LAN/公网地址、proxy routing、redirect、API key、报告的 remote/cloud 标记，以及缺失或无效的 Ollama 报告模型元数据；
- 最多发送 80 个代码符号候选，每个候选最多 12 个 observed 关系，并限制名称和仓库相对路径；
- 排除源代码正文、注释、任意字符串字面量、环境变量、凭据、绝对路径、源指纹、私有源清单和原始文件哈希；
- 请求不使用 streaming、temperature 为零、严格 schema 的 JSON 响应，并设定有界响应大小和超时；使用 `keep_alive=0` 请求 Ollama 在响应后立即卸载模型；
- 拒绝重复键、非有限数值、未知节点、不受支持角色、重复建议、畸形 JSON 和超大输出。

`localMetadataVerified=true` 的含义被有意限定得很窄：Ollama 的 `/api/tags` 和 `/api/show` 响应报告的 digest、size、format、model information、completion capability 和 remote-marker 字段通过了这些检查。它不会验证模型权重字节、认证在回环上监听的进程、证明推理在本地运行或证明 Ollama 未发起出站请求。`/api/chat` 中的 remote/cloud 标记也会被拒绝，但只能在已披露候选元数据到达该服务之后进行。

回环只能证明 Companion 把请求发送到了哪里。它不能证明独立管理的 Ollama 进程从不与外部通信。要求 air-gapped 保证的用户必须在操作系统和 Ollama 配置层强制执行，或保持增强禁用。

推理是真实的本地计算操作：Ollama 可能把模型权重加载到 CPU 或 GPU 内存中，并在回答时消耗计算资源。`keep_alive=0` 请求在响应后立即卸载，但 Companion 无法证明 Ollama 已释放资源，也无法覆盖 API 契约之外的行为。

## 证据与保留

配置以模式 `0600` 的 `local-llm.json` 存储在所选工作区中。它包含 provider、固定 endpoint、选定模型名称和 digest、capability 元数据、同意版本和数据范围版本。它不包含 API key、executable 路径、任意 URL 或仓库路径。

每次成功运行会在以下位置创建一个模式 `0600`、仅创建的 sidecar：

```text
enrichments/<snapshot-id>/<run-id>.json
```

Sidecar 仅保留规范化建议、模型和 schema 来源、输入/本体 digest 以及精确的 false authority。不保留原始提示词和原始模型响应。它绝不修改 `ontology.json`、RDF、runtime binding、目标源代码或血缘证据。建议属于 `inferred`；其置信度不会使其成为 observed、validated 或 approved。
