// static/timesheet/manager.js — manager dashboard (wireframe screen 6). Reads /dashboard/manager only.
(function () {
  const D = window.Dash;
  const $ = (id) => document.getElementById(id);

  function render(d) {
    $("asOf").textContent = d.as_of ? `Snapshot ${d.as_of} · compliance ${d.window.from} to ${d.window.to}` : "No snapshot yet: the nightly job has not run.";
    const k = d.kpis, box = $("kpis"); box.textContent = "";
    D.kpi(box, "Active projects", k.active_projects, "", "fa-diagram-project");
    D.kpi(box, "Overdue tasks", k.overdue_tasks, k.overdue_tasks ? "red" : "green", "fa-triangle-exclamation");
    D.kpi(box, "Timesheet compliance", D.pct(k.compliance_pct), k.compliance_pct !== null && k.compliance_pct < 80 ? "amber" : "", "fa-clipboard-check");
    D.kpi(box, "Unplanned work", D.pct(k.unplanned_pct), "", "fa-bolt");
    D.kpi(box, "HRMS reco matched", D.pct(k.reco_matched_pct), k.reco_matched_pct !== null && k.reco_matched_pct < 80 ? "amber" : "", "fa-scale-balanced");

    const pb = $("projects"); pb.textContent = "";
    if (!d.projects.length) { const td = pb.insertRow().insertCell(); td.colSpan = 7; td.className = "empty-row"; td.textContent = "No projects found for this manager."; }
    d.projects.forEach((p) => {
      const tr = pb.insertRow();
      const name = document.createElement("div");
      const title = document.createElement("b"); title.textContent = p.project_name || p.project_code;
      const code = document.createElement("div"); code.className = "cap"; code.textContent = p.project_code;
      name.append(D.ragDot(p.rag), title, code);
      D.cell(tr, name);
      const hours = document.createElement("div");
      hours.append(D.bar("used", p.hours_used_pct), `${D.fmt(p.hours_used)} / ${D.fmt(p.budget_hours)} h (${D.pct(p.hours_used_pct)})`);
      D.cell(tr, hours);
      const done = document.createElement("div");
      done.append(D.bar("done", p.tasks_done_pct), `${p.tasks_done}/${p.tasks_total} (${D.pct(p.tasks_done_pct)})`);
      D.cell(tr, done);
      const od = D.cell(tr, p.overdue_tasks); if (p.overdue_tasks > 0) od.classList.add("bad");
      D.cell(tr, p.days_since_last_entry === null ? "never" : p.days_since_last_entry + " d ago");
      D.cell(tr, p.planned_end); D.cell(tr, p.forecast_end);
    });

    const lb = $("load"); lb.textContent = "";
    if (!d.team_load.length) { const td = lb.insertRow().insertCell(); td.colSpan = 4; td.className = "empty-row"; td.textContent = "No team data yet."; }
    d.team_load.forEach((t) => {
      const tr = lb.insertRow();
      const who = document.createElement("div");
      const nm = document.createElement("b"); nm.textContent = t.employee_name || t.employee_id;
      const cd = document.createElement("div"); cd.className = "cap"; cd.textContent = t.employee_id;
      who.append(nm, cd); D.cell(tr, who);
      const b = document.createElement("div"); b.append(D.bar("load", t.load_pct, t.load_pct > 100), `${t.load_pct}%`);
      D.cell(tr, b);
      D.cell(tr, `${t.remaining_hours} / ${t.capacity_hours}`); D.cell(tr, t.open_tasks);
    });
    D.label(pb); D.label(lb);
    D.alerts($("alerts"), d.alerts);
    D.notes($("notes"), d.notes);
  }

  async function load() {
    D.banner("msg", "");
    const m = $("mgr").value.trim();
    try { render(await D.get(`/dashboard/manager?days=${$("days").value}${m ? "&manager=" + encodeURIComponent(m) : ""}`)); }
    catch (err) { D.banner("msg", err.message, "err"); }
  }

  $("go").onclick = load;
  (async () => {
    try {
      const a = await D.get("/dashboard/access");
      if (a.is_admin || a.is_partner) $("mgrWrap").style.display = "flex";
      if (!a.manager_dashboard) { D.banner("msg", "Only managers, partners and admins have a dashboard.", "err"); return; }
      await load();
    } catch (err) { D.banner("msg", err.message, "err"); }
  })();
})();
