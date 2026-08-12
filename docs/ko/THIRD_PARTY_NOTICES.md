<!-- informational-translation; english-authoritative -->
# 타사 고지

[English](../../THIRD_PARTY_NOTICES.md) | [한국어](THIRD_PARTY_NOTICES.md) | [日本語](../ja/THIRD_PARTY_NOTICES.md) | [简体中文](../zh-CN/THIRD_PARTY_NOTICES.md)

> 이 번역은 편의를 위한 정보 제공용입니다. 내용이 다르거나 상충하는 경우 [영어 원문](../../THIRD_PARTY_NOTICES.md)이 우선합니다. 라이선스 원문 자체는 번역하지 않습니다.

Code Ontology Companion 0.5.1은 생성되는 각 workbench가 자체 완결형 local HTML file로 유지되도록 다음 browser library를 vendor합니다. CDN에서 불러오지 않고, application이 시작하는 network request를 만들지 않으며, npm 설치가 필요하지 않습니다.

## Cytoscape.js 3.34.0

- 용도: 대화형 canvas graph rendering, selection, pan, zoom
- 라이선스: MIT
- 소스: <https://github.com/cytoscape/cytoscape.js/tree/v3.34.0>
- npm 소스 archive: <https://registry.npmjs.org/cytoscape/-/cytoscape-3.34.0.tgz>
- Vendored file: `skills/manage-code-ontology/assets/vendor/cytoscape-3.34.0.min.js`
- Vendored file SHA-256: `9c2a3bf2592e0b14a1f7bec07c03a54f16dedf32af9cd0af155c716aa6c87bc3`
- 라이선스 사본: `skills/manage-code-ontology/assets/vendor/licenses/CYTOSCAPE-MIT.txt`

Copyright (c) 2016-2026, The Cytoscape Consortium.

## ELK.js 0.12.0

- 용도: 제한된 ontology subgraph를 위한 same-thread layered layout
- 라이선스: EPL-2.0 OR GPL-3.0-or-later; 이 배포판은 EPL-2.0을 사용합니다.
- 소스: <https://github.com/kieler/elkjs/tree/0.12.0>
- npm 소스 archive: <https://registry.npmjs.org/elkjs/-/elkjs-0.12.0.tgz>
- Vendored file: `skills/manage-code-ontology/assets/vendor/elkjs-0.12.0.bundled.js`
- Vendored file SHA-256: `1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3`
- 라이선스 사본: `skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.md`

Copyright (c) 2017 Kiel University and others.

ELK.js bundle에는 `web-worker` 1.4.1의 browser module이 포함됩니다.

- 라이선스: Apache-2.0
- 소스: <https://github.com/developit/web-worker/tree/1.4.1>
- npm 소스 archive: <https://registry.npmjs.org/web-worker/-/web-worker-1.4.1.tgz>
- 라이선스 사본: `skills/manage-code-ontology/assets/vendor/licenses/WEB-WORKER-APACHE-2.0.txt`

생성된 workbench는 browser Worker를 생성하지 않습니다. ELK.js는 workbench Content Security Policy(`worker-src 'none'`)에 맞게 bundled same-thread fallback을 사용합니다.

RDF export는 W3C RDF, RDFS, XML Schema, PROV-O namespace IRI를 참조합니다. public standard 또는 namespace를 참조한다고 해서 그 구현을 함께 제공하는 것은 아닙니다.

logo와 project source는 original project asset입니다. Java, Spring, Python, Apache Jena, RDF4J, GraphDB, Stardog 명칭은 호환성 또는 migration target을 설명하기 위해서만 사용됩니다. third-party logo는 포함하지 않습니다.
