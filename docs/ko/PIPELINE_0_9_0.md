# 0.9.0 로컬 온톨로지 파이프라인

[English](../PIPELINE_0_9_0.md) | [한국어](PIPELINE_0_9_0.md) | [日本語](../ja/PIPELINE_0_9_0.md) | [简体中文](../zh-CN/PIPELINE_0_9_0.md) | [Русский](../ru/PIPELINE_0_9_0.md)

개발자는 **battle-doll(배틀돌)**입니다. AI는 로컬 MCP, 사람은 생성된 오프라인 HTML을 사용합니다. Windows·macOS·Linux 지원을 유지하며 실제 OS 검증과 처리 용량은 단위 테스트와 별도로 보고합니다. 이 흐름은 공식 플러그인 제출·공개를 수행하지 않습니다.

**0.9.1 HTML** — 생성 HTML의 첫 화면을 움직이는 3D 지도로 복원했습니다. 상단 전체 기록에서 카탈로그와 정책을 열 수 있으며, 지도는 제한된 페이지·전체/확대 모드·모션 감소 설정을 유지합니다.

## 시작과 갱신

Python 3.9 이상과 신뢰할 수 있는 설치 번들을 사용합니다. 아래 `COMPANION`은 번들의 `skills/manage-code-ontology/scripts/companion.py`이며 Windows에서는 `py -3`을 사용할 수 있습니다. 허용된 소스 밖에 새 워크스페이스를 선택합니다. HTML·이동용 번들을 내보내기 전에 `CODE_ONTOLOGY_PRIVACY_FILE`을 소스·출력 경로 밖의 비공개 개인정보 거부 프로필로 설정합니다. 프로필은 지식 산출물에 복사되지 않으며 내보내기에 필요한 보호 설정이 없으면 실패합니다.

```sh
python3 "$COMPANION" analyze --repo /path/to/source --workspace /path/to/knowledge --authorized --language en
python3 "$COMPANION" refresh --workspace /path/to/knowledge --language en
python3 "$COMPANION" pipeline-status --workspace /path/to/knowledge
```

대량 소스에는 `analyze`에 `--capacity large`를 추가합니다. 상한은 250,000개 파일·입력 4 GiB·500만 레코드·스냅샷 출력 8 GiB·7,200초이며 기본값은 25,000개 파일·입력 512 MiB입니다. 명시적 예산 선택이며 모든 실제 프로젝트의 처리 보증은 아닙니다. HTML·번들 내보내기는 별도 1 GiB 한도를 유지하므로 확정된 지식만 필요하면 `--no-html`을 사용합니다. 파일별 AST 한도는 기본 20,000노드, `--capacity large`에서 200,000노드이며 소스 바이트·규칙 IR·깊이 제한은 계속 적용됩니다.

한국어 기본 화면은 `--language ko`를 사용합니다. 첫 명령은 지식을 봉인하고 소유자 전용 권한을 만든 뒤 MCP에 워크스페이스를 등록하고 5개국어 HTML을 생성합니다. `--source-root`를 반복하여 범위를 선택할 수 있습니다. `--no-html`은 분석만 수행하며 `--label`에는 안전한 프로젝트 별칭을 지정합니다. 갱신은 이전 스냅샷을 보존하고 변경되지 않은 파일 사실을 재사용하며 파일 간 해석을 다시 구성합니다. 취소·실패 시 이전 완료본을 보존합니다. `pipeline-recover --workspace /path/to/knowledge`로 검증된 중단 작업을 재개·완료할 수 있습니다. 분석 중 소스·카탈로그 식별자가 바뀌면 새 세대를 승격하지 않습니다.

새 파이프라인은 `pipeline.json`과 불변 분할 SQLite 스냅샷을 사용합니다. 기존 `init`/`sync` 및 대형 프로젝트 카탈로그도 유지하며 자동 변환·병합하지 않습니다. 상태 조회는 소스를 열지 않고 저장된 산출물을 검증하므로 `freshness=not_checked`입니다. 소스의 현행성 재확인은 갱신 작업에서 수행합니다.

## 분석 범위

