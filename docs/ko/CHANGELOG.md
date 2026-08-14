# 변경 이력

[English](../../CHANGELOG.md) | [한국어](CHANGELOG.md) | [日本語](../ja/CHANGELOG.md) | [简体中文](../zh-CN/CHANGELOG.md)

## 0.5.2 - 2026-08-15

- 완전한 러시아어 제품 README를 추가하고 영어, 한국어, 일본어, 중국어 간체,
  러시아어 루트 가이드 모두에 동일한 5개 언어 전환 링크를 적용했습니다.
- 표준 언어 전환 링크, 공통 기능·안전 마커, 동일한 명령 예제 구조로 루트 README
  정합성을 검증합니다. 상대 언어 링크가 로컬에서 유효하도록 complete GitHub
  package에 5개 루트 가이드를 모두 포함하면서 기존 4개 언어 전체 문서 매트릭스와
  Skills-only 경계는 유지합니다.
- 릴리스 메타데이터, 런타임 버전 마커, SBOM 날짜, 평가 메타데이터, CI artifact
  이름, validator, test, submission 문서를 동기화했습니다. 공개된 v0.5.1 tag와
  artifact는 그대로 유지하며 analyzer semantics, ontology schema, permission,
  privacy boundary, dependency는 변경하지 않았습니다.

## 0.5.1 - 2026-08-13

- 공식 Skills-only manifest에 rule-attributed relationship evidence와 제한된
  Java/Python adapter coverage를 명시해 canonical listing과 정렬했습니다.
- 함께 제공되는 skill agent metadata를 접근 가능한 기본 2D/선택형 3D
  workbench 및 evidence/coverage workflow와 정렬했습니다.
- 공개된 v0.5.0 tag와 artifact는 변경하지 않습니다. 이 patch는 release
  metadata만 변경하며 analyzer semantics, ontology schema, visualization
  behavior, 권한·privacy 경계, vendored dependency는 그대로입니다.

## 0.5.0 - 2026-08-13

- 기존 2D 보기에 표시되는 것과 동일한 제한된 관계 이웃을 선택형 대화형
  **3D 별자리** 보기로 탐색할 수 있습니다. 2D는 기본값이자 상시 fallback이며,
  두 보기는 선택한 심볼, 온톨로지 identity, 관계 evidence, 상세 정보, 필터와
  한계를 함께 사용합니다.
- `graph.html`에 이미 포함된 결정론적 데이터와 브라우저 내장 canvas API만으로
  3D projection을 로컬에서 렌더링합니다. CDN, package, WebGL, worker, telemetry,
  network 요구사항을 추가하지 않으며 graph database, SPARQL, runtime tracing
  지원을 주장하지 않습니다.
- Pointer orbit/zoom과 keyboard orbit, zoom, camera reset, node 순회·선택,
  root 복귀를 지원합니다. Reduced-motion과 forced-colors/high-contrast 환경을
  존중하고, 상태와 도움말을 assistive technology에 제공하며, 숨겨진 탭에서는
  렌더링을 멈추고 canvas 사용이 불가능하면 keyboard-accessible 2D 보기로
  안전하게 돌아갑니다.
- 전체 저장소 그래프를 한 번에 표시하지 않고 선택한 관계 이웃으로 시각화를
  제한합니다.

- 모든 생성 관계의 `evidence` array에 안정적인 `rule_id`, 정성적 `basis`,
  `runtime_status`, 선택적 저장소 상대 `path`와 line span, 제한된
  `limitations`를 기록합니다. 호환 가능한 consumer를 위해 기존 relation
  triple과 node/edge identity는 유지합니다.
- Versioned `document.quality` contract와 제한된 Java/Python adapter coverage
  matrix를 제공해 snapshot, report, query, offline workbench, read-only MCP 결과가 supported,
  partial, heuristic, runtime-unknown 영역을 구분하도록 제한된 Java/Python
  adapter coverage matrix를 제공합니다. Parse warning이 없다는 사실을 완전한
  coverage의 증거로 취급하지 않습니다.
