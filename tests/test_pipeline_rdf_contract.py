"""Synthetic pipeline projection/SHACL tests, separate from legacy JSON RDF."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/manage-code-ontology/scripts'))
import pipeline_store as store
import privacy_guard

EXTRAS = all(importlib.util.find_spec(name) is not None for name in ('rdflib', 'pyshacl'))
EXTRAS_REASON = 'Optional pipeline RDF tests require both rdflib and pyshacl; required RDF CI must run them'
if EXTRAS:
    from rdflib import Graph, Literal, Namespace, RDF, URIRef
    from pyshacl import validate
    CO = Namespace('urn:code-ontology:pipeline:')
    PROV = Namespace('http://www.w3.org/ns/prov#')


def records():
    common = {'path': 'synthetic/例.java', 'sourceDigest': 'a' * 64,
              'basis': 'declared', 'span': {'lineStart': 1, 'lineEnd': 2}}
    rows = []
    for index, kind in enumerate(('symbol', 'callsite', 'framework', 'assertion', 'policy_rule')):
        rows.append(dict(common, id='p:' + str(index) * 64, kind=kind,
                         name=kind, ruleVersion='synthetic-adapter-1'))
    rows[3].update(subject=rows[0]['id'], object=rows[0]['id'], predicate='CALLS',
                   resolution='resolved_static')
    for index, (category, version) in enumerate((
            ('return', 'policy-fragments-2'), ('coverage', 'policy-fragments-2'),
            ('source_documentation', 'source-documentation-1'),
            ('coverage', 'source-documentation-1'),
            ('documentation_omission', 'source-documentation-1'))):
        row = dict(common, id='semantic:' + str(index + 5) * 64,
                   kind='semantic_fragment', name=category, category=category,
                   extractorVersion=version, businessMeaningVerified=False)
        if category == 'return':
            row['expression'] = {'op': 'literal', 'value': 'AST_SENTINEL'}
        if category == 'source_documentation':
            row.update(sourceText='/** DOC_SENTINEL */', instructionAuthority='none')
        rows.append(row)
    return rows


class ProjectionFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript(store.SCHEMA)

    def emit(self, rows=None):
        rows = records() if rows is None else rows
        self.db.execute('DELETE FROM records')
        for row in rows:
            self.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',
                            (row['id'], row['kind'], row['name'], row['path'],
                             'synthetic', store._json(row).decode()))
        before = list(self.db.execute('SELECT id,payload FROM records ORDER BY id'))
        store._rdf(self.root, [self.db], 'synthetic-snapshot', 'synthetic-run')
        self.assertEqual(before, list(self.db.execute('SELECT id,payload FROM records ORDER BY id')))
        return rows


class PipelineRdfEmissionTests(ProjectionFixture):
    def test_actual_producer_versions_and_opaque_projection_without_optional_libraries(self):
        self.emit()
        text = (self.root / 'ontology.ttl').read_text()
        self.assertEqual(text.count('co:extractorVersion'), 5)
        self.assertEqual(text.count('co:ruleVersion'), 5)
        self.assertIn('co:Symbol, co:SemanticFragment, prov:Entity', text)
        self.assertIn('co:extractorVersion "source-documentation-1"', text)
        self.assertIn('co:extractorVersion "policy-fragments-2"', text)
        for value in ('AST_SENTINEL', 'DOC_SENTINEL', 'businessMeaningVerified'):
            self.assertNotIn(value, text)

    def test_invalid_or_missing_producer_versions_are_not_coerced_into_valid_text(self):
        missing = object()
        for index, kind in enumerate(('symbol', 'callsite', 'framework', 'assertion', 'policy_rule', 'semantic_fragment')):
            for value in (missing, None, 7, True, [], {}, '', ' \t\n'):
                with self.subTest(kind=kind, value=value):
                    rows = records()
                    key = 'extractorVersion' if kind == 'semantic_fragment' else 'ruleVersion'
                    if value is missing: rows[index].pop(key)
                    else: rows[index][key] = value
                    category = 'extractor' if kind == 'semantic_fragment' else 'rule'
                    with self.assertRaisesRegex(store.PipelineError, '^rdf_' + category + '_version_invalid$'):
                        self.emit(rows)

    def test_failed_emission_preserves_existing_export_and_error_hides_value(self):
        self.emit()
        before = {p.name: p.read_bytes() for p in self.root.glob('*.ttl')}
        rows = records()
        rows[-1]['extractorVersion'] = {'PRIVATE_DIAGNOSTIC_SENTINEL': 'not a version'}
        with self.assertRaises(store.PipelineError) as error:
            self.emit(rows)
        self.assertEqual(str(error.exception), 'rdf_extractor_version_invalid')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob('*.ttl')})
        self.assertFalse(list(self.root.glob('.tmp-*')))


@unittest.skipUnless(EXTRAS, EXTRAS_REASON)
class PipelineRdfShapeTests(ProjectionFixture):
    def setUp(self):
        super().setUp()
        self.rows = self.emit()
        self.data = Graph().parse(self.root / 'ontology.ttl', format='turtle')
        self.shapes = Graph().parse(self.root / 'shapes.ttl', format='turtle')

    def subject(self, row):
        return URIRef('urn:code-ontology:record:' + quote(row['id'], safe=''))

    def conforms(self, graph=None):
        good, report, _ = validate(self.data if graph is None else graph,
                                   shacl_graph=self.shapes, inference='none',
                                   advanced=False, js=False, do_owl_imports=False,
                                   meta_shacl=True)
        return bool(good)

    def changed(self):
        graph = Graph()
        graph += self.data
        return graph

    def test_mixed_pipeline_kinds_pass_their_declared_shapes(self):
        self.assertTrue(self.conforms())
        semantic = [row for row in self.rows if row['kind'] == 'semantic_fragment']
        self.assertEqual(set(self.data.subjects(RDF.type, CO.SemanticFragment)),
                         {self.subject(row) for row in semantic})
        for row in semantic:
            subject = self.subject(row)
            self.assertIn((subject, RDF.type, CO.Symbol), self.data)
            self.assertEqual(list(self.data.objects(subject, CO.extractorVersion)),
                             [Literal(row['extractorVersion'])])
            self.assertFalse(list(self.data.objects(subject, CO.ruleVersion)))

    def test_nonsemantic_versions_cannot_be_replaced_by_extractor_versions(self):
        for row in self.rows[:5]:
            with self.subTest(kind=row['kind']):
                graph = self.changed(); subject = self.subject(row)
                graph.remove((subject, CO.ruleVersion, None))
                graph.add((subject, CO.extractorVersion, Literal('synthetic-extractor-1')))
                self.assertFalse(self.conforms(graph))

    def test_missing_semantic_version_cannot_be_replaced_by_rule_version(self):
        for row in self.rows[5:]:
            with self.subTest(category=row['category'], producer=row['extractorVersion']):
                graph = self.changed(); subject = self.subject(row)
                graph.remove((subject, CO.extractorVersion, None))
                graph.add((subject, CO.ruleVersion, Literal('invented-rule-1')))
                self.assertFalse(self.conforms(graph))

    def test_extractor_version_datatype_cardinality_and_nonempty_content(self):
        subject = self.subject(self.rows[-1])
        for values in ([], [Literal('')], [Literal(' \t\n')], [Literal(1)],
                       [URIRef('urn:not-a-version')], [Literal('one'), Literal('two')]):
            with self.subTest(values=values):
                graph = self.changed(); graph.remove((subject, CO.extractorVersion, None))
                for value in values: graph.add((subject, CO.extractorVersion, value))
                self.assertFalse(self.conforms(graph))

    def test_nonsemantic_version_datatype_and_nonempty_content(self):
        for row in self.rows[:5]:
            for value in (Literal(''), Literal(' \t\n'), Literal(3), URIRef('urn:not-a-version')):
                with self.subTest(kind=row['kind'], value=value):
                    graph = self.changed(); subject = self.subject(row)
                    graph.remove((subject, CO.ruleVersion, None)); graph.add((subject, CO.ruleVersion, value))
                    self.assertFalse(self.conforms(graph))

    def test_semantic_typing_cannot_bypass_assertion_or_policy_rule_version(self):
        for row in self.rows[3:5]:
            with self.subTest(kind=row['kind']):
                graph = self.changed(); subject = self.subject(row)
                graph.add((subject, RDF.type, CO.Symbol))
                graph.add((subject, RDF.type, CO.SemanticFragment))
                graph.add((subject, CO.extractorVersion, Literal('synthetic-extractor-1')))
                graph.remove((subject, CO.ruleVersion, None))
                self.assertFalse(self.conforms(graph))

    def test_semantic_typing_retains_symbol_query_surface(self):
        subject = self.subject(self.rows[-1])
        graph = self.changed(); graph.remove((subject, RDF.type, CO.Symbol))
        self.assertFalse(self.conforms(graph))
        graph = self.changed(); graph.remove((subject, RDF.type, CO.SemanticFragment))
        self.assertFalse(self.conforms(graph))

    def test_existing_source_and_provenance_requirements_still_apply_to_all_kinds(self):
        for row in (self.rows[0], self.rows[3], self.rows[4], self.rows[5], self.rows[7]):
            for predicate in (CO.path, CO.sourceDigest, CO.basis, CO.lineStart, CO.lineEnd,
                              PROV.wasGeneratedBy, PROV.wasDerivedFrom):
                with self.subTest(kind=row['kind'], field=str(predicate)):
                    graph = self.changed(); graph.remove((self.subject(row), predicate, None))
                    self.assertFalse(self.conforms(graph))

    def test_existing_relation_requirements_still_apply(self):
        graph = self.changed()
        graph.remove((self.subject(self.rows[3]), CO.subject, None))
        self.assertFalse(self.conforms(graph))

    def test_new_projection_is_only_two_additive_triples_per_semantic_record(self):
        # Independently specify the pre-existing bounded projection. The full
        # expression tree and reviewed comment text have never been RDF parity.
        legacy = Graph()
        run = URIRef('urn:code-ontology:run:synthetic-run')
        for row in self.rows:
            subject = self.subject(row)
            kind = {'assertion': CO.Assertion, 'policy_rule': CO.PolicyRule}.get(row['kind'], CO.Symbol)
            legacy.add((subject, RDF.type, kind)); legacy.add((subject, RDF.type, PROV.Entity))
            legacy.add((subject, CO.label, Literal(row['name'])))
            legacy.add((subject, PROV.wasGeneratedBy, run))
            for key in ('path', 'sourceDigest', 'ruleVersion', 'basis', 'resolution', 'predicate'):
                if key in row: legacy.add((subject, CO[key], Literal(row[key])))
            for key in ('lineStart', 'lineEnd'):
                legacy.add((subject, CO[key], Literal(row['span'][key])))
            legacy.add((subject, PROV.wasDerivedFrom, URIRef('urn:code-ontology:source:' + row['sourceDigest'])))
            for key in ('subject', 'object'):
                if key in row:
                    legacy.add((subject, CO[key], URIRef('urn:code-ontology:record:' + quote(row[key], safe=''))))
        added = set()
        for row in self.rows[5:]:
            added.add((self.subject(row), RDF.type, CO.SemanticFragment))
            added.add((self.subject(row), CO.extractorVersion, Literal(row['extractorVersion'])))
        self.assertEqual(set(self.data) - set(legacy), added)
        self.assertFalse(set(legacy) - set(self.data))


@unittest.skipUnless(EXTRAS, EXTRAS_REASON)
class PipelineRdfIntegrationTests(unittest.TestCase):
    def test_invalid_producer_version_cannot_replace_current_snapshot(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve(); repo = root / 'source'; repo.mkdir()
            source = repo / 'Rules.java'; source.write_text('class Rules {int f(){return 1;}}')
            profile = root / 'profile.json'
            store._atomic(profile, privacy_guard.build_profile([], [], key=b'x' * 32))
            with patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile)}):
                workspace = root / 'workspace'
                before = store.initialize(repo, workspace)['snapshotId']
                write_facts = store._write_facts
                for kind, key in (('symbol', 'ruleVersion'), ('semantic_fragment', 'extractorVersion')):
                    for value in (None, 4, '', '  '):
                        with self.subTest(kind=kind, value=value):
                            source.write_text(source.read_text() + '\n')
                            def corrupt(db, facts):
                                count = write_facts(db, facts)
                                found = db.execute('SELECT id,payload FROM records WHERE kind=? LIMIT 1', (kind,)).fetchone()
                                self.assertIsNotNone(found)
                                row = json.loads(found[1]); row[key] = value
                                db.execute('UPDATE records SET payload=? WHERE id=?', (store._json(row).decode(), found[0]))
                                return count
                            with patch.object(store, '_write_facts', side_effect=corrupt), self.assertRaisesRegex(store.PipelineError, '^rdf_(?:rule|extractor)_version_invalid$'):
                                store.sync(workspace, force=True)
                            self.assertEqual(store.status(workspace)['snapshotId'], before)

    def test_generated_mixed_snapshot_and_readonly_reexport_preserve_record_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve(); repo = root / 'source'; repo.mkdir()
            (repo / 'Rules.java').write_text('/** A synthetic source claim. */\nclass Rules {int adjusted(int n){return n+1;}}')
            (repo / 'rules.py').write_text('def order_discount(total: int) -> int:\n    if total >= 100:\n        return total - 10\n    return total\n')
            profile = root / 'profile.json'
            store._atomic(profile, privacy_guard.build_profile([], [], key=b'x' * 32))
            environment = patch.dict(os.environ, {privacy_guard.PROFILE_ENV: str(profile)})
            environment.start(); self.addCleanup(environment.stop)
            workspace = root / 'workspace'
            result = store.initialize(repo, workspace)
            folder = workspace / 'snapshots' / result['snapshotId']
            rows = list(store.iter_records(workspace))
            self.assertTrue({'symbol', 'assertion', 'policy_rule', 'semantic_fragment'} <= {r['kind'] for r in rows})
            self.assertEqual({r['extractorVersion'] for r in rows if r['kind'] == 'semantic_fragment'},
                             {'policy-fragments-2', 'source-documentation-1', 'policy-function-outcomes-1'})
            data = Graph().parse(folder / 'ontology.ttl', format='turtle')
            shapes = Graph().parse(folder / 'shapes.ttl', format='turtle')
            good, _, _ = validate(data, shacl_graph=shapes, inference='none',
                                  advanced=False, js=False, do_owl_imports=False, meta_shacl=True)
            self.assertTrue(good)
            # Emission is not independent validation; do not silently promote it.
            self.assertEqual(store.status(workspace)['rdfValidation']['shacl'], 'not_run')
            paths = sorted(folder.glob('part-*.sqlite'))
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
            connections = [sqlite3.connect(p.as_uri() + '?mode=ro&immutable=1', uri=True) for p in paths]
            output = root / 'new-export'; output.mkdir()
            try:
                store._rdf(output, connections, result['snapshotId'], 'synthetic-reexport-run')
            finally:
                for connection in connections: connection.close()
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
            self.assertEqual(rows, list(store.iter_records(workspace)))
            projected = Graph().parse(output / 'ontology.ttl', format='turtle')
            # Only the explicitly supplied run linkage differs on re-export.
            self.assertEqual({t for t in data if t[1] != PROV.wasGeneratedBy},
                             {t for t in projected if t[1] != PROV.wasGeneratedBy})
            self.assertEqual((folder / 'shapes.ttl').read_bytes(), (output / 'shapes.ttl').read_bytes())


if __name__ == '__main__':
    unittest.main()
