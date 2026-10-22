# 기여하기

[English](../../CONTRIBUTING.md) | [한국어](CONTRIBUTING.md) | [日本語](../ja/CONTRIBUTING.md) | [简体中文](../zh-CN/CONTRIBUTING.md) | [Русский](../ru/CONTRIBUTING.md)

기여는 결정론적, 로컬 우선, 최소 권한 기본값을 보존해야 합니다.

## 문서 현지화

사람이 읽는 문서를 변경할 때마다 같은 변경에서 해당 영어, 한국어, 일본어, 중국어 간체, 러시아어 문서를 모두 업데이트해야 합니다. 제출하기 전에 `python3 scripts/validate_documentation.py`를 실행하십시오. 개인정보, 약관, 상표, 고지, 타사 고지 자료의 번역은 정보 제공용이며 영어 원문 우선 공통 marker를 유지해야 합니다. `LICENSE` 또는 함께 제공되는 dependency license text를 번역하거나 교체하지 마십시오.

변경을 제안하기 전:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

## 버전 및 릴리스 기록

추적되는 모든 릴리스 변경에는 새 A.B.C 제품 버전과 날짜가 적힌 `CHANGELOG.md` 항목이 필요합니다. A는 완전히 다른 상품, B는 같은 상품의 대규모 변경, C는 기존 상품의 일부 기능 개선·수정을 뜻합니다. 기능이 추가됐다는 이유만으로 B를 올리지 않습니다. 현재 작업은 0.8.x 계열을 유지합니다. CI는 PR을 기준 브랜치와, main push를 이전 revision과 비교하며 후보 버전은 정규화된 기준 버전보다 크고 날짜가 있는 변경 항목이 맨 앞에 있어야 합니다. 명시적으로 기록된 미공개 0.9.0 후보 기준에만 0.8.2 대응을 적용하며 임의 버전 하향을 허용하지 않습니다. 기존 배포 태그·커밋 해시·압축파일 식별자와 과거 증거는 보존합니다.

릴리스를 게시하기 전:

1. plugin manifest, runtime constant, SBOM, evaluation metadata, release validator, CI artifact path, test, current-version documentation의 version을 동기화합니다.
2. 최종 source state에서 전체 test suite와 package validator를 실행합니다.
3. 결정론적 release profile 두 개를 각각 두 번 다시 빌드하고 검증하여 byte와 checksum이 일치하는지 확인합니다.
4. release archive와 추출된 CLI의 `--help` smoke test가 지원 명령, 문서, manifest를 일관되게 검증하는지 확인합니다.
5. 최종 commit된 source state에서 등록된 self-ontology를 refresh하고, declared version-policy와 validated release-evidence event를 lineage에 append합니다.
6. final commit과 필수 CI check가 완료된 후에만 release tag를 생성합니다. 게시된 release tag를 이동하거나 교체하지 마십시오.

synthetic fixture만 사용하십시오. private repository, third-party source excerpt, credential, real-project ontology artifact, model weight, 복사한 proprietary schema를 commit하지 마십시오.

network access, target execution, package installation, authentication, telemetry, persistent service, hook, write-capable MCP, external database, automatic model download를 추가하는 변경에는 별도 설계와 업데이트된 privacy, security, threat model, test, SBOM, submission review가 필요합니다.

기여함으로써 귀하는 Apache-2.0에 따라 해당 작업을 라이선스할 권리가 있음을 진술합니다.

## 0.8.3 개인정보 통제와 공개 증거

설정된 비공개 HMAC-SHA256 프로필은 공개 소스에 실명·개인 이메일 원문을 넣지 않고 지원하는 생성 산출물·읽기 응답의 지정 식별자를 거부할 수 있습니다. 키·지문이 있는 프로필 자체도 비공개이며 보호 소스·출력 루트 밖에 보관하고 공개 산출물로 만들지 않습니다. 선택 프로필이 없으면 실명 보호가 확인되지 않습니다. 제한된 텍스트·인코딩 검사는 알 수 없는 모든 이름·임의 바이너리나 이미지 메타데이터·타사 출력의 보편적 검출기가 아니며 POSIX 권한 검사는 Windows ACL을 인증하지 않습니다.

공개 PR 전에 실제 GitHub 계정 이메일 보호의 최신 신뢰 확인 기록과 선택한 소스·서비스 자동 생성 commit ref 감사를 요구합니다. 로컬 git 설정·수동 주장·합성 테스트·HEAD만의 검사는 대체 증거가 아닙니다. 보관된 ref 노출은 서비스 제거 확인 전까지 미해결입니다. 공개 개발자 신원이 battle-doll 외 개인정보를 표시할 수 있으면 공식 업로드·제출·게시를 HOLD합니다. 개인정보 통제는 신원 업로드 기능·telemetry·별도 HTML 보고서를 만들지 않습니다.

[개인정보 운영 가이드](PRIVACY_OPERATIONS.md)를 참조합니다. 테스트·서비스 확인·업로드·제출·승인·게시를 별도 증거로 유지합니다.
