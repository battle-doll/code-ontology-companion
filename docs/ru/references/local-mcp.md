# Необязательный локальный MCP только для чтения

> В 0.9.0 добавлены дисковые разделы, запечатанные правила и доступ только владельцу по умолчанию. Полный пакет содержит **19 MCP-инструментов только для чтения (12 прежних + 7 новых)**. Ниже описана прежняя совместимость, если явно не названа команда конвейера. Для новых многоязычных пространств и правил используйте руководство реализации. [0.9.0](https://github.com/battle-doll/code-ontology-companion/blob/main/docs/ru/PIPELINE_0_9_0.md)

[English](../../../skills/manage-code-ontology/references/local-mcp.md) | [한국어](../../ko/references/local-mcp.md) | [日本語](../../ja/references/local-mcp.md) | [简体中文](../../zh-CN/references/local-mcp.md) | [Русский](local-mcp.md)

Полный пакет Code Ontology Companion включает локальный stdio MCP для пространств, явно инициализированных CLI. Он не слушает порт, принимает зарегистрированные ID вместо произвольных путей и предоставляет идемпотентное чтение. Инициализация, обновление, запись происхождения, изменение целевого кода, установка, загрузка и вызов необязательного LLM через MCP не выполняются.

## Граница пакета

Официальный Skills-only включает это руководство, детерминированный анализатор и LLM-помощник. Полный GitHub-пакет той же версии дополнительно содержит:

```text
code-ontology-companion/
  mcp/server.py
  skills/manage-code-ontology/scripts/companion.py
  skills/manage-code-ontology/scripts/code_ontology_core.py
```

Используйте полный пакет той же версии со страницы [GitHub Releases](https://github.com/battle-doll/code-ontology-companion/releases) и проверьте опубликованную контрольную сумму. Сервер должен оставаться рядом со своими скриптами. Не смешивайте версии и не скачивайте/устанавливайте ничего незаметно.

## Предварительные условия

1. Python 3.9 или новее.
2. Хотя бы один разрешённый репозиторий инициализирован CLI; при этом создаётся и регистрируется случайный ID пространства.
3. `mcp/server.py` и Companion-скрипты подтверждены как обычные файлы правильного полного пакета, а не одноимённые файлы цели.
4. Настройка MCP запрошена пользователем. Перед изменением конфигурации Codex покажите точные пути интерпретатора и сервера; сохраните посторонние записи.
5. Если bundled `.mcp.json` уже работает, не добавляйте дублирующий ручной сервер.

## macOS

Проверьте существующий Python без изменений машины:

```bash
command -v python3
python3 --version
```

Укажите подтверждённые абсолютные пути в `~/.codex/config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Linux

Найдите существующий Python дистрибутива и убедитесь, что версия не ниже 3.9:

```bash
command -v python3
python3 --version
```

В `~/.codex/config.toml` используйте его абсолютный путь и сервер извлечённого полного пакета:

```toml
[mcp_servers."code-ontology-companion-local"]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/complete-code-ontology-companion/mcp/server.py"]
startup_timeout_sec = 30
enabled = true
```

## Windows

Проверьте уже установленный Python:

```powershell
py -3 --version
py -3 -c "import sys; print(sys.executable)"
```

Укажите выведенный абсолютный путь и литеральные TOML-строки в `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers."code-ontology-companion-local"]
command = 'C:\absolute\path\to\python.exe'
args = ['C:\absolute\path\to\complete-code-ontology-companion\mcp\server.py']
startup_timeout_sec = 30
enabled = true
```

Если launcher отсутствует, используйте другой установленный и явно проверенный Python 3.9+. Companion не устанавливает Python.

## Проверка в новом процессе Codex

После изменения записи полностью откройте новый процесс Codex: старый может сохранить прежнюю версию сервера или список инструментов.

1. Вызовите `ontology_list_workspaces` без аргументов.
2. Выберите возвращённый `id`.
3. Вызовите `ontology_status` с `{"workspace_id":"<id>"}`.
4. Для последующих чтений используйте то же snake-case поле `workspace_id`; не `workspaceId` и не файловый путь.

В версии 0.9.0 доступны 12 инструментов:

- `ontology_list_workspaces`
- `ontology_status`
- `ontology_search`
- `ontology_neighbors`
- `ontology_history`
- `ontology_changes`
- `ontology_lineage`
- `ontology_large_modules`
- `ontology_large_search`
- `ontology_large_neighbors`
- `ontology_evidence_bundle`
- `ontology_evidence_pack`

У всех `readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: false`, `idempotentHint: true`. Запись, обновление, восстановление, удаление, установка, загрузка и доступ по произвольному пути — отдельные разрешённые CLI-операции.

## Устранение проблем

Если `node ./mcp/launcher.mjs` не работает из-за отсутствия Node, используйте прямую Python stdio-конфигурацию выше. При отсутствии инструментов или старой версии откройте новый процесс и проверьте, что пути ведут в один полный пакет. При неизвестном ID перечислите пространства под тем же пользователем ОС, который их создал; не заменяйте ID путём. При сбое старта сначала проверьте версию Python и обычные файлы. Не исполняйте код цели и не ослабляйте проверки ссылок, прав или вывода.

`pipelineStatus: recovery_required` и `pendingRecoveryRuns` означают незавершённую транзакцию. Разрешённое восстановление выполняется CLI `recover --workspace ...`; MCP остаётся читающим. Старый или уже переключённый полный снимок доступен, но незавершённость нельзя выдавать за здоровый pipeline.

## Закреплённые контракты извлечения

Прежние имена 11 инструментов совместимы. `ontology_list_workspaces` отмечает большие родительские пространства как `mode: "large"`. Используйте реальные схемы доступных инструментов.

| Инструмент | Обязательные параметры | Закрепление и область |
| --- | --- | --- |
| `ontology_large_modules` | `workspace_id` | Необязательный `catalog_snapshot_id`; страницы `term`, `offset`, `limit` |
| `ontology_large_search` | `workspace_id`, точные `module_roots`, `term` | `catalog_snapshot_id`, фильтры языка/типа/пути и страницы |
| `ontology_large_neighbors` | `workspace_id`, один `module_root`, `symbol` | `catalog_snapshot_id`, направление/глубина/связи/лимит; пути внутри одного модуля |
| `ontology_evidence_bundle` | Обычный `workspace_id`, 1–8 `requests` | `snapshot_id`; уникальные `id`, `operation: "search"` либо `"neighbors"` и параметры операции |
| `ontology_evidence_pack` | Обычный `workspace_id`, 1–8 `requests` | Один закреплённый `snapshot_id`, общие качество/снимок, таблицы уникальных узлов/свидетельств и продолжение |

Старый bundle разрешает один снимок в начале, выдаёт `ok`/`error` для элементов и `ok`/`partial` для всего ответа. Предел — 200 результатов и 262144 UTF-8 байта канонического structured JSON; повторный protocol-text и wire-обёртка в этот старый предел не входят. Слишком большой элемент становится безопасной ошибкой. `partial` не означает успех ошибочного элемента.

Новый `ontology_evidence_pack` сохраняет snapshot/quality один раз, а узлы и свидетельства ссылаются на content-addressed `n:`/`e:` SHA-256 ID. `node_fields` выбирает `qualifiedName`, `path`, `metadata` (по умолчанию все; `[]` минимально), сохраняя обязательную идентичность, когда она доступна. `max_results`: 1–200; `max_payload_bytes`: 16384–262144, по умолчанию 262144; `max_wire_bytes`: 16384–1048576, по умолчанию 1048576. `payloadBytes` считает канонический UTF-8; `wireBytes` включает полный JSON-RPC ответ, request-ID, дублированный совместимый текст и перевод строки.

`continuation={tool,arguments}` закрепляет снимок, исходный запрос и выбранные поля/лимиты. Search продвигает offset; neighbors использует `page_offset` 0–500 и страницы только внутри исходного traversal-limit (по умолчанию 200, максимум 500). Достижение `query_limit` остаётся явно частичным. Компактность не доказывает полноту анализа или выполнения. ID обычного снимка и каталога различны; не смешивайте их и не выдумывайте межмодульные пути.

См. [процесс и проверки 0.9.0](v090-workflow.md).
