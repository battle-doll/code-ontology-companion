"""Synthetic offline export, privacy, access and exact-navigation regressions."""
from __future__ import annotations

from contextlib import contextmanager
from html.parser import HTMLParser
import json
import importlib
import os
from pathlib import Path
from windows_fixture import protect_private_path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
from urllib.parse import urlsplit

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline_html as view
import pipeline_acl as acl
import privacy_guard as guard


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids, self.links, self.tags, self.lang, self.records, self.script_data = set(), [], [], None, [], ""
        self.map_links = {}
        self.in_data = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append(tag)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if "data-search-record" in attributes and "id" in attributes:
            self.records.append(attributes["id"])
        if tag == "html":
            self.lang = attributes.get("lang")
        self.links.extend(attributes[key] for key in ("href", "src") if key in attributes)
        if "data-map-record" in attributes:
            self.map_links[attributes["data-map-record"]] = attributes["href"]
        if tag == "script" and attributes.get("id") == "ontology-data":
            self.in_data = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, text):
        if self.in_data:
            self.script_data += text


def symbol(index):
    return {"id": f"symbol:{index:04d}", "kind": "symbol", "name": f"operation_{index}", "path": "src/flow.py",
            "module": "src", "language": "Python", "symbolKind": "Function", "span": {"lineStart": index + 1, "lineEnd": index + 2},
            "basis": "direct_syntax", "status": "observed"}


def policy_record():
    return {"id": "policy:choice", "kind": "policy_rule", "name": "choose_value", "path": "src/policy.py", "module": "src",
            "status": "extraction_verified", "sourceAssertionIds": ["assertion:choice"],
            "parameters": [{"name": "enabled", "type": "bool", "finiteValues": [True, False]}],
            "program": {"op": "if", "condition": {"op": "input", "type": "bool", "name": "enabled"},
                        "then": {"op": "return", "value": {"op": "literal", "type": "decimal", "value": "1.25"}},
                        "else": {"op": "return", "value": {"op": "literal", "type": "decimal", "value": "0"}}},
            "authority": {"kind": "implemented-rule", "rulesetAuthority": "python-static-v1"}, "complete": True,
            "validity": {"from": None, "to": None, "status": "undeclared"},
            "combinations": {"stackability": "unknown", "precedence": "source-control-flow", "caps": "expression-only"}}


class PipelineHtmlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.output = self.base / "html"
        self.profile_file = self.base / "profile.json"
        profile = guard.build_profile(["Synthetic Private Person"], ["synthetic-person@privacy-fixture.test"], key=b"p" * 32)
        self.profile_file.write_text(json.dumps(profile), encoding="utf-8")
        protect_private_path(self.profile_file)
        patcher = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(self.profile_file), acl.PRINCIPAL_ENV: "local-owner"})
        patcher.start()
        self.addCleanup(patcher.stop)
        acl.initialize_access(self.workspace)
        self.records = [symbol(index) for index in range(103)]
        self.records += [{"id": "assertion:choice", "kind": "assertion", "name": "calls", "module": "src", "path": "src/flow.py",
                          "span": {"lineStart": 5, "lineEnd": 6}, "subject": "symbol:0000", "predicate": "CALLS", "object": "symbol:0001",
                          "basis": "direct_syntax", "status": "observed"}, policy_record()]
        self.reader_open_count, self.requested_page_sizes, self.exit_error, self.on_exit = 0, [], False, None
        self.final_stable_checks,self.stable_error=0,False
        fake = types.ModuleType("pipeline_store")
        fake.open_reader = self.open_reader
        # ACL updates must keep the real private-file write boundary while
        # these tests substitute only the snapshot reader.
        fake._atomic = importlib.import_module("pipeline_store")._atomic
        self.store_patch = mock.patch.dict(sys.modules, {"pipeline_store": fake})
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

    @contextmanager
    def open_reader(self, workspace, snapshot_id=None):
        self.reader_open_count += 1
        case = self
        class Reader:
            metadata = {"snapshotId": "synthetic-snapshot-1", "analysisSpecId": "synthetic-spec-1", "recordCount": len(case.records),
                        "coverage": {"complete": False, "unsupportedFiles": 2}, "createdAt": "2030-01-01T00:00:00Z", "sourceLastVerifiedAt": None}
            def _stable(self):
                case.final_stable_checks+=1
                if case.stable_error:raise ValueError("synthetic_late_snapshot_changed")
            def iter_records(self, *, page_size):
                case.requested_page_sizes.append(page_size)
                yield from case.records
        yield Reader()
        if self.on_exit:
            self.on_exit()
        if self.exit_error:
            raise ValueError("synthetic_snapshot_changed")

    def render(self, maps=False):
        return view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.output, include_maps=maps)

    def test_all_records_reachable_exactly_once_per_language_with_bounded_pages(self):
        result = self.render()
        expected = {view._anchor(record["id"]) for record in self.records}
        self.assertEqual(result["recordCount"], len(self.records))
        self.assertFalse(result["sourceRechecked"])
        self.assertEqual(result["browserVerification"], "unverified")
        self.assertEqual(self.reader_open_count, 1)
        self.assertEqual(self.requested_page_sizes, [50])
        for locale in view.LANGUAGES:
            reached = []
            for path in (self.output / locale).glob("*.html"):
                page = Page(path.read_text(encoding="utf-8"))
                self.assertEqual(page.lang, locale)
                self.assertLessEqual(len(page.records), 50)
                reached.extend(page.records)
            self.assertEqual(set(reached), expected)
            self.assertEqual(len(reached), len(expected))
            self.assertIn("103", (self.output / locale / "symbol-000003.html").read_text())

    def test_every_internal_link_resolves_and_no_source_path_becomes_a_link(self):
        self.render(maps=True)
        for path in self.output.rglob("*.html"):
            page = Page(path.read_text(encoding="utf-8"))
            for link in page.links:
                parsed = urlsplit(link)
                self.assertFalse(parsed.scheme, link)
                self.assertFalse(parsed.netloc, link)
                target = (path.parent / parsed.path).resolve() if parsed.path else path
                self.assertTrue(target.is_relative_to(self.output), link)
                self.assertTrue(target.is_file(), link)
                self.assertNotIn("src/flow.py", link)
                if parsed.fragment:
                    self.assertIn(parsed.fragment, Page(target.read_text()).ids, (path.name, link))

    def test_five_languages_have_real_translation_parity_and_preserve_policy_values(self):
        self.records = [policy_record()]
        self.render()
        keys = set(view.TRANSLATIONS["ko"])
        self.assertGreater(len(keys), 40)
        for locale in view.LANGUAGES:
            self.assertEqual(set(view.TRANSLATIONS[locale]), keys)
            self.assertTrue(all(view.TRANSLATIONS[locale].values()))
            text = (self.output / locale / "policy_rule-000001.html").read_text()
            self.assertIn("policy:choice", text)
            self.assertIn("1.25", text)
            self.assertIn("UNKNOWN", text)
            self.assertIn(view.TRANSLATIONS[locale]["export_access"], text)
        for key in ("catalog", "decision", "source", "scope", "export_access"):
            self.assertEqual(len({view.TRANSLATIONS[locale][key] for locale in view.LANGUAGES}), 5)

    def test_policy_decision_rows_preserve_true_false_and_exact_evidence_location(self):
        self.render()
        text = (self.output / "en/policy_rule-000001.html").read_text()
        self.assertIn("NOT (enabled)", text)
        self.assertIn("src/flow.py:5–6", text)
        self.assertIn('assertion-000001.html#' + view._anchor("assertion:choice"), text)
        self.assertIn("implemented-rule", text)
        self.assertIn("maximum-benefit calculation", text)

    def test_unknown_evidence_has_no_broken_link(self):
        self.records = [policy_record()]
        self.render()
        page = (self.output / "en/policy_rule-000001.html").read_text()
        self.assertIn("Evidence record is absent", page)
        self.assertNotIn('href="assertion-', page)

    def test_empty_snapshot_and_more_than_one_module_catalog_page_remain_reachable(self):
        self.records = []
        result = self.render()
        self.assertEqual(result["recordCount"], 0)
        self.assertIn("No records in this scope", (self.output / "en/modules-000001.html").read_text())
        self.output = self.base / "many-modules"
        self.records = [{**symbol(index), "module": f"module-{index:04d}"} for index in range(57)]
        result = self.render()
        self.assertEqual(result["moduleCount"], 57)
        page = (self.output / "en/modules-000002.html").read_text()
        self.assertIn('rel="prev"', page)
        self.assertNotIn('rel="next"', page)
        self.assertIn("module-0056", page)

    def test_revocation_during_export_prevents_promotion(self):
        self.records = [symbol(0)]
        self.on_exit = lambda: acl.update_access(self.workspace, "local-owner", sorted(acl.ACTIONS - {"export_html"}), ["*"])
        with self.assertRaises(acl.AccessDenied):
            self.render()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_native_profile_replacement_after_final_file_walk_blocks_direct_html(self):
        import pipeline_access
        self.records=[symbol(0)];replacement=guard.build_profile([self.records[0]['name']],[],key=b'w'*32)
        with self.assertRaises(guard.PrivacyError):guard.ensure_public_safe(self.records[0],profile=replacement,require_profile=True)
        original=pipeline_access.check_business_export;changed=[]
        def after_walk(*args,**kwargs):
            result=original(*args,**kwargs);changed.append(True)
            sys.modules['pipeline_store']._atomic(self.profile_file,replacement);return result
        with mock.patch.object(pipeline_access,'check_business_export',new=after_walk),mock.patch.object(view.os,'rename') as promote:
            with self.assertRaisesRegex(view.PipelineHtmlError,'html_privacy_profile_changed'):self.render()
        self.assertEqual(changed,[True]);self.assertEqual(self.final_stable_checks,1);promote.assert_not_called();self.assertFalse(self.output.exists())
    def test_source_binding_is_rechecked_after_final_file_walk(self):
        import pipeline_access
        original=pipeline_access.check_business_export;changed=[]
        def after_walk(*args,**kwargs):
            result=original(*args,**kwargs);changed.append(True);self.stable_error=True;return result
        with mock.patch.object(pipeline_access,'check_business_export',new=after_walk),mock.patch.object(view.os,'rename') as promote:
            with self.assertRaisesRegex(ValueError,'synthetic_late_snapshot_changed'):self.render()
        self.assertEqual(changed,[True]);self.assertEqual(self.final_stable_checks,1);promote.assert_not_called();self.assertFalse(self.output.exists())

    def test_profile_change_during_export_prevents_promotion(self):
        self.records = [symbol(0)]
        def change_profile():
            self.profile_file.write_text(json.dumps(guard.build_profile(["Other Synthetic Identity"], [], key=b"p" * 32)))
        self.on_exit = change_profile
        with self.assertRaisesRegex(view.PipelineHtmlError, "privacy_profile_changed"):
            self.render()
        self.assertFalse(self.output.exists())

    def test_cancel_after_first_written_asset_rolls_back_and_stops_further_writes(self):
        self.records = [symbol(0)]
        cancelled = threading.Event()
        original = view._write
        written = []
        def write_then_cancel(path, text, profile):
            original(path, text, profile)
            written.append(path.name)
            cancelled.set()
        with mock.patch.object(view, "_write", side_effect=write_then_cancel):
            with self.assertRaisesRegex(view.PipelineHtmlError, "export_cancelled"):
                view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.output, cancel=cancelled)
        self.assertEqual(written, ["pipeline.css"])
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_total_output_budget_is_enforced_without_truncated_success(self):
        self.records = [symbol(0)]
        with self.assertRaisesRegex(view.PipelineHtmlError, "output_budget_exceeded"):
            view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.output, max_output_bytes=30000, include_maps=False)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_private_handle_rejection_happens_before_payload_write(self):
        self.records = [symbol(0)]
        observed_sizes = []
        original = view._private_handle
        def verify(fd):
            observed_sizes.append(os.fstat(fd).st_size)
            if len(observed_sizes) == 2:
                raise guard.PrivacyError("profile_permissions")
            return original(fd)
        with mock.patch.object(view, "_private_handle", side_effect=verify):
            with self.assertRaises(guard.PrivacyError):
                self.render()
        self.assertEqual(observed_sizes, [0, 0])
        self.assertFalse(self.output.exists())

    @unittest.skipIf(os.name == "nt", "POSIX permission mutation; Windows uses open-handle DACL verification")
    def test_permission_change_before_promotion_rolls_back(self):
        self.records = [symbol(0)]
        def weaken_staged_file():
            staged_file = next(self.base.glob(".pipeline-html-*/artifact/assets/pipeline.css"))
            staged_file.chmod(0o644)
        self.on_exit = weaken_staged_file
        with self.assertRaises(guard.PrivacyError):
            self.render()
        self.assertFalse(self.output.exists())

    def test_html_injection_is_text_only_and_csp_blocks_network(self):
        self.records = [symbol(0)]
        self.records[0]["name"] = '<img src="https://invalid.test/leak" onerror="alert(1)"></script>'
        self.render()
        text = (self.output / "en/symbol-000001.html").read_text()
        self.assertIn("&lt;img", text)
        self.assertNotIn("img", Page(text).tags)
        self.assertIn("connect-src 'none'", text)
        self.assertIn("form-action 'none'", text)
        self.assertNotIn("unsafe-inline", text)

    def test_snapshot_close_failure_leaves_no_complete_or_partial_artifact(self):
        self.exit_error = True
        with self.assertRaisesRegex(ValueError, "synthetic_snapshot_changed"):
            self.render()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_snapshot_exits_before_promotion_and_acl_update_cannot_cross_final_boundary(self):
        self.records = [symbol(0)]
        state = {"reader_closed": False, "competing_update_rejected": False}
        self.on_exit = lambda: state.update(reader_closed=True)
        original = os.rename
        def promote(source, destination):
            self.assertTrue(state["reader_closed"])
            with self.assertRaisesRegex(acl.companion.CompanionError, "Another snapshot writer"):
                acl.update_access(self.workspace, "local-owner", sorted(acl.ACTIONS - {"export_html"}), ["*"])
            state["competing_update_rejected"] = True
            return original(source, destination)
        with mock.patch.object(view.os, "rename", side_effect=promote):
            self.render()
        self.assertTrue(state["competing_update_rejected"])
        self.assertTrue((self.output / "en/index.html").is_file())
        acl.authorize(self.workspace, "export_html", "synthetic-snapshot-1")

    def test_personal_identity_and_email_fail_closed_before_artifact_promotion(self):
        personal_email = "@".join(("synthetic-person-fixture", ".".join(("mail-service-fixture", "org"))))
        home_path = "/".join(("", "Users", "synthetic-account-fixture", "source.py"))
        for value in ("Synthetic Private Person", "synthetic-person@privacy-fixture.test", personal_email, home_path):
            self.records = [symbol(0)]
            self.records[0]["name"] = value
            with self.subTest(kind=value.split("@")[0][:2]), self.assertRaises(guard.PrivacyError):
                self.render()
            self.assertFalse(self.output.exists())
            self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_private_profile_is_required(self):
        self.profile_file.unlink()
        with self.assertRaises((guard.PrivacyError, acl.AccessDenied)):
            self.render()
        self.assertEqual(self.reader_open_count, 0)

    def test_missing_or_insufficient_acl_denies_before_snapshot_read(self):
        (self.workspace / "access.json").unlink()
        with self.assertRaises(acl.AccessDenied):
            self.render()
        self.assertEqual(self.reader_open_count, 0)
        acl.initialize_access(self.workspace)
        for omitted in ("export_html", "read_structure", "read_policy", "read_evidence"):
            actions = sorted(acl.ACTIONS - {omitted})
            # Operator setup fixture, not a role supplied by exported data.
            acl.update_access(self.workspace, "local-owner", actions, ["*"])
            with self.subTest(omitted=omitted), self.assertRaises(acl.AccessDenied):
                self.render()
            self.assertEqual(self.reader_open_count, 0)

    def test_existing_output_and_source_workspace_are_not_modified(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(view.PipelineHtmlError, "destination_exists"):
            self.render()
        self.assertEqual(sentinel.read_text(), "keep")
        with self.assertRaisesRegex(view.PipelineHtmlError, "inside_workspace"):
            view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.workspace / "html")

    def test_record_path_traversal_duplicate_id_and_record_budget_fail_closed(self):
        for records, category in (([{**symbol(0), "path": "../secret.py"}], "source_path_not_relative"),
                                  ([symbol(0), symbol(0)], "duplicate_record_id"),
                                  ([{**symbol(0), "name": "x" * (view.MAX_RECORD_BYTES + 1)}], "record_budget_exceeded")):
            self.records = records
            with self.subTest(category=category), self.assertRaisesRegex(view.PipelineHtmlError, category):
                self.render()
            self.assertFalse(self.output.exists())

    def test_maps_reuse_existing_workbench_only_bounded_nodes_and_real_assertions(self):
        self.render(maps=True)
        maps = list((self.output / "en").glob("map-*.html"))
        self.assertGreater(len(maps), 0)
        for path in maps:
            page = Page(path.read_text())
            payload = json.loads(page.script_data)
            self.assertLessEqual(len(payload["nodes"]), 60)
            self.assertLessEqual(len(payload["edges"]), 160)
            self.assertTrue(all(node["id"].startswith("symbol:") for node in payload["nodes"]))
            for edge in payload["edges"]:
                self.assertEqual((edge["source"], edge["target"], edge["type"]), ("symbol:0000", "symbol:0001", "CALLS"))
                self.assertEqual(edge["evidence"][0]["path"], "src/flow.py")
                self.assertEqual(edge["evidence"][0]["line_start"], 5)
                self.assertEqual(edge["evidence"][0]["basis"], "direct_syntax")
            self.assertIn('class="brand-mark" href="', path.read_text())
            self.assertIn('href="../assets/workbench.css"', path.read_text())
            self.assertIn('src="../assets/workbench.js"', path.read_text())
        self.assertEqual((self.output / "assets/workbench.js").read_bytes(), (view.ASSETS / "workbench.js").read_bytes())

    def test_default_entrypoint_is_connected_3d_and_catalog_is_native_in_every_language(self):
        self.records[-2]["subject"] = "symbol:0100"
        self.records[-2]["object"] = "symbol:0102"
        result = view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.output)
        self.assertEqual(Path(result["entrypoint"]), self.output / "ko/index.html")
        self.assertEqual(result["mappedAssertions"], 1)
        self.assertGreater(result["mapPagesPerLanguage"], 1)
        for locale in view.LANGUAGES:
            source = (self.output / locale / "index.html").read_text()
            page = Page(source)
            payload = json.loads(page.script_data)
            self.assertIn("graph-3d-canvas", page.ids)
            self.assertIn("motion-toggle", page.ids)
            self.assertEqual({node["id"] for node in payload["nodes"]}, {"symbol:0100", "symbol:0102"})
            self.assertEqual(len(payload["edges"]), 1)
            self.assertEqual(payload["meta"]["uiLanguage"], locale)
            self.assertIn("catalog.html", page.links)
            self.assertIn("map-000002.html", page.links)
            self.assertIn(view.TRANSLATIONS[locale]["all_records"], source)
            self.assertIn('href="index.html"', (self.output / locale / "catalog.html").read_text())
            self.assertFalse(Page((self.output / locale / "catalog.html").read_text()).script_data)
        self.assertIn('http-equiv="refresh" content="0;url=ko/index.html"', (self.output / "index.html").read_text())

    def test_global_maps_preserve_every_valid_assertion_and_bound_nodes_and_duplicate_evidence(self):
        self.records = [symbol(index) for index in range(144)]
        assertions = [{"id": f"assertion:pair-{index:04d}", "kind": "assertion", "module": "src", "path": "src/flow.py",
                       "span": {"lineStart": index + 1}, "subject": f"symbol:{index * 2:04d}", "object": f"symbol:{index * 2 + 1:04d}",
                       "predicate": "CALLS", "basis": "declared"} for index in range(70)]
        assertions += [{**assertions[0], "id": f"assertion:duplicate-{index:04d}", "span": {"lineStart": 200 + index}} for index in range(181)]
        self.records += assertions + [
            {**assertions[0], "id": "assertion:missing-target", "object": "absent:target"},
            {**assertions[0], "id": "assertion:non-symbol", "object": "framework:one"},
            {"id": "framework:one", "kind": "framework", "name": "ExampleFramework", "module": "src"},
            {"id": "assertion:evidence-only", "kind": "assertion", "module": "src"},
        ]
        result = self.render(maps=True)
        self.assertEqual(result["mappedAssertions"], len(assertions))
        self.assertEqual(result["unmappedAssertions"], 3)
        payloads = {}
        seen_assertions, seen_symbols = [], set()
        for path in (self.output / "en").glob("*.html"):
            page = Page(path.read_text())
            if not page.script_data:
                continue
            payload = json.loads(page.script_data)
            evidence = [item for edge in payload["edges"] for item in edge["evidence"]]
            self.assertLessEqual(len(payload["nodes"]), 60)
            self.assertLessEqual(len(payload["edges"]), 160)
            self.assertLessEqual(len(evidence), 160)
            self.assertEqual(len({(edge["source"], edge["type"], edge["target"]) for edge in payload["edges"]}), len(payload["edges"]))
            for item in evidence:
                self.assertEqual(item["evidence_id"], item["assertion_id"])
                self.assertEqual(item["basis"], "declared")
            node_ids = {node["id"] for node in payload["nodes"]}
            assertion_ids = {item["assertion_id"] for item in evidence}
            payloads[path.name] = node_ids | assertion_ids
            seen_assertions.extend(item["assertion_id"] for item in evidence)
            seen_symbols.update(node_ids)
        self.assertEqual(len(seen_assertions), len(assertions))
        self.assertEqual(set(seen_assertions), {record["id"] for record in assertions})
        self.assertEqual(seen_symbols, {f"symbol:{index:04d}" for index in range(144)})
        linked = set()
        for path in (self.output / "en").glob("*.html"):
            for record_id, target in Page(path.read_text()).map_links.items():
                self.assertIn(record_id, payloads[target])
                linked.add(record_id)
        self.assertEqual(linked, set(seen_assertions) | seen_symbols)

    def test_empty_policy_only_and_maps_disabled_keep_catalog_access(self):
        for index, records in enumerate(([], [policy_record()])):
            self.output = self.base / f"empty-map-{index}"
            self.records = records
            self.render(maps=True)
            entry = Page((self.output / "en/index.html").read_text())
            graph = json.loads(entry.script_data)
            self.assertEqual((graph["nodes"], graph["edges"]), ([], []))
            self.assertIn("catalog.html", entry.links)
            self.assertTrue((self.output / "en/catalog.html").is_file())
        self.output = self.base / "text-only"
        result = self.render(maps=False)
        self.assertFalse(Page(Path(result["entrypoint"]).read_text()).script_data)
        self.assertEqual(result["mapPagesPerLanguage"], 0)
        self.assertFalse((self.output / "assets/workbench.js").exists())
        self.assertIn("catalog.html", Page(Path(result["entrypoint"]).read_text()).links)

    def test_default_index_runs_shipped_workbench_startup_zoom_and_motion_controls(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; browser remains unverified")
        import test_workbench_quality_ui as ui
        self.records[0]["path"] = "alpha/root.py"
        self.records[1]["path"] = "beta/target.py"
        view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.output)
        payload = json.loads(Page((self.output / "en/index.html").read_text()).script_data)
        # Keep the real startup code after exposing handles for observation.
        # Canvas/DOM are deliberately minimal, not browser layout emulation.
        setup = r'''
const frames=new Map();let frameId=0;
window.requestAnimationFrame=callback=>{frames.set(++frameId,callback);return frameId;};
window.cancelAnimationFrame=id=>frames.delete(id);
const reduced={matches:false,addEventListener:(_event,callback)=>{reduced.change=callback;}};
window.matchMedia=query=>query.includes('prefers-reduced-motion')?reduced:{matches:false};
document.documentElement={lang:'en'};
const gradient={addColorStop:()=>{}};
const canvas=new Proxy({},{get:(target,key)=>key==='measureText'?value=>({width:value.length*6}):key==='createRadialGradient'?()=>gradient:target[key]||(()=>{}),set:(target,key,value)=>{target[key]=value;return true;}});
Element.prototype.getContext=()=>canvas;
Element.prototype.getBoundingClientRect=()=>({left:0,top:0,width:1200,height:800});
function advance(time){const entries=[...frames];frames.clear();entries.forEach(([_id,callback])=>callback(time));}
Object.assign(context,{frames,reduced,advance});
'''
        harness = ui.JS_HARNESS.replace("}; return;';", "};';")
        self.assertNotEqual(harness, ui.JS_HARNESS)
        harness = harness.replace("const source=fs.readFileSync", setup + "\nconst source=fs.readFileSync")
        script = r'''
advance(0);advance(50);
const initial={nodes:api.state.threeDGraph.nodes.length,edges:api.state.threeDGraph.edges.length,
  projected:api.state.threeDProjectedNodes.length,canvas:api.state.threeDAvailable,motion:api.state.motionEnabled};
const zoom=api.state.camera.zoom;api.dom.zoomIn.events.click();const zoomed=api.state.camera.zoom>zoom;
const yaw=api.state.camera.yaw;api.dom.motionToggle.events.click();advance(100);advance(200);
const rotating=api.state.motionEnabled&&api.state.camera.yaw!==yaw;
api.dom.motionToggle.events.click();advance(300);const stopped=!api.state.motionEnabled&&frames.size===0;
api.dom.motionToggle.events.click();document.visibilityState='hidden';document.events.visibilitychange();
const hiddenStopped=frames.size===0;
document.visibilityState='visible';document.events.visibilitychange();reduced.matches=true;reduced.change({matches:true});advance(400);
result={initial,zoomed,rotating,stopped,hiddenStopped,reducedStopped:!api.state.motionEnabled&&frames.size===0};
'''
        run = subprocess.run([node, "-e", harness, str(view.ASSETS / "workbench.js")], input=json.dumps({"payload": payload, "script": script}), text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertGreater(result["initial"]["nodes"], 0)
        self.assertGreater(result["initial"]["edges"], 0)
        self.assertGreater(result["initial"]["projected"], 0)
        self.assertTrue(result["initial"]["canvas"])
        self.assertFalse(result["initial"]["motion"])
        self.assertTrue(all(result[key] for key in ("zoomed", "rotating", "stopped", "hiddenStopped", "reducedStopped")))

    def test_map_navigation_translates_and_links_the_selected_locale_without_network_or_query(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; browser remains unverified")
        source = (view.ASSETS / "pipeline-map.js").read_text()
        for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "innerHTML", "location", "eval("):
            self.assertNotIn(forbidden, source)
        script = r'''
const fs=require('fs'),vm=require('vm');
const translations=JSON.parse(fs.readFileSync(0,'utf8'));
const events={},language={value:'en',addEventListener:(name,fn)=>events[name]=fn};
const text={dataset:{pipelineCopy:'all_records'},textContent:''},label={dataset:{pipelineLabel:'next'},attributes:{},setAttribute(key,value){this.attributes[key]=value;}};
const links=['catalog.html','map-000002.html','assertion-000001.html#r-'+'a'.repeat(64),'../unsafe.html'].map(target=>({dataset:{pipelineTarget:target},attributes:{},setAttribute(key,value){this.attributes[key]=value;}}));
const details={open:true},summary={focus:()=>summary.focused=true},close={addEventListener:(_name,fn)=>close.click=fn};
const elements={'pipeline-map-data':{textContent:JSON.stringify(translations)},'ui-language':language,'pipeline-map-details':details,'pipeline-map-summary':summary,'pipeline-map-close':close};
const document={getElementById:id=>elements[id],querySelectorAll:selector=>({'[data-pipeline-copy]':[text],'[data-pipeline-label]':[label],'[data-pipeline-target]':links}[selector]),addEventListener:(name,fn)=>events[name]=fn};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{document});
const results=[];for(const locale of ['ko','en','ja','zh-CN','ru']){language.value=locale;events.change();results.push({locale,text:text.textContent,label:label.attributes['aria-label'],targets:links.map(link=>link.attributes.href||null)});}
events.keydown({key:'Escape'});process.stdout.write(JSON.stringify({results,closed:!details.open,focused:summary.focused}));
'''
        translations = {locale: {"all_records": view.TRANSLATIONS[locale]["all_records"], "next": view.TRANSLATIONS[locale]["next"]} for locale in view.LANGUAGES}
        run = subprocess.run([node, "-e", script, str(view.ASSETS / "pipeline-map.js")], input=json.dumps(translations), text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        for row in result["results"]:
            self.assertEqual(row["text"], translations[row["locale"]]["all_records"])
            self.assertEqual(row["label"], translations[row["locale"]]["next"])
            self.assertTrue(all(target.startswith("../" + row["locale"] + "/") for target in row["targets"][:3]))
            self.assertIsNone(row["targets"][3])
        self.assertTrue(result["closed"] and result["focused"])

    @unittest.skipIf(os.name == "nt", "POSIX mode assertion; native Windows DACL is a separate gate")
    def test_private_permissions_and_temporary_index_not_exported(self):
        self.render()
        for path in (self.output, *self.output.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        self.assertFalse(list(self.output.rglob("*.sqlite")))
        self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_pretty_printer_uses_typed_semantics_without_evaluation(self):
        expression = {"op": "compare", "operator": "ge", "left": {"op": "input", "name": "amount"},
                      "right": {"op": "literal", "type": "decimal", "value": "1.25"}}
        self.assertEqual(view.pretty_expression(expression), '(amount ≥ "1.25" : decimal)')
        self.assertEqual(view.pretty_expression({"op": "neg", "arg": expression}), '− ((amount ≥ "1.25" : decimal))')
        self.assertIn('"op": "future_operator"', view.pretty_expression({"op": "future_operator", "value": "UNKNOWN"}))

    def test_real_sealed_sqlite_snapshot_exports_after_source_is_removed(self):
        self.store_patch.stop()
        store = importlib.import_module("pipeline_store")
        repository = self.base / "source"
        repository.mkdir()
        (repository / "order.py").write_text("def order_value(enabled: bool) -> int:\n    if enabled:\n        return 3\n    return 1\n", encoding="utf-8")
        workspace = self.base / "sealed-workspace"
        built = store.initialize(repository, workspace, partition_count=2)
        acl.initialize_access(workspace)
        with store.open_reader(workspace, built["snapshotId"]) as reader:
            expected = {record["id"] for record in reader.iter_records()}
        shutil.rmtree(repository)
        result = view.render_pipeline(workspace, built["snapshotId"], self.output)
        self.assertFalse(repository.exists())
        self.assertEqual(result["recordCount"], len(expected))
        self.assertEqual(result["counts"]["policy_rule"], 1)
        reached = set()
        for path in (self.output / "en").glob("*.html"):
            reached.update(Page(path.read_text()).records)
        self.assertEqual(reached, {view._anchor(record_id) for record_id in expected})
        policy = (self.output / "en/policy_rule-000001.html").read_text()
        self.assertIn("order.py:", policy)
        self.assertIn("extraction_verified", policy)
        self.assertIn("UNKNOWN", policy)

    def test_shared_raw_data_is_lossless_safe_and_identical_across_five_locales(self):
        self.output = self.base / "오프라인 공유 기록"
        hostile = "</script><script>unexpected()</script>\u2028\u2029 & < >"
        self.records = [{**symbol(i), "rawOnlyValue": hostile, "__proto__": {"ordinary": True}} for i in range(53)]
        result = self.render()
        decoded = []
        for path in sorted((self.output / "data").glob("*.json")):
            payload = json.loads(path.read_text())
            self.assertEqual(payload["snapshotId"], "synthetic-snapshot-1")
            self.assertLessEqual(len(payload["records"]), 50)
            decoded.extend(payload["records"])
            script = path.with_suffix(".js").read_text()
            node = shutil.which("node")
            if not node:
                self.skipTest("Node unavailable; raw transport runtime remains unverified")
            harness = "const fs=require('fs'),vm=require('vm'),s={};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),s);vm.runInNewContext(fs.readFileSync(0,'utf8'),s);process.stdout.write(JSON.stringify(s.CODE_ONTOLOGY_RAW_PAGE));"
            run = subprocess.run([node, "-e", harness, str(view.ASSETS / "pipeline-raw.js")], input=script,
                                 text=True, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), payload)
            for unsafe in ("</script>", "\u2028", "\u2029", "unexpected()"):
                if unsafe == "unexpected()":
                    continue  # It is retained only inside a JSON string, never executable syntax.
                self.assertNotIn(unsafe, script)
            for locale in view.LANGUAGES:
                page = self.output / locale / (path.stem + ".html")
                text = page.read_text()
                self.assertIn('../data/' + path.name, text)
                self.assertIn('../data/' + path.stem + '.js', text)
                self.assertLess(text.index('<script src="../assets/pipeline-raw.js"'), text.index('<script src="../data/' + path.stem + '.js"'))
                self.assertIn(view.TRANSLATIONS[locale]["raw_pending"], text)
                self.assertNotIn("unexpected()", text)
                self.assertLess(text.index('<script src="../data/' + path.stem + '.js"'), text.index('<script src="../assets/pipeline.js"'))
                for record in payload["records"]:
                    self.assertIn(view._anchor(record["id"]), Page(text).records)
        self.assertEqual(decoded, self.records)
        self.assertEqual(result["outputBytes"], sum(p.stat().st_size for p in self.output.rglob("*") if p.is_file()))

    def test_shared_data_json_and_script_writes_keep_the_privacy_guard(self):
        record = {**symbol(0), "nested": {"identity": "Synthetic Private Person"}}
        raw, script = view._raw_page([record], "synthetic-snapshot-1")
        profile = json.loads(self.profile_file.read_text())
        for name, content in (("raw.json", raw), ("raw.js", script)):
            with self.subTest(name=name), self.assertRaises(guard.PrivacyError):
                view._write(self.base / name, content, profile)
            self.assertFalse((self.base / name).exists())

    def test_shared_data_output_budget_failure_cleans_partial_stage(self):
        self.records = [symbol(0)]
        raw, script = view._raw_page(self.records, "synthetic-snapshot-1")
        asset_bytes = sum((view.ASSETS / name).stat().st_size for name in ("pipeline.css", "pipeline.js", "pipeline-raw.js"))
        budget = asset_bytes + len(raw.encode()) + len(script.encode()) // 2
        written = []
        original = view._write
        def observe(path, text, profile):
            written.append(path.name)
            return original(path, text, profile)
        with mock.patch.object(view, "_write", side_effect=observe):
            with self.assertRaisesRegex(view.PipelineHtmlError, "output_budget_exceeded"):
                view.render_pipeline(self.workspace, "synthetic-snapshot-1", self.output, include_maps=False, max_output_bytes=budget)
        self.assertIn("symbol-000001.json", written)
        self.assertNotIn("symbol-000001.js", written)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".pipeline-html-*")), [])

    def test_shared_raw_runtime_search_missing_binding_and_inert_text(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; browser remains unverified")
        records = [{**symbol(0), "rawOnlyValue": "hidden-search-target </script>\u2028", "__proto__": {"ordinary": True}}]
        raw, script = view._raw_page(records, "snapshot-check")
        harness = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8'),decoder=fs.readFileSync(process.argv[2],'utf8'),payload=JSON.parse(fs.readFileSync(0,'utf8'));
function run(mode){
 const events={},details={open:false,addEventListener:(key,fn)=>details[key]=fn};
 const pre={dataset:{rawRecord:'symbol:0000',rawSnapshot:'snapshot-check'},textContent:'Explicit missing data notice',closest:()=>details};
 const row={textContent:'visible metadata',hidden:false,querySelector:()=>pre};
 const input={value:'',addEventListener:(key,fn)=>events[key]=fn},count={textContent:''},empty={hidden:false};
 const sandbox={document:{getElementById:id=>({'page-search':input,'search-count':count,'search-empty':empty}[id]),querySelectorAll:()=>[row]},setTimeout:fn=>{fn();return 1;},clearTimeout:()=>{}};
 vm.runInNewContext(decoder,sandbox);
 if(mode!=='missing')vm.runInNewContext(payload.script,sandbox);
 if(mode==='wrongSnapshot')sandbox.CODE_ONTOLOGY_RAW_PAGE.snapshotId='another';
 if(mode==='wrongPage')sandbox.CODE_ONTOLOGY_RAW_PAGE.records[0].id='another-record';
 vm.runInNewContext(source,sandbox);
 input.value='hidden-search-target';events.input();
 const found=!row.hidden,collapsed=pre.textContent;
 details.open=true;if(details.toggle)details.toggle();
 return {mode,found,collapsed,displayed:pre.textContent,ownProto:mode==='loaded'&&Object.hasOwn(sandbox.CODE_ONTOLOGY_RAW_PAGE.records[0],'__proto__')};
}
process.stdout.write(JSON.stringify(['loaded','missing','wrongSnapshot','wrongPage'].map(run)));
'''
        run = subprocess.run([node, "-e", harness, str(view.ASSETS / "pipeline.js"), str(view.ASSETS / "pipeline-raw.js")], input=json.dumps({"script": script}), text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        results = json.loads(run.stdout)
        loaded = results[0]
        self.assertTrue(loaded["found"] and loaded["ownProto"])
        self.assertEqual(loaded["collapsed"], "Explicit missing data notice")
        self.assertEqual(json.loads(loaded["displayed"]), records[0])
        for missing in results[1:]:
            self.assertFalse(missing["found"])
            self.assertEqual(missing["displayed"], "Explicit missing data notice")
        self.assertEqual(json.loads(raw)["records"], records)

    def test_search_is_bounded_preindexed_and_keeps_queries_out_of_storage_and_urls(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; browser remains unverified")
        source = (view.ASSETS / "pipeline.js").read_text()
        for forbidden in ("localStorage", "sessionStorage", "location", "fetch(", "XMLHttpRequest", "innerHTML"):
            self.assertNotIn(forbidden, source)
        script = r'''
const fs=require('fs'),vm=require('vm');
const callbacks=[],timers=[];let cancelled=[];
const rows=[{textContent:'Alpha evidence',hidden:false},{textContent:'Beta policy',hidden:false}];
const input={value:'',addEventListener:(event,fn)=>callbacks[event]=fn};
const count={textContent:''},empty={hidden:false};
const sandbox={document:{getElementById:id=>({'page-search':input,'search-count':count,'search-empty':empty}[id]),querySelectorAll:()=>rows},
setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:id=>cancelled.push(id)};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),sandbox);
input.value='alpha';callbacks.input();input.value='beta';callbacks.input();timers.at(-1)();
const filtered=rows.map(row=>row.hidden),found=count.textContent;
callbacks.keydown({key:'Escape'});
process.stdout.write(JSON.stringify({filtered,found,restored:rows.every(row=>!row.hidden),cleared:input.value==='',cancelled}));
'''
        result = subprocess.run([node, "-e", script, str(view.ASSETS / "pipeline.js")], capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["filtered"], [True, False])
        self.assertEqual(data["found"], "1 / 2")
        self.assertTrue(data["restored"] and data["cleared"])
        self.assertIn(1, data["cancelled"])


if __name__ == "__main__":
    unittest.main()
