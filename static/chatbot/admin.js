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
  function wireKnowledgeUpload({ statEl, dropEl, inputEl, titleEl, updateBtn, replaceBtn, statusEl,
                                   statsPath, updatePath, replacePath, statLabel, fileNoun, warnLabel }) {
    async function refreshStat() {
      try {
        const data = await api("GET", statsPath);
        const n = data.chunks !== undefined ? data.chunks : data.observations;
        statEl.textContent = `Currently: ${n} ${statLabel} in the knowledge base.`;
      } catch {
        statEl.textContent = "Couldn't load the current knowledge-base size.";
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
        </div>`;
    }).join("");
  }

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
      renderDashboardUserTable();
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
      renderDashboardSummary();
      renderDashboardUserTable();
      renderAlerts();
    } catch {
      document.getElementById("dashboardSummary").textContent = "Couldn't load dashboard data.";
      document.getElementById("dashAlertsWrap").textContent = "Couldn't load alerts.";
    }
  }

  document.getElementById("dashboardRefreshBtn").addEventListener("click", () => loadDashboard(true));
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
