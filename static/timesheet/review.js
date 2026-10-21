// static/timesheet/review.js - manager review of 10-day cycles: approve and lock, send back with a note.
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

  const S = { cycleId: null, data: null, selected: null, admin: false };
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const shortDate = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
  const fmt = (v) => (v == null ? "—" : String(Math.round(v * 100) / 100));

  function cycleIdFor(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-C${d.getDate() <= 10 ? 1 : d.getDate() <= 20 ? 2 : 3}`; }
  function cycleStart(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() <= 10 ? 1 : d.getDate() <= 20 ? 11 : 21); }
  function cycleEnd(d) { return d.getDate() <= 10 ? new Date(d.getFullYear(), d.getMonth(), 10) : d.getDate() <= 20 ? new Date(d.getFullYear(), d.getMonth(), 20) : new Date(d.getFullYear(), d.getMonth() + 1, 0); }

  function banner(kind, text) {
    const b = h("div", { class: "banner " + kind }, h("span", { text }), h("button", { type: "button", "aria-label": "Dismiss", onclick: () => b.remove(), text: "×" }));
    $("banners").textContent = ""; $("banners").append(b);
  }

  function fillCycles() {
    const sel = $("cycleSel"); sel.textContent = "";
    let d = new Date(); const today = new Date(); today.setHours(0, 0, 0, 0);
    const list = [];
    for (let i = 0; i < 9; i++) {
      const s = cycleStart(d), e = cycleEnd(d);
      list.push({ id: cycleIdFor(d), start: s, end: e, ended: e < today });
      d = new Date(s); d.setDate(d.getDate() - 1);
    }
    list.forEach((c) => sel.append(h("option", { value: c.id, text: `${shortDate(iso(c.start))} – ${shortDate(iso(c.end))} ${c.start.getFullYear()}${c.ended ? "" : " (running)"}` })));
    const firstEnded = list.find((c) => c.ended) || list[0];
    sel.value = firstEnded.id;
  }

  const STATUS_TEXT = { pending: "Pending", approved: "Approved", sent_back: "Sent back", reopened: "Reopened" };
  function statusBadge(r) {
    if (r.status === "sent_back" && r.resubmitted) return h("span", { class: "badge resub", text: "Resubmitted" });
    return h("span", { class: "badge " + r.status, text: STATUS_TEXT[r.status] || r.status });
  }

  async function load() {
    S.cycleId = $("cycleSel").value;
    const mgr = S.admin ? $("team").value.trim() : "";
    $("banners").textContent = "";
    try {
      const data = await api("GET", `/timesheet/v2/cycles/${S.cycleId}/team${mgr ? "?manager=" + encodeURIComponent(mgr) : ""}`);
      S.data = data; S.admin = data.is_admin; $("teamWrap").hidden = !S.admin;
    } catch (err) {
      S.data = null; $("rows").textContent = "";
      $("cycleInfo").textContent = "";
      banner(err.status === 403 ? "info" : "err", err.status === 403 ? "This page is for reporting managers and admins." : err.message);
      return;
    }
    renderTeam();
    if (S.selected && S.data.rows.some((r) => r.employee_id === S.selected)) openDetail(S.selected); else { S.selected = null; $("detail").textContent = ""; $("detail").append(h("div", { class: "empty", text: "Click an employee to see their days." })); }
  }

  function ended() { return S.data && new Date(S.data.cycle.end + "T00:00:00") < new Date(new Date().toDateString()); }

  function renderTeam() {
    const c = S.data.cycle;
    $("cycleInfo").textContent = `Cycle ${c.label} · employees fill by ${shortDate(c.deadline)}${c.past_deadline ? " (closed)" : ""}` +
      (ended() ? "" : " · you can approve once the cycle has ended");
    const body = $("rows"); body.textContent = "";
    $("confirmWrap").hidden = true; $("confirm").checked = false;
    if (!S.data.rows.length) body.append(h("tr", {}, h("td", { colspan: "7", class: "empty", text: "No employees on the daily timesheet in this team yet." })));
    S.data.rows.forEach((r) => {
      const cb = h("input", { type: "checkbox", "data-emp": r.employee_id, "aria-label": "Select " + r.employee_id, disabled: r.status === "approved" });
      body.append(h("tr", { class: S.selected === r.employee_id ? "sel" : "" },
        h("td", {}, cb),
        h("td", {}, h("button", { class: "who", type: "button", onclick: () => openDetail(r.employee_id) }, r.employee_name || r.employee_id),
          h("div", { class: "cap", text: r.employee_id })),
        h("td", { class: "num", text: `${r.days_filled} / ${r.days_required}` }),
        h("td", { class: "num hide-s", text: fmt(r.timesheet_hours) }),
        h("td", { class: "num hide-s", text: String(r.unplanned) }),
        h("td", {}, statusBadge(r), r.mirror === "error" ? h("div", { class: "warn-text", text: "Copy to classic reports failed" }) : null),
        h("td", { class: "hide-s" }, r.warnings.length ? h("span", { class: "warn-text", text: r.warnings.join("; ") }) : "—")));
    });
    $("approveBtn").disabled = !ended();
  }

  $("all").addEventListener("change", () => document.querySelectorAll("#rows input[type=checkbox]:not(:disabled)").forEach((c) => { c.checked = $("all").checked; }));

  function selectedIds() { return [...document.querySelectorAll("#rows input[type=checkbox]:checked")].map((c) => c.getAttribute("data-emp")); }

  async function approve(ids) {
    if (!ids.length) { banner("info", "Select at least one employee."); return; }
    const confirmed = $("confirm").checked;
    try {
      const r = await api("POST", `/timesheet/v2/cycles/${S.cycleId}/approve`, { employee_ids: ids, confirm_warnings: confirmed });
      banner(r.mirror_failed.length ? "warn" : "ok", `Approved and locked: ${r.approved.join(", ")}.` +
        (r.mirror_failed.length ? ` The copy to the classic reports failed for ${r.mirror_failed.join(", ")} - ask an admin to re-run it.` : ""));
      await load();
    } catch (err) {
      if (err.status === 409 && err.detail && err.detail.warnings) {
        const lines = Object.entries(err.detail.warnings).map(([e, w]) => `${e}: ${w.join(", ")}`).join(" | ");
        $("confirmText").textContent = `Some days are still open (${lines}). Tick here and press Approve again to approve anyway.`;
        $("confirmWrap").hidden = false;
      } else banner("err", err.message);
    }
  }
  $("approveBtn").addEventListener("click", () => approve(selectedIds()));

  async function openDetail(id) {
    S.selected = id;
    document.querySelectorAll("#rows tr").forEach((tr) => tr.classList.toggle("sel", !!tr.querySelector(`[data-emp="${id}"]`)));
    const box = $("detail"); box.textContent = ""; box.append(h("div", { class: "empty", text: "Loading…" }));
    let d;
    try { d = await api("GET", `/timesheet/v2/cycles/${S.cycleId}/employee/${id}`); } catch (err) { box.textContent = ""; box.append(h("div", { class: "empty", text: err.message })); return; }
    const row = d.employee;
    box.textContent = "";
    box.append(h("h2", { text: row.employee_name || id }),
      h("p", { class: "sub", text: `${shortDate(d.cycle.start)} – ${shortDate(d.cycle.end)} · ${fmt(row.timesheet_hours)} h · ` }, statusBadge(row)));
    if (row.note) box.append(h("div", { class: "banner warn" }, h("span", { text: "Sent back: " + row.note + (row.resubmitted ? " (the employee has resubmitted)" : "") })));
    d.days.forEach((day) => {
      if (day.state === "none" && !day.entries.length && !day.location) return;
      const entries = day.entries.map((e) => h("div", { class: "er" + (e.is_unplanned ? " unplanned" : "") },
        h("div", { text: `${e.is_unplanned ? "Unplanned work" : (e.task_name || "—")} · ${e.hours == null ? "—" : e.hours + " h"}${e.task_status ? " · " + e.task_status.replace("_", " ") : ""}` }),
        h("div", { class: "m", text: [e.client, e.project, e.project_code].filter(Boolean).join(" › ") + (e.remarks ? " — " + e.remarks : "") })));
      box.append(h("div", { class: "dayrow" + (day.state === "missing" ? " missing" : "") },
        h("div", {}, h("div", { class: "d", text: `${day.weekday} ${shortDate(day.date)}` }), h("div", { class: "loc", text: day.state === "missing" ? "Not submitted" : (day.location || "") + (day.state === "saved" ? " · saved, not submitted" : "") })),
        h("div", {}, entries.length ? entries : (day.location && ["Leave", "Week Off", "PHY"].includes(day.location) ? h("span", { class: "m", text: "Day off" }) : null)),
        h("div", { class: "num", text: day.hours ? fmt(day.hours) : "" })));
    });
    if (row.status !== "approved") {
      const note = h("textarea", { class: "inp", maxlength: "500", placeholder: "What should the employee fix? (required)", "aria-label": "Note to the employee" });
      box.append(h("div", { class: "rv-actions" },
        h("button", { class: "btn primary small", type: "button", disabled: !ended(), onclick: () => approve([id]) }, "Approve & lock"),
      ), h("div", { style: "margin-top:14px" }, note,
        h("div", { class: "rv-actions" }, h("button", { class: "btn small", type: "button", disabled: !ended(), onclick: async () => {
          if (note.value.trim().length < 3) { banner("info", "Write a short note so the employee knows what to fix."); return; }
          try { await api("POST", `/timesheet/v2/cycles/${S.cycleId}/send-back`, { employee_id: id, note: note.value.trim() }); banner("ok", "Sent back to " + id + "."); await load(); }
          catch (err) { banner("err", err.message); }
        } }, "Send back with note"))));
    } else if (S.admin) {
      box.append(h("div", { class: "rv-actions" }, h("button", { class: "btn small", type: "button", onclick: async () => {
        const reason = prompt("Why are you unlocking this approved cycle? (shown in the audit trail)");
        if (!reason || reason.trim().length < 3) return;
        try { await api("POST", `/timesheet/v2/cycles/${S.cycleId}/unlock`, { employee_id: id, reason: reason.trim() }); banner("ok", "Unlocked " + id + "."); await load(); }
        catch (err) { banner("err", err.message); }
      } }, "Unlock (admin)")));
    }
    if (d.history.length) box.append(h("ul", { class: "hist" }, d.history.map((x) => h("li", { text: `${x.action.replace("_", " ")} by ${x.by}${x.note ? ": " + x.note : ""}` }))));
  }

  $("go").addEventListener("click", load);
  $("cycleSel").addEventListener("change", load);
  fillCycles();
  load();
})();
