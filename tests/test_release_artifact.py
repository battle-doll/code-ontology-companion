from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
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
        with zipfile.ZipFile(self.skills) as archive:
            manifest = json.loads(
                archive.read(
                    f"{validator.PREFIX}.codex-plugin/plugin.json"
                ).decode("utf-8")
            )
            skill = archive.read(
                f"{validator.PREFIX}skills/manage-code-ontology/SKILL.md"
            ).decode("utf-8")
        self.assertNotIn("mcpServers", manifest)
        self.assertIn("Ollama", manifest["interface"]["longDescription"])
        self.assertIn("127.0.0.1:11434", skill)
        self.assertIn("Do not connect or write before an", skill)
        self.assertIn(
            "Immutable static runtime-path receipts",
            full_manifest["interface"]["capabilities"],
        )
        self.assertNotIn("runtime-path", manifest["interface"]["longDescription"])
        self.assertNotIn(
            "Immutable static runtime-path receipts",
            manifest["interface"]["capabilities"],
        )
        self.assertIn("runtime-binding", self._companion_help(self.full))
        self.assertNotIn("runtime-binding", self._companion_help(self.skills))

    def test_skills_only_public_scan_rejects_private_domain_wording(self) -> None:
        for forbidden in (
            "AETHER",
            "runtime-binding",
            "aether.runtime-effective-ontology-binding/v1",
            "runtimeEffective",
            "strategy.exits.stopLossPct",
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

    def test_skills_only_transform_requires_exact_source_fragments(self) -> None:
        with self.assertRaises(validator.ReleaseValidationError):
            validator.skills_only_skill(b"changed instructions without release transforms\n")
        companion_path = (
            ROOT / "skills/manage-code-ontology/scripts/companion.py"
        )
        malformed = companion_path.read_bytes().replace(
            b"# BEGIN FULL_PROFILE_PRIVATE_PARSER",
            b"# CHANGED FULL_PROFILE_PRIVATE_PARSER",
            1,
        )
        with self.assertRaises(validator.ReleaseValidationError):
            validator.skills_only_content(
                "skills/manage-code-ontology/scripts/companion.py",
                malformed,
            )

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
                info.date_time = (2026, 8, 3, 0, 0, 0)
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
