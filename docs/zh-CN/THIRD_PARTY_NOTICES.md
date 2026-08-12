<!-- informational-translation; english-authoritative -->
# 第三方声明

[English](../../THIRD_PARTY_NOTICES.md) | [한국어](../ko/THIRD_PARTY_NOTICES.md) | [日本語](../ja/THIRD_PARTY_NOTICES.md) | [简体中文](THIRD_PARTY_NOTICES.md)

> 本译文仅为方便阅读而提供。如本译文与英文原文存在任何差异，以英文原文为准。此译文不替代任何随附许可证原文。

Code Ontology Companion 0.5.1 随附以下浏览器库，使每个生成的工作台都保持为自包含的本地 HTML 文件。这些库不从 CDN 加载，不发起由应用启动的网络请求，也不要求 npm 安装。

## Cytoscape.js 3.34.0

- 用途：交互式画布图谱渲染、选择、平移和缩放
- 许可证：MIT
- 来源：<https://github.com/cytoscape/cytoscape.js/tree/v3.34.0>
- npm 源归档：<https://registry.npmjs.org/cytoscape/-/cytoscape-3.34.0.tgz>
- 随附文件：`skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js`
- 随附文件 SHA-256：`9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3`
- 许可证副本：`skills/manage-code-ontology/assets/vendor/licenses/CYTOSCAPE-MIT.txt`

Copyright (c) 2016-2026, The Cytoscape Consortium.

## ELK.js 0.12.0

- 用途：为有界本体子图提供同线程分层布局
- 许可证：EPL-2.0 OR GPL-3.0-or-later；本分发使用 EPL-2.0
- 来源：<https://github.com/kieler/elkjs/tree/0.12.0>
- npm 源归档：<https://registry.npmjs.org/elkjs/-/elkjs-0.12.0.tgz>
- 随附文件：`skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js`
- 随附文件 SHA-256：`1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3`
- 许可证副本：`skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.md`

Copyright (c) 2017 Kiel University and others.

ELK.js bundle 包含来自 `web-worker` 1.4.1 的浏览器模块：

- 许可证：Apache-2.0
- 来源：<https://github.com/developit/web-worker/tree/1.4.1>
- npm 源归档：<https://registry.npmjs.org/web-worker/-/web-worker-1.4.1.tgz>
- 许可证副本：`skills/manage-code-ontology/assets/vendor/licenses/WEB-WORKER-APACHE-2.0.txt`

生成的工作台不会创建浏览器 Worker；ELK.js 使用其内置的同线程后备方案，这与工作台 Content Security Policy（`worker-src 'none'`）一致。

RDF 导出引用 W3C RDF、RDFS、XML Schema 和 PROV-O 命名空间 IRI。引用公共标准或命名空间并不意味着随附其实现。

Logo 和项目源代码是本项目的原创资产。Java、Spring、Python、Apache Jena、RDF4J、GraphDB 和 Stardog 名称仅用于说明兼容性或迁移目标。未随附任何第三方 logo。
