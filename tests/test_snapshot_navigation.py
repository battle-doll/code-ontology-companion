from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import companion
import code_ontology_core as core


def node(identifier, *, name=None, kind="Method", path="src/Code.java"):
    return {"id": identifier, "name": name or identifier, "type": kind,
            "language": "Java", "qualified_name": identifier, "path": path,
            "metadata": {"line_start": 1, "line_end": 1}}


def edge(source, target, kind="CALLS", line=1):
    return {"source": source, "target": target, "type": kind, "evidence": [{
        "rule_id": "java.call.same_owner", "basis": "resolved_static",
        "runtime_status": "not_applicable", "path": "src/Code.java",
        "line_start": line, "line_end": line,
    }]}


class SnapshotNavigationTests(unittest.TestCase):
    def test_exact_identity_precedes_substrings_and_filters_page_stably(self):
        document = {"nodes": [node("zz", name="run"), node("aa", name="run_more"),
                              node("run", name="other"), node("nested", name="run", path="src2/Code.java")], "edges": []}
        first = core.query_document(document, "run", 1)
        self.assertEqual("run", first["matches"][0]["id"])
        self.assertEqual(1, first["next_offset"])
        second = core.query_document(document, "run", 2, offset=1, path_prefix="src", language="java", node_type="method")
        self.assertEqual(["zz", "aa"], [item["id"] for item in second["matches"]])
        self.assertIsNone(second["next_offset"])
        self.assertFalse(second["truncated"])
        self.assertEqual("unknown", second["scope"]["completeness"])
        with self.assertRaises(core.OntologyError):
            core.query_document(document, "run", 1, path_prefix="../src")

    def test_impact_directions_paths_and_shared_concepts(self):
        document = {"nodes": [node(key) for key in ("a", "b", "c", "unrelated")]
                    + [node("service", kind="FrameworkConcept")],
                    "edges": [edge("a", "b"), edge("b", "c", line=9),
                              edge("a", "service", "MANAGED_AS"), edge("unrelated", "service", "MANAGED_AS")]}
        impact = core.impact_document(document, "a", 5, direction="outgoing")
        self.assertEqual(["b", "c"], [item["node"]["id"] for item in impact["impact"]])
        path = impact["impact"][1]["path"]
        self.assertEqual([("a", "b"), ("b", "c")], [(step["source"], step["target"]) for step in path])
        self.assertEqual(9, path[1]["evidence"][0]["line_start"])
        self.assertRegex(path[1]["evidence"][0]["evidence_id"], r"^evidence:[0-9a-f]{24}$")
        incoming = core.impact_document(document, "c", 2, direction="incoming")
        self.assertEqual(["b", "a"], [item["node"]["id"] for item in incoming["impact"]])
        self.assertFalse(core.impact_document(document, "a", 1, limit=1)["truncated"])
        self.assertTrue(core.impact_document(document, "a", 2, limit=1)["truncated"])

    def test_impact_exact_id_does_not_lose_to_many_partial_matches(self):
        document = {"nodes": [node(f"a{index}", name=f"needle-{index}") for index in range(1200)]
                    + [node("needle", name="zzz")], "edges": []}
        self.assertEqual("needle", core.impact_document(document, "needle", 1)["root"]["id"])

    def test_canonical_diff_includes_location_and_evidence_changes(self):
        before = {"nodes": [node("a"), node("b")], "edges": [edge("a", "b")],
                  "companion": {"snapshotId": "before", "sourceFingerprint": "private1"}}
        after = copy.deepcopy(before)
        after["nodes"][0]["metadata"]["line_start"] = 8
        after["edges"][0]["evidence"][0]["line_start"] = 8
        after["edges"][0]["evidence"][0]["line_end"] = 8
        after["companion"] = {"snapshotId": "after", "sourceFingerprint": "private2"}
        diff = core.canonical_diff(after, before)
        self.assertEqual(1, diff["counts"]["nodesModified"])
        self.assertEqual(1, diff["counts"]["edgesModified"])
        self.assertNotEqual(diff["edgesModified"][0]["evidence"][0]["evidence_id"],
                            diff["edgesModified"][0]["previousEvidence"][0]["evidence_id"])
        self.assertEqual(diff, core._visualization_diff(after, before))
        self.assertNotIn("private", json.dumps(diff))

    def test_snapshot_pin_cache_reuse_copy_and_same_size_edit_invalidation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repo = base / "repo"
            repo.mkdir()
            source = repo / "sample.py"
            source.write_text("def first():\n    return 1\n")
            workspace = base / "workspace"
            with mock.patch.dict(os.environ, {"CODE_ONTOLOGY_HOME": str(base / "data")}):
                initial = companion.initialize(str(repo), str(workspace), authorized=True)
                companion._SNAPSHOT_CACHE.clear()
                with mock.patch.object(core, "SnapshotIndex", wraps=core.SnapshotIndex) as build:
                    result = companion.query(str(workspace), "first")
                    result["matches"][0]["name"] = "poison"
                    repeated = companion.query(str(workspace), "first")
                    self.assertEqual("first", repeated["matches"][0]["name"])
                    companion.impact(str(workspace), "first")
                    self.assertEqual(1, build.call_count)
                    index_path = workspace / "snapshots" / initial["snapshotId"] / "ontology.json"
                    raw = index_path.read_bytes()
                    index_path.write_bytes(raw.replace(b'"first"', b'"other"'))
                    changed = companion.query(str(workspace), "other")
                    self.assertEqual(2, build.call_count)
                    self.assertEqual("other", changed["matches"][0]["name"])
                source.write_text("def second():\n    return 1\n")
                companion.sync(str(workspace))
                pinned = companion.query(str(workspace), "first", snapshot=initial["snapshotId"])
                self.assertEqual(initial["snapshotId"], pinned["snapshotId"])
                self.assertTrue(pinned["matches"])
                self.assertFalse(companion.query(str(workspace), "first")["matches"])

    def test_java_parameter_and_local_bindings_shadow_imported_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "Calls.java").write_text("""package demo;
import java.util.Collections;
class Calls {
 void parameter(Worker Collections) { Collections.emptyList(); }
 void local() { Worker Collections = null; Collections.emptyList(); }
 void safe() { Collections.emptyList(); }
}
class Worker { void emptyList() {} }
""")
            document = core.build_document(repo)
            sources = {edge["source"] for edge in document["edges"] if edge["type"] == "CALLS"}
            self.assertFalse(any("#parameter(" in source or "#local(" in source for source in sources))
            self.assertTrue(any("#safe(" in source for source in sources))

    def test_python_unresolved_value_call_is_syntax_not_resolved_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "sample.py").write_text("from other import fetch\ndef run(fetch):\n    return fetch()\n")
            document = core.build_document(repo)
            calls = [item for item in document["edges"] if item["type"] == "CALLS"]
            self.assertEqual(1, len(calls))
            evidence = calls[0]["evidence"][0]
            self.assertEqual("direct_syntax", evidence["basis"])
            self.assertIn("python.call_target_not_resolved", evidence["limitations"])


if __name__ == "__main__":
    unittest.main()
