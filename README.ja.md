# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

許可された Java/Spring または Python コードベースを立体的な3Dマップで探索します。シンボルを検索し、ソース根拠を持つ依存経路とスナップショット間の変更を確認できます。

**Astra 公開記念アップデート · 0.6.0。** GPT-6 Astra の公開に合わせ、検索精度、根拠の追跡、スキルの指示を改善しました。人には直感的な3D画面を、AIには構造化された資料を提供します。[詳細](docs/ASTRA_RELEASE.md)。

## インストール / 使用

[プラグインディレクトリ](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [GitHub パッケージ](https://github.com/battle-doll/code-ontology-companion/releases)

このソースは0.6.0です。ディレクトリには別の審査・公開手順があるため提供バージョンが異なる場合があります。公式スキル版は分析器、画面、ローカル MCP 設定ガイドを含み、GitHub 完全版には読み取り専用stdio MCPサーバーも含まれます。クラウド接続先は不要です。

## 実際の自己オントロジーを探索

[**3D エクスプローラーを開く →**](https://battle-doll.github.io/code-ontology-companion/)

このプラグイン自身の対応ソースから生成した静的スナップショットです。モジュールやシンボルを選び、接続とソース位置を確認できます。別タブで開くにはCommandまたはCtrlを押しながらクリックしてください。

[生成根拠](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [アーキテクチャ](docs/ja/ARCHITECTURE_AND_ROADMAP.md)

## バージョン 0.6.0 の対応機能

- 構造・影響・変更の3Dオフライン画面とカメラフォーカス。
- 完全一致優先検索、構造フィルター、ページ送り、スナップショット固定読み取り。
- 方向別の依存経路と各段階の根拠、明確な探索上限。
- 追加・削除・修正と根拠変更の一貫した比較。
- Java/Springの型・import・保守的な呼び出し解決・注入・プロキシ信号、Pythonのモジュール・関数・呼び出し・パイプライン役割推定。
- 元の根拠を保持するCode参照、Context用不変ロケーター、明示的なContracts互換範囲。
- キーボード・テキスト探索、動きの低減、安全な2D代替表示。

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

## 根拠と互換性

`graph.html`、`ontology.json`、`ontology.ttl`は同じソースオントロジーを使用します。RDF 1.1 Turtle の `RelationshipEvidence` と PROV-O 系譜が根拠を保持します。`inferred`は検証済みではなく、`runtime_unknown`は実行の証明ではありません。根拠添付率は解析精度ではありません。

Codeはコード構造、Contextは決定と有効時点、Contractsは対応交換形式の検証を担当します。製品は独立して使用できます。[AIデータ契約](skills/manage-code-ontology/references/ai-data-contract.md) · [参照交換](skills/manage-code-ontology/references/code-reference.md)。

Context には元のデータへの参照を渡します。実際のスナップショットを厳密な Contracts draft へ直接変換する機能は未対応です。検証済みの範囲は参照ガイドに記載しています。

既存の Ollama `127.0.0.1:11434` は個別の同意後にのみ利用し、推論は観察された根拠と分離します。決定的解析にモデルは不要です。

## ライセンスとプライバシー

Apache-2.0。分析器は対象コードの実行、テレメトリ送信、直接ネットワーク接続を行いません。ユーザーの作業領域はローカルに保持し、公開デモはこの公開リポジトリのみを対象とします。ソース本文、コメント、秘密情報は保持しません。

[プライバシー](PRIVACY.md) · [セキュリティ](SECURITY.md) · [サポート](SUPPORT.md) · [規約](TERMS.md) · [変更履歴](CHANGELOG.md)
