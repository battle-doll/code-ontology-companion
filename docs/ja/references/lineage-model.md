# リネージモデル

[English](../../../skills/manage-code-ontology/references/lineage-model.md) | [한국어](../../ko/references/lineage-model.md) | [日本語](lineage-model.md) | [简体中文](../../zh-CN/references/lineage-model.md) | [Русский](../../ru/references/lineage-model.md)

非公開追記型 `lineage.jsonl` journalで記録済み変更と推論を区別します。`lineage.ttl` は根拠で限定したPROV-O部分集合の別の交換用出力です。記録は活動自体ではなく情報Entityです。

## Evidence class

- `observed`: source または workspace state から決定論的に抽出されたもの。
- `declared`: ユーザーが述べたもの、または提供された decision record。
- `inferred`: analyzer または model が提案し、独立して確認されていないもの。
- `validated`: 名前付き test、review、replay、その他の再現可能な check に裏付けられたもの。
- `approved`: 責任者または governance process が明示的に許可したもの。

confidence や反復だけを根拠に `inferred` を `validated` へ書き換えてはなりません。
オプションのローカル LLM の提案は、この lineage journal ではなく、非公開 enrichment sidecar に保存します。
別個の再現可能な validation または責任者による approval が明示的に記録されるまで、提案は
`inferred` のままです。model の confidence value は provenance であって、validation ではありません。

## コアイベントシーケンス

```text
意思決定
  -> 変更
  -> 検証
  -> 有効化
  -> 観測
  -> 結果
  -> 維持 / ロールバック / 置換済み
```

code、deployment、activation、outcome は別々の event です。commit は deployment を証明せず、
deployment は runtime activation を証明せず、change に近接した outcome は change が原因であることを
証明しません。

## 時間のセマンティクス

現在のリリースは transaction time、すなわち Companion が event を保存した時刻を記録します。
ある fact がそれより前に有効になっていた場合、人間が読める summary にその日付を
記載してください。修正された発効日を
模擬するために古い event を上書きしてはなりません。修正 event を追記してください。

## ポータブルな識別子

- Workspace ID と event ID はランダムな local UUID です。
- Snapshot ID は UTC 時刻と source fingerprint prefix を組み合わせます。
- Code entity ID は RDF 互換性のため Explorer 1.0 vocabulary を維持します。
- リポジトリの絶対パスと完全な source fingerprint は、非公開の local configuration または
  manifest に保持します。通常の RDF、HTML、MCP 応答では公開しません。


## 0.8.1 PROV-O部分集合とプライバシー境界

既存event URIの記録は `coc:LineageRecord`, `prov:Entity` です。保存時刻は `coc:recordedAt` で、timezone付き有効ISO値は `xsd:dateTime`、不正またはtimezoneなしの過去値はplain literalです。活動開始・終了時刻は推測しません。

保存済み `observed` スナップショット確定記録を通常ファイル `snapshot.json` と `source-manifest.json` で裏付けた場合だけ、別の `coc:SnapshotBuild` / `prov:Activity`, `coc:OntologySnapshot` / `prov:Entity`, `coc:ScopedSource` / `prov:Entity` を追加します。run ID、workspace/snapshot ID、trigger、生成時刻、revision、ソース範囲、再計算した集約SHA-256を照合します。記録→buildは `coc:describesBuild`、build→ソースは `prov:used`、snapshot→buildは `prov:wasGeneratedBy`、snapshot→ソースは `prov:wasDerivedFrom` です。snapshotの `prov:generatedAtTime` は照合済みmetadataです。前の裏付け済み確定記録は独自の `coc:previousSnapshot` だけで接続し、以前のsnapshotからのPROV派生は推論しません。

条件不足時は記録を保持して生成関係を省きます。保存済みローカル根拠の照合であり、現在ソースの再観測やjournalの暗号認証ではありません。`prov:Agent`/Person、人への帰属、推測した実行時刻、完全な系譜、PROV準拠認証を主張しません。MCPはJSON/JSONL journal契約を読み、Turtleは交換用です。ファイルhashは非公開manifest、集約指紋は非公開snapshot JSON metadataにも残り得ます。通常のRDF/HTML/MCPは全指紋や絶対repoルートを公開しません。

設定済みHMAC-SHA256検査は新しいraw event、既存journal、準備したTurtleを追記・置換の前に検査します。私的情報は全体拒否し、密かに省略しません。記録には相対パスを推奨します。任意I/O失敗で2ファイルを単一transactionにする保証はなく、任意プロファイルなしで全実名は検出しません。

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
