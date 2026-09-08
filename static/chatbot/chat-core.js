/**
 * JHS Chat Core — chat-core.js
 *
 * Shared, framework-free helpers used by BOTH the floating widget
 * (chatbot-widget.js) and the full JHS Chatbot module page (index.html's
 * HR Policy tab). Kept dependency-free (no globals besides `window.JHSChatCore`)
 * so either surface can pull in just what it needs.
 *
 * Exposes: JHSChatCore.getToken, .api, .renderMarkdown, .escapeHtml,
 * .formatTime, .streamChat
 */
(function () {
  "use strict";

  function getToken() {
    return localStorage.getItem("access_token") || localStorage.getItem("token") || "";
  }

  function decodeEmpid() {
    try {
      const token = getToken();
      if (!token) return "user";
      const payload = JSON.parse(atob(token.split(".")[1]));
      return payload.sub || "user";
    } catch {
      return "user";
    }
  }

  async function api(method, path, body) {
    const token = getToken();
    const opts = {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
    return res.json();
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // Inline formatting: **bold**, *italic*, `code` — applied within one line.
  function renderInline(text) {
    return text
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  // Small, safe markdown renderer: paragraphs, "- "/"* " bullet lists,
  // "1. " numbered lists, plus the inline formatting above. Input is
  // HTML-escaped first, so this never introduces unsanitized markup.
  function renderMarkdown(raw) {
    const lines = escapeHtml(raw).split("\n");
    let html = "";
    let listType = null; // "ul" | "ol" | null
    let paragraph = [];

    function closeList() {
      if (listType) {
        html += `</${listType}>`;
        listType = null;
      }
    }
    function flushParagraph() {
      if (paragraph.length) {
        html += `<p>${paragraph.join("<br>")}</p>`;
        paragraph = [];
      }
    }

    lines.forEach((line) => {
      const trimmed = line.trim();
      const bullet = trimmed.match(/^[-*]\s+(.*)/);
      const numbered = trimmed.match(/^\d+[.)]\s+(.*)/);

      if (bullet) {
        flushParagraph();
        if (listType !== "ul") { closeList(); html += "<ul>"; listType = "ul"; }
        html += `<li>${renderInline(bullet[1])}</li>`;
      } else if (numbered) {
        flushParagraph();
        if (listType !== "ol") { closeList(); html += "<ol>"; listType = "ol"; }
        html += `<li>${renderInline(numbered[1])}</li>`;
      } else if (trimmed === "") {
        closeList();
        flushParagraph();
      } else {
        closeList();
        paragraph.push(renderInline(line));
      }
    });
    closeList();
    flushParagraph();
    return html;
  }

  function formatTime(unixSeconds) {
    if (!unixSeconds) return "";
    try {
      return new Date(unixSeconds * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  }

  /**
   * Streams a chat reply over SSE from `url` (POST, {session_id, message}).
   * Calls back into the caller so the UI stays fully in control of DOM.
   *   onChunk(textSoFar)
   *   onDone(fullText, sources, fromCache, followUps)
   *   onError(message)
   * Returns nothing — callers await it (it resolves once the stream ends).
   */
  async function streamChat(url, { sessionId, message, onChunk, onDone, onError }) {
    let buffer = "";
    let doneSources = null;
    let doneFromCache = false;
    let doneFollowUps = [];
    let sawError = null;

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({ session_id: sessionId, message }),
      });
      if (!res.ok || !res.body) throw new Error(`API ${url} → ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });

        const parts = sseBuffer.split("\n\n");
        sseBuffer = parts.pop(); // keep the trailing partial event for next read

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          let evt;
          try {
            evt = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }

          if (evt.type === "chunk") {
            buffer += evt.text;
            if (onChunk) onChunk(buffer);
          } else if (evt.type === "done") {
            doneSources = evt.sources;
            doneFromCache = !!evt.from_cache;
            doneFollowUps = evt.follow_ups || [];
          } else if (evt.type === "error") {
            sawError = evt.message;
          }
        }
      }

      if (sawError) throw new Error(sawError);
      if (onDone) onDone(buffer, doneSources, doneFromCache, doneFollowUps);
    } catch (err) {
      const msg =
        err.message && err.message.includes("401")
          ? "Session expired — please log in again."
          : err.message && (err.message.includes("502") || err.message.includes("stream"))
          ? "AI service is temporarily unavailable. Try again in a moment."
          : "Something went wrong. Please try again.";
      if (onError) onError(msg, buffer);
    }
  }

  // ── Follow-up suggestion chips — capped at 4 SHOWN per login ────────────
  // The counter lives in localStorage (persists across page loads within
  // one login) and is reset to 0 by static/login.html right after a fresh
  // login — so "4 per login" means 4 total across HR/RCM/Library/the
  // floating widget combined, not 4 per bot or per page.
  const FOLLOWUP_CAP = 4;
  const FOLLOWUP_COUNT_KEY = "chatbot_followup_shown_count";

  function followupBudgetRemaining() {
    const n = parseInt(localStorage.getItem(FOLLOWUP_COUNT_KEY) || "0", 10);
    return Math.max(0, FOLLOWUP_CAP - (isNaN(n) ? 0 : n));
  }

  function _recordFollowupShown() {
    const n = parseInt(localStorage.getItem(FOLLOWUP_COUNT_KEY) || "0", 10);
    localStorage.setItem(FOLLOWUP_COUNT_KEY, String((isNaN(n) ? 0 : n) + 1));
  }

  /**
   * Renders up to 4 follow-up suggestion chips into `container` (appended
   * as the last child) — but only while the per-login budget allows it;
   * silently does nothing once the cap is used up, or if there's nothing
   * to show. onPick(questionText) fires when a chip is clicked.
   * Returns true if chips were actually rendered.
   */
  function renderFollowUps(container, followUps, onPick) {
    if (!followUps || !followUps.length || !container) return false;
    if (followupBudgetRemaining() <= 0) return false;
    _recordFollowupShown();

    const wrap = document.createElement("div");
    wrap.className = "cb-followups";
    followUps.slice(0, 4).forEach((q) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "cb-followup-chip";
      chip.textContent = q;
      chip.addEventListener("click", () => onPick && onPick(q));
      wrap.appendChild(chip);
    });
    container.appendChild(wrap);
    return true;
  }

  window.JHSChatCore = {
    getToken,
    decodeEmpid,
    api,
    escapeHtml,
    renderInline,
    renderMarkdown,
    formatTime,
    streamChat,
    followupBudgetRemaining,
    renderFollowUps,
  };
})();
