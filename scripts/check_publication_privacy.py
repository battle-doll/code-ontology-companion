#!/usr/bin/env python3
"""Read-only, bounded publication privacy preflight; this tool never authorizes publication.

Checks the local publisher manifest, every locally available Git ref through the
shared release scanner, the public GitHub profile, PR titles/bodies, and recorded
PR merge commit identities/messages.
GitHub email privacy controls and the selected OpenAI verified developer identity
are outside these API checks. The result therefore remains HOLD. No private input,
remote identifier, command error, or output path is included in the receipt.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import validate_public_privacy as release_privacy
from privacy_guard import PROFILE_ENV, PrivacyError, ensure_public_safe, load_profile

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = "battle-doll"
REPOSITORY = "battle-doll/code-ontology-companion"
MAX_PRS = 100
MAX_API_CALLS = 2 + 2 * MAX_PRS
MAX_GH_BYTES = 2 * 1024 * 1024
MAX_GIT_BYTES = 16 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 30
REMOTE_BUDGET_SECONDS = 180
COMMIT_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+\Z")
PUBLIC_EMAIL_RE = re.compile(r"(?:\d+\+)?battle-doll@users\.noreply\.github\.com\Z")
VENDOR_EMAILS = {"noreply" + "@github.com", "web-flow" + "@github.com"}
ALLOWED_ENDPOINT_RE = re.compile(
    r"(?:users/battle-doll|repos/battle-doll/code-ontology-companion/"
    r"(?:pulls\?state=all&per_page=100&page=1|pulls/[1-9][0-9]*|commits/[0-9a-f]{40}(?:[0-9a-f]{24})?))\Z")
LOCAL_RULES = {
    "git-name", "git-email", "git-tagger-identity", "invalid-git-identity",
    "invalid-git-ref", "credential", "private-key", "personal-phone",
    "government-identifier", "private-project", "current-home-path",
    "named-home-path", "non-synthetic-email", "known-private-identity",
}


class UnreadableInput(Exception):
    """An intentionally detail-free input or command failure."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes unrecognized arguments, which may be private.
        raise UnreadableInput()


def _command(args: list[str], *, cwd: Path, max_bytes: int,
             timeout: float = COMMAND_TIMEOUT_SECONDS) -> bytes:
    environment = os.environ.copy()
    environment["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(args, cwd=cwd, env=environment, shell=False,
                                capture_output=True, check=False, timeout=timeout)
        if result.returncode or len(result.stdout) > max_bytes:
            raise UnreadableInput()
        return result.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        raise UnreadableInput() from None


