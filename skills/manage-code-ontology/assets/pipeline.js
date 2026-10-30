"use strict";
// This search inspects only the current bounded page. Queries stay in memory.
(() => {
  const input = document.getElementById("page-search");
  if (!input) return;
  const rows = Array.from(document.querySelectorAll("[data-search-record]"));
  // One language-neutral data page is loaded by a preceding deferred script.
  // Text-only insertion keeps raw source syntax inert, including markup-like values.
  const page = globalThis.CODE_ONTOLOGY_RAW_PAGE;
  const validPage = page && page.schemaVersion === 1 && typeof page.snapshotId === "string"
    && Array.isArray(page.records) && page.records.length <= 50
    && page.records.every(record => record && typeof record === "object" && typeof record.id === "string")
    && new Set(page.records.map(record => record.id)).size === page.records.length;
  const records = new Map(validPage ? page.records.map(record => [record.id, record]) : []);
  const index = rows.map(node => {
    const pre = node.querySelector ? node.querySelector("[data-raw-record]") : null;
    let raw = "";
    if (pre && validPage && pre.dataset.rawSnapshot === page.snapshotId && records.has(pre.dataset.rawRecord)) {
      const record = records.get(pre.dataset.rawRecord);
      raw = JSON.stringify(record);
      const details = pre.closest("details");
      let displayed = false;
      const display = () => {
        if (!displayed && details.open) {
          pre.textContent = JSON.stringify(record, null, 2);
          displayed = true;
        }
      };
      details.addEventListener("toggle", display);
      display();
    }
    // Include every raw value even while its details panel stays collapsed.
    // Missing or mismatched data retains the localized notice and static JSON link.
    return {node, text: (node.textContent + "\n" + raw).toLocaleLowerCase()};
  });
  const count = document.getElementById("search-count");
  const empty = document.getElementById("search-empty");
  let timer;
  function filter() {
    const term = input.value.toLocaleLowerCase().trim();
    let visible = 0;
    for (const item of index) {
      item.node.hidden = !item.text.includes(term);
      if (!item.node.hidden) visible++;
    }
    count.textContent = `${visible} / ${rows.length}`;
    empty.hidden = visible !== 0;
  }
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(filter, 120);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      clearTimeout(timer);
      input.value = "";
      filter();
    }
  });
  filter();
})();
