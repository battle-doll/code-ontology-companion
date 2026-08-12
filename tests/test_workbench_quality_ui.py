from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "skills" / "manage-code-ontology" / "assets"
HTML = ASSETS / "workbench.html"
JS = ASSETS / "workbench.js"
CSS = ASSETS / "workbench.css"


class WorkbenchQualityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")

    def test_quality_panel_and_legacy_state_are_present(self) -> None:
        for marker in (
            'id="quality-panel"',
            'id="quality-contract"',
            'id="quality-content"',
            'aria-labelledby="quality-title"',
        ):
            self.assertIn(marker, self.html)
        self.assertIn('dataset.qualityState = "legacy"', self.js)
        self.assertIn('qualityContract === "legacy_unknown"', self.js)
        self.assertIn("품질 계약 메타데이터가 없습니다", self.js)

    def test_canonical_quality_contract_fields_are_consumed(self) -> None:
        for marker in (
            "contract_version",
            "relationship_evidence",
            "total_edges",
            "documented_edges",
            "missing_evidence",
            "coverage_percent",
            "basis_counts",
            "runtime_status_counts",
            "unsupported_runtime",
            "capabilities",
            "interpretation",
        ):
            self.assertIn(marker, self.js)
        for status in ("supported", "partial", "unsupported"):
            self.assertIn(status + ":", self.js)

    def test_selected_edge_uses_only_bounded_evidence_metadata(self) -> None:
        for marker in (
            "rule_id",
            "direct_syntax",
            "resolved_static",
            "framework_semantic",
            "name_heuristic",
            "runtime_unknown",
            "line_start",
            "line_end",
            "limitations",
            'state.cy.on("tap", "edge"',
        ):
            self.assertIn(marker, self.js)
        for forbidden in (
            "source_text",
            "sourceText",
            "source_body",
            "sourceBody",
        ):
            self.assertNotIn(forbidden, self.js)
        self.assertIn("소스 본문은 이 패널에 포함하지 않습니다", self.js)
        self.assertIn('path.startsWith("/")', self.js)
        self.assertIn('/^[A-Za-z]:[\\\\/]/.test(path)', self.js)

    def test_quality_ui_preserves_offline_csp_and_safe_dom_rendering(self) -> None:
        for marker in (
            "default-src 'none'",
            "connect-src 'none'",
            "worker-src 'none'",
        ):
            self.assertIn(marker, self.html)
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "document.write",
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "EventSource",
            "new Worker",
        ):
            self.assertNotIn(forbidden, self.js)
        self.assertIn(".quality-runtime-warning", self.css)
        self.assertIn(".edge-evidence-card", self.css)

    @unittest.skipUnless(shutil.which("node"), "Node is unavailable for JavaScript syntax validation")
    def test_workbench_javascript_syntax(self) -> None:
        result = subprocess.run(
            [shutil.which("node") or "node", "--check", str(JS)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
