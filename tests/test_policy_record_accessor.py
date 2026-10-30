"""Source record component types, independent from Java call exactness counts."""
import copy
import hashlib
import json
import unittest

from test_policy_java_contracts import extract, returns, bindings, core, pipeline_java, policy_semantics, pipeline_delivery
from test_policy_literal_review import walk


class RecordAccessorTypeTests(unittest.TestCase):
    def test_implicit_component_type_enables_arithmetic_without_call_promotion(self):
        source='record Funds(java.math.BigDecimal cash) {} class Rules {Object f(Funds funds){return funds.cash().multiply(java.math.BigDecimal.valueOf(2));}}'
        digest=hashlib.sha256(source.encode()).hexdigest()
        index=core.build_java_index({'Rules.java':source})
        before=copy.deepcopy(index.calls)
        method_ids=set(index.methods)
        facts={'path':'Rules.java','sourceDigest':digest,'module':'synthetic','modulePath':'.','records':[]}
        pipeline_java.enrich(facts,index)
        result=policy_semantics.extract_semantics(source,'Java','Rules.java',digest,java_type_context=pipeline_java.semantic_type_context(facts,index))
        row=returns(result)[0]
        self.assertEqual({contract['method'] for _,contract in bindings(row)},{'multiply','valueOf'})
        accessor=row['expression']['callee']['receiver']['staticAccessorBinding']
        self.assertEqual(accessor['signature'],'Funds#cash():java.math.BigDecimal')
        self.assertEqual(accessor['runtimeValue'],'UNKNOWN')
        self.assertEqual(accessor['callResolution'],'java_index_unchanged')
        self.assertEqual(index.calls,before);self.assertEqual(set(index.methods),method_ids)
        self.assertEqual(next(c for c in index.calls['Rules.java'] if c['name']=='cash')['resolution'],'unresolved')
        self.assertTrue(set(accessor['sourceEvidenceIds'])<={r['id'] for r in facts['records'] if r['kind']=='symbol'})
        span=accessor['component']['sourceRange']
        self.assertEqual(source[span['charStart']:span['charEnd']],'java.math.BigDecimal cash')

    def test_public_cross_file_record_and_qualified_type_are_exact(self):
        other={'Funds.java':'package ledger; public record Funds(java.math.BigDecimal cash) {}'}
        for typename, prefix in [('Funds','import ledger.Funds;'),('ledger.Funds','')]:
            result,_=extract(prefix+' class Rules {Object f('+typename+' funds){return funds.cash().abs();}}',other)
            self.assertEqual(bindings(returns(result)[0])[0][1]['method'],'abs')

    def test_nested_record_component_chain_retains_both_declarations(self):
        source='record Funds(java.math.BigDecimal cash) {} record Envelope(Funds funds) {} class Rules {Object f(Envelope value){return value.funds().cash().abs();}}'
        result,_=extract(source)
        row=returns(result)[0]
        self.assertEqual(len([node for node in walk(row) if 'staticAccessorBinding' in node]),2)
        self.assertEqual(bindings(row)[0][1]['method'],'abs')

    def test_exact_factory_return_record_can_feed_implicit_accessor(self):
        source='record Funds(java.math.BigDecimal cash) {} class Rules {Funds factory(){return null;} Object f(){return factory().cash().abs();}}'
        result,_=extract(source)
        row=returns(result)[-1]
        self.assertEqual(bindings(row)[0][1]['method'],'abs')
        self.assertTrue(any(node.get('staticType',{}).get('evidenceKinds')==['callsite','symbol'] for node in walk(row)))

    def test_explicit_accessor_return_declaration_has_priority(self):
        source='record Funds(java.math.BigDecimal cash) {public java.math.BigDecimal cash(){return java.math.BigDecimal.ZERO;}} class Rules {Object f(Funds funds){return funds.cash().abs();}}'
        result,_=extract(source)
        row=returns(result)[-1]
        self.assertEqual(bindings(row)[0][1]['method'],'abs')
        self.assertFalse(any('staticAccessorBinding' in node for node in walk(row)))
        getter=row['expression']['callee']['receiver']
        self.assertEqual(getter['staticType']['basis'],'exact_source_call_return_declaration')
        self.assertNotIn('component',getter)

    def test_same_name_nonzero_overload_does_not_replace_implicit_zero_arg(self):
        source='record Funds(java.math.BigDecimal cash) {public String cash(int ignored){return null;}} class Rules {Object f(Funds funds){return funds.cash().abs();}}'
        result,_=extract(source)
        self.assertEqual(bindings(returns(result)[-1])[0][1]['method'],'abs')
        self.assertTrue(any('staticAccessorBinding' in node for node in walk(returns(result)[-1])))

    def test_wrong_arity_or_wrong_component_name_do_not_gain_type(self):
        for expr in ('funds.cash(1).abs()','funds.other().abs()'):
            result,_=extract('record Funds(java.math.BigDecimal cash) {} class Rules {Object f(Funds funds){return '+expr+';}}')
            self.assertEqual(bindings(returns(result)[0]),[])

    def test_generic_local_array_and_duplicate_components_are_unknown(self):
        sources=[
            'record Funds<T>(T cash) {} class Rules {Object f(Funds<java.math.BigDecimal> funds){return funds.cash().abs();}}',
            'class Rules {Object f(){record Funds(java.math.BigDecimal cash) {} Funds funds=null;return funds.cash().abs();}}',
            'record Funds(java.math.BigDecimal cash) {} class Rules {Object f(Funds[] funds){return funds.cash().abs();}}',
            'record Funds(java.math.BigDecimal cash,java.math.BigDecimal cash) {} class Rules {Object f(Funds funds){return funds.cash().abs();}}',
            'record Funds(java.math.BigDecimal hashCode) {} class Rules {Object f(Funds funds){return funds.hashCode().abs();}}',
        ]
        for source in sources:
            with self.subTest(source=source):
                result,_=extract(source)
                self.assertFalse(any(bindings(row) for row in returns(result)))

    def test_custom_class_and_unknown_record_import_do_not_use_field_guess(self):
        sources=['class Funds {java.math.BigDecimal cash;} class Rules {Object f(Funds funds){return funds.cash().abs();}}',
                 'import missing.Funds; class Rules {Object f(Funds funds){return funds.cash().abs();}}']
        for source in sources:
            self.assertFalse(any(bindings(row) for row in returns(extract(source)[0])))

    def test_inaccessible_nested_and_package_record_types_stay_unknown(self):
        cases=[
            ('class Owner {private record Funds(java.math.BigDecimal cash) {}} class Rules {Object f(Owner.Funds funds){return funds.cash().abs();}}',None),
            ('import ledger.Funds; class Rules {Object f(Funds funds){return funds.cash().abs();}}',{'Funds.java':'package ledger; record Funds(java.math.BigDecimal cash) {}'}),
            ('import ledger.Owner.Funds; class Rules {Object f(Funds funds){return funds.cash().abs();}}',{'Owner.java':'package ledger; public class Owner {private record Funds(java.math.BigDecimal cash) {}}'}),
        ]
        for source, others in cases:
            self.assertFalse(any(bindings(row) for row in returns(extract(source,others)[0])))

    def test_member_private_record_is_accessible_within_its_own_nest(self):
        source='class Rules {private record Funds(java.math.BigDecimal cash) {} Object f(Funds funds){return funds.cash().abs();}}'
        self.assertEqual(bindings(returns(extract(source)[0])[0])[0][1]['method'],'abs')

    def test_record_and_component_type_shadowing_remain_unknown(self):
        cases=[
            ('import ledger.Funds; class Rules {class Funds {} Object f(Funds funds){return funds.cash().abs();}}',{'Funds.java':'package ledger; public record Funds(java.math.BigDecimal cash) {}'}),
            ('record Funds(java.math.BigDecimal cash) {} class Rules {<Funds> Object f(Funds funds){return funds.cash().abs();}}',None),
            ('import java.math.BigDecimal; record Funds(BigDecimal cash) {static class BigDecimal {}} class Rules {Object f(Funds funds){return funds.cash().abs();}}',None),
            ('record Funds(java.math.BigDecimal cash) {} class Rules {Object f(Object x,Funds funds){if(x instanceof Fake funds){return funds.cash().abs();}return null;}}',None),
            ('record Funds(java.math.BigDecimal cash) {} class Rules {Funds funds; Object f(){return stream.map(funds->funds.cash().abs());}}',None),
        ]
        for source, others in cases:
            self.assertFalse(any(bindings(row) for row in returns(extract(source,others)[0])))

    def test_array_components_never_gain_scalar_numeric_contract(self):
        source='record Funds(java.math.BigDecimal[] cash) {} class Rules {Object f(Funds funds){return funds.cash().abs();}}'
        row=returns(extract(source)[0])[0]
        self.assertEqual(bindings(row),[])
        getter=row['expression']['callee']['receiver']
        self.assertEqual(getter['staticType']['name'],'java.math.BigDecimal[]')

    def test_abstract_unrelated_methods_do_not_break_record_context(self):
        source='interface Marker {Object other();} record Funds(java.math.BigDecimal cash) {} abstract class Rules {abstract Object other();Object f(Funds funds){return funds.cash().abs();}}'
        self.assertEqual(bindings(returns(extract(source)[0])[0])[0][1]['method'],'abs')

    def test_duplicate_source_types_are_rejected_by_existing_index(self):
        with self.assertRaises(core.DuplicateDeclarationError):
            extract('record Funds(java.math.BigDecimal cash) {} class Rules {}',{'Other.java':'record Funds(String cash) {}'})

    def test_bounded_accessor_chain_preserves_delivery_budget(self):
        declarations='record R0(java.math.BigDecimal cash) {} '+''.join('record R%d(R%d link) {} '%(i,i-1) for i in range(1,13))
        source=declarations+'class Rules {Object f(R12 value){return value'+'.link()'*12+'.cash().abs();}}'
        row=returns(extract(source)[0])[0]
        self.assertEqual(len([node for node in walk(row) if 'staticAccessorBinding' in node]),13)
        self.assertEqual(bindings(row)[0][1]['method'],'abs')
        delivered=pipeline_delivery.normalize_response({'records':[row]})
        self.assertLess(len(json.dumps(delivered).encode()),256*1024)
        self.assertFalse(row['businessMeaningVerified'])

    def test_component_package_access_is_checked_at_chain_call_site(self):
        declarations={'Envelope.java':'package ledger; public record Envelope(Hidden hidden) {} record Hidden(java.math.BigDecimal cash) {}'}
        source='import ledger.Envelope; class Rules {Object f(Envelope value){return value.hidden().cash().abs();}}'
        row=returns(extract(source,declarations)[0])[-1]
        self.assertEqual(bindings(row),[])
        self.assertFalse(any(node.get('staticType',{}).get('name')=='ledger.Hidden' for node in walk(row)))
        same_package='package ledger; class Rules {Object f(Envelope value){return value.hidden().cash().abs();}}'
        self.assertEqual(bindings(returns(extract(same_package,declarations)[0])[-1])[0][1]['method'],'abs')

    def test_private_component_type_is_not_accessible_to_other_nest(self):
        declarations={'Envelope.java':'package ledger; public record Envelope(Envelope.Hidden hidden) {private record Hidden(java.math.BigDecimal cash) {}}'}
        for prefix in ('import ledger.Envelope;','package ledger;'):
            source=prefix+' class Rules {Object f(Envelope value){return value.hidden().cash().abs();}}'
            row=returns(extract(source,declarations)[0])[-1]
            self.assertEqual(bindings(row),[])
            self.assertFalse(any(node.get('staticType',{}).get('name')=='ledger.Envelope.Hidden' for node in walk(row)))

    def test_exact_factory_result_checks_caller_access_before_type_bridge(self):
        declarations=[
            'package ledger; public class Factory {public static Hidden create(){return null;}} record Hidden(java.math.BigDecimal cash) {}',
            'package ledger; public class Factory {public static Hidden create(){return null;} private record Hidden(java.math.BigDecimal cash) {}}',
        ]
        source='import ledger.Factory; class Rules {Object f(){return Factory.create().cash().abs();}}'
        for declaration in declarations:
            row=returns(extract(source,{'Factory.java':declaration})[0])[-1]
            self.assertEqual(bindings(row),[])
            self.assertFalse(any(node.get('staticType',{}).get('basis')=='exact_source_call_return_declaration' for node in walk(row)))

    def test_public_component_and_factory_result_keep_cross_package_access(self):
        declarations={'Envelope.java':'package ledger; public record Envelope(Hidden hidden) {}',
                      'Hidden.java':'package ledger; public record Hidden(java.math.BigDecimal cash) {}',
                      'Factory.java':'package ledger; public class Factory {public static Hidden create(){return null;}}'}
        for method in ('Object f(ledger.Envelope value){return value.hidden().cash().abs();}',
                       'Object f(){return ledger.Factory.create().cash().abs();}'):
            self.assertEqual(bindings(returns(extract('class Rules {'+method+'}',declarations)[0])[-1])[0][1]['method'],'abs')

    def test_explicit_accessor_does_not_bypass_inaccessible_receiver_type(self):
        declarations={'Factory.java':'package ledger; public class Factory {public static Hidden create(){return null;}} record Hidden(java.math.BigDecimal cash) {public java.math.BigDecimal cash(){return java.math.BigDecimal.ZERO;}}'}
        source='import ledger.Factory; class Rules {Object f(){return Factory.create().cash().abs();}}'
        self.assertEqual(bindings(returns(extract(source,declarations)[0])[-1]),[])

    def test_sensitive_accessor_never_receives_return_type_or_arithmetic(self):
        source='record Funds(java.math.BigDecimal secretCash) {} class Rules {Object f(Funds funds){return funds.secretCash().abs();}}'
        row=returns(extract(source)[0])[0]
        self.assertTrue(row['structuralOnly'])
        self.assertFalse(any('staticAccessorBinding' in node or 'staticType' in node for node in walk(row)))


if __name__=='__main__': unittest.main()
