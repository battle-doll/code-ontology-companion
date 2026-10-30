(function () {
  "use strict";
  const locales = ["ko", "en", "ja", "zh-CN", "ru"];
  const rows = {
    title: ["온톨로지 큰 문맥", "Ontology overview", "オントロジーの概要", "本体概览", "Обзор онтологии"],
    boundary: ["영역 → 주요 모듈 → 핵심 요약 · 최대 3단계. 개별 함수·호출·AST는 MCP에서 확인합니다.", "Area → major module → core summary, at most three levels. Individual functions, calls and ASTs remain in MCP.", "領域 → 主要モジュール → 要約、最大3階層。関数・呼出し・ASTはMCPで確認します。", "领域 → 主要模块 → 核心摘要，最多三级。单个函数、调用和AST保留在MCP中。", "Область → основной модуль → краткое содержание, до трёх уровней. Функции, вызовы и AST остаются в MCP."],
    full: ["전체 범위 요약", "Full-scope summary", "全範囲の要約", "全范围摘要", "Обзор всей области"],
    reset: ["3D 초기 위치", "Reset 3D", "3Dをリセット", "重置3D", "Сбросить 3D"],
    motion: ["동작 줄이기/켜기", "Reduce/enable motion", "動きを減らす/有効", "减少/启用动画", "Уменьшить/включить анимацию"],
    search: ["현재 요약 페이지 검색", "Search current summary page", "現在の要約ページを検索", "搜索当前摘要页", "Поиск на текущей странице"],
    gesture: ["끌어 회전 · 휠로 확대 · 요약을 선택해 진입. 목록에서도 같은 항목을 볼 수 있습니다.", "Drag to rotate · wheel to zoom · select a summary to enter. The list contains the same items.", "ドラッグで回転・ホイールで拡大・要約を選んで移動。一覧にも同じ項目があります。", "拖动旋转 · 滚轮缩放 · 选择摘要进入。列表包含相同项目。", "Перетаскивайте для поворота, колесо — масштаб, выбор — переход. Список содержит те же элементы."],
    evidence: ["스냅샷 근거와 한계", "Snapshot evidence and limits", "スナップショットの根拠と制限", "快照依据与限制", "Свидетельства снимка и ограничения"],
    ready: ["정적 요약 · 실행 미관측 · 전체 의미 UNKNOWN/PARTIAL", "Static summary · runtime not observed · overall meaning UNKNOWN/PARTIAL", "静的要約・実行未観測・全体の意味 UNKNOWN/PARTIAL", "静态摘要 · 未观测运行 · 整体含义UNKNOWN/PARTIAL", "Статический обзор · выполнение не наблюдалось · смысл UNKNOWN/PARTIAL"],
    unavailable: ["요약 데이터 없음/불일치 · UNAVAILABLE. 원 온톨로지 상태를 0으로 추정하지 않습니다.", "Summary missing/mismatched · UNAVAILABLE. The original ontology is not assumed empty.", "要約なし・不一致 UNAVAILABLE。元のオントロジーを空とは推定しません。", "摘要缺失或不匹配 · UNAVAILABLE。不假定原本体为空。", "Обзор отсутствует/не совпадает · UNAVAILABLE. Исходная онтология не считается пустой."],
    original: ["원 선택 기록", "Original selected records", "元の選択記録", "原始选定记录", "Исходные выбранные записи"],
    shown: ["표시 요약 모듈 그룹", "Summary module groups shown", "表示中の要約モジュール群", "显示的摘要模块组", "Показанные группы модулей"],
    hidden: ["현재 화면 밖 그룹", "Groups outside this page", "ページ外のグループ", "当前页外的组", "Группы вне страницы"],
    privacy: ["privacy 보호 수", "Privacy-withheld count", "保護された件数", "隐私保护数量", "Число скрытых по приватности"],
    independent: ["요약 생략과 온톨로지 누락은 별개입니다.", "Summary selection is separate from ontology omissions.", "要約の選択とオントロジーの欠落は別です。", "摘要选择与本体遗漏是分开的。", "Выбор обзора отделён от пропусков онтологии."],
    records: ["기록", "records", "記録", "记录", "записей"],
    focus: ["선택 영역 확대", "Focus selected scope", "選択範囲へ", "聚焦所选范围", "Открыть выбранную область"],
    previous: ["이전 요약 페이지", "Previous summary page", "前の要約ページ", "上一摘要页", "Предыдущая страница"],
    next: ["다음 요약 페이지", "Next summary page", "次の要約ページ", "下一摘要页", "Следующая страница"],
    back: ["상위 범위", "Parent scope", "上位範囲", "上级范围", "Родительская область"],
    cards: ["정책 카드 표시/전체", "Policy cards shown/total", "表示/全ポリシーカード", "已显示/全部策略卡", "Карточки политик: показано/всего"],
    complex: ["복잡한 의미·원 근거는 MCP에서 확인", "Complex meaning and original evidence remain in MCP", "複雑な意味と元の根拠はMCPで確認", "复杂含义与原始依据保留在MCP", "Сложный смысл и исходные свидетельства остаются в MCP"],
    noMatch: ["현재 페이지에 일치 없음", "No match on this page", "このページに一致なし", "当前页无匹配", "На этой странице совпадений нет"],
    policy: ["정책 근거 · 의미 미확인", "Policy evidence · meaning UNKNOWN", "ポリシー根拠・意味未確認", "策略依据 · 含义UNKNOWN", "Основание политики · смысл UNKNOWN"],
    depth: ["단계", "Level", "階層", "层级", "Уровень"],
    flows: ["저장 관계 수 / 요약 평가 미확인", "Stored relations / summary assessment unavailable", "保存関係数 / 要約評価不明", "已存关系数 / 摘要评估未知", "Сохранённые связи / оценка обзора недоступна"],
    structural: ["저장된 소스 디렉터리로 묶은 구조 요약 · 업무 분류 UNKNOWN", "Structural grouping by stored source directory · business classification UNKNOWN", "保存されたソースディレクトリの構造要約・業務分類 UNKNOWN", "按已存源目录分组的结构摘要 · 业务分类UNKNOWN", "Структурная группировка по сохранённому каталогу · бизнес-классификация UNKNOWN"],
    otherAreas: ["그 밖의 영역 · 선택하여 확인", "Other areas · select to inspect", "その他の領域・選択して確認", "其他领域 · 选择查看", "Другие области · выберите для просмотра"],
    files: ["원 파일 outcome 분모", "Original file-outcome denominator", "元のファイル結果の分母", "原文件结果分母", "Исходный знаменатель результатов файлов"],
    nodes: ["현재 화면 요약 노드", "Summary nodes on this screen", "画面内の要約ノード", "当前屏幕摘要节点", "Узлы обзора на этом экране"],
    locators: ["현재 근거 참조", "Current evidence locators", "現在の根拠参照", "当前依据引用", "Текущие ссылки на свидетельства"],
    otherGroups: ["그 밖의 구조 그룹 · 전체 그룹 수 UNKNOWN", "Other structural groups · total groups UNKNOWN", "その他の構造グループ・総数 UNKNOWN", "其他结构组 · 总组数UNKNOWN", "Другие структурные группы · общее число UNKNOWN"],
    remainder: ["그 밖의 그룹에 포함된 기록", "Records represented by other groups", "その他のグループに含まれる記録", "其他组所代表的记录", "Записи, представленные другими группами"]
  };
  const i = Math.max(0, locales.indexOf(document.documentElement.lang));
  const dictionary = {};
  Object.keys(rows).forEach(function (key) { dictionary[key] = rows[key][i]; });
  Object.freeze(dictionary);
  globalThis.CODE_ONTOLOGY_HUMAN_I18N = dictionary;
}());
