"""Synthetic declarations; these are syntax coverage, never runtime proof."""
import hashlib
import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/manage-code-ontology/scripts'))
import pipeline_adapters as adapters


def analyze(path, source, **options):
    return adapters.analyze_file(path, source, hashlib.sha256(source.encode()).hexdigest(), **options)


class AdapterTests(unittest.TestCase):
    def test_each_language_declarations_and_imports(self):
        fixtures = {
            'demo.py': ('import demo\ndef Build():\n    return 1\n', 'Build'),
            'demo.java': ('package demo; import example.Item; public class Build {}', 'Build'),
            'demo.js': ('import React from "react"; export function Build() {}', 'Build'),
            'demo.ts': ('import Item from "demo"; export interface Build {}', 'Build'),
            'demo.sql': ('CREATE TABLE Build (id INTEGER); SELECT id FROM Build;', 'Build'),
            'demo.xml': ('<mapper namespace="demo"><select id="Build">SELECT id FROM items</select></mapper>', 'Build'),
            'demo.vue': ('<template><p>Sample</p></template>\n<script>import Vue from "vue"; function Build() {}</script>', 'Build'),
            'demo.kt': ('import example.Item\nclass Build {}', 'Build'),
            'demo.cs': ('using Example; class Build {}', 'Build'),
            'demo.go': ('package demo\nimport "fmt"\nfunc Build() {}', 'Build'),
            'demo.rs': ('use example::Item; pub struct Build {}', 'Build'),
            'demo.c': ('#include "demo.h"\nstruct Build { int x; };', 'Build'),
            'demo.cpp': ('#include <demo.hpp>\nclass Build {};', 'Build'),
            'demo.php': ('<?php use Example\\Item; class Build {}', 'Build'),
            'demo.swift': ('import Example\nstruct Build {}', 'Build'),
            'demo.dart': ('import "package:demo/item.dart"; class Build {}', 'Build'),
            'demo.rb': ('require "example"\nclass Build\nend', 'Build'),
            'demo.scala': ('import example.Item\nclass Build {}', 'Build'),
            'demo.sh': ('#!/bin/bash\nBuild() { echo safe; }\n', 'Build'),
            'demo.ps1': ('Import-Module Example\nfunction Build { Get-Item . }', 'Build'),
        }
        for path, (source, name) in fixtures.items():
            with self.subTest(path=path):
                facts = analyze(path, source)
                self.assertTrue(any(r['name'] == name for r in facts['records']))
                self.assertFalse(facts['coverage']['semanticComplete'])
                self.assertNotIn('sourceText', json.dumps(facts))
                if path.endswith(('.kt','.cs','.go','.rs','.c','.cpp','.php','.swift','.dart','.rb','.scala')):
                    self.assertTrue(facts['imports'], path)

    def test_comments_and_strings_never_create_declarations(self):
        for extension in ('java','js','ts','kt','cs','go','rs','c','cpp','php','swift','dart','scala'):
            with self.subTest(extension=extension):
                facts = analyze('demo.' + extension, '// class Ghost {}\nconst sample = "class Phantom {}";\n/* function Forged() {} */\n')
                names = [r['name'] for r in facts['records']]
                self.assertNotIn('Ghost', names)
                self.assertNotIn('Phantom', names)
                self.assertNotIn('Forged', names)
        self.assertNotIn('Ghost', [r['name'] for r in analyze('demo.rb', '# class Ghost\nx = "class Phantom"\n')['records']])
        self.assertNotIn('Ghost', [r['name'] for r in analyze('demo.sql', '-- CREATE TABLE Ghost(id int);\n')['records']])

    def test_xml_external_declarations_rejected(self):
        for source in ('<!DOCTYPE mapper SYSTEM "https://example.invalid/x"><mapper/>', '<!DOCTYPE x [<!ENTITY a "x">]><mapper/>'):
            with self.assertRaises(adapters.AdapterError):
                analyze('mapper.xml', source)

    def test_framework_resources_are_opaque_and_scoped(self):
        source = 'from kafka import KafkaProducer\nimport redis\np = KafkaProducer()\np.send("private-topic", value="opaque-payload")\nr = redis.Redis()\nr.set("private-key", "private-value", ex=30)\n'
        a = analyze('one/demo.py', source, resource_key=b'x' * 32)
        b = analyze('two/demo.py', source, resource_key=b'x' * 32)
        encoded = json.dumps(a)
        for value in ('private-topic', 'private-key', 'private-value', 'opaque-payload'):
            self.assertNotIn(value, encoded)
        first = [r['resourceId'] for r in a['records'] if r['kind'] == 'framework']
        second = [r['resourceId'] for r in b['records'] if r['kind'] == 'framework']
        self.assertTrue(first)
        self.assertFalse(set(first) & set(second))
        self.assertTrue(any(r.get('declaredTTLSeconds') == 30 for r in a['records']))

    def test_framework_name_substring_is_not_binding(self):
        for path, source in [('x.js', 'import thing from "notreact";'), ('x.py', 'import redis_fake\nr = redis_fake.Redis()\nr.get("secret")')]:
            self.assertFalse([r for r in analyze(path, source)['records'] if r['kind'] == 'framework'])

    def test_vue_original_lines(self):
        facts = analyze('x.vue', '<script>function First() {}</script>\n<template/>\n<script>function Second() {}</script>')
        self.assertEqual(next(r['span']['lineStart'] for r in facts['records'] if r['name'] == 'Second'), 3)

    def test_budgets_and_invalid_paths_fail_closed(self):
        with self.assertRaises(adapters.AdapterError):
            analyze('x.py', 'x = 1\n' * 100, max_ast_nodes=20)
        with self.assertRaises(adapters.AdapterError):
            analyze('x.java', 'class One {} class Two {}', max_records=2)
        with self.assertRaises(adapters.AdapterError):
            analyze('../escape.py', 'pass')

    def test_extensionless_shell(self):
        self.assertEqual(analyze('build', '#!/usr/bin/env bash\nrun() { echo safe; }\n')['language'], 'Shell')

    def test_explicit_large_ast_budget_preserves_default_and_depth_boundary(self):
        above_default='x = 1\n' * 5000
        self.assertEqual(sum(1 for _ in ast.walk(ast.parse(above_default))),20001)
        with self.assertRaisesRegex(adapters.AdapterError,'ast_budget'):
            analyze('large.py',above_default)
        self.assertEqual(analyze('large.py',above_default,max_ast_nodes=200000)['language'],'Python')
        near_limit='x = 1\n' * 49999 + 'pass\n' * 3
        self.assertEqual(sum(1 for _ in ast.walk(ast.parse(near_limit))),200000)
        self.assertEqual(analyze('large.py',near_limit,max_ast_nodes=200000)['language'],'Python')
        with self.assertRaisesRegex(adapters.AdapterError,'ast_budget'):
            analyze('large.py','x = 1\n' * 50000,max_ast_nodes=200000)
        with self.assertRaisesRegex(adapters.AdapterError,'ast_budget'):
            analyze('deep.py','x = '+ '['*121 + '0' + ']'*121,max_ast_nodes=200000)


if __name__ == '__main__':
    unittest.main()
