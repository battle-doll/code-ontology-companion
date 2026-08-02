# 공개 플러그인 제출 참고 사항

[English](../../SUBMISSION.md) | [한국어](SUBMISSION.md) | [日本語](../ja/SUBMISSION.md) | [简体中文](../zh-CN/SUBMISSION.md)

## 등록 정보

- 이름: Code Ontology Companion
- 버전: 0.3.3
- 개발자: battle-doll
- 카테고리: Developer Tools
- 배포: Public
- 공개 profile: Skills-only
- Local/full profile: 하나의 skill과 bundled local read-only stdio MCP server
- 라이선스: Apache-2.0

짧은 설명:

> RDF 계보를 갖춘 로컬 코드 그래프

긴 설명:

> 사용 권한이 있는 Java, Spring 또는 Python 저장소를 불변 로컬 지식 그래프 스냅샷으로 정적으로 매핑합니다. 가능한 변경 영향을 검사하고, 버전을 비교하고, 증거 계보를 보존하고, RDF 1.1 Turtle을 내보내며, 자체 완결형 오프라인 시각화를 엽니다. 결정론적 분석은 대상 코드를 실행하지 않고 네트워크 요청을 하지 않습니다. 기존 Ollama가 탐지되면 사용자는 관찰된 증거와 분리되고 검증되지 않은 상태를 유지하는 제한된 loopback-only inference를 별도로 승인할 수 있습니다. 어떤 것도 모델을 설치하거나 Ollama를 시작하지 않습니다. 승인된 enrichment는 선택된 모델을 실행하고 응답 후 즉시 unload를 요청합니다.

## 접근 및 데이터 사용 선언

| 영역 | 버전 0.3.3 동작 |
| --- | --- |
| 인증 | 없음 |
| 직접 네트워크 접근 | 결정론적 analyzer/workspace/MCP: 없음. 명시적 동의 후 선택적 helper: 고정 `127.0.0.1:11434`만 |
| 외부 API | 선택적인 기존 local Ollama API만 사용, remote 또는 publisher API 없음 |
| 원격 측정/분석 | 없음 |
| 대상 코드 실행 | 없음 |
| 읽기 | 명시적 repository path 아래에서 사용 권한이 있는 regular `.java` 및 `.py` file; 선택적 runtime binding에는 명시적인 JSON 또는 `policy-json` document 하나 |
| 제외 | secret처럼 보이는 이름, key, env file, link/reparse point, VCS, dependency, build output, cache, special 및 oversized file |
| 쓰기 | repository 외부의 새로운 명시적 workspace, immutable refresh snapshot과 append-only lineage; 명시적 승인 후 create-only mode-`0400` runtime-binding receipt 하나; 별도 local-LLM 동의 후 mode-`0600` workspace configuration과 create-only inferred sidecar |
| 비공개 로컬 상태 | absolute repository path, file별 relative path/size/SHA-256, workspace/snapshot/event ID, 선택적 Git revision; 활성화된 경우 local model name/digest/capability 및 normalized inferred suggestion |
| 이식 가능한 artifact | symbol, relationship, language, qualified name, validated policy identifier, relative path, count, RDF/Turtle, lineage, offline HTML |
| 보존하지 않음 | source body, comment, arbitrary string literal, policy value, credential, raw prompt, raw model response |
| 업로드 | 없음 |
| 백그라운드 서비스 | 없음. 선택적 watcher는 명시적인 foreground-only |
| MCP | public Skills-only archive에서 제외. Full/local profile: stdio, read-only, port 없음, 등록된 workspace ID만 |
| MCP 쓰기 | 없음 |
| Hook/app/widget | 없음 |
| Package/model/database 설치 | 없음 |
| Local LLM 필수 여부 | 아니요. workspace 범위 동의 후 선택적인 기존 Ollama만 사용하며 install/download/Ollama-service start 없음. Enrichment는 선택한 model을 실행하고 `keep_alive=0`을 전송함 |

## 도구 annotation

MCP 도구 7개 모두 다음을 설정합니다.

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

도구는 workspace 목록 조회, status 읽기, search, static neighbor 검사, history 목록 조회, snapshot 비교, lineage 읽기를 수행합니다. Initialization, refresh, lineage write, installation, deletion, upload, target execution, arbitrary path access는 MCP를 통해 노출하지 않습니다.

선택적 `runtime-binding` command는 CLI-only로 유지됩니다. 정확한 false authority는 candidate generation/gating, approval, promotion, policy 또는 runtime write, order submission, network access, funds transfer를 금지합니다. 버전 0.3.3은 owner 및 mode-`0400` semantic을 강제할 수 있는 macOS/POSIX에서만 정확한 receipt를 생성하며, 이 command는 Windows에서 fail closed 처리됩니다.

