/* Help Centre: live search, category filter, expandable answers */
(function () {
  "use strict";
  const list = $("#faqList"), empty = $("#faqEmpty"), countEl = $("#faqCount");
  const form = $("#faqSearchForm"), search = $("#faqSearch");
  const chips = $$("#categoryChips .chip");
  const params = new URLSearchParams(location.search);
  let category = "All", openId = params.get("open"), timer, seq = 0;

  function render(faqs) {
    list.innerHTML = "";
    empty.hidden = faqs.length > 0;
    faqs.forEach((f) => {
      const d = document.createElement("details");
      d.className = "faq-item"; d.id = "faq-" + f.id;
      d.innerHTML = '<summary><span class="faq-q"><span>' + escapeHtml(f.question) + '</span><span class="badge badge-neutral plain">' + escapeHtml(f.category) +
        '</span></span></summary><div class="faq-body">' + renderRichText(f.answer) +
        '<p class="small muted" style="margin-top:.6rem">Still stuck? <a href="/app/chat?q=' + encodeURIComponent(f.question) + '">Ask the AI</a> or <a href="/app/tickets?new=1">open a ticket</a>.</p></div>';
      if (openId && String(f.id) === String(openId)) d.open = true;
      list.appendChild(d);
    });
    const q = search.value.trim();
    countEl.textContent = faqs.length + (faqs.length === 1 ? " article" : " articles") + (category !== "All" ? " in " + category : "") + (q ? ' for "' + q + '"' : "");
    if (openId) { const el = document.getElementById("faq-" + openId); if (el) el.scrollIntoView({ block: "center" }); openId = null; }
  }

  async function load() {
    const my = ++seq;
    const qs = new URLSearchParams();
    if (search.value.trim()) qs.set("q", search.value.trim());
    if (category !== "All") qs.set("category", category);
    try {
      const res = await api("/api/faqs?" + qs.toString());
      if (my === seq) render(res.faqs);
    } catch (ex) { toast(ex.message, true); }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(timer); load(); });
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 220); });
  chips.forEach((chip) => chip.addEventListener("click", () => {
    category = chip.dataset.category;
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
    load();
  }));
  load();
})();
