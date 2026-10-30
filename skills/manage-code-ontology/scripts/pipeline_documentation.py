"""Bounded source documentation claims with exact private review provenance.

Comments are untrusted source data, never instructions, verified policy or
execution evidence. All recognized Java comments enter the inventory. Their
text is withheld unless the exact complete token passes an independent review
manifest and the mandatory privacy scanner. No spelling-based allowlist or
application-specific classifier is used. Review identity is a supplied claim,
not reviewer authentication or public disclosure authorization.
"""
from __future__ import annotations

import datetime
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import unquote

if "privacy_guard" not in globals():
    import privacy_guard

FORMAT = "companion.reviewed-documentation.v1"
PURPOSE = "private-policy-analysis"
EXTRACTOR_VERSION = "source-documentation-1"
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ENTRIES = 5_000
MAX_COMMENT_BYTES = 8_192
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_FRAGMENTS = 20_000
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_REVIEW_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TOP = {"format", "purpose", "sourceFingerprint", "review", "entries"}
_META = {"reviewId", "reviewerKind", "reviewedAt"}
_ENTRY = {"path", "sourceSha256", "tokenByteStart", "tokenByteEnd", "tokenSha256",
          "classification", "reasonCode", "usageContext", "reviewId"}
_REVOKE = {"privacy_denied", "fragment_redacted", "review_revoked", "source_changed"}
_UNICODE = re.compile(r"\\u+[0-9a-fA-F]{4}")
_VALUE_ASSIGNMENT = re.compile(
    r"\b[a-z0-9_$]*(?:password|passwd|secret|credential|token|key|authorization)[a-z0-9_$]*"
    r"[\"']?\s*(?::|=(?!=))\s*\S", re.I)
_ESCAPE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|x([0-9a-fA-F]{2}))")


class DocumentationReviewError(ValueError):
    """Fixed diagnostics; never embed inspected source or manifest values."""


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DocumentationReviewError("invalid_review_manifest") from None


