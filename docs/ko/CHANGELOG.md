# 변경 이력

[English](../../CHANGELOG.md) | [한국어](CHANGELOG.md) | [日本語](../ja/CHANGELOG.md) | [简体中文](../zh-CN/CHANGELOG.md)

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
