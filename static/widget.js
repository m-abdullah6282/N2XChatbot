(function () {
  "use strict";

  var CONFIG = window.N2XChatConfig || {};
  var API_BASE = CONFIG.apiBase || "";

  var sessionId = localStorage.getItem("n2x_session_id");
  if (!sessionId) {
    sessionId = "session-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
    localStorage.setItem("n2x_session_id", sessionId);
  }

  var STYLE_ID = "n2x-widget-style";
  var root = document.createElement("div");
  root.id = "n2x-widget";
  root.innerHTML = "";

  function mount() {
    document.body.appendChild(root);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  var style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent =
    "#n2x-widget * { box-sizing: border-box; margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; }" +
    "#n2x-widget { position: fixed; right: 24px; bottom: 24px; z-index: 999999; font-size: 14px; }" +
    "#n2x-launcher { width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer; background: #00C2B8; color: #fff; box-shadow: 0 4px 16px rgba(0, 194, 184, 0.4); display: flex; align-items: center; justify-content: center; transition: transform 0.15s ease; }" +
    "#n2x-launcher:hover { transform: scale(1.08); }" +
    "#n2x-panel { position: fixed; right: 96px; bottom: 24px; width: 320px; max-width: calc(100vw - 104px); height: 360px; max-height: calc(100dvh - 84px); background: #fff; border-radius: 14px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; overflow: hidden; border: 1px solid #e5e7eb; }" +
    "#n2x-panel.hidden { display: none; }" +
    "#n2x-header { background: #00C2B8; color: #fff; padding: 14px 16px; display: flex; align-items: center; gap: 10px; }" +
    "#n2x-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #34d399; flex-shrink: 0; }" +
    "#n2x-agent-select { flex: 1; background: transparent; color: #fff; border: none; font-size: 14px; font-weight: 600; outline: none; cursor: pointer; }" +
    "#n2x-agent-select option { color: #111; }" +
    "#n2x-close { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; line-height: 1; }" +
    "#n2x-messages { flex: 1; overflow-y: auto; padding: 16px; background: #f9fafb; display: flex; flex-direction: column; gap: 10px; }" +
    "#n2x-messages .msg { max-width: 80%; padding: 10px 12px; border-radius: 12px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }" +
    "#n2x-messages .msg.user { align-self: flex-end; background: #00C2B8; color: #fff; border-bottom-right-radius: 3px; }" +
    "#n2x-messages .msg.bot { align-self: flex-start; background: #fff; color: #111; border: 1px solid #e5e7eb; border-bottom-left-radius: 3px; }" +
    "#n2x-messages .msg.typing { color: #6b7280; font-style: italic; }" +
    "#n2x-input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; background: #fff; }" +
    "#n2x-input { flex: 1; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 12px; font-size: 14px; outline: none; }" +
    "#n2x-input:focus { border-color: #00C2B8; }" +
    "#n2x-send { background: #00C2B8; color: #fff; border: none; border-radius: 8px; padding: 0 18px; font-size: 14px; font-weight: 600; cursor: pointer; }" +
    "#n2x-send:hover { background: #0d9488; }" +
    "@media (max-width: 480px) { #n2x-widget { right: 12px; bottom: 12px; } #n2x-panel { right: 84px; bottom: 12px; width: calc(100vw - 96px); height: 340px; max-height: calc(100dvh - 84px); } }";

  document.head.appendChild(style);

  root.innerHTML =
    '<button id="n2x-launcher" aria-label="Open chat">' +
    '  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>' +
    '  </svg>' +
    "</button>" +
    '<div id="n2x-panel" class="hidden">' +
    '  <div id="n2x-header">' +
    '    <span class="dot"></span>' +
    '    <select id="n2x-agent-select" title="Choose agent"></select>' +
    '    <button id="n2x-close" aria-label="Close chat">&times;</button>' +
    "  </div>" +
    '  <div id="n2x-messages"></div>' +
    '  <div id="n2x-input-row">' +
    '    <input id="n2x-input" type="text" placeholder="Apna sawal likho..." autocomplete="off" />' +
    '    <button id="n2x-send">Send</button>' +
    "  </div>" +
    "</div>";

  var launcher = root.querySelector("#n2x-launcher");
  var panel = root.querySelector("#n2x-panel");
  var messagesEl = root.querySelector("#n2x-messages");
  var inputEl = root.querySelector("#n2x-input");
  var sendBtn = root.querySelector("#n2x-send");
  var closeBtn = root.querySelector("#n2x-close");
  var agentSelect = root.querySelector("#n2x-agent-select");

  var agents = [];
  var currentAgentId = null;

  // --- Human handoff reply polling ---
  // The widget normally only shows messages from the live browser session.
  // When a human admin replies to a handoff from the admin panel, that reply
  // is saved server-side as an assistant message. While the chat panel is
  // open we poll a lightweight endpoint every 15s and render any assistant
  // messages newer than our last-seen id, so the user sees the human reply.
  var POLL_MS = 15000;
  var pollTimer = null;
  var pendingOwnRequest = 0;

  function lastSeenKey() {
    return "n2x_last_seen_" + sessionId;
  }

  // The cursor survives page reloads (persisted per session). Anything above
  // it is genuinely new for THIS visitor — e.g. a human reply that arrived
  // while the page was closed — and must not be silently marked as seen.
  var lastSeenMsgId = parseInt(localStorage.getItem(lastSeenKey()), 10) || 0;

  // Forward-only: never lets a stale/out-of-order response drag the cursor
  // backward (which would make polling re-render old messages as "new").
  function advanceCursor(id) {
    if (typeof id !== "number" || isNaN(id)) return;
    if (id > lastSeenMsgId) {
      lastSeenMsgId = id;
      try {
        localStorage.setItem(lastSeenKey(), String(id));
      } catch (e) {}
    }
  }

  async function fetchSessionMessages() {
    try {
      var res = await fetch(API_BASE + "/chat/messages/" + encodeURIComponent(sessionId));
      if (!res.ok) return [];
      return (await res.json()) || [];
    } catch (e) {
      return [];
    }
  }

  function renderNewMessages(msgs) {
    var maxId = lastSeenMsgId;
    msgs.forEach(function (m) {
      if (m.id > maxId) maxId = m.id;
      if (m.id > lastSeenMsgId && m.role === "assistant") addMessage(m.content, "bot");
    });
    advanceCursor(maxId);
  }

  async function pollMessages() {
    var msgs = await fetchSessionMessages();
    if (pendingOwnRequest > 0) {
      // Our own /chat answer arrives via the direct response, which carries
      // its exact message id — that alone advances the cursor. Do NOT touch
      // the cursor here: a human reply inserted while our request was in
      // flight must stay "new" so the next tick renders it.
      return;
    }
    renderNewMessages(msgs);
  }

  function startPolling() {
    if (pollTimer) return;
    pollMessages();
    pollTimer = setInterval(pollMessages, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // First-ever visit for this browser (no stored cursor): adopt whatever
  // history already exists as "seen" so old rows are not replayed. The
  // zero-check at resolve time prevents a slow baseline fetch from marking
  // genuinely new messages (e.g. an early human reply) as seen.
  if (!lastSeenMsgId) {
    fetchSessionMessages().then(function (msgs) {
      if (msgs.length && lastSeenMsgId === 0) {
        advanceCursor(msgs[msgs.length - 1].id);
      }
    });
  }

  function selectAgent(agent) {
    currentAgentId = agent.id;
    localStorage.setItem("n2x_agent_id", String(agent.id));
    messagesEl.innerHTML = '<div class="msg bot">' + (agent.greeting || "Hello!") + "</div>";
  }

  async function loadAgents() {
    try {
      var res = await fetch(API_BASE + "/agents");
      agents = (await res.json()) || [];
    } catch (e) {
      agents = [];
    }
    agents.forEach(function (a) {
      var opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = a.name;
      agentSelect.appendChild(opt);
    });
    if (!agents.length) return;

    var saved = localStorage.getItem("n2x_agent_id");
    var savedId = saved ? parseInt(saved, 10) : null;
    var target = agents.filter(function (a) { return a.id === savedId; })[0] || agents[0];
    agentSelect.value = target.id;
    selectAgent(target);
  }

  agentSelect.addEventListener("change", function () {
    var target = agents.filter(function (a) { return a.id === parseInt(agentSelect.value, 10); })[0];
    if (target) selectAgent(target);
  });

  loadAgents();

  function openPanel() {
    panel.classList.remove("hidden");
    inputEl.focus();
    messagesEl.scrollTop = messagesEl.scrollHeight;
    startPolling();
  }

  function closePanel() {
    panel.classList.add("hidden");
    stopPolling();
  }

  launcher.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);

  function addMessage(text, sender) {
    var el = document.createElement("div");
    el.className = "msg " + sender;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  async function sendQuestion() {
    var question = inputEl.value.trim();
    if (!question) return;

    inputEl.value = "";
    addMessage(question, "user");

    var typingEl = addMessage("Soch raha hoon...", "bot typing");

    pendingOwnRequest++;
    var data = null;
    try {
      var res = await fetch(API_BASE + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, session_id: sessionId, agent_id: currentAgentId }),
      });
      data = await res.json();
      typingEl.classList.remove("typing");
      typingEl.textContent = data.answer || "Koi answer nahi mila.";
    } catch (err) {
      typingEl.classList.remove("typing");
      typingEl.textContent = "Error: server se connect nahi ho paya.";
    }
    // The /chat response carries the exact id of the assistant row it saved
    // (normal answer, fallback, or service-unavailable notice). Advance past
    // it immediately so polling can never mistake our own answer — e.g. a
    // fallback — for a newly arriving message and render it twice.
    if (data && typeof data.message_id === "number") {
      advanceCursor(data.message_id);
    }
    pendingOwnRequest--;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  sendBtn.addEventListener("click", sendQuestion);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendQuestion();
  });
})();
