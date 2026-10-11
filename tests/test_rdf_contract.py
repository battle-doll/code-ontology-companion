from __future__ import annotations
import importlib.util
import contextlib
import copy
import io
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
core=load('rdf_contract_core',ROOT/'skills/manage-code-ontology/scripts/code_ontology_core.py')
validator=load('rdf_contract_validator',ROOT/'scripts/validate_rdf_contract.py')
EXTRAS=importlib.util.find_spec('rdflib') is not None and importlib.util.find_spec('pyshacl') is not None

@unittest.skipUnless(EXTRAS,'Optional RDF validation extras; separate required CI job runs these checks')
class RdfContractTests(unittest.TestCase):
    def test_promoted_snapshot_provenance_contract(self):
        sys.path.insert(0,str(ROOT/'skills/manage-code-ontology/scripts'))
        import companion
        with tempfile.TemporaryDirectory() as raw:
            base=Path(raw);repo=base/'repo';repo.mkdir()
            (repo/'entry.py').write_text('def entry():\n    return 1\n',encoding='utf-8')
            workspace=base/'workspace'
            with mock.patch.dict(os.environ,{'CODE_ONTOLOGY_HOME':str(base/'data')}):
                result=companion.initialize(str(repo),str(workspace),authorized=True)
            snapshot=workspace/'snapshots'/result['snapshotId']
            doc=json.loads((snapshot/'ontology.json').read_text())
            ttl=(snapshot/'ontology.ttl').read_text()
            lineage=(workspace/'lineage.ttl').read_text()
            self.assertEqual('PASS',validator.validate(doc,ttl,lineage)['status'])
            # Remove a required provenance edge while preserving valid Turtle.
            from rdflib import Graph,URIRef
            graph=Graph().parse(data=lineage,format='turtle')
            generated=URIRef('http://www.w3.org/ns/prov#wasGeneratedBy')
            graph.remove((None,generated,None))
            self.assertEqual('FAIL',validator.validate(doc,ttl,graph.serialize(format='turtle'))['status'])

    def test_generated_graphs_and_complete_corpus(self):
        corpus=json.loads((ROOT/'evals/ontology-quality-cases.json').read_text())
        for case in corpus['cases']:
            with self.subTest(case=case['id']),tempfile.TemporaryDirectory() as raw:
                repo=Path(raw)
                for name,content in case['files'].items():
                    p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
                doc=core.build_document(repo)
                result=validator.validate(doc,core.render_turtle(doc))
                self.assertEqual('PASS',result['status'],result)

    def test_unicode_escaping_and_empty_graph(self):
        doc={'nodes':[{'id':'python:module:例','type':'Module','name':'quote"\\\n例','language':'Python','path':'例.py'}],'edges':[]}
        self.assertEqual('PASS',validator.validate(doc,core.render_turtle(doc))['status'])
        empty={'nodes':[],'edges':[]}
        self.assertEqual('PASS',validator.validate(empty,core.render_turtle(empty))['status'])

    def test_deleted_and_invented_triples_fail(self):
        doc={'nodes':[{'id':'python:module:x','type':'Module','name':'x','language':'Python'}],'edges':[]}
        turtle=core.render_turtle(doc)
        self.assertEqual('FAIL',validator.validate(doc,'')['status'])
        extra=turtle+'\n<urn:invented> <urn:predicate> <urn:object> .\n'
        result=validator.validate(doc,extra)
        self.assertEqual('FAIL',result['status']);self.assertEqual(1,result['extraTriples'])

    def test_invalid_graph_identity_is_rejected_before_library_calls(self):
        node = {'id': 'a', 'type': 'Function', 'name': 'a', 'language': 'Python'}
        invalid = [
            {'nodes': [node, dict(node)], 'edges': []},
            {'nodes': [node, {**node, 'type': 'Class'}], 'edges': []},
            {'nodes': [{**node, 'id': ''}], 'edges': []},
            {'nodes': [{**node, 'id': ['a']}], 'edges': []},
            {'nodes': [{**node, 'type': 'Bad PRIVATE_SYNTHETIC_SENTINEL'}], 'edges': []},
            {'nodes': [{**node, 'type': 'UnknownType'}], 'edges': []},
            {'nodes': [{**node, 'type': ['Function']}], 'edges': []},
            {'nodes': [{**node, 'name': 4}], 'edges': []},
            {'nodes': [node], 'edges': [{'source': 'a', 'target': 'missing', 'type': 'CALLS'}]},
            {'nodes': [node], 'edges': [{'source': 'missing', 'target': 'a', 'type': 'CALLS'}]},
            {'nodes': [node], 'edges': [{'source': ['a'], 'target': 'a', 'type': 'CALLS'}]},
            {'nodes': [node], 'edges': [{'source': 'a', 'target': 'a', 'type': 'BAD PRIVATE_SYNTHETIC_SENTINEL'}]},
        ]
        with mock.patch.object(validator.subprocess, 'run') as worker:
            for doc in invalid:
                with self.subTest(document=invalid.index(doc)):
                    result = validator.validate(doc, '')
                    self.assertEqual({'status': 'FAIL', 'category': 'rdf_contract_invalid'}, result)
            worker.assert_not_called()

    def test_matching_json_turtle_cannot_hide_dangling_nodes(self):
        doc = {'nodes': [{'id': 'a', 'type': 'Function', 'name': 'a', 'language': 'Python'}],
               'edges': [{'source': 'a', 'target': 'missing', 'type': 'CALLS',
                          'evidence': [{'rule_id': 'python.call.test', 'basis': 'direct_syntax',
                                        'runtime_status': 'runtime_unknown'}]}]}
        turtle = core.render_turtle(doc)
        self.assertEqual('FAIL', validator.validate(doc, turtle)['status'])
        # Independently exercise SHACL, including the no-evidence direct edge.
        from rdflib import Graph
        from pyshacl import validate
        shapes = Graph().parse(data=validator.SHAPES.read_text(), format='turtle')
        for include_evidence in (True, False):
            document = copy.deepcopy(doc)
            if not include_evidence:
                document['edges'][0].pop('evidence')
            graph = Graph().parse(data=core.render_turtle(document), format='turtle')
            conformant, _, _ = validate(graph, shacl_graph=shapes, inference='none',
                                       advanced=False, js=False, do_owl_imports=False)
            self.assertFalse(conformant)

    def test_library_diagnostics_never_reach_cli_or_caller_streams(self):
        marker = 'PRIVATE_SYNTHETIC_SENTINEL'
        valid = {'nodes': [{'id': 'a', 'type': 'Function', 'name': 'a', 'language': 'Python'}], 'edges': []}
        bad_node = copy.deepcopy(valid)
        bad_node['nodes'][0]['type'] = 'Bad ' + marker
        cases = [(bad_node, '', None),
                 (valid, '<urn:Bad ' + marker + '> <urn:p> <urn:o> .', None),
                 (valid, core.render_turtle(valid), '<urn:Bad ' + marker + '> <urn:p> <urn:o> .'),
                 (valid, 'not turtle ' + marker, None)]
        out, err = io.StringIO(), io.StringIO()
        root_handlers = tuple(logging.getLogger().handlers)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda args: validator.validate(*args), cases))
        self.assertEqual('', out.getvalue())
        self.assertEqual('', err.getvalue())
        self.assertEqual(root_handlers, tuple(logging.getLogger().handlers))
        for result in results:
            self.assertEqual('FAIL', result['status'])
            self.assertNotIn(marker, json.dumps(result))
        # The command-line boundary must also suppress rdflib's raw IRI warning.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'input.json').write_text(json.dumps(valid))
            (root / 'input.ttl').write_text(cases[1][1])
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_rdf_contract.py'),
                                        '--json', str(root / 'input.json'), '--turtle', str(root / 'input.ttl')],
                                       capture_output=True, check=False, text=True)
            self.assertEqual(1, completed.returncode)
            self.assertEqual('', completed.stderr)
            self.assertNotIn(marker, completed.stdout)
            self.assertEqual('FAIL', json.loads(completed.stdout)['status'])
            arguments = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_rdf_contract.py'),
                                        '--unexpected', marker], capture_output=True, check=False, text=True)
            self.assertEqual(1, arguments.returncode)
            self.assertEqual('', arguments.stderr)
            self.assertNotIn(marker, arguments.stdout)
            self.assertEqual('FAIL', json.loads(arguments.stdout)['status'])

    def test_turtle_and_lineage_urls_are_never_dereferenced(self):
        doc = {'nodes': [], 'edges': []}
        imports = '<urn:graph> <http://www.w3.org/2002/07/owl#imports> <https://invalid.example/PRIVATE_SYNTHETIC_SENTINEL> .'
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as urlopen, \
             mock.patch('socket.create_connection', side_effect=AssertionError('network forbidden')) as connect:
            result = validator._validate_in_process(doc, core.render_turtle(doc) + imports, imports)
        self.assertEqual('FAIL', result['status'])
        self.assertEqual(1, result['extraTriples'])
        self.assertTrue(result['lineageShaclConforms'])
        urlopen.assert_not_called()
        connect.assert_not_called()

    def test_invalid_evidence_and_parse_errors_are_sanitized(self):
        graph=core.Graph('synthetic')
        graph.add_node('a','Function','a','Python');graph.add_node('b','Function','b','Python')
        graph.add_edge('a','b','CALLS',rule_id='python.call.test',basis='direct_syntax',runtime_status='runtime_unknown')
        from collections import Counter
        doc=graph.document(Counter({'Python':1}),Counter())
        turtle=core.render_turtle(doc).replace('runtime_unknown','made_up')
        result=validator.validate(doc,turtle)
        self.assertEqual('FAIL',result['status']);self.assertFalse(result['shaclConforms'])
        result=validator.validate(doc,'not turtle PRIVATE_SYNTHETIC_SENTINEL')
        self.assertNotIn('PRIVATE_SYNTHETIC_SENTINEL',json.dumps(result))

if __name__=='__main__':unittest.main()
