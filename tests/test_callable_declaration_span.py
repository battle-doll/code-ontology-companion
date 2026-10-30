"""Lexical callable and full declaration positions retain separate meanings."""
import unittest
from test_policy_java_contracts import extract


class CallableDeclarationSpanTests(unittest.TestCase):
    def test_annotations_headers_and_body_use_actual_independent_ranges(self):
        sources = [
            'class Example {\n @Deprecated\n int f() {\n return 1;\n }\n}',
            'class Example {\r\n // 한글 😀\r\n @Deprecated\r\n public int f(\r\n int value\r\n ) {return value;}\r\n}',
            'class Example {\n int f() {return 1;}\n}',
        ]
        for source in sources:
            facts, _ = extract(source)
            owners = [fragment.get('controlFlow', {}).get('owner') for fragment in facts['fragments']]
            owners = [owner for owner in owners if owner and owner.get('resolution') == 'source_callable_definition']
            self.assertTrue(owners)
            for owner in owners:
                bounds = owner['sourceRange']
                start = source.count('\n', 0, bounds['charStart']) + 1
                end = source.count('\n', 0, max(bounds['charStart'], bounds['charEnd'] - 1)) + 1
                self.assertEqual(owner['declarationSpan'], {'lineStart': start, 'lineEnd': end})
                self.assertIn('span', owner)
                self.assertLessEqual(start, owner['span']['lineStart'])
                self.assertGreaterEqual(end, owner['span']['lineEnd'])

    def test_unresolved_lexical_owner_does_not_invent_a_declaration_span(self):
        facts, _ = extract('class Example { @Deprecated Example(){int value=1;} Object f(){return values.map(value -> value);} }')
        for fragment in facts['fragments']:
            owner = fragment.get('controlFlow', {}).get('owner')
            if owner and owner.get('resolution') == 'lexical_callable_only':
                self.assertNotIn('declarationSpan', owner)


if __name__ == '__main__':
    unittest.main()
