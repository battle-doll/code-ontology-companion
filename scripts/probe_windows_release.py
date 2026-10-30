"""Scoped native Windows diagnostics; never a full release validation gate."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from run_windows_validation import current_user_owner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/manage-code-ontology/scripts"))
import companion
import pipeline_access
import validate_package


def run(focused=False):
    if os.name != "nt":
        raise RuntimeError("native_windows_required")
    _, _, exporter = pipeline_access._business()
    partitioned = companion.core._load_bundled_helper("pipeline_partitioned")
    partitioned.configure(store=None, exporter=exporter, privacy_guard=companion.privacy_guard)
    results = {"scope": "NATIVE_DIAGNOSTIC_ONLY_NOT_A_RELEASE_GATE", "metadata": [], "rename": [], "tests": []}
    with current_user_owner() as security, tempfile.TemporaryDirectory(prefix="ontology-windows-probe-") as raw:
        root = Path(raw).resolve()
        security.protect(root)
        fixture = root / "fixture.txt"
        fixture.write_bytes(b"neutral fixture\n")
        for label, path in (("interpreter", Path(sys.executable).resolve()),
                            ("bundled_script", ROOT / "skills/manage-code-ontology/scripts/companion.py"),
                            ("private_fixture", fixture)):
            before = path.lstat()
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns", "st_birthtime_ns")
                row = {"label": label, "differentFields": [key for key in fields if getattr(before, key, None) != getattr(opened, key, None)],
                       "sameFile": os.path.samestat(before, opened), "sameFileType": stat.S_IFMT(before.st_mode) == stat.S_IFMT(opened.st_mode)}
            try:
                partitioned._policy_bounded_hash(path, 256 * 1024 ** 2)
                row["productHash"] = "ACCEPTED"
            except partitioned.PartitionedExportError as error:
                row["productHash"] = error.code
            results["metadata"].append(row)
        print(json.dumps({"probeMetadata": results["metadata"]}, separators=(",", ":")), flush=True)

        class ParentAddRights(exporter._WindowsBoundary):
            def open_directory(self, path, *, source):
                if source or path != self.parent:
                    return super().open_directory(path, source=source)
                handle = self.api.CreateFileW(str(path), 0xA6, 3, None, 3, 0x02200000, None)
                if handle in (None, ctypes.c_void_p(-1).value):
                    raise exporter.BusinessExportError("export_windows_directory_open_failed")
                self.identity(handle)
                return handle

        for label, cls in (("current_parent_rights", exporter._WindowsBoundary), ("parent_add_rights", ParentAddRights)):
            parent = root / label
            parent.mkdir()
            security.protect(parent)
            stage = parent / "stage"
            stage.mkdir()
            security.protect(stage)
            boundary = cls(parent)
            try:
                boundary.bind_stage(stage)
                try:
                    boundary.rename("result")
                    row = {"variant": label, "status": "RENAMED", "targetPresent": (parent / "result").is_dir()}
                except exporter.BusinessExportError as error:
                    row = {"variant": label, "status": "BLOCKED", "reason": error.code, "winError": ctypes.get_last_error(), "ntStatus": getattr(error, "ntstatus", None), "ioStatus": getattr(error, "io_status", None)}
                results["rename"].append(row)
                print(json.dumps({"probeRename": row}, separators=(",", ":")), flush=True)
            finally:
                boundary.close()

        if focused:
            environment = dict(os.environ)
            environment.update({"TMP": str(root), "TEMP": str(root), "TMPDIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"})
            patterns = ("test_business_export.py", "test_authorized_policy_projection.py", "test_business_projection_boundaries.py",
                        "test_partitioned_policy_projection.py", "test_documentation_review_pipeline.py", "test_literal_review_pipeline.py",
                        "test_local_source_access.py", "test_business_index_coherence.py", "test_pipeline_partitioned.py",
                        "test_policy_api_composition_contracts.py")
            for pattern in patterns:
                process = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
                                         cwd=ROOT, env=environment, capture_output=True, text=True, timeout=900)
                count = re.search(r"Ran (\d+) tests? in", process.stderr)
                row = {"pattern": pattern, "exitCode": process.returncode, "total": int(count[1]) if count else "UNKNOWN"}
                if process.returncode:
                    row["failures"] = validate_package.safe_unittest_failure_summary(process.stdout + process.stderr, ROOT)
                results["tests"].append(row)
                print(json.dumps(row, separators=(",", ":")), flush=True)
    print(json.dumps(results, separators=(",", ":")), flush=True)
    return 1 if any(row["exitCode"] for row in results["tests"]) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="Run only the named diagnostic regression modules, never the full release gate.")
    try:
        raise SystemExit(run(parser.parse_args().tests))
    except Exception as error:
        # Never print an exception value, fixture payload or absolute path.
        print(json.dumps({"scope": "NATIVE_DIAGNOSTIC_ONLY_NOT_A_RELEASE_GATE", "status": "PROBE_FAILED", "exception": type(error).__name__}), flush=True)
        raise SystemExit(1)
