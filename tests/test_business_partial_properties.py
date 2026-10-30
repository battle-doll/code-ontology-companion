"""Known numeric property facets survive without inventing executable facts."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_business_query as fixture
from test_business_explicit_contracts import ptype


class PartialPropertyTests(unittest.TestCase):
    setUp = fixture.BusinessQueryTests.setUp
    args = fixture.BusinessQueryTests.args
    call = fixture.BusinessQueryTests.call
    candidate = fixture.BusinessQueryTests.candidate

    def review_properties(self, values):
        anchor = self.candidate()['sourceAnchors']
        concepts = [{'namespace':'review','domain':'catalog','kind':'business_property','conceptKey':'value'+str(i),
                     'label':'Numeric property '+str(i),'sourceAnchors':anchor,
                     'facets':{'scalar_type':{'status':'DECLARED','value':value,'basis':'explicit neutral property facts'}}}
                    for i,value in enumerate(values)]
        self.meta = self.store.review(self.workspace, self.sid, self.meta['businessSnapshotId'], self.meta['businessDigest'],
            {'schemaVersion':1,'sourcePins':{k:self.meta[k] for k in self.store._semantics.PIN_KEYS},'concepts':concepts})
        return self.call(kind='business_property')['records']

    def test_independently_known_precision_scale_and_rounding_preserved(self):
        values = [ptype('decimal',scale=3,rounding='ROUND_HALF_UP'),
                  ptype('decimal',precision=12), ptype('decimal',rounding='ROUND_DOWN'),
                  ptype('decimal',precision=12,scale=3,rounding='ROUND_HALF_UP')]
        records = self.review_properties(values)
        own = {r['conceptKey']:r for r in records if r['namespace']=='review'}
        self.assertEqual(len(own),4)
        self.assertEqual(self.meta['coverage']['reviewAccepted'],4)
        for i,value in enumerate(values):
            record=own['value'+str(i)]
            self.assertEqual(record['facets']['scalar_type']['value'],value)
            self.assertEqual(record['facets']['scalar_type']['status'],'DECLARED')
            self.assertFalse(record['businessMeaningComplete'])
            self.assertEqual(record['runtimeStatus'],'NOT_OBSERVED')

    def test_partial_decimal_information_does_not_enable_execution(self):
        sem=self.store._semantics
        for spec in (ptype('decimal',scale=3,rounding='ROUND_HALF_UP'),
                     ptype('decimal',precision=12,rounding='ROUND_HALF_UP'),
                     ptype('decimal',precision=12,scale=3)):
            self.assertEqual(sem._typed_value(spec),spec)
            with self.assertRaisesRegex(sem.BusinessError,'explicit_decimal_contract_required'):
                sem.property_value(spec,{'type':'decimal','value':'1.250'})
        full=ptype('decimal',precision=12,scale=3,rounding='ROUND_HALF_UP')
        self.assertEqual(sem.property_value(full,{'type':'decimal','value':'1.250'})['value'],'1.250')

    def test_concrete_numeric_value_contract_remains_complete_or_absent(self):
        sem=self.store._semantics
        for extra in ({'scale':3},{'precision':12},{'precision':'UNKNOWN','scale':3},
                      {'precision':12,'scale':'UNKNOWN'}):
            with self.assertRaises(sem.BusinessError):
                sem._typed_value({'type':'decimal','value':'1.250',**extra})
        self.assertEqual(sem._typed_value({'type':'decimal','value':'1.250'})['value'],'1.250')

    def test_malformed_partial_values_and_contradictory_pairs_are_rejected(self):
        sem=self.store._semantics
        for field in ('precision','scale'):
            for value in (True,False,None,-1,101,2.0,'2','unknown'):
                with self.subTest(field=field,value=value),self.assertRaises(sem.BusinessError):
                    sem._typed_value(ptype('decimal',**{field:value}))
        for value in (ptype('decimal',precision=0),ptype('decimal',precision=2,scale=3),
                      ptype('int',scale=1),ptype('string',scale=2),ptype('bool',precision=2)):
            with self.assertRaises(sem.BusinessError):sem._typed_value(value)

    def test_original_rejected_review_inputs_remain_in_denominator(self):
        values=[ptype('decimal',scale=2),ptype('decimal',scale=-1),ptype('decimal',precision=9),ptype('decimal',precision=True)]
        rows=self.review_properties(values)
        self.assertEqual({r['conceptKey'] for r in rows if r['namespace']=='review'},{'value0','value2'})
        self.assertEqual(self.meta['coverage']['denominator'],4)
        self.assertEqual(self.meta['coverage']['reviewAccepted'],2)
        self.assertEqual(self.meta['coverage']['rejected'],2)
        self.assertEqual(self.meta['coverage']['state'],'PARTIAL')

    def test_integer_known_zero_scale_does_not_change_prior_value_authority(self):
        sem=self.store._semantics; raw={'type':'integer','value':37}
        self.assertEqual(sem.property_value(ptype('int',scale=0),raw),sem.property_value(ptype('int'),raw))
        with self.assertRaises(sem.BusinessError):sem.property_value(ptype('int',precision=9),raw)

    def test_quantity_and_currency_constraints_unchanged_with_partial_facets(self):
        sem=self.store._semantics
        allowed=ptype('decimal',scale=2,quantityKind='money',currency='EUR',rounding='ROUND_HALF_EVEN')
        self.assertEqual(sem._typed_value(allowed),allowed)
        for bad in (dict(allowed,currency='UNKNOWN'),dict(allowed,currency='eur'),
                    ptype('decimal',scale=2,quantityKind='quantity'),dict(allowed,quantityKind='scalar')):
            with self.assertRaises(sem.BusinessError):sem._typed_value(bad)

    def test_source_deleted_stdio_and_policy_only_projection_keep_partial_facts(self):
        values=[ptype('decimal',scale=4,rounding='ROUND_HALF_EVEN'),ptype('decimal',precision=15)]
        self.review_properties(values)
        profile=self.root/'neutral-profile.json';profile.write_text(json.dumps(fixture.companion.privacy_guard.load_profile()));profile.chmod(0o600)
        cache=self.root/'empty-cache';cache.mkdir(mode=0o700)
        fixture.acl.update_access(self.workspace,'reader',['read_policy'],[self.sid])
        env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
        env.update({fixture.companion.privacy_guard.PROFILE_ENV:str(profile),fixture.acl.PRINCIPAL_ENV:'reader',
                    'PYTHONDONTWRITEBYTECODE':'1','PYTHONPYCACHEPREFIX':str(cache)})
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ontology_pipeline_search','arguments':self.args(kind='business_property')}}
        run=subprocess.run([sys.executable,'-E','-s','-B','-X','pycache_prefix='+str(cache),str(Path(__file__).resolve().parents[1]/'mcp/server.py')],
            input=json.dumps(request)+'\n',text=True,capture_output=True,timeout=30,env=env)
        self.assertEqual(run.returncode,0,run.stderr)
        reply=json.loads(run.stdout)['result'];self.assertFalse(reply['isError'])
        self.assertEqual(json.loads(reply['content'][0]['text']),reply['structuredContent'])
        rows={r['conceptKey']:r for r in reply['structuredContent']['data']['records'] if r['namespace']=='review'}
        for i,value in enumerate(values):self.assertEqual(rows['value'+str(i)]['facets']['scalar_type']['value'],value)
        self.assertTrue(all(r['evidenceDetailsWithheld'] for r in rows.values()))
        self.assertNotIn('sourceSha256',json.dumps(rows));self.assertFalse(any(cache.rglob('*')))

    def test_source_deleted_html_and_portable_records_preserve_partial_contract(self):
        import pipeline_html
        import pipeline_export
        values=[ptype('decimal',scale=2,rounding='ROUND_HALF_EVEN',quantityKind='money',currency='EUR'),
                ptype('decimal',precision=13)]
        self.review_properties(values)
        with self.store.open_reader(self.workspace,self.sid,self.meta['businessSnapshotId'],self.meta['businessDigest']) as reader:
            expected={r['id']:r for r in reader.iter_records() if r['namespace']=='review'}
        human=self.root/'human';profile=fixture.companion.privacy_guard.load_profile()
        with patch.object(pipeline_html.privacy_guard,'load_profile',return_value=profile):
            pipeline_html.render_pipeline(self.workspace,self.sid,human)
        actual={}
        for file in (human/'business'/'records').glob('*.json'):
            row=json.loads(file.read_text())
            if row['id'] in expected:actual[row['id']]=row
        self.assertEqual(actual,expected)
        for locale in ('ko','en','ja','zh-CN','ru'):
            self.assertTrue((human/'business'/locale/'index.html').is_file())
            for row in actual.values():
                digest=__import__('hashlib').sha256(row['id'].encode()).hexdigest()
                self.assertTrue((human/'business'/locale/'records'/(digest+'.html')).is_file())
        portable=self.root/'portable';pipeline_export.export_bundle(self.workspace,self.sid,portable)
        copied={json.loads(f.read_text())['id']:json.loads(f.read_text()) for f in (portable/'business'/'records').glob('*.json')}
        self.assertEqual({key:copied[key] for key in expected},expected)


if __name__=='__main__':unittest.main()
