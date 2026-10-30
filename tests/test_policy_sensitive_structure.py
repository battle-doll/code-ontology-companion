"""Value-free source structure never declassifies sensitive terminals."""
import hashlib
import json
import unittest
from unittest import mock

from test_policy_java_contracts import extract
from test_policy_literal_review import occurrence, reviewed, walk
import policy_semantics
import privacy_guard


class SensitiveSourceStructureTests(unittest.TestCase):
    def assert_structural(self, row):
        self.assertTrue(row.get('structuralOnly'))
        self.assertEqual(row['representationStatus'], 'partial')
        self.assertIn('sensitive_value_redacted', row['unsupportedReasons'])
        self.assertFalse(row['businessMeaningVerified'])
        self.assertEqual(row['runtimeStatus'], 'not_observed')
        for node in walk(row):
            if node.get('op') == 'literal':
                self.assertEqual(node['type'], 'null')
                self.assertIsNone(node['value'])
            for field in ('staticContract', 'staticType', 'standardConstant', 'collectionShape', 'recordShape', 'unitEvidence', 'standardApiContracts'):
                self.assertNotIn(field, node)

    def test_resource_lifecycle_and_guard_remain_source_bound(self):
        source = 'class Rules { Resource secretResource; void f(){ secretResource=new Resource(); secretResource.load(bytes); secretResource=null; if(secretResource!=null){secretResource.get(71829);} }}'
        result, _ = extract(source)
        rows = result['fragments'][1:]
        self.assertEqual([r['expression']['op'] for r in rows], ['construct','call','literal','binary','call'])
        for row in rows:
            self.assert_structural(row)
        self.assertEqual(rows[2]['target']['name'], 'secretResource')
        self.assertEqual(rows[3]['expression']['operator'], '!=')
        self.assertEqual(rows[4]['controlFlow']['contexts'][0]['fragmentId'], rows[3]['id'])
        self.assertIn(rows[2]['id'], rows[3]['dataFlow']['reads'][0]['precedingWriteCandidates'])
        self.assertFalse(rows[3]['dataFlow']['valueSubstitution'])
        self.assertTrue(result['coverage']['inventoryComplete'])

    def test_digits_arrays_concatenation_casts_and_receivers_hide_all_values(self):
        sources = [
            'class Rules { long secretDigits=88366127L; boolean secretFlag=true; }',
            'class Rules { int[] secretArray=new int[]{88366127,66557431}; }',
            'class Rules { Object x=secretValue + "PRIVATE_SENTINEL" + 88366127; }',
            'class Rules { Object x=(long)(secretValue+88366127); }',
            'class Rules { void f(){secretArray[88366127]=(byte)66557431;} }',
            'class Rules { Object x=secretReceiver.call(88366127, false, \'Q\'); }',
            'import java.math.BigDecimal; class Rules { Object x=secretReceiver.call(new BigDecimal("88366127.25")); }',
        ]
        for source in sources:
            with self.subTest(source=source):
                result, _ = extract(source)
                for row in result['fragments']:
                    self.assert_structural(row)
                encoded = json.dumps(result)
                for value in ('88366127','66557431','PRIVATE_SENTINEL'):
                    self.assertNotIn(value, encoded)
                masks = [node for node in walk(result) if node.get('op') == 'masked_value']
                self.assertTrue(masks)
                self.assertTrue(all('value' not in node and node['sourceRange']['charEnd'] > node['sourceRange']['charStart'] for node in masks))

    def test_sensitive_guard_masks_switch_labels_and_nested_call_values(self):
        source = 'class Rules { void f(int secretCode){ switch(secretCode){case 88366127: consume(66557431); break; default: consume(false);} if(secretCode!=null){consume("PRIVATE_SENTINEL");} }}'
        result, _ = extract(source)
        for row in result['fragments']:
            self.assert_structural(row)
        encoded = json.dumps(result)
        for value in ('88366127','66557431','PRIVATE_SENTINEL'):
            self.assertNotIn(value, encoded)
        self.assertTrue(any(node.get('op') == 'switch_labels' for node in walk(result)))

    def test_sensitive_loop_retains_clause_structure_without_values(self):
        source = 'class Rules { void f(){for(int i=88366127; secretFlag && i<66557431; i++){consume(99887766);}}}'
        result, _ = extract(source)
        for row in result['fragments']:
            self.assert_structural(row)
        for value in ('88366127','66557431','99887766'):
            self.assertNotIn(value, json.dumps(result))

    def test_sensitive_methods_types_and_enum_arguments_are_structural(self):
        sources = ['class Rules { int getSecret(){return 88366127;} }',
                   'class SecretHolder { int number=88366127; }',
                   'enum SecretCodes { A(88366127); final int number; SecretCodes(int n){this.number=n;} }']
        for source in sources:
            result, _ = extract(source)
            self.assertNotIn('88366127', json.dumps(result))
            for row in result['fragments']:
                if row['expression'] is not None:
                    self.assert_structural(row)

    def test_sensitive_flows_do_not_receive_library_numeric_or_shape_contracts(self):
        source = 'import java.math.BigDecimal; import java.time.Duration; class Rules { Object f(BigDecimal secretNumber){ return secretNumber.add(BigDecimal.ONE).setScale(88366127); } Object g(){return Duration.ofMillis(secretCount);} Object h(){return java.util.Map.of(secretName,88366127);} }'
        result, _ = extract(source)
        for row in result['fragments']:
            self.assert_structural(row)

    def test_sensitive_literal_identity_does_not_correlate_with_visible_decimal(self):
        source = 'import java.math.BigDecimal; class Rules { String secretText="1234.25"; BigDecimal ordinary=new BigDecimal("1234.25"); }'
        result, _ = extract(source)
        sensitive, ordinary = result['fragments']
        self.assert_structural(sensitive)
        self.assertNotEqual(sensitive['literalIdentities']['opaqueIds'], ordinary['literalIdentities']['opaqueIds'])
        self.assertEqual(sensitive['literalIdentities']['scope'], 'source_occurrence')
        self.assertNotIn('1234.25', json.dumps(sensitive))

    def test_reviewed_algorithm_sibling_stays_masked_in_sensitive_expression(self):
        source = 'class Rules { Object value=new SecretKeySpec(key,"SYNTHETIC_ALGORITHM"); }'
        review, digest = reviewed(source, [occurrence(source, '"SYNTHETIC_ALGORITHM"')])
        result = policy_semantics.extract_semantics(source, 'Java', 'Rules.java', digest, literal_review=review)
        self.assert_structural(result['fragments'][0])
        self.assertEqual(result['fragments'][0]['expression']['op'], 'construct')
        self.assertNotIn('SYNTHETIC_ALGORITHM', json.dumps(result))
        self.assertEqual(review.coverage()['entries'][0]['reason'], 'sensitive_context')

    def test_profile_denied_identifier_never_bypasses_final_guard(self):
        source = 'class Rules { Object f(){return secretResource.call(FictionalIdentity);} }'
        profile = privacy_guard.build_profile(['FictionalIdentity'], [], key=b'x'*32)
        original = privacy_guard.ensure_public_safe
        with mock.patch.object(privacy_guard, 'ensure_public_safe', side_effect=lambda value: original(value, profile=profile)):
            result, _ = extract(source)
        self.assertNotIn('FictionalIdentity', json.dumps(result))
        self.assertEqual(result['fragments'][0]['unsupportedReasons'], ['privacy_denied'])

    def test_sensitive_deferred_parent_propagates_through_nested_bodies(self):
        sources = [
            'class Rules { java.util.function.IntSupplier secretCallback=()->{return 87162345;}; }',
            'class Rules { Object secretFactory=new Object(){int f(){return 87162345;}}; }',
            'class Rules { boolean active; java.util.function.IntSupplier secretCallback=()->{if(active){java.util.function.IntSupplier inner=()->{return 87162345;};return inner.getAsInt();}return 66554433;}; }',
            'class Rules { int mode; Object secretFactory=new Object(){int f(){switch(mode){case 11111111:for(int i=0;i<2;i++){consume(new Object(){int g(){return 87162345;}});}default:return 66554433;}}}; }',
            'class Rules { int mode; Object secretFactory=switch(mode){case 0->{yield new Object(){int value(){return 87162345;}};}default->null;}; }',
        ]
        for source in sources:
            with self.subTest(source=source):
                result, _ = extract(source)
                for value in ('87162345', '66554433', '11111111'):
                    self.assertNotIn(value, json.dumps(result))
                descendants = [row for row in result['fragments'] if any(c['kind']=='embedded_body' for c in row.get('controlFlow',{}).get('contexts',[]))]
                self.assertTrue(descendants)
                for row in descendants:
                    self.assertTrue(row.get('structuralOnly'))
                    if row['expression'] is not None:
                        self.assert_structural(row)

    def test_reviewed_string_remains_denied_in_sensitive_deferred_descendant(self):
        source = 'class Rules { java.util.function.Supplier<String> secretCallback=()->{return "MASK_SENTINEL";}; }'
        review, digest = reviewed(source, [occurrence(source, '"MASK_SENTINEL"')])
        result = policy_semantics.extract_semantics(source, 'Java', 'Rules.java', digest, literal_review=review)
        self.assertNotIn('MASK_SENTINEL', json.dumps(result))
        self.assertEqual(review.summary()['rejectedEntries'], 1)
        self.assertEqual(review.coverage()['entries'][0]['reason'], 'sensitive_context')

    def test_ordinary_deferred_body_retains_non_sensitive_contracts(self):
        source = 'class Rules { java.util.function.IntSupplier callback=()->{return Math.max(7,8);}; }'
        result, _ = extract(source)
        returned = next(row for row in result['fragments'] if row['category']=='return')
        self.assertNotIn('structuralOnly', returned)
        self.assertEqual(returned['standardApiContracts'][0]['operation'], 'numeric_max')

    def test_final_tree_gate_rejects_unmasked_terminal_from_later_parser_path(self):
        source = 'class Rules { Object secretField=unknown; }'
        with mock.patch.object(policy_semantics._Expression, 'parse', return_value={'op':'literal','type':'string','value':'PRIVATE_SENTINEL'}):
            result, _ = extract(source)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertEqual(result['fragments'][0]['unsupportedReasons'], ['structural_safety_veto'])
        self.assertEqual(result['coverage']['unsupportedFragments'], 1)


if __name__ == '__main__':
    unittest.main()
