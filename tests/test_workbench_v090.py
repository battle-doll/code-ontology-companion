from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import shutil
import subprocess
import unittest

import test_workbench_quality_ui as ui


class WorkbenchV090Tests(unittest.TestCase):
    sample_payload = ui.WorkbenchQualityUiTests.sample_payload

    def run_application(self, payload, script):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable for shipped browser logic")
        harness = ui.JS_HARNESS.replace(
            "switchLens}; return;",
            "switchLens,setPresentation,setUiLanguage,UI_DICTIONARIES,UI_LOCALES,comparisonRows,renderNodeComparison,tracePaths,renderSnapshotTrust,scheduleSearch,searchIndex,CHANGE_PAGE_SIZE,t}; return;",
        )
        result = subprocess.run([node, "-e", harness, str(ui.JS)], input=json.dumps({"payload": payload, "script": script}),
                                text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_all_interface_catalogs_have_full_key_parity_and_translate_labels(self):
        result = self.run_application(self.sample_payload(), r"""
            const keys=Object.keys(api.UI_DICTIONARIES.ko).sort();
            const rows=api.UI_LOCALES.map(locale=>{
                api.setUiLanguage(locale,false);
                return {locale,keys:Object.keys(api.UI_DICTIONARIES[locale]).sort(),
                    label:api.t('스냅샷 신뢰 정보'),aria:api.t('심볼, 유형, 경로 검색'),
                    complete:keys.every(key=>typeof api.UI_DICTIONARIES[locale][key]==='string'&&api.UI_DICTIONARIES[locale][key].trim())};
            });
            result={keyCount:keys.length,parity:rows.every(row=>JSON.stringify(row.keys)===JSON.stringify(keys)),rows};
        """)
        self.assertGreater(result["keyCount"], 400)
        self.assertTrue(result["parity"])
        self.assertTrue(all(row["complete"] for row in result["rows"]))
        self.assertEqual([row["locale"] for row in result["rows"]], ["ko", "en", "ja", "zh-CN", "ru"])
        self.assertEqual(len({row["label"] for row in result["rows"]}), 5)
        self.assertEqual(len({row["aria"] for row in result["rows"]}), 5)

    def test_static_text_and_aria_are_in_embedded_catalog(self):
        rows = json.loads(ui.JS.read_text().split("const UI_TRANSLATION_ROWS = ", 1)[1].split(";\n", 1)[0])
        keys = {row[0] for row in rows}
        found = set()

        class StaticText(HTMLParser):
            def handle_data(self, data):
                if re.search("[가-힣]", data):
                    found.add(data.strip())

            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key in ("aria-label", "aria-roledescription", "placeholder", "title") and value and re.search("[가-힣]", value):
                        found.add(value.strip())

        StaticText().feed(ui.HTML.read_text())
        self.assertEqual(found - keys, set())

    def test_language_switch_preserves_exact_source_identifiers_and_private_query(self):
        payload = self.sample_payload()
        payload["nodes"][1]["name"] = "구조"
        result = self.run_application(payload, r"""
            api.state.selectedId='fn:root';api.state.rootId='fn:root';api.state.atlasOverview=false;
            api.state.presentation='list';api.dom.searchInput.value='Synthetic person name';
            api.setUiLanguage('ru');
            const texts=[];const walk=node=>{texts.push(node.textContent);node.children.forEach(walk);};walk(api.dom.detailsContent);
            result={name:api.nodeById.get('fn:root').name,header:texts.includes('구조'),
                query:api.dom.searchInput.value,url:api.selectionUrl().search,
                label:api.t('속성'),presentation:api.state.presentation};
        """)
        self.assertEqual(result["name"], "구조")
        self.assertTrue(result["header"])
        self.assertEqual(result["label"], "Свойство")
        self.assertEqual(result["query"], "Synthetic person name")
        self.assertNotIn("Synthetic", result["url"])
        self.assertEqual(result["presentation"], "list")

    def test_list_mode_keeps_selection_and_filters_and_stops_canvas(self):
        result = self.run_application(self.sample_payload(), r"""
            api.state.selectedId='fn:root';api.state.rootId='fn:root';api.state.atlasOverview=false;
            api.state.groupQuery='root';api.state.sourceScope='application';api.state.relationFilter='CALLS';
            api.setPresentation('list');
            result={selected:api.state.selectedId,root:api.state.rootId,query:api.state.groupQuery,
                scope:api.state.sourceScope,relation:api.state.relationFilter,
                graphHidden:api.dom.graphView.hidden,listOpen:api.dom.graphTextAlternative.open,
                focus:document.activeElement===api.dom.graphTextAlternative,
                selectedButton:api.dom.presentationList.attributes['aria-pressed']};
        """)
        self.assertEqual(result, {"selected": "fn:root", "root": "fn:root", "query": "root",
                                  "scope": "application", "relation": "CALLS", "graphHidden": True,
                                  "listOpen": True, "focus": True, "selectedButton": "true"})

    def test_modified_node_renders_saved_before_and_after_without_html_interpretation(self):
        result = self.run_application(self.sample_payload(), r"""
            const item={id:'fn:root',name:'new',path:'src/new.py',metadata:{line:9},
                previous:{id:'fn:root',name:'<img onerror=alert(1)>',path:'src/old.py',metadata:{line:2}}};
            api.renderNodeComparison(item);
            const strings=[];const tags=[];const walk=node=>{strings.push(node.textContent);tags.push(node.tagName);node.children.forEach(walk);};walk(api.dom.detailsContent);
            result={rows:api.comparisonRows(item),strings,tags,open:!api.dom.detailsPanel.hidden};
        """)
        self.assertEqual([row["key"] for row in result["rows"]], ["metadata.line", "name", "path"])
        self.assertEqual(result["rows"][0], {"key": "metadata.line", "before": 2, "after": 9})
        self.assertIn("<img onerror=alert(1)>", result["strings"])
        self.assertNotIn("IMG", result["tags"])
        self.assertTrue(result["open"])

    def test_legacy_modified_node_does_not_invent_prior_values(self):
        result = self.run_application(self.sample_payload(), r"""
            api.renderNodeComparison({id:'fn:root',name:'root'});
            result={rows:api.comparisonRows({id:'fn:root'}),tables:api.dom.detailsContent.querySelectorAll('table').length,
                note:api.dom.detailsContent.children[3].textContent};
        """)
        self.assertIsNone(result["rows"])
        self.assertEqual(result["tables"], 0)
        self.assertIn("이전 속성이", result["note"])

    def test_change_pages_are_bounded_and_navigable(self):
        payload = self.sample_payload()
        payload["changes"] = {"beforeSnapshotId": "before", "afterSnapshotId": "after", "nodesAdded": [
            {"id": f"new:{i}", "name": f"symbol-{i}", "type": "Function"} for i in range(93)]}
        result = self.run_application(payload, r"""
            api.renderChanges();
            const first=api.dom.changesView.querySelectorAll('.change-items')[0];
            const initial={length:first.children.length,first:first.children[0].children[0].textContent};
            api.dom.changesView.querySelectorAll('.change-pagination')[0].children[2].events.click();
            const second=api.dom.changesView.querySelectorAll('.change-items')[0];
            const page2={length:second.children.length,first:second.children[0].children[0].textContent};
            api.dom.changesView.querySelectorAll('.change-pagination')[0].children[2].events.click();
            const third=api.dom.changesView.querySelectorAll('.change-items')[0];
            result={initial,page2,page3:{length:third.children.length,first:third.children[0].children[0].textContent,
                disabled:api.dom.changesView.querySelectorAll('.change-pagination')[0].children[2].disabled}};
        """)
        self.assertEqual(result, {"initial": {"length": 40, "first": "symbol-0"},
                                  "page2": {"length": 40, "first": "symbol-40"},
                                  "page3": {"length": 13, "first": "symbol-80", "disabled": True}})

    def test_search_debounce_cancels_stale_query_and_keeps_rank_order(self):
        result = self.run_application(self.sample_payload(), r"""
            const pending=[];const cleared=[];window.setTimeout=(callback,delay)=>{pending.push({callback,delay});return pending.length;};
            window.clearTimeout=id=>cleared.push(id);
            api.dom.searchInput.value='root';api.scheduleSearch();
            api.dom.searchInput.value='caller';api.scheduleSearch();
            pending[0].callback();const before=api.state.searchMatches.length;
            pending[1].callback();
            result={before,matches:api.state.searchMatches.map(node=>node.id),cleared,delay:pending[1].delay};
        """)
        self.assertEqual(result["before"], 0)
        self.assertEqual(result["matches"], ["fn:caller"])
        self.assertIn(1, result["cleared"])
        self.assertEqual(result["delay"], 120)

    def test_paths_only_follow_actual_visible_edges_in_original_direction(self):
        payload = self.sample_payload()
        payload["nodes"].append({"id": "fn:first", "name": "first", "type": "Function", "language": "Python", "path": "src/a.py"})
        payload["edges"].append({"source": "fn:first", "target": "fn:caller", "type": "CALLS", "evidence": []})
        result = self.run_application(payload, r"""
            api.state.activeLens='impact';api.state.rootId='fn:root';api.state.direction='incoming';api.state.depth=3;
            const graph={edges:api.edges.filter(edge=>edge.type==='CALLS'&&edge.source!=='concept:x')};
            result=api.tracePaths(graph).map(path=>path.map(edge=>[edge.source,edge.target]));
        """)
        self.assertIn([["fn:first", "fn:caller"], ["fn:caller", "fn:root"]], result)
        self.assertEqual(len(result), 2)

    def test_generated_at_does_not_claim_freshness_without_a_bound_check(self):
        payload = self.sample_payload()
        payload["meta"].update({"generatedAt": "2026-10-11T00:00:00Z", "freshness": {
            "snapshotId": "different-snapshot", "checkedAt": "2026-10-11T00:00:01Z", "status": "current"}})
        result = self.run_application(payload, r"""
            api.renderSnapshotTrust();const parts=[];const walk=node=>{parts.push(node.textContent);node.children.forEach(walk);};walk(api.dom.snapshotTrust);result=parts.join(' ');
        """)
        self.assertIn("재검사하지 않았습니다", result)
        self.assertNotIn("current", result)


if __name__ == "__main__":
    unittest.main()
