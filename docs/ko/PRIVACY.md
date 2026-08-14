<!-- informational-translation; english-authoritative -->
# 개인정보 처리방침

[English](../../PRIVACY.md) | [한국어](PRIVACY.md) | [日本語](../ja/PRIVACY.md) | [简体中文](../zh-CN/PRIVACY.md)

> 이 번역은 편의를 위한 정보 제공용입니다. 내용이 다르거나 상충하는 경우 [영어 원문](../../PRIVACY.md)이 우선합니다.

시행일: 2026년 8월 1일

Code Ontology Companion은 사용자가 권한 있는 저장소를 지정하고 분석을 요청한 후에만 지원되는 소스 파일을 로컬에서 처리합니다.

## 데이터 범주 및 목적

분석기는 다음을 도출하기 위해 regular `.java` 및 `.py` file을 읽을 수 있습니다.

- symbol, annotation, decorator, qualified name
- 인식된 Java policy accessor가 사용하는 검증된 dotted policy identifier
- static structural relationship 및 language label
- stable extraction rule ID, 정성적 evidence basis, runtime-status indicator,
  bounded limitation, adapter-coverage summary
- repository-relative path, 선택적 relation-evidence line span, count, parse warning

source body, comment, arbitrary string literal, credential, API key, environment variable, raw prompt, raw model response를 의도적으로 보존하지 않습니다. dotted policy identifier는 semantic `PolicyLeaf`로만 보존됩니다. 해당 configured value와 주변 source text는 ontology에 저장되지 않습니다.

local refresh와 integrity를 위해 private workspace는 다음을 보존합니다.

- absolute repository path
- file별 relative path, size, language label, SHA-256 value
- local snapshot, workspace, event, 선택적 Git revision identifier

이러한 private field는 사용 권한이 있는 repository를 찾고, 변경을 감지하고, snapshot integrity를 보존하고, lineage를 유지하는 데만 사용됩니다. 이식 가능한 RDF, offline HTML, MCP result는 absolute repository path와 full file fingerprint를 생략합니다. Portable evidence의 repository-relative path와 line span도 기밀 project structure를 드러낼 수 있습니다.

사용자가 workspace 하나에 선택적 local LLM enrichment를 명시적으로 활성화하면 private local state는 다음도 보존합니다.

- 고정 loopback provider 및 endpoint, consent/data-scope version, 선택한 model name, digest, format, size, completion capability
- 기존 ontology node ID를 참조하는 정규화된 model suggestion과 제안된 pipeline role 및 confidence value
- 정확한 inferred run을 식별하는 데 필요한 snapshot, prompt-schema, input, ontology digest

이러한 suggestion에는 `inferred` label이 붙고 어떤 authority도 부여하지 않으며, 별도의 create-only sidecar에 저장합니다. observed ontology, RDF, lineage, MCP data에 병합하지 않습니다. Raw prompt와 raw response는 저장하지 않습니다.

secret처럼 보이는 filename, private-key 및 keystore extension, symbolic link/reparse point, 일반적인 VCS/dependency/build/cache/virtual-environment directory, special file, configured limit를 넘는 file은 제외됩니다.

## 로컬 저장, 보존, 삭제

`doctor`와 `preflight`는 파일을 생성하지 않습니다. 명시적 확인을 거친 initialization은 target repository 외부의 immutable initial snapshot을 포함한 local workspace를 작성합니다. Refresh는 새로운 immutable snapshot을 생성하고 이전 snapshot을 보존하며, lineage record를 local journal에 append합니다. 분석 대상 repository는 수정하지 않습니다.

publisher는 이러한 artifact의 사본을 받지 않습니다. 사용자가 일반적인 local file-management tool을 사용하여 선택한 workspace와 원하는 경우 local Companion registry의 해당 entry를 삭제할 때까지 남아 있습니다. 버전 0.5.2는 automatic retention 또는 cloud backup을 제공하지 않습니다.

## 네트워크, 수신자, 타사

