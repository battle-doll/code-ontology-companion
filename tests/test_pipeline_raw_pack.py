"""Generic shared transport equality and adversarial closed-decoder checks."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/manage-code-ontology/scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline_html as view


class RawPackTests(unittest.TestCase):
    def node(self, body, data):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable; browser remains unverified")
        script = "const fs=require('fs'),vm=require('vm'),s={};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),s);const data=JSON.parse(fs.readFileSync(0,'utf8'));" + body
        result = subprocess.run([node, "-e", script, str(view.ASSETS / "pipeline-raw.js")], input=json.dumps(data),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_all_json_values_markup_proto_unicode_and_raw_json_bytes(self):
        hostile = "</script><script>unexpected()</script> & < > ' ` ${process.exit()}\u2028\u2029 한글 中文 日本語 Русский 😀"
        record = {"id": "synthetic:1", "__proto__": {"ordinary": True}, "constructor": {"prototype": "ordinary"},
                  "values": [None, False, True, -0.0, 2.5, 123, "", hostile, ["o", "a", "s"], {"0": "literal"}],
                  "repeat": [hostile] * 40}
        raw, script = view._raw_page([record], "synthetic-snapshot")
        expected = {"schemaVersion": 1, "snapshotId": "synthetic-snapshot", "records": [record]}
        self.assertEqual(raw, json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
        self.assertIn("CODE_ONTOLOGY_DECODE_RAW_PAGE", script)
        result = self.node("vm.runInNewContext(data.script,s);process.stdout.write(JSON.stringify({page:s.CODE_ONTOLOGY_RAW_PAGE,own:Object.hasOwn(s.CODE_ONTOLOGY_RAW_PAGE.records[0],'__proto__'),negativeZero:Object.is(s.CODE_ONTOLOGY_RAW_PAGE.records[0].values[3],-0),polluted:({}).ordinary===true}));", {"script": script})
        self.assertEqual(result["page"], expected)
        self.assertTrue(result["own"])
        self.assertTrue(result["negativeZero"])
        self.assertFalse(result["polluted"])
        for unsafe in ("</script>", "\u2028", "\u2029"):
            self.assertNotIn(unsafe, script)

    def test_deterministic_encoding_and_short_page_legacy_fallback(self):
        records = [{"id": "short"}]
        raw, script = view._raw_page(records, "s")
        self.assertIn("= JSON.parse(", script)
        self.assertNotIn("CODE_ONTOLOGY_DECODE_RAW_PAGE", script)
        a = {"records": [{"z": "a", "id": "one"}], "snapshotId": "s", "schemaVersion": 1}
        b = {"schemaVersion": 1, "snapshotId": "s", "records": [{"id": "one", "z": "a"}]}
        self.assertEqual(view._pack_raw_value(a), view._pack_raw_value(b))

    def test_json_numbers_preserve_legacy_values_and_overflow_page_fallback(self):
        maximum = int(sys.float_info.max)
        overflow_boundary = maximum + 2 ** 970
        cases = []
        for value, packed in (
            (10 ** 400, False), (-(10 ** 400), False),
            (overflow_boundary, False), (-overflow_boundary, False),
            (overflow_boundary - 1, True), (-(overflow_boundary - 1), True),
            (maximum, True), (-maximum, True),
            (sys.float_info.max, True), (-sys.float_info.max, True),
            (-0.0, True), (True, True), (False, True),
            (9007199254740993, True), (-9007199254740993, True),
        ):
            record = {"id": "neutral:number", "value": value,
                      "padding": ["a repeated neutral transport value"] * 60}
            raw, script = view._raw_page([record], "neutral-snapshot")
            self.assertEqual(raw, json.dumps({"schemaVersion": 1, "snapshotId": "neutral-snapshot", "records": [record]},
                                            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
            self.assertEqual("CODE_ONTOLOGY_DECODE_RAW_PAGE" in script, packed)
            cases.append({"script": script, "raw": raw})
        result = self.node("""
