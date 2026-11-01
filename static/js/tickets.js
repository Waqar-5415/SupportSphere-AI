/* Tickets: create (list page) and reply / close (detail page) */
(function () {
  "use strict";

  /* ------------------------------------------------------------ list page: new ticket */
  const form = $("#ticketForm");
  if (form) {
    const panel = $("#newTicket"), toggle = $("#toggleNew"), desc = $("#description"), counter = $("#descCount");
    const submit = $("#ticketSubmit");
    const params = new URLSearchParams(location.search);

    function openPanel(open) {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) { panel.scrollIntoView({ block: "start", behavior: "smooth" }); $("#subject").focus({ preventScroll: true }); }
    }
    toggle.addEventListener("click", () => openPanel(panel.hidden));
    $("#cancelNew").addEventListener("click", () => { form.reset(); clearErrors(form); updateCount(); openPanel(false); toggle.focus(); });
    const emptyBtn = $("#emptyNew"); if (emptyBtn) emptyBtn.addEventListener("click", () => openPanel(true));

    const updateCount = () => { counter.textContent = desc.value.length + " / 2000"; };
    desc.addEventListener("input", updateCount);

    if (params.get("subject")) $("#subject").value = params.get("subject").slice(0, 120);
    if (params.get("description")) { desc.value = params.get("description").slice(0, 2000); updateCount(); }
    if (params.get("new") || params.get("subject") || params.get("description")) openPanel(true);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearErrors(form);
      const body = {
        subject: form.subject.value, category: form.category.value, description: form.description.value,
        priority: (form.querySelector("input[name='priority']:checked") || {}).value || "",
      };
      setBusy(submit, true, "Submitting…");
      try {
        const res = await api("/api/tickets", { method: "POST", body: body });
        location.href = "/app/tickets/" + res.ticket.id;
      } catch (ex) {
        setBusy(submit, false);
        showErrors(form, ex.data && ex.data.errors, ex.data && ex.data.errors ? "" : ex.message);
      }
    });
  }

  /* ------------------------------------------------------------ detail page */
  const reply = $("#replyForm");
  if (reply) {
    reply.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearErrors(reply);
      const btn = $("button[type='submit']", reply);
      setBusy(btn, true, "Sending…");
      try {
        await api("/api/tickets/" + reply.dataset.id + "/replies", { method: "POST", body: { body: reply.body.value } });
        location.reload();
      } catch (ex) { setBusy(btn, false); showErrors(reply, {}, ex.message); }
    });
  }
  const closeBtn = $("#closeTicket");
  if (closeBtn) closeBtn.addEventListener("click", async () => {
    if (!confirm("Close this ticket? You can re-open it later by replying.")) return;
    try { await api("/api/tickets/" + closeBtn.dataset.id, { method: "PATCH", body: { status: "Closed" } }); location.reload(); }
    catch (ex) { toast(ex.message, true); }
  });
})();
