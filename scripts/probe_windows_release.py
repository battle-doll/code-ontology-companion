"""Scoped native Windows diagnostics; never a full release validation gate."""
from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from run_windows_validation import current_user_owner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/manage-code-ontology/scripts"))
import companion
import pipeline_access
import validate_package


def worker_metadata_summary(capture, output, partitioned):
    """Compare only an exported neutral worker's metadata; never return values."""
    summary = {"childStatus": "UNKNOWN", "metadataComparison": "UNKNOWN"}
    if capture["workers"] != 1 or capture["overflow"]:
        return summary
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_diagnostic_key")
                result[key] = value
            return result
        response = json.loads(bytes(capture["raw"]), object_pairs_hook=unique)
        if (type(response) is not dict
                or response.get("format") != "companion.private-policy-worker-response.v1"
                or response.get("status") != "exported"):
            return summary
        identities = (response.get("outputIdentity"), response.get("manifestIdentity"))
        if any(type(values) is not list or len(values) != size
               or any(type(value) is not int for value in values)
               for values, size in zip(identities, (4, 5))):
            return summary
        expected_digest = response.get("manifestSha256")
        if type(expected_digest) is not str or not re.fullmatch("[0-9a-f]{64}", expected_digest):
            return summary
        summary["childStatus"] = "EXPORTED"
        output_info = output.lstat()
        if companion.privacy_guard._link_like(output_info) or not stat.S_ISDIR(output_info.st_mode):
            return summary
        manifest = output / "policy-projection-set.json"
        manifest_info = manifest.lstat()
        companion.privacy_guard._check_private_file_metadata(manifest_info)
        actual = ([output_info.st_dev, output_info.st_ino, output_info.st_mode, getattr(output_info, "st_uid", 0)],
                  [manifest_info.st_dev, manifest_info.st_ino, manifest_info.st_size,
                   manifest_info.st_mtime_ns, manifest_info.st_ctime_ns])
        names = (("output_dev", "output_ino", "output_mode", "output_uid"),
                 ("manifest_dev", "manifest_ino", "manifest_size", "manifest_mtime", "manifest_ctime"))
        differences = [name for fields, expected, observed in zip(names, identities, actual)
                       for name, before, after in zip(fields, expected, observed) if before != after]
        digest = partitioned._policy_bounded_hash(manifest, 32 * 1024 ** 2)[0]
        summary.update({"metadataComparison": "COMPARED", "differentFields": differences,
                        "manifestDigestMatches": digest == expected_digest})
    except Exception:
        # Parse/stat/hash diagnostics cannot change the product result or print
        # response text, nonce, pins, profile facts, paths or metadata values.
        pass
    return summary


