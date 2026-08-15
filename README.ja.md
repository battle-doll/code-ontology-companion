# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

[アーキテクチャと対応ワークフロー](docs/ja/ARCHITECTURE_AND_ROADMAP.md)

Code Ontology Companion は、許可された Java/Spring または Python リポジトリについて、
プライバシーに配慮したローカル知識グラフを維持するための独立した Codex プラグインです。
目的は、既存コードをソースレベルの静的リバースエンジニアリングでオントロジー化し、
構造、依存関係、変更影響をローカルで探索できる証拠へ変換することです。

基本的な使用フローは次のとおりです。

1. macOS／Linux では `python3`、Windows では `py -3` を使い、`doctor` と `preflight` で
   許可済みリポジトリと解析条件を確認します。
2. リポジトリ外の workspace を指定し、`init --authorized` で最初の不変 snapshot を作成します。
3. `graph.html`、RDF/Turtle、CLI の query／impact／history／lineage、読み取り専用 MCP の
   list／status／search／neighbors／changes でオントロジーを探索します。
4. コード変更後は `sync` で新しい snapshot を昇格し、`diff` で前後の差分を確認します。

決定論的な静的解析、監査可能な関係 evidence、イミュータブルなスナップショット、RDF 1.1 Turtle エクスポート、
PROV-O 互換のリネージ、対話型オフラインワークベンチ、および
読み取り専用ローカル MCP サーバーを組み合わせています。決定論的アナライザーと MCP サーバーは、
対象コードを実行せず、ソフトウェアをインストールせず、テレメトリを送信せず、
ネットワークリクエストも行いません。オプションとして別途許可されたヘルパーのみが、
固定ループバックアドレス `127.0.0.1:11434` 上の既存 Ollama サービスへ、
範囲を限定したポータブルなオントロジーメタデータを送信できます。その未検証の提案は、
観測済みグラフの外部に保持されます。

## インタラクティブな例：Voice Notify for Codex

