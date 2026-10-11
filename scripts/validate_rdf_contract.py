#!/usr/bin/env python3
"""Optional independent RDF parser + SHACL + exact JSON/Turtle parity checks.

No remote graph loading, imports, inference, JS rules or source execution.
Reports only category/counts, never input text, paths or parser exceptions.
"""
from __future__ import annotations
import argparse
import contextlib
import os
import hashlib
import json
import re
import sys
import subprocess
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SHAPES = ROOT/'skills/manage-code-ontology/references/validation-shapes.ttl'
MAX_BYTES = 128 * 1024 * 1024
WORKER_FLAG = '--_rdf-validation-worker'
SCOPE = 'Export structure and JSON parity; not source accuracy or complete PROV conformance'
# The released source ontology vocabulary, independently enumerated here. Unknown
# classes/relationships require an explicit contract update, not URI interpolation.
NODE_TYPES = frozenset({
    'Module', 'Package', 'Class', 'Interface', 'Enum', 'Record', 'Function',
    'AsyncFunction', 'Method', 'AsyncMethod', 'ExternalModule', 'ExternalType',
    'ExternalCallable', 'FrameworkAnnotation', 'FrameworkConcept', 'Decorator',
    'PipelineRole', 'PolicyLeaf', 'RuntimeBranch',
})
RELATIONSHIP_TYPES = frozenset({
    'DECLARES', 'IMPORTS', 'EXTENDS', 'IMPLEMENTS', 'ANNOTATED_BY', 'DECORATED_BY',
    'INJECTS', 'DECLARES_BEAN', 'MANAGED_AS', 'MAY_BE_PROXIED_BY', 'CALLS',
    'HAS_PIPELINE_ROLE', 'READS_POLICY_LEAF', 'DECLARES_RUNTIME_BRANCH',
    'GUARDS_RUNTIME_BRANCH',
})


def _valid_graph_identity(document: object) -> bool:
    """Reject ambiguous/missing identities before constructing any RDF URI."""
    if not isinstance(document, dict):
        return False
    nodes, edges = document.get('nodes'), document.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return False
    identities = set()
    for node in nodes:
        if not isinstance(node, dict):
            return False
        identity, kind = node.get('id'), node.get('type')
        if (not isinstance(identity, str) or not identity.strip()
                or identity in identities or not isinstance(kind, str)
                or kind not in NODE_TYPES):
            return False
        if any(not isinstance(node.get(field), str) for field in ('name', 'language')):
            return False
        if not node['language'].strip():
            return False
        if any(field in node and not isinstance(node[field], str)
               for field in ('path', 'qualified_name')):
            return False
        identities.add(identity)
    for edge in edges:
        if not isinstance(edge, dict):
            return False
        if any(not isinstance(edge.get(field), str) or edge[field] not in identities
               for field in ('source', 'target')):
            return False
        kind = edge.get('type')
        if not isinstance(kind, str) or kind not in RELATIONSHIP_TYPES:
            return False
        if not isinstance(edge.get('evidence', []), list):
            return False
    return True


def _safe_result(result: object) -> dict:
    """Only fixed categories and scalar counts may cross the worker boundary."""
    invalid = {'status': 'FAIL', 'category': 'rdf_contract_invalid'}
    if not isinstance(result, dict):
        return invalid
    if result == {'status': 'UNAVAILABLE', 'category': 'validation_extras_missing'}:
        return result
    if result == invalid:
        return invalid
    counts = ('missingTriples', 'extraTriples', 'triples')
    flags = ('jsonTurtleParity', 'shaclConforms')
    if (result.get('status') not in ('PASS', 'FAIL')
            or any(type(result.get(key)) is not int or result[key] < 0 for key in counts)
            or any(type(result.get(key)) is not bool for key in flags)
            or (result.get('lineageShaclConforms') is not None and type(result['lineageShaclConforms']) is not bool)):
        return invalid
    return {'status': result['status'], **{key: result[key] for key in (*counts, *flags)},
            'lineageShaclConforms': result['lineageShaclConforms'], 'scope': SCOPE}


