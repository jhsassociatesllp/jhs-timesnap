/**
 * HR Policy tab controller — static/chatbot/index.html's dedicated HR
 * Policy chat panel. Unlike the floating widget's general assistant, this
 * always talks to /chatbot/chat/stream (pure HR RAG, no classify/dispatch)
 * so switching to this tab is a deliberate "I want the HR bot" choice.
 * Built on the shared streaming/markdown helpers in chat-core.js.
 */
(function () {
  "use strict";

  const Core = window.JHSChatCore;
  const BOT_SVG = '<svg viewBox="0 0 120 60" xmlns="http://www.w3.org/2000/svg"><text x="60" y="43" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-weight="800" font-size="40" letter-spacing="-1" fill="#ffffff">JHS</text></svg>';

  let sessionId = sessionStorage.getItem("hr_tab_session_id") || crypto.randomUUID();
  sessionStorage.setItem("hr_tab_session_id", sessionId);

  let isLoading = false;
  let typingRow = null;
  let initialized = false;

  let messagesEl, welcomeEl, inputEl, sendBtn, errToast;

  function initHrTab() {
    if (initialized) return;
    initialized = true;

    messagesEl = document.getElementById("hr-messages");
    welcomeEl = document.getElementById("hr-welcome");
    inputEl = document.getElementById("hr-input");
    sendBtn = document.getElementById("hr-send-btn");
    errToast = document.getElementById("hr-error-toast");

    document.querySelectorAll(".hr-sugg-btn").forEach((btn) => {
      btn.addEventListener("click", () => sendHrMessage(btn.dataset.q));
    });

    inputEl.addEventListener("input", () => {
      inputEl.style.height = "auto";
      inputEl.style.height = Math.min(inputEl.scrollHeight, 130) + "px";
    });
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendHrMessage(inputEl.value);
      }
    });
    sendBtn.addEventListener("click", () => sendHrMessage(inputEl.value));

    // Personalized "Hi {name}" — module.js resolves /chatbot/me once for the
    // whole page; pick it up whenever it's ready, whichever order wins.
    if (window.jhsUserName) applyGreeting(window.jhsUserName);
    window.onJhsGreetingReady = applyGreeting;

    loadSessionMessages(sessionId);
  }
  window.initHrTab = initHrTab;

  function applyGreeting(name) {
    const titleEl = document.getElementById("hr-welcome-title");
    if (titleEl) titleEl.textContent = `Hi ${name} 👋`;
  }

  // Populates the SHARED sidebar (module.js) with this bot's sessions and
  // wires its "New chat" button — called by module.js whenever the HR
  // Policy tab becomes the active outer tab.
  function hrActivateSidebar() {
    if (!window.CbSidebar) return;
    window.CbSidebar.attach({
      activeSessionId: sessionId,
      onNewChat: startNewHrChat,
      fetchSessions: () => Core.api("GET", "/chatbot/sessions"),
      onSelect: (id) => {
        sessionId = id;
        sessionStorage.setItem("hr_tab_session_id", id);
        loadSessionMessages(id);
      },
    });
  }
  window.hrActivateSidebar = hrActivateSidebar;

  function startNewHrChat() {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem("hr_tab_session_id", sessionId);
    messagesEl.innerHTML = "";
    messagesEl.appendChild(welcomeEl);
    welcomeEl.style.display = "flex";
    if (window.CbSidebar) window.CbSidebar.refreshActiveItem(sessionId);
    inputEl.focus();
  }

  async function loadSessionMessages(id) {
    try {
      const msgs = await Core.api("GET", `/chatbot/session/${id}/messages`);
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

  async function sendHrMessage(text) {
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

    await Core.streamChat("/chatbot/chat/stream", {
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
        Core.renderFollowUps(assistantEl, followUps, (q) => sendHrMessage(q));
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
