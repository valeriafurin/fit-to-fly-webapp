function jumpTo(q) {
  q.scrollIntoView({ behavior: "smooth", block: "center" });
  q.querySelector("input[type=radio]").focus({ preventScroll: true });
  q.classList.remove("jump-flash");
  void q.offsetWidth; // restart the highlight animation
  q.classList.add("jump-flash");
}
function renderMissing(missing) {
  const banner = document.getElementById("missing-scores");
  if (!banner) return;
  banner.hidden = !missing.length;
  banner.replaceChildren();
  if (!missing.length) return;
  const n = missing.length;
  const head = document.createElement("b");
  head.textContent = `${n} question${n > 1 ? "s still need" : " still needs"} a score.`;
  const list = document.createElement("ul");
  list.className = "jump-list";
  missing.forEach((q) => {
    const a = document.createElement("a");
    a.href = `#${q.id}`;
    a.dataset.jump = "";
    a.textContent = q.dataset.label;
    const li = document.createElement("li");
    li.appendChild(a);
    list.appendChild(li);
  });
  banner.append(head, " Jump to:", list);
}
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
  const submit = e.target.closest("[data-submit-confirm]");
  if (submit) {
    const missing = [...document.querySelectorAll("[data-question]")].filter((q) => !q.querySelector("input[type=radio]:checked"));
    document.querySelectorAll("[data-question]").forEach((q) => {
      const miss = missing.includes(q);
      q.classList.toggle("missing", miss);
      q.querySelector(".score-error").hidden = !miss;
    });
    renderMissing(missing);
    if (missing.length) {
      e.preventDefault();
      jumpTo(missing[0]);
      return;
    }
    const n = document.querySelectorAll(".note-warn:not([hidden])").length;
    const warn = n ? `${n} note${n > 1 ? "s don't" : " doesn't"} seem to match the score (see the yellow warnings). You can still submit.\n\n` : "";
    if (!confirm(warn + "Submit and lock your assessment? You will receive the PDF by email.")) e.preventDefault();
  }
  const jump = e.target.closest("[data-jump]");
  if (jump) {
    const q = document.getElementById(jump.getAttribute("href").slice(1));
    if (q) { e.preventDefault(); jumpTo(q); }
  }
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    navigator.clipboard.writeText(copy.dataset.copy).then(() => {
      const old = copy.textContent; copy.textContent = "Copied"; setTimeout(() => (copy.textContent = old), 1200);
    });
  }
});
document.addEventListener("change", (e) => {
  const q = e.target.closest("[data-question]");
  if (!q || e.target.type !== "radio") return;
  q.classList.remove("missing");
  q.querySelector(".score-error").hidden = true;
  if (!document.getElementById("missing-scores")?.hidden) renderMissing([...document.querySelectorAll("[data-question].missing")]);
});
document.addEventListener("htmx:responseError", (e) => {
  const box = document.getElementById("save-error");
  if (box) { box.textContent = e.detail.xhr.responseText.replace(/<[^>]+>/g, "") || "Save failed"; box.hidden = false; }
});
document.addEventListener("htmx:afterRequest", (e) => {
  const box = document.getElementById("save-error");
  if (box && e.detail.successful) box.hidden = true;
});
document.addEventListener("DOMContentLoaded", () => {
  // Page came back from the server with skipped questions: jump straight to the first one.
  const first = document.querySelector("[data-question].missing");
  if (first) jumpTo(first);
});
