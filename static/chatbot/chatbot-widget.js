/**
 * JHS Assistant floating widget — chatbot-widget.js
 *
 * Drop this script (after chat-core.js) into any HTML page before </body>.
 * Renders a floating branded bubble in the bottom-right corner. Clicking
 * opens a slide-in chat panel. Closing the panel returns the user to
 * wherever they were — no navigation.
 *
 * This is a GENERAL assistant, not dedicated to one bot: it hits
 * /chatbot/assistant/chat/stream, which classifies each message and routes
 * it to HR Policy, JHS Library, an RCM placeholder, or a plain reply (see
 * backend/chatbot/assistant.py). Once a conversation goes deep enough (5+
 * questions in one session) it nudges the user, once, toward the full
 * /jhs-chatbot module for complete history and deeper tools.
 *
 * The panel's header is a drag handle — grab it to move the panel anywhere
 * on screen; it stays put until "New chat" or a page reload.
 *
 * Auth: reads the JWT token from localStorage (see chat-core.js getToken()).
 */
(function () {
  "use strict";

  const Core = window.JHSChatCore;
  if (!Core) {
    console.error("[JHS Assistant] chat-core.js must be loaded before chatbot-widget.js");
    return;
  }
  const { getToken, api, renderMarkdown, formatTime, streamChat } = Core;

  // ── generate / persist a session id per browser tab ───────────────────────
  let currentSessionId =
    sessionStorage.getItem("chatbot_session_id") ||
    crypto.randomUUID();
  sessionStorage.setItem("chatbot_session_id", currentSessionId);

  // ── branded bubble artwork ─────────────────────────────────────────────────
  // Robot badge (static/chatbot/bot_icon.png — pre-cropped to a clean circle
  // with transparent corners, see scratch_process_icon.py) with a soft pulse
  // ring — swap the <img> markup below for a different asset any time
  // without touching JS. Fills its container completely (see the img rules
  // below), since the artwork is already its own circular badge.
  const JHS_BADGE_IMG = `<img src="/static/chatbot/bot_icon.png" alt="JHS Assistant" />`;

  // ── build DOM ──────────────────────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
    /* Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap');

    #jhs-chat-root * { box-sizing: border-box; font-family: 'Inter', sans-serif; }

    /* ── Bubble ───────────────────────────────────────────────────────── */
    #jhs-chat-bubble {
      position: fixed;
      bottom: 28px;
      right: 28px;
      z-index: 99999;
      width: 62px;
      height: 62px;
      border-radius: 50%;
      background: linear-gradient(135deg, #4a6fa5 0%, #2f4d75 100%);
      /* Layered shadow: a tight dark shadow for lift + a soft light-blue
         ambient glow (matching the badge artwork's own palette) so the
         bubble reads as gently lit rather than just flat with a drop
         shadow. */
      box-shadow: 0 4px 20px rgba(74,111,165,0.45), 0 0 22px 2px rgba(157,197,240,0.55);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 2.5px solid rgba(255,255,255,0.9);
      outline: none;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    #jhs-chat-bubble:hover {
      transform: scale(1.08);
      box-shadow: 0 6px 28px rgba(74,111,165,0.55), 0 0 30px 4px rgba(157,197,240,0.75);
    }
    #jhs-chat-bubble img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }

    /* Pulsing brand ring — subtle "I'm alive" cue on the bubble */
    #jhs-chat-bubble::before {
      content: '';
      position: absolute;
      inset: -6px;
      border-radius: 50%;
      border: 2px solid rgba(133,178,224,0.65);
      animation: jhs-pulse-ring 2.6s ease-out infinite;
    }
    @keyframes jhs-pulse-ring {
      0%   { transform: scale(0.92); opacity: 0.9; }
      70%  { transform: scale(1.28); opacity: 0; }
      100% { transform: scale(1.28); opacity: 0; }
    }

    /* Notification dot */
    #jhs-chat-bubble .notif-dot {
      position: absolute;
      top: 4px; right: 4px;
      width: 10px; height: 10px;
      border-radius: 50%;
      background: #f04c4c;
      border: 2px solid #fff;
      display: none;
    }
    #jhs-chat-bubble.has-notif .notif-dot { display: block; }

    /* Tooltip */
    #jhs-chat-bubble::after {
      content: 'JHS Assistant — ask me anything';
      position: absolute;
      right: 72px;
      bottom: 50%;
      transform: translateY(50%);
      background: #1c2230;
      color: #fff;
      font-size: 12px;
      font-weight: 500;
      padding: 6px 10px;
      border-radius: 6px;
      white-space: nowrap;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
    }
    #jhs-chat-bubble:hover::after { opacity: 1; }

    /* ── Panel ────────────────────────────────────────────────────────── */
    #jhs-chat-panel {
      position: fixed;
      bottom: 104px;
      right: 28px;
      z-index: 99998;
      width: 400px;
      max-width: calc(100vw - 40px);
      height: 580px;
      max-height: calc(100vh - 124px);
      background: #f6f4ef;
      border-radius: 18px;
      box-shadow: 0 16px 60px rgba(0,0,0,0.22);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      opacity: 0;
      transform: translateY(20px) scale(0.97);
      pointer-events: none;
      transition: opacity 0.28s cubic-bezier(.4,0,.2,1),
                  transform 0.28s cubic-bezier(.4,0,.2,1);
    }
    #jhs-chat-panel.open {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: all;
    }

    /* ── Panel header ─────────────────────────────────────────────────── */
    #jhs-chat-header {
      background: linear-gradient(135deg, #4a6fa5 0%, #2f4d75 100%);
      padding: 14px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    #jhs-chat-header .avatar {
      width: 36px; height: 36px;
      border-radius: 50%;
      background: rgba(255,255,255,0.2);
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
      overflow: hidden;
    }
    #jhs-chat-header .avatar img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
    #jhs-chat-header .info { flex: 1; min-width: 0; }
    #jhs-chat-header .info h4 {
      margin: 0; color: #fff; font-size: 14px; font-weight: 600;
    }
    #jhs-chat-header .info p {
      margin: 0; color: rgba(255,255,255,0.75); font-size: 11px;
    }
    #jhs-chat-header-actions { display: flex; gap: 6px; }
    .jhs-icon-btn {
      background: rgba(255,255,255,0.15);
      border: none; cursor: pointer;
      border-radius: 8px;
      width: 32px; height: 32px;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.15s;
    }
    .jhs-icon-btn:hover { background: rgba(255,255,255,0.28); }
    .jhs-icon-btn svg { width: 16px; height: 16px; fill: #fff; }

    /* ── Sessions sidebar (hidden by default) ─────────────────────────── */
    #jhs-sessions-bar {
      background: #171b26;
      color: #cfd3dd;
      flex-shrink: 0;
      max-height: 0;
      overflow: hidden;
      transition: max-height 0.3s ease;
    }
    #jhs-sessions-bar.open { max-height: 220px; overflow-y: auto; }
    #jhs-sessions-bar .sessions-header {
      padding: 10px 14px 6px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: #8990a3;
      display: flex; justify-content: space-between; align-items: center;
    }
    #jhs-new-chat-btn {
      background: transparent;
      border: 1px solid #2a3040;
      color: #cfd3dd;
      border-radius: 6px;
      padding: 3px 8px;
      font-size: 11px;
      cursor: pointer;
      transition: background 0.15s;
    }
    #jhs-new-chat-btn:hover { background: #2a3040; }
    .jhs-session-item {
      padding: 8px 14px;
      font-size: 12px;
      cursor: pointer;
      border-radius: 6px;
      margin: 2px 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      transition: background 0.15s;
      color: #cfd3dd;
    }
    .jhs-session-item:hover { background: #232a3b; }
    .jhs-session-item.active { background: #2a3346; color: #fff; }

    /* ── Messages area ────────────────────────────────────────────────── */
    #jhs-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px 14px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-behavior: smooth;
    }
    #jhs-messages::-webkit-scrollbar { width: 4px; }
    #jhs-messages::-webkit-scrollbar-thumb { background: #c8c3b8; border-radius: 4px; }

    /* Welcome state */
    #jhs-welcome {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-align: center;
      padding: 20px;
      color: #4d5566;
    }
    #jhs-welcome .w-icon {
      width: 52px; height: 52px;
      background: linear-gradient(135deg, #4a6fa5 0%, #2f4d75 100%);
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      margin-bottom: 4px;
      overflow: hidden;
    }
    #jhs-welcome .w-icon img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
    #jhs-welcome h3 { margin: 0; font-size: 15px; color: #1c2230; }
    #jhs-welcome p { margin: 0; font-size: 12.5px; line-height: 1.5; }

    /* Suggested questions */
    .jhs-suggestions { display: flex; flex-direction: column; gap: 6px; width: 100%; margin-top: 8px; }
    .jhs-sugg-btn {
      background: #fff;
      border: 1px solid #dedad0;
      border-radius: 10px;
      padding: 8px 12px;
      font-size: 12px;
      color: #1c2230;
      cursor: pointer;
      text-align: left;
      transition: border-color 0.15s, background 0.15s;
    }
    .jhs-sugg-btn:hover { background: #eef0f4; border-color: #4a6fa5; }

    /* Message rows (avatar + bubble) */
    .jhs-msg-row { display: flex; gap: 7px; align-items: flex-end; }
    .jhs-msg-row.user { justify-content: flex-end; }
    .jhs-msg-row.assistant { justify-content: flex-start; }
    .jhs-avatar-mini {
      width: 22px; height: 22px;
      border-radius: 50%;
      background: linear-gradient(135deg, #4a6fa5 0%, #2f4d75 100%);
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
      margin-bottom: 3px;
      box-shadow: 0 2px 6px rgba(74,111,165,0.3);
      overflow: hidden;
    }
    .jhs-avatar-mini img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }

    /* Message bubbles */
    .jhs-msg {
      max-width: 86%;
      padding: 10px 13px;
      border-radius: 14px;
      font-size: 13.5px;
      line-height: 1.5;
      word-break: break-word;
    }
    .jhs-msg.user {
      background: #232a3b;
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .jhs-msg.assistant {
      background: #fff;
      color: #1c2230;
      border: 1px solid #dedad0;
      border-bottom-left-radius: 4px;
      box-shadow: 0 2px 10px rgba(28,34,48,0.06);
    }
    .jhs-msg { animation: jhs-msg-in 0.22s ease; }
    @keyframes jhs-msg-in {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    /* Markdown rendered inside assistant bubbles */
    .jhs-msg p { margin: 0 0 8px; }
    .jhs-msg p:last-child { margin-bottom: 0; }
    .jhs-msg ul, .jhs-msg ol { margin: 4px 0 8px; padding-left: 18px; }
    .jhs-msg ul:last-child, .jhs-msg ol:last-child { margin-bottom: 0; }
    .jhs-msg li { margin-bottom: 4px; }
    .jhs-msg li:last-child { margin-bottom: 0; }
    .jhs-msg strong { color: #2f4d75; font-weight: 600; }
    .jhs-msg.user strong { color: #fff; }
    .jhs-msg code {
      background: #f1efe9;
      color: #a8763e;
      padding: 1px 5px;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
    }
    .jhs-msg-time {
      margin-top: 5px;
      font-size: 10.5px;
      opacity: 0.6;
    }
    .jhs-msg.assistant .jhs-msg-time { color: #8990a3; }
    .jhs-msg.user .jhs-msg-time { color: #d7dae2; text-align: right; }

    /* Source chips under an assistant answer */
    .jhs-sources { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
    .jhs-source-chip {
      font-size: 10.5px;
      font-weight: 500;
      background: #fdeef0;
      color: #2f4d75;
      border: 1px solid #f6cdd4;
      border-radius: 999px;
      padding: 3px 9px;
      white-space: nowrap;
    }

    /* Blinking cursor while an answer is still streaming in */
    .jhs-cursor {
      display: inline-block;
      width: 2px;
      height: 13px;
      background: #4a6fa5;
      margin-left: 2px;
      vertical-align: middle;
      animation: jhs-blink 0.9s steps(1) infinite;
    }
    @keyframes jhs-blink { 50% { opacity: 0; } }

    /* Typing indicator */
    .jhs-typing {
      background: #fff;
      border: 1px solid #dedad0;
      border-radius: 14px;
      border-bottom-left-radius: 4px;
      padding: 10px 16px;
      display: flex; gap: 4px; align-items: center;
    }
    .jhs-typing span {
      width: 6px; height: 6px;
      border-radius: 50%;
      background: #4a6fa5;
      animation: jhs-bounce 1s infinite;
    }
    .jhs-typing span:nth-child(2) { animation-delay: 0.15s; }
    .jhs-typing span:nth-child(3) { animation-delay: 0.3s; }
    @keyframes jhs-bounce {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-5px); }
    }

    /* ── Module nudge card — shown once, inline in the feed, after a few
       questions in one session (not a permanently-visible footer) ───── */
    .jhs-nudge-card {
      align-self: center;
      max-width: 92%;
      background: #eaf0f8;
      border: 1px solid #cddaeb;
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 12px;
      color: #2f4d75;
      text-align: center;
      line-height: 1.5;
      animation: jhs-msg-in 0.25s ease;
    }
    .jhs-nudge-card a {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-top: 5px;
      color: #2f4d75;
      font-weight: 600;
      text-decoration: none;
    }
    .jhs-nudge-card a:hover { text-decoration: underline; }
    .jhs-nudge-card svg { width: 11px; height: 11px; fill: #2f4d75; }

    /* ── Draggable panel ──────────────────────────────────────────────── */
    #jhs-chat-header { cursor: move; touch-action: none; user-select: none; }
    #jhs-chat-header-actions, #jhs-chat-header-actions * { cursor: pointer; }
    #jhs-chat-panel.dragging { transition: none !important; }

    /* ── Minimized panel — collapses to just the header/title bar ──────── */
    #jhs-chat-panel.minimized {
      height: auto;
      max-height: none;
    }
    #jhs-chat-panel.minimized #jhs-sessions-bar,
    #jhs-chat-panel.minimized #jhs-messages,
    #jhs-chat-panel.minimized #jhs-error-toast,
    #jhs-chat-panel.minimized #jhs-input-bar {
      display: none;
    }

    /* ── Input bar ────────────────────────────────────────────────────── */
    #jhs-input-bar {
      background: #fff;
      border-top: 1px solid #dedad0;
      padding: 10px 12px;
      display: flex;
      gap: 8px;
      align-items: flex-end;
      flex-shrink: 0;
    }
    #jhs-input {
      flex: 1;
      border: 1px solid #dedad0;
      border-radius: 10px;
      padding: 9px 12px;
      font-size: 13.5px;
      resize: none;
      outline: none;
      max-height: 100px;
      overflow-y: auto;
      line-height: 1.45;
      transition: border-color 0.15s;
      color: #1c2230;
      background: #fafaf8;
    }
    #jhs-input:focus { border-color: #4a6fa5; background: #fff; }
    #jhs-send-btn {
      width: 38px; height: 38px;
      border-radius: 10px;
      background: linear-gradient(135deg, #4a6fa5 0%, #2f4d75 100%);
      border: none;
      cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
      transition: opacity 0.15s;
    }
    #jhs-send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    #jhs-send-btn svg { width: 16px; height: 16px; fill: #fff; }

    /* ── Error toast ──────────────────────────────────────────────────── */
    #jhs-error-toast {
      position: absolute;
      bottom: 70px; left: 12px; right: 12px;
      background: #f04c4c;
      color: #fff;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 12px;
      display: none;
      z-index: 10;
    }
    #jhs-error-toast.show { display: block; }
  `;
  document.head.appendChild(style);

  // ── Root wrapper ──────────────────────────────────────────────────────────
  const root = document.createElement("div");
  root.id = "jhs-chat-root";
  root.innerHTML = `
    <!-- Floating bubble -->
    <button id="jhs-chat-bubble" title="JHS Assistant" aria-label="Open JHS Assistant">
      <span class="notif-dot"></span>
      ${JHS_BADGE_IMG}
    </button>

    <!-- Chat panel -->
    <div id="jhs-chat-panel" role="dialog" aria-label="JHS Assistant">
      <!-- Header -->
      <div id="jhs-chat-header">
        <div class="avatar">${JHS_BADGE_IMG}</div>
        <div class="info">
          <h4>JHS Assistant</h4>
          <p>HR &middot; RCM &middot; Library</p>
        </div>
        <div id="jhs-chat-header-actions">
          <button class="jhs-icon-btn" id="jhs-history-btn" title="Chat history" aria-label="Toggle history">
            <svg viewBox="0 0 24 24"><path d="M13 3C8 3 4 7 4 12H1l3.9 3.9.1.2L9 12H6c0-3.9 3.1-7 7-7s7 3.1 7 7-3.1 7-7 7c-1.9 0-3.7-.8-5-2l-1.4 1.4C8.3 20.5 10.6 21.5 13 21.5c5 0 9-4 9-9s-4-9.5-9-9.5zm-1 5v5l4.3 2.5.7-1.2-3.5-2.1V8h-1.5z"/></svg>
          </button>
          <button class="jhs-icon-btn" id="jhs-newchat-btn" title="New chat" aria-label="New chat">
            <svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
          </button>
          <button class="jhs-icon-btn" id="jhs-minimize-btn" title="Minimize" aria-label="Minimize chatbot">
            <svg viewBox="0 0 24 24"><path d="M6 19h12v2H6z"/></svg>
          </button>
          <button class="jhs-icon-btn" id="jhs-close-btn" title="Close" aria-label="Close chatbot">
            <svg viewBox="0 0 24 24"><path d="M19 6.4L17.6 5 12 10.6 6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6z"/></svg>
          </button>
        </div>
      </div>

      <!-- Sessions sidebar (hidden by default) -->
      <div id="jhs-sessions-bar">
        <div class="sessions-header">
          <span>Recent Chats</span>
          <button id="jhs-new-chat-btn">+ New</button>
        </div>
        <div id="jhs-sessions-list"></div>
      </div>

      <!-- Messages -->
      <div id="jhs-messages">
        <div id="jhs-welcome">
          <div class="w-icon">${JHS_BADGE_IMG}</div>
          <h3 id="jhs-welcome-title">Hi there 👋</h3>
          <p>I'm your JHS Assistant — ask me about HR policy or the audit observation library. For RCM, full history, or deeper digging, open the JHS Chatbot module.</p>
          <div class="jhs-suggestions">
            <button class="jhs-sugg-btn" data-q="What is the work from home policy?">🏠 What is the work from home policy?</button>
            <button class="jhs-sugg-btn" data-q="How many casual leaves do I get?">💼 How many casual leaves do I get?</button>
            <button class="jhs-sugg-btn" data-q="How many high risk observations are there in Banking?">🔎 High-risk observations in Banking?</button>
          </div>
        </div>
      </div>

      <!-- Error toast -->
      <div id="jhs-error-toast"></div>

      <!-- Input -->
      <div id="jhs-input-bar">
        <textarea id="jhs-input" placeholder="Ask about HR, RCM, or the audit library…" rows="1" aria-label="Chat input"></textarea>
        <button id="jhs-send-btn" aria-label="Send message">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  // ── Element references ────────────────────────────────────────────────────
  const bubble     = root.querySelector("#jhs-chat-bubble");
  const panel      = root.querySelector("#jhs-chat-panel");
  const closeBtn   = root.querySelector("#jhs-close-btn");
  const minimizeBtn = root.querySelector("#jhs-minimize-btn");
  const historyBtn = root.querySelector("#jhs-history-btn");
  const newChatBtn = root.querySelector("#jhs-newchat-btn");
  const newChatBtn2 = root.querySelector("#jhs-new-chat-btn");
  const sessBar    = root.querySelector("#jhs-sessions-bar");
  const sessList   = root.querySelector("#jhs-sessions-list");
  const messages   = root.querySelector("#jhs-messages");
  const welcome    = root.querySelector("#jhs-welcome");
  const input      = root.querySelector("#jhs-input");
  const sendBtn    = root.querySelector("#jhs-send-btn");
  const errToast   = root.querySelector("#jhs-error-toast");

  // ── State ─────────────────────────────────────────────────────────────────
  let panelOpen    = false;
  let histOpen     = false;
  let isLoading    = false;
  let typingRow    = null;
  let userMsgCount = 0;   // resets on "new chat" — drives the module nudge below
  let nudgeShown   = false;

  const BOT_AVATAR_IMG = JHS_BADGE_IMG;
  const header = root.querySelector("#jhs-chat-header");

  // ── Draggable panel — grab the header to move the whole panel anywhere on
  // screen. A small movement threshold keeps the header's own buttons
  // (close/history/new chat) clickable instead of being swallowed by drag. ──
  (function makeDraggable() {
    let dragging = false, moved = false, startX = 0, startY = 0, startLeft = 0, startTop = 0;

    header.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".jhs-icon-btn")) return;
      dragging = true;
      moved = false;
      const rect = panel.getBoundingClientRect();
      startLeft = rect.left;
      startTop = rect.top;
      startX = e.clientX;
      startY = e.clientY;
      try { header.setPointerCapture(e.pointerId); } catch {}
    });

    header.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!moved && Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
      moved = true;
      panel.classList.add("dragging");
      const maxLeft = window.innerWidth - panel.offsetWidth - 8;
      const maxTop = window.innerHeight - panel.offsetHeight - 8;
      const newLeft = Math.min(Math.max(8, startLeft + dx), Math.max(8, maxLeft));
      const newTop = Math.min(Math.max(8, startTop + dy), Math.max(8, maxTop));
      panel.style.left = `${newLeft}px`;
      panel.style.top = `${newTop}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    });

    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      panel.classList.remove("dragging");
      try { header.releasePointerCapture(e.pointerId); } catch {}
    }
    header.addEventListener("pointerup", endDrag);
    header.addEventListener("pointercancel", endDrag);
  })();

  // ── Personalized greeting ────────────────────────────────────────────────
  (async function loadGreeting() {
    try {
      const data = await api("GET", "/chatbot/me");
      if (data && data.name) {
        const titleEl = root.querySelector("#jhs-welcome-title");
        if (titleEl) titleEl.textContent = `Hi ${data.name} 👋`;
      }
    } catch {
      // not logged in yet, or endpoint unavailable — generic greeting stays
    }
  })();

  // ── Panel open / close ────────────────────────────────────────────────────
  function openPanel() {
    panelOpen = true;
    panel.classList.add("open");
    bubble.style.display = "none";
    loadSessionMessages(currentSessionId);
    input.focus();
  }

  function closePanel() {
    panelOpen = false;
    panel.classList.remove("open");
    panel.classList.remove("minimized");
    minimizeBtn.innerHTML = MINIMIZE_ICON;
    minimizeBtn.title = "Minimize";
    minimized = false;
    bubble.style.display = "flex";
    sessBar.classList.remove("open");
    histOpen = false;
  }

  bubble.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);

  // ── Minimize — collapses the panel to just its title bar (still on
  // screen, still draggable) instead of hiding it back to the bubble. ──────
  const MINIMIZE_ICON = '<svg viewBox="0 0 24 24"><path d="M6 19h12v2H6z"/></svg>';
  const RESTORE_ICON = '<svg viewBox="0 0 24 24"><path d="M6 6h5v2H8.4l4.3 4.3-1.4 1.4L7 9.4V13H5V6h1zm13 12h-5v-2h2.6l-4.3-4.3 1.4-1.4 4.3 4.3V11h2v7h-1z"/></svg>';
  let minimized = false;
  minimizeBtn.addEventListener("click", () => {
    minimized = !minimized;
    panel.classList.toggle("minimized", minimized);
    minimizeBtn.innerHTML = minimized ? RESTORE_ICON : MINIMIZE_ICON;
    minimizeBtn.title = minimized ? "Restore" : "Minimize";
    minimizeBtn.setAttribute("aria-label", minimized ? "Restore chatbot" : "Minimize chatbot");
    if (!minimized) input.focus();
  });

  // ── New chat ──────────────────────────────────────────────────────────────
  function startNewChat() {
    currentSessionId = crypto.randomUUID();
    sessionStorage.setItem("chatbot_session_id", currentSessionId);
    messages.innerHTML = "";
    messages.appendChild(welcome);
    welcome.style.display = "flex";
    sessBar.classList.remove("open");
    histOpen = false;
    userMsgCount = 0;
    nudgeShown = false;
    input.focus();
  }

  newChatBtn.addEventListener("click", startNewChat);
  newChatBtn2.addEventListener("click", startNewChat);

  // ── History sidebar ───────────────────────────────────────────────────────
  historyBtn.addEventListener("click", async () => {
    histOpen = !histOpen;
    sessBar.classList.toggle("open", histOpen);
    if (histOpen) await refreshSessions();
  });

  async function refreshSessions() {
    try {
      const sessions = await api("GET", "/chatbot/sessions");
      sessList.innerHTML = "";
      sessions.forEach((s) => {
        const item = document.createElement("div");
        item.className = "jhs-session-item" + (s.id === currentSessionId ? " active" : "");
        item.textContent = s.title;
        item.title = s.title;
        item.addEventListener("click", () => {
          currentSessionId = s.id;
          sessionStorage.setItem("chatbot_session_id", s.id);
          loadSessionMessages(s.id);
          sessBar.classList.remove("open");
          histOpen = false;
        });
        sessList.appendChild(item);
      });
      if (!sessions.length) {
        sessList.innerHTML = '<div style="padding:8px 14px;font-size:12px;color:#8990a3">No chats yet</div>';
      }
    } catch {
      // silently fail — history sidebar is non-critical
    }
  }

  async function loadSessionMessages(sessionId) {
    try {
      const msgs = await api("GET", `/chatbot/session/${sessionId}/messages`);
      if (!msgs || msgs.length === 0) {
        messages.innerHTML = "";
        messages.appendChild(welcome);
        welcome.style.display = "flex";
        return;
      }
      messages.innerHTML = "";
      msgs.forEach((m) => appendMessage(m.role, m.content, false, m.created_at));
      scrollToBottom();
    } catch {
      // new session or error — just show welcome
    }
  }

  // ── Suggested questions ───────────────────────────────────────────────────
  root.querySelectorAll(".jhs-sugg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.dataset.q;
      sendMessage(q);
    });
  });

  // ── Auto-resize textarea ──────────────────────────────────────────────────
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 100) + "px";
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input.value);
    }
  });

  sendBtn.addEventListener("click", () => sendMessage(input.value));

  // ── Send a message (streamed via the general assistant router) ───────────
  async function sendMessage(text) {
    text = text.trim();
    if (!text || isLoading) return;

    welcome.style.display = "none";
    input.value = "";
    input.style.height = "auto";

    appendMessage("user", text, true, Date.now() / 1000);
    userMsgCount++;
    showTyping();
    setLoading(true);
    hideError();

    let assistantEl = null;

    await streamChat("/chatbot/assistant/chat/stream", {
      sessionId: currentSessionId,
      message: text,
      onChunk: (textSoFar) => {
        if (!assistantEl) {
          hideTyping();
          assistantEl = appendMessage("assistant", "", false, null);
        }
        renderStreamingBody(assistantEl, textSoFar);
        scrollToBottom();
      },
      onDone: (fullText, sources, fromCache) => {
        hideTyping();
        if (assistantEl) {
          finalizeAssistantMessage(assistantEl, fullText, sources, Date.now() / 1000);
        }
        maybeShowModuleNudge();
      },
      onError: (msg) => {
        hideTyping();
        if (assistantEl) {
          const row = assistantEl.closest(".jhs-msg-row");
          if (row) row.remove();
        }
        showError(msg);
      },
    });

    setLoading(false);
  }

  // Shown once per session, after the user's 5th question — not a
  // permanently-visible footer, just a gentle nudge when the conversation
  // is clearly going deep enough to benefit from the full module.
  function maybeShowModuleNudge() {
    if (nudgeShown || userMsgCount < 5) return;
    nudgeShown = true;
    const card = document.createElement("div");
    card.className = "jhs-nudge-card";
    card.innerHTML = `
      Got a lot to ask? The full JHS Chatbot module has your complete history and deeper tools for HR, RCM &amp; the Library.
      <br/>
      <a href="/jhs-chatbot">
        <svg viewBox="0 0 24 24"><path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7zM5 5v14h14v-7h-2v5H7V7h5V5H5z"/></svg>
        Open the full module
      </a>`;
    messages.appendChild(card);
    scrollToBottom();
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function formatTimeSafe(ts) {
    return formatTime(ts);
  }

  // Builds a message row (avatar + bubble) and returns the bubble element so
  // callers (e.g. the stream reader) can keep updating its contents.
  function appendMessage(role, content, doScroll = true, createdAt) {
    const row = document.createElement("div");
    row.className = `jhs-msg-row ${role}`;

    if (role === "assistant") {
      const avatar = document.createElement("div");
      avatar.className = "jhs-avatar-mini";
      avatar.innerHTML = BOT_AVATAR_IMG;
      row.appendChild(avatar);
    }

    const el = document.createElement("div");
    el.className = `jhs-msg ${role}`;

    const body = document.createElement("div");
    body.className = "jhs-msg-body";
    body.innerHTML =
      role === "assistant"
        ? renderMarkdown(content)
        : `<p>${Core.escapeHtml(content).replace(/\n/g, "<br>")}</p>`;
    el.appendChild(body);

    const time = formatTimeSafe(createdAt);
    if (time) {
      const timeEl = document.createElement("div");
      timeEl.className = "jhs-msg-time";
      timeEl.textContent = time;
      el.appendChild(timeEl);
    }

    row.appendChild(el);
    messages.appendChild(row);
    if (doScroll) scrollToBottom();
    return el;
  }

  function renderStreamingBody(el, textSoFar) {
    const body = el.querySelector(".jhs-msg-body");
    body.innerHTML = renderMarkdown(textSoFar) + '<span class="jhs-cursor"></span>';
  }

  function finalizeAssistantMessage(el, fullText, sources, createdAt) {
    const body = el.querySelector(".jhs-msg-body");
    body.innerHTML = renderMarkdown(fullText);

    const meaningful = (sources || []).filter(
      (s) => s && !s.startsWith("cache:") && s !== "No matching policy section"
    );
    if (meaningful.length) {
      const chips = document.createElement("div");
      chips.className = "jhs-sources";
      meaningful.forEach((s) => {
        const chip = document.createElement("span");
        chip.className = "jhs-source-chip";
        chip.textContent = s;
        chips.appendChild(chip);
      });
      el.appendChild(chips);
    }

    const time = formatTimeSafe(createdAt);
    if (time) {
      const timeEl = document.createElement("div");
      timeEl.className = "jhs-msg-time";
      timeEl.textContent = time;
      el.appendChild(timeEl);
    }
    scrollToBottom();
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "jhs-msg-row assistant";
    const avatar = document.createElement("div");
    avatar.className = "jhs-avatar-mini";
    avatar.innerHTML = BOT_AVATAR_IMG;
    row.appendChild(avatar);

    const typingEl = document.createElement("div");
    typingEl.className = "jhs-typing";
    typingEl.innerHTML = "<span></span><span></span><span></span>";
    row.appendChild(typingEl);

    typingRow = row;
    messages.appendChild(row);
    scrollToBottom();
  }

  function hideTyping() {
    if (typingRow && typingRow.parentNode) typingRow.parentNode.removeChild(typingRow);
    typingRow = null;
  }

  function scrollToBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function setLoading(v) {
    isLoading = v;
    sendBtn.disabled = v;
    input.disabled = v;
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
