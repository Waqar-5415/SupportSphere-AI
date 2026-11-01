/* AI chat */
(function () {
  "use strict";
  const app = $("#chatApp");
  const log = $("#chatLog"), form = $("#chatForm"), input = $("#chatInput");
  const sendBtn = $("#sendBtn"), errBox = $("#chatError"), count = $("#chatCount");
  const convList = $("#convList"), titleEl = $("#chatTitle"), clearBtn = $("#clearChat");
  const side = $("#chatSide"), sideToggle = $("#convToggle"), engine = $("#engine");
  const me = { initials: app.dataset.initials, hue: app.dataset.hue };
  const SUGGESTIONS = [
    "How do I reset my password?", "Why was I charged twice?", "How do I enable two-factor authentication?",
    "What's the status of my tickets?",
  ];
  let convId = parseInt(app.dataset.convId, 10) || 0;
  let busy = false;

  const scrollDown = () => { log.scrollTop = log.scrollHeight; };

  function welcome() {
    log.innerHTML =
      '<div class="chat-welcome" id="welcome"><div class="brand-mark">' + icon("sparkles", 30) + "</div>" +
      "<h2>How can I help you today?</h2>" +
      '<p class="muted">Ask about your account, billing, security or technical problems. I can also check the status of your tickets.</p>' +
      '<div class="suggest">' + SUGGESTIONS.map((s) => '<button type="button" class="chip" data-prompt="' + escapeHtml(s) + '">' + escapeHtml(s) + "</button>").join("") + "</div></div>";
    $$(".chip", log).forEach((c) => c.addEventListener("click", () => send(c.dataset.prompt)));
    clearBtn.hidden = true;
  }

  function tagFor(m) {
    if (m.source === "groq") return '<span class="tag t-groq">' + icon("bolt", 12) + " Groq</span>";
    if (m.source === "gemini") return '<span class="tag t-gemini">' + icon("sparkles", 12) + " Gemini</span>";
    if (m.source === "faq") return '<span class="tag t-faq">' + icon("book", 12) + " Help centre</span>";
    return '<span class="tag">No match</span>';
  }

  function addUser(text) {
    const w = $("#welcome"); if (w) w.remove();
    const div = document.createElement("div");
    div.className = "msg user";
    div.innerHTML = '<span class="msg-av" style="--h:' + me.hue + '">' + escapeHtml(me.initials) + '</span><div class="msg-body"><span class="visually-hidden">You said:</span><div class="bubble"></div></div>';
    $(".bubble", div).textContent = text;
    log.appendChild(div);
    scrollDown();
  }

  function addBot(m, question) {
    const w = $("#welcome"); if (w) w.remove();
    $$(".regen", log).forEach((b) => b.remove());
    const div = document.createElement("div");
    div.className = "msg bot";
    div.dataset.id = m.id;
    let meta = tagFor(m);
    if (m.suggest_ticket) {
      meta += '<a class="btn btn-secondary btn-sm" href="/app/tickets?new=1&subject=' + encodeURIComponent((question || "").slice(0, 100)) +
        "&description=" + encodeURIComponent(question || "") + '">' + icon("ticket", 14) + " Open a ticket</a>";
    }
    meta += '<span class="fb" role="group" aria-label="Was this answer helpful?">' +
      '<button type="button" class="up" data-r="helpful" aria-label="Helpful" aria-pressed="' + (m.feedback === "helpful") + '">' + icon("thumb", 15) + "</button>" +
      '<button type="button" class="down" data-r="not_helpful" aria-label="Not helpful" aria-pressed="' + (m.feedback === "not_helpful") + '">' + icon("thumb", 15) + "</button></span>" +
      '<button type="button" class="mini-btn copy">' + icon("copy", 14) + " Copy</button>" +
      '<button type="button" class="mini-btn regen">' + icon("refresh", 14) + " Regenerate</button>";
    div.innerHTML =
      '<span class="msg-av">' + icon("sparkles", 16) + '</span><div class="msg-body"><span class="visually-hidden">Assistant said:</span><div class="bubble">' + renderRichText(m.content) + "</div>" +
      (m.notice ? '<div class="msg-notice">' + escapeHtml(m.notice) + "</div>" : "") + '<div class="msg-meta">' + meta + "</div></div>";
    $$(".fb button", div).forEach((b) => b.addEventListener("click", () => rate(div, m.id, b)));
    $(".copy", div).addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(m.content); toast("Answer copied."); } catch (e) { toast("Could not copy.", true); }
    });
    $(".regen", div).addEventListener("click", () => regenerate());
    log.appendChild(div);
    scrollDown();
  }

  async function rate(div, id, btn) {
    try {
      await api("/api/feedback", { method: "POST", body: { kind: "chat", message_id: id, rating: btn.dataset.r } });
      $$(".fb button", div).forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      toast("Thanks for your feedback!");
    } catch (ex) { toast(ex.message, true); }
  }

  function showTyping() {
    const div = document.createElement("div");
    div.className = "msg bot"; div.id = "typing";
    div.innerHTML = '<span class="msg-av">' + icon("sparkles", 16) + '</span><div class="msg-body"><div class="bubble"><span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span><span class="visually-hidden">Assistant is typing…</span></div></div>';
    log.appendChild(div); scrollDown();
  }
  const hideTyping = () => { const t = $("#typing"); if (t) t.remove(); };

  function lock(v) {
    busy = v; sendBtn.disabled = v; input.setAttribute("aria-busy", String(v));
  }

  async function ensureConversation() {
    if (convId) return convId;
    const res = await api("/api/conversations", { method: "POST", body: {} });
    convId = res.conversation.id;
    history.replaceState(null, "", "/app/chat/" + convId);
    return convId;
  }

  async function send(text) {
    text = (text || "").trim();
    errBox.hidden = true;
    if (busy) return;
    if (!text) { errBox.textContent = "Please type a question before sending."; errBox.hidden = false; input.focus(); return; }
    lock(true);
    try {
      await ensureConversation();
    } catch (ex) { errBox.textContent = ex.message; errBox.hidden = false; lock(false); return; }
    addUser(text);
    input.value = ""; updateCount(); autoGrow();
    clearBtn.hidden = false;
    showTyping();
    try {
      const res = await api("/api/conversations/" + convId + "/messages", { method: "POST", body: { message: text } });
      hideTyping();
      addBot(res.message, text);
      titleEl.textContent = res.conversation.title;
      loadList();
    } catch (ex) {
      hideTyping();
      errBox.textContent = ex.message + " Your message is above — you can send it again.";
      errBox.hidden = false;
      input.value = text; updateCount();
    } finally { lock(false); input.focus(); }
  }

  async function regenerate() {
    if (busy || !convId) return;
    lock(true);
    const last = $$(".msg.bot", log).pop();
    const lastUser = $$(".msg.user .bubble", log).pop();
    const question = lastUser ? lastUser.textContent : "";
    if (last) last.remove();
    showTyping();
    try {
      const res = await api("/api/conversations/" + convId + "/regenerate", { method: "POST", body: {} });
      hideTyping(); addBot(res.message, question);
    } catch (ex) { hideTyping(); toast(ex.message, true); }
    finally { lock(false); }
  }

  async function loadMessages() {
    log.innerHTML = '<p class="muted" style="margin:auto">Loading conversation…</p>';
    try {
      const res = await api("/api/conversations/" + convId + "/messages");
      titleEl.textContent = res.conversation.title;
      log.innerHTML = "";
      if (!res.messages.length) { welcome(); return; }
      clearBtn.hidden = false;
      res.messages.forEach((m, i) => {
        if (m.role === "user") addUser(m.content);
        else { const prev = res.messages[i - 1]; addBot(m, prev ? prev.content : ""); }
      });
    } catch (ex) { welcome(); toast(ex.message, true); }
  }

  async function loadList() {
    try {
      const res = await api("/api/conversations");
      if (!res.conversations.length) { convList.innerHTML = '<p class="muted small" style="padding:.5rem">No conversations yet.</p>'; return; }
      convList.innerHTML = res.conversations.map((c) =>
        '<div class="conv ' + (c.id === convId ? "active" : "") + '"><a href="/app/chat/' + c.id + '" ' + (c.id === convId ? 'aria-current="page"' : "") + ">" + escapeHtml(c.title) + "</a>" +
        '<button class="icon-btn" type="button" data-del="' + c.id + '" aria-label="Delete conversation ' + escapeHtml(c.title) + '">' + icon("trash", 16) + "</button></div>").join("");
      $$("[data-del]", convList).forEach((b) => b.addEventListener("click", () => removeConv(parseInt(b.dataset.del, 10))));
    } catch (ex) { convList.innerHTML = '<p class="muted small" style="padding:.5rem">Could not load conversations.</p>'; }
  }

  async function removeConv(id) {
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    try {
      await api("/api/conversations/" + id, { method: "DELETE" });
      if (id === convId) { location.href = "/app/chat"; return; }
      loadList(); toast("Conversation deleted.");
    } catch (ex) { toast(ex.message, true); }
  }

  const updateCount = () => { count.textContent = input.value.length + " / 1500"; };
  const autoGrow = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 150) + "px"; };

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); } });
  input.addEventListener("input", () => { updateCount(); autoGrow(); });

  clearBtn.addEventListener("click", async () => {
    if (!convId || !confirm("Clear all messages in this conversation?")) return;
    try { await api("/api/conversations/" + convId + "/clear", { method: "POST", body: {} }); welcome(); titleEl.textContent = "New chat"; loadList(); toast("Conversation cleared."); }
    catch (ex) { toast(ex.message, true); }
  });

  if (engine) engine.addEventListener("change", async () => {
    try { await api("/api/me", { method: "PATCH", body: { ai_provider: engine.value } }); toast("AI engine set to " + engine.options[engine.selectedIndex].text.replace("Engine: ", "") + "."); }
    catch (ex) { toast(ex.message, true); }
  });

  if (sideToggle) sideToggle.addEventListener("click", () => {
    const open = side.classList.toggle("open");
    sideToggle.setAttribute("aria-expanded", String(open));
  });

  // Hand-off from other pages: /app/chat?q=...
  const q = new URLSearchParams(location.search).get("q");

  loadList();
  if (convId) loadMessages(); else { welcome(); if (q) send(q); }
  input.focus();
})();
