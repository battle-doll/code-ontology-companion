from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from windows_fixture import protect_private_path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import code_ontology_core as core
guard = core.privacy_guard


# All identities below are synthetic. The tests never discover or read a user's
# actual identity, configured deny profile, Git identity, or source outside here.
SYNTHETIC_NAME = "Synthetic Private Name"
SYNTHETIC_EMAIL = "synthetic.fixture@example.test"


def payload():
    return {
        "meta": {"repositoryName": "safe fixture", "snapshotId": "synthetic-snapshot"},
        "nodes": [{"id": "fn:safe", "type": "Function", "name": "safe", "language": "Python", "path": "src/safe.py"}],
        "edges": [], "warnings": [], "quality": {}, "changes": {},
        "statistics": {}, "limits": {"maxVisibleNodes": 1},
    }


class HtmlPrivacyAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.private = Path(self.temporary.name).resolve()
        self.profile = guard.build_profile([SYNTHETIC_NAME], [SYNTHETIC_EMAIL], key=b"k" * 32)
        self.profile_path = self.private / "deny-profile.json"
        self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
        protect_private_path(self.profile_path)
        self.environment = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(self.profile_path)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_hidden_payload_fields_are_checked_before_embedding(self):
        assignments = (
            lambda data: data["meta"].update(repositoryName=SYNTHETIC_NAME),
            lambda data: data["nodes"][0].update(id=SYNTHETIC_NAME),
            lambda data: data["nodes"][0].update(qualified_name=SYNTHETIC_NAME),
            lambda data: data["nodes"][0].update(metadata={"parameter_types": [SYNTHETIC_EMAIL]}),
            lambda data: data.update(warnings=[{"path": "src/safe.py", "message": SYNTHETIC_EMAIL}]),
            lambda data: data.update(quality={"adapters": [{"limitations": [SYNTHETIC_NAME]}]}),
            lambda data: data.update(changes={"nodesRemoved": [{"name": SYNTHETIC_NAME}]}),
        )
        for assign in assignments:
            with self.subTest(field=assign.__code__.co_firstlineno):
                data = payload()
                assign(data)
                with self.assertRaises(guard.PrivacyError) as rejected:
                    core._render_visualization_payload(data)
                self.assertNotIn(SYNTHETIC_NAME, str(rejected.exception))
                self.assertNotIn(SYNTHETIC_EMAIL, str(rejected.exception))

    def test_encoded_identities_in_script_data_are_rejected(self):
        encoded = (
            "Synthetic%20Private%20Name",
            "Synthetic&#32;Private&#32;Name",
            r"\u0053ynthetic Private Name",
            "Ｓｙｎｔｈｅｔｉｃ Ｐｒｉｖａｔｅ Ｎａｍｅ",
            "synthetic.fixture%40example.test",
            "synthetic.fixture&#64;example.test",
            r"synthetic.fixture\u0040example.test",
        )
        for value in encoded:
            with self.subTest(encoding=encoded.index(value)):
                data = payload()
                data["nodes"][0]["name"] = value
                with self.assertRaises(guard.PrivacyError):
                    core._render_visualization_payload(data)

    def test_visually_invisible_email_obfuscation_cannot_bypass_known_profile(self):
        for value in (
            SYNTHETIC_EMAIL.replace("@", "@\u200b"),
            SYNTHETIC_EMAIL.replace(".fixture", ".\u2060fixture"),
            SYNTHETIC_EMAIL.replace("@", "@\ufeff"),
        ):
            with self.subTest(obfuscation=ord(next(c for c in value if ord(c) > 127))):
                with self.assertRaises(guard.PrivacyError):
                    guard.ensure_public_safe({"hidden": value})

    def test_previous_snapshot_identity_is_checked_even_if_not_shown_initially(self):
        clean = {"repository": {"name": "safe"}, "nodes": [], "edges": [], "warnings": []}
        previous = copy.deepcopy(clean)
        previous["nodes"] = [{"id": "old", "name": SYNTHETIC_NAME, "type": "Function"}]
        with self.assertRaises(guard.PrivacyError):
            core.render_visualization(clean, 1, previous_document=previous)

    def test_clean_embedded_payload_never_contains_profile_key_or_digests(self):
        page = core._render_visualization_payload(payload())
        self.assertIn('id="ontology-data"', page)
        self.assertNotIn(self.profile["key"], page)
        for field in ("denyNames", "denyEmails"):
            for identity in self.profile[field]:
                self.assertNotIn(identity["digest"], page)
        self.assertNotIn(str(self.profile_path), page)

    def test_profile_changes_are_seen_on_next_render_not_cached(self):
        core._render_visualization_payload(payload())
        changed = guard.build_profile(["safe fixture"], [], key=b"m" * 32)
        self.profile_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(guard.PrivacyError):
            core._render_visualization_payload(payload())


if __name__ == "__main__":
    unittest.main()
