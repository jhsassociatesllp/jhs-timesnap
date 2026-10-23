// static/timesheet/export.js - admin data export. Downloads Excel/CSV from /admin-exports/*.
// All server text is inserted with textContent.
(function () {
  "use strict";
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { Authorization: `Bearer ${token}` };

  function banner(text, kind) {
    const el = $("msg");
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text; el.className = "dt-banner " + kind; el.style.display = "block";
  }

  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  function setRange(a, b) { $("from").value = iso(a); $("to").value = iso(b); }

  function presets() {
    const box = $("presets");
    const today = new Date();
    const mk = (label, fn) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.onclick = fn; box.append(b); };
    mk("Last 10 days", () => setRange(new Date(today.getTime() - 9 * 86400000), today));
    mk("Last 30 days", () => setRange(new Date(today.getTime() - 29 * 86400000), today));
    mk("This payroll", () => {            // 21st to 20th
      const d = today.getDate();
      const start = d >= 21 ? new Date(today.getFullYear(), today.getMonth(), 21) : new Date(today.getFullYear(), today.getMonth() - 1, 21);
      const end = new Date(start.getFullYear(), start.getMonth() + 1, 20);
      setRange(start, end);
    });
    mk("Last payroll", () => {
      const d = today.getDate();
      const thisStart = d >= 21 ? new Date(today.getFullYear(), today.getMonth(), 21) : new Date(today.getFullYear(), today.getMonth() - 1, 21);
      setRange(new Date(thisStart.getFullYear(), thisStart.getMonth() - 1, 21), new Date(thisStart.getFullYear(), thisStart.getMonth(), 20));
    });
  }

  async function download(ds, btn) {
    banner("");
    const needs = ds.needs_dates;
    if (needs && (!$("from").value || !$("to").value)) { banner("Choose a From and To date first.", "warn"); return; }
    const q = new URLSearchParams({ format: $("fmt").value });
    if (needs) { q.set("from", $("from").value); q.set("to", $("to").value); }
    const emp = $("emp").value.trim();
    if (emp && needs) q.set("employee", emp.replace(/\s+/g, ""));
    btn.disabled = true; const label = btn.textContent; btn.textContent = "Preparing…";
    try {
      const res = await fetch(`/admin-exports/${encodeURIComponent(ds.id)}?${q}`, { headers });
      if (res.status === 401) { window.location.href = "/static/login.html"; return; }
      if (!res.ok) {
        let msg = `Export failed (${res.status})`;
        try { const d = await res.json(); if (d.detail) msg = typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail); } catch (_) { /* keep default */ }
        throw new Error(msg);
      }
      const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = m ? m[1] : `${ds.id}.${$("fmt").value}`;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      banner(`Downloaded ${a.download}`, "ok");
    } catch (err) { banner(err.message, "err"); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  async function start() {
    presets();
    const today = new Date();
    setRange(new Date(today.getTime() - 29 * 86400000), today);
    let info;
    try {
      const res = await fetch("/admin-exports/datasets", { headers });
      if (res.status === 401) { window.location.href = "/static/login.html"; return; }
      if (res.status === 403) { banner("Only admins can export data.", "err"); return; }
      info = await res.json();
    } catch (err) { banner("Could not load the export list: " + err.message, "err"); return; }
    $("limits").textContent = `Date ranges up to ${info.max_range_days} days; at most ${info.max_rows.toLocaleString()} rows per file. Every export is logged.`;
    const box = $("datasets");
    info.datasets.forEach((ds) => {
      const card = document.createElement("div"); card.className = "dcard";
      const h3 = document.createElement("h3"); const ic = document.createElement("i"); ic.className = "fas fa-table";
      h3.append(ic, document.createTextNode(ds.label));
      const p = document.createElement("p"); p.textContent = ds.description;
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "dt-btn";
      btn.textContent = "Download"; btn.onclick = () => download(ds, btn);
      card.append(h3, p, btn); box.append(card);
    });
  }
  start();
})();
