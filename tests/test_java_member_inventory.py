"""Independent neutral direct-member inventory and fail-closed boundaries."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from test_policy_java_contracts import core, extract, pipeline_java, returns, bindings
from test_policy_literal_review import walk
from test_policy_dependency_closure import analyzed_files, finish

platform = pipeline_java.policy_java_platform
BD = 'import java.math.BigDecimal;'


def last(source, others=None):
    return returns(extract(source, others)[0])[-1]


def constants(fragment):
    return [node for node in walk(fragment.get('expression')) if isinstance(node, dict) and 'standardConstant' in node]


class JavaMemberInventoryTests(unittest.TestCase):
    def test_multifield_duration_math_chain_has_complete_source_proof_without_calls(self):
        source = ('import java.time.Duration; abstract class Sample implements AutoCloseable {'
                  'Object left, right; Duration bound(Duration interval,long limit) {'
                  'return Duration.ofNanos(Math.min(interval.toNanos(),limit));}}')
        result, facts = extract(source); fragment = returns(result)[-1]
        self.assertEqual({contract['method'] for _,contract in bindings(fragment)}, {'ofNanos','min','toNanos'})
        for check in fragment['platformInheritanceChecks']:
            self.assertEqual(check['status'], 'absent')
            self.assertEqual(check['sourceScopes'][0]['memberInventory']['fieldNames'], ['left','right'])
            self.assertEqual(check['sourceScopes'][0]['sourceDigest'], hashlib.sha256(source.encode()).hexdigest())
        self.assertTrue(all(entry['actualTargetJdk'] == 'UNKNOWN' for entry in fragment['platformTypeContracts']))
        calls = [record for record in facts['records'] if record['kind'] == 'callsite']
        self.assertEqual(len(calls),3)
        self.assertTrue(all(record['resolution'] != 'exact' for record in calls))

    def test_generic_array_and_balanced_initializer_declarators_are_names_only(self):
        declarations = [
            'Object left,right;', 'Object left=null,right;',
            'Object left=(null),right=new Object(){};',
            'Object left=new Object[]{null,null},right;',
            'java.util.Map<String,java.util.List<Object>> left,right;',
            'Object[] left,right[];',
        ]
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                source = BD+'abstract class Sample implements AutoCloseable{'+declaration+'BigDecimal f(BigDecimal n){return n.abs().add(BigDecimal.ONE);}}'
                fragment=last(source)
                self.assertEqual(len(bindings(fragment)),2)
                self.assertEqual(len(constants(fragment)),1)
                self.assertTrue(all(scope['memberInventory']['fields']=='complete'
                    for check in fragment['platformInheritanceChecks'] for scope in check['sourceScopes']))

    def test_true_multifield_hiding_withdraws_each_static_qualifier(self):
        for hidden,expression in [('Math','Math.min(1,2)'),('Duration','Duration.ofNanos(1)'),('BigDecimal','BigDecimal.ONE')]:
            for declaration in ['Object first,'+hidden+';', 'Object '+hidden+',second;']:
                with self.subTest(hidden=hidden,declaration=declaration):
                    source='import java.time.Duration;'+BD+'abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return '+expression+';}}'
                    fragment=last(source)
                    self.assertFalse(bindings(fragment));self.assertFalse(constants(fragment))
                    index=core.build_java_index({'Rules.java':source})
                    inventory=platform.Inheritance(index,lambda identity:identity)
                    check,_=inventory.query('Sample',hidden,True)
                    self.assertEqual(check['status'],'present')
                    self.assertIn(hidden,check['sourceScopes'][0]['memberInventory']['fieldNames'])

    def test_record_component_field_names_are_complete_without_runtime_values(self):
        source=BD+'record Portion(BigDecimal quantity) implements AutoCloseable{public void close(){} BigDecimal f(BigDecimal factor){return quantity.multiply(factor).add(BigDecimal.ONE);}}'
        fragment=last(source)
        self.assertEqual(len(bindings(fragment)),2);self.assertEqual(len(constants(fragment)),1)
        self.assertTrue(all(scope['memberInventory']['fieldNames']==['quantity']
            for check in fragment['platformInheritanceChecks'] for scope in check['sourceScopes']))
        self.assertIn('declared_record_component_field_type',json.dumps(fragment))
        self.assertIn('"runtimeValue": "UNKNOWN"',json.dumps(fragment))

    def test_record_components_hide_static_qualifiers(self):
        for hidden,expression in [('Math','Math.min(1,2)'),('Duration','Duration.ofNanos(1)'),('BigDecimal','BigDecimal.ONE')]:
            with self.subTest(hidden=hidden):
                source='import java.time.Duration;'+BD+'record Portion(Object '+hidden+') implements AutoCloseable{public void close(){} Object f(){return '+expression+';}}'
                fragment=last(source);self.assertFalse(bindings(fragment));self.assertFalse(constants(fragment))

    def test_enum_constants_and_bodies_are_bounded_direct_field_names(self):
        for constants_text in ['ALPHA,BETA;', 'ALPHA(),BETA{};', 'ALPHA,BETA,;', ';']:
            with self.subTest(constants_text=constants_text):
                source=BD+'enum Choice implements AutoCloseable{'+constants_text+'public void close(){} BigDecimal f(BigDecimal n){return n.remainder(BigDecimal.ONE).abs();}}'
                fragment=last(source)
                self.assertEqual(len(bindings(fragment)),2);self.assertEqual(len(constants(fragment)),1)
                self.assertFalse(any(check['reasons'] for check in fragment['platformInheritanceChecks']))

    def test_enum_constants_hide_static_qualifiers(self):
        for hidden,expression in [('Math','Math.min(1,2)'),('Duration','Duration.ofNanos(1)'),('BigDecimal','BigDecimal.ONE')]:
            with self.subTest(hidden=hidden):
                source='import java.time.Duration;'+BD+'enum Choice implements AutoCloseable{'+hidden+'; public void close(){} Object f(){return '+expression+';}}'
                fragment=last(source);self.assertFalse(bindings(fragment));self.assertFalse(constants(fragment))

    def test_unparsed_annotations_and_malformed_regions_remain_unknown(self):
        for declaration in ['@Deprecated Object first,second;','Object first,;',
                            'Object first,second[;', 'java.util.Map<String,> first,second;',
                            'Object first,first;', 'Object first, class;']:
            with self.subTest(declaration=declaration):
                source=BD+'abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return BigDecimal.ONE;}}'
                result,_=extract(source)
                self.assertFalse(any(constants(fragment) for fragment in result['fragments']))
                index=core.build_java_index({'Rules.java':source})
                inventory=platform.Inheritance(index,lambda identity:identity).source_inventory('Sample')
                self.assertEqual(inventory['fields'],'UNKNOWN')

    def test_invalid_record_header_and_enum_constant_syntax_remain_unknown(self):
        for prefix in ['record Portion(void component)', 'record Portion(Object same,Object same)',
                       'enum Portion']:
            extra='@Deprecated ALPHA;' if prefix.startswith('enum') else ''
            fragment=last(BD+prefix+' implements AutoCloseable{'+extra+'public void close(){} Object f(){return BigDecimal.ONE;}}')
            self.assertFalse(constants(fragment))
            self.assertTrue(any(check['status']=='UNKNOWN' for check in fragment['platformInheritanceChecks']))

    def test_unknown_and_ambiguous_parent_imports_remain_unknown(self):
        cases=[('import java.time.*; import omitted.api.*; abstract class Sample extends Missing{Object f(Duration d){return d.minusNanos(1);}}',{}),
               (BD+'import omitted.api.*; abstract class Sample implements AutoCloseable{BigDecimal f(BigDecimal n){return n.abs();}}',{}),
               (BD+'import static omitted.Values.*; abstract class Sample implements AutoCloseable{BigDecimal f(BigDecimal n){return n.abs();}}',{}),
               (BD+'import java.lang.AutoCloseable; import omitted.AutoCloseable; abstract class Sample implements AutoCloseable{BigDecimal f(BigDecimal n){return n.abs();}}',{}),
               (BD+'import java.lang.AutoCloseable; import static omitted.Values.AutoCloseable; abstract class Sample implements AutoCloseable{BigDecimal f(BigDecimal n){return n.abs();}}',{}),
               (BD+'import chosen.*; import omitted.api.*; abstract class Sample extends Parent{BigDecimal f(BigDecimal n){return n.abs();}}',{'Parent.java':'package chosen; public abstract class Parent implements java.lang.AutoCloseable{}'})]
        for source,others in cases:
            with self.subTest(source=source):
                fragment=last(source,others);self.assertFalse(bindings(fragment))
                self.assertTrue(any(check['status']=='UNKNOWN' for check in fragment['platformInheritanceChecks']))

    def test_anchored_parent_binding_ignores_unrelated_on_demand_imports(self):
        for imports,parent in [('import static omitted.Values.*;','java.lang.AutoCloseable'),
                               ('import static omitted.Values.*; import java.lang.AutoCloseable;','AutoCloseable'),
                               ('import omitted.api.*; import java.lang.AutoCloseable;','AutoCloseable')]:
            with self.subTest(imports=imports,parent=parent):
                fragment=last(BD+imports+'abstract class Sample implements '+parent+'{BigDecimal f(BigDecimal n){return n.abs();}}')
                self.assertEqual(len(bindings(fragment)),1)

    def test_selected_static_import_parent_inventory_and_actual_hiding(self):
        template=BD+'import static selected.Types.*; abstract class Sample implements AutoCloseable{BigDecimal f(BigDecimal n){return n.abs();}}'
        for declaration,expected in [('public class Types{public static int count;}',False),
                                     ('public class Types{public static class AutoCloseable{}}',False),
                                     ('public class Types extends Missing{}',False)]:
            fragment=last(template,{'Types.java':'package selected;'+declaration})
            self.assertEqual(bool(bindings(fragment)),expected)
        selected=BD+'import selected.Parent; import omitted.api.*; abstract class Sample extends Parent{BigDecimal f(BigDecimal n){return n.abs();}}'
        fragment=last(selected,{'Parent.java':'package selected; public abstract class Parent implements java.lang.AutoCloseable{}'})
        self.assertEqual(len(bindings(fragment)),1)

    def test_exact_source_return_requires_exact_target_and_does_not_guess_overloads(self):
        source=BD+'abstract class Sample implements AutoCloseable{static BigDecimal pass(BigDecimal n){return n;} BigDecimal f(BigDecimal n,BigDecimal scale){return pass(n).multiply(scale);}}'
        result,facts=extract(source);fragment=returns(result)[-1]
        self.assertEqual(len(bindings(fragment)),1)
        call=next(record for record in facts['records'] if record['kind']=='callsite' and record['name']=='pass')
        self.assertEqual(call['resolution'],'exact')
        self.assertIn('source_return',json.dumps(fragment))
        ambiguous=source.replace('static BigDecimal pass','static BigDecimal pass(Object n){return null;} static BigDecimal pass')
        # A completely untyped argument cannot establish which source return
        # declaration supplies the standard receiver type.
        ambiguous=ambiguous.replace('pass(n).multiply','pass(missing).multiply')
        self.assertFalse(bindings(last(ambiguous)))

    def test_inventory_tamper_cannot_be_rehashed_into_a_false_absence(self):
        source=BD+'abstract class Sample implements AutoCloseable{Object first,second; Object f(){return BigDecimal.ONE;}}'
        fragment=last(source)
        for fault in ['missing','duplicate','unsorted','queried','nonstring','budget']:
            with self.subTest(fault=fault):
                item=copy.deepcopy(fragment);check=next(c for c in item['platformInheritanceChecks'] if c['namespace']=='field_or_member_type')
                inventory=check['sourceScopes'][0]['memberInventory']
                if fault=='missing': inventory.pop('fieldNames')
                elif fault=='duplicate': inventory['fieldNames']=['first','first']
                elif fault=='unsorted': inventory['fieldNames']=['second','first']
                elif fault=='queried': inventory['fieldNames']=[check['queriedName']]
                elif fault=='nonstring': inventory['fieldNames']=[1]
                else: inventory['fieldNames']=['field'+str(i) for i in range(platform.MAX_SOURCE_MEMBERS+1)]
                old_id=check['id'];check['id']='platform-lookup:'+hashlib.sha256(platform.canonical({k:v for k,v in check.items() if k!='id'})).hexdigest()[:24]
                for node in walk(item['expression']):
                    if 'platformInheritance' in node:
                        refs=node['platformInheritance']['checkIds'];node['platformInheritance']['checkIds']=[check['id'] if ref==old_id else ref for ref in refs]
                required,reason=platform.requirements(item['expression'],item)
                self.assertEqual(required,[])
                # Several checks can share this source scope. Traversal may
                # encounter either its invalid inventory or its conflicting
                # repeated definition first; both must withdraw all proof.
                self.assertIn(reason,{'platform_source_member_inventory_unverified',
                                     'platform_inheritance_definition_invalid'})

    def test_missing_source_digest_type_range_and_return_target_withdraw_contracts(self):
        source=BD+'abstract class Sample implements AutoCloseable{Object first,second; static BigDecimal pass(BigDecimal n){return n;} BigDecimal f(BigDecimal n){return pass(n).add(BigDecimal.ONE);}}'
        for fault in ['digest','type','range','target']:
            with self.subTest(fault=fault):
                results,facts=analyzed_files({'Rules.java':source})
                def change(record):
                    record=copy.deepcopy(record)
                    if record.get('qualifiedName')=='Sample':
                        if fault=='digest':record['sourceDigest']='0'*64
                        if fault=='type':record['type']='Method'
                        if fault=='range':record['declarationHeaderRange']['charEnd']-=1
                    if fault=='target' and record.get('name')=='pass' and record.get('kind')=='callsite':record['target']=None
                    return record
                finish(results,facts,change)
                fragment=returns(results['Rules.java'])[-1]
                self.assertFalse(bindings(fragment))

    def test_direct_field_and_component_inventory_budgets_fail_closed(self):
        source=BD+'abstract class Sample implements AutoCloseable{Object first,second; Object f(){return BigDecimal.ONE;}}'
        with patch.object(platform,'MAX_SOURCE_MEMBERS',1):
            fragment=last(source);self.assertFalse(constants(fragment))
            self.assertTrue(any(c['status']=='UNKNOWN' for c in fragment['platformInheritanceChecks']))
        with patch.object(platform,'MAX_SOURCE_MEMBERS',1):
            source=BD+'record Portion(Object first,Object second) implements AutoCloseable{public void close(){} Object f(){return BigDecimal.ONE;}}'
            self.assertFalse(constants(last(source)))



    def test_quoted_lambda_body_tokens_preserve_names_without_retaining_values(self):
        for expression in ('"neutral"', "'x'", '""', '"->"', 'combine("neutral",1)', 'new Box<String>("neutral")'):
            for block in (False,True):
                body='{return '+expression+';}' if block else expression
                with self.subTest(expression=expression,block=block):
                    source='class Sample{Object callback=()->'+body+',after;Object outside(){return Math.max(1,2);}}'
                    results,facts=analyzed_files({'Rules.java':source});finish(results,facts)
                    fragment=returns(results['Rules.java'])[-1]
                    self.assertEqual(len(bindings(fragment)),1)
                    owner=next(r for r in facts['Rules.java']['records'] if r.get('qualifiedName')=='Sample')
                    self.assertEqual(owner['directMemberInventory']['fields'],'complete')
                    self.assertEqual(owner['directMemberInventory']['fieldNames'],['after','callback'])
                    self.assertNotIn('neutral',json.dumps(results))

    def test_source_only_absence_cannot_use_a_rebased_donor_inventory(self):
        # The caller has no platform ancestor catalog. Its own emitted type
        # still supplies the exact bounded direct-name denominator.
        bad='class Sample{Object callback=()->{},after;Object Math;Object outside(){return Math.max(1,2);}}'
        good=bad.replace('Object Math;','Object Moth;')
        good_results,_=analyzed_files({'Rules.java':good});bad_results,bad_facts=analyzed_files({'Rules.java':bad})
        donor=returns(good_results['Rules.java'])[-1];actual=returns(bad_results['Rules.java'])[-1]
        self.assertEqual(len(bindings(donor)),1);self.assertFalse(bindings(actual))
        mapping={hashlib.sha256(good.encode()).hexdigest():hashlib.sha256(bad.encode()).hexdigest()}
        for left in good_results['Rules.java']['fragments']:
            for right in bad_results['Rules.java']['fragments']:
                if (left['category'],left['sourceRange'])==(right['category'],right['sourceRange']):mapping[left['id']]=right['id']
        def rebound(value,mapping):
            if isinstance(value,dict):return {key:rebound(child,mapping) for key,child in value.items()}
            if isinstance(value,list):return [rebound(child,mapping) for child in value]
            return mapping.get(value,value) if isinstance(value,str) else value
        for key in ('expression','standardApiContracts','platformTypeContracts','platformInheritanceChecks','platformTypeProofs'):
            if key in donor:actual[key]=rebound(copy.deepcopy(donor[key]),mapping)
        identities={}
        for check in actual.get('platformInheritanceChecks',[]):
            old=check['id'];check['id']='platform-lookup:'+hashlib.sha256(platform.canonical({key:value for key,value in check.items() if key!='id'})).hexdigest()[:24];identities[old]=check['id']
        for proof in actual.get('platformTypeProofs',[]):
            old=proof['id'];proof['id']=platform._proof_id(actual['id'],proof['consumer']);identities[old]=proof['id']
        actual.update(rebound(actual,identities));finish(bad_results,bad_facts)
        self.assertFalse(bindings(actual))
        self.assertIn('platform_source_member_inventory_unverified',actual['dependencyClosure']['reasons'])
        self.assertEqual(actual['expression']['callee']['name'],'Math.max')


class JavaMemberInventoryGrammarTests(unittest.TestCase):
    def test_malformed_declarations_never_supply_complete_inventory_or_math_binding(self):
        declarations = [
            'Object a=,b;', 'Object a=;', 'Object a=new Object() garbage,b;',
            'Object a,while;', 'java.util.List<? extends ?> a,b;', 'Object a=null b;',
            'Object a=new while(),b;', 'Object a=else,b;',
            'Object[] a=new Object[],b;', 'Object[] a=new Object[][1],b;',
            'Object[] a=new Object[1]{null},b;', 'Object a=obj.<>make(),b;',
            'Object a=new java.util.List<>[1],b;', 'Object a=(factory)(1),b;',
            "Object a='ab',b;", r"Object a='\q',b;", r'Object a="\q",b;',
            'Object a=1_,b;', 'public private Object a,b;',
            'final final Object a,b;', 'final volatile Object a,b;',
            'java.util.List<? super ? extends Other> a,b;',
            'Object a=new Object(,),b;', 'Object a=new Object(){int x=;},b;',
        ]
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                source='abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return Math.min(1,2);}}'
                index=core.build_java_index({'Rules.java':source})
                inventory=platform.Inheritance(index,lambda value:value).source_inventory('Sample')
                self.assertEqual(inventory['fields'],'UNKNOWN')
                result,_=extract(source)
                self.assertFalse(any(bindings(fragment) for fragment in result['fragments']))

    def test_nearby_supported_initializers_preserve_names_and_math_binding(self):
        declarations = [
            'Object a,b;', 'Object a=null,b;', 'Object a=(null),b=new Object(){};',
            'int a=1,b=2;', 'String a="",b="neutral";', r"char a='x',b='\n';",
            'Object a=provider(),b;', 'Object[] a=new Object[]{null,null},b;',
            'boolean a=flag?true:false,b;',
        ]
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                source='abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return Math.min(1,2);}}'
                index=core.build_java_index({'Rules.java':source})
                inventory=platform.Inheritance(index,lambda value:value).source_inventory('Sample')
                self.assertEqual(inventory['fields'],'complete')
                self.assertEqual(inventory['fieldNames'],['a','b'])
                self.assertEqual(len(bindings(last(source))),1)

    def test_malformed_record_and_enum_headers_or_arguments_remain_unknown(self):
        sources = [
            'record Portion(Object while) implements AutoCloseable{public void close(){}Object f(){return Math.min(1,2);}}',
            'record Portion(java.util.List<? extends ?> value) implements AutoCloseable{public void close(){}Object f(){return Math.min(1,2);}}',
            'enum Choice implements AutoCloseable{while;public void close(){}Object f(){return Math.min(1,2);}}',
            'enum Choice implements AutoCloseable{ALPHA(,);public void close(){}Object f(){return Math.min(1,2);}}',
            'enum Choice implements AutoCloseable{ALPHA(new Object() junk);public void close(){}Object f(){return Math.min(1,2);}}',
            'enum Choice implements AutoCloseable{ALPHA{int a=;};public void close(){}Object f(){return Math.min(1,2);}}',
        ]
        for source in sources:
            with self.subTest(source=source):
                fragment=last(source)
                self.assertFalse(bindings(fragment))
                self.assertTrue(any(check['status']=='UNKNOWN' for check in fragment.get('platformInheritanceChecks',[])))

    def test_unsupported_valid_initializer_bodies_remain_explicitly_unknown(self):
        for declaration in [
            'Object a=new Object(){void nested(){}},b;',
            'java.util.function.Function<Object,Object> a=(Object x)->x,b;',
            'java.util.Map<String,Object> a=java.util.Map.<String,Object>of(),b;',
        ]:
            with self.subTest(declaration=declaration):
                source='abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return Math.min(1,2);}}'
                fragment=last(source)
                self.assertFalse(bindings(fragment))
                self.assertTrue(any('selected_source_field_inventory_unverified' in check['reasons']
                                    for check in fragment.get('platformInheritanceChecks',[])))

    def test_bounded_untyped_lambda_fields_and_following_declarators_are_names_only(self):
        declarations = [
            'java.util.function.IntSupplier callback=()->{return Math.max(7,8);},after;',
            'java.util.function.IntUnaryOperator callback=value->value,after;',
            'java.util.function.IntBinaryOperator callback=(left,right)->{return Math.max(left,right);},after;',
            'java.util.function.Function<Object,Object> callback=x->x,after;',
            'Runnable callback=()->{Math.max(7,8);},after;',
            'Runnable callback=()->{},after;',
        ]
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                source='abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return Math.min(1,2);}}'
                result,facts=extract(source);fragment=returns(result)[-1]
                self.assertEqual(len(bindings(fragment)),1)
                index=core.build_java_index({'Rules.java':source})
                inventory=platform.Inheritance(index,lambda identity:identity).source_inventory('Sample')
                self.assertEqual(inventory['fields'],'complete')
                self.assertEqual(inventory['fieldNames'],['after','callback'])
                self.assertFalse(inventory['reasons'])
                self.assertNotIn('runtimeValue',inventory)
                self.assertFalse(any(record.get('type')=='Constructor' for record in facts['records']))

    def test_unparsed_lambda_headers_bodies_and_remaining_declarators_stay_unknown(self):
        declarations = [
            'Object callback=(Object value)->value,after;',
            'Object callback=(@Deprecated value)->value,after;',
            'Object callback=(left,left)->left,after;',
            'Object callback=(left,)->left,after;',
            'Object callback=()->{return Math.max(7,8)},after;',
            'Object callback=()->{1+2;},after;',
            'Object callback=()->{int local=1;return Math.max(7,8);},after;',
            'Object callback=()->{class Local{}return Math.max(7,8);},after;',
            'Object callback=()->{return new Object(){void nested(){}};},after;',
            'Object callback=()->{return value->value;},after;',
            'Object callback=()->{return Object::new;},after;',
            'Object callback=()->{} extra,after;',
            'Object callback=()->{}(),after;',
            'Object callback=()->{},;',
            'Object callback=()->{},class;',
            '@Deprecated Object callback=()->{},after;',
        ]
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                source='abstract class Sample implements AutoCloseable{'+declaration+'Object f(){return Math.min(1,2);}}'
                result,_=extract(source)
                self.assertFalse(any(bindings(row) for row in returns(result)))
                index=core.build_java_index({'Rules.java':source})
                inventory=platform.Inheritance(index,lambda identity:identity).source_inventory('Sample')
                self.assertEqual(inventory['fields'],'UNKNOWN')

    def test_lambda_inventory_preserves_real_field_and_parameter_shadowing(self):
        source='class Sample{java.util.function.IntSupplier callback=()->{return Math.max(7,8);};Object Math;}'
        result,_=extract(source)
        self.assertFalse(any(bindings(row) for row in returns(result)))
        index=core.build_java_index({'Rules.java':source})
        inventory=platform.Inheritance(index,lambda identity:identity)
        check,_=inventory.query('Sample','Math',True)
        self.assertEqual(check['status'],'present')
        self.assertEqual(check['sourceScopes'][0]['memberInventory']['fieldNames'],['Math','callback'])
        source='class Sample{java.util.function.IntUnaryOperator callback=Math->{return Math.max(7,8);};}'
        result,_=extract(source)
        self.assertFalse(any(bindings(row) for row in returns(result)))

    def test_lambda_parameters_hide_platform_names_in_expression_and_block_bodies(self):
        cases = [
            ('java.util.function.IntUnaryOperator', '(Math)', 'Math.max(7,8)', 'Math.max(1,2)'),
            ('java.util.function.IntUnaryOperator', 'Math', 'Math.max(7,8)', 'Math.max(1,2)'),
            ('java.util.function.BiFunction<Object,Object,Object>', '(System,value)', 'System.currentTimeMillis()', 'System.nanoTime()'),
            ('java.util.function.BiFunction<Object,Object,Object>', '(value,System)', 'System.currentTimeMillis()', 'System.nanoTime()'),
            ('java.util.function.BiFunction<Object,Object,Object>', '(System,value)', 'System.nanoTime()', 'System.nanoTime()'),
            ('java.util.function.BiFunction<Object,Object,Object>', '(value,System)', 'System.nanoTime()', 'System.nanoTime()'),
        ]
        for declared,parameters,call,outside in cases:
            for block in (False,True):
                for field_first in (False,True):
                    with self.subTest(parameters=parameters,block=block,field_first=field_first):
                        body='{return '+call+';}' if block else call
                        field=declared+' callback='+parameters+'->'+body+';'
                        method='Object outside(){return '+outside+';}'
                        source='class Sample{'+(field+method if field_first else method+field)+'}'
                        result,_=extract(source)
                        index=core.build_java_index({'Rules.java':source})
                        inventory=platform.Inheritance(index,lambda identity:identity).source_inventory('Sample')
                        self.assertEqual(inventory['fields'],'complete')
                        all_contracts=[contract for row in result['fragments'] for _,contract in bindings(row)]
                        # Only the ordinary outside method can select a platform
                        # contract; the lambda receiver is a local parameter.
                        self.assertEqual(len(all_contracts),1)
                        inside=[row for row in result['fragments'] if row.get('category')!='control_boundary'
                            and any(context['kind']=='embedded_body' for context in row.get('controlFlow',{}).get('contexts',[]))]
                        self.assertFalse(any(bindings(row) for row in inside))

    def test_supported_sensitive_lambda_boundary_never_declassifies_body(self):
        source=('class Sample{java.util.function.IntSupplier secretCallback=()->{return Math.max(7,8);};'
                'Object outside(){return Math.max(1,2);}}')
        result,_=extract(source)
        inside=[row for row in result['fragments'] if any(context['kind']=='embedded_body'
            for context in row.get('controlFlow',{}).get('contexts',[]))]
        self.assertTrue(inside)
        self.assertTrue(all(row.get('structuralOnly') for row in inside))
        self.assertFalse(any(bindings(row) for row in inside))
        self.assertEqual(sum(len(bindings(row)) for row in result['fragments']),1)

    def test_lambda_parameter_statement_and_delimiter_budgets_remain_bounded(self):
        for initializer in [
            '('+','.join('arg'+str(i) for i in range(platform.MAX_CHECKS+1))+')->0',
            '()->{'+''.join('consume();' for _ in range(platform.MAX_CHECKS+1))+'}',
            '()->{return '+'('*33+'1'+')'*33+';}',
        ]:
            with self.subTest(initializer=initializer):
                source='class Sample{Object callback='+initializer+';Object f(){return Math.min(1,2);}}'
                index=core.build_java_index({'Rules.java':source})
                inventory=platform.Inheritance(index,lambda identity:identity).source_inventory('Sample')
                self.assertEqual(inventory['fields'],'UNKNOWN')

    def test_valid_consumer_proof_cannot_authorize_a_malformed_sibling_owner(self):
        source=('abstract class Good implements AutoCloseable{Object a,b;Object f(){return Math.min(1,2);}}'
                'abstract class Bad implements AutoCloseable{Object a=,b;Object f(){return Math.min(1,2);}}')
        results,facts=analyzed_files({'Rules.java':source})
        good,bad=returns(results['Rules.java'])
        self.assertEqual(len(bindings(good)),1);self.assertFalse(bindings(bad))
        for key in ('expression','standardApiContracts','platformTypeContracts','platformInheritanceChecks','platformTypeProofs'):
            if key in good:bad[key]=copy.deepcopy(good[key])
        finish(results,facts)
        self.assertEqual(len(bindings(good)),1)
        self.assertFalse(bindings(bad))


if __name__=='__main__':unittest.main()
