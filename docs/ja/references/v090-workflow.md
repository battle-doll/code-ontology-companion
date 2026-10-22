# 0.8.3 のローカルワークフロー

[English](../../../skills/manage-code-ontology/references/v090-workflow.md) | [한국어](../../ko/references/v090-workflow.md) | [日本語](v090-workflow.md) | [简体中文](../../zh-CN/references/v090-workflow.md) | [Русский](../../ru/references/v090-workflow.md)

既存リンクとの互換性のため `v090-workflow.md` のファイル名を保持します。未公開の開発表記 0.9.0 は 0.8.2 に対応し、この文書は現在の 0.8.3 の動作を説明します。

Code Ontology Companion は Java/Spring・Python ソースからオントロジーを作るローカルデータパイプラインです。Python 3.9+、Windows・macOS・Linux をサポートします。AI はローカル MCP、人は生成されたオフライン HTML を使用します。開発者表記は **battle-doll（배틀돌）**です。選択したモデルと推論強度を維持し、特定モデルの品質・トークン量・速度の優位性は主張しません。

## 0.8.3 で生成される人向け HTML

生成されるオフライン HTML は **フォーカスモード**で開始し、別の**全体モード**も用意します。フォーカスのレベル 1 はモジュールの入口です。地図または一覧で項目を選んで進むと、その項目が宣言する子だけをレベル 4 まで表示します。経路ボタンで親へ戻れます。選択範囲の地図はモバイル・PC とも 1 ページに**最大 60 ノードと 160 本の表示エッジ**を含み、残りは明示的なページとテキスト一覧からアクセスできます。これは表示の上限であり、ソース解析の上限ではありません。既存の全体・累積探索は独自の上限とレベル 4 以降の確認を維持します。

フォーカスモードでは選択された有限の表示グラフだけを配置・アニメーション化しますが、埋め込まれた全データの解析と階層構築は行います。任意に大きなリポジトリの完全な遅延読み込みではありません。動きを抑える設定では進入アニメーションを抑え、移動時には古い動作を取り消します。地図は静的ソースの根拠であり、実行時の動作を証明しません。ローカル DOM・幾何・単体テストは実機の使いやすさや実測速度向上の証拠ではありません。ローカル MCP、5 言語の UI・文書、Windows・macOS・Linux 対応を維持します。

## 最新性の確認と中断した処理の復旧

`ontology_status` はソースの `freshness` と生成器の `generatorFreshness`（`current`、`stale`、`unknown`）を分けて返します。生成器の指紋には解析ヘルパーと画面資産が含まれます。ソースが最新でも HTML の再生成が必要な場合があります。指紋のない旧スナップショットは `unknown` です。`sync` はメタデータの欠落を最新性の証拠とせず、新形式のスナップショットを作成します。

完成したスナップショットと SHA-256 成果物 manifest を確定してから、準備済み実行記録を使って系譜を追記し、現在ポインターを原子的に置き換えます。中断後には未完了記録や派生系譜出力の不一致が残ることがあります。`doctor --workspace` は整合性と復旧状態を読み取ります。`recover` は同じ実行のハッシュと対応関係を検証し、系譜イベントを重複させず完了して Turtle 出力も修復します。ハッシュ不一致、状態競合、複数の未完了実行がある場合は停止します。全ファイルを一つのファイルシステムトランザクションにする方式ではありません。Windows は POSIX ディレクトリ fsync ではなく file-flush-only として耐久性を報告します。

許可されたワークスペースで中断が診断されたときに `recover` を使用し、ソースまたは生成器が古ければ `sync` を実行します。MCP は読み取り専用で、復旧や更新を実行しません。

```bash
python3 skills/manage-code-ontology/scripts/companion.py status --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py doctor --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py recover --workspace "/path/outside/repo/ontology"
python3 skills/manage-code-ontology/scripts/companion.py sync --workspace "/path/outside/repo/ontology"
```

## 非公開の増分解析

macOS・Linux では、ソースリポジトリ外の所有者専用 `.parse-cache` を使用します。ソースと解析文脈が一致すると、認証済みパーサー操作を再利用します。ソース本文のバックアップではありません。操作からグラフを再構築して関係を再解決します。対象範囲、インポート/型の文脈、解析器の変更で該当キャッシュは無効になります。キャッシュ再利用は解析精度の証拠ではありません。Windows は非公開キャッシュ用 DACL 設定機能が整うまでキャッシュを保存せず、同等の全体解析を行って対応を維持します。