| 계열 | 구현 경계 |
| --- | --- |
| Python | AST 기반 선언·import·지원하는 정적 관계, 제한된 형식화 순수 함수 정책 추출. 동적 실행은 미확인입니다. |
| Java, JavaScript/TypeScript, SQL, Vue, XML/MyBatis | 보수적인 구문·선언·import 및 선택 프레임워크 패턴. 전체 컴파일러·SQL 방언·프로그램 의미를 증명하지 않으며 동적 SQL·reflection은 미해석입니다. |
| Kotlin, C#, Go, Rust, C/C++, PHP | 제한된 선언·import 인식과 부분 coverage, 미해석 의미를 명시합니다. |
| Swift, Dart, Ruby, Scala | 제한된 선언·import 인식이며 완전한 언어 의미·정책 추출을 뜻하지 않습니다. |
| Bash/POSIX shell, PowerShell | Bash 함수·source 참조·명령/파이프라인·제어 경계, PowerShell 선언·import. 스크립트 실행·변수 확장·비밀 인자 수집을 하지 않고 모호한 인용·heredoc 영역은 보류합니다. |
| LangChain/LangGraph, Kafka, Redis | 선택된 agent/tool/graph 및 메시징·캐시 선언 관계. 환경이 미확인인 자원을 합치지 않고 prompt·key·value·credential 원문이나 실제 실행 성공을 수집하지 않습니다. |

파일마다 언어·어댑터/규칙 버전·소스 지문·근거 위치·분석 수준·한계를 제공합니다. 미지원 구문을 확인된 지식으로 승격하지 않습니다. 과거 설계의 더 넓은 프레임워크 목록은 로드맵이며 모든 SDK·버전 지원을 뜻하지 않습니다.

엔진은 제한된 파일 배치·단일 writer·디스크 분할을 사용하며 구현된 실행 설정은 `workers=1`입니다. 엔진 API에서 명시적으로 파일·바이트·레코드 예산을 높일 수 있지만 상한은 실측 용량이 아닙니다. 그래프 질의는 페이지 단위입니다. 정책 계산은 별도 전체 규칙 예산을 사용하며 규칙을 몰래 잘라 계산하지 않고 초과 시 실패합니다.

## 정책 지식과 AI 사용

도메인 후보는 `product`, `order`, `display`, `claim`, `settlement`, `delivery`입니다. 식별자 기반 분류는 업무 소유권 승인이 아닙니다. 정책에는 조건·형식화 입력·실행 순서·소스 Assertion·미지원 경계가 남습니다. Python 지원 범위는 typed bool/int/Decimal, 대입, 조기 return, boolean 조건과 명시적으로 지원하는 산술·반올림입니다. 미지원 호출·예외·반복문을 검증된 정책으로 내보내지 않습니다. 정확한 범위는 생성된 coverage를 확인합니다. Java·TypeScript는 명시적으로 타입이 지정된 순수 불리언 조건 함수를 지원하며 수치 계산·프레임워크 기반·동적 디스패치 정책은 미지원입니다.

정책 MCP 도구는 `list_domain_policies`, `query_policy_rules`, `compare_policy_cases`, `explain_policy_result`입니다. 새 구조 조회 도구는 `ontology_pipeline_status`, `ontology_pipeline_search`, `ontology_pipeline_modules`이며 기존 12개와 합쳐 전체 패키지에는 읽기 전용 도구 19개가 있습니다. Skills-only에는 분석기·설정 안내가 있고 MCP 서버는 없습니다.

1. `ontology_list_workspaces`에서 `pipeline` 워크스페이스를 선택합니다.
2. `ontology_pipeline_status`에서 구체적인 snapshot ID를 확인합니다.
3. 관련 조회에 같은 ID를 고정합니다. `current`나 임의 파일 경로를 조회 식별자로 받지 않습니다.
4. 규칙을 확인한 뒤 형식에 맞는 문맥을 전달하여 설명·비교합니다. Decimal 금액은 십진 문자열로 전달합니다.

기본 권위 뷰는 `verified_implemented`이며 `AI-proposed`는 계산에서 제외됩니다. `approved_business`에는 별도의 명시적 승인 메타데이터가 필요하고 추출 성공만으로 승인하지 않습니다. 모델 신원과 의미 검증은 별개입니다. 기본 엔진은 모델을 쓰지 않아 `modelNotUsed` / `N/A`이며 cloud API·모델 설치·자동 모델 전환·소스 전송을 추가하지 않습니다.

정책 질문은 봉인된 정책만 읽으며 코드·DB·broker·cache를 실시간 재조회하지 않습니다. 자격·사용 횟수·설정·시간 입력이 부족하면 `needs_context` 또는 `UNKNOWN`입니다. 제공된 표본에서 가장 좋은 사례는 `best_found`입니다. `proven_maximum`/`proven_minimum`은 완전한 지원 범위·정확한 snapshot/ruleset 고정·독립적으로 확인된 유한 입력 전체 탐색이 필요하며 명시한 범위가 조직의 모든 정책을 뜻하지 않습니다. 코드의 동작은 업무 승인이나 현재 사용자 자격의 증거가 아닙니다.

