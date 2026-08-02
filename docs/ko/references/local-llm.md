# 선택적 로컬 LLM enrichment

[English](../../../skills/manage-code-ontology/references/local-llm.md) | [한국어](local-llm.md) | [日本語](../../ja/references/local-llm.md) | [简体中文](../../zh-CN/references/local-llm.md)

버전 0.3.4는 기존 Ollama installation을 선택적 local inference sidecar로 사용할 수 있습니다. 결정론적 ontology는 이것 없이도 완전하며 항상 observed evidence의 source입니다.

## 동의 sequence

1. 이미 초기화된 workspace에서는 먼저 `status`를 실행합니다. enabled이면 다시 묻거나 probe 또는 configure하지 않습니다. disabled이면 사용자가 re-enablement를 명시적으로 요청하지 않는 한 다시 묻지 않습니다. `not_configured` 또는 새 workspace에 대해서만 이 sequence를 계속합니다.
2. `doctor` 또는 `local_llm.py detect`는 알려진 executable/app indicator만 검사할 수 있습니다. Detection은 process를 실행하거나 port에 접속하거나 file을 쓰지 않습니다.
3. 지원되는 Ollama가 탐지되고 initialized workspace가 있을 때만 묻습니다. 새 workspace에서는 승인된 `init`이 성공할 때까지 기다립니다. 질문하기 전에 fixed endpoint, data scope, output path, evidence class, residual risk를 공개합니다.
4. 긍정적인 응답 후에만 `probe --authorized`를 실행합니다. 이는 `127.0.0.1:11434`에만 접속하고 Ollama tag metadata가 제한된 validation을 통과한 model candidate를 나열합니다. Ollama를 시작하거나 model을 install/download하지 않습니다.
5. candidate가 정확히 하나면 name과 digest를 보여 주고 구성합니다. configuration에는 추가로 `/api/show`에서 Ollama가 보고한 model information과 completion capability가 필요합니다. candidate가 여러 개면 사용자에게 하나를 선택하도록 요청합니다. 하나도 없거나, verification에 실패하거나, Ollama를 사용할 수 없으면 아무것도 쓰지 않고 deterministic workflow를 활성 상태로 유지합니다.
6. Configuration은 workspace 범위입니다. `disable --authorized`는 기존 evidence sidecar를 보존하면서 향후 enrichment를 중단합니다.

동의 안내에는 다음 내용이 포함되어야 합니다.

> 기존 Ollama가 탐지되었습니다. 활성화하면 Companion은 기존 service의 `127.0.0.1:11434`에만 접속하고, source body, comment, arbitrary string, secret, absolute path, private file hash가 아닌 제한된 이식 가능 ontology metadata를 전송합니다. model을 설치 또는 다운로드하거나 Ollama service를 시작하지 않습니다. 승인된 enrichment는 선택한 model을 실행하고 CPU/GPU memory를 할당할 수 있으며, response 후 `keep_alive=0`으로 즉시 unload를 요청합니다. 유효한 normalized suggestion은 이 workspace 아래에 검증되지 않은 `inferred` evidence로 저장되고 observed graph에 병합되지 않습니다. Ollama 자체의 network behavior는 Companion 통제 밖에 있습니다. 기존 local model을 검사하고 이 workspace를 구성해도 될까요?

거부, timeout, 사용할 수 없는 service는 core ontology workflow의 error가 아닙니다. 같은 workflow에서 거부 후 반복해서 묻지 않습니다.

## 명령

bundled Companion script 옆의 `LOCAL_LLM`을 확인합니다.

```bash
LOCAL_LLM="$SKILL_DIR/scripts/local_llm.py"

python3 "$LOCAL_LLM" detect
python3 "$LOCAL_LLM" probe --authorized
python3 "$LOCAL_LLM" configure \
  --workspace "/absolute/path/to/workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 "$LOCAL_LLM" status --workspace "/absolute/path/to/workspace"
python3 "$LOCAL_LLM" enrich \
  --workspace "/absolute/path/to/workspace" \
  --authorized
python3 "$LOCAL_LLM" disable \
  --workspace "/absolute/path/to/workspace" \
  --authorized
```

