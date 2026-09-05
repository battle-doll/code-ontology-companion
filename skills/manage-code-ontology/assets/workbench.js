(function () {
  "use strict";

  const HARD_MAX_VISIBLE_NODES = 250;
  const MAX_3D_VISIBLE_NODES = 160;
  const MAX_3D_VISIBLE_EDGES = 480;
  const THREE_D_FRAME_BUDGET_MS = 20;
  const THREE_D_FRAME_INTERVAL_MS = 33;
  const THREE_D_SLOW_FRAME_INTERVAL_MS = 66;
  const MAX_SEARCH_RESULTS = 80;
  const MAX_MODULE_GROUPS = 12;
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
    architecture: null,
    impact: new Set(["CALLS", "INJECTS", "EXTENDS", "IMPLEMENTS", "DECLARES_BEAN", "READS_POLICY_LEAF", "GUARDS_RUNTIME_BRANCH"]),
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
    architecture: { eyebrow: "SOURCE ATLAS", title: "구조", description: "" },
    impact: { eyebrow: "DEPENDENCY TRACE", title: "영향", description: "정적 의존 관계" },
    changes: { eyebrow: "SNAPSHOT DIFF", title: "변경", description: "" },
  };
  const LENS_ALIASES = { overview: "architecture", explore: "architecture", spring: "architecture", policy: "architecture", pipeline: "architecture" };
  const GENERIC_CONCEPT_TYPES = new Set(["FrameworkConcept", "Annotation", "PipelineRole"]);

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

  const QUALITY_STATUS_LABELS = {
    supported: "지원",
    partial: "부분 지원",
    unsupported: "미지원",
    unknown: "알 수 없음",
  };

  const EVIDENCE_BASIS_LABELS = {
    direct_syntax: "직접 구문",
    resolved_static: "해석된 정적 관계",
    framework_semantic: "프레임워크 의미",
    name_heuristic: "이름 휴리스틱",
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
    graph3d: document.getElementById("graph-3d"),
    graph3dCanvas: document.getElementById("graph-3d-canvas"),
    graph3dSummary: document.getElementById("graph-3d-summary"),
    graph3dStatus: document.getElementById("graph-3d-status"),
    graphTextAlternative: document.getElementById("graph-text-alternative"),
    graphTextSummary: document.getElementById("graph-text-summary"),
    graphTextNodes: document.getElementById("graph-text-nodes"),
    graphTextEdges: document.getElementById("graph-text-edges"),
    graphEmpty: document.getElementById("graph-empty"),
    graphNote: document.getElementById("graph-note"),
    depthSelect: document.getElementById("depth-select"),
    directionSelect: document.getElementById("direction-select"),
    zoomOut: document.getElementById("zoom-out"),
    zoomIn: document.getElementById("zoom-in"),
    fitGraph: document.getElementById("fit-graph"),
    resetView: document.getElementById("reset-view"),
    viewMode2d: document.getElementById("view-mode-2d"),
    viewMode3d: document.getElementById("view-mode-3d"),
    motionToggle: document.getElementById("motion-toggle"),
    metricCards: document.getElementById("metric-cards"),
    qualityPanel: document.getElementById("quality-panel"),
    qualityContract: document.getElementById("quality-contract"),
    qualityContent: document.getElementById("quality-content"),
    nodeTypeBars: document.getElementById("node-type-bars"),
    edgeTypeBars: document.getElementById("edge-type-bars"),
    packageCount: document.getElementById("package-count"),
    packageList: document.getElementById("package-list"),
    guidedActions: document.getElementById("guided-actions"),
    detailsContent: document.getElementById("details-content"),
    liveStatus: document.getElementById("live-status"),
    searchPanel: document.getElementById("search-panel"),
    detailsPanel: document.getElementById("details-panel"),
    closeSearch: document.getElementById("close-search"),
    closeDetails: document.getElementById("close-details"),
    qualityToggle: document.getElementById("quality-toggle"),
    qualityClose: document.getElementById("quality-close"),
    viewBack: document.getElementById("view-back"),
    copyLink: document.getElementById("copy-link"),
    linkStatus: document.getElementById("link-status"),
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
  const quality = objectOrEmpty(payload.quality);
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
    edges.push({
      source: source,
      target: target,
      type: type,
      key: key,
      evidence: arrayOrEmpty(item.evidence).filter(function (entry) {
        return entry && typeof entry === "object" && !Array.isArray(entry);
      }),
    });
  });

  edges.sort(function (left, right) {
    return (
      left.source.localeCompare(right.source) ||
      left.type.localeCompare(right.type) ||
      left.target.localeCompare(right.target)
    );
  });

  const edgeByKey = new Map(edges.map(function (edge) { return [edge.key, edge]; }));
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

  const reducedMotionQuery = typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false, addEventListener: null };

  const state = {
    activeLens: "architecture",
    atlasOverview: true,
    selectionHistory: [],
    restoringSelection: false,
    selectedEvidenceId: "",
    graphSignature: "",
    selectedId: "",
    rootId: "",
    depth: Math.max(1, Math.min(3, finiteNumber(dom.depthSelect.value, 2))),
    direction: dom.directionSelect.value,
    searchMatches: [],
    activeSearchIndex: -1,
    searchVisibleLimit: MAX_SEARCH_RESULTS,
    selectedEdgeKey: "",
    renderedEdgeById: new Map(),
    renderedEdgeIdByKey: new Map(),
    renderToken: 0,
    cy: null,
    viewMode: "3d",
    threeDAvailable: true,
    threeDContext: null,
    threeDGraph: null,
    threeDPositions: new Map(),
    threeDProjectedNodes: [],
    threeDProjectedEdges: [],
    threeDGroups: [],
    groupByNodeId: new Map(),
    cameraTransition: null,
    cameraFocusId: "",
    threeDFrame: 0,
    threeDLastFrameAt: 0,
    threeDLastRenderMs: 0,
    threeDFocusedIndex: 0,
    threeDHoverNodeId: "",
    threeDHoverEdgeKey: "",
    threeDDragging: false,
    threeDDragDistance: 0,
    threeDPointer: { x: 0, y: 0 },
    motionEnabled: !reducedMotionQuery.matches,
    camera: { yaw: -0.38, pitch: -0.16, zoom: 1, distance: 980, x: 0, y: 0, z: 0 },
  };

  function isSpringAnnotation(node) {
    if (!node || node.type !== "FrameworkAnnotation") return false;
    return arrayOrEmpty(node.metadata.semantic_groups).some(function (group) {
      return SPRING_GROUPS.has(text(group));
    });
  }

  function edgeAllowed(edge, lens, rootId) {
    const allowed = RELATION_SETS[lens];
    if (lens === "impact") {
      const concept = function (node) { return !node || GENERIC_CONCEPT_TYPES.has(node.type) || ["Framework", "Concept"].includes(node.language); };
      if (concept(nodeById.get(edge.source)) || concept(nodeById.get(edge.target))) return false;
    }
    if (allowed && !allowed.has(edge.type)) return false;
    if (lens === "spring" && edge.type === "ANNOTATED_BY") {
      return isSpringAnnotation(nodeById.get(edge.target));
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
    const degrees = new Map();
    candidates.forEach(function (edge) { degrees.set(edge.source, (degrees.get(edge.source) || 0) + 1); degrees.set(edge.target, (degrees.get(edge.target) || 0) + 1); });
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
        (degrees.get(right.id) || 0) - (degrees.get(left.id) || 0) ||
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
    const selectedRelation = edgeByKey.get(state.selectedEdgeKey);
    if (selectedRelation && edgeAllowed(selectedRelation, lens, rootId) && (selectedRelation.source === rootId || selectedRelation.target === rootId)) {
      const endpoint = selectedRelation.source === rootId ? selectedRelation.target : selectedRelation.source;
      if (visited.size < maxVisibleNodes) { visited.add(endpoint); queue.push({ id: endpoint, depth: 1 }); }
    }
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
    state.searchVisibleLimit = MAX_SEARCH_RESULTS;
    renderSearchResults();
  }

  function resultContext(node) {
    return node.path || node.qualified_name || node.id;
  }

  function renderSearchResults() {
    const visible = state.searchMatches.slice(0, state.searchVisibleLimit);
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
      button.dataset.nodeId = node.id;
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
        const replacement = Array.from(dom.searchResults.querySelectorAll("[data-node-id]")).find(function (option) {
          return option.dataset.nodeId === node.id;
        });
        if (replacement) dom.graph3dCanvas.focus({ preventScroll: true });
      });
      fragment.appendChild(button);
    });
    if (visible.length < state.searchMatches.length) {
      const more = make("button", "more-button", "검색 결과 더 보기 · " + formatCount(state.searchMatches.length - visible.length));
      more.type = "button";
      more.addEventListener("click", function () {
        const nextIndex = state.searchVisibleLimit;
        state.searchVisibleLimit += MAX_SEARCH_RESULTS;
        renderSearchResults();
        const next = document.getElementById("search-option-" + nextIndex);
        if (next) next.focus({ preventScroll: true });
      });
      fragment.appendChild(more);
    }
    dom.searchResults.replaceChildren(fragment);
    syncActiveSearchOption(false);
  }

  function syncActiveSearchOption(scroll) {
    const visibleCount = Math.min(state.searchMatches.length, state.searchVisibleLimit);
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

  function qualityStatus(value) {
    const normalized = text(value).toLowerCase();
    return Object.prototype.hasOwnProperty.call(QUALITY_STATUS_LABELS, normalized)
      ? normalized
      : "unknown";
  }

  function qualityStatusChip(value, prefix) {
    const status = qualityStatus(value);
    return make(
      "span",
      "quality-status quality-status--" + status,
      (prefix ? prefix + " · " : "") + QUALITY_STATUS_LABELS[status]
    );
  }

  function qualityCountChip(label, count) {
    const chip = make("span", "quality-chip");
    append(chip, make("span", "", label), make("strong", "", formatCount(count)));
    return chip;
  }

  function qualityMap(value) {
    const result = objectOrEmpty(value);
    return Object.keys(result).length ? result : {};
  }

  function qualityField(object, snakeCaseName, camelCaseName, fallback) {
    if (object[snakeCaseName] !== undefined && object[snakeCaseName] !== null) {
      return object[snakeCaseName];
    }
    if (object[camelCaseName] !== undefined && object[camelCaseName] !== null) {
      return object[camelCaseName];
    }
    return fallback;
  }

  function renderQualityPanel() {
    const qualityContract = text(
      quality.contract_version || quality.contractVersion || quality.status,
      "legacy_unknown"
    ).toLowerCase();
    if (!Object.keys(quality).length || qualityContract === "legacy_unknown") {
      dom.qualityPanel.dataset.qualityState = "legacy";
      dom.qualityContract.textContent = "legacy snapshot";
      dom.qualityContent.replaceChildren(
        make(
          "p",
          "quality-legacy",
          "이 스냅샷에는 품질 계약 메타데이터가 없습니다. 증거 범위를 추정하지 않고 기존 정적 관계 탐색을 계속 제공합니다."
        )
      );
      return;
    }

    dom.qualityPanel.dataset.qualityState = "available";
    dom.qualityContract.textContent = "contract " + text(quality.contract_version || quality.contractVersion, "unknown");
    const relationship = objectOrEmpty(
      quality.relationship_evidence || quality.relationshipEvidence
    );
    const totalEdges = Math.max(
      0,
      finiteNumber(qualityField(relationship, "total_edges", "totalEdges", edges.length), edges.length)
    );
    const documentedEdges = Math.max(
      0,
      finiteNumber(qualityField(relationship, "documented_edges", "documentedEdges", 0), 0)
    );
    const missingEvidence = Math.max(
      0,
      finiteNumber(
        qualityField(
          relationship,
          "missing_evidence",
          "missingEvidence",
          Math.max(0, totalEdges - documentedEdges)
        ),
        Math.max(0, totalEdges - documentedEdges)
      )
    );
    const coverageValue = finiteNumber(
      qualityField(
        relationship,
        "coverage_percent",
        "coveragePercent",
        totalEdges ? (documentedEdges / totalEdges) * 100 : 0
      ),
      totalEdges ? (documentedEdges / totalEdges) * 100 : 0
    );
    const coverage = Math.max(0, Math.min(100, coverageValue));
    const summary = make("div", "quality-summary");
    append(
      summary,
      append(
        make("div", "quality-stat"),
        make("strong", "", formatCount(documentedEdges) + " / " + formatCount(totalEdges)),
        make("span", "", "근거가 연결된 관계")
      ),
      append(
        make("div", "quality-stat"),
        make("strong", "", formatCount(Object.keys(qualityMap(quality.adapters)).length)),
        make("span", "", "언어 어댑터")
      ),
      append(
        make("div", "quality-stat"),
        make("strong", "", formatCount(missingEvidence)),
        make("span", "", "증거 메타데이터가 없는 관계")
      )
    );

    const basisSection = make("section", "quality-subsection");
    basisSection.appendChild(make("h4", "", "증거 근거"));
    const basisList = make("div", "quality-chip-list");
    const basisCounts = qualityMap(relationship.basis_counts || relationship.basisCounts);
    Object.keys(basisCounts)
      .sort()
      .forEach(function (basis) {
        basisList.appendChild(
          qualityCountChip(ownValue(EVIDENCE_BASIS_LABELS, basis, basis), basisCounts[basis])
        );
      });
    if (!Object.keys(basisCounts).length) {
      basisList.appendChild(make("span", "details-subtitle", "근거 집계 없음"));
    }
    basisSection.appendChild(basisList);

    const adapterSection = make("section", "quality-subsection");
    adapterSection.appendChild(make("h4", "", "언어 어댑터"));
    const adapterList = make("div", "adapter-list");
    const adapters = qualityMap(quality.adapters);
    Object.keys(adapters)
      .sort()
      .forEach(function (language) {
        const adapter = objectOrEmpty(adapters[language]);
        const row = make("div", "adapter-row");
        const heading = make("div", "adapter-heading");
        append(
          heading,
          make("strong", "", language + (adapter.detected === false ? " · 미검출" : "")),
          qualityStatusChip(adapter.status)
        );
        row.appendChild(heading);
        const capabilities = qualityMap(adapter.capabilities);
        if (Object.keys(capabilities).length) {
          const capabilityList = make("div", "adapter-capabilities");
          Object.keys(capabilities)
            .sort()
            .forEach(function (capability) {
              capabilityList.appendChild(qualityStatusChip(capabilities[capability], capability));
            });
          row.appendChild(capabilityList);
        }
        const unsupportedRuntime = arrayOrEmpty(
          adapter.unsupported_runtime || adapter.unsupportedRuntime
        )
          .map(function (item) { return text(item); })
          .filter(Boolean);
        if (unsupportedRuntime.length) {
          row.appendChild(
            make(
              "p",
              "adapter-runtime-gap",
              "런타임 미지원: " + unsupportedRuntime.join(", ")
            )
          );
        }
        adapterList.appendChild(row);
      });
    if (!Object.keys(adapters).length) {
      adapterList.appendChild(make("span", "details-subtitle", "어댑터 상태 없음"));
    }
    adapterSection.appendChild(adapterList);

    const grid = make("div", "quality-grid");
    append(grid, basisSection, adapterSection);
    const content = document.createDocumentFragment();
    append(content, summary, grid);

    const runtimeCounts = qualityMap(
      relationship.runtime_status_counts || relationship.runtimeStatusCounts
    );
    const runtimeUnknown = Math.max(
      0,
      finiteNumber(qualityField(runtimeCounts, "runtime_unknown", "runtimeUnknown", 0), 0)
    );
    if (runtimeUnknown > 0) {
      content.appendChild(
        make(
          "p",
          "quality-runtime-warning",
          "런타임 확인 안 됨 · " + formatCount(runtimeUnknown) +
            "개 관계는 정적 증거만 있으며 실제 실행·활성화 여부를 입증하지 않습니다."
        )
      );
    }
    const interpretation = text(quality.interpretation);
    if (interpretation) {
      content.appendChild(make("p", "quality-interpretation", interpretation));
    }
    dom.qualityContent.replaceChildren(content);
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
    dom.metricCards.replaceChildren(
      metricCard("파일", formatCount(sourceFileCount()), ""),
      metricCard("심볼", formatCount(finiteNumber(statistics.nodes, nodes.length)), ""),
      metricCard("관계", formatCount(finiteNumber(statistics.edges, edges.length)), ""),
      metricCard("분석 경고", formatCount(finiteNumber(statistics.warnings, warnings.length)), "")
    );
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
      const heading = append(make("div", "relation-group-title"), make("span", "", relationPhrase(entry[1][0], direction)), make("span", "relation-chip", formatCount(entry[1].length)));
      const list = make("div", "neighbor-list");
      const sorted = entry[1].slice().sort(function (left, right) { return left.key.localeCompare(right.key); });
      let shown = 0;
      const more = make("button", "more-button");
      more.type = "button";
      function showPage() {
        sorted.slice(shown, shown + MAX_DETAIL_NEIGHBORS).forEach(function (edge) { list.appendChild(neighborButton(edge, direction)); });
        shown = Math.min(sorted.length, shown + MAX_DETAIL_NEIGHBORS);
        more.textContent = "더 보기 · " + formatCount(sorted.length - shown);
        setHidden(more, shown >= sorted.length);
      }
      more.addEventListener("click", showPage);
      showPage();
      append(group, heading, list, more);
      container.appendChild(group);
    });
    if (!groups.length) container.appendChild(make("div", "empty-results", "연결 없음"));
  }

  function renderDetails(node) {
    if (!node) return;
    setHidden(dom.detailsPanel, false);
    setHidden(dom.searchPanel, true);
    dom.searchInput.setAttribute("aria-expanded", "false");
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
    centerButton.addEventListener("click", function () { focusAsRoot(node.id); });
    const searchButton = make("button", "secondary-button", "의존 관계");
    searchButton.type = "button";
    searchButton.addEventListener("click", function () {
      switchLens("impact", node.id);
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
    const line = node.metadata.line || node.metadata.line_start;
    if (line) list.appendChild(propertyRow("줄", text(line)));
    if (["ExternalType", "ExternalModule", "ExternalCallable"].includes(node.type)) list.appendChild(propertyRow("경계", "외부 / 미해결 대상"));
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


    dom.detailsContent.replaceChildren(header, actions, properties, outgoingSection, incomingSection);
    if (warningSection) dom.detailsContent.appendChild(warningSection);

  }

  function evidenceBasisLabel(value) {
    const basis = text(value);
    return ownValue(EVIDENCE_BASIS_LABELS, basis, basis || "근거 미상");
  }

  function evidenceSourceLocation(item) {
    const path = text(item.path);
    if (
      !path ||
      path.length > 1000 ||
      path.startsWith("/") ||
      path.startsWith("\\") ||
      /^[A-Za-z]:[\\/]/.test(path) ||
      path.split(/[\\/]/).some(function (part) { return part === ".."; }) ||
      Array.from(path).some(function (character) { return character.charCodeAt(0) < 32; })
    ) {
      return "";
    }
    const start = Math.trunc(finiteNumber(item.line_start || item.lineStart, 0));
    const end = Math.trunc(finiteNumber(item.line_end || item.lineEnd, 0));
    if (start < 1) return path;
    return path + ":" + start + (end > start ? "-" + end : "");
  }

  function renderEdgeEvidenceCard(item) {
    const evidence = objectOrEmpty(item);
    const evidenceId = text(evidence.evidence_id || evidence.id);
    const card = make("article", "edge-evidence-card" + (evidenceId && evidenceId === state.selectedEvidenceId ? " is-selected" : ""));
    if (evidenceId) card.dataset.evidenceId = evidenceId;
    const heading = make("div", "edge-evidence-heading");
    append(
      heading,
      make("strong", "", text(evidence.rule_id || evidence.ruleId, "규칙 미상")),
      make("span", "quality-chip", evidenceBasisLabel(evidence.basis))
    );
    const currentEdge = edgeByKey.get(state.selectedEdgeKey);
    if (evidenceId && currentEdge && currentEdge.evidence.some(function (item) { return text(item.evidence_id || item.id) === evidenceId; })) {
      const link = make("button", "icon-button", "↗"); link.type = "button"; link.setAttribute("aria-label", "이 근거 선택");
      link.addEventListener("click", function () { state.selectedEvidenceId = evidenceId; updateSelectionLink(); const edge = edgeByKey.get(state.selectedEdgeKey); if (edge) renderEdgeDetails(edge); });
      heading.appendChild(link);
    }
    card.appendChild(heading);
    const location = evidenceSourceLocation(evidence);
    if (location) card.appendChild(make("div", "edge-evidence-location", location));
    const runtimeStatus = text(evidence.runtime_status || evidence.runtimeStatus);
    if (runtimeStatus === "runtime_unknown") {
      card.appendChild(
        make(
          "div",
          "edge-evidence-runtime",
          "런타임 확인 안 됨 · 이 규칙은 정적 관계만 설명합니다."
        )
      );
    } else if (runtimeStatus === "not_applicable") {
      card.appendChild(make("div", "details-subtitle", "런타임 상태: 해당 없음"));
    }
    const limitations = arrayOrEmpty(evidence.limitations)
      .map(function (itemValue) { return text(itemValue); })
      .filter(Boolean)
      .slice(0, 12);
    if (limitations.length) {
      const list = make("div", "edge-evidence-limitations");
      limitations.forEach(function (limitation) {
        list.appendChild(make("span", "quality-chip", limitation));
      });
      card.appendChild(list);
    }
    return card;
  }

  function renderEdgeDetails(edge) {
    if (!edge) return;
    setHidden(dom.detailsPanel, false);
    state.selectedEdgeKey = edge.key;
    if (state.selectedId !== edge.source && state.selectedId !== edge.target) state.selectedId = edge.source;
    if (state.selectedEvidenceId && !edge.evidence.some(function (item) { return text(item.evidence_id || item.id) === state.selectedEvidenceId; })) state.selectedEvidenceId = "";
    updateViewHeading();
    updateSelectionLink();
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    const header = make("div", "details-header");
    append(
      header,
      make("span", "relation-chip", relationLabel(edge.type)),
      make(
        "h3",
        "",
        (source ? source.name : edge.source) + " → " + (target ? target.name : edge.target)
      ),
      make("div", "details-subtitle", "선택한 관계의 정적 증거")
    );
    const properties = make("section", "details-section");
    append(
      properties,
      make("h4", "", "관계"),
      append(
        make("dl", "property-list"),
        propertyRow("출발", source ? source.qualified_name || source.name : edge.source),
        propertyRow("도착", target ? target.qualified_name || target.name : edge.target),
        propertyRow("유형", relationLabel(edge.type)),
        propertyRow("증거", formatCount(edge.evidence.length) + "건")
      )
    );
    const evidenceSection = make("section", "details-section");
    evidenceSection.appendChild(make("h4", "", "관계 증거"));
    const evidenceList = make("div", "edge-evidence-list");
    let shownEvidence = 0;
    const moreEvidence = make("button", "more-button");
    moreEvidence.type = "button";
    const selectedIndex = edge.evidence.findIndex(function (item) { return text(item.evidence_id || item.id) === state.selectedEvidenceId; });
    function showEvidencePage() {
      const end = Math.min(edge.evidence.length, Math.max(shownEvidence + 12, selectedIndex + 1));
      edge.evidence.slice(shownEvidence, end).forEach(function (item) { evidenceList.appendChild(renderEdgeEvidenceCard(item)); });
      shownEvidence = end;
      moreEvidence.textContent = "근거 더 보기 · " + formatCount(edge.evidence.length - shownEvidence);
      setHidden(moreEvidence, shownEvidence >= edge.evidence.length);
    }
    moreEvidence.addEventListener("click", showEvidencePage);
    showEvidencePage();
    if (!edge.evidence.length) evidenceList.appendChild(make("p", "quality-legacy", "구조화된 근거 없음"));
    evidenceSection.appendChild(moreEvidence);
    evidenceSection.insertBefore(evidenceList, moreEvidence);
    evidenceSection.appendChild(
      make(
        "p",
        "edge-evidence-note",
        "정적 근거 · 소스 본문은 이 패널에 포함하지 않습니다."
      )
    );
    dom.detailsContent.replaceChildren(header, properties, evidenceSection);
  }

  function renderRemovedDetails(item) {
    setHidden(dom.detailsPanel, false);
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
    dom.detailsContent.replaceChildren(header, section);
  }

  function selectionUrl() {
    const url = new URL(window.location.href);
    url.search = "";
    url.hash = "";
    url.searchParams.set("lens", state.activeLens);
    if (meta.snapshotId) url.searchParams.set("snapshot", text(meta.snapshotId));
    if (state.selectedId) url.searchParams.set("entity", state.selectedId);
    if (state.selectedEdgeKey) url.searchParams.set("edge", state.selectedEdgeKey);
    if (state.selectedEvidenceId) url.searchParams.set("evidence", state.selectedEvidenceId);
    return url;
  }

  function updateSelectionLink() {
    if (state.restoringSelection) return;
    try { window.history.replaceState(null, "", selectionUrl().href); } catch (error) { /* File viewers may disallow history updates; the explicit link remains available. */ }
  }

  function linkFailure(message) {
    dom.linkStatus.textContent = message;
    setHidden(dom.linkStatus, false);
    announce(message);
    return null;
  }

  function readSelectionLink() {
    const params = new URLSearchParams(window.location.search);
    const entity = params.get("entity") || "";
    const edgeKey = params.get("edge") || "";
    const evidenceId = params.get("evidence") || "";
    const snapshot = params.get("snapshot") || "";
    if ((entity || edgeKey || evidenceId) && (!snapshot || snapshot !== text(meta.snapshotId))) return linkFailure("이 링크는 현재 스냅샷의 근거를 가리키지 않습니다.");
    if (snapshot && snapshot !== text(meta.snapshotId)) return linkFailure("스냅샷이 다릅니다. 현재 코드 지도를 표시합니다.");
    if (entity && !nodeById.has(entity)) return linkFailure("이 스냅샷에 해당 심볼이 없습니다.");
    const edge = edgeKey ? edgeByKey.get(edgeKey) : null;
    if (edgeKey && (!edge || (entity && edge.source !== entity && edge.target !== entity))) return linkFailure("심볼과 관계의 근거 연결을 확인할 수 없습니다.");
    if (evidenceId && (!edge || !edge.evidence.some(function (item) { return text(item.evidence_id || item.id) === evidenceId; }))) return linkFailure("해당 관계에 연결된 근거가 아닙니다.");
    const requested = params.get("lens") || "architecture";
    return { lens: edge ? "architecture" : LENS_COPY[requested] ? requested : LENS_ALIASES[requested] || "architecture", entity: entity || (edge ? edge.source : ""), edge: edge, evidenceId: evidenceId };
  }

  function updateViewHeading() {
    const node = nodeById.get(state.selectedId || (state.activeLens === "impact" ? state.rootId : ""));
    dom.viewEyebrow.textContent = LENS_COPY[state.activeLens].eyebrow;
    dom.viewTitle.textContent = state.activeLens === "changes" ? "변경된 코드" : node ? node.name : text(meta.repositoryName, "코드 지도");
    dom.viewDescription.textContent = state.activeLens === "changes" ? "" : state.activeLens === "impact" ? "정적 의존 후보 · " + (state.direction === "incoming" ? "이 코드에 의존" : state.direction === "outgoing" ? "이 코드의 의존 대상" : "양방향") : node ? shortLabel(node.path || node.qualified_name, 85) : "";
  }

  function rememberSelection() {
    if (state.restoringSelection) return;
    const previous = { lens: state.activeLens, rootId: state.rootId, selectedId: state.selectedId, edgeKey: state.selectedEdgeKey, evidenceId: state.selectedEvidenceId, overview: state.atlasOverview, camera: Object.assign({}, state.camera) };
    const last = state.selectionHistory[state.selectionHistory.length - 1];
    if (!last || last.lens !== previous.lens || last.rootId !== previous.rootId || last.selectedId !== previous.selectedId || last.edgeKey !== previous.edgeKey || last.overview !== previous.overview) state.selectionHistory.push(previous);
    if (state.selectionHistory.length > 40) state.selectionHistory.shift();
    dom.viewBack.disabled = !state.selectionHistory.length;
  }

  function goBack() {
    const previous = state.selectionHistory.pop();
    if (!previous) return;
    state.restoringSelection = true;
    state.atlasOverview = previous.overview;
    state.rootId = previous.rootId;
    state.selectedId = previous.selectedId;
    state.selectedEdgeKey = previous.edgeKey;
    state.selectedEvidenceId = previous.evidenceId;
    switchLens(previous.lens, "", true);
    state.camera = previous.camera;
    state.cameraTransition = null;
    if (state.selectedEdgeKey) renderEdgeDetails(edgeByKey.get(state.selectedEdgeKey));
    else if (state.selectedId) renderDetails(nodeById.get(state.selectedId));
    else setHidden(dom.detailsPanel, true);
    state.restoringSelection = false;
    dom.viewBack.disabled = !state.selectionHistory.length;
    updateSelectionLink();
    draw3dScene(0);
  }

  function selectNode(nodeId, updateGraphSelection) {
    const node = nodeById.get(nodeId);
    if (!node) return;
    if (state.selectedId !== nodeId || state.selectedEdgeKey) rememberSelection();
    state.selectedId = nodeId;
    state.selectedEdgeKey = "";
    state.selectedEvidenceId = "";
    renderDetails(node);
    renderSearchResults();
    if (state.cy) {
      state.cy.elements().unselect();
      const element = state.cy.getElementById(nodeId);
      if (element && element.length) element.select();
    }
    if (updateGraphSelection || !state.threeDPositions.has(nodeId) || (state.activeLens === "impact" && state.rootId !== nodeId)) {
      state.rootId = nodeId;
      state.atlasOverview = false;
      renderGraph();
    } else {
      syncGraphTextSelection();
      focus3dCamera(nodeId);
    }
    updateViewHeading();
    updateSelectionLink();
    announce(node.name + " 선택됨");
  }

  function focusAsRoot(nodeId) {
    if (!nodeById.has(nodeId)) return;
    rememberSelection();
    state.atlasOverview = false;
    state.selectedId = nodeId;
    state.selectedEdgeKey = "";
    state.selectedEvidenceId = "";
    state.rootId = nodeId;
    renderDetails(nodeById.get(nodeId));
    if (state.activeLens === "changes") switchLens("architecture", nodeId, true);
    else { renderSearchResults(); renderGraph(); updateViewHeading(); }
    focus3dCamera(nodeId);
    updateSelectionLink();
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
    state.renderedEdgeById.clear();
    state.renderedEdgeIdByKey.clear();
    const elements = graph.nodes.map(function (node) {
      return {
        group: "nodes",
        data: cyNodeData(node, state.rootId),
        classes: node.id === state.rootId ? "root" : "",
      };
    });
    graph.edges.forEach(function (edge, index) {
      const edgeId = "edge-" + index;
      state.renderedEdgeById.set(edgeId, edge);
      state.renderedEdgeIdByKey.set(edge.key, edgeId);
      elements.push({
        group: "edges",
        data: {
          id: edgeId,
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
          selector: "edge:selected",
          style: {
            "line-color": "#65f0ba",
            "target-arrow-color": "#65f0ba",
            width: 3,
            opacity: 1,
            "z-index": 12,
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
    state.cy.on("tap", "edge", function (event) {
      const edge = state.renderedEdgeById.get(event.target.id());
      if (!edge) return;
      rememberSelection();
      state.selectedEdgeKey = edge.key;
      state.cy.elements().unselect();
      event.target.select();
      renderEdgeDetails(edge);
      syncGraphTextSelection();
      announce(relationLabel(edge.type) + " 관계 증거 선택됨");
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

  const GROUP_COLORS = ["#76e6ee", "#a795f5", "#7ae4bc", "#85baff", "#e9bc87", "#e49fc5"];
  const groupCache = new Map();

  function moduleGroup(node) {
    if (groupCache.has(node.id)) return groupCache.get(node.id);
    let current = node;
    const seen = new Set();
    let owner = null;
    for (let depth = 0; current && depth < 16 && !seen.has(current.id); depth += 1) {
      seen.add(current.id);
      if (current.type === "Module" || current.type === "Package") { owner = current; break; }
      const parent = arrayOrEmpty(incoming.get(current.id)).find(function (edge) { return edge.type === "DECLARES"; });
      current = parent ? nodeById.get(parent.source) : null;
    }
    const path = node.path.replace(/\\/g, "/");
    const directory = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    const group = owner
      ? { key: owner.id, label: owner.qualified_name || owner.name, kind: typeLabel(owner.type), anchorId: owner.id }
      : directory ? { key: "path:" + directory, label: directory, kind: "소스 폴더", anchorId: "" }
      : { key: path ? "file:" + path : "boundary:" + node.language, label: path || node.language, kind: path ? "소스 파일" : "외부 / 미해결", anchorId: "" };
    groupCache.set(node.id, group);
    return group;
  }

  function atlasGraph() {
    const groups = new Map();
    nodes.forEach(function (node) {
      const key = moduleGroup(node).key;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(node);
    });
    const buckets = Array.from(groups.entries()).sort(function (a, b) {
      const sourceA = a[1].some(function (node) { return Boolean(node.path); });
      const sourceB = b[1].some(function (node) { return Boolean(node.path); });
      return Number(sourceB) - Number(sourceA) || b[1].length - a[1].length || a[0].localeCompare(b[0]);
    }).slice(0, MAX_MODULE_GROUPS);
    buckets.forEach(function (entry) { entry[1].sort(function (a, b) { return typePriority(a.type) - typePriority(b.type) || a.id.localeCompare(b.id); }); });
    const selected = [];
    const included = new Set();
    if (state.selectedId && nodeById.has(state.selectedId)) { selected.push(nodeById.get(state.selectedId)); included.add(state.selectedId); }
    for (let offset = 0; selected.length < Math.min(MAX_3D_VISIBLE_NODES, maxVisibleNodes); offset += 1) {
      let found = false;
      for (let index = 0; index < buckets.length; index += 1) {
        const node = buckets[index][1][offset];
        if (!node) continue;
        found = true;
        if (!included.has(node.id)) { selected.push(node); included.add(node.id); }
        if (selected.length >= Math.min(MAX_3D_VISIBLE_NODES, maxVisibleNodes)) break;
      }
      if (!found) break;
    }
    return { nodes: selected, edges: edges.filter(function (edge) { return included.has(edge.source) && included.has(edge.target); }), truncated: selected.length < nodes.length };
  }

  function buildModuleLayout(graph) {
    const grouped = new Map();
    graph.nodes.forEach(function (node) {
      const descriptor = moduleGroup(node);
      if (!grouped.has(descriptor.key)) grouped.set(descriptor.key, { descriptor: descriptor, nodes: [] });
      grouped.get(descriptor.key).nodes.push(node);
    });
    state.threeDGroups = Array.from(grouped.values()).sort(function (a, b) { return a.descriptor.key.localeCompare(b.descriptor.key); });
    state.groupByNodeId.clear();
    const groupCount = state.threeDGroups.length;
    state.threeDGroups.forEach(function (group, groupIndex) {
      const angle = (groupIndex / Math.max(1, groupCount)) * Math.PI * 2 - Math.PI / 2;
      const orbit = groupCount <= 1 ? 0 : groupCount <= 4 ? 205 : Math.min(440, 205 + groupCount * 13);
      group.center = { x: Math.cos(angle) * orbit, y: Math.sin(angle) * orbit * 0.58, z: Math.sin(angle * 2 + .5) * Math.min(140, orbit * .35) };
      group.color = GROUP_COLORS[groupIndex % GROUP_COLORS.length];
      group.nodes.sort(function (a, b) { return (a.id === group.descriptor.anchorId ? -1 : b.id === group.descriptor.anchorId ? 1 : typePriority(a.type) - typePriority(b.type)) || a.id.localeCompare(b.id); });
      group.radius = Math.min(168, 46 + Math.sqrt(group.nodes.length) * 13);
      group.nodes.forEach(function (node, index) {
        state.groupByNodeId.set(node.id, group);
        state.threeDPositions.set(node.id, deterministic3dPosition(node, index, group.nodes.length, group));
      });
    });
  }

  function stable3dHash(value) {
    let hash = 2166136261;
    const source = text(value);
    for (let index = 0; index < source.length; index += 1) {
      hash ^= source.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function deterministic3dPosition(node, index, count, group) {
    const center = group ? group.center : { x: 0, y: 0, z: 0 };
    if (index === 0) return { x: center.x, y: center.y, z: center.z };
    const hash = stable3dHash(node.id);
    const angle = index * 2.399963229728653;
    const radius = 29 + Math.sqrt(index) * 18;
    const depth = ((hash % 1000) / 1000 - 0.5) * Math.min(110, 35 + count * 2);
    return { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius * .72, z: center.z + depth };
  }

  function bounded3dGraph(graph) {
    const boundedNodes = graph.nodes
      .slice()
      .sort(function (left, right) {
        if (left.id === state.rootId) return -1;
        if (right.id === state.rootId) return 1;
        const selected = edgeByKey.get(state.selectedEdgeKey);
        if (selected) {
          const leftEndpoint = left.id === selected.source || left.id === selected.target;
          const rightEndpoint = right.id === selected.source || right.id === selected.target;
          if (leftEndpoint !== rightEndpoint) return leftEndpoint ? -1 : 1;
        }
        return left.id.localeCompare(right.id);
      })
      .slice(0, MAX_3D_VISIBLE_NODES);
    const included = new Set(boundedNodes.map(function (node) { return node.id; }));
    const boundedEdges = graph.edges
      .filter(function (edge) { return included.has(edge.source) && included.has(edge.target); })
      .slice()
      .sort(function (left, right) { return left.key.localeCompare(right.key); })
      .slice(0, MAX_3D_VISIBLE_EDGES);
    return { nodes: boundedNodes, edges: boundedEdges, truncated: graph.truncated || boundedNodes.length < graph.nodes.length || boundedEdges.length < graph.edges.length };
  }

  function syncGraphTextSelection() {
    dom.graphTextNodes.querySelectorAll("[data-node-id]").forEach(function (button) {
      const selected = button.dataset.nodeId === state.selectedId && !state.selectedEdgeKey;
      button.classList.toggle("is-selected", selected);
      if (selected) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
      if (selected) {
        const group = button.closest("details");
        if (group) group.open = true;
      }
    });
    dom.graphTextEdges.querySelectorAll("[data-edge-key]").forEach(function (button) {
      const selected = button.dataset.edgeKey === state.selectedEdgeKey;
      button.classList.toggle("is-selected", selected);
      if (selected) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
      if (selected) {
        const group = button.closest("details");
        if (group) group.open = true;
      }
    });
  }

  function renderGraphTextAlternative(graph) {
    const bounded = bounded3dGraph(graph);
    dom.graphTextSummary.textContent =
      "현재 이웃: 노드 " + formatCount(bounded.nodes.length) + "개, 관계 " +
      formatCount(bounded.edges.length) + "개." +
      (bounded.truncated ? " 표시 한도가 적용되었습니다." : "");
    const nodeGroups = new Map();
    bounded.nodes.forEach(function (node) {
      const label = typeLabel(node.type);
      if (!nodeGroups.has(label)) nodeGroups.set(label, []);
      nodeGroups.get(label).push(node);
    });
    const nodeFragment = document.createDocumentFragment();
    Array.from(nodeGroups.entries()).sort(function (left, right) {
      return left[0].localeCompare(right[0], "ko");
    }).forEach(function (entry) {
      const groupItem = make("div", "graph-text-group-item");
      groupItem.setAttribute("role", "listitem");
      const group = make("details", "graph-text-group");
      group.open = entry[1].some(function (node) { return node.id === state.selectedId && !state.selectedEdgeKey; });
      group.appendChild(make("summary", "", entry[0] + " · " + formatCount(entry[1].length)));
      const list = make("div", "graph-text-list-inner");
      list.setAttribute("role", "list");
      entry[1].forEach(function (node) {
        const item = make("div", "graph-text-item");
        item.setAttribute("role", "listitem");
        const button = make(
          "button",
          "graph-text-button" + (node.id === state.selectedId && !state.selectedEdgeKey ? " is-selected" : ""),
          node.name + " · " + typeLabel(node.type)
        );
        button.type = "button";
        button.dataset.nodeId = node.id;
        if (node.id === state.selectedId && !state.selectedEdgeKey) button.setAttribute("aria-current", "true");
        button.addEventListener("click", function () { selectNode(node.id, false); });
        item.appendChild(button);
        list.appendChild(item);
      });
      append(group, list);
      groupItem.appendChild(group);
      nodeFragment.appendChild(groupItem);
    });
    dom.graphTextNodes.replaceChildren(nodeFragment);
    const edgeGroups = new Map();
    bounded.edges.forEach(function (edge) {
      const label = relationLabel(edge.type);
      if (!edgeGroups.has(label)) edgeGroups.set(label, []);
      edgeGroups.get(label).push(edge);
    });
    const edgeFragment = document.createDocumentFragment();
    Array.from(edgeGroups.entries()).sort(function (left, right) {
      return left[0].localeCompare(right[0], "ko");
    }).forEach(function (entry) {
      const groupItem = make("div", "graph-text-group-item");
      groupItem.setAttribute("role", "listitem");
      const group = make("details", "graph-text-group");
      group.open = entry[1].some(function (edge) { return edge.key === state.selectedEdgeKey; });
      group.appendChild(make("summary", "", entry[0] + " · " + formatCount(entry[1].length)));
      const list = make("div", "graph-text-list-inner");
      list.setAttribute("role", "list");
      entry[1].forEach(function (edge) {
        const source = nodeById.get(edge.source);
        const target = nodeById.get(edge.target);
        const item = make("div", "graph-text-item");
        item.setAttribute("role", "listitem");
        const button = make(
          "button",
          "graph-text-button" + (edge.key === state.selectedEdgeKey ? " is-selected" : ""),
          (source ? source.name : edge.source) + " → " +
            (target ? target.name : edge.target) + " · " + relationLabel(edge.type)
        );
        button.type = "button";
        button.dataset.edgeKey = edge.key;
        if (edge.key === state.selectedEdgeKey) button.setAttribute("aria-current", "true");
        button.addEventListener("click", function () {
          rememberSelection();
          state.selectedEdgeKey = edge.key;
          renderEdgeDetails(edge);
          if (state.cy) {
            state.cy.elements().unselect();
            const edgeId = state.renderedEdgeIdByKey.get(edge.key);
            const element = edgeId ? state.cy.getElementById(edgeId) : null;
            if (element && element.length) element.select();
          }
          syncGraphTextSelection();
          if (state.viewMode === "3d" && state.threeDGraph) draw3dScene(0);
          announce(relationLabel(edge.type) + " 관계 증거 선택됨");
        });
        item.appendChild(button);
        list.appendChild(item);
      });
      append(group, list);
      groupItem.appendChild(group);
      edgeFragment.appendChild(groupItem);
    });
    dom.graphTextEdges.replaceChildren(edgeFragment);
  }

  function ensure3dContext() {
    if (state.threeDContext) return true;
    if (!dom.graph3dCanvas || typeof dom.graph3dCanvas.getContext !== "function") {
      state.threeDAvailable = false;
      return false;
    }
    try {
      state.threeDContext = dom.graph3dCanvas.getContext("2d", { alpha: true });
    } catch (error) {
      state.threeDContext = null;
    }
    state.threeDAvailable = Boolean(state.threeDContext);
    if (state.threeDAvailable) dom.graph3dCanvas.textContent = "";
    return state.threeDAvailable;
  }

  function stop3dFrame() {
    if (state.threeDFrame) window.cancelAnimationFrame(state.threeDFrame);
    state.threeDFrame = 0;
  }

  function resize3dCanvas() {
    const canvas = dom.graph3dCanvas;
    const ratio = Math.max(1, Math.min(2, finiteNumber(window.devicePixelRatio, 1)));
    const width = Math.max(1, Math.round(canvas.clientWidth * ratio));
    const height = Math.max(1, Math.round(canvas.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    return { width: width, height: height, ratio: ratio };
  }

  function project3d(position, viewport) {
    const x = position.x - state.camera.x;
    const y = position.y - state.camera.y;
    const z = position.z - state.camera.z;
    const yawCos = Math.cos(state.camera.yaw), yawSin = Math.sin(state.camera.yaw);
    const pitchCos = Math.cos(state.camera.pitch), pitchSin = Math.sin(state.camera.pitch);
    const yawX = x * yawCos - z * yawSin;
    const yawZ = x * yawSin + z * yawCos;
    const pitchY = y * pitchCos - yawZ * pitchSin;
    const pitchZ = y * pitchSin + yawZ * pitchCos;
    const perspective = state.camera.distance / Math.max(240, state.camera.distance + pitchZ);
    const baseScale = Math.max(.25, Math.min(1.8, (viewport.width / viewport.ratio) / 1100, (viewport.height / viewport.ratio) / 710));
    const scale = viewport.ratio * state.camera.zoom * perspective * baseScale;
    const offset = !dom.detailsPanel.hidden && viewport.width / viewport.ratio > 900 ? .39 : .5;
    return { x: viewport.width * offset + yawX * scale, y: viewport.height * .51 + pitchY * scale, z: pitchZ, scale: scale, perspective: perspective };
  }

  function nodeCanvasColor(node, forcedForeground) {
    if (forcedForeground) return forcedForeground;
    return ownValue(NODE_COLORS, node.language, node.type === "PolicyLeaf" ? "#f8c15c" : "#ff8790");
  }

  function draw3dScene(timestamp) {
    if (!state.threeDGraph || !ensure3dContext()) return false;
    const startedAt = window.performance && typeof window.performance.now === "function" ? window.performance.now() : Date.now();
    const context = state.threeDContext;
    const viewport = resize3dCanvas();
    const dpr = viewport.ratio;
    context.clearRect(0, 0, viewport.width, viewport.height);
    const forcedColors = window.matchMedia && window.matchMedia("(forced-colors: active)").matches;
    const forcedStyle = forcedColors && typeof window.getComputedStyle === "function" ? window.getComputedStyle(dom.graph3d) : null;
    const foreground = forcedStyle ? forcedStyle.color : "#daf8ff";
    const background = forcedStyle ? forcedStyle.backgroundColor : "#0a1725";
    const focusId = state.threeDHoverNodeId || state.selectedId;
    const connected = new Set(focusId ? [focusId] : []);
    if (focusId) state.threeDGraph.edges.forEach(function (edge) { if (edge.source === focusId) connected.add(edge.target); if (edge.target === focusId) connected.add(edge.source); });

    // Spatial reference rings are scenery, never additional ontology nodes or edges.
    if (!forcedColors) {
      const glow = context.createRadialGradient(viewport.width * .5, viewport.height * .51, 0, viewport.width * .5, viewport.height * .51, viewport.width * .46);
      glow.addColorStop(0, "rgba(56,151,185,.10)"); glow.addColorStop(1, "rgba(4,10,20,0)");
      context.fillStyle = glow; context.fillRect(0, 0, viewport.width, viewport.height);
      [270, 390, 515].forEach(function (radius, index) {
        context.beginPath();
        for (let step = 0; step <= 120; step += 1) {
          const theta = step / 120 * Math.PI * 2;
          const projected = project3d({ x: Math.cos(theta) * radius, y: 170 + index * 15, z: Math.sin(theta) * radius }, viewport);
          if (!step) context.moveTo(projected.x, projected.y); else context.lineTo(projected.x, projected.y);
        }
        context.strokeStyle = "rgba(108,181,214," + (.09 - index * .018) + ")";
        context.lineWidth = dpr * .7; context.stroke();
      });
    }

    const occupied = [];
    const compactLabels = viewport.width / dpr < 760;
    const moduleLabelLimit = compactLabels ? 6 : MAX_MODULE_GROUPS;
    const symbolLabelLimit = compactLabels ? 8 : 42;
    let moduleLabelsDrawn = 0;
    state.threeDGroups.slice().sort(function (a, b) {
      if (compactLabels) {
        const activeA = a.nodes.some(function (node) { return node.id === focusId; });
        const activeB = b.nodes.some(function (node) { return node.id === focusId; });
        return Number(activeB) - Number(activeA) || project3d(a.center, viewport).z - project3d(b.center, viewport).z || a.descriptor.key.localeCompare(b.descriptor.key);
      }
      return b.center.z - a.center.z;
    }).forEach(function (group) {
      const point = project3d(group.center, viewport);
      const radius = Math.max(26 * dpr, group.radius * point.scale);
      const active = group.nodes.some(function (node) { return node.id === focusId; });
      context.save();
      context.globalAlpha = focusId && !active ? .38 : 1;
      if (!forcedColors) {
        const halo = context.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius * 1.55);
        halo.addColorStop(0, group.color + (active ? "13" : "0a")); halo.addColorStop(1, group.color + "00");
        context.fillStyle = halo; context.fillRect(point.x - radius * 1.55, point.y - radius * 1.55, radius * 3.1, radius * 3.1);
      }
      context.beginPath();
      context.ellipse(point.x, point.y, radius * 1.14, radius * .80, -.10, 0, Math.PI * 2);
      context.strokeStyle = forcedColors ? foreground : group.color + (active ? "60" : "25");
      context.lineWidth = dpr * .8;
      context.setLineDash([3 * dpr, 7 * dpr]); context.stroke(); context.setLineDash([]);
      context.font = "500 " + (10 * dpr) + "px ui-monospace, SFMono-Regular, monospace";
      context.textAlign = "center";
      context.fillStyle = forcedColors ? foreground : group.color + "c9";
      const label = shortLabel(group.descriptor.label, compactLabels ? 20 : 37);
      const captionWidth = context.measureText(label).width + 12 * dpr;
      const captionY = point.y - radius * .88 - 14 * dpr;
      const captionBox = { x: point.x - captionWidth / 2, y: captionY - 11 * dpr, w: captionWidth, h: 29 * dpr };
      const overlaps = occupied.some(function (other) { return captionBox.x < other.x + other.w + 6 * dpr && captionBox.x + captionBox.w + 6 * dpr > other.x && captionBox.y < other.y + other.h + 6 * dpr && captionBox.y + captionBox.h + 6 * dpr > other.y; });
      const inViewport = captionBox.x >= 8 * dpr && captionBox.x + captionBox.w <= viewport.width - 8 * dpr && captionBox.y >= 130 * dpr && captionBox.y + captionBox.h <= viewport.height - 115 * dpr;
      if (!compactLabels || (moduleLabelsDrawn < moduleLabelLimit && !overlaps && inViewport)) {
        context.fillText(label, point.x, captionY);
        occupied.push(captionBox);
        moduleLabelsDrawn += 1;
        context.font = (8 * dpr) + "px system-ui, sans-serif";
        context.fillStyle = forcedColors ? foreground : "#7599ad";
        context.fillText(group.descriptor.kind + " · " + group.nodes.length, point.x, captionY + 13 * dpr);
      }
      context.restore();
    });

    state.threeDProjectedNodes = state.threeDGraph.nodes.map(function (node, index) {
      const position = state.threeDPositions.get(node.id) || deterministic3dPosition(node, index, state.threeDGraph.nodes.length);
      return Object.assign({ node: node }, project3d(position, viewport));
    });
    const projectedById = new Map(state.threeDProjectedNodes.map(function (item) { return [item.node.id, item]; }));
    state.threeDProjectedEdges = state.threeDGraph.edges.map(function (edge) { return { edge: edge, source: projectedById.get(edge.source), target: projectedById.get(edge.target) }; }).filter(function (item) { return item.source && item.target; });
    state.threeDProjectedEdges.sort(function (a, b) { return (b.source.z + b.target.z) - (a.source.z + a.target.z); });
    state.threeDProjectedEdges.forEach(function (item) {
      const selected = item.edge.key === state.selectedEdgeKey || item.edge.key === state.threeDHoverEdgeKey;
      const adjacent = item.edge.source === focusId || item.edge.target === focusId;
      const alpha = selected ? 1 : focusId ? adjacent ? .70 : .065 : .23;
      const group = state.groupByNodeId.get(item.edge.source);
      const color = group ? group.color : "#8fcbeb";
      context.save();
      context.globalAlpha = forcedColors ? 1 : alpha;
      context.strokeStyle = forcedColors ? foreground : selected ? "#b0fff1" : color;
      context.lineWidth = (selected ? 2.3 : adjacent ? 1.5 : .75) * dpr;
      if (selected && !forcedColors) { context.shadowColor = color; context.shadowBlur = 9 * dpr; }
      const dx = item.target.x - item.source.x, dy = item.target.y - item.source.y;
      const length = Math.max(1, Math.hypot(dx, dy));
      const curve = Math.min(18 * dpr, length * .055);
      item.control = { x: (item.source.x + item.target.x) / 2 - dy / length * curve, y: (item.source.y + item.target.y) / 2 + dx / length * curve };
      context.beginPath(); context.moveTo(item.source.x, item.source.y); context.quadraticCurveTo(item.control.x, item.control.y, item.target.x, item.target.y); context.stroke();
      if (selected || adjacent || state.threeDGraph.edges.length < 55) {
        const t = .78;
        const ax = (1-t)*(1-t)*item.source.x + 2*(1-t)*t*item.control.x + t*t*item.target.x;
        const ay = (1-t)*(1-t)*item.source.y + 2*(1-t)*t*item.control.y + t*t*item.target.y;
        const angle = Math.atan2(item.target.y-item.control.y, item.target.x-item.control.x);
        const size = (selected ? 5 : 3) * dpr;
        context.beginPath(); context.moveTo(ax,ay); context.lineTo(ax-Math.cos(angle-.42)*size,ay-Math.sin(angle-.42)*size); context.lineTo(ax-Math.cos(angle+.42)*size,ay-Math.sin(angle+.42)*size); context.closePath(); context.fillStyle=context.strokeStyle; context.fill();
      }
      if (selected) {
        context.font = "500 " + 10*dpr + "px system-ui, sans-serif"; context.textAlign="center";
        const caption=relationLabel(item.edge.type); const measured=context.measureText(caption).width;
        context.fillStyle=background; context.fillRect(item.control.x-measured/2-5*dpr,item.control.y-13*dpr,measured+10*dpr,18*dpr);
        context.fillStyle=foreground; context.fillText(caption,item.control.x,item.control.y);
      }
      context.restore();
    });

    const focusedNode = state.threeDGraph.nodes[state.threeDFocusedIndex];
    state.threeDProjectedNodes.sort(function (a, b) { return b.z - a.z; });
    state.threeDProjectedNodes.forEach(function (item) {
      const group = state.groupByNodeId.get(item.node.id);
      const anchor = group && group.nodes[0].id === item.node.id;
      const selected = item.node.id === state.selectedId;
      const hovered = item.node.id === state.threeDHoverNodeId;
      const focused = document.activeElement === dom.graph3dCanvas && focusedNode && focusedNode.id === item.node.id;
      const color = forcedColors ? foreground : group ? group.color : "#91dce7";
      const emphasis = selected || hovered || focused;
      const radius = Math.max(3.4 * dpr, Math.min(13*dpr, (anchor ? 8 : 4.7) * item.scale));
      context.save();
      context.globalAlpha = forcedColors ? 1 : focusId && !connected.has(item.node.id) ? .25 : Math.max(.45, Math.min(1,item.perspective));
      if (!forcedColors) { context.shadowColor=color; context.shadowBlur=(emphasis?22:anchor?12:6)*dpr; }
      if (emphasis) {
        context.beginPath(); context.arc(item.x,item.y,radius+7*dpr,0,Math.PI*2); context.strokeStyle=color; context.lineWidth=dpr; context.stroke();
        context.beginPath(); context.arc(item.x,item.y,radius+12*dpr,-.7,.5); context.arc(item.x,item.y,radius+12*dpr,2.5,3.6); context.strokeStyle=forcedColors?foreground:color+"80"; context.stroke();
      }
      context.beginPath();
      if (anchor || ["PolicyLeaf","RuntimeBranch"].includes(item.node.type)) {
        const sides=anchor?6:4;
        for(let vertex=0;vertex<sides;vertex+=1){ const theta=vertex/sides*Math.PI*2-Math.PI/2; const x=item.x+Math.cos(theta)*radius,y=item.y+Math.sin(theta)*radius; if(!vertex)context.moveTo(x,y);else context.lineTo(x,y); }
        context.closePath();
      } else context.arc(item.x,item.y,radius,0,Math.PI*2);
      if (!forcedColors) {
        const sphere=context.createRadialGradient(item.x-radius*.3,item.y-radius*.4,0,item.x,item.y,radius);
        sphere.addColorStop(0,"#e4ffff"); sphere.addColorStop(.32,color); sphere.addColorStop(1,color+"64"); context.fillStyle=sphere;
      } else context.fillStyle=foreground;
      context.fill(); context.lineWidth=(emphasis?1.7:.7)*dpr; context.strokeStyle=forcedColors?background:color+"db"; context.stroke(); context.restore();
      item.hitRadius=Math.max(12*dpr,radius+5*dpr);
      item.labelPriority=emphasis?0:anchor?1:connected.has(item.node.id)?2:3;
    });
    // Labels retain deterministic priority and never overlap one another.
    state.threeDProjectedNodes.slice().sort(function(a,b){return a.labelPriority-b.labelPriority || a.z-b.z || a.node.id.localeCompare(b.node.id);}).forEach(function(item,index){
      if(index>=symbolLabelLimit && item.labelPriority>0)return;
      if(state.threeDGraph.nodes.length>55 && item.labelPriority===3)return;
      const caption=shortLabel(item.node.name,compactLabels?(item.labelPriority===0?28:18):(item.labelPriority===0?44:28));
      const fontSize=(item.labelPriority===0?12:10)*dpr;
      context.font=(item.labelPriority===0?"600 ":"400 ")+fontSize+"px system-ui, sans-serif";
      const width=context.measureText(caption).width+12*dpr;
      const x=item.x-width/2,y=item.y+item.hitRadius+5*dpr;
      const box={x:x,y:y-10*dpr,w:width,h:18*dpr};
      if(x<8*dpr||x+width>viewport.width-8*dpr||y>viewport.height-90*dpr)return;
      if(item.labelPriority>0&&occupied.some(function(other){return box.x<other.x+other.w&&box.x+box.w>other.x&&box.y<other.y+other.h&&box.y+box.h>other.y;}))return;
      occupied.push(box);
      context.fillStyle=forcedColors?background:"rgba(6,17,29,.86)"; context.fillRect(box.x,box.y,box.w,box.h);
      context.fillStyle=forcedColors?foreground:item.labelPriority===0?"#e4fffa":item.labelPriority===3?"#86a5b7":"#b8d2e0";
      context.textAlign="center"; context.fillText(caption,item.x,y+2*dpr);
    });
    state.threeDLastRenderMs=Math.max(0,(window.performance&&typeof window.performance.now==="function"?window.performance.now():Date.now())-startedAt);
    const statusText=state.threeDGroups.length+"개 모듈 / 폴더 · "+state.threeDGraph.nodes.length+"개 심볼";
    if(dom.graph3dStatus.textContent!==statusText)dom.graph3dStatus.textContent=statusText;
    const summary=statusText+", 관계 "+state.threeDGraph.edges.length+"개. "+(focusedNode?"키보드 초점: "+focusedNode.name+". ":"")+"목록 보기에서 같은 항목을 선택할 수 있습니다.";
    if(dom.graph3dSummary.textContent!==summary)dom.graph3dSummary.textContent=summary;
    return true;
  }

  function schedule3dFrame() {
    stop3dFrame();
    if (state.viewMode !== "3d" || document.visibilityState === "hidden" || dom.graphView.hidden || state.activeLens === "changes") return;
    state.threeDFrame = window.requestAnimationFrame(function tick(timestamp) {
      state.threeDFrame = 0;
      if (state.viewMode !== "3d" || document.visibilityState === "hidden" || dom.graphView.hidden || state.activeLens === "changes") return;
      const frameInterval = state.threeDLastRenderMs > THREE_D_FRAME_BUDGET_MS ? THREE_D_SLOW_FRAME_INTERVAL_MS : THREE_D_FRAME_INTERVAL_MS;
      const elapsed = timestamp - state.threeDLastFrameAt;
      if (elapsed >= frameInterval) {
        if (state.cameraTransition) {
          const transition = state.cameraTransition;
          if (!transition.startedAt) transition.startedAt = timestamp;
          const fraction = Math.min(1, (timestamp - transition.startedAt) / 540);
          const eased = 1 - Math.pow(1 - fraction, 3);
          ["x", "y", "z", "zoom"].forEach(function (key) { state.camera[key] = transition.from[key] + (transition.to[key] - transition.from[key]) * eased; });
          if (fraction >= 1) state.cameraTransition = null;
        } else if (state.motionEnabled && !state.threeDDragging && !state.threeDHoverNodeId ) state.camera.yaw += .000045 * Math.min(66, elapsed || 16);
        state.threeDLastFrameAt = timestamp;
        draw3dScene(timestamp);
      }
      if (state.cameraTransition || state.motionEnabled) state.threeDFrame = window.requestAnimationFrame(tick);
    });
  }

  function focus3dCamera(nodeId) {
    const position = state.threeDPositions.get(nodeId);
    if (!position || state.viewMode !== "3d") return;
    state.cameraFocusId = nodeId;
    const target = { x: position.x, y: position.y, z: position.z, zoom: Math.max(1.05, Math.min(1.4, state.camera.zoom)) };
    if (reducedMotionQuery.matches) { Object.assign(state.camera, target); state.cameraTransition = null; draw3dScene(0); }
    else { state.cameraTransition = { from: Object.assign({}, state.camera), to: target, startedAt: 0 }; schedule3dFrame(); }
  }

  function renderGraph3d(graph) {
    if (!ensure3dContext()) return false;
    state.threeDGraph = bounded3dGraph(graph);
    const signature = state.threeDGraph.nodes.map(function(node){return node.id;}).sort().join("\u0000");
    if (signature !== state.graphSignature) { state.graphSignature = signature; state.threeDPositions.clear(); buildModuleLayout(state.threeDGraph); }
    state.threeDFocusedIndex = Math.max(0, state.threeDGraph.nodes.findIndex(function (node) { return node.id === state.selectedId; }));
    draw3dScene(0);
    if (state.selectedId) focus3dCamera(state.selectedId); else schedule3dFrame();
    return true;
  }

  function updateMotionControl() {
    dom.motionToggle.setAttribute("aria-pressed", state.motionEnabled ? "true" : "false");
    dom.motionToggle.replaceChildren(make("span", "", state.motionEnabled ? "◌ 회전" : "◌ 정지"));
    dom.motionToggle.setAttribute("aria-label", "공간 회전 " + (state.motionEnabled ? "켜짐" : "꺼짐"));
  }

  function setViewMode(mode, message, rerender, silent) {
    const requested = mode === "3d" ? "3d" : "2d";
    if (requested === "3d" && !ensure3dContext()) {
      state.threeDAvailable = false;
      state.viewMode = "2d";
      message = "3D Canvas를 사용할 수 없어 2D 구조 보기로 돌아왔습니다.";
    } else {
      state.viewMode = requested;
    }
    const is3d = state.viewMode === "3d";
    dom.graphView.dataset.viewMode = state.viewMode;
    setHidden(dom.graph, is3d);
    setHidden(dom.graph3d, !is3d);
    dom.viewMode2d.classList.toggle("is-active", !is3d);
    dom.viewMode3d.classList.toggle("is-active", is3d);
    dom.viewMode2d.setAttribute("aria-pressed", is3d ? "false" : "true");
    dom.viewMode3d.setAttribute("aria-pressed", is3d ? "true" : "false");
    if (!is3d) stop3dFrame();
    if (rerender !== false && state.activeLens !== "overview" && state.activeLens !== "changes") renderGraph(false);
    if (!silent) announce(message || (is3d ? "3D 공간 보기로 전환했습니다." : "2D 구조 보기로 전환했습니다."));
  }

  function reset3dCamera() {
    state.camera = { yaw: -0.38, pitch: -0.16, zoom: 1, distance: 980, x: 0, y: 0, z: 0 };
    state.cameraTransition = null;
    draw3dScene(0);
    schedule3dFrame();
  }

  function hit3dNode(clientX, clientY) {
    const rect = dom.graph3dCanvas.getBoundingClientRect();
    const scaleX = dom.graph3dCanvas.width / Math.max(1, rect.width);
    const scaleY = dom.graph3dCanvas.height / Math.max(1, rect.height);
    const x = (clientX - rect.left) * scaleX;
    const y = (clientY - rect.top) * scaleY;
    let best = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    state.threeDProjectedNodes.forEach(function (item) {
      const distance = Math.hypot(item.x - x, item.y - y);
      if (distance <= item.hitRadius && distance < bestDistance) {
        best = item;
        bestDistance = distance;
      }
    });
    return best;
  }

  function hit3dEdge(clientX, clientY) {
    const rect = dom.graph3dCanvas.getBoundingClientRect();
    const ratio = dom.graph3dCanvas.width / Math.max(1, rect.width);
    const x = (clientX - rect.left) * ratio, y = (clientY - rect.top) * ratio;
    let best = null, bestDistance = 7 * ratio;
    state.threeDProjectedEdges.forEach(function (item) {
      if (!item.control) return;
      for (let step = 1; step < 16; step += 1) {
        const t = step / 16, u = 1 - t;
        const px = u*u*item.source.x + 2*u*t*item.control.x + t*t*item.target.x;
        const py = u*u*item.source.y + 2*u*t*item.control.y + t*t*item.target.y;
        const distance = Math.hypot(x-px,y-py);
        if (distance < bestDistance) { best = item.edge; bestDistance = distance; }
      }
    });
    return best;
  }

  function selectFocused3dNode() {
    if (!state.threeDGraph || !state.threeDGraph.nodes.length) return;
    const node = state.threeDGraph.nodes[state.threeDFocusedIndex];
    if (node) {
      selectNode(node.id, false);
      draw3dScene(0);
    }
  }

  function renderGraph(announceResult) {
    if (state.activeLens === "changes") return;
    if (!state.atlasOverview && (!state.rootId || !nodeById.has(state.rootId))) state.rootId = defaultSeed(state.activeLens);
    const graph = bounded3dGraph(
      state.atlasOverview && state.activeLens === "architecture" ? atlasGraph() : neighborhood(state.rootId, state.activeLens, state.depth, state.direction)
    );
    if (state.selectedEdgeKey && !graph.edges.some(function (edge) { return edge.key === state.selectedEdgeKey; })) {
      state.selectedEdgeKey = "";
      if (state.selectedId && nodeById.has(state.selectedId)) renderDetails(nodeById.get(state.selectedId));
    }
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
      "개 심볼 · " +
      formatCount(graph.edges.length) +
      "개 관계" +
      (state.atlasOverview ? "" : " · " + state.depth + "단계") +
      (graph.truncated
        ? " · 일부 표시 (전체 " + formatCount(nodes.length) + "개 심볼)"
        : "");

    renderGraphTextAlternative(graph);

    if (!graph.nodes.length) {
      stop3dFrame();
      state.threeDGraph = null;
      if (state.threeDContext) state.threeDContext.clearRect(0, 0, dom.graph3dCanvas.width, dom.graph3dCanvas.height);
      if (state.cy) state.cy.elements().remove();
      if (announceResult !== false) announce("표시할 관계가 없습니다.");
      return;
    }
    let fallbackAnnouncement = "";
    if (state.viewMode === "3d") {
      if (renderGraph3d(graph)) {
        if (announceResult !== false) announce("3D 노드 " + graph.nodes.length + "개와 관계 " + graph.edges.length + "개를 표시했습니다.");
        return;
      }
      fallbackAnnouncement = "3D Canvas를 사용할 수 없어 2D 구조 보기로 돌아왔습니다.";
      setViewMode("2d", fallbackAnnouncement, false, true);
    }
    if (!ensureCytoscape()) {
      setHidden(dom.graphEmpty, false);
      dom.graphEmpty.replaceChildren(
        make("strong", "", "그래프 엔진을 불러오지 못했습니다."),
        make("span", "", "검색 결과와 상세 패널로 전체 온톨로지를 계속 탐색할 수 있습니다.")
      );
      dom.graphNote.textContent = "Cytoscape를 사용할 수 없음";
      if (announceResult !== false) announce("그래프 엔진을 불러오지 못했습니다.");
      return;
    }

    state.cy.startBatch();
    state.cy.elements().remove();
    state.cy.add(graphElements(graph));
    state.cy.endBatch();
    const selectedEdgeId = state.renderedEdgeIdByKey.get(state.selectedEdgeKey);
    const selectedEdge = selectedEdgeId ? state.cy.getElementById(selectedEdgeId) : null;
    if (selectedEdge && selectedEdge.length) {
      selectedEdge.select();
    } else {
      if (state.selectedEdgeKey) {
        state.selectedEdgeKey = "";
        if (state.selectedId && nodeById.has(state.selectedId)) {
          renderDetails(nodeById.get(state.selectedId));
        }
      }
      const selected = state.cy.getElementById(state.selectedId);
      if (selected && selected.length) selected.select();
    }
    window.requestAnimationFrame(function () {
      if (!state.cy || token !== state.renderToken) return;
      state.cy.resize();
      layoutWithElk(graph, token);
    });
    if (announceResult !== false) {
      announce(fallbackAnnouncement || "노드 " + graph.nodes.length + "개와 관계 " + graph.edges.length + "개를 표시했습니다.");
    }
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
      make("strong", mode === "added" ? "change-added" : mode === "modified" ? "change-modified" : "change-removed", edgeDescription(edge)),
      make("span", "", relationLabel(text(edge.type)))
    );
    const source = text(edge.source);
    const target = text(edge.target);
    const available = nodeById.has(source) ? source : nodeById.has(target) ? target : "";
    button.addEventListener("click", function () {
      const key = source + "\u0000" + text(edge.type) + "\u0000" + target;
      const current = edgeByKey.get(key);
      if (mode !== "removed" && current && available) {
        switchLens("architecture", available);
        state.selectedEdgeKey = key;
        renderEdgeDetails(current);
        if (mode === "modified") {
          const previous = make("section", "details-section");
          previous.appendChild(make("h4", "", "이전 스냅샷 근거"));
          arrayOrEmpty(edge.previousEvidence).forEach(function (item) { previous.appendChild(renderEdgeEvidenceCard(item)); });
          if (!arrayOrEmpty(edge.previousEvidence).length) previous.appendChild(make("p", "details-subtitle", "이전 구조화된 근거 없음"));
          dom.detailsContent.appendChild(previous);
        }
        syncGraphTextSelection();
        draw3dScene(0);
      } else {
        setHidden(dom.detailsPanel, false);
        dom.detailsContent.replaceChildren(make("span", "relation-chip change-removed", "삭제된 관계"), make("h3", "", edgeDescription(edge)), make("p", "details-subtitle", relationLabel(text(edge.type)) + " · 이전 스냅샷"));
        arrayOrEmpty(edge.evidence).forEach(function (item) { dom.detailsContent.appendChild(renderEdgeEvidenceCard(item)); });
      }
    });
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
        make("p", "view-description", "다음 스냅샷에서 심볼과 관계의 추가·수정·삭제를 비교합니다.")
      );
      dom.changesView.replaceChildren(card);
      return;
    }
    const summary = make("div", "change-summary");
    summary.appendChild(metricCard("추가 심볼", formatCount(changeCount("nodesAdded")), "현재 스냅샷에 새로 등장"));
    summary.appendChild(metricCard("삭제 심볼", formatCount(changeCount("nodesRemoved")), "이전 스냅샷에서 사라짐"));
    summary.appendChild(metricCard("수정 심볼", formatCount(changeCount("nodesModified")), "같은 ID의 속성이 변경됨"));
    summary.appendChild(metricCard("추가 관계", formatCount(changeCount("edgesAdded")), "새로운 정적 연결"));
    summary.appendChild(metricCard("삭제 관계", formatCount(changeCount("edgesRemoved")), ""));
    summary.appendChild(metricCard("근거 변경", formatCount(changeCount("edgesModified")), "같은 관계의 근거 변경"));
    const context = make("article", "surface-card change-context");
    append(
      context,
      make("div", "section-kicker", text(changes.basis, "정적 구조 비교")),
      make("h3", "", shortLabel(text(changes.beforeSnapshotId, "이전") + " → " + text(changes.afterSnapshotId, "현재"), 110)),
      make(
        "p",
        "view-description",
        "정적 스냅샷 비교" + (changes.truncated ? " · 목록 일부 표시" : "")
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
      changeList("삭제된 관계", arrayOrEmpty(changes.edgesRemoved), "removed", "edge"),
      changeList("근거가 바뀐 관계", arrayOrEmpty(changes.edgesModified), "modified", "edge")
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

  function switchLens(lens, preferredRoot, preserveState) {
    lens = LENS_ALIASES[lens] || lens;
    if (!LENS_COPY[lens]) return;
    if (!preserveState && (lens !== state.activeLens || preferredRoot)) rememberSelection();
    const changedLens = state.activeLens !== lens;
    state.activeLens = lens;
    updateLensButtons(lens);
    setHidden(dom.overviewView, true);
    dom.qualityToggle.setAttribute("aria-expanded", "false");
    setHidden(dom.searchPanel, true);
    dom.searchInput.setAttribute("aria-expanded", "false");
    const graphMode = lens !== "changes";
    if (!graphMode) { state.renderToken += 1; stop3dFrame(); setHidden(dom.detailsPanel, true); }
    setHidden(dom.graphView, !graphMode);
    setHidden(dom.changesView, graphMode);
    setHidden(dom.graphToolbar, !graphMode);
    setHidden(dom.graphTextAlternative, !graphMode);
    if (lens === "changes") renderChanges();
    if (preferredRoot && nodeById.has(preferredRoot)) {
      state.rootId = preferredRoot; state.selectedId = preferredRoot; state.selectedEdgeKey = ""; state.selectedEvidenceId = ""; state.atlasOverview = false;
    } else if (lens === "architecture" && changedLens && !preserveState) {
      state.atlasOverview = true; state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = ""; setHidden(dom.detailsPanel, true); reset3dCamera();
    }
    if (lens === "impact") {
      state.atlasOverview = false;
      if (changedLens && !preserveState) { state.direction = "incoming"; dom.directionSelect.value = "incoming"; }
      if (!state.rootId || !nodeById.has(state.rootId)) state.rootId = state.selectedId || defaultSeed("impact");
      if (!state.selectedId) state.selectedId = state.rootId;
    }
    if (graphMode) {
      if (state.selectedId && preferredRoot) renderDetails(nodeById.get(state.selectedId));
      renderSearchResults();
      window.requestAnimationFrame(function () { renderGraph(); });
    }
    updateViewHeading();
    updateSelectionLink();
    announce(LENS_COPY[lens].title + " 보기");
  }

  function initializeMeta() {
    const repositoryName = text(meta.repositoryName, "이름 없는 저장소");
    dom.repositoryName.textContent = repositoryName;
    dom.repositoryName.title = repositoryName;
    dom.snapshotBadge.textContent = meta.generatedAt ? formatDate(meta.generatedAt) : "스냅샷";
    dom.snapshotBadge.title = "생성: " + formatDate(meta.generatedAt) + " · 생성기 " + text(meta.generatorVersion, "unknown");
    dom.evidenceBadge.textContent = "정적 소스";
    const warningCount = finiteNumber(statistics.warnings, warnings.length);
    dom.warningBadge.textContent = warningCount ? "분석 경고 " + formatCount(warningCount) : "분석 정보";
    dom.warningBadge.classList.toggle("status-badge--warning", warningCount > 0);
    dom.copyLink.disabled = !meta.snapshotId;
    document.title = "Code Ontology — " + repositoryName;
  }

  function bindEvents() {
    dom.viewBack.addEventListener("click", goBack);
    dom.closeDetails.addEventListener("click", function () { setHidden(dom.detailsPanel, true); dom.graph3dCanvas.focus(); draw3dScene(0); });
    dom.closeSearch.addEventListener("click", function () { setHidden(dom.searchPanel, true); dom.searchInput.setAttribute("aria-expanded", "false"); dom.graph3dCanvas.focus(); });
    dom.searchInput.addEventListener("focus", function () { setHidden(dom.searchPanel, false); dom.searchInput.setAttribute("aria-expanded", "true"); });
    dom.qualityToggle.addEventListener("click", function () { const show = dom.overviewView.hidden; setHidden(dom.overviewView, !show); dom.qualityToggle.setAttribute("aria-expanded", show ? "true" : "false"); });
    dom.qualityClose.addEventListener("click", function () { setHidden(dom.overviewView, true); dom.qualityToggle.setAttribute("aria-expanded", "false"); dom.qualityToggle.focus(); });
    dom.copyLink.addEventListener("click", function () {
      let field = dom.detailsPanel.querySelector(".selection-link");
      if (!field) { field = make("input", "selection-link"); field.type = "text"; field.readOnly = true; field.setAttribute("aria-label", "현재 선택의 스냅샷 링크"); dom.detailsPanel.appendChild(field); }
      field.value = selectionUrl().href; field.focus(); field.select(); announce("현재 선택 링크를 복사할 수 있습니다.");
    });

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
      setHidden(dom.searchPanel, false); dom.searchInput.setAttribute("aria-expanded", "true");
      runSearch();
    });
    dom.searchInput.addEventListener("keydown", function (event) {
      const visibleCount = Math.min(state.searchMatches.length, state.searchVisibleLimit);
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
          setHidden(dom.searchPanel, true); dom.searchInput.setAttribute("aria-expanded", "false"); dom.searchInput.blur();
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
      updateViewHeading();
      renderGraph();
    });
    dom.viewMode2d.addEventListener("click", function () {
      setViewMode("2d");
    });
    dom.viewMode3d.addEventListener("click", function () {
      setViewMode("3d");
    });
    dom.motionToggle.addEventListener("click", function () {
      state.motionEnabled = !state.motionEnabled;
      updateMotionControl();
      draw3dScene(0);
      schedule3dFrame();
      announce(state.motionEnabled ? "3D 자동 움직임을 켰습니다." : "3D 자동 움직임을 멈췄습니다.");
    });
    dom.zoomIn.addEventListener("click", function () {
      if (state.viewMode === "3d") {
        state.camera.zoom = Math.min(2.4, state.camera.zoom * 1.16);
        draw3dScene(0);
      } else if (state.cy) {
        state.cy.zoom({ level: Math.min(state.cy.maxZoom(), state.cy.zoom() * 1.2), renderedPosition: { x: dom.graph.clientWidth / 2, y: dom.graph.clientHeight / 2 } });
      }
    });
    dom.zoomOut.addEventListener("click", function () {
      if (state.viewMode === "3d") {
        state.camera.zoom = Math.max(0.35, state.camera.zoom / 1.16);
        draw3dScene(0);
      } else if (state.cy) {
        state.cy.zoom({ level: Math.max(state.cy.minZoom(), state.cy.zoom() / 1.2), renderedPosition: { x: dom.graph.clientWidth / 2, y: dom.graph.clientHeight / 2 } });
      }
    });
    dom.fitGraph.addEventListener("click", function () {
      if (state.viewMode === "3d") reset3dCamera();
      else if (state.cy) state.cy.fit(state.cy.elements(), 46);
    });
    dom.resetView.addEventListener("click", function () {
      rememberSelection();
      state.depth = 2; state.direction = "both"; dom.depthSelect.value = "2"; dom.directionSelect.value = "both";
      state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = ""; state.atlasOverview = true;
      setHidden(dom.detailsPanel, true); reset3dCamera(); switchLens("architecture", "", true);
    });
    dom.graph3dCanvas.addEventListener("pointerdown", function (event) {
      state.cameraTransition = null;
      state.threeDDragging = true;
      state.threeDDragDistance = 0;
      state.threeDPointer = { x: event.clientX, y: event.clientY };
      dom.graph3dCanvas.classList.add("is-dragging");
      if (typeof dom.graph3dCanvas.setPointerCapture === "function") {
        try { dom.graph3dCanvas.setPointerCapture(event.pointerId); } catch (error) { /* ignored */ }
      }
    });
    dom.graph3dCanvas.addEventListener("pointermove", function (event) {
      if (!state.threeDDragging) {
        const hovered = hit3dNode(event.clientX, event.clientY);
        state.threeDHoverNodeId = hovered ? hovered.node.id : "";
        const hoveredEdge = hovered ? null : hit3dEdge(event.clientX, event.clientY);
        state.threeDHoverEdgeKey = hoveredEdge ? hoveredEdge.key : "";
        dom.graph3dCanvas.style.cursor = hovered || hoveredEdge ? "pointer" : "grab";
        draw3dScene(0);
        return;
      }
      const dx = event.clientX - state.threeDPointer.x;
      const dy = event.clientY - state.threeDPointer.y;
      state.threeDDragDistance += Math.abs(dx) + Math.abs(dy);
      state.camera.yaw += dx * 0.005;
      state.camera.pitch = Math.max(-1.35, Math.min(1.35, state.camera.pitch + dy * 0.005));
      state.threeDPointer = { x: event.clientX, y: event.clientY };
      draw3dScene(0);
    });
    function end3dPointer(event, cancelled) {
      if (!state.threeDDragging) return;
      state.threeDDragging = false;
      dom.graph3dCanvas.classList.remove("is-dragging");
      if (!cancelled && state.threeDDragDistance < 8) {
        const hit = hit3dNode(event.clientX, event.clientY);
        if (hit) {
          const index = state.threeDGraph.nodes.findIndex(function (node) { return node.id === hit.node.id; });
          state.threeDFocusedIndex = Math.max(0, index);
          selectFocused3dNode();
        } else {
          const edge = hit3dEdge(event.clientX, event.clientY);
          if (edge) { rememberSelection(); state.selectedEdgeKey = edge.key; state.selectedEvidenceId = ""; if (!state.selectedId || (state.selectedId !== edge.source && state.selectedId !== edge.target)) state.selectedId = edge.source; renderEdgeDetails(edge); syncGraphTextSelection(); draw3dScene(0); }
        }
      }
      schedule3dFrame();
    }
    dom.graph3dCanvas.addEventListener("pointerleave", function () { state.threeDHoverNodeId = ""; state.threeDHoverEdgeKey = ""; draw3dScene(0); });
    dom.graph3dCanvas.addEventListener("pointerup", function (event) { end3dPointer(event, false); });
    dom.graph3dCanvas.addEventListener("pointercancel", function (event) { end3dPointer(event, true); });
    dom.graph3dCanvas.addEventListener("wheel", function (event) {
      event.preventDefault();
      state.cameraTransition = null;
      state.camera.zoom = Math.max(0.35, Math.min(2.4, state.camera.zoom * (event.deltaY > 0 ? 0.9 : 1.1)));
      draw3dScene(0);
    }, { passive: false });
    dom.graph3dCanvas.addEventListener("keydown", function (event) {
      if (!state.threeDGraph || !state.threeDGraph.nodes.length) return;
      let handled = true;
      if (event.key === "ArrowLeft") state.camera.yaw -= 0.12;
      else if (event.key === "ArrowRight") state.camera.yaw += 0.12;
      else if (event.key === "ArrowUp") state.threeDFocusedIndex = (state.threeDFocusedIndex - 1 + state.threeDGraph.nodes.length) % state.threeDGraph.nodes.length;
      else if (event.key === "ArrowDown") state.threeDFocusedIndex = (state.threeDFocusedIndex + 1) % state.threeDGraph.nodes.length;
      else if (event.key === "Home" || event.key === "0" || event.key.toLowerCase() === "f") reset3dCamera();
      else if (event.key === "Enter" || event.key === " ") selectFocused3dNode();
      else if (event.key === "Escape") {
        if (state.selectionHistory.length) goBack(); else setHidden(dom.detailsPanel, true);
      } else if (event.key === "+" || event.key === "=") state.camera.zoom = Math.min(2.4, state.camera.zoom * 1.16);
      else if (event.key === "-" || event.key === "_") state.camera.zoom = Math.max(0.35, state.camera.zoom / 1.16);
      else handled = false;
      if (handled) {
        event.preventDefault();
        const focused = state.threeDGraph.nodes[state.threeDFocusedIndex];
        if (focused && ["ArrowUp", "ArrowDown"].includes(event.key)) announce(focused.name + "에 키보드 초점");
        draw3dScene(0);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || (!event.metaKey && !event.ctrlKey) || event.altKey) return;
      const target = event.target;
      const editing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (!editing) {
        event.preventDefault();
        dom.searchInput.focus();
        dom.searchInput.select();
      }
    });
    window.addEventListener("resize", function () {
      if (state.viewMode === "3d") draw3dScene(0);
      if (state.cy && !dom.graphView.hidden) {
        state.cy.resize();
        state.cy.fit(state.cy.elements(), 46);
      }
    });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") stop3dFrame();
      else if (
        state.viewMode === "3d" &&
        !dom.graphView.hidden &&
        state.activeLens !== "overview" &&
        state.activeLens !== "changes"
      ) schedule3dFrame();
    });
    if (typeof reducedMotionQuery.addEventListener === "function") {
      reducedMotionQuery.addEventListener("change", function (event) {
        if (event.matches) { state.motionEnabled = false; if (state.cameraTransition) Object.assign(state.camera, state.cameraTransition.to); state.cameraTransition = null; }
        updateMotionControl();
        draw3dScene(0);
        schedule3dFrame();
      });
    }
  }

  const initialSelection = readSelectionLink();
  state.restoringSelection = true;
  initializeMeta();
  renderQualityPanel();
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
  updateMotionControl();
  bindEvents();
  runSearch();
  setViewMode("3d", "", false, true);
  switchLens(initialSelection ? initialSelection.lens : "architecture", initialSelection ? initialSelection.entity : "", true);
  if (initialSelection && initialSelection.edge) {
    state.selectedEdgeKey = initialSelection.edge.key;
    state.selectedEvidenceId = initialSelection.evidenceId;
    renderEdgeDetails(initialSelection.edge);
  }
  state.restoringSelection = false;
})();
