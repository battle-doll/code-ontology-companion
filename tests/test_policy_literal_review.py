"""Exact-occurrence private review integration; all fixtures are synthetic."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
import pipeline_literals
import policy_semantics
import privacy_guard


def reviewed(source, occurrences, *, profile=None):
    digest = hashlib.sha256(source.encode()).hexdigest()
    entries = []
    for start, end in occurrences:
        entries.append({"path": "Rules.java", "sourceSha256": digest,
            "tokenByteStart": len(source[:start].encode()), "tokenByteEnd": len(source[:end].encode()),
            "tokenSha256": hashlib.sha256(source[start:end].encode()).hexdigest(),
            "classification": "nonsecret_policy", "reasonCode": "synthetic_policy_constant",
            "usageContext": "synthetic_test", "reviewId": "synthetic-review"})
    review = pipeline_literals.prepare_review({"format": pipeline_literals.FORMAT, "purpose": pipeline_literals.PURPOSE,
        "sourceFingerprint": "0" * 64, "review": {"reviewId": "synthetic-review",
        "reviewerKind": "independent_source_review", "reviewedAt": "2026-01-01T00:00:00Z"}, "entries": entries},
        source_fingerprint="0" * 64, profile=profile)
    return review, digest


def occurrence(source, value, start=0):
    left = source.index(value, start)
    return left, left + len(value)


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


class PolicyLiteralReviewTests(unittest.TestCase):
    def test_only_reviewed_occurrence_visible_and_opaque_ids_do_not_correlate(self):
        source = 'class Rules { String a="PUBLIC_MODE"; String b="PUBLIC_MODE"; }'
        review, digest = reviewed(source, [occurrence(source, '"PUBLIC_MODE"')])
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        visible = [node for node in walk(result) if node.get("op") == "literal" and node.get("type") == "string"]
        self.assertEqual([node["value"] for node in visible], ["PUBLIC_MODE"])
        ids = [row["literalIdentities"]["opaqueIds"][0] for row in result["fragments"]]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(row["literalIdentities"]["scope"] == "source_occurrence" for row in result["fragments"]))
        self.assertEqual(review.coverage()["admittedEntries"], 1)
        self.assertFalse(visible[0]["literalReview"]["publicDisclosureAuthorized"])
        default = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest)
        self.assertNotIn("PUBLIC_MODE", json.dumps(default))

    def test_utf8_byte_offsets_and_escape_decoding_retain_review_proof(self):
        source = 'class Rules { /* 한글 */ String label="한글\\nMODE"; }'
        start, end = occurrence(source, '"한글\\nMODE"')
        review, digest = reviewed(source, [(start, end)])
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        node = result["fragments"][0]["expression"]
        self.assertEqual(node["value"], "한글\nMODE")
        self.assertEqual(node["literalReview"]["sourceBinding"]["tokenByteStart"], len(source[:start].encode()))

    def test_sensitive_identifier_and_profile_veto_override_review(self):
        for source, profile in (
                ('class Rules { String secret="PUBLIC_MODE"; }', None),
                ('class Rules { void f(){ setPassword("PUBLIC_MODE"); }}', None),
                ('class Rules { String label="Fictional Identity"; }', privacy_guard.build_profile(["Fictional Identity"], [], key=b"x" * 32))):
            token = '"PUBLIC_MODE"' if "PUBLIC_MODE" in source else '"Fictional Identity"'
            review, digest = reviewed(source, [occurrence(source, token)], profile=profile)
            result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
            self.assertNotIn(token[1:-1], json.dumps(result))
            self.assertEqual(review.coverage()["rejectedEntries"], 1)

    def test_fragment_parse_failure_revokes_provisional_admission(self):
        source = 'class Rules { Object x="PUBLIC_MODE" ??? thing; }'
        review, digest = reviewed(source, [occurrence(source, '"PUBLIC_MODE"')])
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        self.assertNotIn("PUBLIC_MODE", json.dumps(result))
        self.assertEqual(review.coverage()["entries"][0]["reason"], "fragment_redacted")

    def test_unreviewed_numeric_constructor_cannot_bypass_active_review(self):
        source = 'import java.math.BigDecimal; class Rules { Object n=new BigDecimal("123.45"); }'
        review, digest = reviewed(source, [])
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        self.assertNotIn("123.45", json.dumps(result))
        review, digest = reviewed(source, [occurrence(source, '"123.45"')])
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        self.assertTrue(any(node.get("value") == "123.45" and "literalReview" in node for node in walk(result)))

    def test_deferred_body_review_belongs_to_child_record(self):
        source = 'class Rules { void f(){ run(() -> { consume("PUBLIC_MODE"); }); }}'
        review, digest = reviewed(source, [occurrence(source, '"PUBLIC_MODE"')])
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        self.assertEqual(sum(node.get("value") == "PUBLIC_MODE" for node in walk(result)), 1)
        self.assertEqual(review.coverage()["admittedEntries"], 1)

    def test_later_revocation_removes_previously_materialized_value(self):
        source = 'class Rules { String a="PUBLIC_MODE"; String b="OTHER_MODE"; }'
        first = occurrence(source, '"PUBLIC_MODE"')
        second = occurrence(source, '"OTHER_MODE"')
        review, digest = reviewed(source, [first, second])
        bound = review.bind_source("Rules.java", source, digest)
        original_admit = bound.admit
        def admit(start, end, **kwargs):
            if start == second[0]:
                review.reject(0, "fragment_redacted")
            return original_admit(start, end, **kwargs)
        bound.admit = admit
        result = policy_semantics.extract_semantics(source, "Java", "Rules.java", digest, literal_review=review)
        self.assertNotIn("PUBLIC_MODE", json.dumps(result))
        self.assertIn("OTHER_MODE", json.dumps(result))
        self.assertIn("literal_review_revoked", result["fragments"][0]["unsupportedReasons"])


if __name__ == "__main__":
    unittest.main()
