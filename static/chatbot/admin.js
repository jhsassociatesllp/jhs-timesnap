/**
 * JHS Chatbot admin hub controller — static/chatbot/admin.html. Tab switcher
 * (HR Policy / RCM / JHS Library — only RCM has real content for now) plus
 * the RCM knowledge-base upload/collection management, talking to
 * /chatbot/rcm/admin/* (JWT-authed, gated server-side to "chatbot" module
 * admins — see backend/rcm_chatbot/router.py's _require_rcm_admin).
 */
(function () {
  "use strict";

  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || "";
  if (!token) {
    window.location.href = "/login";
    return;
  }

  async function api(method, path, opts) {
    opts = opts || {};
    const headers = Object.assign({ Authorization: `Bearer ${token}` }, opts.headers || {});
    const res = await fetch(path, { method, headers, body: opts.body });
    if (res.status === 403) {
      showAccessDenied();
      throw new Error("403");
    }
    if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
    return res.json();
  }

  function showAccessDenied() {
    document.getElementById("accessDeniedWrap").style.display = "block";
    document.getElementById("tabsWrap").style.display = "none";
  }

  function escapeHtml(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function setStatus(el, msg, cls) { el.textContent = msg; el.className = "admin-status-line " + (cls || ""); }
  function pluralize(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

  // ── Tab switcher ────────────────────────────────────────────────────────
  function switchAdminTab(name) {
    document.querySelectorAll(".cb-tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.atab === name));
    document.querySelectorAll(".admin-tab-panel").forEach((p) => p.classList.toggle("active", p.id === `atab-${name}`));
    if (name === "dashboard") loadDashboard();
  }
  window.switchAdminTab = switchAdminTab;

  // ── RCM: collections list ──────────────────────────────────────────────
  const COLLECTIONS_PAGE_SIZE = 8;
  let allCollections = [];
  let collectionsPage = 1;

  async function fetchCollections() {
    try {
      return await api("GET", "/chatbot/rcm/admin/collections");
    } catch {
      return [];
    }
  }

  async function refreshCollectionsUI() {
    allCollections = await fetchCollections();
    const totalPages = Math.max(1, Math.ceil(allCollections.length / COLLECTIONS_PAGE_SIZE));
    if (collectionsPage > totalPages) collectionsPage = totalPages;
    renderCollectionsPage();
  }

  function renderCollectionsPage() {
    const listEl = document.getElementById("rcmCollList");
    const pagEl = document.getElementById("rcmCollPagination");

    if (!allCollections.length) {
      listEl.innerHTML = `<div class="admin-empty-note">No collections yet. Import a folder above.</div>`;
      pagEl.innerHTML = "";
      return;
    }

    const totalPages = Math.max(1, Math.ceil(allCollections.length / COLLECTIONS_PAGE_SIZE));
    const start = (collectionsPage - 1) * COLLECTIONS_PAGE_SIZE;
    const pageItems = allCollections.slice(start, start + COLLECTIONS_PAGE_SIZE);

    listEl.innerHTML = pageItems.map((c) => `
      <div class="admin-coll-item">
        <div style="flex:1; min-width:220px;">
          <div class="admin-coll-name">${escapeHtml(c.pretty_name)}</div>
          <div class="admin-coll-name-raw" title="Pinecone namespace">${escapeHtml(c.name)}</div>
          <div class="admin-coll-meta">${pluralize(c.rows, "row")}</div>
        </div>
        <button class="admin-btn admin-btn-danger del-coll-btn" data-coll="${escapeHtml(c.name)}">Delete</button>
      </div>
    `).join("");

    listEl.querySelectorAll(".del-coll-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.getAttribute("data-coll");
        if (!confirm(`Delete collection "${name}" and all its data?`)) return;
        try {
          await api("DELETE", `/chatbot/rcm/admin/collections/${encodeURIComponent(name)}`);
          refreshCollectionsUI();
        } catch {}
      });
    });

    pagEl.innerHTML = `
      <button class="admin-btn admin-btn-ghost" id="rcmCollPrevBtn" ${collectionsPage <= 1 ? "disabled" : ""}>← Prev</button>
      <span class="admin-page-info">Page ${collectionsPage} of ${totalPages} · ${allCollections.length} collections</span>
      <button class="admin-btn admin-btn-ghost" id="rcmCollNextBtn" ${collectionsPage >= totalPages ? "disabled" : ""}>Next →</button>
    `;
    document.getElementById("rcmCollPrevBtn").addEventListener("click", () => {
      if (collectionsPage > 1) { collectionsPage--; renderCollectionsPage(); }
    });
    document.getElementById("rcmCollNextBtn").addEventListener("click", () => {
      if (collectionsPage < totalPages) { collectionsPage++; renderCollectionsPage(); }
    });
  }

  document.getElementById("rcmRefreshCollBtn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    try {
      await refreshCollectionsUI();
    } finally {
      btn.textContent = original;
      btn.disabled = false;
    }
  });

  // ── RCM: bulk folder upload ────────────────────────────────────────────
  const SUPPORTED_EXTS = ["xlsx", "xls", "csv", "docx", "pdf", "txt", "json"];
  const folderInput = document.getElementById("rcmFolderInput");
  const folderDrop = document.getElementById("rcmFolderDrop");
  const folderTitle = document.getElementById("rcmFolderTitle");
  const importFolderBtn = document.getElementById("rcmImportFolderBtn");
  const folderStatus = document.getElementById("rcmFolderStatus");

  function isSupportedFile(name) {
    if (name.startsWith("~$")) return false;
    const ext = name.split(".").pop().toLowerCase();
    return SUPPORTED_EXTS.includes(ext);
  }

  function skipReason(name) {
    if (name.startsWith("~$")) {
      return {
        reason: "This is Microsoft Office's own temporary lock file, auto-created while the real file is open in Excel/Word. It has no data in it.",
        action: "Close the real file in Excel/Word — this temp file disappears on its own.",
      };
    }
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "(no extension)";
    return {
      reason: `Unsupported file type ".${ext}" — only ${SUPPORTED_EXTS.map((e) => "." + e).join(", ")} are supported.`,
      action: "Convert or re-save this file as one of the supported types above, then re-run the import.",
    };
  }

  let skippedFiles = [];

  function openSkippedModal() {
    const body = document.getElementById("rcmSkippedModalBody");
    body.innerHTML = skippedFiles.map((f) => `
      <div class="admin-skip-item">
        <div class="admin-skip-file">${escapeHtml(f.name)}</div>
        <div class="admin-skip-reason">${escapeHtml(f.reason)}</div>
        <div class="admin-skip-action">${escapeHtml(f.action)}</div>
      </div>
    `).join("");
    document.getElementById("rcmSkippedModal").style.display = "flex";
  }
  function closeSkippedModal() {
    document.getElementById("rcmSkippedModal").style.display = "none";
  }
  document.getElementById("rcmSkippedModalClose").addEventListener("click", closeSkippedModal);
  document.getElementById("rcmSkippedModal").addEventListener("click", (e) => {
    if (e.target.id === "rcmSkippedModal") closeSkippedModal();
  });

  folderDrop.addEventListener("click", () => folderInput.click());
  folderInput.addEventListener("change", () => {
    const all = [...folderInput.files];
    const supported = all.filter((f) => isSupportedFile(f.name));
    skippedFiles = all.filter((f) => !isSupportedFile(f.name)).map((f) => ({ name: f.name, ...skipReason(f.name) }));
    importFolderBtn.disabled = !supported.length;
    setStatus(folderStatus, "", "");
    if (all.length && skippedFiles.length) {
      folderTitle.innerHTML = `${supported.length} file(s) ready (<button type="button" class="admin-skip-note-btn" id="rcmSkippedNoteBtn">${skippedFiles.length} skipped — why?</button>)`;
      document.getElementById("rcmSkippedNoteBtn").addEventListener("click", (e) => {
        e.stopPropagation();
        openSkippedModal();
      });
    } else if (all.length) {
      folderTitle.textContent = `${supported.length} file(s) ready`;
    } else {
      folderTitle.textContent = "Click to choose a folder";
    }
  });

  importFolderBtn.addEventListener("click", async () => {
    const files = [...folderInput.files].filter((f) => isSupportedFile(f.name));
    if (!files.length) return;
    importFolderBtn.disabled = true;

    let succeeded = 0, rowsTotal = 0;
    const failures = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      setStatus(folderStatus, `Uploading ${i + 1} of ${files.length}: ${file.name}…`, "info");
      try {
        const formData = new FormData();
        formData.append("files", file);
        const data = await api("POST", "/chatbot/rcm/admin/collections/bulk-upload", { body: formData });
        if (data.files_succeeded < 1) {
          throw new Error((data.results && data.results[0] && data.results[0].error) || "upload failed");
        }
        succeeded++;
        rowsTotal += data.rows_imported;
      } catch (err) {
        failures.push({ file: file.name, reason: err.message || "network error — request never reached the server" });
      }
    }

    let summary = `Imported ${succeeded} file(s) (${rowsTotal} rows) into their own collections.`;
    if (failures.length) {
      summary += ` ${failures.length} file(s) failed:\n` +
        failures.map((f) => `• ${f.file} — ${f.reason}`).join("\n");
    }
    setStatus(folderStatus, summary, failures.length ? "err" : "ok");
    folderInput.value = "";
    folderTitle.textContent = "Click to choose a folder";
    refreshCollectionsUI();
    importFolderBtn.disabled = false;
  });

  // ── HR Policy / JHS Library: single-file Update / Replace ─────────────────
  // Same wiring for both tabs — a single-file picker plus an Update button
  // (adds to the existing knowledge base) and a Replace button (wipes it
  // first, confirmed before proceeding since it's destructive).
  function formatHistoryDate(ts) {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  function wireKnowledgeUpload({ statEl, dropEl, inputEl, titleEl, updateBtn, replaceBtn, statusEl,
                                   statsPath, updatePath, replacePath, statLabel, fileNoun, warnLabel,
                                   historyPath, historyListEl }) {
    async function refreshStat() {
      try {
        const data = await api("GET", statsPath);
        const n = data.chunks !== undefined ? data.chunks : data.observations;
        statEl.textContent = `Currently: ${n} ${statLabel} in the knowledge base.`;
      } catch {
        statEl.textContent = "Couldn't load the current knowledge-base size.";
      }
    }

    async function refreshHistory() {
      if (!historyListEl) return;
      try {
        const rows = await api("GET", historyPath);
        if (!rows.length) {
          historyListEl.innerHTML = `<div class="admin-empty-note">No uploads yet.</div>`;
          return;
        }
        historyListEl.innerHTML = rows.map((r) => `
          <div class="admin-coll-item">
            <div style="flex:1; min-width:220px;">
              <div class="admin-coll-name">${escapeHtml(r.filename)}</div>
              <div class="admin-coll-meta">${escapeHtml(r.name || r.empid)} · ${r.mode === "replace" ? "Replaced" : "Updated"} · ${pluralize(r.count, statLabel.replace(/s$/, ""))}</div>
            </div>
            <div class="admin-coll-meta">${formatHistoryDate(r.created_at)}</div>
          </div>
        `).join("");
      } catch {
        historyListEl.innerHTML = `<div class="admin-empty-note">Couldn't load upload history.</div>`;
      }
    }

    dropEl.addEventListener("click", () => inputEl.click());
    inputEl.addEventListener("change", () => {
      const file = inputEl.files[0];
      titleEl.textContent = file ? file.name : `Click to choose ${fileNoun}`;
      updateBtn.disabled = !file;
      replaceBtn.disabled = !file;
    });

    async function upload(path, mode) {
      const file = inputEl.files[0];
      if (!file) return;
      updateBtn.disabled = true;
      replaceBtn.disabled = true;
      setStatus(statusEl, `${mode === "replace" ? "Replacing" : "Updating"} with ${file.name}…`, "info");
      try {
        const formData = new FormData();
        formData.append("file", file);
        const data = await api("POST", path, { body: formData });
        const count = data.chunks_added !== undefined ? data.chunks_added : data.rows_inserted;
        setStatus(statusEl, `Done — ${mode === "replace" ? "replaced with" : "added"} ${count} ${statLabel} from ${file.name}.`, "ok");
        inputEl.value = "";
        titleEl.textContent = `Click to choose ${fileNoun}`;
        await refreshStat();
        await refreshHistory();
      } catch (err) {
        setStatus(statusEl, err.message || "Upload failed.", "err");
      } finally {
        updateBtn.disabled = !inputEl.files[0];
        replaceBtn.disabled = !inputEl.files[0];
      }
    }

    updateBtn.addEventListener("click", () => upload(updatePath, "update"));
    replaceBtn.addEventListener("click", () => {
      const file = inputEl.files[0];
      if (!file) return;
      if (!confirm(`This will DELETE every existing ${warnLabel} and replace it with ${file.name}. This can't be undone. Continue?`)) return;
      upload(replacePath, "replace");
    });

    refreshStat();
    refreshHistory();
  }

  wireKnowledgeUpload({
    statEl: document.getElementById("hrKbStat"),
    dropEl: document.getElementById("hrFileDrop"),
    inputEl: document.getElementById("hrFileInput"),
    titleEl: document.getElementById("hrFileTitle"),
    updateBtn: document.getElementById("hrUpdateBtn"),
    replaceBtn: document.getElementById("hrReplaceBtn"),
    statusEl: document.getElementById("hrKbStatus"),
    statsPath: "/chatbot/admin/knowledge/stats",
    updatePath: "/chatbot/admin/knowledge/update",
    replacePath: "/chatbot/admin/knowledge/replace",
    statLabel: "chunks",
    fileNoun: "a file",
    warnLabel: "HR policy chunk",
    historyPath: "/chatbot/admin/knowledge/history",
    historyListEl: document.getElementById("hrHistoryList"),
  });

  wireKnowledgeUpload({
    statEl: document.getElementById("libKbStat"),
    dropEl: document.getElementById("libFileDrop"),
    inputEl: document.getElementById("libFileInput"),
    titleEl: document.getElementById("libFileTitle"),
    updateBtn: document.getElementById("libUpdateBtn"),
    replaceBtn: document.getElementById("libReplaceBtn"),
    statusEl: document.getElementById("libKbStatus"),
    statsPath: "/chatbot/library/admin/knowledge/stats",
    updatePath: "/chatbot/library/admin/knowledge/update",
    replacePath: "/chatbot/library/admin/knowledge/replace",
    statLabel: "observations",
    fileNoun: "a file",
    warnLabel: "observation",
    historyPath: "/chatbot/library/admin/knowledge/history",
    historyListEl: document.getElementById("libHistoryList"),
  });

  // ── Dashboard: active users + API usage per bot ────────────────────────
  const BOT_LABELS = { hr: "HR Policy", rcm: "RCM", library: "Observation Library" };
  let dashboardData = null;   // cached last successful fetch — see loadDashboard()
  let dashboardBot = "hr";    // which bot's user-activity table is showing

  function formatLastActive(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function renderDashboardSummary() {
    const el = document.getElementById("dashboardSummary");
    el.innerHTML = Object.keys(BOT_LABELS).map((bot) => {
      const d = dashboardData[bot] || {};
      const u = d.api_usage || {};
      const c = u.cost_usd || {};
      const fmt = (v) => `$${(v ?? 0).toFixed(2)}`;
      return `
        <div class="dash-bot-card">
          <div class="dash-bot-name">${BOT_LABELS[bot]}</div>
          <div class="dash-active-users"><span class="dash-num">${d.active_users ?? 0}</span> active user${d.active_users === 1 ? "" : "s"} (all-time)</div>
          <div class="dash-usage-row">
            <div class="dash-usage-cell"><span class="dash-num-sm">${u.today ?? 0}</span><label>Today</label></div>
            <div class="dash-usage-cell"><span class="dash-num-sm">${u.this_week ?? 0}</span><label>This week</label></div>
            <div class="dash-usage-cell"><span class="dash-num-sm">${u.this_month ?? 0}</span><label>This month</label></div>
            <div class="dash-usage-cell"><span class="dash-num-sm">${u.all_time ?? 0}</span><label>All time</label></div>
          </div>
          <div class="dash-usage-caption">LLM API calls</div>
          <div class="dash-usage-row">
            <div class="dash-usage-cell"><span class="dash-num-sm">${fmt(c.today)}</span><label>Today</label></div>
            <div class="dash-usage-cell"><span class="dash-num-sm">${fmt(c.this_week)}</span><label>This week</label></div>
            <div class="dash-usage-cell"><span class="dash-num-sm">${fmt(c.this_month)}</span><label>This month</label></div>
            <div class="dash-usage-cell"><span class="dash-num-sm">${fmt(c.all_time)}</span><label>All time</label></div>
          </div>
          <div class="dash-usage-caption">Estimated $ spent</div>
        </div>`;
    }).join("");
  }

  const WINDOW_LABELS = { today: "today", this_week: "this week", this_month: "this month", all_time: "all time" };
  let dashCompareWindow = "this_month";

  // Fixed categorical order — never reassigned when a bot has zero calls or
  // the window changes, so a color always means the same bot everywhere on
  // this page (see admin.css's .dash-series-* — validated palette slots 1-3).
  function renderDashCompareChart() {
    const headline = document.getElementById("dashCompareHeadline");
    const chart = document.getElementById("dashCompareChart");
    const bots = Object.keys(BOT_LABELS);
    const values = bots.map((bot) => (dashboardData[bot] && dashboardData[bot].api_usage && dashboardData[bot].api_usage[dashCompareWindow]) || 0);
    const max = Math.max(...values, 1);
    const windowLabel = WINDOW_LABELS[dashCompareWindow];

    const ranked = bots.map((bot, i) => ({ bot, value: values[i] })).sort((a, b) => b.value - a.value);
    const top = ranked[0], second = ranked[1];
    if (top.value === 0) {
      headline.textContent = `No LLM calls recorded yet ${windowLabel}.`;
    } else if (second.value === 0) {
      headline.innerHTML = `<strong>${BOT_LABELS[top.bot]}</strong> is the only bot with activity ${windowLabel} — ${top.value.toLocaleString()} call${top.value === 1 ? "" : "s"}.`;
    } else {
      const times = top.value / second.value;
      const timesText = times >= 1.05 ? ` — ${times.toFixed(1)}× ${BOT_LABELS[second.bot]}'s usage` : " — roughly tied with the next busiest bot";
      headline.innerHTML = `<strong>${BOT_LABELS[top.bot]}</strong> gets used the most ${windowLabel}, with <strong>${top.value.toLocaleString()}</strong> call${top.value === 1 ? "" : "s"}${timesText}.`;
    }

    chart.innerHTML = bots.map((bot, i) => {
      const value = values[i];
      const pct = value > 0 ? Math.max((value / max) * 100, 2) : 0;
      return `
        <div class="dash-bar-row dash-series-${bot}">
          <div class="dash-bar-label"><span class="dash-bar-swatch"></span>${BOT_LABELS[bot]}</div>
          <div class="dash-bar-track" title="${value.toLocaleString()} call${value === 1 ? "" : "s"} ${windowLabel}">
            <div class="dash-bar-fill" style="width:${pct}%"></div>
          </div>
          <div class="dash-bar-value">${value.toLocaleString()}</div>
        </div>`;
    }).join("");
  }

  document.querySelectorAll("#dashCompareWindowSwitch .dash-bot-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#dashCompareWindowSwitch .dash-bot-btn").forEach((b) => b.classList.toggle("active", b === btn));
      dashCompareWindow = btn.dataset.window;
      if (dashboardData) renderDashCompareChart();
    });
  });

  function renderDashboardUserTable() {
    const wrap = document.getElementById("dashUserTableWrap");
    const rows = (dashboardData[dashboardBot] || {}).user_activity || [];
    if (!rows.length) {
      wrap.innerHTML = `<div class="admin-empty-note">No chat activity yet for ${BOT_LABELS[dashboardBot]}.</div>`;
      return;
    }
    wrap.innerHTML = `
      <table class="dash-table">
        <thead><tr><th>Employee</th><th>Today</th><th>This week</th><th>This month</th><th>All time</th><th>Last active</th></tr></thead>
        <tbody>
          ${rows.map((r) => `
            <tr>
              <td><div class="dash-emp-name">${escapeHtml(r.name)}</div><div class="dash-emp-id">${escapeHtml(r.empid)}</div></td>
              <td>${r.today}</td>
              <td>${r.this_week}</td>
              <td>${r.this_month}</td>
              <td>${r.all_time}</td>
              <td>${formatLastActive(r.last_active)}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
  }

  const SEVERITY_LABEL = { red: "🔴", orange: "🟠", yellow: "🟡", critical: "⚠️" };
  let alertsData = null;
  let highAlertUsers = [];

  function renderHighAlertBanner() {
    const el = document.getElementById("dashHighAlertBanner");
    if (!highAlertUsers.length) { el.innerHTML = ""; return; }
    el.innerHTML = `
      <div class="dash-high-alert-banner">
        <div class="dash-high-alert-title">⚠️ HIGH ALERT — repeated red-flagged activity</div>
        <div class="dash-high-alert-list">
          ${highAlertUsers.map((u) => `
            <span class="dash-high-alert-chip">${escapeHtml(u.name)} (${escapeHtml(u.empid)}) — <strong>${u.red_session_count}</strong> red-flagged sessions</span>
          `).join("")}
        </div>
      </div>`;
  }

  function formatDateTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function renderAlerts() {
    const wrap = document.getElementById("dashAlertsWrap");
    const rows = alertsData || [];
    if (!rows.length) {
      wrap.innerHTML = `<div class="admin-empty-note">No retention-risk language detected in any chat yet.</div>`;
      return;
    }
    wrap.innerHTML = `
      <table class="dash-table dash-alerts-table">
        <thead><tr><th>Employee</th><th>Bot</th><th>Category</th><th>Date &amp; time</th><th>Chat message</th></tr></thead>
        <tbody>
          ${rows.map((a) => {
            const badges = a.matches.map((m) =>
              `<span class="dash-alert-badge dash-sev-${m.severity}">${SEVERITY_LABEL[m.severity] || ""} ${escapeHtml(m.label)} <em>"${escapeHtml(m.keyword)}"</em></span>`
            ).join("");
            const multiBadge = a.multi_signal ? `<span class="dash-alert-badge dash-sev-critical">⚠️ Multi-signal</span>` : "";
            return `
              <tr>
                <td><div class="dash-emp-name">${escapeHtml(a.name)}</div><div class="dash-emp-id">${escapeHtml(a.empid)}</div></td>
                <td>${BOT_LABELS[a.bot] || escapeHtml(a.bot)}</td>
                <td>${multiBadge}${badges}</td>
                <td>${formatDateTime(a.created_at)}</td>
                <td class="dash-alert-msg">${escapeHtml(a.message)}</td>
              </tr>`;
          }).join("")}
        </tbody>
      </table>`;
  }

  async function loadDashboard(forceRefresh) {
    if (dashboardData && !forceRefresh) {
      renderDashboardSummary();
      renderDashCompareChart();
      renderDashboardUserTable();
      renderHighAlertBanner();
      renderAlerts();
      return;
    }
    document.getElementById("dashboardSummary").textContent = "Loading…";
    document.getElementById("dashAlertsWrap").textContent = "Loading…";
    try {
      const [dashboard, alertsRes] = await Promise.all([
        api("GET", "/chatbot/admin/dashboard"),
        api("GET", "/chatbot/admin/alerts"),
      ]);
      dashboardData = dashboard;
      alertsData = alertsRes.alerts || [];
      highAlertUsers = alertsRes.high_alert_users || [];
      renderDashboardSummary();
      renderDashCompareChart();
      renderDashboardUserTable();
      renderHighAlertBanner();
      renderAlerts();
    } catch {
      document.getElementById("dashboardSummary").textContent = "Couldn't load dashboard data.";
      document.getElementById("dashAlertsWrap").textContent = "Couldn't load alerts.";
    }
  }

  document.getElementById("dashboardRefreshBtn").addEventListener("click", () => loadDashboard(true));

  // ── Alerts export (Excel, with week/month/custom date presets) ─────────
  document.querySelectorAll("#dashExportPresets .dash-bot-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#dashExportPresets .dash-bot-btn").forEach((b) => b.classList.toggle("active", b === btn));
      document.getElementById("dashExportDates").hidden = btn.dataset.preset !== "custom";
    });
  });

  function exportDateRange() {
    const preset = document.querySelector("#dashExportPresets .dash-bot-btn.active")?.dataset.preset || "all";
    const iso = (d) => d.toISOString().slice(0, 10);
    const today = new Date();
    if (preset === "week") {
      const monday = new Date(today);
      const dayOffset = (today.getDay() + 6) % 7; // Monday = 0
      monday.setDate(today.getDate() - dayOffset);
      return { start: iso(monday), end: iso(today) };
    }
    if (preset === "month") {
      const first = new Date(today.getFullYear(), today.getMonth(), 1);
      return { start: iso(first), end: iso(today) };
    }
    if (preset === "custom") {
      return {
        start: document.getElementById("dashExportFrom").value || "",
        end: document.getElementById("dashExportTo").value || "",
      };
    }
    return { start: "", end: "" }; // all time
  }

  document.getElementById("dashExportBtn").addEventListener("click", async () => {
    const btn = document.getElementById("dashExportBtn");
    const { start, end } = exportDateRange();
    const params = new URLSearchParams();
    if (start) params.set("start", start);
    if (end) params.set("end", end);

    btn.disabled = true;
    const originalHtml = btn.innerHTML;
    btn.innerHTML = "Preparing…";
    try {
      const res = await fetch(`/chatbot/admin/alerts/export.xlsx?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "retention-risk-alerts.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Couldn't generate the export. Please try again.");
      console.error(err);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  });
  document.querySelectorAll(".dash-bot-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".dash-bot-btn").forEach((b) => b.classList.toggle("active", b === btn));
      dashboardBot = btn.dataset.dashbot;
      renderDashboardUserTable();
    });
  });

  // ── Init ────────────────────────────────────────────────────────────────
  (async function init() {
    document.getElementById("loading-screen").style.display = "none";
    document.getElementById("main-content").style.display = "flex";
    document.getElementById("main-content").style.flexDirection = "column";
    try {
      await refreshCollectionsUI();
    } catch {
      // 403 already shown by api()
    }
  })();
})();