def _path(value):
    return (isinstance(value, str) and bool(value) and len(value) <= 4096
            and not any(char in value for char in "\\:\x00*?[]")
            and not PurePosixPath(value).is_absolute()
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def _hash(value):
    return hashlib.sha256(value).hexdigest()


class _InspectionText(HTMLParser):
    """Formatting projection for veto checks only; never emitted as source."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _underscore_emphasis(text):
    """Inspect paired outer emphasis without deleting intraword underscores.

    This deliberately bounded Markdown subset is a privacy projection, not a
    renderer. An unmatched opening or mismatched pair is withheld explicitly.
    Literal suffix/intraword underscores are preserved.
    """
    stack, removed = [], set()
    def word(char):
        return bool(char) and (char.isalnum() or char == "_")
    for match in re.finditer(r"_+", text):
        start, end = match.span()
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        opening = not word(before) and bool(after) and not after.isspace()
        closing = bool(before) and not before.isspace() and not word(after)
        if closing and stack:
            left, right = stack.pop()
            if end - start != right - left or end - start > 3:
                raise DocumentationReviewError("unsupported_documentation_format")
            removed.update(range(left, right)); removed.update(range(start, end))
        elif opening:
            if end - start > 3:
                raise DocumentationReviewError("unsupported_documentation_format")
            stack.append((start, end))
    if stack:
        raise DocumentationReviewError("unsupported_documentation_format")
    return "".join(char for index, char in enumerate(text) if index not in removed)


def _documentation_guard(text, guard):
    """Apply profile/builtin and assignment vetoes to raw and formatted views.

    These inspection-only views cannot authorize a comment or replace its
    sourceText. Exact occurrence review is still mandatory. HTML tags/entities,
    Markdown emphasis/code delimiters and Javadoc decoration cannot conceal
    denied identities, recognizable secrets or credential assignment values.
    """
    previous = None
    for _ in range(4):
        guard(text)
        normalized = unicodedata.normalize("NFKC", text)
        normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
        decorated = re.sub(r"(?m)^[ \t]*\*[ \t]?", "", normalized)
        parser = _InspectionText()
        try:
            parser.feed(decorated)
            parser.close()
        except Exception:
            raise privacy_guard.PrivacyError("unsupported_payload") from None
        html_plain = "".join(parser.parts)
        # Leading emphasis underscores must not hide a builtin word boundary;
        # unlike global deletion this keeps underscores inside credential names.
        boundary_plain = re.sub(r"(?<!\w)_+(?=\S)", "", html_plain)
        markers = [char for char in "`*~" if char in html_plain]
        inspected_views = [normalized, decorated, html_plain]
        # Preserve semantic underscores in all views. At most eight delimiter
        # combinations per view; malformed outer underscore markup fails closed.
        for base in (html_plain, boundary_plain):
            for mask in range(1 << len(markers)):
                removed = "".join(char for index, char in enumerate(markers) if mask & (1 << index))
                inspected_views.append(base.translate(str.maketrans("", "", removed)))
        seen_views = set()
        for inspected in inspected_views:
            if inspected in seen_views:
                continue
            seen_views.add(inspected)
            # Every normalized representation uses the identical configured
            # profile and builtin guard, not just the assignment-pattern veto.
            guard(inspected)
            if _VALUE_ASSIGNMENT.search(inspected):
                raise privacy_guard.PrivacyError("secret_token")
        emphasis_plain = _underscore_emphasis(html_plain)
        for mask in range(1 << len(markers)):
            removed = "".join(char for index, char in enumerate(markers) if mask & (1 << index))
            inspected = emphasis_plain.translate(str.maketrans("", "", removed))
            guard(inspected)
            if _VALUE_ASSIGNMENT.search(inspected):
                raise privacy_guard.PrivacyError("secret_token")
        if previous == text:
            return
        previous = text
        def decoded(match):
            value = int(next(group for group in match.groups() if group is not None), 16)
            return chr(value) if value <= 0x10FFFF else match.group(0)
        text = _ESCAPE.sub(decoded, html.unescape(unquote(text, encoding="utf-8", errors="replace")))
    if previous != text:
        raise privacy_guard.PrivacyError("encoding_depth")


class DocumentationReview:
    def __init__(self, manifest, encoded, source_fingerprint, profile, context_roots):
        self.manifest_sha256 = self.manifestSha256 = _hash(encoded)
        self.source_fingerprint = source_fingerprint
        self._profile = profile
        self._roots = tuple(context_roots)
        self._review_id = None
        self._entries = [{"index": i, "entry": entry, "status": "not_observed", "reason": "requested_not_observed"}
                         for i, entry in enumerate(manifest["entries"])]
        self._outputs = {}
        self._output_count = 0
        self._manifest_reason = self._top_reason(manifest)
        self.valid = self._manifest_reason is None
        if not self.valid:
            for state in self._entries:
                self._reject(state, self._manifest_reason)
            return
        self._review_id = manifest["review"]["reviewId"]
        groups = {}
        for state in self._entries:
            reason = self._entry_reason(state["entry"])
            if reason:
                self._reject(state, reason)
            else:
                groups.setdefault(state["entry"]["path"], []).append(state)
        for states in groups.values():
            ordered = sorted(states, key=lambda s: (s["entry"]["tokenByteStart"], s["entry"]["tokenByteEnd"]))
            active = []
            for state in ordered:
                entry = state["entry"]
                active = [other for other in active if other["entry"]["tokenByteEnd"] > entry["tokenByteStart"]]
                for other in active:
                    same = all(other["entry"][key] == entry[key] for key in ("tokenByteStart", "tokenByteEnd"))
                    reason = "duplicate_entry" if same else "overlapping_entries"
                    self._reject(other, reason); self._reject(state, reason)
                active.append(state)

    def __repr__(self):
        return "<DocumentationReview>"

    def _guard(self, value):
        privacy_guard.ensure_public_safe(value, profile=self._profile, context_roots=self._roots)

    def _reject(self, state, reason):
        state["status"] = "rejected"; state["reason"] = reason
        # Revoke every still-live output made by this review object, including
        # repeated extractions. Persisted copies require caller invalidation.
        reports = {}
        for output in self._outputs.pop(state["index"], []):
            fragment = output["fragment"]
            fragment.pop("sourceText", None); fragment.pop("documentationReview", None)
            fragment["sourceDisclosure"] = {"status": "rejected", "reason": reason}
            fragment["unsupportedReasons"] = ["documentation_enforcement_not_verified", reason]
            coverage = output.get("coverage")
            if coverage is not None:
                coverage["reviewedFragments"] -= 1
                coverage["blockedFragments"] += 1
                reports[id(coverage)] = (coverage, fragment["path"])
            self._output_count -= 1
        for coverage, path in reports.values():
            coverage["documentationReview"] = self.coverage(path)

    def reject(self, request_index, reason):
        if type(request_index) is not int or not 0 <= request_index < len(self._entries) or reason not in _REVOKE:
            raise DocumentationReviewError("invalid_review_rejection")
        self._reject(self._entries[request_index], reason)

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
        if entry["tokenByteEnd"] - entry["tokenByteStart"] > MAX_COMMENT_BYTES:
            return "comment_token_budget_exceeded"
        if not isinstance(entry["tokenSha256"], str) or not _HEX.fullmatch(entry["tokenSha256"]):
            return "invalid_token_sha256"
        if entry["classification"] != "nonsecret_documentation":
            return "classification_not_nonsecret_documentation"
        if entry["reviewId"] != self._review_id:
            return "review_id_mismatch"
        if any(not isinstance(entry[key], str) or not _CODE.fullmatch(entry[key]) for key in ("reasonCode", "usageContext")):
            return "invalid_review_code"
        try:
            self._guard(entry)
        except privacy_guard.PrivacyError:
            return "privacy_denied"
        return None

    def _bind(self, path, encoded, source_digest):
        matches = {}
        for state in self._entries:
            entry = state["entry"]
            if not isinstance(entry, dict) or entry.get("path") != path:
                continue
            if type(entry.get("tokenByteStart")) is int and type(entry.get("tokenByteEnd")) is int:
                matches.setdefault((entry["tokenByteStart"], entry["tokenByteEnd"]), []).append(state)
            if state["status"] == "rejected":
                continue
            if entry["sourceSha256"] != source_digest:
                self._reject(state, "source_sha256_mismatch"); continue
            start, end = entry["tokenByteStart"], entry["tokenByteEnd"]
            if end > len(encoded):
                self._reject(state, "invalid_token_span"); continue
            try:
                encoded[start:end].decode("utf-8")
                # Start/end validity does not require decoding every prefix.
                if start < len(encoded) and encoded[start] & 0xC0 == 0x80:
                    raise UnicodeError
                if end < len(encoded) and encoded[end] & 0xC0 == 0x80:
                    raise UnicodeError
            except UnicodeError:
                self._reject(state, "token_span_not_utf8_boundary"); continue
            if _hash(encoded[start:end]) != entry["tokenSha256"]:
                self._reject(state, "token_hash_mismatch")
        return matches

    def _admit(self, states, raw, fragment):
        if not states:
            return "unreviewed", "occurrence_not_reviewed"
        if len(states) != 1:
            return "rejected", "ambiguous_review_occurrence"
        state = states[0]
        if state["status"] == "rejected":
            return "rejected", state["reason"]
        try:
            _documentation_guard(raw, self._guard)
        except privacy_guard.PrivacyError:
            self._reject(state, "privacy_denied")
            return "rejected", "privacy_denied"
        except DocumentationReviewError:
            self._reject(state, "unsupported_documentation_format")
            return "rejected", "unsupported_documentation_format"
        if self._output_count >= MAX_ENTRIES:
            self._reject(state, "review_output_budget_exceeded")
            return "rejected", "review_output_budget_exceeded"
        entry = state["entry"]
        fragment["sourceText"] = raw
        fragment["documentationReview"] = {"format": FORMAT, "purpose": PURPOSE,
            "manifestSha256": self.manifest_sha256, "sourceFingerprint": self.source_fingerprint,
            "reviewId": self._review_id, "requestIndex": state["index"],
            "reasonCode": entry["reasonCode"], "usageContext": entry["usageContext"],
            "sourceBinding": {key: entry[key] for key in ("path", "sourceSha256", "tokenByteStart", "tokenByteEnd", "tokenSha256")},
            "identityScope": "source_occurrence", "publicDisclosureAuthorized": False}
        try:
            self._guard(fragment)
        except privacy_guard.PrivacyError:
            fragment.pop("sourceText", None); fragment.pop("documentationReview", None)
            self._reject(state, "privacy_denied")
            return "rejected", "privacy_denied"
        state["status"] = "admitted"; state["reason"] = "reviewed_nonsecret_documentation_occurrence"
        self._outputs.setdefault(state["index"], []).append({"fragment": fragment, "coverage": None}); self._output_count += 1
        return "admitted", state["reason"]

    def coverage(self, path=None):
        states = [s for s in self._entries if path is None or (isinstance(s["entry"], dict) and s["entry"].get("path") == path)]
        counts = {status: sum(state["status"] == status for state in states) for status in ("admitted", "rejected", "not_observed")}
        result = {"format": FORMAT, "purpose": PURPOSE, "manifestSha256": self.manifest_sha256,
            "manifestValid": self.valid, "requestedEntries": len(states), "admittedEntries": counts["admitted"],
            "rejectedEntries": counts["rejected"], "notObservedEntries": counts["not_observed"],
            "allRequestsAccounted": sum(counts.values()) == len(states),
            "allRequestedAdmitted": self.valid and counts["admitted"] == len(states),
            "publicDisclosureAuthorized": False, "admissionMeaning": "comment_permission_not_enforcement_or_policy_completeness",
            "entries": [{"requestIndex": state["index"], "status": state["status"], "reason": state["reason"],
                **{key: state["entry"].get(key) if isinstance(state["entry"], dict) and type(state["entry"].get(key)) is int
                   and 0 <= state["entry"][key] <= MAX_SOURCE_BYTES else None for key in ("tokenByteStart", "tokenByteEnd")}}
                for state in states]}
        if self._manifest_reason:
            result["manifestReason"] = self._manifest_reason
        return result

    def summary(self):
        return {key: value for key, value in self.coverage().items() if key != "entries"}


def prepare_review(manifest, *, source_fingerprint, profile=None, context_roots=()):
    """Validate a bounded explicit private manifest, never discover or classify."""
    if isinstance(manifest, (str, bytes)):
        try:
            raw = manifest.encode("utf-8") if isinstance(manifest, str) else manifest
            if len(raw) > MAX_MANIFEST_BYTES:
                raise DocumentationReviewError("review_manifest_budget_exceeded")
            def pairs(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise DocumentationReviewError("duplicate_json_key")
                    value[key] = item
                return value
            manifest = json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, UnicodeError, RecursionError) as exc:
            if isinstance(exc, DocumentationReviewError):
                raise
            raise DocumentationReviewError("invalid_review_manifest") from None
    if (not isinstance(source_fingerprint, str) or not _HEX.fullmatch(source_fingerprint)
            or not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), list)
            or len(manifest["entries"]) > MAX_ENTRIES):
        raise DocumentationReviewError("invalid_review_manifest")
    encoded = _canonical(manifest)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise DocumentationReviewError("review_manifest_budget_exceeded")
    detached = json.loads(encoded)
    injected = json.loads(_canonical(profile)) if profile is not None else None
    return DocumentationReview(detached, encoded, source_fingerprint, injected, context_roots)


def _comments(source):
    """Yield complete comment tokens, or one explicit unknown lexical suffix."""
    # Unicode escapes precede Java lexical analysis and can create delimiters.
    # This scanner does not implement that phase; do not guess token boundaries.
    if _UNICODE.search(source):
        yield "unsupported", 0, len(source), "java_unicode_preprocessing_unsupported"
        return
    i, size = 0, len(source)
    while i < size:
        start = i
        if source.startswith("//", i):
            i += 2
            while i < size and source[i] not in "\r\n":
                i += 1
            yield "line", start, i, None
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                yield "block", start, size, "unterminated_comment"
                return
            i = end + 2
            yield "javadoc" if source.startswith("/**", start) else "block", start, i, None
        elif source.startswith('"""', i):
            opening_end = i + 3
            while opening_end < size and source[opening_end] in " \t\f":
                opening_end += 1
            if opening_end >= size or source[opening_end] not in "\r\n":
                yield "unsupported", start, size, "invalid_text_block_opening"
                return
            i = opening_end + 1
            while i < size:
                if source[i] == "\\":
                    i = min(size, i + 2)
                elif source.startswith('"""', i):
                    i += 3; break
                else:
                    i += 1
            else:
                yield "unsupported", start, size, "unterminated_text_block"
                return
        elif source[i] in "\"'":
            quote = source[i]; i += 1
            while i < size:
                if source[i] == "\\":
                    if i + 1 < size and source[i + 1] in "\r\n":
                        yield "unsupported", start, size, "invalid_quoted_line_continuation"
                        return
                    i = min(size, i + 2)
                elif source[i] == quote:
                    i += 1; break
                elif source[i] in "\r\n":
                    yield "unsupported", start, size, "unterminated_quoted_literal"
                    return
                else:
                    i += 1
            else:
                yield "unsupported", start, size, "unterminated_quoted_literal"
                return
        else:
            i += 1


def _target(context, path, digest, start, end):
    # A callback assertion plus matching file hash is not proof that its target
    # declaration/span/evidence ID exists. This standalone lexer has no verified
    # declaration inventory, so it never invokes or promotes such assertions.
    reason = "documentation_target_not_proven"
    if (isinstance(context, dict) and context.get("path") == path and context.get("sourceDigest") == digest
            and callable(context.get("documentationTarget"))):
        reason = "documentation_target_not_independently_verified"
    return {"resolution": "UNKNOWN", "reason": reason}


def extract_documentation(source, language, path, source_digest, review=None, java_type_context=None,
                          max_fragments=MAX_FRAGMENTS, local_access=None):
    """Return source claims with complete inventory/omission accounting.

    ``sourceText`` is the exact comment token including delimiters. Each record
    remains partial evidence: source wording is not implementation enforcement.
    ``review.reject`` revokes in-memory outputs; persisted copies must be
    invalidated by their owner before re-use.
    """
    if (not isinstance(source, str) or not _path(path) or not isinstance(source_digest, str)
            or not _HEX.fullmatch(source_digest) or type(max_fragments) is not int
            or not 0 <= max_fragments <= MAX_FRAGMENTS
            or (review is not None and not isinstance(review, DocumentationReview))
            or (local_access is not None and not isinstance(local_access, LocalSourceAccess))):
        raise DocumentationReviewError("invalid_documentation_source")
    try:
        encoded = source.encode("utf-8")
    except UnicodeError:
        raise DocumentationReviewError("invalid_documentation_source_encoding") from None
    fragments, omissions = [], []
    detected = 0; lexical_complete = True; seen = set()
    matches = review._bind(path, encoded, source_digest) if review else {}
    guard = review._guard if review else privacy_guard.ensure_public_safe
    initial_reason = ("source_budget_exceeded" if len(encoded) > MAX_SOURCE_BYTES else
                      "source_digest_argument_mismatch" if _hash(encoded) != source_digest else
                      "unsupported_language" if language != "Java" else None)
    if initial_reason:
        for states in matches.values():
            for state in states:
                if state["status"] != "rejected": review._reject(state, initial_reason)
        tokens = [("unsupported", 0, len(source), initial_reason)]
    else:
        tokens = _comments(source)
    char_cursor = byte_cursor = 0
    line = 1
    fragment_omitted = 0
    for kind, start, end, reason in tokens:
        before = source[char_cursor:start]
        byte_start = byte_cursor + len(before.encode("utf-8"))
        raw = source[start:end]
        byte_end = byte_start + len(raw.encode("utf-8"))
        line += len(re.findall(r"\r\n|\r|\n", before))
        line_end = line + len(re.findall(r"\r\n|\r|\n", raw))
        char_cursor, byte_cursor = end, byte_end
        span = {"lineStart": line, "lineEnd": line_end}; line = line_end
        source_range = {"charStart": start, "charEnd": end, "byteStart": byte_start, "byteEnd": byte_end}
        if kind == "unsupported":
            lexical_complete = False
            omissions.append({"reason": reason, "span": span, "sourceRange": source_range, "commentCount": "UNKNOWN"})
            continue
        detected += 1
        states = matches.get((byte_start, byte_end), [])
        seen.update(state["index"] for state in states)
        if reason:
            lexical_complete = False
        if len(fragments) >= max_fragments:
            fragment_omitted += 1
            for state in states:
                if state["status"] != "rejected": review._reject(state, "fragment_budget_exceeded")
            continue
        fragment = {"id": "semantic-documentation:" + _hash(_canonical([path, source_digest, byte_start, byte_end, EXTRACTOR_VERSION])),
            "name": "Source documentation", "path": path, "sourceDigest": source_digest, "language": language,
            "category": "source_documentation", "extractorVersion": EXTRACTOR_VERSION,
            "span": span, "sourceRange": source_range, "commentKind": kind,
            "commentSha256": _hash(encoded[byte_start:byte_end]), "representationStatus": "partial",
            "expression": None, "references": [], "instructionAuthority": "none",
            "evidence": {"kind": "source_documentation", "interpretation": "documentation_claim", "enforcement": "UNKNOWN"},
            "businessMeaningVerified": False, "runtimeStatus": "not_observed",
            "target": _target(java_type_context, path, source_digest, start, end),
            "unsupportedReasons": ["documentation_enforcement_not_verified"]}
        reason = reason or ("comment_token_budget_exceeded" if byte_end - byte_start > MAX_COMMENT_BYTES else None)
        if reason:
            for state in states:
                if state["status"] != "rejected": review._reject(state, reason)
            status = "rejected" if states else "withheld"
        else:
            status, reason = review._admit(states, raw, fragment) if review else ("unreviewed", "review_not_supplied")
        if status in {"admitted", "rejected", "withheld"} and local_access is not None:
            local_access._observe_existing(path, source_digest, byte_start, byte_end, raw, status)
        if status == "unreviewed" and local_access is not None:
            capture = local_access._admit(path, source_digest, byte_start, byte_end, raw, fragment)
            if capture is not None: status, reason = capture
        fragment["sourceDisclosure"] = {"status": status, "reason": reason}
        if status != "admitted":
            fragment["unsupportedReasons"].append(reason)
        try:
            guard(fragment)
        except privacy_guard.PrivacyError:
            for state in states:
                if state["status"] != "rejected": review._reject(state, "privacy_denied")
            omissions.append({"reason": "metadata_privacy_denied", "span": span, "sourceRange": source_range, "commentCount": 1})
            continue
        fragments.append(fragment)
    if fragment_omitted:
        omissions.append({"reason": "fragment_budget_exceeded", "commentCount": fragment_omitted})
    if review:
        for states in matches.values():
            for state in states:
                if state["index"] not in seen and state["status"] != "rejected":
                    review._reject(state, "not_exact_comment_token" if lexical_complete else "lexical_boundary_not_proven")
    recorded = len(fragments)
    reviewed = sum("sourceText" in f and "documentationReview" in f for f in fragments)
    blocked = sum(f["sourceDisclosure"]["status"] in {"rejected", "withheld"} for f in fragments)
    coverage = {"scope": "recognized_java_comment_tokens", "detectedFragments": detected,
        "recordedFragments": recorded, "reviewedFragments": reviewed,
        "unreviewedFragments": recorded - reviewed - blocked, "blockedFragments": blocked,
        "omittedFragments": detected - recorded,
        "lexicalComplete": lexical_complete, "inventoryComplete": detected == recorded,
        "sourceCommentDenominator": "recognized_comment_tokens" if lexical_complete else "UNKNOWN",
        "semanticComplete": False, "businessPolicyComplete": False, "runtimeStatus": "not_observed",
        "reasons": sorted({"documentation_claim_not_enforcement", "whole_policy_denominator_unknown"}
            | {item["reason"] for item in omissions}
            | {f["sourceDisclosure"]["reason"] for f in fragments if f["sourceDisclosure"]["status"] != "admitted"})}
    if local_access is not None:
        coverage["localSourceAccess"] = local_access.coverage(path)
        coverage["localCapturedFragments"] = sum("localCapturePermission" in f and "sourceText" in f for f in fragments)
    if review:
        coverage["documentationReview"] = review.coverage(path)
        for fragment in fragments:
            proof = fragment.get("documentationReview")
            if proof:
                for output in reversed(review._outputs.get(proof["requestIndex"], [])):
                    if output["fragment"] is fragment:
                        output["coverage"] = coverage
                        break
    result = {"schemaVersion": 1, "extractorVersion": EXTRACTOR_VERSION,
        "sourceSpan": {"lineStart": 1, "lineEnd": 1 + len(re.findall(r"\r\n|\r|\n", source))},
        "fragments": fragments, "coverage": coverage, "omissions": omissions}
    try:
        binding = {"path": path, "sourceDigest": source_digest, "language": language}
        guard(binding)
        result.update(binding)
    except privacy_guard.PrivacyError:
        # Never return a profile-denied filename just to satisfy a downstream
        # binding check. The integration must reject this missing source bind.
        coverage["reasons"] = sorted(set(coverage["reasons"]) | {"source_metadata_privacy_denied"})
    return result

LOCAL_ACCESS_FORMAT = "companion.local-source-analysis-access.v1"
_LOCAL_KEYS = {"format", "purpose", "permissionId", "sourceFingerprint", "scopeDigest", "selectedScope",
    "privateDestinationId", "profileSha256", "aclSha256", "revocationId", "revoked", "expiresAt", "entries"}
_LOCAL_ENTRY_KEYS = {"path", "sourceSha256", "tokenByteStart", "tokenByteEnd", "tokenSha256"}


class LocalSourceAccess:
    """Explicit local disclosure permission; never independent semantic review.

    The store supplies current scope/profile/ACL/destination bindings. No model
    classification can create a permission and no source is read by this class.
    """
    def __init__(self, receipt, *, source_fingerprint, selected_scope, scope_digest,
                 destination_id, profile, acl_sha256):
        self.receipt = json.loads(_canonical(receipt))
        self.digest = _hash(_canonical(receipt))
        if not isinstance(profile, dict): raise DocumentationReviewError("local_source_access_profile_required")
        self._profile = profile
        self._entries = []; self._seen = set(); self._outputs = 0
        self._validate(source_fingerprint, selected_scope, scope_digest, destination_id, acl_sha256)

    def _validate(self, fingerprint, scope, scope_digest, destination, acl):
        scope = list(scope) if scope else ["."]
        value = self.receipt
        if (not isinstance(value, dict) or set(value) != _LOCAL_KEYS or value["format"] != LOCAL_ACCESS_FORMAT
                or value["purpose"] != "local-source-analysis" or value["revoked"] is not False
                or not isinstance(value["permissionId"], str) or not _REVIEW_ID.fullmatch(value["permissionId"])
                or not isinstance(value["revocationId"], str) or not _REVIEW_ID.fullmatch(value["revocationId"])
                or value["sourceFingerprint"] != fingerprint or value["scopeDigest"] != scope_digest
                or value["selectedScope"] != sorted(scope) or len(set(scope)) != len(scope)
                or any(root != "." and not _path(root) for root in scope)
                or value["privateDestinationId"] != destination
                or value["aclSha256"] != acl or value["profileSha256"] != _hash(_canonical(self._profile))
                or any(not isinstance(value[k], str) or not _HEX.fullmatch(value[k]) for k in
                    ("sourceFingerprint", "scopeDigest", "profileSha256", "aclSha256"))
                or not isinstance(value["entries"], list) or len(value["entries"]) > MAX_ENTRIES
                or len(_canonical(value)) > MAX_MANIFEST_BYTES):
            raise DocumentationReviewError("local_source_access_binding_invalid")
        expiry = value["expiresAt"]
        if expiry is not None:
            try:
                when = datetime.datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if when.tzinfo is None or when <= datetime.datetime.now(datetime.timezone.utc): raise ValueError()
            except (AttributeError, ValueError, TypeError):
                raise DocumentationReviewError("local_source_access_expired") from None
        keys = set(); ranges = {}
        for index, entry in enumerate(value["entries"]):
            if (not isinstance(entry, dict) or set(entry) != _LOCAL_ENTRY_KEYS or not _path(entry.get("path"))
                    or any(not isinstance(entry.get(k), str) or not _HEX.fullmatch(entry[k]) for k in ("sourceSha256", "tokenSha256"))
                    or type(entry.get("tokenByteStart")) is not int or type(entry.get("tokenByteEnd")) is not int
                    or not 0 <= entry["tokenByteStart"] < entry["tokenByteEnd"] <= MAX_SOURCE_BYTES
                    or not any(root == "." or entry["path"] == root or entry["path"].startswith(root + "/") for root in scope)):
                raise DocumentationReviewError("local_source_access_occurrence_invalid")
            key = (entry["path"], entry["tokenByteStart"], entry["tokenByteEnd"])
            if key in keys: raise DocumentationReviewError("local_source_access_occurrence_duplicate")
            keys.add(key)
            for before in ranges.setdefault(entry["path"], []):
                if entry["tokenByteStart"] < before[1] and before[0] < entry["tokenByteEnd"]:
                    raise DocumentationReviewError("local_source_access_occurrence_overlap")
            ranges[entry["path"]].append((entry["tokenByteStart"], entry["tokenByteEnd"]))
            self._entries.append({"index": index, "entry": entry, "status": "not_observed", "reason": "occurrence_not_observed"})
        privacy_guard.ensure_public_safe(value, profile=self._profile)

    def _observe_existing(self, path, digest, byte_start, byte_end, raw, status):
        for state in self._entries:
            entry = state["entry"]
            if entry["path"] == path and entry["tokenByteStart"] == byte_start and entry["tokenByteEnd"] == byte_end:
                good = entry["sourceSha256"] == digest and entry["tokenSha256"] == _hash(raw.encode("utf-8"))
                state.update(status="reviewed_existing" if status == "admitted" and good else "rejected",
                    reason="independent_review_already_supplies_evidence" if status == "admitted" and good else "existing_review_denied_or_digest_mismatch")

    def _admit(self, path, digest, byte_start, byte_end, raw, fragment):
        states = [state for state in self._entries if state["entry"]["path"] == path and
            state["entry"]["tokenByteStart"] == byte_start and state["entry"]["tokenByteEnd"] == byte_end]
        if not states: return None
        state = states[0]; self._seen.add(state["index"])
        if state["entry"]["sourceSha256"] != digest or state["entry"]["tokenSha256"] != _hash(raw.encode("utf-8")):
            state.update(status="rejected", reason="occurrence_digest_mismatch"); return "rejected", state["reason"]
        if byte_end - byte_start > MAX_COMMENT_BYTES or self._outputs >= MAX_ENTRIES:
            state.update(status="rejected", reason="local_capture_budget_exceeded"); return "rejected", state["reason"]
        try:
            _documentation_guard(raw, lambda text: privacy_guard.ensure_public_safe(text, profile=self._profile))
        except (privacy_guard.PrivacyError, DocumentationReviewError):
            state.update(status="rejected", reason="privacy_denied"); return "rejected", state["reason"]
        fragment["sourceText"] = raw
        fragment["localCapturePermission"] = {"format": LOCAL_ACCESS_FORMAT, "receiptSha256": self.digest,
            "permissionId": self.receipt["permissionId"], "sourceFingerprint": self.receipt["sourceFingerprint"],
            "scopeDigest": self.receipt["scopeDigest"], "privateDestinationId": self.receipt["privateDestinationId"],
            "profileSha256": self.receipt["profileSha256"], "aclSha256": self.receipt["aclSha256"],
            "revocationId": self.receipt["revocationId"], "expiresAt": self.receipt["expiresAt"],
            "semanticReview": "UNREVIEWED", "publicDisclosureAuthorized": False,
            "sourceBinding": {"sourceSha256": digest, "tokenByteStart": byte_start, "tokenByteEnd": byte_end,
                "tokenSha256": state["entry"]["tokenSha256"]}}
        fragment["semanticReview"] = "UNREVIEWED"
        state.update(status="captured", reason="explicit_local_source_analysis_permission")
        self._outputs += 1
        return "local_permitted", "explicit_local_source_analysis_permission"

    def binding(self):
        return {"format": LOCAL_ACCESS_FORMAT, "receiptSha256": self.digest,
            **{k: self.receipt[k] for k in ("permissionId", "sourceFingerprint", "scopeDigest", "privateDestinationId",
                "profileSha256", "aclSha256", "revocationId", "expiresAt")},
            "semanticReview": "UNREVIEWED", "publicDisclosureAuthorized": False}

    def coverage(self, path=None):
        selected = [s for s in self._entries if path is None or s["entry"]["path"] == path]
        return {"format": LOCAL_ACCESS_FORMAT, "receiptSha256": self.digest,
            "requestedOccurrences": len(selected), "capturedOccurrences": sum(s["status"] == "captured" for s in selected),
            "deniedOccurrences": sum(s["status"] == "rejected" for s in selected),
            "existingReviewedOccurrences": sum(s["status"] == "reviewed_existing" for s in selected),
            "notObservedOccurrences": sum(s["status"] == "not_observed" for s in selected),
            "independentSemanticReview": "UNREVIEWED", "publicDisclosureAuthorized": False,
            "entries": [{"requestIndex": s["index"], "status": s["status"], "reason": s["reason"]} for s in selected]}


def prepare_local_source_access(receipt, *, source_fingerprint, selected_scope, scope_digest,
                                destination_id, profile, acl_sha256):
    return LocalSourceAccess(receipt, source_fingerprint=source_fingerprint, selected_scope=selected_scope,
        scope_digest=scope_digest, destination_id=destination_id, profile=profile, acl_sha256=acl_sha256)


class RdfDocumentationBindings:
    """Private current-build disclosure witnesses; never a serialized permission.

    Default RDF has no text authority. Only a prepared review/local context may
    bind an exact staged record. Every use rechecks its still-current in-process
    authority and every occurrence, proof, claim and record digest. The store
    separately revalidates current config/profile/ACL before publication.
    """
    MAX_BINDINGS = MAX_ENTRIES * 2
    MAX_BINDING_BYTES = 16 * 1024 * 1024

    def __init__(self, rows, *, review=None, local_access=None):
        if ((review is not None and not isinstance(review, DocumentationReview))
                or (local_access is not None and not isinstance(local_access, LocalSourceAccess))):
            raise DocumentationReviewError("rdf_documentation_authority_invalid")
        self.review, self.local_access = review, local_access
        self._bindings = {}; self._serialized = set(); self._withdrawn = set()
        self._detected = self._denied = self._omitted = 0; self._bytes = 0
        for row in rows:
            if row.get("category") != "source_documentation" or "sourceText" not in row: continue
            self._detected += 1
            binding = self._binding(row)
            if binding is None or row.get("id") in self._bindings:
                self._denied += 1; continue
            size = len(_canonical(binding))
            if len(self._bindings) >= self.MAX_BINDINGS or self._bytes + size > self.MAX_BINDING_BYTES:
                self._omitted += 1; continue
            self._bindings[row["id"]] = binding; self._bytes += size

    @staticmethod
    def claim(row):
        return {key: row[key] for key in ("sourceText", "documentationReview", "localCapturePermission",
            "semanticReview", "instructionAuthority", "evidence") if key in row}

    def _binding(self, row):
        try:
            raw = row.get("sourceText"); bounds = row.get("sourceRange", {})
            if (row.get("category") != "source_documentation" or row.get("extractorVersion") != EXTRACTOR_VERSION
                    or not isinstance(raw, str) or not _path(row.get("path"))
                    or not isinstance(row.get("sourceDigest"), str) or not _HEX.fullmatch(row["sourceDigest"])
                    or row.get("instructionAuthority") != "none" or row.get("businessMeaningVerified") is not False
                    or row.get("runtimeStatus") != "not_observed"
                    or row.get("evidence") != {"kind": "source_documentation", "interpretation": "documentation_claim", "enforcement": "UNKNOWN"}
                    or type(bounds.get("byteStart")) is not int or type(bounds.get("byteEnd")) is not int):
                return None
            encoded = raw.encode("utf-8"); start, end = bounds["byteStart"], bounds["byteEnd"]
            if not 0 <= start < end <= MAX_SOURCE_BYTES or len(encoded) != end - start or len(encoded) > MAX_COMMENT_BYTES:
                return None
            token = _hash(encoded)
            if row.get("commentSha256") != token or row.get("id") != "semantic-documentation:" + _hash(_canonical([row["path"], row["sourceDigest"], start, end, EXTRACTOR_VERSION])):
                return None
            tokens = list(_comments(raw))
            if len(tokens) != 1 or tokens[0] != (row.get("commentKind"), 0, len(raw), None): return None
            entry_binding = {"path": row["path"], "sourceSha256": row["sourceDigest"], "tokenByteStart": start,
                "tokenByteEnd": end, "tokenSha256": token}
            review_proof, local_proof = row.get("documentationReview"), row.get("localCapturePermission")
            proof = kind = None
            if isinstance(review_proof, dict) and local_proof is None and self.review is not None:
                context = self.review; index = review_proof.get("requestIndex")
                if not context.valid or type(index) is not int or not 0 <= index < len(context._entries): return None
                state = context._entries[index]; entry = state["entry"]
                if state["status"] != "admitted" or any(entry.get(key) != value for key, value in entry_binding.items()): return None
                proof = {"format": FORMAT, "purpose": PURPOSE, "manifestSha256": context.manifest_sha256,
                    "sourceFingerprint": context.source_fingerprint, "reviewId": context._review_id, "requestIndex": index,
                    "reasonCode": entry["reasonCode"], "usageContext": entry["usageContext"], "sourceBinding": entry_binding,
                    "identityScope": "source_occurrence", "publicDisclosureAuthorized": False}
                if review_proof != proof or row.get("sourceDisclosure") != {"status": "admitted", "reason": "reviewed_nonsecret_documentation_occurrence"}: return None
                _documentation_guard(raw, context._guard); kind = "independent_documentation_review"
            elif isinstance(local_proof, dict) and review_proof is None and self.local_access is not None:
                context = self.local_access; receipt = context.receipt
                if receipt.get("revoked") is not False or _hash(_canonical(receipt)) != context.digest or _hash(_canonical(context._profile)) != receipt["profileSha256"]: return None
                expiry = receipt["expiresAt"]
                if expiry is not None:
                    when = datetime.datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    if when.tzinfo is None or when <= datetime.datetime.now(datetime.timezone.utc): return None
                states = [state for state in context._entries if state["entry"] == entry_binding]
                if len(states) != 1 or states[0]["status"] != "captured": return None
                proof = {**context.binding(), "sourceBinding": {key: value for key, value in entry_binding.items() if key != "path"}}
                if (local_proof != proof or row.get("semanticReview") != "UNREVIEWED"
                        or row.get("sourceDisclosure") != {"status": "local_permitted", "reason": "explicit_local_source_analysis_permission"}): return None
                _documentation_guard(raw, lambda value: privacy_guard.ensure_public_safe(value, profile=context._profile))
                kind = "explicit_local_source_analysis"
            else: return None
            return {"format": "companion.rdf-documentation-binding.v1", "recordId": row["id"],
                "path": row["path"], "sourceDigest": row["sourceDigest"], "sourceBinding": entry_binding,
                "permissionKind": kind, "proofSha256": _hash(_canonical(proof)),
                "claimSha256": _hash(_canonical(self.claim(row))), "recordSha256": _hash(_canonical(row))}
        except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, privacy_guard.PrivacyError):
            return None

    def allows(self, row):
        identity = row.get("id"); expected = self._bindings.get(identity)
        if expected is not None and self._binding(row) == expected:
            self._serialized.add(identity); return True
        if expected is not None: self._withdrawn.add(identity)
        return False

    def failure_reason(self, row):
        if row.get("id") in self._bindings: return "rdf_documentation_binding_changed"
        if self._omitted and self._binding(row) is not None: return "rdf_documentation_binding_budget"
        return "rdf_documentation_permission_unavailable"

    def coverage(self):
        return {"scope": "staged_text_bearing_source_documentation_records_not_all_comments",
            "detected": self._detected, "authorized": len(self._bindings), "denied": self._denied,
            "omitted": self._omitted, "serialized": len(self._serialized), "withdrawnAfterBinding": len(self._withdrawn),
            "notSerialized": len(set(self._bindings) - self._serialized - self._withdrawn),
            "bindingBytes": self._bytes, "omissionReasons": ["rdf_documentation_binding_budget"] if self._omitted else [],
            "publicDisclosureAuthorized": False, "semanticCompleteness": "UNKNOWN"}


