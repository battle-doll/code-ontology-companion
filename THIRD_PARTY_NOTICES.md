# Third-Party Notices

[English](THIRD_PARTY_NOTICES.md) | [한국어](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ko/THIRD_PARTY_NOTICES.md) | [日本語](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ja/THIRD_PARTY_NOTICES.md) | [简体中文](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/zh-CN/THIRD_PARTY_NOTICES.md) | [Русский](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/THIRD_PARTY_NOTICES.md)

The Code Ontology Companion 0.9.1 candidate contains no bundled third-party libraries. It uses the Python standard library and browser Canvas/DOM APIs. It no longer bundles Cytoscape.js, ELK.js or web-worker after removal of the 2D view. The Canvas2D API draws the 3D projection; it is not a separate planar graph mode. No CDN, npm installation or browser worker is required.

RDF exports reference W3C RDF, RDFS, XML Schema and PROV-O namespace IRIs; this does not bundle their implementations. The logo and project source are original assets. Java, Spring, Python, Apache Jena, RDF4J, GraphDB and Stardog names describe compatibility; no third-party logo is bundled.

The optional development validation environment uses RDFLib 7.1.4 and pySHACL 0.30.1 from their package registries, declared in `requirements-validation.txt`. They are not bundled or imported by the analyzer, MCP server or generated HTML. The full package includes a separate validator that requires the operator to install these extras explicitly. Their distributions carry their own dependency and license notices.
