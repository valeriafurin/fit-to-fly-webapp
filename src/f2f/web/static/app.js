document.addEventListener("click", (e) => {
  const add = e.target.closest("[data-add-panelist]");
  if (add) {
    const body = document.getElementById("panel-rows");
    const count = document.getElementById("panel_count");
    const i = parseInt(count.value, 10);
    const tpl = body.querySelector("tr").cloneNode(true);
    tpl.querySelectorAll("input, select").forEach((el) => {
      el.name = el.name.replace(/panel-\d+-/, `panel-${i}-`);
      if (el.tagName === "INPUT") el.value = "";
    });
    body.appendChild(tpl);
    count.value = i + 1;
  }
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    navigator.clipboard.writeText(copy.dataset.copy).then(() => {
      const old = copy.textContent; copy.textContent = "Copied"; setTimeout(() => (copy.textContent = old), 1200);
    });
  }
});
document.addEventListener("htmx:responseError", (e) => {
  const box = document.getElementById("save-error");
  if (box) { box.textContent = e.detail.xhr.responseText.replace(/<[^>]+>/g, "") || "Save failed"; box.hidden = false; }
});
document.addEventListener("htmx:afterRequest", (e) => {
  const box = document.getElementById("save-error");
  if (box && e.detail.successful) box.hidden = true;
});
