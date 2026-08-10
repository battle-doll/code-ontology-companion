# 보안 정책

[English](../../SECURITY.md) | [한국어](SECURITY.md) | [日本語](../ja/SECURITY.md) | [简体中文](../zh-CN/SECURITY.md)

## 지원 버전

보안 수정은 최신 릴리스 버전에 제공됩니다.

## 취약점 신고

공개 issue에 private source, secret, credential, local absolute path, ontology artifact를 포함하지 마십시오.

다음 저장소의 GitHub private vulnerability reporting을 사용하십시오.

https://github.com/battle-doll/code-ontology-companion

private reporting을 사용할 수 없다면 exploit detail이나 confidential data 없이 private channel을 요청하는 최소한의 public issue를 여십시오.

## 보안 모델

버전 0.4.0 보안 모델:

- static parsing을 수행하며 target code를 import하거나 execute하지 않습니다.
- link/reparse point인 repository 및 workspace root를 거부합니다.
- link-like, special, sensitive-name, dependency, VCS, generated file을 건너뜁니다.
- per-file, total-source, source-count, graph, impact, HTTP, candidate, suggestion limit를 강제합니다.
- repository 외부의 새롭고 명시적인 workspace에만 artifact를 생성합니다.
- refresh를 staging에서 빌드하고 immutable snapshot을 원자적으로 승격합니다.
- analyzer 또는 Companion version이 바뀌면 변경되지 않은 repository도 refresh합니다.
- refresh 실패 후 마지막 정상 snapshot을 유지합니다.
- deterministic analysis, workspace operation, workbench와 MCP를 network-free로 유지하고 telemetry를 수집하지 않습니다.
- 선택적 Ollama를 실행하거나 port를 probe하거나 기록하지 않고 탐지합니다.
- 별도 helper가 `127.0.0.1:11434`에만 접속하기 전에 명시적인 workspace 범위 동의를 요구하고, 보고된 remote/cloud marker 또는 API metadata 누락을 거부하며, output을 검증되지 않은 create-only inferred sidecar로만 저장합니다.
- Codex host가 활성화한 경우에만 read-only stdio MCP process를 시작합니다.
- MCP는 port를 열지 않고 filesystem path 대신 등록된 workspace ID를 받습니다.
- MCP는 write, refresh, install, delete, upload, execution tool을 노출하지 않습니다.
- runtime, package, database, model, daemon, background watcher를 설치하지 않습니다.

선택적 helper는 Ollama를 신뢰할 수 있는 analyzer의 일부로 만들지 않습니다. Ollama 자체 networking, logging, model behavior, security는 Companion 경계 외부에 있습니다. loopback-only delivery가 충분한 보장이 아니라면 enrichment를 비활성화하거나 operating-system control을 적용하십시오. Enrichment는 선택한 model을 실행하여 CPU/GPU memory를 할당할 수 있습니다. helper는 response 후 즉시 unload를 요청하도록 `keep_alive=0`을 보내지만, 별도로 관리되는 service가 실제로 resource를 release했음을 보증할 수 없습니다. `localMetadataVerified=true`는 Ollama가 보고한 API metadata의 validation이지 model weight, loopback-service identity, local execution, outbound Ollama traffic 부재에 대한 attestation이 아닙니다.

생성된 output을 자동으로 공개해도 안전한 것은 아닙니다. symbol과 relative path가 confidential architecture를 드러낼 수 있습니다.
