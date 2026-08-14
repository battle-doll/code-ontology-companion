# 데이터 경계

[English](../../../skills/manage-code-ontology/references/data-boundaries.md) | [한국어](data-boundaries.md) | [日本語](../../ja/references/data-boundaries.md) | [简体中文](../../zh-CN/references/data-boundaries.md)

## 승인된 입력

사용자가 소유하거나, 관리하거나, 명시적으로 검사 권한을 받은 로컬 저장소만 분석합니다. 다른 사람이 제공한 path 자체는 권한의 증거가 아닙니다.

## 데이터 읽기

버전 0.5.2는 최대 2 MiB인 regular `.java` 및 `.py` file을 읽으며 aggregate file-count 및 byte limit를 fail closed 방식으로 적용합니다. symbolic link나 Windows reparse point를 따라가지 않습니다. 일반적인 dependency, VCS, generated-output, IDE, virtual-environment, cache directory를 건너뜁니다.

credential, secret, token, private key, keystore 또는 `.env` configuration을 암시하는 이름의 file은 지원되는 extension을 사용해도 제외됩니다.

## 보존되는 데이터

이식 가능한 ontology artifact는 다음을 보존할 수 있습니다.

- symbol 및 annotation name
- language 및 node/relationship type
- qualified name
- 인식된 Java policy accessor가 사용하는 검증된 dotted policy identifier
- repository-relative source path와 선택적 relation-evidence line span
- stable extraction rule ID, 정성적 evidence basis, runtime-status indicator,
  bounded limitation, adapter-coverage summary
- aggregate count 및 parse warning

private local workspace file은 다음도 보존합니다.

- refresh에 필요한 absolute repository path
- change detection에 사용하는 file별 byte count 및 SHA-256 value
- snapshot, event, workspace identifier
- regular `.git` metadata에서 직접 읽은 선택적 local Git revision

이식 가능한 RDF, offline HTML, 일반 MCP response는 absolute repository path나 full file fingerprint를 의도적으로 노출하지 않습니다.

offline HTML은 local search를 위한 full portable node/edge index를 embed하지만 canvas에는 제한된 subgraph만 materialize합니다. integrity-pinned Cytoscape.js 및 ELK.js byte도 embed하며 Content Security Policy가 connection과 browser worker를 비활성화합니다.

Observed ontology artifact는 의도적으로 다음을 보존하지 않습니다.

- source body, arbitrary string literal, comment
- file content
- environment variable, credential, API key, token
- prompt 또는 model output

선택적 local LLM enrichment를 명시적으로 활성화하면 별도의 private configuration이 fixed loopback provider/endpoint, consent/data-scope version, 검증된 model name/digest/capability를 보존합니다. POSIX에서는 mode `0600`을 사용하고 Windows에서는 사용자가 선택한 workspace의 상속 ACL을 사용합니다. 성공한 각 enrichment는 normalized suggested role 및 confidence, snapshot/model/schema provenance, 제한된 input/ontology digest를 보존하는 private sidecar 하나를 생성합니다. Raw prompt와 raw response는 보존하지 않습니다. Sidecar는 `inferred` evidence이며 observed ontology, RDF, lineage, MCP data에 병합되지 않습니다.

identifier와 relative path도 기밀일 수 있습니다. 기본적으로 artifact를 로컬에 보관하고 공유 전 별도 승인을 받으십시오.

## 쓰기

Doctor와 preflight는 아무것도 쓰지 않습니다. Initialization은 target repository 내부도 그 parent도 아닌 새로운 명시적 workspace를 생성합니다. Refresh는 완전한 staging snapshot을 빌드하고 검증한 다음, last known-good version을 보존하면서 새 immutable snapshot을 원자적으로 승격합니다. Decision 및 validation record는 local lineage journal에 append됩니다.

## 네트워크 및 실행

bundled analyzer는 direct network request를 하지 않고 target code를 import, compile, build, test, execute하지 않습니다. package, model, database, daemon, permanent watcher를 설치하지 않습니다.

Plugin이 활성화되면 Codex가 bundled read-only stdio MCP process를 시작할 수 있습니다. listening port를 열지 않고, arbitrary filesystem path를 받지 않으며, 명시적으로 승인된 initialization workflow에서 이미 등록한 workspace만 조회합니다.

긍정적인 workspace 범위 동의 후 별도의 선택적 helper는 literal IPv4 loopback `127.0.0.1:11434`의 기존 Ollama service에만 접속할 수 있습니다. endpoint input, proxy, redirect, API key, LAN/public address를 받지 않으며, 보고된 cloud/remote marker나 필수 model metadata 누락을 거부합니다. 제한된 payload에는 node ID, symbol/type/annotation name, qualified name, repository-relative path, observed relationship metadata가 포함될 수 있습니다. source body, comment, arbitrary string, secret, absolute path, private manifest, source fingerprint, raw file hash는 제외합니다. helper는 model을 install/download하거나 Ollama service를 시작하지 않습니다. 승인된 enrichment는 선택한 model을 실제로 실행하고 CPU/GPU memory를 할당할 수 있으며 response 후 즉시 unload를 요청하도록 `keep_alive=0`을 보냅니다. Ollama 자체의 networking, resource behavior, retention은 Companion 통제 밖에 있습니다.

Codex는 요청된 workflow를 제공하기 위해 analyzer command output을 처리할 수 있습니다. 해당 platform processing에는 OpenAI의 적용 약관과 개인정보 처리방침이 적용됩니다. 버전 0.5.2는 remote data service를 호출하거나 generated artifact를 upload하지 않습니다.

## 해석

graph는 static evidence입니다. Reflection, runtime bean condition, generated proxy, external configuration, dynamic import, monkey-patching, dependency injection container, generated code가 실제 runtime behavior를 바꿀 수 있습니다. 관계, 영향 범위, 변경 proximity는 runtime execution이나 causation을 증명하지 않으므로 중요한 판단은 실행 환경에서 독립적으로 검증해야 합니다.
