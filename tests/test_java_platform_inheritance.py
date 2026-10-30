"""Neutral static parent inventory proofs; no application-specific fixtures."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from test_policy_java_contracts import core, extract, pipeline_java, returns, bindings
from test_policy_literal_review import walk, reviewed, occurrence
from test_policy_dependency_closure import analyzed_files, finish
import pipeline_adapters
import pipeline_store
import policy_semantics

platform = pipeline_java.policy_java_platform
BD = 'import java.math.BigDecimal;'


def source(parent='', extra='', imports='', expression='n.abs()'):
    return BD + imports + 'class Rules ' + parent + '{' + extra + 'BigDecimal f(BigDecimal n){return ' + expression + ';}}'


def row(text, others=None):
    return returns(extract(text, others)[0])[-1]


class PlatformInheritanceTests(unittest.TestCase):
    def test_exact_platform_parents_and_transitive_catalog_are_source_bound(self):
        for parent, imports, expected in [
            ('implements AutoCloseable', '', {'java.lang.AutoCloseable'}),
            ('implements java.lang.AutoCloseable', '', {'java.lang.AutoCloseable'}),
            ('implements AutoCloseable', 'import java.lang.AutoCloseable;', {'java.lang.AutoCloseable'}),
            ('implements Runnable', '', {'java.lang.Runnable'}),
            ('implements Comparable<String>', '', {'java.lang.Comparable'}),
            ('implements Closeable', 'import java.io.Closeable;', {'java.io.Closeable', 'java.lang.AutoCloseable'}),
            ('implements Runnable,AutoCloseable', '', {'java.lang.Runnable', 'java.lang.AutoCloseable'}),
            ('extends Object', '', {'java.lang.Object'}),
        ]:
            with self.subTest(parent=parent, imports=imports):
                text = source(parent, imports=imports)
                item = row(text)
                self.assertEqual(len(bindings(item)), 1)
                self.assertEqual({c['qualifiedName'] for c in item['platformTypeContracts']}, expected)
                self.assertTrue(all(c['actualTargetJdk'] == 'UNKNOWN' and c['effectivePlatform'] == 'Java SE 21' for c in item['platformTypeContracts']))
                checks = {c['id']: c for c in item['platformInheritanceChecks']}
                for node in walk(item['expression']):
                    if 'platformInheritance' in node:
                        ref = node['platformInheritance']
                        self.assertEqual(ref['catalogLocation'], 'fragment.platformInheritanceChecks')
                        for key in ref['checkIds']:
                            check = checks[key]
                            self.assertEqual(check['status'], 'absent')
                            self.assertTrue(check['transitiveInventoryComplete'])
                            for scope in check['sourceScopes']:
                                self.assertEqual(scope['path'], 'Rules.java')
                                self.assertEqual(scope['sourceDigest'], hashlib.sha256(text.encode()).hexdigest())
                                self.assertIn('class Rules', text[scope['sourceRange']['charStart']:scope['sourceRange']['charEnd']])
                    for identity in node.get('sourceEvidenceIds', []):
                        self.assertFalse(identity.startswith(('jdk21-members:', 'platform-lookup:')))

    def test_unknown_mixed_foreign_and_impersonated_parents_never_establish_absence(self):
        cases = [
            (source('implements Missing'), {}),
            (source('implements Closeable', imports='import java.io.*;'), {}),
            (source('implements AutoCloseable,Missing'), {}),
            (source('implements AutoCloseable', imports='import external.AutoCloseable;'), {}),
            (source('implements AutoCloseable', imports='import external.*;'), {}),
            (source('implements AutoCloseable'), {'java/lang/AutoCloseable.java': 'package java.lang;public interface AutoCloseable{}'}),
            (source('implements Own'), {'Own.java': 'interface Own extends Missing{}'}),
            (source('implements java.unknown.AutoCloseable'), {}),
            (source('implements java.io.Closeable'), {'java/lang/AutoCloseable.java': 'package java.lang;public interface AutoCloseable{}'}),
        ]
        for text, others in cases:
            with self.subTest(text=text):
                item = row(text, others)
                self.assertFalse(bindings(item))
                self.assertTrue(any(c['status'] == 'UNKNOWN' for c in item.get('platformInheritanceChecks', [])))

    def test_duplicate_selected_parent_declarations_keep_existing_index_rejection(self):
        with self.assertRaises(core.DuplicateDeclarationError):
            row(source("implements Own"), {"a/Own.java": "interface Own extends AutoCloseable{}", "b/Own.java": "interface Own{}"})

    def test_explicit_import_precedence_and_ambiguity(self):
        for imports in ('import external.AutoCloseable;import java.lang.AutoCloseable;',
                        'import java.lang.AutoCloseable;import external.AutoCloseable;',
                        'import external . AutoCloseable;import java.lang.AutoCloseable;'):
            self.assertFalse(bindings(row(source('implements AutoCloseable', imports=imports))))
        for imports in ('import java.lang.AutoCloseable;import java.lang.AutoCloseable;',
                        'import java.lang.AutoCloseable;import unknown.api.*;'):
            self.assertTrue(bindings(row(source('implements AutoCloseable', imports=imports))))
        for imports in ('import custom.BigDecimal;import java.math.BigDecimal;',
                        'import java.math.BigDecimal;import custom.BigDecimal;'):
            self.assertFalse(bindings(row(source('implements AutoCloseable', imports=imports),
                {'custom/BigDecimal.java': 'package custom;public class BigDecimal{}'})))

    def test_lexical_type_variables_and_member_types_do_not_use_platform_shortcuts(self):
        for text, others in [
            (BD + 'class Rules<BigDecimal> implements AutoCloseable{Object f(BigDecimal n){return n.abs();}}', {}),
            (BD + 'class Rules<AutoCloseable> implements AutoCloseable{Object f(BigDecimal n){return n.abs();}}', {}),
            (source('implements Own,AutoCloseable'), {'Own.java': 'interface Own{class BigDecimal{}}'}),
            (source('implements AutoCloseable'), {'AutoCloseable.java': 'interface AutoCloseable{class BigDecimal{}}'}),
            (source('implements external.AutoCloseable'), {'external/AutoCloseable.java': 'package external;public interface AutoCloseable{class BigDecimal{}}'}),
        ]:
            with self.subTest(text=text): self.assertFalse(bindings(row(text, others)))
        # Selected source declarations retain their source-based behavior,
        # without pretending a foreign same-simple-name type is a JDK type.
        item = row(source('implements external.AutoCloseable'), {'external/AutoCloseable.java': 'package external;public interface AutoCloseable{}'})
        self.assertTrue(bindings(item)); self.assertNotIn('platformTypeContracts', item)

    def test_nonempty_map_member_inventory_and_field_namespace_are_distinct(self):
        item = row(source('implements java.util.Map<String,String>'))
        self.assertTrue(bindings(item))
        self.assertEqual(item['platformTypeContracts'][0]['memberTypes'], ['Entry'])
        text = 'import selected.Entry;abstract class Rules implements java.util.Map<String,String>{Entry f(Entry n){return n;}}'
        item = row(text, {'selected/Entry.java': 'package selected;public class Entry{}'})
        self.assertNotIn('staticType', item['expression'])
        self.assertTrue(any(c['queriedName'] == 'Entry' and c['status'] == 'present' for c in item['platformInheritanceChecks']))
        # A field called BigDecimal does not hide a type in a type position.
        item = row(source('implements Own,AutoCloseable'), {'Own.java': 'interface Own{int BigDecimal=1;}'} )
        self.assertTrue(bindings(item))
        # The same source field does hide a static value qualifier.
        text = 'class Rules implements Own,AutoCloseable{int f(){return Math.abs(1);}}'
        self.assertFalse(bindings(row(text, {'Own.java': 'interface Own{Object Math=null;}'})))

    def test_selected_transitive_scopes_and_cached_queries_retain_provenance(self):
        text = source('implements Own', expression='n.abs().negate().min(n.abs())')
        others = {'Own.java': 'interface Own extends java.io.Closeable{}'}
        result, facts = extract(text, others)
        item = returns(result)[-1]
        self.assertEqual(len(bindings(item)), 4)
        self.assertEqual(len(item['platformTypeContracts']), 2)
        self.assertTrue(all({s['path'] for s in c['sourceScopes']} == {'Own.java','Rules.java'} for c in item['platformInheritanceChecks']))
        self.assertEqual(len({c['id'] for c in item['platformInheritanceChecks']}), len(item['platformInheritanceChecks']))
        index = core.build_java_index({'Rules.java': text, **others})
        context = pipeline_java.semantic_type_context(facts, index)
        offset = text.index('return')
        outputs = []
        for _ in range(2):
            projection = context['platformProjection']()
            typed = projection.call(context['resolve'], 'BigDecimal', offset)
            out = {'expression': {'staticType': typed}}; projection.finish(out); outputs.append(out)
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn('platformInheritance', outputs[1]['expression']['staticType'])

    def test_record_component_projection_has_its_own_catalog_without_constructor_calls(self):
        text = BD + 'record Box(BigDecimal amount) implements AutoCloseable{public void close(){} BigDecimal f(){return amount.abs();}}'
        result, facts = extract(text)
        record = next(r for r in facts['records'] if r.get('type') == 'Record')
        component = record['recordComponents'][0]
        self.assertEqual(component['type'], 'java.math.BigDecimal')
        self.assertEqual(component['platformInheritance']['catalogLocation'], 'record.platformInheritanceChecks')
        self.assertTrue(record['platformTypeContracts'])
        self.assertTrue(bindings(returns(result)[-1]))
        self.assertFalse(any(c['name'] == 'abs' and c.get('resolution') == 'exact' for c in facts['records'] if c['kind'] == 'callsite'))

    def test_sensitive_structure_never_acquires_platform_proofs_or_values(self):
        for expression in ('new java.math.BigDecimal(87162345).abs()', 'n.add(new java.math.BigDecimal(87162345))'):
            result, _ = extract(source('implements AutoCloseable', extra='BigDecimal secret;', expression='secret = '+expression))
            item = returns(result)[-1]
            self.assertTrue(item['structuralOnly'])
            encoded = json.dumps(item)
            self.assertNotIn('87162345', encoded)
            self.assertNotIn('platformTypeContracts', item)
            self.assertFalse(bindings(item))

    def test_projection_and_transitive_budgets_fail_closed(self):
        text = source('implements AutoCloseable')
        with patch.object(platform, 'MAX_CHECKS', 0):
            item = row(text)
            self.assertFalse(bindings(item))
            self.assertEqual(item['platformInheritanceCoverage']['status'], 'PARTIAL')
        with patch.object(platform, 'MAX_CATALOG_BYTES', 8):
            self.assertFalse(bindings(row(text)))
        others = {f'I{i}.java': f'interface I{i} extends I{i+1}{{}}' for i in range(18)}
        others['I18.java'] = 'interface I18 extends AutoCloseable{}'
        item = row(source('implements I0'), others)
        self.assertFalse(bindings(item))
        self.assertTrue(any('inheritance_scope_budget_exceeded' in c['reasons'] for c in item['platformInheritanceChecks']))

    def test_value_free_catalog_size_is_bounded_for_deep_chains(self):
        text = source('implements AutoCloseable', expression='n' + '.abs()' * 24)
        item = row(text)
        self.assertEqual(len(bindings(item)), 24)
        self.assertEqual(len(item['platformTypeContracts']), 1)
        self.assertEqual(len(item['platformInheritanceChecks']), 1)
        self.assertLess(len(json.dumps(item).encode()), 256 * 1024)
        self.assertLess(len(list(walk(item))), 20_000)

    def test_pruning_withdraws_positive_definitions_but_keeps_unknown_diagnostics(self):
        item = row(source('implements AutoCloseable'))
        self.assertIn('platformTypeContracts', item)
        item['expression'] = None; platform.prune(item)
        self.assertNotIn('platformTypeContracts', item); self.assertNotIn('platformInheritanceChecks', item)
        unknown = row(source('implements Missing'))
        unknown['expression'] = None; platform.prune(unknown)
        self.assertEqual(unknown['platformInheritanceChecks'][0]['status'], 'UNKNOWN')

    def test_snapshot_finalization_validates_selected_scope_identity_and_parent_projection(self):
        text = source('implements Own', expression='combine(n.abs(),17)')
        sources = {'Rules.java': text, 'Own.java': 'interface Own extends java.io.Closeable{}'}
        for fault in ('none', 'missing', 'digest', 'range', 'parent', 'type'):
            with self.subTest(fault=fault):
                results, facts = analyzed_files(sources)
                def transform(record):
                    if record.get('qualifiedName') != 'Own': return record
                    record = copy.deepcopy(record)
                    if fault == 'missing': return None
                    if fault == 'digest': record['sourceDigest'] = '0' * 64
                    if fault == 'range': record['declarationHeaderRange']['charEnd'] -= 1
                    if fault == 'parent': record['extendsTypes'][0]['resolvedType'] = 'other.Closeable'
                    if fault == 'type': record['type'] = 'Method'
                    return record
                finish(results, facts, transform)
                item = returns(results['Rules.java'])[-1]
                self.assertEqual(bool(bindings(item)), fault == 'none')
                self.assertTrue(any(n.get('value') == '17' or n.get('value') == 17 for n in walk(item)))
                if fault != 'none':
                    self.assertNotIn('platformTypeContracts', item)
                    self.assertNotIn('platformInheritanceChecks', item)

    def test_late_loop_revocation_withdraws_platform_contracts_but_not_a_surviving_sibling(self):
        text = ('record Item(java.math.BigDecimal amount) implements AutoCloseable{public void close(){}}'
                'class Rules implements AutoCloseable{public void close(){}Item[] make(String label){return null;}'
                'void use(java.math.BigDecimal n){}void consume(String t){}void f(java.math.BigDecimal n){'
                'for(Item item:make("MODE_A")){use(item.amount().abs());consume("TRIGGER_MODE");}use(n.abs());}}')
        review, digest = reviewed(text, [occurrence(text, '"MODE_A"'), occurrence(text, '"TRIGGER_MODE"')])
        bound = review.bind_source('Rules.java', text, digest); admit = bound.admit
        def revoke(left, right, **kwargs):
            if left == text.index('"TRIGGER_MODE"'): review.reject(0, 'fragment_redacted')
            return admit(left, right, **kwargs)
        bound.admit = revoke
        results, facts = analyzed_files({'Rules.java': text}, review=review); finish(results, facts)
        fragments = results['Rules.java']['fragments']
        child = next(f for f in fragments if any(n.get('name') == 'item.amount' for n in walk(f)))
        self.assertFalse(bindings(child)); self.assertNotIn('platformTypeContracts', child)
        self.assertTrue(any(bindings(f) for f in fragments if f is not child))
        self.assertNotIn('MODE_A', json.dumps(results))

    def test_store_binds_model_and_helper_hash_without_changing_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); repo = root / 'source'; repo.mkdir(); workspace = root / 'workspace'
            text = source('implements AutoCloseable')
            (repo / 'Rules.java').write_text(text)
            snapshot = pipeline_store.initialize(repo, workspace)
            with pipeline_store.open_reader(workspace) as reader:
                self.assertEqual(reader.metadata['javaStaticModel'], platform.MODEL)
                rows = list(reader.iter_records())
                self.assertTrue(any(r.get('platformTypeContracts') for r in rows))
                actual_calls = [r for r in rows if r['kind'] == 'callsite']
                facts = extract(text)[1]
                expected = [(r['id'], r.get('target'), r.get('resolution')) for r in facts['records'] if r['kind'] == 'callsite']
                self.assertEqual(sorted((r['id'], r.get('target'), r.get('resolution')) for r in actual_calls), sorted(expected))
            config = json.loads((workspace / 'pipeline.json').read_text())
            original_spec = pipeline_store._spec(config); read = pipeline_store._read
            def changed(path, limit):
                data = read(path, limit)
                return data + b'\n# synthetic change' if path.name == 'policy_java_platform.py' else data
            with patch.object(pipeline_store, '_read', changed):
                self.assertNotEqual(pipeline_store._spec(config), original_spec)
            self.assertEqual(pipeline_store.status(workspace)['snapshotId'], snapshot['snapshotId'])

    def test_unindexed_multi_field_declarations_never_become_platform_absence(self):
        for declaration in (
            'Holder first,BigDecimal;', 'Holder first=null,BigDecimal;',
            'Holder BigDecimal,first;', 'Holder BigDecimal,first=new Holder(){};',
            'Holder first=make(),BigDecimal;Holder make(){return null;}',
            'Holder first=(null),BigDecimal;',
        ):
            with self.subTest(declaration=declaration):
                text = (BD + 'class Holder{static String ZERO;}'
                    'abstract class Base implements java.lang.AutoCloseable{' + declaration + '}'
                    'class Child extends Base{public void close(){}Object read(){return BigDecimal.ZERO;}}')
                item = row(text)
                self.assertFalse(any('standardConstant' in n for n in walk(item)))
                check = next(c for c in item['platformInheritanceChecks'] if c['queriedName'] == 'BigDecimal')
                self.assertEqual(check['status'], 'present')
                self.assertTrue(check['transitiveInventoryComplete'])
                base = next(scope for scope in check['sourceScopes'] if scope['qualifiedName'] == 'Base')
                self.assertEqual(base['memberInventory']['fields'], 'complete')
                self.assertEqual(base['memberInventory']['fieldNames'], ['BigDecimal', 'first'])
                self.assertFalse(check['reasons'])

    def test_own_interface_and_transitive_multi_fields_fail_closed_without_call_changes(self):
        cases = [
            BD + 'class Holder{static String ZERO;}class Rules implements AutoCloseable{Holder first,BigDecimal;public void close(){}Object read(){return BigDecimal.ZERO;}}',
            BD + 'class Holder{static String ZERO;}interface Own{Holder first=null,BigDecimal=null;}class Rules implements Own,AutoCloseable{public void close(){}Object read(){return BigDecimal.ZERO;}}',
            BD + 'class Holder{static String ZERO;}abstract class Base implements AutoCloseable{Holder first,BigDecimal;}abstract class Middle extends Base{}class Rules extends Middle{public void close(){}Object read(){return BigDecimal.ZERO;}}',
        ]
        for text in cases:
            with self.subTest(text=text):
                result, facts = extract(text)
                self.assertFalse(any('standardConstant' in n for f in result['fragments'] for n in walk(f)))
                self.assertFalse(any(c['status'] == 'absent' and c['namespace'] == 'field_or_member_type'
                                     for f in result['fragments'] for c in f.get('platformInheritanceChecks', [])))
                index = core.build_java_index({'Rules.java': text})
                direct = {'path': 'Rules.java', 'sourceDigest': hashlib.sha256(text.encode()).hexdigest(),
                          'module': 'synthetic', 'modulePath': '.', 'records': []}
                pipeline_java.enrich(direct, index)
                self.assertEqual([r for r in facts['records'] if r['kind'] == 'callsite'],
                                 [r for r in direct['records'] if r['kind'] == 'callsite'])

    def test_complete_multi_field_inventory_keeps_type_and_value_namespaces_distinct(self):
        text = (BD + 'class Holder{}abstract class Base implements AutoCloseable{Holder first,BigDecimal;}'
                'class Rules extends Base{public void close(){}BigDecimal f(BigDecimal n){return n.abs();}}')
        item = row(text)
        self.assertEqual(len(bindings(item)), 1)
        self.assertTrue(all(c['namespace'] == 'member_type' and c['status'] == 'absent'
                            for c in item['platformInheritanceChecks']))
        self.assertTrue(all(s['memberInventory']['fields'] == 'complete'
                            for c in item['platformInheritanceChecks'] for s in c['sourceScopes']))
        hidden = row(text.replace('n.abs()', 'BigDecimal.ZERO'))
        self.assertFalse(any('standardConstant' in n for n in walk(hidden)))
        self.assertFalse(bindings(hidden))

    def test_supported_member_boundaries_keep_safe_static_qualifiers(self):
        text = (BD + 'abstract class Rules implements AutoCloseable{'
                'int count=1;String label="BigDecimal";Object value=new Object(){};'
                '{int Math=1;}static{int BigDecimal=1;}abstract void f(int first,int second);'
                'void g(int first,int second){}class Nested{Object Math;}'
                'Object read(){return BigDecimal.ZERO;}}')
        item = row(text)
        self.assertTrue(any('standardConstant' in n for n in walk(item)))
        self.assertTrue(all(s['memberInventory']['fields'] == 'complete'
                            for c in item['platformInheritanceChecks'] for s in c['sourceScopes']))

    def test_unverified_annotation_unicode_and_inventory_limits_remain_unknown(self):
        for extra in ('@Deprecated Object value;',
                      r'Object first,BigDecim\u0061l;'):
            with self.subTest(extra=extra):
                item = row(source('implements AutoCloseable', extra=extra, expression='BigDecimal.ZERO'))
                self.assertFalse(any('standardConstant' in n for n in walk(item)))
                self.assertTrue(any(c['status'] == 'UNKNOWN' for c in item['platformInheritanceChecks']))
        with patch.object(platform, 'MAX_SOURCE_MEMBERS', 1):
            item = row(source('implements AutoCloseable', extra='int first;int second;'))
            self.assertFalse(bindings(item))
            self.assertTrue(any('selected_source_member_inventory_budget_exceeded' in c['reasons']
                                for c in item['platformInheritanceChecks']))

    def test_incomplete_member_type_inventory_withholds_positive_type_bridge(self):
        # An unsupported annotated constructor header still cannot authorize
        # a complete member-name absence observation.
        item = row(source('implements AutoCloseable', extra='@Deprecated Rules(){}'))
        self.assertFalse(bindings(item))
        self.assertTrue(any(c['status'] == 'UNKNOWN' and not c['transitiveInventoryComplete']
                            for c in item['platformInheritanceChecks']))

    def test_positive_requirements_reject_missing_or_unknown_member_inventory(self):
        item = row(source('implements AutoCloseable'))
        check = item['platformInheritanceChecks'][0]
        for fault in ('missing', 'memberTypes', 'observed'):
            value = copy.deepcopy(item)
            changed = value['platformInheritanceChecks'][0]
            inventory = changed['sourceScopes'][0]['memberInventory']
            if fault == 'missing': changed['sourceScopes'][0].pop('memberInventory')
            elif fault == 'memberTypes': inventory['memberTypes'] = 'UNKNOWN'
            else: inventory['observedDirectDeclarationRegions'] = -1
            old_id = changed['id']
            changed['id'] = 'platform-lookup:' + hashlib.sha256(platform.canonical({k:v for k,v in changed.items() if k != 'id'})).hexdigest()[:24]
            for node in walk(value['expression']):
                if 'platformInheritance' in node:
                    node['platformInheritance']['checkIds'] = [changed['id'] if key == old_id else key for key in node['platformInheritance']['checkIds']]
            _, reason = platform.requirements(value['expression'], value)
            self.assertEqual(reason, 'platform_source_member_inventory_unverified')

    def test_conflicting_duplicate_definitions_withdraw_proof_in_both_orders(self):
        text = source('implements AutoCloseable', expression='combine(n.abs(),17)')
        for key in ('platformInheritanceChecks', 'platformTypeContracts'):
            for bad_first in (True, False):
                with self.subTest(key=key, bad_first=bad_first):
                    results, facts = analyzed_files({'Rules.java': text})
                    item = returns(results['Rules.java'])[-1]
                    good = copy.deepcopy(item[key][0]); bad = copy.deepcopy(good)
                    if key == 'platformInheritanceChecks':
                        bad['sourceScopes'][0]['memberInventory']['memberTypes'] = 'UNKNOWN'
                    else:
                        bad['memberTypes'] = ['BigDecimal']
                    item[key] = [bad, good] if bad_first else [good, bad]
                    finish(results, facts)
                    self.assertFalse(bindings(item))
                    self.assertIn('platform_inheritance_definition_conflict', json.dumps(item))
                    self.assertTrue(any(n.get('value') in (17, '17') for n in walk(item)))
                    self.assertEqual(item['expression']['op'], 'call')

    def test_conflicting_check_does_not_withdraw_independent_typed_sibling(self):
        text = source('implements AutoCloseable', expression='combine(n.abs(),Math.abs(17))')
        for bad_first in (True, False):
            results, facts = analyzed_files({'Rules.java': text})
            item = returns(results['Rules.java'])[-1]
            good = next(c for c in item['platformInheritanceChecks'] if c['queriedName'] == 'BigDecimal')
            bad = copy.deepcopy(good); bad['sourceScopes'][0]['memberInventory']['memberTypes'] = 'UNKNOWN'
            item['platformInheritanceChecks'].insert(0 if bad_first else len(item['platformInheritanceChecks']), bad)
            finish(results, facts)
            self.assertEqual([contract['declaringType'] for _, contract in bindings(item)], ['java.lang.Math'])
            self.assertTrue(any(n.get('value') in (17, '17') for n in walk(item)))

    def test_identical_canonical_duplicates_are_equivalent_in_both_definition_arrays(self):
        text = source('implements AutoCloseable')
        for key in ('platformInheritanceChecks', 'platformTypeContracts'):
            results, facts = analyzed_files({'Rules.java': text})
            item = returns(results['Rules.java'])[-1]
            # Mapping key order does not change a canonical JSON definition.
            duplicate = dict(reversed(list(copy.deepcopy(item[key][0]).items())))
            item[key].insert(0, duplicate)
            finish(results, facts)
            self.assertEqual(len(bindings(item)), 1)
            self.assertNotIn('platform_inheritance_definition_conflict', json.dumps(item))

    def test_conflicting_duplicate_status_is_not_overwritten_by_a_third_definition(self):
        text = source('implements AutoCloseable')
        for key in ('platformInheritanceChecks', 'platformTypeContracts'):
            for arrangement in ('good_bad_good', 'bad_good_bad'):
                results, facts = analyzed_files({'Rules.java': text})
                item = returns(results['Rules.java'])[-1]
                good = copy.deepcopy(item[key][0]); bad = copy.deepcopy(good)
                if key == 'platformInheritanceChecks':
                    bad['sourceScopes'][0]['memberInventory']['memberTypes'] = 'UNKNOWN'
                else:
                    bad['inventoryComplete']['fields'] = 1
                item[key] = [copy.deepcopy({'good': good, 'bad': bad}[name]) for name in arrangement.split('_')]
                finish(results, facts)
                self.assertFalse(bindings(item))
                self.assertIn('platform_inheritance_definition_conflict', json.dumps(item))

    def test_single_catalog_with_coerced_boolean_does_not_match_exact_model(self):
        results, facts = analyzed_files({'Rules.java': source('implements AutoCloseable')})
        item = returns(results['Rules.java'])[-1]
        item['platformTypeContracts'][0]['inventoryComplete']['fields'] = 1
        finish(results, facts)
        self.assertFalse(bindings(item))
        self.assertIn('platform_inheritance_definition_invalid', json.dumps(item))

    def test_trusted_core_loader_does_not_use_a_foreign_same_name_module(self):
        hostile = types.ModuleType('policy_java_platform')
        hostile.VERSION = 'foreign-untrusted'
        with patch.dict(sys.modules, {'policy_java_platform': hostile}):
            helper = core._load_bundled_helper('policy_java_contracts').policy_java_platform
            self.assertEqual(helper.VERSION, 'java-se21-member-inventory-1')
            self.assertEqual(Path(helper.__file__).resolve(), Path(pipeline_java.__file__).with_name('policy_java_platform.py').resolve())
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp); (target / 'policy_java_platform.py').write_text('raise RuntimeError("foreign module executed")')
            script = ('import importlib.util;from pathlib import Path;'
                's=importlib.util.spec_from_file_location("checked_core",'+repr(core.__file__)+');'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                'h=m._load_bundled_helper("policy_semantics");'
                'assert h.policy_java_contracts.policy_java_platform.VERSION=="java-se21-member-inventory-1"')
            completed = subprocess.run([sys.executable, '-c', script], cwd=temp, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__': unittest.main()
