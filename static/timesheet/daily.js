// static/timesheet/daily.js — hours-only daily timesheet (pilot). Talks to /timesheet/v2/*.
// All server text is inserted with textContent (task names come from NQ).
(function () {
  const emp = (localStorage.getItem("loggedInEmployeeId") || "").trim().toUpperCase();
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  if (!token || !emp) { window.location.href = "/static/login.html"; return; }

  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  let state = null;   // last payload from the server

  function today() {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  }

  function banner(text, kind) {
    const el = $("bnMsg");
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text;
    el.className = "dt-banner " + kind;
    el.style.display = "block";
  }

  async function api(method, url, body) {
    const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("auth"); }
    if (!res.ok) {
      let msg = (data && data.detail) || `Request failed (${res.status})`;
      if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join("; ");
      const err = new Error(msg); err.status = res.status; throw err;
    }
    return data;
  }

  const day = () => $("dayPicker").value;
  const num = (v) => (v === null || v === undefined || v === "" ? null : Number(v));
  const fmt = (v) => (v === null || v === undefined ? "—" : String(Math.round(v * 100) / 100));

  // ── rendering ──────────────────────────────────────────────────────────────
  function renderHrms(h) {
    const el = $("hrmsStrip");
    el.textContent = "";
    if (!h) { el.textContent = "HRMS data not uploaded for this day yet (awaiting HRMS)."; return; }
    if (h.is_leave) { el.textContent = "Leave / holiday per HRMS — no timesheet expected."; return; }
    [["In", h.in_time], ["Out", h.out_time], ["Gross", fmt(h.gross)], ["Lunch", fmt(h.lunch)], ["Net", fmt(h.net)]]
      .forEach(([k, v]) => {
        const box = document.createElement("div");
        const s = document.createElement("span"); s.textContent = k;
        const b = document.createElement("b"); b.textContent = v || "—";
        box.append(s, b); el.append(box);
      });
  }

  function renderTasks(tasks) {
    const body = $("tasksBody");
    body.textContent = "";
    if (!tasks.length) {
      const tr = body.insertRow(); const td = tr.insertCell(); td.colSpan = 5;
      td.className = "dt-muted"; td.textContent = "No tasks assigned to you for this date. Use “Unplanned work” if needed.";
      return;
    }
    tasks.forEach((t) => {
      const tr = body.insertRow();
      tr.insertCell().textContent = t.task_name;
      tr.insertCell().textContent = `${t.project_code} · ${t.project_name}`;
      const endCell = tr.insertCell();
      endCell.textContent = t.end_date || "—";
      if (t.is_overdue) { const tag = document.createElement("span"); tag.className = "dt-tag red"; tag.textContent = "overdue"; endCell.append(" ", tag); }
      tr.insertCell().textContent = t.status;
      tr.insertCell().textContent = `${fmt(t.hours_used)} / ${fmt(t.budget_hours)} h`;
    });
  }

  function taskSelect(selectedId, isUnplanned) {
    const sel = document.createElement("select");
    sel.className = "e-task";
    (state.tasks || []).forEach((t) => {
      const o = document.createElement("option");
      o.value = String(t.task_id); o.textContent = `${t.project_code} — ${t.task_name}`;
      sel.append(o);
    });
    const u = document.createElement("option");
    u.value = "unplanned"; u.textContent = "Unplanned work";
    sel.append(u);
    sel.value = isUnplanned ? "unplanned" : String(selectedId ?? (state.tasks[0] ? state.tasks[0].task_id : "unplanned"));
    return sel;
  }

  function addRow(e) {
    e = e || {};
    const tr = $("entryBody").insertRow();
    const locked = state.locked;

    const c1 = tr.insertCell();
    const sel = taskSelect(e.task_id, e.is_unplanned);
    const extra = document.createElement("div");           // unplanned reason + optional project code
    extra.className = "e-extra"; extra.style.marginTop = ".4rem";
    const reason = document.createElement("input"); reason.className = "e-reason"; reason.placeholder = "Reason for unplanned work"; reason.maxLength = 500; reason.value = e.unplanned_reason || "";
    const code = document.createElement("input"); code.className = "e-code"; code.placeholder = "Project code (optional)"; code.maxLength = 30; code.value = e.is_unplanned ? e.project_code || "" : ""; code.style.marginTop = ".3rem";
    extra.append(reason, code);
    c1.append(sel, extra);

    const c2 = tr.insertCell();
    const act = document.createElement("input"); act.className = "e-act"; act.maxLength = 1000; act.placeholder = "What I did"; act.value = e.activity || "";
    c2.append(act);

    const c3 = tr.insertCell();
    const hrs = document.createElement("input"); hrs.className = "e-hours"; hrs.type = "number"; hrs.step = "0.25"; hrs.min = "0.25"; hrs.max = "24";
    hrs.value = e.hours === null || e.hours === undefined ? "" : e.hours;
    c3.append(hrs);

    const c4 = tr.insertCell();
    const st = document.createElement("select"); st.className = "e-status";
    [["in_progress", "In progress"], ["done", "Done"], ["blocked", "Blocked"]].forEach(([v, l]) => {
      const o = document.createElement("option"); o.value = v; o.textContent = l; st.append(o);
    });
    st.value = e.task_status || "in_progress";
    c4.append(st);

    const c5 = tr.insertCell();
    const del = document.createElement("button"); del.type = "button"; del.className = "dt-btn del"; del.textContent = "✕";
    del.onclick = () => { tr.remove(); refresh(); };
    c5.append(del);

    [sel, act, hrs, st, reason, code].forEach((el) => { el.disabled = locked; el.addEventListener("input", refresh); });
    del.disabled = locked;
    refresh();
  }

  const rows = () => Array.from($("entryBody").rows);

  // Live totals + which inputs are editable (one entry => hours come from HRMS).
  function refresh() {
    if (!state) return;
    const rs = rows();
    const single = rs.length === 1;
    const net = state.hrms && state.hrms.net !== null && state.hrms.net !== undefined ? state.hrms.net : null;
    let total = 0;
    rs.forEach((tr) => {
      const unplanned = tr.querySelector(".e-task").value === "unplanned";
      tr.querySelector(".e-extra").style.display = unplanned ? "block" : "none";
      const h = tr.querySelector(".e-hours");
      if (single) {
        h.disabled = true;
        h.value = net !== null ? net : "";
        h.placeholder = net !== null ? "" : "awaiting HRMS";
      } else {
        h.disabled = state.locked;
        h.placeholder = "";
      }
      total += Number(h.value) || 0;
    });
    total = Math.round(total * 100) / 100;
    $("tTask").textContent = fmt(total);
    $("tNet").textContent = fmt(net);
    let needReason = false;
    if (net === null || !rs.length || (single && net === null)) {
      $("tDiff").textContent = "—";
      $("tNote").textContent = single && net === null ? "Awaiting HRMS — hours will be filled when attendance is uploaded." :
        (net === null ? "No HRMS data yet — nothing to reconcile." : "");
    } else {
      const diff = Math.round((total - net) * 100) / 100;
      const ok = Math.abs(diff) <= (state.tolerance ?? 0.5);
      const d = $("tDiff");
      d.textContent = (diff > 0 ? "+" : "") + diff;
      d.className = ok ? "dt-ok" : "dt-bad";
      $("tNote").textContent = ok ? "Matched" : (diff < 0 ? "Short — a reason is required" : "Over — a reason is required");
      needReason = !ok;
    }
    $("recoWrap").style.display = needReason ? "block" : "none";
  }

  function collect() {
    return rows().map((tr) => {
      const v = tr.querySelector(".e-task").value;
      const unplanned = v === "unplanned";
      const h = num(tr.querySelector(".e-hours").value);
      return {
        task_id: unplanned ? null : Number(v),
        activity: tr.querySelector(".e-act").value,
        hours: h,
        task_status: tr.querySelector(".e-status").value,
        is_unplanned: unplanned,
        unplanned_reason: unplanned ? tr.querySelector(".e-reason").value : "",
        project_code: unplanned ? (tr.querySelector(".e-code").value.trim() || null) : null,
      };
    });
  }

  function render(p) {
    state = p;
    $("bnNq").style.display = p.nq_data_may_be_stale ? "block" : "none";
    $("cycleInfo").textContent = `Cycle ${p.cycle.label} · fill by ${p.cycle.deadline}`;
    const tag = $("statusTag"); tag.textContent = "";
    const t = document.createElement("span"); t.className = "dt-tag";
    t.textContent = p.locked ? "Locked" : p.submitted ? "Submitted" : "Not submitted";
    tag.append(t);
    const rc = p.reco;
    if (rc && rc.status === "sent_back") banner("Your manager sent this day back: " + (rc.manager_note || "please review your hours"), "err");
    else if (rc && rc.status === "accepted") banner("Your manager accepted the hours for this day.", "ok");
    renderHrms(p.hrms);
    renderTasks(p.tasks);
    $("entryBody").textContent = "";
    if (p.entries.length) p.entries.forEach(addRow);
    $("recoReason").value = p.reco_reason || "";
    $("recoReason").disabled = p.locked;
    $("saveBtn").disabled = $("submitBtn").disabled = $("addRow").disabled = p.locked;
    refresh();
  }

  async function load() {
    banner("");
    try { render(await api("GET", `/timesheet/v2/day/${emp}?date=${day()}`)); }
    catch (err) { banner(err.message, "err"); }
  }

  async function save() {
    return api("PUT", `/timesheet/v2/day/${emp}/${day()}`, { entries: collect() });
  }

  $("dayPicker").value = today();
  $("dayPicker").max = today();
  $("dayPicker").addEventListener("change", load);
  $("addRow").onclick = () => addRow({});
  $("saveBtn").onclick = async () => {
    try { render(await save()); banner("Draft saved", "ok"); } catch (err) { banner(err.message, "err"); }
  };
  $("submitBtn").onclick = async () => {
    try {
      await save();
      const p = await api("POST", `/timesheet/v2/day/${emp}/${day()}/submit`, { reco_reason: $("recoReason").value });
      render(p); banner("Day submitted", "ok");
    } catch (err) { banner(err.message, "err"); }
  };

  (async () => {
    try {
      const en = await api("GET", `/timesheet/v2/enabled/${emp}`);
      if (!en.enabled) { banner("The daily timesheet is not enabled for you yet.", "err"); $("saveBtn").disabled = $("submitBtn").disabled = $("addRow").disabled = true; return; }
      await load();
    } catch (err) { banner(err.message, "err"); }
  })();
})();