function equal(a,b) {
  if (typeof a==='number' || typeof b==='number') return Object.is(a,b);
  if (a===null || b===null || typeof a!=='object' || typeof b!=='object') return a===b;
  if (Array.isArray(a)!==Array.isArray(b)) return false;
  const ak=Object.keys(a).sort(),bk=Object.keys(b).sort();
  return JSON.stringify(ak)===JSON.stringify(bk) && ak.every(k=>equal(a[k],b[k]));
}
const out=data.map(item=>{
  vm.runInNewContext(item.script,s);
  const actual=s.CODE_ONTOLOGY_RAW_PAGE,expected=JSON.parse(item.raw);
  return {same:equal(actual,expected),infinite:!Number.isFinite(actual.records[0].value),
          negativeZero:Object.is(actual.records[0].value,-0),type:typeof actual.records[0].value};
});
process.stdout.write(JSON.stringify(out));
""", cases)
        self.assertTrue(all(item["same"] for item in result), result)
        self.assertTrue(all(item["infinite"] for item in result[:4]))
        self.assertTrue(all(not item["infinite"] for item in result[4:11]))
        self.assertTrue(result[10]["negativeZero"])
        self.assertEqual([item["type"] for item in result[11:13]], ["boolean", "boolean"])

    def test_closed_tags_keys_references_and_page_shape_reject_invalid_values(self):
        page = {"schemaVersion": 1, "snapshotId": "s", "records": [{"id": "one"}]}
        good = view._pack_raw_value(page)
        cases = [None, [], {}, {**good, "extra": 1}, {**good, "format": "other"},
                 {**good, "strings": ["same", "same"]}, {**good, "root": ["unknown"]},
                 {**good, "root": ["s", -1]}, {**good, "root": ["s", 0.5]},
                 {**good, "root": ["s", len(good["strings"])]}, {**good, "root": ["s", 0, 1]},
                 {**good, "root": ["o", "id"]}, {**good, "root": ["o", "x", 1, "x", 2]},
                 {**good, "root": {"format": "object_not_a_closed_node"}},
                 view._pack_raw_value({**page, "records": [{"id": "same"}, {"id": "same"}]}),
                 view._pack_raw_value({**page, "records": [{"value": 1}]}),
                 view._pack_raw_value({**page, "records": list(range(51))}),
                 view._pack_raw_value({**page, "extra": True})]
        result = self.node("const out=data.map(pack=>{try{s.CODE_ONTOLOGY_DECODE_RAW_PAGE(pack);return 'ACCEPTED';}catch(e){return e.message;}});process.stdout.write(JSON.stringify(out));", cases)
        self.assertTrue(all(value == "html_raw_pack_invalid" for value in result), result)

    def test_existing_record_depth_and_byte_caps_are_enforced(self):
        shallow = {"id": "one", "value": "x" * (512 * 1024)}
        deep = None
        for _ in range(49):
            deep = [deep]
        cases = [view._pack_raw_value({"schemaVersion": 1, "snapshotId": "s", "records": [shallow]}),
                 view._pack_raw_value({"schemaVersion": 1, "snapshotId": "s", "records": [{"id": "one", "value": deep}]})]
        result = self.node("process.stdout.write(JSON.stringify(data.map(pack=>{try{s.CODE_ONTOLOGY_DECODE_RAW_PAGE(pack);return 'ACCEPTED';}catch(e){return e.message;}})));", cases)
        self.assertEqual(result, ["html_raw_pack_budget_exceeded"] * 2)

    def test_valid_depth_boundary_cycles_nonfinite_and_dictionary_budget(self):
        nested = None
        for _ in range(47):
            nested = [nested]
        page = {"schemaVersion": 1, "snapshotId": "s", "records": [{"id": "one", "value": nested}]}
        packed = view._pack_raw_value(page)
        result = self.node("""
const out=[];out.push(s.CODE_ONTOLOGY_DECODE_RAW_PAGE(data).records.length);
const cycle=['a'];cycle.push(cycle);
for(const root of [cycle,NaN,Infinity]){try{s.CODE_ONTOLOGY_DECODE_RAW_PAGE({format:'companion.raw-page-pack.v1',strings:[],root});out.push('ACCEPTED');}catch(e){out.push(e.message);}}
try{s.CODE_ONTOLOGY_DECODE_RAW_PAGE({format:'companion.raw-page-pack.v1',strings:['x'.repeat(32*1024*1024)],root:null});out.push('ACCEPTED');}catch(e){out.push(e.message);}
process.stdout.write(JSON.stringify(out));
""", packed)
        self.assertEqual(result, [1, "html_raw_pack_invalid", "html_raw_pack_invalid", "html_raw_pack_invalid", "html_raw_pack_budget_exceeded"])


if __name__ == "__main__":
    unittest.main()
