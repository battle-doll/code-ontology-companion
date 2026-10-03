"""Shipped-JS checks for cumulative hierarchy layers and call-hover controls."""
from __future__ import annotations

import unittest

import test_workbench_quality_ui as ui_tests


def call_chain() -> dict:
    names = ("a", "b", "c", "d")
    return {
        "meta": {"snapshotId": "call-chain", "repositoryName": "Call Chain"},
        "nodes": [
            {
                "id": name,
                "name": name,
                "type": "Function",
                "language": "Python",
                "path": f"src/{name}/{name}.py",
            }
            for name in names
        ],
        "edges": [
            {"source": source, "target": target, "type": "CALLS"}
            for source, target in (("a", "b"), ("b", "c"), ("c", "d"))
        ],
    }


def hierarchy(modules: int = 2) -> dict:
    """Two independent branches, with real ownership down to a fifth layer."""
    nodes, edges = [], []
    for index in range(modules):
        suffix = f"{index:03}"
        path = f"src/module{suffix}.py"
        for kind, name in (("Module", "module"), ("Class", "class"), ("Method", "method"),
                           ("RuntimeBranch", "branch"), ("RuntimeBranch", "nested")):
            nodes.append({"id": f"{name}:{suffix}", "name": f"{name}{suffix}",
                          "type": kind, "language": "Python", "path": path})
        for source, target, relation in (("module", "class", "DECLARES"),
                                         ("class", "method", "DECLARES"),
                                         ("method", "branch", "DECLARES_RUNTIME_BRANCH"),
                                         ("branch", "nested", "DECLARES_RUNTIME_BRANCH")):
            edges.append({"source": f"{source}:{suffix}", "target": f"{target}:{suffix}", "type": relation})
        for offset in (1, 2, 3):
            target = f"{(index + offset) % modules:03}"
            edges.append({"source": f"method:{suffix}", "target": f"method:{target}", "type": "CALLS"})
    return {"meta": {"snapshotId": "layers", "repositoryName": "Synthetic Layers"}, "nodes": nodes, "edges": edges}


def aggregated_calls() -> dict:
    nodes = []
    edges = []
    for index in range(5):
        nodes.extend(
            [
                {
                    "id": f"a:{index}",
                    "name": f"a{index}",
                    "type": "Function",
                    "language": "Python",
                    "path": f"src/a/a{index}.py",
                },
                {
                    "id": f"b:{index}",
                    "name": f"b{index}",
                    "type": "Function",
                    "language": "Python",
                    "path": f"src/b/b{index}.py",
                },
            ]
        )
        edges.append({"source": f"a:{index}", "target": f"b:{index}", "type": "CALLS"})
    return {
        "meta": {"snapshotId": "aggregate-calls", "repositoryName": "Aggregate Calls"},
        "nodes": nodes,
        "edges": edges,
    }


