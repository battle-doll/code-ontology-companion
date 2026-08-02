# Code Ontology Companion: 전체 아키텍처 및 버전 로드맵

[English](../ARCHITECTURE_AND_ROADMAP.md) | [한국어](ARCHITECTURE_AND_ROADMAP.md) | [日本語](../ja/ARCHITECTURE_AND_ROADMAP.md) | [简体中文](../zh-CN/ARCHITECTURE_AND_ROADMAP.md)

## 1. 목적

Code Ontology Companion은 사용 권한이 있는 애플리케이션 소스, 구성, 빌드 메타데이터, 제한된 런타임 증거를 이식 가능하고 버전이 관리되는 코드 온톨로지로 변환하는 로컬 우선 AI 데이터 파이프라인으로 발전하고 있습니다. 이 파이프라인은 LLM에 직접적인 쓰기, 배포, 주문, 자격 증명 또는 자금 권한을 주지 않으면서 저비용 코드 이해, 변경 영향 분석, 증거 계보, 신중하게 통제되는 개선 워크플로를 지원해야 합니다.

버전 0.3.2는 더 좁은 제품 약속을 위한 최초의 안정적인 기능 기준선을 확립했습니다. 여기에는 결정론적 Java/Spring 및 Python 정적 분석, 불변 온톨로지 스냅샷, RDF 1.1 Turtle 내보내기, PROV-O 호환 계보, 오프라인 시각화, CLI 탐색, 선택적 동의 기반 Ollama enrichment, 읽기 전용 로컬 MCP profile이 포함됩니다. 아직 아래에서 설명하는 완전한 상시 가동 파이프라인은 아닙니다.

버전 0.3.4는 공개 Skills-only/OpenAI 제출물을 범용 온톨로지 워크플로로 명확히 제한합니다. AETHER Lab runtime-binding 명령과 구현, 프로젝트 전용 정책 스키마, 영수증 생성기, 프로젝트 전용 평가 사례는 공개 profile에 포함하거나 홍보하지 않습니다. 해당 선택 확장은 full/local GitHub profile에만 유지되며 OpenAI 호스팅 기능이 아니고 runtime, policy, order, funds 권한을 부여하지 않습니다.

## 2. 엔지니어링 원칙

- **Local first:** 기본적으로 로컬 저장소, 분석, 시각화, 모델을 사용합니다. 외부 리소스는 사용자가 명시적으로 구성하는 선택적 fallback입니다.
- **KISS:** graph database, model, daemon, network service가 없어도 종속성 없는 file snapshot 경로를 유용하게 유지합니다.
- **YAGNI:** Graph DB, SPARQL, REST, CI 자동화, 모델 설치는 검증된 use case에 필요한 경우에만 선택적 adapter로 추가합니다.
- **DRY:** 하나의 canonical ontology와 provenance model을 유지합니다. 모든 storage, query, visualization, improvement component는 동일한 불변 identity와 receipt를 사용합니다.
- **Deterministic core:** static analysis, fingerprint, candidate identity, validation, promotion gate는 결정론적으로 유지합니다. LLM 출력은 조언입니다.
- **Fail closed:** stale source, ambiguous binding, malformed evidence, unsupported runtime state, signature failure, partial mutation을 승인으로 해석해서는 안 됩니다.
- **Portable by design:** RDF 1.1 Turtle과 문서화된 provenance는 file storage와 선택적 ontology store 사이의 migration boundary로 유지됩니다.

## 3. 목표 아키텍처

