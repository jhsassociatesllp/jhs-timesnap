// static/timesheet/team.js - Team dashboard for team leads, partners and admins. Talks to /timesheet/v2/team/*.
// Everything from the server is inserted with textContent (never innerHTML).
(function () {
  "use strict";
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { Authorization: `Bearer ${token}` };
  const B = "/timesheet/v2/team";

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === false || v == null) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
    kids.flat().forEach((c) => { if (c == null || c === false) return; el.append(c.nodeType ? c : document.createTextNode(String(c))); });
    return el;
  }
  const svg = (tag, attrs, ...kids) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, v));
    kids.forEach((c) => el.append(c));
    return el;
  };

  async function get(url) {
    const res = await fetch(url, { headers });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("Please log in again"); }
    if (!res.ok) {
      const d = data && data.detail;
      const err = new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((m) => m.msg).join("; ") : `Request failed (${res.status})`);
      err.status = res.status; throw err;
    }
    return data;
  }

  function banner(text, kind) {
    const el = $("msg");
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text; el.className = "dt-banner " + kind; el.style.display = "block";
  }
  const fmt = (v) => (v == null ? "—" : String(Math.round(v * 100) / 100));
  const signed = (v) => (v == null ? "—" : (v > 0 ? "+" : "") + String(Math.round(v * 100) / 100));
  const shortDate = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");

  const S = { opts: null, view: null };

  // ── filters ────────────────────────────────────────────────────────────────────────
  function fillPayrolls() {
    const sel = $("fPayroll"); sel.textContent = "";
    S.opts.payrolls.forEach((p) => sel.append(h("option", { value: p.id, text: `${p.label}${p.current ? " (running)" : ""}` })));
    const cur = S.opts.payrolls.find((p) => p.current) || S.opts.payrolls[0];
    sel.value = cur.id; fillCycles();
  }
  function fillCycles() {
    const p = S.opts.payrolls.find((x) => x.id === $("fPayroll").value);
    const sel = $("fCycle"); sel.textContent = "";
    sel.append(h("option", { value: "", text: "Whole payroll" }));
    p.cycles.forEach((c) => sel.append(h("option", { value: c.id, text: c.label + (c.current ? " (running)" : "") })));
  }
  function fillFilters(f) {
    const cSel = $("fClient"), pSel = $("fProject");
    const keepC = cSel.value, keepP = pSel.value;
    cSel.textContent = ""; cSel.append(h("option", { value: "", text: "All clients" }));
    f.clients.forEach((c) => cSel.append(h("option", { value: c === "" ? "__unplanned__" : c, text: c === "" ? "Unplanned work" : c })));
    cSel.value = [...cSel.options].some((o) => o.value === keepC) ? keepC : "";
    renderProjectChoices(f, keepP);
  }
  function renderProjectChoices(f, keep) {
    const pSel = $("fProject"), client = $("fClient").value;
    pSel.textContent = ""; pSel.append(h("option", { value: "", text: "All projects" }));
    f.projects.filter((p) => !client || client === "__unplanned__" ? !client : p.client === client)
      .forEach((p) => pSel.append(h("option", { value: p.code, text: `${p.name || p.code} (${p.code})` })));
    pSel.value = [...pSel.options].some((o) => o.value === keep) ? keep : "";
  }

  function query() {
    const q = new URLSearchParams({ payroll: $("fPayroll").value });
    if ($("fCycle").value) q.set("cycle", $("fCycle").value);
    if ($("fClient").value) q.set("client", $("fClient").value);
    if ($("fProject").value) q.set("project", $("fProject").value);
    if (!$("teamWrap").hidden && $("fTeam").value) q.set("manager", $("fTeam").value);
    return q;
  }

  // ── rendering ──────────────────────────────────────────────────────────────────────
  function tile(label, value, sub, cls, icon) {
    return h("div", { class: "kpi " + (cls || "") }, h("span", {}, h("i", { class: "fas " + icon }), label), h("b", { text: value }), sub ? h("div", { class: "cap", text: sub }) : null);
  }

  function renderTiles(v) {
    const t = v.tiles, box = $("tiles"); box.textContent = "";
    box.append(
      tile("Hours logged", fmt(t.hours), `${t.people} ${t.people === 1 ? "person" : "people"}`, "", "fa-hourglass-half"),
      tile("Typed vs HRMS", t.hrms_hours == null ? "—" : signed(t.diff_hours) + " h", t.hrms_hours == null ? (v.filtered ? "Not shown for one client or project" : "No HRMS data uploaded") : `HRMS ${fmt(t.hrms_hours)} h`,
        t.diff_hours != null && Math.abs(t.diff_hours) > 8 ? "amber" : "", "fa-scale-balanced"),
      tile("Days filled", t.days_filled_pct == null ? "—" : t.days_filled_pct + "%", "of the working days so far", t.days_filled_pct != null && t.days_filled_pct < 80 ? "amber" : "green", "fa-clipboard-check"),
      tile("Tasks done", `${t.tasks_done} of ${t.tasks_total}`, "in the projects shown", "", "fa-list-check"),
      tile("Overdue tasks", String(t.overdue), "not finished and past the end date", t.overdue ? "red" : "green", "fa-triangle-exclamation"),
      tile("Unplanned work", t.unplanned_pct + "%", "of the hours logged", t.unplanned_pct >= 15 ? "amber" : "", "fa-bolt"));
  }

  function renderAttention(v) {
    const box = $("attention"); box.textContent = "";
    if (!v.attention.length) { box.append(h("div", { class: "att ok" }, h("i", { class: "fas fa-circle-check" }), h("span", { text: "Nothing needs attention in this view." }))); return; }
    v.attention.forEach((a) => box.append(h("div", { class: "att " + a.level }, h("i", { class: "fas " + (a.level === "red" ? "fa-circle-exclamation" : a.level === "amber" ? "fa-triangle-exclamation" : "fa-circle-info") }), h("span", { text: a.text }))));
  }

  function renderChart(v) {
    const box = $("chart"); box.textContent = "";
    if (!v.daily.length) { box.append(h("div", { class: "empty", text: "No hours in this period yet." })); return; }
    const W = 900, H = 220, L = 38, R = 8, T = 14, Bm = 28, max = Math.max(...v.daily.map((d) => d.hours));
    const top = Math.ceil(max / 10) * 10 || 10, n = v.daily.length, bw = (W - L - R) / n;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", preserveAspectRatio: "none", "aria-label": `Bar chart of hours per day. Highest day ${fmt(max)} hours.` });
    [0, 0.5, 1].forEach((f) => {
      const y = T + (H - T - Bm) * (1 - f);
      s.append(svg("line", { x1: L, x2: W - R, y1: y, y2: y, class: f ? "grid" : "axis" }));
      const tx = svg("text", { x: L - 6, y: y + 4, "text-anchor": "end" }); tx.textContent = String(Math.round(top * f)); s.append(tx);
    });
    v.daily.forEach((d, i) => {
      const hh = (H - T - Bm) * (d.hours / top), x = L + i * bw + bw * 0.12;
      const r = svg("rect", { x, y: H - Bm - hh, width: Math.max(2, bw * 0.76), height: Math.max(1, hh), rx: 3, class: "bar" });
      const t = svg("title"); t.textContent = `${shortDate(d.date)}: ${fmt(d.hours)} h`; r.append(t); s.append(r);
      if (n <= 31 || i % Math.ceil(n / 31) === 0) { const tx = svg("text", { x: x + bw * 0.38, y: H - 10, "text-anchor": "middle" }); tx.textContent = String(Number(d.date.slice(8))); s.append(tx); }
    });
    box.append(s);
  }

  function renderProjects(v) {
    const body = $("projects"); body.textContent = "";
    if (!v.projects.length) { body.append(h("tr", {}, h("td", { colspan: "7", class: "empty-row", text: "No hours on any project in this view." }))); return; }
    const LABEL = { late: "Late", watch: "Watch", on_track: "On track", unknown: "No task data" };
    v.projects.forEach((p) => {
      const bar = p.allotted ? h("div", { class: "bar used" }, h("i", { style: `width:${Math.min(100, p.pct_used || 0)}%` })) : null;
      body.append(h("tr", {},
        h("td", {}, h("b", { text: p.label }), h("div", { class: "cap", text: [p.client, p.project_code].filter(Boolean).join(" · ") })),
        h("td", {}, h("span", { class: "st " + p.status, text: LABEL[p.status] || p.status }), p.reasons.length ? h("div", { class: "why", text: p.reasons.join("; ") }) : null),
        h("td", { class: "num", text: fmt(p.hours) }),
        h("td", {}, p.hours_so_far == null ? "—" : h("div", {}, bar, `${fmt(p.hours_so_far)} / ${p.allotted ? fmt(p.allotted) : "—"} h${p.pct_used != null ? ` (${p.pct_used}%)` : ""}`)),
        h("td", { class: "num", text: p.tasks_total ? `${p.tasks_done} of ${p.tasks_total}` : "—" }),
        h("td", { class: "num" + (p.overdue ? " bad" : ""), text: p.project_code ? String(p.overdue) : "—" }),
        h("td", { class: "num", text: String(p.people) })));
    });
    labelCells($("projects"));
  }

  function reviewCycle() {
    if ($("fCycle").value) return $("fCycle").value;
    const p = S.opts.payrolls.find((x) => x.id === $("fPayroll").value);
    return (p.cycles.find((c) => c.current) || p.cycles[p.cycles.length - 1]).id;
  }

  function renderPeople(v) {
    const body = $("people"); body.textContent = "";
    if (!v.people.length) { body.append(h("tr", {}, h("td", { colspan: "7", class: "empty-row", text: "No people in this team yet." }))); return; }
    const cyc = reviewCycle();
    v.people.forEach((p) => {
      body.append(h("tr", {},
        h("td", {}, h("b", { text: p.name || p.employee_id }), h("div", { class: "cap", text: p.employee_id })),
        h("td", { class: "num", text: fmt(p.hours) }),
        h("td", { class: "num", text: p.hrms_hours == null ? "—" : fmt(p.hrms_hours) }),
        h("td", { class: "num" + (p.diff_hours != null && Math.abs(p.diff_hours) > 4 ? " bad" : ""), text: p.diff_hours == null ? "—" : signed(p.diff_hours) }),
        h("td", { class: "num" + (p.missing_days ? " bad" : ""), text: `${p.days_filled} of ${p.days_required}` }),
        h("td", { class: "num", text: fmt(p.unplanned_hours) }),
        h("td", {}, h("a", { class: "rl", href: `/static/timesheet/review.html?cycle=${encodeURIComponent(cyc)}&emp=${encodeURIComponent(p.employee_id)}`, text: "Review" }))));
    });
    labelCells($("people"));
  }

  function renderClients(v) {
    const box = $("clients"); box.textContent = "";
    if (!v.clients.length) { box.append(h("div", { class: "empty", text: "No hours in this view." })); return; }
    v.clients.forEach((c) => box.append(h("div", { class: "cbar" }, h("div", { class: "nm", title: c.client, text: c.client }),
      h("div", { class: "tr", role: "img", "aria-label": `${c.client}: ${c.share} percent` }, h("i", { style: `width:${c.share}%` })), h("div", { class: "nv", text: `${fmt(c.hours)} h · ${c.share}%` }))));
  }

  function labelCells(tbody) {          // stacked cards on a narrow screen (same helper idea as the other dashboards)
    const heads = [...tbody.closest("table").querySelectorAll("thead th")].map((th) => th.textContent);
    [...tbody.rows].forEach((tr) => [...tr.cells].forEach((td, i) => { if (heads[i] && !td.classList.contains("empty-row")) td.setAttribute("data-label", heads[i]); }));
  }

  function render(v) {
    S.view = v;
    $("empty").hidden = true; $("content").hidden = false;
    $("periodLine").textContent = `${v.period.payroll} · ${v.period.cycle} (${shortDate(v.period.start)} – ${shortDate(v.period.end)})`;
    fillFilters(v.filters);
    renderTiles(v); renderAttention(v); renderChart(v); renderProjects(v); renderPeople(v); renderClients(v);
  }

  async function load() {
    banner("");
    try { render(await get(`${B}/data?${query()}`)); }
    catch (err) { $("content").hidden = true; banner(err.message, err.status === 403 ? "warn" : "err"); }
  }

  // ── Excel ──────────────────────────────────────────────────────────────────────────
  $("download").addEventListener("click", async (e) => {
    const btn = e.currentTarget, label = btn.innerHTML; banner("");
    btn.disabled = true; btn.textContent = "Preparing…";
    try {
      const res = await fetch(`${B}/export?${query()}`, { headers });
      if (!res.ok) { let m = `Download failed (${res.status})`; try { const d = await res.json(); if (d.detail) m = d.detail; } catch (_) { /* default */ } throw new Error(m); }
      const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
      const blob = await res.blob(), a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = m ? m[1] : "team_dashboard.xlsx";
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      banner(`Downloaded ${a.download}`, "ok");
    } catch (err) { banner(err.message, "err"); }
    finally { btn.disabled = false; btn.innerHTML = label; }
  });

  // ── wiring ─────────────────────────────────────────────────────────────────────────
  $("fPayroll").addEventListener("change", () => { fillCycles(); $("fClient").value = ""; $("fProject").value = ""; load(); });
  $("fCycle").addEventListener("change", load);
  $("fClient").addEventListener("change", () => { renderProjectChoices(S.view.filters, ""); load(); });
  $("fProject").addEventListener("change", load);
  $("fTeam").addEventListener("change", () => { $("fClient").value = ""; $("fProject").value = ""; load(); });
  $("reload").addEventListener("click", load);

  (async () => {
    try { S.opts = await get(`${B}/options`); }
    catch (err) { banner(err.status === 403 ? "The team dashboard is for team leads, partners and admins." : err.message, err.status === 403 ? "warn" : "err"); return; }
    if (!S.opts.payrolls.length) {
      $("empty").hidden = false;
      $("empty").textContent = "No payroll has been created yet. An admin creates one in Admin setup, and then the dashboard appears here.";
      return;
    }
    if (S.opts.is_firm) {
      $("teamWrap").hidden = false;
      S.opts.managers.forEach((m) => $("fTeam").append(h("option", { value: m.code, text: `${m.name || m.code} (${m.people})` })));
    }
    fillPayrolls();
    await load();
  })();
})();
