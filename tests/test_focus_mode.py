"""Execute shipped focus-navigation JS against synthetic source evidence.

The DOM/Canvas harness checks state, geometry and interaction contracts. It does
not establish real-browser layout, accessibility, frame rate or GPU performance.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from urllib.parse import urlencode

import test_workbench_quality_ui as ui
from test_workbench_spatial import SPATIAL_HELPERS, layered_modules


def dense_module() -> dict:
    """96 owners, 288 children, and all 4,560 pairwise owner calls."""
    nodes = [{"id": "m", "name": "module", "type": "Module", "language": "Python", "path": "m.py"}]
    edges = []
    for index in range(96):
        owner = f"c:{index}"
        nodes.append({"id": owner, "name": f"class{index:02}", "type": "Class", "language": "Python", "path": "m.py"})
        edges.append({"source": "m", "target": owner, "type": "DECLARES"})
        for child in range(3):
            symbol = f"f:{index}:{child}"
            nodes.append({"id": symbol, "name": f"method{child}", "type": "Method", "language": "Python", "path": "m.py"})
            edges.append({"source": owner, "target": symbol, "type": "DECLARES"})
        for target in range(index + 1, 96):
            edges.append({"source": owner, "target": f"c:{target}", "type": "CALLS"})
    return {"meta": {"snapshotId": "synthetic-focus-dense", "repositoryName": "Synthetic Focus"}, "nodes": nodes, "edges": edges}


FOCUS_HELPERS = SPATIAL_HELPERS + r"""
function startFocus(){enableCanvas(390,320);api.bindEvents();api.renderGraph(false);}
function enterFirst(){const item=api.state.renderedGraph.nodes[0];if(!item)throw Error('missing fixture item');api.selectFocusItem(item.id);return api.enterFocusSelection();}
function navigationSnapshot(){return JSON.stringify({mode:api.state.explorationMode,path:api.state.focusPath,pick:api.state.focusSelectedId,
  page:api.state.atlasPage,lines:api.state.edgePage,selected:api.state.selectedId,history:api.state.selectionHistory,
  graph:api.state.renderedGraph,camera:api.state.camera,url:window.location.href});}
