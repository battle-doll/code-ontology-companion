"""Finite API composition over authored neutral Java text; never executes Java."""
import copy
from contextlib import closing
import hashlib
import json
import sqlite3
import shutil
from pathlib import Path
import unittest

from test_policy_java_contracts import extract, returns, bindings, core, pipeline_java, policy_semantics
from test_policy_literal_review import reviewed, occurrence

api=policy_semantics.policy_java_contracts
platform=api.policy_java_platform
IMPORT='import java.util.Comparator; '
SPRING='import org.springframework.http.ResponseEntity; '


def source(expression='Comparator.comparingInt(Entry::rank)', methods='int rank(){return 0;} String label(){return null;}', extra='', prefix=IMPORT):
    return prefix+'class Entry {'+methods+'} class Rules {'+extra+' Object f(){return '+expression+';}}'


def analyzed(text, others=None, literal_review=None):
    rows,facts=extract(text,others)
    if literal_review is not None:
        index=core.build_java_index({'Rules.java':text,**(others or {})})
        rows=policy_semantics.extract_semantics(text,'Java','Rules.java',hashlib.sha256(text.encode()).hexdigest(),
            java_type_context=pipeline_java.semantic_type_context(facts,index),literal_review=literal_review)
    providers={r['id']:r for r in facts['records']}
    policy_semantics.finalize_dependencies(rows,lookup=lambda identity,path:providers.get(identity))
    return rows,facts


def target(rows):
    return returns(rows)[-1]


def contracts(row):
    return [n for n,c in bindings(row) if c['declaringType'] in {api.COMPARATOR,api.RESPONSE,api.HEADERS}]


def reason(row,facts):
    providers={r['id']:r for r in facts['records']}
    return api.validate_composition(row['expression'],row,lookup=lambda identity,path:providers.get(identity))


