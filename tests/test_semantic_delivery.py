"""Source-free delivery of semantic gaps through sealed records and exports."""
from __future__ import annotations

from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from windows_fixture import protect_private_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import pipeline_acl as acl
import pipeline_adapters as adapters
import pipeline_export as exporter
import pipeline_html as view
import pipeline_store as store
import policy_semantics as semantics
import privacy_guard as guard
import code_ontology_core as core


class SemanticDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.workspace = self.root / "knowledge"
        self.source = "class Rules {\n  static final int CAP = 6;\n  boolean accept(int amount) { return amount >= CAP; }\n}\n"
        (self.repo / "Rules.java").write_text(self.source, encoding="utf-8")
        profile = self.root / "profile.json"
        profile.write_text(json.dumps(guard.build_profile(["Synthetic Private Person"], ["person@privacy-fixture.test"], key=b"s" * 32)), encoding="utf-8")
        protect_private_path(profile)
        patcher = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(profile), acl.PRINCIPAL_ENV: "local-owner"})
        patcher.start(); self.addCleanup(patcher.stop)

    def initialize(self, token_limit=None):
        if token_limit is None:
            result = store.initialize(self.repo, self.workspace)
        else:
            with mock.patch.object(semantics, "MAX_TOKENS", token_limit):
                result = store.initialize(self.repo, self.workspace)
        acl.initialize_access(self.workspace)
        return result

    def test_zero_fragment_failure_blocks_promotion_and_retains_exact_region(self):
        result = self.initialize()
        original_state = (self.workspace / "state.json").read_bytes()
        with mock.patch.object(semantics, "MAX_TOKENS", 2):
            with self.assertRaisesRegex(store.PipelineError, "semantic_fragment_inventory_incomplete"):
                store.sync(self.workspace, force=True)
        self.assertEqual((self.workspace / "state.json").read_bytes(), original_state)
        self.assertEqual(store.status(self.workspace)["snapshotId"], result["snapshotId"])
        attempt = json.loads((self.workspace / "last-coverage-attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(attempt["summary"]["state"], "BLOCKED")
        self.assertEqual(len(attempt["semanticFailures"]), 1)
        failure = attempt["semanticFailures"][0]
        self.assertEqual(failure["path"], "Rules.java")
        self.assertEqual(failure["sourceDigest"], hashlib.sha256(self.source.encode()).hexdigest())
        coverage = failure["coverage"]
        self.assertFalse(coverage["inventoryComplete"])
        self.assertEqual(coverage["detectedFragments"], 0)
        self.assertEqual(coverage["reasons"], ["token_budget_exceeded"])
        self.assertEqual(coverage["unprocessedRegion"], {"lineStart": 1, "lineEnd": 4})
        self.assertFalse(coverage["businessPolicyComplete"])

    def test_unsupported_semantics_reach_all_html_languages_and_portable_sqlite(self):
        self.source = "class Rules { int compute(int value) { return transform(value); } int transform(int value) { return value; } }"
        (self.repo / "Rules.java").write_text(self.source, encoding="utf-8")
        result = self.initialize()
        self.assertEqual(result["coverage"]["semantics"]["state"], "PARTIAL")
        shutil.rmtree(self.repo)
        html = self.root / "html"
        view.render_pipeline(self.workspace, result["snapshotId"], html, include_maps=False)
        for language in view.LANGUAGES:
            content = (html / language / "semantic_fragment-000001.html").read_text(encoding="utf-8")
            self.assertIn("call_semantics_unresolved", content)
            self.assertIn("coverage_metadata", content)
        portable = self.root / "portable"
        exporter.export_bundle(self.workspace, result["snapshotId"], portable)
        with closing(sqlite3.connect(portable / "knowledge.sqlite")) as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM records WHERE kind='semantic_fragment'")]
        partial = [row for row in rows if "call_semantics_unresolved" in row.get("unsupportedReasons", [])]
        self.assertTrue(partial)
        self.assertEqual(partial[0]["sourceDigest"], hashlib.sha256(self.source.encode()).hexdigest())
        self.assertTrue(partial[0]["span"])
        self.assertFalse(partial[0]["businessMeaningVerified"])
        self.assertEqual(json.loads((portable / "bundle.json").read_text())["coverage"]["semantics"]["state"], "PARTIAL")

    def test_fragment_budget_retains_every_unprocessed_locator_without_promotion(self):
        self.initialize()
        original_state = (self.workspace / "state.json").read_bytes()
        extract = semantics.extract_semantics

        def bounded(*args, **kwargs):
            return extract(*args, **{**kwargs, "max_fragments": 1})

        with mock.patch.object(semantics, "extract_semantics", side_effect=bounded):
            with self.assertRaisesRegex(store.PipelineError, "semantic_fragment_inventory_incomplete"):
                store.sync(self.workspace, force=True)
        self.assertEqual((self.workspace / "state.json").read_bytes(), original_state)
        attempt = json.loads((self.workspace / "last-coverage-attempt.json").read_text(encoding="utf-8"))
        self.assertEqual(attempt["summary"]["state"], "BLOCKED")
        failure = attempt["semanticFailures"][0]
        self.assertEqual(failure["sourceSpan"], {"lineStart": 1, "lineEnd": 4})
        self.assertEqual(len(failure["omissions"]), failure["coverage"]["detectedFragments"] - 1)
        self.assertGreater(len(failure["omissions"]), 0)
        for omitted in failure["omissions"]:
            self.assertEqual(omitted["path"], "Rules.java")
            self.assertEqual(omitted["sourceDigest"], hashlib.sha256(self.source.encode()).hexdigest())
            self.assertEqual(omitted["reason"], "fragment_budget_exceeded")
            self.assertEqual(omitted["span"], {"lineStart": 3, "lineEnd": 3})
            self.assertEqual(omitted["status"], "not_processed")
            self.assertNotIn("expression", omitted)

    def test_legacy_failure_preserves_semantic_omissions_before_artifact_write(self):
        legacy_semantics = core._load_bundled_helper("policy_semantics")
        extract = legacy_semantics.extract_semantics
        def bounded(*args, **kwargs):
            return extract(*args, **{**kwargs, "max_fragments": 1})
        destination = self.root / "legacy-output"
        with mock.patch.object(legacy_semantics, "extract_semantics", side_effect=bounded):
            with self.assertRaises(core.ScopeIncompleteError) as caught:
                core.write_index(self.repo, destination, authorized=True)
        failure = caught.exception.inventory["semanticFailures"][0]
        self.assertEqual(failure["path"], "Rules.java")
        self.assertEqual(failure["sourceDigest"], hashlib.sha256(self.source.encode()).hexdigest())
        self.assertTrue(failure["omissions"])
        self.assertEqual(failure["omissions"][0]["reason"], "fragment_budget_exceeded")
        self.assertFalse((destination / "ontology.json").exists())

    def test_coverage_metadata_not_counted_as_semantic_fragments_or_policy_rules(self):
        result = self.initialize()
        rows = store.query(self.workspace, result["snapshotId"], kind="semantic_fragment")["records"]
        summary = result["coverage"]["semantics"]
        self.assertEqual(len(rows), summary["recordedFragments"] + 1)
        self.assertEqual(sum(row.get("category") == "coverage" for row in rows), 1)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["wholePolicyDenominator"], "UNKNOWN")

    def test_internal_mixed_source_bindings_are_rejected_before_relabeling(self):
        digest = hashlib.sha256(self.source.encode()).hexdigest()
        base = adapters.analyze_file("Rules.java", self.source, digest)
        base["semantics"] = semantics.extract_semantics(self.source, "Java", "Rules.java", digest)
        for mutate, reason in [
            (lambda facts: facts["semantics"].update(sourceDigest="e" * 64), "semantic_source_binding_mismatch"),
            (lambda facts: facts["semantics"]["fragments"][0].update(sourceDigest="e" * 64), "semantic_fragment_binding_mismatch"),
            (lambda facts: facts["semantics"]["fragments"][0].update(path="Other.java"), "semantic_fragment_binding_mismatch"),
        ]:
            facts = copy.deepcopy(base); mutate(facts)
            with closing(sqlite3.connect(":memory:")) as db:
                db.executescript(store.SCHEMA)
                with self.assertRaisesRegex(store.PipelineError, reason):
                    store._write_facts(db, facts)
                self.assertEqual(db.execute("SELECT count(*) FROM records").fetchone()[0], 0)

    def test_sensitive_values_stay_absent_from_source_free_records(self):
        source = 'class Rules { static final int apiKey = 987654; String note="private-contents-never-copy"; }'
        (self.repo / "Rules.java").write_text(source, encoding="utf-8")
        result = self.initialize()
        encoded = json.dumps(list(store.iter_records(self.workspace, result["snapshotId"])))
        self.assertNotIn("987654", encoded)
        self.assertNotIn("private-contents-never-copy", encoded)
        self.assertIn("sensitive_value_redacted", encoded)


if __name__ == "__main__":
    unittest.main()
