// static/timesheet/portfolio.js — founder/partner portfolio (wireframe screen 7). Reads /dashboard/portfolio
// and downloads /exports/*. Partners and admins only (the server enforces it).
(function () {
  const D = window.Dash;
  const $ = (id) => document.getElementById(id);

  function render(d) {
    $("asOf").textContent = d.as_of ? `Snapshot ${d.as_of} · compliance ${d.window.from} to ${d.window.to}` : "No snapshot yet — the nightly job has not run.";
    const k = d.kpis, box = $("kpis"); box.textContent = "";
    D.kpi(box, "Active projects", k.projects);
    D.kpi(box, "Red", k.red, "red"); D.kpi(box, "Amber", k.amber, "amber"); D.kpi(box, "Green", k.green, "green");
    D.kpi(box, "Overdue tasks", k.overdue_tasks);
    D.kpi(box, "Hours used", k.hours_used);
    D.kpi(box, "Timesheet compliance", D.pct(k.compliance_pct));
    D.kpi(box, "Unplanned work", D.pct(k.unplanned_pct));
    D.kpi(box, "HRMS reco matched", D.pct(k.reco_matched_pct));

    const rb = $("risk"); rb.textContent = "";
    if (!d.at_risk_projects.length) { const td = rb.insertRow().insertCell(); td.colSpan = 7; td.className = "dt-muted"; td.textContent = "No amber or red projects."; }
    d.at_risk_projects.forEach((p) => {
      const tr = rb.insertRow();
      const name = document.createElement("span"); name.append(D.ragDot(p.rag), `${p.project_code} · ${p.project_name || ""}`);
      D.cell(tr, name); D.cell(tr, (p.manager_names || []).join(", "));
      const h = document.createElement("div"); h.append(D.bar("used", p.hours_used_pct), `${D.fmt(p.hours_used)} / ${D.fmt(p.budget_hours)} h`);
      D.cell(tr, h);
      const t = document.createElement("div"); t.append(D.bar("done", p.tasks_done_pct), `${p.tasks_done}/${p.tasks_total}`);
      D.cell(tr, t);
      D.cell(tr, p.overdue_tasks); D.cell(tr, p.planned_end);
      D.cell(tr, p.forecast_end ? `${p.forecast_end}${p.days_late_forecast > 0 ? ` (+${p.days_late_forecast} d)` : ""}` : "—");
    });

    const cb = $("comp"); cb.textContent = "";
    if (!d.compliance_by_manager.length) { const td = cb.insertRow().insertCell(); td.colSpan = 6; td.className = "dt-muted"; td.textContent = "No compliance data in this window."; }
    d.compliance_by_manager.forEach((m) => {
      const tr = cb.insertRow();
      D.cell(tr, `${m.manager_name || ""} (${m.manager_id})`); D.cell(tr, m.team_size);
      const c = document.createElement("div"); c.append(D.bar("done", m.compliance_pct), D.pct(m.compliance_pct));
      D.cell(tr, c); D.cell(tr, D.pct(m.unplanned_pct)); D.cell(tr, D.pct(m.reco_matched_pct)); D.cell(tr, m.hours);
    });
    D.alerts($("alerts"), d.alerts);
    D.notes($("notes"), d.notes);
  }

  async function load() {
    D.banner("msg", "");
    try { render(await D.get(`/dashboard/portfolio?days=${$("days").value}`)); }
    catch (err) { D.banner("msg", err.message, "err"); }
  }

  document.querySelectorAll("[data-export]").forEach((btn) => {
    btn.onclick = async () => {
      D.banner("msg", "");
      const f = $("from").value, t = $("to").value;
      if (!f || !t) { D.banner("msg", "Choose a From and To date for the export.", "warn"); return; }
      try { await D.download(`/exports/${btn.dataset.export}?from=${f}&to=${t}`, `${btn.dataset.export}.xlsx`); }
      catch (err) { D.banner("msg", err.message, "err"); }
    };
  });

  const today = new Date();
  const iso = (d) => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
  $("to").value = iso(today); $("from").value = iso(new Date(today.getTime() - 30 * 86400000));
  $("go").onclick = load;
  (async () => {
    try {
      const a = await D.get("/dashboard/access");
      if (!a.portfolio) { D.banner("msg", "Only partners and admins can view the portfolio.", "err"); return; }
      await load();
    } catch (err) { D.banner("msg", err.message, "err"); }
  })();
})();
