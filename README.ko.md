# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[전체 아키텍처 및 로드맵](docs/ko/ARCHITECTURE_AND_ROADMAP.md)

Code Ontology Companion은 사용 권한이 있는 Java/Spring 또는 Python 저장소의 개인정보 보호를 고려한 로컬 지식 그래프를 유지 관리하는 독립형 Codex 플러그인입니다.

결정론적 정적 분석, 불변 스냅샷, RDF 1.1 Turtle 내보내기, PROV-O 호환 계보, 대화형 오프라인 워크벤치를 결합합니다. Full/local GitHub 프로필에는 읽기 전용 로컬 MCP 서버도 포함됩니다. 결정론적 분석기와 MCP 서버는 대상 코드를 실행하거나, 소프트웨어를 설치하거나, 원격 측정 데이터를 전송하거나, 네트워크 요청을 하지 않습니다. 선택 사항인 별도 승인 도우미는 제한된 이식 가능 온톨로지 메타데이터를 고정 루프백 주소 `127.0.0.1:11434`의 기존 Ollama 서비스로 보낼 수 있으며, 검증되지 않은 제안은 관찰된 그래프 외부에 유지됩니다.

Codex는 요청된 워크플로를 수행하기 위해 기호, 개수, 저장소 상대 경로 같은 명령 출력을 처리할 수 있습니다. 이러한 플랫폼 처리는 OpenAI의 [적용 약관](https://openai.com/policies/terms-of-use/)과 [개인정보 처리방침](https://openai.com/policies/privacy-policy/)의 적용을 받습니다. 이 플러그인을 설치한다고 해서 Codex가 오프라인 제품이 되는 것은 아닙니다.

## 버전 0.3.4 공개 Skills-only 기능

OpenAI에 제출하는 공개 Skills-only 프로필은 아래의 범용 온톨로지 워크플로만 포함합니다. AETHER Lab `runtime-binding` 명령과 구현 코드, 프로젝트 전용 정책 스키마, 영수증 생성기, 프로젝트 전용 평가 사례는 공개 제출물에 포함하거나 공개 기능으로 홍보하지 않습니다.

- Java 패키지, import, 타입, 메서드, 상속, 기본 종속성을 매핑합니다.
- 일반적인 Spring stereotype, `@Bean`, 생성자/필드 주입, AspectJ advice, 트랜잭션, 비동기, 캐시, 권한 부여, 재시도 프록시 신호를 인식합니다.
- Python 모듈, import, 타입, 함수, decorator, 호출, 상속과 휴리스틱 Extract/Transform/Load/Validate/Orchestrate 역할을 매핑합니다.
- Java generic, record, 중첩 타입, 다중 interface, Spring annotation/injection 사례를 더 보수적으로 파싱하고, Python alias, 상대 import, lexical shadowing, 중첩 함수, `src/` 레이아웃 사례를 해석합니다.
- 제한된 소스, 그래프, 영향, 출력 한도를 강제합니다.
- 명시적인 workspace 범위 동의와 Ollama가 보고한 모델 메타데이터 검증 후 기존 Ollama completion 모델 하나를 선택적으로 구성하며, 결정론적 온톨로지를 변경하지 않고 정규화된 `inferred` sidecar만 저장합니다.
- 비공개 소스 fingerprint를 사용해 변경되지 않은 refresh를 건너뜁니다.
- 분석기 또는 Companion 버전이 변경되면 소스가 변경되지 않았더라도 refresh합니다.
- 변경된 저장소를 staging에서 빌드하고 불변 스냅샷을 원자적으로 승격합니다.
- 분석 또는 검증에 실패하면 마지막 정상 스냅샷을 보존합니다.
- 스냅샷을 비교하고 observed/declared/inferred/validated/approved 계보를 유지합니다.
- 전체 index 검색, 제한된 관계 lens, 사람이 읽을 수 있는 상세 정보, CDN 없는 자체 완결형 대화형 HTML 워크벤치와 이식 가능한 RDF/Turtle을 내보냅니다.
- 소스 fingerprint와 절대 workspace 경로를 비공개로 유지하면서 워크벤치에서 현재와 이전 스냅샷을 직접 비교합니다.
- 임의 문자열 literal을 보존하지 않고, 인식된 Java policy accessor 읽기를 그것이 보호하는 control-flow branch에 매핑합니다.

Full/local GitHub 프로필에는 등록된 workspace를 조회하는 읽기 전용 로컬 MCP 도구 7개와 아래에 설명한 선택적 프로젝트 확장이 별도로 유지됩니다. 이 확장은 OpenAI 호스팅 기능이 아니며 runtime, policy, order, funds에 대한 어떤 권한도 부여하지 않습니다.

버전 0.3.4에서는 변경된 저장소를 전체 재분석합니다. fingerprint는 불필요한 미변경 실행을 피하지만, 파일별 증분 파싱은 향후 최적화 대상입니다.

## 개인정보 보호 및 안전 기본값

- 본인이 소유하거나 검사 권한이 있는 코드만 분석합니다.
- `doctor`와 `preflight`는 읽기 전용입니다.
- 초기화에는 `--authorized`와 저장소 외부의 새 workspace가 필요합니다.
- 소스 본문, 주석, 임의 문자열 literal은 보존하지 않습니다. 인식된 Java policy accessor에 전달되는 검증된 dotted policy identifier는 `PolicyLeaf` 노드로 보존될 수 있습니다.
- 비공개 로컬 구성에는 절대 저장소 경로를, 비공개 manifest에는 최신 상태 확인을 위한 파일별 크기와 SHA-256 값을 저장합니다.
- 이식 가능한 RDF, HTML, full/local 프로필의 일반 MCP 응답에서는 절대 경로와 전체 fingerprint를 생략합니다.
- secret으로 보이는 파일, link/reparse point, 종속성, VCS 내용, 생성된 출력은 제외합니다.
- 대상 프로젝트를 import, build, test, run하지 않습니다.
- Full/local 프로필의 MCP 프로세스는 stdio를 사용하고 수신 port를 열지 않으며, 임의 filesystem 경로 대신 workspace ID를 받습니다.
- daemon, graph database, local model, package, watcher를 설치하지 않습니다. Cytoscape.js와 ELK.js는 생성된 HTML 내부에 고정되어 있으며 npm 설치, CDN, browser worker, 원격 측정, network service를 사용하지 않습니다.
- 로컬 LLM 탐지는 아무것도 실행하거나 연결하거나 기록하지 않습니다. 동의한 후에만 선택 사항인 도우미가 고정 IPv4 loopback에 접속하고, Ollama가 보고한 메타데이터를 검증하고, remote/cloud 표시가 있는 응답을 거부하며, workspace 범위 mode-`0600` 구성과 create-only inferred evidence를 작성할 수 있습니다.

기호 이름과 저장소 상대 경로도 기밀일 수 있습니다. 별도로 공유 승인을 받지 않았다면 workspace와 내보낸 결과를 로컬에 보관하세요.

## 요구 사항

- plugin과 skill을 지원하는 Codex; full/local MCP를 사용할 때는 bundled MCP 지원도 필요
- Python 3.9 이상
- 타사 Python package, graph database, Java runtime, local LLM은 필요하지 않음

Full/local 프로필의 MCP launcher는 지원되는 Codex plugin host가 제공하는 JavaScript runtime을 사용하여 shell을 호출하지 않고 Python을 찾습니다.

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

도우미는 제한된 기호 메타데이터와 관찰된 관계만 전송하며, 소스 본문, 주석, 임의 문자열, secret, 절대 경로, 비공개 파일 hash는 전송하지 않습니다. 정규화된 제안은 `enrichments/<snapshot-id>/<run-id>.json`에 `inferred` evidence로 저장합니다. 원본 prompt와 원본 response는 보존하지 않습니다. Ollama 자체의 네트워크 동작은 Companion의 통제 밖에 있습니다. Enrichment는 선택한 모델을 실행하여 CPU/GPU 메모리를 할당할 수 있으며, 도우미는 각 응답 후 즉시 unload를 요청하도록 `keep_alive=0`을 보냅니다. `localMetadataVerified=true`는 Ollama API가 보고한 digest, size, format, model information, capability, remote-marker field가 Companion 검사를 통과했다는 뜻일 뿐입니다. 모델 weight byte, loopback 서비스의 신원, 로컬 전용 실행, Ollama outbound traffic 부재를 보증하지 않습니다. [local-llm.md](docs/ko/references/local-llm.md)를 참고하세요.

### Full/local GitHub 프로필 전용 선택 확장: AETHER Lab runtime binding

이 하위 프로젝트 전용 로컬 CLI 작업은 full/local GitHub 프로필에만 유지되며 공개 Skills-only/OpenAI 제출물에는 명령, 구현, 프로젝트 전용 정책 스키마, 영수증 생성기, 평가 사례가 들어 있지 않습니다. OpenAI가 호스팅하거나 실행하는 기능이 아니며 읽기 전용 MCP 서버를 통해서도 노출되지 않습니다. 버전 0.3.4의 full/local 프로필은 Windows가 아닌 macOS/POSIX에서 이 정확한 mode-`0400` receipt를 지원합니다. 최신 current snapshot, 지원되는 policy leaf, 중복이 없는 정확한 로컬 JSON 또는 `policy-json` 문서, source repository 외부의 새 output path, 명시적 승인이 필요합니다.

```bash
mkdir -m 700 "/private/path/runtime-bindings"

python3 skills/manage-code-ontology/scripts/companion.py \
  runtime-binding \
  --workspace "/path/to/ontology-workspace" \
  --policy-leaf "strategy.exits.timeStopMinutes" \
  --policy-document "/path/to/authorized/repository/policies/policy.md" \
  --output "/private/path/runtime-bindings/time-stop.json" \
  --authorized
```

출력은 `aether.runtime-effective-ontology-binding/v1`을 정확히 구현합니다. 즉, canonical JSON과 LF 하나, self-hash, 명령이 반환하는 외부 file hash, 정렬 및 hash 처리된 ontology-edge reference, 고정된 source/snapshot hash, 정확한 false authority, create-only publication, mode `0400`입니다.

이 receipt에서 `runtimeEffective=true`의 의미는 하나로 제한됩니다. 고정된 active source에서 지정된 leaf가 정적 분석상 production control-flow branch에 도달하며, 제공된 policy 문서에 그 leaf를 비활성화하는 알려진 AETHER shadow/enable condition이 없다는 뜻입니다. producer는 active source로부터 그래프를 다시 빌드하고 snapshot과 정확한 node/edge 일치를 요구합니다. test/fixture 전용 경로, stale source, 사용되지 않는 read, 활성 stop-loss/take-profit ladder, 비활성 trailing, 모호한 path, 변경된 output은 fail closed 처리됩니다.

이는 branch 실행, order 제출, policy 안전성, 수익 변화를 **증명하지 않습니다**. candidate 생성, gate, approval, promotion, policy write, order, network, runtime write, funds authority를 부여하지 않습니다. v1 receipt는 Lab의 정확한 schema를 깨지 않고서는 policy-document hash를 포함할 수 없으므로, 이를 소비하는 Lab은 사용 시점에 정확한 baseline policy와 shadow condition을 독립적으로 다시 확인해야 합니다.

## Workspace pipeline

```text
사용 권한이 있는 소스
  -> 비공개 소스 manifest
  -> 격리된 staging 분석
  -> artifact 검증
  -> 불변 snapshot 승격
  -> current snapshot pointer
  -> RDF / 대화형 offline HTML / full/local read-only MCP
```

각 snapshot에는 `ontology.json`, `ontology.ttl`, `report.md`, `graph.html`, `snapshot.json`, 비공개 `source-manifest.json`이 포함됩니다. workspace에는 append-only `lineage.jsonl`과 이식 가능한 `lineage.ttl`도 포함됩니다.

## RDF 이식성과 계보

핵심 vocabulary는 Explorer 1.0 `co:` namespace를 보존하므로 이전 export와 호환됩니다. 계보는 W3C PROV-O와 문서화된 Companion namespace를 사용합니다. Turtle export는 RDF 1.1 호환 store로 import할 수 있습니다. store별 index, reasoning rule, extension은 mapping이 필요할 수 있습니다.

## 정적 분석 한계

그래프는 탐색과 변경 계획을 위한 evidence이지 runtime trace, security verdict, causal proof, correctness guarantee가 아닙니다. Full/local 전용 runtime-binding receipt는 정적 source reachability와 알려진 policy shadowing만 좁혀 줍니다. runtime 실행이나 결과 인과관계를 확립하지 않습니다. reflection, generated code, runtime Spring condition, dynamic proxy, external configuration, dependency version, Python metaprogramming은 불완전할 수 있습니다.

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
