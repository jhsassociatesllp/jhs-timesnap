// static/timesheet/admin.js - Admin setup: payrolls and cycles, working rules, who uses My day, allow changes to a submitted day.
// Talks to /timesheet/v2/admin/*. All server text is inserted with textContent.
(function () {
  "use strict";
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  const B = "/timesheet/v2/admin";
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

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
      const err = new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((m) => m.msg).join("; ") : `Request failed (${res.status})`);
      err.status = res.status; throw err;
    }
    return data;
  }

  const shortDate = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const addDays = (s, n) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };

  function banner(kind, text) {
    const b = h("div", { class: "banner " + kind }, h("span", { text }), h("button", { type: "button", "aria-label": "Dismiss", onclick: () => b.remove(), text: "×" }));
    $("banners").textContent = ""; $("banners").append(b);
    b.scrollIntoView({ block: "nearest" });
  }

  const S = { data: null, hol: [], pilot: [], inc: [], off: [] };

  // ── tabs ───────────────────────────────────────────────────────────────────────────
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tabpane").forEach((p) => { p.hidden = p.id !== "pane-" + b.dataset.tab; });
  });

  // ── modal helper ───────────────────────────────────────────────────────────────────
  let opener = null;
  function openModal(id, from) {
    opener = from || null;
    const m = $(id); m.hidden = false; document.body.classList.add("modal-open");
    const first = m.querySelector("input, textarea, button.btn"); (first || m.querySelector(".modal-box")).focus();
  }
  function closeModals() {
    document.querySelectorAll(".modal").forEach((m) => { m.hidden = true; });
    document.body.classList.remove("modal-open");
    if (opener && document.contains(opener)) opener.focus();
  }
  document.querySelectorAll(".modal").forEach((m) => {
    m.addEventListener("mousedown", (e) => { if (e.target === m) closeModals(); });
    m.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeModals));
  });
  document.addEventListener("keydown", (e) => {
    const open = [...document.querySelectorAll(".modal")].find((m) => !m.hidden);
    if (!open) return;
    if (e.key === "Escape") { closeModals(); return; }
    if (e.key === "Tab") {
      const f = [...open.querySelectorAll("button, textarea, input")].filter((x) => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });

  // ── 1. payrolls and cycles ─────────────────────────────────────────────────────────
  function renderPayrolls() {
    const box = $("payrollList"); box.textContent = "";
    const list = S.data.payrolls;
    if (!list.length) { box.append(h("div", { class: "empty-big" }, h("b", { text: "No payroll has been created yet." }), h("div", { text: "Employees cannot fill their timesheets until you create one. Press “Create payroll”." }))); return; }
    list.forEach((p) => {
      const used = p.cycles.reduce((n, c) => n + c.entries, 0);
      const tbody = h("tbody", {});
      p.cycles.forEach((c) => {
        const cell = h("td", {});
        const show = () => {
          cell.textContent = "";
          cell.append(h("span", { text: `${shortDate(c.deadline)}, 23:59 ` }),
            h("button", { class: "btn tiny", type: "button", "aria-label": `Change the deadline of ${c.label}`, onclick: edit }, h("i", { class: "fas fa-pen" }), " Change"));
        };
        const edit = () => {
          const inp = h("input", { class: "inp", type: "date", value: c.deadline, min: c.end, "aria-label": "New deadline" });
          const msg = h("span", { class: "save-note", role: "alert" });
          cell.textContent = "";
          cell.append(h("span", { class: "dl-edit" }, inp,
            h("button", { class: "btn tiny good", type: "button", onclick: async () => {
              try { await api("PUT", `${B}/payrolls/${p._id}/cycles/${c.id}`, { deadline: inp.value }); c.deadline = inp.value; show(); banner("ok", `Deadline of ${c.label} is now ${shortDate(c.deadline)}.`); }
              catch (err) { msg.textContent = err.message; msg.className = "save-note err"; }
            } }, "Save"),
            h("button", { class: "btn tiny", type: "button", onclick: show }, "Cancel")), msg);
          inp.focus();
        };
        show();
        tbody.append(h("tr", {}, h("td", { text: c.label }), h("td", { text: `${shortDate(c.start)} – ${shortDate(c.end)}` }), cell, h("td", { class: "num", text: String(c.entries) })));
      });
      const del = h("button", { class: "btn tiny danger", type: "button", disabled: used > 0, title: used ? "This payroll already has timesheet data" : "Delete this payroll",
        onclick: async () => {
          if (!confirm(`Delete the payroll ${p.label}? Nobody has filled anything in it yet.`)) return;
          try { await api("DELETE", `${B}/payrolls/${p._id}`); banner("ok", `Deleted the payroll ${p.label}.`); await load(); } catch (err) { banner("err", err.message); }
        } }, h("i", { class: "fas fa-trash" }), " Delete");
      box.append(h("div", { class: "pr" },
        h("div", { class: "pr-head" }, h("div", {}, h("b", { text: `Payroll ${p.label}` }), h("div", { class: "m", text: `Created by ${p.created_by || "—"} · ${used} timesheet row${used === 1 ? "" : "s"} so far` })), del),
        h("div", { class: "table-responsive" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Sub-cycle" }), h("th", { text: "Dates" }), h("th", { text: "Fill by (deadline)" }), h("th", { class: "num", text: "Rows" }))), tbody))));
    });
  }

  // create payroll modal with a live preview of the three sub-cycles
  function monthEndDay(y, m) { return new Date(y, m, 0).getDate(); }            // m is 1-12
  function previewCycles(ym, days) {
    const [y, m] = ym.split("-").map(Number);
    const py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1;
    const defs = [[`${py}-${pad(pm)}-21`, `${py}-${pad(pm)}-${monthEndDay(py, pm)}`], [`${y}-${pad(m)}-01`, `${y}-${pad(m)}-10`], [`${y}-${pad(m)}-11`, `${y}-${pad(m)}-20`]];
    return defs.map(([s, e]) => ({ start: s, end: e, deadline: addDays(e, days) }));
  }
  function renderPreview() {
    const box = $("mpPreview"); box.textContent = "";
    const ym = $("mpMonth").value, days = Number($("mpDays").value);
    if (!/^\d{4}-\d{2}$/.test(ym) || Number.isNaN(days)) return;
    const taken = S.data.payrolls.some((p) => p._id === ym);
    box.append(h("table", { class: "tbl mt" }, h("thead", {}, h("tr", {}, h("th", { text: "Sub-cycle" }), h("th", { text: "Fill by" }))),
      h("tbody", {}, previewCycles(ym, days).map((c) => h("tr", {}, h("td", { text: `${shortDate(c.start)} – ${shortDate(c.end)}` }), h("td", { text: `${shortDate(c.deadline)}, 23:59` }))))));
    if (taken) box.append(h("p", { class: "warn-text", text: "This payroll already exists." }));
    $("mpCreate").disabled = taken;
  }
  $("newPayroll").addEventListener("click", (e) => {
    const now = new Date(); const next = new Date(now.getFullYear(), now.getMonth() + (now.getDate() >= 21 ? 1 : 0), 1);
    $("mpMonth").value = `${next.getFullYear()}-${pad(next.getMonth() + 1)}`;
    $("mpDays").value = S.data.settings.deadline_days; $("mpMsg").textContent = "";
    renderPreview(); openModal("mPayroll", e.currentTarget);
  });
  $("mpMonth").addEventListener("input", renderPreview); $("mpDays").addEventListener("input", renderPreview);
  $("mpCreate").addEventListener("click", async () => {
    $("mpMsg").textContent = "";
    try {
      const r = await api("POST", `${B}/payrolls`, { month: $("mpMonth").value, deadline_days: Number($("mpDays").value) });
      closeModals(); banner("ok", `Created the payroll ${r.label} with three sub-cycles.`); await load();
    } catch (err) { $("mpMsg").textContent = err.message; }
  });

  // ── 2. working rules ───────────────────────────────────────────────────────────────
  function renderRules() {
    const st = S.data.settings;
    $("stdHours").value = st.standard_hours; $("deadlineDays").value = st.deadline_days;
    S.off = [...st.week_off_days]; S.hol = st.holidays.map((x) => ({ ...x }));
    const box = $("weekOff"); box.textContent = "";
    DAYS.forEach((d, i) => {
      const cb = h("input", { type: "checkbox", value: String(i), checked: S.off.includes(i) });
      cb.addEventListener("change", () => { S.off = [...box.querySelectorAll("input:checked")].map((x) => Number(x.value)); dirty("rulesNote"); });
      box.append(h("label", {}, cb, h("span", { text: d })));
    });
    renderHolidays();
  }
  function renderHolidays() {
    const ul = $("holList"); ul.textContent = "";
    S.hol.sort((a, b) => a.date.localeCompare(b.date)).forEach((x, i) => {
      ul.append(h("li", {}, h("span", { text: `${shortDate(x.date)}${x.name ? " · " + x.name : ""}` }),
        h("button", { class: "x", type: "button", "aria-label": "Remove this holiday", onclick: () => { S.hol.splice(i, 1); renderHolidays(); dirty("rulesNote"); } }, "×")));
    });
    if (!S.hol.length) ul.append(h("li", { text: "No holidays added." }));
  }
  function dirty(id) { const n = $(id); n.textContent = "Unsaved changes"; n.className = "save-note"; }
  $("holAdd").addEventListener("click", () => {
    const d = $("holDate").value;
    if (!d) { $("rulesNote").textContent = "Pick the holiday date first."; $("rulesNote").className = "save-note err"; return; }
    if (S.hol.some((x) => x.date === d)) { $("rulesNote").textContent = "That date is already in the list."; $("rulesNote").className = "save-note err"; return; }
    S.hol.push({ date: d, name: $("holName").value.trim() }); $("holDate").value = ""; $("holName").value = "";
    renderHolidays(); dirty("rulesNote");
  });
  ["stdHours", "deadlineDays"].forEach((id) => $(id).addEventListener("input", () => dirty("rulesNote")));
  $("saveRules").addEventListener("click", async () => {
    const n = $("rulesNote");
    try {
      await api("PUT", `${B}/settings`, { standard_hours: Number($("stdHours").value), week_off_days: S.off, deadline_days: Number($("deadlineDays").value), holidays: S.hol });
      n.textContent = "Saved"; n.className = "save-note ok"; await load(false);
    } catch (err) { n.textContent = err.message; n.className = "save-note err"; }
  });

  // ── 3. who uses My day ─────────────────────────────────────────────────────────────
  function chips(listId, arr, onChange) {
    const box = $(listId); box.textContent = "";
    arr.forEach((c, i) => box.append(h("span", { class: "cchip" }, c, h("button", { type: "button", "aria-label": "Remove " + c, onclick: () => { arr.splice(i, 1); chips(listId, arr, onChange); onChange(); } }, "×"))));
  }
  function wireChipInput(inputId, listId, arr) {
    const add = () => {
      const inp = $(inputId);
      let bad = "";
      inp.value.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean).forEach((c) => {
        if (!/^[A-Z0-9_-]{2,20}$/.test(c)) { bad = c; return; }
        if (!arr.includes(c)) arr.push(c);
      });
      inp.value = ""; chips(listId, arr, () => dirty("accessNote"));
      if (bad) { $("accessNote").textContent = `“${bad}” is not a valid employee code.`; $("accessNote").className = "save-note err"; }
      else dirty("accessNote");
    };
    $(inputId).addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } });
    $(inputId).addEventListener("blur", () => { if ($(inputId).value.trim()) add(); });
  }
  function renderAccess() {
    const a = S.data.access;
    S.pilot = [...a.pilot_employees]; S.inc = [...a.include];
    document.querySelectorAll("input[name=scope]").forEach((r) => { r.checked = r.value === a.scope; });
    chips("pilotChips", S.pilot, () => dirty("accessNote")); chips("incChips", S.inc, () => dirty("accessNote"));
    syncScope();
  }
  function syncScope() { const pilot = document.querySelector("input[name=scope]:checked")?.value === "pilot"; $("pilotBox").style.opacity = pilot ? "1" : ".5"; $("pilotIn").disabled = !pilot; }
  document.querySelectorAll("input[name=scope]").forEach((r) => r.addEventListener("change", () => { syncScope(); dirty("accessNote"); }));
  wireChipInput("pilotIn", "pilotChips", S.pilot); wireChipInput("incIn", "incChips", S.inc);
  $("saveAccess").addEventListener("click", async () => {
    const n = $("accessNote");
    try {
      await api("PUT", `${B}/access`, { scope: document.querySelector("input[name=scope]:checked").value, pilot_employees: S.pilot, include: S.inc });
      n.textContent = "Saved"; n.className = "save-note ok"; await load(false);
    } catch (err) { n.textContent = err.message; n.className = "save-note err"; }
  });

  // ── 4. allow changes to a submitted day ────────────────────────────────────────────
  async function findDays() {
    const emp = $("rEmp").value.trim();
    if (!emp) { banner("info", "Type an employee code first."); return; }
    try {
      const d = await api("GET", `${B}/submitted-days?employee=${encodeURIComponent(emp)}&from=${$("rFrom").value}&to=${$("rTo").value}`);
      $("rWho").textContent = `${d.employee_name || d.employee_id} (${d.employee_id}): ${d.days.length} submitted day${d.days.length === 1 ? "" : "s"} in this range`;
      const body = $("rRows"); body.textContent = "";
      if (!d.days.length) body.append(h("tr", {}, h("td", { colspan: "6", class: "empty", text: "No submitted days in this range." })));
      d.days.forEach((x) => {
        const state = x.classic ? "Classic timesheet" : x.reopened ? "Open for changes" : x.cycle_status === "approved" ? "Approved and locked" : "Locked";
        const can = !x.classic && !x.reopened && x.cycle_status !== "approved";
        body.append(h("tr", {}, h("td", { text: shortDate(x.date) }), h("td", { text: x.location || "" }), h("td", { class: "num", text: String(x.hours) }),
          h("td", { text: x.submitted_at ? new Date(x.submitted_at).toLocaleString() : "" }), h("td", { text: state }),
          h("td", {}, can ? h("button", { class: "btn tiny good", type: "button", onclick: (e) => askReopen(d.employee_id, d.employee_name, x.date, e.currentTarget) }, h("i", { class: "fas fa-lock-open" }), " Allow") : null)));
      });
    } catch (err) { banner("err", err.message); }
  }
  $("rFind").addEventListener("click", findDays);
  $("rEmp").addEventListener("keydown", (e) => { if (e.key === "Enter") findDays(); });
  let pending = null;
  function askReopen(emp, name, day, from) {
    pending = { emp, day };
    $("mrSub").textContent = `${name || emp} · ${shortDate(day)}`; $("mrReason").value = ""; $("mrMsg").textContent = "";
    openModal("mReopen", from);
  }
  $("mrOk").addEventListener("click", async () => {
    $("mrMsg").textContent = "";
    if ($("mrReason").value.trim().length < 3) { $("mrMsg").textContent = "Please give a short reason."; return; }
    try {
      await api("POST", `${B}/reopen-day`, { employee_id: pending.emp, date: pending.day, reason: $("mrReason").value.trim() });
      closeModals(); banner("ok", `${pending.emp} can now change ${shortDate(pending.day)} and submit it again.`); await findDays();
    } catch (err) { $("mrMsg").textContent = err.message; }
  });

  // ── load ───────────────────────────────────────────────────────────────────────────
  async function load(all = true) {
    try { S.data = await api("GET", `${B}/overview`); }
    catch (err) { banner(err.status === 403 ? "info" : "err", err.status === 403 ? "Only admins can open this page." : err.message); return; }
    renderPayrolls();
    if (all) { renderRules(); renderAccess(); }
  }
  const today = new Date();
  $("rTo").value = iso(today); $("rFrom").value = iso(new Date(today.getTime() - 29 * 86400000));
  load();
})();
