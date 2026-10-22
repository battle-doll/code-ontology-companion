# 第三者に関する通知

[English](../../THIRD_PARTY_NOTICES.md) | [한국어](../ko/THIRD_PARTY_NOTICES.md) | [日本語](THIRD_PARTY_NOTICES.md) | [简体中文](../zh-CN/THIRD_PARTY_NOTICES.md) | [Русский](../ru/THIRD_PARTY_NOTICES.md)

<!-- informational-translation; english-authoritative -->

> 本文書は便宜のための翻訳です。内容に相違がある場合は、英語原文が優先されます。

Code Ontology Companion 0.8.3 候補は Python 標準ライブラリとブラウザーの Canvas/DOM API を使用します。2D 表示の削除に伴い Cytoscape.js、ELK.js、web-worker の同梱を終了しました。Canvas2D は3D投影を描画する API であり、平面グラフのモードではありません。CDN、npm、ブラウザー worker は不要です。

RDF は W3C RDF、RDFS、XML Schema、PROV-O 名前空間を参照するだけで、その実装を同梱しません。ロゴとソースは本プロジェクトの資産です。互換性の説明に用いる製品名の第三者ロゴは同梱しません。

任意の開発検証環境では、`requirements-validation.txt` に記載した RDFLib 7.1.4 と pySHACL 0.30.1 をパッケージレジストリからインストールします。解析器、MCP サーバー、生成 HTML には同梱されず、それらから読み込まれません。完全パッケージの独立した検証器を使用するには、利用者がこれらを明示的にインストールします。各配布物の依存関係とライセンス通知が適用されます。
