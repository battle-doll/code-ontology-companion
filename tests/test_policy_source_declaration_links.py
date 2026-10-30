"""Synthetic selected constants and canonical record declarations; no values inferred."""
import hashlib
import json
import unittest

from test_policy_java_contracts import extract as single_extract, returns, bindings, core, pipeline_java, policy_semantics, pipeline_delivery
from test_policy_literal_review import walk


def extract(source, others=None):
    # Cross-file proof is tested only after every synthetic file's actual
    # definitions are emitted; the standalone extractor intentionally cannot
    # certify a declaration it has never received.
    if not others:
        return single_extract(source)
    from test_policy_dependency_closure import analyzed_files, finish
    results, facts = analyzed_files({"Rules.java": source, **others})
    finish(results, facts)
    return results["Rules.java"], facts["Rules.java"]


class SourceStaticFieldTests(unittest.TestCase):
    def test_imported_field_links_to_actual_initializer_fragment_without_copying_value(self):
        declaration="package sample;public class Constants{public static final java.math.BigDecimal FACTOR=java.math.BigDecimal.valueOf(271); }"
        source="import static sample.Constants.FACTOR;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
        row=returns(extract(source,{"Constants.java":declaration})[0])[0]
        self.assertEqual({c["method"] for _,c in bindings(row)},{"multiply"})
        field=row["expression"]["arguments"][0]["staticFieldBinding"]
        digest=hashlib.sha256(declaration.encode()).hexdigest()
        facts={"path":"Constants.java","sourceDigest":digest,"module":"synthetic","modulePath":".","records":[]}
        index=core.build_java_index({"Constants.java":declaration})
        pipeline_java.enrich(facts,index)
        result=policy_semantics.extract_semantics(declaration,"Java","Constants.java",digest,java_type_context=pipeline_java.semantic_type_context(facts,index))
        record=next(f for f in result["fragments"] if f.get("name")=="FACTOR")
        self.assertEqual(field["declarationFragmentId"],record["id"])
        self.assertEqual(field["initializerEvidence"]["fragmentId"],record["id"])
        self.assertEqual(field["runtimeValue"],"UNKNOWN")
        self.assertFalse(field["valueSubstitution"])
        self.assertNotIn('"value": 271',json.dumps(row))

    def test_selected_wildcard_and_single_import_precedence(self):
        declarations={"Constants.java":"package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}"}
        for imports,positive in [("import static sample.Constants.*;",True),
                ("import static sample.Constants.FACTOR;import static unknown.Owner.*;",True),
                ("import static sample.Constants.*;import static unknown.Owner.*;",False),
                ("import static sample.Constants.FACTOR;import static unknown.Owner.FACTOR;",False)]:
            row=returns(extract(imports+"class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}",declarations)[0])[0]
            self.assertEqual(bool(bindings(row)),positive)

    def test_selected_wildcard_exact_direct_declaration_closes_without_absence_claim(self):
        from test_policy_dependency_closure import analyzed_files, finish
        declaration="package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}"
        source="import static sample.Constants.*;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
        results,facts=analyzed_files({"Rules.java":source,"Constants.java":declaration})
        lookup=finish(results,facts); row=returns(results["Rules.java"])[0]
        self.assertTrue(bindings(row))
        field=row["expression"]["arguments"][0]["staticFieldBinding"]
        provider=lookup(field["declarationFragmentId"],"Constants.java")
        self.assertEqual((provider["name"],provider["path"],provider["sourceDigest"]),("FACTOR","Constants.java",hashlib.sha256(declaration.encode()).hexdigest()))
        self.assertEqual(field["sourceRange"],provider["sourceRange"])
        self.assertEqual(field["runtimeValue"],"UNKNOWN")
        self.assertFalse(field["valueSubstitution"])
        api=core._load_bundled_helper("policy_java_contracts")
        for path,result in results.items():
            for fragment in result["fragments"]:
                owner={**fragment,"kind":"semantic_fragment"}
                _,reason=pipeline_java.policy_java_platform.requirements(owner,owner,lookup=lookup,api_validator=api.validate_catalog_entry,allow_pending=False)
                self.assertIsNone(reason)

    def test_other_selected_wildcard_namespaces_require_exact_actual_absence(self):
        import copy
        from test_policy_dependency_closure import analyzed_files, finish
        caller="import static sample.Constants.*;import static sample.Other.*;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
        provider="package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}"
        for extra in ("public static int DIFFERENT;","public static void FACTOR(){}"):
            for reverse in (False,True):
                with self.subTest(extra=extra,reverse=reverse):
                    sources={"Rules.java":caller,"Constants.java":provider,"Other.java":"package sample;public class Other{"+extra+"}"}
                    if reverse:sources=dict(reversed(list(sources.items())))
                    results,facts=analyzed_files(sources);finish(results,facts)
                    fragment=returns(results["Rules.java"])[0];self.assertEqual(len(bindings(fragment)),1)
                    owner=next(row for row in facts["Other.java"]["records"] if row.get("qualifiedName")=="sample.Other")
                    def changed(record):
                        if record['id']!=owner['id']:return record
                        record=copy.deepcopy(record);record['directMemberInventory']['fieldNames']=['FACTOR'];return record
                    finish(results,facts,changed);self.assertFalse(bindings(fragment))

    def test_selected_wildcard_does_not_exempt_other_or_incomplete_namespaces(self):
        source="import static sample.Constants.*;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
        declarations=[
            {"Constants.java":"package sample;public class Constants extends Missing{public static final java.math.BigDecimal FACTOR=null;}"},
            {"Constants.java":"package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null; Object unsupported = Other::call;}"},
            {"Constants.java":"package sample;public class Constants extends Parent{public static final java.math.BigDecimal FACTOR=null;}","Parent.java":"package sample;public class Parent{public static final Object FACTOR=null;}"},
            {"Constants.java":"package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}","Other.java":"package sample;public class Other{public static final java.math.BigDecimal FACTOR=null;}"},
        ]
        declarations.append({"Constants.java":"package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;"+"".join("int field%d;"%i for i in range(1024))+"}"})
        for index,others in enumerate(declarations):
            imported=source.replace("class AmountCase","import static sample.Other.*;class AmountCase") if index==3 else source
            self.assertFalse(bindings(returns(extract(imported,others)[0])[0]))
        private="package sample;public class Constants{public static final java.math.BigDecimal secretFactor=null;}"
        redacted=source.replace("FACTOR","secretFactor")
        self.assertFalse(bindings(returns(extract(redacted,{"Constants.java":private})[0])[0]))

    def test_selected_wildcard_missing_or_changed_emitted_direct_definition_is_withdrawn(self):
        import copy
        from test_policy_dependency_closure import analyzed_files, finish
        declaration="package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}"
        source="import static sample.Constants.*;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
        for fault in ("missing","id","owner_path","source_digest","range","unsupported"):
            results,facts=analyzed_files({"Rules.java":source,"Constants.java":declaration})
            target=next(r for r in results["Constants.java"]["fragments"] if r.get("name")=="FACTOR")
            identity=target["id"]
            if fault=="missing": results["Constants.java"]["fragments"].remove(target)
            def altered(record):
                if record["id"]!=identity:return record
                record=copy.deepcopy(record)
                if fault=="id":record["id"]="semantic:"+"0"*64
                elif fault=="owner_path":record["path"]="Other.java"
                elif fault=="source_digest":record["sourceDigest"]="0"*64
                elif fault=="range":record["sourceRange"]["charEnd"]-=1
                elif fault=="unsupported":record.update(representationStatus="unsupported",expression=None)
                return record
            finish(results,facts,altered)
            self.assertFalse(bindings(returns(results["Rules.java"])[0]))

    def test_selected_field_actual_provider_and_owner_provenance_is_required(self):
        import copy
        from test_policy_dependency_closure import analyzed_files, finish
        variants = {
            "fq": "public static final java.math.BigDecimal FACTOR=null;",
            "simple": "public static final BigDecimal FACTOR=null;",
            "lambda": "Object callback=()->{};public static final java.math.BigDecimal FACTOR=null;",
        }
        for imported in ("*", "FACTOR"):
            caller="import static sample.Constants."+imported+";class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
            for variant,field in variants.items():
                provider="package sample;import java.math.BigDecimal;public class Constants{"+field+"}"
                for reverse in (False,True):
                    sources={"Rules.java":caller,"Constants.java":provider}
                    if reverse:sources=dict(reversed(list(sources.items())))
                    for fault in ("type","owner_name","owner_digest","owner_range","owner_kind","owner_path"):
                        with self.subTest(imported=imported,variant=variant,reverse=reverse,fault=fault):
                            results,facts=analyzed_files(sources);fragment=returns(results["Rules.java"])[0]
                            # First validate the real delivered records. A later
                            # observation cannot inherit a successful cache.
                            finish(results,facts);self.assertEqual(len(bindings(fragment)),1)
                            binding=fragment["expression"]["arguments"][0]["staticFieldBinding"]
                            provider_id=binding["declarationFragmentId"];owner_id=binding["declaringOwner"]["id"]
                            observed=[]
                            def changed(record):
                                if record["id"] not in {provider_id,owner_id}:return record
                                record=copy.deepcopy(record)
                                if record["id"]==provider_id and fault=="type":record["declaredType"]="java.lang.Object";observed.append(record["id"])
                                elif record["id"]==owner_id and fault.startswith("owner_"):
                                    observed.append(record["id"])
                                    if fault=="owner_name":record["qualifiedName"]="sample.Unrelated"
                                    elif fault=="owner_digest":record["sourceDigest"]="0"*64
                                    elif fault=="owner_range":record["declarationHeaderRange"]["charEnd"]-=1
                                    elif fault=="owner_kind":record["type"]="Method"
                                    elif fault=="owner_path":record["path"]="Elsewhere.java"
                                return record
                            finish(results,facts,changed)
                            self.assertTrue(observed)
                            self.assertFalse(bindings(fragment))
                            self.assertEqual(fragment["expression"]["arguments"][0]["name"],"FACTOR")
                            self.assertEqual(fragment["dependencyClosure"]["status"],"invalidated")

    def test_retargeted_inline_field_type_cannot_contradict_actual_spelling(self):
        from test_policy_dependency_closure import analyzed_files, finish
        for imported in ("*","FACTOR"):
            for raw in ("java.math.BigDecimal","BigDecimal"):
                with self.subTest(imported=imported,raw=raw):
                    sources={"Rules.java":"import static sample.Constants."+imported+";class AmountCase{Object f(java.math.BigDecimal n){return n.multiply(FACTOR);}}",
                        "Constants.java":"package sample;import java.math.BigDecimal;public class Constants{public static final "+raw+" FACTOR=null;}"}
                    results,facts=analyzed_files(sources);finish(results,facts);fragment=returns(results["Rules.java"])[0]
                    self.assertTrue(bindings(fragment))
                    provider=next(row for row in results["Constants.java"]["fragments"] if row.get("name")=="FACTOR")
                    provider["declaredType"]="java.lang.Object"
                    for node in walk(fragment["expression"]):
                        for key in ("staticFieldBinding","receiverStaticFieldBinding"):
                            if key in node:node[key]["declaredType"]="java.lang.Object"
                    finish(results,facts);self.assertFalse(bindings(fragment))

    def test_selected_field_missing_or_unknown_subproof_withdraws_derived_type(self):
        from test_policy_dependency_closure import analyzed_files, finish
        for imported in ("*","FACTOR"):
            for fault in ("binding","owner","version_missing","version_unknown"):
                with self.subTest(imported=imported,fault=fault):
                    sources={"Rules.java":"import static sample.Constants."+imported+";class AmountCase{Object f(java.math.BigDecimal n){return n.multiply(FACTOR);}}",
                        "Constants.java":"package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}"}
                    results,facts=analyzed_files(sources);finish(results,facts);fragment=returns(results["Rules.java"])[0]
                    self.assertTrue(bindings(fragment));argument=fragment["expression"]["arguments"][0]
                    if fault=="binding":argument.pop("staticFieldBinding");argument["staticType"].pop("platformInheritance",None)
                    elif fault=="owner":argument["staticFieldBinding"].pop("declaringOwner")
                    elif fault=="version_missing":argument["staticFieldBinding"].pop("declarationProofVersion")
                    else:argument["staticFieldBinding"]["declarationProofVersion"]=2
                    finish(results,facts);self.assertFalse(bindings(fragment))

    def test_actual_member_role_catalog_and_modifiers_are_one_obligation(self):
        import copy
        from test_policy_dependency_closure import analyzed_files, finish
        for imported in ("*", "FACTOR"):
            for fault in ("callable", "missing_role", "initializer_role", "catalog_missing", "catalog_range", "static", "final", "private", "type_private", "enclosing"):
                with self.subTest(imported=imported,fault=fault):
                    sources={"Rules.java":"import static sample.Constants."+imported+";class AmountCase{Object f(java.math.BigDecimal n){return n.multiply(FACTOR);}}",
                        "Constants.java":"package sample;public class Constants{Object callback=()->{return 1;};public static final java.math.BigDecimal FACTOR=null;}"}
                    results,facts=analyzed_files(sources);finish(results,facts);fragment=returns(results["Rules.java"])[0]
                    self.assertEqual(len(bindings(fragment)),1)
                    field=fragment["expression"]["arguments"][0]["staticFieldBinding"]
                    provider=next(row for row in results['Constants.java']['fragments'] if row['id']==field['declarationFragmentId'])
                    owner=next(row for row in facts['Constants.java']['records'] if row['id']==field['declaringOwner']['id'])
                    if fault=='callable':provider['controlFlow']['owner']=copy.deepcopy(fragment['controlFlow']['owner'])
                    elif fault=='missing_role':provider.pop('controlFlow')
                    elif fault=='initializer_role':provider['controlFlow']['contexts']=[{'kind':'initializer'}]
                    elif fault=='catalog_missing':owner.pop('staticFieldDeclarations')
                    elif fault=='catalog_range':owner['staticFieldDeclarations']['declarations'][0]['sourceRange']['charEnd']-=1
                    elif fault in {'static','final','private'}:
                        actual=owner['staticFieldDeclarations']['declarations'][0]
                        modifiers=actual['modifiers']
                        if fault=='private':modifiers.remove('public');modifiers.append('private');modifiers.sort()
                        else:modifiers.remove(fault)
                        # Even matching derived metadata cannot repair a
                        # contradictory actual member eligibility declaration.
                        field['memberDeclaration']['modifiers']=list(modifiers)
                    elif fault=='type_private':owner['typeDeclarationEligibility']['modifiers']=['private']
                    else:owner['typeDeclarationEligibility']['enclosingTypeId']=fragment['javaSourceOwner']['typeSymbolId']
                    finish(results,facts);self.assertFalse(bindings(fragment))

    def test_actual_caller_namespace_selection_preserves_single_precedence(self):
        import copy
        from test_policy_dependency_closure import analyzed_files, finish
        for imported in ('*','FACTOR'):
            for fault in ('removed','wrong_owner','wrong_kind','same_name_explicit','unknown_wildcard','duplicate','coverage','count','use_name'):
                with self.subTest(imported=imported,fault=fault):
                    sources={'Rules.java':'import static sample.Constants.'+imported+';class AmountCase{Object f(java.math.BigDecimal n){return n.multiply(FACTOR);}}',
                        'Constants.java':'package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}'}
                    results,facts=analyzed_files(sources);finish(results,facts);fragment=returns(results['Rules.java'])[0]
                    self.assertEqual(len(bindings(fragment)),1)
                    caller=next(row for row in facts['Rules.java']['records'] if row['id']==fragment['javaSourceOwner']['typeSymbolId'])
                    imported_row=caller['typeImports'][0]
                    if fault=='removed':caller['typeImports']=[]
                    elif fault=='wrong_owner':imported_row['qualifiedName']=imported_row['qualifiedName'].replace('sample.Constants','omitted.Other')
                    elif fault=='wrong_kind':imported_row['kind']='type'
                    elif fault in {'same_name_explicit','unknown_wildcard'}:caller['typeImports'].append({'kind':'static','qualifiedName':'omitted.Other.'+('FACTOR' if fault=='same_name_explicit' else '*'),'sourceRange':copy.deepcopy(imported_row['sourceRange'])})
                    elif fault=='duplicate':caller['typeImports'].append(copy.deepcopy(imported_row))
                    elif fault=='use_name':fragment['expression']['arguments'][0]['name']='MISSING'
                    count=len(caller['typeImports']);caller['typeImportCoverage'].update(detected=count,recorded=count,complete=True)
                    if fault=='coverage':caller['typeImportCoverage']['complete']=False
                    if fault=='count':caller['typeImportCoverage']['recorded']+=1
                    finish(results,facts)
                    self.assertEqual(bool(bindings(fragment)),fault=='duplicate' or fault=='unknown_wildcard' and imported=='FACTOR')

    def test_same_named_nested_member_cannot_be_rebound_to_an_outer_owner(self):
        import copy
        from test_policy_dependency_closure import analyzed_files, finish
        sources={'Rules.java':'import static sample.Outer.Constants.FACTOR;class AmountCase{Object f(java.math.BigDecimal n){return n.multiply(FACTOR);}}',
            'Outer.java':'package sample;public class Outer{public static final java.math.BigDecimal FACTOR=null;public static class Constants{public static final java.math.BigDecimal FACTOR=null;}}'}
        results,facts=analyzed_files(sources);finish(results,facts);fragment=returns(results['Rules.java'])[0]
        self.assertEqual(len(bindings(fragment)),1)
        field=fragment['expression']['arguments'][0]['staticFieldBinding'];old=field['declaringOwner']['id']
        outer=next(row for row in facts['Outer.java']['records'] if row.get('qualifiedName')=='sample.Outer')
        field['declaringOwner']={key:copy.deepcopy(outer[key])for key in field['declaringOwner']}
        field['declaringType']='sample.Outer';field['callerNamespace']['selectedOwner']='sample.Outer'
        field['callerNamespace']['namespaceOwners']=[{key:outer[key]for key in ('id','qualifiedName','path','sourceDigest')}]
        typed=fragment['expression']['arguments'][0]['staticType'];typed['sourceEvidenceIds']=[outer['id']if identity==old else identity for identity in typed['sourceEvidenceIds']]
        caller=next(row for row in facts['Rules.java']['records'] if row['id']==fragment['javaSourceOwner']['typeSymbolId'])
        caller['typeImports'][0]['qualifiedName']='sample.Outer.FACTOR'
        finish(results,facts);self.assertFalse(bindings(fragment))

    def test_local_and_initializer_declarations_are_not_direct_members(self):
        from test_policy_dependency_closure import analyzed_files, finish
        bodies=['void f(){final java.math.BigDecimal FACTOR=null;}',
            'static{final java.math.BigDecimal FACTOR=null;}',
            'Object callback=()->{final java.math.BigDecimal FACTOR=null;return FACTOR;};']
        for body in bodies:
            with self.subTest(body=body):
                sources={'Rules.java':'import static sample.Constants.FACTOR;class AmountCase{Object f(java.math.BigDecimal n){return n.multiply(FACTOR);}}',
                    'Constants.java':'package sample;public class Constants{'+body+'}'}
                results,facts=analyzed_files(sources);finish(results,facts)
                self.assertFalse(bindings(returns(results['Rules.java'])[0]))

    def test_private_inaccessible_nonfinal_multi_and_annotated_fields_are_not_promoted(self):
        fields=["private static final java.math.BigDecimal FACTOR=null;",
                "static final java.math.BigDecimal FACTOR=null;",
                "public static java.math.BigDecimal FACTOR=null;",
                "public final java.math.BigDecimal FACTOR=null;",
                "public static final java.math.BigDecimal FACTOR=null, OTHER=null;",
                "@Deprecated public static final java.math.BigDecimal FACTOR=null;"]
        source="import static sample.Constants.FACTOR;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}"
        for field in fields:
            row=returns(extract(source,{"Constants.java":"package sample;public class Constants{"+field+"}"})[0])[0]
            self.assertFalse(bindings(row))
        row=returns(extract(source,{"Constants.java":"package sample;class Constants{public static final java.math.BigDecimal FACTOR=null;}"})[0])[0]
        self.assertFalse(bindings(row))

    def test_same_package_field_access_and_static_import_conflict(self):
        declarations={"Constants.java":"package sample;public class Constants{static final java.math.BigDecimal FACTOR=null;}",
            "Other.java":"package sample;public class Other{public static final java.math.BigDecimal FACTOR=null;}"}
        prefix="package sample;import static sample.Constants.FACTOR;"
        row=returns(extract(prefix+"class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}",declarations)[0])[0]
        self.assertTrue(bindings(row))
        row=returns(extract(prefix+"import static sample.Other.FACTOR;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}",declarations)[0])[0]
        self.assertFalse(bindings(row))

    def test_source_import_shadowing_and_custom_type_do_not_gain_arithmetic(self):
        declarations={"Constants.java":"package sample;public class Constants{public static final java.math.BigDecimal FACTOR=null;}"}
        bodies=["Object FACTOR;Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}",
                "Object f(java.math.BigDecimal value,Object FACTOR){return value.multiply(FACTOR);}",
                "<FACTOR>Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}",
                "Object f(java.math.BigDecimal value){Object FACTOR;return value.multiply(FACTOR);}",
                "Object f(java.math.BigDecimal value,Object input){if(input instanceof Fake FACTOR)return value.multiply(FACTOR);return null;}"]
        for body in bodies:
            self.assertFalse(any(bindings(row) for row in returns(extract("import static sample.Constants.FACTOR;class AmountCase{"+body+"}",declarations)[0])))
        declarations={"Constants.java":"package sample;public class Constants{public static final Object FACTOR=null;}"}
        row=returns(extract("import static sample.Constants.FACTOR;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}",declarations)[0])[0]
        self.assertFalse(bindings(row))

    def test_array_source_constant_retains_array_type_only(self):
        declaration="package sample;public class Constants{public static final java.math.BigDecimal[] FACTOR={null,null};}"
        row=returns(extract("import static sample.Constants.FACTOR;class AmountCase{Object f(java.math.BigDecimal value){return value.multiply(FACTOR);}}",{"Constants.java":declaration})[0])[0]
        self.assertFalse(bindings(row))
        self.assertEqual(row["expression"]["arguments"][0]["staticType"]["name"],"java.math.BigDecimal[]")


