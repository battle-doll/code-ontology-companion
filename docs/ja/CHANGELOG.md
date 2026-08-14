# 変更履歴

[English](../../CHANGELOG.md) | [한국어](../ko/CHANGELOG.md) | [日本語](CHANGELOG.md) | [简体中文](../zh-CN/CHANGELOG.md)

## 0.5.2 - 2026-08-15

- 完全なロシア語の製品 README を追加し、英語、韓国語、日本語、簡体字中国語、
  ロシア語の各ルートガイドに同一の 5 言語切り替えリンクを適用しました。
- 標準言語切り替え、共通の capability／safety marker、同一のコマンド例構造に
  よってルート README の parity を検証します。相対言語リンクがローカルで有効な
  ように complete GitHub package へ 5 つのルートガイドをすべて収録し、既存の
  4 言語の全文書マトリクスと Skills-only の境界は維持します。
- リリース metadata、runtime version marker、SBOM 日付、evaluation metadata、
  CI artifact 名、validator、test、submission 文書を同期しました。公開済みの
  v0.5.1 tag と artifact は変更せず、analyzer semantics、ontology schema、
  permission、privacy boundary、dependency に変更はありません。

## 0.5.1 - 2026-08-13

- 公式 Skills-only manifest に rule-attributed relationship evidence と制限付き
  Java/Python adapter coverage を明記し、canonical listing と整合させました。
- 同梱の skill agent metadata を、アクセシブルな既定 2D／オプション 3D
  workbench および evidence／coverage workflow と整合させました。
- 公開済み v0.5.0 tag と artifact は変更しません。この patch は release
  metadata のみを変更し、analyzer semantics、ontology schema、visualization
  behavior、権限・privacy 境界、vendored dependency は変更しません。

## 0.5.0 - 2026-08-13

- 従来の 2D ビューと同じ制限付き関係近傍を探索する、オプションの対話型
  **3D コンステレーション**ビューを追加しました。2D は既定かつ常設の
  fallback であり、両ビューは選択シンボル、ontology identity、関係 evidence、
  詳細、filter、上限を共有します。
- `graph.html` に埋め込まれた決定論的データとブラウザー標準 canvas API だけで
  3D projection をローカル描画します。CDN、package、WebGL、worker、telemetry、
  network は不要であり、graph database、SPARQL、runtime tracing の対応を
  意味しません。
- Pointer orbit/zoom に加え、keyboard での orbit、zoom、camera reset、node
  移動・選択、root への復帰を提供します。Reduced-motion と
  forced-colors/high-contrast を尊重し、状態と操作説明を assistive technology に
  公開し、非表示タブでは描画を停止します。Canvas が利用できない場合は、
  keyboard-accessible な 2D ビューへ安全に戻ります。
- リポジトリ全体を一度に描画せず、選択した制限付き関係近傍だけを可視化します。

- 生成されるすべての関係の `evidence` array に、安定した `rule_id`、
  定性的な `basis`、`runtime_status`、任意のリポジトリ相対 `path` と line
  span、制限された `limitations` を記録します。互換 consumer のため、
  従来の relation triple と node/edge identity は維持します。
- Versioned `document.quality` contract と制限付き Java/Python adapter
  coverage matrix を公開し、snapshot、report、query、offline workbench、read-only MCP result が
  supported、partial、heuristic、runtime-unknown の領域を区別できるよう、
  制限付き Java/Python adapter coverage matrix を公開します。Parse warning が
  ないことを完全な coverage の証明として扱いません。
- 同じ owner の method と、認識済み import type を介した明示的な
  `Type.method` Java call を
  保守的に解決し、曖昧な candidate から関係を作りません。
- Expected/prohibited node と relationship、evidence metadata、coverage、
  決定論的動作を確認する実行可能な golden/forbidden ontology quality gate を
  追加します。この gate は target repository を実行しません。
- Python standard library の zero-dependency analyzer、安定した RDF vocabulary、
  immutable snapshot、target-code 非実行と direct-network 非接続の境界、
  同意に基づく分離された inferred Ollama sidecar を維持します。