def validate(document: dict, turtle: str, lineage_turtle: str | None = None) -> dict:
    """Run optional parsers in a local process so diagnostics stay private.

    Redirecting global streams/loggers in this caller would race with unrelated
    threads. The isolated worker captures library output; this process emits none.
    All graph parsing uses in-memory Turtle and fixed local shapes, never a URL.
    """
    invalid = {'status': 'FAIL', 'category': 'rdf_contract_invalid'}
    try:
        if not _valid_graph_identity(document):
            return invalid
        if not isinstance(turtle, str) or (lineage_turtle is not None and not isinstance(lineage_turtle, str)):
            return invalid
        encoded_document = json.dumps(document, ensure_ascii=False, allow_nan=False)
        if any(len(value.encode('utf-8')) > MAX_BYTES for value in (encoded_document, turtle, lineage_turtle or '')):
            return invalid
        request = json.dumps({'document': document, 'turtle': turtle, 'lineage': lineage_turtle},
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
        worker = subprocess.run([sys.executable, str(Path(__file__).resolve()), WORKER_FLAG],
                                input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=False, timeout=120)
        if worker.returncode != 0 or len(worker.stdout) > 4096:
            return invalid
        return _safe_result(json.loads(worker.stdout))
    except Exception:
        return invalid


def _worker_main() -> int:
    result = {'status': 'FAIL', 'category': 'rdf_contract_invalid'}
    # This process is dedicated to one validation. Suppression here cannot alter
    # another caller thread's stdout, stderr or logging configuration.
    with open(os.devnull, 'w', encoding='utf-8') as sink:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            try:
                raw = sys.stdin.buffer.read(6 * MAX_BYTES + 1024)
                request = json.loads(raw)
                result = _validate_in_process(request['document'], request['turtle'], request.get('lineage'))
            except Exception:
                pass
    print(json.dumps(_safe_result(result), ensure_ascii=True, sort_keys=True))
    return 0


def _validate_in_process(document: dict, turtle: str, lineage_turtle: str | None = None) -> dict:
    if not _valid_graph_identity(document):
        return {'status': 'FAIL', 'category': 'rdf_contract_invalid'}
    try:
        from rdflib import Graph, Literal, Namespace, URIRef
        from rdflib.namespace import RDF, RDFS, XSD
        from pyshacl import validate as validate_shapes
    except ImportError:
        return {'status': 'UNAVAILABLE', 'category': 'validation_extras_missing'}
    try:
        co = Namespace('https://battle-doll.github.io/code-ontology-explorer/schema#')
        node_uri = lambda value: URIRef('urn:code-ontology:node:' + quote(value, safe=''))
        # Building a graph independently of the Turtle renderer catches omitted,
        # extra, incorrectly escaped and incorrectly typed statements.
        expected = Graph()
        for node in document['nodes']:
            subject = node_uri(node['id'])
            expected.add((subject, RDF.type, co[node['type']]))
            expected.add((subject, RDFS.label, Literal(node['name'])))
            expected.add((subject, co.language, Literal(node['language'])))
            for field, predicate in [('qualified_name', co.qualifiedName), ('path', co.relativePath)]:
                if node.get(field): expected.add((subject, predicate, Literal(node[field])))
        for edge in document['edges']:
            predicate = co[re.sub('[^A-Za-z0-9]', '', edge['type'].title())]
            subject, target = node_uri(edge['source']), node_uri(edge['target'])
            expected.add((subject, predicate, target))
            for evidence in edge.get('evidence', []):
                raw = json.dumps({'source':edge['source'], 'target':edge['target'], 'type':edge['type'], 'evidence':evidence}, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode('utf-8')
                item = URIRef('urn:code-ontology:relationship-evidence:'+hashlib.sha256(raw).hexdigest())
                for pred, obj in [(RDF.type, co.RelationshipEvidence), (RDF.type, RDF.Statement),
                                  (RDF.subject, subject), (RDF.predicate, predicate), (RDF.object, target),
                                  (co.relationshipType, Literal(edge['type'])), (co.ruleId, Literal(evidence['rule_id'])),
                                  (co.evidenceBasis, Literal(evidence['basis'])), (co.runtimeStatus, Literal(evidence['runtime_status']))]:
                    expected.add((item,pred,obj))
                if evidence.get('path'): expected.add((item,co.evidencePath,Literal(evidence['path'])))
                if isinstance(evidence.get('line_start'),int):
                    expected.add((item,co.lineStart,Literal(evidence['line_start'],datatype=XSD.integer)))
                    expected.add((item,co.lineEnd,Literal(evidence['line_end'],datatype=XSD.integer)))
                for limitation in evidence.get('limitations',[]):
                    expected.add((item,co.limitationId,Literal(limitation)))
        quality = document.get('quality', {})
        relationship_quality = quality.get('relationship_evidence', {})
        quality_scope = json.dumps({'generator': document.get('generator', {}),
            'edges': [(e.get('source'), e.get('target'), e.get('type')) for e in document.get('edges', []) if isinstance(e, dict)],
            'quality': quality}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        digest = hashlib.sha256(quality_scope).hexdigest()
        q = URIRef('urn:code-ontology:quality:' + digest)
        expected.add((q, RDF.type, co.OntologyQuality))
        expected.add((q, co.contractVersion, Literal(quality.get('contract_version', 'unknown'))))
        for field, predicate in [('documented_edges', co.documentedEdges), ('missing_evidence', co.missingEvidence)]:
            expected.add((q, predicate, Literal(int(relationship_quality.get(field, 0)), datatype=XSD.integer)))
        expected.add((q, co.coveragePercent, Literal(str(float(relationship_quality.get('coverage_percent', 0.0))), datatype=XSD.decimal)))
        for language, adapter in quality.get('adapters', {}).items():
            item = URIRef('urn:code-ontology:adapter-quality:' + digest + ':' + quote(language, safe=''))
            expected.add((item, RDF.type, co.AdapterQuality))
            expected.add((item, co.language, Literal(language)))
            expected.add((item, co.supportStatus, Literal(adapter.get('status', 'unknown'))))
            expected.add((item, co.detected, Literal(adapter.get('detected') is True)))
            for name, status in adapter.get('capabilities', {}).items():
                expected.add((item, co.capability, Literal(name+'='+status)))
            for value in adapter.get('unsupported_runtime', []):
                expected.add((item, co.unsupportedRuntime, Literal(value)))
            expected.add((q, co.hasAdapterQuality, item))
        def check_iris(graph):
            # rdflib can merely warn about malformed IRIs and retain them. A
            # shape with no matching target must not turn such input into PASS.
            for triple in graph:
                for term in triple:
                    if not isinstance(term, URIRef):
                        continue
                    value = str(term)
                    if (not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value)
                            or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f
                                   or char in '<>"{}|\\^`' for char in value)
                            or re.search(r'%(?![0-9A-Fa-f]{2})', value)):
                        raise ValueError()
        actual = Graph().parse(data=turtle, format='turtle')
        check_iris(actual)
        missing, extra = len(set(expected)-set(actual)), len(set(actual)-set(expected))
        shapes = Graph().parse(data=SHAPES.read_text(encoding='utf-8'), format='turtle')
        conformant, report, _ = validate_shapes(actual, shacl_graph=shapes, inference='none', advanced=False, js=False, do_owl_imports=False, meta_shacl=True)
        lineage_ok = None
        if lineage_turtle is not None:
            lineage = Graph().parse(data=lineage_turtle,format='turtle')
            check_iris(lineage)
            lineage_ok, _, _ = validate_shapes(lineage, shacl_graph=shapes, inference='none', advanced=False, js=False, do_owl_imports=False)
            lineage_ok = bool(lineage_ok)
        return {'status':'PASS' if conformant and not missing and not extra and lineage_ok is not False else 'FAIL',
                'jsonTurtleParity':not missing and not extra, 'missingTriples':missing, 'extraTriples':extra,
                'triples':len(actual), 'shaclConforms':bool(conformant), 'lineageShaclConforms':lineage_ok,
                'scope':SCOPE}
    except Exception:
        return {'status':'FAIL','category':'rdf_contract_invalid'}


def main():
    if sys.argv[1:] == [WORKER_FLAG]:
        return _worker_main()
    class SafeArgumentParser(argparse.ArgumentParser):
        def error(self, message):
            # argparse normally echoes unknown arguments, which can be private.
            raise ValueError()
    parser=SafeArgumentParser(description=__doc__)
    parser.add_argument('--json',required=True)
    parser.add_argument('--turtle',required=True)
    parser.add_argument('--lineage')
    try:
        args=parser.parse_args()
        def read(value):
            path=Path(value)
            if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_BYTES: raise ValueError()
            with path.open('rb') as stream: raw=stream.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES: raise ValueError()
            return raw.decode('utf-8')
        result=validate(json.loads(read(args.json)),read(args.turtle),read(args.lineage) if args.lineage else None)
    except Exception:
        result={'status':'FAIL','category':'input_unreadable'}
    print(json.dumps(result,ensure_ascii=True,sort_keys=True))
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