```text
사용 권한이 있는 애플리케이션
  source + build + configuration + 제한된 runtime evidence
                         |
                         v
  Host 사전 점검 및 명시적 setup orchestrator
  - OS/CPU/RAM/disk/runtime 탐지
  - 기존 Python, Java, Ollama, store 탐색
  - installation 또는 service 변경 전 preview와 동의
                         |
                         v
  입력 adapter
  - Java/Spring       - Python           - 향후 언어 adapter
  - build metadata    - configuration    - 인증된 read-only runtime 사실
                         |
                         v
  결정론적 분석 및 정규화
  - symbol, call, import, inheritance, DI/AOP/proxy signal
  - pipeline role, policy leaf, runtime branch, evidence binding
                         |
                         v
  정규 ontology 및 provenance model
  - RDF 1.1 / 선택적 OWL profile / SHACL validation profile
  - observed, declared, inferred, validated, approved evidence class
  - immutable snapshot, diff, lineage, release 및 policy identity
                         |
          +--------------+---------------+
          |                              |
          v                              v
  기본 file snapshot store        선택적 store adapter
  JSON + Turtle + lineage         Jena/RDF4J/GraphDB/Stardog 또는 호환 store
          |                              |
          +--------------+---------------+
                         |
                         v
  조회 및 표현 plane
  - Codex Skill/CLI       - read-only MCP
  - 선택적 SPARQL/REST    - 대화형 graph 및 version 비교
                         |
                         v
  선택적 자문 intelligence
  - 기존 local LLM 탐색 및 사용자 선택 enrichment
  - 수치가 없는 가설과 설명만 허용
  - inferred sidecar는 observed fact와 분리
                         |
                         v
  별도의 통제된 improvement controller
  - 사전 등록된 candidate와 deterministic fingerprint
  - paired replay, purged OOS, cost calibration, natural shadow evidence
  - domain policy gate, signed admission, CAS, canary, rollback
  - 독립된 authority gate를 통한 issue/PR 또는 policy activation
                         |
                         v
  새로 관찰된 outcome과 source 변경이 evidence pipeline으로 돌아감
```

애플리케이션 서버는 이 시스템 안의 생산자이자 소비자 중 하나이며 AI 데이터 파이프라인 전체가 아닙니다. Spring Boot/Tomcat 애플리케이션은 인증된 읽기 전용 런타임 사실을 노출하고 검증된 policy를 사용할 수 있지만, ontology, experiment, validation, governance 단계는 분리된 상태를 유지합니다.

## 4. 아키텍처 plane

### 4.1 설정 및 host 탐색

향후 setup orchestrator는 새로운 것을 제안하기 전에 기존 component를 탐색합니다. 운영 체제가 지원하는 package manager와 로컬에서 사용 가능한 runtime을 우선해야 합니다. 모든 installation, model download, service start, port binding, credential use, external endpoint에는 명시적인 preview와 사용자 승인이 필요합니다. plugin 설치만으로 host를 몰래 변경해서는 안 됩니다.

최소 profile:

1. **Zero-install profile:** bundled Python script, immutable file, CLI, offline workbench.
2. **Full local profile:** zero-install profile과 bundled read-only stdio MCP.
3. **Extended local profile:** 선택적 graph store, SPARQL/REST management service, foreground 또는 OS 관리 refresh trigger, 기존 local LLM.
4. **External fallback profile:** 로컬 리소스가 부족하고 data boundary가 수락된 경우에만 사용자가 구성한 remote RDF 또는 model service.

다음은 사용자 안내용 권장치이며, 엄격한 호환성 보장은 아닙니다.

| Profile | macOS 안내 | Windows 안내 | 용도 |
| --- | --- | --- | --- |
| File-only 최소 | CPU 4코어, RAM 8 GiB, SSD 여유 5 GiB | x64, CPU 4코어, RAM 8 GiB, SSD 여유 5 GiB | Graph DB와 로컬 LLM을 사용하지 않는 소·중규모 저장소 |
| 권장 로컬 | Apple silicon, RAM 16 GiB, SSD 여유 20 GiB | CPU 6코어 이상, RAM 16 GiB, SSD 여유 20 GiB | 현재 full-local workflow와 가벼운 선택 서비스 하나 |
| 확장 로컬 | Apple silicon, RAM 24-32 GiB, SSD 여유 50 GiB 이상 | CPU 8코어 이상, RAM 32 GiB, SSD 여유 50 GiB 이상, 8 GiB 이상 GPU는 선택 사항 | 대규모 저장소, RDF store, quantized 7-9B급 model 동시 사용 |

