// static/timesheet/review.js - team lead review of a 10-day cycle: team table, a per-employee modal showing every date,
// task and the hours against what was allotted, then approve (any time) or send back with remarks.
// Talks to /timesheet/v2/cycles/*. All server text is inserted with textContent.
(function () {
  "use strict";

  const emp = (localStorage.getItem("loggedInEmployeeId") || "").trim().toUpperCase();
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
  if (!token || !emp) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

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

  async function api(method, url, body) {
    const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("Please log in again"); }
    if (!res.ok) {
      const d = data && data.detail;
      const err = new Error(typeof d === "string" ? d : (d && d.message) || (Array.isArray(d) ? d.map((m) => m.msg).join("; ") : `Request failed (${res.status})`));
      err.status = res.status; err.detail = d; throw err;
    }
    return data;
  }

  const S = { cycleId: null, data: null, selected: null, admin: false, opener: null };
  const shortDate = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
  const longDate = (s) => new Date(s + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const fmt = (v) => (v == null ? "—" : String(Math.round(v * 100) / 100));

  function banner(kind, text) {
    const b = h("div", { class: "banner " + kind }, h("span", { text }), h("button", { type: "button", "aria-label": "Dismiss", onclick: () => b.remove(), text: "×" }));
    $("banners").textContent = ""; $("banners").append(b);
    b.scrollIntoView({ block: "nearest" });
  }

  // ── cycles the admin created ───────────────────────────────────────────────────────
  async function fillCycles() {
    const sel = $("cycleSel"); sel.textContent = "";
    let info;
    try { info = await api("GET", "/timesheet/v2/cycles/payrolls"); }
    catch (err) { banner(err.status === 403 ? "info" : "err", err.status === 403 ? "This page is for reporting managers and admins." : err.message); return false; }
    if (!info.payrolls.length) {
      sel.append(h("option", { value: "", text: "No payroll has been created yet" }));
      $("cycleInfo").textContent = "An admin has to create a payroll (Admin setup) before timesheets can be reviewed.";
      return false;
    }
    let preferred = null;
    info.payrolls.forEach((p) => {
      const grp = h("optgroup", { label: `Payroll ${p.label}` });
      p.cycles.forEach((c) => {
        grp.append(h("option", { value: c.id, text: `${c.label}${c.current ? " (running)" : c.ended ? "" : " (not started)"}` }));
        if (!preferred && c.current) preferred = c.id;
      });
      sel.append(grp);
    });
    if (!preferred) {                          // no running cycle: the most recent one that has ended
      const ended = info.payrolls.flatMap((p) => p.cycles).filter((c) => c.ended).sort((a, b) => b.end.localeCompare(a.end));
      preferred = ended.length ? ended[0].id : sel.querySelector("option").value;
    }
    sel.value = preferred;
    return true;
  }

  const STATUS_TEXT = { pending: "Pending", approved: "Approved", sent_back: "Sent back", reopened: "Reopened" };
  function statusBadge(r) {
    if (r.status === "sent_back" && r.resubmitted) return h("span", { class: "badge resub", text: "Resubmitted" });
    return h("span", { class: "badge " + r.status, text: STATUS_TEXT[r.status] || r.status });
  }

  // ── team table ─────────────────────────────────────────────────────────────────────
  async function load() {
    S.cycleId = $("cycleSel").value;
    if (!S.cycleId) { $("rows").textContent = ""; return; }
    const mgr = S.admin ? $("team").value.trim() : "";
    try {
      const data = await api("GET", `/timesheet/v2/cycles/${S.cycleId}/team${mgr ? "?manager=" + encodeURIComponent(mgr) : ""}`);
      S.data = data; S.admin = data.is_admin; $("teamWrap").hidden = !S.admin;
    } catch (err) {
      S.data = null; $("rows").textContent = ""; $("cycleInfo").textContent = "";
      banner(err.status === 403 ? "info" : "err", err.status === 403 ? "This page is for reporting managers and admins." : err.message);
      return;
    }
    renderTeam();
  }

  function renderTeam() {
    const c = S.data.cycle;
    $("cycleInfo").textContent = `Cycle ${c.label} · employees fill by ${shortDate(c.deadline)}${c.past_deadline ? " (closed)" : ""}`;
    const body = $("rows"); body.textContent = "";
    $("confirmWrap").hidden = true; $("confirm").checked = false;
    if (!S.data.rows.length) body.append(h("tr", {}, h("td", { colspan: "8", class: "empty", text: "No employees on the daily timesheet in this team yet." })));
    S.data.rows.forEach((r) => {
      const cb = h("input", { type: "checkbox", "data-emp": r.employee_id, "aria-label": "Select " + r.employee_id, disabled: r.status === "approved" });
      body.append(h("tr", {},
        h("td", {}, cb),
        h("td", {}, h("button", { class: "who", type: "button", onclick: (e) => openModal(r.employee_id, e.currentTarget) }, r.employee_name || r.employee_id),
          h("div", { class: "cap", text: r.employee_id })),
        h("td", { class: "num", text: `${r.days_filled} / ${r.days_required}` }),
        h("td", { class: "num hide-s", text: fmt(r.timesheet_hours) }),
        h("td", { class: "num hide-s", text: String(r.unplanned) }),
        h("td", {}, statusBadge(r), r.mirror === "error" ? h("div", { class: "warn-text", text: "Copy to classic reports failed" }) : null),
        h("td", { class: "hide-s" }, r.warnings.length ? h("span", { class: "warn-text", text: r.warnings.join("; ") }) : "—"),
        h("td", {}, h("button", { class: "btn small", type: "button", onclick: (e) => openModal(r.employee_id, e.currentTarget) }, "Review"))));
    });
  }

  $("all").addEventListener("change", () => document.querySelectorAll("#rows input[type=checkbox]:not(:disabled)").forEach((c) => { c.checked = $("all").checked; }));
  const selectedIds = () => [...document.querySelectorAll("#rows input[type=checkbox]:checked")].map((c) => c.getAttribute("data-emp"));

  // approve one or many; `where` says where to show the answer (the page or the modal)
  async function approve(ids, note, where) {
    if (!ids.length) { banner("info", "Select at least one employee."); return false; }
    try {
      const r = await api("POST", `/timesheet/v2/cycles/${S.cycleId}/approve`, { employee_ids: ids, confirm_warnings: !!(where && where.confirmed) || $("confirm").checked, note: note || "" });
      closeModal();
      banner(r.mirror_failed.length ? "warn" : "ok", `Approved and locked: ${r.approved.join(", ")}.` +
        (r.mirror_failed.length ? ` The copy to the classic reports failed for ${r.mirror_failed.join(", ")} - ask an admin to re-run it.` : ""));
      await load();
      return true;
    } catch (err) {
      if (err.status === 409 && err.detail && err.detail.warnings) {
        const lines = Object.entries(err.detail.warnings).map(([e, w]) => `${e}: ${w.join(", ")}`).join(" | ");
        if (where && where.modal) {
          where.modal(lines);
        } else {
          $("confirmText").textContent = `Please check before approving (${lines}). Tick here and press Approve again to approve anyway.`;
          $("confirmWrap").hidden = false;
        }
      } else if (where && where.error) where.error(err.message); else banner("err", err.message);
      return false;
    }
  }
  $("approveBtn").addEventListener("click", () => approve(selectedIds(), "", null));

  // ── the review modal ───────────────────────────────────────────────────────────────
  const VERDICT = {
    completed_within: ["Completed within allotted hours", "ok"],
    completed_over: ["Completed, over the allotted hours", "bad"],
    in_progress_within: ["In progress, within allotted hours", "info"],
    in_progress_over: ["In progress, over the allotted hours", "warn"],
    unplanned: ["Unplanned work", "unp"],
    unknown: ["Allotted hours not available", "none"],
  };
  const STATUS_LABEL = { done: "Done", in_progress: "In progress", blocked: "Blocked" };

  function verdictBadge(v) { const [t, k] = VERDICT[v] || VERDICT.unknown; return h("span", { class: "vb " + k, text: t }); }

  function openModal(id, opener) {
    S.selected = id; S.opener = opener || null;
    $("mTitle").textContent = "Loading…"; $("mSub").textContent = ""; $("mBody").textContent = "";
    $("rvModal").hidden = false; document.body.classList.add("modal-open");
    $("mBox").focus();
    renderModal(id);
  }

  function closeModal() {
    $("rvModal").hidden = true; document.body.classList.remove("modal-open");
    if (S.opener && document.contains(S.opener)) S.opener.focus();
  }
  $("mClose").addEventListener("click", closeModal);
  $("rvModal").addEventListener("mousedown", (e) => { if (e.target === $("rvModal")) closeModal(); });
  document.addEventListener("keydown", (e) => {
    if ($("rvModal").hidden) return;
    if (e.key === "Escape") { closeModal(); return; }
    if (e.key === "Tab") {                                   // keep focus inside the dialog
      const f = [...$("mBox").querySelectorAll("button, textarea, input, [href]")].filter((x) => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  async function renderModal(id) {
    let d;
    try { d = await api("GET", `/timesheet/v2/cycles/${S.cycleId}/employee/${id}`); }
    catch (err) { $("mTitle").textContent = "Could not load"; $("mBody").append(h("div", { class: "empty", text: err.message })); return; }
    const row = d.employee, body = $("mBody");
    $("mTitle").textContent = `${row.employee_name || id} (${id})`;
    $("mSub").textContent = `Cycle ${d.cycle.label} · ${fmt(row.timesheet_hours)} h entered · ${row.days_filled} of ${row.days_required} days filled`;
    body.textContent = "";
    body.append(h("div", { class: "m-status" }, statusBadge(row)));
    if (row.note) body.append(h("div", { class: "banner warn" }, h("span", { text: "Sent back: " + row.note + (row.resubmitted ? " (the employee has resubmitted)" : "") })));
    if (d.nq_unavailable) body.append(h("div", { class: "banner warn" }, h("span", { text: "Project data from Nexus Quant is unavailable, so the allotted hours cannot be shown right now." })));

    const off = d.rules.week_off_days.map((n) => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][n]).join(" & ");
    body.append(h("p", { class: "m-rule" }, h("i", { class: "fas fa-circle-info" }),
      ` Allotted hours = the working days between a task's start and end date in Nexus Quant × ${fmt(d.rules.standard_hours)} hours a day, leaving out ${off} and holidays.`));

    // summary of the cycle's tasks
    const s = d.summary;
    body.append(h("div", { class: "m-sum" },
      sumChip("completed_within", s.completed_within), sumChip("completed_over", s.completed_over),
      sumChip("in_progress_within", s.in_progress_within), sumChip("in_progress_over", s.in_progress_over),
      sumChip("unplanned", s.unplanned), s.unknown ? sumChip("unknown", s.unknown) : null));

    // the table: one block per date, one row per task
    const tbody = h("tbody", {});
    d.days.forEach((day) => {
      const entries = day.entries;
      const dayOff = day.location && ["Leave", "Week Off", "PHY"].includes(day.location);
      if (!entries.length) {
        if (day.state === "missing") tbody.append(h("tr", { class: "r-missing" }, h("td", { class: "dc", text: longDate(day.date) }), h("td", { colspan: "5", text: "Not submitted" })));
        else if (dayOff) tbody.append(h("tr", { class: "r-off" }, h("td", { class: "dc", text: longDate(day.date) }), h("td", { colspan: "5", text: `Day off: ${day.location}` })));
        else if (day.holiday != null) tbody.append(h("tr", { class: "r-off" }, h("td", { class: "dc", text: longDate(day.date) }), h("td", { colspan: "5", text: "Holiday" + (day.holiday ? `: ${day.holiday}` : "") })));
        return;
      }
      entries.forEach((e, i) => {
        const task = h("td", {},
          h("div", { class: "tn", text: e.is_unplanned || e.task_id == null ? "Unplanned work" : e.task_name }),
          h("div", { class: "m", text: [e.client, e.project, e.project_code].filter(Boolean).join(" › ") }),
          e.task_status ? h("span", { class: "sc " + e.task_status, text: STATUS_LABEL[e.task_status] || e.task_status }) : null,
          e.remarks ? h("div", { class: "w", text: "What I did: " + e.remarks }) : null,
          e.extra_remarks ? h("div", { class: "w", text: "Remarks: " + e.extra_remarks }) : null);
        const first = i === 0;
        tbody.append(h("tr", { class: e.verdict === "completed_over" || e.verdict === "in_progress_over" ? "r-over" : "" },
          first ? h("td", { class: "dc", rowspan: String(entries.length) }, longDate(day.date), h("div", { class: "m", text: `${day.location || ""}${day.state === "saved" ? " · not submitted" : ""}` }), h("div", { class: "m", text: `${fmt(day.hours)} h` })) : null,
          task,
          h("td", { class: "num", text: fmt(e.hours) }),
          h("td", { class: "num", text: e.task_id == null ? "—" : fmt(e.total_on_task) }),
          h("td", { class: "num" }, e.allotted_hours == null ? "—" : fmt(e.allotted_hours),
            e.allotted_days != null ? h("div", { class: "m", text: `${e.allotted_days} working day${e.allotted_days === 1 ? "" : "s"}` }) : null,
            e.task_start ? h("div", { class: "m", text: `${shortDate(e.task_start)} – ${shortDate(e.task_end)}` }) : null),
          h("td", {}, verdictBadge(e.verdict))));
      });
    });
    body.append(h("div", { class: "table-responsive" }, h("table", { class: "tbl mt" },
      h("thead", {}, h("tr", {}, h("th", { text: "Date" }), h("th", { text: "Task and what was done" }), h("th", { class: "num", text: "Hours that day" }),
        h("th", { class: "num", text: "Total on task" }), h("th", { class: "num", text: "Allotted" }), h("th", { text: "Result" }))),
      tbody)));

    // the decision
    const decision = h("div", { class: "m-decision" });
    if (row.status !== "approved") {
      const note = h("textarea", { class: "inp", maxlength: "500", placeholder: "Remarks for the employee (optional when approving, required when sending back)", "aria-label": "Remarks for the employee" });
      const msg = h("div", { class: "m-msg", role: "alert" });
      const approveBtn = h("button", { class: "btn good", type: "button" }, h("i", { class: "fas fa-lock" }), " Approve & lock");
      const sendBtn = h("button", { class: "btn", type: "button" }, h("i", { class: "fas fa-rotate-left" }), " Send back with remarks");
      let confirmed = false;
      approveBtn.addEventListener("click", async () => {
        msg.textContent = "";
        await approve([id], note.value.trim(), {
          confirmed, error: (t) => { msg.textContent = t; },
          modal: (lines) => { confirmed = true; msg.textContent = `Please check: ${lines}. Press Approve & lock again to approve anyway.`; approveBtn.lastChild.textContent = " Approve anyway"; },
        });
      });
      sendBtn.addEventListener("click", async () => {
        msg.textContent = "";
        if (note.value.trim().length < 3) { msg.textContent = "Write a short remark so the employee knows what to fix."; note.focus(); return; }
        try { await api("POST", `/timesheet/v2/cycles/${S.cycleId}/send-back`, { employee_id: id, note: note.value.trim() }); closeModal(); banner("ok", "Sent back to " + id + "."); await load(); }
        catch (err) { msg.textContent = err.message; }
      });
      decision.append(h("h3", { class: "rv-h", text: "Your decision" }), note, msg, h("div", { class: "rv-actions" }, approveBtn, sendBtn));
    } else if (S.admin) {
      decision.append(h("div", { class: "rv-actions" }, h("button", { class: "btn small", type: "button", onclick: async () => {
        const reason = prompt("Why are you unlocking this approved cycle? (shown in the audit trail)");
        if (!reason || reason.trim().length < 3) return;
        try { await api("POST", `/timesheet/v2/cycles/${S.cycleId}/unlock`, { employee_id: id, reason: reason.trim() }); closeModal(); banner("ok", "Unlocked " + id + "."); await load(); }
        catch (err) { banner("err", err.message); }
      } }, "Unlock this cycle (admin)")));
    }
    body.append(decision);
    if (d.history.length) body.append(h("ul", { class: "hist" }, d.history.map((x) => h("li", { text: `${x.action.replace("_", " ")} by ${x.by}${x.note ? ": " + x.note : ""}` }))));
  }

  function sumChip(kind, n) { const [t, k] = VERDICT[kind]; return h("span", { class: "chipv " + k }, h("b", { text: String(n) }), " ", t); }

  $("go").addEventListener("click", () => { $("banners").textContent = ""; load(); });
  $("cycleSel").addEventListener("change", () => { $("banners").textContent = ""; load(); });
  (async () => { if (await fillCycles()) await load(); })();
})();
