# 第三者に関する通知

[English](../../THIRD_PARTY_NOTICES.md) | [한국어](../ko/THIRD_PARTY_NOTICES.md) | [日本語](THIRD_PARTY_NOTICES.md) | [简体中文](../zh-CN/THIRD_PARTY_NOTICES.md)

<!-- informational-translation; english-authoritative -->

> 本文書は便宜のための翻訳です。内容に相違がある場合は、英語原文が優先されます。

Code Ontology Companion 0.3.4 は、生成される各ワークベンチを自己完結型のローカル HTML ファイルとして
維持するため、以下のブラウザーライブラリを同梱しています。これらは CDN から読み込まれず、
アプリケーションが開始するネットワークリクエストを行わず、npm のインストールも必要としません。

## Cytoscape.js 3.34.0

- 目的：インタラクティブなキャンバスグラフの描画、選択、パン、およびズーム
- ライセンス：MIT
- ソース：<https://github.com/cytoscape/cytoscape.js/tree/v3.34.0>
- npm ソースアーカイブ：<https://registry.npmjs.org/cytoscape/-/cytoscape-3.34.0.tgz>
- 同梱ファイル：`skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js`
- 同梱ファイルの SHA-256：`9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3`
- ライセンスのコピー：`skills/manage-code-ontology/assets/vendor/licenses/CYTOSCAPE-MIT.txt`

Copyright (c) 2016-2026, The Cytoscape Consortium.

## ELK.js 0.12.0

- 目的：上限付きオントロジーサブグラフに対する同一スレッド内のレイヤードレイアウト
- ライセンス：EPL-2.0 OR GPL-3.0-or-later。本配布物では EPL-2.0 を使用
- ソース：<https://github.com/kieler/elkjs/tree/0.12.0>
- npm ソースアーカイブ：<https://registry.npmjs.org/elkjs/-/elkjs-0.12.0.tgz>
- 同梱ファイル：`skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js`
- 同梱ファイルの SHA-256：`1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3`
- ライセンスのコピー：`skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.md`

Copyright (c) 2017 Kiel University and others.

ELK.js バンドルには、`web-worker` 1.4.1 のブラウザーモジュールが含まれています。

- ライセンス：Apache-2.0
- ソース：<https://github.com/developit/web-worker/tree/1.4.1>
- npm ソースアーカイブ：<https://registry.npmjs.org/web-worker/-/web-worker-1.4.1.tgz>
- ライセンスのコピー：`skills/manage-code-ontology/assets/vendor/licenses/WEB-WORKER-APACHE-2.0.txt`

生成されるワークベンチはブラウザー Worker を作成しません。ELK.js は、ワークベンチの
Content Security Policy（`worker-src 'none'`）に従って、同梱された同一スレッドのフォールバックを使用します。

RDF エクスポートは、W3C RDF、RDFS、XML Schema、および PROV-O の名前空間 IRI を参照します。
公開標準または名前空間を参照しても、その実装が同梱されることにはなりません。

ロゴおよびプロジェクトソースは、プロジェクト独自の資産です。Java、Spring、Python、Apache Jena、
RDF4J、GraphDB、および Stardog の名称は、互換性または移行先を説明する目的に限り使用されています。
第三者のロゴは同梱されていません。
