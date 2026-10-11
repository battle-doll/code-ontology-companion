from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "manage-code-ontology" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import large_project


class LargeCatalogLanguageTests(unittest.TestCase):
    def sample(self):
        return {"repositoryLabel": "Example <source>", "catalogSnapshotId": "catalog-fixture", "modules": [
            {"moduleId": "module-example", "root": "src/구조", "snapshotId": "snapshot-one", "sourceFileCount": 2,
             "supportedSourceBytes": 300, "counts": {"nodes": 3, "edges": 4}},
        ]}

    def test_native_language_disclosures_have_translated_full_contract(self):
        page = large_project._catalog_html(self.sample()).decode("utf-8")
        copy = large_project.CATALOG_UI_COPY
        self.assertEqual(set(copy), {"en", "ko", "ja", "zh-CN", "ru"})
        for locale, values in copy.items():
            self.assertEqual(set(values), set(copy["en"]))
            self.assertEqual(len(values["columns"]), 7)
            self.assertEqual(len(values["limitations"]), 4)
            self.assertIn(f'<details lang="{locale}" id="language-{locale}"', page)
            self.assertIn(values["open"], page)
            self.assertIn(values["limitations"][0], page)
        self.assertEqual(len({item["open"] for item in copy.values()}), 5)
        self.assertEqual(len({item["pinned"] for item in copy.values()}), 5)
        self.assertIn("Example &lt;source&gt;", page)
        self.assertEqual(page.count('scope="row">src/구조</th>'), 5)

    def test_pinned_relative_links_carry_only_supported_locale_and_csp_stays_strict(self):
        page = large_project._catalog_html(self.sample()).decode("utf-8")
        hrefs = []

        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    hrefs.extend(value for key, value in attrs if key == "href")

        Links().feed(page)
        self.assertEqual(hrefs, [
            f"../../modules/module-example/snapshots/snapshot-one/graph.html?ui={locale}"
            for locale in ("en", "ko", "ja", "zh-CN", "ru")])
        self.assertIn("script-src 'none'", page)
        self.assertIn("style-src 'none'", page)
        self.assertIn("connect-src 'none'", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<style", page)
        self.assertNotIn("javascript:", page)


if __name__ == "__main__":
    unittest.main()
