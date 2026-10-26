"""Bounded, source-free HTML export of a verified pipeline snapshot.

The temporary disk index resolves exact evidence links without retaining the
catalog in memory. All five language trees are static: navigation needs neither
an HTTP server nor fetch. Search intentionally covers only the current page.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import privacy_guard

LANGUAGES = ("ko", "en", "ja", "zh-CN", "ru")
LANGUAGE_NAMES = ("한국어", "English", "日本語", "简体中文", "Русский")
PAGE_SIZE = 50
GRAPH_NODES = 60
GRAPH_ASSERTIONS = 160
MAX_RECORD_BYTES = 512 * 1024
MAX_RECORD_DEPTH = 48
MAX_PAGE_BYTES = 32 * 1024 * 1024
DEFAULT_OUTPUT_BYTES = 1024 * 1024 * 1024
KINDS = ("symbol", "assertion", "framework", "policy_rule", "callsite", "semantic_fragment", "other")
ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Rows preserve key parity while keeping source identifiers and numeric values
# outside the translation layer.
_ROWS = {
    "title": ("온톨로지 데이터 파이프라인", "Ontology data pipeline", "オントロジーデータパイプライン", "本体数据流水线", "Конвейер данных онтологии"),
    "catalog": ("카탈로그", "Catalog", "カタログ", "目录", "Каталог"),
    "modules": ("모듈", "Modules", "モジュール", "模块", "Модули"),
    "symbol": ("코드 개체", "Code entities", "コード実体", "代码实体", "Сущности кода"),
    "assertion": ("주장과 근거", "Assertions and evidence", "主張と根拠", "断言与证据", "Утверждения и основания"),
    "framework": ("프레임워크 선언", "Framework declarations", "フレームワーク宣言", "框架声明", "Объявления фреймворков"),
    "callsite": ("호출 해석 상태", "Call resolution", "呼び出し解決", "调用解析", "Разрешение вызовов"),
    "semantic_fragment": ("정책 조건·계산식", "Policy expression fragments", "条件・計算式", "条件与计算表达式", "Условия и выражения"),
    "policy_rule": ("정책 규칙", "Policy rules", "ポリシールール", "策略规则", "Правила политик"),
    "other": ("기타 기록", "Other records", "その他の記録", "其他记录", "Прочие записи"),
    "records": ("기록", "Records", "記録", "记录", "Записи"),
    "snapshot": ("고정 스냅샷", "Pinned snapshot", "固定スナップショット", "固定快照", "Зафиксированный снимок"),
    "analysis": ("분석 명세", "Analysis specification", "解析仕様", "分析规范", "Спецификация анализа"),
    "created": ("스냅샷 생성 시각", "Snapshot created", "スナップショット作成時刻", "快照创建时间", "Время создания снимка"),
    "verified": ("소스 마지막 확인 시각", "Source last verified", "ソースの最終確認時刻", "源代码最后验证时间", "Последняя проверка исходного кода"),
    "coverage": ("분석 범위와 한계", "Coverage and limitations", "解析範囲と制限", "分析覆盖范围与限制", "Охват и ограничения"),
    "offline": ("저장된 정적 분석 결과입니다. 현재 소스와 실행 상태는 실시간 확인하지 않습니다.", "Saved static analysis. Current source and runtime state are not checked live.", "保存された静的解析です。現在のソースや実行状態はリアルタイムでは確認しません。", "这是已保存的静态分析。不会实时检查当前源代码和运行状态。", "Сохранённый статический анализ. Текущее состояние исходного кода и выполнения не проверяется в реальном времени."),
    "scope": ("모든 기록은 페이지를 통해 열 수 있습니다. 검색과 3D 지도는 현재 페이지 범위이며 미표시 관계는 다른 기록 페이지에서 확인합니다.", "Every record is reachable through pages. Search and 3D maps cover the current page; inspect other record pages for relations outside it.", "すべての記録にページからアクセスできます。検索と3D地図は現在のページが対象です。範囲外の関係は他の記録ページで確認してください。", "所有记录都可通过分页访问。搜索和3D图仅覆盖当前页；其他关系请在对应记录页查看。", "Все записи доступны через страницы. Поиск и 3D-карта охватывают текущую страницу; связи за её пределами доступны на других страницах записей."),
    "search": ("이 페이지에서 찾기", "Find on this page", "このページを検索", "在此页查找", "Найти на этой странице"),
    "search_hint": ("검색어는 이 화면 메모리에만 남습니다. Escape로 지울 수 있습니다.", "The query stays in this page's memory. Press Escape to clear it.", "検索語はこのページのメモリにのみ保持されます。Escapeで消去できます。", "搜索词仅保留在此页面的内存中。按Escape清除。", "Запрос остаётся только в памяти страницы. Нажмите Escape, чтобы очистить его."),
    "empty": ("이 범위에 기록이 없습니다.", "No records in this scope.", "この範囲に記録はありません。", "此范围内没有记录。", "В этой области нет записей."),
    "no_match": ("이 페이지에 일치하는 기록이 없습니다.", "No matching records on this page.", "このページに一致する記録はありません。", "此页没有匹配的记录。", "На этой странице нет совпадений."),
    "previous": ("이전 페이지", "Previous page", "前のページ", "上一页", "Предыдущая страница"),
    "next": ("다음 페이지", "Next page", "次のページ", "下一页", "Следующая страница"),
    "page": ("페이지", "Page", "ページ", "页", "Страница"),
    "total": ("전체", "Total", "合計", "总计", "Всего"),
    "name": ("이름", "Name", "名前", "名称", "Название"),
    "source": ("소스 위치", "Source location", "ソース位置", "源代码位置", "Расположение в исходном коде"),
    "basis": ("근거 유형", "Evidence basis", "根拠の種別", "证据类型", "Тип основания"),
    "status": ("검증 상태", "Verification status", "検証状態", "验证状态", "Статус проверки"),
    "evidence": ("정확한 근거 기록", "Exact evidence records", "正確な根拠記録", "精确证据记录", "Точные записи оснований"),
    "missing": ("이 스냅샷에 해당 근거 기록이 없습니다. UNKNOWN", "Evidence record is absent from this snapshot. UNKNOWN", "このスナップショットに対応する根拠記録はありません。UNKNOWN", "此快照缺少对应证据记录。UNKNOWN", "Запись основания отсутствует в этом снимке. UNKNOWN"),
    "raw": ("저장된 기록 전체", "Complete stored record", "保存された記録全体", "完整已存储记录", "Полная сохранённая запись"),
    "decision": ("저장된 정책 의사결정표", "Stored policy decision table", "保存されたポリシー決定表", "已存储策略决策表", "Таблица решений сохранённой политики"),
    "condition": ("조건", "Condition", "条件", "条件", "Условие"),
    "result": ("반환 식", "Return expression", "戻り値の式", "返回表达式", "Выражение результата"),
    "always": ("항상", "Always", "常に", "始终", "Всегда"),
    "not": ("아님", "NOT", "否定", "非", "НЕ"),
    "policy_note": ("소스에서 추출한 식을 보여줍니다. 업무 승인이나 최대 혜택 계산 결과가 아닙니다. 미확인 조건은 UNKNOWN으로 유지합니다.", "Expressions extracted from source. This is neither business approval nor a maximum-benefit calculation. Unresolved conditions remain UNKNOWN.", "ソースから抽出した式を表示します。業務上の承認や最大便益の計算結果ではありません。未解決の条件はUNKNOWNのままです。", "展示从源代码提取的表达式，不代表业务批准或最大优惠计算结果。未解析条件保留为UNKNOWN。", "Показаны выражения, извлечённые из исходного кода. Это не бизнес-одобрение и не расчёт максимальной выгоды. Неопределённые условия остаются UNKNOWN."),
    "parameters": ("필요한 입력과 유한 값", "Required inputs and finite values", "必要な入力と有限値", "所需输入与有限取值", "Необходимые входные данные и конечные значения"),
    "authority": ("규칙 출처와 권한", "Rule origin and authority", "ルールの出典と権限", "规则来源与权限", "Происхождение и полномочия правила"),
    "boundary": ("유효기간·설정·중복·우선순위 경계", "Validity, configuration, stacking and precedence", "有効期間・設定・併用・優先順位", "有效期、配置、叠加和优先级", "Срок действия, конфигурация, сочетание и приоритет"),
    "domain_note": ("도메인 표시는 식별자에 근거한 후보이며 업무 분류 승인이 아닙니다.", "Domains are identifier-based candidates, not approved business classifications.", "ドメインは識別子に基づく候補であり、承認済みの業務分類ではありません。", "领域标签是基于标识符的候选分类，并非已批准的业务分类。", "Домены — кандидаты на основе идентификаторов, а не утверждённая бизнес-классификация."),
    "map": ("이 페이지의 3D 지도", "3D map of this page", "このページの3D地図", "此页的3D图", "3D-карта этой страницы"),
    "overview": ("3D 코드 탐색", "Explore code in 3D", "3Dコード探索", "3D代码探索", "Исследовать код в 3D"),
    "all_records": ("전체 기록", "All records", "すべての記録", "全部记录", "Все записи"),
    "map_details": ("지도 범위·근거", "Map scope and evidence", "地図の範囲・根拠", "图的范围与证据", "Область и основания карты"),
    "close": ("닫기", "Close", "閉じる", "关闭", "Закрыть"),
    "overview_page": ("지도 {page}/{pages}", "Map {page}/{pages}", "地図 {page}/{pages}", "图 {page}/{pages}", "Карта {page}/{pages}"),
    "overview_summary": ("이 페이지: 심볼 {nodes}/{symbols} · 관계 {edges} · 전체 기록 {records}", "This page: symbols {nodes}/{symbols} · relations {edges} · total records {records}", "このページ: シンボル {nodes}/{symbols}・関係 {edges}・全記録 {records}", "此页：符号 {nodes}/{symbols} · 关系 {edges} · 全部记录 {records}", "Эта страница: символы {nodes}/{symbols} · связи {edges} · всего записей {records}"),
    "overview_boundary": ("전체 스냅샷을 여러 지도로 나눴습니다. 이전·다음은 다른 페이지를 엽니다. 확대·전체 모드와 검색은 지금 불러온 페이지만 탐색합니다. 같은 심볼이 여러 페이지에 나타날 수 있습니다.", "The snapshot is split into maps. Previous/next opens another page. Focus/full mode and search explore only the loaded page. A symbol may appear on several pages.", "スナップショットを複数の地図に分割しています。前後の操作で別ページを開きます。フォーカス・全体モードと検索は読み込んだページのみが対象です。同じシンボルが複数ページに現れる場合があります。", "快照分为多页图。上一页/下一页打开其他页面。聚焦、全图模式与搜索仅覆盖已加载的页面；同一符号可能出现在多页。", "Снимок разделён на карты. Кнопки назад/вперёд открывают другие страницы. Фокус, полный режим и поиск охватывают только загруженную страницу. Символ может встречаться на нескольких страницах."),
    "overview_coverage": ("지도에 연결된 저장 주장 {eligible}개 · 지도에서 연결할 수 없는 주장 {excluded}개는 전체 기록에서 확인하세요. 관계가 없는 심볼도 별도 페이지로 유지합니다. 관계를 추정해 추가하지 않습니다.", "Mapped stored assertions: {eligible}. Assertions not connectable in the map: {excluded}; inspect All records. Symbols without relations also have pages. No inferred relations are added.", "地図に接続した保存済み主張: {eligible}件。地図で接続できない主張: {excluded}件は「すべての記録」で確認できます。関係のないシンボルも別ページに保持し、推測の関係は追加しません。", "已映射的存储断言：{eligible}条。无法在图中连接的断言：{excluded}条，请查看全部记录。无关系符号也保留在单独页面中，不添加推测关系。", "Сохранённых утверждений на картах: {eligible}. Утверждений без соединяемых концов: {excluded}; см. все записи. Символы без связей также имеют страницы. Предполагаемые связи не добавляются."),
    "context_map": ("이 기록이 포함된 3D 지도", "3D map containing these records", "この記録を含む3D地図", "包含这些记录的3D图", "3D-карта с этими записями"),
    "map_scope": ("제한된 페이지 지도 · 노드 최대 60개 · 관계 최대 160개 · 관계는 저장된 주장만 표시", "Bounded page map · up to 60 nodes · up to 160 relations · only stored assertions form relations", "限定されたページ地図・ノード最大60・関係最大160・保存された主張のみを関係として表示", "受限页面图 · 最多60个节点 · 最多160条关系 · 仅以已存储断言表示关系", "Ограниченная карта страницы · до 60 узлов · до 160 связей · связи только из сохранённых утверждений"),
    "back": ("기록 목록으로 돌아가기", "Return to record list", "記録一覧へ戻る", "返回记录列表", "Вернуться к списку записей"),
    "skip": ("본문으로 바로가기", "Skip to content", "本文へ移動", "跳到正文", "Перейти к содержимому"),
    "language": ("화면 언어", "Interface language", "表示言語", "界面语言", "Язык интерфейса"),
    "unknown": ("미확인 · UNKNOWN", "Unverified · UNKNOWN", "未確認 · UNKNOWN", "未验证 · UNKNOWN", "Не проверено · UNKNOWN"),
    "local": ("오프라인 HTML · 외부 연결 없음 · 개발자 배틀돌", "Offline HTML · no external connections · developer battle-doll", "オフラインHTML・外部接続なし・開発者 battle-doll", "离线HTML · 无外部连接 · 开发者 battle-doll", "Автономный HTML · без внешних соединений · разработчик battle-doll"),
    "export_access": ("내보내기 권한으로 만든 정적 사본입니다. 이후 워크스페이스 권한을 변경해도 이미 복사한 파일의 접근권한은 회수되지 않습니다.", "A static copy created under export permission. Later workspace permission changes cannot revoke access to copies already made.", "エクスポート権限に基づく静的コピーです。後でワークスペースの権限を変更しても、既存のコピーへのアクセスは取り消せません。", "这是依据导出权限生成的静态副本。之后更改工作区权限无法撤销已复制文件的访问权。", "Статическая копия, созданная по разрешению на экспорт. Последующее изменение прав рабочей области не отзывает доступ к уже созданным копиям."),
}
TRANSLATIONS = {language: {key: row[index] for key, row in _ROWS.items()} for index, language in enumerate(LANGUAGES)}


class PipelineHtmlError(ValueError):
    """Safe, non-source-bearing export error."""


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _anchor(record_id: str) -> str:
    return "r-" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()


def _module_name(module: str) -> str:
    return "module-" + hashlib.sha256(module.encode("utf-8")).hexdigest()


def _page_name(kind: str, number: int) -> str:
    return f"{kind}-{number:06d}.html"


def _validate_shape(value: Any, depth: int = 0) -> None:
    if depth > MAX_RECORD_DEPTH:
        raise PipelineHtmlError("html_record_depth_exceeded")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PipelineHtmlError("html_record_key_invalid")
            if key in {"path", "relativePath", "relative_path", "modulePath"} and isinstance(child, str) and child:
                if child.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", child) or ".." in child.replace("\\", "/").split("/"):
                    raise PipelineHtmlError("html_source_path_not_relative")
            _validate_shape(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_shape(child, depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise PipelineHtmlError("html_record_value_invalid")


def pretty_expression(value: Any, depth: int = 0) -> str:
    """Print typed IR, never evaluate it or treat source text as markup."""
    if depth > MAX_RECORD_DEPTH:
        raise PipelineHtmlError("html_expression_depth_exceeded")
    if not isinstance(value, dict):
        return _json(value)
    op = value.get("op")
    if op == "literal":
        return f"{_json(value.get('value'))} : {value.get('type', 'UNKNOWN')}"
    if op == "input":
        return str(value.get("name", "UNKNOWN"))
    if op in {"not", "neg", "pos"}:
        symbol = {"not": "NOT", "neg": "−", "pos": "+"}[op]
        return f"{symbol} ({pretty_expression(value.get('arg'), depth + 1)})"
    symbols = {"add": "+", "sub": "−", "mul": "×", "div": "÷", "floordiv": "//", "mod": "%", "and": "AND", "or": "OR"}
    if op in symbols:
        args = value.get("args")
        if args is None:
            args = [value.get("left"), value.get("right")]
        if isinstance(args, list):
            return "(" + f" {symbols[op]} ".join(pretty_expression(arg, depth + 1) for arg in args) + ")"
    if op == "compare":
        operator = {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}.get(value.get("operator"), value.get("operator", "UNKNOWN"))
        return f"({pretty_expression(value.get('left'), depth + 1)} {operator} {pretty_expression(value.get('right'), depth + 1)})"
    # Unknown/new IR is preserved verbatim, not assigned invented semantics.
    return _json(value)


def _decision_rows(program: Any, labels: dict[str, str], conditions: tuple[str, ...] = (), depth: int = 0) -> list[tuple[str, str]]:
    if depth > MAX_RECORD_DEPTH:
        raise PipelineHtmlError("html_program_depth_exceeded")
    if not isinstance(program, dict):
        return [(" AND ".join(conditions) or labels["always"], "UNKNOWN")]
    if program.get("op") == "return":
        return [(" AND ".join(conditions) or labels["always"], pretty_expression(program.get("value")))]
    if program.get("op") == "if":
        condition = pretty_expression(program.get("condition"))
        return (_decision_rows(program.get("then"), labels, (*conditions, condition), depth + 1)
                + _decision_rows(program.get("else"), labels, (*conditions, f"{labels['not']} ({condition})"), depth + 1))
    return [(" AND ".join(conditions) or labels["always"], "UNKNOWN\n" + _json(program))]


def _source(record: dict[str, Any]) -> str:
    path = record.get("path", record.get("relativePath", "UNKNOWN"))
    span = record.get("span") or {}
    start, end = span.get("lineStart", record.get("lineStart")), span.get("lineEnd", record.get("lineEnd"))
    return str(path) + (f":{start}" + (f"–{end}" if end and end != start else "") if start else "")


def _reference_ids(record: dict[str, Any]) -> list[str]:
    found = set()
    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"sourceAssertionIds", "evidenceIds", "assertionIds"} and isinstance(child, list):
                    found.update(item for item in child if isinstance(item, str))
                elif key in {"sourceAssertionId", "evidenceId", "assertionId"} and isinstance(child, str):
                    found.add(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(record)
    return sorted(found)


def _record_link(db: sqlite3.Connection, record_id: str) -> str | None:
    row = db.execute("SELECT kind, ordinal FROM records WHERE id = ?", (record_id,)).fetchone()
    return _page_name(row[0], row[1] // PAGE_SIZE + 1) + "#" + _anchor(record_id) if row else None


def _evidence_html(record: dict[str, Any], db: sqlite3.Connection, labels: dict[str, str]) -> str:
    references = _reference_ids(record)
    if not references:
        return ""
    items = []
    for record_id in references:
        link = _record_link(db, record_id)
        target = db.execute("SELECT payload FROM records WHERE id = ?", (record_id,)).fetchone() if link else None
        detail = _source(json.loads(target[0])) if target else labels["missing"]
        label = f"{record_id} · {detail}"
        items.append(f'<li><a href="{link}">{_e(label)}</a></li>' if link else f'<li>{_e(label)}</li>')
    return f'<h3>{_e(labels["evidence"])}</h3><ul class="evidence">{"".join(items)}</ul>'


def _policy_html(record: dict[str, Any], labels: dict[str, str]) -> str:
    rule = record.get("rule", record)
    rows = _decision_rows(rule.get("program"), labels)
    table = "".join(f"<tr><td><pre>{_e(condition)}</pre></td><td><pre>{_e(result)}</pre></td></tr>" for condition, result in rows)
    fields = (("parameters", rule.get("parameters", "UNKNOWN")), ("authority", rule.get("authority", "UNKNOWN")),
              ("boundary", {key: rule.get(key, "UNKNOWN") for key in ("configProfile", "validity", "combinations", "complete")}))
    details = "".join(f'<details><summary>{_e(labels[key])}</summary><pre>{_e(_json(value))}</pre></details>' for key, value in fields)
    return (f'<p class="notice">{_e(labels["policy_note"])}</p><div class="table-scroll"><table>'
            f'<caption>{_e(labels["decision"])}</caption><thead><tr><th scope="col">{_e(labels["condition"])}</th>'
            f'<th scope="col">{_e(labels["result"])}</th></tr></thead><tbody>{table}</tbody></table></div>'
            + details + (f'<p class="subtle">{_e(labels["domain_note"])}</p><pre>{_e(_json(rule["domains"]))}</pre>' if rule.get("domains") else ""))


def _record_html(record: dict[str, Any], db: sqlite3.Connection, labels: dict[str, str], *, maps: bool = False) -> str:
    rows = (("source", _source(record)), ("basis", record.get("basis", "UNKNOWN")), ("status", record.get("status", "UNKNOWN")))
    metadata = "".join(f'<dt>{_e(labels[key])}</dt><dd>{_e(value)}</dd>' for key, value in rows)
    policy = _policy_html(record, labels) if record.get("kind") == "policy_rule" else ""
    mapped = db.execute("SELECT page FROM overview_members WHERE id=?", (record["id"],)).fetchone() if maps else None
    map_link = f'<p class="actions"><a data-map-record="{_e(record["id"])}" href="{_overview_name(mapped[0])}">{_e(labels["context_map"])}</a></p>' if mapped else ''
    return (f'<article class="record" data-search-record id="{_anchor(record["id"])}"><h2>{_e(record.get("name", record["id"]))}</h2>'
            f'<p class="record-id">{_e(record["id"])}</p><dl class="metadata">{metadata}</dl>{policy}'
            + map_link + _evidence_html(record, db, labels)
            + f'<details><summary>{_e(labels["raw"])}</summary><pre>{_e(_json(record))}</pre></details></article>')


def _pagination(prefix: str, number: int, total: int, labels: dict[str, str]) -> str:
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    previous = f'<a rel="prev" href="{_page_name(prefix, number - 1)}">← {_e(labels["previous"])}</a>' if number > 1 else '<span></span>'
    following = f'<a rel="next" href="{_page_name(prefix, number + 1)}">{_e(labels["next"])} →</a>' if number < pages else '<span></span>'
    return f'<nav class="pagination" aria-label="{_e(labels["page"])}">{previous}<span>{_e(labels["page"])} {number} / {pages} · {_e(labels["total"])} {total}</span>{following}</nav>'


def _search(labels: dict[str, str]) -> str:
    return (f'<div class="search"><label for="page-search">{_e(labels["search"])}</label><input id="page-search" type="search" autocomplete="off" spellcheck="false" aria-describedby="search-hint" aria-controls="records">'
            f'<small id="search-hint" class="subtle">{_e(labels["search_hint"])}</small><output id="search-count" aria-live="polite"></output></div>'
            f'<p id="search-empty" class="empty" hidden>{_e(labels["no_match"])}</p>')


def _document(language: str, filename: str, title: str, body: str, counts: dict[str, int], metadata: dict[str, Any], *, searchable: bool = False, maps: bool = True) -> str:
    labels = TRANSLATIONS[language]
    languages = "".join(f'<a href="../{code}/{filename}" lang="{code}" hreflang="{code}"' + (' aria-current="page"' if code == language else '') + f'>{_e(name)}</a>' for code, name in zip(LANGUAGES, LANGUAGE_NAMES))
    navigation = (f'<a href="index.html">{_e(labels["overview"])}</a>' if maps else '')
    navigation += f'<a href="catalog.html">{_e(labels["catalog"])}</a><a href="modules-000001.html">{_e(labels["modules"])}</a>'
    for kind in KINDS:
        if counts[kind]:
            navigation += f'<a href="{_page_name(kind, 1)}">{_e(labels[kind])} <span>({counts[kind]})</span></a>'
    return (f'<!doctype html><html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<meta name="color-scheme" content="dark"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; connect-src \'none\'; img-src \'none\'; font-src \'none\'; style-src \'self\'; script-src \'self\'; worker-src \'none\'; frame-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">'
            f'<title>{_e(title)} · Code Ontology</title><link rel="stylesheet" href="../assets/pipeline.css"></head><body>'
            f'<a class="skip" href="#main">{_e(labels["skip"])}</a><header><div class="brand">CODE ONTOLOGY · PIPELINE</div><h1>{_e(title)}</h1>'
            f'<p class="scope">{_e(labels["offline"])}</p><nav class="languages" aria-label="{_e(labels["language"])}">{languages}</nav><nav class="navigation" aria-label="{_e(labels["catalog"])}">{navigation}</nav></header>'
            f'<main id="main"><p class="record-id">{_e(labels["snapshot"])}: {_e(metadata.get("snapshotId", "UNKNOWN"))}</p>'
            + (_search(labels) if searchable else "") + body
            + f'</main><footer><p>{_e(labels["scope"])}</p><p>{_e(labels["export_access"])}</p><p>{_e(labels["local"])}</p></footer>'
            + ('<script src="../assets/pipeline.js" defer></script>' if searchable else "") + '</body></html>')


def _write(path: Path, text: str, profile: dict[str, Any]) -> None:
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_PAGE_BYTES:
        raise PipelineHtmlError("html_page_budget_exceeded")
    privacy_guard.ensure_public_safe(text, profile=profile, allow_local_paths=False)
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        _private_handle(handle.fileno())
        handle.write(encoded)


def _private_handle(fd: int) -> None:
    privacy_guard._check_private_file_metadata(os.fstat(fd))
    if os.name == "nt":
        privacy_guard._windows_profile_security(fd)


def _private_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        _private_handle(fd)
        opened, current = os.fstat(fd), path.lstat()
        privacy_guard._check_private_file_metadata(current)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise PipelineHtmlError("html_file_identity_changed")
    finally:
        os.close(fd)


def _metadata(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: raw.get(key) for key in ("snapshotId", "analysisSpecId", "coverage", "recordCount", "createdAt", "sourceLastVerifiedAt", "policySnapshotId", "rulesetDigest")}


def _overview_name(number: int) -> str:
    return "index.html" if number == 1 else _page_name("map", number)


def _index_overview(db: sqlite3.Connection, check_cancel: Any, counts: dict[str, int]) -> dict[str, int]:
    """Partition actual relations on disk, then cover unconnected symbols.

    Each page owns at most 160 assertion records (including duplicate evidence)
    and 60 endpoint IDs. No query or in-memory list contains the full graph.
    """
    db.execute("CREATE TABLE overview_pages (number INTEGER PRIMARY KEY, ids TEXT NOT NULL)")
    db.execute("CREATE TABLE overview_members (id TEXT PRIMARY KEY, page INTEGER NOT NULL)")
    number, eligible = 0, 0
    chosen: list[str] = []
    nodes: set[str] = set()
    def flush() -> None:
        nonlocal number, chosen, nodes
        number += 1
        db.execute("INSERT INTO overview_pages VALUES (?,?)", (number, json.dumps(chosen)))
        for record_id in (*chosen, *sorted(nodes)):
            db.execute("INSERT OR IGNORE INTO overview_members VALUES (?,?)", (record_id, number))
        chosen, nodes = [], set()
    candidates = db.execute("SELECT a.id,a.source,a.target FROM graph_assertions a JOIN records s ON s.id=a.source AND s.kind='symbol' JOIN records t ON t.id=a.target AND t.kind='symbol' ORDER BY a.ordinal")
    for record_id, source, target in candidates:
        check_cancel()
        endpoints = {source, target}
        if chosen and (len(chosen) >= GRAPH_ASSERTIONS or len(nodes | endpoints) > GRAPH_NODES):
            flush()
        chosen.append(record_id)
        nodes.update(endpoints)
        eligible += 1
    if chosen:
        flush()
    # Keyset/primary-key-backed batches avoid a whole-symbol DOM or Python list.
    # This includes symbols absent from valid relations without fabricating edges.
    after_ordinal = -1
    while True:
        check_cancel()
        rows = db.execute("SELECT r.id,r.ordinal FROM records r LEFT JOIN overview_members m ON m.id=r.id WHERE r.kind='symbol' AND r.ordinal>? AND m.id IS NULL ORDER BY r.ordinal LIMIT ?", (after_ordinal, GRAPH_NODES)).fetchall()
        if not rows:
            break
        chosen = [row[0] for row in rows]
        after_ordinal = rows[-1][1]
        nodes = set(chosen)
        flush()
    if not number:
        flush()
    db.commit()
    return {"pages": number, "eligible": eligible, "excluded": counts["assertion"] - eligible}


def _graph_document(records: list[dict[str, Any]], db: sqlite3.Connection, metadata: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edge_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    evidence_count = 0
    def add(record: dict[str, Any]) -> bool:
        record_id = record["id"]
        if record_id in nodes:
            return True
        if len(nodes) >= GRAPH_NODES or record.get("kind") != "symbol":
            return False
        span = record.get("span") or {}
        nodes[record_id] = {"id": record_id, "name": record.get("name", record_id), "type": record.get("type", record.get("symbolKind", "Symbol")),
                            "path": record.get("path", ""), "language": record.get("language", "UNKNOWN"),
                            "metadata": {"line_start": span.get("lineStart"), "line_end": span.get("lineEnd")}}
        return True
    for record in records:
        add(record)
    for record in records:
        if record.get("kind") != "assertion" or evidence_count >= GRAPH_ASSERTIONS:
            continue
        source, target, relation = record.get("subject"), record.get("object"), record.get("predicate")
        if not all(isinstance(value, str) and value for value in (source, target, relation)):
            continue
        endpoints = []
        for record_id in (source, target):
            row = db.execute("SELECT payload FROM records WHERE id = ?", (record_id,)).fetchone()
            endpoints.append(json.loads(row[0]) if row else None)
        if all(endpoints) and all(endpoint.get("kind") == "symbol" for endpoint in endpoints):
            missing = {endpoint["id"] for endpoint in endpoints} - nodes.keys()
            if len(nodes) + len(missing) > GRAPH_NODES:
                continue
            for endpoint in endpoints:
                add(endpoint)
            span = record.get("span") or {}
            key = (source, relation, target)
            edge = edge_by_key.setdefault(key, {"source": source, "target": target, "type": relation, "evidence": []})
            edge["evidence"].append({"path": record.get("path", ""), "line_start": span.get("lineStart"), "line_end": span.get("lineEnd"), "basis": record.get("basis", "UNKNOWN"), "rule_id": "pipeline.stored-assertion", "assertion_id": record["id"], "evidence_id": record["id"], "runtime_status": "runtime_unknown"})
            evidence_count += 1
    return {"repository": {"name": "Code Ontology", "source_scope": "selected_roots", "source_roots": []},
            "generated_at": metadata.get("createdAt") or "", "companion": {"snapshotId": metadata.get("snapshotId"), "evidenceType": "observed"},
            "nodes": list(nodes.values()), "edges": list(edge_by_key.values()), "warnings": []}


def _map_html(document: dict[str, Any], language: str, db: sqlite3.Connection, counts: dict[str, int], metadata: dict[str, Any], overview: dict[str, int], number: int) -> str:
    import code_ontology_core as core
    labels = TRANSLATIONS[language]
    document["repository"]["name"] = labels["overview"]
    payload = core._set_ui_language(core._visualization_payload(document, GRAPH_NODES), language)
    # Preserve the pipeline basis vocabulary, exact assertion IDs and ALL bounded
    # evidence for canonical relations; the workbench deduplicates relation keys.
    payload["edges"] = document["edges"]
    payload["meta"]["pipelineScope"] = {"page": number, "pages": overview["pages"], "symbols": counts["symbol"], "records": sum(counts.values()), "mappedAssertions": overview["eligible"], "unmappedAssertions": overview["excluded"]}
    def json_data(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = core._read_visualization_asset("workbench.html")
    template = template.replace('<html lang="ko">', f'<html lang="{language}">').replace('<body>', '<body class="pipeline-workbench">')
    template = template.replace("style-src 'unsafe-inline'", "style-src 'self' 'unsafe-inline'").replace("script-src 'unsafe-inline'", "script-src 'self' 'unsafe-inline'")
    template = template.replace("<style>\n__CODE_ONTOLOGY_CSS__\n</style>", '<link rel="stylesheet" href="../assets/workbench.css"><link rel="stylesheet" href="../assets/pipeline-map.css">')
    template = template.replace("<script>\n__CODE_ONTOLOGY_APP__\n</script>", '<script src="../assets/workbench.js"></script><script src="../assets/pipeline-map.js"></script>')
    template = template.replace("__CODE_ONTOLOGY_TITLE__", _e(labels["overview"]))
    template = template.replace("__CODE_ONTOLOGY_DATA__", json_data(payload))
    values = {"page": number, "pages": overview["pages"], "nodes": len(document["nodes"]), "symbols": counts["symbol"], "edges": len(document["edges"]), "records": sum(counts.values()), **overview}
    copies = {locale: {key: translated[key].format(**values) for key in ("overview", "all_records", "map_details", "close", "overview_page", "overview_summary", "overview_boundary", "overview_coverage", "previous", "next", "evidence", "symbol", "offline", "export_access", "empty")} for locale, translated in TRANSLATIONS.items()}
    def copy(key: str) -> str:
        return _e(copies[language][key])
    def record_link(record_id: str) -> str:
        row = db.execute("SELECT payload FROM records WHERE id=?", (record_id,)).fetchone()
        record = json.loads(row[0])
        return f'<li><a data-pipeline-target="{_record_link(db, record_id)}" href="{_record_link(db, record_id)}">{_e(record.get("name", record_id))} · {_e(_source(record))}<small>{_e(record_id)}</small></a></li>'
    evidence_ids = [item["assertion_id"] for edge in document["edges"] for item in edge["evidence"]]
    records = '<h3 data-pipeline-copy="evidence">' + copy("evidence") + '</h3><ul>' + ''.join(record_link(record_id) for record_id in evidence_ids) + '</ul>'
    records += '<h3 data-pipeline-copy="symbol">' + copy("symbol") + '</h3><ul>' + ''.join(record_link(node["id"]) for node in document["nodes"]) + '</ul>'
    if not document["nodes"]:
        records += '<p data-pipeline-copy="empty">' + copy("empty") + '</p>'
    previous = (f'<a data-pipeline-target="{_overview_name(number - 1)}" href="{_overview_name(number - 1)}" rel="prev" data-pipeline-label="previous" aria-label="{copy("previous")}">←</a>' if number > 1 else '<span class="pipeline-disabled" aria-hidden="true">←</span>')
    following = (f'<a data-pipeline-target="{_overview_name(number + 1)}" href="{_overview_name(number + 1)}" rel="next" data-pipeline-label="next" aria-label="{copy("next")}">→</a>' if number < overview["pages"] else '<span class="pipeline-disabled" aria-hidden="true">→</span>')
    navigation = (f'<nav class="pipeline-navigation" aria-label="{copy("overview")}" data-pipeline-label="overview">'
                  f'<a class="pipeline-catalog" data-pipeline-target="catalog.html" href="catalog.html"><span data-pipeline-copy="all_records">{copy("all_records")}</span> <span>({sum(counts.values())})</span></a>'
                  + previous + f'<span class="pipeline-page" data-pipeline-copy="overview_page">{copy("overview_page")}</span>' + following
                  + f'<details id="pipeline-map-details"><summary id="pipeline-map-summary" data-pipeline-copy="map_details">{copy("map_details")}</summary><section class="pipeline-map-panel" aria-labelledby="pipeline-map-heading">'
                  f'<div class="pipeline-panel-heading"><h2 id="pipeline-map-heading" data-pipeline-copy="map_details">{copy("map_details")}</h2><button type="button" id="pipeline-map-close" data-pipeline-copy="close">{copy("close")}</button></div>'
                  f'<p data-pipeline-copy="overview_boundary">{copy("overview_boundary")}</p><p data-pipeline-copy="overview_coverage">{copy("overview_coverage")}</p><p data-pipeline-copy="offline">{copy("offline")}</p><p data-pipeline-copy="export_access">{copy("export_access")}</p>'
                  + records + '</section></details></nav>'
                  + f'<p class="pipeline-page-scope" data-pipeline-copy="overview_summary">{copy("overview_summary")}</p>')
    marker = '<div id="workspace-heading"'
    template = template.replace(marker, navigation + '\n    ' + marker, 1)
    template = template.replace('<script id="ontology-data"', '<script id="pipeline-map-data" type="application/json">' + json_data(copies) + '</script>\n<script id="ontology-data"', 1)
    # Native navigation remains available with JavaScript disabled.
    link = f'<a class="brand-mark" href="catalog.html" data-pipeline-target="catalog.html" data-pipeline-label="all_records" aria-label="{copy("all_records")}" title="{copy("all_records")}" style="min-height:44px;min-width:44px;text-decoration:none">←</a>'
    return template.replace('<div class="brand-mark" aria-hidden="true"><span>◈</span></div>', link)


def _safe_destination(workspace: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise PipelineHtmlError("html_destination_exists")
    if not output.parent.is_dir():
        raise PipelineHtmlError("html_destination_parent_missing")
    for parent in (output.parent, *output.parent.parents):
        if privacy_guard._link_like(parent.lstat()):
            raise PipelineHtmlError("html_destination_symlink")
    if output == workspace or workspace in output.parents:
        raise PipelineHtmlError("html_destination_inside_workspace")


def render_pipeline(workspace_path: str | Path, snapshot_id: str | None, output_dir: str | Path, language: str = "ko", *, include_maps: bool = True, max_output_bytes: int = DEFAULT_OUTPUT_BYTES, cancel: Any = None) -> dict[str, Any]:
    """Write a new private artifact tree from one verified immutable snapshot.

    Existing destinations are never overwritten. The entire new tree is staged
    with private permissions, then published only after the read session closes
    successfully. Memory is bounded by 50 records or a 60-node/160-assertion map,
    not the catalog. A map may contain fewer canonical relations when multiple
    assertions provide evidence for the same relation.
    """
    import pipeline_store
    import pipeline_acl
    import companion
    if language not in LANGUAGES:
        raise PipelineHtmlError("html_language_unsupported")
    if type(max_output_bytes) is not int or max_output_bytes < 1:
        raise PipelineHtmlError("html_output_budget_invalid")
    def check_cancel() -> None:
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
            raise PipelineHtmlError("html_export_cancelled")
    check_cancel()
    for action in ("export_html", "read_structure", "read_policy", "read_evidence"):
        pipeline_acl.authorize(workspace_path, action, snapshot_id)
    workspace = Path(workspace_path).absolute()
    output = Path(output_dir).absolute()
    _safe_destination(workspace, output)
    profile = privacy_guard.load_profile((workspace, output), required=True)
    privacy_guard.ensure_public_safe({}, profile=profile, require_profile=True)
    counts = dict.fromkeys(KINDS, 0)
    file_count = 0
    output_bytes = 0
    spool_bytes = 0
    def write(path: Path, text: str) -> None:
        nonlocal output_bytes
        check_cancel()
        size = len(text.encode("utf-8"))
        if output_bytes + size > max_output_bytes:
            raise PipelineHtmlError("html_output_budget_exceeded")
        _write(path, text, profile)
        output_bytes += size
    with tempfile.TemporaryDirectory(prefix=".pipeline-html-", dir=output.parent) as temporary:
        temporary_path = Path(temporary)
        stage = temporary_path / "artifact"
        stage.mkdir(mode=0o700)
        with closing(sqlite3.connect(temporary_path / "links.sqlite")) as db:
            os.chmod(temporary_path / "links.sqlite", 0o600)
            _private_file(temporary_path / "links.sqlite")
            # This disposable index is never recovered or published. Avoid a
            # side journal inheriting weaker permissions than the checked DB.
            db.execute("PRAGMA journal_mode = OFF")
            db.execute("PRAGMA temp_store = MEMORY")
            db.execute("PRAGMA cache_size = -2048")
            db.execute("CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, ordinal INTEGER NOT NULL, module TEXT NOT NULL, module_path TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE UNIQUE INDEX record_page ON records(kind, ordinal)")
            db.execute("CREATE INDEX module_records ON records(module, id)")
            db.execute("CREATE TABLE modules (module TEXT UNIQUE NOT NULL, label TEXT NOT NULL, amount INTEGER NOT NULL)")
            db.execute("CREATE TABLE graph_assertions (id TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL)")
            with pipeline_store.open_reader(workspace, snapshot_id) as reader:
                metadata = _metadata(reader.metadata)
                _validate_shape(metadata)
                privacy_guard.ensure_public_safe(metadata, profile=profile)
                for record in reader.iter_records(page_size=PAGE_SIZE):
                    check_cancel()
                    if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                        raise PipelineHtmlError("html_record_id_invalid")
                    _validate_shape(record)
                    privacy_guard.ensure_public_safe(record, profile=profile)
                    payload = _json(record)
                    size = len(payload.encode("utf-8"))
                    if size > MAX_RECORD_BYTES:
                        raise PipelineHtmlError("html_record_budget_exceeded")
                    spool_bytes += size
                    if spool_bytes > max_output_bytes:
                        raise PipelineHtmlError("html_spool_budget_exceeded")
                    kind = record.get("kind") if record.get("kind") in KINDS else "other"
                    module = record.get("module") or "UNKNOWN"
                    if not isinstance(module, str):
                        raise PipelineHtmlError("html_module_invalid")
                    try:
                        db.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", (record["id"], kind, counts[kind], module, str(record.get("modulePath", module)), payload))
                        db.execute("INSERT INTO modules VALUES (?,?,1) ON CONFLICT(module) DO UPDATE SET amount=amount+1", (module, str(record.get("modulePath", module))))
                        if kind == "assertion" and all(isinstance(record.get(key), str) and record[key] for key in ("subject", "object", "predicate")):
                            db.execute("INSERT INTO graph_assertions VALUES (?,?,?,?)", (record["id"], counts[kind], record["subject"], record["object"]))
                    except sqlite3.IntegrityError as exc:
                        raise PipelineHtmlError("html_duplicate_record_id") from exc
                    counts[kind] += 1
                db.commit()
                total = sum(counts.values())
                if metadata.get("recordCount") != total:
                    raise PipelineHtmlError("html_record_count_mismatch")
                module_count = db.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
                overview = _index_overview(db, check_cancel, counts) if include_maps else {"pages": 0, "eligible": 0, "excluded": counts["assertion"]}
                assets = stage / "assets"
                assets.mkdir(mode=0o700)
                for name in ("pipeline.css", "pipeline.js") + (("workbench.css", "workbench.js", "pipeline-map.css", "pipeline-map.js") if include_maps else ()):
                    write(assets / name, (ASSETS / name).read_text(encoding="utf-8"))
                    file_count += 1
                for locale in LANGUAGES:
                    directory = stage / locale
                    directory.mkdir(mode=0o700)
                    labels = TRANSLATIONS[locale]
                    cards = f'<div class="card"><div class="metric">{total}</div>{_e(labels["records"])}</div><div class="card"><div class="metric">{module_count}</div><a href="modules-000001.html">{_e(labels["modules"])}</a></div>'
                    cards += "".join(f'<div class="card"><div class="metric">{counts[kind]}</div><a href="{_page_name(kind, 1)}">{_e(labels[kind])}</a></div>' for kind in KINDS if counts[kind])
                    values = (("snapshot", metadata.get("snapshotId")), ("analysis", metadata.get("analysisSpecId")), ("created", metadata.get("createdAt")), ("verified", metadata.get("sourceLastVerifiedAt")))
                    info = "".join(f'<dt>{_e(labels[key])}</dt><dd>{_e(value or labels["unknown"])}</dd>' for key, value in values)
                    cards += f'<div class="card"><a href="coverage-000001.html">{_e(labels["coverage"])}</a></div>'
                    body = f'<div class="cards">{cards}</div><section class="panel"><dl class="metadata">{info}</dl></section><section class="panel"><h2>{_e(labels["coverage"])}</h2><pre>{_e(_json(metadata.get("coverage") or "UNKNOWN"))}</pre></section>'
                    write(directory / "catalog.html", _document(locale, "catalog.html", labels["title"], body, counts, metadata, maps=include_maps))
                    file_count += 1
                    if include_maps:
                        for number, selected in db.execute("SELECT number,ids FROM overview_pages ORDER BY number"):
                            check_cancel()
                            graph_records = [json.loads(db.execute("SELECT payload FROM records WHERE id=?", (record_id,)).fetchone()[0]) for record_id in json.loads(selected)]
                            graph = _graph_document(graph_records, db, metadata)
                            write(directory / _overview_name(number), _map_html(graph, locale, db, counts, metadata, overview, number))
                            file_count += 1
                    else:
                        write(directory / "index.html", _document(locale, "index.html", labels["title"], body, counts, metadata, maps=False))
                        file_count += 1
                    coverage_offset = 0
                    coverage_page = 1
                    while True:
                        check_cancel()
                        if "coverage.json" in reader.metadata.get("artifacts", {}):
                            scope_page = reader.coverage(coverage_offset, PAGE_SIZE)
                        else:
                            scope_page = {"entries": [], "total": 0, "nextOffset": None, "summary": "UNKNOWN: legacy snapshot has no selection inventory"}
                        filename = _page_name("coverage", coverage_page)
                        nav = _pagination("coverage", coverage_page, scope_page["total"], labels)
                        body = nav + '<section class="panel"><h2>' + _e(labels["coverage"]) + '</h2><pre>' + _e(_json(scope_page)) + '</pre></section>' + nav
                        write(directory / filename, _document(locale, filename, labels["coverage"], body, counts, metadata, maps=include_maps))
                        file_count += 1
                        if scope_page["nextOffset"] is None:
                            break
                        coverage_offset = scope_page["nextOffset"]
                        coverage_page += 1
                    for kind in KINDS:
                        for page in range(1, (counts[kind] + PAGE_SIZE - 1) // PAGE_SIZE + 1):
                            start = (page - 1) * PAGE_SIZE
                            records = [json.loads(row[0]) for row in db.execute("SELECT payload FROM records WHERE kind = ? AND ordinal >= ? AND ordinal < ? ORDER BY ordinal", (kind, start, start + PAGE_SIZE))]
                            filename = _page_name(kind, page)
                            navigation = _pagination(kind, page, counts[kind], labels)
                            body = navigation + '<div id="records">' + "".join(_record_html(record, db, labels, maps=include_maps) for record in records) + '</div>' + navigation
                            write(directory / filename, _document(locale, filename, labels[kind], body, counts, metadata, searchable=True, maps=include_maps))
                            file_count += 1
                    for page in range(1, max(1, (module_count + PAGE_SIZE - 1) // PAGE_SIZE) + 1):
                        modules = db.execute("SELECT module, label, amount FROM modules WHERE rowid > ? AND rowid <= ? ORDER BY rowid", ((page - 1) * PAGE_SIZE, page * PAGE_SIZE)).fetchall()
                        items = "".join(f'<article class="record" data-search-record><h2><a href="{_page_name(_module_name(module), 1)}">{_e(label)}</a></h2><p>{amount} {_e(labels["records"])}</p><p class="record-id">{_e(module)}</p></article>' for module, label, amount in modules)
                        filename = _page_name("modules", page)
                        nav = _pagination("modules", page, module_count, labels)
                        write(directory / filename, _document(locale, filename, labels["modules"], nav + '<div id="records">' + (items or f'<p class="empty">{_e(labels["empty"])}</p>') + '</div>' + nav, counts, metadata, searchable=True, maps=include_maps))
                        file_count += 1
                        for module, module_label, amount in modules:
                            prefix = _module_name(module)
                            after_id = ""
                            for module_page in range(1, (amount + PAGE_SIZE - 1) // PAGE_SIZE + 1):
                                rows = db.execute("SELECT id, payload FROM records WHERE module = ? AND id > ? ORDER BY id LIMIT ?", (module, after_id, PAGE_SIZE)).fetchall()
                                after_id = rows[-1][0]
                                items = "".join(f'<article class="record" data-search-record><h2><a href="{_record_link(db, record_id)}">{_e(json.loads(payload).get("name", record_id))}</a></h2><p>{_e(_source(json.loads(payload)))}</p><p class="record-id">{_e(record_id)}</p></article>' for record_id, payload in rows)
                                filename = _page_name(prefix, module_page)
                                nav = _pagination(prefix, module_page, amount, labels)
                                write(directory / filename, _document(locale, filename, module_label, nav + '<div id="records">' + items + '</div>' + nav, counts, metadata, searchable=True, maps=include_maps))
                                file_count += 1
            # Leaving the verified reader precedes any externally visible artifact.
            landing = f'<!doctype html><html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'self\'; base-uri \'none\'; form-action \'none\'"><meta http-equiv="refresh" content="0;url={language}/index.html"><title>Code Ontology</title><link rel="stylesheet" href="assets/pipeline.css"></head><body><main><div class="brand">CODE ONTOLOGY · PIPELINE</div><h1>{_e(TRANSLATIONS[language]["title"])}</h1><nav class="languages" aria-label="{_e(TRANSLATIONS[language]["language"])}">'
            landing += "".join(f'<a href="{code}/index.html" lang="{code}">{_e(name)}</a>' for code, name in [(language, LANGUAGE_NAMES[LANGUAGES.index(language)]), *((code, name) for code, name in zip(LANGUAGES, LANGUAGE_NAMES) if code != language)])
            write(stage / "index.html", landing + '</nav></main></body></html>')
            file_count += 1
        # Serialize final authorization and promotion with normal ACL updates.
        # The verified snapshot reader has already exited successfully above.
        with companion._snapshot_write_lock(workspace):
            _safe_destination(workspace, output)
            for action in ("export_html", "read_structure", "read_policy", "read_evidence"):
                pipeline_acl.authorize(workspace, action, metadata["snapshotId"])
            if privacy_guard.load_profile((workspace, output), required=True) != profile:
                raise PipelineHtmlError("html_privacy_profile_changed")
            for directory, subdirectories, files in os.walk(stage, followlinks=False):
                check_cancel()
                for name in subdirectories:
                    if privacy_guard._link_like((Path(directory) / name).lstat()):
                        raise PipelineHtmlError("html_output_directory_changed")
                for name in files:
                    _private_file(Path(directory) / name)
            check_cancel()
            os.rename(stage, output)
    return {"snapshotId": metadata["snapshotId"], "entrypoint": str(output / language / "index.html"), "outputDirectory": str(output),
            "languages": list(LANGUAGES), "recordCount": sum(counts.values()), "moduleCount": module_count, "counts": counts,
            "pageSize": PAGE_SIZE, "fileCount": file_count, "outputBytes": output_bytes, "maxOutputBytes": max_output_bytes,
            "mapPagesPerLanguage": overview["pages"], "mappedAssertions": overview["eligible"], "unmappedAssertions": overview["excluded"],
            "sourceRechecked": False, "browserVerification": "unverified"}
