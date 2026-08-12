# オプションのローカル LLM エンリッチメント

[English](../../../skills/manage-code-ontology/references/local-llm.md) | [한국어](../../ko/references/local-llm.md) | [日本語](local-llm.md) | [简体中文](../../zh-CN/references/local-llm.md)

バージョン 0.5.0 は、既存の Ollama インストールをオプションのローカル inference sidecar として
使用できます。決定論的オントロジーはそれがなくても完全であり、常に observed evidence の
source です。

## 同意手順

1. 初期化済みの既存 workspace では、最初に `status` を実行します。有効なら、再び質問、probe、
   configure を行いません。無効なら、ユーザーが明示的に再有効化を依頼しない限り再度質問しません。
   `not_configured` または新規 workspace の場合に限り、この手順を続けます。
2. `doctor` または `local_llm.py detect` が調査できるのは、既知の executable/app indicator だけです。
   検出は process の実行、port への接続、file の書き込みを行いません。
3. サポート対象の Ollama が検出され、初期化済み workspace が利用できる場合に限り質問します。
   新しい workspace では、許可済み `init` が成功するまで待ちます。質問前に fixed endpoint、
   data scope、output path、evidence class、residual risk を開示します。
4. 肯定回答を得た後に限り、`probe --authorized` を実行します。これは `127.0.0.1:11434` だけへ
   接続し、Ollama tag metadata が範囲限定の validation を通過した model candidate を一覧表示します。
   Ollama を起動せず、model を install／download しません。
5. candidate が厳密に 1 つなら、その name と digest を示して設定します。設定にはさらに、
   `/api/show` が報告する model information と completion capability が必要です。複数の candidate が
   ある場合はユーザーに 1 つ選択してもらいます。1 つもない、検証に失敗した、Ollama が利用できない
   場合は何も書かず、決定論的ワークフローを有効なまま保ちます。
6. 設定は workspace 単位です。`disable --authorized` は既存 evidence sidecar を保持したまま、
   将来の enrichment を停止します。

同意時の開示では、次の内容を伝えなければなりません。

> 既存の Ollama が検出されました。有効にすると、Companion は 127.0.0.1:11434 上の既存
> サービスだけへ接続し、範囲を限定したポータブルなオントロジーメタデータを送信します。
> ソース本文、コメント、任意の文字列、秘密情報、絶対パス、非公開のファイルハッシュは
> 送信しません。モデルのインストール／ダウンロードや Ollama サービスの起動は行いません。
> 許可されたエンリッチメントは選択したモデルを実行し、CPU/GPU メモリを割り当てる場合があり、
> `keep_alive=0` によって応答後の即時アンロードを要求します。有効で正規化された提案は、
> このワークスペース内に未検証の `inferred` evidence として保存され、observed graph へ
> 統合されることはありません。Ollama 自体のネットワーク動作は Companion の管理外です。
> 既存のローカルモデルを調査し、このワークスペースを設定してもよろしいですか？

拒否、タイムアウト、サービスが利用できないことは、コアのオントロジーワークフローにとって
エラーではありません。同じワークフローで拒否された後、繰り返し質問してはなりません。

## コマンド

同梱 Companion script の隣にある `LOCAL_LLM` を解決します。

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

有効化後は、関連する user-requested ontology analysis の実行中、かつ deterministic snapshot が
current になった後に限り `enrich` を使用します。保存された workspace consent により、以後その
workspace に対する on-demand enrichment が許可されますが、使用のたびに報告してください。
`init`、`sync`、`watch`、すべての MCP tool は helper を暗黙に呼び出しません。

## 固定されたデータおよびネットワーク境界

helper は次のように動作します。

- literal IPv4 loopback host `127.0.0.1`、port `11434` 経由の Ollama だけをサポートします。
- 任意 URL、DNS name、LAN/public address、proxy routing、redirect、API key、報告された
  remote/cloud marker、欠落または不正な Ollama-reported model metadata を拒否します。
- 最大 80 個の code-symbol candidate と candidate ごとに 12 個の observed relation を考慮し、
  stable order で 1 request 最大 20 candidate、直列化された portable metadata 最大 16 KiB に分割します。
- source body、comment、任意の string literal、environment variable、credential、絶対 path、
  source fingerprint、private source manifest、raw file hash を除外します。
- strict schema、`think=false`、`num_ctx=8192`、`num_predict=2048`、範囲を限定した response size、
  1 request 最大 180 秒の timeout、`keep_alive=0` を指定した non-streaming、temperature-zero の
  JSON response を要求し、Ollama に各応答後の model 即時 unload を求めます。
- 許可された role vocabulary と一致する提案だけを関連付け、同一 role の重複提案は低い
  confidence で統合し、role が競合する node は除外します。duplicate key、
  non-finite number、unknown node、malformed JSON、oversized output は拒否します。

`localMetadataVerified=true` は、意図的に限定された意味を持ちます。Ollama の `/api/tags` と
`/api/show` の応答で報告された digest、size、format、model information、completion capability、
remote-marker field が、これらの検査を通過したという意味です。model weight bytes を検証せず、
loopback で待ち受ける process を認証せず、inference がローカルで実行されたことや Ollama が
outbound request を行っていないことを証明しません。`/api/chat` の remote/cloud marker も
拒否されますが、それは開示済み candidate metadata が service へ到達した後です。

loopback が証明するのは Companion が request を送る場所だけです。別途管理される Ollama process が
外部と一切通信しないことまでは証明できません。air-gapped guarantee が必要なユーザーは、OS と
Ollama の configuration layer でそれを強制するか、enrichment を無効のままにしてください。

inference は実際のローカル compute action です。Ollama は応答中に model weight を CPU／GPU memory
へ読み込み、compute を消費する場合があります。`keep_alive=0` は応答後の即時 unload を要求しますが、
Companion は API contract 外にある Ollama の resource release や override behavior を保証できません。

## Evidence と保持

設定は選択した workspace の非公開 `local-llm.json` として保存されます。POSIX では mode `0600` を
適用し、Windows ではユーザーが選択した workspace から継承した ACL を使います。provider、fixed
endpoint、選択した model name／digest、capability metadata、consent version、data-scope version を
含みます。API key、executable path、任意 URL、リポジトリ path は含みません。

全 batch が成功して検証された後に限り、実行は同じプラットフォーム別の権限境界で次の場所に
非公開の作成専用 sidecar を atomic に 1 つ作成します。

```text
enrichments/<snapshot-id>/<run-id>.json
```

失敗、未完了、または部分的な batch sequence は sidecar を残しません。

sidecar が保持するのは、正規化された suggestion、model／schema provenance、input/ontology digest、
厳密に false の authority だけです。生の prompt と raw model response は保持しません。
`ontology.json`、RDF、target source、lineage evidence を変更することはありません。
suggestion は `inferred` であり、その confidence によって observed、validated、approved になることは
ありません。
