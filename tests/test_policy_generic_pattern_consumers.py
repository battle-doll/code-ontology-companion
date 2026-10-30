"""Syntax-only generic patterns survive transport without becoming meaning."""
import copy
import hashlib
import json
import unittest

from test_policy_generic_patterns import extract, walk
from test_pipeline_delivery import restore
import pipeline_delivery as delivery
import pipeline_html as view
import pipeline_policy as policy


class GenericPatternConsumerTests(unittest.TestCase):
    def source(self):
        return 'class Rules{boolean eligible(Object item){return !(item instanceof java.util.Map<?,?> matched);}}'

    def fragment(self):
        return next(f for f in extract(self.source())[0]['fragments'] if f['category']=='return')

    def test_delivery_and_raw_json_keep_required_syntax_and_unknown_fields(self):
        row={**self.fragment(),'kind':'semantic_fragment'}
        response={'status':'ok','snapshotId':'ps-neutral','data':{'records':[row]}}
        projected=delivery.normalize_response(response)
        delivered=projected['data']['records'][0]
        expression=delivered['expression']
        if expression.get('format')=='companion.flat-json.v1':expression=restore(expression)
        self.assertEqual(expression,row['expression'])
        for field in set(row)-{'expression'}:self.assertEqual(delivered[field],row[field])
        raw,_=view._raw_page([row],'ps-neutral')
        self.assertEqual(json.loads(raw)['records'],[row])
        self.assertIn('instanceof_runtime_unresolved',delivered['unsupportedReasons'])
        self.assertFalse(delivered['businessMeaningVerified'])

    def test_generic_type_syntax_never_supplies_pattern_receiver_type_or_contract(self):
        row=self.fragment()
        types=[node for node in walk(row['expression']) if node.get('op')=='type_reference']
        self.assertEqual(len(types),1)
        self.assertEqual(types[0]['syntaxVersion'],'java.instanceof.type.v1')
        pattern=row['expression']['operand']['right']
        self.assertFalse(any('staticType' in n or 'staticContract' in n for n in walk(pattern)))
        # The explicitly declared subject may keep its independent Object
        # proof; that is not a type learned from a successful pattern match.
        self.assertEqual(row['expression']['operand']['left']['staticType']['name'],'java.lang.Object')
        self.assertFalse(row.get('standardApiContracts'))
        self.assertEqual(row['runtimeStatus'],'not_observed')
        self.assertEqual(row['representationStatus'],'partial')

    def test_raw_source_common_rule_reader_explicitly_keeps_unknown(self):
        source=self.source()
        result=policy.extract_policy_rules(source,'Java','Rules.java',hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(result['rules'],[])
        self.assertEqual(result['coverage']['detectedRules'],1)
        self.assertEqual(result['coverage']['unsupportedRules'],1)
        self.assertFalse(result['coverage']['complete'])
        self.assertFalse(result['coverage']['businessPolicyComplete'])
        self.assertTrue(result['coverage']['reasons'])


if __name__=='__main__':unittest.main()
