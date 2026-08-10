# 공개 플러그인 제출 참고 사항

[English](../../SUBMISSION.md) | [한국어](SUBMISSION.md) | [日本語](../ja/SUBMISSION.md) | [简体中文](../zh-CN/SUBMISSION.md)

## 등록 정보

- 이름: Code Ontology Companion
- 버전: 0.4.0
- 개발자: battle-doll
- 카테고리: Developer Tools
- 배포: Public
- 제출 유형: Skills only
- 구성 요소: deterministic ontology skill과 CLI, offline workbench, 선택적 consent 기반 Ollama helper, local MCP setup workflow
- GitHub package: 같은 skill과 함께 제공되는 cross-platform read-only stdio MCP server
- 라이선스: Apache-2.0

짧은 설명:

> RDF 계보를 갖춘 로컬 코드 그래프

긴 설명:

> 사용 권한이 있는 Java, Spring 또는 Python repository를 불변 로컬 knowledge-graph snapshot으로 정적으로 매핑합니다. 가능한 변경 영향을 검사하고, version을 비교하고, evidence lineage를 보존하고, RDF 1.1 Turtle을 내보내며, 자체 완결형 offline visualization을 엽니다. Deterministic analysis는 target code를 실행하지 않고 network request를 하지 않습니다. 기존 Ollama가 탐지되면 사용자는 observed evidence와 분리된 제한적 loopback-only inference를 별도로 승인할 수 있습니다. Model을 설치하거나 Ollama를 시작하지 않으며, 승인된 enrichment는 선택한 model을 실행하고 response 후 즉시 unload를 요청합니다.

## 접근 및 데이터 사용 선언

| 영역 | 버전 0.4.0 동작 |
| --- | --- |
| 인증 | 없음 |
| 직접 network access | Deterministic analyzer/workspace는 없음. 명시적 동의 후 선택적 helper는 고정 `127.0.0.1:11434`만 사용 |
| 외부 API | 선택적인 기존 local Ollama API만 사용, remote 또는 publisher API 없음 |
| telemetry/analytics | 없음 |
| target-code execution | 없음 |
| 읽기 | 명시적 repository path 아래에서 사용 권한이 있는 regular `.java` 및 `.py` file |
| 제외 | Secret처럼 보이는 name, key, env file, link/reparse point, VCS, dependency, build output, cache, special 및 oversized file |
| 쓰기 | Repository 외부의 새 explicit workspace, immutable refresh snapshot, append-only lineage, 별도 local-LLM 동의 후 private workspace configuration 및 create-only inferred sidecar(POSIX mode `0600`, Windows inherited workspace ACL) |
| private local state | Absolute repository path, file별 relative path/size/SHA-256, workspace/snapshot/event ID, 선택적 Git revision. 활성화 시 local model name/digest/capability와 normalized inferred suggestion |
| portable artifact | Symbol, relationship, language, qualified name, validated policy identifier, relative path, count, RDF/Turtle, lineage, offline HTML |
| 보존하지 않음 | Source body, comment, arbitrary string literal, policy value, credential, raw prompt, raw model response |
| upload | 없음 |
| background service | 없음. 선택적 watcher는 명시적인 foreground-only |
| MCP | 선택적 local stdio server, read-only, listening port 없음, 등록 workspace ID만 사용. Windows, macOS, Linux setup은 skill bundle에 문서화 |
| MCP write | 없음 |
| hook/app/widget | 없음 |
| package/model/database 설치 | 없음 |
| local LLM 필요 여부 | 필요하지 않음. Workspace 범위 동의 후 선택적인 기존 Ollama만 사용하며 install/download/Ollama-service start 없음. Enrichment는 request당 최대 candidate 20개와 16 KiB, `think=false`, `num_ctx=8192`, `num_predict=2048`, 최대 180초 timeout, atomic sidecar publication, `keep_alive=0`을 사용 |

## 로컬 MCP annotation

MCP tool 7개는 모두 다음 annotation을 설정합니다.

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

Tool은 workspace 목록, status, search, static neighbor, history, snapshot comparison, lineage를 제공합니다. Initialization, refresh, lineage write, installation, deletion, upload, target execution, arbitrary path access는 MCP로 노출하지 않습니다. Windows/macOS/Linux의 전체 configuration과 검증 순서는 [읽기 전용 로컬 MCP 가이드](references/local-mcp.md)를 따릅니다.

## 검토 근거

이 release는 cloud account, remote service, graph database, model 없이 독립적인 deterministic value를 제공합니다. 다음 흐름을 요구합니다.

1. repository authorization
2. no-write preflight
3. repository 외부의 explicit workspace
4. initialization 전 explicit authorization
5. runtime 또는 causal claim 대신 static-evidence language 사용
6. 선택적 loopback model inspection 또는 workspace configuration 전 별도의 disclosure와 consent

Analyzer는 authorization flag, output separation, link/reparse/special-file avoidance, sensitive-path exclusion, source-size limit, deterministic path의 network access 금지, target execution 금지를 독립적으로 강제합니다. Refresh는 stable manifest, staging, validation, immutable snapshot, atomic promotion을 사용합니다. Source 및 release-artifact validation은 supported component metadata, documentation, deterministic package content, extracted smoke behavior도 확인합니다.

선택적 local enrichment는 observed analyzer authority의 일부가 아닙니다. Indicator check는 실행이나 연결을 하지 않습니다. 동의 후 helper는 literal IPv4 loopback만 사용하고, 보고된 cloud/remote marker, 누락되거나 잘못된 필수 API metadata, unbounded/malformed response를 거부합니다. Source body, secret, absolute path, private hash를 보내지 않고 normalized output을 create-only `inferred` sidecar로 저장합니다. Ollama 자체의 network behavior는 명시적으로 공개되는 residual risk입니다.

## 제출 package

공식 portal upload는 **Skills only** 유형을 사용합니다. Skill bundle은 portable analyzer, workspace CLI, workbench, 선택적 local LLM helper, Windows/macOS/Linux local MCP configuration workflow를 제공합니다. Complete GitHub package는 stdio MCP executable과 automatic launcher도 함께 제공합니다.

Portal-safe archive 생성:

```bash
python3 scripts/build_skills_only_release.py
```

생성된 ZIP은 manifest, skill, script, reference, license, notice, icon을 포함합니다. 이 Skills-only ZIP은 portal의 Skills upload에 사용하고, complete ZIP은 local plugin installation과 GitHub distribution에 사용합니다.

## 평가 사례

[evals/cases.json](../../evals/cases.json)은 preflight, initialization, Spring/Python analysis, version comparison, lineage, local-LLM consent/decline/absence와 malformed response handling, MCP read boundary, unauthorized access, secret exfiltration, silent installation, MCP write를 다루는 positive/negative reviewer case를 포함합니다. Local-LLM case는 제한된 fake response를 사용하므로 reviewer infrastructure가 필요하지 않습니다.

## 법률 및 정책 자료

- [LICENSE](../../LICENSE)
- [NOTICE](../../NOTICE)
- [PRIVACY.md](PRIVACY.md)
- [TERMS.md](TERMS.md)
- [SECURITY.md](SECURITY.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [SUPPORT.md](SUPPORT.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TRADEMARKS.md](TRADEMARKS.md)
- [SBOM.spdx.json](../../SBOM.spdx.json)

제출 전에 publisher는 developer identity, listing, availability, release note, 적용되는 법률 및 정책 attestation의 정확성을 확인해야 합니다.
