# Code Ontology Companion

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md) | [Русский](README.ru.md)

Исследуйте разрешённый Java/Spring или Python проект как пространственную 3D-карту. Находите символы, прослеживайте зависимости с опорой на исходный код и сравнивайте снимки.

**Обновление к выпуску Astra · 0.6.0.** В честь GPT-6 Astra улучшены поиск, прослеживаемость оснований и инструкции навыка. Людям — наглядный 3D-интерфейс, ИИ — структурированные данные. [Подробности](docs/ASTRA_RELEASE.md).

## Установка / Использование

[Каталог плагинов](https://chatgpt.com/plugins/plugins_6a6a23c0434c8191aec6a38bb590fd3c) · [Пакеты GitHub](https://github.com/battle-doll/code-ontology-companion/releases)

Версия исходного кода — 0.6.0. Каталог проходит отдельную проверку и публикацию, поэтому доступная версия может отличаться. Официальный пакет навыка содержит анализатор, интерфейс и инструкции настройки локального MCP. Полный пакет GitHub также содержит stdio MCP-сервер только для чтения. Облачный адрес не требуется.

## Настоящая онтология самого плагина

[**Открыть 3D-карту →**](https://battle-doll.github.io/code-ontology-companion/)

Создана из поддерживаемого исходного кода этого плагина с указанием коммита и оснований. Выберите модуль или символ, чтобы увидеть связи и места в исходном коде. Это статический снимок. Для новой вкладки используйте Command-click или Ctrl-click.

[Происхождение снимка](https://battle-doll.github.io/code-ontology-companion/snapshot.json) · [Архитектура](docs/ARCHITECTURE_AND_ROADMAP.md)

## Возможности версии 0.6.0

- Основной офлайн-интерфейс 3D со структурой, зависимостями, изменениями и фокусировкой камеры.
- Приоритет точных символов, структурные фильтры, страницы результатов и чтение фиксированного снимка.
- Направленные пути зависимостей с основаниями каждого шага и явными ограничениями.
- Единое сравнение добавлений, удалений, изменений и их оснований.
- Типы, импорты, консервативный анализ вызовов, внедрение и сигналы прокси Java/Spring; модули, функции, вызовы и эвристические роли Python.
- Ссылки Code с сохранением исходных оснований, неизменяемые локаторы для Context и явная область совместимости Contracts.
- Клавиатура, текстовый просмотр, уменьшение движения и безопасный резервный режим 2D.

## Быстрый старт

Требуется Python 3.9+. Сначала проверьте поддержку без записи файлов. Анализируйте только собственный или разрешённый код; после согласования создаваемых материалов инициализируйте рабочую область вне репозитория.

```bash
python3 skills/manage-code-ontology/scripts/companion.py doctor --repo "/path/to/repo"
python3 skills/manage-code-ontology/scripts/companion.py preflight --repo "/path/to/repo"
```

```bash
python3 skills/manage-code-ontology/scripts/companion.py init --repo "/path/to/repo" --workspace "/path/outside/repo/ontology" --authorized
python3 skills/manage-code-ontology/scripts/companion.py query --workspace "/path/outside/repo/ontology" --term "OrderService"
python3 skills/manage-code-ontology/scripts/companion.py impact --workspace "/path/outside/repo/ontology" --symbol "OrderService" --direction incoming
python3 skills/manage-code-ontology/scripts/companion.py diff --workspace "/path/outside/repo/ontology"
```

## Основания и совместимость

`graph.html`, `ontology.json` и `ontology.ttl` используют одну онтологию исходного кода. RDF 1.1 Turtle содержит `RelationshipEvidence`, а совместимая с PROV-O история сохраняет происхождение. `inferred` не означает проверку; `runtime_unknown` не доказывает исполнение. Доля связей с основаниями не является точностью анализа.

Code отвечает за структуру кода, Context — за решения и сроки их действия, Contracts — за проверку формата обмена. Продукты независимы. [Контракт данных ИИ](skills/manage-code-ontology/references/ai-data-contract.md) · [Обмен ссылками](skills/manage-code-ontology/references/code-reference.md).

В Context передаётся ссылка на исходный артефакт. Прямое преобразование реальных снимков в строгий формат Contracts draft пока не поддерживается; проверенная область описана в руководстве по обмену ссылками.

Существующий Ollama по `127.0.0.1:11434` используется только после отдельного согласия; предположения отделяются от наблюдений. Для детерминированного анализа модель не нужна.

## Лицензия и конфиденциальность

Apache-2.0. Анализатор не исполняет целевой код, не отправляет телеметрию и не делает прямых сетевых запросов. Пользовательские области остаются локальными; публичная демонстрация относится только к этому открытому репозиторию. Тела исходного кода, комментарии и секреты не сохраняются.

[Конфиденциальность](PRIVACY.md) · [Безопасность](SECURITY.md) · [Поддержка](SUPPORT.md) · [Условия](TERMS.md) · [Изменения](CHANGELOG.md)
