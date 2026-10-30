"""Annotation privacy context crosses complete balanced declaration prefixes."""
import json
import unittest

from test_policy_c5_syntax_review import extract_reviewed
from test_policy_literal_review import reviewed, occurrence, walk
import policy_semantics


class AnnotationContextTests(unittest.TestCase):
    def check_hidden(self, source, *, with_index=True):
        if with_index:
            result, review, _ = extract_reviewed(source, ['"HIDDEN_SENTINEL"'])
        else:
            review, digest = reviewed(source, [occurrence(source, '"HIDDEN_SENTINEL"')])
            result = policy_semantics.extract_semantics(source, 'Java', 'Rules.java', digest, literal_review=review)
        self.assertNotIn('HIDDEN_SENTINEL', json.dumps(result))
        self.assertEqual(review.summary()['admittedEntries'], 0)
        self.assertEqual(review.summary()['rejectedEntries'], 1)
        rows = [r for r in result['fragments'] if r['category'] == 'annotation_argument'
                and any(node.get('op') in {'masked_value', 'redacted'} for node in walk(r))]
        self.assertTrue(rows)
        self.assertTrue(all(r.get('structuralOnly') for r in rows))
        self.assertFalse(any('staticContract' in node or 'staticType' in node for row in rows for node in walk(row)))
        return result

    def test_following_annotations_do_not_end_sensitive_method_context(self):
        for suffix in ('@Other(flag=true)', '@Other(flags={true,false})',
                       '@Other(value=@Inner(flag=true))', '<@Other(flag=true) T>',
                       '@Other(flag=true) @Third(flags={true,false})'):
            for with_index in (True, False):
                with self.subTest(suffix=suffix, with_index=with_index):
                    self.check_hidden('class Rules {@Meta("HIDDEN_SENTINEL") '+suffix+' void getSecret(){}}', with_index=with_index)

    def test_following_annotations_do_not_end_sensitive_type_context(self):
        for suffix in ('@Other(flag=true)', '@Other(flags={true,false})', '@Other(value=@Inner(flag=true))'):
            for with_index in (True, False):
                self.check_hidden('@Meta("HIDDEN_SENTINEL") '+suffix+' class SecretHolder {}', with_index=with_index)

    def test_nested_annotation_array_inherits_sensitive_declaration(self):
        for source in ('@Meta({@Inner("HIDDEN_SENTINEL")}) class SecretHolder {}',
                       'class Rules {@Meta({@Inner("HIDDEN_SENTINEL")}) void getSecret(){}}',
                       'class Rules {@Outer(value=@Meta({@Inner("HIDDEN_SENTINEL")})) void getSecret(){}}'):
            for with_index in (True, False):
                with self.subTest(source=source, with_index=with_index):
                    self.check_hidden(source, with_index=with_index)

    def test_parameter_and_type_parameter_annotations_keep_sensitive_owner(self):
        for source in ('class Rules {void getSecret(@Meta("HIDDEN_SENTINEL") @Other(flag=true) String value){}}',
                       'class Rules {<@Meta("HIDDEN_SENTINEL") @Other(flag=true) T> void getSecret(){}}',
                       'class SecretHolder<@Meta("HIDDEN_SENTINEL") @Other(flag=true) T> {}'):
            for with_index in (True, False):
                with self.subTest(source=source, with_index=with_index):
                    self.check_hidden(source, with_index=with_index)

    def test_unknown_target_retains_sensitive_field_context(self):
        result = self.check_hidden('class Rules {@Meta("HIDDEN_SENTINEL") @Other(flag=true) String secretField;}')
        self.assertTrue(any(r.get('annotation', {}).get('target', {}).get('resolution') == 'UNKNOWN' for r in result['fragments']))

    def test_balanced_prefix_does_not_capture_next_sensitive_declaration(self):
        source='class Rules {@Meta("VISIBLE") @Other(flag=true) void ordinary(){} void getSecret(){}}'
        result, review, _=extract_reviewed(source,['"VISIBLE"'])
        self.assertEqual(review.summary()['admittedEntries'],1)
        self.assertTrue(any(node.get('value') == 'VISIBLE' for node in walk(result)))

    def test_exact_empty_marker_allowed_without_annotation_type_enrichment(self):
        source='class Rules {@Meta("") @Other(flag=true) void getSecret(){}}'
        result, review, _=extract_reviewed(source,['""'])
        self.assertEqual(review.summary()['admittedEntries'],1)
        row=next(r for r in result['fragments'] if r['category']=='annotation_argument')
        self.assertTrue(row['structuralOnly'])
        self.assertEqual(row['expression']['value'],'')
        self.assertTrue(row['expression']['literalReview']['emptySensitiveMarker'])
        self.assertFalse(any('staticType' in node or 'staticContract' in node for node in walk(row)))


if __name__ == '__main__': unittest.main()
