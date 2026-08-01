(function () {
  "use strict";

  const HARD_MAX_VISIBLE_NODES = 250;
  const MAX_SEARCH_RESULTS = 80;
  const MAX_DETAIL_NEIGHBORS = 18;
  const STRUCTURAL_TYPES = new Set([
    "Package",
    "Module",
    "Class",
    "Interface",
    "Enum",
    "Record",
    "ExternalType",
    "ExternalModule",
  ]);
  const SPRING_GROUPS = new Set([
    "SpringBean",
    "DependencyInjection",
    "AspectOrAdvice",
    "ProxyOrInterceptor",
  ]);

  const TYPE_LABELS = {
    Package: "Java 패키지",
    Module: "Python 모듈",
    Class: "클래스",
    Interface: "인터페이스",
    Enum: "열거형",
    Record: "레코드",
    Function: "함수",
    AsyncFunction: "비동기 함수",
    Method: "메서드",
    AsyncMethod: "비동기 메서드",
    FrameworkAnnotation: "프레임워크 애너테이션",
    Decorator: "데코레이터",
    ExternalType: "외부 타입",
    ExternalModule: "외부 모듈",
    ExternalCallable: "외부 호출 대상",
    FrameworkConcept: "프레임워크 개념",
    PipelineRole: "파이프라인 역할",
    PolicyLeaf: "정책 값",
    RuntimeBranch: "런타임 분기",
  };

  const RELATION_LABELS = {
    DECLARES: "선언함",
    IMPORTS: "가져옴",
    EXTENDS: "상속함",
    IMPLEMENTS: "구현함",
    ANNOTATED_BY: "애너테이션 적용",
    DECORATED_BY: "데코레이터 적용",
    INJECTS: "의존성 주입",
    DECLARES_BEAN: "Bean 선언",
    MANAGED_AS: "프레임워크가 관리",
    MAY_BE_PROXIED_BY: "프록시 적용 가능",
    CALLS: "호출함",
    HAS_PIPELINE_ROLE: "파이프라인 역할",
    READS_POLICY_LEAF: "정책 값을 읽음",
    DECLARES_RUNTIME_BRANCH: "조건 분기 선언",
    GUARDS_RUNTIME_BRANCH: "분기를 제어함",
  };

  const RELATION_SETS = {
    explore: null,
    architecture: new Set(["DECLARES", "IMPORTS", "EXTENDS", "IMPLEMENTS"]),
    spring: new Set([
      "ANNOTATED_BY",
      "INJECTS",
      "DECLARES_BEAN",
      "MANAGED_AS",
      "MAY_BE_PROXIED_BY",
    ]),
    policy: new Set([
      "READS_POLICY_LEAF",
      "DECLARES_RUNTIME_BRANCH",
      "GUARDS_RUNTIME_BRANCH",
    ]),
    pipeline: new Set(["DECORATED_BY", "CALLS", "HAS_PIPELINE_ROLE"]),
  };

  const LENS_COPY = {
    overview: {
      eyebrow: "스냅샷 개요",
      title: "코드 구조를 질문 중심으로 보세요",
      description: "전체 그래프를 한꺼번에 그리지 않고, 필요한 관계만 점진적으로 펼칩니다.",
    },
    explore: {
      eyebrow: "심볼 탐색",
      title: "한 심볼에서 주변 관계를 따라가세요",
      description: "검색한 심볼을 중심으로 선언, 호출, 정책, 프레임워크 관계를 함께 봅니다.",
    },
    architecture: {
      eyebrow: "아키텍처",
      title: "패키지와 타입의 구조를 읽으세요",
      description: "선언, import, 상속, 구현 관계에 집중한 정적 구조입니다.",
    },
    spring: {
      eyebrow: "Spring 연결",
      title: "주입과 관리 경계를 확인하세요",
      description: "Spring 의미가 확인된 애너테이션, 의존성 주입, Bean, 프록시 관계만 표시합니다.",
    },
    policy: {
      eyebrow: "정책 흐름",
      title: "정책 값이 어떤 분기를 지키는지 보세요",
      description: "정책을 읽는 메서드와 그 값이 제어하는 조건 분기를 연결합니다.",
    },
    pipeline: {
      eyebrow: "파이프라인",
      title: "처리 단계와 호출 흐름을 따라가세요",
      description: "파이프라인 역할, 데코레이터, 함수 호출 관계에 집중합니다.",
    },
    changes: {
      eyebrow: "스냅샷 비교",
      title: "이전 스냅샷과 달라진 구조를 확인하세요",
      description: "추가·삭제된 노드와 관계를 보여주는 정적 구조 비교입니다.",
    },
  };

  const TYPE_PRIORITY = {
    Package: 0,
    Module: 1,
    Class: 2,
    Interface: 3,
    PolicyLeaf: 4,
    PipelineRole: 5,
    FrameworkConcept: 6,
    Method: 7,
    Function: 8,
    RuntimeBranch: 9,
  };

  const NODE_COLORS = {
    Java: "#f2aa55",
    Python: "#69b8ff",
    Framework: "#b69cff",
    Concept: "#55d6a2",
    Policy: "#f8c15c",
  };

  const TYPE_SHAPES = {
    Package: "round-rectangle",
    Module: "round-rectangle",
    Interface: "round-rectangle",
    PolicyLeaf: "hexagon",
    RuntimeBranch: "diamond",
    FrameworkAnnotation: "ellipse",
    Decorator: "ellipse",
    PipelineRole: "tag",
  };

  const dom = {
    repositoryName: document.getElementById("repository-name"),
    snapshotBadge: document.getElementById("snapshot-badge"),
    evidenceBadge: document.getElementById("evidence-badge"),
    warningBadge: document.getElementById("warning-badge"),
    globalSearch: document.getElementById("global-search"),
    searchInput: document.getElementById("search-input"),
    languageFilter: document.getElementById("language-filter"),
    typeFilter: document.getElementById("type-filter"),
    searchResults: document.getElementById("search-results"),
    searchCount: document.getElementById("search-count"),
    lensNav: document.getElementById("lens-nav"),
    viewEyebrow: document.getElementById("view-eyebrow"),
    viewTitle: document.getElementById("view-title"),
    viewDescription: document.getElementById("view-description"),
    graphToolbar: document.getElementById("graph-toolbar"),
    overviewView: document.getElementById("overview-view"),
    graphView: document.getElementById("graph-view"),
    changesView: document.getElementById("changes-view"),
    graph: document.getElementById("graph"),
    graphEmpty: document.getElementById("graph-empty"),
    graphNote: document.getElementById("graph-note"),
    depthSelect: document.getElementById("depth-select"),
    directionSelect: document.getElementById("direction-select"),
    zoomOut: document.getElementById("zoom-out"),
    zoomIn: document.getElementById("zoom-in"),
    fitGraph: document.getElementById("fit-graph"),
    resetView: document.getElementById("reset-view"),
    metricCards: document.getElementById("metric-cards"),
    nodeTypeBars: document.getElementById("node-type-bars"),
    edgeTypeBars: document.getElementById("edge-type-bars"),
    packageCount: document.getElementById("package-count"),
    packageList: document.getElementById("package-list"),
    guidedActions: document.getElementById("guided-actions"),
    detailsContent: document.getElementById("details-content"),
    liveStatus: document.getElementById("live-status"),
  };

  function text(value, fallback) {
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return fallback || "";
  }

  function finiteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function objectOrEmpty(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function arrayOrEmpty(value) {
    return Array.isArray(value) ? value : [];
  }

  function make(tagName, className, content) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (content !== undefined && content !== null) element.textContent = text(content);
    return element;
  }

  function append(parent) {
    for (let index = 1; index < arguments.length; index += 1) {
      const child = arguments[index];
      if (child) parent.appendChild(child);
    }
    return parent;
  }

  function setHidden(element, hidden) {
    element.hidden = hidden;
    element.style.display = hidden ? "none" : "";
  }

  function formatCount(value) {
    return new Intl.NumberFormat("ko-KR").format(Math.max(0, finiteNumber(value, 0)));
  }

  function formatDate(value) {
    if (!value) return "생성 시각 없음";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return text(value);
    return new Intl.DateTimeFormat("ko-KR", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(parsed);
  }

  function announce(message) {
    dom.liveStatus.textContent = "";
    window.setTimeout(function () {
      dom.liveStatus.textContent = message;
    }, 20);
  }

  function ownValue(mapping, key, fallback) {
    return Object.prototype.hasOwnProperty.call(mapping, key) ? mapping[key] : fallback;
  }

  function typeLabel(type) {
    return ownValue(TYPE_LABELS, type, type || "알 수 없는 유형");
  }

  function relationLabel(type) {
    return ownValue(RELATION_LABELS, type, type || "알 수 없는 관계");
  }

  function typePriority(type) {
    return finiteNumber(ownValue(TYPE_PRIORITY, type, 50), 50);
  }

  function shortLabel(value, maximum) {
    const source = text(value);
    const limit = maximum || 34;
    return source.length > limit ? source.slice(0, Math.max(1, limit - 1)) + "…" : source;
  }

  let payload;
  try {
    payload = JSON.parse(document.getElementById("ontology-data").textContent);
  } catch (error) {
    payload = {};
    dom.viewTitle.textContent = "온톨로지 데이터를 읽을 수 없습니다";
    dom.viewDescription.textContent = "내장 JSON이 올바른지 새 스냅샷을 생성해 확인해 주세요.";
    dom.detailsContent.replaceChildren(
      append(
        make("div", "details-placeholder"),
        make("strong", "", "데이터 파싱 실패"),
        make("p", "", error instanceof Error ? error.message : "알 수 없는 오류")
      )
    );
  }

  const meta = objectOrEmpty(payload.meta);
  const statistics = objectOrEmpty(payload.statistics);
  const changes = objectOrEmpty(payload.changes);
  const limits = objectOrEmpty(payload.limits);
  const warnings = arrayOrEmpty(payload.warnings).filter(function (item) {
    return item && typeof item === "object";
  });
  const maxVisibleNodes = Math.max(
    1,
    Math.min(HARD_MAX_VISIBLE_NODES, finiteNumber(limits.maxVisibleNodes, 200))
  );

  const nodes = [];
  const nodeById = new Map();
  arrayOrEmpty(payload.nodes).forEach(function (item) {
    if (!item || typeof item !== "object" || typeof item.id !== "string" || !item.id) return;
    if (nodeById.has(item.id)) return;
    const node = {
      id: item.id,
      type: text(item.type, "Unknown"),
      name: text(item.name, item.id),
      language: text(item.language, "Unknown"),
      path: text(item.path),
      qualified_name: text(item.qualified_name || item.qualifiedName),
      metadata: objectOrEmpty(item.metadata),
    };
    nodes.push(node);
    nodeById.set(node.id, node);
  });

  const edges = [];
  const edgeKeys = new Set();
  arrayOrEmpty(payload.edges).forEach(function (item) {
    if (!item || typeof item !== "object") return;
    const source = text(item.source);
    const target = text(item.target);
    const type = text(item.type);
    if (!source || !target || !type || source === target) return;
    if (!nodeById.has(source) || !nodeById.has(target)) return;
    const key = source + "\u0000" + type + "\u0000" + target;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    edges.push({ source: source, target: target, type: type });
  });

  edges.sort(function (left, right) {
    return (
      left.source.localeCompare(right.source) ||
      left.type.localeCompare(right.type) ||
      left.target.localeCompare(right.target)
    );
  });

  const outgoing = new Map();
  const incoming = new Map();
  edges.forEach(function (edge) {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    outgoing.get(edge.source).push(edge);
    incoming.get(edge.target).push(edge);
  });

  function flattenSearchValues(value, result, depth) {
    if (depth > 3 || result.length >= 40) return;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      result.push(String(value));
      return;
    }
    if (Array.isArray(value)) {
      value.slice(0, 20).forEach(function (item) {
        flattenSearchValues(item, result, depth + 1);
      });
      return;
    }
    if (value && typeof value === "object") {
      Object.keys(value)
        .sort()
        .slice(0, 20)
        .forEach(function (key) {
          result.push(key);
          flattenSearchValues(value[key], result, depth + 1);
        });
    }
  }

  nodes.forEach(function (node) {
    const values = [node.id, node.type, node.name, node.language, node.path, node.qualified_name];
    flattenSearchValues(node.metadata, values, 0);
    node.searchText = values.join(" ").toLocaleLowerCase("ko-KR");
    node.nameLower = node.name.toLocaleLowerCase("ko-KR");
    node.qualifiedLower = node.qualified_name.toLocaleLowerCase("ko-KR");
    node.idLower = node.id.toLocaleLowerCase("ko-KR");
  });

  const state = {
    activeLens: "overview",
    selectedId: "",
    rootId: "",
    depth: Math.max(1, Math.min(3, finiteNumber(dom.depthSelect.value, 2))),
    direction: dom.directionSelect.value,
    searchMatches: [],
    activeSearchIndex: -1,
    renderToken: 0,
    cy: null,
  };

  function isSpringAnnotation(node) {
    if (!node || node.type !== "FrameworkAnnotation") return false;
    return arrayOrEmpty(node.metadata.semantic_groups).some(function (group) {
      return SPRING_GROUPS.has(text(group));
    });
  }

  function edgeAllowed(edge, lens, rootId) {
    const allowed = RELATION_SETS[lens];
    if (allowed && !allowed.has(edge.type)) return false;
    if (lens === "spring" && edge.type === "ANNOTATED_BY") {
      return isSpringAnnotation(nodeById.get(edge.target));
    }
    if (lens === "architecture" && edge.type === "DECLARES") {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      return (
        (source && target && STRUCTURAL_TYPES.has(source.type) && STRUCTURAL_TYPES.has(target.type)) ||
        edge.source === rootId ||
        edge.target === rootId
      );
    }
    return true;
  }

  function lensEdges(lens, rootId) {
    return edges.filter(function (edge) {
      return edgeAllowed(edge, lens, rootId || "");
    });
  }

  function degreeFor(nodeId, candidateEdges) {
    let degree = 0;
    candidateEdges.forEach(function (edge) {
      if (edge.source === nodeId || edge.target === nodeId) degree += 1;
    });
    return degree;
  }

  function preferredTypesForLens(lens) {
    if (lens === "architecture") return new Set(["Package", "Module", "Class", "Interface"]);
    if (lens === "spring") return new Set(["FrameworkConcept", "Class", "Interface", "Method"]);
    if (lens === "policy") return new Set(["PolicyLeaf"]);
    if (lens === "pipeline") return new Set(["PipelineRole"]);
    return new Set(["Package", "Module", "Class", "PolicyLeaf", "PipelineRole"]);
  }

  function defaultSeed(lens) {
    const candidates = lensEdges(lens, "");
    const preferred = preferredTypesForLens(lens);
    const connected = new Set();
    candidates.forEach(function (edge) {
      connected.add(edge.source);
      connected.add(edge.target);
    });
    const choices = nodes.filter(function (node) {
      return connected.has(node.id) && preferred.has(node.type);
    });
    const pool = choices.length
      ? choices
      : nodes.filter(function (node) {
          return connected.has(node.id);
        });
    pool.sort(function (left, right) {
      return (
        degreeFor(right.id, candidates) - degreeFor(left.id, candidates) ||
        left.nameLower.localeCompare(right.nameLower) ||
        left.id.localeCompare(right.id)
      );
    });
    return pool.length ? pool[0].id : nodes.length ? nodes[0].id : "";
  }

  function neighborhood(rootId, lens, depth, direction) {
    if (!nodeById.has(rootId)) return { nodes: [], edges: [], truncated: false };
    const candidates = lensEdges(lens, rootId);
    const localOutgoing = new Map();
    const localIncoming = new Map();
    candidates.forEach(function (edge) {
      if (!localOutgoing.has(edge.source)) localOutgoing.set(edge.source, []);
      if (!localIncoming.has(edge.target)) localIncoming.set(edge.target, []);
      localOutgoing.get(edge.source).push(edge);
      localIncoming.get(edge.target).push(edge);
    });
    const visited = new Set([rootId]);
    const queue = [{ id: rootId, depth: 0 }];
    let truncated = false;

    while (queue.length) {
      const current = queue.shift();
      if (current.depth >= depth) continue;
      const steps = [];
      if (direction !== "incoming") {
        arrayOrEmpty(localOutgoing.get(current.id)).forEach(function (edge) {
          steps.push({ id: edge.target, edge: edge });
        });
      }
      if (direction !== "outgoing") {
        arrayOrEmpty(localIncoming.get(current.id)).forEach(function (edge) {
          steps.push({ id: edge.source, edge: edge });
        });
      }
      steps.sort(function (left, right) {
        return (
          left.edge.type.localeCompare(right.edge.type) ||
          left.id.localeCompare(right.id)
        );
      });
      for (let index = 0; index < steps.length; index += 1) {
        const neighborId = steps[index].id;
        if (visited.has(neighborId)) continue;
        if (visited.size >= maxVisibleNodes) {
          truncated = true;
          break;
        }
        visited.add(neighborId);
        queue.push({ id: neighborId, depth: current.depth + 1 });
      }
      if (truncated && visited.size >= maxVisibleNodes) break;
    }

    const selectedNodes = Array.from(visited)
      .map(function (id) {
        return nodeById.get(id);
      })
      .filter(Boolean);
    const selectedEdges = candidates.filter(function (edge) {
      return visited.has(edge.source) && visited.has(edge.target);
    });
    return { nodes: selectedNodes, edges: selectedEdges, truncated: truncated };
  }

  function populateFacet(select, values, allLabel) {
    const current = select.value;
    const first = make("option", "", allLabel);
    first.value = "";
    const options = [first];
    Array.from(values)
      .sort(function (left, right) {
        return left.localeCompare(right, "ko");
      })
      .forEach(function (value) {
        const option = make("option", "", value);
        option.value = value;
        options.push(option);
      });
    select.replaceChildren.apply(select, options);
    if (values.has(current)) select.value = current;
  }

  function searchScore(node, needle) {
    if (!needle) return typePriority(node.type);
    if (node.nameLower === needle) return 0;
    if (node.qualifiedLower === needle || node.idLower === needle) return 1;
    if (node.nameLower.startsWith(needle)) return 2;
    if (node.qualifiedLower.startsWith(needle)) return 3;
    if (node.idLower.startsWith(needle)) return 4;
    if (node.searchText.includes(needle)) return 5;
    return Number.POSITIVE_INFINITY;
  }

  function runSearch() {
    const needle = dom.searchInput.value.trim().toLocaleLowerCase("ko-KR");
    const language = dom.languageFilter.value;
    const type = dom.typeFilter.value;
    const ranked = [];
    nodes.forEach(function (node) {
      if (language && node.language !== language) return;
      if (type && node.type !== type) return;
      const score = searchScore(node, needle);
      if (!Number.isFinite(score)) return;
      ranked.push({ node: node, score: score });
    });
    ranked.sort(function (left, right) {
      return (
        left.score - right.score ||
        typePriority(left.node.type) - typePriority(right.node.type) ||
        left.node.nameLower.localeCompare(right.node.nameLower) ||
        left.node.id.localeCompare(right.node.id)
      );
    });
    state.searchMatches = ranked.map(function (item) {
      return item.node;
    });
    state.activeSearchIndex = state.searchMatches.length ? 0 : -1;
    renderSearchResults();
  }

  function resultContext(node) {
    return node.path || node.qualified_name || node.id;
  }

  function renderSearchResults() {
    const visible = state.searchMatches.slice(0, MAX_SEARCH_RESULTS);
    dom.searchCount.textContent = formatCount(state.searchMatches.length);
    if (!visible.length) {
      dom.searchResults.replaceChildren(
        make("div", "empty-results", "일치하는 심볼이 없습니다. 검색어나 필터를 바꾸어 보세요.")
      );
      dom.searchInput.removeAttribute("aria-activedescendant");
      return;
    }
    const fragment = document.createDocumentFragment();
    visible.forEach(function (node, index) {
      const button = make("button", "search-result");
      button.type = "button";
      button.id = "search-option-" + index;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", node.id === state.selectedId ? "true" : "false");
      if (node.id === state.selectedId) button.classList.add("is-selected");
      if (index === state.activeSearchIndex) button.dataset.active = "true";
      const title = make("span", "result-title", node.name);
      const metaRow = make("span", "result-meta");
      append(
        metaRow,
        make("span", "type-chip", typeLabel(node.type)),
        make("span", "", node.language)
      );
      append(button, title, metaRow, make("span", "result-context", resultContext(node)));
      button.addEventListener("click", function () {
        focusAsRoot(node.id);
      });
      fragment.appendChild(button);
    });
    dom.searchResults.replaceChildren(fragment);
    syncActiveSearchOption(false);
  }

  function syncActiveSearchOption(scroll) {
    const visibleCount = Math.min(state.searchMatches.length, MAX_SEARCH_RESULTS);
    if (!visibleCount || state.activeSearchIndex < 0) {
      dom.searchInput.removeAttribute("aria-activedescendant");
      return;
    }
    state.activeSearchIndex = Math.max(0, Math.min(visibleCount - 1, state.activeSearchIndex));
    const options = dom.searchResults.querySelectorAll("[role='option']");
    options.forEach(function (option, index) {
      if (index === state.activeSearchIndex) {
        option.dataset.active = "true";
      } else {
        delete option.dataset.active;
      }
    });
    const active = document.getElementById("search-option-" + state.activeSearchIndex);
    if (active) {
      dom.searchInput.setAttribute("aria-activedescendant", active.id);
      if (scroll) active.scrollIntoView({ block: "nearest" });
    }
  }

  function metricCard(label, value, note) {
    return append(
      make("article", "metric-card"),
      make("div", "metric-label", label),
      make("div", "metric-value", value),
      make("div", "metric-note", note)
    );
  }

  function countBy(items, key) {
    const counts = Object.create(null);
    items.forEach(function (item) {
      const value = text(item[key], "Unknown");
      counts[value] = (counts[value] || 0) + 1;
    });
    return counts;
  }

  function renderBars(container, counts, labeler) {
    const entries = Object.keys(counts).map(function (key) {
      return [key, finiteNumber(counts[key], 0)];
    });
    entries.sort(function (left, right) {
      return right[1] - left[1] || left[0].localeCompare(right[0]);
    });
    const maximum = entries.length ? Math.max(1, entries[0][1]) : 1;
    const fragment = document.createDocumentFragment();
    entries.forEach(function (entry) {
      const row = make("div", "bar-item");
      const track = make("div", "bar-track");
      const fill = make("div", "bar-fill");
      fill.style.width = Math.max(1, (entry[1] / maximum) * 100) + "%";
      append(track, fill);
      append(
        row,
        make("div", "bar-label", labeler(entry[0])),
        track,
        make("div", "bar-value", formatCount(entry[1]))
      );
      fragment.appendChild(row);
    });
    if (!entries.length) fragment.appendChild(make("div", "empty-results", "집계 데이터가 없습니다."));
    container.replaceChildren(fragment);
  }

  function sourceFileCount() {
    const sourceFiles = objectOrEmpty(statistics.sourceFiles || statistics.source_files);
    return Object.keys(sourceFiles).reduce(function (sum, key) {
      return sum + finiteNumber(sourceFiles[key], 0);
    }, 0);
  }

  function renderOverview() {
    const nodeCount = finiteNumber(statistics.nodes, nodes.length);
    const edgeCount = finiteNumber(statistics.edges, edges.length);
    const warningCount = finiteNumber(statistics.warnings, warnings.length);
    dom.metricCards.replaceChildren(
      metricCard("분석 파일", formatCount(sourceFileCount()), "Java · Python 정적 분석"),
      metricCard("심볼", formatCount(nodeCount), "검색 가능한 전체 인덱스"),
      metricCard("관계", formatCount(edgeCount), "방향이 있는 구조적 연결"),
      metricCard("경고", formatCount(warningCount), warningCount ? "검토가 필요한 분석 공백" : "파싱 경고 없음")
    );
    renderBars(
      dom.nodeTypeBars,
      Object.keys(objectOrEmpty(statistics.nodeTypes || statistics.node_types)).length
        ? objectOrEmpty(statistics.nodeTypes || statistics.node_types)
        : countBy(nodes, "type"),
      typeLabel
    );
    renderBars(
      dom.edgeTypeBars,
      Object.keys(objectOrEmpty(statistics.edgeTypes || statistics.edge_types)).length
        ? objectOrEmpty(statistics.edgeTypes || statistics.edge_types)
        : countBy(edges, "type"),
      relationLabel
    );

    const packages = nodes.filter(function (node) {
      return node.type === "Package" || node.type === "Module";
    });
    packages.sort(function (left, right) {
      return (
        degreeFor(right.id, edges) - degreeFor(left.id, edges) ||
        left.nameLower.localeCompare(right.nameLower) ||
        left.id.localeCompare(right.id)
      );
    });
    dom.packageCount.textContent = formatCount(packages.length);
    const packageFragment = document.createDocumentFragment();
    packages.slice(0, 18).forEach(function (node) {
      const button = make("button", "package-button");
      button.type = "button";
      append(
        button,
        make("strong", "", node.qualified_name || node.name),
        make("span", "", formatCount(degreeFor(node.id, edges)) + "개 직접 연결")
      );
      button.addEventListener("click", function () {
        switchLens("architecture", node.id);
      });
      packageFragment.appendChild(button);
    });
    if (!packages.length) packageFragment.appendChild(make("div", "empty-results", "패키지나 모듈이 없습니다."));
    dom.packageList.replaceChildren(packageFragment);

    const guided = [
      ["architecture", "▤", "구조의 큰 덩어리는?", "패키지, 상속, 구현 관계부터 봅니다."],
      ["spring", "⇄", "어디서 주입되는가?", "Bean과 프록시 경계를 따라갑니다."],
      ["policy", "⊢", "정책이 무엇을 막는가?", "정책 값과 조건 분기를 연결합니다."],
      ["pipeline", "⇥", "처리 흐름은 어디로 가는가?", "역할, 데코레이터, 호출을 따라갑니다."],
    ];
    const guidedFragment = document.createDocumentFragment();
    guided.forEach(function (item) {
      const button = make("button", "guided-action");
      button.type = "button";
      append(
        button,
        make("span", "guided-icon", item[1]),
        make("strong", "", item[2]),
        make("span", "", item[3])
      );
      button.addEventListener("click", function () {
        switchLens(item[0]);
      });
      guidedFragment.appendChild(button);
    });
    dom.guidedActions.replaceChildren(guidedFragment);
  }

  function relationPhrase(edge, direction) {
    if (edge.type === "READS_POLICY_LEAF") {
      return direction === "outgoing" ? "이 심볼이 읽는 정책 값" : "이 정책 값을 읽는 메서드";
    }
    if (edge.type === "DECLARES_RUNTIME_BRANCH") {
      return direction === "outgoing" ? "이 메서드의 조건 분기" : "이 분기를 선언한 메서드";
    }
    if (edge.type === "GUARDS_RUNTIME_BRANCH") {
      return direction === "outgoing" ? "이 정책 값이 제어하는 분기" : "이 분기를 제어하는 정책 값";
    }
    return relationLabel(edge.type) + (direction === "outgoing" ? " · 나가는 관계" : " · 들어오는 관계");
  }

  function ownerTrail(nodeId) {
    const result = [];
    const seen = new Set([nodeId]);
    let current = nodeId;
    for (let depth = 0; depth < 6; depth += 1) {
      const ownerEdge = arrayOrEmpty(incoming.get(current))
        .filter(function (edge) {
          return edge.type === "DECLARES" && !seen.has(edge.source);
        })
        .sort(function (left, right) {
          return left.source.localeCompare(right.source);
        })[0];
      if (!ownerEdge) break;
      const owner = nodeById.get(ownerEdge.source);
      if (!owner) break;
      result.unshift(owner.name);
      seen.add(owner.id);
      current = owner.id;
    }
    return result;
  }

  function propertyRow(label, value) {
    const row = make("div", "property-row");
    append(row, make("dt", "", label), make("dd", "", value || "—"));
    return row;
  }

  function groupedRelations(nodeId, direction) {
    const sourceEdges = direction === "outgoing" ? arrayOrEmpty(outgoing.get(nodeId)) : arrayOrEmpty(incoming.get(nodeId));
    const groups = new Map();
    sourceEdges.forEach(function (edge) {
      const key = edge.type;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(edge);
    });
    return Array.from(groups.entries()).sort(function (left, right) {
      return left[0].localeCompare(right[0]);
    });
  }

  function neighborButton(edge, direction) {
    const neighborId = direction === "outgoing" ? edge.target : edge.source;
    const neighbor = nodeById.get(neighborId);
    const button = make("button", "neighbor-button", neighbor ? neighbor.name : neighborId);
    button.type = "button";
    button.title = neighbor ? resultContext(neighbor) : neighborId;
    button.addEventListener("click", function () {
      selectNode(neighborId, false);
    });
    return button;
  }

  function renderRelationGroups(container, nodeId, direction) {
    const groups = groupedRelations(nodeId, direction);
    groups.forEach(function (entry) {
      const group = make("div", "relation-group");
      const heading = make("div", "relation-group-title");
      append(
        heading,
        make("span", "", relationPhrase(entry[1][0], direction)),
        make("span", "relation-chip", formatCount(entry[1].length))
      );
      const list = make("div", "neighbor-list");
      entry[1]
        .slice()
        .sort(function (left, right) {
          const leftId = direction === "outgoing" ? left.target : left.source;
          const rightId = direction === "outgoing" ? right.target : right.source;
          const leftNode = nodeById.get(leftId);
          const rightNode = nodeById.get(rightId);
          return (
            (leftNode ? leftNode.nameLower : leftId).localeCompare(rightNode ? rightNode.nameLower : rightId) ||
            leftId.localeCompare(rightId)
          );
        })
        .slice(0, MAX_DETAIL_NEIGHBORS)
        .forEach(function (edge) {
          list.appendChild(neighborButton(edge, direction));
        });
      if (entry[1].length > MAX_DETAIL_NEIGHBORS) {
        list.appendChild(
          make("div", "result-context", "+ " + formatCount(entry[1].length - MAX_DETAIL_NEIGHBORS) + "개 더 있음")
        );
      }
      append(group, heading, list);
      container.appendChild(group);
    });
    if (!groups.length) container.appendChild(make("div", "empty-results", "이 방향의 관계가 없습니다."));
  }

  function renderDetails(node) {
    if (!node) return;
    const header = make("div", "details-header");
    append(
      header,
      make("span", "type-chip", typeLabel(node.type)),
      make("h3", "", node.name),
      make("div", "details-subtitle", node.qualified_name || node.path || node.id)
    );
    const actions = make("div", "details-actions");
    const centerButton = make("button", "primary-button", "이 심볼 중심으로 보기");
    centerButton.type = "button";
    centerButton.addEventListener("click", function () {
      if (state.activeLens === "overview" || state.activeLens === "changes") {
        switchLens("explore", node.id);
      } else {
        state.rootId = node.id;
        renderGraph();
      }
    });
    const searchButton = make("button", "secondary-button", "검색어로 사용");
    searchButton.type = "button";
    searchButton.addEventListener("click", function () {
      dom.searchInput.value = node.name;
      runSearch();
      dom.searchInput.focus();
    });
    append(actions, centerButton, searchButton);

    const properties = make("section", "details-section");
    properties.appendChild(make("h4", "", "속성"));
    const list = make("dl", "property-list");
    const trail = ownerTrail(node.id);
    append(
      list,
      propertyRow("유형", typeLabel(node.type)),
      propertyRow("언어", node.language),
      propertyRow("소유 구조", trail.length ? trail.join(" › ") : "—"),
      propertyRow("정규 이름", node.qualified_name),
      propertyRow("상대 경로", node.path)
    );
    Object.keys(node.metadata)
      .sort()
      .forEach(function (key) {
        const value = node.metadata[key];
        const rendered = typeof value === "object" ? JSON.stringify(value) : text(value);
        list.appendChild(propertyRow(key, rendered));
      });
    properties.appendChild(list);

    const outgoingSection = make("section", "details-section");
    outgoingSection.appendChild(make("h4", "", "나가는 관계"));
    renderRelationGroups(outgoingSection, node.id, "outgoing");
    const incomingSection = make("section", "details-section");
    incomingSection.appendChild(make("h4", "", "들어오는 관계"));
    renderRelationGroups(incomingSection, node.id, "incoming");

    const relatedWarnings = warnings.filter(function (warning) {
      return node.path && text(warning.path) === node.path;
    });
    let warningSection = null;
    if (relatedWarnings.length) {
      warningSection = make("section", "details-section");
      warningSection.appendChild(make("h4", "", "이 파일의 분석 경고"));
      relatedWarnings.forEach(function (warning) {
        warningSection.appendChild(make("p", "details-subtitle", text(warning.message, "분석 경고")));
      });
    }

    const raw = make("details", "raw-details");
    append(raw, make("summary", "", "고급: 원본 노드 JSON"), make("pre", "", JSON.stringify(node, null, 2)));
    dom.detailsContent.replaceChildren(header, actions, properties, outgoingSection, incomingSection);
    if (warningSection) dom.detailsContent.appendChild(warningSection);
    dom.detailsContent.appendChild(raw);
  }

  function renderRemovedDetails(item) {
    const node = objectOrEmpty(item);
    const header = make("div", "details-header");
    append(
      header,
      make("span", "type-chip", typeLabel(text(node.type, "Unknown"))),
      make("h3", "change-removed", text(node.name, text(node.id, "삭제된 심볼"))),
      make("div", "details-subtitle", "현재 스냅샷에는 없는 심볼입니다.")
    );
    const section = make("section", "details-section");
    append(
      section,
      make("h4", "", "이전 스냅샷 정보"),
      append(
        make("dl", "property-list"),
        propertyRow("식별자", text(node.id)),
        propertyRow("정규 이름", text(node.qualified_name || node.qualifiedName)),
        propertyRow("상대 경로", text(node.path)),
        propertyRow("언어", text(node.language))
      )
    );
    const raw = make("details", "raw-details");
    append(raw, make("summary", "", "고급: 변경 기록 JSON"), make("pre", "", JSON.stringify(node, null, 2)));
    dom.detailsContent.replaceChildren(header, section, raw);
  }

  function selectNode(nodeId, updateGraphSelection) {
    const node = nodeById.get(nodeId);
    if (!node) return;
    state.selectedId = nodeId;
    renderDetails(node);
    renderSearchResults();
    if (state.cy) {
      state.cy.nodes().unselect();
      const element = state.cy.getElementById(nodeId);
      if (element && element.length) element.select();
    }
    if (updateGraphSelection) {
      state.rootId = nodeId;
      renderGraph();
    }
    announce(node.name + " 선택됨");
  }

  function focusAsRoot(nodeId) {
    if (!nodeById.has(nodeId)) return;
    state.selectedId = nodeId;
    state.rootId = nodeId;
    renderDetails(nodeById.get(nodeId));
    if (state.activeLens === "overview" || state.activeLens === "changes") {
      switchLens("explore", nodeId);
    } else {
      renderSearchResults();
      renderGraph();
    }
  }

  function cyNodeData(node, rootId) {
    return {
      id: node.id,
      label: shortLabel(node.name, 36),
      type: node.type,
      language: node.language,
      color: ownValue(NODE_COLORS, node.language, "#ff8790"),
      shape: ownValue(TYPE_SHAPES, node.type, "round-rectangle"),
      root: node.id === rootId ? "yes" : "no",
    };
  }

  function graphElements(graph) {
    const elements = graph.nodes.map(function (node) {
      return {
        group: "nodes",
        data: cyNodeData(node, state.rootId),
        classes: node.id === state.rootId ? "root" : "",
      };
    });
    graph.edges.forEach(function (edge, index) {
      elements.push({
        group: "edges",
        data: {
          id: "edge-" + index,
          source: edge.source,
          target: edge.target,
          type: edge.type,
          label: relationLabel(edge.type),
        },
      });
    });
    return elements;
  }

  function ensureCytoscape() {
    if (state.cy) return true;
    if (typeof window.cytoscape !== "function") return false;
    state.cy = window.cytoscape({
      container: dom.graph,
      elements: [],
      minZoom: 0.12,
      maxZoom: 3,
      wheelSensitivity: 0.22,
      selectionType: "single",
      boxSelectionEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            width: 34,
            height: 34,
            shape: "data(shape)",
            "background-color": "data(color)",
            "background-opacity": 0.92,
            "border-width": 1.2,
            "border-color": "#d7eee5",
            "border-opacity": 0.62,
            label: "data(label)",
            color: "#dcebe5",
            "font-size": 9,
            "font-weight": 600,
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 7,
            "text-wrap": "ellipsis",
            "text-max-width": 138,
            "text-outline-width": 2,
            "text-outline-color": "#081510",
          },
        },
        {
          selector: "node.root",
          style: {
            width: 48,
            height: 48,
            "border-width": 4,
            "border-color": "#65f0ba",
            "background-opacity": 1,
            "font-size": 11,
            "font-weight": 800,
          },
        },
        {
          selector: "node:selected",
          style: {
            "overlay-opacity": 0,
            "border-width": 4,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.3,
            "line-color": "#5b7b70",
            "target-arrow-color": "#75a697",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.75,
            "curve-style": "bezier",
            opacity: 0.7,
            label: "data(label)",
            color: "#8ca69d",
            "font-size": 7,
            "text-rotation": "autorotate",
            "text-margin-y": -8,
            "text-background-color": "#0a1814",
            "text-background-opacity": 0.82,
            "text-background-padding": 2,
          },
        },
        {
          selector: "edge[type = 'GUARDS_RUNTIME_BRANCH']",
          style: {
            "line-color": "#f8c15c",
            "target-arrow-color": "#f8c15c",
            width: 2.2,
          },
        },
        {
          selector: ".faded",
          style: { opacity: 0.1, "text-opacity": 0.08 },
        },
        {
          selector: ".highlighted",
          style: { opacity: 1, "z-index": 10 },
        },
      ],
    });
    state.cy.on("tap", "node", function (event) {
      selectNode(event.target.id(), false);
    });
    state.cy.on("mouseover", "node", function (event) {
      state.cy.elements().addClass("faded");
      event.target.closedNeighborhood().removeClass("faded").addClass("highlighted");
    });
    state.cy.on("mouseout", "node", function () {
      state.cy.elements().removeClass("faded highlighted");
    });
    return true;
  }

  function fallbackLayout(token, rootId) {
    if (!state.cy || token !== state.renderToken) return;
    const nodesOnly = state.cy.nodes();
    const options = nodesOnly.length <= 1
      ? { name: "grid", fit: true, padding: 44 }
      : {
          name: "breadthfirst",
          directed: true,
          circle: false,
          spacingFactor: 1.35,
          padding: 44,
          roots: state.cy.getElementById(rootId),
          fit: true,
        };
    state.cy.layout(options).run();
    dom.graphNote.textContent += " · 계층형 기본 배치";
  }

  async function layoutWithElk(graph, token) {
    if (!state.cy || token !== state.renderToken) return;
    if (typeof window.ELK !== "function") {
      fallbackLayout(token, state.rootId);
      return;
    }
    const localIdByNode = new Map();
    graph.nodes.forEach(function (node, index) {
      localIdByNode.set(node.id, "n" + index);
    });
    const elkGraph = {
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": "34",
        "elk.layered.spacing.nodeNodeBetweenLayers": "72",
        "elk.padding": "[top=36,left=36,bottom=36,right=36]",
        "elk.layered.cycleBreaking.strategy": "GREEDY",
      },
      children: graph.nodes.map(function (node) {
        return { id: localIdByNode.get(node.id), width: 154, height: 54 };
      }),
      edges: graph.edges.map(function (edge, index) {
        return {
          id: "e" + index,
          sources: [localIdByNode.get(edge.source)],
          targets: [localIdByNode.get(edge.target)],
        };
      }),
    };
    try {
      const elk = new window.ELK();
      const result = await elk.layout(elkGraph);
      if (!state.cy || token !== state.renderToken) return;
      const originalByLocal = new Map();
      localIdByNode.forEach(function (localId, originalId) {
        originalByLocal.set(localId, originalId);
      });
      const positions = new Map();
      arrayOrEmpty(result.children).forEach(function (child) {
        const originalId = originalByLocal.get(child.id);
        if (originalId) {
          positions.set(originalId, {
            x: finiteNumber(child.x, 0) + finiteNumber(child.width, 0) / 2,
            y: finiteNumber(child.y, 0) + finiteNumber(child.height, 0) / 2,
          });
        }
      });
      if (positions.size !== graph.nodes.length) throw new Error("ELK returned incomplete positions");
      state.cy.nodes().positions(function (element) {
        return positions.get(element.id());
      });
      state.cy.fit(state.cy.elements(), 46);
    } catch (error) {
      fallbackLayout(token, state.rootId);
    }
  }

  function renderGraph() {
    if (state.activeLens === "overview" || state.activeLens === "changes") return;
    if (!state.rootId || !nodeById.has(state.rootId)) state.rootId = defaultSeed(state.activeLens);
    if (!state.selectedId && state.rootId) state.selectedId = state.rootId;
    const graph = neighborhood(state.rootId, state.activeLens, state.depth, state.direction);
    const token = state.renderToken + 1;
    state.renderToken = token;
    setHidden(dom.graphEmpty, graph.nodes.length > 0);
    dom.graph.setAttribute(
      "aria-label",
      typeLabel(nodeById.get(state.rootId) ? nodeById.get(state.rootId).type : "") +
        " 중심의 정적 관계 그래프. 노드 " +
        graph.nodes.length +
        "개, 관계 " +
        graph.edges.length +
        "개."
    );
    dom.graphNote.textContent =
      formatCount(graph.nodes.length) +
      "개 노드 · " +
      formatCount(graph.edges.length) +
      "개 관계 · 깊이 " +
      state.depth +
      (graph.truncated ? " · 표시 한도 " + formatCount(maxVisibleNodes) + "개에 도달" : "");

    if (!graph.nodes.length) {
      if (state.cy) state.cy.elements().remove();
      announce("표시할 관계가 없습니다.");
      return;
    }
    if (!ensureCytoscape()) {
      setHidden(dom.graphEmpty, false);
      dom.graphEmpty.replaceChildren(
        make("strong", "", "그래프 엔진을 불러오지 못했습니다."),
        make("span", "", "검색 결과와 상세 패널로 전체 온톨로지를 계속 탐색할 수 있습니다.")
      );
      dom.graphNote.textContent = "Cytoscape를 사용할 수 없음";
      announce("그래프 엔진을 불러오지 못했습니다.");
      return;
    }

    state.cy.startBatch();
    state.cy.elements().remove();
    state.cy.add(graphElements(graph));
    state.cy.endBatch();
    const selected = state.cy.getElementById(state.selectedId);
    if (selected && selected.length) selected.select();
    window.requestAnimationFrame(function () {
      if (!state.cy || token !== state.renderToken) return;
      state.cy.resize();
      layoutWithElk(graph, token);
    });
    announce("노드 " + graph.nodes.length + "개와 관계 " + graph.edges.length + "개를 표시했습니다.");
  }

  function changeCount(name) {
    return finiteNumber(objectOrEmpty(changes.counts)[name], arrayOrEmpty(changes[name]).length);
  }

  function changeNodeButton(item, mode) {
    const node = objectOrEmpty(item);
    const button = make("button", "change-item");
    button.type = "button";
    const nodeId = text(node.id);
    append(
      button,
      make(
        "strong",
        mode === "added" ? "change-added" : mode === "modified" ? "change-modified" : "change-removed",
        text(node.name, nodeId || "이름 없음")
      ),
      make("span", "", typeLabel(text(node.type, "Unknown")))
    );
    button.addEventListener("click", function () {
      if (nodeId && nodeById.has(nodeId)) {
        switchLens("explore", nodeId);
      } else {
        renderRemovedDetails(node);
        announce("삭제된 심볼의 이전 스냅샷 정보를 표시했습니다.");
      }
    });
    return button;
  }

  function edgeDescription(item) {
    const edge = objectOrEmpty(item);
    const source = nodeById.get(text(edge.source));
    const target = nodeById.get(text(edge.target));
    return (
      (source ? source.name : shortLabel(text(edge.source), 24)) +
      " → " +
      (target ? target.name : shortLabel(text(edge.target), 24))
    );
  }

  function changeEdgeButton(item, mode) {
    const edge = objectOrEmpty(item);
    const button = make("button", "change-item");
    button.type = "button";
    append(
      button,
      make("strong", mode === "added" ? "change-added" : "change-removed", edgeDescription(edge)),
      make("span", "", relationLabel(text(edge.type)))
    );
    const source = text(edge.source);
    const target = text(edge.target);
    const available = nodeById.has(source) ? source : nodeById.has(target) ? target : "";
    if (available) {
      button.addEventListener("click", function () {
        switchLens("explore", available);
      });
    } else {
      button.disabled = true;
    }
    return button;
  }

  function changeList(title, items, mode, kind) {
    const card = make("article", "surface-card change-list");
    const heading = make("div", "card-heading");
    append(
      heading,
      append(
        make("div", ""),
        make("span", "section-kicker", mode === "added" ? "추가" : mode === "modified" ? "수정" : "삭제"),
        make("h3", "", title)
      ),
      make("span", "count-pill", formatCount(items.length))
    );
    const list = make("div", "change-items");
    items.forEach(function (item) {
      list.appendChild(kind === "node" ? changeNodeButton(item, mode) : changeEdgeButton(item, mode));
    });
    if (!items.length) list.appendChild(make("div", "empty-results", "해당 변경이 없습니다."));
    append(card, heading, list);
    return card;
  }

  function renderChanges() {
    const hasComparison =
      changes.available !== false && Boolean(changes.beforeSnapshotId || changes.previousSnapshotId);
    if (!hasComparison) {
      const card = make("article", "surface-card");
      append(
        card,
        make("div", "section-kicker", "첫 스냅샷"),
        make("h3", "", "비교할 이전 스냅샷이 없습니다"),
        make("p", "view-description", "다음 동기화부터 추가·삭제된 심볼과 관계를 이곳에서 비교합니다.")
      );
      dom.changesView.replaceChildren(card);
      return;
    }
    const summary = make("div", "change-summary");
    summary.appendChild(metricCard("추가 심볼", formatCount(changeCount("nodesAdded")), "현재 스냅샷에 새로 등장"));
    summary.appendChild(metricCard("삭제 심볼", formatCount(changeCount("nodesRemoved")), "이전 스냅샷에서 사라짐"));
    summary.appendChild(metricCard("수정 심볼", formatCount(changeCount("nodesModified")), "같은 ID의 속성이 변경됨"));
    summary.appendChild(metricCard("추가 관계", formatCount(changeCount("edgesAdded")), "새로운 정적 연결"));
    summary.appendChild(metricCard("삭제 관계", formatCount(changeCount("edgesRemoved")), "사라진 정적 연결"));
    const context = make("article", "surface-card");
    append(
      context,
      make("div", "section-kicker", text(changes.basis, "정적 구조 비교")),
      make("h3", "", shortLabel(text(changes.beforeSnapshotId, "이전") + " → " + text(changes.afterSnapshotId, "현재"), 110)),
      make(
        "p",
        "view-description",
        "이 비교는 정적 구조의 상관관계이며 실제 실행 변화나 인과관계를 증명하지 않습니다." +
          (changes.truncated ? " 목록은 일부만 표시됩니다." : "")
      )
    );
    const nodeGrid = make("div", "change-list-grid");
    append(
      nodeGrid,
      changeList("추가된 심볼", arrayOrEmpty(changes.nodesAdded), "added", "node"),
      changeList("삭제된 심볼", arrayOrEmpty(changes.nodesRemoved), "removed", "node"),
      changeList("수정된 심볼", arrayOrEmpty(changes.nodesModified), "modified", "node")
    );
    const edgeGrid = make("div", "change-list-grid");
    append(
      edgeGrid,
      changeList("추가된 관계", arrayOrEmpty(changes.edgesAdded), "added", "edge"),
      changeList("삭제된 관계", arrayOrEmpty(changes.edgesRemoved), "removed", "edge")
    );
    dom.changesView.replaceChildren(summary, context, nodeGrid, edgeGrid);
  }

  function updateLensButtons(lens) {
    dom.lensNav.querySelectorAll("[data-lens]").forEach(function (button) {
      const active = button.dataset.lens === lens;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
  }

  function switchLens(lens, preferredRoot) {
    if (!LENS_COPY[lens]) return;
    state.activeLens = lens;
    const copy = LENS_COPY[lens];
    dom.viewEyebrow.textContent = copy.eyebrow;
    dom.viewTitle.textContent = copy.title;
    dom.viewDescription.textContent = copy.description;
    updateLensButtons(lens);
    const graphMode = lens !== "overview" && lens !== "changes";
    if (!graphMode) state.renderToken += 1;
    setHidden(dom.overviewView, lens !== "overview");
    setHidden(dom.graphView, !graphMode);
    setHidden(dom.changesView, lens !== "changes");
    setHidden(dom.graphToolbar, !graphMode);
    if (lens === "changes") renderChanges();
    if (graphMode) {
      if (preferredRoot && nodeById.has(preferredRoot)) {
        state.rootId = preferredRoot;
        state.selectedId = preferredRoot;
      } else if (!state.rootId || !nodeById.has(state.rootId) || !degreeFor(state.rootId, lensEdges(lens, state.rootId))) {
        state.rootId = defaultSeed(lens);
        state.selectedId = state.rootId;
      }
      if (state.selectedId && nodeById.has(state.selectedId)) renderDetails(nodeById.get(state.selectedId));
      renderSearchResults();
      window.requestAnimationFrame(renderGraph);
    }
    announce(copy.eyebrow + " 관점으로 이동했습니다.");
  }

  function initializeMeta() {
    const repositoryName = text(meta.repositoryName, "이름 없는 저장소");
    dom.repositoryName.textContent = repositoryName;
    dom.repositoryName.title = repositoryName;
    dom.snapshotBadge.textContent = text(meta.snapshotId, "standalone");
    dom.snapshotBadge.title = "생성: " + formatDate(meta.generatedAt) + " · 생성기 " + text(meta.generatorVersion, "unknown");
    dom.evidenceBadge.textContent = text(meta.evidenceType, "observed-static");
    const warningCount = finiteNumber(statistics.warnings, warnings.length);
    dom.warningBadge.textContent = formatCount(warningCount) + " warnings";
    dom.warningBadge.classList.toggle("status-badge--warning", warningCount > 0);
    document.title = "Code Ontology Workbench — " + repositoryName;
  }

  function bindEvents() {
    dom.lensNav.addEventListener("click", function (event) {
      const button = event.target.closest("[data-lens]");
      if (button) switchLens(button.dataset.lens);
    });
    dom.globalSearch.addEventListener("submit", function (event) {
      event.preventDefault();
      const selected = state.searchMatches[state.activeSearchIndex];
      if (selected) focusAsRoot(selected.id);
    });
    dom.searchInput.setAttribute("aria-controls", "search-results");
    dom.searchInput.setAttribute("aria-autocomplete", "list");
    dom.searchInput.addEventListener("input", function () {
      runSearch();
    });
    dom.searchInput.addEventListener("keydown", function (event) {
      const visibleCount = Math.min(state.searchMatches.length, MAX_SEARCH_RESULTS);
      if (event.key === "ArrowDown" && visibleCount) {
        event.preventDefault();
        state.activeSearchIndex = (state.activeSearchIndex + 1 + visibleCount) % visibleCount;
        syncActiveSearchOption(true);
      } else if (event.key === "ArrowUp" && visibleCount) {
        event.preventDefault();
        state.activeSearchIndex = (state.activeSearchIndex - 1 + visibleCount) % visibleCount;
        syncActiveSearchOption(true);
      } else if (event.key === "Escape") {
        if (dom.searchInput.value) {
          dom.searchInput.value = "";
          runSearch();
        } else {
          dom.searchInput.blur();
        }
      }
    });
    dom.languageFilter.addEventListener("change", runSearch);
    dom.typeFilter.addEventListener("change", runSearch);
    dom.depthSelect.addEventListener("change", function () {
      state.depth = Math.max(1, Math.min(3, finiteNumber(dom.depthSelect.value, 2)));
      renderGraph();
    });
    dom.directionSelect.addEventListener("change", function () {
      state.direction = ["both", "incoming", "outgoing"].includes(dom.directionSelect.value)
        ? dom.directionSelect.value
        : "both";
      renderGraph();
    });
    dom.zoomIn.addEventListener("click", function () {
      if (state.cy) state.cy.zoom({ level: Math.min(state.cy.maxZoom(), state.cy.zoom() * 1.2), renderedPosition: { x: dom.graph.clientWidth / 2, y: dom.graph.clientHeight / 2 } });
    });
    dom.zoomOut.addEventListener("click", function () {
      if (state.cy) state.cy.zoom({ level: Math.max(state.cy.minZoom(), state.cy.zoom() / 1.2), renderedPosition: { x: dom.graph.clientWidth / 2, y: dom.graph.clientHeight / 2 } });
    });
    dom.fitGraph.addEventListener("click", function () {
      if (state.cy) state.cy.fit(state.cy.elements(), 46);
    });
    dom.resetView.addEventListener("click", function () {
      state.depth = 2;
      state.direction = "both";
      dom.depthSelect.value = "2";
      dom.directionSelect.value = "both";
      state.rootId = defaultSeed(state.activeLens);
      state.selectedId = state.rootId;
      if (state.selectedId) renderDetails(nodeById.get(state.selectedId));
      renderSearchResults();
      renderGraph();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      const editing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (!editing) {
        event.preventDefault();
        dom.searchInput.focus();
        dom.searchInput.select();
      }
    });
    window.addEventListener("resize", function () {
      if (state.cy && !dom.graphView.hidden) {
        state.cy.resize();
        state.cy.fit(state.cy.elements(), 46);
      }
    });
  }

  initializeMeta();
  populateFacet(
    dom.languageFilter,
    new Set(nodes.map(function (node) { return node.language; })),
    "모든 언어"
  );
  populateFacet(
    dom.typeFilter,
    new Set(nodes.map(function (node) { return node.type; })),
    "모든 유형"
  );
  renderOverview();
  renderChanges();
  bindEvents();
  runSearch();
  const requestedLens = new URLSearchParams(window.location.search).get("lens") || "";
  switchLens(LENS_COPY[requestedLens] ? requestedLens : "overview");
})();
