# 계보 모델

[English](../../../skills/manage-code-ontology/references/lineage-model.md) | [한국어](lineage-model.md) | [日本語](../../ja/references/lineage-model.md) | [简体中文](../../zh-CN/references/lineage-model.md)

lineage를 사용하여 실제로 변경된 것과 변경에 관해 단지 추론된 것을 구분합니다. local journal은 append-only입니다. `lineage.ttl`은 PROV-O-compatible activity와 Companion evidence class를 사용하여 event를 내보냅니다.

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

current release는 transaction time, 즉 Companion이 event를 저장한 시점을 기록합니다. fact가 그보다 일찍 효력을 갖게 되었다면 향후 schema에 별도의 valid-time property가 추가될 때까지 그 날짜를 human-readable summary에 넣으십시오. 수정된 effective date를 흉내 내려고 이전 event를 overwrite하지 말고 correcting event를 append하십시오.

## 이식 가능한 identifier

- Workspace ID 및 event ID는 random local UUID입니다.
- Snapshot ID는 UTC time과 source fingerprint prefix를 결합합니다.
- Code entity ID는 RDF compatibility를 위해 Explorer 1.0 vocabulary를 유지합니다.
- Absolute repository path와 full source fingerprint는 private local configuration 또는 manifest에 남으며, 일반 RDF, HTML, MCP response에서는 노출되지 않습니다.
