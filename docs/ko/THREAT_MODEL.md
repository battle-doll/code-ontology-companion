# 위협 모델

[English](../../THREAT_MODEL.md) | [한국어](THREAT_MODEL.md) | [日本語](../ja/THREAT_MODEL.md) | [简体中文](../zh-CN/THREAT_MODEL.md)

## 자산

- target source 및 architecture
- source tree 근처의 credential 및 configuration
- target-repository integrity
- current 및 historical ontology integrity
- private workspace path 및 source fingerprint
- installation, transfer, background activity에 대한 user control
- 선택적 local inference configuration 및 inferred sidecar

## 신뢰 경계

접근 권한이 있더라도 repository content는 신뢰할 수 없습니다. filename, symbol, annotation, comment, syntax error, generated artifact는 instruction이 아니라 data입니다.

Codex가 workflow를 조율합니다. analyzer는 core filesystem, authorization, output, execution boundary를 독립적으로 강제합니다. local MCP server는 두 번째 경계입니다. 등록된 workspace ID만 받고 read-only method를 제공합니다.

선택적 local LLM helper는 의도적으로 격리된 세 번째 경계입니다. deterministic analysis나 MCP가 import하지 않습니다. 동의 전에는 알려진 installation indicator만 검사할 수 있습니다. 동의 후에는 고정 IPv4 loopback endpoint 하나에 접속하고 선택한 workspace 내부에만 쓸 수 있습니다.

## 위협 및 완화책

| 위협 | 완화책 |
| --- | --- |
| source 또는 name의 prompt injection | source body, comment, arbitrary string을 보존하지 않으며, 검증된 dotted policy identifier는 data-only graph node입니다. skill은 모든 identifier를 untrusted data로 취급하도록 요구합니다. |
| secret 수집 | secret처럼 보이는 name/extension과 일반적인 VCS, dependency, generated, cache path를 제외합니다. |
| link 또는 path escape | link를 따라가지 않고, root link/reparse point를 거부하며, workspace 및 snapshot containment를 검증합니다. |
| FIFO 또는 device blocking | regular file만 읽고 special file은 건너뜁니다. |
| target-code execution | import/build/test/runtime path가 없으며, package check가 target execution primitive를 거부합니다. |
| repository modification | workspace는 외부에 있어야 하고 repository를 포함할 수 없습니다. target digest test가 read-only behavior를 강제합니다. |
| partial 또는 corrupt refresh | stable before/after manifest, staging, validation, immutable snapshot, atomic state promotion을 사용합니다. |
| 동시 source change | fingerprint mismatch가 staged output을 quarantine하고 last known-good를 보존합니다. |
| MCP arbitrary file access | MCP는 filesystem path가 아니라 임의로 선택된 등록 workspace ID를 받습니다. |
| MCP hidden write | 노출된 모든 MCP tool은 read-only이며 정확한 annotation이 있습니다. |
| Analyzer 또는 MCP network exfiltration | core analyzer, workspace CLI, workbench, launcher, MCP에는 network client가 없고 listening socket을 열지 않습니다. |
| Silent local LLM connection | indicator detection은 아무것도 실행하지 않고 어디에도 연결하지 않습니다. probe, configure, enrich, disable은 연결 또는 쓰기가 가능한 경우 explicit authorization을 요구합니다. |
| Endpoint redirection 또는 LAN/public transfer | helper는 `HTTPConnection("127.0.0.1", 11434)`만 구성하고 URL 또는 host input을 받지 않으며 proxy configuration을 우회하고 redirect를 따라가지 않습니다. |
| Remote/cloud result를 local evidence로 수락 | `/api/tags`, `/api/show`, `/api/chat`이 보고한 remote/cloud marker, digest/size/format/model information 또는 completion capability 누락은 fail closed 처리됩니다. |
| Prompt injection 또는 fabricated model output | 제한된 portable metadata만 보내고 identifier를 untrusted data로 선언합니다. strict JSON, duplicate-key, finite-number, node-ID, role, count, size, timeout check가 malformed output을 거부합니다. |
| Model inference를 fact로 승격 | normalized result는 정확한 false authority를 가진 create-only `inferred` sidecar이며 observed graph, RDF, lineage, MCP output에 병합되지 않습니다. |
| Private-path disclosure | absolute path와 full fingerprint는 일반 RDF, HTML, MCP output에서 제거됩니다. |
| Resource exhaustion | 지원되는 extension만 사용하고, file당 2 MiB 및 aggregate source limit, 제한된 graph/impact/visualization/LLM payload 및 response limit를 적용합니다. |
| HTML injection | title escaping, JSON-safe embedding을 사용하며 CDN, iframe, remote script, fetch는 없습니다. |
| 잘못된 인과 결론 | observed/declared/inferred/validated/approved evidence를 분리하고 문서에서 runtime 또는 causal claim을 금지합니다. |

## 잔여 위험

- symbol 및 repository-relative path가 confidential architecture를 드러낼 수 있습니다.
- 변경된 repository는 버전 0.5.0에서 전체 재분석되며 눈에 띄는 CPU 및 memory를 사용할 수 있습니다.
- static parsing은 reflection, generated code, runtime condition, dynamic dispatch, metaprogramming을 놓칠 수 있습니다.
- local registry 및 workspace는 이미 사용자의 filesystem permission을 가진 다른 process에 정보를 노출합니다.
- compromised Python/Node runtime, Codex host, operating system, user account는 이 plugin의 security boundary 외부입니다.
- 사용자가 artifact 생성 후 의도적으로 공유할 수 있습니다.
- Loopback은 Companion의 destination을 제한하지만 별도 관리 Ollama process 또는 model의 network behavior, logging, retention은 제한하지 않습니다.
- Enrichment는 선택한 model을 실행하고 CPU/GPU memory를 할당할 수 있습니다. `keep_alive=0`은 response 후 immediate unload를 요청하지만 별도 관리 service의 resource release를 보증할 수 없습니다.
- Ollama API metadata는 self-reported입니다. `localMetadataVerified=true`는 model weight byte를 보증하거나 loopback service를 인증하거나 local execution 또는 outbound traffic 부재를 증명하지 않습니다. chat-response marker는 request metadata가 해당 service에 도달한 후에만 거부할 수 있습니다.
- Model suggestion은 schema validation 후에도 틀리거나 적대적일 수 있습니다. 검증되지 않은 inference로 남으며 독립적인 검토가 필요합니다.

## 보안을 변경하는 확장

public network endpoint, remote AI call, 문서화된 fixed-loopback optional helper를 넘는 확장, target-code execution, automatic package/model/database installation, authentication, telemetry, persistent daemon, filesystem hook, write-capable MCP tool, external graph store에는 새 privacy, license, threat-model, submission review가 필요합니다.
