"""Neutral human presentation; deliberately not a full-data fidelity proof."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline_html as view
import privacy_guard as guard
import pipeline_acl as acl
from windows_fixture import protect_private_path


def record(i, module="m", domain=None):
    value = {"id": "s:%08d" % i, "kind": "symbol", "name": "Individual function is not a summary label",
             "module": module, "modulePath": "module-"+module, "path": "synthetic.py"}
    if domain is not None: value["domain"] = domain
    return value


class Reader:
    def __init__(self, rows, selected=None):
        self.rows = rows; self.metadata = {"snapshotId":"ps-neutral", "analysisSpecId":"spec-neutral",
            "recordCount":len(rows) if selected is None else selected, "coverage":{"complete":False,"unsupportedFiles":2}}
        self.by_id = {r["id"]:r for r in rows}
    def iter_records(self, *, page_size):
        assert page_size == 100
        yield from copy.deepcopy(self.rows)
    def get_record(self, identity):return copy.deepcopy(self.by_id.get(identity))


class MetadataReader(Reader):
    def __init__(self,rows):super().__init__(rows);self.fetches=[];self.details=[];self.plan=[(0,"Init",0,0)];self.partitions=["p0.sqlite"]
    def _union(self):return "SELECT * FROM p0.records"
    def _fetch(self,sql,params):
        self.fetches.append(sql)
        if sql.startswith("EXPLAIN "):return self.plan
        self.asserted_sql="SELECT id,kind,module,path FROM (SELECT id,kind,module,path FROM p0.records) WHERE id>? ORDER BY id LIMIT 100"
        assert sql==self.asserted_sql
        return [(r["id"],r["kind"],r["module"],r["path"]) for r in sorted(self.rows,key=lambda r:r["id"]) if r["id"]>params[0]][:100]
    def iter_records(self,**kwargs):raise AssertionError("full payload iteration forbidden")
    def get_record(self,identity):self.details.append(identity);return super().get_record(identity)


def checkpoint():pass


class HumanProjectionSummaryTests(unittest.TestCase):
    def test_private_render_omission_legacy_and_explicit_none_public_human(self):
        import pipeline_access as access
        args=('neutral-workspace','neutral-snapshot','neutral-output','ko')
        with mock.patch.object(view,'render_pipeline',return_value={'presentation':'records'}) as legacy, \
             mock.patch.object(view,'render_human',return_value={'presentation':'human'}) as human:
            self.assertEqual(access._render(*args),{'presentation':'records'})
            self.assertEqual(access._render(*args,presentation=None),{'presentation':'human'})
            self.assertEqual(access._render(*args,presentation='human'),{'presentation':'human'})
            self.assertEqual(access._render(*args,presentation='records'),{'presentation':'records'})
            self.assertEqual(legacy.call_count,2);self.assertEqual(human.call_count,2)
    def summary(self, rows, **kwargs):return view._human_aggregate(Reader(rows),checkpoint,**kwargs)
    def test_default_two_layers_max_three_and_constant_browser_data(self):
        rows=[record(i,"m%03d" % (i%90)) for i in range(1000)]
        summary=self.summary(rows); pages=list(view._human_pages(summary,Reader(rows).metadata))
        self.assertEqual(summary["processed"],1000);self.assertEqual(len(summary["groups"]),90)
        self.assertEqual(pages[0][1]["depth"],2)
        self.assertTrue(all(v["depth"] in (2,3) and len(v["nodes"])<=32 and len(v["edges"])<=64 for _,v in pages))
        self.assertTrue(all(len(view._human_script(v))<=131072 for _,v in pages))
        first=pages[0][1];self.assertEqual(first["ontologyCoverage"]["selectedRecords"],1000)
        self.assertEqual(first["presentationCoverage"]["shownGroups"],31)
        self.assertEqual(first["presentationCoverage"]["hiddenGroups"],59)
        self.assertNotIn("Individual function",json.dumps(pages))
    def test_unclassified_and_candidate_domain_are_not_invented(self):
        rows=[record(0,"a"),record(1,"b","Admitted candidate")]
        pages=list(view._human_pages(self.summary(rows),Reader(rows).metadata))
        labels=[n["label"] for _,p in pages for n in p["nodes"] if n["type"]=="area"]
        self.assertEqual(set(labels),{"UNKNOWN","Admitted candidate"})
    def test_stored_directories_form_structural_groups_original_module_stays(self):
        a={**record(0,"src"),"path":"src/core/alpha.py"}
        b={**record(1,"src"),"path":"src/adapters/beta.py"}
        summary=self.summary([a,b]);self.assertEqual(len(summary["groups"]),2)
        self.assertEqual(a["module"],"src");self.assertEqual(b["module"],"src")
        nodes=list(view._human_pages(summary,Reader([a,b]).metadata))[0][1]["nodes"][1:]
        self.assertTrue(all(n["groupingBasis"]=="SOURCE_DIRECTORY" and n["sourceModuleRef"]=="src" for n in nodes))
        self.assertEqual({n["label"] for n in nodes},{"src/core","src/adapters"})
    def test_full_scope_represents_all_areas_with_explicit_remainder_bucket(self):
        rows=[record(i,"m%02d"%i,"domain-%02d"%i) for i in range(40)]
        first=list(view._human_pages(self.summary(rows),Reader(rows).metadata))[0][1]
        self.assertEqual(first["chunkId"],"s000000");self.assertEqual(len(first["nodes"]),32)
        self.assertEqual(sum(n["recordCount"] for n in first["nodes"] if n["type"]=="area"),40)
        remaining=[n for n in first["nodes"] if n.get("groupingBasis")=="PRESENTATION_BUCKET"]
        self.assertEqual(len(remaining),1);self.assertEqual(remaining[0]["recordCount"],9)
        self.assertEqual(first["ontologyCoverage"]["selectedRecords"],40)
    def test_record_file_group_node_reference_units_stay_separate(self):
        rows=[record(i) for i in range(10)];reader=Reader(rows)
        reader.metadata["coverage"]["sourceProcessing"]={"state":"COMPLETE","denominator":3,"knownEntries":3,"numerator":3,"unknownDenominator":False,"counts":{"analyzed":3}}
        reader.metadata["coverage"]["semantics"]={"deniedRelations":7}
        first=list(view._human_pages(self.summary(rows),reader.metadata))[0][1]
        self.assertEqual(first["ontologyCoverage"]["selectedRecords"],10)
        self.assertEqual(first["ontologyCoverage"]["sourceFileOutcomes"]["denominator"],3)
        self.assertEqual(first["presentationCoverage"]["totalGroups"],1)
        self.assertEqual(first["presentationCoverage"]["shownNodes"],2)
        self.assertEqual(first["presentationCoverage"]["evidenceLocatorCount"],0)
        self.assertEqual(first["presentationCoverage"]["privacyWithheld"],"UNKNOWN")
        self.assertNotIn("deniedRelations",json.dumps(first))
    def test_counts_partition_and_stored_flow_occurrences(self):
        rows=[record(0,"a"),record(1,"b")]
        rows += [{"id":"r:%d"%i,"kind":"assertion","name":"static flow","module":"a","modulePath":"module-a",
                  "subject":rows[0]["id"],"object":rows[1]["id"],"predicate":"CALLS"} for i in range(3)]
        summary=self.summary(rows)
        self.assertEqual(sum(g["recordCount"] for g in summary["groups"].values()),5)
        self.assertEqual(list(summary["flows"].values()),[3]);self.assertEqual(summary["flowAssessmentUnavailable"],0)
        page=list(view._human_pages(summary,Reader(rows).metadata))[0][1]
        edges=[e for e in page["edges"] if e["type"]=="CALLS"]
        self.assertEqual(len(edges),1);self.assertEqual(edges[0]["count"],3)
    def test_lookup_limit_is_explicit_unknown_not_inferred_flow(self):
        rows=[record(i,"m%d"%i) for i in range(260)]
        rows += [{"id":"r:%d"%i,"kind":"assertion","module":"m0","modulePath":"module-m0",
                  "subject":"s:%08d"%i,"object":"s:%08d"%(i+1),"predicate":"CALLS"} for i in range(259)]
        summary=self.summary(rows)
        self.assertEqual(summary["endpointLookups"],256)
        self.assertGreater(summary["flowAssessmentUnavailable"],0)
        self.assertEqual(sum(summary["flows"].values())+summary["flowAssessmentUnavailable"],259)
    def test_source_policy_has_only_compact_evidence_no_program_or_path(self):
        row={**record(0),"kind":"policy_rule","program":{"op":"if","raw":"PRIVATE BODY"},"sourceDigest":"PRIVATE HASH"}
        card=view._human_card(row);encoded=json.dumps(card)
        for value in ("PRIVATE BODY","PRIVATE HASH","synthetic.py","Individual function"):
            self.assertNotIn(value,encoded)
        self.assertEqual(card["meaning"],"UNKNOWN");self.assertEqual(card["evidence"],[row["id"]])
    def test_policy_status_and_atomic_values_keep_types_complex_stays_explicit(self):
        row={"id":"p:neutral","kind":"business_policy","name":"Safe policy","facets":{
            "condition":{"status":"SOURCE_SUPPORTED","value":False},"calculation":{"status":"DECLARED","value":"1.20"},
            "exception":{"status":"UNKNOWN"},"complex":{"status":"SOURCE_SUPPORTED","value":{"not":["x","y"]}}}}
        card=view._human_card(row)
        self.assertIs(card["facets"]["condition"]["value"],False)
        self.assertEqual(card["facets"]["calculation"]["value"],"1.20")
        self.assertEqual(card["facets"]["complex"]["valueState"],"COMPLEX_MCP_ONLY")
        self.assertNotIn("value",card["facets"]["exception"])
    def test_cards_are_deliberately_bounded_with_remaining_count(self):
        rows=[{**record(i),"kind":"policy_rule"} for i in range(20)]
        pages=list(view._human_pages(self.summary(rows),Reader(rows).metadata));detail=pages[-1][1]
        self.assertEqual(len(detail["nodes"]),7)
        self.assertEqual(detail["presentationCoverage"]["totalPolicyCards"],20)
        self.assertEqual(detail["presentationCoverage"]["hiddenPolicyCards"],14)
    def test_denominator_and_group_limit_preserve_explicit_remainder(self):
        with self.assertRaisesRegex(view.PipelineHtmlError,"denominator"):
            view._human_aggregate(Reader([record(0)],selected=2),checkpoint)
        with mock.patch.object(view,"HUMAN_GROUPS",1):
            result=self.summary([record(0,"a"),record(1,"b")])
        self.assertIsNone(result["totalGroups"]);self.assertEqual(result["remainderRecords"],2)
        self.assertEqual(sum(g["recordCount"] for g in result["groups"].values()),2)
    def test_metadata_projection_never_reads_unselected_payload(self):
        rows=[{**record(i),"program":{"unselected":"protected neutral body"}} for i in range(200)]
        reader=MetadataReader(rows);profile=guard.build_profile(["Neutral"],[],key=b"m"*32,values=["protected neutral body"])
        result=view._human_aggregate(reader,checkpoint,metadata_only=True,profile=profile)
        self.assertEqual(result["processed"],200);self.assertEqual(reader.details,[])
        self.assertEqual(result["sourceProjection"],"indexed_metadata_v1")
        self.assertTrue(all("payload" not in sql and "GROUP BY" not in sql for sql in reader.fetches))
    def test_metadata_privacy_veto_preserves_opaque_affected_batch(self):
        rows=[record(0,"protected-module"),record(1)]
        profile=guard.build_profile(["Neutral"],[],key=b"m"*32,values=["protected-module"])
        checkpoint.progress=0
        with self.assertRaises(view.PipelineHtmlError) as caught:
            view._human_aggregate(MetadataReader(rows),checkpoint,metadata_only=True,profile=profile)
        affected=caught.exception.blockedMetadataRange
        self.assertEqual(affected["recordCount"],2);self.assertEqual(affected["piiEventCount"],"UNKNOWN")
        self.assertNotIn("protected-module",json.dumps(affected))
    def test_metadata_plan_and_duplicate_advancement_are_closed(self):
        profile=guard.build_profile(["Neutral"],[],key=b"m"*32)
        reader=MetadataReader([record(0)]);reader.plan=[(0,"SorterOpen",0,0)]
        with self.assertRaisesRegex(view.PipelineHtmlError,"plan_unsupported"):
            view._human_aggregate(reader,checkpoint,metadata_only=True,profile=profile)
        reader=MetadataReader([record(0),record(0)])
        with self.assertRaisesRegex(view.PipelineHtmlError,"metadata_row_invalid"):
            view._human_aggregate(reader,checkpoint,metadata_only=True,profile=profile)
    def test_selected_policy_detail_uses_existing_reader_and_coherence(self):
        rows=[{**record(i),"kind":"policy_rule"} for i in range(20)]
        reader=MetadataReader(rows);profile=guard.build_profile(["Neutral"],[],key=b"m"*32)
        result=view._human_aggregate(reader,checkpoint,metadata_only=True,profile=profile)
        self.assertEqual(result["selectedPolicyRows"],6);self.assertEqual(len(reader.details),6)
        self.assertEqual(next(iter(result["groups"].values()))["cardCount"],20)
    def test_metadata_types_caps_future_kind_and_selected_coherence_fail_closed(self):
        profile=guard.build_profile(["Neutral"],[],key=b"m"*32)
        for changes in ({"kind":"future_source_kind"},{"path":"x"*1025},{"path":"C:/private/user.py"},{"module":None}):
            with self.subTest(field=next(iter(changes))):
                with self.assertRaisesRegex(view.PipelineHtmlError,"metadata_row_invalid"):
                    view._human_aggregate(MetadataReader([{**record(0),**changes}]),checkpoint,metadata_only=True,profile=profile)
        reader=MetadataReader([{**record(0),"kind":"policy_rule"}])
        reader.get_record=lambda identity:{**reader.rows[0],"module":"wrong-module"}
        with self.assertRaisesRegex(view.PipelineHtmlError,"selected_detail_mismatch"):
            view._human_aggregate(reader,checkpoint,metadata_only=True,profile=profile)
    def test_duplicate_summary_identity_is_rejected_before_write(self):
        value=list(view._human_pages(self.summary([record(0)]),Reader([record(0)]).metadata))[0][1]
        value["nodes"].append(value["nodes"][0])
        with self.assertRaisesRegex(view.PipelineHtmlError,"identity_invalid"):view._human_script(value)
    def test_high_cardinality_metadata_has_bounded_remainder_and_unknown_group_total(self):
        rows=[{**record(i,"m%05d"%i),"path":"packages/group%05d/unit.py"%i} for i in range(1000)]
        reader=MetadataReader(rows);profile=guard.build_profile(["Neutral"],[],key=b"m"*32)
        result=view._human_aggregate(reader,checkpoint,metadata_only=True,profile=profile)
        self.assertEqual(len(result["groups"]),128);self.assertEqual(result["knownGroups"],127)
        self.assertIsNone(result["totalGroups"]);self.assertEqual(result["remainderRecords"],873)
        self.assertEqual(sum(g["recordCount"] for g in result["groups"].values()),1000)
        first=list(view._human_pages(result,reader.metadata))[0][1]
        self.assertIsNone(first["presentationCoverage"]["hiddenGroups"])
        self.assertLessEqual(len(first["nodes"]),32);self.assertEqual(reader.details,[])
    def test_safe_json_string_transport_and_five_shell_shared_data(self):
        value=list(view._human_pages(self.summary([record(0)]),Reader([record(0)]).metadata))[0][1]
        value["nodes"][0]["label"]="</script><img onerror=alert(1)>\u2028\u2029&\"__proto__"
        script=view._human_script(value).decode()
        self.assertNotIn("</script>",script);self.assertNotIn("<img",script)
        raw=json.loads(script.split("REGISTER(",1)[1].rsplit(");",1)[0]);decoded=json.loads(raw)
        self.assertEqual(decoded,value)
        for locale in view.LANGUAGES:
            shell=view._human_shell(locale,"s000001")
            self.assertIn('../data/s000001.js',shell);self.assertNotIn("ontology-data",shell)
            self.assertNotIn("records.json",shell);self.assertNotIn("<style",shell)
            self.assertIn("UNAVAILABLE",shell)
    def test_chunk_budget_rejects_before_script_materialization(self):
        with self.assertRaisesRegex(view.PipelineHtmlError,"chunk_budget"):
            view._human_script({"long":"x"*131072})


class HumanProjectionRealTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();protect_private_path(self.base)
        self.repo=self.base/"source";self.repo.mkdir(mode=0o700)
        (self.repo/"flow.py").write_text("def allowed(active: bool, blocked: bool) -> bool:\n    return active and not blocked\n")
        self.workspace=self.base/"ontology";self.registry=self.base/"registry";self.profile=self.base/"profile.json"
        self.profile.write_text(json.dumps(guard.build_profile(["Neutral Private Person"],[],key=b"h"*32)))
        protect_private_path(self.profile)
        self.env={k:v for k,v in os.environ.items() if not k.startswith(("CODE_ONTOLOGY","PYTHON"))}
        self.env.update({"CODE_ONTOLOGY_HOME":str(self.registry),"CODE_ONTOLOGY_PRINCIPAL":"local-owner",guard.PROFILE_ENV:str(self.profile)})
    def cli(self,*args):
        cache=Path(tempfile.mkdtemp(prefix="python-cache-",dir=self.base));os.chmod(cache,0o700)
        result=subprocess.run([sys.executable,"-E","-s","-B","-X","pycache_prefix="+str(cache),str(SCRIPTS/"companion.py"),*map(str,args)],
                              cwd=self.base,env=self.env,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,"Neutral CLI failed")
        return json.loads(result.stdout)
    def analyze(self,*extra):return self.cli("analyze","--repo",self.repo,"--workspace",self.workspace,"--authorized",*extra)
    def test_real_default_analyze_refresh_and_source_free_view(self):
        first=self.analyze();self.assertEqual(first["stages"]["html"]["status"],"READY")
        result=first["html"];self.assertEqual(result["presentation"],"human")
        self.assertEqual(result["sourceProjection"],"indexed_metadata_v1")
        self.assertTrue(result["initialBytesGoalMet"]);self.assertLessEqual(result["initialRequiredBytes"],524288)
        output=Path(result["outputDirectory"]);manifest=json.loads((output/"human-view.json").read_text())
        self.assertEqual(manifest["selectedRecords"],manifest["processedRecords"])
        self.assertEqual(len(list((output/"data").glob("*.js"))),manifest["summaryChunks"])
        before=json.loads((self.workspace/"state.json").read_text())
        second=self.cli("refresh","--workspace",self.workspace)
        self.assertEqual(second["snapshotId"],first["snapshotId"])
        self.assertEqual(second["stages"]["source"]["status"],"CURRENT")
        self.assertEqual(second["stages"]["html"]["status"],"READY")
        self.assertNotEqual(second["html"]["outputDirectory"],result["outputDirectory"])
        self.assertTrue(output.exists())
        after=json.loads((self.workspace/"state.json").read_text())
        self.assertEqual({k:v for k,v in after.items() if k!="sourceLastVerifiedAt"},
                         {k:v for k,v in before.items() if k!="sourceLastVerifiedAt"})
        shutil.rmtree(self.repo)
        third=self.cli("pipeline-html","--workspace",self.workspace,"--snapshot",first["snapshotId"],"--output",self.base/"offline")
        self.assertEqual(third["presentation"],"human");self.assertFalse(third["sourceRechecked"])
    def test_no_html_and_explicit_legacy_record_presentation(self):
        first=self.analyze("--no-html")
        self.assertEqual(first["stages"]["html"]["status"],"NOT_REQUESTED")
        result=self.cli("pipeline-html","--workspace",self.workspace,"--snapshot",first["snapshotId"],"--output",self.base/"records","--presentation","records")
        self.assertNotIn("presentation",result);self.assertIn("mapPagesPerLanguage",result)
    def test_late_profile_and_acl_changes_preserve_previous_output(self):
        first=self.analyze("--no-html")
        env_patch=mock.patch.dict(os.environ,self.env,clear=True);env_patch.start();self.addCleanup(env_patch.stop)
        import pipeline_store
        output=self.base/"human";previous=self.base/"previous";previous.mkdir(mode=0o700);(previous/"keep").write_text("old")
        original=guard.load_profile;calls=[0]
        def changed(*args,**kwargs):
            value=original(*args,**kwargs);calls[0]+=1
            if calls[0]>3:value={**value,"version":999}
            return value
        with mock.patch.object(guard,"load_profile",side_effect=changed):
            with self.assertRaises(view.PipelineHtmlError):view.render_human(self.workspace,first["snapshotId"],output)
        self.assertFalse(output.exists());self.assertEqual((previous/"keep").read_text(),"old")
        with mock.patch.object(acl,"authorize",side_effect=ValueError("neutral_acl_changed")):
            with self.assertRaises(view.PipelineHtmlError):view.render_human(self.workspace,first["snapshotId"],output)
        self.assertFalse(output.exists())
    def test_cancel_budget_collision_and_late_acl_keep_known_denominator(self):
        first=self.analyze("--no-html")
        env_patch=mock.patch.dict(os.environ,self.env,clear=True);env_patch.start();self.addCleanup(env_patch.stop)
        output=self.base/"human";n=[0]
        def cancel():n[0]+=1;return n[0]>=4
        with self.assertRaises(view.PipelineHtmlError) as caught:
            view.render_human(self.workspace,first["snapshotId"],output,cancel=cancel)
        self.assertIsInstance(caught.exception.exportProgress["selectedRecords"],int)
        self.assertFalse(output.exists())
        with self.assertRaises(view.PipelineHtmlError) as caught:
            view.render_human(self.workspace,first["snapshotId"],output,max_output_bytes=1)
        self.assertEqual(caught.exception.exportProgress["selectedRecords"],caught.exception.exportProgress["processedRecords"])
        self.assertFalse(output.exists())
        calls=[0];authorize=acl.authorize
        def late(*args,**kwargs):
            result=authorize(*args,**kwargs);calls[0]+=1
            if calls[0]>20:result={**result,"revision":result["revision"]+1}
            return result
        with mock.patch.object(acl,"authorize",side_effect=late):
            with self.assertRaises(view.PipelineHtmlError) as caught:
                view.render_human(self.workspace,first["snapshotId"],output)
        self.assertIsInstance(caught.exception.exportProgress["selectedRecords"],int)
        self.assertFalse(output.exists())
        output.mkdir(mode=0o700);(output/"old").write_text("previous")
        with self.assertRaises(view.PipelineHtmlError):view.render_human(self.workspace,first["snapshotId"],output)
        self.assertEqual((output/"old").read_text(),"previous")


if __name__=="__main__":unittest.main()
