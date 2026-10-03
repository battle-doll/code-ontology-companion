"""Execute the shipped JS over synthetic data: coverage, hierarchy, and CALLS paths."""
from __future__ import annotations

import unittest
import test_workbench_quality_ui as ui_tests


def ontology(modules: int, dense: bool = False) -> dict:
    nodes, edges = [], []
    for index in range(modules):
        owner = f"module:{index:03}"
        nodes.append({"id": owner, "name": f"module{index:03}", "type": "Module", "language": "Python", "path": f"src/mod{index:03}.py"})
        for suffix in ("a", "b"):
            symbol = f"fn:{index:03}:{suffix}"
            nodes.append({"id": symbol, "name": symbol, "type": "Function", "language": "Python", "path": f"src/mod{index:03}.py"})
            edges.append({"source": owner, "target": symbol, "type": "DECLARES"})
        edges.append({"source": f"fn:{index:03}:a", "target": f"fn:{index:03}:b", "type": "CALLS"})
        if index:
            edges.append({"source": f"fn:{index-1:03}:b", "target": f"fn:{index:03}:a", "type": "CALLS"})
    if dense:
        for source in range(modules):
            for target in range(modules):
                if source != target:
                    edges.append({"source": f"fn:{source:03}:a", "target": f"fn:{target:03}:b", "type": "CALLS"})
    return {"meta": {"snapshotId": "synthetic", "repositoryName": "Synthetic Atlas"}, "nodes": nodes, "edges": edges}


