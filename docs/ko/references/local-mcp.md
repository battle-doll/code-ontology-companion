# 선택적 읽기 전용 로컬 MCP

[English](../../../skills/manage-code-ontology/references/local-mcp.md) | [한국어](local-mcp.md) | [日本語](../../ja/references/local-mcp.md) | [简体中文](../../zh-CN/references/local-mcp.md)

Code Ontology Companion complete package에는 Companion CLI로 명시적으로 초기화한 workspace를 조회하는 로컬 stdio MCP 서버가 포함됩니다. 이 서버는 수신 port를 열지 않고 임의의 filesystem path 대신 등록된 workspace ID를 받으며, 읽기 전용이고 멱등인 tool만 제공합니다. Workspace를 초기화하거나 refresh하고, lineage를 추가하고, target code를 수정하고, software를 설치하고, data를 upload하거나 선택적 local LLM enrichment를 호출하지 않습니다.

## 패키지 경계

공식 Skills bundle은 이 configuration workflow, deterministic analyzer, 선택적 local LLM helper를 제공합니다. 같은 version의 complete GitHub package는 다음 file tree로 local server를 제공합니다.

```text
code-ontology-companion/
  mcp/server.py
  skills/manage-code-ontology/scripts/companion.py
  skills/manage-code-ontology/scripts/code_ontology_core.py
```

프로젝트 [GitHub Releases](https://github.com/battle-doll/code-ontology-companion/releases) 페이지에서 같은 version의 complete package를 사용하고, configuration 전에 게시된 checksum을 확인하십시오. Server를 함께 제공된 script와 함께 유지하고, 서로 다른 version을 섞거나 software를 몰래 download 또는 install하지 마십시오.

## 사전 조건

1. Python 3.9 이상을 사용합니다.
2. Companion CLI로 권한이 확인된 repository를 하나 이상 초기화합니다. Initialization은 random workspace ID를 생성하고 등록합니다.
3. Complete package의 `mcp/server.py`와 함께 제공되는 Companion script가 regular file인지 확인합니다. Target repository에 있는 같은 이름의 파일을 사용하지 않습니다.
4. 사용자가 요청한 경우에만 MCP를 구성합니다. Codex configuration을 편집하기 전에 정확한 Python path와 server path를 보여 주고, 관련 없는 entry를 보존합니다.
5. Complete plugin package의 `.mcp.json`이 이미 정상적으로 load된다면 수동 server entry를 중복 추가하지 않습니다.

## macOS

Machine을 변경하지 않고 Python을 확인합니다.

```bash
command -v python3
python3 --version
```

확인한 interpreter와 complete-package server의 absolute path를 `~/.codex/config.toml`에 넣습니다.

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Linux

Distribution에 이미 설치된 Python 3 interpreter를 확인하고 version이 3.9 이상인지 검사합니다.

```bash
command -v python3
python3 --version
```

그 absolute path와 압축을 푼 complete-package server를 `~/.codex/config.toml`에 지정합니다.

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Windows

새로 설치하지 않고 기존 Python interpreter를 확인합니다.

```powershell
py -3 --version
py -3 -c "import sys; print(sys.executable)"
```

출력된 absolute interpreter path와 TOML literal string을 `%USERPROFILE%\.codex\config.toml`에 사용합니다.

```toml
[mcp_servers."code-ontology-companion-local"]
command = 'C:\absolute\path\to\python.exe'
args = ['C:\absolute\path\to\complete-code-ontology-companion\mcp\server.py']
startup_timeout_sec = 30
enabled = true
```

Python launcher가 없으면 이미 설치되어 있고 명시적으로 확인한 다른 Python 3.9+ executable을 사용합니다. Companion은 Python을 설치하지 않습니다.

## 새 Codex process에서 확인

MCP entry를 추가하거나 변경한 뒤 Codex process를 완전히 새로 시작합니다. 실행 중인 process는 이전 server version이나 tool list를 유지할 수 있습니다.

1. Argument 없이 `ontology_list_workspaces`를 호출합니다.
2. 반환된 workspace `id`를 선택합니다.
3. `ontology_status`를 `{"workspace_id":"<id>"}`로 호출합니다.
4. Search, neighbors, history, changes, lineage에도 같은 snake-case `workspace_id`를 사용합니다. `workspaceId`나 filesystem path를 전달하지 않습니다.

열한 개 tool은 모두 읽기 전용입니다.

- `ontology_list_workspaces`
- `ontology_status`
- `ontology_search`
- `ontology_neighbors`
- `ontology_history`
- `ontology_changes`
- `ontology_lineage`
- `ontology_large_modules`
- `ontology_large_search`
- `ontology_large_neighbors`
- `ontology_evidence_bundle`

모든 tool은 `readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: false`, `idempotentHint: true`를 선언합니다. Initialization, refresh, lineage 기록, deletion, installation, upload, arbitrary-path access는 MCP operation이 아닙니다. 권한이 확인된 write가 필요하면 명시적인 Companion CLI workflow를 사용합니다.

## 문제 해결

- `node ./mcp/launcher.mjs`를 실행할 수 없고 `node`가 없다면 Node를 설치하지 말고 위의 direct Python stdio configuration을 사용합니다.
- Tool이 없거나 이전 version을 보고하면 Codex process를 완전히 새로 시작하고, configured path가 서로 일치하는 하나의 complete package를 가리키는지 확인합니다.
- Workspace ID를 찾을 수 없으면 그 workspace를 초기화한 것과 같은 OS user로 등록 workspace를 나열합니다. ID 대신 path를 전달하지 않습니다.
- Startup이 실패하면 먼저 Python version과 regular-file check만 실행합니다. 문제 해결 중 target code를 실행하거나 workspace, link, permission, output protection을 약화하지 않습니다.

## 0.8.0 조회 계약

`ontology_list_workspaces`는 대규모 부모를 `mode: "large"`로 구분합니다. `ontology_large_modules`는 등록 `workspace_id`와 선택 `catalog_snapshot_id`, 검색어·페이지 범위를 사용합니다. `ontology_large_search`는 정확한 `module_roots`와 `term`을 받고, `ontology_large_neighbors`는 하나의 `module_root`와 `symbol`을 받아 단일 모듈 안에서만 조회합니다. 실제 노출된 입력 스키마를 확인하세요.

일반 작업공간 전용 `ontology_evidence_bundle`은 `workspace_id`, 선택 `snapshot_id`, 1–8개 `requests`를 받습니다. 각 요청은 고유 `id`, `operation: "search"` 또는 `"neighbors"`와 해당 조회의 입력을 가집니다. 시작 시 스냅샷을 한 번 고정하며 항목은 `ok/error`, 전체는 `ok/partial`입니다. 총 결과 200개와 정규 구조 JSON 262144 UTF-8 byte로 제한하고 초과 항목은 안전한 오류로 처리합니다. 프로토콜의 중복 텍스트·wire byte는 이 예산 밖입니다. 실패한 항목을 성공한 답으로 취급하지 말고 카탈로그와 일반 스냅샷 ID를 혼용하지 마세요.