class GitHubReader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = 0
        self.deadline = time.monotonic() + REMOTE_BUDGET_SECONDS

    def get(self, endpoint: str):
        if not isinstance(endpoint, str) or not ALLOWED_ENDPOINT_RE.fullmatch(endpoint):
            raise UnreadableInput()
        remaining = self.deadline - time.monotonic()
        if self.calls >= MAX_API_CALLS or remaining <= 0:
            raise UnreadableInput()
        self.calls += 1
        raw = _command(["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint], cwd=self.root,
                       max_bytes=MAX_GH_BYTES,
                       timeout=min(COMMAND_TIMEOUT_SECONDS, remaining))
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise UnreadableInput() from None


def _add(receipt: dict, rule: str, count: int = 1, pr: int | None = None) -> None:
    finding = {"rule": rule, "count": count}
    if pr is not None:
        finding["pr"] = pr
    receipt["findings"].append(finding)


def _new_receipt() -> dict:
    return {
        "checkedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "version": None, "sourceCommit": None, "status": "HOLD",
        "remotePICount": None, "observedRemotePICount": 0,
        "checks": {
            "privateProfile": "UNKNOWN", "manifest": "UNKNOWN", "localGitAllRefs": "UNKNOWN",
            "githubPublicProfile": "UNKNOWN", "recordedPrMergeCommits": "UNKNOWN",
            "githubEmailPrivacyControls": "UNKNOWN", "openaiSelectedVerifiedIdentity": "UNKNOWN",
        },
        "counts": {"inventoryPrs": 0, "checkedMergeCommits": 0, "prsWithoutRecordedMergeCommit": 0,
                   "unknownPrs": 0, "apiCalls": 0},
        "scope": {
            "localGit": "all refs currently available locally; identities, messages and ref names",
            "remoteGit": "at most 100 REST pull request titles/bodies and recorded merge_commit_sha identities/messages",
            "excluded": "unfetched/deleted/provider-internal refs, historical source blobs, issue/comments, CI logs, image pixels, account UI controls and OpenAI identity selection",
            "remotePICount": "observed public identity-policy field violations; not a global privacy guarantee",
        },
        "findings": [
            {"rule": "github-email-privacy-controls-unverified", "count": 1},
            {"rule": "openai-selected-verified-identity-unverified", "count": 1},
        ],
    }


def _manifest(root: Path, receipt: dict, profile: dict) -> None:
    try:
        path = root / ".codex-plugin" / "plugin.json"
        if path.is_symlink() or path.stat().st_size > 64 * 1024:
            raise UnreadableInput()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise UnreadableInput()
        version = value.get("version")
        if isinstance(version, str) and VERSION_RE.fullmatch(version):
            receipt["version"] = version
        else:
            raise UnreadableInput()
        author, interface = value.get("author"), value.get("interface")
        if not isinstance(author, dict) or not isinstance(interface, dict):
            raise UnreadableInput()
        violations = 0
        if author.get("name") != PUBLISHER:
            _add(receipt, "manifest-author-alias"); violations += 1
        if interface.get("developerName") != PUBLISHER:
            _add(receipt, "manifest-developer-alias"); violations += 1
        if "email" in author:
            _add(receipt, "manifest-author-email"); violations += 1
        try:
            ensure_public_safe(value, profile=profile, context_roots=(root,))
        except PrivacyError:
            _add(receipt, "manifest-private-content"); violations += 1
        receipt["checks"]["manifest"] = "FAIL" if violations else "PASS"
    except (OSError, ValueError, RecursionError, UnreadableInput):
        _add(receipt, "manifest-unreadable")


def _git(root: Path, receipt: dict) -> None:
    try:
        raw = _command(["git", "rev-parse", "HEAD"], cwd=root, max_bytes=256)
        commit = raw.decode("ascii").strip()
        if not COMMIT_RE.fullmatch(commit):
            raise UnreadableInput()
        receipt["sourceCommit"] = commit
    except (UnicodeError, UnreadableInput):
        _add(receipt, "source-commit-unreadable")
    previous = release_privacy.subprocess.check_output

    def bounded_check_output(args, **kwargs):
        return _command(args, cwd=Path(kwargs.get("cwd", root)), max_bytes=MAX_GIT_BYTES)

    try:
        # Reuse the existing scanner while bounding and capturing its subprocesses.
        # This CLI is synchronous; restore the shared module function in finally.
        release_privacy.subprocess.check_output = bounded_check_output
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            findings = release_privacy.scan_git_identity(root)
        counts: dict[str, int] = {}
        for finding in findings:
            rule = finding.get("rule")
            rule = rule if rule in LOCAL_RULES else "local-git-private-content"
            counts[rule] = counts.get(rule, 0) + 1
        for rule, count in sorted(counts.items()):
            _add(receipt, rule, count)
        receipt["checks"]["localGitAllRefs"] = "FAIL" if counts else "PASS"
    except (OSError, ValueError, RuntimeError, RecursionError, UnreadableInput, subprocess.SubprocessError):
        _add(receipt, "local-git-unreadable")
    finally:
        release_privacy.subprocess.check_output = previous


def _public_profile(reader: GitHubReader, receipt: dict, profile: dict) -> bool:
    try:
        value = reader.get("users/" + PUBLISHER)
        if (not isinstance(value, dict) or value.get("login") != PUBLISHER
                or "name" not in value or "email" not in value):
            raise UnreadableInput()
        violations = 0
        if value["name"] not in (None, "", PUBLISHER, "배틀돌"):
            _add(receipt, "github-public-name"); violations += 1
        if value["email"] is not None:
            _add(receipt, "github-public-email"); violations += 1
        # Inspect selected fields only: the authenticated /user API is not used.
        try:
            ensure_public_safe([value["name"], value["email"]], profile=profile)
        except PrivacyError:
            if not violations:
                _add(receipt, "github-public-known-identity"); violations += 1
        receipt["checks"]["githubPublicProfile"] = "FAIL" if violations else "PASS"
        receipt["observedRemotePICount"] += violations
        return True
    except (UnreadableInput, TypeError, ValueError):
        _add(receipt, "github-public-profile-unreadable")
        return False


def _identity_pair(value, kind: str, pr: int, receipt: dict, profile: dict) -> None:
    if not isinstance(value, dict) or not all(isinstance(value.get(key), str) and value[key]
                                              for key in ("name", "email")):
        raise UnreadableInput()
    name, email = value["name"], value["email"]
    vendor = name == "GitHub" and email in VENDOR_EMAILS
    name_allowed = name == PUBLISHER or vendor
    email_allowed = bool(PUBLIC_EMAIL_RE.fullmatch(email)) or vendor
    violations = 0
    if not name_allowed:
        _add(receipt, "provider-" + kind + "-name", pr=pr); violations += 1
    if not email_allowed:
        _add(receipt, "provider-" + kind + "-email", pr=pr); violations += 1
    try:
        ensure_public_safe([name, email], profile=profile)
    except PrivacyError as error:
        # Vendor/no-reply allowlisting never overrides a known identity deny rule.
        # The generic runtime email rule is stricter than this Git identity policy.
        if error.category != "personal_email" and not violations:
            _add(receipt, "provider-" + kind + "-private-content", pr=pr); violations += 1
    receipt["observedRemotePICount"] += violations


def _remote_text(value, field: str, pr: int, receipt: dict, profile: dict,
                 *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str):
        raise UnreadableInput()
    try:
        ensure_public_safe(value, profile=profile)
    except PrivacyError:
        _add(receipt, "provider-" + field + "-private-content", pr=pr)
        receipt["observedRemotePICount"] += 1


def _pull_requests(reader: GitHubReader, receipt: dict, profile: dict) -> bool:
    try:
        inventory = reader.get("repos/" + REPOSITORY + "/pulls?state=all&per_page=100&page=1")
        if not isinstance(inventory, list) or len(inventory) > MAX_PRS:
            raise UnreadableInput()
        numbers = [item.get("number") if isinstance(item, dict) else None for item in inventory]
        if (any(type(number) is not int or number < 1 for number in numbers)
                or len(set(numbers)) != len(numbers)):
            raise UnreadableInput()
    except (UnreadableInput, ValueError, TypeError):
        _add(receipt, "github-pr-inventory-unreadable")
        return False
    receipt["counts"]["inventoryPrs"] = len(numbers)
    complete = len(numbers) < MAX_PRS
    if not complete:
        _add(receipt, "github-pr-inventory-cap", MAX_PRS)
    before = receipt["observedRemotePICount"]
    for number in numbers:
        try:
            detail = reader.get("repos/" + REPOSITORY + "/pulls/" + str(number))
            if (not isinstance(detail, dict) or type(detail.get("number")) is not int or detail.get("number") != number
                    or any(field not in detail for field in ("merge_commit_sha", "title", "body"))):
                raise UnreadableInput()
            _remote_text(detail["title"], "pr-title", number, receipt, profile)
            _remote_text(detail["body"], "pr-body", number, receipt, profile, allow_none=True)
            sha = detail["merge_commit_sha"]
            if sha is None:
                receipt["counts"]["prsWithoutRecordedMergeCommit"] += 1
                continue
            if not isinstance(sha, str) or not COMMIT_RE.fullmatch(sha):
                raise UnreadableInput()
            value = reader.get("repos/" + REPOSITORY + "/commits/" + sha)
            if (not isinstance(value, dict) or value.get("sha") != sha
                    or not isinstance(value.get("commit"), dict)):
                raise UnreadableInput()
            _remote_text(value["commit"].get("message"), "commit-message", number, receipt, profile)
            for kind in ("author", "committer"):
                _identity_pair(value["commit"].get(kind), kind, number, receipt, profile)
            receipt["counts"]["checkedMergeCommits"] += 1
        except (UnreadableInput, TypeError, ValueError):
            complete = False
            receipt["counts"]["unknownPrs"] += 1
            _add(receipt, "provider-merge-commit-unreadable", pr=number)
    receipt["checks"]["recordedPrMergeCommits"] = (
        "UNKNOWN" if not complete else "FAIL" if receipt["observedRemotePICount"] > before else "PASS")
    return complete


def check(root: Path = ROOT) -> dict:
    receipt = _new_receipt()
    try:
        profile = load_profile((root,), required=True)
        if not profile["denyNames"] or not profile["denyEmails"]:
            raise PrivacyError("profile_identity_required")
    except (PrivacyError, OSError, ValueError, TypeError, KeyError):
        _add(receipt, "required-private-profile-unavailable")
        return receipt
    receipt["checks"]["privateProfile"] = "PASS"
    _manifest(root, receipt, profile)
    _git(root, receipt)
    reader = GitHubReader(root)
    profile_complete = _public_profile(reader, receipt, profile)
    prs_complete = _pull_requests(reader, receipt, profile)
    receipt["counts"]["apiCalls"] = reader.calls
    if profile_complete and prs_complete:
        receipt["remotePICount"] = receipt["observedRemotePICount"]
    return receipt


def _write_receipt(path: Path, receipt: dict, root: Path = ROOT) -> None:
    """Write an optional local receipt without overwriting source or private policy."""
    temporary = None
    try:
        destination = path.absolute()
        if any(parent.is_symlink() for parent in (destination, *destination.parents)):
            raise UnreadableInput()
        resolved = destination.resolve()
        if resolved == root.resolve() or root.resolve() in resolved.parents:
            raise UnreadableInput()
        selected = os.environ.get(PROFILE_ENV)
        if selected and resolved == Path(selected).resolve():
            raise UnreadableInput()
        if destination.exists() and not destination.is_file():
            raise UnreadableInput()
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".publication-receipt-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(receipt, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
        os.replace(temporary, destination)
    except (OSError, ValueError, RuntimeError, UnreadableInput):
        raise UnreadableInput() from None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    receipt = None
    try:
        parser = SafeParser(prog="check_publication_privacy.py", description=__doc__)
        parser.add_argument("--output", type=Path, help="Optional local sanitized JSON receipt, outside the source tree.")
        args = parser.parse_args(argv)
        receipt = check()
        if args.output is not None:
            _write_receipt(args.output, receipt)
    except KeyboardInterrupt:
        receipt = receipt or _new_receipt()
        _add(receipt, "preflight-interrupted")
    except Exception:
        # No exception text or traceback: dependencies may contain private values.
        receipt = receipt or _new_receipt()
        _add(receipt, "preflight-unreadable-input")
    print(json.dumps(receipt, ensure_ascii=True, indent=2))
    return 1  # HOLD never grants upload, PR creation, or account-setting approval.


if __name__ == "__main__":
    raise SystemExit(main())