- 같은 owner의 method 및 인식된 import type을 통한 명시적 `Type.method`
  Java call을 보수적으로
  해석하고, 모호한 candidate는 관계를 만들어내지 않고 생략합니다.
- Expected/prohibited node와 relation, evidence metadata, coverage, 결정론적
  동작을 확인하는 실행 가능한 golden/forbidden ontology quality gate를
  추가합니다. 이 gate는 target repository를 실행하지 않습니다.
- Python standard library 기반 zero-dependency analyzer, 안정적인 RDF
  vocabulary, immutable snapshot, target-code 미실행과 direct-network 차단
  경계, 별도 동의 기반 inferred Ollama sidecar를 유지합니다.

## 0.4.0 - 2026-08-10

- 제품, 정책, 제출, 아키텍처, 참고 및 현지화 문서를 현재 지원하는 범용
  온톨로지 워크플로 중심으로 정리하고 기존 프로젝트 전용 명령, 구현, 테스트,
  평가 사례를 제거했습니다.
- 권한 있는 기존 Java/Spring 또는 Python 코드를 source-level static reverse
  engineering으로 불변 JSON, RDF/Turtle, 계보 및 대화형 오프라인 온톨로지로
  구성하고 갱신·비교하는 사용법을 추가했습니다.
- 공식 Skills 번들에 Windows, macOS, Linux용 선택적 읽기 전용 로컬 MCP 설정
  가이드와 프롬프트를 포함하고, 전체 GitHub 패키지에는 동일 버전의 서버와
  런처를 제공합니다.
- Windows에서 Python 3.9 이상을 실제로 확인하고 MCP stdio를 UTF-8로 고정하며,
  스냅샷·스테이징·릴리스 소스의 링크 및 reparse point를 fail closed 처리합니다.
- 로컬 Ollama 프롬프트의 역할 목록을 정규 스키마와 동기화하고 `Validate` 역할과
  0.3.5의 제한된 결정론적 배치 처리를 유지합니다.

## 0.3.5 - 2026-08-03

- 선택적 로컬 Ollama 보강을 결정적으로 분할하여 각 요청이 최대 후보
  20개와 직렬화된 이식 가능 메타데이터 16 KiB 이하만 포함하도록 했습니다.
- 모델 사고를 비활성화하고 요청별 컨텍스트를 8,192토큰, 응답당 출력 토큰을
  2,048개로 제한하며, 지원되는 로컬 하드웨어에서 제한된 보강이 완료될 수
  있도록 요청당 최대 180초를 허용합니다.
- 모든 배치를 검증한 뒤 하나의 inferred 사이드카를 원자적으로 게시합니다.
  실패하거나 완료되지 않은 부분 실행은 보강 산출물을 남기지 않습니다. 허용된
  역할 vocabulary와 일치하는 제안만 연결하고, 같은 역할의 중복에는 더 낮은
  confidence를 사용하며 역할이 충돌하는 node는 분리합니다.

## 0.3.4 - 2026-08-02

- Java/Spring/Python 분석, snapshot, RDF, lineage, workbench, read-only local MCP 및 선택적 Ollama 기능 설명을 제품, 운영, 안전, 개인정보 보호, 제출, 참조 문서 전반에서 동기화합니다.
- 릴리스 artifact와 추출된 CLI를 결정적으로 검증하는 fail-closed validation을 강화합니다.

## 0.3.3 - 2026-08-02

- 버전 0.3.2를 변경되지 않은 기능 기준선으로 유지하면서 전체 로컬 우선 아키텍처와 단계별 버전 로드맵을 공개합니다.
- 사람이 읽는 모든 제품, 운영, 안전, 정책, 제출, 참고 문서에 영어, 한국어, 일본어, 중국어 간체 진입점과 번역을 추가합니다.
- 영어 라이선스 및 정책 문서를 권위 있는 원문으로 보존하고, 법률 번역을 정보 제공용으로 표시하며, source package에서 문서 언어 parity를 검증합니다.

## 0.3.2 - 2026-08-02

