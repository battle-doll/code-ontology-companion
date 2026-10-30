"""Neutral, opt-in v2 text registration; no real profile or source discovery."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import html
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/manage-code-ontology/scripts'))
import privacy_guard as guard
from windows_fixture import protect_private_path

MARKER = 'Neutral-protected:phrase Z8!'
JSON_ESCAPE_VALUES = ['Neutral escape ' + str(index) + ':left' + character + 'right'
                      for index, character in enumerate(('\n', '\t', '\r', '\b', '\f', '"', '\\', '/'))]


class RegisteredValuePrivacyTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {guard.PROFILE_ENV: ''})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.profile = guard.build_profile([], [], key=b'v' * 32, values=[MARKER])

    def rejected(self, value, category='denied_value', profile=None):
        with self.assertRaises(guard.PrivacyError) as caught:
            guard.ensure_public_safe(value, profile=self.profile if profile is None else profile)
        self.assertEqual(caught.exception.category, category)
        self.assertNotIn(MARKER, str(caught.exception))

    def test_v1_fixed_key_bytes_and_legacy_rows_are_unchanged(self):
        profile = guard.build_profile(['Neutral Person', '중립 인물'], ['neutral@fixture.test'], key=b'v' * 32)
        self.assertEqual(hashlib.sha256(json.dumps(profile, ensure_ascii=False).encode()).hexdigest(),
                         '953b0233a00a4cd4c87fc749adbf1048725e17f908f3a7f92228d4519b1cae1c')
        self.assertEqual(profile['schemaVersion'], 1)
        self.assertNotIn('denyValues', profile)
        for row in profile['denyNames']:
            row.pop('prefixDigest')
        self.rejected('NeutralPerson', 'denied_identity', profile)
        # Legacy scalar handling and optional empty profiles remain unchanged.
        guard.ensure_public_safe([True, 42, float('nan'), None], profile=profile)
        guard.ensure_public_safe(MARKER, profile=guard.build_profile([], [], key=b'v' * 32))

    def test_v2_is_optional_hashed_text_and_domain_separated(self):
        text = json.dumps(self.profile)
        self.assertNotIn(MARKER, text)
        self.assertEqual(self.profile['schemaVersion'], 2)
        row = self.profile['denyValues'][0]
        self.assertEqual(set(row), {'chars', 'digest', 'prefixDigest'})
        key = b'v' * 32
        self.assertNotEqual(row['digest'], guard._identity_digest(key, 'name', guard._value(MARKER)))
        self.assertNotEqual(row['prefixDigest'], guard._identity_digest(key, 'initial', 'n'))
        guard.ensure_public_safe('ordinary approved business text', profile=self.profile, require_profile=True)
        with self.assertRaises(guard.PrivacyError):
            guard.ensure_public_safe('', profile=guard.build_profile([], [], values=[]), require_profile=True)

    def test_normalization_encoding_keys_nested_alias_and_basis(self):
        variants = [MARKER, MARKER.upper(), quote(MARKER, safe=''), MARKER.replace(':', '&#58;'),
                    MARKER.replace(':', r'\u003a'), MARKER[:4] + '\u200b' + MARKER[4:],
                    ''.join(chr(ord(c) + 0xFEE0) if 33 <= ord(c) <= 126 else c for c in MARKER),
                    'prefix ' + MARKER + ' suffix']
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                for payload in ({value: 'safe'}, {'aliases': [{'basis': value}]}, {'nested': [({'value': value},)]}, value.encode()):
                    self.rejected(payload)
        # Punctuation/whitespace remain meaningful; no arbitrary transform claim.
        for value in (MARKER.replace(':', '-'), MARKER.replace(' ', ''), 'Unregistered source text'):
            guard.ensure_public_safe(value, profile=self.profile)
        encoded = MARKER
        for _ in range(5):
            encoded = quote(encoded, safe='')
        self.rejected(encoded, 'encoding_depth')

    def test_scalar_json_and_html_forms_are_checked(self):
        for index, (registered, scalar) in enumerate([('47019', 47019), ('-13.25', -13.25),
                                                   ('true', True), ('false', False), ('null', None), ('none', None)]):
            with self.subTest(index=index):
                profile = guard.build_profile([], [], values=[registered])
                self.rejected({'value': scalar}, profile=profile)
                for rendered in (json.dumps(scalar), html.escape(str(scalar))):
                    if guard._value(registered) in guard._value(rendered):
                        self.rejected(rendered, profile=profile)
        for scalar in (float('nan'), float('inf'), -float('inf')):
            self.rejected(scalar, 'unsupported_payload')

    def test_every_json_short_escape_and_supported_wrapper_is_denied(self):
        for index, value in enumerate(JSON_ESCAPE_VALUES):
            profile = guard.build_profile([], [], key=b's' * 32, values=[value])
            encoded = json.dumps(value)
            unicode_text = ''.join('\\u%04x' % ord(character) for character in value)
            shapes = [value, encoded, html.escape(encoded), encoded.encode('utf-8'), quote(encoded),
                      json.dumps(encoded), json.dumps(json.dumps(encoded)),
                      encoded.replace('/', r'\/'), unicode_text, quote(html.escape(encoded)),
                      json.dumps(quote(value)), json.dumps(html.escape(value))]
            for shape_index, shape in enumerate(shapes):
                with self.subTest(escape=index, shape=shape_index):
                    self.rejected(shape, profile=profile)
            # Ordinary punctuation-distinct and unclassified text stays usable.
            guard.ensure_public_safe(json.dumps(value.replace(value[len('Neutral escape ' + str(index) + ':left')], '~', 1)),
                                     profile=profile)
            guard.ensure_public_safe({'approved': 'Ordinary unrelated business wording'}, profile=profile)

    def test_json_backslash_parity_and_single_pass_do_not_recurse(self):
        self.assertEqual(guard._decode_value_once(r'\u005cn'), r'\n')
        self.assertEqual(guard._decode_value_once(r'\\n'), r'\n')
        self.assertEqual(guard._decode_value_once(r'\n'), '\n')
        for count in range(1, 7):
            value = 'Neutral parity ' + '\\' * count + 'n" tail'
            encoded = json.dumps(value)
            self.assertEqual(guard._decode_value_once(encoded), '"' + value + '"')
            profile = guard.build_profile([], [], values=[value])
            self.rejected(encoded, profile=profile)
        raw = JSON_ESCAPE_VALUES[0]
        profile = guard.build_profile([], [], values=[raw])
        encoded = raw
        for _ in range(guard.MAX_VALUE_DECODE_ROUNDS): encoded = json.dumps(encoded)
        self.rejected(encoded, profile=profile)
        self.rejected(json.dumps(encoded), 'encoding_depth', profile=profile)
        with mock.patch.object(guard, 'MAX_VALUE_SCAN_TOTAL_CHARS', len(json.dumps(raw))):
            self.rejected(json.dumps(raw), 'value_scan_budget', profile=profile)
        with mock.patch.object(guard, 'MAX_VALUE_SCAN_CANDIDATES', 1):
            self.rejected(json.dumps(raw), 'value_scan_budget', profile=profile)

    def test_explicit_four_round_v2_contract_preserves_v1_three_round_limit(self):
        self.assertEqual(guard.MAX_DECODE_ROUNDS, 3)
        self.assertEqual(guard.MAX_VALUE_DECODE_ROUNDS, 4)
        value = JSON_ESCAPE_VALUES[6]
        encoded = value
        for _ in range(3): encoded = json.dumps(encoded)
        # Preserve the former three-round failure as evidence of why v2 alone
        # needed a versioned limit revision for the real RDF transport shape.
        with mock.patch.object(guard, 'MAX_VALUE_DECODE_ROUNDS', 3):
            self.rejected(encoded, 'encoding_depth')
        guard.ensure_public_safe(encoded, profile=self.profile)
        self.rejected(encoded, profile=guard.build_profile([], [], values=[value]))
        legacy = guard.build_profile([], [], key=b'l' * 32)
        text = 'ordinary:typed-text'
        for _ in range(3): text = quote(text, safe='')
        guard.ensure_public_safe(text, profile=legacy)
        self.rejected(quote(text, safe=''), 'encoding_depth', profile=legacy)

    def test_unicode_pair_and_malformed_escape_scope_is_explicit(self):
        value = 'Neutral supplementary \U0001f512 value'
        profile = guard.build_profile([], [], values=[value])
        self.rejected(json.dumps(value, ensure_ascii=True), profile=profile)
        self.rejected(value.replace('\U0001f512', r'\U0001f512'), profile=profile)
        for index, value in enumerate((r'\ud800', r'\udc00', r'\ud800\u0041', r'\udfff\ud800', r'\U00110000')):
            with self.subTest(index=index): self.rejected(value, 'unsupported_payload')
        for value in (r'ordinary\q', r'ordinary\u12', r'ordinary\u00ZZ', 'ordinary\\',
                      r'C:\Projects\ordinary', r'C:\temp\logs', r'\\server\share\folder',
                      r'pattern \d+\w+', r'{unfinished "ordinary\q', '[not-json]'):
            guard.ensure_public_safe(value, profile=self.profile, allow_local_paths=True)
        for value in (r'ordinary\q', r'ordinary\u12', r'ordinary\u00ZZ', 'ordinary\\'):
            self.assertEqual(guard._decode_value_once(value), value)
        # No-value profiles still select the untouched legacy decoder.
        legacy = guard.build_profile([], [], key=b'l' * 32)
        guard.ensure_public_safe(r'\ud800', profile=legacy)
        guard.ensure_public_safe(r'\ud800', profile=guard.build_profile([], [], values=[]))

    def test_all_v2_profile_material_and_safe_errors_are_denied(self):
        profile = guard.build_profile(['Neutral Person'], ['neutral@fixture.test'], values=[MARKER])
        material = [profile['key']]
        material += [row[field] for name in ('denyNames', 'denyEmails', 'denyValues')
                     for row in profile[name] for field in ('digest', 'prefixDigest') if field in row]
        for index, item in enumerate(material):
            for variant in (item, item.upper(), quote(item, safe=''), item[:4] + '\u200b' + item[4:]):
                with self.subTest(index=index):
                    self.rejected({'hidden': variant}, 'private_profile_material', profile)
        self.rejected(profile, 'private_profile_material', profile)
        with mock.patch.object(guard, 'load_profile', return_value=self.profile):
            message = guard.safe_error_message(ValueError(MARKER))
        self.assertNotIn(MARKER, message)
        self.assertEqual(message, 'The local ontology request was rejected by the privacy guard.')

    def test_strict_schema_text_input_and_profile_size(self):
        for values in (MARKER, b'value', {'value': MARKER}, [1], [True], [None], [''], ['   '],
                       ['x' * (guard.MAX_VALUE_CHARS + 1)], ['x' * (guard.MAX_VALUE_INPUT_CHARS + 1)],
                       ['x'] * (guard.MAX_VALUES + 1), ['\ud800']):
            with self.assertRaises(guard.PrivacyError):
                guard.build_profile([], [], values=values)
        mutations = [lambda p: p.update(schemaVersion=True), lambda p: p.update(schemaVersion=3),
                     lambda p: p.update(untrusted='allow'), lambda p: p['denyValues'][0].update(chars=True),
                     lambda p: p['denyValues'][0].pop('prefixDigest'),
                     lambda p: p['denyValues'][0].update(digest='x' * 64),
                     lambda p: p['denyValues'][0].update(plaintext=MARKER)]
        for mutate in mutations:
            profile = copy.deepcopy(self.profile); mutate(profile)
            self.rejected('safe', 'profile_schema', profile)
        names = ['Neutral Person ' + str(i) for i in range(256)]
        emails = ['neutral' + str(i) + '@fixture.test' for i in range(256)]
        with self.assertRaises(guard.PrivacyError) as caught:
            guard.build_profile(names, emails, values=['registered-' + str(i) for i in range(128)])
        self.assertEqual(caught.exception.category, 'profile_size')

    def test_profile_file_is_reread_and_invalid_changes_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / 'neutral-profile.json'
            def write(profile):
                path.write_text(json.dumps(profile)); protect_private_path(path)
            with mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(path)}):
                write(guard.build_profile([], [], values=['other-neutral-value']))
                guard.ensure_public_safe(MARKER)
                write(self.profile)
                with self.assertRaises(guard.PrivacyError): guard.ensure_public_safe(MARKER)
                write({**self.profile, 'untrusted': True})
                with self.assertRaises(guard.PrivacyError): guard.ensure_public_safe('safe')
                self.assertEqual(path.read_text(), json.dumps({**self.profile, 'untrusted': True}))

    def test_independent_budgets_and_v1_exemption(self):
        for constant, maximum, payload in [('MAX_VALUE_SCAN_CHARS', 8, 'z' * 9),
                                           ('MAX_VALUE_SCAN_CHARS', 8, '\ufb03' * 3),
                                           ('MAX_VALUE_SCAN_TOTAL_CHARS', 9, ['zzzzz', 'zzzzz']),
                                           ('MAX_VALUE_SCAN_NODES', 4, ['z'] * 4),
                                           ('MAX_VALUE_SCAN_DEPTH', 2, [[['z']]]),
                                           ('MAX_VALUE_SCAN_CANDIDATES', 4, 'n' * 100)]:
            with self.subTest(constant=constant), mock.patch.object(guard, constant, maximum):
                self.rejected(payload, 'value_scan_budget')
                guard.ensure_public_safe(payload, profile=guard.build_profile([], [], key=b'w' * 32))
        with mock.patch.object(guard, 'MAX_VALUE_SCAN_TOTAL_CHARS', 12):
            self.rejected('zz&#122;zz', 'value_scan_budget')
        cyclic = []; cyclic.append(cyclic)
        self.rejected(cyclic, 'unsupported_payload')
        self.rejected('\ud800', 'unsupported_payload')

    def test_actual_32_mib_html_page_boundary_and_large_record(self):
        # Existing HTML writers allow 32 MiB per page. ASCII makes bytes and
        # characters equal here; Unicode expansion is tested separately above.
        prefix, suffix = '<!doctype html><html><body>', '</body></html>'
        fragment = '<section><h2>Approved rule</h2><p>Ordinary business statement</p><code>value=47019</code></section>'
        size = 32 * 1024 * 1024 - len(prefix) - len(suffix)
        page = prefix + (fragment * (size // len(fragment))) + 'z' * (size % len(fragment)) + suffix
        self.assertEqual(len(page.encode('utf-8')), 32 * 1024 * 1024)
        guard.ensure_public_safe(page, profile=self.profile)
        self.rejected(page + 'z', 'value_scan_budget')
        guard.ensure_public_safe({'text': 'z' * (512 * 1024 - 100)}, profile=self.profile)

    def test_values_only_profile_cannot_relax_release_identity_gates(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import build_release
        import build_skills_only_release
        import check_publication_privacy as preflight
        for module in (build_release, build_skills_only_release):
            with mock.patch.object(sys, 'argv', ['builder', '--public']), \
                    mock.patch('validate_public_privacy.load_profile', return_value=self.profile), \
                    mock.patch.object(module, '_run_source_validator') as validate, \
                    mock.patch.object(module, 'build_archive') as build, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 1)
                validate.assert_not_called(); build.assert_not_called()
        with mock.patch.object(preflight, 'load_profile', return_value=self.profile), \
                mock.patch.object(preflight.GitHubReader, 'get') as get:
            receipt = preflight.check(ROOT)
        get.assert_not_called()
        self.assertIn('required-private-profile-unavailable', {item['rule'] for item in receipt['findings']})

    def test_initial_digest_memo_is_call_local_domain_separated_and_bounded(self):
        profile = guard.build_profile(['Zqxv Private Individual'], [], key=b'p' * 32)
        payload = ['ordinary routine'] * 100
        with mock.patch.object(guard, '_identity_digest', wraps=guard._identity_digest) as calls:
            guard.ensure_public_safe(payload, profile=profile)
            first = calls.call_count
            guard.ensure_public_safe(payload, profile=profile)
            self.assertEqual(calls.call_count, first * 2)
        self.assertEqual(first, len(set(guard._name(payload[0]))))
        second = guard.build_profile(['Zqxv Private Individual'], [], key=b'q' * 32)
        self.rejected('Zqxv Private Individual', 'denied_identity', second)
        both = guard.build_profile(['Zqxv Private Individual'], [], values=[MARKER])
        with mock.patch.object(guard, '_identity_digest', wraps=guard._identity_digest) as calls:
            guard.ensure_public_safe(payload, profile=both)
        domains = {call.args[1] for call in calls.call_args_list}
        self.assertIn('initial', domains); self.assertIn('value-initial-v2', domains)
        # Cache exhaustion performs the original calculation; it never skips.
        with mock.patch.object(guard, 'MAX_INITIAL_DIGEST_CACHE', 1), \
                mock.patch.object(guard, '_identity_digest', wraps=guard._identity_digest) as calls:
            guard.ensure_public_safe(['abcdef', 'abcdef'], profile=profile)
            self.assertEqual(calls.call_count, 11)
        with mock.patch.object(guard, 'MAX_INITIAL_DIGEST_CACHE', 0):
            self.rejected(MARKER)
        # V2 resource charging is unchanged even when all initials are cached.
        with mock.patch.object(guard, 'MAX_VALUE_SCAN_CANDIDATES', 4):
            self.rejected(['z'] * 5, 'value_scan_budget')

    def test_memoized_and_uncached_v1_results_and_categories_match(self):
        profile = guard.build_profile(['Neutral Person'], ['neutral@fixture.test'], key=b'd' * 32)
        legacy = copy.deepcopy(profile)
        for row in legacy['denyNames']: row.pop('prefixDigest')
        payloads = ['ordinary routine', ['safe', {'kind': 'routine'}], 'NEUTRAL_PERSON',
                    quote('Neutral Person'), r'Neutral\u0020Person', 'neutral@fixture.test',
                    'unknown@fixture.invalid', '/home/example/path', 'sk-proj-' + 'x' * 40,
                    profile['key'], profile['denyNames'][0]['prefixDigest'], [1, True, None]]
        def outcome(value, selected):
            try:
                guard.ensure_public_safe(value, profile=selected)
                return 'allowed'
            except guard.PrivacyError as exc:
                return exc.category, str(exc)
        for index, payload in enumerate(payloads):
            for selected in (profile, legacy):
                with self.subTest(index=index):
                    cached = outcome(payload, selected)
                    with mock.patch.object(guard, 'MAX_INITIAL_DIGEST_CACHE', 0):
                        self.assertEqual(cached, outcome(payload, selected))


class RegisteredValueBusinessBoundaryTests(unittest.TestCase):
    def setUp(self):
        import test_business_query as fixture_module
        self.fixture = fixture_module.BusinessQueryTests('test_status_discovery_and_page_pins_without_source')
        self.fixture.setUp()
        self.guard = fixture_module.companion.privacy_guard
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.profile.stop()
        self.profile_path = self.fixture.root / 'neutral-profile.json'
        self.write_profile([MARKER])
        environment = mock.patch.dict(os.environ, {guard.PROFILE_ENV: str(self.profile_path)})
        environment.start(); self.addCleanup(environment.stop)

    def write_profile(self, values):
        self.profile = guard.build_profile(['Neutral Private Reviewer'], ['neutral-reviewer@fixture.test'],
                                           key=b'j' * 32, values=values)
        self.profile_path.write_text(json.dumps(self.profile)); protect_private_path(self.profile_path)

    def manifest(self, value='Ordinary approved statement'):
        f = self.fixture
        with f.store.open_reader(f.workspace, f.sid, f.meta['businessSnapshotId'], f.meta['businessDigest']) as reader:
            row = next(reader.iter_records(kind='business_policy'))
        return {'schemaVersion': 1, 'sourcePins': {k: f.meta[k] for k in ('sourceSnapshotId', 'sourceManifestSha256', 'sourceFingerprint', 'analysisSpecId')},
                'concepts': [{'namespace': 'neutral-review', 'domain': 'catalog', 'kind': 'business_policy',
                              'conceptKey': 'neutral-description', 'label': 'Neutral description', 'sourceAnchors': row['sourceAnchors'],
                              'facets': {'outcome': {'status': 'DECLARED', 'value': {'type': 'text', 'value': value},
                                                     'basis': 'Manager supplied business statement'}}}]}

    def review(self, manifest):
        f = self.fixture
        return f.store.review(f.workspace, f.sid, f.meta['businessSnapshotId'], f.meta['businessDigest'], manifest)

    def test_trusted_review_deny_preserves_pointer_for_values_basis_alias_and_nested(self):
        f = self.fixture
        pointer = (f.workspace / 'business-state.json').read_bytes()
        changes = [lambda c: c['facets']['outcome']['value'].update(value=MARKER),
                   lambda c: c['facets']['outcome'].update(basis=MARKER),
                   lambda c: c['facets']['outcome'].update(value={'type': 'sequence', 'items': [{'type': 'text', 'value': MARKER}]}),
                   lambda c: c.update(aliases=[{'target': 'business:' + '0' * 64, 'relation': 'alias', 'basis': MARKER}]),
                   lambda c: c.update(untrusted={'privacyOverride': True, 'nested': [MARKER]})]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                manifest = self.manifest(); change(manifest['concepts'][0])
                with self.assertRaises(self.guard.PrivacyError) as caught: self.review(manifest)
                self.assertEqual(caught.exception.category, 'denied_value')
                self.assertEqual((f.workspace / 'business-state.json').read_bytes(), pointer)

    def test_json_escape_review_ingress_denies_all_eight_controls_and_preserves_pointer(self):
        f = self.fixture
        self.write_profile(JSON_ESCAPE_VALUES)
        pointer = (f.workspace / 'business-state.json').read_bytes()
        for index, value in enumerate(JSON_ESCAPE_VALUES):
            encoded = json.dumps(value)
            changes = [lambda c: c['facets']['outcome']['value'].update(value=encoded),
                       lambda c: c['facets']['outcome'].update(basis=encoded),
                       lambda c: c['facets']['outcome'].update(value={'type': 'sequence', 'items': [{'type': 'text', 'value': encoded}]}),
                       lambda c: c.update(aliases=[{'target': 'business:' + '0' * 64, 'relation': 'alias', 'basis': encoded}]),
                       lambda c: c.update(untrusted={encoded: 'ordinary'})]
            for channel, change in enumerate(changes):
                with self.subTest(escape=index, channel=channel):
                    manifest = self.manifest(); change(manifest['concepts'][0])
                    with self.assertRaises(self.guard.PrivacyError) as caught: self.review(manifest)
                    self.assertEqual(caught.exception.category, 'denied_value')
                    self.assertEqual((f.workspace / 'business-state.json').read_bytes(), pointer)

    def test_json_escape_old_snapshot_actual_source_offline_mcp_and_exports_are_revoked(self):
        import companion
        import pipeline_acl as acl
        import pipeline_export
        import pipeline_html
        f = self.fixture
        self.assertFalse(f.repo.exists())
        self.write_profile(['Other neutral protected text'])
        manifest = self.manifest()
        template = manifest['concepts'][0]
        manifest['concepts'] = []
        for index, value in enumerate(JSON_ESCAPE_VALUES):
            concept = copy.deepcopy(template)
            concept.update(conceptKey='escaped-' + str(index), label='Escape statement ' + str(index))
            concept['facets']['outcome']['value']['value'] = json.dumps(value)
            manifest['concepts'].append(concept)
        f.meta = self.review(manifest)
        self.assertEqual(f.meta['coverage']['reviewAccepted'], 8)
        pointer = (f.workspace / 'business-state.json').read_bytes()
        acl.update_access(f.workspace, 'reader', ['read_policy'], [f.sid])

        def wire(index):
            request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'ontology_pipeline_search',
                'arguments': f.args(kind='business_policy', term='Escape statement ' + str(index))}}
            env = {**os.environ, acl.PRINCIPAL_ENV: 'reader', guard.PROFILE_ENV: str(self.profile_path)}
            result = subprocess.run([sys.executable, str(ROOT / 'mcp/server.py')], input=json.dumps(request) + '\n',
                                    text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 0); self.assertEqual(result.stderr, '')
            return json.loads(result.stdout)['result']

        for index, value in enumerate(JSON_ESCAPE_VALUES):
            reply = wire(index)
            self.assertFalse(reply.get('isError'))
            data = reply['structuredContent']['data']
            self.assertTrue(data['evidenceDetailsWithheld'])
            self.assertEqual(len(data['records']), 1)
            transported = data['records'][0]['facets']['outcome']['value']['value']
            self.assertTrue(json.loads(transported) == value)
        for name, operation in [('escape-before-html', pipeline_html.render_pipeline),
                                ('escape-before-bundle', pipeline_export.export_bundle)]:
            operation(f.workspace, f.sid, f.root / name)
            self.assertTrue((f.root / name).is_dir())
            self.assertEqual((f.workspace / 'business-state.json').read_bytes(), pointer)
        self.write_profile(JSON_ESCAPE_VALUES)
        for index in range(8):
            reply = wire(index)
            self.assertTrue(reply.get('isError'))
            guard.ensure_public_safe(reply, profile=self.profile)
        with self.assertRaises(self.guard.PrivacyError) as caught:
            with f.store.open_reader(f.workspace, f.sid, f.meta['businessSnapshotId'], f.meta['businessDigest']) as reader:
                list(reader.iter_records())
        self.assertEqual(caught.exception.category, 'denied_value')
        for name, operation in [('escape-blocked-html', pipeline_html.render_pipeline),
                                ('escape-blocked-bundle', pipeline_export.export_bundle)]:
            with self.assertRaises((ValueError, companion.CompanionError)):
                operation(f.workspace, f.sid, f.root / name)
            self.assertFalse((f.root / name).exists())
        self.assertEqual((f.workspace / 'business-state.json').read_bytes(), pointer)

    def test_four_round_original_transport_retains_all_eight_values_then_profile_blocks(self):
        import companion
        import pipeline_export
        import pipeline_html
        f = self.fixture
        values = JSON_ESCAPE_VALUES
        self.write_profile(['Other neutral protected text'])
        manifest = self.manifest(); template = manifest['concepts'][0]; manifest['concepts'] = []
        for index, value in enumerate(values):
            concept = copy.deepcopy(template)
            concept.update(conceptKey='transport-' + str(index), label='Transport statement ' + str(index))
            concept['facets']['outcome']['value']['value'] = json.dumps(value)
            manifest['concepts'].append(concept)
        f.meta = self.review(manifest)
        self.assertEqual(f.meta['coverage']['reviewAccepted'], 8)
        pointer = (f.workspace / 'business-state.json').read_bytes()
        for name, operation in [('transport-before-html', pipeline_html.render_pipeline),
                                ('transport-before-bundle', pipeline_export.export_bundle)]:
            operation(f.workspace, f.sid, f.root / name)
            self.assertTrue((f.root / name).is_dir())
            retained = [json.loads(path.read_text()) for path in (f.root / name / 'business' / 'records').glob('*.json')]
            selected = {row['conceptKey']: row for row in retained if row['namespace'] == 'neutral-review'}
            self.assertEqual(len(selected), 8)
            for index, value in enumerate(values):
                transported = selected['transport-' + str(index)]['facets']['outcome']['value']['value']
                self.assertTrue(json.loads(transported) == value)
        self.write_profile(values)
        for name, operation in [('transport-blocked-html', pipeline_html.render_pipeline),
                                ('transport-blocked-bundle', pipeline_export.export_bundle)]:
            with self.assertRaises((ValueError, companion.CompanionError)):
                operation(f.workspace, f.sid, f.root / name)
            self.assertFalse((f.root / name).exists())
        self.assertEqual((f.workspace / 'business-state.json').read_bytes(), pointer)

    def test_actual_source_offline_mcp_and_current_profile_export_revocation(self):
        import pipeline_acl as acl
        import pipeline_export
        import pipeline_html
        import companion
        f = self.fixture
        self.assertFalse(f.repo.exists())
        self.write_profile(['Other neutral protected text'])
        f.meta = self.review(self.manifest(MARKER))
        self.assertEqual(f.meta['coverage']['reviewAccepted'], 1)
        pointer = (f.workspace / 'business-state.json').read_bytes()
        acl.update_access(f.workspace, 'reader', ['read_policy'], [f.sid])
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'ontology_pipeline_search', 'arguments': f.args(kind='business_policy')}}
        def wire():
            env = {**os.environ, acl.PRINCIPAL_ENV: 'reader', guard.PROFILE_ENV: str(self.profile_path)}
            result = subprocess.run([sys.executable, str(ROOT / 'mcp/server.py')], input=json.dumps(request) + '\n',
                                    text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, '')
            return json.loads(result.stdout)['result'], result.stdout
        before, raw = wire()
        self.assertFalse(before.get('isError'), before)
        self.assertTrue(MARKER in raw)
        self.assertNotIn('sourceSha256', raw)
        for name, operation in [('before-html', pipeline_html.render_pipeline), ('before-bundle', pipeline_export.export_bundle)]:
            result = operation(f.workspace, f.sid, f.root / name)
            self.assertTrue((f.root / name).is_dir())
        self.write_profile([MARKER])
        after, raw = wire()
        self.assertTrue(after.get('isError'), after)
        self.assertNotIn(MARKER, raw)
        with self.assertRaises(self.guard.PrivacyError):
            with f.store.open_reader(f.workspace, f.sid, f.meta['businessSnapshotId'], f.meta['businessDigest']) as reader:
                list(reader.iter_records())
        for name, operation in [('blocked-html', pipeline_html.render_pipeline), ('blocked-bundle', pipeline_export.export_bundle)]:
            with self.assertRaises((ValueError, companion.CompanionError)):
                operation(f.workspace, f.sid, f.root / name)
            self.assertFalse((f.root / name).exists())
        self.assertEqual((f.workspace / 'business-state.json').read_bytes(), pointer)


if __name__ == '__main__':
    unittest.main()
