/* The catalog remains native links; changing UI language never sends a query. */
(function () {
  "use strict";
  const source = document.getElementById("pipeline-map-data");
  const language = document.getElementById("ui-language");
  if (!source || !language) return;
  const copies = JSON.parse(source.textContent);
  const locales = ["ko", "en", "ja", "zh-CN", "ru"];
  const details = document.getElementById("pipeline-map-details");
  const summary = document.getElementById("pipeline-map-summary");
  function update() {
    const locale = locales.includes(language.value) ? language.value : "ko";
    const copy = copies[locale];
    if (!copy) return;
    document.querySelectorAll("[data-pipeline-copy]").forEach(function (element) {
      const value = copy[element.dataset.pipelineCopy];
      if (typeof value === "string") element.textContent = value;
    });
    document.querySelectorAll("[data-pipeline-label]").forEach(function (element) {
      const value = copy[element.dataset.pipelineLabel];
      if (typeof value === "string") { element.setAttribute("aria-label", value); element.setAttribute("title", value); }
    });
    document.querySelectorAll("[data-pipeline-target]").forEach(function (element) {
      const target = element.dataset.pipelineTarget;
      // Only generated sibling filenames and hashed record anchors are valid.
      if (/^[a-z_]+(?:-[0-9]{6})?\.html(?:#r-[a-f0-9]{64})?$/.test(target)) {
        element.setAttribute("href", "../" + locale + "/" + target);
      }
    });
  }
  function close() {
    if (details && details.open) { details.open = false; if (summary) summary.focus(); }
  }
  language.addEventListener("change", update);
  const closeButton = document.getElementById("pipeline-map-close");
  if (closeButton) closeButton.addEventListener("click", close);
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") close(); });
  update();
})();
