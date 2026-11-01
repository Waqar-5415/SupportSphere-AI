/* Settings: profile, preferences, password, delete account */
(function () {
  "use strict";

  function applyPrefs(p) {
    document.documentElement.setAttribute("data-theme", p.theme);
    document.documentElement.setAttribute("data-textsize", p.text_size);
  }

  const profile = $("#profileForm");
  profile.addEventListener("submit", async (e) => {
    e.preventDefault(); clearErrors(profile);
    const btn = $("button[type='submit']", profile); setBusy(btn, true, "Saving…");
    try {
      const res = await api("/api/me", { method: "PATCH", body: { name: profile.elements.name.value, email: profile.elements.email.value } });
      toast(res.message);
      $$(".user-chip strong").forEach((el) => { el.textContent = res.user.name; });
    } catch (ex) { showErrors(profile, ex.data && ex.data.errors, ex.data && ex.data.errors ? "" : ex.message); }
    finally { setBusy(btn, false); }
  });

  const pref = $("#prefForm");
  const checked = (n) => (pref.querySelector("input[name='" + n + "']:checked") || {}).value;
  pref.addEventListener("change", (e) => {
    if (e.target.name === "theme" || e.target.name === "text_size") applyPrefs({ theme: checked("theme"), text_size: checked("text_size") });
  });
  pref.addEventListener("submit", async (e) => {
    e.preventDefault(); clearErrors(pref);
    const btn = $("button[type='submit']", pref); setBusy(btn, true, "Saving…");
    try {
      const res = await api("/api/me", { method: "PATCH", body: { theme: checked("theme"), text_size: checked("text_size"), ai_provider: checked("ai_provider") } });
      applyPrefs(res.user); toast(res.message);
    } catch (ex) { showErrors(pref, {}, ex.message); }
    finally { setBusy(btn, false); }
  });

  const pw = $("#pwForm");
  pw.addEventListener("submit", async (e) => {
    e.preventDefault(); clearErrors(pw);
    const btn = $("button[type='submit']", pw); setBusy(btn, true, "Updating…");
    try {
      const res = await api("/api/me/password", { method: "POST", body: { current: pw.current.value, new: pw.new.value } });
      toast(res.message); pw.reset();
    } catch (ex) { showErrors(pw, ex.data && ex.data.errors, ex.data && ex.data.errors ? "" : ex.message); }
    finally { setBusy(btn, false); }
  });

  const del = $("#deleteForm");
  del.addEventListener("submit", async (e) => {
    e.preventDefault(); clearErrors(del);
    if (!confirm("Permanently delete your account and all your data?")) return;
    try {
      await api("/api/me", { method: "DELETE", body: { password: del.password.value } });
      location.href = "/";
    } catch (ex) { showErrors(del, ex.data && ex.data.errors, ex.data && ex.data.errors ? "" : ex.message); }
  });
})();
