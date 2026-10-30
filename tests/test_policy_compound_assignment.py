"""All Java assignment operators survive extraction without invented values."""
import hashlib
import json
import unittest

from test_policy_semantics import extract
from test_policy_java_contracts import extract as typed_extract
import policy_semantics as semantics


OPERATORS = ('=', '*=', '/=', '%=', '+=', '-=', '<<=', '>>=', '>>>=', '&=', '^=', '|=')


def assignments(result):
    return [row for row in result['fragments'] if row['category'] == 'assignment']


class CompoundAssignmentTests(unittest.TestCase):
    def test_all_twelve_operators_keep_their_exact_source_operator_and_target(self):
        for operator in OPERATORS:
            with self.subTest(operator=operator):
                source = 'class Operators { void apply(int other){int value=3;value ' + operator + ' other;} }'
                result = extract(source)
                row, = assignments(result)
                self.assertEqual(row['assignmentOperator'], operator)
                self.assertEqual(row['target'], {'op': 'reference', 'name': 'value'})
                self.assertEqual(row['expression'], {'op': 'reference', 'name': 'other'})
                self.assertEqual(row['sourceDigest'], hashlib.sha256(source.encode()).hexdigest())
                self.assertEqual(row['dataFlow']['writes'][0]['operator'], operator)
                self.assertTrue(row['dataFlow']['writes'][0]['declarationIds'])
                self.assertFalse(row['businessMeaningVerified'])
                self.assertEqual(row['runtimeStatus'], 'not_observed')
                self.assertEqual('assignmentSemantics' in row, operator != '=')
                if operator != '=':
                    self.assertEqual(row['assignmentSemantics']['binaryOperator'], operator[:-1])
                    self.assertEqual(row['assignmentSemantics']['resultValue'], 'UNKNOWN')

    def test_boolean_compound_operators_are_eager_not_conditional_or_and(self):
        for operator in ('|=', '&=', '^='):
            source = 'class Operators{void apply(boolean incoming){boolean flag=false;flag ' + operator + ' incoming;}}'
            row, = assignments(extract(source))
            contract = row['assignmentSemantics']
            self.assertEqual(contract['operator'], operator)
            self.assertFalse(contract['rightHandSideSkippedByBooleanShortCircuit'])
            self.assertEqual(contract['targetValueRead'], 'saved_before_right_hand_side')
            self.assertEqual(contract['targetEvaluationCountOnNormalPath'], 1)
            self.assertEqual(contract['atomicity'], 'UNKNOWN')

    def test_field_member_array_and_effectful_target_are_not_duplicated(self):
        for target in ('this.bits', 'other.bits', 'values[index]', 'holder().bits', 'values[next()]'):
            with self.subTest(target=target):
                source = 'class Operators{int bits;void apply(Operators other,int[] values,int index){' + target + ' |= 2;}}'
                row, = assignments(extract(source))
                self.assertNotEqual(row['target']['op'], 'unresolved')
                self.assertEqual(row['assignmentOperator'], '|=')
                self.assertEqual(row['assignmentSemantics']['targetPointer'], '/target')
                self.assertEqual(row['assignmentSemantics']['targetEvaluationCountOnNormalPath'], 1)
                self.assertEqual(row['assignmentSemantics']['typeCompatibility'], 'UNKNOWN')
                self.assertNotIn('evaluatedValue', row)

    def test_longest_match_and_binary_shift_tokens_are_distinct(self):
        for operator in OPERATORS:
            tokens = semantics._tokens('value' + operator + 'other')
            self.assertEqual([t.value for t in tokens], ['value', operator, 'other'])
        for operator in ('>>>', '>>', '<<', '|', '&', '^', '||', '&&', '==', '>='):
            self.assertEqual([t.value for t in semantics._tokens('a' + operator + 'b')], ['a', operator, 'b'])

    def test_unknown_targets_are_counted_as_partial_not_represented(self):
        for target in ('value +', 'left ||', '1', 'read()'):
            with self.subTest(target=target):
                result = extract('class Operators{void apply(int other){' + target + ' = other;}}')
                row, = assignments(result)
                self.assertEqual(row['representationStatus'], 'partial')
                self.assertTrue(row['unsupportedReasons'])
                self.assertNotIn('assignmentSemantics', row)
                self.assertGreaterEqual(result['coverage']['partialFragments'], 1)
                self.assertFalse(result['coverage']['semanticComplete'])

    def test_reserved_pseudo_values_are_not_assignment_variables(self):
        for target in ('this', 'super', 'Outer.this', 'Outer.super', 'String.class', 'int', '_', 'holder().class'):
            with self.subTest(target=target):
                result = extract('class Operators{void apply(int next){' + target + ' |= next;}}')
                row, = assignments(result)
                self.assertEqual(row['assignmentOperator'], '|=')
                self.assertEqual(row['representationStatus'], 'partial')
                self.assertIn('assignment_target_not_variable', row['unsupportedReasons'])
                self.assertNotIn('assignmentSemantics', row)
        for target in ('this.bits', 'Outer.this.bits', 'super.bits', 'var', 'record'):
            with self.subTest(target=target):
                row, = assignments(extract('class Operators{void apply(int next){' + target + ' |= next;}}'))
                self.assertNotIn('assignment_target_not_variable', row['unsupportedReasons'])
                self.assertEqual(row['assignmentSemantics']['typeCompatibility'], 'UNKNOWN')
        # A leading contextual `yield` is a separate existing flow boundary;
        # this target-name repair does not pretend to resolve that ambiguity.
        result = extract('class Operators{void apply(int next){int yield=0;yield |= next;}}')
        self.assertGreater(result['coverage']['unsupportedFragments'], 0)
        self.assertFalse(result['coverage']['semanticComplete'])

    def test_invalid_declaration_and_nested_assignment_keep_unsupported_status(self):
        result = extract('class Operators{void apply(int other){int value |= other;}}')
        row = next(row for row in result['fragments'] if row.get('name') == 'value')
        self.assertIn('compound_assignment_in_declaration_not_valid', row['unsupportedReasons'])
        self.assertNotIn('assignmentSemantics', row)
        result = extract('class Operators{void apply(int left,int right){left |= (right = 2);}}')
        row, = assignments(result)
        self.assertEqual(row['assignmentOperator'], '|=')
        self.assertEqual(row['representationStatus'], 'unsupported')
        self.assertTrue(row['unsupportedReasons'])
        self.assertNotIn('assignmentSemantics', row)

    def test_structural_sensitive_values_do_not_gain_operator_contracts(self):
        source = 'class Operators{void apply(){int secretBits=88273726;secretBits |= 99346482;}}'
        result = extract(source)
        self.assertNotIn('88273726', json.dumps(result))
        self.assertNotIn('99346482', json.dumps(result))
        row, = assignments(result)
        self.assertEqual(row['assignmentOperator'], '|=')
        self.assertTrue(row.get('structuralOnly'))
        self.assertNotIn('assignmentSemantics', row)

    def test_type_enrichment_does_not_convert_compound_assignment_to_simple_assignment(self):
        source = 'class Operators{void apply(int incoming){int bits=1;bits >>>= incoming;}}'
        result, _ = typed_extract(source)
        row, = assignments(result)
        self.assertEqual(row['assignmentOperator'], '>>>=')
        self.assertEqual(row['assignmentSemantics']['binaryOperator'], '>>>')
        self.assertEqual(row['assignmentSemantics']['resultConversion'], 'to_left_hand_variable_type')
        self.assertEqual(row['assignmentSemantics']['execution'], 'not_observed')
        self.assertFalse(result['coverage']['businessPolicyComplete'])

    def test_enhanced_loop_retains_compound_accumulator_relation(self):
        source = 'class Operators{int apply(int[] values){int bits=0;for(int item:values){bits |= item;}return bits;}}'
        row, = assignments(extract(source))
        relations = row.get('loopRelations', [])
        self.assertTrue(any(r.get('selfRead') == 'compound_assignment' for r in relations))
        self.assertTrue(all(r.get('recurrenceValue') == 'UNKNOWN' for r in relations if 'recurrenceValue' in r))

    def test_semantic_inventory_remains_reconciled_when_targets_fail(self):
        result = extract('class Operators{void apply(int next){int bits=0;bits |= next;bits + = next;}}')
        coverage = result['coverage']
        self.assertEqual(coverage['recordedFragments'], len(result['fragments']))
        self.assertEqual(sum(coverage[key] for key in ('representedFragments', 'partialFragments', 'unsupportedFragments')),
                         coverage['recordedFragments'])
        self.assertEqual(coverage['wholePolicyDenominator'], 'UNKNOWN')
        self.assertFalse(coverage['businessPolicyComplete'])


if __name__ == '__main__':
    unittest.main()
