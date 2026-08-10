# 公式プラグイン提出ノート

[English](../../SUBMISSION.md) | [한국어](../ko/SUBMISSION.md) | [日本語](SUBMISSION.md) | [简体中文](../zh-CN/SUBMISSION.md)

## 掲載情報

- 名前: Code Ontology Companion
- バージョン: 0.4.0
- 開発者: battle-doll
- カテゴリ: Developer Tools
- 配布: Public
- 提出タイプ: Skills only
- コンポーネント: deterministic ontology skill と CLI、offline workbench、オプションの同意ベース Ollama helper、local MCP setup workflow
- GitHub package: 同じ skill と同梱の cross-platform read-only stdio MCP server
- ライセンス: Apache-2.0

短い説明:

> RDF リネージを備えたローカルコードグラフ

長い説明:

> 許可された Java、Spring、Python repository を静的にマッピングし、不変のローカル knowledge-graph snapshot を作成します。変更による影響の可能性を調査し、version を比較し、evidence lineage を保持し、RDF 1.1 Turtle を export し、自己完結型の offline visualization を開きます。Deterministic analysis は target code を実行せず、network request を行いません。既存 Ollama が検出された場合、ユーザーは observed evidence と分離された範囲限定の loopback-only inference を別途許可できます。Model の install や Ollama の起動は行わず、許可された enrichment は選択した model を実行し、response 後の即時 unload を要求します。

## アクセスおよびデータ利用に関する宣言

| 領域 | バージョン 0.4.0 の動作 |
| --- | --- |
| 認証 | なし |
| 直接 network access | Deterministic analyzer/workspace はなし。明示的な同意後、オプション helper は固定 `127.0.0.1:11434` だけを使用 |
| 外部 API | オプションの既存 local Ollama API のみ。remote／publisher API はなし |
| telemetry/analytics | なし |
| target-code execution | なし |
| 読み取り | 明示的な repository path 内で許可された通常の `.java` および `.py` file |
| 除外 | Secret に似た name、key、env file、link/reparse point、VCS、dependency、build output、cache、special／oversized file |
| 書き込み | Repository 外の新しい explicit workspace、不変 refresh snapshot、追記型 lineage、別途 local-LLM 同意後の private workspace configuration と create-only inferred sidecar（POSIX mode `0600`、Windows inherited workspace ACL） |
| private local state | Absolute repository path、file ごとの relative path/size/SHA-256、workspace/snapshot/event ID、オプションの Git revision。有効時は local model name/digest/capability と normalized inferred suggestion |
| portable artifact | Symbol、relationship、language、qualified name、validated policy identifier、relative path、count、RDF/Turtle、lineage、offline HTML |
| 保持しないもの | Source body、comment、arbitrary string literal、policy value、credential、raw prompt、raw model response |
| upload | なし |
| background service | なし。オプション watcher は明示的な foreground-only |
| MCP | オプションの local stdio server、read-only、listening port なし、登録 workspace ID のみ。Windows、macOS、Linux setup は skill bundle に記載 |
| MCP write | なし |
| hook/app/widget | なし |
| package/model/database install | なし |
| local LLM の必須性 | 必須ではない。Workspace 単位の同意後、既存 Ollama をオプションで使用し、install/download/Ollama-service start は行わない。Enrichment は request ごとに最大 20 candidate／16 KiB、`think=false`、`num_ctx=8192`、`num_predict=2048`、最大 180 秒 timeout、atomic sidecar publication、`keep_alive=0` を使用 |

## ローカル MCP annotation

7 個の MCP tool はすべて次の annotation を設定します。

- `readOnlyHint: true`
- `openWorldHint: false`
- `destructiveHint: false`
- `idempotentHint: true`

Tool は workspace 一覧、status、search、static neighbor、history、snapshot comparison、lineage を提供します。Initialization、refresh、lineage write、installation、deletion、upload、target execution、arbitrary path access は MCP から公開しません。Windows／macOS／Linux の完全な configuration と検証手順は、[読み取り専用ローカル MCP ガイド](references/local-mcp.md)に従います。

## レビューの根拠

この release は cloud account、remote service、graph database、model なしで独立した deterministic value を提供します。次の workflow を要求します。

1. repository authorization
2. no-write preflight
3. repository 外の explicit workspace
4. initialization 前の explicit authorization
5. runtime／causal claim ではなく static-evidence language を使用
6. オプションの loopback model inspection または workspace configuration 前の、別個の disclosure と consent

Analyzer は authorization flag、output separation、link/reparse/special-file avoidance、sensitive-path exclusion、source-size limit、deterministic path の network access 禁止、target execution 禁止を独立して強制します。Refresh は stable manifest、staging、validation、不変 snapshot、atomic promotion を使用します。Source／release-artifact validation は supported component metadata、documentation、deterministic package content、extracted smoke behavior も確認します。

オプションの local enrichment は observed analyzer authority の一部ではありません。Indicator check は実行も接続も行いません。同意後、helper は literal IPv4 loopback だけを使用し、報告された cloud/remote marker、欠落または不正な必須 API metadata、unbounded/malformed response を拒否します。Source body、secret、absolute path、private hash を送らず、normalized output を create-only `inferred` sidecar として保存します。Ollama 自体の network behavior は、明示的に開示される residual risk です。

## 提出 package

公式 portal upload は **Skills only** タイプを使用します。Skill bundle は portable analyzer、workspace CLI、workbench、オプションの local LLM helper、Windows／macOS／Linux local MCP configuration workflow を提供します。Complete GitHub package は stdio MCP executable と automatic launcher も同梱します。

Portal-safe archive の生成:

```bash
python3 scripts/build_skills_only_release.py
```

生成 ZIP には manifest、skill、script、reference、license、notice、icon が含まれます。この Skills-only ZIP は portal の Skills upload に、complete ZIP は local plugin installation と GitHub distribution に使用します。

## 評価ケース

[evals/cases.json](../../evals/cases.json) には、preflight、initialization、Spring/Python analysis、version comparison、lineage、local-LLM consent/decline/absence と malformed response handling、MCP read boundary、unauthorized access、secret exfiltration、silent installation、MCP write を扱う positive／negative reviewer case が含まれます。Local-LLM case は範囲限定の fake response を使用し、reviewer infrastructure を必要としません。

## 法務およびポリシー資料

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

提出前に publisher は developer identity、listing、availability、release note、適用される法務／policy attestation の正確性を確認する必要があります。
