from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills" / "manage-code-ontology" / "assets"
HTML = ASSETS / "workbench.html"
JS = ASSETS / "workbench.js"
CSS = ASSETS / "workbench.css"


# This harness executes the shipped application functions with a minimal DOM.
# It verifies graph/data/interaction logic, not browser layout or accessibility.
JS_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tagName=tag.toUpperCase(); this.children=[]; this.dataset={}; this.style={}; this.attributes={}; this.events={}; this.hidden=false; this.value=''; this.textContent=''; this.className=''; this.width=1200; this.height=800; this.clientWidth=1200; this.clientHeight=800; const classes=new Set(); this.classList={add:(x)=>classes.add(x), remove:(x)=>classes.delete(x), toggle:(x,on)=>on?classes.add(x):classes.delete(x)}; }
  appendChild(child) { if(child.tagName==='#FRAGMENT'){child.children.slice().forEach(x=>this.appendChild(x));return child;} child.parentElement=this;this.children.push(child);return child; }
  replaceChildren(...children) {this.children=[];children.forEach(child=>this.appendChild(child));}
  insertBefore(child, reference) { const at=this.children.indexOf(reference); child.parentElement=this; if(at<0)this.children.push(child);else this.children.splice(at,0,child); }
  setAttribute(key,value) {this.attributes[key]=value;}
  removeAttribute(key) {delete this.attributes[key];}
  addEventListener(type, callback) {this.events[type]=callback;}
  focus() {} select() {} scrollIntoView() {}
  querySelectorAll(selector) { const all=[]; const walk=(node)=>node.children.forEach(child=>{all.push(child);walk(child);});walk(this); if(selector.startsWith('.'))return all.filter(item=>item.className.split(' ').includes(selector.slice(1)));return []; }
  querySelector(selector) {return this.querySelectorAll(selector)[0]||null;}
  closest() {return null;}
}
const elements=new Map();
const document={getElementById:(id)=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('#fragment'),visibilityState:'visible',activeElement:null};
document.getElementById('ontology-data').textContent=JSON.stringify(input.payload);
document.getElementById('depth-select').value='2';document.getElementById('direction-select').value='both';
let page=new URL(input.url || 'file:///snapshot.html');
const window={document,location:page,setTimeout:callback=>callback(),matchMedia:()=>({matches:false}),history:{replaceState:(_a,_b,url)=>{page=new URL(url);window.location=page;}},requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},performance:{now:()=>0},devicePixelRatio:1};
const context={document,window,URL,URLSearchParams,Map,Set,Date,console};
vm.createContext(context);
const source=fs.readFileSync(process.argv[1],'utf8');
const exportCode='globalThis.api={state,nodes,edges,nodeById,edgeByKey,dom,readSelectionLink,selectionUrl,atlasGraph,moduleGroup,bounded3dGraph,neighborhood,buildModuleLayout,runSearch,renderSearchResults,renderRelationGroups,renderEdgeDetails,renderChanges,renderGraph3d,draw3dScene,focus3dCamera,selectNode,goBack,reducedMotionQuery}; return;';
vm.runInContext(source.replace('  const initialSelection = readSelectionLink();',exportCode+'\n  const initialSelection = readSelectionLink();'),context);
context.result=null;
vm.runInContext(input.script,context);
process.stdout.write(JSON.stringify(context.result));
"""


class WorkbenchQualityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")

    def test_quality_panel_and_legacy_state_are_present(self) -> None:
        for marker in (
            'id="quality-panel"',
            'id="quality-contract"',
            'id="quality-content"',
            'aria-labelledby="quality-title"',
        ):
            self.assertIn(marker, self.html)
        self.assertIn('dataset.qualityState = "legacy"', self.js)
        self.assertIn('qualityContract === "legacy_unknown"', self.js)
        self.assertIn("품질 계약 메타데이터가 없습니다", self.js)

    def test_canonical_quality_contract_fields_are_consumed(self) -> None:
        for marker in (
            "contract_version",
            "relationship_evidence",
            "total_edges",
            "documented_edges",
            "missing_evidence",
            "coverage_percent",
            "basis_counts",
            "runtime_status_counts",
            "unsupported_runtime",
            "capabilities",
            "interpretation",
        ):
            self.assertIn(marker, self.js)
        for status in ("supported", "partial", "unsupported"):
            self.assertIn(status + ":", self.js)

    def test_selected_edge_uses_only_bounded_evidence_metadata(self) -> None:
        for marker in (
            "rule_id",
            "direct_syntax",
            "resolved_static",
            "framework_semantic",
            "name_heuristic",
            "runtime_unknown",
            "line_start",
            "line_end",
            "limitations",
            'state.cy.on("tap", "edge"',
        ):
            self.assertIn(marker, self.js)
        for forbidden in (
            "source_text",
            "sourceText",
            "source_body",
            "sourceBody",
        ):
            self.assertNotIn(forbidden, self.js)
        self.assertIn("소스 본문은 이 패널에 포함하지 않습니다", self.js)
        self.assertIn('path.startsWith("/")', self.js)
        self.assertIn('/^[A-Za-z]:[\\\\/]/.test(path)', self.js)

    def test_quality_ui_preserves_offline_csp_and_safe_dom_rendering(self) -> None:
        for marker in (
            "default-src 'none'",
            "connect-src 'none'",
            "worker-src 'none'",
        ):
            self.assertIn(marker, self.html)
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "document.write",
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "EventSource",
            "new Worker",
        ):
            self.assertNotIn(forbidden, self.js)
        self.assertIn(".quality-runtime-warning", self.css)
        self.assertIn(".edge-evidence-card", self.css)

    def test_primary_navigation_is_three_d_and_has_only_three_modes(self) -> None:
        import re
        self.assertEqual(re.findall(r'data-lens="([^"]+)"', self.html), ["architecture", "impact", "changes"])
        self.assertRegex(self.html, r'id="view-mode-3d"[^>]*aria-pressed="true"')
        self.assertRegex(self.html, r'id="view-mode-2d"[^>]*aria-pressed="false"')
        self.assertIn('id="view-options"', self.html)

    def run_application(self, payload: dict, script: str, url: str = "file:///snapshot.html"):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable for application behavior checks")
        result = subprocess.run([node, "-e", JS_HARNESS, str(JS)], input=json.dumps({"payload": payload, "script": script, "url": url}), text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def sample_payload(self) -> dict:
        return {
            "meta": {"snapshotId": "snapshot-a", "repositoryName": "sample"},
            "nodes": [
                {"id": "module:a", "name": "a", "type": "Module", "language": "Python", "path": "src/a.py"},
                {"id": "fn:root", "name": "root", "type": "Function", "language": "Python", "path": "src/a.py"},
                {"id": "fn:caller", "name": "caller", "type": "Function", "language": "Python", "path": "src/b.py"},
                {"id": "concept:x", "name": "x", "type": "FrameworkConcept", "language": "Framework"},
            ],
            "edges": [
                {"source": "module:a", "target": "fn:root", "type": "DECLARES", "evidence": []},
                {"source": "fn:caller", "target": "fn:root", "type": "CALLS", "evidence": [{"evidence_id": "ev:one", "rule_id": "python.call", "path": "src/b.py", "line_start": 2}]},
                {"source": "concept:x", "target": "fn:root", "type": "CALLS", "evidence": []},
            ],
        }

    def test_deep_link_is_bound_to_snapshot_entity_edge_and_evidence(self) -> None:
        from urllib.parse import urlencode
        payload = self.sample_payload()
        edge = "fn:caller\x00CALLS\x00fn:root"
        script = "result = api.readSelectionLink();"
        url = "file:///snapshot.html?" + urlencode({"snapshot": "snapshot-a", "entity": "fn:root", "edge": edge, "evidence": "ev:one"})
        result = self.run_application(payload, script, url)
        self.assertEqual(result["entity"], "fn:root")
        self.assertEqual(result["evidenceId"], "ev:one")
        for altered in (
            {"snapshot": "old", "entity": "fn:root"},
            {"entity": "fn:root"},
            {"snapshot": "snapshot-a", "entity": "missing"},
            {"snapshot": "snapshot-a", "entity": "module:a", "edge": edge},
            {"snapshot": "snapshot-a", "entity": "fn:root", "edge": edge, "evidence": "unrelated"},
            {"snapshot": "snapshot-a", "entity": "fn:root", "evidence": "ev:one"},
        ):
            with self.subTest(altered=altered):
                self.assertIsNone(self.run_application(payload, script, "file:///snapshot.html?" + urlencode(altered)))

    def test_selected_edge_link_removes_unrelated_previous_entity_and_evidence(self) -> None:
        result = self.run_application(self.sample_payload(), """
            api.state.selectedId='module:a'; api.state.selectedEvidenceId='unrelated';
            api.renderEdgeDetails(api.edges.find(x=>x.source==='fn:caller'));
            result=api.readSelectionLink();
        """)
        self.assertEqual(result["entity"], "fn:caller")
        self.assertEqual(result["evidenceId"], "")
        self.assertEqual(result["edge"]["target"], "fn:root")

    def test_impact_excludes_generic_concepts_and_preserves_direction(self) -> None:
        result = self.run_application(self.sample_payload(), "result = api.neighborhood('fn:root', 'impact', 2, 'incoming');")
        self.assertEqual({node["id"] for node in result["nodes"]}, {"fn:root", "fn:caller"})
        self.assertEqual([edge["type"] for edge in result["edges"]], ["CALLS"])
        outgoing = self.run_application(self.sample_payload(), "result = api.neighborhood('fn:root', 'impact', 2, 'outgoing');")
        self.assertEqual([node["id"] for node in outgoing["nodes"]], ["fn:root"])

    def test_atlas_keeps_real_nodes_balances_modules_and_has_finite_stable_positions(self) -> None:
        payload = self.sample_payload()
        for module in range(8):
            for index in range(40):
                payload["nodes"].append({"id": f"f:{module}:{index}", "name": f"function{index}", "type": "Function", "language": "Python", "path": f"module{module}/code.py"})
        result = self.run_application(payload, """
            const graph=api.bounded3dGraph(api.atlasGraph());
            api.buildModuleLayout(graph);
            const first=JSON.stringify(Array.from(api.state.threeDPositions));
            api.buildModuleLayout(graph);
            result={nodes:graph.nodes.map(x=>x.id), groups:api.state.threeDGroups.map(x=>x.descriptor.key), stable:first===JSON.stringify(Array.from(api.state.threeDPositions)), finite:Array.from(api.state.threeDPositions.values()).every(p=>[p.x,p.y,p.z].every(Number.isFinite)), truncated:graph.truncated};
        """)
        self.assertLessEqual(len(result["nodes"]), 160)
        self.assertTrue(set(result["nodes"]).issubset({node["id"] for node in payload["nodes"]}))
        self.assertTrue(result["stable"])
        self.assertTrue(result["finite"])
        self.assertTrue(result["truncated"])
        for module in range(8):
            self.assertIn(f"path:module{module}", result["groups"])

    def test_more_relations_and_evidence_are_real_paged_controls(self) -> None:
        payload = self.sample_payload()
        for index in range(45):
            payload["nodes"].append({"id": f"caller:{index}", "name": f"caller{index}", "type": "Function", "language": "Python"})
            payload["edges"].append({"source": f"caller:{index}", "target": "fn:root", "type": "CALLS", "evidence": []})
        payload["edges"][1]["evidence"] = [{"evidence_id": f"ev:{index}", "rule_id": "call", "path": "src/b.py", "line_start": index + 1} for index in range(29)]
        result = self.run_application(payload, """
            const container=document.createElement('div');
            api.renderRelationGroups(container,'fn:root','incoming');
            const group=container.children.find(x=>x.children[1].children.length===18);
            const countBefore=group.children[1].children.length;
            group.children[2].events.click();
            const countAfter=group.children[1].children.length;
            api.renderEdgeDetails(api.edges.find(x=>x.source==='fn:caller'));
            const evidenceBefore=api.dom.detailsContent.querySelectorAll('.edge-evidence-card').length;
            const more=api.dom.detailsContent.querySelectorAll('.more-button')[0];
            more.events.click();more.events.click();
            result={countBefore,countAfter,evidenceBefore,evidenceAfter:api.dom.detailsContent.querySelectorAll('.edge-evidence-card').length,hidden:more.hidden};
        """)
        self.assertEqual(result, {"countBefore": 18, "countAfter": 36, "evidenceBefore": 12, "evidenceAfter": 29, "hidden": True})

    def test_search_paginates_past_eighty_without_dropping_matches(self) -> None:
        payload = self.sample_payload()
        for index in range(205):
            payload["nodes"].append({"id": f"match:{index}", "name": f"shared{index}", "type": "Function", "language": "Python"})
        result = self.run_application(payload, """
            api.dom.searchInput.value='shared';
            api.runSearch();
            const first=api.dom.searchResults.querySelectorAll('.search-result').length;
            api.dom.searchResults.querySelectorAll('.more-button')[0].events.click();
            const second=api.dom.searchResults.querySelectorAll('.search-result').length;
            api.dom.searchResults.querySelectorAll('.more-button')[0].events.click();
            result={first,second,third:api.dom.searchResults.querySelectorAll('.search-result').length,remaining:api.dom.searchResults.querySelectorAll('.more-button').length};
        """)
        self.assertEqual(result, {"first": 80, "second": 160, "third": 205, "remaining": 0})

    def test_scene_projects_real_graph_to_finite_canvas_coordinates(self) -> None:
        result = self.run_application(self.sample_payload(), """
            let operations=0;
            const gradient={addColorStop:()=>{}};
            const context=new Proxy({}, {get:(_target,name)=>name==='measureText'?(text)=>({width:text.length*6}):name==='createRadialGradient'?()=>gradient:(...args)=>{operations+=1;if(args.some(x=>typeof x==='number'&&!Number.isFinite(x)))throw new Error('non-finite canvas coordinate: '+String(name));},set:()=>true});
            api.dom.graph3dCanvas.getContext=()=>context;
            api.dom.graph3dCanvas.textContent='fallback';
            api.dom.detailsPanel.hidden=true;
            api.renderGraph3d(api.bounded3dGraph(api.atlasGraph()));
            api.reducedMotionQuery.matches=true;
            api.focus3dCamera('fn:root');
            result={operations,ids:api.state.threeDProjectedNodes.map(x=>x.node.id),finite:api.state.threeDProjectedNodes.every(x=>[x.x,x.y,x.z,x.scale,x.hitRadius].every(Number.isFinite)),noTransition:api.state.cameraTransition===null,fallbackText:api.dom.graph3dCanvas.textContent};
        """)
        self.assertGreater(result["operations"], 100)
        self.assertEqual(set(result["ids"]), {node["id"] for node in self.sample_payload()["nodes"]})
        self.assertTrue(result["finite"])
        self.assertTrue(result["noTransition"])
        self.assertEqual(result["fallbackText"], "")

    def test_mobile_caption_budget_keeps_all_graph_nodes_and_avoids_module_overlap(self) -> None:
        payload = {"meta": {"snapshotId": "mobile"}, "nodes": [], "edges": []}
        for module in range(12):
            module_id = f"pkg:{module}"
            payload["nodes"].append({"id": module_id, "name": f"package{module}", "type": "Module", "language": "Python", "path": f"pkg{module}/code.py"})
            for index in range(7):
                node_id = f"symbol:{module}:{index}"
                payload["nodes"].append({"id": node_id, "name": f"symbol{module}_{index}", "type": "Function", "language": "Python", "path": f"pkg{module}/code.py"})
                payload["edges"].append({"source": module_id, "target": node_id, "type": "DECLARES"})
        result = self.run_application(payload, """
            const labels=[];
            const backing={};
            const gradient={addColorStop:()=>{}};
            const context=new Proxy(backing,{get:(target,name)=>name==='measureText'?text=>({width:text.length*6}):name==='fillText'?(text,x,y)=>labels.push({text,x,y,font:target.font}):name==='createRadialGradient'?()=>gradient:target[name]||(()=>{}),set:(target,name,value)=>{target[name]=value;return true;}});
            api.dom.graph3dCanvas.getContext=()=>context;
            api.dom.graph3dCanvas.clientWidth=390;
            api.dom.graph3dCanvas.clientHeight=726;
            api.dom.detailsPanel.hidden=true;
            api.renderGraph3d(api.bounded3dGraph(api.atlasGraph()));
            const captions=labels.filter(item=>item.font.includes('ui-monospace'));
            const rectangles=captions.map(item=>({x:item.x-(item.text.length*6+12)/2,y:item.y-11,w:item.text.length*6+12,h:29}));
            const overlap=rectangles.some((a,index)=>rectangles.slice(index+1).some(b=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y));
            result={nodeCount:api.state.threeDGraph.nodes.length,groups:api.state.threeDGroups.length,captionCount:captions.length,overlap};
        """)
        self.assertEqual(result["nodeCount"], 96)
        self.assertEqual(result["groups"], 12)
        self.assertGreater(result["captionCount"], 0)
        self.assertLessEqual(result["captionCount"], 6)
        self.assertFalse(result["overlap"])

    def test_changes_consumes_shared_modified_edge_evidence(self) -> None:
        payload = self.sample_payload()
        payload["changes"] = {"available": True, "beforeSnapshotId": "before", "afterSnapshotId": "snapshot-a", "edgesModified": [{"source": "fn:caller", "target": "fn:root", "type": "CALLS", "evidence": [{"evidence_id": "new"}], "previousEvidence": [{"evidence_id": "old"}]}], "counts": {"edgesModified": 7}}
        result = self.run_application(payload, """
            api.renderChanges();
            const view=api.dom.changesView;
            const values=view.querySelectorAll('.metric-value').map(x=>x.textContent);
            const cards=view.querySelectorAll('.change-list');
            result={modifiedCount:values[5],modifiedItems:cards[5].querySelectorAll('.change-item').length};
        """)
        self.assertEqual(result, {"modifiedCount": "7", "modifiedItems": 1})

    @unittest.skipUnless(shutil.which("node"), "Node is unavailable for JavaScript syntax validation")
    def test_workbench_javascript_syntax(self) -> None:
        result = subprocess.run(
            [shutil.which("node") or "node", "--check", str(JS)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
