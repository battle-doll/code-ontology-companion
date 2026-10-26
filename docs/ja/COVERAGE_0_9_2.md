# 0.9.2 欠落検出とカバレッジ検証

[English](../COVERAGE_0_9_2.md) | [한국어](../ko/COVERAGE_0_9_2.md) | [日本語](COVERAGE_0_9_2.md) | [简体中文](../zh-CN/COVERAGE_0_9_2.md) | [Русский](../ru/COVERAGE_0_9_2.md)

開発者: **battle-doll (배틀돌)**。AI はローカル MCP、人は生成されたオフライン HTML を使います。Windows、macOS、Linux を対象とし、実 OS の検証とローカル回帰テストを区別します。この手順は対象アプリの公開・インストール・再起動を行いません。

## 選択範囲の全体を先に記録

AI に「選択した全範囲を一覧化し、除外・失敗も分母に残して六段階のカバレッジと未解決事項を示して」と依頼できます。一覧化は読み取り専用です。

```sh
python3 "$COMPANION" coverage-inventory --repo /path/to/source --source-root src
```

既定の一覧化は pipeline アダプターを使い、`--mode legacy` は従来の Java/Python 対応を測定します。組み込みの除外ディレクトリも台帳に残ります。この一覧化は `.gitignore` パターンを解釈しないため、それによる除外や完全性を保証しません。

`COMPANION` は信頼したバンドルの `skills/manage-code-ontology/scripts/companion.py` です。既存の Python 3.9 以上を使い、Windows では `py -3` も利用できます。許可されたルートごとに `--source-root` を繰り返し、検証結果はソースやインストール先の外に保存します。機密らしいファイル名だけを理由に正常な構造を黙って捨てません。秘密値、リンク・reparse point、安全でないパス、読めない内容は保護し、除外・未対応言語・上限・文字コードエラー・アクセス不能境界を記録します。読めないディレクトリがあれば全ファイルの分母は `UNKNOWN` です。

処理できない項目は対象・原因・影響・代替案を残し、その項目の先へ進む前にユーザーの判断を得ます。承認済みの正常処理に再承認は不要です。

## 六つの測定を分ける

| 段階 | 数えられる根拠 | 完全性を示さないもの |
| --- | --- | --- |
| `scope_files` | 独立に選んだ全ファイル中の処理済みファイル | フィルター通過分だけの割合 |
| `declarations_types` | 明示した期待集合の正確な宣言・型 | ファイルの存在・似た名前 |
| `exact_calls` | 呼出位置と正確な対象宣言に一致する根拠 | 候補・placeholder・`IMPORTS`・`IMPLEMENTS`・実行時推測 |
| `policy_semantics` | 表現された断片と独立照合した必須条件・式 | ポリシーノードや数値定数の存在 |
| `mcp_delivery` | 固定した一つの問い合わせの全ページと正確な payload | `truncated=false` だけ・一部ページ |
| `policy_document` | 対応する段落が元の意味要素を述べるとの独立レビュー | 引用・ハッシュだけ・未レビュー文 |

分子・分母・割合・測定範囲・欠落・根拠・限界を保持します。不明な分母は `UNKNOWN` であり 0 や 100% ではありません。標本率を全体に一般化せず、部分記述に 0.5 点を付けません。生成済み関係の根拠付与率は全コードのカバレッジではありません。欠落・未対応・不明が残れば、実行や snapshot 作成が成功しても全体は `PARTIAL` または `BLOCKED` です。

## snapshot と意味の根拠

pipeline workspace は `ontology_pipeline_status` で具体的な snapshot を取得し、`ontology_pipeline_coverage` を最後までページ取得します。`ontology_pipeline_search` の `callsite`・`semantic_fragment` で呼出と意味断片を取得できます。正確な静的対象・候補・未解決を区別し、インターフェース対象を実際の実装選択とみなしません。Java の限定されたフィールド・定数・代入・条件・戻り式を保持します。任意文字列や機密値は保存せず、未解決呼出・未対応制御フロー・初期値なしには位置と理由を残します。`represented` は対応構文の保持であり、業務規則全体の検証ではありません。単位は独立に対応した結合がなければ `UNKNOWN` です。既存の実行可能 typed-policy は別契約です。

`snapshotId`・`sourceFingerprint`・`scopeDigest`・`analysisSpecId` とファイルハッシュを結合します。`nextOffset` が終わるまで `queryDigest`・offset・total・returned・payload を保存します。先頭・途中・最終ページの欠落、異なる識別子や問い合わせの混合、重複 ID、同じ ID の payload 改変は無効です。保存 snapshot の状態確認はソース最新性の再検査ではありません。

`coverage_contract.validate_policy_document` は独立したソース期待集合、断片、MCP ページ、文書バイト、主張を受け取ります。別入力 `semantic_reviews` によるレビューは期待集合・ソース根拠・文書・段落・意味要素・レビュアー・snapshot を結合します。ハッシュは整合性だけを示し、意味の妥当性には独立レビューが必要です。直接ソースを読んだ補足は `direct_source_supplemented` とし、完全記述でも `ontologyOnlyFull` に算入しません。完全・部分・未記述・根拠なしを区別し、ソース・snapshot・期待集合・段落が変われば再検証します。 各主張は `directSourceSupplemented` に JSON 真偽値 `true` または `false` を明示します。未指定や別の型では知識の根拠は未検証です。

測定済みの六指標をローカルに出力します。

```sh
python3 "$COMPANION" coverage-validate --input /path/to/coverage-request.json --output /path/to/new-verification
```

入力は `binding`・六つの `metrics`・`remaining` です。このコマンドは整合性を確認して `coverage.json`・`coverage.md` を出力します。分母の推測、独立文書レビュー、全体完全性の証明は行いません。非公開ソースと検証物はローカルに保管し、公開 fixture や文書に個人情報・秘密値・運用内容を入れません。
