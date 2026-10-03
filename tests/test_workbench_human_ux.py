from __future__ import annotations

import unittest

import test_workbench_quality_ui as ui


# These checks execute real shipped handlers and canvas caption placement. They
# do not replace browser measurements of layout, contrast or assistive support.
CANVAS = r"""
const labels=[];
const backing={};
const gradient={addColorStop:()=>{}};
const canvasContext=new Proxy(backing,{get:(target,name)=>name==='measureText'?value=>({width:value.length*6}):name==='fillText'?(text,x,y)=>labels.push({text,x,y,font:target.font}):name==='createRadialGradient'?()=>gradient:target[name]||(()=>{}),set:(target,name,value)=>{target[name]=value;return true;}});
api.dom.graph3dCanvas.getContext=()=>canvasContext;
"""


class WorkbenchHumanUxTests(unittest.TestCase):
    run_application = ui.WorkbenchQualityUiTests.run_application
    sample_payload = ui.WorkbenchQualityUiTests.sample_payload

    def test_click_and_enter_select_the_same_symbol_and_move_focus(self):
        results = []
        for activation in (
            "api.dom.searchResults.querySelectorAll(\"[role='option']\")[0].events.click();",
            "api.dom.globalSearch.events.submit({preventDefault:()=>{}});",
        ):
            results.append(self.run_application(self.sample_payload(), CANVAS + r"""
                api.bindEvents();
                api.dom.searchInput.value='root';
                api.dom.searchInput.focus();
                api.dom.searchInput.events.focus();
                api.runSearch();
                api.dom.atlasSettings.open=true;api.dom.mapHelp.open=true;
            """ + activation + r"""
                result={root:api.state.rootId,selected:api.state.selectedId,
                    searchClosed:api.dom.searchPanel.hidden,
                    expanded:api.dom.searchInput.attributes['aria-expanded'],
                    activeDescendant:api.dom.searchInput.attributes['aria-activedescendant']||null,
                    focusIsMap:document.activeElement===api.dom.graph3dCanvas,
                    detailsOpen:!api.dom.detailsPanel.hidden,
                    settingsClosed:!api.dom.atlasSettings.open,helpClosed:!api.dom.mapHelp.open};
            """))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], {
            "root": "fn:root", "selected": "fn:root", "searchClosed": True,
            "expanded": "false", "activeDescendant": None, "focusIsMap": True,
            "detailsOpen": True, "settingsClosed": True, "helpClosed": True,
        })

    def test_keyboard_choice_updates_active_descendant_then_selects_it(self):
        result = self.run_application(self.sample_payload(), CANVAS + r"""
            api.bindEvents();api.dom.searchInput.value='fn:';
            api.dom.searchInput.events.focus();api.runSearch();
            api.dom.searchInput.events.keydown({key:'ArrowDown',preventDefault:()=>{}});
            const active=document.getElementById(api.dom.searchInput.attributes['aria-activedescendant']);
            const choice=active.dataset.nodeId;
            api.dom.globalSearch.events.submit({preventDefault:()=>{}});
            result={choice,selected:api.state.selectedId,focusIsMap:document.activeElement===api.dom.graph3dCanvas};
        """)
        self.assertEqual(result, {"choice": "fn:root", "selected": "fn:root", "focusIsMap": True})

    def test_canvas_failure_moves_search_selection_to_visible_list(self):
        result = self.run_application(self.sample_payload(), r"""
            api.bindEvents();api.dom.searchInput.value='root';
            api.dom.searchInput.events.focus();api.runSearch();
            api.dom.globalSearch.events.submit({preventDefault:()=>{}});
            result={selected:api.state.selectedId,canvasAvailable:api.state.threeDAvailable,
                listOpen:api.dom.graphTextAlternative.open,
                focusIsList:document.activeElement===api.dom.graphTextAlternative,
                searchClosed:api.dom.searchPanel.hidden};
        """)
        self.assertEqual(result, {"selected": "fn:root", "canvasAvailable": False,
                                "listOpen": True, "focusIsList": True, "searchClosed": True})

    def test_reopening_search_restores_active_option_without_resetting_query(self):
        result = self.run_application(self.sample_payload(), CANVAS + r"""
            api.bindEvents();api.dom.searchInput.value='root';
            api.dom.searchInput.events.focus();api.runSearch();
            api.dom.globalSearch.events.submit({preventDefault:()=>{}});
            api.dom.searchInput.events.focus();
            result={query:api.dom.searchInput.value,searchOpen:!api.dom.searchPanel.hidden,
                expanded:api.dom.searchInput.attributes['aria-expanded'],
                active:document.getElementById(api.dom.searchInput.attributes['aria-activedescendant']).dataset.nodeId};
        """)
        self.assertEqual(result, {"query": "root", "searchOpen": True, "expanded": "true", "active": "fn:root"})

    def test_search_pagination_keeps_combobox_focus_and_selects_next_page(self):
        payload = self.sample_payload()
        payload["nodes"].extend({"id": f"match:{index}", "name": f"shared{index}",
                                 "type": "Function", "language": "Python"} for index in range(205))
        result = self.run_application(payload, CANVAS + r"""
            api.bindEvents();api.dom.searchInput.value='shared';
            api.dom.searchInput.events.focus();api.runSearch();
            const expected=api.state.searchMatches[80].id;
            api.dom.searchPagination.querySelectorAll('.more-button')[0].events.click();
            const active=document.getElementById(api.dom.searchInput.attributes['aria-activedescendant']);
            const afterMore={index:api.state.activeSearchIndex,choice:active.dataset.nodeId,
                inputFocused:document.activeElement===api.dom.searchInput,
                onlyOptions:api.dom.searchResults.children.every(child=>child.attributes.role==='option')};
            api.dom.globalSearch.events.submit({preventDefault:()=>{}});
            result={afterMore,expected,selected:api.state.selectedId};
        """)
        self.assertEqual(result["afterMore"]["index"], 80)
        self.assertEqual(result["afterMore"]["choice"], result["expected"])
        self.assertEqual(result["selected"], result["expected"])
        self.assertTrue(result["afterMore"]["inputFocused"])
        self.assertTrue(result["afterMore"]["onlyOptions"])

    def test_call_trace_replaces_start_guide_and_clearing_restores_it(self):
        result = self.run_application(self.sample_payload(), r"""
            api.setCallHover('fn:caller',null);
            const active={guideHidden:api.dom.startGuide.hidden,traceVisible:!api.dom.callTraceSummary.hidden};
            api.clearCallHover();
            result={active,cleared:{guideVisible:!api.dom.startGuide.hidden,traceHidden:api.dom.callTraceSummary.hidden}};
        """)
        self.assertEqual(result, {"active": {"guideHidden": True, "traceVisible": True},
                                  "cleared": {"guideVisible": True, "traceHidden": True}})

    def test_secondary_disclosures_only_keep_one_panel_open(self):
        result = self.run_application(self.sample_payload(), r"""
            api.bindEvents();api.dom.atlasSettings.open=true;api.dom.atlasSettings.events.toggle();
            api.dom.mapHelp.open=true;api.dom.mapHelp.events.toggle();
            const helpOnly=api.dom.mapHelp.open&&!api.dom.atlasSettings.open&&!api.dom.atlasBrowser.open;
            const raised=api.dom.atlasControls.dataset.disclosureOpen==='true';
            api.dom.atlasBrowser.open=true;api.dom.atlasBrowser.events.toggle();
            const browserOnly=api.dom.atlasBrowser.open&&!api.dom.atlasSettings.open&&!api.dom.mapHelp.open;
            api.dom.atlasBrowser.open=false;api.dom.atlasBrowser.events.toggle();
            result={helpOnly,browserOnly,raised,closed:api.dom.atlasControls.dataset.disclosureOpen==='false'};
        """)
        self.assertEqual(result, {"helpOnly": True, "browserOnly": True, "raised": True, "closed": True})

    def test_ctrl_and_command_shortcuts_use_search_and_do_not_take_over_editing(self):
        result = self.run_application(self.sample_payload(), r"""
            api.bindEvents();const focused=[];
            for(const key of ['ctrlKey','metaKey']){
                document.activeElement=null;
                document.events.keydown({key:'/',[key]:true,target:{tagName:'CANVAS'},preventDefault:()=>{}});
                focused.push(document.activeElement===api.dom.searchInput);
            }
            document.activeElement=null;
            document.events.keydown({key:'/',ctrlKey:true,target:{tagName:'INPUT'},preventDefault:()=>{}});
            result={focused,editingUntouched:document.activeElement===null};
        """)
        self.assertEqual(result, {"focused": [True, True], "editingUntouched": True})

    def test_panel_close_buttons_return_focus_to_disclosure_summaries(self):
        result = self.run_application(self.sample_payload(), r"""
            api.bindEvents();api.dom.mapHelp.open=true;api.dom.mapHelp.events.toggle();
            api.dom.mapHelpClose.events.click();
            const helpClosed=!api.dom.mapHelp.open&&document.activeElement===api.dom.mapHelpSummary;
            api.dom.atlasSettings.open=true;api.dom.atlasSettings.events.toggle();
            api.dom.atlasSettingsClose.events.click();
            const settingsClosed=!api.dom.atlasSettings.open&&document.activeElement===api.dom.atlasSettingsSummary;
            api.dom.atlasBrowser.open=true;api.dom.atlasBrowser.events.toggle();
            api.dom.atlasBrowserClose.events.click();
            result={helpClosed,settingsClosed,browserClosed:!api.dom.atlasBrowser.open&&document.activeElement===api.dom.atlasBrowserSummary,
                normalStack:api.dom.atlasControls.dataset.disclosureOpen==='false'};
        """)
        self.assertEqual(result, {"helpClosed": True, "settingsClosed": True, "browserClosed": True, "normalStack": True})

    def test_desktop_caption_budget_respects_control_region_and_collisions(self):
        payload = {"meta": {"snapshotId": "desktop-labels"}, "nodes": [], "edges": []}
        for module in range(20):
            module_id = f"pkg:{module}"
            payload["nodes"].append({"id": module_id, "name": f"package{module}",
                                     "type": "Module", "language": "Python", "path": f"pkg{module}/code.py"})
            for index in range(3):
                node_id = f"symbol:{module}:{index}"
                payload["nodes"].append({"id": node_id, "name": f"symbol{module}_{index}",
                                         "type": "Function", "language": "Python", "path": f"pkg{module}/code.py"})
                payload["edges"].append({"source": module_id, "target": node_id, "type": "DECLARES"})
        result = self.run_application(payload, CANVAS + r"""
            api.dom.graph3dCanvas.clientWidth=1280;api.dom.graph3dCanvas.clientHeight=720;
            api.dom.atlasControls.offsetTop=160;api.dom.atlasControls.offsetHeight=92;
            api.dom.detailsPanel.hidden=true;
            api.renderGraph3d(api.bounded3dGraph({nodes:api.nodes,edges:api.edges}));
            const captions=labels.filter(item=>item.font.includes('ui-monospace')||/^(400|600) /.test(item.font));
            const rectangles=captions.map(item=>({x:item.x-(item.text.length*6+12)/2,y:item.y-(item.font.includes('ui-monospace')?11:12),w:item.text.length*6+12,h:item.font.includes('ui-monospace')?29:18}));
            const overlap=rectangles.some((a,index)=>rectangles.slice(index+1).some(b=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y));
            result={nodes:api.state.threeDGraph.nodes.length,modules:captions.filter(item=>item.font.includes('ui-monospace')).length,
                captions:captions.length,overlap,belowControls:rectangles.every(box=>box.y>=264)};
        """)
        self.assertEqual(result["nodes"], 80)
        self.assertGreater(result["captions"], 0)
        self.assertLessEqual(result["modules"], 12)
        self.assertFalse(result["overlap"])
        self.assertTrue(result["belowControls"])

    def test_long_module_captions_keep_suffixes_no_overlap_and_all_nodes(self):
        payload = {"meta": {"snapshotId": "long-labels"}, "nodes": [], "edges": []}
        for index in range(12):
            name = f"skills.manage-code-ontology.scripts.distinct_module_{index}"
            payload["nodes"].append({"id": f"module:{index}", "name": name,
                                     "qualified_name": name, "type": "Module", "language": "Python",
                                     "path": f"skills/manage-code-ontology/scripts/distinct_module_{index}.py"})
        result = self.run_application(payload, CANVAS + r"""
            api.dom.graph3dCanvas.clientWidth=390;api.dom.graph3dCanvas.clientHeight=726;
            api.dom.detailsPanel.hidden=true;
            const graph=api.atlasGraph();api.renderGraph3d(graph);
            const captions=labels.filter(item=>item.font.includes('system-ui')&&item.text.includes('distinct_module'));
            const rectangles=captions.map(item=>({x:item.x-(item.text.length*6+12)/2,y:item.y-12,w:item.text.length*6+12,h:18}));
            const overlap=rectangles.some((a,index)=>rectangles.slice(index+1).some(b=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y));
            result={nodes:api.state.threeDGraph.nodes.length,total:api.nodes.length,
                captionCount:captions.length,overlap,
                suffixes:captions.every(item=>!/skills\.manage/.test(item.text)),
                originals:api.nodes.every(node=>node.name.startsWith('skills.manage-code-ontology.scripts.'))};
        """)
        self.assertEqual(result["nodes"], result["total"])
        self.assertGreater(result["captionCount"], 0)
        self.assertLessEqual(result["captionCount"], 6)
        self.assertFalse(result["overlap"])
        self.assertTrue(result["suffixes"])
        self.assertTrue(result["originals"])


if __name__ == "__main__":
    unittest.main()