로컬 MCP 응답도 호스트가 원격 모델로 전달할 수 있습니다. 로컬 소스 분석 승인은 그 전송 승인이 아니므로 보낼 근거를 별도로 선택·승인해야 합니다.

## 지식 접근권한

`access.json`은 비공개 로컬 권한 정책입니다. 초기에는 실행 환경에 연결된 가명 소유자만 허용합니다. 신뢰하는 실행 환경이 `CODE_ONTOLOGY_PRINCIPAL`을 지정하며 기본값은 `local-owner`입니다. 도구 인자로 주체·역할을 선택할 수 없습니다. 서로 다른 주체는 각각 설정한 MCP 프로세스를 사용합니다. 이 경계는 로컬 프로세스·OS 계정이며 원격 로그인·신원 제공자가 아닙니다.

권한은 `read_structure`, `read_policy`, `read_evidence`, `export_html`, `export_bundle`, `manage_access`이며 특정 스냅샷으로 제한할 수 있습니다. 미등록 주체·없거나 안전하지 않은 ACL·미지원 작업·스냅샷 불일치는 거부합니다. 정책 전용 조회에는 불투명 근거 ID만 남고 소스 위치 정보는 별도의 근거 권한이 있어야 표시됩니다. 기존 워크스페이스는 로컬 소유자 전용입니다. 변경된 권한은 이후 요청마다 다시 읽습니다.

명시적으로 실행한 로컬 운영자 명령으로 권한을 교체하며 MCP에는 이 명령이 없습니다.

```sh
python3 "$COMPANION" pipeline-access --workspace /path/to/knowledge --principal policy-reader --action read_policy --snapshot SNAPSHOT_ID
```

`--action`을 생략하면 해당 별칭의 작업 권한을 회수합니다. 전체 스냅샷을 관리하는 관리자 최소 1명은 남아야 합니다. 실명·개인 이메일 대신 별칭을 사용합니다. 추론된 도메인은 보안 분류가 아니므로 이 버전은 도메인별 행 수준 격리를 보장하지 않습니다. 서로 다른 기밀 범위는 각각 허용한 워크스페이스로 분리합니다.

HTML은 `export_html`과 3개 조회 권한, 이동용 번들은 `export_bundle`과 3개 조회 권한이 필요합니다. 이미 복사된 오프라인 HTML은 이후 ACL 변경으로 회수할 수 없으므로 파일과 전달 대상을 별도로 보호해야 합니다. POSIX 소유권·모드 및 사용 가능한 Windows 열린 핸들 ACL 검사에서 보호를 확인할 수 없으면 거부합니다. 실제 Windows 실행은 별도 검증 대상입니다.

## 사람용 HTML·계보·교환

한국어·영어·일본어·중국어 간체·러시아어 화면을 생성합니다. 카탈로그·모듈·기록·정책 의사결정표는 제한된 페이지와 정확한 근거 앵커를 사용합니다. 검색·3D는 현재 페이지 범위이며 전체 기록은 페이지 이동으로 접근합니다. 기존 3D 확대/전체 제어·모션 감소·텍스트 이동·모바일 터치 대상을 유지합니다. 상대 링크는 `fetch`나 필수 HTTP 서버 없이 동작합니다. 정적 페이지는 현재 소스·실행 상태의 증거가 아닙니다.

RDF 1.1 Turtle은 [PROV-O](https://www.w3.org/TR/prov-o/)를 사용하여 주장과 계보를 표현합니다. [SHACL](https://www.w3.org/TR/shacl/)은 필수 형태를 검사하며 진실을 인증하지 않습니다. 매니페스트는 산출물 체크섬·분석 명세·coverage·소스 확인 시간을 연결합니다. 체크섬은 무결성 근거이며 신뢰된 서명이 아닙니다. 비공개 소스 매니페스트·캐시·접근 정책·로컬 설정은 이동용 번들에서 제외합니다. 이동 가능한 형식이 업로드 권한을 부여하지 않습니다.

과거 [0.9.0 설계 기준](NEXT_ARCHITECTURE_0_9_0.md)은 목표 아키텍처와 수용 기준을 보존합니다. 실제 지원은 이 구현 안내와 검증 기록으로 판단하며 미측정 성능·실기기 검사·후속 어댑터는 미확인으로 구분합니다. 공식 제출·승인·공개는 이 로컬 작업에 포함되지 않습니다.