활성화한 후에는 사용자가 요청한 관련 ontology analysis 중 deterministic snapshot이 current인 경우에만 `enrich`를 사용합니다. 저장된 workspace consent는 이후 해당 workspace의 on-demand enrichment를 허용하지만 사용 사실을 매번 보고합니다. `init`, `sync`, `watch`, full/local 프로필의 모든 MCP tool은 helper를 암묵적으로 호출하지 않습니다.

## 고정된 데이터 및 네트워크 경계

helper는 다음과 같이 동작합니다.

- literal IPv4 loopback host `127.0.0.1`과 port `11434`를 통한 Ollama만 지원합니다.
- arbitrary URL, DNS name, LAN/public address, proxy routing, redirect, API key, 보고된 remote/cloud marker, 누락되거나 잘못된 Ollama-reported model metadata를 거부합니다.
- 제한된 name 및 repository-relative path와 함께 code-symbol candidate 최대 80개, candidate당 observed relation 최대 12개만 보냅니다.
- source body, comment, arbitrary string literal, environment variable, credential, absolute path, source fingerprint, private source manifest, raw file hash를 제외합니다.
- strict schema, bounded response size 및 timeout, `keep_alive=0`을 사용하여 non-streaming temperature-zero JSON response를 요청하므로 Ollama에 response 후 즉시 model unload를 요청합니다.
- duplicate key, non-finite number, unknown node, unsupported role, duplicate suggestion, malformed JSON, oversized output을 거부합니다.

`localMetadataVerified=true`의 의미는 의도적으로 제한됩니다. Ollama의 `/api/tags` 및 `/api/show` response가 보고한 digest, size, format, model information, completion capability, remote-marker field가 이러한 check를 통과했다는 뜻입니다. model weight byte를 검증하거나 loopback에서 듣는 process를 인증하거나 inference가 local에서 실행되었거나 Ollama가 outbound request를 만들지 않았음을 증명하지 않습니다. `/api/chat`의 remote/cloud marker도 거부되지만, 공개된 candidate metadata가 service에 도달한 후에만 가능합니다.

Loopback은 Companion이 request를 어디로 보내는지만 증명합니다. 별도로 관리되는 Ollama process가 외부와 전혀 통신하지 않는다는 것을 증명할 수 없습니다. air-gapped 보장이 필요한 사용자는 operating-system 및 Ollama configuration layer에서 이를 강제하거나 enrichment를 비활성화해야 합니다.

Inference는 실제 local compute action입니다. Ollama는 응답하는 동안 model weight를 CPU 또는 GPU memory에 load하고 compute를 사용할 수 있습니다. `keep_alive=0`은 response 후 immediate unload를 요청하지만 Companion은 Ollama의 resource release나 API contract 밖의 override behavior를 보증할 수 없습니다.

## 증거 및 보존

Configuration은 선택한 workspace의 mode-`0600` `local-llm.json`으로 저장됩니다. provider, fixed endpoint, selected model name 및 digest, capability metadata, consent version, data-scope version을 포함합니다. API key, executable path, arbitrary URL, repository path는 포함하지 않습니다.

성공한 각 run은 다음 위치에 mode-`0600`, create-only sidecar 하나를 생성합니다.

```text
enrichments/<snapshot-id>/<run-id>.json
```

sidecar는 normalized suggestion, model 및 schema provenance, input/ontology digest, exact false authority만 보존합니다. Raw prompt와 raw model response는 보존하지 않습니다. `ontology.json`, RDF, full/local 전용 runtime binding, target source, lineage evidence를 수정하지 않습니다. suggestion은 `inferred`이며 confidence로 인해 observed, validated 또는 approved가 되지 않습니다.
