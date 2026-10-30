"use strict";
// A bounded JSON transport decoder. Source strings remain inert own data values.
(() => {
  const MAX_PAGE_BYTES = 32 * 1024 * 1024;
  const MAX_RECORD_BYTES = 512 * 1024;
  const MAX_DEPTH = 48;
  const fail = () => { throw new Error("html_raw_pack_invalid"); };
  const budget = () => { throw new Error("html_raw_pack_budget_exceeded"); };
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  function bytes(text) {
    let size = 0;
    for (let index = 0; index < text.length; index++) {
      const code = text.charCodeAt(index);
      if (code < 0x80) size++;
      else if (code < 0x800) size += 2;
      else if (code >= 0xd800 && code <= 0xdbff && index + 1 < text.length
               && text.charCodeAt(index + 1) >= 0xdc00 && text.charCodeAt(index + 1) <= 0xdfff) { size += 4; index++; }
      else size += 3;
      if (size > MAX_PAGE_BYTES) budget();
    }
    return size;
  }
  function decode(pack) {
    if (!pack || typeof pack !== "object" || Array.isArray(pack)
        || Object.keys(pack).length !== 3 || !own(pack, "format") || !own(pack, "strings") || !own(pack, "root")
        || pack.format !== "companion.raw-page-pack.v1" || !Array.isArray(pack.strings)) fail();
    if (pack.strings.length > MAX_PAGE_BYTES) budget();
    let dictionaryBytes = 0;
    const seenStrings = new Set();
    for (const text of pack.strings) {
      if (typeof text !== "string" || seenStrings.has(text)) fail();
      seenStrings.add(text);
      dictionaryBytes += bytes(JSON.stringify(text)) + 1;
      if (dictionaryBytes > MAX_PAGE_BYTES) budget();
    }
    let visited = 0;
    const active = new Set();
    function reference(index) {
      if (!Number.isSafeInteger(index) || index < 0 || index >= pack.strings.length) fail();
      return pack.strings[index];
    }
    function walk(node, depth) {
      if (++visited > MAX_PAGE_BYTES || depth > MAX_DEPTH + 2) budget();
      if (node === null || typeof node === "string" || typeof node === "boolean"
          || (typeof node === "number" && Number.isFinite(node))) {
        return {value: node, size: bytes(JSON.stringify(node))};
      }
      if (!Array.isArray(node) || !node.length || active.has(node)) fail();
      active.add(node);
      const tag = node[0];
      let value, size = 2;
      if (tag === "s") {
        if (node.length !== 2) fail();
        value = reference(node[1]); size = bytes(JSON.stringify(value));
      } else if (tag === "a") {
        value = [];
        for (let index = 1; index < node.length; index++) {
          const child = walk(node[index], depth + 1);
          value.push(child.value); size += child.size + (index > 1 ? 1 : 0);
          if (size > MAX_PAGE_BYTES) budget();
        }
      } else if (tag === "o") {
        if (node.length % 2 !== 1) fail();
        value = {};
        for (let index = 1; index < node.length; index += 2) {
          const key = typeof node[index] === "string" ? node[index] : reference(node[index]);
          if (own(value, key)) fail();
          const child = walk(node[index + 1], depth + 1);
          Object.defineProperty(value, key, {value: child.value, writable: true, enumerable: true, configurable: true});
          size += bytes(JSON.stringify(key)) + 1 + child.size + (index > 1 ? 1 : 0);
          if (size > MAX_PAGE_BYTES) budget();
        }
      } else fail();
      active.delete(node);
      if (size > MAX_PAGE_BYTES) budget();
      return {value, size};
    }
    const page = walk(pack.root, 0).value;
    if (!page || typeof page !== "object" || Array.isArray(page) || Object.keys(page).length !== 3
        || !own(page, "schemaVersion") || !own(page, "snapshotId") || !own(page, "records")
        || page.schemaVersion !== 1 || typeof page.snapshotId !== "string" || !Array.isArray(page.records)
        || page.records.length > 50) fail();
    const ids = new Set();
    for (const record of page.records) {
      if (!record || typeof record !== "object" || Array.isArray(record) || !own(record, "id")
          || typeof record.id !== "string" || !record.id || ids.has(record.id)) fail();
      ids.add(record.id);
      // The producer checks this same pretty-record byte cap before spooling.
      if (bytes(JSON.stringify(record, null, 2)) > MAX_RECORD_BYTES) budget();
    }
    return page;
  }
  Object.defineProperty(globalThis, "CODE_ONTOLOGY_DECODE_RAW_PAGE", {value: decode});
})();
