/**
 * RCM tab controller — static/chatbot/index.html's dedicated RCM chat panel.
 * Close copy of hr-tab.js, pointed at /chatbot/rcm/chat/stream instead of
 * /chatbot/chat/stream. Reuses the exact same `.hr-*` CSS classes (they're
 * already generic, not HR-specific) under `rcm-*` element ids, and the same
 * shared streaming/markdown helpers in chat-core.js.
 */
(function () {
  "use strict";

  const Core = window.JHSChatCore;
  const BOT_SVG = '<svg viewBox="0 0 120 60" xmlns="http://www.w3.org/2000/svg"><text x="60" y="43" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-weight="800" font-size="40" letter-spacing="-1" fill="#ffffff">JHS</text></svg>';

  let sessionId = sessionStorage.getItem("rcm_tab_session_id") || crypto.randomUUID();
  sessionStorage.setItem("rcm_tab_session_id", sessionId);

  let isLoading = false;
  let typingRow = null;
  let initialized = false;

  let messagesEl, welcomeEl, inputEl, sendBtn, errToast;

  function initRcmTab() {
    if (initialized) return;
    initialized = true;

    messagesEl = document.getElementById("rcm-messages");
    welcomeEl = document.getElementById("rcm-welcome");
    inputEl = document.getElementById("rcm-input");
    sendBtn = document.getElementById("rcm-send-btn");
    errToast = document.getElementById("rcm-error-toast");

    document.querySelectorAll("#cbtab-rcm .hr-sugg-btn").forEach((btn) => {
      btn.addEventListener("click", () => sendRcmMessage(btn.dataset.q));
    });

    inputEl.addEventListener("input", () => {
      inputEl.style.height = "auto";
      inputEl.style.height = Math.min(inputEl.scrollHeight, 130) + "px";
    });
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendRcmMessage(inputEl.value);
      }
    });
    sendBtn.addEventListener("click", () => sendRcmMessage(inputEl.value));

    if (window.jhsUserName) applyGreeting(window.jhsUserName);
    const prevHook = window.onJhsGreetingReady;
    window.onJhsGreetingReady = (name) => {
      if (prevHook) prevHook(name);
      applyGreeting(name);
    };

    loadSessionMessages(sessionId);
  }
  window.initRcmTab = initRcmTab;

  function applyGreeting(name) {
    const titleEl = document.getElementById("rcm-welcome-title");
    if (titleEl) titleEl.textContent = `Hi ${name} 👋`;
  }

  function rcmActivateSidebar() {
    if (!window.CbSidebar) return;
    window.CbSidebar.attach({
      activeSessionId: sessionId,
      onNewChat: startNewRcmChat,
      fetchSessions: () => Core.api("GET", "/chatbot/rcm/sessions"),
      onSelect: (id) => {
        sessionId = id;
        sessionStorage.setItem("rcm_tab_session_id", id);
        loadSessionMessages(id);
      },
    });
  }
  window.rcmActivateSidebar = rcmActivateSidebar;

  function startNewRcmChat() {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem("rcm_tab_session_id", sessionId);
    messagesEl.innerHTML = "";
    messagesEl.appendChild(welcomeEl);
    welcomeEl.style.display = "flex";
    if (window.CbSidebar) window.CbSidebar.refreshActiveItem(sessionId);
    inputEl.focus();
  }

  async function loadSessionMessages(id) {
    try {
      const msgs = await Core.api("GET", `/chatbot/rcm/session/${id}/messages`);
      if (!msgs || !msgs.length) {
        messagesEl.innerHTML = "";
        messagesEl.appendChild(welcomeEl);
        welcomeEl.style.display = "flex";
        return;
      }
      messagesEl.innerHTML = "";
      msgs.forEach((m) => appendMessage(m.role, m.content, m.created_at));
      scrollToBottom();
    } catch {
      // new/empty session — leave welcome showing
    }
  }

  async function sendRcmMessage(text) {
    text = (text || "").trim();
    if (!text || isLoading) return;

    welcomeEl.style.display = "none";
    inputEl.value = "";
    inputEl.style.height = "auto";

    appendMessage("user", text, Date.now() / 1000);
    showTyping();
    setLoading(true);
    hideError();

    let assistantEl = null;

    await Core.streamChat("/chatbot/rcm/chat/stream", {
      sessionId,
      message: text,
      onChunk: (textSoFar) => {
        if (!assistantEl) {
          hideTyping();
          assistantEl = appendMessage("assistant", "", null);
        }
        assistantEl.querySelector(".hr-msg-body").innerHTML =
          Core.renderMarkdown(textSoFar) + '<span class="hr-cursor"></span>';
        scrollToBottom();
      },
      onDone: (fullText, _sources, _fromCache, followUps) => {
        hideTyping();
        if (!assistantEl) return;
        const body = assistantEl.querySelector(".hr-msg-body");
        body.innerHTML = Core.renderMarkdown(fullText);
        // Source/reference chips deliberately not shown — the conversation
        // stays plain-answer only, no citation clutter.
        Core.renderFollowUps(assistantEl, followUps, (q) => sendRcmMessage(q));
        addTime(assistantEl, Date.now() / 1000);
        scrollToBottom();
      },
      onError: (msg) => {
        hideTyping();
        if (assistantEl) {
          const row = assistantEl.closest(".hr-msg-row");
          if (row) row.remove();
        }
        showError(msg);
      },
    });

    setLoading(false);
  }

  function appendMessage(role, content, createdAt) {
    const row = document.createElement("div");
    row.className = `hr-msg-row ${role}`;

    if (role === "assistant") {
      const avatar = document.createElement("div");
      avatar.className = "hr-avatar-mini";
      avatar.innerHTML = BOT_SVG;
      row.appendChild(avatar);
    }

    const el = document.createElement("div");
    el.className = `hr-msg ${role}`;
    const body = document.createElement("div");
    body.className = "hr-msg-body";
    body.innerHTML = role === "assistant" ? Core.renderMarkdown(content) : `<p>${Core.escapeHtml(content).replace(/\n/g, "<br>")}</p>`;
    el.appendChild(body);

    addTime(el, createdAt);
    row.appendChild(el);
    messagesEl.appendChild(row);
    scrollToBottom();
    return el;
  }

  function addTime(el, createdAt) {
    const t = Core.formatTime(createdAt);
    if (!t) return;
    const timeEl = document.createElement("div");
    timeEl.className = "hr-msg-time";
    timeEl.textContent = t;
    el.appendChild(timeEl);
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "hr-msg-row assistant";
    const avatar = document.createElement("div");
    avatar.className = "hr-avatar-mini";
    avatar.innerHTML = BOT_SVG;
    row.appendChild(avatar);
    const typingEl = document.createElement("div");
    typingEl.className = "hr-typing";
    typingEl.innerHTML = "<span></span><span></span><span></span>";
    row.appendChild(typingEl);
    typingRow = row;
    messagesEl.appendChild(row);
    scrollToBottom();
  }

  function hideTyping() {
    if (typingRow && typingRow.parentNode) typingRow.parentNode.removeChild(typingRow);
    typingRow = null;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setLoading(v) {
    isLoading = v;
    sendBtn.disabled = v;
    inputEl.disabled = v;
  }

  function showError(msg) {
    errToast.textContent = msg;
    errToast.classList.add("show");
    setTimeout(() => errToast.classList.remove("show"), 5000);
  }

  function hideError() {
    errToast.classList.remove("show");
  }
})();
