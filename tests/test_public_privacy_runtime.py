"""Synthetic-only, fail-closed public exporter and local-profile regressions."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from windows_fixture import protect_private_path
from unittest import mock
from urllib.parse import quote

import test_mcp_contract as contract
import local_llm
import test_application_workflow as application_contract

server = contract.server
core, companion = server.core, server.companion
guard = core.privacy_guard
SPEC = importlib.util.spec_from_file_location("privacy_reference_test", core.__file__.replace("code_ontology_core.py", "code_reference.py"))
reference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reference)
SYNTHETIC_NAME = "Synthetic Person"
SYNTHETIC_EMAIL = "synthetic.person@privacy-fixture.test"


class PublicPrivacyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.profile_file = self.base / "private-profile.json"
        self.profile = guard.build_profile([SYNTHETIC_NAME, "가상인물표본"], [SYNTHETIC_EMAIL], key=b"x" * 32)
        self.write_profile(self.profile)
        patcher = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(self.profile_file),
                                               "CODE_ONTOLOGY_HOME": str(self.base / "registry")}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.base / "repository"
        self.repo.mkdir()
        (self.repo / "flow.py").write_text("def leaf():\n    return 1\n\ndef entry():\n    return leaf()\n", encoding="utf-8")

    def write_profile(self, profile):
        self.profile_file.write_text(json.dumps(profile), encoding="utf-8")
        protect_private_path(self.profile_file)

    def assert_rejected(self, payload, **kwargs):
        with self.assertRaises(guard.PrivacyError) as raised:
            guard.ensure_public_safe(payload, **kwargs)
        message = str(raised.exception)
        self.assertNotIn(SYNTHETIC_NAME, message)
        self.assertNotIn(SYNTHETIC_EMAIL, message)
        self.assertNotIn(str(self.base), message)
        return raised.exception.category

    def test_profile_contains_only_keyed_hashes_and_reads_changes_without_cache(self):
        encoded = json.dumps(self.profile)
        self.assertNotIn(SYNTHETIC_NAME, encoded)
        self.assertNotIn(SYNTHETIC_EMAIL, encoded)
        self.assertEqual(len(self.profile["denyNames"][0]["prefixDigest"]), 64)
        self.assert_rejected({"label": "Synthetic-Person"})
        self.write_profile(guard.build_profile([], [], key=b"z" * 32))
        guard.ensure_public_safe({"label": "Synthetic-Person"})
        self.write_profile(self.profile)
        self.assert_rejected({"label": "Synthetic-Person"})

    def test_known_name_variants_and_encoded_strings_fail_closed_without_echo(self):
        values = ["SyntheticPerson", "synthetic_person", "synthetic-person", "src/Synthetic.Person.py",
                  "Ｓｙｎｔｈｅｔｉｃ Ｐｅｒｓｏｎ", "가상-인물_표본", quote(SYNTHETIC_NAME),
                  "Synthetic&#32;Person", "Synthetic\\u0020Person", "Synthetic\u200bPerson"]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(self.assert_rejected({"field": value}), "denied_identity")
        legacy = copy.deepcopy(self.profile)
        for item in legacy["denyNames"]:
            item.pop("prefixDigest")
        self.assert_rejected("SyntheticPerson", profile=legacy)

    def test_known_email_has_priority_over_reserved_domain_and_zero_width_obfuscation(self):
        values = [SYNTHETIC_EMAIL, SYNTHETIC_EMAIL.replace("@", "&#64;"), quote(SYNTHETIC_EMAIL),
                  SYNTHETIC_EMAIL.replace("@", "\\u0040"), SYNTHETIC_EMAIL.replace("@", "@\u200b"),
                  SYNTHETIC_EMAIL.replace(".", ".\u2060", 1)]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(self.assert_rejected(value), "denied_identity")
        public = guard.build_profile([], [guard.ALLOWED_PUBLIC_EMAIL], key=b"a" * 32)
        self.assert_rejected(guard.ALLOWED_PUBLIC_EMAIL, profile=public)
        guard.ensure_public_safe("example@other-fixture.test")
        guard.ensure_public_safe(guard.ALLOWED_PUBLIC_EMAIL)
        guard.ensure_public_safe("12345+" + guard.ALLOWED_PUBLIC_EMAIL)
        denied_alias = guard.build_profile([], ["12345+" + guard.ALLOWED_PUBLIC_EMAIL], key=b"c" * 32)
        self.assert_rejected("12345+" + guard.ALLOWED_PUBLIC_EMAIL, profile=denied_alias)

    def test_deeply_nested_encoding_is_rejected_with_a_static_depth_category(self):
        for atom in (SYNTHETIC_NAME, SYNTHETIC_EMAIL):
            encoded = "".join("%%%02X" % ord(character) for character in atom)
            for _ in range(4):
                encoded = quote(encoded, safe="")
            self.assertEqual(self.assert_rejected({"value": encoded}), "encoding_depth")
        guard.ensure_public_safe("ordinary percent 10% and regex \\d+")

    def test_private_profile_material_and_obfuscated_variants_are_never_public(self):
        materials = [self.profile["key"], self.profile["denyNames"][0]["digest"],
                     self.profile["denyNames"][0]["prefixDigest"], self.profile["denyEmails"][0]["digest"]]
        for material in materials:
            variants = [material, material.upper(), "\\u%04x" % ord(material[0]) + material[1:],
                        "".join("%%%02X" % ord(character) for character in material),
                        "".join(chr(ord(character) + 0xFEE0) for character in material),
                        material[:5] + "\u200b" + material[5:]]
            for variant in variants:
                with self.subTest(materialKind=len(material), variantKind=variants.index(variant)):
                    self.assertEqual(self.assert_rejected({"material": variant}), "private_profile_material")
        self.assert_rejected({"material": self.profile})

    def test_profile_material_document_html_and_mcp_envelopes_fail_as_a_whole(self):
        document = core.build_document(self.repo)
        document["private_profile"] = self.profile
        for operation in (lambda: core.render_turtle(document), lambda: core.render_report(document),
                          lambda: core.render_visualization(document, 20)):
            with self.assertRaises(guard.PrivacyError) as raised:
                operation()
            self.assertEqual(raised.exception.category, "private_profile_material")
        payload = core._visualization_payload(core.build_document(self.repo), 20)
        payload["meta"]["private_material"] = self.profile["key"]
        with self.assertRaises(guard.PrivacyError):
            core._render_visualization_payload(payload)
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        raw = companion.query(str(workspace), "entry")
        raw["private_profile"] = self.profile
        with mock.patch.object(server, "_dispatch", return_value=raw):
            response = server._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "ontology_search", "arguments": {"workspace_id": initialized["workspaceId"], "term": "entry"}}})
        self.assertTrue(response["result"]["isError"])
        serialized = json.dumps(response)
        for material in (self.profile["key"], self.profile["denyNames"][0]["digest"],
                         self.profile["denyNames"][0]["prefixDigest"]):
            self.assertNotIn(material, serialized)

    def test_lineage_record_rejection_preserves_existing_journal_turtle_and_private_paths(self):
        workspace = self.base / "workspace"
        companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        companion.record(str(workspace), "validation", "Reviewed src/flow.py", "declared", "flow.entry")
        journal, turtle = workspace / "lineage.jsonl", workspace / "lineage.ttl"
        before = (journal.read_bytes(), turtle.read_bytes())
        for atom in (SYNTHETIC_NAME, SYNTHETIC_EMAIL, self.profile["key"],
                     self.profile["denyNames"][0]["digest"], self.profile["denyNames"][0]["prefixDigest"]):
            for field in ("summary", "subject"):
                arguments = {"summary": "Reviewed src/flow.py", "subject": "flow.entry", field: atom}
                with self.assertRaises(guard.PrivacyError):
                    companion.record(str(workspace), "note", evidence_type="declared", **arguments)
                self.assertEqual((journal.read_bytes(), turtle.read_bytes()), before)
        private_config = json.loads((workspace / "companion.json").read_text(encoding="utf-8"))
        self.assertEqual(private_config["repositoryRoot"], str(self.repo))
        self.assertIn("src/flow.py", turtle.read_text(encoding="utf-8"))
        self.assertEqual(companion.lineage(str(workspace))["events"][0]["evidenceType"], "declared")

    def test_lineage_rejection_creates_no_files_and_cannot_bypass_via_direct_append_or_render(self):
        workspace = self.base / "workspace"
        companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        journal, turtle = workspace / "lineage.jsonl", workspace / "lineage.ttl"
        journal.unlink()
        turtle.unlink()
        with self.assertRaises(guard.PrivacyError):
            companion._append_journal(workspace, {"eventId": "fixture", "summary": SYNTHETIC_NAME})
        self.assertFalse(journal.exists())
        self.assertFalse(turtle.exists())
        # Historical raw events must not be silently omitted from a fresh TTL.
        journal.write_text(json.dumps({"eventId": "fixture", "summary": SYNTHETIC_EMAIL}) + "\n", encoding="utf-8")
        prior = journal.read_bytes()
        turtle.write_text("safe prior Turtle", encoding="utf-8")
        with self.assertRaises(guard.PrivacyError):
            companion._render_lineage_turtle(workspace)
        self.assertEqual(journal.read_bytes(), prior)
        self.assertEqual(turtle.read_text(encoding="utf-8"), "safe prior Turtle")
        with self.assertRaises(guard.PrivacyError):
            companion.record(str(workspace), "note", "Safe new event", "declared")
        self.assertEqual(journal.read_bytes(), prior)
        self.assertEqual(turtle.read_text(encoding="utf-8"), "safe prior Turtle")

    def test_lineage_public_home_path_rejection_occurs_before_private_append(self):
        workspace = self.base / "workspace"
        companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        journal, turtle = workspace / "lineage.jsonl", workspace / "lineage.ttl"
        before = (journal.read_bytes(), turtle.read_bytes())
        with self.assertRaises(guard.PrivacyError) as raised:
            companion.record(str(workspace), "note", "/home/" + "synthetic-fixture/private", "declared")
        self.assertEqual(raised.exception.category, "private_home_path")
        self.assertEqual((journal.read_bytes(), turtle.read_bytes()), before)

    def test_prov_snapshot_entities_have_correlated_generation_source_and_custom_predecessor(self):
        workspace = self.base / "workspace"
        first = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        (self.repo / "flow.py").write_text("def leaf():\n    return 2\n", encoding="utf-8")
        second = companion.sync(str(workspace))
        journal = companion._read_journal(workspace)
        before = (workspace / "lineage.jsonl").read_bytes()
        companion._render_lineage_turtle(workspace)
        self.assertEqual((workspace / "lineage.jsonl").read_bytes(), before)
        turtle = (workspace / "lineage.ttl").read_text(encoding="utf-8")
        types, generated, used, generated_by = {}, [], [], []
        subject = None
        for line in turtle.splitlines():
            if line.startswith("<"):
                subject = line.split()[0]
                if " a " in line:
                    classes = line.split(" a ", 1)[1].rstrip(" ;.")
                    types[subject] = {item.strip() for item in classes.split(",")}
            if "  prov:generatedAtTime " in line:
                generated.append(subject)
                self.assertIn("^^xsd:dateTime .", line)
            if "  prov:used " in line:
                used.append((subject, line.split()[1]))
            if "  prov:wasGeneratedBy " in line:
                generated_by.append((subject, line.split()[1]))
        self.assertEqual(len(generated), 2)
        for subject in generated:
            self.assertIn("prov:Entity", types[subject])
            self.assertIn("coc:OntologySnapshot", types[subject])
            self.assertNotIn("prov:Activity", types[subject])
        for activity, source in used:
            self.assertIn("prov:Activity", types[activity])
            self.assertIn("prov:Entity", types[source])
            self.assertIn("coc:ScopedSource", types[source])
        for snapshot, activity in generated_by:
            self.assertIn("prov:Entity", types[snapshot])
            self.assertIn("prov:Activity", types[activity])
        base = companion.PROVENANCE_NS
        first_snapshot = f"<{base}snapshot-{first['snapshotId']}>"
        second_snapshot = f"<{base}snapshot-{second['snapshotId']}>"
        self.assertIn(f"{second_snapshot} coc:previousSnapshot {first_snapshot} .", turtle)
        self.assertNotIn("prov:wasDerivedFrom " + first_snapshot, turtle)
        for event in journal:
            record = f"<{base}event-{event['eventId'].replace('-', '')}>"
            self.assertIn("coc:LineageRecord", types[record])
            self.assertNotIn("prov:Activity", types[record])
        for snapshot_id in (first["snapshotId"], second["snapshotId"]):
            metadata = companion._snapshot_metadata(workspace / "snapshots" / snapshot_id)
            self.assertIn('prov:generatedAtTime "' + metadata["createdAt"] + '"^^xsd:dateTime', turtle)
            self.assertNotIn(metadata["sourceFingerprint"], turtle)
        self.assertNotIn(str(self.repo), turtle)
        self.assertNotIn("prov:Agent", turtle)
        self.assertNotIn("prov:Person", turtle)
        self.assertNotIn("prov:startedAtTime", turtle)
        self.assertNotIn("prov:endedAtTime", turtle)

    def test_prov_records_preserve_legacy_time_without_promoting_manual_claims_to_generation(self):
        workspace = self.base / "workspace"
        companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        promotion = companion._read_journal(workspace)[0]
        for evidence in ("declared", "inferred", "validated", "approved"):
            event = {**promotion, "evidenceType": evidence}
            turtle = companion._lineage_turtle_text([event], workspace=workspace)
            self.assertIn('coc:evidenceType "' + evidence + '"', turtle)
            self.assertNotIn("prov:wasGeneratedBy", turtle)
            self.assertNotIn("prov:used", turtle)
        for value in ("2026-10-03T10:00:00", "not-a-time", "2026-02-30T10:00:00Z",
                      "20261003T100000Z", "2026-10-03T10:00:00+15:00"):
            event = {**promotion, "recordedAt": value, "runId": None}
            turtle = companion._lineage_turtle_text([event], workspace=workspace)
            self.assertIn('coc:recordedAt "' + value + '"', turtle)
            self.assertNotIn("^^xsd:dateTime", turtle)
            self.assertNotIn("prov:generatedAtTime", turtle)
        # A genuine promotion-shaped record alone cannot corroborate a snapshot.
        turtle = companion._lineage_turtle_text([promotion])
        self.assertNotIn("prov:wasGeneratedBy", turtle)
        self.assertNotIn("prov:used", turtle)
        missing = {**promotion, "snapshotId": "missing-fixture", "summary": "Promoted ontology snapshot missing-fixture"}
        self.assertNotIn("prov:wasGeneratedBy", companion._lineage_turtle_text([missing], workspace=workspace))

    def test_prov_snapshot_metadata_and_recomputed_manifest_must_agree(self):
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        event = companion._read_journal(workspace)[0]
        snapshot = workspace / "snapshots" / initialized["snapshotId"]
        metadata_path, manifest_path = snapshot / "snapshot.json", snapshot / "source-manifest.json"
        baseline_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        baseline_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field, value in (("workspaceId", "wrong-fixture"), ("createdAt", "2026-01-01T00:00:00Z"),
                             ("trigger", "wrong-trigger"), ("sourceRoots", ["other"]),
                             ("sourceFingerprint", "0" * 64)):
            metadata_path.write_text(json.dumps({**baseline_metadata, field: value}), encoding="utf-8")
            self.assertNotIn("prov:wasGeneratedBy", companion._lineage_turtle_text([event], workspace=workspace))
        metadata_path.write_text(json.dumps(baseline_metadata), encoding="utf-8")
        for field, value in (("sha256", "0" * 64), ("language", ["Python"]), ("bytes", True)):
            manifest = copy.deepcopy(baseline_manifest)
            manifest["files"][0][field] = value
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertNotIn("prov:wasGeneratedBy", companion._lineage_turtle_text([event], workspace=workspace))
        manifest_path.write_text(json.dumps(baseline_manifest), encoding="utf-8")
        self.assertIn("prov:wasGeneratedBy", companion._lineage_turtle_text([event], workspace=workspace))

    def test_prov_corroboration_checks_raw_snapshot_metadata_before_any_lineage_write(self):
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        metadata_path = workspace / "snapshots" / initialized["snapshotId"] / "snapshot.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["private_ignored_field"] = self.profile["key"]
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        journal, turtle = workspace / "lineage.jsonl", workspace / "lineage.ttl"
        before = (journal.read_bytes(), turtle.read_bytes())
        with self.assertRaises(guard.PrivacyError) as raised:
            companion.record(str(workspace), "note", "Reviewed src/flow.py", "declared")
        self.assertEqual(raised.exception.category, "private_profile_material")
        self.assertEqual((journal.read_bytes(), turtle.read_bytes()), before)

    def test_generic_email_home_path_and_recognizable_secrets_are_blocked(self):
        personal_email = "fixture-person" + "@" + "privacy-fixture.net"
        for value, category in [(personal_email, "personal_email"),
                                ("/home/" + "synthetic-fixture/private", "private_home_path"),
                                ("C:\\Users\\" + "synthetic-fixture\\private", "private_home_path"),
                                ("github_pat_" + "x" * 60, "secret_token"),
                                ("sk-proj-" + "x" * 40, "secret_token")]:
            self.assertEqual(self.assert_rejected(value), category)
        guard.ensure_public_safe("/home/" + "synthetic-fixture/private", allow_local_paths=True)

    def test_no_profile_does_not_claim_unknown_name_detection_but_generic_checks_remain(self):
        with mock.patch.dict(os.environ, {guard.PROFILE_ENV: ""}, clear=False):
            self.assertIsNone(guard.load_profile())
            guard.ensure_public_safe("Unregistered Fixture")
            self.assert_rejected("fixture" + "@" + "privacy-fixture.net")
            with self.assertRaises(guard.PrivacyError):
                guard.load_profile(required=True)

    def test_profile_boundary_permissions_symlinks_and_size_fail_without_path_echo(self):
        self.assert_rejected("safe", context_roots=(self.base,))
        if os.name != "nt":
            self.profile_file.chmod(0o644)
            self.assertEqual(self.assert_rejected("safe"), "profile_permissions")
            self.profile_file.chmod(0o600)
        self.profile_file.write_bytes(b"x" * (guard.MAX_PROFILE_BYTES + 1))
        self.assertEqual(self.assert_rejected("safe"), "profile_size")
        self.write_profile(self.profile)
        linked_directory = self.base / "linked"
        try:
            linked_directory.symlink_to(self.base, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Links unavailable")
        with mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(linked_directory / self.profile_file.name)}, clear=False):
            self.assertEqual(self.assert_rejected("safe"), "profile_link")

    def test_profile_malformed_fields_and_cycles_fail_closed(self):
        bad = copy.deepcopy(self.profile)
        bad["denyNames"][0]["chars"] = True
        self.write_profile(bad)
        self.assert_rejected("safe")
        self.write_profile(self.profile)
        cyclic = []
        cyclic.append(cyclic)
        self.assertEqual(self.assert_rejected(cyclic), "unsupported_payload")

    def test_source_comments_and_string_literals_are_not_retained_but_personal_filename_is_blocked(self):
        (self.repo / "comment.py").write_text("# " + SYNTHETIC_NAME + "\nVALUE = '" + SYNTHETIC_EMAIL + "'\ndef safe_entry():\n    return 1\n", encoding="utf-8")
        document = core.build_document(self.repo)
        self.assertNotIn(SYNTHETIC_NAME, json.dumps(document))
        (self.repo / "SyntheticPerson.py").write_text("def safe_entry():\n    return 1\n", encoding="utf-8")
        output = self.base / "index"
        with self.assertRaises(guard.PrivacyError):
            core.write_index(self.repo, output, authorized=True)
        self.assertFalse(output.exists())

    def test_all_direct_public_renderers_reject_raw_and_previous_document_atoms(self):
        document = core.build_document(self.repo)
        unsafe = copy.deepcopy(document)
        unsafe["nodes"][0]["metadata"] = {"parameter_types": ["SyntheticPerson"]}
        for operation in (lambda: core.render_turtle(unsafe), lambda: core.render_report(unsafe),
                          lambda: core.render_visualization(unsafe, 20),
                          lambda: core.render_visualization(document, 20, previous_document=unsafe)):
            with self.assertRaises(guard.PrivacyError):
                operation()
        payload = core._visualization_payload(document, 20)
        payload["meta"]["repositoryName"] = SYNTHETIC_NAME
        with self.assertRaises(guard.PrivacyError):
            core._render_visualization_payload(payload)

    def test_visualization_write_rejects_without_replacing_existing_safe_artifact(self):
        output = self.base / "index"
        core.write_index(self.repo, output, authorized=True)
        page = output / "graph.html"
        page.write_text("safe prior artifact", encoding="utf-8")
        index = output / "ontology.json"
        document = json.loads(index.read_text(encoding="utf-8"))
        document["repository"]["name"] = SYNTHETIC_NAME
        index.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(guard.PrivacyError):
            core.write_visualization(str(index), str(page), 20, overwrite=True)
        self.assertEqual(page.read_text(encoding="utf-8"), "safe prior artifact")

    def test_companion_failed_refresh_keeps_pointer_and_private_required_paths(self):
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        before = (workspace / "state.json").read_bytes()
        private_config = json.loads((workspace / "companion.json").read_text(encoding="utf-8"))
        self.assertEqual(private_config["repositoryRoot"], str(self.repo))
        (self.repo / "SyntheticPerson.py").write_text("def blocked():\n    return 1\n", encoding="utf-8")
        with self.assertRaises(guard.PrivacyError):
            companion.sync(str(workspace))
        self.assertEqual((workspace / "state.json").read_bytes(), before)
        self.assertEqual(len(list((workspace / "snapshots").iterdir())), 1)
        self.assertEqual(companion._state(workspace)["currentSnapshot"], initialized["snapshotId"])

    def test_label_rejection_preserves_no_new_workspace_or_public_snapshots(self):
        workspace = self.base / "workspace"
        with self.assertRaises(guard.PrivacyError):
            companion.initialize(str(self.repo), str(workspace), authorized=True, label=SYNTHETIC_NAME)
        self.assertFalse(workspace.exists())

    def test_selected_reference_identifier_and_evidence_fail_closed(self):
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        document = companion._read_json(workspace / "snapshots" / initialized["snapshotId"] / "ontology.json", "test")
        metadata = companion._snapshot_metadata(workspace / "snapshots" / initialized["snapshotId"])
        symbol = next(node["id"] for node in document["nodes"] if node["name"] == "entry")
        artifact = reference.build_reference(document, metadata, "fixture", [symbol])
        guard.ensure_public_safe(artifact)
        with self.assertRaises(guard.PrivacyError):
            reference.build_reference(document, metadata, "SyntheticPerson", [symbol])
        artifact["private_ignored_field"] = "SyntheticPerson"
        with self.assertRaises(guard.PrivacyError):
            reference.verify_artifact(artifact)

    def test_mcp_blocks_raw_atom_even_in_field_that_old_allowlist_would_drop(self):
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        original = companion.query
        def unsafe(*args, **kwargs):
            result = original(*args, **kwargs)
            result["private_ignored_field"] = SYNTHETIC_NAME
            return result
        with mock.patch.object(companion, "query", side_effect=unsafe):
            response = server._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "ontology_search", "arguments": {"workspace_id": initialized["workspaceId"], "term": "entry"}}})
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "error")
        self.assertNotIn(SYNTHETIC_NAME, json.dumps(response))
        self.assertNotIn(SYNTHETIC_EMAIL, json.dumps(response))

    def test_cli_and_mcp_errors_never_echo_known_identity_or_bad_profile_path(self):
        bad = companion.CompanionError("Duplicate declaration " + SYNTHETIC_NAME)
        self.assertNotIn(SYNTHETIC_NAME, guard.safe_error_message(bad))
        self.assertNotIn(SYNTHETIC_NAME, server._public_error(bad))
        error = io.StringIO()
        output = io.StringIO()
        with contextlib.redirect_stderr(error), contextlib.redirect_stdout(output):
            code = core.main(["index", "--repo", str(self.repo), "--output", str(self.base / "index"), "--authorized"])
        self.assertEqual(code, 0)
        self.profile_file.write_text("invalid", encoding="utf-8")
        result = server._tool_result({"status": "error", "message": SYNTHETIC_NAME}, is_error=True)
        self.assertNotIn(SYNTHETIC_NAME, json.dumps(result))
        self.assertNotIn(str(self.profile_file), json.dumps(result))

    def test_mcp_unknown_methods_and_private_request_ids_never_echo_input(self):
        for atom in (SYNTHETIC_NAME, SYNTHETIC_EMAIL):
            response = server._handle({"jsonrpc": "2.0", "id": 1, "method": atom})
            self.assertEqual(response["error"], {"code": -32601, "message": "Method not found."})
            self.assertNotIn(atom, json.dumps(response))
            response = server._handle({"jsonrpc": "2.0", "id": atom, "method": "ping"})
            self.assertIsNone(response["id"])
            self.assertEqual(response["error"]["code"], -32600)
            self.assertNotIn(atom, json.dumps(response))
            for response in (server._response(1, {"value": atom}), server._error(1, -32602, atom)):
                self.assertIsNone(response["id"])
                self.assertEqual(response["error"]["code"], -32603)
                self.assertNotIn(atom, json.dumps(response))

    def test_mcp_stdio_parse_errors_and_final_wire_gate_are_static(self):
        malformed = '{"method": "' + SYNTHETIC_NAME + '", "partial": "' + SYNTHETIC_EMAIL + '"\n'
        output = io.StringIO()
        with mock.patch.object(server, "_force_utf8_stdio"), mock.patch.object(server.sys, "stdin", io.StringIO(malformed)), \
                contextlib.redirect_stdout(output):
            self.assertEqual(server.main(), 0)
        response = json.loads(output.getvalue())
        self.assertEqual(response["error"], {"code": -32700, "message": "Parse error."})
        self.assertIsNone(response["id"])
        self.assertNotIn(SYNTHETIC_NAME, output.getvalue())
        self.assertNotIn(SYNTHETIC_EMAIL, output.getvalue())
        output = io.StringIO()
        injected = {"jsonrpc": "2.0", "id": 1, "result": {"ignored": SYNTHETIC_EMAIL}}
        with mock.patch.object(server, "_force_utf8_stdio"), mock.patch.object(server, "_handle", return_value=injected), \
                mock.patch.object(server.sys, "stdin", io.StringIO('{"method":"ping","id":1}\n')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(server.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32603)
        self.assertNotIn(SYNTHETIC_EMAIL, output.getvalue())

    def configured_local_model(self):
        workspace = self.base / "workspace"
        initialized = companion.initialize(str(self.repo), str(workspace), authorized=True, label="fixture")
        model = {"name": "fixture:local", "digest": "sha256:" + "a" * 64,
                 "size": 1_000_000, "format": "gguf"}
        with mock.patch.object(local_llm, "detect", return_value={"supportedProviderDetected": True}), \
                mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)), \
                mock.patch.object(local_llm, "_verify_model", return_value={**model, "capabilities": ["completion"]}):
            local_llm.configure(str(workspace), model["name"], True)
        return workspace, initialized, model

    def test_local_model_receives_no_contaminated_snapshot_even_in_ignored_fields(self):
        workspace, initialized, _model = self.configured_local_model()
        index = workspace / "snapshots" / initialized["snapshotId"] / "ontology.json"
        document = json.loads(index.read_text(encoding="utf-8"))
        document["private_ignored_field"] = SYNTHETIC_NAME
        index.write_text(json.dumps(document), encoding="utf-8")
        with mock.patch.object(local_llm, "_request_json") as request, \
                mock.patch.object(local_llm, "_tag_models") as tags:
            with self.assertRaises(guard.PrivacyError):
                local_llm.enrich(str(workspace), True)
        request.assert_not_called()
        tags.assert_not_called()
        self.assertFalse((workspace / "enrichments").exists())

    def test_local_model_raw_output_and_final_annotation_fail_before_any_sidecar_write(self):
        workspace, _initialized, model = self.configured_local_model()
        safe_response = {"done": True, "done_reason": "stop", "message": {"content": '{"suggestions":[]}'}}
        for raw_private in (True, False):
            response = copy.deepcopy(safe_response)
            if raw_private:
                response["private_ignored_field"] = SYNTHETIC_EMAIL
            with mock.patch.object(local_llm, "_tag_models", return_value=([model], 0)), \
                    mock.patch.object(local_llm, "_verify_model", return_value=model), \
                    mock.patch.object(local_llm, "_request_json", return_value=response), \
                    mock.patch.object(local_llm, "_now", return_value="fixture-time" if raw_private else SYNTHETIC_NAME):
                with self.assertRaises(guard.PrivacyError):
                    local_llm.enrich(str(workspace), True)
            self.assertFalse((workspace / "enrichments").exists())

    def test_local_model_cli_and_application_stdout_reject_complete_contaminated_results(self):
        for value in ({"status": "detected", "ignored": SYNTHETIC_NAME}, local_llm.LocalLLMError(SYNTHETIC_EMAIL)):
            output, error = io.StringIO(), io.StringIO()
            patch = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
            with mock.patch.object(local_llm, "detect", **patch), contextlib.redirect_stdout(output), \
                    contextlib.redirect_stderr(error):
                self.assertEqual(local_llm.main(["detect"]), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(json.loads(error.getvalue())["status"], "error")
            self.assertNotIn(SYNTHETIC_NAME, error.getvalue())
            self.assertNotIn(SYNTHETIC_EMAIL, error.getvalue())
        workflow = application_contract.workflow
        output = io.StringIO()
        with mock.patch.object(workflow, "plan", return_value={"status": "planned", "raw": SYNTHETIC_NAME}), \
                contextlib.redirect_stdout(output):
            self.assertEqual(workflow.main(["plan", "--capabilities", "{}"]), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "invalid_input")
        self.assertEqual(result["issues"], ["Public output rejected by the privacy guard."])
        self.assertNotIn(SYNTHETIC_NAME, output.getvalue())
        output = io.StringIO()
        with mock.patch.object(workflow, "_load_privacy_guard", side_effect=RuntimeError(SYNTHETIC_EMAIL)), \
                contextlib.redirect_stdout(output):
            self.assertEqual(workflow.main(["plan", "--capabilities", "{}"]), 1)
        self.assertNotIn(SYNTHETIC_EMAIL, output.getvalue())


if __name__ == "__main__":
    unittest.main()
