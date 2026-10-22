# 개인정보 운영 절차 — 0.8.3

[English](../../skills/manage-code-ontology/references/privacy-operations.md) | [한국어](../ko/PRIVACY_OPERATIONS.md) | [日本語](../ja/PRIVACY_OPERATIONS.md) | [简体中文](../zh-CN/PRIVACY_OPERATIONS.md) | [Русский](../ru/PRIVACY_OPERATIONS.md)

## 개인 식별자는 로컬에 보관

지원하는 생성 온톨로지 산출물·로컬 MCP 응답·오프라인 HTML에 로컬 개인정보 검사를 적용합니다. 설정된 비공개 프로필은 지정된 실명·개인 이메일을 차단하고 일반 검사도 개인 이메일 형태 값을 차단합니다. 공개 코드·fixture·패키지 메타데이터·보고서·테스트 출력에 실제 개인정보를 넣지 않습니다. 공개 배포자 이름은 battle-doll 닉네임을 사용합니다.

`CODE_ONTOLOGY_PRIVACY_FILE`은 보호 대상 소스·출력 루트 밖의 비공개 프로필을 지정합니다. 프로필은 원문 식별자 대신 비공개 키·길이 제한·HMAC-SHA256 지문을 저장합니다. 이 프로필도 비공개 자료이며 키·지문을 커밋·업로드·출력하거나 HTML/JSON/MCP에 넣지 않습니다. 매번 파일을 다시 읽고 링크·reparse point·잘못되거나 과도한 크기의 프로필을 거부하며 POSIX에서는 `0600` 권한을 요구합니다. Windows에서는 실제 열린 프로필 핸들의 소유자·DACL을 읽기 전후 검사합니다. 현재 사용자·Local System·기본 Administrators 외의 유효 접근 허용, null DACL, 미지원 ACE 또는 확인할 수 없는 권한은 거부합니다. 실제 Windows 실행 검증은 별도이며 POSIX·모의 테스트로 통과를 주장하지 않습니다. 임의의 설정 명령을 만들지 말고 실제 runtime 계약을 따릅니다.

0.8.3 공개용 내보내기는 보호된 비어 있지 않은 식별자 프로필을 요구하고 일반 로컬 탐색은 선택 프로필 동작을 유지합니다. 공개 산출물 manifest에는 비공개 source manifest·파싱 캐시 키·실행 기록을 넣지 않습니다. 파일별 증분 분석은 안전하게 접근 가능한 비공개 인증 캐시를 사용하며 확인되지 않으면 전체 파싱으로 전환합니다. Windows 캐시 저장은 비공개 디렉터리·키 생성 절차가 검증될 때까지 비활성화되어 있고 전체 분석은 가능합니다. 이는 구현된 Windows 프로필 DACL 검사와 별개입니다.

실패는 일치한 개인정보 대신 유형만 반환합니다. 선택 프로필이 없으면 실명 보호가 제공되지 않으며 알 수 없는 모든 이름을 자동 식별하지 않습니다. JSON/HTML entity/percent/unicode-escape 해제는 최대3회이며 추가 해제가 가능한 값은 `encoding_depth`로 차단합니다. 정규화는 제한되어 있고 모든 바이너리 메타데이터·화면의 글자·타사 출력·모든 인코딩까지 보장하지 않습니다. 로컬 PASS를 모든 곳의 개인정보0으로 확대하지 않습니다.

## 공개 경로마다 별도 검토

공개 PR 전에 실제 계정의 GitHub 이메일 보호가 최신 상태임을 확인한 신뢰할 수 있는 기록을 요구합니다. 수동 작성한 확인서·로컬 `git config`·설정 파일·단위 테스트는 현재 서비스의 확인 증거가 아닙니다. 선택한 소스·서비스 자동 생성 commit ref를 모두 감사합니다. 로컬 HEAD만 검사하면 보관된 일부 PR merge ref를 놓칩니다. 직접 branch 테스트는 코드 검증이며 앞으로 서비스가 생성할 commit의 안전성 검증이 아닙니다.

공식 디렉터리는 실제 공개 개발자 신원을 별도로 확인합니다. battle-doll만 표시되지 않고 개인정보가 공개될 수 있으면 업로드·제출·게시 전에 **HOLD**합니다. 파일 업로드·포털 초안 검사·승인·공개 listing은 다른 상태입니다. 보관된 ref 노출은 서비스가 제거를 확인할 때까지 미해결이며 branch·로컬 저장소 변경만으로 전체 삭제라고 주장하지 않습니다.

## 제품과 검증 한계 유지

전체 소스 checkout 또는 full 배포본에서 `CODE_ONTOLOGY_PRIVACY_FILE`을 안전하게 설정한 뒤 Python3.9 이상과 인증된 GitHub CLI로 읽기 전용 배포자 점검을 실행합니다.

```sh
python scripts/check_publication_privacy.py
```

프로필에는 실명·이메일 deny 목록이 모두 필요합니다. 닉네임 전용 manifest, 공유 scanner를 이용한 로컬 Git `--all` 신원·메시지·ref 이름, 공개 GitHub 프로필(name은 null·빈값·battle-doll·배틀돌, email은 null), PR 제목·본문, REST의 각 `merge_commit_sha` author/committer/메시지를 검사합니다. PR 최대100개와 각 PR당 API 최대2회를 읽으며100개가 꽉 찬 페이지·읽기 실패·시간 제한은 UNKNOWN입니다. 가져오지 않은 ref·삭제된 ref·서비스 내부 ref·과거 소스 blob·issue/comment·CI 로그·이미지 픽셀은 제외합니다. GitHub 이메일 보호 UI와 OpenAI에서 선택한 검증 신원은 확인할 수 없어 기계 검사 통과 후에도 **HOLD**, 종료코드1을 유지합니다. 수동 `--verified` 우회는 없습니다. 선택적 `--output`은 소스 밖에 정제된 JSON 기록을 저장하며 findings에는 규칙·PR 번호·건수만 남깁니다. 이 기록은 PR·업로드 승인이 아닙니다. 이 배포 관리 CLI는 skills-only에 포함되지 않으며 온톨로지 생성·MCP·HTML의 네트워크 동작을 추가하지 않습니다.

Windows·macOS·Linux를 유지합니다. AI는 읽기 전용 로컬 MCP, 사람은 요청해 생성한 오프라인 HTML을 사용합니다. 이 patch는 별도 HTML 보고서·원격 endpoint·telemetry·개인 신원 업로드 절차를 만들지 않습니다. 사용자의 모델·추론 강도도 유지합니다.

HTML 선택 복사 필드는 전체 로컬 파일 URL 대신 snapshot/entity/edge 상대 query를 사용합니다. 자유 검색어를 URL·history에 저장하거나 재생하지 않고 native JSON parse 오류 원문도 UI에 출력하지 않습니다.

최종 후보에서 소스·선택 ref·추출 패키지 개인정보 검사를 실행하고 두 exact release profile을 확인합니다. 기존0.8.0 태그를 바꾸지 않습니다. 합성 회귀 테스트는 해당 사례의 검출 동작 증거이며 실제 호스트 E2E·전문 번역·전체 접근성·외부 서비스 삭제에는 별도 증거가 필요합니다. [번역 범위](../TRANSLATION_COVERAGE.md)는5언어 가이드와 실제 범위를 명시합니다.
