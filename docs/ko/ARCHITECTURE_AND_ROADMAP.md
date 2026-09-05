# Code Ontology Companion: 현재 아키텍처와 지원 워크플로

[English](../ARCHITECTURE_AND_ROADMAP.md) | [한국어](ARCHITECTURE_AND_ROADMAP.md) | [日本語](../ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](../zh-CN/ARCHITECTURE_AND_ROADMAP.md)

이 문서는 0.6.1 공개 후보의 구현을 설명합니다. 배포·공개 완료를 뜻하지 않습니다.

## 1. 목적

Code Ontology Companion은 사용 권한이 있는 Java/Spring 및 Python 저장소를 결정론적으로 분석해 개인정보 보호를 고려한 로컬 코드 지식 그래프로 유지합니다. 버전 0.6.1는 불변 스냅샷, 근거가 명시된 관계, adapter coverage, RDF 1.1 Turtle, PROV-O 호환 계보, 3D 공간 지도를 기본으로 하고 선택적 평면/텍스트 대안을 갖춘 오프라인 워크벤치, 읽기 전용 로컬 MCP, 선택적 Ollama 보강을 지원합니다.

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

분석기는 Python standard library만 사용합니다. `.java`와 `.py` regular file을 제한된 크기와 개수 범위에서 읽고 target repository를 import, compile, build, test, run하지 않습니다. Java package/import/type/method/inheritance, Spring stereotype/bean/injection/AOP/proxy 신호, Python module/import/type/function/decorator/call/inheritance 및 heuristic pipeline role을 추출합니다. Java의 unqualified call 또는 `this.method(...)`는 같은 owner에서 method name과 argument count가 일치하는 candidate가 정확히 하나일 때만 해석합니다. 인식된 imported `Type.method(...)`는 `ExternalCallable`로 기록하며, 같은 arity overload와 dynamic receiver는 보수적으로 생략합니다.

### 관계 evidence와 adapter coverage

버전 0.6.1는 기존 `source`/`target`/`type` relation triple과 안정적인 identity를 보존합니다. 각 relation의 추가 `evidence` array에는 안정적인 `rule_id`, 정성적 `basis`(`direct_syntax`, `resolved_static`, `framework_semantic`, `name_heuristic`), `runtime_status`(`not_applicable`, `runtime_unknown`), 선택적 저장소 상대 `path`/`line_start`/`line_end`, 제한된 `limitations`가 들어갑니다.

`document.quality` contract version `1.0`은 `relationship_evidence`의 `total_edges`, `documented_edges`, `missing_evidence`, `coverage_percent`, `basis_counts`, `runtime_status_counts`와 Java/Python adapter의 `status`, `detected`, `capabilities`, `unsupported_runtime`을 보고합니다. 두 adapter는 항상 표시되며 `detected`가 해당 언어의 실제 존재 여부를 구분합니다. 정성적 basis는 숫자 확률이 아니며 parse warning 0건은 완전한 정적 또는 runtime coverage의 증거가 아닙니다. RDF는 기존 direct triple을 유지하고 추가 `RelationshipEvidence` resource로 이 metadata를 표현합니다.

### 스냅샷과 계보

각 스냅샷은 운영 검색용 JSON, 이식 가능한 RDF 1.1 Turtle, 요약 report, 자체 완결형 HTML workbench, private source manifest를 포함합니다. workspace 계보는 observed, declared, inferred, validated, approved evidence를 구분해 append-only JSONL과 Turtle로 유지합니다.

### 오프라인 워크벤치

0.6.1 후보의 HTML은 `구조 / 영향 / 변경` 세 메뉴와 3D 공간 지도로 시작합니다. 실제 모듈 소유 관계와 소스 폴더를 기준으로 최대 12개 그룹, 160개 심볼을 균형 있게 표시하고 전체 인덱스 검색을 유지합니다. 선택하면 카메라가 해당 심볼에 초점을 맞추고 근거 패널이 열립니다. 평면 보기는 보기 옵션에 있으며 텍스트 관계 목록도 같은 제한된 그래프를 탐색합니다. 내장 Canvas2D perspective를 사용하고 CDN, WebGL, package, worker, telemetry, network를 추가하지 않습니다.

영향은 CLI와 같은 의존 관계 및 generic concept 제외 규칙에 따른 정적 후보입니다. 변경은 공통 canonical diff의 `edgesModified`와 이전/현재 근거를 소비합니다. 링크는 snapshot/entity/relationship/evidence ID를 검증하고, 다른 스냅샷이나 무관한 근거는 거부합니다. 공간상의 거리나 장식 링은 실행 순서·실시간 흐름을 뜻하지 않습니다.

Pointer orbit/zoom에는 keyboard orbit, zoom, camera reset, node 순회·선택, root 복귀 대안이 있습니다. 검색, DOM 관계 목록, 상세 패널과 2D graph는 screen reader를 포함한 동등 탐색 경로입니다. Workbench는 reduced-motion과 forced-colors/high-contrast를 존중하고 mode·selection 상태를 assistive technology에 제공하며 숨겨진 탭에서는 rendering을 멈추고 canvas 실패 시 2D로 돌아갑니다. 이는 WCAG 2.2 AA 지향 설계 계약이며 별도의 수동 AT/browser 검증 없는 포괄적 준수 주장은 아닙니다.

