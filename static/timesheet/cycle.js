// static/timesheet/cycle.js — late projects: update a task's hours needed / end date. Talks to /timesheet/v2/cycles/*/at-risk.
// All server text goes through textContent.
(function () {
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

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
  const tag = (text, cls) => { const x = document.createElement("span"); x.className = "dt-tag " + (cls || ""); x.textContent = text; return x; };

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

  async function renderRisk(cycleId) {
    const box = $("risk"); box.textContent = "";
    let d;
    try { d = await call("GET", `/timesheet/v2/cycles/${cycleId}/at-risk${$("team").value.trim() ? "?manager=" + encodeURIComponent($("team").value.trim()) : ""}`); }
    catch (err) { box.textContent = err.message; return; }
    $("wbNote").textContent = d.writeback_enabled
      ? "New end dates are saved here AND written back to Nexus Quant."
      : "New end dates are saved here only (write-back to Nexus Quant is switched off).";
    if (!d.projects.length) { const n = document.createElement("div"); n.className = "none"; n.textContent = "No amber or red projects. Everything is on track."; box.append(n); return; }
    d.projects.forEach((p) => {
      const card = document.createElement("div"); card.className = "dt-card inner";
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
      const wrap = document.createElement("div"); wrap.className = "table-responsive"; wrap.append(tb);
      card.append(wrap); box.append(card);
    });
  }

  async function load() {
    banner("");
    try { await renderRisk($("cycleSel").value); } catch (err) { banner(err.message, "err"); }
  }

  $("go").onclick = load;
  fillCycles();
  (async () => {
    try {
      const a = await call("GET", "/hrms/access");
      if (a.is_admin) $("teamWrap").style.display = "flex";
      if (!a.is_admin && !a.is_manager) { banner("Only managers and admins can use this page.", "err"); return; }
      await load();
    } catch (err) { banner(err.message, "err"); }
  })();
})();