def synthetic_exports(root, security, partitioned):
    """Report only source-owned reason codes, never fixture text or paths."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_business_projection_boundaries import BusinessProjectionBoundaryTests
    from test_pipeline_partitioned import PartitionedExportTests
    from unittest.mock import patch
    allowed = set()
    for path in (ROOT / "skills/manage-code-ontology/scripts").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and type(node.value) is str and re.fullmatch("[a-z_]{1,100}", node.value):
                allowed.add(node.value)
    rows = []
    previous = tempfile.tempdir
    tempfile.tempdir = str(root)
    try:
        for label, fixture_type in (("ordinary_partitioned", PartitionedExportTests),
                                    ("policy_partitioned", BusinessProjectionBoundaryTests)):
            fixture = fixture_type("runTest")
            capture = {"raw": bytearray(), "overflow": False, "workers": 0}
            started = None
            row = {"variant": label, "status": "BLOCKED", "reason": "UNKNOWN"}
            try:
                fixture.setUp()
                if label == "ordinary_partitioned":
                    started = time.monotonic()
                    fixture.run_export()
                else:
                    fixture.meta = fixture.store.build(fixture.workspace, fixture.sid, partition_size=10000)
                    fixture.review([fixture.item("one"), fixture.item("two")])
                    fixture.grant(["read_policy", "export_html"])
                    profile_path = fixture.root / "worker-profile.json"
                    profile_path.write_text(json.dumps(fixture.profile), encoding="utf-8")
                    security.protect(profile_path)
                    real_popen = subprocess.Popen
                    class ObservedStdout:
                        def __init__(self, stream): self.stream = stream
                        def __getattr__(self, name): return getattr(self.stream, name)
                        def read(self, *args, **kwargs):
                            block = self.stream.read(*args, **kwargs)
                            if type(block) is bytes:
                                remaining = 65536 - len(capture["raw"])
                                capture["raw"].extend(block[:remaining])
                                if len(block) > remaining: capture["overflow"] = True
                            else:
                                capture["overflow"] = True
                            return block
                        def close(self): return self.stream.close()
                    def observe_popen(command, *args, **kwargs):
                        process = real_popen(command, *args, **kwargs)
                        if (type(command) in (list, tuple) and command
                                and command[-1] == partitioned._POLICY_WORKER_BOOTSTRAP
                                and process.stdout is not None):
                            capture["workers"] += 1
                            process.stdout = ObservedStdout(process.stdout)
                        return process
                    started = time.monotonic()
                    with patch.dict(os.environ, {companion.privacy_guard.PROFILE_ENV: str(profile_path), "CODE_ONTOLOGY_PRINCIPAL": "reader"}), \
                            patch.object(subprocess, "Popen", side_effect=observe_popen):
                        pipeline_access.export_business_view(fixture.workspace, fixture.sid, fixture.meta, fixture.root / "probe-result",
                            max_output_bytes=256 * 1024 ** 2, profile=fixture.profile, profile_roots=[fixture.workspace],
                            projection="policy_projection", partitioned=True, partition_size=2,
                            export_python=os.environ.get("CODE_ONTOLOGY_TEST_EXPORT_PYTHON", sys.executable))
                row = {"variant": label, "status": "EXPORTED"}
            except Exception as error:
                code = getattr(error, "code", None)
                report = getattr(error, "report", {})
                row = {"variant": label, "status": "BLOCKED", "reason": code if code in allowed else "UNKNOWN"}
                for key in ("selectedRecords", "processedRecords", "visitedRecords", "renderedRecordsByLocale"):
                    value = report.get(key) if type(report) is dict else None
                    if type(value) is int and value >= 0:
                        row[key] = value
                phase = report.get("phase") if type(report) is dict else None
                if phase in allowed:
                    row["phase"] = phase
            finally:
                try:
                    if started is not None:
                        row["elapsedSeconds"] = round(time.monotonic() - started, 3)
                    if label == "policy_partitioned":
                        row["workerMetadata"] = worker_metadata_summary(capture, fixture.root / "probe-result", partitioned) if hasattr(fixture, "root") else {"childStatus": "UNKNOWN", "metadataComparison": "UNKNOWN"}
                finally:
                    capture["raw"].clear()
                    fixture.doCleanups()
            rows.append(row)
            print(json.dumps({"probeSyntheticExport": row}, separators=(",", ":")), flush=True)
    finally:
        tempfile.tempdir = previous
    return rows


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
        fixture.write_bytes(b"neutral\r\nfixture\x1aend\n")
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
                digest = partitioned._policy_bounded_hash(path, 256 * 1024 ** 2)[0]
                row["productHash"] = "ACCEPTED_EXACT_BYTES" if digest == hashlib.sha256(path.read_bytes()).hexdigest() else "BYTE_MISMATCH"
            except partitioned.PartitionedExportError as error:
                row["productHash"] = error.code
            results["metadata"].append(row)
        print(json.dumps({"probeMetadata": results["metadata"]}, separators=(",", ":")), flush=True)

        class ParentAddRights(exporter._WindowsBoundary):
            def open_directory(self, path, *, source, rename=False):
                if source or path != self.parent:
                    return super().open_directory(path, source=source, rename=rename)
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

        parent=root/'nested-custody';parent.mkdir();security.protect(parent)
        stage=parent/'stage';stage.mkdir();security.protect(stage)
        outer=exporter._WindowsBoundary(parent)
        try:
            outer.bind_stage(stage)
            try:
                child=exporter._WindowsBoundary(stage)
                child.close()
                row={'status':'NESTED_ANCESTOR_OPENED'}
            except exporter.BusinessExportError as error:
                row={'status':'BLOCKED','reason':error.code,'winError':ctypes.get_last_error()}
            results['nestedCustody']=row
            print(json.dumps({'probeNestedCustody':row},separators=(',',':')),flush=True)
        finally:outer.close()

        results["syntheticExports"] = synthetic_exports(root, security, partitioned)
        if focused:
            environment = dict(os.environ)
            environment.update({"TMP": str(root), "TEMP": str(root), "TMPDIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"})
            patterns = ("test_business_export.py", "test_authorized_policy_projection.py", "test_business_projection_boundaries.py",
                        "test_partitioned_policy_projection.py", "test_documentation_review_pipeline.py", "test_literal_review_pipeline.py",
                        "test_local_source_access.py", "test_business_index_coherence.py", "test_pipeline_partitioned.py",
                        "test_policy_api_composition_contracts.py", "test_windows_artifact_metadata.py", "test_windows_stage_custody.py")
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
