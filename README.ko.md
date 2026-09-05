# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

허가된 Java/Spring 또는 Python 코드베이스를 입체적인 3D 지도로 탐색합니다. 심볼을 찾고, 소스 근거가 있는 의존 경로를 따라가며, 스냅샷 사이의 변경을 확인합니다.

**Astra 출시 기념 업데이트 · 0.6.0.** GPT-6 Astra 출시를 기념해 검색 정밀도, 근거 추적, 스킬 지침을 개선했습니다. 사람에게는 직관적인 3D 화면을, AI에게는 구조화된 온톨로지 자료를 제공합니다. [업데이트 내용](docs/ASTRA_RELEASE.md).

## 지금 하는 작업에 적용하기

> Code Ontology Companion 여기에 적용하고, 이 프로젝트 작업에 계속 활용해줘.

Codex가 실제 사용할 수 있는 도구와 기존 작업공간을 확인하고, 현재 상태와 작업에 관련된 심볼 검색 또는 영향 조회부터 실행합니다. 연결된 조회는 같은 스냅샷을 사용합니다. 의미 있는 Java/Python 변경 뒤에는 허가된 범위에서 갱신하고 최신 상태·분석 범위·경고를 확인합니다. 기본 적용 범위는 현재 대화이며, 프로젝트에 지침을 저장하는 일은 명시적으로 요청했을 때만 합니다.

> 온톨로지 여기 설정해줘.

일반적인 요청에는 Code·Context·Contracts 중 실제 실행 가능한 제품을 확인합니다. Code만 있어도 사용할 수 있으며, 제품을 지목하면 그 제품을 우선합니다. 없는 제품을 자동 설치하지 않습니다. Context는 사용자가 선택하고 확정한 결정·제약만 저장한 뒤 다시 읽어 확인하고, Contracts는 선택한 실제 교환 JSON을 검사하며 미지원·정보 손실·미검사 결과를 유지합니다.

[적용 흐름](skills/apply-code-ontology/SKILL.md)

## 설치 / 사용

[플러그인 디렉터리에서 설치](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [GitHub 패키지 다운로드](https://github.com/battle-doll/code-ontology-companion/releases)

이 소스는 0.6.1입니다. 디렉터리는 별도 심사·게시 절차를 거치므로 제공 버전이 다를 수 있습니다. 공식 스킬 전용 패키지에는 적용·관리 두 스킬과 분석기·화면·로컬 MCP 설정 안내가 들어 있습니다. MCP 서버는 포함하지 않으며, GitHub 전체 패키지에는 읽기 전용 stdio MCP 서버도 포함됩니다. 클라우드 엔드포인트는 필요하지 않습니다.

## 실제 자체 온톨로지 탐색

[**3D 탐색기 바로 열기 →**](https://battle-doll.github.io/code-ontology-companion/)

플러그인 자체의 지원 소스로 생성한 실제 온톨로지입니다. 모듈과 심볼을 선택해 연결과 소스 근거를 확인할 수 있습니다. 분석한 커밋과 기준 스냅샷도 공개합니다. 새 탭으로 열려면 ⌘ 클릭 또는 Ctrl 클릭을 사용하세요.

[스냅샷 생성 근거](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [아키텍처](docs/ko/ARCHITECTURE_AND_ROADMAP.md)

## 버전 0.6.1 지원 기능

- 현재 대화에 적용하고 실제 첫 조회부터 시작하며, 변경 뒤 허가된 갱신과 상태 확인까지 연결.
- 구조·영향·변경을 탐색하는 3D 중심 오프라인 화면과 부드러운 카메라 포커스.
- 정확한 심볼 우선 검색, 구조 필터, 이어서 조회, 스냅샷을 고정한 읽기.
- 방향별 의존 경로와 단계별 근거, 명확한 탐색 범위.
- 추가·삭제·수정과 근거 변경을 일관되게 비교.
- Java/Spring 타입·임포트·보수적 호출 해석·주입·프록시 신호, Python 모듈·함수·호출·파이프라인 역할 추정.
- 원본 근거를 보존하는 Code 참조와 Context용 불변 로케이터, 명시적인 Contracts 호환 범위.
- 키보드·텍스트 탐색, 움직임 감소 설정, 안전한 2D 대체 보기.

## 빠른 시작

Python 3.9+가 필요합니다. 먼저 쓰기 없이 지원 범위를 확인합니다. 본인 소유 또는 분석 허가를 받은 코드만 사용하고, 생성할 자료를 확인한 뒤 저장소 바깥의 작업공간을 초기화합니다.

```bash
python3 skills/manage-code-ontology/scripts/companion.py doctor --repo "/path/to/repo"
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo"
```

```bash
python3 skills/manage-code-ontology/scripts/companion.py init --repo "/path/to/repo" --workspace "/path/outside/repo/ontology" --authorized
python3 skills/manage-code-ontology/scripts/companion.py query --workspace "/path/outside/repo/ontology" --term "OrderService"
python3 skills/manage-code-ontology/scripts/companion.py impact --workspace "/path/outside/repo/ontology" --symbol "OrderService" --direction incoming
python3 skills/manage-code-ontology/scripts/companion.py diff --workspace "/path/outside/repo/ontology"
```

## 근거와 호환성

`graph.html`, `ontology.json`, `ontology.ttl`은 같은 소스 온톨로지를 사용합니다. RDF 1.1 Turtle의 `RelationshipEvidence`와 PROV-O 계보로 근거를 보존합니다. `inferred`는 검증 완료가 아니며 `runtime_unknown`은 실제 실행의 증거가 아닙니다. 근거 첨부율은 분석 정확도가 아닙니다.

Code는 코드 구조, Context는 결정과 유효 시점, Contracts는 지원 교환 규격 검증을 담당합니다. 각 제품은 독립적으로 사용할 수 있습니다. [AI용 데이터 계약](skills/manage-code-ontology/references/ai-data-contract.md) · [참조 교환](skills/manage-code-ontology/references/code-reference.md).

Context에는 원본 자료를 가리키는 참조를 전달합니다. 실제 스냅샷을 엄격한 Contracts draft로 직접 변환하는 기능은 아직 미지원입니다. 검증한 범위는 참조 교환 가이드에 명시했습니다.

기존 Ollama의 `127.0.0.1:11434` 연결은 별도 동의를 받은 경우에만 사용하며, 제안은 관찰된 근거와 분리합니다. 결정적 분석에는 모델이 필요하지 않습니다.

## 라이선스와 개인정보

Apache-2.0. 분석기는 대상 코드를 실행하거나 텔레메트리를 전송하거나 직접 네트워크에 연결하지 않습니다. 사용자 작업공간은 로컬에 남고, 공개 데모는 이 공개 저장소만 명시적으로 게시합니다. 소스 본문·주석·비밀정보는 보관하지 않습니다.

[개인정보](PRIVACY.md) · [보안](SECURITY.md) · [지원](SUPPORT.md) · [약관](TERMS.md) · [변경 이력](CHANGELOG.md)