class RecordConstructorSourceTests(unittest.TestCase):
    def test_implicit_canonical_constructor_links_arguments_to_component_declarations(self):
        source="record Measures(String label,java.math.BigDecimal lower,java.math.BigDecimal upper){}class AmountCase{Object f(String label,java.math.BigDecimal low,java.math.BigDecimal high){return new Measures(label,low,high);}}"
        result,facts=extract(source); row=returns(result)[0]; binding=row["expression"]["recordConstruction"]
        declaration=row["recordConstructorDeclarations"][0]
        self.assertEqual(binding["declarationId"],declaration["id"])
        self.assertEqual(binding["resolution"],"implicit_canonical_parameter_order")
        self.assertEqual(binding["argumentBindings"],[{"argumentIndex":i,"parameterIndex":i} for i in range(3)])
        self.assertEqual([p["name"] for p in declaration["parameters"]],["label","lower","upper"])
        for parameter in declaration["parameters"]:
            span=parameter["sourceRange"]
            self.assertTrue(source[span["charStart"]:span["charEnd"]].endswith(parameter["name"]))
        self.assertIn(declaration["recordDeclarationId"],{r["id"] for r in facts["records"] if r["kind"]=="symbol"})
        self.assertEqual(binding["storedComponentValues"],"UNKNOWN")
        self.assertEqual(binding["argumentApplicability"],"UNKNOWN")
        self.assertNotIn("recordShape",row["expression"])
        self.assertEqual(row["unit"]["status"],"UNKNOWN")

    def test_explicit_compact_and_overloaded_constructors_do_not_map_arguments_to_fields(self):
        bodies=["Measures{lower=upper;}",
            "Measures(String label,java.math.BigDecimal lower,java.math.BigDecimal upper){this.label=label;this.lower=upper;this.upper=lower;}",
            "Measures(String label){this(label,null,null);}"]
        for body in bodies:
            source="record Measures(String label,java.math.BigDecimal lower,java.math.BigDecimal upper){"+body+"}class AmountCase{Object f(String label,java.math.BigDecimal low,java.math.BigDecimal high){return new Measures(label,low,high);}}"
            row=returns(extract(source)[0])[-1]
            binding=row["expression"]["recordConstruction"]; declaration=row["recordConstructorDeclarations"][0]
            self.assertEqual(binding["resolution"],"UNKNOWN")
            self.assertEqual(binding["argumentBindings"],[])
            self.assertTrue(declaration["constructorCandidates"])
            self.assertEqual(declaration["parameterToField"],"UNKNOWN")

    def test_arity_accessibility_generic_and_type_shadow_fail_closed(self):
        sources=[
            "record Measures(String label){}class AmountCase{Object f(){return new Measures(null,null);}}",
            "record Measures<T>(T label){}class AmountCase{Object f(){return new Measures<String>(null);}}",
            "record Measures(String label){}class AmountCase{<Measures>Object f(){return new Measures(null);}}",
            "class Owner{private record Measures(String label){}}class AmountCase{Object f(){return new Owner.Measures(null);}}",
            "class Measures{Measures(String label){}}class AmountCase{Object f(){return new Measures(null);}}",
        ]
        for source in sources:
            row=returns(extract(source)[0])[-1]
            self.assertNotEqual(row["expression"].get("recordConstruction",{}).get("resolution"),"implicit_canonical_parameter_order")

    def test_cross_file_public_record_has_exact_source_owner_not_simple_name_guess(self):
        declarations={"Measures.java":"package sample;public record Measures(String label){}"}
        source="import sample.Measures;class AmountCase{Object f(String label){return new Measures(label);}}"
        row=returns(extract(source,declarations)[0])[0]
        self.assertEqual(row["recordConstructorDeclarations"][0]["recordType"],"sample.Measures")
        declarations={"Owner.java":"package sample;public class Owner{public record Measures(String label){}}"}
        row=returns(extract("import missing.Measures;class AmountCase{Object f(){return new Measures(null);}}",declarations)[0])[0]
        self.assertNotIn("recordConstruction",row["expression"])

    def test_repeated_array_constructor_has_one_bounded_declaration_catalog(self):
        source="record Measures(String label){}class AmountCase{Object[] values={"+','.join('new Measures(null)' for _ in range(40))+"};}"
        result,_=extract(source); row=next(f for f in result["fragments"] if f.get("name")=="values")
        self.assertEqual(len(row["recordConstructorDeclarations"]),1)
        self.assertEqual(len([n for n in walk(row["expression"]) if "recordConstruction" in n]),40)
        self.assertLess(len(json.dumps(pipeline_delivery.normalize_response({"records":[row]})).encode()),256*1024)

    def test_sensitive_constructor_never_gains_component_catalog(self):
        source="record Measures(String label){}class AmountCase{Object secretValue=new Measures(null);}"
        row=extract(source)[0]["fragments"][0]
        self.assertTrue(row["structuralOnly"])
        self.assertNotIn("recordConstructorDeclarations",row)
        self.assertFalse(any("recordConstruction" in n for n in walk(row)))


if __name__=="__main__": unittest.main()
