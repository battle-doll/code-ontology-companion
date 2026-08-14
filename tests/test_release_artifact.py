from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_release  # noqa: E402
import build_skills_only_release  # noqa: E402
import validate_release_artifact as validator  # noqa: E402


class ReleaseArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.full = cls.root / "baseline-full" / (
            f"{validator.EXPECTED_NAME}-{validator.EXPECTED_VERSION}.zip"
        )
        cls.skills = cls.root / "baseline-skills" / (
            f"{validator.EXPECTED_NAME}-skills-only-{validator.EXPECTED_VERSION}.zip"
        )
        build_release.build_archive(cls.full)
        build_skills_only_release.build_archive(cls.skills)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _target(self, case: str, profile: str = "full") -> Path:
        marker = "-skills-only" if profile == "skills-only" else ""
        target = self.root / case / (
            f"{validator.EXPECTED_NAME}{marker}-{validator.EXPECTED_VERSION}.zip"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _rewrite(
        self,
        source: Path,
        target: Path,
        *,
        omit: str | None = None,
        mutate: Callable[[zipfile.ZipInfo, bytes], tuple[zipfile.ZipInfo, bytes]] | None = None,
        extra: tuple[zipfile.ZipInfo, bytes] | None = None,
    ) -> None:
        with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as changed:
            for source_info in original.infolist():
                if source_info.filename == omit:
                    continue
                info = copy.copy(source_info)
                content = original.read(source_info)
                if mutate is not None:
                    info, content = mutate(info, content)
                changed.writestr(info, content)
            if extra is not None:
                changed.writestr(*extra)

    def _companion_help(self, source: Path) -> str:
        with tempfile.TemporaryDirectory() as raw:
            extracted = Path(raw)
            with zipfile.ZipFile(source) as archive:
                for relative in (
                    "skills/manage-code-ontology/scripts/code_ontology_core.py",
                    "skills/manage-code-ontology/scripts/companion.py",
                ):
                    target = extracted / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(f"{validator.PREFIX}{relative}"))
            environment = dict(os.environ)
            for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
                environment.pop(name, None)
            environment.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        extracted
                        / "skills/manage-code-ontology/scripts/companion.py"
                    ),
                    "--help",
                ],
                cwd=extracted,
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_both_profiles_are_exact_and_extracted_smoke_passes(self) -> None:
        validator.validate_archive(self.full, "full", run_smoke=True)
        validator.validate_archive(self.skills, "skills-only", run_smoke=True)
        with zipfile.ZipFile(self.full) as archive:
            full_manifest = json.loads(
                archive.read(
                    f"{validator.PREFIX}.codex-plugin/plugin.json"
                ).decode("utf-8")
            )
            full_entries = set(archive.namelist())
            full_readmes = {
                relative: archive.read(f"{validator.PREFIX}{relative}").decode(
                    "utf-8"
                )
                for relative in (
                    "README.md",
                    "README.ko.md",
                    "README.ja.md",
                    "README.zh-CN.md",
                    "README.ru.md",
                )
            }
        with zipfile.ZipFile(self.skills) as archive:
            manifest = json.loads(
                archive.read(
                    f"{validator.PREFIX}.codex-plugin/plugin.json"
                ).decode("utf-8")
            )
            skill = archive.read(
                f"{validator.PREFIX}skills/manage-code-ontology/SKILL.md"
            ).decode("utf-8")
            local_mcp = archive.read(
                f"{validator.PREFIX}skills/manage-code-ontology/references/local-mcp.md"
            ).decode("utf-8")
            skill_entries = set(archive.namelist())
        language_switcher = (
            "[English](README.md) | [한국어](README.ko.md) | "
            "[日本語](README.ja.md) | [简体中文](README.zh-CN.md) | "
            "[Русский](README.ru.md)"
        )
        expected_readmes = {
            f"{validator.PREFIX}{relative}" for relative in full_readmes
        }
        self.assertTrue(expected_readmes.issubset(full_entries))
        self.assertTrue(expected_readmes.isdisjoint(skill_entries))
        for relative, content in full_readmes.items():
            with self.subTest(full_readme=relative):
                self.assertIn(language_switcher, content)
        self.assertNotIn("mcpServers", manifest)
        self.assertIn("Ollama", manifest["interface"]["longDescription"])
        self.assertIn("local MCP", manifest["interface"]["longDescription"])
        self.assertIn(
            "rule-attributed relationship evidence",
            manifest["interface"]["longDescription"],
        )
        self.assertIn(
            "adapter coverage",
            manifest["interface"]["longDescription"],
        )
        self.assertIn(
            "Auditable relationship evidence and adapter coverage",
            manifest["interface"]["capabilities"],
        )
        self.assertIn("127.0.0.1:11434", skill)
        self.assertIn("Do not connect or write before an", skill)
        self.assertIn("Windows", local_mcp)
        self.assertIn("workspace_id", local_mcp)
        self.assertNotIn("runtime-path", full_manifest["interface"]["longDescription"])
        self.assertNotIn(
            "Immutable static runtime-path receipts",
            full_manifest["interface"]["capabilities"],
        )
        self.assertNotIn(
            "Immutable static runtime-path receipts",
            manifest["interface"]["capabilities"],
        )
        removed_command = "runtime-" + "binding"
        self.assertNotIn(removed_command, self._companion_help(self.full))
        self.assertNotIn(removed_command, self._companion_help(self.skills))
        self.assertFalse(any(name.endswith("/.mcp.json") for name in skill_entries))
        self.assertFalse(any("/mcp/server.py" in name for name in skill_entries))

    def test_skills_only_public_scan_rejects_private_domain_wording(self) -> None:
        for forbidden in (
            "AET" + "HER",
            "runtime-" + "binding",
            "aeth" + "er.runtime-effective-ontology-" + "binding/v1",
            "runtime" + "Effective",
            "strategy." + "exits.stopLossPct",
            '"funds_transfer": false',
            '"order_submission": false',
            "does_not_prove_profit_causation",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(validator.ReleaseValidationError):
                    validator._validate_skills_only_public_content(
                        {"skills/manage-code-ontology/SKILL.md": forbidden.encode()}
                    )

    def test_independent_builds_are_byte_identical(self) -> None:
        full_second = self._target("second-full")
        skills_second = self._target("second-skills", "skills-only")
        build_release.build_archive(full_second)
        build_skills_only_release.build_archive(skills_second)
        self.assertEqual(self.full.read_bytes(), full_second.read_bytes())
        self.assertEqual(self.skills.read_bytes(), skills_second.read_bytes())

    def test_skills_only_preserves_supported_skill_content(self) -> None:
        skill_path = ROOT / "skills/manage-code-ontology/SKILL.md"
        content = skill_path.read_bytes()
        self.assertEqual(validator.skills_only_skill(content), content)
        with self.assertRaises(validator.ReleaseValidationError):
            validator.skills_only_skill(b"\xff\xfe")
        self.assertEqual(
            validator.skills_only_content(
                "skills/manage-code-ontology/references/local-mcp.md",
                b"supported local MCP setup\n",
            ),
            b"supported local MCP setup\n",
        )

    def test_source_selection_treats_windows_reparse_points_as_links(self) -> None:
        metadata = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=validator.WINDOWS_REPARSE_POINT,
        )
        self.assertTrue(validator._is_link_like(metadata))

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlink test requires platform support")
    def test_source_selection_rejects_linked_selected_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "source"
            outside = Path(raw) / "outside-skills"
            source.mkdir()
            outside.mkdir()
            try:
                (source / "skills").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Directory symlink is unavailable: {exc}")
            with self.assertRaisesRegex(
                validator.ReleaseValidationError,
                "symbolic link or reparse point",
            ):
                validator.selected_source_files(source, "full")

    def test_rejects_path_traversal_and_case_collisions(self) -> None:
        traversal = self._target("traversal")
        info = validator.archive_info("../escape.py")
        self._rewrite(self.full, traversal, extra=(info, b"pass\n"))
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(traversal, "full", run_smoke=False)

        collision = self._target("collision")
        info = validator.archive_info("readme.md")
        self._rewrite(self.full, collision, extra=(info, b"collision\n"))
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(collision, "full", run_smoke=False)

    def test_rejects_duplicate_entry_and_missing_required_entry(self) -> None:
        duplicate = self._target("duplicate")
        shutil.copyfile(self.full, duplicate)
        with zipfile.ZipFile(duplicate, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            existing = archive.getinfo(f"{validator.PREFIX}LICENSE")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(copy.copy(existing), archive.read(existing))
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(duplicate, "full", run_smoke=False)

        missing = self._target("missing")
        self._rewrite(self.full, missing, omit=f"{validator.PREFIX}LICENSE")
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(missing, "full", run_smoke=False)

    def test_rejects_wrong_timestamp_mode_and_version(self) -> None:
        expected_license = f"{validator.PREFIX}LICENSE"

        def timestamp_mutation(info: zipfile.ZipInfo, content: bytes) -> tuple[zipfile.ZipInfo, bytes]:
            if info.filename == expected_license:
                info.date_time = (2026, 8, 11, 0, 0, 0)
            return info, content

        wrong_timestamp = self._target("timestamp")
        self._rewrite(self.full, wrong_timestamp, mutate=timestamp_mutation)
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(wrong_timestamp, "full", run_smoke=False)

        def mode_mutation(info: zipfile.ZipInfo, content: bytes) -> tuple[zipfile.ZipInfo, bytes]:
            if info.filename == expected_license:
                info.external_attr = (0o100600) << 16
            return info, content

        wrong_mode = self._target("mode")
        self._rewrite(self.full, wrong_mode, mutate=mode_mutation)
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(wrong_mode, "full", run_smoke=False)

        manifest_name = f"{validator.PREFIX}.codex-plugin/plugin.json"

        def version_mutation(info: zipfile.ZipInfo, content: bytes) -> tuple[zipfile.ZipInfo, bytes]:
            if info.filename == manifest_name:
                manifest = json.loads(content)
                manifest["version"] = "9.9.9"
                content = json.dumps(manifest, indent=2, ensure_ascii=False).encode() + b"\n"
            return info, content

        wrong_version = self._target("version")
        self._rewrite(self.full, wrong_version, mutate=version_mutation)
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(wrong_version, "full", run_smoke=False)

    def test_rejects_crc_corruption_and_profile_mismatch(self) -> None:
        corrupt = self._target("crc")
        data = bytearray(self.full.read_bytes())
        with zipfile.ZipFile(self.full, "r") as archive:
            info = archive.getinfo(f"{validator.PREFIX}LICENSE")
        local_header = struct.unpack("<IHHHHHIIIHH", data[info.header_offset : info.header_offset + 30])
        name_length, extra_length = local_header[-2:]
        compressed_start = info.header_offset + 30 + name_length + extra_length
        data[compressed_start + max(0, info.compress_size // 2)] ^= 0x01
        corrupt.write_bytes(data)
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(corrupt, "full", run_smoke=False)

        profile_mismatch = self._target("profile-mismatch", "skills-only")
        shutil.copyfile(self.full, profile_mismatch)
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(profile_mismatch, "skills-only", run_smoke=False)

    def test_checksum_must_match_exact_archive(self) -> None:
        target = self._target("checksum")
        shutil.copyfile(self.full, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        target.with_suffix(".zip.sha256").write_text(
            f"{digest}  {target.name}\n", encoding="ascii"
        )
        validator.validate_archive(
            target, "full", run_smoke=False, verify_checksum=True
        )
        target.with_suffix(".zip.sha256").write_text(
            f"{'0' * 64}  {target.name}\n", encoding="ascii"
        )
        with self.assertRaises(validator.ReleaseValidationError):
            validator.validate_archive(
                target, "full", run_smoke=False, verify_checksum=True
            )


if __name__ == "__main__":
    unittest.main()
