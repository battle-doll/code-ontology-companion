from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_publication_privacy as preflight
from privacy_guard import PROFILE_ENV, PrivacyError, build_profile


SYNTHETIC_NAME = "FictionPersonZQ"
SYNTHETIC_EMAIL = "fiction-person" + "@" + "synthetic-provider.org"
COMMIT = "b" * 40
MERGE_COMMIT = "c" * 40
PROFILE = build_profile([SYNTHETIC_NAME], [SYNTHETIC_EMAIL], key=b"x" * 32)


def alias_commit():
    return {"sha": MERGE_COMMIT, "commit": {"message": "Synthetic merge", "author": {"name": "battle-doll", "email": "123+battle-doll@users.noreply.github.com"},
                       "committer": {"name": "GitHub", "email": "noreply" + "@github.com"}}}


def pr_detail(number, sha):
    return {"number": number, "merge_commit_sha": sha, "title": "Synthetic pull request", "body": None}


class PublicationPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        (self.root / ".codex-plugin").mkdir(parents=True)
        self.manifest = {"version": "0.8.3", "author": {"name": "battle-doll"},
                         "interface": {"developerName": "battle-doll"}}
        self.write_manifest()

    def write_manifest(self):
        (self.root / ".codex-plugin" / "plugin.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def run_check(self, responses=None, local_findings=None):
        if responses is None:
            responses = [{"login": "battle-doll", "name": None, "email": None}, []]
        with (mock.patch.object(preflight, "load_profile", return_value=PROFILE),
              mock.patch.object(preflight, "_command", return_value=(COMMIT + "\n").encode()),
              mock.patch.object(preflight.release_privacy, "scan_git_identity", return_value=local_findings or []) as scan,
              mock.patch.object(preflight.GitHubReader, "get", side_effect=responses) as get):
            receipt = preflight.check(self.root)
        return receipt, scan, get

    def assert_sanitized(self, receipt, values=(SYNTHETIC_NAME, SYNTHETIC_EMAIL)):
        text = json.dumps(receipt)
        for value in values:
            self.assertNotIn(value, text)
        for finding in receipt["findings"]:
            self.assertLessEqual(set(finding), {"rule", "pr", "count"})

    def test_good_machine_snapshot_always_holds_unverified_ui_identity(self):
        receipt, scan, get = self.run_check()
        self.assertEqual("HOLD", receipt["status"])
        self.assertEqual(0, receipt["remotePICount"])
        for stage in ("privateProfile", "manifest", "localGitAllRefs", "githubPublicProfile", "recordedPrMergeCommits"):
            self.assertEqual("PASS", receipt["checks"][stage])
        self.assertEqual("UNKNOWN", receipt["checks"]["githubEmailPrivacyControls"])
        self.assertEqual("UNKNOWN", receipt["checks"]["openaiSelectedVerifiedIdentity"])
        self.assertEqual({"github-email-privacy-controls-unverified", "openai-selected-verified-identity-unverified"},
                         {finding["rule"] for finding in receipt["findings"]})
        scan.assert_called_once_with(self.root)
        self.assertEqual(["users/battle-doll", "repos/battle-doll/code-ontology-companion/pulls?state=all&per_page=100&page=1"],
                         [call.args[0] for call in get.call_args_list])
        self.assertIn("provider-internal", receipt["scope"]["excluded"])
        self.assert_sanitized(receipt)

    def test_required_profile_unreadable_stops_all_remote_commands(self):
        for failure in (PrivacyError("profile_missing"), OSError(SYNTHETIC_EMAIL)):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(preflight, "load_profile", side_effect=failure), mock.patch.object(preflight, "_command") as command:
                    receipt = preflight.check(self.root)
                command.assert_not_called()
                self.assertIsNone(receipt["remotePICount"])
                self.assert_sanitized(receipt)

    def test_profile_requires_name_and_email_deny_lists(self):
        for profile in (build_profile([], [SYNTHETIC_EMAIL]), build_profile([SYNTHETIC_NAME], [])):
            with mock.patch.object(preflight, "load_profile", return_value=profile), mock.patch.object(preflight.GitHubReader, "get") as get:
                receipt = preflight.check(self.root)
            get.assert_not_called()
            self.assertIn("required-private-profile-unavailable", {finding["rule"] for finding in receipt["findings"]})

    def test_manifest_only_allows_public_alias_and_no_email(self):
        self.manifest["author"] = {"name": SYNTHETIC_NAME, "email": SYNTHETIC_EMAIL}
        self.manifest["interface"]["developerName"] = SYNTHETIC_NAME
        self.write_manifest()
        receipt, _, _ = self.run_check()
        self.assertEqual("FAIL", receipt["checks"]["manifest"])
        self.assertTrue({"manifest-author-alias", "manifest-author-email", "manifest-developer-alias"}.issubset(
            {finding["rule"] for finding in receipt["findings"]}))
        self.assert_sanitized(receipt)

    def test_invalid_manifest_version_never_enters_receipt(self):
        self.manifest["version"] = SYNTHETIC_EMAIL
        self.write_manifest()
        receipt, _, _ = self.run_check()
        self.assertIsNone(receipt["version"])
        self.assertEqual("UNKNOWN", receipt["checks"]["manifest"])
        self.assert_sanitized(receipt)

    def test_private_public_profile_fields_are_counted_without_echo(self):
        receipt, _, _ = self.run_check([{"login": "battle-doll", "name": SYNTHETIC_NAME, "email": SYNTHETIC_EMAIL}, []])
        self.assertEqual(2, receipt["remotePICount"])
        self.assertEqual("FAIL", receipt["checks"]["githubPublicProfile"])
        self.assert_sanitized(receipt)

    def test_missing_public_profile_fields_are_unknown(self):
        receipt, _, _ = self.run_check([{"login": "battle-doll", "name": None}, []])
        self.assertIsNone(receipt["remotePICount"])
        self.assertEqual("UNKNOWN", receipt["checks"]["githubPublicProfile"])

    def test_allowed_public_display_aliases(self):
        for name in (None, "", "battle-doll", "배틀돌"):
            with self.subTest(name=name):
                receipt, _, _ = self.run_check([{"login": "battle-doll", "name": name, "email": None}, []])
                self.assertEqual(0, receipt["remotePICount"])
                self.assertEqual("PASS", receipt["checks"]["githubPublicProfile"])

    def test_pr_text_and_commit_message_use_known_identity_guard(self):
        detail = pr_detail(9, MERGE_COMMIT)
        detail["title"], detail["body"] = SYNTHETIC_NAME, SYNTHETIC_EMAIL
        commit = alias_commit()
        commit["commit"]["message"] = "Merge " + SYNTHETIC_NAME
        receipt, _, get = self.run_check([
            {"login": "battle-doll", "name": None, "email": None}, [{"number": 9}], detail, commit])
        self.assertEqual(3, receipt["remotePICount"])
        self.assertEqual(4, get.call_count)
        self.assertEqual("FAIL", receipt["checks"]["recordedPrMergeCommits"])
        self.assertTrue({"provider-pr-title-private-content", "provider-pr-body-private-content",
                         "provider-commit-message-private-content"}.issubset(
            {finding["rule"] for finding in receipt["findings"]}))
        self.assert_sanitized(receipt)

    def test_missing_commit_message_is_unknown(self):
        commit = alias_commit()
        del commit["commit"]["message"]
        receipt, _, _ = self.run_check([
            {"login": "battle-doll", "name": None, "email": None}, [{"number": 1}], pr_detail(1, MERGE_COMMIT), commit])
        self.assertIsNone(receipt["remotePICount"])
        self.assertEqual("UNKNOWN", receipt["checks"]["recordedPrMergeCommits"])

    def test_recorded_merge_author_committer_are_checked(self):
        commit = alias_commit()
        commit["commit"]["author"] = {"name": SYNTHETIC_NAME, "email": SYNTHETIC_EMAIL}
        responses = [{"login": "battle-doll", "name": None, "email": None}, [{"number": 7}],
                     pr_detail(7, MERGE_COMMIT), commit]
        receipt, _, get = self.run_check(responses)
        self.assertEqual(2, receipt["remotePICount"])
        self.assertEqual(1, receipt["counts"]["checkedMergeCommits"])
        self.assertEqual("FAIL", receipt["checks"]["recordedPrMergeCommits"])
        provider = [finding for finding in receipt["findings"] if finding["rule"].startswith("provider-")]
        self.assertEqual({7}, {finding["pr"] for finding in provider})
        self.assertEqual(4, get.call_count)
        self.assert_sanitized(receipt, (SYNTHETIC_NAME, SYNTHETIC_EMAIL, MERGE_COMMIT))

    def test_alias_and_exact_vendor_identity_are_allowed(self):
        for vendor in preflight.VENDOR_EMAILS:
            commit = alias_commit()
            commit["commit"]["committer"]["email"] = vendor
            receipt, _, _ = self.run_check([
                {"login": "battle-doll", "name": "battle-doll", "email": None}, [{"number": 1}],
                pr_detail(1, MERGE_COMMIT), commit])
            self.assertEqual(0, receipt["remotePICount"])
            self.assertEqual("PASS", receipt["checks"]["recordedPrMergeCommits"])

    def test_vendor_address_with_nonvendor_name_is_rejected(self):
        commit = alias_commit()
        commit["commit"]["committer"]["name"] = SYNTHETIC_NAME
        receipt, _, _ = self.run_check([
            {"login": "battle-doll", "name": None, "email": None}, [{"number": 1}],
            pr_detail(1, MERGE_COMMIT), commit])
        self.assertEqual(2, receipt["remotePICount"])
        self.assert_sanitized(receipt)

    def test_known_identity_deny_rule_overrides_allowed_alias(self):
        profile = build_profile(["battle-doll"], [SYNTHETIC_EMAIL])
        receipt = preflight._new_receipt()
        preflight._identity_pair(alias_commit()["commit"]["author"], "author", 1, receipt, profile)
        self.assertEqual(1, receipt["observedRemotePICount"])
        self.assertEqual("provider-author-private-content", receipt["findings"][-1]["rule"])

    def test_missing_or_malicious_sha_is_unknown_without_endpoint_interpolation(self):
        for detail in ({"number": 2}, pr_detail(2, SYNTHETIC_EMAIL)):
            receipt, _, get = self.run_check([
                {"login": "battle-doll", "name": None, "email": None}, [{"number": 2}], detail])
            self.assertIsNone(receipt["remotePICount"])
            self.assertEqual(1, receipt["counts"]["unknownPrs"])
            self.assertEqual(3, get.call_count)
            self.assert_sanitized(receipt)

    def test_pr_without_recorded_merge_commit_has_explicit_count(self):
        receipt, _, get = self.run_check([
            {"login": "battle-doll", "name": None, "email": None}, [{"number": 8}],
            pr_detail(8, None)])
        self.assertEqual(1, receipt["counts"]["prsWithoutRecordedMergeCommit"])
        self.assertEqual(0, receipt["counts"]["checkedMergeCommits"])
        self.assertEqual(3, get.call_count)

    def test_100_pr_cap_limits_calls_and_does_not_claim_complete_remote_scan(self):
        responses = [{"login": "battle-doll", "name": None, "email": None},
                     [{"number": number} for number in range(1, 101)]]
        for number in range(1, 101):
            responses.extend([pr_detail(number, MERGE_COMMIT), alias_commit()])
        receipt, _, get = self.run_check(responses)
        self.assertEqual(202, get.call_count)
        self.assertEqual(100, receipt["counts"]["checkedMergeCommits"])
        self.assertEqual("UNKNOWN", receipt["checks"]["recordedPrMergeCommits"])
        self.assertIsNone(receipt["remotePICount"])
        self.assertIn("github-pr-inventory-cap", {finding["rule"] for finding in receipt["findings"]})

    def test_inventory_invalid_or_duplicate_numbers_fail_closed(self):
        for inventory in ([{"number": True}], [{"number": 1}, {"number": 1}], [{"number": SYNTHETIC_EMAIL}]):
            receipt, _, get = self.run_check([{"login": "battle-doll", "name": None, "email": None}, inventory])
            self.assertEqual(2, get.call_count)
            self.assertIsNone(receipt["remotePICount"])
            self.assert_sanitized(receipt)

    def test_local_scanner_findings_drop_raw_paths_and_lines(self):
        receipt, _, _ = self.run_check(local_findings=[
            {"rule": "git-name", "file": SYNTHETIC_NAME, "line": 100},
            {"rule": "git-name", "file": SYNTHETIC_EMAIL, "line": 101},
            {"rule": SYNTHETIC_EMAIL, "file": SYNTHETIC_NAME}])
        self.assertEqual("FAIL", receipt["checks"]["localGitAllRefs"])
        self.assertEqual({"rule": "git-name", "count": 2}, next(
            finding for finding in receipt["findings"] if finding["rule"] == "git-name"))
        self.assert_sanitized(receipt)

    def test_local_scanner_output_is_captured_and_override_restored(self):
        previous = subprocess.check_output
        receipt = preflight._new_receipt()
        def scanner(root):
            print(SYNTHETIC_NAME)
            print(SYNTHETIC_EMAIL, file=sys.stderr)
            release_output = preflight.release_privacy.subprocess.check_output(["git", "log", "--all"], cwd=root)
            self.assertEqual(b"bounded", release_output)
            return []
        stdout, stderr = io.StringIO(), io.StringIO()
        with (mock.patch.object(preflight, "_command", side_effect=[COMMIT.encode(), b"bounded"]),
              mock.patch.object(preflight.release_privacy, "scan_git_identity", side_effect=scanner),
              contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr)):
            preflight._git(self.root, receipt)
        self.assertIs(previous, subprocess.check_output)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_command_uses_capture_get_and_never_echoes_failure(self):
        reader = preflight.GitHubReader(self.root)
        with mock.patch.object(preflight.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", SYNTHETIC_EMAIL.encode())) as run:
            with self.assertRaises(preflight.UnreadableInput) as failure:
                reader.get("users/battle-doll")
        self.assertEqual("", str(failure.exception))
        self.assertEqual(["gh", "api", "--hostname", "github.com", "--method", "GET", "users/battle-doll"], run.call_args.args[0])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual("1", run.call_args.kwargs["env"]["GH_PROMPT_DISABLED"])

    def test_reader_rejects_output_size_malformed_json_timeout_and_budget(self):
        reader = preflight.GitHubReader(self.root)
        for output in (b"x" * (preflight.MAX_GH_BYTES + 1), SYNTHETIC_EMAIL.encode()):
            with mock.patch.object(preflight.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, b"")):
                with self.assertRaises(preflight.UnreadableInput):
                    reader.get("users/battle-doll")
        with mock.patch.object(preflight.subprocess, "run", side_effect=subprocess.TimeoutExpired(SYNTHETIC_EMAIL, 30)):
            with self.assertRaises(preflight.UnreadableInput):
                reader.get("users/battle-doll")
        reader.calls = preflight.MAX_API_CALLS
        with mock.patch.object(preflight.subprocess, "run") as run:
            with self.assertRaises(preflight.UnreadableInput):
                reader.get("users/battle-doll")
        run.assert_not_called()

    def test_deadline_and_mismatched_commit_fail_closed(self):
        reader = preflight.GitHubReader(self.root)
        reader.deadline = 0
        with mock.patch.object(preflight.subprocess, "run") as run:
            with self.assertRaises(preflight.UnreadableInput):
                reader.get("users/battle-doll")
        run.assert_not_called()
        commit = alias_commit()
        commit["sha"] = "d" * 40
        receipt, _, _ = self.run_check([
            {"login": "battle-doll", "name": None, "email": None}, [{"number": 1}],
            pr_detail(1, MERGE_COMMIT), commit])
        self.assertIsNone(receipt["remotePICount"])
        self.assertEqual(1, receipt["counts"]["unknownPrs"])

    def test_main_unknown_arguments_and_failures_never_echo_private_values(self):
        for argv in (["--verified", SYNTHETIC_EMAIL], ["--repository", SYNTHETIC_NAME]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = preflight.main(argv)
            self.assertEqual(1, result)
            self.assertEqual("", stderr.getvalue())
            self.assert_sanitized(json.loads(stdout.getvalue()))
        with mock.patch.object(preflight, "check", side_effect=RuntimeError(SYNTHETIC_EMAIL)), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(1, preflight.main([]))
        self.assert_sanitized(json.loads(stdout.getvalue()))

    def test_optional_receipt_is_local_sanitized_and_private(self):
        receipt, _, _ = self.run_check()
        destination = Path(self.temporary.name).resolve() / "receipt.json"
        preflight._write_receipt(destination, receipt, self.root)
        self.assertEqual(receipt, json.loads(destination.read_text()))
        self.assert_sanitized(json.loads(destination.read_text()))
        if os.name != "nt":
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)
        for unsafe in (self.root / "receipt.json", self.root / ".codex-plugin" / "plugin.json"):
            with self.assertRaises(preflight.UnreadableInput):
                preflight._write_receipt(unsafe, receipt, self.root)
        with mock.patch.dict(os.environ, {PROFILE_ENV: str(destination)}):
            with self.assertRaises(preflight.UnreadableInput):
                preflight._write_receipt(destination, receipt, self.root)

    def test_no_remote_mutating_command_or_bypass_flag_is_available(self):
        text = (Path(preflight.__file__)).read_text()
        self.assertNotIn('add_argument("--verified"', text)
        self.assertNotIn('add_argument("--repository"', text)
        self.assertEqual("battle-doll/code-ontology-companion", preflight.REPOSITORY)

    def test_reader_rejects_other_repositories_hosts_or_endpoints(self):
        reader = preflight.GitHubReader(self.root)
        with mock.patch.object(preflight, "_command") as command:
            for endpoint in ("user", "users/other-user", "repos/other-user/project/pulls",
                             "https://example.com/", "repos/battle-doll/code-ontology-companion/issues/1"):
                with self.assertRaises(preflight.UnreadableInput):
                    reader.get(endpoint)
        command.assert_not_called()
        self.assertEqual(0, reader.calls)


if __name__ == "__main__":
    unittest.main()