キャッシュ、本人識別プロファイル、実行記録、`source-manifest.json` は非公開のまま保持します。`CODE_ONTOLOGY_PRIVACY_FILE` は既知の識別情報と一般的な機密パターンを検査しますが、未知の実名をすべて識別するものではありません。`--public` で公開候補を作る場合は保護されたプロファイルとプライバシー検証が必要です。非公開ワークスペース内部、実名、個人メールアドレスをアップロードしないでください。

## AI に必要な根拠を渡す

既存の読み取り専用 11 ツールを維持し、任意使用の12番目 `ontology_evidence_pack` を追加します。一意の ID を持つ検索・近傍照会 1–8 件を同じ不変スナップショットで実行します。スナップショットと品質情報は一度だけ送り、`n:`・`e:` 参照は射影されたノードと根拠の正確な表現を識別します。ノード ID だけで異なる表現を統合せず、返された参照を使います。

```json
{
  "workspace_id": "registered-workspace-id",
  "requests": [
    {"id": "symbols", "operation": "search", "term": "OrderService", "limit": 20},
    {"id": "callers", "operation": "neighbors", "symbol": "OrderService", "direction": "incoming", "limit": 100}
  ],
  "node_fields": ["qualifiedName", "path", "metadata"],
  "max_results": 100,
  "max_payload_bytes": 65536,
  "max_wire_bytes": 150000
}
```

- `node_fields` は `qualifiedName`・`path`・`metadata` を選択します。既定は全部、`[]` はこれらを省略します。利用可能な識別フィールドを維持し、`omittedNodeFields` が省略項目を示します。
- `max_results` は返す行数 1–200、`max_payload_bytes` は正規化 UTF-8 構造化 JSON の 16384–262144 バイトです。`max_wire_bytes` は要求 ID、互換用複製テキスト、改行を含む実際の JSON-RPC 応答の 16384–1048576 バイトです。`payloadBytes` と `wireBytes` は個別の実測値で、トークン推定ではありません。
- `continuation.tool` と `continuation.arguments` をそのまま使います。スナップショット、条件、予算は固定されます。検索は元の offset を進めます。近傍ページは最初の探索上限の範囲内だけを継続します。最後の `query_limit` も部分結果を意味し、グラフ全体の網羅性を証明しません。
- `excludedReasons`、項目エラー、省略フィールドは明示されます。行と経路根拠はまとめて渡します。1行も収まらなければ進まないカーソルではなく予算調整を案内するエラーを返します。scope は現在のページではなく元の照会を説明します。

## 人向け HTML と RDF 検証

生成した `graph.html` をローカルで開きます。英語・韓国語・日本語・簡体字中国語・ロシア語を選択し、選択対象とフィルターを維持しながらマップと独立したページ一覧を切り替えます。変更画面は以前/現在の値、関係画面は静的な経路根拠を示します。空の結果、欠落、切り詰めの制限も維持します。オフライン HTML は生成時のスナップショットであり、現在のソースや実行状況を調べません。

RDF 1.1 Turtle、`RelationshipEvidence`、限定した PROV-O 系譜は同じオントロジーの出力です。開発/CI では `requirements-validation.txt` に固定した任意依存関係を使い、独立 RDF パーサー、SHACL、JSON/Turtle トリプルの完全一致を検査できます。プラグイン実行時には不要です。依存関係がなければ検証不能となり、成功とは扱いません。

```bash
python3 scripts/validate_rdf_contract.py --json "/path/ontology.json" --turtle "/path/ontology.ttl" --lineage "/path/lineage.ttl"
```

RDF の構造検証はソース解析精度、完全な PROV 準拠、実行成功の証明ではありません。保守的な Java ディスパッチ、Python の定義時/動的処理の部分対応範囲は残ります。JS/TS 解析とモジュール間解決は、このリリースの対応グラフ解析範囲外です。

[ローカル MCP 設定](local-mcp.md) · [プライバシー運用](../PRIVACY_OPERATIONS.md)