## 0.4.0 - 2026-08-10

- 製品、ポリシー、提出、アーキテクチャ、リファレンス、および各言語の文書を、
  現在対応している汎用オントロジーワークフローに統一し、従来のプロジェクト固有の
  コマンド、実装、テスト、評価ケースを削除しました。
- 許可された既存の Java/Spring または Python コードをソースレベルの静的な
  リバースエンジニアリングによって、イミュータブルな JSON、RDF/Turtle、リネージ、
  対話型オフラインオントロジーへ構成し、更新・比較する使用手順を追加しました。
- 公式 Skills バンドルに Windows、macOS、Linux 向けのオプションの読み取り専用
  ローカル MCP 設定ガイドとプロンプトを含め、完全な GitHub パッケージには同じ
  バージョンのサーバーとランチャーを収録します。
- Windows で Python 3.9 以上を実際に検証し、MCP stdio を UTF-8 に固定し、
  スナップショット、ステージング、リリースソースのリンクと reparse point を
  フェイルクローズで拒否します。
- ローカル Ollama プロンプトの role 一覧を正規スキーマと同期し、`Validate` role と
  0.3.5 で導入した制限付きの決定論的バッチ処理を維持します。

## 0.3.5 - 2026-08-03

- オプションのローカル Ollama enrichment を決定的に分割し、各リクエストを
  最大 20 candidate、直列化された portable metadata 16 KiB 以下に制限しました。
- model thinking を無効化し、request ごとの context を 8,192 token、応答ごとの
  出力を 2,048 token に制限するとともに、対応するローカル hardware で制限付き
  enrichment が完了できるよう、各リクエストに最大 180 秒を許可しました。
- 全 batch の検証後に 1 つの inferred sidecar を atomic に公開します。失敗、未完了、
  または部分的な実行では enrichment artifact を残しません。許可された role vocabulary と
  一致する提案だけを関連付け、同一 role の重複には低い confidence を使い、role が競合する
  node は除外します。

## 0.3.4 - 2026-08-02

- Java/Spring/Python の静的解析、スナップショット、RDF、リネージ、ワークベンチ、
  読み取り専用ローカル MCP、オプションの Ollama に関するリリース文書を同期しました。
- 宣言されたファイル構成、機能、指示、メタデータが一致することをフェイルクローズで確認する、
  決定論的なリリース検証を追加しました。

## 0.3.3 - 2026-08-02

- バージョン 0.3.2 を変更のない機能ベースラインとして維持しながら、
  完全なローカルファーストアーキテクチャと段階的なバージョンロードマップを公開しました。
- 人が読むすべての製品、運用、安全性、ポリシー、提出、リファレンス文書について、
  英語、韓国語、日本語、簡体字中国語の入口と翻訳を追加しました。
- 英語のライセンスおよびポリシー文書を正規の原文として維持し、法的文書の翻訳を
  参考情報であると明記し、ソースパッケージ内で文書の言語間整合性を検証するようにしました。

## 0.3.2 - 2026-08-02

- 追跡対象となるすべてのリリース変更に、新しいセマンティックバージョンと
  日付付きの変更履歴エントリを必須とし、ベースラインを考慮した CI の適用、
  メタデータの同期、決定論的な成果物を実現しました。
- 最終的なソース状態からプラグインの登録済み自己オントロジーを更新し、
  宣言された系譜と検証済みの系譜を記録するリリースチェックリストを追加しました。
- 不正な形式または将来バージョンの来歴は拒否しつつ、互換性があり同意済みの
  ローカル LLM ワークスペース設定をパッチリリース間で保持するようにしました。

## 0.3.1 - 2026-08-01

- ジェネリック宣言とレコード宣言、複数インターフェースの階層、ネストされた import、
  検証済み Spring アノテーション、同一パッケージでのワイルドカードのシャドーイング、
  コンパクト／ジェネリックコンストラクターの検出、保守的なコンストラクターインジェクション、
  および `@Bean` パラメーターインジェクションについて、決定論的な Java 解析の精度を向上しました。