function frameQueue(){
  let next=1,now=0,callbacks=new Map(),count=0,maxNodes=0,maxEdges=0;
  window.requestAnimationFrame=callback=>{const id=next++;callbacks.set(id,callback);return id;};
  window.cancelAnimationFrame=id=>callbacks.delete(id);
  return {flush(){while(callbacks.size&&count<100){const batch=[...callbacks.values()];callbacks.clear();now+=20;
    for(const callback of batch){count++;maxNodes=Math.max(maxNodes,api.state.threeDGraph.nodes.length);maxEdges=Math.max(maxEdges,api.state.threeDGraph.edges.length);callback(now);}}
    return {count,pending:callbacks.size,maxNodes,maxEdges};},pending:()=>callbacks.size};
}
"""


class FocusModeTests(unittest.TestCase):
    def run_app(self, script: str, payload=None, url="file:///snapshot.html", initialize=False):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable for shipped-JS focus checks")
        harness = ui.JS_HARNESS.replace(
            "buildModuleLayout,runSearch",
            "buildModuleLayout,project3d,reset3dCamera,cumulativeLayerGraph,focusExplorationGraph,focusExplorationActive,"
            "selectFocusItem,enterFocusSelection,setFocusDepth,focusBreadcrumb,setExplorationMode,showNextLayer,showPreviousLayer,"
            "validFocusPath,animateFocusEntry,cancelExplorationMotion,updateExplorationControls,setUiLanguage,setPresentation,"
            "UI_DICTIONARIES,UI_LOCALES,t,runSearch",
        )
        if initialize:
            harness = harness.replace("}; return;';", "};';")
        completed = subprocess.run([node, "-e", harness, str(ui.JS)],
            input=json.dumps({"payload": payload if payload is not None else layered_modules(), "script": FOCUS_HELPERS + script, "url": url}),
            text=True, encoding="utf-8", capture_output=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_default_requires_a_selection_and_rejects_skipping_without_mutation(self):
        result = self.run_app(r"""
            startFocus();const before=navigationSnapshot();
            const entered=api.enterFocusSelection(),selectionMessage=api.dom.explorationScope.textContent;
            const unchanged=before===navigationSnapshot();api.dom.explorationDepth.value='4';api.dom.explorationDepth.events.change();
            result={mode:api.state.explorationMode,depth:api.state.renderedGraph.focusDepth,motion:api.state.motionEnabled,entered,unchanged,
              skipUnchanged:before===navigationSnapshot(),selectDepth:api.dom.explorationDepth.value,selectionMessage,skipMessage:api.dom.explorationScope.textContent};
        """)
        self.assertEqual((result["mode"], result["depth"], result["motion"]), ("focus", 1, False))
        self.assertFalse(result["entered"])
        self.assertTrue(result["unchanged"] and result["skipUnchanged"])
        self.assertEqual(result["selectDepth"], "1")
        self.assertIn("선택", result["selectionMessage"])
        self.assertIn("한 단계씩", result["skipMessage"])

    def test_leaf_selection_keeps_source_scope_history_camera_and_link(self):
        payload = {"meta": {"snapshotId": "synthetic-leaf"}, "nodes": [
            {"id": "m", "name": "m", "type": "Module", "language": "Python", "path": "m.py"},
            {"id": "leaf", "name": "leaf", "type": "Function", "language": "Python", "path": "m.py"}],
            "edges": [{"source": "m", "target": "leaf", "type": "DECLARES"}]}
        result = self.run_app(r"""
            startFocus();enterFirst();api.selectFocusItem(api.state.renderedGraph.nodes[0].id);
            const before=navigationSnapshot(),entered=api.enterFocusSelection();
            result={entered,unchanged:before===navigationSnapshot(),message:api.dom.explorationScope.textContent,depth:api.state.renderedGraph.focusDepth};
        """, payload)
        self.assertFalse(result["entered"])
        self.assertTrue(result["unchanged"])
        self.assertEqual(result["depth"], 2)
        self.assertIn("더 깊은 선언 하위 항목이 없습니다", result["message"])

    def test_four_levels_follow_declared_ownership_and_native_breadcrumb_controls(self):
        result = self.run_app(r"""
            startFocus();const rows=[];
            function record(){const graph=api.state.renderedGraph;rows.push({depth:graph.focusDepth,ids:graph.nodes.map(n=>n.canonicalId),
              members:graph.nodes.flatMap(n=>n.memberIds),path:api.state.focusPath.slice(),crumbs:api.dom.explorationBreadcrumb.children.map(n=>({tag:n.tagName,label:n.textContent,title:n.title,current:n.attributes['aria-current']}))});}
            record();for(let i=0;i<3;i++){api.selectFocusItem(api.state.renderedGraph.nodes[0].id);api.dom.layerNext.events.click();record();}
            api.selectFocusItem(api.state.renderedGraph.nodes[0].id);const before=navigationSnapshot();api.dom.layerNext.events.click();
            const blocked=before===navigationSnapshot(),message=api.dom.explorationScope.textContent;
            api.dom.explorationBreadcrumb.children[1].events.click();const returned=api.state.renderedGraph.focusDepth;
            api.dom.layerPrevious.events.click();result={rows,blocked,message,returned,home:api.state.renderedGraph.focusDepth};
        """)
        self.assertEqual([r["depth"] for r in result["rows"]], [1, 2, 3, 4])
        self.assertEqual(result["rows"][0]["ids"], [f"module:{i:02}" for i in range(12)])
        for depth, prefix in ((2, "class:00:"), (3, "method:00:0:"), (4, "branch:00:0:0:")):
            row = result["rows"][depth - 1]
            self.assertEqual(row["ids"], [prefix + str(i) for i in range(3)])
            self.assertFalse(any(":01:" in node for node in row["members"]))
        for row in result["rows"]:
            self.assertEqual(len(row["crumbs"]), row["depth"])
            self.assertTrue(all(c["tag"] == "BUTTON" and c["title"] == c["label"] for c in row["crumbs"]))
            self.assertEqual(sum(c.get("current") == "location" for c in row["crumbs"]), 1)
            self.assertEqual(row["crumbs"][-1]["current"], "location")
        self.assertTrue(result["blocked"])
        self.assertIn("4단계까지", result["message"])
        self.assertEqual((result["returned"], result["home"]), (2, 1))

    def test_full_mode_and_history_restore_the_previous_focus_scope(self):
        result = self.run_app(r"""
            startFocus();enterFirst();enterFirst();const path=JSON.stringify(api.state.focusPath),ids=api.state.renderedGraph.nodes.map(n=>n.id);
            api.dom.explorationFull.events.click();const home={mode:api.state.explorationMode,depth:api.state.layerDepth};api.dom.layerNext.events.click();
            const full=api.state.renderedGraph,allMembers=full.nodes.flatMap(n=>n.memberIds);
            const fullComplete=allMembers.length===api.nodes.length&&new Set(allMembers).size===api.nodes.length;
            api.goBack();const restored={mode:api.state.explorationMode,path:JSON.stringify(api.state.focusPath),ids:api.state.renderedGraph.nodes.map(n=>n.id)};
            api.dom.explorationFull.events.click();api.dom.explorationFocus.events.click();
            result={home,fullComplete,fullCumulative:full.cumulative,restored,path,ids,resetDepth:api.state.renderedGraph.focusDepth,
              modeAttribute:api.dom.graphView.dataset.explorationMode,pressed:api.dom.explorationFocus.attributes['aria-pressed']};
        """)
        self.assertEqual(result["home"], {"mode": "full", "depth": 1})
        self.assertTrue(result["fullComplete"] and result["fullCumulative"])
        self.assertEqual(result["restored"], {"mode": "focus", "path": result["path"], "ids": result["ids"]})
        self.assertEqual((result["resetDepth"], result["modeAttribute"], result["pressed"]), (1, "focus", "true"))

    def test_dense_scope_caps_rendering_and_partitions_every_source_edge_once(self):
        payload = dense_module()
        result = self.run_app(r"""
            startFocus();enterFirst();const first=api.state.renderedGraph;
            const rows=[],members=[],bucketIds=[];
            for(let page=0;page<2;page++){
              api.state.atlasPage=page;api.state.edgePage=0;const graph=api.focusExplorationGraph();
              const keys=[...graph.visibleKeys,...graph.internalKeys,...graph.offPageKeys,...graph.offLineKeys];
              rows.push({page,nodes:graph.nodes.length,edges:graph.edges.length,keys,valid:keys.every(k=>api.edgeByKey.has(k)),
                boundarySubset:graph.boundaryKeys.every(k=>graph.offPageKeys.includes(k)),omitted:graph.omittedNodes,total:graph.totalBuckets,
                outOfScope:graph.outOfScopeNodes,outsideEdges:graph.outOfScopeEdges,eligible:graph.totalEligibleEdges});
              members.push(...graph.nodes.flatMap(n=>n.memberIds));bucketIds.push(...graph.nodes.map(n=>n.canonicalId));
            }
            api.state.atlasPage=0;api.state.edgePage=0;const lineKeys=[];let linePages=0;
            for(let page=0;page<Math.ceil(first.totalLines/160);page++){
              api.state.edgePage=page;const graph=api.focusExplorationGraph();lineKeys.push(...graph.visibleKeys);linePages++;
              if(graph.edges.length>160)throw Error('edge budget exceeded');
            }
            api.state.atlasPage=999;api.state.edgePage=999;const clamped=api.focusExplorationGraph();
            result={rows,members,bucketIds,lineKeys,linePages,firstLines:first.totalLines,clamped:{page:api.state.atlasPage,lines:api.state.edgePage,nodes:clamped.nodes.length},
              allCanonical:api.canonicalRelationPage().total};
        """, payload)
        expected_edges = {e["source"] + "\0" + e["type"] + "\0" + e["target"] for e in payload["edges"] if e["source"] != "m"}
        self.assertEqual(len(expected_edges), 4848)
        for row in result["rows"]:
            self.assertEqual(len(row["keys"]), 4848)
            self.assertEqual(set(row["keys"]), expected_edges)
            self.assertTrue(row["valid"] and row["boundarySubset"])
            self.assertLessEqual(row["nodes"], 60)
            self.assertLessEqual(row["edges"], 160)
            self.assertEqual((row["total"], row["eligible"], row["outOfScope"], row["outsideEdges"]), (96, 4848, 1, 96))
        self.assertEqual([r["nodes"] for r in result["rows"]], [60, 36])
        self.assertEqual([r["omitted"] for r in result["rows"]], [36, 60])
        self.assertEqual(len(result["members"]), 384)
        self.assertEqual(set(result["members"]), {n["id"] for n in payload["nodes"] if n["id"] != "m"})
        self.assertEqual(set(result["bucketIds"]), {f"c:{i}" for i in range(96)})
        self.assertEqual(len(result["lineKeys"]), result["firstLines"])
        self.assertEqual(len(result["lineKeys"]), len(set(result["lineKeys"])))
        self.assertEqual(result["firstLines"], 1770)
        first_owners = {f"c:{i}" for i in range(60)}
        self.assertEqual(set(result["lineKeys"]), {e["source"] + "\0CALLS\0" + e["target"] for e in payload["edges"]
                         if e["type"] == "CALLS" and e["source"] in first_owners and e["target"] in first_owners})
        self.assertEqual(result["linePages"], 12)
        self.assertEqual(result["clamped"]["page"], 1)
        self.assertEqual(result["clamped"]["nodes"], 36)
        self.assertEqual(result["allCanonical"], len(payload["edges"]))

    def test_five_languages_cover_actual_html_controls_and_dynamic_scope(self):
        class Page(HTMLParser):
            def __init__(self):
                super().__init__(); self.ids = {}; self.texts = []
            def handle_starttag(self, tag, pairs):
                attrs = dict(pairs)
                if "id" in attrs:
                    self.ids.setdefault(attrs["id"], []).append((tag, attrs))
            def handle_data(self, data):
                if data.strip(): self.texts.append(data.strip())
        page = Page(); page.feed(ui.HTML.read_text(encoding="utf-8"))
        expected = {"exploration-mode-controls": "div", "exploration-focus": "button", "exploration-full": "button",
                    "exploration-depth": "select", "exploration-breadcrumb": "nav", "exploration-scope": "p"}
        for identifier, tag in expected.items():
            self.assertEqual(len(page.ids.get(identifier, [])), 1, identifier)
            self.assertEqual(page.ids[identifier][0][0], tag)
        self.assertEqual(page.ids["exploration-scope"][0][1]["aria-live"], "polite")
        self.assertEqual(page.ids["exploration-focus"][0][1]["aria-pressed"], "true")
        static_keys = ["확대 모드", "전체 모드", "탐색 모드", "탐색 단계", "현재 탐색 경로", "전체 모듈",
                       "1 · 전체 모듈", "2 · 선택 모듈", "3 · 선택 구성요소", "4 · 선택 심볼 내부",
                       "전체 모듈에서 시작합니다. 항목을 선택한 뒤 진입하세요."]
        actual_text = " ".join(page.texts) + " " + " ".join(attrs.get("aria-label", "") for values in page.ids.values() for _, attrs in values)
        self.assertTrue(all(key in actual_text for key in static_keys))
        result = self.run_app("startFocus();const keys=" + json.dumps(static_keys) + r""";result=api.UI_LOCALES.map(locale=>{
            api.setUiLanguage(locale,false);api.updateExplorationControls(api.state.renderedGraph);
            return {locale,missing:keys.filter(key=>!api.UI_DICTIONARIES[locale][key]),translations:keys.map(key=>api.t(key)),
              next:api.dom.layerNext.textContent,previous:api.dom.layerPrevious.textContent,scope:api.dom.explorationScope.textContent,
              crumb:api.dom.explorationBreadcrumb.children[0].textContent};});
        """)
        self.assertEqual([r["locale"] for r in result], ["ko", "en", "ja", "zh-CN", "ru"])
        for row in result:
            self.assertFalse(row["missing"])
            self.assertTrue(all(row[k] for k in ("next", "previous", "scope", "crumb")))
            self.assertEqual(row["crumb"], row["translations"][5])
        for field in ("next", "previous", "scope", "crumb"):
            self.assertEqual(len({row[field] for row in result}), 5, field)

    def test_focus_links_roundtrip_and_reject_stale_or_cross_scope_paths(self):
        result = self.run_app(r"""
            startFocus();enterFirst();enterFirst();api.selectFocusItem(api.state.renderedGraph.nodes[0].id);
            const valid=api.selectionUrl(),parsed=api.readSelectionLink(),invalid=[];
            function reject(edit){const url=new URL(valid);edit(url.searchParams);window.location=url;invalid.push(api.readSelectionLink()===null);}
            reject(p=>p.delete('snapshot'));reject(p=>p.set('snapshot','old'));
            reject(p=>p.set('trail','not-json'));reject(p=>p.set('trail','{}'));
            reject(p=>p.set('trail',JSON.stringify([{kind:'group',key:'missing'}])));
            reject(p=>p.set('trail',JSON.stringify([{kind:'group',key:api.state.focusPath[0].key},{kind:'node',id:'class:01:0'}])));
            reject(p=>p.set('trail',JSON.stringify([...api.state.focusPath,{kind:'node',id:'method:00:0:0'},{kind:'node',id:'branch:00:0:0:0'}])));
            reject(p=>p.set('pick',JSON.stringify(['focus-node','method:01:0:0'])));
            reject(p=>p.set('entity','method:00:1:0'));
            result={path:api.state.focusPath,pick:api.state.focusSelectedId,parsed,invalid};
        """)
        self.assertEqual(result["parsed"]["navigation"]["focusPath"], result["path"])
        self.assertEqual(result["parsed"]["navigation"]["focusSelectedId"], result["pick"])
        self.assertEqual(result["parsed"]["entity"], "method:00:0:0")
        self.assertTrue(all(result["invalid"]))
        self.assertEqual(len(result["invalid"]), 9)

    def test_original_evidence_links_override_focus_scope_without_rewriting_edges(self):
        payload = layered_modules()
        edge = next(e for e in payload["edges"] if e["type"] == "CALLS")
        edge["evidence"] = [{"evidence_id": "synthetic-call-evidence", "rule_id": "python.call", "path": "src/layered00.py", "line_start": 2}]
        edge_key = edge["source"] + "\0CALLS\0" + edge["target"]
        url = "file:///snapshot.html?" + urlencode({"snapshot": "layer-button-cycle", "explore": "focus", "entity": edge["source"], "edge": edge_key, "evidence": "synthetic-call-evidence"})
        result = self.run_app("result=api.readSelectionLink();", payload, url)
        self.assertFalse(result["navigation"]["focusLink"])
        self.assertEqual(result["navigation"]["focusPath"], [])
        self.assertEqual(result["edge"]["key"], edge_key)
        self.assertEqual(result["edge"]["evidence"], edge["evidence"])
        self.assertEqual(result["evidenceId"], "synthetic-call-evidence")

    def test_focus_link_initialization_restores_scope_and_full_deep_link_needs_confirmation(self):
        path = [{"kind": "group", "key": "module:00"}, {"kind": "node", "id": "class:00:0"}]
        focus_url = "file:///snapshot.html?" + urlencode({"snapshot": "layer-button-cycle", "explore": "focus", "trail": json.dumps(path)})
        result = self.run_app(r"""
            enableCanvas(390,320);api.renderGraph(false);result={mode:api.state.explorationMode,path:api.state.focusPath,
              depth:api.state.renderedGraph.focusDepth,ids:api.state.renderedGraph.nodes.map(n=>n.canonicalId)};
        """, url=focus_url, initialize=True)
        self.assertEqual(result, {"mode": "focus", "path": path, "depth": 3, "ids": [f"method:00:0:{i}" for i in range(3)]})
        # No confirmation function is available in this file-viewer harness:
        # an incoming expensive full-mode link must remain below level four.
        full_url = "file:///snapshot.html?" + urlencode({"snapshot": "layer-button-cycle", "explore": "full", "layers": 4})
        guarded = self.run_app("result={mode:api.state.explorationMode,depth:api.state.layerDepth};", url=full_url, initialize=True)
        self.assertEqual(guarded, {"mode": "full", "depth": 3})

    def test_mouse_touch_keyboard_and_list_choose_the_same_item_before_entry(self):
        result = self.run_app(r"""
            startFocus();const rows=[];
            for(const input of ['mouse','touch','keyboard','list']){
              api.showAtlasHome();const item=api.state.renderedGraph.nodes[0],canvas=api.dom.graph3dCanvas;
              if(input==='keyboard'){api.state.threeDFocusedIndex=0;canvas.events.keydown({key:'Enter',preventDefault(){}});}
              else if(input==='list')api.dom.graphTextNodes.querySelectorAll('[data-node-id]').find(n=>n.dataset.nodeId===item.id).events.click();
              else {const point=api.state.threeDProjectedNodes.find(p=>p.node.id===item.id);
                const event={pointerId:1,pointerType:input,clientX:point.x,clientY:point.y};canvas.events.pointerdown(event);canvas.events.pointerup(event);}
              const picked=api.state.focusSelectedId,selectedDepth=api.state.renderedGraph.focusDepth;
              api.dom.layerNext.events.click();rows.push({input,picked,expected:item.id,selectedDepth,enteredDepth:api.state.renderedGraph.focusDepth,path:api.state.focusPath});
            }result=rows;
        """)
        for row in result:
            self.assertEqual(row["picked"], row["expected"], row["input"])
            self.assertEqual((row["selectedDepth"], row["enteredDepth"]), (1, 2))
            self.assertEqual(row["path"], [{"kind": "group", "key": "module:00"}])

    def test_flight_completes_without_continuous_frames_and_only_draws_bounded_graph(self):
        result = self.run_app(r"""
            startFocus();const queue=frameQueue();enterFirst();const transition=api.state.cameraTransition;
            const started=Boolean(transition&&transition.focusDive),target={...transition.to},frames=queue.flush();
            result={started,frames,finished:api.state.cameraTransition===null,marker:api.dom.graphView.dataset.transitioning,motion:api.state.motionEnabled,
              atTarget:Object.keys(target).every(key=>Math.abs(api.state.camera[key]-target[key])<1e-9)};
        """, dense_module())
        self.assertTrue(result["started"] and result["finished"] and result["atTarget"])
        self.assertEqual(result["marker"], "false")
        self.assertFalse(result["motion"])
        self.assertGreater(result["frames"]["count"], 1)
        self.assertLess(result["frames"]["count"], 100)
        self.assertEqual(result["frames"]["pending"], 0)
        self.assertEqual(result["frames"]["maxNodes"], 60)
        self.assertEqual(result["frames"]["maxEdges"], 160)

    def test_mode_and_user_input_cancel_inflight_camera_safely(self):
        result = self.run_app(r"""
            startFocus();const rows=[];
            for(const action of ['mode','zoom','key','pointer']){
              api.showAtlasHome();if(api.state.explorationMode==='full')api.setExplorationMode('focus');
              enterFirst();const started=Boolean(api.state.cameraTransition);
              if(action==='mode'){api.state.threeDTouchPointers.set(9,{x:1,y:2});api.state.threeDDragging=true;api.dom.explorationFull.events.click();}
              if(action==='zoom')api.dom.zoomIn.events.click();
              if(action==='key')api.dom.graph3dCanvas.events.keydown({key:'ArrowLeft',preventDefault(){}});
              if(action==='pointer')api.dom.graph3dCanvas.events.pointerdown({pointerId:1,pointerType:'touch',clientX:120,clientY:100});
              rows.push({action,started,stopped:api.state.cameraTransition===null,marker:api.dom.graphView.dataset.transitioning,
                finite:Object.values(api.state.camera).every(Number.isFinite),touches:api.state.threeDTouchPointers.size,dragging:api.state.threeDDragging});
              api.cancelExplorationMotion();
            }result=rows;
        """)
        for row in result:
            self.assertTrue(row["started"] and row["stopped"] and row["finite"], row)
            self.assertEqual(row["marker"], "false")
        self.assertEqual(result[0]["touches"], 0)
        self.assertFalse(result[0]["dragging"])

    def test_reduced_motion_change_finishes_camera_and_list_entry_has_no_flight(self):
        result = self.run_app(r"""
            let reducedChanged;api.reducedMotionQuery.addEventListener=(type,callback)=>{reducedChanged=callback;};
            startFocus();const queue=frameQueue();enterFirst();const target={...api.state.cameraTransition.to};
            reducedChanged({matches:true});const frames=queue.flush();
            const changed={stopped:api.state.cameraTransition===null,marker:api.dom.graphView.dataset.transitioning,
              target:Object.keys(target).every(key=>Math.abs(target[key]-api.state.camera[key])<1e-9),frames};
            api.showAtlasHome();api.reducedMotionQuery.matches=true;enterFirst();const reduced=api.state.cameraTransition===null;
            api.showAtlasHome();api.reducedMotionQuery.matches=false;api.setPresentation('list');enterFirst();
            result={changed,reduced,list:api.state.presentation,depth:api.state.renderedGraph.focusDepth,listStatic:api.state.cameraTransition===null};
        """)
        self.assertTrue(result["changed"]["stopped"] and result["changed"]["target"])
        self.assertEqual(result["changed"]["marker"], "false")
        self.assertEqual(result["changed"]["frames"]["pending"], 0)
        self.assertTrue(result["reduced"] and result["listStatic"])
        self.assertEqual((result["list"], result["depth"]), ("list", 2))


if __name__ == "__main__":
    unittest.main()
