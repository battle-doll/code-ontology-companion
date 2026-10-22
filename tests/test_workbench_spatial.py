"""Shipped-JS geometry checks; these do not prove actual browser rendering."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest

import test_workbench_quality_ui as ui_tests


def uneven_modules() -> dict:
    """Synthetic density skew, without copying repository names or source data."""
    nodes, edges = [], []
    for group, count in enumerate((1279, 96, 10)):
        module = f"module:{group}"
        path = f"src/group{group}.py"
        nodes.append({"id": module, "name": f"group{group}", "type": "Module",
                      "language": "Python", "path": path})
        for index in range(count):
            symbol = f"function:{group}:{index:04}"
            nodes.append({"id": symbol, "name": f"function{index:04}", "type": "Function",
                          "language": "Python", "path": path})
            edges.append({"source": module, "target": symbol, "type": "DECLARES"})
        edges.append({"source": f"function:{group}:0000", "target": f"function:{(group + 1) % 3}:0000",
                      "type": "CALLS"})
    return {"meta": {"snapshotId": "synthetic-spatial", "repositoryName": "Synthetic Spatial"},
            "nodes": nodes, "edges": edges}


def layered_modules() -> dict:
    """Twelve independent modules with enough symbols at each ownership level."""
    nodes, edges = [], []
    for group in range(12):
        path = f"src/layered{group:02}.py"
        module = f"module:{group:02}"

        def add(identifier, kind, parent=None, relation="DECLARES"):
            nodes.append({"id": identifier, "name": identifier, "type": kind,
                          "language": "Python", "path": path})
            if parent:
                edges.append({"source": parent, "target": identifier, "type": relation})

        add(module, "Module")
        for owner in range(3):
            class_id = f"class:{group:02}:{owner}"
            add(class_id, "Class", module)
            for method in range(3):
                method_id = f"method:{group:02}:{owner}:{method}"
                add(method_id, "Method", class_id)
                for branch in range(3):
                    add(f"branch:{group:02}:{owner}:{method}:{branch}", "RuntimeBranch",
                        method_id, "DECLARES_RUNTIME_BRANCH")
        edges.append({"source": f"method:{group:02}:0:0",
                      "target": f"method:{(group + 1) % 12:02}:0:0", "type": "CALLS"})
    return {"meta": {"snapshotId": "layer-button-cycle", "repositoryName": "Synthetic Layers"},
            "nodes": nodes, "edges": edges}


SPATIAL_HELPERS = r"""
function enableCanvas(width,height){
  const gradient={addColorStop:()=>{}};
  const context=new Proxy({}, {get:(_target,name)=>name==='measureText'?(text)=>({width:text.length*6}):name==='createRadialGradient'?()=>gradient:(...args)=>{if(args.some(x=>typeof x==='number'&&!Number.isFinite(x)))throw new Error('non-finite canvas coordinate');},set:()=>true});
  api.dom.graph3dCanvas.getContext=()=>context;
  api.dom.graph3dCanvas.getBoundingClientRect=()=>({left:0,top:0,width,height});
  api.dom.graph3dCanvas.clientWidth=width;api.dom.graph3dCanvas.clientHeight=height;
  api.dom.graph3d.clientWidth=width;api.dom.graph3d.clientHeight=height;
  api.dom.detailsPanel.hidden=true;
}
function prepareCumulative(){
  api.state.explorationMode='full';
  const graph=api.cumulativeLayerGraph(2);
  api.state.layerDepth=graph.layerDepth;api.state.threeDGraph=graph;
  api.state.threeDPositions.clear();api.buildModuleLayout(graph);
  return graph;
}
function covarianceVolume(points){
  const mean={x:0,y:0,z:0};for(const p of points)for(const key of ['x','y','z'])mean[key]+=p[key]/points.length;
  let xx=0,xy=0,xz=0,yy=0,yz=0,zz=0;
  for(const p of points){const x=p.x-mean.x,y=p.y-mean.y,z=p.z-mean.z;xx+=x*x;xy+=x*y;xz+=x*z;yy+=y*y;yz+=y*z;zz+=z*z;}
  const determinant=xx*(yy*zz-yz*yz)-xy*(xy*zz-xz*yz)+xz*(xy*yz-xz*yy);
  return determinant/Math.max(1,(xx+yy+zz)**3);
}
function spatialShape(points){
  const spans=['x','y','z'].map(key=>Math.max(...points.map(p=>p[key]))-Math.min(...points.map(p=>p[key])));
  return {volume:covarianceVolume(points),depthRatio:spans[2]/Math.max(1,spans[0],spans[1])};
}
"""


class WorkbenchSpatialTests(unittest.TestCase):
    def run_application(self, payload: dict, script: str):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable for application geometry checks")
        harness = ui_tests.JS_HARNESS.replace(
            "buildModuleLayout,runSearch",
            "buildModuleLayout,project3d,reset3dCamera,cumulativeLayerGraph,runSearch",
        )
        result = subprocess.run(
            [node, "-e", harness, str(ui_tests.JS)],
            input=json.dumps({"payload": payload, "script": SPATIAL_HELPERS + script}),
            text=True, encoding="utf-8", capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_uneven_cumulative_layout_preserves_all_source_nodes_and_edges(self):
        result = self.run_application(uneven_modules(), r"""
            const graph=prepareCumulative();
            const members=graph.nodes.flatMap(n=>n.memberIds);
            const keys=[...graph.visibleKeys,...graph.internalKeys,...graph.offPageKeys,...graph.offLineKeys];
            result={members:members.length,uniqueMembers:new Set(members).size,sourceNodes:api.nodes.length,
              validMembers:members.every(id=>api.nodeById.has(id)),edges:keys.length,uniqueEdges:new Set(keys).size,
              sourceEdges:api.edges.length,validEdges:keys.every(key=>api.edgeByKey.has(key)),
              positions:api.state.threeDPositions.size,displayed:graph.nodes.length,
              finite:Array.from(api.state.threeDPositions.values()).every(p=>[p.x,p.y,p.z].every(Number.isFinite))};
        """)
        self.assertEqual(result["members"], result["sourceNodes"])
        self.assertEqual(result["uniqueMembers"], result["sourceNodes"])
        self.assertEqual(result["edges"], result["sourceEdges"])
        self.assertEqual(result["uniqueEdges"], result["sourceEdges"])
        self.assertEqual(result["positions"], result["displayed"])
        self.assertTrue(result["validMembers"] and result["validEdges"] and result["finite"])

    def test_same_level_siblings_are_non_coplanar_and_layout_is_deterministic(self):
        result = self.run_application(uneven_modules(), r"""
            const graph=prepareCumulative();const first=JSON.stringify(Array.from(api.state.threeDPositions));
            const siblings=graph.nodes.filter(n=>n.id.startsWith('function:0:')).map(n=>api.state.threeDPositions.get(n.id));
            api.state.threeDPositions.clear();api.buildModuleLayout(graph);
            result={volume:covarianceVolume(siblings),count:siblings.length,
              unique:new Set(siblings.map(p=>[p.x,p.y,p.z].join(','))).size,
              deterministic:first===JSON.stringify(Array.from(api.state.threeDPositions))};
        """)
        self.assertEqual(result["count"], 1279)
        self.assertEqual(result["unique"], result["count"])
        self.assertGreater(result["volume"], 0.0001)
        self.assertTrue(result["deterministic"])

    def test_normal_symbol_layout_keeps_render_caps_and_has_real_depth(self):
        result = self.run_application(uneven_modules(), r"""
            api.state.rootId='module:0';
            const graph=api.bounded3dGraph(api.neighborhood('module:0','architecture',2,'both'));
            api.buildModuleLayout(graph);
            const points=Array.from(api.state.threeDPositions.values());
            result={nodes:graph.nodes.length,edges:graph.edges.length,positions:points.length,
              finite:points.every(p=>[p.x,p.y,p.z].every(Number.isFinite)),volume:covarianceVolume(points)};
        """)
        self.assertGreater(result["nodes"], 10)
        self.assertLessEqual(result["nodes"], 160)
        self.assertLessEqual(result["edges"], 480)
        self.assertEqual(result["positions"], result["nodes"])
        self.assertTrue(result["finite"])
        self.assertGreater(result["volume"], 0.0001)

    def test_fit_recovers_from_pan_and_zoom_without_near_plane_clamping(self):
        result = self.run_application(uneven_modules(), r"""
            const rows=[];
            for(const [width,height,ratio] of [[1200,800,1],[320,640,1],[768,1024,2],[2000,900,2]]){
              window.devicePixelRatio=ratio;enableCanvas(width,height);prepareCumulative();
              Object.assign(api.state.camera,{x:8000,y:-9000,z:5000,yaw:2,pitch:1.2,zoom:2.4});
              api.reset3dCamera();const fitted={...api.state.camera};
              const viewport={width:width*ratio,height:height*ratio,ratio};
              const initial=Array.from(api.state.threeDPositions.values()).map(p=>api.project3d(p,viewport));
              for(const yawDelta of [0,Math.PI/2,Math.PI]){
                api.state.camera.yaw=fitted.yaw+yawDelta;
                const projected=Array.from(api.state.threeDPositions.values()).map(p=>api.project3d(p,viewport));
                rows.push({width,height,ratio,yawDelta,finite:projected.every(p=>[p.x,p.y,p.z,p.scale,p.perspective,p.cameraDepth].every(Number.isFinite)),
                  nearClamp:projected.filter(p=>p.cameraDepth<=240).length,
                  visible:projected.filter(p=>p.x>=0&&p.x<=viewport.width&&p.y>=0&&p.y<=viewport.height).length,total:projected.length});
              }
              api.reset3dCamera();const repeated=Array.from(api.state.threeDPositions.values()).map(p=>api.project3d(p,viewport));
              if(JSON.stringify(initial)!==JSON.stringify(repeated))throw new Error('Fit is not deterministic');
            }result=rows;
        """)
        for row in result:
            with self.subTest(width=row["width"], ratio=row["ratio"], yaw=row["yawDelta"]):
                self.assertTrue(row["finite"])
                self.assertEqual(row["nearClamp"], 0)
                if row["yawDelta"] == 0:
                    self.assertEqual(row["visible"], row["total"])

    def test_zoom_out_controls_do_not_zoom_in_after_a_small_fit(self):
        result = self.run_application(uneven_modules(), r"""
            enableCanvas(1200,800);prepareCumulative();api.bindEvents();const rows=[];
            for(const action of [()=>api.dom.zoomOut.events.click(),
              ()=>api.dom.graph3dCanvas.events.wheel({deltaY:1,preventDefault:()=>{}}),
              ()=>api.dom.graph3dCanvas.events.keydown({key:'-',preventDefault:()=>{}})]){
              api.reset3dCamera();const before=api.state.camera.zoom;action();rows.push({before,after:api.state.camera.zoom});
            }result=rows;
        """)
        for row in result:
            self.assertLess(row["before"], 0.35)
            self.assertLess(row["after"], row["before"])
            self.assertGreater(row["after"], 0)

    def test_single_node_fit_stays_finite(self):
        payload = {"meta": {"snapshotId": "single"}, "nodes": [
            {"id": "one", "name": "one", "type": "Module", "language": "Python", "path": "one.py"}
        ], "edges": []}
        result = self.run_application(payload, r"""
            enableCanvas(320,640);prepareCumulative();api.reset3dCamera();
            const points=Array.from(api.state.threeDPositions.values()).map(p=>api.project3d(p,{width:320,height:640,ratio:1}));
            result={count:points.length,finite:points.every(p=>[p.x,p.y,p.z,p.scale,p.perspective].every(Number.isFinite))};
        """)
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["finite"])

    def test_small_scene_stays_ahead_of_near_plane_after_tilt_and_pan(self):
        payload = {"meta": {"snapshotId": "small-pan"}, "nodes": [
            {"id": "one", "name": "one", "type": "Module", "language": "Python", "path": "one.py"}
        ], "edges": []}
        result = self.run_application(payload, r"""
            enableCanvas(320,640);prepareCumulative();api.reset3dCamera();
            api.state.camera.pitch=1.35;api.state.camera.y=2000;
            const point=api.project3d(Array.from(api.state.threeDPositions.values())[0],{width:320,height:640,ratio:1});
            result={cameraDepth:point.cameraDepth,finite:[point.x,point.y,point.scale,point.perspective].every(Number.isFinite)};
        """)
        self.assertTrue(result["finite"])
        self.assertGreater(result["cameraDepth"], 240)

    def test_hierarchy_height_follows_depth_even_when_source_nodes_are_reversed(self):
        kinds = ("Module", "Class", "Method", "RuntimeBranch", "RuntimeBranch")
        payload = {"meta": {"snapshotId": "reverse-order"}, "nodes": [
            {"id": f"node:{depth}", "name": f"node{depth}", "type": kind,
             "language": "Python", "path": "src/reversed.py"}
            for depth, kind in enumerate(kinds)
        ][::-1], "edges": [
            {"source": f"node:{depth - 1}", "target": f"node:{depth}",
             "type": "DECLARES_RUNTIME_BRANCH" if depth >= 3 else "DECLARES"}
            for depth in range(1, len(kinds))
        ]}
        result = self.run_application(payload, r"""
            const graph=api.cumulativeLayerGraph(5);api.state.threeDPositions.clear();api.buildModuleLayout(graph);
            result=graph.nodes.map(node=>({depth:node.layerDepth,y:api.state.threeDPositions.get(node.id).y}))
              .sort((a,b)=>a.depth-b.depth);
        """)
        self.assertEqual([row["depth"] for row in result], [1, 2, 3, 4, 5])
        for parent, child in zip(result, result[1:]):
            self.assertLess(parent["y"], child["y"])

    def test_canvas_layer_button_cycle_keeps_modules_and_nodes_volumetric(self):
        result = self.run_application(layered_modules(), r"""
            enableCanvas(1200,800);api.bindEvents();api.renderGraph();window.confirm=()=>true;
            api.dom.explorationFull.events.click();
            api.dom.layerNext.events.click();api.dom.layerPrevious.events.click();
            const rows=[],seen=new Map();let previous=null;
            function inspect(){
              const graph=api.state.renderedGraph,depth=api.state.layerDepth;
              const positions=Array.from(api.state.threeDPositions.entries()).sort((a,b)=>a[0].localeCompare(b[0]));
              const centers=api.state.threeDGroups.map(group=>[group.descriptor.key,group.center]).sort((a,b)=>a[0].localeCompare(b[0]));
              const geometry=JSON.stringify({positions,centers}),members=graph.nodes.flatMap(node=>node.memberIds);
              const keys=[...graph.visibleKeys,...graph.internalKeys,...graph.offPageKeys,...graph.offLineKeys];
              const ids=new Set(graph.nodes.map(node=>node.id));
              rows.push({depth,nodeShape:spatialShape(positions.map(item=>item[1])),groupShape:spatialShape(centers.map(item=>item[1])),
                groups:centers.length,displayed:graph.nodes.length,positions:positions.length,projected:api.state.threeDProjectedNodes.length,
                validMembers:members.length===api.nodes.length&&new Set(members).size===api.nodes.length&&members.every(id=>api.nodeById.has(id)),
                validEdges:keys.length===api.edges.length&&new Set(keys).size===api.edges.length&&keys.every(key=>api.edgeByKey.has(key)),
                sameGeometry:!seen.has(depth)||seen.get(depth)===geometry,
                ancestorsRetained:!previous||(depth>previous.depth?Array.from(previous.ids).every(id=>ids.has(id)):Array.from(ids).every(id=>previous.ids.has(id))),
                finite:api.state.threeDProjectedNodes.every(point=>[point.x,point.y,point.z,point.scale,point.cameraDepth].every(Number.isFinite)),
                complete:graph.cumulative&&!graph.truncated&&!graph.offPageKeys.length&&!graph.offLineKeys.length});
              seen.set(depth,geometry);previous={depth,ids};
            }
            inspect();
            for(const next of [2,3,4,3,2,1]){
              (next>api.state.layerDepth?api.dom.layerNext:api.dom.layerPrevious).events.click();inspect();
            }
            result=rows;
        """)
        self.assertEqual([row["depth"] for row in result], [1, 2, 3, 4, 3, 2, 1])
        for row in result:
            with self.subTest(depth=row["depth"]):
                self.assertEqual(row["groups"], 12)
                self.assertEqual(row["positions"], row["displayed"])
                self.assertEqual(row["projected"], row["displayed"])
                for key in ("validMembers", "validEdges", "sameGeometry", "ancestorsRetained", "finite", "complete"):
                    self.assertTrue(row[key], key)
                # Nonzero z alone allows a nearly flat shelf with a small depth wobble.
                self.assertGreater(row["groupShape"]["depthRatio"], 0.40)
                self.assertGreater(row["nodeShape"]["depthRatio"], 0.35)
                self.assertGreater(row["groupShape"]["volume"], 0.005)
                self.assertGreater(row["nodeShape"]["volume"], 0.005)

    def test_canvas_heavy_layer_cancellation_preserves_camera_geometry_and_projection(self):
        result = self.run_application(layered_modules(), r"""
            enableCanvas(1200,800);api.bindEvents();api.renderGraph();
            api.dom.explorationFull.events.click();
            api.dom.layerNext.events.click();api.dom.layerNext.events.click();
            function snapshot(){return JSON.stringify({depth:api.state.layerDepth,camera:api.state.camera,
              positions:Array.from(api.state.threeDPositions),centers:api.state.threeDGroups.map(group=>group.center),
              projected:api.state.threeDProjectedNodes.map(point=>[point.node.id,point.x,point.y,point.z,point.scale]),
              history:api.state.selectionHistory,selection:api.state.selectedId,url:window.location.href,
              summary:api.dom.layerSummary.textContent});}
            const before=snapshot(),rendered=api.state.renderedGraph,canvasGraph=api.state.threeDGraph;let confirmations=0;
            window.confirm=()=>{confirmations++;return false;};api.dom.layerNext.events.click();
            const unchanged=before===snapshot()&&rendered===api.state.renderedGraph&&canvasGraph===api.state.threeDGraph;
            const cancelledDepth=api.state.layerDepth;
            window.confirm=()=>{confirmations++;return true;};api.dom.layerNext.events.click();
            result={unchanged,cancelledDepth,acceptedDepth:api.state.layerDepth,confirmations};
        """)
        self.assertEqual(result, {"unchanged": True, "cancelledDepth": 3, "acceptedDepth": 4, "confirmations": 2})


if __name__ == "__main__":
    unittest.main()
