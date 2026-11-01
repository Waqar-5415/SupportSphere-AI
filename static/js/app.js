/* SupportSphere AI — shared helpers (loaded on every page) */
(function () {
  "use strict";

  window.$ = (sel, root) => (root || document).querySelector(sel);
  window.$$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  window.icon = function (name, size) {
    size = size || 18;
    const body = (window.ICONS && window.ICONS[name]) || "";
    return '<svg class="icon" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + body + "</svg>";
  };

  window.escapeHtml = function (s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  /* Safe mini-markdown: **bold**, `code`, "- " bullets, paragraphs. Input is HTML-escaped first. */
  window.renderRichText = function (text) {
    const inline = (s) => escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
    let html = "", inList = false;
    String(text).split(/\r?\n/).forEach((raw) => {
      const m = raw.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
      if (m) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + inline(m[1]) + "</li>";
      } else {
        if (inList) { html += "</ul>"; inList = false; }
        if (raw.trim()) html += "<p>" + inline(raw) + "</p>";
      }
    });
    if (inList) html += "</ul>";
    return html;
  };

  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  window.api = async function (url, options) {
    options = options || {};
    const init = {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
    };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    let res;
    try {
      res = await fetch(url, init);
    } catch (e) {
      const err = new Error("Network problem. Please check your connection and try again.");
      err.network = true;
      throw err;
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (res.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); }
    if (!res.ok) {
      const err = new Error((data && data.error) || "Something went wrong. Please try again.");
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  };

  let toastTimer;
  window.toast = function (message, isError) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", !!isError);
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3800);
  };

  /* Inline validation helpers. Error elements: <p data-error-for="fieldName">. "form" = general error. */
  window.clearErrors = function (form) {
    $$("[aria-invalid]", form).forEach((el) => el.removeAttribute("aria-invalid"));
    $$("[data-error-for]", form).forEach((el) => { el.hidden = true; el.textContent = ""; });
  };
  window.showErrors = function (form, errors, general) {
    errors = errors || {};
    Object.keys(errors).forEach((name) => {
      const input = form.querySelector("[name='" + name + "']");
      const out = form.querySelector("[data-error-for='" + name + "']");
      if (input) input.setAttribute("aria-invalid", "true");
      if (out) { out.innerHTML = icon("alert", 16) + "<span>" + escapeHtml(errors[name]) + "</span>"; out.hidden = false; }
    });
    const first = Object.keys(errors)[0];
    if (first) {
      const t = form.querySelector("[name='" + first + "']");
      if (t && t.focus) t.focus();
    }
    if (general || !Object.keys(errors).length) {
      const g = form.querySelector("[data-error-for='form']");
      if (g && general) { g.innerHTML = icon("alert", 16) + "<span>" + escapeHtml(general) + "</span>"; g.hidden = false; }
    }
  };
  window.setBusy = function (btn, busy, label) {
    if (!btn) return;
    if (busy) { btn.dataset.label = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> ' + (label || "Working…"); }
    else { btn.disabled = false; if (btn.dataset.label) btn.innerHTML = btn.dataset.label; }
  };

  /* Show times in the visitor's own time zone */
  function localiseTimes() {
    $$("time[data-local]").forEach((el) => {
      const d = new Date(el.getAttribute("datetime"));
      if (isNaN(d)) return;
      const fmt = el.dataset.fmt;
      let opts = { dateStyle: "medium", timeStyle: "short" };
      if (fmt === "date") opts = { dateStyle: "medium" };
      if (fmt === "short") opts = { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };
      el.textContent = d.toLocaleString([], opts);
      el.title = d.toLocaleString();
    });
  }
  window.formatTime = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  localiseTimes();

  /* Mobile sidebar */
  const openBtn = $("#navOpen"), scrim = $("#scrim");
  function setNav(open) {
    document.body.classList.toggle("nav-open", open);
    if (openBtn) openBtn.setAttribute("aria-expanded", String(open));
  }
  if (openBtn) openBtn.addEventListener("click", () => setNav(!document.body.classList.contains("nav-open")));
  if (scrim) scrim.addEventListener("click", () => setNav(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setNav(false); });

  /* Show / hide password buttons */
  $$("[data-toggle-pw]").forEach((btn) => btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.togglePw);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }));

  /* Dashboard: overall experience rating */
  const exp = $("#experienceForm");
  if (exp) {
    exp.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearErrors(exp);
      const rating = (exp.querySelector("input[name='rating']:checked") || {}).value;
      if (!rating) { showErrors(exp, {}, "Please choose a rating from 1 to 5."); return; }
      try {
        const res = await api("/api/feedback", { method: "POST", body: { kind: "experience", rating: rating, comment: exp.comment.value } });
        toast(res.message);
        exp.reset();
      } catch (ex) { showErrors(exp, {}, ex.message); }
    });
  }
})();
