"""Bounded normal record constructor declarations, never initialization evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_policy_java_contracts import core, extract, pipeline_java, returns, bindings
from test_java_member_closure import inventory
import pipeline_acl as acl
import pipeline_access as access
import pipeline_store as store

platform = pipeline_java.policy_java_platform
ROOT = Path(__file__).resolve().parents[1]


def record(body, prefix='record Portion(Object value)'):
    return prefix + ' implements AutoCloseable{' + body + 'public void close(){}Object f(){return Math.min(1,2);}}'


class RecordConstructorInventoryTests(unittest.TestCase):
    def complete(self, text, owner='Portion', names=('value',)):
        observed = inventory(text, owner)
        self.assertEqual((observed['fields'], observed['memberTypes']), ('complete', 'complete'))
        self.assertEqual(observed['fieldNames'], sorted(names))
        self.assertFalse(observed['reasons'])
        return observed

    def unknown(self, text, owner='Portion'):
        observed = inventory(text, owner)
        self.assertEqual((observed['fields'], observed['memberTypes']), ('UNKNOWN', 'UNKNOWN'))
        self.assertTrue(observed['reasons'])
        self.assertFalse(any(bindings(f) for f in extract(text)[0]['fragments']))

    def test_supported_normal_headers_and_compact_have_separate_kinds(self):
        for body, kinds in [
            ('Portion(){this(null);}', ['record_explicit']),
            ('private Portion(int ignored,int other){this(null);}', ['record_explicit']),
            ('Portion(Object value){this.value=value;}', ['record_explicit']),
            ('Portion(){this(null);}Portion{Object Math=null;}', ['record_explicit','record_compact']),
            ('Portion() throws Failure,other.Failure{this(null);}', ['record_explicit']),
            ('Portion(int ignored,Object... rest){this(null);}', ['record_explicit']),
        ]:
            with self.subTest(body=body):
                text=record(body);observed=self.complete(text)
                self.assertEqual([r['kind'] for r in observed['_constructorRegions']], kinds)
                self.assertEqual(len(bindings(returns(extract(text)[0])[-1])),1)

    def test_canonical_access_is_distinct_from_overload_access(self):
        for prefix, body in [
            ('public record Portion(Object value)', 'public Portion(Object value){this.value=value;}'),
            ('public record Portion(Object value)', 'private Portion(){this(null);}'),
            ('record Portion(Object value)', 'protected Portion(Object value){this.value=value;}'),
        ]:
            with self.subTest(prefix=prefix,body=body):self.complete(record(body,prefix))
        for body in ['private Portion(Object value){this.value=value;}', 'Portion(Object value){this.value=value;}']:
            self.unknown(record(body,'public record Portion(Object value)'))

    def test_nested_owners_and_interface_implicit_public_access(self):
        self.complete('class Outer{'+record('public Portion(){this(null);}public Portion{}','public record Portion(Object value)')+'}', 'Outer.Portion')
        self.complete('interface Outer{'+record('public Portion(Object value){this.value=value;}')+'}', 'Outer.Portion')
        self.unknown('interface Outer{'+record('Portion(Object value){this.value=value;}')+'}', 'Outer.Portion')
        self.unknown(record('Other(){}'))

    def test_array_varargs_and_generic_record_type_headers_only(self):
        self.complete(record('Portion(Object value[]){this.value=value;}','record Portion(Object[] value)'))
        self.complete(record('Portion(Object... value){this.value=value;}','record Portion(Object... value)'))
        # Generic record type variables are names; generic constructor headers
        # and their erasure/constructor selection are deliberately unsupported.
        self.complete(record('Portion(T value){this.value=value;}','record Portion<T>(T value)'))
        for body,prefix in [
            ('Portion(Object[] value){this.value=value;}','record Portion(Object... value)'),
            ('Portion(Object... value){this.value=value;}','record Portion(Object[] value)'),
            ('<T> Portion(T value,int extra){this(null);}','record Portion(Object value)'),
        ]:
            with self.subTest(body=body):self.unknown(record(body,prefix))

    def test_same_arity_type_equivalence_and_annotations_remain_unknown(self):
        for body in ['private Portion(int ignored){this(null);}', 'Portion(String value){this(null);}',
                     'Portion(java.lang.Object value){this.value=value;}',
                     'Portion(Object renamed){this.value=renamed;}',
                     'Portion(@Deprecated Object value){this.value=value;}',
                     '@Deprecated Portion(){this(null);}',
                     'Portion(Portion this){this(null);}']:
            with self.subTest(body=body):self.unknown(record(body))

    def test_duplicate_and_canonical_conflicts_fail_closed(self):
        for body in ['Portion{}Portion{}', 'Portion(){}Portion(){}',
                     'Portion{}Portion(Object value){this.value=value;}',
                     'Portion(Object value){this.value=value;}Portion(Object value){this.value=value;}',
                     'Portion(Object value) throws Failure{this.value=value;}']:
            with self.subTest(body=body):self.unknown(record(body))

    def test_former_unsupported_canonical_header_keeps_body_semantics_unknown(self):
        # The former compact-only negative was a header support boundary.
        # Empty bodies do not prove definite assignment or Java compilation.
        text=record('Portion(Object value){}')
        observed=self.complete(text)
        self.assertEqual(observed['_constructorRegions'][0]['kind'],'record_explicit')
        self.assertEqual(observed['_constructorRegions'][0]['status'],'constructor_body_semantics_not_modeled')
        _,facts=extract(text)
        selected=next(r for r in facts['records'] if r.get('name')=='Portion' and 'constructorInventory' in r)
        self.assertEqual(selected['constructorInventory']['modeledConstructorBodies'],0)
        self.assertEqual(selected['constructorInventory']['wholeJavaDeclarationDenominator'],'UNKNOWN')

    def test_invalid_headers_and_unbalanced_bodies_fail_closed(self):
        for body in ['static Portion(){}','abstract Portion(){}','public private Portion(){}',
                     'Portion(int){}','Portion(int x,int x){}','Portion(int x,){}',
                     'Portion(int... x,int y){}','Portion(var x){}','Portion(void x){}',
                     'Portion(final final int x){}','Portion() throws Failure[]{}',
                     'Portion() trailing{}','Portion(;{}']:
            with self.subTest(body=body):self.unknown(record(body))

    def test_compact_invalid_component_inventory_does_not_crash(self):
        for prefix in ['record Portion(void value)','record Portion(Object value,Object value)']:
            observed=inventory(record('Portion{}',prefix),'Portion')
            self.assertEqual(observed['fields'],'UNKNOWN')
            self.assertTrue(observed['reasons'])

    def test_record_header_bool_api_is_backward_compatible_and_bounded(self):
        scope={'kind':'record','name':'Portion'}
        self.assertIs(platform.Inheritance.constructor_header_supported('Portion',scope),True)
        self.assertIs(platform.Inheritance.constructor_header_supported('Portion()',scope),False)
        self.assertIs(platform.Inheritance.constructor_header_supported('Portion()',scope,record_components=[]),True)
        self.assertIs(platform.Inheritance.constructor_header_supported('Wrong()',scope,record_components=[]),False)
        components=[{'name':'value','rawType':'Object'}]
        self.assertIs(platform.Inheritance.constructor_header_supported('Portion(Object value)',scope,record_components=components),True)
        self.assertIs(platform.Inheritance.constructor_header_supported('Portion(Object value) throws E',scope,record_components=components),False)

    def test_shadow_names_parent_unknown_and_accessor_do_not_gain_wrong_contracts(self):
        cases=[record('Portion(){this(null);}','record Portion(Object Math)'),
               record('Portion(){this(null);}static class Math{}'),
               'interface Parent{class Math{}}record Portion(Object value) implements Parent{Portion(){this(null);}Object f(){return Math.min(1,2);}}',
               'record Portion(Object value) implements External{Portion(){this(null);}Object f(){return Math.min(1,2);}}']
        for text in cases:
            with self.subTest(text=text):self.assertFalse(any(bindings(f) for f in extract(text)[0]['fragments']))
        text='import java.time.Instant; record Event(Instant until){Event(){this(null);}Event(Instant until){this.until=until;}}class Use{boolean f(Event event,Instant now){return event.until().isBefore(now);}}'
        output,facts=extract(text)
        self.assertEqual([c['method'] for _,c in bindings(returns(output)[-1])],['isBefore'])
        self.assertFalse(any(r.get('type')=='Constructor' or r.get('predicate')=='CONSTRUCTS' for r in facts['records']))
        for row in facts['records']:
            if 'constructorInventory' in row:
                self.assertEqual(row['constructorInventory']['modeledConstructorBodies'],0)
                self.assertEqual(row['constructorInventory']['constructorCalls'],'not_added')

    def test_field_names_constructor_scopes_and_budget_are_not_omitted(self):
        observed=self.complete(record('Portion(){this(null);Object Math=null;class Local{Object Duration;}}'))
        self.assertEqual(observed['fieldNames'],['value'])
        for region in observed['_constructorRegions']:
            self.assertEqual(region['status'],'constructor_body_semantics_not_modeled')
        with patch.object(platform,'MAX_SOURCE_MEMBERS',2):
            observed=inventory(record('Portion(){this(null);}Portion(int x){this(null);}Portion(int x,int y){this(null);}'),'Portion')
            self.assertEqual(observed['fields'],'UNKNOWN')
            self.assertIn('selected_source_member_inventory_budget_exceeded',observed['reasons'])

    def test_custom_headers_never_enable_implicit_parameter_to_field_mapping(self):
        for body in ['', 'Portion(){this(null);}',
                     'Portion(Object value){this.value=value;}', 'Portion{}']:
            text='record Portion(Object value){'+body+'}class Use{Object f(){return new Portion(null);}}'
            index=core.build_java_index({'Rules.java':text})
            facts={'path':'Rules.java','sourceDigest':hashlib.sha256(text.encode()).hexdigest(),
                   'module':'neutral','modulePath':'.','records':[]}
            pipeline_java.enrich(facts,index)
            context=pipeline_java.semantic_type_context(facts,index)
            observed=context['recordConstruction']('Portion',1,text.index('new Portion'))
            self.assertIsNotNone(observed)
            self.assertEqual(observed['resolution'],'UNKNOWN' if body else 'implicit_canonical_parameter_order')
            self.assertEqual(observed['declaration']['parameterToField'],'UNKNOWN' if body else 'implicit_assignment_on_success')
            self.assertEqual(observed['declaration']['runtimeFieldValues'],'UNKNOWN')

    def test_private_constructor_body_values_are_not_projected(self):
        marker='Neutral Constructor Private Identity'
        text=record('Portion(){this(null);String hidden="'+marker+'";Object Duration=null;}')
        observed=self.complete(text)
        self.assertEqual(observed['fieldNames'],['value'])
        sem,facts=extract(text)
        self.assertNotIn(marker,json.dumps({'semantics':sem,'facts':facts}))


if __name__=='__main__':unittest.main()
