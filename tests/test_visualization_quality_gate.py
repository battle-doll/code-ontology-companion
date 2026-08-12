from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_visualization_quality.py"
CASES = ROOT / "evals" / "visualization-quality-cases.json"
ASSETS = ROOT / "skills" / "manage-code-ontology" / "assets"

SPEC = importlib.util.spec_from_file_location("validate_visualization_quality", VALIDATOR)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class VisualizationQualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CASES.read_text(encoding="utf-8"))

    def test_release_assets_pass_every_visualization_contract(self) -> None:
        result = gate.evaluate(self.corpus)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["summary"], {"passed": 8, "failed": 0, "total": 8})
        self.assertLessEqual(
            result["budgets"]["max_3d_nodes"],
            self.corpus["budgets"]["max_3d_nodes_ceiling"],
        )
        self.assertLessEqual(
            result["budgets"]["max_3d_edges"],
            self.corpus["budgets"]["max_3d_edges_ceiling"],
        )

    def test_corpus_rejects_missing_contract_or_nonpositive_budget(self) -> None:
        missing = copy.deepcopy(self.corpus)
        missing["checks"].pop()
        with self.assertRaisesRegex(gate.VisualizationGateError, "check set"):
            gate.validate_corpus(missing)

        invalid = copy.deepcopy(self.corpus)
        invalid["budgets"]["max_3d_nodes_ceiling"] = 0
        with self.assertRaisesRegex(gate.VisualizationGateError, "budgets"):
            gate.validate_corpus(invalid)

    def test_unsafe_application_primitive_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            for name in ("workbench.html", "workbench.js", "workbench.css"):
                (assets / name).write_text((ASSETS / name).read_text(encoding="utf-8"), encoding="utf-8")
            with (assets / "workbench.js").open("a", encoding="utf-8") as stream:
                stream.write("\nfetch('https://example.invalid');\n")
            result = gate.evaluate(self.corpus, assets)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["offline-safe"]["status"], "fail")

    def test_resource_cap_regression_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            for name in ("workbench.html", "workbench.js", "workbench.css"):
                text = (ASSETS / name).read_text(encoding="utf-8")
                if name == "workbench.js":
                    text = text.replace(
                        "MAX_3D_VISIBLE_NODES = 160",
                        "MAX_3D_VISIBLE_NODES = 9999",
                    )
                (assets / name).write_text(text, encoding="utf-8")
            result = gate.evaluate(self.corpus, assets)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["checks"]["deterministic-resource-bounds"]["status"], "fail"
        )

    def test_inert_three_d_scaffolding_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            for name in ("workbench.html", "workbench.js", "workbench.css"):
                text = (ASSETS / name).read_text(encoding="utf-8")
                if name == "workbench.js":
                    text = text.replace('.clearRect(', '.inertClearRect(')
                    text = text.replace(
                        'viewMode3d.addEventListener("click"',
                        'viewMode3d.inertListener("click"',
                    )
                (assets / name).write_text(text, encoding="utf-8")
            result = gate.evaluate(self.corpus, assets)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["three-d-controls"]["status"], "fail")
        self.assertEqual(result["checks"]["progressive-fallback"]["status"], "fail")

    def test_two_d_three_d_and_text_neighborhood_must_share_the_same_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            for name in ("workbench.html", "workbench.js", "workbench.css"):
                text = (ASSETS / name).read_text(encoding="utf-8")
                if name == "workbench.js":
                    text = text.replace(
                        "const graph = bounded3dGraph(\n      neighborhood(",
                        "const graph = neighborhood(",
                    )
                (assets / name).write_text(text, encoding="utf-8")
            result = gate.evaluate(self.corpus, assets)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            result["checks"]["deterministic-resource-bounds"]["status"], "fail"
        )

    def test_hidden_graph_must_stop_three_d_animation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = Path(temporary)
            for name in ("workbench.html", "workbench.js", "workbench.css"):
                text = (ASSETS / name).read_text(encoding="utf-8")
                if name == "workbench.js":
                    text = text.replace("      stop3dFrame();\n", "      void 0;\n", 1)
                (assets / name).write_text(text, encoding="utf-8")
            result = gate.evaluate(self.corpus, assets)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["motion-and-visibility"]["status"], "fail")

    def test_cli_emits_only_canonical_json_and_uses_stable_exit_codes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(
            result.stdout.strip(),
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )


if __name__ == "__main__":
    unittest.main()
