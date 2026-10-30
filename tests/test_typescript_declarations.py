"""Neutral declarative TypeScript boundaries and source-free delivery."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from test_pipeline_policy import policy, extract_language, seal_extraction

FUNCTION='function eligible(active: boolean, blocked: boolean): boolean { return active && !blocked; }'

class TypeScriptDeclarationTests(unittest.TestCase):
    def test_class_before_after_and_multiple_preserve_function_program(self):
        original=extract_language(FUNCTION,'TypeScript')['rules'][0]['program']
        for source,count in [('class Model {} '+FUNCTION,1),(FUNCTION+' class Model {}',1),
                ('export class First {} '+FUNCTION+' class Last {}',2)]:
            result=extract_language(source,'TypeScript')
            self.assertEqual(result['rules'][0]['program'],original)
            self.assertEqual(result['coverage']['detectedRules'],1)
            self.assertEqual(result['coverage']['sourceDeclarationCoverage']['detectedDeclarations'],count)
            self.assertTrue(result['coverage']['sourceDeclarationCoverage']['inventoryComplete'])
            self.assertTrue(result['coverage']['complete'])
            self.assertFalse(result['coverage']['businessPolicyComplete'])
            self.assertTrue(all(r['expression']['selection']=='not_a_source_function'for r in result['sourceDeclarations']))

    def test_strict_class_binding_names_never_become_verified_rules(self):
        for name in ("eval", "arguments"):
            for prefix in ("", "export "):
                declaration = prefix + "class " + name + " {}"
                for source in (declaration + " " + FUNCTION, FUNCTION + " " + declaration):
                    with self.subTest(name=name, exported=bool(prefix)):
                        result = extract_language(source, "TypeScript")
                        self.assertFalse(result["rules"])
                        self.assertFalse(result["coverage"]["complete"])
                        self.assertTrue(result["coverage"]["unknownDenominator"])
                        row = result["sourceDeclarations"][0]["expression"]
                        self.assertEqual(row["status"], "unsupported")
                        self.assertIn("unsupported_typescript_class_binding", row["reasons"])
        # These are valid property names, and are not module bindings.
        result = extract_language("class Model {eval: boolean; arguments: string;} " + FUNCTION, "TypeScript")
        self.assertEqual(len(result["rules"]), 1)
        self.assertEqual(result["sourceDeclarations"][0]["expression"]["fieldCount"], 2)

    def test_export_strictness_covers_all_function_bindings_in_source_order(self):
        for name in ("eval", "arguments"):
            functions = [
                "function check(" + name + ": boolean): boolean { return " + name + "; }",
                "function " + name + "(active: boolean): boolean { return active; }",
                "function check(" + name + ": boolean): boolean { return callback(" + name + "); }",
            ]
            for function in functions:
                for source in ("export class Model {} " + function + " " + FUNCTION,
                               function + " " + FUNCTION + " export class Model {}",
                               "class Model {} " + function + " export " + FUNCTION):
                    result = extract_language(source, "TypeScript")
                    self.assertFalse(result["rules"])
                    self.assertFalse(result["coverage"]["complete"])
                    self.assertTrue(result["coverage"]["unknownDenominator"])
                    self.assertIn("unsupported_typescript_strict_binding", result["coverage"]["reasons"])
            # A class declaration alone does not make its enclosing script strict.
            for function in functions[:2]:
                result = extract_language("class Model {} " + function, "TypeScript")
                self.assertEqual(len(result["rules"]), 1)
        result = extract_language("export class Model {eval: boolean; arguments: string;} " + FUNCTION, "TypeScript")
        self.assertEqual(len(result["rules"]), 1)

    def test_unparsed_module_signature_cannot_hide_a_later_strict_binding(self):
        for name in ("eval", "arguments"):
            hidden = "function opaque(x: number, " + name + ": boolean): boolean { return true; } "
            for source in ("export class Model {} " + hidden + FUNCTION,
                           hidden + FUNCTION + " export class Model {}"):
                result = extract_language(source, "TypeScript")
                self.assertFalse(result["rules"])
                self.assertFalse(result["coverage"]["complete"])
                self.assertTrue(result["coverage"]["unknownDenominator"])
                self.assertEqual(result["coverage"]["detectedRules"], 2)
                self.assertEqual(result["coverage"]["unsupportedRules"], 2)
                self.assertIn("typescript_module_header_unverified", result["coverage"]["reasons"])
        # Complete bindings with an unsupported body do not imply syntax invalidity.
        result = extract_language("export class Model {} function opaque(x: boolean): boolean { return callback(x); } " + FUNCTION, "TypeScript")
        self.assertEqual(len(result["rules"]), 1)
        self.assertFalse(result["coverage"]["complete"])

    def test_typed_fields_do_not_become_policy_inputs_or_module_bindings(self):
        result=extract_language('class Model {active: boolean; amount: number; eligible: string;} '+FUNCTION,'TypeScript')
        self.assertEqual([p['name']for p in result['rules'][0]['parameters']],['active','blocked'])
        item=result['sourceDeclarations'][0]
        self.assertEqual(item['expression']['fieldCount'],3)
        self.assertEqual(item['expression']['bodyForm'],'uninitialized_primitive_type_fields')
        self.assertEqual(item['expression']['runtimeSemantics'],'UNKNOWN')
        self.assertEqual(item['extractorVersion'],'source-policy-declarations-1')
        self.assertNotIn('ruleVersion',item)
        self.assertEqual(result['coverage']['analyzedRules'],1)

    def test_duplicate_class_function_and_internal_type_bindings_are_not_ignored(self):
        for prefix in ('class eligible {}','class Model {} class Model {}','class bool {}','class int {}'):
            for source in (prefix+' '+FUNCTION,FUNCTION+' '+prefix):
                result=extract_language(source,'TypeScript')
                self.assertFalse(result['rules'])
                self.assertFalse(result['coverage']['complete'])
                self.assertTrue(result['coverage']['reasons'])
                self.assertTrue(result.get('sourceDeclarations'))

    def test_unsupported_function_name_still_conflicts_with_class(self):
        result=extract_language('class eligible {} function eligible(active: boolean): boolean { return callback(active); } '+
            'function other(active: boolean): boolean { return active; }','TypeScript')
        self.assertFalse(result['rules'])
        self.assertEqual(result['coverage']['detectedRules'],2)
        self.assertIn('ambiguous_typescript_module_binding',result['coverage']['reasons'])

    def test_unsupported_class_shapes_withhold_module_without_exposing_literals(self):
        classes=[
            'class Model {static { execute(); }}','class Model {value: number = 87162345;}',
            'class Model {static value: boolean;}','class Model {check(): boolean{return true;}}',
            'class Model {constructor(){execute();}}','class Model {get value(){return true;}}',
            'class Model {value: string = "HIDDEN_SENTINEL";}','class Model {active: boolean;active: boolean;}',
            'class Model {readonly value: boolean;}','class Model {value: boolean[];}',
            'class Model {value: UnknownType;}','class Model {value?: boolean;}','class Model {[field]: boolean;}',
            'class Model extends factory() {}','class Model implements Shape {}','class Model<T> {}',
            '@decorate class Model {}','const Model = class {};','new Model(); class Model {}',
            'export default class Model {static {execute();}}','export interface Model {}',
            'class Model {class Nested {}}','class Model {value: {active:boolean};}',
        ]
        for declaration in classes:
            with self.subTest(declaration=declaration.split('{')[0]):
                result=extract_language(declaration+' '+FUNCTION,'TypeScript')
                self.assertFalse(result['rules'])
                self.assertFalse(result['coverage']['complete'])
                self.assertTrue(result['coverage']['unknownDenominator'])
                self.assertNotIn('87162345',json.dumps(result));self.assertNotIn('HIDDEN_SENTINEL',json.dumps(result))
                for row in result.get('sourceDeclarations',[]):self.assertEqual(row['expression']['status'],'unsupported')

    def test_unbalanced_boundary_keeps_observed_entry_and_unknown_denominator(self):
        source=FUNCTION+' class Model {active: boolean;'
        result=extract_language(source,'TypeScript')
        self.assertEqual(result['coverage']['detectedRules'],1)
        self.assertEqual(result['coverage']['unsupportedRules'],1)
        self.assertTrue(result['coverage']['unknownDenominator'])
        self.assertEqual(result['sourceDeclarations'][0]['expression']['boundaryStatus'],'UNKNOWN')
        self.assertFalse(result['coverage']['sourceDeclarationCoverage']['inventoryComplete'])

    def test_comment_literal_impostors_and_crlf_positions_are_honest(self):
        source='// class FalseShape {}\r\n/* 한글 😀 */\r\nexport class Model {\r\n active: boolean;\r\n}\r\n'+FUNCTION
        result=extract_language(source,'TypeScript');row=result['sourceDeclarations'][0]
        self.assertEqual(row['span'],{'lineStart':3,'lineEnd':5})
        self.assertEqual(row['sourceDigest'],hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(row['expression']['tokenRange'],{'start':0,'end':9,'unit':'boolean_lexer_token_index','endExclusive':True})
        self.assertNotIn('sourceRange',row)
        poisoned=extract_language('class Model {value: string = "class Fake {}";} '+FUNCTION,'TypeScript')
        self.assertEqual(poisoned['coverage']['sourceDeclarationCoverage']['detectedDeclarations'],1)
        self.assertNotIn('Fake',json.dumps(poisoned))

    def test_declaration_budget_preserves_known_original_denominator(self):
        source='class First {} class Second {} '+FUNCTION
        for limit in (0,1):
            result=extract_language(source,'TypeScript',max_declarations=limit)
            coverage=result['coverage']['sourceDeclarationCoverage']
            self.assertEqual(coverage['detectedDeclarations'],2)
            self.assertEqual(coverage['recordedDeclarations'],limit)
            self.assertEqual(coverage['omittedDeclarations'],2-limit)
            self.assertFalse(coverage['inventoryComplete'])
            self.assertEqual(result['coverage']['detectedRules'],1)
            self.assertFalse(result['coverage']['complete'])
        result=extract_language('class Model {active: boolean = true;} '+FUNCTION,'TypeScript',max_declarations=0)
        self.assertEqual(result['coverage']['sourceDeclarationCoverage']['unsupportedDeclarations'],1)

    def test_declaration_only_scope_is_not_a_complete_business_policy(self):
        result=extract_language('class Model {}','TypeScript')
        self.assertFalse(result['rules']);self.assertEqual(result['coverage']['detectedRules'],0)
        self.assertTrue(result['coverage']['unknownDenominator']);self.assertFalse(result['coverage']['complete'])
        snapshot=seal_extraction(result)
        self.assertEqual(snapshot['coverage']['sourceDeclarationCoverage']['recordedDeclarations'],1)
        self.assertFalse(snapshot['coverage']['businessPolicyComplete'])

    def test_policy_domain_summary_preserves_separate_declaration_counts(self):
        result=extract_language('class Model {} '+FUNCTION,'TypeScript')
        snapshot=seal_extraction(result);summary=policy.list_domain_policies(snapshot)
        self.assertEqual(summary['coverage']['analyzedRules'],1)
        self.assertEqual(summary['coverage']['sourceDeclarationCoverage']['detectedDeclarations'],1)
        self.assertEqual(sum(d['ruleCount']for d in summary['domains']),1)

    def test_sensitive_identifiers_and_private_literals_do_not_enter_observation(self):
        for declaration in ('class SecretModel {}','class Model {password: string;}','class Model {value: string = "HIDDEN_SENTINEL";}'):
            result=extract_language(declaration+' '+FUNCTION,'TypeScript')
            encoded=json.dumps(result)
            self.assertNotIn('SecretModel',encoded);self.assertNotIn('password',encoded);self.assertNotIn('HIDDEN_SENTINEL',encoded)
            self.assertFalse(result['rules'])

    def test_sealed_declaration_accounting_rejects_inconsistent_claims(self):
        snapshot=seal_extraction(extract_language('class Model {} '+FUNCTION,'TypeScript'))
        for key,value in (('recordedDeclarations',2),('omittedDeclarations',1),('unsupportedDeclarations',2),('businessPolicyComplete',True)):
            corrupt=copy.deepcopy(snapshot);corrupt['coverage']['sourceDeclarationCoverage'][key]=value
            corrupt['rulesetDigest']=policy.policy_ruleset_digest(corrupt)
            with self.assertRaises(policy.PolicyError):policy.list_domain_policies(corrupt)


@unittest.skipIf(os.name=='nt','Private ACL setup is tested on the host platform separately')
class TypeScriptDeclarationDeliveryTests(unittest.TestCase):
    def setUp(self):
        from test_pipeline_mcp import access,acl,store,server
        import privacy_guard
        self.access,self.acl,self.store,self.server=access,acl,store,server
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.repo=self.root/'source';self.repo.mkdir();self.workspace=self.root/'knowledge'
        (self.repo/'model.ts').write_text('class Model {active: boolean;} '+FUNCTION)
        profile=privacy_guard.build_profile([],[],key=b't'*32)
        p=patch.object(privacy_guard,'load_profile',return_value=profile);p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'CODE_ONTOLOGY_HOME':str(self.root/'registry'),acl.PRINCIPAL_ENV:'local-owner'});p.start();self.addCleanup(p.stop)
        result=store.initialize(self.repo,self.workspace);self.snapshot=result['snapshotId'];self.args={'workspace_id':result['workspaceId'],'snapshot_id':self.snapshot}
        acl.initialize_access(self.workspace);access.register(str(self.workspace))
    def call(self,name,arguments):
        result=self.server._handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments}})['result']
        self.assertFalse(result['isError'],result);return result['structuredContent']['data']
    def test_sealed_mcp_retains_declaration_and_policy_coverage_without_source(self):
        shutil.rmtree(self.repo)
        delivered=self.call('ontology_pipeline_search',{**self.args,'kind':'semantic_fragment','limit':100})
        rows=[r for r in delivered['records']if r.get('category')=='source_policy_declaration']
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual(row['expression']['fieldCount'],1)
        self.assertEqual(row['extractorVersion'],'source-policy-declarations-1')
        self.assertEqual(row['path'],'model.ts');self.assertIn('sourceDigest',row)
        self.assertFalse(row['businessMeaningVerified']);self.assertNotIn('ruleVersion',row)
        coverage=self.call('list_domain_policies',self.args)['coverage']
        self.assertEqual(coverage['sourceDeclarationCoverage']['recordedDeclarations'],1)
        self.assertEqual(coverage['analyzedRules'],1)
        self.assertFalse(coverage['businessPolicyComplete'])
    def test_declaration_omission_blocks_new_publication(self):
        before=(self.workspace/'state.json').read_bytes();original=policy.extract_policy_rules
        def bounded(*args,**kwargs):kwargs['max_declarations']=0;return original(*args,**kwargs)
        with patch.object(policy,'extract_policy_rules',side_effect=bounded):
            with self.assertRaisesRegex(self.store.PipelineError,'policy_declaration_inventory_incomplete'):
                self.store.sync(self.workspace,force=True)
        self.assertEqual((self.workspace/'state.json').read_bytes(),before)
        self.assertEqual(self.store.status(self.workspace)['snapshotId'],self.snapshot)
        attempt=json.loads((self.workspace/'last-coverage-attempt.json').read_text())
        self.assertEqual(attempt['semanticFailures'][0]['coverage']['omittedDeclarations'],1)
    def test_rule_and_extractor_producer_versions_are_not_fabricated(self):
        rows=list(self.store.iter_records(self.workspace,self.snapshot));declaration=next(r for r in rows if r.get('category')=='source_policy_declaration')
        self.assertNotIn('ruleVersion',declaration)
        self.assertTrue(all(r['ruleVersion']==policy.RULE_VERSION for r in rows if r['kind']=='policy_rule'))
        ttl=(self.workspace/'snapshots'/self.snapshot/'ontology.ttl').read_text()
        self.assertIn(declaration['sourceDigest'],ttl)
        self.assertIn('prov:wasDerivedFrom',ttl)
