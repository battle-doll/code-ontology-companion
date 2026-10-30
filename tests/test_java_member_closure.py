"""C18 neutral constructor/creation syntax closure; no target source fixtures."""
import copy
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
from test_policy_literal_review import walk
from test_java_member_inventory import constants
import pipeline_access as access
import pipeline_acl as acl
import pipeline_store as store

platform = pipeline_java.policy_java_platform
ROOT = Path(__file__).resolve().parents[1]


def ordinary(declaration):
    return ('abstract class Sample implements AutoCloseable{' + declaration +
            'Object f(){return Math.min(1,2);}}')


def inventory(text, owner='Sample'):
    index = core.build_java_index({'Rules.java': text})
    return platform.Inheritance(index, lambda identity: identity,
        record_header=lambda scope: pipeline_java._record_component_header(index, scope)).source_inventory(owner)


class JavaMemberClosureTests(unittest.TestCase):
    def assert_complete(self, text, owner='Sample', names=()):
        observed = inventory(text, owner)
        self.assertEqual((observed['fields'], observed['memberTypes']), ('complete', 'complete'))
        self.assertEqual(observed['fieldNames'], sorted(names))
        self.assertFalse(observed['reasons'])
        fragment = returns(extract(text)[0])[-1]
        self.assertEqual(len(bindings(fragment)), 1)
        for check in fragment['platformInheritanceChecks']:
            self.assertEqual(check['status'], 'absent')
            self.assertTrue(check['transitiveInventoryComplete'])
            for scope in check['sourceScopes']:
                self.assertEqual(scope['sourceDigest'], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(scope['sourceRange']['charStart'], core.build_java_index({'Rules.java':text}).types[owner]['start'])

    def assert_unknown(self, text, owner='Sample'):
        observed = inventory(text, owner)
        self.assertEqual(observed['fields'], 'UNKNOWN')
        self.assertTrue(observed['reasons'])
        self.assertFalse(any(bindings(fragment) or constants(fragment) for fragment in extract(text)[0]['fragments']))

    def test_c14v2_supported_examples_are_now_positive(self):
        # These are the only former C14v2 UNKNOWN examples promoted by C18.
        self.assert_complete(ordinary('Sample(){}'))
        self.assert_complete(ordinary('Object first=new Pair<String,Object>(),second;'), names=('first', 'second'))

    def test_class_constructor_headers_and_balanced_bodies_are_names_only(self):
        for header in ['Sample()', 'public Sample()', 'protected Sample()', 'private Sample()',
                       'Sample(int value)', 'Sample(final int value,String label[])',
                       'Sample(java.util.Map<String,java.util.List<int[]>> value, Object... rest)',
                       '<T> Sample(T value)',
                       'protected <T extends Number & Comparable<T>,U> Sample(T value,U other) throws Failure,other.Failure']:
            with self.subTest(header=header):
                self.assert_complete(ordinary(header+'{Object Math=null; class Local{Object BigDecimal;} if(true){Object Duration=null;}}'))

    def test_enum_constructor_headers(self):
        for header in ['Choice()', 'private Choice()', 'Choice(int value)', '<T> Choice(T value)']:
            with self.subTest(header=header):
                self.assert_complete('enum Choice implements AutoCloseable{ALPHA;'+header+'{Object Math=null;}public void close(){}Object f(){return Math.min(1,2);}}', 'Choice', ('ALPHA',))

    def test_record_compact_headers_keep_implicit_component_names(self):
        for prefix, header in [('record Portion(Object value)', 'Portion'),
                               ('public record Portion(Object value)', 'public Portion')]:
            with self.subTest(prefix=prefix):
                self.assert_complete(prefix+' implements AutoCloseable{'+header+'{Object Math=null;}public void close(){}Object f(){return Math.min(1,2);}}', 'Portion', ('value',))

    def test_constructor_paired_negative_headers_and_boundaries(self):
        declarations = ['Wrong(){}', 'Sample(int){}', 'Sample(int x,int x){}', 'Sample(int x,){}',
                        'Sample(int... x,int y){}', 'Sample(int... x[]){}', 'Sample(void x){}',
                        'Sample(var x){}', 'Sample(final final int x){}', 'Sample(Sample this){}',
                        'Sample(Sample Sample.this){}', 'Sample(@Marker Object x){}', '@Marker Sample(){}',
                        'static Sample(){}', 'final Sample(){}', 'abstract Sample(){}', 'native Sample(){}',
                        'synchronized Sample(){}', 'strictfp Sample(){}', 'public public Sample(){}',
                        'public private Sample(){}', 'Sample() throws {}', 'Sample() throws Failure, {}',
                        'Sample() throws int {}', 'Sample() throws Failure[] {}', 'Sample() throws Failure<Object> {}',
                        '<> Sample(){}', '<T,> Sample(){}', '<T,T> Sample(){}', '<T extends ?> Sample(){}',
                        '<T extends int> Sample(){}', '<T extends Number &> Sample(){}',
                        'Sample() trailing {}', 'Sample;', 'Sample(){} Object hidden,;',
                        'Sample(){if(true){]', 'Sample(', 'Sample() {']
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                self.assert_unknown(ordinary(declaration))

    def test_enum_and_compact_record_invalid_owners_modifiers_and_headers(self):
        for header in ['public Choice()', 'protected Choice()', 'Other()', 'static Choice()']:
            with self.subTest(header=header):
                self.assert_unknown('enum Choice implements AutoCloseable{ALPHA;'+header+'{}public void close(){}Object f(){return Math.min(1,2);}}', 'Choice')
        for declaration in ['Other{}', 'static Portion{}', '<T> Portion{}', 'Portion throws Failure{}',
                            'private Portion{}', 'Portion{} Portion{}']:
            with self.subTest(declaration=declaration):
                self.assert_unknown('record Portion(Object value) implements AutoCloseable{'+declaration+'public void close(){}Object f(){return Math.min(1,2);}}', 'Portion')
        self.assert_unknown('public record Portion(Object value) implements AutoCloseable{Portion{}public void close(){}Object f(){return Math.min(1,2);}}', 'Portion')
        self.assert_unknown('interface Sample extends AutoCloseable{Sample{}default Object f(){return Math.min(1,2);}}')

    def test_generic_and_diamond_creation_initializers_fully_consume_types(self):
        for creation in ['new java.util.HashMap<>()', 'new Pair<String,Object>()',
                         'new Pair<String,java.util.List<Object>>()',
                         'new Pair<java.util.Map<String,java.util.List<Object>>,Object>()',
                         'new Pair<java.util.List<? extends Number>,java.util.List<? super Integer>>()',
                         'new Pair<int[],Object[]>()', 'new Pair<java.util.List<int[]>,Object>()',
                         'new Pair<String,Object>(provider(1,2),new Box<>())',
                         '(new Pair<String,Object>())', 'flag?new Box<>():new Pair<String,Object>()',
                         'new Pair<String,Object>(){}']:
            with self.subTest(creation=creation):
                self.assert_complete(ordinary('Object first='+creation+',second;'), names=('first','second'))
        self.assert_complete(ordinary('java.util.List<int[]> first,second;'), names=('first','second'))

    def test_malformed_or_unsupported_creations_fail_closed(self):
        for creation in ['new while()', 'new int()', 'new ?()', 'new Pair<int>()', 'new Pair<?>suffix()',
                         'new Pair<?>()', 'new Pair<? extends Number>()', 'new Pair<? super Number>()',
                         'new Pair<String,>()', 'new Pair<,Object>()', 'new Pair<<String>>()',
                         'new Pair<String,Object>> Extra()', 'new Pair<String,Object>>>()',
                         'new Pair<String,Object>() junk', 'new Pair<String,Object>(,)',
                         'new Pair<String,Object>(1,)', 'new Pair<String,Object>(){Object hidden;}',
                         'new Pair<String,Object>(){void nested(){}}', 'new Box<>.Nested()',
                         'new Box<String>.Nested()', 'new <String> Box()',
                         'new Pair<java.util.List<int>,Object>()', 'new Pair<java.util.List<? extends ?>,Object>()',
                         'new Pair<String,Object>[1]', 'new Pair<String,Object>[]{}',
                         'factory.<String,Object>make()']:
            with self.subTest(creation=creation):
                self.assert_unknown(ordinary('Object first='+creation+',second;'))

    def test_untyped_lambda_generic_creation_preserves_names_only(self):
        # Former C18 UNKNOWN item: C20 explicitly supports this fully consumed
        # untyped lambda for direct-name boundaries. The other 26 malformed
        # creation cases retain their original negative expectations.
        source=ordinary('Object first=x->new Pair<String,Object>(),second;')
        self.assert_complete(source,names=('first','second'))
        _,facts=extract(source)
        self.assertFalse(any(row.get('predicate')=='CALLS' for row in facts['records']))
        # Object assignment, Pair lookup/arity, compilation, values and lambda
        # execution are deliberately not established by the names inventory.

    def test_true_hiding_and_unknown_parents_remain_fail_closed(self):
        expressions = {'Math':'Math.min(1,2)', 'Duration':'Duration.ofNanos(1)', 'BigDecimal':'BigDecimal.ONE'}
        imports = 'import java.time.Duration;import java.math.BigDecimal;'
        for name, expression in expressions.items():
            declarations = ['Object first=new Pair<String,Object>(),'+name+';Sample(){Object local=null;}',
                            'Sample(){} class '+name+'{}']
            for declaration in declarations:
                with self.subTest(name=name, declaration=declaration):
                    text=imports+ordinary(declaration).replace('Math.min(1,2)', expression)
                    self.assertFalse(any(bindings(f) or constants(f) for f in extract(text)[0]['fragments']))
            for text in [imports+'record Portion(Object '+name+') implements AutoCloseable{Portion{}public void close(){}Object f(){return '+expression+';}}',
                         imports+'enum Choice implements AutoCloseable{'+name+';Choice(){}public void close(){}Object f(){return '+expression+';}}']:
                self.assertFalse(any(bindings(f) or constants(f) for f in extract(text)[0]['fragments']))
        unknown = returns(extract(ordinary('Sample(){}').replace('implements AutoCloseable', 'extends Missing'))[0])[-1]
        self.assertFalse(bindings(unknown))
        self.assertTrue(any(c['status']=='UNKNOWN' for c in unknown['platformInheritanceChecks']))
        self.assert_unknown(ordinary(r'Sample(){}Object first,Ma\u0074h;'))

    def test_constructor_and_creation_changes_do_not_modify_source_records_or_expression_values(self):
        fixtures = [ordinary('Sample(){Object Math=null;}'), ordinary('Object first=new Pair<String,Object>(),second;'),
                    'record Portion(Object value) implements AutoCloseable{Portion{}public void close(){}Object f(){return Math.min(1,2);}}']
        def syntax(value):
            # Select only source expression fields, never derived proof/type
            # annotations. Source record comparison below is fully exact.
            keys = {'op','name','type','value','javaSuffix','operator','resolution','sourceInvocationOffset',
                    'sourceConstructionOffset','opaqueLiteralId','identityScope','callee','receiver','arguments',
                    'left','right','operand','condition','then','else','dimensions','initializer','elements'}
            if isinstance(value,dict): return {k:syntax(v) for k,v in value.items() if k in keys}
            if isinstance(value,list): return [syntax(v) for v in value]
            return value
        for text in fixtures:
            with self.subTest(text=text):
                result, facts = extract(text)
                with patch.object(platform.Inheritance,'constructor_header_supported',return_value=False), patch.object(platform.Inheritance,'initializer_tokens',lambda self,raw,semantics:semantics._tokens(raw)):
                    previous, previous_facts = extract(text)
                stable_keys = {'id','kind','type','name','owner','path','span','sourceRange','declarationHeaderRange',
                               'declarationSpan','bodySpan','sourceDigest','status','target','resolution',
                               'subject','predicate','object','caller','column','argumentCount'}
                self.assertEqual([{k:v for k,v in r.items() if k in stable_keys} for r in facts['records']],
                                 [{k:v for k,v in r.items() if k in stable_keys} for r in previous_facts['records']])
                self.assertEqual([r for r in facts['records'] if r['kind']=='callsite' or r.get('predicate')=='CALLS'],
                                 [r for r in previous_facts['records'] if r['kind']=='callsite' or r.get('predicate')=='CALLS'])
                for record in facts['records']:
                    if 'constructorInventory' not in record: continue
                    coverage=record['constructorInventory']
                    self.assertEqual(coverage['modeledConstructorBodies'],0)
                    self.assertEqual(coverage['wholeJavaDeclarationDenominator'],'UNKNOWN')
                    self.assertEqual(coverage['sourceDigest'],hashlib.sha256(text.encode()).hexdigest())
                    for region in coverage['regions']:
                        self.assertEqual(region['status'],'constructor_body_semantics_not_modeled')
                        self.assertEqual(region['sourceRange']['charStart'],region['headerRange']['charStart'])
                        self.assertEqual(region['sourceRange']['charEnd'],region['bodyRange']['charEnd'])
                        self.assertEqual(region['headerRange']['charEnd'],region['bodyRange']['charStart'])
                        self.assertEqual(text[region['bodyRange']['charStart']],'{')
                        self.assertEqual(text[region['bodyRange']['charEnd']-1],'}')
                self.assertTrue(all('_constructorRegions' not in c['memberInventory'] for f in result['fragments']
                    for check in f.get('platformInheritanceChecks',[]) for c in check['sourceScopes']))
                self.assertEqual([syntax(f['expression']) for f in result['fragments']], [syntax(f['expression']) for f in previous['fragments']])
                self.assertEqual([(f['id'],f['sourceRange']) for f in result['fragments']], [(f['id'],f['sourceRange']) for f in previous['fragments']])
                self.assertTrue(any(bindings(f) for f in result['fragments']))
                self.assertFalse(any(bindings(f) for f in previous['fragments']))

    @unittest.skipIf(os.name == 'nt', 'Native Windows private ACL provisioning is a separate check')
    def test_real_offline_source_free_mcp_keeps_positive_negative_contract_and_metadata_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); repo=base/'source'; repo.mkdir(); workspace=base/'workspace'
            sources={'Safe.java':ordinary('Sample(){}Object first=new Pair<String,Object>(),second;'),
                     'Hidden.java':'abstract class Hidden implements AutoCloseable{Hidden(){}Object first=new Pair<String,Object>(),Math;Object f(){return Math.min(1,2);}}',
                     'Malformed.java':'abstract class Malformed implements AutoCloseable{Malformed(int x,int x){}Object f(){return Math.min(1,2);}}'}
            for path,text in sources.items(): (repo/path).write_text(text)
            env={**os.environ,'CODE_ONTOLOGY_HOME':str(base/'registry'),acl.PRINCIPAL_ENV:'local-owner'}
            with patch.dict(os.environ,env):
                result=store.initialize(repo,workspace); acl.initialize_access(workspace); access.register(str(workspace))
                expected=store.query(str(workspace),snapshot_id=result['snapshotId'],kind='semantic_fragment',limit=100)['records']
                expected_symbols=store.query(str(workspace),snapshot_id=result['snapshotId'],kind='symbol',limit=100)['records']
            snapshot=workspace/'snapshots'/result['snapshotId']
            before={str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.rglob('*') if p.is_file()}
            shutil.rmtree(repo)
            requests=[{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':{'workspace_id':result['workspaceId'],'snapshot_id':result['snapshotId'],'kind':'semantic_fragment','limit':100}}},
                      {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'ontology_pipeline_status','arguments':{'workspace_id':result['workspaceId']}}},
                      {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':{'workspace_id':result['workspaceId'],'snapshot_id':result['snapshotId'],'kind':'symbol','limit':100}}}]
            proc=subprocess.run([sys.executable,str(ROOT/'mcp/server.py')],input=''.join(json.dumps(r)+'\n' for r in requests),text=True,capture_output=True,env=env,check=True)
            responses=[json.loads(line)['result'] for line in proc.stdout.splitlines()]
            self.assertTrue(all(not r['isError'] for r in responses),responses)
            data=responses[0]['structuredContent']; rows=data['data']['records']
            self.assertEqual(rows,expected)
            symbols=responses[2]['structuredContent']['data']['records']
            self.assertEqual(symbols,expected_symbols)
            types=[r for r in symbols if 'constructorInventory' in r]
            self.assertEqual(len(types),3)
            self.assertEqual({r['name']:r['constructorInventory']['detectedBoundedConstructors'] for r in types},
                             {'Sample':1,'Hidden':1,'Malformed':0})
            self.assertTrue(all(r['constructorInventory']['wholeJavaDeclarationDenominator']=='UNKNOWN' and
                                r['constructorInventory']['modeledConstructorBodies']==0 and
                                r['constructorInventory']['sourceDigest']==r['sourceDigest'] for r in types))
            self.assertEqual(data['snapshotId'],result['snapshotId'])
            self.assertEqual(responses[1]['structuredContent']['data']['sourceAccess'],'not_read')
            selected=[r for r in rows if r.get('category')=='return']
            self.assertEqual({r['path']:len(bindings(r)) for r in selected},{'Safe.java':1,'Hidden.java':0,'Malformed.java':0})
            self.assertTrue(all(c['actualTargetJdk']=='UNKNOWN' for r in rows for c in r.get('platformTypeContracts',[])))
            after={str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.rglob('*') if p.is_file()}
            self.assertEqual(before,after)


if __name__ == '__main__':
    unittest.main()
