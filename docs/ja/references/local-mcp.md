# オプションの読み取り専用ローカル MCP

[English](../../../skills/manage-code-ontology/references/local-mcp.md) | [한국어](../../ko/references/local-mcp.md) | [日本語](local-mcp.md) | [简体中文](../../zh-CN/references/local-mcp.md)

Code Ontology Companion の complete package には、Companion CLI で明示的に初期化された workspace を照会するローカル stdio MCP server が含まれます。待受 port を開かず、任意の filesystem path ではなく登録済み workspace ID を受け取り、読み取り専用で冪等な tool だけを公開します。Workspace の初期化や refresh、lineage の追記、target code の変更、software の install、data の upload、オプションの local LLM enrichment の呼び出しは行いません。

## Package の境界

公式 Skills bundle は、この configuration workflow、deterministic analyzer、オプションの local LLM helper を提供します。同じ version の complete GitHub package は、次の file tree で local server を提供します。

```text
code-ontology-companion/
  mcp/server.py
  skills/manage-code-ontology/scripts/companion.py
  skills/manage-code-ontology/scripts/code_ontology_core.py
```

プロジェクトの [GitHub Releases](https://github.com/battle-doll/code-ontology-companion/releases) page から同じ version の complete package を使用し、configuration の前に公開 checksum を確認してください。Server は同梱 script と一緒に保持し、異なる version を混在させたり、software を無断で download／install してはなりません。

## 前提条件

1. Python 3.9 以降を使用します。
2. Companion CLI で許可済み repository を 1 つ以上初期化します。Initialization により random workspace ID が作成、登録されます。
3. Complete package の `mcp/server.py` と同梱 Companion script が通常ファイルであることを確認します。Target repository 内の同名ファイルは使用しません。
4. ユーザーから依頼された場合にだけ MCP を設定します。Codex configuration の編集前に Python と server の正確な path を示し、無関係な entry を保持します。
5. Complete plugin package の `.mcp.json` がすでに正常に load される場合、手動 server entry を重複して追加しません。

## macOS

Machine を変更せずに Python を確認します。

```bash
command -v python3
python3 --version
```

確認した interpreter と complete-package server の absolute path を `~/.codex/config.toml` に設定します。

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Linux

Distribution に既存の Python 3 interpreter を確認し、version が 3.9 以降であることを検査します。

```bash
command -v python3
python3 --version
```

その absolute path と展開済みの complete-package server を `~/.codex/config.toml` に指定します。

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Windows

新たに install せず、既存の Python interpreter を確認します。

```powershell
py -3 --version
py -3 -c "import sys; print(sys.executable)"
```

出力された absolute interpreter path と TOML literal string を `%USERPROFILE%\.codex\config.toml` に使用します。

```toml
[mcp_servers."code-ontology-companion-local"]
command = 'C:\absolute\path\to\python.exe'
args = ['C:\absolute\path\to\complete-code-ontology-companion\mcp\server.py']
startup_timeout_sec = 30
enabled = true
```

Python launcher がなければ、すでに install 済みで明示的に確認した別の Python 3.9+ executable を使います。Companion は Python を install しません。

## 新しい Codex process での確認

MCP entry の追加または変更後、Codex process を完全に新しく起動します。実行中の process は、古い server version や tool list を保持している場合があります。

1. Argument なしで `ontology_list_workspaces` を呼び出します。
2. 返された workspace `id` を選びます。
3. `ontology_status` を `{"workspace_id":"<id>"}` で呼び出します。
4. Search、neighbors、history、changes、lineage でも同じ snake-case の `workspace_id` を使います。`workspaceId` や filesystem path を渡しません。

7 個の tool はすべて読み取り専用です。

- `ontology_list_workspaces`
- `ontology_status`
- `ontology_search`
- `ontology_neighbors`
- `ontology_history`
- `ontology_changes`
- `ontology_lineage`

すべての tool は `readOnlyHint: true`、`destructiveHint: false`、`openWorldHint: false`、`idempotentHint: true` を宣言します。Initialization、refresh、lineage の記録、deletion、installation、upload、arbitrary-path access は MCP operation ではありません。許可済み write が必要な場合は、明示的な Companion CLI workflow を使用します。

## トラブルシューティング

- `node ./mcp/launcher.mjs` が起動できず `node` がない場合は、Node を install せず、上記の direct Python stdio configuration を使用します。
- Tool が見つからない、または古い version を報告する場合、Codex process を完全に新しく起動し、configured path が version の一致する 1 つの complete package を指していることを確認します。
- Workspace ID が不明な場合、その workspace を初期化したのと同じ OS user で登録 workspace を一覧表示します。ID の代わりに path を渡しません。
- Startup に失敗した場合、最初に Python version と regular-file check だけを実行します。トラブルシューティング中に target code を実行したり、workspace、link、permission、output protection を弱めたりしません。