결정론적 analyzer, workspace CLI, workbench, launcher와 MCP server는 다음과 같이 동작합니다.

- network request를 하지 않습니다.
- telemetry, analytics, cookie, advertising identifier, IP log를 수집하지 않습니다.
- external API를 호출하거나 source 또는 ontology data를 publisher에게 보내지 않습니다.
- package, model, database, daemon, background watcher를 설치하지 않습니다.
- listening network port를 열지 않습니다.

선택적 `local_llm.py` helper는 별도의 경계입니다. Detection은 process를 실행하거나 connection을 만들거나 file을 쓰지 않습니다. 사용자가 data disclosure를 확인하고 명시적으로 동의한 후에만 helper는 다음을 수행할 수 있습니다.

- literal IPv4 loopback endpoint `127.0.0.1:11434`에 접속
- 기존 Ollama model metadata를 검사하고 remote/cloud marker가 보고되거나 필수 metadata가 누락된 response 거부
- symbol name, qualified name, repository-relative path, node type, observed relationship metadata의 제한된 이식 가능 subset만 전송
- 제한된 JSON completion을 수신하고 normalized inferred output만 보존

source body, comment, arbitrary string, secret, credential, absolute path, private manifest, source fingerprint, raw file hash를 보내지 않습니다. arbitrary URL, LAN/public host, proxy, redirect, API key를 받지 않으며, model을 install/download하거나 Ollama service를 시작하지 않습니다. 승인된 enrichment는 선택한 model을 실행하고 CPU/GPU memory를 할당할 수 있으며, response 후 즉시 unload를 요청하도록 `keep_alive=0`을 보냅니다. Ollama로 제시된 loopback service와 선택된 model은 사용자가 관리하는 third-party recipient입니다. Companion은 해당 service를 authenticate하거나 외부 network behavior 또는 retention을 보증하거나 통제할 수 없습니다. 사용자는 Ollama 환경을 검토하고 제한하거나 enrichment를 비활성화해야 합니다.

`localMetadataVerified=true`는 Ollama의 `/api/tags` 및 `/api/show` response가 보고한 field가 제한된 validation을 통과했다는 사실만 기록합니다. model weight byte를 보증하거나, loopback service를 인증하거나, inference가 로컬에서 실행되었거나 Ollama가 outbound connection을 만들지 않았음을 증명하지 않습니다. chat response의 remote marker는 거부되지만, 그 response는 공개된 metadata가 이미 service로 전송된 후에 도착합니다.

Read-only MCP server는 stdio를 통해 local Codex host와 통신하고 등록된 workspace ID만 받습니다. workspace를 initialize, refresh, record, delete, upload할 수 없습니다.

Codex가 skill 또는 MCP tool을 호출할 때 symbol, qualified name, count, warning, snapshot ID, relative path와 같은 선택된 command 또는 tool output을 OpenAI가 요청된 기능을 제공하기 위해 처리할 수 있습니다. OpenAI는 [적용 약관](https://openai.com/policies/terms-of-use/)과 [개인정보 처리방침](https://openai.com/policies/privacy-policy/)이 적용되는 별도의 수신자입니다. operating system과 Codex host에는 각 provider의 약관이 적용됩니다.

## 사용자 제어

사용자는 다음을 수행할 수 있습니다.

- read-only preflight를 검토한 후 initialization 전에 중단
- local workspace 위치 선택
- runtime installation 또는 external transfer 거부
- core functionality를 잃지 않고 선택적 local LLM inspection 거부
- 이전 inferred sidecar를 보존하거나 수동으로 삭제하면서 workspace별 local LLM configuration 검사 또는 비활성화
- JSON, Turtle, Markdown, HTML artifact 검사
- 언제든 foreground watching 중단
- local workspace 및 registry data 삭제
- export를 로컬에 유지하거나 별도로 공유 승인

## 연락처

개인정보 관련 문의:

https://github.com/battle-doll/code-ontology-companion/issues
