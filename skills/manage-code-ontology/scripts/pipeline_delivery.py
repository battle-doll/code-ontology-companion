"""Lossless read-only wire projection of deep sealed JSON values.

``companion.flat-json.v1`` replaces only deep containers. ``root`` and every
``{"$ref": N}`` address an index in ``nodes``. Object nodes have ordered
``entries`` pairs; array nodes have ordered ``items``. Values are JSON scalars
or references, never inline containers. Thus even an original ``$ref`` key is
unambiguous. Rebuilding the root restores the exact JSON value (including key
order), whose canonical UTF-8 JSON SHA-256 is ``originalSha256``. ``sourceBinding``
pins the enclosing snapshot, record and original JSON pointer; existing source
locators/authority/limitations stay in their original record.

This does not change snapshot files, expression semantics, or delivery budgets.
The caller must apply its ordinary size, structure and privacy checks afterwards.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import companion

FORMAT = "companion.flat-json.v1"


def _inspect(value: Any) -> dict[int, int]:
    """Check original scalar/collection limits and compute container depths.

    Iteration avoids consuming the Python stack on a sealed nested expression.
    The unchanged output node/byte/depth budget is also checked after projection.
    """
    depths: dict[int, int] = {}
    pending = [(value, False)]
    remaining = 20_000
    while pending:
        item, visited = pending.pop()
        if visited:
            children = item.values() if isinstance(item, dict) else item
            depths[id(item)] = 1 + max((depths.get(id(child), 0) for child in children), default=0)
            continue
        remaining -= 1
        if remaining < 0:
            raise companion.CompanionError("Pipeline JSON exceeds its structural budget.")
        if isinstance(item, dict):
            if len(item) > 256:
                raise companion.CompanionError("Pipeline object exceeds its field budget.")
            if any(not isinstance(key, str) or len(key) > 200 for key in item):
                raise companion.CompanionError("Invalid pipeline field.")
            pending.append((item, True))
            pending.extend((child, False) for child in reversed(list(item.values())))
        elif isinstance(item, list):
            if len(item) > 10_000:
                raise companion.CompanionError("Pipeline list exceeds its item budget.")
            pending.append((item, True))
            pending.extend((child, False) for child in reversed(item))
        elif isinstance(item, str) and len(item) > 16_384:
            raise companion.CompanionError("Pipeline text exceeds its size budget.")
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise companion.CompanionError("Invalid pipeline JSON value.")
    return depths


def _flat(value: Any, binding: dict) -> dict:
    nodes: list[dict] = []
    pending: list[tuple[Any, int]] = []

    def reference(item):
        if not isinstance(item, (dict, list)):
            return item
        index = len(nodes)
        nodes.append({})
        pending.append((item, index))
        return {"$ref": index}

    root = reference(value)["$ref"]
    while pending:
        item, index = pending.pop()
        if isinstance(item, dict):
            nodes[index] = {"type": "object", "entries": [[key, reference(child)] for key, child in item.items()]}
        else:
            nodes[index] = {"type": "array", "items": [reference(child) for child in item]}
    original = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return {"format": FORMAT, "root": root, "nodes": nodes,
            "originalSha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "sourceBinding": binding}


def normalize_response(value: dict) -> dict:
    """Preserve the public envelope and shallow records, flatten deep fields.

    Begin below the envelope/page/record collection so ordinary callers retain
    record IDs, counts, pagination and source evidence at their existing paths.
    No data is sampled, omitted, truncated or written back to a sealed snapshot.
    """
    depths = _inspect(value)
    snapshot = value.get("snapshotId")

    def visit(item, path, depth, record):
        if isinstance(item, dict):
            if isinstance(item.get("id"), str):
                record = item
            result = {}
            for key, child in item.items():
                pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if depth >= 3 and depths.get(id(child), 0) > 12:
                    binding = {"snapshotId": snapshot, "jsonPointer": pointer}
                    if record is not None:
                        for original, projected in (("id", "recordId"), ("sourceDigest", "sourceDigest"),
                                                     ("sourceAssertionIds", "sourceAssertionIds")):
                            if original in record:
                                binding[projected] = record[original]
                    result[key] = _flat(child, binding)
                else:
                    result[key] = visit(child, pointer, depth + 1, record)
            return result
        if isinstance(item, list):
            return [visit(child, path + "/" + str(index), depth + 1, record) for index, child in enumerate(item)]
        return item

    return visit(value, "", 0, None)
