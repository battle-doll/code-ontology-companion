"""Exact-occurrence, independently reviewed literals for private analysis.

This module does not discover files, classify strings by spelling/API, authorize
publication, or execute target code. A caller explicitly supplies a trusted
review manifest. SourceScope/authorization provenance belongs to its private
sidecar. Review metadata records a claim; it is not identity attestation.

When a review is active the lexer MUST use ``bound.opaque_id`` for *every*
quoted occurrence, including unreviewed ones. Never propagate an admission by
raw value or the legacy same-spelling opaque ID. Fragment-level sensitive and
privacy vetoes remain mandatory and must revoke provisional admissions through
``review.reject`` before serialization. ``admitted`` means token permission only,
not proof that the parser emitted a literal or preserved complete policy meaning.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

if "privacy_guard" not in globals():
    import privacy_guard

FORMAT = "companion.reviewed-literals.v1"
PURPOSE = "private-policy-analysis"
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ENTRIES = 5_000
MAX_LITERAL_CHARS = 4_096
MAX_SOURCE_BYTES = 2 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_REVIEW_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TOP = {"format", "purpose", "sourceFingerprint", "review", "entries"}
_META = {"reviewId", "reviewerKind", "reviewedAt"}
_ENTRY = {"path", "sourceSha256", "tokenByteStart", "tokenByteEnd", "tokenSha256",
          "classification", "reasonCode", "usageContext", "reviewId"}
_REVOKE = {"sensitive_context", "context_not_verified", "privacy_denied", "fragment_redacted",
           "unsupported_literal_encoding", "literal_value_mismatch"}
_UNSET = object()


class LiteralReviewError(ValueError):
    """Fixed diagnostics; never include values, input filenames or profiles."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise LiteralReviewError("invalid_review_manifest") from None


def _path(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and len(value) <= 4096
            and not any(char in value for char in "\\:\x00*?[]")
            and not PurePosixPath(value).is_absolute()
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def opaque_occurrence_id(path: str, source_sha256: str, token_char_start: int, token_char_end: int) -> str:
    """Unique source occurrence, using Python-character offsets (not value hashes)."""
    if (not _path(path) or not isinstance(source_sha256, str) or not _HEX.fullmatch(source_sha256)
            or type(token_char_start) is not int or type(token_char_end) is not int
            or not 0 <= token_char_start < token_char_end <= MAX_SOURCE_BYTES):
        raise LiteralReviewError("invalid_literal_occurrence")
    return "literal-occurrence:" + hashlib.sha256(_canonical(
        [path, source_sha256, "python_char_offsets", token_char_start, token_char_end])).hexdigest()


def _decode_quoted(raw: str) -> tuple[str, str]:
    """Conservative Java quoted literal decoder; no Unicode prelexing guesses."""
    if len(raw) < 2 or raw[0] not in "\"'" or raw[-1] != raw[0] or raw.startswith('"""'):
        raise LiteralReviewError("token_not_quoted_literal")
    quote = raw[0]
    text = raw[1:-1]
    output = []
    index = 0
    escapes = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r",
               "\"": "\"", "'": "'", "\\": "\\", "s": " "}
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 1
            if index == len(text):
                raise LiteralReviewError("unsupported_literal_encoding")
            char = text[index]
            if char in escapes:
                output.append(escapes[char]); index += 1
            elif char in "01234567":
                end = index + 1
                maximum = 3 if char in "0123" else 2
                while end < len(text) and end - index < maximum and text[end] in "01234567":
                    end += 1
                output.append(chr(int(text[index:end], 8))); index = end
            else:
                # Java Unicode preprocessing can change lexer boundaries; the
                # existing lexer has not proven that phase. Keep it unknown.
                raise LiteralReviewError("unsupported_literal_encoding")
        elif char == quote or char in "\n\r" or 0xD800 <= ord(char) <= 0xDFFF:
            raise LiteralReviewError("unsupported_literal_encoding")
        else:
            output.append(char); index += 1
    decoded = "".join(output)
    if quote == "'" and (len(decoded) != 1 or ord(decoded) > 0xFFFF):
        raise LiteralReviewError("unsupported_literal_encoding")
    if len(decoded) > MAX_LITERAL_CHARS:
        raise LiteralReviewError("literal_value_too_large")
    return decoded, "string" if quote == '"' else "character"


