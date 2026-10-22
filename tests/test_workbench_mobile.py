"""Mobile viewport and pointer logic in the shipped JS, not a browser emulator."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest

import test_workbench_quality_ui as ui
from test_workbench_spatial import SPATIAL_HELPERS, layered_modules


class WorkbenchMobileTests(unittest.TestCase):
    def run_app(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is unavailable for mobile interaction checks')
        harness = ui.JS_HARNESS.replace('buildModuleLayout,runSearch',
            'buildModuleLayout,project3d,reset3dCamera,cumulativeLayerGraph,resize3dViewport,syncCompactWorkspace,runSearch')
        completed = subprocess.run([node, '-e', harness, str(ui.JS)],
            input=json.dumps({'payload': layered_modules(), 'script': SPATIAL_HELPERS + script}),
            text=True, encoding='utf-8', capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_mobile_dom_targets_exist_and_browser_zoom_remains_enabled(self):
        from html.parser import HTMLParser
        class Page(HTMLParser):
            def __init__(self):
                super().__init__(); self.ids=[]; self.viewport=''
            def handle_starttag(self, tag, pairs):
                attrs=dict(pairs)
                if 'id' in attrs: self.ids.append(attrs['id'])
                if tag == 'meta' and attrs.get('name') == 'viewport':
                    self.viewport=attrs.get('content', '')
        page=Page(); page.feed(ui.HTML.read_text(encoding='utf-8'))
        for target in ('workspace-heading', 'workspace-identity', 'snapshot-strip',
                       'mobile-workspace-context', 'mobile-workspace-context-content',
                       'mobile-workspace-context-close', 'mobile-workspace-context-summary',
                       'graph-3d-legend'):
            self.assertEqual(page.ids.count(target), 1, target)
        self.assertIn('viewport-fit=cover', page.viewport)
        self.assertNotIn('user-scalable=no', page.viewport)
        self.assertNotIn('maximum-scale=1', page.viewport)
        # Portable demos reject these private registration markers in all bytes.
        for marker in ('workspaceId', 'sourceFingerprint'):
            self.assertNotIn(marker, ui.JS.read_text(encoding='utf-8'))

    def test_short_mobile_canvas_fits_nodes_without_subtracting_external_controls(self):
        rows = self.run_app(r'''
          result=[];
          for(const [width,height] of [[320,240],[390,320],[430,380],[760,240]])for(const ratio of [1,2]){
            window.devicePixelRatio=ratio;enableCanvas(width,height);prepareCumulative();
            api.dom.atlasControls.offsetTop=180;api.dom.atlasControls.offsetHeight=140;
            api.reset3dCamera();const viewport={width:width*ratio,height:height*ratio,ratio};
            const points=[...api.state.threeDPositions.values()].map(p=>api.project3d(p,viewport));
            const xs=points.map(p=>p.x/ratio),ys=points.map(p=>p.y/ratio);
            result.push({width,height,visible:points.every(p=>p.x>=20*ratio&&p.x<=(width-20)*ratio&&p.y>=20*ratio&&p.y<=(height-20)*ratio),
              utilization:Math.max((Math.max(...xs)-Math.min(...xs))/(width-56),(Math.max(...ys)-Math.min(...ys))/(height-56))});
          }
        ''')
        for row in rows:
            with self.subTest(row=row):
                self.assertTrue(row['visible'])
                self.assertGreater(row['utilization'], .65)

    def test_mobile_layer_add_remove_keeps_entire_graph_in_canvas(self):
        rows = self.run_app(r'''
          enableCanvas(390,260);api.bindEvents();window.confirm=()=>true;api.dom.explorationFull.events.click();api.showAtlasHome();result=[];
          for(const action of ['layerNext','layerNext','layerNext','layerPrevious','layerPrevious']){
            api.dom[action].events.click();const points=api.state.threeDProjectedNodes;
            result.push({depth:api.state.layerDepth,count:points.length,visible:points.every(p=>p.x>=20&&p.x<=370&&p.y>=20&&p.y<=240)});
          }
        ''')
        self.assertEqual([r['depth'] for r in rows], [2, 3, 4, 3, 2])
        self.assertTrue(all(r['visible'] for r in rows))
        self.assertEqual(rows[0]['count'], rows[-1]['count'])

    def test_resize_observer_refits_auto_view_but_preserves_deliberate_zoom(self):
        result = self.run_app(r'''
          enableCanvas(390,420);prepareCumulative();api.reset3dCamera();let observed=null,callback=null;
          window.ResizeObserver=class {constructor(fn){callback=fn;}observe(el){observed=el;}};
          api.bindEvents();callback();const initial=api.state.camera.zoom;
          api.dom.graph3dCanvas.clientHeight=240;callback();const fitted=api.state.camera.zoom;
          api.dom.zoomIn.events.click();const manual=JSON.stringify(api.state.camera);
          api.dom.graph3dCanvas.clientHeight=360;callback();
          result={observed:observed===api.dom.graph3dCanvas,initial,fitted,manualPreserved:manual===JSON.stringify(api.state.camera)};
        ''')
        self.assertTrue(result['observed'])
        self.assertLess(result['fitted'], result['initial'])
        self.assertTrue(result['manualPreserved'])

    def test_touch_pinch_zoom_pan_and_release_do_not_select_or_jump(self):
        result = self.run_app(r'''
          enableCanvas(390,320);prepareCumulative();api.reset3dCamera();api.bindEvents();
          const e=api.dom.graph3dCanvas.events;
          const touch=(pointerId,x,y)=>({pointerId,pointerType:'touch',clientX:x,clientY:y});
          const before={...api.state.camera};
          e.pointerdown(touch(1,120,120));e.pointerdown(touch(2,220,120));
          e.pointermove(touch(2,270,150));const pinched={...api.state.camera};
          e.pointerup(touch(2,270,150));e.pointermove(touch(1,120,120));
          const noJump=pinched.yaw===api.state.camera.yaw&&pinched.pitch===api.state.camera.pitch;
          e.pointerup(touch(1,120,120));
          result={before,pinched,noJump,selected:api.state.selectedId,dragging:api.state.threeDDragging,touches:api.state.threeDTouchPointers.size};
        ''')
        self.assertGreater(result['pinched']['zoom'], result['before']['zoom'])
        self.assertNotEqual(result['pinched']['x'], result['before']['x'])
        self.assertEqual(result['pinched']['yaw'], result['before']['yaw'])
        self.assertTrue(result['noJump'])
        self.assertFalse(result['selected'] or result['dragging'] or result['touches'])

    def test_cancelled_touch_recovers_and_one_finger_still_rotates(self):
        result = self.run_app(r'''
          enableCanvas(390,320);prepareCumulative();api.reset3dCamera();api.bindEvents();const e=api.dom.graph3dCanvas.events;
          const touch=(pointerId,x,y)=>({pointerId,pointerType:'touch',clientX:x,clientY:y});
          e.pointerdown(touch(1,100,100));e.pointerdown(touch(2,200,100));
          e.pointercancel(touch(1,100,100));e.pointerup(touch(2,200,100));
          const before=api.state.camera.yaw;e.pointerdown(touch(3,100,100));e.pointermove(touch(3,130,100));e.pointerup(touch(3,130,100));
          result={before,after:api.state.camera.yaw,selected:api.state.selectedId,touches:api.state.threeDTouchPointers.size,dragging:api.state.threeDDragging};
        ''')
        self.assertAlmostEqual(result['after'] - result['before'], .15)
        self.assertFalse(result['selected'] or result['touches'] or result['dragging'])

    def test_mobile_labels_remain_available_in_short_canvas(self):
        result = self.run_app(r'''
          enableCanvas(390,240);const labels=[];const gradient={addColorStop:()=>{}};
          api.dom.graph3dCanvas.getContext=()=>new Proxy({},{get:(_,key)=>key==='measureText'?text=>({width:text.length*6}):key==='fillText'?(text,x,y)=>labels.push({text,x,y}):key==='createRadialGradient'?()=>gradient:()=>{},set:()=>true});
          api.dom.atlasControls.offsetTop=180;api.dom.atlasControls.offsetHeight=140;
          api.showAtlasHome();api.reset3dCamera();result=labels;
        ''')
        self.assertGreater(len(result), 0)
        self.assertTrue(all(12 <= label['y'] <= 230 for label in result))

    def test_workspace_context_moves_and_restores_existing_information(self):
        result = self.run_app(r'''
          window.innerWidth=390;api.syncCompactWorkspace();
          const mobile=api.dom.viewDescription.parentElement===api.dom.mobileWorkspaceContextContent && api.dom.snapshotStrip.parentElement===api.dom.mobileWorkspaceContextContent;
          api.dom.mobileWorkspaceContext.open=true;api.syncCompactWorkspace();const retained=api.dom.mobileWorkspaceContext.open;
          window.innerWidth=1200;api.syncCompactWorkspace();
          result={mobile,retained,desktop:api.dom.viewDescription.parentElement===api.dom.workspaceTitleBlock&&api.dom.snapshotStrip.parentElement===api.dom.workspaceHeading,closed:!api.dom.mobileWorkspaceContext.open};
        ''')
        self.assertTrue(all(result.values()))


if __name__ == '__main__':
    unittest.main()