저사양 PC는 graph storage와 model enrichment를 끈 file-only profile을 유지합니다. Preflight는 이 표만으로 설치를 승인하지 않고 실제 repository, 선택 model, store의 요구량을 측정해야 합니다.

### 4.2 입력 및 언어 adapter

각 language adapter는 자체 ontology를 정의하는 대신 canonical symbol 및 relationship model을 방출합니다. Java/Spring 분석은 package, type, method, record, import, inheritance, bean declaration, injection, annotation, aspect, transaction, asynchronous execution, cache, authorization, retry, proxy signal을 다룹니다. Python 분석은 module, class, function, decorator, call, import, inheritance, data-pipeline role을 다룹니다.

향후 adapter는 discovery, parsing, normalization, validation, capability reporting을 위한 제한된 interface를 사용해야 합니다. Build 및 configuration adapter는 대상 코드를 실행하지 않고 source structure를 dependency version 및 effective configuration에 결합해야 합니다. Runtime adapter는 인증되고, 읽기 전용이며, 정제되고, 만료 시간이 제한되고, static evidence와 분리되어야 합니다.

### 4.3 Canonical ontology

RDF 1.1 Turtle은 이식성 기준선으로 유지됩니다. 전체 설계에서는 상호운용 가능한 의미론을 위한 문서화된 OWL profile과 artifact validation을 위한 SHACL shape를 추가할 수 있지만, 어떤 reasoner 출력도 observed fact가 되지 않습니다. 모든 inference는 producer, algorithm 또는 model identity, source snapshot, timestamp, validation state를 유지합니다.

provenance model은 다음을 연결합니다.

```text
source revision
  -> ontology snapshot
  -> 가설
  -> candidate 및 domain policy
  -> dataset, replay, OOS, cost, shadow evidence
  -> 판정 및 admission receipt
  -> canary 또는 deployment
  -> 관찰된 outcome
  -> rollback 또는 다음 experiment
```

이는 진술이 observed, inferred, validated, approved 중 무엇인지 보존하면서 “이 날짜의 처리 정책 개선 때문에 timeout이 2초에서 3초로 변경되었다”와 같은 진술의 근거가 됩니다.

### 4.4 저장 및 조회

file store는 이식 가능하고, 검사할 수 있고, 백업하기 쉬우며, service가 필요하지 않으므로 기본값으로 유지됩니다. 선택적 store adapter는 동일한 Turtle과 provenance를 RDF 호환 graph database로 import합니다. Store별 index, reasoning extension, authentication, port, license는 canonical model 외부에 있으며 명시적으로 구성해야 합니다.

조회 기능은 다음 계층으로 발전합니다.

- 결정론적 CLI search, impact, history, diff, lineage
- 등록된 workspace만 대상으로 하는 read-only MCP
- 표준 기반 graph query를 위한 선택적 SPARQL
- 선택적 localhost REST management 및 health API
- 제한된 결정론적 tool에 대한 Codex natural-language orchestration

자연어 출력은 evidence strength를 높이지 않습니다.

### 4.5 Refresh 및 데이터 파이프라인

refresh pipeline은 비공개 source fingerprint를 사용해 변경되지 않은 작업을 건너뛰고, 변경된 분석을 staging에서 빌드하고, 모든 artifact를 검증하고, 불변 snapshot을 원자적으로 승격하며, 실패 시 마지막 정상 snapshot을 보존합니다.

전체 설계에는 다음이 추가됩니다.

- 언어 인식 파일별 증분 parsing
- 명시적 Git hook, CI 또는 foreground watcher trigger
- debouncing과 single-flight lease
- build/config/runtime evidence adapter
- provenance에 결합된 partial refresh 및 dependency invalidation
- snapshot 또는 lineage의 중복 publication 없는 retry

상시 watcher나 daemon을 몰래 설치하지 않습니다.

### 4.6 로컬 LLM 경계

