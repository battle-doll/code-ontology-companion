"""Generic synthetic annotation, array, review and privacy boundary regressions."""
import hashlib
import json
import unittest
from unittest import mock

from test_policy_literal_review import reviewed, occurrence, walk
from test_policy_java_contracts import core, pipeline_java, pipeline_delivery
import policy_semantics
import privacy_guard


def extract_reviewed(source, quoted=(), *, profile=None, max_fragments=policy_semantics.MAX_FRAGMENTS):
    review, digest = reviewed(source, [occurrence(source, token) for token in quoted], profile=profile)
    facts = {"path":"Rules.java","sourceDigest":digest,"module":"synthetic","modulePath":".","records":[]}
    index = core.build_java_index({"Rules.java":source})
    pipeline_java.enrich(facts, index)
    result = policy_semantics.extract_semantics(source, 'Java', 'Rules.java', digest,
        java_type_context=pipeline_java.semantic_type_context(facts,index), literal_review=review, max_fragments=max_fragments)
    return result, review, facts


class UnifiedReviewedSyntaxTests(unittest.TestCase):
    def test_statement_switch_label_uses_exact_occurrence_review(self):
        source='class Rules { int f(String x){switch(x){case "READY":return 1;default:return 0;}}}'
        result, review, _=extract_reviewed(source,['"READY"'])
        labels=[node for node in walk(result) if node.get('op')=='switch_labels']
        self.assertEqual(labels[0]['labels'][0]['value'],'READY')
        self.assertEqual(review.summary()['admittedEntries'],1)
        self.assertEqual(result['coverage']['literalReviewDelivery']['retainedOccurrences'],1)
        self.assertIn('literalReview',labels[0]['labels'][0])

    def test_for_clause_cannot_bypass_empty_review_with_numeric_string(self):
        source='import java.math.BigDecimal; class Rules { void f(BigDecimal x){for(;x.compareTo(new BigDecimal("0.5"))<0;){break;}}}'
        result, review, _=extract_reviewed(source)
        self.assertNotIn('0.5',json.dumps(result))
        self.assertFalse(any(node.get('binding')=='java.math.BigDecimal.String' for node in walk(result)))
        self.assertEqual(review.summary()['admittedEntries'],0)
        reviewed_result, review, _=extract_reviewed(source,['"0.5"'])
        self.assertEqual(review.summary()['admittedEntries'],1)
        self.assertEqual(reviewed_result['coverage']['literalReviewDelivery']['retainedOccurrences'],1)
        constructor=next(node for node in walk(reviewed_result) if node.get('op')=='construct')
        self.assertEqual(constructor['staticConstructorBinding']['signature'],'java.math.BigDecimal#<init>(java.lang.String)')
        self.assertEqual(constructor['staticConstructorBinding']['executionSuccess'],'UNKNOWN')

    def test_sensitive_for_and_switch_still_block_nonempty_review(self):
        source='class Rules {void f(String secretMode){for(;secretMode.equals("HIDDEN");){switch(secretMode){case "READY":break;default:break;}}}}'
        result, review, _=extract_reviewed(source,['"HIDDEN"','"READY"'])
        self.assertEqual(review.summary()['rejectedEntries'],2)
        self.assertNotIn('HIDDEN',json.dumps(result)); self.assertNotIn('READY',json.dumps(result))
        self.assertFalse(any('staticContract' in node for node in walk(result)))

    def test_declared_object_array_retains_every_reviewed_constructor_argument(self):
        source='class Rules {private static final Band[] BANDS={new Band("1.5","0.1"),new Band("2.5","0.2")};}'
        result, review, _=extract_reviewed(source,['"1.5"','"0.1"','"2.5"','"0.2"'])
        array=result['fragments'][0]['expression']
        self.assertEqual(array['op'],'array_initializer')
        self.assertEqual([node['type'] for node in array['elements']],['Band','Band'])
        self.assertEqual([arg['value'] for node in array['elements'] for arg in node['arguments']],['1.5','0.1','2.5','0.2'])
        self.assertEqual(review.summary()['admittedEntries'],4)
        self.assertEqual(result['coverage']['literalReviewDelivery']['retainedOccurrences'],4)
        self.assertFalse(result['coverage']['semanticComplete'])

    def test_nested_and_trailing_comma_arrays_keep_order_and_default_masking(self):
        source='class Rules {Object[][] values={{new Band("MODE"),},{},};}'
        result, review, _=extract_reviewed(source,['"MODE"'])
        expr=result['fragments'][0]['expression']
        self.assertEqual(expr['op'],'array_initializer')
        self.assertEqual(len(expr['elements']),2)
        self.assertEqual(expr['elements'][1]['elements'],[])
        self.assertEqual(result['coverage']['literalReviewDelivery']['retainedOccurrences'],1)
        hidden, _, _=extract_reviewed(source)
        self.assertNotIn('MODE',json.dumps(hidden))

    def test_sensitive_array_keeps_shape_but_no_reviewed_values(self):
        source='class Rules {Object[] secretArray={new Band("MODE",88366127),};}'
        result, review, _=extract_reviewed(source,['"MODE"'])
        self.assertEqual(result['fragments'][0]['expression']['op'],'array_initializer')
        self.assertTrue(result['fragments'][0]['structuralOnly'])
        self.assertNotIn('MODE',json.dumps(result)); self.assertNotIn('88366127',json.dumps(result))
        self.assertEqual(review.summary()['rejectedEntries'],1)

    def test_array_depth_budget_and_fragment_inventory_remain_explicit(self):
        source='class Rules {Object[][] values='+('{'*40)+'null'+('}'*40)+';}'
        result, _, _=extract_reviewed(source)
        self.assertIn('expression_depth_exceeded',result['fragments'][0]['unsupportedReasons'])
        source='class Rules {Object[] first={new Band("A")}; Object[] second={new Band("B")};}'
        result, review, _=extract_reviewed(source,['"A"','"B"'],max_fragments=1)
        self.assertFalse(result['coverage']['inventoryComplete'])
        self.assertEqual(review.summary()['notObservedEntries'],1)

    def test_delivery_is_counted_separately_from_admission(self):
        source='class Rules {Object[] values={new Band("MODE")};}'
        def discard(parser, depth):
            parser.index=len(parser.tokens)
            return {'op':'array_initializer','elements':[]}
        with mock.patch.object(policy_semantics._Expression,'array_initializer',discard):
            # A future postprocessor may discard an admitted occurrence;
            # permission must remain distinct from actual emitted content.
            result, review, _=extract_reviewed(source,['"MODE"'])
        delivery=result['coverage']['literalReviewDelivery']
        self.assertEqual(review.summary()['admittedEntries'],1)
        self.assertEqual(delivery['retainedOccurrences'],0)
        self.assertEqual(delivery['notRetainedRequestIndices'],[0])
        self.assertFalse(delivery['completeForAdmitted'])
        self.assertFalse(result['coverage']['semanticComplete'])

    def test_reviewed_empty_sensitive_marker_has_exact_proof_and_no_enrichment(self):
        source='class Rules {Object value=secretResource.read("", "HIDDEN", 88366127, true);}'
        result, review, _=extract_reviewed(source,['""','"HIDDEN"'])
        row=result['fragments'][0]
        self.assertTrue(row['structuralOnly'])
        arguments=row['expression']['arguments']
        self.assertEqual(arguments[0]['value'],'')
        self.assertTrue(arguments[0]['literalReview']['emptySensitiveMarker'])
        self.assertTrue(all(arg['op']=='masked_value' for arg in arguments[1:]))
        self.assertEqual(review.summary()['admittedEntries'],1)
        self.assertEqual(review.summary()['rejectedEntries'],1)
        self.assertFalse(any('staticType' in node or 'staticContract' in node for node in walk(row)))

    def test_empty_review_does_not_propagate_to_other_occurrence(self):
        source='class Rules {Object value=secretResource.read("", "");}'
        result, review, _=extract_reviewed(source,['""'])
        arguments=result['fragments'][0]['expression']['arguments']
        self.assertEqual(arguments[0]['value'],'')
        self.assertEqual(arguments[1]['op'],'masked_value')
        self.assertNotEqual(arguments[0]['opaqueOccurrenceId'],arguments[1]['opaqueOccurrenceId'])
        no_review, _, _=extract_reviewed(source)
        self.assertFalse(any(node.get('op')=='literal' and node.get('type')=='string' for node in walk(no_review)))

    def test_nonempty_whitespace_zero_width_and_escape_never_use_empty_exception(self):
        for quoted in ('" "','"\\0"','"\\n"','"\u200b"'):
            source='class Rules {Object value=secretResource.read('+quoted+');}'
            result, review, _=extract_reviewed(source,[quoted])
            self.assertEqual(review.summary()['admittedEntries'],0)
            self.assertFalse(any(node.get('op')=='literal' and node.get('type')=='string' for node in walk(result)))

    def test_empty_marker_keeps_profile_and_unknown_context_veto(self):
        source='class Rules {Object value=secretResource.read("");}'
        review,digest=reviewed(source,[occurrence(source,'""')])
        bound=review.bind_source('Rules.java',source,digest)
        left,right=occurrence(source,'""')
        self.assertEqual(bound.admit(left,right,sensitive_context=None,allow_reviewed_empty=True)['status'],'rejected')
        review,digest=reviewed(source,[occurrence(source,'""')])
        with mock.patch.object(review,'_guard',side_effect=privacy_guard.PrivacyError('blocked')):
            result=policy_semantics.extract_semantics(source,'Java','Rules.java',digest,literal_review=review)
        self.assertFalse(any(node.get('op')=='literal' and node.get('type')=='string' for node in walk(result)))
        self.assertEqual(review.summary()['rejectedEntries'],1)

    def test_empty_marker_inherited_sensitive_callback_is_still_source_only(self):
        source='class Rules {Runnable secretCallback=()->{consume("");};}'
        result, review, _=extract_reviewed(source,['""'])
        nodes=[node for node in walk(result) if node.get('op')=='literal' and node.get('type')=='string']
        self.assertEqual(len(nodes),1); self.assertEqual(nodes[0]['value'],'')
        self.assertEqual(review.summary()['admittedEntries'],1)
        self.assertFalse(any('staticContract' in node for node in walk(result)))

    def test_annotation_scalar_array_and_target_provenance(self):
        source='package sample; import example.Route; @Route("/base") class Rules { @Route(path="/items",produces={"A","B"}) String f(){return null;} }'
        result, review, facts=extract_reviewed(source,['"/base"','"/items"','"A"','"B"'])
        rows=[r for r in result['fragments'] if r['category']=='annotation_argument']
        self.assertEqual([r['annotation']['argumentKey'] for r in rows],['value','path','produces'])
        self.assertEqual([r['annotation']['target']['kind'] for r in rows],['class','method','method'])
        symbol_ids={r['id'] for r in facts['records'] if r['kind']=='symbol'}
        for row in rows:
            self.assertTrue(set(row['annotation']['target']['sourceEvidenceIds'])<=symbol_ids)
            self.assertEqual(row['annotation']['typeBinding']['name'],'example.Route')
            self.assertEqual(row['annotation']['runtimeMeaning'],'UNKNOWN')
            self.assertFalse(row['businessMeaningVerified'])
        self.assertEqual(rows[2]['expression']['op'],'annotation_array')
        self.assertEqual(result['coverage']['literalReviewDelivery']['retainedOccurrences'],4)
        self.assertLess(len(json.dumps(pipeline_delivery.normalize_response({'records':rows})).encode()),256*1024)

    def test_annotation_utf8_ranges_and_unproven_parameter_target(self):
        source='/* 한글 */ class Rules { void f(@Named("준비") String value){} }'
        result, review, _=extract_reviewed(source,['"준비"'])
        row=next(r for r in result['fragments'] if r['category']=='annotation_argument')
        self.assertEqual(row['annotation']['target']['resolution'],'UNKNOWN')
        value_range=row['annotation']['argumentRange']
        self.assertEqual(source.encode()[value_range['byteStart']:value_range['byteEnd']].decode(),'"준비"')
        self.assertNotEqual(value_range['byteStart'],value_range['charStart'])

    def test_nested_annotation_remains_explicitly_unsupported_at_outer_value(self):
        source='@Outer(@Inner("MODE")) class Rules {}'
        result, review, _=extract_reviewed(source,['"MODE"'])
        rows=[r for r in result['fragments'] if r['category']=='annotation_argument']
        self.assertIn('nested_annotation_value_unsupported',rows[0]['unsupportedReasons'])
        self.assertEqual(rows[1]['annotation']['target']['reason'],'nested_annotation_target')
        self.assertEqual(rows[1]['expression']['value'],'MODE')

    def test_sensitive_annotation_array_and_target_block_nonempty_values(self):
        for source in ('@SecretMeta({"MODE"}) class Rules {}','class Rules { @Meta("MODE") void getSecret(){} }'):
            result, review, _=extract_reviewed(source,['"MODE"'])
            self.assertNotIn('MODE',json.dumps(result))
            self.assertEqual(review.summary()['rejectedEntries'],1)
            self.assertTrue(next(r for r in result['fragments'] if r['category']=='annotation_argument')['structuralOnly'])


if __name__=='__main__': unittest.main()
