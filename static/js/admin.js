/* Admin console: ticket replies, help articles, users, AI connection tests */
(function () {
  "use strict";

  /* ------------------------------------------------------------ ticket detail */
  const reply = $("#adminReply");
  if (reply) {
    reply.addEventListener("submit", async (e) => {
      e.preventDefault(); clearErrors(reply);
      const btn = $("button[type='submit']", reply); setBusy(btn, true, "Sending…");
      try {
        await api("/api/tickets/" + reply.dataset.id + "/replies", { method: "POST", body: { body: reply.body.value, status: $("#replyStatus").value } });
        location.reload();
      } catch (ex) { setBusy(btn, false); showErrors(reply, {}, ex.message); }
    });
    $$("select[data-field]").forEach((sel) => sel.addEventListener("change", async () => {
      try {
        await api("/api/tickets/" + sel.dataset.id, { method: "PATCH", body: { [sel.dataset.field]: sel.value } });
        toast("Ticket updated."); if (sel.dataset.field === "status") setTimeout(() => location.reload(), 400);
      } catch (ex) { toast(ex.message, true); }
    }));
  }

  /* ------------------------------------------------------------ help articles */
  const modal = $("#faqModal");
  if (modal) {
    const form = $("#faqForm"), title = $("#faqModalTitle");
    let lastFocus = null;
    function openModal(faq) {
      clearErrors(form); form.reset();
      form.elements.faq_id.value = faq ? faq.id : "";
      if (faq) { form.question.value = faq.question; form.category.value = faq.category; form.answer.value = faq.answer; form.keywords.value = faq.keywords; }
      title.textContent = faq ? "Edit article" : "New article";
      lastFocus = document.activeElement; modal.hidden = false; form.question.focus();
    }
    function closeModal() { modal.hidden = true; if (lastFocus) lastFocus.focus(); }
    $("#faqNew").addEventListener("click", () => openModal(null));
    $("#faqCancel").addEventListener("click", closeModal);
    modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeModal(); });

    $$(".faq-edit").forEach((b) => b.addEventListener("click", () => openModal(JSON.parse(b.closest("tr").dataset.faq))));
    $$(".faq-del").forEach((b) => b.addEventListener("click", async () => {
      const faq = JSON.parse(b.closest("tr").dataset.faq);
      if (!confirm('Delete the article "' + faq.question + '"?')) return;
      try { await api("/api/admin/faqs/" + faq.id, { method: "DELETE" }); location.reload(); } catch (ex) { toast(ex.message, true); }
    }));
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); clearErrors(form);
      const id = form.elements.faq_id.value;
      const body = { question: form.question.value, category: form.category.value, answer: form.answer.value, keywords: form.keywords.value };
      const btn = $("button[type='submit']", form); setBusy(btn, true, "Saving…");
      try {
        await api(id ? "/api/admin/faqs/" + id : "/api/admin/faqs", { method: id ? "PUT" : "POST", body: body });
        location.reload();
      } catch (ex) { setBusy(btn, false); showErrors(form, ex.data && ex.data.errors, ex.data && ex.data.errors ? "" : ex.message); }
    });
  }

  /* ------------------------------------------------------------ users */
  $$(".user-act").forEach((btn) => btn.addEventListener("click", async () => {
    const body = {};
    if (btn.dataset.role) body.role = btn.dataset.role;
    if (btn.dataset.active !== undefined) body.is_active = btn.dataset.active === "1";
    if (!confirm("Apply this change to the user?")) return;
    try { await api("/api/admin/users/" + btn.dataset.id, { method: "PATCH", body: body }); location.reload(); }
    catch (ex) { toast(ex.message, true); }
  }));

  /* ------------------------------------------------------------ AI connection tests */
  $$(".ai-test").forEach((btn) => btn.addEventListener("click", async () => {
    const out = btn.closest(".prov").querySelector(".ai-result");
    setBusy(btn, true, "Testing…"); out.textContent = "";
    try {
      const res = await api("/api/admin/ai/test", { method: "POST", body: { provider: btn.dataset.provider } });
      out.style.color = res.ok ? "var(--success)" : "var(--danger)";
      out.textContent = (res.ok ? "✓ " : "✗ ") + res.message + (res.ms ? " (" + res.ms + " ms)" : "");
    } catch (ex) { out.style.color = "var(--danger)"; out.textContent = "✗ " + ex.message; }
    finally { setBusy(btn, false); }
  }));
})();
