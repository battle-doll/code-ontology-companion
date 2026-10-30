"""Contract projection, parent conditions and clock boundaries on neutral data."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_business_explicit_contracts as cases


class ContractBoundaryTests(unittest.TestCase):
    setUp = cases.ExplicitContractTests.setUp
    tearDown = cases.ExplicitContractTests.tearDown
    validated = cases.ExplicitContractTests.validated
    decide = cases.ExplicitContractTests.decide

    def test_mapping_evidence_projection_recurses_without_mutating_canonical_record(self):
        cases.query._semantics = cases.sem
        cases.query._guard = cases.privacy_guard
        leaf = next(row for row in self.validated()['records'] if row['id'] == cases.identity('leaf1'))
        mapping = copy.deepcopy(leaf['facets']['inputs']['value'])
        for wrapped in (mapping, {'type': 'sequence', 'items': [mapping]},
                        {'type': 'sequence', 'items': [{'type': 'sequence', 'items': [mapping]}]}):
            record = copy.deepcopy(leaf)
            record['facets']['inputs']['value'] = wrapped
            before = cases.sem.canonical(record)
            restricted = cases.query.project_record(record, evidence=False)
            complete = cases.query.project_record(record, evidence=True)
            self.assertEqual(complete['facets']['inputs']['value'], wrapped)
            for key in ('sourceRuleDigest', 'numericContextDigest', 'sourcePins'):
                self.assertNotIn(key, json.dumps(restricted))
            self.assertEqual(cases.sem.canonical(record), before)
            self.assertTrue(restricted['evidenceDetailsWithheld'])

    def test_unknown_parent_eligibility_cannot_delegate_to_valid_children(self):
        for mode in ('absent', 'unknown', 'declared_true', 'declared_false'):
            result = self.validated()
            top = next(row for row in result['records'] if row['id'] == cases.identity('composition'))
            if mode == 'absent': top['facets'].pop('eligibility')
            elif mode == 'unknown': top['facets']['eligibility'] = {'status': 'UNKNOWN'}
            else: top['facets']['eligibility'] = cases.declared({'type': 'boolean', 'value': mode == 'declared_true'})
            with self.subTest(mode=mode):
                direct = self.decide(result, context=self.cases[0])
                finite = self.decide(result, cases=self.cases)
                self.assertEqual(direct['status'], 'UNKNOWN')
                self.assertEqual(direct['reason'], 'eligibility_contract_unsupported_or_missing')
                self.assertIsNone(direct['value'])
                self.assertEqual(finite['evaluatedContextNumerator'], 0)
                self.assertIsNone(finite['finiteBest'])
        positive = self.decide(context=self.cases[0])
        self.assertEqual(positive['status'], 'evaluated')

    def test_aware_business_clock_never_guesses_source_date_validity(self):
        cases.query._semantics = cases.sem
        aware = '2026-01-01T12:00:00+09:00'
        self.assertEqual(cases.query._source_date_context({'validity': {}}, aware), (None, None))
        bounded = {'validity': {'from': '2026-01-01', 'to': '2026-01-02'}}
        self.assertEqual(cases.query._source_date_context(bounded, aware),
            (None, 'source_date_validity_clock_mapping_unsupported'))
        self.assertEqual(cases.query._source_date_context(bounded, '2026-01-01'), ('2026-01-01', None))
        for value in ('2026-01-01T12:00:00', '2026-02-30T12:00:00Z', True):
            self.assertEqual(cases.query._source_date_context({}, value)[1], 'explicit_aware_time_required')


class ContractStdioBoundaryTests(unittest.TestCase):
    setUp = cases.ExplicitConsumerIntegrationTests.setUp

    def test_source_deleted_policy_only_aware_contract_keeps_answers_and_hides_proofs(self):
        import companion
        import pipeline_acl as acl
        instant = '2026-01-01T12:00:00Z'
        leaf = self.review_manifest['concepts'][-1]
        leaf['facets']['effective_interval'] = cases.declared(dict(type='time_interval',
            start='2026-01-01T00:00:00Z', end='2026-01-02T00:00:00Z', timezone='UTC', clock='business', bounds='left_closed'))
        leaf['facets']['clock_timezone'] = cases.declared(dict(type='clock_basis', clock='business', timezone='UTC'))
        for value in leaf['facets']['missing_context']['value']['contexts']:
            value['asOf'] = instant
        self.meta = self.store.review(self.workspace, self.sid, self.meta['businessSnapshotId'], self.meta['businessDigest'], self.review_manifest)
        shutil.rmtree(self.root / 'source-offline')
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps(companion.privacy_guard.load_profile()))
        profile.chmod(0o600)
        acl.update_access(self.workspace, 'reader', ['read_policy'], [self.sid])
        common = dict(rule_id=cases.identity('mapped'), policy_view='approved_business')
        inputs = [
            ('ontology_pipeline_search', self.args(kind='business_policy')),
            ('query_policy_rules', self.args(**common)),
            ('explain_policy_result', self.args(**common, as_of=instant,
                context={**self.cases[1], '$clock': 'business', '$timezone': 'UTC'})),
            ('compare_policy_cases', self.args(**common, as_of=instant, cases=self.cases, objective='maximize_value')),
        ]
        wire = ''.join(json.dumps(dict(jsonrpc='2.0', id=index, method='tools/call',
            params=dict(name=name, arguments=arguments))) + '\n' for index, (name, arguments) in enumerate(inputs, 1))
        env = {**os.environ, acl.PRINCIPAL_ENV: 'reader', companion.privacy_guard.PROFILE_ENV: str(profile), 'PYTHONDONTWRITEBYTECODE': '1'}
        process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'mcp/server.py')],
            input=wire, text=True, capture_output=True, timeout=30, env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        replies = [json.loads(line)['result'] for line in process.stdout.splitlines()]
        self.assertEqual(len(replies), 4)
        for reply in replies:
            self.assertFalse(reply.get('isError'), reply)
            data = reply['structuredContent']['data']
            self.assertTrue(data['evidenceDetailsWithheld'])
            for key in ('sourceRuleDigest', 'numericContextDigest', 'sourceSha256', 'sourceText'):
                self.assertNotIn(key, json.dumps(data))
        direct = replies[2]['structuredContent']['data']['businessDecision']
        self.assertEqual(direct['status'], 'evaluated', direct)
        self.assertEqual(direct['temporalDecision']['asOf'], instant)
        finite = replies[3]['structuredContent']['data']['businessDecision']
        self.assertEqual(finite['status'], 'finite_set_evaluated', finite)
        self.assertEqual(finite['finiteBest']['contextIds'], ['case1'])
        self.assertFalse(finite['finiteBest']['globalMaximum'])


if __name__ == '__main__':
    unittest.main()
