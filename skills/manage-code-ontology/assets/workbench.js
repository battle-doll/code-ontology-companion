(function () {
  "use strict";

  const HARD_MAX_VISIBLE_NODES = 250;
  const MAX_3D_VISIBLE_NODES = 160;
  const MAX_3D_VISIBLE_EDGES = 480;
  const THREE_D_FRAME_BUDGET_MS = 20;
  const THREE_D_FRAME_INTERVAL_MS = 33;
  const THREE_D_SLOW_FRAME_INTERVAL_MS = 66;
  const MAX_SEARCH_RESULTS = 80;
  const MAX_MODULE_LABELS = 12;
  const ATLAS_PAGE_SIZE = 160;
  const RELATION_PAGE_SIZE = 80;
  const MAX_DETAIL_NEIGHBORS = 18;
  const CALL_HOP_COLORS = ["", "#80ffe0", "#ffd17a", "#c7a0ff"];
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
    AtlasGroup: "모듈 / 폴더 집계",
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
    AGGREGATED: "모듈 간 관계 집계",
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
    policy: { eyebrow: "POLICY SOURCE", title: "정책 · 분기", description: "정적 정책 · 조건 분기 관계" },
    pipeline: { eyebrow: "PIPELINE SOURCE", title: "호출 · 파이프라인", description: "정적 호출 · 역할 관계" },
    spring: { eyebrow: "FRAMEWORK SOURCE", title: "프레임워크", description: "정적 프레임워크 관계" },
    changes: { eyebrow: "SNAPSHOT DIFF", title: "변경", description: "" },
  };
  const LENS_ALIASES = { overview: "architecture", explore: "architecture" };
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
    displayDepth: document.getElementById("display-depth"),
    hoverDepth: document.getElementById("hover-depth"),
    layerNext: document.getElementById("atlas-layer-next"),
    layerPrevious: document.getElementById("atlas-layer-previous"),
    layerSummary: document.getElementById("atlas-layer-summary"),
    callTraceSummary: document.getElementById("call-trace-summary"),
    atlasBrowser: document.getElementById("atlas-browser"),
    atlasBrowserSummary: document.getElementById("atlas-browser-summary"),
    atlasBrowserClose: document.getElementById("atlas-browser-close"),
    atlasSettings: document.getElementById("atlas-settings"),
    atlasSettingsSummary: document.getElementById("atlas-settings-summary"),
    atlasSettingsClose: document.getElementById("atlas-settings-close"),
    mapHelp: document.getElementById("map-help"),
    mapHelpSummary: document.getElementById("map-help-summary"),
    mapHelpClose: document.getElementById("map-help-close"),
    startGuide: document.getElementById("start-guide"),
    relationList: document.getElementById("relation-list"),
    relationSummary: document.getElementById("relation-summary"),
    relationPrevious: document.getElementById("relation-previous"),
    relationNext: document.getElementById("relation-next"),
    edgePrevious: document.getElementById("edge-previous"),
    edgeNext: document.getElementById("edge-next"),
    edgePageSummary: document.getElementById("edge-page-summary"),
    sourceRoots: document.getElementById("source-roots"),
    atlasControls: document.getElementById("atlas-controls"),
    sourceScope: document.getElementById("source-scope"),
    relationFilter: document.getElementById("relation-filter"),
    categoryFilter: document.getElementById("category-filter"),
    groupSearch: document.getElementById("group-search"),
    groupSummary: document.getElementById("group-summary"),
    groupList: document.getElementById("group-list"),
    groupPrevious: document.getElementById("group-previous"),
    groupNext: document.getElementById("group-next"),
    atlasBreadcrumb: document.getElementById("atlas-breadcrumb"),
    coverageSummary: document.getElementById("coverage-summary"),
    atlasHome: document.getElementById("atlas-home"),
    repositoryName: document.getElementById("repository-name"),
    snapshotBadge: document.getElementById("snapshot-badge"),
    evidenceBadge: document.getElementById("evidence-badge"),
    warningBadge: document.getElementById("warning-badge"),
    globalSearch: document.getElementById("global-search"),
    searchInput: document.getElementById("search-input"),
    languageFilter: document.getElementById("language-filter"),
    typeFilter: document.getElementById("type-filter"),
    searchResults: document.getElementById("search-results"),
    searchPagination: document.getElementById("search-pagination"),
    searchCount: document.getElementById("search-count"),
    lensNav: document.getElementById("lens-nav"),
    viewEyebrow: document.getElementById("view-eyebrow"),
    viewTitle: document.getElementById("view-title"),
    viewDescription: document.getElementById("view-description"),
    graphToolbar: document.getElementById("graph-toolbar"),
    overviewView: document.getElementById("overview-view"),
    graphView: document.getElementById("graph-view"),
    changesView: document.getElementById("changes-view"),
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
    if (!source || !target || !type) return;
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
    atlasGroupKey: "",
    atlasPage: 0,
    memberPage: 0,
    displayDepth: 1,
    layerDepth: 0,
    layerFocusGroup: "",
    layerCameraPending: false,
    hoverDepth: 1,
    componentId: "",
    edgePage: 0,
    relationPage: 0,
    neighborhoodPage: 0,
    neighborhoodEdgePage: 0,
    callHighlight: { edges: new Map(), nodes: new Map() },
    hoverSignature: "",
    lastCallHover: null,
    hoverViewEdges: new Map(),
    hoverViewNodes: new Set(),
    renderedGraph: null,
    sourceScope: "all",
    relationFilter: "all",
    categoryFilter: "all",
    groupQuery: "",
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
    renderToken: 0,
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
    if (!scopeAllows(nodeById.get(edge.source)) || !scopeAllows(nodeById.get(edge.target))) return false;
    const relation = state.relationFilter;
    const filterSet = RELATION_SETS[relation];
    if (filterSet && !filterSet.has(edge.type)) return false;
    if (relation !== "all" && !filterSet && relation !== edge.type) return false;
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
    if (!nodeById.has(rootId) || !scopeAllows(nodeById.get(rootId))) return { nodes: [], edges: [], truncated: false };
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
      if (!visited.has(endpoint)) { visited.add(endpoint); queue.push({ id: endpoint, depth: 1 }); }
    }
    // Compute the complete requested neighborhood before paging the presentation.
    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const current = queue[cursor];
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
        visited.add(neighborId);
        queue.push({ id: neighborId, depth: current.depth + 1 });
      }
    }

    const selectedNodes = Array.from(visited)
      .map(function (id) {
        return nodeById.get(id);
      })
      .filter(Boolean);
    const selectedEdges = candidates.filter(function (edge) {
      return visited.has(edge.source) && visited.has(edge.target);
    });
    return { nodes: selectedNodes, edges: selectedEdges, truncated: false };
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
      if (!scopeAllows(node)) return;
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
    dom.searchPagination.replaceChildren();
    if (!visible.length) {
      dom.searchResults.replaceChildren();
      dom.searchPagination.replaceChildren(
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
      button.tabIndex = -1;
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
        selectSearchResult(node.id);
      });
      fragment.appendChild(button);
    });
    if (visible.length < state.searchMatches.length) {
      const more = make("button", "more-button", "검색 결과 더 보기 · " + formatCount(state.searchMatches.length - visible.length));
      more.type = "button";
      more.addEventListener("click", function () {
        const nextIndex = state.searchVisibleLimit;
        state.searchVisibleLimit += MAX_SEARCH_RESULTS;
        state.activeSearchIndex = nextIndex;
        renderSearchResults();
        dom.searchInput.focus({ preventScroll: true });
        syncActiveSearchOption(true);
      });
      dom.searchPagination.appendChild(more);
    }
    dom.searchResults.replaceChildren(fragment);
    syncActiveSearchOption(false);
  }

  function syncActiveSearchOption(scroll) {
    const visibleCount = Math.min(state.searchMatches.length, state.searchVisibleLimit);
    if (dom.searchPanel.hidden || !visibleCount || state.activeSearchIndex < 0) {
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
    if (edge.aggregate) { renderAggregateDetails(edge); return; }
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
    if (state.atlasOverview && !state.layerDepth) {
      url.searchParams.set("display", String(state.displayDepth));
      if (state.atlasGroupKey) url.searchParams.set("group", state.atlasGroupKey);
      if (state.componentId) url.searchParams.set("component", state.componentId);
      if (state.atlasPage) url.searchParams.set("page", String(state.atlasPage));
      if (state.edgePage) url.searchParams.set("lines", String(state.edgePage));
    }
    if (state.sourceScope !== "all") url.searchParams.set("scope", state.sourceScope);
    if (state.relationFilter !== "all") url.searchParams.set("relation", state.relationFilter);
    if (state.categoryFilter !== "all") url.searchParams.set("category", state.categoryFilter);
    if (state.groupQuery) url.searchParams.set("query", state.groupQuery);
    if (state.relationPage) url.searchParams.set("relations", String(state.relationPage));
    url.searchParams.set("hover", String(state.hoverDepth));
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
    const groupKey = params.get("group") || "", componentId = params.get("component") || "";
    const displayDepth = Math.max(1, Math.min(3, Math.floor(finiteNumber(params.get("display") || 1, 1))));
    if ((groupKey || componentId) && (!snapshot || snapshot !== text(meta.snapshotId))) return linkFailure("펼친 지도 링크의 스냅샷을 확인할 수 없습니다.");
    if (groupKey && !nodes.some(function (node) { return moduleGroup(node).key === groupKey; })) return linkFailure("이 스냅샷에 해당 모듈이 없습니다.");
    if (componentId && (!nodeById.has(componentId) || moduleGroup(nodeById.get(componentId)).key !== groupKey)) return linkFailure("구성요소가 선택 모듈에 속하지 않습니다.");
    if ((displayDepth >= 2 && !groupKey) || (displayDepth === 3 && !componentId)) return linkFailure("펼칠 모듈 또는 구성요소가 없는 링크입니다.");
    const scope = params.get("scope") || "all", relation = params.get("relation") || "all", category = params.get("category") || "all";
    const navigation = { relationPage: Math.max(0, Math.floor(finiteNumber(params.get("relations"), 0))), atlasGroupKey: groupKey, componentId: componentId, displayDepth: displayDepth, hoverDepth: Math.max(1, Math.min(3, Math.floor(finiteNumber(params.get("hover") || 1, 1)))), atlasPage: Math.max(0, Math.floor(finiteNumber(params.get("page"), 0))), edgePage: Math.max(0, Math.floor(finiteNumber(params.get("lines"), 0))), sourceScope: Object.prototype.hasOwnProperty.call(SCOPE_LABELS, scope) ? scope : "all", relationFilter: relation === "all" || Object.prototype.hasOwnProperty.call(RELATION_SETS, relation) || Object.prototype.hasOwnProperty.call(RELATION_LABELS, relation) ? relation : "all", categoryFilter: Object.prototype.hasOwnProperty.call(CATEGORY_TYPES, category) ? category : "all", groupQuery: params.get("query") || "" };
    const requested = params.get("lens") || "architecture";
    return { navigation: navigation, lens: edge ? "architecture" : LENS_COPY[requested] ? requested : LENS_ALIASES[requested] || "architecture", entity: entity || (edge ? edge.source : ""), edge: edge, evidenceId: evidenceId };
  }

  function updateViewHeading() {
    const node = nodeById.get(state.selectedId || (state.activeLens === "impact" ? state.rootId : ""));
    dom.viewEyebrow.textContent = LENS_COPY[state.activeLens].eyebrow;
    dom.viewTitle.textContent = state.activeLens === "changes" ? "변경된 코드" : node ? node.name : text(meta.repositoryName, "코드 지도");
    if (state.atlasGroupKey && !node && state.displayDepth > 1) {
      const owner = nodes.find(function (item) { return moduleGroup(item).key === state.atlasGroupKey; });
      const component = state.displayDepth === 3 ? nodeById.get(state.componentId) : null;
      dom.viewTitle.textContent = (owner ? moduleGroup(owner).label : "선택 모듈") + (component ? " / " + component.name : "");
    }
    if (state.layerDepth) dom.viewTitle.textContent = "누적 펼치기 · 1–" + state.layerDepth + "단계";
    dom.viewDescription.textContent = state.layerDepth ? "모든 영역의 상위 레이어를 유지하며 한 층씩 확장 · Shift + 드래그로 이동" : state.activeLens === "changes" ? "" : state.activeLens === "impact" ? "정적 의존 후보 · " + (state.direction === "incoming" ? "이 코드에 의존" : state.direction === "outgoing" ? "이 코드의 의존 대상" : "양방향") : node ? shortLabel(node.path || node.qualified_name, 85) : "모듈 집계 → 심볼 → 실제 관계와 근거";
  }

  function rememberSelection() {
    if (state.restoringSelection) return;
    const previous = { lens: state.activeLens, rootId: state.rootId, selectedId: state.selectedId, edgeKey: state.selectedEdgeKey, evidenceId: state.selectedEvidenceId, overview: state.atlasOverview, groupKey: state.atlasGroupKey, atlasPage: state.atlasPage, memberPage: state.memberPage, sourceScope: state.sourceScope, relationFilter: state.relationFilter, categoryFilter: state.categoryFilter, groupQuery: state.groupQuery, displayDepth: state.displayDepth, componentId: state.componentId, edgePage: state.edgePage, relationPage: state.relationPage, neighborhoodPage: state.neighborhoodPage, neighborhoodEdgePage: state.neighborhoodEdgePage, camera: Object.assign({}, state.camera) };
    const last = state.selectionHistory[state.selectionHistory.length - 1];
    if (!last || last.lens !== previous.lens || last.rootId !== previous.rootId || last.selectedId !== previous.selectedId || last.edgeKey !== previous.edgeKey || last.overview !== previous.overview || last.groupKey !== previous.groupKey || last.atlasPage !== previous.atlasPage || last.memberPage !== previous.memberPage || last.sourceScope !== previous.sourceScope || last.relationFilter !== previous.relationFilter || last.categoryFilter !== previous.categoryFilter || last.groupQuery !== previous.groupQuery || last.displayDepth !== previous.displayDepth || last.componentId !== previous.componentId || last.edgePage !== previous.edgePage || last.neighborhoodPage !== previous.neighborhoodPage || last.neighborhoodEdgePage !== previous.neighborhoodEdgePage) state.selectionHistory.push(previous);
    if (state.selectionHistory.length > 40) state.selectionHistory.shift();
    dom.viewBack.disabled = !state.selectionHistory.length;
  }

  function goBack() {
    const previous = state.selectionHistory.pop();
    if (!previous) return;
    state.layerDepth = 0;
    state.restoringSelection = true;
    state.atlasOverview = previous.overview;
    state.atlasGroupKey = previous.groupKey;
    ["atlasPage", "memberPage", "sourceScope", "relationFilter", "categoryFilter", "groupQuery", "displayDepth", "componentId", "edgePage", "relationPage", "neighborhoodPage", "neighborhoodEdgePage"].forEach(function (key) { state[key] = previous[key]; });
    dom.sourceScope.value = state.sourceScope; dom.relationFilter.value = state.relationFilter; dom.categoryFilter.value = state.categoryFilter; dom.groupSearch.value = state.groupQuery;
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
    const aggregate = presentationGroups.get(nodeId);
    if (aggregate) { chooseAtlasBucket(aggregate); return; }
    const node = nodeById.get(nodeId);
    if (!node) return;
    if (state.selectedId !== nodeId || state.selectedEdgeKey) rememberSelection();
    state.selectedId = nodeId;
    state.selectedEdgeKey = "";
    state.selectedEvidenceId = "";
    renderDetails(node);
    renderSearchResults();
    const visibleBucket = state.atlasOverview && !updateGraphSelection && Array.from(presentationGroups.values()).find(function (bucket) { return bucket.memberIds.includes(nodeId); });
    if ((state.atlasOverview || state.layerDepth) && !updateGraphSelection) {
      syncGraphTextSelection();
      if (visibleBucket) focus3dCamera(visibleBucket.id);
      else if (state.threeDPositions.has(nodeId)) focus3dCamera(nodeId);
      updateViewHeading(); updateSelectionLink(); draw3dScene(0);
      announce(node.name + " 선택됨 · 펼친 지도 유지");
      return;
    }
    if ((!state.atlasOverview && state.atlasGroupKey) || updateGraphSelection || !state.threeDPositions.has(nodeId) || (state.activeLens === "impact" && state.rootId !== nodeId)) {
      state.rootId = nodeId;
      state.neighborhoodPage = 0; state.neighborhoodEdgePage = 0;
      state.atlasGroupKey = "";
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
    state.layerDepth = 0;
    state.atlasOverview = false;
    state.atlasGroupKey = "";
    state.selectedId = nodeId;
    state.selectedEdgeKey = "";
    state.selectedEvidenceId = "";
    state.rootId = nodeId;
    state.neighborhoodPage = 0; state.neighborhoodEdgePage = 0;
    renderDetails(nodeById.get(nodeId));
    if (state.activeLens === "changes") switchLens("architecture", nodeId, true);
    else { renderSearchResults(); renderGraph(); updateViewHeading(); }
    focus3dCamera(nodeId);
    updateSelectionLink();
  }

  function selectSearchResult(nodeId) {
    if (!nodeById.has(nodeId)) return;
    dom.atlasSettings.open = false;
    dom.mapHelp.open = false;
    focusAsRoot(nodeId);
    dom.searchInput.removeAttribute("aria-activedescendant");
    if (state.threeDAvailable) {
      dom.atlasBrowser.open = false;
      dom.graph3dCanvas.focus({ preventScroll: true });
    } else {
      dom.graphTextAlternative.open = true;
      dom.graphTextAlternative.focus({ preventScroll: true });
    }
    announce(nodeById.get(nodeId).name + " 선택됨 · 정적 근거 패널을 열었습니다.");
  }

  const GROUP_COLORS = ["#76e6ee", "#a795f5", "#7ae4bc", "#85baff", "#e9bc87", "#e49fc5"];
  const groupCache = new Map();

  function moduleGroup(node) {
    if (node.atlasGroup) return node.atlasGroup;
    if (groupCache.has(node.id)) return groupCache.get(node.id);
    let current = node;
    const seen = new Set();
    let owner = null;
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      if (current.type === "Module" || current.type === "Package") { owner = current; break; }
      const parent = arrayOrEmpty(incoming.get(current.id)).find(function (edge) { return edge.type === "DECLARES" || edge.type === "DECLARES_RUNTIME_BRANCH"; });
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

  // These objects exist only in the view. They never enter nodeById, edgeByKey,
  // payload, exports, or evidence links; every relation retains its canonical key.
  const presentationGroups = new Map();
  const SCOPE_LABELS = { all: "모든 소스", application: "일반 소스 후보", test: "테스트 후보", auxiliary: "보조 · 사본 후보", unknown: "분류 불명" };
  const CATEGORY_TYPES = {
    structure: new Set(["Package", "Module", "Class", "Interface", "Enum", "Record"]),
    callable: new Set(["Function", "AsyncFunction", "Method", "AsyncMethod", "ExternalCallable"]),
    policy: new Set(["PolicyLeaf", "RuntimeBranch"]),
  };

  function sourceScopeFor(node) {
    if (!node || !node.path) return "unknown";
    const path = node.path.replace(/\\/g, "/").toLowerCase();
    const parts = path.split("/");
    if (parts.some(function (part) { return /^(?:backup|backups|archive|archives|disabled|historical|build|dist|target|vendor|\.venv|venv|node_modules)$/.test(part); }) || /(?:[._-](?:bak|backup|before|orig|old|copy)(?:[._-]|$)|~$)/.test(path)) return "auxiliary";
    if (parts.some(function (part) { return /^(?:test|tests|__tests__|testing|fixtures|testdata)$/.test(part); }) || /(?:^|\/)(?:test_[^/]+|[^/]+_test)\.py$/.test(path) || /(?:test|tests|spec)\.java$/.test(path)) return "test";
    return "application";
  }

  function scopeAllows(node) {
    return Boolean(node) && (state.sourceScope === "all" || sourceScopeFor(node) === state.sourceScope);
  }

  function categoryAllows(node) {
    const types = CATEGORY_TYPES[state.categoryFilter];
    return !types || types.has(node.type);
  }

  let inventoryCacheKey = "";
  let inventoryCacheValue = null;
  function atlasInventory() {
    const cacheKey = JSON.stringify([state.sourceScope, state.categoryFilter, state.relationFilter, state.activeLens, state.groupQuery]);
    if (cacheKey === inventoryCacheKey && inventoryCacheValue) return inventoryCacheValue;
    const scopedNodes = nodes.filter(scopeAllows);
    const candidates = lensEdges(state.activeLens, "");
    const relationRestricted = state.relationFilter !== "all" || Boolean(RELATION_SETS[state.activeLens]);
    const connected = new Set();
    candidates.forEach(function (edge) { connected.add(edge.source); connected.add(edge.target); });
    const groups = new Map();
    scopedNodes.forEach(function (node) {
      if (!categoryAllows(node) || (relationRestricted && !connected.has(node.id))) return;
      const descriptor = moduleGroup(node);
      if (!groups.has(descriptor.key)) groups.set(descriptor.key, { descriptor: descriptor, members: [] });
      groups.get(descriptor.key).members.push(node);
    });
    const query = state.groupQuery.trim().toLocaleLowerCase("ko-KR");
    const allGroups = Array.from(groups.values()).sort(function (a, b) { return a.descriptor.label.localeCompare(b.descriptor.label) || a.descriptor.key.localeCompare(b.descriptor.key); });
    const matching = allGroups.filter(function (group) { return !query || group.descriptor.label.toLocaleLowerCase("ko-KR").includes(query) || group.members.some(function (node) { return node.searchText.includes(query); }); });
    const eligibleIds = new Set();
    matching.forEach(function (group) { group.members.forEach(function (node) { eligibleIds.add(node.id); }); });
    const eligibleEdges = candidates.filter(function (edge) { return eligibleIds.has(edge.source) && eligibleIds.has(edge.target); });
    inventoryCacheKey = cacheKey;
    inventoryCacheValue = { groups: matching, allGroups: allGroups, edges: eligibleEdges, nodeIds: eligibleIds, sourceNodes: scopedNodes.length, filteredNodes: nodes.length - eligibleIds.size, filteredEdges: edges.length - eligibleEdges.length };
    return inventoryCacheValue;
  }

  const componentCache = new Map();
  function componentOwner(node) {
    if (componentCache.has(node.id)) return componentCache.get(node.id);
    let current = node, owner = node;
    const seen = new Set();
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      if (["Package", "Module"].includes(current.type)) break;
      owner = current;
      const parent = arrayOrEmpty(incoming.get(current.id)).find(function (edge) { return edge.type === "DECLARES" || edge.type === "DECLARES_RUNTIME_BRANCH"; });
      const next = parent ? nodeById.get(parent.source) : null;
      if (!next || ["Package", "Module"].includes(next.type)) break;
      current = next;
    }
    componentCache.set(node.id, owner);
    return owner;
  }

  function presentationBuckets(inventory) {
    const buckets = new Map();
    inventory.groups.forEach(function (group) {
      group.members.forEach(function (node) {
        const expandedModule = state.displayDepth >= 2 && group.descriptor.key === state.atlasGroupKey;
        const owner = componentOwner(node);
        const expandedComponent = expandedModule && state.displayDepth >= 3 && owner.id === state.componentId;
        const kind = !expandedModule ? "module" : expandedComponent ? "symbol" : "component";
        const key = kind === "module" ? group.descriptor.key : kind === "component" ? owner.id : node.id;
        const viewId = JSON.stringify(["atlas-view", kind, key]);
        if (!buckets.has(viewId)) {
          const labelNode = kind === "component" ? owner : node;
          buckets.set(viewId, { id: viewId, type: "AtlasGroup", name: kind === "module" ? group.descriptor.label : labelNode.name, qualified_name: kind === "module" ? group.descriptor.label : labelNode.qualified_name, language: labelNode.language, path: labelNode.path, metadata: {}, atlasGroup: group.descriptor, bucketKind: kind, canonicalId: kind === "module" ? "" : labelNode.id, memberIds: [], memberCount: 0, internalKeys: [], internalCount: 0 });
        }
        const bucket = buckets.get(viewId);
        bucket.memberIds.push(node.id); bucket.memberCount += 1;
      });
    });
    return Array.from(buckets.values()).sort(function (a, b) { return a.atlasGroup.label.localeCompare(b.atlasGroup.label) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id); });
  }

  function atlasGraph() {
    const inventory = atlasInventory();
    const buckets = presentationBuckets(inventory);
    const pageSize = Math.min(ATLAS_PAGE_SIZE, MAX_3D_VISIBLE_NODES, maxVisibleNodes);
    state.atlasPage = Math.max(0, Math.min(state.atlasPage, Math.max(0, Math.ceil(buckets.length / pageSize) - 1)));
    const page = buckets.slice(state.atlasPage * pageSize, (state.atlasPage + 1) * pageSize);
    presentationGroups.clear();
    const memberGroups = new Map();
    buckets.forEach(function (bucket) { bucket.memberIds.forEach(function (id) { memberGroups.set(id, bucket.id); }); });
    page.forEach(function (bucket) { presentationGroups.set(bucket.id, bucket); });
    const aggregates = new Map();
    const offPageKeys = [], boundaryKeys = [], internalKeys = [];
    inventory.edges.forEach(function (edge) {
      const source = memberGroups.get(edge.source), target = memberGroups.get(edge.target);
      const sourceVisible = presentationGroups.has(source), targetVisible = presentationGroups.has(target);
      if (!sourceVisible || !targetVisible) {
        offPageKeys.push(edge.key);
        if (sourceVisible || targetVisible) boundaryKeys.push(edge.key);
        return;
      }
      if (source === target) { const node = presentationGroups.get(source); node.internalCount += 1; node.internalKeys.push(edge.key); internalKeys.push(edge.key); return; }
      const key = JSON.stringify(["atlas-edge", source, target]);
      if (!aggregates.has(key)) aggregates.set(key, { source: source, target: target, type: "AGGREGATED", key: key, aggregate: true, evidence: [], canonicalKeys: [], relationCounts: {} });
      const aggregate = aggregates.get(key);
      aggregate.canonicalKeys.push(edge.key);
      aggregate.relationCounts[edge.type] = (aggregate.relationCounts[edge.type] || 0) + 1;
    });
    const lines = Array.from(aggregates.values()).sort(function (a, b) { return a.key.localeCompare(b.key); });
    state.edgePage = Math.max(0, Math.min(state.edgePage, Math.max(0, Math.ceil(lines.length / MAX_3D_VISIBLE_EDGES) - 1)));
    const visibleLines = lines.slice(state.edgePage * MAX_3D_VISIBLE_EDGES, (state.edgePage + 1) * MAX_3D_VISIBLE_EDGES);
    const visibleKeys = visibleLines.flatMap(function (edge) { return edge.canonicalKeys; });
    const offLineKeys = lines.filter(function (edge) { return !visibleLines.includes(edge); }).flatMap(function (edge) { return edge.canonicalKeys; });
    return { nodes: page, edges: visibleLines, aggregate: true, totalGroups: inventory.allGroups.length, matchingGroups: inventory.groups.length, totalBuckets: buckets.length, pageSize: pageSize, sourceNodes: inventory.sourceNodes, eligibleNodeCount: inventory.nodeIds.size, totalEligibleEdges: inventory.edges.length, visibleKeys: visibleKeys, internalKeys: internalKeys, offPageKeys: offPageKeys, boundaryKeys: boundaryKeys, offLineKeys: offLineKeys, totalLines: lines.length, representedEdges: visibleKeys.length + internalKeys.length, representedNodes: page.reduce(function (count, node) { return count + node.memberCount; }, 0), filteredNodes: inventory.filteredNodes, filteredEdges: inventory.filteredEdges, truncated: page.length < buckets.length || visibleLines.length < lines.length };
  }

  function groupMemberGraph() { return atlasGraph(); }

  function revealAtlasSelection() {
    const buckets = presentationBuckets(atlasInventory());
    const index = buckets.findIndex(function (bucket) { return state.displayDepth >= 3 ? bucket.canonicalId === state.componentId : bucket.atlasGroup.key === state.atlasGroupKey; });
    state.atlasPage = index < 0 ? 0 : Math.floor(index / Math.min(ATLAS_PAGE_SIZE, MAX_3D_VISIBLE_NODES, maxVisibleNodes));
  }

  function chooseAtlasBucket(bucket) {
    if (state.layerDepth) {
      state.layerFocusGroup = bucket.atlasGroup.key;
      state.selectedId = bucket.canonicalId || ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = "";
      if (bucket.canonicalId) renderDetails(nodeById.get(bucket.canonicalId)); else renderBucketDetails(bucket);
      syncGraphTextSelection(); focus3dCamera(bucket.id); updateSelectionLink(); return;
    }
    if (bucket.bucketKind === "module") { openAtlasGroup(bucket.atlasGroup.key); return; }
    if (bucket.bucketKind === "component" && bucket.memberCount > 1) {
      rememberSelection(); state.componentId = bucket.canonicalId; state.displayDepth = 3; dom.displayDepth.value = "3";
      revealAtlasSelection(); state.edgePage = 0;
      renderGraph(); renderBucketDetails(bucket); updateViewHeading(); updateSelectionLink(); return;
    }
    if (bucket.canonicalId) selectNode(bucket.canonicalId, false);
  }

  function openAtlasGroup(key) {
    rememberSelection();
    state.layerDepth = 0;
    const previous = Array.from(presentationGroups.values()).find(function (bucket) { return bucket.atlasGroup.key === key && bucket.bucketKind === "module"; });
    state.atlasGroupKey = key; state.componentId = ""; state.displayDepth = 2; dom.displayDepth.value = "2";
    state.atlasOverview = true; revealAtlasSelection(); state.edgePage = 0;
    state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = "";
    reset3dCamera(); renderGraph(); updateViewHeading(); updateSelectionLink();
    if (previous) renderBucketDetails(previous);
    announce("선택 모듈만 2단계로 펼쳤습니다. 다른 모듈은 접힌 상태입니다.");
  }

  function showAtlasHome() {
    rememberSelection();
    state.layerDepth = 0;
    state.atlasOverview = true; state.atlasGroupKey = ""; state.componentId = "";
    state.displayDepth = 1; dom.displayDepth.value = "1"; state.atlasPage = 0; state.edgePage = 0;
    state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = "";
    setHidden(dom.detailsPanel, true);
    reset3dCamera(); renderGraph(); updateViewHeading(); updateSelectionLink();
  }

  // The layer tree is presentation only. Parent evidence is restricted to static
  // declaration edges; folder/external roots never imply a source relationship.
  let cumulativeIndex = null;
  function cumulativeHierarchy() {
    if (cumulativeIndex) return cumulativeIndex;
    const groups = new Map(), parents = new Map(), depths = new Map(), children = new Map();
    nodes.forEach(function (node) {
      const descriptor = moduleGroup(node);
      if (!groups.has(descriptor.key)) groups.set(descriptor.key, { descriptor: descriptor, members: [], id: JSON.stringify(["atlas-layer", descriptor.key]) });
      groups.get(descriptor.key).members.push(node);
    });
    nodes.forEach(function (node) {
      const descriptor = moduleGroup(node);
      const parent = arrayOrEmpty(incoming.get(node.id)).find(function (edge) {
        return (edge.type === "DECLARES" || edge.type === "DECLARES_RUNTIME_BRANCH") && edge.source !== node.id && moduleGroup(nodeById.get(edge.source)).key === descriptor.key;
      });
      const parentId = node.id === descriptor.anchorId ? "" : parent ? parent.source : "";
      parents.set(node.id, parentId);
      if (parentId) { if (!children.has(parentId)) children.set(parentId, []); children.get(parentId).push(node.id); }
    });
    const queue = [];
    function add(id, depth) {
      const node = nodeById.get(id);
      depths.set(id, ["PolicyLeaf", "RuntimeBranch"].includes(node.type) ? Math.max(4, depth) : depth);
      queue.push(id);
    }
    nodes.forEach(function (node) { if (!parents.get(node.id)) add(node.id, node.id === moduleGroup(node).anchorId ? 1 : 2); });
    function drain() {
      for (let i = 0; i < queue.length; i += 1) {
        const id = queue[i];
        arrayOrEmpty(children.get(id)).forEach(function (child) { if (!depths.has(child)) add(child, depths.get(id) + 1); });
      }
      queue.length = 0;
    }
    drain();
    // Malformed cycles still remain navigable, without inventing a containment edge.
    nodes.forEach(function (node) { if (!depths.has(node.id)) { parents.set(node.id, ""); add(node.id, 2); drain(); } });
    let maxDepth = 1;
    depths.forEach(function (depth) { maxDepth = Math.max(maxDepth, depth); });
    cumulativeIndex = { groups: Array.from(groups.values()).sort(function (a, b) { return a.descriptor.key.localeCompare(b.descriptor.key); }), parents: parents, depths: depths, maxDepth: maxDepth };
    return cumulativeIndex;
  }

  function cumulativeLayerGraph(requestedDepth) {
    const hierarchy = cumulativeHierarchy();
    const depth = Math.max(1, Math.min(hierarchy.maxDepth, Math.floor(requestedDepth)));
    const displayed = new Map(), representatives = new Map();
    hierarchy.groups.forEach(function (group) {
      const anchor = nodeById.get(group.descriptor.anchorId);
      displayed.set(group.id, { id: group.id, type: "AtlasGroup", name: group.descriptor.label, qualified_name: group.descriptor.label,
        language: anchor ? anchor.language : group.members[0].language, path: anchor ? anchor.path : "", metadata: {},
        atlasGroup: group.descriptor, bucketKind: "module", canonicalId: anchor ? anchor.id : "", layerDepth: 1,
        memberIds: [], memberCount: 0, internalKeys: [], internalCount: 0 });
      group.members.forEach(function (node) {
        if (node.id === group.descriptor.anchorId) { representatives.set(node.id, group.id); return; }
        if (hierarchy.depths.get(node.id) <= depth) {
          displayed.set(node.id, Object.assign({}, node, { atlasGroup: group.descriptor, bucketKind: "layer", canonicalId: node.id,
            layerDepth: hierarchy.depths.get(node.id), memberIds: [], memberCount: 0, internalKeys: [], internalCount: 0 }));
        }
      });
      group.members.forEach(function (node) {
        let current = node.id;
        const seen = new Set();
        while (current && !displayed.has(current) && current !== group.descriptor.anchorId && !seen.has(current)) { seen.add(current); current = hierarchy.parents.get(current); }
        const representative = displayed.has(current) ? current : group.id;
        representatives.set(node.id, representative);
        const bucket = displayed.get(representative);
        bucket.memberIds.push(node.id); bucket.memberCount += 1;
      });
    });
    const aggregates = new Map(), internalKeys = [];
    edges.forEach(function (edge) {
      const source = representatives.get(edge.source), target = representatives.get(edge.target);
      if (source === target && !(edge.source === edge.target && displayed.get(source).canonicalId === edge.source)) {
        const bucket = displayed.get(source); bucket.internalKeys.push(edge.key); bucket.internalCount += 1; internalKeys.push(edge.key); return;
      }
      const key = JSON.stringify(["layer-edge", source, target]);
      if (!aggregates.has(key)) aggregates.set(key, { source: source, target: target, type: "AGGREGATED", key: key, aggregate: true, evidence: [], canonicalKeys: [], relationCounts: {} });
      const line = aggregates.get(key); line.canonicalKeys.push(edge.key); line.relationCounts[edge.type] = (line.relationCounts[edge.type] || 0) + 1;
    });
    const graphNodes = Array.from(displayed.values()), graphEdges = Array.from(aggregates.values());
    presentationGroups.clear(); graphNodes.forEach(function (node) { presentationGroups.set(node.id, node); });
    return { nodes: graphNodes, edges: graphEdges, aggregate: true, cumulative: true, layerDepth: depth, maxLayerDepth: hierarchy.maxDepth,
      totalGroups: hierarchy.groups.length, matchingGroups: hierarchy.groups.length, totalBuckets: graphNodes.length, pageSize: Math.max(1, graphNodes.length),
      sourceNodes: nodes.length, eligibleNodeCount: nodes.length, totalEligibleEdges: edges.length,
      visibleKeys: graphEdges.flatMap(function (edge) { return edge.canonicalKeys; }), internalKeys: internalKeys,
      offPageKeys: [], boundaryKeys: [], offLineKeys: [], totalLines: graphEdges.length,
      representedEdges: edges.length, representedNodes: nodes.length, filteredNodes: 0, filteredEdges: 0, truncated: false };
  }

  function setCumulativeDepth(requested) {
    const next = Math.max(1, Math.min(cumulativeHierarchy().maxDepth, requested));
    if (next === state.layerDepth) return;
    if (next > state.layerDepth && next >= 4 && !window.confirm(next + "단계까지 모든 영역을 누적해서 펼칩니다.\n\n표시 항목이 늘어나 메모리와 CPU 사용량이 커지고 화면이 느려질 수 있습니다. 배치 공간과 확대율도 함께 늘어납니다.\n\n계속 펼치시겠습니까?")) return;
    const prior = state.layerDepth;
    const focused = nodeById.get(state.selectedId || state.rootId);
    if (focused) state.layerFocusGroup = moduleGroup(focused).key;
    else if (!prior) {
      const group = cumulativeHierarchy().groups.find(function (item) { return item.descriptor.anchorId; }) || cumulativeHierarchy().groups[0];
      state.layerFocusGroup = group ? group.descriptor.key : "";
    }
    if (!prior) rememberSelection();
    state.layerDepth = next; state.atlasOverview = true; state.atlasGroupKey = ""; state.componentId = "";
    state.displayDepth = 1; state.atlasPage = 0; state.edgePage = 0; state.neighborhoodPage = 0; state.neighborhoodEdgePage = 0;
    state.sourceScope = "all"; state.relationFilter = "all"; state.categoryFilter = "all"; state.groupQuery = "";
    dom.sourceScope.value = "all"; dom.relationFilter.value = "all"; dom.categoryFilter.value = "all"; dom.groupSearch.value = "";
    state.activeLens = "architecture"; updateLensButtons("architecture");
    state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = "";
    setHidden(dom.detailsPanel, true); state.motionEnabled = false; updateMotionControl();
    state.cameraTransition = null;
    const priorZoom = state.camera.zoom;
    if (!prior) reset3dCamera();
    state.camera.zoom = Math.max(0.35, Math.min(2.4, priorZoom * Math.pow(1.16, next - (prior || 1))));
    state.layerCameraPending = true;
    renderGraph(); updateViewHeading(); updateSelectionLink();
    announce("1–" + next + "단계 누적 표시. 상위 레이어를 유지하며 배치 공간을 넓혔습니다. Shift와 함께 드래그하면 이동합니다.");
  }

  function showNextLayer() { setCumulativeDepth(state.layerDepth ? state.layerDepth + 1 : 2); }
  function showPreviousLayer() { if (state.layerDepth > 1) setCumulativeDepth(state.layerDepth - 1); }

  function canonicalRelationPage() {
    const relations = atlasInventory().edges;
    state.relationPage = Math.max(0, Math.min(state.relationPage, Math.max(0, Math.ceil(relations.length / RELATION_PAGE_SIZE) - 1)));
    return { total: relations.length, page: state.relationPage, edges: relations.slice(state.relationPage * RELATION_PAGE_SIZE, (state.relationPage + 1) * RELATION_PAGE_SIZE) };
  }

  function canonicalRelationButton(edge) {
    const from = nodeById.get(edge.source), to = nodeById.get(edge.target);
    const button = make("button", "atlas-list-button", from.name + " → " + to.name + " · " + relationLabel(edge.type)); button.type = "button";
    button.addEventListener("click", function () { state.activeLens = "architecture"; updateLensButtons("architecture"); state.relationFilter = "all"; dom.relationFilter.value = "all"; state.categoryFilter = "all"; dom.categoryFilter.value = "all"; focusAsRoot(edge.source); state.selectedEdgeKey = edge.key; renderGraph(); renderEdgeDetails(edge); });
    button.addEventListener("mouseenter", function () { setCallHover("", edge); });
    button.addEventListener("focus", function () { setCallHover("", edge); });
    button.addEventListener("mouseleave", clearCallHover);
    button.addEventListener("blur", clearCallHover);
    return button;
  }

  function renderCanonicalRelations() {
    const page = canonicalRelationPage();
    dom.relationSummary.textContent = "원본 관계 " + (page.total ? formatCount(page.page * RELATION_PAGE_SIZE + 1) + "–" + formatCount(page.page * RELATION_PAGE_SIZE + page.edges.length) : "0") + " / " + formatCount(page.total) + "개 · 내부 / 다른 지도 페이지 포함";
    dom.relationPrevious.disabled = page.page === 0;
    dom.relationNext.disabled = (page.page + 1) * RELATION_PAGE_SIZE >= page.total;
    const fragment = document.createDocumentFragment();
    page.edges.forEach(function (edge) { fragment.appendChild(canonicalRelationButton(edge)); });
    dom.relationList.replaceChildren(fragment);
  }

  function renderAtlasNavigation(graph) {
    const overview = Boolean(graph.aggregate);
    const inventory = atlasInventory();
    dom.atlasBreadcrumb.textContent = graph.cumulative ? "전체 영역 · 1–" + graph.layerDepth + "단계 누적" : !overview ? "심볼의 정적 연결" : state.displayDepth === 1 ? "전체 모듈 · 선택해서 펼치기" : state.displayDepth === 2 ? "선택 모듈의 클래스 · 함수" : "선택 구성요소의 멤버 · 실제 연결";
    dom.atlasHome.disabled = !graph.cumulative && overview && state.displayDepth === 1;
    const maxLayer = cumulativeHierarchy().maxDepth;
    dom.layerNext.disabled = (state.layerDepth || 1) >= maxLayer;
    dom.layerPrevious.disabled = state.layerDepth <= 1;
    dom.layerSummary.textContent = state.layerDepth ? "1–" + state.layerDepth + " / " + maxLayer + "단계" : "1 / " + maxLayer + "단계";
    [dom.displayDepth, dom.sourceScope, dom.relationFilter, dom.categoryFilter, dom.groupSearch].forEach(function (control) { control.disabled = Boolean(graph.cumulative); });
    dom.displayDepth.value = String(state.displayDepth);
    dom.hoverDepth.value = String(state.hoverDepth);
    const count = graph.totalBuckets;
    const pageSize = graph.pageSize;
    const currentPage = overview ? state.atlasPage : state.neighborhoodPage;
    const currentEdgePage = overview ? state.edgePage : state.neighborhoodEdgePage;
    const start = currentPage * pageSize;
    const items = graph.nodes;
    dom.groupSummary.textContent = (overview ? "지도 항목 " : "전체 이웃 심볼 ") + (count ? formatCount(start + 1) + "–" + formatCount(Math.min(start + pageSize, count)) : "0") + " / " + formatCount(count) + " · 모듈 " + formatCount(inventory.groups.length) + "개";
    dom.groupPrevious.disabled = currentPage === 0;
    dom.groupNext.disabled = start + pageSize >= count;
    dom.edgePrevious.disabled = currentEdgePage === 0;
    dom.edgeNext.disabled = Boolean(graph.cumulative) || (currentEdgePage + 1) * MAX_3D_VISIBLE_EDGES >= graph.totalLines;
    dom.edgePageSummary.textContent = (overview ? "집계선 " : "현재 지도 관계 ") + formatCount(graph.edges.length) + " / " + formatCount(graph.totalLines) + (graph.cumulative ? " · 모두 표시" : " · " + (currentEdgePage + 1) + "/" + Math.max(1, Math.ceil(graph.totalLines / MAX_3D_VISIBLE_EDGES)) + "페이지");
    const fragment = document.createDocumentFragment();
    items.forEach(function (bucket) {
      const button = make("button", "atlas-list-button"); button.type = "button";
      if (!overview) {
        append(button, make("strong", "", bucket.name), make("span", "", typeLabel(bucket.type) + " · " + (bucket.path || bucket.qualified_name)));
        button.addEventListener("click", function () { selectNode(bucket.id, false); });
        button.addEventListener("mouseenter", function () { setCallHover(bucket.id, null); });
        button.addEventListener("focus", function () { setCallHover(bucket.id, null); });
        button.addEventListener("mouseleave", clearCallHover); button.addEventListener("blur", clearCallHover);
        fragment.appendChild(button); return;
      }
      append(button, make("strong", "", bucket.name), make("span", "", (bucket.bucketKind === "module" ? "접힌 모듈" : bucket.bucketKind === "component" ? "구성요소" : "심볼") + " · 원본 " + formatCount(bucket.memberCount) + "개 · 내부 관계 " + formatCount(bucket.internalCount)));
      button.addEventListener("click", function () { chooseAtlasBucket(bucket); });
      button.addEventListener("mouseenter", function () { setCallHover(bucket.id, null, bucket.memberIds); });
      button.addEventListener("focus", function () { setCallHover(bucket.id, null, bucket.memberIds); });
      button.addEventListener("mouseleave", clearCallHover); button.addEventListener("blur", clearCallHover);
      fragment.appendChild(button);
    });
    dom.groupList.replaceChildren(fragment);
    renderCanonicalRelations();
  }

  function renderBucketDetails(bucket) {
    setHidden(dom.detailsPanel, false);
    const header = make("div", "details-header");
    append(header, make("span", "type-chip", "표시용 집계 · 원본 심볼 " + formatCount(bucket.memberCount) + "개"), make("h3", "", bucket.name), make("p", "details-subtitle", "집계는 표시 방식입니다. 원본 심볼과 관계는 모두 아래에서 탐색할 수 있습니다. 정적 소스이며 실행 여부는 확인하지 않습니다."));
    const members = make("div", "atlas-member-list");
    const more = make("button", "more-button", "심볼 더 보기"); more.type = "button";
    let shown = 0;
    function nextPage() {
      bucket.memberIds.slice(shown, shown + MAX_SEARCH_RESULTS).forEach(function (id) {
        const node = nodeById.get(id);
        const button = make("button", "atlas-list-button", node.name + " · " + typeLabel(node.type)); button.type = "button";
        button.addEventListener("click", function () { selectNode(id, false); }); members.appendChild(button);
      });
      shown += MAX_SEARCH_RESULTS; setHidden(more, shown >= bucket.memberIds.length);
    }
    more.addEventListener("click", nextPage); nextPage();
    dom.detailsContent.replaceChildren(header, members, more);
    const internal = make("button", "more-button", "내부 관계 " + formatCount(bucket.internalKeys.length) + "개 보기"); internal.type = "button";
    internal.addEventListener("click", function () { renderAggregateDetails({ source: bucket.id, target: bucket.id, canonicalKeys: bucket.internalKeys, relationCounts: {}, aggregate: true }); });
    dom.detailsContent.appendChild(internal);
  }

  function canonicalCallTrace(seedIds, depth, seedKeys) {
    const maxDepth = Math.max(1, Math.min(3, finiteNumber(depth, 1)));
    const callEdges = atlasInventory().edges.filter(function (edge) { return edge.type === "CALLS"; });
    const allowed = new Map(callEdges.map(function (edge) { return [edge.key, edge]; }));
    const adjacency = new Map();
    callEdges.forEach(function (edge) { if (!adjacency.has(edge.source)) adjacency.set(edge.source, []); adjacency.get(edge.source).push(edge); });
    const edgeDepths = new Map(), nodeDepths = new Map(), visited = new Map(), queue = [];
    function visit(id, distance) { if (!visited.has(id) || distance < visited.get(id)) { visited.set(id, distance); nodeDepths.set(id, Math.min(nodeDepths.has(id) ? nodeDepths.get(id) : Infinity, distance)); queue.push({ id: id, distance: distance }); } }
    if (seedKeys && seedKeys.length) {
      seedKeys.forEach(function (key) { const edge = allowed.get(key); if (!edge) return; edgeDepths.set(key, 1); if (!nodeDepths.has(edge.source)) nodeDepths.set(edge.source, 0); visit(edge.target, 1); });
    } else seedIds.forEach(function (id) { visit(id, 0); });
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index];
      if (current.distance >= maxDepth) continue;
      arrayOrEmpty(adjacency.get(current.id)).forEach(function (edge) {
        const distance = current.distance + 1;
        if (!edgeDepths.has(edge.key) || distance < edgeDepths.get(edge.key)) edgeDepths.set(edge.key, distance);
        visit(edge.target, distance);
      });
    }
    return { edges: edgeDepths, nodes: nodeDepths };
  }

  function setCallHover(nodeId, edge, explicitMembers) {
    const signature = JSON.stringify([nodeId, edge ? edge.key || edge.canonicalKeys : "", state.hoverDepth]);
    if (signature === state.hoverSignature) return;
    state.hoverSignature = signature;
    const bucket = presentationGroups.get(nodeId);
    const seeds = explicitMembers || (bucket ? bucket.memberIds : nodeId ? [nodeId] : []);
    const keys = edge ? (edge.aggregate ? edge.canonicalKeys : [edge.key]) : null;
    state.lastCallHover = { nodeId: nodeId, edge: edge, members: explicitMembers };
    state.callHighlight = canonicalCallTrace(seeds, state.hoverDepth, keys);
    state.hoverViewEdges.clear(); state.hoverViewNodes.clear();
    const graph = state.threeDGraph || state.renderedGraph;
    if (graph) {
      graph.edges.forEach(function (visibleEdge) {
        let nearest = Infinity;
        (visibleEdge.aggregate ? visibleEdge.canonicalKeys : [visibleEdge.key]).forEach(function (key) { if (state.callHighlight.edges.has(key)) nearest = Math.min(nearest, state.callHighlight.edges.get(key)); });
        if (Number.isFinite(nearest)) state.hoverViewEdges.set(visibleEdge.key, nearest);
      });
      graph.nodes.forEach(function (node) { if ((node.memberIds || [node.id]).some(function (id) { return state.callHighlight.nodes.has(id); })) state.hoverViewNodes.add(node.id); });
    }
    updateCallTraceSummary(graph);
    draw3dScene(0);
  }

  function updateCallTraceSummary(graph) {
    setHidden(dom.startGuide, Boolean(state.hoverSignature));
    setHidden(dom.callTraceSummary, !state.hoverSignature);
    if (!state.hoverSignature) {
      dom.callTraceSummary.textContent = "심볼이나 선을 가리키면 호출 경로를 강조합니다. 1차 청록 · 2차 금색 · 3차 보라";
      return;
    }
    const hops = [0, 0, 0, 0], represented = new Set();
    state.callHighlight.edges.forEach(function (depth) { hops[depth] += 1; });
    if (graph) graph.edges.forEach(function (edge) {
      (edge.aggregate ? edge.canonicalKeys : [edge.key]).forEach(function (key) { if (state.callHighlight.edges.has(key)) represented.add(key); });
    });
    const hidden = state.callHighlight.edges.size - represented.size;
    dom.callTraceSummary.textContent = "1차 " + formatCount(hops[1]) + " · 2차 " + formatCount(hops[2]) + " · 3차 " + formatCount(hops[3]) + " | 원본 호출 " + formatCount(state.callHighlight.edges.size) + "개 → 화면 선 " + formatCount(state.hoverViewEdges.size) + "개" + (hidden ? " · 접힘/화면 밖 " + formatCount(hidden) + "개 (아래 레이어로 펼치기)" : "") + (state.callHighlight.edges.size && !hops[2] && state.hoverDepth > 1 ? " · 이 시작점에서 이어지는 다음 호출 없음" : "");
  }

  function clearCallHover() {
    state.hoverSignature = "";
    state.threeDHoverNodeId = ""; state.threeDHoverEdgeKey = "";
    state.callHighlight = { edges: new Map(), nodes: new Map() };
    state.hoverViewEdges.clear(); state.hoverViewNodes.clear();
    updateCallTraceSummary(null);
    draw3dScene(0);
  }

  function callHopForEdge(edge) {
    return state.hoverViewEdges.has(edge.key) ? state.hoverViewEdges.get(edge.key) : Infinity;
  }

  function renderAggregateDetails(edge) {
    const source = presentationGroups.get(edge.source), target = presentationGroups.get(edge.target);
    state.selectedEdgeKey = ""; state.selectedId = ""; state.selectedEvidenceId = "";
    setHidden(dom.detailsPanel, false);
    const header = make("div", "details-header");
    append(header, make("span", "relation-chip", "표시용 집계 · 원본 관계 " + formatCount(edge.canonicalKeys.length) + "개"), make("h3", "", (source ? source.name : "모듈") + " → " + (target ? target.name : "모듈")), make("p", "details-subtitle", "이 선은 원본 소스 관계를 모듈별로 묶은 표시입니다. 아래 관계를 선택하면 실제 심볼과 근거를 확인합니다."));
    const list = make("div", "atlas-relation-list");
    const counts = make("p", "details-subtitle", Object.keys(edge.relationCounts).sort().map(function (type) { return relationLabel(type) + " " + formatCount(edge.relationCounts[type]); }).join(" · "));
    let shown = 0;
    const more = make("button", "more-button", "원본 관계 더 보기"); more.type = "button";
    function nextPage() {
      edge.canonicalKeys.slice(shown, shown + MAX_DETAIL_NEIGHBORS).forEach(function (key) {
        const canonical = edgeByKey.get(key);
        if (!canonical) return;
        list.appendChild(canonicalRelationButton(canonical));
      });
      shown += MAX_DETAIL_NEIGHBORS; setHidden(more, shown >= edge.canonicalKeys.length);
    }
    more.addEventListener("click", nextPage); nextPage();
    dom.detailsContent.replaceChildren(header, counts, list, more);
    updateSelectionLink();
  }

  function buildCumulativeLayout(graph) {
    const grouped = new Map();
    graph.nodes.forEach(function (node) {
      const descriptor = node.atlasGroup;
      if (!grouped.has(descriptor.key)) grouped.set(descriptor.key, { descriptor: descriptor, nodes: [], levels: new Map() });
      const group = grouped.get(descriptor.key); group.nodes.push(node);
      if (!group.levels.has(node.layerDepth)) group.levels.set(node.layerDepth, []);
      group.levels.get(node.layerDepth).push(node);
    });
    const groups = Array.from(grouped.values()).sort(function (a, b) { return a.descriptor.key.localeCompare(b.descriptor.key); });
    const bandRows = new Map();
    let tileWidth = 300;
    groups.forEach(function (group) {
      group.levels.forEach(function (items, depth) {
        items.sort(function (a, b) { return a.id.localeCompare(b.id); });
        const columns = Math.ceil(Math.sqrt(items.length));
        tileWidth = Math.max(tileWidth, columns * 110 + 160);
        bandRows.set(depth, Math.max(bandRows.get(depth) || 1, Math.ceil(items.length / columns)));
      });
    });
    const offsets = new Map();
    let tileHeight = 100;
    for (let depth = 1; depth <= graph.layerDepth; depth += 1) {
      offsets.set(depth, tileHeight); tileHeight += (bandRows.get(depth) || 1) * 100 + 150;
    }
    const columns = Math.max(1, Math.ceil(Math.sqrt(groups.length)));
    const rows = Math.ceil(groups.length / columns);
    state.threeDGroups = groups; state.groupByNodeId.clear();
    groups.forEach(function (group, index) {
      const left = (index % columns - (columns - 1) / 2) * tileWidth;
      const top = (Math.floor(index / columns) - (rows - 1) / 2) * tileHeight - tileHeight / 2;
      group.center = { x: left, y: top + tileHeight / 2, z: 0 };
      group.color = GROUP_COLORS[index % GROUP_COLORS.length]; group.radius = 24;
      group.levels.forEach(function (items, depth) {
        const countAcross = Math.ceil(Math.sqrt(items.length));
        items.forEach(function (node, ordinal) {
          state.groupByNodeId.set(node.id, group);
          state.threeDPositions.set(node.id, { x: left + (ordinal % countAcross - (countAcross - 1) / 2) * 110,
            y: top + offsets.get(depth) + Math.floor(ordinal / countAcross) * 100, z: 0 });
        });
      });
    });
    // Deliberately do not fit or normalize this layout: more layers get more room.
  }

  function buildModuleLayout(graph) {
    if (graph.cumulative) { buildCumulativeLayout(graph); return; }
    if (graph.aggregate) {
      state.threeDGroups = [];
      state.groupByNodeId.clear();
      graph.nodes.forEach(function (node, index) {
        const count = graph.nodes.length;
        const y = count <= 1 ? 0 : 1 - (index / (count - 1)) * 2;
        const ring = Math.sqrt(Math.max(0, 1 - y * y));
        const angle = index * 2.399963229728653;
        const center = { x: Math.cos(angle) * ring * 410, y: y * 235, z: Math.sin(angle) * ring * 210 };
        const group = { descriptor: node.atlasGroup, nodes: [node], center: center, color: GROUP_COLORS[index % GROUP_COLORS.length], radius: 20 };
        state.groupByNodeId.set(node.id, group);
        state.threeDPositions.set(node.id, center);
      });
      return;
    }
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
    if (graph.cumulative || graph.aggregate || graph.paged) return graph;
    const orderedNodes = graph.nodes.slice().sort(function (left, right) {
      if (left.id === state.rootId) return -1;
      if (right.id === state.rootId) return 1;
      const selected = edgeByKey.get(state.selectedEdgeKey);
      if (selected) {
        const leftEndpoint = left.id === selected.source || left.id === selected.target;
        const rightEndpoint = right.id === selected.source || right.id === selected.target;
        if (leftEndpoint !== rightEndpoint) return leftEndpoint ? -1 : 1;
      }
      return left.id.localeCompare(right.id);
    });
    const pageSize = Math.min(MAX_3D_VISIBLE_NODES, maxVisibleNodes);
    state.neighborhoodPage = Math.max(0, Math.min(state.neighborhoodPage, Math.max(0, Math.ceil(orderedNodes.length / pageSize) - 1)));
    const boundedNodes = orderedNodes.slice(state.neighborhoodPage * pageSize, (state.neighborhoodPage + 1) * pageSize).slice(0, MAX_3D_VISIBLE_NODES);
    const included = new Set(boundedNodes.map(function (node) { return node.id; }));
    const pageEdges = [], offPageKeys = [], boundaryKeys = [];
    graph.edges.forEach(function (edge) {
      const source = included.has(edge.source), target = included.has(edge.target);
      if (source && target) pageEdges.push(edge);
      else { offPageKeys.push(edge.key); if (source || target) boundaryKeys.push(edge.key); }
    });
    pageEdges.sort(function (left, right) { return left.key.localeCompare(right.key); });
    state.neighborhoodEdgePage = Math.max(0, Math.min(state.neighborhoodEdgePage, Math.max(0, Math.ceil(pageEdges.length / MAX_3D_VISIBLE_EDGES) - 1)));
    const start = state.neighborhoodEdgePage * MAX_3D_VISIBLE_EDGES;
    const boundedEdges = pageEdges.slice(start).slice(0, MAX_3D_VISIBLE_EDGES);
    const offLineKeys = pageEdges.slice(0, start).concat(pageEdges.slice(start + MAX_3D_VISIBLE_EDGES)).map(function (edge) { return edge.key; });
    return Object.assign({}, graph, { nodes: boundedNodes, edges: boundedEdges, paged: true, pageSize: pageSize, totalBuckets: orderedNodes.length, totalNeighborhoodNodes: orderedNodes.length, totalNeighborhoodEdges: graph.edges.length, totalLines: pageEdges.length, offPageKeys: offPageKeys, boundaryKeys: boundaryKeys, offLineKeys: offLineKeys, truncated: boundedNodes.length < graph.nodes.length || boundedEdges.length < graph.edges.length });
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
      (bounded.aggregate ? "모듈 집계: 그룹 " : "현재 지도: 심볼 ") + formatCount(bounded.nodes.length) + "개, 관계 " +
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
        const source = nodeById.get(edge.source) || presentationGroups.get(edge.source);
        const target = nodeById.get(edge.target) || presentationGroups.get(edge.target);
        const item = make("div", "graph-text-item");
        item.setAttribute("role", "listitem");
        const button = make(
          "button",
          "graph-text-button" + (edge.key === state.selectedEdgeKey ? " is-selected" : ""),
          (source ? source.name : edge.source) + " → " +
            (target ? target.name : edge.target) + " · " + relationLabel(edge.type) + (edge.aggregate ? " " + formatCount(edge.canonicalKeys.length) + "개" : "")
        );
        button.type = "button";
        button.dataset.edgeKey = edge.key;
        if (edge.key === state.selectedEdgeKey) button.setAttribute("aria-current", "true");
        button.addEventListener("click", function () {
          rememberSelection();
          state.selectedEdgeKey = edge.key;
          renderEdgeDetails(edge);
          syncGraphTextSelection();
          if (state.threeDGraph) draw3dScene(0);
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
    const verticalOffset = viewport.width / viewport.ratio < 760 ? .58 : .51;
    return { x: viewport.width * offset + yawX * scale, y: viewport.height * verticalOffset + pitchY * scale, z: pitchZ, scale: scale, perspective: perspective };
  }

  function compactModuleCaption(value, limit) {
    const parts = text(value).split(/[.\\/]+/).filter(Boolean);
    const suffix = parts.slice(-2).join(".") || text(value);
    const caption = (parts.length > 2 ? "…" : "") + suffix;
    return caption.length > limit ? "…" + caption.slice(-(limit - 1)) : caption;
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
    const selectedBucket = state.atlasOverview && Array.from(presentationGroups.values()).find(function (bucket) { return bucket.memberIds.includes(state.selectedId); });
    const focusId = state.threeDHoverNodeId || (selectedBucket ? selectedBucket.id : state.selectedId);
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
    const labelTop = (finiteNumber(dom.atlasControls.offsetTop, compactLabels ? 140 : 132) + finiteNumber(dom.atlasControls.offsetHeight, compactLabels ? 95 : 58) + 12) * dpr;
    const moduleLabelLimit = compactLabels ? 4 : MAX_MODULE_LABELS;
    const symbolLabelLimit = compactLabels ? 6 : 42;
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
      const label = compactLabels ? compactModuleCaption(group.descriptor.label, 20) : shortLabel(group.descriptor.label, 37);
      const captionWidth = context.measureText(label).width + 12 * dpr;
      const captionY = point.y - radius * .88 - 14 * dpr;
      const captionBox = { x: point.x - captionWidth / 2, y: captionY - 11 * dpr, w: captionWidth, h: 29 * dpr };
      const overlaps = occupied.some(function (other) { return captionBox.x < other.x + other.w + 6 * dpr && captionBox.x + captionBox.w + 6 * dpr > other.x && captionBox.y < other.y + other.h + 6 * dpr && captionBox.y + captionBox.h + 6 * dpr > other.y; });
      const inViewport = captionBox.x >= 8 * dpr && captionBox.x + captionBox.w <= viewport.width - 8 * dpr && captionBox.y >= labelTop && captionBox.y + captionBox.h <= viewport.height - 115 * dpr;
      if ((!compactLabels || !state.threeDGraph.aggregate) && moduleLabelsDrawn < moduleLabelLimit && !overlaps && inViewport) {
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
    state.threeDProjectedEdges.sort(function (a, b) {
      const aHop = callHopForEdge(a.edge), bHop = callHopForEdge(b.edge);
      return Number(Number.isFinite(aHop)) - Number(Number.isFinite(bHop)) || (Number.isFinite(aHop) && Number.isFinite(bHop) ? bHop - aHop : 0) || (b.source.z + b.target.z) - (a.source.z + a.target.z);
    });
    state.threeDProjectedEdges.forEach(function (item) {
      const selected = item.edge.key === state.selectedEdgeKey || item.edge.key === state.threeDHoverEdgeKey;
      const adjacent = item.edge.source === focusId || item.edge.target === focusId;
      const callHop = callHopForEdge(item.edge);
      const tracing = Boolean(state.hoverSignature);
      const alpha = tracing ? (Number.isFinite(callHop) ? [0, 1, .65, .38][callHop] : .035) : selected ? 1 : focusId ? adjacent ? .70 : .065 : .23;
      const group = state.groupByNodeId.get(item.edge.source);
      const color = group ? group.color : "#8fcbeb";
      context.save();
      context.globalAlpha = forcedColors ? 1 : alpha;
      context.strokeStyle = forcedColors ? foreground : Number.isFinite(callHop) ? CALL_HOP_COLORS[callHop] : selected ? "#b0fff1" : color;
      context.lineWidth = (Number.isFinite(callHop) ? 3.3 - callHop * .55 : selected ? 2.3 : adjacent ? 1.5 : .75) * dpr;
      if (selected && !forcedColors) { context.shadowColor = color; context.shadowBlur = 9 * dpr; }
      const dx = item.target.x - item.source.x, dy = item.target.y - item.source.y;
      const length = Math.max(1, Math.hypot(dx, dy));
      const curve = Math.min(18 * dpr, length * .055);
      item.control = { x: (item.source.x + item.target.x) / 2 - dy / length * curve, y: (item.source.y + item.target.y) / 2 + dx / length * curve };
      context.beginPath(); context.moveTo(item.source.x, item.source.y);
      if (item.edge.source === item.edge.target) {
        item.control = { x: item.source.x - 28 * dpr, y: item.source.y - 55 * dpr };
        item.control2 = { x: item.source.x + 28 * dpr, y: item.source.y - 55 * dpr };
        context.bezierCurveTo(item.control.x, item.control.y, item.control2.x, item.control2.y, item.target.x, item.target.y);
      } else context.quadraticCurveTo(item.control.x, item.control.y, item.target.x, item.target.y);
      context.stroke();
      if (selected || Number.isFinite(callHop) || adjacent || state.threeDGraph.edges.length < 55) {
        const t = .78;
        const ax = (1-t)*(1-t)*item.source.x + 2*(1-t)*t*item.control.x + t*t*item.target.x;
        const ay = (1-t)*(1-t)*item.source.y + 2*(1-t)*t*item.control.y + t*t*item.target.y;
        const arrowControl = item.control2 || item.control;
        const angle = Math.atan2(item.target.y-arrowControl.y, item.target.x-arrowControl.x);
        const size = (selected ? 5 : 3) * dpr;
        context.beginPath(); context.moveTo(ax,ay); context.lineTo(ax-Math.cos(angle-.42)*size,ay-Math.sin(angle-.42)*size); context.lineTo(ax-Math.cos(angle+.42)*size,ay-Math.sin(angle+.42)*size); context.closePath(); context.fillStyle=context.strokeStyle; context.fill();
      }
      if (selected || Number.isFinite(callHop)) {
        context.font = "500 " + 10*dpr + "px system-ui, sans-serif"; context.textAlign="center";
        const caption=Number.isFinite(callHop) ? "CALLS · "+callHop+"차" : relationLabel(item.edge.type)+(item.edge.aggregate?" · "+item.edge.canonicalKeys.length:""); const measured=context.measureText(caption).width;
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
      const selected = item.node.id === state.selectedId || item.node.canonicalId === state.selectedId;
      const hovered = item.node.id === state.threeDHoverNodeId;
      const focused = document.activeElement === dom.graph3dCanvas && focusedNode && focusedNode.id === item.node.id;
      const color = forcedColors ? foreground : group ? group.color : "#91dce7";
      const callRelated = state.hoverViewNodes.has(item.node.id);
      const emphasis = selected || hovered || focused || (Boolean(state.hoverSignature) && callRelated);
      const radius = Math.max(3.4 * dpr, Math.min(13*dpr, (anchor ? 8 : 4.7) * item.scale));
      context.save();
      context.globalAlpha = forcedColors ? 1 : state.hoverSignature ? callRelated ? 1 : .16 : focusId && !connected.has(item.node.id) ? .25 : Math.max(.45, Math.min(1,item.perspective));
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
    let symbolLabelsDrawn = 0;
    state.threeDProjectedNodes.slice().sort(function(a,b){return a.labelPriority-b.labelPriority || a.z-b.z || a.node.id.localeCompare(b.node.id);}).forEach(function(item,index){
      if(compactLabels ? symbolLabelsDrawn>=symbolLabelLimit : index>=symbolLabelLimit && item.labelPriority>0)return;
      if(state.threeDGraph.nodes.length>55 && item.labelPriority===3)return;
      const compactName = compactLabels && item.node.atlasGroup && item.node.bucketKind === "module" ? compactModuleCaption(item.node.name, 18) : item.node.name;
      const caption=shortLabel(compactName+(item.node.atlasGroup?" · "+item.node.memberCount:""),compactLabels?(item.labelPriority===0?24:22):(item.labelPriority===0?44:28));
      const fontSize=(item.labelPriority===0?12:10)*dpr;
      context.font=(item.labelPriority===0?"600 ":"400 ")+fontSize+"px system-ui, sans-serif";
      const width=context.measureText(caption).width+12*dpr;
      const x=item.x-width/2,y=item.y+item.hitRadius+5*dpr;
      const box={x:x,y:y-10*dpr,w:width,h:18*dpr};
      if(x<8*dpr||x+width>viewport.width-8*dpr||box.y<labelTop||y>viewport.height-90*dpr)return;
      if(occupied.some(function(other){return box.x<other.x+other.w+4*dpr&&box.x+box.w+4*dpr>other.x&&box.y<other.y+other.h+4*dpr&&box.y+box.h+4*dpr>other.y;}))return;
      occupied.push(box);
      symbolLabelsDrawn += 1;
      context.fillStyle=forcedColors?background:"rgba(6,17,29,.86)"; context.fillRect(box.x,box.y,box.w,box.h);
      context.fillStyle=forcedColors?foreground:item.labelPriority===0?"#e4fffa":item.labelPriority===3?"#86a5b7":"#b8d2e0";
      context.textAlign="center"; context.fillText(caption,item.x,y+2*dpr);
    });
    state.threeDLastRenderMs=Math.max(0,(window.performance&&typeof window.performance.now==="function"?window.performance.now():Date.now())-startedAt);
    const statusText=state.hoverSignature ? "정적 CALLS · "+state.hoverDepth+"차까지 · 원본 관계 "+state.callHighlight.edges.size+"개 · 화면 선 "+state.hoverViewEdges.size+"개" : state.threeDGraph.cumulative ? "1–"+state.layerDepth+"단계 · "+state.threeDGraph.nodes.length+"개 항목 · Shift + 드래그로 이동" : state.threeDGraph.aggregate ? "표시용 집계 · 심볼 / 원본 관계는 선택해서 탐색" : state.threeDGroups.length+"개 모듈 / 폴더 · "+state.threeDGraph.nodes.length+"개 심볼";
    if(dom.graph3dStatus.textContent!==statusText)dom.graph3dStatus.textContent=statusText;
    const summary=statusText+", 관계 "+state.threeDGraph.edges.length+"개. "+(focusedNode?"키보드 초점: "+focusedNode.name+". ":"")+"목록 보기에서 같은 항목을 선택할 수 있습니다.";
    if(dom.graph3dSummary.textContent!==summary)dom.graph3dSummary.textContent=summary;
    return true;
  }

  function schedule3dFrame() {
    stop3dFrame();
    if (document.visibilityState === "hidden" || dom.graphView.hidden || state.activeLens === "changes") return;
    state.threeDFrame = window.requestAnimationFrame(function tick(timestamp) {
      state.threeDFrame = 0;
      if (document.visibilityState === "hidden" || dom.graphView.hidden || state.activeLens === "changes") return;
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
    if (!position) return;
    state.cameraFocusId = nodeId;
    const target = { x: position.x, y: position.y, z: position.z, zoom: state.layerDepth ? state.camera.zoom : Math.max(1.05, Math.min(1.4, state.camera.zoom)) };
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

  function showGraphListFallback() {
    stop3dFrame();
    state.threeDGraph = null;
    setHidden(dom.graph3d, true);
    dom.graphTextAlternative.open = true;
    dom.atlasBrowser.open = true;
    dom.graphView.dataset.presentation = "list";
    dom.graphNote.textContent += " · 3D Canvas를 사용할 수 없어 목록으로 표시합니다.";
    announce("3D Canvas를 사용할 수 없어 목록으로 표시합니다.");
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
      const length = Math.hypot(item.control.x-item.source.x,item.control.y-item.source.y) + Math.hypot(item.target.x-item.control.x,item.target.y-item.control.y);
      const segments = Math.max(16, Math.min(512, Math.ceil(length / Math.max(4, 8 * ratio))));
      let previous = item.source;
      for (let step = 1; step <= segments; step += 1) {
        const t = step / segments, u = 1 - t;
        const point = { x:u*u*item.source.x+2*u*t*item.control.x+t*t*item.target.x, y:u*u*item.source.y+2*u*t*item.control.y+t*t*item.target.y };
        const dx=point.x-previous.x, dy=point.y-previous.y, lengthSquared=dx*dx+dy*dy;
        const fraction=lengthSquared ? Math.max(0,Math.min(1,((x-previous.x)*dx+(y-previous.y)*dy)/lengthSquared)) : 0;
        const distance=Math.hypot(x-previous.x-fraction*dx,y-previous.y-fraction*dy);
        if(distance<bestDistance){best=item.edge;bestDistance=distance;}
        previous=point;
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
    if (!state.atlasOverview && !state.atlasGroupKey && (!state.rootId || !nodeById.has(state.rootId))) state.rootId = defaultSeed(state.activeLens);
    clearCallHover();
    state.lastCallHover = null;
    const graph = bounded3dGraph(
      state.layerDepth ? cumulativeLayerGraph(state.layerDepth) : state.atlasOverview ? atlasGraph() : state.atlasGroupKey ? groupMemberGraph() : neighborhood(state.rootId, state.activeLens, state.depth, state.direction)
    );
    state.renderedGraph = graph;
    if (graph.cumulative && state.layerCameraPending) {
      state.threeDPositions.clear(); buildCumulativeLayout(graph);
      const candidates = graph.nodes.filter(function (node) { return node.atlasGroup.key === state.layerFocusGroup; });
      const target = candidates.filter(function (node) { return node.layerDepth === graph.layerDepth; })[0] || candidates[candidates.length - 1];
      const position = target && state.threeDPositions.get(target.id);
      if (position) Object.assign(state.camera, { x: position.x, y: position.y, z: position.z });
      state.layerCameraPending = false;
    }
    if (state.selectedEdgeKey && !graph.edges.some(function (edge) { return edge.key === state.selectedEdgeKey; })) {
      state.selectedEdgeKey = "";
      if (state.selectedId && nodeById.has(state.selectedId)) renderDetails(nodeById.get(state.selectedId));
    }
    const token = state.renderToken + 1;
    state.renderToken = token;
    setHidden(dom.graphEmpty, graph.nodes.length > 0);
    dom.graph3dCanvas.setAttribute(
      "aria-label",
      typeLabel(nodeById.get(state.rootId) ? nodeById.get(state.rootId).type : "") +
        " 중심의 정적 관계 그래프. 노드 " +
        graph.nodes.length +
        "개, 관계 " +
        graph.edges.length +
        "개."
    );
    dom.graphNote.textContent = graph.aggregate
      ? "현재 지도: 원본 심볼 " + formatCount(graph.representedNodes) + "/" + formatCount(graph.eligibleNodeCount) + "개 · 내부 관계 " + formatCount(graph.internalKeys.length) + "개 접힘 · 전체 관계 " + formatCount(graph.totalEligibleEdges) + "개 탐색 가능" + (graph.truncated ? " · 다른 페이지 있음" : "")
      : state.depth + "단계 이웃: 심볼 " + formatCount(graph.nodes.length) + "/" + formatCount(graph.totalNeighborhoodNodes) + "개 · 관계 " + formatCount(graph.edges.length) + "/" + formatCount(graph.totalNeighborhoodEdges) + "개" + (graph.truncated ? " · 다른 페이지 / 전체 관계 목록 이용" : "");
    const filteredNodes = graph.aggregate ? graph.filteredNodes : atlasInventory().filteredNodes;
    const filteredEdges = graph.aggregate ? graph.filteredEdges : atlasInventory().filteredEdges;
    if (filteredNodes || filteredEdges) dom.graphNote.textContent += " · 필터 적용";
    dom.coverageSummary.textContent = graph.aggregate
      ? "원본 관계 " + formatCount(graph.visibleKeys.length) + "개 선 표시 + 접힌 내부 " + formatCount(graph.internalKeys.length) + " + 다른 지도 페이지 " + formatCount(graph.offPageKeys.length) + " (현재 지도와 경계 " + formatCount(graph.boundaryKeys.length) + ") + 다른 선 페이지 " + formatCount(graph.offLineKeys.length) + " = 필터 내 " + formatCount(graph.totalEligibleEdges) + "개. 필터 제외: 심볼 " + formatCount(filteredNodes) + "개, 관계 " + formatCount(filteredEdges) + "개."
      : "전체 " + state.depth + "단계 이웃 관계: " + formatCount(graph.edges.length) + "개 선 표시 + 다른 지도 페이지 " + formatCount(graph.offPageKeys.length) + " (현재 지도와 경계 " + formatCount(graph.boundaryKeys.length) + ") + 다른 선 페이지 " + formatCount(graph.offLineKeys.length) + " = " + formatCount(graph.totalNeighborhoodEdges) + "개. 이웃 밖 관계도 아래 전체 원본 목록에서 탐색할 수 있습니다.";
    if (graph.cumulative) {
      dom.graphNote.textContent = "1–" + graph.layerDepth + "단계 누적 · 모든 영역 " + formatCount(graph.nodes.length) + "개 항목 · 아래 레이어에 접힌 관계 " + formatCount(graph.internalKeys.length) + "개 · Shift + 드래그 이동";
      dom.coverageSummary.textContent = "상위 레이어 유지 · 원본 관계 " + formatCount(graph.visibleKeys.length) + "개 선 표시 + 아래에 접힌 내부 " + formatCount(graph.internalKeys.length) + "개 = " + formatCount(edges.length) + "개. 모듈/폴더 묶음은 표시용이며 추가 관계를 만들지 않습니다.";
    }
    renderAtlasNavigation(graph);

    renderGraphTextAlternative(graph);

    if (!graph.nodes.length) {
      stop3dFrame();
      state.threeDGraph = null;
      if (state.threeDContext) state.threeDContext.clearRect(0, 0, dom.graph3dCanvas.width, dom.graph3dCanvas.height);
      if (announceResult !== false) announce("표시할 관계가 없습니다.");
      return;
    }
    if (renderGraph3d(graph)) {
      setHidden(dom.graph3d, false);
      dom.graphView.dataset.presentation = "3d";
      if (announceResult !== false) announce("3D 노드 " + graph.nodes.length + "개와 관계 " + graph.edges.length + "개를 표시했습니다.");
    } else showGraphListFallback();
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
      make("div", "section-kicker", changes.sourceScopeChanged || changes.changeBasis === "source_scope_change" ? "분석 소스 범위 변경" : text(changes.basis, "정적 구조 비교")),
      make("h3", "", shortLabel(text(changes.beforeSnapshotId, "이전") + " → " + text(changes.afterSnapshotId, "현재"), 110)),
      make(
        "p",
        "view-description",
        (changes.sourceScopeChanged ? "분석 범위가 달라졌습니다. 추가·삭제 수치는 코드 수정만을 뜻하지 않습니다." : "정적 스냅샷 비교") + (changes.truncated ? " · 목록 일부 표시" : "")
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
    if (!preserveState) state.layerDepth = 0;
    lens = LENS_ALIASES[lens] || lens;
    if (!LENS_COPY[lens]) return;
    if (!preserveState && (lens !== state.activeLens || preferredRoot)) rememberSelection();
    const changedLens = state.activeLens !== lens;
    state.activeLens = lens;
    if (changedLens && !preserveState) { state.relationFilter = "all"; dom.relationFilter.value = "all"; }
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
    setHidden(dom.atlasControls, !graphMode);
    setHidden(dom.graphTextAlternative, !graphMode);
    if (lens === "changes") renderChanges();
    if (preferredRoot && nodeById.has(preferredRoot)) {
      state.rootId = preferredRoot; state.selectedId = preferredRoot; state.selectedEdgeKey = ""; state.selectedEvidenceId = ""; state.atlasOverview = false; state.atlasGroupKey = "";
    } else if (lens !== "impact" && lens !== "changes" && changedLens && !preserveState) {
      state.atlasOverview = true; state.atlasGroupKey = ""; state.displayDepth = 1; state.componentId = ""; state.atlasPage = 0; state.edgePage = 0; state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = ""; setHidden(dom.detailsPanel, true); reset3dCamera();
    }
    if (lens === "impact") {
      state.atlasOverview = false; state.atlasGroupKey = "";
      if (changedLens && !preserveState) { state.neighborhoodPage = 0; state.neighborhoodEdgePage = 0; state.direction = "incoming"; dom.directionSelect.value = "incoming"; }
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
    dom.evidenceBadge.textContent = "정적 소스 · 실행 미확인";
    dom.sourceRoots.textContent = "분석 대상: " + (arrayOrEmpty(meta.sourceRoots).length ? meta.sourceRoots.join(", ") : meta.sourceScope === "legacy_unknown" || !meta.sourceScope ? "이전 스냅샷 · 범위 메타데이터 없음" : "저장소 전체") + " · 경로 분류는 후보이며 배포 여부를 뜻하지 않습니다.";
    const warningCount = finiteNumber(statistics.warnings, warnings.length);
    dom.warningBadge.textContent = warningCount ? "분석 경고 " + formatCount(warningCount) : "분석 정보";
    dom.warningBadge.classList.toggle("status-badge--warning", warningCount > 0);
    dom.copyLink.disabled = !meta.snapshotId;
    document.title = "Code Ontology — " + repositoryName;
  }

  function bindEvents() {
    dom.atlasHome.addEventListener("click", showAtlasHome);
    dom.layerNext.addEventListener("click", showNextLayer);
    dom.layerPrevious.addEventListener("click", showPreviousLayer);
    dom.groupPrevious.addEventListener("click", function () { rememberSelection(); if (state.atlasOverview) { state.atlasPage -= 1; state.edgePage = 0; } else { state.neighborhoodPage -= 1; state.neighborhoodEdgePage = 0; } renderGraph(); updateSelectionLink(); });
    dom.groupNext.addEventListener("click", function () { rememberSelection(); if (state.atlasOverview) { state.atlasPage += 1; state.edgePage = 0; } else { state.neighborhoodPage += 1; state.neighborhoodEdgePage = 0; } renderGraph(); updateSelectionLink(); });
    dom.edgePrevious.addEventListener("click", function () { if (state.atlasOverview) state.edgePage -= 1; else state.neighborhoodEdgePage -= 1; renderGraph(); updateSelectionLink(); });
    dom.edgeNext.addEventListener("click", function () { if (state.atlasOverview) state.edgePage += 1; else state.neighborhoodEdgePage += 1; renderGraph(); updateSelectionLink(); });
    dom.relationPrevious.addEventListener("click", function () { state.relationPage -= 1; renderCanonicalRelations(); updateSelectionLink(); });
    dom.relationNext.addEventListener("click", function () { state.relationPage += 1; renderCanonicalRelations(); updateSelectionLink(); });
    dom.displayDepth.addEventListener("change", function () {
      rememberSelection();
      const requested = Math.max(1, Math.min(3, finiteNumber(dom.displayDepth.value, 1)));
      if (requested >= 2 && !state.atlasGroupKey) { dom.displayDepth.value = String(state.displayDepth); dom.atlasBrowser.open = true; announce("먼저 펼칠 모듈을 선택하세요."); return; }
      if (requested === 3 && !state.componentId) { dom.displayDepth.value = String(state.displayDepth); dom.atlasBrowser.open = true; announce("먼저 펼칠 클래스나 함수를 선택하세요."); return; }
      state.displayDepth = requested; state.atlasOverview = true; revealAtlasSelection(); state.edgePage = 0; renderGraph(); updateViewHeading(); updateSelectionLink();
    });
    dom.hoverDepth.addEventListener("change", function () {
      state.hoverDepth = Math.max(1, Math.min(3, finiteNumber(dom.hoverDepth.value, 1)));
      const anchor = state.lastCallHover;
      state.hoverSignature = "";
      if (anchor) setCallHover(anchor.nodeId, anchor.edge, anchor.members);
      else if (state.selectedEdgeKey) setCallHover("", edgeByKey.get(state.selectedEdgeKey));
      else if (state.selectedId) setCallHover(state.selectedId, null);
      else clearCallHover();
      updateSelectionLink();
    });
    function updateAtlasFilter() {
      rememberSelection();
      state.sourceScope = dom.sourceScope.value || "all";
      state.relationFilter = dom.relationFilter.value || "all";
      state.categoryFilter = dom.categoryFilter.value || "all";
      state.groupQuery = dom.groupSearch.value;
      state.atlasPage = 0; state.edgePage = 0; state.relationPage = 0;
      if (state.activeLens !== "architecture") { state.activeLens = "architecture"; updateLensButtons("architecture"); }
      state.atlasOverview = true;
      state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = "";
      setHidden(dom.detailsPanel, true); runSearch(); renderGraph(); updateViewHeading(); updateSelectionLink();
    }
    dom.sourceScope.addEventListener("change", updateAtlasFilter);
    dom.relationFilter.addEventListener("change", updateAtlasFilter);
    dom.categoryFilter.addEventListener("change", updateAtlasFilter);
    dom.groupSearch.addEventListener("input", updateAtlasFilter);
    dom.viewBack.addEventListener("click", goBack);
    dom.closeDetails.addEventListener("click", function () { setHidden(dom.detailsPanel, true); dom.graph3dCanvas.focus(); draw3dScene(0); });
    dom.closeSearch.addEventListener("click", function () { setHidden(dom.searchPanel, true); dom.searchInput.setAttribute("aria-expanded", "false"); dom.searchInput.removeAttribute("aria-activedescendant"); if (state.threeDAvailable) dom.graph3dCanvas.focus(); else dom.graphTextAlternative.focus(); });
    dom.searchInput.addEventListener("focus", function () { [dom.atlasSettings, dom.atlasBrowser, dom.mapHelp].forEach(function (disclosure) { disclosure.open = false; }); dom.atlasControls.dataset.disclosureOpen = "false"; setHidden(dom.searchPanel, false); dom.searchInput.setAttribute("aria-expanded", "true"); syncActiveSearchOption(false); });
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
      if (selected) selectSearchResult(selected.id);
    });
    dom.searchInput.setAttribute("aria-controls", "search-results");
    dom.searchInput.setAttribute("aria-autocomplete", "list");
    const disclosures = [dom.atlasSettings, dom.atlasBrowser, dom.mapHelp];
    disclosures.forEach(function (disclosure) {
      disclosure.addEventListener("toggle", function () {
        if (disclosure.open) disclosures.forEach(function (other) { if (other !== disclosure) other.open = false; });
        dom.atlasControls.dataset.disclosureOpen = disclosures.some(function (panel) { return panel.open; }) ? "true" : "false";
      });
    });
    dom.mapHelpClose.addEventListener("click", function () { dom.mapHelp.open = false; dom.atlasControls.dataset.disclosureOpen = "false"; dom.mapHelpSummary.focus({ preventScroll: true }); });
    dom.atlasSettingsClose.addEventListener("click", function () { dom.atlasSettings.open = false; dom.atlasControls.dataset.disclosureOpen = "false"; dom.atlasSettingsSummary.focus({ preventScroll: true }); });
    dom.atlasBrowserClose.addEventListener("click", function () { dom.atlasBrowser.open = false; dom.atlasControls.dataset.disclosureOpen = "false"; dom.atlasBrowserSummary.focus({ preventScroll: true }); });
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
          setHidden(dom.searchPanel, true); dom.searchInput.setAttribute("aria-expanded", "false"); dom.searchInput.removeAttribute("aria-activedescendant"); dom.searchInput.blur();
        }
      }
    });
    dom.languageFilter.addEventListener("change", runSearch);
    dom.typeFilter.addEventListener("change", runSearch);
    dom.depthSelect.addEventListener("change", function () {
      state.depth = Math.max(1, Math.min(3, finiteNumber(dom.depthSelect.value, 2)));
      state.neighborhoodPage = 0; state.neighborhoodEdgePage = 0;
      renderGraph();
    });
    dom.directionSelect.addEventListener("change", function () {
      state.direction = ["both", "incoming", "outgoing"].includes(dom.directionSelect.value)
        ? dom.directionSelect.value
        : "both";
      state.neighborhoodPage = 0; state.neighborhoodEdgePage = 0;
      updateViewHeading();
      renderGraph();
    });
    dom.motionToggle.addEventListener("click", function () {
      state.motionEnabled = !state.motionEnabled;
      updateMotionControl();
      draw3dScene(0);
      schedule3dFrame();
      announce(state.motionEnabled ? "3D 자동 움직임을 켰습니다." : "3D 자동 움직임을 멈췄습니다.");
    });
    dom.zoomIn.addEventListener("click", function () { state.camera.zoom = Math.min(2.4, state.camera.zoom * 1.16); draw3dScene(0); });
    dom.zoomOut.addEventListener("click", function () { state.camera.zoom = Math.max(0.35, state.camera.zoom / 1.16); draw3dScene(0); });
    dom.fitGraph.addEventListener("click", reset3dCamera);
    dom.resetView.addEventListener("click", function () {
      rememberSelection();
      state.layerDepth = 0;
      state.depth = 2; state.direction = "both"; dom.depthSelect.value = "2"; dom.directionSelect.value = "both";
      state.rootId = ""; state.selectedId = ""; state.selectedEdgeKey = ""; state.selectedEvidenceId = ""; state.atlasOverview = true; state.atlasGroupKey = "";
      state.atlasPage = 0; state.memberPage = 0; state.displayDepth = 1; state.componentId = ""; state.edgePage = 0;
      setHidden(dom.detailsPanel, true); reset3dCamera(); switchLens("architecture", "", true);
    });
    dom.graph3dCanvas.addEventListener("pointerdown", function (event) {
      clearCallHover();
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
        if (hovered || hoveredEdge) setCallHover(hovered ? hovered.node.id : "", hoveredEdge); else clearCallHover();
        return;
      }
      const dx = event.clientX - state.threeDPointer.x;
      const dy = event.clientY - state.threeDPointer.y;
      state.threeDDragDistance += Math.abs(dx) + Math.abs(dy);
      if (event.shiftKey && state.layerDepth) {
        const distance = 1.8 / state.camera.zoom;
        state.camera.x -= dx * distance * Math.cos(state.camera.yaw);
        state.camera.z += dx * distance * Math.sin(state.camera.yaw);
        state.camera.y -= dy * distance;
      } else {
        state.camera.yaw += dx * 0.005;
        state.camera.pitch = Math.max(-1.35, Math.min(1.35, state.camera.pitch + dy * 0.005));
      }
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
    dom.graph3dCanvas.addEventListener("pointerleave", clearCallHover);
    dom.graph3dCanvas.addEventListener("blur", clearCallHover);
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
        if (focused && ["ArrowUp", "ArrowDown"].includes(event.key)) { state.threeDHoverNodeId = focused.id; setCallHover(focused.id, null); announce(focused.name + "에 키보드 초점 · 정적 호출 " + state.hoverDepth + "차"); }
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
    window.addEventListener("resize", function () { draw3dScene(0); });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") stop3dFrame();
      else if (
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
  if (initialSelection && initialSelection.navigation) Object.assign(state, initialSelection.navigation);
  dom.sourceScope.value = state.sourceScope; dom.relationFilter.value = state.relationFilter; dom.categoryFilter.value = state.categoryFilter; dom.groupSearch.value = state.groupQuery;
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
  ensure3dContext();
  switchLens(initialSelection ? initialSelection.lens : "architecture", initialSelection && !initialSelection.navigation.atlasGroupKey ? initialSelection.entity : "", true);
  if (initialSelection && initialSelection.navigation.atlasGroupKey && initialSelection.entity) { state.selectedId = initialSelection.entity; renderDetails(nodeById.get(state.selectedId)); updateViewHeading(); }
  if (initialSelection && initialSelection.edge) {
    state.selectedEdgeKey = initialSelection.edge.key;
    state.selectedEvidenceId = initialSelection.evidenceId;
    renderEdgeDetails(initialSelection.edge);
  }
  state.restoringSelection = false;
})();
