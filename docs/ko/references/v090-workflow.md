# 0.9.0 로컬 작업 흐름

[English](../../../skills/manage-code-ontology/references/v090-workflow.md) | [한국어](v090-workflow.md) | [日本語](../../ja/references/v090-workflow.md) | [简体中文](../../zh-CN/references/v090-workflow.md) | [Русский](../../ru/references/v090-workflow.md)

Code Ontology Companion은 Java/Spring·Python 소스를 온톨로지로 만드는 로컬 데이터 파이프라인입니다. Python 3.9+와 Windows·macOS·Linux를 지원합니다. AI는 로컬 MCP를 사용하고, 사람은 생성된 오프라인 HTML을 사용합니다. 개발자 표기는 **배틀돌(battle-doll)**입니다. 선택한 모델·추론 강도를 유지하며 특정 모델의 품질·토큰·속도 우위를 주장하지 않습니다.

## 현행 여부와 중단된 작업 확인

`ontology_status`는 소스의 `freshness`와 생성기의 `generatorFreshness`(`current`, `stale`, `unknown`)를 구분합니다. 생성기 지문에는 분석 도우미와 사람용 화면 자산이 포함됩니다. 소스가 현행이어도 HTML 재생성이 필요할 수 있습니다. 지문이 없는 이전 스냅샷은 `unknown`이며, `sync`는 메타데이터 누락을 현행의 근거로 삼지 않고 새 형식의 스냅샷을 만듭니다.

완성된 스냅샷 파일과 SHA-256 산출물 manifest를 확정한 뒤 준비된 실행 기록을 이용해 계보를 추가하고 현재 포인터를 원자적으로 교체합니다. 중단 시 미완료 실행 기록이나 계보 내보내기 불일치가 남을 수 있습니다. `doctor --workspace`는 무결성과 복구 상태를 읽습니다. `recover`는 같은 실행의 해시·연결을 검증하고 계보 이벤트를 중복시키지 않으면서 완료하며, 파생 Turtle도 복구합니다. 해시 불일치·상태 충돌·여러 미완료 실행이 있으면 중단합니다. 여러 파일 전체를 하나의 파일시스템 트랜잭션으로 바꾸는 방식은 아닙니다. Windows의 내구성 표시는 POSIX 디렉터리 fsync 대신 file-flush-only입니다.

허가된 작업공간의 진단에서 중단된 작업이 확인될 때 `recover`를 사용하고, 소스나 생성기가 오래되었으면 `sync`를 실행합니다. MCP는 읽기 전용이며 복구·갱신을 수행하지 않습니다.

```bash
python3 skills/manage-code-ontology/scripts/companion.py status --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py doctor --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py recover --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py sync --workspace "/path/outside/repo/ontology"
```

## 비공개 증분 분석

macOS·Linux에서는 소스 저장소 밖의 소유자 전용 `.parse-cache`를 사용합니다. 소스와 분석 문맥이 같으면 인증된 파서 연산을 재사용하며 원문 백업을 저장하지 않습니다. 연산으로 그래프를 다시 구성한 뒤 관계를 재해석합니다. 범위·임포트/타입 문맥·분석기가 바뀌면 관련 캐시가 무효화됩니다. 캐시 재사용은 분석 정확도의 증거가 아닙니다. Windows는 비공개 캐시 DACL 설정기가 마련되기 전까지 캐시를 저장하지 않고 동등한 전체 분석을 수행하므로 지원을 유지합니다.

캐시·신원 프로필·실행 기록·`source-manifest.json`은 비공개로 유지합니다. `CODE_ONTOLOGY_PRIVACY_FILE`을 설정하면 알려진 신원과 일반적인 민감 패턴을 검사하지만, 알려지지 않은 모든 실명을 식별하지는 못합니다. `--public` 공개 후보 패키징에는 보호된 신원 프로필과 개인정보 검증이 필요합니다. 비공개 작업공간 내부 파일·실명·개인 이메일을 업로드하지 마세요.

## AI에 필요한 근거 전달

