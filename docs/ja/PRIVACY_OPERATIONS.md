# プライバシー運用 — 0.9.0

[English](../../skills/manage-code-ontology/references/privacy-operations.md) | [한국어](../ko/PRIVACY_OPERATIONS.md) | [日本語](../ja/PRIVACY_OPERATIONS.md) | [简体中文](../zh-CN/PRIVACY_OPERATIONS.md) | [Русский](../ru/PRIVACY_OPERATIONS.md)

## 個人識別子はローカルに保持

対応する生成オントロジー成果物、ローカル MCP 応答、オフライン HTML にローカル検査を適用します。設定済みの非公開プロファイルは指定した実名・個人メールを拒否し、一般検査も私的メール形式の値を拒否します。公開コード、fixture、パッケージ情報、報告、テスト出力に実際の個人情報を含めません。公開発行者は battle-doll の別名です。

`CODE_ONTOLOGY_PRIVACY_FILE` は保護するソース・出力ルートの外に置く非公開プロファイルを指定します。原文ではなく非公開キー、長さ制限、HMAC-SHA256 指紋を保存します。この資料も非公開であり、キーや指紋をコミット、送信、表示したり HTML/JSON/MCP に埋め込みません。毎回新たに読み、リンク、reparse point、不正・過大なプロファイルを拒否し、POSIX では `0600` を要求します。Windows は実際に開いたプロファイルハンドルの所有者と DACL を読み取り前後に検査します。現在の利用者、Local System、組み込み Administrators 以外への有効な許可、null DACL、未対応 ACE、確認できない権限は拒否します。実 Windows 実行の検証は別途必要であり、POSIX やモックテストで成功を主張しません。架空の設定コマンドではなく実際のruntime契約を使います。

0.9.0 の公開用エクスポートには保護された空でない識別子プロファイルが必要です。通常のローカル探索では任意のままです。公開成果物 manifest に非公開 source manifest、解析キャッシュキー、実行記録を含めません。ファイル単位の差分解析は安全に利用できる非公開の認証済みキャッシュを使用し、確認できなければ全体解析に戻ります。Windows のキャッシュ保存は非公開ディレクトリとキーの作成方法が検証されるまで無効で、全体解析は利用できます。これは実装済みの Windows プロファイル DACL 検査とは別です。

失敗は一致した値でなく分類だけを示します。任意プロファイルがなければ実名保護はなく、未知の名前をすべて自動検出する保証もありません。JSON/HTML entity/percent/unicode-escapeの解除は最大3回で、さらに解除可能な値は `encoding_depth` で拒否します。正規化は有限で、全バイナリ情報、画像中の文字、第三者出力、全エンコーディングは対象外です。ローカル PASS を全体の個人情報ゼロと見なしません。

## 公開経路ごとに確認

公開 PR の前に、実際の GitHub アカウントのメール保護を検証した新しい信頼できる記録を要求します。手動記録、ローカル `git config`、設定済み資料、単体テストは現在のサービス確認証拠ではありません。選択したソースとサービス自動生成commit refをすべて監査します。HEADだけでは保管された一部PR merge refを除外します。直接branchテストはコードの証拠であり、将来のサービス生成commitの安全証拠ではありません。

公式ディレクトリの実際の公開開発者名を別途確認します。battle-dollだけでなく個人情報が見えるなら、アップロード、提出、公開の前に **HOLD** します。ファイル送信、ポータル草案確認、承認、公開listingは異なる状態です。保持refの露出はサービスが削除を確認するまで未解決であり、branchやローカル変更だけで全体削除と主張しません。

## 製品と確認限界を維持

完全なソースcheckoutまたはfull配布で `CODE_ONTOLOGY_PRIVACY_FILE` を安全に設定した後、Python3.9以降と認証済みGitHub CLIで読み取り専用の発行者検査を実行します。

```sh
python scripts/check_publication_privacy.py
```

プロファイルには名前・メール両方のdeny一覧が必要です。別名のみのmanifest、共有scannerによるローカルGit `--all` の識別子・メッセージ・ref名、公開GitHubプロファイル(nameはnull/空/battle-doll/배틀돌、emailはnull)、PR題名・本文、RESTの各 `merge_commit_sha` author/committer/メッセージを検査します。最大100PR、PRごとに最大2APIを読み、100件で満杯のページ、読めない情報、時間切れはUNKNOWNです。未取得・削除済み・サービス内部ref、過去ソースblob、issue/comment、CIログ、画像pixelを除外します。GitHubメール保護UIとOpenAIで選択された検証済み識別情報は確認できないため、機械検査が通っても **HOLD** と終了コード1を維持します。手動の `--verified` 回避はありません。任意の `--output` はソース外に安全化されたJSON記録を保存し、findingsは規則・PR番号・件数だけです。PRや送信を承認する記録ではありません。この配布管理CLIはskills-onlyに含まず、生成・MCP・HTMLにネットワーク動作を追加しません。

Windows、macOS、Linux を維持します。AIは読み取り専用ローカル MCP、人は依頼された生成オフライン HTML を利用します。このpatchは別のHTML報告、リモートendpoint、telemetry、個人確認の送信手順を作りません。利用者のモデルと推論強度も維持します。

HTMLの選択コピー欄は完全なローカルfile URLでなくsnapshot/entity/edgeの相対queryを使います。自由検索文をURL・historyに保存または再生せず、native JSON parseのエラー原文もUIに表示しません。

最終候補でソース、選択ref、展開パッケージの検査と両exact release profileを確認します。既存0.8.0タグは変更しません。合成回帰テストはそのケースの検出動作を示し、実ホストE2E、専門翻訳、全アクセシビリティ、サービス削除は別証拠が必要です。[翻訳範囲](../TRANSLATION_COVERAGE.md)は5言語ガイドと実範囲を示します。
