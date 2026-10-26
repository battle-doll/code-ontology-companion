"""Selection-first, non-executing source inventory. No source bodies in receipts.

Discovery and analysis are different denominators. Unreadable subtrees retain a
frontier and an UNKNOWN denominator; ignored files remain individual entries.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections import Counter
from pathlib import Path

VERSION = "source-inventory-1"
STRUCTURAL_SUFFIXES = frozenset({".java", ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".vue", ".kt", ".kts", ".cs", ".go", ".rs", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp",
    ".php", ".swift", ".dart", ".rb", ".scala", ".sh", ".bash", ".zsh", ".ksh", ".ps1", ".psm1"})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def protected_file(path, core=None):
    if core is None:
        import code_ontology_core as core
    # Names are not evidence of secret values. Only structural parsers may read
    # these files; arbitrary literals must never enter their public output.
    return core._is_sensitive_file(path) and path.suffix.lower() not in STRUCTURAL_SUFFIXES


def summarize(entries, frontiers):
    counts = Counter(row["status"] for row in entries)
    known = len(entries)
    denominator = None if frontiers else known
    processed = counts["analyzed"]
    blockers = counts["blocked"] + counts["failed"] + counts["interrupted"] + len(frontiers)
    return {"state": "BLOCKED" if blockers else "PARTIAL" if not known or processed != known else "COMPLETE",
        "numerator": processed, "denominator": denominator,
        "percent": round(100 * processed / denominator, 2) if denominator else None,
        "knownEntries": known, "counts": dict(sorted(counts.items())),
        "unknownDenominator": bool(frontiers), "semanticCompleteness": "UNKNOWN",
        "denominatorDefinition": "Every discovered file in selected roots before filters; inaccessible or bounded subtrees make the total UNKNOWN."}


def inventory(repo, roots, languages, *, max_files=25000, max_source_bytes=2*1024*1024,
              max_total_bytes=512*1024*1024, max_entries=500000, max_depth=64,
              cancel=None, deadline=None, read_file=None, core_api=None):
    if core_api is None:
        import code_ontology_core as core
    else:
        core = core_api
    repo = Path(os.path.abspath(repo))
    # Validate without resolving links. Discovery is also used independently of
    # the legacy core, so caller-side root normalization is not sufficient.
    if isinstance(roots, (str, bytes, dict)):
        raise core.OntologyError("Source roots must be relative directory paths.")
    selected = []
    for root in roots or ["."]:
        if not isinstance(root, str) or not root or root != root.strip():
            raise core.OntologyError("Source roots must be relative directory paths.")
        path = Path(root)
        if path.is_absolute() or "\\" in root or ":" in root or any(
                ord(char) < 32 or ord(char) == 127 for char in root):
            raise core.OntologyError("Source roots may not escape the selected repository.")
        if root != "." and any(part in {"", ".", ".."} or part.endswith((" ", ".")) for part in root.split("/")):
            raise core.OntologyError("Source roots may not escape the selected repository.")
        selected.append(root)
    selected = sorted(set(selected))
    selected = [root for root in selected if not any(
        other != root and (other == "." or root.startswith(other + "/")) for other in selected)]
    for bound in (max_files, max_source_bytes, max_total_bytes, max_entries, max_depth):
        if not isinstance(bound, int) or isinstance(bound, bool) or bound < 0:
            raise core.OntologyError("Source inventory budgets must be nonnegative integers.")
    entries, frontiers = [], []
    pending = [(repo / root, "ignored_directory" if any(part.lower() in core.EXCLUDED_DIRECTORIES
                for part in Path(root).parts) else None, 0) for root in reversed(selected)]
    total = eligible = visited = 0
    stopped = False

    def check_ancestors(path):
        current = repo
        for part in (None, *path.relative_to(repo).parts):
            if part is not None:
                current /= part
            info = current.lstat()
            if core._is_link_like(info) or not stat.S_ISDIR(info.st_mode):
                raise OSError("source_directory_boundary_changed")

    def interrupted():
        nonlocal stopped
        try:
            return (stopped or (cancel is not None and (cancel() if callable(cancel) else cancel.is_set()))
                    or (deadline is not None and time.monotonic() > deadline))
        except KeyboardInterrupt:
            stopped = True
            return True

    def frontier(path, reason):
        frontiers.append({"path": path.relative_to(repo).as_posix(), "reason": reason,
            "status": "not_enumerated", "impact": "unknown_selected_descendants",
            "alternative": "Review this boundary and retry the same scope; do not narrow the denominator."})

    while pending:
        parent, inherited, depth = pending.pop()
        paused = interrupted()
        if paused or visited >= max_entries:
            frontier(parent, "discovery_interrupted" if paused else "inventory_entry_budget")
            for item, _, _ in pending:
                frontier(item, "discovery_not_reached")
            break
        if depth > max_depth:
            frontier(parent, "directory_depth_budget")
            continue
        try:
            check_ancestors(parent)
            info = parent.lstat()
            if core._is_link_like(info) or not stat.S_ISDIR(info.st_mode):
                frontier(parent, "directory_link_or_type_boundary")
                continue
            # Metadata enumeration is bounded before sorting, including ignored
            # directories. Never materialize an unbounded scandir result.
            children = []
            with os.scandir(parent) as scan:
                for item in scan:
                    if interrupted():
                        frontier(parent, "discovery_interrupted")
                        stopped = True
                        break
                    if visited + len(children) >= max_entries:
                        frontier(parent, "inventory_entry_budget")
                        break
                    children.append(Path(item.path))
            check_ancestors(parent)
            after = parent.lstat()
            if not core._same_file(info, after):
                raise OSError("source_directory_boundary_changed")
        except KeyboardInterrupt:
            frontier(parent, "discovery_interrupted")
            stopped = True
            continue
        except OSError:
            frontier(parent, "directory_access_failed")
            continue
        for path in sorted(children):
            visited += 1
            relative = path.relative_to(repo).as_posix()
            row = {"path": relative, "status": "eligible", "reason": None,
                   "language": languages.get(path.suffix.lower()), "sourceDigest": None}
            try:
                check_ancestors(path.parent)
                info = path.lstat()
            except KeyboardInterrupt:
                row.update(status="interrupted", reason="metadata_read_interrupted",
                    impact="source_structure_or_semantics_not_processed",
                    alternative="Retry the same scope after reviewing the interruption.")
                entries.append(row)
                stopped = True
                continue
            except OSError:
                row.update(status="blocked", reason="metadata_access_failed",
                    impact="source_structure_or_semantics_not_processed",
                    alternative="Restore readable metadata within the selected boundary, then retry the same scope.")
                entries.append(row)
                continue
            if core._is_link_like(info):
                row.update(status="blocked", reason="symlink_or_reparse_point")
                # A link may name a directory. Never follow it to determine size.
                frontier(path, "linked_target_not_enumerated")
            elif stat.S_ISDIR(info.st_mode):
                reason = inherited or ("ignored_directory" if path.name.lower() in core.EXCLUDED_DIRECTORIES else None)
                pending.append((path, reason, depth + 1))
                continue
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                row.update(status="blocked", reason="special_or_hardlinked_file")
            elif inherited:
                row.update(status="excluded", reason=inherited)
            elif protected_file(path, core):
                row.update(status="excluded", reason="protected_nonstructural_file")
            elif row["language"] is None:
                row.update(status="unsupported", reason="unsupported_language")
            elif interrupted():
                row.update(status="interrupted", reason="processing_not_started")
            elif info.st_size > max_source_bytes:
                row.update(status="blocked", reason="source_size_budget")
            elif eligible >= max_files or total + info.st_size > max_total_bytes:
                row.update(status="blocked", reason="source_count_or_byte_budget")
            else:
                try:
                    raw = read_file(path) if read_file else core._safe_read_bytes(path)
                    check_ancestors(path.parent)
                    current = path.lstat()
                    if (core._is_link_like(current) or not stat.S_ISREG(current.st_mode)
                            or current.st_nlink != 1 or not core._same_file(info, current)
                            or core._stable_file_metadata(info) != core._stable_file_metadata(current)):
                        raise OSError("source_changed_during_inventory")
                    if not isinstance(raw, bytes) or len(raw) != current.st_size:
                        raise OSError("source_changed_during_inventory")
                    if len(raw) > max_source_bytes or total + len(raw) > max_total_bytes:
                        row.update(status="blocked", reason="source_size_or_total_byte_budget")
                    else:
                        row["sourceDigest"] = hashlib.sha256(raw).hexdigest()
                        row["bytes"] = len(raw)
                        total += len(raw)
                        eligible += 1
                        try:
                            raw.decode("utf-8", errors="strict")
                        except UnicodeError:
                            row.update(status="blocked", reason="unsupported_source_encoding")
                except KeyboardInterrupt:
                    row.update(status="interrupted", reason="source_read_interrupted")
                    stopped = True
                except (OSError, ValueError, RuntimeError, core.OntologyError):
                    row.update(status="blocked", reason="safe_source_read_failed")
            if row["status"] not in {"eligible", "analyzed"}:
                row.update(impact="source_structure_or_semantics_not_processed",
                    alternative="Review the named cause, provide a safe readable source or supported adapter, then retry this same scope.")
            entries.append(row)
    entries.sort(key=lambda row: row["path"])
    value = {"schemaVersion": 1, "inventoryVersion": VERSION, "sourceRoots": [] if selected == ["."] else selected,
             "entries": entries, "frontiers": sorted(frontiers, key=lambda row: (row["path"], row["reason"]))}
    value["scopeDigest"] = digest(value)
    value["summary"] = summarize(entries, frontiers)
    return value


def finish(value, outcomes):
    """Attach analysis outcomes without changing the discovery identity."""
    result = json.loads(json.dumps(value))
    for row in result["entries"]:
        if row["status"] == "eligible":
            outcome = outcomes.get(row["path"], {"status": "interrupted", "reason": "processing_not_reached"})
            state = outcome.get("status")
            if state not in {"analyzed", "failed", "blocked", "interrupted", "unsupported", "excluded"}:
                state = "failed"
                reason = "invalid_processing_outcome"
            else:
                reason = outcome.get("reason")
            # An analysis receipt cannot replace discovery path/hash/language.
            row.update(status=state, reason=reason)
            if state != "analyzed":
                row.update(impact="source_structure_or_semantics_not_processed",
                    alternative="Review the named cause, provide a safe readable source or supported adapter, then retry this same scope.")
    result["summary"] = summarize(result["entries"], result["frontiers"])
    return result
