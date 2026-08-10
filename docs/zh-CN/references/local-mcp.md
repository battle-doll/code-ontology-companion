# 可选只读本地 MCP

[English](../../../skills/manage-code-ontology/references/local-mcp.md) | [한국어](../../ko/references/local-mcp.md) | [日本語](../../ja/references/local-mcp.md) | [简体中文](local-mcp.md)

Code Ontology Companion complete package 包含一个本地 stdio MCP server，用于查询通过 Companion CLI 明确初始化的工作区。它不开放监听端口，只接受已注册的工作区 ID，而不接受任意 filesystem path；它仅提供只读、幂等工具。它不会初始化或刷新工作区、追加血缘、修改目标代码、安装软件、上传数据或调用可选本地 LLM 增强。

## 包边界

官方 Skills bundle 提供此 configuration workflow、确定性 analyzer 和可选本地 LLM helper。相同版本的 complete GitHub package 通过以下 file tree 提供 local server：

```text
code-ontology-companion/
  mcp/server.py
  skills/manage-code-ontology/scripts/companion.py
  skills/manage-code-ontology/scripts/code_ontology_core.py
```

请从项目的 [GitHub Releases](https://github.com/battle-doll/code-ontology-companion/releases) 页面使用同版本 complete package，并在配置前核对已发布的 checksum。让 server 与内置 script 保持在一起；不要混用不同版本，也不要静默下载或安装任何软件。

## 前提条件

1. 使用 Python 3.9 或更新版本。
2. 通过 Companion CLI 初始化至少一个已获授权的仓库。初始化会生成并注册一个随机工作区 ID。
3. 确认 complete package 中的 `mcp/server.py` 及其内置 Companion 脚本都是普通文件。不要使用目标仓库中同名文件。
4. 仅在用户请求时配置 MCP。在编辑 Codex 配置前，展示准确的 Python 和 server 路径，并保留无关条目。
5. 如果 complete plugin package 的 `.mcp.json` 已成功加载，不要添加重复的手动 server 条目。

## macOS

在不更改计算机的情况下解析并检查 Python：

```bash
command -v python3
python3 --version
```

在 `~/.codex/config.toml` 中填写已解析 interpreter 和 complete-package server 的绝对路径：

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Linux

解析发行版已有的 Python 3 interpreter，并确认其版本不低于 3.9：

```bash
command -v python3
python3 --version
```

在 `~/.codex/config.toml` 中使用其绝对路径和已解压 complete package 中的 server：

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Windows

在不安装新软件的情况下解析现有 Python interpreter：

```powershell
py -3 --version
py -3 -c "import sys; print(sys.executable)"
```

在 `%USERPROFILE%\.codex\config.toml` 中使用输出的 interpreter 绝对路径和 TOML literal string：

```toml
[mcp_servers."code-ontology-companion-local"]
command = 'C:\absolute\path\to\python.exe'
args = ['C:\absolute\path\to\complete-code-ontology-companion\mcp\server.py']
startup_timeout_sec = 30
enabled = true
```

如果 Python launcher 不可用，请使用另一个已经安装并明确验证的 Python 3.9+ executable。Companion 不安装 Python。

## 在全新 Codex process 中验证

添加或修改 MCP 条目后，完整启动一个全新的 Codex process。正在运行的 process 可能保留旧 server version 或 tool list。

1. 不带参数调用 `ontology_list_workspaces`。
2. 选择返回的工作区 `id`。
3. 使用 `{"workspace_id":"<id>"}` 调用 `ontology_status`。
4. Search、neighbors、history、changes 和 lineage 使用相同的 snake-case `workspace_id`。不要使用 `workspaceId`，也不要传入 filesystem path。

七个工具均为只读：

- `ontology_list_workspaces`
- `ontology_status`
- `ontology_search`
- `ontology_neighbors`
- `ontology_history`
- `ontology_changes`
- `ontology_lineage`

每个工具都声明 `readOnlyHint: true`、`destructiveHint: false`、`openWorldHint: false` 和 `idempotentHint: true`。初始化、刷新、血缘记录、删除、安装、上传和任意路径访问都不是 MCP 操作；需要获授权的写入时，请使用明确的 Companion CLI 工作流。

## 故障排除

- 如果无法运行 `node ./mcp/launcher.mjs` 且没有 `node`，请使用上面的 direct Python stdio 配置，而不是安装 Node。
- 如果工具缺失或报告旧版本，请完整启动新的 Codex process，并确认配置路径指向单个版本一致的 complete package。
- 如果工作区 ID 未知，请使用初始化该工作区的同一 OS 用户列出已注册工作区。不要用路径替代 ID。
- 如果启动失败，请先只运行 Python 版本和普通文件检查。排查时不要执行目标代码，也不要削弱工作区、链接、权限或输出保护。