class CumulativeLayerTests(unittest.TestCase):
    run_application = ui_tests.WorkbenchQualityUiTests.run_application

    def test_layers_keep_ancestors_and_expand_every_branch_without_paging(self) -> None:
        result = self.run_application(hierarchy(), """
            api.bindEvents();api.renderGraph();
            let confirms=0;window.confirm=()=>{confirms++;return true;};const rows=[];
            api.dom.layerNext.events.click();api.dom.layerPrevious.events.click();
            for(let depth=1;depth<=5;depth++){
              if(depth>1)api.dom.layerNext.events.click();const graph=api.state.renderedGraph;
              const keys=[...graph.visibleKeys,...graph.internalKeys,...graph.offPageKeys,...graph.offLineKeys];
              const members=graph.nodes.flatMap(n=>n.memberIds);
              rows.push({depth:api.state.layerDepth,ids:graph.nodes.map(n=>n.id),
                canonical:graph.nodes.map(n=>n.canonicalId||n.id),confirms,
                groups:Array.from(new Set(graph.nodes.map(n=>api.moduleGroup(n).key))),
                uncapped:!graph.truncated&&!graph.offPageKeys.length&&!graph.offLineKeys.length,
                memberPartition:members.length===api.nodes.length&&new Set(members).size===api.nodes.length&&members.every(id=>api.nodeById.has(id)),
                edgePartition:keys.length===api.edges.length&&new Set(keys).size===api.edges.length&&keys.every(k=>api.edgeByKey.has(k)),
                boundedSame:api.bounded3dGraph(graph)===graph});
            }
            result=rows;
        """)
        self.assertEqual([row["depth"] for row in result], [1, 2, 3, 4, 5])
        self.assertEqual([row["confirms"] for row in result], [0, 0, 0, 1, 2])
        for row in result:
            self.assertEqual(set(row["groups"]), {"module:000", "module:001"})
            self.assertTrue(row["uncapped"])
            self.assertTrue(row["memberPartition"])
            self.assertTrue(row["edgePartition"])
            self.assertTrue(row["boundedSame"])
        for before, after in zip(result, result[1:]):
            self.assertTrue(set(before["ids"]).issubset(after["ids"]))
            self.assertGreater(len(after["ids"]), len(before["ids"]))
        for index, kind in ((1, "class"), (2, "method"), (3, "branch"), (4, "nested")):
            for suffix in ("000", "001"):
                symbol = f"{kind}:{suffix}"
                self.assertNotIn(symbol, result[index - 1]["canonical"])
                self.assertIn(symbol, result[index]["canonical"])

    def test_heavy_layer_cancel_preserves_all_state_and_collapse_needs_no_confirm(self) -> None:
        result = self.run_application(hierarchy(), """
            api.bindEvents();api.renderGraph();let confirms=0;window.confirm=()=>{confirms++;return true;};
            for(let i=0;i<2;i++)api.dom.layerNext.events.click();
            function snapshot(){return JSON.stringify({depth:api.state.layerDepth,scope:api.state.sourceScope,
              relation:api.state.relationFilter,category:api.state.categoryFilter,query:api.state.groupQuery,
              history:api.state.selectionHistory,camera:api.state.camera,url:window.location.href,
              selection:api.state.selectedId,root:api.state.rootId});}
            const before=snapshot(),graph=api.state.renderedGraph;
            window.confirm=()=>{confirms++;return false;};api.dom.layerNext.events.click();
            const cancelled={identical:before===snapshot(),sameGraph:graph===api.state.renderedGraph,confirms};
            window.confirm=()=>{confirms++;return true;};api.dom.layerNext.events.click();
            const accepted={depth:api.state.layerDepth,confirms};
            api.dom.layerPrevious.events.click();const collapsed={depth:api.state.layerDepth,confirms};
            api.dom.layerNext.events.click();result={cancelled,accepted,collapsed,reentered:{depth:api.state.layerDepth,confirms}};
        """)
        self.assertEqual(result["cancelled"], {"identical": True, "sameGraph": True, "confirms": 1})
        self.assertEqual(result["accepted"], {"depth": 4, "confirms": 2})
        self.assertEqual(result["collapsed"], {"depth": 3, "confirms": 2})
        self.assertEqual(result["reentered"], {"depth": 4, "confirms": 3})

    def test_all_module_regions_and_lines_exceed_normal_caps_without_truncation(self) -> None:
        result = self.run_application(hierarchy(161), """
            api.bindEvents();api.renderGraph();let confirms=0;window.confirm=()=>{confirms++;return true;};
            api.dom.layerNext.events.click();api.dom.layerPrevious.events.click();const first=api.state.renderedGraph;
            api.dom.layerNext.events.click();api.dom.layerNext.events.click();const third=api.state.renderedGraph;
            result={firstNodes:first.nodes.length,thirdNodes:third.nodes.length,thirdEdges:third.edges.length,
              groups:new Set(third.nodes.map(n=>api.moduleGroup(n).key)).size,confirms,
              uncapped:!third.truncated&&!third.offPageKeys.length&&!third.offLineKeys.length,
              canonical:third.nodes.map(n=>n.canonicalId||n.id)};
        """)
        self.assertEqual(result["firstNodes"], 161)
        self.assertGreater(result["thirdNodes"], 160)
        self.assertGreater(result["thirdEdges"], 480)
        self.assertEqual(result["groups"], 161)
        self.assertEqual(result["confirms"], 0)
        self.assertTrue(result["uncapped"])
        for index in range(161):
            self.assertIn(f"class:{index:03}", result["canonical"])
            self.assertIn(f"method:{index:03}", result["canonical"])

    def test_expansion_adds_spatial_room_and_zooms_in(self) -> None:
        result = self.run_application(hierarchy(), """
            api.bindEvents();api.renderGraph();window.confirm=()=>true;const rows=[];
            api.dom.layerNext.events.click();api.dom.layerPrevious.events.click();
            for(let i=0;i<3;i++){
              if(i)api.dom.layerNext.events.click();api.state.threeDPositions.clear();api.buildModuleLayout(api.state.renderedGraph);
              rows.push({depth:api.state.layerDepth,zoom:api.state.camera.zoom,
                extent:Math.max(...Array.from(api.state.threeDPositions.values()).map(p=>Math.hypot(p.x,p.y,p.z))),
                finite:Array.from(api.state.threeDPositions.values()).every(p=>[p.x,p.y,p.z].every(Number.isFinite)),
                positions:api.state.threeDPositions.size,nodes:api.state.renderedGraph.nodes.length});
            }
            api.dom.layerPrevious.events.click();api.state.threeDPositions.clear();api.buildModuleLayout(api.state.renderedGraph);
            result={rows,collapsed:{depth:api.state.layerDepth,zoom:api.state.camera.zoom,
              extent:Math.max(...Array.from(api.state.threeDPositions.values()).map(p=>Math.hypot(p.x,p.y,p.z)))}};
        """)
        for row in result["rows"]:
            self.assertTrue(row["finite"])
            self.assertEqual(row["positions"], row["nodes"])
        for before, after in zip(result["rows"], result["rows"][1:]):
            self.assertGreater(after["extent"], before["extent"])
            self.assertGreater(after["zoom"], before["zoom"])
        self.assertEqual(result["collapsed"]["depth"], 2)
        self.assertLess(result["collapsed"]["extent"], result["rows"][-1]["extent"])
        self.assertLess(result["collapsed"]["zoom"], result["rows"][-1]["zoom"])

    def test_normal_navigation_exits_layers_and_restores_normal_caps(self) -> None:
        result = self.run_application(hierarchy(161), """
            api.bindEvents();api.renderGraph();window.confirm=()=>true;
            function inspect(){return {depth:api.state.layerDepth,nodes:api.state.renderedGraph.nodes.length,
              edges:api.state.renderedGraph.edges.length};}
            api.dom.layerNext.events.click();api.dom.atlasHome.events.click();const home=inspect();
            api.dom.layerNext.events.click();api.openAtlasGroup('module:000');const group=inspect();
            api.dom.layerNext.events.click();api.switchLens('impact');api.renderGraph();const lens=inspect();
            result={home,group,lens};
        """)
        for exit_state in result.values():
            self.assertEqual(exit_state["depth"], 0)
            self.assertLessEqual(exit_state["nodes"], 160)
            self.assertLessEqual(exit_state["edges"], 480)

    def test_cumulative_state_is_not_serialized_or_replayed_from_url(self) -> None:
        result = self.run_application(hierarchy(), """
            api.bindEvents();api.renderGraph();window.confirm=()=>true;
            for(let i=0;i<4;i++)api.dom.layerNext.events.click();
            const url=api.selectionUrl();window.location=url;const replay=api.readSelectionLink();
            api.showAtlasHome();window.location=new URL('file:///snapshot.html?snapshot=layers&full=1&layerDepth=5&layer=5&layers=5');
            const forged=api.readSelectionLink();
            result={queryKeys:Array.from(url.searchParams.keys()),replay,forged,depth:api.state.layerDepth};
        """)
        self.assertTrue(set(result["queryKeys"]).isdisjoint({"full", "layer", "layers", "layerDepth", "display"}))
        self.assertEqual(result["depth"], 0)
        for selection in (result["replay"], result["forged"]):
            self.assertEqual(selection["navigation"]["displayDepth"], 1)
            self.assertFalse(selection["navigation"].get("layerDepth", 0))

    def test_hover_depth_restores_last_anchor_after_visual_clear(self) -> None:
        result = self.run_application(call_chain(), """
            api.bindEvents();api.renderGraph();api.setCallHover('a',null);
            const one=api.state.callHighlight.edges.size;
            api.clearCallHover();
            const cleared={edges:api.state.callHighlight.edges.size,last:api.state.lastCallHover&&api.state.lastCallHover.nodeId};
            api.dom.hoverDepth.value='2';api.dom.hoverDepth.events.change();
            const two=api.state.callHighlight.edges.size;
            api.clearCallHover();api.dom.hoverDepth.value='3';api.dom.hoverDepth.events.change();
            const three=api.state.callHighlight.edges.size;
            api.renderGraph();
            result={one,cleared,two,three,afterRender:api.state.lastCallHover};
        """)
        self.assertEqual(result["cleared"], {"edges": 0, "last": "a"})
        self.assertEqual([result["one"], result["two"], result["three"]], [1, 2, 3])
        self.assertIsNone(result["afterRender"])

    def test_call_summary_reports_canonical_calls_and_aggregate_lines_separately(self) -> None:
        result = self.run_application(aggregated_calls(), """
            api.bindEvents();api.renderGraph();
            const bucket=api.state.renderedGraph.nodes.find(node=>node.memberIds.includes('a:0'));
            api.setCallHover(bucket.id,null,bucket.memberIds);
            result={canonical:api.state.callHighlight.edges.size,visible:api.state.hoverViewEdges.size,
              aggregateLines:api.state.renderedGraph.edges.length,summary:api.dom.callTraceSummary.textContent};
        """)
        self.assertEqual(result["canonical"], 5)
        self.assertEqual(result["visible"], 1)
        self.assertEqual(result["aggregateLines"], 1)
        self.assertIn("원본 호출 5개", result["summary"])
        self.assertIn("화면 선 1개", result["summary"])


if __name__ == "__main__":
    unittest.main()
