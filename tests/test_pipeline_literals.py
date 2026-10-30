"""Synthetic exact-occurrence review/privacy tests; no private source or profile."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import builtins
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline_literals as literals
import privacy_guard

FINGERPRINT = "a" * 64
PATH = "synthetic/Rules.java"


def sha(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def entry(source, token, *, occurrence=0, **changes):
    start = -1
    for _ in range(occurrence + 1):
        start = source.index(token, start + 1)
    end = start + len(token)
    result = dict(path=PATH, sourceSha256=sha(source), tokenByteStart=len(source[:start].encode()),
                  tokenByteEnd=len(source[:end].encode()), tokenSha256=sha(token),
                  classification="nonsecret_policy", reasonCode="policy_constant",
                  usageContext="comparison_operand", reviewId="review-synthetic")
    result.update(changes)
    return result


def manifest(entries):
    return {"format": literals.FORMAT, "purpose": literals.PURPOSE, "sourceFingerprint": FINGERPRINT,
            "review": {"reviewId": "review-synthetic", "reviewerKind": "independent_source_review",
                       "reviewedAt": "2026-10-28T00:00:00Z"}, "entries": entries}


def prepare(value, **kwargs):
    return literals.prepare_review(value, source_fingerprint=FINGERPRINT, **kwargs)


class ReviewedLiteralTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop(privacy_guard.PROFILE_ENV, None)

    def admit(self, source, token, *, review=None, occurrence=0, **kwargs):
        review = review or prepare(manifest([entry(source, token, occurrence=occurrence)]))
        start = -1
        for _ in range(occurrence + 1):
            start = source.index(token, start + 1)
        bound = review.bind_source(PATH, source, sha(source))
        return review, bound.admit(start, start + len(token), sensitive_context=kwargs.pop("sensitive_context", False), **kwargs)

    def test_exact_private_occurrence_and_compact_coverage(self):
        source = 'class Rules { String mode="READY"; }'
        review, result = self.admit(source, '"READY"')
        self.assertEqual(result["value"], "READY")
        self.assertEqual(result["literalType"], "string")
        self.assertFalse(result["review"]["publicDisclosureAuthorized"])
        self.assertEqual(result["review"]["purpose"], "private-policy-analysis")
        self.assertEqual(review.manifestSha256, review.manifest_sha256)
        coverage = review.coverage(PATH)
        self.assertEqual((coverage["requestedEntries"], coverage["admittedEntries"]), (1, 1))
        self.assertEqual(set(coverage["entries"][0]), {"requestIndex", "status", "reason", "tokenByteStart", "tokenByteEnd"})
        self.assertNotIn("entries", review.summary())
        self.assertNotIn("READY", json.dumps(coverage))
        self.assertNotIn(entry(source, '"READY"')["tokenSha256"], json.dumps(coverage))
        self.assertEqual(coverage["admissionMeaning"], "token_permission_not_parser_or_policy_completeness")

    def test_identical_strings_only_one_allowed_and_no_shared_opaque_identity(self):
        source = 'class Rules { String first="READY"; String second="READY"; }'
        review = prepare(manifest([entry(source, '"READY"')]))
        _, first = self.admit(source, '"READY"', review=review)
        _, second = self.admit(source, '"READY"', review=review, occurrence=1)
        self.assertEqual(first["status"], "admitted")
        self.assertEqual(second["status"], "unreviewed")
        self.assertNotIn("value", second)
        self.assertNotEqual(first["opaqueOccurrenceId"], second["opaqueOccurrenceId"])
        bound = review.bind_source(PATH, source, sha(source))
        second_start = source.rindex('"READY"')
        self.assertEqual(second["opaqueOccurrenceId"], bound.opaque_id(second_start, second_start + 7))
        self.assertEqual(review.coverage()["requestedEntries"], 1)

    def test_plain_unicode_has_exact_utf8_boundaries(self):
        source = 'class Rules { String 이름="가상"; String mode="준비"; }'
        token = '"준비"'
        approved = entry(source, token)
        start = source.index(token)
        self.assertNotEqual(start, approved["tokenByteStart"])
        review, result = self.admit(source, token)
        self.assertEqual(result["value"], "준비")
        self.assertEqual(result["review"]["sourceBinding"]["tokenByteStart"], len(source[:start].encode()))

    def test_inside_utf8_codepoint_rejected_without_values(self):
        source = 'class Rules { String mode="준비"; }'
        approved = entry(source, '"준비"')
        approved["tokenByteStart"] += 2
        review = prepare(manifest([approved]))
        review.bind_source(PATH, source, sha(source))
        row = review.coverage()["entries"][0]
        self.assertEqual(row["reason"], "token_span_not_utf8_boundary")
        self.assertNotIn("준비", json.dumps(review.coverage(), ensure_ascii=False))

    def test_stale_source_fingerprint_rejects_every_request(self):
        source = 'class Rules { String mode="READY"; }'
        data = manifest([entry(source, '"READY"')])
        data["sourceFingerprint"] = "b" * 64
        review = prepare(data)
        self.assertFalse(review.valid)
        self.assertEqual(review.coverage()["rejectedEntries"], 1)
        self.assertEqual(review.coverage()["entries"][0]["reason"], "source_fingerprint_mismatch")
        _, result = self.admit(source, '"READY"', review=review)
        self.assertNotIn("value", result)

    def test_stale_file_digest_and_untruthful_source_argument_rejected(self):
        source = 'class Rules { String mode="READY"; }'
        review = prepare(manifest([entry(source, '"READY"', sourceSha256="b" * 64)]))
        review.bind_source(PATH, source, sha(source))
        self.assertEqual(review.coverage()["entries"][0]["reason"], "source_sha256_mismatch")
        review = prepare(manifest([entry(source, '"READY"')]))
        review.bind_source(PATH, source + " ", sha(source))
        self.assertEqual(review.coverage()["entries"][0]["reason"], "source_digest_argument_mismatch")

    def test_token_hash_and_bad_spans_rejected(self):
        source = 'class Rules { String mode="READY"; }'
        for changes, reason in [({"tokenSha256": "b" * 64}, "token_hash_mismatch"),
                                ({"tokenByteEnd": 1000}, "invalid_token_span"),
                                ({"tokenByteStart": True}, "invalid_token_span"),
                                ({"tokenByteStart": -1}, "invalid_token_span")]:
            with self.subTest(changes=changes):
                review = prepare(manifest([entry(source, '"READY"', **changes)]))
                review.bind_source(PATH, source, sha(source))
                self.assertEqual(review.coverage()["entries"][0]["reason"], reason)

    def test_duplicates_and_overlaps_reject_all_conflicting_requests(self):
        source = 'class Rules { String mode="READY"; }'
        approved = entry(source, '"READY"')
        duplicate = copy.deepcopy(approved)
        review = prepare(manifest([approved, duplicate]))
        self.assertEqual(review.coverage()["rejectedEntries"], 2)
        self.assertEqual({x["reason"] for x in review.coverage()["entries"]}, {"duplicate_entry"})
        overlap = copy.deepcopy(approved)
        overlap["tokenByteStart"] += 1
        review = prepare(manifest([approved, overlap]))
        self.assertEqual({x["reason"] for x in review.coverage()["entries"]}, {"overlapping_entries"})

    def test_wrong_class_unknown_purpose_and_unrecognized_fields_fail_closed(self):
        source = 'class Rules { String mode="READY"; }'
        for data, reason in [(manifest([entry(source, '"READY"', classification="secret")]), "classification_not_nonsecret_policy"),
                             ({**manifest([entry(source, '"READY"')]), "purpose": "public-export"}, "unsupported_review_purpose"),
                             ({**manifest([entry(source, '"READY"')]), "value": "READY"}, "invalid_review_schema"),
                             (manifest([{**entry(source, '"READY"'), "value": "READY"}]), "invalid_entry_schema")]:
            with self.subTest(reason=reason):
                review = prepare(data)
                self.assertEqual(review.coverage()["entries"][0]["reason"], reason)
                self.assertNotIn("READY", json.dumps(review.coverage()))

    def test_grammar_and_review_id_not_freeform_permission(self):
        source = 'class Rules { String mode="READY"; }'
        for changes in ({"path": "../outside.java"}, {"path": "*.java"}, {"reasonCode": "raw prose"},
                        {"usageContext": "a" * 65}, {"reviewId": "another-review"}):
            with self.subTest(changes=changes):
                review = prepare(manifest([entry(source, '"READY"', **changes)]))
                self.assertEqual(review.coverage()["rejectedEntries"], 1)

    def test_not_observed_and_unselected_path_remain_in_requested_denominator(self):
        source = 'class Rules { String mode="READY"; }'
        data = manifest([entry(source, '"READY"'), entry(source, '"READY"', path="synthetic/Unseen.java")])
        review = prepare(data)
        review.bind_source(PATH, source, sha(source))
        self.assertEqual(review.summary()["notObservedEntries"], 2)
        self.assertEqual(review.coverage(PATH)["requestedEntries"], 1)
        self.assertEqual(review.coverage("synthetic/Unseen.java")["requestedEntries"], 1)
        self.assertTrue(review.summary()["allRequestsAccounted"])

    def test_manifest_hash_is_canonical_and_caller_mutation_cannot_add_permissions(self):
        source = 'class Rules { String mode="READY"; }'
        data = manifest([entry(source, '"READY"')])
        review = prepare(data)
        reverse = {key: data[key] for key in reversed(data)}
        self.assertEqual(review.manifestSha256, prepare(reverse).manifestSha256)
        data["entries"].clear()
        _, result = self.admit(source, '"READY"', review=review)
        self.assertEqual(result["status"], "admitted")
        self.assertEqual(review.coverage()["requestedEntries"], 1)

    def test_sensitive_and_unknown_contexts_are_terminal_vetoes(self):
        source = 'class Rules { String mode="READY"; }'
        for context, reason in [(True, "sensitive_context"), (None, "context_not_verified")]:
            with self.subTest(context=context):
                review, result = self.admit(source, '"READY"', sensitive_context=context)
                self.assertEqual(result["reason"], reason)
                _, repeated = self.admit(source, '"READY"', review=review)
                self.assertNotIn("value", repeated)
                self.assertEqual(review.coverage()["rejectedEntries"], 1)

    def test_fragment_veto_revokes_token_permission_without_claiming_emission(self):
        source = 'class Rules { String mode="READY"; }'
        review, result = self.admit(source, '"READY"')
        review.reject(result["requestIndex"], "fragment_redacted")
        self.assertEqual(review.summary()["admittedEntries"], 0)
        self.assertEqual(review.coverage()["entries"][0]["reason"], "fragment_redacted")
        with self.assertRaisesRegex(literals.LiteralReviewError, "invalid_review_rejection"):
            review.reject(0, "unbounded raw source prose")

    def test_injected_private_identity_and_email_vetoes(self):
        for value, profile in [("FictionalMember", privacy_guard.build_profile(["FictionalMember"], [], key=b"x" * 32)),
                               ("fixture@example.test", privacy_guard.build_profile([], ["fixture@example.test"], key=b"x" * 32))]:
            with self.subTest(kind="synthetic-private-value"):
                token = '"' + value + '"'
                source = "class Rules { String mode=" + token + "; }"
                review = prepare(manifest([entry(source, token)]), profile=profile)
                _, result = self.admit(source, token, review=review)
                self.assertEqual(result["reason"], "privacy_denied")
                self.assertNotIn(value, json.dumps(result))
                self.assertNotIn(value, json.dumps(review.coverage()))

    def test_effective_configured_profile_is_mandatory_without_injection(self):
        value = "FictionalMember"
        token = '"' + value + '"'
        source = "class Rules { String mode=" + token + "; }"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "profile.json"
            path.write_text(json.dumps(privacy_guard.build_profile([value], [], key=b"x" * 32)))
            path.chmod(0o600)
            with mock.patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(path)}):
                review = prepare(manifest([entry(source, token)]))
                _, result = self.admit(source, token, review=review)
                self.assertEqual(result["reason"], "privacy_denied")

    def test_generic_email_secret_and_escaped_secret_vetoes(self):
        values = ["fixture" + "@" + "privacy-fixture.localdomain", "sk-proj-" + "x" * 32]
        for value in values:
            token = '"' + value + '"'
            source = "class Rules { String mode=" + token + "; }"
            review, result = self.admit(source, token)
            self.assertEqual(result["reason"], "privacy_denied")
            self.assertNotIn(value, json.dumps(result))
        token = '"\\163\\153-proj-' + "x" * 32 + '"'
        source = "class Rules { String mode=" + token + "; }"
        review, result = self.admit(source, token)
        self.assertEqual(result["reason"], "privacy_denied")
        self.assertNotIn("value", result)

    def test_decoded_value_mismatch_and_unproven_unicode_escape_are_rejected(self):
        source = 'class Rules { String mode="READY"; }'
        review, result = self.admit(source, '"READY"', decoded_value="DIFFERENT")
        self.assertEqual(result["reason"], "literal_value_mismatch")
        source = 'class Rules { String mode="\\u0041"; }'
        review = prepare(manifest([entry(source, '"\\u0041"')]))
        review.bind_source(PATH, source, sha(source))
        self.assertEqual(review.coverage()["entries"][0]["reason"], "unsupported_literal_encoding")

    def test_quoted_character_and_standard_escapes_preserve_actual_value(self):
        source = "class Rules { char mode='X'; }"
        review, result = self.admit(source, "'X'")
        self.assertEqual((result["value"], result["literalType"]), ("X", "character"))
        source = 'class Rules { String mode="line\\nnext"; }'
        review, result = self.admit(source, '"line\\nnext"')
        self.assertEqual(result["value"], "line\nnext")

    def test_injected_profile_mutation_cannot_remove_a_veto(self):
        value = "FictionalMember"
        source = 'class Rules { String mode="' + value + '"; }'
        token = '"' + value + '"'
        profile = privacy_guard.build_profile([value], [], key=b"x" * 32)
        review = prepare(manifest([entry(source, token)]), profile=profile)
        profile["denyNames"].clear()
        _, result = self.admit(source, token, review=review)
        self.assertEqual(result["reason"], "privacy_denied")

    def test_invalid_empty_manifest_never_reports_all_admitted(self):
        review = prepare({**manifest([]), "purpose": "unknown"})
        self.assertFalse(review.summary()["allRequestedAdmitted"])

    def test_direct_spec_client_preserves_injected_bundled_privacy_guard(self):
        spec = importlib.util.spec_from_file_location("literal_review_injected_fixture", SCRIPTS / "pipeline_literals.py")
        module = importlib.util.module_from_spec(spec)
        module.privacy_guard = privacy_guard
        original_import = builtins.__import__
        def checked_import(name, *args, **kwargs):
            if name == "privacy_guard":
                raise AssertionError("must retain verified injected sibling")
            return original_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=checked_import):
            spec.loader.exec_module(module)
        self.assertIs(module.privacy_guard, privacy_guard)
        source = 'class Rules { String mode="READY"; }'
        review = module.prepare_review(manifest([entry(source, '\"READY\"')]), source_fingerprint=FINGERPRINT)
        bound = review.bind_source(PATH, source, sha(source))
        start = source.index('\"READY\"')
        self.assertEqual(bound.admit(start, start + 7, sensitive_context=False)["status"], "admitted")

    def test_manifest_budget_and_non_json_values_fail_with_fixed_diagnostics(self):
        with self.assertRaisesRegex(literals.LiteralReviewError, "review_manifest_budget_exceeded"):
            prepare({**manifest([]), "extra": "x" * literals.MAX_MANIFEST_BYTES})
        with self.assertRaisesRegex(literals.LiteralReviewError, "invalid_review_manifest"):
            prepare({**manifest([]), "extra": float("nan")})
        with self.assertRaisesRegex(literals.LiteralReviewError, "invalid_review_manifest"):
            prepare(manifest([{}] * (literals.MAX_ENTRIES + 1)))


if __name__ == "__main__":
    unittest.main()