- 相対 import とエイリアス付き import、内部呼び出し、レキシカルシャドーイング、
  ネストされた関数、明示的な `self`／`cls` 呼び出し、`src/` レイアウト、
  内包表記のスコープ、制限付き AST の深さ／数、およびトークンベースの
  パイプライン役割分類について、Python 解析の精度を向上しました。
- ソース、グラフ、影響、出力のリソース制限をフェイルクローズ方式で追加しました。
- 明示的な同意後に利用できる、ワークスペース単位のオプションの Ollama エンリッチメントを追加しました。
  固定の IPv4 ループバックのみを使用し、報告されたクラウド／リモートのマーカーや
  必須メタデータの欠落を拒否します。また、制限された移植可能なメタデータのサブセットを送信し、
  `keep_alive=0` によるモデルの即時アンロードを要求し、観測済みのオントロジー証拠を変更せずに
  作成専用の `inferred` サイドカーを保存します。
- Git リビジョンのメタデータ読み取りと、制限付き MCP 応答コントラクトを強化しました。
- 展開後のスモークチェックを含め、リリースアーカイブに対する厳密で再現可能な検証を追加しました。
- ファイルの同一性、サイズ、mtime のガードを維持しながら、プラットフォーム間で
  テキストのチェックアウトを正規化し、Windows のファイル変更チェックを Python 3.12 と互換にしました。

## 0.3.0 - 2026-07-31

- ID 順に並べたリンググラフを、自己完結型のインタラクティブなオントロジー
  ワークベンチに置き換えました。全インデックス検索、制限付きの関係レンズ、
  ガイド付き探索、人が読める詳細、現在と前回のスナップショット間の変更を提供します。
- ローカルの同一スレッド内レイアウト向けに Cytoscape.js 3.34.0 と ELK.js 0.12.0 を
  同梱して完全性を固定し、CDN、インストール手順、テレメトリ、ネットワークアクセスを不要にしました。
- 中核となるオントロジー／RDF 1.0 の語彙を安定させ、静的証拠の境界を維持しました。
  表示される関係は、実行時の因果関係を立証するものではありません。

## 0.2.0 - 2026-07-31

- 任意の文字列リテラルを保持することなく、認識済み Java ポリシーアクセサーと
  制御フローの間に保守的な静的データフロー関係を追加しました。
- ポリシー関係を静的証拠として扱い、実行時の因果関係を示すものではないことを文書化しました。

## 0.1.1 - 2026-07-30

- 系譜ジャーナルへの追記または読み取り前に、シンボリックリンク、リパースポイント、
  ハードリンク、ファイル差し替え競合を拒否するようにしました。
- スナップショットマニフェストで、ファイル記述子ベースの制限付きソース読み取りを再利用し、
  検出から読み取りまでの間のシンボリックリンク差し替えや上限超過の増大をフェイルクローズさせました。
- `O_NOFOLLOW` がないプラットフォームを含め、保護された読み取りの前、途中、後に
  ファイルの同一性と安定したメタデータを検証するようにしました。
- シンボリックリンク先、オープン時の差し替え、上限超過の増大、
  生バイトのマニフェストハッシュに対する回帰テストを追加しました。

## 0.1.0 - 2026-07-29

- 決定論的な Java/Spring および Python の静的オントロジー抽出を追加しました。
- 不変スナップショット、安定した更新フィンガープリント、ステージング検証、
  アトミックな昇格、最終正常状態への復旧を追加しました。
- RDF 1.1 Turtle エクスポートと PROV-O 互換の系譜を追加しました。
- 構造クエリ、制限付き影響分析、スナップショット履歴、差分コマンドを追加しました。
- 自己完結型のオフライングラフを追加しました。
- 登録済みワークスペース専用で読み取り専用のローカル MCP ツールを 7 個追加しました。
- プライバシー、利用規約、セキュリティ、脅威モデル、SBOM、レビュー担当者向け評価、
  決定論的リリースパッケージングを追加しました。
