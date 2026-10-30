"""Neutral ACL-validation cache holdouts; no live workspace/profile is read."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import pipeline_acl as acl


@unittest.skipIf(os.name == "nt", "POSIX fixtures; native Windows validation is separate")
class AclValidationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.path = self.workspace / "access.json"
        self.guard = acl.companion.privacy_guard
        self.profile = self.guard.build_profile(["Synthetic Confidential Marker"],
            ["synthetic-private@neutral-fixture.test"], key=b"c" * 32)
        self.profile_path = self.base / "synthetic-profile.json"
        self.write_profile(self.profile)
        self.env = mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "local-owner",
            self.guard.PROFILE_ENV: str(self.profile_path)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.value = {"schemaVersion": 1, "revision": 7, "principals": {
            "local-owner": {"actions": sorted(acl.ACTIONS), "snapshots": ["*"]},
            "reader": {"actions": ["read_policy"], "snapshots": ["one"]}}}
        self.write(self.value)
        acl._VALIDATION_CACHE.clear()
        self.addCleanup(acl._VALIDATION_CACHE.clear)

    def write(self, value, path=None):
        path = path or self.path
        path.write_bytes(acl.companion._json_bytes(value))
        path.chmod(0o600)

    def write_profile(self, value):
        self.profile_path.write_text(json.dumps(value), encoding="utf-8")
        self.profile_path.chmod(0o600)

    def allow(self):
        return acl.authorize(self.workspace, "read_policy", "one")

    def denied(self, callback=None):
        with self.assertRaises(acl.AccessDenied):
            (callback or self.allow)()

    def test_warm_hit_keeps_full_reads_metadata_sha_and_fresh_profile(self):
        raw = self.path.read_bytes()
        original_sha = hashlib.sha256
        digests = []
        def observed_sha(data=b""):
            digests.append(data)
            return original_sha(data)
        with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate, \
             mock.patch.object(self.guard, "ensure_public_safe", wraps=self.guard.ensure_public_safe) as privacy, \
             mock.patch.object(self.guard, "load_profile", wraps=self.guard.load_profile) as profile, \
             mock.patch.object(self.guard, "_check_private_file_metadata", wraps=self.guard._check_private_file_metadata) as metadata, \
             mock.patch.object(acl.os, "open", wraps=os.open) as opened, \
             mock.patch.object(acl.hashlib, "sha256", side_effect=observed_sha):
            first = acl._read(self.workspace)
            self.assertEqual(first, acl._read(self.workspace))
            self.assertEqual(validate.call_count, 1)
            self.assertEqual(privacy.call_count, 1)
            self.assertEqual(profile.call_count, 2)
            self.assertEqual(sum(call.args[0] == self.path for call in opened.call_args_list), 2)
            self.assertEqual(sum(data == raw for data in digests), 2)
            self.assertGreaterEqual(metadata.call_count, 14)

    def test_fresh_principal_action_snapshot_and_visibility(self):
        self.allow()
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.assertTrue(acl.visible(self.workspace))
            self.assertEqual(self.allow()["decision"], "allow")
            for action, snapshot in (("read_evidence", "one"), ("read_policy", "two"),
                                     ("read_policy", None), ("unknown", "one")):
                self.denied(lambda: acl.authorize(self.workspace, action, snapshot))
        for principal in ("unknown", "../owner"):
            with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: principal}):
                self.denied()
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "unknown"}):
            self.assertFalse(acl.visible(self.workspace))

    def test_same_revision_revoke_and_copy_are_immediate(self):
        self.allow()
        revoked = copy.deepcopy(self.value)
        revoked["principals"]["reader"]["actions"] = []
        self.write(revoked)
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.denied()
        other = self.workspace / "replacement.json"
        self.write(self.value, other)
        os.replace(other, self.path)
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.assertEqual(self.allow()["revision"], 7)

    def test_identical_bytes_replacement_requires_cold_validation(self):
        self.allow()
        previous = self.path.stat().st_ino
        replacement = self.workspace / "replacement.json"
        self.write(self.value, replacement)
        os.replace(replacement, self.path)
        self.assertNotEqual(self.path.stat().st_ino, previous)
        with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
            self.allow()
            self.assertEqual(validate.call_count, 1)

    def test_in_place_same_size_rewrite_with_restored_mtime_is_not_a_hit(self):
        self.allow()
        info = self.path.stat()
        changed = copy.deepcopy(self.value)
        changed["principals"]["reader"]["snapshots"] = ["two"]
        self.write(changed)
        os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        final = self.path.stat()
        self.assertEqual((final.st_ino, final.st_size, final.st_mtime_ns),
                         (info.st_ino, info.st_size, info.st_mtime_ns))
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.denied()
            self.assertEqual(acl.authorize(self.workspace, "read_policy", "two")["revision"], 7)

    def test_raw_sha_detects_change_even_with_synthetically_identical_metadata(self):
        self.allow()
        original = self.path.stat()
        changed = copy.deepcopy(self.value)
        changed["principals"]["reader"]["snapshots"] = ["two"]
        self.write(changed)
        os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns))
        real_fstat = os.fstat
        real_metadata = acl.companion.core._stable_file_metadata
        class StatView:
            def __init__(self, info):
                self.info = info
                self.st_ctime = original.st_ctime
                self.st_ctime_ns = original.st_ctime_ns
            def __getattr__(self, name):
                return getattr(self.info, name)
        def frozen_fstat(descriptor):
            info = real_fstat(descriptor)
            return StatView(info) if info.st_ino == original.st_ino else info
        def frozen_metadata(info):
            return real_metadata(original if info.st_ino == original.st_ino else info)
        with mock.patch.object(acl.os, "fstat", side_effect=frozen_fstat), \
             mock.patch.object(acl.companion.core, "_stable_file_metadata", side_effect=frozen_metadata), \
             mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.denied()
            self.assertEqual(acl.authorize(self.workspace, "read_policy", "two")["revision"], 7)

    def test_distinct_workspace_paths_never_share_validation(self):
        self.allow()
        other = self.base / "other"
        other.mkdir(mode=0o700)
        self.write(self.value, other / "access.json")
        with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
            acl.authorize(other, "read_policy", "one")
            self.assertEqual(validate.call_count, 1)
        self.assertEqual(len(acl._VALIDATION_CACHE), 2)

    def test_renamed_workspace_same_file_identity_is_a_different_key(self):
        self.allow()
        original = self.path.stat()
        moved = self.base / "moved-workspace"
        self.workspace.rename(moved)
        self.assertEqual((moved / "access.json").stat().st_ino, original.st_ino)
        with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
            acl.authorize(moved, "read_policy", "one")
            self.assertEqual(validate.call_count, 1)

    def test_returned_objects_cannot_pollute_the_cache(self):
        value = acl._read(self.workspace)
        value["principals"]["reader"]["actions"].append("read_evidence")
        value["revision"] = 99
        cached = acl._read(self.workspace)
        cached["principals"].clear()
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.denied(lambda: acl.authorize(self.workspace, "read_evidence", "one"))
            self.assertEqual(self.allow()["revision"], 7)

    def test_profile_names_emails_key_and_same_object_mutation_miss(self):
        shared = copy.deepcopy(self.profile)
        with mock.patch.object(self.guard, "load_profile", return_value=shared):
            self.allow()
            for field in ("denyNames", "denyEmails", "key"):
                new = self.guard.build_profile(["Another Fictional Identity"],
                    ["another@neutral-fixture.test"], key=b"d" * 32)
                shared[field] = copy.deepcopy(new[field])
                with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
                    self.allow()
                    self.assertEqual(validate.call_count, 1)

    def test_same_private_profile_copy_binds_fingerprint_and_validation(self):
        shared = copy.deepcopy(self.profile)
        real = acl._validate
        def mutate_external(value, *, private_profile=None):
            shared.update(self.guard.build_profile(["local-owner"], [], key=b"e" * 32))
            self.assertNotEqual(shared, private_profile)
            return real(value, private_profile=private_profile)
        with mock.patch.object(self.guard, "load_profile", return_value=shared):
            with mock.patch.object(acl, "_validate", side_effect=mutate_external):
                self.allow()
            self.denied()

    def test_deny_profile_change_rejects_warm_policy_without_caching_failure(self):
        self.allow()
        count = len(acl._VALIDATION_CACHE)
        self.write_profile(self.guard.build_profile(["local-owner"], [], key=b"f" * 32))
        for _ in range(2):
            self.denied()
            self.assertEqual(len(acl._VALIDATION_CACHE), count)

    def test_unsafe_or_invalid_profile_is_checked_even_when_warm(self):
        self.allow()
        count = len(acl._VALIDATION_CACHE)
        self.profile_path.chmod(0o644)
        self.denied()
        self.profile_path.chmod(0o600)
        self.profile_path.write_text("{}", encoding="utf-8")
        self.denied()
        self.assertEqual(len(acl._VALIDATION_CACHE), count)

    def test_profile_path_change_loads_new_policy(self):
        self.allow()
        other = self.base / "other-profile.json"
        self.write(self.guard.build_profile(["local-owner"], [], key=b"g" * 32), other)
        with mock.patch.dict(os.environ, {self.guard.PROFILE_ENV: str(other)}):
            self.denied()

    def test_none_profile_bypasses_cache_and_retains_autoload(self):
        with mock.patch.dict(os.environ, {self.guard.PROFILE_ENV: ""}):
            with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
                self.allow()
                self.allow()
                self.assertEqual(validate.call_count, 2)
            self.assertEqual(len(acl._VALIDATION_CACHE), 0)
        with mock.patch.object(self.guard, "load_profile", side_effect=[None,
                self.guard.build_profile(["local-owner"], [], key=b"h" * 32)]):
            self.denied()
        self.assertEqual(len(acl._VALIDATION_CACHE), 0)

    def test_profile_not_stored_in_cache(self):
        self.allow()
        stored = repr(acl._VALIDATION_CACHE)
        for material in (self.profile["key"], self.profile["denyNames"][0]["digest"],
                         self.profile["denyEmails"][0]["digest"]):
            self.assertNotIn(material, stored)

    def test_unsafe_mode_owner_and_metadata_failure_are_not_bypassed(self):
        self.allow()
        self.path.chmod(0o755)
        self.denied()
        self.path.chmod(0o600)
        with mock.patch.object(self.guard.os, "getuid", return_value=os.getuid() + 1):
            self.denied()
        with mock.patch.object(self.guard, "_check_private_file_metadata",
                side_effect=self.guard.PrivacyError("profile_permissions")):
            self.denied()

    def test_symlink_and_hardlink_are_rejected_when_warm(self):
        self.allow()
        other = self.workspace / "other.json"
        os.link(self.path, other)
        self.denied()
        other.unlink()
        self.path.rename(other)
        self.path.symlink_to(other)
        self.denied()

    def test_parent_link_like_reparse_boundary_is_checked_when_warm(self):
        self.allow()
        original = acl.companion._is_link_like
        def linked(info):
            return original(info) or info.st_ino == self.workspace.parent.stat().st_ino
        with mock.patch.object(acl.companion, "_is_link_like", side_effect=linked):
            self.denied()

    def test_read_race_is_rejected_before_a_warm_hit(self):
        self.allow()
        real = os.fstat
        seen = []
        def changed(descriptor):
            result = real(descriptor)
            if result.st_ino == self.path.stat().st_ino:
                seen.append(result)
                if len(seen) == 2:
                    altered = copy.deepcopy(self.value)
                    altered["revision"] = 8
                    self.write(altered)
                    return real(descriptor)
            return result
        with mock.patch.object(acl.os, "fstat", side_effect=changed):
            self.denied()

    def test_windows_dacl_is_checked_twice_per_read_and_changes_deny(self):
        self.allow()
        class WindowsOs:
            name = "nt"
            def __getattr__(self, name):
                return getattr(os, name)
        with mock.patch.object(acl, "os", WindowsOs()), \
             mock.patch.object(self.guard, "_windows_profile_security", return_value=b"synthetic-safe") as security:
            self.allow()
            self.allow()
            self.assertEqual(security.call_count, 4)
            security.return_value = b"synthetic-safe-changed"
            with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
                self.allow()
                self.assertEqual(validate.call_count, 1)
            security.side_effect = [b"synthetic-safe", b"synthetic-changed"]
            self.denied()
            security.side_effect = self.guard.PrivacyError("profile_permissions")
            self.denied()

    def test_failures_are_never_inserted_and_can_recover(self):
        invalid = ({}, {**self.value, "schemaVersion": 2}, {**self.value, "revision": 0},
                   {**self.value, "principals": {}},
                   {**self.value, "principals": {"reader": {"actions": ["unknown"], "snapshots": ["*"]}}})
        for value in invalid:
            self.write(value)
            for _ in range(2):
                self.denied()
            self.assertEqual(len(acl._VALIDATION_CACHE), 0)
        for raw in (b"{", b"\xff", b" " * (acl.MAX_ACL_BYTES + 1), b""):
            self.path.write_bytes(raw)
            self.denied()
            self.assertEqual(len(acl._VALIDATION_CACHE), 0)
        self.write(self.value)
        self.allow()
        self.assertEqual(len(acl._VALIDATION_CACHE), 1)

    def test_validation_schema_version_is_part_of_key(self):
        self.allow()
        with mock.patch.object(acl, "_VALIDATION_VERSION", acl._VALIDATION_VERSION + 1), \
             mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
            self.allow()
            self.assertEqual(validate.call_count, 1)

    def test_lru_is_bounded_and_evicted_policy_is_revalidated(self):
        workspaces = []
        for index in range(acl._VALIDATION_CACHE_LIMIT + 1):
            workspace = self.base / ("workspace-" + str(index))
            workspace.mkdir(mode=0o700)
            self.write(self.value, workspace / "access.json")
            acl.authorize(workspace, "read_policy", "one")
            workspaces.append(workspace)
        self.assertEqual(len(acl._VALIDATION_CACHE), acl._VALIDATION_CACHE_LIMIT)
        with mock.patch.object(acl, "_validate", wraps=acl._validate) as validate:
            acl.authorize(workspaces[-1], "read_policy", "one")
            self.assertEqual(validate.call_count, 0)
            acl.authorize(workspaces[0], "read_policy", "one")
            self.assertEqual(validate.call_count, 1)
        self.assertEqual(len(acl._VALIDATION_CACHE), acl._VALIDATION_CACHE_LIMIT)

    def test_initialize_update_and_policy_digest_stay_equivalent(self):
        before = self.allow()
        self.assertEqual(before["policyDigest"], hashlib.sha256(acl.companion._json_bytes(self.value)).hexdigest())
        acl.update_access(self.workspace, "reader", [], ["one"])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            self.denied()
        self.assertEqual(self.allow()["revision"], 8)
        workspace = self.base / "initialized"
        workspace.mkdir(mode=0o700)
        initialized = acl.initialize_access(workspace)
        self.assertEqual(initialized["revision"], 1)
        self.assertEqual(acl.authorize(workspace, "manage_knowledge")["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
