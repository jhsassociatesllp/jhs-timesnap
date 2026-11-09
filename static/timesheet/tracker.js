// static/timesheet/tracker.js - Project tracker for team leads, partners and admins. Talks to /timesheet/v2/tracker/*.
// Everything from the server is inserted with textContent (never innerHTML).
(function () {
  "use strict";
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { Authorization: `Bearer ${token}` };
  const B = "/timesheet/v2/tracker";

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
  const shortDate = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" }) : "—");
  const S = { view: null };

  function query() {
    const q = new URLSearchParams({ show: $("fShow").value });
    ["fClient:client", "fAudit:audit", "fStatus:status"].forEach((p) => { const [id, key] = p.split(":"); if ($(id).value) q.set(key, $(id).value); });
    if (!$("teamWrap").hidden && $("fTeam").value) q.set("manager", $("fTeam").value);
    return q;
  }

  function fillChoices(f) {
    [["fClient", f.clients, "All clients"], ["fAudit", f.audits, "All types"]].forEach(([id, items, all]) => {
      const sel = $(id), keep = sel.value;
      sel.textContent = ""; sel.append(h("option", { value: "", text: all }));
      items.forEach((x) => sel.append(h("option", { value: x, text: x })));
      sel.value = items.includes(keep) ? keep : "";
    });
  }

  function tile(label, value, sub, cls, icon) {
    return h("div", { class: "kpi " + (cls || "") }, h("span", {}, h("i", { class: "fas " + icon }), label), h("b", { text: String(value) }), sub ? h("div", { class: "cap", text: sub }) : null);
  }
  function renderTiles(v) {
    const k = v.kpis, box = $("tiles"); box.textContent = "";
    box.append(
      tile("Clients", k.clients, "linked to this view", "", "fa-building"),
      tile("Projects", k.projects, `${k.stages_done} of ${k.stages_total} stages done`, "", "fa-diagram-project"),
      tile("Completed", k.completed, "all stages done", "green", "fa-circle-check"),
      tile("Ongoing", k.ongoing, "work has started", "", "fa-spinner"),
      tile("Pending", k.pending, "nothing started yet", k.pending ? "amber" : "", "fa-hourglass-start"),
      tile("Not planned", k.not_planned, k.partly_planned ? `${k.partly_planned} partly planned` : "no stages with dates", k.not_planned ? "amber" : "green", "fa-calendar-xmark"),
      tile("Not assigned", k.not_assigned, k.partly_assigned ? `${k.partly_assigned} partly assigned` : "no one on the stages", k.not_assigned ? "amber" : "green", "fa-user-slash"),
      tile("On track", k.on_track, "", "green", "fa-thumbs-up"),
      tile("At risk", k.at_risk, "final report within 3 days", k.at_risk ? "amber" : "green", "fa-triangle-exclamation"),
      tile("Delayed", k.delayed, "past the date or a stage overdue", k.delayed ? "red" : "green", "fa-circle-exclamation"));
  }

  function renderSummary(v) {
    const box = $("summary"); box.textContent = "";
    v.summary.forEach((s) => box.append(h("div", { class: "sumline" }, h("i", { class: "fas fa-angle-right" }), h("span", { text: s }))));
    if (v.hidden_closed) box.append(h("div", { class: "sumline" }, h("i", { class: "fas fa-box-archive" }), h("span", { text: `${v.hidden_closed} closed project${v.hidden_closed === 1 ? " is" : "s are"} hidden. Choose "All, including closed" under Projects to see them.` })));
  }

  function tag(text, cls) { return h("span", { class: "tag " + (cls || ""), text }); }
  const planCls = (x) => (x === "Planned" ? "good" : x === "Partly planned" ? "warn" : "bad");
  const assignCls = (x) => (x === "Assigned" ? "good" : x === "Partly assigned" ? "warn" : "bad");

  function stagesTable(p) {
    if (!p.tasks.length) return h("div", { class: "cap", text: "No stages have been created for this project in Nexus Quant." });
    return h("table", {},
      h("thead", {}, h("tr", {}, ["Stage / task", "Start", "End", "Assigned to", "State", "Plan", "Assigned"].map((x) => h("th", { text: x })))),
      h("tbody", {}, p.tasks.map((t) => h("tr", {},
        h("td", { class: t.sub_task ? "sub-task" : "", text: (t.sub_task ? "↳ " : "") + t.name }),
        h("td", { text: shortDate(t.start) }), h("td", { text: shortDate(t.end) }),
        h("td", { text: t.assignees.length ? t.assignees.join(", ") : "Nobody" }),
        h("td", {}, tag(t.state, t.state === "Completed" ? "good" : ""), t.overdue ? tag("Overdue", "bad") : null),
        h("td", {}, tag(t.planned ? "Planned" : "Not planned", t.planned ? "good" : "bad")),
        h("td", {}, tag(t.assigned ? "Assigned" : "Not assigned", t.assigned ? "good" : "bad"))))));
  }

  function renderProjects(v) {
    const body = $("projects"); body.textContent = "";
    if (!v.projects.length) { body.append(h("tr", {}, h("td", { colspan: "9", class: "empty-row", text: "No projects match this view." }))); return; }
    v.projects.forEach((p) => {
      const pct = p.stages_total ? Math.round(100 * p.stages_done / p.stages_total) : 0;
      const detail = h("tr", { class: "detail", hidden: true }, h("td", { colspan: "9" }, stagesTable(p),
        p.next_stage ? h("div", { class: "cap", text: `Next open stage: ${p.next_stage}${p.next_stage_due ? " (due " + shortDate(p.next_stage_due) + ")" : ""}` }) : null));
      const row = h("tr", { class: "pr", tabindex: "0", "aria-expanded": "false", onclick: toggle, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } } },
        h("td", {}, h("span", { class: "chev" }, h("i", { class: "fas fa-chevron-right" })), h("b", { text: p.project }),
          h("div", { class: "cap", text: [p.client, p.code, p.role].filter(Boolean).join(" · ") })),
        h("td", { text: p.audit_type }),
        h("td", {}, h("span", { class: "st " + p.status, text: p.status_label })),
        h("td", { text: p.state }),
        h("td", {}, h("div", { class: "prog", role: "img", "aria-label": `${pct} percent of stages done` }, h("i", { style: `width:${pct}%` })),
          h("span", { class: "cap", text: p.stages_total ? `${p.stages_done} of ${p.stages_total} stages` : "No stages" }),
          p.stages_overdue ? h("div", { class: "cap bad", text: `${p.stages_overdue} overdue` }) : null),
        h("td", {}, tag(p.plan, planCls(p.plan)), p.stages_undated && p.plan !== "Not planned" ? h("div", { class: "cap", text: `${p.stages_undated} without dates` }) : null),
        h("td", {}, tag(p.assigned, assignCls(p.assigned)), p.stages_unassigned && p.assigned !== "Not assigned" ? h("div", { class: "cap", text: `${p.stages_unassigned} without anyone` }) : null),
        h("td", {}, h("div", { text: shortDate(p.deadline) }), p.days_left == null || p.state === "Completed" ? null : h("div", { class: "cap", text: p.days_left < 0 ? `${-p.days_left} days late` : p.days_left === 0 ? "today" : `${p.days_left} days left` })),
        h("td", {}, p.week.length ? h("div", { class: "cap", text: p.week.map((w) => `${w.name} ${w.hours} h`).join(", ") }) : h("span", { class: "cap", text: "No hours this week" })));
      function toggle() { const open = detail.hidden; detail.hidden = !open; row.classList.toggle("open", open); row.setAttribute("aria-expanded", String(open)); }
      body.append(row, detail);
    });
    labelCells(body);
  }

  function renderClients(v) {
    const body = $("clients"); body.textContent = "";
    if (!v.clients.length) { body.append(h("tr", {}, h("td", { colspan: "9", class: "empty-row", text: "No clients in this view." }))); return; }
    v.clients.forEach((c) => body.append(h("tr", {},
      h("td", {}, h("b", { text: c.client })),
      ...["projects", "completed", "ongoing", "pending", "on_hold", "not_planned", "not_assigned", "delayed"].map((k) =>
        h("td", { class: "num" + ((k === "delayed" || k === "not_planned" || k === "not_assigned") && c[k] ? " bad" : ""), text: String(c[k]) })))));
    labelCells(body);
  }

  function labelCells(tbody) {          // stacked cards on a narrow screen
    const heads = [...tbody.closest("table").querySelectorAll("thead th")].map((th) => th.textContent);
    [...tbody.rows].forEach((tr) => { if (!tr.classList.contains("detail")) [...tr.cells].forEach((td, i) => { if (heads[i] && !td.classList.contains("empty-row")) td.setAttribute("data-label", heads[i]); }); });
  }

  function render(v) {
    S.view = v;
    if (v.nq_unavailable) { $("content").hidden = true; banner("Project data from Nexus Quant is unavailable right now. Please try again in a minute.", "warn"); return; }
    $("content").hidden = false;
    $("asOf").textContent = `${v.manager} · as of ${shortDate(v.as_of)} · from Nexus Quant`;
    if (v.note) banner(v.note, "warn");
    fillChoices(v.filters);
    renderTiles(v); renderSummary(v); renderProjects(v); renderClients(v);
  }

  async function load() {
    banner("");
    try {
      const v = await get(`${B}/data?${query()}`);
      if (v.is_firm && $("teamWrap").hidden) {
        $("teamWrap").hidden = false;
        v.managers.forEach((m) => $("fTeam").append(h("option", { value: m.code, text: `${m.name || m.code} (${m.people})` })));
      }
      render(v);
    } catch (err) { $("content").hidden = true; banner(err.message, err.status === 403 ? "warn" : "err"); }
  }

  $("download").addEventListener("click", async (e) => {
    const btn = e.currentTarget, label = btn.innerHTML; banner("");
    btn.disabled = true; btn.textContent = "Preparing…";
    try {
      const res = await fetch(`${B}/export?${query()}`, { headers });
      if (!res.ok) { let m = `Download failed (${res.status})`; try { const d = await res.json(); if (d.detail) m = d.detail; } catch (_) { /* default */ } throw new Error(m); }
      const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
      const blob = await res.blob(), a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = m ? m[1] : "project_tracker.xlsx";
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      banner(`Downloaded ${a.download}`, "ok");
    } catch (err) { banner(err.message, "err"); }
    finally { btn.disabled = false; btn.innerHTML = label; }
  });

  ["fShow", "fClient", "fAudit", "fStatus"].forEach((id) => $(id).addEventListener("change", load));
  $("fTeam").addEventListener("change", () => { $("fClient").value = ""; $("fAudit").value = ""; load(); });
  $("reload").addEventListener("click", load);
  load();
})();