결정론적 온톨로지에는 LLM이 필요하지 않습니다. 명시적으로 활성화하면 시스템은 자격이 있는 기존 로컬 모델을 탐색하고, 사용자에게 모델 선택을 요청하고, 제한된 이식 가능 메타데이터만 전송하며, 정규화된 제안을 별도의 inferred evidence로 저장합니다.

향후 installer는 CPU, GPU, memory, disk, operating system, license, provenance를 확인한 후 적절한 local model을 제안할 수 있습니다. 해당 모델의 다운로드나 시작에는 여전히 명시적 동의가 필요합니다. Remote/cloud model은 선택적 fallback이며 몰래 선택해서는 안 됩니다.

LLM이 할 수 있는 일:

- 구조적 변경 요약
- 수치 없는 가설 제안
- 결정론적 verdict 설명
- 조사 대상 제안

LLM이 할 수 없는 일:

- observed evidence 조작
- candidate value 또는 candidate ordering 선택
- 서명, 승인, 승격, 배포, 주문 제출
- safety, reconciliation, idempotency, cost, OOS gate 완화

### 4.7 개선 자동화 경계

Code Ontology Companion은 읽기 중심의 지식 및 증거 component로 유지됩니다. 별도의 improvement controller가 experiment와 모든 write workflow를 담당합니다. 도메인별 experiment, policy, deployment, trading stack은 별도 프로젝트에 속하는 downstream extension입니다. 이 확장은 버전이 지정된 evidence contract를 소비하고 자체적인 deterministic evaluation, admission, canary, rollback gate를 정의하며, Companion core 또는 공개 roadmap에 포함되지 않습니다.

Full/local GitHub 프로필의 선택적 하위 프로젝트 확장은 policy leaf와 static production branch 사이에 범위가 좁은 불변 binding을 생성할 수 있습니다. 이 확장은 공개 Skills-only/OpenAI 제출물의 기능이 아닙니다. Receipt는 runtime execution, safety, profitability, policy mutation 또는 order 제출 권한을 증명하지 않으며 funds authority도 부여하지 않습니다.

## 5. 현재 공개 기준선: 버전 0.3.4

| 영역 | 버전 0.3.4 | 전체 설계와의 관계 |
| --- | --- | --- |
| 제품 | 공개 Skills-only: Codex Skill, Python CLI, offline workbench; full/local: read-only stdio MCP 추가 | 유용한 local ontology pipeline이며 상시 가동은 아님 |
| 입력 | 사용 권한이 있는 `.java` 및 `.py` | source core 구현 완료, build/config/runtime adapter 예정 |
| Java/Spring | 결정론적 구조 및 보수적인 DI/AOP/proxy signal 추출 | 정적 가능성이며 active ApplicationContext 사실이 아님 |
| Python | 결정론적 module, symbol, call, import, inheritance, pipeline-role 추출 | core 구현 완료, adapter SPI 예정 |
| Ontology | JSON, RDF 1.1 Turtle, 안정적인 `co:` vocabulary, PROV-O 호환 lineage | core 구현 완료, 선택적 OWL/SHACL 예정 |
| 저장소 | immutable file snapshot, atomic current pointer, append-only lineage | default store 구현 완료, graph DB는 선택적 향후 작업 |
| 검색 | 공개 CLI query/impact/diff/history/lineage와 workbench 검색; full/local read-only MCP tool 7개 | MCP는 로컬 구현 완료, SPARQL/REST 예정 |
| Refresh | fingerprint skip, foreground watch, full staging reanalysis, atomic promotion | 안전한 refresh 구현 완료, 파일별 증분 및 관리 trigger 예정 |
| Local LLM | 기존 Ollama 탐지, 동의 후 사용자 선택 enrichment, inferred sidecar | 선택적 enrichment 구현 완료, 설치는 의도적으로 제외 |
| 시각화 | relationship lens와 current/previous 비교 기능을 갖춘 자체 완결형 Cytoscape/ELK workbench | 상당 부분 구현 완료 |
| 공개 확장 경계 | AETHER Lab runtime-binding 명령/구현, 프로젝트 전용 정책 schema, receipt generator, 전용 평가 사례 없음 | 해당 선택 확장은 full/local GitHub profile에만 유지 |
| 개선 | candidate, approval, policy-write, deployment, order, funds authority 없음 | 별도 controller 필요 |

