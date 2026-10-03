# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

許可された Java/Spring または Python コードベースを立体的な3Dマップで探索します。シンボルを検索し、ソース根拠を持つ依存経路とスナップショット間の変更を確認できます。

**0.8.0** · 選択した GPT-6 Astra または GPT-6.1 Sol と推論強度を維持します。Windows・macOS・Linux でAIはローカル MCP の根拠、人はオフライン HTML を使います。完全パッケージは既存7個に `ontology_large_modules`、`ontology_large_search`、`ontology_large_neighbors`、`ontology_evidence_bundle` を追加した11個の範囲制限付き読み取り専用ツールを提供します。関連照会は固定したスナップショットを使い、大規模プロジェクトの経路は選択した単一モジュール内です。モデル優位性や実行成功を証明したとは主張しません。.

## 今の作業に適用する

> Code Ontology Companion をこのプロジェクトの作業に適用して。

Codex が実行可能なツールと既存の許可済みワークスペースを確認し、状態の確認と関連するシンボル検索または影響照会を実行します。関連する照会は同じスナップショットを使います。重要な Java/Python の変更後は、許可範囲内で更新し、鮮度・解析範囲・警告を確認します。既定の範囲は現在の会話です。プロジェクトへの指示の保存は明示的な依頼がある場合のみ行います。

> この作業用にオントロジーを設定して。

一般的な依頼では Code・Context・Contracts のうち実際に実行可能な製品を選びます。Code 単独でも使え、製品を指定した場合はその製品を優先します。不足する製品を自動インストールしません。Context は選択・確認済みの決定や制約のみを保存して再読み取りし、Contracts は選択した実際の交換 JSON を検証して未対応・情報損失・未検証を保持します。

[適用ワークフロー](skills/apply-code-ontology/SKILL.md)

## インストール / 使用

[プラグインディレクトリ](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [GitHub パッケージ](https://github.com/battle-doll/code-ontology-companion/releases)

このソースは0.8.0です。ディレクトリには別の審査・公開手順があるため提供バージョンが異なる場合があります。公式スキル版は適用・管理の両スキル、分析器、画面、ローカル MCP 設定ガイドを含みます。MCPサーバーは含まず、GitHub 完全版には読み取り専用stdio MCPサーバーも含まれます。クラウド接続先は不要です。

## 実際の自己オントロジーを探索

[**3D エクスプローラーを開く →**](https://battle-doll.github.io/code-ontology-companion/)

このプラグイン自身の対応ソースから生成した静的スナップショットです。モジュールやシンボルを選び、接続とソース位置を確認できます。別タブで開くにはCommandまたはCtrlを押しながらクリックしてください。

[生成根拠](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [アーキテクチャ](docs/ja/ARCHITECTURE_AND_ROADMAP.md)

## バージョン 0.8.0 の対応機能

- 現在の会話で最初の照会を実行し、変更後の許可された更新と状態確認につなげます。
- 構造・影響・変更の3Dオフライン画面とカメラフォーカス。
- 完全一致優先検索、構造フィルター、ページ送り、スナップショット固定読み取り。
- 方向別の依存経路と各段階の根拠、明確な探索上限。
- 追加・削除・修正と根拠変更の一貫した比較。
- Java/Springの型・import・保守的な呼び出し解決・注入・プロキシ信号、Pythonのモジュール・関数・呼び出し・パイプライン役割推定。
- 元の根拠を保持するCode参照、Context用不変ロケーター、明示的なContracts互換範囲。
- キーボード・テキスト探索、動きの低減、安全なテキスト一覧。

## クイックスタート

Python 3.9+が必要です。まず書き込まずに対応範囲を確認します。所有または解析を許可されたコードのみを使用し、生成する資料を確認してからリポジトリ外のワークスペースを初期化します。

```bash
python3 skills/manage-code-ontology/scripts/companion.py doctor --repo "/path/to/repo"
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo"
```

```bash
python3 skills/manage-code-ontology/scripts/companion.py init --repo "/path/to/repo" --workspace "/path/outside/repo/ontology" --authorized
python3 skills/manage-code-ontology/scripts/companion.py query --workspace "/path/outside/repo/ontology" --term "OrderService"
python3 skills/manage-code-ontology/scripts/companion.py impact --workspace "/path/outside/repo/ontology" --symbol "OrderService" --direction incoming
python3 skills/manage-code-ontology/scripts/companion.py diff --workspace "/path/outside/repo/ontology"
```

テストやコードのコピーがある場合は本番用ソースのディレクトリを明示してください。複数の相対ディレクトリには `--source-root` を繰り返します。更新時も範囲を保持し、`sync --source-root .` でリポジトリ全体の探索へ明示的に戻せます。別ファイルの競合宣言は統合せず分析を停止します。全グループを検索・ページ移動で探し、要素とソース関係へ展開できます。概要の接続は集約表示であり、パスフィルターは配備の証拠ではなく推定です。

表示深度は全モジュール、選択モジュールの構成要素、選択要素のメンバーの3段階です。他の領域は折り畳みます。呼び出し強調は別に静的な CALLS の1・2・3段階をたどります。任意の標本抽出はせず、索引内の全要素と関係を展開・ページ移動で確認でき、折り畳みと別ページの数を表示します。

```bash
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo" --source-root src/main
python3 skills/manage-code-ontology/scripts/companion.py sync --workspace "/path/outside/repo/ontology" --source-root src/main
```

## 根拠と互換性

`graph.html`、`ontology.json`、`ontology.ttl`は同じソースオントロジーを使用します。RDF 1.1 Turtle の `RelationshipEvidence` と PROV-O 系譜が根拠を保持します。`inferred`は検証済みではなく、`runtime_unknown`は実行の証明ではありません。根拠添付率は解析精度ではありません。

Codeはコード構造、Contextは決定と有効時点、Contractsは対応交換形式の検証を担当します。製品は独立して使用できます。[AIデータ契約](skills/manage-code-ontology/references/ai-data-contract.md) · [参照交換](skills/manage-code-ontology/references/code-reference.md)。

Context には元のデータへの参照を渡します。実際のスナップショットを厳密な Contracts draft へ直接変換する機能は未対応です。検証済みの範囲は参照ガイドに記載しています。

既存の Ollama `127.0.0.1:11434` は個別の同意後にのみ利用し、推論は観察された根拠と分離します。決定的解析にモデルは不要です。

## 新しいモデル環境のローカル利用

選択した GPT-6 Astra または GPT-6.1 Sol と推論強度を維持します。Windows・macOS・Linux でAIはローカル MCP の根拠、人はオフライン HTML を使います。完全パッケージは既存7個に `ontology_large_modules`、`ontology_large_search`、`ontology_large_neighbors`、`ontology_evidence_bundle` を追加した11個の範囲制限付き読み取り専用ツールを提供します。関連照会は固定したスナップショットを使い、大規模プロジェクトの経路は選択した単一モジュール内です。モデル優位性や実行成功を証明したとは主張しません。

[5言語の利用ガイド](docs/ja/MODEL_ERA_WORKFLOW.md) · [翻訳範囲](docs/TRANSLATION_COVERAGE.md)

## ライセンスとプライバシー

Apache-2.0。分析器は対象コードの実行、テレメトリ送信、直接ネットワーク接続を行いません。ユーザーの作業領域はローカルに保持し、公開デモはこの公開リポジトリのみを対象とします。ソース本文、コメント、秘密情報は保持しません。

[プライバシー](PRIVACY.md) · [セキュリティ](SECURITY.md) · [サポート](SUPPORT.md) · [規約](TERMS.md) · [変更履歴](CHANGELOG.md)
