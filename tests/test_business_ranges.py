"""Exact source-produced character/byte coordinates; no coordinate inference."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/manage-code-ontology/scripts'))
import business_semantics as sem
import pipeline_store as source
import privacy_guard

class BusinessRangeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.profile=patch.object(privacy_guard,'load_profile',return_value=privacy_guard.build_profile([],[],key=b'r'*32))
        self.profile.start();self.addCleanup(self.profile.stop);sem.configure(privacy_guard=privacy_guard)
    def fixture(self,text):
        repo=self.root/'source';repo.mkdir();(repo/'items.py').write_bytes(text.encode('utf-8'))
        workspace=self.root/'knowledge';meta=source.initialize(repo,workspace)
        with source.open_reader(workspace,meta['snapshotId']) as reader:
            row=next(r for r in reader.iter_records() if set(r.get('sourceRange',{}))=={'charStart','charEnd','byteStart','byteEnd'})
            pins={'sourceSnapshotId':reader.snapshot_id,'sourceManifestSha256':hashlib.sha256((reader.directory/'manifest.json').read_bytes()).hexdigest(),'sourceFingerprint':reader.metadata['sourceFingerprint'],'analysisSpecId':reader.metadata['analysisSpecId']}
        return workspace,meta,row,pins
    def test_ascii_utf8_and_crlf_source_produced_bounds(self):
        for suffix,text in [('ascii','class Item:\n    value: int=1\n'),('utf8','class \ud56d\ubaa9:\n    value: int=1\n'),('crlf','class Item:\r\n    value: int=1\r\n')]:
            with self.subTest(format=suffix),tempfile.TemporaryDirectory() as td:
                self.root=Path(td).resolve();workspace,meta,row,pins=self.fixture(text)
                anchor=sem.make_anchor(row,source_pins=pins)
                self.assertEqual(anchor['sourceRangeOrSpan'],row['sourceRange'])
                self.assertEqual(row['sourceRange']['charEnd'],len(text))
                self.assertEqual(row['sourceRange']['byteEnd'],len(text.encode('utf-8')))
                with source.open_reader(workspace,meta['snapshotId']) as reader:
                    sem.validate_anchor(anchor,reader,source_pins=pins)
                if suffix=='utf8':self.assertGreater(row['sourceRange']['byteEnd'],row['sourceRange']['charEnd'])
    def test_wrong_types_partial_keys_unknown_keys_and_bounds_rejected(self):
        _,_,row,pins=self.fixture('class Item:\n    value: int=1\n')
        original=row['sourceRange']
        invalid=[{**original,'byteStart':True},{**original,'charEnd':'2'},
                 {k:v for k,v in original.items() if k!='byteEnd'},
                 {**original,'columnStart':0},{**original,'byteStart':-1},
                 {**original,'charEnd':-1},{**original,'byteStart':original['byteEnd']+1},
                 {**original,'charStart':original['charEnd']+1}]
        for span in invalid:
            with self.subTest(span=span),self.assertRaisesRegex(sem.BusinessError,'source_span_invalid'):
                sem.make_anchor({**row,'sourceRange':span},source_pins=pins)
    def test_rehashed_anchor_and_valid_fallback_cannot_replace_actual_range(self):
        workspace,meta,row,pins=self.fixture('class Item:\n    value: int=1\n')
        changed=copy.deepcopy(row);changed['sourceRange']['byteEnd']+=1
        forged=sem.make_anchor(changed,source_pins=pins)
        self.assertEqual(forged['recordDigest'],sem.digest(changed))
        with source.open_reader(workspace,meta['snapshotId']) as reader,self.assertRaisesRegex(sem.BusinessError,'source_anchor_mismatch'):
            sem.validate_anchor(forged,reader,source_pins=pins)
        changed=copy.deepcopy(row);changed['sourceRange']['byteStart']=-1
        self.assertEqual(set(changed['span']),{'lineStart','lineEnd'})
        with self.assertRaisesRegex(sem.BusinessError,'source_span_invalid'):sem.make_anchor(changed,source_pins=pins)

if __name__=='__main__':unittest.main()
