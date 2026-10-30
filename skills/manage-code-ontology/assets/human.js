(function () {
  "use strict";
  const FORMAT = "companion.human-summary.v1", MAX_BYTES = 131072;
  const copy = globalThis.CODE_ONTOLOGY_HUMAN_I18N || {};
  const t = function (key) { return copy[key] || key; };
  const el = function (id) { return document.getElementById(id); };
  document.querySelectorAll("[data-copy]").forEach(function (item) { item.textContent = t(item.dataset.copy); });
  let data = null, nodes = [], edges = [], points = [], yaw = -.35, pitch = .24, zoom = 1, selected = null;
  let frame = 0, started = 0, dragging = null, dirty = true;
  const motionPreference = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  let reduced = !!(motionPreference && motionPreference.matches);
  const canvas = el("human-canvas");
  let context = null;
  try { context = canvas && canvas.getContext ? canvas.getContext("2d") : null; } catch (_) { context = null; }
  const finite = function (x) { return typeof x === "number" && Number.isFinite(x); };
  const route = function (s) { return typeof s === "string" && /^(s[0-9]{6}|m[a-f0-9]{24})$/.test(s); };
  const own = function (o, key) { return Object.prototype.hasOwnProperty.call(o, key); };
  const count = function (n) { return Number.isSafeInteger(n) && n >= 0; };
  const object = function (o) { return o !== null && typeof o === "object" && !Array.isArray(o); };
  const fields = function (o, allowed) { return object(o) && Object.keys(o).every(function (key) { return allowed.includes(key); }); };
  function path(token) { return (document.body.dataset.humanBase || "") + token + ".html"; }
  function unavailable() { el("human-state").textContent = t("unavailable"); }
  function label(node) {return node.label === "Policy evidence" ? t("policy") : node.groupingBasis === "PRESENTATION_BUCKET" ? t(node.label==="Other structural groups"?"otherGroups":"otherAreas") : node.label;}
  function check(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const keys = ["format","snapshotId","viewId","chunkId","depth","nodes","edges","previous","next","parent","ontologyCoverage","presentationCoverage","bindings"];
    if (Object.keys(value).some(function (key) { return !keys.includes(key); })) return false;
    if (value.format !== FORMAT || value.chunkId !== document.body.dataset.humanChunk || !route(value.chunkId)) return false;
    if (typeof value.snapshotId !== "string" || value.snapshotId.length > 256 || !/^[a-f0-9]{24}$/.test(value.viewId)) return false;
    if (value.snapshotId !== document.body.dataset.humanSnapshot || value.viewId !== document.body.dataset.humanView) return false;
    if (![2,3].includes(value.depth) || !Array.isArray(value.nodes) || value.nodes.length > 32 || !Array.isArray(value.edges) || value.edges.length > 64) return false;
    const ids = new Set();
    for (const node of value.nodes) {
      if (!node || typeof node !== "object" || typeof node.id !== "string" || node.id.length > 64 || ids.has(node.id)) return false;
      if (!["area","module","summary"].includes(node.type) || typeof node.label !== "string" || node.label.length > 160) return false;
      if (own(node,"recordCount") && !count(node.recordCount) || own(node,"route") && !route(node.route)) return false;
      if (!fields(node,["id","type","label","recordCount","kinds","route","policySummaries","support","approval","facets","meaning","details","evidence","groupingBasis","sourceModuleRef"])) return false;
      if (own(node,"groupingBasis") && !["SOURCE_DIRECTORY","STORED_MODULE","PRESENTATION_BUCKET"].includes(node.groupingBasis)) return false;
      if (own(node,"sourceModuleRef") && (typeof node.sourceModuleRef!=="string" || node.sourceModuleRef.length>256)) return false;
      if (own(node,"evidence") && (!Array.isArray(node.evidence) || node.evidence.length > 3 || node.evidence.some(function (x) { return typeof x !== "string" || x.length > 256; }))) return false;
      if (own(node,"facets")) {
        if (!object(node.facets) || Object.keys(node.facets).length > 16) return false;
        for (const name of Object.keys(node.facets)) {
          const facet=node.facets[name];
          if (name.length > 64 || !fields(facet,["status","value","valueState"]) || !["UNKNOWN","SOURCE_SUPPORTED","DECLARED","NOT_APPLICABLE"].includes(facet.status)) return false;
          if (own(facet,"value") && !(facet.value===null || typeof facet.value==="boolean" || finite(facet.value) || typeof facet.value==="string" && facet.value.length<=120)) return false;
          if (own(facet,"valueState") && facet.valueState!=="COMPLEX_MCP_ONLY") return false;
        }
      }
      ids.add(node.id);
    }
    for (const edge of value.edges) {
      if (!fields(edge,["from","to","type","count","evidenceState"]) || !ids.has(edge.from) || !ids.has(edge.to) || typeof edge.type !== "string" || edge.type.length > 64 || !count(edge.count)) return false;
    }
    if (![value.previous,value.next,value.parent].every(function (x) { return x == null || route(x); })) return false;
    const o=value.ontologyCoverage,p=value.presentationCoverage;
    if (!fields(o,["selectedRecords","processedRecords","counts","completeness","relationOccurrences","flowAssessmentUnavailable","sourceRechecked","runtimeStatus","originalSummary","sourceFileOutcomes"])) return false;
    if (!(o.selectedRecords===null || count(o.selectedRecords)) || !count(o.processedRecords) || o.selectedRecords!==null && o.selectedRecords!==o.processedRecords) return false;
    if (!object(o.counts) || Object.keys(o.counts).length>7 || Object.values(o.counts).some(function(n){return !count(n);})) return false;
    if (!count(o.relationOccurrences) || !count(o.flowAssessmentUnavailable) || o.flowAssessmentUnavailable>o.relationOccurrences || o.completeness!=="UNKNOWN" || o.sourceRechecked!==false || o.runtimeStatus!=="NOT_OBSERVED") return false;
    const f=o.sourceFileOutcomes;
    if(!fields(f,["state","denominator","knownEntries","numerator","unknownDenominator","counts"]) || !["COMPLETE","PARTIAL","BLOCKED","UNKNOWN"].includes(f.state))return false;
    if(![f.denominator,f.knownEntries,f.numerator].every(function(n){return n===null||count(n);}) || typeof f.unknownDenominator!=="boolean" || !object(f.counts) || Object.values(f.counts).some(function(n){return !count(n);}))return false;
    if (!fields(p,["scope","shownGroups","totalGroups","hiddenGroups","maxDepth","fineDetail","privacyWithheld","privacyWithheldNotEqualToHidden","page","pages","hiddenRelationOccurrences","shownPolicyCards","totalPolicyCards","hiddenPolicyCards","shownNodes","evidenceLocatorCount","knownGroups","remainderRecords"])) return false;
    if (p.scope!=="summary_only" || p.maxDepth!==3 || p.fineDetail!=="MCP_ONLY" || p.privacyWithheld!=="UNKNOWN" || p.privacyWithheldNotEqualToHidden!==true) return false;
    if (![p.shownGroups,p.knownGroups,p.remainderRecords].every(count)) return false;
    if (p.totalGroups===null) {if(p.hiddenGroups!==null || p.remainderRecords<1)return false;}
    else if(![p.totalGroups,p.hiddenGroups].every(count) || p.totalGroups-p.shownGroups!==p.hiddenGroups || p.remainderRecords!==0)return false;
    if(p.shownNodes!==value.nodes.length || !count(p.evidenceLocatorCount) || p.evidenceLocatorCount>18)return false;
    for (const key of ["page","pages","hiddenRelationOccurrences","shownPolicyCards","totalPolicyCards","hiddenPolicyCards"]) if(own(p,key)&&!count(p[key]))return false;
    if (own(p,"shownPolicyCards") && (p.shownPolicyCards>6 || p.totalPolicyCards-p.shownPolicyCards!==p.hiddenPolicyCards)) return false;
    return object(value.bindings) && Object.keys(value.bindings).length <= 12 && Object.values(value.bindings).every(function(x){return typeof x==="string" && x.length<=256;});
  }
  function link(parent, token, label) {
    if (!route(token)) return;
    const a = document.createElement("a"); a.href = path(token); a.textContent = label; parent.appendChild(a);
  }
  function focus(node) {
    selected = node.id;
    document.querySelectorAll(".card").forEach(function (card) { card.classList.toggle("is-selected",card.dataset.node === selected); });
    zoom = Math.min(2.2, zoom + .15); started = performance.now(); dirty = true; schedule();
  }
  function renderList(query) {
    const box = el("human-list"); box.replaceChildren();
    const term = query.trim().toLocaleLowerCase();
    const filtered = nodes.filter(function (node) { return !term || node.label.toLocaleLowerCase().includes(term); });
    const shown = filtered.slice(0, term ? 20 : 32);
    el("human-search-count").textContent = shown.length + " / " + filtered.length;
    for (const node of shown) {
      const article = document.createElement("article"); article.className = "card " + node.type; article.dataset.node = node.id;
      const heading = document.createElement("h2"); heading.textContent = label(node); article.appendChild(heading);
      const description = document.createElement("p");
      description.textContent = own(node,"recordCount") ? String(node.recordCount)+" "+t("records") : t("complex"); article.appendChild(description);
      if (node.groupingBasis === "SOURCE_DIRECTORY") {const basis=document.createElement("small");basis.textContent=t("structural");article.appendChild(basis);}
      if (node.type === "summary") {
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify({support:node.support,approval:node.approval,meaning:node.meaning,facets:node.facets},null,2); article.appendChild(pre);
        const refs = document.createElement("small"); refs.textContent = "MCP · " + (Array.isArray(node.evidence) ? node.evidence.slice(0,3).join(" · ") : "UNKNOWN"); article.appendChild(refs);
      }
      const select = document.createElement("button"); select.textContent = "3D"; select.addEventListener("click",function () { focus(node); }); article.appendChild(select);
      if (node.route) link(article,node.route,t("focus"));
      box.appendChild(article);
    }
    if (!shown.length) { const p=document.createElement("p"); p.textContent=t("noMatch"); box.appendChild(p); }
  }
  function metadata() {
    const o = data.ontologyCoverage, p = data.presentationCoverage, box = el("human-counts"); box.replaceChildren();
    const rows = [[t("original"),o.selectedRecords == null ? "UNKNOWN" : o.selectedRecords],
      [t("files"),o.sourceFileOutcomes.denominator==null ? "UNKNOWN" : o.sourceFileOutcomes.denominator],
      [t("shown"),p.shownGroups+" / "+(p.totalGroups===null?"UNKNOWN":p.totalGroups)], [t("nodes"),p.shownNodes], [t("locators"),p.evidenceLocatorCount],
      [t("hidden"),p.hiddenGroups===null?"UNKNOWN":p.hiddenGroups], [t("privacy"),p.privacyWithheld], [t("depth"),data.depth+" / 3"],
      [t("flows"),o.relationOccurrences+" / "+o.flowAssessmentUnavailable]];
    if (own(p,"totalPolicyCards")) rows.push([t("cards"),p.shownPolicyCards+" / "+p.totalPolicyCards]);
    if(p.remainderRecords)rows.push([t("remainder"),p.remainderRecords]);
    for (const row of rows) { const span=document.createElement("span"); span.textContent=row[0]+": "+String(row[1]); box.appendChild(span); }
    const note=document.createElement("p"); note.textContent=t("independent"); box.appendChild(note);
    el("human-evidence").textContent = JSON.stringify({bindings:data.bindings,ontologyCoverage:o,presentationCoverage:p},null,2);
    const nav = el("human-pages"); nav.replaceChildren();
    link(nav,data.parent,t("back")); link(nav,data.previous,t("previous")); link(nav,data.next,t("next"));
  }
  function schedule() { if (!frame && !document.hidden && context) frame=requestAnimationFrame(draw); }
  function draw(now) {
    frame=0; if (!data || !context || document.hidden) return;
    const size=canvas.getBoundingClientRect(), dpr=Math.min(2,globalThis.devicePixelRatio || 1), width=Math.max(200,size.width), height=Math.max(240,size.height);
    if (canvas.width !== Math.round(width*dpr) || canvas.height !== Math.round(height*dpr)) {canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);dirty=true;}
    const progress=reduced ? 1 : Math.min(1,(now-started)/550);
    if (!dirty && progress === 1) return;
    context.setTransform(dpr,0,0,dpr,0,0); context.clearRect(0,0,width,height);
    points=[];const visible=new Map(), scale=Math.min(width,height)*.30*zoom;
    nodes.forEach(function (node,i) {
      const angle=i*2.399963, radius=node.type === "area" ? .15 : .45+Math.sqrt(i/nodes.length)*.7;
      let x=Math.cos(angle)*radius,y=Math.sin(angle)*radius*.65,z=((i%5)-2)*.24*progress;
      const rx=x*Math.cos(yaw)+z*Math.sin(yaw),rz=-x*Math.sin(yaw)+z*Math.cos(yaw);
      const ry=y*Math.cos(pitch)-rz*Math.sin(pitch),depth=y*Math.sin(pitch)+rz*Math.cos(pitch),perspective=3/(3+depth);
      const point={node:node,x:width/2+rx*scale*perspective,y:height/2+ry*scale*perspective,z:depth,r:node.type === "area" ? 9 : 6};
      points.push(point);visible.set(node.id,point);
    });
    for (const edge of edges) {
      const a=visible.get(edge.from),b=visible.get(edge.to); if(!a||!b) continue;
      context.strokeStyle=edge.type === "CONTAINS" ? "#3c648a88" : "#96d4dcaa";context.lineWidth=edge.type === "CONTAINS" ? 1 : 1.5;
      context.beginPath();context.moveTo(a.x,a.y);context.lineTo(b.x,b.y);context.stroke();
      if(edge.type !== "CONTAINS") {const angle=Math.atan2(b.y-a.y,b.x-a.x);context.beginPath();context.moveTo(b.x,b.y);context.lineTo(b.x-9*Math.cos(angle-.4),b.y-9*Math.sin(angle-.4));context.lineTo(b.x-9*Math.cos(angle+.4),b.y-9*Math.sin(angle+.4));context.closePath();context.fillStyle="#96d4dc";context.fill();}
    }
    points.sort(function(a,b){return b.z-a.z;});
    for(const point of points) {
      context.beginPath();context.arc(point.x,point.y,point.r+(point.node.id===selected?3:0),0,Math.PI*2);context.fillStyle=point.node.type === "area" ? "#a6d8ff" : point.node.type === "summary" ? "#c6adf5" : "#74b5de";context.fill();
      context.font="12px system-ui";context.fillStyle="#e3eeff";
      const caption=label(point.node),short=caption.length>30 ? caption.slice(0,27)+"…" : caption;
      context.fillText(short,Math.max(8,Math.min(width-170,point.x+12)),Math.max(15,Math.min(height-8,point.y-8)));
    }
    dirty=false;if(progress<1)schedule();
  }
  globalThis.CODE_ONTOLOGY_HUMAN_REGISTER = function (raw) {
    // Producer emits ASCII JSON. Its string length is its UTF-8 byte length.
    if (data !== null || typeof raw !== "string" || raw.length > MAX_BYTES || /[^\x00-\x7f]/.test(raw)) {unavailable();return;}
    let value;
    try {value=JSON.parse(raw);if(!check(value))throw new Error("invalid_summary");} catch (_) {unavailable();return;}
    data=value;nodes=value.nodes;edges=value.edges;el("human-state").textContent=t("ready");metadata();renderList("");started=performance.now();schedule();
  };
  el("human-search").addEventListener("input",function(event){if(data)renderList(event.target.value);});
  el("human-full").addEventListener("click",function(){yaw=-.35;pitch=.24;zoom=1;selected=null;dirty=true;started=performance.now();schedule();});
  el("human-motion").addEventListener("click",function(){reduced=!reduced;dirty=true;schedule();});
  if(canvas) {
    canvas.addEventListener("pointerdown",function(event){dragging={x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY};canvas.setPointerCapture(event.pointerId);});
    canvas.addEventListener("pointermove",function(event){if(!dragging)return;yaw+=(event.clientX-dragging.x)*.008;pitch=Math.max(-1.2,Math.min(1.2,pitch+(event.clientY-dragging.y)*.008));dragging.x=event.clientX;dragging.y=event.clientY;dirty=true;schedule();});
    canvas.addEventListener("pointerup",function(event){if(dragging&&Math.hypot(event.clientX-dragging.startX,event.clientY-dragging.startY)<6){const bounds=canvas.getBoundingClientRect(),x=event.clientX-bounds.left,y=event.clientY-bounds.top;const hit=points.find(function(p){return Math.hypot(p.x-x,p.y-y)<20;});if(hit)focus(hit.node);}dragging=null;});
    canvas.addEventListener("pointercancel",function(){dragging=null;});
    canvas.addEventListener("wheel",function(event){event.preventDefault();zoom=Math.max(.4,Math.min(2.5,zoom-event.deltaY*.001));dirty=true;schedule();},{passive:false});
    canvas.addEventListener("keydown",function(event){if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","-"].includes(event.key))return;event.preventDefault();if(event.key==="ArrowLeft")yaw-=.15;if(event.key==="ArrowRight")yaw+=.15;if(event.key==="ArrowUp")pitch-=.1;if(event.key==="ArrowDown")pitch+=.1;if(event.key==="+")zoom=Math.min(2.5,zoom+.1);if(event.key==="-")zoom=Math.max(.4,zoom-.1);dirty=true;schedule();});
  }
  document.addEventListener("visibilitychange",function(){if(document.hidden&&frame){cancelAnimationFrame(frame);frame=0;}else{dirty=true;schedule();}});
  globalThis.addEventListener("resize",function(){dirty=true;schedule();});
  if (motionPreference && typeof motionPreference.addEventListener === "function") motionPreference.addEventListener("change",function(event){reduced=event.matches;dirty=true;schedule();});
  unavailable();
}());
