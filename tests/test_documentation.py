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


class DocumentationValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        legal_paths = set(validator.legal_translation_paths())
        readme_paths = set(validator.root_readme_paths())
        for relative in validator.expected_document_paths():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            marker = (
                f"{validator.LEGAL_TRANSLATION_MARKER}\n"
                if relative in legal_paths
                else ""
            )
            if relative in readme_paths:
                navigation = validator.README_LANGUAGE_NAVIGATION
                parity = "\n".join(validator.README_PARITY_TOKENS)
            else:
                navigation = " | ".join(validator.LANGUAGE_NAVIGATION_TOKENS)
                parity = ""
            path.write_text(
                f"# {relative}\n\n{navigation}\n\n{marker}{parity}\nContent.\n",
                encoding="utf-8",
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_complete_documentation_matrix(self) -> None:
        expected = validator.expected_document_paths()
        self.assertEqual(81, len(expected))
        self.assertIn("README.ru.md", expected)
        self.assertIn("docs/ja/NOTICE.md", expected)
        self.assertNotIn("docs/ja/NOTICE", expected)
        self.assertEqual(len(expected), validator.validate_documentation(self.root))

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