class LiteralReview:
    def __init__(self, manifest: dict, encoded: bytes, source_fingerprint: str, profile: dict | None,
                 context_roots):
        self.manifestSha256 = hashlib.sha256(encoded).hexdigest()
        self.manifest_sha256 = self.manifestSha256
        self.source_fingerprint = source_fingerprint
        self._profile = profile
        self._roots = tuple(context_roots)
        self._entries = []
        self._review_id = None
        self._bound = None
        self.valid = False
        entries = manifest.get("entries", [])
        for index, entry in enumerate(entries):
            self._entries.append({"index": index, "entry": entry, "status": "not_observed",
                                  "reason": "requested_not_observed"})
        reason = self._top_reason(manifest)
        if reason:
            for state in self._entries:
                self._reject_state(state, reason)
            self._manifest_reason = reason
            return
        self.valid = True
        self._manifest_reason = None
        self._review_id = manifest["review"]["reviewId"]
        for state in self._entries:
            reason = self._entry_reason(state["entry"])
            if reason:
                self._reject_state(state, reason)
        groups = {}
        for state in self._entries:
            if state["status"] != "rejected":
                entry = state["entry"]
                groups.setdefault(entry["path"], []).append(state)
        for states in groups.values():
            states.sort(key=lambda s: (s["entry"]["tokenByteStart"], s["entry"]["tokenByteEnd"]))
            for index, current in enumerate(states):
                for previous in reversed(states[:index]):
                    left, right = previous["entry"], current["entry"]
                    if left["tokenByteEnd"] <= right["tokenByteStart"]:
                        continue
                    reason = ("duplicate_entry" if (left["tokenByteStart"], left["tokenByteEnd"]) ==
                              (right["tokenByteStart"], right["tokenByteEnd"]) else "overlapping_entries")
                    self._reject_state(previous, reason); self._reject_state(current, reason)

    def __repr__(self):
        return "<LiteralReview>"

    def _guard(self, value):
        privacy_guard.ensure_public_safe(value, profile=self._profile, context_roots=self._roots)

    @staticmethod
    def _reject_state(state, reason):
        state["status"] = "rejected"
        state["reason"] = reason

    def _top_reason(self, manifest):
        if set(manifest) != _TOP or not isinstance(manifest.get("review"), dict):
            return "invalid_review_schema"
        if manifest["format"] != FORMAT:
            return "unsupported_review_format"
        if manifest["purpose"] != PURPOSE:
            return "unsupported_review_purpose"
        if manifest["sourceFingerprint"] != self.source_fingerprint:
            return "source_fingerprint_mismatch"
        review = manifest["review"]
        if (set(review) != _META or review.get("reviewerKind") != "independent_source_review"
                or not isinstance(review.get("reviewId"), str) or not _REVIEW_ID.fullmatch(review["reviewId"])
                or not isinstance(review.get("reviewedAt"), str) or len(review["reviewedAt"]) > 64):
            return "invalid_review_metadata"
        try:
            date = datetime.datetime.fromisoformat(review["reviewedAt"].replace("Z", "+00:00"))
            if date.tzinfo is None:
                return "invalid_review_metadata"
            self._guard({key: value for key, value in manifest.items() if key != "entries"})
        except (ValueError, privacy_guard.PrivacyError):
            return "review_metadata_privacy_or_format_denied"
        return None

    def _entry_reason(self, entry):
        if not isinstance(entry, dict) or set(entry) != _ENTRY:
            return "invalid_entry_schema"
        if not _path(entry["path"]):
            return "invalid_entry_path"
        if not isinstance(entry["sourceSha256"], str) or not _HEX.fullmatch(entry["sourceSha256"]):
            return "invalid_source_sha256"
        if (type(entry["tokenByteStart"]) is not int or type(entry["tokenByteEnd"]) is not int
                or not 0 <= entry["tokenByteStart"] < entry["tokenByteEnd"] <= MAX_SOURCE_BYTES):
            return "invalid_token_span"
        if not isinstance(entry["tokenSha256"], str) or not _HEX.fullmatch(entry["tokenSha256"]):
            return "invalid_token_sha256"
        if entry["classification"] != "nonsecret_policy":
            return "classification_not_nonsecret_policy"
        if entry["reviewId"] != self._review_id:
            return "review_id_mismatch"
        if any(not isinstance(entry[key], str) or not _CODE.fullmatch(entry[key]) for key in ("reasonCode", "usageContext")):
            return "invalid_review_code"
        try:
            self._guard(entry)
        except privacy_guard.PrivacyError:
            return "privacy_denied"
        return None

    def bind_source(self, path: str, source: str, source_sha256: str):
        if (not _path(path) or not isinstance(source, str) or not isinstance(source_sha256, str)
                or not _HEX.fullmatch(source_sha256)):
            raise LiteralReviewError("invalid_review_source")
        if (self._bound is not None and self._bound.path == path and self._bound.source is source
                and self._bound.source_sha256 == source_sha256):
            return self._bound
        self._bound = ReviewedSource(self, path, source, source_sha256)
        return self._bound

    def admit(self, path, source_sha256, source, token_char_start, token_char_end, decoded_value=_UNSET,
              *, sensitive_context, allow_reviewed_empty=False):
        return self.bind_source(path, source, source_sha256).admit(
            token_char_start, token_char_end, decoded_value, sensitive_context=sensitive_context,
            allow_reviewed_empty=allow_reviewed_empty)

    def reject(self, request_index: int, reason: str):
        if type(request_index) is not int or not 0 <= request_index < len(self._entries) or reason not in _REVOKE:
            raise LiteralReviewError("invalid_review_rejection")
        self._reject_state(self._entries[request_index], reason)

    def coverage(self, path=None):
        states = [s for s in self._entries if path is None or
                  (isinstance(s["entry"], dict) and s["entry"].get("path") == path)]
        counts = {status: sum(state["status"] == status for state in states)
                  for status in ("admitted", "rejected", "not_observed")}
        result = {"format": FORMAT, "purpose": PURPOSE, "manifestSha256": self.manifestSha256,
                  "manifestValid": self.valid, "requestedEntries": len(states),
                  "admittedEntries": counts["admitted"], "rejectedEntries": counts["rejected"],
                  "notObservedEntries": counts["not_observed"], "allRequestsAccounted": sum(counts.values()) == len(states),
                  "allRequestedAdmitted": self.valid and counts["admitted"] == len(states), "publicDisclosureAuthorized": False,
                  "admissionMeaning": "token_permission_not_parser_or_policy_completeness",
                  "entries": [{"requestIndex": state["index"], "status": state["status"], "reason": state["reason"],
                               **{key: state["entry"].get(key) if isinstance(state["entry"], dict) and
                                  type(state["entry"].get(key)) is int and 0 <= state["entry"][key] <= MAX_SOURCE_BYTES else None
                                  for key in ("tokenByteStart", "tokenByteEnd")}} for state in states]}
        if self._manifest_reason:
            result["manifestReason"] = self._manifest_reason
        return result

    def summary(self):
        return {key: value for key, value in self.coverage().items() if key != "entries"}