実在する Codex プラグインを対象にした Companion の出力をご覧いただけます。公開済みのこの
スナップショットは、[Voice Notify for Codex](https://github.com/battle-doll/codex-voice-notify)
`0.1.6` の Python リファレンス実装、設定ヘルパー、ビルド・検証ツール、テストを、
証拠に基づくグラフとしてマッピングしたものです。

[インタラクティブな Voice Notify オントロジーを開く](https://rawcdn.githack.com/battle-doll/code-ontology-companion/a32b97474450a025fa383614cd83d0d0393317e7/docs/examples/codex-voice-notify-code-ontology.html)
または、[自己完結型 HTML を表示・ダウンロード](docs/examples/codex-voice-notify-code-ontology.html)できます。

このスナップショットには、6 個の Python ファイルから得られた 417 ノードと 769 関係が
含まれています。パース警告は 0 件で、すべての関係にソース範囲と抽出証拠が付与されています。
シンボルの検索、呼び出し元と依存関係の調査、2D 構造ビューと 3D コンステレーションビューの切り替えに加え、
各関係のルール、定性的な根拠、ランタイム状態、ソース範囲、および制限事項を確認できます。

ここで示すのはランタイムの証明ではなく、静的解析の証拠です。Voice Notify の Windows および macOS 用の
本番フックエントリポイントは PowerShell と POSIX shell であり、この Python スナップショットの
アダプター対応範囲には含まれません。この例は明示的な許可を得て公開されており、生成されたエクスポートには
シンボル名とリポジトリ相対パスが含まれる可能性があります。ブラウザープレビューでは、GitHub にホストされたファイルを
HTML の Content-Type で配信するためだけに raw.githack を使用します。自己完結型ワークベンチ自体には、
実行時の CDN やネットワーク依存関係はありません。

Codex は、依頼されたワークフローを実行するため、シンボル、件数、
リポジトリ相対パスなどのコマンド出力を処理する場合があります。そのプラットフォーム上の
処理には、OpenAI の[適用される利用規約](https://openai.com/policies/terms-of-use/)と
[プライバシーポリシー](https://openai.com/policies/privacy-policy/)が適用されます。
このプラグインをインストールしても、Codex がオフライン製品になるわけではありません。

## バージョン 0.5.2 の対応機能

プラグインは、次のコードオントロジーワークフローをサポートします。

- Java のパッケージ、インポート、型、メソッド、継承、基本的な依存関係をマッピングします。
- 一般的な Spring ステレオタイプ、`@Bean`、コンストラクタ／フィールドインジェクション、
  AspectJ アドバイス、トランザクション、非同期、キャッシュ、認可、再試行の
  プロキシシグナルを認識します。
- Python のモジュール、インポート、型、関数、デコレーター、呼び出し、継承、および
  ヒューリスティックな Extract/Transform/Load/Validate/Orchestrate ロールをマッピングします。
- すべての関係に追加の `evidence` array を記録します。各項目には安定した
  `rule_id`、定性的な `basis`（`direct_syntax`、`resolved_static`、
  `framework_semantic`、`name_heuristic`）、`runtime_status`
  （`not_applicable` または `runtime_unknown`）、任意のリポジトリ相対
  `path`、`line_start`、`line_end`、制限付き `limitations` が含まれます。
- `document.quality` contract version `1.0` で、関係 evidence の coverage/count、
  Java/Python adapter status、capability、unsupported-runtime indicator を公開します。
  Parse warning が 0 でも、完全な静的または runtime coverage を意味しません。
- 同じ owner の Java call と、認識済み import type を介した明示的な
  `Type.method` call を保守的に解決し、
  曖昧な call candidate から関係を作りません。
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
- 選択した 1 つの制限付き関係近傍を、既定の `2D 構造` ビューとオプションの
  `3D 空間`コンステレーションの間で切り替えられます。3D はローカル
  Canvas2D perspective、決定論的な静的位置、明示的な node/edge/frame budget
  を使用し、WebGL、package、worker、telemetry、network を必要としません。
- Pointer orbit/zoom または同等の keyboard orbit、zoom、camera reset、node
  移動・選択、root への復帰で探索できます。DOM 検索、関係一覧、詳細パネル、
  2D graph は、同じ node と relation への正式なアクセシビリティ経路です。
- Reduced-motion と forced-colors/high-contrast を尊重し、mode と selection の
  状態を assistive technology に公開し、非表示タブでは描画を停止します。
  Canvas 描画が失敗した場合は 2D へ安全に戻ります。
- ソースフィンガープリントとワークスペースの絶対パスを非公開に保ちながら、ワークベンチで
  現在と前回のスナップショットを直接比較します。
- 登録済みワークスペースを 7 個の読み取り専用ローカル MCP ツールで照会します。
- 一般的な Java ポリシーアクセサーの読み取りを、それが制御する制御フロー分岐へ
  マッピングします。任意の文字列リテラルは保持しません。
- Python 3.9 以降を使用し、Windows、macOS、Linux で決定論的アナライザー、
  ローカル MCP サーバー、オプションの Ollama ヘルパーを実行します。
- Target repository を実行せずに expected/prohibited node と relationship、
  evidence metadata、adapter coverage、決定論的 output を確認する実行可能な
  golden/forbidden quality gate を適用します。

バージョン 0.5.2 では、変更されたリポジトリを全面的に再解析し、フィンガープリントにより
不要な未変更時の実行を避けます。

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
  関係 evidence にはリポジトリ相対 path と line span が含まれる場合があり、
  それらも機密である可能性があります。
- 秘密情報らしいファイル、リンク／reparse point、依存関係、VCS 内容、生成物は除外します。
- 対象プロジェクトをインポート、ビルド、テスト、実行することはありません。
- MCP プロセスは stdio を使い、待受ポートを開かず、任意のファイルシステムパスではなく
  ワークスペース ID を受け取ります。
- daemon、グラフデータベース、ローカルモデル、パッケージ、watcher はインストールしません。
  Cytoscape.js と ELK.js は生成 HTML 内に固定されており、npm install、CDN、
  ブラウザ worker、テレメトリ、ネットワークサービスは使用しません。
- ローカル LLM の検出は何も実行せず、どこにも接続せず、何も書き込みません。同意後に限り、
  オプションのヘルパーが固定 IPv4 ループバックへ接続し、Ollama が報告したメタデータを検証し、
  remote/cloud マーカーを含む応答を拒否し、ワークスペース単位の非公開設定と、
  作成専用の inferred evidence を書き込めます。POSIX では mode `0600` を使い、
  Windows ではユーザーが選択したワークスペースから継承した ACL を使います。

シンボル名とリポジトリ相対パスも機密である可能性があります。別途共有の許可を得ていない限り、
ワークスペースとエクスポートはローカルに保持してください。

## 必要要件

- プラグインと Skill をサポートする Codex
- Python 3.9 以降
- サードパーティ Python パッケージ、グラフデータベース、Java ランタイム、
  ローカル LLM は不要

bundled MCP launcher は Node.js が利用可能な場合、シェルを起動せずに Python を特定できます。
すべてのプラットフォームで、Python stdio を直接設定する方法もサポートされます。

## 既存コードをオントロジーへリバースエンジニアリング

macOS または Linux では以下のコマンドで `python3` を使います。Windows では
`py -3` など、既存の Python 3.9 以降のインタープリタを使います。

1. 既存のリポジトリに対して `doctor` と `preflight` を実行し、ファイルを書き込まずに
   対応するソースセットを確認します。
2. 結果を確認してリポジトリ外に新しい workspace を選び、許可済みの `init` を
   実行します。ソースレベルのリバースエンジニアリングによって、最初の不変な
   ontology snapshot が作成されます。
3. `graph.html` を探索し、`ontology.ttl` を RDF 対応 workflow に読み込むか、
   CLI とオプションの読み取り専用ローカル MCP tool で symbol と relationship を
   検索します。
4. コード変更後に `sync` と `diff` を実行し、以前の snapshot と lineage を
   維持しながら新しい snapshot を作成して比較します。

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

### オプションの読み取り専用ローカル MCP

公式 Skills bundle は[読み取り専用ローカル MCP setup workflow](docs/ja/references/local-mcp.md)を提供し、同じ version の complete GitHub package は server と同梱 script を提供します。Server は登録済みの `workspace_id` だけを受け付ける 7 個の読み取り専用 stdio tool を提供し、待受 port を開かず、任意の repository path も受け付けません。

macOS または Linux:

```toml
[mcp_servers.code-ontology-companion]
command = "python3"
args = ["/absolute/path/to/code-ontology-companion/mcp/server.py"]
```

Windows:

```toml
[mcp_servers.code-ontology-companion]
command = "py"
args = ["-3", "C:\\absolute\\path\\to\\code-ontology-companion\\mcp\\server.py"]
```

設定変更後に Codex を再起動するか新しい Codex プロセスを開き、ワークスペース一覧、状態、検索を確認します。

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
evidence として保存し、生のプロンプトと応答は保持しません。バージョン 0.5.2 はメタデータを
安定した順序で request ごとに最大 20 candidate／16 KiB に分割し、model thinking を無効化し、
request ごとの context を 8,192 token、response ごとの output を 2,048 token、request 時間を
最大 180 秒に制限します。すべての batch が検証された後にだけ sidecar を atomic に公開するため、
失敗または部分的な実行は artifact を残しません。未対応または競合する role suggestion は関係として
結び付けず、除外数だけを記録します。Ollama 自体のネットワーク動作は Companion の管理外です。
エンリッチメントは選択したモデルを実行し、CPU/GPU メモリを割り当てる
場合があります。各応答の後で直ちにアンロードするよう、ヘルパーは `keep_alive=0` を送ります。
`localMetadataVerified=true` は、Ollama API が報告した digest、size、format、model information、
capability、remote-marker fields が Companion の検査を通過したことだけを意味します。
モデル weight bytes、ループバックサービスの同一性、ローカル限定実行、Ollama の外向き通信が
存在しないことを保証するものではありません。詳しくは
[local-llm.md](docs/ja/references/local-llm.md)を参照してください。

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

バージョン 0.5.2 は従来の direct relationship triple と安定した identity を
維持し、rule、basis、source span、runtime status、limitation metadata のための
`RelationshipEvidence` resource を追加します。

## 静的解析の制限

グラフはナビゲーションと変更計画のための evidence であり、ランタイムトレース、セキュリティ判定、
因果関係の証明、正しさの保証ではありません。reflection、生成コード、runtime Spring conditions、
dynamic proxies、外部設定、dependency versions、Python metaprogramming により、一部の関係が
完全でない場合があります。

変更計画に使う前に、各関係の定性的 basis、runtime status、limitations と
adapter coverage matrix を確認してください。`runtime_unknown` の関係は静的
evidence であり、runtime activation の証明ではありません。

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
