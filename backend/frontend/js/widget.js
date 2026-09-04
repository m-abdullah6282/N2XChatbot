(function () {
  "use strict";

  var CONFIG = window.N2XChatConfig || {};
  var API_BASE = CONFIG.apiBase || "";
  var EMBEDDED = CONFIG.mode === "embedded";
  var LOCKED_AGENT =
    window.N2X_CHAT_AGENT && typeof window.N2X_CHAT_AGENT.id === "number" ? window.N2X_CHAT_AGENT : null;

  var sessionId = localStorage.getItem("n2x_session_id");
  if (!sessionId) {
    sessionId = "session-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
    localStorage.setItem("n2x_session_id", sessionId);
  }

  var STYLE_ID = "n2x-widget-style";
  var root = document.createElement("div");
  root.id = "n2x-widget";
  if (EMBEDDED) root.className = "embedded";
  root.innerHTML = "";

  function mount() {
    if (EMBEDDED && CONFIG.mount) {
      var host = document.getElementById(CONFIG.mount);
      if (host) { host.appendChild(root); return; }
    }
    document.body.appendChild(root);
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", mount); } else { mount(); }

  var style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent =
    "#n2x-widget * { box-sizing: border-box; margin: 0; padding: 0; }" +
    "#n2x-widget { position: fixed; right: 24px; bottom: 24px; z-index: 999999; font-size: 14px; font-family: 'Inter', system-ui, -apple-system, sans-serif; --n2x-color: #2563EB; --n2x-color-dark: #1d4ed8; --n2x-color-light: #eff6ff; }" +

    /* Launcher */
    "#n2x-launcher { width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer; background: var(--n2x-color); color: #fff; box-shadow: 0 4px 20px rgba(37, 99, 235, 0.35); display: flex; align-items: center; justify-content: center; transition: all 0.2s ease; position: relative; }" +
    "#n2x-launcher:hover { transform: scale(1.08); box-shadow: 0 6px 28px rgba(37, 99, 235, 0.45); }" +
    "#n2x-launcher::after { content: ''; position: absolute; inset: -4px; border-radius: 50%; border: 2px solid var(--n2x-color); opacity: 0; animation: n2x-pulse 2s ease-out infinite; }" +
    "@keyframes n2x-pulse { 0% { opacity: 0.5; transform: scale(1); } 100% { opacity: 0; transform: scale(1.3); } }" +

    /* Panel */
    "#n2x-panel { position: fixed; right: 96px; bottom: 24px; width: 380px; max-width: calc(100vw - 48px); height: 520px; max-height: calc(100dvh - 48px); background: #fff; border-radius: 16px; box-shadow: 0 12px 48px rgba(0, 0, 0, 0.18), 0 0 0 1px rgba(0, 0, 0, 0.04); display: flex; flex-direction: column; overflow: hidden; }" +
    "#n2x-panel.hidden { display: none; }" +

    /* Header */
    "#n2x-header { background: var(--n2x-color); color: #fff; padding: 16px 18px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }" +
    "#n2x-header .dot { width: 8px; height: 8px; border-radius: 50%; background: #34d399; flex-shrink: 0; box-shadow: 0 0 6px rgba(52, 211, 153, 0.5); }" +
    "#n2x-agent-select { flex: 1; background: transparent; color: #fff; border: none; font-size: 14px; font-weight: 600; outline: none; cursor: pointer; font-family: inherit; }" +
    "#n2x-agent-select option { color: #111; background: #fff; }" +
    "#n2x-close { background: rgba(255,255,255,0.15); border: none; color: #fff; width: 28px; height: 28px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.15s; flex-shrink: 0; }" +
    "#n2x-close:hover { background: rgba(255,255,255,0.25); }" +
    "#n2x-close svg { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }" +

    /* Messages */
    "#n2x-messages { flex: 1; overflow-y: auto; padding: 16px; background: #f8fafc; display: flex; flex-direction: column; gap: 8px; }" +
    "#n2x-messages .msg { max-width: 82%; padding: 10px 14px; border-radius: 14px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; font-size: 13px; animation: n2x-msg-in 0.2s ease-out; }" +
    "@keyframes n2x-msg-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }" +
    "#n2x-messages .msg.user { align-self: flex-end; background: var(--n2x-color); color: #fff; border-bottom-right-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }" +
    "#n2x-messages .msg.bot { align-self: flex-start; background: #fff; color: #1e293b; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }" +
    "#n2x-messages .msg.typing { color: #94a3b8; font-style: normal; display: flex; align-items: center; gap: 4px; }" +
    "#n2x-messages .msg.typing .dots { display: inline-flex; gap: 3px; }" +
    "#n2x-messages .msg.typing .dots span { width: 6px; height: 6px; border-radius: 50%; background: #94a3b8; animation: n2x-dot 1.2s ease-in-out infinite; }" +
    "#n2x-messages .msg.typing .dots span:nth-child(2) { animation-delay: 0.15s; }" +
    "#n2x-messages .msg.typing .dots span:nth-child(3) { animation-delay: 0.3s; }" +
    "@keyframes n2x-dot { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-4px); } }" +

    /* Input */
    "#n2x-input-row { display: flex; gap: 8px; padding: 14px 16px; border-top: 1px solid #e2e8f0; background: #fff; flex-shrink: 0; }" +
    "#n2x-input { flex: 1; border: 1.5px solid #e2e8f0; border-radius: 10px; padding: 10px 14px; font-size: 13px; outline: none; font-family: inherit; transition: border-color 0.15s; }" +
    "#n2x-input:focus { border-color: var(--n2x-color); box-shadow: 0 0 0 3px var(--n2x-color-light); }" +
    "#n2x-input::placeholder { color: #94a3b8; }" +
    "#n2x-send { background: var(--n2x-color); color: #fff; border: none; border-radius: 10px; padding: 0 18px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; display: flex; align-items: center; gap: 6px; font-family: inherit; }" +
    "#n2x-send:hover { background: var(--n2x-color-dark); }" +
    "#n2x-send:active { transform: scale(0.97); }" +
    "#n2x-send svg { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }" +

    /* Locked label */
    "#n2x-widget .locked-label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 600; }" +

    /* Embedded mode */
    "#n2x-widget.embedded { position: static; inset: auto; width: 100%; height: 100%; }" +
    "#n2x-widget.embedded #n2x-launcher, #n2x-widget.embedded #n2x-close { display: none; }" +
    "#n2x-widget.embedded #n2x-panel { position: static; right: auto; bottom: auto; width: 100%; height: 100%; max-width: none; max-height: none; border: none; border-radius: 0; box-shadow: none; }" +
    "#n2x-widget.embedded #n2x-panel.hidden { display: flex; }" +

    /* Mobile */
    "@media (max-width: 480px) { #n2x-widget { right: 16px; bottom: 16px; } #n2x-panel { right: 16px; bottom: 16px; width: calc(100vw - 32px); height: calc(100dvh - 80px); border-radius: 16px; } }";

  document.head.appendChild(style);

  root.innerHTML =
    '<button id="n2x-launcher" aria-label="Open chat">' +
    '  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>' +
    '  </svg>' +
    '</button>' +
    '<div id="n2x-panel" class="hidden">' +
    '  <div id="n2x-header">' +
    '    <span class="dot"></span>' +
    '    <select id="n2x-agent-select" title="Choose agent"></select>' +
    '    <button id="n2x-close" aria-label="Close chat"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>' +
    '  </div>' +
    '  <div id="n2x-messages"></div>' +
    '  <div id="n2x-input-row">' +
    '    <input id="n2x-input" type="text" placeholder="Apna sawal likho..." autocomplete="off" />' +
    '    <button id="n2x-send"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>Send</button>' +
    '  </div>' +
    '</div>';

  var launcher = root.querySelector("#n2x-launcher");
  var panel = root.querySelector("#n2x-panel");
  var messagesEl = root.querySelector("#n2x-messages");
  var inputEl = root.querySelector("#n2x-input");
  var sendBtn = root.querySelector("#n2x-send");
  var closeBtn = root.querySelector("#n2x-close");
  var agentSelect = root.querySelector("#n2x-agent-select");

  var agents = [];
  var currentAgentId = null;

  var POLL_MS = 15000, pollTimer = null, pendingOwnRequest = 0;
  function lastSeenKey() { return "n2x_last_seen_" + sessionId; }
  var lastSeenMsgId = parseInt(localStorage.getItem(lastSeenKey()), 10) || 0;
  function advanceCursor(id) {
    if (typeof id !== "number" || isNaN(id)) return;
    if (id > lastSeenMsgId) { lastSeenMsgId = id; try { localStorage.setItem(lastSeenKey(), String(id)); } catch (e) {} }
  }
  async function fetchSessionMessages() {
    try { var res = await fetch(API_BASE + "/chat/messages/" + encodeURIComponent(sessionId)); return res.ok ? (await res.json()) || [] : []; }
    catch (e) { return []; }
  }
  function renderNewMessages(msgs) {
    var maxId = lastSeenMsgId;
    msgs.forEach(function (m) { if (m.id > maxId) maxId = m.id; if (m.id > lastSeenMsgId && m.role === "assistant") addMessage(m.content, "bot"); });
    advanceCursor(maxId);
  }
  async function pollMessages() {
    var msgs = await fetchSessionMessages();
    if (pendingOwnRequest > 0) return;
    renderNewMessages(msgs);
  }
  function startPolling() { if (pollTimer) return; pollMessages(); pollTimer = setInterval(pollMessages, POLL_MS); }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  if (!lastSeenMsgId) {
    fetchSessionMessages().then(function (msgs) {
      if (msgs.length && lastSeenMsgId === 0) advanceCursor(msgs[msgs.length - 1].id);
    });
  }

  function applyColor(color) {
    if (!color) color = "#2563EB";
    root.style.setProperty("--n2x-color", color);
    var darker = shadeHex(color, -18);
    root.style.setProperty("--n2x-color-dark", darker || color);
    root.style.setProperty("--n2x-color-light", hexToRgba(color, 0.08));
  }
  function shadeHex(color, percent) {
    var hex = String(color || "").replace("#", "");
    if (hex.length !== 6) return null;
    var num = parseInt(hex, 16), amt = Math.round(2.55 * percent);
    var r = Math.min(255, Math.max(0, (num >> 16) + amt));
    var g = Math.min(255, Math.max(0, ((num >> 8) & 0x00ff) + amt));
    var b = Math.min(255, Math.max(0, (num & 0x0000ff) + amt));
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
  }
  function hexToRgba(hex, alpha) {
    var h = String(hex || "").replace("#", "");
    if (h.length !== 6) return "rgba(37,99,235," + alpha + ")";
    var r = parseInt(h.substring(0, 2), 16), g = parseInt(h.substring(2, 4), 16), b = parseInt(h.substring(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }

  function selectAgent(agent) {
    currentAgentId = agent.id;
    localStorage.setItem("n2x_agent_id", String(agent.id));
    applyColor(agent.primary_color || agent.color || "#2563EB");
    messagesEl.innerHTML = '<div class="msg bot">' + (agent.greeting || "Hello!") + "</div>";
  }

  async function loadAgents() {
    var locked = LOCKED_AGENT;
    if (EMBEDDED && !locked) {
      var pathMatch = window.location.pathname.match(/^\/chat\/([A-Za-z0-9_-]+)\/?$/);
      if (pathMatch) {
        try {
          var listRes = await fetch(API_BASE + "/agents");
          var list = (await listRes.json()) || [];
          var found = list.filter(function (a) { return a.slug === pathMatch[1]; })[0];
          if (found) locked = { id: found.id, name: found.name, greeting: found.greeting, slug: found.slug, primary_color: found.primary_color };
        } catch (e) {}
      }
    }
    if (locked) {
      var label = document.createElement("span");
      label.className = "locked-label";
      label.textContent = locked.name;
      agentSelect.parentNode.replaceChild(label, agentSelect);
      selectAgent(locked);
      return;
    }
    try { var res = await fetch(API_BASE + "/agents"); agents = (await res.json()) || []; } catch (e) { agents = []; }
    agents.forEach(function (a) {
      var opt = document.createElement("option"); opt.value = a.id; opt.textContent = a.name; agentSelect.appendChild(opt);
    });
    if (!agents.length) return;
    var saved = localStorage.getItem("n2x_agent_id"), savedId = saved ? parseInt(saved, 10) : null;
    var target = agents.filter(function (a) { return a.id === savedId; })[0] || agents[0];
    agentSelect.value = target.id;
    selectAgent(target);
  }

  agentSelect.addEventListener("change", function () {
    if (!agentSelect.parentNode) return;
    var target = agents.filter(function (a) { return a.id === parseInt(agentSelect.value, 10); })[0];
    if (target) selectAgent(target);
  });

  loadAgents();
  if (EMBEDDED) startPolling();

  function openPanel() { panel.classList.remove("hidden"); inputEl.focus(); messagesEl.scrollTop = messagesEl.scrollHeight; startPolling(); }
  function closePanel() { panel.classList.add("hidden"); stopPolling(); }

  launcher.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);

  function addMessage(text, sender) {
    var el = document.createElement("div");
    el.className = "msg " + sender;
    if (sender === "typing") {
      el.innerHTML = '<div class="dots"><span></span><span></span><span></span></div>';
    } else {
      el.textContent = text;
    }
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  async function sendQuestion() {
    var question = inputEl.value.trim();
    if (!question) return;
    inputEl.value = "";
    addMessage(question, "user");
    var typingEl = addMessage("", "bot typing");
    pendingOwnRequest++;
    var data = null;
    try {
      var res = await fetch(API_BASE + "/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, session_id: sessionId, agent_id: currentAgentId }),
      });
      if (!res.ok) {
        var errData = null;
        try { errData = await res.json(); } catch (e) {}
        typingEl.classList.remove("typing");
        typingEl.textContent = (errData && errData.answer) || "Server ne jawaab nahi diya. Thodi der baad try karein.";
        if (errData && typeof errData.message_id === "number") advanceCursor(errData.message_id);
        pendingOwnRequest--; messagesEl.scrollTop = messagesEl.scrollHeight; return;
      }
      data = await res.json();
      typingEl.classList.remove("typing");
      typingEl.textContent = data.answer || "Koi answer nahi mila.";
    } catch (err) {
      typingEl.classList.remove("typing");
      typingEl.textContent = "Error: server se connect nahi ho paya.";
    }
    if (data && typeof data.message_id === "number") advanceCursor(data.message_id);
    pendingOwnRequest--;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  sendBtn.addEventListener("click", sendQuestion);
  inputEl.addEventListener("keydown", function (e) { if (e.key === "Enter") sendQuestion(); });
})();
