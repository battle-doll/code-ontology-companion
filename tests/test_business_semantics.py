"""Neutral business contract tests; no private source or identity fixtures."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_semantics as sem
import privacy_guard

PINS={'sourceSnapshotId':'ps-'+'1'*32,'sourceManifestSha256':'2'*64,'sourceFingerprint':'3'*64,'analysisSpecId':'neutral-spec'}
RULE={'id':'policy:neutral','kind':'policy_rule','name':'allowed','path':'neutral.py','sourceDigest':'4'*64,
      'span':{'lineStart':1,'lineEnd':2},'status':'extraction_verified','parameters':[{'name':'active','type':'bool','finiteValues':[False,True]}],
      'program':{'op':'return','value':{'op':'input','name':'active','type':'bool'}},'returnType':'bool'}

class Reader:
    def __init__(self,rows=None):
        self.rows=copy.deepcopy(rows if rows is not None else [RULE]);self.metadata={'recordCount':len(self.rows)}
    def iter_records(self): yield from copy.deepcopy(self.rows)
    def get_record(self,rid):
        found=[x for x in self.rows if x['id']==rid]
        if len(found)>1: raise sem.BusinessError('duplicate_source_identity')
        return copy.deepcopy(found[0]) if found else None


def concept(reader=None,key='eligibility',kind='business_policy',domain='catalog'):
    reader=reader or Reader()
    return {'namespace':'review','domain':domain,'kind':kind,'conceptKey':key,'label':'Eligibility',
            'sourceAnchors':[sem.make_anchor(reader.rows[0],source_pins=PINS)],'facets':{}}


def review(items,reader=None):
    reader=reader or Reader()
    return sem.validate_review({'schemaVersion':1,'sourcePins':PINS,'concepts':items},reader,source_pins=PINS,candidates=[])


class BusinessSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.profile=privacy_guard.build_profile([],[],key=b'n'*32)
        self.patch=patch.object(privacy_guard,'load_profile',return_value=self.profile);self.patch.start()
        sem.configure(privacy_guard=privacy_guard)
    def tearDown(self):self.patch.stop()

    def test_outcome_metadata_accepts_only_opaque_identity_and_known_kind(self):
        row={**RULE,'id':'p:'+'a'*64};row.pop('span')
        events=list(sem.iter_candidate_events(Reader([row]),source_pins=PINS))
        self.assertEqual(events[0][2]['sourceRecordId'],row['id'])
        self.assertEqual(events[0][2]['sourceKind'],'policy_rule')
        row.update(id='src/private.py',kind='private_review_note')
        entry=list(sem.iter_candidate_events(Reader([row]),source_pins=PINS))[0][2]
        self.assertIsNone(entry['sourceRecordId']);self.assertEqual(entry['sourceKind'],'UNKNOWN')
        self.assertNotIn('private',str(entry))

    def test_candidate_is_useful_without_invented_meaning(self):
        result=sem.build_candidates(Reader(),source_pins=PINS)
        row=result['records'][0]
        self.assertEqual(row['support'],'candidate');self.assertEqual(row['businessApproval'],'unreviewed')
        self.assertEqual(row['facets']['formula']['value'],{'type':'ontology_reference','valueKind':'program'})
        self.assertEqual(row['facets']['inputs']['value']['items'][0],{'name':'active','valueType':'bool'})
        self.assertEqual(row['facets']['outcome']['value'],{'type':'scalar_type','name':'bool'})
        self.assertEqual(row['facets']['units']['status'],'UNKNOWN')
        self.assertEqual(result['coverage']['state'],'PARTIAL')
        self.assertNotIn('program',row['facets']['formula']['value'])

    def test_labels_never_merge_scoped_keys_or_domains(self):
        result=review([concept(key='one'),concept(key='two'),concept(key='one',domain='scheduling')])
        self.assertEqual(len({r['id'] for r in result['records']}),3)
        self.assertEqual({r['businessApproval'] for r in result['records']},{'unreviewed'})

    def test_duplicate_identity_preserves_both_inputs_as_conflicts(self):
        result=review([concept(),concept()])
        self.assertEqual(result['coverage']['denominator'],2);self.assertEqual(result['records'],[])
        self.assertEqual([r['status'] for r in result['omissions']],['conflicted','conflicted'])

    def test_every_anchor_field_is_actual_not_self_asserted(self):
        anchor=concept()['sourceAnchors'][0]
        for field,value in [('recordDigest','0'*64),('sourceSha256','0'*64),('sourceFingerprint','fake'),('path','other.py'),('inlinePointer','/program'),('targetDigest','0'*64),('dependencyClosureDigest','0'*64),('sourceRangeOrSpan',{'lineStart':2,'lineEnd':3})]:
            with self.subTest(field=field):
                changed=copy.deepcopy(anchor);changed[field]=value
                with self.assertRaises(sem.BusinessError):sem.validate_anchor(changed,Reader(),source_pins=PINS)

    def test_inline_pointer_escaping_and_wrong_indices(self):
        row={**RULE,'a/b':{'~x':[True]}};reader=Reader([row])
        anchor=sem.make_anchor(row,source_pins=PINS,inline_pointer='/a~1b/~0x/0')
        self.assertIs(sem.validate_anchor(anchor,reader,source_pins=PINS),True)
        for pointer in ('/a~2b','/a~1b/~0x/00','/a~1b/~0x/-','/missing'):
            with self.assertRaises(sem.BusinessError):sem.make_anchor(row,source_pins=PINS,inline_pointer=pointer)

    def test_typed_source_projection_and_bool_int_not_equal(self):
        item=concept();a=sem.make_anchor(RULE,source_pins=PINS,inline_pointer='/returnType')
        item['facets']['outcome']={'status':'SOURCE_SUPPORTED','value':{'type':'scalar_type','name':'bool'},'sourceAnchors':[a]}
        self.assertEqual(len(review([item])['records']),1)
        item['facets']['outcome']['value']={'type':'boolean','value':1}
        self.assertEqual(review([item])['omissions'][0]['reason'],'semantic_scalar_invalid')

    def test_input_cannot_approve_or_impersonate(self):
        for key in ('approved','businessApproval','actor','principal'):
            item=concept();item[key]='approved'
            self.assertFalse(review([item])['records'])

    def test_raw_source_or_hidden_metadata_value_rejected(self):
        for value in ({'type':'text','value':'safe','sourceText':'hidden'},{'path':'hidden.py'},{'type':'ontology_reference','valueKind':'program','actor':'any'}):
            item=concept();item['facets']['formula']={'status':'DECLARED','value':value,'basis':'explicit meaning'}
            self.assertFalse(review([item])['records'])
        item=concept();item['facets']['formula']={'status':'SOURCE_SUPPORTED','value':RULE,'sourceAnchors':item['sourceAnchors']}
        self.assertFalse(review([item])['records'])

    def test_unknown_partial_and_invalidated_closure_fail_closed(self):
        for change in ({'dependencyClosure':{'status':'invalidated'}},{'structuralOnly':True},{'status':'unsupported'}):
            row={**RULE,**change};r=Reader([row]);item=concept(r)
            item['facets']['formula']={'status':'SOURCE_SUPPORTED','value':{'type':'ontology_reference','valueKind':'program'},'sourceAnchors':[sem.make_anchor(row,source_pins=PINS,inline_pointer='/program')]}
            self.assertFalse(review([item],r)['records'])

    def test_budget_retains_original_denominator(self):
        rows=[{**RULE,'id':f'policy:{i}'} for i in range(4)]
        result=sem.build_candidates(Reader(rows),source_pins=PINS,max_records=1)
        self.assertEqual(result['coverage']['denominator'],4);self.assertEqual(result['coverage']['omitted'],3)
        self.assertEqual(result['coverage']['state'],'PARTIAL')
        self.assertEqual(review([concept(key=str(i)) for i in range(3)])['coverage']['denominator'],3)

    def test_json_duplicates_nonfinite_schema_bool_rejected(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}','{"a":1e999}'):
            with self.assertRaises(sem.BusinessError):sem.loads(raw)
        with self.assertRaises(sem.BusinessError):sem.validate_review({'schemaVersion':True,'sourcePins':PINS,'concepts':[]},Reader(),source_pins=PINS,candidates=[])
        self.assertNotEqual(sem.digest(True),sem.digest(1));self.assertNotEqual(sem.digest(1),sem.digest(1.0))

    def test_relation_identity_direction_and_closure(self):
        one,two=concept(key='one',kind='business_object_type'),concept(key='two',kind='business_object_type')
        relation=concept(key='link',kind='business_relation');relation.update(subject=sem.concept_id('review','catalog','business_object_type','one'),object=sem.concept_id('review','catalog','business_object_type','two'),role='contains',cardinality={'min':0,'max':3})
        result=review([one,two,relation]);self.assertEqual(len(result['records']),3)
        relation['cardinality']['min']=False;self.assertEqual(len(review([one,two,relation])['records']),2)
        relation['cardinality']['min']=0;two['sourceAnchors'][0]['recordDigest']='0'*64
        result=review([one,two,relation]);self.assertEqual(len(result['records']),1);self.assertEqual(result['coverage']['denominator'],3)

    def test_declared_units_not_promoted_to_source_truth(self):
        item=concept();item['facets']['units']={'status':'DECLARED','value':{'type':'money','value':'12.50','currency':'USD'},'basis':'operator selected unit'}
        row=review([item])['records'][0]
        self.assertEqual(row['support'],'candidate');self.assertEqual(row['facets']['units']['status'],'DECLARED')
        self.assertEqual(row['runtimeStatus'],'NOT_OBSERVED')

    def test_privacy_rejection_is_bounded(self):
        item=concept();item['label']='ghp_' + 'q' * 36
        with self.assertRaises(privacy_guard.PrivacyError) as caught:review([item])
        self.assertNotIn(item['label'],str(caught.exception))

    def test_source_locator_cannot_become_policy_value(self):
        item=concept();item['facets']['units']={'status':'SOURCE_SUPPORTED','value':{'type':'text','value':RULE['path']},'sourceAnchors':[sem.make_anchor(RULE,source_pins=PINS,inline_pointer='/path')]}
        result=review([item]);self.assertFalse(result['records']);self.assertEqual(result['omissions'][0]['reason'],'source_facet_role_unsupported')

    def test_facet_concept_reference_requires_actual_scope(self):
        item=concept();item['facets']['subject_scope']={'status':'DECLARED','value':{'type':'concept_reference','conceptId':'business:'+'0'*64},'basis':'explicit relationship'}
        result=review([item]);self.assertFalse(result['records']);self.assertEqual(result['coverage']['denominator'],1)

    def test_time_calendar_and_order_boundaries(self):
        for start,end in [('2025-13-02T00:00:00Z','2025-12-03T00:00:00Z'),('2025-12-03T00:00:00Z','2025-12-02T00:00:00Z')]:
            item=concept();item['facets']['effective_interval']={'status':'DECLARED','value':{'type':'time_interval','start':start,'end':end,'timezone':'UTC','clock':'event_time','bounds':'left_closed'},'basis':'explicit period'}
            self.assertFalse(review([item])['records'])

    def test_explicit_conflict_is_not_a_source_fact(self):
        item=concept();item['facets']['conflicts']={'status':'DECLARED','value':{'type':'boolean','value':True},'basis':'conflicting reviewed policies'}
        row=review([item])['records'][0];self.assertEqual(row['support'],'conflicted');self.assertEqual(row['businessApproval'],'unreviewed')

    def test_reserved_namespace_and_malformed_kind_retained(self):
        first=concept();first['namespace']='source'
        second=concept();second['kind']=[]
        result=review([first,second]);self.assertEqual(result['coverage']['denominator'],2);self.assertEqual(result['records'],[])

    def test_same_label_does_not_create_equivalence(self):
        one=concept(key='one',kind='business_object_type');two=concept(key='two',kind='business_object_type')
        result=review([one,two]);self.assertEqual(len(result['records']),2)
        self.assertTrue(all('aliases' not in r for r in result['records']))

if __name__=='__main__':unittest.main()