class ReviewedSource:
    def __init__(self, review, path, source, source_sha256):
        self.review = review
        self.path = path
        self.source = source
        self.source_sha256 = source_sha256
        self._matches = {}
        try:
            encoded = source.encode("utf-8")
        except UnicodeError:
            raise LiteralReviewError("invalid_review_source_encoding") from None
        states = [state for state in review._entries if isinstance(state["entry"], dict)
                  and state["entry"].get("path") == path and state["status"] != "rejected"]
        argument_digest_valid = len(encoded) <= MAX_SOURCE_BYTES and hashlib.sha256(encoded).hexdigest() == source_sha256
        for state in states:
            entry = state["entry"]
            if not argument_digest_valid:
                review._reject_state(state, "source_digest_argument_mismatch"); continue
            if entry["sourceSha256"] != source_sha256:
                review._reject_state(state, "source_sha256_mismatch"); continue
            start, end = entry["tokenByteStart"], entry["tokenByteEnd"]
            if end > len(encoded):
                review._reject_state(state, "invalid_token_span"); continue
            try:
                before = encoded[:start].decode("utf-8")
                raw = encoded[start:end].decode("utf-8")
                encoded[:end].decode("utf-8")
            except UnicodeError:
                review._reject_state(state, "token_span_not_utf8_boundary"); continue
            if hashlib.sha256(encoded[start:end]).hexdigest() != entry["tokenSha256"]:
                review._reject_state(state, "token_hash_mismatch"); continue
            try:
                _decode_quoted(raw)
            except LiteralReviewError as exc:
                review._reject_state(state, str(exc)); continue
            self._matches[(len(before), len(before) + len(raw))] = state

    def __repr__(self):
        return "<ReviewedSource>"

    def opaque_id(self, token_char_start, token_char_end):
        return opaque_occurrence_id(self.path, self.source_sha256, token_char_start, token_char_end)

    def admit(self, token_char_start, token_char_end, decoded_value=_UNSET, *, sensitive_context, allow_reviewed_empty=False):
        occurrence = self.opaque_id(token_char_start, token_char_end)
        state = self._matches.get((token_char_start, token_char_end))
        if state is None:
            return {"status": "unreviewed", "reason": "occurrence_not_reviewed", "opaqueOccurrenceId": occurrence}
        result = {"status": "rejected", "requestIndex": state["index"], "opaqueOccurrenceId": occurrence}
        if state["status"] == "rejected":
            return {**result, "reason": state["reason"]}
        reason = "sensitive_context" if sensitive_context is True else "context_not_verified" if sensitive_context is not False else None
        empty_sensitive_marker = False
        try:
            value, kind = _decode_quoted(self.source[token_char_start:token_char_end])
            if allow_reviewed_empty is True and sensitive_context is True and kind == "string" and value == "":
                # Empty contains no value characters; this exception still
                # requires the exact reviewed occurrence and every guard.
                reason = None
                empty_sensitive_marker = True
            if decoded_value is not _UNSET and (not isinstance(decoded_value, str) or decoded_value != value):
                reason = reason or "literal_value_mismatch"
            # Scan both spellings; decoded octal/escaped forms cannot evade the
            # configured identity/secret scanner. No value reaches diagnostics.
            self.review._guard(self.source[token_char_start:token_char_end])
            self.review._guard(value)
        except privacy_guard.PrivacyError:
            reason = "privacy_denied"
        except LiteralReviewError as exc:
            reason = str(exc)
        if reason:
            self.review._reject_state(state, reason)
            return {**result, "reason": reason}
        entry = state["entry"]
        proof = {"format": FORMAT, "purpose": PURPOSE, "manifestSha256": self.review.manifestSha256,
                 "reviewId": self.review._review_id, "reasonCode": entry["reasonCode"], "usageContext": entry["usageContext"],
                 "sourceBinding": {key: entry[key] for key in ("path", "sourceSha256", "tokenByteStart", "tokenByteEnd")},
                 "identityScope": "source_occurrence", "publicDisclosureAuthorized": False}
        if empty_sensitive_marker:
            proof["emptySensitiveMarker"] = True
        output = {"status": "admitted", "requestIndex": state["index"], "opaqueOccurrenceId": occurrence,
                  "value": value, "literalType": kind, "review": proof}
        try:
            self.review._guard(output)
        except privacy_guard.PrivacyError:
            self.review._reject_state(state, "privacy_denied")
            return {**result, "reason": "privacy_denied"}
        state["status"] = "admitted"; state["reason"] = "reviewed_nonsecret_occurrence"
        return output


def prepare_review(manifest, *, source_fingerprint: str, profile=None, context_roots=()) -> LiteralReview:
    """Prepare one explicit private input; reject malformed/unbounded envelopes.

    ``profile=None`` uses the existing effective configured profile, never a
    profile-free bypass. An injected profile uses the same mandatory scanner.
    Invalid purpose/pins/entries retain a per-request rejected coverage record.
    Source binding does not authorize publication or prove policy semantics.
    """
    if (not isinstance(source_fingerprint, str) or not _HEX.fullmatch(source_fingerprint)
            or not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), list)
            or len(manifest["entries"]) > MAX_ENTRIES):
        raise LiteralReviewError("invalid_review_manifest")
    encoded = _canonical(manifest)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise LiteralReviewError("review_manifest_budget_exceeded")
    # Detach caller-owned containers so mutation after preparation cannot change
    # the content represented by manifestSha256 or add an occurrence silently.
    detached = json.loads(encoded)
    injected = json.loads(_canonical(profile)) if profile is not None else None
    return LiteralReview(detached, encoded, source_fingerprint, injected, context_roots)
