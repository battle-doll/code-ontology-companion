# Third-Party Notices

[English](THIRD_PARTY_NOTICES.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/THIRD_PARTY_NOTICES.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/THIRD_PARTY_NOTICES.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/THIRD_PARTY_NOTICES.md)

Code Ontology Companion 0.5.2 vendors the following browser libraries so each
generated workbench remains a self-contained local HTML file. They are not
loaded from a CDN, make no application-initiated network request, and require
no npm installation.

The optional 3D constellation uses the browser's built-in Canvas2D APIs. It
adds no third-party 3D, WebGL, animation, worker, or accessibility package.

## Cytoscape.js 3.34.0

- Purpose: interactive canvas graph rendering, selection, pan, and zoom
- License: MIT
- Source: <https://github.com/cytoscape/cytoscape.js/tree/v3.34.0>
- npm source archive: <https://registry.npmjs.org/cytoscape/-/cytoscape-3.34.0.tgz>
- Vendored file: `skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js`
- Vendored file SHA-256: `9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3`
- License copy: `skills/manage-code-ontology/assets/vendor/licenses/CYTOSCAPE-MIT.txt`

Copyright (c) 2016-2026, The Cytoscape Consortium.

## ELK.js 0.12.0

- Purpose: same-thread layered layout for bounded ontology subgraphs
- License: EPL-2.0 OR GPL-3.0-or-later; this distribution uses EPL-2.0
- Source: <https://github.com/kieler/elkjs/tree/0.12.0>
- npm source archive: <https://registry.npmjs.org/elkjs/-/elkjs-0.12.0.tgz>
- Vendored file: `skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js`
- Vendored file SHA-256: `1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3`
- License copy: `skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.md`

Copyright (c) 2017 Kiel University and others.

The ELK.js bundle includes the browser module from `web-worker` 1.4.1:

- License: Apache-2.0
- Source: <https://github.com/developit/web-worker/tree/1.4.1>
- npm source archive: <https://registry.npmjs.org/web-worker/-/web-worker-1.4.1.tgz>
- License copy: `skills/manage-code-ontology/assets/vendor/licenses/WEB-WORKER-APACHE-2.0.txt`

The generated workbench does not create a browser Worker; ELK.js uses its
bundled same-thread fallback, consistent with the workbench Content Security
Policy (`worker-src 'none'`).

The RDF exports reference W3C RDF, RDFS, XML Schema, and PROV-O namespace IRIs.
Referencing a public standard or namespace does not bundle its implementation.

The logo and project source are original project assets. Java, Spring, Python,
Apache Jena, RDF4J, GraphDB, and Stardog names appear only to describe
compatibility or migration targets. No third-party logo is bundled.
