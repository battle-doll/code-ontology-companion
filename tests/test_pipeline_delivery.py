from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/manage-code-ontology/scripts"))
import companion
import pipeline_access as access
import pipeline_delivery as delivery


def restore(graph):
    """Independent source-free consumer of the advertised wire format."""
    if graph["format"] != "companion.flat-json.v1":
        raise ValueError("unknown format")

    def value(item):
        if not isinstance(item, dict):
            return item
        node = graph["nodes"][item["$ref"]]
        if node["type"] == "object":
            return {key: value(child) for key, child in node["entries"]}
        return [value(child) for child in node["items"]]

    result = value({"$ref": graph["root"]})
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if hashlib.sha256(encoded.encode()).hexdigest() != graph["originalSha256"]:
        raise ValueError("original digest mismatch")
    return result


class PipelineDeliveryTests(unittest.TestCase):
    def response(self, expression):
        return {"status": "ok", "snapshotId": "ps-synthetic", "data": {"records": [{
            "id": "semantic:synthetic", "kind": "semantic_fragment", "sourceDigest": "a" * 64,
            "span": {"lineStart": 4, "lineEnd": 9}, "status": "runtime_unknown",
            "expression": expression}], "total": 1, "returned": 1, "offset": 0, "truncated": False}}

    def deep(self):
        expression = {"op": "literal", "value": "한글", "$ref": 9, "empty": [], "object": {},
                      "scalars": [None, True, False, 3, 2.5]}
        for _ in range(45):
            expression = {"op": "binary", "left": expression, "right": {"op": "name", "name": "threshold"}}
        return expression

    def test_round_trip_original_identity_source_binding_and_unchanged_input(self):
        original = self.response(self.deep())
        before = copy.deepcopy(original)
        with self.assertRaisesRegex(companion.CompanionError, "structural budget"):
            access.bounded_json(original, output=True)
        projected = delivery.normalize_response(original)
        access.project(projected)
        row = projected["data"]["records"][0]
        graph = row["expression"]
        self.assertEqual(restore(graph), original["data"]["records"][0]["expression"])
        self.assertEqual(graph["sourceBinding"], {"snapshotId": "ps-synthetic", "recordId": "semantic:synthetic",
            "sourceDigest": "a" * 64, "jsonPointer": "/data/records/0/expression"})
        self.assertEqual(original, before)
        self.assertEqual(projected, delivery.normalize_response(projected))
        for key in set(row) - {"expression"}:
            self.assertEqual(row[key], original["data"]["records"][0][key])

    def test_shallow_legacy_shape_and_pagination_unchanged(self):
        value = self.response({"op": "name", "name": "eligible"})
        self.assertEqual(delivery.normalize_response(value), value)

    def test_generic_deep_nonexpression_field_is_lossless(self):
        value = self.response(None)
        row = value["data"]["records"][0]
        row["control/graph~"] = self.deep()
        projected = delivery.normalize_response(value)
        graph = projected["data"]["records"][0]["control/graph~"]
        self.assertEqual(restore(graph), row["control/graph~"])
        self.assertEqual(graph["sourceBinding"]["jsonPointer"], "/data/records/0/control~1graph~0")

    def test_original_collection_and_output_limits_remain_enforced(self):
        for expression in ({str(index): index for index in range(257)}, list(range(10_001)), "x" * 16_385):
            with self.subTest(kind=type(expression).__name__), self.assertRaises(companion.CompanionError):
                access.project(delivery.normalize_response(self.response(expression)))
        for expression in (float("nan"), 10 ** 101, ["x" * 16_000] * 20, [None] * 9999 + [None] * 9999):
            with self.subTest(kind=type(expression).__name__), self.assertRaises((companion.CompanionError, ValueError)):
                access.project(delivery.normalize_response(self.response(expression)))

    def test_flat_projection_does_not_increase_output_node_budget(self):
        expression = [{"left": index, "right": index + 1, "active": True} for index in range(1500)]
        for _ in range(20):
            expression = {"nested": expression}
        with self.assertRaisesRegex(companion.CompanionError, "structural budget"):
            access.project(delivery.normalize_response(self.response(expression)))

    def test_flat_nodes_remain_under_privacy_guard(self):
        expression = self.deep()
        expression["private"] = "sk-proj-" + ("x" * 40)
        with self.assertRaises(companion.privacy_guard.PrivacyError):
            access.project(delivery.normalize_response(self.response(expression)))