기존 읽기 전용 도구 11개를 유지하고, 선택형 12번째 도구 `ontology_evidence_pack`을 추가합니다. 고유한 요청 ID를 가진 검색·이웃 조회 1–8개가 같은 불변 스냅샷을 읽습니다. 스냅샷·품질 정보는 한 번만 전달하고, `n:`·`e:` 참조는 실제 선택된 노드·근거 표현을 식별합니다. 모든 표현을 노드 ID 하나로 합치지 말고 반환된 참조를 사용합니다.

```json
{
  "workspace_id": "registered-workspace-id",
  "requests": [
    {"id": "symbols", "operation": "search", "term": "OrderService", "limit": 20},
    {"id": "callers", "operation": "neighbors", "symbol": "OrderService", "direction": "incoming", "limit": 100}
  ],
  "node_fields": ["qualifiedName", "path", "metadata"],
  "max_results": 100,
  "max_payload_bytes": 65536,
  "max_wire_bytes": 150000
}
```

- `node_fields`는 `qualifiedName`·`path`·`metadata`를 선택하며 기본값은 전부입니다. `[]`이면 해당 선택 필드를 생략합니다. 가능한 식별 필드는 유지하고 생략 사항을 `omittedNodeFields`로 표시합니다.
- `max_results`는 반환 행 1–200개입니다. `max_payload_bytes`는 정규화된 UTF-8 구조화 JSON 16384–262144바이트, `max_wire_bytes`는 요청 ID·호환용 복제 텍스트·줄바꿈을 포함한 실제 JSON-RPC 응답 16384–1048576바이트입니다. `payloadBytes`·`wireBytes`는 각각의 측정값이며 토큰 추정치가 아닙니다.
- `continuation.tool`과 `continuation.arguments`를 그대로 사용합니다. 스냅샷·선택 조건·제한값은 유지됩니다. 검색은 원래 조회의 offset을 전진시키며, 이웃 페이지는 처음 정한 탐색 한도 안에서만 이어집니다. 마지막에도 `query_limit`이면 부분 결과이며 그래프 전체를 확인한 것이 아닙니다.
- `excludedReasons`·항목 오류·필드 생략을 표시합니다. 행과 경로 근거는 함께 전달합니다. 한 행도 담지 못하면 진행할 수 없는 커서 대신 제한값 조정 안내 오류를 반환합니다. scope는 현재 페이지가 아닌 원래 조회를 설명합니다.

## 사람용 HTML과 RDF 검증

생성된 `graph.html`을 로컬에서 엽니다. 영어·한국어·일본어·중국어 간체·러시아어를 선택하고, 지도와 독립적인 페이지 목록 사이에서 선택·필터를 유지하며 탐색합니다. 변경 화면은 이전/현재 값을 보여주고 관계 화면은 정적 경로 근거를 제공합니다. 빈 결과·누락·잘림의 한계를 유지합니다. 오프라인 HTML은 생성된 스냅샷을 표시하며 현재 소스나 실제 실행 여부를 검사하지 않습니다.

RDF 1.1 Turtle·`RelationshipEvidence`·제한된 PROV-O 계보는 같은 온톨로지의 내보내기입니다. 개발/CI에서는 `requirements-validation.txt`의 고정된 선택 의존성으로 독립 RDF 파서·SHACL·JSON/Turtle 트리플의 정확한 일치를 검사할 수 있습니다. 플러그인 실행에는 이 의존성이 필요 없으며, 설치되지 않았으면 검증 불가로 표시하고 통과로 처리하지 않습니다.

```bash
python3 scripts/validate_rdf_contract.py --json "/path/ontology.json" --turtle "/path/ontology.ttl" --lineage "/path/lineage.ttl"
```

RDF 구조 검증 통과는 소스 분석 정확도·완전한 PROV 준수·실행 성공을 증명하지 않습니다. 보수적인 Java 디스패치와 Python 정의 시점/동적 동작의 부분 지원 범위를 유지합니다. JS/TS 분석과 모듈 간 해석은 이번 릴리스의 지원 그래프 분석 범위 밖입니다.

[로컬 MCP 설정](local-mcp.md) · [개인정보 보호 운영](../PRIVACY_OPERATIONS.md)
