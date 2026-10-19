// static/timesheet/cycle.js — 10-day cycle review. Talks to /timesheet/v2/cycles/*.
// All server text goes through textContent.
(function () {
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  let isAdmin = false;
  let pendingWarnings = null;     // set when the server asks for confirmation

  function banner(text, kind) {
    const el = $("msg");
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text; el.className = "dt-banner " + kind; el.style.display = "block";
  }

  async function call(method, url, body) {
    const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("auth"); }
    if (!res.ok) {
      const err = new Error("Request failed");
      err.status = res.status; err.detail = data && data.detail;
      let msg = err.detail || `Request failed (${res.status})`;
      if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join("; ");
      else if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
      err.message = msg;
      throw err;
    }
    return data;
  }

  function cell(tr, text) { tr.insertCell().textContent = text === null || text === undefined ? "—" : text; }
  const tag = (text, cls) => { const s = document.createElement("span"); s.className = "dt-tag " + (cls || ""); s.textContent = text; return s; };

  // cycle ids look like 2026-10-C2: offer the current and the three previous cycles
  function cycleFor(d) { const c = d.getDate() <= 10 ? 1 : d.getDate() <= 20 ? 2 : 3; return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-C${c}`; }
  function fillCycles() {
    const sel = $("cycleSel"); sel.textContent = "";
    const seen = new Set();
    const d = new Date();
    for (let i = 0; i < 4; i++) {
      const id = cycleFor(d);
      if (!seen.has(id)) { seen.add(id); const o = document.createElement("option"); o.value = id; o.textContent = id; sel.append(o); }
      d.setDate(d.getDate() - 10);
    }
  }

  const selected = () => Array.from(document.querySelectorAll("#rows input[type=checkbox]:checked")).map((c) => c.value);

  function renderTeam(d) {
    $("cycleInfo").textContent = `${d.cycle.label} · ${d.cycle.start} to ${d.cycle.end} · fill by ${d.cycle.deadline}` +
      (d.cycle.past_deadline ? " (deadline passed)" : "");
    const body = $("rows"); body.textContent = "";
    if (!d.rows.length) {
      const td = body.insertRow().insertCell(); td.colSpan = 9; td.className = "dt-muted"; td.textContent = "No employees on the daily timesheet in this team."; return;
    }
    d.rows.forEach((r) => {
      const tr = body.insertRow();
      const c = tr.insertCell(); const cb = document.createElement("input"); cb.type = "checkbox"; cb.value = r.employee_id; c.append(cb);
      cell(tr, `${r.employee_name || ""} (${r.employee_id})`);
      cell(tr, `${r.days_filled} / ${r.days_required}`);
      cell(tr, r.hrms_hours); cell(tr, r.timesheet_hours); cell(tr, r.unplanned); cell(tr, r.reco_gaps);
      tr.insertCell().append(tag(r.status === "approved" ? "Approved & locked" : r.status === "reopened" ? "Reopened" : "Pending",
        r.status === "approved" ? "green" : r.status === "reopened" ? "amber" : ""));
      const w = tr.insertCell(); w.textContent = r.warnings.join("; ");
    });
  }

  async function renderRisk(cycleId) {
    const box = $("risk"); box.textContent = "";
    let d;
    try { d = await call("GET", `/timesheet/v2/cycles/${cycleId}/at-risk${$("team").value.trim() ? "?manager=" + encodeURIComponent($("team").value.trim()) : ""}`); }
    catch (err) { box.textContent = err.message; return; }
    $("wbNote").textContent = d.writeback_enabled
      ? "New end dates are saved here AND written back to Nexus Quant."
      : "New end dates are saved here only (write-back to Nexus Quant is switched off).";
    if (!d.projects.length) { box.textContent = "No amber or red projects."; return; }
    d.projects.forEach((p) => {
      const card = document.createElement("div"); card.className = "dt-card"; card.style.margin = ".6rem 0";
      const h = document.createElement("div");
      h.append(tag(p.rag.toUpperCase(), p.rag === "red" ? "red" : "amber"), " ", `${p.project_code} · ${p.project_name} (${p.client_name})`);
      const m = document.createElement("div"); m.className = "dt-muted";
      m.textContent = `Hours ${p.hours_used} / ${p.budget_hours} · tasks done ${p.tasks_done}/${p.tasks_total} · overdue ${p.overdue_tasks} · gap ${p.gap_points} pts · planned end ${p.planned_end || "—"} · forecast ${p.forecast_end || "—"}`;
      card.append(h, m);
      const tb = document.createElement("table"); tb.className = "dt-grid";
      p.tasks.forEach((t) => {
        const tr = tb.insertRow();
        cell(tr, t.name); cell(tr, t.status); cell(tr, t.end_date);
        if (t.is_overdue) tr.cells[2].append(" ", tag("overdue", "red"));
        const act = tr.insertCell();
        const hrs = document.createElement("input"); hrs.type = "number"; hrs.min = "0"; hrs.step = "0.5"; hrs.placeholder = "hours needed"; hrs.style.width = "110px";
        const dt = document.createElement("input"); dt.type = "date"; dt.title = "new end date";
        const btn = document.createElement("button"); btn.type = "button"; btn.className = "dt-btn go small"; btn.textContent = "Save";
        btn.onclick = async () => {
          banner("");
          try {
            const r = await call("POST", `/timesheet/v2/cycles/${cycleId}/reestimate`,
              { task_id: t.task_id, hours_needed: Number(hrs.value), new_end_date: dt.value, note: "" });
            banner(r.written_back ? "Saved and written back to Nexus Quant." :
              r.writeback_error ? `Saved here. Write-back to Nexus Quant failed: ${r.writeback_error}` : "Saved here.", r.writeback_error ? "warn" : "ok");
          } catch (err) { banner(err.message, "err"); }
        };
        act.append(hrs, " ", dt, " ", btn);
      });
      card.append(tb); box.append(card);
    });
  }

  async function load() {
    banner(""); $("confirmWrap").style.display = "none"; pendingWarnings = null;
    const id = $("cycleSel").value;
    const team = $("team").value.trim();
    try {
      renderTeam(await call("GET", `/timesheet/v2/cycles/${id}/team${team ? "?manager=" + encodeURIComponent(team) : ""}`));
      await renderRisk(id);
    } catch (err) { banner(err.message, "err"); }
  }

  $("approveBtn").onclick = async () => {
    const ids = selected();
    if (!ids.length) { banner("Select at least one employee.", "warn"); return; }
    banner("");
    try {
      const r = await call("POST", `/timesheet/v2/cycles/${$("cycleSel").value}/approve`,
        { employee_ids: ids, confirm_warnings: $("confirm").checked && !!pendingWarnings });
      banner(`Approved and locked: ${r.approved.join(", ")}.`, "ok");
      await load();
    } catch (err) {
      if (err.status === 409 && err.detail && err.detail.warnings) {
        pendingWarnings = err.detail.warnings;
        $("confirmText").textContent = " I understand: " + Object.entries(pendingWarnings).map(([e, w]) => `${e} (${w.join(", ")})`).join("; ") + " — approve anyway.";
        $("confirm").checked = false; $("confirmWrap").style.display = "block";
        banner("Some selected employees have open items. Tick the confirmation box and press Approve again.", "warn");
      } else banner(err.message, "err");
    }
  };

  $("remindBtn").onclick = async () => {
    const ids = selected();
    if (!ids.length) { banner("Select at least one employee.", "warn"); return; }
    banner("");
    try {
      const r = await call("POST", `/timesheet/v2/cycles/${$("cycleSel").value}/remind`, { employee_ids: ids });
      banner(`Reminders sent: ${r.sent.length}. Skipped: ${r.skipped.map((s) => `${s.employee_id} (${s.reason || s.status})`).join(", ") || "none"}.`, r.sent.length ? "ok" : "warn");
    } catch (err) { banner(err.message, "err"); }
  };

  $("unlockBtn").onclick = async () => {
    const ids = selected();
    if (ids.length !== 1) { banner("Select exactly one employee to unlock.", "warn"); return; }
    const reason = window.prompt("Reason for unlocking (recorded in the audit log):");
    if (!reason || reason.trim().length < 3) return;
    try {
      await call("POST", `/timesheet/v2/cycles/${$("cycleSel").value}/unlock`, { employee_id: ids[0], reason: reason.trim() });
      banner(`${ids[0]} unlocked.`, "ok"); await load();
    } catch (err) { banner(err.message, "err"); }
  };

  $("go").onclick = load;
  fillCycles();
  (async () => {
    try {
      const a = await call("GET", "/hrms/access");
      isAdmin = a.is_admin;
      if (a.is_admin) { $("teamWrap").style.display = "block"; $("unlockBtn").style.display = "inline-block"; }
      if (!a.is_admin && !a.is_manager) { banner("Only managers and admins can review cycles.", "err"); return; }
      await load();
    } catch (err) { banner(err.message, "err"); }
  })();
})();