공개 Skills-only package에는 범용 CLI, analyzer, workbench, reference, 선택적 local-LLM helper가 들어 있습니다. 공개 portal profile과 로컬 stdio transport는 서로 다른 배포 모델이므로 bundled MCP server는 의도적으로 제외합니다. AETHER Lab runtime-binding 명령과 구현, 프로젝트 전용 정책 schema, receipt generator, 전용 평가 사례도 제외합니다. Full/local GitHub package에는 MCP와 선택적 하위 프로젝트 확장이 별도로 유지되지만, 이는 OpenAI 호스팅 기능이 아니며 어떤 runtime/policy/order/funds 권한도 부여하지 않습니다.

## 6. 버전 로드맵

이 로드맵은 방향을 나타내며 날짜를 약속하지 않습니다. 각 릴리스는 다음 단계 없이도 유용하고 안전하게 유지됩니다.

### 0.3.3: 다국어 문서 및 릴리스 연속성

- 전체 아키텍처 및 버전 로드맵 공개
- 영어, 한국어, 일본어, 중국어 간체 문서 진입점 제공
- 영어를 권위 있는 법률 및 정책 원문으로 유지
- 문서 parity 검사 추가 및 결정론적 packaging 유지

### 0.3.4: 공개 프로필 경계 강화

- 공개 Skills-only/OpenAI 제출물을 범용 온톨로지 워크플로로 제한
- AETHER Lab runtime-binding 구현과 지침, 프로젝트 전용 정책 schema, receipt generator, 전용 평가 사례를 공개 archive에서 제외
- 공개 artifact에 전용 확장 표식이나 command route가 남으면 fail closed 처리하고 CLI surface를 smoke test
- 선택적 하위 프로젝트 확장을 full/local GitHub profile에만 유지하고 OpenAI 호스팅 및 runtime/policy/order/funds authority와 분리

### 0.4.x: 사용성 및 분석기 adapter

- 명시적으로 제한된 language-adapter contract 추출
- setup 진단, progress reporting, 조치 가능한 failure 개선
- foreground watcher control, debouncing, single-flight behavior 개선
- 더 명확한 static-confidence 및 unsupported-runtime 표시기 추가
- 종속성 없는 기본값 유지

### 0.5.x: 선택적 저장소 및 조회 확장

- RDF 1.1 import/export를 중심으로 graph-store adapter contract 정의
- 어떤 제품도 필수로 만들지 않으면서 사용자가 선택한 Jena, RDF4J, GraphDB, Stardog 또는 호환 store 지원
- 선택적 SPARQL 및 localhost REST management profile 추가
- 대규모 graph visualization 및 multi-snapshot 비교 개선
- file snapshot store의 완전한 지원 유지

### 0.6.x: 로컬 AI 데이터 파이프라인 운영

- 명시적인 Git, CI, managed-local refresh trigger adapter 추가
- 언어 인식 파일별 incremental invalidation 구현
- build metadata, dependency, effective configuration, 인증된 read-only runtime evidence adapter 추가
- 지속 가능한 pipeline health, recovery, lineage receipt 추가
- local-first 권고가 포함된 동의 기반 host setup assistant 제공

### 0.7.x: 통제된 개선 통합

- 외부 experiment controller를 위한 안정적인 evidence contract 정의
- ontology identity를 hypothesis, candidate, replay, OOS, cost, natural-shadow receipt에 연결
- 별도 승인 adapter를 통한 issue 또는 draft-PR 준비 지원
- code merge, deployment, policy mutation, runtime actuation을 Companion 권한 외부에 유지

### 0.8.x-0.9.x: 운영 환경 강화