- 추적되는 모든 릴리스 변경에 새 semantic version과 날짜가 적힌 changelog 항목을 요구하고, baseline-aware CI enforcement, 동기화된 metadata, deterministic artifact를 적용합니다.
- 최종 source state에서 plugin의 등록된 self-ontology를 refresh하고 declared 및 validated lineage를 기록하는 release checklist를 추가합니다.
- patch release 전반에서 호환되고 동의를 받은 local-LLM workspace configuration을 보존하면서 malformed 또는 future-version provenance는 거부합니다.

## 0.3.1 - 2026-08-01

- generic 및 record 선언, multi-interface hierarchy, nested import, 검증된 Spring annotation, same-package wildcard shadowing, compact/generic constructor detection, conservative constructor injection, `@Bean` parameter injection에 대한 결정론적 Java 정확도를 개선합니다.
- relative 및 aliased import, internal call, lexical shadowing, nested function, 명시적인 `self`/`cls` call, `src/` layout, comprehension scope, 제한된 AST depth/count, token 기반 pipeline-role classification에 대한 Python 정확도를 개선합니다.
- fail-closed source, graph, impact, output resource limit를 추가합니다.
- 명시적 동의 후 선택적으로 workspace 범위 Ollama enrichment를 추가합니다. 고정 IPv4 loopback만 사용하고, 보고된 cloud/remote marker나 필수 metadata 누락을 거부하고, 제한된 이식 가능 metadata subset을 전송하고, `keep_alive=0`으로 즉시 model unload를 요청하며, observed ontology evidence를 변경하지 않고 create-only `inferred` sidecar를 저장합니다.
- Git revision metadata read와 제한된 MCP response contract를 강화합니다.
- 추출 후 smoke check를 포함하여 release archive에 대한 정확하고 재현 가능한 validation을 추가합니다.
- platform 전반의 text checkout을 정규화하고, file identity, size, mtime guard를 유지하면서 Windows file-change check를 Python 3.12와 호환되게 합니다.

## 0.3.0 - 2026-07-31

- ID 순서 ring graph를 자체 완결형 대화형 ontology workbench로 교체합니다. full-index search, 제한된 relationship lens, guided exploration, 사람이 읽을 수 있는 상세 정보, current-versus-previous snapshot change를 제공합니다.
- CDN, 설치 단계, telemetry, network access 없이 로컬 same-thread layout을 제공하도록 Cytoscape.js 3.34.0과 ELK.js 0.12.0을 vendor하고 integrity pin을 적용합니다.
- core ontology/RDF 1.0 vocabulary를 안정적으로 유지하고 static evidence boundary를 보존합니다. 표시된 관계는 runtime causality를 확립하지 않습니다.

## 0.2.0 - 2026-07-31

- 임의 문자열 literal을 보존하지 않으면서 Java `PolicyLeaf`에서 `RuntimeBranch`로 이어지는 static data-flow edge를 추가합니다.

## 0.1.1 - 2026-07-30

- append 또는 read 전 lineage journal symlink, reparse point, hard link, file-swap race를 거부합니다.
- snapshot manifest에 descriptor 기반의 제한된 source read를 재사용하여 discovery-to-read symlink swap과 oversize growth를 fail closed 처리합니다.
- `O_NOFOLLOW`가 없는 platform을 포함해 보호된 read 전, 중, 후에 file identity와 stable metadata를 검증합니다.
- symlink target, open-time swap, oversize growth, raw-byte manifest hashing에 대한 regression coverage를 추가합니다.

## 0.1.0 - 2026-07-29

- 결정론적 Java/Spring 및 Python static ontology extraction을 추가합니다.
- immutable snapshot, stable refresh fingerprint, staging validation, atomic promotion, last-known-good recovery를 추가합니다.
- RDF 1.1 Turtle export 및 PROV-O-compatible lineage를 추가합니다.
- structural query, bounded impact, snapshot history, diff command를 추가합니다.
- 자체 완결형 offline graph를 추가합니다.
- 등록된 workspace만 대상으로 하는 read-only local MCP tool 7개를 추가합니다.
- privacy, terms, security, threat model, SBOM, reviewer eval, deterministic release packaging을 추가합니다.
