from __future__ import annotations

import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('incremental_core', ROOT/'skills/manage-code-ontology/scripts/code_ontology_core.py')
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def semantic(value):
    result = copy.deepcopy(value)
    result.pop('generated_at', None)
    return result


class IncrementalAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ontology-incremental-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base/'source'
        self.repo.mkdir()
        self.cache = self.base/'private-cache'

    def write(self, relative, text):
        path = self.repo/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def build(self, roots=None):
        stats = {}
        actual = core.build_document(self.repo, roots, cache_directory=self.cache, build_stats=stats)
        expected = core.build_document(self.repo, roots)
        self.assertEqual(semantic(expected), semantic(actual))
        return actual, stats

    def test_cold_warm_change_delete_and_import_reconciliation(self):
        self.write('pkg/__init__.py', '')
        self.write('pkg/a.py', 'from .b import target as chosen\ndef call():\n    chosen()\n')
        self.write('pkg/b.py', 'def target():\n    return 1\n')
        _, cold = self.build()
        self.assertEqual(3, cold['parsedFiles'])
        _, warm = self.build()
        self.assertEqual(3 if os.name == 'nt' else 0, warm['parsedFiles'])
        if os.name == 'nt':
            self.assertFalse(self.cache.exists())
            self.assertEqual('windows_private_cache_unavailable', warm['cacheDisabledReason'])
        self.write('pkg/b.py', 'def renamed():\n    return 2\n')
        _, changed = self.build()
        self.assertEqual(3 if os.name == 'nt' else 1, changed['parsedFiles'])
        (self.repo/'pkg/b.py').unlink()
        self.build()
        self.write('pkg/c.py', 'def target():\n    return 3\n')
        self.write('pkg/a.py', 'from .c import target as chosen\ndef call():\n    chosen()\n')
        self.build()

    def test_scope_and_package_identity_invalidates_context(self):
        self.write('src/pkg/a.py', 'def read():\n    return 1\n')
        self.build(['src'])
        self.write('src/__init__.py', '')
        _, changed = self.build(['src'])
        self.assertEqual(2, changed['parsedFiles'])
        self.build(['src/pkg'])

    def test_java_shadowing_type_index_and_duplicate_declarations(self):
        self.write('src/A.java', 'package demo; import org.springframework.stereotype.*; @Service public class A { void work() {} }')
        self.build()
        self.write('src/Service.java', 'package demo; public @interface Service {}')
        _, result = self.build()
        self.assertEqual(2, result['parsedFiles'])
        self.write('copy/A.java', 'package demo; public class A {}')
        with self.assertRaises(core.DuplicateDeclarationError):
            core.build_document(self.repo, cache_directory=self.cache)

    def test_syntax_warnings_and_shadowed_calls_match_full_build(self):
        self.write('bad.py', 'def incomplete(\n')
        self.write('ok.py', 'def same():\n    return 1\ndef outer(same):\n    return same()\n')
        self.build()
        self.build()
        self.write('bad.py', 'def complete():\n    return 2\n')
        self.build()

    @unittest.skipIf(os.name == 'nt', 'Windows safely uses full analysis without private cache writes')
    def test_corrupt_cache_is_rejected_and_reparsed(self):
        self.write('sample.py', 'def correct():\n    return 1\n')
        self.build()
        fragment = next(self.cache.glob('*.json'))
        fragment.write_text('{"forged":"data"}', encoding='utf-8')
        _, stats = self.build()
        self.assertEqual(1, stats['cacheRejected'])
        self.assertEqual(1, stats['parsedFiles'])

    @unittest.skipIf(os.name == 'nt', 'Windows safely uses full analysis without private cache writes')
    def test_linked_cache_and_profile_readable_by_others_fail_closed(self):
        self.write('sample.py', 'def correct():\n    return 1\n')
        outside = self.base/'outside'
        outside.mkdir()
        self.cache.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(core.OntologyError):
            core.build_document(self.repo, cache_directory=self.cache)
        self.cache.unlink()
        self.build()
        (self.cache/'key.bin').chmod(0o644)
        with self.assertRaises(core.OntologyError):
            core.build_document(self.repo, cache_directory=self.cache)

    def test_analyzer_version_invalidates_cached_operations(self):
        self.write('sample.py', 'def correct():\n    return 1\n')
        self.build()
        with patch.object(core, 'PLUGIN_VERSION', '99.0.0'):
            _, stats = self.build()
        self.assertEqual(1, stats['parsedFiles'])


if __name__ == '__main__':
    unittest.main()