- cross-platform lock, path safety, service lifecycle adapter 검증
- signed evidence 및 expiry contract 추가
- 외부 controller와의 CAS, canary, rollback, mixed-state recovery 통합 검증
- 대규모 repository 및 graph store benchmark
- migration 및 backward-compatibility 도구 완성

### 1.0: 완전한 제품 기준

버전 1.0은 다음 항목이 독립적으로 검증된 경우에만 선언해야 합니다.

1. language adapter, build/config input, 인증된 runtime evidence가 하나의 canonical ontology identity를 공유합니다.
2. file storage와 하나 이상의 선택적 표준 RDF store가 이식 가능한 의미론이나 lineage를 잃지 않고 round-trip합니다.
3. foreground, Git/CI, 승인된 managed-local refresh 경로가 신뢰할 수 있고, 관찰 가능하고, idempotent하고, 복구 가능합니다.
4. MCP, SPARQL/REST profile, natural-language orchestration, visualization이 동일한 read 및 evidence boundary를 보존합니다.
5. 기존 local model을 탐지하고 안전하게 enrichment할 수 있으며, 선택적 설치는 명시적이고 license를 고려합니다.
6. 외부 improvement controller가 인증된 evidence를 소비하고 필요한 모든 validation, CAS, canary, rollback gate를 증명할 수 있습니다.
7. 설치와 upgrade가 user data, rollback lineage, privacy, portability, 유용한 zero-dependency mode를 보존합니다.
8. 제품 문서와 핵심 workflow가 영어, 한국어, 일본어, 중국어 간체로 유지됩니다.

## 7. 호환성 및 migration

- 안정적인 `co:` namespace와 RDF 1.1 export가 migration contract입니다.
- 새 storage adapter는 독점적인 source of truth를 만드는 대신 기존 Turtle을 import해야 합니다.
- Snapshot과 provenance identifier는 불변이며, adapter는 index를 만들 수 있지만 다시 작성할 수 없습니다.
- Analyzer, Companion, schema, canonicalizer, inference version은 receipt에 명시적으로 유지됩니다.
- 새 analyzer가 refresh를 요구해도 이전 snapshot은 읽을 수 있습니다.
- Store별 기능에는 이식 가능한 fallback이 있거나 이식 불가능한 extension임을 명확하게 표시해야 합니다.

## 8. 영구적인 안전 및 개인정보 경계

이 프로젝트는 코드 접근 권한을 대상 코드 실행, secret 읽기, repository upload, policy mutation, software deployment, order submission, funds movement 권한으로 취급하지 않습니다. 결정론적 분석은 민감하고 생성된 path를 제외하며, 이식 가능한 artifact는 absolute path와 private fingerprint를 생략하고, 선택적 LLM data는 제한되고 별도로 분류됩니다.

자동 개선은 ontology plugin 내부의 기능 switch가 아니라 독립적으로 검증된 component의 조합입니다. 어떤 로드맵 milestone도 단지 자동화를 쉽게 만들기 위해 이 분리를 약화해서는 안 됩니다.

## 9. 게시 전략

버전 0.3.2를 최초 안정 기준선으로, 0.3.3을 다국어 문서 이력으로 보존하고, 버전 0.3.4의 격리된 공개 Skills-only profile을 현재 공개 기준선으로 사용하십시오. 이후 호환되는 patch 및 minor release를 통해 발전시키되 전체 목표 아키텍처를 완성할 때까지 실제 사용자 feedback 수집을 미루지 마십시오. 현재 제품을 graph database, live runtime tracer, autonomous refactoring system, deployment agent, profitability engine으로 홍보하지 마십시오.

의도한 제품 설명은 다음과 같습니다.

> 사용 권한이 있는 Java/Spring 및 Python 저장소를 대상으로 이식 가능한 RDF 계보, 정적 영향 탐색, 버전 비교, 오프라인 시각화를 제공하는 개인정보 보호를 고려한 로컬 코드 지식 그래프를 구축하고 유지 관리합니다.
