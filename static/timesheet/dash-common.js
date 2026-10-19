// static/timesheet/dash-common.js — helpers shared by the manager and portfolio dashboards.
// Everything from the server is inserted with textContent (never innerHTML).
window.Dash = (function () {
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; }
  const headers = { Authorization: `Bearer ${token}` };

  async function get(url) {
    const res = await fetch(url, { headers });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("auth"); }
    if (!res.ok) {
      let msg = (data && data.detail) || `Request failed (${res.status})`;
      if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join("; ");
      throw new Error(msg);
    }
    return data;
  }

  async function download(url, fallbackName) {
    const res = await fetch(url, { headers });
    if (!res.ok) {
      let msg = `Export failed (${res.status})`;
      try { const d = await res.json(); if (d.detail) msg = d.detail; } catch (_) { /* keep default */ }
      throw new Error(msg);
    }
    const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : fallbackName;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  function banner(id, text, kind) {
    const el = document.getElementById(id);
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text; el.className = "dt-banner " + kind; el.style.display = "block";
  }

  function kpi(box, label, value, cls) {
    const d = document.createElement("div"); d.className = "kpi " + (cls || "");
    const s = document.createElement("span"); s.textContent = label;
    const b = document.createElement("b"); b.textContent = value === null || value === undefined ? "—" : value;
    d.append(s, b); box.append(d);
  }

  const pct = (v) => (v === null || v === undefined ? "—" : v + "%");
  const fmt = (v) => (v === null || v === undefined ? "—" : String(v));

  function bar(cls, value, over) {
    const b = document.createElement("div"); b.className = "bar " + cls + (over ? " over" : "");
    const i = document.createElement("i"); i.style.width = Math.max(0, Math.min(100, value || 0)) + "%";
    b.append(i); return b;
  }

  function ragDot(r) { const s = document.createElement("span"); s.className = "rag " + r; s.title = r; return s; }

  function cell(tr, content) {
    const td = tr.insertCell();
    if (content instanceof Node) td.append(content); else td.textContent = fmt(content);
    return td;
  }

  function alerts(box, list) {
    box.textContent = "";
    if (!list.length) { box.textContent = "No alerts."; return; }
    list.forEach((a) => { const d = document.createElement("div"); d.className = "alert " + a.level; d.textContent = a.text; box.append(d); });
  }

  function notes(el, n) {
    el.textContent = "Hours include the legacy timesheet; compliance and reconciliation cover employees on the daily timesheet only; " +
      "team load assumes 100% allocation (Nexus Quant has no allocation field).";
  }

  return { get, download, banner, kpi, pct, fmt, bar, ragDot, cell, alerts, notes };
})();
