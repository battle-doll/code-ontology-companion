"""Source hashing stays bounded independently of inline business payloads."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'))
import business_semantics as sem
import privacy_guard
from test_business_semantics import PINS, Reader


def nested(depth, leaf=1):
    for _ in range(depth):
        leaf = {'child': leaf}
    return leaf


def source(depth):
    return {'id': 'semantic:' + 'a' * 64, 'kind': 'semantic_fragment',
            'name': 'Neutral fragment', 'path': 'neutral.java', 'sourceDigest': '4' * 64,
            'span': {'lineStart': 1, 'lineEnd': 2}, 'payload': nested(depth)}


def standard_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


class SourceAnchorBoundsTests(unittest.TestCase):
    def setUp(self):
        profile = privacy_guard.build_profile([], [], key=b'z' * 32)
        self.profile_patch = patch.object(privacy_guard, 'load_profile', return_value=profile)
        self.profile_patch.start()
        sem.configure(privacy_guard=privacy_guard)

    def tearDown(self):
        self.profile_patch.stop()

    def test_legacy_hash_bytes_and_anchor_closure_stay_identical(self):
        for depth in (0, 1, 15, 31):
            row = source(depth)
            anchor = sem.make_anchor(row, source_pins=PINS)
            self.assertEqual(anchor['recordDigest'], sem.digest(row))
            self.assertEqual(anchor['targetDigest'], standard_digest(row))
            expected = {'recordDigest': standard_digest(row), 'dependencyClosure': None,
                        'sourceEvidence': [], 'sourceAssertionIds': []}
            self.assertEqual(anchor['dependencyClosureDigest'], sem.digest(expected))

    def test_deep_source_is_a_shallow_unreviewed_candidate_only(self):
        for depth in (32, 40, 63, 95, 127):
            row = source(depth)
            with self.subTest(depth=depth):
                with self.assertRaisesRegex(sem.BusinessError, 'json_budget_exceeded'):
                    sem.canonical(row)
                record = sem.candidate_record(row, source_pins=PINS)
                self.assertEqual(record['support'], 'candidate')
                self.assertEqual(record['businessApproval'], 'unreviewed')
                self.assertTrue(all(facet['status'] == 'UNKNOWN' for facet in record['facets'].values()))
                self.assertNotIn('payload', record)
                self.assertNotIn('child', sem.canonical(record).decode())
                anchor = record['sourceAnchors'][0]
                self.assertEqual(anchor['recordDigest'], standard_digest(row))
                self.assertEqual(sem.validate_anchor(anchor, Reader([row]), source_pins=PINS), row)

    def test_pointer_and_dependency_changes_cannot_reuse_old_anchor(self):
        row = source(40)
        row['sourceEvidence'] = [{'id': 'neutral-evidence', 'proof': nested(35)}]
        anchor = sem.make_anchor(row, source_pins=PINS, inline_pointer='/payload')
        self.assertEqual(anchor['targetDigest'], standard_digest(row['payload']))
        for changed in ('payload', 'sourceEvidence', 'sourceDigest', 'span'):
            altered = copy.deepcopy(row)
            if changed == 'payload':
                altered['payload'] = nested(40, 2)
            elif changed == 'sourceEvidence':
                altered['sourceEvidence'][0]['id'] = 'changed-evidence'
            elif changed == 'sourceDigest':
                altered['sourceDigest'] = '5' * 64
            else:
                altered['span']['lineEnd'] = 3
            with self.subTest(changed=changed), self.assertRaises(sem.BusinessError):
                sem.validate_anchor(anchor, Reader([altered]), source_pins=PINS)

    def test_original_denominator_retains_out_of_bound_source(self):
        good, bad = source(40), source(128)
        bad['id'] = 'semantic:' + 'b' * 64
        result = sem.build_candidates(Reader([good, bad]), source_pins=PINS)
        self.assertEqual(result['coverage']['denominator'], 2)
        self.assertEqual(len(result['records']), 1)
        entry = result['coverage']['entries'][0]
        self.assertEqual(entry['inputIndex'], 1)
        self.assertEqual(entry['reason'], 'json_budget_exceeded')
        self.assertEqual(result['coverage']['state'], 'PARTIAL')
        events = list(sem.iter_candidate_events(Reader([good, bad]), source_pins=PINS))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1][2]['sourceRecordId'], bad['id'])
        self.assertEqual(events[1][2]['reason'], 'json_budget_exceeded')

    def test_source_hash_rejects_cycles_nonfinite_and_invalid_types(self):
        cycle = {}
        cycle['child'] = cycle
        for value in (cycle, float('nan'), float('inf'), {1: 'bad-key'}, {'x': object()},
                      {'x': 'a' * 131073}, {'a' * 513: True}, nested(129)):
            with self.subTest(valueType=type(value).__name__), self.assertRaises(sem.BusinessError):
                sem._source_digest(value)

    def test_source_node_and_byte_limits_remain_enforced(self):
        with self.assertRaisesRegex(sem.BusinessError, 'json_budget_exceeded'):
            sem._source_digest([None] * 2000000)
        with self.assertRaisesRegex(sem.BusinessError, 'json_budget_exceeded'):
            sem._source_digest(['a' * 131072] * 256)

    def test_inline_business_json_guard_still_rejects_depth33(self):
        self.assertEqual(sem.digest(nested(32)), standard_digest(nested(32)))
        with self.assertRaisesRegex(sem.BusinessError, 'json_budget_exceeded'):
            sem.canonical(nested(33))
        with self.assertRaisesRegex(sem.BusinessError, 'json_budget_exceeded'):
            sem.loads(json.dumps(nested(33)))

    def test_deep_source_candidate_still_requires_privacy_guard(self):
        row = source(40)
        row['name'] = 'Neutral Private Identity'
        profile = privacy_guard.build_profile([row['name']], [], key=b'x' * 32)
        with patch.object(privacy_guard, 'load_profile', return_value=profile):
            with self.assertRaises(privacy_guard.PrivacyError):
                sem.candidate_record(row, source_pins=PINS)
            with self.assertRaises(privacy_guard.PrivacyError):
                list(sem.iter_candidate_events(Reader([row]), source_pins=PINS))


if __name__ == '__main__':
    unittest.main()
