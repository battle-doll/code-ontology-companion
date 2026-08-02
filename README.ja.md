# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[全体アーキテクチャとロードマップ](docs/ja/ARCHITECTURE_AND_ROADMAP.md)

Code Ontology Companion は、許可された Java/Spring または Python リポジトリについて、
プライバシーに配慮したローカル知識グラフを維持するための独立した Codex プラグインです。

決定論的な静的解析、イミュータブルなスナップショット、RDF 1.1 Turtle エクスポート、
PROV-O 互換のリネージ、対話型オフラインワークベンチ、および完全版／ローカルプロファイル用の
読み取り専用ローカル MCP サーバーを組み合わせています。決定論的アナライザーと MCP サーバーは、
対象コードを実行せず、ソフトウェアをインストールせず、テレメトリを送信せず、
ネットワークリクエストも行いません。オプションとして別途許可されたヘルパーのみが、
固定ループバックアドレス `127.0.0.1:11434` 上の既存 Ollama サービスへ、
範囲を限定したポータブルなオントロジーメタデータを送信できます。その未検証の提案は、
観測済みグラフの外部に保持されます。

Codex は、依頼されたワークフローを実行するため、シンボル、件数、
リポジトリ相対パスなどのコマンド出力を処理する場合があります。そのプラットフォーム上の
処理には、OpenAI の[適用される利用規約](https://openai.com/policies/terms-of-use/)と
[プライバシーポリシー](https://openai.com/policies/privacy-policy/)が適用されます。
このプラグインをインストールしても、Codex がオフライン製品になるわけではありません。

## バージョン 0.3.4 の公開機能

OpenAI への提出に使用する公開 Skills-only プロファイルには、以下の汎用コードオントロジー
ワークフローだけが含まれます。AETHER Lab の `runtime-binding` コマンド、プロジェクト固有の
ポリシースキーマ、レシート生成機能、専用評価ケースは含まれず、公開機能として案内もしません。
これらは GitHub の完全版／ローカルプロファイルにのみ残る、別途管理される downstream extension
です。OpenAI がホストする提出物には含まれず、ランタイム、ポリシー、注文、資金を操作する権限を
一切持ちません。

- Java のパッケージ、インポート、型、メソッド、継承、基本的な依存関係をマッピングします。
- 一般的な Spring ステレオタイプ、`@Bean`、コンストラクタ／フィールドインジェクション、
  AspectJ アドバイス、トランザクション、非同期、キャッシュ、認可、再試行の
  プロキシシグナルを認識します。
- Python のモジュール、インポート、型、関数、デコレーター、呼び出し、継承、および
  ヒューリスティックな Extract/Transform/Load/Validate/Orchestrate ロールをマッピングします。
- Java のジェネリック、record、ネスト型、複数インターフェース、Spring の
  アノテーション／インジェクションのケースをより保守的に解析し、Python のエイリアス、
  相対インポート、レキシカルシャドーイング、ネスト関数、`src/` レイアウトのケースを解決します。
- ソース、グラフ、影響分析、出力に上限を適用します。
- 明示的なワークスペース単位の同意と Ollama が報告したモデルメタデータの検証後にのみ、
  既存の Ollama completion モデルを 1 つオプションとして設定できます。そのうえで、決定論的
  オントロジーを変更せず、正規化された `inferred` サイドカーだけを保存します。
- 非公開のソースフィンガープリントを使って、変更のない更新を省略します。
- アナライザーまたは Companion のバージョンが変わった場合は、ソースが未変更でも更新します。
- 変更されたリポジトリをステージング領域で構築し、イミュータブルなスナップショットを
  アトミックに昇格します。
- 解析または検証が失敗した場合は、直近の正常なスナップショットを保持します。
- スナップショットを比較し、observed/declared/inferred/validated/approved のリネージを維持します。
- ポータブルな RDF/Turtle と、全インデックス検索、範囲を限定した関係レンズ、
  人間が読める詳細表示を備え、CDN を使用しない自己完結型の対話的 HTML ワークベンチを
  エクスポートします。
- ソースフィンガープリントとワークスペースの絶対パスを非公開に保ちながら、ワークベンチで
  現在と前回のスナップショットを直接比較します。
- 一般的な Java ポリシーアクセサーの読み取りを、それが制御する制御フロー分岐へ
  マッピングします。任意の文字列リテラルは保持しません。

GitHub の完全版／ローカルプロファイルには、登録済みワークスペースを照会する 7 個の
読み取り専用ローカル MCP ツールも含まれます。ローカル stdio MCP サーバーは、公開
Skills-only／OpenAI 提出プロファイルには含まれません。

バージョン 0.3.4 では、変更されたリポジトリを全面的に再解析します。フィンガープリントにより、
不要な未変更時の実行は避けられますが、ファイル単位の増分解析は将来の最適化項目です。

## プライバシーと安全性の既定値

- 所有している、または調査を許可されたコードだけを解析してください。
- `doctor` と `preflight` は読み取り専用です。
- 初期化には `--authorized` と、リポジトリ外部の新規ワークスペースが必要です。
- ソース本文、コメント、任意の文字列リテラルは保持しません。認識済みの Java
  ポリシーアクセサーへ渡された、検証済みドット区切りポリシー識別子は、`PolicyLeaf`
  ノードとして保持される場合があります。
- 非公開のローカル設定にリポジトリの絶対パスを保存し、非公開マニフェストに鮮度確認用の
  ファイルごとのサイズと SHA-256 値を保存します。
- ポータブル RDF、HTML、通常の MCP 応答では、絶対パスと完全なフィンガープリントを省略します。
- 秘密情報らしいファイル、リンク／reparse point、依存関係、VCS 内容、生成物は除外します。
- 対象プロジェクトをインポート、ビルド、テスト、実行することはありません。
- MCP プロセスは stdio を使い、待受ポートを開かず、任意のファイルシステムパスではなく
  ワークスペース ID を受け取ります。
- daemon、グラフデータベース、ローカルモデル、パッケージ、watcher はインストールしません。
  Cytoscape.js と ELK.js は生成 HTML 内に固定されており、npm install、CDN、
  ブラウザ worker、テレメトリ、ネットワークサービスは使用しません。
- ローカル LLM の検出は何も実行せず、どこにも接続せず、何も書き込みません。同意後に限り、
  オプションのヘルパーが固定 IPv4 ループバックへ接続し、Ollama が報告したメタデータを検証し、
  remote/cloud マーカーを含む応答を拒否し、ワークスペース単位のモード `0600` 設定と、
  作成専用の inferred evidence を書き込めます。

シンボル名とリポジトリ相対パスも機密である可能性があります。別途共有の許可を得ていない限り、
ワークスペースとエクスポートはローカルに保持してください。

## 必要要件

- プラグイン、Skill、bundled MCP をサポートする Codex
- Python 3.9 以降
- サードパーティ Python パッケージ、グラフデータベース、Java ランタイム、
  ローカル LLM は不要

MCP launcher は、サポートされる Codex プラグインホストが提供する JavaScript ランタイムを使い、
シェルを起動せずに Python を特定します。

## 手動クイックスタート

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  doctor --repo "/path/to/authorized/repository"

python3 skills/manage-code-ontology/scripts/companion.py \
  preflight --repo "/path/to/authorized/repository"
```

preflight の内容を確認し、ローカル成果物の作成を許可した後に実行します。

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  init \
  --repo "/path/to/authorized/repository" \
  --workspace "/path/outside/repository/ontology-workspace" \
  --authorized
```

更新と照会:

```bash
python3 skills/manage-code-ontology/scripts/companion.py \
  sync --workspace "/path/to/ontology-workspace"

python3 skills/manage-code-ontology/scripts/companion.py \
  query --workspace "/path/to/ontology-workspace" --term "OrderService"

python3 skills/manage-code-ontology/scripts/companion.py \
  diff --workspace "/path/to/ontology-workspace"
```

### 既存 Ollama によるオプションのエンリッチメント

決定論的ワークフローにモデルは一切必要ありません。最初の関連ワークフローでは、検出は
読み取り専用です。Ollama が検出された場合に限り、Companion は既存ローカルモデルの
調査可否を尋ねます。同意は固定ループバック上のモデル調査とワークスペース設定を許可しますが、
インストール、ダウンロード、サーバー起動、任意のエンドポイントは許可しません。
Ollama が remote/cloud と報告したモデルと結果は拒否されます。

```bash
python3 skills/manage-code-ontology/scripts/local_llm.py detect

# Run only after the disclosure and explicit consent described in the skill.
python3 skills/manage-code-ontology/scripts/local_llm.py probe --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py configure \
  --workspace "/path/to/ontology-workspace" \
  --model "an-existing-local-model" \
  --authorized
python3 skills/manage-code-ontology/scripts/local_llm.py enrich \
  --workspace "/path/to/ontology-workspace" \
  --authorized
```

ヘルパーが送信するのは、範囲を限定したシンボルメタデータと observed relations だけであり、
ソース本文、コメント、任意の文字列、秘密情報、絶対パス、非公開のファイルハッシュは送信しません。
正規化された提案は `enrichments/<snapshot-id>/<run-id>.json` 配下に `inferred`
evidence として保存します。生のプロンプトと応答は保持しません。Ollama 自体のネットワーク動作は
Companion の管理外です。エンリッチメントは選択したモデルを実行し、CPU/GPU メモリを割り当てる
場合があります。各応答の後で直ちにアンロードするよう、ヘルパーは `keep_alive=0` を送ります。
`localMetadataVerified=true` は、Ollama API が報告した digest、size、format、model information、
capability、remote-marker fields が Companion の検査を通過したことだけを意味します。
モデル weight bytes、ループバックサービスの同一性、ローカル限定実行、Ollama の外向き通信が
存在しないことを保証するものではありません。詳しくは
[local-llm.md](docs/ja/references/local-llm.md)を参照してください。

### 完全版／ローカル GitHub プロファイル限定: オプションの AETHER Lab ランタイムバインディング

この downstream extension は公開 Skills-only アーカイブおよび OpenAI 提出版には含まれず、
OpenAI がホストする機能として案内されません。GitHub の完全版／ローカルプロファイルにだけ含まれる
ローカル CLI 操作であり、読み取り専用 MCP サーバーにも公開していません。
バージョン 0.3.4 がこのモード `0400` のレシートをサポートするのは macOS/POSIX であり、
Windows は対象外です。最新の current snapshot、サポート対象の policy leaf、重複のない厳密な
ローカル JSON または `policy-json` 文書、ソースリポジトリ外部の新しい出力先、明示的な許可が
必要です。

```bash
mkdir -m 700 "/private/path/runtime-bindings"

python3 skills/manage-code-ontology/scripts/companion.py \
  runtime-binding \
  --workspace "/path/to/ontology-workspace" \
  --policy-leaf "strategy.exits.timeStopMinutes" \
  --policy-document "/path/to/authorized/repository/policies/policy.md" \
  --output "/private/path/runtime-bindings/time-stop.json" \
  --authorized
```

出力は `aether.runtime-effective-ontology-binding/v1` を厳密に実装します。すなわち、
canonical JSON と 1 個の LF、self-hash、コマンドが返す外部ファイルハッシュ、並べ替え済みで
ハッシュ化された ontology-edge references、固定された source/snapshot hashes、厳密に false の
authority、作成専用の公開、モード `0400` です。

このレシートで `runtimeEffective=true` が持つ意味は 1 つに限られます。固定された active source
において、指定 leaf が静的解析上 production control-flow branch に到達し、指定された policy
document に、その leaf を無効化する既知の AETHER shadow/enable condition が存在しないという意味です。
producer は active source からグラフを再構築し、snapshot との node/edge の完全一致を要求します。
test/fixture 限定パス、古い source、未使用 read、有効な stop-loss/take-profit ladder、
無効化された trailing、曖昧なパス、既存の出力のいずれかがあれば fail closed します。

これは、分岐が実行されたこと、注文が送信されたこと、ポリシーが安全であること、または利益が
変化したことを証明しません。candidate-generation、gate、approval、promotion、policy-write、
order、network、runtime-write、funds のいずれの権限も与えません。v1 レシートは Lab の厳密な
schema を破らずに policy-document hash を含められないため、利用側の Lab は使用時に正確な
baseline policy と shadow conditions を独立して再確認しなければなりません。

## ワークスペースパイプライン

```text
使用を許可されたソース
  -> 非公開 source manifest
  -> 分離された staging 解析
  -> artifact 検証
  -> イミュータブル snapshot の昇格
  -> current snapshot pointer
  -> RDF / 対話型 offline HTML / read-only MCP
```

各スナップショットには `ontology.json`、`ontology.ttl`、`report.md`、`graph.html`、
`snapshot.json`、非公開の `source-manifest.json` が含まれます。ワークスペースには、追記専用の
`lineage.jsonl` とポータブルな `lineage.ttl` も含まれます。

## RDF の移植性とリネージ

コア語彙は Explorer 1.0 の `co:` namespace を維持するため、過去のエクスポートとの互換性が
保たれます。リネージは W3C PROV-O と、文書化された Companion namespace を使用します。
Turtle エクスポートは RDF 1.1 互換ストアへインポートできます。ストア固有のインデックス、
推論ルール、拡張にはマッピングが必要な場合があります。

## 静的解析の制限

グラフはナビゲーションと変更計画のための evidence であり、ランタイムトレース、セキュリティ判定、
因果関係の証明、正しさの保証ではありません。完全版／ローカル限定の runtime-binding receipt が限定するのは、静的な
source reachability と既知の policy shadowing だけであり、ランタイム実行や結果の因果関係を
確立するものではありません。reflection、生成コード、runtime Spring conditions、dynamic proxies、
外部設定、dependency versions、Python metaprogramming は不完全な場合があります。

## 開発

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
python3 scripts/build_release.py
python3 scripts/build_skills_only_release.py
```

セキュリティ問題: [SECURITY.md](docs/ja/SECURITY.md)。サポート: [SUPPORT.md](docs/ja/SUPPORT.md)。

## ライセンスと独立性

ソースは Apache-2.0 の下でライセンスされています。本プロジェクトは独立しており、OpenAI、
Broadcom、VMware、Spring project、Oracle、Python Software Foundation と提携しておらず、
またそれらによる承認も受けていません。製品名は互換性を説明する目的でのみ使用しています。
