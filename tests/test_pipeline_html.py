"""Synthetic offline export, privacy, access and exact-navigation regressions."""
from __future__ import annotations

from contextlib import contextmanager
from html.parser import HTMLParser
import json
import importlib
import os
from pathlib import Path
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
        self.profile_file.chmod(0o600)
        patcher = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(self.profile_file), acl.PRINCIPAL_ENV: "local-owner"})
        patcher.start()
        self.addCleanup(patcher.stop)
        acl.initialize_access(self.workspace)
        self.records = [symbol(index) for index in range(103)]
        self.records += [{"id": "assertion:choice", "kind": "assertion", "name": "calls", "module": "src", "path": "src/flow.py",
                          "span": {"lineStart": 5, "lineEnd": 6}, "subject": "symbol:0000", "predicate": "CALLS", "object": "symbol:0001",
                          "basis": "direct_syntax", "status": "observed"}, policy_record()]
        self.reader_open_count, self.requested_page_sizes, self.exit_error, self.on_exit = 0, [], False, None
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
