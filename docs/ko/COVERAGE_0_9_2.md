# 0.9.2 누락 탐지와 커버리지 검증

[English](../COVERAGE_0_9_2.md) | [한국어](COVERAGE_0_9_2.md) | [日本語](../ja/COVERAGE_0_9_2.md) | [简体中文](../zh-CN/COVERAGE_0_9_2.md) | [Русский](../ru/COVERAGE_0_9_2.md)

개발자: **battle-doll (배틀돌)**. AI는 로컬 MCP를, 사람은 생성된 오프라인 HTML을 사용합니다. Windows·macOS·Linux 지원을 유지하며 실제 운영체제 검증과 로컬 회귀시험 결과는 구분합니다. 이 절차는 대상 앱의 게시·설치·재시작을 수행하지 않습니다.

## 선택한 전체 범위에서 시작

AI에게 “선택한 전체 범위를 먼저 목록화하고, 제외·실패 항목도 분모에 남긴 뒤 여섯 단계의 커버리지와 남은 누락을 보여줘”라고 요청하세요. 원본 목록화는 읽기 전용입니다.

```sh
python3 "$COMPANION" coverage-inventory --repo /path/to/source --source-root src
```

기본 목록화는 pipeline 어댑터를 사용하며 `--mode legacy`는 기존 Java/Python 지원을 측정합니다. 내장 제외 디렉터리도 목록에 남습니다. 이 목록화는 `.gitignore` 패턴을 해석하지 않으므로 해당 파일이 제외 또는 완전성을 보장하지 않습니다.

`COMPANION`은 신뢰한 번들의 `skills/manage-code-ontology/scripts/companion.py`입니다. 기존 Python 3.9 이상을 사용하며 Windows에서는 `py -3`를 사용할 수 있습니다. 허용한 소스 루트가 여러 개면 `--source-root`를 반복합니다. 검증 결과는 소스 저장소·설치본 밖에 보관합니다. 민감해 보이는 파일명만으로 정상 소스 구조를 조용히 지우지 않습니다. 실제 비밀값, 링크·reparse point, 안전하지 않은 경로와 읽을 수 없는 내용은 계속 보호합니다. 제외·지원하지 않는 언어·제한·인코딩 오류·접근 불가 경계는 목록에 남습니다. 디렉터리를 읽지 못하면 전체 파일 분모는 `UNKNOWN`이며 보이는 파일만으로 전체 완료를 주장할 수 없습니다.

처리할 수 없는 항목은 대상·원인·영향·대안을 남기고 그 항목을 넘어가기 전에 사용자 판단을 받습니다. 이미 승인된 정상 처리에는 재승인이 필요하지 않습니다.

## 여섯 지표를 별도로 확인

| 단계 | 인정할 수 있는 근거 | 완료 증거가 아닌 것 |
| --- | --- | --- |
| `scope_files` | 독립적으로 선정한 전체 파일 중 처리된 파일 | 필터 통과 파일만의 비율 |
| `declarations_types` | 명시한 기대 목록의 정확한 선언·타입 | 파일 존재·비슷한 심벌 이름 |
| `exact_calls` | 원본 호출 위치와 정확한 목표 선언 및 일치하는 근거 | 후보·placeholder·`IMPORTS`·`IMPLEMENTS`·런타임 구현체 추측 |
| `policy_semantics` | 표현된 조각과 독립 대조한 필수 조건·계산식 | 정책 노드·숫자 상수의 존재 |
| `mcp_delivery` | 고정한 한 조회의 모든 페이지와 정확한 예상 payload | `truncated=false` 하나·일부 페이지 |
| `policy_document` | 원본 의미 요소를 해당 문단에서 서술했음을 독립 검토 | 인용·해시·검토하지 않은 생성 문단 |

각 지표는 분자·분모·비율·측정 범위·누락·근거·한계를 보존합니다. 분모를 모르면 `UNKNOWN`이며 0이나 100%가 아닙니다. 표본 비율은 그 표본에만 적용합니다. 부분 서술은 별도 범주이며 임의의 0.5점을 주지 않습니다. 생성 관계의 근거 부착률은 전체 코드 커버리지가 아닙니다. 누락·미지원·미확인이 남으면 명령이나 snapshot 생성이 성공해도 전체 완전성은 `PARTIAL` 또는 `BLOCKED`입니다.

## snapshot과 의미 근거 결합

pipeline workspace는 `ontology_pipeline_status`에서 구체적인 snapshot을 얻고 `ontology_pipeline_coverage`로 파일 처리 상태를 끝까지 조회합니다. `ontology_pipeline_search`의 `callsite`·`semantic_fragment` 종류로 호출과 의미 조각을 조회할 수 있습니다. 호출은 정확한 정적 목표·후보·미해결을 구분하며 인터페이스 목표가 실제 실행 구현체라는 뜻은 아닙니다. Java 의미 조각은 제한된 필드·상수·대입·조건·반환식 구조를 보존합니다. 임의 문자열과 민감값은 저장하지 않고 미해결 호출·미지원 제어 흐름·초깃값 부재는 위치와 사유를 남깁니다. `represented`는 지원하는 식의 구문을 보존했다는 뜻이며 전체 업무 규칙 검증이 아닙니다. 단위는 독립적으로 지원된 결합이 없으면 `UNKNOWN`입니다. 기존 실행 가능한 typed-policy 규칙은 별도 계약입니다.

모든 결과에 `snapshotId`·`sourceFingerprint`·`scopeDigest`·`analysisSpecId`를 결합하고 원본 위치에는 파일 해시를 붙입니다. `nextOffset`이 끝날 때까지 `queryDigest`·offset·total·returned·payload를 보존합니다. 첫·중간·마지막 페이지 누락, 다른 snapshot/해시/조회 혼합, 중복 ID와 같은 ID의 payload 변조는 영수증을 무효화합니다. snapshot 상태 조회 자체는 원본 최신성 재검사가 아닙니다.

`coverage_contract.validate_policy_document`는 독립 원본 기대 목록·온톨로지 조각·MCP 페이지·문서 바이트·주장을 받습니다. 문단 의미 검토는 별도 `semantic_reviews`로 입력하며 정확한 기대 목록·원본 근거·문서·문단·검토한 의미 요소·검토자·snapshot을 결합합니다. 해시는 정합성을 확인할 뿐 문장이 규칙을 제대로 서술했는지는 독립 검토가 필요합니다. 직접 소스를 읽어 보완했다면 `direct_source_supplemented`로 표시하고 문서가 완전 서술이어도 `ontologyOnlyFull`에는 넣지 않습니다. 완전·부분·미서술·근거 없는 주장을 따로 집계합니다. 원본·snapshot·기대 목록·문단이 바뀌면 재검증해야 합니다. 각 주장은 `directSourceSupplemented`를 JSON 불리언 `true` 또는 `false`로 명시해야 합니다. 누락하거나 다른 자료형이면 지식 근거가 미확인인 상태로 남습니다.

이미 측정한 여섯 지표를 로컬 보고서로 저장하려면 다음을 사용합니다.

```sh
python3 "$COMPANION" coverage-validate --input /path/to/coverage-request.json --output /path/to/new-verification
```

요청 파일은 `binding`·여섯 `metrics`·`remaining`을 포함합니다. 이 명령은 지표 정합성을 검사하고 `coverage.json`·`coverage.md`를 만들며, 분모를 추정하거나 독립 문단 검토를 대신하거나 전체 완전성을 증명하지 않습니다. 비공개 원본과 검증 산출물은 로컬에 보관하고 공개 fixture·보고서에 개인정보·비밀값·운영 내용을 넣지 않습니다.