class AtlasNavigationTests(unittest.TestCase):
    run_application = ui_tests.WorkbenchQualityUiTests.run_application

    def test_all_97_groups_fit_without_top_group_sampling(self):
        result = self.run_application(ontology(97), """
            const graph=api.atlasGraph();
            const members=graph.nodes.flatMap(n=>n.memberIds);
            result={groups:graph.nodes.length,members:members.length,unique:new Set(members).size,
              canonicalUntouched:graph.nodes.every(n=>!api.nodeById.has(n.id)),
              accounted:graph.visibleKeys.length+graph.internalKeys.length+graph.offPageKeys.length+graph.offLineKeys.length,
              total:api.edges.length,truncated:graph.truncated};
        """)
        self.assertEqual(result, {"groups": 97, "members": 291, "unique": 291, "canonicalUntouched": True, "accounted": 387, "total": 387, "truncated": False})

    def test_node_and_relation_pages_cover_every_canonical_item_over_budgets(self):
        result = self.run_application(ontology(173, True), """
            const nodeIds=new Set(), relationKeys=new Set();
            let pageCount=0,bounded=true,boundaries=0,partition=true;
            for(let page=0;page<2;page++){
              api.state.atlasPage=page;const graph=api.atlasGraph();pageCount++;
              graph.nodes.forEach(n=>n.memberIds.forEach(id=>nodeIds.add(id)));
              bounded=bounded&&graph.nodes.length<=160&&graph.edges.length<=480;
              boundaries+=graph.boundaryKeys.length;
              const parts=[...graph.visibleKeys,...graph.internalKeys,...graph.offPageKeys,...graph.offLineKeys];
              partition=partition&&parts.length===api.edges.length&&new Set(parts).size===api.edges.length;
            }
            for(let page=0;page<Math.ceil(api.edges.length/80);page++){
              api.state.relationPage=page;api.canonicalRelationPage().edges.forEach(e=>relationKeys.add(e.key));
            }
            result={nodes:nodeIds.size,totalNodes:api.nodes.length,relations:relationKeys.size,totalRelations:api.edges.length,bounded,boundaries,partition,pageCount};
        """)
        self.assertEqual(result["nodes"], result["totalNodes"])
        self.assertEqual(result["relations"], result["totalRelations"])
        self.assertGreater(result["totalRelations"], 480)
        self.assertGreater(result["boundaries"], 0)
        self.assertTrue(result["bounded"])
        self.assertTrue(result["partition"])

    def test_edge_pages_cover_all_lines_without_silent_slicing(self):
        result = self.run_application(ontology(30, True), """
            const keys=new Set(); let pages=0;const first=api.atlasGraph();
            for(let page=0;page<Math.ceil(first.totalLines/480);page++){
              api.state.edgePage=page;const graph=api.atlasGraph();pages++;
              [...graph.visibleKeys,...graph.internalKeys].forEach(k=>keys.add(k));
            }
            result={pages,total:api.edges.length,represented:keys.size,firstLines:first.edges.length,hidden:first.offLineKeys.length};
        """)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["represented"], result["total"])
        self.assertEqual(result["firstLines"], 480)
        self.assertGreater(result["hidden"], 0)

    def test_selected_module_component_depths_preserve_collapsed_coverage(self):
        payload = ontology(4)
        payload["nodes"] += [
            {"id": "class:A", "name": "Service", "type": "Class", "language": "Python", "path": "src/mod000.py"},
            {"id": "method:A", "name": "execute", "type": "Method", "language": "Python", "path": "src/mod000.py"},
            {"id": "branch:A", "name": "predicate", "type": "RuntimeBranch", "language": "Python", "path": "src/mod000.py"},
        ]
        payload["edges"] += [
            {"source": "module:000", "target": "class:A", "type": "DECLARES"},
            {"source": "class:A", "target": "method:A", "type": "DECLARES"},
            {"source": "method:A", "target": "branch:A", "type": "DECLARES_RUNTIME_BRANCH"},
        ]
        result = self.run_application(payload, """
            const resultByDepth=[];
            api.state.atlasGroupKey='module:000';api.state.componentId='class:A';
            for(let depth=1;depth<=3;depth++){
              api.state.displayDepth=depth;const graph=api.atlasGraph();
              resultByDepth.push({depth,nodes:graph.nodes.map(n=>({kind:n.bucketKind,id:n.canonicalId,members:n.memberIds})),coverage:graph.nodes.flatMap(n=>n.memberIds).sort()});
            }
            result=resultByDepth;
        """)
        all_ids = sorted(node["id"] for node in payload["nodes"])
        for row in result:
            self.assertEqual(row["coverage"], all_ids)
        self.assertTrue(all(row["kind"] == "module" for row in result[0]["nodes"]))
        self.assertEqual(sum(row["kind"] == "module" for row in result[1]["nodes"]), 3)
        cls = next(row for row in result[1]["nodes"] if row["id"] == "class:A")
        self.assertEqual(set(cls["members"]), {"class:A", "method:A", "branch:A"})
        self.assertEqual({row["id"] for row in result[2]["nodes"] if row["kind"] == "symbol"}, {"class:A", "method:A", "branch:A"})

    def calls_payload(self):
        names = ["a", "b", "c", "d", "x", "y"]
        return {"nodes": [{"id": name, "name": name, "type": "Function", "language": "Python", "path": f"src/{name}.py"} for name in names], "edges": [{"source": source, "target": target, "type": relation} for source, target, relation in [("a", "b", "CALLS"), ("b", "c", "CALLS"), ("c", "d", "CALLS"), ("c", "a", "CALLS"), ("x", "y", "CALLS"), ("a", "x", "IMPORTS")]]}

    def test_call_hops_direction_cycles_and_unrelated_edges(self):
        result = self.run_application(self.calls_payload(), """
            result=[1,2,3].map(depth=>Array.from(api.canonicalCallTrace(['a'],depth,null).edges).map(([k,v])=>[api.edgeByKey.get(k).source,api.edgeByKey.get(k).target,v]));
        """)
        self.assertEqual(result[0], [["a", "b", 1]])
        self.assertEqual(result[1], [["a", "b", 1], ["b", "c", 2]])
        self.assertEqual(result[2], [["a", "b", 1], ["b", "c", 2], ["c", "a", 3], ["c", "d", 3]])

    def test_line_hover_begins_with_only_that_call_and_handles_self_recursion(self):
        payload = self.calls_payload()
        payload["edges"] += [{"source": "a", "target": "x", "type": "CALLS"}, {"source": "a", "target": "a", "type": "CALLS"}]
        result = self.run_application(payload, """
            const line=api.edges.find(e=>e.source==='a'&&e.target==='b');
            const recursive=api.edges.find(e=>e.source==='a'&&e.target==='a');
            result={line:Array.from(api.canonicalCallTrace([],3,[line.key]).edges).map(([k,d])=>[api.edgeByKey.get(k).target,d]),recursive:Array.from(api.canonicalCallTrace([],2,[recursive.key]).edges).map(([k,d])=>[api.edgeByKey.get(k).target,d])};
        """)
        self.assertNotIn(["x", 1], result["line"])
        self.assertIn(["b", 2], result["recursive"])
        self.assertIn(["x", 2], result["recursive"])

    def test_aggregate_hover_cannot_join_disconnected_calls_in_middle_module(self):
        payload = ontology(3)
        payload["edges"] = [edge for edge in payload["edges"] if edge["type"] == "DECLARES"] + [
            {"source": "fn:000:a", "target": "fn:001:a", "type": "CALLS"},
            {"source": "fn:001:b", "target": "fn:002:a", "type": "CALLS"},
        ]
        result = self.run_application(payload, """
            const graph=api.atlasGraph();api.state.renderedGraph=graph;api.state.hoverDepth=3;
            const a=graph.nodes.find(n=>n.atlasGroup.key==='module:000');
            api.setCallHover(a.id,null);
            const traced=Array.from(api.state.callHighlight.edges.keys());
            const highlighted=graph.edges.filter(e=>Number.isFinite(api.callHopForEdge(e))).length;
            api.clearCallHover();
            result={traced,highlighted,after:api.state.callHighlight.edges.size,viewAfter:api.state.hoverViewEdges.size,signature:api.state.hoverSignature};
        """)
        self.assertEqual(len(result["traced"]), 1)
        self.assertEqual(result["highlighted"], 1)
        self.assertEqual(result["after"], 0)
        self.assertEqual(result["viewAfter"], 0)
        self.assertEqual(result["signature"], "")

    def test_policy_pipeline_links_do_not_alias_to_architecture(self):
        for lens in ("policy", "pipeline", "spring"):
            result = self.run_application(ontology(2), "result=api.readSelectionLink();", f"file:///snapshot.html?lens={lens}")
            self.assertEqual(result["lens"], lens)

    def test_scope_filters_are_explicit_and_default_all(self):
        payload = {"nodes": [{"id": path, "name": path, "type": "Function", "language": "Python", "path": path} for path in ["src/live.py", "tests/test_live.py", "backups/old.py", "misc/helper.py"]], "edges": []}
        result = self.run_application(payload, """
            const counts={};for(const scope of ['all','application','test','auxiliary']){api.state.sourceScope=scope;counts[scope]=api.atlasInventory().nodeIds.size;}result=counts;
        """)
        self.assertEqual(result, {"all": 4, "application": 2, "test": 1, "auxiliary": 1})

    def test_real_controls_pagination_hover_clear_and_depth_require_selection(self):
        result = self.run_application(ontology(173), """
            api.bindEvents();api.renderGraph();
            api.dom.groupNext.events.click();const page=api.state.atlasPage;
            api.dom.groupPrevious.events.click();
            api.dom.displayDepth.value='2';api.dom.displayDepth.events.change();const untouched=api.state.displayDepth;
            const first=api.dom.groupList.children[0];first.events.focus();const traced=api.state.callHighlight.edges.size;first.events.blur();
            first.events.click();const expanded=api.state.displayDepth;
            result={page,untouched,traced,cleared:api.state.callHighlight.edges.size,expanded};
        """)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["untouched"], 1)
        self.assertGreater(result["traced"], 0)
        self.assertEqual(result["cleared"], 0)
        self.assertEqual(result["expanded"], 2)

    def test_pointer_handlers_hit_nodes_call_lines_and_clear_on_leave(self):
        result = self.run_application(self.calls_payload(), """
            api.bindEvents();
            api.dom.graph3dCanvas.getBoundingClientRect=()=>({left:0,top:0,width:1200,height:800});
            const node=api.nodeById.get('a'), edge=api.edges.find(e=>e.source==='a'&&e.target==='b');
            api.state.threeDProjectedNodes=[{node,x:10,y:10,hitRadius:15}];
            api.state.threeDProjectedEdges=[{edge,source:{x:100,y:100},target:{x:200,y:100},control:{x:150,y:100}}];
            api.state.threeDGraph={nodes:api.nodes,edges:api.edges};
            api.dom.graph3dCanvas.events.pointermove({clientX:10,clientY:10});
            const nodeTrace=api.state.callHighlight.edges.size;
            api.dom.hoverDepth.value='3';api.dom.hoverDepth.events.change();
            const thirdTrace=api.state.callHighlight.edges.size;
            api.dom.graph3dCanvas.events.pointermove({clientX:150,clientY:100});
            const lineTrace=Array.from(api.state.callHighlight.edges.values());
            const edgeHovered=api.state.threeDHoverEdgeKey===edge.key;
            api.dom.graph3dCanvas.events.pointerleave();
            const cleared=api.state.callHighlight.edges.size;
            api.dom.graph3dCanvas.events.pointermove({clientX:600,clientY:600});
            result={nodeTrace,thirdTrace,lineTrace,edgeHovered,cleared,emptyHover:api.state.hoverSignature};
        """)
        self.assertEqual(result["nodeTrace"], 1)
        self.assertEqual(result["thirdTrace"], 4)
        self.assertEqual(result["lineTrace"], [1, 2, 3, 3])
        self.assertTrue(result["edgeHovered"])
        self.assertEqual(result["cleared"], 0)
        self.assertEqual(result["emptyHover"], "")

    def test_expanded_link_round_trip_and_invalid_cross_module_component(self):
        result = self.run_application(ontology(3), """
            api.state.atlasGroupKey='module:001';api.state.componentId='fn:001:a';api.state.displayDepth=3;
            api.state.sourceScope='application';api.state.hoverDepth=3;api.state.relationFilter='CALLS';
            const url=api.selectionUrl();window.location=url;
            const valid=api.readSelectionLink();
            url.searchParams.set('component','fn:002:a');window.location=url;
            result={valid:valid.navigation,invalid:api.readSelectionLink()};
        """)
        self.assertEqual(result["valid"]["displayDepth"], 3)
        self.assertEqual(result["valid"]["hoverDepth"], 3)
        self.assertEqual(result["valid"]["atlasGroupKey"], "module:001")
        self.assertEqual(result["valid"]["relationFilter"], "CALLS")
        self.assertIsNone(result["invalid"])

    def test_last_module_expands_on_its_page_and_title_uses_name(self):
        result = self.run_application(ontology(173), """
            api.state.atlasPage=1;api.atlasGraph();api.openAtlasGroup('module:172');
            api.updateViewHeading();
            result={page:api.state.atlasPage,selectedVisible:api.state.renderedGraph.nodes.some(n=>n.atlasGroup.key==='module:172'),title:api.dom.viewTitle.textContent,canonical:api.nodeById.size};
        """)
        self.assertEqual(result["page"], 1)
        self.assertTrue(result["selectedVisible"])
        self.assertEqual(result["title"], "module172")
        self.assertEqual(result["canonical"], 519)

    def wide_neighborhood(self):
        payload = {"nodes": [{"id": "root", "name": "Root", "type": "Function", "language": "Python", "path": "src/root.py"}], "edges": []}
        for index in range(350):
            target = f"leaf:{index:03}"
            payload["nodes"].append({"id": target, "name": target, "type": "Function", "language": "Python", "path": "src/root.py"})
            payload["edges"].append({"source": "root", "target": target, "type": "CALLS"})
        for source in range(35):
            for target in range(35):
                if source != target:
                    payload["edges"].append({"source": f"leaf:{source:03}", "target": f"leaf:{target:03}", "type": "CALLS"})
        return payload

    def test_complete_neighborhood_is_computed_before_render_paging(self):
        result = self.run_application(self.wide_neighborhood(), """
            api.state.rootId='root';
            const complete=api.neighborhood('root','impact',1,'outgoing');
            const ids=new Set(), shownEdges=new Set();let exact=true,partition=true,idempotent=true,maxNodes=0,maxEdges=0;
            for(let page=0;page<Math.ceil(complete.nodes.length/160);page++){
              api.state.neighborhoodPage=page;api.state.neighborhoodEdgePage=0;
              const first=api.bounded3dGraph(complete);
              first.nodes.forEach(n=>ids.add(n.id));
              for(let lines=0;lines<Math.max(1,Math.ceil(first.totalLines/480));lines++){
                api.state.neighborhoodEdgePage=lines;const graph=api.bounded3dGraph(complete);
                graph.edges.forEach(e=>shownEdges.add(e.key));
                const parts=[...graph.edges.map(e=>e.key),...graph.offPageKeys,...graph.offLineKeys];
                partition=partition&&parts.length===complete.edges.length&&new Set(parts).size===complete.edges.length;
                exact=exact&&graph.totalNeighborhoodNodes===351&&graph.totalNeighborhoodEdges===1540;
                idempotent=idempotent&&api.bounded3dGraph(graph)===graph;
                maxNodes=Math.max(maxNodes,graph.nodes.length);maxEdges=Math.max(maxEdges,graph.edges.length);
              }
            }
            const allRelations=new Set();
            for(let page=0;page<Math.ceil(api.edges.length/80);page++){api.state.relationPage=page;api.canonicalRelationPage().edges.forEach(e=>allRelations.add(e.key));}
            result={count:complete.nodes.length,ids:ids.size,edges:complete.edges.length,allRelations:allRelations.size,maxNodes,maxEdges,exact,partition,idempotent};
        """)
        self.assertEqual(result, {"count": 351, "ids": 351, "edges": 1540, "allRelations": 1540, "maxNodes": 160, "maxEdges": 480, "exact": True, "partition": True, "idempotent": True})

    def test_neighborhood_pagers_keep_lens_and_show_actual_counts(self):
        result = self.run_application(self.wide_neighborhood(), """
            const gradient={addColorStop:()=>{}};
            const canvasContext=new Proxy({}, {get:(_t,name)=>name==='measureText'?text=>({width:text.length*6}):name==='createRadialGradient'?()=>gradient:()=>{},set:()=>true});
            api.dom.graph3dCanvas.getContext=()=>canvasContext;
            api.state.rootId='root';api.state.selectedId='root';api.state.atlasOverview=false;api.state.activeLens='impact';api.state.direction='outgoing';api.state.depth=1;
            api.bindEvents();api.renderGraph();
            const first={nodes:api.state.renderedGraph.nodes.length,edges:api.state.renderedGraph.edges.length,note:api.dom.graphNote.textContent,coverage:api.dom.coverageSummary.textContent};
            api.dom.edgeNext.events.click();const secondEdges=api.state.renderedGraph.edges.length;
            api.dom.groupNext.events.click();
            result={first,secondEdges,page:api.state.neighborhoodPage,nodeCount:api.state.renderedGraph.nodes.length,atlas:api.state.atlasOverview,lens:api.state.activeLens,total:api.state.renderedGraph.totalNeighborhoodNodes,summary:api.dom.groupSummary.textContent};
        """)
        self.assertEqual(result["first"]["nodes"], 160)
        self.assertEqual(result["first"]["edges"], 480)
        self.assertIn("160/351", result["first"]["note"])
        self.assertIn("480/1,540", result["first"]["note"])
        self.assertIn("= 1,540", result["first"]["coverage"])
        self.assertEqual(result["secondEdges"], 480)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["nodeCount"], 160)
        self.assertFalse(result["atlas"])
        self.assertEqual(result["lens"], "impact")
        self.assertEqual(result["total"], 351)
        self.assertIn("161–320 / 351", result["summary"])


    def test_long_curved_line_hover_has_no_gaps_between_samples(self):
        result = self.run_application(self.calls_payload(), """
            api.bindEvents();api.dom.graph3dCanvas.getBoundingClientRect=()=>({left:0,top:0,width:1200,height:800});
            const edge=api.edges.find(e=>e.source==='a'&&e.target==='b');
            api.state.threeDProjectedNodes=[];api.state.threeDProjectedEdges=[{edge,source:{x:0,y:100},target:{x:600,y:100},control:{x:300,y:118}}];
            api.state.threeDGraph={nodes:api.nodes,edges:api.edges};
            const traces=[];
            for(let step=2;step<98;step++){const t=step/100;api.dom.graph3dCanvas.events.pointermove({clientX:600*t,clientY:100+36*t*(1-t)});traces.push(api.state.callHighlight.edges.size);}
            api.dom.graph3dCanvas.events.pointermove({clientX:300,clientY:150});
            result={allHit:traces.every(n=>n===1),offLine:api.state.callHighlight.edges.size};
        """)
        self.assertEqual(result, {"allHit": True, "offLine": 0})

    def test_member_selection_preserves_hierarchy_and_depth_controls(self):
        payload=ontology(4)
        payload["nodes"] += [{"id":"class:A","name":"Service","type":"Class","language":"Python","path":"src/mod000.py"},{"id":"method:A","name":"execute","type":"Method","language":"Python","path":"src/mod000.py"}]
        payload["edges"] += [{"source":"module:000","target":"class:A","type":"DECLARES"},{"source":"class:A","target":"method:A","type":"DECLARES"}]
        result=self.run_application(payload, """
            api.bindEvents();api.state.atlasGroupKey='module:000';api.state.displayDepth=2;api.renderGraph();
            api.chooseAtlasBucket(api.state.renderedGraph.nodes.find(n=>n.canonicalId==='class:A'));
            const detailMember=api.dom.detailsContent.querySelectorAll('.atlas-list-button').find(n=>n.textContent==='execute · 메서드');
            detailMember.events.click();
            const detailPreserved=api.state.atlasOverview&&api.state.displayDepth===3&&api.state.atlasGroupKey==='module:000';
            const before=api.state.renderedGraph.nodes.flatMap(n=>n.memberIds).sort();
            api.chooseAtlasBucket(api.state.renderedGraph.nodes.find(n=>n.canonicalId==='method:A'));
            const after=api.state.renderedGraph.nodes.flatMap(n=>n.memberIds).sort();
            const snapshot={atlas:api.state.atlasOverview,group:api.state.atlasGroupKey,selected:api.state.selectedId,depth:api.state.displayDepth,others:api.state.renderedGraph.nodes.filter(n=>n.bucketKind==='module').length,same:JSON.stringify(before)===JSON.stringify(after),detailPreserved};
            const url=api.selectionUrl();window.location=url;const linked=api.readSelectionLink();
            api.dom.displayDepth.value='2';api.dom.displayDepth.events.change();
            result={snapshot,depthAfter:api.state.displayDepth,linkGroup:linked.navigation.atlasGroupKey,entity:linked.entity};
        """)
        self.assertEqual(result['snapshot'], {'atlas':True,'group':'module:000','selected':'method:A','depth':3,'others':3,'same':True,'detailPreserved':True})
        self.assertEqual(result['depthAfter'],2)
        self.assertEqual(result['linkGroup'],'module:000')
        self.assertEqual(result['entity'],'method:A')

    def test_canvas_unavailable_keeps_complete_paged_lists(self):
        result=self.run_application(ontology(173,True), """
            api.bindEvents();api.dom.graph3dCanvas.getContext=()=>null;api.renderGraph();
            const first=api.dom.groupList.children.length;
            api.dom.groupNext.events.click();const second=api.dom.groupList.children.length;
            result={first,second,listOpen:api.dom.graphTextAlternative.open,atlasOpen:api.dom.atlasBrowser.open,presentation:api.dom.graphView.dataset.presentation,relationTotal:api.canonicalRelationPage().total,expected:api.edges.length,graph:api.state.threeDGraph};
        """)
        self.assertEqual(result['first']+result['second'],173)
        self.assertTrue(result['listOpen'])
        self.assertTrue(result['atlasOpen'])
        self.assertEqual(result['presentation'],'list')
        self.assertEqual(result['relationTotal'],result['expected'])
        self.assertIsNone(result['graph'])

    def test_control_events_update_address_and_link_round_trip(self):
        result=self.run_application(ontology(30,True), """
            api.bindEvents();api.renderGraph();api.dom.edgeNext.events.click();
            api.dom.hoverDepth.value='3';api.dom.hoverDepth.events.change();api.dom.relationNext.events.click();
            const link=api.readSelectionLink();
            result={lines:new URL(window.location.href).searchParams.get('lines'),hover:new URL(window.location.href).searchParams.get('hover'),relations:link.navigation.relationPage,restoredLines:link.navigation.edgePage};
        """)
        self.assertEqual(result,{'lines':'1','hover':'3','relations':1,'restoredLines':1})



    def test_expanded_member_link_survives_real_initialization(self):
        result=self.run_application(ontology(4), """
            api.renderGraph();result={atlas:api.state.atlasOverview,depth:api.state.displayDepth,group:api.state.atlasGroupKey,selected:api.state.selectedId,others:api.state.renderedGraph.nodes.filter(n=>n.bucketKind==='module').length};
        """, "file:///snapshot.html?lens=architecture&snapshot=synthetic&display=3&group=module%3A000&component=fn%3A000%3Aa&entity=fn%3A000%3Aa&hover=3", initialize=True)
        self.assertEqual(result,{'atlas':True,'depth':3,'group':'module:000','selected':'fn:000:a','others':3})

if __name__ == "__main__":
    unittest.main()
