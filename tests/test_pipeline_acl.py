from __future__ import annotations
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import pipeline_acl as acl


@unittest.skipIf(os.name == "nt", "Requires a native Windows owner-only workspace fixture")
class KnowledgeAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "local-owner"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_missing_policy_is_not_owner_bypass(self):
        with self.assertRaises(acl.AccessDenied):
            acl.authorize(self.workspace, "read_policy")

    def test_legacy_grants_do_not_gain_knowledge_approval(self):
        acl.initialize_access(self.workspace)
        legacy = sorted(acl.ACTIONS - {"manage_knowledge"})
        acl.update_access(self.workspace, "local-owner", legacy, ["*"])
        with self.assertRaises(acl.AccessDenied):
            acl.authorize(self.workspace, "manage_knowledge", "sealed-1")
        acl.authorize(self.workspace, "read_policy", "sealed-1")
        acl.update_access(self.workspace, "local-owner", sorted(acl.ACTIONS), ["*"])
        self.assertEqual(acl.authorize(self.workspace, "manage_knowledge", "sealed-1")["decision"], "allow")

    def test_default_owner_and_policy_only_reader(self):
        acl.initialize_access(self.workspace)
        acl.update_access(self.workspace, "policy-reader", ["read_policy"], ["sealed-1"])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "policy-reader"}):
            self.assertEqual(acl.authorize(self.workspace, "read_policy", "sealed-1")["decision"], "allow")
            for action, snapshot in (("export_html", "sealed-1"), ("read_structure", "sealed-1"),
                                     ("read_evidence", "sealed-1"), ("read_policy", "sealed-2"), ("read_policy", None)):
                with self.assertRaises(acl.AccessDenied):
                    acl.authorize(self.workspace, action, snapshot)
            with self.assertRaises(acl.AccessDenied):
                acl.update_access(self.workspace, "policy-reader", list(acl.ACTIONS), ["*"])

    def test_revocation_applies_on_next_read_and_retains_admin(self):
        acl.initialize_access(self.workspace)
        acl.update_access(self.workspace, "reader", ["read_structure"], ["*"])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            acl.authorize(self.workspace, "read_structure", "one")
        acl.update_access(self.workspace, "reader", [], ["*"])
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "reader"}):
            with self.assertRaises(acl.AccessDenied):
                acl.authorize(self.workspace, "read_structure", "one")
        with self.assertRaises(acl.AccessDenied):
            acl.update_access(self.workspace, "local-owner", [], ["*"])

    def test_unknown_principal_invalid_grants_and_permissions_fail_closed(self):
        acl.initialize_access(self.workspace)
        with mock.patch.dict(os.environ, {acl.PRINCIPAL_ENV: "unknown"}):
            with self.assertRaises(acl.AccessDenied):
                acl.authorize(self.workspace, "read_structure")
        for alias, actions, snapshots in (("../owner", ["read_policy"], ["*"]),
                                          ("reader", ["wildcard"], ["*"]),
                                          ("reader", ["read_policy"], ["../snapshot"])):
            with self.assertRaises(acl.AccessDenied):
                acl.update_access(self.workspace, alias, actions, snapshots)
        (self.workspace / "access.json").chmod(0o644)
        with self.assertRaises(acl.AccessDenied):
            acl.authorize(self.workspace, "read_structure")

    def test_symlink_hardlink_and_malformed_policy_rejected(self):
        acl.initialize_access(self.workspace)
        path = self.workspace / "access.json"
        original = path.read_bytes()
        path.write_text('{"schemaVersion":1}')
        with self.assertRaises(acl.AccessDenied):
            acl.authorize(self.workspace, "read_structure")
        path.write_bytes(original)
        linked = self.workspace / "copy.json"
        os.link(path, linked)
        with self.assertRaises(acl.AccessDenied):
            acl.authorize(self.workspace, "read_structure")
        linked.unlink()
        path.rename(linked)
        path.symlink_to(linked)
        with self.assertRaises(acl.AccessDenied):
            acl.authorize(self.workspace, "read_structure")

    def test_second_initializer_cannot_reset_permissions(self):
        acl.initialize_access(self.workspace)
        with self.assertRaises(FileExistsError):
            acl.initialize_access(self.workspace)

    def test_private_metadata_is_checked_before_initial_grant_bytes(self):
        guard = acl.companion.privacy_guard
        original = guard._check_private_file_metadata
        path = self.workspace / "access.json"
        def reject_grant_only(info):
            # A configured privacy profile must still pass its own metadata
            # check before the grant exists; inject failure only at the grant.
            if path.exists() and acl.companion.core._same_file(info, path.lstat()):
                raise guard.PrivacyError("unsafe_permissions")
            return original(info)
        with mock.patch.object(guard, "_check_private_file_metadata", side_effect=reject_grant_only):
            with self.assertRaises(guard.PrivacyError):
                acl.initialize_access(self.workspace)
        self.assertEqual((self.workspace / "access.json").read_bytes(), b"")

    def test_failed_private_temporary_write_preserves_previous_grant(self):
        import pipeline_store
        acl.initialize_access(self.workspace)
        path = self.workspace / "access.json"
        before = path.read_bytes()
        with mock.patch.object(pipeline_store, "_private_handle", side_effect=pipeline_store.PipelineError("unsafe_fixture")):
            with self.assertRaises(pipeline_store.PipelineError):
                acl.update_access(self.workspace, "reader", ["read_policy"], ["*"])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(self.workspace.glob(".tmp-*")))
