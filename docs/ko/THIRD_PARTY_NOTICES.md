<!-- informational-translation; english-authoritative -->
# 타사 고지

[English](../../THIRD_PARTY_NOTICES.md) | [한국어](THIRD_PARTY_NOTICES.md) | [日本語](../ja/THIRD_PARTY_NOTICES.md) | [简体中文](../zh-CN/THIRD_PARTY_NOTICES.md) | [Русский](../ru/THIRD_PARTY_NOTICES.md)

> 이 번역은 편의를 위한 정보 제공용입니다. 내용이 다르거나 상충하는 경우 [영어 원문](../../THIRD_PARTY_NOTICES.md)이 우선합니다. 라이선스 원문 자체는 번역하지 않습니다.

Code Ontology Companion 0.8.3 후보는 Python 표준 라이브러리와 브라우저 Canvas/DOM API를 사용합니다. 페이지형 목록 제거에 따라 Cytoscape.js, ELK.js, web-worker를 더 이상 배포하지 않습니다. Canvas2D는 3D 투영을 그리는 API이며 별도의 평면 그래프 모드가 아닙니다. CDN, npm 설치, 브라우저 worker가 필요하지 않습니다.

RDF는 W3C RDF, RDFS, XML Schema, PROV-O 이름공간을 참조하며 해당 구현을 포함하지 않습니다. 로고와 소스는 프로젝트 원본 자산입니다. Java, Spring, Python, Apache Jena, RDF4J, GraphDB, Stardog 명칭은 호환성을 설명하며 타사 로고를 배포하지 않습니다.

선택 개발 검증 환경은 `requirements-validation.txt`에 명시한 RDFLib 7.1.4와 pySHACL 0.30.1을 패키지 저장소에서 설치합니다. 분석기·MCP 서버·생성 HTML에 포함하거나 가져오지 않습니다. 전체 패키지의 별도 검증기를 실행하려면 사용자가 이 추가 의존성을 명시적으로 설치해야 합니다. 각 배포본의 의존성과 라이선스 고지가 적용됩니다.
