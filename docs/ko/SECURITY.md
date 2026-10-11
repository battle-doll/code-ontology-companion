# 보안 정책

[English](../../SECURITY.md) | [한국어](SECURITY.md) | [日本語](../ja/SECURITY.md) | [简体中文](../zh-CN/SECURITY.md) | [Русский](../ru/SECURITY.md)

## 지원 버전

보안 수정은 최신 공개 버전에 제공됩니다. 2026-08-29 확인 기준으로 버전 0.5.3이 공개되었고 정확한 이름의 공개 디렉터리 검색에 표시됩니다.

## 취약점 신고

공개 issue에 private source, secret, credential, local absolute path, ontology artifact를 포함하지 마십시오.

다음 저장소의 GitHub private vulnerability reporting을 사용하십시오.

https://github.com/battle-doll/code-ontology-companion

private reporting을 사용할 수 없다면 exploit detail이나 confidential data 없이 private channel을 요청하는 최소한의 public issue를 여십시오.

## 보안 모델

0.9.0 공개 후보의 보안 모델입니다. 위의 공개 확인은 과거 이력이며 후보의 공개 완료를 뜻하지 않습니다.

- static parsing을 수행하며 target code를 import하거나 execute하지 않습니다.
- link/reparse point인 repository 및 workspace root를 거부합니다.
- link-like, special, sensitive-name, dependency, VCS, generated file을 건너뜁니다.
- per-file, total-source, source-count, graph, impact, HTTP, candidate, suggestion limit를 강제합니다.
- 기본 3D 공간 지도는 그룹·심볼·관계·깊이 상한과 프레임 목표를 적용하고 숨겨진 화면의 애니메이션을 멈춥니다. 선택적 페이지형 텍스트 대안을 제공하며 CDN, WebGL 의존성, worker, network primitive를 추가하지 않습니다.
- 링크를 열기 전에 snapshot/entity/relationship/evidence ID 연결을 검증하며, 오래되거나 무관한 근거를 다른 근거로 대체하지 않습니다.
- repository 외부의 새롭고 명시적인 workspace에만 artifact를 생성합니다.
- refresh를 staging에서 빌드하고 immutable snapshot을 원자적으로 승격합니다.
- analyzer 또는 Companion version이 바뀌면 변경되지 않은 repository도 refresh합니다.
- refresh 실패 후 마지막 정상 snapshot을 유지합니다.
- deterministic analysis, workspace operation, workbench와 MCP를 network-free로 유지하고 telemetry를 수집하지 않습니다.
- 선택적 Ollama를 실행하거나 port를 probe하거나 기록하지 않고 탐지합니다.
- 별도 helper가 `127.0.0.1:11434`에만 접속하기 전에 명시적인 workspace 범위 동의를 요구하고, 보고된 remote/cloud marker 또는 API metadata 누락을 거부하며, output을 검증되지 않은 create-only inferred sidecar로만 저장합니다.
- Codex host가 활성화한 경우에만 read-only stdio MCP process를 시작합니다.
- MCP는 port를 열지 않고 filesystem path 대신 등록된 workspace ID를 받습니다.
- MCP는 write, refresh, install, delete, upload, execution tool을 노출하지 않습니다.
- runtime, package, database, model, daemon, background watcher를 설치하지 않습니다.

선택적 helper는 Ollama를 신뢰할 수 있는 analyzer의 일부로 만들지 않습니다. Ollama 자체 networking, logging, model behavior, security는 Companion 경계 외부에 있습니다. loopback-only delivery가 충분한 보장이 아니라면 enrichment를 비활성화하거나 operating-system control을 적용하십시오. Enrichment는 선택한 model을 실행하여 CPU/GPU memory를 할당할 수 있습니다. helper는 response 후 즉시 unload를 요청하도록 `keep_alive=0`을 보내지만, 별도로 관리되는 service가 실제로 resource를 release했음을 보증할 수 없습니다. `localMetadataVerified=true`는 Ollama가 보고한 API metadata의 validation이지 model weight, loopback-service identity, local execution, outbound Ollama traffic 부재에 대한 attestation이 아닙니다.

생성된 output을 자동으로 공개해도 안전한 것은 아닙니다. symbol과 relative path가 confidential architecture를 드러낼 수 있습니다.

## 0.9.0 개인정보 통제와 공개 증거

설정된 비공개 HMAC-SHA256 프로필은 공개 소스에 실명·개인 이메일 원문을 넣지 않고 지원하는 생성 산출물·읽기 응답의 지정 식별자를 거부할 수 있습니다. 키·지문이 있는 프로필 자체도 비공개이며 보호 소스·출력 루트 밖에 보관하고 공개 산출물로 만들지 않습니다. 선택 프로필이 없으면 실명 보호가 확인되지 않습니다. 제한된 텍스트·인코딩 검사는 알 수 없는 모든 이름·임의 바이너리나 이미지 메타데이터·타사 출력의 보편적 검출기가 아니며 POSIX 권한 검사는 Windows ACL을 인증하지 않습니다.

공개 PR 전에 실제 GitHub 계정 이메일 보호의 최신 신뢰 확인 기록과 선택한 소스·서비스 자동 생성 commit ref 감사를 요구합니다. 로컬 git 설정·수동 주장·합성 테스트·HEAD만의 검사는 대체 증거가 아닙니다. 보관된 ref 노출은 서비스 제거 확인 전까지 미해결입니다. 공개 개발자 신원이 battle-doll 외 개인정보를 표시할 수 있으면 공식 업로드·제출·게시를 HOLD합니다. 개인정보 통제는 신원 업로드 기능·telemetry·별도 HTML 보고서를 만들지 않습니다.

[개인정보 운영 가이드](PRIVACY_OPERATIONS.md)를 참조합니다. 테스트·서비스 확인·업로드·제출·승인·게시를 별도 증거로 유지합니다.
