# リネージモデル

[English](../../../skills/manage-code-ontology/references/lineage-model.md) | [한국어](../../ko/references/lineage-model.md) | [日本語](lineage-model.md) | [简体中文](../../zh-CN/references/lineage-model.md)

リネージを使い、何が変更されたかと、その変更について単に推論されたことを区別します。
ローカル journal は追記専用です。`lineage.ttl` は、PROV-O 互換 activity と Companion の
evidence class を使って event をエクスポートします。

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