### 읽기 전용 로컬 MCP

stdio MCP 서버는 workspace 목록, status, symbol search, bounded neighbors, history, snapshot changes, lineage 조회를 위한 7개 도구를 제공합니다. listening port를 열지 않고 임의 filesystem path 대신 등록된 `workspace_id`를 받습니다. Python 3.9 이상이 설치된 Windows, macOS, Linux에서 직접 Python stdio 설정을 사용할 수 있습니다.

### 선택적 로컬 LLM

사용자가 명시적으로 동의하면 별도 helper가 기존 Ollama의 고정 IPv4 loopback `127.0.0.1:11434`에만 접속합니다. helper는 제한된 portable ontology metadata를 결정적으로 분할해 보내고 정규화된 제안을 별도 `inferred` sidecar로 원자적으로 저장합니다. observed ontology와 RDF는 변경하지 않습니다.

## 4. 지원 기능

| 영역 | 버전 0.6.1 지원 기능 |
| --- | --- |
| 입력 | 사용 권한이 있는 regular `.java`, `.py` 파일 |
| Java/Spring | 구조, generic/record/nested type, inheritance, annotation, bean, injection, AOP/proxy signal |
| Python | module, symbol, import, call, inheritance, decorator, nested scope, pipeline role |
| Ontology | JSON index, additive relation evidence, adapter coverage, legacy-compatible RDF 1.1 Turtle, 안정적인 `co:` vocabulary |
| Provenance | PROV-O 호환 append-only lineage와 구분된 evidence type |
| Refresh | private fingerprint, stable manifest, staging validation, full reanalysis, atomic promotion |
| Search | CLI, offline workbench, 7개 read-only local MCP tool |
| Visualization | full-index search, 기본 Canvas2D 3D 공간 지도, 선택적 평면/텍스트 대안, 구조/영향/변경, keyboard/pointer control, reduced motion/high contrast, current/previous comparison |
| Local LLM | 기존 Ollama 탐지, 동의 기반 model 선택, bounded batching, atomic inferred sidecar |
| Platform | Python 3.9+를 사용하는 Windows, macOS, Linux |

## 5. 데이터 및 실행 경계

분석기는 secret처럼 보이는 이름, link/reparse point, special file, VCS, dependency, generated output, cache path를 건너뜁니다. Portable RDF, HTML, MCP response에는 absolute repository path와 full source fingerprint를 넣지 않습니다. 로컬 LLM payload에는 source body, comment, credential, absolute path, private manifest, raw file hash를 넣지 않습니다.

분석기, workspace CLI, workbench, launcher, MCP는 direct network request를 만들지 않습니다. 선택적 Ollama helper만 동의 후 고정 loopback endpoint를 사용합니다. 플러그인은 Python, Java, model, graph database, package manager, daemon, watcher를 자동으로 설치하지 않습니다.

## 6. 해석 한계

정적 graph는 runtime trace, active dependency-injection container, vulnerability verdict, causal proof가 아닙니다. Reflection, generated code, runtime condition, dynamic proxy, external configuration, dependency version, Python metaprogramming 때문에 일부 관계가 완전하지 않을 수 있습니다. 표시되는 parse warning과 evidence type을 함께 확인하고 runtime 사실은 별도 runtime evidence로 검증해야 합니다.

RDF/Turtle은 RDF 1.1-compatible store로 이식할 수 있습니다. Store별 index, reasoning rule, authentication, extension은 해당 store의 구성에 맞게 mapping합니다.

## 7. 현재 로드맵

이 로드맵은 방향을 나타내며 날짜를 약속하지 않습니다. 0.5.x는 v0.3.4 아키텍처 로드맵의 대규모 시각화 방향을 제한된 오프라인 탐색으로 발전시키며, 선택적 storage/query는 future work로 구분합니다.

0.5.0부터 bounded Java/Python adapter coverage, 정성적 static evidence basis, unsupported-runtime indicator, source-attributed relation evidence, 보수적인 Java call, ontology quality gate, 그리고 같은 제한된 이웃을 공유하는 기본 2D/선택형 Canvas2D 3D와 visualization quality gate가 포함됩니다.

0.6.1 후보는 3D를 기본으로 바꾸고 구조/영향/변경, 모듈 그룹, 근거 링크, 실제 더 보기, 공통 변경 비교를 제공합니다. 시각화 gate는 정적 계약 검사이며 브라우저 시각·접근성 검증을 대신하지 않습니다.

향후 방향은 setup 진단/progress/actionable failure, foreground watcher debouncing/single-flight, quality fixture로 정당화된 bounded parser/language adapter, 선택적 RDF store/SPARQL/large-graph profile, 별도 범위의 build/config/authenticated read-only runtime evidence adapter입니다. 새 언어, graph database, SPARQL/REST profile, whole-repository 3D, target 실행, live runtime tracing, autonomous code change/deployment, security verdict, local-LLM inference의 observed evidence 승격은 버전 0.6.1 기능이 아닙니다.
