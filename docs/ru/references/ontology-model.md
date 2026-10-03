# Модель онтологии

[English](../../../skills/manage-code-ontology/references/ontology-model.md) | [한국어](../../ko/references/ontology-model.md) | [日本語](../../ja/references/ontology-model.md) | [简体中文](../../zh-CN/references/ontology-model.md) | [Русский](ontology-model.md)

Экспорт использует RDF 1.1 Turtle и собственный словарь `https://battle-doll.github.io/code-ontology-explorer/schema#`.

## Сущности и отношения

Классы: `Package`, `Module`, `Class`, `Interface`, `Enum`, `Record`, `Function`, `AsyncFunction`, `Method`, `AsyncMethod`, `FrameworkAnnotation`, `Decorator`, `ExternalType`, `ExternalModule`, `ExternalCallable`, `FrameworkConcept`, `PipelineRole`, `PolicyLeaf`, `RuntimeBranch`.

Отношения: `DECLARES`, `IMPORTS`, `EXTENDS`, `IMPLEMENTS`, `ANNOTATED_BY`, `DECORATED_BY`, `INJECTS`, `DECLARES_BEAN`, `MANAGED_AS`, `MAY_BE_PROXIED_BY`, `CALLS`, `HAS_PIPELINE_ROLE`, `READS_POLICY_LEAF`, `DECLARES_RUNTIME_BRANCH`, `GUARDS_RUNTIME_BRANCH`. Имена RDF-предикатов используют UpperCamelCase, например `co:AnnotatedBy`.

## Доказательства и качество

В0.8.1 сохраняются прямые RDF-тройки и стабильные ID. JSON-ребро содержит массив `evidence`: стабильный `rule_id`, качественный `basis` (`direct_syntax`, `resolved_static`, `framework_semantic`, `name_heuristic`) и `runtime_status` (`not_applicable`, `runtime_unknown`). Возможны относительный `path`, `line_start`, `line_end` и ограниченный список `limitations`.

`document.quality` версии1.0 сообщает количество/охват доказательств, категории basis/runtime и состояние/возможности/неподдерживаемое выполнение адаптеров Java/Python. RDF добавляет `RelationshipEvidence`. Basis не является вероятностью; `runtime_unknown` не доказывает выполнение, а покрытие не доказывает точность. Статическое ребро не является трассой, заключением об уязвимости или доказательством активности Spring proxy/bean.

## Переносимость

`ontology.ttl` — обменный формат для совместимого RDF-потребителя; установка или настройка внешнего хранилища не входит вMVP. Стабильные URN и словарь Explorer1.0 сохраняются. Локальный инструмент использует неизменяемый JSON снимка; происхождение экспортируется отдельно в `lineage.ttl` с пространством `https://battle-doll.github.io/code-ontology-companion/provenance#`. Классы observed/declared/inferred/validated/approved остаются раздельными; см. [модель происхождения](lineage-model.md).


## Чтение, обмен и происхождение в0.8.1

Локальныйstdio MCP читает неизменяемый `ontology.json` иworkspace `lineage.jsonl`, возвращая ограниченные структурированные доказательства с фиксированнымsnapshot. Человеческий `graph.html` встраивает переносимую проекцию того жеJSON. `ontology.ttl` — параллельный экспорт RDF 1.1 Turtle графа кода/`RelationshipEvidence`; объявление PROV prefix не создаёт provenance triples. Отдельныйworkspace `lineage.ttl` экспортирует подмножество PROV-O из руководства: записи какEntity, сопоставленные snapshot build со связями генерации источника/snapshot. Человеческая Agent-атрибуция, полная цепь и сертификация соответствия не предоставляются.

Охват доказательств, metadata частичных адаптеров и `runtime_unknown` — диагностические границы, не доказательство точности или выполнения. Частичные диагностики сами не блокируют фиксациюsnapshot; регрессии качества — отдельная проверкаrelease. НастроенныйHMAC-SHA256 отклоняет опасный поддерживаемый вывод, профиль идентификаторов имеет ограниченный охват. Реализованный MVP входного кода не заявляет произвольную загрузку данных или готовую платформуAI.

[W3C RDF 1.1 Turtle](https://www.w3.org/TR/turtle/) · [W3C PROV-O](https://www.w3.org/TR/prov-o/)
