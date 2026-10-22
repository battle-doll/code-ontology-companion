"use strict";
// This search inspects only the current bounded page. Queries stay in memory.
(() => {
  const input = document.getElementById("page-search");
  if (!input) return;
  const rows = Array.from(document.querySelectorAll("[data-search-record]"));
  const index = rows.map(node => ({node, text: node.textContent.toLocaleLowerCase()}));
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
