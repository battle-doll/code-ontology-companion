from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import validate_documentation as validator  # noqa: E402


PIPELINE_FIXTURE = '''```mermaid
flowchart TB
    source["Authorized Java/Spring + Python + Bash"]
    scope["Read-only source scope + SHA-256"]
    adapters["Python AST + conservative Java"]
    evidence["Typed source facts: observed / inferred"]
    gate["Coverage diagnostics + configured HMAC-SHA256 output guard"]
    snapshot["SQLite + policy.json + ontology.json + source-manifest.json + lineage.jsonl"]
    rdf["RDF 1.1 Turtle: ontology.ttl + lineage.ttl / PROV-O subset"]
    mcp["Local stdio MCP: JSON + JSONL, pinned snapshot"]
    ai["Evidence for AI tasks"]
    human["Offline human HTML"]
    source --> scope
    scope --> adapters
    adapters --> evidence
    evidence --> gate
    gate --> snapshot
    snapshot -->|Turtle exports| rdf
    snapshot -->|SQLite + policy.json / legacy JSON + JSONL| mcp
    mcp --> ai
    snapshot -->|bounded pages / embedded JSON| human
```'''


class DocumentationValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        legal_paths = set(validator.legal_translation_paths())
        readme_paths = set(validator.root_readme_paths())
        for relative in validator.expected_document_paths():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative in validator.NEXT_DESIGN_PATHS:
                path.write_text((ROOT / validator.NEXT_DESIGN_PATHS[0]).read_text(encoding="utf-8"), encoding="utf-8")
                continue
            if relative in validator.PIPELINE_GUIDE_PATHS:
                path.write_text((ROOT / validator.PIPELINE_GUIDE_PATHS[0]).read_text(encoding="utf-8"), encoding="utf-8")
                continue
            if relative in validator.COVERAGE_GUIDE_PATHS:
                path.write_text((ROOT / validator.COVERAGE_GUIDE_PATHS[0]).read_text(encoding="utf-8"), encoding="utf-8")
                continue
            marker = (
                f"{validator.LEGAL_TRANSLATION_MARKER}\n"
                if relative in legal_paths
                else ""
            )
            if relative in readme_paths:
                navigation = validator.README_LANGUAGE_NAVIGATION
                parity = "\n".join(validator.README_PARITY_TOKENS)
                parity += "\n" + PIPELINE_FIXTURE
            elif relative in validator.LINEAGE_REFERENCE_PATHS or relative in validator.ONTOLOGY_REFERENCE_PATHS:
                navigation = " | ".join(validator.README_LANGUAGE_NAVIGATION_TOKENS)
                parity = "\n".join(validator.LINEAGE_PARITY_TOKENS if relative in validator.LINEAGE_REFERENCE_PATHS
                                   else validator.ONTOLOGY_PARITY_TOKENS)
            elif relative in validator.FIVE_LANGUAGE_PATHS:
                navigation = " | ".join(validator.README_LANGUAGE_NAVIGATION_TOKENS)
                parity = "\n".join(
                    validator.CORE_GUIDE_PARITY_TOKENS if relative in validator.CORE_GUIDE_PATHS
                    else validator.PRIVACY_GUIDE_PARITY_TOKENS if relative in validator.PRIVACY_GUIDE_PATHS
                    else ()
                )
            else:
                navigation = " | ".join(validator.LANGUAGE_NAVIGATION_TOKENS)
                parity = ""
            path.write_text(
                f"# {relative}\n\n{navigation}\n\n{marker}{parity}\nContent.\n",
                encoding="utf-8",
            )
        schema = self.root / "skills/manage-code-ontology/references/provenance-schema.ttl"
        schema.write_text((ROOT / "skills/manage-code-ontology/references/provenance-schema.ttl").read_text(encoding="utf-8"), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_complete_documentation_matrix(self) -> None:
        expected = validator.expected_document_paths()
        self.assertEqual(131, len(expected))
        self.assertIn("README.ru.md", expected)
        self.assertIn("docs/ja/NOTICE.md", expected)
        self.assertNotIn("docs/ja/NOTICE", expected)
        self.assertEqual(len(expected), validator.validate_documentation(self.root))

    def test_accepts_utf8_crlf_documents_without_changing_semantic_checks(self) -> None:
        for path in self.root.rglob("*"):
            if path.is_file():
                content = path.read_bytes().replace(b"\r\n", b"\n")
                path.write_bytes(content.replace(b"\n", b"\r\n"))
        self.assertEqual(131, validator.validate_documentation(self.root))
        readme = self.root / "README.ru.md"
        readme.write_bytes(readme.read_bytes() + b"\r\n```mermaid\r\nflowchart TB\r\n```\r\n")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "one Mermaid diagram"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_future_design_translation(self) -> None:
        (self.root / "docs/ru/NEXT_ARCHITECTURE_0_9_0.md").unlink()
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Missing documentation file"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_coverage_translation(self) -> None:
        (self.root / "docs/ru/COVERAGE_0_9_2.md").unlink()
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Missing documentation file"):
            validator.validate_documentation(self.root)

    def test_rejects_coverage_evidence_contract_loss(self) -> None:
        path = self.root / "docs/ko/COVERAGE_0_9_2.md"
        path.write_text(path.read_text(encoding="utf-8").replace("ontologyOnlyFull", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Coverage verification guide parity"):
            validator.validate_documentation(self.root)

    def test_rejects_coverage_command_translation_drift(self) -> None:
        path = self.root / "docs/ja/COVERAGE_0_9_2.md"
        path.write_text(path.read_text(encoding="utf-8").replace("--source-root src", "--source-root other"), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Coverage command parity"):
            validator.validate_documentation(self.root)

    def test_rejects_pipeline_access_contract_loss(self) -> None:
        path = self.root / "docs/ko/PIPELINE_0_9_0.md"
        path.write_text(path.read_text(encoding="utf-8").replace("CODE_ONTOLOGY_PRINCIPAL", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Pipeline implementation guide parity"):
            validator.validate_documentation(self.root)

    def test_rejects_future_design_losing_unimplemented_boundary(self) -> None:
        path = self.root / "docs/ko/NEXT_ARCHITECTURE_0_9_0.md"
        path.write_text(path.read_text(encoding="utf-8").replace("NOT_IMPLEMENTED_IN_0_8_3", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Future design boundary parity"):
            validator.validate_documentation(self.root)

    def test_rejects_translation_changing_policy_calculation_example(self) -> None:
        path = self.root / "docs/ja/NEXT_ARCHITECTURE_0_9_0.md"
        path.write_text(path.read_text(encoding="utf-8").replace('"max_cases": 100', '"max_cases": 101'), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Future design policy example parity"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_russian_core_workflow(self) -> None:
        (self.root / "docs/ru/MODEL_ERA_WORKFLOW.md").unlink()
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Missing documentation file: docs/ru/MODEL_ERA_WORKFLOW"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_pipeline_diagram_in_one_language(self) -> None:
        path = self.root / "README.ru.md"
        path.write_text(path.read_text(encoding="utf-8").replace(PIPELINE_FIXTURE, ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "one Mermaid diagram"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_russian_lineage_reference(self) -> None:
        (self.root / "docs/ru/references/lineage-model.md").unlink()
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Missing documentation file: docs/ru/references/lineage-model"):
            validator.validate_documentation(self.root)

    def test_rejects_lineage_record_semantic_boundary_gap(self) -> None:
        path = self.root / "docs/ja/references/lineage-model.md"
        path.write_text(path.read_text(encoding="utf-8").replace("coc:recordedAt", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Model reference boundary parity"):
            validator.validate_documentation(self.root)

    def test_rejects_ontology_consumption_boundary_gap(self) -> None:
        path = self.root / "docs/ru/references/ontology-model.md"
        path.write_text(path.read_text(encoding="utf-8").replace("lineage.jsonl", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Model reference boundary parity"):
            validator.validate_documentation(self.root)

    def test_rejects_schema_domain_reclassifying_records_as_activities(self) -> None:
        path = self.root / "skills/manage-code-ontology/references/provenance-schema.ttl"
        path.write_text(path.read_text(encoding="utf-8").replace("rdfs:domain coc:LineageRecord", "rdfs:domain prov:Activity", 1), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "keep journal records separate"):
            validator.validate_documentation(self.root)

    def test_rejects_pipeline_stage_semantic_gap(self) -> None:
        path = self.root / "README.zh-CN.md"
        path.write_text(path.read_text(encoding="utf-8").replace('adapters["Python AST + conservative Java"]',
                                                'adapters["Python + Java"]'), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "stage labels are incomplete"):
            validator.validate_documentation(self.root)

    def test_rejects_native_rdf_mcp_claim(self) -> None:
        path = self.root / "README.ko.md"
        path.write_text(path.read_text(encoding="utf-8").replace('mcp["Local stdio MCP: JSON + JSONL, pinned snapshot"]',
                                                'mcp["Local stdio MCP: JSON + JSONL, pinned snapshot + RDF"]'), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "MCP JSON/JSONL reads"):
            validator.validate_documentation(self.root)

    def test_rejects_rdf_branch_used_as_mcp_input(self) -> None:
        path = self.root / "README.ja.md"
        path.write_text(path.read_text(encoding="utf-8").replace('snapshot -->|SQLite + policy.json / legacy JSON + JSONL| mcp',
                                                'rdf -->|ontology.ttl| mcp'), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "artifact paths are incomplete"):
            validator.validate_documentation(self.root)

    def test_rejects_core_workflow_safety_parity_gap(self) -> None:
        path = self.root / "docs/ko/MODEL_ERA_WORKFLOW.md"
        path.write_text(path.read_text(encoding="utf-8").replace("runtime_unknown", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Core workflow parity is incomplete"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_russian_privacy_operations(self) -> None:
        (self.root / "docs/ru/PRIVACY_OPERATIONS.md").unlink()
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Missing documentation file: docs/ru/PRIVACY_OPERATIONS"):
            validator.validate_documentation(self.root)

    def test_rejects_privacy_operations_receipt_boundary_gap(self) -> None:
        path = self.root / "docs/ko/PRIVACY_OPERATIONS.md"
        path.write_text(path.read_text(encoding="utf-8").replace("HOLD", ""), encoding="utf-8")
        with self.assertRaisesRegex(validator.DocumentationValidationError, "Privacy operations parity is incomplete"):
            validator.validate_documentation(self.root)

    def test_rejects_missing_document(self) -> None:
        (self.root / "docs/ja/SUPPORT.md").unlink()
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"Missing documentation file: docs/ja/SUPPORT\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_missing_russian_readme(self) -> None:
        (self.root / "README.ru.md").unlink()
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"Missing documentation file: README\.ru\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_symlink_instead_of_regular_file(self) -> None:
        translated = self.root / "docs/ko/SUPPORT.md"
        target = self.root / "support-target.md"
        target.write_text(translated.read_text(encoding="utf-8"), encoding="utf-8")
        translated.unlink()
        translated.symlink_to(target)
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"regular non-symlink file: docs/ko/SUPPORT\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_directory_instead_of_regular_file(self) -> None:
        translated = self.root / "docs/zh-CN/SUPPORT.md"
        translated.unlink()
        translated.mkdir()
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"regular non-symlink file: docs/zh-CN/SUPPORT\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_symlinked_documentation_directory(self) -> None:
        locale_directory = self.root / "docs/ko"
        target = self.root / "ko-content"
        locale_directory.rename(target)
        locale_directory.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"path must not traverse a symlink: docs/ko/README\.md: docs/ko",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_invalid_utf8(self) -> None:
        (self.root / "docs/zh-CN/CONTRIBUTING.md").write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"valid UTF-8: docs/zh-CN/CONTRIBUTING\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_whitespace_only_document(self) -> None:
        (self.root / "README.ko.md").write_text(" \n\t", encoding="utf-8")
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"must not be empty: README\.ko\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_missing_language_navigation_token(self) -> None:
        path = self.root / "docs/ja/references/ontology-model.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("简体中文", "Chinese"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"language navigation is incomplete: "
            r"docs/ja/references/ontology-model\.md: missing 简体中文",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_inconsistent_five_language_readme_switcher(self) -> None:
        path = self.root / "README.ja.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("[Русский]", "[Russian]"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"README\.ja\.md: missing Русский",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_readme_capability_parity_gap(self) -> None:
        path = self.root / "README.ru.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("RelationshipEvidence", ""),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"README capability parity is incomplete: README\.ru\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_readme_section_parity_gap(self) -> None:
        path = self.root / "README.zh-CN.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n## 额外章节\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"README section parity is incomplete: README\.zh-CN\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_legal_translation_without_common_marker(self) -> None:
        path = self.root / "docs/ko/TERMS.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                validator.LEGAL_TRANSLATION_MARKER, ""
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"English source authoritative: docs/ko/TERMS\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_primary_license_translation(self) -> None:
        translated_license = self.root / "docs/ko/LICENSE.md"
        translated_license.write_text("translation\n", encoding="utf-8")
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"License translations are forbidden: docs/ko/LICENSE\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_russian_license_translation(self) -> None:
        translated_license = self.root / "docs/ru/LICENSE.md"
        translated_license.parent.mkdir(parents=True, exist_ok=True)
        translated_license.write_text("translation\n", encoding="utf-8")
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"License translations are forbidden: docs/ru/LICENSE\.md",
        ):
            validator.validate_documentation(self.root)

    def test_rejects_vendor_license_translation(self) -> None:
        translated_license = (
            self.root
            / "skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2.0.ja.md"
        )
        translated_license.parent.mkdir(parents=True, exist_ok=True)
        translated_license.write_text("translation\n", encoding="utf-8")
        with self.assertRaisesRegex(
            validator.DocumentationValidationError,
            r"License translations are forbidden: "
            r"skills/manage-code-ontology/assets/vendor/licenses/ELKJS-EPL-2\.0\.ja\.md",
        ):
            validator.validate_documentation(self.root)


if __name__ == "__main__":
    unittest.main()
