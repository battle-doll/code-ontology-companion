# 기여하기

[English](../../CONTRIBUTING.md) | [한국어](CONTRIBUTING.md) | [日本語](../ja/CONTRIBUTING.md) | [简体中文](../zh-CN/CONTRIBUTING.md)

기여는 결정론적, 로컬 우선, 최소 권한 기본값을 보존해야 합니다.

## 문서 현지화

사람이 읽는 문서를 변경할 때마다 같은 변경에서 해당 영어, 한국어, 일본어, 중국어 간체 문서를 모두 업데이트해야 합니다. 제출하기 전에 `python3 scripts/validate_documentation.py`를 실행하십시오. 개인정보, 약관, 상표, 고지, 타사 고지 자료의 번역은 정보 제공용이며 영어 원문 우선 공통 marker를 유지해야 합니다. `LICENSE` 또는 함께 제공되는 dependency license text를 번역하거나 교체하지 마십시오.

변경을 제안하기 전:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

## 버전 및 릴리스 기록

추적되는 모든 릴리스 변경에는 새 semantic version과 날짜가 적힌 `CHANGELOG.md` 항목이 필요합니다. 기본적으로 patch version을 사용하고, 변경이 기능을 확장하거나 호환성을 깨는 경우 minor 또는 major version을 사용합니다. CI는 pull request를 base branch와 비교하고 main branch push를 이전 revision과 비교합니다. manifest version이 해당 baseline보다 크고 새 changelog 항목이 맨 앞에 있지 않으면 추적된 변경은 실패합니다.

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
