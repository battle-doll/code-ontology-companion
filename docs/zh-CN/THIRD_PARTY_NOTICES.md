<!-- informational-translation; english-authoritative -->
# 第三方声明

[English](../../THIRD_PARTY_NOTICES.md) | [한국어](../ko/THIRD_PARTY_NOTICES.md) | [日本語](../ja/THIRD_PARTY_NOTICES.md) | [简体中文](THIRD_PARTY_NOTICES.md)

> 本译文仅为方便阅读而提供。如本译文与英文原文存在任何差异，以英文原文为准。此译文不替代任何随附许可证原文。

Code Ontology Companion 0.9.1 候选版使用 Python 标准库和浏览器 Canvas/DOM API。移除2D视图后，不再捆绑 Cytoscape.js、ELK.js 和 web-worker。Canvas2D 用于绘制3D投影，并非平面图模式。不需要 CDN、npm 或浏览器 worker。

RDF 仅引用 W3C RDF、RDFS、XML Schema 和 PROV-O 命名空间，不捆绑其实现。标志和源代码为本项目资产。产品名称仅用于兼容性说明，不捆绑第三方标志。

可选开发验证环境从软件包注册表安装 `requirements-validation.txt` 中声明的 RDFLib 7.1.4 和 pySHACL 0.30.1。分析器、MCP 服务器和生成的 HTML 不捆绑或导入它们。完整软件包中的独立验证器要求使用者显式安装这些额外依赖。各发行版均附有自己的依赖和许可证声明。