class C29ApiCompositionContractTests(unittest.TestCase):
    def test_exact_primitive_method_reference_factories_and_tiebreakers(self):
        for suffix,kind in [('Int','int'),('Long','long'),('Double','double')]:
            text=source('Comparator.comparing'+suffix+'(Entry::rank).thenComparing'+suffix+'(Entry::rank)',kind+' rank(){return 0;}')
            rows,facts=analyzed(text);row=target(rows)
            self.assertEqual(len(contracts(row)),2);self.assertIsNone(reason(row,facts))
            self.assertEqual([k['keyType'] for k in row['expression']['staticContract']['orderingContract']['keys']],[kind,kind])
        for kind in ['short','long','Integer','Number','Object']:
            with self.subTest(kind=kind):self.assertFalse(contracts(target(analyzed(source(methods=kind+' rank(){return null;}'))[0])))

    def test_finite_comparable_self_table_and_natural_ties(self):
        for kind in ['java.lang.String','java.math.BigDecimal','java.time.Instant','java.lang.Integer','java.lang.Long','java.lang.Double']:
            rows,facts=analyzed(source('Comparator.comparing(Entry::rank)',kind+' rank(){return null;}'))
            row=target(rows);self.assertEqual(len(contracts(row)),1);self.assertIsNone(reason(row,facts))
            order=row['expression']['staticContract']['orderingContract']
            self.assertEqual(order['keys'][0]['keyType'],kind)
            self.assertEqual(order['tiePredicate'],'all_previous_key_comparisons_return_zero')
        self.assertEqual(next(c for c in api.COMPARABLE_TYPES if c['qualifiedName']==api.BD)['objectEquality'],'may_differ_from_equals')
        for kind,extra in [('Number',''),('Comparable',''),('java.time.LocalDate',''),('Key','class Key implements Comparable<Key>{public int compareTo(Key x){return 0;}}'),('Choice','enum Choice{A,B}')]:
            self.assertFalse(contracts(target(analyzed(extra+source('Comparator.comparing(Entry::rank)',kind+' rank(){return null;}'))[0])))

    def test_typed_and_receiver_typed_lambda_signature_only(self):
        for expression in ['Comparator.comparingInt((Entry x)->x.rank())',
                'Comparator.comparingInt(Entry::rank).thenComparing(x->x.label())']:
            rows,facts=analyzed(source(expression));row=target(rows)
            self.assertTrue(contracts(row));self.assertIsNone(reason(row,facts))
            self.assertEqual(row['expression']['staticContract']['callbackBinding']['javaTypeCheckSuccess'],'UNKNOWN')
        for expression in ['Comparator.comparingInt(x->x.rank())','Comparator.comparingInt((Entry x)->{return x.rank();})',
                'Comparator.comparingInt((Entry x,Entry y)->x.rank())','Comparator.comparingInt((Entry x)->other.rank())',
                'Comparator.comparingInt((Entry x)->(Entry y)->y.rank())']:
            self.assertFalse(contracts(target(analyzed(source(expression))[0])))

    def test_method_reference_binding_shape_negative_neighbors(self):
        variants=['static int rank(){return 0;}','int rank(int x){return 0;}','int rank(int... x){return 0;}',
            '<T> int rank(){return 0;}','int rank(){return 0;} int rank(int x){return 0;}',
            'private int rank(){return 0;}','abstract int rank();']
        for methods in variants:
            self.assertFalse(contracts(target(analyzed(source(methods=methods))[0])),methods)
        for expression in ['Comparator.comparingInt(value::rank)','Comparator.comparingInt(Entry::new)','Comparator.comparingInt(this::rank)']:
            self.assertFalse(contracts(target(analyzed(source(expression,extra='Entry value;'))[0])))
        self.assertFalse(contracts(target(analyzed(source().replace('class Entry {','class Base {int rank(){return 0;}} class Entry extends Base {'))[0])))

    def test_callback_source_range_unicode_coordinates(self):
        text='/* 한글 😀 */ '+source('Comparator.comparingInt((Entry item)->item.rank())')
        rows,facts=analyzed(text);row=target(rows);binding=row['expression']['staticContract']['callbackBinding']
        bounds=binding['sourceRange'];self.assertEqual(text[bounds['charStart']:bounds['charEnd']],'(Entry item)->item.rank()')
        parameter=binding['parameterRange'];self.assertEqual(text[parameter['charStart']:parameter['charEnd']],'Entry item')
        changed=copy.deepcopy(row);changed['expression']['staticContract']['callbackBinding']['sourceRange']['charStart']+=1
        self.assertIsNotNone(reason(changed,facts))

    def test_then_and_reversed_priority_boundaries(self):
        for expression,directions in [('Comparator.comparingInt(Entry::rank).thenComparing(Entry::label).reversed()',['reverse','reverse']),
                ('Comparator.comparingInt(Entry::rank).reversed().thenComparing(Entry::label)',['reverse','forward']),
                ('Comparator.comparingInt(Entry::rank).reversed().reversed()',['forward'])]:
            rows,facts=analyzed(source(expression));row=target(rows);order=row['expression']['staticContract']['orderingContract']
            self.assertEqual([k['direction'] for k in order['keys']],directions)
            self.assertEqual([k['priority'] for k in order['keys']],list(range(len(directions))))
            self.assertIsNone(reason(row,facts))
            changed=copy.deepcopy(row);changed['expression']['staticContract']['orderingContract']['keys'][0]['direction']='invalid'
            self.assertIsNotNone(reason(changed,facts))

    def test_unknown_comparator_links_preserve_denominator(self):
        for expression in ['Comparator.comparingInt(Entry::rank).thenComparing(other).reversed()',
                'Comparator.comparing(Entry::label,other).reversed()',
                'Comparator.comparingInt(Entry::rank).unknown().reversed()']:
            row=target(analyzed(source(expression,extra='Comparator<Entry> other;'))[0])
            self.assertNotIn('staticContract',row['expression']);self.assertEqual(row['representationStatus'],'partial')
            self.assertIn('call_semantics_unresolved',row['unsupportedReasons'])

    def test_shadow_import_member_inheritance_and_fqn_veto(self):
        cases=[(source(extra='Object Comparator;'),None),
            (source().replace('Object f(){','Object f(Object Comparator){'),None),
            (source().replace('class Rules {','class Rules<Comparator> {'),None),
            (source(extra='class Comparator {}'),None),
            (source().replace('import java.util.Comparator;','import custom.Comparator;'),None),
            (source().replace('Comparator.comparingInt','comparingInt').replace(IMPORT,'import static java.util.Comparator.comparingInt;'),None),
            (source(),{'Comparator.java':'package java.util; public class Comparator{}'}),
            (source('Comparator.comparing(Entry::label)'),{'String.java':'package java.lang;public class String{}'}),
            (source().replace('class Rules {','class Rules extends Missing {'),None)]
        for text,others in cases:
            with self.subTest(text=text):self.assertFalse(contracts(target(analyzed(text,others)[0])))
        with self.assertRaises(core.DuplicateDeclarationError):
            analyzed(source(),{'Other.java':'class Entry{}'})

    def test_spring_builder_public_status_and_inherited_build(self):
        for factory,code in [('badRequest',400),('notFound',404)]:
            rows,facts=analyzed(SPRING+'class Rules { Object f(){return ResponseEntity.'+factory+'().build();}}')
            row=target(rows);node=row['expression'];contract=node['staticContract']
            self.assertEqual(contract['responseStatusContract']['statusCode'],code);self.assertIsNone(reason(row,facts))
            self.assertEqual(contract['responseStatusContract']['responseDelivery'],'UNKNOWN')
            entry=next(c for c in row['standardApiContracts'] if c['method']=='build')
            self.assertEqual(entry['declaringType'],api.HEADERS)
            self.assertEqual(entry['libraryProvenance']['actualTargetVersion'],'UNKNOWN')
            self.assertEqual('receiverBridge' in contract,factory=='badRequest')
            if factory=='badRequest':self.assertEqual(contract['operands'][0]['actualType'],api.BODY)
        text=SPRING+'class Rules {Object f(){return ResponseEntity.badRequest().build();}}'
        self.assertFalse(contracts(target(analyzed(text,{'ResponseEntity.java':'package org.springframework.http;public class ResponseEntity{}'})[0])))

    def test_spring_status_argument_privacy_and_overload_unknown(self):
        text=SPRING+'class Rules {Object f(){return ResponseEntity.status(409).build();}}'
        rows,facts=analyzed(text);row=target(rows)
        self.assertEqual(len(contracts(row)),2)
        self.assertEqual(row['expression']['staticContract']['responseStatusContract']['statusArgumentReview'],'not_applicable')
        self.assertIsNone(reason(row,facts))
        for field,value in [('type','floating'),('value','2147483648'),('value',True),('javaSuffix','L'),('op','masked_value')]:
            changed=copy.deepcopy(row);changed['expression']['callee']['receiver']['arguments'][0][field]=value
            self.assertIsNotNone(reason(changed,facts),field)
        changed=copy.deepcopy(row);changed['expression']['callee']['receiver']['arguments'][0].pop('staticType')
        self.assertIsNotNone(reason(changed,facts))
        review,digest=reviewed(text,[occurrence(text,'409')]);rows,facts=analyzed(text,literal_review=review)
        self.assertEqual(len(contracts(target(rows))),2)
        self.assertEqual(review.coverage()['entries'][0]['reason'],'token_not_quoted_literal')
        rows,facts=analyzed(SPRING+'class Rules {Object f(int code){return ResponseEntity.status(code).build();}}')
        row=target(rows);self.assertEqual(len(contracts(row)),2);self.assertIsNone(reason(row,facts))
        for node in contracts(row):
            contract=node['staticContract']['responseStatusContract']
            self.assertIsNone(contract['statusCode']);self.assertEqual(contract['statusArgumentValue'],'UNKNOWN')
            self.assertNotIn('409',json.dumps(contract))
        changed=copy.deepcopy(row);inner=changed['expression']['callee']['receiver'];inner['arguments'][0].pop('staticType')
        self.assertIsNotNone(reason(changed,facts))
        for type_name in ['int','org.springframework.http.HttpStatusCode']:
            row=target(analyzed(SPRING+'class Rules {Object f('+type_name+' code){return ResponseEntity.status(code).build();}}')[0])
            self.assertEqual(len(contracts(row)),2)
        row=target(analyzed(SPRING+'class Rules {Object f(Object code){return ResponseEntity.status(code);}}')[0]);self.assertFalse(contracts(row))
        for expression in ['2147483648','1234567890123','409L','409.0','true','"409"']:
            row=target(analyzed(SPRING+'class Rules {Object f(){return ResponseEntity.status('+expression+').build();}}')[0])
            self.assertFalse(contracts(row),expression)
        self.assertFalse(contracts(target(analyzed(SPRING+'class Rules{Object password(){return ResponseEntity.status(409).build();}}')[0])))

    def test_status_and_comparator_no_initializer_substitution(self):
        row=target(analyzed(source('prior.reversed()',extra='Comparator<Entry> prior=Comparator.comparingInt(Entry::rank);'))[0])
        self.assertFalse(contracts(row))
        text=SPRING+'class Rules {ResponseEntity.BodyBuilder prior=ResponseEntity.badRequest(); Object f(){return prior.build();}}'
        row=target(analyzed(text)[0]);status=row['expression']['staticContract']['responseStatusContract']
        self.assertEqual(status['statusOrigin'],'unproven_builder');self.assertIsNone(status['statusCode'])

    def test_callback_and_derived_metadata_forgery_revocation(self):
        rows,facts=analyzed(source());row=target(rows)
        for path,key,value in [('callbackBinding','schemaVersion',2),('callbackBinding','inputType','Other'),
                ('callbackBinding','runtimeDispatch','executed'),('orderingContract','capability','unknown'),
                ('orderingContract','schemaVersion',True),('orderingContract','receiverPointer','/bogus')]:
            changed=copy.deepcopy(row);changed['expression']['staticContract'][path][key]=value
            self.assertIsNotNone(reason(changed,facts))
        for key in list(row['expression']['staticContract']['callbackBinding']):
            changed=copy.deepcopy(row);del changed['expression']['staticContract']['callbackBinding'][key]
            self.assertIsNotNone(reason(changed,facts),key)
        changed=copy.deepcopy(row);changed['standardApiContracts'][0]['rules']['keyDirection']='reverse';self.assertIsNotNone(reason(changed,facts))
        changed=copy.deepcopy(row);del changed['expression']['staticContract'];self.assertIsNotNone(reason(changed,facts))

    def test_independent_siblings_survive_c29_dependency_failure(self):
        rows,facts=analyzed(source('flag ? Comparator.comparingInt(Entry::rank) : Math.abs(n)',extra='boolean flag; int n;'))
        row=target(rows);self.assertTrue(any(c['method']=='abs' for c in row['standardApiContracts']))
        facts['records']=[r for r in facts['records'] if r.get('name')!='rank']
        providers={r['id']:r for r in facts['records']}
        policy_semantics.finalize_dependencies(rows,lookup=lambda i,p:providers.get(i))
        self.assertEqual([c['method'] for c in target(rows).get('standardApiContracts',[])],['abs'])

    def test_c29_budget_boundaries_and_omitted_denominator(self):
        for count in [63,64,65]:
            text=source(methods=' '.join('int m'+str(i)+'(){return 0;}' for i in range(count)),expression='Comparator.comparingInt(Entry::m0)')
            rows,facts=analyzed(text);inventory=next(r['callbackMemberInventory'] for r in facts['records'] if r.get('name')=='Entry')
            self.assertEqual(inventory['detectedDeclarations'],count);self.assertEqual(inventory['omittedDeclarations'],max(0,count-64))
            self.assertLessEqual(len(inventory['declarationIds']),64)
            if count>64:self.assertEqual(inventory['status'],'UNKNOWN');self.assertFalse(contracts(target(rows)))
        rows,facts=analyzed(source('Comparator.comparingInt(Entry::rank)'+'.thenComparingInt(Entry::rank)'*16))
        self.assertNotIn('staticContract',target(rows)['expression'])

    def test_c29_baseline_ids_ranges_calls_and_entry_bytes(self):
        # Baseline signatures/rules are covered by existing catalog tests; this
        # independent finite count excludes only the new C29 owners.
        entries={api._catalog_entry(owner,name,static,e)['id']:api._catalog_entry(owner,name,static,e)
            for (owner,name,static),values in api.CONTRACTS.items() for e in values if owner not in {api.COMPARATOR,api.RESPONSE,api.BODY,api.HEADERS}}
        self.assertEqual(len(entries),83)
        text=source();first=analyzed(text);second=analyzed(text)
        self.assertEqual([(r['id'],r.get('sourceRange'),r.get('sourceDigest')) for r in first[1]['records']],
            [(r['id'],r.get('sourceRange'),r.get('sourceDigest')) for r in second[1]['records']])
        self.assertFalse(any(r.get('relation')=='CALLS' and r.get('resolution')=='exact' and r.get('name')=='rank' for r in first[1]['records']))

    def test_c29_enum_and_record_consumers_preserved(self):
        text=IMPORT+'record Entry(int rank,String label){} class Rules{Object f(){return Comparator.comparingInt(Entry::rank).thenComparing(Entry::label);}}'
        rows,facts=analyzed(text);row=target(rows)
        self.assertEqual(len(contracts(row)),2);self.assertIsNone(reason(row,facts))
        self.assertEqual(row['expression']['staticContract']['callbackBinding']['declarationEvidence']['evidenceKind'],'existing_record_component_accessor')
        self.assertFalse(contracts(target(analyzed('enum Key{A,B} '+source('Comparator.comparing(Entry::rank)','Key rank(){return null;}'))[0])))

    def test_c29_capability_profile_consumer_matrix(self):
        rows,facts=analyzed(source());row=target(rows);self.assertIsNone(reason(row,facts))
        for capability in [None,'java-comparator-ordering-2']:
            changed=copy.deepcopy(row);changed['expression']['staticContract']['orderingContract']['capability']=capability
            self.assertIsNotNone(reason(changed,facts))
        rows,facts=analyzed(SPRING+'class Rules{Object f(){return ResponseEntity.badRequest().build();}}')
        node=target(rows)['expression'];entry=next(c for c in target(rows)['standardApiContracts'] if c['method']=='build')
        self.assertNotEqual(node['staticContract']['operands'][0]['actualType'],entry['declaringType'])
        self.assertTrue(api.validate_receiver_bridge(node['staticContract']['receiverBridge'],receiver_type=node['callee']['receiver']['staticType'],catalog_entry=entry,method='build',static=False,arguments=[]))

    def test_c29_five_language_contract_documentation_parity(self):
        root=Path(__file__).resolve().parents[1]/'docs'
        for relative in ['QUALITY_0_9_3.md','ko/QUALITY_0_9_3.md','ja/QUALITY_0_9_3.md','zh-CN/QUALITY_0_9_3.md','ru/QUALITY_0_9_3.md']:
            text=(root/relative).read_text(encoding='utf-8')
            for required in ['java-comparator-ordering-1','spring-response-status-1','6.2.12','UNKNOWN','BigDecimal','Instant','callbackDeclaration']:
                self.assertIn(required,text,relative)

    def test_callback_provider_static_varargs_generic_access_and_overload_neighbors(self):
        self.test_method_reference_binding_shape_negative_neighbors()
        rows,facts=analyzed(source());provider=next(r for r in facts['records'] if r.get('name')=='rank')
        self.assertEqual(provider['callbackDeclaration']['invocationKind'],'instance')
        self.assertEqual(provider['callbackDeclaration']['access'],'package')

    def test_callback_provider_inventory_missing_duplicate_mutated_records_fail_closed(self):
        rows,facts=analyzed(source());row=target(rows)
        for field,value in [('invocationKind','static'),('varargs',True),('generic',True),('access','private'),('hasBody',False),('declarationValidity','UNKNOWN')]:
            changed=copy.deepcopy(facts);provider=next(r for r in changed['records'] if r.get('name')=='rank')
            provider['callbackDeclaration'][field]=value;self.assertIsNotNone(reason(row,changed),field)
        changed=copy.deepcopy(facts);provider=next(r for r in changed['records'] if r.get('name')=='rank')
        provider['callbackDeclaration']['headerRange']['charStart']+=1;self.assertIsNotNone(reason(row,changed))
        for name in ['rank','label']:
            changed=copy.deepcopy(facts);changed['records']=[r for r in changed['records'] if r.get('name')!=name]
            self.assertIsNotNone(reason(row,changed))
        changed=copy.deepcopy(facts);owner=next(r for r in changed['records'] if r.get('name')=='Entry')
        owner['callbackMemberInventory']['declarationIds']*=2;self.assertIsNotNone(reason(row,changed))

    def test_callback_provider_shapes_survive_existing_raw_readers(self):
        rows,facts=analyzed(source());roundtrip=json.loads(json.dumps({'rows':rows,'facts':facts}))
        self.assertEqual(roundtrip['facts']['records'],facts['records']);self.assertIsNone(reason(target(roundtrip['rows']),roundtrip['facts']))

    def test_callback_provider_digests_change_without_source_ids_or_calls_changes(self):
        rows,facts=analyzed(source());provider=next(r for r in facts['records'] if r.get('name')=='rank')
        old=copy.deepcopy(provider);old.pop('callbackDeclaration')
        self.assertEqual(old['id'],provider['id']);self.assertEqual(old['sourceDigest'],provider['sourceDigest'])
        self.assertEqual(old['sourceRange'],provider['sourceRange']);self.assertNotEqual(platform.canonical(old),platform.canonical(provider))

    def test_c29_html_raw_detail_preserves_optional_fields_and_char_ranges(self):
        import pipeline_html as view
        rows,facts=analyzed('/* 한글 😀 */ '+source())
        records=[{**r,'kind':'semantic_fragment'} for r in rows['fragments']]+facts['records']
        raw,script=view._raw_page(records,'ps-neutral-c29')
        self.assertEqual(json.loads(raw),{'schemaVersion':1,'snapshotId':'ps-neutral-c29','records':records})
        self.assertNotIn('</script>',script)
        with closing(sqlite3.connect(':memory:')) as db, db:
            db.execute('CREATE TABLE records(id TEXT,payload TEXT)')
            for row in records:
                for locale in view.LANGUAGES:
                    detail=view._record_html(row,db,view.TRANSLATIONS[locale])
                    self.assertIn('sourceDigest',detail)
                    if row.get('callbackDeclaration'):self.assertIn('callbackDeclaration',detail)
                    if row.get('callbackTypeNamespace'):self.assertIn('callbackTypeNamespace',detail)
                    if row.get('standardApiContracts'):self.assertIn('orderingContract',detail);self.assertIn('charStart',detail)

    def test_c29_html_graph_preserves_declared_projection_without_fabricated_edges(self):
        import pipeline_html as view
        rows,facts=analyzed(source());records=facts['records']+[{**r,'kind':'semantic_fragment'} for r in rows['fragments']]
        previous=copy.deepcopy(records)
        for row in previous:
            row.pop('callbackDeclaration',None);row.pop('callbackMemberInventory',None);row.pop('callbackTypeNamespace',None)
            if 'expression' in row:
                for node,path in api._syntax_nodes(row['expression']):
                    if 'staticContract' in node:node.pop('staticContract');node.pop('staticType',None)
        def graph(values):
            with closing(sqlite3.connect(':memory:')) as db, db:
                db.execute('CREATE TABLE records(id TEXT,payload TEXT)')
                db.executemany('INSERT INTO records VALUES (?,?)',[(r['id'],json.dumps(r)) for r in values])
                return view._graph_document(values,db,{'snapshotId':'ps-neutral-c29'})
        self.assertEqual(graph(records),graph(previous))

    def test_c29_source_bundle_sqlite_retains_record_metadata(self):
        from test_semantic_delivery import SemanticDeliveryTests,store,exporter,view
        fixture=SemanticDeliveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        text=source('Comparator.<Entry,String>comparing(Entry::label)',extra='Object response(){return ResponseEntity.badRequest().build();}',prefix=IMPORT+SPRING)
        (fixture.repo/'Rules.java').write_text(text,encoding='utf-8')
        initialized=fixture.initialize();snapshot=initialized['snapshotId']
        expected=list(store.iter_records(fixture.workspace,snapshot));shutil.rmtree(fixture.repo)
        destination=fixture.root/'portable';exporter.export_bundle(fixture.workspace,snapshot,destination)
        with closing(sqlite3.connect(destination/'knowledge.sqlite')) as db, db:
            actual=[json.loads(row[0]) for row in db.execute('SELECT payload FROM records ORDER BY id')]
        self.assertEqual(sorted(expected,key=lambda r:r['id']),actual)
        relevant=[r for r in actual if r.get('standardApiContracts')]
        self.assertTrue(any('orderingContract' in json.dumps(r) for r in relevant))
        self.assertTrue(any('responseStatusContract' in json.dumps(r) for r in relevant))
        self.assertTrue(any('callbackDeclaration' in r for r in actual))
        self.assertTrue(any('callbackTypeNamespace' in r for r in actual))
        output=fixture.root/'html';view.render_pipeline(fixture.workspace,snapshot,output,include_maps=False)
        delivered=[r for file in (output/'data').glob('*.json') for r in json.loads(file.read_text(encoding='utf-8'))['records']]
        self.assertEqual(sorted(expected,key=lambda r:r['id']),sorted(delivered,key=lambda r:r['id']))
        for locale in view.LANGUAGES:self.assertTrue((output/locale/'index.html').is_file())

    def test_c29_capability_interpretation_is_separate_from_raw_html_sqlite(self):
        from test_pipeline_delivery import restore
        import pipeline_delivery as delivery
        rows,facts=analyzed(source());row={**target(rows),'kind':'semantic_fragment'}
        projected=delivery.normalize_response({'status':'ok','snapshotId':'ps-neutral-c29','data':{'records':[row]}})
        delivered=projected['data']['records'][0]
        for key,value in list(delivered.items()):
            if isinstance(value,dict) and value.get('format')=='companion.flat-json.v1':delivered[key]=restore(value)
        self.assertEqual(delivered,row);self.assertIsNone(reason(delivered,facts))
        delivered['expression']['staticContract']['orderingContract']['schemaVersion']=99
        self.assertIsNotNone(reason(delivered,facts))
        self.assertEqual(delivered['representationStatus'],'partial');self.assertFalse(delivered['businessMeaningVerified'])

    def test_explicit_comparator_type_arguments_bind_exact_T_U_and_arity(self):
        prefix=IMPORT+'class Other {} '
        for suffix,kind in [('Int','int'),('Long','long'),('Double','double')]:
            for callback in ['Entry::rank','(Entry x)->x.rank()','x->x.rank()']:
                expression='Comparator.<Entry>comparing'+suffix+'('+callback+')'
                rows,facts=analyzed(source(expression,kind+' rank(){return 0;}',prefix=prefix))
                self.assertEqual(len(contracts(target(rows))),1,expression);self.assertIsNone(reason(target(rows),facts))
                for argument in ['Other','Entry,Other','Entry<?>']:
                    bad=expression.replace('<Entry>','<'+argument+'>')
                    self.assertFalse(contracts(target(analyzed(source(bad,kind+' rank(){return 0;}',prefix=prefix))[0])),bad)
        for callback in ['Entry::label','(Entry x)->x.label()','x->x.label()']:
            for arguments,count in [('Entry,String',1),('Entry,java.lang.String',1),('Other,String',0),
                    ('Entry,java.time.Instant',0),('Entry',0),('Entry,String,Other',0),('Entry,String[]',0)]:
                expression='Comparator.<'+arguments+'>comparing('+callback+')'
                rows,facts=analyzed(source(expression,prefix=prefix));self.assertEqual(len(contracts(target(rows))),count,expression)
                self.assertIsNone(reason(target(rows),facts))

    def test_explicit_type_argument_unknowns_preserve_proven_receiver_and_denominator(self):
        for arguments,count in [('String',2),('java.lang.String',2),('java.time.Instant',1),('Entry,String',1),('Missing',1)]:
            expression='Comparator.comparingInt(Entry::rank).<'+arguments+'>thenComparing(Entry::label)'
            rows,facts=analyzed(source(expression));row=target(rows)
            self.assertEqual(len(contracts(row)),count,expression);self.assertIsNone(reason(row,facts))
            self.assertEqual(row['representationStatus'],'partial')
            if count==1:self.assertNotIn('staticContract',row['expression'])
        for ending in ['.<String>thenComparingInt(Entry::rank)','.<String>reversed()']:
            row=target(analyzed(source('Comparator.comparingInt(Entry::rank)'+ending))[0])
            self.assertNotIn('staticContract',row['expression']);self.assertEqual(len(contracts(row)),1)
        text=source('Comparator.<Entry,T>comparing(Entry::label)').replace('class Rules {','class Rules<T> {')
        self.assertFalse(contracts(target(analyzed(text)[0])))

    def test_typed_lambda_type_namespace_ignores_value_names_but_methodref_does_not(self):
        for value_kind in ['parameter','field','local']:
            for callback,count in [('(Entry x)->x.rank()',1),('Entry::rank',0)]:
                text=source('Comparator.comparingInt('+callback+')')
                if value_kind=='parameter':text=text.replace('Object f(){','Object f(Entry Entry){')
                elif value_kind=='field':text=text.replace('class Rules {','class Rules {Entry Entry;')
                else:text=text.replace('Object f(){','Object f(){Entry Entry=null;')
                rows,facts=analyzed(text);row=target(rows)
                self.assertEqual(len(contracts(row)),count,(value_kind,callback));self.assertIsNone(reason(row,facts))
        for declaration in ['class Rules<Entry> {','class Rules {class Entry {}']:
            text=source('Comparator.comparingInt((Entry x)->x.rank())').replace('class Rules {',declaration)
            self.assertFalse(contracts(target(analyzed(text)[0])))

    def test_explicit_type_argument_and_namespace_consumer_mutations_fail_closed(self):
        rows,facts=analyzed(source('Comparator.<Entry>comparingInt(Entry::rank)',prefix=IMPORT+'class Other {} '))
        for arguments in [['Other'],['Entry','Other'],[],['Entry<?>']]:
            changed=copy.deepcopy(rows);row=target(changed);row['expression']['callee']['typeArguments']=arguments
            self.assertIsNotNone(reason(row,facts),arguments)
            providers={r['id']:r for r in facts['records']}
            policy_semantics.finalize_dependencies(changed,lookup=lambda i,p:providers.get(i))
            self.assertFalse(contracts(target(changed)))
        rows,facts=analyzed(source('Comparator.<Entry,String>comparing(Entry::label)'))
        changed=copy.deepcopy(target(rows));changed['expression']['callee']['typeArguments']=['Entry','java.time.Instant']
        self.assertIsNotNone(reason(changed,facts))
        text=source('Comparator.comparingInt((Entry x)->x.rank())',extra='Entry Entry;')
        rows,facts=analyzed(text);changed=copy.deepcopy(target(rows))
        changed['expression']['staticContract']['callbackBinding']['form']='unbound_instance_method_reference'
        self.assertIsNotNone(reason(changed,facts))

    def test_explicit_type_context_fqn_positive_and_member_shadow_negative_pairs(self):
        base='package demo; '+IMPORT+'class Entry {int rank(){return 0;} java.lang.String label(){return null;}} '
        for member,method,good,bad,getter in [('Entry','comparingInt','demo.Entry','Entry','rank'),
                ('String','comparing','demo.Entry,java.lang.String','demo.Entry,String','label')]:
            for arguments,count in [(good,1),(bad,0)]:
                text=base+'class Rules {class '+member+'{} Object f(){return Comparator.<'+arguments+'>'+method+'(demo.Entry::'+getter+');}}'
                rows,facts=analyzed(text);row=target(rows)
                self.assertEqual(len(contracts(row)),count,(member,arguments));self.assertIsNone(reason(row,facts))
        text=base+'class String{} class Rules {Object f(){return Comparator.<demo.Entry,java.lang.String>comparing(demo.Entry::label);}}'
        rows,facts=analyzed(text);row=target(rows);self.assertEqual(len(contracts(row)),1)
        changed=copy.deepcopy(row);changed['expression']['callee']['typeArguments']=['demo','.','Entry',',','String']
        self.assertIsNotNone(reason(changed,facts))

    def test_explicit_type_context_delivered_T_U_mutations_are_withdrawn(self):
        base='package demo; '+IMPORT+'class Entry {int rank(){return 0;} java.lang.String label(){return null;}} '
        cases=[('class Rules {class Entry{} Object f(){return Comparator.<demo.Entry>comparingInt(demo.Entry::rank);}}',['Entry']),
            ('class Rules {class String{} Object f(){return Comparator.<demo.Entry,java.lang.String>comparing(demo.Entry::label);}}',['demo','.','Entry',',','String']),
            ('class Rules {class String{} Object f(){return Comparator.comparingInt(demo.Entry::rank).<java.lang.String>thenComparing(demo.Entry::label);}}',['String'])]
        for tail,arguments in cases:
            rows,facts=analyzed(base+tail);changed=copy.deepcopy(rows);row=target(changed)
            before=len(contracts(row));self.assertGreater(before,0)
            row['expression']['callee']['typeArguments']=arguments
            self.assertIsNotNone(reason(row,facts));providers={r['id']:r for r in facts['records']}
            policy_semantics.finalize_dependencies(changed,lookup=lambda i,p:providers.get(i))
            self.assertEqual(len(contracts(target(changed))),before-1)
            self.assertEqual(target(changed)['representationStatus'],'partial')

    def test_explicit_type_context_enclosing_local_type_variable_and_value_names(self):
        base='package demo; '+IMPORT+'class Entry {int rank(){return 0;} java.lang.String label(){return null;}} '
        expression='Comparator.<demo.Entry,java.lang.String>comparing(demo.Entry::label)'
        for tail in ['class Outer {class String{} class Rules {Object f(){return '+expression+';}}}',
                'class Rules {Object g(){class String{} return null;} Object f(){return '+expression+';}}',
                'class Rules<String> {Object f(){return '+expression+';}}']:
            rows,facts=analyzed(base+tail);row=target(rows);self.assertEqual(len(contracts(row)),1,tail)
            changed=copy.deepcopy(row);changed['expression']['callee']['typeArguments']=['demo','.','Entry',',','String']
            self.assertIsNotNone(reason(changed,facts),tail)
        for value in ['Entry Entry;','String String;']:
            text=base+'class Rules {'+value+' Object f(Entry Entry){return Comparator.<Entry,String>comparing((Entry x)->x.label());}}'
            rows,facts=analyzed(text);self.assertEqual(len(contracts(target(rows))),1);self.assertIsNone(reason(target(rows),facts))
        for parent in ['extends java.lang.Object','extends Missing']:
            text=base+'class Rules '+parent+' {Object f(){return '+expression+';}}'
            rows,_=analyzed(text);self.assertFalse(contracts(target(rows)))
        text=base+'class Rules {Object g(){class Local{} return null;} Object f(){return '+expression+';}}'
        _,facts=analyzed(text);owner=next(r for r in facts['records'] if r.get('qualifiedName')=='demo.Rules')
        self.assertEqual(next(d['relation'] for d in owner['callbackTypeNamespace']['declarations'] if d['name']=='Local'),'local_or_nonmember')

    def test_explicit_type_context_missing_tampered_incomplete_over_budget_providers(self):
        rows,facts=analyzed(source('Comparator.<Entry,String>comparing(Entry::label)'));row=target(rows)
        self.assertEqual(len(contracts(row)),1)
        owner_id=row['javaSourceOwner']['typeSymbolId']
        def mutate(change):
            providers=copy.deepcopy({r['id']:r for r in facts['records']});change(providers,providers[owner_id])
            self.assertIsNotNone(api.validate_composition(row['expression'],row,lookup=lambda i,p:providers.get(i)))
        mutate(lambda p,o:o.pop('callbackTypeNamespace'))
        mutate(lambda p,o:o['callbackTypeNamespace'].update(schemaVersion=True))
        mutate(lambda p,o:o['callbackTypeNamespace'].update(detectedDeclarations=True))
        mutate(lambda p,o:o['callbackTypeNamespace'].update(omittedDeclarations=1))
        mutate(lambda p,o:o['callbackTypeNamespace'].update(status='complete-ish'))
        mutate(lambda p,o:o['callbackTypeNamespace'].update(status='UNKNOWN',reason='source_type_namespace_unverified'))
        mutate(lambda p,o:o['callbackTypeNamespace']['declarations'][0]['sourceRange'].update(charStart=9999))
        mutate(lambda p,o:p.pop(o['callbackTypeNamespace']['declarations'][0]['recordId']))
        mutate(lambda p,o:o['callbackTypeNamespace']['declarations'].append(copy.deepcopy(o['callbackTypeNamespace']['declarations'][0])))
        many=' '.join('class Extra'+str(i)+'{}' for i in range(64))
        text=source('Comparator.comparingInt(Entry::rank).<String>thenComparing(Entry::label)',prefix=IMPORT+many)
        result,providers=analyzed(text);self.assertEqual(len(contracts(target(result))),1)
        owner=next(r for r in providers['records'] if r.get('qualifiedName')=='Rules')
        inventory=owner['callbackTypeNamespace'];self.assertEqual(len(inventory['declarations']),64)
        self.assertEqual(inventory['detectedDeclarations'],66);self.assertEqual(inventory['omittedDeclarations'],2)
        self.assertEqual(inventory['status'],'UNKNOWN');self.assertEqual(inventory['reason'],'type_namespace_budget_exceeded')
        self.assertEqual(target(result)['representationStatus'],'partial')
        for extra_count,expected in [(58,2),(59,1)]:
            many=' '.join('class Extra'+str(i)+'{}' for i in range(extra_count))
            text=source('Comparator.comparingInt(Entry::rank).<String>thenComparing(Entry::label)',prefix=IMPORT+many)
            result,_=analyzed(text);self.assertEqual(len(contracts(target(result))),expected)

    def test_explicit_type_context_source_range_joins_and_private_inventory_keys(self):
        text=source('Comparator.<Entry,String>comparing(Entry::label)')
        rows,facts=analyzed(text);row=target(rows);providers={r['id']:r for r in facts['records']}
        for record in facts['records']:
            namespace=record.get('callbackTypeNamespace')
            if namespace:
                self.assertTrue(api.validate_callback_type_namespace(record,lambda i,p:providers.get(i)))
                for declaration in namespace['declarations']:
                    self.assertEqual(declaration['sourceRange'],providers[declaration['recordId']]['sourceRange'])
        self.assertFalse(any(key.startswith('_') for r in facts['records'] for key in r.get('directMemberInventory',{})))
        for locale in ['', 'ko/', 'ja/', 'zh-CN/', 'ru/']:
            text=(Path(__file__).resolve().parents[1]/'docs'/locale/'QUALITY_0_9_3.md').read_text(encoding='utf-8')
            for marker in ['callbackTypeNamespace','/sourceRange','detectedDeclarations','omittedDeclarations','64','62','32 KiB','known_types']:
                self.assertIn(marker,text)
        # Exact old/new source ID/CALLS and catalog byte comparison is separately
        # run against both frozen candidate pins by the author evidence runner.

    def test_explicit_type_context_optional_namespace_raw_reader_parity(self):
        from test_pipeline_delivery import restore
        import pipeline_delivery as delivery
        _,facts=analyzed(source('Comparator.<Entry,String>comparing(Entry::label)'))
        record=next(r for r in facts['records'] if r.get('qualifiedName')=='Rules')
        response=delivery.normalize_response({'status':'ok','snapshotId':'ps-neutral-c29','data':{'records':[record]}})
        actual=response['data']['records'][0]
        for key,value in list(actual.items()):
            if isinstance(value,dict) and value.get('format')=='companion.flat-json.v1':actual[key]=restore(value)
        self.assertEqual(actual,record)
        # The existing source-bundle test exercises the real SQLite exporter;
        # this cell specifically exercises normalized stdio JSON restoration.


    def test_namespace_reverse_membership_rejects_callback_role_overlap_omission(self):
        cases=[('package demo; '+IMPORT+'class String {java.lang.String label(){return null;}} class Rules {Object f(){return Comparator.<demo.String,java.lang.String>comparing(demo.String::label);}}',
                ['demo','.','String',',','String']),
            ('package demo; '+IMPORT+'class Rules {static class String {java.lang.String label(){return null;}} Object f(){return Comparator.<Rules.String,java.lang.String>comparing(Rules.String::label);}}',
                ['Rules','.','String',',','String'])]
        for text,arguments in cases:
            rows,facts=analyzed(text);self.assertEqual(len(contracts(target(rows))),1)
            changed=copy.deepcopy(rows);providers=copy.deepcopy(facts);row=target(changed)
            owner=next(r for r in providers['records'] if r.get('qualifiedName')=='demo.Rules')
            namespace=owner['callbackTypeNamespace']
            namespace['declarations']=[d for d in namespace['declarations'] if d['name']!='String']
            namespace['detectedDeclarations']=len(namespace['declarations'])
            row['expression']['callee']['typeArguments']=arguments
            self.assertIsNotNone(reason(row,providers));lookup={r['id']:r for r in providers['records']}
            policy_semantics.finalize_dependencies(changed,lookup=lambda i,p:lookup.get(i))
            self.assertFalse(contracts(target(changed)));self.assertEqual(target(changed)['representationStatus'],'partial')

    def test_namespace_self_membership_required_and_reordering_preserves_meaning(self):
        rows,facts=analyzed(source('Comparator.<Entry,String>comparing(Entry::label)'));row=target(rows)
        reordered=copy.deepcopy(facts)
        for record in reordered['records']:
            if record.get('callbackTypeNamespace'):record['callbackTypeNamespace']['declarations'].reverse()
        self.assertIsNone(reason(row,reordered))
        changed=copy.deepcopy(facts);owner=next(r for r in changed['records'] if r.get('qualifiedName')=='Rules')
        namespace=owner['callbackTypeNamespace']
        namespace['declarations']=[d for d in namespace['declarations'] if d['recordId']!=owner['id']]
        namespace['detectedDeclarations']=len(namespace['declarations'])
        by_id={r['id']:r for r in changed['records']}
        self.assertFalse(api.validate_callback_type_namespace(owner,lambda i,p:by_id.get(i)))
        self.assertIsNotNone(reason(row,changed))

    def test_namespace_known_type_input_is_bounded_actual_records(self):
        _,facts=analyzed(source('Comparator.<Entry,String>comparing(Entry::label)'))
        providers={r['id']:r for r in facts['records']};owner=next(r for r in providers.values() if r.get('qualifiedName')=='Rules')
        known=[r for r in providers.values() if r.get('type')=='Class'];lookup=lambda i,p:providers.get(i)
        self.assertTrue(api.validate_callback_type_namespace(owner,lookup,known))
        self.assertFalse(api.validate_callback_type_namespace(owner,lookup,[r['id'] for r in known]))
        self.assertFalse(api.validate_callback_type_namespace(owner,lookup,[owner]*65))
        changed=copy.deepcopy(known);changed[0]['sourceDigest']='0'*64
        self.assertFalse(api.validate_callback_type_namespace(owner,lookup,changed))
        bad=copy.deepcopy(owner);bad['callbackTypeNamespace']['declarations'][0]['qualifiedName']='foreign.Type'
        self.assertFalse(api.validate_callback_type_namespace(bad,lookup,known))


if __name__=='__main__':unittest.main()
