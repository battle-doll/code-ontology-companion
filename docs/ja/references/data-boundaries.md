# データ境界

[English](../../../skills/manage-code-ontology/references/data-boundaries.md) | [한국어](../../ko/references/data-boundaries.md) | [日本語](data-boundaries.md) | [简体中文](../../zh-CN/references/data-boundaries.md)

## 許可された入力

ユーザーが所有、管理、または明示的に調査を許可されたローカルリポジトリだけを解析してください。
他者から提供されたパスは、許可の証明にはなりません。

## 読み取るデータ

バージョン 0.5.2 は、2 MiB 以下の通常の `.java` および `.py` ファイルを読み取り、
ファイル総数と合計バイト数の上限に対して fail closed します。symbolic link や Windows の
reparse point はたどりません。一般的な dependency、VCS、generated-output、IDE、
virtual-environment、cache の各ディレクトリは省略します。

ファイル名が credential、secret、token、private key、keystore、または `.env` 設定を示唆する
ファイルは、対応拡張子を使用していても除外されます。

## 保持するデータ

ポータブルなオントロジー成果物は、次を保持する場合があります。

- symbol 名と annotation 名。
- language と node／relationship type。
- qualified name。
- 認識済み Java policy accessor で使われる、検証済みのドット区切り policy identifier。
- リポジトリ相対の source path と任意の relationship-evidence line span。
- stable extraction rule ID、定性的 evidence basis、runtime-status indicator、
  bounded limitation、adapter-coverage summary。
- 集計件数と parse warning。

非公開のローカルワークスペースファイルは、さらに次を保持します。

- refresh に必要なリポジトリの絶対パス。
- 変更検出に使うファイルごとの byte count と SHA-256 値。
- snapshot、event、workspace identifier。
- 通常の `.git` metadata から直接読み取るオプションの local Git revision。

ポータブル RDF、オフライン HTML、通常の MCP 応答は、リポジトリの絶対パスや完全な
ファイル fingerprint を意図的に公開しません。

オフライン HTML はローカル検索のために完全なポータブル node/edge index を埋め込みますが、
canvas 上では範囲を限定した subgraph だけを実体化します。また、integrity-pinned の
Cytoscape.js と ELK.js の bytes を埋め込み、Content Security Policy により接続と
browser worker を無効にします。

observed ontology artifact は、意図的に次を一切保持しません。

- source body、任意の string literal、comment。
- ファイル内容。
- environment variable、credential、API key、token。
- prompt または model output。

オプションのローカル LLM エンリッチメントを明示的に有効にした場合、別個の非公開設定が、
固定 loopback provider/endpoint、consent/data-scope version、検証済み model
name/digest/capabilities を保持します。成功した各 enrichment は、正規化された suggested role と
confidence、snapshot/model/schema provenance、範囲を限定した input/ontology digest を保持する
非公開 sidecar を 1 つ作成します。生の prompt と raw response は保持しません。sidecar は
`inferred` evidence であり、observed ontology、RDF、lineage、MCP data に統合されることはありません。
POSIX では mode `0600` を使い、Windows ではユーザーが選択した workspace から継承した ACL を使います。

identifier と相対パスも機密である可能性があります。既定では成果物をローカルに保持し、
共有する前に別途許可を得てください。

## 書き込み

Doctor と preflight は何も書き込みません。初期化では、対象リポジトリの内部でも親でもない、
明示的に指定された新しいワークスペースを作成します。refresh は完全な staging snapshot を構築して
検証し、新しいイミュータブル snapshot をアトミックに昇格するとともに、直近の正常な version を
保持します。decision／validation record はローカル lineage journal に追記されます。

## ネットワークと実行

同梱アナライザーは直接のネットワークリクエストを行わず、対象コードを import、compile、build、
test、execute しません。package、model、database、daemon、permanent watcher はインストールしません。

プラグインが有効な場合、Codex は同梱の読み取り専用 stdio MCP process を起動する場合があります。
待受 port を開かず、任意の filesystem path を受け入れず、明示的に許可された初期化ワークフローで
登録済みの workspace だけを照会します。

ワークスペース単位の明示的な同意後、別個のオプション helper は、literal IPv4 loopback
`127.0.0.1:11434` 上の既存 Ollama service だけへ接続できます。endpoint input、proxy、redirect、
API key、LAN/public address は受け入れず、報告された cloud/remote marker や必須 model metadata の
欠落を拒否します。範囲を限定した payload には、node ID、symbol/type/annotation name、qualified
name、リポジトリ相対 path、observed relationship metadata が含まれる場合があります。source body、
comment、任意の string、secret、絶対 path、private manifest、source fingerprint、raw file hash は
除外します。helper は model の install／download を行わず、Ollama service を起動しません。
許可済み enrichment は選択した model を実行し、CPU/GPU memory を割り当てる場合があり、応答後の
即時 unload を要求するため `keep_alive=0` を送ります。Ollama 自体の networking、resource behavior、
retention は Companion の管理外です。

Codex は、依頼されたワークフローを提供するために analyzer command output を処理する場合があります。
その platform processing には OpenAI の適用される terms と privacy policy が適用されます。
バージョン 0.5.2 は remote data service を呼び出さず、生成された artifact を upload しません。

## 解釈

グラフは static evidence です。Java/Spring/Python の symbol、call、dependency、policy、pipeline
relationship は、解析対象 snapshot から観測された構造と到達可能性を表します。reflection、runtime
Bean condition、generated proxy、external configuration、dynamic import、monkey-patching、dependency
injection container、generated code により、実際の runtime behavior が変わる可能性があります。
したがって、static correlation と change proximity は runtime causality を確立しません。
