# Code Ontology Companion: 현재 아키텍처와 지원 워크플로

[English](../ARCHITECTURE_AND_ROADMAP.md) | [한국어](ARCHITECTURE_AND_ROADMAP.md) | [日本語](../ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](../zh-CN/ARCHITECTURE_AND_ROADMAP.md)

## 1. 목적

Code Ontology Companion은 사용 권한이 있는 Java/Spring 및 Python 저장소를 결정론적으로 분석해 개인정보 보호를 고려한 로컬 코드 지식 그래프로 유지합니다. 버전 0.4.0는 불변 스냅샷, RDF 1.1 Turtle, PROV-O 호환 계보, 대화형 오프라인 워크벤치, 읽기 전용 로컬 MCP, 선택적 Ollama 보강을 지원합니다.

## 2. 현재 구현 원칙

- **로컬 우선:** 소스 분석, 스냅샷, 검색, 시각화, 계보를 로컬에서 처리합니다.
- **결정론적 핵심:** 같은 입력과 버전은 같은 정규화 결과를 생성합니다.
- **불변 이력:** 새 분석은 새 스냅샷으로 게시되며 이전 스냅샷과 계보를 보존합니다.
- **읽기 전용 검색:** MCP는 등록된 workspace ID만 받고 조회 도구만 제공합니다.
- **명시적 동의:** 초기화와 선택적 Ollama 연결은 데이터 범위 공개와 승인을 요구합니다.
- **정적 증거:** 관계, 영향, 비교 결과는 정적 구조 증거로 분류합니다.

## 3. 현재 구현 아키텍처

```text
사용 권한이 있는 Java/Spring 또는 Python 저장소
  -> read-only doctor / preflight
  -> 안전한 source manifest와 제한된 정적 분석
  -> staging artifact 검증
  -> immutable snapshot의 atomic promotion
  -> ontology.json / ontology.ttl / report.md / graph.html
  -> append-only lineage.jsonl / portable lineage.ttl
  -> CLI 및 read-only local MCP query
  -> 선택적 fixed-loopback Ollama inferred sidecar
```

### 분석기

분석기는 Python standard library만 사용합니다. `.java`와 `.py` regular file을 제한된 크기와 개수 범위에서 읽고 target repository를 import, compile, build, test, run하지 않습니다. Java package/import/type/method/inheritance, Spring stereotype/bean/injection/AOP/proxy 신호, Python module/import/type/function/decorator/call/inheritance 및 heuristic pipeline role을 추출합니다.

### 스냅샷과 계보

각 스냅샷은 운영 검색용 JSON, 이식 가능한 RDF 1.1 Turtle, 요약 report, 자체 완결형 HTML workbench, private source manifest를 포함합니다. workspace 계보는 observed, declared, inferred, validated, approved evidence를 구분해 append-only JSONL과 Turtle로 유지합니다.

### 오프라인 워크벤치

워크벤치는 full portable index를 검색하고 선택한 관계 neighborhood만 화면에 materialize합니다. architecture, Spring, policy, pipeline, change lens와 current/previous 비교를 제공하며 Cytoscape.js와 ELK.js를 로컬 asset으로 사용합니다.

### 읽기 전용 로컬 MCP

stdio MCP 서버는 workspace 목록, status, symbol search, bounded neighbors, history, snapshot changes, lineage 조회를 위한 7개 도구를 제공합니다. listening port를 열지 않고 임의 filesystem path 대신 등록된 `workspace_id`를 받습니다. Python 3.9 이상이 설치된 Windows, macOS, Linux에서 직접 Python stdio 설정을 사용할 수 있습니다.

### 선택적 로컬 LLM

사용자가 명시적으로 동의하면 별도 helper가 기존 Ollama의 고정 IPv4 loopback `127.0.0.1:11434`에만 접속합니다. helper는 제한된 portable ontology metadata를 결정적으로 분할해 보내고 정규화된 제안을 별도 `inferred` sidecar로 원자적으로 저장합니다. observed ontology와 RDF는 변경하지 않습니다.

## 4. 지원 기능

| 영역 | 버전 0.4.0 지원 기능 |
| --- | --- |
| 입력 | 사용 권한이 있는 regular `.java`, `.py` 파일 |
| Java/Spring | 구조, generic/record/nested type, inheritance, annotation, bean, injection, AOP/proxy signal |
| Python | module, symbol, import, call, inheritance, decorator, nested scope, pipeline role |
| Ontology | JSON index, RDF 1.1 Turtle, 안정적인 `co:` vocabulary |
| Provenance | PROV-O 호환 append-only lineage와 구분된 evidence type |
| Refresh | private fingerprint, stable manifest, staging validation, full reanalysis, atomic promotion |
| Search | CLI, offline workbench, 7개 read-only local MCP tool |
| Visualization | full-index search, bounded relation lens, current/previous comparison |
| Local LLM | 기존 Ollama 탐지, 동의 기반 model 선택, bounded batching, atomic inferred sidecar |
| Platform | Python 3.9+를 사용하는 Windows, macOS, Linux |

## 5. 데이터 및 실행 경계

분석기는 secret처럼 보이는 이름, link/reparse point, special file, VCS, dependency, generated output, cache path를 건너뜁니다. Portable RDF, HTML, MCP response에는 absolute repository path와 full source fingerprint를 넣지 않습니다. 로컬 LLM payload에는 source body, comment, credential, absolute path, private manifest, raw file hash를 넣지 않습니다.

분석기, workspace CLI, workbench, launcher, MCP는 direct network request를 만들지 않습니다. 선택적 Ollama helper만 동의 후 고정 loopback endpoint를 사용합니다. 플러그인은 Python, Java, model, graph database, package manager, daemon, watcher를 자동으로 설치하지 않습니다.

## 6. 해석 한계

정적 graph는 runtime trace, active dependency-injection container, vulnerability verdict, causal proof가 아닙니다. Reflection, generated code, runtime condition, dynamic proxy, external configuration, dependency version, Python metaprogramming 때문에 일부 관계가 완전하지 않을 수 있습니다. 표시되는 parse warning과 evidence type을 함께 확인하고 runtime 사실은 별도 runtime evidence로 검증해야 합니다.

RDF/Turtle은 RDF 1.1-compatible store로 이식할 수 있습니다. Store별 index, reasoning rule, authentication, extension은 해당 store의 구성에 맞게 mapping합니다.