def local_source_occurrences(source, language, path, source_digest):
    """Metadata-only complete comment inventory for an explicit permission issuer.

    This does not grant access, classify harmlessness, return comment text or
    register protected values. The operator must separately authorize the scope.
    """
    if (not isinstance(source, str) or not _path(path) or not isinstance(source_digest, str)
            or not _HEX.fullmatch(source_digest)):
        raise DocumentationReviewError("local_occurrence_source_invalid")
    try:
        encoded = source.encode("utf-8")
    except UnicodeError:
        raise DocumentationReviewError("local_occurrence_source_invalid") from None
    if len(encoded) > MAX_SOURCE_BYTES or _hash(encoded) != source_digest:
        raise DocumentationReviewError("local_occurrence_source_binding_invalid")
    if language != "Java":
        return {"scope": "recognized_java_comment_tokens", "status": "unsupported",
            "reason": "unsupported_documentation_language", "entries": [], "sourceTextIncluded": False,
            "commentDenominator": "UNKNOWN"}
    entries = []; cursor = byte_cursor = 0
    for kind, start, end, reason in _comments(source):
        if kind == "unsupported" or reason:
            raise DocumentationReviewError("local_occurrence_inventory_incomplete")
        byte_start = byte_cursor + len(source[cursor:start].encode("utf-8"))
        token = source[start:end].encode("utf-8"); byte_end = byte_start + len(token)
        entries.append({"path": path, "sourceSha256": source_digest, "tokenByteStart": byte_start,
            "tokenByteEnd": byte_end, "tokenSha256": _hash(token)})
        cursor, byte_cursor = end, byte_end
        if len(entries) > MAX_ENTRIES:
            raise DocumentationReviewError("local_occurrence_inventory_budget_exceeded")
    return {"scope": "recognized_java_comment_tokens", "status": "complete", "entries": entries,
        "detectedComments": len(entries), "commentDenominator": len(entries), "sourceTextIncluded": False}
