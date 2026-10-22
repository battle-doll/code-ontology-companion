from __future__ import annotations
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"))
from pipeline_shell import analyze_shell


def analyze(text, path="jobs/run.sh", **kwargs):
    return analyze_shell(path, text, hashlib.sha256(text.encode()).hexdigest(), **kwargs)


class ShellAnalysisTests(unittest.TestCase):
    def test_functions_source_pipes_and_guards(self):
        result = analyze('''#!/usr/bin/env bash
source "lib/helpers.sh"
build() { printf '%s' ready | sort; }
if test -f marker; then
  build && printf done
fi
for item in a b; do
  printf '%s' "$item"
done
''')
        records = result["records"]
        functions = [r for r in records if r.get("type") == "Function"]
        self.assertEqual([r["name"] for r in functions], ["build"])
        self.assertEqual(result["imports"], [{"module": "lib/helpers.sh", "name": "", "alias": ""}])
        edges = [r for r in records if r["kind"] == "assertion"]
        self.assertTrue(any(r["predicate"] == "PIPES_TO" for r in edges))
        self.assertTrue(any(r["predicate"] == "MAY_CALL" and r["object"] == functions[0]["id"] for r in edges))
        self.assertEqual({r["name"] for r in records if r.get("type") == "ControlFlow"}, {"if", "for"})
        self.assertFalse(result["coverage"]["semanticComplete"])

    def test_arguments_comments_heredoc_and_quoted_operators_are_data(self):
        result = analyze('''# fake() { dangerous; }
printf '$(hidden)' '|' "source other.sh"
cat <<'END'
evil() { fake-command; }
source secret.sh
END
printf done
''')
        names = [r["name"] for r in result["records"]]
        self.assertNotIn("evil", names)
        self.assertNotIn("fake-command", names)
        self.assertNotIn("PIPES_TO", names)
        self.assertNotIn("DynamicSubstitution", names)
        self.assertFalse(result["imports"])

    def test_substitution_eval_and_dynamic_source_are_unresolved(self):
        result = analyze('''VALUE=$(unobserved-command)
source "$LIBRARY"
eval "$COMMAND"
$COMMAND argument
''')
        names = [r["name"] for r in result["records"]]
        self.assertNotIn("unobserved-command", names)
        self.assertIn("DynamicSubstitution", names)
        self.assertIn("DynamicSource", names)
        self.assertIn("ExternalExecution", names)
        self.assertIn("DynamicCommand", names)
        self.assertFalse(result["imports"])

    def test_values_and_absolute_source_paths_never_persist(self):
        result = analyze('''INTERNAL_VALUE='not-for-ontology'
source /opt/internal/private.sh
printf '%s' 'private-argument'
''')
        rendered = str(result)
        for secret in ("not-for-ontology", "/opt/internal", "private-argument"):
            self.assertNotIn(secret, rendered)
        self.assertIn("INTERNAL_VALUE", rendered)

    def test_powershell_comments_strings_and_here_strings(self):
        result = analyze('''# function Fake { }
function Invoke-Task { }
Import-Module SyntheticModule
$text = @'
function Hidden { }
'@
"function Quoted { }"
<# function Commented { } #>
''', "jobs/run.ps1")
        names = [r["name"] for r in result["records"]]
        self.assertIn("Invoke-Task", names)
        self.assertNotIn("Hidden", names)
        self.assertNotIn("Quoted", names)
        self.assertNotIn("Commented", names)
        self.assertEqual(result["imports"][0]["module"], "SyntheticModule")

    def test_determinism_and_budgets(self):
        source = "task() { printf ok; }\ntask\n"
        self.assertEqual(analyze(source), analyze(source))
        with self.assertRaises(ValueError):
            analyze(source, max_records=2)
        with self.assertRaises(ValueError):
            analyze(source, max_ast_nodes=2)
        with self.assertRaises(ValueError):
            analyze(source, path="../escape.sh")

    def test_multiline_quote_and_unrecognized_heredoc_never_create_commands(self):
        for text in ('printf "%s" "\nsynthetic_fake() { synthetic_hidden; }\n"\n',
                     "cat <<'END-TEXT'\nsynthetic_fake() { synthetic_hidden; }\nEND-TEXT\n",
                     "cat <<'NON STANDARD'\nsynthetic_fake() { synthetic_hidden; }\nNON STANDARD\n"):
            names = [r["name"] for r in analyze(text)["records"]]
            self.assertNotIn("synthetic_fake", names)
            self.assertNotIn("synthetic_hidden", names)
