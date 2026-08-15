# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

[아키텍처 및 지원 워크플로](docs/ko/ARCHITECTURE_AND_ROADMAP.md)

Code Ontology Companion은 사용 권한이 있는 기존 Java/Spring 또는 Python 코드를 소스 수준에서 정적으로 역공학해 개인정보 보호를 고려한 로컬 코드 온톨로지와 지식 그래프로 구성하는 독립형 Codex 플러그인입니다.

결정론적 정적 분석, 감사 가능한 관계 evidence, 불변 스냅샷, RDF 1.1 Turtle 내보내기, PROV-O 호환 계보, 대화형 오프라인 워크벤치, 읽기 전용 로컬 MCP 서버를 결합합니다. 결정론적 분석기와 MCP 서버는 대상 코드를 실행하거나, 소프트웨어를 설치하거나, 원격 측정 데이터를 전송하거나, 네트워크 요청을 하지 않습니다. 선택 사항인 별도 승인 도우미는 제한된 이식 가능 온톨로지 메타데이터를 고정 루프백 주소 `127.0.0.1:11434`의 기존 Ollama 서비스로 보낼 수 있으며, 검증되지 않은 제안은 관찰된 그래프 외부에 유지됩니다.

## 대화형 예시: Voice Notify for Codex

실제 Codex 플러그인을 분석한 Companion 결과를 확인할 수 있습니다. 이 공개
스냅샷은 [Voice Notify for Codex](https://github.com/battle-doll/codex-voice-notify)
`0.1.6`의 Python 참조 구현, 설정 도우미, 빌드·검증 도구와 테스트를 근거가
포함된 그래프로 구성합니다.

[Voice Notify 대화형 온톨로지 열기](https://rawcdn.githack.com/battle-doll/code-ontology-companion/a32b97474450a025fa383614cd83d0d0393317e7/docs/examples/codex-voice-notify-code-ontology.html) 또는
[자체 완결형 HTML 보기·다운로드](docs/examples/codex-voice-notify-code-ontology.html)를
사용할 수 있습니다.

이 스냅샷은 Python 파일 6개에서 노드 417개와 관계 769개를 생성했으며,
파싱 경고는 0개이고 모든 관계에 소스 위치와 추출 근거가 포함돼 있습니다.
기호 검색, 호출자·종속성 확인, 2D 구조와 3D 별자리 보기 전환, 관계별 규칙,
정성적 근거, 런타임 상태, 소스 위치와 한계를 직접 살펴볼 수 있습니다.

이는 런타임 증명이 아니라 정적 분석 근거입니다. Voice Notify의 실제 Windows와
macOS 훅 진입점은 PowerShell 및 POSIX shell이므로 이 Python 스냅샷의 adapter
범위 밖입니다. 이 예시는 명시적인 공유 승인을 받아 게시했으며, 생성된 export는
기호 이름과 저장소 상대 경로를 노출할 수 있습니다. 브라우저 미리보기는 GitHub에
저장된 파일을 HTML content type으로 제공하기 위해 raw.githack만 사용하며,
자체 완결형 워크벤치에는 런타임 CDN 또는 네트워크 종속성이 없습니다.

Codex는 요청된 워크플로를 수행하기 위해 기호, 개수, 저장소 상대 경로 같은 명령 출력을 처리할 수 있습니다. 이러한 플랫폼 처리는 OpenAI의 [적용 약관](https://openai.com/policies/terms-of-use/)과 [개인정보 처리방침](https://openai.com/policies/privacy-policy/)의 적용을 받습니다. 이 플러그인을 설치한다고 해서 Codex가 오프라인 제품이 되는 것은 아닙니다.

## 버전 0.5.2 지원 기능

플러그인은 다음 코드 온톨로지 워크플로를 지원합니다.

- Java 패키지, import, 타입, 메서드, 상속, 기본 종속성을 매핑합니다.
- 일반적인 Spring stereotype, `@Bean`, 생성자/필드 주입, AspectJ advice, 트랜잭션, 비동기, 캐시, 권한 부여, 재시도 프록시 신호를 인식합니다.
- Python 모듈, import, 타입, 함수, decorator, 호출, 상속과 휴리스틱 Extract/Transform/Load/Validate/Orchestrate 역할을 매핑합니다.
- 모든 관계에 추가 `evidence` array를 기록합니다. 각 항목은 안정적인
  `rule_id`, 정성적 `basis`(`direct_syntax`, `resolved_static`,
  `framework_semantic`, `name_heuristic`), `runtime_status`
  (`not_applicable` 또는 `runtime_unknown`), 선택적 저장소 상대 `path`,
  `line_start`, `line_end`, 제한된 `limitations`를 포함합니다.
- `document.quality` contract version `1.0`에서 관계 evidence coverage/count와
  Java/Python adapter status, capability, unsupported-runtime indicator를
  제공합니다. Parse warning이 0이라는 사실은 완전한 정적 또는 runtime
  coverage를 뜻하지 않습니다.
- 같은 owner의 Java call과 인식된 import type을 통한 명시적 `Type.method`
  call을 보수적으로 해석하며,
  모호한 call candidate는 관계를 만들어내지 않고 생략합니다.
- Java generic, record, 중첩 타입, 다중 interface, Spring annotation/injection 사례를 더 보수적으로 파싱하고, Python alias, 상대 import, lexical shadowing, 중첩 함수, `src/` 레이아웃 사례를 해석합니다.
- 제한된 소스, 그래프, 영향, 출력 한도를 강제합니다.
- 명시적인 workspace 범위 동의와 Ollama가 보고한 모델 메타데이터 검증 후 기존 Ollama completion 모델 하나를 선택적으로 구성하며, 결정론적 온톨로지를 변경하지 않고 정규화된 `inferred` sidecar만 저장합니다.
- 비공개 소스 fingerprint를 사용해 변경되지 않은 refresh를 건너뜁니다.
- 분석기 또는 Companion 버전이 변경되면 소스가 변경되지 않았더라도 refresh합니다.
- 변경된 저장소를 staging에서 빌드하고 불변 스냅샷을 원자적으로 승격합니다.
- 분석 또는 검증에 실패하면 마지막 정상 스냅샷을 보존합니다.
- 스냅샷을 비교하고 observed/declared/inferred/validated/approved 계보를 유지합니다.
- 전체 index 검색, 제한된 관계 lens, 사람이 읽을 수 있는 상세 정보, CDN 없는 자체 완결형 대화형 HTML 워크벤치와 이식 가능한 RDF/Turtle을 내보냅니다.
- 선택한 하나의 제한된 관계 이웃을 기본 `2D 구조` 보기와 선택형 `3D 공간`
  별자리 보기 사이에서 전환합니다. 3D는 로컬 Canvas2D perspective, 결정론적
  정적 위치, 명시적인 node/edge/frame budget을 사용하며 WebGL, package,
  worker, telemetry 또는 network 요구사항을 추가하지 않습니다.
- Pointer orbit/zoom 또는 동등한 keyboard orbit, zoom, camera reset, node
  순회·선택, root 복귀로 탐색합니다. DOM 검색, 관계 목록, 상세 패널과 2D
  그래프는 같은 node와 relation에 접근하는 정식 접근성 경로로 유지됩니다.
- Reduced-motion과 forced-colors/high-contrast 환경을 존중하고 mode·selection
  상태를 assistive technology에 제공하며, 숨겨진 탭에서 rendering을 중단하고
  canvas 실패 시 2D로 안전하게 돌아갑니다.
- 소스 fingerprint와 절대 workspace 경로를 비공개로 유지하면서 워크벤치에서 현재와 이전 스냅샷을 직접 비교합니다.
- 등록된 workspace를 읽기 전용 로컬 MCP 도구 7개로 조회합니다.
- 임의 문자열 literal을 보존하지 않고, 인식된 Java policy accessor 읽기를 그것이 보호하는 control-flow branch에 매핑합니다.
- Python 3.9 이상이 설치된 Windows, macOS, Linux에서 결정론적 분석기, 로컬 MCP 서버, 선택적 Ollama 도우미를 실행합니다.
- Target repository를 실행하지 않고 expected/prohibited node와 relation,
  evidence metadata, adapter coverage, 결정론적 output을 확인하는 실행 가능한
  golden/forbidden quality gate를 적용합니다.

버전 0.5.2에서는 변경된 저장소를 전체 재분석하고 fingerprint로 불필요한 미변경 실행을 피합니다.

## 기존 코드 역공학 사용 흐름

1. macOS/Linux에서는 `python3`, Windows에서는 `py -3`로 `doctor`와 `preflight`를 실행해 기존 코드의 지원 언어, 분석 범위, 안전 경계를 확인합니다.
2. 저장소 밖의 새 workspace를 선택하고 `init --authorized`로 소스 수준의 정적 역공학 결과를 불변 snapshot으로 생성합니다.
3. `graph.html`, RDF/Turtle, CLI `query`/`impact`/`lineage`, 읽기 전용 MCP `ontology_search`/`ontology_neighbors`로 온톨로지를 탐색합니다.
4. 코드가 바뀌면 `sync`로 새 snapshot을 만들고 `diff` 또는 `ontology_changes`로 이전 snapshot과 비교합니다.

예를 들어 macOS/Linux는 `python3 skills/manage-code-ontology/scripts/companion.py doctor ...`, Windows는 `py -3 skills\manage-code-ontology\scripts\companion.py doctor ...` 형식을 사용합니다.

## 개인정보 보호 및 안전 기본값

- 본인이 소유하거나 검사 권한이 있는 코드만 분석합니다.
- `doctor`와 `preflight`는 읽기 전용입니다.
- 초기화에는 `--authorized`와 저장소 외부의 새 workspace가 필요합니다.
- 소스 본문, 주석, 임의 문자열 literal은 보존하지 않습니다. 인식된 Java policy accessor에 전달되는 검증된 dotted policy identifier는 `PolicyLeaf` 노드로 보존될 수 있습니다.
- 비공개 로컬 구성에는 절대 저장소 경로를, 비공개 manifest에는 최신 상태 확인을 위한 파일별 크기와 SHA-256 값을 저장합니다.
- 이식 가능한 RDF, HTML, 일반 MCP 응답에서는 절대 경로와 전체 fingerprint를
  생략합니다. 관계 evidence에는 저장소 상대 경로와 line span이 포함될 수
  있으며, 이것도 기밀일 수 있습니다.
- secret으로 보이는 파일, link/reparse point, 종속성, VCS 내용, 생성된 출력은 제외합니다.
- 대상 프로젝트를 import, build, test, run하지 않습니다.
- MCP 프로세스는 stdio를 사용하고 수신 port를 열지 않으며, 임의 filesystem 경로 대신 workspace ID를 받습니다.
- daemon, graph database, local model, package, watcher를 설치하지 않습니다. Cytoscape.js와 ELK.js는 생성된 HTML 내부에 고정되어 있으며 npm 설치, CDN, browser worker, 원격 측정, network service를 사용하지 않습니다.
- 로컬 LLM 탐지는 아무것도 실행하거나 연결하거나 기록하지 않습니다. 동의한 후에만 선택 사항인 도우미가 고정 IPv4 loopback에 접속하고, Ollama가 보고한 메타데이터를 검증하고, remote/cloud 표시가 있는 응답을 거부하며, workspace 범위의 비공개 구성과 create-only inferred evidence를 작성할 수 있습니다. POSIX에서는 mode `0600`을 사용하고 Windows에서는 사용자가 선택한 workspace의 상속 ACL을 사용합니다.

기호 이름과 저장소 상대 경로도 기밀일 수 있습니다. 별도로 공유 승인을 받지 않았다면 workspace와 내보낸 결과를 로컬에 보관하세요.

## 요구 사항

- plugin과 skill을 지원하는 Codex
- Python 3.9 이상
- 타사 Python package, graph database, Java runtime, local LLM은 필요하지 않음

bundled MCP launcher는 Node.js를 사용할 수 있을 때 shell을 호출하지 않고 Python을 찾습니다. 모든 플랫폼에서 Python을 직접 실행하는 stdio 설정도 지원합니다.

## 수동 빠른 시작

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  doctor --repo "/path/to/authorized/repository"

python3 skills/manage-code-ontology/scripts/companion.py \
  preflight --repo "/path/to/authorized/repository"
```

preflight를 검토하고 로컬 artifact 생성을 승인한 후:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  init \
  --repo "/path/to/authorized/repository" \
  --workspace "/path/outside/repository/ontology-workspace" \
  --authorized
```

refresh 및 query:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  sync --workspace "/path/to/ontology-workspace"

python3 skills/manage-code-ontology/scripts/companion.py \
  query --workspace "/path/to/ontology-workspace" --term "OrderService"

python3 skills/manage-code-ontology/scripts/companion.py \
  diff --workspace "/path/to/ontology-workspace"
```

### 선택 사항: 읽기 전용 로컬 MCP

공식 Skills bundle은 [읽기 전용 로컬 MCP 설정 workflow](docs/ko/references/local-mcp.md)를 제공하고, 같은 version의 complete GitHub package는 server와 함께 제공되는 script를 제공합니다. Server는 등록된 `workspace_id`만 받는 읽기 전용 stdio 도구 7개를 제공하며 listening port를 열거나 임의 repository path를 받지 않습니다.

macOS 또는 Linux:

```toml
[mcp_servers.code-ontology-companion]
command = "python3"
args = ["/absolute/path/to/code-ontology-companion/mcp/server.py"]
```

Windows:

```toml
[mcp_servers.code-ontology-companion]
command = "py"
args = ["-3", "C:\\absolute\\path\\to\\code-ontology-companion\\mcp\\server.py"]
```

설정을 변경한 뒤 Codex를 다시 시작하거나 새 Codex process를 열고 workspace 목록, status, search를 확인합니다.

### 선택 사항: 기존 Ollama enrichment

결정론적 워크플로에는 모델이 필요하지 않습니다. 최초 관련 워크플로에서 탐지는 읽기 전용입니다. Ollama가 탐지된 경우에만 Companion이 기존 로컬 모델을 검사할지 물어야 합니다. 동의는 고정 loopback 모델 검사와 workspace 구성을 허용할 뿐 설치, 다운로드, 서버 시작, 임의 endpoint를 허용하지 않습니다. Ollama가 remote/cloud로 보고한 모델과 결과는 거부됩니다.

```bash
python3 skills/manage-code-ontology/scripts/local_llm.py detect

# Run only after the disclosure and explicit consent described in the skill.
python3 skills/manage-code-ontology/scripts/local_llm.py probe --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py configure \
  --workspace "/path/to/ontology-workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py enrich \
  --workspace "/path/to/ontology-workspace" \
  --authorized
```

도우미는 제한된 기호 메타데이터와 관찰된 관계만 전송하며, 소스 본문, 주석, 임의 문자열, secret, 절대 경로, 비공개 파일 hash는 전송하지 않습니다. 정규화된 제안은 `enrichments/<snapshot-id>/<run-id>.json`에 `inferred` evidence로 저장하며 원본 prompt와 원본 response는 보존하지 않습니다. 버전 0.5.2는 이 메타데이터를 안정적인 순서로 request당 최대 candidate 20개와 16 KiB로 나누고, model thinking을 끄며, request별 context를 8,192 token, response별 output을 2,048 token, request 시간을 최대 180초로 제한합니다. 모든 batch가 검증된 뒤에만 sidecar를 atomic하게 게시하므로 실패하거나 일부만 끝난 실행은 artifact를 남기지 않습니다. 지원하지 않거나 서로 충돌하는 role 제안은 연결하지 않고 제외 수만 기록합니다. Ollama 자체의 네트워크 동작은 Companion의 통제 밖에 있습니다. Enrichment는 선택한 모델을 실행하여 CPU/GPU 메모리를 할당할 수 있으며, 도우미는 각 응답 후 즉시 unload를 요청하도록 `keep_alive=0`을 보냅니다. `localMetadataVerified=true`는 Ollama API가 보고한 digest, size, format, model information, capability, remote-marker field가 Companion 검사를 통과했다는 뜻일 뿐입니다. 모델 weight byte, loopback 서비스의 신원, 로컬 전용 실행, Ollama outbound traffic 부재를 보증하지 않습니다. [local-llm.md](docs/ko/references/local-llm.md)를 참고하세요.

## Workspace pipeline

```text
사용 권한이 있는 소스
  -> 비공개 소스 manifest
  -> 격리된 staging 분석
  -> artifact 검증
  -> 불변 snapshot 승격
  -> current snapshot pointer
  -> RDF / 대화형 offline HTML / read-only MCP
```

각 snapshot에는 `ontology.json`, `ontology.ttl`, `report.md`, `graph.html`, `snapshot.json`, 비공개 `source-manifest.json`이 포함됩니다. workspace에는 append-only `lineage.jsonl`과 이식 가능한 `lineage.ttl`도 포함됩니다.

## RDF 이식성과 계보

핵심 vocabulary는 Explorer 1.0 `co:` namespace를 보존하므로 이전 export와 호환됩니다. 계보는 W3C PROV-O와 문서화된 Companion namespace를 사용합니다. Turtle export는 RDF 1.1 호환 store로 import할 수 있습니다. store별 index, reasoning rule, extension은 mapping이 필요할 수 있습니다.

버전 0.5.2는 기존 direct relation triple과 안정적인 identity를 보존하고,
rule, basis, source span, runtime status, limitation metadata를 위한
`RelationshipEvidence` resource를 추가합니다.

## 정적 분석 한계

그래프는 탐색과 변경 계획을 위한 evidence이지 runtime trace, security verdict, causal proof, correctness guarantee가 아닙니다. reflection, generated code, runtime Spring condition, dynamic proxy, external configuration, dependency version, Python metaprogramming 때문에 일부 관계가 완전하지 않을 수 있습니다.

변경 계획에 사용하기 전에 각 관계의 정성적 basis, runtime status,
limitations와 adapter coverage matrix를 확인하세요. `runtime_unknown` 관계는
정적 evidence이며 runtime activation의 증거가 아닙니다.

## 개발

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
python3 scripts/build_release.py
python3 scripts/build_skills_only_release.py
```

보안 문제: [SECURITY.md](docs/ko/SECURITY.md). 지원: [SUPPORT.md](docs/ko/SUPPORT.md).

## 라이선스 및 독립성

소스는 Apache-2.0으로 라이선스됩니다. 이 프로젝트는 독립적이며 OpenAI, Broadcom, VMware, Spring project, Oracle, Python Software Foundation과 제휴하거나 이들의 보증을 받지 않습니다. 제품명은 호환성을 설명하기 위해서만 사용합니다.
