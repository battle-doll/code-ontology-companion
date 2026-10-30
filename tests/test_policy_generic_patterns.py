"""Bounded instanceof type syntax and conservative generic pattern shadowing."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from test_policy_java_contracts import extract,bindings,returns,policy_semantics as sem


def walk(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from walk(child)
    elif isinstance(value,list):
        for child in value:yield from walk(child)


def parse(expression):
    parser=sem._Expression(sem._tokens(expression),False)
    return parser.parse(),parser.reasons


class GenericPatternTests(unittest.TestCase):
    def call_proofs(self,result):
        return {node['sourceInvocationOffset']:bool(node.get('staticContract'))
                for fragment in result['fragments'] for node in walk(fragment.get('expression'))
                if node.get('op')=='call'}

    def test_nested_lambda_pattern_guard_keeps_outer_callable_positive(self):
        bodies=[
            'java.util.function.Predicate<Object> action=item->PATTERN;',
            'java.util.function.Predicate<Object> action=(item)->PATTERN;',
            'java.util.function.Predicate<Object> action=item->{return PATTERN;};',
            'accept(item->PATTERN);',
            'java.util.function.Supplier<java.util.function.Predicate<Object>> action=()->item->PATTERN;',
        ]
        for body in bodies:
            for binder in ['token','Math']:
                pattern='item instanceof Crate<?> '+binder+' && Math.min(8,3)>0'
                source='class Rules{boolean check(Object entry){'+body.replace('PATTERN',pattern)+'return Math.min(4,2)>0;}}'
                with self.subTest(body=body,binder=binder):
                    result,_=extract(source);calls=self.call_proofs(result)
                    self.assertTrue(calls[source.index('min(4')])
                    self.assertEqual(calls[source.index('min(8')],binder=='token')
        source='class Rules{Rules(){java.util.function.Predicate<Object> action=item->item instanceof Crate<?> Math && Math.min(8,3)>0;int outside=Math.min(4,2);}int next(){return Math.min(6,1);}}'
        calls=self.call_proofs(extract(source)[0])
        self.assertFalse(calls[source.index('min(8')]);self.assertTrue(calls[source.index('min(4')]);self.assertTrue(calls[source.index('min(6')])

    def test_pattern_lambda_siblings_and_parent_arguments_do_not_share_guard(self):
        arguments=['Math.min(1,2)','item->item instanceof Crate<?> Math && Math.min(3,4)>0',
                   '()->Math.min(5,6)','Math.min(7,8)']
        for parts in [arguments,list(reversed(arguments))]:
            source='class Rules{Object check(){return combine('+','.join(parts)+');}}'
            with self.subTest(parts=parts):
                calls=self.call_proofs(extract(source)[0])
                self.assertFalse(calls[source.index('min(3')])
                for marker in ['min(1','min(5','min(7']:self.assertTrue(calls[source.index(marker)])

    def test_nested_pattern_namespace_and_explicit_field_boundaries(self):
        for binder,inside,outside in [('System','System.nanoTime()','System.nanoTime()'),
                ('java','java.lang.Math.min(8,3)','java.lang.Math.min(4,2)'),
                ('Math','java.lang.Math.min(8,3)','java.lang.Math.min(4,2)')]:
            source='class Rules{Object check(){Object action=item->item instanceof Crate<?> '+binder+' && '+inside+';return '+outside+';}}'
            calls=self.call_proofs(extract(source)[0]);positions=sorted(calls)
            self.assertEqual(calls[positions[0]],binder=='Math');self.assertTrue(calls[positions[-1]])
        source='import java.time.Instant;class Rules{Instant cursor;Object check(Instant limit){Object action=item->item instanceof Crate<?> cursor && cursor.isBefore(limit);return cursor.isBefore(limit);}}'
        calls=self.call_proofs(extract(source)[0]);positions=sorted(calls)
        self.assertFalse(calls[positions[0]]);self.assertTrue(calls[positions[-1]])

    def test_unsupported_lambda_pattern_keeps_local_unknown_and_outer_proof(self):
        for typename in ['Crate<? extends Number>','Crate<String>','Crate<?>(Object child)']:
            source='class Rules{Object check(){Object action=item->item instanceof '+typename+' Math && Math.min(8,3)>0;return Math.min(4,2);}}'
            result,_=extract(source)
            self.assertTrue(self.call_proofs(result)[source.index('min(4')])
            self.assertTrue(any(f['expression'] is None and f['representationStatus']=='unsupported' for f in result['fragments']))

    def test_scope_callback_restores_after_exception_and_rejects_foreign_nodes(self):
        source='class Rules{Object check(){return combine(Math.min(1,2),item->item instanceof Crate<?> Math && Math.min(3,4)>0,Math.min(5,6));}}'
        original=sem.policy_java_contracts.enrich;observations=[]
        def inspect(expression,**kwargs):
            callback=kwargs.get('node_scope')
            if callback:
                nodes=[node for node in walk(expression) if node.get('op')=='call']
                inner=next(node for node in nodes if node['sourceInvocationOffset']==source.index('min(3'))
                before=kwargs['type_name']('Math',True)
                self.assertIsNotNone(before)
                def fail():
                    self.assertIsNone(kwargs['type_name']('Math',True))
                    raise RuntimeError('neutral callback failure')
                with self.assertRaisesRegex(RuntimeError,'neutral callback failure'):callback(inner,fail)
                self.assertEqual(kwargs['type_name']('Math',True),before)
                for offset in [-1,len(source),source.index('min(1')]:
                    saved=inner['sourceInvocationOffset'];inner['sourceInvocationOffset']=offset
                    try:
                        self.assertIsNone(callback(inner,lambda:self.fail('invalid context reached lookup')))
                        self.assertEqual(inner['staticContractStatus']['status'],'UNKNOWN')
                    finally:
                        inner['sourceInvocationOffset']=saved;inner.pop('staticContractStatus',None)
                    self.assertEqual(kwargs['type_name']('Math',True),before)
                foreign=copy.deepcopy(inner)
                self.assertIsNone(callback(foreign,lambda:self.fail('foreign node reached lookup')))
                self.assertEqual(kwargs['type_name']('Math',True),before)
                observations.append(True)
            return original(expression,**kwargs)
        with patch.object(sem.policy_java_contracts,'enrich',side_effect=inspect):result,_=extract(source)
        self.assertTrue(observations)
        calls=self.call_proofs(result);self.assertFalse(calls[source.index('min(3')]);self.assertTrue(calls[source.index('min(5')])
        # A later extraction has no shared current-scope state.
        result,_=extract('class Rules{Object check(){return Math.min(1,2);}}')
        self.assertTrue(any(bindings(fragment) for fragment in result['fragments']))

    def test_pattern_scope_near_token_limit_preserves_left_fold_stack(self):
        body='item instanceof Crate<?> token && Math.min(8,3)>0'
        expression='item -> '+body
        while len(sem._tokens(expression+' && ready'))<=sem.MAX_EXPRESSION_TOKENS:
            expression+=' && ready'
        self.assertGreaterEqual(len(sem._tokens(expression)),sem.MAX_EXPRESSION_TOKENS-1)
        source='class Rules{Object check(){Object action='+expression+';return Math.min(4,2);}}'
        result,_=extract(source);calls=self.call_proofs(result)
        self.assertTrue(calls[source.index('min(8')]);self.assertTrue(calls[source.index('min(4')])
        self.assertNotIn('lambda_scopes',json.dumps(result));self.assertNotIn('fragment_call_nodes',json.dumps(result))

    def test_unbounded_generic_type_tests_retain_subject_and_complete_type(self):
        for typename,args,dims in [('Map<?,?>',2,0),('java.util.List<?>',1,0),
                                   ('Outer<?>.Inner<?>',1,0),('List<?>[][]',1,2)]:
            with self.subTest(typename=typename):
                source='candidate instanceof '+typename
                tree,reasons=parse(source)
                self.assertEqual(tree['operator'],'instanceof')
                self.assertEqual(tree['left'],{'op':'reference','name':'candidate'})
                right=tree['right'];self.assertEqual(right['op'],'type_reference')
                self.assertEqual(right['segments'][-1]['typeArguments'],['?']*args)
                self.assertEqual(right['arrayDimensions'],dims)
                self.assertEqual(source[right['sourceRange']['charStart']:right['sourceRange']['charEnd']],typename)
                self.assertEqual(right['runtimeTypeCheck'],right['compileValidity'],'UNKNOWN')
                self.assertEqual(right['resolution'],'syntax_only')
                self.assertEqual(right['syntaxVersion'],'java.instanceof.type.v1')
                self.assertEqual(reasons,{'instanceof_runtime_unresolved'})
                self.assertFalse(any('staticType' in node or 'staticContract' in node for node in walk(right)))

    def test_type_patterns_keep_binder_and_unresolved_flow_scope(self):
        expression='value instanceof java.util.Map<?,?> matched'
        tree,reasons=parse(expression);pattern=tree['right']
        self.assertEqual(pattern['op'],'type_pattern');self.assertEqual(pattern['binding'],'matched')
        self.assertEqual(pattern['scopeResolution'],'flow_scope_unresolved')
        self.assertEqual(sem._walk_references(tree),['value'])
        self.assertEqual(reasons,{'instanceof_runtime_unresolved'})

    def test_precedence_negation_conditional_and_branch_contexts_are_preserved(self):
        tree,_=parse('enabled && value instanceof List<?> matched && other')
        self.assertEqual(tree['operator'],'&&');self.assertEqual(tree['left']['operator'],'&&')
        self.assertEqual(tree['left']['right']['operator'],'instanceof')
        tree,_=parse('value instanceof List<?> ? left : right')
        self.assertEqual(tree['op'],'conditional');self.assertEqual(tree['condition']['operator'],'instanceof')
        text='class Rules{boolean f(Object value){if(!(value instanceof List<?> matched))return false;else return true;}}'
        result,_=extract(text);condition=next(f for f in result['fragments'] if f['category']=='condition')
        self.assertEqual(condition['expression']['op'],'unary')
        self.assertEqual(condition['expression']['operand']['operator'],'instanceof')
        branches=[c['branch'] for f in returns(result) for c in f['controlFlow']['contexts'] if c['kind']=='condition']
        self.assertEqual(branches,['true','false'])
        self.assertEqual(condition['representationStatus'],'partial')
        self.assertFalse(condition['businessMeaningVerified'])
        self.assertEqual(condition['runtimeStatus'],'not_observed')

    def test_comments_whitespace_and_original_offsets_are_not_erased(self):
        source='input instanceof java.util.Map< /*neutral*/ ?, ? > item'
        tree,_=parse(source);right=tree['right']['type']
        self.assertEqual(source[right['sourceRange']['charStart']:right['sourceRange']['charEnd']], 'java.util.Map< /*neutral*/ ?, ? >')
        self.assertNotIn('neutral',json.dumps(tree))

    def test_plain_type_and_plain_pattern_keep_legacy_ast_shapes(self):
        self.assertEqual(parse('value instanceof String')[0],{'op':'binary','operator':'instanceof','left':{'op':'reference','name':'value'},'right':{'op':'reference','name':'String'}})
        self.assertEqual(parse('value instanceof Object matched')[0]['right'],{'op':'type_pattern','type':{'op':'reference','name':'Object'},'binding':'matched'})

    def test_nonreifiable_bound_annotation_and_record_forms_stay_unsupported(self):
        forms=['List<String>','List<? extends Number>','List<? super Number>','Map<?,String>',
               'Outer<?>.Inner<String>','List<List<?>>','Map<>','Map<?,>','Map<,?>',
               'List<?>[index]','@Marker List<?>','List<?> @Marker []','Box<?>(Object member)',
               'Box(Object member)','var<?>','record<?>','int<?>','List<?> this']
        for typename in forms:
            with self.subTest(typename=typename),self.assertRaises(sem._Unsupported):parse('input instanceof '+typename)

    def test_type_shape_and_expression_budgets_remain_finite(self):
        parse('input instanceof List<?>'+'[]'*sem.MAX_EXPRESSION_DEPTH)
        forms=['List<?>'+'[]'*(sem.MAX_EXPRESSION_DEPTH+1),
               '.'.join('Part' for _ in range(sem.MAX_EXPRESSION_DEPTH+1))+'<?>',
               'Many<'+','.join('?' for _ in range(sem.MAX_EXPRESSION_DEPTH+1))+'>']
        for typename in forms:
            with self.subTest(typename=typename),self.assertRaisesRegex(sem._Unsupported,''):
                parse('input instanceof '+typename)
        with self.assertRaises(sem._Unsupported):parse('('*40+'input instanceof List<?>'+')'*40)

    def test_rhs_recursion_entry_matches_plain_at_exact_depth_boundary(self):
        for typename in ['Plain', 'List<?>']:
            for base in [30,31]:
                with self.subTest(typename=typename,base=base):
                    sem._Expression(sem._tokens('input instanceof '+typename),False,base_depth=base).parse()
            for base in [32,33]:
                with self.subTest(typename=typename,base=base),self.assertRaises(sem._Unsupported):
                    sem._Expression(sem._tokens('input instanceof '+typename),False,base_depth=base).parse()
        # Left-folded binary trees keep the legacy recursion-entry semantics;
        # the depth budget has never been a bound on final AST child edges.
        sem._Expression(sem._tokens('+'.join('item' for _ in range(80))),False,base_depth=31).parse()
        with self.assertRaises(sem._Unsupported):
            sem._Expression(sem._tokens('item+other'),False,base_depth=32).parse()

    def test_plain_qualified_legacy_and_extended_shape_caps_are_separate(self):
        for count in [31,32,33,255]:
            typename='.'.join('Part' for _ in range(count))
            tree,_=parse('input instanceof '+typename)
            self.assertEqual(tree['right'],{'op':'reference','name':typename})
        with self.assertRaises(sem._Unsupported):parse('input instanceof '+'.'.join('Part' for _ in range(256)))
        for count in [31,32]:
            parse('input instanceof '+'.'.join('Part' for _ in range(count))+'<?>')
        with self.assertRaises(sem._Unsupported):
            parse('input instanceof '+'.'.join('Part' for _ in range(33))+'<?>')
        for count in [31,32]:
            parse('input instanceof First<'+','.join('?' for _ in range(count-1))+'>.Second<?>')
        with self.assertRaises(sem._Unsupported):
            parse('input instanceof First<'+','.join('?' for _ in range(32))+'>.Second<?>')

    def test_reader_token_budget_is_consumption_not_peek_or_binder(self):
        for count in [255,256]:
            typename='.'.join('Part' for _ in range(count))
            tokens=sem._tokens(typename+' binder')
            _,end,_=sem._instanceof_type_syntax(tokens,0)
            self.assertEqual(end,count*2-1)
            self.assertEqual(tokens[end].value,'binder')
        with self.assertRaises(sem._Unsupported):
            sem._instanceof_type_syntax(sem._tokens('.'.join('Part' for _ in range(257))),0)

    def test_unknown_flow_owner_stays_in_actual_callable_or_local_block(self):
        source='class Rules{Object one(Object input){if(input instanceof Box<?> Math)return Math.max(1,2);return null;}Object two(){return Math.max(1,2);}}'
        original=sem.policy_java_flow.scan
        def no_methods(*args,**kwargs):
            nodes,_=original(*args,**kwargs)
            return nodes,{}
        with patch.object(sem.policy_java_flow,'scan',side_effect=no_methods):
            result,_=extract(source)
        self.assertEqual([c['method'] for f in result['fragments'] for _,c in bindings(f)],['max'])
        # Raw extraction has no Java-index type proof. Check the actual
        # lexical field binding rather than expecting a platform contract.
        source='class Rules{Object Math;Object one(Object input){if(input instanceof Box<?> Math)return Math;return null;}Object two(){return Math;}}'
        with patch.object(sem.policy_java_flow,'scan',side_effect=no_methods):
            result=sem.extract_semantics(source,'Java','Rules.java',hashlib.sha256(source.encode()).hexdigest())
        references=[r for f in returns(result) for r in f['references'] if r['name']=='Math']
        self.assertEqual([r['resolution'] for r in references],['nested_scope_binding_unresolved','lexical_declaration_only'])

    def test_fallback_budget_reason_and_shadow_are_local_to_callable(self):
        pattern='Box<'+','.join('?' for _ in range(300))+'> Math'
        source='class Rules{Object one(Object input){if(input instanceof '+pattern+')return Math.max(1,2);return null;}Object two(){return Math.max(1,2);}}'
        result,_=extract(source)
        self.assertEqual([c['method'] for f in result['fragments'] for _,c in bindings(f)],['max'])
        affected=[f for f in result['fragments'] if 'pattern_scope_budget_exceeded' in f['unsupportedReasons']]
        self.assertTrue(affected)
        self.assertTrue(all(f['sourceRange']['charStart']<source.index('Object two') for f in affected))

    def test_unbounded_and_bound_math_system_binders_never_gain_platform_contract(self):
        for typename in ['Box<?>','Box<?,?>','Outer<?>.Inner<?>','Box<?>[]',
                         'Box<? extends Number>','Box<? super Number>','Box<String>',
                         'Box<?>(Object nested)','Box<?,>']:
            for name,call in [('Math','Math.max(1,2)'),('System','System.nanoTime()'),
                              ('java','java.lang.Math.max(1,2)')]:
                text='class Rules{Object f(Object input){if(input instanceof '+typename+' '+name+')return '+call+';return null;}}'
                with self.subTest(typename=typename,name=name):
                    result,_=extract(text)
                    self.assertFalse(any(bindings(f) for f in result['fragments']))

    def test_pattern_in_boolean_expression_and_guard_exit_is_not_outer_field(self):
        statements=['if(input instanceof Box<?> Math && Math.max(1,2)>0)return true;',
                    'if(!(input instanceof Box<?> Math))return false;return Math.max(1,2)>0;',
                    'if(input instanceof Box<?> Math)return true;else return Math.max(1,2)>0;']
        for statement in statements:
            text='class Rules{boolean f(Object input){'+statement+'return false;}}'
            with self.subTest(statement=statement):self.assertFalse(any(bindings(f) for f in extract(text)[0]['fragments']))
        text='import java.math.BigDecimal;class Rules{BigDecimal amount;Object f(Object input){if(input instanceof Box<?> amount)return amount.abs();return null;}}'
        self.assertFalse(any(bindings(f) for f in extract(text)[0]['fragments']))

    def test_separate_methods_and_unshadowed_qualified_namespace_remain_positive(self):
        text='class Rules{Object one(Object input){if(input instanceof Box<?> Math)return Math.max(1,2);return null;}Object two(){return Math.max(1,2);}}'
        result,_=extract(text);self.assertEqual([c['method'] for f in result['fragments'] for _,c in bindings(f)],['max'])
        text='class Rules{Object f(Object input){if(input instanceof Box<?> Math)return java.lang.Math.max(1,2);return null;}}'
        self.assertEqual([c['method'] for f in extract(text)[0]['fragments'] for _,c in bindings(f)],['max'])

    def test_exhausted_fallback_cannot_restore_unseen_binder_namespace(self):
        pattern='Box<'+','.join('?' for _ in range(300))+'> Math'
        text='class Rules{Object f(Object input){if(input instanceof '+pattern+')return Math.max(1,2);return null;}}'
        result,_=extract(text)
        self.assertFalse(any(bindings(f) for f in result['fragments']))
        self.assertTrue(any('expression_budget_exceeded' in f['unsupportedReasons'] for f in result['fragments']))

    def test_sensitive_annotation_values_are_not_projected(self):
        marker='Neutral Pattern Private Value'
        text='class Rules{boolean f(Object input){return input instanceof @Marker("'+marker+'") List<?> value;}}'
        result,facts=extract(text)
        self.assertNotIn(marker,json.dumps({'semantics':result,'facts':facts}))


if __name__=='__main__':unittest.main()
