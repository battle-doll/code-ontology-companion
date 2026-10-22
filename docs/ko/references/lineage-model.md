# 계보 모델

[English](../../../skills/manage-code-ontology/references/lineage-model.md) | [한국어](lineage-model.md) | [日本語](../../ja/references/lineage-model.md) | [简体中文](../../zh-CN/references/lineage-model.md) | [Русский](../../ru/references/lineage-model.md)

비공개 추가형 `lineage.jsonl` journal로 기록된 변경과 추론을 구분합니다. `lineage.ttl`은 근거로 제한한 PROV-O 부분집합의 별도 교환용 출력입니다. journal 기록은 설명하는 활동 자체가 아닌 정보 엔터티입니다.

## 증거 class

- `observed`: source 또는 workspace state에서 결정론적으로 추출됨
- `declared`: 사용자 또는 제공된 decision record가 진술함
- `inferred`: analyzer 또는 model이 제안했으며 독립적으로 확인되지 않음
- `validated`: 이름이 명시된 test, review, replay 또는 기타 재현 가능한 check가 뒷받침함
- `approved`: 책임자 또는 governance process가 명시적으로 승인함

confidence나 repetition만을 근거로 `inferred`를 `validated`로 다시 작성하지 마십시오. 선택적 local LLM suggestion은 이 lineage journal이 아니라 private enrichment sidecar에 저장됩니다. 별도의 재현 가능한 validation 또는 responsible-person approval이 명시적으로 기록될 때까지 `inferred`로 유지됩니다. model의 confidence value는 provenance이지 validation이 아닙니다.

## 핵심 event sequence

```text
결정
  -> 변경
  -> 검증
  -> 활성화
  -> 관찰
  -> 결과
  -> 유지 / 롤백 / 대체됨
```

Code, deployment, activation, outcome은 별도 event입니다. commit은 deployment를 증명하지 않고, deployment는 runtime activation을 증명하지 않으며, change와 가까운 outcome은 그 change가 원인이었음을 증명하지 않습니다.

## 시간 semantic

current release는 transaction time, 즉 Companion이 event를 저장한 시점을 기록합니다. fact가 그보다 일찍 효력을 갖게 되었다면 그 날짜를 human-readable summary에 넣으십시오. 수정된 effective date를 흉내 내려고 이전 event를 overwrite하지 말고 correcting event를 append하십시오.

## 이식 가능한 identifier

- Workspace ID 및 event ID는 random local UUID입니다.
- Snapshot ID는 UTC time과 source fingerprint prefix를 결합합니다.
- Code entity ID는 RDF compatibility를 위해 Explorer 1.0 vocabulary를 유지합니다.
- Absolute repository path와 full source fingerprint는 private local configuration 또는 manifest에 남으며, 일반 RDF, HTML, MCP response에서는 노출되지 않습니다.


## 0.8.3 PROV-O 부분집합과 개인정보 경계

기존 event URI의 기록은 `coc:LineageRecord`, `prov:Entity`입니다. 기록 시각은 `coc:recordedAt`이며 유효한 timezone ISO 값은 `xsd:dateTime`, 잘못되거나 timezone이 없는 과거 값은 plain literal로 유지합니다. 활동의 시작·종료 시각을 만들지 않습니다.

저장된 `observed` 스냅샷 확정 기록을 일반 파일인 `snapshot.json`·`source-manifest.json`과 대조한 경우에만 별도의 `coc:SnapshotBuild` / `prov:Activity`, `coc:OntologySnapshot` / `prov:Entity`, `coc:ScopedSource` / `prov:Entity`를 추가합니다. run ID·workspace/snapshot ID·trigger·생성 시각·revision·소스 범위·재계산한 종합 SHA-256을 확인합니다. 기록→build는 `coc:describesBuild`, build→선택 소스는 `prov:used`, snapshot→build는 `prov:wasGeneratedBy`, snapshot→선택 소스는 `prov:wasDerivedFrom`입니다. snapshot의 `prov:generatedAtTime`은 대조한 metadata에서 가져옵니다. 앞서 대조된 확정 기록이 있으면 사용자 정의 `coc:previousSnapshot`만 추가하며 이전 snapshot에서 파생됐다는 PROV 추정을 하지 않습니다.

대조 조건이 없으면 기록을 유지하고 생성 관계를 생략합니다. 저장된 로컬 근거 확인이며 현재 소스를 다시 관측하거나 journal을 암호학적으로 인증하지 않습니다. `prov:Agent`/Person·인간 귀속·추정 실행 시각·완전한 계보·PROV 준수 인증을 주장하지 않습니다. MCP는 JSON/JSONL journal 계약을 읽고 Turtle은 교환용 출력입니다. 파일별 hash는 비공개 manifest에, 선택 범위의 종합 지문은 비공개 snapshot JSON metadata에도 남을 수 있습니다. 일반 RDF/HTML/MCP에는 전체 지문·절대 저장소 루트를 노출하지 않습니다.

설정된 HMAC-SHA256 검사는 원시 새 event·기존 journal·준비한 Turtle을 쓰기 전에 검사합니다. 개인정보가 있으면 전체를 거부하며 몰래 기록을 누락하지 않습니다. 기록에는 상대 경로를 권장합니다. 임의 I/O 실패에서 두 파일의 단일 트랜잭션을 보장하지 않으며, 선택적 프로필이 없으면 모든 실명을 검출하지 않습니다.

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