## 검토 근거

이 릴리스는 cloud account, remote service, graph database, model 없이 독립적인 결정론적 가치를 제공합니다. 다음이 필요합니다.

1. repository authorization
2. no-write preflight
3. repository 외부의 명시적 workspace
4. initialization 전 explicit authorization
5. create-only runtime-binding receipt 전 explicit authorization
6. runtime 또는 causal claim 대신 static-evidence language 사용
7. 모든 선택적 loopback model inspection 또는 workspace configuration 전 별도의 명시적 disclosure와 consent

분석기는 authorization flag, output separation, link/reparse/special-file avoidance, sensitive-path exclusion, source-size limit, deterministic-path network access 금지, target execution 금지를 독립적으로 강제합니다. Refresh는 stable manifest, staging, validation, immutable snapshot, atomic promotion을 사용합니다. Runtime-binding은 추가로 active source에서 graph를 다시 빌드하고 frozen snapshot과 정확한 semantic node/edge를 비교하며 test-only 또는 unused path 및 알려진 active-policy shadow를 거부하고 canonical self-/externally-hashed mode-`0400` output을 게시합니다. `runtimeEffective=true`는 알려진 supplied-policy shadowing이 없는 static production-branch reachability만 뜻합니다. execution, order, safety, profit causation을 증명하지 않습니다.

선택적 local enrichment는 observed analyzer authority의 일부가 아닙니다. indicator check는 아무것도 실행하거나 연결하지 않습니다. 동의 후 helper는 literal IPv4 loopback만 사용하고, 보고된 cloud/remote marker, 누락되거나 잘못된 필수 API metadata, 제한되지 않거나 malformed response를 거부하며, source body/secret/absolute path/private hash를 보내지 않고 normalized output을 create-only `inferred` sidecar로 저장합니다. Ollama 자체의 network behavior는 명시적으로 공개된 residual risk로 남습니다.

## 제출 transport 참고 사항

full/local profile의 bundled MCP transport는 local stdio이며 의도적으로 public HTTPS endpoint가 없습니다. 현재 공개 제출 portal이 MCP를 포함하는 모든 plugin에 public MCP URL을 요구한다면 placeholder를 입력하거나 transport를 잘못 표시하지 마십시오. 문서화된 bundled-stdio 경로를 통해서만 제출하거나, MCP claim을 생략하는 별도 검토된 skills-only package를 생성하십시오.

현재 portal의 **With MCP** 경로에는 production HTTPS MCP URL, domain verification, current tool scan, demo recording이 필요합니다. bundled local stdio server를 해당 URL로 받지 않습니다. 따라서 승인 지향 public profile은 **Skills only**이며, personal/local distribution은 bundled MCP server를 유지합니다.

portal-safe archive를 다음과 같이 빌드합니다.

```bash
python3 scripts/build_skills_only_release.py
```

생성된 ZIP에는 manifest, skill, script, reference, license, notice, icon이 포함됩니다. 생성된 manifest는 `mcpServers`를 생략하고 archive는 skills-only upload 요건에 따라 `.mcp.json`과 `mcp/`를 생략합니다. skills-only submission form에서 이것을 full local ZIP으로 바꾸지 마십시오.

## 평가 사례

[evals/cases.json](../../evals/cases.json)에는 preflight, initialization, Spring/Python analysis, version comparison, lineage, local-LLM consent/decline/absence 및 malformed response handling, MCP read boundary, unauthorized access, secret exfiltration, silent installation, MCP write를 다루는 최소 5개의 positive case와 3개의 negative reviewer case가 포함됩니다. Local-LLM case는 제한된 fake response를 사용하며 reviewer infrastructure가 필요하지 않습니다.

## 법률 및 정책 자료

- [LICENSE](../../LICENSE)
- [NOTICE](NOTICE.md)
- [PRIVACY.md](PRIVACY.md)
- [TERMS.md](TERMS.md)
- [SECURITY.md](SECURITY.md)
- [THREAT_MODEL.md](THREAT_MODEL.md)
- [SUPPORT.md](SUPPORT.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TRADEMARKS.md](TRADEMARKS.md)
- [SBOM.spdx.json](../../SBOM.spdx.json)

publisher는 직접 developer identity를 확인하고, listing 및 availability field를 검토하고, portal에서 요구하는 domain 또는 credential을 제공하며, 법률/정책 attestation을 수락해야 합니다. 자동화된 agent는 publisher를 대신해 attestation해서는 안 됩니다.
