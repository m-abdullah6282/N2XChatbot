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
    "#n2x-widget { position: fixed; bottom: 20px; right: 20px; z-index: 999999; font-size: 14px; }" +
    "#n2x-launcher { width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer; background: #2563eb; color: #fff; box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4); display: flex; align-items: center; justify-content: center; transition: transform 0.15s ease; }" +
    "#n2x-launcher:hover { transform: scale(1.08); }" +
    "#n2x-panel { position: fixed; bottom: 92px; right: 20px; width: 360px; max-width: calc(100vw - 40px); height: 520px; max-height: calc(100vh - 120px); background: #fff; border-radius: 14px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; overflow: hidden; border: 1px solid #e5e7eb; }" +
    "#n2x-panel.hidden { display: none; }" +
    "#n2x-header { background: #2563eb; color: #fff; padding: 14px 16px; display: flex; align-items: center; gap: 10px; }" +
    "#n2x-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #34d399; }" +
    "#n2x-header .title { font-weight: 600; flex: 1; }" +
    "#n2x-close { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; line-height: 1; }" +
    "#n2x-messages { flex: 1; overflow-y: auto; padding: 16px; background: #f9fafb; display: flex; flex-direction: column; gap: 10px; }" +
    "#n2x-messages .msg { max-width: 80%; padding: 10px 12px; border-radius: 12px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }" +
    "#n2x-messages .msg.user { align-self: flex-end; background: #2563eb; color: #fff; border-bottom-right-radius: 3px; }" +
    "#n2x-messages .msg.bot { align-self: flex-start; background: #fff; color: #111; border: 1px solid #e5e7eb; border-bottom-left-radius: 3px; }" +
    "#n2x-messages .msg.typing { color: #6b7280; font-style: italic; }" +
    "#n2x-input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; background: #fff; }" +
    "#n2x-input { flex: 1; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 12px; font-size: 14px; outline: none; }" +
    "#n2x-input:focus { border-color: #2563eb; }" +
    "#n2x-send { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 0 18px; font-size: 14px; font-weight: 600; cursor: pointer; }" +
    "#n2x-send:hover { background: #1d4ed8; }" +
    "@media (max-width: 480px) { #n2x-panel { right: 10px; bottom: 80px; width: calc(100vw - 20px); } }";

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
    '    <span class="title">N2X Chat Assistant</span>' +
    '    <button id="n2x-close" aria-label="Close chat">&times;</button>' +
    "  </div>" +
    '  <div id="n2x-messages"><div class="msg bot">Hello! Main aapki kaise madad kar sakta hoon?</div></div>' +
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

  function openPanel() {
    panel.classList.remove("hidden");
    inputEl.focus();
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function closePanel() {
    panel.classList.add("hidden");
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

    try {
      var res = await fetch(API_BASE + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, session_id: sessionId }),
      });
      var data = await res.json();
      typingEl.classList.remove("typing");
      typingEl.textContent = data.answer || "Koi answer nahi mila.";
    } catch (err) {
      typingEl.classList.remove("typing");
      typingEl.textContent = "Error: server se connect nahi ho paya.";
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  sendBtn.addEventListener("click", sendQuestion);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendQuestion();
  });
})();
